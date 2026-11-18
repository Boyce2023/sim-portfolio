#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
fast_26q4_special_today.py — 当季科学专供版（09:26 唯一挂单 + 滚动夏普把握度择优）实盘决策引擎
------------------------------------------------------------------------------------------------
核心原理（2026-11-16 零前视验证与8项防过拟合定版）：
  1. 底层个股打分与门槛 100% 锁死五年基础版（高标首阴 V5.1 满88分、三进四 V4.0 满90分、一进二 V19 满304.8/329.8分），零微观凑数改分。
  2. 计算当季滚动把握度 rk_prio = (得分 - 门槛)/历史标准差 + 当季50/50贝叶斯滚动夏普（近10笔触发样本收缩）。
  3. 严守盘前 09:26 唯一 1 笔挂单物理约束：常态严格按主战顺位选唯一头名，仅当低顺位 rk_prio 领先高顺位满 1.50 以上时越级挂单。
------------------------------------------------------------------------------------------------
"""
import os, sys, json, time, argparse, urllib.request
from collections import defaultdict
import numpy as np
import pandas as pd

os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
DATA_DIR = f"{SIM}/data"

CACHE_HD = f"{DATA_DIR}/high_dragon_premarket_cache.json"
CACHE_34 = f"{DATA_DIR}/3to4_premarket_cache.json"
CACHE_12 = f"{DATA_DIR}/1to2_premarket_cache.json"
STATE_SR = f"{DATA_DIR}/seasonal_rolling_sr_state.json"

def load_sr_state() -> dict:
    if os.path.exists(STATE_SR):
        try:
            return json.load(open(STATE_SR, "r", encoding="utf-8"))
        except Exception:
            pass
    return {
        "as_of_date": "2026-11-16",
        "train_stds_2021_2025": {"高标首阴_V51": 14.9334, "三进四_V34": 6.8491, "一进二_V18": 26.1185},
        "blended_seasonal_sr": {"高标首阴_V51": 0.9884, "三进四_V34": 0.5335, "一进二_V18": 0.5552},
    }

sys.path.insert(0, f"{SIM}/scripts")
from live_3to4_v40_engine import score_single_3to4_v40_row as score_single_3to4_row
from fast_2to3_today import evaluate_2to3_candidate
from fast_1to2_today import evaluate_1to2_v19_df

def fetch_tencent_quotes(codes: list[str]) -> dict[str, dict]:
    """并发/批量拉取腾讯实时行情"""
    if not codes:
        return {}
    qmap = {}
    clist = sorted(set(codes))
    batch_size = 80
    for i in range(0, len(clist), batch_size):
        chunk = clist[i:i + batch_size]
        q_codes = [f"{'sh' if c.startswith('6') else 'sz'}{c}" for c in chunk]
        url = f"http://qt.gtimg.cn/q={','.join(q_codes)}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                content = resp.read().decode("gbk", errors="ignore")
                for line in content.strip().split(";"):
                    if "~" not in line:
                        continue
                    parts = line.split("~")
                    if len(parts) > 38:
                        c6 = parts[2].strip()
                        nm = parts[1].strip()
                        px = float(parts[3] or 0.0)
                        pc = float(parts[4] or 0.0)
                        op = float(parts[5] or 0.0)
                        hi = float(parts[33] or 0.0)
                        lo = float(parts[34] or 0.0)
                        amt_yi = float(parts[37] or 0.0) / 10000.0
                        b1_v = float(parts[10] or 0.0) if len(parts) > 10 else 0.0
                        s1_v = float(parts[20] or 0.0) if len(parts) > 20 else 0.0
                        dt8 = str(parts[30]).strip()[:8] if len(parts) > 30 else ""
                        q_dt = f"{dt8[:4]}-{dt8[4:6]}-{dt8[6:8]}" if len(dt8) == 8 and dt8.isdigit() else ""
                        op_px = op if op > 0.0 else px
                        op_pct = (op_px / pc - 1.0) if pc > 0 else 0.0
                        cur_pct = (px / pc - 1.0) if pc > 0 else 0.0
                        zt_px = np.floor(pc * 1.10 * 100.0 + 0.5) / 100.0 if pc > 0 else 999.0
                        is_yz = bool(op_px >= zt_px - 0.011 or (b1_v > 0 and s1_v == 0 and op_pct >= 0.090))
                        qmap[c6] = {
                            "code": c6, "name": nm, "price": px, "pre_c": pc,
                            "open": op_px, "open_pct": op_pct, "cur_pct": cur_pct,
                            "high": hi, "low": lo, "amt_yi": amt_yi, "zt_px": zt_px,
                            "is_yizi": is_yz, "q_dt": q_dt,
                        }
        except Exception as e:
            print(f"[WARN] fetch_tencent_quotes error: {e}", file=sys.stderr)
    return qmap

def evaluate_high_dragon_26q4(cache: dict, quotes: dict, sr_state: dict) -> list[dict]:
    """高标首阴（锁死 V5.1 基础分满88分 + 当季滚动把握度）"""
    cands = cache.get("candidates", [])
    sig_hd = cache.get("as_of_d1", "")
    std_hd = float(sr_state["train_stds_2021_2025"]["高标首阴_V51"])
    bsr_hd = float(sr_state["blended_seasonal_sr"]["高标首阴_V51"])
    results = []
    for r in cands:
        c6 = r["code"]
        q = quotes.get(c6, {})
        is_live_hd = (not sig_hd) or (q.get("q_dt", "") > sig_hd)
        op_pct = q.get("open_pct", 0.0) if is_live_hd else 0.0
        open_px = q.get("open", r.get("close_d1", 0.0)) if is_live_hd else 0.0
        cur_px = q.get("price", open_px)
        veto_list = list(r.get("veto_reasons", []))
        if not is_live_hd:
            veto_list.append("盘后待明日09:25竞价")
        else:
            if op_pct > 0.045: veto_list.append("竞价超涨>4.5%")
            if op_pct < -0.065: veto_list.append("竞价核按钮<-6.5%")
            if q.get("is_yizi", False): veto_list.append("一字不可买")
        is_vetoed = bool(r.get("is_vetoed", False)) or bool(veto_list)
        static_score = int(r.get("static_score", 60))

        score_v51 = static_score + (8 if op_pct < 0.0 else (6 if op_pct <= 0.025 else 0)) if not is_vetoed else -999
        is_passed = (score_v51 >= 88) and (not is_vetoed)
        is_direct = (0.0 <= op_pct <= 0.045)
        trig_px = round(open_px, 2) if is_direct else round(open_px * 1.015, 2)
        ord_type = "09:26 开盘直买（卖五价扫入）" if is_direct else "09:26 突破条件单（今开*1.015，11:30未触发撤单）"
        rk_prio = round((score_v51 - 88.0) / std_hd + bsr_hd, 3) if is_passed else -999.0
        results.append({
            "strategy": "高标首阴 V5.1",
            "priority": 2,
            "code": c6,
            "name": r.get("name", q.get("name", c6)),
            "streak_d0": r.get("streak_d0", 4),
            "static_score": static_score,
            "score_base": score_v51,
            "score_q4": score_v51,
            "rk_prio": rk_prio,
            "threshold": 88,
            "is_passed": is_passed,
            "is_direct_open": is_direct,
            "open_px": open_px,
            "open_pct": op_pct,
            "cur_px": cur_px,
            "cur_pct": q.get("cur_pct", 0.0),
            "is_vetoed": is_vetoed,
            "veto_reasons": veto_list,
            "order_type": ord_type,
            "trigger_px": trig_px,
        })
    results.sort(key=lambda x: (-x["rk_prio"], -x["score_base"]))
    return results

def evaluate_3to4_26q4(cache: dict, quotes: dict, sr_state: dict) -> list[dict]:
    """三进四（锁死 V4.0 基础分满90分 + 当季滚动把握度，10:30撤单窗）"""
    env = cache.get("env", {})
    cands = cache.get("candidates", [])
    d3_str = cache.get("d3_date", "")
    stds = sr_state["train_stds_2021_2025"]
    bsrs = sr_state["blended_seasonal_sr"]
    std_34 = float(stds.get("三进四_V40") or stds.get("三进四_V34", 6.8491))
    bsr_34 = float(bsrs.get("三进四_V40") or bsrs.get("三进四_V34", 0.5335))
    open_3b = [
        (r["code"], quotes.get(r["code"], {}).get("open_pct", -1.0),
         ((not d3_str) or quotes.get(r["code"], {}).get("q_dt", "") > d3_str) and quotes.get(r["code"], {}).get("open", 0) < r["px_d3"] * 1.095)
        for r in cands
    ]
    buy_3b = [x for x in open_3b if x[2]]
    top1_c = max(buy_3b, key=lambda x: x[1])[0] if buy_3b else ""

    results = []
    for r in cands:
        c6 = r["code"]
        q = quotes.get(c6, {})
        is_live_34 = (not d3_str) or (q.get("q_dt", "") > d3_str)
        op_pct = q.get("open_pct", 0.0) if is_live_34 else 0.0
        open_px = q.get("open", r["px_d3"] * 1.055) if is_live_34 else 0.0
        fb_ops = [quotes.get(fc, {}) for fc in r.get("plate_fb_codes", []) if fc in quotes and ((not d3_str) or quotes.get(fc, {}).get("q_dt", "") > d3_str)]
        zt_ops = [quotes.get(zc, {}).get("open_pct", 0.0) for zc in r.get("plate_zt_codes", []) if zc in quotes and ((not d3_str) or quotes.get(zc, {}).get("q_dt", "") > d3_str)]

        row = dict(r, **env)
        row["open_pct"] = op_pct
        row["buyable_open"] = bool(is_live_34 and open_px > 0 and open_px < q.get("zt_px", r["px_d3"] * 1.10) - 0.005)
        row["is_top1_3b_open"] = (c6 == top1_c) if is_live_34 else False
        row["plate_fb_ho_cnt"] = sum(1 for x in fb_ops if 0.03 <= x.get("open_pct", 0) < 0.095)
        row["plate_fb_yz_cnt"] = sum(1 for x in fb_ops if x.get("open_pct", 0) >= 0.095)
        row["plate_peers_open_avg"] = float(np.mean(zt_ops)) if zt_ops else 0.0

        res_v40 = score_single_3to4_row(row)
        sc_v40 = res_v40["score"] if (is_live_34 and res_v40["passed_skeleton"]) else -999
        is_passed = (sc_v40 >= 90) and res_v40["passed_skeleton"] and is_live_34
        rk_prio = round((sc_v40 - 90.0) / std_34 + bsr_34, 3) if is_passed else -999.0
        trig_px = max(round(r["px_d3"] * 1.065, 2), round(open_px, 2)) if is_live_34 else round(r["px_d3"] * 1.065, 2)
        results.append({
            "strategy": "三进四 V4.0",
            "priority": 1,
            "code": c6,
            "name": r.get("name", q.get("name", c6)),
            "px_d3": r["px_d3"],
            "score_base": sc_v40,
            "score_q4": sc_v40,
            "rk_prio": rk_prio,
            "threshold": 90,
            "is_passed": is_passed,
            "is_direct_open": False,
            "open_px": open_px,
            "open_pct": op_pct,
            "cur_px": q.get("price", open_px),
            "cur_pct": q.get("cur_pct", 0.0),
            "passed_skeleton": res_v40["passed_skeleton"] and is_live_34,
            "veto_reasons": res_v40.get("veto_reasons", []),
            "breakdown_str": res_v40.get("breakdown_str", "") if is_live_34 else "盘后待明日09:25竞价",
            "order_type": "09:26 突破条件单（卖五价扫入，10:30未突破撤单）",
            "trigger_px": trig_px,
        })
    results.sort(key=lambda x: (-x["rk_prio"], -x["score_base"]))
    return results

def evaluate_1to2_26q4(cache: dict, quotes: dict, sr_state: dict, mock_map: dict = None) -> list[dict]:
    """一进二 V19（100% 复用 fast_1to2_today.evaluate_1to2_v19_df 唯一真源）"""
    stds = sr_state["train_stds_2021_2025"]
    bsrs = sr_state["blended_seasonal_sr"]
    std_12 = float(stds.get("一进二_V19") or stds.get("一进二_V18", 26.1185))
    bsr_12 = float(bsrs.get("一进二_V19") or bsrs.get("一进二_V18", 0.5552))
    df, meta = evaluate_1to2_v19_df(cache, quotes, mock_map=mock_map)
    if df.empty:
        return []
    tot_thr = float(meta["tot_thr"])
    results = []
    for _, r_row in df.iterrows():
        sc_b = round(float(r_row["tot_v18"]), 1)
        is_p = bool(r_row["passed_base"])
        is_fb = bool(r_row.get("fb_dom295", False))
        do_direct = bool(r_row["is_direct_open"])
        if bool(r_row["passed_v18"]):
            rk_prio = round((sc_b - tot_thr) / std_12 + bsr_12, 3)
        elif is_fb:
            rk_prio = round((float(r_row["tot_no_t3"]) - 295.0) / std_12 - 5.0, 3)
        else:
            rk_prio = -999.0
        strat_lbl = "一进二 V19[候补fb295]" if is_fb else "一进二 V19"
        results.append({
            "strategy": strat_lbl,
            "priority": 5,
            "code": r_row["c6"],
            "name": r_row["name"],
            "plate": r_row["plate"],
            "score_base": sc_b,
            "score_q4": sc_b,
            "rk_prio": rk_prio,
            "threshold": 295.0 if is_fb else tot_thr,
            "is_passed": is_p,
            "is_direct_open": do_direct,
            "open_px": r_row["open_p"],
            "open_pct": 0.0 if r_row["o_pct"] <= -0.90 else r_row["o_pct"],
            "cur_px": r_row["cur_p"],
            "cur_pct": r_row["c_pct"],
            "gate_ok": bool(r_row["gate_ok"] and r_row.get("purifier_ok", True)),
            "order_type": "09:26 周一断层开盘直买（卖五价扫入）" if do_direct else "09:26 突破条件单（11:30未触及撤单）",
            "trigger_px": r_row["open_p"] if do_direct else r_row["trig_p"],
        })
    results.sort(key=lambda x: (-x["rk_prio"], -x["score_base"]))
    return results

def main():
    parser = argparse.ArgumentParser(description="当季科学专供版（多股互斥条件单+滚动夏普择优）实盘决策引擎")
    parser.add_argument("--mock-open", type=str, default="", help="模拟竞价涨幅，如 '002205=0.045'")
    args = parser.parse_args()

    t0 = time.time()
    if not (os.path.exists(CACHE_HD) and os.path.exists(CACHE_34) and os.path.exists(CACHE_12)):
        print("[!] 核心缓存缺失，请先运行各大策略 --build-cache 生成盘前缓存！", file=sys.stderr)
        return

    c_hd = json.load(open(CACHE_HD, "r", encoding="utf-8"))
    c_34 = json.load(open(CACHE_34, "r", encoding="utf-8"))
    c_12 = json.load(open(CACHE_12, "r", encoding="utf-8"))
    sr_state = load_sr_state()

    all_codes = set()
    for x in c_hd.get("candidates", []): all_codes.add(x["code"])
    for x in c_34.get("candidates", []):
        all_codes.add(x["code"])
        all_codes.update(x.get("plate_fb_codes", []))
        all_codes.update(x.get("plate_zt_codes", []))
    for x in c_12.get("candidates", []): all_codes.add(x["c6"])

    quotes = fetch_tencent_quotes(list(all_codes))

    mock_map = {}
    if args.mock_open:
        for pair in args.mock_open.split(","):
            if "=" in pair:
                k, v = pair.split("=")
                c6_k, op_v = k.strip().zfill(6), float(v.strip())
                mock_map[c6_k] = op_v
                if c6_k in quotes:
                    pre_ref = quotes[c6_k]["price"] or quotes[c6_k]["pre_c"]
                    quotes[c6_k]["pre_c"] = pre_ref
                    quotes[c6_k]["open_pct"] = op_v
                    quotes[c6_k]["open"] = round(pre_ref * (1.0 + op_v), 2)
                    quotes[c6_k]["q_dt"] = "9999-12-31"
                else:
                    quotes[c6_k] = {"code": c6_k, "name": c6_k, "open_pct": op_v, "open": 10.0, "price": 10.0, "pre_c": 10.0 / (1.0 + op_v), "cur_pct": op_v, "zt_px": 11.0, "is_yizi": False, "q_dt": "9999-12-31"}

    res_hd = evaluate_high_dragon_26q4(c_hd, quotes, sr_state)
    res_34 = evaluate_3to4_26q4(c_34, quotes, sr_state)
    res_12 = evaluate_1to2_26q4(c_12, quotes, sr_state, mock_map=mock_map)

    top_cands = []
    for group in (res_hd, res_34, res_12):
        passed = [x for x in group if x["is_passed"]]
        if passed:
            top_cands.append(passed[0])

    # 严格盘前唯一单挂单裁决：常态按 三进四 > 高标首阴 > 超跌撬板 > 二进三 > 一进二 走；仅当低顺位出现极端超高胜率满格分(把握度领先>=1.5)才越级
    chosen = None
    if top_cands:
        top_by_order = sorted(top_cands, key=lambda x: x["priority"])[0]
        top_by_conv = sorted(top_cands, key=lambda x: -x["rk_prio"])[0]
        if top_by_conv["rk_prio"] - top_by_order["rk_prio"] >= 1.50:
            chosen = top_by_conv
        else:
            chosen = top_by_order

    print("=" * 88)
    print(f"【当季科学专供版（盘前唯一挂单 · 三进四第1顺位＞高标＞超跌＞二进三＞一进二）决策面板 | 基准日: {sr_state.get('as_of_date','')}】")
    bsr = sr_state["blended_seasonal_sr"]
    print(f"当季50/50贝叶斯滚动夏普底分: 高标={bsr['高标首阴_V51']:.3f} | 三进四={bsr['三进四_V34']:.3f} | 一进二={bsr['一进二_V18']:.3f}")
    if chosen:
        print(f"🎯 最终结论：`09:26 唯一挂单 {chosen['strategy']} 头名 {chosen['code']} {chosen['name']}（得分{chosen['score_base']}分，把握度={chosen['rk_prio']:+.2f}）`")
        print(f"   - 基础总分: {chosen['score_base']}分 (门槛>={chosen['threshold']}分) | 今开: {chosen['open_pct']*100:+.2f}% | 现价: {chosen['cur_px']:.2f}元")
        print(f"   - ⚡ 唯一挂单指令: {chosen['order_type']} | 触发价: {chosen['trigger_px']:.2f}元")
    else:
        print("🎯 最终结论：`今日三大核心主战策略全线空仓观望（未触发购买门槛）`")
        print(f"   - 高标首阴 V5.1 (门槛88分): 无标的过线")
        print(f"   - 三进四 V4.0 (门槛90分): 无标的过线")
        print(f"   - 一进二 V19 (门槛{float(c_12.get('mkt_sentiment',{}).get('tot_thr',304.8))}分): 无标的过线")
    print("=" * 88)

    print("\n--- [高标首阴 V5.1 | 门槛88分] ---")
    for x in res_hd:
        print(f"  {x['code']} {x['name']:<6s} | 得分: {x['score_base']:>4} | 把握度: {x['rk_prio']:>6.2f} | 今开: {x['open_pct']*100:+.2f}% | 否决: {x['is_vetoed']} ({'；'.join(x['veto_reasons']) if x['veto_reasons'] else '无'})")
    if not res_hd: print("  今日无候选池标的")

    print("\n--- [三进四 V4.0 | 门槛90分] ---")
    for x in res_34:
        print(f"  {x['code']} {x['name']:<6s} | 得分: {x['score_base']:>4} | 把握度: {x['rk_prio']:>6.2f} | 今开: {x['open_pct']*100:+.2f}% | 硬骨架: {x['passed_skeleton']} ({x.get('breakdown_str', '')[:35]})")
    if not res_34: print("  今日无候选池标的")

    print("\n--- [一进二 V19 | Top 10] ---")
    for x in res_12[:10]:
        print(f"  {x['code']} {x['name']:<6s} | 得分: {x['score_base']:>5.1f} | 把握度: {x['rk_prio']:>6.2f} | 今开: {x['open_pct']*100:+.2f}% | 门禁: {x['gate_ok']} | 题材: {x['plate']}")
    if not res_12: print("  今日无候选池标的")

    print(f"\n[+] 全流程决策完成，耗时: {time.time()-t0:.2f}s")

if __name__ == "__main__":
    main()

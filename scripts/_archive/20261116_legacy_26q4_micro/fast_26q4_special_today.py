#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
fast_26q4_special_today.py — 26Q4 专供版三大主策略实盘极速打分与购买决策引擎
------------------------------------------------------------------------------------------------
物理隔离铁律：
  本引擎独立读取三大缓存 + 腾讯实时竞价行情，严格按 26Q4 当季专供版规则独立打分与裁决；
  严禁混淆与污染五年基础版（fast_high_dragon_today / fast_3to4_today / fast_1to2_today 基础因子不动）。

顺位执行法则（纯单仓，旧仓未平不开新仓，空仓日按唯一顺位取首个达标策略头名）：
  第1顺位: 高标首阴 26Q4 专供版 (满96分)
  第2顺位: 三进四 26Q4 专供版 (满94分)
  第3顺位: 一进二 26Q4 专供版 (满304.8分)
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

sys.path.insert(0, f"{SIM}/backtests_astock2")
from score_3to4_v31_card import score_single_3to4_row

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
                        op_px = op if op > 0.0 else px
                        op_pct = (op_px / pc - 1.0) if pc > 0 else 0.0
                        cur_pct = (px / pc - 1.0) if pc > 0 else 0.0
                        zt_px = np.floor(pc * 1.10 * 100.0 + 0.5) / 100.0 if pc > 0 else 999.0
                        is_yz = bool(op_px >= zt_px - 0.011 or (b1_v > 0 and s1_v == 0 and op_pct >= 0.090))
                        qmap[c6] = {
                            "code": c6, "name": nm, "price": px, "pre_c": pc,
                            "open": op_px, "open_pct": op_pct, "cur_pct": cur_pct,
                            "high": hi, "low": lo, "amt_yi": amt_yi, "zt_px": zt_px,
                            "is_yizi": is_yz,
                        }
        except Exception as e:
            print(f"[WARN] fetch_tencent_quotes error: {e}", file=sys.stderr)
    return qmap

def evaluate_high_dragon_26q4(cache: dict, quotes: dict) -> list[dict]:
    """第1顺位：高标首阴 26Q4 专供版打分"""
    cands = cache.get("candidates", [])
    results = []
    for r in cands:
        c6 = r["code"]
        q = quotes.get(c6, {})
        op_pct = q.get("open_pct", 0.0)
        open_px = q.get("open", r.get("close_d1", 0.0))
        cur_px = q.get("price", open_px)
        is_vetoed = bool(r.get("is_vetoed", False))
        static_score = int(r.get("static_score", 60))

        # 26Q4 竞价修正
        auc_adj = 12 if (-0.004 <= op_pct <= 0.035) else (-8 if op_pct <= -0.008 else 0)
        # 26Q4 专供妖股溢价 (+6 抱团反包 +5 增量流动性)
        q4_bonus = 6 + 5
        score_q4 = static_score + auc_adj + q4_bonus if not is_vetoed else -999

        # 五年基础版对照分
        score_v51 = static_score + (8 if op_pct < 0.0 else (6 if op_pct <= 0.025 else 0)) if not is_vetoed else -999

        is_passed = (score_q4 >= 96) and (not is_vetoed)
        results.append({
            "strategy": "高标首阴 26Q4",
            "priority": 1,
            "code": c6,
            "name": r.get("name", q.get("name", c6)),
            "streak_d0": r.get("streak_d0", 4),
            "static_score": static_score,
            "score_base": score_v51,
            "score_q4": score_q4,
            "threshold": 96,
            "is_passed": is_passed,
            "open_px": open_px,
            "open_pct": op_pct,
            "cur_px": cur_px,
            "cur_pct": q.get("cur_pct", 0.0),
            "is_vetoed": is_vetoed,
            "veto_reasons": r.get("veto_reasons", []),
            "order_type": "09:26 挂单买入（卖五价扫入）",
            "trigger_px": open_px,
        })
    results.sort(key=lambda x: -x["score_q4"])
    return results

def evaluate_3to4_26q4(cache: dict, quotes: dict) -> list[dict]:
    """第2顺位：三进四 26Q4 专供版打分"""
    env = cache.get("env", {})
    cands = cache.get("candidates", [])
    open_3b = [(r["code"], quotes.get(r["code"], {}).get("open_pct", -1.0),
                quotes.get(r["code"], {}).get("open", 0) < r["px_d3"] * 1.095) for r in cands]
    buy_3b = [x for x in open_3b if x[2]]
    top1_c = max(buy_3b, key=lambda x: x[1])[0] if buy_3b else ""

    results = []
    for r in cands:
        c6 = r["code"]
        q = quotes.get(c6, {})
        op_pct = q.get("open_pct", 0.0)
        open_px = q.get("open", r["px_d3"] * 1.055)
        fb_ops = [quotes.get(fc, {}) for fc in r.get("plate_fb_codes", []) if fc in quotes]
        zt_ops = [quotes.get(zc, {}).get("open_pct", 0.0) for zc in r.get("plate_zt_codes", []) if zc in quotes]

        row = dict(r, **env)
        row["open_pct"] = op_pct
        row["buyable_open"] = (open_px < q.get("zt_px", r["px_d3"] * 1.10) - 0.005)
        row["is_top1_3b_open"] = (c6 == top1_c)
        row["plate_fb_ho_cnt"] = sum(1 for x in fb_ops if 0.025 <= x.get("open_pct", 0) < 0.095)
        row["plate_fb_yz_cnt"] = sum(1 for x in fb_ops if x.get("open_pct", 0) >= 0.095)
        row["plate_peers_open_avg"] = float(np.mean(zt_ops)) if zt_ops else 0.0

        res_v34 = score_single_3to4_row(row)
        sc_v34 = res_v34["score"]
        sc_q4 = sc_v34

        if res_v34["passed_skeleton"]:
            if 0.030 <= op_pct <= 0.058: sc_q4 += 4
            if 32.0 < r["px_d3"] <= 48.0: sc_q4 += 5
            elif r["px_d3"] > 48.0: sc_q4 -= 5
            if int(env.get("mkt_max_board_prev", 4)) >= 6 and r.get("lock_top10", 0) < 45.0: sc_q4 -= 8
            if r.get("prev_to", 0) < 9.5: sc_q4 -= 5
            sc_q4 += 1  # 26Q4 跨周末发酵额外+1 (合计+3)
        else:
            sc_q4 = -999

        is_passed = (sc_q4 >= 94) and res_v34["passed_skeleton"]
        trig_px = max(round(r["px_d3"] * 1.065, 2), round(open_px, 2))
        results.append({
            "strategy": "三进四 26Q4",
            "priority": 2,
            "code": c6,
            "name": r.get("name", q.get("name", c6)),
            "px_d3": r["px_d3"],
            "score_base": sc_v34,
            "score_q4": sc_q4,
            "threshold": 94,
            "is_passed": is_passed,
            "open_px": open_px,
            "open_pct": op_pct,
            "cur_px": q.get("price", open_px),
            "cur_pct": q.get("cur_pct", 0.0),
            "passed_skeleton": res_v34["passed_skeleton"],
            "veto_reasons": res_v34.get("veto_reasons", []),
            "breakdown_str": res_v34.get("breakdown_str", ""),
            "order_type": "09:26 突破条件单（卖五价扫入，11:30未突破撤单）",
            "trigger_px": trig_px,
        })
    results.sort(key=lambda x: -x["score_q4"])
    return results

def evaluate_1to2_26q4(cache: dict, quotes: dict) -> list[dict]:
    """第3顺位：一进二 26Q4 专供版打分"""
    cands = cache.get("candidates", [])
    is_mon = bool(cache.get("is_monday", False))
    mkt = cache.get("mkt_sentiment", {})
    d1_zt = int(mkt.get("d1_zt_cnt", 50))
    seal_r = float(mkt.get("d1_1to2_seal_rate", 0.5))
    climax_pen = (-15.0 if d1_zt >= 100 else (-10.0 if d1_zt >= 95 else 0.0)) + (-10.0 if seal_r >= 0.80 else 0.0)

    rows = []
    for r in cands:
        c6 = r["c6"]
        q = quotes.get(c6, {})
        r_item = dict(r)
        if not r_item.get("name"): r_item["name"] = q.get("name", "")
        op, lp, cp, pre = q.get("open", 0), q.get("low", 0), q.get("price", 0), r_item["pre_c"]
        zt_p = round(pre * 1.10 + 1e-6, 2)
        r_item["open_p"], r_item["cur_p"] = op, cp
        r_item["o_pct"] = q.get("open_pct", 0.0)
        r_item["c_pct"] = q.get("cur_pct", 0.0)
        r_item["zt_p"] = zt_p
        r_item["d2_is_yizi"] = bool(op >= zt_p - 0.01 and lp >= zt_p - 0.01)
        r_item["is_buyable_open"] = bool(r_item.get("gate_ok", False) and 0 < op < zt_p - 0.005)
        r_item["trig_p"] = min(zt_p, max(round(op * 1.012, 2), round(pre * 1.065, 2))) if op > 0 else zt_p
        rows.append(r_item)

    if not rows:
        return []

    df = pd.DataFrame(rows)
    is_fl = df["d2_is_yizi"] | ((not is_mon) & (df["o_pct"] > 0.078)) | (is_mon & (df["o_pct"] > 0.088))
    df["front_lock_cnt"] = is_fl.astype(int).groupby(df["plate"]).transform("sum")
    df["plate_d2_yizi_cnt"] = df["d2_is_yizi"].astype(int).groupby(df["plate"]).transform("sum")
    myz = int(df["d2_is_yizi"].sum())
    in_win = df["is_buyable_open"] & ((is_mon & df["o_pct"].between(0.020, 0.088)) | ((not is_mon) & df["o_pct"].between(0.022, 0.078)))
    df["true_buy_rk"] = np.where(in_win, df["o_pct"], -9.99)
    df["true_buy_rk"] = df.groupby("plate")["true_buy_rk"].rank(ascending=False, method="min")
    df["_bo"] = np.where(df["is_buyable_open"], df["o_pct"], -9.99)
    df["mkt_open_rk"] = df["_bo"].rank(ascending=False, method="min")
    df["sub_rk"] = df.groupby(["plate", "r_short"])["_bo"].rank(ascending=False, method="min")
    p2 = df.groupby("plate")["_bo"].transform(lambda s: s.nlargest(2).iloc[-1] if (s > -1.0).sum() >= 2 else -0.05)
    df["open_lead"] = np.where(df["true_buy_rk"] == 1, df["o_pct"] - p2, 0.0)

    has_sub = (df["p_sz"] >= 8) & (~df["r_short"].isin([df["plate"], "其他", ""]))
    rk_bon = np.where(df["true_buy_rk"] == 1, 35.0, np.where(has_sub & (df["sub_rk"] == 1), 24.0, np.where(df["true_buy_rk"] == 2, 8.0, -25.0)))
    sw = (df["rk_theme"] == 1) & (df["p_sz"] >= 8) & (df["true_buy_rk"] == 1)
    hm = df["notice_hard"] | df["is_ma"]
    yg = np.select([(df["front_lock_cnt"] == 1) & (df["true_buy_rk"] == 1) & (myz in [1, 2]),
                    (df["front_lock_cnt"] >= 2) & sw, (df["front_lock_cnt"] == 2) & (~sw),
                    (df["front_lock_cnt"] >= 3) & (~sw), (df["front_lock_cnt"] == 0) & (myz == 0) & (~hm)],
                   [8.0, 5.0, -15.0, -22.0, -5.0], default=0.0)
    auc_b = (rk_bon + np.where(df["mkt_open_rk"] <= 3, 20.0, np.where(df["mkt_open_rk"] <= 6, 12.0, 0.0))
             + np.where(df["open_lead"] >= 0.020, 22.0, np.where(df["open_lead"] >= 0.010, 12.0, 0.0))
             + np.where(df["plate_d2_yizi_cnt"] >= 1, 10.0, 0.0)
             + np.where(df["o_pct"].between(0.040, 0.082), 20.0, np.where(df["o_pct"].between(0.018, 0.040), 12.0, 0.0)))
    roll_ho = float(mkt.get("roll20_ho_zt", 0.5))
    wk_pen = 0.0 if is_mon else np.where(df["o_pct"] < (0.035 if roll_ho < 0.45 else 0.031), -25.0 if roll_ho < 0.45 else -15.0, 0.0)

    ts = cache.get("theme_structure", {})
    t1_m, t3_m = float(ts.get("t1_med", 0)), float(ts.get("t3_med", 0))
    dom_t3 = (t1_m >= 65.0) and (t1_m - t3_m >= 35.0) and (t3_m < 42.0)
    v18_pen = np.where((df["plate_d2_yizi_cnt"] >= 1) & (df["mcap"] > 90.0), -25.0, 0.0) + np.where(dom_t3 & (df["rk_theme"] >= 3), -15.0, 0.0)
    df["tot_v18"] = df["static_tot"] + auc_b + wk_pen + yg + climax_pen + v18_pen

    q4_delta = (np.where(df["is_dying_pulse"], -15.0, 0.0) + np.where(hm, 10.0, 0.0)
                + np.where(df["o_pct"].between(0.045, 0.078), 5.0, 0.0) + np.where(df["clean_brk60"], 5.0, 0.0)
                + np.where(df["plate_d2_yizi_cnt"] >= 1, -10.0, 0.0))
    df["tot_26q4"] = df["tot_v18"] + q4_delta

    results = []
    for _, r_row in df.iterrows():
        is_p = (r_row["tot_26q4"] >= 304.8) and bool(r_row["gate_ok"]) and (not r_row["d2_is_yizi"])
        results.append({
            "strategy": "一进二 26Q4",
            "priority": 3,
            "code": r_row["c6"],
            "name": r_row["name"],
            "plate": r_row["plate"],
            "score_base": round(float(r_row["tot_v18"]), 1),
            "score_q4": round(float(r_row["tot_26q4"]), 1),
            "threshold": 304.8,
            "is_passed": is_p,
            "open_px": r_row["open_p"],
            "open_pct": r_row["o_pct"],
            "cur_px": r_row["cur_p"],
            "cur_pct": r_row["c_pct"],
            "gate_ok": bool(r_row["gate_ok"]),
            "order_type": "09:26 突破买单（条件单）",
            "trigger_px": r_row["trig_p"],
        })
    results.sort(key=lambda x: -x["score_q4"])
    return results

def main():
    parser = argparse.ArgumentParser(description="26Q4 专供版三大主策略实盘极速打分与购买决策引擎")
    parser.add_argument("--mock-open", type=str, default="", help="模拟竞价涨幅，如 '603396=0.045,002148=0.035'")
    args = parser.parse_args()

    t0 = time.time()
    if not (os.path.exists(CACHE_HD) and os.path.exists(CACHE_34) and os.path.exists(CACHE_12)):
        print("[!] 核心缓存缺失，请先运行各大策略 --build-cache 生成盘前缓存！", file=sys.stderr)
        return

    c_hd = json.load(open(CACHE_HD, "r", encoding="utf-8"))
    c_34 = json.load(open(CACHE_34, "r", encoding="utf-8"))
    c_12 = json.load(open(CACHE_12, "r", encoding="utf-8"))

    all_codes = set()
    for x in c_hd.get("candidates", []): all_codes.add(x["code"])
    for x in c_34.get("candidates", []):
        all_codes.add(x["code"])
        all_codes.update(x.get("plate_fb_codes", []))
        all_codes.update(x.get("plate_zt_codes", []))
    for x in c_12.get("candidates", []): all_codes.add(x["c6"])

    quotes = fetch_tencent_quotes(list(all_codes))

    if args.mock_open:
        for pair in args.mock_open.split(","):
            if "=" in pair:
                k, v = pair.split("=")
                c6_k, op_v = k.strip(), float(v.strip())
                if c6_k in quotes:
                    quotes[c6_k]["open_pct"] = op_v
                    quotes[c6_k]["open"] = round(quotes[c6_k]["pre_c"] * (1.0 + op_v), 2)
                else:
                    quotes[c6_k] = {"code": c6_k, "name": c6_k, "open_pct": op_v, "open": 10.0, "price": 10.0, "pre_c": 10.0 / (1.0 + op_v), "cur_pct": op_v, "zt_px": 11.0, "is_yizi": False}

    res_hd = evaluate_high_dragon_26q4(c_hd, quotes)
    res_34 = evaluate_3to4_26q4(c_34, quotes)
    res_12 = evaluate_1to2_26q4(c_12, quotes)

    passed_hd = [x for x in res_hd if x["is_passed"]]
    passed_34 = [x for x in res_34 if x["is_passed"]]
    passed_12 = [x for x in res_12 if x["is_passed"]]

    # 裁决唯一主战指令
    target_action = None
    if passed_hd:
        target_action = passed_hd[0]
    elif passed_34:
        target_action = passed_34[0]
    elif passed_12:
        target_action = passed_12[0]

    print("=" * 86)
    print("【26Q4 专供版三大主策略实盘购买决策面板】")
    if target_action:
        print(f"🎯 最终结论：`买入第{target_action['priority']}顺位 {target_action['strategy']} 标的：{target_action['code']} {target_action['name']}`")
        print(f"   - 26Q4 专供总分: {target_action['score_q4']}分 (门槛: >={target_action['threshold']}分 | 五年基准分: {target_action['score_base']}分)")
        print(f"   - 竞价开盘涨幅: {target_action['open_pct']*100:+.2f}% | 当前现价: {target_action['cur_px']:.2f}元 ({target_action['cur_pct']*100:+.2f}%)")
        print(f"   - ⚡ 09:26 挂单卡: {target_action['order_type']} | 触发价: {target_action['trigger_px']:.2f}元")
    else:
        print("🎯 最终结论：`今日三大核心主战策略全线空仓观望（未触发购买门槛）`")
        print("   - 第1顺位 高标首阴 26Q4 (门槛96分): 无标的过线")
        print("   - 第2顺位 三进四 26Q4 (门槛94分): 无标的过线")
        print("   - 第3顺位 一进二 26Q4 (门槛304.8分): 无标的过线")
    print("=" * 86)

    print("\n--- [顺位 1] 高标首阴 26Q4 专供版 ---")
    for x in res_hd:
        print(f"  {x['code']} {x['name']:<6s} | 专供分: {x['score_q4']:>4} | 基准分: {x['score_base']:>4} | 今开: {x['open_pct']*100:+.2f}% | 否决: {x['is_vetoed']} ({'；'.join(x['veto_reasons']) if x['veto_reasons'] else '无'})")
    if not res_hd: print("  今日无候选池标的")

    print("\n--- [顺位 2] 三进四 26Q4 专供版 ---")
    for x in res_34:
        print(f"  {x['code']} {x['name']:<6s} | 专供分: {x['score_q4']:>4} | 基准分: {x['score_base']:>4} | 今开: {x['open_pct']*100:+.2f}% | 硬骨架: {x['passed_skeleton']} ({x.get('breakdown_str', '')[:35]})")
    if not res_34: print("  今日无候选池标的")

    print("\n--- [顺位 3] 一进二 26Q4 专供版 (Top 10) ---")
    for x in res_12[:10]:
        print(f"  {x['code']} {x['name']:<6s} | 专供分: {x['score_q4']:>5.1f} | 基准分: {x['score_base']:>5.1f} | 今开: {x['open_pct']*100:+.2f}% | 门禁: {x['gate_ok']} | 题材: {x['plate']}")
    if not res_12: print("  今日无候选池标的")

    print(f"\n[+] 全流程决策完成，耗时: {time.time()-t0:.2f}s")

if __name__ == "__main__":
    main()

#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
fast_26q4_special_today.py — 当季科学专供版（09:26 唯一挂单 + 五顺位滚动夏普把握度择优）实盘决策引擎
------------------------------------------------------------------------------------------------
核心原理（2026-11-18 v19.1 零前视验证定版）：
  1. 底层个股打分与门槛 100% 锁死五年基础版（五大实盘策略：三进四 V4.1 满90分、高标首阴 V5.1 满88分、超跌撬板 V2.1 满165分、二进三 V2.1 满90分[满96分重点提醒]、一进二 V19 满304.8/329.8分[候补295分]），零微观凑数改分。
  2. 计算当季滚动把握度 rk_prio = (得分 - 门槛)/历史标准差 + 当季50/50贝叶斯滚动夏普（近10笔触发样本收缩）。
  3. 严守盘前 09:26 唯一 1 笔挂单物理约束：常态严格按五顺位选唯一头名，仅当低顺位 rk_prio 领先高顺位满 1.50 以上时越级挂单。
------------------------------------------------------------------------------------------------
"""
import os, sys, json, time, argparse, urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import pandas as pd

os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
DATA_DIR = f"{SIM}/data"

CACHE_HD = f"{DATA_DIR}/high_dragon_premarket_cache.json"
CACHE_34 = f"{DATA_DIR}/3to4_premarket_cache.json"
CACHE_PRY = f"{DATA_DIR}/pry_premarket_cache.json"
CACHE_23 = f"{DATA_DIR}/2to3_premarket_cache.json"
CACHE_12 = f"{DATA_DIR}/1to2_premarket_cache.json"
STATE_SR = f"{DATA_DIR}/seasonal_rolling_sr_state.json"
ST_UNIVERSE = f"{DATA_DIR}/st_universe.json"

def load_sr_state() -> dict:
    if os.path.exists(STATE_SR):
        try:
            return json.load(open(STATE_SR, "r", encoding="utf-8"))
        except Exception:
            pass
    return {
        "as_of_date": "2026-11-20",
        "train_stds_2021_2025": {
            "三进四_V41": 7.2638, "高标首阴_V51": 14.9334, "超跌撬板_V21": 15.4066,
            "二进三_V21": 4.5105, "一进二_V19": 25.8750, "三进四_V34": 6.8491, "一进二_V18": 26.1185,
        },
        "blended_seasonal_sr": {
            "三进四_V41": 0.6412, "高标首阴_V51": 0.9884, "超跌撬板_V21": 0.5182,
            "二进三_V21": 0.4246, "一进二_V19": 0.6254, "三进四_V34": 0.5335, "一进二_V18": 0.5552,
        },
    }

sys.path.insert(0, f"{SIM}/scripts")
from live_3to4_v40_engine import score_single_3to4_v40_row as score_single_3to4_row
from fast_2to3_today import evaluate_2to3_candidate
from fast_1to2_today import evaluate_1to2_v19_df

def fetch_tencent_quotes(codes: list[str], max_workers: int = 24) -> dict[str, dict]:
    """并发/批量拉取腾讯实时行情"""
    if not codes:
        return {}
    clist = sorted(set(str(c).zfill(6) for c in codes))
    chunks = [clist[i:i + 80] for i in range(0, len(clist), 80)]

    def _fetch_chunk(chunk: list[str]) -> dict[str, dict]:
        res = {}
        q_codes = [f"{'sh' if c.startswith('6') else 'sz'}{c}" for c in chunk]
        url = f"http://qt.gtimg.cn/q={','.join(q_codes)}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        for _ in range(3):
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
                            zt_px = float(np.floor(pc * 1.10 * 100.0 + 0.5) / 100.0) if pc > 0 else 999.0
                            is_yz = bool(op_px >= zt_px - 0.005 or (b1_v > 0 and s1_v == 0 and op_pct >= 0.098))
                            res[c6] = {
                                "code": c6, "name": nm, "price": px, "pre_c": pc,
                                "open": op_px, "open_pct": op_pct, "cur_pct": cur_pct,
                                "high": hi, "low": lo, "amt_yi": amt_yi, "zt_px": zt_px,
                                "is_yizi": is_yz, "q_dt": q_dt,
                            }
                if res:
                    return res
            except Exception as e:
                print(f"[WARN] fetch_tencent_quotes error: {e}", file=sys.stderr)
        return res

    if len(chunks) == 1:
        return _fetch_chunk(chunks[0])
    qmap = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for res in executor.map(_fetch_chunk, chunks):
            qmap.update(res)
    return qmap

def _is_fb_yizi(x: dict) -> bool:
    if x.get("is_yizi"):
        return True
    opx = float(x.get("open", 0.0) or 0.0)
    zpx = float(x.get("zt_px", 0.0) or 0.0)
    if opx > 0 and 0 < zpx < 900:
        return opx >= zpx - 0.005
    return float(x.get("open_pct", 0.0) or 0.0) >= 0.098


def _is_3b_buyable(r_item: dict, q_item: dict, d3_str: str) -> bool:
    is_live = (not d3_str) or (q_item.get("q_dt", "") > d3_str)
    opx = float(q_item.get("open", 0.0) or 0.0)
    op_pct = float(q_item.get("open_pct", -1.0))
    zt_px = float(q_item.get("zt_px") or (np.floor(r_item["px_d3"] * 1.10 * 100.0 + 0.5) / 100.0))
    return bool(is_live and opx > 0 and op_pct < 0.098 and opx < zt_px - 0.005 and (not q_item.get("is_yizi", False)))


def evaluate_high_dragon_26q4(cache: dict, quotes: dict, sr_state: dict) -> list[dict]:
    """高标首阴（锁死 V5.1 基础分满88分 + 当季滚动把握度）"""
    cands = cache.get("candidates", [])
    sig_hd = cache.get("as_of_d1", "")
    stds = sr_state.get("train_stds_2021_2025", {})
    bsrs = sr_state.get("blended_seasonal_sr", {})
    std_hd = float(stds.get("高标首阴_V51", 14.9334))
    bsr_hd = float(bsrs.get("高标首阴_V51", 0.9884))
    results = []
    for r in cands:
        c6 = r["code"]
        q = quotes.get(c6, {})
        is_live_hd = (not sig_hd) or (q.get("q_dt", "") > sig_hd)
        op_pct = q.get("open_pct", 0.0) if is_live_hd else 0.0
        open_px = q.get("open", r.get("close_d1", 0.0)) if is_live_hd else 0.0
        cur_px = q.get("price", open_px)
        zt_px = float(q.get("zt_px", 999.0))
        veto_list = list(r.get("veto_reasons", []))
        if not is_live_hd:
            veto_list.append("盘后待明日09:25竞价")
        else:
            if op_pct > 0.045: veto_list.append("竞价超涨>4.5%")
            if op_pct < -0.065: veto_list.append("竞价核按钮<-6.5%")
            if q.get("is_yizi", False) or (open_px > 0 and open_px >= zt_px - 0.005):
                veto_list.append("一字不可买")
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
    """三进四 V4.1（买点锁死 V4.0 基础分满90分 + 当季滚动把握度，10:30撤单窗；连板期7因子风险开关+7.0%/+5.0%护利）"""
    env = cache.get("env", {})
    cands = cache.get("candidates", [])
    d3_str = cache.get("d3_date", "")
    stds = sr_state["train_stds_2021_2025"]
    bsrs = sr_state["blended_seasonal_sr"]
    std_34 = float(stds.get("三进四_V41") or stds.get("三进四_V40") or stds.get("三进四_V34", 7.2638))
    bsr_34 = float(bsrs.get("三进四_V41") or bsrs.get("三进四_V40") or bsrs.get("三进四_V34", 0.6412))
    open_3b = [
        (r["code"], quotes.get(r["code"], {}).get("open_pct", -1.0),
         _is_3b_buyable(r, quotes.get(r["code"], {}), d3_str))
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
        row["buyable_open"] = _is_3b_buyable(r, q, d3_str)
        row["is_top1_3b_open"] = (c6 == top1_c) if is_live_34 else False
        row["plate_fb_ho_cnt"] = sum(1 for x in fb_ops if x.get("open_pct", 0) >= 0.03 and not _is_fb_yizi(x))
        row["plate_fb_yz_cnt"] = sum(1 for x in fb_ops if _is_fb_yizi(x))
        row["plate_peers_open_avg"] = float(np.mean(zt_ops)) if zt_ops else 0.0

        res_v40 = score_single_3to4_row(row)
        sc_v40 = res_v40["score"] if (is_live_34 and res_v40["passed_skeleton"]) else -999
        is_passed = (sc_v40 >= 90) and res_v40["passed_skeleton"] and is_live_34
        rk_prio = round((sc_v40 - 90.0) / std_34 + bsr_34, 3) if is_passed else -999.0
        trig_px = max(round(r["px_d3"] * 1.065, 2), round(open_px, 2)) if is_live_34 else round(r["px_d3"] * 1.065, 2)
        results.append({
            "strategy": "三进四 V4.1",
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


def evaluate_pry_26q4(cache: dict, quotes: dict, sr_state: dict, st_set: set[str]) -> tuple[list[dict], dict]:
    """超跌撬板 V2.1（第3顺位，满165分，含09:25剔ST竞价涨停家数>=12加15分与当季滚动把握度）"""
    cands = cache.get("candidates", [])
    dpr_str = cache.get("sig_date", "")
    stds = sr_state.get("train_stds_2021_2025", {})
    bsrs = sr_state.get("blended_seasonal_sr", {})
    std_pry = float(stds.get("超跌撬板_V21", 15.4066))
    bsr_pry = float(bsrs.get("超跌撬板_V21", 0.5182))

    pre_eval = []
    need_mkt = False
    for r in cands:
        c6 = r["code"]
        q = quotes.get(c6, {})
        nm = str(q.get("name", r.get("name", c6)))
        is_live = (not dpr_str) or (q.get("q_dt", "") > dpr_str)
        is_st = (c6 in st_set) or ("ST" in nm.upper()) or ("退" in nm)
        open_px = float(q.get("open", 0.0)) if is_live else 0.0
        op_pct = float(q.get("open_pct", 0.0)) if (is_live and open_px > 0) else 0.0
        zt_px = float(q.get("zt_px", 999.0))
        is_yz = bool(is_live and (q.get("is_yizi", False) or (open_px > 0 and open_px >= zt_px - 0.005)))
        in_win = bool(is_live and (not is_st) and (not is_yz) and open_px > 0 and (0.0 <= op_pct <= 0.05))
        max_pos = int(r.get("max_possible", int(r.get("static_score", 100)) + 15))
        if in_win and max_pos >= 165:
            need_mkt = True
        pre_eval.append((r, q, nm, is_live, is_st, is_yz, open_px, op_pct, in_win))

    zt_open_cnt = 0
    valid_mkt_cnt = 0
    scanned = False
    if need_mkt:
        all_m = [str(mc).zfill(6) for mc in cache.get("main_codes_sample", []) if str(mc).zfill(6) not in st_set]
        if all_m:
            scanned = True
            qm = fetch_tencent_quotes(all_m)
            valid_mkt = [
                v for ck, v in qm.items()
                if ck not in st_set and "ST" not in str(v.get("name", "")).upper() and "退" not in str(v.get("name", ""))
                and ((not dpr_str) or v.get("q_dt", "") > dpr_str)
            ]
            valid_mkt_cnt = len(valid_mkt)
            if valid_mkt_cnt < min(len(all_m) * 0.9, 4500):
                print(f"[WARN] 超跌撬板 09:25 全市场有效竞价样本数偏低 ({valid_mkt_cnt}/{len(all_m)})，请检查网络或非交易时段！", file=sys.stderr)
            zt_open_cnt = sum(
                1 for v in valid_mkt
                if v.get("open", 0.0) > 0 and v.get("open", 0.0) >= v.get("zt_px", 999.0) - 0.005
            )

    results = []
    for r, q, nm, is_live, is_st, is_yz, open_px, op_pct, in_win in pre_eval:
        c6 = r["code"]
        static_sc = int(r.get("static_score", 100))
        vetos = []
        if not is_live:
            vetos.append("盘后待明日09:25竞价")
        else:
            if is_st: vetos.append("ST/退市剔除")
            if is_yz: vetos.append("一字不可买")
            if not (0.0 <= op_pct <= 0.05): vetos.append(f"今开{op_pct*100:+.2f}%出[0%,+5%]")
        bonus = 15 if (in_win and zt_open_cnt >= 12) else 0
        sc_tot = (static_sc + bonus) if in_win else static_sc
        is_passed = bool(in_win and sc_tot >= 165)
        if in_win and not is_passed:
            vetos.append(f"总分{sc_tot}<165")
        rk_prio = round((sc_tot - 165.0) / std_pry + bsr_pry, 3) if is_passed else -999.0
        ref_px = open_px if open_px > 0 else float(r.get("close", 0.0))
        results.append({
            "strategy": "超跌撬板 V2.1",
            "priority": 3,
            "code": c6,
            "name": nm,
            "static_score": static_sc,
            "score_base": sc_tot,
            "score_q4": sc_tot,
            "rk_prio": rk_prio,
            "threshold": 165,
            "is_passed": is_passed,
            "is_direct_open": True,
            "open_px": round(open_px, 2),
            "open_pct": op_pct,
            "cur_px": float(q.get("price", ref_px)) if is_live else float(r.get("close", 0.0)),
            "cur_pct": float(q.get("cur_pct", 0.0)),
            "bias10": float(r.get("bias10", 0.0)),
            "dyn_tp_pct": float(r.get("dyn_tp_pct", 6.0)),
            "zt_open_cnt": zt_open_cnt,
            "veto_reasons": vetos,
            "order_type": "09:25 竞价直买（卖五价扫入，V2.1四步阶梯止盈）",
            "trigger_px": round(ref_px, 2),
        })
    results.sort(key=lambda x: (-int(x["is_passed"]), -x["rk_prio"], -x["score_base"], x["bias10"], x["code"]))
    return results, {"zt_open_cnt": zt_open_cnt, "valid_mkt_cnt": valid_mkt_cnt, "scanned": scanned}

def evaluate_2to3_26q4(cache: dict, quotes: dict, sr_state: dict) -> list[dict]:
    """二进三 V2.1（第四核心主战，门槛90分·满96分顶部单独重点提醒 + 当季滚动把握度，09:25直买；priority=4）"""
    cands = cache.get("candidates", [])
    d23_str = cache.get("data_as_of_date") or cache.get("sig_date") or ""
    stds = sr_state.get("train_stds_2021_2025", {})
    bsrs = sr_state.get("blended_seasonal_sr", {})
    std_23 = float(stds.get("二进三_V21", 4.5105))
    bsr_23 = float(bsrs.get("二进三_V21", 0.4246))
    results = []
    for r in cands:
        c6 = r["code"]
        q = quotes.get(c6, {})
        is_live_23 = (not d23_str) or (q.get("q_dt", "") > d23_str)
        pre_c = float(r.get("prev_close", 0.0)) or float(q.get("pre_c", 0.0))
        open_px = float(q.get("open", 0.0)) if is_live_23 else 0.0
        op_pct = float(q.get("open_pct", 0.0)) if (is_live_23 and open_px > 0) else 0.0
        zt_px = float(np.floor(pre_c * 1.10 * 100.0 + 0.5) / 100.0) if pre_c > 0 else float(q.get("zt_px", 999.0))
        is_yz = bool(
            is_live_23
            and (
                (open_px >= zt_px - 0.005)
                or (q.get("is_yizi", False) and q.get("q_dt", "") != "9999-12-31")
            )
        )
        buyable = bool(is_live_23 and open_px > 0 and not is_yz)
        ev = evaluate_2to3_candidate(r, op_pct, buyable)
        veto_list = list(ev["veto_reasons"])
        if not is_live_23 and "盘后待明日09:25竞价" not in veto_list:
            veto_list = ["盘后待明日09:25竞价"] + veto_list
        sc_v21 = int(ev["score"])
        is_passed = bool(is_live_23 and ev["passed_std90"])
        is_strict96 = bool(is_live_23 and ev["passed_strict96"])
        rk_prio = round((sc_v21 - 90.0) / std_23 + bsr_23, 3) if is_passed else -999.0
        ref_px = open_px if open_px > 0 else pre_c
        results.append({
            "strategy": "二进三 V2.1",
            "priority": 4,
            "code": c6,
            "name": r.get("name", q.get("name", c6)),
            "plate": r.get("plate", ""),
            "plate_sz": int(r.get("plate_sz", 0)),
            "static_score": int(ev["static_score"]),
            "score_base": sc_v21,
            "score_q4": sc_v21,
            "rk_prio": rk_prio,
            "threshold": 90,
            "is_passed": is_passed,
            "passed_strict96": is_strict96,
            "is_direct_open": True,
            "open_px": round(open_px, 2),
            "open_pct": op_pct,
            "cur_px": float(q.get("price", ref_px)) if is_live_23 else float(pre_c),
            "cur_pct": float(q.get("cur_pct", 0.0)),
            "veto_reasons": veto_list,
            "breakdown_str": ev["breakdown_str"],
            "order_type": "09:25 竞价直买（普通限价保护价 round(今开*1.015, 2)）",
            "trigger_px": round(ref_px * 1.015, 2),
        })
    results.sort(key=lambda x: (-int(x["is_passed"]), -x["rk_prio"], -x["score_base"], x["open_pct"], x["plate_sz"], x["code"]))
    return results

def evaluate_1to2_26q4(cache: dict, quotes: dict, sr_state: dict, mock_map: dict = None) -> list[dict]:
    """一进二 V19（100% 复用 fast_1to2_today.evaluate_1to2_v19_df 唯一真源）"""
    stds = sr_state["train_stds_2021_2025"]
    bsrs = sr_state["blended_seasonal_sr"]
    std_12 = float(stds.get("一进二_V19") or stds.get("一进二_V18", 25.8750))
    bsr_12 = float(bsrs.get("一进二_V19") or bsrs.get("一进二_V18", 0.6254))
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
    parser = argparse.ArgumentParser(description="当季科学专供版（09:26 唯一挂单 + 五顺位滚动夏普把握度择优）实盘决策引擎")
    parser.add_argument("--strict", action="store_true", default=True, help="默认开启：强制要求五大缓存基准日同日且为开盘啦官方源")
    parser.add_argument("--no-strict", dest="strict", action="store_false", help="仅调试时关闭严格校验")
    parser.add_argument("--mock-open", type=str, default="", help="模拟竞价涨幅，如 '002205=0.045,603978=0.02'")
    args = parser.parse_args()

    t0 = time.time()
    req_caches = [CACHE_HD, CACHE_34, CACHE_PRY, CACHE_23, CACHE_12]
    if not all(os.path.exists(p) for p in req_caches):
        print("[!] 核心缓存缺失，请先运行各大策略 --build-cache 生成盘前缓存！", file=sys.stderr)
        sys.exit(1)

    c_hd = json.load(open(CACHE_HD, "r", encoding="utf-8"))
    c_34 = json.load(open(CACHE_34, "r", encoding="utf-8"))
    c_pry = json.load(open(CACHE_PRY, "r", encoding="utf-8"))
    c_23 = json.load(open(CACHE_23, "r", encoding="utf-8"))
    c_12 = json.load(open(CACHE_12, "r", encoding="utf-8"))
    sr_state = load_sr_state()
    st_set = {str(x)[:6].zfill(6) for x in json.load(open(ST_UNIVERSE, "r", encoding="utf-8")).get("codes", [])} if os.path.exists(ST_UNIVERSE) else set()

    d1_str = c_12.get("d1_date", "")
    d3_str = c_34.get("d3_date", "")
    dhd_str = c_hd.get("as_of_d1", "")
    dpr_str = c_pry.get("sig_date", "")
    d23_str = c_23.get("data_as_of_date") or c_23.get("sig_date", "")
    all_aligned = bool(d1_str and d1_str == d3_str == dhd_str == dpr_str == d23_str)
    if args.strict:
        assert not c_12.get("used_ths_plate_fallback", False), "[S15真源阻断] 1to2_premarket_cache 仍为同花顺临时兜底，阻断决策！"
        assert all_aligned, (
            f"[S15基准日硬断言阻断] 五大盘前缓存基准日不一致或为空: 1to2={d1_str}, 3to4={d3_str}, hd={dhd_str}, pry={dpr_str}, 2to3={d23_str}，请先运行 --build-cache 同步至最新收盘日"
        )

    cache_pre_map = {}
    for x in c_hd.get("candidates", []):
        if x.get("close_d1"): cache_pre_map[x["code"]] = float(x["close_d1"])
    for x in c_34.get("candidates", []):
        if x.get("px_d3"): cache_pre_map[x["code"]] = float(x["px_d3"])
    for x in c_pry.get("candidates", []):
        if x.get("close"): cache_pre_map[x["code"]] = float(x["close"])
    for x in c_23.get("candidates", []):
        if x.get("prev_close"): cache_pre_map[x["code"]] = float(x["prev_close"])
    for x in c_12.get("candidates", []):
        if x.get("pre_c"): cache_pre_map[x["c6"]] = float(x["pre_c"])
    for x in c_12.get("fb20_cln_pool", []):
        if x.get("pre_c"): cache_pre_map[x["c6"]] = float(x["pre_c"])

    all_codes = set()
    for x in c_hd.get("candidates", []): all_codes.add(x["code"])
    for x in c_34.get("candidates", []):
        all_codes.add(x["code"])
        all_codes.update(x.get("plate_fb_codes", []))
        all_codes.update(x.get("plate_zt_codes", []))
    for x in c_pry.get("candidates", []): all_codes.add(x["code"])
    for x in c_23.get("candidates", []): all_codes.add(x["code"])
    for x in c_12.get("candidates", []): all_codes.add(x["c6"])
    if not c_12.get("fb20_cln_blocked_by_16", False):
        for x in c_12.get("fb20_cln_pool", []): all_codes.add(x["c6"])

    quotes = fetch_tencent_quotes(list(all_codes))

    mock_map = {}
    if args.mock_open:
        for pair in args.mock_open.split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                c6_k, op_v = k.strip().zfill(6), float(v.strip())
                mock_map[c6_k] = op_v
                old_q = quotes.get(c6_k, {})
                pre_ref = float(old_q.get("pre_c") or cache_pre_map.get(c6_k) or old_q.get("price") or 10.0)
                op_m = round(pre_ref * (1.0 + op_v), 2)
                lim_m = 1.20 if c6_k.startswith(("30", "688", "689")) else 1.10
                zt_m = float(np.floor(pre_ref * lim_m * 100.0 + 0.5) / 100.0)
                is_yz_m = bool(op_m >= zt_m - 0.005)
                quotes[c6_k] = {
                    **old_q,
                    "code": c6_k,
                    "name": old_q.get("name", c6_k),
                    "pre_c": pre_ref,
                    "open": op_m,
                    "price": op_m,
                    "high": op_m,
                    "low": op_m,
                    "open_pct": op_v,
                    "cur_pct": op_v,
                    "zt_px": zt_m,
                    "is_yizi": is_yz_m,
                    "q_dt": "9999-12-31",
                }

    res_hd = evaluate_high_dragon_26q4(c_hd, quotes, sr_state)
    res_34 = evaluate_3to4_26q4(c_34, quotes, sr_state)
    res_pry, pry_meta = evaluate_pry_26q4(c_pry, quotes, sr_state, st_set)
    res_23 = evaluate_2to3_26q4(c_23, quotes, sr_state)
    res_12 = evaluate_1to2_26q4(c_12, quotes, sr_state, mock_map=mock_map)

    top_cands = []
    for group in (res_hd, res_34, res_pry, res_23, res_12):
        passed = [x for x in group if x["is_passed"]]
        if passed:
            top_cands.append(passed[0])

    # 严格盘前唯一单挂单裁决：常态按 三进四V4.1 > 高标首阴V5.1 > 超跌撬板V2.1 > 二进三V2.1 > 一进二V19 走；仅当低顺位出现极端超高胜率满格分(把握度领先>=1.5)才越级
    chosen = None
    if top_cands:
        top_by_order = sorted(top_cands, key=lambda x: x["priority"])[0]
        top_by_conv = sorted(top_cands, key=lambda x: -x["rk_prio"])[0]
        if top_by_conv["rk_prio"] - top_by_order["rk_prio"] >= 1.50:
            chosen = top_by_conv
        else:
            chosen = top_by_order

    print("=" * 88)
    print(f"【当季科学专供版（五大实盘策略 · 盘前唯一挂单 · 三进四V4.1＞高标V5.1＞超跌撬板V2.1＞二进三V2.1＞一进二V19）决策面板 | 基准日: {sr_state.get('as_of_date','')}】")
    if not all_aligned:
        print(f"⚠️[S15基准日未全对齐] 1to2={d1_str} | 3to4={d3_str} | hd={dhd_str} | pry={dpr_str} | 2to3={d23_str}")
    bsr = sr_state["blended_seasonal_sr"]
    b34 = bsr.get("三进四_V41") or bsr.get("三进四_V34", 0.6412)
    bhd = bsr.get("高标首阴_V51", 0.9884)
    bpry = bsr.get("超跌撬板_V21", 0.5182)
    b23 = bsr.get("二进三_V21", 0.4246)
    b12 = bsr.get("一进二_V19") or bsr.get("一进二_V18", 0.6254)
    print(f"当季50/50贝叶斯滚动夏普底分: 三进四={b34:.3f} | 高标={bhd:.3f} | 超跌撬板={bpry:.3f} | 二进三={b23:.3f} | 一进二={b12:.3f}")
    if chosen:
        print(f"🎯 最终结论：`09:26 唯一挂单 第{chosen['priority']}顺位 {chosen['strategy']} 头名 {chosen['code']} {chosen['name']}（得分{chosen['score_base']}分，把握度={chosen['rk_prio']:+.2f}）`")
        print(f"   - 基础总分: {chosen['score_base']}分 (门槛>={chosen['threshold']}分) | 今开: {chosen['open_pct']*100:+.2f}% | 现价: {chosen['cur_px']:.2f}元")
        print(f"   - ⚡ 唯一挂单指令: {chosen['order_type']} | 触发价: {chosen['trigger_px']:.2f}元")
    else:
        print("🎯 最终结论：`今日五大实盘策略（三进四V4.1、高标首阴V5.1、超跌撬板V2.1、二进三V2.1、一进二V19）全线空仓观望（未触发购买门槛）`")
        print(f"   - 三进四 V4.1 (第1顺位 · 门槛90分): 无标的过线")
        print(f"   - 高标首阴 V5.1 (第2顺位 · 门槛88分): 无标的过线")
        print(f"   - 超跌撬板 V2.1 (第3顺位 · 门槛165分): 无标的过线")
        print(f"   - 二进三 V2.1 (第4顺位 · 门槛90分 · 满96分重点提醒): 无标的过线")
        print(f"   - 一进二 V19 (第5顺位 · 门槛{float(c_12.get('mkt_sentiment',{}).get('tot_thr',304.8))}分): 无标的过线")
    p23_96 = [x for x in res_23 if x.get("passed_strict96")]
    if p23_96:
        s96 = "，".join(f"{x['code']} {x['name']}({x['score_base']}分)" for x in p23_96)
        print(f"   - ★二进三 V2.1 满96分高胜率单独重点提醒: {s96}")
    print("=" * 88)

    print("\n--- [三进四 V4.1 | 第1顺位 · 门槛90分 · 7因子风险开关+7.0%/+5.0%] ---")
    for x in res_34:
        print(f"  {x['code']} {x['name']:<6s} | 得分: {x['score_base']:>4} | 把握度: {x['rk_prio']:>6.2f} | 今开: {x['open_pct']*100:+.2f}% | 硬骨架: {x['passed_skeleton']} ({x.get('breakdown_str', '')[:35]})")
    if not res_34: print("  今日无候选池标的")

    print("\n--- [高标首阴 V5.1 | 第2顺位 · 门槛88分] ---")
    for x in res_hd:
        print(f"  {x['code']} {x['name']:<6s} | 得分: {x['score_base']:>4} | 把握度: {x['rk_prio']:>6.2f} | 今开: {x['open_pct']*100:+.2f}% | 否决: {x['is_vetoed']} ({'；'.join(x['veto_reasons']) if x['veto_reasons'] else '无'})")
    if not res_hd: print("  今日无候选池标的")

    zt_note = f"09:25非ST竞价涨停={pry_meta['zt_open_cnt']}家(样本{pry_meta['valid_mkt_cnt']})" if pry_meta.get("scanned") else "未触发市场扫描"
    print(f"\n--- [超跌撬板 V2.1 | 第3顺位 · 门槛165分 · {zt_note}] ---")
    for x in res_pry:
        veto_s = "；".join(x["veto_reasons"]) if x["veto_reasons"] else "过线可买"
        print(f"  {x['code']} {x['name']:<6s} | 静态{x['static_score']} -> 总分{x['score_base']:>4} | 把握度: {x['rk_prio']:>6.2f} | 今开: {x['open_pct']*100:+.2f}% | dyn_tp=+{x['dyn_tp_pct']:.2f}% | {veto_s}")
    if not res_pry: print("  今日无候选池标的")

    print("\n--- [二进三 V2.1 | 第4顺位 · 门槛90分 · 满96分重点提醒] ---")
    for x in res_23:
        tag96 = " ★满96高胜率" if x.get("passed_strict96") else ""
        veto_s = "；".join(x["veto_reasons"]) if x["veto_reasons"] else "无"
        print(f"  {x['code']} {x['name']:<6s} | 得分: {x['score_base']:>4}{tag96} | 把握度: {x['rk_prio']:>6.2f} | 今开: {x['open_pct']*100:+.2f}% | 否决: {veto_s}")
    if not res_23: print("  今日无候选池标的")

    print("\n--- [一进二 V19 | 第5顺位 · Top 10] ---")
    for x in res_12[:10]:
        print(f"  {x['code']} {x['name']:<6s} | 得分: {x['score_base']:>5.1f} | 把握度: {x['rk_prio']:>6.2f} | 今开: {x['open_pct']*100:+.2f}% | 门禁: {x['gate_ok']} | 题材: {x['plate']}")
    if not res_12: print("  今日无候选池标的")

    print("\n[V4.1/V2.1 离场锚] 三进四V4.1: 连板7因子>=1收紧13:45护利至+7.0%(0命中+5.0%) | 超跌V2.1: 09:25<5家熔断+T+1放飞兼14:55跌1.5%清+强阳/止血+3%+T+2~T+4阶梯 | 二进三V2.1: 13:45摸+8.5%破+6.5%")
    print(f"[+] 全流程决策完成，耗时: {time.time()-t0:.2f}s")

if __name__ == "__main__":
    main()

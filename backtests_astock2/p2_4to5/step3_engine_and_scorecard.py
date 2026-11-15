#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""四进五纯整数打分卡策略与撮合引擎 (<=150 行)"""
import os, sys, pickle, numpy as np, pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
ASTOCK2_DIR = f"{ROOT}/sim-portfolio/backtests_astock2"
if ASTOCK2_DIR not in sys.path: sys.path.insert(0, ASTOCK2_DIR)
OUT_DIR = f"{ASTOCK2_DIR}/p2_4to5"
ENRICHED_PATH = f"{OUT_DIR}/cand_4to5_enriched.parquet"
BARS_5M_PATH = f"{OUT_DIR}/cand_4to5_5m_bars.parquet"
BARS_PKL = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/code_bars_5y.pkl"

DEFAULT_WEIGHTS = {
    "mkt_ge6": -10, "tox": -10, "hr100_lt12": -10, "rfmcap_ge45": -8, "op_lt_neg2": -8, "op_gt_65": -5,
    "mkt_highest": 3, "sole_4b": 2, "op_mod": 2, "px_10_20": 2, "quant": 2, "op_brk_ge1": 2,
    "tb_ge3": 1, "hr_safe": 1, "rfmcap_lt25": 1, "top1_op": 1, "brk60": 1, "ech": 1,
    "rival_ge3": -3, "surf": -3, "px_ge30": -2, "to_shrink": -2, "op_brk_eq0": -2, "tb_le1": -2, "blackout": -2
}

def calc_score(r, w=None):
    if w is None: w = DEFAULT_WEIGHTS
    s = 0
    if r.mkt_max_board_prev >= 6: s += w["mkt_ge6"]
    if r.has_tox_notice == 1: s += w["tox"]
    if r.headroom_100 < 0.12: s += w["hr100_lt12"]
    if r.real_free_mcap >= 45.0: s += w["rfmcap_ge45"]
    if r.open_pct < -0.02: s += w["op_lt_neg2"]
    if r.open_pct > 0.065: s += w["op_gt_65"]
    if r.is_mkt_highest_4b == 1: s += w["mkt_highest"]
    if r.is_sole_4b == 1: s += w["sole_4b"]
    if 0.015 <= r.open_pct <= 0.055: s += w["op_mod"]
    if 10.0 <= r.px_d4 <= 20.0: s += w["px_10_20"]
    if r.lhb_quant_cnt >= 1: s += w["quant"]
    if r.open_board_count >= 1: s += w["op_brk_ge1"]
    if r.turn_boards_4d >= 3: s += w["tb_ge3"]
    if r.headroom_100 >= 0.22: s += w["hr_safe"]
    if r.real_free_mcap < 25.0: s += w["rfmcap_lt25"]
    if r.is_top1_4b_open == 1: s += w["top1_op"]
    if r.clean_brk60 == 1: s += w["brk60"]
    if r.has_4321_echelon == 1: s += w["ech"]
    if r.b4_rival_cnt >= 3: s += w["rival_ge3"]
    if r.surf_yz_buy >= 1: s += w["surf"]
    if r.px_d4 >= 30.0: s += w["px_ge30"]
    if r.to_ratio_d4_d3 < 0.5: s += w["to_shrink"]
    if r.open_board_count == 0: s += w["op_brk_eq0"]
    if r.turn_boards_4d <= 1: s += w["tb_le1"]
    if r.is_earn_blackout_month == 1: s += w["blackout"]
    return int(s)

def sim_trade(r, cb, bars_5m_map):
    c6, bd = str(r.code).zfill(6), str(r.buy_date)
    pos = cb["date_to_pos"].get(bd, -1)
    if pos < 0 or pos >= len(cb["dts"]) - 1: return None
    op, zt = float(cb["open"][pos]), float(cb["zt_px"][pos])
    if op >= zt - 0.005: return None
    bpx = op; n = len(cb["dts"]); k = pos + 1; spx = None; s_dt = None
    while k < n:
        ok, pck, clk, ztk = float(cb["open"][k]), float(cb["pre_c"][k]), float(cb["close"][k]), float(cb["zt_px"][k])
        arr_k = bars_5m_map.get((c6, cb["dts"][k]))
        if arr_k is not None:
            peak = ok
            for row in arr_k:
                hh, bo, bh, bl = int(row[0]), row[1], row[2], row[3]
                if hh >= 1345 and peak >= pck * 1.085 and bl <= pck * 1.050 and row[4] < ztk - 0.01:
                    spx = float(min(bo, pck * 1.050)); s_dt = cb["dts"][k]; break
                if bh > peak: peak = bh
            if spx is not None: break
        if bool(cb["is_zt"][k]): k += 1; continue
        spx = clk; s_dt = cb["dts"][k]; break
    if spx is None: k = n - 1; spx = float(cb["close"][k]); s_dt = cb["dts"][k]
    pos_s = cb["date_to_pos"].get(s_dt, k)
    ret = (spx * cb["adjf"][pos_s]) / (bpx * cb["adjf"][pos]) - 1.0 - 0.0020
    return {"buy_date": bd, "code": c6, "name": r.name, "score": getattr(r, "score", 0), "buy_px": bpx, "sell_date": s_dt, "sell_px": spx, "ret": ret, "hold_days": pos_s - pos}

def generate_ledgers():
    df = pd.read_parquet(ENRICHED_PATH); df = df[df["buyable_open"]].copy()
    with open(BARS_PKL, "rb") as f: cb_map = pickle.load(f)["code_bars"]
    df_5m = pd.read_parquet(BARS_5M_PATH)
    b5m = {(c6, d): g[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float) for (c6, d), g in df_5m.groupby(["c6", "date"], sort=False)}
    df["score"] = [calc_score(r) for r in df.itertuples(index=False)]
    sub = df[df["score"] >= 7].sort_values(["buy_date", "score", "open_pct"], ascending=[True, False, False]).copy()
    trades = [sim_trade(r, cb_map.get(str(r.code).zfill(6)), b5m) for r in sub.itertuples(index=False)]
    tdf = pd.DataFrame([t for t in trades if t is not None])
    tdf["year"] = pd.to_datetime(tdf["buy_date"]).dt.year
    single_list, cur_free = [], "2000-01-01"
    for d, g in tdf.groupby("buy_date", sort=True):
        best = g.sort_values(["score", "buy_px"], ascending=[False, False]).iloc[0]
        if best["buy_date"] >= cur_free: single_list.append(best); cur_free = best["sell_date"]
    tdf_s = pd.DataFrame(single_list)
    tdf_s.to_csv(f"{OUT_DIR}/best_4to5_ledger.csv", index=False, encoding="utf-8-sig")
    tdf.to_csv(f"{OUT_DIR}/equal_weight_4to5_ledger.csv", index=False, encoding="utf-8-sig")
    print(f"[Done] Best 4to5 ledger saved: Single={len(tdf_s)}, Equal={len(tdf)}")
    return tdf_s, tdf

if __name__ == "__main__":
    generate_ledgers()

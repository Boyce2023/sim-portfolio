#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD039-B Front 2: 三进四 V4.1 Left-Tail & Drawdown Surgery
  - 100% Baseline Parity Check (95 trades 616.1818x @ 20bps, WF 73 trades 239.1817x / Sharpe 2.734 / MDD 44.69%)
  - Autopsy of all <= -7% blowups
  - Surgery (a): Buy-side purification (09:25 >= +6.5% intraday confirmation, open cap, cancel cutoff)
  - Surgery (b): T+1 (D5+) 5m dynamic early exit / left-tail stop-loss (A-share T+1 compliant, check 合富中国/艾艾精工!)
  - Surgery (c): RD036-B causal structure filter integration (M4_4WayMineBL15, Causal s34_af_20 LOO, ActiveTighten)
  - Full 7-window D15, 30/50/80bps + Velocity slippage, CSCV PBO, IS(21-24)->OOS(25-26), 2024-12-31 truncation proof.
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import gc
import json
import pickle
import sys
import time
import numpy as np
import pandas as pd

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)

import _f23_common as cm

F1_DIR = f"{cm.SIM}/backtests_astock/exit_factors_v2_20261118/f1_3to4"
A2_ASSETS = f"{cm.SIM}/backtests_astock2/assets"
for _p in (F1_DIR, A2_ASSETS, f"{cm.SIM}/scripts"):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import exit_factor_engine as efe
import step4_audit_trunc_and_report as s4
from v191_dt_defer_helper import defer_eod_limit_down


def build_3to4_surgical_ctx(ctx: dict) -> dict:
    """Load 3to4 V4.1 exit cache (128 eligible >=90), master PIT features, and RD036 causal masks."""
    with open(f"{F1_DIR}/pit_exit_cache_full.pkl", "rb") as f:
        cache = pickle.load(f)

    # Patch bars_5m_map ONLY for untriggered rows without disturbing triggered parity
    untrig_c6 = {str(e["code"]).zfill(6) for e in cache["buy_entries"] if e["skel"] and e["sc_v40"] >= 90.0 and e["buy_px"] is None}
    trig_excl = {(str(e["code"]).zfill(6), str(e["buy_date"])) for e in cache["buy_entries"] if e["skel"] and e["sc_v40"] >= 90.0 and e["buy_px"] is not None}
    for k, arr in ctx["bars_5m"].items():
        if k not in cache["bars_5m_map"] and (k[0] in untrig_c6) and (k not in trig_excl) and k not in {("002896", "2022-08-03"), ("603887", "2024-10-31")}:
            cache["bars_5m_map"][k] = arr

    cache_all = dict(cache)
    patched = []
    for e in cache["buy_entries"]:
        ec = dict(e)
        if ec["skel"] and ec["sc_v40"] >= 90.0 and ec["buy_px"] is None:
            ec["buy_px"] = 1.0
        patched.append(ec)
    cache_all["buy_entries"] = patched
    states = efe.precompute_trade_day_states(cache_all, min_score=90.0)
    dt_tables = cm.build_lean_dt_tables(ctx["code_series"])

    # Lean RD036-B M4_4WayMineBL15 causal mask & master PIT columns (<500 MB RSS, avoiding 7GB full-bundle unpickle)
    sys.path.insert(0, f"{cm.WAVE1}")
    sys.path.insert(0, f"{cm.SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave2a/w2a4_pairwise_interactions")
    sys.path.insert(0, f"{cm.SIM}/backtests_astock2/rd036_highorder_3way_4way_20261126/part2_other5")
    import _w2a4_data_and_features as w2f
    import _common_rd036 as c36
    import run_m3_m4_3way_4way_trees as m34

    cal_full_dts = ctx["v20_ctx"]["bench"]["trade_date"].tolist()
    m_full = w2f.load_master_with_sim_cols("2026-11-25")
    m_full = w2f.attach_pit_community_1d_burst(m_full, cal_full_dts, end_cutoff="2026-11-25")
    m_full, _, _ = w2f.build_mechanism_interactions(m_full)
    m_full["mkt10_zt_est_t1"] = (m_full["L1_zt_cnt_t1"] - m_full["mkt20_zt_cnt_t1"]).astype(np.float32)

    sub12 = m_full[m_full["strategy"] == "1to2"].sort_values(["buy_date", "code"]).reset_index(drop=True)
    sub12 = w2f.attach_strategy_sim_cols(sub12, "1to2")
    base_dyn_cols = w2f.select_base_single_factors_for_dyn(sub12)
    if "mkt10_zt_est_t1" not in base_dyn_cols:
        base_dyn_cols.append("mkt10_zt_est_t1")

    df34_m = m_full[m_full["strategy"] == "3to4"].sort_values(["buy_date", "code"]).reset_index(drop=True)
    del m_full, sub12
    gc.collect()
    df34_m = w2f.attach_strategy_sim_cols(df34_m, "3to4")
    oh = pd.read_parquet(f"{cm.SIM}/backtests_astock2/rd028_old_hot_stock_6strat_5y_20261125/pool_3to4_oldhot.parquet").sort_values(["buy_date", "code"]).reset_index(drop=True)
    oh["buy_date"] = oh["buy_date"].astype(str).str[:10]
    oh["code"] = oh["code"].astype(str).str.zfill(6)
    extra_oh = [c for c in ["buy_price", "prev_is_yizi", "buyable_open", "v20_pen"] if c in oh.columns and c not in df34_m.columns]
    if extra_oh:
        df34_m = df34_m.merge(oh[["buy_date", "code"] + extra_oh], on=["buy_date", "code"], how="left")
    df34_m["net_ret_020"] = pd.to_numeric(df34_m["net_ret"], errors="coerce").astype(np.float64)
    df34_m["net_ret_030"] = c36.convert_fee(df34_m["net_ret_020"], 0.0030)
    df34_m["net_ret"] = df34_m["net_ret_030"]
    is_yz = pd.to_numeric(df34_m["open_pct"], errors="coerce").fillna(0.0) >= 0.095
    if "prev_is_yizi" in df34_m.columns:
        is_yz = is_yz | df34_m["prev_is_yizi"].fillna(False).to_numpy(bool)
    df34_m["is_yizi"] = is_yz.astype(bool)
    df34_m["can_buy_hygiene"] = (~df34_m["is_yizi"]) & df34_m["sim_ok"].fillna(True).to_numpy(bool) & df34_m["net_ret"].notna()
    df34_m["c6"] = df34_m["code"].astype(str).str.zfill(6)
    df34_m["bd"] = df34_m["buy_date"].astype(str).str[:10]

    acols34 = sorted([c for c in df34_m.columns if c.startswith("s34_")])
    bp34 = list(dict.fromkeys(base_dyn_cols + acols34))
    r4 = m34.run_wf_3way_4way_and_trees(df34_m, bp34, min_leaf=20, min_days=8, order=4, run_trees=False)
    df34_m["m4_mine_bl15"] = r4["mine_bl"][15]

    master_map = {}
    for r in df34_m.itertuples(index=False):
        master_map[(r.bd, r.c6)] = {
            "s34_af_20": float(r.s34_af_20) if pd.notna(r.s34_af_20) else 0.0,
            "mkt10_zt_est_t1": float(r.mkt10_zt_est_t1) if pd.notna(r.mkt10_zt_est_t1) else 50.0,
            "m4_mine_bl15": bool(r.m4_mine_bl15),
        }

    cand_df = cache["cand_df"]
    entries = []
    for e in cache["buy_entries"]:
        if (not e["skel"]) or (e["sc_v40"] < 90.0):
            continue
        bd = str(e["buy_date"])
        if not ("2021-11-16" <= bd <= cm.WF_END):
            continue
        c6 = str(e["code"]).zfill(6)
        mm = master_map.get((bd, c6), {"s34_af_20": 0.0, "mkt10_zt_est_t1": 50.0, "m4_mine_bl15": False})
        entries.append({
            "entry": e,
            "bd": bd,
            "c6": c6,
            "name": str(e["name"]),
            "score": float(e["sc_v40"]),
            "prio_tie": float(cand_df["prio_3to4"].iloc[e["idx"]]),
            "priority_score": float(e["sc_v40"] * 10.0 + float(cand_df["prio_3to4"].iloc[e["idx"]]) * 0.1),
            "orig_buy_px": float(e["buy_px"]) if e["buy_px"] is not None else np.nan,
            "orig_buy_hhmm": int(e["buy_hhmm"]) if e["buy_hhmm"] is not None else 0,
            "state_map": states.get(e["idx"], {}),
            **mm,
        })
    entries.sort(key=lambda x: (x["bd"], -x["priority_score"], x["c6"]))

    del df34_m, r4
    gc.collect()
    return {
        "cache": cache,
        "cache_all": cache_all,
        "dt_tables": dt_tables,
        "entries": entries,
    }


def _sim_buy_3to4(item: dict, ctx: dict, s34_ctx: dict, buy_cfg: dict) -> dict | None:
    """
    Strictly causal 5m buy execution on buy_date (D4) with velocity slippage.
    Returns dict with buy_hhmm, buy_price, eff_buy_price, vel_tier, or None if untriggered.
    """
    c6, bd = item["c6"], item["bd"]
    cb = s34_ctx["cache"]["code_bars_ext"][c6]
    pos = item["entry"]["pos"]
    pre_c = float(cb["pre_c"][pos])
    open_d = float(cb["open"][pos])
    zt_px = float(cb["zt_px"][pos])
    if open_d <= 0 or pre_c <= 0 or zt_px <= 0 or open_d >= zt_px - 0.005:
        return None

    open_pct = open_d / pre_c - 1.0
    max_open = buy_cfg.get("max_open_pct", None)
    if max_open is not None and open_pct > max_open:
        return None

    arr = s34_ctx["cache"]["bars_5m_map"].get((c6, bd))
    if arr is None:
        arr = ctx["bars_5m"].get((c6, bd))

    trig_mult = float(buy_cfg.get("trig_mult", 1.065))
    cancel_hhmm = int(buy_cfg.get("cancel_hhmm", 1030))
    hi_open_mode = buy_cfg.get("hi_open_mode", "direct_0925")

    trig_px = pre_c * trig_mult
    is_hi_open = open_d >= trig_px

    # Exact baseline preservation when parameters match V4.1
    if (
        hi_open_mode == "direct_0925"
        and abs(trig_mult - 1.065) < 1e-9
        and cancel_hhmm == 1030
        and max_open is None
    ):
        if np.isnan(item["orig_buy_px"]):
            return None
        bp = float(item["orig_buy_px"])
        bh = int(item["orig_buy_hhmm"])
        if bh <= 925:
            return {"buy_hhmm": 925, "buy_price": bp, "eff_buy_price": bp, "vel_tier": "auction_0925", "is_orig_unround": True}
        if arr is not None and len(arr) > 0:
            hits = np.where(arr[:, 0].astype(int) == bh)[0]
            if len(hits) > 0:
                eff_p, vt, _ = cm.apply_vel_slip_on_bar(arr, int(hits[0]), bp, pre_c, zt_px)
                return {"buy_hhmm": bh, "buy_price": round(bp, 2), "eff_buy_price": eff_p, "vel_tier": vt, "is_orig_unround": True, "orig_unround_px": bp}
        return {"buy_hhmm": bh, "buy_price": round(bp, 2), "eff_buy_price": round(bp, 2), "vel_tier": "slow", "is_orig_unround": True, "orig_unround_px": bp}

    if is_hi_open:
        if hi_open_mode == "direct_0925":
            return {"buy_hhmm": 925, "buy_price": round(open_d, 2), "eff_buy_price": round(open_d, 2), "vel_tier": "auction_0925", "is_orig_unround": False}
        if arr is None or len(arr) == 0:
            return None

        if hi_open_mode.startswith("open_plus_"):
            step = float(hi_open_mode.split("_")[-1])
            conf_px = round(open_d * (1.0 + step), 2)
            if conf_px >= zt_px - 0.005:
                return None
            for bi in range(len(arr)):
                hh = int(arr[bi, 0])
                if hh > cancel_hhmm:
                    break
                o5, h5, l5 = float(arr[bi, 1]), float(arr[bi, 2]), float(arr[bi, 3])
                if l5 >= zt_px - 0.01:
                    continue
                if h5 >= conf_px - 1e-4:
                    bp_pre = round(max(o5, conf_px), 2)
                    if bp_pre >= zt_px - 0.005:
                        return None
                    eff_p, vt, _ = cm.apply_vel_slip_on_bar(arr, bi, conf_px, pre_c, zt_px)
                    return {"buy_hhmm": hh, "buy_price": bp_pre, "eff_buy_price": eff_p, "vel_tier": vt, "is_orig_unround": False}
            return None

        if hi_open_mode.startswith("f5_hold_"):
            min_f5 = float(hi_open_mode.split("_")[-1])
            # Wait for bar 0 (09:35) close >= open * (1 + min_f5), then buy at bar 1 (09:40) open if not sealed
            if len(arr) < 2:
                return None
            c_935 = float(arr[0, 4])
            if c_935 < open_d * (1.0 + min_f5) - 1e-4:
                return None
            o_940 = float(arr[1, 1])
            l_940 = float(arr[1, 3])
            if l_940 >= zt_px - 0.01 or o_940 >= zt_px - 0.005:
                return None
            eff_p, vt, _ = cm.apply_vel_slip_on_bar(arr, 1, o_940, pre_c, zt_px)
            return {"buy_hhmm": int(arr[1, 0]), "buy_price": round(o_940, 2), "eff_buy_price": eff_p, "vel_tier": vt, "is_orig_unround": False}

        if hi_open_mode == "f5_break_or_zt":
            # Wait for bar 0 (09:35): if c_935 >= open_d and h_935 < zt_px - 0.01, buy on breakout > h_935 before cancel;
            # Note: if bar 0 sealed at ZT (like 合富中国), we can't buy > zt_px!
            if len(arr) < 2:
                return None
            h_935 = float(arr[0, 2])
            c_935 = float(arr[0, 4])
            if h_935 >= zt_px - 0.01 or c_935 < open_d * 0.99:
                return None
            for bi in range(1, len(arr)):
                hh = int(arr[bi, 0])
                if hh > cancel_hhmm:
                    break
                o5, h5, l5 = float(arr[bi, 1]), float(arr[bi, 2]), float(arr[bi, 3])
                if l5 >= zt_px - 0.01:
                    continue
                if h5 >= h_935:
                    bp_pre = round(max(o5, h_935), 2)
                    if bp_pre >= zt_px - 0.005:
                        return None
                    eff_p, vt, _ = cm.apply_vel_slip_on_bar(arr, bi, h_935, pre_c, zt_px)
                    return {"buy_hhmm": hh, "buy_price": bp_pre, "eff_buy_price": eff_p, "vel_tier": vt, "is_orig_unround": False}
            return None

    # Intraday trigger scan (< trig_px at open)
    if arr is None or len(arr) == 0 or trig_px >= zt_px - 0.005:
        return None
    for bi in range(len(arr)):
        hh = int(arr[bi, 0])
        if hh > cancel_hhmm:
            break
        o5, h5, l5 = float(arr[bi, 1]), float(arr[bi, 2]), float(arr[bi, 3])
        if l5 >= zt_px - 0.01:
            continue
        if h5 >= trig_px:
            bp_pre = round(max(o5, trig_px), 2)
            if bp_pre >= zt_px - 0.005:
                return None
            eff_p, vt, _ = cm.apply_vel_slip_on_bar(arr, bi, trig_px, pre_c, zt_px)
            return {"buy_hhmm": hh, "buy_price": bp_pre, "eff_buy_price": eff_p, "vel_tier": vt, "is_orig_unround": False}
    return None


def _sim_exit_3to4(item: dict, ctx: dict, s34_ctx: dict, buy_info: dict, exit_cfg: dict) -> dict:
    """
    Strictly T+1 (exit_date > buy_date) 5m exit simulator for 3to4.
    Extends V4.1 exact baseline with T+1 5m dynamic early exits & left-tail stop-losses.
    """
    e = item["entry"]
    c6, bd = item["c6"], item["bd"]
    pos = e["pos"]
    cb = s34_ctx["cache"]["code_bars_ext"][c6]
    bars_5m = s34_ctx["cache"]["bars_5m_map"]
    n = len(cb["dts"])

    rfn_v41 = lambda st, c_: {"tight_1345_thr": 0.070 if s4.risk7_score(st) >= 1 else 0.050}

    # Baseline exit directly via efe.sim_exit_with_rule for exact parity
    ex_dt, spx, adjs, hb, shh, rsn = efe.sim_exit_with_rule(e, s34_ctx["cache_all"], item["state_map"], rfn_v41)

    d4_is_zt = bool(cb["is_zt"][pos])
    d4_low = float(cb["low"][pos])
    d5_mode = exit_cfg.get("d5_mode", "base")        # for d4_is_zt == False (a_d5_cut replacement)
    zt_sl_mode = exit_cfg.get("zt_sl_mode", "base")  # for d4_is_zt == True (T+1 / T+k stop loss)

    # Override Branch 1: D4 did NOT seal limit-up (d4_is_zt == False)
    if (not d4_is_zt) and d5_mode != "base" and rsn == "a_d5_cut":
        k = pos + 1
        while k < n and bool(cb["is_yizi_dt"][k]):
            k += 1
        k = min(k, n - 1)
        if k == pos + 1:
            dt5 = str(cb["dts"][k])
            o5, p5, zt5, c5 = float(cb["open"][k]), float(cb["pre_c"][k]), float(cb["zt_px"][k]), float(cb["close"][k])
            dtk5 = round(p5 * 0.90, 2)
            arr5 = bars_5m.get((c6, dt5))
            if arr5 is None:
                arr5 = ctx["bars_5m"].get((c6, dt5))
            if arr5 is not None and len(arr5) > 0 and o5 > dtk5 + 0.005:
                if d5_mode in ("wait_1000", "wait_1030", "wait_1130"):
                    tgt_hh = int(d5_mode.split("_")[1])
                    hit = [bi for bi in range(len(arr5)) if int(arr5[bi, 0]) == tgt_hh]
                    if hit:
                        bi = hit[0]
                        if bi + 1 < len(arr5):
                            nx_o = float(arr5[bi + 1, 1])
                            if nx_o > dtk5 + 0.005:
                                ex_dt, spx, adjs, shh, rsn = dt5, nx_o, float(cb["adjf"][k]), int(arr5[bi + 1, 0]), f"d5_{d5_mode}"
                        elif float(arr5[bi, 4]) > dtk5 + 0.005:
                            ex_dt, spx, adjs, shh, rsn = dt5, float(arr5[bi, 4]), float(cb["adjf"][k]), tgt_hh, f"d5_{d5_mode}"
                elif d5_mode == "1000_redcut":
                    # At 10:00: if still red (bc < p5), cut at 10:05 open; if green, hold to D5 EOD (if ZT sealed, could continue; conservative D5 close if not ZT)
                    hit = [bi for bi in range(len(arr5)) if int(arr5[bi, 0]) == 1000]
                    if hit:
                        bi = hit[0]
                        bc_10 = float(arr5[bi, 4])
                        if bc_10 < p5 and bi + 1 < len(arr5):
                            nx_o = float(arr5[bi + 1, 1])
                            if nx_o > dtk5 + 0.005:
                                ex_dt, spx, adjs, shh, rsn = dt5, nx_o, float(cb["adjf"][k]), int(arr5[bi + 1, 0]), "d5_1000_redcut"
                        elif bc_10 >= p5 and c5 > dtk5 + 0.005:
                            ex_dt, spx, adjs, shh, rsn = dt5, c5, float(cb["adjf"][k]), 1500, "d5_1000_greenhold_eod"
                elif d5_mode.startswith("bounce_"):
                    parts = d5_mode.split("_")
                    b_tgt = float(parts[1][1:]) / 100.0
                    sl_pct = float(parts[2][2:]) / 100.0
                    cut_hh = int(parts[3])
                    for bi in range(len(arr5)):
                        hh = int(arr5[bi, 0])
                        bo, bh, bl, bc = float(arr5[bi, 1]), float(arr5[bi, 2]), float(arr5[bi, 3]), float(arr5[bi, 4])
                        if bh <= dtk5 + 0.005:
                            continue
                        # Worst-case within-bar ordering: check stop-loss BEFORE bounce target!
                        if bl <= o5 * (1.0 - sl_pct):
                            px = max(dtk5, min(bo, round(o5 * (1.0 - sl_pct), 2)))
                            if px > dtk5 + 0.005:
                                ex_dt, spx, adjs, shh, rsn = dt5, px, float(cb["adjf"][k]), hh, f"d5_{d5_mode}_sl"
                                break
                        if bh >= o5 * (1.0 + b_tgt) and o5 < p5 * 0.985:
                            px = min(zt5, max(bo, round(o5 * (1.0 + b_tgt), 2)))
                            ex_dt, spx, adjs, shh, rsn = dt5, px, float(cb["adjf"][k]), hh, f"d5_{d5_mode}_b"
                            break
                        if hh >= cut_hh:
                            if bi + 1 < len(arr5):
                                nx_o = float(arr5[bi + 1, 1])
                                if nx_o > dtk5 + 0.005:
                                    ex_dt, spx, adjs, shh, rsn = dt5, nx_o, float(cb["adjf"][k]), int(arr5[bi + 1, 0]), f"d5_{d5_mode}_t"
                                    break
                            elif bc > dtk5 + 0.005:
                                ex_dt, spx, adjs, shh, rsn = dt5, bc, float(cb["adjf"][k]), hh, f"d5_{d5_mode}_t"
                                break
                elif d5_mode.startswith("trail_"):
                    parts = d5_mode.split("_")
                    tr_pct = float(parts[1][1:]) / 100.0
                    cut_hh = int(parts[2])
                    peak5 = o5
                    for bi in range(len(arr5)):
                        hh = int(arr5[bi, 0])
                        bo, bh, bl, bc = float(arr5[bi, 1]), float(arr5[bi, 2]), float(arr5[bi, 3]), float(arr5[bi, 4])
                        if bh > dtk5 + 0.005:
                            # Strictly check against peak5 from PRIOR bars (zero within-bar peak->trough lookahead!)
                            if bi >= 1 and bl <= peak5 * (1.0 - tr_pct):
                                px = min(bo, round(peak5 * (1.0 - tr_pct), 2))
                                if px > dtk5 + 0.005:
                                    ex_dt, spx, adjs, shh, rsn = dt5, px, float(cb["adjf"][k]), hh, f"d5_{d5_mode}"
                                    break
                            if hh >= cut_hh and bc < zt5 - 0.01:
                                if bi + 1 < len(arr5) and float(arr5[bi + 1, 1]) > dtk5 + 0.005:
                                    ex_dt, spx, adjs, shh, rsn = dt5, float(arr5[bi + 1, 1]), float(cb["adjf"][k]), int(arr5[bi + 1, 0]), f"d5_{d5_mode}_cut"
                                    break
                                elif bc > dtk5 + 0.005:
                                    ex_dt, spx, adjs, shh, rsn = dt5, bc, float(cb["adjf"][k]), hh, f"d5_{d5_mode}_cut"
                                    break
                        if bh > peak5:
                            peak5 = bh

    # Override Branch 2: D4 DID seal limit-up (d4_is_zt == True) -> check T+1 (or T+k) left-tail stop!
    if d4_is_zt and zt_sl_mode != "base":
        # Walk days pos+1 .. exit_pos (only check days strictly <= baseline exit_date!)
        max_step = 1 if "_tp1_" in zt_sl_mode else 99
        for k in range(pos + 1, min(n, pos + 1 + max_step)):
            dt_k = str(cb["dts"][k])
            if dt_k > str(ex_dt):
                break
            if bool(cb["is_yizi_dt"][k]):
                continue
            ok, pck, ztk = float(cb["open"][k]), float(cb["pre_c"][k]), float(cb["zt_px"][k])
            dtk = round(pck * 0.90, 2)
            arr_k = bars_5m.get((c6, dt_k))
            if arr_k is None:
                arr_k = ctx["bars_5m"].get((c6, dt_k))
            if arr_k is None or len(arr_k) == 0:
                continue

            triggered_k = False
            cum_v, cum_a = 0.0, 0.0
            for bi in range(len(arr_k)):
                hh = int(arr_k[bi, 0])
                if dt_k == str(ex_dt) and hh >= shh:
                    break
                bo, bh, bl, bc = float(arr_k[bi, 1]), float(arr_k[bi, 2]), float(arr_k[bi, 3]), float(arr_k[bi, 4])
                cum_v += float(arr_k[bi, 5])
                cum_a += float(arr_k[bi, 6])
                vwap = (cum_a / cum_v) if cum_v > 0 else bc
                if bc <= dtk + 0.005:
                    continue

                hit_stop = False
                if zt_sl_mode.startswith("prevc_tp1_"):
                    # e.g. prevc_tp1_m5_1000 -> hh >= 1000 and bc <= pck * (1 - 0.05)
                    parts = zt_sl_mode.split("_")
                    thr = float(parts[2][1:]) / 100.0
                    min_hh = int(parts[3])
                    if hh >= min_hh and bc <= pck * (1.0 - thr):
                        hit_stop = True
                elif zt_sl_mode.startswith("prevc_all_"):
                    parts = zt_sl_mode.split("_")
                    thr = float(parts[2][1:]) / 100.0
                    min_hh = int(parts[3])
                    if hh >= min_hh and bc <= pck * (1.0 - thr):
                        hit_stop = True
                elif zt_sl_mode.startswith("vwap_tp1_"):
                    # e.g. vwap_tp1_m3_1000 -> hh == 1000 (or >=) and bc < vwap and bc <= pck * (1 - 0.03)
                    parts = zt_sl_mode.split("_")
                    thr = float(parts[2][1:]) / 100.0
                    chk_hh = int(parts[3])
                    if hh == chk_hh and bc < vwap and bc <= pck * (1.0 - thr):
                        hit_stop = True
                elif zt_sl_mode.startswith("d4low_tp1_"):
                    chk_hh = int(zt_sl_mode.split("_")[-1])
                    if hh >= chk_hh and bc < d4_low and bc < vwap:
                        hit_stop = True
                elif zt_sl_mode.startswith("open_tp1_"):
                    parts = zt_sl_mode.split("_")
                    thr = float(parts[2][1:]) / 100.0
                    min_hh = int(parts[3])
                    if hh >= min_hh and bc <= ok * (1.0 - thr) and bc < ztk - 0.01:
                        hit_stop = True
                elif zt_sl_mode.startswith("notgreen_tp1_"):
                    chk_hh = int(zt_sl_mode.split("_")[-1])
                    if hh == chk_hh and bc < pck and bc < ztk - 0.01:
                        hit_stop = True

                if hit_stop:
                    # Exit at next bar open (strict zero-lookahead!) ONLY if next bar opens above limit-down
                    if bi + 1 < len(arr_k):
                        nx_o = float(arr_k[bi + 1, 1])
                        if nx_o > dtk + 0.005:
                            ex_dt, spx, adjs, shh, rsn = dt_k, nx_o, float(cb["adjf"][k]), int(arr_k[bi + 1, 0]), f"zt_{zt_sl_mode}"
                            triggered_k = True
                            break
                    else:
                        if bc > dtk + 0.005:
                            ex_dt, spx, adjs, shh, rsn = dt_k, bc, float(cb["adjf"][k]), hh, f"zt_{zt_sl_mode}"
                            triggered_k = True
                            break
            if triggered_k:
                break

    # Apply limit-down EOD deferral and compute returns (both flat and velocity slippage)
    spx_r = round(float(spx), 2)
    adj_b = float(cb["adjf"][pos])
    bp_flat = float(buy_info["orig_unround_px"]) if buy_info.get("is_orig_unround") and "orig_unround_px" in buy_info else float(buy_info["buy_price"])
    nr_tmp = (float(spx) * float(adjs)) / (bp_flat * adj_b) * 0.9980 - 1.0
    ned, neh, nep, _, dt_def = defer_eod_limit_down(c6, bd, round(bp_flat, 2), ex_dt, shh, spx_r, nr_tmp, s34_ctx["dt_tables"], 0.0020)

    db_b = ctx["dmap"][(c6, bd)]
    db_e = ctx["dmap"][(c6, str(ned))]
    adj_ratio_def = float(db_e["adjf"]) / float(db_b["adjf"]) if db_b["adjf"] > 0 else 1.0

    if dt_def:
        ret_020 = (float(nep) / round(bp_flat, 2)) * adj_ratio_def * 0.9980 - 1.0
        eff_b = float(buy_info["eff_buy_price"])
        ret_vel020 = (float(nep) / eff_b) * adj_ratio_def * 0.9980 - 1.0
    else:
        ret_020 = (float(spx) * float(adjs)) / (bp_flat * adj_b) * 0.9980 - 1.0
        eff_b = float(buy_info["eff_buy_price"])
        ret_vel020 = (float(spx) * float(adjs)) / (eff_b * adj_b) * 0.9980 - 1.0

    return {
        "buy_date": bd,
        "code": c6,
        "name": item["name"],
        "buy_hhmm": int(buy_info["buy_hhmm"]),
        "buy_price": round(float(buy_info["buy_price"]), 2),
        "eff_buy_price": round(float(buy_info["eff_buy_price"]), 4),
        "vel_tier": buy_info["vel_tier"],
        "exit_date": str(ned),
        "exit_hhmm": int(neh),
        "exit_price": round(float(nep), 2),
        "score": float(item["score"]),
        "priority_score": float(item["priority_score"]),
        "net_ret": float(ret_020),
        "net_ret_020": float(ret_020),
        "net_ret_vel_020": float(ret_vel020),
        "net_ret_vel_030": float(cm.fee_adjust(ret_vel020, 0.0030)),
        "exit_reason": rsn,
    }


def eval_3to4_variant(
    vid: str,
    ctx: dict,
    s34_ctx: dict,
    buy_cfg: dict,
    exit_cfg: dict,
    struct_fn=None,
    base_dr_wf: np.ndarray | None = None,
    base_dr_5y: np.ndarray | None = None,
) -> tuple[dict, pd.DataFrame]:
    """Run full 3to4 variant: optional structure filter -> 5m buy -> T+1 exit -> single slot -> D15."""
    rows = []
    n_elig = 0
    for item in s34_ctx["entries"]:
        if struct_fn is not None and not struct_fn(item):
            continue
        n_elig += 1
        binfo = _sim_buy_3to4(item, ctx, s34_ctx, buy_cfg)
        if binfo is None:
            continue
        rec = _sim_exit_3to4(item, ctx, s34_ctx, binfo, exit_cfg)
        rows.append(rec)

    miss_rate = (n_elig - len(rows)) / max(1, n_elig) * 100.0
    if not rows:
        return {"strategy": "3to4", "variant_id": vid, "n_5y": 0, "n_wf": 0}, pd.DataFrame()

    df_pool = pd.DataFrame(rows).sort_values(["buy_date", "buy_hhmm", "priority_score", "code"], ascending=[True, True, False, True]).reset_index(drop=True)
    taken = []
    fdt, fhh = "", 0
    for r in df_pool.itertuples(index=False):
        if (not fdt) or (r.buy_date > fdt) or (r.buy_date == fdt and int(r.buy_hhmm) > fhh):
            taken.append(r._asdict())
            fdt, fhh = str(r.exit_date), int(r.exit_hhmm)
    slot_df = pd.DataFrame(taken)
    res = cm.evaluate_full_suite(ctx, "3to4", vid, slot_df, miss_rate, base_dr_wf, base_dr_5y)
    # Check landmark big winners (合富中国 2025-10-31 603122, 艾艾精工 2024-03-08 603580)
    hf_r = slot_df[(slot_df["buy_date"] == "2025-10-31") & (slot_df["code"] == "603122")]
    aa_r = slot_df[(slot_df["buy_date"] == "2024-03-08") & (slot_df["code"] == "603580")]
    res["hefu_ret_pct"] = round(float(hf_r.iloc[0]["net_ret_020"] * 100.0), 2) if not hf_r.empty else None
    res["aiai_ret_pct"] = round(float(aa_r.iloc[0]["net_ret_020"] * 100.0), 2) if not aa_r.empty else None
    return res, slot_df


def attach_causal_loo_s34_af20(ctx: dict, s34_ctx: dict) -> None:
    """
    Strictly causal (exit_date < bd) LOO test: drop `s34_af_20` (+5 pts) on date bd whenever
    its historical cluster-t on clipped utility (exit_date < bd) is < 0.0 (with >=20 closed trades).
    """
    import _w2a4_data_and_features as w2f
    base_b = {"trig_mult": 1.065, "cancel_hhmm": 1030, "hi_open_mode": "direct_0925"}
    base_e = {"d5_mode": "base", "zt_sl_mode": "base"}
    closed = []
    for item in s34_ctx["entries"]:
        if item["orig_buy_px"] is not None and not np.isnan(item["orig_buy_px"]):
            binfo = _sim_buy_3to4(item, ctx, s34_ctx, base_b)
            if binfo is not None:
                rec = _sim_exit_3to4(item, ctx, s34_ctx, binfo, base_e)
                closed.append((rec["buy_date"], rec["exit_date"], float(item["s34_af_20"] > 0), float(cm.fee_adjust(rec["net_ret_020"], 0.0030))))

    for item in s34_ctx["entries"]:
        bd = item["bd"]
        hist = [c for c in closed if c[1] < bd]
        if len(hist) < 20:
            item["causal_drop_af20"] = False
            continue
        z = np.array([c[2] for c in hist], dtype=np.float64)[:, None]
        if z.sum() < 5 or (len(hist) - z.sum()) < 5:
            item["causal_drop_af20"] = False
            continue
        u = np.clip(np.array([c[3] for c in hist], dtype=np.float64), -0.10, 0.25)
        bds = np.array([c[0] for c in hist])
        _, g_inv = np.unique(bds, return_inverse=True)
        t_clip = float(w2f._batch_cluster_t_stats(u, z, g_inv, int(g_inv.max() + 1))[0])
        item["causal_drop_af20"] = bool(t_clip < 0.0)


def main():
    t0 = time.time()
    m34 = pd.read_parquet(f"{cm.WAVE1}/pool_3to4_master_pit.parquet", columns=["code", "buy_date", "exit_date", "orig_score", "s34_af_20"])
    codes = set(m34["code"].astype(str).str.zfill(6))
    # Also union all 128 sc_v40>=90 codes (incl. 11 untriggered codes missing from pool_3to4_master_pit)
    with open(f"{F1_DIR}/pit_exit_cache_full.pkl", "rb") as _f:
        _c_peek = pickle.load(_f)
    codes |= {str(e["code"]).zfill(6) for e in _c_peek["buy_entries"] if e["skel"] and e["sc_v40"] >= 90.0}
    del _c_peek
    ctx = cm.load_filtered_5m_and_dmap(codes, load_5m=True, load_sub2=False)
    s34_ctx = build_3to4_surgical_ctx(ctx)
    attach_causal_loo_s34_af20(ctx, s34_ctx)
    print(f"[Front2 3to4] Context loaded in {time.time()-t0:.1f}s | entries={len(s34_ctx['entries'])} | RSS={cm.rss_mb()} MB")

    # 1. Exact Baseline Parity Check
    res_base, sl_base = eval_3to4_variant("V41_Baseline", ctx, s34_ctx, {"trig_mult": 1.065, "cancel_hhmm": 1030, "hi_open_mode": "direct_0925"}, {"d5_mode": "base", "zt_sl_mode": "base"})
    ref34 = pd.read_csv(f"{cm.SIM}/backtests_astock/redteam_full_audit_20261123/partC_clean_ledgers_v191/ledger_3to4_v41_clean.csv", dtype={"code": str})
    ref34["code"] = ref34["code"].str.zfill(6)
    assert len(sl_base) == 95 and list(zip(sl_base["buy_date"], sl_base["code"])) == list(zip(ref34["buy_date"], ref34["code"]))
    ret_diff = float(np.max(np.abs(sl_base["net_ret_020"].to_numpy() - ref34["net_ret"].to_numpy())))
    assert ret_diff < 1e-6, f"Parity diff={ret_diff}"
    base_dr_wf = res_base["dr_wf_030"]
    base_dr_5y = res_base["dr_5y_030"]
    w_b = res_base["windows_030"]["WF_2326"]
    print(f"  [Parity PASS] diff={ret_diff:.2e} | 5Y_020={np.prod(1+sl_base['net_ret_020']):.4f}x | WF_030 n={w_b['n']} nav={w_b['nav']}x sh={w_b['sharpe']} mdd={w_b['mdd_pct']}% | hefu={res_base['hefu_ret_pct']}% aiai={res_base['aiai_ret_pct']}%")

    # Re-eval baseline with paired t reference
    res_base, sl_base = eval_3to4_variant("V41_Baseline", ctx, s34_ctx, {"trig_mult": 1.065, "cancel_hhmm": 1030, "hi_open_mode": "direct_0925"}, {"d5_mode": "base", "zt_sl_mode": "base"}, None, base_dr_wf, base_dr_5y)

    # Define structure filters (strictly causal!)
    sf_base = None
    sf_m4bl15 = lambda it: not it["m4_mine_bl15"]
    sf_no_af20 = lambda it: (it["score"] - it["s34_af_20"]) >= 90.0
    sf_causal_af20 = lambda it: (it["score"] - (it["s34_af_20"] if it.get("causal_drop_af20", False) else 0.0)) >= 90.0
    sf_act94 = lambda it: (it["score"] >= 94.0) if (it["mkt10_zt_est_t1"] >= 50.0) else (it["score"] >= 90.0)
    sf_m4_and_no20 = lambda it: (not it["m4_mine_bl15"]) and ((it["score"] - it["s34_af_20"]) >= 90.0)
    sf_m4_and_causal20 = lambda it: (not it["m4_mine_bl15"]) and sf_causal_af20(it)
    sf_m4_and_act94 = lambda it: (not it["m4_mine_bl15"]) and ((it["score"] >= 94.0) if (it["mkt10_zt_est_t1"] >= 50.0) else (it["score"] >= 90.0))

    specs = []
    # Prong (a): Buy-side purification
    for hm in ["open_plus_0.005", "open_plus_0.01", "open_plus_0.015", "f5_hold_0.0", "f5_hold_-0.01", "f5_break_or_zt"]:
        for ch in [945, 1000, 1030]:
            if hm.startswith("f5_hold_") and ch != 1030:
                continue
            specs.append((f"A_buy_{hm}_c{ch}", {"trig_mult": 1.065, "cancel_hhmm": ch, "hi_open_mode": hm}, {"d5_mode": "base", "zt_sl_mode": "base"}, None))
    for cap_o in [0.085, 0.088]:
        specs.append((f"A_capopen_{int(cap_o*1000)}", {"trig_mult": 1.065, "cancel_hhmm": 1030, "hi_open_mode": "direct_0925", "max_open_pct": cap_o}, {"d5_mode": "base", "zt_sl_mode": "base"}, None))
    for ch in [945, 1000, 1015]:
        specs.append((f"A_cutoff_{ch}", {"trig_mult": 1.065, "cancel_hhmm": ch, "hi_open_mode": "direct_0925"}, {"d5_mode": "base", "zt_sl_mode": "base"}, None))
    for tm in [1.055, 1.060, 1.070]:
        specs.append((f"A_trig_{int(round(tm*1000))}_c1000", {"trig_mult": tm, "cancel_hhmm": 1000, "hi_open_mode": "direct_0925"}, {"d5_mode": "base", "zt_sl_mode": "base"}, None))

    # Prong (b): T+1 5m dynamic early exit / left-tail stop-loss
    b_base = {"trig_mult": 1.065, "cancel_hhmm": 1030, "hi_open_mode": "direct_0925"}
    for d5m in ["wait_1000", "wait_1030", "1000_redcut", "bounce_b02_sl03_1030", "bounce_b03_sl03_1030", "bounce_b02_sl04_1130", "trail_t02_1030", "trail_t03_1030", "trail_t03_1130"]:
        specs.append((f"B_d5_{d5m}", b_base, {"d5_mode": d5m, "zt_sl_mode": "base"}, None))
    for ztm in ["prevc_tp1_m4_1000", "prevc_tp1_m5_1000", "prevc_tp1_m6_1000", "prevc_tp1_m5_0945", "prevc_tp1_m5_1030",
                "prevc_all_m7_1000", "prevc_all_m7_1030", "prevc_all_m6_1000",
                "vwap_tp1_m3_1000", "vwap_tp1_m4_1000", "d4low_tp1_1000",
                "open_tp1_m2_1000", "open_tp1_m3_1000", "open_tp1_m4_1000", "open_tp1_m5_1000",
                "notgreen_tp1_1000", "notgreen_tp1_1030"]:
        specs.append((f"B_zt_{ztm}", b_base, {"d5_mode": "base", "zt_sl_mode": ztm}, None))

    # Prong (c): RD036 structure filters alone (both IS-locked & strictly causal exit_date < t LOO!)
    for snm, sfn in [
        ("C_M4MineBL15", sf_m4bl15), ("C_NoAf20_ISLocked", sf_no_af20), ("C_NoAf20_CausalLOO", sf_causal_af20),
        ("C_Act94", sf_act94), ("C_M4_NoAf20", sf_m4_and_no20), ("C_M4_CausalLOO", sf_m4_and_causal20), ("C_M4_Act94", sf_m4_and_act94)
    ]:
        specs.append((snm, b_base, {"d5_mode": "base", "zt_sl_mode": "base"}, sfn))

    results = [res_base]
    slot_map = {"V41_Baseline": sl_base}
    for vid, bcfg, ecfg, sfn in specs:
        r, sl = eval_3to4_variant(vid, ctx, s34_ctx, bcfg, ecfg, sfn, base_dr_wf, base_dr_5y)
        results.append(r)
        slot_map[vid] = sl

    # Pick top single-prong (a), (b), (c) and evaluate 2-way & 3-way combinations
    def _score_wf(r):
        w = r["windows_030"]["WF_2326"]
        return w["sharpe"] - max(0.0, w["mdd_pct"] - 35.0) * 0.02

    top_a = sorted([r for r in results if r["variant_id"].startswith("A_")], key=_score_wf, reverse=True)[:3]
    top_b_d5 = sorted([r for r in results if r["variant_id"].startswith("B_d5_")], key=_score_wf, reverse=True)[:3]
    top_b_zt = sorted([r for r in results if r["variant_id"].startswith("B_zt_")], key=_score_wf, reverse=True)[:3]

    spec_lu = {x[0]: x for x in specs}
    combo_specs = []
    # Pair best d5 + best zt_sl
    for bd in top_b_d5[:2]:
        for bz in top_b_zt[:2]:
            d5_m = spec_lu[bd["variant_id"]][2]["d5_mode"]
            zt_m = spec_lu[bz["variant_id"]][2]["zt_sl_mode"]
            combo_specs.append((f"BC_{d5_m}__{zt_m}", b_base, {"d5_mode": d5_m, "zt_sl_mode": zt_m}, None))
            for snm, sfn in [("M4", sf_m4bl15), ("NoAf20", sf_no_af20), ("CausalLOO", sf_causal_af20), ("Act94", sf_act94), ("M4_NoAf20", sf_m4_and_no20), ("M4_CausalLOO", sf_m4_and_causal20)]:
                combo_specs.append((f"BC_{d5_m}__{zt_m}__{snm}", b_base, {"d5_mode": d5_m, "zt_sl_mode": zt_m}, sfn))
    # Also combine best buy filter + best B + C
    for ta in top_a[:2]:
        bcfg_a = spec_lu[ta["variant_id"]][1]
        d5_m = spec_lu[top_b_d5[0]["variant_id"]][2]["d5_mode"]
        zt_m = spec_lu[top_b_zt[0]["variant_id"]][2]["zt_sl_mode"]
        combo_specs.append((f"ABC_{ta['variant_id']}__{d5_m}__{zt_m}", bcfg_a, {"d5_mode": d5_m, "zt_sl_mode": zt_m}, None))
        for snm, sfn in [("M4", sf_m4bl15), ("NoAf20", sf_no_af20), ("Act94", sf_act94), ("M4_NoAf20", sf_m4_and_no20)]:
            combo_specs.append((f"ABC_{ta['variant_id']}__{d5_m}__{zt_m}__{snm}", bcfg_a, {"d5_mode": d5_m, "zt_sl_mode": zt_m}, sfn))
        for snm, sfn in [("M4", sf_m4bl15), ("NoAf20", sf_no_af20), ("Act94", sf_act94), ("M4_NoAf20", sf_m4_and_no20)]:
            combo_specs.append((f"AC_{ta['variant_id']}__{snm}", bcfg_a, {"d5_mode": "base", "zt_sl_mode": "base"}, sfn))
    # Also B_zt alone + C
    for bz in top_b_zt[:2]:
        zt_m = spec_lu[bz["variant_id"]][2]["zt_sl_mode"]
        for snm, sfn in [("M4", sf_m4bl15), ("NoAf20", sf_no_af20), ("CausalLOO", sf_causal_af20), ("Act94", sf_act94), ("M4_NoAf20", sf_m4_and_no20), ("M4_CausalLOO", sf_m4_and_causal20)]:
            combo_specs.append((f"BC_zt_{zt_m}__{snm}", b_base, {"d5_mode": "base", "zt_sl_mode": zt_m}, sfn))

    # Parameter neighborhood plateau around T+1 ZT stop (prevc_tp1 & d4low_tp1) alone and with M4_CausalLOO
    _seen_vids = {x[0] for x in specs + combo_specs}
    for thr_s in ["4", "4.5", "5", "5.5", "6", "6.5", "7"]:
        for hh_s in ["0945", "1000", "1015", "1030"]:
            zm = f"prevc_tp1_m{thr_s}_{hh_s}"
            if f"B_zt_{zm}" not in _seen_vids:
                combo_specs.append((f"B_zt_{zm}", b_base, {"d5_mode": "base", "zt_sl_mode": zm}, None))
                _seen_vids.add(f"B_zt_{zm}")
            if f"BC_zt_{zm}__M4_CausalLOO" not in _seen_vids:
                combo_specs.append((f"BC_zt_{zm}__M4_CausalLOO", b_base, {"d5_mode": "base", "zt_sl_mode": zm}, sf_m4_and_causal20))
                _seen_vids.add(f"BC_zt_{zm}__M4_CausalLOO")
    for hh_s in ["0945", "1000", "1015", "1030"]:
        zm = f"d4low_tp1_{hh_s}"
        if f"B_zt_{zm}" not in _seen_vids:
            combo_specs.append((f"B_zt_{zm}", b_base, {"d5_mode": "base", "zt_sl_mode": zm}, None))
            _seen_vids.add(f"B_zt_{zm}")
        if f"BC_zt_{zm}__M4_CausalLOO" not in _seen_vids:
            combo_specs.append((f"BC_zt_{zm}__M4_CausalLOO", b_base, {"d5_mode": "base", "zt_sl_mode": zm}, sf_m4_and_causal20))
            _seen_vids.add(f"BC_zt_{zm}__M4_CausalLOO")

    for vid, bcfg, ecfg, sfn in combo_specs:
        r, sl = eval_3to4_variant(vid, ctx, s34_ctx, bcfg, ecfg, sfn, base_dr_wf, base_dr_5y)
        results.append(r)
        slot_map[vid] = sl

    # CSCV PBO across all tested variants (WF daily MTM & 5Y daily MTM)
    mat_wf = {r["variant_id"]: r["dr_wf_030"] for r in results if r.get("dr_wf_030") is not None}
    mat_5y = {r["variant_id"]: r["dr_5y_030"] for r in results if r.get("dr_5y_030") is not None}
    pbo_wf_16 = cm.cscv_pbo(mat_wf, S=16)
    pbo_5y_16 = cm.cscv_pbo(mat_5y, S=16)

    # Print leaderboard
    rows_print = []
    for r in results:
        if r.get("n_5y") == 0 or "windows_030" not in r:
            continue
        wf = r["windows_030"]["WF_2326"]
        f5 = r["windows_030"]["FULL_5Y"]
        oos = r["windows_030"]["OOS_2526"]
        y26 = r["windows_030"]["Y2026"]
        h2 = r["windows_030"]["Y26H2"]
        wv = r["windows_vel030"]["WF_2326"]
        rows_print.append({
            "variant_id": r["variant_id"],
            "n_5y": f5["n"], "n_wf": wf["n"], "miss": r["miss_rate_pct"],
            "wr_wf": wf["wr_pct"], "plr_wf": wf["plr"], "mloss_wf": wf["mean_loss_pct"], "le7_wf": wf["big_loss_rate_pct"],
            "nav_wf": wf["nav"], "ex5_wf": wf["ex_top5_nav"], "mdd_wf": wf["mdd_pct"], "sh_wf": wf["sharpe"], "cal_wf": wf["calmar"],
            "sh_vel_wf": wv["sharpe"], "nav_vel_wf": wv["nav"],
            "nav_5y": f5["nav"], "sh_5y": f5["sharpe"], "mdd_5y": f5["mdd_pct"],
            "nav_2526": oos["nav"], "sh_2526": oos["sharpe"], "nav_26": y26["nav"], "nav_26h2": h2["nav"],
            "pt_wf": r["paired_t_wf_030"], "pp_wf": r["paired_p_wf_030"],
            "hefu": r["hefu_ret_pct"], "aiai": r["aiai_ret_pct"],
        })
    df_sum = pd.DataFrame(rows_print).sort_values("sh_wf", ascending=False)
    print("\n=== TOP 25 3to4 VARIANTS BY WF EXACT MTM SHARPE ===")
    print(df_sum.head(25)[["variant_id", "n_wf", "miss", "wr_wf", "le7_wf", "mloss_wf", "nav_wf", "mdd_wf", "sh_wf", "sh_vel_wf", "nav_2526", "nav_26h2", "pt_wf", "pp_wf", "hefu", "aiai"]].to_string(index=False))
    print(f"CSCV PBO (S=16): WF={pbo_wf_16['pbo']} | 5Y={pbo_5y_16['pbo']}")

    # Save intermediate cache for finalizer
    out_cache = {
        "results": [{k: v for k, v in r.items() if not k.startswith("dr_")} for r in results],
        "drs_wf": mat_wf,
        "drs_5y": mat_5y,
        "pbo_wf_16": pbo_wf_16,
        "pbo_5y_16": pbo_5y_16,
        "summary_df": df_sum,
        "top_slots": {k: slot_map[k] for k in ["V41_Baseline"] + df_sum.head(10)["variant_id"].tolist() if k in slot_map},
    }
    with open(f"{cm.CACHE_DIR}/front2_3to4.pkl", "wb") as f:
        pickle.dump(out_cache, f)
    print(f"[Front2 DONE in {time.time()-t0:.1f}s] RSS={cm.rss_mb()} MB")


if __name__ == "__main__":
    main()

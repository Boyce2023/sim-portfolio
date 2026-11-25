#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD029 Zero-Hindsight Day-by-Day ETF Backtest (2000-01-04 ~ 2026-11-25).
Tests S1 ~ S5 strictly day-by-day (signal at T close -> execute at T+1 open),
against Buy & Hold, Same-Avg-Weight Static Baseline, and Pure 1/vol Baseline,
with 2020-12-31 physical truncation anti-leakage verification (max_abs_diff == 0.0),
dual fee regimes (0.10% vs 0.30% round-trip), and dual cash yield regimes (0% vs 2% vs CGB10Y).
Outputs:
  - output/china_policy_macro_rd027_20261125/rd029_daybyday_etf/rd029_daybyday_audit.json
  - output/china_policy_macro_rd027_20261125/rd029_daybyday_etf/rd029_trades_ledger.csv
  - output/china_policy_macro_rd027_20261125/rd029_daybyday_etf/rd029_nav_daily.parquet
"""
import json
import os
import sys
import time
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)
import rd029_engine as eng

assert "yfinance" not in sys.modules, "D12 violation"

ROOT = eng.ROOT
OUT_DIR = os.path.join(ROOT, "output/china_policy_macro_rd027_20261125/rd029_daybyday_etf")
os.makedirs(OUT_DIR, exist_ok=True)


def make_strategy_fns(state: dict, target_asset_mode: str = "CHAIN") -> dict:
    """
    Create strategy target_fn callables for S1, S2, S3, S4 and B&H / 1overVol baselines.
    target_asset_mode: 'CHAIN' (sh_comp -> 510050 -> 510300) or '512100'.
    """
    chain = state["chain_asset"]
    mp = state["mp"]
    sigs = state["signals"]
    dates = state["dates"]

    def _asset_at(i: int) -> str:
        return "512100" if target_asset_mode == "512100" else str(chain[i])

    def fn_bh(i: int, ctx: dict):
        return {_asset_at(i): 1.0}, "BH"

    def make_s1_fn(sig_key: str, hold_days: int = 20, extend_on_retrig: bool = True):
        sig_arr = sigs[sig_key]
        v3_col = "v3_score_eod" if "eod" in sig_key else "v3_score_live"

        def _fn(i: int, ctx: dict):
            trig = bool(sig_arr[i])
            if not ctx["in_pos"]:
                if trig:
                    ctx["hold_rem"] = hold_days
                    sc = mp.at[i, v3_col]
                    rsn = f"V3={int(sc)}" if pd.notna(sc) and dates[i] >= "2016-02-01" else "Pre2016_HardTool_Spike2x"
                    return {_asset_at(i): 1.0}, rsn
                return {}, ""
            else:
                if trig and extend_on_retrig:
                    ctx["hold_rem"] = hold_days
                else:
                    ctx["hold_rem"] = ctx.get("hold_rem", 1) - 1
                if ctx["hold_rem"] <= 0:
                    return {}, ""
                return {_asset_at(i): 1.0}, ""

        return _fn

    def make_s2_fn(exit_mode: str = "H60"):
        sig_arr = sigs["s2_four_gate"]
        g1, g2, g3, g4 = sigs["g1_gate"], sigs["g2_gate"], sigs["g3_gate"], sigs["g4_gate"]
        tight_5d = sigs["tight_5d"]

        def _fn(i: int, ctx: dict):
            trig = bool(sig_arr[i])
            if not ctx["in_pos"]:
                if trig:
                    ctx["hold_rem"] = 60 if exit_mode == "H60" else (120 if exit_mode == "H120" else 9999)
                    gates = "+".join([x for x, fl in [("G1", g1[i]), ("G2", g2[i]), ("G3", g3[i]), ("G4", g4[i])] if fl])
                    return {_asset_at(i): 1.0}, f"4Gate[{gates}]"
                return {}, ""
            else:
                if exit_mode in ("H60", "H120"):
                    ctx["hold_rem"] = ctx.get("hold_rem", 1) - 1
                    if ctx["hold_rem"] <= 0:
                        return {}, ""
                    return {_asset_at(i): 1.0}, ""
                else:
                    # DynExit: hold >=20d, exit if (cum_ret>=15% & high_overheat) OR tightening reg signal
                    held = ctx.get("days_held", 0)
                    b_close, b_ma20, b_ret20 = mp.at[i, "bench_level"], mp.at[i, "bench_ma20"], mp.at[i, "bench_ret_20d"]
                    high_oh = pd.notna(b_ma20) and (b_close > b_ma20) and pd.notna(b_ret20) and (b_ret20 >= 0.05)
                    if held >= 20 and ((ctx.get("cur_trade_ret", 0.0) >= 0.15 and high_oh) or bool(tight_5d[i])):
                        return {}, ""
                    return {_asset_at(i): 1.0}, ""

        return _fn

    def make_s3_fn(use_inv_vol: bool = False):
        esc = sigs["s3_escape"]
        rec = sigs["s3_recover"]
        rescue = sigs["s1_live_60"] | sigs["s2_four_gate"]
        vol20 = mp["chain_vol_20d"].to_numpy(float)

        def _fn(i: int, ctx: dict):
            if rescue[i]:
                ctx["escaped"] = False
                return {_asset_at(i): 1.0}, "RescueSnap100"
            if esc[i]:
                ctx["escaped"] = True
                return {}, "EscapeOverheatTight"
            if ctx.get("escaped", False):
                if rec[i]:
                    ctx["escaped"] = False
                else:
                    return {}, ""
            # Normal holding regime
            if not use_inv_vol:
                return {_asset_at(i): 1.0}, ""
            v = vol20[i]
            w = float(np.clip(0.16 / v, 0.30, 1.0)) if (np.isfinite(v) and v > 0.02) else 0.70
            return {_asset_at(i): w}, ""

        return _fn

    def fn_pure_1overvol_t16(i: int, ctx: dict):
        v = mp.at[i, "chain_vol_20d"]
        w = float(np.clip(0.16 / v, 0.30, 1.0)) if (pd.notna(v) and v > 0.02) else 0.70
        return {_asset_at(i): w}, ""

    def fn_all14_ew(i: int, ctx: dict):
        w = 1.0 / len(eng.SECTORS)
        return {f"SEC_{s}": w for s in eng.SECTORS}, ""

    def make_s4_fn(green_boost: bool = False, rescue_512100: bool = False):
        s1_arr = sigs["s1_live_60"]
        red120 = sigs["sec_red120"]
        grn250 = sigs["sec_green250"]

        def _fn(i: int, ctx: dict):
            if s1_arr[i]:
                ctx["hold_rem"] = 20
            else:
                ctx["hold_rem"] = max(0, ctx.get("hold_rem", 0) - 1)

            if ctx.get("hold_rem", 0) > 0:
                ak = "512100" if rescue_512100 else _asset_at(i)
                return {ak: 1.0}, "RescueETF"

            reds = red120[i]
            pool = [s for s in eng.SECTORS if s not in reds]
            if not pool:
                pool = list(eng.SECTORS)
            if not green_boost:
                w = 1.0 / len(pool)
                return {f"SEC_{s}": w for s in pool}, ""
            grns = grn250[i]
            raw_w = {s: (1.5 if s in grns else 1.0) for s in pool}
            tot_w = sum(raw_w.values())
            return {f"SEC_{s}": raw_w[s] / tot_w for s in pool}, ""

        return _fn

    return {
        "BH": (fn_bh, False),
        "S1_Live_ge60": (make_s1_fn("s1_live_60", 20, True), True),
        "S1_Live_ge75": (make_s1_fn("s1_live_75", 20, True), True),
        "S1_EOD_ge60": (make_s1_fn("s1_eod_60", 20, True), True),
        "S1_EOD_ge75": (make_s1_fn("s1_eod_75", 20, True), True),
        "S2_4Gate_H60": (make_s2_fn("H60"), True),
        "S2_4Gate_H120": (make_s2_fn("H120"), True),
        "S2_4Gate_DynExit": (make_s2_fn("DynExit"), True),
        "S3a_HoldETF_PolicyEscape": (make_s3_fn(False), False),
        "S3b_HoldETF_Escape_1overVol": (make_s3_fn(True), False),
        "Pure_1overVol_T16": (fn_pure_1overvol_t16, False),
        "All14_EW_BH": (fn_all14_ew, False),
        "S4_Rescue300_ExclRed120": (make_s4_fn(False, False), False),
        "S4_Rescue300_Green250_ExclRed120": (make_s4_fn(True, False), False),
        "S4_Rescue1000_ExclRed120": (make_s4_fn(False, True), False),
    }


def eval_zero_signal_baselines(
    state: dict,
    strat_res: dict,
    start_date: str,
    d0: str,
    d1: str,
    asset_mode: str,
    fee_one_way: float,
    cash_mode: str,
) -> dict:
    """Run exact Same-Avg-Weight Static B&H & Pure 1/vol Matched-Avg-Weight (plus IS-calibrated 1/vol) for a window."""
    dates = strat_res["dates"]
    arr_d = np.array(dates)
    mask = (arr_d >= d0) & (arr_d <= d1)
    if mask.sum() < 15:
        return {}
    w_bar = float(np.mean(strat_res["eq_w"][mask]))
    chain = state["chain_asset"]
    mp = state["mp"]
    vol60 = mp["chain_vol_60d"].to_numpy(float)

    def _ak(i: int) -> str:
        return "512100" if asset_mode == "512100" else str(chain[i])

    # 1. Static Same-Avg-Weight B&H
    sim_stat = eng.run_daily_portfolio_sim(
        state,
        lambda i, ctx: ({_ak(i): w_bar}, ""),
        start_date=start_date,
        fee_one_way=fee_one_way,
        cash_mode=cash_mode,
    )

    # 2. Pure 1/vol Matched-Avg-Weight in window (and IS-calibrated scalar from <=2020-12-31)
    start_idx = next((i for i, d in enumerate(state["dates"]) if d >= start_date), 0)
    win_mp_mask = (np.array(state["dates"]) >= d0) & (np.array(state["dates"]) <= d1)
    inv_v_full = np.where(np.isfinite(vol60) & (vol60 > 0.02), 1.0 / vol60, 1.0 / 0.22)
    c_win = eng.solve_vol_scalar_for_target(inv_v_full[win_mp_mask], w_bar)
    sim_iv = eng.run_daily_portfolio_sim(
        state,
        lambda i, ctx: ({_ak(i): float(np.clip(c_win * inv_v_full[i], 0.0, 1.0))}, ""),
        start_date=start_date,
        fee_one_way=fee_one_way,
        cash_mode=cash_mode,
    )

    # Benchmark BH
    sim_bh = eng.run_daily_portfolio_sim(
        state,
        lambda i, ctx: ({_ak(i): 1.0}, ""),
        start_date=start_date,
        fee_one_way=fee_one_way,
        cash_mode=cash_mode,
    )
    m_st = eng.compute_window_metrics(sim_stat["nav"], sim_stat["eq_w"], sim_stat["turnover"], dates, sim_bh["nav"], None, d0, d1)
    m_iv = eng.compute_window_metrics(sim_iv["nav"], sim_iv["eq_w"], sim_iv["turnover"], dates, sim_bh["nav"], None, d0, d1)
    m_main = eng.compute_window_metrics(strat_res["nav"], strat_res["eq_w"], strat_res["turnover"], dates, sim_bh["nav"], strat_res["trades"], d0, d1)
    return {
        "strategy": m_main,
        "same_avg_weight_bh": m_st,
        "pure_1overvol_matched": m_iv,
        "alpha_vs_same_w_ann_pp": round(m_main["ann_ret_pct"] - m_st["ann_ret_pct"], 2),
        "sharpe_vs_same_w": round(m_main["sharpe"] - m_st["sharpe"], 2),
        "mdd_diff_vs_same_w_pp": round(m_main["mdd_pct"] - m_st["mdd_pct"], 2),
        "alpha_vs_1overvol_ann_pp": round(m_main["ann_ret_pct"] - m_iv["ann_ret_pct"], 2),
        "sharpe_vs_1overvol": round(m_main["sharpe"] - m_iv["sharpe"], 2),
    }


def run_truncation_audit(full_state: dict, full_sims: dict) -> dict:
    """Physical truncation at 2020-12-31: rebuild ALL features & simulate from scratch <= 2020-12-31."""
    trunc_date = "2020-12-31"
    tr_state = eng.build_causal_state(cutoff_date=trunc_date, wp_lag_mode="after_16")
    tr_fns = make_strategy_fns(tr_state, "CHAIN")
    n_tr = len(tr_state["dates"])

    checks = {}
    max_all = 0.0
    for sname in ["BH", "S1_Live_ge60", "S1_Live_ge75", "S1_EOD_ge60", "S2_4Gate_H60", "S2_4Gate_H120", "S2_4Gate_DynExit", "S3a_HoldETF_PolicyEscape", "S3b_HoldETF_Escape_1overVol"]:
        fn, trk = tr_fns[sname]
        s_tr = eng.run_daily_portfolio_sim(tr_state, fn, start_date="2000-01-04", fee_one_way=0.0005, cash_mode="0pct", track_single_trades=trk, strat_name=sname)
        nav_full_slice = full_sims[sname]["nav"][:n_tr]
        w_full_slice = full_sims[sname]["eq_w"][:n_tr]
        diff_nav = float(np.max(np.abs(s_tr["nav"] - nav_full_slice)))
        diff_w = float(np.max(np.abs(s_tr["eq_w"] - w_full_slice)))
        max_all = max(max_all, diff_nav, diff_w)
        checks[sname] = {"max_nav_diff": diff_nav, "max_weight_diff": diff_w}

    # Check S4 from 2008-08-28
    s4_tr = eng.run_daily_portfolio_sim(tr_state, tr_fns["S4_Rescue300_ExclRed120"][0], start_date="2008-08-28", fee_one_way=0.0005, cash_mode="0pct")
    n_s4_tr = len(s4_tr["nav"])
    diff_s4 = float(np.max(np.abs(s4_tr["nav"] - full_sims["S4_Rescue300_ExclRed120"]["nav"][:n_s4_tr])))
    max_all = max(max_all, diff_s4)
    checks["S4_Rescue300_ExclRed120"] = {"max_nav_diff": diff_s4}

    # Check V3 score invariance on 2016-02-01..2020-12-31
    v3_diff = float(np.max(np.abs(
        tr_state["mp"]["v3_score_live"].fillna(0).to_numpy()[:n_tr]
        - full_state["mp"]["v3_score_live"].fillna(0).to_numpy()[:n_tr]
    )))
    max_all = max(max_all, v3_diff)
    return {
        "cutoff_date": trunc_date,
        "max_abs_diff": max_all,
        "passed_zero_diff": bool(max_all == 0.0),
        "per_strategy": checks,
        "v3_score_live_max_diff": v3_diff,
    }


def main():
    t0 = time.time()
    print("[RD029] Building strictly causal full-sample state (2000-01-04 ~ 2026-11-25)...")
    state = eng.build_causal_state(cutoff_date=None, wp_lag_mode="after_16")
    dates = state["dates"]
    print(f"  Calendar: {len(dates)} days [{dates[0]} -> {dates[-1]}]")
    print(f"  Today (2026-11-25) V3 live={state['mp']['v3_score_live'].iloc[-1]}, S1_live_60={state['signals']['s1_live_60'][-1]}, S2_4Gate={state['signals']['s2_four_gate'][-1]}, G1..4=({int(state['signals']['g1_gate'][-1])},{int(state['signals']['g2_gate'][-1])},{int(state['signals']['g3_gate'][-1])},{int(state['signals']['g4_gate'][-1])})")

    fns_chain = make_strategy_fns(state, "CHAIN")
    fns_1000 = make_strategy_fns(state, "512100")

    # ------------------------------------------------------------------
    # 1. Primary Regime: Real ETF Fee 0.10% (5bps 1-way) + Strict 0% Cash
    # ------------------------------------------------------------------
    chain_strats = [
        "BH", "S1_Live_ge60", "S1_Live_ge75", "S1_EOD_ge60", "S1_EOD_ge75",
        "S2_4Gate_H60", "S2_4Gate_H120", "S2_4Gate_DynExit",
        "S3a_HoldETF_PolicyEscape", "S3b_HoldETF_Escape_1overVol", "Pure_1overVol_T16",
    ]
    sims_010_0cash = {}
    for sn in chain_strats:
        fn, trk = fns_chain[sn]
        sims_010_0cash[sn] = eng.run_daily_portfolio_sim(state, fn, "2000-01-04", 0.0005, "0pct", track_single_trades=trk, strat_name=sn)

    # S4 starts 2008-08-28 (industry data start)
    for sn in ["All14_EW_BH", "S4_Rescue300_ExclRed120", "S4_Rescue300_Green250_ExclRed120"]:
        fn, trk = fns_chain[sn]
        sims_010_0cash[sn] = eng.run_daily_portfolio_sim(state, fn, "2008-08-28", 0.0005, "0pct", track_single_trades=False, strat_name=sn)
    sims_010_0cash["BH_S4_2008"] = eng.run_daily_portfolio_sim(state, fns_chain["BH"][0], "2008-08-28", 0.0005, "0pct")

    # Pure 512100 & Pure 510300 Modern Era Comparison (2016-11-04 ~ 2026-11-25)
    mod_strats = ["BH", "S1_Live_ge60", "S1_Live_ge75", "S1_EOD_ge60", "S2_4Gate_H60", "S2_4Gate_H120", "S2_4Gate_DynExit", "S3a_HoldETF_PolicyEscape", "S3b_HoldETF_Escape_1overVol"]
    sims_1000 = {}
    sims_300_mod = {}
    for sn in mod_strats:
        fn1k, trk1k = fns_1000[sn]
        sims_1000[sn] = eng.run_daily_portfolio_sim(state, fn1k, "2016-11-04", 0.0005, "0pct", track_single_trades=trk1k, strat_name=f"{sn}_512100")
        fn3, _ = fns_chain[sn]
        sims_300_mod[sn] = eng.run_daily_portfolio_sim(state, fn3, "2016-11-04", 0.0005, "0pct", track_single_trades=False)
    sims_1000["S4_Rescue1000_ExclRed120"] = eng.run_daily_portfolio_sim(state, fns_chain["S4_Rescue1000_ExclRed120"][0], "2016-11-04", 0.0005, "0pct")

    # ------------------------------------------------------------------
    # 2. Multi-Window & Zero-Signal Ablation Summary
    # ------------------------------------------------------------------
    windows_chain = [
        ("FULL_2000_2026", "2000-01-04", "2026-11-25"),
        ("REAL_ETF_2005_2026", "2005-02-23", "2026-11-25"),
        ("PURE_510300_2012_2026", "2012-05-28", "2026-11-25"),
        ("MODERN_2016_2026", "2016-11-04", "2026-11-25"),
        ("RECENT_6Y_2021_2026", "2021-01-04", "2026-11-25"),
        ("RECENT_3Y_2024_2026", "2024-01-02", "2026-11-25"),
    ]
    chain_summary = {}
    for wname, d0, d1 in windows_chain:
        w_dict = {}
        b_nav = sims_010_0cash["BH"]["nav"]
        for sn in chain_strats:
            sim_r = sims_010_0cash[sn]
            if sn == "BH":
                w_dict[sn] = {"strategy": eng.compute_window_metrics(sim_r["nav"], sim_r["eq_w"], sim_r["turnover"], sim_r["dates"], b_nav, None, d0, d1)}
            else:
                w_dict[sn] = eval_zero_signal_baselines(state, sim_r, "2000-01-04", d0, d1, "CHAIN", 0.0005, "0pct")
        chain_summary[wname] = w_dict

    # S4 18Y + Subwindows summary
    s4_windows = [
        ("S4_18Y_2008_2026", "2008-08-28", "2026-11-25"),
        ("S4_510300_2012_2026", "2012-05-28", "2026-11-25"),
        ("S4_MODERN_2016_2026", "2016-11-04", "2026-11-25"),
        ("S4_6Y_2021_2026", "2021-01-04", "2026-11-25"),
        ("S4_3Y_2024_2026", "2024-01-02", "2026-11-25"),
    ]
    s4_summary = {}
    for wname, d0, d1 in s4_windows:
        w_dict = {}
        b_nav = sims_010_0cash["BH_S4_2008"]["nav"]
        for sn in ["BH_S4_2008", "All14_EW_BH", "S4_Rescue300_ExclRed120", "S4_Rescue300_Green250_ExclRed120"]:
            sim_r = sims_010_0cash[sn]
            m = eng.compute_window_metrics(sim_r["nav"], sim_r["eq_w"], sim_r["turnover"], sim_r["dates"], b_nav, None, d0, d1)
            m_ew = eng.compute_window_metrics(sims_010_0cash["All14_EW_BH"]["nav"], sims_010_0cash["All14_EW_BH"]["eq_w"], sims_010_0cash["All14_EW_BH"]["turnover"], sims_010_0cash["All14_EW_BH"]["dates"], b_nav, None, d0, d1)
            m["excess_ann_vs_all14ew_pp"] = round(m["ann_ret_pct"] - m_ew["ann_ret_pct"], 2)
            w_dict[sn] = m
        s4_summary[wname] = w_dict

    # 510300 vs 512100 Modern Comparison (2016.11+, 2021+, 2024+)
    mod_windows = [
        ("MODERN_2016_2026", "2016-11-04", "2026-11-25"),
        ("RECENT_6Y_2021_2026", "2021-01-04", "2026-11-25"),
        ("RECENT_3Y_2024_2026", "2024-01-02", "2026-11-25"),
    ]
    mod_512100_vs_510300 = {}
    for wname, d0, d1 in mod_windows:
        w_dict = {}
        for sn in mod_strats:
            m3 = eval_zero_signal_baselines(state, sims_300_mod[sn], "2016-11-04", d0, d1, "CHAIN", 0.0005, "0pct")
            m1k = eval_zero_signal_baselines(state, sims_1000[sn], "2016-11-04", d0, d1, "512100", 0.0005, "0pct")
            w_dict[sn] = {"ETF_510300": m3, "ETF_512100": m1k}
        s4_1k_m = eng.compute_window_metrics(sims_1000["S4_Rescue1000_ExclRed120"]["nav"], sims_1000["S4_Rescue1000_ExclRed120"]["eq_w"], sims_1000["S4_Rescue1000_ExclRed120"]["turnover"], sims_1000["S4_Rescue1000_ExclRed120"]["dates"], sims_1000["BH"]["nav"], None, d0, d1)
        w_dict["S4_Rescue1000_ExclRed120"] = {"ETF_512100": {"strategy": s4_1k_m}}
        mod_512100_vs_510300[wname] = w_dict

    # ------------------------------------------------------------------
    # 3. Fee & Cash Yield Sensitivity Matrix (FULL_2000_2026 & PURE_510300 & RECENT_6Y)
    # ------------------------------------------------------------------
    sens_matrix = {}
    for tag, fee_ow, cash_m in [
        ("Fee010_Cash0pct", 0.0005, "0pct"),
        ("Fee010_Cash2pct", 0.0005, "2pct"),
        ("Fee010_CashCGB10Y", 0.0005, "cgb10y"),
        ("Fee030_Cash0pct", 0.0015, "0pct"),
        ("Fee030_Cash2pct", 0.0015, "2pct"),
    ]:
        bh_s = eng.run_daily_portfolio_sim(state, fns_chain["BH"][0], "2000-01-04", fee_ow, cash_m)
        s_rows = {}
        for sn in ["BH", "S1_Live_ge60", "S1_Live_ge75", "S2_4Gate_H60", "S2_4Gate_H120", "S2_4Gate_DynExit", "S3a_HoldETF_PolicyEscape", "S3b_HoldETF_Escape_1overVol"]:
            sr = bh_s if sn == "BH" else eng.run_daily_portfolio_sim(state, fns_chain[sn][0], "2000-01-04", fee_ow, cash_m)
            s_rows[sn] = {
                "FULL_2000_2026": eng.compute_window_metrics(sr["nav"], sr["eq_w"], sr["turnover"], sr["dates"], bh_s["nav"], None, "2000-01-04", "2026-11-25"),
                "PURE_510300_2012_2026": eng.compute_window_metrics(sr["nav"], sr["eq_w"], sr["turnover"], sr["dates"], bh_s["nav"], None, "2012-05-28", "2026-11-25"),
                "RECENT_6Y_2021_2026": eng.compute_window_metrics(sr["nav"], sr["eq_w"], sr["turnover"], sr["dates"], bh_s["nav"], None, "2021-01-04", "2026-11-25"),
            }
        sens_matrix[tag] = s_rows

    # ------------------------------------------------------------------
    # 4. Waterpool Strict Full-1M Lag (M+2 day 1) Sensitivity + 2020-12-31 Physical Truncation Test
    # ------------------------------------------------------------------
    print("[RD029] Running 2020-12-31 physical truncation anti-leakage test...")
    trunc_audit = run_truncation_audit(state, sims_010_0cash)
    print(f"  Truncation max_abs_diff={trunc_audit['max_abs_diff']} (passed={trunc_audit['passed_zero_diff']})")

    state_m2 = eng.build_causal_state(cutoff_date=None, wp_lag_mode="full_1m")
    fns_m2 = make_strategy_fns(state_m2, "CHAIN")
    wp_lag_sens = {}
    for sn in ["S2_4Gate_H60", "S2_4Gate_H120", "S3a_HoldETF_PolicyEscape"]:
        sr_m2 = eng.run_daily_portfolio_sim(state_m2, fns_m2[sn][0], "2000-01-04", 0.0005, "0pct")
        m_orig = chain_summary["FULL_2000_2026"][sn]["strategy"]
        m_full1m = eng.compute_window_metrics(sr_m2["nav"], sr_m2["eq_w"], sr_m2["turnover"], sr_m2["dates"], sims_010_0cash["BH"]["nav"], None, "2000-01-04", "2026-11-25")
        wp_lag_sens[sn] = {"after_day16": m_orig, "full_1m_M2_day1": m_full1m}

    # ------------------------------------------------------------------
    # 5. Save Trade Ledger CSV, Daily NAV Parquet, and Audit JSON
    # ------------------------------------------------------------------
    all_trades = []
    for sn in ["S1_Live_ge60", "S1_Live_ge75", "S1_EOD_ge60", "S2_4Gate_H60", "S2_4Gate_H120", "S2_4Gate_DynExit"]:
        all_trades.extend(sims_010_0cash[sn]["trades"])
    for sn in ["S1_Live_ge60", "S1_Live_ge75", "S2_4Gate_H60"]:
        all_trades.extend(sims_1000[sn]["trades"])
    ledger_df = pd.DataFrame(all_trades)
    ledger_path = os.path.join(OUT_DIR, "rd029_trades_ledger.csv")
    ledger_df.to_csv(ledger_path, index=False, encoding="utf-8-sig")

    nav_df = pd.DataFrame({"date": dates})
    for sn in chain_strats:
        nav_df[f"{sn}_nav"] = sims_010_0cash[sn]["nav"]
        nav_df[f"{sn}_w"] = sims_010_0cash[sn]["eq_w"]
    for sn in ["All14_EW_BH", "S4_Rescue300_ExclRed120", "S4_Rescue300_Green250_ExclRed120"]:
        sub_df = pd.DataFrame({"date": sims_010_0cash[sn]["dates"], f"{sn}_nav": sims_010_0cash[sn]["nav"]})
        nav_df = nav_df.merge(sub_df, on="date", how="left")
    for sn in ["BH", "S1_Live_ge60", "S2_4Gate_H60", "S4_Rescue1000_ExclRed120"]:
        sub_df = pd.DataFrame({"date": sims_1000[sn]["dates"], f"ETF1000_{sn}_nav": sims_1000[sn]["nav"]})
        nav_df = nav_df.merge(sub_df, on="date", how="left")
    nav_path = os.path.join(OUT_DIR, "rd029_nav_daily.parquet")
    nav_df.to_parquet(nav_path, index=False)

    audit = {
        "meta": {
            "task": "RD029 Zero-Hindsight Day-by-Day ETF Backtest (2000-01-04 ~ 2026-11-25)",
            "d12_compliant": True,
            "data_as_of_date": dates[-1],
            "n_trading_days": int(len(dates)),
            "etf_chain_spec": {
                "2000-01-04_to_2005-02-22": "sh000001的上证指数现货代理(尚无中国ETF)",
                "2005-02-23_to_2012-05-27": "510050华夏上证50ETF(真实含分红后复权)",
                "2012-05-28_to_2026-11-25": "510300华泰柏瑞沪深300ETF(真实含分红后复权)",
                "modern_compare": "512100南方中证1000ETF(2016-11-04起真实含分红拆份复权)",
            },
            "primary_cost_and_cash": "0.10% round-trip (5bps one-way) + 0% cash yield (strictest no-cushion baseline)",
            "waterpool_pit_rule": "Strictly > M+1 day 16 (>= 17th of next month), plus M+2 day 1 sensitivity verified",
            "live_2026_11_25_reading": {
                "csi300_close": float(state["mp"]["csi300_close"].iloc[-1]),
                "v3_score_live": int(state["mp"]["v3_score_live"].iloc[-1]),
                "s1_live_60_trigger": bool(state["signals"]["s1_live_60"][-1]),
                "s2_4gate_trigger": bool(state["signals"]["s2_four_gate"][-1]),
                "gates": {
                    "G1": bool(state["signals"]["g1_gate"][-1]),
                    "G2": bool(state["signals"]["g2_gate"][-1]),
                    "G3": bool(state["signals"]["g3_gate"][-1]),
                    "G4": bool(state["signals"]["g4_gate"][-1]),
                },
            },
        },
        "truncation_test_2020_12_31": trunc_audit,
        "chain_windows_010fee_0cash": chain_summary,
        "s4_sector_windows_010fee_0cash": s4_summary,
        "modern_510300_vs_512100": mod_512100_vs_510300,
        "fee_and_cash_sensitivity": sens_matrix,
        "waterpool_lag_sensitivity": wp_lag_sens,
        "ledger_summary": {
            "total_logged_trades": int(len(ledger_df)),
            "counts_by_strategy": ledger_df["strategy"].value_counts().to_dict() if not ledger_df.empty else {},
        },
    }
    audit_path = os.path.join(OUT_DIR, "rd029_daybyday_audit.json")
    with open(audit_path, "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)

    print(f"\n[RD029] ALL DONE in {time.time()-t0:.1f}s!")
    print(f"  Audit JSON: {audit_path}")
    print(f"  Trades CSV: {ledger_path} ({len(ledger_df)} rows)")
    print(f"  Daily NAV : {nav_path} ({nav_df.shape})")

    # Print clean overview
    for wn, _, _ in windows_chain:
        print(f"\n=== {wn} (0.10% RT fee, 0% Cash) ===")
        wd = chain_summary[wn]
        for sn in chain_strats:
            m = wd[sn]["strategy"]
            if sn == "BH":
                print(f"  {sn:28s}: Mult={m['total_mult']:5.2f}x Ann={m['ann_ret_pct']:+6.2f}% MDD={m['mdd_pct']:7.2f}% Sharpe={m['sharpe']:5.2f} W={m['avg_weight_pct']:5.1f}%")
            else:
                st = wd[sn]["same_avg_weight_bh"]
                iv = wd[sn]["pure_1overvol_matched"]
                tr_info = f"Tr={m['n_trades']:2d}(W={m['trade_win_rate_pct']}%,PL={m['trade_payoff_ratio']})" if "n_trades" in m else ""
                print(f"  {sn:28s}: Mult={m['total_mult']:5.2f}x Ann={m['ann_ret_pct']:+6.2f}% MDD={m['mdd_pct']:7.2f}% Sh={m['sharpe']:5.2f} W={m['avg_weight_pct']:5.1f}% | vsSameW={wd[sn]['alpha_vs_same_w_ann_pp']:+5.2f}pp(Sh{wd[sn]['sharpe_vs_same_w']:+.2f}) vs1/V={wd[sn]['alpha_vs_1overvol_ann_pp']:+5.2f}pp | {tr_info}")

    print("\n=== S4 SECTOR + RESCUE ETF (2008.08 ~ 2026.11, 0.10% RT, 0% Cash) ===")
    for wn in ["S4_18Y_2008_2026", "S4_510300_2012_2026", "S4_MODERN_2016_2026", "S4_6Y_2021_2026", "S4_3Y_2024_2026"]:
        print(f"[{wn}]")
        for sn, m in s4_summary[wn].items():
            print(f"  {sn:34s}: Mult={m['total_mult']:5.2f}x Ann={m['ann_ret_pct']:+6.2f}% MDD={m['mdd_pct']:7.2f}% Sh={m['sharpe']:5.2f} ExBH={m['excess_ann_vs_bh_pp']:+5.2f}pp ExEW={m['excess_ann_vs_all14ew_pp']:+5.2f}pp")


if __name__ == "__main__":
    main()

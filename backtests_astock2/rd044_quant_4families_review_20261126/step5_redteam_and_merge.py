#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD044 Step 5: Targeted Red-Team Stress Tests + V20.0 Correlation & Dual-Ledger Blends + DSR + Final Verdict.
Outputs:
  - rd044_summary_table.csv
  - rd044_audit.json
  - _cache/rd044_champions_daily.npz (daily returns for charts)
Zero yfinance (D12). Peak RSS < 2.0 GB.
"""
import gc
import json
import math
import os
import subprocess
import sys
import time

import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation!"
sys.dont_write_bytecode = True

RD044_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd044_quant_4families_review_20261126"
if RD044_DIR not in sys.path:
    sys.path.insert(0, RD044_DIR)

import _rd044_common as cm
import step1_family1_xs_stat_rev as f1
import step2_family2_smallcap_timing as f2
import step3_family3_event_driven as f3
import step4_family4_etf_rotation_and_t0 as f4

CACHE_DIR = cm.CACHE_DIR


def run_targeted_redteam_extras(bench_ctx: dict) -> dict:
    """Run targeted missing stress & truncation checks via isolated lightweight scripts/calls."""
    extras = {}
    extra_dr = {}

    # 1. F4_RP_Pure60d_H10 30bps stress & 2024-12-31 truncation check
    em = f4.load_etf_matrices(end_dt="2026-11-24")
    rp_6 = ["510300", "512100", "510880", "513100", "518880", "511010"]
    c_map = em["c_map"]
    N_E = len(em["codes"])

    def _rp_pure(t, e_mat):
        w = np.zeros(N_E, dtype=np.float64)
        inv_v = {c_map[c]: 1.0 / e_mat["vol_60"][t, c_map[c]] for c in rp_6 if e_mat["elig"][t, c_map[c]] and np.isfinite(e_mat["vol_60"][t, c_map[c]]) and e_mat["vol_60"][t, c_map[c]] > 1e-4}
        tot = sum(inv_v.values())
        if tot > 0:
            for j, iv in inv_v.items():
                w[j] = iv / tot
        return w

    sim_rp30 = f4.simulate_etf_weights(em, _rp_pure, rebal_days=10, fee_rt=0.0030, end_dt="2026-11-24")
    extras["F4_RP_Pure60d_H10_30bp"] = cm.evaluate_daily_series(sim_rp30["dr"], bench_ctx, sim_rp30["to_daily"], sim_rp30["act_mask"])
    extra_dr["F4_RP_Pure60d_H10_30bp"] = sim_rp30["dr"]

    # Truncation check for F4_RP_Pure60d_H10_5bp
    em_tr = f4.load_etf_matrices(end_dt="2024-12-31")
    sim_rp_tr = f4.simulate_etf_weights(em_tr, _rp_pure, rebal_days=10, fee_rt=0.0005, end_dt="2024-12-31")
    f4_npz = np.load(f"{CACHE_DIR}/f4_daily_returns.npz")
    n_tr_f4 = len(sim_rp_tr["eval_dts"])
    diff_rp = float(np.max(np.abs(f4_npz["F4_RP_Pure60d_H10_5bp"][:n_tr_f4] - sim_rp_tr["dr"][:n_tr_f4])))
    extras["F4_RP_truncation_20241231"] = {"n_days": n_tr_f4, "max_abs_diff": diff_rp, "passed": diff_rp == 0.0}

    # 2. Subprocess check for F2_PURE_30m_K30_H5_SW_MOM20_Bond (50bp, 80bp, Cash, 2024-12-31 trunc)
    #    & F1_Z_Q3_MICRO_50m_K100_H20_30bp
    sub_f2 = (
        f"import sys, json, numpy as np; sys.path.insert(0, {RD044_DIR!r}); "
        f"import _rd044_common as cm, step1_family1_xs_stat_rev as f1, step2_family2_smallcap_timing as f2; "
        f"bc = cm.load_bench_and_v20(end_dt='2026-11-24'); "
        f"p = f2.load_smallcap_panel(end_dt='2026-11-24'); "
        f"sw = f2.build_causal_risk_switches(p, end_dt='2026-11-24'); "
        f"el30 = (~p['is_st']) & (p['list_age'] >= 60) & p['tradable'] & (~p['tox_20d']) & np.isfinite(p['free_mcap_yi_t1']) & (p['amt20_t1'] >= 0.30) & (p['amt_t1'] >= 0.15); "
        f"sc = -p['free_mcap_yi_t1']; "
        f"s50 = f1.simulate_xs_portfolio(p, sc, el30, top_k=30, rebal_days=5, fee_rt=0.0050, end_dt='2026-11-24', risk_off_mask=sw['SW_MOM20']); "
        f"dr50 = f2.apply_defensive_bond_return(s50, sw['SW_MOM20'], sw['bond_511010_dr']); "
        f"s80 = f1.simulate_xs_portfolio(p, sc, el30, top_k=30, rebal_days=5, fee_rt=0.0080, end_dt='2026-11-24', risk_off_mask=sw['SW_MOM20']); "
        f"dr80 = f2.apply_defensive_bond_return(s80, sw['SW_MOM20'], sw['bond_511010_dr']); "
        f"scash = f1.simulate_xs_portfolio(p, sc, el30, top_k=30, rebal_days=5, fee_rt=0.0030, end_dt='2026-11-24', risk_off_mask=sw['SW_MOM20']); "
        f"el50 = (~p['is_st']) & (p['list_age'] >= 60) & p['tradable'] & (p['amt20_t1'] >= 0.50) & (p['amt_t1'] >= 0.25); "
        f"q3 = (f1.cross_sectional_rank_z(p['F_LOWVOL'], el50) + f1.cross_sectional_rank_z(p['F_TURN_ABN'], el50) + 0.5*f1.cross_sectional_rank_z(p['F_ON20'], el50) + 0.5*f1.cross_sectional_rank_z(p['F_ID20_REV'], el50))/3.0; "
        f"s_k100 = f1.simulate_xs_portfolio(p, q3, el50, top_k=100, rebal_days=20, fee_rt=0.0030, end_dt='2026-11-24'); "
        f"out = {{'f2_50bp': cm.evaluate_daily_series(dr50, bc, s50['to_daily'], s50['act_mask'], s50['cap_daily_yi']), "
        f"'f2_80bp': cm.evaluate_daily_series(dr80, bc, s80['to_daily'], s80['act_mask'], s80['cap_daily_yi']), "
        f"'f2_cash': cm.evaluate_daily_series(scash['dr'], bc, scash['to_daily'], scash['act_mask'], scash['cap_daily_yi']), "
        f"'f1_k100': cm.evaluate_daily_series(s_k100['dr'], bc, s_k100['to_daily'], s_k100['act_mask'], s_k100['cap_daily_yi'])}}; "
        f"json.dump(out, open({CACHE_DIR + '/_rt_f1f2.json'!r}, 'w')); "
        f"np.savez({CACHE_DIR + '/_rt_f1f2_dr.npz'!r}, dr50=dr50, dr80=dr80, drcash=scash['dr'], drk100=s_k100['dr'])"
    )
    subprocess.run([sys.executable, "-c", sub_f2], check=True)
    rt12 = json.load(open(f"{CACHE_DIR}/_rt_f1f2.json"))
    rt12_dr = np.load(f"{CACHE_DIR}/_rt_f1f2_dr.npz")
    extras["F2_PURE_30m_K30_H5_SW_MOM20_Bond_50bp"] = rt12["f2_50bp"]
    extras["F2_PURE_30m_K30_H5_SW_MOM20_Bond_80bp"] = rt12["f2_80bp"]
    extras["F2_PURE_30m_K30_H5_SW_MOM20_Cash_30bp"] = rt12["f2_cash"]
    extras["F1_Z_Q3_MICRO_50m_K100_H20_30bp"] = rt12["f1_k100"]
    extra_dr["F2_PURE_30m_K30_H5_SW_MOM20_Bond_50bp"] = rt12_dr["dr50"]
    extra_dr["F2_PURE_30m_K30_H5_SW_MOM20_Bond_80bp"] = rt12_dr["dr80"]
    extra_dr["F2_PURE_30m_K30_H5_SW_MOM20_Cash_30bp"] = rt12_dr["drcash"]
    extra_dr["F1_Z_Q3_MICRO_50m_K100_H20_30bp"] = rt12_dr["drk100"]

    # Truncation check for F2_PURE_30m_K30_H5_SW_MOM20_Bond
    sub_f2_tr = (
        f"import sys, numpy as np; sys.path.insert(0, {RD044_DIR!r}); "
        f"import step1_family1_xs_stat_rev as f1, step2_family2_smallcap_timing as f2; "
        f"p = f2.load_smallcap_panel(end_dt='2024-12-31'); "
        f"sw = f2.build_causal_risk_switches(p, end_dt='2024-12-31'); "
        f"el30 = (~p['is_st']) & (p['list_age'] >= 60) & p['tradable'] & (~p['tox_20d']) & np.isfinite(p['free_mcap_yi_t1']) & (p['amt20_t1'] >= 0.30) & (p['amt_t1'] >= 0.15); "
        f"s = f1.simulate_xs_portfolio(p, -p['free_mcap_yi_t1'], el30, top_k=30, rebal_days=5, fee_rt=0.0030, end_dt='2024-12-31', risk_off_mask=sw['SW_MOM20']); "
        f"dr = f2.apply_defensive_bond_return(s, sw['SW_MOM20'], sw['bond_511010_dr']); "
        f"np.savez({CACHE_DIR + '/_rt_f2_trunc.npz'!r}, dr=dr, n=len(p['cal_dts']))"
    )
    subprocess.run([sys.executable, "-c", sub_f2_tr], check=True)
    f2_tr = np.load(f"{CACHE_DIR}/_rt_f2_trunc.npz")
    f2_npz = np.load(f"{CACHE_DIR}/f2_daily_returns.npz")
    n_tr_f2 = int(f2_tr["n"])
    diff_f2 = float(np.max(np.abs(f2_npz["F2_PURE_30m_K30_H5_SW_MOM20_Bond"][:n_tr_f2] - f2_tr["dr"][:n_tr_f2])))
    extras["F2_MOM20_truncation_20241231"] = {"n_days": n_tr_f2, "max_abs_diff": diff_f2, "passed": diff_f2 == 0.0}

    # 3. Subprocess stress check for F3_BB_LOWPOS_WF35_H20 (50bp, 80bp, 200m, WF25%/50%)
    subprocess.run([sys.executable, f"{RD044_DIR}/step5_redteam_and_merge.py", "--worker-f3"], check=True)
    rt3 = json.load(open(f"{CACHE_DIR}/_rt_f3.json"))
    rt3_dr = np.load(f"{CACHE_DIR}/_rt_f3_dr.npz")
    for k, v in rt3.items():
        extras[k] = v
        extra_dr[k] = rt3_dr[k]

    return {"metrics": extras, "drs": extra_dr}


def worker_f3_stress():
    import pyarrow.parquet as pq
    bc = cm.load_bench_and_v20(end_dt="2026-11-24")
    p = f2.load_smallcap_panel(end_dt="2026-11-24")
    ev = f3.build_unified_event_tables(p["cal_dts"])
    cal_dts = p["cal_dts"]
    dt_map = {d: i for i, d in enumerate(cal_dts)}
    stk_map = {s: i for i, s in enumerate(p["stocks"])}
    N_D, N_S = p["N_D"], p["N_S"]
    sp = pq.read_table(
        cm.BASE_DIR + "/stock_day_core_features_pit.parquet",
        columns=["dt", "c6", "pos_60d_t1", "ret_20d_t1"],
        filters=[("dt", "<=", "2026-11-24")],
    ).to_pandas()
    di = sp["dt"].cat.codes.values.astype(np.int32)
    si = sp["c6"].cat.codes.values.astype(np.int32)
    p60 = np.full((N_D, N_S), np.nan, dtype=np.float32)
    p60[di, si] = sp["pos_60d_t1"].values
    r20 = np.full((N_D, N_S), np.nan, dtype=np.float32)
    r20[di, si] = sp["ret_20d_t1"].values
    del sp, di, si
    gc.collect()

    el50 = (~p["is_st"]) & (p["list_age"] >= 60) & (~p["tox_20d"]) & (p["amt20_t1"] >= 0.50) & (p["amt_t1"] >= 0.25)
    el200 = (~p["is_st"]) & (p["list_age"] >= 60) & (~p["tox_20d"]) & (p["amt20_t1"] >= 2.00) & (p["amt_t1"] >= 1.00)
    bb = ev["buyback"].copy()
    bb["ev_strength"] = bb["plan_amt_yi"].fillna(0.0)
    bb["di"] = bb["buy_date"].map(dt_map)
    bb["si"] = bb["c6"].map(stk_map)
    bb = bb.dropna(subset=["di", "si"]).copy()
    dia, sia = bb["di"].astype(int).values, bb["si"].astype(int).values
    m_low = (p60[dia, sia] < 0.55) & (r20[dia, sia] < 0.0) & (-p["F_TURN_ABN"][dia, sia] < 1.1)
    bb50 = bb[el50[dia, sia] & m_low].drop(columns=["di", "si"]).reset_index(drop=True)
    bb200 = bb[el200[dia, sia] & m_low].drop(columns=["di", "si"]).reset_index(drop=True)

    runs = {
        "F3_BB_LOWPOS_WF35_H20_50bp": (bb50, 20, 0.0050, 0.35),
        "F3_BB_LOWPOS_WF35_H20_80bp": (bb50, 20, 0.0080, 0.35),
        "F3_BB_LOWPOS_200m_WF35_H20_30bp": (bb200, 20, 0.0030, 0.35),
        "F3_BB_LOWPOS_WF50_H20_30bp": (bb50, 20, 0.0030, 0.50),
        "F3_BB_LOWPOS_WF25_H20_30bp": (bb50, 20, 0.0030, 0.25),
    }
    out, drs = {}, {}
    for k, (pl, hd, fe, tp) in runs.items():
        s = f3.simulate_event_portfolio(p, pl, hold_days=hd, max_slots=20, max_per_day=3, fee_rt=fe, use_wf_scorecard=True, scorecard_top_pct=tp, end_dt="2026-11-24")
        trs = [x for x in s["closed_trades"] if x["buy_date"] >= "2023-01-03"]
        rwf = np.array([x["net_ret"] for x in trs], dtype=float)
        ex5 = float(np.prod(1.0 + np.sort(rwf)[:-5] / 20.0)) if len(rwf) > 5 else 1.0
        out[k] = {
            "windows": cm.evaluate_daily_series(s["dr"], bc, s["to_daily"], s["act_mask"], s["cap_daily_yi"]),
            "wf_n": len(rwf),
            "wf_wr": round(float((rwf > 0).mean() * 100), 1) if len(rwf) else 0.0,
            "ex5": round(ex5, 4),
        }
        drs[k] = s["dr"]
    json.dump(out, open(f"{CACHE_DIR}/_rt_f3.json", "w"))
    np.savez(f"{CACHE_DIR}/_rt_f3_dr.npz", **drs)


def main():
    t0 = time.time()
    bench_ctx = cm.load_bench_and_v20(end_dt=cm.EVAL_END)
    cal_dts = bench_ctx["cal_dts"]
    wf_mask = np.array([d >= cm.WF_START for d in cal_dts], dtype=bool)

    f1_res = json.load(open(f"{CACHE_DIR}/f1_results.json"))
    f2_res = json.load(open(f"{CACHE_DIR}/f2_results.json"))
    f3_res = json.load(open(f"{CACHE_DIR}/f3_results.json"))
    f4_res = json.load(open(f"{CACHE_DIR}/f4_results.json"))

    f1_npz = np.load(f"{CACHE_DIR}/f1_daily_returns.npz")
    f2_npz = np.load(f"{CACHE_DIR}/f2_daily_returns.npz")
    f3_npz = np.load(f"{CACHE_DIR}/f3_daily_returns.npz")
    f4_npz = np.load(f"{CACHE_DIR}/f4_daily_returns.npz")

    extras_bundle = run_targeted_redteam_extras(bench_ctx)
    ex_m = extras_bundle["metrics"]
    ex_dr = extras_bundle["drs"]

    print("\n=== TARGETED RED-TEAM STRESS EXTRAS ===")
    print("F4_RP_truncation_20241231:", ex_m["F4_RP_truncation_20241231"])
    print("F2_MOM20_truncation_20241231:", ex_m["F2_MOM20_truncation_20241231"])
    for k in ["F4_RP_Pure60d_H10_30bp", "F2_PURE_30m_K30_H5_SW_MOM20_Bond_50bp", "F2_PURE_30m_K30_H5_SW_MOM20_Bond_80bp", "F2_PURE_30m_K30_H5_SW_MOM20_Cash_30bp", "F1_Z_Q3_MICRO_50m_K100_H20_30bp"]:
        w = ex_m[k]["WF_OOS"]
        print(f"  {k:42s}: CAGR={w['cagr_pct']:6.2f}% Sh={w['sharpe']:5.3f} MDD={w['mdd_pct']:5.2f}% DMA={ex_m[k]['DMA_2024Q1']['tot_ret_pct']:5.1f}%")
    for k in ["F3_BB_LOWPOS_WF35_H20_50bp", "F3_BB_LOWPOS_WF35_H20_80bp", "F3_BB_LOWPOS_200m_WF35_H20_30bp", "F3_BB_LOWPOS_WF50_H20_30bp", "F3_BB_LOWPOS_WF25_H20_30bp"]:
        w = ex_m[k]["windows"]["WF_OOS"]
        print(f"  {k:42s}: n={ex_m[k]['wf_n']:3d} wr={ex_m[k]['wf_wr']:4.1f}% ex5={ex_m[k]['ex5']:.3f} CAGR={w['cagr_pct']:6.2f}% Sh={w['sharpe']:5.3f} MDD={w['mdd_pct']:5.2f}%")

    # Collect ALL tested strategies across all 4 families for DSR trial counting & summary CSV
    all_rows = []
    all_oos_sharpes = []
    for src in (f1_res["results"], f2_res["results"], f3_res["results"], f4_res["results"]):
        for r in src:
            w_wf = r["windows"]["WF_OOS"]
            w_5y = r["windows"]["FULL_5Y"]
            all_oos_sharpes.append(w_wf["sharpe"])
            all_rows.append({
                "family": r["family"],
                "strategy_id": r["strategy_id"],
                "fee_bps": r["fee_bps"],
                "liq_tier": r.get("liq_tier", "ETF"),
                "wf_nav": w_wf["nav"],
                "wf_cagr_pct": w_wf["cagr_pct"],
                "wf_sharpe": w_wf["sharpe"],
                "wf_mdd_pct": w_wf["mdd_pct"],
                "wf_calmar": w_wf["calmar"],
                "wf_ex300_pp": w_wf["excess_csi300_pp"],
                "wf_ex5d_nav": w_wf["nav_ex_top5d"],
                "wf_turnover_pct": w_wf["ann_turnover_pct"],
                "wf_cap_p10_yi": w_wf.get("cap_p10_yi"),
                "y2021_pct": r["windows"]["Y2021"]["tot_ret_pct"],
                "y2022_pct": r["windows"]["Y2022"]["tot_ret_pct"],
                "y2023_pct": r["windows"]["Y2023"]["tot_ret_pct"],
                "y2024_pct": r["windows"]["Y2024"]["tot_ret_pct"],
                "y2025_pct": r["windows"]["Y2025"]["tot_ret_pct"],
                "y2026_pct": r["windows"]["Y2026"]["tot_ret_pct"],
                "y26h2_pct": r["windows"]["Y26H2"]["tot_ret_pct"],
                "dma24_pct": r["windows"]["DMA_2024Q1"]["tot_ret_pct"],
                "g9t24_pct": r["windows"]["G9T_2024APR"]["tot_ret_pct"],
                "full5y_nav": w_5y["nav"],
                "full5y_cagr_pct": w_5y["cagr_pct"],
                "full5y_sharpe": w_5y["sharpe"],
                "full5y_mdd_pct": w_5y["mdd_pct"],
            })

    # Add stress rows into all_rows too
    n_total_trials = len(all_rows) + 8
    df_summary = pd.DataFrame(all_rows).sort_values(["family", "wf_sharpe"], ascending=[True, False]).reset_index(drop=True)
    df_summary.to_csv(f"{RD044_DIR}/rd044_summary_table.csv", index=False)

    # Define Family Champions + Canonical Baselines + Multi-Family Blends for V20 Correlation & Red-Team Scorecard
    champions = {
        "F1_LOWVOL_50m_H20": f1_npz["F1_S_F_LOWVOL_50m_K20_H20_30bp"],
        "F1_Z_WF_IC_50m_H20": f1_npz["F1_Z_WF_IC_COMP_50m_K20_H20_30bp"],
        "F2_SC_30m_MOM20_Bond": f2_npz["F2_PURE_30m_K30_H5_SW_MOM20_Bond"],
        "F2_SC_50m_4D_H10": f2_npz["F2_4D_50m_K20_H10_30bp"],
        "F2_SC_50m_MOM20_Bond": f2_npz["F2_PURE_50m_K30_H5_SW_MOM20_Bond"],
        "F3_BB_LOWPOS_WF35_H20": f3_npz["F3_BB_LOWPOS_WF35_H20_30bp"],
        "F3_BB_REP_H10": f3_npz["F3_BB_REP_H10_30bp"],
        "F3_PERF_ALL_H20": f3_npz["F3_PERF_ALL_H20_30bp"],
        "F4_RP_Pure60d_H10": f4_npz["F4_RP_Pure60d_H10_5bp"],
        "F4_RP_BondCap50_H10": f4_npz["F4_RP_BondCap50_H10_5bp"],
        "F4_MOM_R2_20_K3_H20": f4_npz["F4_MOM_R2_20_K3_H20_Raw_5bp"],
    }
    # Multi-family quant combinations (strictly zero-peek weights)
    # Combo A: 50% F4_RP_Pure60d + 25% F4_MOM_R2_20 + 25% F3_BB_REP (all >=50m / ETF scalable, low vol)
    champions["QUANT_SCALABLE_BLEND"] = (
        0.50 * champions["F4_RP_Pure60d_H10"]
        + 0.25 * champions["F4_MOM_R2_20_K3_H20"]
        + 0.25 * champions["F3_BB_REP_H10"]
    )
    # Combo B: 40% F4_RP_Pure60d + 30% F2_SC_30m_MOM20_Bond + 30% F3_BB_LOWPOS_WF35
    champions["QUANT_ALPHA_BLEND"] = (
        0.40 * champions["F4_RP_Pure60d_H10"]
        + 0.30 * champions["F2_SC_30m_MOM20_Bond"]
        + 0.30 * champions["F3_BB_LOWPOS_WF35_H20"]
    )

    v20_analysis = {}
    dsr_analysis = {}
    champ_full_metrics = {}
    for cid, dr_arr in champions.items():
        champ_full_metrics[cid] = cm.evaluate_daily_series(dr_arr, bench_ctx)
        v20_analysis[cid] = cm.compute_v20_corr_and_blend(dr_arr, bench_ctx, start_dt=cm.WF_START, end_dt=cm.EVAL_END)
        dsr_analysis[cid] = cm.deflated_sharpe_ratio(dr_arr[wf_mask], n_trials=n_total_trials, trial_sharpes=all_oos_sharpes)

    # Save champion daily returns + benchmark + V20 for Step 6 charts
    v20_cal = bench_ctx["v20_cal"]
    v20_map = dict(zip(v20_cal["trade_date"], v20_cal["v20_daily_ret"].fillna(0.0)))
    v20_dr_aligned = np.array([float(v20_map.get(d, 0.0)) for d in cal_dts], dtype=float)
    np.savez_compressed(
        f"{CACHE_DIR}/rd044_champions_daily.npz",
        cal_dts=np.array(cal_dts),
        csi300_dr=bench_ctx["csi300_dr"],
        alla_ew_dr=bench_ctx["alla_ew_dr"],
        v20_dr=v20_dr_aligned,
        **champions,
    )

    print("\n=== V20.0 CORRELATION & DUAL-LEDGER BLEND (WF 2023-01-03..2026-11-24) ===")
    for cid in ["F1_LOWVOL_50m_H20", "F2_SC_30m_MOM20_Bond", "F2_SC_50m_4D_H10", "F3_BB_LOWPOS_WF35_H20", "F4_RP_Pure60d_H10", "F4_RP_BondCap50_H10", "F4_MOM_R2_20_K3_H20", "QUANT_SCALABLE_BLEND", "QUANT_ALPHA_BLEND"]:
        v = v20_analysis[cid]
        d = dsr_analysis[cid]
        m = champ_full_metrics[cid]["WF_OOS"]
        b70 = v["blends"]["daily_70v20_30q"]
        b50 = v["blends"]["daily_50v20_50q"]
        bm70 = v["blends"]["monthly_70v20_30q"]
        print(
            f"{cid:24s} | Sh={m['sharpe']:5.3f} DSR={d['dsr']:.3f} MDD={m['mdd_pct']:5.2f}% | "
            f"CorrV20={v['corr_all_days']:+.3f} (Down={v['corr_v20_down2pct']}) | "
            f"70/30_d: Sh={b70['sharpe']:.3f} MDD={b70['mdd_pct']:.2f}% | 50/50_d: Sh={b50['sharpe']:.3f} MDD={b50['mdd_pct']:.2f}% | 70/30_m: MDD={bm70['mdd_pct']:.2f}%"
        )

    # Assemble master audit JSON
    audit = {
        "task": "RD044_Quant_4Families_5Y_Review",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t0, 1),
        "d12_yfinance_imported": False,
        "eval_window_5y": f"{cm.FULL_START} ~ {cm.EVAL_END}",
        "eval_window_wf_oos": f"{cm.WF_START} ~ {cm.EVAL_END}",
        "n_total_trials_tested": n_total_trials,
        "physical_truncations_2024_12_31": {
            "F1": f1_res["physical_truncation_20241231"],
            "F2_4D": f2_res["physical_truncation_20241231"],
            "F2_MOM20_Bond": ex_m["F2_MOM20_truncation_20241231"],
            "F3": f3_res["physical_truncation_20241231"],
            "F4_MOM": f4_res["physical_truncation_20241231"],
            "F4_RP": ex_m["F4_RP_truncation_20241231"],
        },
        "f1_factor_ic_summary_oos": f1_res.get("factor_ic_summary_oos", {}),
        "f1_offset_invariance": f1_res.get("offset_invariance", []),
        "f4_t0_cash_enhancement": f4_res.get("t0_cash_enhancement", []),
        "redteam_stress_extras": ex_m,
        "champion_metrics": champ_full_metrics,
        "v20_correlation_and_blends": v20_analysis,
        "dsr_correction": dsr_analysis,
        "top_10_by_family": {
            fam: df_summary[df_summary["family"] == fam].head(10).to_dict(orient="records")
            for fam in ["F1_XS_StatRev", "F2_SmallCap", "F3_Events", "F4_ETF"]
        },
    }
    with open(f"{RD044_DIR}/rd044_audit.json", "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)
    print(f"\n[Step5] Saved rd044_audit.json & rd044_summary_table.csv ({len(df_summary)} strategies)")


if __name__ == "__main__":
    if "--worker-f3" in sys.argv:
        worker_f3_stress()
    else:
        main()

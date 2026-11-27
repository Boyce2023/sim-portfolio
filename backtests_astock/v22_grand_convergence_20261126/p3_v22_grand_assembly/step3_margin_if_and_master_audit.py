#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
V22.0 Wave 2 Step 3:
  - Champion Verification & 2025-2026 Trade-by-Trade Diff vs V21.0
  - 4-Tier 1.5x Margin Real-World Audit (L1..L4 incl. Buwen Selective) with 5.5% interest & intraday-low MMR
  - Outside-Stock Independent 5x National Team Rescue IF Futures (P_IF_5x_V3EOD_ge65_H3_SL2, 18 trades)
    Parallel Accounting + Crash Co-Movement Audit
  - Exports: v22_master_audit.json, v22_margin_and_if_table.csv, v22_2526_diff_vs_v21.csv, v22_trades_champion.csv
Zero yfinance (D12). Read-only on V20/V21/RD038/RD048/RD049.
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import json
import math
import pickle
import sys
import time
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
assert "yfinance" not in sys.modules, "D12 VIOLATION"
sys.dont_write_bytecode = True

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/v22_grand_convergence_20261126/p3_v22_grand_assembly"
CACHE_DIR = f"{OUT_DIR}/_cache"
if OUT_DIR not in sys.path:
    sys.path.insert(0, OUT_DIR)

import _v22_engine as v22
sys.path.insert(0, f"{v22.RD048}")
import step3_helpers as h3

CHAMPION_NAME = "V21_M5_B_NoXQ_Pos5"
IF_VARIANT = "P_IF_5x_V3EOD_ge65_H3_SL2"


def eval_daily_7win(dr_5y: np.ndarray, cal_5y: list[str], bench_df: pd.DataFrame) -> dict:
    """Compute exact 7-window metrics on any daily return series."""
    idx = {d: i for i, d in enumerate(cal_5y)}
    csi_5y = bench_df["csi300_daily_ret"].to_numpy(float)
    out = {}
    for wn, sdt, edt in v22.D15_WINDOWS:
        pos = [idx[d] for d in cal_5y if sdt <= d <= edt]
        ds_w = dr_5y[pos]
        T_w = len(ds_w)
        nav = float(np.prod(1.0 + ds_w))
        mdd, dd2 = v22.calc_top2_dd(ds_w)
        sd = float(np.std(ds_w, ddof=1)) if T_w > 1 else 0.0
        sh = float(np.mean(ds_w) / sd * math.sqrt(v22.eng.TRD_DAYS_YEAR)) if sd > 1e-12 else 0.0
        cagr = (nav ** (v22.eng.TRD_DAYS_YEAR / T_w) - 1.0) * 100.0 if nav > 0 else -100.0
        calmar = (cagr / mdd) if mdd > 1e-6 else 0.0
        csi_pct = (float(np.prod(1.0 + csi_5y[pos])) - 1.0) * 100.0
        out[wn] = {
            "nav": round(nav, 4), "mdd_pct": mdd, "second_mdd_pct": dd2,
            "sharpe": round(sh, 3), "calmar": round(calmar, 2), "cagr_pct": round(cagr, 2),
            "csi300_pct": round(csi_pct, 2), "excess_csi300_pp": round((nav - 1.0) * 100.0 - csi_pct, 2),
        }
    return out


def calc_custom_combo(dr_stk: np.ndarray, dr_fut: np.ndarray, w_stk: float, w_fut: float, cal_5y: list[str]) -> dict:
    """Compute DailyRebal, QuarterlyRebal, NoRebal_Separate for arbitrary (w_stk, w_fut) and Additive Overlay."""
    T = len(cal_5y)
    tot_w = w_stk + w_fut
    ws, wf = w_stk / tot_w, w_fut / tot_w
    dr_daily = ws * dr_stk + wf * dr_fut

    dr_q = np.zeros(T, dtype=float)
    vs, vf = ws, wf
    p_tot = 1.0
    q_tags = [f"{d[:4]}-Q{(int(d[5:7]) - 1) // 3 + 1}" for d in cal_5y]
    for i in range(T):
        vs *= (1.0 + dr_stk[i])
        vf *= (1.0 + dr_fut[i])
        tot = vs + vf
        dr_q[i] = tot / p_tot - 1.0
        if i + 1 < T and q_tags[i + 1] != q_tags[i]:
            vs, vf = ws * tot, wf * tot
        p_tot = tot

    dr_nr = np.zeros(T, dtype=float)
    ns, nf = ws, wf
    p_nr = 1.0
    for i in range(T):
        ns *= (1.0 + dr_stk[i])
        nf *= (1.0 + dr_fut[i])
        tot = ns + nf
        dr_nr[i] = tot / p_nr - 1.0
        p_nr = tot

    dr_overlay = np.clip(dr_stk + w_fut * dr_fut, -0.99, None)
    return {
        "FixedWeight_DailyRebal": dr_daily,
        "Quarterly_Rebal": dr_q,
        "NoRebal_Separate": dr_nr,
        "Additive_100Stk_Plus_15IF": dr_overlay,
    }


def main():
    t0 = time.time()
    print("[Step 3.1] Loading caches & Step 1 / Step 2 outputs...", flush=True)
    with open(f"{v22.RD038}/_cache/rd038_master_cache.pkl", "rb") as f:
        cache = pickle.load(f)
    cal_5y = cache["cal_5y"]
    bench_df = cache["bench_5y"]
    reg = pd.read_parquet(f"{v22.RD049}/_cache/rd049_daily_regime_pit.parquet")
    reg_idx = v22.cm49.build_2d_states(reg, y_cut=42.0, x_sh=20.0, x_dp=42.0).set_index("trade_date")

    with open(f"{CACHE_DIR}/step1_ablation_results.pkl", "rb") as f:
        s1 = pickle.load(f)
    with open(f"{CACHE_DIR}/step2_truncation_proof.json", encoding="utf-8") as f:
        s2_trunc = json.load(f)
    with open(f"{CACHE_DIR}/v22_margin_eligibility_ext.json", encoding="utf-8") as f:
        elig_map = json.load(f)["pair_elig"]
    with open(f"{CACHE_DIR}/v22_5m_low_lu.pkl", "rb") as f:
        f5_low_lu = pickle.load(f)

    sim_030 = s1["sim_030"]
    evals = s1["evals"]

    # 1. Export Champion Trade Ledger & 2025-2026 Diff vs V21.0
    print("[Step 3.2] Exporting Champion trades & 2025-2026 diff vs V21.0...", flush=True)
    tr_champ = sim_030[CHAMPION_NAME]["trades_df"].copy()
    tr_v21 = sim_030["B1_V21"]["trades_df"].copy()

    # Check 100% margin eligibility coverage on all evaluated models
    key_models = ["B1_V21", "V21_M4_P2_DirA", "V21_M5_A_Pos5", CHAMPION_NAME, "V21_M5_B_Pos5"]
    for km in key_models:
        for r in sim_030[km]["trades_df"].itertuples(index=False):
            k = f"{str(r.code).zfill(6)}|{str(r.buy_date)[:10]}"
            assert k in elig_map and elig_map[k] is not None, f"Missing margin eligibility for {k} in {km}"

    low_tail_strats = {"1to2", "2to3", "high", "4to5"}
    tr_champ["t1_margin_elig"] = [bool(elig_map[f"{str(r.code).zfill(6)}|{str(r.buy_date)[:10]}"]) for r in tr_champ.itertuples(index=False)]
    tr_champ["L3_lev"] = np.where(tr_champ["t1_margin_elig"], 1.5, 1.0)
    tr_champ["L4_buwen_lev"] = np.where(tr_champ["t1_margin_elig"] & tr_champ["strategy"].isin(low_tail_strats), 1.5, 1.0)
    tr_champ["light_5"] = tr_champ["buy_date"].map(reg_idx["light_5"].to_dict())
    tr_champ["net_ret_050"] = (1.0 + tr_champ["net_ret"].to_numpy(float)) / (1.0 - 0.0030) * (1.0 - 0.0050) - 1.0
    tr_champ["net_ret_080"] = (1.0 + tr_champ["net_ret"].to_numpy(float)) / (1.0 - 0.0030) * (1.0 - 0.0080) - 1.0
    champ_cols = [c for c in ["buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name", "strategy", "tier", "score", "net_ret", "net_ret_050", "net_ret_080", "light_5", "t1_margin_elig", "L3_lev", "L4_buwen_lev"] if c in tr_champ.columns]
    tr_champ[champ_cols].to_csv(f"{OUT_DIR}/v22_trades_champion.csv", index=False, encoding="utf-8-sig")

    sc_2526 = v22.run_dual_scissors_and_diff(f"{CHAMPION_NAME}_vs_V21", tr_champ, tr_v21, evals[f"{CHAMPION_NAME}__030"], evals["B1_V21__030"])
    df_diff_all = pd.DataFrame(sc_2526["diff_rows"])
    df_diff_2526 = df_diff_all[df_diff_all["buy_date"] >= "2025-01-01"].sort_values(["buy_date", "diff_type"]).reset_index(drop=True)
    df_diff_2526.to_csv(f"{OUT_DIR}/v22_2526_diff_vs_v21.csv", index=False, encoding="utf-8-sig")
    print(f"  2025-2026 Diff vs V21: total={len(df_diff_2526)} (ADDED={(df_diff_2526['diff_type']=='ADDED').sum()}, REMOVED={(df_diff_2526['diff_type']=='REMOVED').sum()}, MODIFIED={(df_diff_2526['diff_type']=='MODIFIED').sum()})", flush=True)

    # 1b. Exact Champion-Centric LOO Attribution on V21_M5_B_NoXQ_Pos5
    print("[Step 3.2b] Computing exact Champion-centric LOO attribution...", flush=True)
    dirA_raw = pd.read_parquet(f"{v22.P1A}/dirA_pass_Risk7D2_Tight80_raw.parquet")
    with open(f"{CACHE_DIR}/v22_dirb_ledgers_full.pkl", "rb") as f:
        dirb = pickle.load(f)["ledgers"]
    c_p2_da = v22.apply_v22_modifications(cache, reg_idx, use_p2=True, use_dirA=True, dirA_raw_df=dirA_raw)
    c_p2_only = v22.apply_v22_modifications(cache, reg_idx, use_p2=True, use_dirA=False)
    c_da_only = v22.apply_v22_modifications(cache, reg_idx, use_p2=False, use_dirA=True, dirA_raw_df=dirA_raw)

    sim_no_7f = v22.run_v22_sim(c_p2_da, v22.CFG_V21, raw_4to5_df=dirb["SJ114_E4_DtDefer"]["raw"], pos_mode="Pos5", fee_mode="030", tier_lbl="4to5_SJ114_E4_DtDefer")
    sim_no_da = v22.run_v22_sim(c_p2_only, v22.CFG_V21, raw_4to5_df=dirb["SJ114_7f_DtDefer"]["raw"], pos_mode="Pos5", fee_mode="030", tier_lbl="4to5_SJ114_7f_DtDefer")
    sim_no_p2 = v22.run_v22_sim(c_da_only, v22.CFG_V21, raw_4to5_df=dirb["SJ114_7f_DtDefer"]["raw"], pos_mode="Pos5", fee_mode="030", tier_lbl="4to5_SJ114_7f_DtDefer")
    sim_pure_4to5 = v22.run_v22_sim(c_p2_only, v22.CFG_V21, raw_4to5_df=dirb["SJ114_E4_DtDefer"]["raw"], pos_mode="Pos5", fee_mode="030", tier_lbl="4to5_SJ114_E4_DtDefer")

    ev_champ = evals[f"{CHAMPION_NAME}__030"]
    champ_dr_wf = sim_030[CHAMPION_NAME]["dr_wf"]
    champ_loo = {}
    for lbl, sim_old, ev_old in [
        ("Champ_vs_V21", sim_030["B1_V21"], evals["B1_V21__030"]),
        ("LOO_P2_on_Champ", sim_no_p2, v22.evaluate_d15_full("Champ_NoP2", "LOO", sim_no_p2, cache, perm_n=0)),
        ("LOO_DirA_on_Champ", sim_no_da, v22.evaluate_d15_full("Champ_NoDirA", "LOO", sim_no_da, cache, perm_n=0)),
        ("LOO_4to5_SJ114_on_Champ", sim_030["V21_M4_P2_DirA"], evals["V21_M4_P2_DirA__030"]),
        ("LOO_7f_on_Champ", sim_no_7f, v22.evaluate_d15_full("Champ_No7f", "LOO", sim_no_7f, cache, perm_n=0)),
        ("Pure_V21_P2_SJ114_E4_vs_Champ", sim_pure_4to5, v22.evaluate_d15_full("Pure_V21_P2_SJ114_E4", "LOO", sim_pure_4to5, cache, perm_n=0)),
        ("Add_XQLt6_over_Champ", sim_030[CHAMPION_NAME], ev_champ),
    ]:
        if lbl == "Add_XQLt6_over_Champ":
            sc_l = v22.run_dual_scissors_and_diff(lbl, sim_030["V21_M5_B_Pos5"]["trades_df"], tr_champ, evals["V21_M5_B_Pos5__030"], ev_champ)
            p_l = v22.paired_perm_test(sim_030["V21_M5_B_Pos5"]["dr_wf"], champ_dr_wf, n_perm=1000)
        else:
            sc_l = v22.run_dual_scissors_and_diff(lbl, tr_champ, sim_old["trades_df"], ev_champ, ev_old)
            p_l = v22.paired_perm_test(champ_dr_wf, sim_old["dr_wf"], n_perm=1000)
        champ_loo[lbl] = {"cf_5y": sc_l["cf_5y"], "cf_wf": sc_l["cf_wf"], "paired_wf": p_l, "n_diff": len(sc_l["diff_rows"])}
        print(f"    {lbl:30s}: WF_mult={sc_l['cf_wf']['raw_mult']:.4f}, ex_both={sc_l['cf_wf']['mult_ex_both']:.4f}, ex_both_mod={sc_l['cf_wf']['mult_ex_both_and_mod']:.4f}, t={p_l['paired_t']}, p1={p_l['paired_perm_p_1sided']}", flush=True)

    # 2. 4-Tier 1.5x Margin Audit
    print("[Step 3.3] Running 4-Tier 1.5x Margin Audit (L1..L4)...", flush=True)
    bar_low_lu = v22.cm49.preload_low_bars_for_trades([sim_030[km]["trades_df"] for km in key_models], cal_5y)
    margin_modes = ["L1_10x_Cash", "L2_15x_TheoFull", "L3_15x_EligOnly", "L4_15x_BuwenSelective"]

    margin_rows = []
    margin_details = {}
    champ_lev_curves = {}
    for km in key_models:
        margin_details[km] = {}
        sr = sim_030[km]
        tr_k = sr["trades_df"].copy()
        tr_k["elig"] = [bool(elig_map[f"{str(r.code).zfill(6)}|{str(r.buy_date)[:10]}"]) for r in tr_k.itertuples(index=False)]
        elig_by_strat = {st: round(float(g["elig"].mean() * 100.0), 1) for st, g in tr_k.groupby("strategy")}
        for mm in margin_modes:
            res_m = v22.simulate_margin_tier(sr, cal_5y, bar_low_lu, f5_low_lu, elig_map, mode=mm, annual_rate=0.055)
            margin_details[km][mm] = {k: v for k, v in res_m.items() if k != "dr_lev"}
            margin_details[km][mm]["elig_by_strat"] = elig_by_strat
            if km == CHAMPION_NAME:
                champ_lev_curves[mm] = res_m["dr_lev"]
            w = res_m["windows"]
            margin_rows.append({
                "sleeve": "STOCK_ONLY", "model": km, "mode": mm,
                "n_trades": res_m["n_trades"], "elig_pct": res_m["elig_pct"], "lev_pct": res_m["lev_pct"],
                "avg_eff_lev": res_m["avg_eff_leverage"], "min_mmr_pct": res_m["min_mmr_pct"],
                "n_warn_150": res_m["n_warn_below_150"], "n_liq_130": res_m["n_liq_below_130"],
                "5Y_nav": w["FULL_5Y"]["nav"], "5Y_mdd": w["FULL_5Y"]["mdd_pct"], "5Y_dd2": w["FULL_5Y"]["second_mdd_pct"], "5Y_sh": w["FULL_5Y"]["sharpe"], "5Y_cal": w["FULL_5Y"]["calmar"],
                "WF_nav": w["WF_2326"]["nav"], "WF_mdd": w["WF_2326"]["mdd_pct"], "WF_sh": w["WF_2326"]["sharpe"],
                "OOS_nav": w["OOS_2426"]["nav"], "OOS_mdd": w["OOS_2426"]["mdd_pct"],
                "Y2526_nav": w["Y2025_2026"]["nav"], "Y26_nav": w["Y2026"]["nav"], "H2_nav": w["Y2026_H2"]["nav"],
            })

    # 3. Outside-Stock 5x National Team Rescue IF Futures Parallel Accounting
    print("[Step 3.4] Running 5x Rescue IF Futures Parallel & Crash Co-Movement Audit...", flush=True)
    g4_pq = pd.read_parquet(f"{v22.RD048}/wave1b_gem2_gem4/rd048_gem4_trades.parquet")
    if5_all = g4_pq[g4_pq["variant"] == IF_VARIANT].copy().reset_index(drop=True)
    assert len(if5_all) == 18, f"Expected 18 IF 5x trades, got {len(if5_all)}"
    dr_if5, if5_cal = h3.build_gem4_daily_returns(if5_all, cal_5y, "2026-11-16")
    dr_cash = np.zeros(len(cal_5y), dtype=float)

    if_standalone_18 = {
        "n_total": int(len(if5_all)),
        "compound_18_nav": round(float(np.prod(1.0 + if5_all["net_ret"].to_numpy(float))), 4),
        "wr_18_pct": round(float((if5_all["net_ret"] > 0).mean() * 100.0), 2),
        "n_in_5y_cal": int(len(if5_cal)),
        "compound_16_cal_nav": round(float(np.prod(1.0 + if5_cal["net_ret"].to_numpy(float))), 4),
        "pre_window_trade": if5_all[if5_all["buy_date"] < "2021-11-16"][["buy_date", "exit_date", "net_ret", "exit_reason"]].to_dict("records"),
        "post_window_trade": if5_all[if5_all["buy_date"] > "2026-11-16"][["buy_date", "exit_date", "net_ret", "exit_reason"]].to_dict("records"),
        "trades_18": if5_all[["buy_date", "exit_date", "net_ret", "min_margin_ratio_pct", "exit_reason"]].to_dict("records"),
    }

    comov_audit = {}
    if_combo_audit = {}
    wf_off = {d: i for i, d in enumerate(cal_5y)}[v22.eng.WF_START]

    for lev_lbl in ("L1_10x_Cash", "L3_15x_EligOnly", "L4_15x_BuwenSelective"):
        dr_stk = champ_lev_curves[lev_lbl]
        comov = h3.audit_crash_window_comovement(tr_champ, dr_stk, if5_all, cal_5y, 0.15)
        # Also audit extreme crash days where IF is active (e.g. 2024-02-05, 2024-02-06, 2025-04-08, 2026-10-12)
        act_mask = np.abs(dr_if5) > 1e-12
        big_drop_stk_days = []
        for idx_d in np.argsort(dr_stk)[:10]:
            big_drop_stk_days.append({
                "date": cal_5y[idx_d], "stk_pct": round(float(dr_stk[idx_d] * 100), 2),
                "if5_pct": round(float(dr_if5[idx_d] * 100), 2),
                "comb_85_15_pct": round(float((0.85 * dr_stk[idx_d] + 0.15 * dr_if5[idx_d]) * 100), 2),
                "comb_100_15_norm_pct": round(float(((1.0 * dr_stk[idx_d] + 0.15 * dr_if5[idx_d]) / 1.15) * 100), 2),
            })
        comov["worst10_stk_days_protection"] = big_drop_stk_days
        comov_audit[lev_lbl] = comov

        # Mode B (85/15) + Extra 15% External Pool (100/115 = 86.96%/13.04% & Additive 1.0 + 0.15*IF)
        b_85 = calc_custom_combo(dr_stk, dr_if5, 0.85, 0.15, cal_5y)
        b_85_cash = calc_custom_combo(dr_stk, dr_cash, 0.85, 0.15, cal_5y)
        b_115 = calc_custom_combo(dr_stk, dr_if5, 1.00, 0.15, cal_5y)
        b_115_cash = calc_custom_combo(dr_stk, dr_cash, 1.00, 0.15, cal_5y)

        if_combo_audit[lev_lbl] = {}
        for scheme_tag, dr_dict, cash_dict in [
            ("ModeB_85Stk_15IF", b_85, b_85_cash),
            ("ExtraPool_100Stk_15IF", b_115, b_115_cash),
        ]:
            for acc_nm, dr_c in dr_dict.items():
                if scheme_tag == "ModeB_85Stk_15IF" and acc_nm == "Additive_100Stk_Plus_15IF":
                    continue
                w7 = eval_daily_7win(dr_c, cal_5y, bench_df)
                w7_cash = eval_daily_7win(cash_dict[acc_nm], cal_5y, bench_df)
                p_vs_stk = v22.paired_perm_test(dr_c[wf_off:], dr_stk[wf_off:], n_perm=1000)
                p_vs_cash = v22.paired_perm_test(dr_c[wf_off:], cash_dict[acc_nm][wf_off:], n_perm=1000)
                full_tag = f"{CHAMPION_NAME}_{lev_lbl}__{scheme_tag}__{acc_nm}"
                if_combo_audit[lev_lbl][f"{scheme_tag}__{acc_nm}"] = {
                    "windows": w7,
                    "mult_vs_cash_5y": round(w7["FULL_5Y"]["nav"] / w7_cash["FULL_5Y"]["nav"], 4),
                    "mult_vs_cash_wf": round(w7["WF_2326"]["nav"] / w7_cash["WF_2326"]["nav"], 4),
                    "paired_vs_stk_wf": p_vs_stk,
                    "paired_vs_cash_wf": p_vs_cash,
                }
                margin_rows.append({
                    "sleeve": f"{scheme_tag}__{acc_nm}", "model": CHAMPION_NAME, "mode": lev_lbl,
                    "n_trades": int(len(tr_champ)), "elig_pct": margin_details[CHAMPION_NAME][lev_lbl]["elig_pct"],
                    "lev_pct": margin_details[CHAMPION_NAME][lev_lbl]["lev_pct"],
                    "avg_eff_lev": margin_details[CHAMPION_NAME][lev_lbl]["avg_eff_leverage"],
                    "min_mmr_pct": margin_details[CHAMPION_NAME][lev_lbl]["min_mmr_pct"],
                    "n_warn_150": margin_details[CHAMPION_NAME][lev_lbl]["n_warn_below_150"],
                    "n_liq_130": margin_details[CHAMPION_NAME][lev_lbl]["n_liq_below_130"],
                    "5Y_nav": w7["FULL_5Y"]["nav"], "5Y_mdd": w7["FULL_5Y"]["mdd_pct"], "5Y_dd2": w7["FULL_5Y"]["second_mdd_pct"],
                    "5Y_sh": w7["FULL_5Y"]["sharpe"], "5Y_cal": w7["FULL_5Y"]["calmar"],
                    "WF_nav": w7["WF_2326"]["nav"], "WF_mdd": w7["WF_2326"]["mdd_pct"], "WF_sh": w7["WF_2326"]["sharpe"],
                    "OOS_nav": w7["OOS_2426"]["nav"], "OOS_mdd": w7["OOS_2426"]["mdd_pct"],
                    "Y2526_nav": w7["Y2025_2026"]["nav"], "Y26_nav": w7["Y2026"]["nav"], "H2_nav": w7["Y2026_H2"]["nav"],
                    "mult_vs_cash_5y": round(w7["FULL_5Y"]["nav"] / w7_cash["FULL_5Y"]["nav"], 4),
                    "t_vs_cash_wf": p_vs_cash["paired_t"],
                })

    pd.DataFrame(margin_rows).to_csv(f"{OUT_DIR}/v22_margin_and_if_table.csv", index=False, encoding="utf-8-sig")

    master_audit = v22.sanitize_json({
        "task": "V22.0 Wave 2 Grand Assembly & Cold-Blooded Red-Team Final Verdict",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t0, 2),
        "d12_yfinance_imported": False,
        "sqlite_readonly_mode": True,
        "champion": {
            "id": CHAMPION_NAME,
            "formula": "V21.0 + P2_R_OPT(pos750<0.50 & pry_dt>=100) + P1A_DirA_Tight80(4to5_win & risk7>=1:7%->8%) + P1A_DirB_SJ114_7f_DtDefer@Pos5_EmptyFill",
            "rejected_building_blocks": {
                "XQLt6_on_4to5": "FAILS Redline (3) in portfolio: 3/4 standalone filters already occluded by V21; leaves ONLY 1 trade (2023-01-16 002238 天威视讯 -12.81%), 2024-2026 0 diff, mult_wf_ex_both=1.0000 (not >1.0), p=0.2363.",
                "Pos1_Pos2_on_4to5": "Crowds out P2_R_OPT rescued 2024-02-06 002644 佛慈制药 (+13.19%) to force in 000972 中基健康 (-16.00% under DtDefer). Pos5 dominates.",
                "Fix120_over_SJ114": "Strictly dominated by SJ114@Pos5 across 5Y (2.92B vs 4.39B), WF (17.87M vs 29.51M), 25-26 (14.4k vs 21.9k), 2026 (58.6x vs 81.5x), Sharpe (5.779 vs 5.832), identical MaxDD (28.80%/21.32%).",
            },
            "eval_030": evals[f"{CHAMPION_NAME}__030"],
            "eval_050": evals[f"{CHAMPION_NAME}__050"],
            "eval_080": evals[f"{CHAMPION_NAME}__080"],
            "diff_2526_vs_v21": df_diff_2526.to_dict("records"),
        },
        "standalone_4to5_e4_vs_dtdefer": s1["standalone_4to5"],
        "key_ablation_evals": {
            k: evals[f"{k}__030"] for k in ("B0_V20", "B1_V21", "V21_M1_P2", "V21_M2_DirA", "V21_M4_P2_DirA", "V21_M5_A_Pos2", "V21_M5_A_Pos5", CHAMPION_NAME, "V21_M5_B_Pos2", "V21_M5_B_Pos5", "V20_M4_P2_DirA", "V20_M5_A_Pos5", "V20_M5_B_NoXQ_Pos5", "V20_M5_B_Pos5")
        },
        "key_slippage_evals": {
            f"{k}__{fm}": evals[f"{k}__{fm}"] for k in ("B0_V20", "B1_V21", "V21_M4_P2_DirA", "V21_M5_A_Pos5", CHAMPION_NAME, "V21_M5_B_Pos5") for fm in ("050", "080")
        },
        "loo_and_dual_scissors": s1["loo_audit"],
        "champion_loo_audit": champ_loo,
        "truncation_proof_2024_12_31": s2_trunc,
        "margin_4tiers_audit": margin_details,
        "if_5x_standalone_18": if_standalone_18,
        "if_5x_comovement": comov_audit,
        "if_5x_parallel_accounting": if_combo_audit,
    })

    with open(f"{OUT_DIR}/v22_master_audit.json", "w", encoding="utf-8") as f:
        json.dump(master_audit, f, ensure_ascii=False, indent=2)

    print(f"\n[Step 3 DONE in {time.time()-t0:.1f}s | RSS={v22.rss_mb()} MB]")
    print("=== MARGIN & IF SUMMARY (CHAMPION) ===")
    df_m = pd.DataFrame(margin_rows)
    print(df_m[df_m["model"] == CHAMPION_NAME][["sleeve", "mode", "avg_eff_lev", "min_mmr_pct", "5Y_nav", "5Y_mdd", "5Y_dd2", "5Y_sh", "WF_nav", "WF_mdd", "Y2526_nav", "Y26_nav"]].to_string(index=False))


if __name__ == "__main__":
    main()

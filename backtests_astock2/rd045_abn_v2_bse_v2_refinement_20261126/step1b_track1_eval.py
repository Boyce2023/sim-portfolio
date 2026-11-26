#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD045 Step 1B: Evaluate Track 1 (V2_A/V2_B/V2_C), Theme Continuation Hypothesis, 2023 Bear Check & WF."""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"
import json, resource, sys, time
import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
BASE_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
RD045_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd045_abn_v2_bse_v2_refinement_20261126"
for p in (BASE_DIR, RD045_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import wf_scorecard_engine as wf
import _wf_sim_and_metrics as wfm
import _rd045_common as cm

END_DT = "2026-11-25"
T1_WINS = [
    ("FULL_5Y", "2021-01-04", END_DT),
    ("WF_2326", "2023-01-03", END_DT),
    ("Y2023", "2023-01-01", "2023-12-31"),
    ("Y2024", "2024-01-01", "2024-12-31"),
    ("Y2025_2026", "2025-01-01", END_DT),
    ("Y2026", "2026-01-01", END_DT),
]


def eval_track1_slice(sec: str, name: str, ex: str, df_sub: pd.DataFrame, cand_pool: pd.DataFrame, v20_ctx: dict,
                      score_col: str = "abn_sig_amt_yi", thresh=None, wf_only: bool = False, start_dt: str = "2021-01-04", perm_n: int = 200) -> dict:
    bench_df = v20_ctx["bench"]
    pass_df, slot_df = wfm.select_single_slot_trades(df_sub, score_col=score_col, threshold=thresh, tie_col="abn_sig_amt_yi", wf_only=wf_only)
    if slot_df.empty:
        return {}
    ev30 = cm.eval_slice_exact(slot_df, pass_df, cand_pool, bench_df, "mtm_json_use", 0.0030, start_dt, END_DT, T1_WINS, perm_n=perm_n)
    ev50 = cm.eval_slice_exact(slot_df.assign(net_ret=(1.0 + slot_df["gross_ret"]) * (1.0 - 0.0050) - 1.0), pass_df, cand_pool, bench_df, "mtm_json_use", 0.0050, start_dt, END_DT, T1_WINS[:3], perm_n=20)
    ev80 = cm.eval_slice_exact(slot_df.assign(net_ret=(1.0 + slot_df["gross_ret"]) * (1.0 - 0.0080) - 1.0), pass_df, cand_pool, bench_df, "mtm_json_use", 0.0080, start_dt, END_DT, T1_WINS[:3], perm_n=20)
    v20c = cm.compute_v20_corr_and_patch(pass_df, slot_df, v20_ctx, "mtm_json_use", 0.0030, "2023-01-03", "2026-11-16", score_col=score_col)

    main_w = "WF_2326" if wf_only else "FULL_5Y"
    mw = ev30["windows"].get(main_w, {})
    wf_w = ev30["windows"].get("WF_2326", {})
    y23 = ev30["windows"].get("Y2023", {})
    y25 = ev30["windows"].get("Y2025_2026", {})
    y26 = ev30["windows"].get("Y2026", {})
    m1 = v20c.get("patch_m1") or {}
    m2 = (v20c.get("patch_m2") or {}).get("windows", {}).get("FULL_WF", {})
    return {
        "section": sec, "track": name, "exit_rule": ex, "n_cands": int(len(pass_df)),
        "n_trades": mw.get("n", 0), "wr_pct": mw.get("wr_pct", 0.0), "plr": mw.get("plr", 0.0),
        "nav_30": mw.get("nav", 1.0), "ex5_30": mw.get("ex_top5_nav", 1.0), "eq_nav": mw.get("eq_nav", 1.0),
        "mdd_pct": mw.get("daily_mdd_pct", 0.0), "sharpe": mw.get("daily_sharpe", 0.0),
        "excess_csi_pp": mw.get("excess_csi300_pp", 0.0), "mtm_diff": ev30["mtm_reconciliation_diff"],
        "nav_50": ev50["windows"].get(main_w, {}).get("nav", 1.0),
        "ex5_50": ev50["windows"].get(main_w, {}).get("ex_top5_nav", 1.0),
        "nav_80": ev80["windows"].get(main_w, {}).get("nav", 1.0),
        "n_wf": wf_w.get("n", 0), "nav_wf": wf_w.get("nav", 1.0), "ex5_wf": wf_w.get("ex_top5_nav", 1.0),
        "n_2023": y23.get("n", 0), "nav_2023": y23.get("nav", 1.0),
        "n_2526": y25.get("n", 0), "nav_2526": y25.get("nav", 1.0), "ex5_2526": y25.get("ex_top5_nav", 1.0),
        "nav_y26": y26.get("nav", 1.0), "perm_any_p": ev30["permutation"].get("any_cand_day_p_nav", 1.0),
        "corr_v20": v20c.get("corr_all_days"), "v20_delta_ratio": m1.get("delta_nav_ratio_full_wf"),
        "v20_delta_sharpe": m1.get("delta_sharpe_full_wf"), "emp_nav": m2.get("nav"), "emp_ex5": m2.get("ex_top5_nav"),
    }


def main():
    t0 = time.time()
    df = pd.read_parquet(f"{RD045_DIR}/track1_abn_v2_events_pit.parquet")
    v20_ctx = wf.load_v20_reference_context(BASE_DIR)
    rows = []

    is_a = (df["entry_type"] == "V2_A").to_numpy()
    is_b = (df["entry_type"] == "V2_B").to_numpy()
    is_c = (df["entry_type"] == "V2_C").to_numpy()
    stk3 = (df["abn_max_streak_wave"] >= 3).to_numpy()
    stk4 = (df["abn_max_streak_wave"] >= 4).to_numpy()
    amt3 = (df["abn_sig_amt_yi"] >= 3.0).to_numpy()
    amt5 = (df["abn_sig_amt_yi"] >= 5.0).to_numpy()
    ma5 = (df["abn_above_ma5"] == 1).to_numpy()
    shrk = (df["abn_vol_shrink"] <= 0.85).to_numpy()
    no100 = (df["abn_was_hit_100"] == 0).to_numpy()
    op_m5p3 = df["abn_open_pct"].between(-5.0, 3.0).to_numpy()
    op_m3p5 = df["abn_open_pct"].between(-3.0, 5.0).to_numpy()
    op_m45p25 = df["abn_open_pct"].between(-4.5, 2.5).to_numpy()

    hot_main = ((df["thm_ind_zt_sig"] >= 2) | (df["thm_kp_cnt_sig"] >= 2)).to_numpy()
    sent_ok = (pd.to_numeric(df["L1_zt_cnt_t1"], errors="coerce").fillna(0) >= 35).to_numpy()
    thm_up = (df["thm_delta"] > 0).to_numpy()
    thm_hi = ((df["thm_ratio"] >= 0.80) & ((df["thm_kp_cnt_sig"] >= 3) | (df["thm_ind_zt3d_sig"] >= 5))).to_numpy()
    thm_fade = (df["thm_ratio"] < 0.50).to_numpy()
    thm_lone = ((df["thm_kp_cnt_sig"] <= 1) & (df["thm_ind_zt_sig"] <= 1)).to_numpy()
    rel_up = (df["thm_rel_delta"] > 0).to_numpy()

    hug94 = (df["abn_mg100_b"] <= 4.0).to_numpy() & df["abn_sig_dev10"].between(94.0, 99.98).to_numpy() & (df["abn_next_mg100_b"] >= 10.0).to_numpy()
    hug90 = (df["abn_mg100_b"] <= 5.0).to_numpy() & df["abn_sig_dev10"].between(90.0, 99.98).to_numpy() & (df["abn_next_mg100_b"] >= 10.0).to_numpy()
    hug80 = (df["abn_mg100_b"] <= 5.0).to_numpy() & df["abn_sig_dev10"].between(80.0, 99.98).to_numpy() & (df["abn_next_mg100_b"] >= 10.0).to_numpy()
    v2a_exact = is_a & (df["abn_mg100_prev"] <= 5.0).to_numpy() & (df["abn_mg100_b"] >= 10.0).to_numpy()

    specs = [
        ("V2_A", "V2_A_All_Stk3_Amt3", v2a_exact & stk3 & amt3),
        ("V2_A", "V2_A_MA5_OpenM5P3_Amt3", v2a_exact & stk3 & amt3 & ma5 & op_m5p3),
        ("V2_A", "V2_A_MA5_OpenM3P5_Amt3", v2a_exact & stk3 & amt3 & ma5 & op_m3p5),
        ("V2_A", "V2_A_Stk4_Amt5_MA5", v2a_exact & stk4 & amt5 & ma5 & op_m5p3),
        ("V2_A", "V2_A_Mainline_MA5_OpenM5P3", v2a_exact & stk3 & amt3 & ma5 & op_m5p3 & hot_main),
        ("V2_A", "V2_A_ThmUp_MA5_OpenM5P3", v2a_exact & stk3 & amt3 & ma5 & op_m5p3 & thm_up),
        ("V2_B", "V2_B_Hug94_Stk3_Amt3_MA5", is_b & hug94 & stk3 & amt3 & ma5),
        ("V2_B", "V2_B_Hug94_Amt5_MA5", is_b & hug94 & stk3 & amt5 & ma5),
        ("V2_B", "V2_B_Hug90_Stk3_Amt3_MA5", is_b & hug90 & stk3 & amt3 & ma5),
        ("V2_B", "V2_B_Hug80_Stk3_Amt3_MA5", is_b & hug80 & stk3 & amt3 & ma5),
        ("V2_B", "V2_B_Hug80_Mainline_MA5", is_b & hug80 & stk3 & amt3 & ma5 & hot_main),
        ("V2_B", "V2_B_Hug80_ThmUp_MA5", is_b & hug80 & stk3 & amt3 & ma5 & thm_up),
        ("V2_C", "V2_C_Base_NoHit100_LowOpen", is_c & no100 & op_m45p25),
        ("V2_C", "V2_C_Qual_Stk3_Amt3_MA5", is_c & no100 & op_m45p25 & stk3 & amt3 & ma5 & shrk),
        ("V2_C", "V2_C_Mainline_Sent_Amt3", is_c & no100 & op_m45p25 & stk3 & amt3 & ma5 & hot_main & sent_ok),
        ("V2_C", "V2_C_ThmUp_Qual_Amt3", is_c & no100 & op_m45p25 & stk3 & amt3 & ma5 & thm_up),
        # Buwen 4-Group Theme Continuation Experiment across V2_A+V2_C open quality pool & V2_B tail pool
        ("THEME_EXP", "OpenQual_G1_ThmUp", (v2a_exact | is_c) & stk3 & amt3 & ma5 & op_m5p3 & thm_up),
        ("THEME_EXP", "OpenQual_G2_ThmHighHold", (v2a_exact | is_c) & stk3 & amt3 & ma5 & op_m5p3 & thm_hi),
        ("THEME_EXP", "OpenQual_G3_ThmFade", (v2a_exact | is_c) & stk3 & amt3 & ma5 & op_m5p3 & thm_fade),
        ("THEME_EXP", "OpenQual_G4_LoneZhuang", (v2a_exact | is_c) & stk3 & amt3 & ma5 & op_m5p3 & thm_lone),
        ("THEME_EXP", "OpenQual_G1_RelThmUp", (v2a_exact | is_c) & stk3 & amt3 & ma5 & op_m5p3 & rel_up),
        ("THEME_EXP", "OpenAll_G1_ThmUp_NoMA5", (v2a_exact | is_c) & stk3 & amt3 & thm_up),
        ("THEME_EXP", "OpenAll_G3_ThmFade_NoMA5", (v2a_exact | is_c) & stk3 & amt3 & thm_fade),
        ("THEME_EXP", "OpenAll_G4_LoneZhuang_NoMA5", (v2a_exact | is_c) & stk3 & amt3 & thm_lone),
    ]
    for sec, nm, msk in specs:
        for ex in ("S1_hold1c", "S2_hold2c", "S5_ma5_trail", "S7_lianban"):
            v = cm.make_clean_view(df, ex, msk, 0.0030)
            cp = cm.make_clean_view(df, ex, (is_b if sec == "V2_B" else (is_a | is_c)), 0.0030)
            r = eval_track1_slice(sec, nm, ex, v, cp, v20_ctx, perm_n=200)
            if r:
                rows.append(r)

    # Low-DOF Expanding Walk-Forward (exit_date < t) + 2024-12-31 Truncation Proof
    low_dof_cols = [
        "abn_mg100_prev", "abn_mg100_b", "abn_unlock_jump", "abn_max_streak_wave", "abn_above_ma5",
        "abn_vol_shrink", "abn_sig_amt_yi", "abn_open_pct", "thm_score_sig", "thm_delta",
        "thm_ratio", "thm_rel_delta", "thm_kp_cnt_sig", "thm_ind_zt3d_sig", "L1_zt_cnt_t1",
    ]
    wf_specs = [
        ("WF_V2A_Amt3", v2a_exact & stk3 & amt3, "S1_hold1c"),
        ("WF_V2A_Amt3_S5", v2a_exact & stk3 & amt3, "S5_ma5_trail"),
        ("WF_V2A_Amt3_S7", v2a_exact & stk3 & amt3, "S7_lianban"),
        ("WF_V2B_Hug90_Amt3_S1", is_b & hug90 & stk3 & amt3, "S1_hold1c"),
        ("WF_V2B_Hug90_Amt3_S5", is_b & hug90 & stk3 & amt3, "S5_ma5_trail"),
        ("WF_V2C_No100_Low_S1", is_c & no100 & op_m45p25 & amt3, "S1_hold1c"),
        ("WF_V2C_No100_Low_S7", is_c & no100 & op_m45p25 & amt3, "S7_lianban"),
        ("WF_OpenPool_Amt3_S1", (v2a_exact | is_c) & stk3 & amt3, "S1_hold1c"),
        ("WF_OpenPool_Amt3_S7", (v2a_exact | is_c) & stk3 & amt3, "S7_lianban"),
    ]
    for tid, msk, ex in wf_specs:
        vw = cm.make_clean_view(df, ex, msk, 0.0030)
        if len(vw) < 40:
            continue
        f_use = [c for c in low_dof_cols if c in vw.columns]
        wf_res = wf.run_wf_scorecard_new_strategy(
            vw, feature_cols=f_use, v20_ctx=v20_ctx, wf_start_date="2023-01-03", end_date=END_DT,
            min_warmup_trades=30, min_warmup_trades_rare=20, min_warmup_months=15, recalc_freq="daily",
            top_k=6, min_k=3, max_corr=0.65, min_t_stat=0.8, shrink_tau=20.0, fee_rt=0.0030,
            gross_ret_col="gross_ret", thresholds=("top30", "top20", 70), eval_v20_patch=False, perm_n=30,
        )
        sc_df = wf_res["scored_df"]
        tr_chk = wf.verify_truncation_zero_leakage(
            vw, f_use, mode="A", cutoff="2024-12-31", score_threshold="top20", v20_ctx=v20_ctx,
            wf_start_date="2023-01-03", end_date=END_DT, min_warmup_trades=30, min_warmup_trades_rare=20,
            min_warmup_months=15, recalc_freq="daily", top_k=6, min_k=3, max_corr=0.65, min_t_stat=0.8,
            shrink_tau=20.0, fee_rt=0.0030, gross_ret_col="gross_ret",
        )
        for th in ("top30", "top20", "abs_70"):
            tcol = {"top30": "wf_thr_top30", "top20": "wf_thr_top20"}.get(th, 70.0)
            rwf = eval_track1_slice("T1_WF", f"{tid}_{th}", ex, sc_df, sc_df[sc_df["wf_in_window"]], v20_ctx,
                                    score_col="wf_score", thresh=tcol, wf_only=True, start_dt="2023-01-03", perm_n=200)
            if rwf:
                rwf["trunc_20241231_pass"] = tr_chk["zero_leakage_pass"]
                rows.append(rwf)

    res_df = pd.DataFrame(rows)
    res_df.to_csv(f"{RD045_DIR}/rd045_track1_abn_grid.csv", index=False, encoding="utf-8-sig")
    print(f"[Step1B DONE {time.time()-t0:.1f}s | RSS={round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1048576,1)}MB] rows={len(res_df)}")
    if not res_df.empty:
        cols = ["section", "track", "exit_rule", "n_trades", "wr_pct", "nav_30", "ex5_30", "nav_wf", "ex5_wf", "nav_2023", "nav_2526", "nav_50", "v20_delta_ratio"]
        print(res_df.sort_values("ex5_wf", ascending=False)[[c for c in cols if c in res_df.columns]].head(20).to_string(index=False))


if __name__ == "__main__":
    main()

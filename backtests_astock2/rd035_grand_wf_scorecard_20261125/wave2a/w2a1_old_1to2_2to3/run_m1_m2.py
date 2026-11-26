#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 2A-1 Runner Part 1: Baseline Parity + Module 1 (Internal Pruning & Dynamic Reweight)
+ Module 2 (Cross-Strategy Transplant xtr_37).
"""
import json
import os
import sys
import time

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import numpy as np
import pandas as pd

DIR = os.path.dirname(os.path.abspath(__file__))
if DIR not in sys.path:
    sys.path.insert(0, DIR)

import w2a1_data_and_eval as de
import w2a1_causal_models as cm
import wf_scorecard_engine as wf


def run_mode_a_grid(bundle: dict, strat: str, module: str, tag: str, feat_cols: list[str], recalc_freq: str = "daily", top_k: int = 12, thresholds=("top30", "top20", "top10", "top5", 70, 75, 80, 85)) -> list[dict]:
    df = bundle["p12"] if strat == "1to2" else bundle["p23"]
    res = wf.run_wf_scorecard_new_strategy(
        df, feat_cols, v20_ctx=bundle["v20_ctx"], wf_start_date=de.WF_START, end_date=de.WF_END,
        min_warmup_trades=80, recalc_freq=recalc_freq, top_k=top_k, max_corr=0.65,
        thresholds=thresholds, eval_v20_patch=False, perm_n=100,
    )
    rows = []
    for th in thresholds:
        tname = str(th) if not isinstance(th, (int, float)) else f"abs_{int(th)}"
        tr = res["threshold_results"][tname]
        rows.append(de.eval_variant_full(
            bundle, strat, module, f"{tag}__{tname}", tr["pass_df"], tr["slot_df"], perm_n=1000
        ))
    return rows


def main():
    t0 = time.time()
    bundle = de.load_all_bundle()
    p12, p23 = bundle["p12"], bundle["p23"]
    rows = []

    # --- 0. Exact Baselines (0.30% cost in WF) ---
    p12_pass_b, p12_slot_b = de.sim_1to2_custom(p12, p12["v20_score"].to_numpy(float))
    p23_pass_b, p23_slot_b = de.sim_2to3_custom(p23, p23["v20_score"].to_numpy(float), thr=90.0)
    assert len(p12_slot_b) == 92 and len(p23_slot_b) == 95
    rows.append(de.eval_variant_full(bundle, "1to2", "M0_Baseline", "V20_Baseline_30bps", p12_pass_b, p12_slot_b, perm_n=1000))
    rows.append(de.eval_variant_full(bundle, "2to3", "M0_Baseline", "V20_Baseline_30bps", p23_pass_b, p23_slot_b, perm_n=1000))
    # Also test higher S-tier baseline on 2to3 (>=96) and 1to2 (>=325)
    p23_ps, p23_ss = de.sim_2to3_custom(p23, p23["v20_score"].to_numpy(float), thr=96.0)
    rows.append(de.eval_variant_full(bundle, "2to3", "M0_Baseline", "V20_STier_ge96", p23_ps, p23_ss, perm_n=1000))

    # --- 1.1 Module 1: Leave-One-Out (1to2: 28 atoms; 2to3: 18 atoms) ---
    print("[M1.1] Running Leave-One-Out ablations...")
    s12_cols, s12_cmat = bundle["s12_atom_28"], bundle["s12_contrib"]
    orig_12 = p12["v20_score"].to_numpy(float)
    for j, col in enumerate(s12_cols):
        sc_loo = orig_12 - s12_cmat[:, j]
        ps, sl = de.sim_1to2_custom(p12, sc_loo)
        rows.append(de.eval_variant_full(bundle, "1to2", "M1_LOO", f"LOO_drop_{col}", ps, sl, perm_n=1000))

    s23_cols = bundle["s23_af_18"]
    s23_cmat = p23[s23_cols].fillna(0.0).to_numpy(float)
    orig_23 = p23["v20_score"].to_numpy(float)
    for j, col in enumerate(s23_cols):
        sc_loo = orig_23 - s23_cmat[:, j]
        ps, sl = de.sim_2to3_custom(p23, sc_loo, thr=90.0)
        rows.append(de.eval_variant_full(bundle, "2to3", "M1_LOO", f"LOO_drop_{col}", ps, sl, perm_n=1000))

    # --- 1.2 Module 1: Causal Auto-Prune (exit_date < t) ---
    print("[M1.2] Running Causal Auto-Prune...")
    ap_cfgs = [
        ("AutoPrune_Exp_t0", "exp", 80, 0.0, False),
        ("AutoPrune_Exp_tm05", "exp", 80, -0.5, False),
        ("AutoPrune_Roll80_t0", "roll", 80, 0.0, False),
        ("AutoPrune_Roll120_t0", "roll", 120, 0.0, False),
        ("AutoPrune_Exp_t0_Rec", "exp", 80, 0.0, True),
        ("AutoPrune_Roll80_t0_Rec", "roll", 80, 0.0, True),
    ]
    for vname, wm, rn, tc, rec in ap_cfgs:
        sc12 = cm.run_causal_autoprune(p12, s12_cmat, wf_start_date=de.WF_START, window_mode=wm, roll_n=rn, t_cut=tc, recenter=rec)
        ps12, sl12 = de.sim_1to2_custom(p12, sc12)
        rows.append(de.eval_variant_full(bundle, "1to2", "M1_AutoPrune", vname, ps12, sl12, perm_n=1000))

        sc23 = cm.run_causal_autoprune(p23, s23_cmat, wf_start_date=de.WF_START, window_mode=wm, roll_n=rn, t_cut=tc, recenter=rec)
        ps23, sl23 = de.sim_2to3_custom(p23, sc23, thr=90.0)
        rows.append(de.eval_variant_full(bundle, "2to3", "M1_AutoPrune", vname, ps23, sl23, perm_n=1000))

    # --- 1.3 Module 1: Causal Dynamic Reweight & Mode A Internal ---
    print("[M1.3] Running Dynamic Reweight & Mode A Internal...")
    for pb in (0.0, 0.5, 0.7):
        sc12_rw = cm.run_causal_reweight_v20(p12, s12_cmat, wf_start_date=de.WF_START, prior_blend=pb)
        ps12, sl12 = de.sim_1to2_custom(p12, sc12_rw)
        rows.append(de.eval_variant_full(bundle, "1to2", "M1_DynReweight", f"DynRewt_blend{int(pb*100)}", ps12, sl12, perm_n=1000))

        sc23_rw = cm.run_causal_reweight_v20(p23, s23_cmat, wf_start_date=de.WF_START, prior_blend=pb)
        ps23, sl23 = de.sim_2to3_custom(p23, sc23_rw, thr=90.0)
        rows.append(de.eval_variant_full(bundle, "2to3", "M1_DynReweight", f"DynRewt_blend{int(pb*100)}", ps23, sl23, perm_n=1000))

    rows.extend(run_mode_a_grid(bundle, "1to2", "M1_ModeA_Internal", "ModeA_Int28_daily", s12_cols, recalc_freq="daily", top_k=12))
    rows.extend(run_mode_a_grid(bundle, "1to2", "M1_ModeA_Internal", "ModeA_Int28_monthly", s12_cols, recalc_freq="monthly", top_k=12))
    rows.extend(run_mode_a_grid(bundle, "2to3", "M1_ModeA_Internal", "ModeA_Int18_daily", s23_cols, recalc_freq="daily", top_k=12))
    rows.extend(run_mode_a_grid(bundle, "2to3", "M1_ModeA_Internal", "ModeA_Int18_monthly", s23_cols, recalc_freq="monthly", top_k=12))

    # --- 2. Module 2: Cross-Strategy Transplant (xtr_37) ---
    print("[M2] Running Cross-Strategy Transplant (xtr_37)...")
    xtr_37 = bundle["xtr_37"]
    for md in (8, 15, 25):
        for freq in ("daily", "monthly"):
            if freq == "monthly" and md == 8:
                continue
            d12, c12_last = cm.score_mode_b_all_rows(p12, xtr_37, wf_start_date=de.WF_START, recalc_freq=freq, top_k=10, max_delta=md)
            ps12, sl12 = de.sim_1to2_custom(p12, orig_12 + d12)
            rows.append(de.eval_variant_full(bundle, "1to2", "M2_Transplant_ModeB", f"XTR37_ModeB_d{md}_{freq}", ps12, sl12, perm_n=1000))

            d23, c23_last = cm.score_mode_b_all_rows(p23, xtr_37, wf_start_date=de.WF_START, recalc_freq=freq, top_k=10, max_delta=md)
            ps23, sl23 = de.sim_2to3_custom(p23, orig_23 + d23, thr=90.0)
            rows.append(de.eval_variant_full(bundle, "2to3", "M2_Transplant_ModeB", f"XTR37_ModeB_d{md}_{freq}", ps23, sl23, perm_n=1000))
            if md == 15 and freq == "daily":
                ps23_h, sl23_h = de.sim_2to3_custom(p23, orig_23 + d23, thr=96.0)
                rows.append(de.eval_variant_full(bundle, "2to3", "M2_Transplant_ModeB", "XTR37_ModeB_d15_daily_thr96", ps23_h, sl23_h, perm_n=1000))

    rows.extend(run_mode_a_grid(bundle, "1to2", "M2_Transplant_ModeA", "ModeA_Int28_XTR37", s12_cols + xtr_37, recalc_freq="daily", top_k=12, thresholds=("top20", "top10", "top5", 75, 80)))
    rows.extend(run_mode_a_grid(bundle, "2to3", "M2_Transplant_ModeA", "ModeA_Int18_XTR37", s23_cols + xtr_37, recalc_freq="daily", top_k=12, thresholds=("top20", "top10", "top5", 75, 80)))

    df_res = pd.DataFrame(rows)
    df_res.to_csv(f"{de.OUT_DIR}/_part1_m1_m2.csv", index=False)
    print(f"[M1+M2 DONE in {time.time()-t0:.1f}s] {len(df_res)} variants saved.")


if __name__ == "__main__":
    main()

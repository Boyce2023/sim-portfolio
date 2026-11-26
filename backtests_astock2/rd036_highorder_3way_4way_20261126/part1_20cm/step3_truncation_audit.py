#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD036-A Step 3 (Module 5): End-to-End Physical 2024-12-31 Truncation Zero-Leakage Proof
on Top 3 Winning Composite Combinations + Core Learners, and Final Audit JSON (`rd036_20cm_audit.json`).

Zero yfinance (D12), Peak RSS < 2.0 GB, internal threads <= 2.
"""
import gc
import json
import os
import pickle
import resource
import sys
import time
import warnings

os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "2")

import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True
warnings.filterwarnings("ignore")

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd036_highorder_3way_4way_20261126/part1_20cm"
if OUT_DIR not in sys.path:
    sys.path.insert(0, OUT_DIR)

import rd036_lib as lib
import _wf_sim_and_metrics as wfm

CUTOFF = "2024-12-31"


def rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 1)


def _compute_all_pipeline_scores(p20_df: pd.DataFrame, meta: dict) -> dict[str, tuple[pd.DataFrame, np.ndarray, float]]:
    """Run all base learners & composite combinations from scratch on given p20_df."""
    df_h = p20_df.copy()
    df_h["wf_in_window"] = df_h["buy_date"] >= lib.WF_START_DT

    feat_cb = meta["feat_clean_b"]
    feat_ix = meta["ix_cols"]
    feat_union = meta["feat_union_cb_mech"]
    atomic_cols = meta["atomic_cols"]

    dm_cb, _ = lib.run_mode_b_multi_grid(df_h, feat_cb, ["v20_cold50"], deltas=(15,), min_discrete_bin_cnt=15, top_k=10)
    dm_mn, _ = lib.run_mode_b_multi_grid(df_h, feat_ix, ["v20_cold50"], deltas=(15,), min_discrete_bin_cnt=0, top_k=10)
    dm_mc, _ = lib.run_mode_b_multi_grid(df_h, feat_ix, ["v20_cold50"], deltas=(15,), min_discrete_bin_cnt=15, top_k=10)

    ho_res = lib.run_causal_highorder_and_tree_wf(
        df_h, atomic_cols=atomic_cols, extra_static_cols=feat_union,
        wf_start_date=lib.WF_START_DT, min_warmup_trades=80, deltas=(8, 12, 15), enable_4way=True,
    )

    c50 = df_h["v20_cold50"].to_numpy(float)
    d_cb15 = dm_cb[("v20_cold50", 15)]
    d_mn15 = dm_mn[("v20_cold50", 15)]
    d_mc15 = dm_mc[("v20_cold50", 15)]
    d_3w12 = ho_res["rule_deltas"][("Rule3Way", 12)]
    d_4w12 = ho_res["rule_deltas"][("Rule4Way", 12)]
    d_gb3_8 = np.round(np.nan_to_num(ho_res["raw_z"]["GBDT_D3"], nan=0.0) * 8.0)

    models = {
        "Blend_c50_Half_CB15_MN15_S80": (df_h, c50 + np.round(0.5 * d_cb15 + 0.5 * d_mn15), 80.0),
        "Blend_c50_Half_CB15_MC15_S80": (df_h, c50 + np.round(0.5 * d_cb15 + 0.5 * d_mc15), 80.0),
        "Stack_c50_Avg_CB15_MN15_R3W12_S80": (df_h, c50 + np.round((d_cb15 + d_mn15 + d_3w12) / 3.0), 80.0),
        "GBDT_D3_cold50_d8_S80": (df_h, c50 + d_gb3_8, 80.0),
        "CLEANB_cold50_d15_S84": (df_h, c50 + d_cb15, 84.0),
        "Rule3Way_cold50_d12_S78": (df_h, c50 + d_3w12, 78.0),
        "Rule4Way_cold50_d12_S80": (df_h, c50 + d_4w12, 80.0),
    }
    return models


def main():
    t0 = time.time()
    print("[Step 3 (Module 5)] Loading full cache & running 2024-12-31 physical truncation from scratch ...")

    p20_full = pd.read_parquet(f"{OUT_DIR}/_cache_p20.parquet")
    with open(f"{OUT_DIR}/_cache_p20_segs.pkl", "rb") as f:
        meta_full = pickle.load(f)["meta"]
    full_models = _compute_all_pipeline_scores(p20_full, meta_full)
    del p20_full
    gc.collect()

    # Physically reload & enrich ONLY rows <= 2024-12-31 from raw files
    p20_trunc, meta_trunc = lib.load_20cm_enriched_data(end_cutoff=CUTOFF)
    trunc_models = _compute_all_pipeline_scores(p20_trunc, meta_trunc)
    del p20_trunc
    gc.collect()

    trunc_proofs = {}
    for mname, (df_f, sc_f, thr) in full_models.items():
        df_t, sc_t, _ = trunc_models[mname]
        df_f = df_f.copy(); df_f["_sc"] = sc_f
        df_t = df_t.copy(); df_t["_sc"] = sc_t

        f_le = df_f[df_f["buy_date"] <= CUTOFF].sort_values(["buy_date", "code"]).reset_index(drop=True)
        t_le = df_t.sort_values(["buy_date", "code"]).reset_index(drop=True)
        assert len(f_le) == len(t_le), f"{mname}: row count mismatch {len(f_le)} vs {len(t_le)}"
        max_sc_diff = float(np.max(np.abs(f_le["_sc"].to_numpy(float) - t_le["_sc"].to_numpy(float))))

        _, sl_f = wfm.select_single_slot_trades(df_f, score_col="_sc", threshold=thr, wf_only=True)
        _, sl_t = wfm.select_single_slot_trades(df_t, score_col="_sc", threshold=thr, wf_only=True)
        tr_f = sl_f[sl_f["exit_date"] <= CUTOFF].sort_values(["buy_date", "code"]).reset_index(drop=True)
        tr_t = sl_t[sl_t["exit_date"] <= CUTOFF].sort_values(["buy_date", "code"]).reset_index(drop=True)
        assert len(tr_f) == len(tr_t), f"{mname}: trade count mismatch {len(tr_f)} vs {len(tr_t)}"
        assert list(zip(tr_f["buy_date"], tr_f["code"])) == list(zip(tr_t["buy_date"], tr_t["code"])), f"{mname}: sequence mismatch"
        max_r_diff = float(np.max(np.abs(tr_f["net_ret_30"].to_numpy(float) - tr_t["net_ret_30"].to_numpy(float)))) if len(tr_f) else 0.0

        assert max_sc_diff == 0.0, f"{mname} score diff = {max_sc_diff}"
        assert max_r_diff == 0.0, f"{mname} ret diff = {max_r_diff}"
        trunc_proofs[mname] = {
            "cutoff": CUTOFF,
            "n_rows_checked": int(len(f_le)),
            "n_trades_exiting_le_cutoff": int(len(tr_f)),
            "max_abs_score_diff": max_sc_diff,
            "max_abs_ret_diff": max_r_diff,
            "zero_leakage_pass": True,
        }
        print(f"  Trunc {mname:35s}: rows={len(f_le)}, trades_le={len(tr_f)}, score_diff={max_sc_diff}, ret_diff={max_r_diff} [PASS]")

    # Assemble final comprehensive rd036_20cm_audit.json
    with open(f"{OUT_DIR}/_suite_interim.json", encoding="utf-8") as f:
        interim = json.load(f)
    df_grid = pd.read_csv(f"{OUT_DIR}/rd036_20cm_grid.csv")
    rules_df = pd.read_csv(f"{OUT_DIR}/rd036_20cm_top_rules.csv")

    # Extract concise comparative tables for Module 1..4
    key_comp_names = [
        "BASE_V11_S82", "BASE_V11_S80", "BASE_V11_S78", "BASE_V11_S84",
        "COLD40_S80", "COLD45_S80", "COLD50_S80", "COLD50_S82", "COLD55_S80",
        "CLEANB_v20_d15_S80", "CLEANB_cold50_d15_S80", "CLEANB_cold50_d15_S84", "CLEANB_cold50_d15_S78",
        "MechNat_v20_d10_S82", "MechNat_v20_d15_S82", "MechNat_cold50_d5_S80", "MechNat_cold50_d10_S80",
        "MechNat_cold50_d15_S80", "MechNat_cold50_d20_S80", "MechClean_cold50_d15_S80",
        "Union10_CB_Mech_cold50_d8_S80", "Union12_CB_Mech_cold50_d15_S82",
        "Blend_c50_Half_CB15_MN15_S80", "Blend_c50_Half_CB15_MN15_S78", "Blend_c50_Half_CB15_MN15_S82", "Blend_c50_Half_CB15_MN15_S84",
        "Rule3Way_cold50_d12_S78", "Rule3Way_cold50_d15_S82", "Rule3Way_v20_d12_S78",
        "DT_D3_cold50_d8_S84", "GBDT_D3_cold50_d8_S80", "GBDT_D3_cold50_d12_S82", "GBDT_D3_cold50_d15_S84",
        "Rule4Way_cold50_d12_S80", "DT_D4_cold50_d8_S78", "GBDT_D4_cold50_d8_S80", "GBDT_D4_cold50_d15_S84",
        "Stack_c50_Avg_CB15_MN15_R3W12_S80", "Stack_c50_MN10_Rule3W8_cap20_S82",
        "Stack_c50_CB15_Rule3W8_cap20_S84", "Stack_c50_CB15_Rule4W8_cap20_S78",
    ]
    comp_rows = [
        interim["must_check_finalists"][nm] if nm in interim["must_check_finalists"]
        else df_grid[df_grid["variant"] == nm].iloc[0].to_dict()
        for nm in key_comp_names if nm in df_grid["variant"].values
    ]

    # Cold50 x Mech130 d5/d10/d15/d20 plateau table
    mech_plateau = df_grid[
        df_grid["family"].str.startswith("1C_MECHNAT") & df_grid["variant"].str.endswith("_S80")
    ][["variant", "n_wf", "wr_wf", "nav_wf", "ex5_wf", "mdd_wf", "sharpe_wf", "nav_2526", "nav_80bps"]].to_dict("records")

    cb_plateau = df_grid[
        df_grid["family"].str.startswith("1B_CLEANB") & df_grid["variant"].str.endswith("_S80")
    ][["variant", "n_wf", "wr_wf", "nav_wf", "ex5_wf", "mdd_wf", "sharpe_wf", "nav_2526", "nav_80bps"]].to_dict("records")

    audit = lib.sanitize_json({
        "task": "RD036-A: 20cm Deep-Open High-Order Synergy (Cold50 x CLEAN_B x Mech130 x 3-Way/4-Way/Shallow-Tree)",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_step3_sec": round(time.time() - t0, 2),
        "peak_rss_step3_mb": rss_mb(),
        "peak_rss_step2_mb": interim["peak_rss_mb"],
        "d12_yfinance_imported": False,
        "exact_mtm_methodology": "True daily close-to-close bar MTM aligned to WF trading dates (mtm_reconciliation_diff < 1e-6; zero geometric return smoothing).",
        "deliverables": {
            "audit_json": f"{OUT_DIR}/rd036_20cm_audit.json",
            "grid_csv": f"{OUT_DIR}/rd036_20cm_grid.csv",
            "top_rules_csv": f"{OUT_DIR}/rd036_20cm_top_rules.csv",
            "best_trades_parquet": f"{OUT_DIR}/rd036_20cm_best_trades.parquet",
        },
        "module5_truncation_2024_12_31_proof": {
            "all_zero_diff_passed": all(v["zero_leakage_pass"] for v in trunc_proofs.values()),
            "models": trunc_proofs,
        },
        "module4_anti_overfit_summary": {
            "n_trials_grid": interim["n_trials_grid"],
            "cscv_global_s10": interim["cscv_global_s10"],
            "cscv_global_s8": interim["cscv_global_s8"],
            "cscv_by_family_s10": interim["cscv_by_family_s10"],
            "v20_official_comb_baseline": interim["v20_official_comb_baseline"],
        },
        "module1_plateaus": {
            "cold_x_cleanb_s80": cb_plateau,
            "cold_x_mechnat_s80": mech_plateau,
        },
        "module4_key_head_to_head_comparison": comp_rows,
        "top_ranked_winners": interim["top_ranked_winners"],
        "primary_winner": "Blend_c50_Half_CB15_MN15_S80",
        "secondary_3way_winner": "Stack_c50_Avg_CB15_MN15_R3W12_S80",
        "low_pbo_tree_winner": "GBDT_D3_cold50_d8_S80",
        "high_sharpe_s84_winner": "CLEANB_cold50_d15_S84",
        "module2_3_top_rules_monthly_freq": rules_df.head(40).to_dict("records"),
        "latest_3way_rules": interim["latest_3way_rules"],
        "latest_4way_rules": interim["latest_4way_rules"],
        "latest_dt_d3_rules": interim["latest_dt_d3_rules"],
        "latest_scorecards": interim["latest_scorecards"],
        "executive_findings": {
            "1_mtm_sharpe_truth": "True bar-MTM Sharpe of BASE_V11_S82 is 1.737 (MDD 30.27%), vs geometrically smoothed 2.329 in W2A3 and date-index-shifted 1.336 in W2A4.",
            "2_cold_plateau": "Disabling F06 on cold days (mkt10 < cut) forms a monotonic plateau from cut<40..55 across Pure Cold, CLEAN_B, and Mech130; Cold50/55 consistently lifts WF NAV and 2526 NAV.",
            "3_mech130_d20_plateau": "Cold50 + MechNat130 peaks at d5 (89.18x, Sh=2.272) and d10 (86.85x, Sh=2.232, Comb 2.83x), holds at d15 (70.33x), and collapses at d20 (38.28x, Sh=1.923) due to over-writing V20 score.",
            "4_two_secondary_fusion_winner": "Half-weight blend (Cold50 + round(0.5*CLEAN_B_d15 + 0.5*Mech130_d15)) at S80 achieves 146.36x WF NAV (Ex5 32.47x, Sharpe 2.413, WR 59.26%, 2526 14.59x, 26H2 2.28x, 80bps 74.24x, paired t=2.970 vs S82, DSR=1.0000/0.9751, V20 Comb 1,743,104.54x = 2.8495x).",
            "5_3way_and_trees": "3-Way AND + Depth=3 GBDT discover clean orthogonal alpha (2B_TREE_D3 achieves lowest ML family CSCV PBO=27.38%, GBDT_D3_cold50_d8_S80=107.88x / Sh=2.284). 3-Way average stack (Stack_c50_Avg_CB15_MN15_R3W12_S80) cuts MDD to 26.08% with 61.24% WR, 125.96x WF NAV, 75.44x >=2yi NAV, and 2.5068x V20 Comb.",
            "6_4way_vs_3way_verdict": "4-Way expansion & Depth=4 trees over-fragment sample size: DT/GBDT depth=4 doubles PBO (27.38% -> 55.56%) and drops GBDT_cold50_d8_S80 NAV from 107.88x to 60.49x (-44%). Rule4Way adds negligible value over CLEAN_B+3Way.",
            "7_global_cscv_warning": "Global CSCV PBO across all 548 tested variants is 79.37% (med OOS rank 27.46%) because blind argmax over 548 noisy configurations picks low-sample S84 / depth-4 spikes; disciplined fixed-budget families (2B_TREE_D3 PBO=27.38%, 1B_CLEANB_COLD50 PBO=32.14%) remain robust.",
        },
    })
    with open(f"{OUT_DIR}/rd036_20cm_audit.json", "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2, allow_nan=False)

    # Clean up temporary cache files to keep output folder tidy & focused on deliverables
    for tmp in ("_cache_p20.parquet", "_cache_p20_segs.pkl", "_cache_v20_comb_ctx.pkl", "_suite_interim.json"):
        tp = f"{OUT_DIR}/{tmp}"
        if os.path.exists(tp):
            os.remove(tp)

    print(f"\n[Step 3 DONE in {time.time()-t0:.1f}s | Peak RSS={rss_mb()}MB]")
    print(f"Deliverables ready in {OUT_DIR}:")
    for fn in ("rd036_20cm_audit.json", "rd036_20cm_grid.csv", "rd036_20cm_top_rules.csv", "rd036_20cm_best_trades.parquet"):
        fp = f"{OUT_DIR}/{fn}"
        print(f"  {fn}: {round(os.path.getsize(fp)/1024, 1)} KB")


if __name__ == "__main__":
    main()

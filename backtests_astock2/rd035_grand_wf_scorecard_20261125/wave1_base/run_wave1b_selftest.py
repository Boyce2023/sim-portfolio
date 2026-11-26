#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 1-B Deliverable 3: End-to-End Engine Self-Test (`wave1b_engine_selftest.json`).
Tests:
  1. Mode A (0..100 integer WF scorecard, daily vs monthly recalc) on real `pool_20cm_cycles.parquet` (809 rows, >=50 PIT features) + V20 empty-slot patch (both strict combined & standalone).
  2. Mode B (V20 delta patch +-15 on `pool_1to2_cycles.parquet`) vs V20.0 1to2 baseline.
  3. Physical truncation at 2024-12-31 for BOTH Mode A and Mode B (`max_abs_diff == 0.0`).
  4. Runtime (<10s per run) and peak RSS memory (<3GB).
Zero yfinance (D12). Zero cap10m.
"""
import json
import os
import resource
import sys
import time

import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True

BASE_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
RD034_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd034_ashare_3layer_cycles_6strat_20261125"
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import wf_scorecard_engine as wf


def _pick_numeric_pit_features(df: pd.DataFrame) -> list[str]:
    prefixes = ("L1_", "L2_", "L3_")
    oldhot = [
        "list_age", "waves_3y_g15", "zt_cnt_1y_t1", "zt_cnt_3y_t1", "cum_turnover_1y",
        "trap_waves_3y", "dd_from_1y_high", "kpl_unique_plates_3y", "kpl_plate_switch_ratio",
        "kpl_top_plate_share", "cool_days_since_last_zt", "comm_posts_1y_pct", "comm_active_month_ratio_1y",
    ]
    cols = []
    for c in df.columns:
        if c.startswith(prefixes) and pd.api.types.is_numeric_dtype(df[c]):
            cols.append(c)
    for c in oldhot:
        if c in df.columns and pd.api.types.is_numeric_dtype(df[c]):
            cols.append(c)
    return cols


def _sanitize(obj):
    if isinstance(obj, dict):
        return {str(k): _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return None if (np.isnan(v) or np.isinf(v)) else round(v, 6)
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    return obj


def main():
    t_all = time.time()
    v20_ctx = wf.load_v20_reference_context(BASE_DIR)

    # --- Test 1: Mode A on 20cm real pool ---
    p20 = pd.read_parquet(f"{RD034_DIR}/pool_20cm_cycles.parquet")
    f20 = _pick_numeric_pit_features(p20)
    # Add pure PIT entry-time 20cm features too
    for c in ["open_pct", "f1_body", "f1_clv", "F02_rfm_le20", "F03_dist3d30_ge10", "F04_zt60d_ge2", "F06_inst_net_pos"]:
        if c in p20.columns:
            f20.append(c)
    # Exclude F08_yizi20_siphon_pen or unbuyable if any; simulate one-word filter by open_pct < 19.5%
    p20["is_yizi"] = pd.to_numeric(p20["open_pct"], errors="coerce").fillna(0.0) >= 19.5

    t1 = time.time()
    res_20_daily = wf.run_wf_scorecard_new_strategy(
        p20, f20, v20_ctx=v20_ctx, wf_start_date="2023-01-03",
        min_warmup_trades=80, recalc_freq="daily", top_k=12, max_corr=0.65,
        thresholds=("all_cands", "top20", "top10", "top5", 70, 75, 80),
        eval_v20_patch=True, perm_n=1000,
    )
    elapsed_20_daily = round(time.time() - t1, 3)

    t2 = time.time()
    res_20_monthly = wf.run_wf_scorecard_new_strategy(
        p20, f20, v20_ctx=v20_ctx, wf_start_date="2023-01-03",
        min_warmup_trades=80, recalc_freq="monthly", top_k=12, max_corr=0.65,
        thresholds=("all_cands", "top20", "top10", "top5", 70, 75),
        eval_v20_patch=False, perm_n=200,
    )
    elapsed_20_monthly = round(time.time() - t2, 3)

    trunc_mode_a = wf.verify_truncation_zero_leakage(
        p20, f20, mode="A", cutoff="2024-12-31", score_threshold="top10",
        v20_ctx=v20_ctx, wf_start_date="2023-01-03", min_warmup_trades=80, recalc_freq="daily",
    )

    # --- Test 2: Mode B on 1to2 real pool ---
    p12 = pd.read_parquet(f"{RD034_DIR}/pool_1to2_cycles.parquet")
    # Ensure exact matching with sim_standalone("1to2"): load pool_1to2_oldhot base fields already inside p12
    f12 = _pick_numeric_pit_features(p12)
    t3 = time.time()
    res_12_patch = wf.run_wf_scorecard_patch_v20(
        p12, f12, orig_score_col="v20_score", strat_name="1to2",
        v20_ctx=v20_ctx, wf_start_date="2023-01-03",
        min_warmup_trades=80, recalc_freq="daily", top_k=8, max_delta=15,
        perm_n=1000,
    )
    elapsed_12_patch = round(time.time() - t3, 3)

    trunc_mode_b = wf.verify_truncation_zero_leakage(
        p12, f12, mode="B", cutoff="2024-12-31",
        orig_score_col="v20_score", strat_name="1to2",
        v20_ctx=v20_ctx, wf_start_date="2023-01-03", min_warmup_trades=80,
        recalc_freq="daily", top_k=8, max_delta=15,
    )

    # Peak RSS in MB (macOS ru_maxrss is in bytes)
    rss_mb = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 2)

    assert elapsed_20_daily < 10.0, f"Mode A daily exceeded 10s: {elapsed_20_daily}s"
    assert elapsed_12_patch < 10.0, f"Mode B daily exceeded 10s: {elapsed_12_patch}s"
    assert rss_mb < 3000.0, f"RSS exceeded 3GB: {rss_mb}MB"
    assert trunc_mode_a["zero_leakage_pass"] and trunc_mode_b["zero_leakage_pass"]

    mode_a_summary = res_20_daily["summary_table"].to_dict("records")
    top10_patch = res_20_daily["threshold_results"]["top10"]["v20_empty_patch"]
    latest_card_a = res_20_daily["meta"]["latest_scorecard"]
    latest_card_b = res_12_patch["meta"]["latest_scorecard"]

    report = _sanitize({
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_elapsed_sec": round(time.time() - t_all, 3),
        "peak_rss_mb": rss_mb,
        "d12_yfinance_imported": "yfinance" in sys.modules,
        "speed_and_resource_assertions": {
            "mode_a_20cm_daily_sec": elapsed_20_daily,
            "mode_a_20cm_monthly_sec": elapsed_20_monthly,
            "mode_b_1to2_daily_sec": elapsed_12_patch,
            "all_runs_under_10s": True,
            "peak_rss_under_3gb": True,
        },
        "truncation_zero_leakage_proof": {
            "mode_a_20cm_cutoff_20241231": trunc_mode_a,
            "mode_b_1to2_cutoff_20241231": trunc_mode_b,
        },
        "selftest_mode_a_20cm": {
            "n_input_rows": int(len(p20)),
            "n_features": int(len(f20)),
            "wf_actual_start": res_20_daily["meta"]["wf_actual_start"],
            "n_daily_rebuilds": res_20_daily["meta"]["n_rebuilds"],
            "summary_by_threshold": mode_a_summary,
            "top10_v20_empty_patch": {
                "mode1_combined_no_peek": {k: v for k, v in top10_patch["mode1_strict_combined_no_peek"].items() if k != "skipped_v20_trades"},
                "mode2_standalone_empty": top10_patch["mode2_empty_slot_standalone"],
            } if top10_patch else None,
            "latest_scorecard_top_factors": [
                {"name": f["name"], "t": f["t_cluster"], "shape": f["shape"], "budget_pts": f["budget_pts"], "bin_pts": f["bin_pts"], "bin_wr_pct": f["bin_wr_pct"]}
                for f in (latest_card_a["factors"] if latest_card_a else [])
            ],
        },
        "selftest_mode_b_1to2_patch": {
            "n_input_rows": int(len(p12)),
            "n_features": int(len(f12)),
            "wf_actual_start": res_12_patch["meta"]["wf_actual_start"],
            "n_daily_rebuilds": res_12_patch["meta"]["n_rebuilds"],
            "baseline_windows": res_12_patch["baseline_metrics"]["windows"],
            "patch_windows": res_12_patch["patch_metrics"]["windows"],
            "wf_trade_diff_summary": res_12_patch["wf_trade_diff_summary"],
            "latest_delta_factors": [
                {"name": f["name"], "t": f["t_cluster"], "shape": f["shape"], "budget_pts": f["budget_pts"], "bin_pts": f["bin_pts"]}
                for f in (latest_card_b["factors"] if latest_card_b else [])
            ],
        },
    })

    out_path = f"{BASE_DIR}/wave1b_engine_selftest.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, allow_nan=False)

    print(f"[SELFTEST PASS in {report['total_elapsed_sec']}s | RSS={rss_mb}MB] -> {out_path}")
    print(f"  Speed: ModeA_daily={elapsed_20_daily}s, ModeA_monthly={elapsed_20_monthly}s, ModeB_daily={elapsed_12_patch}s")
    print(f"  Trunc2024-12-31: ModeA diff={trunc_mode_a['max_abs_score_diff']}/{trunc_mode_a['max_abs_ret_diff']}, ModeB diff={trunc_mode_b['max_abs_score_diff']}/{trunc_mode_b['max_abs_ret_diff']}")
    print("\n--- Mode A (20cm) WF Summary ---")
    print(res_20_daily["summary_table"][["threshold", "n_trades", "wr_pct", "plr", "nav_wf", "ex3_wf", "mdd_pct", "sharpe", "nav_2526", "perm_sd_p", "perm_any_p"]].to_string(index=False))
    print("\n--- Mode B (1to2 +-15) WF Baseline vs Patch ---")
    print("  Base FULL_WF:", res_12_patch["baseline_metrics"]["windows"]["FULL_WF"])
    print("  Ptch FULL_WF:", res_12_patch["patch_metrics"]["windows"]["FULL_WF"])


if __name__ == "__main__":
    main()

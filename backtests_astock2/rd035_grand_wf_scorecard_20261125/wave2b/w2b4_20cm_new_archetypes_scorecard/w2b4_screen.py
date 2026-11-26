#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 2B-4 Screen: Build union 20cm candidate pool (<1.8 GB RSS) & screen all 5 tracks
(Track A/B/C/D/E + exit trees h1/h2/v11 + sub-cohorts) with 0..100 causal WF scorecard.
"""
import os

for _env in (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
):
    os.environ[_env] = "1"

import gc
import json
import sys
import time

import numpy as np
import pandas as pd
import pyarrow as pa

pa.set_cpu_count(1)
pa.set_io_thread_count(1)
sys.dont_write_bytecode = True

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave2b/w2b4_20cm_new_archetypes_scorecard"
if OUT_DIR not in sys.path:
    sys.path.insert(0, OUT_DIR)

import w2b4_lib as lib


def define_track_specs(df: pd.DataFrame) -> list[tuple[str, str, np.ndarray, str]]:
    """Return list of (track_id, track_group, boolean_mask, exit_mode)."""
    ta = df["track_A"].to_numpy(bool)
    tb = df["track_B"].to_numpy(bool)
    tbs2 = df["track_B_s2"].to_numpy(bool)
    tc = df["track_C"].to_numpy(bool)
    td = df["track_D"].to_numpy(bool)
    te = df["track_E"].to_numpy(bool)

    op = df["open_pct"].to_numpy(float)
    is_23 = df["eng_is_2to3"].to_numpy(float) == 1.0
    pb_d = df["eng_pb_days"].to_numpy(float)
    kpl_rk = df["kpl_rank_t1"].to_numpy(float)
    kpl_zt1 = df["kpl_zt1_t1"].to_numpy(float)
    csrc_rk = df["csrc_ind_rank20_t1"].to_numpy(float)

    strong_thm = ((kpl_rk >= 1) & (kpl_rk <= 3)) | (kpl_zt1 >= 5) | (csrc_rk <= 5)

    specs = [
        # Track A: 20cm 连板接力 (1进2 & 2进3 非一字开盘) -> 测 h1, h2, v11 + sub-cohorts
        ("A1_12_23_h1", "Track_A_Relay", ta, "h1"),
        ("A2_12_23_h2", "Track_A_Relay", ta, "h2"),
        ("A3_12_23_v11", "Track_A_Relay", ta, "v11"),
        ("A4_1to2_hiopen_v11", "Track_A_Relay", ta & (~is_23) & (op >= 2.0), "v11"),
        ("A5_2to3_only_h1", "Track_A_Relay", ta & is_23, "h1"),
        ("A6_2to3_only_v11", "Track_A_Relay", ta & is_23, "v11"),

        # Track B: 20cm 高标首阴反包
        ("B1_all_v11", "Track_B_HighYin", tb, "v11"),
        ("B2_all_h1", "Track_B_HighYin", tb, "h1"),
        ("B3_all_h2", "Track_B_HighYin", tb, "h2"),
        ("B4_streak2_v11", "Track_B_HighYin", tbs2, "v11"),

        # Track C: 20cm 首板/连板断板后 1~3日缩量回踩反包
        ("C1_turn_pos_v11", "Track_C_Pullback", tc & (op >= 0.0), "v11"),
        ("C2_turn_pos_h1", "Track_C_Pullback", tc & (op >= 0.0), "h1"),
        ("C3_mild_all_v11", "Track_C_Pullback", tc, "v11"),
        ("C4_pb1d_only_v11", "Track_C_Pullback", tc & (pb_d == 1.0), "v11"),

        # Track D: 20cm 冲板炸板次日深水低吸
        ("D1_s82zone_v11", "Track_D_ZhabanDeep", td & (op >= -10.0) & (op <= -3.0), "v11"),
        ("D2_s82zone_h1", "Track_D_ZhabanDeep", td & (op >= -10.0) & (op <= -3.0), "h1"),
        ("D3_wide_v11", "Track_D_ZhabanDeep", td, "v11"),

        # Track E: 20cm 强主线首板次日非深水买点 (-1% ~ +8%)
        ("E1_mild_all_v11", "Track_E_ThemeMild", te, "v11"),
        ("E2_strong_thm_v11", "Track_E_ThemeMild", te & strong_thm, "v11"),
        ("E3_mild_all_h1", "Track_E_ThemeMild", te, "h1"),
        ("E4_sweet0_6_v11", "Track_E_ThemeMild", te & (op >= 0.0) & (op <= 6.0), "v11"),
    ]
    return specs


def main():
    t0 = time.time()
    os.makedirs(OUT_DIR, exist_ok=True)
    cache_pq = f"{OUT_DIR}/_cache_w2b4_master.parquet"
    cache_meta = f"{OUT_DIR}/_cache_w2b4_meta.json"
    if os.path.exists(cache_pq) and os.path.exists(cache_meta):
        master_df = pd.read_parquet(cache_pq)
        with open(cache_meta, encoding="utf-8") as f:
            mc = json.load(f)
        all_fcols, build_meta = mc["all_fcols"], mc["build_meta"]
        print(f"[CACHE LOAD] n_union={len(master_df)} | RSS={lib.get_rss_mb()} MB")
    else:
        master_df, all_fcols, build_meta = lib.build_w2b4_candidate_pool("2026-11-16")
        master_df.to_parquet(cache_pq, index=False)
        with open(cache_meta, "w", encoding="utf-8") as f:
            json.dump({"all_fcols": all_fcols, "build_meta": build_meta}, f, ensure_ascii=False, indent=2)
        print(f"[BUILD] n_union={build_meta['n_union_cands']} | counts={build_meta['track_counts']} | RSS={build_meta['peak_rss_mb']} MB")

    v20_ctx = lib.wf.load_v20_reference_context(lib.WAVE1_BASE)

    specs = define_track_specs(master_df)
    all_rows = []
    all_meta = {}
    for tid, tgrp, mask, ex_mode in specs:
        sub_df, vf_cols = lib.prepare_track_df(master_df, mask, exit_mode=ex_mode, end_dt="2026-11-16", all_feat_cols=all_fcols)
        rows, det, _ = lib.evaluate_track_full(
            tid, tgrp, sub_df, vf_cols, v20_ctx,
            wf_start_date="2023-01-03", end_dt="2026-11-16",
            thresholds=("all_cands", "top30", "top20", "top10", "top5", 70, 75, 80, 85),
            perm_n=200, recalc_freq="monthly",
        )
        all_rows.extend(rows)
        all_meta[tid] = det["meta"]
        df_r = pd.DataFrame(rows)
        best_r = df_r[df_r["threshold"] != "all_cands"].sort_values("nav_wf", ascending=False).iloc[0]
        best_patch = df_r[df_r["threshold"] != "all_cands"].sort_values("patch_delta_nav_ratio", ascending=False).iloc[0]
        print(
            f"[{tid:20s}] N={len(sub_df):4d} | BEST_NAV({best_r['threshold']:6s}): "
            f"n={int(best_r['n_trades']):3d} wr={best_r['wr_pct']:5.1f}% plr={best_r['plr']:4.2f} "
            f"nav={best_r['nav_wf']:6.2f}x ex5={best_r['ex5_wf']:5.2f}x mdd={best_r['mdd_pct']:5.1f}% "
            f"2526={best_r['nav_2526']:5.2f}x 26={best_r['nav_y26']:4.2f}x 26H2={best_r['nav_26h2']:4.2f}x "
            f"corr={best_r['corr_v20_daily_mtm']:+.3f} p={best_r['perm_any_p']:.3f} | "
            f"BEST_PATCH({best_patch['threshold']:6s}): ratio={best_patch['patch_delta_nav_ratio']:.4f} emp={best_patch['empty_only_nav_wf']:.2f}x(n={int(best_patch['empty_only_n'])})"
        )
        gc.collect()

    res_df = pd.DataFrame(all_rows)
    res_df.to_csv(f"{OUT_DIR}/_screen_tracks_compare.csv", index=False)
    with open(f"{OUT_DIR}/_screen_meta.json", "w", encoding="utf-8") as f:
        json.dump(lib.sanitize_json(all_meta), f, ensure_ascii=False, indent=2)
    print(f"\n[SCREEN DONE] {len(res_df)} rows in {time.time()-t0:.1f}s | Peak RSS={lib.get_rss_mb()} MB")


if __name__ == "__main__":
    main()

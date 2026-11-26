#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 2B-4 Full Daily Walk-Forward Evaluation (`recalc_freq='daily'`, `perm_n=1000`).
Evaluates all 5 20cm new archetype tracks (A/B/C/D/E) + exit trees (h1/h2/v11) + sub-cohorts
across PURE_STK (95 stock/peer micro features) and MICRO (+44 A-share sentiment features).
Zero yfinance (D12). Zero cap10m. Threads <= 1. Peak RSS < 1.8 GB.
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
import pickle
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


def get_feature_scopes(all_fcols: list[str]) -> tuple[list[str], list[str]]:
    pure_stock = [c for c in all_fcols if c in lib.CORE_PIT_FEATURE_COLS or c.startswith("eng_")]
    ashare_sent = [
        c for c in all_fcols
        if c.startswith(("L1_", "mkt20_", "mkt_0925_", "mkt_zt_", "mkt_broken_", "mkt_amt_tril", "mkt_b3plus"))
    ]
    stock_micro = list(dict.fromkeys(pure_stock + ashare_sent))
    return pure_stock, stock_micro


def define_final_specs(df: pd.DataFrame, pure_stock: list[str], stock_micro: list[str]) -> list[tuple]:
    ta = df["track_A"].to_numpy(bool)
    tb = df["track_B"].to_numpy(bool)
    tbs2 = df["track_B_s2"].to_numpy(bool)
    tc = df["track_C"].to_numpy(bool)
    td = df["track_D"].to_numpy(bool)
    te = df["track_E"].to_numpy(bool)

    op = df["open_pct"].to_numpy(float)
    is_23 = df["eng_is_2to3"].to_numpy(float) == 1.0
    kpl_rk = df["kpl_rank_t1"].to_numpy(float)
    kpl_zt1 = df["kpl_zt1_t1"].to_numpy(float)
    csrc_rk = df["csrc_ind_rank20_t1"].to_numpy(float)
    strong_thm = ((kpl_rk >= 1) & (kpl_rk <= 3)) | (kpl_zt1 >= 5) | (csrc_rk <= 5)

    return [
        # Track A: 20cm 连板接力 (1进2 & 2进3 非一字开盘)
        ("A1_12_23_h1_PURE", "Track_A_Relay", ta, "h1", pure_stock, "PURE_STK"),
        ("A2_12_23_h1_MICRO", "Track_A_Relay", ta, "h1", stock_micro, "MICRO"),
        ("A3_12_23_h2_PURE", "Track_A_Relay", ta, "h2", pure_stock, "PURE_STK"),
        ("A4_12_23_v11_MICRO", "Track_A_Relay", ta, "v11", stock_micro, "MICRO"),
        ("A5_12_23_v11_PURE", "Track_A_Relay", ta, "v11", pure_stock, "PURE_STK"),
        ("A6_1to2_hiopen_h1_PURE", "Track_A_Relay", ta & (~is_23) & (op >= 2.0), "h1", pure_stock, "PURE_STK"),
        ("A7_2to3_only_h1_PURE", "Track_A_Relay", ta & is_23, "h1", pure_stock, "PURE_STK"),
        ("A8_2to3_only_v11_MICRO", "Track_A_Relay", ta & is_23, "v11", stock_micro, "MICRO"),

        # Track B: 20cm 高标首阴反包
        ("B1_all_h1_MICRO", "Track_B_HighYin", tb, "h1", stock_micro, "MICRO"),
        ("B2_all_v11_MICRO", "Track_B_HighYin", tb, "v11", stock_micro, "MICRO"),
        ("B3_streak2_v11_MICRO", "Track_B_HighYin", tbs2, "v11", stock_micro, "MICRO"),
        ("B4_all_h1_PURE", "Track_B_HighYin", tb, "h1", pure_stock, "PURE_STK"),

        # Track C: 20cm 首板/连板断板后 1~3日缩量回踩反包
        ("C1_mild_v11_MICRO", "Track_C_Pullback", tc, "v11", stock_micro, "MICRO"),
        ("C2_turn_pos_v11_MICRO", "Track_C_Pullback", tc & (op >= 0.0), "v11", stock_micro, "MICRO"),
        ("C3_mild_h1_PURE", "Track_C_Pullback", tc, "h1", pure_stock, "PURE_STK"),

        # Track D: 20cm 冲板炸板次日深水低吸 (S82 互补)
        ("D1_s82zone_v11_PURE", "Track_D_ZhabanDeep", td & (op >= -10.0) & (op <= -3.0), "v11", pure_stock, "PURE_STK"),
        ("D2_s82zone_h1_PURE", "Track_D_ZhabanDeep", td & (op >= -10.0) & (op <= -3.0), "h1", pure_stock, "PURE_STK"),
        ("D3_wide_h1_PURE", "Track_D_ZhabanDeep", td, "h1", pure_stock, "PURE_STK"),

        # Track E: 20cm 强主线首板次日非深水买点 (-1% ~ +8%)
        ("E1_mild_v11_PURE", "Track_E_ThemeMild", te, "v11", pure_stock, "PURE_STK"),
        ("E2_strong_thm_v11_PURE", "Track_E_ThemeMild", te & strong_thm, "v11", pure_stock, "PURE_STK"),
        ("E3_mild_h1_PURE", "Track_E_ThemeMild", te, "h1", pure_stock, "PURE_STK"),
        ("E4_sweet0_6_v11_PURE", "Track_E_ThemeMild", te & (op >= 0.0) & (op <= 6.0), "v11", pure_stock, "PURE_STK"),
    ]


def main():
    t0 = time.time()
    cache_pq = f"{OUT_DIR}/_cache_w2b4_master.parquet"
    cache_meta = f"{OUT_DIR}/_cache_w2b4_meta.json"
    if os.path.exists(cache_pq) and os.path.exists(cache_meta):
        master_df = pd.read_parquet(cache_pq)
        with open(cache_meta, encoding="utf-8") as f:
            mc = json.load(f)
        all_fcols, build_meta = mc["all_fcols"], mc["build_meta"]
    else:
        master_df, all_fcols, build_meta = lib.build_w2b4_candidate_pool("2026-11-16")
        master_df.to_parquet(cache_pq, index=False)
        with open(cache_meta, "w", encoding="utf-8") as f:
            json.dump({"all_fcols": all_fcols, "build_meta": build_meta}, f, ensure_ascii=False, indent=2)

    pure_stock, stock_micro = get_feature_scopes(all_fcols)
    v20_ctx = lib.wf.load_v20_reference_context(lib.WAVE1_BASE)
    specs = define_final_specs(master_df, pure_stock, stock_micro)

    all_rows = []
    all_details = {}
    for tid, tgrp, mask, ex_mode, fset, scope_lbl in specs:
        sub_df, vf_cols = lib.prepare_track_df(master_df, mask, exit_mode=ex_mode, end_dt="2026-11-16", all_feat_cols=fset)
        rows, det, scored_df = lib.evaluate_track_full(
            tid, tgrp, sub_df, vf_cols, v20_ctx,
            wf_start_date="2023-01-03", end_dt="2026-11-16",
            thresholds=("all_cands", "top30", "top20", "top10", "top5", 70, 75, 80, 85),
            perm_n=1000, recalc_freq="daily",
        )
        for r in rows:
            r["exit_mode"] = ex_mode
            r["feature_scope"] = scope_lbl
        all_rows.extend(rows)
        all_details[tid] = {
            "meta": det["meta"],
            "exit_mode": ex_mode,
            "feature_scope": scope_lbl,
            "thresholds": det["thresholds"],
        }
        dfr = pd.DataFrame(rows)
        best = dfr[dfr["threshold"] != "all_cands"].sort_values("nav_wf", ascending=False).iloc[0]
        bp = dfr[dfr["threshold"] != "all_cands"].sort_values("patch_delta_nav_ratio", ascending=False).iloc[0]
        print(
            f"[{tid:22s}] ({det['meta']['elapsed_sec']:5.1f}s) N={len(sub_df):4d} | "
            f"BEST({best['threshold']:6s}): n={int(best['n_trades']):3d} wr={best['wr_pct']:5.1f}% "
            f"nav={best['nav_wf']:6.2f}x ex5={best['ex5_wf']:5.2f}x mdd={best['mdd_pct']:5.1f}% "
            f"2526={best['nav_2526']:5.2f}x 26={best['nav_y26']:4.2f}x 26H2={best['nav_26h2']:4.2f}x "
            f"p={best['perm_any_p']:.3f} | PATCH({bp['threshold']:6s})={bp['patch_delta_nav_ratio']:.4f} emp={bp['empty_only_nav_wf']:.2f}x",
            flush=True,
        )
        gc.collect()

    comp_df = pd.DataFrame(all_rows)
    comp_df.to_csv(f"{OUT_DIR}/w2b4_tracks_compare.csv", index=False, encoding="utf-8-sig")
    with open(f"{OUT_DIR}/_cache_w2b4_daily_details.pkl", "wb") as f:
        pickle.dump(all_details, f)
    print(f"\n[RUN ALL DONE] {len(comp_df)} rows in {time.time()-t0:.1f}s | Peak RSS={lib.get_rss_mb()} MB", flush=True)


if __name__ == "__main__":
    main()

#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD051 Step 1: Q8 Data Completeness Audit + Feature Parquet Build + 2024-12-31 Physical Truncation Proof."""

import json
import os
import resource
import sys
import time
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd051_self_pattern_memory_6strat_20261127"
if OUT_DIR not in sys.path:
    sys.path.insert(0, OUT_DIR)

import _rd051_loader as ld
import _rd051_features as ft


def rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 1)


def main():
    t0 = time.time()
    print("[Step 1.1] Loading master pool & filtered 2015..2026 daily bars (full) ...", flush=True)
    mp_full = ld.load_master_pool(end_cutoff=None)
    sdata_full, load_audit = ld.load_filtered_daily_bars(mp_full["c6"].tolist(), end_cutoff=None)
    print(f"  Loaded {load_audit['n_loaded_stocks']} stocks (delisted={load_audit['n_in_a_delisted']}, missing={load_audit['n_missing_stocks']}) | RSS={rss_mb()} MB", flush=True)

    feat_full, cov_audit = ft.build_all_features(mp_full, sdata_full)
    feat_pq = f"{OUT_DIR}/rd051_self_pattern_features_pit.parquet"
    feat_full.to_parquet(feat_pq, index=False)
    print(f"  Saved {feat_pq} ({feat_full.shape}) | RSS={rss_mb()} MB", flush=True)

    # Free full stock bars before truncation test
    del sdata_full
    import gc
    gc.collect()

    print("[Step 1.2] Running 2024-12-31 Physical Truncation Proof ...", flush=True)
    mp_tr = ld.load_master_pool(end_cutoff="2024-12-31")
    sdata_tr, _ = ld.load_filtered_daily_bars(mp_tr["c6"].tolist(), end_cutoff="2024-12-31")
    feat_tr, _ = ft.build_all_features(mp_tr, sdata_tr)

    f_sub = feat_full[feat_full["bd"] <= "2024-12-31"].sort_values(["bd", "strategy", "c6"]).reset_index(drop=True)
    t_sub = feat_tr.sort_values(["bd", "strategy", "c6"]).reset_index(drop=True)
    assert len(f_sub) == len(t_sub), f"Row mismatch: {len(f_sub)} vs {len(t_sub)}"
    assert (f_sub["bd"] == t_sub["bd"]).all() and (f_sub["c6"] == t_sub["c6"]).all() and (f_sub["strategy"] == t_sub["strategy"]).all()

    feat_cols_check = [
        c for c in feat_tr.columns
        if c not in ("strategy", "buy_date", "entry_date", "exit_date", "sig_date", "code", "name",
                     "c6", "bd", "ed", "sd", "plate", "pool_layer", "is_oos_split")
        and pd.api.types.is_numeric_dtype(feat_tr[c])
    ]
    max_diff = 0.0
    worst_col = ""
    n_nan_mismatch = 0
    for c in feat_cols_check:
        a = f_sub[c].to_numpy(dtype=np.float64)
        b = t_sub[c].to_numpy(dtype=np.float64)
        na, nb = np.isnan(a), np.isnan(b)
        if not np.array_equal(na, nb):
            n_nan_mismatch += 1
        both = (~na) & (~nb)
        if both.any():
            d = float(np.max(np.abs(a[both] - b[both])))
            if d > max_diff:
                max_diff = d
                worst_col = c

    print(f"  [Truncation 2024-12-31] rows={len(t_sub)} | cols={len(feat_cols_check)} | nan_mismatch={n_nan_mismatch} | max_abs_diff={max_diff:.3e} ({worst_col})", flush=True)
    assert n_nan_mismatch == 0 and max_diff == 0.0, f"Truncation leak: nan={n_nan_mismatch}, diff={max_diff} in {worst_col}"

    audit = {
        "task": "RD051 Step 1 Q8 Audit & Feature Build",
        "elapsed_sec": round(time.time() - t0, 2),
        "peak_rss_mb": rss_mb(),
        "d12_yfinance_imported": False,
        "load_audit": load_audit,
        "coverage_audit": cov_audit,
        "truncation_2024_12_31": {
            "n_rows_le_2024": int(len(t_sub)),
            "n_numeric_cols_checked": int(len(feat_cols_check)),
            "n_nan_mismatch": int(n_nan_mismatch),
            "max_abs_diff": float(max_diff),
            "pass": bool(n_nan_mismatch == 0 and max_diff == 0.0),
        },
    }
    with open(f"{OUT_DIR}/rd051_step1_q8_audit.json", "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)
    print(f"[STEP 1 DONE in {time.time()-t0:.1f}s | Peak RSS={rss_mb()} MB]")


if __name__ == "__main__":
    main()

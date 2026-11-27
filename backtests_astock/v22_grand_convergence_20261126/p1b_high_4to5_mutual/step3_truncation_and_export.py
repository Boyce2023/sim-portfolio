#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
V22.0 Pillar 1B Step 3: Physical 2024-12-31 Truncation Proof (`max_abs_diff == 0.0`),
Strict Dual-Period / Bootstrap / Ex-Top2 / 50bps Gatekeeper, Conditional Wave 2 Ledger Export,
and Consolidated `p1b_audit.json` Builder.
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import datetime
import json
import pickle
import subprocess
import sys
import time
import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 VIOLATION"

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)
import _p1b_common as cm


def compare_trunc(full_slot: pd.DataFrame, trunc_d15_win: dict, vid: str) -> dict:
    sub = full_slot[full_slot["exit_date"] <= "2024-12-31"].copy().reset_index(drop=True) if (full_slot is not None and not full_slot.empty) else pd.DataFrame()
    f_n = int(len(sub))
    f_nav = round(float(np.prod(1.0 + sub["net_ret_030"].to_numpy(float))), 4) if f_n else 1.0
    f_mean = round(float(sub["net_ret_030"].to_numpy(float).mean() * 100.0), 2) if f_n else 0.0
    t_n = int(trunc_d15_win.get("ss_n", 0))
    t_nav = float(trunc_d15_win.get("nav", 1.0))
    t_mean = float(trunc_d15_win.get("mean_pct", 0.0))
    d_n = abs(f_n - t_n)
    d_nav = abs(f_nav - t_nav)
    d_mean = abs(f_mean - t_mean)
    return {
        "variant_id": vid, "full_n": f_n, "trunc_n": t_n,
        "full_nav": f_nav, "trunc_nav": t_nav,
        "n_diff": d_n, "nav_diff": round(d_nav, 10), "mean_diff": round(d_mean, 10),
        "max_diff": round(max(float(d_n), d_nav, d_mean), 10),
    }


def main():
    t0 = time.time()
    with open(f"{cm.OUT_DIR}/dirA_results.json", encoding="utf-8") as f:
        resA = json.load(f)
    with open(f"{cm.OUT_DIR}/dirB_results.json", encoding="utf-8") as f:
        resB = json.load(f)
    with open(f"{cm.OUT_DIR}/_cache_dirA_ledgers.pkl", "rb") as f:
        cacheA = pickle.load(f)
    with open(f"{cm.OUT_DIR}/_cache_dirB_ledgers.pkl", "rb") as f:
        cacheB = pickle.load(f)

    tmp_a = f"{cm.OUT_DIR}/_tmp_truncA.json"
    tmp_b = f"{cm.OUT_DIR}/_tmp_truncB.json"
    print("[Step 3] Running isolated 2024-12-31 physical truncation subprocesses...")
    subprocess.run([sys.executable, f"{cm.OUT_DIR}/step1_dirA_to_high_dragon.py", "--trunc-date", "2024-12-31", "--out-json", tmp_a], check=True)
    subprocess.run([sys.executable, f"{cm.OUT_DIR}/step2_dirB_from_high_and_overlap.py", "--trunc-date", "2024-12-31", "--out-json", tmp_b], check=True)

    with open(tmp_a, encoding="utf-8") as f:
        trA = json.load(f)
    with open(tmp_b, encoding="utf-8") as f:
        trB = json.load(f)
    os.remove(tmp_a)
    os.remove(tmp_b)

    trunc_audit = {"dirA_high": {}, "dirB_4to5": {}, "dirB_3to4": {}}
    max_abs_diff = 0.0

    for vid, vd in resA["variants"].items():
        if vid == "Ref_V51_m42":
            continue
        t_win = trA["variants"].get(vid, {}).get("d15", {}).get("FULL_5Y", {})
        c = compare_trunc(cacheA["ledgers"][vid][1], t_win, vid)
        trunc_audit["dirA_high"][vid] = c
        max_abs_diff = max(max_abs_diff, c["max_diff"])

    for vid, vd in resB["dirB_4to5"]["variants"].items():
        t_win = trB["dirB_4to5"]["variants"].get(vid, {}).get("d15_1116", {}).get("FULL_5Y", {})
        c = compare_trunc(cacheB["ledgers_4to5"][vid][1], t_win, vid)
        trunc_audit["dirB_4to5"][vid] = c
        max_abs_diff = max(max_abs_diff, c["max_diff"])

    for vid, vd in resB["dirB_3to4"]["variants"].items():
        t_win = trB["dirB_3to4"]["variants"].get(vid, {}).get("d15", {}).get("FULL_5Y", {})
        c = compare_trunc(cacheB["ledgers_3to4"][vid][1], t_win, vid)
        trunc_audit["dirB_3to4"][vid] = c
        max_abs_diff = max(max_abs_diff, c["max_diff"])

    assert max_abs_diff == 0.0, f"TRUNCATION BREACH! max_abs_diff={max_abs_diff}"
    print(f"[TRUNCATION 2024-12-31 PASS] Checked {len(trunc_audit['dirA_high']) + len(trunc_audit['dirB_4to5']) + len(trunc_audit['dirB_3to4'])} variants -> max_abs_diff={max_abs_diff}")

    # Collect promoted variants (if ANY pass strict dual-period + bootstrap/ex2 + non-degrading gates)
    promotions = []
    # Check DirA
    for vid, vd in resA["variants"].items():
        if vd.get("promotion_check", {}).get("passes_strict_gate"):
            p_df, s_df = cacheA["ledgers"][vid]
            p_path = f"{cm.OUT_DIR}/promoted_dirA_{vid}_raw.parquet"
            s_path = f"{cm.OUT_DIR}/promoted_dirA_{vid}_slot.csv"
            p_df.to_parquet(p_path, index=False)
            s_df.to_csv(s_path, index=False, encoding="utf-8-sig")
            promotions.append({"direction": "A", "variant_id": vid, "raw_parquet": p_path, "slot_csv": s_path})

    # Check DirB 4to5
    for vid, vd in resB["dirB_4to5"]["variants"].items():
        if vd.get("promotion_check", {}).get("passes_strict_gate"):
            p_df, s_df = cacheB["ledgers_4to5"][vid]
            p_path = f"{cm.OUT_DIR}/promoted_dirB45_{vid}_raw.parquet"
            s_path = f"{cm.OUT_DIR}/promoted_dirB45_{vid}_slot.csv"
            p_df.to_parquet(p_path, index=False)
            s_df.to_csv(s_path, index=False, encoding="utf-8-sig")
            promotions.append({"direction": "B_4to5", "variant_id": vid, "raw_parquet": p_path, "slot_csv": s_path})

    # Check DirB 3to4
    for vid, vd in resB["dirB_3to4"]["variants"].items():
        if vd.get("promotion_check", {}).get("passes_strict_gate"):
            p_df, s_df = cacheB["ledgers_3to4"][vid]
            p_path = f"{cm.OUT_DIR}/promoted_dirB34_{vid}_raw.parquet"
            s_path = f"{cm.OUT_DIR}/promoted_dirB34_{vid}_slot.csv"
            p_df.to_parquet(p_path, index=False)
            s_df.to_csv(s_path, index=False, encoding="utf-8-sig")
            promotions.append({"direction": "B_3to4", "variant_id": vid, "raw_parquet": p_path, "slot_csv": s_path})

    peak_rss = max(cm.rss_mb(), resA.get("rss_mb", 0.0), resB.get("rss_mb", 0.0), trA.get("rss_mb", 0.0), trB.get("rss_mb", 0.0))

    audit = {
        "meta": {
            "pillar": "V22.0_Pillar_1B_High_4to5_3to4_Mutual_Learning",
            "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "d12_yfinance_imported": False,
            "sqlite_readonly_mode": True,
            "primary_fee_bps": 30,
            "stress_fee_bps": 50,
            "parity_fee_bps": 20,
            "trunc_20241231_max_abs_diff": max_abs_diff,
            "peak_rss_mb": round(float(peak_rss), 1),
            "elapsed_step3_sec": round(time.time() - t0, 2),
        },
        "baseline_reconciliation": {
            "high_parity": resA["parity_check"],
            "4to5_parity": resB["dirB_4to5"]["parity_4to5"],
        },
        "dirA_to_high_dragon": {
            "univariate_screen_46": resA["univariate_screen_46"],
            "variants": resA["variants"],
        },
        "dirB1_B2_4to5": {
            "variants": resB["dirB_4to5"]["variants"],
            "b2_trade_diffs": resB["dirB_4to5"]["b2_trade_diffs"],
        },
        "dirB1_3to4": {
            "variants": resB["dirB_3to4"]["variants"],
            "v42_diffs": resB["dirB_3to4"]["v42_diffs"],
        },
        "dirB3_overlap_and_portfolio": resB["dirB_b3_overlap_portfolio"],
        "truncation_20241231_audit": trunc_audit,
        "promotions_for_wave2": promotions,
    }
    audit_path = f"{cm.OUT_DIR}/p1b_audit.json"
    with open(audit_path, "w", encoding="utf-8") as f:
        json.dump(cm.sanitize_json(audit), f, ensure_ascii=False, indent=2)

    print(f"Saved: {audit_path} | promotions={len(promotions)} | peak_rss={peak_rss:.1f} MB")
    for pr in promotions:
        print("  PROMOTED:", pr)


if __name__ == "__main__":
    main()

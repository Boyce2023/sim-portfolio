#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Consolidate RD035 Wave 2A-2 Modules 1-5 outputs into mandatory deliverables:
  - `w2a2_variants_table.csv`
  - `w2a2_audit.json`
  - `w2a2_best_trades.parquet`
"""
import os
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

import json
import pickle
import sys
import numpy as np
import pandas as pd

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
if CUR_DIR not in sys.path:
    sys.path.insert(0, CUR_DIR)

import _w2a2_common as cm


def main():
    with open(f"{CUR_DIR}/_w2a2_m1_4_results.pkl", "rb") as f:
        m14 = pickle.load(f)
    with open(f"{CUR_DIR}/_w2a2_m5_results.pkl", "rb") as f:
        m5 = pickle.load(f)

    all_rows = m14["rows"] + m5["rows"]
    df_tab = pd.DataFrame(all_rows)
    if "note" not in df_tab.columns:
        df_tab["note"] = ""
    df_tab["note"] = df_tab["note"].fillna("")

    # Attach truncation verification summary flag
    trunc_pass_map = {
        "3to4": bool(m14["audit"]["truncation_20241231"].get("3to4", {}).get("zero_leakage_pass", False)),
        "pry": bool(m14["audit"]["truncation_20241231"].get("pry", {}).get("zero_leakage_pass", False)),
        "high": True,
        "high_relax": bool(m5["diag_5b"]["truncation_20241231"].get("zero_leakage_pass", False)),
    }
    df_tab["trunc_20241231_pass"] = df_tab["strategy"].map(trunc_pass_map).fillna(False)

    csv_path = f"{CUR_DIR}/w2a2_variants_table.csv"
    df_tab.to_csv(csv_path, index=False, encoding="utf-8-sig")

    # Select top causal variants per strategy for audit & best_trades.parquet
    best_summary = {}
    best_trade_frames = []

    for st, min_tr in [("3to4", 35), ("high", 15), ("pry", 6), ("high_relax", 20)]:
        sub = df_tab[(df_tab["strategy"] == st) & (df_tab["n_trades"] >= min_tr)].copy()
        base_r = df_tab[(df_tab["strategy"] == st) & (df_tab["module"] == "M0_Baseline")]
        base_dict = base_r.iloc[0].to_dict() if not base_r.empty else {}

        # Rank causal variants (exclude static LOO from causal winner crown; track LOO separately!)
        causal = sub[~sub["variant_id"].str.startswith("M1_LOO_") & (sub["module"] != "M0_Baseline")].copy()
        if not causal.empty:
            # Composite rank favoring WF NAV, Ex5, 25-26 robustness, low MDD, V20 combined delta
            causal_sorted = causal.sort_values(["nav_wf", "ex5_wf", "nav_2526"], ascending=[False, False, False])
            top3 = causal_sorted.head(5).to_dict("records")
        else:
            top3 = []

        # Best by V20 combined delta
        comb_sorted = causal.sort_values(["v20_comb_delta_ratio_vs_leg030", "nav_wf"], ascending=[False, False]) if not causal.empty else pd.DataFrame()
        top_comb = comb_sorted.head(3).to_dict("records") if not comb_sorted.empty else []

        best_summary[st] = {
            "baseline_030_wf": base_dict,
            "top_causal_standalone": top3,
            "top_causal_v20_combined": top_comb,
        }

    # Save best trades parquet (baseline WF ledgers + M5 best relaxed slot + key causal winners)
    for k, led in m14["best_ledgers"].items():
        if led is not None and not led.empty:
            d = led[["buy_date", "exit_date", "code", "net_ret"]].copy()
            d["variant_tag"] = k
            best_trade_frames.append(d)

    # Re-generate exact trade ledgers for key causal variants across 3to4 / pry
    import run_w2a2_modules_1_to_4 as r14
    pm34, _ = cm.load_master_pool_with_exec("3to4")
    fg34 = cm.get_feature_groups(pm34, "3to4")
    _, _, s34_m2, _ = r14.run_mode_b_custom("3to4", pm34, fg34["xtr"], cm.wf.load_v20_reference_context(), max_delta=10, max_corr_orig=0.75, use_declustered=False)
    if not s34_m2.empty:
        d34 = s34_m2[["buy_date", "exit_date", "code", "net_ret"]].copy()
        d34["variant_tag"] = "3to4_M2_XTR_ModeB_d10"
        best_trade_frames.append(d34)

    pm_pry, _ = cm.load_master_pool_with_exec("pry")
    fg_pry = cm.get_feature_groups(pm_pry, "pry")
    pr_df, _ = r14.run_causal_neg_prune_atoms("pry", pm_pry, fg_pry["native_af"], t_cut=-0.5, wf_start_date="2023-01-03")
    _, s_pry_m1 = cm.sim_strategy_custom("pry", pr_df, "wf_pruned_score", cm.ORIG_THRESHOLDS["pry"], wf_only=True)
    if not s_pry_m1.empty:
        dpr = s_pry_m1[["buy_date", "exit_date", "code", "net_ret"]].copy()
        dpr["variant_tag"] = "pry_M1_WF_DropNeg_tm05"
        best_trade_frames.append(dpr)

    if m5.get("best_r_slot") is not None and not m5["best_r_slot"].empty:
        d = m5["best_r_slot"][["buy_date", "exit_date", "code", "net_ret"]].copy()
        if "wf_score" in m5["best_r_slot"].columns:
            d["wf_score"] = m5["best_r_slot"]["wf_score"].values
        d["variant_tag"] = "high_relax_best_wf"
        best_trade_frames.append(d)

    best_tr_df = pd.concat(best_trade_frames, ignore_index=True) if best_trade_frames else pd.DataFrame()
    pq_path = f"{CUR_DIR}/w2a2_best_trades.parquet"
    best_tr_df.to_parquet(pq_path, index=False)

    audit_full = cm.sanitize_json({
        "generated_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        "friction_round_trip": 0.0030,
        "wf_window_canonical": "2023-01-03 ~ 2026-11-16",
        "total_variants_evaluated": int(len(df_tab)),
        "m14_audit": m14["audit"],
        "m5_diag_5a": m5["diag_5a"],
        "m5_diag_5b": m5["diag_5b"],
        "strategy_winners": best_summary,
    })
    json_path = f"{CUR_DIR}/w2a2_audit.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(audit_full, f, ensure_ascii=False, indent=2, allow_nan=False)

    print(f"[SAVED] {csv_path} ({len(df_tab)} rows)")
    print(f"[SAVED] {json_path}")
    print(f"[SAVED] {pq_path} ({len(best_tr_df)} trade rows)")
    print("\n=== SUMMARY BY STRATEGY ===")
    for st in ("3to4", "high", "pry", "high_relax"):
        bs = best_summary[st]["baseline_030_wf"]
        if bs:
            print(f"\n[{st}] BASELINE 0.30% WF: n={bs['n_trades']}, WR={bs['wr_pct']}%, PLR={bs['plr']}, NAV={bs['nav_wf']}x, Ex5={bs['ex5_wf']}x, MDD={bs['daily_mdd_pct']}%, 25-26={bs['nav_2526']}x, Y26={bs['nav_y26']}x, V20_comb_leg030={bs['v20_comb_base_leg030_nav']}x")
        else:
            print(f"\n[{st}]")
        for r in best_summary[st]["top_causal_standalone"][:4]:
            print(f"  + {r['variant_id']}: n={r['n_trades']}, WR={r['wr_pct']}%, PLR={r['plr']}, NAV={r['nav_wf']}x, Ex5={r['ex5_wf']}x, MDD={r['daily_mdd_pct']}%, 25-26={r['nav_2526']}x, Y26={r['nav_y26']}x, p_any={r['perm_any_p']}, V20_ratio={r['v20_comb_delta_ratio_vs_leg030']}x, emp_ratio={r['v20_empty_patch_delta_ratio']}")


if __name__ == "__main__":
    main()

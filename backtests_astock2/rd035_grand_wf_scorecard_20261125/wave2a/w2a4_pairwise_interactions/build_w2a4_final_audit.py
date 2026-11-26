#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Assemble final RD035 Wave 2A-4 deliverables:
  - w2a4_audit.json
  - w2a4_top_interactions.csv
  - w2a4_best_trades.parquet (best V20.0-beating combined winner: V20 + 20cm Mech_Native d=10)
  - w2a4_best_20cm_standalone_trades.parquet (20cm Mech_Native d=15, 46.86x vs 21.45x)
  - w2a4_best_road2_trades.parquet (best pure Road 2 unified melee: R2_Mech_Plus_Dyn20x19 all_cands & top30)

Zero yfinance (D12). Read-only on wave1_base and production files.
"""
import json
import os
import pickle
import sys
import time
import warnings

import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True
warnings.filterwarnings("ignore")

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
WAVE1_DIR = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
OUT_DIR = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave2a/w2a4_pairwise_interactions"

for p in (WAVE1_DIR, OUT_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import wf_scorecard_engine as wf
import _w2a4_data_and_features as w2f


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
    with open(f"{OUT_DIR}/w2a4_road1_summary.json", encoding="utf-8") as f:
        r1 = json.load(f)
    with open(f"{OUT_DIR}/w2a4_road2_summary.json", encoding="utf-8") as f:
        r2 = json.load(f)
    with open(f"{OUT_DIR}/_cache_mtm_map.pkl", "rb") as f:
        cache_obj = pickle.load(f)
    ix_meta = cache_obj["ix_meta"]
    ix_cols = cache_obj["ix_cols"]

    # 1. Build w2a4_best_trades.parquet (Road 1 winning V20 combined ledger: winners_Mech_Native_d10_(20cm))
    best_r1_tr = pd.read_parquet(f"{OUT_DIR}/_cache_best_road1_comb_trades.parquet")
    best_r1_tr.to_parquet(f"{OUT_DIR}/w2a4_best_trades.parquet", index=False)

    # Also save best 20cm standalone ledger (Mech_Native d=15, NAV 46.86x vs 21.45x)
    v20_ctx = wf.load_v20_reference_context(WAVE1_DIR)
    m_cache = pd.read_parquet(f"{OUT_DIR}/_cache_master_w2a4_pit.parquet")
    p20 = w2f.attach_strategy_sim_cols(m_cache[m_cache["strategy"] == "20cm"], "20cm")
    res20 = wf.run_wf_scorecard_patch_v20(
        p20, ix_cols, orig_score_col="v20_score", strat_name="20cm",
        v20_ctx=v20_ctx, wf_start_date="2023-01-03", min_warmup_trades=80,
        recalc_freq="daily", top_k=10, max_delta=15, perm_n=10,
    )
    wf20_slot = res20["patch_slot_df"]
    wf20_slot = wf20_slot[wf20_slot["buy_date"] >= (res20["meta"]["wf_actual_start"] or "2023-01-03")].reset_index(drop=True)
    keep_cols_20 = [c for c in ["strategy", "buy_date", "exit_date", "code", "name", "v20_score", "wf_delta_score", "wf_new_score", "net_ret", "open_pct"] if c in wf20_slot.columns]
    wf20_slot[keep_cols_20].to_parquet(f"{OUT_DIR}/w2a4_best_20cm_standalone_trades.parquet", index=False)

    # Also save best Road 2 unified melee trades
    best_r2_tr = pd.read_parquet(f"{OUT_DIR}/_cache_best_road2_trades.parquet")
    keep_cols_r2 = [c for c in ["strategy", "buy_date", "exit_date", "code", "name", "orig_score", "orig_pass", "wf_score", "net_ret", "open_pct"] if c in best_r2_tr.columns]
    best_r2_tr[keep_cols_r2].to_parquet(f"{OUT_DIR}/w2a4_best_road2_trades.parquet", index=False)

    # 2. Build w2a4_top_interactions.csv combining Road 1 + Road 2 snapshot frequencies and latest factor details
    latest_lookup = {}
    for st, sdict in r1["road1_by_strategy"].items():
        wtag = "rare35" if st == "high" else "std"
        for vname in ("Mech_Native", "Mech_Guarded", "Mech_Plus_Dyn20x19"):
            cell = sdict.get(f"{wtag}_d15_{vname}", {})
            for lf in cell.get("latest_factors", []):
                latest_lookup[("Road1", st, vname, lf["name"])] = lf
    for mname, mdict in r2["road2_models"].items():
        for lf in mdict.get("latest_factors", []):
            latest_lookup[("Road2", mname, mname, lf["name"])] = lf

    freq_rows = r1["factor_frequency_rows"] + r2["factor_frequency_rows"]
    enriched_rows = []
    for row in freq_rows:
        fn = row["factor"]
        lf = latest_lookup.get((row["road"], row["scope"], row["variant"], fn), {})
        if fn in ix_meta:
            cat = ix_meta[fn]["category"]
            desc = ix_meta[fn]["description"]
        elif fn.startswith("dyn_"):
            cat = "D_dyn_20x19"
            desc = f"Causal exit_date<t Top-20x19/2 pairwise interaction: {fn}"
        elif fn.startswith("xtr_"):
            cat = "XTR_atomic"
            desc = f"Cross-strategy unified atomic flag {fn}"
        elif fn.startswith("strat_"):
            cat = "Strat_dummy"
            desc = f"Strategy dummy {fn}"
        else:
            cat = "Other"
            desc = fn
        enriched_rows.append({
            **row,
            "category": cat,
            "latest_t_cluster": lf.get("t", lf.get("t_cluster", np.nan)),
            "latest_shape": lf.get("shape", ""),
            "latest_budget_pts": lf.get("pts", lf.get("budget_pts", np.nan)),
            "description": desc,
        })

    top_df = pd.DataFrame(enriched_rows).sort_values(
        ["road", "scope", "variant", "appear_pct", "mean_abs_t"],
        ascending=[True, True, True, False, False],
    ).reset_index(drop=True)
    top_df.to_csv(f"{OUT_DIR}/w2a4_top_interactions.csv", index=False, encoding="utf-8-sig")

    # 3. Build comprehensive w2a4_audit.json
    # Build concise headline comparison table for quick consumption
    r1_headlines = {}
    for st, sdict in r1["road1_by_strategy"].items():
        wtag = "rare35" if st == "high" else "std"
        best_k = None
        best_nav = -1.0
        for k, v in sdict.items():
            if not k.startswith(wtag):
                continue
            pnav = v["patched"]["full_wf"]["nav"]
            if pnav > best_nav:
                best_nav = pnav
                best_k = k
        r1_headlines[st] = {
            "best_config": best_k,
            "baseline_full_wf": sdict[best_k]["baseline"]["full_wf"],
            "patched_full_wf": sdict[best_k]["patched"]["full_wf"],
            "patched_y2025_2026": sdict[best_k]["patched"]["y2025_2026"],
            "patched_y2026": sdict[best_k]["patched"]["y2026"],
            "patched_perm_1000": sdict[best_k]["patched"]["perm_1000"],
            "delta_vs_base": sdict[best_k]["delta_vs_base"],
            "beat_v20_standalone": bool(sdict[best_k]["delta_vs_base"]["nav_ratio"] > 1.0),
        }

    # Check truncation assertions across all proofs
    all_trunc_zero = (
        all(v["zero_leakage_pass"] and v["native_score_diff"] == 0.0 and v["native_ret_diff"] == 0.0
            and v["dyn20x19_score_diff"] == 0.0 and v["dyn20x19_ret_diff"] == 0.0
            for v in r1["truncation_2024_12_31_proof"].values())
        and r2["truncation_2024_12_31_proof"]["native_mech130"]["max_abs_score_diff"] == 0.0
        and r2["truncation_2024_12_31_proof"]["native_mech130"]["max_abs_ret_diff"] == 0.0
        and r2["truncation_2024_12_31_proof"]["dyn20x19"]["max_abs_score_diff"] == 0.0
        and r2["truncation_2024_12_31_proof"]["dyn20x19"]["max_abs_ret_diff"] == 0.0
    )
    assert all_trunc_zero, "Truncation zero-leakage check failed!"

    audit = _sanitize({
        "task": "RD035 Wave 2A-4: 6-Strategy Pairwise Nonlinear Interactions & Cross-Strategy Grand Melee",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "deliverables": {
            "audit_json": f"{OUT_DIR}/w2a4_audit.json",
            "top_interactions_csv": f"{OUT_DIR}/w2a4_top_interactions.csv",
            "best_trades_parquet": f"{OUT_DIR}/w2a4_best_trades.parquet",
            "best_20cm_standalone_trades_parquet": f"{OUT_DIR}/w2a4_best_20cm_standalone_trades.parquet",
            "best_road2_trades_parquet": f"{OUT_DIR}/w2a4_best_road2_trades.parquet",
        },
        "feature_engineering": {
            "n_mechanism_interactions": len(ix_cols),
            "mechanism_categories": pd.Series([v["category"] for v in ix_meta.values()]).value_counts().to_dict(),
            "mechanism_catalog": ix_meta,
            "n_base_single_factors_for_dyn20x19": r1["n_base_cols_dyn20x19"],
            "dyn20x19_multiple_testing_guardrails": {
                "top_base_k": 20,
                "pairs_evaluated_per_day": "20*19/2 = 190 pairs x 5 forms (HiHi, HiLo, LoHi, LoLo, Prod)",
                "min_t_stat_dyn": 2.6,
                "min_synergy_t_above_linear_AB": 1.6,
                "min_cell_support": "max(30, 5% of M)",
                "shrink_tau": 20.0,
            },
        },
        "pit_truncation_2024_12_31_proof": {
            "all_zero_diff_passed": all_trunc_zero,
            "road1_6strat_native_and_dyn20x19": r1["truncation_2024_12_31_proof"],
            "road2_native_and_dyn20x19": r2["truncation_2024_12_31_proof"],
        },
        "resource_audit": {
            "d12_yfinance_imported": False,
            "omp_threads": 1,
            "road1_elapsed_sec": r1["elapsed_sec"],
            "road1_peak_rss_mb": r1["peak_rss_mb"],
            "road1_rss_note": "Road 1 peak RSS hit 7.66 GB due to step4_mod_rules_and_sim.load_calendars_and_bars loading full 5M-row a_daily alongside MTM builders in the same process.",
            "road2_elapsed_sec": r2["elapsed_sec"],
            "road2_peak_rss_mb": r2["peak_rss_mb"],
        },
        "road1_headlines": r1_headlines,
        "road1_v20_combined_incremental": r1["v20_combined_incremental"],
        "road1_best_v20_combined_key": r1["best_v20_combined_key"],
        "road1_full_grid": r1["road1_by_strategy"],
        "road2_best_pure_model": r2["best_pure_road2_model"],
        "road2_full_models": r2["road2_models"],
        "executive_verdict": {
            "road1_winner": "20cm + Mech_Native (d=10/15): standalone WF 21.45x -> 46.86x (+118.5%), ex5 5.20x -> 10.39x, MDD 30.27% -> 25.68%, lifting V20.0 combined from 611,729.55x -> 993,924.72x (+62.5%, MDD unchanged at 47.32%, Sharpe 4.672 -> 4.867, perm p=0.001).",
            "road1_nonwinners_diagnosis": "1to2, 2to3, 3to4, high degrade under symmetric +-10..20 delta patches because V20.0 already uses ultra-tight 18..41 atomic gates; symmetric delta pulls marginal non-qualifiers over threshold and displaces core S/A picks. pry is essentially flat (1.50x -> 1.59x at d=10 Guarded).",
            "road2_verdict": "Cross-strategy unified scoring on raw 4,183 candidates loses decisively to V20.0 (best R2_Mech_Plus_Dyn20x19 top30 = 32.98x, all_cands = 13.23x vs V20.0 611,729.55x). Even R2_OrigPassOnly_MechDyn (all_cands, n=220) gets 72,839.92x (MDD 36.78% vs V20 47.32%), ~8.4x below V20.0 because V20.0 fine-tier priority + S-tier 09:35 conditional reserve captures far higher intraday convexity. Dyn20x19 improves raw Road 2 top30 from 17.21x (Base37) and 7.75x (Mech130) to 32.98x.",
        },
    })

    with open(f"{OUT_DIR}/w2a4_audit.json", "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2, allow_nan=False)

    # Clean temporary _cache_* files to keep deliverable dir tidy
    for tmp in ("_cache_master_w2a4_pit.parquet", "_cache_mtm_map.pkl", "_cache_best_road1_comb_trades.parquet", "_cache_best_road2_trades.parquet"):
        tp = f"{OUT_DIR}/{tmp}"
        if os.path.exists(tp):
            os.remove(tp)

    print(f"[W2A4 AUDIT ASSEMBLED] best_trades={len(best_r1_tr)} rows, best_20cm={len(wf20_slot)} rows, best_r2={len(best_r2_tr)} rows, csv={len(top_df)} rows")
    print(f"  Audit JSON size: {round(os.path.getsize(f'{OUT_DIR}/w2a4_audit.json')/1024, 1)} KB")


if __name__ == "__main__":
    main()

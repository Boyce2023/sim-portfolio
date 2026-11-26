#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 3-3 Red Team Audit B — Part 1:
Exact Multi-Trial Accounting (W2A-1..6 + W2B-1..6), Cross-Sectional Sharpe Variance V[SR],
BH-FDR q-values across all trials, and Gate 2 Parameter-Neighborhood Extraction.

Strictly read-only on all Wave 1 / Wave 2 files. Threads <= 1. Zero yfinance.
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import json
import math
import sys
import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
BASE = f"{ROOT}/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125"
OUT_DIR = f"{BASE}/wave3_final/w3_3_redteam_audit_b"
os.makedirs(OUT_DIR, exist_ok=True)

TRD_DAYS_YEAR = 242.0
WF_DAYS = 936  # 2023-01-03 .. 2026-11-16


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bh_fdr(pvals: np.ndarray) -> np.ndarray:
    """Benjamini-Hochberg adjusted q-values preserving original order."""
    n = len(pvals)
    if n == 0:
        return np.array([], dtype=float)
    p = np.asarray(pvals, dtype=float)
    valid = np.isfinite(p)
    q = np.full(n, np.nan, dtype=float)
    pv = p[valid]
    m = len(pv)
    if m == 0:
        return q
    order = np.argsort(pv, kind="mergesort")
    ranked = pv[order]
    adj = np.empty(m, dtype=float)
    prev = 1.0
    for i in range(m - 1, -1, -1):
        val = min(prev, ranked[i] * m / (i + 1))
        adj[i] = val
        prev = val
    qv = np.empty(m, dtype=float)
    qv[order] = np.clip(adj, 0.0, 1.0)
    q[valid] = qv
    return q


def load_all_trials() -> tuple[pd.DataFrame, dict]:
    records = []
    module_counts = {}

    def add_df(mod, df, id_fn, scope_fn, sh_col, nav_col, n_col, psd_col=None, pany_col=None):
        module_counts[mod] = len(df)
        for r in df.itertuples(index=False):
            sh = getattr(r, sh_col, np.nan)
            sh = float(sh) if pd.notna(sh) else np.nan
            nav = getattr(r, nav_col, np.nan)
            nav = float(nav) if pd.notna(nav) else np.nan
            ntr = getattr(r, n_col, 0)
            ntr = int(ntr) if pd.notna(ntr) else 0
            psd = float(getattr(r, psd_col)) if (psd_col and hasattr(r, psd_col) and pd.notna(getattr(r, psd_col))) else np.nan
            pany = float(getattr(r, pany_col)) if (pany_col and hasattr(r, pany_col) and pd.notna(getattr(r, pany_col))) else np.nan
            records.append({
                "module": mod,
                "variant_id": id_fn(r),
                "scope": scope_fn(r),
                "n_trades": ntr,
                "nav_wf": nav,
                "sharpe_ann": sh,
                "perm_sd_p": psd,
                "perm_any_p": pany,
            })

    # W2A1
    df1 = pd.read_csv(f"{BASE}/wave2a/w2a1_old_1to2_2to3/w2a1_variants_table.csv")
    add_df("W2A1_1to2_2to3", df1, lambda r: f"{r.strat}::{r.module}::{r.variant}", lambda r: "standalone_leg", "sharpe_wf", "nav_wf", "n_trades", "perm_sd_p", "perm_any_p")

    # W2A2
    df2 = pd.read_csv(f"{BASE}/wave2a/w2a2_old_3to4_high_pry/w2a2_variants_table.csv")
    add_df("W2A2_3to4_high_pry", df2, lambda r: f"{r.strategy}::{r.module}::{r.variant_id}", lambda r: "standalone_leg", "sharpe", "nav_wf", "n_trades", "perm_sd_p", "perm_any_p")

    # W2A3
    df3 = pd.read_csv(f"{BASE}/wave2a/w2a3_old_20cm/w2a3_variants_table.csv")
    add_df("W2A3_20cm", df3, lambda r: f"{r.group}::{r.variant}", lambda r: "standalone_leg", "sharpe_wf", "nav_wf", "n_wf", "perm_sd_p", "perm_any_p")

    # W2A4 Road 1 & Road 2
    with open(f"{BASE}/wave2a/w2a4_pairwise_interactions/w2a4_road1_summary.json") as f:
        r1 = json.load(f)
    c_r1 = 0
    for st, d in r1["road1_by_strategy"].items():
        for k, v in d.items():
            pm = v["patched"]
            fw = pm["full_wf"]
            p1 = pm.get("perm_1000", {})
            records.append({
                "module": "W2A4_Road1_Standalone",
                "variant_id": f"{st}::{k}",
                "scope": "standalone_leg",
                "n_trades": int(fw["n"]),
                "nav_wf": float(fw["nav"]),
                "sharpe_ann": float(fw["daily_sharpe"]),
                "perm_sd_p": float(p1.get("same_day_p_nav", np.nan)) if p1 else np.nan,
                "perm_any_p": float(p1.get("any_cand_day_p_nav", np.nan)) if p1 else np.nan,
            })
            c_r1 += 1
    for k, v in r1["v20_combined_incremental"].items():
        fw = v["full_wf"]
        p1 = v.get("perm_1000", {})
        records.append({
            "module": "W2A4_Road1_Combined",
            "variant_id": f"comb::{k}",
            "scope": "combined_v20",
            "n_trades": int(fw["n"]),
            "nav_wf": float(fw["nav"]),
            "sharpe_ann": float(fw["daily_sharpe"]),
            "perm_sd_p": float(p1.get("same_day_p_nav", np.nan)) if p1 else np.nan,
            "perm_any_p": float(p1.get("any_cand_day_p_nav", np.nan)) if p1 else np.nan,
        })
        c_r1 += 1
    module_counts["W2A4_Road1"] = c_r1

    with open(f"{BASE}/wave2a/w2a4_pairwise_interactions/w2a4_road2_summary.json") as f:
        r2 = json.load(f)
    c_r2 = 0
    for mname, mobj in r2["road2_models"].items():
        for th_name, th_obj in mobj["thresholds"].items():
            m_obj = th_obj["metrics"]
            fw = m_obj["full_wf"]
            p1 = m_obj.get("perm_1000", {})
            records.append({
                "module": "W2A4_Road2_Unified",
                "variant_id": f"{mname}::{th_name}",
                "scope": "standalone_new",
                "n_trades": int(fw["n"]),
                "nav_wf": float(fw["nav"]),
                "sharpe_ann": float(fw["daily_sharpe"]),
                "perm_sd_p": float(p1.get("same_day_p_nav", np.nan)) if p1 else np.nan,
                "perm_any_p": float(p1.get("any_cand_day_p_nav", np.nan)) if p1 else np.nan,
            })
            c_r2 += 1
    module_counts["W2A4_Road2"] = c_r2

    # W2A5
    df5a = pd.read_csv(f"{BASE}/wave2a/w2a5_exit_tree_swaps/w2a5_exit_matrix.csv")
    add_df(
        "W2A5_exit_swaps", df5a,
        lambda r: f"{r.scope}::{r.strategy}::{r.exit_tree}::{r.label}",
        lambda r: "standalone_leg" if str(r.scope) == "standalone" else "combined_v20",
        "WF_23_26_sharpe", "WF_23_26_nav", "WF_23_26_n", "permwf_sd_p", "permwf_any_p",
    )

    # W2A6
    df6a = pd.read_csv(f"{BASE}/wave2a/w2a6_portfolio_priority_and_slots/w2a6_scheme_compare.csv")
    add_df(
        "W2A6_priority_schemes", df6a,
        lambda r: f"{r.module}::{r.scheme_id}",
        lambda r: "combined_v20",
        "sharpe_wf", "nav_wf", "n_wf", "perm_sd_p_wf", None,
    )

    # W2B1
    dfb1 = pd.read_csv(f"{BASE}/wave2b/w2b1_20cm_surge10_19_scorecard/w2b1_scorecard_grid.csv")
    add_df(
        "W2B1_20cm_surge", dfb1,
        lambda r: f"{r.track}::{r.pool}::{r.entry}::{r.exit_rule}::{r.mine_mode}::k{r.top_k}::{r.recalc_freq}::{r.threshold}",
        lambda r: "standalone_new",
        "sharpe", "nav_wf", "n_trades", "perm_sd_p", "perm_any_p",
    )

    # W2B2
    dfb2 = pd.read_csv(f"{BASE}/wave2b/w2b2_rebound_wave2_temp5b_scorecard/w2b2_tracks_compare.csv")
    add_df("W2B2_temp5b", dfb2, lambda r: f"{r.track}::{r.threshold}", lambda r: "standalone_new", "sharpe", "nav_wf", "n_trades", "perm_sd_p", "perm_any_p")

    # W2B3
    dfb3 = pd.read_csv(f"{BASE}/wave2b/w2b3_theme_pullback_laggard_scorecard/w2b3_tracks_compare.csv")
    add_df("W2B3_pullback_laggard", dfb3, lambda r: f"{r.variant}::{r.recalc_freq}::{r.threshold}", lambda r: "standalone_new", "sharpe", "nav_wf", "n_trades", "perm_sd_p_nav", "perm_any_p_nav")

    # W2B4
    dfb4 = pd.read_csv(f"{BASE}/wave2b/w2b4_20cm_new_archetypes_scorecard/w2b4_tracks_compare.csv")
    add_df("W2B4_20cm_new_arch", dfb4, lambda r: f"{r.track_id}::{r.threshold}", lambda r: "standalone_new", "sharpe", "nav_wf", "n_trades", "perm_sd_p", "perm_any_p")

    # W2B5
    dfb5 = pd.read_csv(f"{BASE}/wave2b/w2b5_event_crossmarket_lowcorr_scorecard/w2b5_tracks_compare.csv")
    add_df(
        "W2B5_event_crossmkt", dfb5,
        lambda r: f"{r.track}::{r.variant}::{r.threshold}",
        lambda r: "combined_v20" if "V20_Baseline" in str(r.variant) else "standalone_new",
        "sharpe_wf", "nav_wf", "n_trades_wf", "perm_sd_p", "perm_any_p",
    )

    # W2B6
    dfb6 = pd.read_csv(f"{BASE}/wave2b/w2b6_empty_slot_blind_and_crossseat/w2b6_tracks_compare.csv")
    add_df("W2B6_blind_crossseat", dfb6, lambda r: f"{r.track_id}::{r.recalc_freq}::{r.threshold}", lambda r: "standalone_new", "sharpe_wf", "nav_wf", "n_trades_wf", "perm_sd_p", "perm_any_p")

    all_df = pd.DataFrame(records)
    # Compute Sharpe-based one-sided p-value (daily SR * sqrt(T-1))
    sr_daily = all_df["sharpe_ann"] / math.sqrt(TRD_DAYS_YEAR)
    z_stat = sr_daily * math.sqrt(WF_DAYS - 1)
    all_df["sr_t_pval"] = [1.0 - norm_cdf(float(z)) if np.isfinite(z) else np.nan for z in z_stat]

    all_df["q_bh_sr_all"] = bh_fdr(all_df["sr_t_pval"].to_numpy(float))
    all_df["q_bh_perm_sd_all"] = bh_fdr(all_df["perm_sd_p"].to_numpy(float))
    all_df["q_bh_perm_any_all"] = bh_fdr(all_df["perm_any_p"].to_numpy(float))

    # Separate standalone vs all
    standalone_mask = all_df["scope"].isin(["standalone_leg", "standalone_new"]).to_numpy()
    new_only_mask = (all_df["scope"] == "standalone_new").to_numpy()

    all_df["q_bh_sr_standalone"] = np.nan
    all_df.loc[standalone_mask, "q_bh_sr_standalone"] = bh_fdr(all_df.loc[standalone_mask, "sr_t_pval"].to_numpy(float))
    all_df["q_bh_perm_sd_standalone"] = np.nan
    all_df.loc[standalone_mask, "q_bh_perm_sd_standalone"] = bh_fdr(all_df.loc[standalone_mask, "perm_sd_p"].to_numpy(float))
    all_df["q_bh_perm_any_standalone"] = np.nan
    all_df.loc[standalone_mask, "q_bh_perm_any_standalone"] = bh_fdr(all_df.loc[standalone_mask, "perm_any_p"].to_numpy(float))

    meta = {
        "module_counts_main_tables": module_counts,
        "n_trials_main_tables": int(len(all_df)),
        "n_trials_extra_unlisted": {
            "W2A2_extra_loo_not_in_table": 49,
            "W2A6_priority_permutations_720x2": 1440,
            "W2B1_mine_removal_combos": 96,
            "W2A4_dyn20x19_daily_pair_search": 950,
        },
        "n_trials_including_w2a2loo_and_w2a6perms": int(len(all_df) + 49 + 1440),
        "n_trials_standalone_only": int(standalone_mask.sum()),
        "n_trials_new_tracks_only": int(new_only_mask.sum()),
        "sharpe_distribution": {
            "all_5456": {
                "n": int(all_df["sharpe_ann"].notna().sum()),
                "mean_ann": round(float(all_df["sharpe_ann"].mean()), 4),
                "var_ann": round(float(all_df["sharpe_ann"].var(ddof=1)), 4),
                "var_daily": round(float((all_df["sharpe_ann"] / math.sqrt(TRD_DAYS_YEAR)).var(ddof=1)), 6),
                "sr0_ann_euler_mascheroni": round(
                    float(
                        math.sqrt(all_df["sharpe_ann"].var(ddof=1))
                        * ((1 - 0.5772156649) * 3.553 + 0.5772156649 * 3.796)
                    ), 4
                ),
            },
            "standalone_only": {
                "n": int(all_df.loc[standalone_mask, "sharpe_ann"].notna().sum()),
                "mean_ann": round(float(all_df.loc[standalone_mask, "sharpe_ann"].mean()), 4),
                "var_ann": round(float(all_df.loc[standalone_mask, "sharpe_ann"].var(ddof=1)), 4),
                "var_daily": round(float((all_df.loc[standalone_mask, "sharpe_ann"] / math.sqrt(TRD_DAYS_YEAR)).var(ddof=1)), 6),
            },
            "new_tracks_only": {
                "n": int(all_df.loc[new_only_mask, "sharpe_ann"].notna().sum()),
                "mean_ann": round(float(all_df.loc[new_only_mask, "sharpe_ann"].mean()), 4),
                "var_ann": round(float(all_df.loc[new_only_mask, "sharpe_ann"].var(ddof=1)), 4),
                "var_daily": round(float((all_df.loc[new_only_mask, "sharpe_ann"] / math.sqrt(TRD_DAYS_YEAR)).var(ddof=1)), 6),
            },
        },
        "per_module_sharpe_stats": {
            mod: {
                "n": int(g["sharpe_ann"].notna().sum()),
                "mean_ann": round(float(g["sharpe_ann"].mean()), 4),
                "var_ann": round(float(g["sharpe_ann"].var(ddof=1)), 4) if len(g) > 1 else 0.0,
                "var_daily": round(float((g["sharpe_ann"] / math.sqrt(TRD_DAYS_YEAR)).var(ddof=1)), 6) if len(g) > 1 else 0.0,
                "max_ann": round(float(g["sharpe_ann"].max()), 4),
            }
            for mod, g in all_df.groupby("module")
        },
    }
    return all_df, meta


def main():
    all_df, meta = load_all_trials()
    all_df.to_parquet(f"{OUT_DIR}/_part1_all_trials_fdr.parquet", index=False)
    with open(f"{OUT_DIR}/_part1_global_stats.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"Total main table trials: {meta['n_trials_main_tables']} (with W2A6 1440 perms + W2A2 49 LOO = {meta['n_trials_including_w2a2loo_and_w2a6perms']})")
    print(f"Standalone trials: {meta['n_trials_standalone_only']} | New-track trials: {meta['n_trials_new_tracks_only']}")
    print("Sharpe dist:", json.dumps(meta["sharpe_distribution"], indent=2))
    print("\nFDR pass counts (q < 0.05 & q < 0.10):")
    for col in ["q_bh_sr_all", "q_bh_perm_sd_all", "q_bh_perm_any_all", "q_bh_sr_standalone", "q_bh_perm_sd_standalone", "q_bh_perm_any_standalone"]:
        s = all_df[col].dropna()
        print(f"  {col:26s}: nonna={len(s):4d}, q<0.05={(s<0.05).sum():4d}, q<0.10={(s<0.10).sum():4d}")


if __name__ == "__main__":
    main()

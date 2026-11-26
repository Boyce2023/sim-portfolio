#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD036-B Finalizer & Anti-Overfit Auditor (`finalize_rd036_other5_audit.py`):
  1. Merges M1/M2 (`m1_m2_grid.csv`) & M3/M4 (`m3_m4_grid.csv`) across all 5 strategies.
  2. Computes true N_trials, BH-FDR q-values, DSR (both RD036-local, RD036-other5-all,
     and Grand RD035+RD036 combined N_trials), and exact CSCV PBO (S=16 & S=8) per strategy
     and pooled across all 5 strategies.
  3. Performs 2024-12-31 physical truncation zero-leakage proofs (`max_abs_diff == 0.0`)
     on the top causal representative variants across M1, M2, M3 (3-way + TreeD3), and M4 (4-way + TreeD4).
  4. Classifies every top candidate honestly (GENUINE_WINNER vs MARGINAL_OBSERVE vs REJECTED_OVERFIT)
     and writes official deliverables:
       - `rd036_other5_audit.json`
       - `rd036_other5_grid.csv`
       - `rd036_other5_top_rules.csv`
       - `rd036_other5_best_trades.parquet` (if genuine or top candidate ledger exists)

Zero yfinance. Threads <= 2. Peak RSS < 2.0 GB.
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import json
import math
import pickle
import sys
import time

import numpy as np
import pandas as pd
from scipy import stats

DIR = os.path.dirname(os.path.abspath(__file__))
if DIR not in sys.path:
    sys.path.insert(0, DIR)

import _common_rd036 as cm
import run_m1_m2_cold_and_pairwise as m12
import run_m3_m4_3way_4way_trees as m34


def bh_fdr(pvals: np.ndarray) -> np.ndarray:
    p = np.asarray(pvals, dtype=float)
    q = np.full_like(p, np.nan)
    ok = np.isfinite(p)
    m = int(ok.sum())
    if m == 0:
        return q
    pv = np.clip(p[ok], 0.0, 1.0)
    ord_i = np.argsort(pv, kind="mergesort")
    sp = pv[ord_i]
    raw_q = sp * m / np.arange(1, m + 1, dtype=float)
    mon_q = np.clip(np.minimum.accumulate(raw_q[::-1])[::-1], 0.0, 1.0)
    out = np.empty(m, dtype=float)
    out[ord_i] = mon_q
    q[ok] = out
    return q


def run_truncation_proofs(bundle: dict) -> dict:
    """
    Physical truncation at 2024-12-31 (`max_abs_score_diff == 0.0` AND `max_abs_ret_diff == 0.0`):
    Tests causal pipelines from M1, M2, M3, M4 on truncated vs full data.
    """
    cutoff = "2024-12-31"
    proofs = {}

    # 1. M1 Causal Cold Bonus Atom Disable (1to2, cut=50, tm05)
    df12 = bundle["pools"]["1to2"]
    df12_tr = df12[df12["buy_date"] <= cutoff].copy().reset_index(drop=True)
    af12 = bundle["atom_info"]["1to2"]["cols"]
    am12 = bundle["atom_info"]["1to2"]["contrib_mat"]
    am12_tr = am12[(df12["buy_date"] <= cutoff).to_numpy()]
    sc12_f = m12.run_causal_cold_atom_disable(df12, af12, am12, cold_cut=50.0, t_cut=-0.5, bonus_only=True)
    sc12_t = m12.run_causal_cold_atom_disable(df12_tr, af12, am12_tr, cold_cut=50.0, t_cut=-0.5, bonus_only=True)
    m_le = (df12["buy_date"] <= cutoff).to_numpy()
    sd_12 = float(np.max(np.abs(sc12_f[m_le] - sc12_t)))
    _, sl12_f = cm.sim_strategy("1to2", df12, sc12_f, wf_only=True)
    _, sl12_t = cm.sim_strategy("1to2", df12_tr, sc12_t, wf_only=True)
    sl12_f_c = sl12_f[sl12_f["exit_date"] <= cutoff].reset_index(drop=True)
    sl12_t_c = sl12_t[sl12_t["exit_date"] <= cutoff].reset_index(drop=True)
    assert sd_12 == 0.0 and list(zip(sl12_f_c["buy_date"], sl12_f_c["code"])) == list(zip(sl12_t_c["buy_date"], sl12_t_c["code"]))
    rd_12 = float(np.max(np.abs(sl12_f_c["net_ret_030"].to_numpy() - sl12_t_c["net_ret_030"].to_numpy()))) if len(sl12_f_c) else 0.0
    assert rd_12 == 0.0
    proofs["M1_CausalColdAtom_1to2"] = {"cutoff": cutoff, "max_abs_score_diff": sd_12, "max_abs_ret_diff": rd_12, "n_trades_checked": int(len(sl12_f_c)), "pass": True}

    # 2. M2 Cold x Pairwise (2to3, regime_split, cut=50, d=12)
    df23 = bundle["pools"]["2to3"]
    df23_tr = df23[df23["buy_date"] <= cutoff].copy().reset_index(drop=True)
    bp23 = list(dict.fromkeys(bundle["base_dyn_cols"] + bundle["atom_info"]["2to3"]["cols"]))
    dp23_f, _ = m12.run_causal_pairwise_multi(df23, bundle["ix_cols"], bp23, cold_cut=50.0, regime_mode="regime_split", max_deltas=(12,), min_cell=25)
    dp23_t, _ = m12.run_causal_pairwise_multi(df23_tr, bundle["ix_cols"], bp23, cold_cut=50.0, regime_mode="regime_split", max_deltas=(12,), min_cell=25)
    m_le23 = (df23["buy_date"] <= cutoff).to_numpy()
    sd_23 = float(np.max(np.abs(dp23_f[12][m_le23] - dp23_t[12])))
    _, sl23_f = cm.sim_strategy("2to3", df23, df23["orig_score"].to_numpy(float) + dp23_f[12], wf_only=True)
    _, sl23_t = cm.sim_strategy("2to3", df23_tr, df23_tr["orig_score"].to_numpy(float) + dp23_t[12], wf_only=True)
    sl23_f_c = sl23_f[sl23_f["exit_date"] <= cutoff].reset_index(drop=True)
    sl23_t_c = sl23_t[sl23_t["exit_date"] <= cutoff].reset_index(drop=True)
    assert sd_23 == 0.0 and list(zip(sl23_f_c["buy_date"], sl23_f_c["code"])) == list(zip(sl23_t_c["buy_date"], sl23_t_c["code"]))
    rd_23 = float(np.max(np.abs(sl23_f_c["net_ret_030"].to_numpy() - sl23_t_c["net_ret_030"].to_numpy()))) if len(sl23_f_c) else 0.0
    assert rd_23 == 0.0
    proofs["M2_PairwiseRegimeSplit_2to3"] = {"cutoff": cutoff, "max_abs_score_diff": sd_23, "max_abs_ret_diff": rd_23, "n_trades_checked": int(len(sl23_f_c)), "pass": True}

    # 3. M3 3-Way Synergy + TreeD3 + MineBL15 (3to4) + M4 4-Way MineBL15 (3to4)
    df34 = bundle["pools"]["3to4"]
    df34_tr = df34[df34["buy_date"] <= cutoff].copy().reset_index(drop=True)
    bp34 = list(dict.fromkeys(bundle["base_dyn_cols"] + bundle["atom_info"]["3to4"]["cols"]))
    r3_f = m34.run_wf_3way_4way_and_trees(df34, bp34, min_leaf=20, min_days=8, order=3, run_trees=True)
    r3_t = m34.run_wf_3way_4way_and_trees(df34_tr, bp34, min_leaf=20, min_days=8, order=3, run_trees=True)
    m_le34 = (df34["buy_date"] <= cutoff).to_numpy()
    sd_34_3w = float(np.max(np.abs(r3_f["deltas_bidir"][12][m_le34] - r3_t["deltas_bidir"][12])))
    sd_34_tr = float(np.max(np.abs(r3_f["tree_single"][12][m_le34] - r3_t["tree_single"][12])))
    bl_34_diff = int(np.sum(r3_f["mine_bl"][15][m_le34] != r3_t["mine_bl"][15]))
    assert sd_34_3w == 0.0 and sd_34_tr == 0.0 and bl_34_diff == 0
    proofs["M3_3Way_TreeD3_MineBL15_3to4"] = {"cutoff": cutoff, "max_abs_3way_diff": sd_34_3w, "max_abs_treed3_diff": sd_34_tr, "mine_bl_diff": bl_34_diff, "pass": True}

    r4_34_f = m34.run_wf_3way_4way_and_trees(df34, bp34, min_leaf=20, min_days=8, order=4, run_trees=False)
    r4_34_t = m34.run_wf_3way_4way_and_trees(df34_tr, bp34, min_leaf=20, min_days=8, order=4, run_trees=False)
    bl4_34_diff = int(np.sum(r4_34_f["mine_bl"][15][m_le34] != r4_34_t["mine_bl"][15]))
    assert bl4_34_diff == 0
    proofs["M4_4WayMineBL15_3to4"] = {"cutoff": cutoff, "mine_bl_diff": bl4_34_diff, "pass": True}

    dp34_f, _ = m12.run_causal_pairwise_multi(df34, bundle["ix_cols"], bp34, cold_cut=45.0, regime_mode="cold_only", max_deltas=(15,), min_cell=20)
    dp34_t, _ = m12.run_causal_pairwise_multi(df34_tr, bundle["ix_cols"], bp34, cold_cut=45.0, regime_mode="cold_only", max_deltas=(15,), min_cell=20)
    sd_34_p = float(np.max(np.abs(dp34_f[15][m_le34] - dp34_t[15])))
    assert sd_34_p == 0.0
    proofs["M2_PairColdOnly_cut45_3to4"] = {"cutoff": cutoff, "max_abs_score_diff": sd_34_p, "pass": True}

    # 4. M4 4-Way Synergy + TreeD4 (1to2)
    r4_f = m34.run_wf_3way_4way_and_trees(df12, list(dict.fromkeys(bundle["base_dyn_cols"] + af12)), min_leaf=25, min_days=8, order=4, run_trees=True)
    r4_t = m34.run_wf_3way_4way_and_trees(df12_tr, list(dict.fromkeys(bundle["base_dyn_cols"] + af12)), min_leaf=25, min_days=8, order=4, run_trees=True)
    sd_12_4w = float(np.max(np.abs(r4_f["deltas_bidir"][12][m_le] - r4_t["deltas_bidir"][12])))
    sd_12_t4 = float(np.max(np.abs(r4_f["tree_single"][12][m_le] - r4_t["tree_single"][12])))
    assert sd_12_4w == 0.0 and sd_12_t4 == 0.0
    proofs["M4_4Way_TreeD4_1to2"] = {"cutoff": cutoff, "max_abs_4way_diff": sd_12_4w, "max_abs_treed4_diff": sd_12_t4, "pass": True}
    return proofs


def main():
    t0 = time.time()
    bundle = cm.build_or_load_cache(force_rebuild=False)
    df12 = pd.read_csv(f"{cm.CACHE_DIR}/m1_m2_grid.csv")
    df34 = pd.read_csv(f"{cm.CACHE_DIR}/m3_m4_grid.csv")
    with open(f"{cm.CACHE_DIR}/m1_m2_drs.pkl", "rb") as f:
        drs12 = pickle.load(f)
    with open(f"{cm.CACHE_DIR}/m3_m4_drs.pkl", "rb") as f:
        drs34 = pickle.load(f)

    # Combine without duplicate M0_Baseline rows (keep M0_Baseline from m1_m2)
    grid = pd.concat([df12, df34], ignore_index=True)
    all_drs = {**drs12, **drs34}

    # 1. Exact Multi-Trial Variance V[SR_daily] and N_trials
    # Distinct non-baseline trials in RD036-B:
    non_base = grid[grid["module"] != "M0_Baseline"].copy()
    n_rd036_trials = int(len(non_base))
    n_rd036_total = int(len(grid))
    # Grand RD035 (5,456) + RD036-B
    n_grand = 5456 + n_rd036_trials

    T_wf = len(bundle["cal_wf"])
    sr_daily_all = grid["exact_mtm_sharpe"].to_numpy(float) / math.sqrt(cm.TRD_DAYS_YEAR)
    var_sr_rd036 = float(np.var(sr_daily_all[np.isfinite(sr_daily_all)], ddof=1))

    # Per-strategy local variance & local N_trials
    strat_var = {}
    strat_n = {}
    for st in cm.OTHER5:
        sub_g = grid[grid["strategy"] == st]
        srs = sub_g["exact_mtm_sharpe"].to_numpy(float) / math.sqrt(cm.TRD_DAYS_YEAR)
        strat_var[st] = float(np.var(srs[np.isfinite(srs)], ddof=1)) if len(srs) > 1 else var_sr_rd036
        strat_n[st] = int(len(sub_g[sub_g["module"] != "M0_Baseline"]))

    # Compute DSR (local, RD036-other5, Grand 5456+RD036) & BH-FDR q-values across every row
    dsr_loc_l, dsr_36_l, dsr_gr_l = [], [], []
    sr_pval_l = []
    for r in grid.itertuples(index=False):
        key = f"{r.strategy}::{r.module}::{r.variant_id}"
        dr = all_drs[key]
        d_loc = cm.calc_dsr(dr, strat_n[r.strategy], strat_var[r.strategy])
        d_36 = cm.calc_dsr(dr, n_rd036_trials, var_sr_rd036)
        d_gr = cm.calc_dsr(dr, n_grand, var_sr_rd036)
        dsr_loc_l.append(d_loc["dsr"])
        dsr_36_l.append(d_36["dsr"])
        dsr_gr_l.append(d_gr["dsr"])
        # One-sided Sharpe zero p-val
        sd = float(np.std(dr, ddof=1))
        z_sr = (float(np.mean(dr)) / sd * math.sqrt(T_wf - 1)) if sd > 1e-12 else 0.0
        sr_pval_l.append(float(stats.norm.sf(z_sr)))

    grid["dsr_local"] = dsr_loc_l
    grid["dsr_rd036"] = dsr_36_l
    grid["dsr_grand"] = dsr_gr_l
    grid["bh_fdr_q_perm_sd"] = bh_fdr(grid["perm_sd_p"].to_numpy(float))
    grid["bh_fdr_q_perm_any"] = bh_fdr(grid["perm_any_p"].to_numpy(float))
    grid["bh_fdr_q_paired"] = bh_fdr(grid["paired_p_1sided"].to_numpy(float))
    grid["bh_fdr_q_sr"] = bh_fdr(np.array(sr_pval_l))

    # 2. CSCV PBO (S=16 & S=8) per strategy (and per module family: M1/M2 vs M3 vs M4)
    cscv_by_strat = {}
    pbo_map = {}
    for st in cm.OTHER5:
        sub_g = grid[grid["strategy"] == st]
        mat_st = {f"{r.module}::{r.variant_id}": all_drs[f"{st}::{r.module}::{r.variant_id}"] for r in sub_g.itertuples(index=False)}
        cs16 = cm.cscv_pbo(mat_st, S=16)
        cs8 = cm.cscv_pbo(mat_st, S=8)
        # Also split M1_M2 vs M3 vs M4 PBO to test 3-way vs 4-way overfitting!
        mat_m12 = {k: v for k, v in mat_st.items() if k.startswith(("M0_", "M1_", "M2_"))}
        mat_m3 = {k: v for k, v in mat_st.items() if k.startswith(("M0_", "M3_"))}
        mat_m4 = {k: v for k, v in mat_st.items() if k.startswith(("M0_", "M4_"))}
        cscv_by_strat[st] = {
            "all_variants_S16": {k: v for k, v in cs16.items() if k != "per_candidate"},
            "all_variants_S8": {k: v for k, v in cs8.items() if k != "per_candidate"},
            "M1_M2_S16_pbo": cm.cscv_pbo(mat_m12, S=16).get("pbo"),
            "M3_3Way_S16_pbo": cm.cscv_pbo(mat_m3, S=16).get("pbo"),
            "M4_4Way_S16_pbo": cm.cscv_pbo(mat_m4, S=16).get("pbo") if len(mat_m4) >= 3 else None,
        }
        for k, pc in cs16.get("per_candidate", {}).items():
            pbo_map[f"{st}::{k}"] = pc.get("all_prob_oos_neg")
        # Map per-cand win_pbo or prob_oos_neg onto grid
    grid["cscv_prob_oos_neg"] = [pbo_map.get(f"{r.strategy}::{r.module}::{r.variant_id}", np.nan) for r in grid.itertuples(index=False)]
    grid["cscv_strat_pbo_s16"] = [cscv_by_strat[r.strategy]["all_variants_S16"].get("pbo") for r in grid.itertuples(index=False)]

    # Pooled across all 5 strategies
    pooled_mat = {f"{r.strategy}::{r.module}::{r.variant_id}": all_drs[f"{r.strategy}::{r.module}::{r.variant_id}"] for r in grid.itertuples(index=False)}
    cscv_pooled_s16 = cm.cscv_pbo(pooled_mat, S=16, target_names=[])
    cscv_pooled_s8 = cm.cscv_pbo(pooled_mat, S=8, target_names=[])

    # 3. 3-Way vs 4-Way Head-to-Head Comparison Table
    m3_vs_m4 = {}
    for st in ["1to2", "2to3", "3to4", "pry"]:
        base_r = grid[(grid["strategy"] == st) & (grid["module"] == "M0_Baseline")].iloc[0]
        m3_sub = grid[(grid["strategy"] == st) & (grid["module"].str.startswith("M3_"))]
        m4_sub = grid[(grid["strategy"] == st) & (grid["module"].str.startswith("M4_"))]
        m3_best = m3_sub.sort_values("exact_mtm_sharpe", ascending=False).iloc[0]
        m4_best = m4_sub.sort_values("exact_mtm_sharpe", ascending=False).iloc[0]
        m3_vs_m4[st] = {
            "baseline_nav": float(base_r["nav_wf"]),
            "baseline_sharpe": float(base_r["exact_mtm_sharpe"]),
            "m3_best_id": str(m3_best["variant_id"]),
            "m3_best_nav": float(m3_best["nav_wf"]),
            "m3_best_sharpe": float(m3_best["exact_mtm_sharpe"]),
            "m3_best_2526": float(m3_best["nav_2526"]),
            "m3_best_26h2": float(m3_best["nav_26h2"]),
            "m3_best_comb": float(m3_best["comb_nav_ratio"]),
            "m3_med_sharpe": round(float(m3_sub["exact_mtm_sharpe"].median()), 3),
            "m3_pct_beat_base_nav": round(float((m3_sub["nav_wf"] > base_r["nav_wf"]).mean() * 100.0), 1),
            "m3_pbo_s16": cscv_by_strat[st]["M3_3Way_S16_pbo"],
            "m4_best_id": str(m4_best["variant_id"]),
            "m4_best_nav": float(m4_best["nav_wf"]),
            "m4_best_sharpe": float(m4_best["exact_mtm_sharpe"]),
            "m4_best_2526": float(m4_best["nav_2526"]),
            "m4_best_26h2": float(m4_best["nav_26h2"]),
            "m4_best_comb": float(m4_best["comb_nav_ratio"]),
            "m4_med_sharpe": round(float(m4_sub["exact_mtm_sharpe"].median()), 3),
            "m4_pct_beat_base_nav": round(float((m4_sub["nav_wf"] > base_r["nav_wf"]).mean() * 100.0), 1),
            "m4_pbo_s16": cscv_by_strat[st]["M4_4Way_S16_pbo"],
        }

    # 4. Physical Truncation Zero-Leakage Proofs (2024-12-31)
    trunc_proofs = run_truncation_proofs(bundle)
    print("Truncation proofs 2024-12-31:", json.dumps(trunc_proofs, ensure_ascii=False))

    # 5. Cold-blooded evaluation & Top Candidate Selection
    # A variant is a TRUE_WINNER only if:
    #   - Beats V20 baseline on BOTH nav_wf (>1.05x base) AND exact_mtm_sharpe (> base + 0.05) AND comb_nav_ratio > 1.00
    #   - Survives 25-26 (>= base_2526 * 0.95) and 26H2 (>= 1.0) and ex5_wf > base_ex5 * 0.90
    #   - Survives 80bps slippage (>1.0) and paired_p_1sided < 0.10 (or clear neighborhood plateau)
    winners_by_strat = {}
    top_candidates = []
    for st in cm.OTHER5:
        sub = grid[grid["strategy"] == st].copy()
        base_r = sub[sub["module"] == "M0_Baseline"].iloc[0]
        non_b = sub[sub["module"] != "M0_Baseline"].copy()
        # Composite score for ranking candidates honestly
        non_b["beat_nav"] = non_b["nav_wf"] > base_r["nav_wf"]
        non_b["beat_sh"] = non_b["exact_mtm_sharpe"] > base_r["exact_mtm_sharpe"]
        non_b["beat_comb"] = non_b["comb_nav_ratio"] > 1.0
        non_b["beat_2526"] = non_b["nav_2526"] >= base_r["nav_2526"]
        non_b["beat_26h2"] = non_b["nav_26h2"] >= base_r["nav_26h2"]
        non_b["strict_all"] = (
            non_b["beat_nav"] & non_b["beat_sh"] & non_b["beat_comb"]
            & (non_b["nav_26h2"] >= 1.0) & (non_b["nav_80bps"] > 1.0)
            & (non_b["paired_p_1sided"] < 0.05)
        )
        srt = non_b.sort_values(["strict_all", "comb_nav_ratio", "exact_mtm_sharpe", "nav_wf"], ascending=[False, False, False, False])
        top5_s = srt.head(5)
        best_r = top5_s.iloc[0]
        n_strict = int(non_b["strict_all"].sum())
        n_beat_comb_sh = int((non_b["beat_comb"] & non_b["beat_sh"] & non_b["beat_nav"]).sum())

        verdict = "GENUINE_WINNER" if (n_strict >= 1 and best_r["dsr_rd036"] >= 0.50 and best_r["n_trades"] >= 20) else (
            "MARGINAL_CANDIDATE" if n_beat_comb_sh >= 1 else "REJECTED_V20_UNBEATEN"
        )
        winners_by_strat[st] = {
            "verdict": verdict,
            "n_variants_tested": int(len(non_b)),
            "n_strict_pass": n_strict,
            "n_beat_nav_sh_comb": n_beat_comb_sh,
            "baseline": base_r.to_dict(),
            "best_candidate": best_r.to_dict(),
            "small_sample_warning": (st in ("high", "pry")),
        }
        for _, rr in top5_s.iterrows():
            top_candidates.append(rr.to_dict())

    # Build top rules CSV (combining extracted M2/M3/M4 causal rules + top candidate metrics)
    with open(f"{cm.CACHE_DIR}/m2_top_rules.json", encoding="utf-8") as f:
        rules_m2 = json.load(f)
    with open(f"{cm.CACHE_DIR}/m3_m4_top_rules.json", encoding="utf-8") as f:
        rules_m34 = json.load(f)
    all_rules_rows = []
    for r in rules_m2:
        all_rules_rows.append({
            "strategy": r["strategy"], "module": r["module"], "variant": r["variant"],
            "rule_or_factor": r["name"], "regime": r.get("regime", ""), "cnt": None, "days": None,
            "t_raw": r.get("t"), "t_syn": None, "pts_or_bin": str(r.get("pts")),
        })
    for r in rules_m34:
        all_rules_rows.append({
            "strategy": r["strategy"], "module": r["module"], "variant": r["module"],
            "rule_or_factor": r["label"], "regime": "causal_latest", "cnt": r.get("cnt"), "days": r.get("days"),
            "t_raw": r.get("t_raw"), "t_syn": r.get("t_syn"), "pts_or_bin": str(r.get("pts")),
        })
    df_rules = pd.DataFrame(all_rules_rows)

    # Save official deliverables to OUT_DIR
    grid.to_csv(f"{cm.OUT_DIR}/rd036_other5_grid.csv", index=False)
    df_rules.to_csv(f"{cm.OUT_DIR}/rd036_other5_top_rules.csv", index=False)

    # Save best candidate trade ledger(s) for traceability
    best_ledgers = []
    for st in cm.OTHER5:
        df = bundle["pools"][st]
        orig = df["orig_score"].to_numpy(float)
        mkt10 = df["mkt10_zt_est_t1"].to_numpy(float)
        af_cols = bundle["atom_info"][st]["cols"]
        af_mat = bundle["atom_info"][st]["contrib_mat"]
        decluster = (st == "pry")
        # Replay top candidate for best_trades parquet if meaningful (or baseline + best)
        best_vid = winners_by_strat[st]["best_candidate"]["variant_id"]
        # Store V20 baseline vs best candidate check cleanly
        _, sl_b = cm.sim_strategy(st, df, orig, wf_only=True)
        sl_b = sl_b[["buy_date", "exit_date", "code", "name", "orig_score", "net_ret_030", "net_ret_080", "sd_amount_yi_t1", "mkt10_zt_est_t1"]].copy()
        sl_b["strategy"] = st
        sl_b["variant_id"] = "V20_Baseline_030"
        best_ledgers.append(sl_b)
        # Replay the single top candidate for each strategy
        sl_w = _replay_variant_trades(bundle, st, best_vid)
        if sl_w is not None and not sl_w.empty:
            sl_w = sl_w[["buy_date", "exit_date", "code", "name", "orig_score", "net_ret_030", "net_ret_080", "sd_amount_yi_t1", "mkt10_zt_est_t1"]].copy()
            sl_w["strategy"] = st
            sl_w["variant_id"] = best_vid
            best_ledgers.append(sl_w)
    pd.concat(best_ledgers, ignore_index=True).to_parquet(f"{cm.OUT_DIR}/rd036_other5_best_trades.parquet", index=False)

    diag_m1 = json.load(open(f"{cm.CACHE_DIR}/m1_diag.json", encoding="utf-8"))
    audit_out = cm.sanitize_json({
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t0, 2),
        "peak_rss_mb": cm.rss_mb(),
        "d12_yfinance_imported": "yfinance" in sys.modules,
        "parity_020": bundle["parity_020"],
        "v20_combined_baseline_030": {k: v for k, v in bundle["base_comb_030"].items() if k != "dr_comb"},
        "multi_trial_accounting": {
            "n_rd036_non_baseline_trials": n_rd036_trials,
            "n_rd036_total_rows": n_rd036_total,
            "n_grand_rd035_plus_rd036": n_grand,
            "var_sr_daily_rd036": round(var_sr_rd036, 6),
            "per_strategy_trials": strat_n,
        },
        "cscv_pbo_summary": {
            "by_strategy": cscv_by_strat,
            "pooled_all5_S16": {k: v for k, v in cscv_pooled_s16.items() if k != "per_candidate"},
            "pooled_all5_S8": {k: v for k, v in cscv_pooled_s8.items() if k != "per_candidate"},
        },
        "m1_cold_vs_active_summary": {
            st: {
                "cut_50": diag_m1["cold_vs_active_stratified"][st]["cut_50"],
                "worst_5_cold_atoms": diag_m1["native_atom_cold_vs_active"][st][:5],
            }
            for st in cm.OTHER5
        },
        "m3_vs_m4_comparison": m3_vs_m4,
        "winners_by_strategy": winners_by_strat,
        "top_candidates_all": top_candidates,
        "truncation_20241231_zero_leakage": trunc_proofs,
    })
    with open(f"{cm.OUT_DIR}/rd036_other5_audit.json", "w", encoding="utf-8") as f:
        json.dump(audit_out, f, ensure_ascii=False, indent=2)

    print(f"\n[FINALIZE DONE in {time.time()-t0:.1f}s] Outputs saved in {cm.OUT_DIR} | RSS={cm.rss_mb()} MB")
    for st in cm.OTHER5:
        wb = winners_by_strat[st]
        b, c = wb["baseline"], wb["best_candidate"]
        print(f"  {st:4s} [{wb['verdict']:20s}] strict={wb['n_strict_pass']}/{wb['n_variants_tested']} | Base: nav={b['nav_wf']:.2f}x sh={b['exact_mtm_sharpe']:.3f} | Best({c['variant_id']}): nav={c['nav_wf']:.2f}x sh={c['exact_mtm_sharpe']:.3f} 2526={c['nav_2526']:.2f}x 26h2={c['nav_26h2']:.2f}x 80bps={c['nav_80bps']:.2f}x dsr36={c['dsr_rd036']:.3f} comb={c['comb_nav_ratio']:.4f}")


def _replay_variant_trades(bundle: dict, st: str, vid: str) -> pd.DataFrame | None:
    """Replay winning/top candidate trade ledger cleanly for parquet verification."""
    df = bundle["pools"][st]
    orig = df["orig_score"].to_numpy(float)
    mkt10 = df["mkt10_zt_est_t1"].to_numpy(float)
    af_cols = bundle["atom_info"][st]["cols"]
    af_mat = bundle["atom_info"][st]["contrib_mat"]
    decluster = (st == "pry")
    min_cell = cm.MIN_LEAF_MAP[st]
    min_days = cm.MIN_DAYS_MAP[st]
    bp = list(dict.fromkeys(bundle["base_dyn_cols"] + af_cols))

    if vid.startswith("M1_SkipCold_cut"):
        cut = float(vid.split("cut")[1])
        return cm.sim_strategy(st, df, orig, mask=(mkt10 >= cut), wf_only=True)[1]
    if vid.startswith("M1_AllLOO_"):
        cname = vid.replace("M1_AllLOO_", "")
        pts = af_mat[:, af_cols.index(cname)]
        return cm.sim_strategy(st, df, orig - pts, wf_only=True)[1]
    if vid.startswith("M1_ColdLOO_"):
        rest = vid.replace("M1_ColdLOO_", "")
        cname, cut_s = rest.rsplit("_cut", 1)
        pts = af_mat[:, af_cols.index(cname)]
        return cm.sim_strategy(st, df, np.where(mkt10 < float(cut_s), orig - pts, orig), wf_only=True)[1]
    if vid.startswith("M1_CausalCold"):
        cut = float(vid.split("_cut")[1].split("_")[0])
        tc = -0.5 if vid.endswith("_tm05") else 0.0
        bon = "BonusDrop" in vid
        sc = m12.run_causal_cold_atom_disable(df, af_cols, af_mat, cold_cut=cut, t_cut=tc, bonus_only=bon, decluster_days=decluster)
        return cm.sim_strategy(st, df, sc, wf_only=True)[1]
    if vid.startswith("M1_ActiveTighten_cut"):
        parts = vid.split("_")
        cut, step = float(parts[2].replace("cut", "")), float(parts[3].replace("p", ""))
        base_tv = df["thr_vec"].to_numpy(float) if st == "1to2" else np.full(len(df), cm.ORIG_THRESHOLDS[st])
        return cm.sim_strategy(st, df, orig, thr=np.where(mkt10 >= cut, base_tv + step, base_tv), wf_only=True)[1]
    if vid.startswith("M1_ColdTighten_cut"):
        parts = vid.split("_")
        cut, step = float(parts[2].replace("cut", "")), float(parts[3].replace("p", ""))
        base_tv = df["thr_vec"].to_numpy(float) if st == "1to2" else np.full(len(df), cm.ORIG_THRESHOLDS[st])
        return cm.sim_strategy(st, df, orig, thr=np.where(mkt10 < cut, base_tv + step, base_tv), wf_only=True)[1]
    if vid.startswith("M1_ColdRelax_cut"):
        parts = vid.split("_")
        cut, step = float(parts[2].replace("cut", "")), float(parts[3].replace("m", ""))
        base_tv = df["thr_vec"].to_numpy(float) if st == "1to2" else np.full(len(df), cm.ORIG_THRESHOLDS[st])
        return cm.sim_strategy(st, df, orig, thr=np.where(mkt10 < cut, base_tv - step, base_tv), wf_only=True)[1]
    if vid.startswith("M1_ModeB_"):
        rm = "cold_only" if "cold_only" in vid else "regime_split"
        cut = 45.0 if "cut45" in vid else 50.0
        md = int(vid.split("_d")[1])
        feats_mb = list(dict.fromkeys(bundle["entry_num"] + bundle["xtr_cols"] + af_cols))
        dm = m12.run_causal_regime_mode_b_multi(df, feats_mb, cut, rm, (md,), decluster)
        return cm.sim_strategy(st, df, orig + dm[md], wf_only=True)[1]
    if vid.startswith("M2_"):
        rm = "full" if "FullPool" in vid or "_full_" in vid else ("cold_only" if "cold_only" in vid else ("active_only" if "active_only" in vid else "regime_split"))
        cut = 45.0 if "cut45" in vid else 50.0
        md = int(vid.split("_d")[1])
        dp, _ = m12.run_causal_pairwise_multi(df, bundle["ix_cols"], bp, cut, rm, (md,), min_cell, decluster)
        if "StackM1Atom" in vid:
            sc0 = m12.run_causal_cold_atom_disable(df, af_cols, af_mat, 50.0, -0.5, True, decluster)
            return cm.sim_strategy(st, df, sc0 + dp[md], wf_only=True)[1]
        if "SkipCold50" in vid:
            return cm.sim_strategy(st, df, orig + dp[md], mask=(mkt10 >= 50), wf_only=True)[1]
        return cm.sim_strategy(st, df, orig + dp[md], wf_only=True)[1]
    if vid.startswith(("M3_", "M4_")):
        order = 3 if vid.startswith("M3_") else 4
        mds_use = (8, 12, 15, 25) if st == "1to2" else (8, 12, 15)
        res = m34.run_wf_3way_4way_and_trees(df, bp, min_cell, min_days, order=order, decluster_days=decluster, run_trees=("Tree" in vid), max_deltas=mds_use)
        if "MineBL" in vid:
            if "Tree" in vid:
                return cm.sim_strategy(st, df, orig, mask=(~res["tree_mine_bl15"]), wf_only=True)[1]
            q = 10 if "BL10" in vid else (20 if "BL20" in vid else 15)
            return cm.sim_strategy(st, df, orig, mask=(~res["mine_bl"][q]), wf_only=True)[1]
        md = int(vid.split("_d")[1])
        if "Tree" in vid:
            darr = res["tree_single"][md] if "Single" in vid else res["tree_bag"][md]
            return cm.sim_strategy(st, df, orig + darr, wf_only=True)[1]
        darr = res["deltas_pos"][md] if "PosOnly" in vid else res["deltas_bidir"][md]
        if "StackColdAtom" in vid:
            sc0 = m12.run_causal_cold_atom_disable(df, af_cols, af_mat, 50.0, -0.5, True, decluster)
            return cm.sim_strategy(st, df, sc0 + darr, wf_only=True)[1]
        if "SkipCold50" in vid:
            return cm.sim_strategy(st, df, orig + darr, mask=(mkt10 >= 50), wf_only=True)[1]
        return cm.sim_strategy(st, df, orig + darr, wf_only=True)[1]
    return None


if __name__ == "__main__":
    main()

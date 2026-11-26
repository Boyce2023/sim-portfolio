#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 2A-2 Modules 1 to 4:
  M1: Internal Atomic Factor Ablation (22 / 22 / 10) + Causal Dynamic Pruning & Reweighting
  M2: Cross-Strategy Transplant (`xtr_*` 37 cols) Mode A & Mode B
  M3: 334+ New Factors Mode B (+10/15/25) & Mode A (0..100), plus special `pry` sample-size & de-clustering tests
  M4: Physical Separation of Minefield (<= -7%) Scorecard vs Dragon-Hunting Scorecard
  + 2024-12-31 physical truncation zero-leakage proof (max_abs_diff == 0.0)

Zero yfinance (D12). Strict exit_date < t. 0.30% round-trip friction.
"""
import os
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

import json
import pickle
import resource
import sys
import time
import warnings
from typing import Optional

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
if CUR_DIR not in sys.path:
    sys.path.insert(0, CUR_DIR)

import _w2a2_common as cm
import _wf_core as wfc
import _wf_sim_and_metrics as wfm


def get_warmup_cfg(strat: str) -> dict:
    """Honest warmup config acknowledging sample sizes of 3to4(318), high(62), pry(759/79d)."""
    if strat == "high":
        return {"min_warmup_trades": 12, "min_warmup_trades_rare": 12, "min_warmup_months": 9, "min_warmup_days": 12}
    if strat == "pry":
        return {"min_warmup_trades": 80, "min_warmup_trades_rare": 60, "min_warmup_months": 12, "min_warmup_days": 20}
    return {"min_warmup_trades": 60, "min_warmup_trades_rare": 50, "min_warmup_months": 12, "min_warmup_days": 30}


def run_mode_b_custom(
    strat: str,
    df: pd.DataFrame,
    feature_cols: list[str],
    v20_ctx: dict,
    max_delta: int,
    max_corr_orig: Optional[float] = 0.70,
    top_k: int = 10,
    min_k: int = 4,
    use_declustered: bool = False,
    wf_start_date: str = "2023-01-03",
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    wcfg = get_warmup_cfg(strat)
    if use_declustered:
        scored_df, meta = cm.run_declustered_wf_loop(
            df, feature_cols, mode="delta_patch", wf_start_date=wf_start_date,
            min_warmup_trades=wcfg["min_warmup_trades_rare"], min_warmup_days=wcfg["min_warmup_days"],
            top_k=top_k, min_k=min_k, max_corr=0.65, min_t_stat=1.0, shrink_tau=10.0,
            max_delta=max_delta, orig_score_col="orig_score", max_corr_orig=max_corr_orig,
        )
    else:
        scored_df, meta = wfc.run_expanding_scorecard_loop(
            df, feature_cols=feature_cols, mode="delta_patch", wf_start_date=wf_start_date,
            min_warmup_trades=wcfg["min_warmup_trades"], min_warmup_trades_rare=wcfg["min_warmup_trades_rare"],
            min_warmup_months=wcfg["min_warmup_months"], recalc_freq="daily",
            top_k=top_k, min_k=min_k, max_corr=0.65, min_t_stat=1.0, shrink_tau=20.0,
            max_delta=max_delta, orig_score_col="orig_score", max_corr_orig=max_corr_orig,
            can_buy_mask=df["can_buy_hygiene"].to_numpy(bool),
        )
    pass_df, slot_df = cm.sim_strategy_custom(
        strat, scored_df, score_col="wf_new_score", threshold=cm.ORIG_THRESHOLDS[strat], wf_only=True
    )
    return scored_df, pass_df, slot_df, meta


def run_mode_a_custom(
    strat: str,
    df: pd.DataFrame,
    feature_cols: list[str],
    use_declustered: bool = False,
    wf_start_date: str = "2023-01-03",
    top_k: int = 12,
    min_k: int = 4,
) -> tuple[pd.DataFrame, dict]:
    wcfg = get_warmup_cfg(strat)
    if use_declustered:
        scored_df, meta = cm.run_declustered_wf_loop(
            df, feature_cols, mode="scorecard_0_100", wf_start_date=wf_start_date,
            min_warmup_trades=wcfg["min_warmup_trades_rare"], min_warmup_days=wcfg["min_warmup_days"],
            top_k=top_k, min_k=min_k, max_corr=0.65, min_t_stat=1.0, shrink_tau=10.0,
            orig_score_col="orig_score", max_corr_orig=None,
        )
    else:
        scored_df, meta = wfc.run_expanding_scorecard_loop(
            df, feature_cols=feature_cols, mode="scorecard_0_100", wf_start_date=wf_start_date,
            min_warmup_trades=wcfg["min_warmup_trades"], min_warmup_trades_rare=wcfg["min_warmup_trades_rare"],
            min_warmup_months=wcfg["min_warmup_months"], recalc_freq="daily",
            top_k=top_k, min_k=min_k, max_corr=0.65, min_t_stat=1.0, shrink_tau=20.0,
            can_buy_mask=df["can_buy_hygiene"].to_numpy(bool),
        )
    return scored_df, meta


def run_causal_neg_prune_atoms(
    strat: str,
    df: pd.DataFrame,
    af_cols: list[str],
    t_cut: float = 0.0,
    wf_start_date: str = "2023-01-03",
) -> tuple[pd.DataFrame, dict]:
    """
    Strictly causal (exit_date < t) atomic factor pruning:
    On each day t, compute cluster-robust t_cluster of each native atom af_j against u_util on exit_date < t.
    If t_cluster < t_cut, drop af_j from orig_score (score_pruned = orig_score - sum(dropped af_j)).
    """
    wcfg = get_warmup_cfg(strat)
    n = len(df)
    buy_dts = df["buy_date"].astype(str).str[:10].to_numpy()
    exit_dts = df["exit_date"].astype(str).str[:10].to_numpy()
    codes = df["code"].astype(str).str.zfill(6).to_numpy()
    y_ret = df["net_ret"].to_numpy(float)
    y_win = (y_ret > 0.0).astype(float)
    can_buy = df["can_buy_hygiene"].to_numpy(bool)

    uniq_dts = sorted(set(buy_dts.tolist()))
    dt_to_id = {d: i for i, d in enumerate(uniq_dts)}
    day_ids = np.array([dt_to_id[d] for d in buy_dts], dtype=np.int32)

    X_af = df[af_cols].fillna(0.0).to_numpy(float)
    orig = df["orig_score"].to_numpy(float)

    b_idx = np.where(can_buy)[0]
    ex_ord = np.asarray(sorted(b_idx.tolist(), key=lambda i: (exit_dts[i], buy_dts[i], codes[i])), dtype=np.int64)
    ex_dts = exit_dts[ex_ord]
    X_ex = X_af[ex_ord]
    r_ex = y_ret[ex_ord]
    w_ex = y_win[ex_ord]
    d_ex = day_ids[ex_ord]

    by_dt = {}
    for i in b_idx:
        by_dt.setdefault(buy_dts[i], []).append(i)

    wf_in = np.zeros(n, dtype=bool)
    pruned_sc = np.copy(orig)
    ptr, last_ptr, started, wf_actual_start = 0, -1, False, None
    keep_mask = np.ones(len(af_cols), dtype=bool)
    latest_t = {}

    for t in sorted(by_dt.keys()):
        while ptr < len(ex_ord) and ex_dts[ptr] < t:
            ptr += 1
        if t < wf_start_date:
            continue
        if not started:
            if ptr >= wcfg["min_warmup_trades_rare"]:
                started = True
                wf_actual_start = t
            else:
                continue
        if ptr > last_ptr:
            rv, wv, dv = r_ex[:ptr], w_ex[:ptr], d_ex[:ptr]
            mu0, wr0 = float(rv.mean()), float(wv.mean())
            sd_r = max(1e-5, float(rv.std(ddof=1)))
            u = 0.6 * (rv - mu0) / sd_r + 0.4 * (wv - wr0) / 0.25
            new_keep = np.ones(len(af_cols), dtype=bool)
            tmap = {}
            for j, cname in enumerate(af_cols):
                xj = X_ex[:ptr, j]
                # Use signed score contribution direction (higher af_j is supposed to improve return)
                t_val = wfc._cluster_t_stat(u, xj, dv)
                tmap[cname] = round(float(t_val), 3)
                if np.std(xj) > 1e-12 and t_val < t_cut:
                    new_keep[j] = False
            keep_mask = new_keep
            latest_t = tmap
            last_ptr = ptr

        rows_t = np.asarray(by_dt[t], dtype=np.int64)
        wf_in[rows_t] = True
        dropped = X_af[rows_t][:, ~keep_mask].sum(axis=1) if (~keep_mask).any() else 0.0
        pruned_sc[rows_t] = orig[rows_t] - dropped

    out = df.copy()
    out["wf_in_window"] = wf_in
    out["wf_pruned_score"] = np.where(wf_in, pruned_sc, np.nan)
    kept_names = [c for c, k in zip(af_cols, keep_mask) if k]
    dropped_names = [c for c, k in zip(af_cols, keep_mask) if not k]
    return out, {
        "wf_actual_start": wf_actual_start,
        "latest_kept": kept_names,
        "latest_dropped": dropped_names,
        "latest_atom_t_stats": latest_t,
    }


def run_module4_minefield_dragon(
    strat: str,
    df: pd.DataFrame,
    feature_cols: list[str],
    v20_ctx: dict,
    mine_loss_thr: float = -0.07,
    blacklist_qs: tuple[int, ...] = (15, 20, 25),
    use_declustered: bool = False,
    wf_start_date: str = "2023-01-03",
) -> tuple[list[dict], dict]:
    """
    Module 4: Physical separation of Minefield Risk Scorecard (predicting net_ret <= mine_loss_thr)
    and Dragon-Hunting Scorecard (or OrigScore) inside the non-blacklisted safe pool.
    Strictly causal (exit_date < t).
    """
    wcfg = get_warmup_cfg(strat)
    n = len(df)
    buy_dts = df["buy_date"].astype(str).str[:10].to_numpy()
    exit_dts = df["exit_date"].astype(str).str[:10].to_numpy()
    codes = df["code"].astype(str).str.zfill(6).to_numpy()
    raw_ret = df["net_ret"].to_numpy(float)
    y_mine = (raw_ret <= mine_loss_thr).astype(float)
    y_win = (raw_ret > 0.0).astype(float)
    can_buy = df["can_buy_hygiene"].to_numpy(bool) & np.isfinite(raw_ret)

    X_all = df[feature_cols].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=np.float64)
    uniq_dts = sorted(set(buy_dts.tolist()))
    dt_to_id = {d: i for i, d in enumerate(uniq_dts)}
    day_ids_all = np.array([dt_to_id[d] for d in buy_dts], dtype=np.int32)

    b_idx = np.where(can_buy)[0]
    ex_ord = np.asarray(sorted(b_idx.tolist(), key=lambda i: (exit_dts[i], buy_dts[i], codes[i])), dtype=np.int64)
    ex_dts = exit_dts[ex_ord]
    X_ex = X_all[ex_ord]
    r_ex = raw_ret[ex_ord]
    ym_ex = y_mine[ex_ord]
    w_ex = y_win[ex_ord]
    d_ex = day_ids_all[ex_ord]

    by_dt = {}
    for i in b_idx:
        by_dt.setdefault(buy_dts[i], []).append(i)

    wf_in = np.zeros(n, dtype=bool)
    mine_sc = np.full(n, np.nan, dtype=float)
    drag_sc = np.full(n, np.nan, dtype=float)
    mine_thrs = {q: np.full(n, np.nan, dtype=float) for q in blacklist_qs}
    drag_thrs = {k: np.full(n, np.nan, dtype=float) for k in ("top30", "top20", "top10")}

    ptr, last_ptr, started, wf_actual_start = 0, -1, False, None
    seen_days = set()
    mine_card, drag_card = None, None
    latest_safe_thr = 75.0

    for t in sorted(by_dt.keys()):
        while ptr < len(ex_ord) and ex_dts[ptr] < t:
            seen_days.add(int(d_ex[ptr]))
            ptr += 1
        if t < wf_start_date:
            continue
        if not started:
            cond_w = (ptr >= wcfg["min_warmup_trades_rare"]) and (len(seen_days) >= (wcfg["min_warmup_days"] if use_declustered else 8))
            if cond_w:
                started = True
                wf_actual_start = t
            else:
                continue

        if mine_card is None or ptr > last_ptr:
            if use_declustered:
                mine_card = cm.fit_declustered_causal_scorecard(
                    X_ex[:ptr], ym_ex[:ptr], ym_ex[:ptr], d_ex[:ptr],
                    feature_names=feature_cols, mode="scorecard_0_100",
                    top_k=8, min_k=3, max_corr=0.65, min_t_stat=1.0, shrink_tau=10.0,
                    target_mode="minefield",
                )
            else:
                mine_card = cm.fit_declustered_causal_scorecard(
                    X_ex[:ptr], ym_ex[:ptr], ym_ex[:ptr], d_ex[:ptr],
                    feature_names=feature_cols, mode="scorecard_0_100",
                    top_k=8, min_k=3, max_corr=0.65, min_t_stat=1.0, shrink_tau=15.0,
                    target_mode="minefield",
                )
            # Train-set minefield scores to establish causal blacklist quantile thresholds
            m_tr_sc = wfc.score_candidates_with_card(X_ex[:ptr], mine_card).astype(float)
            # Use 20% blacklist safe pool to fit Dragon-Hunting scorecard (strictly exit_date < t)
            q80_thr = mine_card.get("train_score_q80_top20", 60)
            safe_mask = m_tr_sc < q80_thr
            if int(safe_mask.sum()) >= max(10, int(0.4 * ptr)):
                drag_card = cm.fit_declustered_causal_scorecard(
                    X_ex[:ptr][safe_mask], r_ex[:ptr][safe_mask], w_ex[:ptr][safe_mask], d_ex[:ptr][safe_mask],
                    feature_names=feature_cols, mode="scorecard_0_100",
                    top_k=10, min_k=4, max_corr=0.65, min_t_stat=1.0, shrink_tau=10.0,
                    target_mode="dragon",
                )
            else:
                drag_card = cm.fit_declustered_causal_scorecard(
                    X_ex[:ptr], r_ex[:ptr], w_ex[:ptr], d_ex[:ptr],
                    feature_names=feature_cols, mode="scorecard_0_100",
                    top_k=10, min_k=4, max_corr=0.65, min_t_stat=1.0, shrink_tau=10.0,
                    target_mode="dragon",
                )
            last_ptr = ptr

        rows_t = np.asarray(by_dt[t], dtype=np.int64)
        wf_in[rows_t] = True
        mine_sc[rows_t] = wfc.score_candidates_with_card(X_all[rows_t], mine_card).astype(float)
        drag_sc[rows_t] = wfc.score_candidates_with_card(X_all[rows_t], drag_card).astype(float)
        for q in blacklist_qs:
            mine_thrs[q][rows_t] = mine_card.get(f"train_score_q{100 - q}_top{q}", 65)
        drag_thrs["top30"][rows_t] = drag_card.get("train_score_q70_top30", 55)
        drag_thrs["top20"][rows_t] = drag_card.get("train_score_q80_top20", 60)
        drag_thrs["top10"][rows_t] = drag_card.get("train_score_q90_top10", 68)

    out = df.copy()
    out["wf_in_window"] = wf_in
    out["wf_mine_score"] = mine_sc
    out["wf_dragon_score"] = drag_sc
    for q in blacklist_qs:
        out[f"wf_mine_thr_{q}"] = mine_thrs[q]
    for k, arr in drag_thrs.items():
        out[f"wf_drag_{k}"] = arr

    wf_cands = out[out["wf_in_window"]].copy()
    rows_summary = []
    best_detail = None
    best_nav = -1.0

    for q in blacklist_qs:
        safe_df = out.copy()
        is_black = safe_df["wf_mine_score"] >= safe_df[f"wf_mine_thr_{q}"]
        safe_df["can_buy_hygiene"] = safe_df["can_buy_hygiene"] & (~is_black.fillna(False))

        # Diagnostic: minefield precision/recall on WF candidates
        wf_blk = wf_cands[wf_cands["wf_mine_score"] >= wf_cands[f"wf_mine_thr_{q}"]]
        wf_saf = wf_cands[wf_cands["wf_mine_score"] < wf_cands[f"wf_mine_thr_{q}"]]
        mine_rate_blk = float((wf_blk["net_ret"] <= mine_loss_thr).mean() * 100.0) if len(wf_blk) else 0.0
        mine_rate_saf = float((wf_saf["net_ret"] <= mine_loss_thr).mean() * 100.0) if len(wf_saf) else 0.0

        # Pair 1: Safe Pool + Original V20 Score
        p1, s1 = cm.sim_strategy_custom(strat, safe_df, "orig_score", cm.ORIG_THRESHOLDS[strat], wf_only=True)
        r1, d1 = cm.summarize_eval_row(
            strat, "M4_MineSplit", f"M4_MineBL{q}_OrigScore",
            p1, s1, wf_cands, v20_ctx, wf_actual_start or wf_start_date, perm_n=1000, score_col="_sc_use",
        )
        r1["note"] = f"blk_n={len(wf_blk)} mine%={mine_rate_blk:.1f} vs saf mine%={mine_rate_saf:.1f}"
        rows_summary.append(r1)
        if r1["nav_wf"] > best_nav:
            best_nav = r1["nav_wf"]
            best_detail = {"variant_id": r1["variant_id"], "slot_df": s1, "mine_card": mine_card, "drag_card": drag_card, "metrics": d1}

        # Pair 2: Safe Pool + Dragon-Hunting Scorecard
        for d_thr in ("top30", "top20", "top10", 65, 70):
            t_arg = f"wf_drag_{d_thr}" if isinstance(d_thr, str) else float(d_thr)
            t_lbl = d_thr if isinstance(d_thr, str) else f"abs{d_thr}"
            p2, s2 = cm.sim_strategy_custom(strat, safe_df, "wf_dragon_score", t_arg, wf_only=True)
            s_cut = float(np.nanmedian(safe_df.loc[safe_df["wf_in_window"], "wf_drag_top10"])) if safe_df["wf_in_window"].any() else 70.0
            r2, d2 = cm.summarize_eval_row(
                strat, "M4_MineSplit", f"M4_MineBL{q}_Dragon_{t_lbl}",
                p2, s2, wf_cands, v20_ctx, wf_actual_start or wf_start_date, perm_n=1000, s_tier_cutoff=s_cut, score_col="_sc_use",
            )
            r2["note"] = f"blk_n={len(wf_blk)} mine%={mine_rate_blk:.1f} vs saf mine%={mine_rate_saf:.1f}"
            rows_summary.append(r2)
            if r2["nav_wf"] > best_nav:
                best_nav = r2["nav_wf"]
                best_detail = {"variant_id": r2["variant_id"], "slot_df": s2, "mine_card": mine_card, "drag_card": drag_card, "metrics": d2}

    return rows_summary, {
        "wf_actual_start": wf_actual_start,
        "latest_mine_card": mine_card,
        "latest_drag_card": drag_card,
        "best_detail": best_detail,
        "scored_df": out,
    }


def main():
    t_start = time.time()
    v20_ctx = cm.wf.load_v20_reference_context()
    all_rows = []
    audit = {"parity": {}, "module1_loo": {}, "module1_wf": {}, "module2": {}, "module3": {}, "module3_pry_clustering": {}, "module4": {}, "truncation_20241231": {}}
    best_ledgers = {}

    for strat in ("3to4", "high", "pry"):
        t_st = time.time()
        pm, pinfo = cm.load_master_pool_with_exec(strat)
        audit["parity"][strat] = pinfo
        fg = cm.get_feature_groups(pm, strat)
        wcfg = get_warmup_cfg(strat)
        use_dec = (strat == "pry")

        # 0. Strict 0.30% Baseline over WF window
        # First get actual WF start from standard Mode B so baseline and variants align on exact WF window!
        _, b_pass, b_slot = cm.sim_strategy_custom(strat, pm, "orig_score", cm.ORIG_THRESHOLDS[strat], wf_only=False) if False else (None, *cm.sim_strategy_custom(strat, pm, "orig_score", cm.ORIG_THRESHOLDS[strat], wf_only=False))
        # Determine standard WF start date by running baseline filter >= 2023-01-03 (or aligned with Mode A/B actual start)
        probe_df, probe_meta = run_mode_b_custom(strat, pm, fg["xtr"], v20_ctx, max_delta=15, use_declustered=use_dec)[:2]
        wf_dt_base = "2023-01-03"
        b_wf_cands = pm[pm["buy_date"] >= wf_dt_base].copy()
        b_pass_wf = b_pass[b_pass["buy_date"] >= wf_dt_base].reset_index(drop=True)
        b_slot_wf = b_slot[b_slot["buy_date"] >= wf_dt_base].reset_index(drop=True)
        row_b, det_b = cm.summarize_eval_row(
            strat, "M0_Baseline", "Baseline_V20_030",
            b_pass_wf, b_slot_wf, b_wf_cands, v20_ctx, wf_dt_base, perm_n=1000, score_col="orig_score",
        )
        all_rows.append(row_b)
        best_ledgers[f"{strat}_baseline_wf"] = b_slot_wf

        # =====================================================================
        # MODULE 1: Internal Atomic Factor LOO Ablation + Causal Dynamic Pruning
        # =====================================================================
        loo_list = []
        for afc in fg["native_af"]:
            pm_loo = pm.copy()
            pm_loo["sc_loo"] = pm_loo["orig_score"] - pm_loo[afc].fillna(0.0)
            p_l, s_l = cm.sim_strategy_custom(strat, pm_loo, "sc_loo", cm.ORIG_THRESHOLDS[strat], wf_only=False)
            p_lw = p_l[p_l["buy_date"] >= wf_dt_base]
            s_lw = s_l[s_l["buy_date"] >= wf_dt_base]
            ev_l = wfm.evaluate_wf_ledger(s_lw, p_lw, b_wf_cands, v20_ctx["bench"], wf_start_dt=wf_dt_base, end_dt="2026-11-16", perm_n=200)
            fw_l = ev_l["windows"]["FULL_WF"]
            y25_l = ev_l["windows"]["Y2025_2026"]
            loo_list.append({
                "dropped_factor": afc,
                "n_trades": fw_l["n"],
                "wr_pct": fw_l["wr_pct"],
                "plr": fw_l["plr"],
                "nav_wf": fw_l["nav"],
                "ex5_wf": fw_l["ex_top5_nav"],
                "mdd_pct": fw_l["daily_mdd_pct"],
                "nav_2526": y25_l["nav"],
                "delta_nav_vs_base": round(fw_l["nav"] - row_b["nav_wf"], 4),
            })
        loo_list.sort(key=lambda x: -x["nav_wf"])
        audit["module1_loo"][strat] = loo_list

        # Record top-1 LOO winner + worst-1 LOO + special `spry_af_lock50` in table with 1000x perm
        special_af = [loo_list[0]["dropped_factor"]]
        if strat == "pry" and "spry_af_lock50" not in special_af:
            special_af.append("spry_af_lock50")
        for afc in special_af:
            pm_loo = pm.copy()
            pm_loo["sc_loo"] = pm_loo["orig_score"] - pm_loo[afc].fillna(0.0)
            p_l, s_l = cm.sim_strategy_custom(strat, pm_loo, "sc_loo", cm.ORIG_THRESHOLDS[strat], wf_only=False)
            r_l, _ = cm.summarize_eval_row(
                strat, "M1_AtomicPrune", f"M1_LOO_Drop_{afc}",
                p_l[p_l["buy_date"] >= wf_dt_base], s_l[s_l["buy_date"] >= wf_dt_base],
                b_wf_cands, v20_ctx, wf_dt_base, perm_n=1000, score_col="sc_loo",
            )
            all_rows.append(r_l)
            if strat == "pry" and afc == "spry_af_lock50":
                # Also test lowering pry threshold by 10 (165->155) after removing +10 lock50 bonus
                p_l2, s_l2 = cm.sim_strategy_custom(strat, pm_loo, "sc_loo", 155.0, wf_only=False)
                r_l2, _ = cm.summarize_eval_row(
                    strat, "M1_AtomicPrune", "M1_LOO_Drop_spry_af_lock50_thr155",
                    p_l2[p_l2["buy_date"] >= wf_dt_base], s_l2[s_l2["buy_date"] >= wf_dt_base],
                    b_wf_cands, v20_ctx, wf_dt_base, perm_n=1000, score_col="sc_loo",
                )
                all_rows.append(r_l2)

        # M1b: Causal WF Negative-Atom Pruning (t < 0.0 and t < -0.5)
        for t_cut, tag in ((0.0, "t0"), (-0.5, "tm05")):
            pr_df, pr_meta = run_causal_neg_prune_atoms(strat, pm, fg["native_af"], t_cut=t_cut, wf_start_date=wf_dt_base)
            p_pr, s_pr = cm.sim_strategy_custom(strat, pr_df, "wf_pruned_score", cm.ORIG_THRESHOLDS[strat], wf_only=True)
            wfs = pr_meta["wf_actual_start"] or wf_dt_base
            r_pr, _ = cm.summarize_eval_row(
                strat, "M1_AtomicPrune", f"M1_WF_DropNeg_{tag}",
                p_pr, s_pr, pr_df[pr_df["wf_in_window"]], v20_ctx, wfs, perm_n=1000, score_col="wf_pruned_score",
            )
            r_pr["note"] = f"dropped={len(pr_meta['latest_dropped'])}:{','.join(pr_meta['latest_dropped'][:4])}"
            all_rows.append(r_pr)
            audit["module1_wf"][f"{strat}_{tag}"] = pr_meta

        # M1c: Causal Mode B Reweight on native atoms only (max_corr_orig=None)
        for md in (15, 25):
            sc_df, p_mb, s_mb, mb_meta = run_mode_b_custom(strat, pm, fg["native_af"], v20_ctx, max_delta=md, max_corr_orig=None, use_declustered=use_dec)
            wfs = mb_meta["wf_actual_start"] or wf_dt_base
            r_mb, _ = cm.summarize_eval_row(
                strat, "M1_AtomicReweight", f"M1_WF_NativeRewt_ModeB_d{md}",
                p_mb, s_mb, sc_df[sc_df["wf_in_window"]], v20_ctx, wfs, perm_n=1000, score_col="wf_new_score",
            )
            all_rows.append(r_mb)

        # M1d: Causal Mode A 0..100 on native atoms only
        ma_nat_df, ma_nat_meta = run_mode_a_custom(strat, pm, fg["native_af"], use_declustered=use_dec, top_k=min(10, len(fg["native_af"])))
        wfs = ma_nat_meta["wf_actual_start"] or wf_dt_base
        for th in ("top30", "top20", "top10", 65, 70):
            t_arg = f"wf_thr_{th}" if isinstance(th, str) else float(th)
            t_lbl = th if isinstance(th, str) else f"abs{th}"
            p_ma, s_ma = cm.sim_strategy_custom(strat, ma_nat_df, "wf_score", t_arg, wf_only=True)
            s_cut = float(np.nanmedian(ma_nat_df.loc[ma_nat_df["wf_in_window"], "wf_thr_top10"])) if ma_nat_df["wf_in_window"].any() else 70.0
            r_ma, _ = cm.summarize_eval_row(
                strat, "M1_AtomicReweight", f"M1_WF_Native_ModeA_{t_lbl}",
                p_ma, s_ma, ma_nat_df[ma_nat_df["wf_in_window"]], v20_ctx, wfs, perm_n=1000, s_tier_cutoff=s_cut, score_col="_sc_use",
            )
            all_rows.append(r_ma)

        # =====================================================================
        # MODULE 2: Cross-Strategy Transplant (`xtr_*` 37 cols)
        # =====================================================================
        for md in (10, 15, 25):
            sc_df, p_x, s_x, x_meta = run_mode_b_custom(strat, pm, fg["xtr"], v20_ctx, max_delta=md, max_corr_orig=0.75, use_declustered=use_dec)
            wfs = x_meta["wf_actual_start"] or wf_dt_base
            r_x, _ = cm.summarize_eval_row(
                strat, "M2_CrossTransplant", f"M2_XTR_ModeB_d{md}",
                p_x, s_x, sc_df[sc_df["wf_in_window"]], v20_ctx, wfs, perm_n=1000, score_col="wf_new_score",
            )
            all_rows.append(r_x)
            if md == 15:
                audit["module2"][f"{strat}_modeB_d15"] = x_meta["latest_scorecard"]

        x_ma_df, x_ma_meta = run_mode_a_custom(strat, pm, fg["native_af"] + fg["xtr"], use_declustered=use_dec)
        wfs = x_ma_meta["wf_actual_start"] or wf_dt_base
        audit["module2"][f"{strat}_modeA_nat_xtr"] = x_ma_meta["latest_scorecard"]
        for th in ("top30", "top20", "top10", 65, 70, 75):
            t_arg = f"wf_thr_{th}" if isinstance(th, str) else float(th)
            t_lbl = th if isinstance(th, str) else f"abs{th}"
            p_ma, s_ma = cm.sim_strategy_custom(strat, x_ma_df, "wf_score", t_arg, wf_only=True)
            s_cut = float(np.nanmedian(x_ma_df.loc[x_ma_df["wf_in_window"], "wf_thr_top10"])) if x_ma_df["wf_in_window"].any() else 70.0
            r_ma, _ = cm.summarize_eval_row(
                strat, "M2_CrossTransplant", f"M2_NatPlusXTR_ModeA_{t_lbl}",
                p_ma, s_ma, x_ma_df[x_ma_df["wf_in_window"]], v20_ctx, wfs, perm_n=1000, s_tier_cutoff=s_cut, score_col="_sc_use",
            )
            all_rows.append(r_ma)

        # =====================================================================
        # MODULE 3: 334+ New Factors Mode B (+10/15/25) & Mode A (0..100)
        # =====================================================================
        for md in (10, 15, 25):
            sc_df, p_m3, s_m3, m3_meta = run_mode_b_custom(strat, pm, fg["all_new_367"], v20_ctx, max_delta=md, max_corr_orig=0.70, use_declustered=use_dec)
            wfs = m3_meta["wf_actual_start"] or wf_dt_base
            r_m3, _ = cm.summarize_eval_row(
                strat, "M3_New334_ModeB", f"M3_New367_ModeB_d{md}",
                p_m3, s_m3, sc_df[sc_df["wf_in_window"]], v20_ctx, wfs, perm_n=1000, score_col="wf_new_score",
            )
            all_rows.append(r_m3)
            if md == 15:
                audit["module3"][f"{strat}_modeB_d15"] = m3_meta["latest_scorecard"]

            # Also all_with_native
            sc_df2, p_m3n, s_m3n, m3n_meta = run_mode_b_custom(strat, pm, fg["all_with_native"], v20_ctx, max_delta=md, max_corr_orig=0.70, use_declustered=use_dec)
            wfs2 = m3n_meta["wf_actual_start"] or wf_dt_base
            r_m3n, _ = cm.summarize_eval_row(
                strat, "M3_New334_ModeB", f"M3_AllWithNat_ModeB_d{md}",
                p_m3n, s_m3n, sc_df2[sc_df2["wf_in_window"]], v20_ctx, wfs2, perm_n=1000, score_col="wf_new_score",
            )
            all_rows.append(r_m3n)

        # Mode A full 0..100 reconstruction on all_with_native
        ma_df, ma_meta = run_mode_a_custom(strat, pm, fg["all_with_native"], use_declustered=use_dec)
        wfs = ma_meta["wf_actual_start"] or wf_dt_base
        audit["module3"][f"{strat}_modeA_all"] = ma_meta["latest_scorecard"]
        for th in ("all_cands", "top30", "top20", "top10", "top5", 65, 70, 75, 80, 85):
            t_arg = None if th == "all_cands" else (f"wf_thr_{th}" if isinstance(th, str) else float(th))
            t_lbl = th if isinstance(th, str) else f"abs{th}"
            p_ma, s_ma = cm.sim_strategy_custom(strat, ma_df, "wf_score", t_arg, wf_only=True)
            s_cut = float(np.nanmedian(ma_df.loc[ma_df["wf_in_window"], "wf_thr_top10"])) if ma_df["wf_in_window"].any() else 70.0
            r_ma, _ = cm.summarize_eval_row(
                strat, "M3_New334_ModeA", f"M3_All_ModeA_{t_lbl}",
                p_ma, s_ma, ma_df[ma_df["wf_in_window"]], v20_ctx, wfs, perm_n=1000, s_tier_cutoff=s_cut, score_col="_sc_use",
            )
            all_rows.append(r_ma)

        # Special PRY clustering & sample-size stress test: Naive unweighted vs De-clustered vs Daily-Top1 collapsed
        if strat == "pry":
            # 1) Naive unweighted Mode B d15 and Mode A
            sc_u, p_u, s_u, u_meta = run_mode_b_custom("pry", pm, fg["all_with_native"], v20_ctx, max_delta=15, use_declustered=False)
            r_u, _ = cm.summarize_eval_row(
                "pry", "M3_PryClusteringTest", "M3_Pry_NaiveUnweighted_ModeB_d15",
                p_u, s_u, sc_u[sc_u["wf_in_window"]], v20_ctx, u_meta["wf_actual_start"] or wf_dt_base, perm_n=1000, score_col="wf_new_score",
            )
            all_rows.append(r_u)

            ma_u, ma_u_meta = run_mode_a_custom("pry", pm, fg["all_with_native"], use_declustered=False)
            for th in ("top20", "top10", 70, 75):
                t_arg = f"wf_thr_{th}" if isinstance(th, str) else float(th)
                t_lbl = th if isinstance(th, str) else f"abs{th}"
                pu, su = cm.sim_strategy_custom("pry", ma_u, "wf_score", t_arg, wf_only=True)
                ru, _ = cm.summarize_eval_row(
                    "pry", "M3_PryClusteringTest", f"M3_Pry_NaiveUnweighted_ModeA_{t_lbl}",
                    pu, su, ma_u[ma_u["wf_in_window"]], v20_ctx, ma_u_meta["wf_actual_start"] or wf_dt_base, perm_n=1000, score_col="_sc_use",
                )
                all_rows.append(ru)

            # 2) Post-2024-02-07 OOS check (2024-03-01 .. 2026-11-16) comparing Declustered vs Naive vs Baseline
            def _post_feb24_stats(slot_d, label):
                sub = slot_d[slot_d["buy_date"] >= "2024-03-01"]
                return {
                    "label": label,
                    "n": int(len(sub)),
                    "wr_pct": round(float((sub["net_ret"] > 0).mean() * 100.0), 2) if len(sub) else 0.0,
                    "nav": round(float(np.prod(1.0 + sub["net_ret"].to_numpy(float))), 4) if len(sub) else 1.0,
                }
            _, s_decl_top10 = cm.sim_strategy_custom("pry", ma_df, "wf_score", "wf_thr_top10", wf_only=True)
            _, s_naive_top10 = cm.sim_strategy_custom("pry", ma_u, "wf_score", "wf_thr_top10", wf_only=True)
            audit["module3_pry_clustering"] = {
                "total_rows": int(len(pm)),
                "unique_days": int(pm["buy_date"].nunique()),
                "max_single_day_rows": int(pm["buy_date"].value_counts().iloc[0]),
                "max_single_day_date": str(pm["buy_date"].value_counts().index[0]),
                "top5_day_share_pct": round(float(pm["buy_date"].value_counts().head(5).sum() / len(pm) * 100.0), 2),
                "post_20240207_comparison": [
                    _post_feb24_stats(b_slot_wf, "Baseline_V21_030"),
                    _post_feb24_stats(s_naive_top10, "NaiveUnweighted_ModeA_top10"),
                    _post_feb24_stats(s_decl_top10, "Declustered_ModeA_top10"),
                ],
                "declustered_latest_factors": ma_meta["latest_scorecard"]["factors"] if ma_meta.get("latest_scorecard") else [],
                "naive_latest_factors": ma_u_meta["latest_scorecard"]["factors"] if ma_u_meta.get("latest_scorecard") else [],
            }

        # =====================================================================
        # MODULE 4: Physical Separation of Minefield vs Dragon-Hunting Tables
        # =====================================================================
        m_thr = -0.07 if strat in ("3to4", "pry") else -0.02
        m4_rows, m4_det = run_module4_minefield_dragon(
            strat, pm, fg["all_with_native"], v20_ctx, mine_loss_thr=m_thr,
            blacklist_qs=(15, 20, 25), use_declustered=True, wf_start_date=wf_dt_base,
        )
        all_rows.extend(m4_rows)
        audit["module4"][strat] = {
            "mine_loss_thr": m_thr,
            "wf_actual_start": m4_det["wf_actual_start"],
            "latest_mine_card_factors": m4_det["latest_mine_card"]["factors"] if m4_det.get("latest_mine_card") else [],
            "latest_drag_card_factors": m4_det["latest_drag_card"]["factors"] if m4_det.get("latest_drag_card") else [],
        }

        # Track best standalone WF variant per strategy
        st_rows = [r for r in all_rows if r["strategy"] == strat and r["n_trades"] >= (10 if strat == "high" else 8)]
        st_rows.sort(key=lambda x: (-x["nav_wf"], -x["sharpe"]))
        if st_rows:
            best_v = st_rows[0]
            print(f"[{strat}] finished in {time.time()-t_st:.1f}s | Base WF: {row_b['n_trades']}t {row_b['nav_wf']:.2f}x (25-26:{row_b['nav_2526']:.2f}x) | Best: {best_v['variant_id']} -> {best_v['n_trades']}t {best_v['nav_wf']:.2f}x (Ex5:{best_v['ex5_wf']:.2f}x, MDD:{best_v['daily_mdd_pct']:.1f}%, 25-26:{best_v['nav_2526']:.2f}x, p={best_v['perm_any_p']})")

    # =========================================================================
    # Physical Truncation Zero-Leakage Proof at 2024-12-31
    # =========================================================================
    print("\n[Truncation Proof 2024-12-31] Running full vs truncated zero-leakage assertions...")
    for strat in ("3to4", "pry"):
        pm, _ = cm.load_master_pool_with_exec(strat)
        fg = cm.get_feature_groups(pm, strat)
        pm_t = pm[pm["buy_date"] <= "2024-12-31"].copy().reset_index(drop=True)

        # Test Mode A (`wf_scorecard_engine` on 3to4, declustered on pry)
        sf, _ = run_mode_a_custom(strat, pm, fg["all_with_native"], use_declustered=(strat == "pry"))
        st, _ = run_mode_a_custom(strat, pm_t, fg["all_with_native"], use_declustered=(strat == "pry"))
        sf_le = sf[sf["buy_date"] <= "2024-12-31"].sort_values(["buy_date", "code"]).reset_index(drop=True)
        st_le = st.sort_values(["buy_date", "code"]).reset_index(drop=True)
        diff_a = float(np.max(np.abs(sf_le["wf_score"].fillna(-999.0).to_numpy() - st_le["wf_score"].fillna(-999.0).to_numpy())))
        assert diff_a == 0.0, f"{strat} Mode A truncation leaked: {diff_a}"

        # Test Mode B
        bf, _, _, _ = run_mode_b_custom(strat, pm, fg["all_new_367"], v20_ctx, max_delta=15, use_declustered=(strat == "pry"))
        bt, _, _, _ = run_mode_b_custom(strat, pm_t, fg["all_new_367"], v20_ctx, max_delta=15, use_declustered=(strat == "pry"))
        bf_le = bf[bf["buy_date"] <= "2024-12-31"].sort_values(["buy_date", "code"]).reset_index(drop=True)
        bt_le = bt.sort_values(["buy_date", "code"]).reset_index(drop=True)
        diff_b = float(np.max(np.abs(bf_le["wf_delta_score"].to_numpy() - bt_le["wf_delta_score"].to_numpy())))
        assert diff_b == 0.0, f"{strat} Mode B truncation leaked: {diff_b}"

        audit["truncation_20241231"][strat] = {
            "modeA_max_abs_diff": diff_a,
            "modeB_max_abs_diff": diff_b,
            "n_rows_le_20241231": int(len(st_le)),
            "zero_leakage_pass": True,
        }

    # Also test Module 4 truncation on 3to4
    pm34, _ = cm.load_master_pool_with_exec("3to4")
    fg34 = cm.get_feature_groups(pm34, "3to4")
    _, d_full = run_module4_minefield_dragon("3to4", pm34, fg34["all_with_native"], v20_ctx, mine_loss_thr=-0.07, blacklist_qs=(20,))
    _, d_trnc = run_module4_minefield_dragon("3to4", pm34[pm34["buy_date"] <= "2024-12-31"].copy().reset_index(drop=True), fg34["all_with_native"], v20_ctx, mine_loss_thr=-0.07, blacklist_qs=(20,))
    m_f = d_full["scored_df"][d_full["scored_df"]["buy_date"] <= "2024-12-31"].sort_values(["buy_date", "code"]).reset_index(drop=True)
    m_t = d_trnc["scored_df"].sort_values(["buy_date", "code"]).reset_index(drop=True)
    diff_m = float(np.max(np.abs(m_f["wf_mine_score"].fillna(-999.0).to_numpy() - m_t["wf_mine_score"].fillna(-999.0).to_numpy())))
    diff_d = float(np.max(np.abs(m_f["wf_dragon_score"].fillna(-999.0).to_numpy() - m_t["wf_dragon_score"].fillna(-999.0).to_numpy())))
    assert diff_m == 0.0 and diff_d == 0.0, f"M4 truncation leaked: mine={diff_m}, drag={diff_d}"
    audit["truncation_20241231"]["m4_3to4"] = {"mine_max_abs_diff": diff_m, "dragon_max_abs_diff": diff_d, "zero_leakage_pass": True}

    rss_mb = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 2)
    audit["runtime_sec"] = round(time.time() - t_start, 2)
    audit["peak_rss_mb"] = rss_mb

    out_pkl = f"{CUR_DIR}/_w2a2_m1_4_results.pkl"
    with open(out_pkl, "wb") as f:
        pickle.dump({"rows": all_rows, "audit": audit, "best_ledgers": best_ledgers}, f)
    print(f"[DONE M1-M4 in {audit['runtime_sec']}s | RSS={rss_mb}MB] rows={len(all_rows)} -> {out_pkl}")


if __name__ == "__main__":
    main()

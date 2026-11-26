#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 2A-1 Strictly Causal (exit_date < t) Learners for Modules 1, 2, 3, 4, 5.
Zero lookahead, deterministic sorting, truncation-invariant at 2024-12-31.
"""
import math
import os
import sys
from typing import Optional

import numpy as np
import pandas as pd

WAVE1_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
if WAVE1_DIR not in sys.path:
    sys.path.insert(0, WAVE1_DIR)

import _wf_core as wfc


def _build_exit_index(df: pd.DataFrame) -> dict:
    n = len(df)
    buy_dts = df["buy_date"].astype(str).str[:10].to_numpy()
    exit_dts = df["exit_date"].astype(str).str[:10].to_numpy()
    codes = df["code"].astype(str).str.zfill(6).to_numpy()
    y_ret = df["net_ret"].to_numpy(dtype=np.float64)
    can_buy = (~df["is_yizi"].fillna(False).to_numpy(bool)) & np.isfinite(y_ret)
    if "sim_ok" in df.columns:
        can_buy &= df["sim_ok"].fillna(True).to_numpy(bool)

    uniq_dts = sorted(set(buy_dts.tolist()))
    dt_to_id = {d: i for i, d in enumerate(uniq_dts)}
    day_ids_all = np.array([dt_to_id[d] for d in buy_dts], dtype=np.int32)

    buyable_idx = np.where(can_buy)[0]
    exit_order = sorted(buyable_idx.tolist(), key=lambda i: (exit_dts[i], buy_dts[i], codes[i]))
    exit_arr = np.asarray(exit_order, dtype=np.int64)

    by_dt_all = {}
    for i in range(n):
        by_dt_all.setdefault(buy_dts[i], []).append(i)

    return {
        "n": n, "buy_dts": buy_dts, "exit_dts": exit_dts, "y_ret": y_ret,
        "day_ids_all": day_ids_all, "can_buy": can_buy,
        "exit_arr": exit_arr, "exit_dts_sorted": exit_dts[exit_arr],
        "r_exit": y_ret[exit_arr], "d_exit": day_ids_all[exit_arr],
        "by_dt_all": by_dt_all, "sorted_dts": sorted(by_dt_all.keys()),
    }


def run_causal_autoprune(
    df: pd.DataFrame,
    contrib_mat: np.ndarray,
    wf_start_date: str = "2023-01-03",
    window_mode: str = "exp",
    roll_n: int = 80,
    t_cut: float = 0.0,
    recenter: bool = False,
) -> np.ndarray:
    """
    Module 1.2: Day-by-day (exit_date < t) automatically zero out atomic factors whose
    causal cluster-t contribution < t_cut. Returns full-length adjusted score array.
    """
    idx_info = _build_exit_index(df)
    exit_arr = idx_info["exit_arr"]
    exit_dts_s = idx_info["exit_dts_sorted"]
    r_exit = idx_info["r_exit"]
    w_exit = (r_exit > 0.0).astype(np.float64)
    d_exit = idx_info["d_exit"]
    C_exit = contrib_mat[exit_arr]
    orig_sc = df["v20_score"].to_numpy(np.float64)
    out_sc = orig_sc.copy()

    ptr = 0
    n_exit = len(exit_arr)
    F = contrib_mat.shape[1]
    for t in idx_info["sorted_dts"]:
        while ptr < n_exit and exit_dts_s[ptr] < t:
            ptr += 1
        if t < wf_start_date or ptr < 40:
            continue
        sl = slice(max(0, ptr - roll_n), ptr) if window_mode == "roll" else slice(0, ptr)
        rv, wv, dv = r_exit[sl], w_exit[sl], d_exit[sl]
        mu0, wr0 = float(np.mean(rv)), float(np.mean(wv))
        sd_r = max(1e-5, float(np.std(rv, ddof=1)))
        u_util = 0.6 * (rv - mu0) / sd_r + 0.4 * (wv - wr0) / 0.25
        C_tr = C_exit[sl]

        rows_t = np.asarray(idx_info["by_dt_all"][t], dtype=np.int64)
        drop_sum = np.zeros(len(rows_t), dtype=np.float64)
        mean_shift = 0.0
        for j in range(F):
            cj = C_tr[:, j]
            if float(np.std(cj)) < 1e-12:
                continue
            t_j = wfc._cluster_t_stat(u_util, cj, dv)
            if t_j < t_cut:
                drop_sum += contrib_mat[rows_t, j]
                if recenter:
                    mean_shift += float(np.mean(cj))
        out_sc[rows_t] = orig_sc[rows_t] - drop_sum + mean_shift
    return out_sc


def run_causal_reweight_v20(
    df: pd.DataFrame,
    contrib_mat: np.ndarray,
    wf_start_date: str = "2023-01-03",
    prior_blend: float = 0.5,
    shrink_tau: float = 25.0,
) -> np.ndarray:
    """
    Module 1.3: Day-by-day (exit_date < t) re-weight internal atomic components using
    shrunk cluster-t multiplier blended with original V20 prior weight, preserving V20 score scale.
    """
    idx_info = _build_exit_index(df)
    exit_arr = idx_info["exit_arr"]
    exit_dts_s = idx_info["exit_dts_sorted"]
    r_exit = idx_info["r_exit"]
    w_exit = (r_exit > 0.0).astype(np.float64)
    d_exit = idx_info["d_exit"]
    C_exit = contrib_mat[exit_arr]
    orig_sc = df["v20_score"].to_numpy(np.float64)
    orig_exit = orig_sc[exit_arr]
    out_sc = orig_sc.copy()
    base_res = orig_sc - contrib_mat.sum(axis=1)

    ptr = 0
    n_exit = len(exit_arr)
    F = contrib_mat.shape[1]
    for t in idx_info["sorted_dts"]:
        while ptr < n_exit and exit_dts_s[ptr] < t:
            ptr += 1
        if t < wf_start_date or ptr < 40:
            continue
        rv, wv, dv = r_exit[:ptr], w_exit[:ptr], d_exit[:ptr]
        mu0, wr0 = float(np.mean(rv)), float(np.mean(wv))
        sd_r = max(1e-5, float(np.std(rv, ddof=1)))
        u_util = 0.6 * (rv - mu0) / sd_r + 0.4 * (wv - wr0) / 0.25
        C_tr = C_exit[:ptr]

        mults = np.ones(F, dtype=np.float64)
        for j in range(F):
            cj = C_tr[:, j]
            if float(np.std(cj)) < 1e-12:
                continue
            t_j = wfc._cluster_t_stat(u_util, cj, dv)
            # Empirical data multiplier: positive t -> >0, negative t -> 0 (or negative if strongly inverted)
            n_eff = ptr / (ptr + shrink_tau)
            data_m = float(np.clip((t_j / 1.5) * n_eff, -0.5, 2.0))
            mults[j] = prior_blend * 1.0 + (1.0 - prior_blend) * max(0.0, data_m)

        # Preserve mean & std of orig_sc on training < t
        tr_new_raw = base_res[exit_arr[:ptr]] + C_tr @ mults
        rows_t = np.asarray(idx_info["by_dt_all"][t], dtype=np.int64)
        te_new_raw = base_res[rows_t] + contrib_mat[rows_t] @ mults
        sd_tr = float(np.std(tr_new_raw))
        sd_or = float(np.std(orig_exit[:ptr]))
        if sd_tr > 1e-9 and sd_or > 1e-9:
            out_sc[rows_t] = (te_new_raw - float(np.mean(tr_new_raw))) * (sd_or / sd_tr) + float(np.mean(orig_exit[:ptr]))
        else:
            out_sc[rows_t] = te_new_raw
    return out_sc


def run_causal_risk_and_dragon(
    df: pd.DataFrame,
    feature_cols: list[str],
    wf_start_date: str = "2023-01-03",
    blowup_cut: float = -0.07,
    top_k_risk: int = 10,
    top_k_dragon: int = 12,
    dragon_target: str = "util",
    recalc_freq: str = "daily",
) -> pd.DataFrame:
    """
    Module 4: Strictly causal day-by-day (exit_date < t) physical separation of:
      1. `wf_risk_score`: 0..100 probability-oriented scorecard trained on y_blowup = (net_ret <= blowup_cut)
         + training quantile cutoffs q75/q80/q85 (top 25%/20%/15% highest risk).
      2. `wf_dragon_score`: 0..100 Dragon-Hunting scorecard trained on safe pool (excluding risk >= q80 on train < t),
         targeting either 'util' or upside tail 'big_win' (net_ret >= +0.10).
    """
    idx_info = _build_exit_index(df)
    X_all = df[feature_cols].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=np.float64)
    exit_arr = idx_info["exit_arr"]
    exit_dts_s = idx_info["exit_dts_sorted"]
    X_exit = X_all[exit_arr]
    r_exit = idx_info["r_exit"]
    d_exit = idx_info["d_exit"]
    y_blow = (r_exit <= blowup_cut).astype(np.float64)
    y_risk_ret = y_blow  # higher = more blowups

    n = idx_info["n"]
    risk_sc = np.full(n, np.nan, dtype=np.float64)
    risk_q85 = np.full(n, np.nan, dtype=np.float64)
    risk_q80 = np.full(n, np.nan, dtype=np.float64)
    risk_q75 = np.full(n, np.nan, dtype=np.float64)
    dragon_sc = np.full(n, np.nan, dtype=np.float64)
    drag_q80 = np.full(n, np.nan, dtype=np.float64)
    drag_q90 = np.full(n, np.nan, dtype=np.float64)

    ptr = 0
    n_exit = len(exit_arr)
    last_ptr, last_month = -1, ""
    risk_card = None
    dragon_card = None
    r_q85 = r_q80 = r_q75 = 100.0
    d_q80 = d_q90 = 50.0

    for t in idx_info["sorted_dts"]:
        while ptr < n_exit and exit_dts_s[ptr] < t:
            ptr += 1
        if t < wf_start_date or ptr < 80:
            continue
        need = (risk_card is None) or (recalc_freq == "daily" and ptr > last_ptr) or (recalc_freq == "monthly" and t[:7] != last_month)
        if need:
            risk_card = wfc.fit_causal_scorecard(
                X_exit[:ptr], y_risk_ret[:ptr], y_blow[:ptr], d_exit[:ptr],
                feature_names=feature_cols, mode="scorecard_0_100",
                top_k=top_k_risk, min_k=4, max_corr=0.65, min_t_stat=1.0, shrink_tau=20.0,
            )
            tr_risk = wfc.score_candidates_with_card(X_exit[:ptr], risk_card)
            r_q85 = float(np.percentile(tr_risk, 85.0))
            r_q80 = float(np.percentile(tr_risk, 80.0))
            r_q75 = float(np.percentile(tr_risk, 75.0))

            safe_m = tr_risk < r_q80
            if safe_m.sum() < 50:
                safe_m = np.ones(ptr, dtype=bool)
            rv_s = r_exit[:ptr][safe_m]
            if dragon_target == "big_win":
                wv_s = (rv_s >= 0.10).astype(np.float64)
            else:
                wv_s = (rv_s > 0.0).astype(np.float64)
            dragon_card = wfc.fit_causal_scorecard(
                X_exit[:ptr][safe_m], rv_s, wv_s, d_exit[:ptr][safe_m],
                feature_names=feature_cols, mode="scorecard_0_100",
                top_k=top_k_dragon, min_k=5, max_corr=0.65, min_t_stat=1.0, shrink_tau=20.0,
            )
            tr_drag = wfc.score_candidates_with_card(X_exit[:ptr][safe_m], dragon_card)
            d_q80 = float(math.ceil(float(np.percentile(tr_drag, 80.0))))
            d_q90 = float(math.ceil(float(np.percentile(tr_drag, 90.0))))
            last_ptr, last_month = ptr, t[:7]

        rows_t = np.asarray(idx_info["by_dt_all"][t], dtype=np.int64)
        risk_sc[rows_t] = wfc.score_candidates_with_card(X_all[rows_t], risk_card).astype(np.float64)
        risk_q85[rows_t] = r_q85
        risk_q80[rows_t] = r_q80
        risk_q75[rows_t] = r_q75
        dragon_sc[rows_t] = wfc.score_candidates_with_card(X_all[rows_t], dragon_card).astype(np.float64)
        drag_q80[rows_t] = d_q80
        drag_q90[rows_t] = d_q90

    out = pd.DataFrame({
        "wf_risk_score": risk_sc, "risk_q85": risk_q85, "risk_q80": risk_q80, "risk_q75": risk_q75,
        "wf_dragon_score": dragon_sc, "drag_q80": drag_q80, "drag_q90": drag_q90,
    }, index=df.index)
    return out


def score_mode_b_all_rows(
    df: pd.DataFrame,
    feature_cols: list[str],
    wf_start_date: str = "2023-01-03",
    recalc_freq: str = "daily",
    top_k: int = 10,
    min_k: int = 5,
    max_corr: float = 0.65,
    max_corr_orig: Optional[float] = 0.70,
    min_t_stat: float = 1.0,
    shrink_tau: float = 20.0,
    max_delta: int = 15,
) -> tuple[np.ndarray, dict]:
    """
    Strictly causal Mode B delta_patch that trains ONLY on buyable settled trades (exit_date < t)
    but scores ALL pre-09:25 rows (including sim_ok==0 in 1to2 so ranking has zero hindsight bias).
    """
    idx_info = _build_exit_index(df)
    X_all = df[feature_cols].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=np.float64)
    orig_arr = pd.to_numeric(df["v20_score"], errors="coerce").to_numpy(dtype=np.float64)
    exit_arr = idx_info["exit_arr"]
    exit_dts_s = idx_info["exit_dts_sorted"]
    X_exit = X_all[exit_arr]
    r_exit = idx_info["r_exit"]
    w_exit = (r_exit > 0.0).astype(np.float64)
    d_exit = idx_info["d_exit"]
    orig_exit = orig_arr[exit_arr]

    delta_out = np.zeros(idx_info["n"], dtype=np.float64)
    ptr = 0
    n_exit = len(exit_arr)
    last_ptr, last_month = -1, ""
    card = None
    for t in idx_info["sorted_dts"]:
        while ptr < n_exit and exit_dts_s[ptr] < t:
            ptr += 1
        if t < wf_start_date or ptr < 80:
            continue
        need = (card is None) or (recalc_freq == "daily" and ptr > last_ptr) or (recalc_freq == "monthly" and t[:7] != last_month)
        if need:
            card = wfc.fit_causal_scorecard(
                X_exit[:ptr], r_exit[:ptr], w_exit[:ptr], d_exit[:ptr],
                feature_names=feature_cols, mode="delta_patch",
                top_k=top_k, min_k=min_k, max_corr=max_corr,
                min_t_stat=min_t_stat, shrink_tau=shrink_tau, max_delta=max_delta,
                orig_score_train=orig_exit[:ptr], max_corr_orig=max_corr_orig,
            )
            last_ptr, last_month = ptr, t[:7]
        rows_t = np.asarray(idx_info["by_dt_all"][t], dtype=np.int64)
        delta_out[rows_t] = wfc.score_candidates_with_card(X_all[rows_t], card).astype(np.float64)
    return delta_out, (card or {})

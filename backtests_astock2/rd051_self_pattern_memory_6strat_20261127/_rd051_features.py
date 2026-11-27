#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD051 Feature Engine: Strict PIT Self-Event Gene (Family A), Self-KNN (Family B), and Target Alignment."""

import math
from typing import Optional

import numpy as np
import pandas as pd

KNN_SCALES_NOTE = "10d scaled by [0.05,0.05,0.04,0.06,0.25,0.04,0.40,0.30,0.15,0.04]"


def _safe_mean(arr: np.ndarray) -> float:
    return float(np.mean(arr)) if len(arr) > 0 else np.nan


def _eb_shrink(n: int, raw_mean: float, prior: float, m: float) -> float:
    if not np.isfinite(prior):
        prior = 0.0
    if n <= 0 or not np.isfinite(raw_mean):
        return float(prior)
    return float((n * raw_mean + m * prior) / (n + m))


def _greedy_knn(
    cand_indices: np.ndarray,
    knn_mat: np.ndarray,
    q_vec: np.ndarray,
    k_max: int,
    min_gap: int = 10,
) -> tuple[np.ndarray, np.ndarray]:
    """Select up to k_max nearest neighbors spaced >= min_gap bars apart."""
    if len(cand_indices) == 0 or not np.all(np.isfinite(q_vec)):
        return np.empty(0, dtype=np.int64), np.empty(0, dtype=np.float64)
    sub = knn_mat[cand_indices]
    valid = np.all(np.isfinite(sub), axis=1)
    if not valid.any():
        return np.empty(0, dtype=np.int64), np.empty(0, dtype=np.float64)
    c_use = cand_indices[valid]
    diff = sub[valid] - q_vec[None, :]
    d2 = np.sum(diff * diff, axis=1, dtype=np.float64)
    order = np.argsort(d2, kind="mergesort")
    picked = []
    dists = []
    for pos in order:
        idx_h = int(c_use[pos])
        if all(abs(idx_h - p) >= min_gap for p in picked):
            picked.append(idx_h)
            dists.append(math.sqrt(float(d2[pos])))
            if len(picked) >= k_max:
                break
    return np.asarray(picked, dtype=np.int64), np.asarray(dists, dtype=np.float64)


def _summarize_knn_outcomes(picked: np.ndarray, dists: np.ndarray, s: dict) -> dict:
    if len(picked) == 0:
        return {
            "n": 0, "avg_dist": np.nan, "min_dist": np.nan,
            "t0_intraday": np.nan, "t0_red_wr": np.nan,
            "t1_buy_ret": np.nan, "t1_wr": np.nan, "t1_w_ret": np.nan, "damian_rate": np.nan,
        }
    ao = s["ao"][picked]
    ac0 = s["ac"][picked]
    ac1 = s["ac"][picked + 1]
    t0_ret = ac0 / ao - 1.0
    t0_red = (ac0 > ao).astype(np.float64)
    t1_ret = ac1 / ao - 1.0
    t1_win = (t1_ret > 0.0).astype(np.float64)
    damian = ((t1_ret < -0.05) | (t0_ret < -0.06)).astype(np.float64)
    w = 1.0 / (1.0 + dists * dists)
    w_sum = float(np.sum(w))
    t1_w = float(np.sum(w * t1_ret) / w_sum) if w_sum > 0 else float(np.mean(t1_ret))
    return {
        "n": int(len(picked)),
        "avg_dist": float(np.mean(dists)),
        "min_dist": float(dists[0]),
        "t0_intraday": float(np.mean(t0_ret)),
        "t0_red_wr": float(np.mean(t0_red)),
        "t1_buy_ret": float(np.mean(t1_ret)),
        "t1_wr": float(np.mean(t1_win)),
        "t1_w_ret": t1_w,
        "damian_rate": float(np.mean(damian)),
    }


def _compute_zt_gene(
    zt_indices: np.ndarray,
    s: dict,
    idx_T: int,
    max_gap: int,
    win_bars: Optional[int] = None,
) -> dict:
    """Compute self ZT gene strictly using t_h <= idx_T - max_gap."""
    hi_cut = idx_T - max_gap
    lo_cut = (idx_T - win_bars) if win_bars is not None else 0
    sel = zt_indices[(zt_indices <= hi_cut) & (zt_indices >= lo_cut)]
    n = int(len(sel))
    if n == 0:
        return {
            "n": 0, "open_prem": np.nan, "next1d_ret": np.nan, "next1d_wr": np.nan,
            "intraday_ret": np.nan, "lianban_rate": np.nan, "damian_rate": np.nan,
            "last3_ret": np.nan, "yizi_share": np.nan,
        }
    nxt = sel + 1
    c_h = s["ac"][sel]
    o_n = s["ao"][nxt]
    c_n = s["ac"][nxt]
    op_prem = o_n / c_h - 1.0
    n1_ret = c_n / c_h - 1.0
    intr = c_n / o_n - 1.0
    n1_win = (n1_ret > 0.0).astype(np.float64)
    lb = s["is_zt"][nxt].astype(np.float64)
    damian = ((n1_ret < -0.05) | (intr < -0.06)).astype(np.float64)
    yz_sh = float(np.mean(s["is_yizi_zt"][sel]))
    last3 = float(np.mean(n1_ret[-3:]))
    return {
        "n": n,
        "open_prem": float(np.mean(op_prem)),
        "next1d_ret": float(np.mean(n1_ret)),
        "next1d_wr": float(np.mean(n1_win)),
        "intraday_ret": float(np.mean(intr)),
        "lianban_rate": float(np.mean(lb)),
        "damian_rate": float(np.mean(damian)),
        "last3_ret": last3,
        "yizi_share": yz_sh,
    }


def _same_scene_mask_for_strategy(strat: str, s: dict) -> np.ndarray:
    """Boolean mask of historical candidate buy-day analogs t_h where t_h >= 21 and t_h + 1 < len(dts)."""
    m = len(s["dts"])
    mask = np.zeros(m, dtype=bool)
    if m < 25:
        return mask
    is_zt = s["is_zt"]
    is_yz_zt = s["is_yizi_zt"]
    is_dt = s["is_dt"]
    ret_1d = s["ret_1d"]
    open_pct = s["open_pct"]
    streak = s["streak"]
    is_20 = s["is_20"]
    valid_t = (~s["is_ipo20"]) & (~s["is_split"]) & (~is_yz_zt)
    valid_t[0:2] = False
    valid_t[-1] = False  # need t_h + 1

    prev_zt = np.roll(is_zt, 1); prev_zt[0] = False
    prev_stk = np.roll(streak, 1); prev_stk[0] = 0
    prev2_stk = np.roll(streak, 2); prev2_stk[:2] = 0
    prev_dt = np.roll(is_dt, 1); prev_dt[0] = False
    prev_ret = np.roll(ret_1d, 1); prev_ret[0] = np.nan
    prev_20 = np.roll(is_20, 1); prev_20[0] = False

    if strat == "1to2":
        mask = valid_t & (prev_stk == 1)
    elif strat == "2to3":
        mask = valid_t & (prev_stk >= 2)
    elif strat == "3to4":
        # Prefer >=3 board history, fallback to >=2 if needed handled separately
        mask = valid_t & (prev_stk >= 2)
    elif strat == "pry":
        mask = valid_t & (prev_dt | (prev_ret <= -0.07))
    elif strat == "20cm":
        surge = (prev_20 & prev_zt) | (prev_ret >= 0.10)
        mask = valid_t & surge & (open_pct < 0.0)
    elif strat == "high":
        mask = valid_t & (prev2_stk >= 2) & (~prev_zt)
    else:
        raise ValueError(f"Unknown strategy: {strat}")
    return mask


def _knn2_precond_mask(strat: str, s: dict) -> np.ndarray:
    """Boolean mask of historical days t_h matching same pre-condition for KNN-2."""
    m = len(s["dts"])
    mask = np.zeros(m, dtype=bool)
    if m < 25:
        return mask
    is_zt = s["is_zt"]
    is_dt = s["is_dt"]
    ret_1d = s["ret_1d"]
    streak = s["streak"]
    is_20 = s["is_20"]
    valid_t = (~s["is_ipo20"]) & (~s["is_split"]) & (~s["is_yizi_zt"])
    valid_t[0:20] = False
    valid_t[-1] = False

    prev_zt = np.roll(is_zt, 1); prev_zt[0] = False
    prev2_stk = np.roll(streak, 2); prev2_stk[:2] = 0
    prev_dt = np.roll(is_dt, 1); prev_dt[0] = False
    prev_ret = np.roll(ret_1d, 1); prev_ret[0] = np.nan
    prev_20 = np.roll(is_20, 1); prev_20[0] = False

    if strat in ("1to2", "2to3", "3to4"):
        mask = valid_t & prev_zt
    elif strat == "pry":
        mask = valid_t & (prev_dt | (prev_ret <= -0.07))
    elif strat == "20cm":
        mask = valid_t & ((prev_20 & prev_zt) | (prev_ret >= 0.10))
    elif strat == "high":
        mask = valid_t & (prev2_stk >= 1) & (~prev_zt)
    return mask


def build_all_features(mp: pd.DataFrame, stock_data: dict[str, dict]) -> tuple[pd.DataFrame, dict]:
    """Compute all 4 feature families + Day-T outcomes strictly PIT for every row in `mp`."""
    # Precompute per-(code) ZT indices & per-(code, strat) same-scene & KNN-2 candidate indices
    zt_idx_cache: dict[str, np.ndarray] = {}
    scene_cache: dict[tuple[str, str], np.ndarray] = {}
    scene3b_cache: dict[str, np.ndarray] = {}
    knn1_cache: dict[str, np.ndarray] = {}
    knn2_cache: dict[tuple[str, str], np.ndarray] = {}

    for c6, s in stock_data.items():
        m = len(s["dts"])
        valid_zt = np.flatnonzero(s["is_zt"] & (~s["is_ipo20"]) & (~s["is_split"]) & (np.arange(m) < m - 1))
        zt_idx_cache[c6] = valid_zt

        # KNN-1 valid indices: >= 20, not split, not IPO20, has t_h + 1
        k1 = (~s["is_ipo20"]) & (~s["is_split"])
        k1[:20] = False
        k1[-1] = False
        knn1_cache[c6] = np.flatnonzero(k1)

        prev_stk = np.roll(s["streak"], 1); prev_stk[0] = 0
        s3 = (~s["is_ipo20"]) & (~s["is_split"]) & (~s["is_yizi_zt"]) & (prev_stk >= 3)
        s3[:3] = False; s3[-1] = False
        scene3b_cache[c6] = np.flatnonzero(s3)

        for st in ("1to2", "2to3", "3to4", "pry", "20cm", "high"):
            scene_cache[(c6, st)] = np.flatnonzero(_same_scene_mask_for_strategy(st, s))
            knn2_cache[(c6, st)] = np.flatnonzero(_knn2_precond_mask(st, s))

    # Build causal expanding prior for same_scene EB shrinkage using settled rows in mp (exit_date < T)
    # Sort mp by exit_date for O(N) causal sweep
    mp_work = mp.copy()
    mp_work["_orig_idx"] = np.arange(len(mp_work))
    mp_work["net_ret_030"] = np.where(
        mp_work["strategy"] == "20cm",
        mp_work["net_ret"].astype(float),
        (1.0 + mp_work["net_ret"].astype(float)) / 0.9980 * 0.9970 - 1.0,
    )

    # Compute t0 outcomes first for every row so causal prior uses exact t0/t1_buy_ret
    t0_intr = np.full(len(mp_work), np.nan, dtype=np.float64)
    t0_c_gt_o = np.full(len(mp_work), np.nan, dtype=np.float64)
    t0_is_zt = np.full(len(mp_work), np.nan, dtype=np.float64)
    t0_h_vs_o = np.full(len(mp_work), np.nan, dtype=np.float64)
    t0_cl_ret = np.full(len(mp_work), np.nan, dtype=np.float64)
    t1_buy_ret = np.full(len(mp_work), np.nan, dtype=np.float64)
    prior_days_arr = np.zeros(len(mp_work), dtype=np.int32)
    matched_bar = np.zeros(len(mp_work), dtype=bool)
    op_diff_arr = np.full(len(mp_work), np.nan, dtype=np.float64)

    for i, r in enumerate(mp_work.itertuples(index=False)):
        s = stock_data.get(r.c6)
        if s is None:
            continue
        idx_T = s["dt_to_idx"].get(r.bd)
        if idx_T is None:
            continue
        matched_bar[i] = True
        prior_days_arr[i] = idx_T
        t0_intr[i] = float(s["intraday_ret"][idx_T])
        t0_c_gt_o[i] = float(s["ac"][idx_T] > s["ao"][idx_T])
        t0_is_zt[i] = float(s["is_zt"][idx_T])
        t0_h_vs_o[i] = float(s["high_vs_open"][idx_T])
        t0_cl_ret[i] = float(s["ret_1d"][idx_T])
        if idx_T + 1 < len(s["dts"]):
            t1_buy_ret[i] = float(s["ac"][idx_T + 1] / s["ao"][idx_T] - 1.0)
        if np.isfinite(s["open_pct"][idx_T]):
            op_diff_arr[i] = abs(float(r.open_pct) - float(s["open_pct"][idx_T]))

    mp_work["t0_intraday_ret"] = t0_intr
    mp_work["t0_close_gt_open"] = t0_c_gt_o
    mp_work["t0_is_zt"] = t0_is_zt
    mp_work["t0_high_vs_open"] = t0_h_vs_o
    mp_work["t0_close_ret"] = t0_cl_ret
    mp_work["t1_open_buy_ret"] = t1_buy_ret
    mp_work["prior_trading_days"] = prior_days_arr
    mp_work["open_pct_abs_diff"] = op_diff_arr

    # Pre-index settled trades strictly by (strategy, exit_date < buy_date) and (code, exit_date < buy_date)
    settled_rows = mp_work[(mp_work["sim_ok"] == 1) & mp_work["net_ret_030"].notna()].sort_values(["ed", "bd", "c6"]).reset_index(drop=True)
    # Causal priors by unique (strategy, buy_date)
    causal_priors: dict[tuple[str, str], dict] = {}
    for st in ("1to2", "2to3", "3to4", "high", "pry", "20cm"):
        st_set = settled_rows[settled_rows["strategy"] == st]
        eds = st_set["ed"].to_numpy()
        r_t1 = st_set["t1_open_buy_ret"].fillna(0.0).to_numpy(np.float64)
        w_t1 = (r_t1 > 0.0).astype(np.float64)
        r_t0 = st_set["t0_intraday_ret"].fillna(0.0).to_numpy(np.float64)
        cs_r1 = np.concatenate(([0.0], np.cumsum(r_t1)))
        cs_w1 = np.concatenate(([0.0], np.cumsum(w_t1)))
        cs_r0 = np.concatenate(([0.0], np.cumsum(r_t0)))
        for bd in mp_work.loc[mp_work["strategy"] == st, "bd"].unique():
            k = int(np.searchsorted(eds, bd, side="left"))
            # Damped toward neutral 0.0 / 0.50 with 10 pseudo-obs so early warmup is smooth & strictly causal
            causal_priors[(st, bd)] = {
                "p_ret": float(cs_r1[k] / (k + 10.0)),
                "p_wr": float((cs_w1[k] + 5.0) / (k + 10.0)),
                "p_t0": float(cs_r0[k] / (k + 10.0)),
            }

    # Index settled rows by code for hist_pool_self_ret & hist_pool_any_ret
    pool_by_code: dict[str, list[tuple[str, str, float]]] = {}
    for r in settled_rows.itertuples(index=False):
        pool_by_code.setdefault(r.c6, []).append((r.ed, r.strategy, float(r.net_ret_030)))

    # Main per-row feature extraction
    feat_rows = []
    for r in mp_work.itertuples(index=False):
        s = stock_data[r.c6]
        idx_T = s["dt_to_idx"][r.bd]
        st = r.strategy
        pri = causal_priors[(st, r.bd)]

        # 1) ZT Gene: gap>=2 (all & 3y) + gap>=10 (de-waved)
        z_arr = zt_idx_cache[r.c6]
        zg2_all = _compute_zt_gene(z_arr, s, idx_T, max_gap=2, win_bars=None)
        zg2_3y = _compute_zt_gene(z_arr, s, idx_T, max_gap=2, win_bars=750)
        zg10_all = _compute_zt_gene(z_arr, s, idx_T, max_gap=10, win_bars=None)

        # 2) Same-Scene Self-Analogue (gap>=2 and gap>=10)
        sc_arr = scene_cache[(r.c6, st)]
        sc_g2 = sc_arr[sc_arr <= idx_T - 2]
        sc_g10 = sc_arr[sc_arr <= idx_T - 10]
        if st == "3to4":
            sc3 = scene3b_cache[r.c6]
            sc3_g2 = sc3[sc3 <= idx_T - 2]
        else:
            sc3_g2 = sc_g2

        def _scene_stats(idxs: np.ndarray) -> dict:
            n = int(len(idxs))
            if n == 0:
                return {
                    "n": 0, "t0_intr": np.nan, "t0_red": np.nan, "t0_zt": np.nan,
                    "t1_ret": np.nan, "t1_wr": np.nan, "damian": np.nan, "last3_ret": np.nan,
                }
            ao = s["ao"][idxs]
            ac0 = s["ac"][idxs]
            ac1 = s["ac"][idxs + 1]
            t0r = ac0 / ao - 1.0
            t1r = ac1 / ao - 1.0
            dam = ((t1r < -0.05) | (t0r < -0.06)).astype(np.float64)
            return {
                "n": n,
                "t0_intr": float(np.mean(t0r)),
                "t0_red": float(np.mean(ac0 > ao)),
                "t0_zt": float(np.mean(s["is_zt"][idxs])),
                "t1_ret": float(np.mean(t1r)),
                "t1_wr": float(np.mean(t1r > 0.0)),
                "damian": float(np.mean(dam)),
                "last3_ret": float(np.mean(t1r[-3:])),
            }

        ss2 = _scene_stats(sc_g2)
        ss10 = _scene_stats(sc_g10)
        ss3b = _scene_stats(sc3_g2)

        # 3) Same-strategy & any-strategy historical settled pool outcomes (exit_date < buy_date)
        p_recs = pool_by_code.get(r.c6, [])
        self_rets = [rv for edv, stv, rv in p_recs if edv < r.bd and stv == st]
        any_rets = [rv for edv, stv, rv in p_recs if edv < r.bd]

        # 4) KNN-1 (unconstrained, >=10d gap & spacing) and KNN-2 (pre-condition constrained)
        q_vec = s["knn_mat"][idx_T]
        k1_cands = knn1_cache[r.c6]
        k1_cands = k1_cands[k1_cands <= idx_T - 10]
        p1_5, d1_5 = _greedy_knn(k1_cands, s["knn_mat"], q_vec, k_max=5, min_gap=10)
        p1_10, d1_10 = _greedy_knn(k1_cands, s["knn_mat"], q_vec, k_max=10, min_gap=10)
        ks1_5 = _summarize_knn_outcomes(p1_5, d1_5, s)
        ks1_10 = _summarize_knn_outcomes(p1_10, d1_10, s)

        k2_cands = knn2_cache[(r.c6, st)]
        k2_cands = k2_cands[k2_cands <= idx_T - 10]
        p2_5, d2_5 = _greedy_knn(k2_cands, s["knn_mat"], q_vec, k_max=5, min_gap=10)
        ks2_5 = _summarize_knn_outcomes(p2_5, d2_5, s)

        row_d = {
            "_orig_idx": r._orig_idx,
            # ZT Gene (gap>=2 all & 3y, gap>=10 all)
            "hist_zt_n": zg2_all["n"],
            "hist_zt_open_prem": zg2_all["open_prem"],
            "hist_zt_next1d_ret": zg2_all["next1d_ret"],
            "hist_zt_next1d_wr": zg2_all["next1d_wr"],
            "hist_zt_intraday_ret": zg2_all["intraday_ret"],
            "hist_zt_lianban_rate": zg2_all["lianban_rate"],
            "hist_zt_damian_rate": zg2_all["damian_rate"],
            "hist_zt_last3_ret": zg2_all["last3_ret"],
            "hist_zt_yizi_share": zg2_all["yizi_share"],
            "hist_zt_3y_n": zg2_3y["n"],
            "hist_zt_3y_next1d_ret": zg2_3y["next1d_ret"],
            "hist_zt_3y_next1d_wr": zg2_3y["next1d_wr"],
            "hist_zt_3y_lianban_rate": zg2_3y["lianban_rate"],
            "hist_zt_3y_damian_rate": zg2_3y["damian_rate"],
            "hist_zt_g10_n": zg10_all["n"],
            "hist_zt_g10_next1d_ret": zg10_all["next1d_ret"],
            "hist_zt_g10_lianban_rate": zg10_all["lianban_rate"],
            "hist_zt_g10_damian_rate": zg10_all["damian_rate"],
            # Same-Scene Self-Analogue (gap>=2 & gap>=10 & EB shrunk)
            "same_scene_n": ss2["n"],
            "same_scene_is_new_face": int(ss2["n"] == 0),
            "same_scene_t0_intr": ss2["t0_intr"],
            "same_scene_t0_red_wr": ss2["t0_red"],
            "same_scene_zt_rate": ss2["t0_zt"],
            "same_scene_t1_ret": ss2["t1_ret"],
            "same_scene_t1_wr": ss2["t1_wr"],
            "same_scene_damian_rate": ss2["damian"],
            "same_scene_last3_ret": ss2["last3_ret"],
            "same_scene_ret_eb_m3": _eb_shrink(ss2["n"], ss2["t1_ret"], pri["p_ret"], 3.0),
            "same_scene_ret_eb_m5": _eb_shrink(ss2["n"], ss2["t1_ret"], pri["p_ret"], 5.0),
            "same_scene_wr_eb_m3": _eb_shrink(ss2["n"], ss2["t1_wr"], pri["p_wr"], 3.0),
            "same_scene_t0_eb_m3": _eb_shrink(ss2["n"], ss2["t0_intr"], pri["p_t0"], 3.0),
            "same_scene_g10_n": ss10["n"],
            "same_scene_g10_t1_ret": ss10["t1_ret"],
            "same_scene_g10_ret_eb_m3": _eb_shrink(ss10["n"], ss10["t1_ret"], pri["p_ret"], 3.0),
            "same_scene_g10_damian_rate": ss10["damian"],
            "same_scene_3b_n": ss3b["n"],
            "same_scene_3b_t1_ret": ss3b["t1_ret"],
            # Historical Pool Self Backtest
            "hist_pool_self_n": len(self_rets),
            "hist_pool_self_ret": float(np.mean(self_rets)) if self_rets else np.nan,
            "hist_pool_self_wr": float(np.mean([x > 0 for x in self_rets])) if self_rets else np.nan,
            "hist_pool_any_n": len(any_rets),
            "hist_pool_any_ret": float(np.mean(any_rets)) if any_rets else np.nan,
            # KNN-1 Top-5 & Top-10
            "knn1_k5_n": ks1_5["n"],
            "knn1_k5_avg_dist": ks1_5["avg_dist"],
            "knn1_k5_min_dist": ks1_5["min_dist"],
            "knn1_k5_t0_intr": ks1_5["t0_intraday"],
            "knn1_k5_t0_red_wr": ks1_5["t0_red_wr"],
            "knn1_k5_t1_ret": ks1_5["t1_buy_ret"],
            "knn1_k5_t1_w_ret": ks1_5["t1_w_ret"],
            "knn1_k5_t1_wr": ks1_5["t1_wr"],
            "knn1_k5_damian_rate": ks1_5["damian_rate"],
            "knn1_k5_ret_eb_m5": _eb_shrink(ks1_5["n"], ks1_5["t1_buy_ret"], pri["p_ret"], 5.0),
            "knn1_k10_n": ks1_10["n"],
            "knn1_k10_avg_dist": ks1_10["avg_dist"],
            "knn1_k10_t0_intr": ks1_10["t0_intraday"],
            "knn1_k10_t1_ret": ks1_10["t1_buy_ret"],
            "knn1_k10_t1_wr": ks1_10["t1_wr"],
            "knn1_k10_damian_rate": ks1_10["damian_rate"],
            # KNN-2 Top-5 (precondition constrained)
            "knn2_n_avail": int(len(k2_cands)),
            "knn2_k5_n": ks2_5["n"],
            "knn2_k5_avg_dist": ks2_5["avg_dist"],
            "knn2_k5_t0_intr": ks2_5["t0_intraday"],
            "knn2_k5_t0_red_wr": ks2_5["t0_red_wr"],
            "knn2_k5_t1_ret": ks2_5["t1_buy_ret"],
            "knn2_k5_t1_w_ret": ks2_5["t1_w_ret"],
            "knn2_k5_t1_wr": ks2_5["t1_wr"],
            "knn2_k5_damian_rate": ks2_5["damian_rate"],
            "knn2_k5_ret_eb_m3": _eb_shrink(ks2_5["n"], ks2_5["t1_buy_ret"], pri["p_ret"], 3.0),
            "knn2_k5_wr_eb_m3": _eb_shrink(ks2_5["n"], ks2_5["t1_wr"], pri["p_wr"], 3.0),
            # Combined EB Shrinkage across ZT + SameScene + KNN2 (for composite exploration)
            "zt_next1d_ret_eb_m5": _eb_shrink(zg2_all["n"], zg2_all["next1d_ret"], 0.0, 5.0),
            "zt_lianban_eb_m5": _eb_shrink(zg2_all["n"], zg2_all["lianban_rate"], 0.25, 5.0),
            "zt_damian_eb_m5": _eb_shrink(zg2_all["n"], zg2_all["damian_rate"], 0.25, 5.0),
        }
        feat_rows.append(row_d)

    feat_df = pd.DataFrame(feat_rows).sort_values("_orig_idx").reset_index(drop=True)
    mp_work = mp_work.sort_values("_orig_idx").reset_index(drop=True)
    base_cols = [
        "strategy", "buy_date", "entry_date", "exit_date", "sig_date", "code", "name",
        "c6", "bd", "ed", "sd", "base_score", "v20_score", "orig_score",
        "is_pass_official", "orig_pass", "sim_ok", "net_ret", "net_ret_030", "ret",
        "buy_price", "exit_price", "open_pct", "plate", "pool_layer", "year", "is_oos_split",
        "oh_list_age", "oh_zt_cnt_1y", "oh_zt_cnt_3y", "oh_zt_cnt_5y",
        "oh_waves_3y_g15", "oh_trap_waves_3y", "oh_cool_days_since_last_zt",
        "t0_intraday_ret", "t0_close_gt_open", "t0_is_zt", "t0_high_vs_open", "t0_close_ret", "t1_open_buy_ret",
        "prior_trading_days", "open_pct_abs_diff",
    ]
    out_df = pd.concat([mp_work[base_cols], feat_df.drop(columns=["_orig_idx"])], axis=1)

    cov_audit = {
        "n_pool_rows": int(len(out_df)),
        "n_pass_official": int((out_df["is_pass_official"] == 1).sum()),
        "n_sim_ok": int((out_df["sim_ok"] == 1).sum()),
        "matched_buy_date_bars": int(matched_bar.sum()),
        "matched_buy_date_pct": round(float(matched_bar.mean() * 100.0), 4),
        "open_pct_max_abs_diff": round(float(np.nanmax(op_diff_arr)), 6),
        "open_pct_gt_1e2_cnt": int(np.sum(op_diff_arr > 1e-2)),
        "prior_days_min": int(out_df["prior_trading_days"].min()),
        "prior_days_p01": float(out_df["prior_trading_days"].quantile(0.01)),
        "prior_days_p05": float(out_df["prior_trading_days"].quantile(0.05)),
        "prior_days_median": float(out_df["prior_trading_days"].median()),
        "pct_ge_60_prior_days": round(float((out_df["prior_trading_days"] >= 60).mean() * 100.0), 2),
        "pct_ge_250_prior_days": round(float((out_df["prior_trading_days"] >= 250).mean() * 100.0), 2),
        "new_face_rate_zt_pct": round(float((out_df["hist_zt_n"] == 0).mean() * 100.0), 2),
        "new_face_rate_same_scene_pct": round(float((out_df["same_scene_n"] == 0).mean() * 100.0), 2),
        "new_face_rate_knn1_pct": round(float((out_df["knn1_k5_n"] == 0).mean() * 100.0), 2),
        "new_face_rate_knn2_pct": round(float((out_df["knn2_k5_n"] == 0).mean() * 100.0), 2),
        "new_face_same_scene_by_strat": {
            st: {
                "n_all": int(len(g)),
                "n_new_face": int((g["same_scene_n"] == 0).sum()),
                "pct_new_face": round(float((g["same_scene_n"] == 0).mean() * 100.0), 2),
                "pass_n": int((g["is_pass_official"] == 1).sum()),
                "pass_new_face_pct": round(float((g.loc[g["is_pass_official"] == 1, "same_scene_n"] == 0).mean() * 100.0), 2),
            }
            for st, g in out_df.groupby("strategy")
        },
    }
    return out_df, cov_audit

#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Core Expanding Walk-Forward Scorecard Learner (Mode A & Mode B).
Strict causal boundary: at decision day t, ONLY trades with exit_date < t are visible.
Zero yfinance (D12). Deterministic & 100% truncation-invariant.
"""
import math
from typing import Optional

import numpy as np
import pandas as pd


def _cluster_t_stat(u: np.ndarray, z: np.ndarray, day_ids: np.ndarray) -> float:
    """Exact Liang-Zeger / CGM cluster-robust OLS t-stat for u ~ 1 + z clustered by buy_date."""
    n = len(u)
    if n < 20:
        return 0.0
    dz = z - float(np.mean(z))
    szz = float(np.dot(dz, dz))
    if szz <= 1e-12:
        return 0.0
    du = u - float(np.mean(u))
    beta = float(np.dot(dz, du)) / szz
    eps = du - beta * dz
    _, g_inv = np.unique(day_ids, return_inverse=True)
    G = int(g_inv.max()) + 1
    if G < 5:
        return 0.0
    sg = np.bincount(g_inv, weights=dz * eps, minlength=G)
    var_b = (G / max(1, G - 1)) * float(np.dot(sg, sg)) / (szz * szz)
    if var_b <= 1e-18:
        return 0.0
    return float(beta / math.sqrt(var_b))


def _largest_remainder_int(weights: np.ndarray, total_pts: int) -> np.ndarray:
    """Allocate exact integer points >= 1 summing to total_pts using largest remainder."""
    k = len(weights)
    if k == 0 or total_pts <= 0:
        return np.zeros(k, dtype=int)
    w = np.maximum(weights, 1e-9)
    w = w / w.sum()
    if total_pts < k:
        # Rare edge: fewer points than factors -> assign 1 to top total_pts
        out = np.zeros(k, dtype=int)
        out[np.argsort(-w)[:total_pts]] = 1
        return out
    rem_tot = total_pts - k
    raw = w * rem_tot
    flo = np.floor(raw).astype(int)
    diff = int(rem_tot - flo.sum())
    if diff > 0:
        order = np.argsort(-(raw - flo), kind="mergesort")
        for idx in order[:diff]:
            flo[idx] += 1
    return flo + 1


def fit_causal_scorecard(
    X_train: np.ndarray,
    y_ret: np.ndarray,
    y_win: np.ndarray,
    day_ids: np.ndarray,
    feature_names: list[str],
    mode: str = "scorecard_0_100",
    top_k: int = 12,
    min_k: int = 5,
    max_corr: float = 0.65,
    min_t_stat: float = 1.0,
    shrink_tau: float = 20.0,
    max_delta: int = 15,
    orig_score_train: Optional[np.ndarray] = None,
    max_corr_orig: Optional[float] = None,
) -> dict:
    """
    Build a transparent integer scorecard strictly from training rows (exit_date < t).
    Mode 'scorecard_0_100': integer bin points summing to exact [0, 100].
    Mode 'delta_patch': signed integer bin deltas bounded in [-max_delta, +max_delta].
    """
    M, F = X_train.shape
    mu0_all = float(np.mean(y_ret))
    wr0_all = float(np.mean(y_win))
    sd_all = max(1e-5, float(np.std(y_ret, ddof=1))) if M > 1 else 0.05
    min_valid_n = max(35, int(0.45 * M))

    candidates = []
    for j in range(F):
        col = X_train[:, j]
        valid = np.isfinite(col)
        nv = int(valid.sum())
        if nv < min_valid_n:
            continue
        xv = col[valid]
        if float(np.std(xv)) < 1e-12:
            continue
        rv = y_ret[valid]
        wv = y_win[valid]
        dv = day_ids[valid]
        mu0 = float(np.mean(rv))
        wr0 = float(np.mean(wv))
        sd_r = max(1e-5, float(np.std(rv, ddof=1)))
        u_util = 0.6 * (rv - mu0) / sd_r + 0.4 * (wv - wr0) / 0.25

        uniq = np.unique(xv)
        if len(uniq) <= 3:
            edges = uniq.astype(float)
            b_idx = np.searchsorted(edges, xv, side="left")
            is_discrete = True
            B = len(edges)
            if B < 2:
                continue
        else:
            q33, q67 = np.percentile(xv, [33.3333333, 66.6666667])
            if q67 <= q33 + 1e-12:
                q50 = float(np.median(xv))
                b_idx = (xv > q50).astype(int)
                if b_idx.sum() < 8 or (nv - b_idx.sum()) < 8:
                    b_idx = (xv >= q50).astype(int)
                if b_idx.sum() < 8 or (nv - b_idx.sum()) < 8:
                    continue
                edges = np.array([q50], dtype=float)
                B = 2
            else:
                b_idx = np.where(xv <= q33, 0, np.where(xv <= q67, 1, 2))
                cnts = np.bincount(b_idx, minlength=3)
                if np.any(cnts < 8):
                    q50 = float(np.median(xv))
                    b_idx = (xv > q50).astype(int)
                    if b_idx.sum() < 8 or (nv - b_idx.sum()) < 8:
                        continue
                    edges = np.array([q50], dtype=float)
                    B = 2
                else:
                    edges = np.array([float(q33), float(q67)], dtype=float)
                    B = 3
            is_discrete = False

        cnts = np.bincount(b_idx, minlength=B)
        sum_r = np.bincount(b_idx, weights=rv, minlength=B)
        sum_w = np.bincount(b_idx, weights=wv, minlength=B)
        shr_dr = (sum_r + shrink_tau * mu0) / (cnts + shrink_tau) - mu0
        shr_dw = (sum_w + shrink_tau * wr0) / (cnts + shrink_tau) - wr0
        eff = 0.6 * (shr_dr / sd_r) + 0.4 * (shr_dw / 0.25)

        if B == 3:
            # Guard against noisy middle-bin inversion: only keep U/inv-U if mid vs ends |t| >= 1.5
            z_lin = b_idx.astype(float) - 1.0
            t_lin = _cluster_t_stat(u_util, z_lin, dv)
            z_quad = np.where(b_idx == 1, 1.0, -0.5)
            t_quad = _cluster_t_stat(u_util, z_quad, dv)
            if abs(t_quad) >= max(1.5, abs(t_lin) + 0.35):
                t_eff = t_quad
                shape = "nonmonotone"
            else:
                # Enforce monotonicity between bin 0 and bin 2
                lo_e, hi_e = min(eff[0], eff[2]), max(eff[0], eff[2])
                eff[1] = float(np.clip(eff[1], lo_e, hi_e))
                if abs(eff[2] - eff[0]) < 1e-12:
                    eff[2] += 1e-9 if t_lin >= 0 else -1e-9
                t_eff = t_lin
                shape = "monotone_up" if eff[2] >= eff[0] else "monotone_down"
        else:
            z_bin = b_idx.astype(float)
            t_eff = _cluster_t_stat(u_util, z_bin, dv)
            shape = "binary_up" if eff[-1] >= eff[0] else "binary_down"

        # Optional check against orig_score in Mode B
        if max_corr_orig is not None and orig_score_train is not None:
            ov = orig_score_train[valid]
            m_ov = np.isfinite(ov)
            if m_ov.sum() >= 30 and np.std(ov[m_ov]) > 1e-12 and np.std(xv[m_ov]) > 1e-12:
                r_orig = abs(float(np.corrcoef(xv[m_ov], ov[m_ov])[0, 1]))
                if r_orig > max_corr_orig:
                    continue

        candidates.append({
            "col_idx": j,
            "name": feature_names[j],
            "abs_t": abs(float(t_eff)),
            "t_cluster": round(float(t_eff), 3),
            "shape": shape,
            "is_discrete": is_discrete,
            "edges": edges,
            "B": B,
            "eff": eff,
            "cnts": cnts.tolist(),
            "bin_wr_pct": [round(float(sum_w[b] / cnts[b] * 100.0), 2) for b in range(B)],
            "bin_mean_pct": [round(float(sum_r[b] / cnts[b] * 100.0), 2) for b in range(B)],
        })

    # Sort deterministically: highest |t_cluster|, then original feature index
    candidates.sort(key=lambda c: (-c["abs_t"], c["col_idx"]))

    # Greedy orthogonal pruning (|r| <= max_corr)
    def _select_pool(cands_list: list[dict]) -> list[dict]:
        sel = []
        for c in cands_list:
            j = c["col_idx"]
            xj = X_train[:, j]
            ok_corr = True
            for s in sel:
                xs = X_train[:, s["col_idx"]]
                both = np.isfinite(xj) & np.isfinite(xs)
                if both.sum() >= 25:
                    a, b = xj[both], xs[both]
                    if np.std(a) > 1e-12 and np.std(b) > 1e-12:
                        r = abs(float(np.corrcoef(a, b)[0, 1]))
                        if r > max_corr:
                            ok_corr = False
                            break
            if ok_corr:
                sel.append(c)
                if len(sel) >= top_k:
                    break
        return sel

    strong = [c for c in candidates if c["abs_t"] >= min_t_stat]
    selected = _select_pool(strong)
    if len(selected) < min_k and len(candidates) > len(selected):
        # Fallback cleanly using remaining top factors (deterministically)
        used = {s["col_idx"] for s in selected}
        rem = [c for c in candidates if c["col_idx"] not in used]
        for c in rem:
            j = c["col_idx"]
            xj = X_train[:, j]
            ok_corr = True
            for s in selected:
                xs = X_train[:, s["col_idx"]]
                both = np.isfinite(xj) & np.isfinite(xs)
                if both.sum() >= 25 and np.std(xj[both]) > 1e-12 and np.std(xs[both]) > 1e-12:
                    if abs(float(np.corrcoef(xj[both], xs[both])[0, 1])) > max_corr:
                        ok_corr = False
                        break
            if ok_corr:
                selected.append(c)
                if len(selected) >= min_k:
                    break

    if not selected:
        return {"mode": mode, "n_train": M, "factors": [], "train_mu0": mu0_all, "train_wr0": wr0_all}

    t_weights = np.array([min(4.0, max(0.25, c["abs_t"])) for c in selected], dtype=float)
    budget_tot = 100 if mode == "scorecard_0_100" else int(max_delta)
    budgets = _largest_remainder_int(t_weights, budget_tot)

    factors_out = []
    for c, bgt in zip(selected, budgets):
        eff = c["eff"]
        emin, emax = float(np.min(eff)), float(np.max(eff))
        if mode == "scorecard_0_100":
            if emax > emin + 1e-12:
                pts = [int(round((float(e) - emin) / (emax - emin) * bgt)) for e in eff]
            else:
                pts = [int(round(0.5 * bgt)) for _ in eff]
            nan_pt = int(round(0.5 * bgt))
        else:
            emean = float(np.average(eff, weights=np.array(c["cnts"], dtype=float)))
            span = max(1e-12, float(np.max(np.abs(eff - emean))))
            pts = [int(round((float(e) - emean) / span * bgt)) for e in eff]
            nan_pt = 0
        factors_out.append({
            "col_idx": c["col_idx"],
            "name": c["name"],
            "t_cluster": c["t_cluster"],
            "shape": c["shape"],
            "budget_pts": int(bgt),
            "is_discrete": c["is_discrete"],
            "edges": c["edges"].tolist(),
            "bin_pts": pts,
            "nan_pt": nan_pt,
            "bin_cnts": c["cnts"],
            "bin_wr_pct": c["bin_wr_pct"],
            "bin_mean_pct": c["bin_mean_pct"],
        })

    card = {
        "mode": mode,
        "n_train": int(M),
        "train_mu0_pct": round(mu0_all * 100.0, 2),
        "train_wr0_pct": round(wr0_all * 100.0, 2),
        "factors": factors_out,
    }
    if mode == "scorecard_0_100":
        tr_scores = score_candidates_with_card(X_train, card)
        card["train_score_q80_top20"] = int(math.ceil(float(np.percentile(tr_scores, 80.0))))
        card["train_score_q90_top10"] = int(math.ceil(float(np.percentile(tr_scores, 90.0))))
        card["train_score_q95_top5"] = int(math.ceil(float(np.percentile(tr_scores, 95.0))))
        card["train_score_q70_top30"] = int(math.ceil(float(np.percentile(tr_scores, 70.0))))
    return card


def score_candidates_with_card(X: np.ndarray, card: dict) -> np.ndarray:
    """Vectorized integer scoring using a frozen causal scorecard."""
    n = X.shape[0]
    factors = card.get("factors", [])
    if not factors:
        return np.full(n, 50 if card.get("mode") == "scorecard_0_100" else 0, dtype=np.int32)
    tot = np.zeros(n, dtype=np.int32)
    for f in factors:
        col = X[:, f["col_idx"]]
        edges = f["edges"]
        pts = np.array(f["bin_pts"], dtype=np.int32)
        nan_pt = int(f["nan_pt"])
        valid = np.isfinite(col)
        sc = np.full(n, nan_pt, dtype=np.int32)
        if valid.any():
            xv = col[valid]
            if f["is_discrete"]:
                # Map to nearest discrete edge value
                ed = np.asarray(edges, dtype=float)
                idx = np.argmin(np.abs(xv[:, None] - ed[None, :]), axis=1)
                sc[valid] = pts[idx]
            elif len(edges) == 1:
                idx = (xv > edges[0]).astype(np.int32)
                sc[valid] = pts[idx]
            else:
                idx = np.where(xv <= edges[0], 0, np.where(xv <= edges[1], 1, 2))
                sc[valid] = pts[idx]
        tot += sc
    if card.get("mode") == "scorecard_0_100":
        tot = np.clip(tot, 0, 100)
    return tot


def _add_months(dt_str: str, months: int) -> str:
    y, m, d = int(dt_str[:4]), int(dt_str[5:7]), int(dt_str[8:10])
    m_tot = (y * 12 + (m - 1)) + months
    ny, nm = divmod(m_tot, 12)
    nm += 1
    return f"{ny:04d}-{nm:02d}-{min(d, 28):02d}"


def run_expanding_scorecard_loop(
    df: pd.DataFrame,
    feature_cols: list[str],
    mode: str = "scorecard_0_100",
    wf_start_date: str = "2023-01-03",
    min_warmup_trades: int = 80,
    min_warmup_trades_rare: int = 60,
    min_warmup_months: int = 18,
    recalc_freq: str = "daily",
    top_k: int = 12,
    min_k: int = 5,
    max_corr: float = 0.65,
    min_t_stat: float = 1.0,
    shrink_tau: float = 20.0,
    max_delta: int = 15,
    orig_score_col: Optional[str] = None,
    max_corr_orig: Optional[float] = None,
    can_buy_mask: Optional[np.ndarray] = None,
    save_snapshot_freq: str = "monthly",
) -> tuple[pd.DataFrame, dict]:
    """
    Day-by-day expanding Walk-Forward scoring loop aligned 1-to-1 with input `df`.
    Guarantees strict exit_date < t causality and zero truncation leakage.
    """
    assert mode in ("scorecard_0_100", "delta_patch"), f"Unsupported mode: {mode}"
    assert recalc_freq in ("daily", "monthly"), f"Unsupported recalc_freq: {recalc_freq}"

    n = len(df)
    if n == 0:
        out = df.copy()
        out["wf_in_window"] = False
        out["wf_score"] = np.nan
        return out, {"wf_actual_start": None, "snapshots": []}

    buy_dts = df["buy_date"].astype(str).str[:10].to_numpy()
    exit_dts = df["exit_date"].astype(str).str[:10].to_numpy()
    codes = df["code"].astype(str).str.zfill(6).to_numpy()
    y_ret = df["net_ret"].to_numpy(dtype=np.float64)
    y_win = (y_ret > 0.0).astype(np.float64)

    if can_buy_mask is None:
        can_buy = np.ones(n, dtype=bool)
        if "is_yizi" in df.columns:
            can_buy &= (~df["is_yizi"].fillna(False).to_numpy(bool))
        if "can_buy" in df.columns:
            can_buy &= df["can_buy"].fillna(True).to_numpy(bool)
    else:
        can_buy = np.asarray(can_buy_mask, dtype=bool)
    can_buy &= np.isfinite(y_ret)

    X_all = df[feature_cols].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=np.float64)
    orig_arr = pd.to_numeric(df[orig_score_col], errors="coerce").to_numpy(dtype=np.float64) if (orig_score_col and orig_score_col in df.columns) else None

    # Deterministic buy_date integer IDs (sorted unique buy_dates <= each date -> invariant under truncation!)
    uniq_dts = sorted(set(buy_dts.tolist()))
    dt_to_id = {d: i for i, d in enumerate(uniq_dts)}
    day_ids_all = np.array([dt_to_id[d] for d in buy_dts], dtype=np.int32)

    # Buyable training pool sorted deterministically by (exit_date, buy_date, code)
    buyable_idx = np.where(can_buy)[0]
    if len(buyable_idx) == 0:
        out = df.copy()
        out["wf_in_window"] = False
        out["wf_score"] = np.nan
        return out, {"wf_actual_start": None, "snapshots": []}

    exit_order = sorted(buyable_idx.tolist(), key=lambda i: (exit_dts[i], buy_dts[i], codes[i]))
    exit_order_arr = np.asarray(exit_order, dtype=np.int64)
    exit_dts_sorted = exit_dts[exit_order_arr]
    X_exit = X_all[exit_order_arr]
    r_exit = y_ret[exit_order_arr]
    w_exit = y_win[exit_order_arr]
    d_exit = day_ids_all[exit_order_arr]
    orig_exit = orig_arr[exit_order_arr] if orig_arr is not None else None

    first_buy_dt = buy_dts[buyable_idx].min()
    rare_fallback_dt = _add_months(str(first_buy_dt), min_warmup_months)

    # Group buyable indices by buy_date in chronological order
    by_dt_rows = {}
    for i in buyable_idx:
        by_dt_rows.setdefault(buy_dts[i], []).append(i)
    sorted_trade_dts = sorted(by_dt_rows.keys())

    wf_in_win = np.zeros(n, dtype=bool)
    wf_score = np.full(n, np.nan, dtype=np.float64)
    wf_delta = np.zeros(n, dtype=np.float64)
    thr_t30 = np.full(n, np.nan, dtype=np.float64)
    thr_t20 = np.full(n, np.nan, dtype=np.float64)
    thr_t10 = np.full(n, np.nan, dtype=np.float64)
    thr_t5 = np.full(n, np.nan, dtype=np.float64)

    ptr = 0
    n_exit_tot = len(exit_order_arr)
    started = False
    wf_actual_start = None
    current_card = None
    last_ptr = -1
    last_month = ""
    last_snap_month = ""
    snapshots = []
    n_rebuilds = 0

    for t in sorted_trade_dts:
        while ptr < n_exit_tot and exit_dts_sorted[ptr] < t:
            ptr += 1
        if t < wf_start_date:
            continue
        if not started:
            if (ptr >= min_warmup_trades) or (t >= rare_fallback_dt and ptr >= min_warmup_trades_rare):
                started = True
                wf_actual_start = t
            else:
                continue

        need_rebuild = (
            current_card is None
            or (recalc_freq == "daily" and ptr > last_ptr)
            or (recalc_freq == "monthly" and t[:7] != last_month)
        )
        if need_rebuild:
            current_card = fit_causal_scorecard(
                X_exit[:ptr], r_exit[:ptr], w_exit[:ptr], d_exit[:ptr],
                feature_names=feature_cols,
                mode=mode, top_k=top_k, min_k=min_k, max_corr=max_corr,
                min_t_stat=min_t_stat, shrink_tau=shrink_tau, max_delta=max_delta,
                orig_score_train=(orig_exit[:ptr] if orig_exit is not None else None),
                max_corr_orig=max_corr_orig,
            )
            last_ptr = ptr
            last_month = t[:7]
            n_rebuilds += 1
            if save_snapshot_freq == "daily" or t[:7] != last_snap_month:
                snapshots.append({"as_of_date": t, **current_card})
                last_snap_month = t[:7]

        rows_t = np.asarray(by_dt_rows[t], dtype=np.int64)
        sc_t = score_candidates_with_card(X_all[rows_t], current_card)
        wf_in_win[rows_t] = True
        if mode == "scorecard_0_100":
            wf_score[rows_t] = sc_t.astype(np.float64)
            thr_t30[rows_t] = current_card.get("train_score_q70_top30", 55)
            thr_t20[rows_t] = current_card.get("train_score_q80_top20", 60)
            thr_t10[rows_t] = current_card.get("train_score_q90_top10", 68)
            thr_t5[rows_t] = current_card.get("train_score_q95_top5", 73)
        else:
            wf_delta[rows_t] = sc_t.astype(np.float64)
            if orig_arr is not None:
                wf_score[rows_t] = orig_arr[rows_t] + sc_t.astype(np.float64)

    out = df.copy()
    out["can_buy_hygiene"] = can_buy
    out["wf_in_window"] = wf_in_win
    if mode == "scorecard_0_100":
        out["wf_score"] = wf_score
        out["wf_thr_top30"] = thr_t30
        out["wf_thr_top20"] = thr_t20
        out["wf_thr_top10"] = thr_t10
        out["wf_thr_top5"] = thr_t5
    else:
        out["wf_delta_score"] = wf_delta
        if orig_arr is not None:
            out["wf_new_score"] = np.where(wf_in_win, orig_arr + wf_delta, orig_arr)

    meta = {
        "mode": mode,
        "recalc_freq": recalc_freq,
        "wf_start_date_req": wf_start_date,
        "wf_actual_start": wf_actual_start,
        "n_rebuilds": n_rebuilds,
        "n_buyable_total": int(len(buyable_idx)),
        "n_wf_candidates": int(wf_in_win.sum()),
        "latest_scorecard": current_card,
        "snapshots": snapshots,
    }
    return out, meta

#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD036-B Modules 1 & 2 (`run_m1_m2_cold_and_pairwise.py`):
  Module 1: Cold-Day Condition (`mkt10 < 50`, plus `<40/<45/<55`) across all 5 strategies:
    - Pure regime skip / cold-only / threshold tighten & relax
    - Causal cold-day weak-atom disabling (`exit_date < t`) + static cold-LOO neighborhood
    - Cold-only & Regime-Split Mode B delta_patch
  Module 2: Cold-Day Condition x Pairwise Interactions (re-tested across all 5 strategies):
    - Clean mechanism interactions (130) + causal dynamic Top-18x17/2 pairs (incl. native atoms!)
    - FullPool vs ColdOnly vs ActiveOnly vs RegimeSplit vs Stacked-with-M1-ColdSurgery
    - 2-Way Pairwise Minefield Blacklist (15%) as direct baseline for Module 3's 3-way blacklist
    - Declustered (1/N_day weighted) handling for `pry`

Strictly exit_date < t causal. Zero yfinance. Peak RSS < 2.0 GB.
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import json
import math
import pickle
import sys
import time
from typing import Optional

import numpy as np
import pandas as pd

DIR = os.path.dirname(os.path.abspath(__file__))
if DIR not in sys.path:
    sys.path.insert(0, DIR)

import _common_rd036 as cm
import _wf_core as wfc
import _w2a4_data_and_features as w2f


def _cluster_t_weighted(u: np.ndarray, z: np.ndarray, day_ids: np.ndarray, weights: Optional[np.ndarray] = None) -> float:
    if weights is None:
        return wfc._cluster_t_stat(u, z, day_ids)
    n = len(u)
    if n < 15:
        return 0.0
    w = np.asarray(weights, dtype=np.float64)
    w = w / np.sum(w)
    mz = float(np.sum(w * z))
    mu = float(np.sum(w * u))
    dz = z - mz
    du = u - mu
    szz = float(np.sum(w * dz * dz))
    if szz <= 1e-12:
        return 0.0
    beta = float(np.sum(w * dz * du)) / szz
    eps = du - beta * dz
    _, g_inv = np.unique(day_ids, return_inverse=True)
    G = int(g_inv.max()) + 1
    if G < 5:
        return 0.0
    sg = np.bincount(g_inv, weights=w * dz * eps, minlength=G)
    var_b = (G / max(1, G - 1)) * float(np.dot(sg, sg)) / (szz * szz)
    if var_b <= 1e-18:
        return 0.0
    return float(beta / math.sqrt(var_b))


def _fit_delta_card_multi(
    X_tr: np.ndarray,
    y_ret: np.ndarray,
    y_win: np.ndarray,
    day_ids: np.ndarray,
    feat_names: list[str],
    max_deltas: tuple[int, ...],
    orig_tr: Optional[np.ndarray],
    top_k: int = 10,
    min_k: int = 4,
    max_corr: float = 0.65,
    max_corr_orig: Optional[float] = 0.70,
    min_t_stat: float = 1.0,
    shrink_tau: float = 20.0,
    decluster_days: bool = False,
) -> dict[int, dict]:
    """
    Fit causal delta_patch factor selection ONCE on exit_date < t, then emit exact
    integer cards for every `max_delta` in `max_deltas` (zero redundant t-stat/corr work).
    """
    M, F = X_tr.shape
    empty = {md: {"mode": "delta_patch", "factors": []} for md in max_deltas}
    if M < 12 or len(np.unique(day_ids)) < 5 or F == 0:
        return empty

    if decluster_days:
        _, g_inv = np.unique(day_ids, return_inverse=True)
        dc = np.bincount(g_inv)
        w_all = 1.0 / dc[g_inv]
        w_all = w_all / np.sum(w_all) * M
    else:
        w_all = np.ones(M, dtype=np.float64)

    min_valid_n = max(15, int(0.45 * M))
    cands = []
    for j in range(F):
        col = X_tr[:, j]
        valid = np.isfinite(col)
        nv = int(valid.sum())
        if nv < min_valid_n:
            continue
        xv = col[valid]
        if float(np.std(xv)) < 1e-12:
            continue
        rv, wv, dv, wt = y_ret[valid], y_win[valid], day_ids[valid], w_all[valid]
        wt_n = wt / np.sum(wt)
        mu0 = float(np.sum(wt_n * rv))
        wr0 = float(np.sum(wt_n * wv))
        sd_r = max(1e-5, float(np.sqrt(np.sum(wt_n * (rv - mu0) ** 2))))
        u = 0.6 * (rv - mu0) / sd_r + 0.4 * (wv - wr0) / 0.25

        uniq = np.unique(xv)
        if len(uniq) <= 3:
            edges = uniq.astype(float)
            b_idx = np.searchsorted(edges, xv, side="left")
            is_disc = True
            B = len(edges)
            if B < 2:
                continue
        else:
            q33, q67 = np.percentile(xv, [33.3333333, 66.6666667])
            min_bin = 5 if M < 80 else 8
            if q67 <= q33 + 1e-12:
                q50 = float(np.median(xv))
                b_idx = (xv > q50).astype(int)
                if b_idx.sum() < min_bin or (nv - b_idx.sum()) < min_bin:
                    b_idx = (xv >= q50).astype(int)
                if b_idx.sum() < min_bin or (nv - b_idx.sum()) < min_bin:
                    continue
                edges = np.array([q50], dtype=float)
                B = 2
            else:
                b_idx = np.where(xv <= q33, 0, np.where(xv <= q67, 1, 2))
                cnts = np.bincount(b_idx, minlength=3)
                if np.any(cnts < min_bin):
                    q50 = float(np.median(xv))
                    b_idx = (xv > q50).astype(int)
                    if b_idx.sum() < min_bin or (nv - b_idx.sum()) < min_bin:
                        continue
                    edges = np.array([q50], dtype=float)
                    B = 2
                else:
                    edges = np.array([float(q33), float(q67)], dtype=float)
                    B = 3
            is_disc = False

        w_cnts = np.bincount(b_idx, weights=wt, minlength=B)
        sum_r = np.bincount(b_idx, weights=wt * rv, minlength=B)
        sum_w = np.bincount(b_idx, weights=wt * wv, minlength=B)
        shr_dr = (sum_r + shrink_tau * mu0) / (w_cnts + shrink_tau) - mu0
        shr_dw = (sum_w + shrink_tau * wr0) / (w_cnts + shrink_tau) - wr0
        eff = 0.6 * (shr_dr / sd_r) + 0.4 * (shr_dw / 0.25)

        if B == 3:
            z_lin = b_idx.astype(float) - 1.0
            t_lin = _cluster_t_weighted(u, z_lin, dv, wt if decluster_days else None)
            z_quad = np.where(b_idx == 1, 1.0, -0.5)
            t_quad = _cluster_t_weighted(u, z_quad, dv, wt if decluster_days else None)
            if abs(t_quad) >= max(1.5, abs(t_lin) + 0.35):
                t_eff, shape = t_quad, "nonmonotone"
            else:
                lo_e, hi_e = min(eff[0], eff[2]), max(eff[0], eff[2])
                eff[1] = float(np.clip(eff[1], lo_e, hi_e))
                if abs(eff[2] - eff[0]) < 1e-12:
                    eff[2] += 1e-9 if t_lin >= 0 else -1e-9
                t_eff = t_lin
                shape = "monotone_up" if eff[2] >= eff[0] else "monotone_down"
        else:
            t_eff = _cluster_t_weighted(u, b_idx.astype(float), dv, wt if decluster_days else None)
            shape = "binary_up" if eff[-1] >= eff[0] else "binary_down"

        if max_corr_orig is not None and orig_tr is not None:
            ov = orig_tr[valid]
            m_ov = np.isfinite(ov)
            if m_ov.sum() >= 15 and np.std(ov[m_ov]) > 1e-12 and np.std(xv[m_ov]) > 1e-12:
                if abs(float(np.corrcoef(xv[m_ov], ov[m_ov])[0, 1])) > max_corr_orig:
                    continue

        cands.append({
            "col_idx": j, "name": feat_names[j], "abs_t": abs(float(t_eff)),
            "t_cluster": round(float(t_eff), 3), "shape": shape, "is_discrete": is_disc,
            "edges": edges, "eff": eff, "w_cnts": w_cnts,
        })

    cands.sort(key=lambda c: (-c["abs_t"], c["col_idx"]))
    sel = []
    for c in [x for x in cands if x["abs_t"] >= min_t_stat] + [x for x in cands if x["abs_t"] < min_t_stat]:
        if len(sel) >= top_k or (c["abs_t"] < min_t_stat and len(sel) >= min_k):
            break
        xj = X_tr[:, c["col_idx"]]
        ok = True
        for s in sel:
            xs = X_tr[:, s["col_idx"]]
            both = np.isfinite(xj) & np.isfinite(xs)
            if both.sum() >= 15 and np.std(xj[both]) > 1e-12 and np.std(xs[both]) > 1e-12:
                if abs(float(np.corrcoef(xj[both], xs[both])[0, 1])) > max_corr:
                    ok = False
                    break
        if ok:
            sel.append(c)

    if not sel:
        return empty

    t_w = np.array([min(4.0, max(0.25, c["abs_t"])) for c in sel], dtype=float)
    out = {}
    for md in max_deltas:
        bgts = wfc._largest_remainder_int(t_w, int(md))
        f_out = []
        for c, bgt in zip(sel, bgts):
            eff = c["eff"]
            emean = float(np.average(eff, weights=c["w_cnts"]))
            span = max(1e-12, float(np.max(np.abs(eff - emean))))
            pts = [int(round((float(e) - emean) / span * bgt)) for e in eff]
            f_out.append({
                "col_idx": c["col_idx"], "name": c["name"], "t_cluster": c["t_cluster"],
                "shape": c["shape"], "budget_pts": int(bgt), "is_discrete": c["is_discrete"],
                "edges": c["edges"].tolist(), "bin_pts": pts, "nan_pt": 0,
            })
        out[md] = {"mode": "delta_patch", "factors": f_out}
    return out


def _fit_pairwise_multi_delta(
    Xm_tr: np.ndarray,
    Xb_tr: np.ndarray,
    y_ret: np.ndarray,
    y_win: np.ndarray,
    day_ids: np.ndarray,
    mech_names: list[str],
    base_names: list[str],
    max_deltas: tuple[int, ...],
    orig_tr: Optional[np.ndarray],
    top_base_k: int = 18,
    max_dyn_keep: int = 25,
    min_cell: int = 20,
    decluster_days: bool = False,
) -> dict[int, dict]:
    """
    Causal exit_date < t pairwise screen (130 mech + Top-18x17/2 dynamic pairs) computed ONCE,
    then emitted for all `max_deltas` in one shot (~3x faster than calling separately).
    """
    M, F_mech = Xm_tr.shape
    F_base = Xb_tr.shape[1]
    empty = {md: {"mode": "delta_patch", "factors": [], "dyn_pairs_meta": []} for md in max_deltas}
    if M < max(12, min_cell) or len(np.unique(day_ids)) < 5:
        return empty

    mu0_all = float(np.mean(y_ret))
    wr0_all = float(np.mean(y_win))
    sd_all = max(1e-5, float(np.std(y_ret, ddof=1)))
    u_all = 0.6 * (y_ret - mu0_all) / sd_all + 0.4 * (y_win - wr0_all) / 0.25
    _, g_inv = np.unique(day_ids, return_inverse=True)
    G = int(g_inv.max()) + 1
    min_valid_n = max(15, int(0.45 * M))
    mc_use = min(min_cell, max(10, int(0.15 * M))) if M < 60 else max(min_cell, int(0.05 * M))
    min_t_dyn = 2.4 if M >= 100 else 2.0

    dyn_pairs_meta = []
    X_dyn_tr = np.empty((M, 0), dtype=np.float64)
    if F_base >= 2 and M >= 30 and G >= 5:
        fin_mask = np.isfinite(Xb_tr)
        cnt_valid = fin_mask.sum(axis=0)
        col_meds = np.nanmedian(Xb_tr, axis=0)
        col_meds = np.where(np.isfinite(col_meds), col_meds, 0.0)
        Xb_imp = np.where(fin_mask, Xb_tr, col_meds[None, :])
        col_stds = np.std(Xb_imp, axis=0)
        ok_idx = np.where((cnt_valid >= min_valid_n) & (col_stds > 1e-9))[0]

        if len(ok_idx) >= 2:
            t_base = w2f._batch_cluster_t_stats(u_all, Xb_imp[:, ok_idx], g_inv, G)
            order = np.argsort(-np.abs(t_base), kind="mergesort")
            sel_base = []
            min_side = 10 if M < 80 else 15
            for oi in order:
                j = int(ok_idx[oi])
                xj = Xb_imp[:, j]
                if any(abs(float(np.corrcoef(xj, Xb_imp[:, sj])[0, 1])) > 0.85 for sj, *_ in sel_base):
                    continue
                med_j = float(col_meds[j])
                n_gt = int(np.sum(xj > med_j))
                if n_gt >= min_side and (M - n_gt) >= min_side:
                    thr_j = med_j
                else:
                    mean_j = float(np.mean(xj))
                    n_gtm = int(np.sum(xj > mean_j))
                    if n_gtm >= min_side and (M - n_gtm) >= min_side:
                        thr_j = mean_j
                    else:
                        continue
                q25, q75 = np.percentile(xj, [25.0, 75.0])
                iqr_j = float(q75 - q25)
                if iqr_j <= 1e-9:
                    iqr_j = max(1e-6, float(col_stds[j]))
                tj = float(t_base[oi])
                sel_base.append((j, med_j, thr_j, iqr_j, 1.0 if tj >= 0 else -1.0, tj))
                if len(sel_base) >= top_base_k:
                    break

            K_sel = len(sel_base)
            if K_sel >= 2:
                Z_top = np.empty((M, K_sel), dtype=np.float64)
                HI_top = np.empty((M, K_sel), dtype=bool)
                for p_i, (j, med_j, thr_j, iqr_j, sgn_j, _) in enumerate(sel_base):
                    xj = np.where(np.isfinite(Xb_tr[:, j]), Xb_tr[:, j], med_j)
                    Z_top[:, p_i] = np.clip((xj - med_j) / iqr_j, -3.0, 3.0) * sgn_j
                    HI_top[:, p_i] = xj > thr_j

                pair_cols, pair_specs = [], []
                for a in range(K_sel):
                    za, ha = Z_top[:, a], HI_top[:, a]
                    na_name = base_names[sel_base[a][0]]
                    for b in range(a + 1, K_sel):
                        zb, hb = Z_top[:, b], HI_top[:, b]
                        nb_name = base_names[sel_base[b][0]]
                        for tag, vec in [
                            ("HiHi", (ha & hb).astype(np.float64)),
                            ("HiLo", (ha & (~hb)).astype(np.float64)),
                            ("LoHi", ((~ha) & hb).astype(np.float64)),
                            ("LoLo", ((~ha) & (~hb)).astype(np.float64)),
                            ("Prod", za * zb),
                        ]:
                            if tag != "Prod":
                                sv = float(vec.sum())
                                if sv < mc_use or (M - sv) < mc_use:
                                    continue
                            else:
                                if int(np.sum(np.abs(vec - float(np.median(vec))) > 1e-6)) < mc_use or float(np.std(vec)) <= 1e-6:
                                    continue
                            pair_cols.append(vec)
                            pair_specs.append((a, b, tag, f"dyn_{tag}__{na_name}__x__{nb_name}"))

                if pair_cols:
                    P_mat = np.column_stack(pair_cols)
                    t_pairs = w2f._batch_cluster_t_stats(u_all, P_mat, g_inv, G)
                    Zc = Z_top - np.mean(Z_top, axis=0, keepdims=True)
                    cand_dyn = []
                    # Vectorize prefilter by abs(t_p) >= min_t_dyn before residual check!
                    hit_idx = np.where(np.abs(t_pairs) >= min_t_dyn)[0]
                    for pi_idx in hit_idx:
                        a, b, tag, pname = pair_specs[pi_idx]
                        p_col = P_mat[:, pi_idx]
                        pc = p_col - np.mean(p_col)
                        za, zb = Zc[:, a], Zc[:, b]
                        saa, sbb, sab = float(np.dot(za, za)), float(np.dot(zb, zb)), float(np.dot(za, zb))
                        sap, sbp = float(np.dot(za, pc)), float(np.dot(zb, pc))
                        det = saa * sbb - sab * sab
                        if det > 1e-12:
                            resid = pc - ((sbb * sap - sab * sbp) / det) * za - ((saa * sbp - sab * sap) / det) * zb
                        else:
                            resid = pc - (sap / max(saa, 1e-12)) * za
                        if float(np.std(resid)) < 1e-6:
                            continue
                        t_syn = float(w2f._batch_cluster_t_stats(u_all, resid[:, None], g_inv, G)[0])
                        if abs(t_syn) >= 1.5:
                            cand_dyn.append((abs(float(t_pairs[pi_idx])), abs(t_syn), int(pi_idx), a, b, tag, pname))
                    cand_dyn.sort(key=lambda x: (-x[0], -x[1], x[6]))
                    cand_dyn = cand_dyn[:max_dyn_keep]
                    if cand_dyn:
                        X_dyn_tr = np.column_stack([P_mat[:, c[2]] for c in cand_dyn])
                        for _, t_syn, _, a, b, tag, pname in cand_dyn:
                            j_a, med_a, thr_a, iqr_a, sgn_a, _ = sel_base[a]
                            j_b, med_b, thr_b, iqr_b, sgn_b, _ = sel_base[b]
                            dyn_pairs_meta.append({
                                "name": pname, "tag": tag,
                                "j_a": j_a, "med_a": med_a, "thr_a": thr_a, "iqr_a": iqr_a, "sgn_a": sgn_a,
                                "j_b": j_b, "med_b": med_b, "thr_b": thr_b, "iqr_b": iqr_b, "sgn_b": sgn_b,
                                "t_synergy": round(t_syn, 3),
                            })

    min_supp = max(12 if M < 80 else 25, int(0.04 * M))
    valid_mech_idx = []
    for jm in range(F_mech):
        col = Xm_tr[:, jm]
        fin = np.isfinite(col)
        if int(fin.sum()) < min_valid_n:
            continue
        cv = col[fin]
        if int(np.sum(np.abs(cv - float(np.median(cv))) > 1e-6)) >= min_supp:
            valid_mech_idx.append(jm)
    X_mech_filt = Xm_tr[:, valid_mech_idx]
    mech_filt_names = [mech_names[jm] for jm in valid_mech_idx]

    X_comb = np.hstack([X_mech_filt, X_dyn_tr]) if X_dyn_tr.shape[1] > 0 else X_mech_filt
    comb_names = mech_filt_names + [d["name"] for d in dyn_pairs_meta]

    cards = _fit_delta_card_multi(
        X_comb, y_ret, y_win, day_ids, comb_names, max_deltas=max_deltas,
        orig_tr=orig_tr, top_k=10, min_k=4, max_corr=0.65, max_corr_orig=0.70,
        min_t_stat=1.0, shrink_tau=(15.0 if M < 100 else 20.0), decluster_days=decluster_days,
    )
    for md, card in cards.items():
        for f in card.get("factors", []):
            ci = f["col_idx"]
            f["col_idx"] = valid_mech_idx[ci] if ci < len(valid_mech_idx) else F_mech + (ci - len(valid_mech_idx))
        card["dyn_pairs_meta"] = dyn_pairs_meta
    return cards


def run_causal_cold_atom_disable(
    df: pd.DataFrame, af_cols: list[str], af_mat: np.ndarray,
    cold_cut: float = 50.0, t_cut: float = 0.0, bonus_only: bool = True, decluster_days: bool = False,
) -> np.ndarray:
    n = len(df)
    buy_dts = df["buy_date"].to_numpy(str)
    exit_dts = df["exit_date"].to_numpy(str)
    codes = df["code"].to_numpy(str)
    y_ret = df["net_ret_030"].to_numpy(float)
    can_buy = df["can_buy_hygiene"].to_numpy(bool)
    is_cold = (df["mkt10_zt_est_t1"].to_numpy(float) < cold_cut)
    orig = df["orig_score"].to_numpy(float)
    out_sc = orig.copy()

    uniq_dts = sorted(set(buy_dts.tolist()))
    dt_id = {d: i for i, d in enumerate(uniq_dts)}
    dids = np.array([dt_id[d] for d in buy_dts], dtype=np.int32)
    b_idx = np.where(can_buy)[0]
    ex_ord = np.asarray(sorted(b_idx.tolist(), key=lambda i: (exit_dts[i], buy_dts[i], codes[i])), dtype=np.int64)
    ex_dts = exit_dts[ex_ord]
    A_ex, r_ex, d_ex, c_ex = af_mat[ex_ord], y_ret[ex_ord], dids[ex_ord], is_cold[ex_ord]
    w_ex = (r_ex > 0.0).astype(float)

    by_dt_all = {}
    for i in range(n):
        by_dt_all.setdefault(buy_dts[i], []).append(i)
    is_bonus = np.array([np.max(af_mat[:, j]) > 0.0 for j in range(len(af_cols))], dtype=bool)
    ptr, last_ptr = 0, -1
    drop_mask = np.zeros(len(af_cols), dtype=bool)

    for t in sorted(by_dt_all.keys()):
        while ptr < len(ex_ord) and ex_dts[ptr] < t:
            ptr += 1
        if t < cm.WF_START or ptr < 10:
            continue
        if ptr > last_ptr:
            cm_tr = c_ex[:ptr]
            use_m = cm_tr if int(cm_tr.sum()) >= 10 else np.ones(ptr, dtype=bool)
            rv, wv, dv = r_ex[:ptr][use_m], w_ex[:ptr][use_m], d_ex[:ptr][use_m]
            wt = None
            if decluster_days:
                _, g_inv = np.unique(dv, return_inverse=True)
                wt = 1.0 / np.bincount(g_inv)[g_inv]
            mu0, wr0 = float(rv.mean()), float(wv.mean())
            sdr = max(1e-5, float(rv.std(ddof=1)))
            u = 0.6 * (rv - mu0) / sdr + 0.4 * (wv - wr0) / 0.25
            Atr = A_ex[:ptr][use_m]
            new_drop = np.zeros(len(af_cols), dtype=bool)
            for j in range(len(af_cols)):
                if bonus_only and not is_bonus[j]:
                    continue
                xj = Atr[:, j]
                if np.std(xj) < 1e-12:
                    continue
                if _cluster_t_weighted(u, xj, dv, wt) < t_cut:
                    new_drop[j] = True
            drop_mask = new_drop
            last_ptr = ptr

        rows_t = np.asarray(by_dt_all[t], dtype=np.int64)
        cold_t = is_cold[rows_t]
        if cold_t.any() and drop_mask.any():
            drop_pts = af_mat[rows_t[cold_t]][:, drop_mask].sum(axis=1)
            out_sc[rows_t[cold_t]] = orig[rows_t[cold_t]] - drop_pts
    return out_sc


def run_causal_regime_mode_b_multi(
    df: pd.DataFrame, feat_cols: list[str], cold_cut: float, regime_mode: str,
    max_deltas: tuple[int, ...] = (8, 12, 15), decluster_days: bool = False,
) -> dict[int, np.ndarray]:
    n = len(df)
    buy_dts = df["buy_date"].to_numpy(str)
    exit_dts = df["exit_date"].to_numpy(str)
    codes = df["code"].to_numpy(str)
    y_ret = df["net_ret_030"].to_numpy(float)
    can_buy = df["can_buy_hygiene"].to_numpy(bool)
    is_cold = (df["mkt10_zt_est_t1"].to_numpy(float) < cold_cut)
    orig = df["orig_score"].to_numpy(float)
    X_all = df[feat_cols].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=np.float64)

    uniq_dts = sorted(set(buy_dts.tolist()))
    dt_id = {d: i for i, d in enumerate(uniq_dts)}
    dids = np.array([dt_id[d] for d in buy_dts], dtype=np.int32)
    b_idx = np.where(can_buy)[0]
    ex_ord = np.asarray(sorted(b_idx.tolist(), key=lambda i: (exit_dts[i], buy_dts[i], codes[i])), dtype=np.int64)
    ex_dts = exit_dts[ex_ord]
    X_ex, r_ex, d_ex, c_ex, o_ex = X_all[ex_ord], y_ret[ex_ord], dids[ex_ord], is_cold[ex_ord], orig[ex_ord]
    w_ex = (r_ex > 0.0).astype(float)

    by_dt_all = {}
    for i in range(n):
        by_dt_all.setdefault(buy_dts[i], []).append(i)

    deltas_out = {md: np.zeros(n, dtype=np.float64) for md in max_deltas}
    ptr, last_ptr = 0, -1
    cards_f = cards_c = cards_a = None

    for t in sorted(by_dt_all.keys()):
        while ptr < len(ex_ord) and ex_dts[ptr] < t:
            ptr += 1
        if t < cm.WF_START or ptr < 12:
            continue
        if ptr > last_ptr:
            if regime_mode in ("full", "regime_split") or int(c_ex[:ptr].sum()) < 20 or int((~c_ex[:ptr]).sum()) < 20:
                cards_f = _fit_delta_card_multi(X_ex[:ptr], r_ex[:ptr], w_ex[:ptr], d_ex[:ptr], feat_cols, max_deltas, o_ex[:ptr], decluster_days=decluster_days)
            if regime_mode in ("cold_only", "regime_split") and int(c_ex[:ptr].sum()) >= 20:
                mc = c_ex[:ptr]
                cards_c = _fit_delta_card_multi(X_ex[:ptr][mc], r_ex[:ptr][mc], w_ex[:ptr][mc], d_ex[:ptr][mc], feat_cols, max_deltas, o_ex[:ptr][mc], decluster_days=decluster_days)
            if regime_mode in ("active_only", "regime_split") and int((~c_ex[:ptr]).sum()) >= 20:
                ma = ~c_ex[:ptr]
                cards_a = _fit_delta_card_multi(X_ex[:ptr][ma], r_ex[:ptr][ma], w_ex[:ptr][ma], d_ex[:ptr][ma], feat_cols, max_deltas, o_ex[:ptr][ma], decluster_days=decluster_days)
            last_ptr = ptr

        rows_t = np.asarray(by_dt_all[t], dtype=np.int64)
        cold_t = is_cold[rows_t]
        for md in max_deltas:
            if regime_mode == "full" and cards_f:
                deltas_out[md][rows_t] = wfc.score_candidates_with_card(X_all[rows_t], cards_f[md]).astype(float)
            elif regime_mode == "cold_only":
                uc = cards_c[md] if cards_c else (cards_f[md] if cards_f else None)
                if cold_t.any() and uc:
                    deltas_out[md][rows_t[cold_t]] = wfc.score_candidates_with_card(X_all[rows_t[cold_t]], uc).astype(float)
            elif regime_mode == "regime_split":
                uc = cards_c[md] if cards_c else (cards_f[md] if cards_f else None)
                ua = cards_a[md] if cards_a else (cards_f[md] if cards_f else None)
                if cold_t.any() and uc:
                    deltas_out[md][rows_t[cold_t]] = wfc.score_candidates_with_card(X_all[rows_t[cold_t]], uc).astype(float)
                if (~cold_t).any() and ua:
                    deltas_out[md][rows_t[~cold_t]] = wfc.score_candidates_with_card(X_all[rows_t[~cold_t]], ua).astype(float)
    return deltas_out


def run_causal_pairwise_multi(
    df: pd.DataFrame, mech_cols: list[str], base_cols: list[str],
    cold_cut: float = 50.0, regime_mode: str = "full", max_deltas: tuple[int, ...] = (8, 12, 15),
    min_cell: int = 20, decluster_days: bool = False,
) -> tuple[dict[int, np.ndarray], list[dict]]:
    n = len(df)
    buy_dts = df["buy_date"].to_numpy(str)
    exit_dts = df["exit_date"].to_numpy(str)
    codes = df["code"].to_numpy(str)
    y_ret = df["net_ret_030"].to_numpy(float)
    y_win = (y_ret > 0.0).astype(float)
    can_buy = df["can_buy_hygiene"].to_numpy(bool)
    is_cold = (df["mkt10_zt_est_t1"].to_numpy(float) < cold_cut)
    orig = df["orig_score"].to_numpy(float)

    X_m = df[mech_cols].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=np.float64)
    X_b = df[base_cols].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=np.float64)
    uniq_dts = sorted(set(buy_dts.tolist()))
    dt_id = {d: i for i, d in enumerate(uniq_dts)}
    dids = np.array([dt_id[d] for d in buy_dts], dtype=np.int32)
    b_idx = np.where(can_buy)[0]
    ex_ord = np.asarray(sorted(b_idx.tolist(), key=lambda i: (exit_dts[i], buy_dts[i], codes[i])), dtype=np.int64)
    ex_dts = exit_dts[ex_ord]
    Xm_ex, Xb_ex, r_ex, w_ex, d_ex, c_ex, o_ex = X_m[ex_ord], X_b[ex_ord], y_ret[ex_ord], y_win[ex_ord], dids[ex_ord], is_cold[ex_ord], orig[ex_ord]

    by_dt_all = {}
    for i in range(n):
        by_dt_all.setdefault(buy_dts[i], []).append(i)

    deltas_out = {md: np.zeros(n, dtype=np.float64) for md in max_deltas}
    ptr, last_ptr = 0, -1
    cf = cc = ca = None

    for t in sorted(by_dt_all.keys()):
        while ptr < len(ex_ord) and ex_dts[ptr] < t:
            ptr += 1
        if t < cm.WF_START or ptr < 12:
            continue
        if ptr > last_ptr:
            if regime_mode == "full" or int(c_ex[:ptr].sum()) < 25 or int((~c_ex[:ptr]).sum()) < 25:
                cf = _fit_pairwise_multi_delta(Xm_ex[:ptr], Xb_ex[:ptr], r_ex[:ptr], w_ex[:ptr], d_ex[:ptr], mech_cols, base_cols, max_deltas, o_ex[:ptr], min_cell=min_cell, decluster_days=decluster_days)
            if regime_mode in ("cold_only", "regime_split") and int(c_ex[:ptr].sum()) >= 25:
                mc = c_ex[:ptr]
                cc = _fit_pairwise_multi_delta(Xm_ex[:ptr][mc], Xb_ex[:ptr][mc], r_ex[:ptr][mc], w_ex[:ptr][mc], d_ex[:ptr][mc], mech_cols, base_cols, max_deltas, o_ex[:ptr][mc], min_cell=min_cell, decluster_days=decluster_days)
            if regime_mode in ("active_only", "regime_split") and int((~c_ex[:ptr]).sum()) >= 25:
                ma = ~c_ex[:ptr]
                ca = _fit_pairwise_multi_delta(Xm_ex[:ptr][ma], Xb_ex[:ptr][ma], r_ex[:ptr][ma], w_ex[:ptr][ma], d_ex[:ptr][ma], mech_cols, base_cols, max_deltas, o_ex[:ptr][ma], min_cell=min_cell, decluster_days=decluster_days)
            last_ptr = ptr

        rows_t = np.asarray(by_dt_all[t], dtype=np.int64)
        cold_t = is_cold[rows_t]
        for md in max_deltas:
            if regime_mode == "full" and cf:
                deltas_out[md][rows_t] = w2f.score_with_interaction_card(X_m[rows_t], X_b[rows_t], cf[md]).astype(float)
            elif regime_mode == "cold_only":
                uc = cc[md] if cc else (cf[md] if cf else None)
                if cold_t.any() and uc:
                    deltas_out[md][rows_t[cold_t]] = w2f.score_with_interaction_card(X_m[rows_t[cold_t]], X_b[rows_t[cold_t]], uc).astype(float)
            elif regime_mode == "active_only":
                ua = ca[md] if ca else (cf[md] if cf else None)
                if (~cold_t).any() and ua:
                    deltas_out[md][rows_t[~cold_t]] = w2f.score_with_interaction_card(X_m[rows_t[~cold_t]], X_b[rows_t[~cold_t]], ua).astype(float)
            elif regime_mode == "regime_split":
                uc = cc[md] if cc else (cf[md] if cf else None)
                ua = ca[md] if ca else (cf[md] if cf else None)
                if cold_t.any() and uc:
                    deltas_out[md][rows_t[cold_t]] = w2f.score_with_interaction_card(X_m[rows_t[cold_t]], X_b[rows_t[cold_t]], uc).astype(float)
                if (~cold_t).any() and ua:
                    deltas_out[md][rows_t[~cold_t]] = w2f.score_with_interaction_card(X_m[rows_t[~cold_t]], X_b[rows_t[~cold_t]], ua).astype(float)

    latest_rules = []
    md_ref = max_deltas[len(max_deltas) // 2]
    for tag, cd in [("full", cf), ("cold", cc), ("act", ca)]:
        if cd and cd[md_ref].get("factors"):
            for f in cd[md_ref]["factors"]:
                latest_rules.append({"regime": tag, "name": f["name"], "t": f["t_cluster"], "pts": f["bin_pts"]})
    return deltas_out, latest_rules


def run_causal_pairwise_mine_bl15(df: pd.DataFrame, mech_cols: list[str], base_cols: list[str], min_cell: int = 20) -> np.ndarray:
    """2-Way pairwise minefield blacklist top 15% (predicting net_ret <= -0.07) strictly exit_date < t."""
    n = len(df)
    buy_dts = df["buy_date"].to_numpy(str)
    exit_dts = df["exit_date"].to_numpy(str)
    codes = df["code"].to_numpy(str)
    y_ret = df["net_ret_030"].to_numpy(float)
    y_mine = (y_ret <= -0.07).astype(float)
    can_buy = df["can_buy_hygiene"].to_numpy(bool)

    X_m = df[mech_cols].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=np.float64)
    X_b = df[base_cols].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=np.float64)
    uniq_dts = sorted(set(buy_dts.tolist()))
    dt_id = {d: i for i, d in enumerate(uniq_dts)}
    dids = np.array([dt_id[d] for d in buy_dts], dtype=np.int32)
    b_idx = np.where(can_buy)[0]
    ex_ord = np.asarray(sorted(b_idx.tolist(), key=lambda i: (exit_dts[i], buy_dts[i], codes[i])), dtype=np.int64)
    ex_dts = exit_dts[ex_ord]
    Xm_ex, Xb_ex, ym_ex, d_ex = X_m[ex_ord], X_b[ex_ord], y_mine[ex_ord], dids[ex_ord]

    by_dt_all = {}
    for i in range(n):
        by_dt_all.setdefault(buy_dts[i], []).append(i)
    is_blk = np.zeros(n, dtype=bool)
    ptr, last_ptr = 0, -1
    card = None
    q85 = 100.0
    for t in sorted(by_dt_all.keys()):
        while ptr < len(ex_ord) and ex_dts[ptr] < t:
            ptr += 1
        if t < cm.WF_START or ptr < max(12, min_cell):
            continue
        if ptr > last_ptr:
            if float(ym_ex[:ptr].sum()) >= 3.0:
                card = w2f.fit_causal_interaction_scorecard(
                    Xm_ex[:ptr], Xb_ex[:ptr], ym_ex[:ptr], ym_ex[:ptr], d_ex[:ptr],
                    mech_names=mech_cols, base_names=base_cols, mode="scorecard_0_100",
                    top_k=8, min_k=3, max_corr=0.65, min_t_stat=1.0,
                    min_t_stat_dyn=2.2 if ptr >= 100 else 1.8, min_synergy_t=1.4,
                    shrink_tau=15.0, max_delta=10, orig_score_train=None, max_corr_orig=None,
                    top_base_k=16, max_dyn_keep=20,
                )
                tr_sc = w2f.score_with_interaction_card(Xm_ex[:ptr], Xb_ex[:ptr], card)
                q85 = float(np.percentile(tr_sc, 85.0))
            last_ptr = ptr
        rows_t = np.asarray(by_dt_all[t], dtype=np.int64)
        if card is not None and card.get("factors"):
            sc_t = w2f.score_with_interaction_card(X_m[rows_t], X_b[rows_t], card)
            is_blk[rows_t] = sc_t >= q85
    return is_blk


def main():
    t0 = time.time()
    bundle = cm.build_or_load_cache(force_rebuild=False)
    print(f"[M1+M2] Cache loaded in {time.time()-t0:.2f}s | RSS={cm.rss_mb()} MB", flush=True)
    diag = json.load(open(f"{cm.CACHE_DIR}/m1_diag.json", encoding="utf-8"))

    rows = []
    dr_map = {}
    rule_records = []

    def add_var(st, mod, vid, ps, sl):
        row, dr = cm.evaluate_variant_complete(bundle, st, mod, vid, ps, sl, perm_n=1000, eval_comb=True, eval_liq=True)
        rows.append(row)
        dr_map[f"{st}::{mod}::{vid}"] = dr
        return row

    for st in cm.OTHER5:
        t_st = time.time()
        df = bundle["pools"][st]
        orig = df["orig_score"].to_numpy(float)
        mkt10 = df["mkt10_zt_est_t1"].to_numpy(float)
        af_cols = bundle["atom_info"][st]["cols"]
        af_mat = bundle["atom_info"][st]["contrib_mat"]
        decluster = (st == "pry")
        min_cell = cm.MIN_LEAF_MAP[st]

        # 0. Baseline
        ps_b, sl_b = cm.sim_strategy(st, df, orig, wf_only=True)
        add_var(st, "M0_Baseline", "V20_Baseline_030", ps_b, sl_b)

        # MODULE 1: Cold-Day Condition (<40 / <45 / <50 / <55)
        for cut in (40, 45, 50, 55):
            ps, sl = cm.sim_strategy(st, df, orig, mask=(mkt10 >= cut), wf_only=True)
            add_var(st, "M1_ColdSkip", f"M1_SkipCold_cut{cut}", ps, sl)
            ps2, sl2 = cm.sim_strategy(st, df, orig, mask=(mkt10 < cut), wf_only=True)
            add_var(st, "M1_ColdOnly", f"M1_OnlyCold_cut{cut}", ps2, sl2)

        thr_steps = [10, 20] if st in ("1to2", "pry") else [4, 8]
        for cut in (45, 50):
            base_tv = df["thr_vec"].to_numpy(float) if st == "1to2" else np.full(len(df), cm.ORIG_THRESHOLDS[st])
            for step in thr_steps:
                ps, sl = cm.sim_strategy(st, df, orig, thr=np.where(mkt10 < cut, base_tv + step, base_tv), wf_only=True)
                add_var(st, "M1_ColdThr", f"M1_ColdTighten_cut{cut}_p{step}", ps, sl)
                ps, sl = cm.sim_strategy(st, df, orig, thr=np.where(mkt10 >= cut, base_tv + step, base_tv), wf_only=True)
                add_var(st, "M1_ActiveThr", f"M1_ActiveTighten_cut{cut}_p{step}", ps, sl)
            ps, sl = cm.sim_strategy(st, df, orig, thr=np.where(mkt10 < cut, base_tv - thr_steps[0], base_tv), wf_only=True)
            add_var(st, "M1_ColdThr", f"M1_ColdRelax_cut{cut}_m{thr_steps[0]}", ps, sl)

        for cut in (40, 45, 50, 55):
            for tc_lbl, tc_val in [("t0", 0.0), ("tm05", -0.5)]:
                sc_cd = run_causal_cold_atom_disable(df, af_cols, af_mat, cold_cut=float(cut), t_cut=tc_val, bonus_only=True, decluster_days=decluster)
                ps, sl = cm.sim_strategy(st, df, sc_cd, wf_only=True)
                add_var(st, "M1_CausalColdAtom", f"M1_CausalColdBonusDrop_cut{cut}_{tc_lbl}", ps, sl)
                if cut in (45, 50) and tc_lbl == "tm05":
                    sc_all_d = run_causal_cold_atom_disable(df, af_cols, af_mat, cold_cut=float(cut), t_cut=tc_val, bonus_only=False, decluster_days=decluster)
                    ps2, sl2 = cm.sim_strategy(st, df, sc_all_d, wf_only=True)
                    add_var(st, "M1_CausalColdAtom", f"M1_CausalColdAnyDrop_cut{cut}_{tc_lbl}", ps2, sl2)

        worst_atoms = [a["atom"] for a in diag["native_atom_cold_vs_active"][st][:2]]
        for cname in worst_atoms:
            j_idx = af_cols.index(cname)
            pts_j = af_mat[:, j_idx]
            for cut in (40, 45, 50, 55):
                ps, sl = cm.sim_strategy(st, df, np.where(mkt10 < cut, orig - pts_j, orig), wf_only=True)
                add_var(st, "M1_StaticColdLOO", f"M1_ColdLOO_{cname}_cut{cut}", ps, sl)
            ps, sl = cm.sim_strategy(st, df, orig - pts_j, wf_only=True)
            add_var(st, "M1_StaticAllLOO", f"M1_AllLOO_{cname}", ps, sl)

        feats_mb = list(dict.fromkeys(bundle["entry_num"] + bundle["xtr_cols"] + af_cols))
        for cut in (45, 50):
            for rmode in ("cold_only", "regime_split"):
                d_map = run_causal_regime_mode_b_multi(df, feats_mb, cold_cut=float(cut), regime_mode=rmode, max_deltas=(8, 12, 15), decluster_days=decluster)
                for md, dv in d_map.items():
                    ps, sl = cm.sim_strategy(st, df, orig + dv, wf_only=True)
                    add_var(st, "M1_ColdModeB", f"M1_ModeB_{rmode}_cut{cut}_d{md}", ps, sl)

        # MODULE 2: Cold-Day Condition x Pairwise Interactions
        base_pair_cols = list(dict.fromkeys(bundle["base_dyn_cols"] + af_cols))
        mech_cols = bundle["ix_cols"]
        sc_m1_stack = run_causal_cold_atom_disable(df, af_cols, af_mat, cold_cut=50.0, t_cut=-0.5, bonus_only=True, decluster_days=decluster)

        for rmode, cut_list in [("full", [50]), ("cold_only", [45, 50]), ("active_only", [50]), ("regime_split", [45, 50])]:
            for cut in cut_list:
                dp_map, lfac = run_causal_pairwise_multi(
                    df, mech_cols, base_pair_cols, cold_cut=float(cut),
                    regime_mode=rmode, max_deltas=(8, 12, 15), min_cell=min_cell, decluster_days=decluster,
                )
                for md, dv_p in dp_map.items():
                    lbl = f"M2_Pair_{rmode}_cut{cut}_d{md}" if rmode != "full" else f"M2_Pair_FullPool_d{md}"
                    ps, sl = cm.sim_strategy(st, df, orig + dv_p, wf_only=True)
                    add_var(st, "M2_ColdPairwise", lbl, ps, sl)
                    if rmode in ("full", "regime_split") and cut == 50 and md in (8, 12):
                        ps_s, sl_s = cm.sim_strategy(st, df, sc_m1_stack + dv_p, wf_only=True)
                        add_var(st, "M2_ColdPairwise", f"M2_StackM1Atom_{rmode}_cut50_d{md}", ps_s, sl_s)
                        if st == "pry":
                            ps_sp, sl_sp = cm.sim_strategy(st, df, orig + dv_p, mask=(mkt10 >= 50), wf_only=True)
                            add_var(st, "M2_ColdPairwise", f"M2_SkipCold50_Pair_{rmode}_d{md}", ps_sp, sl_sp)
                for lf in lfac[:6]:
                    rule_records.append({"strategy": st, "module": "M2_Pairwise", "variant": f"{rmode}_cut{cut}", **lf})

        is_blk2 = run_causal_pairwise_mine_bl15(df, mech_cols, base_pair_cols, min_cell=min_cell)
        ps_m2, sl_m2 = cm.sim_strategy(st, df, orig, mask=(~is_blk2), wf_only=True)
        add_var(st, "M2_PairMineBL", "M2_PairMineBL15_SafePool", ps_m2, sl_m2)

        print(f"  [{st} M1+M2 DONE in {time.time()-t_st:.1f}s] total variants={len(rows)} | RSS={cm.rss_mb()} MB", flush=True)

    df_m12 = pd.DataFrame(rows)
    df_m12.to_csv(f"{cm.CACHE_DIR}/m1_m2_grid.csv", index=False)
    with open(f"{cm.CACHE_DIR}/m1_m2_drs.pkl", "wb") as f:
        pickle.dump(dr_map, f)
    with open(f"{cm.CACHE_DIR}/m2_top_rules.json", "w", encoding="utf-8") as f:
        json.dump(cm.sanitize_json(rule_records), f, ensure_ascii=False, indent=2)

    print(f"\n[M1+M2 ALL DONE in {time.time()-t0:.1f}s] {len(df_m12)} variants | Peak RSS={cm.rss_mb()} MB")
    for st in cm.OTHER5:
        sub = df_m12[df_m12["strategy"] == st].sort_values("nav_wf", ascending=False)
        b_row = sub[sub["variant_id"] == "V20_Baseline_030"].iloc[0]
        print(f"\n--- Top 8 for {st} (Base: n={b_row['n_trades']}, nav={b_row['nav_wf']:.2f}x, sh={b_row['exact_mtm_sharpe']:.3f}, 2526={b_row['nav_2526']:.2f}x, 26h2={b_row['nav_26h2']:.2f}x, comb=1.000) ---")
        print(sub[["variant_id", "n_trades", "wr_pct", "nav_wf", "ex5_wf", "exact_mtm_sharpe", "nav_2526", "nav_26h2", "nav_80bps", "paired_t", "comb_nav_ratio"]].head(8).to_string(index=False))


if __name__ == "__main__":
    main()

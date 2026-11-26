#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Strictly Causal (exit_date < t) Multi-Factor Orthogonality & Shrinkage Regression Library.
Covers M1 (Cluster Consolidation), M2 (Partial-t Pruning), M3 (Lowdin Symmetric Orth),
M4 (Ridge / Lasso / ElasticNet / PLS), and M5 (V20 Prior + Gram-Schmidt Orth Residual).

Zero yfinance (D12). Deterministic & 100% truncation-invariant at 2024-12-31.
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import math
import sys
from typing import Optional

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.optimize import nnls
from scipy.spatial.distance import squareform
from sklearn.cross_decomposition import PLSRegression
from sklearn.linear_model import ElasticNet, Lasso

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True

WF_START = "2023-01-03"
WF_END = "2026-11-16"

# Curated orthogonal physical domain features (3-layer cycle + micro liquidity + community + mech ix)
PHYS_CORE_COLS = [
    "mkt10_zt_est_t1",
    "L1_zt_dt_logratio_t1",
    "L1_zb_rate_t1",
    "L2_ind_ex5_t1",
    "L2_kpl_zt1_t1",
    "L3_amp_comp_20v60_t1",
    "L3_pos_60d_t1",
    "sd_free_mcap_yi_t1",
    "sd_real_turn_pct_t1",
    "oh_cool_days_since_last_zt",
    "w24_xq_1d_pre",
    "ix_xq_burst_1d_vs_1y",
    "ix_ind_crowd_x_brd5_div",
    "ix_atr_comp_x_pos60",
]


def prepare_strategy_inputs(
    strat: str,
    df: pd.DataFrame,
    atom_info: dict,
    cand_ext_cols: list[str],
    use_cold50_for_20cm: bool = False,
) -> dict:
    """Extract aligned raw arrays, native atomic matrix, physical core matrix, and causal exit order."""
    n = len(df)
    buy_dts = df["buy_date"].astype(str).str[:10].to_numpy()
    exit_dts = df["exit_date"].astype(str).str[:10].to_numpy()
    codes = df["code"].astype(str).str.zfill(6).to_numpy()
    can_buy = df["can_buy_hygiene"].fillna(True).to_numpy(bool)
    y_ret = pd.to_numeric(df["net_ret_030"], errors="coerce").to_numpy(dtype=np.float64)
    can_buy = can_buy & np.isfinite(y_ret)

    if strat == "20cm" and use_cold50_for_20cm:
        f6 = pd.to_numeric(df["s20cm_F06_inst_net_pos"], errors="coerce").fillna(0.0).to_numpy(float)
        m10 = pd.to_numeric(df["mkt10_zt_est_t1"], errors="coerce").fillna(50.0).to_numpy(float)
        orig = np.where(m10 < 50.0, df["orig_score"].to_numpy(float) - f6, df["orig_score"].to_numpy(float))
    else:
        orig = df["orig_score"].to_numpy(dtype=np.float64)

    if strat == "20cm":
        acols = sorted([c for c in df.columns if c.startswith("s20cm_F")])
        amat = df[acols].fillna(0.0).to_numpy(dtype=np.float64)
        if use_cold50_for_20cm:
            idx_f6 = acols.index("s20cm_F06_inst_net_pos")
            m10 = pd.to_numeric(df["mkt10_zt_est_t1"], errors="coerce").fillna(50.0).to_numpy(float)
            amat = amat.copy()
            amat[m10 < 50.0, idx_f6] = 0.0
    else:
        acols = list(atom_info[strat]["cols"])
        amat = np.asarray(atom_info[strat]["contrib_mat"], dtype=np.float64)

    # For 1to2, orig_score = base_res + sum(s12_atom_*); for others, base_res is constant intercept
    base_res = orig - amat.sum(axis=1)

    pcols = [c for c in PHYS_CORE_COLS if c in df.columns]
    pmat = df[pcols].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=np.float64)

    ecols = [
        c for c in cand_ext_cols
        if c in df.columns and not c.startswith(("s12_", "s23_", "s34_", "shigh_", "spry_", "s20cm_", "v20_", "orig_", "bar_"))
    ]
    emat = df[ecols].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=np.float64)

    b_idx = np.where(can_buy)[0]
    ex_ord = np.asarray(sorted(b_idx.tolist(), key=lambda i: (exit_dts[i], buy_dts[i], codes[i])), dtype=np.int64)
    ex_dts = exit_dts[ex_ord]

    uniq_dts = sorted(set(buy_dts.tolist()))
    dt_id = {d: i for i, d in enumerate(uniq_dts)}
    dids = np.array([dt_id[d] for d in buy_dts], dtype=np.int32)

    by_dt_all = {}
    for i in range(n):
        by_dt_all.setdefault(buy_dts[i], []).append(i)

    return {
        "strat": strat,
        "n": n,
        "buy_dts": buy_dts,
        "exit_dts": exit_dts,
        "codes": codes,
        "can_buy": can_buy,
        "y_ret": y_ret,
        "orig": orig,
        "base_res": base_res,
        "acols": acols,
        "amat": amat,
        "pcols": pcols,
        "pmat": pmat,
        "ecols": ecols,
        "emat": emat,
        "ex_ord": ex_ord,
        "ex_dts": ex_dts,
        "dids": dids,
        "by_dt_all": by_dt_all,
        "sorted_dts": sorted(by_dt_all.keys()),
    }


def _causal_target(r_tr: np.ndarray, dids_tr: Optional[np.ndarray] = None, decluster: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """Compute winsorized utility target standardized on TR(t) plus optional day-decluster weights."""
    M = len(r_tr)
    if decluster and dids_tr is not None:
        _, g_inv = np.unique(dids_tr, return_inverse=True)
        dc = np.bincount(g_inv)
        w = 1.0 / dc[g_inv]
        w = w / np.sum(w) * M
    else:
        w = np.ones(M, dtype=np.float64)
    wn = w / np.sum(w)
    r_w = np.clip(r_tr, -0.20, 0.35)
    mu_r = float(np.sum(wn * r_w))
    sd_r = max(1e-5, float(np.sqrt(np.sum(wn * (r_w - mu_r) ** 2))))
    win = (r_tr > 0.0).astype(np.float64)
    mu_w = float(np.sum(wn * win))
    sd_w = max(0.10, float(np.sqrt(np.sum(wn * (win - mu_w) ** 2))))
    u = 0.6 * (r_w - mu_r) / sd_r + 0.4 * (win - mu_w) / sd_w
    mu_u = float(np.sum(wn * u))
    sd_u = max(1e-6, float(np.sqrt(np.sum(wn * (u - mu_u) ** 2))))
    return (u - mu_u) / sd_u, w


def _select_causal_dyncore(
    E_tr: np.ndarray,
    A_tr: np.ndarray,
    orig_tr: np.ndarray,
    y_z: np.ndarray,
    k_core: int = 8,
    max_corr_orig: float = 0.45,
    max_corr_pair: float = 0.45,
) -> list[tuple[int, float, float, float]]:
    """Select top-K low-correlation core features strictly on TR(t). Returns [(col_idx, med, sd, t_sign)]."""
    M, F = E_tr.shape
    if M < 25 or F == 0:
        return []
    fin = np.isfinite(E_tr)
    cnt = fin.sum(axis=0)
    keep_idx = np.where(cnt >= int(0.75 * M))[0]
    if len(keep_idx) == 0:
        return []
    Ev = np.where(fin[:, keep_idx], E_tr[:, keep_idx], np.nan)
    meds = np.nanmedian(Ev, axis=0)
    Ev = np.where(np.isnan(Ev), meds[None, :], Ev)
    stds = np.std(Ev, axis=0)
    nz = stds > 1e-12
    keep_idx = keep_idx[nz]
    Ev = Ev[:, nz]
    meds = meds[nz]
    stds = stds[nz]
    if len(keep_idx) == 0:
        return []
    Zv = (Ev - Ev.mean(axis=0)) / stds
    oz = (orig_tr - orig_tr.mean()) / max(1e-9, float(orig_tr.std()))
    r_orig = (Zv.T @ oz) / M
    r_y = (Zv.T @ y_z) / M

    # Also check correlation against nonzero native atoms
    astd = np.std(A_tr, axis=0)
    anz = astd > 1e-12
    if anz.any():
        Za = (A_tr[:, anz] - A_tr[:, anz].mean(axis=0)) / astd[anz]
        r_atoms = np.max(np.abs((Zv.T @ Za) / M), axis=1)
    else:
        r_atoms = np.zeros(len(keep_idx))

    cands = []
    for k in range(len(keep_idx)):
        if abs(r_orig[k]) <= max_corr_orig and r_atoms[k] <= max_corr_pair:
            cands.append((abs(float(r_y[k])), int(k)))
    cands.sort(key=lambda x: (-x[0], int(keep_idx[x[1]])))

    sel = []
    sel_vecs = []
    for _, k in cands:
        if len(sel) >= k_core:
            break
        zk = Zv[:, k]
        ok = True
        for zs in sel_vecs:
            if abs(float(np.dot(zk, zs)) / M) > max_corr_pair:
                ok = False
                break
        if ok:
            sgn = 1.0 if r_y[k] >= 0 else -1.0
            sel.append((int(keep_idx[k]), float(meds[k]), float(stds[k]), sgn))
            sel_vecs.append(zk)
    return sel


def _build_design_tr_te(
    inp: dict,
    tr_idx: np.ndarray,
    te_idx: np.ndarray,
    feat_set: str,
    y_z: np.ndarray,
    include_base_res_1to2: bool = False,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, int]:
    """
    Build clean standardized-ready (X_tr, X_te, prior_signs, is_atom_mask, n_raw_feats)
    strictly from TR(t) stats (zero lookahead).
    """
    A_tr = inp["amat"][tr_idx]
    A_te = inp["amat"][te_idx]
    orig_tr = inp["orig"][tr_idx]
    M = len(tr_idx)
    oz = (orig_tr - orig_tr.mean()) / max(1e-9, float(orig_tr.std()))

    cols_tr, cols_te, prior_signs, is_atom = [], [], [], []

    # Optionally include base_res for 1to2 when testing full-matrix regression
    if include_base_res_1to2 and inp["strat"] == "1to2":
        br_tr = inp["base_res"][tr_idx]
        br_te = inp["base_res"][te_idx]
        if float(np.std(br_tr)) > 1e-12:
            cols_tr.append(br_tr)
            cols_te.append(br_te)
            prior_signs.append(1.0)
            is_atom.append(True)

    # Native atoms
    for j in range(A_tr.shape[1]):
        v_tr = A_tr[:, j]
        if float(np.std(v_tr)) > 1e-12:
            cols_tr.append(v_tr)
            cols_te.append(A_te[:, j])
            prior_signs.append(1.0)
            is_atom.append(True)

    # External core features
    if feat_set == "B_PhysCore" and inp["pmat"].shape[1] > 0:
        P_tr = inp["pmat"][tr_idx]
        P_te = inp["pmat"][te_idx]
        for j in range(P_tr.shape[1]):
            v_tr = P_tr[:, j]
            fin = np.isfinite(v_tr)
            if fin.mean() < 0.70:
                continue
            med = float(np.nanmedian(v_tr))
            v_tr_imp = np.where(fin, v_tr, med)
            sd = float(np.std(v_tr_imp))
            if sd < 1e-12:
                continue
            vz = (v_tr_imp - float(np.mean(v_tr_imp))) / sd
            ro = abs(float(np.dot(vz, oz)) / M)
            if ro > 0.45:
                continue
            ry = float(np.dot(vz, y_z)) / M
            v_te = P_te[:, j]
            v_te_imp = np.where(np.isfinite(v_te), v_te, med)
            cols_tr.append(v_tr_imp)
            cols_te.append(v_te_imp)
            prior_signs.append(1.0 if ry >= 0 else -1.0)
            is_atom.append(False)
    elif feat_set == "C_DynCore" and M >= 30 and inp["emat"].shape[1] > 0:
        sel = _select_causal_dyncore(inp["emat"][tr_idx], A_tr, orig_tr, y_z, k_core=8)
        for cidx, med, _, sgn in sel:
            v_tr = inp["emat"][tr_idx, cidx]
            v_te = inp["emat"][te_idx, cidx]
            cols_tr.append(np.where(np.isfinite(v_tr), v_tr, med))
            cols_te.append(np.where(np.isfinite(v_te), v_te, med))
            prior_signs.append(sgn)
            is_atom.append(False)

    if not cols_tr:
        return np.empty((M, 0)), np.empty((len(te_idx), 0)), np.empty(0), np.empty(0, dtype=bool), 0
    X_tr = np.column_stack(cols_tr)
    X_te = np.column_stack(cols_te)
    return X_tr, X_te, np.asarray(prior_signs, dtype=float), np.asarray(is_atom, dtype=bool), len(cols_tr)


def _align_to_orig(
    s_raw_tr: np.ndarray,
    s_raw_te: np.ndarray,
    orig_tr: np.ndarray,
    anchor_tr: Optional[np.ndarray] = None,
    anchor_te: Optional[np.ndarray] = None,
) -> np.ndarray:
    """Align raw model predictions onto exact V20 score scale using ONLY TR(t) mean/std."""
    sd_raw = float(np.std(s_raw_tr))
    mu_raw = float(np.mean(s_raw_tr))
    if anchor_tr is not None and anchor_te is not None:
        tgt_tr = orig_tr - anchor_tr
        if sd_raw < 1e-9:
            return anchor_te + float(np.mean(tgt_tr))
        sd_t = max(1e-9, float(np.std(tgt_tr)))
        mu_t = float(np.mean(tgt_tr))
        return anchor_te + ((s_raw_te - mu_raw) / sd_raw) * sd_t + mu_t
    if sd_raw < 1e-9:
        return np.full(len(s_raw_te), float(np.mean(orig_tr)), dtype=float)
    sd_o = max(1e-9, float(np.std(orig_tr)))
    mu_o = float(np.mean(orig_tr))
    return ((s_raw_te - mu_raw) / sd_raw) * sd_o + mu_o


def _fit_ridge(Z_tr: np.ndarray, y_z: np.ndarray, alpha: float, w: Optional[np.ndarray] = None) -> np.ndarray:
    p = Z_tr.shape[1]
    if p == 0:
        return np.empty(0)
    if w is not None:
        sw = np.sqrt(w)[:, None]
        Zw = Z_tr * sw
        yw = y_z * np.sqrt(w)
    else:
        Zw, yw = Z_tr, y_z
    A = Zw.T @ Zw + float(alpha) * np.eye(p)
    return np.linalg.solve(A, Zw.T @ yw)


def _fit_nnls_ridge(Z_tr: np.ndarray, y_z: np.ndarray, alpha: float, w: Optional[np.ndarray] = None) -> np.ndarray:
    p = Z_tr.shape[1]
    if p == 0:
        return np.empty(0)
    if w is not None:
        sw = np.sqrt(w)[:, None]
        Zw = Z_tr * sw
        yw = y_z * np.sqrt(w)
    else:
        Zw, yw = Z_tr, y_z
    A_aug = np.vstack([Zw, math.sqrt(max(1e-6, float(alpha))) * np.eye(p)])
    b_aug = np.concatenate([yw, np.zeros(p)])
    coef, _ = nnls(A_aug, b_aug)
    return coef


def _eval_one_day_model(
    inp: dict,
    tr_idx: np.ndarray,
    te_idx: np.ndarray,
    spec: dict,
    y_z: np.ndarray,
    w_tr: np.ndarray,
    design_tuple: tuple,
) -> tuple[np.ndarray, int, int]:
    """
    Fit and score ONE causal step at day t using ONLY tr_idx (exit_date < t).
    Returns (scores_te, n_raw_feats, n_eff_feats).
    """
    method = spec["method"]
    feat_set = spec["feat_set"]
    strat = inp["strat"]
    M = len(tr_idx)
    orig_tr = inp["orig"][tr_idx]
    orig_te = inp["orig"][te_idx]

    keep_anchor = (strat == "1to2") and spec.get("anchor_1to2", True)
    anchor_tr = inp["base_res"][tr_idx] if keep_anchor else None
    anchor_te = inp["base_res"][te_idx] if keep_anchor else None

    X_tr, X_te, p_signs, is_atom, n_raw = design_tuple
    p = X_tr.shape[1]
    if p == 0:
        return orig_te.copy(), 0, 0

    mu_x = X_tr.mean(axis=0)
    sd_x = np.maximum(1e-12, X_tr.std(axis=0))
    Z_tr = (X_tr - mu_x) / sd_x
    Z_te = (X_te - mu_x) / sd_x

    # ------------------------------------------------------------------
    # M1: Cluster Consolidation
    # ------------------------------------------------------------------
    if method == "M1":
        r_cut = float(spec["r_cut"])
        dist_mode = spec.get("dist_mode", "signed")  # "signed" or "abs"
        agg_mode = spec.get("agg_mode", "eq_z")      # "eq_z" or "inv_var"
        outer = spec.get("outer", "prior_v20")       # "prior_v20", "prior_eqz", "nnls", "ridge"

        if p == 1:
            C_tr, C_te, c_signs, c_scales, n_eff = Z_tr, Z_te, p_signs.copy(), sd_x.copy(), 1
        else:
            R = (Z_tr.T @ Z_tr) / M
            R = np.clip(0.5 * (R + R.T), -1.0, 1.0)
            D = (1.0 - R) if dist_mode == "signed" else (1.0 - np.abs(R))
            np.fill_diagonal(D, 0.0)
            D = np.maximum(0.0, D)
            Z_link = linkage(squareform(D, checks=False), method="complete")
            lbls = fcluster(Z_link, t=(1.0 - r_cut), criterion="distance")
            uniq_lbls = sorted(set(lbls.tolist()))
            n_eff = len(uniq_lbls)
            cl_tr_list, cl_te_list, c_signs, c_scales = [], [], [], []
            for lb in uniq_lbls:
                members = [j for j, l in enumerate(lbls) if l == lb]
                if len(members) == 1:
                    j0 = members[0]
                    cl_tr_list.append(Z_tr[:, j0])
                    cl_te_list.append(Z_te[:, j0])
                    c_signs.append(p_signs[j0])
                    c_scales.append(sd_x[j0] if is_atom[j0] else float(np.median(sd_x)))
                else:
                    anchor_j = members[0]
                    align_sgn = []
                    for mj in members:
                        if dist_mode == "abs" and R[anchor_j, mj] < 0:
                            align_sgn.append(-1.0)
                        else:
                            align_sgn.append(1.0)
                    if agg_mode == "inv_var":
                        inv_v = np.array([1.0 / max(1e-6, sd_x[mj] ** 2) for mj in members])
                        mw = (inv_v / inv_v.sum()) * np.asarray(align_sgn)
                    else:
                        mw = np.asarray(align_sgn) / len(members)
                    v_c_tr = Z_tr[:, members] @ mw
                    v_c_te = Z_te[:, members] @ mw
                    sd_c = max(1e-9, float(np.std(v_c_tr)))
                    cl_tr_list.append(v_c_tr / sd_c)
                    cl_te_list.append(v_c_te / sd_c)
                    atom_m = [mj for mj in members if is_atom[mj]]
                    if atom_m:
                        c_signs.append(1.0)
                        c_scales.append(float(np.mean([sd_x[mj] for mj in atom_m])))
                    else:
                        ry_c = float(np.dot(v_c_tr / sd_c, y_z)) / M
                        c_signs.append(1.0 if ry_c >= 0 else -1.0)
                        c_scales.append(float(np.median(sd_x)))
            C_tr = np.column_stack(cl_tr_list)
            C_te = np.column_stack(cl_te_list)
            c_signs = np.asarray(c_signs, dtype=float)
            c_scales = np.asarray(c_scales, dtype=float)

        if outer == "prior_v20":
            # Preserves V20 relative point scales on unclustered factors while removing duplicate double-counting
            w_out = c_signs * c_scales
        elif outer in ("prior", "prior_eqz"):
            w_out = c_signs
        elif outer == "nnls":
            C_tr_s = C_tr * c_signs[None, :]
            C_te_s = C_te * c_signs[None, :]
            w_pos = _fit_nnls_ridge(C_tr_s, y_z, alpha=float(spec.get("alpha", 30.0)), w=w_tr)
            s_raw_tr = C_tr_s @ w_pos
            s_raw_te = C_te_s @ w_pos
            return _align_to_orig(s_raw_tr, s_raw_te, orig_tr, anchor_tr, anchor_te), n_raw, n_eff
        else:
            w_out = _fit_ridge(C_tr, y_z, alpha=float(spec.get("alpha", 50.0)), w=w_tr)

        s_raw_tr = C_tr @ w_out
        s_raw_te = C_te @ w_out
        return _align_to_orig(s_raw_tr, s_raw_te, orig_tr, anchor_tr, anchor_te), n_raw, n_eff

    # ------------------------------------------------------------------
    # M2: Causal Partial-t Pruning
    # ------------------------------------------------------------------
    if method == "M2":
        lam = float(spec.get("lam", 20.0))
        t_cut = float(spec.get("t_cut", 0.0))
        mode_m2 = spec.get("mode", "prior_aligned")  # "prior_raw", "prior_aligned", "ridge_refit"

        sw = np.sqrt(w_tr)[:, None]
        Zw = Z_tr * sw
        yw = y_z * np.sqrt(w_tr)
        ZtZ = Zw.T @ Zw
        A = ZtZ + lam * np.eye(p)
        A_inv = np.linalg.inv(A)
        beta = A_inv @ (Zw.T @ yw)
        resid = yw - Zw @ beta
        df_eff = float(np.trace(ZtZ @ A_inv))
        dof = max(3.0, float(M) - df_eff)
        sigma2 = float(np.dot(resid, resid)) / dof
        cov_b = sigma2 * (A_inv @ ZtZ @ A_inv)
        se_b = np.sqrt(np.maximum(1e-12, np.diag(cov_b)))
        t_stats = beta / se_b

        # Orient sign test vs prior sign for atoms (since atoms are pre-signed +, negative t means wrong sign/harmful)
        # For external core features (prior sign already matched univariate sign), keep if t * p_sign > t_cut
        signed_t = t_stats * p_signs
        keep_mask = signed_t > t_cut
        n_eff = int(keep_mask.sum())

        if mode_m2 == "prior_raw" and feat_set == "A_Atoms":
            # Exact additive drop on raw contributions (matches RD036 causal atom drop paradigm)
            if n_eff == p:
                return orig_te.copy(), n_raw, n_eff
            drop_cols = ~keep_mask
            drop_sum = X_te[:, drop_cols].sum(axis=1)
            return orig_te - drop_sum, n_raw, n_eff

        if n_eff == 0:
            return _align_to_orig(np.zeros(M), np.zeros(len(te_idx)), orig_tr, anchor_tr, anchor_te), n_raw, 0

        if mode_m2 == "ridge_refit":
            Zk_tr = Z_tr[:, keep_mask]
            Zk_te = Z_te[:, keep_mask]
            wk = _fit_ridge(Zk_tr, y_z, alpha=float(spec.get("alpha", 50.0)), w=w_tr)
            return _align_to_orig(Zk_tr @ wk, Zk_te @ wk, orig_tr, anchor_tr, anchor_te), n_raw, n_eff

        # prior_aligned: keep surviving features with V20 raw scale (atoms) or unit prior sign
        if feat_set == "A_Atoms":
            s_raw_tr = X_tr[:, keep_mask].sum(axis=1)
            s_raw_te = X_te[:, keep_mask].sum(axis=1)
        else:
            s_raw_tr = Z_tr[:, keep_mask] @ p_signs[keep_mask]
            s_raw_te = Z_te[:, keep_mask] @ p_signs[keep_mask]
        return _align_to_orig(s_raw_tr, s_raw_te, orig_tr, anchor_tr, anchor_te), n_raw, n_eff

    # ------------------------------------------------------------------
    # M3: Lowdin Symmetric Orthogonalization X_orth = Z @ Sigma_reg^{-1/2}
    # ------------------------------------------------------------------
    if method == "M3":
        eps = float(spec.get("eps", 0.15))
        outer = spec.get("outer", "prior")  # "prior", "nnls", "ridge"
        Sigma = (Z_tr.T @ Z_tr) / M
        Sigma = 0.5 * (Sigma + Sigma.T)
        Sigma_reg = (1.0 - eps) * Sigma + eps * np.eye(p)
        vals, vecs = np.linalg.eigh(Sigma_reg)
        inv_sqrt = (vecs / np.sqrt(np.maximum(vals, 1e-8))[None, :]) @ vecs.T
        Xo_tr = Z_tr @ inv_sqrt
        Xo_te = Z_te @ inv_sqrt

        if outer == "prior_v20":
            w_out = p_signs * np.where(is_atom, sd_x, float(np.median(sd_x)))
        elif outer in ("prior", "prior_eqz"):
            w_out = p_signs
        elif outer == "nnls":
            Xo_tr_s = Xo_tr * p_signs[None, :]
            Xo_te_s = Xo_te * p_signs[None, :]
            w_pos = _fit_nnls_ridge(Xo_tr_s, y_z, alpha=float(spec.get("alpha", 30.0)), w=w_tr)
            n_eff = int(np.sum(w_pos > 1e-6))
            return _align_to_orig(Xo_tr_s @ w_pos, Xo_te_s @ w_pos, orig_tr, anchor_tr, anchor_te), n_raw, n_eff
        else:
            w_out = _fit_ridge(Xo_tr, y_z, alpha=float(spec.get("alpha", 50.0)), w=w_tr)

        n_eff = int(np.sum(np.abs(w_out) > 1e-6))
        return _align_to_orig(Xo_tr @ w_out, Xo_te @ w_out, orig_tr, anchor_tr, anchor_te), n_raw, n_eff

    # ------------------------------------------------------------------
    # M4: Sparse / Shrinkage Multi-Factor Regression (Ridge / Lasso / ENet / PLS)
    # ------------------------------------------------------------------
    if method == "M4":
        reg_type = spec["reg_type"]
        if reg_type == "ridge":
            w_out = _fit_ridge(Z_tr, y_z, alpha=float(spec["alpha"]), w=w_tr)
            s_raw_tr = Z_tr @ w_out
            s_raw_te = Z_te @ w_out
            n_eff = p
        elif reg_type == "lasso":
            mdl = Lasso(alpha=float(spec["alpha"]), fit_intercept=False, max_iter=1500, tol=1e-4)
            mdl.fit(Z_tr, y_z, sample_weight=w_tr)
            w_out = mdl.coef_
            n_eff = int(np.sum(np.abs(w_out) > 1e-6))
            s_raw_tr = Z_tr @ w_out
            s_raw_te = Z_te @ w_out
        elif reg_type == "enet":
            mdl = ElasticNet(alpha=float(spec["alpha"]), l1_ratio=float(spec.get("l1_ratio", 0.5)), fit_intercept=False, max_iter=1500, tol=1e-4)
            mdl.fit(Z_tr, y_z, sample_weight=w_tr)
            w_out = mdl.coef_
            n_eff = int(np.sum(np.abs(w_out) > 1e-6))
            s_raw_tr = Z_tr @ w_out
            s_raw_te = Z_te @ w_out
        elif reg_type == "pls":
            nc = min(int(spec["n_comp"]), p, max(1, M - 2))
            mdl = PLSRegression(n_components=nc, scale=False, max_iter=500)
            mdl.fit(Z_tr, y_z)
            s_raw_tr = mdl.predict(Z_tr).ravel()
            s_raw_te = mdl.predict(Z_te).ravel()
            n_eff = nc
        else:
            raise ValueError(reg_type)
        return _align_to_orig(s_raw_tr, s_raw_te, orig_tr, anchor_tr, anchor_te), n_raw, n_eff

    # ------------------------------------------------------------------
    # M5: V20 Prior + Gram-Schmidt Orthogonal Residual
    # ------------------------------------------------------------------
    if method == "M5":
        mu_o = float(orig_tr.mean())
        sd_o = float(orig_tr.std())
        if sd_o < 1e-9:
            return orig_te.copy(), n_raw, 0
        oc_tr = orig_tr - mu_o
        oc_te = orig_te - mu_o
        var_o = float(np.dot(oc_tr, oc_tr))

        # Project every column in X onto [1, orig_tr] and keep purely orthogonal residual
        orth_tr_cols, orth_te_cols = [], []
        for j in range(p):
            xc_tr = X_tr[:, j] - float(X_tr[:, j].mean())
            xc_te = X_te[:, j] - float(X_tr[:, j].mean())
            proj = float(np.dot(xc_tr, oc_tr)) / var_o
            r_tr_j = xc_tr - proj * oc_tr
            r_te_j = xc_te - proj * oc_te
            sd_rj = float(np.std(r_tr_j))
            if sd_rj > 1e-5 * sd_x[j]:
                orth_tr_cols.append(r_tr_j / sd_rj)
                orth_te_cols.append(r_te_j / sd_rj)

        if not orth_tr_cols:
            return orig_te.copy(), n_raw, 0
        Zo_tr = np.column_stack(orth_tr_cols)
        Zo_te = np.column_stack(orth_te_cols)
        p_orth = Zo_tr.shape[1]

        # Residualize target against orig_tr so fit only learns pure orthogonal alpha
        oz = oc_tr / sd_o
        y_orth = y_z - (float(np.dot(y_z, oz)) / M) * oz

        reg_type = spec.get("reg_type", "ridge")
        if reg_type == "ridge":
            beta = _fit_ridge(Zo_tr, y_orth, alpha=float(spec.get("alpha", 200.0)), w=w_tr)
            res_tr = Zo_tr @ beta
            res_te = Zo_te @ beta
            n_eff = p_orth
        elif reg_type == "enet":
            mdl = ElasticNet(alpha=float(spec.get("alpha", 0.06)), l1_ratio=0.5, fit_intercept=False, max_iter=1500, tol=1e-4)
            mdl.fit(Zo_tr, y_orth, sample_weight=w_tr)
            beta = mdl.coef_
            n_eff = int(np.sum(np.abs(beta) > 1e-6))
            res_tr = Zo_tr @ beta
            res_te = Zo_te @ beta
        elif reg_type == "pls":
            nc = min(int(spec.get("n_comp", 2)), p_orth, max(1, M - 2))
            mdl = PLSRegression(n_components=nc, scale=False, max_iter=500)
            mdl.fit(Zo_tr, y_orth)
            res_tr = mdl.predict(Zo_tr).ravel()
            res_te = mdl.predict(Zo_te).ravel()
            n_eff = nc
        else:
            raise ValueError(reg_type)

        sd_res = float(np.std(res_tr))
        if sd_res < 1e-9:
            return orig_te.copy(), n_raw, 0
        gamma = float(spec.get("gamma", 0.30))
        cap = float(spec.get("cap", 15.0))
        delta_te = np.clip(gamma * ((res_te - float(res_tr.mean())) / sd_res) * sd_o, -cap, cap)
        return orig_te + delta_te, n_raw, n_eff

    raise ValueError(f"Unknown method: {method}")


def run_causal_ortho_wf(
    inp: dict,
    specs: list[dict],
    wf_start: str = WF_START,
    min_warmup_override: Optional[int] = None,
    decluster_pry: bool = True,
) -> dict[str, dict]:
    """
    Run a batch of model specs in strictly causal day-by-day walk-forward (`exit_date < t`)
    with shared sorted calendar loop. Guarantees zero lookahead & exact 2024-12-31 truncation invariance.
    """
    n = inp["n"]
    strat = inp["strat"]
    min_ptr = min_warmup_override if min_warmup_override is not None else (12 if strat == "high" else 40)
    decluster = decluster_pry and (strat == "pry")

    ex_ord = inp["ex_ord"]
    ex_dts = inp["ex_dts"]
    n_ex = len(ex_ord)

    results = {}
    for sp in specs:
        results[sp["variant_id"]] = {
            "score": inp["orig"].copy(),
            "n_raw_list": [],
            "n_eff_list": [],
            "n_wf_days": 0,
        }

    ptr = 0
    last_ptr = -1
    y_z = None
    w_tr = None
    tr_idx = None

    for t in inp["sorted_dts"]:
        while ptr < n_ex and ex_dts[ptr] < t:
            ptr += 1
        if t < wf_start or ptr < min_ptr:
            continue

        rows_t = np.asarray(inp["by_dt_all"][t], dtype=np.int64)
        if ptr > last_ptr:
            tr_idx = ex_ord[:ptr]
            y_z, w_tr = _causal_target(inp["y_ret"][tr_idx], dids_tr=inp["dids"][tr_idx], decluster=decluster)
            last_ptr = ptr

        # Build & cache design matrix per (feat_set, inc_br) ONCE per day t across all specs
        design_cache = {}
        for sp in specs:
            fs = sp["feat_set"]
            inc_br = (strat == "1to2") and (not sp.get("anchor_1to2", True))
            ck = (fs, inc_br)
            if ck not in design_cache:
                design_cache[ck] = _build_design_tr_te(
                    inp, tr_idx, rows_t, feat_set=fs, y_z=y_z, include_base_res_1to2=inc_br
                )
            sc_t, n_raw, n_eff = _eval_one_day_model(inp, tr_idx, rows_t, sp, y_z, w_tr, design_cache[ck])
            res = results[sp["variant_id"]]
            res["score"][rows_t] = sc_t
            res["n_raw_list"].append(n_raw)
            res["n_eff_list"].append(n_eff)
            res["n_wf_days"] += 1

    # Summarize compression metadata
    for vid, res in results.items():
        if res["n_raw_list"]:
            res["avg_n_raw"] = round(float(np.mean(res["n_raw_list"])), 2)
            res["avg_n_eff"] = round(float(np.mean(res["n_eff_list"])), 2)
            res["final_n_raw"] = int(res["n_raw_list"][-1])
            res["final_n_eff"] = int(res["n_eff_list"][-1])
            res["compression_ratio"] = round(float(res["avg_n_eff"] / max(1e-9, res["avg_n_raw"])), 3)
        else:
            res["avg_n_raw"] = 0.0
            res["avg_n_eff"] = 0.0
            res["final_n_raw"] = 0
            res["final_n_eff"] = 0
            res["compression_ratio"] = 1.0
        del res["n_raw_list"]
        del res["n_eff_list"]
    return results


def build_standard_spec_grid() -> list[dict]:
    """Build unified M1..M5 experimental grid across Set A (Atoms_Only), Set B (PhysCore), and Set C (DynCore)."""
    specs = []
    for feat_set in ("A_Atoms", "B_PhysCore", "C_DynCore"):
        # M1: Cluster Consolidation
        specs.extend([
            {"variant_id": f"M1_sign_r35_eq_v20sc__{feat_set}", "method": "M1", "feat_set": feat_set, "r_cut": 0.35, "dist_mode": "signed", "agg_mode": "eq_z", "outer": "prior_v20"},
            {"variant_id": f"M1_sign_r35_invv_v20sc__{feat_set}", "method": "M1", "feat_set": feat_set, "r_cut": 0.35, "dist_mode": "signed", "agg_mode": "inv_var", "outer": "prior_v20"},
            {"variant_id": f"M1_sign_r45_eq_v20sc__{feat_set}", "method": "M1", "feat_set": feat_set, "r_cut": 0.45, "dist_mode": "signed", "agg_mode": "eq_z", "outer": "prior_v20"},
            {"variant_id": f"M1_abs_r35_eq_v20sc__{feat_set}", "method": "M1", "feat_set": feat_set, "r_cut": 0.35, "dist_mode": "abs", "agg_mode": "eq_z", "outer": "prior_v20"},
            {"variant_id": f"M1_sign_r35_eq_eqz__{feat_set}", "method": "M1", "feat_set": feat_set, "r_cut": 0.35, "dist_mode": "signed", "agg_mode": "eq_z", "outer": "prior_eqz"},
            {"variant_id": f"M1_sign_r35_nnls__{feat_set}", "method": "M1", "feat_set": feat_set, "r_cut": 0.35, "dist_mode": "signed", "agg_mode": "eq_z", "outer": "nnls", "alpha": 30.0},
            {"variant_id": f"M1_abs_r35_nnls__{feat_set}", "method": "M1", "feat_set": feat_set, "r_cut": 0.35, "dist_mode": "abs", "agg_mode": "eq_z", "outer": "nnls", "alpha": 30.0},
            {"variant_id": f"M1_sign_r35_ridge__{feat_set}", "method": "M1", "feat_set": feat_set, "r_cut": 0.35, "dist_mode": "signed", "agg_mode": "eq_z", "outer": "ridge", "alpha": 50.0},
        ])
        # M2: Causal Partial-t Pruning
        if feat_set == "A_Atoms":
            specs.append({"variant_id": f"M2_lam20_t0_raw__{feat_set}", "method": "M2", "feat_set": feat_set, "lam": 20.0, "t_cut": 0.0, "mode": "prior_raw"})
            specs.append({"variant_id": f"M2_lam20_tm05_raw__{feat_set}", "method": "M2", "feat_set": feat_set, "lam": 20.0, "t_cut": -0.5, "mode": "prior_raw"})
        specs.extend([
            {"variant_id": f"M2_lam20_t0_align__{feat_set}", "method": "M2", "feat_set": feat_set, "lam": 20.0, "t_cut": 0.0, "mode": "prior_aligned"},
            {"variant_id": f"M2_lam20_tm05_align__{feat_set}", "method": "M2", "feat_set": feat_set, "lam": 20.0, "t_cut": -0.5, "mode": "prior_aligned"},
            {"variant_id": f"M2_lam1_t0_align__{feat_set}", "method": "M2", "feat_set": feat_set, "lam": 1.0, "t_cut": 0.0, "mode": "prior_aligned"},
            {"variant_id": f"M2_lam100_tp05_align__{feat_set}", "method": "M2", "feat_set": feat_set, "lam": 100.0, "t_cut": 0.5, "mode": "prior_aligned"},
            {"variant_id": f"M2_lam20_t0_ridge50__{feat_set}", "method": "M2", "feat_set": feat_set, "lam": 20.0, "t_cut": 0.0, "mode": "ridge_refit", "alpha": 50.0},
        ])
        # M3: Lowdin Symmetric Orthogonalization
        specs.extend([
            {"variant_id": f"M3_eps05_v20sc__{feat_set}", "method": "M3", "feat_set": feat_set, "eps": 0.05, "outer": "prior_v20"},
            {"variant_id": f"M3_eps15_v20sc__{feat_set}", "method": "M3", "feat_set": feat_set, "eps": 0.15, "outer": "prior_v20"},
            {"variant_id": f"M3_eps30_v20sc__{feat_set}", "method": "M3", "feat_set": feat_set, "eps": 0.30, "outer": "prior_v20"},
            {"variant_id": f"M3_eps15_eqz__{feat_set}", "method": "M3", "feat_set": feat_set, "eps": 0.15, "outer": "prior_eqz"},
            {"variant_id": f"M3_eps15_nnls30__{feat_set}", "method": "M3", "feat_set": feat_set, "eps": 0.15, "outer": "nnls", "alpha": 30.0},
            {"variant_id": f"M3_eps30_nnls30__{feat_set}", "method": "M3", "feat_set": feat_set, "eps": 0.30, "outer": "nnls", "alpha": 30.0},
            {"variant_id": f"M3_eps15_ridge50__{feat_set}", "method": "M3", "feat_set": feat_set, "eps": 0.15, "outer": "ridge", "alpha": 50.0},
            {"variant_id": f"M3_eps30_ridge150__{feat_set}", "method": "M3", "feat_set": feat_set, "eps": 0.30, "outer": "ridge", "alpha": 150.0},
        ])
        # M4: Sparse / Shrinkage Multi-Factor Regression
        specs.extend([
            {"variant_id": f"M4_Ridge_a30__{feat_set}", "method": "M4", "feat_set": feat_set, "reg_type": "ridge", "alpha": 30.0},
            {"variant_id": f"M4_Ridge_a150__{feat_set}", "method": "M4", "feat_set": feat_set, "reg_type": "ridge", "alpha": 150.0},
            {"variant_id": f"M4_Ridge_a500__{feat_set}", "method": "M4", "feat_set": feat_set, "reg_type": "ridge", "alpha": 500.0},
            {"variant_id": f"M4_Lasso_a02__{feat_set}", "method": "M4", "feat_set": feat_set, "reg_type": "lasso", "alpha": 0.02},
            {"variant_id": f"M4_Lasso_a04__{feat_set}", "method": "M4", "feat_set": feat_set, "reg_type": "lasso", "alpha": 0.04},
            {"variant_id": f"M4_Lasso_a06__{feat_set}", "method": "M4", "feat_set": feat_set, "reg_type": "lasso", "alpha": 0.06},
            {"variant_id": f"M4_ENet_a04__{feat_set}", "method": "M4", "feat_set": feat_set, "reg_type": "enet", "alpha": 0.04},
            {"variant_id": f"M4_ENet_a08__{feat_set}", "method": "M4", "feat_set": feat_set, "reg_type": "enet", "alpha": 0.08},
            {"variant_id": f"M4_PLS_k2__{feat_set}", "method": "M4", "feat_set": feat_set, "reg_type": "pls", "n_comp": 2},
            {"variant_id": f"M4_PLS_k3__{feat_set}", "method": "M4", "feat_set": feat_set, "reg_type": "pls", "n_comp": 3},
            {"variant_id": f"M4_PLS_k4__{feat_set}", "method": "M4", "feat_set": feat_set, "reg_type": "pls", "n_comp": 4},
        ])
        # M5: V20 Prior + Gram-Schmidt Orthogonal Residual
        specs.extend([
            {"variant_id": f"M5_Ridge_a100_g20__{feat_set}", "method": "M5", "feat_set": feat_set, "reg_type": "ridge", "alpha": 100.0, "gamma": 0.20, "cap": 15.0},
            {"variant_id": f"M5_Ridge_a250_g35__{feat_set}", "method": "M5", "feat_set": feat_set, "reg_type": "ridge", "alpha": 250.0, "gamma": 0.35, "cap": 15.0},
            {"variant_id": f"M5_Ridge_a500_g50__{feat_set}", "method": "M5", "feat_set": feat_set, "reg_type": "ridge", "alpha": 500.0, "gamma": 0.50, "cap": 15.0},
            {"variant_id": f"M5_ENet_a06_g30__{feat_set}", "method": "M5", "feat_set": feat_set, "reg_type": "enet", "alpha": 0.06, "gamma": 0.30, "cap": 15.0},
            {"variant_id": f"M5_PLS_k2_g30__{feat_set}", "method": "M5", "feat_set": feat_set, "reg_type": "pls", "n_comp": 2, "gamma": 0.30, "cap": 15.0},
        ])
    return specs

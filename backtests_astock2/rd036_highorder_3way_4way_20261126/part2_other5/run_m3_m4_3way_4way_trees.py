#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD036-B Modules 3 & 4 (`run_m3_m4_3way_4way_trees.py`):
  Module 3 (All 5 strategies: `1to2`, `2to3`, `3to4`, `high`, `pry`):
    - 3A: Causal 3-Way Synergy (`A & B & C`) with strict orthogonal residual test over all 3 singles + 3 pairs,
          injected into orig_score (+-8 / +-12 / +-15; Bidir & PosOnly & stacked with ColdSurgery).
    - 3B: Independent 3-Way Minefield Blacklist (top 15%, plus 10%/20% neighborhood).
    - 3C: Regularized Shallow Decision Tree (max_depth=3, adaptive min_samples_leaf, EB leaf shrinkage, Single & Bagged).
  Module 4 (`1to2`, `2to3`, `pry`, `3to4`; `high` skipped due to N=62):
    - 4A: Causal 4-Way Synergy (`A & B & C & D`) with strict orthogonal residual test over all 14 lower-order terms.
    - 4B: 4-Way Minefield Blacklist (top 15%).
    - 4C: Regularized Shallow Decision Tree (max_depth=4, adaptive min_samples_leaf, EB shrinkage, Single & Bagged).

Adaptive min_leaf: 1to2/2to3/pry >= 25 (pry min_days>=5), 3to4 >= 20, high >= 12 (SMALL_SAMPLE_WARNING).
Strictly exit_date < t. Zero yfinance. Peak RSS < 2.0 GB.
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import gc
import itertools
import json
import math
import pickle
import sys
import time
from typing import Optional

import numpy as np
import pandas as pd
from sklearn.tree import DecisionTreeRegressor

DIR = os.path.dirname(os.path.abspath(__file__))
if DIR not in sys.path:
    sys.path.insert(0, DIR)

import _common_rd036 as cm
import _wf_core as wfc
import _w2a4_data_and_features as w2f
import run_m1_m2_cold_and_pairwise as m12


def _select_causal_base_literals(
    Xb_tr: np.ndarray,
    u_tgt: np.ndarray,
    g_inv: np.ndarray,
    G: int,
    base_names: list[str],
    top_k: int,
    min_leaf: int,
    forced_cols: Optional[list[str]] = None,
) -> tuple[list[dict], np.ndarray]:
    """
    Strictly inside exit_date < t: pick top_k orthogonal base features, binarize cleanly
    into Hi (x > thr) and Lo (~Hi) literals where both sides have >= min_leaf support.
    Returns (meta_list, literal_bool_matrix (M, 2*K)).
    """
    M, F = Xb_tr.shape
    fin = np.isfinite(Xb_tr)
    cnt = fin.sum(axis=0)
    meds = np.nanmedian(Xb_tr, axis=0)
    meds = np.where(np.isfinite(meds), meds, 0.0)
    X_imp = np.where(fin, Xb_tr, meds[None, :])
    stds = np.std(X_imp, axis=0)
    ok_idx = np.where((cnt >= max(12, int(0.45 * M))) & (stds > 1e-9))[0]
    if len(ok_idx) < 3:
        return [], np.empty((M, 0), dtype=bool)

    t_vals = w2f._batch_cluster_t_stats(u_tgt, X_imp[:, ok_idx], g_inv, G)
    order = np.argsort(-np.abs(t_vals), kind="mergesort")

    chosen = []
    # Optional forced regime anchor (e.g. mkt10_zt_est_t1)
    if forced_cols:
        name_to_j = {nm: j for j, nm in enumerate(base_names)}
        ok_set = set(ok_idx.tolist())
        for fc in forced_cols:
            jf = name_to_j.get(fc)
            if jf is not None and jf in ok_set:
                xj = X_imp[:, jf]
                uniq = np.unique(xj)
                thr = 0.5 * (float(uniq.min()) + float(uniq.max())) if len(uniq) <= 2 else float(meds[jf])
                hi = xj > thr
                if int(hi.sum()) >= min_leaf and int((~hi).sum()) >= min_leaf:
                    chosen.append((jf, thr, float(t_vals[np.where(ok_idx == jf)[0][0]]), hi))

    for oi in order:
        if len(chosen) >= top_k:
            break
        j = int(ok_idx[oi])
        if any(c[0] == j for c in chosen):
            continue
        xj = X_imp[:, j]
        if any(abs(float(np.corrcoef(xj, X_imp[:, cj])[0, 1])) > 0.72 for cj, *_ in chosen):
            continue
        uniq = np.unique(xj)
        if len(uniq) <= 2:
            thr = 0.5 * (float(uniq.min()) + float(uniq.max()))
            hi = xj > thr
        else:
            thr = float(meds[j])
            hi = xj > thr
            if int(hi.sum()) < min_leaf or int((~hi).sum()) < min_leaf:
                thr = float(np.mean(xj))
                hi = xj > thr
        if int(hi.sum()) >= min_leaf and int((~hi).sum()) >= min_leaf:
            chosen.append((j, thr, float(t_vals[oi]), hi))

    if len(chosen) < 3:
        return [], np.empty((M, 0), dtype=bool)

    meta = []
    cols_b = []
    for k_i, (j, thr, tv, hi) in enumerate(chosen):
        meta.append({"base_idx": k_i, "col_idx": j, "name": base_names[j], "thr": thr, "med": float(meds[j]), "t_single": tv})
        cols_b.append(hi)
        cols_b.append(~hi)
    return meta, np.column_stack(cols_b)


def _eval_literals_on_rows(Xb_rows: np.ndarray, base_meta: list[dict]) -> np.ndarray:
    """Apply frozen causal base literal thresholds on new rows -> boolean (n, 2*K)."""
    n = Xb_rows.shape[0]
    cols = []
    for m in base_meta:
        xv = np.where(np.isfinite(Xb_rows[:, m["col_idx"]]), Xb_rows[:, m["col_idx"]], m["med"])
        hi = xv > m["thr"]
        cols.append(hi)
        cols.append(~hi)
    return np.column_stack(cols) if cols else np.empty((n, 0), dtype=bool)


def _ridge_proj_resid(target_vec: np.ndarray, Z_design: np.ndarray) -> np.ndarray:
    """Orthogonal residual of `target_vec` after ridge-regularized OLS projection onto `Z_design`."""
    ZtZ = Z_design.T @ Z_design
    ZtZ.flat[:: ZtZ.shape[0] + 1] += 1e-6
    beta = np.linalg.solve(ZtZ, Z_design.T @ target_vec)
    return target_vec - Z_design @ beta


def _chunked_cluster_t(u: np.ndarray, Z: np.ndarray, g_inv: np.ndarray, G: int, chunk: int = 256) -> np.ndarray:
    """Memory-lean chunked exact Liang-Zeger cluster-robust t-stats (< 5 MB peak temp RAM)."""
    F = Z.shape[1]
    if F <= chunk:
        return w2f._batch_cluster_t_stats(u, Z, g_inv, G)
    out = np.empty(F, dtype=np.float64)
    for s in range(0, F, chunk):
        e = min(F, s + chunk)
        out[s:e] = w2f._batch_cluster_t_stats(u, Z[:, s:e], g_inv, G)
    return out


def _filter_days_from_bool_cands(cand_bools: list[np.ndarray], g_inv: np.ndarray, G: int, min_days: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Count distinct active days per boolean rule column using tiny chunked uint8/float32 matmuls."""
    M = len(g_inv)
    n_c = len(cand_bools)
    G_ind = np.zeros((G, M), dtype=np.float32)
    G_ind[g_inv, np.arange(M)] = 1.0
    day_cnts = np.empty(n_c, dtype=np.int32)
    for s in range(0, n_c, 256):
        e = min(n_c, s + 256)
        blk = np.column_stack(cand_bools[s:e]).astype(np.float32)
        day_cnts[s:e] = np.sum((G_ind @ blk) > 0.5, axis=0)
    keep = day_cnts >= min_days
    if not np.any(keep):
        return np.empty((M, 0), dtype=np.float64), np.empty(0, dtype=np.int32), np.empty(0, dtype=np.int32)
    kept_idx = np.where(keep)[0]
    T_mat = np.column_stack([cand_bools[i] for i in kept_idx]).astype(np.float64)
    return T_mat, kept_idx, day_cnts[kept_idx]


def fit_3way_synergy_card(
    Xb_tr: np.ndarray,
    y_ret: np.ndarray,
    y_win: np.ndarray,
    day_ids: np.ndarray,
    base_names: list[str],
    min_leaf: int,
    min_days: int,
    max_deltas: tuple[int, ...] = (8, 12, 15),
    orig_tr: Optional[np.ndarray] = None,
    mode: str = "delta_bidir",  # 'delta_bidir', 'delta_pos', 'mine_0_100'
    t_min_3way: float = 2.0,
    t_syn_min: float = 1.5,
    top_k_rules: int = 6,
    shrink_tau: float = 15.0,
    decluster_days: bool = False,
) -> dict:
    """
    Strictly inside exit_date < t:
      1. Select top K=12 orthogonal base features (incl. mkt10_zt_est_t1) -> 24 literals.
      2. Search all C(12,3)*8 = 1,760 3-way conjunctions A & B & C passing min_leaf and min_days.
      3. Vectorized cluster-t test + strict orthogonal residual test projecting out {1, A, B, C, A&B, A&C, B&C}.
      4. Enforce strict lift over every 2-way subset & greedy orthogonal rule selection.
    """
    M = len(y_ret)
    is_mine = (mode == "mine_0_100")
    if M < max(min_leaf * 2, 24) or len(np.unique(day_ids)) < max(5, min_days):
        return {"base_meta": [], "cards": {md: [] for md in max_deltas}, "rules": [], "q_cuts": {}}

    _, g_inv = np.unique(day_ids, return_inverse=True)
    G = int(g_inv.max()) + 1

    if is_mine:
        u_tgt = y_win.astype(np.float64)
        if float(u_tgt.sum()) < 3.0:
            return {"base_meta": [], "cards": {}, "rules": [], "q_cuts": {}}
    else:
        if decluster_days:
            dc = np.bincount(g_inv)
            wt = 1.0 / dc[g_inv]
            wt_n = wt / np.sum(wt)
            mu0 = float(np.sum(wt_n * y_ret))
            wr0 = float(np.sum(wt_n * y_win))
            sdr = max(1e-5, float(np.sqrt(np.sum(wt_n * (y_ret - mu0) ** 2))))
        else:
            mu0, wr0 = float(np.mean(y_ret)), float(np.mean(y_win))
            sdr = max(1e-5, float(np.std(y_ret, ddof=1)))
        u_tgt = 0.6 * (y_ret - mu0) / sdr + 0.4 * (y_win - wr0) / 0.25

    base_meta, L_mat = _select_causal_base_literals(
        Xb_tr, u_tgt, g_inv, G, base_names, top_k=12, min_leaf=min_leaf, forced_cols=["mkt10_zt_est_t1"],
    )
    K = len(base_meta)
    if K < 3:
        return {"base_meta": [], "cards": {md: [] for md in max_deltas}, "rules": [], "q_cuts": {}}

    # Generate all 3-way rules (a < b < c) x (sa, sb, sc in {0, 1}) where L_col = 2*idx + s
    cand_bools = []
    cand_specs = []
    pair_cache = {}
    for a in range(K):
        for sa in (0, 1):
            va = L_mat[:, 2 * a + sa]
            for b in range(a + 1, K):
                for sb in (0, 1):
                    vab = va & L_mat[:, 2 * b + sb]
                    if int(vab.sum()) >= min_leaf:
                        pair_cache[(a, sa, b, sb)] = vab

    for (a, sa, b, sb), vab in pair_cache.items():
        for c in range(b + 1, K):
            for sc in (0, 1):
                vabc = vab & L_mat[:, 2 * c + sc]
                cnt = int(vabc.sum())
                if cnt < min_leaf or (M - cnt) < min_leaf:
                    continue
                cand_bools.append(vabc)
                cand_specs.append(((a, sa), (b, sb), (c, sc), cnt))

    if not cand_bools:
        return {"base_meta": base_meta, "cards": {md: [] for md in max_deltas}, "cards_pos": {md: [] for md in max_deltas}, "rules": [], "q_cuts": {}}

    T_mat, kept_idx, kept_dc = _filter_days_from_bool_cands(cand_bools, g_inv, G, min_days)
    del cand_bools, pair_cache
    if T_mat.shape[1] == 0:
        return {"base_meta": base_meta, "cards": {md: [] for md in max_deltas}, "cards_pos": {md: [] for md in max_deltas}, "rules": [], "q_cuts": {}}
    cand_specs = [(*cand_specs[idx_k], int(dc)) for idx_k, dc in zip(kept_idx, kept_dc)]
    t_triples = _chunked_cluster_t(u_tgt, T_mat, g_inv, G)

    if mode == "delta_pos":
        hit_idx = np.where(t_triples >= t_min_3way)[0]
    elif is_mine:
        hit_idx = np.where(t_triples >= max(1.6, t_min_3way - 0.3))[0]
    else:
        hit_idx = np.where(np.abs(t_triples) >= t_min_3way)[0]

    if len(hit_idx) == 0:
        return {"base_meta": base_meta, "cards": {md: [] for md in max_deltas}, "rules": [], "q_cuts": {}}

    # Sort hits by |t| descending and check top 150 for orthogonal synergy (fast & clean)
    hit_order = hit_idx[np.argsort(-np.abs(t_triples[hit_idx]), kind="mergesort")][:150]
    ones = np.ones(M, dtype=np.float64)
    mu_u = float(np.mean(u_tgt))

    surviving = []
    for hi in hit_order:
        (a, sa), (b, sb), (c, sc), cnt, n_days_l = cand_specs[hi]
        t_raw = float(t_triples[hi])
        t_vec = T_mat[:, hi]
        va = L_mat[:, 2 * a + sa].astype(np.float64)
        vb = L_mat[:, 2 * b + sb].astype(np.float64)
        vc = L_mat[:, 2 * c + sc].astype(np.float64)
        vab = va * vb
        vac = va * vc
        vbc = vb * vc

        # True lift check over all 3 pairwise subsets
        m_abc = float(np.mean(u_tgt[t_vec > 0.5]))
        sub_means = [float(np.mean(u_tgt[p > 0.5])) for p in (vab, vac, vbc)]
        if t_raw > 0:
            if m_abc <= max(sub_means) + (0.01 if is_mine else 0.03):
                continue
        else:
            if m_abc >= min(sub_means) - 0.03:
                continue

        # Orthogonal projection onto {1, A, B, C, A&B, A&C, B&C}
        Z_sub = np.column_stack([ones, va, vb, vc, vab, vac, vbc])
        resid = _ridge_proj_resid(t_vec, Z_sub)
        if float(np.std(resid)) < 1e-4:
            continue
        t_syn = float(w2f._batch_cluster_t_stats(u_tgt, resid[:, None], g_inv, G)[0])
        if (t_raw > 0 and t_syn < t_syn_min) or (t_raw < 0 and t_syn > -t_syn_min):
            continue

        # Check correlation with orig_score in Mode B
        if (not is_mine) and orig_tr is not None:
            m_ov = np.isfinite(orig_tr)
            if m_ov.sum() >= 15 and np.std(orig_tr[m_ov]) > 1e-12:
                if abs(float(np.corrcoef(t_vec[m_ov], orig_tr[m_ov])[0, 1])) > 0.65:
                    continue

        # Empirical Bayes shrunk effect size
        diff_u = m_abc - mu_u
        shr_eff = diff_u * (cnt / (cnt + shrink_tau))
        lit_lbl = " & ".join([
            f"{base_meta[idx]['name']}{'>' if s == 0 else '<='}{base_meta[idx]['thr']:.3g}"
            for idx, s in ((a, sa), (b, sb), (c, sc))
        ])
        surviving.append({
            "lits": ((a, sa), (b, sb), (c, sc)),
            "label": lit_lbl,
            "cnt": cnt,
            "days": n_days_l,
            "t_raw": round(t_raw, 3),
            "t_syn": round(t_syn, 3),
            "shr_eff": float(shr_eff),
            "vec": t_vec,
        })

    if not surviving:
        return {"base_meta": base_meta, "cards": {md: [] for md in max_deltas}, "cards_pos": {md: [] for md in max_deltas}, "rules": [], "q_cuts": {}}

    # Greedy orthogonal pruning across surviving 3-way rules (|r| <= 0.55)
    surviving.sort(key=lambda r: (-(abs(r["t_raw"]) + 0.5 * abs(r["t_syn"])), r["label"]))

    def _greedy_select(pool_list):
        sel = []
        for r in pool_list:
            if any(abs(float(np.corrcoef(r["vec"], s["vec"])[0, 1])) > 0.55 for s in sel):
                continue
            sel.append(r)
            if len(sel) >= top_k_rules:
                break
        return sel

    selected = _greedy_select(surviving)
    if is_mine:
        w_t = np.array([min(4.0, max(0.5, abs(s["t_raw"]))) for s in selected], dtype=float)
        bgts = wfc._largest_remainder_int(w_t, 100)
        rules_0_100 = []
        tr_sc = np.zeros(M, dtype=float)
        for s, bgt in zip(selected, bgts):
            rules_0_100.append({**{k: v for k, v in s.items() if k != "vec"}, "pts": int(bgt)})
            tr_sc += s["vec"] * float(bgt)
        q_cuts = {f"q{q}": float(np.percentile(tr_sc, q)) for q in (80, 85, 90)}
        return {"base_meta": base_meta, "cards": {100: rules_0_100}, "cards_pos": {}, "rules": rules_0_100, "q_cuts": q_cuts}

    def _emit_cards(sel_list):
        if not sel_list:
            return {md: [] for md in max_deltas}
        w_t = np.array([min(4.0, max(0.5, abs(s["t_raw"]))) for s in sel_list], dtype=float)
        out_c = {}
        for md in max_deltas:
            bgts = wfc._largest_remainder_int(w_t, int(md))
            out_c[md] = [{**{k: v for k, v in s.items() if k != "vec"}, "pts": int((1 if s["shr_eff"] >= 0 else -1) * bgt)} for s, bgt in zip(sel_list, bgts)]
        return out_c

    cards = _emit_cards(selected)
    selected_pos = _greedy_select([r for r in surviving if r["shr_eff"] > 0])
    cards_pos = _emit_cards(selected_pos)
    return {"base_meta": base_meta, "cards": cards, "cards_pos": cards_pos, "rules": cards[max_deltas[len(max_deltas) // 2]], "q_cuts": {}}


def score_conj_rules(Xb_rows: np.ndarray, model: dict, key: int, card_field: str = "cards") -> np.ndarray:
    """Evaluate frozen 3-way or 4-way conjunctive rules on new rows."""
    n = Xb_rows.shape[0]
    rules = model.get(card_field, {}).get(key, [])
    if not rules or not model.get("base_meta"):
        return np.zeros(n, dtype=np.float64)
    L_rows = _eval_literals_on_rows(Xb_rows, model["base_meta"])
    tot = np.zeros(n, dtype=np.float64)
    for r in rules:
        m = np.ones(n, dtype=bool)
        for idx, s in r["lits"]:
            m &= L_rows[:, 2 * idx + s]
        tot[m] += float(r["pts"])
    return tot


def fit_4way_synergy_card(
    Xb_tr: np.ndarray,
    y_ret: np.ndarray,
    y_win: np.ndarray,
    day_ids: np.ndarray,
    base_names: list[str],
    min_leaf: int,
    min_days: int,
    max_deltas: tuple[int, ...] = (8, 12, 15),
    orig_tr: Optional[np.ndarray] = None,
    mode: str = "delta_bidir",
    t_min_4way: float = 2.2,
    t_syn_min: float = 1.5,
    top_k_rules: int = 5,
    shrink_tau: float = 15.0,
) -> dict:
    """
    Strictly inside exit_date < t:
      4-way extension on top K=10 orthogonal base factors -> C(10,4)*16 = 3,360 4-way rules,
      requiring n_leaf >= min_leaf, n_days >= min_days, and orthogonal residual synergy
      after projecting out ALL 14 lower-order terms (4 singles + 6 pairs + 4 triples).
    """
    M = len(y_ret)
    is_mine = (mode == "mine_0_100")
    if M < max(min_leaf * 2, 35) or len(np.unique(day_ids)) < max(5, min_days):
        return {"base_meta": [], "cards": {md: [] for md in max_deltas}, "rules": [], "q_cuts": {}}

    _, g_inv = np.unique(day_ids, return_inverse=True)
    G = int(g_inv.max()) + 1
    if is_mine:
        u_tgt = y_win.astype(np.float64)
        if float(u_tgt.sum()) < 3.0:
            return {"base_meta": [], "cards": {}, "rules": [], "q_cuts": {}}
    else:
        mu0, wr0 = float(np.mean(y_ret)), float(np.mean(y_win))
        sdr = max(1e-5, float(np.std(y_ret, ddof=1)))
        u_tgt = 0.6 * (y_ret - mu0) / sdr + 0.4 * (y_win - wr0) / 0.25

    base_meta, L_mat = _select_causal_base_literals(
        Xb_tr, u_tgt, g_inv, G, base_names, top_k=10, min_leaf=min_leaf, forced_cols=["mkt10_zt_est_t1"],
    )
    K = len(base_meta)
    if K < 4:
        return {"base_meta": [], "cards": {md: [] for md in max_deltas}, "rules": [], "q_cuts": {}}

    # Prebuild valid 2-way & 3-way sub-masks outside inner loops (20x faster + bool masks)
    cand_bools, cand_specs = [], []
    for a in range(K):
        for sa in (0, 1):
            va = L_mat[:, 2 * a + sa]
            for b in range(a + 1, K):
                for sb in (0, 1):
                    vab = va & L_mat[:, 2 * b + sb]
                    if int(vab.sum()) < min_leaf:
                        continue
                    for c in range(b + 1, K):
                        for sc in (0, 1):
                            v3 = vab & L_mat[:, 2 * c + sc]
                            if int(v3.sum()) < min_leaf:
                                continue
                            for d in range(c + 1, K):
                                for sd_ in (0, 1):
                                    v4 = v3 & L_mat[:, 2 * d + sd_]
                                    cnt = int(v4.sum())
                                    if cnt < min_leaf or (M - cnt) < min_leaf:
                                        continue
                                    cand_bools.append(v4)
                                    cand_specs.append(((a, sa), (b, sb), (c, sc), (d, sd_), cnt))

    if not cand_bools:
        return {"base_meta": base_meta, "cards": {md: [] for md in max_deltas}, "cards_pos": {md: [] for md in max_deltas}, "rules": [], "q_cuts": {}}

    Q_mat, kept_idx, kept_dc = _filter_days_from_bool_cands(cand_bools, g_inv, G, min_days)
    del cand_bools
    if Q_mat.shape[1] == 0:
        return {"base_meta": base_meta, "cards": {md: [] for md in max_deltas}, "cards_pos": {md: [] for md in max_deltas}, "rules": [], "q_cuts": {}}
    cand_specs = [(*cand_specs[idx_k], int(dc)) for idx_k, dc in zip(kept_idx, kept_dc)]
    t_quads = _chunked_cluster_t(u_tgt, Q_mat, g_inv, G)
    hit_idx = np.where((t_quads >= max(1.8, t_min_4way - 0.3)) if is_mine else (np.abs(t_quads) >= t_min_4way))[0]
    if len(hit_idx) == 0:
        return {"base_meta": base_meta, "cards": {md: [] for md in max_deltas}, "rules": [], "q_cuts": {}}

    hit_order = hit_idx[np.argsort(-np.abs(t_quads[hit_idx]), kind="mergesort")][:120]
    ones = np.ones(M, dtype=np.float64)
    mu_u = float(np.mean(u_tgt))

    surviving = []
    for hi in hit_order:
        (a, sa), (b, sb), (c, sc), (d, sd_), cnt, n_dl = cand_specs[hi]
        t_raw = float(t_quads[hi])
        q_vec = Q_mat[:, hi]
        l_vecs = [L_mat[:, 2 * idx + s].astype(np.float64) for idx, s in ((a, sa), (b, sb), (c, sc), (d, sd_))]
        pairs = [l_vecs[i] * l_vecs[j] for i, j in itertools.combinations(range(4), 2)]
        triples = [l_vecs[i] * l_vecs[j] * l_vecs[k] for i, j, k in itertools.combinations(range(4), 3)]

        # Strict lift over ALL 4 sub-triples
        m_q = float(np.mean(u_tgt[q_vec > 0.5]))
        tr_means = [float(np.mean(u_tgt[tr > 0.5])) for tr in triples]
        if t_raw > 0:
            if m_q <= max(tr_means) + (0.01 if is_mine else 0.03):
                continue
        else:
            if m_q >= min(tr_means) - 0.03:
                continue

        # Orthogonal projection onto all 14 lower-order terms + intercept
        Z_sub = np.column_stack([ones] + l_vecs + pairs + triples)
        resid = _ridge_proj_resid(q_vec, Z_sub)
        if float(np.std(resid)) < 1e-4:
            continue
        t_syn = float(w2f._batch_cluster_t_stats(u_tgt, resid[:, None], g_inv, G)[0])
        if (t_raw > 0 and t_syn < t_syn_min) or (t_raw < 0 and t_syn > -t_syn_min):
            continue

        if (not is_mine) and orig_tr is not None:
            m_ov = np.isfinite(orig_tr)
            if m_ov.sum() >= 15 and np.std(orig_tr[m_ov]) > 1e-12:
                if abs(float(np.corrcoef(q_vec[m_ov], orig_tr[m_ov])[0, 1])) > 0.65:
                    continue

        shr_eff = (m_q - mu_u) * (cnt / (cnt + shrink_tau))
        lit_lbl = " & ".join([
            f"{base_meta[idx]['name']}{'>' if s == 0 else '<='}{base_meta[idx]['thr']:.3g}"
            for idx, s in ((a, sa), (b, sb), (c, sc), (d, sd_))
        ])
        surviving.append({
            "lits": ((a, sa), (b, sb), (c, sc), (d, sd_)),
            "label": lit_lbl, "cnt": cnt, "days": n_dl,
            "t_raw": round(t_raw, 3), "t_syn": round(t_syn, 3), "shr_eff": float(shr_eff), "vec": q_vec,
        })

    if not surviving:
        return {"base_meta": base_meta, "cards": {md: [] for md in max_deltas}, "cards_pos": {md: [] for md in max_deltas}, "rules": [], "q_cuts": {}}

    surviving.sort(key=lambda r: (-(abs(r["t_raw"]) + 0.5 * abs(r["t_syn"])), r["label"]))

    def _greedy_sel4(pool_list):
        sel = []
        for r in pool_list:
            if any(abs(float(np.corrcoef(r["vec"], s["vec"])[0, 1])) > 0.55 for s in sel):
                continue
            sel.append(r)
            if len(sel) >= top_k_rules:
                break
        return sel

    selected = _greedy_sel4(surviving)
    if is_mine:
        w_t = np.array([min(4.0, max(0.5, abs(s["t_raw"]))) for s in selected], dtype=float)
        bgts = wfc._largest_remainder_int(w_t, 100)
        rules_0_100 = [{**{k: v for k, v in s.items() if k != "vec"}, "pts": int(bgt)} for s, bgt in zip(selected, bgts)]
        tr_sc = np.zeros(M, dtype=float)
        for r, s in zip(rules_0_100, selected):
            tr_sc += s["vec"] * float(r["pts"])
        return {"base_meta": base_meta, "cards": {100: rules_0_100}, "cards_pos": {}, "rules": rules_0_100, "q_cuts": {f"q{q}": float(np.percentile(tr_sc, q)) for q in (80, 85, 90)}}

    def _emit_4(sel_list):
        if not sel_list:
            return {md: [] for md in max_deltas}
        w_t = np.array([min(4.0, max(0.5, abs(s["t_raw"]))) for s in sel_list], dtype=float)
        out_c = {}
        for md in max_deltas:
            bgts = wfc._largest_remainder_int(w_t, int(md))
            out_c[md] = [{**{k: v for k, v in s.items() if k != "vec"}, "pts": int((1 if s["shr_eff"] >= 0 else -1) * bgt)} for s, bgt in zip(sel_list, bgts)]
        return out_c

    cards = _emit_4(selected)
    cards_pos = _emit_4(_greedy_sel4([r for r in surviving if r["shr_eff"] > 0]))
    return {"base_meta": base_meta, "cards": cards, "cards_pos": cards_pos, "rules": cards[max_deltas[len(max_deltas) // 2]], "q_cuts": {}}


def fit_shallow_tree_model(
    Xb_tr: np.ndarray,
    y_ret: np.ndarray,
    y_win: np.ndarray,
    day_ids: np.ndarray,
    base_names: list[str],
    max_depth: int,
    min_leaf: int,
    n_bag: int = 1,
    is_mine: bool = False,
    shrink_tau: float = 15.0,
) -> dict:
    """
    Fit regularized shallow DecisionTreeRegressor (depth=3 or 4) strictly inside exit_date < t
    on top K=15 orthogonal base factors with Empirical Bayes leaf shrinkage.
    """
    M = len(y_ret)
    if M < max(min_leaf * 2, 24) or len(np.unique(day_ids)) < 5:
        return {"trees": [], "col_idx": [], "meds": [], "scale": 1.0, "q85": 1.0}
    _, g_inv = np.unique(day_ids, return_inverse=True)
    G = int(g_inv.max()) + 1
    if is_mine:
        u_tgt = y_win.astype(np.float64)
        if float(u_tgt.sum()) < 3.0:
            return {"trees": [], "col_idx": [], "meds": [], "scale": 1.0, "q85": 1.0}
    else:
        mu0, wr0 = float(np.mean(y_ret)), float(np.mean(y_win))
        sdr = max(1e-5, float(np.std(y_ret, ddof=1)))
        u_tgt = 0.6 * (y_ret - mu0) / sdr + 0.4 * (y_win - wr0) / 0.25

    # Pick top 15 orthogonal base features
    fin = np.isfinite(Xb_tr)
    meds = np.nanmedian(Xb_tr, axis=0)
    meds = np.where(np.isfinite(meds), meds, 0.0)
    X_imp = np.where(fin, Xb_tr, meds[None, :])
    stds = np.std(X_imp, axis=0)
    ok_idx = np.where((fin.sum(axis=0) >= max(12, int(0.45 * M))) & (stds > 1e-9))[0]
    if len(ok_idx) < 3:
        return {"trees": [], "col_idx": [], "meds": [], "scale": 1.0, "q85": 1.0}
    t_vals = w2f._batch_cluster_t_stats(u_tgt, X_imp[:, ok_idx], g_inv, G)
    order = np.argsort(-np.abs(t_vals), kind="mergesort")
    sel_cols = []
    for oi in order:
        j = int(ok_idx[oi])
        xj = X_imp[:, j]
        if any(abs(float(np.corrcoef(xj, X_imp[:, cj])[0, 1])) > 0.72 for cj in sel_cols):
            continue
        sel_cols.append(j)
        if len(sel_cols) >= 15:
            break

    X_sub = X_imp[:, sel_cols]
    mu_u = float(np.mean(u_tgt))
    trees = []
    rng = np.random.default_rng(20261126 + M)
    for bi in range(n_bag):
        if n_bag == 1:
            idx_s = np.arange(M)
        else:
            idx_s = rng.choice(M, size=int(0.85 * M), replace=False)
        dt = DecisionTreeRegressor(
            max_depth=max_depth,
            min_samples_leaf=min_leaf,
            min_impurity_decrease=0.002 if is_mine else 0.005,
            ccp_alpha=0.001 if is_mine else 0.002,
            random_state=42 + bi,
        )
        dt.fit(X_sub[idx_s], u_tgt[idx_s])
        # Compute EB-shrunk leaf values
        leaf_ids = dt.apply(X_sub)
        shr_map = {}
        for lid in np.unique(leaf_ids):
            lm = (leaf_ids == lid)
            cnt_l = int(lm.sum())
            val_l = float(np.mean(u_tgt[lm]))
            if is_mine:
                shr_map[int(lid)] = (float(np.sum(u_tgt[lm])) + shrink_tau * mu_u) / (cnt_l + shrink_tau)
            else:
                shr_map[int(lid)] = (val_l - mu_u) * (cnt_l / (cnt_l + shrink_tau))
        trees.append((dt, shr_map))

    # Predict training range for clean normalization
    tr_preds = predict_shallow_tree(Xb_tr, {"trees": trees, "col_idx": sel_cols, "meds": meds[sel_cols]})
    max_abs = max(1e-4, float(np.percentile(np.abs(tr_preds), 95.0))) if not is_mine else 1.0
    q85 = float(np.percentile(tr_preds, 85.0)) if is_mine else 1.0
    return {"trees": trees, "col_idx": sel_cols, "meds": meds[sel_cols], "scale": max_abs, "q85": q85}


def predict_shallow_tree(Xb_rows: np.ndarray, model: dict) -> np.ndarray:
    n = Xb_rows.shape[0]
    if not model.get("trees"):
        return np.zeros(n, dtype=np.float64)
    cols = model["col_idx"]
    meds = model["meds"]
    X_sub = Xb_rows[:, cols].copy()
    for j in range(len(cols)):
        bad = ~np.isfinite(X_sub[:, j])
        if bad.any():
            X_sub[bad, j] = meds[j]
    acc = np.zeros(n, dtype=np.float64)
    for dt, shr_map in model["trees"]:
        lids = dt.apply(X_sub)
        acc += np.array([shr_map.get(int(l), 0.0) for l in lids], dtype=np.float64)
    return acc / len(model["trees"])


def run_wf_3way_4way_and_trees(
    df: pd.DataFrame,
    base_cols: list[str],
    min_leaf: int,
    min_days: int,
    order: int = 3,
    decluster_days: bool = False,
    run_trees: bool = True,
    recalc_freq: str = "daily",
    max_deltas: tuple[int, ...] = (8, 12, 15),
) -> dict:
    """
    Single strictly-causal (exit_date < t) pass per strategy & order (3 or 4) emitting:
      - bidir delta scores (+-8, +-12, +-15)
      - pos-only delta scores (+-8, +-12, +-15)
      - minefield blacklist masks (10%, 15%, 20%)
      - shallow decision tree single & bagged(10) delta scores (+-8, +-12, +-15) + tree mine BL15
      - diagnostic counts of average surviving rules per day & latest rules!
    """
    n = len(df)
    buy_dts = df["buy_date"].to_numpy(str)
    exit_dts = df["exit_date"].to_numpy(str)
    codes = df["code"].to_numpy(str)
    y_ret = df["net_ret_030"].to_numpy(float)
    y_win = (y_ret > 0.0).astype(float)
    y_mine = (y_ret <= -0.07).astype(float)
    can_buy = df["can_buy_hygiene"].to_numpy(bool)
    orig = df["orig_score"].to_numpy(float)
    Xb_all = df[base_cols].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=np.float64)

    uniq_dts = sorted(set(buy_dts.tolist()))
    dt_id = {d: i for i, d in enumerate(uniq_dts)}
    dids = np.array([dt_id[d] for d in buy_dts], dtype=np.int32)
    b_idx = np.where(can_buy)[0]
    ex_ord = np.asarray(sorted(b_idx.tolist(), key=lambda i: (exit_dts[i], buy_dts[i], codes[i])), dtype=np.int64)
    ex_dts = exit_dts[ex_ord]
    Xb_ex, r_ex, w_ex, ym_ex, d_ex, o_ex = Xb_all[ex_ord], y_ret[ex_ord], y_win[ex_ord], y_mine[ex_ord], dids[ex_ord], orig[ex_ord]

    by_dt_all = {}
    for i in range(n):
        by_dt_all.setdefault(buy_dts[i], []).append(i)

    deltas_bidir = {md: np.zeros(n, dtype=np.float64) for md in max_deltas}
    deltas_pos = {md: np.zeros(n, dtype=np.float64) for md in max_deltas}
    mine_bl = {q: np.zeros(n, dtype=bool) for q in (10, 15, 20)}
    tree_single = {md: np.zeros(n, dtype=np.float64) for md in max_deltas}
    tree_bag = {md: np.zeros(n, dtype=np.float64) for md in max_deltas}
    tree_mine_bl15 = np.zeros(n, dtype=bool)

    ptr, last_ptr, last_mo = 0, -1, ""
    m_bi = m_mn = t_s = t_b = t_m = None
    rule_cnts = []

    for t in sorted(by_dt_all.keys()):
        while ptr < len(ex_ord) and ex_dts[ptr] < t:
            ptr += 1
        if t < cm.WF_START or ptr < max(12, min_leaf):
            continue
        need = (m_bi is None) or (recalc_freq == "daily" and ptr > last_ptr) or (recalc_freq == "monthly" and t[:7] != last_mo)
        if need:
            if order == 3:
                m_bi = fit_3way_synergy_card(Xb_ex[:ptr], r_ex[:ptr], w_ex[:ptr], d_ex[:ptr], base_cols, min_leaf, min_days, max_deltas, o_ex[:ptr], "delta_bidir", decluster_days=decluster_days)
                m_mn = fit_3way_synergy_card(Xb_ex[:ptr], ym_ex[:ptr], ym_ex[:ptr], d_ex[:ptr], base_cols, min_leaf, min_days, (100,), None, "mine_0_100")
            else:
                m_bi = fit_4way_synergy_card(Xb_ex[:ptr], r_ex[:ptr], w_ex[:ptr], d_ex[:ptr], base_cols, min_leaf, min_days, max_deltas, o_ex[:ptr], "delta_bidir")
                m_mn = fit_4way_synergy_card(Xb_ex[:ptr], ym_ex[:ptr], ym_ex[:ptr], d_ex[:ptr], base_cols, min_leaf, min_days, (100,), None, "mine_0_100")
            if run_trees:
                t_s = fit_shallow_tree_model(Xb_ex[:ptr], r_ex[:ptr], w_ex[:ptr], d_ex[:ptr], base_cols, max_depth=order, min_leaf=min_leaf, n_bag=1, is_mine=False)
                t_b = fit_shallow_tree_model(Xb_ex[:ptr], r_ex[:ptr], w_ex[:ptr], d_ex[:ptr], base_cols, max_depth=order, min_leaf=min_leaf, n_bag=7, is_mine=False)
                t_m = fit_shallow_tree_model(Xb_ex[:ptr], ym_ex[:ptr], ym_ex[:ptr], d_ex[:ptr], base_cols, max_depth=order, min_leaf=min_leaf, n_bag=1, is_mine=True)
            rule_cnts.append(len(m_bi["rules"]))
            last_ptr, last_mo = ptr, t[:7]
            if len(rule_cnts) % 25 == 0:
                gc.collect()

        rows_t = np.asarray(by_dt_all[t], dtype=np.int64)
        X_r = Xb_all[rows_t]
        for md in max_deltas:
            deltas_bidir[md][rows_t] = score_conj_rules(X_r, m_bi, md, "cards")
            deltas_pos[md][rows_t] = score_conj_rules(X_r, m_bi, md, "cards_pos")
        if m_mn and m_mn["rules"]:
            sc_mn = score_conj_rules(X_r, m_mn, 100)
            for q in (10, 15, 20):
                qcut = m_mn["q_cuts"].get(f"q{100 - q}", 999.0)
                mine_bl[q][rows_t] = sc_mn >= max(1.0, qcut)
        if run_trees and t_s and t_s.get("trees"):
            ps_raw = predict_shallow_tree(X_r, t_s)
            for md in max_deltas:
                tree_single[md][rows_t] = np.clip(np.round(ps_raw / t_s["scale"] * md), -md, md)
        if run_trees and t_b and t_b.get("trees"):
            pb_raw = predict_shallow_tree(X_r, t_b)
            for md in max_deltas:
                tree_bag[md][rows_t] = np.clip(np.round(pb_raw / t_b["scale"] * md), -md, md)
        if run_trees and t_m and t_m.get("trees"):
            pm_raw = predict_shallow_tree(X_r, t_m)
            tree_mine_bl15[rows_t] = (pm_raw >= t_m["q85"]) & (pm_raw > float(np.mean(ym_ex[:ptr])))

    return {
        "deltas_bidir": deltas_bidir,
        "deltas_pos": deltas_pos,
        "mine_bl": mine_bl,
        "tree_single": tree_single,
        "tree_bag": tree_bag,
        "tree_mine_bl15": tree_mine_bl15,
        "avg_rules": round(float(np.mean(rule_cnts)), 2) if rule_cnts else 0.0,
        "latest_bidir_rules": m_bi["rules"] if m_bi else [],
        "latest_mine_rules": m_mn["rules"] if m_mn else [],
    }


def main():
    t0 = time.time()
    bundle = cm.build_or_load_cache(force_rebuild=False)
    print(f"[M3+M4] Cache loaded in {time.time()-t0:.2f}s | RSS={cm.rss_mb()} MB", flush=True)

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
        min_leaf = cm.MIN_LEAF_MAP[st]
        min_days = cm.MIN_DAYS_MAP[st]
        base_cols = list(dict.fromkeys(bundle["base_dyn_cols"] + af_cols))
        rfreq = "daily"
        mds_use = (8, 12, 15, 25) if st == "1to2" else (8, 12, 15)

        # M1 cold weak-atom surgery stack base
        sc_m1_stack = m12.run_causal_cold_atom_disable(df, af_cols, af_mat, cold_cut=50.0, t_cut=-0.5, bonus_only=True, decluster_days=decluster)

        # =====================================================================
        # MODULE 3: 3-Way Synergy + Triple Minefield + Depth-3 Regularized Tree
        # =====================================================================
        r3 = run_wf_3way_4way_and_trees(df, base_cols, min_leaf=min_leaf, min_days=min_days, order=3, decluster_days=decluster, run_trees=True, recalc_freq=rfreq, max_deltas=mds_use)
        for md in mds_use:
            # 3A: 3-Way Bidir & PosOnly injection
            for tag_d, dmap in [("3Way_Bidir", r3["deltas_bidir"]), ("3Way_PosOnly", r3["deltas_pos"])]:
                ps, sl = cm.sim_strategy(st, df, orig + dmap[md], wf_only=True)
                add_var(st, "M3_3WaySynergy", f"M3_{tag_d}_d{md}", ps, sl)
                if md == 12:
                    ps_s, sl_s = cm.sim_strategy(st, df, sc_m1_stack + dmap[md], wf_only=True)
                    add_var(st, "M3_3WaySynergy", f"M3_{tag_d}_StackColdAtom_d12", ps_s, sl_s)
                    if st == "pry":
                        ps_p, sl_p = cm.sim_strategy(st, df, orig + dmap[md], mask=(mkt10 >= 50), wf_only=True)
                        add_var(st, "M3_3WaySynergy", f"M3_{tag_d}_SkipCold50_d12", ps_p, sl_p)
            # 3C: Depth-3 Regularized Trees (Single & Bagged)
            ps_ts, sl_ts = cm.sim_strategy(st, df, orig + r3["tree_single"][md], wf_only=True)
            add_var(st, "M3_TreeDepth3", f"M3_TreeD3_Single_d{md}", ps_ts, sl_ts)
            ps_tb, sl_tb = cm.sim_strategy(st, df, orig + r3["tree_bag"][md], wf_only=True)
            add_var(st, "M3_TreeDepth3", f"M3_TreeD3_Bag7_d{md}", ps_tb, sl_tb)

        # 3B: Triple Minefield Blacklist (top 15%, plus 10%/20% neighborhood, plus TreeD3 mine BL15)
        for q in (10, 15, 20):
            ps_m, sl_m = cm.sim_strategy(st, df, orig, mask=(~r3["mine_bl"][q]), wf_only=True)
            add_var(st, "M3_3WayMineBL", f"M3_3WayMineBL{q}_SafePool", ps_m, sl_m)
        ps_tm, sl_tm = cm.sim_strategy(st, df, orig, mask=(~r3["tree_mine_bl15"]), wf_only=True)
        add_var(st, "M3_3WayMineBL", "M3_TreeD3_MineBL15_SafePool", ps_tm, sl_tm)

        for r in r3["latest_bidir_rules"]:
            rule_records.append({"strategy": st, "module": "M3_3Way_Bidir", **r})
        for r in r3["latest_mine_rules"]:
            rule_records.append({"strategy": st, "module": "M3_3Way_Mine", **r})

        # =====================================================================
        # MODULE 4: 4-Way Synergy + Depth-4 Tree (on 1to2, 2to3, pry, 3to4)
        # =====================================================================
        if st != "high":
            r4 = run_wf_3way_4way_and_trees(df, base_cols, min_leaf=min_leaf, min_days=min_days, order=4, decluster_days=decluster, run_trees=True, recalc_freq=rfreq, max_deltas=mds_use)
            for md in mds_use:
                for tag_d, dmap in [("4Way_Bidir", r4["deltas_bidir"]), ("4Way_PosOnly", r4["deltas_pos"])]:
                    ps, sl = cm.sim_strategy(st, df, orig + dmap[md], wf_only=True)
                    add_var(st, "M4_4WaySynergy", f"M4_{tag_d}_d{md}", ps, sl)
                ps_ts4, sl_ts4 = cm.sim_strategy(st, df, orig + r4["tree_single"][md], wf_only=True)
                add_var(st, "M4_TreeDepth4", f"M4_TreeD4_Single_d{md}", ps_ts4, sl_ts4)
                ps_tb4, sl_tb4 = cm.sim_strategy(st, df, orig + r4["tree_bag"][md], wf_only=True)
                add_var(st, "M4_TreeDepth4", f"M4_TreeD4_Bag7_d{md}", ps_tb4, sl_tb4)
            for q in (15,):
                ps_m4, sl_m4 = cm.sim_strategy(st, df, orig, mask=(~r4["mine_bl"][q]), wf_only=True)
                add_var(st, "M4_4WayMineBL", f"M4_4WayMineBL{q}_SafePool", ps_m4, sl_m4)
            ps_tm4, sl_tm4 = cm.sim_strategy(st, df, orig, mask=(~r4["tree_mine_bl15"]), wf_only=True)
            add_var(st, "M4_4WayMineBL", "M4_TreeD4_MineBL15_SafePool", ps_tm4, sl_tm4)
            for r in r4["latest_bidir_rules"]:
                rule_records.append({"strategy": st, "module": "M4_4Way_Bidir", **r})
            for r in r4["latest_mine_rules"]:
                rule_records.append({"strategy": st, "module": "M4_4Way_Mine", **r})
            avg4 = r4["avg_rules"]
        else:
            avg4 = "SKIPPED_N62"

        print(f"  [{st} M3+M4 DONE in {time.time()-t_st:.1f}s] avg_3way={r3['avg_rules']} avg_4way={avg4} | total={len(rows)} | RSS={cm.rss_mb()} MB", flush=True)

    df_m34 = pd.DataFrame(rows)
    df_m34.to_csv(f"{cm.CACHE_DIR}/m3_m4_grid.csv", index=False)
    with open(f"{cm.CACHE_DIR}/m3_m4_drs.pkl", "wb") as f:
        pickle.dump(dr_map, f)
    with open(f"{cm.CACHE_DIR}/m3_m4_top_rules.json", "w", encoding="utf-8") as f:
        json.dump(cm.sanitize_json(rule_records), f, ensure_ascii=False, indent=2)

    print(f"\n[M3+M4 ALL DONE in {time.time()-t0:.1f}s] {len(df_m34)} variants | Peak RSS={cm.rss_mb()} MB")
    for st in cm.OTHER5:
        sub = df_m34[df_m34["strategy"] == st].sort_values("nav_wf", ascending=False)
        print(f"\n--- Top 8 M3/M4 for {st} ---")
        print(sub[["variant_id", "n_trades", "wr_pct", "nav_wf", "ex5_wf", "exact_mtm_sharpe", "nav_2526", "nav_26h2", "nav_80bps", "paired_t", "comb_nav_ratio"]].head(8).to_string(index=False))


if __name__ == "__main__":
    main()

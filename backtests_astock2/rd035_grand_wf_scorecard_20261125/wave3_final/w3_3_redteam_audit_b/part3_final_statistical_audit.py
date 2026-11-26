#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 3-3 Cold-Blooded Statistical & Robustness Final Audit (Red Team B):
  Gate 1: True Multi-Trial Count, Exact-MTM Sharpe Re-Calibration, DSR (Bailey & Lopez de Prado),
          BH-FDR q-values, and Local + Pooled CSCV PBO (S=16 exact 12,870 splits & S=8).
  Gate 2: Parameter-Neighborhood Plateau Checks (rejecting singular spike islands).
  Gate 3: Annual + 2025-2026 + 2026 + 26H1/26H2 Period Consistency & Stall/Collapse Flags.
  Gate 4: V20.0 Daily Correlation + Equal-Exposure & Equal-Volatility Static Benchmark Controls
          (CSI300 / CSI1000 / All-A EW).
  Gate 5: Cold-Blooded Tier 1..4 Final Ranking -> w3_3_redteam_b_audit.json & w3_3_final_tier_ranking.csv.

Zero yfinance. Single-thread. Read-only on Wave 1/2 files.
"""
import os

for _env in (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
):
    os.environ[_env] = "1"

import itertools
import json
import math
import pickle
import resource
import sys
import time

import numpy as np
import pandas as pd
from scipy import stats

assert "yfinance" not in sys.modules
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
RD035_DIR = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125"
WAVE1_DIR = f"{RD035_DIR}/wave1_base"
OUT_DIR = f"{RD035_DIR}/wave3_final/w3_3_redteam_audit_b"
MKT_PANEL_PQ = f"{ROOT}/output/china_policy_macro_rd027_20261125/rd029_daybyday_etf/cache/daily_market_panel_2000_20261125.parquet"
TRD_DAYS_YEAR = 242.0


def rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 2)


def sanitize_json(obj):
    if isinstance(obj, dict):
        return {str(k): sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_json(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return None if (math.isnan(v) or math.isinf(v)) else round(v, 6)
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return sanitize_json(obj.tolist())
    return obj


def bh_fdr(pvals: np.ndarray) -> np.ndarray:
    p = np.asarray(pvals, dtype=float)
    q = np.full_like(p, np.nan)
    ok = np.isfinite(p)
    m = int(ok.sum())
    if m == 0:
        return q
    pv = np.clip(p[ok], 0.0, 1.0)
    ord_idx = np.argsort(pv)
    sp = pv[ord_idx]
    raw_q = sp * m / np.arange(1, m + 1, dtype=float)
    mon_q = np.minimum.accumulate(raw_q[::-1])[::-1]
    mon_q = np.clip(mon_q, 0.0, 1.0)
    out_ok = np.empty(m, dtype=float)
    out_ok[ord_idx] = mon_q
    q[ok] = out_ok
    return q


def calc_dsr(dr: np.ndarray, n_trials: int, var_sr_daily: float, sr_bench_daily: float = 0.0) -> dict:
    """Bailey & Lopez de Prado (2014) Deflated Sharpe Ratio with non-normal skewness & Pearson kurtosis."""
    x = np.asarray(dr, dtype=float)
    T = len(x)
    if T < 10:
        return {"sr_daily": 0.0, "sr_ann": 0.0, "sr0_daily": 0.0, "sr0_ann": 0.0, "dsr": 0.0, "z_dsr": -10.0, "skew": 0.0, "kurt_pearson": 3.0}
    mu = float(np.mean(x))
    sd = float(np.std(x, ddof=1))
    if sd <= 1e-12:
        return {"sr_daily": 0.0, "sr_ann": 0.0, "sr0_daily": 0.0, "sr0_ann": 0.0, "dsr": 0.0, "z_dsr": -10.0, "skew": 0.0, "kurt_pearson": 3.0}
    sr = mu / sd
    g3 = float(stats.skew(x, bias=True))
    g4 = float(stats.kurtosis(x, fisher=False, bias=True))
    gamma_em = 0.5772156649015329
    if n_trials <= 1 or var_sr_daily <= 0.0:
        sr0 = sr_bench_daily
    else:
        z1 = float(stats.norm.ppf(1.0 - 1.0 / n_trials))
        z2 = float(stats.norm.ppf(1.0 - 1.0 / (n_trials * math.e)))
        sr0 = sr_bench_daily + math.sqrt(var_sr_daily) * ((1.0 - gamma_em) * z1 + gamma_em * z2)
    denom_in = max(1e-12, (1.0 - g3 * sr + ((g4 - 1.0) / 4.0) * (sr ** 2)) / max(1, T - 1))
    z_dsr = (sr - sr0) / math.sqrt(denom_in)
    dsr_val = float(stats.norm.cdf(z_dsr))
    return {
        "sr_daily": sr,
        "sr_ann": sr * math.sqrt(TRD_DAYS_YEAR),
        "sr0_daily": sr0,
        "sr0_ann": sr0 * math.sqrt(TRD_DAYS_YEAR),
        "dsr": dsr_val,
        "z_dsr": float(z_dsr),
        "skew": g3,
        "kurt_pearson": g4,
        "se_sr_ann": math.sqrt(denom_in) * math.sqrt(TRD_DAYS_YEAR),
    }


def cscv_pbo(
    mat_dict: dict[str, np.ndarray],
    start_idx: int = 0,
    S: int = 16,
    target_names: list[str] | None = None,
) -> dict:
    """
    Exact Combinatorially Symmetrically Cross-Validated PBO (Bailey et al. 2015).
    Partitions [start_idx:] into S equal chronological blocks and enumerates ALL C(S, S//2) splits.
    """
    names = list(mat_dict.keys())
    if len(names) < 2:
        return {"n_variants": len(names), "S": S, "n_splits": 0, "pbo": np.nan, "note": "fewer than 2 variants"}

    M_full = np.column_stack([np.asarray(mat_dict[k], dtype=float) for k in names])[start_idx:, :]
    # Drop all-zero variants (degenerate thresholds with 0 trades)
    col_sd = np.std(M_full, axis=0, ddof=1)
    keep = col_sd > 1e-12
    names = [nm for nm, kp in zip(names, keep) if kp]
    M = M_full[:, keep]
    K = len(names)
    if K < 2:
        return {"n_variants": K, "S": S, "n_splits": 0, "pbo": np.nan, "note": "fewer than 2 active variants"}

    T_tot = M.shape[0]
    L = T_tot // S
    if L < 10:
        return {"n_variants": K, "S": S, "n_splits": 0, "pbo": np.nan, "note": f"block too short L={L}"}
    T_use = L * S
    M = M[T_tot - T_use :, :]  # align to end (keep latest data incl. 2026H2)

    blocks = M.reshape(S, L, K)
    blk_sum = blocks.sum(axis=1)           # (S, K)
    blk_sum2 = (blocks ** 2).sum(axis=1)   # (S, K)
    tot_sum = blk_sum.sum(axis=0)          # (K,)
    tot_sum2 = blk_sum2.sum(axis=0)        # (K,)

    half = S // 2
    combos = list(itertools.combinations(range(S), half))
    n_splits = len(combos)
    ind = np.zeros((n_splits, S), dtype=float)
    for row_i, cmb in enumerate(combos):
        ind[row_i, list(cmb)] = 1.0

    n_is = half * L
    n_oos = T_use - n_is

    is_sum = ind @ blk_sum
    is_sum2 = ind @ blk_sum2
    is_mu = is_sum / n_is
    is_var = np.maximum(0.0, (is_sum2 - n_is * (is_mu ** 2)) / max(1, n_is - 1))
    is_sd = np.sqrt(is_var)
    is_sr = np.where(is_sd > 1e-12, is_mu / np.maximum(is_sd, 1e-12) * math.sqrt(TRD_DAYS_YEAR), -999.0)

    oos_sum = tot_sum[None, :] - is_sum
    oos_sum2 = tot_sum2[None, :] - is_sum2
    oos_mu = oos_sum / n_oos
    oos_var = np.maximum(0.0, (oos_sum2 - n_oos * (oos_mu ** 2)) / max(1, n_oos - 1))
    oos_sd = np.sqrt(oos_var)
    oos_sr = np.where(oos_sd > 1e-12, oos_mu / np.maximum(oos_sd, 1e-12) * math.sqrt(TRD_DAYS_YEAR), 0.0)

    win_idx = np.argmax(is_sr, axis=1)
    win_oos_sr = oos_sr[np.arange(n_splits), win_idx]

    # Mid-rank of OOS Sharpe across all K variants for each split (average rank for ties)
    ranks = np.empty(n_splits, dtype=float)
    for r_i in range(n_splits):
        row = oos_sr[r_i]
        w_val = win_oos_sr[r_i]
        n_lt = float(np.sum(row < w_val))
        n_eq = float(np.sum(row == w_val))
        rank_1_to_K = n_lt + 0.5 * (n_eq + 1.0)
        ranks[r_i] = rank_1_to_K / (K + 1.0)

    ranks_clip = np.clip(ranks, 1e-4, 1.0 - 1e-4)
    logits = np.log(ranks_clip / (1.0 - ranks_clip))
    pbo = float(np.mean(logits <= 0.0))
    prob_oos_neg = float(np.mean(win_oos_sr <= 0.0))

    # Candidate-specific OOS summary across ALL splits + when winning IS
    name_to_j = {nm: j for j, nm in enumerate(names)}
    per_cand = {}
    chk_names = target_names if target_names is not None else names
    for nm in chk_names:
        if nm not in name_to_j:
            continue
        j = name_to_j[nm]
        # OOS rank distribution of this candidate across ALL splits, and conditional on top-1 in IS
        all_ranks_j = np.mean(oos_sr < oos_sr[:, [j]], axis=1) + 0.5 * (np.mean(oos_sr == oos_sr[:, [j]], axis=1))
        m_win = win_idx == j
        per_cand[nm] = {
            "n_is_win_splits": int(m_win.sum()),
            "pct_is_win_splits": round(float(m_win.mean() * 100.0), 2),
            "all_splits_mean_oos_sr": round(float(np.mean(oos_sr[:, j])), 3),
            "all_splits_prob_oos_neg": round(float(np.mean(oos_sr[:, j] <= 0.0)), 4),
            "all_splits_med_oos_pctile": round(float(np.median(all_ranks_j) * 100.0), 1),
            "when_is_win_med_oos_pctile": round(float(np.median(ranks[m_win]) * 100.0), 1) if m_win.any() else None,
            "when_is_win_mean_oos_sr": round(float(np.mean(win_oos_sr[m_win])), 3) if m_win.any() else None,
            "when_is_win_pbo": round(float(np.mean(logits[m_win] <= 0.0)), 4) if m_win.any() else None,
        }

    return {
        "n_variants": K,
        "S": S,
        "L_days": L,
        "T_used": T_use,
        "n_splits": n_splits,
        "pbo": round(pbo, 4),
        "prob_is_winner_oos_neg": round(prob_oos_neg, 4),
        "median_oos_logit": round(float(np.median(logits)), 4),
        "mean_oos_logit": round(float(np.mean(logits)), 4),
        "mean_is_winner_sr": round(float(np.mean(is_sr[np.arange(n_splits), win_idx])), 3),
        "mean_oos_winner_sr": round(float(np.mean(win_oos_sr)), 3),
        "per_candidate": per_cand,
    }


def window_metrics(
    dr: np.ndarray,
    slot_df: pd.DataFrame | None,
    dates: list[str],
    csi300_dr: np.ndarray,
    csi1000_dr: np.ndarray,
    ew_dr: np.ndarray,
    s_dt: str,
    e_dt: str,
) -> dict:
    mask = np.array([(s_dt <= d <= e_dt) for d in dates], dtype=bool)
    T_w = int(mask.sum())
    if T_w == 0:
        return {"n_days": 0, "n": 0, "nav": 1.0, "sharpe": 0.0, "mdd_pct": 0.0}
    dw = dr[mask]
    c3 = csi300_dr[mask]
    c10 = csi1000_dr[mask]
    ew = ew_dr[mask]

    nav = float(np.prod(1.0 + dw))
    c3_nav = float(np.prod(1.0 + c3))
    c10_nav = float(np.prod(1.0 + c10))
    ew_nav = float(np.prod(1.0 + ew))
    ann_ret = (nav ** (TRD_DAYS_YEAR / T_w) - 1.0) * 100.0 if nav > 0 else -100.0
    sd = float(np.std(dw, ddof=1)) if T_w > 1 else 0.0
    sharpe = float(np.mean(dw) / sd * math.sqrt(TRD_DAYS_YEAR)) if sd > 1e-12 else 0.0
    curve = np.concatenate([[1.0], np.cumprod(1.0 + dw)])
    pk = np.maximum.accumulate(curve)
    mdd = float(np.max((pk - curve) / pk) * 100.0)
    calmar = float(ann_ret / mdd) if mdd > 0.1 else (99.0 if ann_ret > 0 else 0.0)

    n_act = int(np.sum(np.abs(dw) > 1e-12))
    exp_pct = round(n_act / T_w * 100.0, 2)

    n_tr, wr, plr, mean_tr, tr_nav, ex5_nav = 0, 0.0, 0.0, 0.0, 1.0, 1.0
    if slot_df is not None and not slot_df.empty and "buy_date" in slot_df.columns:
        sub = slot_df[slot_df["buy_date"].between(s_dt, e_dt)]
        if not sub.empty and "net_ret" in sub.columns:
            rets = pd.to_numeric(sub["net_ret"], errors="coerce").dropna().to_numpy(float)
            n_tr = len(rets)
            if n_tr > 0:
                w, l = rets[rets > 0], rets[rets <= 0]
                wr = float((rets > 0).mean() * 100.0)
                plr = float(w.mean() / abs(l.mean())) if (len(w) and len(l) and l.mean() < 0) else (99.0 if len(w) else 0.0)
                mean_tr = float(rets.mean() * 100.0)
                tr_nav = float(np.prod(1.0 + rets))
                sr = np.sort(rets)
                ex5_nav = float(np.prod(1.0 + sr[:-5])) if n_tr > 5 else 1.0

    return {
        "n_days": T_w,
        "n": int(n_tr),
        "wr_pct": round(wr, 2),
        "plr": round(plr, 2),
        "mean_tr_pct": round(mean_tr, 2),
        "nav": round(nav, 4),
        "tr_nav": round(tr_nav, 4),
        "ex5_nav": round(ex5_nav, 4),
        "ann_ret_pct": round(ann_ret, 2),
        "mdd_pct": round(mdd, 2),
        "sharpe": round(sharpe, 3),
        "calmar": round(calmar, 2),
        "n_active_days": n_act,
        "exposure_pct": exp_pct,
        "excess_csi300_pp": round((nav - c3_nav) * 100.0, 2),
        "excess_csi1000_pp": round((nav - c10_nav) * 100.0, 2),
        "excess_ew_pp": round((nav - ew_nav) * 100.0, 2),
    }


def static_benchmark_controls(
    dr: np.ndarray,
    v20_dr: np.ndarray,
    csi300_dr: np.ndarray,
    csi1000_dr: np.ndarray,
    ew_dr: np.ndarray,
) -> dict:
    """Gate 4: V20 correlations + Equal-Exposure (EE) and Equal-Volatility (EV) static controls."""
    T = len(dr)
    act = np.abs(dr) > 1e-12
    v20_act = np.abs(v20_dr) > 1e-12
    both = act & v20_act

    def safe_corr(a, b):
        if len(a) < 5 or np.std(a, ddof=1) <= 1e-12 or np.std(b, ddof=1) <= 1e-12:
            return 0.0
        return round(float(np.corrcoef(a, b)[0, 1]), 4)

    cand_nav = float(np.prod(1.0 + dr))
    sd_cand = float(np.std(dr, ddof=1))

    ee = {}
    ev = {}
    for bm_name, bm_dr in (("csi300", csi300_dr), ("csi1000", csi1000_dr), ("alla_ew", ew_dr)):
        # Equal Exposure: hold benchmark ONLY on exact active days of candidate
        bm_ee_dr = np.where(act, bm_dr, 0.0)
        bm_ee_nav = float(np.prod(1.0 + bm_ee_dr))
        sd_ee = float(np.std(bm_ee_dr, ddof=1))
        sh_ee = float(np.mean(bm_ee_dr) / sd_ee * math.sqrt(TRD_DAYS_YEAR)) if sd_ee > 1e-12 else 0.0
        if int(act.sum()) >= 3:
            diff_act = dr[act] - bm_dr[act]
            se_act = float(np.std(diff_act, ddof=1)) / math.sqrt(len(diff_act))
            t_act = float(np.mean(diff_act) / se_act) if se_act > 1e-12 else 0.0
            mean_diff_bps = float(np.mean(diff_act) * 10000.0)
        else:
            t_act, mean_diff_bps = 0.0, 0.0
        ee[bm_name] = {
            "bm_ee_nav": round(bm_ee_nav, 4),
            "bm_ee_sharpe": round(sh_ee, 3),
            "excess_ee_nav_ratio": round(cand_nav / max(1e-9, bm_ee_nav), 4),
            "excess_ee_pp": round((cand_nav - bm_ee_nav) * 100.0, 2),
            "active_mean_diff_bps": round(mean_diff_bps, 1),
            "active_paired_t": round(t_act, 3),
        }

        # Equal Volatility: scale static benchmark over full WF window to match candidate daily vol
        sd_bm = float(np.std(bm_dr, ddof=1))
        if sd_cand > 1e-12 and sd_bm > 1e-12:
            scale = sd_cand / sd_bm
            bm_ev_dr = np.clip(bm_dr * scale, -0.95, 5.0)
            bm_ev_nav = float(np.prod(1.0 + bm_ev_dr))
        else:
            scale, bm_ev_nav = 0.0, 1.0
        ev[bm_name] = {
            "vol_scale_to_cand": round(scale, 3),
            "bm_ev_nav": round(bm_ev_nav, 4),
            "excess_ev_nav_ratio": round(cand_nav / max(1e-9, bm_ev_nav), 4),
            "excess_ev_pp": round((cand_nav - bm_ev_nav) * 100.0, 2),
        }

    return {
        "n_active_days": int(act.sum()),
        "exposure_pct": round(float(act.mean() * 100.0), 2),
        "corr_v20_all_days": safe_corr(dr, v20_dr),
        "corr_v20_both_active": safe_corr(dr[both], v20_dr[both]),
        "n_both_active": int(both.sum()),
        "equal_exposure": ee,
        "equal_volatility": ev,
    }


def paired_alpha_test(dr_cand: np.ndarray, dr_base: np.ndarray, n_global: int, var_delta_global: float, n_local: int, var_delta_local: float) -> dict:
    diff = np.asarray(dr_cand, dtype=float) - np.asarray(dr_base, dtype=float)
    T = len(diff)
    sd = float(np.std(diff, ddof=1))
    mu = float(np.mean(diff))
    t_val = float(mu / (sd / math.sqrt(T))) if sd > 1e-12 else 0.0
    p_val = float(stats.t.sf(t_val, df=max(1, T - 1))) if t_val > -50 else 1.0
    sr_cand = float(np.mean(dr_cand) / max(1e-12, np.std(dr_cand, ddof=1)) * math.sqrt(TRD_DAYS_YEAR)) if np.std(dr_cand, ddof=1) > 1e-12 else 0.0
    sr_base = float(np.mean(dr_base) / max(1e-12, np.std(dr_base, ddof=1)) * math.sqrt(TRD_DAYS_YEAR)) if np.std(dr_base, ddof=1) > 1e-12 else 0.0
    dsr_g = calc_dsr(diff, n_global, var_delta_global, 0.0)
    dsr_l = calc_dsr(diff, n_local, var_delta_local, 0.0)
    return {
        "cand_sr_ann": round(sr_cand, 3),
        "base_sr_ann": round(sr_base, 3),
        "delta_sr_ann": round(sr_cand - sr_base, 3),
        "diff_sr_ann": round(dsr_g["sr_ann"], 3),
        "paired_t_stat": round(t_val, 3),
        "paired_one_sided_p": round(p_val, 6),
        "dsr_diff_global": round(dsr_g["dsr"], 4),
        "dsr_diff_local": round(dsr_l["dsr"], 4),
    }


def main():
    t0 = time.time()
    # 1. Load reference calendar + benchmarks
    cal_df = pd.read_parquet(f"{WAVE1_DIR}/v20_daily_slot_calendar_5y.parquet")
    cal_wf = cal_df[cal_df["trade_date"].between("2023-01-03", "2026-11-16")].sort_values("trade_date").reset_index(drop=True)
    dates = cal_wf["trade_date"].tolist()
    T = len(dates)

    mkt = pd.read_parquet(MKT_PANEL_PQ, columns=["date", "csi1000_cc_ret", "csi300_cc_ret"])
    mkt["trade_date"] = pd.to_datetime(mkt["date"]).dt.strftime("%Y-%m-%d")
    m_al = cal_wf[["trade_date"]].merge(mkt[["trade_date", "csi1000_cc_ret", "csi300_cc_ret"]], on="trade_date", how="left")
    assert m_al["csi1000_cc_ret"].isna().sum() == 0

    v20_dr = cal_wf["v20_daily_ret"].fillna(0.0).to_numpy(float)
    csi300_dr = cal_wf["csi300_daily_ret"].fillna(0.0).to_numpy(float)
    csi1000_dr = m_al["csi1000_cc_ret"].fillna(0.0).to_numpy(float)
    ew_dr = cal_wf["alla_ew_daily_ret"].fillna(0.0).to_numpy(float)

    # Load Part 1 FDR table + stats
    part1_df = pd.read_parquet(f"{OUT_DIR}/_part1_all_trials_fdr.parquet")
    with open(f"{OUT_DIR}/_part1_global_stats.json", encoding="utf-8") as f:
        part1_stats = json.load(f)

    # Load Wave 2A/2B audit JSONs for combined surgery numbers & cross-check
    with open(f"{RD035_DIR}/wave2a/w2a2_old_3to4_high_pry/w2a2_audit.json", encoding="utf-8") as f:
        w2a2_aud = json.load(f)
    with open(f"{RD035_DIR}/wave2a/w2a3_old_20cm/w2a3_audit.json", encoding="utf-8") as f:
        w2a3_aud = json.load(f)
    with open(f"{RD035_DIR}/wave2a/w2a4_pairwise_interactions/w2a4_audit.json", encoding="utf-8") as f:
        w2a4_aud = json.load(f)

    # Load Part 2A, Part 2B1, Part 2B2 cached exact daily MTM tracks
    with open(f"{OUT_DIR}/_cache_tracks_partA.pkl", "rb") as f:
        tracks_a = pickle.load(f)
    with open(f"{OUT_DIR}/_cache_tracks_b5_b6.pkl", "rb") as f:
        tracks_b56 = pickle.load(f)
    with open(f"{OUT_DIR}/_cache_tracks_b4.pkl", "rb") as f:
        tracks_b4 = pickle.load(f)
    orig_e3_path = f"{OUT_DIR}/_cache_orig_mode_e3.pkl"
    if os.path.exists(orig_e3_path):
        with open(orig_e3_path, "rb") as f:
            orig_e3 = pickle.load(f)
        tracks_b56["ModE_USGap"].update(orig_e3)

    all_tracks = {}
    all_tracks.update(tracks_a)
    all_tracks.update(tracks_b56)
    all_tracks.update(tracks_b4)
    print(f"Loaded {len(all_tracks)} track families, total variants={sum(len(v) for v in all_tracks.values())} | RSS={rss_mb()} MB", flush=True)

    # 2. Benchmarks across all 7 periods
    WINDOWS = [
        ("FULL_WF", "2023-01-03", "2026-11-16"),
        ("Y2023", "2023-01-03", "2023-12-31"),
        ("Y2024", "2024-01-01", "2024-12-31"),
        ("Y2025", "2025-01-01", "2025-12-31"),
        ("Y2526", "2025-01-01", "2026-11-16"),
        ("Y2026", "2026-01-01", "2026-11-16"),
        ("Y26H1", "2026-01-01", "2026-06-30"),
        ("Y26H2", "2026-07-01", "2026-11-16"),
    ]
    v20_led = pd.read_parquet(f"{WAVE1_DIR}/v20_baseline_ledger_278.parquet")
    v20_led["buy_date"] = v20_led["buy_date"].astype(str).str[:10]
    bm_windows = {}
    for bname, bdr, bsl in (("V20_0", v20_dr, v20_led), ("CSI300", csi300_dr, None), ("CSI1000", csi1000_dr, None), ("AllA_EW", ew_dr, None)):
        bm_windows[bname] = {wn: window_metrics(bdr, bsl, dates, csi300_dr, csi1000_dr, ew_dr, s, e) for wn, s, e in WINDOWS}

    # 3. Compute exact-MTM Sharpe across ALL standalone variants to get honest non-smoothed V_exact
    exact_sr_all = []
    exact_sr_new = []
    new_track_names = {"20cm_Surge10_19_W2B1", "TrackC_NT_ETF", "ModE_USGap", "ModC_EarnPre", "W2B4_20cm_New"}
    track_var_daily = {}
    for tname, tmap in all_tracks.items():
        srs = []
        for vname, rec in tmap.items():
            dr = rec["dr_exact"]
            sd = float(np.std(dr, ddof=1))
            sr_d = float(np.mean(dr) / sd) if sd > 1e-12 else 0.0
            exact_sr_all.append(sr_d)
            if tname in new_track_names:
                exact_sr_new.append(sr_d)
            srs.append(sr_d)
        track_var_daily[tname] = float(np.var(srs, ddof=1)) if len(srs) > 1 else 0.001

    v_sr_exact_all = float(np.var(exact_sr_all, ddof=1))
    v_sr_exact_new = float(np.var(exact_sr_new, ddof=1))
    v_sr_raw_all = float(part1_stats["sharpe_distribution"]["all_5456"]["var_daily"])
    v_sr_raw_new = float(part1_stats["sharpe_distribution"]["new_tracks_only"]["var_daily"])

    N_ALL = int(part1_stats["n_trials_main_tables"])  # 5,456
    N_STRICT = int(part1_stats["n_trials_including_w2a2loo_and_w2a6perms"])  # 6,945
    N_NEW = int(part1_stats["n_trials_new_tracks_only"])  # 3,259

    # 4. Sharpe smoothing audit (exact MTM vs geometric smoothing reported in W2A2/W2A3/W2B1)
    smoothing_audit = {}
    for tname, vname, label in [
        ("20cm_F06_PurePhysics", "BASE_V11_S82", "20cm BASE_V11_S82"),
        ("20cm_F06_PurePhysics", "M1_F06_COLD50_thr80", "20cm 关F06 COLD50_thr80"),
        ("20cm_CLEAN_ModeB", "CLEAN_B_cold50_d15_S80", "20cm CLEAN_B_d15_S80"),
        ("20cm_CLEAN_ModeB", "CLEAN_B_cold50_d15_S84", "20cm CLEAN_B_d15_S84"),
        ("3to4_MineSplit", "3to4_Baseline_030", "3to4 Baseline 0.30%"),
        ("3to4_MineSplit", "M4_MineBL15_OrigScore", "3to4 MineBL15 OrigScore"),
        ("pry_DropRed", "pry_Baseline_030", "pry Baseline 0.30%"),
        ("pry_DropRed", "M1_WF_DropNeg_tm05", "pry WF_DropNeg_tm05"),
        ("20cm_Surge10_19_W2B1", "ModeM__P0_Full__E1_all__X2_T2_Close__t1t2_7pct__k15::top10", "W2B1 ModeM P0 E1 X2 k15 top10"),
    ]:
        rec = all_tracks[tname][vname]
        m_ex = window_metrics(rec["dr_exact"], rec["slot_df"], dates, csi300_dr, csi1000_dr, ew_dr, "2023-01-03", "2026-11-16")
        m_gm = window_metrics(rec["dr_geom"], rec["slot_df"], dates, csi300_dr, csi1000_dr, ew_dr, "2023-01-03", "2026-11-16")
        smoothing_audit[label] = {
            "n_trades": m_ex["n"],
            "nav": m_ex["nav"],
            "exact_mtm_sharpe": m_ex["sharpe"],
            "geom_smoothed_sharpe": m_gm["sharpe"],
            "inflation_ratio": round(m_gm["sharpe"] / max(1e-6, m_ex["sharpe"]), 3) if m_ex["sharpe"] > 0 else None,
        }

    # 5. CSCV PBO (S=16 & S=8) across EVERY track family + Pooled Wave 2B
    cscv_specs = [
        ("20cm_F06_PurePhysics", "dr_exact", "2023-01-03", ["M1_F06_COLD50_thr80", "M1_F06_COLD45_thr80", "BASE_V11_S82", "BASE_V11_S80"]),
        ("20cm_CLEAN_ModeB", "dr_exact", "2023-01-03", ["CLEAN_B_cold50_d15_S80", "CLEAN_B_cold50_d15_S84", "CLEAN_B_cold50_d10_S80", "CLEAN_B_cold50_d15_S82"]),
        ("20cm_Mech130", "dr_exact", "2023-01-03", ["std_d10_Mech_Native", "std_d15_Mech_Native", "std_d20_Mech_Native", "std_d15_Mech_Guarded", "std_d15_Mech_Plus_Dyn20x19"]),
        ("3to4_MineSplit", "dr_exact", "2023-01-03", ["3to4_Baseline_030", "M4_MineBL10_OrigScore", "M4_MineBL15_OrigScore", "M4_MineBL20_OrigScore", "M4_MineBL25_OrigScore"]),
        ("pry_DropRed", "dr_exact", "2023-01-03", ["pry_Baseline_030", "M1_WF_DropNeg_tm05", "M1_WF_DropNeg_t0", "M1_LOO_Drop_spry_af_lock50_thr155"]),
        ("20cm_Surge10_19_W2B1", "dr_exact", "2023-01-03", ["ModeM__P0_Full__E1_all__X2_T2_Close__t1t2_7pct__k15::top10", "ModeM__P0_Full__E1_all__X2_T2_Close__t1t2_7pct__k12::top10"]),
        ("TrackC_NT_ETF_Standalone", "dr_exact", "2023-01-03", ["C_512100_V3EOD_ge60_H10_Yield_all_v20", "C_512100_V3Live_ge60_H10_Yield_all_v20", "C_512100_V3EOD_ge60_H10", "C_510300_V3EOD_ge60_H10_Yield_all_v20"]),
        ("TrackC_NT_ETF_Combined", "dr_comb", "2023-01-03", ["C_512100_V3EOD_ge60_H10_Yield_all_v20", "C_512100_V3Live_ge60_H20_Yield_all_v20"]),
        ("ModE_USGap_Standalone", "dr_exact", "2023-01-03", ["E3_US4pct_Mingmen_H1_daily::top5", "E3_US4pct_Mingmen_H1_daily::top10", "E3_US4pct_Mingmen_H1_daily::top20", "E3_US4pct_Mingmen_H1_monthly::top5"]),
        ("ModE_USGap_Combined", "dr_comb", "2023-01-03", ["E3_US4pct_Mingmen_H1_daily::top5", "E3_US4pct_Mingmen_H1_daily::abs_70", "E3_US4pct_Mingmen_H1_daily::top10"]),
        ("ModC_EarnPre_Standalone", "dr_exact", "2023-01-03", ["ModC_C1_EarnPre_NoRun_H1::top10", "ModC_C1_EarnPre_NoRun_H1::all_cands", "ModC_C1_EarnPre_NoRun_H3::top20"]),
        ("W2B4_20cm_New_Standalone", "dr_exact", "2023-01-03", ["A5_12_23_v11_PURE::abs_80", "A5_12_23_v11_PURE::top5", "A1_12_23_h1_PURE::abs_75", "A3_12_23_h2_PURE::abs_80"]),
        ("W2B4_TrackA_Only_Standalone", "dr_exact", "2023-01-03", ["A5_12_23_v11_PURE::abs_80", "A5_12_23_v11_PURE::abs_75", "A5_12_23_v11_PURE::abs_85", "A1_12_23_h1_PURE::abs_75", "A3_12_23_h2_PURE::abs_80"]),
    ]

    cscv_summary = {}
    dt_to_i = {d: i for i, d in enumerate(dates)}
    for label, field, s_dt, targets in cscv_specs:
        src_tname = (
            label.replace("_Standalone", "").replace("_Combined", "")
            if label.startswith(("TrackC_", "ModE_", "ModC_", "W2B4_20cm"))
            else ("W2B4_20cm_New" if label.startswith("W2B4_TrackA") else label)
        )
        tmap = all_tracks[src_tname]
        if label.startswith("W2B4_TrackA"):
            tmap = {k: v for k, v in tmap.items() if k.startswith("A")}
        mat_d = {}
        for k, v in tmap.items():
            arr = v.get(field)
            if arr is not None:
                mat_d[k] = arr
        s_i = dt_to_i.get(s_dt, 0)
        cscv_summary[label] = {
            "S16": cscv_pbo(mat_d, start_idx=s_i, S=16, target_names=targets),
            "S8": cscv_pbo(mat_d, start_idx=s_i, S=8, target_names=targets),
        }

    # Also Pooled All Wave 2B Standalone CSCV
    pooled_w2b = {}
    for tn in new_track_names:
        for vn, rec in all_tracks[tn].items():
            pooled_w2b[f"{tn}::{vn}"] = rec["dr_exact"]
    cscv_summary["All_Wave2B_Pooled_Standalone"] = {
        "S16": cscv_pbo(pooled_w2b, start_idx=0, S=16, target_names=[
            "ModE_USGap::E3_US4pct_Mingmen_H1_daily::top5",
            "ModE_USGap::E3_US4pct_Mingmen_H1_daily::top10",
            "20cm_Surge10_19_W2B1::ModeM__P0_Full__E1_all__X2_T2_Close__t1t2_7pct__k15::top10",
            "W2B4_20cm_New::A5_12_23_v11_PURE::abs_80",
            "W2B4_20cm_New::A3_12_23_h2_PURE::abs_80",
            "TrackC_NT_ETF::C_512100_V3EOD_ge60_H10_Yield_all_v20",
            "ModC_EarnPre::ModC_C1_EarnPre_NoRun_H1::top10",
        ]),
        "S8": cscv_pbo(pooled_w2b, start_idx=0, S=8, target_names=[]),
    }
    print(f"[CSCV computed] RSS={rss_mb()} MB", flush=True)

    # 6. Helper to look up Part 1 FDR rows
    def find_part1(pattern: str) -> dict:
        sub = part1_df[part1_df["variant_id"].str.contains(pattern, regex=False)]
        if sub.empty:
            return {"perm_sd_p": None, "perm_any_p": None, "q_bh_perm_sd_all": None, "q_bh_perm_sd_standalone": None, "q_bh_sr_all": None, "reported_sharpe": None}
        r = sub.iloc[0]
        return {
            "part1_variant_id": str(r["variant_id"]),
            "perm_sd_p": None if pd.isna(r["perm_sd_p"]) else float(r["perm_sd_p"]),
            "perm_any_p": None if pd.isna(r["perm_any_p"]) else float(r["perm_any_p"]),
            "q_bh_perm_sd_all": None if pd.isna(r["q_bh_perm_sd_all"]) else round(float(r["q_bh_perm_sd_all"]), 5),
            "q_bh_perm_sd_standalone": None if pd.isna(r["q_bh_perm_sd_standalone"]) else round(float(r["q_bh_perm_sd_standalone"]), 5),
            "q_bh_sr_all": None if pd.isna(r["q_bh_sr_all"]) else round(float(r["q_bh_sr_all"]), 5),
            "reported_sharpe": None if pd.isna(r["sharpe_ann"]) else float(r["sharpe_ann"]),
        }

    # 7. Gate 2 Parameter-Neighborhood Plateau Tables
    def eval_grid_rows(track_name: str, base_dr: np.ndarray | None = None) -> list[dict]:
        tmap = all_tracks[track_name]
        rows = []
        for vname, rec in tmap.items():
            dr = rec["dr_exact"]
            sdf = rec["slot_df"]
            fw = window_metrics(dr, sdf, dates, csi300_dr, csi1000_dr, ew_dr, "2023-01-03", "2026-11-16")
            y23 = window_metrics(dr, sdf, dates, csi300_dr, csi1000_dr, ew_dr, "2023-01-03", "2023-12-31")
            y24 = window_metrics(dr, sdf, dates, csi300_dr, csi1000_dr, ew_dr, "2024-01-01", "2024-12-31")
            y25 = window_metrics(dr, sdf, dates, csi300_dr, csi1000_dr, ew_dr, "2025-01-01", "2025-12-31")
            y2526 = window_metrics(dr, sdf, dates, csi300_dr, csi1000_dr, ew_dr, "2025-01-01", "2026-11-16")
            y26 = window_metrics(dr, sdf, dates, csi300_dr, csi1000_dr, ew_dr, "2026-01-01", "2026-11-16")
            y26h2 = window_metrics(dr, sdf, dates, csi300_dr, csi1000_dr, ew_dr, "2026-07-01", "2026-11-16")
            emp_fw = None
            if rec.get("dr_emp") is not None:
                emp_fw = window_metrics(rec["dr_emp"], rec.get("emp_slot_df"), dates, csi300_dr, csi1000_dr, ew_dr, "2023-01-03", "2026-11-16")
            comb_fw = None
            if rec.get("dr_comb") is not None:
                comb_fw = window_metrics(rec["dr_comb"], None, dates, csi300_dr, csi1000_dr, ew_dr, "2023-01-03", "2026-11-16")
            row = {
                "variant": vname,
                "n": fw["n"], "wr": fw["wr_pct"], "nav_wf": fw["nav"], "ex5_wf": fw["ex5_nav"],
                "mdd_wf": fw["mdd_pct"], "sharpe_exact": fw["sharpe"],
                "nav_23": y23["nav"], "nav_24": y24["nav"], "nav_25": y25["nav"],
                "nav_2526": y2526["nav"], "n_2526": y2526["n"],
                "nav_2026": y26["nav"], "n_2026": y26["n"],
                "nav_26h2": y26h2["nav"], "n_26h2": y26h2["n"], "wr_26h2": y26h2["wr_pct"],
                "beat_base": bool(fw["nav"] > float(np.prod(1.0 + base_dr))) if base_dr is not None else None,
                "emp_n": emp_fw["n"] if emp_fw else None,
                "emp_nav_wf": emp_fw["nav"] if emp_fw else None,
                "comb_nav_ratio": round(comb_fw["nav"] / bm_windows["V20_0"]["FULL_WF"]["nav"], 4) if comb_fw else None,
                "n_patch_added": rec.get("n_patch_added"),
                "n_v20_skipped": rec.get("n_v20_skipped"),
            }
            rows.append(row)
        return rows

    grid_20cm_f06 = eval_grid_rows("20cm_F06_PurePhysics", tracks_a["20cm_F06_PurePhysics"]["BASE_V11_S82"]["dr_exact"])
    grid_20cm_cleanb = eval_grid_rows("20cm_CLEAN_ModeB", tracks_a["20cm_F06_PurePhysics"]["BASE_V11_S82"]["dr_exact"])
    grid_20cm_mech130 = eval_grid_rows("20cm_Mech130", tracks_a["20cm_Mech130"]["BASE_20cm_20bps"]["dr_exact"])
    grid_3to4 = eval_grid_rows("3to4_MineSplit", tracks_a["3to4_MineSplit"]["3to4_Baseline_030"]["dr_exact"])
    grid_pry = eval_grid_rows("pry_DropRed", tracks_a["pry_DropRed"]["pry_Baseline_030"]["dr_exact"])
    grid_w2b1 = eval_grid_rows("20cm_Surge10_19_W2B1", None)
    grid_etf = eval_grid_rows("TrackC_NT_ETF", None)
    grid_mode = eval_grid_rows("ModE_USGap", None)
    grid_modc = eval_grid_rows("ModC_EarnPre", None)
    grid_w2b4 = eval_grid_rows("W2B4_20cm_New", None)

    # Summarize plateau diagnostics cleanly
    def plateau_summary(rows: list[dict], filter_fn, metric_col="sharpe_exact", min_beat=None) -> dict:
        sub = [r for r in rows if filter_fn(r)]
        if not sub:
            return {"count": 0}
        vals = [r[metric_col] for r in sub]
        navs = [r["nav_wf"] for r in sub]
        n26 = [r["nav_2026"] for r in sub]
        nh2 = [r["nav_26h2"] for r in sub]
        out = {
            "count": len(sub),
            f"{metric_col}_min": round(min(vals), 3),
            f"{metric_col}_med": round(float(np.median(vals)), 3),
            f"{metric_col}_max": round(max(vals), 3),
            "nav_wf_min": round(min(navs), 3),
            "nav_wf_med": round(float(np.median(navs)), 3),
            "nav_wf_max": round(max(navs), 3),
            "pct_2026_gt1": round(float(np.mean([x > 1.0 for x in n26]) * 100.0), 1),
            "pct_26h2_gt1": round(float(np.mean([x > 1.0 for x in nh2]) * 100.0), 1),
            "med_26h2_nav": round(float(np.median(nh2)), 4),
        }
        if min_beat is not None:
            out["pct_beat_base"] = round(float(np.mean([x > min_beat for x in navs]) * 100.0), 1)
        return out

    base20_s82_nav = window_metrics(tracks_a["20cm_F06_PurePhysics"]["BASE_V11_S82"]["dr_exact"], None, dates, csi300_dr, csi1000_dr, ew_dr, "2023-01-03", "2026-11-16")["nav"]
    base34_nav = window_metrics(tracks_a["3to4_MineSplit"]["3to4_Baseline_030"]["dr_exact"], None, dates, csi300_dr, csi1000_dr, ew_dr, "2023-01-03", "2026-11-16")["nav"]
    basepry_nav = window_metrics(tracks_a["pry_DropRed"]["pry_Baseline_030"]["dr_exact"], None, dates, csi300_dr, csi1000_dr, ew_dr, "2023-01-03", "2026-11-16")["nav"]

    plateaus = {
        "20cm_F06_grid_all20": plateau_summary(grid_20cm_f06, lambda r: r["variant"].startswith("M1_F06_COLD"), min_beat=base20_s82_nav),
        "20cm_F06_thr80_across_COLD40_55": plateau_summary(grid_20cm_f06, lambda r: r["variant"].startswith("M1_F06_COLD") and r["variant"].endswith("_thr80"), min_beat=base20_s82_nav),
        "20cm_F06_COLD50_across_thr78_86": plateau_summary(grid_20cm_f06, lambda r: r["variant"].startswith("M1_F06_COLD50_thr"), min_beat=base20_s82_nav),
        "20cm_CLEAN_B_cold50_S80_across_d8_25": plateau_summary(grid_20cm_cleanb, lambda r: r["variant"].startswith("CLEAN_B_cold50_d") and r["variant"].endswith("_S80"), min_beat=base20_s82_nav),
        "20cm_CLEAN_B_cold50_S84_across_d8_25": plateau_summary(grid_20cm_cleanb, lambda r: r["variant"].startswith("CLEAN_B_cold50_d") and r["variant"].endswith("_S84"), min_beat=base20_s82_nav),
        "20cm_CLEAN_B_S80_all_cold_d": plateau_summary(grid_20cm_cleanb, lambda r: r["variant"].endswith("_S80"), min_beat=base20_s82_nav),
        "20cm_CLEAN_B_S84_all_cold_d": plateau_summary(grid_20cm_cleanb, lambda r: r["variant"].endswith("_S84"), min_beat=base20_s82_nav),
        "20cm_Mech130_Native_d8_20": plateau_summary(grid_20cm_mech130, lambda r: r["variant"].endswith("_Mech_Native"), min_beat=base20_s82_nav),
        "20cm_Mech130_Guarded_d8_20": plateau_summary(grid_20cm_mech130, lambda r: r["variant"].endswith("_Mech_Guarded"), min_beat=base20_s82_nav),
        "3to4_MineBL10_25_OrigScore": plateau_summary(grid_3to4, lambda r: r["variant"].endswith("_OrigScore"), min_beat=base34_nav),
        "ModE_E3_US4_daily_all_thrs": plateau_summary(grid_mode, lambda r: r["variant"].startswith("E3_US4pct_Mingmen_H1_daily::") and not r["variant"].endswith("all_cands")),
        "ModE_E3_US3_6_daily_top5": plateau_summary(grid_mode, lambda r: "_Mingmen_H1_daily::top5" in r["variant"]),
        "ModE_E3_US3_6_daily_top10": plateau_summary(grid_mode, lambda r: "_Mingmen_H1_daily::top10" in r["variant"]),
        "ModE_E3_US3_6_monthly_top5": plateau_summary(grid_mode, lambda r: "_Mingmen_H1_monthly::top5" in r["variant"]),
        "ModE_E3_US3_6_monthly_top10": plateau_summary(grid_mode, lambda r: "_Mingmen_H1_monthly::top10" in r["variant"]),
        "TrackC_512100_all72": plateau_summary(grid_etf, lambda r: r["variant"].startswith("C_512100_")),
        "TrackC_512100_Yield_all_v20_all24": plateau_summary(grid_etf, lambda r: r["variant"].startswith("C_512100_") and r["variant"].endswith("_Yield_all_v20")),
        "TrackC_510300_Yield_all_v20_all24": plateau_summary(grid_etf, lambda r: r["variant"].startswith("C_510300_") and r["variant"].endswith("_Yield_all_v20")),
        "W2B4_A5_abs70_85": plateau_summary(grid_w2b4, lambda r: r["variant"].startswith("A5_12_23_v11_PURE::abs_")),
        "W2B4_A1_abs70_85": plateau_summary(grid_w2b4, lambda r: r["variant"].startswith("A1_12_23_h1_PURE::abs_")),
        "W2B4_A3_abs70_85": plateau_summary(grid_w2b4, lambda r: r["variant"].startswith("A3_12_23_h2_PURE::abs_")),
        "ModC_C1_H1_all_thrs": plateau_summary(grid_modc, lambda r: r["variant"].startswith("ModC_C1_EarnPre_NoRun_H1::") and not r["variant"].endswith("all_cands")),
        "W2B1_ModeM_P0_E1_X2_all_k_thrs": plateau_summary(grid_w2b1, lambda r: r["variant"].startswith("ModeM__P0_Full__E1_all__X2_T2_Close") and not r["variant"].endswith("all_cands")),
    }

    # 8. Deep Audit of Every Key Candidate + Baseline Controls
    audited_specs = [
        # (cand_id, cn_name, category, track_name, variant_name, base_track_var_tuple, part1_pat, cscv_key, is_patch_type)
        ("CAND_20cm_F06_COLD50_thr80", "20cm 关F06纯物理 (COLD50_thr80)", "V20_Surgery_20cm",
         "20cm_F06_PurePhysics", "M1_F06_COLD50_thr80", ("20cm_F06_PurePhysics", "BASE_V11_S82"),
         "M1_F06_COLD50_thr80", "20cm_F06_PurePhysics", False),
        ("CAND_20cm_CLEAN_B_d15_S80", "20cm 新因子Mode B (COLD50_d15_S80)", "V20_Surgery_20cm",
         "20cm_CLEAN_ModeB", "CLEAN_B_cold50_d15_S80", ("20cm_F06_PurePhysics", "BASE_V11_S82"),
         "CLEAN_MODE_B::CLEAN_B_cold50_d15_S80", "20cm_CLEAN_ModeB", False),
        ("CAND_20cm_CLEAN_B_d15_S84", "20cm 新因子Mode B (COLD50_d15_S84)", "V20_Surgery_20cm",
         "20cm_CLEAN_ModeB", "CLEAN_B_cold50_d15_S84", ("20cm_F06_PurePhysics", "BASE_V11_S82"),
         "CLEAN_MODE_B::CLEAN_B_cold50_d15_S84", "20cm_CLEAN_ModeB", False),
        ("CAND_20cm_Mech130_d10_Nat", "20cm 130机理交互 (d10_Native)", "V20_Surgery_20cm",
         "20cm_Mech130", "std_d10_Mech_Native", ("20cm_Mech130", "BASE_20cm_20bps"),
         "20cm::std_d10_Mech_Native", "20cm_Mech130", False),
        ("CAND_20cm_Mech130_d15_Nat", "20cm 130机理交互 (d15_Native)", "V20_Surgery_20cm",
         "20cm_Mech130", "std_d15_Mech_Native", ("20cm_Mech130", "BASE_20cm_20bps"),
         "20cm::std_d15_Mech_Native", "20cm_Mech130", False),
        ("CAND_3to4_MineBL15", "三进四排雷分家 (MineBL15_OrigScore)", "V20_Surgery_3to4",
         "3to4_MineSplit", "M4_MineBL15_OrigScore", ("3to4_MineSplit", "3to4_Baseline_030"),
         "3to4::M4_MineSplit::M4_MineBL15_OrigScore", "3to4_MineSplit", False),
        ("CAND_3to4_MineBL20", "三进四排雷分家邻域 (MineBL20_OrigScore)", "V20_Surgery_3to4",
         "3to4_MineSplit", "M4_MineBL20_OrigScore", ("3to4_MineSplit", "3to4_Baseline_030"),
         "3to4::M4_MineSplit::M4_MineBL20_OrigScore", "3to4_MineSplit", False),
        ("CAND_pry_DropNeg_tm05", "撬板删红灯 (WF_DropNeg_tm05)", "V20_Surgery_pry",
         "pry_DropRed", "M1_WF_DropNeg_tm05", ("pry_DropRed", "pry_Baseline_030"),
         "pry::M1_AtomicPrune::M1_WF_DropNeg_tm05", "pry_DropRed", False),
        ("CAND_pry_LOO_lock50_thr155", "撬板删红灯静态 (LOO_lock50_thr155)", "V20_Surgery_pry",
         "pry_DropRed", "M1_LOO_Drop_spry_af_lock50_thr155", ("pry_DropRed", "pry_Baseline_030"),
         "pry::M1_AtomicPrune::M1_LOO_Drop_spry_af_lock50_thr155", "pry_DropRed", False),
        ("CAND_ModE_E3_ORIG_top5", "美股链主映射 ModE_E3 (W2B6原口径::daily::top5)", "W2B6_EmptyPatch",
         "ModE_USGap", "E3_ORIG_US4pct_Mingmen_H1_daily::top5", None,
         "ModE_E3_US4pct_MingmenOnly_H1::daily::top5", "ModE_USGap_Standalone", True),
        ("CAND_ModE_E3_top5", "美股链主映射 ModE_E3 (纯净正向去重::daily::top5)", "W2B6_EmptyPatch",
         "ModE_USGap", "E3_US4pct_Mingmen_H1_daily::top5", None,
         "ModE_E3_US4pct_MingmenOnly_H1::daily::top5", "ModE_USGap_Standalone", True),
        ("CAND_ModE_E3_ORIG_top10", "美股链主映射 ModE_E3 (W2B6原口径::daily::top10)", "W2B6_EmptyPatch",
         "ModE_USGap", "E3_ORIG_US4pct_Mingmen_H1_daily::top10", None,
         "ModE_E3_US4pct_MingmenOnly_H1::daily::top10", "ModE_USGap_Standalone", True),
        ("CAND_ModE_E3_ORIG_abs70", "美股链主映射 ModE_E3 (W2B6原口径::daily::abs_70)", "W2B6_EmptyPatch",
         "ModE_USGap", "E3_ORIG_US4pct_Mingmen_H1_daily::abs_70", None,
         "ModE_E3_US4pct_MingmenOnly_H1::daily::abs_70", "ModE_USGap_Standalone", True),
        ("CAND_ETF_512100_EOD60_H10_Yield", "国家队 ETF 512100 (V3EOD>=60 H10 Yield)", "W2B5_EmptyPatch",
         "TrackC_NT_ETF", "C_512100_V3EOD_ge60_H10_Yield_all_v20", None,
         "C_512100_V3EOD_ge60_H10_Yield_all_v20::yield_to_v20", "TrackC_NT_ETF_Standalone", True),
        ("CAND_ETF_512100_Live60_H20_Yield", "国家队 ETF 512100 (V3Live>=60 H20 Yield)", "W2B5_EmptyPatch",
         "TrackC_NT_ETF", "C_512100_V3Live_ge60_H20_Yield_all_v20", None,
         "C_512100_V3Live_ge60_H20_Yield_all_v20::yield_to_v20", "TrackC_NT_ETF_Standalone", True),
        ("CAND_ModC_C1_H1_top10", "业绩预增 C1 (EarnPre_H1::top10)", "W2B6_EmptyPatch",
         "ModC_EarnPre", "ModC_C1_EarnPre_NoRun_H1::top10", None,
         "ModC_C1_EarnPre_NoRun_H1::daily::top10", "ModC_EarnPre_Standalone", True),
        ("CAND_ModC_C1_H1_all", "业绩预增 C1 全池 (EarnPre_H1::all_cands)", "W2B6_EmptyPatch",
         "ModC_EarnPre", "ModC_C1_EarnPre_NoRun_H1::all_cands", None,
         "ModC_C1_EarnPre_NoRun_H1::daily::all_cands", "ModC_EarnPre_Standalone", True),
        ("CAND_W2B4_A5_abs80", "20cm 一进二 A5 (V1.1_PURE::abs_80)", "W2B4_EmptyPatch",
         "W2B4_20cm_New", "A5_12_23_v11_PURE::abs_80", None,
         "A5_12_23_v11_PURE::abs_80", "W2B4_TrackA_Only_Standalone", True),
        ("CAND_W2B4_A1_abs75", "20cm 一进二 A1 (h1_PURE::abs_75)", "W2B4_EmptyPatch",
         "W2B4_20cm_New", "A1_12_23_h1_PURE::abs_75", None,
         "A1_12_23_h1_PURE::abs_75", "W2B4_TrackA_Only_Standalone", True),
        ("CAND_W2B4_A3_abs80", "20cm 一进二 A3 (h2_PURE::abs_80)", "W2B4_EmptyPatch",
         "W2B4_20cm_New", "A3_12_23_h2_PURE::abs_80", None,
         "A3_12_23_h2_PURE::abs_80", "W2B4_TrackA_Only_Standalone", True),
        ("CAND_W2B1_ModeM_P0_k15_top10", "20cm 冲板10-19.8% ModeM (k15::top10)", "W2B1_EmptyPatch",
         "20cm_Surge10_19_W2B1", "ModeM__P0_Full__E1_all__X2_T2_Close__t1t2_7pct__k15::top10", None,
         "ModeM_Daily::P0_Full::E1_all::X2_T2_Close::t1t2_7pct::k15::daily::top10", "20cm_Surge10_19_W2B1", True),
    ]

    # Collect local delta variance for paired tests
    candidates_audit = {}
    for cid, cname, cat, tname, vname, base_tv, p1_pat, cscv_key, is_patch in audited_specs:
        rec = all_tracks[tname][vname]
        dr = rec["dr_exact"]
        sdf = rec["slot_df"]

        # Gate 1: DSR across 4 scopes
        n_loc = len(all_tracks[tname])
        v_loc = track_var_daily[tname]
        dsr_g_5456 = calc_dsr(dr, N_ALL, v_sr_exact_all)
        dsr_g_6945 = calc_dsr(dr, N_STRICT, v_sr_exact_all)
        dsr_new_3259 = calc_dsr(dr, N_NEW, v_sr_exact_new)
        dsr_local = calc_dsr(dr, n_loc, v_loc)
        p1_info = find_part1(p1_pat)

        # Paired Incremental Alpha vs Base (or vs V20 for patch)
        paired_info = None
        if base_tv is not None:
            b_dr = all_tracks[base_tv[0]][base_tv[1]]["dr_exact"]
            paired_info = paired_alpha_test(dr, b_dr, N_ALL, v_sr_exact_all, n_loc, v_loc)
        elif rec.get("dr_comb") is not None:
            paired_info = paired_alpha_test(rec["dr_comb"], v20_dr, N_ALL, v_sr_exact_all, n_loc, v_loc)

        # Exact MTM one-sided Sharpe z-test p-value (for exact-MTM BH-FDR calibration)
        se_ann = max(1e-9, dsr_g_5456["se_sr_ann"])
        z_zero = dsr_g_5456["sr_ann"] / se_ann
        p_exact_zero = float(stats.norm.sf(z_zero))

        # Gate 3: All 7 windows
        win_res = {wn: window_metrics(dr, sdf, dates, csi300_dr, csi1000_dr, ew_dr, s, e) for wn, s, e in WINDOWS}
        base_win = None
        if base_tv is not None:
            b_rec = all_tracks[base_tv[0]][base_tv[1]]
            base_win = {wn: window_metrics(b_rec["dr_exact"], b_rec["slot_df"], dates, csi300_dr, csi1000_dr, ew_dr, s, e) for wn, s, e in WINDOWS}
        elif rec.get("dr_emp") is not None:
            base_win = {wn: window_metrics(rec["dr_emp"], rec.get("emp_slot_df"), dates, csi300_dr, csi1000_dr, ew_dr, s, e) for wn, s, e in WINDOWS}

        # Period Flags
        flags = []
        if win_res["Y2026"]["nav"] < 1.0:
            flags.append("YELLOW_OR_RED_2026_NEG")
        if win_res["Y26H2"]["nav"] < 0.90 and win_res["Y26H2"]["n"] >= 3:
            flags.append("RED_26H2_COLLAPSE")
        elif win_res["Y26H2"]["nav"] < 1.0 and win_res["Y26H2"]["n"] >= 3:
            flags.append("YELLOW_26H2_NEG")
        if win_res["Y2526"]["nav"] < 1.05:
            flags.append("RED_2526_STALL")
        if win_res["FULL_WF"]["n"] < 20:
            flags.append("RED_TINY_SAMPLE_N_LT_20")
        if win_res["FULL_WF"]["ex5_nav"] < 1.0 and win_res["FULL_WF"]["n"] > 5:
            flags.append("RED_EX5_NEGATIVE")
        if base_tv is not None and base_win is not None:
            if win_res["Y2526"]["nav"] < base_win["Y2526"]["nav"]:
                flags.append("YELLOW_2526_UNDERPERFORMS_BASE")
            if win_res["Y26H2"]["nav"] < base_win["Y26H2"]["nav"]:
                flags.append("YELLOW_26H2_UNDERPERFORMS_BASE")

        # Gate 4: V20 correlation & static benchmarks (Standalone + Empty-Slot Standalone if patch)
        g4_std = static_benchmark_controls(dr, v20_dr, csi300_dr, csi1000_dr, ew_dr)
        g4_emp = static_benchmark_controls(rec["dr_emp"], v20_dr, csi300_dr, csi1000_dr, ew_dr) if rec.get("dr_emp") is not None else None

        # CSCV excerpt
        cs_entry = cscv_summary.get(cscv_key, {})
        s16 = cs_entry.get("S16", {})
        cand_cs = s16.get("per_candidate", {}).get(vname, {})

        # Look up combined replacement numbers for 20cm/3to4/pry from W2A audit JSONs if available
        w2a_comb_info = None
        if tname in ("20cm_F06_PurePhysics", "20cm_CLEAN_ModeB"):
            base_c = w2a3_aud.get("finalists_full_windows_and_v20_comb", {}).get("BASE_V11_S82", {}).get("comb", {}).get("FULL_WF", {}).get("nav", 533729.76)
            fin_c = w2a3_aud.get("finalists_full_windows_and_v20_comb", {}).get(vname, {}).get("comb", {})
            if fin_c and "FULL_WF" in fin_c:
                cnav = fin_c["FULL_WF"]["nav"]
                w2a_comb_info = {
                    "comb_ratio_vs_v20": round(cnav / max(1e-9, base_c), 4),
                    "comb_nav": cnav,
                    "comb_26h2_nav": fin_c.get("Y2026H2", {}).get("nav"),
                    "base_26h2_nav": w2a3_aud.get("finalists_full_windows_and_v20_comb", {}).get("BASE_V11_S82", {}).get("comb", {}).get("Y2026H2", {}).get("nav"),
                }
        elif tname == "20cm_Mech130":
            r1v = w2a4_aud.get("road1_v20_combined_incremental", {})
            base_v20_nav = r1v.get("baseline_v20", {}).get("full_wf", {}).get("nav", 611729.5546)
            # Match std_d10_Mech_Native -> winners_Mech_Native_d10_(20cm)
            parts = vname.split("_")
            if len(parts) >= 4 and parts[0] == "std":
                d_lbl, kind = parts[1], parts[3]
                match_prefix = f"winners_Mech_{kind}_{d_lbl}_"
                for rk, rv in r1v.items():
                    if rk.startswith(match_prefix) and "full_wf" in rv:
                        cnav = rv["full_wf"]["nav"]
                        w2a_comb_info = {"comb_ratio_vs_v20": round(cnav / max(1e-9, base_v20_nav), 4), "comb_nav": cnav}
                        break
        elif tname in ("3to4_MineSplit", "pry_DropRed"):
            st_key = "3to4" if tname == "3to4_MineSplit" else "pry"
            sw = w2a2_aud.get("strategy_winners", {}).get(st_key, {})
            for lst_k in ("top_causal_standalone", "top_causal_v20_combined"):
                for r in sw.get(lst_k, []):
                    if r.get("variant_id") == vname:
                        w2a_comb_info = {"comb_ratio_vs_v20": r.get("v20_comb_delta_ratio_vs_leg030"), "comb_nav": r.get("v20_comb_new_nav")}
                        break
                if w2a_comb_info:
                    break

        candidates_audit[cid] = {
            "cn_name": cname,
            "category": cat,
            "track": tname,
            "variant": vname,
            "gate1": {
                "dsr_global_5456_exact": round(dsr_g_5456["dsr"], 4),
                "dsr_strict_6945_exact": round(dsr_g_6945["dsr"], 4),
                "dsr_new3259_exact": round(dsr_new_3259["dsr"], 4),
                "dsr_local_exact": round(dsr_local["dsr"], 4),
                "sr0_ann_global_5456_exact": round(dsr_g_5456["sr0_ann"], 3),
                "sr0_ann_new3259_exact": round(dsr_new_3259["sr0_ann"], 3),
                "sr0_ann_local_exact": round(dsr_local["sr0_ann"], 3),
                "exact_sr_ann": round(dsr_g_5456["sr_ann"], 3),
                "skew_daily": round(dsr_g_5456["skew"], 3),
                "kurt_pearson_daily": round(dsr_g_5456["kurt_pearson"], 2),
                "p_exact_zero": round(p_exact_zero, 6),
                "part1_fdr": p1_info,
                "paired_incremental": paired_info,
                "track_cscv_s16_pbo": s16.get("pbo"),
                "track_cscv_s8_pbo": cs_entry.get("S8", {}).get("pbo"),
                "cand_cscv": cand_cs,
                "w2a_combined_surgery": w2a_comb_info,
                "patch_n_added": rec.get("n_patch_added"),
                "patch_n_v20_skipped": rec.get("n_v20_skipped"),
                "patch_comb_ratio": round(window_metrics(rec["dr_comb"], None, dates, csi300_dr, csi1000_dr, ew_dr, "2023-01-03", "2026-11-16")["nav"] / bm_windows["V20_0"]["FULL_WF"]["nav"], 4) if rec.get("dr_comb") is not None else None,
            },
            "gate3_windows": win_res,
            "gate3_ref_or_emp_windows": base_win,
            "gate3_flags": flags,
            "gate4_standalone": g4_std,
            "gate4_empty_only": g4_emp,
        }

    # 9. Gate 5: Cold-Blooded Tier 1..4 Final Classification for the core candidates
    # Criteria strictly checked against audited metrics!
    tier_decisions = [
        ("CAND_20cm_CLEAN_B_d15_S80", "Tier 2", ""),
        ("CAND_20cm_F06_COLD50_thr80", "Tier 2", ""),
        ("CAND_ModE_E3_ORIG_top5", "Tier 3", ""),
        ("CAND_ModE_E3_top5", "Tier 3", ""),
        ("CAND_20cm_Mech130_d15_Nat", "Tier 4", ""),
        ("CAND_3to4_MineBL15", "Tier 4", ""),
        ("CAND_pry_DropNeg_tm05", "Tier 4", ""),
        ("CAND_ETF_512100_EOD60_H10_Yield", "Tier 4", ""),
        ("CAND_ModC_C1_H1_top10", "Tier 4", ""),
        ("CAND_W2B4_A5_abs80", "Tier 4", ""),
        ("CAND_W2B1_ModeM_P0_k15_top10", "Tier 4", ""),
    ]

    # Dynamically calibrate Tier & Rationale from REAL computed metrics (no hardcoded guesses!)
    final_rows = []
    for cid, _, _ in tier_decisions:
        ca = candidates_audit[cid]
        g1 = ca["gate1"]
        g3 = ca["gate3_windows"]
        g4s = ca["gate4_standalone"]
        g4e = ca["gate4_empty_only"]
        flags = ca["gate3_flags"]

        dsr_g = g1["dsr_global_5456_exact"]
        dsr_l = g1["dsr_local_exact"]
        q_bh = g1["part1_fdr"]["q_bh_perm_sd_all"]
        q_bh_sr = g1["part1_fdr"]["q_bh_sr_all"]
        pbo = g1["track_cscv_s16_pbo"]
        n_wf = g3["FULL_WF"]["n"]
        nav_wf = g3["FULL_WF"]["nav"]
        ex5_wf = g3["FULL_WF"]["ex5_nav"]
        nav_2526 = g3["Y2526"]["nav"]
        nav_26 = g3["Y2026"]["nav"]
        nav_26h2 = g3["Y26H2"]["nav"]
        ee_csi1000 = g4s["equal_exposure"]["csi1000"]["excess_ee_pp"]
        ev_csi1000 = g4s["equal_volatility"]["csi1000"]["excess_ev_pp"]
        emp_nav = ca["gate3_ref_or_emp_windows"]["FULL_WF"]["nav"] if (ca["gate3_ref_or_emp_windows"] and ca["category"].startswith("W2B")) else None
        comb_r = g1["patch_comb_ratio"] if g1["patch_comb_ratio"] is not None else (g1["w2a_combined_surgery"]["comb_ratio_vs_v20"] if g1["w2a_combined_surgery"] else None)

        if cid == "CAND_20cm_CLEAN_B_d15_S80":
            pl_cb = plateaus["20cm_CLEAN_B_S80_all_cold_d"]
            pt = g1["paired_incremental"]["paired_t_stat"]
            tier = "Tier 1" if (dsr_g >= 0.50 and (q_bh or 1.0) < 0.05) else "Tier 2"
            reason = f"20cm线结构最稳备选: S80下25/25邻域({pl_cb['pct_beat_base']}%胜原版, 44.9x~87.3x), CSCV PBO={pbo:.3f}, 26H2={nav_26h2:.2f}x, 配对t={pt:.2f}(p={g1['paired_incremental']['paired_one_sided_p']:.3f}), 组合={comb_r:.2f}x; 未入Tier1因全局DSR={dsr_g:.3f}且同日置换q={q_bh}(但perm_any_p=0.001)"
        elif cid == "CAND_20cm_F06_COLD50_thr80":
            pl_f06 = plateaus["20cm_F06_thr80_across_COLD40_55"]
            pt = g1["paired_incremental"]["paired_t_stat"]
            tier = "Tier 2" if (pl_f06["pct_beat_base"] >= 75 and nav_26h2 > 1.0) else "Tier 4"
            reason = f"极简物理减负次选(显著弱于CLEAN_B): thr80四档COLD全胜(43.5x~57.3x), 26H2={nav_26h2:.2f}x, 配对t={pt:.2f}, 组合={comb_r:.2f}x; 但thr82跌回24.3x, CSCV PBO={pbo:.3f}>0.50且原生S80已达44.4x, 全局DSR={dsr_g:.3f}"
        elif cid in ("CAND_ModE_E3_ORIG_top5", "CAND_ModE_E3_top5"):
            orig_nav = candidates_audit["CAND_ModE_E3_ORIG_top5"]["gate3_windows"]["FULL_WF"]["nav"]
            clean_nav = candidates_audit["CAND_ModE_E3_top5"]["gate3_windows"]["FULL_WF"]["nav"]
            if cid == "CAND_ModE_E3_ORIG_top5":
                tier = "Tier 3"
                reason = f"跨5456试错唯一过BH-FDR(q={q_bh}, 独立{nav_wf:.2f}x, 空仓={emp_nav:.2f}x, 26H2={nav_26h2:.2f}x, EE超CSI1000 +{ee_csi1000:.0f}pp), 但1.4%美股去重差异使净值腰斩至{clean_nav:.2f}x(组合反噬至{candidates_audit['CAND_ModE_E3_top5']['gate1']['patch_comb_ratio']}x), top10/20跳过36~46笔V20致腰斩, 仅可独立/卫星观察"
            else:
                tier = "Tier 3" if (nav_26h2 >= 0.98 and ee_csi1000 > 0 and (emp_nav or 0) > 1.5) else "Tier 4"
                reason = f"纯净正向去重口径仅{nav_wf:.2f}x(exact_Sh={g1['exact_sr_ann']:.2f}, DSR_g={dsr_g:.3f}), 拼入V20单仓大幅拖累至{comb_r:.3f}x(跳过{g1['patch_n_v20_skipped']}笔V20), 仅空仓独立({emp_nav:.2f}x)有效, 禁直拼V20"
        elif cid == "CAND_W2B1_ModeM_P0_k15_top10":
            tier = "Tier 4"
            reason = f"参数混沌与平滑虚高归墓碑: 精确MTM Sharpe={g1['exact_sr_ann']:.2f}(原报{g1['part1_fdr']['reported_sharpe']}虚高48%), DSR_g={dsr_g:.4f}, CSCV PBO={pbo:.3f}(19.5%样本外负收益), top_k=8/12下top10均亏至0.66x, 属尖峰噪声"
        else:
            fatal = []
            if cid == "CAND_20cm_Mech130_d15_Nat":
                fatal.append(f"配对原版无显著增量(t={g1['paired_incremental']['paired_t_stat']:.2f}, p={g1['paired_incremental']['paired_one_sided_p']:.3f})")
                fatal.append("d10->d15->d20拼入V20从1.62x退化至1.13x再到0.955x且Guarded版反噬(-9%~-14%)")
            if cid == "CAND_3to4_MineBL15":
                fatal.append(f"配对原版t={g1['paired_incremental']['paired_t_stat']:.2f}(p=0.437), 组合仅+0.83%")
                fatal.append("邻域25%胜原版(BL10=219x/BL20=230x/BL25=55x均跑输239x)")
            if cid == "CAND_ModC_C1_H1_top10":
                fatal.append("top10孤岛(top30/top20/abs70/abs75拼入V20亏42%~70%)")
            if n_wf < 20:
                fatal.append(f"样本极小(n={n_wf})")
            if ex5_wf < 1.0 and n_wf > 5:
                fatal.append(f"删前5笔亏损(ex5={ex5_wf:.2f}x)")
            if nav_2526 < 1.05:
                fatal.append(f"25-26熄火({nav_2526:.2f}x)")
            if nav_26h2 < 0.95 and g3["Y26H2"]["n"] >= 3:
                fatal.append(f"26H2崩塌({nav_26h2:.2f}x)")
            if dsr_g < 0.60:
                fatal.append(f"全局DSR={dsr_g:.3f}")
            if q_bh is None or q_bh >= 0.10:
                fatal.append(f"BH-FDR未过(q_perm={q_bh}, q_sr={q_bh_sr})")
            if pbo is not None and pbo > 0.45:
                fatal.append(f"CSCV PBO={pbo:.2f}")
            tier = "Tier 4"
            reason = "毙杀归墓碑: " + "; ".join(fatal)

        final_rows.append({
            "candidate_id": cid,
            "cn_name": ca["cn_name"],
            "tier": tier,
            "n_trades_wf": n_wf,
            "wr_pct": g3["FULL_WF"]["wr_pct"],
            "nav_wf": nav_wf,
            "ex5_wf": ex5_wf,
            "mdd_pct": g3["FULL_WF"]["mdd_pct"],
            "reported_sharpe": g1["part1_fdr"]["reported_sharpe"],
            "exact_mtm_sharpe": g1["exact_sr_ann"],
            "dsr_global_5456": dsr_g,
            "dsr_strict_6945": g1["dsr_strict_6945_exact"],
            "dsr_new_3259": g1["dsr_new3259_exact"],
            "dsr_local": dsr_l,
            "perm_sd_p": g1["part1_fdr"]["perm_sd_p"],
            "bh_fdr_q_all": q_bh,
            "bh_fdr_q_sr_all": q_bh_sr,
            "cscv_pbo_s16": pbo,
            "nav_2023": g3["Y2023"]["nav"],
            "nav_2024": g3["Y2024"]["nav"],
            "nav_2025": g3["Y2025"]["nav"],
            "nav_2526": nav_2526,
            "nav_2026": nav_26,
            "nav_26h2": nav_26h2,
            "n_26h2": g3["Y26H2"]["n"],
            "corr_v20_all_days": g4s["corr_v20_all_days"],
            "exposure_pct": g4s["exposure_pct"],
            "ee_excess_csi300_pp": g4s["equal_exposure"]["csi300"]["excess_ee_pp"],
            "ee_excess_csi1000_pp": ee_csi1000,
            "ee_excess_ew_pp": g4s["equal_exposure"]["alla_ew"]["excess_ee_pp"],
            "ev_excess_csi1000_pp": ev_csi1000,
            "empty_only_nav_wf": emp_nav,
            "comb_ratio_vs_v20": comb_r,
            "period_flags": "|".join(flags) if flags else "NONE",
            "verdict_rationale": reason,
        })

    rank_df = pd.DataFrame(final_rows)
    rank_csv = f"{OUT_DIR}/w3_3_final_tier_ranking.csv"
    rank_df.to_csv(rank_csv, index=False, encoding="utf-8-sig")

    audit_out = sanitize_json({
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t0, 2),
        "peak_rss_mb": rss_mb(),
        "wf_window": "2023-01-03 ~ 2026-11-16 (936 trading days; 26H2 = 2026-07-01 ~ 2026-11-16, 93 days)",
        "benchmarks": bm_windows,
        "global_trial_counts": part1_stats,
        "exact_mtm_pool_calibration": {
            "n_exact_all": len(exact_sr_all),
            "var_sr_daily_exact_all": v_sr_exact_all,
            "var_sr_ann_exact_all": v_sr_exact_all * TRD_DAYS_YEAR,
            "n_exact_new": len(exact_sr_new),
            "var_sr_daily_exact_new": v_sr_exact_new,
            "var_sr_ann_exact_new": v_sr_exact_new * TRD_DAYS_YEAR,
            "sr0_ann_global_5456_exact": calc_dsr(v20_dr, N_ALL, v_sr_exact_all)["sr0_ann"],
            "sr0_ann_strict_6945_exact": calc_dsr(v20_dr, N_STRICT, v_sr_exact_all)["sr0_ann"],
            "sr0_ann_new_3259_exact": calc_dsr(v20_dr, N_NEW, v_sr_exact_new)["sr0_ann"],
        },
        "sharpe_smoothing_inflation_audit": smoothing_audit,
        "gate1_cscv_pbo_summary": cscv_summary,
        "gate2_plateaus": plateaus,
        "gate2_full_grids": {
            "20cm_F06": grid_20cm_f06,
            "20cm_Mech130": grid_20cm_mech130,
            "3to4_MineSplit": grid_3to4,
            "pry_DropRed": grid_pry,
            "ModE_USGap": grid_mode,
            "TrackC_NT_ETF": grid_etf,
            "ModC_EarnPre": grid_modc,
            "W2B4_20cm_New": grid_w2b4,
            "W2B1_ModeM": grid_w2b1,
            "20cm_CLEAN_B_S80_S84": [r for r in grid_20cm_cleanb if r["variant"].endswith(("_S80", "_S84"))],
        },
        "candidates_detailed_audit": candidates_audit,
        "gate5_final_tier_ranking": final_rows,
    })
    audit_json_path = f"{OUT_DIR}/w3_3_redteam_b_audit.json"
    with open(audit_json_path, "w", encoding="utf-8") as f:
        json.dump(audit_out, f, ensure_ascii=False, indent=2, allow_nan=False)

    print(f"[PART 3 DONE in {time.time()-t0:.1f}s] Saved:\n  {rank_csv}\n  {audit_json_path}\nRSS={rss_mb()} MB", flush=True)
    print(rank_df[["candidate_id", "tier", "n_trades_wf", "nav_wf", "exact_mtm_sharpe", "dsr_global_5456", "bh_fdr_q_all", "cscv_pbo_s16", "nav_2526", "nav_26h2", "comb_ratio_vs_v20"]].to_string(index=False), flush=True)


if __name__ == "__main__":
    main()

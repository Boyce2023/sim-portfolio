#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
trackA_stats_and_audit.py
Strict single-slot simulation, Daily MTM Sharpe/MDD/Calmar, D15 multi-window metrics,
paired t-test & sign-flip permutation p-values, Benjamini-Hochberg FDR (M=500),
and CSCV PBO (S=10 & S=8).
"""
import itertools
import math
import numpy as np
import pandas as pd
import scipy.stats as stats

TRD_DAYS_YEAR = 242.0


def filter_single_slot(trades: list[dict]) -> tuple[list[dict], int]:
    """Enforce strict chronological non-overlapping single-slot execution."""
    ordered = sorted(trades, key=lambda t: (t["buy_date"], int(t["buy_hhmm"]), t["c6"]))
    taken = []
    skipped = 0
    free_dt, free_hh = "", 0
    for t in ordered:
        assert t["exit_date"] > t["buy_date"], f"T+0 violation: {t}"
        if (not free_dt) or (t["buy_date"], int(t["buy_hhmm"])) > (free_dt, free_hh):
            taken.append(t)
            free_dt, free_hh = t["exit_date"], int(t["exit_hhmm"])
        else:
            skipped += 1
    return taken, skipped


def build_daily_mtm(taken: list[dict], cal_dts: list[str], dt_to_idx: dict, code_bars: dict, is_adj_px: bool) -> np.ndarray:
    T = len(cal_dts)
    day_mult = np.ones(T, dtype=float)
    for t in taken:
        bi = dt_to_idx.get(t["buy_date"])
        ei = dt_to_idx.get(t["exit_date"])
        if bi is None:
            continue
        cb = code_bars[t["c6"]]
        dt_pos = cb["dt_pos"]
        b_p = dt_pos.get(t["buy_date"])
        if is_adj_px:
            b_adj = float(t["buy_price"])
        elif b_p is not None:
            b_adj = float(t["buy_price"]) * float(cb["adjf"][b_p])
        else:
            b_adj = 1.0
        if b_adj <= 0:
            b_adj = 1.0
        prev_v = last_c = b_adj
        end_loop = ei if (ei is not None and ei > bi) else T
        for d_i in range(bi, end_loop):
            p_k = dt_pos.get(cal_dts[d_i])
            cur_c = float(cb["ac"][p_k]) if p_k is not None else last_c
            if cur_c <= 0:
                cur_c = last_c
            day_mult[d_i] *= (cur_c / prev_v)
            prev_v = last_c = cur_c
        if ei is not None and ei > bi:
            day_mult[ei] *= (b_adj * (1.0 + float(t["net_ret"]))) / prev_v
    return day_mult - 1.0


def get_csi_ret(sh300: dict, all_sh_dts: list[str], sdt: str, edt: str) -> float:
    prevs = [d for d in all_sh_dts if d < sdt]
    posts = [d for d in all_sh_dts if d <= edt]
    p0 = sh300[prevs[-1]] if prevs else sh300[all_sh_dts[0]]
    p1 = sh300[posts[-1]]
    return float((p1 / p0 - 1.0) * 100.0)


def calc_window_d15(taken: list[dict], full_dr: np.ndarray, cal_dts: list[str], dt_to_idx: dict, sh300: dict, all_sh_dts: list[str], sdt: str, edt: str) -> dict:
    csi_pct = get_csi_ret(sh300, all_sh_dts, sdt, edt)
    sub = [t for t in taken if sdt <= t["buy_date"] <= edt]
    w_idx = [dt_to_idx[d] for d in cal_dts if sdt <= d <= edt]
    dr = full_dr[w_idx] if w_idx else np.zeros(1)
    T = len(dr)
    mtm_nav = float(np.prod(1.0 + dr))
    cum_d = np.cumprod(1.0 + dr)
    pk_d = np.maximum.accumulate(np.insert(cum_d, 0, 1.0))[1:]
    daily_mdd = float(np.max((pk_d - cum_d) / pk_d) * 100.0) if T > 0 else 0.0
    sd = float(np.std(dr, ddof=1)) if T > 1 else 0.0
    sharpe_d = float(np.mean(dr) / sd * math.sqrt(TRD_DAYS_YEAR)) if sd > 1e-12 else 0.0
    cagr = (mtm_nav ** (TRD_DAYS_YEAR / T) - 1.0) * 100.0 if (T > 0 and mtm_nav > 0) else -100.0
    calmar = (cagr / daily_mdd) if daily_mdd > 1e-6 else 0.0

    if not sub:
        return {
            "n": 0, "wr_pct": 0.0, "plr": 0.0, "mean_pct": 0.0,
            "nav_1s": 1.0, "ex3_nav": 1.0, "ex5_nav": 1.0,
            "mdd_1s_pct": round(daily_mdd, 2), "trade_mdd_pct": 0.0,
            "sharpe": round(sharpe_d, 3), "calmar": round(calmar, 2),
            "csi300_pct": round(csi_pct, 2), "excess_1s_pp": round(-csi_pct, 2),
        }

    rets = np.array([float(t["net_ret"]) for t in sub], dtype=float)
    w, l = rets[rets > 0], rets[rets <= 0]
    wr = float((rets > 0).mean() * 100.0)
    plr = float(w.mean() / abs(l.mean())) if (len(w) and len(l) and l.mean() < 0) else (99.0 if len(w) else 0.0)
    nav_1s = float(np.prod(1.0 + rets))
    s_r = np.sort(rets)
    ex3 = float(np.prod(1.0 + s_r[:-3])) if len(rets) > 3 else 1.0
    ex5 = float(np.prod(1.0 + s_r[:-5])) if len(rets) > 5 else 1.0
    cum_t = np.cumprod(1.0 + rets)
    pk_t = np.maximum.accumulate(np.insert(cum_t, 0, 1.0))[1:]
    tr_mdd = float(np.max((pk_t - cum_t) / pk_t) * 100.0)

    return {
        "n": int(len(rets)),
        "wr_pct": round(wr, 2),
        "plr": round(plr, 2),
        "mean_pct": round(float(rets.mean() * 100.0), 2),
        "nav_1s": round(nav_1s, 4),
        "ex3_nav": round(ex3, 4),
        "ex5_nav": round(ex5, 4),
        "mdd_1s_pct": round(daily_mdd, 2),
        "trade_mdd_pct": round(tr_mdd, 2),
        "sharpe": round(sharpe_d, 3),
        "calmar": round(calmar, 2),
        "csi300_pct": round(csi_pct, 2),
        "excess_1s_pp": round((nav_1s - 1.0) * 100.0 - csi_pct, 2),
    }


def paired_tests_and_change_stats(base_rets: np.ndarray, new_rets: np.ndarray, rng: np.random.Generator, n_perm: int = 10000) -> dict:
    diff = new_rets - base_rets
    log_diff = np.log1p(np.maximum(-0.99, new_rets)) - np.log1p(np.maximum(-0.99, base_rets))
    chg_mask = np.abs(diff) > 1e-6
    n_chg = int(chg_mask.sum())
    if n_chg == 0:
        return {
            "n_changed": 0, "chg_win_rate_pct": 0.0, "wrong_rate_pct": 100.0,
            "mean_delta_pct": 0.0, "mean_log_delta": 0.0,
            "t_stat": 0.0, "p_ttest_1s": 1.0, "p_perm_1s": 1.0,
        }
    chg_d = diff[chg_mask]
    chg_ld = log_diff[chg_mask]
    win_chg = float((chg_d > 0).mean() * 100.0)
    # One-sided paired t-test across full paired sample on log_diff (compounding-consistent) & diff
    sd_ld = float(np.std(log_diff, ddof=1))
    if sd_ld > 1e-12:
        t_res = stats.ttest_1samp(log_diff, 0.0, alternative="greater")
        t_stat, p_tt = float(t_res.statistic), float(t_res.pvalue)
    else:
        t_stat, p_tt = 0.0, 1.0

    # Sign-flip permutation test on changed trades' log_diff (exact conditional null given symmetric ±delta)
    obs = float(chg_ld.sum())
    signs = rng.choice([-1.0, 1.0], size=(n_perm, n_chg))
    perm_sums = signs @ chg_ld
    p_perm = float((np.sum(perm_sums >= obs - 1e-12) + 1) / (n_perm + 1))

    return {
        "n_changed": n_chg,
        "chg_win_rate_pct": round(win_chg, 2),
        "wrong_rate_pct": round(100.0 - win_chg, 2),
        "mean_delta_pct": round(float(chg_d.mean() * 100.0), 3),
        "mean_log_delta": round(float(log_diff.mean()), 6),
        "t_stat": round(t_stat, 3),
        "p_ttest_1s": float(p_tt),
        "p_perm_1s": float(p_perm),
    }


def bh_fdr(p_vals: np.ndarray) -> np.ndarray:
    """Standard Benjamini-Hochberg step-up adjusted q-values across M hypotheses."""
    m = len(p_vals)
    order = np.argsort(p_vals)
    ranked = p_vals[order]
    q_raw = ranked * m / np.arange(1, m + 1, dtype=float)
    q_mono = np.minimum.accumulate(q_raw[::-1])[::-1]
    q_out = np.empty(m, dtype=float)
    q_out[order] = np.clip(q_mono, 0.0, 1.0)
    return q_out


def calc_cscv_pbo_matrix(R: np.ndarray, s_blocks: int = 10) -> dict:
    """CSCV PBO across S contiguous time blocks over matrix R (T x M)."""
    t_len = R.shape[0]
    gs = t_len // s_blocks
    gidx = [list(range(i * gs, (i + 1) * gs if i < s_blocks - 1 else t_len)) for i in range(s_blocks)]
    omegas = []
    for te in itertools.combinations(range(s_blocks), s_blocks // 2):
        tri = [x for k in range(s_blocks) if k not in te for x in gidx[k]]
        tei = [x for k in te for x in gidx[k]]
        rt, re_ = R[tri], R[tei]
        sd_t = rt.std(0, ddof=1)
        sd_e = re_.std(0, ddof=1)
        st = np.divide(rt.mean(0), sd_t, out=np.zeros_like(sd_t), where=sd_t > 1e-12)
        se = np.divide(re_.mean(0), sd_e, out=np.zeros_like(sd_e), where=sd_e > 1e-12)
        b = int(np.argmax(st))
        # Relative rank of b in OOS (fraction of columns strictly better than b, or >= with midpoint)
        better = np.sum(se > se[b]) + 0.5 * np.sum(se == se[b]) - 0.5
        omegas.append(float(better / max(1, R.shape[1] - 1)))
    arr_o = np.array(omegas, dtype=float)
    return {
        "pbo_pct": round(float(np.mean(arr_o > 0.50) * 100.0), 2),
        "mean_omega": round(float(np.mean(arr_o)), 4),
    }

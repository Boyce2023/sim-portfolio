#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD044 Shared Evaluation Engine, DSR, Physical Truncation, V20 Correlation & Dual-Ledger Blending.
Zero yfinance (D12). Peak RAM guard.
"""
import math
import os
import sys
from typing import Optional

import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation!"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
BASE_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd044_quant_4families_review_20261126"
CACHE_DIR = f"{OUT_DIR}/_cache"

TRD_DAYS_YEAR = 242.0
WF_START = "2023-01-03"
FULL_START = "2021-01-04"
EVAL_END = "2026-11-24"

WINDOWS_ALL = [
    ("FULL_5Y", FULL_START, EVAL_END),
    ("WF_OOS", WF_START, EVAL_END),
    ("Y2021", "2021-01-04", "2021-12-31"),
    ("Y2022", "2022-01-01", "2022-12-31"),
    ("Y2023", "2023-01-03", "2023-12-31"),
    ("Y2024", "2024-01-01", "2024-12-31"),
    ("Y2025", "2025-01-01", "2025-12-31"),
    ("Y2026", "2026-01-01", EVAL_END),
    ("Y26H2", "2026-07-01", EVAL_END),
    ("DMA_2024Q1", "2024-01-02", "2024-02-29"),
    ("G9T_2024APR", "2024-04-01", "2024-04-30"),
]


def load_bench_and_v20(end_dt: str = EVAL_END) -> dict:
    """Load canonical benchmark & V20 daily returns up to end_dt."""
    bench = pd.read_parquet(f"{BASE_DIR}/v20_daily_bench_20210104_20261125.parquet")
    bench = bench[bench["trade_date"].between(FULL_START, end_dt)].sort_values("trade_date").reset_index(drop=True)

    cal_ext = pd.read_parquet(f"{BASE_DIR}/v20_daily_slot_calendar_to_20261125.parquet")
    cal_ext = cal_ext[cal_ext["trade_date"].between(FULL_START, end_dt)].sort_values("trade_date").reset_index(drop=True)

    cal_dts = bench["trade_date"].tolist()
    dt_idx = {d: i for i, d in enumerate(cal_dts)}
    return {
        "bench": bench,
        "cal_dts": cal_dts,
        "dt_idx": dt_idx,
        "csi300_dr": bench["csi300_daily_ret"].to_numpy(float),
        "alla_ew_dr": bench["alla_ew_daily_ret"].to_numpy(float),
        "v20_cal": cal_ext,
    }


def calc_window_metrics(
    dr: np.ndarray,
    csi_dr: np.ndarray,
    ew_dr: np.ndarray,
    cal_dts: list[str],
    sdt: str,
    edt: str,
    turnover_daily: Optional[np.ndarray] = None,
    active_mask: Optional[np.ndarray] = None,
    cap_daily_yi: Optional[np.ndarray] = None,
) -> dict:
    """Exact MTM metrics over [sdt, edt] trading days."""
    mask = np.array([sdt <= d <= edt for d in cal_dts], dtype=bool)
    T = int(mask.sum())
    if T == 0:
        return {"T": 0, "nav": 1.0}

    r = dr[mask]
    c = csi_dr[mask]
    e = ew_dr[mask]

    nav = float(np.prod(1.0 + r))
    csi_nav = float(np.prod(1.0 + c))
    ew_nav = float(np.prod(1.0 + e))

    curve = np.concatenate([[1.0], np.cumprod(1.0 + r)])
    pk = np.maximum.accumulate(curve)
    mdd = float(np.max((pk - curve) / pk) * 100.0)

    sd = float(np.std(r, ddof=1)) if T > 1 else 0.0
    sharpe = float(np.mean(r) / sd * math.sqrt(TRD_DAYS_YEAR)) if sd > 1e-12 else 0.0
    cagr = (nav ** (TRD_DAYS_YEAR / T) - 1.0) * 100.0 if nav > 0 else -100.0
    calmar = (cagr / mdd) if mdd > 1e-6 else 0.0

    # Excess vs CSI300 & All-A EW (both total pp and annualized cagr diff)
    tot_ret_pct = (nav - 1.0) * 100.0
    csi_pct = (csi_nav - 1.0) * 100.0
    ew_pct = (ew_nav - 1.0) * 100.0
    csi_cagr = (csi_nav ** (TRD_DAYS_YEAR / T) - 1.0) * 100.0 if csi_nav > 0 else -100.0

    # Information ratio vs CSI300
    ex_d = r - c
    sd_ex = float(np.std(ex_d, ddof=1)) if T > 1 else 0.0
    ir_csi = float(np.mean(ex_d) / sd_ex * math.sqrt(TRD_DAYS_YEAR)) if sd_ex > 1e-12 else 0.0

    # Ex-top5 / Ex-top10 best days
    sr = np.sort(r)
    nav_ex5d = float(np.prod(1.0 + sr[:-5])) if T > 10 else nav
    nav_ex10d = float(np.prod(1.0 + sr[:-10])) if T > 20 else nav

    ann_to = float(np.mean(turnover_daily[mask]) * TRD_DAYS_YEAR * 100.0) if turnover_daily is not None else 0.0
    exp_pct = float(np.mean(active_mask[mask]) * 100.0) if active_mask is not None else float(np.mean(np.abs(r) > 1e-12) * 100.0)
    cap_p10 = float(np.nanpercentile(cap_daily_yi[mask], 10)) if (cap_daily_yi is not None and np.isfinite(cap_daily_yi[mask]).any()) else None
    cap_med = float(np.nanmedian(cap_daily_yi[mask])) if (cap_daily_yi is not None and np.isfinite(cap_daily_yi[mask]).any()) else None

    return {
        "T": T,
        "nav": round(nav, 4),
        "tot_ret_pct": round(tot_ret_pct, 2),
        "cagr_pct": round(cagr, 2),
        "sharpe": round(sharpe, 3),
        "mdd_pct": round(mdd, 2),
        "calmar": round(calmar, 2),
        "csi300_pct": round(csi_pct, 2),
        "excess_csi300_pp": round(tot_ret_pct - csi_pct, 2),
        "excess_cagr_pp": round(cagr - csi_cagr, 2),
        "ir_csi300": round(ir_csi, 3),
        "alla_ew_pct": round(ew_pct, 2),
        "excess_alla_ew_pp": round(tot_ret_pct - ew_pct, 2),
        "nav_ex_top5d": round(nav_ex5d, 4),
        "nav_ex_top10d": round(nav_ex10d, 4),
        "ann_turnover_pct": round(ann_to, 1),
        "exposure_pct": round(exp_pct, 2),
        "cap_p10_yi": round(cap_p10, 3) if cap_p10 is not None else None,
        "cap_med_yi": round(cap_med, 3) if cap_med is not None else None,
        "win_days_pct": round(float((r > 0).mean() * 100.0), 2),
    }


def evaluate_daily_series(
    dr: np.ndarray,
    bench_ctx: dict,
    turnover_daily: Optional[np.ndarray] = None,
    active_mask: Optional[np.ndarray] = None,
    cap_daily_yi: Optional[np.ndarray] = None,
    windows: list[tuple[str, str, str]] = WINDOWS_ALL,
) -> dict:
    """Evaluate a full daily return array across all canonical windows."""
    cal_dts = bench_ctx["cal_dts"]
    csi_dr = bench_ctx["csi300_dr"]
    ew_dr = bench_ctx["alla_ew_dr"]
    res = {}
    for wn, s, e in windows:
        if s > cal_dts[-1] or e < cal_dts[0]:
            continue
        res[wn] = calc_window_metrics(
            dr, csi_dr, ew_dr, cal_dts, s, e,
            turnover_daily=turnover_daily,
            active_mask=active_mask,
            cap_daily_yi=cap_daily_yi,
        )
    return res


def deflated_sharpe_ratio(
    dr: np.ndarray,
    n_trials: int,
    trial_sharpes: Optional[list[float]] = None,
) -> dict:
    """
    Bailey & Lopez de Prado (2014) Deflated Sharpe Ratio (DSR) at daily frequency (annualized via sqrt(242)).
    """
    from scipy.stats import norm

    T = len(dr)
    if T < 30 or np.std(dr, ddof=1) <= 1e-12:
        return {"sr_ann": 0.0, "dsr": 0.0, "n_trials": int(n_trials)}

    sr_daily = float(np.mean(dr) / np.std(dr, ddof=1))
    sr_ann = sr_daily * math.sqrt(TRD_DAYS_YEAR)
    z = (dr - np.mean(dr)) / np.std(dr, ddof=1)
    skew = float(np.mean(z ** 3))
    kurt = float(np.mean(z ** 4))  # non-excess kurtosis

    if trial_sharpes is not None and len(trial_sharpes) > 1:
        var_sr_ann = float(np.var(trial_sharpes, ddof=1))
    else:
        var_sr_ann = 0.25  # fallback conservative variance of annual Sharpes
    var_sr_daily = var_sr_ann / TRD_DAYS_YEAR

    n_eff = max(2, int(n_trials))
    gamma = 0.5772156649
    sr0_daily = math.sqrt(max(var_sr_daily, 1e-9)) * (
        (1.0 - gamma) * norm.ppf(1.0 - 1.0 / n_eff) + gamma * norm.ppf(1.0 - 1.0 / (n_eff * math.e))
    )
    denom_sq = max(1e-9, 1.0 - skew * sr_daily + ((kurt - 1.0) / 4.0) * (sr_daily ** 2))
    z_stat = (sr_daily - sr0_daily) * math.sqrt(T - 1) / math.sqrt(denom_sq)
    dsr = float(norm.cdf(z_stat))
    return {
        "T": T,
        "n_trials": int(n_trials),
        "sr_ann": round(sr_ann, 3),
        "sr0_ann_hurdle": round(sr0_daily * math.sqrt(TRD_DAYS_YEAR), 3),
        "skew": round(skew, 3),
        "kurt": round(kurt, 3),
        "dsr": round(dsr, 4),
    }


def compute_v20_corr_and_blend(
    q_dr: np.ndarray,
    bench_ctx: dict,
    start_dt: str = WF_START,
    end_dt: str = EVAL_END,
) -> dict:
    """
    Compute exact daily Pearson correlation vs V20.0 baseline over [start_dt, end_dt],
    and evaluate independent Dual-Ledger capital splits (70/30, 50/50, 30/70, daily rebalanced & monthly rebalanced).
    """
    cal_dts = bench_ctx["cal_dts"]
    v20_cal = bench_ctx["v20_cal"]
    v20_map = dict(zip(v20_cal["trade_date"], v20_cal["v20_daily_ret"].fillna(0.0)))

    idx_win = [i for i, d in enumerate(cal_dts) if start_dt <= d <= end_dt]
    dts_w = [cal_dts[i] for i in idx_win]
    v_dr = np.array([float(v20_map.get(d, 0.0)) for d in dts_w], dtype=float)
    q_w = q_dr[idx_win]
    csi_w = bench_ctx["csi300_dr"][idx_win]
    ew_w = bench_ctx["alla_ew_dr"][idx_win]

    # Correlations
    corr_all = float(np.corrcoef(q_w, v_dr)[0, 1]) if (np.std(q_w) > 1e-12 and np.std(v_dr) > 1e-12) else 0.0
    v_act = np.abs(v_dr) > 1e-10
    q_act = np.abs(q_w) > 1e-10
    both = v_act & q_act
    corr_v20_act = float(np.corrcoef(q_w[v_act], v_dr[v_act])[0, 1]) if (v_act.sum() >= 10 and np.std(q_w[v_act]) > 1e-12) else None
    corr_both = float(np.corrcoef(q_w[both], v_dr[both])[0, 1]) if (both.sum() >= 10 and np.std(q_w[both]) > 1e-12) else None
    corr_csi = float(np.corrcoef(q_w, csi_w)[0, 1]) if (np.std(q_w) > 1e-12 and np.std(csi_w) > 1e-12) else 0.0

    # Downside correlation when V20 drops > 2% or CSI300 drops > 1%
    v_down = v_dr < -0.02
    corr_v_down = float(np.corrcoef(q_w[v_down], v_dr[v_down])[0, 1]) if (v_down.sum() >= 10 and np.std(q_w[v_down]) > 1e-12) else None
    mean_q_when_v_down = float(np.mean(q_w[v_down]) * 100.0) if v_down.sum() > 0 else None

    def _stats(arr):
        nv = float(np.prod(1.0 + arr))
        cv = np.concatenate([[1.0], np.cumprod(1.0 + arr)])
        pk = np.maximum.accumulate(cv)
        mdd = float(np.max((pk - cv) / pk) * 100.0)
        sd = float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0
        sh = float(np.mean(arr) / sd * math.sqrt(TRD_DAYS_YEAR)) if sd > 1e-12 else 0.0
        cagr = (nv ** (TRD_DAYS_YEAR / len(arr)) - 1.0) * 100.0 if nv > 0 else -100.0
        cal = cagr / mdd if mdd > 1e-6 else 0.0
        return {"nav": round(nv, 2), "cagr_pct": round(cagr, 2), "sharpe": round(sh, 3), "mdd_pct": round(mdd, 2), "calmar": round(cal, 2)}

    def _monthly_rebal_blend(w_v20: float) -> np.ndarray:
        # Target weight w_v20 rebalanced at start of each calendar month (no future peek)
        w_q = 1.0 - w_v20
        cap_v = w_v20
        cap_q = w_q
        prev_ym = ""
        out_r = np.zeros(len(dts_w), dtype=float)
        for i, d in enumerate(dts_w):
            ym = d[:7]
            if ym != prev_ym and i > 0:
                tot = cap_v + cap_q
                cap_v = tot * w_v20
                cap_q = tot * w_q
            prev_ym = ym
            tot_b = cap_v + cap_q
            cap_v *= (1.0 + v_dr[i])
            cap_q *= (1.0 + q_w[i])
            tot_a = cap_v + cap_q
            out_r[i] = tot_a / tot_b - 1.0
        return out_r

    blends = {
        "v20_100pct": _stats(v_dr),
        "quant_100pct": _stats(q_w),
        "daily_70v20_30q": _stats(0.70 * v_dr + 0.30 * q_w),
        "daily_50v20_50q": _stats(0.50 * v_dr + 0.50 * q_w),
        "daily_30v20_70q": _stats(0.30 * v_dr + 0.70 * q_w),
        "monthly_70v20_30q": _stats(_monthly_rebal_blend(0.70)),
        "monthly_50v20_50q": _stats(_monthly_rebal_blend(0.50)),
    }

    return {
        "window": f"{start_dt} ~ {end_dt}",
        "T": len(dts_w),
        "corr_all_days": round(corr_all, 4),
        "corr_v20_active": round(corr_v20_act, 4) if corr_v20_act is not None else None,
        "corr_both_active": round(corr_both, 4) if corr_both is not None else None,
        "corr_csi300": round(corr_csi, 4),
        "corr_v20_down2pct": round(corr_v_down, 4) if corr_v_down is not None else None,
        "q_mean_pct_when_v20_down2": round(mean_q_when_v_down, 3) if mean_q_when_v_down is not None else None,
        "blends": blends,
    }

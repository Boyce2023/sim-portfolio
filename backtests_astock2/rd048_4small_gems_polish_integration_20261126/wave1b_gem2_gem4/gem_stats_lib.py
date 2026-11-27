#!/usr/bin/env python3
"""Shared D15 + 4-Small-Sample Test Suite & MTM Verification Library
for RD048 Wave 1-B (Gem 2 & Gem 4). Strictly zero yfinance imports.
"""
import math
import numpy as np
import pandas as pd


def compute_window_d15_metrics(
    trades_df: pd.DataFrame,
    mtm_daily_rets: np.ndarray,
    cal_dates: np.ndarray,
    bench_daily_rets: np.ndarray,
    start_date: str,
    end_date: str = "2026-11-25",
    ret_col: str = "net_ret",
    allow_trunc_at_window_end: bool = True,
) -> dict:
    """Compute exact D15 metrics on [start_date, end_date] with exact MTM parity check.
    Note: If a trade entered before/within [start_date, end_date] exits after end_date,
    trade-level compounded NAV covers trades whose buy_date is in [start_date, end_date],
    whereas daily MTM covers cal_dates in [start_date, end_date].
    To guarantee mtm_diff == 0.0000 on full windows (where all trades resolve <= end_date),
    we compute BOTH exact calendar MTM NAV & trade-compounded NAV and verify abs diff!
    """
    m_cal = (cal_dates >= start_date) & (cal_dates <= end_date)
    w_dates = cal_dates[m_cal]
    w_rets = mtm_daily_rets[m_cal]
    w_bench = bench_daily_rets[m_cal]

    if len(w_dates) == 0:
        return {"empty": True}

    mtm_nav_curve = np.cumprod(1.0 + w_rets)
    mtm_nav = float(mtm_nav_curve[-1])
    bench_nav = float(np.prod(1.0 + w_bench))
    excess_pp = (mtm_nav - bench_nav) * 100.0

    # Max drawdown & Calmar
    peak = np.maximum.accumulate(np.concatenate([[1.0], mtm_nav_curve]))[1:]
    dd = 1.0 - mtm_nav_curve / peak
    mdd_pct = float(dd.max() * 100.0) if len(dd) > 0 else 0.0
    curr_dd_pct = float(dd[-1] * 100.0) if len(dd) > 0 else 0.0
    ann_ret = (mtm_nav ** (252.0 / len(w_rets)) - 1.0) if mtm_nav > 0 else -1.0
    std_d = float(np.std(w_rets, ddof=1)) if len(w_rets) > 1 else 0.0
    sharpe = float((np.mean(w_rets) / std_d) * math.sqrt(252.0)) if std_d > 1e-12 else 0.0
    calmar = float((ann_ret * 100.0) / mdd_pct) if mdd_pct > 1e-9 else 0.0

    # Trade stats inside [start_date, end_date]
    if len(trades_df) > 0:
        sub = trades_df[(trades_df["buy_date"] >= start_date) & (trades_df["buy_date"] <= end_date)].copy()
    else:
        sub = pd.DataFrame()
    n = int(len(sub))
    if n > 0:
        r = sub[ret_col].to_numpy(dtype=np.float64)
        wr_pct = float((r > 0).mean() * 100.0)
        wins = r[r > 0]
        losses = r[r < 0]
        plr = float(wins.mean() / abs(losses.mean())) if len(wins) > 0 and len(losses) > 0 else (99.0 if len(losses) == 0 else 0.0)
        mean_pct = float(r.mean() * 100.0)
        trade_nav = float(np.prod(1.0 + r))
        r_sorted = np.sort(r)
        ex3_nav = float(np.prod(1.0 + r_sorted[:-3])) if n > 3 else 1.0
        ex5_nav = float(np.prod(1.0 + r_sorted[:-5])) if n > 5 else 1.0
        n_resolved_after = int((sub["exit_date"] > end_date).sum())
    else:
        wr_pct = 0.0
        plr = 0.0
        mean_pct = 0.0
        trade_nav = 1.0
        ex3_nav = 1.0
        ex5_nav = 1.0
        n_resolved_after = 0

    # Exact mtm_diff only compares identically bounded window (or note boundary trade if start>2021-01-04)
    mtm_diff = abs(mtm_nav - trade_nav)
    active_days = int((np.abs(w_rets) > 1e-12).sum())

    return {
        "start_date": start_date,
        "end_date": end_date,
        "cal_days": int(len(w_dates)),
        "active_days": active_days,
        "exposure_pct": round(active_days / max(1, len(w_dates)) * 100.0, 2),
        "n_trades": n,
        "n_boundary_open_after_end": n_resolved_after,
        "wr_pct": round(wr_pct, 2),
        "plr": round(plr, 2),
        "mean_ret_pct": round(mean_pct, 3),
        "trade_nav": round(trade_nav, 6),
        "mtm_nav": round(mtm_nav, 6),
        "mtm_diff": round(mtm_diff, 10),
        "ex3_nav": round(ex3_nav, 4),
        "ex5_nav": round(ex5_nav, 4),
        "mdd_pct": round(mdd_pct, 2),
        "curr_dd_pct": round(curr_dd_pct, 2),
        "sharpe": round(sharpe, 3),
        "calmar": round(calmar, 2),
        "ann_ret_pct": round(ann_ret * 100.0, 2),
        "bench_csi300_ret_pct": round((bench_nav - 1.0) * 100.0, 2),
        "excess_csi300_pp": round(excess_pp, 2),
    }


def build_exact_mtm_series(
    trades_df: pd.DataFrame,
    cal_dates: np.ndarray,
    dt_to_idx: dict,
    daily_mtm_field: str = "mtm_pairs_json",
) -> np.ndarray:
    """Build daily portfolio MTM return series from per-trade (date, ret) JSON pairs.
    For single-slot non-overlapping trades, sum/compound within day guarantees exact parity.
    """
    import json
    n_days = len(cal_dates)
    rets = np.zeros(n_days, dtype=np.float64)
    used = np.zeros(n_days, dtype=bool)
    for _, row in trades_df.iterrows():
        pairs = json.loads(row[daily_mtm_field])
        for dt_str, d_ret in pairs:
            idx = dt_to_idx.get(dt_str)
            if idx is None:
                continue
            if not used[idx]:
                rets[idx] = float(d_ret)
                used[idx] = True
            else:
                # Same-day exit + new entry (e.g. sell at 09:25, buy at 09:25/15:00)
                rets[idx] = (1.0 + rets[idx]) * (1.0 + float(d_ret)) - 1.0
    return rets


def run_four_small_sample_tests(
    trades_df: pd.DataFrame,
    mtm_daily_rets: np.ndarray,
    cal_dates: np.ndarray,
    bench_daily_rets: np.ndarray,
    ret_col: str = "net_ret",
    neg_ctrl_summary: dict = None,
    seed: int = 20261126,
) -> dict:
    """Run all 4 standardized small-sample statistical tests:
      1) 10,000x Bootstrap (5% lower bound & P(expectancy > 0))
      2) Sequential Bayesian posterior & max/threshold consecutive-loss stop line
      3) Same-period negative control comparison
      4) Cross-regime change-point audit & current drawdown from peak
    """
    if len(trades_df) == 0:
        return {"empty": True}

    df = trades_df.sort_values("buy_date").reset_index(drop=True)
    r = df[ret_col].to_numpy(dtype=np.float64)
    n = len(r)
    rng = np.random.default_rng(seed)

    # 1. 10,000x Bootstrap
    n_boot = 10000
    idx = rng.integers(0, n, size=(n_boot, n))
    boot_r = r[idx]
    boot_means = boot_r.mean(axis=1) * 100.0
    # Clamp single-trade extreme <= -1.0 safely for prod
    boot_navs = np.prod(np.maximum(0.0, 1.0 + boot_r), axis=1)
    boot = {
        "n_boot": n_boot,
        "n_trades": int(n),
        "mean_ret_pct_obs": round(float(r.mean() * 100.0), 3),
        "mean_ret_pct_p05": round(float(np.percentile(boot_means, 5)), 3),
        "mean_ret_pct_p50": round(float(np.percentile(boot_means, 50)), 3),
        "mean_ret_pct_p95": round(float(np.percentile(boot_means, 95)), 3),
        "nav_p05": round(float(np.percentile(boot_navs, 5)), 4),
        "nav_p50": round(float(np.percentile(boot_navs, 50)), 4),
        "nav_p95": round(float(np.percentile(boot_navs, 95)), 4),
        "prob_positive_expectancy_pct": round(float((boot_means > 0).mean() * 100.0), 2),
        "prob_nav_gt_1_pct": round(float((boot_navs > 1.0).mean() * 100.0), 2),
    }

    # 2. Sequential Bayesian Posterior (Beta-Binomial for WR + Normal-t for Mean Ret) & Consecutive-Loss Stop Line
    # Beta(2, 2) weak neutral prior (50% mean, ESS=4)
    alpha0, beta0 = 2.0, 2.0
    wins = int((r > 0).sum())
    losses = n - wins
    alpha_post = alpha0 + wins
    beta_post = beta0 + losses
    post_wr_mean = alpha_post / (alpha_post + beta_post)
    post_wr_draws = rng.beta(alpha_post, beta_post, size=20000)
    # Normal-Gamma / Student-t Bayesian return posterior with skeptical zero prior kappa0=2
    kappa0 = 2.0
    mu0 = 0.0
    s2 = float(np.var(r, ddof=1)) if n > 1 else 0.0025
    post_mean = (n * float(r.mean()) + kappa0 * mu0) / (n + kappa0)
    post_se = math.sqrt((s2 * max(1, n - 1) + (n * kappa0 / (n + kappa0)) * (float(r.mean()) - mu0) ** 2) / max(1, (n + kappa0 - 1)) / (n + kappa0))
    # Monte carlo t-draws via normal approx for df > 2
    df_t = max(2, n + 1)
    t_draws = post_mean + post_se * rng.standard_t(df=df_t, size=20000)

    # Observed consecutive losses + statistical stop-loss trigger
    max_consec_loss = 0
    curr_consec_loss = 0
    for x in r:
        if x <= 0:
            curr_consec_loss += 1
            max_consec_loss = max(max_consec_loss, curr_consec_loss)
        else:
            curr_consec_loss = 0
    p_loss_est = 1.0 - post_wr_mean
    # Streak k such that p_loss^k < 0.05 (95% regime break redline) and < 0.01
    redline_95 = max(3, int(math.ceil(math.log(0.05) / math.log(max(0.05, min(0.95, p_loss_est))))))
    redline_99 = max(4, int(math.ceil(math.log(0.01) / math.log(max(0.05, min(0.95, p_loss_est))))))

    bayes = {
        "prior": "Beta(2,2) WR + N(0, kappa=2) ret",
        "post_wr_mean_pct": round(post_wr_mean * 100.0, 2),
        "post_wr_ci90_pct": [round(float(np.percentile(post_wr_draws, 5) * 100.0), 2), round(float(np.percentile(post_wr_draws, 95) * 100.0), 2)],
        "prob_post_wr_gt_50pct": round(float((post_wr_draws > 0.50).mean() * 100.0), 2),
        "post_ret_mean_pct": round(post_mean * 100.0, 3),
        "prob_post_ret_gt_0_pct": round(float((t_draws > 0.0).mean() * 100.0), 2),
        "obs_max_consec_losses": int(max_consec_loss),
        "obs_curr_consec_losses": int(curr_consec_loss),
        "stop_redline_consec_losses_p95": int(redline_95),
        "stop_redline_consec_losses_p99": int(redline_99),
    }

    # 4. Cross-Regime Change-Point & Drawdown from Peak
    regimes = [
        ("R1_2021_2022", "2021-01-04", "2022-12-30"),
        ("R2_2023_24Pre924", "2023-01-03", "2024-09-23"),
        ("R3_924_2025", "2024-09-24", "2025-12-31"),
        ("R4_2026H1", "2026-01-05", "2026-06-30"),
        ("R5_2026H2", "2026-07-01", "2026-11-26"),
    ]
    regime_stats = []
    for rname, s_dt, e_dt in regimes:
        sub_r = df[(df["buy_date"] >= s_dt) & (df["buy_date"] <= e_dt)]
        vals = sub_r[ret_col].to_numpy(dtype=np.float64)
        nav_r = float(np.prod(1.0 + vals)) if len(vals) > 0 else 1.0
        wr_r = float((vals > 0).mean() * 100.0) if len(vals) > 0 else None
        mean_r = float(vals.mean() * 100.0) if len(vals) > 0 else None
        regime_stats.append({
            "regime": rname,
            "n": int(len(vals)),
            "wr_pct": round(wr_r, 2) if wr_r is not None else None,
            "mean_ret_pct": round(mean_r, 3) if mean_r is not None else None,
            "nav": round(nav_r, 4),
        })

    # CUSUM split max |t| test for change-point across chronological trades
    best_split_z = 0.0
    best_split_date = None
    if n >= 8:
        for k in range(3, n - 2):
            a, b = r[:k], r[k:]
            se = math.sqrt(np.var(a, ddof=1) / len(a) + np.var(b, ddof=1) / len(b)) if (np.var(a, ddof=1) + np.var(b, ddof=1)) > 0 else 0.0
            if se > 1e-12:
                z = abs(a.mean() - b.mean()) / se
                if z > best_split_z:
                    best_split_z = float(z)
                    best_split_date = str(df.loc[k, "buy_date"])

    # Peak DD & underwater days on daily MTM
    nav_curve = np.cumprod(1.0 + mtm_daily_rets)
    peak_curve = np.maximum.accumulate(np.concatenate([[1.0], nav_curve]))[1:]
    dd_curve = 1.0 - nav_curve / peak_curve
    peak_idx = int(np.argmax(nav_curve))
    curr_dd_pct = float(dd_curve[-1] * 100.0) if len(dd_curve) else 0.0
    max_dd_pct = float(dd_curve.max() * 100.0) if len(dd_curve) else 0.0
    underwater_days = int(len(nav_curve) - 1 - peak_idx)

    changepoint = {
        "regime_breakdown": regime_stats,
        "cusum_max_abs_t": round(best_split_z, 3),
        "cusum_split_date": best_split_date,
        "regime_shift_flag_p05": bool(best_split_z >= 2.5),
        "peak_nav": round(float(nav_curve.max()), 4),
        "peak_date": str(cal_dates[peak_idx]) if len(cal_dates) else None,
        "latest_nav": round(float(nav_curve[-1]), 4) if len(nav_curve) else 1.0,
        "curr_dd_from_peak_pct": round(curr_dd_pct, 2),
        "max_dd_pct": round(max_dd_pct, 2),
        "underwater_days_since_peak": underwater_days,
    }

    return {
        "test1_bootstrap_10k": boot,
        "test2_sequential_bayes_and_stop": bayes,
        "test3_negative_control": neg_ctrl_summary if neg_ctrl_summary is not None else {},
        "test4_regime_changepoint_and_dd": changepoint,
    }

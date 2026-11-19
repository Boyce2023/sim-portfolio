#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unified Theory Efficacy Index (TEI, 0-100) & Regime Attribution Library
for 15-Year Chinese Investment Theory Backtest (2011-01-01 to 2026-11-18).

TEI = 0.35 * S_IR + 0.25 * S_Exp + 0.20 * S_DD + 0.20 * S_Cons
  50.0 = Random coin-flip / pure benchmark parity
  >= 65: Strong Alpha (真有效)
  55-65: Conditional / Regime-dependent (吃环境饭)
  45-55: Random noise (随机噪音)
  <  45: Reverse indicator / decayed (反向指标/失效)
"""
import numpy as np
import pandas as pd


def _clip_score(x, lo=0.0, hi=100.0):
    if pd.isna(x) or not np.isfinite(x):
        return 50.0
    return float(np.clip(x, lo, hi))


def max_drawdown(ret_series: pd.Series) -> float:
    if len(ret_series) == 0:
        return 0.0
    nav = (1.0 + ret_series.fillna(0.0)).cumprod()
    peak = nav.cummax()
    dd = nav / peak - 1.0
    return float(dd.min())


def compute_period_metrics(strat_ret: pd.Series, bench_ret: pd.Series, active_mask: pd.Series = None) -> dict:
    """Compute D15-compliant metrics + TEI (0-100) for a daily return series vs benchmark."""
    df = pd.DataFrame({"s": strat_ret, "b": bench_ret}).dropna()
    if active_mask is not None:
        df["act"] = active_mask.reindex(df.index).fillna(0.0)
    else:
        df["act"] = (df["s"].abs() > 1e-12).astype(float)
    n = len(df)
    if n < 20:
        return {
            "n_days": n, "ann_ret": None, "bench_ann_ret": None, "excess_ann": None,
            "sharpe": None, "ir": None, "mdd": None, "bench_mdd": None,
            "calmar": None, "q_win_rate": None, "t_stat": None, "tei": 50.0,
            "exposure_pct": 0.0,
        }
    years = n / 242.0
    s_nav = float((1.0 + df["s"]).prod())
    b_nav = float((1.0 + df["b"]).prod())
    s_ann = (s_nav ** (1.0 / years) - 1.0) if s_nav > 0 else -1.0
    b_ann = (b_nav ** (1.0 / years) - 1.0) if b_nav > 0 else -1.0
    excess_ann = s_ann - b_ann

    ex_d = df["s"] - df["b"]
    s_std = float(df["s"].std()) * np.sqrt(242.0)
    ex_std = float(ex_d.std()) * np.sqrt(242.0)
    sharpe = (float(df["s"].mean()) * 242.0) / s_std if s_std > 1e-9 else 0.0
    ir = (float(ex_d.mean()) * 242.0) / ex_std if ex_std > 1e-9 else 0.0
    t_stat = (float(ex_d.mean()) / (float(ex_d.std()) / np.sqrt(n))) if float(ex_d.std()) > 1e-12 else 0.0

    mdd = max_drawdown(df["s"])
    b_mdd = max_drawdown(df["b"])
    calmar = s_ann / abs(mdd) if abs(mdd) > 1e-6 else 0.0

    # Quarterly excess win rate (consistency pillar)
    q_s = (1.0 + df["s"]).resample("QE").prod() - 1.0
    q_b = (1.0 + df["b"]).resample("QE").prod() - 1.0
    q_ex = (q_s - q_b).dropna()
    q_win = float((q_ex > 0).mean()) if len(q_ex) >= 2 else 0.5

    # Active-day excess expectancy (daily excess annualized + t-stat shrinkage toward 50)
    shrink = min(1.0, abs(t_stat) / 1.5)  # shrinks noisy small-t results toward 50
    # Pillar 1: Information Ratio (IR=0 -> 50, IR=+1.0 -> 85, IR=-1.0 -> 15)
    s_ir = _clip_score(50.0 + 35.0 * np.tanh(ir * 0.9))
    # Pillar 2: Risk-adjusted excess return with t-stat shrinkage
    raw_exp = 50.0 + 35.0 * np.tanh((excess_ann / 0.12))
    s_exp = _clip_score(50.0 + (raw_exp - 50.0) * (0.4 + 0.6 * shrink))
    # Pillar 3: Drawdown protection (mdd vs bench_mdd)
    if abs(b_mdd) > 0.05:
        dd_improve = (abs(b_mdd) - abs(mdd)) / abs(b_mdd)  # +0.5 means cut MDD in half
    else:
        dd_improve = 0.0
    # Only reward drawdown protection if strategy isn't permanently 0% exposed cash
    exp_pct = float((df["act"] > 0.01).mean())
    dd_weight_adj = min(1.0, exp_pct / 0.25) if exp_pct < 0.25 else 1.0
    s_dd = _clip_score(50.0 + 35.0 * np.tanh(dd_improve * 1.4) * dd_weight_adj)
    # Pillar 4: Quarterly OOS Consistency (50% -> 50, 75% -> 85, 25% -> 15)
    s_cons = _clip_score(50.0 + (q_win - 0.5) * 140.0)

    tei = round(0.35 * s_ir + 0.25 * s_exp + 0.20 * s_dd + 0.20 * s_cons, 1)
    return {
        "n_days": int(n),
        "ann_ret": round(s_ann * 100, 2),
        "bench_ann_ret": round(b_ann * 100, 2),
        "excess_ann": round(excess_ann * 100, 2),
        "total_mult": round(s_nav, 3),
        "bench_mult": round(b_nav, 3),
        "sharpe": round(sharpe, 2),
        "ir": round(ir, 2),
        "mdd": round(mdd * 100, 2),
        "bench_mdd": round(b_mdd * 100, 2),
        "calmar": round(calmar, 2),
        "q_win_rate": round(q_win * 100, 1),
        "t_stat": round(t_stat, 2),
        "exposure_pct": round(exp_pct * 100, 1),
        "tei": tei,
        "tei_pillars": {"ir": round(s_ir, 1), "exp": round(s_exp, 1), "dd": round(s_dd, 1), "cons": round(s_cons, 1)},
    }


def evaluate_full_profile(name: str, strat_ret: pd.Series, bench_ret: pd.Series,
                          regime_df: pd.DataFrame, active_mask: pd.Series = None) -> dict:
    """
    Produce complete D15 + TEI time-evolution + 6-factor regime attribution profile.
    regime_df must be indexed by date with columns:
      trend_regime ('bull'/'bear'/'range'), vol_regime ('high_vol'/'low_vol'),
      amt_regime ('high_amt'/'low_amt'), rate_regime ('easing'/'tightening'),
      ppi_regime ('reflation'/'deflation'), era ('2011_2015'/'2016_2020'/'2021_2026')
    """
    df = pd.DataFrame({"s": strat_ret, "b": bench_ret}).dropna()
    df = df[(df.index >= "2011-01-01") & (df.index <= "2026-11-18")]
    act = active_mask.reindex(df.index).fillna(0.0) if active_mask is not None else (df["s"].abs() > 1e-12).astype(float)

    # Full 15Y + 3-period D15 check (Full 15Y, Last 10Y 2016-2026, Last 3Y 2023-2026, Recent 2024-2026)
    overall = compute_period_metrics(df["s"], df["b"], act)
    last_10y = compute_period_metrics(df.loc["2016-11-19":, "s"], df.loc["2016-11-19":, "b"], act.loc["2016-11-19":])
    last_3y = compute_period_metrics(df.loc["2023-11-19":, "s"], df.loc["2023-11-19":, "b"], act.loc["2023-11-19":])

    # Year-by-year TEI & excess return (2011..2026)
    by_year = {}
    for yr in range(2011, 2027):
        sub = df[df.index.year == yr]
        if len(sub) >= 20:
            m = compute_period_metrics(sub["s"], sub["b"], act.reindex(sub.index))
            by_year[str(yr)] = {"tei": m["tei"], "ann_ret": m["ann_ret"], "excess_ann": m["excess_ann"], "mdd": m["mdd"], "ir": m["ir"]}

    # Rolling 2-year (484d) TEI sampled semi-annually for decay slope
    roll_pts = []
    dates = df.index
    for i in range(484, len(dates), 120):
        sub = df.iloc[i - 484:i]
        m = compute_period_metrics(sub["s"], sub["b"], act.reindex(sub.index))
        roll_pts.append({"end_date": str(dates[i - 1])[:10], "tei": m["tei"], "ir": m["ir"], "excess_ann": m["excess_ann"]})
    if len(dates) >= 484:
        sub = df.iloc[-484:]
        m = compute_period_metrics(sub["s"], sub["b"], act.reindex(sub.index))
        if not roll_pts or roll_pts[-1]["end_date"] != str(dates[-1])[:10]:
            roll_pts.append({"end_date": str(dates[-1])[:10], "tei": m["tei"], "ir": m["ir"], "excess_ann": m["excess_ann"]})

    # Time decay slope (TEI points per decade via OLS on rolling points)
    if len(roll_pts) >= 4:
        xs = np.linspace(0.0, 1.5, len(roll_pts))  # ~15 years = 1.5 decades
        ys = np.array([p["tei"] for p in roll_pts], dtype=float)
        decay_per_decade = round(float(np.polyfit(xs, ys, 1)[0]), 1)
    else:
        decay_per_decade = 0.0

    # 6-Factor Regime Attribution (TEI & excess_ann in each regime bucket)
    reg_align = regime_df.reindex(df.index)
    regimes = {}
    for col in ["trend_regime", "vol_regime", "amt_regime", "rate_regime", "ppi_regime", "era"]:
        if col not in reg_align.columns:
            continue
        regimes[col] = {}
        for val, grp_idx in reg_align.groupby(col).groups.items():
            if len(grp_idx) >= 40:
                m = compute_period_metrics(df.loc[grp_idx, "s"], df.loc[grp_idx, "b"], act.loc[grp_idx])
                regimes[col][str(val)] = {"n_days": m["n_days"], "tei": m["tei"], "excess_ann": m["excess_ann"], "ir": m["ir"], "ann_ret": m["ann_ret"]}

    return {
        "name": name,
        "overall_15y": overall,
        "last_10y": last_10y,
        "last_3y": last_3y,
        "tei_decay_per_decade": decay_per_decade,
        "by_year": by_year,
        "rolling_2y_tei": roll_pts,
        "regimes": regimes,
    }

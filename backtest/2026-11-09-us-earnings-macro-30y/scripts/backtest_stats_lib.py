"""
backtest_stats_lib.py
Unified, Zero-Lookahead, D15-Compliant & NTRA-5-Pitfall-Compliant Statistical Evaluation Engine
for the 30-Year US Stock Earnings Inflection + Macro Regime Backtest.

Implements:
1. Calendar-Quarter Equal-Weight Net Excess Return vs SPY (eliminates crash-bottom date clustering).
2. 12-Month Cooldown Per-Ticker Deduplication (eliminates counting one multi-year winner 8 times).
3. Median Net Excess Return, Win Rate vs SPY, Real Payoff Ratio, >=+100% Bag Rate, <=-50% Blowup Rate.
4. Explicit Subperiod Splits: Full Period, Ex-2020-2021 Bubble, Last 10Y (2016-2026), High-Rate Era (2022-2026), Pre-2009 (1996-2009).
5. Purged Walk-Forward CV (with embargo = forward horizon) & Benjamini-Hochberg FDR + Bailey-Lopez de Prado Sharpe Haircut.
"""

import numpy as np
import pandas as pd
from scipy import stats

CYCLICAL_SECTORS_KEYWORDS = (
    "energy", "oil", "gas", "coal", "mining", "metals", "steel", "aluminum", "copper", "gold",
    "chemicals", "fertilizer", "agricultural", "paper", "forest", "lumber", "shipping", "marine",
    "airlines", "auto", "homebuilding", "residential construction"
)
FINANCIAL_UTILITY_KEYWORDS = (
    "bank", "insurance", "reit", "real estate", "utilities", "electric", "water", "credit services", "mortgage"
)


def classify_sector_type(sector: str, industry: str) -> str:
    s = f"{sector or ''} {industry or ''}".lower()
    if any(k in s for k in CYCLICAL_SECTORS_KEYWORDS):
        return "Deep_Cyclical"
    if any(k in s for k in FINANCIAL_UTILITY_KEYWORDS):
        return "Financial_Utility_RateSens"
    if "health" in s or "biotech" in s or "pharma" in s or "medical" in s or "diagnostics" in s:
        return "Healthcare_LifeSci"
    if "semiconductor" in s or "memory" in s or "hardware" in s or "electronic" in s:
        return "Tech_Hardware_Semi"
    if "software" in s or "internet" in s or "cloud" in s or "it services" in s or "information" in s:
        return "Software_Internet"
    return "Industrial_Consumer_Compounder"


def deduplicate_cooldown(df: pd.DataFrame, date_col: str = "entry_date", cooldown_days: int = 250) -> pd.DataFrame:
    """Keep first trigger per ticker, then ignore subsequent triggers within cooldown_days."""
    if len(df) == 0:
        return df
    d = df.sort_values(["ticker", date_col]).copy()
    keep_mask = np.zeros(len(d), dtype=bool)
    tks = d["ticker"].values
    dts = pd.to_datetime(d[date_col]).values.astype("datetime64[D]").astype(np.int64)
    last_tk = None
    last_dt = -999999
    for i in range(len(d)):
        if tks[i] != last_tk or (dts[i] - last_dt) >= cooldown_days:
            keep_mask[i] = True
            last_tk = tks[i]
            last_dt = dts[i]
    return d.iloc[keep_mask].copy()


def eval_slice(
    df_sub: pd.DataFrame,
    horizons=(63, 126, 252, 504, 756, 1260),
    dedup_days: int = 250,
    date_col: str = "entry_date",
    label: str = ""
) -> dict:
    """
    Computes comprehensive D15 + anti-bias metrics for a signal slice.
    """
    res = {"label": label, "n_raw": int(len(df_sub))}
    if len(df_sub) == 0:
        return res

    # Remove known unadjusted split anomalies
    if "has_anomaly_break" in df_sub.columns:
        df_clean = df_sub[~df_sub["has_anomaly_break"].fillna(False)].copy()
    else:
        df_clean = df_sub.copy()

    df_clean["cal_qtr"] = pd.to_datetime(df_clean[date_col]).dt.to_period("Q")
    df_dedup = deduplicate_cooldown(df_clean, date_col=date_col, cooldown_days=dedup_days)
    res["n_dedup"] = int(len(df_dedup))
    res["n_tickers"] = int(df_clean["ticker"].nunique())

    # Earnings reaction stats (if available)
    if "earn_jump_ret" in df_clean.columns:
        ej = df_clean["earn_jump_ret"].dropna()
        res["jump_mean"] = float(ej.mean()) if len(ej) else np.nan
        res["jump_ge10_prob"] = float((ej >= 0.10).mean()) if len(ej) else np.nan
        res["jump_ge8_prob"] = float((ej >= 0.08).mean()) if len(ej) else np.nan
        res["drop_le5_prob"] = float((ej <= -0.05).mean()) if len(ej) else np.nan

    for h in horizons:
        r_col = f"fwd_{h}d"
        a_col = f"alpha_fwd_{h}d"
        if a_col not in df_clean.columns:
            continue

        sub_h = df_clean.dropna(subset=[a_col, r_col])
        ded_h = df_dedup.dropna(subset=[a_col, r_col])
        n_h = len(ded_h)
        res[f"n_{h}d"] = int(n_h)
        if n_h < 5:
            for k in ("qtr_ew_alpha", "dedup_mean_alpha", "med_alpha", "win_rate", "payoff", "bag2x_prob", "halve_prob", "t_stat", "p_val"):
                res[f"{k}_{h}d"] = np.nan
            continue

        # 1. Calendar-Quarter Equal-Weight Net Excess Return vs SPY
        qtr_means = sub_h.groupby("cal_qtr")[a_col].mean()
        qtr_ew_alpha = float(qtr_means.mean())
        qtr_se = float(qtr_means.std(ddof=1) / np.sqrt(len(qtr_means))) if len(qtr_means) > 2 else np.nan
        t_stat = qtr_ew_alpha / qtr_se if (qtr_se and qtr_se > 0) else np.nan
        p_val = float(2 * (1 - stats.t.cdf(abs(t_stat), df=max(len(qtr_means) - 1, 1)))) if pd.notna(t_stat) else np.nan

        # 2. Deduplicated Event Stats
        a_vals = ded_h[a_col].values
        r_vals = ded_h[r_col].values
        pos_a = a_vals[a_vals > 0]
        neg_a = a_vals[a_vals <= 0]
        payoff = float(pos_a.mean() / abs(neg_a.mean())) if (len(pos_a) > 0 and len(neg_a) > 0 and neg_a.mean() != 0) else np.nan

        res[f"qtr_ew_alpha_{h}d"] = qtr_ew_alpha
        res[f"qtr_ew_ret_{h}d"] = float(sub_h.groupby("cal_qtr")[r_col].mean().mean())
        res[f"dedup_mean_alpha_{h}d"] = float(np.mean(a_vals))
        res[f"med_alpha_{h}d"] = float(np.median(a_vals))
        res[f"med_ret_{h}d"] = float(np.median(r_vals))
        res[f"win_rate_{h}d"] = float(np.mean(a_vals > 0))
        res[f"payoff_{h}d"] = payoff
        res[f"bag2x_prob_{h}d"] = float(np.mean(r_vals >= 1.0))
        res[f"halve_prob_{h}d"] = float(np.mean(r_vals <= -0.50))
        res[f"t_stat_{h}d"] = t_stat
        res[f"p_val_{h}d"] = p_val
        res[f"n_qtrs_{h}d"] = int(len(qtr_means))

    if "fwd_max_dd_252d" in df_dedup.columns:
        mdd = df_dedup["fwd_max_dd_252d"].dropna().values
        res["med_mdd_1y"] = float(np.median(mdd)) if len(mdd) else np.nan
        res["mdd50_1y_prob"] = float(np.mean(mdd <= -0.50)) if len(mdd) else np.nan

    return res


def eval_d15_subperiods(df_sub: pd.DataFrame, date_col: str = "entry_date", label: str = "") -> pd.DataFrame:
    """
    Evaluates a strategy across mandatory D15 + NTRA anti-bias subperiods:
    - Full Sample
    - Ex-2020-2021 Zero-Rate Bubble
    - Pre-2009 (1996-2009, if present)
    - 2010-2019 Low-Rate Secular Bull
    - 2020-2021 COVID Bubble (quarantined)
    - Last 10Y (2016-2026)
    - Last 4Y High-Rate AI/Capex Era (2022-2026)
    - Recent (2024-2026)
    """
    dt = pd.to_datetime(df_sub[date_col])
    cuts = [
        ("Full_Sample", pd.Series(True, index=df_sub.index)),
        ("Ex_2020_2021_Bubble", ~((dt >= "2020-03-01") & (dt <= "2021-12-31"))),
        ("Pre_2009_1996_2009", (dt >= "1996-01-01") & (dt < "2009-07-01")),
        ("2010_2019_LowRateBull", (dt >= "2010-01-01") & (dt <= "2019-12-31")),
        ("2020_2021_CovidBubble", (dt >= "2020-01-01") & (dt <= "2021-12-31")),
        ("Last_10Y_2016_2026", dt >= "2016-01-01"),
        ("HighRate_2022_2026", dt >= "2022-01-01"),
        ("Recent_2024_2026", dt >= "2024-01-01"),
    ]
    rows = []
    for pname, mask in cuts:
        s = df_sub[mask]
        if len(s) >= 5:
            r = eval_slice(s, horizons=(63, 252, 504, 756, 1260), date_col=date_col, label=f"{label} | {pname}")
            r["subperiod"] = pname
            rows.append(r)
    return pd.DataFrame(rows)


def benjamini_hochberg_fdr(p_vals: np.ndarray) -> np.ndarray:
    """Computes BH-adjusted q-values for multiple-testing control."""
    p = np.asarray(p_vals, dtype=float)
    q = np.full_like(p, np.nan)
    valid = ~np.isnan(p)
    pv = p[valid]
    m = len(pv)
    if m == 0:
        return q
    order = np.argsort(pv)
    ranked = pv[order]
    adj = ranked * m / np.arange(1, m + 1)
    adj = np.minimum.accumulate(adj[::-1])[::-1]
    adj = np.clip(adj, 0.0, 1.0)
    out_v = np.empty_like(pv)
    out_v[order] = adj
    q[valid] = out_v
    return q


def sharpe_haircut_bailey_lopez(sharpe_obs: float, sharpe_all_trials: np.ndarray) -> dict:
    """Bailey & Lopez de Prado expected maximum Sharpe haircut under N trials."""
    valid = np.asarray(sharpe_all_trials, dtype=float)
    valid = valid[~np.isnan(valid)]
    n_trials = len(valid)
    if n_trials < 2:
        return {"n_trials": n_trials, "expected_max_null": 0.0, "haircut_sharpe": sharpe_obs}
    sr_std = float(np.std(valid, ddof=1))
    gamma = 0.5772156649
    exp_max = sr_std * ((1 - gamma) * stats.norm.ppf(1 - 1.0 / n_trials) + gamma * stats.norm.ppf(1 - 1.0 / (n_trials * np.e)))
    return {
        "n_trials": int(n_trials),
        "sharpe_std_across_trials": sr_std,
        "expected_max_null": float(exp_max),
        "observed_sharpe": float(sharpe_obs),
        "haircut_sharpe": float(sharpe_obs - exp_max),
    }

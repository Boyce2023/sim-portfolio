#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RD021 金属与能源组 (黄金 / 铜 / 石油) 十年股期联动实证脚本
Strictly NO yfinance imports (D12). Reads pre-cleaned parquet files from data_cache/.
Modules:
  1. ZigZag (Gold 12%/22%, Copper/Oil 20%/25%) + 120d local extrema turning point lead-lag
  2. Cross-correlation scan k in [-180, +180] (60d primary, 20d robustness, n_eff t-stats)
  3. Strictly PIT t+1 open execution backtest with 0.30% round-trip cost (A, A_adapt, A2, B, C)
"""
import json
import math
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import stats

assert "yfinance" not in sys.modules, "D12 violation: yfinance must not be imported"

BASE_DIR = Path("/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/commodities_leadlag_10y_20261123")
DATA_DIR = BASE_DIR / "data_cache"
OUT_JSON = BASE_DIR / "results_metals_energy.json"

TEI_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/theory_backtest_15y_20261119"
if TEI_DIR not in sys.path:
    sys.path.insert(0, TEI_DIR)
import tei_metrics  # noqa: E402

EVAL_START = pd.Timestamp("2016-01-04")
EVAL_END = pd.Timestamp("2026-11-20")
LAST_5Y_START = pd.Timestamp("2021-11-22")
LAST_3Y_START = pd.Timestamp("2023-11-20")
FEE_ONE_WAY = 0.0015  # 0.15% buy + 0.15% sell = 0.30% round-trip


def clean_val(v):
    if v is None:
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        if math.isnan(v) or math.isinf(v):
            return None
        return round(float(v), 4)
    return v


def clean_obj(obj):
    if isinstance(obj, dict):
        return {k: clean_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [clean_obj(x) for x in obj]
    return clean_val(obj)


def load_aligned_data():
    ac = pd.read_parquet(DATA_DIR / "a_stocks_close.parquet")
    ao = pd.read_parquet(DATA_DIR / "a_stocks_open.parquet")
    cf = pd.read_parquet(DATA_DIR / "cn_futures_close.parquet")
    gf = pd.read_parquet(DATA_DIR / "global_futures_close.parquet")
    us = pd.read_parquet(DATA_DIR / "us_stocks_close.parquet")
    sh = pd.read_parquet(DATA_DIR / "sh000300.parquet")

    a_cal = sh.index
    us_cal = us.index

    # Drop Sunday quotes from global futures before weekday alignment
    gf_wd = gf[gf.index.dayofweek < 5].copy()
    # Mask CL_F <= 0 (2020-04-20 negative oil price -37.63) for clean return checks
    gf_wd["CL_F_CLEAN"] = gf_wd["CL_F"].where(gf_wd["CL_F"] > 0.0, np.nan)

    gf_a = gf_wd.reindex(a_cal).ffill()
    # Preserve NaN on CL_F_CLEAN on the exact 2020-04-20 anomaly day instead of ffill hiding it
    if pd.Timestamp("2020-04-20") in gf_a.index:
        gf_a.loc[pd.Timestamp("2020-04-20"), "CL_F_CLEAN"] = np.nan

    gf_us = gf_wd.reindex(us_cal).ffill()
    if pd.Timestamp("2020-04-20") in gf_us.index:
        gf_us.loc[pd.Timestamp("2020-04-20"), "CL_F_CLEAN"] = np.nan

    # Align CN futures strictly forward onto A-share calendar (never bfill SC0 before 2018-03-26)
    cf_a = cf.reindex(a_cal).ffill()

    # For indicator calculation on A-shares, forward-fill suspensions ONLY after each stock's listing date
    ac_ff = ac.copy()
    for col in ac_ff.columns:
        fv = ac_ff[col].first_valid_index()
        if fv is not None:
            ac_ff.loc[fv:, col] = ac_ff.loc[fv:, col].ffill()

    return {
        "a_cal": a_cal,
        "us_cal": us_cal,
        "ac_raw": ac,
        "ao_raw": ao,
        "ac_ff": ac_ff,
        "cf_a": cf_a,
        "gf_a": gf_a,
        "gf_us": gf_us,
        "us": us,
        "sh": sh["sh000300"],
    }


def make_ew_index(close_df: pd.DataFrame, cols: list[str]) -> pd.Series:
    rets = [close_df[c].pct_change(fill_method=None) for c in cols]
    ew_ret = pd.concat(rets, axis=1).mean(axis=1).fillna(0.0)
    return 100.0 * (1.0 + ew_ret).cumprod()


# ==============================================================================
# MODULE 1: ZigZag + 120d Local Extrema Turning Points Lead-Lag
# ==============================================================================
def extract_zigzag_pivots(s: pd.Series, cal_idx: pd.DatetimeIndex, pct: float) -> list[dict]:
    s = s.dropna()
    if len(s) < 30:
        return []
    vals = s.values.astype(float)
    dates = s.index
    pivots = []
    min_p, min_i = vals[0], 0
    max_p, max_i = vals[0], 0
    direction, start_i = 0, 0
    for i in range(1, len(vals)):
        p = vals[i]
        if p < min_p:
            min_p, min_i = p, i
        if p > max_p:
            max_p, max_i = p, i
        if p >= min_p * (1.0 + pct):
            pivots.append(("L", dates[min_i], float(min_p), min_i))
            direction, last_p, last_i, start_i = 1, p, i, i
            break
        if p <= max_p * (1.0 - pct):
            pivots.append(("H", dates[max_i], float(max_p), max_i))
            direction, last_p, last_i, start_i = -1, p, i, i
            break
    if direction == 0:
        return []
    for i in range(start_i + 1, len(vals)):
        p = vals[i]
        if direction == 1:
            if p >= last_p:
                last_p, last_i = p, i
            elif p <= last_p * (1.0 - pct):
                pivots.append(("H", dates[last_i], float(last_p), last_i))
                direction, last_p, last_i = -1, p, i
        else:
            if p <= last_p:
                last_p, last_i = p, i
            elif p >= last_p * (1.0 + pct):
                pivots.append(("L", dates[last_i], float(last_p), last_i))
                direction, last_p, last_i = 1, p, i

    out = []
    for k, (typ, dt, val, pos) in enumerate(pivots):
        w60 = vals[max(0, pos - 60):min(len(vals), pos + 61)]
        w120 = vals[max(0, pos - 120):min(len(vals), pos + 121)]
        is_121d = bool((val == np.max(w60)) if typ == "H" else (val == np.min(w60)))
        is_241d = bool((val == np.max(w120)) if typ == "H" else (val == np.min(w120)))
        cal_pos = int(cal_idx.get_loc(dt))
        swing_pct = round((val / pivots[k - 1][2] - 1.0) * 100.0, 2) if k > 0 else None
        out.append({
            "type": "Top" if typ == "H" else "Bottom",
            "typ": typ,
            "date": str(dt)[:10],
            "val": round(val, 4),
            "cal_pos": cal_pos,
            "is_121d_ext": is_121d,
            "is_241d_ext": is_241d,
            "swing_pct": swing_pct,
        })
    return out


def collapse_major_pivots(pivs: list[dict], require_121d: bool = True) -> list[dict]:
    kept = []
    for p in pivs:
        if require_121d and not p["is_121d_ext"]:
            continue
        if kept and kept[-1]["typ"] == p["typ"]:
            if (p["typ"] == "H" and p["val"] > kept[-1]["val"]) or (p["typ"] == "L" and p["val"] < kept[-1]["val"]):
                kept[-1] = dict(p)
        else:
            kept.append(dict(p))
    for k in range(len(kept)):
        kept[k]["swing_pct"] = round((kept[k]["val"] / kept[k - 1]["val"] - 1.0) * 100.0, 2) if k > 0 else None
    return kept


def dp_match_turning_points(comm_pivs: list[dict], stk_pivs: list[dict], max_lag: int = 180) -> list[tuple]:
    c_major = collapse_major_pivots(comm_pivs, require_121d=True)
    m, k = len(c_major), len(stk_pivs)
    dp = [[(0.0, None) for _ in range(k + 1)] for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, k + 1):
            best = (dp[i - 1][j][0], ("skip_c", i - 1, j))
            if dp[i][j - 1][0] > best[0]:
                best = (dp[i][j - 1][0], ("skip_s", i, j - 1))
            cp, sp = c_major[i - 1], stk_pivs[j - 1]
            if cp["typ"] == sp["typ"]:
                diff = cp["cal_pos"] - sp["cal_pos"]
                if abs(diff) <= max_lag:
                    score = 1.0 + (0.25 if sp["is_121d_ext"] else 0.0) + (0.15 if (cp["is_241d_ext"] and sp["is_241d_ext"]) else 0.0) - 0.9 * abs(diff) / float(max_lag)
                    val = dp[i - 1][j - 1][0] + score
                    if val > best[0]:
                        best = (val, ("match", i - 1, j - 1))
            dp[i][j] = best

    pairs = {}
    i, j = m, k
    while i > 0 and j > 0:
        act, ni, nj = dp[i][j][1]
        if act == "match":
            pairs[ni] = stk_pivs[nj]
        i, j = ni, nj

    res = []
    for i, cp in enumerate(c_major):
        sp = pairs.get(i)
        diff = int(cp["cal_pos"] - sp["cal_pos"]) if sp is not None else None
        res.append((cp, sp, diff))
    return res


def rolling_local_extrema_series(s: pd.Series, cal_idx: pd.DatetimeIndex, half_win: int = 60) -> list[dict]:
    s = s.dropna()
    vals = s.values.astype(float)
    dates = s.index
    raw = []
    for i in range(len(vals)):
        if i < 15 or i > len(vals) - 16:
            continue
        win = vals[max(0, i - half_win):min(len(vals), i + half_win + 1)]
        if vals[i] == np.max(win):
            raw.append({"typ": "H", "type": "Top", "date": str(dates[i])[:10], "val": round(float(vals[i]), 4), "cal_pos": int(cal_idx.get_loc(dates[i]))})
        elif vals[i] == np.min(win):
            raw.append({"typ": "L", "type": "Bottom", "date": str(dates[i])[:10], "val": round(float(vals[i]), 4), "cal_pos": int(cal_idx.get_loc(dates[i]))})
    # Deduplicate consecutive identical extrema within 10 trading days
    dedup = []
    for r in raw:
        if dedup and dedup[-1]["typ"] == r["typ"] and (r["cal_pos"] - dedup[-1]["cal_pos"]) <= 10:
            if (r["typ"] == "H" and r["val"] > dedup[-1]["val"]) or (r["typ"] == "L" and r["val"] < dedup[-1]["val"]):
                dedup[-1] = r
        else:
            dedup.append(r)
    return dedup


def analyze_turning_points(comm_s: pd.Series, stk_s: pd.Series, cal_idx: pd.DatetimeIndex, c_th: float, s_th: float) -> dict:
    # Restrict stock/commodity comparison to overlapping valid calendar range
    start_dt = max(comm_s.dropna().index.min(), stk_s.dropna().index.min())
    c_sub = comm_s.loc[start_dt:]
    s_sub = stk_s.loc[start_dt:]
    pc = extract_zigzag_pivots(c_sub, cal_idx, c_th)
    ps = extract_zigzag_pivots(s_sub, cal_idx, s_th)
    matched = dp_match_turning_points(pc, ps, max_lag=180)

    waves = []
    b_leads, t_leads = [], []
    b_unm, t_unm = 0, 0
    for cp, sp, diff in matched:
        w = {
            "type": cp["type"],
            "comm_date": cp["date"],
            "comm_val": cp["val"],
            "comm_swing_pct": cp["swing_pct"],
            "comm_is_241d_ext": cp["is_241d_ext"],
            "stock_date": sp["date"] if sp else None,
            "stock_val": sp["val"] if sp else None,
            "stock_swing_pct": sp["swing_pct"] if sp else None,
            "stock_is_121d_ext": sp["is_121d_ext"] if sp else None,
            "lead_days": diff,
        }
        waves.append(w)
        if diff is not None:
            if cp["typ"] == "L":
                b_leads.append(diff)
            else:
                t_leads.append(diff)
        else:
            if cp["typ"] == "L":
                b_unm += 1
            else:
                t_unm += 1

    # Independent 120d centered local extrema cross-check (±60d = 121d window, ±120d = 241d window)
    ext_c_121 = rolling_local_extrema_series(c_sub, cal_idx, half_win=60)
    ext_s_121 = rolling_local_extrema_series(s_sub, cal_idx, half_win=60)
    # Match ±120d extrema (241d window) as secondary robustness check
    ext_c_241 = rolling_local_extrema_series(c_sub, cal_idx, half_win=120)
    ext_s_241 = rolling_local_extrema_series(s_sub, cal_idx, half_win=120)

    def summarize(arr):
        if not arr:
            return {"n": 0, "median": None, "mean": None, "min": None, "max": None, "pct_stock_leads": None}
        return {
            "n": len(arr),
            "median": round(float(np.median(arr)), 1),
            "mean": round(float(np.mean(arr)), 1),
            "min": int(min(arr)),
            "max": int(max(arr)),
            "pct_stock_leads": round(float(np.mean([x > 0 for x in arr]) * 100.0), 1),
        }

    # Cross-check DP match on pure 121d local extrema
    def quick_ext_leads(ec, es):
        b, t = [], []
        for c_e in ec:
            cands = [c_e["cal_pos"] - s_e["cal_pos"] for s_e in es if s_e["typ"] == c_e["typ"] and abs(c_e["cal_pos"] - s_e["cal_pos"]) <= 180]
            if cands:
                best = min(cands, key=abs)
                if c_e["typ"] == "L":
                    b.append(best)
                else:
                    t.append(best)
        return {"bottoms": summarize(b), "tops": summarize(t)}

    return {
        "overlap_start": str(start_dt)[:10],
        "comm_zigzag_pct": round(c_th * 100, 1),
        "stock_zigzag_pct": round(s_th * 100, 1),
        "waves": waves,
        "summary": {
            "bottoms": {**summarize(b_leads), "unmatched_n": b_unm},
            "tops": {**summarize(t_leads), "unmatched_n": t_unm},
            "all_matched": summarize(b_leads + t_leads),
        },
        "local_extrema_crosscheck": {
            "win_121d_leads": quick_ext_leads(ext_c_121, ext_s_121),
            "win_241d_leads": quick_ext_leads(ext_c_241, ext_s_241),
            "comm_241d_extrema": [{"type": x["type"], "date": x["date"], "val": x["val"]} for x in ext_c_241],
            "stock_241d_extrema": [{"type": x["type"], "date": x["date"], "val": x["val"]} for x in ext_s_241],
        },
    }


# ==============================================================================
# MODULE 2: Cross-Correlation Scan [-180, +180]
# ==============================================================================
def corr_stats(r: float, n_obs: int, ret_win: int) -> tuple[float | None, float | None, bool, float]:
    n_eff = float(n_obs) / float(ret_win)
    if n_eff <= 2.5 or r is None or not np.isfinite(r):
        return None, None, False, round(n_eff, 2)
    if abs(r) >= 0.999999:
        return 99.0 if r > 0 else -99.0, 0.0, True, round(n_eff, 2)
    df = n_eff - 2.0
    t_stat = float(r * math.sqrt(df / (1.0 - r * r)))
    p_val = float(2.0 * stats.t.sf(abs(t_stat), df=df))
    return round(t_stat, 3), round(p_val, 4), bool(p_val < 0.05), round(n_eff, 2)


def compute_cross_corr(stk_s: pd.Series, comm_s: pd.Series, ret_win: int = 60, eval_start: pd.Timestamp = EVAL_START) -> dict:
    sr = stk_s.pct_change(ret_win, fill_method=None)
    cr = comm_s.pct_change(ret_win, fill_method=None)
    sr_eval = sr.loc[eval_start:]

    all_lags = list(range(-180, 181))
    corrs_all = {}
    nobs_all = {}
    for k in all_lags:
        # k > 0 => corr(stock_ret(t), comm_ret(t+k)) => stock leads commodity by k days
        cr_shifted = cr.shift(-k).reindex(sr_eval.index)
        pair = pd.concat([sr_eval, cr_shifted], axis=1).dropna()
        n = len(pair)
        nobs_all[k] = n
        if n >= max(60, ret_win + 10):
            corrs_all[k] = float(pair.iloc[:, 0].corr(pair.iloc[:, 1]))
        else:
            corrs_all[k] = np.nan

    valid_ks = [k for k in all_lags if np.isfinite(corrs_all[k])]
    if not valid_ks:
        return {"error": "insufficient_overlap"}

    # Peak overall
    peak_k = max(valid_ks, key=lambda k: corrs_all[k])
    peak_r = corrs_all[peak_k]
    peak_t, peak_p, peak_sig, peak_neff = corr_stats(peak_r, nobs_all[peak_k], ret_win)

    # Lag 0
    lag0_r = corrs_all.get(0, np.nan)
    lag0_t, lag0_p, lag0_sig, lag0_neff = corr_stats(lag0_r, nobs_all.get(0, 0), ret_win)

    # Lead region [1, 180] (stock leads commodity)
    lead_ks = [k for k in valid_ks if k >= 1]
    lead_k = max(lead_ks, key=lambda k: corrs_all[k])
    lead_r = corrs_all[lead_k]
    lead_t, lead_p, lead_sig, _ = corr_stats(lead_r, nobs_all[lead_k], ret_win)

    # Lag region [-180, -1] (commodity leads stock)
    lag_ks = [k for k in valid_ks if k <= -1]
    lag_k = max(lag_ks, key=lambda k: corrs_all[k])
    lag_r = corrs_all[lag_k]
    lag_t, lag_p, lag_sig, _ = corr_stats(lag_r, nobs_all[lag_k], ret_win)

    # Overlap metadata at lag 0
    pair0 = pd.concat([sr_eval, cr.reindex(sr_eval.index)], axis=1).dropna()
    lags_5d = list(range(-180, 181, 5))
    corrs_5d = [round(corrs_all[k], 4) if np.isfinite(corrs_all[k]) else None for k in lags_5d]

    return {
        "ret_window": ret_win,
        "overlap_start": str(pair0.index.min())[:10],
        "overlap_end": str(pair0.index.max())[:10],
        "n_obs_lag0": int(nobs_all[0]),
        "n_eff_lag0": lag0_neff,
        "lag0_corr": round(lag0_r, 4) if np.isfinite(lag0_r) else None,
        "lag0_t_stat": lag0_t,
        "lag0_p_val": lag0_p,
        "lag0_sig_5pct": lag0_sig,
        "peak_lag_days": int(peak_k),
        "peak_corr": round(peak_r, 4),
        "peak_n_eff": peak_neff,
        "peak_t_stat": peak_t,
        "peak_p_val": peak_p,
        "peak_sig_5pct": peak_sig,
        "lead_peak_lag_days": int(lead_k),
        "lead_peak_corr": round(lead_r, 4),
        "lead_peak_t_stat": lead_t,
        "lead_peak_p_val": lead_p,
        "lead_peak_sig_5pct": lead_sig,
        "lag_peak_lag_days": int(lag_k),
        "lag_peak_corr": round(lag_r, 4),
        "lag_peak_t_stat": lag_t,
        "lag_peak_p_val": lag_p,
        "lag_peak_sig_5pct": lag_sig,
        "curve_5d": {"lags": lags_5d, "corrs": corrs_5d},
    }


# ==============================================================================
# MODULE 3: Strictly PIT t+1 Open Execution Backtest
# ==============================================================================
def build_signals(stk_close_ff: pd.Series, comm_close: pd.Series, strategy: str, gold_adapt: bool = False) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Compute strictly causal signals using data <= t close."""
    comm_q756 = comm_close.rolling(756, min_periods=180).rank(pct=True)
    comm_max252 = comm_close.rolling(252, min_periods=60).max()
    comm_dd252 = comm_close / comm_max252 - 1.0
    comm_min252_prev = comm_close.shift(1).rolling(252, min_periods=60).min()
    comm_new_low_252 = comm_close < comm_min252_prev

    comm_ma60 = comm_close.rolling(60, min_periods=60).mean()
    comm_ret60 = comm_close.pct_change(60, fill_method=None)
    comm_ret20 = comm_close.pct_change(20, fill_method=None)

    stk_ma60 = stk_close_ff.rolling(60, min_periods=60).mean()
    stk_ma20 = stk_close_ff.rolling(20, min_periods=20).mean()
    stk_ret20 = stk_close_ff.pct_change(20, fill_method=None)

    if strategy == "A":
        q_th = 0.35 if gold_adapt else 0.25
        dd_th = -0.10 if gold_adapt else -0.25
        in_trough = (comm_q756 < q_th) | (comm_dd252 <= dd_th)
        entry = in_trough & (stk_close_ff > stk_ma60) & (stk_ret20 > comm_ret20)
        below_ma60 = stk_close_ff < stk_ma60
        below_ma60_3d = below_ma60 & below_ma60.shift(1, fill_value=False) & below_ma60.shift(2, fill_value=False)
        exit_sig = ((comm_q756 > 0.85) & (stk_close_ff < stk_ma20)) | below_ma60_3d
        return entry.fillna(False), exit_sig.fillna(False), comm_new_low_252.fillna(False)

    if strategy == "A2":
        entry = comm_q756 < 0.20
        exit_sig = comm_q756 > 0.80  # plus dynamic 252d hold + new low check inside engine
        return entry.fillna(False), exit_sig.fillna(False), comm_new_low_252.fillna(False)

    if strategy == "B":
        entry = (comm_close > comm_ma60) & (comm_ret60 > 0.05)
        exit_sig = comm_close < comm_ma60
        return entry.fillna(False), exit_sig.fillna(False), comm_new_low_252.fillna(False)

    raise ValueError(f"Unknown strategy: {strategy}")


def run_pit_backtest(
    a_cal: pd.DatetimeIndex,
    tickers: list[str],
    ao_raw: pd.DataFrame,
    ac_raw: pd.DataFrame,
    ac_ff: pd.DataFrame,
    stk_sig_series: pd.Series,
    comm_s: pd.Series,
    strategy: str,
    start_dt: pd.Timestamp,
    gold_adapt: bool = False,
) -> dict:
    """
    Strictly PIT execution: signal observed at day t-1 close -> executed at day t open.
    Handles stock suspensions (open[t] NaN) realistically without phantom fills.
    Computes daily portfolio NAV and closed/MTM trade records with 0.15% buy + 0.15% sell fee.
    """
    start_pos = int(a_cal.searchsorted(start_dt))
    n_total = len(a_cal)
    eval_dates = a_cal[start_pos:]
    daily_ret = pd.Series(0.0, index=eval_dates)
    active_mask = pd.Series(0.0, index=eval_dates)

    if strategy == "C":
        # Buy & Hold from start_dt open (or first non-suspended open) to EVAL_END close
        cash = 1.0
        holdings = {}  # ticker -> dollar value
        nav = 1.0
        prev_nav = 1.0
        first_buy_date = None
        for i in range(start_pos, n_total):
            dt = a_cal[i]
            prev_dt = a_cal[i - 1]
            # Require ticker to have open/close today; if post-2016 IPO (e.g. 600938.SH), require prev_dt close so IPO day1 isn't magically front-run
            tradable_now = [
                t for t in tickers
                if pd.notna(ao_raw.loc[dt, t]) and pd.notna(ac_raw.loc[dt, t])
                and (i == start_pos or pd.notna(ac_ff.loc[prev_dt, t]))
            ]
            if not holdings:
                # Wait until at least one ticker is tradable (handles 600988.SH suspended on 2016-01-04)
                if tradable_now:
                    w = 1.0 / len(tradable_now)
                    for t in tradable_now:
                        o_p = float(ao_raw.loc[dt, t])
                        c_p = float(ac_raw.loc[dt, t])
                        holdings[t] = cash * w * (1.0 - FEE_ONE_WAY) * (c_p / o_p)
                    cash = 0.0
                    first_buy_date = str(dt)[:10]
                    nav = sum(holdings.values())
                    active_mask.loc[dt] = 1.0
            else:
                new_t = [t for t in tradable_now if t not in holdings]
                if new_t:
                    # Rebalance equally at day dt open across existing holdings + newly listed/resumed ticker
                    open_vals = {}
                    for t, val in holdings.items():
                        prev_c = float(ac_ff.loc[prev_dt, t])
                        o_p = ao_raw.loc[dt, t]
                        open_vals[t] = val * (float(o_p) / prev_c) if pd.notna(o_p) else val
                    tot_open = sum(open_vals.values())
                    all_t = list(holdings.keys()) + new_t
                    target_w = 1.0 / len(all_t)
                    moved = sum(abs(tot_open * target_w - open_vals.get(t, 0.0)) for t in all_t)
                    scale = (tot_open - moved * FEE_ONE_WAY) / tot_open
                    new_holdings = {}
                    for t in all_t:
                        o_p = ao_raw.loc[dt, t]
                        c_p = ac_raw.loc[dt, t]
                        if pd.notna(o_p) and pd.notna(c_p):
                            new_holdings[t] = (tot_open * target_w * scale) * (float(c_p) / float(o_p))
                        else:
                            new_holdings[t] = open_vals.get(t, 0.0)
                    holdings = new_holdings
                    nav = cash + sum(holdings.values())
                else:
                    for t in list(holdings.keys()):
                        c_p = ac_raw.loc[dt, t]
                        prev_c = ac_ff.loc[prev_dt, t]
                        if pd.notna(c_p) and pd.notna(prev_c):
                            holdings[t] = holdings[t] * (float(c_p) / float(prev_c))
                    nav = cash + sum(holdings.values())
                active_mask.loc[dt] = 1.0

            daily_ret.loc[dt] = (nav / prev_nav - 1.0) if prev_nav > 0 else 0.0
            prev_nav = nav

        tot_mult = nav * (1.0 - FEE_ONE_WAY)
        trades = [{
            "entry_date": first_buy_date or str(a_cal[start_pos])[:10],
            "exit_date": f"{str(a_cal[-1])[:10]} (MTM)",
            "exit_dt_raw": str(a_cal[-1])[:10],
            "target": "+".join(tickers) if len(tickers) > 1 else tickers[0],
            "net_ret_pct": round((tot_mult - 1.0) * 100.0, 2),
            "holding_days": int(n_total - start_pos),
            "is_open": True,
        }]
        return {"daily_ret": daily_ret, "active_mask": active_mask, "trades": trades, "nav": (1.0 + daily_ret).cumprod()}

    entry_sig, exit_sig, comm_new_low_252 = build_signals(stk_sig_series, comm_s, strategy, gold_adapt=gold_adapt)

    pos = False
    pending_exit = False
    cash = 1.0
    holdings = {}  # ticker -> float value
    nav = 1.0
    prev_nav = 1.0
    hold_days = 0
    entry_nav_before_buy = 1.0
    entry_date_str = None
    entry_tickers = []
    trades = []

    for i in range(start_pos, n_total):
        dt = a_cal[i]
        prev_dt = a_cal[i - 1]

        sig_in = bool(entry_sig.loc[prev_dt])
        sig_out = bool(exit_sig.loc[prev_dt])
        if strategy == "A2" and pos and hold_days >= 252 and bool(comm_new_low_252.loc[prev_dt]):
            sig_out = True

        if not pos:
            if sig_in and not sig_out:
                tradable = [
                    t for t in tickers
                    if pd.notna(ao_raw.loc[dt, t]) and pd.notna(ac_raw.loc[dt, t])
                    and pd.notna(ac_ff.loc[prev_dt, t])
                ]
                if tradable:
                    pos = True
                    pending_exit = False
                    hold_days = 1
                    entry_nav_before_buy = cash
                    entry_date_str = str(dt)[:10]
                    entry_tickers = list(tradable)
                    w = 1.0 / len(tradable)
                    holdings = {}
                    for t in tradable:
                        o_p = float(ao_raw.loc[dt, t])
                        c_p = float(ac_raw.loc[dt, t])
                        holdings[t] = cash * w * (1.0 - FEE_ONE_WAY) * (c_p / o_p)
                    cash = 0.0
                    nav = sum(holdings.values())
                    active_mask.loc[dt] = 1.0
        else:
            if sig_out:
                pending_exit = True
            if pending_exit:
                # Sell any non-suspended ticker at dt open into persistent `cash`
                for t in list(holdings.keys()):
                    o_p = ao_raw.loc[dt, t]
                    prev_c = ac_ff.loc[prev_dt, t]
                    if pd.notna(o_p) and pd.notna(prev_c):
                        val = holdings.pop(t)
                        cash += val * (float(o_p) / float(prev_c)) * (1.0 - FEE_ONE_WAY)
                if not holdings:
                    nav = cash
                    pos = False
                    pending_exit = False
                    trades.append({
                        "entry_date": entry_date_str,
                        "exit_date": str(dt)[:10],
                        "exit_dt_raw": str(dt)[:10],
                        "target": "+".join(entry_tickers) if len(entry_tickers) > 1 else entry_tickers[0],
                        "net_ret_pct": round((nav / entry_nav_before_buy - 1.0) * 100.0, 2),
                        "holding_days": int(hold_days),
                        "is_open": False,
                    })
                    hold_days = 0
                else:
                    # Suspended leg remains held at prior close while sold leg sits in cash
                    nav = cash + sum(holdings.values())
                    active_mask.loc[dt] = 1.0
                    hold_days += 1
            else:
                for t in list(holdings.keys()):
                    c_p = ac_raw.loc[dt, t]
                    prev_c = ac_ff.loc[prev_dt, t]
                    if pd.notna(c_p) and pd.notna(prev_c):
                        holdings[t] = holdings[t] * (float(c_p) / float(prev_c))
                nav = cash + sum(holdings.values())
                active_mask.loc[dt] = 1.0
                hold_days += 1

        daily_ret.loc[dt] = (nav / prev_nav - 1.0) if prev_nav > 0 else 0.0
        prev_nav = nav

    if pos:
        mtm_nav = cash + sum(holdings.values()) * (1.0 - FEE_ONE_WAY)
        trades.append({
            "entry_date": entry_date_str,
            "exit_date": f"{str(a_cal[-1])[:10]} (MTM)",
            "exit_dt_raw": str(a_cal[-1])[:10],
            "target": "+".join(entry_tickers) if len(entry_tickers) > 1 else entry_tickers[0],
            "net_ret_pct": round((mtm_nav / entry_nav_before_buy - 1.0) * 100.0, 2),
            "holding_days": int(hold_days),
            "is_open": True,
        })

    return {"daily_ret": daily_ret, "active_mask": active_mask, "trades": trades, "nav": (1.0 + daily_ret).cumprod()}


def compute_window_metrics(
    strat_ret: pd.Series,
    active_mask: pd.Series,
    hs300_ret: pd.Series,
    bh_ret: pd.Series,
    trades: list[dict],
    nav_series: pd.Series,
    w_start: pd.Timestamp,
    w_end: pd.Timestamp,
) -> dict:
    s_sub = strat_ret.loc[w_start:w_end].dropna()
    if len(s_sub) < 20:
        return {"n_days": int(len(s_sub)), "insufficient": True}
    b_hs = hs300_ret.reindex(s_sub.index).fillna(0.0)
    b_bh = bh_ret.reindex(s_sub.index).fillna(0.0)
    act = active_mask.reindex(s_sub.index).fillna(0.0)

    m_hs = tei_metrics.compute_period_metrics(s_sub, b_hs, act)
    m_bh = tei_metrics.compute_period_metrics(s_sub, b_bh, act)
    total_ret = (float((1.0 + s_sub).prod()) - 1.0) * 100.0

    # Trade stats for trades active in [w_start, w_end]
    w_start_s = str(s_sub.index[0])[:10]
    w_end_s = str(s_sub.index[-1])[:10]
    entered_n = 0
    win_rets, loss_rets = [], []
    all_window_rets = []
    for tr in trades:
        ed = tr["entry_date"]
        xd = tr["exit_dt_raw"]
        if xd < w_start_s or ed > w_end_s:
            continue
        if ed >= w_start_s:
            entered_n += 1
            r = tr["net_ret_pct"]
        else:
            # Trade entered before window start: compute window-sliced MTM return using NAV
            idx_pos = nav_series.index.searchsorted(pd.Timestamp(w_start_s))
            base_nav = float(nav_series.iloc[idx_pos - 1]) if idx_pos > 0 else 1.0
            end_ts = min(pd.Timestamp(xd), pd.Timestamp(w_end_s))
            end_pos = min(len(nav_series) - 1, nav_series.index.searchsorted(end_ts))
            end_nav = float(nav_series.iloc[end_pos])
            r = (end_nav / base_nav - 1.0) * 100.0 if base_nav > 0 else 0.0
        all_window_rets.append(r)
        if r > 0:
            win_rets.append(r)
        else:
            loss_rets.append(r)

    trades_n = len(all_window_rets)
    win_rate = (len(win_rets) / trades_n * 100.0) if trades_n > 0 else None
    avg_win = float(np.mean(win_rets)) if win_rets else None
    avg_loss = abs(float(np.mean(loss_rets))) if loss_rets else None
    if trades_n == 0:
        pl_ratio = None
    elif avg_loss is None or avg_loss < 1e-9:
        pl_ratio = None  # zero losing trades
    elif avg_win is None:
        pl_ratio = 0.0
    else:
        pl_ratio = avg_win / avg_loss

    return {
        "start_date": w_start_s,
        "end_date": w_end_s,
        "n_days": m_hs["n_days"],
        "total_ret_pct": round(total_ret, 2),
        "cagr_pct": m_hs["ann_ret"],
        "mdd_pct": m_hs["mdd"],
        "sharpe": m_hs["sharpe"],
        "calmar": m_hs["calmar"],
        "trades_n": int(trades_n),
        "trades_entered_n": int(entered_n),
        "win_rate_pct": round(win_rate, 1) if win_rate is not None else None,
        "pl_ratio": round(pl_ratio, 2) if pl_ratio is not None else None,
        "exposure_pct": m_hs["exposure_pct"],
        "excess_vs_hs300_ann_pct": m_hs["excess_ann"],
        "excess_vs_bh_ann_pct": m_bh["excess_ann"],
        "tei": m_hs["tei"],
        "tei_vs_bh": m_bh["tei"],
        "ir_vs_hs300": m_hs["ir"],
        "ir_vs_bh": m_bh["ir"],
    }


def summarize_backtest(res: dict, hs300_ret: pd.Series, bh_ret: pd.Series, full_start: pd.Timestamp) -> dict:
    dr = res["daily_ret"]
    act = res["active_mask"]
    trs = res["trades"]
    nav = res["nav"]

    periods = {
        "full": compute_window_metrics(dr, act, hs300_ret, bh_ret, trs, nav, full_start, EVAL_END),
        "last_5y": compute_window_metrics(dr, act, hs300_ret, bh_ret, trs, nav, max(full_start, LAST_5Y_START), EVAL_END),
        "last_3y": compute_window_metrics(dr, act, hs300_ret, bh_ret, trs, nav, max(full_start, LAST_3Y_START), EVAL_END),
    }

    sorted_abs = sorted(trs, key=lambda x: abs(x["net_ret_pct"]), reverse=True)[:5]
    sorted_best = sorted(trs, key=lambda x: x["net_ret_pct"], reverse=True)[:5]
    sorted_worst = sorted(trs, key=lambda x: x["net_ret_pct"])[:5]

    def fmt_tr(t):
        return {
            "entry_date": t["entry_date"],
            "exit_date": t["exit_date"],
            "target": t["target"],
            "net_ret_pct": t["net_ret_pct"],
            "holding_days": t["holding_days"],
            "is_open": t["is_open"],
        }

    return {
        "periods": periods,
        "extreme_trades_top5_abs": [fmt_tr(t) for t in sorted_abs],
        "top5_best_trades": [fmt_tr(t) for t in sorted_best],
        "top5_worst_trades": [fmt_tr(t) for t in sorted_worst],
    }


def main():
    data = load_aligned_data()
    a_cal = data["a_cal"]
    us_cal = data["us_cal"]
    ac_raw, ao_raw, ac_ff = data["ac_raw"], data["ao_raw"], data["ac_ff"]
    cf_a, gf_a, gf_us, us = data["cf_a"], data["gf_a"], data["gf_us"], data["us"]
    hs300 = data["sh"]
    hs300_ret = hs300.pct_change().loc[EVAL_START:EVAL_END]

    # Build A-share & US equal-weight indices
    gold_ew = make_ew_index(ac_ff, ["600547.SH", "600988.SH"])
    copper_ew = make_ew_index(ac_ff, ["601899.SH", "603993.SH"])
    oil_ew = make_ew_index(ac_ff, ["601857.SH", "600938.SH"])
    us_gold_ew = make_ew_index(us, ["NEM", "RGLD"])

    # Determine actual 60d-warmup backtest start for late-listing series
    # 600938.SH listed 2022-04-21 -> 60th trading day:
    s938_dates = ac_raw["600938.SH"].dropna().index
    s938_bt_start = s938_dates[59]  # ~2022-07-19
    # SC0 listed 2018-03-26 -> 180th trading day for 756d quantile min_periods=180 (and 60d for MA60):
    sc0_dates = cf_a["SC0"].dropna().index
    sc0_bt_start = sc0_dates[180]   # ~2018-12-18 (first day q756(min_periods=180) is non-NaN)

    # ------------------------------------------------------------------
    # MODULE 1: Turning Points
    # ------------------------------------------------------------------
    m1_specs = {
        "gold": [
            ("GOLD_A_EW_vs_AU0", cf_a["AU0"], gold_ew, a_cal, 0.12, 0.22),
            ("GOLD_A_EW_vs_GC_F", gf_a["GC_F"], gold_ew, a_cal, 0.12, 0.22),
            ("600547.SH_vs_AU0", cf_a["AU0"], ac_ff["600547.SH"], a_cal, 0.12, 0.22),
            ("600988.SH_vs_AU0", cf_a["AU0"], ac_ff["600988.SH"], a_cal, 0.12, 0.22),
            ("600547.SH_vs_GC_F", gf_a["GC_F"], ac_ff["600547.SH"], a_cal, 0.12, 0.22),
            ("600988.SH_vs_GC_F", gf_a["GC_F"], ac_ff["600988.SH"], a_cal, 0.12, 0.22),
            ("US_NEM_vs_GC_F", gf_us["GC_F"], us["NEM"], us_cal, 0.12, 0.22),
            ("US_RGLD_vs_GC_F", gf_us["GC_F"], us["RGLD"], us_cal, 0.12, 0.22),
            ("US_GOLD_EW_vs_GC_F", gf_us["GC_F"], us_gold_ew, us_cal, 0.12, 0.22),
        ],
        "copper": [
            ("COPPER_A_EW_vs_CU0", cf_a["CU0"], copper_ew, a_cal, 0.20, 0.25),
            ("COPPER_A_EW_vs_HG_F", gf_a["HG_F"], copper_ew, a_cal, 0.20, 0.25),
            ("601899.SH_vs_CU0", cf_a["CU0"], ac_ff["601899.SH"], a_cal, 0.20, 0.25),
            ("603993.SH_vs_CU0", cf_a["CU0"], ac_ff["603993.SH"], a_cal, 0.20, 0.25),
            ("601899.SH_vs_HG_F", gf_a["HG_F"], ac_ff["601899.SH"], a_cal, 0.20, 0.25),
            ("603993.SH_vs_HG_F", gf_a["HG_F"], ac_ff["603993.SH"], a_cal, 0.20, 0.25),
            ("US_FCX_vs_HG_F", gf_us["HG_F"], us["FCX"], us_cal, 0.20, 0.25),
        ],
        "oil": [
            ("OIL_A_EW_vs_BZ_F", gf_a["BZ_F"], oil_ew, a_cal, 0.20, 0.25),
            ("OIL_A_EW_vs_SC0", cf_a["SC0"], oil_ew, a_cal, 0.20, 0.25),
            ("601857.SH_vs_BZ_F", gf_a["BZ_F"], ac_ff["601857.SH"], a_cal, 0.20, 0.25),
            ("601857.SH_vs_SC0", cf_a["SC0"], ac_ff["601857.SH"], a_cal, 0.20, 0.25),
            ("600938.SH_vs_BZ_F", gf_a["BZ_F"], ac_ff["600938.SH"], a_cal, 0.20, 0.25),
            ("600938.SH_vs_SC0", cf_a["SC0"], ac_ff["600938.SH"], a_cal, 0.20, 0.25),
            ("US_XOM_vs_BZ_F", gf_us["BZ_F"], us["XOM"], us_cal, 0.20, 0.25),
        ],
    }
    module1 = {}
    for grp, specs in m1_specs.items():
        module1[grp] = {}
        for label, cs, ss, cal, c_th, s_th in specs:
            module1[grp][label] = analyze_turning_points(cs, ss, cal, c_th, s_th)

    # ------------------------------------------------------------------
    # MODULE 2: Cross-Correlation Scan [-180, +180]
    # ------------------------------------------------------------------
    m2_specs = {
        "gold": [
            ("GOLD_A_EW_vs_AU0", gold_ew, cf_a["AU0"]),
            ("GOLD_A_EW_vs_GC_F", gold_ew, gf_a["GC_F"]),
            ("600547.SH_vs_AU0", ac_ff["600547.SH"], cf_a["AU0"]),
            ("600988.SH_vs_AU0", ac_ff["600988.SH"], cf_a["AU0"]),
            ("600547.SH_vs_GC_F", ac_ff["600547.SH"], gf_a["GC_F"]),
            ("600988.SH_vs_GC_F", ac_ff["600988.SH"], gf_a["GC_F"]),
            ("US_NEM_vs_GC_F", us["NEM"], gf_us["GC_F"]),
            ("US_RGLD_vs_GC_F", us["RGLD"], gf_us["GC_F"]),
            ("US_GOLD_EW_vs_GC_F", us_gold_ew, gf_us["GC_F"]),
        ],
        "copper": [
            ("COPPER_A_EW_vs_CU0", copper_ew, cf_a["CU0"]),
            ("COPPER_A_EW_vs_HG_F", copper_ew, gf_a["HG_F"]),
            ("601899.SH_vs_CU0", ac_ff["601899.SH"], cf_a["CU0"]),
            ("603993.SH_vs_CU0", ac_ff["603993.SH"], cf_a["CU0"]),
            ("601899.SH_vs_HG_F", ac_ff["601899.SH"], gf_a["HG_F"]),
            ("603993.SH_vs_HG_F", ac_ff["603993.SH"], gf_a["HG_F"]),
            ("US_FCX_vs_HG_F", us["FCX"], gf_us["HG_F"]),
        ],
        "oil": [
            ("OIL_A_EW_vs_BZ_F", oil_ew, gf_a["BZ_F"]),
            ("OIL_A_EW_vs_SC0", oil_ew, cf_a["SC0"]),
            ("OIL_A_EW_vs_CL_F_clean", oil_ew, gf_a["CL_F_CLEAN"]),
            ("601857.SH_vs_BZ_F", ac_ff["601857.SH"], gf_a["BZ_F"]),
            ("601857.SH_vs_SC0", ac_ff["601857.SH"], cf_a["SC0"]),
            ("600938.SH_vs_BZ_F", ac_ff["600938.SH"], gf_a["BZ_F"]),
            ("600938.SH_vs_SC0", ac_ff["600938.SH"], cf_a["SC0"]),
            ("US_XOM_vs_BZ_F", us["XOM"], gf_us["BZ_F"]),
            ("US_XOM_vs_CL_F_clean", us["XOM"], gf_us["CL_F_CLEAN"]),
        ],
    }
    module2 = {}
    for grp, specs in m2_specs.items():
        module2[grp] = {}
        for label, ss, cs in specs:
            module2[grp][label] = {
                "ret_60d": compute_cross_corr(ss, cs, ret_win=60, eval_start=EVAL_START),
                "ret_20d": compute_cross_corr(ss, cs, ret_win=20, eval_start=EVAL_START),
            }

    # ------------------------------------------------------------------
    # MODULE 3: Strictly PIT t+1 Open Execution Backtest
    # ------------------------------------------------------------------
    # Benchmark HS300 metrics on full_10y, last_5y, last_3y, plus CNOOC & SC0 subwindows
    def hs_stats(st):
        sub = hs300_ret.loc[st:EVAL_END]
        m = tei_metrics.compute_period_metrics(sub, sub)
        return {
            "start_date": str(sub.index[0])[:10],
            "end_date": str(sub.index[-1])[:10],
            "n_days": m["n_days"],
            "total_ret_pct": round((float((1.0 + sub).prod()) - 1.0) * 100.0, 2),
            "cagr_pct": m["ann_ret"],
            "mdd_pct": m["mdd"],
            "sharpe": m["sharpe"],
            "calmar": m["calmar"],
        }

    benchmarks = {
        "sh000300_full_10y": hs_stats(EVAL_START),
        "sh000300_last_5y": hs_stats(LAST_5Y_START),
        "sh000300_last_3y": hs_stats(LAST_3Y_START),
        "sh000300_since_2022_07_19": hs_stats(s938_bt_start),
        "sh000300_since_2018_12_18": hs_stats(sc0_bt_start),
    }

    m3_specs = {
        "gold": [
            ("GOLD_A_EW", ["600547.SH", "600988.SH"], gold_ew, "AU0", cf_a["AU0"], EVAL_START, True),
            ("600547.SH", ["600547.SH"], ac_ff["600547.SH"], "AU0", cf_a["AU0"], EVAL_START, True),
            ("600988.SH", ["600988.SH"], ac_ff["600988.SH"], "AU0", cf_a["AU0"], EVAL_START, True),
            ("GOLD_A_EW", ["600547.SH", "600988.SH"], gold_ew, "GC_F", gf_a["GC_F"], EVAL_START, True),
            ("600547.SH", ["600547.SH"], ac_ff["600547.SH"], "GC_F", gf_a["GC_F"], EVAL_START, True),
            ("600988.SH", ["600988.SH"], ac_ff["600988.SH"], "GC_F", gf_a["GC_F"], EVAL_START, True),
        ],
        "copper": [
            ("COPPER_A_EW", ["601899.SH", "603993.SH"], copper_ew, "CU0", cf_a["CU0"], EVAL_START, False),
            ("601899.SH", ["601899.SH"], ac_ff["601899.SH"], "CU0", cf_a["CU0"], EVAL_START, False),
            ("603993.SH", ["603993.SH"], ac_ff["603993.SH"], "CU0", cf_a["CU0"], EVAL_START, False),
            ("COPPER_A_EW", ["601899.SH", "603993.SH"], copper_ew, "HG_F", gf_a["HG_F"], EVAL_START, False),
            ("601899.SH", ["601899.SH"], ac_ff["601899.SH"], "HG_F", gf_a["HG_F"], EVAL_START, False),
            ("603993.SH", ["603993.SH"], ac_ff["603993.SH"], "HG_F", gf_a["HG_F"], EVAL_START, False),
        ],
        "oil": [
            ("OIL_A_EW", ["601857.SH", "600938.SH"], oil_ew, "BZ_F", gf_a["BZ_F"], EVAL_START, False),
            ("601857.SH", ["601857.SH"], ac_ff["601857.SH"], "BZ_F", gf_a["BZ_F"], EVAL_START, False),
            ("600938.SH", ["600938.SH"], ac_ff["600938.SH"], "BZ_F", gf_a["BZ_F"], s938_bt_start, False),
            # Strict t-1 US settlement robustness check (known strictly before A-share t 15:00 close)
            ("OIL_A_EW", ["601857.SH", "600938.SH"], oil_ew, "BZ_F_lag1d", gf_a["BZ_F"].shift(1), EVAL_START, False),
            ("OIL_A_EW", ["601857.SH", "600938.SH"], oil_ew, "SC0", cf_a["SC0"], sc0_bt_start, False),
            ("601857.SH", ["601857.SH"], ac_ff["601857.SH"], "SC0", cf_a["SC0"], sc0_bt_start, False),
            ("600938.SH", ["600938.SH"], ac_ff["600938.SH"], "SC0", cf_a["SC0"], s938_bt_start, False),
        ],
    }

    module3 = {}
    for grp, specs in m3_specs.items():
        module3[grp] = {}
        for target_lbl, tickers, stk_sig, drv_lbl, comm_s, bt_start, run_gold_adapt in specs:
            key = f"{target_lbl}__{drv_lbl}"
            bh_res = run_pit_backtest(a_cal, tickers, ao_raw, ac_raw, ac_ff, stk_sig, comm_s, "C", bt_start)
            bh_ret = bh_res["daily_ret"]
            entry_dict = {
                "target": target_lbl,
                "tickers": tickers,
                "driver": drv_lbl,
                "backtest_start": str(bt_start)[:10],
                "backtest_end": str(EVAL_END)[:10],
                "strategies": {},
            }
            strat_list = [("A", False)]
            if run_gold_adapt:
                strat_list.append(("A_gold_adapt", True))
            strat_list.extend([("A2", False), ("B", False)])

            for s_name, adapt_flag in strat_list:
                base_s = "A" if s_name == "A_gold_adapt" else s_name
                r = run_pit_backtest(a_cal, tickers, ao_raw, ac_raw, ac_ff, stk_sig, comm_s, base_s, bt_start, gold_adapt=adapt_flag)
                entry_dict["strategies"][s_name] = summarize_backtest(r, hs300_ret, bh_ret, bt_start)
            entry_dict["strategies"]["C_buy_hold"] = summarize_backtest(bh_res, hs300_ret, bh_ret, bt_start)
            module3[grp][key] = entry_dict

    out = {
        "meta": {
            "script": str(Path(__file__).resolve()),
            "data_as_of_date": "2026-11-20",
            "eval_window": "2016-01-04 ~ 2026-11-20",
            "warmup_window": "2015-01-05 ~ 2015-12-31",
            "late_listing_starts": {
                "600938.SH": {"listed": "2022-04-21", "backtest_start_after_60d_ma": str(s938_bt_start)[:10]},
                "SC0": {"listed": "2018-03-26", "backtest_start_after_180d_q756": str(sc0_bt_start)[:10]},
            },
            "cl_f_negative_anomaly": "2020-04-20 (-37.63) masked to NaN in CL_F_CLEAN; BZ_F + SC0 used as primary oil benchmarks",
            "transaction_cost": "0.30% round-trip (0.15% buy at t+1 open + 0.15% sell at exit+1 open)",
            "yfinance_imported": "yfinance" in sys.modules,
        },
        "benchmarks": benchmarks,
        "module1_turning_points": module1,
        "module2_crosscorr": module2,
        "module3_backtest": module3,
    }

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(clean_obj(out), f, ensure_ascii=False, indent=2)
    print(f"WROTE {OUT_JSON} ({OUT_JSON.stat().st_size} bytes)")


if __name__ == "__main__":
    main()

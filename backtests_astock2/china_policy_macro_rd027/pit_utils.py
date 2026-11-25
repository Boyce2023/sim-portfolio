#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Strict PIT calendar alignment, date parsing, causal rolling percentile, and audit helpers for RD027.
"""
import re
import numpy as np
import pandas as pd


def parse_ym_str(val) -> str | None:
    """Parse Chinese/dot/compact year-month string into 'YYYY-MM'."""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    s = str(val).strip()
    m = re.match(r"^(\d{4})\D+(\d{1,2})", s)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}"
    m2 = re.match(r"^(\d{4})(\d{2})$", s)
    if m2:
        return f"{int(m2.group(1)):04d}-{int(m2.group(2)):02d}"
    try:
        dt = pd.to_datetime(s)
        return dt.strftime("%Y-%m")
    except Exception:
        return None


def parse_quarter_end_ym(val) -> str | None:
    """Parse '2026年第1-3季度' or '2026年第1季度' -> quarter end 'YYYY-MM'."""
    if val is None:
        return None
    s = str(val).strip()
    m_yr = re.search(r"(\d{4})", s)
    if not m_yr:
        return None
    yr = int(m_yr.group(1))
    if "1-4" in s or "第4季度" in s or "1-12" in s:
        q_m = 12
    elif "1-3" in s or "第3季度" in s:
        q_m = 9
    elif "1-2" in s or "第2季度" in s:
        q_m = 6
    elif "第1季度" in s:
        q_m = 3
    else:
        return None
    return f"{yr:04d}-{q_m:02d}"


def build_pit_mapper(trade_dates: pd.Series):
    """Return helper functions mapping calendar dates to strict A-share available_date."""
    cal = pd.DatetimeIndex(pd.to_datetime(trade_dates)).sort_values().unique()
    cal_ns = cal.asi8

    def on_or_after(dt) -> pd.Timestamp:
        if pd.isna(dt):
            return pd.NaT
        ts = pd.Timestamp(dt).normalize()
        idx = int(np.searchsorted(cal_ns, ts.value, side="left"))
        return cal[idx] if idx < len(cal) else pd.NaT

    def strictly_after(dt) -> pd.Timestamp:
        if pd.isna(dt):
            return pd.NaT
        ts = pd.Timestamp(dt).normalize()
        idx = int(np.searchsorted(cal_ns, ts.value, side="right"))
        return cal[idx] if idx < len(cal) else pd.NaT

    def ym_day_available(ym: str, day_of_next_month: int, months_ahead: int = 1) -> pd.Timestamp:
        if not ym:
            return pd.NaT
        p = pd.Period(ym, freq="M") + months_ahead
        target = pd.Timestamp(year=p.year, month=p.month, day=min(day_of_next_month, 28))
        return on_or_after(target)

    def pmi_available(ym: str) -> pd.Timestamp:
        if not ym:
            return pd.NaT
        month_end = pd.Period(ym, freq="M").end_time.normalize()
        return strictly_after(month_end)

    return on_or_after, strictly_after, ym_day_available, pmi_available


def causal_rolling_pct(series: pd.Series, window: int, min_periods: int = 242) -> pd.Series:
    """Strictly backward-only causal percentile rank in [0, 1] over [t-window+1, t]."""
    arr = series.to_numpy(dtype=float)
    n = len(arr)
    out = np.full(n, np.nan, dtype=float)
    for i in range(n):
        v = arr[i]
        if np.isnan(v):
            continue
        w = arr[max(0, i - window + 1) : i + 1]
        w = w[~np.isnan(w)]
        if len(w) >= min_periods:
            out[i] = float(np.mean(w <= v))
    return pd.Series(out, index=series.index)


def pit_asof_join(
    base_dates: pd.DataFrame,
    src_df: pd.DataFrame,
    avail_col: str,
    value_cols: list[str],
    max_staleness_days: int | None = None,
) -> pd.DataFrame:
    """Merge src_df onto base_dates strictly backward on available_date <= date, with optional staleness cutoff."""
    if src_df.empty:
        out = base_dates[["date"]].copy()
        for c in value_cols:
            out[c] = np.nan
        return out

    r = src_df[[avail_col] + value_cols].dropna(subset=[avail_col]).copy()
    r[avail_col] = pd.to_datetime(r[avail_col])
    r = r.sort_values(avail_col).drop_duplicates(subset=[avail_col], keep="last")
    # Remove releases after last base date
    max_base = pd.to_datetime(base_dates["date"]).max()
    r = r[r[avail_col] <= max_base]
    if r.empty:
        out = base_dates[["date"]].copy()
        for c in value_cols:
            out[c] = np.nan
        return out

    left = base_dates[["date"]].sort_values("date").copy()
    tol = pd.Timedelta(days=max_staleness_days) if max_staleness_days is not None else None
    merged = pd.merge_asof(
        left, r, left_on="date", right_on=avail_col, direction="backward", tolerance=tol
    )
    return merged[["date"] + value_cols]


def stamp_tax_rate_series(dates: pd.Series) -> pd.Series:
    """Official statutory A-share stamp duty rate on total turnover (two-way equivalent)."""
    d = pd.to_datetime(dates)
    rate = np.where(
        d < pd.Timestamp("2005-01-24"), 0.0040,
        np.where(
            d < pd.Timestamp("2007-05-30"), 0.0020,
            np.where(
                d < pd.Timestamp("2008-04-24"), 0.0060,
                np.where(
                    d < pd.Timestamp("2008-09-19"), 0.0020,
                    np.where(d < pd.Timestamp("2023-08-28"), 0.0010, 0.0005),
                ),
            ),
        ),
    )
    return pd.Series(rate, index=dates.index, dtype=float)


def audit_columns(df: pd.DataFrame, date_col: str, col_meta: dict[str, dict], effective_start: str | None = None) -> dict:
    """Compute per-column coverage, first/last non-null date, missing rate after effective start."""
    d_ser = pd.to_datetime(df[date_col])
    report = {}
    for c in df.columns:
        if c == date_col:
            continue
        s = df[c]
        nn_idx = s.first_valid_index()
        ln_idx = s.last_valid_index()
        if nn_idx is None:
            report[c] = {
                **col_meta.get(c, {}),
                "first_date": None,
                "last_date": None,
                "valid_count": 0,
                "total_rows_after_start": int(len(df)),
                "missing_rate_pct": 100.0,
                "gt_5pct_missing_flag": True,
            }
            continue
        first_dt = d_ser.loc[nn_idx]
        last_dt = d_ser.loc[ln_idx]
        eff_dt = max(first_dt, pd.Timestamp(effective_start)) if effective_start else first_dt
        sub = s[d_ser >= eff_dt]
        miss_pct = round(float(sub.isna().mean() * 100.0), 3) if len(sub) > 0 else 100.0
        report[c] = {
            **col_meta.get(c, {}),
            "first_date": first_dt.strftime("%Y-%m-%d"),
            "last_date": last_dt.strftime("%Y-%m-%d"),
            "valid_count": int(s.notna().sum()),
            "total_rows_after_start": int(len(sub)),
            "missing_rate_pct": miss_pct,
            "gt_5pct_missing_flag": bool(miss_pct > 5.0),
        }
    return report

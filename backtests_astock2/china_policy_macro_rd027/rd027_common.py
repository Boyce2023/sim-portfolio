#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Shared PIT alignment, market-panel level reconstruction, and D15 statistical helpers for RD027.
Strictly zero yfinance (D12 compliant). All returns derived directly from local market panel.
"""
import os
import numpy as np
import pandas as pd
from scipy import stats

ROOT = "/Users/huaichuaibeimeng/claude-projects"
PANEL_PQ = os.path.join(ROOT, "output/csrc_policy_100factors_20261114/policy_polymarket_v1/daily_market_panel_v2_20261124.parquet")
MASTER_PQ = os.path.join(ROOT, "output/csrc_policy_100factors_20261114/policy_polymarket_v1/master_events_v2_20261125.parquet")
OUT_PILLAR_DIR = os.path.join(ROOT, "output/china_policy_macro_rd027_20261125/data_pillars")
os.makedirs(OUT_PILLAR_DIR, exist_ok=True)

PORTFOLIO_PREFIXES = ["ew", "micro30", "large10", "tech_board", "high_relay", "big4_bank", "bench"]

INDEX_ASSETS = [
    "bench", "sh_comp", "csi300", "csi500", "csi1000", "sse50", "chinext", "star50",
    "csi_div", "central_soe", "soe_reform", "brokerage", "bank_idx", "new_energy",
    "baijiu", "pharma", "defense", "media_ai", "tmt_info", "cons_opt", "real_estate",
    "semi_etf", "ew", "micro30", "large10", "tech_board",
]


def load_market_panel() -> tuple[pd.DataFrame, list[str], dict[str, int]]:
    """Load daily_market_panel_v2 and reconstruct open/close level curves for equal-weight & spliced series."""
    panel = pd.read_parquet(PANEL_PQ).sort_values("date").reset_index(drop=True)
    panel["date"] = panel["date"].astype(str).str[:10]

    for ps in PORTFOLIO_PREFIXES:
        cc_col = f"{ps}_cc_ret"
        gap_col = f"{ps}_gap_ret"
        if cc_col not in panel.columns:
            continue
        # Only accumulate starting from first valid observation to avoid flat 1.0 inflation
        valid = panel[cc_col].notna()
        cl = (1.0 + panel[cc_col].fillna(0.0)).cumprod()
        prev_cl = cl.shift(1).fillna(1.0)
        op = prev_cl * (1.0 + panel[gap_col].fillna(0.0))
        if valid.any():
            first_idx = int(valid.idxmax())
            # Keep pre-inception rows NaN so availability checks stay honest
            if first_idx > 1:
                cl.iloc[: first_idx - 1] = np.nan
                op.iloc[:first_idx] = np.nan
        panel[f"{ps}_open"] = op
        panel[f"{ps}_close"] = cl

    # Ensure index open/close are float and strictly positive
    for asset in INDEX_ASSETS:
        for suf in ["_open", "_close"]:
            col = f"{asset}{suf}"
            if col in panel.columns:
                panel[col] = pd.to_numeric(panel[col], errors="coerce")

    dates = panel["date"].tolist()
    date_to_idx = {d: i for i, d in enumerate(dates)}
    return panel, dates, date_to_idx


def align_event_pit(event_date: str, release_slot: str, dates: list[str], date_to_idx: dict[str, int]) -> tuple[int, int, str]:
    """
    Strictly zero-lookahead PIT alignment:
      - BMO on trading day i -> entry at open[i], prior state at close[i-1]
      - INTRADAY on trading day i -> entry at open[i+1], prior state at close[i-1]
      - AMC / WEEKEND_HOLIDAY on trading day i -> entry at open[i+1], prior state at close[i]
      - Non-trading day -> entry at first trading day > event_date, prior state at t_entry - 1
    """
    dt = str(event_date)[:10]
    slot = str(release_slot or "AMC").upper()
    if dt in date_to_idx:
        i_dt = date_to_idx[dt]
        if slot == "BMO":
            t_entry = i_dt
            t_prior = i_dt - 1
        elif slot == "INTRADAY":
            t_entry = i_dt + 1
            t_prior = i_dt - 1
        else:
            t_entry = i_dt + 1
            t_prior = i_dt
    else:
        later = [i for i, d in enumerate(dates) if d > dt]
        t_entry = later[0] if later else len(dates)
        t_prior = (t_entry - 1) if t_entry > 0 else 0

    tradable_date = dates[t_entry] if 0 <= t_entry < len(dates) else "PENDING_NEXT_OPEN"
    t_entry_out = t_entry if 0 <= t_entry < len(dates) else -1
    t_prior_out = min(max(0, t_prior), len(dates) - 1)
    return t_entry_out, t_prior_out, tradable_date


def extract_prior_state(panel: pd.DataFrame, t_prior: int) -> dict:
    """Extract strictly ex-ante market & sentiment state as of t_prior close."""
    if t_prior < 0 or t_prior >= len(panel):
        return {}
    pr = panel.iloc[t_prior]
    fields = [
        ("prior_dd_60d", "bench_dd_60d"),
        ("prior_dd_250d", "bench_dd_250d"),
        ("prior_ret_5d", "bench_ret_5d"),
        ("prior_ret_20d", "bench_ret_20d"),
        ("prior_ret_60d", "bench_ret_60d"),
        ("prior_vol_20d", "bench_vol_20d"),
        ("prior_amt_pct_250d", "amount_pct_250d"),
        ("prior_amt_ratio_20d", "amount_ratio_20d"),
        ("prior_amt_yi", "total_amount_yi"),
        ("prior_zt_cnt", "zt_cnt"),
        ("prior_dt_cnt", "dt_cnt"),
        ("prior_broken_rate", "broken_rate"),
    ]
    out = {}
    for k_out, k_in in fields:
        v = pr.get(k_in, np.nan)
        out[k_out] = float(v) if pd.notna(v) else np.nan
    return out


def calc_fwd_return(panel: pd.DataFrame, t_entry: int, h: int, asset: str) -> float:
    """Exact tradable return: open[t_entry] -> close[t_entry + h - 1]."""
    if t_entry < 0 or t_entry + h - 1 >= len(panel):
        return np.nan
    op_col, cl_col = f"{asset}_open", f"{asset}_close"
    if op_col not in panel.columns or cl_col not in panel.columns:
        return np.nan
    op_v = panel.at[t_entry, op_col]
    cl_v = panel.at[t_entry + h - 1, cl_col]
    if pd.isna(op_v) or pd.isna(cl_v) or op_v <= 0 or cl_v <= 0:
        return np.nan
    return float(cl_v / op_v - 1.0)


def calc_fwd_max_drawdown(panel: pd.DataFrame, t_entry: int, h: int, asset: str = "bench") -> float:
    """Max drawdown of holding [open[t_entry] -> close[t_entry..t_entry+h-1]]."""
    if t_entry < 0 or t_entry >= len(panel):
        return np.nan
    op_col, cl_col = f"{asset}_open", f"{asset}_close"
    if op_col not in panel.columns or cl_col not in panel.columns:
        return np.nan
    op_v = panel.at[t_entry, op_col]
    if pd.isna(op_v) or op_v <= 0:
        return np.nan
    i_end = min(len(panel), t_entry + h)
    cl_seq = panel[cl_col].iloc[t_entry:i_end].to_numpy(dtype=float)
    cl_seq = cl_seq[np.isfinite(cl_seq) & (cl_seq > 0)]
    if len(cl_seq) == 0:
        return np.nan
    path = np.concatenate([[op_v], cl_seq])
    peaks = np.maximum.accumulate(path)
    dds = path / peaks - 1.0
    return float(np.min(dds))


def calc_sample_stats(vals, exp_dir: int = 1) -> dict:
    """Compute n, mean, median, win_rate, payoff ratio, and 1-sample t-stat."""
    arr = np.asarray(vals, dtype=float)
    arr = arr[np.isfinite(arr)]
    n = int(len(arr))
    if n == 0:
        return {"n": 0, "mean": np.nan, "median": np.nan, "win_rate": np.nan, "payoff": np.nan, "t_stat": np.nan, "p_val": np.nan}
    d_arr = arr * exp_dir
    wins = d_arr[d_arr > 0]
    losses = -d_arr[d_arr < 0]
    win_rate = float(np.mean(d_arr > 0))
    if len(wins) > 0 and len(losses) > 0 and np.mean(losses) > 1e-9:
        payoff = float(np.mean(wins) / np.mean(losses))
    elif len(wins) > 0:
        payoff = 9.99
    else:
        payoff = 0.0
    mean_v = float(np.mean(arr))
    med_v = float(np.median(arr))
    if n >= 3 and np.std(arr, ddof=1) > 1e-10:
        t_st, p_v = stats.ttest_1samp(arr, 0.0)
        t_st, p_v = float(t_st), float(p_v)
    else:
        t_st, p_v = np.nan, np.nan
    return {"n": n, "mean": mean_v, "median": med_v, "win_rate": win_rate, "payoff": payoff, "t_stat": t_st, "p_val": p_v}

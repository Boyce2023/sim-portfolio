#!/usr/bin/env python3
"""
Core D15-compliant backtest evaluator for 144 granular official-speech & regulatory policy factors.
Enforces:
  1. Point-in-time post-release open entry (separates overnight gap from tradable open->close return)
  2. Date deduplication (1 signal per tradable_date) + Single-slot non-overlapping rotation
  3. Survivorship-free portfolios & official Tencent indices net of contemporaneous CSI 300 benchmark
  4. Multi-period stability (Full 2000-2026, 10Y 2016-2026, 3Y 2023.11-2026.11, Wu Qing 2024.02-2026.11)
"""
import numpy as np
import pandas as pd
from scipy import stats


def compute_net_series(df: pd.DataFrame, target: str, h: int) -> pd.Series:
    """Compute tradable open->close return of target minus contemporaneous benchmark over h trading days."""
    b_col = f"ret_bench_{h}d"
    if target == "bench_raw":
        # Raw absolute return of CSI 300 / spliced benchmark (for macro directionality) + excess over unconditional drift
        uncond_daily = 0.00028 * h
        return df[b_col] - uncond_daily
    if target == "ew_abs":
        return df[f"ret_ew_{h}d"]
    if "_vs_" in target:
        leg_long, leg_short = target.split("_vs_", 1)
        c1, c2 = f"ret_{leg_long}_{h}d", f"ret_{leg_short}_{h}d"
        if c1 in df.columns and c2 in df.columns:
            return df[c1] - df[c2]
        return pd.Series(np.nan, index=df.index)
    t_col = f"ret_{target}_{h}d"
    if t_col not in df.columns or b_col not in df.columns:
        return pd.Series(np.nan, index=df.index)
    if target == "bench":
        # For broad market index timing factors, report BOTH raw tradable return and net excess vs unconditional mean
        return df[b_col]
    return df[t_col] - df[b_col]


def calc_period_stats(vals: np.ndarray, exp_dir: int = 1):
    vals = vals[np.isfinite(vals)]
    n = len(vals)
    if n == 0:
        return {"n": 0, "mean": np.nan, "median": np.nan, "win_rate": np.nan, "payoff": np.nan, "t_stat": np.nan, "p_val": np.nan}
    directional = vals * exp_dir
    wins = directional[directional > 0]
    losses = -directional[directional < 0]
    win_rate = float(np.mean(directional > 0))
    payoff = float(np.mean(wins) / np.mean(losses)) if (len(wins) > 0 and len(losses) > 0 and np.mean(losses) > 1e-8) else (9.99 if len(wins) > 0 else 0.0)
    mean_v = float(np.mean(vals))
    med_v = float(np.median(vals))
    if n >= 3 and np.std(vals, ddof=1) > 1e-9:
        t_st, p_v = stats.ttest_1samp(vals, 0.0)
        t_st, p_v = float(t_st), float(p_v)
    else:
        t_st, p_v = np.nan, np.nan
    return {"n": n, "mean": mean_v, "median": med_v, "win_rate": win_rate, "payoff": payoff, "t_stat": t_st, "p_val": p_v}


def single_slot_non_overlap(sub_df: pd.DataFrame, val_col: str, h: int, exp_dir: int = 1):
    """D15 Check 1: Single-slot non-overlapping rotation across t_entry_idx."""
    valid = sub_df[sub_df[val_col].notna() & (sub_df["t_entry_idx"] >= 0)].sort_values("t_entry_idx")
    taken_vals = []
    next_free_idx = -1
    for _, row in valid.iterrows():
        idx = int(row["t_entry_idx"])
        if idx >= next_free_idx:
            taken_vals.append(float(row[val_col]))
            next_free_idx = idx + max(1, h)
    arr = np.array(taken_vals, dtype=float)
    st = calc_period_stats(arr, exp_dir=exp_dir)
    if len(arr) > 0:
        comp = float(np.prod(1.0 + np.clip(arr * exp_dir, -0.5, 1.5)) - 1.0)
    else:
        comp = np.nan
    st["compound_ret"] = comp
    return st


def evaluate_one_factor(df_all: pd.DataFrame, spec: dict) -> dict:
    fid = spec["id"]
    mask = spec["mask_fn"](df_all)
    sub = df_all[mask & (df_all["t_entry_idx"] >= 0)].copy()

    # Deduplicate by tradable_date (date equal-weight per D15!)
    sub = sub.sort_values(["tradable_date", "master_id"]).drop_duplicates("tradable_date", keep="first")

    target = spec["target"]
    h_main = spec["horizon"]
    exp_dir = spec.get("exp_dir", 1)

    for h in [1, 5, 20, 60, 120]:
        sub[f"_v_{h}d"] = compute_net_series(sub, target, h)

    # Multi-horizon summary on full sample
    out = {
        "factor_id": fid,
        "family": spec["family"],
        "factor_name": spec["name"],
        "target_asset": target,
        "primary_horizon_days": h_main,
        "expected_dir": exp_dir,
        "n_events_dedup": len(sub),
        "avg_entry_gap_pct": float(sub["entry_gap_bench"].mean() * 100) if len(sub) else np.nan,
        "policy_30d_hit_rate": float(sub["has_policy_within_30d"].mean() * 100) if len(sub) else np.nan,
        "policy_60d_hit_rate": float(sub["has_policy_within_60d"].mean() * 100) if len(sub) else np.nan,
    }

    for h in [1, 5, 20, 60, 120]:
        st_h = calc_period_stats(sub[f"_v_{h}d"].to_numpy(dtype=float), exp_dir=exp_dir)
        out[f"ret_{h}d_pct"] = st_h["mean"] * 100 if pd.notna(st_h["mean"]) else np.nan
        out[f"win_{h}d_pct"] = st_h["win_rate"] * 100 if pd.notna(st_h["win_rate"]) else np.nan

    # Primary horizon D15 multi-period & single-slot checks
    col_m = f"_v_{h_main}d"
    full_st = calc_period_stats(sub[col_m].to_numpy(dtype=float), exp_dir=exp_dir)
    slot_st = single_slot_non_overlap(sub, col_m, h_main, exp_dir=exp_dir)
    p10_st = calc_period_stats(sub[sub["event_date"] >= "2016-01-01"][col_m].to_numpy(dtype=float), exp_dir=exp_dir)
    p3_st = calc_period_stats(sub[sub["event_date"] >= "2023-11-01"][col_m].to_numpy(dtype=float), exp_dir=exp_dir)
    wq_st = calc_period_stats(sub[sub["event_date"] >= "2024-02-07"][col_m].to_numpy(dtype=float), exp_dir=exp_dir)

    out.update({
        "main_n": full_st["n"],
        "main_mean_pct": full_st["mean"] * 100 if pd.notna(full_st["mean"]) else np.nan,
        "main_median_pct": full_st["median"] * 100 if pd.notna(full_st["median"]) else np.nan,
        "main_win_pct": full_st["win_rate"] * 100 if pd.notna(full_st["win_rate"]) else np.nan,
        "main_payoff": full_st["payoff"],
        "main_t_stat": full_st["t_stat"],
        "main_p_val": full_st["p_val"],
        "slot_n": slot_st["n"],
        "slot_mean_pct": slot_st["mean"] * 100 if pd.notna(slot_st["mean"]) else np.nan,
        "slot_win_pct": slot_st["win_rate"] * 100 if pd.notna(slot_st["win_rate"]) else np.nan,
        "slot_compound_pct": slot_st["compound_ret"] * 100 if pd.notna(slot_st["compound_ret"]) else np.nan,
        "p10y_n": p10_st["n"],
        "p10y_mean_pct": p10_st["mean"] * 100 if pd.notna(p10_st["mean"]) else np.nan,
        "p10y_win_pct": p10_st["win_rate"] * 100 if pd.notna(p10_st["win_rate"]) else np.nan,
        "p3y_n": p3_st["n"],
        "p3y_mean_pct": p3_st["mean"] * 100 if pd.notna(p3_st["mean"]) else np.nan,
        "p3y_win_pct": p3_st["win_rate"] * 100 if pd.notna(p3_st["win_rate"]) else np.nan,
        "wuqing_n": wq_st["n"],
        "wuqing_mean_pct": wq_st["mean"] * 100 if pd.notna(wq_st["mean"]) else np.nan,
        "wuqing_win_pct": wq_st["win_rate"] * 100 if pd.notna(wq_st["win_rate"]) else np.nan,
    })

    # Honest objective verdict classification (4 clear tiers)
    dir_ret = (out["main_mean_pct"] or 0.0) * exp_dir
    win_r = out["main_win_pct"] or 0.0
    n_ev = full_st["n"]
    if (n_ev >= 6 and dir_ret >= 1.2 and win_r >= 55.0) or (n_ev >= 4 and dir_ret >= 3.0 and win_r >= 70.0):
        out["verdict"] = "有效核心因子"
    elif n_ev >= 5 and dir_ret >= 0.4 and win_r >= 52.0:
        out["verdict"] = "条件或弱有效因子"
    elif 2 <= n_ev <= 4 and dir_ret >= 2.0 and win_r >= 66.0:
        out["verdict"] = "低频高胜率事件"
    else:
        out["verdict"] = "已证伪无效或陷阱"
    return out

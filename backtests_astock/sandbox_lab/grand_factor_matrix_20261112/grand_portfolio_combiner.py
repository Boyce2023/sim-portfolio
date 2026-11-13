#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Grand Multi-Strategy Account Combiner (1to2 V17 + Optimized High-Dragon/5Ban + 3to4 + 2to3 + Pry + 0to1)."""
import os, sys, json
import numpy as np
import pandas as pd

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
if CUR_DIR not in sys.path:
    sys.path.insert(0, CUR_DIR)

from d15_eval_helper import evaluate_d15_full, csi300_ret

V17_LEDGER = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/full_day_by_day_v17_ledger.csv"


def load_v17_df() -> pd.DataFrame:
    df = pd.read_csv(V17_LEDGER)
    df["code"] = df["c6"].astype(str).str.zfill(6)
    df["strategy"] = "1to2_V17"
    df["buy_at_open"] = False
    df["priority_score"] = 1000.0
    df["hold_bars"] = np.maximum(1, (pd.to_datetime(df["exit_date"]) - pd.to_datetime(df["buy_date"])).dt.days)
    return df[["code", "name", "buy_date", "exit_date", "net_ret", "strategy", "priority_score", "buy_at_open", "exit_at_open", "hold_bars"]]


def combine_and_evaluate(strategy_dfs: dict, priority_order: list) -> dict:
    parts = []
    for rk, sname in enumerate(priority_order):
        sdf = strategy_dfs.get(sname)
        if sdf is None or sdf.empty:
            continue
        tmp = sdf.copy()
        tmp["strategy"] = sname
        base_p = (len(priority_order) - rk) * 10000.0
        sub_p = tmp["priority_score"].fillna(0.0) if "priority_score" in tmp.columns else 0.0
        tmp["priority_score"] = base_p + np.clip(sub_p, -999.0, 999.0)
        if "buy_at_open" not in tmp.columns:
            tmp["buy_at_open"] = True
        if "exit_at_open" not in tmp.columns:
            tmp["exit_at_open"] = False
        if "hold_bars" not in tmp.columns:
            tmp["hold_bars"] = 1
        parts.append(tmp[["code", "name", "buy_date", "exit_date", "net_ret", "strategy", "priority_score", "buy_at_open", "exit_at_open", "hold_bars"]])

    if not parts:
        return {}
    merged = pd.concat(parts, ignore_index=True)
    # Deduplicate same code on same buy_date (keep highest priority)
    merged.sort_values(["buy_date", "priority_score"], ascending=[True, False], inplace=True)
    merged.drop_duplicates(subset=["buy_date", "code"], keep="first", inplace=True)
    d15 = evaluate_d15_full(merged)

    # Also track how many trades came from each strategy inside the single-slot rotation!
    srt = merged.sort_values(["buy_date", "priority_score"], ascending=[True, False])
    free_after = ""
    exit_open_prev = True
    by_strat = {}
    for r in srt.itertuples(index=False):
        can_buy = (free_after == "") or (r.buy_date > free_after) or (r.buy_date == free_after and exit_open_prev and (not r.buy_at_open))
        if not can_buy:
            continue
        free_after = r.exit_date
        exit_open_prev = bool(r.exit_at_open)
        rec = by_strat.setdefault(r.strategy, [])
        rec.append(float(r.net_ret))

    strat_contrib = {
        k: {"n": len(v), "wr": round(float((np.array(v) > 0).mean() * 100), 1), "mean_pct": round(float(np.mean(v) * 100), 2)}
        for k, v in by_strat.items()
    }
    d15["single_slot_strategy_contrib"] = strat_contrib
    return d15


def eval_4bucket_equal_split(bucket_dfs: list) -> dict:
    """Evaluate 4-bucket (or N-bucket) equal initial capital sub-accounts vs CSI300."""
    navs_5y, navs_jul = [], []
    tot_n_5y, tot_wr_list = 0, []
    for bdf in bucket_dfs:
        m = evaluate_d15_full(bdf)
        navs_5y.append(m["full_5y"]["single_nav"])
        navs_jul.append(m["since_jul2026"]["single_nav"])
        tot_n_5y += m["full_5y"]["single_n"]
    avg_nav_5y = float(np.mean(navs_5y)) if navs_5y else 1.0
    avg_nav_jul = float(np.mean(navs_jul)) if navs_jul else 1.0
    b5 = csi300_ret("2022-01-04", "2026-11-10")
    bj = csi300_ret("2026-07-01", "2026-11-10")
    return {
        "n_buckets": len(bucket_dfs),
        "total_single_trades_5y": tot_n_5y,
        "portfolio_5y_nav": round(avg_nav_5y, 3),
        "portfolio_5y_ret_pct": round((avg_nav_5y - 1.0) * 100, 2),
        "portfolio_5y_excess_pct": round(((avg_nav_5y - 1.0) - b5) * 100, 2),
        "portfolio_jul26_nav": round(avg_nav_jul, 3),
        "portfolio_jul26_ret_pct": round((avg_nav_jul - 1.0) * 100, 2),
        "portfolio_jul26_excess_pct": round(((avg_nav_jul - 1.0) - bj) * 100, 2),
    }

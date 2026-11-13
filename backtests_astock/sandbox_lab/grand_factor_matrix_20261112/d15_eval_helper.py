#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Standardized D15 4-Pillar Anti-Fraud Portfolio & Multi-Period Evaluator (Zero Lookahead, 0.2% Fee, CSI300 Net Excess)."""
import json
import numpy as np
import pandas as pd

SANDBOX = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/sandbox_lab"
FEE_RATE = 0.0020

with open(f"{SANDBOX}/index_klines_5y_cache.json", "r", encoding="utf-8") as _f:
    IDX_KLINES = json.load(_f)
CSI300_MAP = IDX_KLINES["sh000300"]


def csi300_ret(start_dt: str, end_dt: str) -> float:
    dts = sorted(k for k in CSI300_MAP.keys() if start_dt <= k <= end_dt)
    if len(dts) < 2:
        return 0.0
    # Use previous close before start_dt as base if available
    prev_dts = [k for k in CSI300_MAP.keys() if k < dts[0]]
    base_dt = max(prev_dts) if prev_dts else dts[0]
    return float(CSI300_MAP[dts[-1]] / CSI300_MAP[base_dt] - 1.0)


def _sim_single_slot(trades_df: pd.DataFrame):
    if trades_df.empty:
        return [], 1.0, 0.0, 0
    srt = trades_df.sort_values(["buy_date", "priority_score"], ascending=[True, False])
    taken = []
    free_after = ""
    exit_at_open_prev = True
    nav, pk, mdd = 1.0, 1.0, 0.0
    hold_days = 0
    for r in srt.itertuples(index=False):
        bd = r.buy_date
        # If exited at open on day X, capital is free for intraday/open buy on day X only if exit_at_open; conservative: bd > free_after or (bd == free_after and exit_at_open_prev and not getattr(r, "buy_at_open", True))
        can_buy = (free_after == "") or (bd > free_after) or (bd == free_after and exit_at_open_prev and (not getattr(r, "buy_at_open", True)))
        if not can_buy:
            continue
        taken.append(r)
        free_after = r.exit_date
        exit_at_open_prev = bool(getattr(r, "exit_at_open", False))
        nav *= (1.0 + float(r.net_ret))
        pk = max(pk, nav)
        mdd = max(mdd, (pk - nav) / pk)
        hold_days += max(1, int(getattr(r, "hold_bars", 1)))
    return taken, nav, mdd, hold_days


def _sim_two_half_slots(trades_df: pd.DataFrame):
    if trades_df.empty:
        return 1.0, 0.0, 0
    srt = trades_df.sort_values(["buy_date", "priority_score"], ascending=[True, False])
    slot_cap = [0.5, 0.5]
    slot_free = ["", ""]
    pk, mdd, cnt = 1.0, 0.0, 0
    used_day_codes = set()
    for r in srt.itertuples(index=False):
        bd, c = r.buy_date, r.code
        if (bd, c) in used_day_codes:
            continue
        chosen = -1
        for s in (0, 1):
            if slot_free[s] == "" or bd > slot_free[s]:
                chosen = s
                break
        if chosen < 0:
            continue
        used_day_codes.add((bd, c))
        slot_free[chosen] = r.exit_date
        slot_cap[chosen] *= (1.0 + float(r.net_ret))
        tot = slot_cap[0] + slot_cap[1]
        pk = max(pk, tot)
        mdd = max(mdd, (pk - tot) / pk)
        cnt += 1
    return float(slot_cap[0] + slot_cap[1]), float(mdd), cnt


def _sim_daily_eq(trades_df: pd.DataFrame):
    if trades_df.empty:
        return 1.0, 0.0
    by_d = trades_df.groupby("buy_date")["net_ret"].mean().sort_index()
    nav, pk, mdd = 1.0, 1.0, 0.0
    for r in by_d.values:
        nav *= (1.0 + float(r))
        pk = max(pk, nav)
        mdd = max(mdd, (pk - nav) / pk)
    return float(nav), float(mdd)


def _slice_metrics(sub_df: pd.DataFrame, start_dt: str, end_dt: str):
    bench = csi300_ret(start_dt, end_dt)
    if sub_df.empty:
        return {
            "raw_n": 0, "single_n": 0, "wr": 0.0, "payoff": 0.0, "mean_pct": 0.0,
            "single_nav": 1.0, "single_ret_pct": 0.0, "single_mdd_pct": 0.0,
            "eq_nav": 1.0, "eq_ret_pct": 0.0, "eq_mdd_pct": 0.0,
            "trimmed5_nav": 1.0, "hold_days": 0,
            "csi300_pct": round(bench * 100, 2),
            "single_excess_pct": round(-bench * 100, 2),
            "eq_excess_pct": round(-bench * 100, 2),
        }
    taken, s_nav, s_mdd, h_days = _sim_single_slot(sub_df)
    eq_nav, eq_mdd = _sim_daily_eq(sub_df)
    rets = np.array([float(t.net_ret) for t in taken], dtype=float)
    wins, losses = rets[rets > 0], rets[rets <= 0]
    wr = float((rets > 0).mean() * 100.0) if len(rets) else 0.0
    po = float(wins.mean() / abs(losses.mean())) if (len(wins) > 0 and len(losses) > 0 and losses.mean() < 0) else (99.0 if len(wins) > 0 else 0.0)
    mean_p = float(rets.mean() * 100.0) if len(rets) else 0.0

    # Trimmed NAV excluding top 5 single-slot winners
    if len(rets) > 5:
        keep = np.sort(rets)[:-5]
        trim_nav = float(np.prod(1.0 + keep))
    else:
        trim_nav = 1.0

    return {
        "raw_n": int(len(sub_df)),
        "single_n": int(len(rets)),
        "wr": round(wr, 2),
        "payoff": round(po, 2),
        "mean_pct": round(mean_p, 2),
        "single_nav": round(s_nav, 3),
        "single_ret_pct": round((s_nav - 1.0) * 100.0, 2),
        "single_mdd_pct": round(s_mdd * 100.0, 2),
        "eq_nav": round(eq_nav, 3),
        "eq_ret_pct": round((eq_nav - 1.0) * 100.0, 2),
        "eq_mdd_pct": round(eq_mdd * 100.0, 2),
        "trimmed5_nav": round(trim_nav, 3),
        "hold_days": int(h_days),
        "csi300_pct": round(bench * 100.0, 2),
        "single_excess_pct": round(((s_nav - 1.0) - bench) * 100.0, 2),
        "eq_excess_pct": round(((eq_nav - 1.0) - bench) * 100.0, 2),
    }


def evaluate_d15_full(trades_df: pd.DataFrame) -> dict:
    """Compute complete D15 metrics across 5Y, Ex-2025 4Y, 3Y, 1Y, Jul2026+, and Annual."""
    if trades_df is None or len(trades_df) == 0:
        empty = _slice_metrics(pd.DataFrame(), "2022-01-04", "2026-11-10")
        return {"full_5y": empty, "ex2025_4y": empty, "recent_3y": empty, "recent_1y": empty, "since_jul2026": empty, "half2_5y": {"nav": 1.0, "mdd_pct": 0.0, "n": 0}, "annual": {}}

    df = trades_df.copy()
    if "priority_score" not in df.columns:
        df["priority_score"] = 0.0

    res = {
        "full_5y": _slice_metrics(df[(df["buy_date"] >= "2022-01-04") & (df["buy_date"] <= "2026-11-10")], "2022-01-04", "2026-11-10"),
        "ex2025_4y": _slice_metrics(df[(df["buy_date"] >= "2022-01-04") & (df["buy_date"] <= "2026-11-10") & (~df["buy_date"].str.startswith("2025"))], "2022-01-04", "2024-12-31"),
        "recent_3y": _slice_metrics(df[df["buy_date"] >= "2024-01-02"], "2024-01-02", "2026-11-10"),
        "recent_1y": _slice_metrics(df[df["buy_date"] >= "2025-11-10"], "2025-11-10", "2026-11-10"),
        "since_jul2026": _slice_metrics(df[df["buy_date"] >= "2026-07-01"], "2026-07-01", "2026-11-10"),
    }
    h_nav, h_mdd, h_n = _sim_two_half_slots(df[(df["buy_date"] >= "2022-01-04") & (df["buy_date"] <= "2026-11-10")])
    res["half2_5y"] = {"nav": round(h_nav, 3), "mdd_pct": round(h_mdd * 100.0, 2), "n": int(h_n)}
    ann = {}
    for yr in ["2022", "2023", "2024", "2025", "2026"]:
        ann[yr] = _slice_metrics(df[df["buy_date"].str.startswith(yr)], f"{yr}-01-01", f"{yr}-12-31" if yr != "2026" else "2026-11-10")
    res["annual"] = ann
    return res

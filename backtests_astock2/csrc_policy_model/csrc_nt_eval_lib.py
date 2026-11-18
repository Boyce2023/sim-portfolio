#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Helper library for zero-lookahead D15 evaluation of panel & event factors (F145 - F162)."""
import numpy as np
import pandas as pd
from scipy import stats


def build_cum_levels(panel: pd.DataFrame) -> pd.DataFrame:
    p = panel.sort_values("date").reset_index(drop=True).copy()
    for ps in ["bench", "ew", "micro30", "large10", "tech_board", "csi300", "csi1000", "csi500", "sse50", "chinext", "star50"]:
        cc_col, gap_col = f"{ps}_cc_ret", f"{ps}_gap_ret"
        if cc_col not in p.columns:
            continue
        cl = (1.0 + p[cc_col].fillna(0.0)).cumprod()
        op = cl.shift(1).fillna(1.0) * (1.0 + p[gap_col].fillna(0.0))
        p[f"_{ps}_op"] = op
        p[f"_{ps}_cl"] = cl
    return p


def forward_ret(p: pd.DataFrame, entry_idx: int, asset: str, h: int) -> float:
    ex = entry_idx + h - 1
    if entry_idx < 0 or ex >= len(p):
        return np.nan
    op = p.at[entry_idx, f"_{asset}_op"]
    cl = p.at[ex, f"_{asset}_cl"]
    if pd.isna(op) or pd.isna(cl) or op <= 0:
        return np.nan
    return float(cl / op - 1.0)


def stats_arr(vals, exp_dir=1):
    arr = np.asarray(vals, dtype=float)
    arr = arr[np.isfinite(arr)]
    n = len(arr)
    if n == 0:
        return {"n": 0, "mean": np.nan, "median": np.nan, "win_rate": np.nan, "payoff": np.nan, "t_stat": np.nan, "p_val": np.nan}
    d = arr * exp_dir
    wins, losses = d[d > 0], -d[d < 0]
    wr = float(np.mean(d > 0))
    po = float(np.mean(wins) / np.mean(losses)) if (len(wins) and len(losses) and np.mean(losses) > 1e-8) else (9.99 if len(wins) else 0.0)
    t_st, p_v = (stats.ttest_1samp(arr, 0.0) if n >= 3 and np.std(arr, ddof=1) > 1e-9 else (np.nan, np.nan))
    return {"n": n, "mean": float(np.mean(arr)), "median": float(np.median(arr)), "win_rate": wr, "payoff": po, "t_stat": float(t_st), "p_val": float(p_v)}


def single_slot_stats(entry_indices, vals, h, exp_dir=1):
    pairs = sorted([(int(i), float(v)) for i, v in zip(entry_indices, vals) if i >= 0 and np.isfinite(v)], key=lambda x: x[0])
    taken, nf = [], -1
    for idx, v in pairs:
        if idx >= nf:
            taken.append(v)
            nf = idx + max(1, h)
    st = stats_arr(taken, exp_dir=exp_dir)
    st["compound_ret"] = float(np.prod(1.0 + np.clip(np.array(taken) * exp_dir, -0.5, 1.5)) - 1.0) if taken else np.nan
    return st


def eval_target_series(p: pd.DataFrame, entry_indices, target: str, h: int, uncond_bench_means: dict):
    out = []
    for idx in entry_indices:
        if idx < 0 or idx + h - 1 >= len(p):
            out.append(np.nan)
            continue
        if target == "bench":
            out.append(forward_ret(p, idx, "bench", h))
        elif target == "bench_excess":
            out.append(forward_ret(p, idx, "bench", h) - uncond_bench_means.get(h, 0.0))
        elif "_vs_" in target:
            a, b = target.split("_vs_", 1)
            va, vb = forward_ret(p, idx, a, h), forward_ret(p, idx, b, h)
            out.append(va - vb if np.isfinite(va) and np.isfinite(vb) else np.nan)
        else:
            vt, vb = forward_ret(p, idx, target, h), forward_ret(p, idx, "bench", h)
            out.append(vt - vb if np.isfinite(vt) and np.isfinite(vb) else np.nan)
    return np.array(out, dtype=float)

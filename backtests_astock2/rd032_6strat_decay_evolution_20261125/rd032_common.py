#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD032 Common Statistical Engine, Windows, BH-FDR, Permutation & Strategy Metrics (NO yfinance)."""
import json
import math
import sys
import numpy as np
import pandas as pd
from scipy import stats

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden!"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
OUT_DIR = f"{SIM}/backtests_astock2/rd032_6strat_decay_evolution_20261125"
RD028_DIR = f"{SIM}/backtests_astock2/rd028_old_hot_stock_6strat_5y_20261125"
IDX_JSON = f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json"

STRATS = ["1to2", "2to3", "3to4", "high", "pry", "20cm"]
STRAT_CN = {
    "1to2": "一进二 V20",
    "2to3": "二进三 V2.1",
    "3to4": "三进四 V4.1",
    "high": "高标首阴 V5.1",
    "pry": "超跌撬板 V2.1",
    "20cm": "20cm首板深水 V1.1",
}

# Active strategy rolling CUSUM / trailing-N health thresholds (strategy_astock.md Section 9)
STRAT_HEALTH_CFG = {
    "3to4": {"n_win": 20, "wr_y": 40.0, "wr_r": 35.0, "mean_y": -1.32, "mean_r": -2.86, "cl_y": 6, "cl_r": 7},
    "high": {"n_win": 15, "wr_y": 46.7, "wr_r": 40.0, "mean_y": 2.30, "mean_r": 1.17, "cl_y": 5, "cl_r": 6},
    "pry": {"n_win": 10, "wr_y": 70.0, "wr_r": 60.0, "mean_y": 1.32, "mean_r": -0.72, "cl_y": 2, "cl_r": 3},
    "2to3": {"n_win": 20, "wr_y": 30.0, "wr_r": 25.0, "mean_y": 0.06, "mean_r": -0.91, "cl_y": 9, "cl_r": 10},
    "1to2": {"n_win": 20, "wr_y": 45.0, "wr_r": 40.0, "mean_y": 1.12, "mean_r": 0.26, "cl_y": 5, "cl_r": 6},
    "20cm": {"n_win": 20, "wr_y": 30.0, "wr_r": 25.0, "mean_y": -1.94, "mean_r": -2.65, "cl_y": 9, "cl_r": 10},
}


def sf(v, digits=4):
    if v is None:
        return None
    fv = float(v)
    return None if (math.isnan(fv) or math.isinf(fv)) else round(fv, digits)


def get_windows(as_of: str) -> dict:
    ts = pd.Timestamp(as_of)
    w1y_start = (ts.replace(day=1) - pd.DateOffset(years=1)).strftime("%Y-%m-%d")
    h_start_dt = pd.Timestamp(f"{ts.year}-07-01" if ts.month >= 7 else f"{ts.year}-01-01")
    if (ts - h_start_dt).days < 45:
        h_start_dt = ts - pd.Timedelta(days=150)
    h_start = h_start_dt.strftime("%Y-%m-%d")
    q_cur = pd.Period(ts, freq="Q")
    quarters = [str(q_cur - k) for k in range(4, -1, -1)]
    return {"as_of": as_of, "w1y_start": w1y_start, "h_start": h_start, "quarters": quarters}


def bh_fdr(pvals) -> np.ndarray:
    arr = np.asarray([np.nan if p is None else float(p) for p in pvals], dtype=float)
    out = np.full(len(arr), np.nan, dtype=float)
    valid = np.isfinite(arr)
    m = int(valid.sum())
    if m == 0:
        return out
    pv = np.clip(arr[valid], 0.0, 1.0)
    order = np.argsort(pv)
    ranks = np.arange(1, m + 1, dtype=float)
    qs = np.minimum.accumulate((pv[order] * m / ranks)[::-1])[::-1]
    qv = np.empty(m, dtype=float)
    qv[order] = np.clip(qs, 0.0, 1.0)
    out[valid] = qv
    return out


def perm_spearman(x: np.ndarray, y: np.ndarray, rng: np.random.Generator, n_perm: int = 2000) -> tuple:
    valid = np.isfinite(x) & np.isfinite(y)
    xv, yv = x[valid], y[valid]
    n = len(xv)
    if n < 8 or np.unique(xv).size < 2 or np.unique(yv).size < 2:
        return None, None, None
    rho, p_asym = stats.spearmanr(xv, yv)
    rx = stats.rankdata(xv).astype(float)
    ry = stats.rankdata(yv).astype(float)
    rx0, ry0 = rx - rx.mean(), ry - ry.mean()
    nx, ny = np.linalg.norm(rx0), np.linalg.norm(ry0)
    if nx < 1e-12 or ny < 1e-12:
        return None, None, None
    rx_u, ry_u = rx0 / nx, ry0 / ny
    perm_idx = np.argsort(rng.random((n, n_perm)), axis=0)
    prhos = rx_u @ ry_u[perm_idx]
    p_perm = float((np.sum(np.abs(prhos) >= abs(float(rho)) - 1e-12) + 1.0) / (n_perm + 1.0))
    return sf(rho, 4), sf(p_asym, 6), sf(p_perm, 5)


def perm_diff_mean(r1: np.ndarray, r0: np.ndarray, rng: np.random.Generator, n_perm: int = 2000) -> dict:
    n1, n0 = len(r1), len(r0)
    if n1 < 2 or n0 < 2:
        return {"n1": n1, "n0": n0, "wr_diff_pp": None, "mean_diff_pp": None, "welch_p": None, "p_perm": None}
    wr1, wr0 = float((r1 > 0).mean() * 100.0), float((r0 > 0).mean() * 100.0)
    m1, m0 = float(r1.mean() * 100.0), float(r0.mean() * 100.0)
    _, wp = stats.ttest_ind(r1, r0, equal_var=False)
    comb = np.concatenate([r1, r0])
    obs_diff = abs(float(r1.mean() - r0.mean()))
    tot = n1 + n0
    p_idx = np.argsort(rng.random((tot, n_perm)), axis=0)[:n1, :]
    m1_p = comb[p_idx].mean(axis=0)
    m0_p = (comb.sum() - comb[p_idx].sum(axis=0)) / n0
    p_perm = float((np.sum(np.abs(m1_p - m0_p) >= obs_diff - 1e-12) + 1.0) / (n_perm + 1.0))
    return {
        "n1": int(n1), "n0": int(n0),
        "wr1_pct": sf(wr1, 2), "wr0_pct": sf(wr0, 2), "wr_diff_pp": sf(wr1 - wr0, 2),
        "mean1_pct": sf(m1, 2), "mean0_pct": sf(m0, 2), "mean_diff_pp": sf(m1 - m0, 2),
        "welch_p": sf(wp, 5) if np.isfinite(wp) else None, "p_perm": sf(p_perm, 5),
        "small_sample_warn": bool(n1 < 30 or n0 < 30),
    }


def load_csi300():
    raw = json.load(open(IDX_JSON, encoding="utf-8"))
    sh300 = {k: float(v) for k, v in raw["sh000300"].items()}
    sh_idx = {k: float(v) for k, v in raw["sh000002"].items()}
    sz_idx = {k: float(v) for k, v in raw["sz399107"].items()}
    dts = sorted(sh300.keys())
    prev_td = {dts[i]: dts[i - 1] for i in range(1, len(dts))}
    return sh300, sh_idx, sz_idx, dts, prev_td


def calc_slot_summary(df: pd.DataFrame, sh300: dict, dts: list, prev_td: dict) -> dict:
    if df.empty:
        return {"n": 0, "wr_pct": 0.0, "plr": 0.0, "mean_ret_pct": 0.0, "nav": 1.0, "mdd_pct": 0.0, "csi_pct": 0.0, "excess_pp": 0.0}
    sub = df.sort_values(["buy_date", "code"])
    rets = sub["net_ret"].to_numpy(float)
    w, l = rets[rets > 0], rets[rets <= 0]
    plr = float(w.mean() / abs(l.mean())) if (len(w) and len(l) and l.mean() < 0) else (99.0 if len(w) else 0.0)
    nc = np.cumprod(1.0 + rets)
    pk = np.maximum.accumulate(np.insert(nc, 0, 1.0))[1:]
    mdd = float(np.max((pk - nc) / pk) * 100.0)
    sdt, edt = str(sub["buy_date"].min()), str(sub["exit_date"].max())
    p0 = prev_td.get(sdt) or ([d for d in dts if d < sdt][-1] if any(d < sdt for d in dts) else dts[0])
    pe = edt if edt in sh300 else ([d for d in dts if d <= edt][-1] if any(d <= edt for d in dts) else dts[-1])
    csi_pct = (sh300[pe] / sh300[p0] - 1.0) * 100.0
    nav = float(nc[-1])
    return {
        "n": int(len(rets)),
        "wr_pct": sf((rets > 0).mean() * 100.0, 2),
        "plr": sf(plr, 2),
        "mean_ret_pct": sf(rets.mean() * 100.0, 2),
        "nav": sf(nav, 2),
        "mdd_pct": sf(mdd, 2),
        "csi_pct": sf(csi_pct, 2),
        "excess_pp": sf((nav - 1.0) * 100.0 - csi_pct, 2),
    }


def sanitize_json(obj):
    if isinstance(obj, dict):
        return {k: sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_json(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return None if (math.isnan(v) or math.isinf(v)) else v
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    return obj

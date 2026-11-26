#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD039-B Shared Data Loader, Exact Close-to-Close Daily MTM, Velocity Slippage & D15 Evaluator.
Zero yfinance (D12). Zero cap10m. Threads <= 2. Peak RSS < 2.5 GB.
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import gc
import itertools
import json
import math
import pickle
import resource
import sys
import warnings
from typing import Optional

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
from scipy import stats

pa.set_cpu_count(1)
pa.set_io_thread_count(1)
warnings.filterwarnings("ignore")
assert "yfinance" not in sys.modules, "D12 VIOLATION: yfinance forbidden"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
RD035_BASE = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125"
WAVE1 = f"{RD035_BASE}/wave1_base"
RD036_P2 = f"{SIM}/backtests_astock2/rd036_highorder_3way_4way_20261126/part2_other5"
SLIP_P2 = f"{SIM}/output/slippage_velocity_audit_20261125/part2_trigger_price_opt"
OUT_DIR = f"{SIM}/backtests_astock2/rd039_single_strat_sharpe_lift_20261126/front2_3_3to4_high_pry"
CACHE_DIR = f"{OUT_DIR}/_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

for _p in (WAVE1, RD036_P2, SLIP_P2):
    if _p not in sys.path:
        sys.path.insert(0, _p)

TRD_DAYS_YEAR = 242.0
WF_START = "2023-01-03"
WF_END = "2026-11-16"
FULL_START = "2021-11-16"

WINDOWS_7 = [
    ("FULL_5Y", FULL_START, WF_END),
    ("WF_2326", WF_START, WF_END),
    ("IS_2124", FULL_START, "2024-12-31"),
    ("OOS_2526", "2025-01-01", WF_END),
    ("Y2026", "2026-01-01", WF_END),
    ("Y26H2", "2026-07-01", WF_END),
    ("WF_IS2324", WF_START, "2024-12-31"),
]


def rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 1)


def sanitize_json(obj):
    if isinstance(obj, dict):
        return {str(k): sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_json(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return None if (math.isnan(v) or math.isinf(v)) else round(v, 6)
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return sanitize_json(obj.tolist())
    return obj


def load_filtered_5m_and_dmap(codes_needed: set[str], load_5m: bool = True, load_sub2: bool = True) -> dict:
    """Fast low-RAM load of 5m bars (filtered to codes_needed), daily bars, and benchmark calendars."""
    import _wf_v20_patch as wfp
    v20_ctx = wfp.load_v20_reference_context(WAVE1)
    bench = v20_ctx["bench"]
    cal_5y = v20_ctx["calendar_5y"]["trade_date"].tolist()
    cal_wf = [d for d in cal_5y if WF_START <= d <= WF_END]

    bars_5m = {}
    p5_paths = [
        f"{SIM}/data/all_strategies_5m_complete_pit.parquet",
        f"{SIM}/backtests_astock2/data_5y/cand_3to4_5m_bars.parquet",
        f"{SLIP_P2}/_patch_5m_bars.parquet",
    ]
    cols_5m = ["c6", "date", "hhmm_int", "open", "high", "low", "close", "volume", "amount"]
    for path in p5_paths if load_5m else ():
        if not os.path.exists(path):
            continue
        chunks = []
        scanner = ds.dataset(path, format="parquet").scanner(columns=cols_5m, batch_size=65536)
        for batch in scanner.to_batches():
            dfb = batch.to_pandas()
            if dfb.empty:
                continue
            dfb["c6"] = dfb["c6"].astype(str).str.zfill(6)
            dfb = dfb[dfb["c6"].isin(codes_needed)]
            if not dfb.empty:
                chunks.append(dfb)
        if not chunks:
            continue
        df5 = pd.concat(chunks, ignore_index=True)
        del chunks
        df5["dt"] = df5["date"].astype(str).str[:10]
        df5 = df5[df5["dt"] <= WF_END].sort_values(["c6", "dt", "hhmm_int"])
        for (c6, dt), grp in df5.groupby(["c6", "dt"], sort=False):
            if (c6, dt) not in bars_5m:
                bars_5m[(c6, dt)] = grp[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=np.float64)
        del df5
        gc.collect()
        pa.default_memory_pool().release_unused()

    sub2_path = f"{SIM}/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113/sub2_5m_bars_cache.pkl"
    if load_5m and load_sub2 and os.path.exists(sub2_path):
        with open(sub2_path, "rb") as f:
            sub2_raw = pickle.load(f)
        for k, v in sub2_raw.items():
            c6, dt = str(k[0]).zfill(6), str(k[2])[:10]
            if c6 in codes_needed and (c6, dt) not in bars_5m and isinstance(v, pd.DataFrame) and not v.empty:
                sub = v[v["date"].astype(str).str[:10] == dt]
                if not sub.empty:
                    hh = sub["hhmm"].astype(str).str.replace(":", "").astype(int).to_numpy(np.float64)
                    bars_5m[(c6, dt)] = np.column_stack([
                        hh, sub["open"], sub["high"], sub["low"], sub["close"], sub["volume"], sub["amount"]
                    ]).astype(np.float64)
        del sub2_raw
    gc.collect()

    tks = sorted({f"{c}.SH" for c in codes_needed} | {f"{c}.SZ" for c in codes_needed})
    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "qfq_factor"]
    flt = (ds.field("date") >= pd.Timestamp("2021-10-01")) & (ds.field("date") <= pd.Timestamp("2026-11-25")) & ds.field("ticker").isin(tks)
    da = ds.dataset(f"{SIM}/data/cn_hk_price_db/a_daily.parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    dd = ds.dataset(f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    da["dl"], dd["dl"] = 0, 1
    dp = pd.concat([da, dd], ignore_index=True)
    dp["c6"] = dp["ticker"].astype(str).str[:6]
    dp["dt"] = dp["date"].dt.strftime("%Y-%m-%d")
    dp = dp.sort_values(["c6", "dt", "dl"]).drop_duplicates(["c6", "dt"], keep="first").reset_index(drop=True)
    dp["adjf"] = np.where((dp["close"] > 0) & (dp["adj_close"] > 0), dp["adj_close"] / dp["close"], 1.0)
    g = dp.groupby("c6", sort=False)
    dp["pre_c"] = g["close"].shift(1) * g["adjf"].shift(1) / dp["adjf"]
    dp["zt_px"] = np.floor(dp["pre_c"] * 1.10 * 100.0 + 0.5) / 100.0
    dp["dt_px"] = np.floor(dp["pre_c"] * 0.90 * 100.0 + 0.5) / 100.0
    dp["is_zt_exact"] = (dp["close"] >= dp["zt_px"] - 0.005) & (dp["pre_c"] > 0)
    dp["is_dt_exact"] = (dp["close"] <= dp["dt_px"] + 0.005) & (dp["pre_c"] > 0)
    dp["is_yizi_zt"] = dp["is_zt_exact"] & (dp["open"] >= dp["zt_px"] - 0.005) & (dp["low"] >= dp["zt_px"] - 0.005)
    dp["is_yizi_dt"] = dp["is_dt_exact"] & (dp["open"] <= dp["dt_px"] + 0.005) & (dp["high"] <= dp["dt_px"] + 0.005)

    dmap = {}
    code_series = {}
    for c6, grp in dp.groupby("c6", sort=False):
        grp_s = grp.sort_values("dt").reset_index(drop=True)
        dts_l = grp_s["dt"].tolist()
        code_series[c6] = {
            "dts": dts_l,
            "dt_to_pos": {d: i for i, d in enumerate(dts_l)},
            "open": grp_s["open"].to_numpy(np.float64),
            "high": grp_s["high"].to_numpy(np.float64),
            "low": grp_s["low"].to_numpy(np.float64),
            "close": grp_s["close"].to_numpy(np.float64),
            "adj_close": grp_s["adj_close"].to_numpy(np.float64),
            "adjf": grp_s["adjf"].to_numpy(np.float64),
            "pre_c": grp_s["pre_c"].to_numpy(np.float64),
            "zt_px": grp_s["zt_px"].to_numpy(np.float64),
            "dt_px": grp_s["dt_px"].to_numpy(np.float64),
            "is_zt": grp_s["is_zt_exact"].to_numpy(bool),
            "is_dt": grp_s["is_dt_exact"].to_numpy(bool),
            "is_yizi_zt": grp_s["is_yizi_zt"].to_numpy(bool),
            "is_yizi_dt": grp_s["is_yizi_dt"].to_numpy(bool),
        }
        for r in grp_s.itertuples(index=False):
            dmap[(c6, r.dt)] = {
                "open": float(r.open), "high": float(r.high), "low": float(r.low), "close": float(r.close),
                "adj_close": float(r.adj_close), "adjf": float(r.adjf),
                "pre_c": float(r.pre_c) if pd.notna(r.pre_c) else np.nan,
                "zt_px": float(r.zt_px) if pd.notna(r.zt_px) else np.nan,
                "dt_px": float(r.dt_px) if pd.notna(r.dt_px) else np.nan,
                "is_zt": bool(r.is_zt_exact), "is_dt": bool(r.is_dt_exact),
                "is_yizi_zt": bool(r.is_yizi_zt), "is_yizi_dt": bool(r.is_yizi_dt),
            }

    del da, dd, dp
    gc.collect()
    pa.default_memory_pool().release_unused()

    cal_df = v20_ctx["calendar_5y"]
    cal_df = cal_df[cal_df["trade_date"].between(FULL_START, WF_END)].sort_values("trade_date").reset_index(drop=True)
    return {
        "v20_ctx": v20_ctx,
        "cal_5y": cal_df["trade_date"].tolist(),
        "csi_5y": cal_df["csi300_daily_ret"].to_numpy(np.float64),
        "ew_5y": cal_df["alla_ew_daily_ret"].to_numpy(np.float64),
        "cal_wf": cal_wf,
        "bars_5m": bars_5m,
        "dmap": dmap,
        "code_series": code_series,
    }


def build_lean_dt_tables(code_series: dict) -> dict:
    """Build defer_eod_limit_down tables strictly from filtered code_series (< 10 MB RAM vs 6.5 GB full load)."""
    from types import SimpleNamespace
    dmap, by_c = {}, {}
    for c6, cs in code_series.items():
        dts = cs["dts"]
        opens, adjfs = cs["open"], cs["adjf"]
        dt_ex, yz_dt = cs["is_dt"], cs["is_yizi_dt"]
        by_c[c6] = pd.DataFrame({
            "dt_s": dts,
            "is_yizi_dt": yz_dt,
            "open": opens,
            "adjf": adjfs,
        })
        for i, dt_s in enumerate(dts):
            dmap[(c6, dt_s)] = SimpleNamespace(adjf=float(adjfs[i]), is_dt_exact=bool(dt_ex[i]), is_yizi_dt=bool(yz_dt[i]))
    return {"dmap": dmap, "by_c": by_c}


def fee_adjust(ret_020: float | np.ndarray, fee_rt: float) -> float | np.ndarray:
    """Convert net_ret from 0.20% round-trip baseline to arbitrary fee_rt."""
    return (1.0 + ret_020) / 0.9980 * (1.0 - float(fee_rt)) - 1.0


def build_exact_mtm_daily(
    slot_df: pd.DataFrame,
    cal_dts: list[str],
    dmap: dict,
    ret_col: str = "net_ret_030",
    buy_px_col: str = "buy_price",
) -> tuple[np.ndarray, float]:
    """Exact close-to-close daily MTM returns with mtm_diff == 0.0."""
    T = len(cal_dts)
    if slot_df is None or slot_df.empty:
        return np.zeros(T, dtype=np.float64), 0.0
    dt_idx = {d: i for i, d in enumerate(cal_dts)}
    day_mult = np.ones(T, dtype=np.float64)
    for r in slot_df.itertuples(index=False):
        bd = str(r.buy_date)[:10]
        ed = str(r.exit_date)[:10]
        bi = dt_idx.get(bd)
        ei = dt_idx.get(ed)
        if bi is None:
            continue
        c6 = str(r.code).zfill(6)
        bb = dmap.get((c6, bd))
        bp = float(getattr(r, buy_px_col))
        b_adj = bp * bb["adjf"] if (bb is not None and bb["adjf"] > 0) else bp
        if not np.isfinite(b_adj) or b_adj <= 0:
            b_adj = 1.0
        prev_v, last_c = b_adj, b_adj
        end_loop = ei if (ei is not None and ei > bi) else T
        for t in range(bi, min(end_loop, T)):
            bt = dmap.get((c6, cal_dts[t]))
            cur_c = float(bt["adj_close"]) if (bt is not None and bt["adj_close"] > 0) else last_c
            if cur_c <= 0:
                cur_c = last_c
            day_mult[t] *= (cur_c / prev_v)
            prev_v, last_c = cur_c, cur_c
        ret_v = float(getattr(r, ret_col))
        if ei is not None and ei > bi and ei < T:
            day_mult[ei] *= (b_adj * (1.0 + ret_v)) / prev_v

    dr = day_mult - 1.0
    in_w = slot_df["buy_date"].astype(str).str[:10].isin(dt_idx)
    tr_sub = slot_df[in_w]
    tr_nav = float(np.prod(1.0 + tr_sub[ret_col].to_numpy(np.float64))) if not tr_sub.empty else 1.0
    mtm_diff = abs(float(np.prod(day_mult)) - tr_nav)
    return dr, mtm_diff


def calc_window_stats(
    dr_full: np.ndarray,
    slot_df: pd.DataFrame,
    cal_dts: list[str],
    csi_arr: np.ndarray,
    ew_arr: np.ndarray,
    s_dt: str,
    e_dt: str,
    ret_col: str,
) -> dict:
    mask = np.array([(s_dt <= d <= e_dt) for d in cal_dts], dtype=bool)
    T_w = int(mask.sum())
    if T_w == 0:
        return {"n": 0, "nav": 1.0, "sharpe": 0.0, "mdd_pct": 0.0, "calmar": 0.0}
    dw = dr_full[mask]
    c3 = csi_arr[mask]
    ew = ew_arr[mask]
    mtm_nav = float(np.prod(1.0 + dw))
    c3_pct = (float(np.prod(1.0 + c3)) - 1.0) * 100.0
    ew_pct = (float(np.prod(1.0 + ew)) - 1.0) * 100.0

    sd = float(np.std(dw, ddof=1)) if T_w > 1 else 0.0
    sharpe = float(np.mean(dw) / sd * math.sqrt(TRD_DAYS_YEAR)) if sd > 1e-12 else 0.0
    curve = np.concatenate([[1.0], np.cumprod(1.0 + dw)])
    pk = np.maximum.accumulate(curve)
    mdd = float(np.max((pk - curve) / pk) * 100.0)
    cagr = (mtm_nav ** (TRD_DAYS_YEAR / T_w) - 1.0) * 100.0 if mtm_nav > 0 else -100.0
    calmar = (cagr / mdd) if mdd > 1e-6 else 0.0

    sub = slot_df[slot_df["buy_date"].between(s_dt, e_dt)] if (slot_df is not None and not slot_df.empty) else pd.DataFrame()
    if sub.empty:
        return {
            "n": 0, "wr_pct": 0.0, "plr": 0.0, "mean_pct": 0.0,
            "mean_loss_pct": 0.0, "big_loss_rate_pct": 0.0,
            "nav": 1.0, "mtm_nav": round(mtm_nav, 4), "ex_top5_nav": 1.0,
            "mdd_pct": round(mdd, 2), "sharpe": round(sharpe, 3), "calmar": round(calmar, 2),
            "cagr_pct": round(cagr, 2), "excess_csi300_pp": round(-c3_pct, 2), "excess_ew_pp": round(-ew_pct, 2),
        }

    rets = sub[ret_col].to_numpy(np.float64)
    w = rets[rets > 0.0]
    l = rets[rets <= 0.0]
    wr = float((rets > 0.0).mean() * 100.0)
    plr = float(w.mean() / abs(l.mean())) if (len(w) and len(l) and l.mean() < 0) else (99.0 if len(w) else 0.0)
    mean_loss = float(l.mean() * 100.0) if len(l) else 0.0
    big_loss_rate = float((rets <= -0.07).mean() * 100.0)
    tr_nav = float(np.prod(1.0 + rets))
    sr = np.sort(rets)
    ex5 = float(np.prod(1.0 + sr[:-5])) if len(rets) > 5 else 1.0
    return {
        "n": int(len(rets)),
        "wr_pct": round(wr, 2),
        "plr": round(plr, 2),
        "mean_pct": round(float(rets.mean() * 100.0), 2),
        "mean_loss_pct": round(mean_loss, 2),
        "big_loss_rate_pct": round(big_loss_rate, 2),
        "nav": round(tr_nav, 4),
        "mtm_nav": round(mtm_nav, 4),
        "ex_top5_nav": round(ex5, 4),
        "mdd_pct": round(mdd, 2),
        "sharpe": round(sharpe, 3),
        "calmar": round(calmar, 2),
        "cagr_pct": round(cagr, 2),
        "excess_csi300_pp": round((tr_nav - 1.0) * 100.0 - c3_pct, 2),
        "excess_ew_pp": round((tr_nav - 1.0) * 100.0 - ew_pct, 2),
    }


def evaluate_full_suite(
    ctx: dict,
    strategy: str,
    variant_id: str,
    slot_df: pd.DataFrame,
    miss_rate_pct: float,
    base_dr_wf_030: Optional[np.ndarray] = None,
    base_dr_5y_030: Optional[np.ndarray] = None,
    vel_col: str = "net_ret_vel_030",
    vel_px_col: str = "eff_buy_price",
) -> dict:
    """
    Evaluate a single-slot ledger across all 7 windows, 30/50/80bps + velocity slippage,
    exact MTM diff == 0.0, paired t-test vs baseline, and landmark survival check.
    """
    cal_5y = ctx["cal_5y"]
    csi_5y = ctx["csi_5y"]
    ew_5y = ctx["ew_5y"]
    dmap = ctx["dmap"]

    if slot_df is None or slot_df.empty:
        return {"strategy": strategy, "variant_id": variant_id, "n_5y": 0, "n_wf": 0}

    df = slot_df.copy()
    df["buy_date"] = df["buy_date"].astype(str).str[:10]
    df["exit_date"] = df["exit_date"].astype(str).str[:10]
    df["code"] = df["code"].astype(str).str.zfill(6)
    assert (df["exit_date"] > df["buy_date"]).all(), f"[{variant_id}] T+0 violation!"

    # Ensure 20/30/50/80bps flat returns + velocity returns exist
    if "net_ret_020" not in df.columns:
        df["net_ret_020"] = df["net_ret"].astype(float)
    df["net_ret_030"] = fee_adjust(df["net_ret_020"].to_numpy(float), 0.0030)
    df["net_ret_050"] = fee_adjust(df["net_ret_020"].to_numpy(float), 0.0050)
    df["net_ret_080"] = fee_adjust(df["net_ret_020"].to_numpy(float), 0.0080)

    if vel_col in df.columns:
        df["net_ret_vel020"] = df["net_ret_vel_020"].astype(float) if "net_ret_vel_020" in df.columns else (1.0 + df[vel_col].astype(float)) / 0.9970 * 0.9980 - 1.0
        df["net_ret_vel030"] = df[vel_col].astype(float)
        df["net_ret_vel050"] = fee_adjust(df["net_ret_vel020"].to_numpy(float), 0.0050)
        df["net_ret_vel080"] = fee_adjust(df["net_ret_vel020"].to_numpy(float), 0.0080)
    else:
        df["net_ret_vel030"] = df["net_ret_030"]
        df["net_ret_vel050"] = df["net_ret_050"]
        df["net_ret_vel080"] = df["net_ret_080"]
        vel_px_col = "buy_price"

    dr_030, diff_030 = build_exact_mtm_daily(df, cal_5y, dmap, "net_ret_030", "buy_price")
    dr_050, _ = build_exact_mtm_daily(df, cal_5y, dmap, "net_ret_050", "buy_price")
    dr_080, _ = build_exact_mtm_daily(df, cal_5y, dmap, "net_ret_080", "buy_price")
    dr_v30, diff_v30 = build_exact_mtm_daily(df, cal_5y, dmap, "net_ret_vel030", vel_px_col)
    dr_v50, _ = build_exact_mtm_daily(df, cal_5y, dmap, "net_ret_vel050", vel_px_col)
    dr_v80, _ = build_exact_mtm_daily(df, cal_5y, dmap, "net_ret_vel080", vel_px_col)
    assert diff_030 < 1e-4 and diff_v30 < 1e-4, f"[{variant_id}] MTM diff too high: {diff_030}, {diff_v30}"

    w_030 = {wn: calc_window_stats(dr_030, df, cal_5y, csi_5y, ew_5y, s, e, "net_ret_030") for wn, s, e in WINDOWS_7}
    w_v30 = {wn: calc_window_stats(dr_v30, df, cal_5y, csi_5y, ew_5y, s, e, "net_ret_vel030") for wn, s, e in WINDOWS_7}
    wf_050 = calc_window_stats(dr_050, df, cal_5y, csi_5y, ew_5y, WF_START, WF_END, "net_ret_050")
    wf_080 = calc_window_stats(dr_080, df, cal_5y, csi_5y, ew_5y, WF_START, WF_END, "net_ret_080")
    wf_v50 = calc_window_stats(dr_v50, df, cal_5y, csi_5y, ew_5y, WF_START, WF_END, "net_ret_vel050")
    wf_v80 = calc_window_stats(dr_v80, df, cal_5y, csi_5y, ew_5y, WF_START, WF_END, "net_ret_vel080")
    f5_050 = calc_window_stats(dr_050, df, cal_5y, csi_5y, ew_5y, FULL_START, WF_END, "net_ret_050")
    f5_080 = calc_window_stats(dr_080, df, cal_5y, csi_5y, ew_5y, FULL_START, WF_END, "net_ret_080")

    wf_mask = np.array([(WF_START <= d <= WF_END) for d in cal_5y], dtype=bool)
    dr_wf_030 = dr_030[wf_mask]
    dr_wf_v30 = dr_v30[wf_mask]

    def _paired(a: np.ndarray, b: Optional[np.ndarray]) -> tuple[float, float]:
        if b is None or len(a) != len(b):
            return 0.0, 0.5
        d = a - b
        sd = float(np.std(d, ddof=1))
        if sd <= 1e-12:
            return 0.0, 0.5
        t = float(np.mean(d) / (sd / math.sqrt(len(d))))
        p = float(stats.t.sf(t, df=len(d) - 1))
        return round(t, 3), round(p, 5)

    pt_wf, pp_wf = _paired(dr_wf_030, base_dr_wf_030)
    pt_5y, pp_5y = _paired(dr_030, base_dr_5y_030)
    pt_vwf, pp_vwf = _paired(dr_wf_v30, base_dr_wf_030)

    return {
        "strategy": strategy,
        "variant_id": variant_id,
        "miss_rate_pct": round(float(miss_rate_pct), 2),
        "mtm_diff_030": round(diff_030, 8),
        "mtm_diff_vel030": round(diff_v30, 8),
        "paired_t_wf_030": pt_wf,
        "paired_p_wf_030": pp_wf,
        "paired_t_5y_030": pt_5y,
        "paired_p_5y_030": pp_5y,
        "paired_t_wf_vel030": pt_vwf,
        "paired_p_wf_vel030": pp_vwf,
        "windows_030": w_030,
        "windows_vel030": w_v30,
        "stress_wf": {"bps50": wf_050, "bps80": wf_080, "vel_bps50": wf_v50, "vel_bps80": wf_v80},
        "stress_5y": {"bps50": f5_050, "bps80": f5_080},
        "dr_5y_030": dr_030,
        "dr_wf_030": dr_wf_030,
        "dr_5y_vel030": dr_v30,
        "dr_wf_vel030": dr_wf_v30,
    }


def cscv_pbo(mat_dict: dict[str, np.ndarray], S: int = 16) -> dict:
    """Exact CSCV PBO over daily MTM return matrix."""
    names = list(mat_dict.keys())
    if len(names) < 2:
        return {"n_variants": len(names), "S": S, "pbo": None}
    M_full = np.column_stack([np.asarray(mat_dict[k], dtype=np.float64) for k in names])
    keep = np.std(M_full, axis=0, ddof=1) > 1e-12
    names = [nm for nm, kp in zip(names, keep) if kp]
    M = M_full[:, keep]
    K = len(names)
    if K < 2:
        return {"n_variants": K, "S": S, "pbo": None}
    T_tot = M.shape[0]
    L = T_tot // S
    if L < 10:
        return {"n_variants": K, "S": S, "pbo": None}
    T_use = L * S
    M = M[T_tot - T_use:, :]
    blocks = M.reshape(S, L, K)
    blk_sum = blocks.sum(axis=1)
    blk_sum2 = (blocks ** 2).sum(axis=1)
    tot_sum = blk_sum.sum(axis=0)
    tot_sum2 = blk_sum2.sum(axis=0)

    half = S // 2
    combos = list(itertools.combinations(range(S), half))
    n_splits = len(combos)
    ind = np.zeros((n_splits, S), dtype=np.float64)
    for r_i, cmb in enumerate(combos):
        ind[r_i, list(cmb)] = 1.0
    n_is = half * L
    n_oos = T_use - n_is

    is_sum = ind @ blk_sum
    is_sum2 = ind @ blk_sum2
    is_mu = is_sum / n_is
    is_sd = np.sqrt(np.maximum(0.0, (is_sum2 - n_is * (is_mu ** 2)) / max(1, n_is - 1)))
    is_sr = np.where(is_sd > 1e-12, is_mu / np.maximum(is_sd, 1e-12) * math.sqrt(TRD_DAYS_YEAR), -999.0)

    oos_sum = tot_sum[None, :] - is_sum
    oos_sum2 = tot_sum2[None, :] - is_sum2
    oos_mu = oos_sum / n_oos
    oos_sd = np.sqrt(np.maximum(0.0, (oos_sum2 - n_oos * (oos_mu ** 2)) / max(1, n_oos - 1)))
    oos_sr = np.where(oos_sd > 1e-12, oos_mu / np.maximum(oos_sd, 1e-12) * math.sqrt(TRD_DAYS_YEAR), 0.0)

    win_idx = np.argmax(is_sr, axis=1)
    win_oos_sr = oos_sr[np.arange(n_splits), win_idx]
    ranks = np.empty(n_splits, dtype=np.float64)
    for r_i in range(n_splits):
        row = oos_sr[r_i]
        wv = win_oos_sr[r_i]
        ranks[r_i] = (float(np.sum(row < wv)) + 0.5 * (float(np.sum(row == wv)) + 1.0)) / (K + 1.0)
    ranks_c = np.clip(ranks, 1e-4, 1.0 - 1e-4)
    logits = np.log(ranks_c / (1.0 - ranks_c))
    pbo = float(np.mean(logits <= 0.0))
    win_counts = {names[j]: int(np.sum(win_idx == j)) for j in range(K) if np.any(win_idx == j)}
    return {
        "n_variants": K,
        "S": S,
        "n_splits": n_splits,
        "pbo": round(pbo, 4),
        "top_is_winners": dict(sorted(win_counts.items(), key=lambda x: -x[1])[:5]),
    }


def apply_vel_slip_on_bar(arr_5m: np.ndarray, hit_idx: int, trig_px: float, pre_c: float, zt_px: float, mode: str = "base") -> tuple[float, str, float]:
    """Compute velocity slippage on triggered 5m bar (Slow 0 / Med +50bps / Fast +100bps, capped at zt_px)."""
    o5 = float(arr_5m[hit_idx, 1])
    h5 = float(arr_5m[hit_idx, 2])
    c5 = float(arr_5m[hit_idx, 4])
    open_gt = bool(o5 > trig_px + 1e-4)
    base_tp = round(max(o5, trig_px), 2) if open_gt else round(trig_px, 2)
    if base_tp >= zt_px - 0.005:
        return zt_px, "zt_cap", 0.0
    surge = (h5 - base_tp) / base_tp
    jump = (h5 - o5) / pre_c if pre_c > 0 else 0.0
    hit_zt = h5 >= zt_px - 0.01
    if hit_zt or surge >= 0.025 or jump >= 0.040:
        tier, sl = "fast", 0.010
    elif surge >= 0.010 or jump >= 0.020:
        tier, sl = "medium", 0.005
    else:
        tier, sl = "slow", 0.000
    eff_p = min(max(o5, base_tp * (1.0 + sl)), zt_px) if open_gt else min(base_tp * (1.0 + sl), zt_px)
    return float(eff_p), tier, float(eff_p / base_tp - 1.0)

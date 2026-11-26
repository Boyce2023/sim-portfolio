#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD043 Step 1: Build 5-Year Tail-Rush Arbitrage (14:30~14:55 -> T+1) Candidate Universe (Strictly PIT).

Covers three physical prototypes + full denominator (including broken limit-ups and T+1 gap-downs):
  - Proto A: Strong mainline / high-recognition stocks surging intraday with strong close near/breaking 10/20/60d high.
  - Proto B: Recognized old dragons (>=2 boards in past 40d) pulling up against market/sentiment ice-point.
  - Proto C: Previous limit-up / consecutive-board stocks absorbing heavy turnover after breaking board & closing green near high.

Strict Anti-Leakage & Memory Guard:
  - Zero yfinance (D12). Peak RSS < 1.3 GB (two-pass row-group extraction).
  - Strictly excludes is_yizi_zt == 1 and close >= zt_px_raw * 0.995 (ensuring tail buyability).
  - Dynamic PIT ST filter from notices + zt_micro_tape in addition to is_st_pit == 0.
  - Computes 5 forward exit trees (E1_T1O, E2_T1C_HoldZT, E2b_PureT1C, E3a_Open0_Hold, E3b_Open15_Hold)
    with full limit-down deferral and exact MTM daily segments.
"""
import os
for _k in (
    "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS",
):
    os.environ[_k] = "1"

import bisect
import gc
import json
import re
import resource
import sqlite3
import sys
import time
import warnings
from collections import defaultdict

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

pa.set_cpu_count(1)
pa.set_io_thread_count(1)
pa.set_memory_pool(pa.system_memory_pool())
warnings.filterwarnings("ignore")

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM_DIR = f"{ROOT}/sim-portfolio"
DATA_DIR = f"{SIM_DIR}/data"
BASE_DIR = f"{SIM_DIR}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
OUT_DIR = f"{SIM_DIR}/backtests_astock2/rd043_tail_rush_arbitrage_20261126"
os.makedirs(OUT_DIR, exist_ok=True)

STOCK_DAY_PQ = f"{BASE_DIR}/stock_day_core_features_pit.parquet"
MKT_DAY_PQ = f"{BASE_DIR}/market_daily_all_new_factors_pit.parquet"
BENCH_PQ = f"{BASE_DIR}/v20_daily_bench_20210104_20261125.parquet"
DB_ZT = f"{DATA_DIR}/zt_micro_tape_5y_pit.db"
REG_TOX_PQ = f"{DATA_DIR}/pit_reg_tox_notices_5y_complete.parquet"

END_BUY_DATE = "2026-11-24"
END_BAR_DATE = "2026-11-25"

ST_ON_RE = re.compile(r"(?:^(?:\*?ST|S\*?ST)|(?:股票交易|股票)(?:被)?实施(?:退市|其他)风险警示|进入退市整理期|作出.*终止上市)")
ST_EXC_RE = re.compile(r"(?:可能被实施|不实施|未实施|免于实施|申请撤销|撤销.*风险警示)")
ST_REV_RE = re.compile(r"(?:撤销(?:退市|其他)风险警示|股票交易撤销.*风险警示)")


def peak_rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 2)


def _read_cols_numpy(cols: list[str], row_idx: np.ndarray | None = None) -> tuple[dict[str, np.ndarray], np.ndarray, np.ndarray]:
    """Stream Parquet row groups directly into compact numpy arrays (or subset by row_idx)."""
    pf = pq.ParquetFile(STOCK_DAY_PQ)
    n_tot = pf.metadata.num_rows
    schema = pf.schema_arrow

    meta = pd.read_parquet(STOCK_DAY_PQ, columns=["dt", "c6"])
    dt_cats = np.array([str(x)[:10] for x in meta["dt"].cat.categories], dtype=object)
    c6_cats = np.array([str(x).zfill(6) for x in meta["c6"].cat.categories], dtype=object)
    dt_id = meta["dt"].cat.codes.to_numpy(np.int16)
    c6_id = meta["c6"].cat.codes.to_numpy(np.int32)
    del meta
    pa.default_memory_pool().release_unused()
    gc.collect()

    if row_idx is None:
        out = {"dt_id": dt_id, "c6_id": c6_id}
        for c in cols:
            pa_t = schema.field(c).type
            np_dt = np.float32 if pa.types.is_floating(pa_t) else (np.int8 if pa.types.is_int8(pa_t) else (np.int16 if pa.types.is_int16(pa_t) else np.int32))
            out[c] = np.empty(n_tot, dtype=np_dt)
        pos = 0
        for rg in range(pf.num_row_groups):
            tbl = pf.read_row_group(rg, columns=cols)
            m = tbl.num_rows
            for c in cols:
                out[c][pos:pos + m] = tbl.column(c).to_numpy(zero_copy_only=False)
            pos += m
            del tbl
            if rg % 10 == 0:
                pa.default_memory_pool().release_unused()
        pa.default_memory_pool().release_unused()
        return out, dt_cats, c6_cats

    # Subset mode: extract only selected row indices cleanly
    n_sel = len(row_idx)
    out = {}
    for c in cols:
        pa_t = schema.field(c).type
        np_dt = np.float32 if pa.types.is_floating(pa_t) else (np.int8 if pa.types.is_int8(pa_t) else (np.int16 if pa.types.is_int16(pa_t) else np.int32))
        out[c] = np.empty(n_sel, dtype=np_dt)

    pos = 0
    sel_ptr = 0
    for rg in range(pf.num_row_groups):
        m = pf.metadata.row_group(rg).num_rows
        rg_end = pos + m
        end_ptr = sel_ptr
        while end_ptr < n_sel and row_idx[end_ptr] < rg_end:
            end_ptr += 1
        if end_ptr > sel_ptr:
            loc_idx = row_idx[sel_ptr:end_ptr] - pos
            tbl = pf.read_row_group(rg, columns=cols)
            for c in cols:
                arr = tbl.column(c).to_numpy(zero_copy_only=False)
                out[c][sel_ptr:end_ptr] = arr[loc_idx]
            del tbl
            sel_ptr = end_ptr
        pos = rg_end
        if rg % 10 == 0:
            pa.default_memory_pool().release_unused()
    pa.default_memory_pool().release_unused()
    return out, dt_cats, c6_cats


def build_pit_st_timeline(end_cutoff: str = END_BAR_DATE) -> dict[str, tuple[list[str], list[int]]]:
    """Build strictly PIT ST status timeline from zt_micro_tape + reg_tox notices."""
    st_ev = defaultdict(list)
    con_z = sqlite3.connect(f"file:{DB_ZT}?mode=ro", uri=True)
    for td, sc6, nm in con_z.execute("SELECT trade_date, sec_code, sec_name FROM zt_micro_tape WHERE trade_date <= ?", (end_cutoff,)):
        s = str(nm or "").strip()
        if s:
            st_ev[str(sc6).zfill(6)].append((f"{td} 15:00:00", 1 if ("ST" in s.upper() or "退" in s) else 0))
    con_z.close()

    rt = pd.read_parquet(REG_TOX_PQ, columns=["sec_code", "pub_datetime_cst", "title"])
    rt["ts"] = rt["pub_datetime_cst"].astype(str).str[:19]
    rt = rt[rt["ts"] <= f"{end_cutoff} 23:59:59"]
    for r in rt.itertuples(index=False):
        t_s = str(r.title or "")
        c6 = str(r.sec_code)[:6].zfill(6)
        if ST_REV_RE.search(t_s):
            st_ev[c6].append((r.ts, 0))
        elif ST_ON_RE.search(t_s) and not ST_EXC_RE.search(t_s):
            st_ev[c6].append((r.ts, 1))
    return {k: ([x[0] for x in sorted(v)], [x[1] for x in sorted(v)]) for k, v in st_ev.items()}


def _calc_exits_and_mtm_tail(
    pos: int, s: int, e: int,
    open_raw: np.ndarray, close_raw: np.ndarray, adj_f: np.ndarray,
    prev_cr: np.ndarray, open_pct: np.ndarray,
    is_zt: np.ndarray, is_dt: np.ndarray, is_yizi_dt: np.ndarray, is_20cm: np.ndarray,
    dt_cats: np.ndarray, dt_id: np.ndarray,
) -> dict:
    """
    Buy at T close (proxy for 14:45 tail rush).
    Compute exact gross returns, exit dates, exit_hhmm, and daily MTM segments:
      - E1_T1O: T+1 Open (with DT deferral up to +10 bars)
      - E2_T1C_HoldZT: T+1 Close if not sealed ZT; if sealed ZT at T+1, hold until streak breaks
      - E2b_PureT1C: T+1 Close unconditionally (deferred only if sealed DT)
      - E3a_Open0_Hold: If T+1 open_pct < 0% -> cut at T+1 Open; else hold to E2_T1C_HoldZT
      - E3b_Open15_Hold: If T+1 open_pct < +1.5% -> cut at T+1 Open; else hold to E2_T1C_HoldZT
    """
    if pos + 1 >= e:
        return {}
    buy_px_adj = float(close_raw[pos]) * float(adj_f[pos])
    if not (buy_px_adj > 0):
        return {}
    lim = 0.20 if is_20cm[pos] == 1 else 0.10

    def _ac(idx: int) -> float:
        return float(close_raw[idx]) * float(adj_f[idx])

    def _ao(idx: int) -> float:
        return float(open_raw[idx]) * float(adj_f[idx])

    def _mtm_to_open(ex_pos: int) -> list[tuple[str, float]]:
        # T close -> T+1 open has multiplier 1.0 on T, and ao(T+1)/ac(T) on T+1!
        segs = []
        for g in range(pos + 1, ex_pos):
            g_dt = str(dt_cats[int(dt_id[g])])
            segs.append((g_dt, _ac(g) / _ac(g - 1)))
        ex_dt = str(dt_cats[int(dt_id[ex_pos])])
        segs.append((ex_dt, _ao(ex_pos) / _ac(ex_pos - 1)))
        return segs

    def _mtm_to_close(ex_pos: int) -> list[tuple[str, float]]:
        segs = []
        for g in range(pos + 1, ex_pos + 1):
            g_dt = str(dt_cats[int(dt_id[g])])
            segs.append((g_dt, _ac(g) / _ac(g - 1)))
        return segs

    out = {}

    # 1. E1_T1O (T+1 Open with DT deferral)
    ex1 = pos + 1
    sold_open = False
    while ex1 < min(e, pos + 11):
        dt_px_ex = round(float(prev_cr[ex1]) * (1.0 - lim), 2)
        if is_yizi_dt[ex1] == 0 and float(open_raw[ex1]) > dt_px_ex + 0.005 and _ao(ex1) > 0:
            sold_open = True
            break
        if is_dt[ex1] == 0 and _ac(ex1) > 0:
            sold_open = False
            break
        ex1 += 1
    if ex1 < e:
        if sold_open and _ao(ex1) > 0:
            gr1 = _ao(ex1) / buy_px_adj - 1.0
            s1 = _mtm_to_open(ex1)
            hh1 = 924
        elif is_dt[ex1] == 0 and _ac(ex1) > 0:
            gr1 = _ac(ex1) / buy_px_adj - 1.0
            s1 = _mtm_to_close(ex1)
            hh1 = 1500
        else:
            gr1, s1, hh1, ex1 = np.nan, [], 1500, -1
        if ex1 > pos and np.isfinite(gr1):
            out["E1_T1O"] = (str(dt_cats[int(dt_id[ex1])]), hh1, gr1, s1, ex1 - pos, int(not sold_open))

    # 2. E2b_PureT1C (T+1 Close with DT deferral)
    ex2b = pos + 1
    while ex2b < min(e - 1, pos + 10) and is_dt[ex2b] != 0:
        ex2b += 1
    if ex2b < e and is_dt[ex2b] == 0 and _ac(ex2b) > 0:
        gr2b = _ac(ex2b) / buy_px_adj - 1.0
        out["E2b_PureT1C"] = (str(dt_cats[int(dt_id[ex2b])]), 1500, gr2b, _mtm_to_close(ex2b), ex2b - pos, 0)

    # 3. E2_T1C_HoldZT (hold while T+1, T+2, ... sealed ZT; exit at first non-ZT & non-DT close)
    ex2 = pos + 1
    while ex2 < min(e - 1, pos + 15) and is_zt[ex2] == 1:
        ex2 += 1
    while ex2 < min(e - 1, pos + 18) and is_dt[ex2] != 0:
        ex2 += 1
    if ex2 < e and is_dt[ex2] == 0 and _ac(ex2) > 0:
        gr2 = _ac(ex2) / buy_px_adj - 1.0
        out["E2_T1C_HoldZT"] = (str(dt_cats[int(dt_id[ex2])]), 1500, gr2, _mtm_to_close(ex2), ex2 - pos, 0)

    # 4. E3a_Open0_Hold & E3b_Open15_Hold (strictly causal T+1 09:25 open_pct decision!)
    t1_op = float(open_pct[pos + 1]) if np.isfinite(open_pct[pos + 1]) else 0.0
    if "E1_T1O" in out and "E2_T1C_HoldZT" in out:
        out["E3a_Open0_Hold"] = out["E1_T1O"] if t1_op < 0.0 else out["E2_T1C_HoldZT"]
        out["E3b_Open15_Hold"] = out["E1_T1O"] if t1_op < 1.5 else out["E2_T1C_HoldZT"]

    return out


def main():
    t0 = time.time()
    print("[Step1] Loading Pass-1 core arrays from stock_day_core_features_pit.parquet...")
    pass1_cols = [
        "open", "high", "low", "close", "adj_factor", "prev_close_raw",
        "ret_1d", "open_pct", "clv",
        "is_zt", "hit_zt", "is_broken_zt", "is_yizi_zt", "is_dt", "is_yizi_dt",
        "streak", "prev_streak", "is_st_pit", "is_20cm",
        "amount_yi", "turn_pct", "list_age", "cool_days_since_last_zt",
        "kpl_in_t1", "csrc_ind_id", "csrc_ind_zt_share5_t1", "csrc_ind_rank20_t1",
        "ret_1d_t1", "ret_5d_t1", "dd_20d_t1",
    ]
    arrs, dt_cats, c6_cats = _read_cols_numpy(pass1_cols)
    n_tot = len(arrs["dt_id"])
    print(f"[Step1] Pass-1 loaded {n_tot:,} rows in {time.time()-t0:.1f}s | RSS={peak_rss_mb()} MB")

    dt_id = arrs["dt_id"]
    c6_id = arrs["c6_id"]
    open_r = arrs["open"]
    high_r = arrs["high"]
    low_r = arrs["low"]
    close_r = arrs["close"]
    adj_f = arrs["adj_factor"]
    prev_cr = arrs["prev_close_raw"]
    ret_1d = arrs["ret_1d"]
    open_pct = arrs["open_pct"]
    clv = arrs["clv"]
    is_zt = arrs["is_zt"]
    hit_zt = arrs["hit_zt"]
    is_broken = arrs["is_broken_zt"]
    is_yizi = arrs["is_yizi_zt"]
    is_dt = arrs["is_dt"]
    is_yizi_dt = arrs["is_yizi_dt"]
    streak = arrs["streak"]
    prev_stk = arrs["prev_streak"]
    is_st = arrs["is_st_pit"]
    is_20 = arrs["is_20cm"]
    amt_yi = arrs["amount_yi"]
    turn_pct = arrs["turn_pct"]
    list_age = arrs["list_age"]
    cool_zt = arrs["cool_days_since_last_zt"]
    kpl_in_t1 = arrs["kpl_in_t1"]
    ind_id = arrs["csrc_ind_id"]
    ind_zt_sh5 = arrs["csrc_ind_zt_share5_t1"]
    ind_rk20 = arrs["csrc_ind_rank20_t1"]
    ret_1d_t1 = arrs["ret_1d_t1"]
    ret_5d_t1 = arrs["ret_5d_t1"]
    dd_20d_t1 = arrs["dd_20d_t1"]

    # Dynamic PIT ST mask
    print("[Step1] Checking dynamic PIT ST status...")
    st_tl = build_pit_st_timeline(END_BAR_DATE)
    is_st_dyn = np.zeros(n_tot, dtype=np.int8)
    brk = np.flatnonzero(c6_id[1:] != c6_id[:-1]) + 1
    starts = np.concatenate(([0], brk))
    ends = np.concatenate((brk, [n_tot]))
    for s, e in zip(starts, ends):
        c6_s = str(c6_cats[int(c6_id[s])])
        tl = st_tl.get(c6_s)
        if tl:
            ts_l, val_l = tl
            for k in range(s, e):
                dt_s = str(dt_cats[int(dt_id[k])])
                idx = bisect.bisect_left(ts_l, f"{dt_s} 15:00:00")
                if idx > 0 and val_l[idx - 1] == 1:
                    is_st_dyn[k] = 1
    del st_tl

    # Per-stock strictly causal rolling arrays (computed over [t-N .. t-1]!)
    print("[Step1] Computing strictly causal rolling highs, ZT history, and 5d avg amount...")
    dist_hi10 = np.full(n_tot, np.nan, dtype=np.float32)
    dist_hi20 = np.full(n_tot, np.nan, dtype=np.float32)
    dist_hi60 = np.full(n_tot, np.nan, dtype=np.float32)
    zt_cnt_5d_t1 = np.zeros(n_tot, dtype=np.int8)
    zt_cnt_20d_t1 = np.zeros(n_tot, dtype=np.int8)
    max_stk_20d_t1 = np.zeros(n_tot, dtype=np.int8)
    max_stk_40d_t1 = np.zeros(n_tot, dtype=np.int8)
    vol_ratio5_t = np.full(n_tot, np.nan, dtype=np.float32)

    adj_high = high_r.astype(np.float64) * adj_f.astype(np.float64)
    adj_close = close_r.astype(np.float64) * adj_f.astype(np.float64)

    for s, e in zip(starts, ends):
        m = e - s
        if m <= 2:
            continue
        ah = adj_high[s:e]
        ac = adj_close[s:e]
        zt_s = is_zt[s:e].astype(np.int32)
        stk_s = streak[s:e].astype(np.int32)
        am_s = np.nan_to_num(amt_yi[s:e].astype(np.float64), nan=0.0)

        # Prefix sums for ZT counts & 5d mean amount strictly < t
        cs_zt = np.concatenate(([0], np.cumsum(zt_s)))
        cs_am = np.concatenate(([0.0], np.cumsum(am_s)))
        idx_arr = np.arange(m)
        l5 = np.maximum(0, idx_arr - 5)
        l20 = np.maximum(0, idx_arr - 20)
        zt_cnt_5d_t1[s:e] = np.clip(cs_zt[idx_arr] - cs_zt[l5], 0, 127).astype(np.int8)
        zt_cnt_20d_t1[s:e] = np.clip(cs_zt[idx_arr] - cs_zt[l20], 0, 127).astype(np.int8)

        # vol_ratio5_t = amt[t] / mean(amt[t-5..t-1])
        denom_cnt = np.maximum(1, idx_arr - l5)
        ma5_prev = (cs_am[idx_arr] - cs_am[l5]) / denom_cnt
        with np.errstate(divide="ignore", invalid="ignore"):
            vr = np.where((idx_arr >= 3) & (ma5_prev > 0), am_s / ma5_prev, np.nan)
        vol_ratio5_t[s:e] = vr.astype(np.float32)

        # Rolling prior high strictly over [t-N .. t-1]
        for win, out_arr in ((10, dist_hi10), (20, dist_hi20), (60, dist_hi60)):
            if m > win:
                wv = np.lib.stride_tricks.sliding_window_view(ah[:-1], win)
                pmax = wv.max(axis=1)
                with np.errstate(divide="ignore", invalid="ignore"):
                    out_arr[s + win:e] = np.where(pmax > 0, (ac[win:] / pmax - 1.0) * 100.0, np.nan).astype(np.float32)
            # Warmup partial window for bars 5..win-1
            for k in range(min(5, m), min(m, win)):
                pmax = float(np.max(ah[:k]))
                if pmax > 0:
                    out_arr[s + k] = np.float32((ac[k] / pmax - 1.0) * 100.0)

        # Rolling max streak over [t-20..t-1] and [t-40..t-1]
        for win_s, out_s in ((20, max_stk_20d_t1), (40, max_stk_40d_t1)):
            if m > win_s:
                wvs = np.lib.stride_tricks.sliding_window_view(stk_s[:-1], win_s)
                out_s[s + win_s:e] = np.clip(wvs.max(axis=1), 0, 127).astype(np.int8)
            for k in range(1, min(m, win_s)):
                out_s[s + k] = np.int8(min(127, int(np.max(stk_s[:k]))))

    del adj_high, adj_close
    gc.collect()

    # Load market_daily + bench for strictly causal T-1 market features & CSI down streaks
    mkt = pd.read_parquet(MKT_DAY_PQ)
    bench = pd.read_parquet(BENCH_PQ)
    bench = bench.sort_values("trade_date").reset_index(drop=True)
    c_r = bench["csi300_daily_ret"].to_numpy(float) * 100.0
    csi_1d_t1 = np.full(len(bench), np.nan)
    csi_2d_t1 = np.full(len(bench), np.nan)
    csi_3d_t1 = np.full(len(bench), np.nan)
    mkt_ds_t1 = np.zeros(len(bench), dtype=np.int8)
    ds_run = 0
    for i in range(len(bench)):
        mkt_ds_t1[i] = ds_run
        if i >= 1:
            csi_1d_t1[i] = c_r[i - 1]
        if i >= 2:
            csi_2d_t1[i] = ((1.0 + c_r[i - 1] / 100.0) * (1.0 + c_r[i - 2] / 100.0) - 1.0) * 100.0
        if i >= 3:
            csi_3d_t1[i] = ((1.0 + c_r[i - 1] / 100.0) * (1.0 + c_r[i - 2] / 100.0) * (1.0 + c_r[i - 3] / 100.0) - 1.0) * 100.0
        ds_run = (ds_run + 1) if c_r[i] < 0 else 0
    bench["csi_1d_t1"] = csi_1d_t1
    bench["csi_2d_t1"] = csi_2d_t1
    bench["csi_3d_t1"] = csi_3d_t1
    bench["mkt_down_streak_t1"] = mkt_ds_t1
    mkt_all = mkt.merge(bench[["trade_date", "csi_1d_t1", "csi_2d_t1", "csi_3d_t1", "mkt_down_streak_t1"]], on="trade_date", how="left")
    mkt_lu = mkt_all.set_index("trade_date")

    # Vectorized T-day market & CSRC sector breadth (over valid non-ST tradable bars!)
    print("[Step1] Computing T-day cross-sectional market & sector breadth...")
    m_trad = (is_st == 0) & (is_st_dyn == 0) & (amt_yi > 0.05) & np.isfinite(ret_1d) & (close_r > 0)
    tmp_df = pd.DataFrame({
        "dt_id": dt_id[m_trad],
        "ind_id": ind_id[m_trad],
        "ret_1d": ret_1d[m_trad],
        "is_zt": is_zt[m_trad],
        "strong5": (ret_1d[m_trad] >= 5.0).astype(np.int8),
        "up": (ret_1d[m_trad] > 0.0).astype(np.int8),
    })
    mkt_t_agg = tmp_df.groupby("dt_id", as_index=False).agg(
        mkt_t_up_pct=("up", "mean"),
        mkt_t_med_ret=("ret_1d", "median"),
        mkt_t_zt_cnt=("is_zt", "sum"),
    )
    ind_t_agg = tmp_df.groupby(["dt_id", "ind_id"], as_index=False).agg(
        ind_t_zt_cnt=("is_zt", "sum"),
        ind_t_strong_cnt=("strong5", "sum"),
        ind_t_med_ret=("ret_1d", "median"),
    )
    del tmp_df
    gc.collect()

    n_dts = len(dt_cats)
    n_inds = int(ind_id.max()) + 2
    mkt_up_arr = np.full(n_dts, np.nan, dtype=np.float32)
    mkt_med_arr = np.full(n_dts, np.nan, dtype=np.float32)
    mkt_zt_arr = np.zeros(n_dts, dtype=np.int16)
    mkt_up_arr[mkt_t_agg["dt_id"].to_numpy()] = mkt_t_agg["mkt_t_up_pct"].to_numpy(np.float32)
    mkt_med_arr[mkt_t_agg["dt_id"].to_numpy()] = mkt_t_agg["mkt_t_med_ret"].to_numpy(np.float32)
    mkt_zt_arr[mkt_t_agg["dt_id"].to_numpy()] = mkt_t_agg["mkt_t_zt_cnt"].to_numpy(np.int16)

    ind_zt_mat = np.zeros((n_dts, n_inds), dtype=np.int16)
    ind_str_mat = np.zeros((n_dts, n_inds), dtype=np.int16)
    ind_med_mat = np.full((n_dts, n_inds), np.nan, dtype=np.float32)
    di_idx = ind_t_agg["dt_id"].to_numpy()
    ii_idx = ind_t_agg["ind_id"].to_numpy()
    ind_zt_mat[di_idx, ii_idx] = ind_t_agg["ind_t_zt_cnt"].to_numpy(np.int16)
    ind_str_mat[di_idx, ii_idx] = ind_t_agg["ind_t_strong_cnt"].to_numpy(np.int16)
    ind_med_mat[di_idx, ii_idx] = ind_t_agg["ind_t_med_ret"].to_numpy(np.float32)

    row_mkt_up = mkt_up_arr[dt_id]
    row_mkt_med = mkt_med_arr[dt_id]
    row_mkt_zt = mkt_zt_arr[dt_id]
    row_ind_zt = ind_zt_mat[dt_id, ind_id]
    row_ind_str = ind_str_mat[dt_id, ind_id]
    row_ind_med = ind_med_mat[dt_id, ind_id]

    # Map T-1 market ice-point columns onto dt_id for prototype B filtering
    l1_zt_t1_by_dt = np.zeros(n_dts, dtype=np.float32)
    l1_zb_t1_by_dt = np.zeros(n_dts, dtype=np.float32)
    l1_dt_t1_by_dt = np.zeros(n_dts, dtype=np.float32)
    l1_sp_t1_by_dt = np.full(n_dts, 3, dtype=np.int8)
    th_ice_t1_by_dt = np.zeros(n_dts, dtype=np.int8)
    csi2_t1_by_dt = np.zeros(n_dts, dtype=np.float32)
    mds_t1_by_dt = np.zeros(n_dts, dtype=np.int8)
    for di_k, dt_s in enumerate(dt_cats):
        if dt_s in mkt_lu.index:
            rw = mkt_lu.loc[dt_s]
            l1_zt_t1_by_dt[di_k] = float(rw["L1_zt_cnt_t1"])
            l1_zb_t1_by_dt[di_k] = float(rw["L1_zb_rate_t1"])
            l1_dt_t1_by_dt[di_k] = float(rw["L1_dt_cnt_t1"])
            l1_sp_t1_by_dt[di_k] = int(rw["L1_sent_phase_t1"])
            th_ice_t1_by_dt[di_k] = int(rw["th_style_ice_point_sig_t1"])
            csi2_t1_by_dt[di_k] = float(rw["csi_2d_t1"]) if pd.notna(rw["csi_2d_t1"]) else 0.0
            mds_t1_by_dt[di_k] = int(rw["mkt_down_streak_t1"]) if pd.notna(rw["mkt_down_streak_t1"]) else 0

    # Strict buyability mask at tail (<= END_BUY_DATE, non-ST, >=1yi, NOT yizi ZT, NOT sealed ZT at close!)
    lim_pct = np.where(is_20 == 1, 0.20, 0.10)
    zt_px_raw = np.round(prev_cr * (1.0 + lim_pct), 2)
    max_buy_di = int(np.searchsorted(dt_cats, END_BUY_DATE, side="right") - 1)
    base_buyable = (
        (dt_id <= max_buy_di)
        & (is_st == 0)
        & (is_st_dyn == 0)
        & (list_age > 20)
        & (amt_yi >= 1.0)
        & (open_r > 0)
        & (close_r > 0)
        & (prev_cr > 0)
        & (is_yizi == 0)
        & (is_zt == 0)
        & (close_r < zt_px_raw * 0.995)
        & np.isfinite(ret_1d)
    )

    # Prototype A: Strong mainline + strong intraday support + near/breaking 10/20/60d high
    gain_ok_a = np.where(
        is_20 == 0,
        (ret_1d >= 3.0) & (ret_1d <= 9.5),
        (ret_1d >= 5.0) & (ret_1d <= 18.5),
    )
    near_high_a = (dist_hi20 >= -4.0) | (dist_hi10 >= -3.0) | (dist_hi60 >= -3.0)
    mainline_or_zt = (
        (zt_cnt_20d_t1 >= 1)
        | (kpl_in_t1 == 1)
        | (ind_zt_sh5 >= 0.05)
        | (ind_rk20 <= 15)
        | (row_ind_zt >= 2)
        | (row_ind_str >= 4)
    )
    proto_A = base_buyable & (clv >= 0.75) & (close_r > open_r) & gain_ok_a & near_high_a & mainline_or_zt

    # Prototype B: Ice-point market + recognized old dragon (>=2 boards in 40d) + counter-trend tail rally
    ice_mkt = (
        (l1_sp_t1_by_dt[dt_id] == 1)
        | (l1_zt_t1_by_dt[dt_id] < 40)
        | (l1_zb_t1_by_dt[dt_id] >= 0.35)
        | (l1_dt_t1_by_dt[dt_id] >= 20)
        | (th_ice_t1_by_dt[dt_id] == 1)
        | (csi2_t1_by_dt[dt_id] <= -1.2)
        | (mds_t1_by_dt[dt_id] >= 2)
        | (row_mkt_up < 0.35)
    )
    pullback_b = (ret_1d_t1 < 0.0) | (ret_5d_t1 < 0.0) | (dd_20d_t1 <= -8.0)
    proto_B = (
        base_buyable
        & ice_mkt
        & (max_stk_40d_t1 >= 2)
        & (cool_zt >= 1)
        & (cool_zt <= 40)
        & pullback_b
        & (clv >= 0.65)
        & (ret_1d >= 1.0)
    )

    # Prototype C: Prior ZT/lianban divergence today + heavy volume absorption + flips green near high
    proto_C = (
        base_buyable
        & (prev_stk >= 1)
        & (ret_1d > 0.0)
        & (clv >= 0.65)
        & ((vol_ratio5_t >= 1.15) | (turn_pct >= 8.0))
    )

    cand_mask = proto_A | proto_B | proto_C
    cand_idx = np.flatnonzero(cand_mask)
    print(
        f"[Step1] Candidates extracted: Total={len(cand_idx):,} "
        f"(A={int(proto_A.sum()):,}, B={int(proto_B.sum()):,}, C={int(proto_C.sum()):,}) "
        f"| RSS={peak_rss_mb()} MB"
    )

    # Compute forward exits & MTM strings on cand_idx while full price arrays are still in RAM
    print("[Step1] Computing exact 5 exit trees + DT deferrals + daily MTM segments...")
    # Build c6 slice boundaries lookup
    c6_slice_map = {int(c6_id[s]): (int(s), int(e)) for s, e in zip(starts, ends)}

    rows_meta = []
    for idx_k in cand_idx:
        ci = int(c6_id[idx_k])
        s, e = c6_slice_map[ci]
        ex = _calc_exits_and_mtm_tail(
            int(idx_k), s, e,
            open_r, close_r, adj_f, prev_cr, open_pct,
            is_zt, is_dt, is_yizi_dt, is_20, dt_cats, dt_id,
        )
        if "E1_T1O" not in ex:
            continue
        hl = max(1e-6, float(high_r[idx_k] - low_r[idx_k]))
        up_sh = float(high_r[idx_k] - max(open_r[idx_k], close_r[idx_k])) / hl
        lo_sh = float(min(open_r[idx_k], close_r[idx_k]) - low_r[idx_k]) / hl
        intraday_g = (float(close_r[idx_k]) / float(open_r[idx_k]) - 1.0) * 100.0
        amp_t = hl / float(prev_cr[idx_k]) * 100.0
        dist_zt_pct = (float(zt_px_raw[idx_k]) / float(close_r[idx_k]) - 1.0) * 100.0

        rec = {
            "_orig_row_idx": int(idx_k),
            "buy_date": str(dt_cats[int(dt_id[idx_k])]),
            "code": str(c6_cats[ci]),
            "buy_hhmm": 1445,
            "is_20cm": int(is_20[idx_k]),
            "proto_A": int(proto_A[idx_k]),
            "proto_B": int(proto_B[idx_k]),
            "proto_C": int(proto_C[idx_k]),
            "close_raw": float(close_r[idx_k]),
            "open_raw": float(open_r[idx_k]),
            "zt_px_raw": float(zt_px_raw[idx_k]),
            "adj_factor": float(adj_f[idx_k]),
            "ret_1d": float(ret_1d[idx_k]),
            "open_pct": float(open_pct[idx_k]),
            "intraday_gain": round(intraday_g, 4),
            "clv": float(clv[idx_k]),
            "upper_shad": round(up_sh, 4),
            "lower_shad": round(lo_sh, 4),
            "amp_t": round(amp_t, 4),
            "dist_zt_pct": round(dist_zt_pct, 4),
            "amount_yi": float(amt_yi[idx_k]),
            "log_amt_t": round(float(np.log1p(max(0.0, amt_yi[idx_k]))), 4),
            "turn_pct": float(turn_pct[idx_k]),
            "vol_ratio5_t": float(vol_ratio5_t[idx_k]) if np.isfinite(vol_ratio5_t[idx_k]) else np.nan,
            "hit_zt": int(hit_zt[idx_k]),
            "is_broken_zt": int(is_broken[idx_k]),
            "prev_streak": int(prev_stk[idx_k]),
            "cool_days_since_last_zt": int(cool_zt[idx_k]),
            "dist_hi10": float(dist_hi10[idx_k]) if np.isfinite(dist_hi10[idx_k]) else np.nan,
            "dist_hi20": float(dist_hi20[idx_k]) if np.isfinite(dist_hi20[idx_k]) else np.nan,
            "dist_hi60": float(dist_hi60[idx_k]) if np.isfinite(dist_hi60[idx_k]) else np.nan,
            "zt_cnt_5d_t1": int(zt_cnt_5d_t1[idx_k]),
            "zt_cnt_20d_t1": int(zt_cnt_20d_t1[idx_k]),
            "max_stk_20d_t1": int(max_stk_20d_t1[idx_k]),
            "max_stk_40d_t1": int(max_stk_40d_t1[idx_k]),
            "mkt_t_up_pct": float(row_mkt_up[idx_k]),
            "mkt_t_med_ret": float(row_mkt_med[idx_k]),
            "mkt_t_zt_cnt": int(row_mkt_zt[idx_k]),
            "ind_t_zt_cnt": int(row_ind_zt[idx_k]),
            "ind_t_strong_cnt": int(row_ind_str[idx_k]),
            "ind_t_med_ret": float(row_ind_med[idx_k]),
            "rel_str_vs_mkt": float(ret_1d[idx_k] - row_mkt_med[idx_k]),
            "rel_str_vs_ind": float(ret_1d[idx_k] - row_ind_med[idx_k]),
            "is_yizi": 0,
            "can_buy": 1,
        }
        # Next-day diagnostics (AUDIT ONLY, never used as WF features!)
        rec["audit_next_open_pct"] = float(open_pct[idx_k + 1]) if np.isfinite(open_pct[idx_k + 1]) else np.nan
        rec["audit_next_is_zt"] = int(is_zt[idx_k + 1])
        rec["audit_next_is_dt"] = int(is_dt[idx_k + 1])

        for ek in ("E1_T1O", "E2_T1C_HoldZT", "E2b_PureT1C", "E3a_Open0_Hold", "E3b_Open15_Hold"):
            if ek in ex:
                edt, ehh, gr, segs, hdays, dt_def = ex[ek]
                rec[f"{ek}_exit_date"] = edt
                rec[f"{ek}_exit_hhmm"] = int(ehh)
                rec[f"{ek}_gross_ret"] = round(float(gr), 6)
                rec[f"{ek}_hold_days"] = int(hdays)
                rec[f"{ek}_dt_deferred"] = int(dt_def)
                rec[f"{ek}_mtm_json"] = json.dumps(segs, separators=(",", ":"))
            else:
                rec[f"{ek}_exit_date"] = None
                rec[f"{ek}_exit_hhmm"] = 1500
                rec[f"{ek}_gross_ret"] = np.nan
                rec[f"{ek}_hold_days"] = 0
                rec[f"{ek}_dt_deferred"] = 0
                rec[f"{ek}_mtm_json"] = "[]"
        rows_meta.append(rec)

    df_cand = pd.DataFrame(rows_meta)
    sel_row_idx = df_cand["_orig_row_idx"].to_numpy(np.int64)
    df_cand = df_cand.drop(columns=["_orig_row_idx"])
    print(f"[Step1] Exits computed: {len(df_cand):,} complete trades | RSS={peak_rss_mb()} MB")

    # Release large Pass-1 arrays before Pass-2 subset read
    del arrs, open_r, high_r, low_r, close_r, adj_f, prev_cr, ret_1d, open_pct, clv
    del is_zt, hit_zt, is_broken, is_yizi, is_dt, is_yizi_dt, streak, prev_stk, is_st, is_st_dyn, is_20
    del amt_yi, turn_pct, list_age, cool_zt, kpl_in_t1, ind_id, ind_zt_sh5, ind_rk20, ret_1d_t1, ret_5d_t1, dd_20d_t1
    del dist_hi10, dist_hi20, dist_hi60, zt_cnt_5d_t1, zt_cnt_20d_t1, max_stk_20d_t1, max_stk_40d_t1, vol_ratio5_t
    del row_mkt_up, row_mkt_med, row_mkt_zt, row_ind_zt, row_ind_str, row_ind_med
    gc.collect()

    print("[Step1] Loading Pass-2 remaining causal T-1 stock features strictly for candidate rows...")
    pass2_cols = [
        "mcap_yi_t1", "free_mcap_yi_t1", "amount_yi_t1", "real_turn_pct_t1",
        "ret_1d_t1", "prev_clv", "prev_is_broken_zt", "prev_is_yizi_zt",
        "overhang_pct_t1", "hr10d_space_t1", "hr30d_space_t1", "down_streak_t1",
        "pos_20d_t1", "pos_60d_t1", "pos_250d_t1", "dd_20d_t1", "amp_20d_t1",
        "bias10_t1", "bias20_t1", "ret_5d_t1", "ret_20d_t1", "vol_ratio5_t1",
        "turn_5_20_t1", "amp_comp_20v60_t1",
        "lhb_on_t1", "lhb_bayes_t2_t1", "lhb_inst_net_yi_t1", "lhb_has_good_yz_t1",
        "list_age", "zt_cnt_1y_t1", "max_streak_3y", "dd_from_3y_high",
        "kpl_in_t1", "kpl_days_30d_t1", "kpl_zt1_t1", "kpl_zt3_t1", "kpl_streak_t1",
        "csrc_ind_ex5_t1", "csrc_ind_ex20_t1", "csrc_ind_rank20_t1", "csrc_ind_zt_share5_t1",
        "tox_reg_30d_pre", "abn_notice_30d_pre",
    ]
    sub_arrs, _, _ = _read_cols_numpy(pass2_cols, row_idx=sel_row_idx)
    for c in pass2_cols:
        df_cand[c] = sub_arrs[c]
    del sub_arrs
    gc.collect()

    # Merge T-1 Market & Overnight US causal columns
    mkt_cols = [
        "trade_date", "L1_zt_cnt_t1", "L1_nat_zt_cnt_t1", "L1_dt_cnt_t1",
        "L1_zt_dt_logratio_t1", "L1_zb_rate_t1", "L1_max_board_t1", "L1_lianban_cnt_t1",
        "L1_zt_prem_t1", "L1_lb_promo_t1", "L1_duanban_damian_t1", "L1_sent_phase_t1",
        "L1_ew_bias20_t1", "L1_ew_pos60_t1", "L1_is_earn_win", "L1_is_month_end3",
        "mkt20_zt_cnt_t1", "mkt_amt_tril_t1", "mkt_pct_above_ma20_t1",
        "th_style_ice_point_sig_t1", "us_ixic_ret1d_on",
        "csi_1d_t1", "csi_2d_t1", "csi_3d_t1", "mkt_down_streak_t1",
    ]
    df_cand = df_cand.merge(mkt_all[mkt_cols], left_on="buy_date", right_on="trade_date", how="left").drop(columns=["trade_date"])

    # Compute additional clean composite ratios
    df_cand["log_mcap_t1"] = np.log1p(np.maximum(0.0, df_cand["mcap_yi_t1"].fillna(50.0)))
    df_cand["is_break_hi20"] = (df_cand["dist_hi20"] >= -0.5).astype(np.int8)
    df_cand["is_near_hi20"] = (df_cand["dist_hi20"] >= -3.0).astype(np.int8)
    df_cand["is_break_hi60"] = (df_cand["dist_hi60"] >= -0.5).astype(np.int8)

    pq_out = f"{OUT_DIR}/rd043_tail_events_pit.parquet"
    df_cand.sort_values(["buy_date", "code"], inplace=True)
    df_cand.reset_index(drop=True, inplace=True)
    df_cand.to_parquet(pq_out, index=False)

    audit_info = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t0, 2),
        "peak_rss_mb": peak_rss_mb(),
        "d12_yfinance_imported": False,
        "source_stock_day_rows": int(n_tot),
        "source_stock_day_dates": [str(dt_cats[0]), str(dt_cats[-1])],
        "n_candidates_total": int(len(df_cand)),
        "proto_A_count": int(df_cand["proto_A"].sum()),
        "proto_B_count": int(df_cand["proto_B"].sum()),
        "proto_C_count": int(df_cand["proto_C"].sum()),
        "proto_A_10cm": int(((df_cand["proto_A"] == 1) & (df_cand["is_20cm"] == 0)).sum()),
        "proto_A_20cm": int(((df_cand["proto_A"] == 1) & (df_cand["is_20cm"] == 1)).sum()),
        "broken_zt_count_in_pool": int(df_cand["is_broken_zt"].sum()),
        "date_range": [str(df_cand["buy_date"].min()), str(df_cand["buy_date"].max())],
        "unique_buy_dates": int(df_cand["buy_date"].nunique()),
        "e1_dt_deferred_cnt": int(df_cand["E1_T1O_dt_deferred"].sum()),
    }
    with open(f"{OUT_DIR}/_step1_audit.json", "w", encoding="utf-8") as f:
        json.dump(audit_info, f, ensure_ascii=False, indent=2)

    print(f"[Step1 DONE] Saved {pq_out} | {json.dumps(audit_info, ensure_ascii=False)}")


if __name__ == "__main__":
    main()

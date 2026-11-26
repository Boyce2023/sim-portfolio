#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 2B-3: Strictly PIT Ultra-Low-RAM (<1.6GB) Candidate Pool & Feature Builder.
Four tracks:
  Track A: Sector Climax Day-1 (`sector_climax_day1`: KPL thematic + CSRC industry)
  Track B: Strong Main-Theme Trend Stock Shrinking-Volume Pullback (`trend_pullback_low_open`)
  Track C: 2-5d Lagging Second-Tier Theme Catch-Up (`laggard_theme_catchup`, Leader Accel vs Broken)
  Track D: Cold Low-Crowding + Volatility-Compressed First Mild Breakout (`cold_compressed_seesaw`)

Memory discipline (< 1.6 GB Peak RSS):
  - PyArrow single-threaded (`cpu=1, io=1`) + `release_unused()`.
  - Zero 7M-row intermediate DataFrames or 7M-row feature arrays: computes rolling stock metrics
    in per-stock L1 cache (~1400 bars) and aggregates industry daily stats via `np.bincount`.
  - Pass 2 reads remaining feature columns in 4-column micro-batches and slices only `u_df` (~106k).
  - Zero yfinance (D12). Zero cap10m.
"""
import gc
import json
import os
import sqlite3
import sys
import time
import warnings
from typing import Optional

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

warnings.filterwarnings("ignore", category=RuntimeWarning)

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
pa.set_cpu_count(1)
pa.set_io_thread_count(1)

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
BASE_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
DATA_DIR = f"{ROOT}/sim-portfolio/data"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave2b/w2b3_theme_pullback_laggard_scorecard"

CORE_PQ = f"{BASE_DIR}/stock_day_core_features_pit.parquet"
MKT_PQ = f"{BASE_DIR}/market_daily_all_new_factors_pit.parquet"
KPL_JSONL = f"{DATA_DIR}/kpl_plates_2018_2026_merged.jsonl"
ZT_DB = f"{DATA_DIR}/zt_micro_tape_5y_pit.db"


def _parse_kpl_plate_tokens(raw_plate: str) -> list[str]:
    if not raw_plate:
        return []
    out, seen = [], set()
    for seg in str(raw_plate).split(","):
        s = seg.strip()
        if not s or s in ("其他", "ST板块"):
            continue
        base = s.split("(")[0].strip()
        if base and base not in ("其他", "ST板块") and base not in seen:
            seen.add(base)
            out.append(base)
    return out


def _roll_pct_arr(arr: np.ndarray, win: int = 60, min_p: int = 20) -> np.ndarray:
    n = len(arr)
    out = np.full(n, np.nan, dtype=np.float32)
    for i in range(min_p - 1, n):
        v = arr[i]
        if not np.isfinite(v):
            continue
        w = arr[max(0, i - win + 1) : i + 1]
        w = w[np.isfinite(w)]
        if len(w) >= min_p:
            out[i] = float(np.mean(w <= v))
    return out


def _compute_stock_eod_block(
    sc: np.ndarray,
    sh: np.ndarray,
    sl: np.ndarray,
    sa: np.ndarray,
    st: np.ndarray,
    sr1: np.ndarray,
    siz: np.ndarray,
) -> dict:
    """Compute all causal EOD arrays for a single stock slice (~1400 bars) in L1 cache."""
    m = len(sc)
    cs_c = np.concatenate(([0.0], np.cumsum(sc)))
    cs_a = np.concatenate(([0.0], np.cumsum(sa)))
    cs_t = np.concatenate(([0.0], np.cumsum(st)))

    bias5 = np.full(m, np.nan, dtype=np.float32)
    bias10 = np.full(m, np.nan, dtype=np.float32)
    bias20 = np.full(m, np.nan, dtype=np.float32)
    ma5_ld = np.full(m, np.nan, dtype=np.float32)
    ma10_ld = np.full(m, np.nan, dtype=np.float32)
    dd5 = np.full(m, np.nan, dtype=np.float32)
    abv5 = np.full(m, np.nan, dtype=np.float32)
    abv20 = np.full(m, np.nan, dtype=np.float32)
    vr5 = np.full(m, np.nan, dtype=np.float32)
    tr5 = np.full(m, np.nan, dtype=np.float32)
    ret5 = np.full(m, np.nan, dtype=np.float32)
    ret20 = np.full(m, np.nan, dtype=np.float32)
    ret20_pre = np.full(m, np.nan, dtype=np.float32)
    atr5_60 = np.full(m, np.nan, dtype=np.float32)
    atr5_20 = np.full(m, np.nan, dtype=np.float32)
    big4_pre = np.zeros(m, dtype=np.int8)
    big3_pre = np.zeros(m, dtype=np.int8)
    zt20 = np.zeros(m, dtype=np.int8)

    if m >= 5:
        ma5 = (cs_c[5:] - cs_c[:-5]) / 5.0
        bias5[4:] = ((sc[4:] / ma5 - 1.0) * 100.0).astype(np.float32)
        ma5_ld[4:] = ((sl[4:] / ma5 - 1.0) * 100.0).astype(np.float32)
        abv5[4:] = (sc[4:] > ma5).astype(np.float32)
        wv5 = np.lib.stride_tricks.sliding_window_view(sh, 5)
        dd5[4:] = ((sc[4:] / np.maximum(1e-6, wv5.max(axis=1)) - 1.0) * 100.0).astype(np.float32)
    if m >= 6:
        ret5[5:] = ((sc[5:] / sc[:-5] - 1.0) * 100.0).astype(np.float32)
        a_p = (cs_a[5:-1] - cs_a[:-6]) / 5.0
        t_p = (cs_t[5:-1] - cs_t[:-6]) / 5.0
        vr5[5:] = np.where(a_p > 1e-6, sa[5:] / a_p, np.nan).astype(np.float32)
        tr5[5:] = np.where(t_p > 1e-6, st[5:] / t_p, np.nan).astype(np.float32)
    if m >= 10:
        ma10 = (cs_c[10:] - cs_c[:-10]) / 10.0
        bias10[9:] = ((sc[9:] / ma10 - 1.0) * 100.0).astype(np.float32)
        ma10_ld[9:] = ((sl[9:] / ma10 - 1.0) * 100.0).astype(np.float32)
    if m >= 20:
        ma20 = (cs_c[20:] - cs_c[:-20]) / 20.0
        bias20[19:] = ((sc[19:] / ma20 - 1.0) * 100.0).astype(np.float32)
        abv20[19:] = (sc[19:] > ma20).astype(np.float32)
    if m >= 21:
        ret20[20:] = ((sc[20:] / sc[:-20] - 1.0) * 100.0).astype(np.float32)
    if m >= 22:
        ret20_pre[21:] = ret20[20:-1]
    if m >= 2:
        pc = sc[:-1]
        tr = np.maximum(sh[1:] - sl[1:], np.maximum(np.abs(sh[1:] - pc), np.abs(sl[1:] - pc))) / np.maximum(1e-6, pc) * 100.0
        cs_tr = np.concatenate(([0.0], np.cumsum(tr)))
        a5 = np.full(m, np.nan); a20 = np.full(m, np.nan); a60 = np.full(m, np.nan)
        if m >= 6: a5[5:] = (cs_tr[5:] - cs_tr[:-5]) / 5.0
        if m >= 21: a20[20:] = (cs_tr[20:] - cs_tr[:-20]) / 20.0
        if m >= 61: a60[60:] = (cs_tr[60:] - cs_tr[:-60]) / 60.0
        atr5_20[:] = np.where(a20 > 1e-6, a5 / a20, np.nan).astype(np.float32)
        atr5_60[:] = np.where(a60 > 1e-6, a5 / a60, np.nan).astype(np.float32)

    b4 = ((sr1 >= 4.0) | (siz == 1)).astype(np.int32)
    b3 = ((sr1 >= 3.0) | (siz == 1)).astype(np.int32)
    cs_b4 = np.concatenate(([0], np.cumsum(b4)))
    cs_b3 = np.concatenate(([0], np.cumsum(b3)))
    cs_iz = np.concatenate(([0], np.cumsum(siz.astype(np.int32))))
    if m >= 6: big4_pre[5:] = np.clip(cs_b4[5:-1] - cs_b4[:-6], 0, 127).astype(np.int8)
    if m >= 11: big3_pre[10:] = np.clip(cs_b3[10:-1] - cs_b3[:-11], 0, 127).astype(np.int8)
    if m >= 20: zt20[19:] = np.clip(cs_iz[20:] - cs_iz[:-20], 0, 127).astype(np.int8)

    return {
        "bias5": bias5, "bias10": bias10, "bias20": bias20,
        "ma5_ld": ma5_ld, "ma10_ld": ma10_ld, "dd5": dd5,
        "abv5": abv5, "abv20": abv20, "vr5": vr5, "tr5": tr5,
        "ret5": ret5, "ret20": ret20, "ret20_pre": ret20_pre,
        "atr5_60": atr5_60, "atr5_20": atr5_20,
        "big4_pre": big4_pre, "big3_pre": big3_pre, "zt20": zt20,
    }


def _read_cols_numpy(cols: list[str], keep_mask: Optional[np.ndarray] = None) -> dict[str, np.ndarray]:
    """Stream columns row-group by row-group into preallocated numpy arrays (minimal Arrow buffer)."""
    pf = pq.ParquetFile(CORE_PQ)
    n_tot = pf.metadata.num_rows
    n_out = int(keep_mask.sum()) if keep_mask is not None else n_tot
    schema = pf.schema_arrow
    out = {}
    for c in cols:
        pa_t = schema.field(c).type
        np_dt = np.float32 if pa.types.is_floating(pa_t) else (np.int8 if pa.types.is_int8(pa_t) else (np.int16 if pa.types.is_int16(pa_t) else np.int32))
        out[c] = np.empty(n_out, dtype=np_dt)

    src_pos = 0
    dst_pos = 0
    for rg in range(pf.num_row_groups):
        tbl = pf.read_row_group(rg, columns=cols)
        m_rg = tbl.num_rows
        if keep_mask is not None:
            km_rg = keep_mask[src_pos : src_pos + m_rg]
            cnt = int(km_rg.sum())
            if cnt > 0:
                for c in cols:
                    arr = tbl.column(c).to_numpy(zero_copy_only=False)
                    out[c][dst_pos : dst_pos + cnt] = arr[km_rg]
                dst_pos += cnt
        else:
            for c in cols:
                arr = tbl.column(c).to_numpy(zero_copy_only=False)
                out[c][dst_pos : dst_pos + m_rg] = arr
            dst_pos += m_rg
        src_pos += m_rg
        del tbl
    pa.default_memory_pool().release_unused()
    return out


def _load_pass1_and_scan(end_cutoff: str = "2026-11-25") -> dict:
    t0 = time.time()
    # Read dt/c6 + price/flag columns in 2 small memory-capped reads (<0.9 GB total!)
    meta = pd.read_parquet(CORE_PQ, columns=["dt", "c6"])
    pa.default_memory_pool().release_unused()
    dt_cats = meta["dt"].cat.categories.astype(str).tolist()
    c6_cats = meta["c6"].cat.categories.astype(str).tolist()
    valid_dt_mask = np.array([d <= end_cutoff for d in dt_cats], dtype=bool)
    cal_dts = sorted([d for d in dt_cats if d <= end_cutoff])
    dt_to_i = {d: i for i, d in enumerate(cal_dts)}
    dt_code_to_cal = np.array([dt_to_i.get(d, -1) for d in dt_cats], dtype=np.int32)

    raw_d_codes = meta["dt"].cat.codes.values
    keep_mask = valid_dt_mask[raw_d_codes]
    orig_row_ids = np.flatnonzero(keep_mask).astype(np.int64)
    c_codes = meta["c6"].cat.codes.values[keep_mask].astype(np.int32)
    d_idx_arr = dt_code_to_cal[raw_d_codes[keep_mask]].astype(np.int32)
    del meta, raw_d_codes
    gc.collect()

    km = None if keep_mask.all() else keep_mask
    d1 = _read_cols_numpy(["open", "high", "low", "close", "adj_factor", "prev_close_raw"], km)
    n = len(c_codes)
    c6_arr = np.array(c6_cats, dtype=object)
    brk = np.flatnonzero(c_codes[1:] != c_codes[:-1]) + 1
    starts = np.concatenate(([0], brk))
    ends = np.concatenate((brk, [n]))
    seg_end = np.empty(n, dtype=np.int64)
    for s, e in zip(starts, ends):
        seg_end[s:e] = e

    ac = (d1["close"] * d1["adj_factor"]).astype(np.float32)
    ao = (d1["open"] * d1["adj_factor"]).astype(np.float32)
    ah = (d1["high"] * d1["adj_factor"]).astype(np.float32)
    al = (d1["low"] * d1["adj_factor"]).astype(np.float32)
    hl = np.maximum(1e-6, d1["high"] - d1["low"])
    lower_shad = ((np.minimum(d1["open"], d1["close"]) - d1["low"]) / hl).astype(np.float32)
    upper_shad = ((d1["high"] - np.maximum(d1["open"], d1["close"])) / hl).astype(np.float32)
    open_raw = d1["open"]
    prev_c_raw = d1["prev_close_raw"]
    del d1, hl
    gc.collect()

    d2 = _read_cols_numpy(["amount_yi", "turn_pct", "ret_1d", "open_pct", "clv", "is_zt", "hit_zt", "is_broken_zt", "is_yizi_zt", "is_dt", "is_yizi_dt", "streak", "prev_streak", "is_st_pit", "is_20cm"], km)
    d3 = _read_cols_numpy(["mcap_yi_t1", "ret_5d_t1", "csrc_ind_id", "csrc_ind_rank20_t1", "kpl_days_30d_t1", "csrc_ind_zt_share5_t1"], km)

    amt = d2["amount_yi"]
    trn = d2["turn_pct"]
    lim_arr = np.where(d2["is_20cm"] == 1, 0.20, 0.10)
    zt_px = np.round(prev_c_raw * (1.0 + lim_arr), 2)
    is_unbuyable_open = (
        (open_raw >= zt_px - 1e-4)
        | (d2["is_yizi_zt"] == 1)
        | (d2["is_yizi_dt"] == 1)
        | (d2["open_pct"] >= lim_arr * 100.0 - 0.15)
        | (amt <= 0.05)
    )
    del open_raw, prev_c_raw, lim_arr, zt_px
    gc.collect()

    r1 = d2["ret_1d"]
    iz = d2["is_zt"]
    op = d2["open_pct"]
    clv = d2["clv"]
    is_st = d2["is_st_pit"]
    ind_id = d3["csrc_ind_id"]

    has_next_consec = np.zeros(n, dtype=bool)
    has_next_consec[:-1] = (c_codes[:-1] == c_codes[1:]) & (d_idx_arr[1:] == d_idx_arr[:-1] + 1)

    # Industry daily accumulators using np.bincount (ZERO 7M-row DataFrame!)
    n_days = len(cal_dts)
    n_inds = 90
    tot_bins = n_days * n_inds
    bin_n = np.zeros(tot_bins, dtype=np.int32)
    bin_amt = np.zeros(tot_bins, dtype=np.float64)
    bin_trn = np.zeros(tot_bins, dtype=np.float64)
    bin_zt = np.zeros(tot_bins, dtype=np.int32)
    bin_ret = np.zeros(tot_bins, dtype=np.float64)
    bin_op = np.zeros(tot_bins, dtype=np.float64)
    bin_abv5 = np.zeros(tot_bins, dtype=np.float64)
    bin_abv5_n = np.zeros(tot_bins, dtype=np.int32)
    bin_abv20 = np.zeros(tot_bins, dtype=np.float64)
    bin_abv20_n = np.zeros(tot_bins, dtype=np.int32)
    bin_atr = np.zeros(tot_bins, dtype=np.float64)
    bin_atr_n = np.zeros(tot_bins, dtype=np.int32)

    # Accumulate Track B, Track C laggard, Track D candidate sig_idxs directly inside stock loop!
    b_sig_list = []
    c_cand_list = []
    d_cand_list = []
    mcap_s_arr = d3["mcap_yi_t1"] * (1.0 + np.nan_to_num(r1, nan=0.0) / 100.0)
    r5_pre_arr = d3["ret_5d_t1"]

    for s, e in zip(starts, ends):
        blk = _compute_stock_eod_block(
            ac[s:e].astype(np.float64),
            ah[s:e].astype(np.float64),
            al[s:e].astype(np.float64),
            np.nan_to_num(amt[s:e].astype(np.float64), nan=0.0),
            np.nan_to_num(trn[s:e].astype(np.float64), nan=0.0),
            r1[s:e],
            iz[s:e],
        )

        # Accumulate active non-ST bars into industry bincounts
        act_loc = np.flatnonzero(is_st[s:e] == 0)
        if len(act_loc):
            g_loc = s + act_loc
            b_ids = d_idx_arr[g_loc].astype(np.int64) * n_inds + ind_id[g_loc].astype(np.int64)
            np.add.at(bin_n, b_ids, 1)
            np.add.at(bin_amt, b_ids, np.nan_to_num(amt[g_loc], nan=0.0))
            np.add.at(bin_trn, b_ids, np.nan_to_num(trn[g_loc], nan=0.0))
            np.add.at(bin_zt, b_ids, iz[g_loc])
            np.add.at(bin_ret, b_ids, np.nan_to_num(r1[g_loc], nan=0.0))
            np.add.at(bin_op, b_ids, np.nan_to_num(op[g_loc], nan=0.0))
            m5 = np.isfinite(blk["abv5"][act_loc])
            if m5.any():
                np.add.at(bin_abv5, b_ids[m5], blk["abv5"][act_loc[m5]])
                np.add.at(bin_abv5_n, b_ids[m5], 1)
            m20 = np.isfinite(blk["abv20"][act_loc])
            if m20.any():
                np.add.at(bin_abv20, b_ids[m20], blk["abv20"][act_loc[m20]])
                np.add.at(bin_abv20_n, b_ids[m20], 1)
            matr = np.isfinite(blk["atr5_60"][act_loc])
            if matr.any():
                np.add.at(bin_atr, b_ids[matr], np.clip(blk["atr5_60"][act_loc[matr]], 0.25, 2.5))
                np.add.at(bin_atr_n, b_ids[matr], 1)

        # Track B mask in stock slice
        bm = (
            (is_st[s:e] == 0)
            & (iz[s:e] == 0)
            & (r1[s:e] <= 0.5)
            & (amt[s:e] >= 0.5)
            & (blk["ret20"] >= 15.0)
            & (blk["ret20"] <= 55.0)
            & (blk["bias20"] >= 0.0)
            & (
                ((blk["bias5"] >= -4.5) & (blk["bias5"] <= 1.8) & (blk["ma5_ld"] <= 1.0))
                | ((blk["bias10"] >= -3.5) & (blk["bias10"] <= 2.5) & (blk["ma10_ld"] <= 1.0))
            )
            & (blk["vr5"] <= 0.68)
            & (blk["tr5"] <= 0.70)
            & has_next_consec[s:e]
        )
        for loc_i in np.flatnonzero(bm):
            gi = s + loc_i
            nxt_op = op[gi + 1]
            if -4.0 <= nxt_op <= 1.0:
                b_sig_list.append(gi)

        # Track C laggard mask in stock slice
        cm = (
            (is_st[s:e] == 0)
            & (mcap_s_arr[s:e] >= 30.0)
            & (mcap_s_arr[s:e] <= 200.0)
            & (r5_pre_arr[s:e] < 10.0)
            & (r1[s:e] >= 4.0)
            & (r1[s:e] <= 9.8)
            & (iz[s:e] == 0)
            & (d2["is_yizi_zt"][s:e] == 0)
            & (blk["vr5"] >= 1.4)
            & (blk["big4_pre"] == 0)
            & (amt[s:e] >= 0.5)
            & has_next_consec[s:e]
        )
        for loc_i in np.flatnonzero(cm):
            c_cand_list.append(s + loc_i)

        # Track D mask in stock slice
        dm = (
            (is_st[s:e] == 0)
            & (ind_id[s:e] != 84)
            & (iz[s:e] == 0)
            & (d2["is_yizi_zt"][s:e] == 0)
            & (r1[s:e] >= 2.5)
            & (r1[s:e] <= 7.5)
            & (blk["vr5"] >= 1.25)
            & (blk["vr5"] <= 3.5)
            & (blk["big3_pre"] == 0)
            & (blk["ret20_pre"] < 15.0)
            & (amt[s:e] >= 0.5)
            & has_next_consec[s:e]
        )
        for loc_i in np.flatnonzero(dm):
            d_cand_list.append((
                s + loc_i,
                float(blk["vr5"][loc_i]),
                float(blk["atr5_60"][loc_i]),
                float(blk["abv20"][loc_i]) if np.isfinite(blk["abv20"][loc_i]) else 0.0,
            ))

    # Build ind_d from bincounts (ZERO 7M-row intermediate DataFrames!)
    nz_bins = np.flatnonzero(bin_n > 0)
    nz_di = nz_bins // n_inds
    nz_iid = nz_bins % n_inds

    ind_d = pd.DataFrame({
        "d_idx": nz_di.astype(np.int32),
        "csrc_ind_id": nz_iid.astype(np.int16),
        "ind_n": bin_n[nz_bins],
        "ind_amt": bin_amt[nz_bins],
        "ind_turn": bin_trn[nz_bins] / bin_n[nz_bins],
        "ind_zt": bin_zt[nz_bins],
        "ind_ret": bin_ret[nz_bins] / bin_n[nz_bins],
        "ind_open_gap_mean": bin_op[nz_bins] / bin_n[nz_bins],
        "ind_above5": np.where(bin_abv5_n[nz_bins] > 0, bin_abv5[nz_bins] / np.maximum(1, bin_abv5_n[nz_bins]), np.nan),
        "ind_above20": np.where(bin_abv20_n[nz_bins] > 0, bin_abv20[nz_bins] / np.maximum(1, bin_abv20_n[nz_bins]), np.nan),
        "ind_atr5_60": np.where(bin_atr_n[nz_bins] > 0, bin_atr[nz_bins] / np.maximum(1, bin_atr_n[nz_bins]), np.nan),
    })
    mkt_d = ind_d.groupby("d_idx", as_index=False).agg(mkt_amt=("ind_amt", "sum"), mkt_n=("ind_n", "sum"))
    mkt_op_tot = pd.DataFrame({"d_idx": nz_di, "op_sum": bin_op[nz_bins]}).groupby("d_idx", as_index=False)["op_sum"].sum()
    mkt_d = mkt_d.merge(mkt_op_tot, on="d_idx")
    mkt_d["mkt_open_med"] = mkt_d["op_sum"] / np.maximum(1, mkt_d["mkt_n"])
    ind_d = ind_d.merge(mkt_d[["d_idx", "mkt_amt", "mkt_open_med"]], on="d_idx", how="left")
    del mkt_d, mkt_op_tot, bin_n, bin_amt, bin_trn, bin_zt, bin_ret, bin_op, bin_abv5, bin_abv5_n, bin_abv20, bin_abv20_n, bin_atr, bin_atr_n
    gc.collect()

    ind_d = ind_d.sort_values(["csrc_ind_id", "d_idx"]).reset_index(drop=True)
    ind_d["ind_amt_share"] = ind_d["ind_amt"] / ind_d["mkt_amt"].replace(0, np.nan)
    ind_d["ind_turn_pct60"] = ind_d.groupby("csrc_ind_id", sort=False)["ind_turn"].transform(
        lambda s: pd.Series(_roll_pct_arr(s.to_numpy(float), 60, 20), index=s.index)
    )
    ind_d["ind_amt_pct60"] = ind_d.groupby("csrc_ind_id", sort=False)["ind_amt_share"].transform(
        lambda s: pd.Series(_roll_pct_arr(s.to_numpy(float), 60, 20), index=s.index)
    )
    ind_d["ind_amt_pct250"] = ind_d.groupby("csrc_ind_id", sort=False)["ind_amt_share"].transform(
        lambda s: pd.Series(_roll_pct_arr(s.to_numpy(float), 250, 30), index=s.index)
    )
    ind_d["ind_above5_peak4d"] = ind_d.groupby("csrc_ind_id", sort=False)["ind_above5"].transform(
        lambda s: s.shift(1).rolling(4, min_periods=1).max()
    )
    ind_d["ind_breadth_drop"] = (ind_d["ind_above5"] - ind_d["ind_above5_peak4d"]).astype(np.float32)
    ind_d["ind_crowd_div_flag"] = (
        (ind_d["ind_amt_pct250"] >= 0.85)
        & (ind_d["ind_above5_peak4d"] >= 0.72)
        & (ind_d["ind_above5"] <= 0.60)
    ).astype(np.int8)
    ind_d["ind_crowd_x_div"] = (
        ind_d["ind_amt_pct250"].fillna(0.5) * np.maximum(0.0, -ind_d["ind_breadth_drop"].fillna(0.0))
    ).astype(np.float32)

    ind_climax_day1 = np.zeros(len(ind_d), dtype=np.int8)
    ind_ids_arr = ind_d["csrc_ind_id"].values
    ind_n_arr = ind_d["ind_n"].values
    ind_zt_arr = ind_d["ind_zt"].values
    ind_ret_arr = ind_d["ind_ret"].values
    ind_di_arr = ind_d["d_idx"].values
    last_cl_di = {}
    for idx_i in range(len(ind_d)):
        iid = int(ind_ids_arr[idx_i])
        di_v = int(ind_di_arr[idx_i])
        is_burst = (
            (iid != 84)
            and (ind_n_arr[idx_i] >= 12)
            and (ind_zt_arr[idx_i] >= 6)
            and (ind_zt_arr[idx_i] / ind_n_arr[idx_i] >= 0.05)
            and (ind_ret_arr[idx_i] >= 3.2)
        )
        if is_burst:
            if di_v - last_cl_di.get(iid, -9999) >= 10:
                ind_climax_day1[idx_i] = 1
            last_cl_di[iid] = di_v
    ind_d["ind_climax_day1"] = ind_climax_day1

    # KPL + ZT micro tape strictly <= end_cutoff
    c6_to_code = {c: i for i, c in enumerate(c6_cats)}
    zt_pairs = set(zip(d_idx_arr[iz == 1].tolist(), c_codes[iz == 1].tolist()))

    kpl_records = []
    with open(KPL_JSONL, encoding="utf-8") as f:
        for line in f:
            obj = json.loads(line)
            dt_str = str(obj["date"])[:10]
            if dt_str > end_cutoff:
                continue
            di = dt_to_i.get(dt_str)
            if di is None:
                continue
            for pl in obj.get("plates", []):
                toks = _parse_kpl_plate_tokens(pl.get("plate", ""))
                if not toks:
                    continue
                stks = [c6_to_code.get(str(s[0])[-6:], -1) for s in pl.get("stocks", []) if s]
                for tk in toks:
                    for cid in stks:
                        if cid >= 0:
                            kpl_records.append((di, tk, cid))

    con_zt = sqlite3.connect(f"file:{ZT_DB}?mode=ro", uri=True)
    zt_rows = pd.read_sql_query(
        "SELECT trade_date, sec_code, plate_name FROM zt_micro_tape WHERE trade_date >= '2021-01-04' AND trade_date <= ?",
        con_zt,
        params=(end_cutoff,),
    )
    con_zt.close()
    zt_extra_records = []
    for r in zt_rows.itertuples(index=False):
        di = dt_to_i.get(str(r.trade_date)[:10])
        cid = c6_to_code.get(str(r.sec_code).zfill(6), -1)
        if di is None or cid < 0:
            continue
        for tk in _parse_kpl_plate_tokens(r.plate_name):
            zt_extra_records.append((di, tk, cid))

    kpl_df = pd.DataFrame(kpl_records, columns=["d_idx", "plate", "c_code"]).drop_duplicates()
    all_theme_df = pd.DataFrame(kpl_records + zt_extra_records, columns=["d_idx", "plate", "c_code"]).drop_duplicates()
    del kpl_records, zt_extra_records, zt_rows

    kpl_df["is_zt"] = [1 if (d, c) in zt_pairs else 0 for d, c in zip(kpl_df["d_idx"], kpl_df["c_code"])]
    kpl_plate_day = kpl_df.groupby(["d_idx", "plate"], as_index=False).agg(
        plate_zt=("is_zt", "sum"),
        plate_n=("c_code", "size"),
    ).sort_values(["plate", "d_idx"]).reset_index(drop=True)
    kpl_plate_day["prev_3d_max_zt"] = kpl_plate_day.groupby("plate", sort=False)["plate_zt"].transform(
        lambda s: s.shift(1).rolling(3, min_periods=1).max()
    ).fillna(0.0)
    kpl_cl_d1 = np.zeros(len(kpl_plate_day), dtype=np.int8)
    last_pl_cl = {}
    for idx_i, (pl, di_v, pzt) in enumerate(zip(kpl_plate_day["plate"].values, kpl_plate_day["d_idx"].values, kpl_plate_day["plate_zt"].values)):
        di_v = int(di_v)
        if pzt >= 4:
            if di_v - last_pl_cl.get(pl, -9999) >= 10:
                kpl_cl_d1[idx_i] = 1
            last_pl_cl[pl] = di_v
    kpl_plate_day["kpl_climax_day1"] = kpl_cl_d1
    mkt_cl_cnt = kpl_plate_day[kpl_plate_day["kpl_climax_day1"] == 1].groupby("d_idx")["plate"].nunique().to_dict()
    kpl_plate_day["mkt_climax_plate_cnt"] = kpl_plate_day["d_idx"].map(mkt_cl_cnt).fillna(0).astype(np.int16)

    # --- Track A1 (KPL) ---
    cl_pl = kpl_plate_day[kpl_plate_day["kpl_climax_day1"] == 1][
        ["d_idx", "plate", "plate_zt", "plate_n", "prev_3d_max_zt", "mkt_climax_plate_cnt"]
    ].copy()
    cl_pl["plate_zt_jump"] = cl_pl["plate_zt"] - cl_pl["prev_3d_max_zt"]
    a1_m = kpl_df.merge(cl_pl, on=["d_idx", "plate"], how="inner")
    cl_d_set = set(cl_pl["d_idx"].unique().tolist())
    sub_act = np.flatnonzero((is_st == 0) & np.isin(d_idx_arr, list(cl_d_set)))
    sub_map = pd.DataFrame({"d_idx": d_idx_arr[sub_act], "c_code": c_codes[sub_act], "sig_idx": sub_act})
    a1_m = a1_m.merge(sub_map, on=["d_idx", "c_code"], how="inner")
    del sub_act, sub_map
    s_i = a1_m["sig_idx"].to_numpy(np.int64)
    a1_m = a1_m[((d2["hit_zt"][s_i] == 1) | (r1[s_i] >= 3.0)) & has_next_consec[s_i]].copy()
    a1_m = a1_m.sort_values(["d_idx", "c_code", "plate_zt"], ascending=[True, True, False]).drop_duplicates(
        subset=["d_idx", "c_code"], keep="first"
    )
    a1_sig = a1_m[["sig_idx", "plate_zt", "plate_n", "plate_zt_jump", "mkt_climax_plate_cnt"]].rename(
        columns={
            "plate_zt": "climax_plate_zt", "plate_n": "climax_plate_n",
            "plate_zt_jump": "climax_zt_jump", "mkt_climax_plate_cnt": "climax_mkt_cnt",
        }
    ).reset_index(drop=True)

    # --- Track A2 (CSRC industry climax Day 1) ---
    cl_ind = ind_d[ind_d["ind_climax_day1"] == 1][["d_idx", "csrc_ind_id", "ind_zt", "ind_n", "ind_ret"]].copy()
    mkt_ic = cl_ind.groupby("d_idx")["csrc_ind_id"].nunique().rename("climax_mkt_cnt")
    cl_ind = cl_ind.merge(mkt_ic, on="d_idx", how="left")
    a2_base_idxs = np.flatnonzero((is_st == 0) & ((d2["hit_zt"] == 1) | (r1 >= 4.0)) & has_next_consec)
    a2_cand = pd.DataFrame({
        "sig_idx": a2_base_idxs, "d_idx": d_idx_arr[a2_base_idxs], "csrc_ind_id": ind_id[a2_base_idxs],
    }).merge(cl_ind, on=["d_idx", "csrc_ind_id"], how="inner")
    a2_sig = a2_cand[["sig_idx", "ind_zt", "ind_n", "ind_ret", "climax_mkt_cnt"]].rename(
        columns={"ind_zt": "climax_plate_zt", "ind_n": "climax_plate_n", "ind_ret": "climax_zt_jump"}
    ).reset_index(drop=True)

    # --- Track B ---
    b_sig = pd.DataFrame({"sig_idx": np.array(b_sig_list, dtype=np.int64)})

    # --- Track C ---
    next_open = np.full(n, np.nan, dtype=np.float32)
    next_open[:-1] = np.where(has_next_consec[:-1], op[1:], np.nan)
    pe_by_c = {c: (g["d_idx"].values, g["plate"].values) for c, g in all_theme_df.sort_values("d_idx").groupby("c_code", sort=False)}
    ld_acc_idx = np.flatnonzero((is_st == 0) & (d2["streak"] >= 3) & (iz == 1))
    ld_brk_idx = np.flatnonzero((is_st == 0) & (d2["prev_streak"] >= 3) & (iz == 0))
    acc_map, brk_map = {}, {}
    for arr_idx, target_map, st_vals in [
        (ld_acc_idx, acc_map, d2["streak"]),
        (ld_brk_idx, brk_map, d2["prev_streak"]),
    ]:
        yz_vals = d2["is_yizi_zt"]
        for srow in arr_idx:
            di = int(d_idx_arr[srow]); cid = int(c_codes[srow])
            tup = pe_by_c.get(cid)
            if tup is None: continue
            ds, ps = tup
            rp = np.searchsorted(ds, di, side="right"); lp = np.searchsorted(ds, di - 3, side="left")
            if rp <= lp: continue
            b_op = float(next_open[srow]) if np.isfinite(next_open[srow]) else np.nan
            val = (int(st_vals[srow]), int(yz_vals[srow]), b_op, cid)
            for pl in set(ps[lp:rp]):
                target_map.setdefault((di, pl), []).append(val)

    c_rows = []
    for srow in c_cand_list:
        di = int(d_idx_arr[srow]); cid = int(c_codes[srow])
        tup = pe_by_c.get(cid)
        if tup is None: continue
        ds, ps = tup
        rp = np.searchsorted(ds, di, side="right"); lp = np.searchsorted(ds, di - 250, side="left")
        if rp <= lp: continue
        c_pls = set(ps[lp:rp])
        m_acc, m_brk = [], []
        for pl in c_pls:
            if (di, pl) in acc_map: m_acc.extend(acc_map[(di, pl)])
            if (di, pl) in brk_map: m_brk.extend(brk_map[(di, pl)])
        if not m_acc and not m_brk:
            continue
        if m_acc:
            is_acc = 1; best_ld = max(m_acc, key=lambda x: (x[0], -x[1])); n_ld = len(set(x[3] for x in m_acc))
        else:
            is_acc = 0; best_ld = max(m_brk, key=lambda x: (x[0], -x[1])); n_ld = len(set(x[3] for x in m_brk))
        c_rows.append({
            "sig_idx": int(srow),
            "leader_is_accel": int(is_acc),
            "leader_max_streak": int(best_ld[0]),
            "leader_was_yizi": int(best_ld[1]),
            "leader_b_open_pct": float(best_ld[2]),
            "theme_n_leaders": int(n_ld),
        })
    c_sig = pd.DataFrame(c_rows)

    # --- Track D ---
    d_arr = np.array([x[0] for x in d_cand_list], dtype=np.int64)
    d_cand = pd.DataFrame({
        "sig_idx": d_arr,
        "d_idx": d_idx_arr[d_arr],
        "csrc_ind_id": ind_id[d_arr],
        "clv_s": clv[d_arr],
        "r1_s": r1[d_arr],
        "vr5_s": np.array([x[1] for x in d_cand_list], dtype=np.float32),
        "stk_atr": np.array([x[2] for x in d_cand_list], dtype=np.float32),
        "abv20": np.array([x[3] for x in d_cand_list], dtype=np.float32),
    }).merge(
        ind_d[["d_idx", "csrc_ind_id", "ind_n", "ind_turn_pct60", "ind_amt_pct60", "ind_amt_pct250", "ind_atr5_60", "ind_breadth_drop", "ind_crowd_div_flag"]],
        on=["d_idx", "csrc_ind_id"], how="inner",
    )
    d_cand = d_cand[d_cand["ind_n"] >= 12].copy()
    is_cold = (
        ((d_cand["ind_turn_pct60"] < 0.20) | (d_cand["ind_amt_pct60"] < 0.20))
        & (d_cand["ind_atr5_60"] < 0.85)
        & (d_cand["stk_atr"] < 0.80)
    )
    is_seesaw = (
        (d_cand["r1_s"] >= 3.0) & (d_cand["vr5_s"] >= 1.3) & (d_cand["vr5_s"] <= 3.0)
        & (d_cand["clv_s"] >= 0.60) & (d_cand["abv20"] == 1.0)
        & (
            (((d_cand["ind_turn_pct60"] < 0.25) | (d_cand["ind_amt_pct60"] < 0.25)) & (d_cand["ind_atr5_60"] < 0.88))
            | ((d_cand["ind_amt_pct250"] >= 0.80) & ((d_cand["ind_breadth_drop"] <= -0.08) | (d_cand["ind_crowd_div_flag"] == 1)))
        )
    )
    d_cand["flag_cold_strict"] = is_cold.astype(np.int8)
    d_cand["flag_seesaw_contrast"] = is_seesaw.astype(np.int8)
    d_sig = d_cand[is_cold | is_seesaw][["sig_idx", "flag_cold_strict", "flag_seesaw_contrast"]].reset_index(drop=True)

    # Union of all candidate indices
    all_sig_idxs = np.unique(np.concatenate([
        a1_sig["sig_idx"].to_numpy(np.int64),
        a2_sig["sig_idx"].to_numpy(np.int64),
        b_sig["sig_idx"].to_numpy(np.int64),
        c_sig["sig_idx"].to_numpy(np.int64) if not c_sig.empty else np.array([], dtype=np.int64),
        d_sig["sig_idx"].to_numpy(np.int64),
    ]))
    all_buy_idxs = all_sig_idxs + 1

    u_df = pd.DataFrame({"sig_idx": all_sig_idxs, "buy_idx": all_buy_idxs})
    u_df["orig_buy_row"] = orig_row_ids[all_buy_idxs]
    u_df["sig_date"] = [cal_dts[i] for i in d_idx_arr[all_sig_idxs]]
    u_df["buy_date"] = [cal_dts[i] for i in d_idx_arr[all_buy_idxs]]
    u_df["code"] = [c6_arr[i] for i in c_codes[all_buy_idxs]]
    u_df["s_d_idx"] = d_idx_arr[all_sig_idxs]
    u_df["b_d_idx"] = d_idx_arr[all_buy_idxs]
    u_df["buy_hhmm"] = 925
    u_df["exit_hhmm"] = 1500
    u_df["is_yizi"] = is_unbuyable_open[all_buy_idxs]

    u_df["open_pct"] = op[all_buy_idxs]
    u_df["mcap_yi_t1"] = d3["mcap_yi_t1"][all_buy_idxs]
    u_df["ret_5d_t1"] = r5_pre_arr[all_buy_idxs]
    u_df["is_20cm"] = d2["is_20cm"][all_buy_idxs]
    u_df["csrc_ind_id"] = ind_id[all_buy_idxs]
    u_df["csrc_ind_rank20_t1"] = d3["csrc_ind_rank20_t1"][all_buy_idxs]
    u_df["kpl_days_30d_t1"] = d3["kpl_days_30d_t1"][all_buy_idxs]
    u_df["csrc_ind_zt_share5_t1"] = d3["csrc_ind_zt_share5_t1"][all_buy_idxs]
    u_df["sig_is_zt"] = iz[all_sig_idxs]
    u_df["sig_hit_zt"] = d2["hit_zt"][all_sig_idxs]
    u_df["sig_is_broken_zt"] = d2["is_broken_zt"][all_sig_idxs]
    u_df["sig_is_yizi_zt"] = d2["is_yizi_zt"][all_sig_idxs]
    u_df["sig_streak"] = d2["streak"][all_sig_idxs]
    u_df["sig_lower_shad_eod"] = lower_shad[all_sig_idxs]
    u_df["sig_upper_shad_eod"] = upper_shad[all_sig_idxs]

    # Compute exact sig_* EOD metrics ONLY for stocks appearing in `all_sig_idxs`!
    sig_set_c = set(c_codes[all_sig_idxs].tolist())
    # Group all_sig_idxs by stock slice
    sig_pos_in_u = {int(si): ui for ui, si in enumerate(all_sig_idxs)}
    sig_feats = {
        k: np.full(len(u_df), np.nan, dtype=np.float32)
        for k in ["sig_bias5_eod", "sig_bias10_eod", "sig_bias20_eod", "sig_ma5_low_dist_eod",
                  "sig_ma10_low_dist_eod", "sig_vr5_eod", "sig_turn_r5_eod", "sig_ret5_eod",
                  "sig_ret20_eod", "sig_ret20_pre", "sig_atr_5_60_eod", "sig_atr_5_20_eod",
                  "sig_zt_20d_eod", "sig_dd5_eod"]
    }
    by_s = {}
    for ui, si in enumerate(all_sig_idxs):
        by_s.setdefault(int(c_codes[si]), []).append((ui, int(si)))
    for s, e in zip(starts, ends):
        cid = int(c_codes[s])
        if cid not in by_s:
            continue
        blk = _compute_stock_eod_block(
            ac[s:e].astype(np.float64), ah[s:e].astype(np.float64), al[s:e].astype(np.float64),
            np.nan_to_num(amt[s:e].astype(np.float64), nan=0.0),
            np.nan_to_num(trn[s:e].astype(np.float64), nan=0.0),
            r1[s:e], iz[s:e],
        )
        for ui, si in by_s[cid]:
            loc = si - s
            sig_feats["sig_bias5_eod"][ui] = blk["bias5"][loc]
            sig_feats["sig_bias10_eod"][ui] = blk["bias10"][loc]
            sig_feats["sig_bias20_eod"][ui] = blk["bias20"][loc]
            sig_feats["sig_ma5_low_dist_eod"][ui] = blk["ma5_ld"][loc]
            sig_feats["sig_ma10_low_dist_eod"][ui] = blk["ma10_ld"][loc]
            sig_feats["sig_vr5_eod"][ui] = blk["vr5"][loc]
            sig_feats["sig_turn_r5_eod"][ui] = blk["tr5"][loc]
            sig_feats["sig_ret5_eod"][ui] = blk["ret5"][loc]
            sig_feats["sig_ret20_eod"][ui] = blk["ret20"][loc]
            sig_feats["sig_ret20_pre"][ui] = blk["ret20_pre"][loc]
            sig_feats["sig_atr_5_60_eod"][ui] = blk["atr5_60"][loc]
            sig_feats["sig_atr_5_20_eod"][ui] = blk["atr5_20"][loc]
            sig_feats["sig_zt_20d_eod"][ui] = float(blk["zt20"][loc])
            sig_feats["sig_dd5_eod"][ui] = blk["dd5"][loc]
    for k, arr in sig_feats.items():
        u_df[k] = arr

    # Compute exact forward exit dates & gross returns for H in (1, 2, 3, 4, 5)
    is_dt_arr = d2["is_dt"]
    for h in (1, 2, 3, 4, 5):
        ex_dts = np.empty(len(u_df), dtype=object)
        ex_dts[:] = None
        gr_arr = np.full(len(u_df), np.nan, dtype=np.float64)
        for idx_r, bi in enumerate(all_buy_idxs):
            se = seg_end[bi]
            target_di = int(d_idx_arr[bi]) + h
            ep = min(int(bi + h), int(se - 1))
            while ep > bi and d_idx_arr[ep - 1] >= target_di:
                ep -= 1
            while ep < se and d_idx_arr[ep] < target_di:
                ep += 1
            if ep >= se or ep <= bi:
                continue
            lim_d = 0
            while ep < se - 1 and lim_d < 5 and is_dt_arr[ep] == 1:
                ep += 1
                lim_d += 1
            aob = float(ao[bi]); ace = float(ac[ep])
            if is_dt_arr[ep] == 1 or aob <= 0.0 or ace <= 0.0:
                continue
            ex_dts[idx_r] = cal_dts[int(d_idx_arr[ep])]
            gr_arr[idx_r] = ace / aob - 1.0
        u_df[f"exit_date_T{h}"] = ex_dts
        u_df[f"gross_ret_T{h}"] = gr_arr

    # Free ALL 7M-row arrays before Pass 2!
    del d2, d3, ac, ao, ah, al, amt, trn, r1, iz, op, clv, is_st, ind_id
    del lower_shad, upper_shad, orig_row_ids, d_idx_arr, c_codes, seg_end, starts, ends
    del kpl_df, all_theme_df, kpl_plate_day, next_open, pe_by_c, mcap_s_arr, r5_pre_arr, is_unbuyable_open
    gc.collect()
    pa.default_memory_pool().release_unused()

    # Pass 2: Stream remaining 50 columns row-group by row-group and slice ONLY `buy_rows_orig`!
    p2_cols = [
        "free_mcap_yi_t1", "real_turn_pct_t1", "amount_yi_t1", "ret_1d_t1", "prev_clv",
        "prev_streak", "prev_is_broken_zt", "prev_is_yizi_zt", "overhang_pct_t1",
        "hr10d_space_t1", "hr30d_space_t1", "down_streak_t1", "pos_20d_t1", "pos_60d_t1",
        "pos_250d_t1", "dd_20d_t1", "amp_20d_t1", "bias10_t1", "bias20_t1", "ret_20d_t1",
        "vol_ratio5_t1", "turn_5_20_t1", "amp_comp_20v60_t1",
        "lhb_on_t1", "lhb_bayes_t2_t1", "lhb_inst_net_yi_t1", "lhb_lhasa_share_t1",
        "lhb_has_good_yz_t1", "lhb_has_quant_t1", "d1_first_seal_hhmm_t1",
        "d1_open_board_cnt_t1", "d1_seal_ratio_t1", "list_age", "waves_3y_g15_t1",
        "zt_cnt_1y_t1", "trap_waves_3y", "dd_from_3y_high", "cool_days_since_last_zt",
        "xq_posts_1y_pct", "kpl_in_t1", "kpl_rank_t1", "kpl_zt1_t1", "kpl_zt3_t1",
        "kpl_streak_t1", "csrc_ind_ex5_t1", "csrc_ind_ex20_t1", "csrc_ind_amt_pct250_t1",
        "tox_reg_30d_pre", "abn_notice_30d_pre", "ir_cnt_30d_pre",
    ]
    buy_rows_orig = u_df["orig_buy_row"].to_numpy(np.int64)
    pf = pq.ParquetFile(CORE_PQ)
    schema = pf.schema_arrow
    p2_buf = {}
    for c in p2_cols:
        pa_t = schema.field(c).type
        np_dt = np.float32 if pa.types.is_floating(pa_t) else (np.int8 if pa.types.is_int8(pa_t) else (np.int16 if pa.types.is_int16(pa_t) else np.int32))
        p2_buf[c] = np.empty(len(u_df), dtype=np_dt)
    rg_start = 0
    for rg in range(pf.num_row_groups):
        m_rg = pf.metadata.row_group(rg).num_rows
        rg_end = rg_start + m_rg
        in_rg = (buy_rows_orig >= rg_start) & (buy_rows_orig < rg_end)
        if in_rg.any():
            loc_idx = buy_rows_orig[in_rg] - rg_start
            for b_start in range(0, len(p2_cols), 17):
                sub_cols = p2_cols[b_start : b_start + 17]
                tbl = pf.read_row_group(rg, columns=sub_cols)
                for c in sub_cols:
                    p2_buf[c][in_rg] = tbl.column(c).to_numpy(zero_copy_only=False)[loc_idx]
                del tbl
                pa.default_memory_pool().release_unused()
        rg_start = rg_end
    for c in p2_cols:
        u_df[c] = p2_buf[c]
    del p2_buf
    gc.collect()

    ind_b = ind_d[["d_idx", "csrc_ind_id", "ind_open_gap_mean", "mkt_open_med"]].rename(
        columns={"d_idx": "b_d_idx", "ind_open_gap_mean": "b_ind_open_gap_mean", "mkt_open_med": "b_mkt_open_med"}
    )
    u_df = u_df.merge(ind_b, on=["b_d_idx", "csrc_ind_id"], how="left")
    u_df["b_gap_minus_ind_gap"] = (u_df["open_pct"] - u_df["b_ind_open_gap_mean"]).astype(np.float32)
    u_df["b_ind_minus_mkt_gap"] = (u_df["b_ind_open_gap_mean"] - u_df["b_mkt_open_med"]).astype(np.float32)

    ind_s_cols = [
        "d_idx", "csrc_ind_id", "ind_n", "ind_zt", "ind_ret", "ind_above5", "ind_above20",
        "ind_atr5_60", "ind_turn_pct60", "ind_amt_pct60", "ind_amt_pct250",
        "ind_breadth_drop", "ind_crowd_div_flag", "ind_crowd_x_div",
    ]
    ind_s = ind_d[ind_s_cols].rename(
        columns={c: (f"sig_{c}" if c not in ("d_idx", "csrc_ind_id") else c) for c in ind_s_cols}
    ).rename(columns={"d_idx": "s_d_idx"})
    u_df = u_df.merge(ind_s, on=["s_d_idx", "csrc_ind_id"], how="left")

    mkt_cols = [
        "trade_date", "L1_zt_cnt_t1", "L1_zb_rate_t1", "L1_max_board_t1", "L1_zt_prem_t1",
        "L1_lb_promo_t1", "L1_duanban_damian_t1", "L1_sent_phase_t1", "L1_smb_20d_t1",
        "L1_amt_ratio20_t1", "L1_ew_bias20_t1", "mkt_pct_above_ma20_t1", "mkt_0925_zt_cnt",
        "mkt_0925_avg_gap_pct", "us_ixic_ret1d_on", "us_vix_chg1d_on",
    ]
    mkt_all = pd.read_parquet(MKT_PQ, columns=mkt_cols)
    mkt_all = mkt_all[mkt_all["trade_date"] <= end_cutoff].rename(columns={"trade_date": "buy_date"})
    u_df = u_df.merge(mkt_all, on="buy_date", how="left")

    u_df["b_div_to_cons_score"] = (
        (u_df["sig_is_broken_zt"].values == 1).astype(float) * 1.0
        + (u_df["prev_clv"].values < 0.75).astype(float) * 0.5
        + np.clip(u_df["open_pct"].values, -5.0, 8.0) * 0.25
        - (u_df["sig_is_yizi_zt"].values == 1).astype(float) * 1.5
    ).astype(np.float32)

    u_df["sig_anti_crowd_score"] = (
        (1.0 - u_df["sig_ind_turn_pct60"].fillna(0.5).values) * 0.4
        + (1.0 - u_df["sig_ind_amt_pct250"].fillna(0.5).values) * 0.3
        + (1.0 - np.clip(u_df["sig_ind_atr5_60"].fillna(0.9).values, 0.4, 1.5)) * 0.3
        - u_df["sig_ind_crowd_div_flag"].fillna(0).values * 1.5
        - u_df["sig_ind_crowd_x_div"].fillna(0.0).values * 2.0
    ).astype(np.float32)

    a1_df = a1_sig.merge(u_df, on="sig_idx", how="inner").reset_index(drop=True)
    a2_df = a2_sig.merge(u_df, on="sig_idx", how="inner").reset_index(drop=True)

    b_all = b_sig.merge(u_df, on="sig_idx", how="inner").reset_index(drop=True)
    is_main = (
        (b_all["csrc_ind_rank20_t1"] <= 12)
        | (b_all["kpl_days_30d_t1"] >= 3)
        | (b_all["sig_zt_20d_eod"] >= 1)
    )
    b1_df = b_all[is_main].copy().reset_index(drop=True)
    b2_df = b_all[(b_all["sig_vr5_eod"] <= 0.60) & (b_all["ret_1d_t1"] <= 0.0)].copy().reset_index(drop=True)

    c_full = c_sig.merge(u_df, on="sig_idx", how="inner").reset_index(drop=True) if not c_sig.empty else pd.DataFrame()
    if not c_full.empty:
        c_full["b_open_minus_leader_open"] = (c_full["open_pct"] - c_full["leader_b_open_pct"]).astype(np.float32)
        c1_df = c_full[c_full["leader_is_accel"] == 1].copy().reset_index(drop=True)
        c2_df = c_full[c_full["leader_is_accel"] == 0].copy().reset_index(drop=True)
    else:
        c1_df, c2_df = pd.DataFrame(), pd.DataFrame()

    d_full = d_sig.merge(u_df, on="sig_idx", how="inner").reset_index(drop=True)
    d1_df = d_full[d_full["flag_cold_strict"] == 1].copy().reset_index(drop=True)
    d2_df = d_full[d_full["flag_seesaw_contrast"] == 1].copy().reset_index(drop=True)
    d3_df = d_full[
        (d_full["flag_seesaw_contrast"] == 1)
        & (d_full["sig_ind_crowd_div_flag"] == 0)
        & (d_full["sig_ind_amt_pct250"] < 0.85)
    ].copy().reset_index(drop=True)

    print(f"[Pools end={end_cutoff}] union={len(u_df)} built in {time.time()-t0:.2f}s")
    return {
        "A1_KPL": a1_df,
        "A2_CSRC": a2_df,
        "B1_MAINLINE": b1_df,
        "B2_ALLTREND": b2_df,
        "C0_ALL": c_full,
        "C1_ACCEL": c1_df,
        "C2_BROKEN": c2_df,
        "D1_COLD_STRICT": d1_df,
        "D2_SEESAW_BROAD": d2_df,
        "D3_NO_CROWD_DIV": d3_df,
    }


def get_track_features(df_pool: pd.DataFrame, track: str) -> list[str]:
    common = [
        "open_pct", "b_gap_minus_ind_gap", "b_ind_minus_mkt_gap",
        "mcap_yi_t1", "free_mcap_yi_t1", "real_turn_pct_t1", "amount_yi_t1",
        "ret_1d_t1", "prev_clv", "sig_lower_shad_eod", "sig_upper_shad_eod",
        "sig_vr5_eod", "sig_turn_r5_eod", "sig_ret5_eod", "sig_ret20_eod",
        "sig_bias5_eod", "sig_bias10_eod", "sig_bias20_eod",
        "sig_atr_5_60_eod", "sig_zt_20d_eod", "sig_dd5_eod",
        "pos_20d_t1", "pos_60d_t1", "pos_250d_t1", "overhang_pct_t1", "hr10d_space_t1",
        "is_20cm", "xq_posts_1y_pct", "ir_cnt_30d_pre", "abn_notice_30d_pre",
        "lhb_on_t1", "lhb_inst_net_yi_t1", "lhb_lhasa_share_t1", "lhb_bayes_t2_t1",
        "csrc_ind_ex5_t1", "csrc_ind_ex20_t1", "csrc_ind_rank20_t1", "csrc_ind_zt_share5_t1",
        "sig_ind_turn_pct60", "sig_ind_amt_pct250", "sig_ind_above5", "sig_ind_above20",
        "sig_ind_atr5_60", "sig_ind_breadth_drop",
        "kpl_days_30d_t1", "kpl_zt3_t1", "kpl_rank_t1",
        "L1_sent_phase_t1", "L1_zt_cnt_t1", "L1_zb_rate_t1", "L1_zt_prem_t1",
        "L1_amt_ratio20_t1", "mkt_pct_above_ma20_t1", "mkt_0925_avg_gap_pct", "us_ixic_ret1d_on",
    ]
    if track.startswith("A"):
        extra = [
            "climax_plate_zt", "climax_plate_n", "climax_zt_jump", "climax_mkt_cnt",
            "sig_is_zt", "sig_is_broken_zt", "sig_is_yizi_zt", "sig_streak",
            "d1_first_seal_hhmm_t1", "d1_open_board_cnt_t1", "d1_seal_ratio_t1",
            "b_div_to_cons_score", "b_ind_open_gap_mean", "lhb_has_good_yz_t1",
        ]
    elif track.startswith("B"):
        extra = [
            "sig_ma5_low_dist_eod", "sig_ma10_low_dist_eod", "down_streak_t1",
            "dd_20d_t1", "amp_20d_t1", "turn_5_20_t1", "L1_ew_bias20_t1",
        ]
    elif track.startswith("C"):
        extra = [
            "leader_is_accel", "leader_max_streak", "leader_was_yizi",
            "leader_b_open_pct", "b_open_minus_leader_open", "theme_n_leaders",
            "ret_5d_t1", "sig_ret20_pre", "L1_max_board_t1", "L1_lb_promo_t1",
        ]
    else:
        extra = [
            "sig_ind_amt_pct60", "sig_ind_crowd_div_flag", "sig_ind_crowd_x_div",
            "sig_anti_crowd_score", "sig_ret20_pre", "amp_comp_20v60_t1",
        ]
    drop = {
        "abn_notice_30d_pre", "tox_reg_30d_pre", "kpl_in_t1",
        "kpl_rank_t1", "kpl_zt1_t1", "kpl_zt3_t1", "kpl_streak_t1",
    }
    if track.startswith("A1"):
        drop |= {"sig_is_zt", "sig_is_broken_zt", "sig_is_yizi_zt", "prev_clv", "sig_upper_shad_eod"}
    elif track.startswith("A2"):
        drop |= {"sig_is_broken_zt", "sig_is_yizi_zt", "lhb_has_good_yz_t1", "lhb_lhasa_share_t1"}
    else:
        drop |= {
            "lhb_on_t1", "lhb_bayes_t2_t1", "lhb_inst_net_yi_t1", "lhb_lhasa_share_t1",
            "lhb_has_good_yz_t1", "d1_first_seal_hhmm_t1", "d1_open_board_cnt_t1",
            "d1_seal_ratio_t1", "sig_is_zt", "sig_is_broken_zt", "sig_is_yizi_zt",
            "sig_streak", "leader_was_yizi",
        }
    if track in ("C1_ACCEL", "C2_BROKEN"):
        drop.add("leader_is_accel")
    if track in ("D1_COLD_STRICT", "D3_NO_CROWD_DIV"):
        drop.add("sig_ind_crowd_div_flag")

    cols, seen = [], set()
    for c in extra + common:
        if c in df_pool.columns and c not in seen and c not in drop:
            seen.add(c)
            cols.append(c)
    return cols


def build_all_pools(end_cutoff: str = "2026-11-25") -> dict:
    return _load_pass1_and_scan(end_cutoff=end_cutoff)


def build_stk_px_map(codes_needed: set[str]) -> dict:
    """Read only 5 OHLC/adj columns once into compact int16/float32 numpy arrays (RAM < 0.3 GB)."""
    pf = pq.ParquetFile(CORE_PQ)
    chunks = []
    dt_cats = None
    for rg in range(pf.num_row_groups):
        tbl = pf.read_row_group(rg, columns=["dt", "c6", "open", "close", "adj_factor"])
        sub = tbl.to_pandas()
        del tbl
        if dt_cats is None:
            dt_cats = sub["dt"].cat.categories.astype(str).tolist()
        c6_s = sub["c6"].astype(str)
        m = c6_s.isin(codes_needed).values
        if m.any():
            chunks.append(pd.DataFrame({
                "c6_s": c6_s.values[m],
                "d_code": sub["dt"].cat.codes.values[m].astype(np.int16),
                "ao": (sub["open"].values[m] * sub["adj_factor"].values[m]).astype(np.float32),
                "ac": (sub["close"].values[m] * sub["adj_factor"].values[m]).astype(np.float32),
            }))
    pa.default_memory_pool().release_unused()
    if not chunks:
        return {}
    px = pd.concat(chunks, ignore_index=True).sort_values(["c6_s", "d_code"]).reset_index(drop=True)
    del chunks
    dt_to_code = {d: i for i, d in enumerate(dt_cats)}
    stk_map = {"__dt_to_code__": dt_to_code, "__code_to_dt__": dt_cats}
    c6v = px["c6_s"].values
    dc = px["d_code"].values
    ao_v = px["ao"].values
    ac_v = px["ac"].values
    brk = np.flatnonzero(c6v[1:] != c6v[:-1]) + 1
    for s, e in zip(np.concatenate(([0], brk)), np.concatenate((brk, [len(px)]))):
        stk_map[str(c6v[s])] = (dc[s:e].copy(), ao_v[s:e].copy(), ac_v[s:e].copy())
    del px
    gc.collect()
    return stk_map


def compute_exact_daily_mtm_series(
    slot_df: pd.DataFrame,
    cal_dts: list[str],
    fee_rt: float = 0.0030,
    stk_map: Optional[dict] = None,
) -> tuple[np.ndarray, float]:
    T = len(cal_dts)
    if slot_df.empty:
        return np.zeros(T, dtype=float), 0.0
    dt_idx = {d: i for i, d in enumerate(cal_dts)}
    if stk_map is None:
        codes_needed = set(slot_df["code"].astype(str).str.zfill(6).unique())
        stk_map = build_stk_px_map(codes_needed)
    if not stk_map or "__dt_to_code__" not in stk_map:
        return np.zeros(T, dtype=float), 0.0

    dt_to_code = stk_map["__dt_to_code__"]
    code_to_dt = stk_map["__code_to_dt__"]
    day_mult = np.ones(T, dtype=float)
    for r in slot_df.itertuples(index=False):
        c = str(r.code).zfill(6)
        bd = str(r.buy_date)
        ed = str(r.exit_date)
        tup = stk_map.get(c)
        bc = dt_to_code.get(bd)
        ec = dt_to_code.get(ed)
        if tup is None or bc is None or ec is None:
            continue
        dc_a, ao_a, ac_a = tup
        bp = int(np.searchsorted(dc_a, bc))
        ep = int(np.searchsorted(dc_a, ec))
        if bp >= len(dc_a) or ep >= len(dc_a) or dc_a[bp] != bc or dc_a[ep] != ec or ep <= bp:
            continue
        mult0 = (float(ac_a[bp]) / float(ao_a[bp])) * (1.0 - fee_rt)
        ti0 = dt_idx.get(bd)
        if ti0 is not None:
            day_mult[ti0] *= mult0
        for k in range(bp + 1, ep + 1):
            tik = dt_idx.get(code_to_dt[int(dc_a[k])])
            if tik is not None:
                day_mult[tik] *= (float(ac_a[k]) / float(ac_a[k - 1]))

    dr = day_mult - 1.0
    tr_sub = slot_df[slot_df["buy_date"].isin(dt_idx) & slot_df["exit_date"].isin(dt_idx)]
    tr_nav = float(np.prod(1.0 + tr_sub["net_ret"].to_numpy(float))) if not tr_sub.empty else 1.0
    return dr, abs(float(np.prod(day_mult)) - tr_nav)


if __name__ == "__main__":
    import resource
    t0 = time.time()
    save_cache = "--save-cache" in sys.argv
    pools = build_all_pools("2026-11-25")
    cache_dir = os.path.join(OUT_DIR, "_cache_pools")
    if save_cache:
        os.makedirs(cache_dir, exist_ok=True)
    for k, v in pools.items():
        if save_cache and not v.empty:
            v.to_parquet(os.path.join(cache_dir, f"{k}.parquet"), index=False)
        wf_n = int((v["buy_date"] >= "2023-01-03").sum()) if not v.empty else 0
        pre_n = int((v["buy_date"] < "2023-01-03").sum()) if not v.empty else 0
        days_wf = int(v.loc[v["buy_date"] >= "2023-01-03", "buy_date"].nunique()) if not v.empty else 0
        yz_pct = float(v["is_yizi"].mean() * 100.0) if not v.empty else 0.0
        print(f"{k:18s} | total={len(v):6d} | pre23={pre_n:5d} | wf23+={wf_n:6d} ({days_wf:3d}d) | yizi={yz_pct:.1f}%")
    rss_gb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e9
    print(f"Done in {time.time()-t0:.2f}s | Peak RSS = {rss_gb:.3f} GB")

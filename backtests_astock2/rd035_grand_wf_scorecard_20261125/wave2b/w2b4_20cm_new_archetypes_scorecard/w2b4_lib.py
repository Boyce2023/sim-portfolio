#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 2B-4 Shared Library:
Strictly PIT (T-1 / 09:25) 20cm New Archetypes Builder, Exit Tree Simulator,
Daily MTM Builder, V20 Correlation & Empty-Slot Patch Evaluator.

Five mutually-exclusive 20cm tracks (0% overlap with S82 1st-ZT deep-open [-10%, -3%]):
  - Track A: 20cm 连板接力 (1进2 & 2进3 非一字开盘; tests h1, h2, and 20cm 4-branch exit tree)
  - Track B: 20cm 高标首阴反包 (streak>=2 or 3d>=40% first yin pullback, next-day low/flat open)
  - Track C: 20cm 首板/连板断板后 1~3 日缩量回踩反包 (no break of ZT low + vol shrink + turn strong)
  - Track D: 20cm 冲板炸板次日深水低吸 (prev_is_broken_zt == 1 + deep open, complement to S82)
  - Track E: 20cm 强主线首板次日非深水买点 (prev_streak == 1, open_pct in [-1%, +8%], disjoint from S82)

Constraints:
  - Zero yfinance (D12). Zero cap10m. Threads <= 1. Peak RSS < 1.8 GB.
  - Round-trip fee = 0.30%. Excludes 一字不可买.
"""
import os

for _env in (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
):
    os.environ[_env] = "1"

import gc
import json
import math
import resource
import sys
import time
from typing import Optional

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

pa.set_cpu_count(1)
pa.set_io_thread_count(1)

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
WAVE1_BASE = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
OUT_DIR = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave2b/w2b4_20cm_new_archetypes_scorecard"

if WAVE1_BASE not in sys.path:
    sys.path.insert(0, WAVE1_BASE)

import _wf_core as wfc
import _wf_sim_and_metrics as wfm
import _wf_v20_patch as wfp
import wf_scorecard_engine as wf

CORE_PQ = f"{WAVE1_BASE}/stock_day_core_features_pit.parquet"
MKT_PQ = f"{WAVE1_BASE}/market_daily_all_new_factors_pit.parquet"

CORE_PIT_FEATURE_COLS = [
    "open_pct",
    "mcap_yi_t1",
    "amount_yi_t1",
    "ret_1d_t1",
    "d1_open_pct",
    "prev_clv",
    "prev_streak",
    "prev_is_broken_zt",
    "prev_is_yizi_zt",
    "overhang_pct_t1",
    "hr10d_space_t1",
    "hr30d_space_t1",
    "down_streak_t1",
    "pos_20d_t1",
    "pos_60d_t1",
    "pos_250d_t1",
    "dd_20d_t1",
    "amp_20d_t1",
    "bias10_t1",
    "bias20_t1",
    "ret_5d_t1",
    "ret_20d_t1",
    "vol_ratio5_t1",
    "turn_5_20_t1",
    "amp_comp_20v60_t1",
    "lhb_on_t1",
    "lhb_bayes_t2_t1",
    "lhb_inst_net_yi_t1",
    "lhb_lhasa_share_t1",
    "lhb_has_good_yz_t1",
    "lhb_has_surf_yz_t1",
    "lhb_has_quant_t1",
    "lhb_cnt_5d_t1",
    "lock_top10_pct_pre",
    "free_mcap_yi_t1",
    "real_turn_pct_t1",
    "d1_first_seal_hhmm_t1",
    "d1_open_board_cnt_t1",
    "d1_seal_ratio_t1",
    "list_age",
    "waves_3y_g15_t1",
    "zt_cnt_1y_t1",
    "max_streak_3y",
    "cum_turnover_1y",
    "trap_waves_3y",
    "dd_from_3y_high",
    "cool_days_since_last_zt",
    "cool_days_since_last_2b",
    "comm_posts_1y_pct",
    "xq_posts_1y_pct",
    "kpl_unique_plates_3y",
    "kpl_top_plate_share",
    "kpl_zt3_t1",
    "kpl_days_30d_t1",
    "kpl_in_t1",
    "kpl_rank_t1",
    "kpl_zt1_t1",
    "kpl_streak_t1",
    "csrc_ind_ex5_t1",
    "csrc_ind_ex20_t1",
    "csrc_ind_rank20_t1",
    "csrc_ind_zt_share5_t1",
    "csrc_ind_amt_pct250_t1",
    "abn_notice_30d_pre",
    "ir_cnt_30d_pre",
    "comm_ring_tier",
]

ENG_COMMON_COLS = [
    "eng_d1_body_t1",
    "eng_d1_upper_shad_t1",
    "eng_d1_broken_dd_t1",
    "eng_d1_amt_to_mcap",
    "eng_min_hr_space_t1",
    "eng_ret_3d_t1",
    "eng_zt_cnt_20d_t1",
    "eng_zt_cnt_60d_t1",
    "eng_turn_pct_t1",
    "eng_rel_open_vs_mkt",
    "eng_open_minus_d1_open",
    "eng_mkt10_zt_est_t1",
    "eng_csrc20_zt_cnt_t1",
    "eng_csrc20_open_mean",
    "eng_mkt20_prevzt_open_mean",
    "eng_mkt20_prevzt_n",
    "eng_is_monday",
    "eng_is_2to3",
    "eng_streak_t2",
    "eng_surge_ret3_pre",
    "eng_yin_vol_ratio",
    "eng_pb_days",
    "eng_pb_vol_shrink",
    "eng_pb_price_retrace",
    "eng_pb_ret_cum",
    "eng_open_vs_zt_close",
    "eng_zt_orig_streak",
    "eng_zt_orig_clv",
    "eng_zt_orig_amt",
]


def get_rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 2)


def sanitize_json(obj):
    if isinstance(obj, dict):
        return {str(k): sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_json(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return None if (np.isnan(v) or np.isinf(v)) else round(v, 6)
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    return obj


def _sim_exit_modes_at_idx(
    idx_buy: int,
    span_start: int,
    span_end: int,
    ao: np.ndarray,
    ah: np.ndarray,
    ac: np.ndarray,
    adjf: np.ndarray,
    close_raw: np.ndarray,
    opct: np.ndarray,
    clv_a: np.ndarray,
    iszt: np.ndarray,
    isdt: np.ndarray,
    isyz_dt: np.ndarray,
    amt_yi: np.ndarray,
    lhb_inst_t1: np.ndarray,
    dt_arr: np.ndarray,
    dt_cats: np.ndarray,
    mkt_dt20_t1: dict,
    mkt_dt10_t1: dict,
    modes: tuple[str, ...] = ("h1", "h2", "v11"),
) -> dict:
    """Simulate exit modes ('h1', 'h2', 'v11') for a 20cm buy at idx_buy (T 09:25 open)."""
    out = {}
    if idx_buy + 1 >= span_end:
        return out
    b_px = float(ao[idx_buy])
    if not (np.isfinite(b_px) and b_px > 0.0):
        return out

    f2 = idx_buy + 1
    risk_hit = (
        (lhb_inst_t1[f2] < -0.20)
        or (mkt_dt20_t1.get(int(dt_arr[f2]), 0) >= 3)
        or (mkt_dt10_t1.get(int(dt_arr[f2]), 0) >= 20)
    )

    def sell_strict(k: int) -> bool:
        return (amt_yi[k] > 0.0) and (close_raw[k] > 0.0) and (isdt[k] == 0)

    def sell_loose(k: int) -> bool:
        return (amt_yi[k] > 0.0) and (close_raw[k] > 0.0) and (isyz_dt[k] == 0)

    def zt_px_adj(k: int) -> float:
        prev_raw = ac[k - 1] / float(adjf[k])
        return (math.floor(prev_raw * 1.20 * 100.0 + 0.5) / 100.0) * float(adjf[k])

    def try_tp(k: int, tp_r: float, ref_px: float):
        if k >= span_end or not sell_loose(k):
            return False, np.nan, ""
        tp_px = ref_px * (1.0 + tp_r)
        if ao[k] >= tp_px and opct[k] > -19.5:
            return True, float(ao[k]), "gap_tp"
        need_ah = min(tp_px * 1.0030, zt_px_adj(k) - 1e-4)
        if ah[k] >= need_ah:
            return True, float(tp_px), "intraday_tp"
        return False, np.nan, ""

    def finalize_trade(sell_k: int, s_px: float, reason: str, eh: int):
        if np.isnan(s_px):
            while sell_k < min(idx_buy + 11, span_end) and not sell_strict(sell_k):
                sell_k += 1
            if sell_k >= span_end:
                return None
            s_px = float(ac[sell_k])
        if sell_k <= idx_buy or not (np.isfinite(s_px) and s_px > 0.0):
            return None
        gross = s_px / b_px - 1.0
        net = (1.0 + gross) * (1.0 - 0.0030) - 1.0
        segs = []
        prev_v = b_px
        last_c = b_px
        for k in range(idx_buy, sell_k):
            ck = float(ac[k]) if (np.isfinite(ac[k]) and ac[k] > 0.0) else last_c
            segs.append((str(dt_cats[int(dt_arr[k])]), ck / prev_v))
            prev_v, last_c = ck, ck
        end_px_net = b_px * (1.0 + net)
        e_dt = str(dt_cats[int(dt_arr[sell_k])])
        segs.append((e_dt, end_px_net / prev_v))
        return (e_dt, eh, gross, sell_k - idx_buy, reason, json.dumps(segs))

    for mode in modes:
        sell_k, s_px, reason, eh = f2, np.nan, "", 1500
        if mode == "h1":
            sell_k, reason = f2, "h1_close"
        elif mode == "h2":
            if idx_buy + 2 >= span_end:
                continue
            sell_k, reason = idx_buy + 2, "h2_close"
        elif mode == "v11":
            if iszt[idx_buy] == 1:
                k = f2
                while k < min(idx_buy + 10, span_end) and iszt[k] == 1:
                    k += 1
                if k >= span_end:
                    continue
                sell_k, reason = k, "B1_zt_break"
            else:
                f1_ac, f1_ao = float(ac[idx_buy]), b_px
                f1_body = f1_ac / f1_ao - 1.0
                f1_clv = float(clv_a[idx_buy]) if np.isfinite(clv_a[idx_buy]) else 0.5
                is_b4 = (f1_body <= -0.05) or (isdt[idx_buy] == 1)
                is_b2 = (not is_b4) and (f1_body >= 0.06) and (f1_clv >= 0.65)
                if is_b4:
                    sell_k, reason = f2, "B4_d2_close"
                elif is_b2:
                    tp2 = 0.07 if risk_hit else 0.12
                    hit, px_h, r_h = try_tp(f2, tp2, f1_ac)
                    if hit:
                        s_px, sell_k, reason = px_h, f2, f"B2_{r_h}"
                        eh = 1030
                    elif not risk_hit:
                        if idx_buy + 2 >= span_end:
                            continue
                        f3 = idx_buy + 2
                        if iszt[f2] == 1:
                            k = f3
                            while k < min(idx_buy + 10, span_end) and iszt[k] == 1:
                                k += 1
                            if k >= span_end:
                                continue
                            sell_k, reason = k, "B2_d2zt_ride"
                        else:
                            hit3, px3, r3 = try_tp(f3, tp2, float(ac[f2]))
                            if hit3:
                                s_px, sell_k, reason = px3, f3, f"B2_d3_{r3}"
                                eh = 1030
                            else:
                                sell_k, reason = f3, "B2_d3_close"
                    else:
                        sell_k, reason = f2, "B2_d2_close"
                else:
                    tp3 = max(0.06, min(0.15, abs(float(opct[idx_buy]) / 100.0) * 1.5))
                    if risk_hit:
                        tp3 = min(tp3, 0.07)
                    hit, px_h, r_h = try_tp(f2, tp3, f1_ac)
                    if hit:
                        s_px, sell_k, reason = px_h, f2, f"B3_{r_h}"
                        eh = 1030
                    else:
                        sell_k, reason = f2, "B3_d2_close"
        res = finalize_trade(sell_k, s_px, reason, eh)
        if res is not None:
            out[mode] = res
    return out


def build_w2b4_candidate_pool(end_cutoff: str = "2026-11-16") -> tuple[pd.DataFrame, list[str], dict]:
    """
    Two-phase strictly PIT, ultra-low-RAM (< 1.5 GB) builder for all 5 20cm new archetype tracks.
    Returns (master_cand_df, all_feature_cols, build_meta).
    """
    t0 = time.time()
    p1_cols = [
        "dt", "c6", "open", "high", "low", "close", "adj_factor",
        "ret_1d", "open_pct", "clv", "is_zt", "is_yizi_zt", "is_dt", "is_yizi_dt",
        "streak", "is_st_pit", "list_age", "amount_yi", "turn_pct",
        "prev_streak", "prev_is_broken_zt", "prev_is_yizi_zt",
        "tox_reg_30d_pre", "lhb_inst_net_yi_t1", "csrc_ind_id",
    ]
    flt_p1 = (ds.field("is_20cm") == 1) & (ds.field("dt") <= end_cutoff)
    tbl_p1 = ds.dataset(CORE_PQ).scanner(columns=p1_cols, filter=flt_p1).to_table()
    df = tbl_p1.to_pandas(self_destruct=True)
    del tbl_p1
    gc.collect()
    pa.default_memory_pool().release_unused()

    dt_cats = df["dt"].cat.categories.to_numpy(dtype=str)
    c6_cats = df["c6"].cat.categories.to_numpy(dtype=str)
    dt_i_raw = df["dt"].cat.codes.to_numpy(np.int16)
    c6_i_raw = df["c6"].cat.codes.to_numpy(np.int16)
    order = np.lexsort((dt_i_raw, c6_i_raw))

    c6_arr = c6_i_raw[order]
    dt_arr = dt_i_raw[order]
    del dt_i_raw, c6_i_raw
    adjf = df["adj_factor"].to_numpy(np.float32)[order]
    ao = df["open"].to_numpy(np.float32)[order].astype(np.float64) * adjf
    ah = df["high"].to_numpy(np.float32)[order].astype(np.float64) * adjf
    al = df["low"].to_numpy(np.float32)[order].astype(np.float64) * adjf
    ac = df["close"].to_numpy(np.float32)[order].astype(np.float64) * adjf
    close_raw = df["close"].to_numpy(np.float32)[order]
    open_raw = df["open"].to_numpy(np.float32)[order]
    high_raw = df["high"].to_numpy(np.float32)[order]
    low_raw = df["low"].to_numpy(np.float32)[order]
    opct = df["open_pct"].to_numpy(np.float32)[order]
    clv_a = df["clv"].to_numpy(np.float32)[order]
    iszt = df["is_zt"].to_numpy(np.int8)[order]
    isdt = df["is_dt"].to_numpy(np.int8)[order]
    isyz_zt = df["is_yizi_zt"].to_numpy(np.int8)[order]
    isyz_dt = df["is_yizi_dt"].to_numpy(np.int8)[order]
    is_st = df["is_st_pit"].to_numpy(np.int8)[order]
    list_age_a = df["list_age"].to_numpy(np.int16)[order]
    amt_yi = df["amount_yi"].to_numpy(np.float32)[order]
    prev_st = df["prev_streak"].to_numpy(np.int8)[order]
    prev_bk = df["prev_is_broken_zt"].to_numpy(np.int8)[order]
    prev_yz = df["prev_is_yizi_zt"].to_numpy(np.int8)[order]
    tox_pre = df["tox_reg_30d_pre"].to_numpy(np.int8)[order]
    lhb_inst_t1 = df["lhb_inst_net_yi_t1"].to_numpy(np.float32)[order]
    csrc_ind_a = df["csrc_ind_id"].to_numpy(np.int16)[order]
    streak_a = df["streak"].to_numpy(np.int8)[order]
    ret_1d_a = df["ret_1d"].to_numpy(np.float32)[order]
    turn_a = df["turn_pct"].to_numpy(np.float32)[order]
    del df, order
    gc.collect()
    pa.default_memory_pool().release_unused()

    dt_str_to_i = {s: i for i, s in enumerate(dt_cats)}
    mkt_all = pd.read_parquet(MKT_PQ)
    mkt_all = mkt_all[mkt_all["trade_date"] <= end_cutoff].sort_values("trade_date").reset_index(drop=True)
    mkt_all["dt_i"] = mkt_all["trade_date"].map(dt_str_to_i).fillna(-1).astype(np.int16)
    mkt_dt20_t1 = dict(zip(mkt_all["dt_i"], mkt_all["mkt20_dt_cnt_t1"]))
    mkt_dt10_t1 = dict(zip(mkt_all["dt_i"], mkt_all["L1_dt_cnt_t1"] - mkt_all["mkt20_dt_cnt_t1"]))
    mkt_gap_map = dict(zip(mkt_all["dt_i"], mkt_all["mkt_0925_avg_gap_pct"]))
    mkt_zt_est_map = dict(zip(mkt_all["dt_i"], mkt_all["L1_zt_cnt_t1"] - mkt_all["mkt20_zt_cnt_t1"]))
    mkt_wd_map = dict(zip(mkt_all["dt_i"], mkt_all["L1_weekday"]))

    n_rows = len(c6_arr)
    brk = np.flatnonzero(c6_arr[1:] != c6_arr[:-1]) + 1
    starts = np.concatenate(([0], brk))
    ends = np.concatenate((brk, [n_rows]))
    span_start_arr = np.empty(n_rows, dtype=np.int32)
    span_end_arr = np.empty(n_rows, dtype=np.int32)
    for s, e in zip(starts, ends):
        span_start_arr[s:e] = s
        span_end_arr[s:e] = e

    def _shift_by_span(arr: np.ndarray, k: int, fill_val=np.nan, out_dtype=np.float32) -> np.ndarray:
        out = np.full(n_rows, fill_val, dtype=out_dtype)
        for s, e in zip(starts, ends):
            if e - s > k:
                out[s + k : e] = arr[s : e - k]
        return out

    close_t1 = _shift_by_span(close_raw, 1)
    open_t1 = _shift_by_span(open_raw, 1)
    high_t1 = _shift_by_span(high_raw, 1)
    low_t1 = _shift_by_span(low_raw, 1)
    turn_t1 = _shift_by_span(turn_a, 1)
    amt_yi_t1 = _shift_by_span(amt_yi, 1)
    ret_1d_t1_a = _shift_by_span(ret_1d_a, 1)
    ret_1d_t2 = _shift_by_span(ret_1d_a, 2)
    close_t2 = _shift_by_span(close_raw, 2)
    open_t2 = _shift_by_span(open_raw, 2)
    amt_t2 = _shift_by_span(amt_yi, 2)
    amt_t3 = _shift_by_span(amt_yi, 3)
    amt_t4 = _shift_by_span(amt_yi, 4)
    streak_t2 = _shift_by_span(streak_a, 2, 0, np.int8)
    streak_t3 = _shift_by_span(streak_a, 3, 0, np.int8)
    streak_t4 = _shift_by_span(streak_a, 4, 0, np.int8)

    ac_t1 = _shift_by_span(ac, 1, np.nan, np.float64)
    ac_t2 = _shift_by_span(ac, 2, np.nan, np.float64)
    ac_t3 = _shift_by_span(ac, 3, np.nan, np.float64)
    ac_t4 = _shift_by_span(ac, 4, np.nan, np.float64)
    ac_t5 = _shift_by_span(ac, 5, np.nan, np.float64)
    al_t1 = _shift_by_span(al, 1, np.nan, np.float64)
    al_t2 = _shift_by_span(al, 2, np.nan, np.float64)
    al_t3 = _shift_by_span(al, 3, np.nan, np.float64)
    al_t4 = _shift_by_span(al, 4, np.nan, np.float64)
    zt_t1 = _shift_by_span(iszt, 1, 0, np.int8) == 1
    zt_t2 = _shift_by_span(iszt, 2, 0, np.int8) == 1
    zt_t3 = _shift_by_span(iszt, 3, 0, np.int8) == 1
    zt_t4 = _shift_by_span(iszt, 4, 0, np.int8) == 1
    clv_t2 = _shift_by_span(clv_a, 2)
    clv_t3 = _shift_by_span(clv_a, 3)
    clv_t4 = _shift_by_span(clv_a, 4)

    zt_cnt_20_t1 = np.zeros(n_rows, dtype=np.float32)
    zt_cnt_60_t1 = np.zeros(n_rows, dtype=np.float32)
    for s, e in zip(starts, ends):
        m = e - s
        if m <= 1:
            continue
        cs = np.concatenate(([0], np.cumsum(iszt[s:e], dtype=np.int32)))
        pos = np.arange(m)
        zt_cnt_20_t1[s:e] = (cs[pos] - cs[np.maximum(0, pos - 20)]).astype(np.float32)
        zt_cnt_60_t1[s:e] = (cs[pos] - cs[np.maximum(0, pos - 60)]).astype(np.float32)

    with np.errstate(divide="ignore", invalid="ignore"):
        ret3_t1 = np.where(ac_t4 > 0, (ac_t1 / ac_t4 - 1.0) * 100.0, np.nan)
        ret3_t2 = np.where(ac_t5 > 0, (ac_t2 / ac_t5 - 1.0) * 100.0, np.nan)
        d1_body_t1 = np.where(open_t1 > 0, (close_t1 / open_t1 - 1.0) * 100.0, np.nan)
        d1_upper_shad_t1 = np.where(
            (high_t1 - low_t1) > 1e-6,
            (high_t1 - np.maximum(open_t1, close_t1)) / (high_t1 - low_t1),
            0.0,
        )
        d1_broken_dd_t1 = np.where(high_t1 > 0, (close_t1 / high_t1 - 1.0) * 100.0, np.nan)
        yin_vol_ratio = np.where(amt_t2 > 0, amt_yi_t1 / amt_t2, np.nan)

    prev_zt_mask = (prev_st >= 1) & (is_st == 0) & (list_age_a > 10)
    tmp_p = pd.DataFrame({
        "dt_i": dt_arr[prev_zt_mask],
        "ind": csrc_ind_a[prev_zt_mask],
        "op": opct[prev_zt_mask],
    })
    mkt20_pzt_stats = tmp_p.groupby("dt_i")["op"].agg(["count", "mean"])
    mkt20_pzt_n_map = mkt20_pzt_stats["count"].to_dict()
    mkt20_pzt_op_map = mkt20_pzt_stats["mean"].to_dict()
    ind20_pzt_stats = tmp_p.groupby(["dt_i", "ind"])["op"].agg(["count", "mean"])
    ind20_pzt_n_map = ind20_pzt_stats["count"].to_dict()
    ind20_pzt_op_map = ind20_pzt_stats["mean"].to_dict()
    del tmp_p

    yizi_buy = (
        (isyz_zt == 1)
        | (opct >= 19.5)
        | (isyz_dt == 1)
        | (open_raw <= 0.0)
        | (amt_yi <= 0.0)
    )
    clean = (
        (list_age_a > 10)
        & (is_st == 0)
        & (tox_pre == 0)
        & (amt_yi_t1 >= 1.0)
        & (close_t1 >= 2.0)
        & (~yizi_buy)
        & (np.abs(ret_1d_t1_a) <= 22.0)
    )

    m_A = clean & (
        ((prev_st == 1) & (opct >= -1.0) & (opct < 19.5))
        | ((prev_st == 2) & (opct >= -5.0) & (opct < 19.5))
    )

    yin_t1 = (close_t1 < open_t1)
    yin_t2 = (close_t2 < open_t2)
    surge_3d_first_break = (streak_t2 < 2) & (ret3_t2 >= 40.0) & (~yin_t2) & (ret_1d_t2 > 0.0)
    m_B = clean & (prev_st == 0) & ((streak_t2 >= 2) | surge_3d_first_break) & yin_t1 & (opct >= -10.0) & (opct <= 3.0)

    c1 = (~zt_t1) & zt_t2 & (al_t1 >= al_t2) & (amt_yi_t1 < amt_t2) & (amt_t2 >= 1.0)
    c2 = (~zt_t1) & (~zt_t2) & zt_t3 & (np.minimum(al_t1, al_t2) >= al_t3) & (0.5 * (amt_yi_t1 + amt_t2) < amt_t3) & (amt_t3 >= 1.0)
    c3 = (~zt_t1) & (~zt_t2) & (~zt_t3) & zt_t4 & (np.minimum(np.minimum(al_t1, al_t2), al_t3) >= al_t4) & ((amt_yi_t1 + amt_t2 + amt_t3) / 3.0 < amt_t4) & (amt_t4 >= 1.0)
    m_C = clean & (prev_st == 0) & (c1 | c2 | c3) & (opct >= -3.0) & (opct <= 8.0)

    m_D = clean & (prev_bk == 1) & (prev_st == 0) & (opct >= -12.0) & (opct <= -2.0)
    m_E = clean & (prev_st == 1) & (prev_yz == 0) & (opct >= -1.0) & (opct <= 8.0)

    pb_days = np.where(c1, 1.0, np.where(c2, 2.0, np.where(c3, 3.0, np.nan)))
    amt_zt = np.where(c1, amt_t2, np.where(c2, amt_t3, np.where(c3, amt_t4, np.nan)))
    amt_pb_mean = np.where(c1, amt_yi_t1, np.where(c2, 0.5 * (amt_yi_t1 + amt_t2), np.where(c3, (amt_yi_t1 + amt_t2 + amt_t3) / 3.0, np.nan)))
    al_zt = np.where(c1, al_t2, np.where(c2, al_t3, np.where(c3, al_t4, np.nan)))
    ac_zt = np.where(c1, ac_t2, np.where(c2, ac_t3, np.where(c3, ac_t4, np.nan)))
    zt_orig_st = np.where(c1, streak_t2, np.where(c2, streak_t3, np.where(c3, streak_t4, np.nan)))
    zt_orig_clv = np.where(c1, clv_t2, np.where(c2, clv_t3, np.where(c3, clv_t4, np.nan)))
    with np.errstate(divide="ignore", invalid="ignore"):
        pb_vol_shrink = np.where(amt_zt > 0, amt_pb_mean / amt_zt, np.nan)
        pb_price_retrace = np.where((ac_zt - al_zt) > 1e-6, (ac_t1 - al_zt) / (ac_zt - al_zt), np.nan)
        pb_ret_cum = np.where(ac_zt > 0, (ac_t1 / ac_zt - 1.0) * 100.0, np.nan)
        open_vs_zt_close = np.where(ac_zt > 0, (ao / ac_zt - 1.0) * 100.0, np.nan)

    union_mask = m_A | m_B | m_C | m_D | m_E
    cand_indices = np.where(union_mask)[0]

    s82_mask = clean & (prev_st == 1) & (prev_yz == 0) & (opct >= -10.0) & (opct <= -3.0)
    assert not np.any(union_mask & s82_mask), "S82 overlap detected!"

    rows = []
    for idx in cand_indices:
        ex = _sim_exit_modes_at_idx(
            int(idx), int(span_start_arr[idx]), int(span_end_arr[idx]),
            ao, ah, ac, adjf, close_raw, opct, clv_a, iszt, isdt, isyz_dt,
            amt_yi, lhb_inst_t1, dt_arr, dt_cats, mkt_dt20_t1, mkt_dt10_t1,
            modes=("h1", "h2", "v11"),
        )
        if not ex:
            continue
        di = int(dt_arr[idx])
        ci = int(c6_arr[idx])
        ind_id = int(csrc_ind_a[idx])
        p_n = mkt20_pzt_n_map.get(di, 0)
        p_mean = mkt20_pzt_op_map.get(di, np.nan)
        if prev_st[idx] >= 1 and p_n > 1 and np.isfinite(p_mean):
            p_mean_ex = (p_mean * p_n - float(opct[idx])) / (p_n - 1)
            p_n_ex = p_n - 1
        elif prev_st[idx] >= 1 and p_n == 1:
            p_mean_ex, p_n_ex = np.nan, 0
        else:
            p_mean_ex, p_n_ex = p_mean, p_n

        ip_n = ind20_pzt_n_map.get((di, ind_id), 0)
        ip_mean = ind20_pzt_op_map.get((di, ind_id), np.nan)
        if prev_st[idx] >= 1 and ip_n > 1 and np.isfinite(ip_mean):
            ip_mean_ex = (ip_mean * ip_n - float(opct[idx])) / (ip_n - 1)
            ip_n_ex = ip_n - 1
        elif prev_st[idx] >= 1 and ip_n == 1:
            ip_mean_ex, ip_n_ex = np.nan, 0
        else:
            ip_mean_ex, ip_n_ex = ip_mean, ip_n

        rec = {
            "buy_date": str(dt_cats[di]),
            "code": str(c6_cats[ci]).zfill(6),
            "buy_hhmm": 925,
            "is_yizi": False,
            "can_buy": True,
            "sim_ok": True,
            "track_A": int(m_A[idx]),
            "track_B": int(m_B[idx]),
            "track_B_s2": int(m_B[idx] and streak_t2[idx] >= 2),
            "track_C": int(m_C[idx]),
            "track_D": int(m_D[idx]),
            "track_E": int(m_E[idx]),
            "eng_d1_body_t1": float(d1_body_t1[idx]),
            "eng_d1_upper_shad_t1": float(d1_upper_shad_t1[idx]),
            "eng_d1_broken_dd_t1": float(d1_broken_dd_t1[idx]),
            "eng_ret_3d_t1": float(ret3_t1[idx]),
            "eng_zt_cnt_20d_t1": float(zt_cnt_20_t1[idx]),
            "eng_zt_cnt_60d_t1": float(zt_cnt_60_t1[idx]),
            "eng_turn_pct_t1": float(turn_t1[idx]),
            "eng_rel_open_vs_mkt": float(opct[idx] - mkt_gap_map.get(di, 0.0)),
            "eng_mkt10_zt_est_t1": float(mkt_zt_est_map.get(di, np.nan)),
            "eng_csrc20_zt_cnt_t1": float(ip_n_ex),
            "eng_csrc20_open_mean": float(ip_mean_ex),
            "eng_mkt20_prevzt_open_mean": float(p_mean_ex),
            "eng_mkt20_prevzt_n": float(p_n_ex),
            "eng_is_monday": float(mkt_wd_map.get(di, 0) == 1),
            "eng_is_2to3": float(prev_st[idx] == 2),
            "eng_streak_t2": float(streak_t2[idx]),
            "eng_surge_ret3_pre": float(ret3_t2[idx]),
            "eng_yin_vol_ratio": float(yin_vol_ratio[idx]),
            "eng_pb_days": float(pb_days[idx]),
            "eng_pb_vol_shrink": float(pb_vol_shrink[idx]),
            "eng_pb_price_retrace": float(pb_price_retrace[idx]),
            "eng_pb_ret_cum": float(pb_ret_cum[idx]),
            "eng_open_vs_zt_close": float(open_vs_zt_close[idx]),
            "eng_zt_orig_streak": float(zt_orig_st[idx]),
            "eng_zt_orig_clv": float(zt_orig_clv[idx]),
            "eng_zt_orig_amt": float(amt_zt[idx]),
        }
        for mname in ("h1", "h2", "v11"):
            if mname in ex:
                e_dt, eh, gr, hb, rsn, seg_j = ex[mname]
                rec[f"{mname}_exit_date"] = e_dt
                rec[f"{mname}_exit_hhmm"] = int(eh)
                rec[f"{mname}_gross_ret"] = float(gr)
                rec[f"{mname}_net_ret"] = (1.0 + float(gr)) * (1.0 - 0.0030) - 1.0
                rec[f"{mname}_hold_bars"] = int(hb)
                rec[f"{mname}_exit_reason"] = rsn
                rec[f"{mname}_mtm_json"] = seg_j
            else:
                rec[f"{mname}_exit_date"] = ""
                rec[f"{mname}_exit_hhmm"] = 1500
                rec[f"{mname}_gross_ret"] = np.nan
                rec[f"{mname}_net_ret"] = np.nan
                rec[f"{mname}_hold_bars"] = np.nan
                rec[f"{mname}_exit_reason"] = ""
                rec[f"{mname}_mtm_json"] = "[]"
        rows.append(rec)

    cand_df = pd.DataFrame(rows)
    cand_dts = sorted(cand_df["buy_date"].unique().tolist())
    cand_pair_set = set(zip(cand_df["buy_date"], cand_df["code"]))

    # Free ALL Phase 1 arrays BEFORE Phase 2 row-group extraction
    del ao, ah, al, ac, adjf, close_raw, open_raw, high_raw, low_raw, opct, clv_a
    del iszt, isdt, isyz_zt, isyz_dt, is_st, list_age_a, amt_yi, amt_yi_t1, ret_1d_t1_a
    del prev_st, prev_bk, prev_yz, tox_pre, lhb_inst_t1, csrc_ind_a
    del streak_a, ret_1d_a, turn_a, c6_arr, dt_arr, brk, starts, ends, span_start_arr, span_end_arr
    del close_t1, open_t1, high_t1, low_t1, turn_t1, ret_1d_t2, close_t2, open_t2
    del amt_t2, amt_t3, amt_t4, streak_t2, streak_t3, streak_t4
    del ac_t1, ac_t2, ac_t3, ac_t4, ac_t5, al_t1, al_t2, al_t3, al_t4, zt_t1, zt_t2, zt_t3, zt_t4
    del clv_t2, clv_t3, clv_t4, zt_cnt_20_t1, zt_cnt_60_t1
    del ret3_t1, ret3_t2, d1_body_t1, d1_upper_shad_t1, d1_broken_dd_t1, yin_vol_ratio
    gc.collect()
    pa.default_memory_pool().release_unused()

    # Phase 2: Read row-group by row-group via ParquetFile in 22-col chunks, take() ONLY matching rows (< 100 MB RAM!)
    pf = pq.ParquetFile(CORE_PQ)
    col_chunks = [CORE_PIT_FEATURE_COLS[i : i + 22] for i in range(0, len(CORE_PIT_FEATURE_COLS), 22)]
    p2_chunks = []
    for rg in range(pf.num_row_groups):
        key_tbl = pf.read_row_group(rg, columns=["is_20cm", "dt", "c6"])
        is20_col = key_tbl.column("is_20cm").to_numpy()
        dt_col = key_tbl.column("dt").to_pandas().astype(str).to_numpy()
        c6_col = key_tbl.column("c6").to_pandas().astype(str).str.zfill(6).to_numpy()
        del key_tbl
        local_idx = [
            i for i in range(len(is20_col))
            if is20_col[i] == 1 and dt_col[i] <= end_cutoff and (dt_col[i], c6_col[i]) in cand_pair_set
        ]
        if local_idx:
            idx_arr = pa.array(local_idx, type=pa.int32())
            parts = []
            for c_sub in col_chunks:
                sub_tbl = pf.read_row_group(rg, columns=c_sub).take(idx_arr)
                parts.append(sub_tbl.to_pandas(self_destruct=True))
                del sub_tbl
                pa.default_memory_pool().release_unused()
            sub_b = pd.concat(parts, axis=1)
            sub_b["buy_date"] = dt_col[local_idx]
            sub_b["code"] = c6_col[local_idx]
            p2_chunks.append(sub_b)
        del is20_col, dt_col, c6_col
        gc.collect()
        pa.default_memory_pool().release_unused()

    df_p2 = pd.concat(p2_chunks, ignore_index=True) if p2_chunks else pd.DataFrame()
    del p2_chunks, pf
    gc.collect()
    pa.default_memory_pool().release_unused()

    for sc_col in ("d1_first_seal_hhmm_t1", "d1_open_board_cnt_t1", "waves_3y_g15_t1", "max_streak_3y", "trap_waves_3y", "kpl_unique_plates_3y"):
        if sc_col in df_p2.columns:
            arr = pd.to_numeric(df_p2[sc_col], errors="coerce").to_numpy(np.float32)
            df_p2[sc_col] = np.where(arr < 0, np.nan, arr)
    for cool_c in ("cool_days_since_last_zt", "cool_days_since_last_2b"):
        if cool_c in df_p2.columns:
            arr = pd.to_numeric(df_p2[cool_c], errors="coerce").to_numpy(np.float32)
            df_p2[cool_c] = np.where(arr < 0, 9999.0, arr)

    cand_df = cand_df.merge(df_p2, on=["buy_date", "code"], how="left")
    del df_p2
    gc.collect()
    pa.default_memory_pool().release_unused()

    # Compute post-merge engineered features cleanly on the 12k-row candidate table
    cand_df["eng_d1_amt_to_mcap"] = np.where(cand_df["mcap_yi_t1"] > 0, cand_df["amount_yi_t1"] / cand_df["mcap_yi_t1"], np.nan)
    cand_df["eng_min_hr_space_t1"] = np.minimum(cand_df["hr10d_space_t1"], cand_df["hr30d_space_t1"])
    cand_df["eng_open_minus_d1_open"] = cand_df["open_pct"] - cand_df["d1_open_pct"]

    mkt_cols = [c for c in mkt_all.columns if c not in ("trade_date", "dt_i")]
    mkt_sub = mkt_all[mkt_all["trade_date"].isin(cand_dts)].drop(columns=["dt_i"]).rename(columns={"trade_date": "buy_date"})
    cand_df = cand_df.merge(mkt_sub, on="buy_date", how="left")

    all_feat_cols = list(dict.fromkeys(CORE_PIT_FEATURE_COLS + ENG_COMMON_COLS + mkt_cols))
    meta = {
        "end_cutoff": end_cutoff,
        "n_union_cands": int(len(cand_df)),
        "track_counts": {k: int(cand_df[k].sum()) for k in ("track_A", "track_B", "track_B_s2", "track_C", "track_D", "track_E")},
        "n_features_total": len(all_feat_cols),
        "elapsed_sec": round(time.time() - t0, 2),
        "peak_rss_mb": get_rss_mb(),
    }
    return cand_df, all_feat_cols, meta


def prepare_track_df(
    master_df: pd.DataFrame,
    track_mask: pd.Series | np.ndarray,
    exit_mode: str = "v11",
    end_dt: str = "2026-11-16",
    all_feat_cols: Optional[list[str]] = None,
) -> tuple[pd.DataFrame, list[str]]:
    """Extract a specific track + exit_mode ready for wf_scorecard_engine, filtering valid exit_date <= end_dt."""
    sub = master_df[np.asarray(track_mask, dtype=bool)].copy()
    sub["exit_date"] = sub[f"{exit_mode}_exit_date"].astype(str)
    sub["exit_hhmm"] = pd.to_numeric(sub[f"{exit_mode}_exit_hhmm"], errors="coerce").fillna(1500).astype(int)
    sub["gross_ret"] = pd.to_numeric(sub[f"{exit_mode}_gross_ret"], errors="coerce").astype(float)
    sub["net_ret"] = pd.to_numeric(sub[f"{exit_mode}_net_ret"], errors="coerce").astype(float)
    sub["hold_bars"] = pd.to_numeric(sub[f"{exit_mode}_hold_bars"], errors="coerce").astype(float)
    sub["exit_reason"] = sub[f"{exit_mode}_exit_reason"].astype(str)
    sub["mtm_json"] = sub[f"{exit_mode}_mtm_json"].astype(str)
    sub = sub[(sub["buy_date"] <= end_dt) & (sub["exit_date"] <= end_dt) & (sub["exit_date"] > sub["buy_date"]) & sub["net_ret"].notna()].copy()
    sub = sub.sort_values(["buy_date", "code"]).reset_index(drop=True)

    feat_cols = all_feat_cols or []
    valid_feats = []
    for c in feat_cols:
        if c in sub.columns:
            s = pd.to_numeric(sub[c], errors="coerce")
            if s.notna().mean() >= 0.50 and s.nunique(dropna=True) >= 2:
                valid_feats.append(c)
    return sub, valid_feats


def attach_aligned_mtm(df: pd.DataFrame, cal_dts: list[str], mtm_col: str = "mtm_segs") -> pd.DataFrame:
    """Convert JSON date-pair MTM segments to integer indices aligned to `cal_dts`."""
    dt_idx = {d: i for i, d in enumerate(cal_dts)}
    segs_out = []
    for js in df["mtm_json"]:
        pairs = json.loads(js) if js else []
        segs_out.append(tuple((dt_idx[d], float(m)) for d, m in pairs if d in dt_idx))
    out = df.copy()
    out[mtm_col] = segs_out
    return out


def compute_v20_corr_and_26h2(
    slot_df: pd.DataFrame,
    v20_ctx: dict,
    wf_start_dt: str,
    end_dt: str = "2026-11-16",
    mtm_col: str = "mtm_segs",
) -> dict:
    """Compute exact daily MTM correlation with V20.0 baseline AND 2026H2 window metrics."""
    cal_df = v20_ctx["calendar_5y"] if end_dt <= "2026-11-16" else v20_ctx["calendar_ext"]
    cw = cal_df[cal_df["trade_date"].between(wf_start_dt, end_dt)].sort_values("trade_date").reset_index(drop=True)
    cal_dts = cw["trade_date"].tolist()
    dt_idx = {d: i for i, d in enumerate(cal_dts)}
    v20_dr = cw["v20_daily_ret"].fillna(0.0).to_numpy(float)

    s_aligned = attach_aligned_mtm(slot_df, cal_dts, mtm_col=mtm_col) if not slot_df.empty else slot_df
    dr_full, mtm_diff = wfm.build_daily_mtm_returns(s_aligned, cal_dts, mtm_col=mtm_col)

    corr_full = float(np.corrcoef(dr_full, v20_dr)[0, 1]) if (np.std(dr_full) > 1e-12 and np.std(v20_dr) > 1e-12) else 0.0
    both_act = (np.abs(dr_full) > 1e-12) & (np.abs(v20_dr) > 1e-12)
    either_act = (np.abs(dr_full) > 1e-12) | (np.abs(v20_dr) > 1e-12)
    corr_either = float(np.corrcoef(dr_full[either_act], v20_dr[either_act])[0, 1]) if (either_act.sum() >= 10 and np.std(dr_full[either_act]) > 1e-12 and np.std(v20_dr[either_act]) > 1e-12) else 0.0
    corr_both = float(np.corrcoef(dr_full[both_act], v20_dr[both_act])[0, 1]) if (both_act.sum() >= 10 and np.std(dr_full[both_act]) > 1e-12 and np.std(v20_dr[both_act]) > 1e-12) else 0.0

    empty_mask = cw["v20_empty_strict_no_stier_wait"].to_numpy(bool)
    empty_active_days = int(np.sum((np.abs(dr_full) > 1e-12) & empty_mask))

    h2_cal = [d for d in cal_dts if d >= "2026-07-01"]
    csi_arr = cw["csi300_daily_ret"].to_numpy(float)
    ew_arr = cw["alla_ew_daily_ret"].to_numpy(float)
    h2_metrics = wfm._calc_one_window(
        s_aligned, None, dr_full, cal_dts, dt_idx, csi_arr, ew_arr, "2026-07-01", end_dt
    ) if h2_cal else {"n": 0, "nav": 1.0}

    return {
        "mtm_reconciliation_diff": round(float(mtm_diff), 8),
        "corr_v20_daily_mtm": round(corr_full, 4),
        "corr_v20_either_active": round(corr_either, 4),
        "corr_v20_both_active": round(corr_both, 4),
        "n_days_both_active": int(both_act.sum()),
        "n_days_empty_covered": empty_active_days,
        "y2026h2": h2_metrics,
    }


def evaluate_track_full(
    track_id: str,
    track_group: str,
    sub_df: pd.DataFrame,
    feat_cols: list[str],
    v20_ctx: dict,
    wf_start_date: str = "2023-01-03",
    end_dt: str = "2026-11-16",
    thresholds: tuple = ("all_cands", "top30", "top20", "top10", "top5", 70, 75, 80, 85),
    perm_n: int = 1000,
    top_k: int = 12,
    min_k: int = 5,
    recalc_freq: str = "daily",
) -> tuple[list[dict], dict, pd.DataFrame]:
    """
    Run Mode A (0..100 causal WF scorecard) on a track and evaluate every threshold across:
      - Standalone single-slot (2023-2026 WF, 2025-2026, 2026, 26H2, ex-top5, MDD, excess CSI300, V20 corr, 1000x perm)
      - V20.0 Empty-Slot Patch (`simulate_v20_empty_slot_patch`: strict combined no-peek + empty-slot standalone)
    """
    t0 = time.time()
    df_h = wfm.prepare_hygiene_and_net_ret(sub_df, fee_rt=0.0030, gross_ret_col="gross_ret")
    scored_df, core_meta = wfc.run_expanding_scorecard_loop(
        df_h,
        feature_cols=feat_cols,
        mode="scorecard_0_100",
        wf_start_date=wf_start_date,
        min_warmup_trades=80,
        min_warmup_trades_rare=60,
        min_warmup_months=18,
        recalc_freq=recalc_freq,
        top_k=top_k,
        min_k=min_k,
        max_corr=0.65,
        min_t_stat=1.0,
        shrink_tau=20.0,
        save_snapshot_freq="monthly",
    )

    actual_wf_start = core_meta["wf_actual_start"] or wf_start_date
    cal_df = v20_ctx["calendar_5y"]
    cal_win = cal_df[cal_df["trade_date"].between(actual_wf_start, end_dt)].sort_values("trade_date").reset_index(drop=True)
    cal_dts = cal_win["trade_date"].tolist()

    scored_aligned = attach_aligned_mtm(scored_df, cal_dts, mtm_col="mtm_segs")
    wf_cands = scored_aligned[scored_aligned["wf_in_window"]].copy()
    bench_df = v20_ctx["bench"]

    thr_map = {
        "all_cands": None,
        "top30": "wf_thr_top30",
        "top20": "wf_thr_top20",
        "top10": "wf_thr_top10",
        "top5": "wf_thr_top5",
    }

    rows = []
    details = {}
    for th in thresholds:
        tname = str(th) if not isinstance(th, (int, float)) else f"abs_{int(th)}"
        t_arg = thr_map[th] if th in thr_map else float(th)
        pass_df, slot_df = wfm.select_single_slot_trades(
            scored_aligned, score_col="wf_score", threshold=t_arg, wf_only=True
        )
        ev = wfm.evaluate_wf_ledger(
            slot_df, pass_df, wf_cands, bench_df,
            wf_start_dt=actual_wf_start, end_dt=end_dt,
            mtm_col="mtm_segs", perm_n=perm_n, seed=20261125,
        )
        corr_h2 = compute_v20_corr_and_26h2(slot_df, v20_ctx, wf_start_dt=actual_wf_start, end_dt=end_dt)

        patch_res = None
        if not pass_df.empty and th != "all_cands":
            patch_res = wfp.simulate_v20_empty_slot_patch(
                pass_df, v20_ctx=v20_ctx, wf_start_dt=actual_wf_start, end_dt=end_dt,
                score_col="wf_score", patch_mtm_col="mtm_segs",
            )

        fw = ev["windows"].get("FULL_WF", {})
        y23 = ev["windows"].get("Y2023", {})
        y24 = ev["windows"].get("Y2024", {})
        y25 = ev["windows"].get("Y2025", {})
        y2526 = ev["windows"].get("Y2025_2026", {})
        y26 = ev["windows"].get("Y2026", {})
        h2 = corr_h2["y2026h2"]
        pm = ev["permutation_1000"]

        row = {
            "track_id": track_id,
            "track_group": track_group,
            "threshold": tname,
            "wf_actual_start": actual_wf_start,
            "n_cands_total": int(len(df_h)),
            "n_cands_wf": int(len(wf_cands)),
            "n_pass": int(len(pass_df)),
            "n_trades": fw.get("n", 0),
            "wr_pct": fw.get("wr_pct", 0.0),
            "plr": fw.get("plr", 0.0),
            "mean_pct": fw.get("mean_pct", 0.0),
            "nav_wf": fw.get("nav", 1.0),
            "eq_nav_wf": fw.get("eq_nav", 1.0),
            "ex3_wf": fw.get("ex_top3_nav", 1.0),
            "ex5_wf": fw.get("ex_top5_nav", 1.0),
            "mdd_pct": fw.get("daily_mdd_pct", 0.0),
            "sharpe": fw.get("daily_sharpe", 0.0),
            "calmar": fw.get("daily_calmar", 0.0),
            "excess_csi300_pp": fw.get("excess_csi300_pp", 0.0),
            "excess_ew_pp": fw.get("excess_alla_ew_pp", 0.0),
            "nav_y23": y23.get("nav", 1.0),
            "nav_y24": y24.get("nav", 1.0),
            "nav_y25": y25.get("nav", 1.0),
            "n_2526": y2526.get("n", 0),
            "wr_2526": y2526.get("wr_pct", 0.0),
            "nav_2526": y2526.get("nav", 1.0),
            "ex5_2526": y2526.get("ex_top5_nav", 1.0),
            "mdd_2526": y2526.get("daily_mdd_pct", 0.0),
            "n_y26": y26.get("n", 0),
            "wr_y26": y26.get("wr_pct", 0.0),
            "nav_y26": y26.get("nav", 1.0),
            "n_26h2": h2.get("n", 0),
            "wr_26h2": h2.get("wr_pct", 0.0),
            "nav_26h2": h2.get("nav", 1.0),
            "mdd_26h2": h2.get("daily_mdd_pct", 0.0),
            "corr_v20_daily_mtm": corr_h2["corr_v20_daily_mtm"],
            "corr_v20_either_active": corr_h2["corr_v20_either_active"],
            "n_days_empty_covered": corr_h2["n_days_empty_covered"],
            "perm_sd_p": pm.get("same_day_p_nav", 1.0),
            "perm_any_p": pm.get("any_cand_day_p_nav", 1.0),
            "mtm_diff": corr_h2["mtm_reconciliation_diff"],
        }
        if patch_res is not None:
            m1c = patch_res["mode1_strict_combined_no_peek"]
            m2e = patch_res["mode2_empty_slot_standalone"]
            cfw = m1c["combined_with_patch"]["FULL_WF"]
            bfw = m1c["v20_baseline"]["FULL_WF"]
            c2526 = m1c["combined_with_patch"]["Y2025_2026"]
            b2526 = m1c["v20_baseline"]["Y2025_2026"]
            c26 = m1c["combined_with_patch"]["Y2026"]
            b26 = m1c["v20_baseline"]["Y2026"]
            efw = m2e["windows"]["FULL_WF"]
            e2526 = m2e["windows"]["Y2025_2026"]
            e26 = m2e["windows"]["Y2026"]
            row.update({
                "patch_n_added": m1c["n_patch_added"],
                "patch_n_v20_skipped": m1c["n_v20_skipped_by_collision"],
                "patch_skipped_v20_prod": m1c["skipped_v20_net_ret_prod"],
                "patch_comb_nav_wf": cfw["nav"],
                "patch_v20_nav_wf": bfw["nav"],
                "patch_delta_nav_ratio": m1c["delta_nav_ratio_full_wf"],
                "patch_comb_mdd": cfw["daily_mdd_pct"],
                "patch_delta_mdd_pp": m1c["delta_mdd_pp_full_wf"],
                "patch_comb_sharpe": cfw["daily_sharpe"],
                "patch_delta_sharpe": m1c["delta_sharpe_full_wf"],
                "patch_comb_2526_ratio": round(c2526["nav"] / max(1e-9, b2526["nav"]), 4),
                "patch_comb_26_ratio": round(c26["nav"] / max(1e-9, b26["nav"]), 4),
                "empty_only_n": m2e["n_standalone_empty_trades"],
                "empty_only_wr": efw.get("wr_pct", 0.0),
                "empty_only_nav_wf": efw.get("nav", 1.0),
                "empty_only_ex5_wf": efw.get("ex_top5_nav", 1.0),
                "empty_only_mdd": efw.get("daily_mdd_pct", 0.0),
                "empty_only_nav_2526": e2526.get("nav", 1.0),
                "empty_only_nav_y26": e26.get("nav", 1.0),
                "empty_collision_pct": m2e["collision_rate_pct"],
            })
        rows.append(row)
        details[tname] = {
            "summary_row": row,
            "eval_ledger": ev,
            "corr_and_26h2": corr_h2,
            "v20_empty_patch": patch_res,
        }

    meta_out = {
        "track_id": track_id,
        "track_group": track_group,
        "elapsed_sec": round(time.time() - t0, 2),
        "wf_actual_start": actual_wf_start,
        "n_rebuilds": core_meta["n_rebuilds"],
        "n_features_used": len(feat_cols),
        "latest_scorecard": core_meta["latest_scorecard"],
        "snapshots_count": len(core_meta["snapshots"]),
    }
    return rows, {"meta": meta_out, "thresholds": details}, scored_aligned

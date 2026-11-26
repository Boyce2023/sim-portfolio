#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD041 Step 1: Build 5-Year Non-Yizi First-Board Touch Universe (100% Sealed + Broken Denominator)
+ Strictly PIT Pre-Open & Intraday News/Theme Catalysts + Exact Forward Exits & Daily MTM Segments.

Zero yfinance (D12). Zero cap10m. Threads <= 1. Peak RSS < 1.2 GB.
Strict Anti-Leakage:
  - Hard exclude is_yizi_zt == 1 and open >= zt_px_raw * 0.998 (and open_pct >= lim*100 - 0.25).
  - 100% include hit_zt == 1 & is_zt == 0 (broken first boards) in pool denominator.
  - All candidate scoring features strictly <= T-1 close or <= T 09:25 auction / pre-open news.
  - zt_micro_tape columns prefixed with `audit_only_` and NEVER used in WF feature lists.
"""
import os
for _env_k in (
    "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS",
):
    os.environ[_env_k] = "1"

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
OUT_DIR = f"{SIM_DIR}/backtests_astock2/rd041_day0_firstboard_sweep_20261126"
CACHE_DIR = f"{OUT_DIR}/_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

STOCK_DAY_PQ = f"{BASE_DIR}/stock_day_core_features_pit.parquet"
MKT_DAY_PQ = f"{BASE_DIR}/market_daily_all_new_factors_pit.parquet"
BENCH_PQ = f"{BASE_DIR}/v20_daily_bench_20210104_20261125.parquet"

END_BUY_DATE = "2026-11-16"
END_BAR_DATE = "2026-11-25"


def peak_rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 2)


def _read_cols_numpy(cols: list[str]) -> tuple[dict[str, np.ndarray], np.ndarray, np.ndarray]:
    """Stream Parquet row groups directly into preallocated compact numpy arrays (< 500 MB RSS)."""
    pf = pq.ParquetFile(STOCK_DAY_PQ)
    n_tot = pf.metadata.num_rows
    schema = pf.schema_arrow

    # Read categorical dt and c6 first cleanly
    meta = pd.read_parquet(STOCK_DAY_PQ, columns=["dt", "c6"])
    dt_cats = np.array([str(x)[:10] for x in meta["dt"].cat.categories], dtype=object)
    c6_cats = np.array([str(x).zfill(6) for x in meta["c6"].cat.categories], dtype=object)
    dt_id = meta["dt"].cat.codes.to_numpy(np.int16)
    c6_id = meta["c6"].cat.codes.to_numpy(np.int32)
    del meta
    pa.default_memory_pool().release_unused()
    gc.collect()

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
            out[c][pos : pos + m] = tbl.column(c).to_numpy(zero_copy_only=False)
        pos += m
        del tbl
        if rg % 10 == 0:
            pa.default_memory_pool().release_unused()
    pa.default_memory_pool().release_unused()
    return out, dt_cats, c6_cats


def build_pit_name_map(end_cutoff: str = END_BAR_DATE) -> dict[str, str]:
    """Build unambiguous sec_name -> c6 map strictly from local PIT DBs."""
    pairs = []
    for db, sql in [
        (f"{DATA_DIR}/cninfo_notices_5y_pit.db", "SELECT DISTINCT sec_code, sec_name FROM notices WHERE substr(pub_datetime_cst,1,10) <= ?"),
        (f"{SIM_DIR}/backtests_astock2/data_5y/cninfo_ir_qa_5y_pit.db", "SELECT DISTINCT sec_code, sec_name FROM ir_qa WHERE substr(pub_datetime_cst,1,10) <= ?"),
        (f"{DATA_DIR}/zt_micro_tape_5y_pit.db", "SELECT DISTINCT sec_code, sec_name FROM zt_micro_tape WHERE trade_date <= ?"),
    ]:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        pairs.append(pd.read_sql_query(sql, con, params=(end_cutoff,)))
        con.close()

    csrc = pd.read_csv(f"{DATA_DIR}/csrc_industry_pit_clean.csv", usecols=["code", "code_name", "start_date"])
    csrc = csrc[csrc["start_date"].astype(str).str[:10] <= end_cutoff].copy()
    csrc["sec_code"] = csrc["code"].astype(str).str[-6:]
    csrc["sec_name"] = csrc["code_name"].astype(str)
    pairs.append(csrc[["sec_code", "sec_name"]])

    df = pd.concat(pairs, ignore_index=True).dropna()
    df["c6"] = df["sec_code"].astype(str).str.zfill(6)
    df = df[df["c6"].str.startswith(("00", "60", "30", "688", "689"))].copy()
    df["clean_name"] = (
        df["sec_name"]
        .astype(str)
        .str.strip()
        .str.replace(r"^\*?ST", "", regex=True)
        .str.replace("Ａ", "A", regex=False)
        .str.replace(" ", "", regex=False)
    )
    cnt = df.groupby("clean_name")["c6"].nunique()
    uniq = df[df["clean_name"].isin(cnt[cnt == 1].index) & (df["clean_name"].str.len() >= 3)].drop_duplicates("clean_name")
    return dict(zip(uniq["clean_name"], uniq["c6"]))


def _calc_exits_and_mtm(
    pos: int, s: int, e: int,
    open_raw: np.ndarray, close_raw: np.ndarray, adj_f: np.ndarray,
    prev_close_raw: np.ndarray, is_zt: np.ndarray, is_dt: np.ndarray,
    is_yizi_dt: np.ndarray, is_20cm: np.ndarray, dt_list: np.ndarray,
    dt_id: np.ndarray, buy_px_adj: float,
) -> dict:
    """Compute exact 4 exits + DT deferrals + raw gross MTM segments [(dt_str, mult), ...]."""
    lim = 0.20 if is_20cm[pos] == 1 else 0.10
    day0_dt = str(dt_list[int(dt_id[pos])])
    ac_pos = float(close_raw[pos]) * float(adj_f[pos])
    m0 = ac_pos / buy_px_adj

    def _ac(idx: int) -> float:
        return float(close_raw[idx]) * float(adj_f[idx])

    def _ao(idx: int) -> float:
        return float(open_raw[idx]) * float(adj_f[idx])

    def _mtm_to_close(ex_pos: int) -> list[tuple[str, float]]:
        segs = [(day0_dt, m0)]
        for g in range(pos + 1, ex_pos + 1):
            g_dt = str(dt_list[int(dt_id[g])])
            segs.append((g_dt, _ac(g) / _ac(g - 1)))
        return segs

    def _mtm_to_open(ex_pos: int) -> list[tuple[str, float]]:
        segs = [(day0_dt, m0)]
        for g in range(pos + 1, ex_pos):
            g_dt = str(dt_list[int(dt_id[g])])
            segs.append((g_dt, _ac(g) / _ac(g - 1)))
        ex_dt = str(dt_list[int(dt_id[ex_pos])])
        segs.append((ex_dt, _ao(ex_pos) / _ac(ex_pos - 1)))
        return segs

    out = {}
    if pos + 1 >= e:
        return out

    # E1: T+1 Open (defer if sealed DT at open!)
    ex1 = pos + 1
    sold_at_open = False
    while ex1 < min(e, pos + 11):
        dt_px_ex = round(float(prev_close_raw[ex1]) * (1.0 - lim), 2)
        if is_yizi_dt[ex1] == 0 and float(open_raw[ex1]) > dt_px_ex + 0.005 and _ao(ex1) > 0:
            sold_at_open = True
            break
        if is_dt[ex1] == 0 and _ac(ex1) > 0:
            sold_at_open = False
            break
        ex1 += 1
    if ex1 < e:
        if sold_at_open and _ao(ex1) > 0:
            gr = _ao(ex1) / buy_px_adj - 1.0
            segs = _mtm_to_open(ex1)
            hhmm = 925
        elif is_dt[ex1] == 0 and _ac(ex1) > 0:
            gr = _ac(ex1) / buy_px_adj - 1.0
            segs = _mtm_to_close(ex1)
            hhmm = 1500
        else:
            gr, segs, hhmm, ex1 = np.nan, [], 1500, -1
        if ex1 > pos and np.isfinite(gr):
            out["E1_T1Open"] = (str(dt_list[int(dt_id[ex1])]), hhmm, gr, segs, ex1 - pos, not sold_at_open)

    # E2: T+1 Close
    ex2 = pos + 1
    while ex2 < min(e - 1, pos + 10) and is_dt[ex2] != 0:
        ex2 += 1
    if ex2 < e and is_dt[ex2] == 0 and _ac(ex2) > 0:
        out["E2_T1Close"] = (str(dt_list[int(dt_id[ex2])]), 1500, _ac(ex2) / buy_px_adj - 1.0, _mtm_to_close(ex2), ex2 - pos, False)

    # E3: T+2 Close
    if pos + 2 < e:
        ex3 = pos + 2
        while ex3 < min(e - 1, pos + 11) and is_dt[ex3] != 0:
            ex3 += 1
        if ex3 < e and is_dt[ex3] == 0 and _ac(ex3) > 0:
            out["E3_T2Close"] = (str(dt_list[int(dt_id[ex3])]), 1500, _ac(ex3) / buy_px_adj - 1.0, _mtm_to_close(ex3), ex3 - pos, False)

    # E4: Hold continuous limit-up until streak breaks (broken Day 0 -> E1_T1Open)
    if is_zt[pos] == 0:
        if "E1_T1Open" in out:
            out["E4_StreakHold"] = out["E1_T1Open"]
    else:
        ex4 = pos + 1
        while ex4 < min(e - 1, pos + 15) and is_zt[ex4] == 1:
            ex4 += 1
        while ex4 < min(e - 1, pos + 18) and is_dt[ex4] != 0:
            ex4 += 1
        if ex4 < e and is_dt[ex4] == 0 and _ac(ex4) > 0:
            out["E4_StreakHold"] = (str(dt_list[int(dt_id[ex4])]), 1500, _ac(ex4) / buy_px_adj - 1.0, _mtm_to_close(ex4), ex4 - pos, False)

    return out


def step1_extract_fb_universe() -> tuple[pd.DataFrame, dict, dict]:
    """Stream stock_day_core_features_pit.parquet into compact numpy arrays -> < 800 MB peak RSS."""
    t0 = time.time()
    num_cols = [
        "open", "close", "adj_factor", "prev_close_raw",
        "open_pct", "ret_1d", "is_zt", "hit_zt", "is_broken_zt", "is_yizi_zt",
        "is_dt", "is_yizi_dt", "prev_streak", "is_st_pit", "is_20cm", "amount_yi", "csrc_ind_id",
    ]
    arrs, dt_cats, c6_cats = _read_cols_numpy(num_cols)
    dt_id = arrs["dt_id"]
    c6_id = arrs["c6_id"]
    open_raw = arrs["open"]
    close_raw = arrs["close"]
    adj_f = arrs["adj_factor"]
    prev_cr = arrs["prev_close_raw"]
    open_pct = arrs["open_pct"]
    ret_1d = arrs["ret_1d"]
    is_zt = arrs["is_zt"]
    hit_zt = arrs["hit_zt"]
    is_broken = arrs["is_broken_zt"]
    is_yizi = arrs["is_yizi_zt"]
    is_dt = arrs["is_dt"]
    is_yizi_dt = arrs["is_yizi_dt"]
    prev_stk = arrs["prev_streak"]
    is_st = arrs["is_st_pit"]
    is_20 = arrs["is_20cm"]
    amt_yi = arrs["amount_yi"]
    ind_id = arrs["csrc_ind_id"]
    del arrs
    gc.collect()
    print(f"[Step1A] Arrays loaded in {time.time()-t0:.1f}s | RSS={peak_rss_mb()} MB")

    # Filter to <= END_BAR_DATE cleanly
    valid_bar_di = set(np.flatnonzero(dt_cats <= END_BAR_DATE))
    lim_pct = np.where(is_20 == 1, 20.0, 10.0).astype(np.float32)
    zt_px_raw = np.round(prev_cr * (1.0 + lim_pct / 100.0), 2).astype(np.float32)

    # 09:25 sector auction breadth & rank strictly from open_pct (vectorized, low RAM!)
    valid_open = (is_st == 0) & np.isfinite(open_pct) & (open_raw > 0) & (prev_cr > 0) & (open_pct >= 2.0)
    # Wait: compute industry gap3/gap5 from >=3.0, and rank across >=2.0 (or all non-yizi)!
    # To compute exact non-yizi rank within CSRC industry without 7M-row DF, keep only open_pct >= -1.0 (or compute over all valid_open using numpy!)
    # Actually keeping only open_pct >= 0.0 for rank is exact for any gap-up FB, and for green-open FB rank is simply bottom; wait: let's compute rank over ALL non-yizi valid_open ONLY for FB candidate dates (same memory: ~350k rows if >= 2% vs 7M). Wait: 7M rows of 4 cols (int16, int32, int16, float32) = 84 MB! Very small!
    m_vo = (is_st == 0) & np.isfinite(open_pct) & (open_raw > 0) & (prev_cr > 0)
    vo_dt = dt_id[m_vo]
    vo_ind = ind_id[m_vo]
    vo_op = open_pct[m_vo]
    vo_c6 = c6_id[m_vo]
    vo_ny = (is_yizi[m_vo] == 0) & (open_raw[m_vo] < zt_px_raw[m_vo] * 0.998)

    # Vectorized bincount for ind_0925_gap3_cnt & gap5_cnt
    n_inds = int(ind_id.max()) + 2
    n_dts = len(dt_cats)
    flat_key_3 = vo_dt[vo_op >= 3.0].astype(np.int32) * n_inds + vo_ind[vo_op >= 3.0].astype(np.int32)
    ind_g3_cnt = np.bincount(flat_key_3, minlength=n_dts * n_inds).astype(np.int16)
    flat_key_5 = vo_dt[vo_op >= 5.0].astype(np.int32) * n_inds + vo_ind[vo_op >= 5.0].astype(np.int32)
    ind_g5_cnt = np.bincount(flat_key_5, minlength=n_dts * n_inds).astype(np.int16)

    # Save open >= 2% dict for KPL theme 09:25 breadth calculation
    m_g2 = vo_op >= 2.0
    open_ge2_by_dt = defaultdict(dict)
    for di_v, ci_v, op_v, ny_v in zip(vo_dt[m_g2], vo_c6[m_g2], vo_op[m_g2], vo_ny[m_g2]):
        open_ge2_by_dt[str(dt_cats[int(di_v)])][str(c6_cats[int(ci_v)])] = (float(op_v), int(ny_v))

    # Locate contiguous c6 slices
    brk = np.flatnonzero(c6_id[1:] != c6_id[:-1]) + 1
    starts = np.concatenate(([0], brk))
    ends = np.concatenate((brk, [len(c6_id)]))

    # Identify all first-board touches <= END_BUY_DATE
    max_buy_di = set(np.flatnonzero(dt_cats <= END_BUY_DATE))
    fb_mask = (hit_zt == 1) & (prev_stk == 0) & (is_st == 0) & (amt_yi > 0.05) & np.isin(dt_id, list(max_buy_di))
    yizi_excl_mask = fb_mask & ((is_yizi == 1) | (open_raw >= zt_px_raw * 0.998) | (open_pct >= lim_pct - 0.25))
    cand_mask = fb_mask & (~yizi_excl_mask)

    audit_counts = {
        "total_hit_zt_prev0_nonst": int(fb_mask.sum()),
        "excluded_yizi_or_open_at_zt": int(yizi_excl_mask.sum()),
        "non_yizi_fb_touches": int(cand_mask.sum()),
        "non_yizi_10cm": int((cand_mask & (is_20 == 0)).sum()),
        "non_yizi_20cm": int((cand_mask & (is_20 == 1)).sum()),
        "non_yizi_10cm_broken": int((cand_mask & (is_20 == 0) & (is_zt == 0)).sum()),
        "non_yizi_20cm_broken": int((cand_mask & (is_20 == 1) & (is_zt == 0)).sum()),
    }

    # Compute exact ind_0925_rank_gap ONLY for (dt_id, ind_id) pairs present in cand_mask!
    cand_positions = np.flatnonzero(cand_mask)
    cand_dt_ind = set(zip(dt_id[cand_positions].tolist(), ind_id[cand_positions].tolist()))
    # Build (dt, ind) -> sorted list of non-yizi open_pct
    ind_ny_gaps = defaultdict(list)
    for di_v, ii_v, op_v, ny_v in zip(vo_dt, vo_ind, vo_op, vo_ny):
        if ny_v and (int(di_v), int(ii_v)) in cand_dt_ind:
            ind_ny_gaps[(int(di_v), int(ii_v))].append(float(op_v))
    for k_di in ind_ny_gaps:
        ind_ny_gaps[k_di].sort(reverse=True)
    del vo_dt, vo_ind, vo_op, vo_c6, vo_ny, m_vo, m_g2, cand_dt_ind
    gc.collect()

    pos_to_slice = np.searchsorted(ends, cand_positions, side="right")
    rows = []
    n_no_fwd = 0
    n_t1_dt_defer = 0
    for idx_k, pos in enumerate(cand_positions):
        sl_i = int(pos_to_slice[idx_k])
        s, e = int(starts[sl_i]), int(ends[sl_i])
        zt_px_a = float(zt_px_raw[pos]) * float(adj_f[pos])
        if not np.isfinite(zt_px_a) or zt_px_a <= 0:
            n_no_fwd += 1
            continue
        ex_dict = _calc_exits_and_mtm(
            int(pos), s, e, open_raw, close_raw, adj_f, prev_cr, is_zt, is_dt, is_yizi_dt, is_20, dt_cats, dt_id, zt_px_a
        )
        if "E1_T1Open" not in ex_dict or "E2_T1Close" not in ex_dict:
            n_no_fwd += 1
            continue

        di_v = int(dt_id[pos])
        ci_v = int(c6_id[pos])
        ii_v = int(ind_id[pos])
        dt_s = str(dt_cats[di_v])
        c6_s = str(c6_cats[ci_v])
        fk = di_v * n_inds + ii_v
        icnt3 = int(ind_g3_cnt[fk])
        icnt5 = int(ind_g5_cnt[fk])
        glist = ind_ny_gaps.get((di_v, ii_v), [])
        op_me = float(open_pct[pos])
        # rank = 1 + number of peers strictly > op_me
        irk = 1 + sum(1 for v in glist if v > op_me + 1e-6) if glist else 999

        rec = {
            "buy_date": dt_s,
            "code": c6_s,
            "is_20cm": int(is_20[pos]),
            "is_zt": int(is_zt[pos]),
            "is_broken_zt": int(is_broken[pos]),
            "open_pct": op_me,
            "ret_1d": float(ret_1d[pos]),
            "zt_px_adj": zt_px_a,
            "ac_day0": float(close_raw[pos]) * float(adj_f[pos]),
            "csrc_ind_id": ii_v,
            "ind_0925_gap3_cnt": icnt3,
            "ind_0925_gap5_cnt": icnt5,
            "ind_0925_rank_gap": int(irk),
            "audit_only_amount_yi": float(amt_yi[pos]),
        }
        for ename in ("E1_T1Open", "E2_T1Close", "E3_T2Close", "E4_StreakHold"):
            if ename in ex_dict:
                edt, ehh, gr, segs, hdays, dt_def = ex_dict[ename]
                rec[f"{ename}_exit_date"] = edt
                rec[f"{ename}_exit_hhmm"] = int(ehh)
                rec[f"{ename}_gross_ret"] = float(gr)
                rec[f"{ename}_hold_days"] = int(hdays)
                rec[f"{ename}_mtm_json"] = json.dumps(segs)
                if ename == "E1_T1Open" and dt_def:
                    n_t1_dt_defer += 1
            else:
                rec[f"{ename}_exit_date"] = ""
                rec[f"{ename}_exit_hhmm"] = 1500
                rec[f"{ename}_gross_ret"] = np.nan
                rec[f"{ename}_hold_days"] = 0
                rec[f"{ename}_mtm_json"] = "[]"
        rows.append(rec)

    fb_df = pd.DataFrame(rows)
    audit_counts["dropped_no_forward_bar"] = n_no_fwd
    audit_counts["t1_open_sealed_dt_deferred"] = n_t1_dt_defer
    audit_counts["final_pool_rows"] = len(fb_df)

    del open_raw, close_raw, adj_f, prev_cr, open_pct, ret_1d, is_zt, hit_zt, is_broken, is_yizi, is_dt, is_yizi_dt, prev_stk, is_st, is_20, amt_yi, ind_id, lim_pct, zt_px_raw, ind_g3_cnt, ind_g5_cnt, ind_ny_gaps
    gc.collect()
    print(f"[Step1A] Built {len(fb_df)} FB touches in {time.time()-t0:.1f}s (DT deferred={n_t1_dt_defer}) | RSS={peak_rss_mb()} MB")
    return fb_df, audit_counts, open_ge2_by_dt


def step1b_attach_pit_features_and_micro(fb_df: pd.DataFrame) -> pd.DataFrame:
    """Attach T-1 features from stock_day_core_features_pit + market_daily + audit_only zt_micro_tape."""
    t0 = time.time()
    stock_t1_cols = [
        "mcap_yi_t1", "free_mcap_yi_t1", "amount_yi_t1", "real_turn_pct_t1",
        "ret_1d_t1", "d1_open_pct", "prev_clv", "prev_is_broken_zt", "prev_is_yizi_zt",
        "overhang_pct_t1", "hr10d_space_t1", "hr30d_space_t1", "down_streak_t1",
        "pos_20d_t1", "pos_60d_t1", "pos_250d_t1", "dd_20d_t1", "amp_20d_t1",
        "bias10_t1", "bias20_t1", "ret_5d_t1", "ret_20d_t1", "vol_ratio5_t1",
        "turn_5_20_t1", "amp_comp_20v60_t1",
        "lhb_on_t1", "lhb_bayes_t2_t1", "lhb_inst_net_yi_t1", "lhb_lhasa_share_t1",
        "lhb_has_good_yz_t1", "lhb_has_surf_yz_t1", "lhb_has_quant_t1", "lhb_cnt_5d_t1",
        "lock_top10_pct_pre", "d1_first_seal_hhmm_t1", "d1_open_board_cnt_t1", "d1_seal_ratio_t1",
        "list_age", "waves_3y_g15_t1", "zt_cnt_1y_t1", "max_streak_3y",
        "cum_turnover_1y", "trap_waves_3y", "dd_from_3y_high",
        "cool_days_since_last_zt", "cool_days_since_last_2b",
        "comm_posts_1y_pct", "xq_posts_1y_pct",
        "kpl_unique_plates_3y", "kpl_top_plate_share",
        "kpl_zt3_t1", "kpl_days_30d_t1", "kpl_in_t1", "kpl_rank_t1", "kpl_zt1_t1", "kpl_streak_t1",
        "csrc_ind_ex5_t1", "csrc_ind_ex20_t1", "csrc_ind_rank20_t1",
        "csrc_ind_zt_share5_t1", "csrc_ind_amt_pct250_t1",
        "tox_reg_30d_pre", "abn_notice_30d_pre", "ir_cnt_30d_pre",
        "comm_ring_tier", "comm_driver_ret20_t1", "comm_driver_pct5y_t1",
    ]
    read_cols = ["c6", "dt"] + stock_t1_cols
    pairs = set(zip(fb_df["buy_date"], fb_df["code"]))
    dt_set = set(fb_df["buy_date"].unique())

    pf = pq.ParquetFile(STOCK_DAY_PQ)
    matched = []
    for i_b, batch in enumerate(pf.iter_batches(batch_size=100_000, columns=read_cols)):
        bdf = batch.to_pandas(categories=["c6", "dt"])
        dt_cats = bdf["dt"].cat.categories.astype(str).str[:10]
        v_dc = set(np.flatnonzero(dt_cats.isin(dt_set)))
        if not v_dc:
            continue
        mdt = bdf["dt"].cat.codes.isin(v_dc).to_numpy()
        if not mdt.any():
            continue
        sub = bdf.loc[mdt].copy()
        c6_arr = sub["c6"].cat.categories.astype(str).str.zfill(6).to_numpy()[sub["c6"].cat.codes.to_numpy()]
        dt_arr = sub["dt"].cat.categories.astype(str).str[:10].to_numpy()[sub["dt"].cat.codes.to_numpy()]
        mp = np.array([(d, c) in pairs for d, c in zip(dt_arr, c6_arr)], dtype=bool)
        if mp.any():
            hit = sub.loc[mp].copy()
            hit["buy_date"] = dt_arr[mp]
            hit["code"] = c6_arr[mp]
            hit.drop(columns=["c6", "dt"], inplace=True)
            matched.append(hit)
        del bdf, sub
        if i_b % 10 == 0:
            pa.default_memory_pool().release_unused()

    sd_t1 = pd.concat(matched, ignore_index=True).drop_duplicates(["buy_date", "code"])
    del matched
    pa.default_memory_pool().release_unused()
    gc.collect()
    fb_df = fb_df.merge(sd_t1, on=["buy_date", "code"], how="left")
    del sd_t1

    # Merge Market Daily T-1 / 09:25 / US Overnight features
    mkt_cols = [
        "trade_date", "L1_zt_cnt_t1", "L1_nat_zt_cnt_t1", "L1_dt_cnt_t1", "L1_zt_dt_logratio_t1",
        "L1_zb_rate_t1", "L1_max_board_t1", "L1_lianban_cnt_t1", "L1_zt_prem_t1",
        "L1_lb_promo_t1", "L1_duanban_damian_t1", "L1_zt_mom3v20_t1", "L1_zt_pct60_t1",
        "L1_sent_phase_t1", "L1_smb_5d_t1", "L1_smb_20d_t1", "L1_amt_ratio20_t1",
        "L1_ew_bias20_t1", "L1_ew_pos60_t1", "L1_is_earn_win", "L1_is_month_end3", "L1_weekday",
        "mkt20_zt_cnt_t1", "mkt_amt_tril_t1", "mkt_0925_zt_cnt", "mkt_0925_avg_gap_pct",
        "th_style_ice_point_sig_t1", "us_ixic_ret1d_on", "us_gspc_ret1d_on", "us_vix_level_on",
        "pol_rescue_signal_10d", "pol_crackdown_signal_10d",
    ]
    mkt = pd.read_parquet(MKT_DAY_PQ, columns=mkt_cols)
    mkt["buy_date"] = mkt["trade_date"].astype(str).str[:10]
    mkt.drop(columns=["trade_date"], inplace=True)
    fb_df = fb_df.merge(mkt, on="buy_date", how="left")

    # Attach audit_only zt_micro_tape (NEVER for causal WF features!)
    con_zt = sqlite3.connect(f"file:{DATA_DIR}/zt_micro_tape_5y_pit.db?mode=ro", uri=True)
    zt = pd.read_sql_query(
        "SELECT trade_date AS buy_date, sec_code AS code, first_seal_time, seal_amount, open_board_count, plate_name FROM zt_micro_tape WHERE trade_date <= ?",
        con_zt, params=(END_BUY_DATE,),
    )
    con_zt.close()
    zt["code"] = zt["code"].astype(str).str.zfill(6)
    zt = zt.drop_duplicates(["buy_date", "code"])
    zt["audit_only_seal_hhmm"] = pd.to_numeric(zt["first_seal_time"].astype(str).str.replace(":", "", regex=False).str[:4], errors="coerce").fillna(-1).astype(np.int16)
    zt["audit_only_seal_time"] = zt["first_seal_time"].fillna("").astype(str)
    zt["audit_only_open_cnt"] = pd.to_numeric(zt["open_board_count"], errors="coerce").fillna(-1).astype(np.int16)
    zt["audit_only_seal_yi"] = (pd.to_numeric(zt["seal_amount"], errors="coerce").fillna(0.0) / 1e8).astype(np.float32)
    zt["audit_only_plate"] = zt["plate_name"].fillna("").astype(str)
    fb_df = fb_df.merge(zt[["buy_date", "code", "audit_only_seal_hhmm", "audit_only_seal_time", "audit_only_open_cnt", "audit_only_seal_yi", "audit_only_plate"]], on=["buy_date", "code"], how="left")
    fb_df["audit_only_seal_hhmm"] = fb_df["audit_only_seal_hhmm"].fillna(-1).astype(np.int16)
    fb_df["audit_only_seal_time"] = fb_df["audit_only_seal_time"].fillna("")
    fb_df["audit_only_open_cnt"] = fb_df["audit_only_open_cnt"].fillna(-1).astype(np.int16)
    fb_df["audit_only_seal_yi"] = fb_df["audit_only_seal_yi"].fillna(0.0).astype(np.float32)
    fb_df["audit_only_seal_ratio"] = np.where(fb_df["audit_only_amount_yi"] > 0, fb_df["audit_only_seal_yi"] / fb_df["audit_only_amount_yi"], 0.0).astype(np.float32)

    print(f"[Step1B] Attached T-1 & audit_only tape in {time.time()-t0:.1f}s | RSS={peak_rss_mb()} MB")
    return fb_df


def step1c_attach_pit_news_and_themes(fb_df: pd.DataFrame, open_ge2_by_dt: dict) -> tuple[pd.DataFrame, dict]:
    """Attach strictly PIT (< 09:25 and intraday) stock & theme catalysts with fast 2-char hash theme matching."""
    t0 = time.time()
    bench = pd.read_parquet(BENCH_PQ, columns=["trade_date"])
    cal = sorted(bench["trade_date"].astype(str).tolist())
    cal_arr = np.array(cal, dtype=object)
    cal_idx = {d: i for i, d in enumerate(cal)}

    # 1. Strictly PIT KPL theme membership (< T)
    kpl_day_plates = {}
    all_clean_themes = {}
    with open(f"{DATA_DIR}/kpl_plates_2018_2026_merged.jsonl", encoding="utf-8") as f:
        for line in f:
            o = json.loads(line)
            dt = str(o["date"])[:10]
            if dt > END_BUY_DATE:
                continue
            plist = []
            for pl in o.get("plates", []):
                raw_p = str(pl.get("plate", "")).split("(")[0].strip()
                if not raw_p or raw_p in ("其他", "ST板块", "新股与次新股", "次新股", "ST摘帽"):
                    continue
                clean_p = raw_p.replace("概念", "").replace("板块", "").strip()
                if len(clean_p) < 2:
                    continue
                stks = {str(s[0])[:6].zfill(6) for s in pl.get("stocks", []) if s}
                if stks:
                    plist.append((clean_p, stks, len(stks)))
                    if clean_p not in all_clean_themes or dt < all_clean_themes[clean_p]:
                        all_clean_themes[clean_p] = dt
            kpl_day_plates[dt] = plist

    fb_pairs_by_dt = defaultdict(set)
    for d, c in zip(fb_df["buy_date"], fb_df["code"]):
        fb_pairs_by_dt[d].add(c)

    stock_theme_counts = defaultdict(lambda: defaultdict(int))
    theme_stock_counts = defaultdict(lambda: defaultdict(int))
    kpl_history_queue = []
    ptr_q = 0
    prev_day_hot_themes = {}

    kpl_gap3_map = {}
    kpl_rank_map = {}
    kpl_cold_map = {}
    stock_pit_themes_by_dt = {}

    kpl_cal_list = sorted([d for d in cal if d <= END_BUY_DATE])
    for i_d, d in enumerate(kpl_cal_list):
        while ptr_q < len(kpl_history_queue) and kpl_history_queue[ptr_q][0] < i_d - 90:
            _, old_pl = kpl_history_queue[ptr_q]
            for tp, stks, _ in old_pl:
                for c in stks:
                    stock_theme_counts[c][tp] -= 1
                    if stock_theme_counts[c][tp] <= 0:
                        del stock_theme_counts[c][tp]
                    theme_stock_counts[tp][c] -= 1
                    if theme_stock_counts[tp][c] <= 0:
                        del theme_stock_counts[tp][c]
            ptr_q += 1

        if d in fb_pairs_by_dt:
            g2_dict = open_ge2_by_dt.get(d, {})
            t_gap3 = {}
            t_scores_list = {}
            for tp, c_dict in theme_stock_counts.items():
                if not c_dict:
                    continue
                cnt3 = 0
                c_gaps = []
                for c in c_dict:
                    if c in g2_dict:
                        op_v, ny_v = g2_dict[c]
                        if op_v >= 3.0:
                            cnt3 += 1
                        if ny_v == 1:
                            c_gaps.append((op_v, c))
                if cnt3:
                    t_gap3[tp] = cnt3
                if c_gaps:
                    c_gaps.sort(reverse=True)
                    t_scores_list[tp] = {c: rk for rk, (_, c) in enumerate(c_gaps, 1)}

            for c in fb_pairs_by_dt[d]:
                tset = set(stock_theme_counts.get(c, {}).keys())
                stock_pit_themes_by_dt[(d, c)] = tset
                kpl_gap3_map[(d, c)] = max((t_gap3.get(tp, 0) for tp in tset), default=0)
                kpl_rank_map[(d, c)] = min((t_scores_list.get(tp, {}).get(c, 999) for tp in tset), default=999)
                kpl_cold_map[(d, c)] = 1 if (not tset or all(tp not in prev_day_hot_themes for tp in tset)) else 0

        cur_pl = kpl_day_plates.get(d, [])
        new_hot = {}
        for tp, stks, n_s in cur_pl:
            new_hot[tp] = n_s
            for c in stks:
                stock_theme_counts[c][tp] += 1
                theme_stock_counts[tp][c] += 1
        kpl_history_queue.append((i_d, cur_pl))
        prev_day_hot_themes = new_hot

    fb_df["kpl_0925_gap3_cnt"] = [kpl_gap3_map.get((d, c), 0) for d, c in zip(fb_df["buy_date"], fb_df["code"])]
    fb_df["kpl_0925_rank_gap"] = [kpl_rank_map.get((d, c), 999) for d, c in zip(fb_df["buy_date"], fb_df["code"])]
    fb_df["kpl_theme_cold_t1"] = [kpl_cold_map.get((d, c), 1) for d, c in zip(fb_df["buy_date"], fb_df["code"])]
    del stock_theme_counts, theme_stock_counts, kpl_history_queue, kpl_day_plates
    gc.collect()

    # 2. Fast 2-char bigram index for KPL themes (100x faster than 600-alt regex!)
    theme_by_bg = defaultdict(list)
    for tp, first_dt in all_clean_themes.items():
        if len(tp) >= 2:
            theme_by_bg[tp[:2]].append((tp, first_dt))
    bg_keys = set(theme_by_bg.keys())

    name_to_c6 = build_pit_name_map(END_BAR_DATE)
    code_re = re.compile(r"(?<![0-9])((?:00|60|30|688|689)\d{3})(?![0-9])")
    head_name_re = re.compile(r"(?:^|【)([^\s：:()（）【】]{2,8}?)(?:[：:(（])")
    pos_kw = re.compile(r"(中标|合同|签约|战略合作|合作协议|收购|并购|重组|增资|入股|获批|批准|批件|批文|注册证|订单|定点|量产|供货|突破|首发|预增|扭亏|大增|回购|增持|产能|扩产|涨价|提价|算力|国产替代|专利|首飞)")
    hard_kw = re.compile(r"(中标|合同|签约|收购|并购|重组|增资|获批|批件|注册证|订单|定点|量产|供货|预增|扭亏|回购|增持|涨价|提价)")
    neg_kw = re.compile(r"(减持|拟减持|立案|处罚|警示|违规|问询|监管函|亏损|预亏|预减|同比下降|终止|取消|流拍|诉讼|仲裁|冻结|解禁|质押|异常波动|风险提示|澄清|未涉足|不涉及|无相关)")
    theme_cat_kw = re.compile(r"(突破|首款|发布|获批|涨价|提价|印发|推进|意见|方案|规划|支持|爆发|订单|量产|加速|暴涨|大涨|试点|落地|重磅|国务院|工信部|发改委|央行|证监会)")

    # Vectorized date-time slot cache to avoid repeated searchsorted per news item
    dt_pos_cache = {}
    def _map_news_slot(pub_str: str) -> tuple[str, str, str]:
        dt_p = pub_str[:10]
        hm_p = pub_str[11:19]
        res_p = dt_pos_cache.get(dt_p)
        if res_p is None:
            pos = int(np.searchsorted(cal_arr, dt_p, side="left"))
            on_same = (pos < len(cal_arr) and cal_arr[pos] == dt_p)
            next_d = str(cal_arr[pos + 1]) if (on_same and pos + 1 < len(cal_arr)) else ""
            cur_d = str(cal_arr[pos]) if pos < len(cal_arr) else ""
            res_p = (on_same, cur_d, next_d)
            dt_pos_cache[dt_p] = res_p
        on_same, cur_d, next_d = res_p
        if not cur_d:
            return "", "", ""
        if on_same:
            if hm_p < "09:25:00":
                return cur_d, "pre", hm_p
            if "09:30:00" <= hm_p <= "14:55:00":
                return cur_d, ("intra_early" if hm_p <= "10:00:00" else "intra_late"), hm_p
            if hm_p > "15:00:00" and next_d:
                return next_d, "pre", hm_p
            return "", "", ""
        return cur_d, "pre", hm_p

    st_pre_any = defaultdict(int)
    st_pre_pos = defaultdict(int)
    st_pre_hard = defaultdict(int)
    st_pre_neg = defaultdict(int)
    st_intra_early = defaultdict(int)
    st_intra_all = defaultdict(int)
    st_intra_times = defaultdict(list)
    st_news_dates = defaultdict(set)
    th_pre_cat = defaultdict(int)
    th_intra_early_cat = defaultdict(int)

    con_fn = sqlite3.connect(f"file:{DATA_DIR}/flash_news_5y_pit.db?mode=ro", uri=True)
    cur = con_fn.cursor()
    cur.execute("SELECT pub_datetime_cst, title, substr(content, 1, 240) FROM flash_news WHERE pub_datetime_cst <= '2026-11-16 15:00:00'")
    n_scanned = 0
    while True:
        rows = cur.fetchmany(100_000)
        if not rows:
            break
        for pub, title, cont in rows:
            n_scanned += 1
            eff_dt, slot, hm_p = _map_news_slot(pub)
            if not eff_dt or eff_dt > END_BUY_DATE:
                continue
            txt = (title or "") + " " + (cont or "")
            txt_head = txt[:160]
            is_neg = bool(neg_kw.search(txt))

            # Stock match
            c_found = set(code_re.findall(txt[:220]))
            for hm in head_name_re.findall(txt[:80]):
                hm_c = hm.replace("*ST", "").replace("ST", "").replace("Ａ", "A").strip()
                if hm_c in name_to_c6:
                    c_found.add(name_to_c6[hm_c])

            if c_found:
                is_pos = bool(pos_kw.search(txt))
                fb_day_set = fb_pairs_by_dt.get(eff_dt)
                for c6_v in c_found:
                    st_news_dates[c6_v].add(eff_dt)
                    if fb_day_set and c6_v in fb_day_set:
                        key = (eff_dt, c6_v)
                        if slot == "pre":
                            if is_neg:
                                st_pre_neg[key] += 1
                            else:
                                st_pre_any[key] += 1
                                if is_pos:
                                    st_pre_pos[key] += 1
                                    if hard_kw.search(txt):
                                        st_pre_hard[key] += 1
                        else:
                            if not is_neg:
                                st_intra_all[key] += 1
                                st_intra_times[key].append(hm_p)
                                if slot == "intra_early":
                                    st_intra_early[key] += 1

            # Fast 2-char bigram theme scan (only when catalyst verb present!)
            if slot in ("pre", "intra_early") and not is_neg and theme_cat_kw.search(txt_head):
                hits_bg = {txt_head[k : k + 2] for k in range(len(txt_head) - 1)} & bg_keys
                if hits_bg:
                    matched_ths = set()
                    for bg in hits_bg:
                        for tp, f_dt in theme_by_bg[bg]:
                            if f_dt < eff_dt and tp in txt_head:
                                matched_ths.add(tp)
                    if slot == "pre":
                        for tp in matched_ths:
                            th_pre_cat[(eff_dt, tp)] += 1
                    else:
                        for tp in matched_ths:
                            th_intra_early_cat[(eff_dt, tp)] += 1
    con_fn.close()

    # 3. CNINFO positive announcements & IR Q&A (< 09:25 pre-open)
    con_cn = sqlite3.connect(f"file:{DATA_DIR}/cninfo_notices_5y_pit.db?mode=ro", uri=True)
    cn_df = pd.read_sql_query(
        """
        SELECT sec_code, pub_datetime_cst, title
        FROM notices
        WHERE substr(pub_datetime_cst,1,10) <= ?
          AND (ann_type IN ('业绩预告:预增', '业绩预告:扭亏', '业绩预告:略增', '重大合同', '并购重组')
               OR title LIKE '%中标%' OR title LIKE '%重大合同%' OR title LIKE '%收购%' OR title LIKE '%回购%' OR title LIKE '%增持%')
        """,
        con_cn, params=(END_BUY_DATE,),
    )
    con_cn.close()
    cn_pre_set = set()
    for sc, pub, ttl in zip(cn_df["sec_code"], cn_df["pub_datetime_cst"], cn_df["title"]):
        if neg_kw.search(str(ttl)):
            continue
        eff_dt, slot, _ = _map_news_slot(str(pub))
        if eff_dt and slot == "pre":
            cn_pre_set.add((eff_dt, str(sc).zfill(6)))

    con_ir = sqlite3.connect(f"file:{SIM_DIR}/backtests_astock2/data_5y/cninfo_ir_qa_5y_pit.db?mode=ro", uri=True)
    ir_df = pd.read_sql_query("SELECT sec_code, pub_datetime_cst FROM ir_qa WHERE substr(pub_datetime_cst,1,10) <= ?", con_ir, params=(END_BUY_DATE,))
    con_ir.close()
    ir_pre_set = set()
    for sc, pub in zip(ir_df["sec_code"], ir_df["pub_datetime_cst"]):
        eff_dt, slot, _ = _map_news_slot(str(pub))
        if eff_dt and slot == "pre":
            ir_pre_set.add((eff_dt, str(sc).zfill(6)))

    n = len(fb_df)
    fn_pre_any = np.zeros(n, dtype=np.int8)
    fn_pre_pos = np.zeros(n, dtype=np.int8)
    fn_pre_hard = np.zeros(n, dtype=np.int8)
    fn_pre_neg = np.zeros(n, dtype=np.int8)
    fn_pre_cold = np.zeros(n, dtype=np.int8)
    fn_intra_early = np.zeros(n, dtype=np.int8)
    fn_intra_all = np.zeros(n, dtype=np.int8)
    cn_pre_pos = np.zeros(n, dtype=np.int8)
    ir_pre_pos = np.zeros(n, dtype=np.int8)
    th_pre_hit = np.zeros(n, dtype=np.int16)
    th_intra_early_hit = np.zeros(n, dtype=np.int16)
    audit_first_intra_hm = [""] * n

    for i, (d, c) in enumerate(zip(fb_df["buy_date"], fb_df["code"])):
        key = (d, c)
        if st_pre_any.get(key, 0) > 0:
            fn_pre_any[i] = 1
        if st_pre_pos.get(key, 0) > 0:
            fn_pre_pos[i] = 1
            di_cur = cal_idx.get(d, -1)
            if di_cur >= 10:
                prev10 = set(cal[di_cur - 10 : di_cur])
                if not (st_news_dates.get(c, set()) & prev10):
                    fn_pre_cold[i] = 1
        if st_pre_hard.get(key, 0) > 0:
            fn_pre_hard[i] = 1
        if st_pre_neg.get(key, 0) > 0:
            fn_pre_neg[i] = 1
        if st_intra_early.get(key, 0) > 0:
            fn_intra_early[i] = 1
        if st_intra_all.get(key, 0) > 0:
            fn_intra_all[i] = 1
            audit_first_intra_hm[i] = min(st_intra_times[key])
        if key in cn_pre_set:
            cn_pre_pos[i] = 1
        if key in ir_pre_set:
            ir_pre_pos[i] = 1

        tset = stock_pit_themes_by_dt.get(key, set())
        if tset:
            th_pre_hit[i] = sum(th_pre_cat.get((d, tp), 0) for tp in tset)
            th_intra_early_hit[i] = sum(th_intra_early_cat.get((d, tp), 0) for tp in tset)

    fb_df["fn_pre_any"] = fn_pre_any
    fb_df["fn_pre_pos"] = fn_pre_pos
    fb_df["fn_pre_hard"] = fn_pre_hard
    fb_df["fn_pre_neg"] = fn_pre_neg
    fb_df["fn_pre_cold"] = fn_pre_cold
    fb_df["fn_intra_early"] = fn_intra_early
    fb_df["fn_intra_all"] = fn_intra_all
    fb_df["cninfo_pre_pos"] = cn_pre_pos
    fb_df["ir_pre_pos"] = ir_pre_pos
    fb_df["any_pre_cat"] = ((fn_pre_pos == 1) | (cn_pre_pos == 1) | (ir_pre_pos == 1)).astype(np.int8)
    fb_df["theme_news_pre_cnt"] = th_pre_hit
    fb_df["theme_news_intra_early_cnt"] = th_intra_early_hit
    fb_df["audit_only_first_intra_news_hm"] = audit_first_intra_hm

    lim_pct = np.where(fb_df["is_20cm"] == 1, 20.0, 10.0)
    fb_df["gap_to_zt_dist"] = (lim_pct - fb_df["open_pct"]).astype(np.float32)
    fb_df["is_weak_to_strong_brk"] = ((fb_df["prev_is_broken_zt"] == 1) & (fb_df["open_pct"] >= 1.0)).astype(np.int8)
    fb_df["is_weak_to_strong_neg"] = ((fb_df["ret_1d_t1"] <= -2.0) & (fb_df["open_pct"] >= 1.5)).astype(np.int8)
    fb_df["is_day0_theme_ignite"] = (((fb_df["theme_news_pre_cnt"] >= 1) | (fb_df["kpl_0925_gap3_cnt"] >= 2) | (fb_df["ind_0925_gap3_cnt"] >= 3)) & (fb_df["kpl_theme_cold_t1"] == 1)).astype(np.int8)

    sub_int = fb_df[(fb_df["fn_intra_all"] == 1) & (fb_df["is_zt"] == 1) & (fb_df["audit_only_seal_time"] != "")]
    n_pre_seal = int((sub_int["audit_only_first_intra_news_hm"] <= sub_int["audit_only_seal_time"]).sum())
    n_post_seal = int((sub_int["audit_only_first_intra_news_hm"] > sub_int["audit_only_seal_time"]).sum())

    news_audit = {
        "flash_news_scanned": n_scanned,
        "flash_news_date_range": "2021-01-19 ~ 2026-11-11",
        "fb_with_fn_pre_any": int(fn_pre_any.sum()),
        "fb_with_fn_pre_pos": int(fn_pre_pos.sum()),
        "fb_with_fn_pre_hard": int(fn_pre_hard.sum()),
        "fb_with_fn_pre_cold": int(fn_pre_cold.sum()),
        "fb_with_cninfo_pre_pos": int(cn_pre_pos.sum()),
        "fb_with_ir_pre_pos": int(ir_pre_pos.sum()),
        "fb_with_any_pre_cat": int(fb_df["any_pre_cat"].sum()),
        "fb_with_theme_news_pre": int((th_pre_hit > 0).sum()),
        "fb_with_day0_theme_ignite": int(fb_df["is_day0_theme_ignite"].sum()),
        "fb_with_fn_intra_early_0930_1000": int(fn_intra_early.sum()),
        "fb_with_fn_intra_all_0930_1455": int(fn_intra_all.sum()),
        "intraday_news_causality_audit_on_sealed": {
            "n_sealed_with_intra_news": int(len(sub_int)),
            "news_before_or_at_seal": n_pre_seal,
            "news_after_seal_reverse_causality": n_post_seal,
            "reverse_causality_pct": round(n_post_seal / max(1, len(sub_int)) * 100.0, 2),
        },
    }
    print(f"[Step1C] News & Themes done in {time.time()-t0:.1f}s | {news_audit} | RSS={peak_rss_mb()} MB")
    return fb_df, news_audit


def main():
    t0 = time.time()
    fb_df, pool_audit, open_ge2_by_dt = step1_extract_fb_universe()
    fb_df = step1b_attach_pit_features_and_micro(fb_df)
    fb_df, news_audit = step1c_attach_pit_news_and_themes(fb_df, open_ge2_by_dt)

    out_pq = f"{CACHE_DIR}/rd041_fb_master_pit.parquet"
    fb_df.to_parquet(out_pq, index=False)

    audit = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t0, 2),
        "peak_rss_mb": peak_rss_mb(),
        "d12_yfinance_imported": "yfinance" in sys.modules,
        "pool_audit": pool_audit,
        "news_audit": news_audit,
        "output_parquet": out_pq,
    }
    with open(f"{CACHE_DIR}/rd041_step1_audit.json", "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)
    print(f"[Step1 DONE] Saved {out_pq} ({len(fb_df)} rows, {fb_df.shape[1]} cols) in {audit['elapsed_sec']}s | Peak RSS={audit['peak_rss_mb']} MB")


if __name__ == "__main__":
    main()

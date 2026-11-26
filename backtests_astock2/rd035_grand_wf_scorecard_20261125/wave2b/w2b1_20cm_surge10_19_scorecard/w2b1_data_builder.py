#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 2B-1 Step 1: Build Strict PIT 20cm Surge (10%~19.8% Non-ZT) Candidate Pool & 3 Exit Trees.
- Two-stage column-pruned + batch-filtered PyArrow scan on `stock_day_core_features_pit.parquet` (< 0.8 GB RSS).
- Full causal KPL historical theme linkage (`hist_kpl` strictly <= T0 + normalized plate tokens + 10cm leader
  yizi/early1030 linkage + 180d/365d/all-prior KPL tiers, fixing `kpl_in_t1 == 0` on non-ZT surge bars!).
- Dynamic PIT ST timeline (`zt_micro_tape` + `cninfo_notices` + `reg_tox_notices`) catching delisted ST traps.
- Excludes IPO first 5 days (`list_age > 5`), sub-2-yuan face-delisting traps, and T+1 suspended rows.
- Simulates 3 exits (0.30% RT cost): X1_T1_Close, X2_T2_Close, X3_20cm_4Branch (exact V20 20cm tree).
Zero yfinance (D12). Zero cap10m. Internal threads <= 1.
"""
import os
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

import argparse
import bisect
import gc
import json
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
warnings.filterwarnings("ignore")

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
WAVE1 = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
RD033 = f"{SIM}/backtests_astock2/rd033_20cm_theme_surge10_19_20261125"
OUT_DIR = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave2b/w2b1_20cm_surge10_19_scorecard"

for p in (WAVE1, RD033):
    if p not in sys.path:
        sys.path.insert(0, p)

import rd033_data_and_kpl as dk

FEE_RT = 0.0030
TP_BUF = 0.0030

SD_T1_PIT_COLS = [
    "open_pct",
    "mcap_yi_t1", "amount_yi_t1", "ret_1d_t1", "d1_open_pct", "prev_clv",
    "prev_streak", "prev_is_broken_zt", "prev_is_yizi_zt",
    "overhang_pct_t1", "hr10d_space_t1", "hr30d_space_t1", "down_streak_t1",
    "pos_20d_t1", "pos_60d_t1", "pos_250d_t1", "dd_20d_t1", "amp_20d_t1",
    "bias10_t1", "bias20_t1", "ret_5d_t1", "ret_20d_t1", "vol_ratio5_t1",
    "turn_5_20_t1", "amp_comp_20v60_t1",
    "lhb_on_t1", "lhb_bayes_t2_t1", "lhb_inst_net_yi_t1", "lhb_lhasa_share_t1",
    "lhb_has_good_yz_t1", "lhb_has_surf_yz_t1", "lhb_has_quant_t1", "lhb_cnt_5d_t1",
    "lock_top10_pct_pre", "free_mcap_yi_t1", "real_turn_pct_t1",
    "d1_first_seal_hhmm_t1", "d1_open_board_cnt_t1", "d1_seal_ratio_t1",
    "list_age", "waves_3y_g15_t1", "zt_cnt_1y_t1", "max_streak_3y",
    "cum_turnover_1y", "trap_waves_3y", "dd_from_3y_high",
    "cool_days_since_last_zt", "cool_days_since_last_2b",
    "comm_posts_1y_pct", "xq_posts_1y_pct",
    "kpl_unique_plates_3y", "kpl_top_plate_share",
    "kpl_zt3_t1", "kpl_days_30d_t1",
    "csrc_ind_id", "csrc_ind_ex5_t1", "csrc_ind_ex20_t1", "csrc_ind_rank20_t1",
    "csrc_ind_zt_share5_t1", "csrc_ind_amt_pct250_t1",
    "tox_reg_30d_pre", "abn_notice_30d_pre", "ir_cnt_30d_pre", "comm_ring_tier",
]

SD_BAR_COLS = [
    "dt", "c6", "open", "high", "low", "close", "adj_factor",
    "ret_1d", "open_pct", "is_zt", "hit_zt", "is_yizi_zt",
    "is_dt", "is_yizi_dt", "is_st_pit", "list_age", "prev_close_raw",
    "amount_yi", "turn_pct",
]


def _causal_pct_rank_250(arr: np.ndarray, starts: np.ndarray, ends: np.ndarray) -> np.ndarray:
    """Strictly causal rolling <=250d percentile rank per stock."""
    out = np.full(len(arr), np.nan, dtype=np.float32)
    for s, e in zip(starts, ends):
        sub = arr[s:e]
        m = e - s
        if m < 10:
            continue
        if m >= 250:
            wv = np.lib.stride_tricks.sliding_window_view(sub, 250)
            cur = sub[249:, None]
            valid = np.isfinite(wv) & np.isfinite(cur)
            cnt = valid.sum(axis=1)
            le = (wv <= cur) & valid
            res = np.where(cnt >= 20, le.sum(axis=1) / np.maximum(cnt, 1), np.nan)
            out[s + 249 : e] = res.astype(np.float32)
        for i in range(9, min(m, 249)):
            v = sub[i]
            if not np.isfinite(v):
                continue
            win = sub[: i + 1]
            win = win[np.isfinite(win)]
            if len(win) >= 10:
                out[s + i] = float(np.mean(win <= v))
    return out


def _simulate_3exits_for_candidates(cand: pd.DataFrame, stock_series: dict, mkt_tp1_risk: dict) -> pd.DataFrame:
    """Simulate X1_T1_Close, X2_T2_Close, X3_20cm_4Branch strictly causally."""
    n = len(cand)
    res_cols = {}
    for ex_name in ("X1_T1_Close", "X2_T2_Close", "X3_20cm_4Branch"):
        res_cols[f"{ex_name}__exit_date"] = np.full(n, "", dtype=object)
        res_cols[f"{ex_name}__exit_hhmm"] = np.zeros(n, dtype=np.int16)
        res_cols[f"{ex_name}__gross_ret"] = np.full(n, np.nan, dtype=np.float32)
        res_cols[f"{ex_name}__net_ret"] = np.full(n, np.nan, dtype=np.float32)
        res_cols[f"{ex_name}__reason"] = np.full(n, "", dtype=object)
        res_cols[f"{ex_name}__hold_bars"] = np.zeros(n, dtype=np.int8)

    def _defer_dt(ss, k_start):
        m = len(ss["dts"])
        k = min(k_start, m - 1)
        while k < m - 1 and ss["is_yizi_dt"][k]:
            k += 1
        return k

    def _finish_close(ss, k, b0, buy_adj, rsn):
        m = len(ss["dts"])
        if ss["is_dt"][k]:
            kd = _defer_dt(ss, min(k + 1, m - 1))
            if kd > k:
                px_adj = float(ss["open"][kd]) * float(ss["adjf"][kd])
                hh, ed = 925, str(ss["dts"][kd])
            else:
                px_adj = float(ss["close"][kd]) * float(ss["adjf"][kd])
                hh, ed = 1500, str(ss["dts"][kd])
            gr = px_adj / buy_adj - 1.0
            nr = (1.0 + gr) * (1.0 - FEE_RT) - 1.0
            return ed, hh, gr, nr, f"{rsn}|dt_defer", kd - b0 + 1
        px_adj = float(ss["close"][k]) * float(ss["adjf"][k])
        gr = px_adj / buy_adj - 1.0
        nr = (1.0 + gr) * (1.0 - FEE_RT) - 1.0
        return str(ss["dts"][k]), 1500, gr, nr, rsn, k - b0 + 1

    def _finish_px(ss, k, px_raw, hh, b0, buy_adj, rsn):
        px_adj = float(px_raw) * float(ss["adjf"][k])
        gr = px_adj / buy_adj - 1.0
        nr = (1.0 + gr) * (1.0 - FEE_RT) - 1.0
        return str(ss["dts"][k]), int(hh), gr, nr, rsn, k - b0 + 1

    def _ride_zt(ss, start_k, b0, buy_adj, max_off=10):
        m = len(ss["dts"])
        k = start_k + 1
        while k < m and (k - b0 <= max_off):
            if ss["is_yizi_dt"][k]:
                k += 1
                continue
            if k > start_k + 1 and ss["is_dt"][k - 1]:
                return _finish_px(ss, k, ss["open"][k], 925, b0, buy_adj, "zt_prev_dt_open")
            if ss["is_zt"][k]:
                k += 1
                continue
            return _finish_close(ss, k, b0, buy_adj, "zt_break_eod")
        kd = min(k, m - 1)
        return _finish_close(ss, kd, b0, buy_adj, "zt_max_hold_eod")

    def _try_tp(ss, k, tp_px):
        ok = float(ss["open"][k])
        hk = float(ss["high"][k])
        dtk = float(ss["dt_px"][k])
        ztk = float(ss["zt_px"][k])
        if ok >= tp_px and ok > dtk + 0.005:
            return True, ok, 925, "gap_tp"
        need_hk = min(tp_px * (1.0 + TP_BUF), ztk - 1e-4)
        if hk >= need_hk and tp_px > dtk + 0.005:
            return True, tp_px, 1030, "intraday_tp"
        return False, np.nan, 0, ""

    codes = cand["code"].to_numpy()
    bdts = cand["buy_date"].to_numpy()

    for i in range(n):
        ss = stock_series.get(codes[i])
        if ss is None:
            continue
        b0 = ss["d2i"].get(bdts[i])
        m = len(ss["dts"])
        if b0 is None or b0 + 1 >= m:
            continue

        o0 = float(ss["open"][b0])
        h0 = float(ss["high"][b0])
        l0 = float(ss["low"][b0])
        c0 = float(ss["close"][b0])
        adj0 = float(ss["adjf"][b0])
        buy_adj = o0 * adj0
        if buy_adj <= 0:
            continue

        # X1_T1_Close
        k1 = _defer_dt(ss, b0 + 1)
        if k1 > b0 + 1:
            ed, hh, gr, nr, rsn, hb = _finish_px(ss, k1, ss["open"][k1], 925, b0, buy_adj, "t1_yizi_dt_defer")
        else:
            ed, hh, gr, nr, rsn, hb = _finish_close(ss, k1, b0, buy_adj, "t1_close")
        res_cols["X1_T1_Close__exit_date"][i] = ed
        res_cols["X1_T1_Close__exit_hhmm"][i] = hh
        res_cols["X1_T1_Close__gross_ret"][i] = gr
        res_cols["X1_T1_Close__net_ret"][i] = nr
        res_cols["X1_T1_Close__reason"][i] = rsn
        res_cols["X1_T1_Close__hold_bars"][i] = hb

        # X2_T2_Close
        if b0 + 2 < m:
            k2 = _defer_dt(ss, b0 + 2)
            if k2 > b0 + 2:
                ed2, hh2, gr2, nr2, rsn2, hb2 = _finish_px(ss, k2, ss["open"][k2], 925, b0, buy_adj, "t2_yizi_dt_defer")
            else:
                ed2, hh2, gr2, nr2, rsn2, hb2 = _finish_close(ss, k2, b0, buy_adj, "t2_close")
            res_cols["X2_T2_Close__exit_date"][i] = ed2
            res_cols["X2_T2_Close__exit_hhmm"][i] = hh2
            res_cols["X2_T2_Close__gross_ret"][i] = gr2
            res_cols["X2_T2_Close__net_ret"][i] = nr2
            res_cols["X2_T2_Close__reason"][i] = rsn2
            res_cols["X2_T2_Close__hold_bars"][i] = hb2

        # X3_20cm_4Branch
        if ss["is_zt"][b0]:
            ed3, hh3, gr3, nr3, rsn3, hb3 = _ride_zt(ss, b0, b0, buy_adj, max_off=10)
        elif k1 > b0 + 1:
            ed3, hh3, gr3, nr3, rsn3, hb3 = _finish_px(ss, k1, ss["open"][k1], 925, b0, buy_adj, "B4_yizi_dt_defer")
        else:
            pc0 = float(ss["prev_c"][b0]) if np.isfinite(ss["prev_c"][b0]) else o0
            op0_pct = (o0 / pc0 - 1.0) if pc0 > 0 else 0.0
            body0 = (c0 / o0 - 1.0) if o0 > 0 else 0.0
            clv0 = (c0 - l0) / (h0 - l0) if (h0 - l0) > 1e-6 else 0.5
            dk1 = str(ss["dts"][k1])
            risk_hit = bool(mkt_tp1_risk.get(dk1, False))

            if body0 <= -0.05 or ss["is_dt"][b0]:
                ed3, hh3, gr3, nr3, rsn3, hb3 = _finish_close(ss, k1, b0, buy_adj, "B4_d2_close")
            elif body0 >= 0.06 and clv0 >= 0.65:
                b2_tp = 0.07 if risk_hit else 0.12
                tp_px = c0 * (adj0 / float(ss["adjf"][k1])) * (1.0 + b2_tp)
                hit, px_h, hh_h, r_h = _try_tp(ss, k1, tp_px)
                if hit:
                    ed3, hh3, gr3, nr3, rsn3, hb3 = _finish_px(ss, k1, px_h, hh_h, b0, buy_adj, f"B2_{r_h}")
                elif risk_hit:
                    ed3, hh3, gr3, nr3, rsn3, hb3 = _finish_close(ss, k1, b0, buy_adj, "B2_d2_risk_close")
                elif ss["is_zt"][k1]:
                    ed3, hh3, gr3, nr3, rsn3, hb3 = _ride_zt(ss, k1, b0, buy_adj, max_off=10)
                elif k1 + 1 < m:
                    k2 = k1 + 1
                    if ss["is_yizi_dt"][k2]:
                        kd = _defer_dt(ss, k2)
                        ed3, hh3, gr3, nr3, rsn3, hb3 = _finish_px(ss, kd, ss["open"][kd], 925, b0, buy_adj, "B2_d3_defer")
                    else:
                        c1 = float(ss["close"][k1])
                        tp_px2 = c1 * (float(ss["adjf"][k1]) / float(ss["adjf"][k2])) * (1.0 + b2_tp)
                        hit2, px2, hh2_v, r2 = _try_tp(ss, k2, tp_px2)
                        if hit2:
                            ed3, hh3, gr3, nr3, rsn3, hb3 = _finish_px(ss, k2, px2, hh2_v, b0, buy_adj, f"B2_d3_{r2}")
                        else:
                            ed3, hh3, gr3, nr3, rsn3, hb3 = _finish_close(ss, k2, b0, buy_adj, "B2_d3_close")
                else:
                    ed3, hh3, gr3, nr3, rsn3, hb3 = _finish_close(ss, k1, b0, buy_adj, "B2_d2_eod_end")
            else:
                tp3_base = max(0.06, min(0.15, abs(op0_pct) * 1.5))
                tp3 = min(tp3_base, 0.07) if risk_hit else tp3_base
                tp_px3 = c0 * (adj0 / float(ss["adjf"][k1])) * (1.0 + tp3)
                hit3, px3, hh3_v, r3 = _try_tp(ss, k1, tp_px3)
                if hit3:
                    ed3, hh3, gr3, nr3, rsn3, hb3 = _finish_px(ss, k1, px3, hh3_v, b0, buy_adj, f"B3_{r3}")
                else:
                    ed3, hh3, gr3, nr3, rsn3, hb3 = _finish_close(ss, k1, b0, buy_adj, "B3_d2_close")

        res_cols["X3_20cm_4Branch__exit_date"][i] = ed3
        res_cols["X3_20cm_4Branch__exit_hhmm"][i] = hh3
        res_cols["X3_20cm_4Branch__gross_ret"][i] = gr3
        res_cols["X3_20cm_4Branch__net_ret"][i] = nr3
        res_cols["X3_20cm_4Branch__reason"][i] = rsn3
        res_cols["X3_20cm_4Branch__hold_bars"][i] = hb3

    return pd.concat([cand.reset_index(drop=True), pd.DataFrame(res_cols)], axis=1)


def _stream_parquet_filtered(path: str, columns: list[str], cond_fn, batch_size: int = 32768) -> pd.DataFrame:
    """Stream parquet in small single-threaded Arrow batches so peak RSS stays < 1.2 GB."""
    pf = pq.ParquetFile(path)
    parts = []
    for batch in pf.iter_batches(batch_size=batch_size, columns=columns, use_threads=False):
        df = batch.to_pandas()
        m = cond_fn(df)
        if np.any(m):
            parts.append(df.loc[m].copy())
        del df
    pa.default_memory_pool().release_unused()
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=columns)


def _compute_causal_kpl_theme_features(cand: pd.DataFrame, end_cutoff: str) -> tuple[pd.DataFrame, dict, dict]:
    """
    Build strictly causal KPL theme linkage on sig_date (T0) matching RD033:
    - Uses `is_zt == 1` across all A-shares <= end_cutoff + `zt_micro_tape` early<=10:30 seals.
    - Tracks historical KPL plate memberships (`hist_kpl` strictly <= T0) + normalized tokens (`split_norm_plates`),
      plus `kpl_t0_stock_direct` on T0, plus 180d/365d/all-prior KPL rank & ZT counts.
    """
    zt_df = _stream_parquet_filtered(
        f"{WAVE1}/stock_day_core_features_pit.parquet",
        columns=["dt", "c6", "is_20cm", "is_yizi_zt", "is_zt", "is_st_pit"],
        cond_fn=lambda d: (d["is_zt"] == 1) & (d["is_st_pit"] == 0) & (d["dt"].astype(str).str[:10] <= end_cutoff),
    )
    zt_df["dt"] = zt_df["dt"].astype(str).str[:10]
    zt_df["c6"] = zt_df["c6"].astype(str).str.zfill(6)

    zt10_by_dt, yz10_by_dt, zt20_by_dt = defaultdict(set), defaultdict(set), defaultdict(set)
    for dt_x, c6_x, i20_x, yz_x in zt_df[["dt", "c6", "is_20cm", "is_yizi_zt"]].itertuples(index=False, name=None):
        if i20_x == 0:
            zt10_by_dt[dt_x].add(c6_x)
            if yz_x == 1:
                yz10_by_dt[dt_x].add(c6_x)
        else:
            zt20_by_dt[dt_x].add(c6_x)
    del zt_df

    early1030_10_by_dt = defaultdict(set)
    con_z = sqlite3.connect(f"file:{SIM}/data/zt_micro_tape_5y_pit.db?mode=ro", uri=True)
    for td, sc, fst in con_z.execute(
        "SELECT trade_date, sec_code, first_seal_time FROM zt_micro_tape WHERE trade_date >= '2021-01-04' AND trade_date <= ?",
        (end_cutoff,),
    ):
        c6 = str(sc).zfill(6)
        if c6.startswith(("00", "60")):
            fst_s = str(fst or "15:00:00").replace(":", "")[:4]
            if (int(fst_s) if fst_s.isdigit() else 1500) <= 1030:
                early1030_10_by_dt[str(td)].add(c6)
    con_z.close()

    hist_kpl = defaultdict(list)
    kpl_t0_plate_stats = {}
    kpl_t0_stock_direct = {}
    kpl_objs = []
    with open(f"{SIM}/data/kpl_plates_2018_2026_merged.jsonl", encoding="utf-8") as f:
        for ln in f:
            if not ln.strip():
                continue
            obj = json.loads(ln)
            dt_k = str(obj.get("date", ""))[:10]
            if dt_k <= end_cutoff:
                kpl_objs.append(obj)
    kpl_objs.sort(key=lambda x: x["date"])

    kpl_by_dt_plate = {}
    kpl_by_dt_code = defaultdict(list)

    for obj in kpl_objs:
        dt_k = str(obj["date"])[:10]
        z10 = zt10_by_dt.get(dt_k, set())
        z20 = zt20_by_dt.get(dt_k, set())
        yz10 = yz10_by_dt.get(dt_k, set())
        e1030 = early1030_10_by_dt.get(dt_k, set())
        rk = 0
        for pl in obj.get("plates", []):
            raw_pn = str(pl.get("plate", "")).strip()
            if not raw_pn or raw_pn in dk.NON_THEME:
                continue
            tokens = dk.split_norm_plates(raw_pn)
            if not tokens:
                continue
            rk += 1
            mems = {str(s[0]).strip()[-6:].zfill(6) for s in pl.get("stocks", []) if s}
            kpl_sz = len(mems)
            if dt_k >= "2021-01-04":
                n10 = len(mems & z10)
                n20 = len(mems & z20)
                tot_zt = max(kpl_sz, n10 + n20)
                has_10yz = int(len(mems & yz10) >= 1)
                has_10e1030 = int(len(mems & (e1030 | yz10)) >= 1)
                rec = (rk, kpl_sz, n10, n20, tot_zt, has_10yz, has_10e1030, raw_pn)
                for tok in tokens:
                    prev = kpl_t0_plate_stats.get((dt_k, tok))
                    if prev is None or (rec[4], -rec[0]) > (prev[4], -prev[0]):
                        kpl_t0_plate_stats[(dt_k, tok)] = rec
                for c6 in mems:
                    cur = kpl_t0_stock_direct.get((dt_k, c6))
                    if cur is None or (rec[4], -rec[0]) > (cur[4], -cur[0]):
                        kpl_t0_stock_direct[(dt_k, c6)] = rec
                    kpl_by_dt_code[(dt_k, c6)].extend(tokens)
                for tok in tokens:
                    prev_m = kpl_by_dt_plate.get((dt_k, tok))
                    if prev_m is None:
                        kpl_by_dt_plate[(dt_k, tok)] = set(mems)
                    else:
                        prev_m |= mems
            for c6 in mems:
                hist_kpl[c6].append((dt_k, tokens))
    del kpl_objs

    hist_dts = {c6: [x[0] for x in v] for c6, v in hist_kpl.items()}
    n = len(cand)
    k_has_hist = np.zeros(n, dtype=np.float32)
    k_rk_all = np.full(n, 99.0, dtype=np.float32)
    k_zt_all = np.zeros(n, dtype=np.float32)
    k_10yz_all = np.zeros(n, dtype=np.float32)
    k_10e1030_all = np.zeros(n, dtype=np.float32)
    k_rk_365 = np.full(n, 99.0, dtype=np.float32)
    k_zt_365 = np.zeros(n, dtype=np.float32)
    k_rk_180 = np.full(n, 99.0, dtype=np.float32)
    k_zt_180 = np.zeros(n, dtype=np.float32)
    k_plate_all = [""] * n
    k_toks_all = [None] * n

    shift_cache = {}
    for i, (c6, dt) in enumerate(zip(cand["code"], cand["sig_date"])):
        if dt not in shift_cache:
            shift_cache[dt] = (dk.shift_cal(dt, -365), dk.shift_cal(dt, -180))
        d365, d180 = shift_cache[dt]

        dir_rec = kpl_t0_stock_direct.get((dt, c6))
        hd = hist_dts.get(c6)
        toks_all = set()
        if hd:
            hi = bisect.bisect_left(hd, dt)
            if hi > 0:
                k_has_hist[i] = 1.0
                toks_365, toks_180 = set(), set()
                lo365 = bisect.bisect_left(hd, d365)
                lo180 = bisect.bisect_left(hd, d180)
                hk_c = hist_kpl[c6]
                for j in range(0, hi):
                    tk = hk_c[j][1]
                    toks_all |= tk
                    if j >= lo365:
                        toks_365 |= tk
                    if j >= lo180:
                        toks_180 |= tk
                best_a = None
                for tok in toks_all:
                    rec = kpl_t0_plate_stats.get((dt, tok))
                    if rec and (best_a is None or (rec[4], -rec[0]) > (best_a[4], -best_a[0])):
                        best_a = rec
                if best_a:
                    k_rk_all[i], _, _, _, k_zt_all[i], k_10yz_all[i], k_10e1030_all[i], k_plate_all[i] = (
                        float(best_a[0]), 0, 0, 0, float(best_a[4]), float(best_a[5]), float(best_a[6]), best_a[7]
                    )
                best_365 = None
                for tok in toks_365:
                    rec = kpl_t0_plate_stats.get((dt, tok))
                    if rec and (best_365 is None or (rec[4], -rec[0]) > (best_365[4], -best_365[0])):
                        best_365 = rec
                if best_365:
                    k_rk_365[i], k_zt_365[i] = float(best_365[0]), float(best_365[4])
                best_180 = None
                for tok in toks_180:
                    rec = kpl_t0_plate_stats.get((dt, tok))
                    if rec and (best_180 is None or (rec[4], -rec[0]) > (best_180[4], -best_180[0])):
                        best_180 = rec
                if best_180:
                    k_rk_180[i], k_zt_180[i] = float(best_180[0]), float(best_180[4])

        if dir_rec is not None and dir_rec[4] > k_zt_all[i]:
            k_rk_all[i] = float(dir_rec[0])
            k_zt_all[i] = float(dir_rec[4])
            k_10yz_all[i] = float(dir_rec[5])
            k_10e1030_all[i] = float(dir_rec[6])
            k_plate_all[i] = dir_rec[7]
            toks_all |= dk.split_norm_plates(dir_rec[7])
        k_toks_all[i] = toks_all

    kpl_feats = pd.DataFrame({
        "kpl_has_hist_t0": k_has_hist,
        "der_kpl_rank_eff": k_rk_all,
        "kpl_zt_cnt_t0": k_zt_all,
        "kpl_10yz_t0": k_10yz_all,
        "kpl_10e1030_t0": k_10e1030_all,
        "kpl_rk_365_t0": k_rk_365,
        "kpl_zt_365_t0": k_zt_365,
        "kpl_rk_180_t0": k_rk_180,
        "kpl_zt_180_t0": k_zt_180,
        "der_is_strong_mainline": ((k_rk_all <= 3.0) & (k_zt_all >= 5.0)).astype(np.float32),
        "der_is_super_climax": ((k_rk_all <= 3.0) & (k_zt_all >= 10.0)).astype(np.float32),
        "der_is_warm_theme": (k_zt_all >= 3.0).astype(np.float32),
    })
    cand = pd.concat([cand, kpl_feats], axis=1)
    cand["tmp_kpl_plate_t0"] = k_plate_all
    cand["tmp_kpl_toks_t0"] = k_toks_all
    return cand, kpl_by_dt_plate, kpl_by_dt_code


def build_w2b1_candidate_pool(end_cutoff: str = "2026-11-25", save_parquet: bool = True) -> tuple[pd.DataFrame, dict]:
    t0 = time.time()
    os.makedirs(OUT_DIR, exist_ok=True)

    # 1. Load market daily 119 PIT factors + benchmark calendar
    mkt = pd.read_parquet(f"{WAVE1}/market_daily_all_new_factors_pit.parquet")
    mkt["trade_date"] = mkt["trade_date"].astype(str).str[:10]
    mkt = mkt[mkt["trade_date"] <= end_cutoff].sort_values("trade_date").reset_index(drop=True)
    cal_dts = mkt["trade_date"].tolist()
    cal_pos = {d: i for i, d in enumerate(cal_dts)}

    bench = pd.read_parquet(f"{WAVE1}/v20_daily_bench_20210104_20261125.parquet")
    bench["trade_date"] = bench["trade_date"].astype(str).str[:10]
    bench = bench[bench["trade_date"] <= end_cutoff].sort_values("trade_date").reset_index(drop=True)
    csi_r = bench["csi300_daily_ret"].to_numpy(float)
    csi_nav = np.cumprod(1.0 + csi_r)
    csi_3d = np.zeros(len(csi_nav), dtype=np.float32)
    if len(csi_nav) > 3:
        csi_3d[3:] = (csi_nav[3:] / csi_nav[:-3] - 1.0) * 100.0
    csi3d_map = dict(zip(bench["trade_date"], csi_3d))

    # 2. Scan 1: streaming batch scan for is_20cm == 1 (~200 MB RAM)
    d20 = _stream_parquet_filtered(
        f"{WAVE1}/stock_day_core_features_pit.parquet",
        columns=list(dict.fromkeys(SD_BAR_COLS + ["is_20cm"])),
        cond_fn=lambda d: (d["is_20cm"] == 1) & (d["dt"].astype(str).str[:10] <= end_cutoff),
    ).drop(columns=["is_20cm"])
    d20["c6"] = d20["c6"].astype(str).str.zfill(6)
    d20["dt"] = d20["dt"].astype(str).str[:10]
    d20 = d20.sort_values(["c6", "dt"]).reset_index(drop=True)

    c6_arr = d20["c6"].to_numpy()
    brk = np.flatnonzero(c6_arr[1:] != c6_arr[:-1]) + 1
    starts = np.concatenate(([0], brk))
    ends = np.concatenate((brk, [len(d20)]))

    turn_arr = d20["turn_pct"].to_numpy(np.float32)
    turn_pct250 = _causal_pct_rank_250(turn_arr, starts, ends)

    adj_c = d20["close"].to_numpy(np.float64) * d20["adj_factor"].to_numpy(np.float64)
    adj_h = d20["high"].to_numpy(np.float64) * d20["adj_factor"].to_numpy(np.float64)
    ret1 = d20["ret_1d"].to_numpy(np.float32)
    is_big10 = ((ret1 >= 10.0) & (d20["is_st_pit"].to_numpy() == 0)).astype(np.float32)

    prev_ret5_pre = np.full(len(d20), np.nan, dtype=np.float32)
    big10_20d_pre = np.zeros(len(d20), dtype=np.float32)
    break60_t0 = np.zeros(len(d20), dtype=np.int8)
    break20_t0 = np.zeros(len(d20), dtype=np.int8)

    for s, e in zip(starts, ends):
        m = e - s
        if m > 6:
            prev_ret5_pre[s + 6 : e] = (adj_c[s + 5 : e - 1] / adj_c[s : e - 6] - 1.0) * 100.0
        if m > 1:
            cs_b = np.concatenate(([0.0], np.cumsum(is_big10[s:e])))
            for i in range(1, m):
                lo = max(0, i - 20)
                big10_20d_pre[s + i] = cs_b[i] - cs_b[lo]
            hi_sub = adj_h[s:e]
            if m >= 21:
                w20 = np.lib.stride_tricks.sliding_window_view(hi_sub[:-1], 20)
                break20_t0[s + 20 : e] = (hi_sub[20:] >= w20.max(axis=1) - 1e-4).astype(np.int8)
            for i in range(5, min(m, 20)):
                if hi_sub[i] >= hi_sub[:i].max() - 1e-4:
                    break20_t0[s + i] = 1
            if m >= 61:
                w60 = np.lib.stride_tricks.sliding_window_view(hi_sub[:-1], 60)
                break60_t0[s + 60 : e] = (hi_sub[60:] >= w60.max(axis=1) - 1e-4).astype(np.int8)
            for i in range(20, min(m, 60)):
                if hi_sub[i] >= hi_sub[:i].max() - 1e-4:
                    break60_t0[s + i] = 1
    del adj_c, adj_h, is_big10

    c6_20_set = set(d20["c6"].unique())
    st_tl, _, _ = dk.build_st_tox_reg_timelines(c6_20_set, c6_20_set, end_cutoff)

    dt_pos_arr = pd.Series(d20["dt"]).map(cal_pos).fillna(-1).to_numpy(np.int32)
    f1_dt = d20.groupby("c6", sort=False)["dt"].shift(-1).fillna("")
    f1_pos = np.empty(len(d20), dtype=np.int32)
    f1_pos[:-1] = np.where(c6_arr[1:] == c6_arr[:-1], dt_pos_arr[1:], -1)
    f1_pos[-1] = -1
    f1_open_pct = d20.groupby("c6", sort=False)["open_pct"].shift(-1).to_numpy(np.float32)
    f1_ret_1d = d20.groupby("c6", sort=False)["ret_1d"].shift(-1).to_numpy(np.float32)
    f1_open = d20.groupby("c6", sort=False)["open"].shift(-1).to_numpy(np.float32)
    f1_close = d20.groupby("c6", sort=False)["close"].shift(-1).to_numpy(np.float32)
    f1_is_st = d20.groupby("c6", sort=False)["is_st_pit"].shift(-1).fillna(1).to_numpy(np.int8)
    f1_is_yizi_zt = d20.groupby("c6", sort=False)["is_yizi_zt"].shift(-1).fillna(1).to_numpy(np.int8)

    cand_mask = (
        (d20["dt"].to_numpy() >= "2021-01-04")
        & (d20["is_st_pit"].to_numpy() == 0)
        & (f1_is_st == 0)
        & (d20["list_age"].to_numpy() > 5)
        & (d20["close"].to_numpy() >= 2.0)
        & (ret1 >= 10.0)
        & (ret1 <= 19.8)
        & (d20["is_zt"].to_numpy() == 0)
        & (f1_pos == dt_pos_arr + 1)
        & (f1_open > 0)
        & (f1_close > 0)
        & (np.abs(f1_ret_1d) <= 22.0)
    )
    cand_idx = np.flatnonzero(cand_mask)
    st_clean = dk._compute_clean_st_flags(st_tl, pd.Series(c6_arr[cand_idx]), pd.Series(d20["dt"].to_numpy()[cand_idx]), pd.Series(f1_dt.to_numpy()[cand_idx]))
    cand_idx = cand_idx[st_clean]
    f1_idx = cand_idx + 1

    hl = np.maximum(d20["high"].to_numpy(np.float64)[cand_idx] - d20["low"].to_numpy(np.float64)[cand_idx], 1e-6)
    o_t0 = d20["open"].to_numpy(np.float64)[cand_idx]
    h_t0 = d20["high"].to_numpy(np.float64)[cand_idx]
    l_t0 = d20["low"].to_numpy(np.float64)[cand_idx]
    c_t0 = d20["close"].to_numpy(np.float64)[cand_idx]
    pc_t0 = np.maximum(d20["prev_close_raw"].to_numpy(np.float64)[cand_idx], 1e-6)

    upper_shad_hl = ((h_t0 - np.maximum(o_t0, c_t0)) / hl).astype(np.float32)
    upper_shad_pc = ((h_t0 - np.maximum(o_t0, c_t0)) / pc_t0).astype(np.float32)
    lower_shad_hl = ((np.minimum(o_t0, c_t0) - l_t0) / hl).astype(np.float32)
    body_pct = ((c_t0 - o_t0) / pc_t0).astype(np.float32)
    body_ratio_hl = ((c_t0 - o_t0) / hl).astype(np.float32)
    amp_pct = (hl / pc_t0).astype(np.float32)
    hit_zt_t0 = d20["hit_zt"].to_numpy(np.int8)[cand_idx]
    is_type_b = (hit_zt_t0 == 1).astype(np.int8)
    is_type_a = ((hit_zt_t0 == 0) & (upper_shad_pc <= 0.03) & (c_t0 > o_t0) & (body_ratio_hl >= 0.55)).astype(np.int8)
    is_type_c = ((is_type_a == 0) & (is_type_b == 0)).astype(np.int8)

    cand = pd.DataFrame({
        "sig_date": d20["dt"].to_numpy()[cand_idx],
        "buy_date": d20["dt"].to_numpy()[f1_idx],
        "code": c6_arr[cand_idx],
        "t0_close": c_t0.astype(np.float32),
        "t0_open_pct": d20["open_pct"].to_numpy(np.float32)[cand_idx],
        "t0_ret_1d": ret1[cand_idx],
        "t0_turn_pct": turn_arr[cand_idx],
        "t0_turn_pct250": turn_pct250[cand_idx],
        "t0_upper_shad_hl": upper_shad_hl,
        "t0_upper_shad_pc": upper_shad_pc,
        "t0_lower_shad_hl": lower_shad_hl,
        "t0_body_pct": body_pct,
        "t0_body_ratio_hl": body_ratio_hl,
        "t0_amp_pct": amp_pct,
        "t0_hit_zt": hit_zt_t0.astype(np.float32),
        "der_is_type_a": is_type_a.astype(np.float32),
        "der_is_type_b": is_type_b.astype(np.float32),
        "der_is_type_c": is_type_c.astype(np.float32),
        "der_t0_break60": break60_t0[cand_idx].astype(np.float32),
        "der_t0_break20": break20_t0[cand_idx].astype(np.float32),
        "der_prev_ret5_pre": prev_ret5_pre[cand_idx],
        "der_big10_20d_pre": big10_20d_pre[cand_idx],
        "is_yizi": ((f1_is_yizi_zt[cand_idx] == 1) | (f1_open_pct[cand_idx] >= 19.5)).astype(bool),
    })

    # Build compact stock_series & IMMEDIATELY free full d20
    need_c6_set = set(cand["code"].unique())
    d20_sub = d20[d20["c6"].isin(need_c6_set)].reset_index(drop=True)
    del d20, prev_ret5_pre, big10_20d_pre, break60_t0, break20_t0, turn_pct250, turn_arr, ret1
    gc.collect()
    pa.default_memory_pool().release_unused()

    stock_series = {}
    for c6_v, grp in d20_sub.groupby("c6", sort=False):
        dts_a = grp["dt"].to_numpy()
        pc_a = grp["prev_close_raw"].to_numpy(np.float64)
        stock_series[c6_v] = {
            "dts": dts_a,
            "d2i": {d: idx for idx, d in enumerate(dts_a)},
            "open": grp["open"].to_numpy(np.float64),
            "high": grp["high"].to_numpy(np.float64),
            "low": grp["low"].to_numpy(np.float64),
            "close": grp["close"].to_numpy(np.float64),
            "adjf": grp["adj_factor"].to_numpy(np.float64),
            "prev_c": pc_a,
            "zt_px": np.round(pc_a * 1.20, 2),
            "dt_px": np.round(pc_a * 0.80, 2),
            "is_zt": grp["is_zt"].to_numpy(bool),
            "is_dt": grp["is_dt"].to_numpy(bool),
            "is_yizi_dt": grp["is_yizi_dt"].to_numpy(bool),
        }
    del d20_sub
    gc.collect()

    # 3. Scan 2: Streaming batch-filtered scan for SD_T1_PIT_COLS ONLY on (buy_date, code) pairs (< 25 MB!)
    buy_pairs = set(zip(cand["buy_date"], cand["code"]))
    buy_dts_set = set(cand["buy_date"].unique())
    cols_s2 = ["dt", "c6", "is_20cm"] + SD_T1_PIT_COLS
    pf_s2 = pq.ParquetFile(f"{WAVE1}/stock_day_core_features_pit.parquet")
    t1_parts = []
    for batch in pf_s2.iter_batches(batch_size=32768, columns=cols_s2, use_threads=False):
        bdf = batch.to_pandas()
        bdf = bdf[bdf["is_20cm"] == 1]
        if bdf.empty:
            continue
        bdf["dt"] = bdf["dt"].astype(str).str[:10]
        bdf = bdf[bdf["dt"].isin(buy_dts_set)]
        if bdf.empty:
            continue
        bdf["c6"] = bdf["c6"].astype(str).str.zfill(6)
        keep_m = [((d, c) in buy_pairs) for d, c in zip(bdf["dt"], bdf["c6"])]
        if any(keep_m):
            t1_parts.append(bdf.loc[keep_m].drop(columns=["is_20cm"]))
        del bdf
    t1_df = pd.concat(t1_parts, ignore_index=True).rename(columns={"dt": "buy_date", "c6": "code", "open_pct": "t1_open_pct"})
    del t1_parts, pf_s2
    gc.collect()
    pa.default_memory_pool().release_unused()

    cand = cand.merge(t1_df, on=["buy_date", "code"], how="left")
    del t1_df

    # 4. Causal KPL historical themes & 10cm/20cm same-theme 09:25 auction features
    cand, kpl_by_dt_plate, _ = _compute_causal_kpl_theme_features(cand, end_cutoff)

    sig_set = set(cand["sig_date"].unique())
    buy_set = set(cand["buy_date"].unique())
    sd_auc = _stream_parquet_filtered(
        f"{WAVE1}/stock_day_core_features_pit.parquet",
        columns=["dt", "c6", "open_pct", "is_20cm", "is_st_pit", "prev_streak", "csrc_ind_id", "amount_yi_t1"],
        cond_fn=lambda d: (d["prev_streak"] >= 1) & (d["is_st_pit"] == 0) & (d["dt"].astype(str).str[:10].isin(buy_set)),
    )
    sd_auc["dt"] = sd_auc["dt"].astype(str).str[:10]
    sd_auc["c6"] = sd_auc["c6"].astype(str).str.zfill(6)

    sd_by_dt = {}
    for dt_v, grp in sd_auc.groupby("dt", sort=False):
        m10, m20, by_ind10, all_lb10 = {}, {}, {}, []
        for r in grp.itertuples(index=False):
            tup = (float(r.open_pct), int(r.prev_streak), float(r.amount_yi_t1 or 0.0), int(r.csrc_ind_id))
            if r.is_20cm == 0:
                m10[r.c6] = tup
                by_ind10.setdefault(int(r.csrc_ind_id), []).append(tup)
                if r.prev_streak >= 2:
                    all_lb10.append(tup)
            else:
                m20[r.c6] = tup
        sd_by_dt[dt_v] = (m10, m20, by_ind10, all_lb10)
    del sd_auc
    gc.collect()

    auc_rows = []
    theme_group_key = []
    for r in cand.itertuples(index=False):
        bd, sdt, ck = r.buy_date, r.sig_date, r.code
        ind_id = int(r.csrc_ind_id) if pd.notna(r.csrc_ind_id) else -1
        m10, m20, by_ind10, all_lb10 = sd_by_dt.get(bd, ({}, {}, {}, []))
        toks = r.tmp_kpl_toks_t0 or set()
        pl_name = r.tmp_kpl_plate_t0
        theme_group_key.append(pl_name if pl_name else f"IND_{ind_id}")

        peers10, peers20 = {}, {}
        for tok in toks:
            for pc in kpl_by_dt_plate.get((sdt, tok), ()):
                if pc in m10:
                    peers10[pc] = m10[pc]
                if pc != ck and pc in m20:
                    peers20[pc] = m20[pc]
        p10_list = list(peers10.values())
        if not p10_list and ind_id in by_ind10:
            p10_list = by_ind10[ind_id]

        if p10_list:
            max_stk = max(x[1] for x in p10_list)
            ldr_op = float(np.mean([x[0] for x in p10_list if x[1] == max_stk]))
            lb_list = [x for x in p10_list if x[1] >= 2]
            lb_ldr_op = float(np.mean([x[0] for x in lb_list if x[1] == max(y[1] for y in lb_list)])) if lb_list else np.nan
            p10_mean = float(np.mean([x[0] for x in p10_list]))
            n10 = len(p10_list)
            nuke_r = sum(1 for x in p10_list if x[0] <= -5.0) / n10
            strong_r = sum(1 for x in p10_list if x[0] >= 5.0) / n10
            has_yizi10 = float(any(x[0] >= 9.5 for x in p10_list))
        else:
            max_stk, ldr_op, lb_ldr_op, p10_mean = 0.0, np.nan, np.nan, np.nan
            n10, nuke_r, strong_r, has_yizi10 = 0, np.nan, np.nan, 0.0

        p20_list = list(peers20.values())
        has_yizi20_thm = float(any(x[0] >= 19.5 for x in p20_list)) if p20_list else 0.0
        p20_mean = float(np.mean([x[0] for x in p20_list])) if p20_list else np.nan

        if all_lb10:
            m_stk = max(x[1] for x in all_lb10)
            mkt_ldr_op = float(np.mean([x[0] for x in all_lb10 if x[1] == m_stk]))
            mkt_nuke_r = sum(1 for x in all_lb10 if x[0] <= -5.0) / len(all_lb10)
        else:
            mkt_ldr_op, mkt_nuke_r = np.nan, np.nan

        own_op = float(r.t1_open_pct)
        auc_rows.append({
            "auc_thm10_n_peers": float(n10),
            "auc_thm10_max_streak": float(max_stk),
            "auc_thm10_ldr_open_pct": ldr_op,
            "auc_thm10_lb_ldr_open_pct": lb_ldr_op,
            "auc_thm10_peer_mean_open": p10_mean,
            "auc_thm10_nuke_ratio": nuke_r,
            "auc_thm10_strong_ratio": strong_r,
            "auc_thm10_has_yizi_open": has_yizi10,
            "auc_thm20_has_yizi_open": has_yizi20_thm,
            "auc_thm20_peer_mean_open": p20_mean,
            "auc_mkt10_ldr_open_pct": mkt_ldr_op,
            "auc_mkt10_lb_nuke_ratio": mkt_nuke_r,
            "auc_rel_gap_vs_thm10": (own_op - ldr_op) if np.isfinite(ldr_op) else np.nan,
        })
    cand = pd.concat([cand.drop(columns=["tmp_kpl_plate_t0", "tmp_kpl_toks_t0"]), pd.DataFrame(auc_rows, dtype=np.float32)], axis=1)
    cand["_thm_key"] = theme_group_key
    cand["der_rk20_ret_in_theme"] = cand.groupby(["sig_date", "_thm_key"])["t0_ret_1d"].rank(ascending=False, method="min").astype(np.float32)
    cand["der_rk20_amt_in_theme"] = cand.groupby(["sig_date", "_thm_key"])["amount_yi_t1"].rank(ascending=False, method="min").astype(np.float32)
    cand = cand.drop(columns=["_thm_key"])

    # 5. Merge 119 market PIT factors on buy_date
    cand = cand.merge(mkt, left_on="buy_date", right_on="trade_date", how="left").drop(columns=["trade_date"])

    # 6. Derived mechanism features
    t1_op = cand["t1_open_pct"].to_numpy(np.float32)
    t0_ret = cand["t0_ret_1d"].to_numpy(np.float32)
    r5_t0 = cand["ret_5d_t1"].to_numpy(np.float32)
    csi3d_t0 = cand["sig_date"].map(csi3d_map).fillna(0.0).to_numpy(np.float32)

    der_extra = pd.DataFrame({
        "der_open_abs": np.abs(t1_op).astype(np.float32),
        "der_open_vs_t0_ret": (t1_op - t0_ret).astype(np.float32),
        "auc_rel_gap_vs_mkt": (t1_op - cand["mkt_0925_avg_gap_pct"].to_numpy(np.float32)).astype(np.float32),
        "der_t0_amt_vs_mkt": (cand["amount_yi_t1"].to_numpy(np.float32) / np.maximum(cand["mkt_amt_tril_t1"].to_numpy(np.float32), 0.1)).astype(np.float32),
        "der_mkt20_share_zt": (cand["mkt20_zt_cnt_t1"].to_numpy(np.float32) / np.maximum(cand["L1_zt_cnt_t1"].to_numpy(np.float32), 1.0)).astype(np.float32),
        "der_kpl_zt_x_open": (cand["kpl_zt_cnt_t0"].to_numpy(np.float32) * t1_op).astype(np.float32),
        "der_first_wave_flag": ((cand["der_prev_ret5_pre"] <= 5.0) & (cand["der_big10_20d_pre"] == 0)).astype(np.float32),
        "der_dist_5d_vs_csi3d": (30.0 - (r5_t0 - csi3d_t0)).astype(np.float32),
        "der_amt_ge_1e8": (cand["amount_yi_t1"] >= 1.0).astype(np.float32),
        "der_amt_ge_5e8": (cand["amount_yi_t1"] >= 5.0).astype(np.float32),
        "der_t0_upper_x_open": (cand["t0_upper_shad_pc"].to_numpy(np.float32) * t1_op).astype(np.float32),
        "der_small_fmcap_x_kpl": ((cand["free_mcap_yi_t1"] <= 25.0) & (cand["kpl_zt_cnt_t0"] >= 5.0)).astype(np.float32),
        "der_ice_deep_open": ((cand["L1_sent_phase_t1"] <= 1) & (t1_op <= -1.0)).astype(np.float32),
    })
    cand = pd.concat([cand, der_extra], axis=1)

    # 7. Simulate 3 exits
    mkt_tp1_risk = {
        str(r.trade_date): (float(r.L1_dt_cnt_t1) >= 20.0 or float(r.mkt20_dt_cnt_t1) >= 3.0)
        for r in mkt.itertuples(index=False)
    }
    cand = _simulate_3exits_for_candidates(cand, stock_series, mkt_tp1_risk)
    del stock_series
    gc.collect()

    non_feat_prefixes = ("X1_", "X2_", "X3_")
    non_feat_exact = {"sig_date", "buy_date", "code", "t0_close", "is_yizi", "csrc_ind_id"}
    feature_cols = [
        c for c in cand.columns
        if c not in non_feat_exact
        and not c.startswith(non_feat_prefixes)
        and pd.api.types.is_numeric_dtype(cand[c])
        and cand[c].isna().mean() <= 0.55
        and cand[c].nunique(dropna=True) >= 2
    ]

    rss_mb = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 1)
    meta = {
        "end_cutoff": end_cutoff,
        "n_candidates": int(len(cand)),
        "n_buyable_e1": int((~cand["is_yizi"]).sum()),
        "n_strong_mainline": int((cand["der_is_strong_mainline"] == 1).sum()),
        "n_super_climax": int((cand["der_is_super_climax"] == 1).sum()),
        "n_type_a": int((cand["der_is_type_a"] == 1).sum()),
        "n_type_b": int((cand["der_is_type_b"] == 1).sum()),
        "n_type_c": int((cand["der_is_type_c"] == 1).sum()),
        "n_features": int(len(feature_cols)),
        "feature_cols": feature_cols,
        "peak_rss_mb": rss_mb,
        "elapsed_sec": round(time.time() - t0, 2),
    }

    if save_parquet:
        cand.to_parquet(f"{OUT_DIR}/w2b1_cand_pool_pit.parquet", index=False)
        with open(f"{OUT_DIR}/w2b1_feature_catalog.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"[W2B-1 Pool <= {end_cutoff}] N={len(cand):,} | E1_buyable={meta['n_buyable_e1']:,} | "
          f"Strong={meta['n_strong_mainline']:,} Climax={meta['n_super_climax']:,} "
          f"A={meta['n_type_a']:,} B={meta['n_type_b']:,} | Features={len(feature_cols)} | RSS={rss_mb}MB in {meta['elapsed_sec']}s")
    return cand, meta


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cutoff", default="2026-11-25")
    ap.add_argument("--verify-trunc-only", action="store_true")
    args = ap.parse_args()

    if args.verify_trunc_only:
        cand_full = pd.read_parquet(f"{OUT_DIR}/w2b1_cand_pool_pit.parquet")
        meta_full = json.load(open(f"{OUT_DIR}/w2b1_feature_catalog.json", encoding="utf-8"))
        cand_trunc, _ = build_w2b1_candidate_pool("2024-12-31", save_parquet=False)
        f_le = cand_full[cand_full["buy_date"] <= "2024-12-31"].sort_values(["buy_date", "code"]).reset_index(drop=True)
        t_le = cand_trunc[cand_trunc["buy_date"] <= "2024-12-31"].sort_values(["buy_date", "code"]).reset_index(drop=True)
        assert len(f_le) == len(t_le), f"Row mismatch: {len(f_le)} vs {len(t_le)}"
        max_f_diff = 0.0
        for c in meta_full["feature_cols"]:
            vf = f_le[c].fillna(-999999.0).to_numpy(np.float64)
            vt = t_le[c].fillna(-999999.0).to_numpy(np.float64)
            d = float(np.max(np.abs(vf - vt)))
            if d > max_f_diff:
                max_f_diff = d
        max_r_diff = 0.0
        for ex in ("X1_T1_Close", "X2_T2_Close", "X3_20cm_4Branch"):
            m_ex = (f_le[f"{ex}__exit_date"].astype(str) <= "2024-12-31").to_numpy()
            rf = f_le.loc[m_ex, f"{ex}__net_ret"].fillna(-999.0).to_numpy(np.float64)
            rt = t_le.loc[m_ex, f"{ex}__net_ret"].fillna(-999.0).to_numpy(np.float64)
            max_r_diff = max(max_r_diff, float(np.max(np.abs(rf - rt))))
        rss_mb = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 1)
        print(f"[Data Truncation Proof <= 2024-12-31] rows={len(f_le):,}, max_feat_diff={max_f_diff}, max_ret_diff={max_r_diff}, RSS={rss_mb}MB")
        assert max_f_diff == 0.0 and max_r_diff == 0.0
    else:
        build_w2b1_candidate_pool(args.cutoff, save_parquet=True)

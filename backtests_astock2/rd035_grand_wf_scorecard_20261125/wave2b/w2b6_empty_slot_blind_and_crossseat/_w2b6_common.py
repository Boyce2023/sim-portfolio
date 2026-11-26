#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 2B-6 Common Utilities (Low-Memory Streaming Edition < 1.2 GB RSS):
  - Single-thread & zero-yfinance D12 guards
  - Streaming PyArrow batch reader + compact int16/int32 categorical PriceReturnIndex (~250 MB RAM)
  - Strict PIT feature joiner (buy_at='open' vs 'close' zero-leakage feature whitelist)
  - Exact daily MTM evaluator + V20 correlation + 2024-12-31 physical truncation checker
"""
import os

for _env_k in (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
):
    os.environ[_env_k] = "1"

import gc
import math
import resource
import sys
import warnings
from typing import Optional

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

pa.set_cpu_count(1)
pa.set_io_thread_count(1)
pa.set_memory_pool(pa.system_memory_pool())

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True
warnings.filterwarnings("ignore", category=FutureWarning)

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM_DIR = f"{ROOT}/sim-portfolio"
DATA_DIR = f"{SIM_DIR}/data"
BASE_DIR = f"{SIM_DIR}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
OUT_DIR = f"{SIM_DIR}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave2b/w2b6_empty_slot_blind_and_crossseat"
os.makedirs(OUT_DIR, exist_ok=True)

if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import wf_scorecard_engine as wf

STOCK_DAY_PQ = f"{BASE_DIR}/stock_day_core_features_pit.parquet"
MKT_DAY_PQ = f"{BASE_DIR}/market_daily_all_new_factors_pit.parquet"

STOCK_OPEN_FEATURES = [
    "open_pct", "is_20cm",
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
    "kpl_zt3_t1", "kpl_days_30d_t1", "kpl_in_t1", "kpl_rank_t1", "kpl_zt1_t1", "kpl_streak_t1",
    "csrc_ind_ex5_t1", "csrc_ind_ex20_t1", "csrc_ind_rank20_t1",
    "csrc_ind_zt_share5_t1", "csrc_ind_amt_pct250_t1",
    "tox_reg_30d_pre", "abn_notice_30d_pre", "ir_cnt_30d_pre",
    "comm_ring_tier", "comm_driver_ret20_t1", "comm_driver_pct5y_t1",
]

STOCK_CLOSE_EXTRA_FEATURES = [
    "ret_1d", "clv", "amount_yi", "turn_pct", "hit_zt", "is_broken_zt", "streak",
]

MKT_PIT_FEATURES = [
    "L1_zt_cnt_t1", "L1_nat_zt_cnt_t1", "L1_dt_cnt_t1", "L1_zt_dt_logratio_t1",
    "L1_zb_rate_t1", "L1_max_board_t1", "L1_lianban_cnt_t1", "L1_zt_prem_t1",
    "L1_lb_promo_t1", "L1_duanban_damian_t1", "L1_zt_mom3v20_t1", "L1_zt_pct60_t1",
    "L1_sent_phase_t1", "L1_smb_5d_t1", "L1_smb_20d_t1", "L1_breadth_5d_t1",
    "L1_breadth_20d_t1", "L1_amt_ratio20_t1", "L1_amt_ratio5v60_t1",
    "L1_ew_bias20_t1", "L1_ew_bias60_t1", "L1_ew_ret20_t1", "L1_ew_vol20_t1",
    "L1_ew_pos60_t1", "L1_csi_bias60_t1", "L1_is_earn_win", "L1_is_month_end3",
    "L1_is_pre_hol2", "L1_weekday",
    "mkt20_zt_cnt_t1", "mkt_amt_tril_t1", "mkt_0925_zt_cnt", "mkt_0925_avg_gap_pct",
    "th_style_shell_spread_20d_t1", "th_style_rev_20d_spread_t1", "th_style_mom_60d_spread_t1",
    "mkt_bank_vs_tech_ret_t1", "mkt_csi300_ret1d_t1", "mkt_csi1000_ret1d_t1",
    "mkt_pct_above_ma20_t1", "mkt_pct_above_ma60_t1", "mkt_turn_pct_3y_t1",
    "mkt_erp_csi300_pct_5y_t1", "th_style_ice_point_sig_t1",
    "nt_v3_score_eod_t1", "nt_etf22_amt_spike_t1", "nt_if0_basis_pct_t1",
    "us_ixic_ret1d_on", "us_ixic_ret5d_on", "us_gspc_ret1d_on", "us_rut_ret1d_on",
    "us_vix_level_on", "us_vix_chg1d_on", "us_tnx_chg5d_on", "us_dxy_ret5d_on",
    "comm_au_ret5d_t1", "comm_cu_ret5d_t1", "comm_cn_ew_ret5d_t1",
    "wp_net_trading_pct_5y_pit", "pol_rescue_signal_10d", "pol_crackdown_signal_10d",
]


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


def peak_rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 2)


class PriceReturnIndex:
    """Compact ~240 MB categorical-indexed stock bar arrays for fast exact forward exits & daily MTM."""

    def __init__(self, end_cutoff: str = "2026-11-25"):
        cols = [
            "c6", "dt", "open", "close", "adj_factor",
            "is_dt", "is_zt", "is_yizi_zt", "is_yizi_dt", "is_st_pit", "is_20cm",
            "open_pct", "ret_1d", "amount_yi",
        ]
        pf = pq.ParquetFile(STOCK_DAY_PQ)
        chunks = []
        for i_b, batch in enumerate(pf.iter_batches(batch_size=100_000, columns=cols)):
            b_df = batch.to_pandas(categories=["c6", "dt"])
            dt_cats = b_df["dt"].cat.categories.astype(str).str[:10]
            valid_dc = set(np.flatnonzero(dt_cats <= end_cutoff))
            if len(valid_dc) < len(dt_cats):
                b_df = b_df[b_df["dt"].cat.codes.isin(valid_dc)].copy()
            chunks.append(b_df)
            if i_b % 10 == 0:
                pa.default_memory_pool().release_unused()
        df = pd.concat(chunks, ignore_index=True)
        del chunks
        pa.default_memory_pool().release_unused()
        gc.collect()

        # Note: df from step2 is already sorted by ['c6', 'dt']; verify & build integer maps
        c6_cats = [str(x).zfill(6) for x in df["c6"].cat.categories]
        dt_cats = [str(x)[:10] for x in df["dt"].cat.categories]
        self.c6_list = np.array(c6_cats, dtype=object)
        self.c6_to_id = {c: i for i, c in enumerate(c6_cats)}
        self.dt_list = np.array(dt_cats, dtype=object)
        self.dt_to_id = {d: i for i, d in enumerate(dt_cats)}

        self.c6_id = df["c6"].cat.codes.to_numpy(np.int32)
        self.dt_id = df["dt"].cat.codes.to_numpy(np.int16)
        self.open = df["open"].to_numpy(np.float32)
        self.close = df["close"].to_numpy(np.float32)
        self.adj_factor = df["adj_factor"].to_numpy(np.float32)
        self.is_dt = df["is_dt"].to_numpy(np.int8)
        self.is_zt = df["is_zt"].to_numpy(np.int8)
        self.is_yizi_zt = df["is_yizi_zt"].to_numpy(np.int8)
        self.is_yizi_dt = df["is_yizi_dt"].to_numpy(np.int8)
        self.is_st = df["is_st_pit"].to_numpy(np.int8)
        self.is_20cm = df["is_20cm"].to_numpy(np.int8)
        self.open_pct = df["open_pct"].to_numpy(np.float32)
        self.ret_1d = df["ret_1d"].to_numpy(np.float32)
        self.amount_yi = df["amount_yi"].to_numpy(np.float32)

        del df
        gc.collect()

        # Verify c6_id grouped contiguously (sort if needed)
        brk = np.flatnonzero(self.c6_id[1:] != self.c6_id[:-1]) + 1
        starts = np.concatenate(([0], brk))
        ends = np.concatenate((brk, [len(self.c6_id)]))
        self.bounds = {}
        for s, e in zip(starts, ends):
            cid = int(self.c6_id[s])
            # Ensure dt_id sorted within slice
            if e - s > 1 and np.any(self.dt_id[s + 1 : e] <= self.dt_id[s : e - 1]):
                order = np.argsort(self.dt_id[s:e], kind="mergesort")
                for arr in (
                    self.dt_id, self.open, self.close, self.adj_factor,
                    self.is_dt, self.is_zt, self.is_yizi_zt, self.is_yizi_dt,
                    self.is_st, self.is_20cm, self.open_pct, self.ret_1d, self.amount_yi,
                ):
                    arr[s:e] = arr[s:e][order]
            self.bounds[cid] = (int(s), int(e))

    def lookup_forward_returns(
        self,
        pairs_df: pd.DataFrame,
        horizons: tuple[int, ...] = (1, 2, 3, 5),
        buy_at: str = "open",
        min_amt_yi: float = 0.0,
    ) -> pd.DataFrame:
        codes = pairs_df["code"].astype(str).str.zfill(6).to_numpy()
        dates = pairs_df["buy_date"].astype(str).str[:10].to_numpy()
        n = len(codes)

        buy_ok = np.zeros(n, dtype=bool)
        out = pairs_df.copy().reset_index(drop=True)
        out["code"] = codes
        out["buy_date"] = dates
        out["buy_hhmm"] = 925 if buy_at == "open" else 1500
        out["exit_hhmm"] = 1500

        res_exit = {h: np.empty(n, dtype=object) for h in horizons}
        res_ret = {h: np.full(n, np.nan, dtype=np.float64) for h in horizons}
        for h in horizons:
            res_exit[h][:] = ""

        by_c = {}
        for idx, c in enumerate(codes):
            cid = self.c6_to_id.get(c, -1)
            if cid >= 0:
                by_c.setdefault(cid, []).append(idx)

        for cid, idxs in by_c.items():
            bnd = self.bounds.get(cid)
            if bnd is None:
                continue
            s, e = bnd
            dt_sub = self.dt_id[s:e]
            for i in idxs:
                did = self.dt_to_id.get(dates[i], -1)
                if did < 0:
                    continue
                rel = int(np.searchsorted(dt_sub, did))
                if rel >= len(dt_sub) or int(dt_sub[rel]) != did:
                    continue
                pos = s + rel
                if self.is_st[pos] != 0 or self.is_yizi_zt[pos] != 0 or self.is_yizi_dt[pos] != 0:
                    continue
                if min_amt_yi > 0 and (not np.isfinite(self.amount_yi[pos]) or self.amount_yi[pos] < min_amt_yi):
                    continue
                if buy_at == "open":
                    lim = 19.5 if self.is_20cm[pos] else 9.7
                    op = self.open_pct[pos]
                    if not np.isfinite(op) or op >= lim or op <= -lim:
                        continue
                    b_px = float(self.open[pos]) * float(self.adj_factor[pos])
                else:
                    if self.is_zt[pos] != 0 or self.is_dt[pos] != 0:
                        continue
                    b_px = float(self.close[pos]) * float(self.adj_factor[pos])
                if not np.isfinite(b_px) or b_px <= 0:
                    continue
                buy_ok[i] = True

                for h in horizons:
                    ex_pos = pos + h
                    if ex_pos >= e:
                        continue
                    lim_wait = min(e - 1, ex_pos + 5)
                    while ex_pos < lim_wait and self.is_dt[ex_pos] != 0:
                        ex_pos += 1
                    ex_px = float(self.close[ex_pos]) * float(self.adj_factor[ex_pos])
                    if not np.isfinite(ex_px) or ex_px <= 0:
                        continue
                    res_exit[h][i] = str(self.dt_list[int(self.dt_id[ex_pos])])
                    res_ret[h][i] = float(ex_px / b_px - 1.0)

        out["can_buy"] = buy_ok
        out["is_yizi"] = ~buy_ok
        for h in horizons:
            out[f"exit_date_h{h}"] = res_exit[h]
            out[f"gross_ret_h{h}"] = res_ret[h]
        return out

    def compute_exact_mtm_series(
        self,
        trades_df: pd.DataFrame,
        cal_dts: list[str],
        buy_at: str = "open",
        fee_rt: float = 0.0030,
    ) -> tuple[np.ndarray, float]:
        T = len(cal_dts)
        if trades_df.empty:
            return np.zeros(T, dtype=float), 0.0
        dt_idx = {d: i for i, d in enumerate(cal_dts)}
        day_mult = np.ones(T, dtype=np.float64)
        f_buy = fee_rt * 0.5
        f_sell_mult = (1.0 - fee_rt) / (1.0 - f_buy)

        for r in trades_df.itertuples(index=False):
            c = str(r.code).zfill(6)
            bd = str(r.buy_date)[:10]
            ed = str(r.exit_date)[:10]
            cid = self.c6_to_id.get(c, -1)
            did0 = self.dt_to_id.get(bd, -1)
            did1 = self.dt_to_id.get(ed, -1)
            if cid < 0 or did0 < 0 or did1 < 0:
                continue
            bnd = self.bounds.get(cid)
            if bnd is None:
                continue
            s, e = bnd
            dt_sub = self.dt_id[s:e]
            p0 = int(np.searchsorted(dt_sub, did0))
            p1 = int(np.searchsorted(dt_sub, did1))
            if p0 >= len(dt_sub) or int(dt_sub[p0]) != did0 or p1 >= len(dt_sub) or int(dt_sub[p1]) != did1 or p1 <= p0:
                continue
            g0, g1 = s + p0, s + p1
            ti0 = dt_idx.get(str(self.dt_list[int(self.dt_id[g0])]))
            if ti0 is not None:
                if buy_at == "open":
                    m0 = (float(self.close[g0]) / float(self.open[g0])) * (1.0 - f_buy)
                else:
                    m0 = 1.0 - f_buy
                day_mult[ti0] *= m0
            for g in range(g0 + 1, g1 + 1):
                tig = dt_idx.get(str(self.dt_list[int(self.dt_id[g])]))
                if tig is None:
                    continue
                ac_cur = float(self.close[g]) * float(self.adj_factor[g])
                ac_prev = float(self.close[g - 1]) * float(self.adj_factor[g - 1])
                mg = ac_cur / ac_prev
                if g == g1:
                    mg *= f_sell_mult
                day_mult[tig] *= mg

        dr = day_mult - 1.0
        tr_sub = trades_df[trades_df["buy_date"].isin(dt_idx)]
        tr_nav = float(np.prod(1.0 + tr_sub["net_ret"].to_numpy(float))) if not tr_sub.empty else 1.0
        return dr, abs(float(np.prod(day_mult)) - tr_nav)


def attach_pit_features(
    cand_df: pd.DataFrame,
    buy_at: str = "open",
    extra_cols: Optional[list[str]] = None,
) -> tuple[pd.DataFrame, list[str]]:
    """
    Stream stock_day_core_features_pit.parquet in 300k batches, immediately keeping ONLY
    rows matching exact (buy_date, code) pairs in cand_df -> < 50 MB memory overhead!
    """
    df = cand_df.copy()
    df["buy_date"] = df["buy_date"].astype(str).str[:10]
    df["code"] = df["code"].astype(str).str.zfill(6)

    s_cols = list(STOCK_OPEN_FEATURES)
    if buy_at == "close":
        s_cols += STOCK_CLOSE_EXTRA_FEATURES
    read_cols = ["c6", "dt"] + [c for c in s_cols if c not in df.columns]

    pair_keys = pd.MultiIndex.from_arrays([df["buy_date"].to_numpy(), df["code"].to_numpy()])
    unique_pairs = set(pair_keys.tolist())
    dt_set = set(df["buy_date"].unique().tolist())

    pf = pq.ParquetFile(STOCK_DAY_PQ)
    matched_chunks = []
    for i_b, batch in enumerate(pf.iter_batches(batch_size=100_000, columns=read_cols)):
        b_df = batch.to_pandas(categories=["c6", "dt"])
        dt_cats = b_df["dt"].cat.categories.astype(str).str[:10]
        valid_dc = set(np.flatnonzero(dt_cats.isin(dt_set)))
        if not valid_dc:
            continue
        m_dt = b_df["dt"].cat.codes.isin(valid_dc).to_numpy()
        if not m_dt.any():
            continue
        b_sub = b_df.loc[m_dt].copy()
        c6_cats = b_sub["c6"].cat.categories.astype(str).str.zfill(6).to_numpy()
        dt_cats_arr = b_sub["dt"].cat.categories.astype(str).str[:10].to_numpy()
        b_c6 = c6_cats[b_sub["c6"].cat.codes.to_numpy()]
        b_d2 = dt_cats_arr[b_sub["dt"].cat.codes.to_numpy()]
        m_pair = np.array([(d, c) in unique_pairs for d, c in zip(b_d2, b_c6)], dtype=bool)
        if m_pair.any():
            b_hit = b_sub.loc[m_pair].copy()
            b_hit["buy_date"] = b_d2[m_pair]
            b_hit["code"] = b_c6[m_pair]
            b_hit.drop(columns=["c6", "dt"], inplace=True)
            matched_chunks.append(b_hit)
        if i_b % 10 == 0:
            pa.default_memory_pool().release_unused()

    pa.default_memory_pool().release_unused()
    if matched_chunks:
        sd = pd.concat(matched_chunks, ignore_index=True).drop_duplicates(["buy_date", "code"])
        df = df.merge(sd, on=["buy_date", "code"], how="left")
    del matched_chunks
    gc.collect()

    if buy_at == "close" and "open_pct" in df.columns and "ret_1d" in df.columns:
        df["intraday_oc_pct"] = ((1.0 + df["ret_1d"] / 100.0) / np.maximum(1e-6, 1.0 + df["open_pct"] / 100.0) - 1.0) * 100.0

    mkt_read = ["trade_date"] + [c for c in MKT_PIT_FEATURES if c not in df.columns]
    mkt = pd.read_parquet(MKT_DAY_PQ, columns=mkt_read)
    mkt["trade_date"] = mkt["trade_date"].astype(str).str[:10]
    mkt.rename(columns={"trade_date": "buy_date"}, inplace=True)
    df = df.merge(mkt, on="buy_date", how="left")
    del mkt
    gc.collect()

    fcols = list(STOCK_OPEN_FEATURES)
    if buy_at == "close":
        fcols += STOCK_CLOSE_EXTRA_FEATURES + ["intraday_oc_pct"]
    fcols += MKT_PIT_FEATURES
    if extra_cols:
        for c in extra_cols:
            if c not in fcols:
                fcols.append(c)
    fcols = [c for c in fcols if c in df.columns]
    return df, fcols


def _metrics_from_daily(dr: np.ndarray, tr_sub: pd.DataFrame, csi_r: np.ndarray, ew_r: np.ndarray) -> dict:
    T = len(dr)
    if T == 0:
        return {"n": 0, "nav": 1.0, "mdd_pct": 0.0, "sharpe": 0.0, "excess_csi_pp": 0.0}
    curve = np.concatenate([[1.0], np.cumprod(1.0 + dr)])
    pk = np.maximum.accumulate(curve)
    mdd = float(np.max((pk - curve) / pk) * 100.0)
    sd = float(np.std(dr, ddof=1)) if T > 1 else 0.0
    sharpe = float(np.mean(dr) / sd * math.sqrt(242.0)) if sd > 1e-12 else 0.0
    csi_pct = (float(np.prod(1.0 + csi_r)) - 1.0) * 100.0
    ew_pct = (float(np.prod(1.0 + ew_r)) - 1.0) * 100.0
    if tr_sub.empty:
        return {
            "n": 0, "wr_pct": 0.0, "plr": 0.0, "mean_pct": 0.0,
            "nav": 1.0, "ex3_nav": 1.0, "ex5_nav": 1.0,
            "mdd_pct": round(mdd, 2), "sharpe": round(sharpe, 3),
            "excess_csi_pp": round(-csi_pct, 2), "excess_ew_pp": round(-ew_pct, 2),
        }
    rets = tr_sub["net_ret"].to_numpy(float)
    w, l = rets[rets > 0], rets[rets <= 0]
    wr = float((rets > 0).mean() * 100.0)
    plr = float(w.mean() / abs(l.mean())) if (len(w) and len(l) and l.mean() < 0) else (99.0 if len(w) else 0.0)
    tr_nav = float(np.prod(1.0 + rets))
    sr = np.sort(rets)
    ex3 = float(np.prod(1.0 + sr[:-3])) if len(rets) > 3 else 1.0
    ex5 = float(np.prod(1.0 + sr[:-5])) if len(rets) > 5 else 1.0
    return {
        "n": int(len(rets)),
        "wr_pct": round(wr, 2),
        "plr": round(plr, 2),
        "mean_pct": round(float(rets.mean() * 100.0), 2),
        "nav": round(tr_nav, 4),
        "ex3_nav": round(ex3, 4),
        "ex5_nav": round(ex5, 4),
        "mdd_pct": round(mdd, 2),
        "sharpe": round(sharpe, 3),
        "excess_csi_pp": round((tr_nav - 1.0) * 100.0 - csi_pct, 2),
        "excess_ew_pp": round((tr_nav - 1.0) * 100.0 - ew_pct, 2),
    }


def evaluate_and_audit_track(
    track_id: str,
    module_name: str,
    desc: str,
    cand_df: pd.DataFrame,
    feature_cols: list[str],
    px_idx: PriceReturnIndex,
    v20_ctx: dict,
    buy_at: str = "open",
    thresholds: tuple = ("all_cands", "top30", "top20", "top10", 70, 75),
    recalc_freq: str = "daily",
    min_warmup_trades: int = 80,
    min_warmup_trades_rare: int = 40,
    min_warmup_months: int = 18,
    top_k: int = 12,
    perm_n: int = 1000,
    run_trunc_check: bool = True,
    trunc_threshold: str = "top20",
) -> dict:
    res = wf.run_wf_scorecard_new_strategy(
        cand_df,
        feature_cols=feature_cols,
        v20_ctx=v20_ctx,
        wf_start_date="2023-01-03",
        end_date="2026-11-16",
        min_warmup_trades=min_warmup_trades,
        min_warmup_trades_rare=min_warmup_trades_rare,
        min_warmup_months=min_warmup_months,
        recalc_freq=recalc_freq,
        top_k=top_k,
        min_k=min(5, len(feature_cols)),
        max_corr=0.65,
        min_t_stat=1.0,
        shrink_tau=20.0,
        fee_rt=0.0030,
        gross_ret_col="gross_ret",
        thresholds=thresholds,
        eval_v20_patch=True,
        perm_n=perm_n,
    )

    actual_wf_start = res["meta"]["wf_actual_start"] or "2023-01-03"
    end_dt = "2026-11-16"
    cal_df = v20_ctx["calendar_5y"]
    cal_win = cal_df[cal_df["trade_date"].between(actual_wf_start, end_dt)].sort_values("trade_date").reset_index(drop=True)
    cal_dts = cal_win["trade_date"].tolist()
    v20_dr = cal_win["v20_daily_ret"].to_numpy(float)
    csi_r = cal_win["csi300_daily_ret"].to_numpy(float)
    ew_r = cal_win["alla_ew_daily_ret"].to_numpy(float)
    mask_2526 = np.array([d >= "2025-01-01" for d in cal_dts], dtype=bool)
    mask_2026 = np.array([d >= "2026-01-01" for d in cal_dts], dtype=bool)

    v20_led = v20_ctx["v20_ledger"]
    v20_wf_sub = v20_led[v20_led["buy_date"].between(actual_wf_start, end_dt)]
    v20_base_wf = _metrics_from_daily(v20_dr, v20_wf_sub, csi_r, ew_r)
    v20_base_2526 = _metrics_from_daily(v20_dr[mask_2526], v20_wf_sub[v20_wf_sub["buy_date"] >= "2025-01-01"], csi_r[mask_2526], ew_r[mask_2526])
    v20_base_2026 = _metrics_from_daily(v20_dr[mask_2026], v20_wf_sub[v20_wf_sub["buy_date"] >= "2026-01-01"], csi_r[mask_2026], ew_r[mask_2026])

    threshold_audits = []
    best_th = None
    best_score = -1e18
    best_slot_df = None

    for th_name, obj in res["threshold_results"].items():
        slot_df = obj["slot_df"]
        ev = obj["metrics"]
        dr_exact, mtm_diff = px_idx.compute_exact_mtm_series(slot_df, cal_dts, buy_at=buy_at, fee_rt=0.0030)
        ex_wf = _metrics_from_daily(dr_exact, slot_df[slot_df["buy_date"].between(actual_wf_start, end_dt)], csi_r, ew_r)
        ex_2526 = _metrics_from_daily(dr_exact[mask_2526], slot_df[slot_df["buy_date"] >= "2025-01-01"], csi_r[mask_2526], ew_r[mask_2526])
        ex_2026 = _metrics_from_daily(dr_exact[mask_2026], slot_df[slot_df["buy_date"] >= "2026-01-01"], csi_r[mask_2026], ew_r[mask_2026])

        corr_v20 = float(np.corrcoef(dr_exact, v20_dr)[0, 1]) if (np.std(dr_exact) > 1e-12 and np.std(v20_dr) > 1e-12) else 0.0

        patch = obj["v20_empty_patch"]
        p_m1 = patch["mode1_strict_combined_no_peek"] if patch else None
        p_m2 = patch["mode2_empty_slot_standalone"] if patch else None

        if p_m2 is not None:
            empty_set = set(cal_win.loc[cal_win["v20_empty_slot"] & (~cal_win["v20_has_stier_wait"]), "trade_date"])
            p_emp_df = obj["pass_df"][obj["pass_df"]["buy_date"].isin(empty_set)].copy()
            _, emp_slot_df = wf.select_single_slot_trades(
                p_emp_df.assign(can_buy_hygiene=True), score_col="wf_score", threshold=None, wf_only=False
            )
            dr_emp_exact, _ = px_idx.compute_exact_mtm_series(emp_slot_df, cal_dts, buy_at=buy_at, fee_rt=0.0030)
            emp_exact_wf = _metrics_from_daily(dr_emp_exact, emp_slot_df, csi_r, ew_r)
            corr_emp_v20 = float(np.corrcoef(dr_emp_exact, v20_dr)[0, 1]) if (np.std(dr_emp_exact) > 1e-12 and np.std(v20_dr) > 1e-12) else 0.0
        else:
            emp_exact_wf = None
            corr_emp_v20 = 0.0

        row = {
            "track_id": track_id,
            "module": module_name,
            "threshold": th_name,
            "desc": desc,
            "wf_actual_start": actual_wf_start,
            "n_cands_total": int(len(cand_df)),
            "n_pass": int(obj["n_passing_cands"]),
            "n_trades_wf": ex_wf["n"],
            "wr_wf_pct": ex_wf["wr_pct"],
            "plr_wf": ex_wf["plr"],
            "mean_wf_pct": ex_wf["mean_pct"],
            "nav_wf": ex_wf["nav"],
            "ex3_wf": ex_wf["ex3_nav"],
            "ex5_wf": ex_wf["ex5_nav"],
            "mdd_wf_pct": ex_wf["mdd_pct"],
            "sharpe_wf": ex_wf["sharpe"],
            "excess_csi_wf_pp": ex_wf["excess_csi_pp"],
            "excess_ew_wf_pp": ex_wf["excess_ew_pp"],
            "corr_v20_wf": round(corr_v20, 4),
            "n_2526": ex_2526["n"],
            "nav_2526": ex_2526["nav"],
            "ex5_2526": ex_2526["ex5_nav"],
            "mdd_2526_pct": ex_2526["mdd_pct"],
            "sharpe_2526": ex_2526["sharpe"],
            "excess_csi_2526_pp": ex_2526["excess_csi_pp"],
            "n_2026": ex_2026["n"],
            "nav_2026": ex_2026["nav"],
            "ex5_2026": ex_2026["ex5_nav"],
            "mdd_2026_pct": ex_2026["mdd_pct"],
            "sharpe_2026": ex_2026["sharpe"],
            "excess_csi_2026_pp": ex_2026["excess_csi_pp"],
            "perm_sd_p": ev["permutation_1000"]["same_day_p_nav"],
            "perm_any_p": ev["permutation_1000"]["any_cand_day_p_nav"],
            "mtm_reconcile_diff": round(float(mtm_diff), 8),
            "patch_n_added": p_m1["n_patch_added"] if p_m1 else 0,
            "patch_n_v20_skipped": p_m1["n_v20_skipped_by_collision"] if p_m1 else 0,
            "patch_skipped_v20_prod": p_m1["skipped_v20_net_ret_prod"] if p_m1 else 1.0,
            "patch_delta_nav_ratio": p_m1["delta_nav_ratio_full_wf"] if p_m1 else 1.0,
            "patch_delta_sharpe": p_m1["delta_sharpe_full_wf"] if p_m1 else 0.0,
            "patch_delta_mdd_pp": p_m1["delta_mdd_pp_full_wf"] if p_m1 else 0.0,
            "patch_comb_nav_wf": p_m1["combined_with_patch"]["FULL_WF"]["nav"] if p_m1 else v20_base_wf["nav"],
            "patch_comb_nav_2526": p_m1["combined_with_patch"]["Y2025_2026"]["nav"] if p_m1 else v20_base_2526["nav"],
            "patch_comb_nav_2026": p_m1["combined_with_patch"]["Y2026"]["nav"] if p_m1 else v20_base_2026["nav"],
            "emp_standalone_n": emp_exact_wf["n"] if emp_exact_wf else 0,
            "emp_standalone_nav_wf": emp_exact_wf["nav"] if emp_exact_wf else 1.0,
            "emp_standalone_sharpe_wf": emp_exact_wf["sharpe"] if emp_exact_wf else 0.0,
            "emp_standalone_mdd_wf_pct": emp_exact_wf["mdd_pct"] if emp_exact_wf else 0.0,
            "emp_corr_v20_wf": round(corr_emp_v20, 4),
            "emp_collision_rate_pct": p_m2["collision_rate_pct"] if p_m2 else 0.0,
        }
        threshold_audits.append(row)

        if th_name != "all_cands" and ex_wf["n"] >= 8:
            sc_rank = ex_wf["sharpe"] + (0.5 if row["patch_delta_nav_ratio"] > 1.0 else 0.0) - 0.01 * ex_wf["mdd_pct"]
            if sc_rank > best_score:
                best_score = sc_rank
                best_th = row
                best_slot_df = slot_df

    if best_th is None and threshold_audits:
        best_th = threshold_audits[0]
        best_slot_df = res["threshold_results"][best_th["threshold"]]["slot_df"]

    latest_card = res["meta"]["latest_scorecard"]
    top_factors = [
        {
            "name": f["name"],
            "t": f["t_cluster"],
            "shape": f["shape"],
            "pts": f["budget_pts"],
            "bin_pts": f["bin_pts"],
            "bin_wr": f["bin_wr_pct"],
            "bin_mean": f["bin_mean_pct"],
        }
        for f in (latest_card["factors"] if latest_card else [])
    ]
    n_rebuilds = res["meta"]["n_rebuilds"]
    elapsed_sec = res["elapsed_sec"]

    # Free heavy scored_df immediately before truncation check
    del res
    gc.collect()

    trunc_proof = None
    if run_trunc_check and len(cand_df[cand_df["buy_date"] <= "2024-12-31"]) >= min_warmup_trades + 15:
        trunc_proof = wf.verify_truncation_zero_leakage(
            cand_df,
            feature_cols=feature_cols,
            mode="A",
            cutoff="2024-12-31",
            score_threshold=trunc_threshold,
            v20_ctx=v20_ctx,
            wf_start_date="2023-01-03",
            min_warmup_trades=min_warmup_trades,
            min_warmup_trades_rare=min_warmup_trades_rare,
            min_warmup_months=min_warmup_months,
            recalc_freq=recalc_freq,
            top_k=top_k,
            min_k=min(5, len(feature_cols)),
            gross_ret_col="gross_ret",
            fee_rt=0.0030,
        )

    return {
        "track_id": track_id,
        "module": module_name,
        "desc": desc,
        "recalc_freq": recalc_freq,
        "elapsed_sec": elapsed_sec,
        "wf_actual_start": actual_wf_start,
        "n_rebuilds": n_rebuilds,
        "n_features": len(feature_cols),
        "v20_baseline_wf": v20_base_wf,
        "threshold_rows": threshold_audits,
        "best_row": best_th,
        "best_slot_df": best_slot_df,
        "top_factors_latest": top_factors,
        "truncation_20241231": trunc_proof,
    }

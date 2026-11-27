#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD051 Data Loader: Memory-Safe Filtered PyArrow Loading + Q8 Coverage + Split-Safe Causal Price Bars."""

import gc
import json
import os
import sys
from typing import Optional

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds

assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
POOL_PQ = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base/pools_6strat_master_newfactors_pit.parquet"
A_DAILY_PQ = f"{SIM}/data/cn_hk_price_db/a_daily.parquet"
A_DELIST_PQ = f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet"
ST_JSON = f"{SIM}/data/st_universe.json"


def load_master_pool(end_cutoff: Optional[str] = None) -> pd.DataFrame:
    """Load pools_6strat_master_newfactors_pit.parquet with canonical string normalization."""
    mp = pd.read_parquet(POOL_PQ)
    mp["c6"] = mp["code"].astype(str).str.zfill(6)
    mp["bd"] = mp["buy_date"].astype(str).str[:10]
    mp["ed"] = mp["exit_date"].astype(str).str[:10]
    mp["sd"] = mp["sig_date"].astype(str).str[:10]
    if end_cutoff is not None:
        mp = mp[mp["bd"] <= end_cutoff].copy()
    mp = mp.sort_values(["bd", "strategy", "c6"]).reset_index(drop=True)
    return mp


def _load_st_set() -> set[str]:
    if not os.path.exists(ST_JSON):
        return set()
    with open(ST_JSON, encoding="utf-8") as f:
        d = json.load(f)
    codes = d.get("codes", d) if isinstance(d, dict) else d
    return {str(x)[-6:].zfill(6) for x in codes}


def load_filtered_daily_bars(codes: list[str], end_cutoff: Optional[str] = None) -> tuple[dict[str, dict], dict]:
    """
    Load 2015-01-01..end_cutoff daily bars ONLY for `codes` using pyarrow.dataset pushdown filters.
    Returns per-stock contiguous numpy arrays + Q8 loader audit dictionary.
    """
    uniq_c6 = sorted({str(c).zfill(6) for c in codes})
    tks = sorted({f"{c}.SH" for c in uniq_c6} | {f"{c}.SZ" for c in uniq_c6})
    ts_start = pd.Timestamp("2015-01-01")
    ts_end = pd.Timestamp(end_cutoff) if end_cutoff else pd.Timestamp("2026-11-26")

    # 1. Determine true IPO date (min date in a_daily across 1990..end_cutoff) to protect pre-2015 listings
    flt_ipo = ds.field("ticker").isin(tks) & (ds.field("date") <= ts_end)
    ipo_tbl = ds.dataset(A_DAILY_PQ, format="parquet").scanner(columns=["date", "ticker"], filter=flt_ipo).to_table().to_pandas()
    ipo_tbl["c6"] = ipo_tbl["ticker"].astype(str).str[:6]
    ipo_min_map = ipo_tbl.groupby("c6")["date"].min().dt.strftime("%Y-%m-%d").to_dict()
    del ipo_tbl
    gc.collect()

    # 2. Load 2015+ bars from a_daily and a_delisted_daily
    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "amount", "turn", "qfq_factor"]
    flt_bars = ds.field("ticker").isin(tks) & (ds.field("date") >= ts_start) & (ds.field("date") <= ts_end)

    ad_df = ds.dataset(A_DAILY_PQ, format="parquet").scanner(columns=cols, filter=flt_bars).to_table().to_pandas()
    ad_df["is_delisted_src"] = 0
    dl_df = ds.dataset(A_DELIST_PQ, format="parquet").scanner(columns=cols, filter=flt_bars).to_table().to_pandas()
    dl_df["is_delisted_src"] = 1

    ad_codes = set(ad_df["ticker"].astype(str).str[:6])
    dl_codes = set(dl_df["ticker"].astype(str).str[:6])

    bars = pd.concat([ad_df, dl_df], ignore_index=True)
    del ad_df, dl_df
    gc.collect()
    pa.default_memory_pool().release_unused()

    bars["c6"] = bars["ticker"].astype(str).str[:6]
    bars["dt"] = pd.to_datetime(bars["date"]).dt.strftime("%Y-%m-%d")
    bars = bars[(bars["close"] > 0) & (bars["open"] > 0) & (bars["adj_close"] > 0)].copy()
    bars = bars.sort_values(["c6", "dt", "is_delisted_src"]).drop_duplicates(["c6", "dt"], keep="first").reset_index(drop=True)

    st_set = _load_st_set()
    stock_data: dict[str, dict] = {}
    n_split_fixed = 0

    for c6, grp in bars.groupby("c6", sort=False):
        dts = grp["dt"].to_numpy()
        op = grp["open"].to_numpy(np.float64)
        hi = grp["high"].to_numpy(np.float64)
        lo = grp["low"].to_numpy(np.float64)
        cl = grp["close"].to_numpy(np.float64)
        ac = grp["adj_close"].to_numpy(np.float64)
        amt = grp["amount"].to_numpy(np.float64)
        trn = grp["turn"].to_numpy(np.float64)
        is_dl = int(grp["is_delisted_src"].iloc[0])
        m = len(dts)

        # Price adjustment: a_daily uses exact adj_close/close ratio; a_delisted_daily (qfq=1) applies causal split detection
        adj_f = ac / cl
        ao = op * adj_f
        ah = hi * adj_f
        al = lo * adj_f
        ac_use = ac.copy()
        is_split_day = np.zeros(m, dtype=bool)

        if is_dl == 1:
            cum_sp = 1.0
            for i in range(1, m):
                raw_op_r = op[i] / cl[i - 1]
                raw_intraday = abs(cl[i] / op[i] - 1.0)
                if 0.28 <= raw_op_r <= 0.78 and cl[i] >= 2.0 and raw_intraday <= 0.11 and dts[i] < "2023-01-01":
                    cum_sp *= (cl[i - 1] / op[i])
                    is_split_day[i] = True
                    n_split_fixed += 1
                ao[i] *= cum_sp
                ah[i] *= cum_sp
                al[i] *= cum_sp
                ac_use[i] *= cum_sp

        # Returns & prev_close_raw
        prev_ac = np.empty(m, dtype=np.float64)
        prev_ac[0] = np.nan
        prev_ac[1:] = ac_use[:-1]
        ret_1d = np.where(np.isfinite(prev_ac) & (prev_ac > 0), ac_use / prev_ac - 1.0, np.nan)
        open_pct = np.where(np.isfinite(prev_ac) & (prev_ac > 0), ao / prev_ac - 1.0, np.nan)

        # Ex-dividend adjusted prev_close in raw price units for exact limit-up/down tick rounding
        prev_close_raw = np.empty(m, dtype=np.float64)
        prev_close_raw[0] = np.nan
        if is_dl == 0:
            prev_close_raw[1:] = ac_use[:-1] * (cl[1:] / ac_use[1:])
        else:
            prev_close_raw[1:] = np.where(is_split_day[1:], op[1:], cl[:-1])

        # Effective split-invariant volume (RMB amount / adjusted close) and turnover
        eff_vol = np.where((amt > 0) & (ac_use > 0), amt / ac_use, np.nan)
        turn_clean = np.where(np.isfinite(trn) & (trn > 0), trn, eff_vol)

        # IPO age: pre-2015 stocks are mature (>=9999 bars)
        ipo_dt = ipo_min_map.get(c6, dts[0] if len(dts) else "2015-01-01")
        is_mature_pre2015 = ipo_dt < "2015-01-01"
        bar_age = np.arange(m, dtype=np.int32) + (9999 if is_mature_pre2015 else 0)
        is_ipo20 = bar_age < 20

        # Historical limit rules: 688/689 always 20%; 300/301 20% from 2020-08-24 onward, 10% prior
        if c6.startswith(("688", "689")):
            is_20 = np.ones(m, dtype=bool)
        elif c6.startswith(("300", "301")):
            is_20 = dts >= "2020-08-24"
        else:
            is_20 = np.zeros(m, dtype=bool)

        lim = np.where(is_20, 0.20, 0.10)
        zt_px = np.round(prev_close_raw * (1.0 + lim), 2)
        dt_px = np.round(prev_close_raw * (1.0 - lim), 2)
        valid_p = np.isfinite(prev_close_raw) & (prev_close_raw > 0) & (~is_ipo20) & (~is_split_day)

        # Post-2026-07-06 ST stocks also have 10% limit; exclude known 2026 ST on >=2026-07-06 cleanly
        st_block = (dts >= "2026-07-06") & (c6 in st_set)
        valid_lim = valid_p & (~st_block)

        is_zt = valid_lim & (cl >= zt_px - 0.005) & (cl >= hi - 1e-4)
        is_yizi_zt = is_zt & (op >= zt_px - 0.005) & (lo >= zt_px - 0.005)
        is_dt = valid_lim & (cl <= dt_px + 0.005) & (cl <= lo + 1e-4)
        is_yizi_dt = is_dt & (op <= dt_px + 0.005) & (hi <= dt_px + 0.005)

        streak = np.zeros(m, dtype=np.int16)
        cur_s = 0
        for i in range(m):
            cur_s = (cur_s + 1) if is_zt[i] else 0
            streak[i] = cur_s

        # 10-dim causal KNN feature matrix at day T (strictly using <= T-1 bars + T open_pct)
        hl_rng = hi - lo
        upper_shad = np.where(hl_rng > 1e-6, (hi - np.maximum(op, cl)) / hl_rng, 0.0)
        body = np.where(op > 0, cl / op - 1.0, 0.0)

        # Trailing 20d avg volume [i-20..i-1] (at bar i, evaluated for bar i's T-1 shift)
        vol_ma20_prev = np.full(m, np.nan, dtype=np.float64)
        ev_valid = np.where(np.isfinite(eff_vol), eff_vol, 0.0)
        ev_cnt = np.where(np.isfinite(eff_vol), 1.0, 0.0)
        cs_ev = np.concatenate(([0.0], np.cumsum(ev_valid)))
        cs_ec = np.concatenate(([0.0], np.cumsum(ev_cnt)))
        for i in range(5, m):
            j0 = max(0, i - 20)
            cnt = cs_ec[i] - cs_ec[j0]
            if cnt >= 5:
                vol_ma20_prev[i] = (cs_ev[i] - cs_ev[j0]) / cnt
        with np.errstate(divide="ignore", invalid="ignore"):
            vr20 = np.where((vol_ma20_prev > 0) & np.isfinite(eff_vol), np.log1p(np.clip(eff_vol / vol_ma20_prev, 0.0, 20.0)), np.nan)

        turn_rank60 = np.full(m, np.nan, dtype=np.float64)
        dd60_hi = np.full(m, np.nan, dtype=np.float64)
        for i in range(15, m):
            j0 = max(0, i - 59)
            w_tr = turn_clean[j0 : i + 1]
            if np.isfinite(turn_clean[i]) and np.isfinite(w_tr).sum() >= 10:
                turn_rank60[i] = float(np.nanmean(w_tr <= turn_clean[i]))
            w_hi = np.max(ah[j0 : i + 1])
            if w_hi > 0:
                dd60_hi[i] = ac_use[i] / w_hi - 1.0

        # Assemble KNN feature vector for index t (uses t-1, t-2, t-3, t-4..t-5, and open_pct[t])
        knn_mat = np.full((m, 10), np.nan, dtype=np.float32)
        if m >= 25:
            idx = np.arange(20, m)
            r1 = np.clip(ret_1d[idx - 1], -0.25, 0.25)
            r2 = np.clip(ret_1d[idx - 2], -0.25, 0.25)
            r3 = np.clip(ret_1d[idx - 3], -0.25, 0.25)
            r45 = np.clip(ac_use[idx - 4] / ac_use[idx - 6] - 1.0, -0.45, 0.45)
            us1 = np.clip(upper_shad[idx - 1], 0.0, 1.0)
            bd1 = np.clip(body[idx - 1], -0.25, 0.25)
            vr1 = np.clip(vr20[idx - 1], 0.0, 3.0)
            tr1 = np.clip(turn_rank60[idx - 1], 0.0, 1.0)
            dd1 = np.clip(dd60_hi[idx - 1], -0.80, 0.0)
            op0 = np.clip(open_pct[idx], -0.22, 0.22)
            raw_mat = np.column_stack([r1, r2, r3, r45, us1, bd1, vr1, tr1, dd1, op0])
            scales = np.array([0.05, 0.05, 0.04, 0.06, 0.25, 0.04, 0.40, 0.30, 0.15, 0.04], dtype=np.float32)
            knn_mat[idx] = (raw_mat / scales).astype(np.float32)

        dt_to_idx = {str(d): i for i, d in enumerate(dts)}
        stock_data[c6] = {
            "dts": dts,
            "dt_to_idx": dt_to_idx,
            "ao": ao,
            "ah": ah,
            "al": al,
            "ac": ac_use,
            "ret_1d": ret_1d,
            "open_pct": open_pct,
            "intraday_ret": np.where(ao > 0, ac_use / ao - 1.0, np.nan),
            "high_vs_open": np.where(ao > 0, ah / ao - 1.0, np.nan),
            "is_20": is_20,
            "is_zt": is_zt,
            "is_yizi_zt": is_yizi_zt,
            "is_dt": is_dt,
            "is_yizi_dt": is_yizi_dt,
            "is_ipo20": is_ipo20,
            "is_split": is_split_day,
            "streak": streak,
            "knn_mat": knn_mat,
            "is_dl": is_dl,
            "ipo_dt": ipo_dt,
        }

    del bars
    gc.collect()
    pa.default_memory_pool().release_unused()

    audit = {
        "n_unique_codes_req": len(uniq_c6),
        "n_loaded_stocks": len(stock_data),
        "n_in_a_daily": len(ad_codes),
        "n_in_a_delisted": len(dl_codes),
        "n_missing_stocks": len(set(uniq_c6) - set(stock_data.keys())),
        "n_delisted_split_gaps_fixed": n_split_fixed,
    }
    return stock_data, audit

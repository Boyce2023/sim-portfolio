#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD030 Wave 1 - Step 1: Build strict PIT 6-dimensional Old-Hot-Stock stock-day feature warehouse.
Covers all .SH/.SZ (00/60/30/688/689, active + delisted) trading days 2021-01-01 ~ 2026-11-25.

Hard rules:
  - ZERO yfinance (D12).
  - Pure compounding & equal-weight evaluation only.
  - All SQLite opened with file:...?mode=ro (uri=True).
  - ProcessPool concurrency <= 8.
  - Strictly causal as of pre-open on day T (uses bars <= T-1, KPL < T, community <= T-6).
  - Primary口径 `excl_curr_wave` excludes the current active ZT launch wave (ZT within last 5 bars
    chained by <= 5-bar gap). Control口径 `_t1` evaluates up to T-1 for cross-verification.
  - Includes physical truncation proof at cutoff 2024-12-31 (max_abs_diff == 0.0).
"""
import argparse
import bisect
import json
import multiprocessing as mp
import os
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
OUT_DIR = f"{SIM}/backtests_astock2/rd028_old_hot_stock_6strat_5y_20261125"
A_DAILY = f"{SIM}/data/cn_hk_price_db/a_daily.parquet"
A_DELISTED = f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet"
DB_XQ_GB = f"{SIM}/data/xueqiu_guba_5y_pit.db"
DB_COMM = f"{SIM}/data/astock_community_5y_pit.db"
KPL_JSONL = f"{SIM}/data/kpl_plates_2018_2026_merged.jsonl"

OUT_PARQUET = f"{OUT_DIR}/old_hot_6dim_stock_day_pit.parquet"

# Shared globals for fork multiprocessing workers (read-only after init)
_G = {}


def _norm_plate(raw: str) -> str:
    s = re.sub(r"\(.*?\)|（.*?）", "", str(raw or "")).strip()
    if s.endswith("概念") and len(s) > 3:
        s = s[:-2].strip()
    return s


def _cool_bin(d: float) -> str:
    if np.isnan(d) or d < 0:
        return "never"
    if d <= 30:
        return "<=30d"
    if d <= 90:
        return "31~90d"
    if d <= 180:
        return "91~180d"
    if d <= 365:
        return "181~365d"
    return ">365d"


def load_daily_panel(end_date_cutoff: str) -> tuple[pd.DataFrame, list[str], dict[str, int]]:
    """Load active + delisted .SH/.SZ bars <= end_date_cutoff, compute list_age & ZT indicators."""
    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "turn"]
    flt = ds.field("date") <= pd.Timestamp(end_date_cutoff)
    da = ds.dataset(A_DAILY, format="parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    dd = ds.dataset(A_DELISTED, format="parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    da["dl"], dd["dl"] = 0, 1
    df = pd.concat([da, dd], ignore_index=True)

    tk = df["ticker"].astype(str)
    df["c6"] = tk.str[:6]
    mask = (
        tk.str.endswith((".SH", ".SZ"))
        & df["c6"].str.startswith(("00", "60", "30", "688", "689"))
        & (df["close"] > 0)
        & (df["adj_close"] > 0)
    )
    df = df[mask].copy()
    df["dt"] = df["date"].dt.strftime("%Y-%m-%d")
    df = df[df["dt"] <= end_date_cutoff].copy()
    df.sort_values(["c6", "dt", "dl"], inplace=True)
    df.drop_duplicates(["c6", "dt"], keep="first", inplace=True)
    df.reset_index(drop=True, inplace=True)

    # True listing age from full IPO history up to end_date_cutoff
    df["list_age"] = (df.groupby("c6", sort=False).cumcount() + 1).astype(np.int32)

    # Slice warm-up window >= 2015-06-01 (>1,350 trading days prior to 2021-01-01)
    df = df[df["dt"] >= "2015-06-01"].copy().reset_index(drop=True)

    all_dts = sorted(df["dt"].unique())
    dt_to_mkt = {d: i for i, d in enumerate(all_dts)}
    df["mkt_idx"] = df["dt"].map(dt_to_mkt).astype(np.int32)

    c6_arr = df["c6"].to_numpy()
    same_c6 = np.empty(len(df), dtype=bool)
    same_c6[0] = False
    same_c6[1:] = c6_arr[1:] == c6_arr[:-1]

    close_v = df["close"].to_numpy(np.float64)
    ac_v = df["adj_close"].to_numpy(np.float64)
    sc_v = ac_v / close_v
    pac_v = np.empty(len(df), dtype=np.float64)
    pac_v[0] = np.nan
    pac_v[1:] = np.where(same_c6[1:], ac_v[:-1], np.nan)

    ret_v = np.where(pac_v > 0, ac_v / pac_v - 1.0, np.nan)
    c6_s = df["c6"]
    dt_s = df["dt"]
    is20 = (c6_s.str.startswith(("688", "689")) | (c6_s.str.startswith("30") & (dt_s >= "2020-08-24"))).to_numpy()
    lim = np.where(is20, 0.20, 0.10)
    r_th = np.where(is20, 0.195, 0.095)
    abn = np.abs(ret_v) > np.where(is20, 0.22, 0.12)
    pre_ex = pac_v / sc_v
    zt_px = np.floor(pre_ex * (1.0 + lim) * 100.0 + 0.5) / 100.0

    vol_v = df["volume"].fillna(0.0).to_numpy(np.float64)
    age_v = df["list_age"].to_numpy(np.int32)
    is_zt = (
        (pac_v > 0)
        & (vol_v > 0)
        & (close_v >= zt_px - 0.011)
        & (ret_v >= r_th)
        & (~abn)
        & (age_v > 20)
    )

    df["ac"] = ac_v.astype(np.float64)
    df["ah"] = (df["high"].to_numpy(np.float64) * sc_v).astype(np.float64)
    df["turn_clean"] = df["turn"].fillna(0.0).clip(lower=0.0, upper=1.0).to_numpy(np.float32)
    df["is_zt"] = is_zt

    # Compute consecutive ZT streak within each stock (no calendar reset across suspension)
    streak = np.zeros(len(df), dtype=np.int16)
    cur = 0
    for i in range(len(df)):
        if not same_c6[i]:
            cur = 0
        if is_zt[i]:
            cur += 1
            streak[i] = cur
        else:
            cur = 0
    df["streak"] = streak
    return df, all_dts, dt_to_mkt


def load_community_daily_and_monthly(
    end_date_cutoff: str,
    c6_list: list[str],
    all_dts: list[str],
    dt_to_mkt: dict[str, int],
    stock_active_ym: dict[str, tuple[str, str]],
) -> dict[str, np.ndarray]:
    """
    Merge deduplicated xueqiu + guba + community_posts strictly <= end_date_cutoff.
    Returns dense daily/monthly lookups for fast causal [T-250..T-6] & [T-750..T-6] aggregation.
    """
    c6_to_sid = {c: i for i, c in enumerate(c6_list)}
    n_s = len(c6_list)
    n_d = len(all_dts)

    c1 = sqlite3.connect(f"file:{DB_XQ_GB}?mode=ro", uri=True)
    c2 = sqlite3.connect(f"file:{DB_COMM}?mode=ro", uri=True)

    # 1. Xueqiu deduplicated (c1.xueqiu_posts + c2.xueqiu)
    xq1 = pd.read_sql_query(
        "SELECT CAST(post_id AS TEXT) AS pid, symbol AS c6, substr(created_time_str,1,10) AS dt "
        "FROM xueqiu_posts WHERE created_time_str >= '2015-06-01' AND substr(created_time_str,1,10) <= ?",
        c1,
        params=(end_date_cutoff,),
    )
    cp2 = pd.read_sql_query(
        "SELECT post_id AS pid, source, symbol AS c6, substr(pub_datetime_cst,1,10) AS dt "
        "FROM community_posts WHERE pub_datetime_cst >= '2015-06-01' AND substr(pub_datetime_cst,1,10) <= ?",
        c2,
        params=(end_date_cutoff,),
    )
    cp2_xq = cp2[cp2["source"] == "xueqiu"].copy()
    cp2_xq["pid"] = cp2_xq["pid"].astype(str).str.replace("xueqiu_", "", regex=False)
    xq_all = pd.concat([xq1, cp2_xq[["pid", "c6", "dt"]]], ignore_index=True).drop_duplicates(["pid"])
    xq_all["c6"] = xq_all["c6"].astype(str).str.zfill(6)

    # 2. Guba deduplicated: SQL-aggregate c1, then check c2 guba pids in c1 via batched IN
    gb1_agg = pd.read_sql_query(
        "SELECT sec_code AS c6, substr(pub_time,1,10) AS dt, COUNT(*) AS cnt "
        "FROM guba_posts WHERE pub_time >= '2015-06-01' AND substr(pub_time,1,10) <= ? "
        "GROUP BY sec_code, substr(pub_time,1,10)",
        c1,
        params=(end_date_cutoff,),
    )
    gb1_agg["c6"] = gb1_agg["c6"].astype(str).str.zfill(6)

    cp2_gb = cp2[cp2["source"].isin(["eastmoney_guba", "guba"])].copy()
    cp2_gb["pid_clean"] = (
        cp2_gb["pid"].astype(str).str.replace("eastmoney_guba_", "", regex=False).str.replace("guba_", "", regex=False)
    )
    cp2_gb = cp2_gb.drop_duplicates(["pid_clean"])
    existing_pids = set()
    pids_list = cp2_gb["pid_clean"].tolist()
    for i in range(0, len(pids_list), 20000):
        chunk = pids_list[i : i + 20000]
        ph = ",".join("?" for _ in chunk)
        for (pid_hit,) in c1.execute(f"SELECT post_id FROM guba_posts WHERE post_id IN ({ph})", chunk):
            existing_pids.add(str(pid_hit))
    cp2_gb_new = cp2_gb[~cp2_gb["pid_clean"].isin(existing_pids)].copy()
    cp2_gb_new["c6"] = cp2_gb_new["c6"].astype(str).str.zfill(6)

    cp2_oth = cp2[~cp2["source"].isin(["xueqiu", "eastmoney_guba", "guba"])].copy()
    cp2_oth["c6"] = cp2_oth["c6"].astype(str).str.zfill(6)

    c1.close()
    c2.close()

    # Combine daily counts (both combined and xueqiu-only)
    xq_agg = xq_all.groupby(["c6", "dt"], as_index=False).size().rename(columns={"size": "cnt"})
    gb2_agg = cp2_gb_new.groupby(["c6", "dt"], as_index=False).size().rename(columns={"size": "cnt"})
    oth_agg = cp2_oth.groupby(["c6", "dt"], as_index=False).size().rename(columns={"size": "cnt"})

    comb_agg = pd.concat([gb1_agg, gb2_agg, xq_agg, oth_agg], ignore_index=True)
    comb_agg = comb_agg.groupby(["c6", "dt"], as_index=False)["cnt"].sum()

    # Map calendar dates (including weekend/holiday posts) to next or same trading day index in all_dts
    def _fill_daily_matrix(agg_df: pd.DataFrame) -> np.ndarray:
        mat = np.zeros((n_s, n_d), dtype=np.int32)
        dt_cache = {}
        for r in agg_df.itertuples(index=False):
            sid = c6_to_sid.get(r.c6)
            if sid is None:
                continue
            d_idx = dt_cache.get(r.dt)
            if d_idx is None:
                pos = bisect.bisect_left(all_dts, r.dt)
                # Map weekend/holiday post to previous trading day if post happened before market or next trading day?
                # Strict causality: map post on calendar day d to the FIRST trading day >= d!
                # That way a weekend post on 2024-12-28 (Sat) lands on 2024-12-30 (Mon),
                # NEVER leaking back to Friday 2024-12-27, and T-6 cutoff handles >=6 trading days gap!
                d_idx = pos if pos < n_d else -1
                dt_cache[r.dt] = d_idx
            if d_idx >= 0:
                mat[sid, d_idx] += int(r.cnt)
        return mat

    mat_comb = _fill_daily_matrix(comb_agg)
    mat_xq = _fill_daily_matrix(xq_agg)

    pref_comb = np.zeros((n_s, n_d + 1), dtype=np.int32)
    pref_comb[:, 1:] = np.cumsum(mat_comb, axis=1)
    pref_xq = np.zeros((n_s, n_d + 1), dtype=np.int32)
    pref_xq[:, 1:] = np.cumsum(mat_xq, axis=1)

    # Monthly matrix for completed-month active ratio (past 12 / 36 completed calendar months < (T-6)[:7])
    all_yms = sorted({d[:7] for d in all_dts} | set(comb_agg["dt"].str[:7].unique()))
    ym_to_idx = {ym: i for i, ym in enumerate(all_yms)}
    n_m = len(all_yms)
    mon_mat = np.zeros((n_s, n_m), dtype=np.int32)
    comb_agg["ym"] = comb_agg["dt"].str[:7]
    m_agg = comb_agg.groupby(["c6", "ym"], as_index=False)["cnt"].sum()
    for r in m_agg.itertuples(index=False):
        sid = c6_to_sid.get(r.c6)
        mi = ym_to_idx.get(r.ym)
        if sid is not None and mi is not None:
            mon_mat[sid, mi] = int(r.cnt)

    # Active-stock mask per month (listed on or before ym_end and not delisted before ym_start)
    mon_med = np.zeros(n_m, dtype=np.float64)
    for mi, ym in enumerate(all_yms):
        active_mask = np.array(
            [(stock_active_ym[c][0] <= ym <= stock_active_ym[c][1]) for c in c6_list],
            dtype=bool,
        )
        if active_mask.any():
            mon_med[mi] = float(np.median(mon_mat[active_mask, mi]))
    above_med = (mon_mat > mon_med[None, :]).astype(np.int16)
    pref_above = np.zeros((n_s, n_m + 1), dtype=np.int16)
    pref_above[:, 1:] = np.cumsum(above_med, axis=1)

    return {
        "pref_comb": pref_comb,
        "pref_xq": pref_xq,
        "pref_above": pref_above,
        "ym_to_idx": ym_to_idx,
        "c6_to_sid": c6_to_sid,
    }


def load_kpl_by_stock(end_date_cutoff: str, dt_to_mkt: dict[str, int], all_dts: list[str]) -> dict[str, tuple[list[int], list[str]]]:
    """Load KPL plates strictly <= end_date_cutoff per stock as sorted (mkt_idx_list, concept_list)."""
    raw = defaultdict(list)
    with open(KPL_JSONL, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            obj = json.loads(line)
            dt = str(obj["date"])[:10]
            if dt > end_date_cutoff:
                continue
            mi = dt_to_mkt.get(dt)
            if mi is None:
                pos = bisect.bisect_left(all_dts, dt)
                if pos >= len(all_dts):
                    continue
                mi = pos
            for p in obj.get("plates", []):
                pname = str(p.get("plate", "")).strip()
                for st in p.get("stocks", []):
                    c6 = str(st[0]).strip().zfill(6)
                    if not c6.startswith(("00", "60", "30", "688", "689")):
                        continue
                    rsn = str(st[2]).strip() if len(st) > 2 else ""
                    if pname not in ("其他", "无", "", "ST板块"):
                        cand = _norm_plate(pname)
                    elif rsn not in ("无", "", "其他", "ST板块"):
                        cand = _norm_plate(re.split(r"[+、,，/；;]", rsn)[0])
                    else:
                        cand = ""
                    if cand:
                        raw[c6].append((mi, cand))
    out = {}
    for c6, items in raw.items():
        items.sort(key=lambda x: x[0])
        out[c6] = ([x[0] for x in items], [x[1] for x in items])
    return out


def _process_stock_chunk(c6_chunk: list[str]) -> dict[str, dict]:
    """Compute Dimensions A, B, D, E, F for a chunk of stocks on bars >= 2021-01-01."""
    df_meta = _G["df_meta"]
    ranges = _G["ranges"]
    kpl_map = _G["kpl_map"]
    all_dts = _G["all_dts"]

    mkt_arr = df_meta["mkt_idx"]
    ac_arr = df_meta["ac"]
    ah_arr = df_meta["ah"]
    turn_arr = df_meta["turn_clean"]
    zt_arr = df_meta["is_zt"]
    streak_arr = df_meta["streak"]
    age_arr = df_meta["list_age"]

    res_chunks = []
    for c6 in c6_chunk:
        s_idx, e_idx = ranges[c6]
        n = e_idx - s_idx
        mkt = mkt_arr[s_idx:e_idx]
        ac = ac_arr[s_idx:e_idx]
        ah = ah_arr[s_idx:e_idx]
        trn = turn_arr[s_idx:e_idx]
        izt = zt_arr[s_idx:e_idx]
        stk = streak_arr[s_idx:e_idx]
        age = age_arr[s_idx:e_idx]

        # Find output range (>= 2021-01-01)
        out_start = int(np.searchsorted(mkt, _G["m_2021_start"]))
        if out_start >= n:
            continue
        m_out = n - out_start

        # Precompute per-stock ZT bars, waves (g15, g20), 2b+ bars, trap bars, turnover prefix
        zt_b = np.flatnonzero(izt)
        zt_m = mkt[zt_b]
        zt_stk = stk[zt_b]
        nz = len(zt_b)

        # Assign causal g15 and g20 wave IDs to each ZT
        g15_id = np.empty(nz, dtype=np.int32)
        g20_id = np.empty(nz, dtype=np.int32)
        if nz > 0:
            g15_id[0] = 0
            g20_id[0] = 0
            for j in range(1, nz):
                gap = int(zt_m[j] - zt_m[j - 1])
                g15_id[j] = g15_id[j - 1] + (1 if gap >= 15 else 0)
                g20_id[j] = g20_id[j - 1] + (1 if gap >= 20 else 0)

        b2_b = np.flatnonzero(stk >= 2)
        b2_m = mkt[b2_b]

        # Causal trap-wave state machine (20d surge >= 30% -> drawdown >= 25%)
        trap_m_list = []
        state = 0
        anchor_start = 0
        peak_ac = 0.0
        for b in range(n):
            if age[b] <= 20:
                anchor_start = b + 1
                continue
            if state == 0:
                lo_i = max(anchor_start, b - 20)
                if b > lo_i:
                    min_lo = float(np.min(ac[lo_i:b]))
                    if min_lo > 0 and (float(ac[b]) / min_lo - 1.0) >= 0.30:
                        state = 1
                        peak_ac = float(ac[b])
            else:
                if float(ac[b]) > peak_ac:
                    peak_ac = float(ac[b])
                elif peak_ac > 0 and (float(ac[b]) / peak_ac - 1.0) <= -0.25:
                    trap_m_list.append(int(mkt[b]))
                    state = 0
                    anchor_start = b + 1
        trap_m_l = trap_m_list
        n_trap = len(trap_m_l)

        turn_pref = np.zeros(n + 1, dtype=np.float64)
        turn_pref[1:] = np.cumsum(trn, dtype=np.float64)

        # KPL items for this stock
        kpl_entry = kpl_map.get(c6)
        kpl_m_l = kpl_entry[0] if kpl_entry else []
        kpl_c = kpl_entry[1] if kpl_entry else []
        n_kpl = len(kpl_m_l)

        # Precompute wave bounds & completed-wave KPL concept (causal <= wm_hi; partial boundary waves evaluated <= m_cut)
        wave_bounds = {}
        wave_kpl_concept = {}
        if nz > 0 and n_kpl > 0:
            w_idx = 0
            while w_idx < nz:
                wid = int(g15_id[w_idx])
                w_end = w_idx
                while w_end + 1 < nz and int(g15_id[w_end + 1]) == wid:
                    w_end += 1
                wm_lo, wm_hi = int(zt_m[w_idx]), int(zt_m[w_end])
                wave_bounds[wid] = (wm_lo, wm_hi)
                kl = bisect.bisect_left(kpl_m_l, wm_lo)
                kr = bisect.bisect_right(kpl_m_l, wm_hi)
                if kr > kl:
                    cnts = Counter(kpl_c[kl:kr])
                    best_c = max(cnts.items(), key=lambda x: x[1])[0]
                    wave_kpl_concept[wid] = best_c
                w_idx = w_end + 1

        mkt_l = mkt.tolist()
        zt_b_l = zt_b.tolist()
        zt_m_l = zt_m.tolist()
        b2_b_l = b2_b.tolist()
        b2_m_l = b2_m.tolist()
        n_b2 = len(b2_b_l)

        # Allocate output arrays for m_out rows
        o_has_act = np.zeros(m_out, dtype=np.int8)
        o_curr_stk = np.zeros(m_out, dtype=np.int16)

        o_w3_15 = np.zeros(m_out, dtype=np.int16)
        o_w5_15 = np.zeros(m_out, dtype=np.int16)
        o_w3_20 = np.zeros(m_out, dtype=np.int16)
        o_w5_20 = np.zeros(m_out, dtype=np.int16)
        o_ay3 = np.zeros(m_out, dtype=np.int8)
        o_ay5 = np.zeros(m_out, dtype=np.int8)
        o_a2y3 = np.zeros(m_out, dtype=np.int8)
        o_a2y5 = np.zeros(m_out, dtype=np.int8)

        o_zt1 = np.zeros(m_out, dtype=np.int16)
        o_zt3 = np.zeros(m_out, dtype=np.int16)
        o_zt5 = np.zeros(m_out, dtype=np.int16)
        o_s3w3 = np.zeros(m_out, dtype=np.int16)
        o_s3w5 = np.zeros(m_out, dtype=np.int16)
        o_s5w5 = np.zeros(m_out, dtype=np.int16)
        o_ms3 = np.zeros(m_out, dtype=np.int16)
        o_ms5 = np.zeros(m_out, dtype=np.int16)

        o_zt1_t1 = np.zeros(m_out, dtype=np.int16)
        o_zt3_t1 = np.zeros(m_out, dtype=np.int16)
        o_w3_15_t1 = np.zeros(m_out, dtype=np.int16)
        o_w5_15_t1 = np.zeros(m_out, dtype=np.int16)

        o_turn1 = np.full(m_out, np.nan, dtype=np.float32)
        o_turn3 = np.full(m_out, np.nan, dtype=np.float32)
        o_trap1 = np.zeros(m_out, dtype=np.int16)
        o_trap3 = np.zeros(m_out, dtype=np.int16)
        o_dd1 = np.full(m_out, np.nan, dtype=np.float32)
        o_dd3 = np.full(m_out, np.nan, dtype=np.float32)

        o_kpl_u3 = np.zeros(m_out, dtype=np.int16)
        o_kpl_u5 = np.zeros(m_out, dtype=np.int16)
        o_kpl_sw = np.full(m_out, np.nan, dtype=np.float32)
        o_kpl_sh = np.full(m_out, np.nan, dtype=np.float32)

        o_cool_zt = np.full(m_out, np.nan, dtype=np.float32)
        o_cool_2b = np.full(m_out, np.nan, dtype=np.float32)

        # Rolling pointers for fast O(1) amortized / O(log K) per bar evaluation
        zp_all = bisect.bisect_left(zt_b_l, out_start)
        bp_all = bisect.bisect_left(b2_b_l, out_start)

        for out_k in range(m_out):
            i = out_start + out_k
            m_T = mkt_l[i]
            while zp_all < nz and zt_b_l[zp_all] < i:
                zp_all += 1
            while bp_all < n_b2 and b2_b_l[bp_all] < i:
                bp_all += 1

            # Active current wave identification (strictly <= i - 1)
            z_end_t1 = zp_all  # zt_b_l[:z_end_t1] are all < i
            if z_end_t1 > 0 and (i - zt_b_l[z_end_t1 - 1]) <= 5:
                o_has_act[out_k] = 1
                ws_pos = z_end_t1 - 1
                while ws_pos > 0 and (zt_b_l[ws_pos] - zt_b_l[ws_pos - 1]) <= 5:
                    ws_pos -= 1
                o_curr_stk[out_k] = z_end_t1 - ws_pos
                cutoff_bar = zt_b_l[ws_pos] - 1
                z_end_ex = ws_pos
            else:
                cutoff_bar = i - 1
                z_end_ex = z_end_t1

            m_cut = mkt_l[cutoff_bar] if cutoff_bar >= 0 else -1

            # Cutoff index for 2b+ bars (<= cutoff_bar)
            b2_end_ex = bp_all
            while b2_end_ex > 0 and b2_b_l[b2_end_ex - 1] > cutoff_bar:
                b2_end_ex -= 1

            m_1y = m_T - 250
            m_3y = m_T - 750
            m_5y = m_T - 1250

            # --- Strict T-1 control metrics ---
            if z_end_t1 > 0:
                z1_t1 = bisect.bisect_left(zt_m_l, m_1y, 0, z_end_t1)
                z3_t1 = bisect.bisect_left(zt_m_l, m_3y, 0, z_end_t1)
                z5_t1 = bisect.bisect_left(zt_m_l, m_5y, 0, z_end_t1)
                o_zt1_t1[out_k] = z_end_t1 - z1_t1
                o_zt3_t1[out_k] = z_end_t1 - z3_t1
                if z_end_t1 > z3_t1:
                    o_w3_15_t1[out_k] = int(g15_id[z_end_t1 - 1] - g15_id[z3_t1] + 1)
                if z_end_t1 > z5_t1:
                    o_w5_15_t1[out_k] = int(g15_id[z_end_t1 - 1] - g15_id[z5_t1] + 1)

            # --- Primary excl_curr_wave metrics ---
            if z_end_ex > 0 and m_cut >= 0:
                z1 = bisect.bisect_left(zt_m_l, m_1y, 0, z_end_ex)
                z3 = bisect.bisect_left(zt_m_l, m_3y, 0, z_end_ex)
                z5 = bisect.bisect_left(zt_m_l, m_5y, 0, z_end_ex)
                o_zt1[out_k] = z_end_ex - z1
                o_zt3[out_k] = z_end_ex - z3
                o_zt5[out_k] = z_end_ex - z5

                if z_end_ex > z3:
                    o_w3_15[out_k] = int(g15_id[z_end_ex - 1] - g15_id[z3] + 1)
                    o_w3_20[out_k] = int(g20_id[z_end_ex - 1] - g20_id[z3] + 1)
                    o_ms3[out_k] = int(np.max(zt_stk[z3:z_end_ex]))
                if z_end_ex > z5:
                    o_w5_15[out_k] = int(g15_id[z_end_ex - 1] - g15_id[z5] + 1)
                    o_w5_20[out_k] = int(g20_id[z_end_ex - 1] - g20_id[z5] + 1)
                    o_ms5[out_k] = int(np.max(zt_stk[z5:z_end_ex]))

                # Active 250-day slices (5 slices from m_T-1250 to m_T-1, restricted to <= m_cut)
                ay_flags = 0
                for sl in range(5):
                    s_lo = m_T - 250 * (sl + 1)
                    s_hi = min(m_T - 250 * sl - 1, m_cut)
                    if s_hi >= s_lo:
                        p_lo = bisect.bisect_left(zt_m_l, s_lo, 0, z_end_ex)
                        p_hi = bisect.bisect_right(zt_m_l, s_hi, 0, z_end_ex)
                        if p_hi > p_lo:
                            ay_flags |= (1 << sl)
                o_ay3[out_k] = bin(ay_flags & 7).count("1")
                o_ay5[out_k] = bin(ay_flags).count("1")

                # Streak >=3 / >=5 waves in 3Y and 5Y
                if z_end_ex > z3:
                    s3_w3 = set()
                    for idx_z in range(z3, z_end_ex):
                        if zt_stk[idx_z] >= 3:
                            s3_w3.add(int(g15_id[idx_z]))
                    o_s3w3[out_k] = len(s3_w3)
                if z_end_ex > z5:
                    s3_w5, s5_w5 = set(), set()
                    for idx_z in range(z5, z_end_ex):
                        if zt_stk[idx_z] >= 3:
                            s3_w5.add(int(g15_id[idx_z]))
                        if zt_stk[idx_z] >= 5:
                            s5_w5.add(int(g15_id[idx_z]))
                    o_s3w5[out_k] = len(s3_w5)
                    o_s5w5[out_k] = len(s5_w5)

                o_cool_zt[out_k] = float(m_T - zt_m_l[z_end_ex - 1])

            if b2_end_ex > 0 and m_cut >= 0:
                a2_flags = 0
                for sl in range(5):
                    s_lo = m_T - 250 * (sl + 1)
                    s_hi = min(m_T - 250 * sl - 1, m_cut)
                    if s_hi >= s_lo:
                        p_lo = bisect.bisect_left(b2_m_l, s_lo, 0, b2_end_ex)
                        p_hi = bisect.bisect_right(b2_m_l, s_hi, 0, b2_end_ex)
                        if p_hi > p_lo:
                            a2_flags |= (1 << sl)
                o_a2y3[out_k] = bin(a2_flags & 7).count("1")
                o_a2y5[out_k] = bin(a2_flags).count("1")
                o_cool_2b[out_k] = float(m_T - b2_m_l[b2_end_ex - 1])

            # --- Dimension D: Chip depreciation & trap waves ---
            if cutoff_bar >= 0:
                b1_lo = bisect.bisect_left(mkt_l, m_1y, 0, cutoff_bar + 1)
                b3_lo = bisect.bisect_left(mkt_l, m_3y, 0, cutoff_bar + 1)
                if cutoff_bar + 1 > b1_lo:
                    o_turn1[out_k] = float(turn_pref[cutoff_bar + 1] - turn_pref[b1_lo])
                if cutoff_bar + 1 > b3_lo:
                    o_turn3[out_k] = float(turn_pref[cutoff_bar + 1] - turn_pref[b3_lo])

            if n_trap > 0 and m_cut >= 0:
                tr_end = bisect.bisect_right(trap_m_l, m_cut)
                tr1_lo = bisect.bisect_left(trap_m_l, m_1y, 0, tr_end)
                tr3_lo = bisect.bisect_left(trap_m_l, m_3y, 0, tr_end)
                o_trap1[out_k] = tr_end - tr1_lo
                o_trap3[out_k] = tr_end - tr3_lo

            if i > 0:
                p1_lo = bisect.bisect_left(mkt_l, m_1y, 0, i)
                p3_lo = bisect.bisect_left(mkt_l, m_3y, 0, i)
                if i > p1_lo:
                    h1 = float(np.max(ah[p1_lo:i]))
                    if h1 > 0:
                        o_dd1[out_k] = float(ac[i - 1]) / h1 - 1.0
                if i > p3_lo:
                    h3 = float(np.max(ah[p3_lo:i]))
                    if h3 > 0:
                        o_dd3[out_k] = float(ac[i - 1]) / h3 - 1.0

            # --- Dimension E: KPL Theme purity (date <= m_cut < m_T) ---
            if n_kpl > 0 and m_cut >= 0:
                k_end = bisect.bisect_right(kpl_m_l, m_cut)
                k3_lo = bisect.bisect_left(kpl_m_l, m_3y, 0, k_end)
                k5_lo = bisect.bisect_left(kpl_m_l, m_5y, 0, k_end)
                if k_end > k3_lo:
                    o_kpl_u3[out_k] = len(set(kpl_c[k3_lo:k_end]))
                if k_end > k5_lo:
                    sub_c = kpl_c[k5_lo:k_end]
                    o_kpl_u5[out_k] = len(set(sub_c))
                    top_cnt = max(Counter(sub_c).values())
                    o_kpl_sh[out_k] = float(top_cnt) / float(len(sub_c))

                if z_end_ex > 0 and wave_bounds:
                    z5 = bisect.bisect_left(zt_m_l, m_5y, 0, z_end_ex)
                    if z_end_ex > z5:
                        seen_w = []
                        prev_w = -1
                        for idx_z in range(z5, z_end_ex):
                            wid = int(g15_id[idx_z])
                            if wid != prev_w:
                                prev_w = wid
                                wm_lo, wm_hi = wave_bounds[wid]
                                if wm_hi <= m_cut:
                                    c_val = wave_kpl_concept.get(wid)
                                    if c_val is not None:
                                        seen_w.append(c_val)
                                else:
                                    kl = bisect.bisect_left(kpl_m_l, wm_lo, 0, k_end)
                                    kr = k_end
                                    if kr > kl:
                                        cnts = Counter(kpl_c[kl:kr])
                                        seen_w.append(max(cnts.items(), key=lambda x: x[1])[0])
                        if len(seen_w) >= 2:
                            last5 = seen_w[-5:]
                            sw_cnt = sum(1 for k in range(1, len(last5)) if last5[k] != last5[k - 1])
                            o_kpl_sw[out_k] = float(sw_cnt) / float(len(last5) - 1)

        out_dts = [all_dts[int(m)] for m in mkt[out_start:]]
        res_chunks.append({
            "c6": np.full(m_out, c6, dtype=object),
            "dt": np.array(out_dts, dtype=object),
            "mkt_idx": mkt[out_start:].astype(np.int32),
            "list_age": age[out_start:].astype(np.int32),
            "has_active_wave": o_has_act,
            "curr_wave_streak": o_curr_stk,
            "waves_3y_g15": o_w3_15,
            "waves_5y_g15": o_w5_15,
            "waves_3y_g20": o_w3_20,
            "waves_5y_g20": o_w5_20,
            "active_years_3y": o_ay3,
            "active_years_5y": o_ay5,
            "active_2b_years_3y": o_a2y3,
            "active_2b_years_5y": o_a2y5,
            "zt_cnt_1y": o_zt1,
            "zt_cnt_3y": o_zt3,
            "zt_cnt_5y": o_zt5,
            "streak3_waves_3y": o_s3w3,
            "streak3_waves_5y": o_s3w5,
            "streak5_waves_5y": o_s5w5,
            "max_streak_3y": o_ms3,
            "max_streak_5y": o_ms5,
            "zt_cnt_1y_t1": o_zt1_t1,
            "zt_cnt_3y_t1": o_zt3_t1,
            "waves_3y_g15_t1": o_w3_15_t1,
            "waves_5y_g15_t1": o_w5_15_t1,
            "cum_turnover_1y": o_turn1,
            "cum_turnover_3y": o_turn3,
            "trap_waves_1y": o_trap1,
            "trap_waves_3y": o_trap3,
            "dd_from_1y_high": o_dd1,
            "dd_from_3y_high": o_dd3,
            "kpl_unique_plates_3y": o_kpl_u3,
            "kpl_unique_plates_5y": o_kpl_u5,
            "kpl_plate_switch_ratio": o_kpl_sw,
            "kpl_top_plate_share": o_kpl_sh,
            "cool_days_since_last_zt": o_cool_zt,
            "cool_days_since_last_2b": o_cool_2b,
        })
    if not res_chunks:
        return {}
    keys = res_chunks[0].keys()
    return {k: np.concatenate([ch[k] for ch in res_chunks]) for k in keys}


def build_old_hot_pit(end_date_cutoff: str, n_workers: int = 8, save_path: str | None = None) -> pd.DataFrame:
    t0 = time.time()
    print(f"[Step1] Building 6-dim PIT warehouse (cutoff={end_date_cutoff}, workers={n_workers})...")
    df, all_dts, dt_to_mkt = load_daily_panel(end_date_cutoff)
    print(f"  Loaded bars >=2015-06-01: {len(df):,} rows, {df['c6'].nunique()} stocks, {len(all_dts)} trading days ({time.time()-t0:.1f}s)")

    # Build stock active month bounds and CSR ranges
    c6_arr = df["c6"].to_numpy()
    dt_arr = df["dt"].to_numpy()
    chg = np.flatnonzero(np.concatenate([[True], c6_arr[1:] != c6_arr[:-1], [True]]))
    c6_list = [str(c6_arr[chg[k]]) for k in range(len(chg) - 1)]
    ranges = {c6_list[k]: (int(chg[k]), int(chg[k + 1])) for k in range(len(c6_list))}
    stock_active_ym = {
        c6_list[k]: (str(dt_arr[chg[k]])[:7], str(dt_arr[chg[k + 1] - 1])[:7])
        for k in range(len(c6_list))
    }

    comm = load_community_daily_and_monthly(end_date_cutoff, c6_list, all_dts, dt_to_mkt, stock_active_ym)
    print(f"  Loaded community matrices ({time.time()-t0:.1f}s)")
    kpl_map = load_kpl_by_stock(end_date_cutoff, dt_to_mkt, all_dts)
    print(f"  Loaded KPL plates: {len(kpl_map)} stocks ({time.time()-t0:.1f}s)")

    m_2021_start = bisect.bisect_left(all_dts, "2021-01-01")
    _G.clear()
    _G["df_meta"] = {
        "mkt_idx": df["mkt_idx"].to_numpy(),
        "ac": df["ac"].to_numpy(),
        "ah": df["ah"].to_numpy(),
        "turn_clean": df["turn_clean"].to_numpy(),
        "is_zt": df["is_zt"].to_numpy(),
        "streak": df["streak"].to_numpy(),
        "list_age": df["list_age"].to_numpy(),
    }
    _G["ranges"] = ranges
    _G["kpl_map"] = kpl_map
    _G["all_dts"] = all_dts
    _G["m_2021_start"] = m_2021_start

    # Split stocks across <=8 worker processes via fork context
    n_workers = min(8, max(1, n_workers))
    chunks = [c6_list[i::n_workers] for i in range(n_workers)]
    if n_workers > 1:
        ctx = mp.get_context("fork")
        with ctx.Pool(processes=n_workers) as pool:
            parts = pool.map(_process_stock_chunk, chunks)
    else:
        parts = [_process_stock_chunk(c6_list)]
    _G.clear()

    valid_parts = [p for p in parts if p]
    keys = valid_parts[0].keys()
    merged = {k: np.concatenate([p[k] for p in valid_parts]) for k in keys}
    out_df = pd.DataFrame(merged)
    out_df.sort_values(["dt", "c6"], inplace=True)
    out_df.reset_index(drop=True, inplace=True)
    print(f"  Computed A/B/D/E/F on {len(out_df):,} rows ({time.time()-t0:.1f}s)")

    # --- Dimension C: Community counts up to T-6 + exact daily cross-sectional percentiles ---
    sids = out_df["c6"].map(comm["c6_to_sid"]).to_numpy(dtype=np.int32)
    mkts = out_df["mkt_idx"].to_numpy(dtype=np.int32)

    m_end = np.maximum(0, mkts - 5)  # pref[..., m_end] sums indices < m_T - 5, i.e., <= m_T - 6!
    m_1y_lo = np.maximum(0, mkts - 250)
    m_3y_lo = np.maximum(0, mkts - 750)
    # Clamp m_1y_lo <= m_end
    m_1y_lo = np.minimum(m_1y_lo, m_end)
    m_3y_lo = np.minimum(m_3y_lo, m_end)

    pref_comb = comm["pref_comb"]
    pref_xq = comm["pref_xq"]
    out_df["comm_posts_1y"] = (pref_comb[sids, m_end] - pref_comb[sids, m_1y_lo]).astype(np.int32)
    out_df["comm_posts_3y"] = (pref_comb[sids, m_end] - pref_comb[sids, m_3y_lo]).astype(np.int32)
    xq_1y = (pref_xq[sids, m_end] - pref_xq[sids, m_1y_lo]).astype(np.int32)
    xq_3y = (pref_xq[sids, m_end] - pref_xq[sids, m_3y_lo]).astype(np.int32)
    out_df["_xq_1y"] = xq_1y
    out_df["_xq_3y"] = xq_3y

    # Cross-sectional causal percentiles per day T
    out_df["comm_posts_1y_pct"] = out_df.groupby("dt", sort=False)["comm_posts_1y"].rank(method="average", pct=True).astype(np.float32)
    out_df["comm_posts_3y_pct"] = out_df.groupby("dt", sort=False)["comm_posts_3y"].rank(method="average", pct=True).astype(np.float32)
    out_df["xq_posts_1y_pct"] = out_df.groupby("dt", sort=False)["_xq_1y"].rank(method="average", pct=True).astype(np.float32)
    out_df["xq_posts_3y_pct"] = out_df.groupby("dt", sort=False)["_xq_3y"].rank(method="average", pct=True).astype(np.float32)
    out_df.drop(columns=["_xq_1y", "_xq_3y"], inplace=True)

    # Active-month ratio over past 12 / 36 COMPLETED calendar months strictly < (T-6)[:7]
    ym_to_idx = comm["ym_to_idx"]
    pref_above = comm["pref_above"]
    t6_ym_idx = np.array([ym_to_idx.get(all_dts[max(0, m - 6)][:7], 0) for m in mkts], dtype=np.int32)
    m12_lo = np.maximum(0, t6_ym_idx - 12)
    m36_lo = np.maximum(0, t6_ym_idx - 36)
    den12 = np.maximum(1, t6_ym_idx - m12_lo).astype(np.float32)
    den36 = np.maximum(1, t6_ym_idx - m36_lo).astype(np.float32)
    out_df["comm_active_month_ratio_1y"] = ((pref_above[sids, t6_ym_idx] - pref_above[sids, m12_lo]) / den12).astype(np.float32)
    out_df["comm_active_month_ratio_3y"] = ((pref_above[sids, t6_ym_idx] - pref_above[sids, m36_lo]) / den36).astype(np.float32)

    # --- Dimension F: Time & regime tags ---
    out_df["cool_bin_zt"] = [_cool_bin(x) for x in out_df["cool_days_since_last_zt"].to_numpy()]
    out_df["cool_bin_2b"] = [_cool_bin(x) for x in out_df["cool_days_since_last_2b"].to_numpy()]
    dt_str = out_df["dt"].astype(str)
    out_df["year"] = dt_str.str[:4].astype(np.int16)
    out_df["era_tag"] = np.where(out_df["year"] <= 2023, "2021_2023_bear", "2024_2026_active")
    out_df["is_oos_split"] = np.where(dt_str <= "2024-12-31", "IS", "OOS")

    out_df.drop(columns=["mkt_idx"], inplace=True)

    if save_path:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        out_df.to_parquet(save_path, index=False, compression="zstd")
        print(f"  Saved {save_path}: {len(out_df):,} rows x {out_df.shape[1]} cols ({os.path.getsize(save_path)/1e6:.1f} MB, {time.time()-t0:.1f}s)")
    return out_df


def run_truncation_proof(full_df: pd.DataFrame) -> dict:
    """Physically truncate ALL raw inputs <= 2024-12-31, rebuild from scratch, and verify max_abs_diff == 0.0."""
    trunc_df = build_old_hot_pit("2024-12-31", n_workers=8, save_path=None)
    sub_full = full_df[full_df["dt"] <= "2024-12-31"].sort_values(["dt", "c6"]).reset_index(drop=True)
    trunc_df = trunc_df.sort_values(["dt", "c6"]).reset_index(drop=True)
    assert len(sub_full) == len(trunc_df), f"Row count mismatch: {len(sub_full)} vs {len(trunc_df)}"
    assert (sub_full["c6"].to_numpy() == trunc_df["c6"].to_numpy()).all()
    assert (sub_full["dt"].to_numpy() == trunc_df["dt"].to_numpy()).all()

    max_diff = 0.0
    col_diffs = {}
    for col in sub_full.columns:
        if col in ("c6", "dt"):
            continue
        s1, s2 = sub_full[col], trunc_df[col]
        if pd.api.types.is_numeric_dtype(s1):
            v1, v2 = s1.to_numpy(np.float64), s2.to_numpy(np.float64)
            nan_mismatch = int((np.isnan(v1) != np.isnan(v2)).sum())
            assert nan_mismatch == 0, f"NaN mask mismatch on {col}: {nan_mismatch}"
            valid = ~np.isnan(v1)
            d = float(np.max(np.abs(v1[valid] - v2[valid]))) if valid.any() else 0.0
            col_diffs[col] = d
            max_diff = max(max_diff, d)
        else:
            neq = int((s1.astype(str).to_numpy() != s2.astype(str).to_numpy()).sum())
            assert neq == 0, f"String mismatch on {col}: {neq}"
            col_diffs[col] = 0.0
    assert max_diff == 0.0, f"Truncation leakage detected: max_abs_diff={max_diff}"
    return {
        "cutoff": "2024-12-31",
        "rows_checked": int(len(trunc_df)),
        "cols_checked": int(len(col_diffs)),
        "max_abs_diff": max_diff,
        "pass": True,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cutoff", default="2026-11-25")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--skip-trunc", action="store_true")
    args = parser.parse_args()

    full_df = build_old_hot_pit(args.cutoff, n_workers=args.workers, save_path=OUT_PARQUET)
    if not args.skip_trunc:
        proof = run_truncation_proof(full_df)
        print("TRUNCATION_PROOF_20241231:", json.dumps(proof, ensure_ascii=False))
        with open(f"{OUT_DIR}/step1_truncation_proof.json", "w", encoding="utf-8") as f:
            json.dump(proof, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()

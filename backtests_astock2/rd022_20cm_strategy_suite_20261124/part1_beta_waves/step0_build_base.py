#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD022 Part 1 - Step 0: Build strict PIT A-share market daily stats & 20cm stock panel (2020-09-01 ~ 2026-11-23)."""

import json
import os
import sqlite3
import time
from collections import defaultdict

import numpy as np
import pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
OUT_DIR = f"{SIM}/backtests_astock2/rd022_20cm_strategy_suite_20261124/part1_beta_waves"
os.makedirs(OUT_DIR, exist_ok=True)

A_DAILY = f"{SIM}/data/cn_hk_price_db/a_daily.parquet"
A_DELISTED = f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet"
SH300_PQ = f"{SIM}/backtests_astock2/commodities_leadlag_10y_20261123/data_cache/sh000300.parquet"
IDX_CACHE = f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json"
ZT_DB = f"{SIM}/data/zt_micro_tape_5y_pit.db"
NOTICES_DB = f"{SIM}/data/cninfo_notices_5y_pit.db"
IR_DB = f"{SIM}/data/cninfo_ir_qa_5y_pit.db"
CSRC_PIT = f"{SIM}/data/csrc_industry_pit_clean.csv"
IND_CSV = f"{SIM}/data/industry.csv"

FEE_RT = 0.0030  # 0.30% roundtrip transaction cost


def load_index_series():
    sh_df = pd.read_parquet(SH300_PQ)
    sh_map = {str(d)[:10]: float(v) for d, v in zip(sh_df.index, sh_df["sh000300"])}
    with open(IDX_CACHE, "r", encoding="utf-8") as f:
        ik = json.load(f)
    for dt, val in ik.get("sh000300", {}).items():
        sh_map[dt] = float(val)
    sh000001_map = {dt: float(v) for dt, v in ik.get("sh000001", {}).items()}
    sz399107_map = {dt: float(v) for dt, v in ik.get("sz399107", {}).items()}
    return sh_map, sh000001_map, sz399107_map


def build_pit_name_and_st_events():
    """Collect PIT (code, date, name) observations from notices, ir_qa, zt_micro_tape, and CSRC CSV."""
    obs = defaultdict(list)  # c6 -> list of (date_str, name)

    # 1. zt_micro_tape (exact trade_date name)
    conn_zt = sqlite3.connect(f"file:{ZT_DB}?mode=ro", uri=True)
    for dt, sc, nm in conn_zt.execute(
        "SELECT trade_date, sec_code, sec_name FROM zt_micro_tape WHERE sec_name IS NOT NULL"
    ):
        c6 = str(sc).strip()[:6].zfill(6)
        if nm:
            obs[c6].append((str(dt)[:10], str(nm).strip()))
    conn_zt.close()

    # 2. cninfo notices (trade_date_avail, sec_name)
    conn_n = sqlite3.connect(f"file:{NOTICES_DB}?mode=ro", uri=True)
    for dt, sc, nm in conn_n.execute(
        "SELECT trade_date_avail, sec_code, sec_name FROM notices WHERE sec_name IS NOT NULL AND (sec_code LIKE '30%' OR sec_code LIKE '688%' OR sec_code LIKE '689%')"
    ):
        c6 = str(sc).strip()[:6].zfill(6)
        if nm and dt:
            obs[c6].append((str(dt)[:10], str(nm).strip()))
    conn_n.close()

    # 3. ir_qa
    conn_ir = sqlite3.connect(f"file:{IR_DB}?mode=ro", uri=True)
    for dt, sc, nm in conn_ir.execute(
        "SELECT trade_date_avail, sec_code, sec_name FROM ir_qa WHERE sec_name IS NOT NULL AND (sec_code LIKE '30%' OR sec_code LIKE '688%' OR sec_code LIKE '689%')"
    ):
        c6 = str(sc).strip()[:6].zfill(6)
        if nm and dt:
            obs[c6].append((str(dt)[:10], str(nm).strip()))
    conn_ir.close()

    # Static fallback name map from CSRC CSV (latest known name for stocks with zero notices/zt)
    fallback_names = {}
    for p in [CSRC_PIT, IND_CSV]:
        if os.path.exists(p):
            df_c = pd.read_csv(p, dtype=str)
            ccol = "sec_code" if "sec_code" in df_c.columns else "code"
            ncol = "code_name" if "code_name" in df_c.columns else "name"
            for raw_c, nm in zip(df_c[ccol].fillna(""), df_c[ncol].fillna("")):
                c6 = raw_c[-6:] if len(raw_c) >= 6 else raw_c
                if c6 and nm:
                    fallback_names[c6] = nm.strip()

    # Sort & deduplicate PIT name events per c6
    pit_names = {}
    for c6, pairs in obs.items():
        pairs.sort(key=lambda x: x[0])
        # Keep only state transitions or sorted list
        pit_names[c6] = pairs

    return pit_names, fallback_names


def main():
    t0 = time.time()
    print("[Step 0] Loading a_daily + a_delisted_daily...")
    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "amount", "oshare", "turn"]
    a1 = pd.read_parquet(A_DAILY, columns=cols)
    a2 = pd.read_parquet(A_DELISTED, columns=cols)
    a1["_act"] = 1
    a2["_act"] = 0
    full = pd.concat([a1, a2], ignore_index=True)
    full = full[full["ticker"].str.endswith((".SH", ".SZ"))].copy()
    full["c6"] = full["ticker"].str[:6]
    full["dt"] = full["date"].dt.strftime("%Y-%m-%d")

    # Compute true listing start date across ALL history (before slicing >= 2020-09-01)
    first_dt_map = full.groupby("c6")["dt"].min().to_dict()
    print(f"  Full A-share universe rows={len(full):,}, unique codes={len(first_dt_map):,} ({time.time()-t0:.1f}s)")

    # Slice >= 2020-08-01 for warm-up and deduplicate keeping active
    sub = full[(full["dt"] >= "2020-08-01") & (full["dt"] <= "2026-11-23")].copy()
    sub = sub.sort_values(["c6", "dt", "_act"], ascending=[True, True, False]).drop_duplicates(["c6", "dt"]).reset_index(drop=True)
    del full, a1, a2

    # Compute exact prev adj_close, prev close, daily return, limit up/down prices
    g = sub.groupby("c6", sort=False)
    sub["adjf"] = np.where(sub["close"] > 0, sub["adj_close"] / sub["close"], 1.0)
    sub["prev_adj_c"] = g["adj_close"].shift(1)
    sub["prev_c_adj"] = sub["prev_adj_c"] / sub["adjf"]
    sub["ret"] = sub["adj_close"] / sub["prev_adj_c"] - 1.0
    sub["is_20cm"] = sub["c6"].str.startswith(("30", "688", "689"))

    # Listing trading-day index since IPO (only strictly accurate for IPOs >= 2020-08-01; older IPOs get >= 100)
    sub["first_dt"] = sub["c6"].map(first_dt_map)
    sub["list_day_idx"] = g.cumcount()
    sub["is_recent_ipo_10d"] = (sub["first_dt"] >= "2020-08-01") & (sub["list_day_idx"] < 10)
    sub["is_recent_ipo_5d"] = (sub["first_dt"] >= "2020-08-01") & (sub["list_day_idx"] < 5)

    # Approximate limit up / limit down for all stocks (for market stats)
    lim_pct = np.where(sub["is_20cm"], 0.20, 0.10)
    sub["zt_px"] = np.round(sub["prev_c_adj"] * (1.0 + lim_pct), 2)
    sub["dt_px"] = np.round(sub["prev_c_adj"] * (1.0 - lim_pct), 2)
    sub["is_zt"] = (sub["close"] >= sub["zt_px"] - 0.011) & (sub["ret"] >= np.where(sub["is_20cm"], 0.195, 0.095)) & (~sub["is_recent_ipo_5d"]) & (sub["volume"] > 0)
    sub["touch_zt"] = (sub["high"] >= sub["zt_px"] - 0.011) & (~sub["is_recent_ipo_5d"]) & (sub["volume"] > 0)
    sub["is_yizi_zt"] = sub["is_zt"] & (sub["low"] >= sub["zt_px"] - 0.011)
    sub["is_dt"] = (sub["close"] <= sub["dt_px"] + 0.011) & (sub["ret"] <= np.where(sub["is_20cm"], -0.195, -0.095)) & (~sub["is_recent_ipo_5d"]) & (sub["volume"] > 0)
    sub["is_yizi_dt"] = sub["is_dt"] & (sub["high"] <= sub["dt_px"] + 0.011)

    # Streak for yesterday's first-board promotion rate
    zt_int = sub["is_zt"].astype(int)
    sub["streak"] = zt_int.groupby([sub["c6"], (zt_int != g["is_zt"].shift(1).fillna(False).astype(int)).cumsum()]).cumsum() * zt_int
    sub["prev_streak"] = g["streak"].shift(1).fillna(0).astype(int)
    sub["prev_is_zt"] = g["is_zt"].shift(1).fillna(False)

    # Market-wide daily statistics (excluding recent IPO first 5d and anomalous >22% / suspended)
    valid_mkt = (~sub["is_recent_ipo_5d"]) & (sub["volume"] > 0) & (sub["ret"].abs() <= 0.22) & sub["ret"].notna()
    m_df = sub[valid_mkt].copy()
    m_df["mcap_yi"] = m_df["oshare"] * m_df["close"] / 1e8

    print("[Step 0] Computing daily market panel...")
    daily_grp = m_df.groupby("dt", sort=True)
    mkt = pd.DataFrame({
        "n_all": daily_grp["c6"].count(),
        "ew_ret_all": daily_grp["ret"].mean(),
        "med_ret_all": daily_grp["ret"].median(),
        "up_ratio_all": daily_grp["ret"].apply(lambda s: (s > 0).mean()),
        "tot_amt_trillion": daily_grp["amount"].sum() / 1e12,
        "zt_all_cnt": daily_grp["is_zt"].sum(),
        "touch_zt_all_cnt": daily_grp["touch_zt"].sum(),
        "dt_all_cnt": daily_grp["is_dt"].sum(),
        "yizi_zt_cnt": daily_grp["is_yizi_zt"].sum(),
        "zt_10cm_cnt": m_df[~m_df["is_20cm"]].groupby("dt")["is_zt"].sum(),
        "zt_20cm_cnt": m_df[m_df["is_20cm"]].groupby("dt")["is_zt"].sum(),
        "max_streak_10cm": m_df[~m_df["is_20cm"]].groupby("dt")["streak"].max(),
        "yest_1b_cnt": m_df[m_df["prev_streak"] == 1].groupby("dt")["c6"].count(),
        "yest_1b_promo_cnt": m_df[(m_df["prev_streak"] == 1) & m_df["is_zt"]].groupby("dt")["c6"].count(),
        "ew_ret_10cm": m_df[~m_df["is_20cm"]].groupby("dt")["ret"].mean(),
        "ew_ret_20cm": m_df[m_df["is_20cm"]].groupby("dt")["ret"].mean(),
        "n_20cm": m_df[m_df["is_20cm"]].groupby("dt")["c6"].count(),
        "up_ratio_20cm": m_df[m_df["is_20cm"]].groupby("dt")["ret"].apply(lambda s: (s > 0).mean()),
        "amt_20cm_trillion": m_df[m_df["is_20cm"]].groupby("dt")["amount"].sum() / 1e12,
    }).fillna(0.0).sort_index()

    # Cap-weighted 20cm, ChiNext, STAR daily returns (for PIT abnormal deviation baseline & benchmark)
    def capw_ret(df_slice):
        w = df_slice["oshare"].fillna(0) * df_slice["close"].fillna(0)
        return df_slice.assign(_wx=w * df_slice["ret"], _w=w).groupby("dt")[["_wx", "_w"]].sum().eval("_wx / _w")

    m20 = m_df[m_df["is_20cm"]].copy()
    mkt["capw_ret_20cm"] = capw_ret(m20)
    mkt["capw_ret_cyb"] = capw_ret(m20[m20["c6"].str.startswith("30")])
    mkt["capw_ret_kcb"] = capw_ret(m20[m20["c6"].str.startswith(("688", "689"))])
    mkt["ew_ret_cyb"] = m20[m20["c6"].str.startswith("30")].groupby("dt")["ret"].mean()
    mkt["ew_ret_kcb"] = m20[m20["c6"].str.startswith(("688", "689"))].groupby("dt")["ret"].mean()
    mkt["bigup7_20cm_cnt"] = m20[m20["ret"] >= 0.07].groupby("dt")["c6"].count()
    mkt["bigup5_20cm_cnt"] = m20[m20["ret"] >= 0.05].groupby("dt")["c6"].count()
    mkt["bigup10_20cm_cnt"] = m20[m20["ret"] >= 0.10].groupby("dt")["c6"].count()
    mkt = mkt.fillna(0.0)

    # Derived market features
    mkt["seal_rate_all"] = np.where(mkt["touch_zt_all_cnt"] > 0, mkt["zt_all_cnt"] / mkt["touch_zt_all_cnt"], 0.0)
    mkt["yest_1b_promo_rate"] = np.where(mkt["yest_1b_cnt"] > 0, mkt["yest_1b_promo_cnt"] / mkt["yest_1b_cnt"], 0.0)
    mkt["amt_ma20_trillion"] = mkt["tot_amt_trillion"].rolling(20, min_periods=5).mean()
    mkt["amt_ratio_20"] = mkt["tot_amt_trillion"] / mkt["amt_ma20_trillion"]
    mkt["ew_idx_all"] = (1.0 + mkt["ew_ret_all"]).cumprod()
    mkt["ew_idx_20cm"] = (1.0 + mkt["ew_ret_20cm"]).cumprod()
    mkt["ew_idx_all_ma20"] = mkt["ew_idx_all"].rolling(20, min_periods=5).mean()
    mkt["ew_idx_20cm_ma20"] = mkt["ew_idx_20cm"].rolling(20, min_periods=5).mean()
    mkt["mkt_is_above_ma20"] = mkt["ew_idx_all"] > mkt["ew_idx_all_ma20"]
    mkt["mkt_20cm_above_ma20"] = mkt["ew_idx_20cm"] > mkt["ew_idx_20cm_ma20"]
    mkt["mkt_prev1d_ew"] = mkt["ew_ret_all"].shift(1)
    mkt["mkt_prev3d_ew"] = mkt["ew_idx_all"].shift(1) / mkt["ew_idx_all"].shift(4) - 1.0
    mkt["mkt_prev5d_ew"] = mkt["ew_idx_all"].shift(1) / mkt["ew_idx_all"].shift(6) - 1.0
    mkt["mkt_prev20d_ew"] = mkt["ew_idx_all"].shift(1) / mkt["ew_idx_all"].shift(21) - 1.0
    mkt["mkt_20cm_prev5d_ew"] = mkt["ew_idx_20cm"].shift(1) / mkt["ew_idx_20cm"].shift(6) - 1.0
    mkt["mkt_20cm_prev20d_ew"] = mkt["ew_idx_20cm"].shift(1) / mkt["ew_idx_20cm"].shift(21) - 1.0

    sh_map, sh1_map, sz_map = load_index_series()
    mkt["sh000300"] = [sh_map.get(d, np.nan) for d in mkt.index]
    mkt["sh000300"] = mkt["sh000300"].ffill()
    mkt["sh000300_ret"] = mkt["sh000300"].pct_change().fillna(0.0)
    mkt["sh000001"] = [sh1_map.get(d, np.nan) for d in mkt.index]
    mkt["sz399107"] = [sz_map.get(d, np.nan) for d in mkt.index]

    mkt_reset = mkt.reset_index().rename(columns={"index": "dt"})
    mkt_reset.to_parquet(f"{OUT_DIR}/market_daily.parquet", index=False)
    print(f"  Saved market_daily.parquet: {len(mkt_reset)} days ({mkt_reset['dt'].min()} ~ {mkt_reset['dt'].max()})")

    # Now build 20cm clean panel
    print("[Step 0] Building 20cm panel with PIT ST flags and forward tradable exits...")
    p20 = sub[sub["is_20cm"]].copy().reset_index(drop=True)
    del sub, m_df

    # PIT ST & Name tagging
    pit_names, fallback_names = build_pit_name_and_st_events()
    unique_c6 = p20["c6"].unique()
    import bisect
    # Vectorized PIT name lookup per stock
    name_col = []
    st_col = []
    for c6, dt_series in p20.groupby("c6", sort=False)["dt"]:
        ev = pit_names.get(c6)
        fb = fallback_names.get(c6, c6)
        if not ev:
            for _ in dt_series:
                name_col.append(fb)
                st_col.append(("ST" in fb) or ("退" in fb))
        else:
            ev_dts = [x[0] for x in ev]
            ev_nms = [x[1] for x in ev]
            for d in dt_series:
                pos = bisect.bisect_right(ev_dts, d) - 1
                nm = ev_nms[pos] if pos >= 0 else fb
                name_col.append(nm)
                st_col.append(("ST" in nm) or ("退" in nm))

    # Wait: groupby order != DataFrame row order if not sorted! Verify p20 is sorted by ['c6', 'dt']
    # p20 IS sorted by ['c6', 'dt'] from earlier sort_values(["c6", "dt", "_act"]), groupby(sort=False) preserves exact order
    p20["sec_name"] = name_col
    p20["is_st_pit"] = st_col
    p20["is_star"] = p20["c6"].str.startswith(("688", "689"))
    p20["is_clean_universe"] = (~p20["is_recent_ipo_10d"]) & (~p20["is_st_pit"]) & (p20["ret"].abs() <= 0.22) & (p20["volume"] > 0)

    # Adjusted OHLC
    p20["adj_open"] = p20["open"] * p20["adjf"]
    p20["adj_high"] = p20["high"] * p20["adjf"]
    p20["adj_low"] = p20["low"] * p20["adjf"]
    p20["circ_mcap"] = p20["oshare"] * p20["close"] / 1e8

    # Map benchmark capw returns for CYB / KCB deviation calculations
    cyb_lvl_map = (1.0 + mkt["capw_ret_cyb"]).cumprod().to_dict()
    kcb_lvl_map = (1.0 + mkt["capw_ret_kcb"]).cumprod().to_dict()
    p20["bench_lvl"] = np.where(p20["is_star"], p20["dt"].map(kcb_lvl_map), p20["dt"].map(cyb_lvl_map))

    # Forward trading-day exit calculation per stock (enforcing suspension & limit-down deferral!)
    all_dts = mkt_reset["dt"].tolist()
    dt_to_gidx = {d: i for i, d in enumerate(all_dts)}
    p20["gidx"] = p20["dt"].map(dt_to_gidx)

    # Precompute per-stock arrays for exact forward execution
    n_rows = len(p20)
    # Route A (T0 close buy):
    # - buyable_A = is_clean_universe & (~is_zt)
    # - exits: T+1 close, T+2 close, T+3 close, T+5 close (all limit-down deferred), plus dynamic exits in step3
    # Route B (T+1 open buy):
    # - buyable_B = is_clean_universe & next_day_exists_t1 & (t1_open < t1_zt_px - 0.011) & (t1_vol > 0)
    # - exits: T+2 close, T+3 close, T+5 close (limit-down deferred)
    p20["buyable_A"] = p20["is_clean_universe"] & (~p20["is_zt"])

    buyable_B = np.zeros(n_rows, dtype=bool)
    t1_open_ret = np.full(n_rows, np.nan)
    t1_adj_open = np.full(n_rows, np.nan)
    t1_dt_arr = np.empty(n_rows, dtype=object); t1_dt_arr[:] = ""

    # Returns net of 0.30% fee
    retA_t1 = np.full(n_rows, np.nan)
    retA_t2 = np.full(n_rows, np.nan)
    retA_t3 = np.full(n_rows, np.nan)
    retA_t5 = np.full(n_rows, np.nan)
    exitdtA_t1 = np.empty(n_rows, dtype=object); exitdtA_t1[:] = ""
    exitdtA_t2 = np.empty(n_rows, dtype=object); exitdtA_t2[:] = ""
    exitdtA_t3 = np.empty(n_rows, dtype=object); exitdtA_t3[:] = ""
    exitdtA_t5 = np.empty(n_rows, dtype=object); exitdtA_t5[:] = ""

    retB_t2 = np.full(n_rows, np.nan)
    retB_t3 = np.full(n_rows, np.nan)
    retB_t5 = np.full(n_rows, np.nan)
    exitdtB_t2 = np.empty(n_rows, dtype=object); exitdtB_t2[:] = ""
    exitdtB_t3 = np.empty(n_rows, dtype=object); exitdtB_t3[:] = ""
    exitdtB_t5 = np.empty(n_rows, dtype=object); exitdtB_t5[:] = ""

    # Deviation headroom (3d30, 10d100, 30d200)
    head_3d30 = np.full(n_rows, np.nan)
    head_10d100 = np.full(n_rows, np.nan)
    head_30d200 = np.full(n_rows, np.nan)

    g_idx_arr = p20["gidx"].to_numpy()
    ac_arr = p20["adj_close"].to_numpy()
    ao_arr = p20["adj_open"].to_numpy()
    op_arr = p20["open"].to_numpy()
    zt_arr = p20["zt_px"].to_numpy()
    is_dt_arr = p20["is_dt"].to_numpy()
    vol_arr = p20["volume"].to_numpy()
    dt_arr = p20["dt"].to_numpy()
    bl_arr = p20["bench_lvl"].to_numpy()
    clean_arr = p20["is_clean_universe"].to_numpy()

    def find_sell_idx(start_row, end_row, min_gidx):
        """Find first tradable non-limit-down day with gidx >= min_gidx."""
        for j in range(start_row, end_row):
            if g_idx_arr[j] >= min_gidx and vol_arr[j] > 0 and (not is_dt_arr[j]):
                return j
        return -1

    for c6, grp_idx in p20.groupby("c6", sort=False).groups.items():
        # grp_idx is contiguous because p20 is sorted by (c6, dt)
        s_i = int(grp_idx[0])
        e_i = int(grp_idx[-1]) + 1
        m_len = e_i - s_i

        # Compute window-max deviations for 3d, 10d, 30d
        ac_s = ac_arr[s_i:e_i]
        bl_s = bl_arr[s_i:e_i]
        for k_max, thresh, out_arr in [(3, 0.30, head_3d30), (10, 1.00, head_10d100), (30, 2.00, head_30d200)]:
            best = np.full(m_len, -999.0)
            for j in range(1, k_max + 1):
                if j >= m_len:
                    break
                r_stk = ac_s[j:] / ac_s[:-j] - 1.0
                r_b = bl_s[j:] / bl_s[:-j] - 1.0
                dev = r_stk - r_b
                best[j:] = np.maximum(best[j:], dev)
            valid_h = best > -900.0
            out_arr[s_i:e_i][valid_h] = thresh - best[valid_h]

        for pos in range(s_i, e_i):
            if not clean_arr[pos]:
                continue
            g0 = g_idx_arr[pos]
            buyA = ac_arr[pos]
            if buyA <= 0 or np.isnan(buyA):
                continue

            # Route A exits (target g0 + k)
            for k, r_out, d_out in [(1, retA_t1, exitdtA_t1), (2, retA_t2, exitdtA_t2), (3, retA_t3, exitdtA_t3), (5, retA_t5, exitdtA_t5)]:
                sj = find_sell_idx(pos + 1, e_i, g0 + k)
                if sj != -1:
                    r_out[pos] = (ac_arr[sj] / buyA) * (1.0 - FEE_RT) - 1.0
                    d_out[pos] = dt_arr[sj]

            # Route B entry at immediate next market trading day (g0 + 1)
            if pos + 1 < e_i and g_idx_arr[pos + 1] == g0 + 1:
                p1 = pos + 1
                if vol_arr[p1] > 0 and op_arr[p1] < (zt_arr[p1] - 0.011):
                    buyable_B[pos] = True
                    buyB = ao_arr[p1]
                    t1_adj_open[pos] = buyB
                    t1_open_ret[pos] = buyB / buyA - 1.0
                    t1_dt_arr[pos] = dt_arr[p1]
                    for k, r_out, d_out in [(2, retB_t2, exitdtB_t2), (3, retB_t3, exitdtB_t3), (5, retB_t5, exitdtB_t5)]:
                        sj = find_sell_idx(p1 + 1, e_i, g0 + k)
                        if sj != -1:
                            r_out[pos] = (ac_arr[sj] / buyB) * (1.0 - FEE_RT) - 1.0
                            d_out[pos] = dt_arr[sj]

    p20["head_3d30"] = head_3d30
    p20["head_10d100"] = head_10d100
    p20["head_30d200"] = head_30d200
    p20["buyable_B"] = buyable_B
    p20["t1_dt"] = t1_dt_arr
    p20["t1_adj_open"] = t1_adj_open
    p20["t1_open_ret"] = t1_open_ret
    p20["retA_t1"] = retA_t1; p20["exitdtA_t1"] = exitdtA_t1
    p20["retA_t2"] = retA_t2; p20["exitdtA_t2"] = exitdtA_t2
    p20["retA_t3"] = retA_t3; p20["exitdtA_t3"] = exitdtA_t3
    p20["retA_t5"] = retA_t5; p20["exitdtA_t5"] = exitdtA_t5
    p20["retB_t2"] = retB_t2; p20["exitdtB_t2"] = exitdtB_t2
    p20["retB_t3"] = retB_t3; p20["exitdtB_t3"] = exitdtB_t3
    p20["retB_t5"] = retB_t5; p20["exitdtB_t5"] = exitdtB_t5

    p20.to_parquet(f"{OUT_DIR}/panel_20cm.parquet", index=False)
    print(f"[Step 0 Done] Saved panel_20cm.parquet ({len(p20):,} rows) in {time.time()-t0:.1f}s")

    # Quick audit printout (<= 3KB)
    sub_21 = p20[(p20["dt"] >= "2021-01-04") & p20["is_clean_universe"]]
    print(f"  2021-2026 clean 20cm rows={len(sub_21):,}, unique tickers={sub_21['c6'].nunique()}, "
          f"ST rows excluded={p20[(p20['dt']>='2021-01-04') & p20['is_st_pit']].shape[0]:,}, "
          f"20cm ZT rows={sub_21['is_zt'].sum():,}")
    # Check beta days count
    b_days = mkt_reset[(mkt_reset["dt"] >= "2021-01-04") & (mkt_reset["ew_ret_all"] >= 0.02) & (mkt_reset["up_ratio_all"] >= 0.80)]
    print(f"  PIT Beta days (ew_ret>=2% & up>=80%): total={len(b_days)}, "
          f"IS(<=2024-08-31)={(b_days['dt']<='2024-08-31').sum()}, "
          f"OOS(>=2024-09-01)={(b_days['dt']>='2024-09-01').sum()}")


if __name__ == "__main__":
    main()

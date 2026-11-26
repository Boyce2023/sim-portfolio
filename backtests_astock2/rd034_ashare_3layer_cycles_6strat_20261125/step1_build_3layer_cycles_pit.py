#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD034 Step 1: Build strictly causal (<= T-1) 3-Layer A-Share Endogenous Cycle Warehouse.
  Layer 1: Market Sentiment, Style/Breadth, Index Trend, Calendar (26 factors)
  Layer 2: CSRC Industry Rotation + KPL Theme Lifecycle (17 factors)
  Layer 3: Individual Stock Position, Vol Compression, Turnover/Overhang, Size/Activity (18 factors)
Total: 61 indicators (60 continuous/ordinal + categorical sentiment phase & earnings window).

Hard rules:
  - ZERO yfinance (D12).
  - Read-only on production scripts, pools, and SQLite (uri mode=ro).
  - Full physical truncation self-test at 2024-12-31 (max_abs_diff == 0.0).
"""
import argparse
import bisect
import json
import os
import re
import sqlite3
import sys
import time
import warnings
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True
warnings.filterwarnings("ignore", category=RuntimeWarning)

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
RD028_DIR = f"{SIM}/backtests_astock2/rd028_old_hot_stock_6strat_5y_20261125"
OUT_DIR = f"{SIM}/backtests_astock2/rd034_ashare_3layer_cycles_6strat_20261125"
os.makedirs(OUT_DIR, exist_ok=True)

if RD028_DIR not in sys.path:
    sys.path.insert(0, RD028_DIR)
import step4_mod_rules_and_sim as m1

A_DAILY = f"{SIM}/data/cn_hk_price_db/a_daily.parquet"
A_DELISTED = f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet"
DB_ZT = f"{SIM}/data/zt_micro_tape_5y_pit.db"
DB_NOTICE = f"{SIM}/data/cninfo_notices_5y_pit.db"
REG_TOX_PQ = f"{SIM}/data/pit_reg_tox_notices_5y_complete.parquet"
CSRC_CSV = f"{SIM}/data/csrc_industry_pit_clean.csv"
KPL_JSONL = f"{SIM}/data/kpl_plates_2018_2026_merged.jsonl"
IDX_JSON = f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json"

ST_ON_RE = re.compile(r"(?:^(?:\*?ST|S\*?ST)|(?:股票交易|股票)(?:被)?实施(?:退市|其他)风险警示|进入退市整理期|作出.*终止上市)")
ST_EXC_RE = re.compile(r"(?:可能被实施|不实施|未实施|免于实施|申请撤销|撤销.*风险警示)")
ST_REV_RE = re.compile(r"(?:撤销(?:退市|其他)风险警示|股票交易撤销.*风险警示)")

# Static statutory CN long-holiday (>=4 cal days) last trading days 2021-2026 (pre-published calendar)
LONG_HOLIDAY_LAST_TRD = {
    "2021-02-10", "2021-04-02", "2021-04-30", "2021-06-11", "2021-09-17", "2021-09-30", "2021-12-31",
    "2022-01-28", "2022-04-01", "2022-04-29", "2022-06-02", "2022-09-09", "2022-09-30", "2022-12-30",
    "2023-01-20", "2023-04-28", "2023-06-21", "2023-09-28", "2023-12-29",
    "2024-02-08", "2024-04-03", "2024-04-30", "2024-06-07", "2024-09-13", "2024-09-30",
    "2025-01-27", "2025-04-03", "2025-04-30", "2025-05-30", "2025-09-30", "2025-12-31",
    "2026-02-13", "2026-04-03", "2026-04-30", "2026-06-18", "2026-09-24", "2026-09-30",
}

STRAT_ORDER = ["1to2", "2to3", "3to4", "high", "pry", "20cm"]


def _norm_plate(raw: str) -> str:
    s = re.sub(r"\(.*?\)|（.*?）", "", str(raw or "")).strip()
    if s.endswith("概念") and len(s) > 3:
        s = s[:-2].strip()
    return s


def build_pit_st_timeline(end_cutoff: str) -> dict[str, tuple[list[str], list[int]]]:
    """Strictly causal ST status timeline up to end_cutoff from PIT zt_micro_tape + notices."""
    st_ev = defaultdict(list)
    con_z = sqlite3.connect(f"file:{DB_ZT}?mode=ro", uri=True)
    for td, sc6, nm in con_z.execute(
        "SELECT trade_date, sec_code, sec_name FROM zt_micro_tape WHERE trade_date <= ?",
        (end_cutoff,),
    ):
        s = str(nm or "").strip()
        if s:
            st_ev[str(sc6).zfill(6)].append((f"{td} 15:00:00", 1 if ("ST" in s.upper() or "退" in s) else 0))
    con_z.close()

    ts_cut = f"{end_cutoff} 23:59:59"
    con_n = sqlite3.connect(f"file:{DB_NOTICE}?mode=ro", uri=True)
    for sc6, ti, ts in con_n.execute(
        "SELECT sec_code, title, pub_datetime_cst FROM notices WHERE pub_datetime_cst <= ?",
        (ts_cut,),
    ):
        t_s = str(ti or "")
        ts_s = str(ts)[:19]
        c6 = str(sc6).zfill(6)
        if ST_REV_RE.search(t_s) and "不" not in t_s[:10]:
            st_ev[c6].append((ts_s, 0))
        elif ST_ON_RE.search(t_s) and not ST_EXC_RE.search(t_s):
            st_ev[c6].append((ts_s, 1))
    con_n.close()

    rt = pd.read_parquet(REG_TOX_PQ, columns=["sec_code", "pub_datetime_cst", "title"])
    rt["ts"] = rt["pub_datetime_cst"].astype(str).str[:19]
    rt = rt[rt["ts"] <= ts_cut]
    for r in rt.itertuples(index=False):
        t_s = str(r.title or "")
        c6 = str(r.sec_code)[:6].zfill(6)
        if ST_REV_RE.search(t_s):
            st_ev[c6].append((r.ts, 0))
        elif ST_ON_RE.search(t_s) and not ST_EXC_RE.search(t_s):
            st_ev[c6].append((r.ts, 1))

    out = {}
    for k, v in st_ev.items():
        v_sorted = sorted(v)
        out[k] = ([x[0] for x in v_sorted], [x[1] for x in v_sorted])
    return out


def is_st_at(st_tl: dict, c6: str, cut_ts: str) -> bool:
    tl = st_tl.get(c6)
    if not tl:
        return False
    idx = bisect.bisect_left(tl[0], cut_ts)
    return bool(tl[1][idx - 1] == 1) if idx > 0 else False


def load_daily_universe(end_cutoff: str, st_tl: dict) -> tuple[pd.DataFrame, list[str], dict[str, int]]:
    """Load active + delisted .SH/.SZ bars <= end_cutoff with exact list_age, ZT/DT, mcap & ST."""
    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "amount", "oshare", "turn"]
    flt = ds.field("date") <= pd.Timestamp(end_cutoff)
    da = ds.dataset(A_DAILY, format="parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    dd = ds.dataset(A_DELISTED, format="parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    da["dl"], dd["dl"] = 0, 1
    df = pd.concat([da, dd], ignore_index=True)
    del da, dd

    tk = df["ticker"].astype(str)
    df["c6"] = tk.str[:6]
    df = df[
        tk.str.endswith((".SH", ".SZ"))
        & df["c6"].str.startswith(("00", "60", "30", "688", "689"))
        & (df["close"] > 0)
        & (df["adj_close"] > 0)
    ].copy()
    df["dt"] = df["date"].dt.strftime("%Y-%m-%d")
    df = df[df["dt"] <= end_cutoff].copy()
    df.sort_values(["c6", "dt", "dl"], inplace=True)
    df.drop_duplicates(["c6", "dt"], keep="first", inplace=True)
    df.reset_index(drop=True, inplace=True)

    # Full IPO listing age strictly causal up to end_cutoff
    df["list_age"] = (df.groupby("c6", sort=False).cumcount() + 1).astype(np.int32)

    # Slice >= 2017-06-01 (~870 trading days warmup prior to 2021-01-04)
    df = df[df["dt"] >= "2017-06-01"].copy().reset_index(drop=True)

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
    vol_v = df["volume"].fillna(0.0).to_numpy(np.float64)
    pvol_v = np.empty(len(df), dtype=np.float64)
    pvol_v[0] = 0.0
    pvol_v[1:] = np.where(same_c6[1:], vol_v[:-1], 0.0)

    ret_v = np.where(pac_v > 0, ac_v / pac_v - 1.0, np.nan)
    c6_s = df["c6"]
    dt_s = df["dt"]
    is20 = (c6_s.str.startswith(("688", "689")) | (c6_s.str.startswith("30") & (dt_s >= "2020-08-24"))).to_numpy()
    lim = np.where(is20, 0.20, 0.10)
    r_th = np.where(is20, 0.195, 0.095)
    abn = np.abs(ret_v) > np.where(is20, 0.22, 0.12)
    pre_ex = pac_v / sc_v
    zt_px = np.floor(pre_ex * (1.0 + lim) * 100.0 + 0.5) / 100.0
    dt_px = np.floor(pre_ex * (1.0 - lim) * 100.0 + 0.5) / 100.0

    high_v = df["high"].to_numpy(np.float64)
    low_v = df["low"].to_numpy(np.float64)
    open_v = df["open"].to_numpy(np.float64)
    age_v = df["list_age"].to_numpy(np.int32)

    is_zt = (pac_v > 0) & (vol_v > 0) & (close_v >= zt_px - 0.011) & (ret_v >= r_th) & (~abn) & (age_v > 20)
    hit_zt = (pac_v > 0) & (vol_v > 0) & (high_v >= zt_px - 0.011) & (~abn) & (age_v > 20)
    is_yizi_zt = is_zt & (open_v >= zt_px - 0.011) & (low_v >= zt_px - 0.011)
    is_dt = (pac_v > 0) & (vol_v > 0) & (close_v <= dt_px + 0.011) & (ret_v <= -r_th) & (~abn) & (age_v > 20)

    osh_v = df["oshare"].fillna(0.0).to_numpy(np.float64)
    turn_raw = df["turn"].fillna(0.0).to_numpy(np.float64)
    shares = np.where(osh_v > 0, osh_v, np.where(turn_raw > 0, vol_v / turn_raw, np.nan))
    mcap_v = close_v * shares
    mcap_m1 = np.empty(len(df), dtype=np.float64)
    mcap_m1[0] = np.nan
    mcap_m1[1:] = np.where(same_c6[1:], mcap_v[:-1], np.nan)

    amt_v = df["amount"].fillna(0.0).to_numpy(np.float64)
    vwap_v = np.where(vol_v > 0, amt_v / vol_v, close_v)
    avwap_v = vwap_v * sc_v

    # Consecutive ZT streak
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

    # PIT ST status on (c6, dt) using vectorized bisect over unique (c6, dt)
    # Fast per-c6 lookup
    st_arr = np.zeros(len(df), dtype=bool)
    dt_arr = df["dt"].to_numpy()
    i = 0
    n_tot = len(df)
    while i < n_tot:
        c = c6_arr[i]
        j = i + 1
        while j < n_tot and c6_arr[j] == c:
            j += 1
        tl = st_tl.get(c)
        if tl:
            ts_list, val_list = tl
            for k in range(i, j):
                idx = bisect.bisect_left(ts_list, f"{dt_arr[k]} 15:00:00")
                if idx > 0 and val_list[idx - 1] == 1:
                    st_arr[k] = True
        i = j

    df["ret"] = ret_v.astype(np.float64)
    df["ac"] = ac_v.astype(np.float64)
    df["ah"] = (high_v * sc_v).astype(np.float64)
    df["al"] = (low_v * sc_v).astype(np.float64)
    df["avwap"] = avwap_v.astype(np.float64)
    df["amt"] = amt_v.astype(np.float64)
    df["mcap"] = mcap_v.astype(np.float64)
    df["mcap_m1"] = mcap_m1.astype(np.float64)
    df["turn_clean"] = np.clip(turn_raw, 0.0, 1.0).astype(np.float64)
    df["pvol"] = pvol_v.astype(np.float64)
    df["is_zt"] = is_zt
    df["hit_zt"] = hit_zt
    df["is_yizi_zt"] = is_yizi_zt
    df["is_dt"] = is_dt
    df["streak"] = streak
    df["is_st"] = st_arr
    return df, all_dts, dt_to_mkt


def _rolling_pct_last(arr: np.ndarray, win: int, min_p: int = 20) -> np.ndarray:
    """Strict trailing percentile rank of arr[i] within arr[max(0,i-win+1)..i]."""
    n = len(arr)
    out = np.full(n, np.nan, dtype=float)
    for i in range(n):
        lo = max(0, i - win + 1)
        w = arr[lo : i + 1]
        v = w[np.isfinite(w)]
        if len(v) >= min_p and np.isfinite(arr[i]):
            out[i] = float(np.mean(v <= arr[i]))
    return out


def build_calendar_flags(all_dts: list[str]) -> pd.DataFrame:
    """Strictly pre-known calendar flags (zero future price/data peeking)."""
    # Month-end last 3 trading days within each YYYY-MM:
    # Build complete statutory weekday calendar per year (2021-2026) minus known holidays so 2024-12-31 truncation is exact
    by_ym = defaultdict(list)
    for d in all_dts:
        by_ym[d[:7]].append(d)
    # Note: for 2026-11 (partial month ending 2026-11-25), 2026-11-26/27/30 are future;
    # for all complete months <= 2024-12 (including 2024-12!), 2024-12-31 IS the last weekday of 2024-12.
    me3_set = set()
    for ym, dlist in by_ym.items():
        # Only mark month-end 3d if dlist reaches >= 26th of month (or last day >= 26), avoiding truncated partial end month
        if ym != "2026-11":
            for d in dlist[-3:]:
                me3_set.add(d)

    # Pre-holiday 2 trading days (T-0 is within 2 trading days prior to long holiday break)
    hol_pre2_set = set()
    dt_idx = {d: i for i, d in enumerate(all_dts)}
    for hd in LONG_HOLIDAY_LAST_TRD:
        pos = dt_idx.get(hd)
        if pos is not None:
            hol_pre2_set.add(all_dts[pos])
            if pos - 1 >= 0:
                hol_pre2_set.add(all_dts[pos - 1])

    rows = []
    for d in all_dts:
        mmdd = d[5:]
        if "01-15" <= mmdd <= "01-31":
            ew = 1  # Jan earnings preview
        elif "04-15" <= mmdd <= "04-30":
            ew = 2  # Apr annual/Q1 report minefield
        elif "07-10" <= mmdd <= "08-31":
            ew = 3  # Jul-Aug interim report
        elif "10-15" <= mmdd <= "10-31":
            ew = 4  # Oct Q3 report
        else:
            ew = 0
        rows.append({
            "dt": d,
            "L1_is_earn_win": int(ew),
            "L1_is_earn_any": int(ew > 0),
            "L1_is_earn_apr": int(ew == 2),
            "L1_is_month_end3": int(d in me3_set),
            "L1_is_pre_hol2": int(d in hol_pre2_set),
            "L1_weekday": int(pd.Timestamp(d).dayofweek + 1),  # 1=Mon .. 5=Fri
        })
    return pd.DataFrame(rows)


def build_layer1_market_daily(df: pd.DataFrame, all_dts: list[str], end_cutoff: str) -> pd.DataFrame:
    """Build Layer 1 daily market factors strictly shifted so row `dt` holds T-1 state (+ calendar on T)."""
    n_d = len(all_dts)
    dt_to_idx = {d: i for i, d in enumerate(all_dts)}

    # Valid non-ST universe for daily cross-section
    val = df[(~df["is_st"]) & (df["volume"] > 0) & (df["list_age"] > 20)].copy()
    val["is_nat_zt"] = val["is_zt"] & (~val["is_yizi_zt"])
    val["is_lb2"] = val["streak"] >= 2
    val_ret = val[(val["pvol"] > 0) & val["ret"].notna() & (val["ret"].abs() <= 0.22)].copy()
    val_ret["is_up"] = val_ret["ret"] > 0

    # Daily market aggregates (indexed by dt, vectorized)
    tot_amt = val.groupby("dt")["amt"].sum().reindex(all_dts).fillna(0.0).to_numpy(float)
    zt_cnt = val.groupby("dt")["is_zt"].sum().reindex(all_dts).fillna(0).to_numpy(float)
    nat_zt_cnt = val.groupby("dt")["is_nat_zt"].sum().reindex(all_dts).fillna(0).to_numpy(float)
    dt_cnt = val.groupby("dt")["is_dt"].sum().reindex(all_dts).fillna(0).to_numpy(float)
    hit_cnt = val.groupby("dt")["hit_zt"].sum().reindex(all_dts).fillna(0).to_numpy(float)
    max_board = val.groupby("dt")["streak"].max().reindex(all_dts).fillna(0).to_numpy(float)
    lb_cnt = val.groupby("dt")["is_lb2"].sum().reindex(all_dts).fillna(0).to_numpy(float)

    zb_rate = np.where(hit_cnt > 0, (hit_cnt - zt_cnt) / hit_cnt * 100.0, 0.0)
    zb_rate = np.clip(zb_rate, 0.0, 100.0)
    zt_dt_logratio = np.log((zt_cnt + 1.0) / (dt_cnt + 1.0))

    # Breadth & Equal-weight market index
    pct_up = val_ret.groupby("dt")["is_up"].mean().reindex(all_dts).fillna(0.5).to_numpy(float)
    ew_ret = val_ret.groupby("dt")["ret"].mean().reindex(all_dts).fillna(0.0).to_numpy(float)
    ew_idx = np.cumprod(1.0 + ew_ret)

    # Yesterday ZT today premium, Yesterday LB today promotion, Yesterday broken-ZT today big-loss
    g_all = df.groupby("c6", sort=False)
    df["zt_m1"] = g_all["is_zt"].shift(1).fillna(False)
    df["streak_m1"] = g_all["streak"].shift(1).fillna(0)
    df["zt_m2"] = g_all["is_zt"].shift(2).fillna(False)
    df["streak_m2"] = g_all["streak"].shift(2).fillna(0)
    df["st_m1"] = g_all["is_st"].shift(1).fillna(False)

    trad_ret = (~df["is_st"]) & (~df["st_m1"]) & (df["volume"] > 0) & (df["pvol"] > 0) & (df["list_age"] > 20) & df["ret"].notna() & (df["ret"].abs() <= 0.22)
    zt_prem_s = df[trad_ret & df["zt_m1"]].groupby("dt")["ret"].mean().reindex(all_dts)
    lb_promo_s = df[trad_ret & (df["streak_m1"] >= 2)].groupby("dt")["is_zt"].mean().reindex(all_dts)
    # Fallback when 0 2b existed on d-1: use 1b promo
    lb_promo_fb = df[trad_ret & (df["streak_m1"] >= 1)].groupby("dt")["is_zt"].mean().reindex(all_dts)
    lb_promo = lb_promo_s.fillna(lb_promo_fb).fillna(0.0).to_numpy(float) * 100.0
    zt_prem = zt_prem_s.fillna(0.0).to_numpy(float) * 100.0

    duanban_df = df[trad_ret & (df["streak_m2"] >= 1) & (~df["zt_m1"])].copy()
    duanban_df["is_bigloss"] = duanban_df["ret"] <= -0.05
    db_damian_s = duanban_df.groupby("dt")["is_bigloss"].mean().reindex(all_dts)
    db_damian = db_damian_s.fillna(0.0).to_numpy(float) * 100.0

    # Size style SMB: bottom 20% mcap_m1 minus top 10% mcap_m1
    vr_mc = val_ret[val_ret["mcap_m1"].notna() & (val_ret["mcap_m1"] > 0)].copy()
    vr_mc["mc_pct"] = vr_mc.groupby("dt")["mcap_m1"].rank(pct=True)
    small_r = vr_mc[vr_mc["mc_pct"] <= 0.20].groupby("dt")["ret"].mean().reindex(all_dts).fillna(0.0).to_numpy(float)
    big_r = vr_mc[vr_mc["mc_pct"] >= 0.90].groupby("dt")["ret"].mean().reindex(all_dts).fillna(0.0).to_numpy(float)
    small_idx = np.cumprod(1.0 + small_r)
    big_idx = np.cumprod(1.0 + big_r)

    # CSI 300 proxy (strictly <= end_cutoff)
    idx_raw = json.load(open(IDX_JSON, encoding="utf-8"))["sh000300"]
    csi_s = pd.Series({k: float(v) for k, v in idx_raw.items() if k <= end_cutoff}).reindex(all_dts).ffill().bfill().to_numpy(float)

    # Compute rolling series (as of day d close)
    s_zt = pd.Series(zt_cnt)
    s_amt = pd.Series(tot_amt)
    s_up = pd.Series(pct_up)
    s_ew = pd.Series(ew_idx)
    s_ew_r = pd.Series(ew_ret)
    s_csi = pd.Series(csi_s)
    s_sm = pd.Series(small_idx)
    s_bg = pd.Series(big_idx)

    zt_ma3 = s_zt.rolling(3, min_periods=1).mean().to_numpy(float)
    zt_ma20 = s_zt.rolling(20, min_periods=5).mean().to_numpy(float)
    zt_mom3v20 = np.where(zt_ma20 > 0, zt_ma3 / zt_ma20 - 1.0, 0.0)
    zt_pct60 = _rolling_pct_last(zt_cnt, 60, min_p=20)
    dt_pct60 = _rolling_pct_last(dt_cnt, 60, min_p=20)

    # Causal 5-state sentiment phase at close of day d
    # 1=冰点, 2=修复, 3=主升, 4=高潮, 5=退潮
    zt_mom3_diff = zt_cnt - s_zt.shift(1).rolling(3, min_periods=1).mean().fillna(s_zt).to_numpy(float)
    sent_phase = np.full(n_d, 3, dtype=int)
    for i in range(n_d):
        zp = zt_pct60[i]
        dp = dt_pct60[i]
        m3 = zt_mom3_diff[i]
        pr = zt_prem[i]
        if np.isnan(zp):
            sent_phase[i] = 3
        elif zp >= 0.80 and (np.isnan(dp) or dp < 0.80):
            sent_phase[i] = 4  # 高潮
        elif zp <= 0.20 and (m3 <= 0 or pr < 0):
            sent_phase[i] = 1  # 冰点
        elif zp <= 0.45 and m3 > 0 and pr >= 0:
            sent_phase[i] = 2  # 修复
        elif (zp < 0.80 and m3 < 0 and ((not np.isnan(dp) and dp >= 0.65) or pr < 0.5)) or (zp >= 0.80 and not np.isnan(dp) and dp >= 0.80):
            sent_phase[i] = 5  # 退潮
        else:
            sent_phase[i] = 3  # 主升

    smb_5d = ((s_sm / s_sm.shift(5) - 1.0) - (s_bg / s_bg.shift(5) - 1.0)).to_numpy(float) * 100.0
    smb_20d = ((s_sm / s_sm.shift(20) - 1.0) - (s_bg / s_bg.shift(20) - 1.0)).to_numpy(float) * 100.0
    smb_60d = ((s_sm / s_sm.shift(60) - 1.0) - (s_bg / s_bg.shift(60) - 1.0)).to_numpy(float) * 100.0

    breadth_5d = s_up.rolling(5, min_periods=3).mean().to_numpy(float)
    breadth_20d = s_up.rolling(20, min_periods=10).mean().to_numpy(float)

    amt_ma20_prev = s_amt.shift(1).rolling(20, min_periods=10).mean().to_numpy(float)
    amt_ratio20 = np.where(amt_ma20_prev > 0, tot_amt / amt_ma20_prev, np.nan)
    amt_ma5 = s_amt.rolling(5, min_periods=3).mean().to_numpy(float)
    amt_ma60 = s_amt.rolling(60, min_periods=20).mean().to_numpy(float)
    amt_ratio5v60 = np.where(amt_ma60 > 0, amt_ma5 / amt_ma60, np.nan)

    ew_ma20 = s_ew.rolling(20, min_periods=15).mean().to_numpy(float)
    ew_ma60 = s_ew.rolling(60, min_periods=40).mean().to_numpy(float)
    ew_ma250 = s_ew.rolling(250, min_periods=180).mean().to_numpy(float)
    ew_bias20 = (ew_idx / ew_ma20 - 1.0) * 100.0
    ew_bias60 = (ew_idx / ew_ma60 - 1.0) * 100.0
    ew_bias250 = (ew_idx / ew_ma250 - 1.0) * 100.0
    ew_ret20 = (s_ew / s_ew.shift(20) - 1.0).to_numpy(float) * 100.0
    ew_vol20 = s_ew_r.rolling(20, min_periods=15).std().to_numpy(float) * 100.0
    ew_min60 = s_ew.rolling(60, min_periods=20).min().to_numpy(float)
    ew_max60 = s_ew.rolling(60, min_periods=20).max().to_numpy(float)
    ew_pos60 = np.where(ew_max60 > ew_min60, (ew_idx - ew_min60) / (ew_max60 - ew_min60), 0.5)

    csi_ma60 = s_csi.rolling(60, min_periods=40).mean().to_numpy(float)
    csi_bias60 = (csi_s / csi_ma60 - 1.0) * 100.0

    raw_df = pd.DataFrame({
        "dt": all_dts,
        "L1_zt_cnt_t1": zt_cnt,
        "L1_nat_zt_cnt_t1": nat_zt_cnt,
        "L1_dt_cnt_t1": dt_cnt,
        "L1_zt_dt_logratio_t1": zt_dt_logratio,
        "L1_zb_rate_t1": zb_rate,
        "L1_max_board_t1": max_board,
        "L1_lianban_cnt_t1": lb_cnt,
        "L1_zt_prem_t1": zt_prem,
        "L1_lb_promo_t1": lb_promo,
        "L1_duanban_damian_t1": db_damian,
        "L1_zt_mom3v20_t1": zt_mom3v20,
        "L1_zt_pct60_t1": zt_pct60,
        "L1_sent_phase_t1": sent_phase,
        "L1_smb_5d_t1": smb_5d,
        "L1_smb_20d_t1": smb_20d,
        "L1_smb_60d_t1": smb_60d,
        "L1_breadth_5d_t1": breadth_5d,
        "L1_breadth_20d_t1": breadth_20d,
        "L1_amt_ratio20_t1": amt_ratio20,
        "L1_amt_ratio5v60_t1": amt_ratio5v60,
        "L1_ew_bias20_t1": ew_bias20,
        "L1_ew_bias60_t1": ew_bias60,
        "L1_ew_bias250_t1": ew_bias250,
        "L1_ew_ret20_t1": ew_ret20,
        "L1_ew_vol20_t1": ew_vol20,
        "L1_ew_pos60_t1": ew_pos60,
        "L1_csi_bias60_t1": csi_bias60,
        "_raw_ew_ret": ew_ret,
        "_raw_tot_amt": tot_amt,
        "_raw_zt_cnt": zt_cnt,
    })

    # Shift all _t1 columns by 1 trading day so row `dt` (day T) holds strictly T-1 close state!
    t1_cols = [c for c in raw_df.columns if c.endswith("_t1")]
    for c in t1_cols:
        raw_df[c] = raw_df[c].shift(1)

    cal_df = build_calendar_flags(all_dts)
    mkt_df = raw_df.merge(cal_df, on="dt", how="left")
    return mkt_df


def build_layer2_industry_and_kpl(
    df: pd.DataFrame,
    mkt_df: pd.DataFrame,
    all_dts: list[str],
    dt_to_mkt: dict[str, int],
    target_pairs: list[tuple[str, str]],
    end_cutoff: str,
) -> pd.DataFrame:
    """Build Layer 2 CSRC Industry (10 factors) & KPL Theme Lifecycle (7 factors) strictly <= T-1."""
    n_d = len(all_dts)

    # --- 2A: CSRC Industry Panel ---
    csrc = pd.read_csv(CSRC_CSV)
    csrc["c6"] = csrc["sec_code"].astype(str).str.zfill(6)
    csrc = csrc[csrc["industry"].notna() & (csrc["start_date"] <= end_cutoff)].copy()
    csrc.sort_values(["c6", "start_date"], inplace=True)

    # Map each c6 to sorted intervals (start_date, end_date, industry)
    csrc_iv = defaultdict(list)
    for r in csrc.itertuples(index=False):
        ed = "9999-12-31" if str(r.end_date) >= "2026-11-16" else str(r.end_date)
        csrc_iv[r.c6].append((str(r.start_date), ed, str(r.industry)))

    def _lookup_ind(c6: str, dt: str) -> str | None:
        ivs = csrc_iv.get(c6)
        if not ivs:
            return None
        chosen = None
        for sd, ed, ind in ivs:
            if sd <= dt <= ed:
                chosen = ind
        return chosen

    # Assign CSRC industry to valid universe rows (fast per-c6 interval assignment)
    val = df[(~df["is_st"]) & (df["volume"] > 0) & (df["list_age"] > 20)].copy()
    c6_v = val["c6"].to_numpy()
    dt_v = val["dt"].to_numpy()
    ind_arr = np.empty(len(val), dtype=object)
    ind_arr[:] = None
    i = 0
    nv = len(val)
    while i < nv:
        c = c6_v[i]
        j = i + 1
        while j < nv and c6_v[j] == c:
            j += 1
        ivs = csrc_iv.get(c)
        if ivs:
            if len(ivs) == 1:
                sd, ed, ind = ivs[0]
                for k in range(i, j):
                    if sd <= dt_v[k] <= ed:
                        ind_arr[k] = ind
            else:
                for k in range(i, j):
                    d = dt_v[k]
                    for sd, ed, ind in ivs:
                        if sd <= d <= ed:
                            ind_arr[k] = ind
        i = j
    val["ind"] = ind_arr
    val_ind = val[val["ind"].notna()].copy()
    val_ind_ret = val_ind[(val_ind["pvol"] > 0) & val_ind["ret"].notna() & (val_ind["ret"].abs() <= 0.22)].copy()

    # Daily industry aggregates (rows=all_dts, cols=industries)
    ind_ret_mat = val_ind_ret.groupby(["dt", "ind"])["ret"].mean().unstack("ind").reindex(all_dts).fillna(0.0)
    ind_amt_mat = val_ind.groupby(["dt", "ind"])["amt"].sum().unstack("ind").reindex(all_dts).fillna(0.0)
    ind_zt_mat = val_ind.groupby(["dt", "ind"])["is_zt"].sum().unstack("ind").reindex(all_dts).fillna(0.0)

    inds = list(ind_ret_mat.columns)
    ind_to_j = {ind: j for j, ind in enumerate(inds)}
    R_ind = ind_ret_mat.to_numpy(float)  # (n_d, n_ind)
    A_ind = ind_amt_mat[inds].to_numpy(float)
    Z_ind = ind_zt_mat[inds].to_numpy(float)
    I_ind = np.cumprod(1.0 + R_ind, axis=0)

    ew_ret_v = mkt_df["_raw_ew_ret"].to_numpy(float)
    ew_idx_v = np.cumprod(1.0 + ew_ret_v)
    tot_amt_v = np.maximum(1.0, mkt_df["_raw_tot_amt"].to_numpy(float))
    tot_zt_v = mkt_df["_raw_zt_cnt"].to_numpy(float)

    def _lag_ret(mat, k):
        out = np.full_like(mat, np.nan)
        out[k:] = (mat[k:] / mat[:-k] - 1.0) * 100.0
        return out

    ew_s = pd.Series(ew_idx_v)
    ew_r5 = ((ew_s / ew_s.shift(5) - 1.0) * 100.0).to_numpy(float)[:, None]
    ew_r20 = ((ew_s / ew_s.shift(20) - 1.0) * 100.0).to_numpy(float)[:, None]
    ew_r60 = ((ew_s / ew_s.shift(60) - 1.0) * 100.0).to_numpy(float)[:, None]
    ew_r120 = ((ew_s / ew_s.shift(120) - 1.0) * 100.0).to_numpy(float)[:, None]

    ind_r5 = _lag_ret(I_ind, 5)
    ind_r20 = _lag_ret(I_ind, 20)
    ind_r60 = _lag_ret(I_ind, 60)
    ind_r120 = _lag_ret(I_ind, 120)

    ind_ex5 = ind_r5 - ew_r5
    ind_ex20 = ind_r20 - ew_r20
    ind_ex60 = ind_r60 - ew_r60
    ind_ex120 = ind_r120 - ew_r120

    # Cross-sectional percentile rank across active industries per day
    ind_rank20 = pd.DataFrame(ind_r20).rank(axis=1, pct=True).to_numpy(float)
    ind_rank60 = pd.DataFrame(ind_r60).rank(axis=1, pct=True).to_numpy(float)

    I_df = pd.DataFrame(I_ind)
    min60 = I_df.rolling(60, min_periods=20).min().to_numpy(float)
    max60 = I_df.rolling(60, min_periods=20).max().to_numpy(float)
    ind_pos60 = np.where(max60 > min60, (I_ind - min60) / (max60 - min60), 0.5)

    min250 = I_df.rolling(250, min_periods=60).min().to_numpy(float)
    max250 = I_df.rolling(250, min_periods=60).max().to_numpy(float)
    ind_pos250 = np.where(max250 > min250, (I_ind - min250) / (max250 - min250), 0.5)

    ind_amt_share = A_ind / tot_amt_v[:, None] * 100.0
    # 250d rolling percentile of industry's own turnover share
    ind_amt_pct250 = np.full_like(ind_amt_share, np.nan)
    for j_col in range(len(inds)):
        ind_amt_pct250[:, j_col] = _rolling_pct_last(ind_amt_share[:, j_col], 250, min_p=60)

    z5 = pd.DataFrame(Z_ind).rolling(5, min_periods=1).sum().to_numpy(float)
    mz5 = np.maximum(1.0, pd.Series(tot_zt_v).rolling(5, min_periods=1).sum().to_numpy(float))[:, None]
    ind_zt_share5 = z5 / mz5 * 100.0

    # Consecutive days beating market EW
    beat_mkt = R_ind > ew_ret_v[:, None]
    ind_up_streak = np.zeros_like(R_ind, dtype=float)
    for j_col in range(len(inds)):
        c_st = 0
        for t_i in range(n_d):
            if beat_mkt[t_i, j_col]:
                c_st += 1
            else:
                c_st = 0
            ind_up_streak[t_i, j_col] = c_st

    # --- 2B: KPL Theme Lifecycle strictly <= end_cutoff ---
    kpl_plate_day_cnt = defaultdict(lambda: np.zeros(n_d, dtype=np.int32))
    kpl_stock_events = defaultdict(list)  # c6 -> list of (mkt_idx, plate_name, plate_sz)
    kpl_day_tot = np.zeros(n_d, dtype=np.int32)

    with open(KPL_JSONL, encoding="utf-8") as f:
        for ln in f:
            if not ln.strip():
                continue
            obj = json.loads(ln)
            dt_s = str(obj["date"])[:10]
            if dt_s > end_cutoff:
                continue
            mi = dt_to_mkt.get(dt_s)
            if mi is None:
                continue
            day_plates = []
            for p in obj.get("plates", []):
                pname = _norm_plate(p.get("plate", ""))
                if pname in ("其他", "无", "", "ST板块"):
                    continue
                sts = p.get("stocks", [])
                psz = len(sts)
                if psz == 0:
                    continue
                kpl_plate_day_cnt[pname][mi] += psz
                kpl_day_tot[mi] += psz
                day_plates.append((pname, psz, sts))
            for pname, psz, sts in day_plates:
                for st in sts:
                    c6 = str(st[0]).strip().zfill(6)
                    if c6.startswith(("00", "60", "30", "688", "689")):
                        kpl_stock_events[c6].append((mi, pname, psz))

    for c6 in kpl_stock_events:
        kpl_stock_events[c6].sort(key=lambda x: (x[0], -x[2], x[1]))

    # Precompute KPL plate time series metrics per plate (as of day d close)
    kpl_metrics = {}
    for pname, cnt_arr in kpl_plate_day_cnt.items():
        s_c = pd.Series(cnt_arr, dtype=float)
        zt3 = s_c.rolling(3, min_periods=1).sum().to_numpy(float)
        zt20 = s_c.rolling(20, min_periods=1).sum().to_numpy(float)
        max20 = s_c.rolling(20, min_periods=1).max().to_numpy(float)
        crowd = np.where(tot_zt_v > 0, cnt_arr / tot_zt_v * 100.0, 0.0)
        peak_ratio = np.where(max20 > 0, cnt_arr / max20, 0.0)

        # Consecutive active outbreak days (cnt >= 3)
        streak_p = np.zeros(n_d, dtype=float)
        cur_p = 0
        for i in range(n_d):
            if cnt_arr[i] >= 3:
                cur_p += 1
            else:
                cur_p = 0
            streak_p[i] = cur_p

        # Distinct active waves (>=3 ZT separated by >=2 days < 3) in trailing 60 trading days
        # Mark wave_start[i] = 1 if cnt[i] >= 3 and cnt[i-1] < 3 and cnt[i-2] < 3
        wave_start = np.zeros(n_d, dtype=float)
        for i in range(n_d):
            if cnt_arr[i] >= 3:
                p1 = cnt_arr[i - 1] < 3 if i >= 1 else True
                p2 = cnt_arr[i - 2] < 3 if i >= 2 else True
                if p1 and p2:
                    wave_start[i] = 1.0
        wave_cnt60 = pd.Series(wave_start).rolling(60, min_periods=1).sum().to_numpy(float)

        kpl_metrics[pname] = {
            "zt1": cnt_arr.astype(float),
            "zt3": zt3,
            "zt20": zt20,
            "streak": streak_p,
            "crowd": crowd,
            "peak_ratio": peak_ratio,
            "wave_cnt60": wave_cnt60,
        }

    # Precompute kpl_stock_events index arrays for fast bisect
    kpl_idx_map = {c6: ([x[0] for x in evs], evs) for c6, evs in kpl_stock_events.items()}

    rows = []
    for c6, buy_dt in target_pairs:
        mi = dt_to_mkt.get(buy_dt)
        row_d = {"c6": c6, "dt": buy_dt}
        if mi is None or mi < 1:
            rows.append(row_d)
            continue
        t1 = mi - 1
        t1_dt = all_dts[t1]

        # Industry lookup strictly as of T-1
        ind = _lookup_ind(c6, t1_dt)
        j_col = ind_to_j.get(ind) if ind is not None else None
        if j_col is not None:
            row_d["L2_ind_name_t1"] = ind
            row_d["L2_ind_ex5_t1"] = float(ind_ex5[t1, j_col])
            row_d["L2_ind_ex20_t1"] = float(ind_ex20[t1, j_col])
            row_d["L2_ind_ex60_t1"] = float(ind_ex60[t1, j_col])
            row_d["L2_ind_ex120_t1"] = float(ind_ex120[t1, j_col])
            row_d["L2_ind_rank20_t1"] = float(ind_rank20[t1, j_col])
            row_d["L2_ind_rank60_t1"] = float(ind_rank60[t1, j_col])
            row_d["L2_ind_pos60_t1"] = float(ind_pos60[t1, j_col])
            row_d["L2_ind_pos250_t1"] = float(ind_pos250[t1, j_col])
            row_d["L2_ind_amt_pct250_t1"] = float(ind_amt_pct250[t1, j_col])
            row_d["L2_ind_zt_share5_t1"] = float(ind_zt_share5[t1, j_col])
            row_d["L2_ind_up_streak_t1"] = float(ind_up_streak[t1, j_col])
        else:
            row_d["L2_ind_name_t1"] = None

        # KPL core theme strictly <= T-1 (within [T-250 .. T-1])
        ke = kpl_idx_map.get(c6)
        core_plate = None
        if ke is not None:
            mis, evs = ke
            hi = bisect.bisect_right(mis, t1)
            if hi > 0:
                last_mi, pname, _ = evs[hi - 1]
                # Since sorted by (mi, -psz, pname), look back to first event with same last_mi (largest plate on last_mi)
                if t1 - last_mi <= 250:
                    k_pos = hi - 1
                    while k_pos > 0 and evs[k_pos - 1][0] == last_mi:
                        k_pos -= 1
                    core_plate = evs[k_pos][1]
        if core_plate is not None and core_plate in kpl_metrics:
            km = kpl_metrics[core_plate]
            row_d["L2_kpl_plate_t1"] = core_plate
            row_d["L2_kpl_zt1_t1"] = float(km["zt1"][t1])
            row_d["L2_kpl_zt3_t1"] = float(km["zt3"][t1])
            row_d["L2_kpl_zt20_t1"] = float(km["zt20"][t1])
            row_d["L2_kpl_streak_t1"] = float(km["streak"][t1])
            row_d["L2_kpl_crowd_t1"] = float(km["crowd"][t1])
            row_d["L2_kpl_peak_ratio_t1"] = float(km["peak_ratio"][t1])
            row_d["L2_kpl_wave_cnt60_t1"] = float(km["wave_cnt60"][t1])
        else:
            row_d["L2_kpl_plate_t1"] = None
            row_d["L2_kpl_zt1_t1"] = 0.0
            row_d["L2_kpl_zt3_t1"] = 0.0
            row_d["L2_kpl_zt20_t1"] = 0.0
            row_d["L2_kpl_streak_t1"] = 0.0
            row_d["L2_kpl_crowd_t1"] = 0.0
            row_d["L2_kpl_peak_ratio_t1"] = 0.0
            row_d["L2_kpl_wave_cnt60_t1"] = 0.0

        rows.append(row_d)
    return pd.DataFrame(rows)


def build_layer3_stock_cycles(
    df: pd.DataFrame,
    target_pairs: list[tuple[str, str]],
) -> pd.DataFrame:
    """Build Layer 3 Individual Stock Cycle features (18 factors) strictly as of T-1."""
    # Cross-sectional mcap percentile per day across non-ST valid stocks
    val_mc = df[(~df["is_st"]) & (df["volume"] > 0) & (df["list_age"] > 20) & df["mcap"].notna() & (df["mcap"] > 0)].copy()
    val_mc["mcap_pct"] = val_mc.groupby("dt")["mcap"].rank(pct=True)
    mcap_pct_map = {(r.c6, r.dt): float(r.mcap_pct) for r in val_mc[["c6", "dt", "mcap_pct"]].itertuples(index=False)}

    needed_c6 = {c for c, _ in target_pairs}
    df_sub = df[df["c6"].isin(needed_c6)].copy()

    # Group pairs by c6 for fast one-pass per stock
    pairs_by_c6 = defaultdict(list)
    for c6, dt in target_pairs:
        pairs_by_c6[c6].append(dt)

    rows = []
    for c6, grp in df_sub.groupby("c6", sort=False):
        grp = grp.reset_index(drop=True)
        dts = list(grp["dt"])
        dt_pos = {d: i for i, d in enumerate(dts)}

        ac = grp["ac"].to_numpy(float)
        ah = grp["ah"].to_numpy(float)
        al = grp["al"].to_numpy(float)
        avw = grp["avwap"].to_numpy(float)
        amt = grp["amt"].to_numpy(float)
        trn = grp["turn_clean"].to_numpy(float)
        zt = grp["is_zt"].to_numpy(float)
        stk = grp["streak"].to_numpy(int)
        n = len(grp)

        s_ac = pd.Series(ac)
        s_ah = pd.Series(ah)
        s_al = pd.Series(al)
        s_trn = pd.Series(trn)
        s_zt = pd.Series(zt)

        ma5 = s_ac.rolling(5, min_periods=5).mean().to_numpy(float)
        ma10 = s_ac.rolling(10, min_periods=10).mean().to_numpy(float)
        ma20 = s_ac.rolling(20, min_periods=20).mean().to_numpy(float)
        ma60 = s_ac.rolling(60, min_periods=40).mean().to_numpy(float)

        max60_h = s_ah.rolling(60, min_periods=20).max().to_numpy(float)
        min60_l = s_al.rolling(60, min_periods=20).min().to_numpy(float)
        max250_h = s_ah.rolling(250, min_periods=60).max().to_numpy(float)
        min250_l = s_al.rolling(250, min_periods=60).min().to_numpy(float)
        max750_h = s_ah.rolling(750, min_periods=120).max().to_numpy(float)
        min750_l = s_al.rolling(750, min_periods=120).min().to_numpy(float)

        max250_c = s_ac.rolling(250, min_periods=60).max().to_numpy(float)
        is_nh250 = ((ac >= max250_c - 1e-9) & np.isfinite(max250_c)).astype(float)
        nh_cnt60 = pd.Series(is_nh250).rolling(60, min_periods=20).sum().to_numpy(float)

        trn5 = s_trn.rolling(5, min_periods=3).mean().to_numpy(float)
        trn20 = s_trn.rolling(20, min_periods=10).mean().to_numpy(float)
        trn_cum20 = s_trn.rolling(20, min_periods=10).sum().to_numpy(float) * 100.0

        def _pct_at(arr_v: np.ndarray, pos_i: int, win: int = 250, min_p: int = 60) -> float:
            if pos_i < 0 or not np.isfinite(arr_v[pos_i]):
                return np.nan
            lo = max(0, pos_i - win + 1)
            w = arr_v[lo : pos_i + 1]
            v = w[np.isfinite(w)]
            return float(np.mean(v <= arr_v[pos_i])) if len(v) >= min_p else np.nan

        zt_cnt250 = s_zt.rolling(250, min_periods=20).sum().to_numpy(float)

        rng20_raw = np.where(
            s_al.rolling(20, min_periods=10).min().to_numpy(float) > 0,
            (s_ah.rolling(20, min_periods=10).max().to_numpy(float) / s_al.rolling(20, min_periods=10).min().to_numpy(float) - 1.0) * 100.0,
            np.nan,
        )
        rng60_raw = np.where(
            s_al.rolling(60, min_periods=30).min().to_numpy(float) > 0,
            (s_ah.rolling(60, min_periods=30).max().to_numpy(float) / s_al.rolling(60, min_periods=30).min().to_numpy(float) - 1.0) * 100.0,
            np.nan,
        )

        for buy_dt in pairs_by_c6[c6]:
            pos = dt_pos.get(buy_dt)
            row_d = {"c6": c6, "dt": buy_dt}
            if pos is None or pos < 1:
                # Fallback if buy_dt wasn't in grp (find last trading date < buy_dt)
                t1 = bisect.bisect_left(dts, buy_dt) - 1
            else:
                t1 = pos - 1
            if t1 < 0:
                rows.append(row_d)
                continue

            t1_dt = dts[t1]
            c_t1 = ac[t1]

            def _pos_rng(hi_a, lo_a):
                if np.isfinite(hi_a) and np.isfinite(lo_a) and hi_a > lo_a:
                    return float(np.clip((c_t1 - lo_a) / (hi_a - lo_a), 0.0, 1.0))
                return np.nan

            pos250 = _pos_rng(max250_h[t1], min250_l[t1])
            row_d["L3_pos_60d_t1"] = _pos_rng(max60_h[t1], min60_l[t1])
            row_d["L3_pos_250d_t1"] = pos250
            row_d["L3_pos_750d_t1"] = _pos_rng(max750_h[t1], min750_l[t1])
            row_d["L3_dd_250d_t1"] = float((c_t1 / max250_h[t1] - 1.0) * 100.0) if (np.isfinite(max250_h[t1]) and max250_h[t1] > 0) else np.nan
            row_d["L3_off_low_250d_t1"] = float((c_t1 / min250_l[t1] - 1.0) * 100.0) if (np.isfinite(min250_l[t1]) and min250_l[t1] > 0) else np.nan
            row_d["L3_bias20_t1"] = float((c_t1 / ma20[t1] - 1.0) * 100.0) if (np.isfinite(ma20[t1]) and ma20[t1] > 0) else np.nan
            row_d["L3_bias60_t1"] = float((c_t1 / ma60[t1] - 1.0) * 100.0) if (np.isfinite(ma60[t1]) and ma60[t1] > 0) else np.nan

            mb = 0
            if np.isfinite(ma5[t1]) and np.isfinite(ma10[t1]) and ma5[t1] > ma10[t1]:
                mb += 1
            if np.isfinite(ma10[t1]) and np.isfinite(ma20[t1]) and ma10[t1] > ma20[t1]:
                mb += 1
            if np.isfinite(ma20[t1]) and np.isfinite(ma60[t1]) and ma20[t1] > ma60[t1]:
                mb += 1
            if np.isfinite(ma20[t1]) and c_t1 > ma20[t1]:
                mb += 1
            row_d["L3_ma_bull_score_t1"] = float(mb)

            # Pre-wave (before current ZT streak started) amplitude & compression
            w_end = max(0, t1 - int(stk[t1]))
            r20_pw = rng20_raw[w_end]
            r60_pw = rng60_raw[w_end]
            row_d["L3_prewave_rng20_t1"] = float(r20_pw) if np.isfinite(r20_pw) else np.nan
            row_d["L3_amp_comp_20v60_t1"] = float(r20_pw / r60_pw) if (np.isfinite(r20_pw) and np.isfinite(r60_pw) and r60_pw > 1e-6) else np.nan
            row_d["L3_newhigh_cnt60_t1"] = float(nh_cnt60[t1]) if np.isfinite(nh_cnt60[t1]) else np.nan

            t5_p = _pct_at(trn5, t1, 250, 60)
            t20_p = _pct_at(trn20, t1, 250, 60)
            row_d["L3_turn5_pct250_t1"] = float(t5_p) if np.isfinite(t5_p) else np.nan
            row_d["L3_turn20_pct250_t1"] = float(t20_p) if np.isfinite(t20_p) else np.nan
            row_d["L3_cum_turn20_t1"] = float(trn_cum20[t1]) if np.isfinite(trn_cum20[t1]) else np.nan

            # 1-year overhead trapped amount ratio
            lo250 = max(0, t1 - 249)
            a_win = amt[lo250 : t1 + 1]
            v_win = avw[lo250 : t1 + 1]
            tot_a = float(np.sum(a_win))
            if tot_a > 0 and (t1 - lo250 + 1) >= 60:
                over_a = float(np.sum(a_win[v_win > c_t1]))
                row_d["L3_overhang_pct_t1"] = over_a / tot_a * 100.0
            else:
                row_d["L3_overhang_pct_t1"] = np.nan

            mc_pct = mcap_pct_map.get((c6, t1_dt), np.nan)
            row_d["L3_mcap_pct_t1"] = mc_pct
            zt250_v = float(zt_cnt250[t1]) if np.isfinite(zt_cnt250[t1]) else np.nan
            row_d["L3_zt_cnt250_t1"] = zt250_v
            row_d["L3_act_x_pos_t1"] = (min(zt250_v, 15.0) / 15.0 * pos250) if (np.isfinite(zt250_v) and np.isfinite(pos250)) else np.nan
            rows.append(row_d)

    return pd.DataFrame(rows)


def run_build(end_cutoff: str, target_pairs: list[tuple[str, str]]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run full PIT 3-layer builder up to end_cutoff and return (mkt_df, feature_table)."""
    st_tl = build_pit_st_timeline(end_cutoff)
    df, all_dts, dt_to_mkt = load_daily_universe(end_cutoff, st_tl)
    mkt_df = build_layer1_market_daily(df, all_dts, end_cutoff)

    pairs_cut = [(c, d) for c, d in target_pairs if d <= end_cutoff]
    l2_df = build_layer2_industry_and_kpl(df, mkt_df, all_dts, dt_to_mkt, pairs_cut, end_cutoff)
    l3_df = build_layer3_stock_cycles(df, pairs_cut)

    feat_df = pd.DataFrame(pairs_cut, columns=["c6", "dt"]).drop_duplicates()
    l1_cols = ["dt"] + [c for c in mkt_df.columns if c.startswith("L1_")]
    feat_df = feat_df.merge(mkt_df[l1_cols], on="dt", how="left")
    feat_df = feat_df.merge(l2_df, on=["c6", "dt"], how="left")
    feat_df = feat_df.merge(l3_df, on=["c6", "dt"], how="left")
    return mkt_df[l1_cols].copy(), feat_df


def main():
    t0 = time.time()
    print("[Step 1] Loading 6 V20.0 strategy pools & untriggered pool...")
    pool_dfs = []
    for st in STRAT_ORDER:
        d = pd.read_parquet(f"{RD028_DIR}/pool_{st}_oldhot.parquet")
        d["code"] = d["code"].astype(str).str.zfill(6)
        d["buy_date"] = d["buy_date"].astype(str).str[:10]
        pool_dfs.append(d[["strategy", "code", "buy_date"]])
    p_all = pd.concat(pool_dfs, ignore_index=True)

    untrig = m1.load_untrig_with_oldhot()
    untrig["code"] = untrig["code"].astype(str).str.zfill(6)
    untrig["buy_date"] = untrig["buy_date"].astype(str).str[:10]

    target_pairs = sorted(
        set(zip(p_all["code"], p_all["buy_date"])) | set(zip(untrig["code"], untrig["buy_date"]))
    )
    print(f"  Total unique (c6, buy_date) pairs: {len(target_pairs)}")

    print("[1/3] Building full 5Y PIT 3-layer warehouse (<= 2026-11-25)...")
    mkt_full, feat_full = run_build("2026-11-25", target_pairs)

    print("[2/3] Running physical truncation test at cutoff = 2024-12-31...")
    mkt_tr, feat_tr = run_build("2024-12-31", target_pairs)

    # Compare every shared row & column strictly <= 2024-12-31
    f_le24 = feat_full[feat_full["dt"] <= "2024-12-31"].sort_values(["c6", "dt"]).reset_index(drop=True)
    t_le24 = feat_tr[feat_tr["dt"] <= "2024-12-31"].sort_values(["c6", "dt"]).reset_index(drop=True)
    assert len(f_le24) == len(t_le24), f"Trunc len mismatch {len(f_le24)} vs {len(t_le24)}"
    assert list(zip(f_le24["c6"], f_le24["dt"])) == list(zip(t_le24["c6"], t_le24["dt"]))

    factor_cols = [c for c in feat_full.columns if c.startswith(("L1_", "L2_", "L3_"))]
    num_diffs = {}
    cat_diffs = {}
    max_all_diff = 0.0
    for c in factor_cols:
        if pd.api.types.is_numeric_dtype(feat_full[c]):
            a = f_le24[c].to_numpy(float)
            b = t_le24[c].to_numpy(float)
            na_same = bool(np.array_equal(np.isnan(a), np.isnan(b)))
            valid = np.isfinite(a) & np.isfinite(b)
            md = float(np.max(np.abs(a[valid] - b[valid]))) if valid.any() else 0.0
            if not na_same:
                md = 999.0
            num_diffs[c] = md
            max_all_diff = max(max_all_diff, md)
        else:
            eq = bool((f_le24[c].fillna("__NA__") == t_le24[c].fillna("__NA__")).all())
            cat_diffs[c] = eq
            if not eq:
                max_all_diff = 999.0

    print(f"  [TRUNCATION PROOF 2024-12-31] rows={len(f_le24)}, max_abs_diff={max_all_diff:.12f}")
    assert max_all_diff == 0.0, f"PIT leakage detected! diffs={ {k:v for k,v in num_diffs.items() if v > 0} } | { {k:v for k,v in cat_diffs.items() if not v} }"

    print("[3/3] Attaching 3-layer features to all 6 strategy pools & untrig, auditing Q8 missingness...")
    missing_audit = {}
    pool_out_list = []
    for st in STRAT_ORDER:
        d = pd.read_parquet(f"{RD028_DIR}/pool_{st}_oldhot.parquet")
        d["code"] = d["code"].astype(str).str.zfill(6)
        d["buy_date"] = d["buy_date"].astype(str).str[:10]
        # Drop any overlapping cols if rerun
        drop_old = [c for c in factor_cols if c in d.columns]
        if drop_old:
            d = d.drop(columns=drop_old)
        m = d.merge(feat_full, left_on=["code", "buy_date"], right_on=["c6", "dt"], how="left")
        if "c6" in m.columns and st != "20cm":
            m.drop(columns=["c6"], inplace=True)
        if "dt" in m.columns:
            m.drop(columns=["dt"], inplace=True)
        # Drop mtm_full/mtm_5y if somehow in parquet (rd028 saved without mtm, check)
        out_p = f"{OUT_DIR}/pool_{st}_cycles.parquet"
        m.to_parquet(out_p, index=False, compression="zstd")
        pool_out_list.append(m[[c for c in m.columns if c in ("strategy", "code", "name", "buy_date", "exit_date", "net_ret", "base_score", "v20_score", "open_pct", "pool_layer", "sim_ok", "is_edge_cand", "is_near_line", "is_pass_official", "is_s_tier", "is_standalone_slot1", "is_v20_slot1") or c in factor_cols]])

        miss_st = {}
        for c in factor_cols:
            mr = float(m[c].isna().mean() * 100.0)
            if mr > 0:
                miss_st[c] = round(mr, 2)
        missing_audit[st] = miss_st

    uni_df = pd.concat(pool_out_list, ignore_index=True)
    uni_df.to_parquet(f"{OUT_DIR}/pools_6strat_with_3layer_cycles.parquet", index=False, compression="zstd")

    mkt_full.to_parquet(f"{OUT_DIR}/rd034_market_daily_pit.parquet", index=False, compression="zstd")

    u_drop = [c for c in factor_cols if c in untrig.columns]
    if u_drop:
        untrig = untrig.drop(columns=u_drop)
    untrig_m = untrig.merge(feat_full, left_on=["code", "buy_date"], right_on=["c6", "dt"], how="left")
    untrig_m.to_parquet(f"{OUT_DIR}/rd034_untrig_with_3layer_cycles.parquet", index=False, compression="zstd")

    # Overall Q8 missingness across unified 4,183 rows
    overall_miss = {c: round(float(uni_df[c].isna().mean() * 100.0), 2) for c in factor_cols if uni_df[c].isna().any()}
    audit = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t0, 2),
        "n_factors_total": len(factor_cols),
        "n_layer1": len([c for c in factor_cols if c.startswith("L1_")]),
        "n_layer2": len([c for c in factor_cols if c.startswith("L2_")]),
        "n_layer3": len([c for c in factor_cols if c.startswith("L3_")]),
        "factor_list": factor_cols,
        "truncation_proof_20241231": {
            "rows_checked": int(len(f_le24)),
            "max_abs_diff": max_all_diff,
            "all_exact_zero": bool(max_all_diff == 0.0),
        },
        "q8_overall_missing_pct_gt0": overall_miss,
        "q8_by_strategy_missing_pct_gt0": missing_audit,
        "sent_phase_dist_5y_days": mkt_full[mkt_full["dt"].between("2021-11-16", "2026-11-16")]["L1_sent_phase_t1"].value_counts().sort_index().to_dict(),
    }
    with open(f"{OUT_DIR}/rd034_step1_pit_audit.json", "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)
    print(f"[DONE Step 1 in {time.time()-t0:.1f}s] factors={len(factor_cols)} (L1={audit['n_layer1']}, L2={audit['n_layer2']}, L3={audit['n_layer3']}), max_missing={max(overall_miss.values(), default=0.0)}%, trunc_diff={max_all_diff}")


if __name__ == "__main__":
    main()

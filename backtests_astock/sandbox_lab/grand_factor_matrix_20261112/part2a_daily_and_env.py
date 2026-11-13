#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Part 2A: Build 5Y PIT Price Panel, Streaks, Historical MultiBoard Memory, and Daily Macro/Regime Sensors."""
import os, json, time, pickle
import numpy as np
import pandas as pd
import pyarrow.dataset as ds

BASE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
SANDBOX = f"{BASE}/backtests_astock/sandbox_lab"
OUT_DIR = f"{SANDBOX}/grand_factor_matrix_20261112"


def build_daily_panel_and_env():
    t0 = time.time()
    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "amount", "turn", "oshare"]
    ds1 = ds.dataset(f"{BASE}/data/cn_hk_price_db/a_daily.parquet", format="parquet")
    df1 = ds1.scanner(columns=cols, filter=(ds.field("date") >= pd.Timestamp("2018-01-01"))).to_table().to_pandas()
    ds2 = ds.dataset(f"{BASE}/data/cn_hk_price_db/a_delisted_daily.parquet", format="parquet")
    df2 = ds2.scanner(columns=cols, filter=(ds.field("date") >= pd.Timestamp("2018-01-01"))).to_table().to_pandas()

    df = pd.concat([df1, df2], ignore_index=True)
    df["c6"] = df["ticker"].astype(str).str[:6]
    df = df[df["ticker"].str.endswith((".SH", ".SZ")) & df["c6"].str.startswith(("00", "60"))].copy()
    df["dt_str"] = df["date"].dt.strftime("%Y-%m-%d")
    df.sort_values(["c6", "dt_str"], inplace=True)
    df.drop_duplicates(["c6", "dt_str"], keep="first", inplace=True)
    df.reset_index(drop=True, inplace=True)

    g = df.groupby("c6")
    df["nth"] = g.cumcount()
    df = df[df["nth"] >= 10].copy().reset_index(drop=True)  # Exclude IPO first 10 days
    g = df.groupby("c6")

    df["adjf"] = df["adj_close"] / df["close"]
    df["pre_c"] = g["close"].shift(1) * g["adjf"].shift(1) / df["adjf"]
    df["pct"] = df["close"] / df["pre_c"] - 1.0
    df["o_pct"] = df["open"] / df["pre_c"] - 1.0
    df["h_pct"] = df["high"] / df["pre_c"] - 1.0
    df["l_pct"] = df["low"] / df["pre_c"] - 1.0
    df["mcap"] = df["close"] * df["oshare"] / 1e8
    df["to"] = df["turn"] * 100.0

    df["zt_price"] = np.floor(df["pre_c"] * 1.10 * 100.0 + 0.5) / 100.0
    df["dt_price"] = np.floor(df["pre_c"] * 0.90 * 100.0 + 0.5) / 100.0
    df["is_zt"] = (df["close"] >= df["zt_price"] - 0.011) & (df["pct"] >= 0.095) & (df["pre_c"] > 0)
    df["is_dt"] = (df["close"] <= df["dt_price"] + 0.011) & (df["pct"] <= -0.095) & (df["pre_c"] > 0)
    df["touch_zt"] = ((df["high"] >= df["zt_price"] - 0.011) | (df["h_pct"] >= 0.098)) & (df["pre_c"] > 0)
    df["touch_dt"] = ((df["low"] <= df["dt_price"] + 0.011) | (df["l_pct"] <= -0.098)) & (df["pre_c"] > 0)
    df["is_yizi"] = df["is_zt"] & (df["open"] >= df["zt_price"] - 0.011) & (df["low"] >= df["zt_price"] - 0.011)
    df["is_yizi_dt"] = df["is_dt"] & (df["open"] <= df["dt_price"] + 0.011) & (df["high"] <= df["dt_price"] + 0.011)

    # Consecutive ZT & DT streaks
    s_zt = df["is_zt"].astype(int)
    df["streak"] = s_zt.groupby([df["c6"], (s_zt != g["is_zt"].shift().fillna(False)).cumsum()]).cumsum() * s_zt
    s_dt = df["is_dt"].astype(int)
    df["dt_streak"] = s_dt.groupby([df["c6"], (s_dt != g["is_dt"].shift().fillna(False)).cumsum()]).cumsum() * s_dt

    df["prev_zt"] = g["is_zt"].shift(1).fillna(False)
    df["is_2b_plus"] = df["is_zt"] & df["prev_zt"]
    df["is_first_board"] = df["is_zt"] & (~df["prev_zt"])

    # Rolling technicals strictly up to T-1 (for day T entry) or T (when T is signal day)
    df["max20"] = g["high"].transform(lambda s: s.rolling(20, min_periods=10).max())
    df["max60"] = g["high"].transform(lambda s: s.rolling(60, min_periods=20).max())
    df["min20"] = g["low"].transform(lambda s: s.rolling(20, min_periods=10).min())
    df["vol_ma5"] = g["amount"].transform(lambda s: s.shift(1).rolling(5, min_periods=2).mean())
    df["zt_cnt20"] = g["is_zt"].transform(lambda s: s.astype(int).rolling(20, min_periods=5).sum())
    df["ret5"] = df["close"] / (g["close"].shift(5) + 1e-6) - 1.0
    df["ret10"] = df["close"] / (g["close"].shift(10) + 1e-6) - 1.0
    df["ret20"] = df["close"] / (g["close"].shift(20) + 1e-6) - 1.0
    df["seal_tightness"] = (
        (df["close"] == df["high"]).astype(int) * 30.0
        + np.clip(df["l_pct"] * 100.0, -10.0, 10.0) * 1.5
        + np.clip((df["close"] - df["open"]) / (df["pre_c"] + 1e-6) * 100.0, 0.0, 10.0) * 2.0
        - np.where(df["amount"] / (df["vol_ma5"] + 1e-6) > 4.0, 15.0, 0.0)
    )

    # Historical multi-board memory: days since previous streak >= 2 ended
    all_dts = sorted(df["dt_str"].unique())
    dt_to_idx = {d: i for i, d in enumerate(all_dts)}
    df["d_idx"] = df["dt_str"].map(dt_to_idx)
    mb_flag = np.where(df["streak"] >= 2, df["d_idx"], np.nan)
    df["_mb_idx"] = mb_flag
    # Shift by current streak + 1 so we look BEFORE the current consecutive streak!
    last_mb = np.full(len(df), 9999, dtype=int)
    c6_arr = df["c6"].values
    didx_arr = df["d_idx"].values
    st_arr = df["streak"].values
    last_seen = {}
    cur_c = None
    prev_mb_before_streak = -9999
    for i in range(len(df)):
        c = c6_arr[i]
        if c != cur_c:
            cur_c = c
            prev_mb_before_streak = -9999
            in_streak_saved = -9999
        st = st_arr[i]
        if st <= 1:
            in_streak_saved = prev_mb_before_streak
        last_mb[i] = min(9999, didx_arr[i] - in_streak_saved) if in_streak_saved >= 0 else 9999
        if st >= 2:
            prev_mb_before_streak = didx_arr[i]
    df["prior_mb_gap"] = last_mb

    print(f"[+] Panel built: {len(df):,} rows across {len(all_dts)} days in {time.time()-t0:.1f}s")
    return df, all_dts, dt_to_idx

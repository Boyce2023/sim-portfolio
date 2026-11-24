#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Layer 1 & 2 & 8: 20cm prices (active+delisted), corporate-action OHLC, PIT top10 lockup, 10cm market stats & benchmarks."""
import json
import os
import numpy as np
import pandas as pd
import pyarrow.dataset as ds

BASE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
OUT_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/part2_native_strategies"


def load_benchmarks() -> tuple[dict, dict]:
    idx_json = json.load(open(f"{BASE}/backtests_astock/sandbox_lab/index_klines_5y_cache.json", encoding="utf-8"))
    sh300 = {k: float(v) for k, v in idx_json.get("sh000300", {}).items()}
    sz399107 = {k: float(v) for k, v in idx_json.get("sz399107", {}).items()}
    p_hs = f"{BASE}/backtests_astock2/commodities_leadlag_10y_20261123/data_cache/sh000300.parquet"
    if os.path.exists(p_hs):
        df_h = pd.read_parquet(p_hs).reset_index()
        for dt_v, c_v in zip(pd.to_datetime(df_h["date"]).dt.strftime("%Y-%m-%d"), df_h["sh000300"].astype(float)):
            sh300.setdefault(dt_v, c_v)
    return sh300, sz399107


def load_10cm_zt_map() -> tuple[dict, dict]:
    """Return mkt_10cm_by_dt[dt] and zt10_by_dt_c6[(dt, c6)] = (is_zt, is_yizi, is_dt)."""
    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close"]
    flt = ds.field("date") >= pd.Timestamp("2020-12-01")
    a1 = ds.dataset(f"{BASE}/data/cn_hk_price_db/a_daily.parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    a2 = ds.dataset(f"{BASE}/data/cn_hk_price_db/a_delisted_daily.parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    a1["dl"] = 0
    a2["dl"] = 1
    df = pd.concat([a1, a2], ignore_index=True)
    df["c6"] = df["ticker"].astype(str).str[:6]
    df = df[df["c6"].str.startswith(("00", "60")) & (~df["ticker"].astype(str).str.endswith(".BJ"))].copy()
    df["dt"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df = df.sort_values(["c6", "dt", "dl"]).drop_duplicates(["c6", "dt"], keep="first").reset_index(drop=True)
    df = df[(df["close"] > 0) & (df["adj_close"] > 0)].copy()
    g = df.groupby("c6", sort=False)
    scale = df["adj_close"] / df["close"]
    prev_ac = g["adj_close"].shift(1)
    ret = df["adj_close"] / prev_ac - 1.0
    o_pct = (df["open"] * scale) / prev_ac - 1.0
    prev_ex = prev_ac / scale
    zt_px = np.floor(prev_ex * 1.10 * 100.0 + 0.5) / 100.0
    dt_px = np.floor(prev_ex * 0.90 * 100.0 + 0.5) / 100.0
    abn = ret.abs() > 0.12
    df["is_zt"] = (prev_ac > 0) & (df["close"] >= zt_px - 0.011) & (ret >= 0.095) & (~abn)
    df["is_dt"] = (prev_ac > 0) & (df["close"] <= dt_px + 0.011) & (ret <= -0.095) & (~abn)
    df["is_yizi"] = df["is_zt"] & (df["low"] == df["high"]) & (o_pct >= 0.095)
    df["is_zt_open"] = (prev_ac > 0) & (df["open"] >= zt_px - 0.011) & (o_pct >= 0.095)
    s_zt = df["is_zt"].astype(int)
    s_sh = df.groupby("c6")["is_zt"].shift(1).fillna(False).astype(bool)
    df["streak"] = s_zt.groupby([df["c6"], (s_zt != s_sh).cumsum()]).cumsum() * s_zt
    df["prev_zt"] = df.groupby("c6")["is_zt"].shift(1).fillna(False).astype(bool)
    df["prev_streak"] = df.groupby("c6")["streak"].shift(1).fillna(0).astype(int)

    zt10_map = {}
    for r in df[(df["dt"] >= "2021-01-01") & (df["is_zt"] | df["is_dt"])][["dt", "c6", "is_zt", "is_yizi", "is_dt"]].itertuples(index=False):
        zt10_map[(r.dt, r.c6)] = (int(r.is_zt), int(r.is_yizi), int(r.is_dt))

    mkt10 = {}
    prev_zt_cnt, prev_dt_cnt, prev_max_b = 40, 5, 3
    for dt, grp in df[df["dt"] >= "2020-12-20"].groupby("dt", sort=True):
        pzt = grp[grp["prev_zt"] & o_pct.loc[grp.index].notna()]
        p1b = grp[(grp["prev_streak"] == 1) & o_pct.loc[grp.index].notna()]
        zt_cnt = int(grp["is_zt"].sum())
        dt_cnt = int(grp["is_dt"].sum())
        max_b = int(grp["streak"].max()) if len(grp) else 0
        if dt >= "2021-01-01":
            mkt10[dt] = {
                "mkt10_zt_cnt": zt_cnt, "mkt10_dt_cnt": dt_cnt, "mkt10_max_board": max_b,
                "mkt10_yizi_cnt": int(grp["is_yizi"].sum()),
                "mkt10_prev_zt_cnt": prev_zt_cnt, "mkt10_prev_dt_cnt": prev_dt_cnt,
                "mkt10_prev_max_board": prev_max_b,
                "mkt10_0925_zt_cnt": int(grp["is_zt_open"].sum()),
                "mkt10_prev_zt_open_avg": float(o_pct.loc[pzt.index].mean()) if len(pzt) else 0.0,
                "mkt10_prev_1b_open_avg": float(o_pct.loc[p1b.index].mean()) if len(p1b) else 0.0,
            }
        prev_zt_cnt, prev_dt_cnt, prev_max_b = zt_cnt, dt_cnt, max_b
    return mkt10, zt10_map


def build_20cm_price_df() -> pd.DataFrame:
    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "amount", "oshare", "turn", "qfq_factor"]
    a1 = pd.read_parquet(f"{BASE}/data/cn_hk_price_db/a_daily.parquet", columns=cols)
    a2 = pd.read_parquet(f"{BASE}/data/cn_hk_price_db/a_delisted_daily.parquet", columns=cols)
    a1 = a1[a1["ticker"].str.startswith(("30", "688", "689"))].copy()
    a2 = a2[a2["ticker"].str.startswith(("30", "688", "689"))].copy()
    a1["dl"] = 0
    a2["dl"] = 1
    df = pd.concat([a1, a2], ignore_index=True)
    df["dt"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df["c6"] = df["ticker"].astype(str).str[:6]
    df = df[df["ticker"].str.endswith((".SH", ".SZ"))].copy()
    df = df.sort_values(["c6", "dt", "dl"]).drop_duplicates(["c6", "dt"], keep="first").reset_index(drop=True)
    df["list_age"] = df.groupby("c6", sort=False).cumcount() + 1
    df = df[(df["dt"] >= "2020-08-24") & (df["close"] > 0) & (df["adj_close"] > 0)].copy().reset_index(drop=True)

    g = df.groupby("c6", sort=False)
    scale = df["adj_close"] / df["close"]
    df["ao"] = df["open"] * scale
    df["ah"] = df["high"] * scale
    df["al"] = df["low"] * scale
    df["ac"] = df["adj_close"]
    df["prev_ac"] = g["ac"].shift(1)
    df["ret"] = df["ac"] / df["prev_ac"] - 1.0
    df["o_pct"] = df["ao"] / df["prev_ac"] - 1.0
    df["h_pct"] = df["ah"] / df["prev_ac"] - 1.0
    df["l_pct"] = df["al"] / df["prev_ac"] - 1.0
    df["abn_ret"] = df["ret"].abs() > 0.22
    df["tradable"] = (df["volume"] > 0) & (df["open"] > 0) & (df["list_age"] > 10) & (~df["abn_ret"])

    prev_ex = df["prev_ac"] / scale
    df["zt_px"] = np.floor(prev_ex * 1.20 * 100.0 + 0.5) / 100.0
    df["dt_px"] = np.floor(prev_ex * 0.80 * 100.0 + 0.5) / 100.0
    df["is_zt"] = (df["prev_ac"] > 0) & (df["close"] >= df["zt_px"] - 0.011) & (df["ret"] >= 0.195) & (~df["abn_ret"])
    df["is_dt"] = (df["prev_ac"] > 0) & (df["close"] <= df["dt_px"] + 0.011) & (df["ret"] <= -0.195) & (~df["abn_ret"])
    df["is_touch_zt"] = (df["prev_ac"] > 0) & (df["high"] >= df["zt_px"] - 0.011) & (df["h_pct"] >= 0.195) & (~df["abn_ret"])
    df["is_touch_dt"] = (df["prev_ac"] > 0) & (df["low"] <= df["dt_px"] + 0.011) & (df["l_pct"] <= -0.195) & (~df["abn_ret"])
    df["is_yizi_zt"] = df["is_zt"] & (df["low"] == df["high"]) & (df["o_pct"] >= 0.195)
    df["is_yizi_dt"] = df["is_dt"] & (df["low"] == df["high"]) & (df["o_pct"] <= -0.195)
    df["buyable_open"] = (df["volume"] > 0) & (df["open"] > 0) & (~((df["o_pct"] >= 0.195) & (df["low"] == df["high"])))
    df["sellable_close"] = (df["volume"] > 0) & (df["close"] > 0) & (~((df["ret"] <= -0.195) & (df["low"] == df["high"])))

    s_zt = df["is_zt"].astype(int)
    s_sh = g["is_zt"].shift(1).fillna(False).astype(bool)
    df["streak"] = s_zt.groupby([df["c6"], (s_zt != s_sh).cumsum()]).cumsum() * s_zt
    s_dt = df["is_dt"].astype(int)
    s_dsh = g["is_dt"].shift(1).fillna(False).astype(bool)
    df["dt_streak"] = s_dt.groupby([df["c6"], (s_dt != s_dsh).cumsum()]).cumsum() * s_dt

    for w in (5, 10, 20, 60):
        df[f"ma{w}"] = g["ac"].transform(lambda s: s.rolling(w, min_periods=max(2, w // 2)).mean())
        df[f"bias{w}"] = df["ac"] / df[f"ma{w}"] - 1.0
    for w in (20, 60):
        hi = g["ah"].transform(lambda s: s.rolling(w, min_periods=10).max())
        lo = g["al"].transform(lambda s: s.rolling(w, min_periods=10).min())
        df[f"high{w}"] = hi
        df[f"low{w}"] = lo
        df[f"pos{w}"] = np.where(hi > lo, (df["ac"] - lo) / (hi - lo), 0.5)
        df[f"high{w}_prev"] = g["ah"].transform(lambda s: s.shift(1).rolling(w, min_periods=10).max())
    for k in (2, 3, 5, 10, 20, 30):
        df[f"ret{k}"] = df["ac"] / g["ac"].shift(k) - 1.0

    df["amt_ma5_prev"] = g["amount"].transform(lambda s: s.shift(1).rolling(5, min_periods=2).mean())
    df["amt_ma20_prev"] = g["amount"].transform(lambda s: s.shift(1).rolling(20, min_periods=5).mean())
    df["vol_ratio5"] = df["amount"] / (df["amt_ma5_prev"] + 1e-6)
    df["vol_ratio20"] = df["amount"] / (df["amt_ma20_prev"] + 1e-6)
    df["to"] = df["turn"] * 100.0
    est_sh = np.where(df["oshare"].fillna(0) > 0, df["oshare"], np.where(df["turn"] > 0, df["volume"] / df["turn"], np.nan))
    df["mcap"] = est_sh * df["close"] / 1e8

    # Candle microstructure
    df["is_true_yang"] = df["close"] > df["open"]
    df["body_pct"] = (df["close"] - df["open"]) / (df["open"] + 1e-9)
    rng = df["ah"] - df["al"]
    df["close_pos"] = np.where(rng > 0, (df["ac"] - df["al"]) / rng, 0.5)
    df["amp"] = rng / (df["prev_ac"] + 1e-9)
    df["upper_shad"] = (df["ah"] - np.maximum(df["ao"], df["ac"])) / (df["prev_ac"] + 1e-9)
    df["lower_shad"] = (np.minimum(df["ao"], df["ac"]) - df["al"]) / (df["prev_ac"] + 1e-9)
    df["zt_cnt_20d"] = g["is_zt"].transform(lambda s: s.rolling(20, min_periods=1).sum())
    df["zt_cnt_60d"] = g["is_zt"].transform(lambda s: s.rolling(60, min_periods=1).sum())
    df["dt_cnt_10d"] = g["is_dt"].transform(lambda s: s.rolling(10, min_periods=1).sum())

    # Attach PIT Top10 freeholders lockup (NOTICE_DATE < dt)
    t10 = json.load(open(f"{OUT_DIR}/pit_top10_20cm_summary.json", encoding="utf-8"))
    lock_arr = np.full(len(df), np.nan)
    big5_arr = np.full(len(df), np.nan)
    for c6, idx_arr in g.groups.items():
        recs = t10.get(c6)
        if not recs:
            continue
        # recs sorted by [notice_date, end_date, sum_rt, big5_rt]
        dts = df.loc[idx_arr, "dt"].values
        l_vals = np.full(len(dts), np.nan)
        b_vals = np.full(len(dts), np.nan)
        for j, d in enumerate(dts):
            best_ed, best_l, best_b = "", np.nan, np.nan
            for nd, ed, l10, b5 in recs:
                if nd < d and ed >= best_ed:
                    best_ed, best_l, best_b = ed, l10, b5
            l_vals[j], b_vals[j] = best_l, best_b
        lock_arr[idx_arr] = l_vals
        big5_arr[idx_arr] = b_vals
    df["lock_top10"] = lock_arr
    df["lock_big5"] = big5_arr
    lock_fill = np.where(np.isnan(lock_arr), 40.0, np.clip(lock_arr, 0.0, 95.0))
    df["real_free_mcap"] = df["mcap"] * (1.0 - lock_fill / 100.0)
    df["real_to"] = df["to"] / (1.0 - lock_fill / 100.0)
    return df

#!/usr/bin/env python3
"""
Build survivorship-free daily market, index, style, sector, and microstructure panel
from 2000-01-01 to 2026-11-13 using:
  1. Tencent official A-share indices via akshare (ZERO yfinance per D12!)
  2. Local survivorship-free a_daily.parquet + a_delisted_daily.parquet + bj_daily.parquet
  3. Local short-term strategy ledgers (v18 一进二, v51 高标首阴, sub2_daily_regime)
"""
import os
import json
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import akshare as ak

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/output/csrc_policy_100factors_20261114/backtest"
os.makedirs(OUT_DIR, exist_ok=True)

# 1. Fetch official indices via Tencent API (akshare)
INDEX_MAP = {
    "sh000001": "sh_comp",       # 上证综指 (1990-2026)
    "sh000300": "csi300",        # 沪深300 (2005-2026)
    "sz399006": "chinext",       # 创业板指 (2010-2026)
    "sh000688": "star50",        # 科创50 (2020-2026)
    "sh000905": "csi500",        # 中证500 (2007-2026)
    "sh000852": "csi1000",       # 中证1000 (2014-2026)
    "sh000016": "sse50",         # 上证50 (2004-2026)
    "sh000922": "csi_div",       # 中证红利 (2008-2026)
    "sz399975": "brokerage",     # 证券公司指数 (券商)
    "sz399986": "bank_idx",      # 中证银行
    "sh000941": "new_energy",    # 新能源
    "sz399997": "baijiu",        # 中证白酒/消费代表
}

idx_frames = {}
for sym, col_prefix in INDEX_MAP.items():
    try:
        df = ak.stock_zh_index_daily_tx(symbol=sym)
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df = df.sort_values("date").drop_duplicates("date")
        df = df[df["date"] >= "2000-01-01"].copy()
        df[f"{col_prefix}_open"] = df["open"].astype(float)
        df[f"{col_prefix}_high"] = df["high"].astype(float)
        df[f"{col_prefix}_low"] = df["low"].astype(float)
        df[f"{col_prefix}_close"] = df["close"].astype(float)
        df[f"{col_prefix}_prev_close"] = df[f"{col_prefix}_close"].shift(1)
        df[f"{col_prefix}_cc_ret"] = df[f"{col_prefix}_close"] / df[f"{col_prefix}_prev_close"] - 1.0
        df[f"{col_prefix}_gap_ret"] = df[f"{col_prefix}_open"] / df[f"{col_prefix}_prev_close"] - 1.0
        df[f"{col_prefix}_oc_ret"] = df[f"{col_prefix}_close"] / df[f"{col_prefix}_open"] - 1.0
        idx_frames[col_prefix] = df[[
            "date",
            f"{col_prefix}_open", f"{col_prefix}_high", f"{col_prefix}_low", f"{col_prefix}_close",
            f"{col_prefix}_cc_ret", f"{col_prefix}_gap_ret", f"{col_prefix}_oc_ret"
        ]]
        print(f"Index {sym} ({col_prefix}): {len(df)} rows [{df['date'].min()} -> {df['date'].max()}]")
    except Exception as e:
        print(f"WARN index {sym} failed: {e}")

# Merge all indices on sh_comp calendar
cal = idx_frames["sh_comp"].copy()
for k, v in idx_frames.items():
    if k != "sh_comp":
        cal = cal.merge(v, on="date", how="left")

# 2. Load survivorship-free individual stock daily parquet (2000-01-01 to 2026-11-13)
DATA_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db"
cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "amount", "oshare", "qfq_factor"]

parts = []
for fn in ["a_daily.parquet", "a_delisted_daily.parquet", "bj_daily.parquet"]:
    p = os.path.join(DATA_DIR, fn)
    if os.path.exists(p):
        t = pq.read_table(p, columns=cols, filters=[("date", ">=", pd.Timestamp("2000-01-01"))])
        df_part = t.to_pandas()
        df_part["date"] = pd.to_datetime(df_part["date"]).dt.strftime("%Y-%m-%d")
        parts.append(df_part)
        print(f"Loaded {fn}: {len(parts[-1])} rows")

stk = pd.concat(parts, ignore_index=True)
stk = stk.drop_duplicates(["date", "ticker"]).sort_values(["ticker", "date"]).reset_index(drop=True)

# True split/dividend-adjusted series: per reference_cn_hk_price_db.md, adj_close = close / qfq_factor
# Compute open_adj and high_adj proportionally via close_adj / close ratio on same day
ratio = np.where(stk["close"] > 0, stk["adj_close"] / stk["close"], 1.0)
stk["open_adj"] = stk["open"] * ratio
stk["high_adj"] = stk["high"] * ratio
stk["low_adj"] = stk["low"] * ratio

stk["prev_adj_close"] = stk.groupby("ticker")["adj_close"].shift(1)
stk["prev_raw_close"] = stk.groupby("ticker")["close"].shift(1)

valid = (stk["prev_adj_close"] > 0) & (stk["open_adj"] > 0) & (stk["adj_close"] > 0) & (stk["amount"] > 0)
stk = stk[valid].copy()

stk["cc_ret"] = stk["adj_close"] / stk["prev_adj_close"] - 1.0
stk["gap_ret"] = stk["open_adj"] / stk["prev_adj_close"] - 1.0
stk["oc_ret"] = stk["adj_close"] / stk["open_adj"] - 1.0
stk["high_ret"] = stk["high_adj"] / stk["prev_adj_close"] - 1.0
stk["mkt_cap"] = stk["close"] * stk["oshare"]

# Board classification for limit-up threshold & hard-tech proxy
tk = stk["ticker"].astype(str)
is_20pct = (
    tk.str.startswith("688") |
    ((tk.str.startswith("300") | tk.str.startswith("301")) & (stk["date"] >= "2020-08-24"))
)
is_bj = tk.str.startswith("8") | tk.str.startswith("4") | tk.str.startswith("92")
zt_thresh = np.where(is_bj, 0.292, np.where(is_20pct, 0.195, 0.0975))
dt_thresh = np.where(is_bj, -0.292, np.where(is_20pct, -0.195, -0.0975))

stk["is_zt"] = (stk["cc_ret"] >= zt_thresh) & (stk["cc_ret"] <= 0.35)
stk["is_dt"] = (stk["cc_ret"] <= dt_thresh) & (stk["cc_ret"] >= -0.35)
stk["touched_zt"] = (stk["high_ret"] >= zt_thresh) & (stk["high_ret"] <= 0.35)
stk["is_broken_zt"] = stk["touched_zt"] & (~stk["is_zt"])

# Consecutive limit-up streak per stock
def calc_streak(s):
    arr = s.to_numpy(dtype=np.int8)
    out = np.zeros(len(arr), dtype=np.int16)
    c = 0
    for i, v in enumerate(arr):
        if v:
            c += 1
        else:
            c = 0
        out[i] = c
    return out

stk["zt_streak"] = stk.groupby("ticker", sort=False)["is_zt"].transform(calc_streak)
stk["prev_zt_streak"] = stk.groupby("ticker", sort=False)["zt_streak"].shift(1).fillna(0)

# Board / style flags
stk["is_tech_board"] = tk.str.startswith("688") | tk.str.startswith("300") | tk.str.startswith("301")

# Daily size rank (0 to 1) for large-cap vs micro-cap survivorship-free portfolios
stk["cap_pct"] = stk.groupby("date")["mkt_cap"].rank(pct=True)
stk["is_micro30"] = stk["cap_pct"] <= 0.30
stk["is_large10"] = stk["cap_pct"] >= 0.90

# Clip extreme IPO day-1 outliers for equal-weight portfolio aggregation
stk["cc_clean"] = stk["cc_ret"].clip(-0.30, 0.30)
stk["oc_clean"] = stk["oc_ret"].clip(-0.25, 0.25)
stk["gap_clean"] = stk["gap_ret"].clip(-0.20, 0.20)

print("Aggregating daily cross-sectional metrics...")
g = stk.groupby("date")
daily = pd.DataFrame({
    "n_stocks": g["ticker"].count(),
    "total_amount_yi": g["amount"].sum() / 1e8,
    "ew_cc_ret": g["cc_clean"].mean(),
    "ew_oc_ret": g["oc_clean"].mean(),
    "ew_gap_ret": g["gap_clean"].mean(),
    "up_ratio": g["cc_ret"].apply(lambda s: (s > 0).mean()),
    "zt_cnt": g["is_zt"].sum(),
    "dt_cnt": g["is_dt"].sum(),
    "touched_zt_cnt": g["touched_zt"].sum(),
    "broken_zt_cnt": g["is_broken_zt"].sum(),
    "max_zt_streak": g["zt_streak"].max(),
    "b3plus_cnt": g["zt_streak"].apply(lambda s: (s >= 3).sum()),
}).reset_index()

daily["broken_rate"] = np.where(daily["touched_zt_cnt"] > 0, daily["broken_zt_cnt"] / daily["touched_zt_cnt"], np.nan)

# Sub-portfolios: Micro30, Large10, TechBoard (688+300), High-Board Relay (prev_zt_streak >= 3)
for label, mask in [
    ("micro30", stk["is_micro30"]),
    ("large10", stk["is_large10"]),
    ("tech_board", stk["is_tech_board"]),
    ("high_relay", stk["prev_zt_streak"] >= 3),
]:
    sub = stk[mask].groupby("date").agg(
        **{
            f"{label}_cc_ret": ("cc_clean", "mean"),
            f"{label}_oc_ret": ("oc_clean", "mean"),
            f"{label}_gap_ret": ("gap_clean", "mean"),
        }
    ).reset_index()
    daily = daily.merge(sub, on="date", how="left")

# Merge index panel + daily breadth panel
panel = cal.merge(daily, on="date", how="left").sort_values("date").reset_index(drop=True)

# Splice benchmark: csi300 from 2005-04-08 onward, sh_comp / large10 before 2005-04-08
panel["bench_cc_ret"] = panel["csi300_cc_ret"].fillna(panel["large10_cc_ret"]).fillna(panel["sh_comp_cc_ret"])
panel["bench_oc_ret"] = panel["csi300_oc_ret"].fillna(panel["large10_oc_ret"]).fillna(panel["sh_comp_oc_ret"])
panel["bench_gap_ret"] = panel["csi300_gap_ret"].fillna(panel["large10_gap_ret"]).fillna(panel["sh_comp_gap_ret"])
panel["bench_level"] = (1.0 + panel["bench_cc_ret"].fillna(0.0)).cumprod()

# Ex-ante rolling state variables (strictly point-in-time as of day T close!)
panel["bench_ret_5d"] = panel["bench_level"] / panel["bench_level"].shift(5) - 1.0
panel["bench_ret_20d"] = panel["bench_level"] / panel["bench_level"].shift(20) - 1.0
panel["bench_ret_60d"] = panel["bench_level"] / panel["bench_level"].shift(60) - 1.0
panel["bench_dd_60d"] = panel["bench_level"] / panel["bench_level"].rolling(60, min_periods=10).max() - 1.0
panel["bench_dd_250d"] = panel["bench_level"] / panel["bench_level"].rolling(250, min_periods=30).max() - 1.0
panel["bench_vol_20d"] = panel["bench_cc_ret"].rolling(20, min_periods=10).std() * np.sqrt(242)
panel["amount_pct_250d"] = panel["total_amount_yi"].rolling(250, min_periods=30).rank(pct=True)
panel["amount_ratio_20d"] = panel["total_amount_yi"] / panel["total_amount_yi"].rolling(20, min_periods=5).mean()

# Merge production short-term strategy daily PnL (v18 一进二, v51 高标首阴)
v18_path = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/full_day_by_day_v18_ledger.csv"
if os.path.exists(v18_path):
    v18 = pd.read_csv(v18_path)
    v18_d = v18.groupby("buy_date").agg(
        v18_1to2_ret=("net_ret", "mean"),
        v18_1to2_cnt=("net_ret", "count")
    ).reset_index().rename(columns={"buy_date": "date"})
    panel = panel.merge(v18_d, on="date", how="left")

v51_path = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/trainer_high_v51/v51_ledger_42.csv"
if os.path.exists(v51_path):
    v51 = pd.read_csv(v51_path)
    v51_d = v51.groupby("buy_date").agg(
        v51_high_dip_ret=("net_ret", "mean"),
        v51_high_dip_cnt=("net_ret", "count")
    ).reset_index().rename(columns={"buy_date": "date"})
    panel = panel.merge(v51_d, on="date", how="left")

out_pq = os.path.join(OUT_DIR, "daily_market_panel.parquet")
panel.to_parquet(out_pq, index=False)
print(f"SUCCESS: Saved {out_pq} with {len(panel)} trading days, {len(panel.columns)} columns [{panel['date'].min()} -> {panel['date'].max()}]")

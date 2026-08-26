#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Step 1: 从 univ2025.db 重构全年涨停标记(用于计算连板/首板需要跨期连续性)，
输出:
  raw/zt_all_2025.csv : 全年涨停记录 (code,date,close,preclose,pct,turn,amount,board_type,limit_pct,is_zt,isST)
  raw/zt_may_jun_2025.csv : 5-6月涨停记录(子集，含前后20日均值/换手辅助字段)
  raw/limit_up_daily_count_may_jun.csv : 5-6月每日涨停家数
"""
import sqlite3
import pandas as pd
import numpy as np
import os

DB = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban/univ2025.db"
OUTDIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/research-notes/astock-database/2026-08-26_游资选股学习/raw"
os.makedirs(OUTDIR, exist_ok=True)

def board_type(code):
    p = code[:6]
    if p in ("sh.688", "sh.689"):
        return "STAR"       # 科创板 20%
    if p in ("sz.300", "sz.301", "sz.302"):
        return "CHINEXT"    # 创业板 20%
    if p.startswith("sh.") or p.startswith("sz."):
        return "MAIN"       # 主板/原中小板 10%
    return "OTHER"

def limit_pct(board, isST):
    if isST:
        return 0.05
    if board in ("STAR", "CHINEXT"):
        return 0.20
    if board == "MAIN":
        return 0.10
    return None

print("Loading full 2025 table from sqlite...")
conn = sqlite3.connect(DB)
df = pd.read_sql_query("SELECT code,date,open,high,low,close,preclose,volume,amount,turn,isST FROM k ORDER BY code,date", conn)
conn.close()
print("rows loaded:", len(df))

df["board"] = df["code"].map(board_type)
df["limitpct"] = df.apply(lambda r: limit_pct(r["board"], r["isST"]), axis=1)
df = df[df["limitpct"].notna()].copy()

# theoretical limit price = round(preclose*(1+limitpct), 2)
df["limit_price"] = (df["preclose"] * (1 + df["limitpct"])).round(2)
# is_zt: closed AT the limit price (within 1 cent tolerance for float rounding)
df["is_zt"] = (df["close"] >= df["limit_price"] - 0.005) & (df["preclose"] > 0)
df["pct_chg"] = (df["close"] / df["preclose"] - 1) * 100

df.to_csv(os.path.join(OUTDIR, "zt_all_2025_full.csv.gz"), index=False, compression="gzip")
print("Full year saved (gzip).")

zt = df[df["is_zt"]].copy()
zt.to_csv(os.path.join(OUTDIR, "zt_all_2025.csv"), index=False)
print("Total ZT rows 2025:", len(zt))

# daily zt count for whole year (sanity check)
daily_count = zt.groupby("date").size().reset_index(name="n_zt")
daily_count.to_csv(os.path.join(OUTDIR, "zt_daily_count_full_year.csv"), index=False)

# May-June subset
mj = zt[(zt["date"] >= "2025-05-01") & (zt["date"] <= "2025-06-30")].copy()
mj.to_csv(os.path.join(OUTDIR, "zt_may_jun_2025.csv"), index=False)
print("May-Jun ZT rows:", len(mj))

mj_daily = mj.groupby("date").size().reset_index(name="n_zt").sort_values("n_zt", ascending=False)
mj_daily.to_csv(os.path.join(OUTDIR, "limit_up_daily_count_may_jun.csv"), index=False)
print("\nTop 15 days by ZT count in May-Jun 2025:")
print(mj_daily.head(15).to_string(index=False))

print("\nAll trading days count in May-Jun:", mj["date"].nunique())

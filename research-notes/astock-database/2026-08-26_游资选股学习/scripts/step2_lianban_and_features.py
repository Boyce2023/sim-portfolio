#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Step 2: 用全年涨停布尔序列计算每只票的"连续涨停板数"(board_number)，
并给每条5-6月涨停记录附加特征: 流通市值(反推)/前20日涨幅(不含当日)/换手率/是否首板/连板数
输出:
  raw/zt_may_jun_with_features.csv
  raw/lianban_ge3_may_jun.csv  (board_number>=3 的记录，即"连板股在这天打出>=3板")
  raw/lianban_stock_summary.csv (每只连板股的最高连板数+起止日期+涉及题材代码留空待人工聚类)
"""
import pandas as pd
import numpy as np
import os

BASE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/research-notes/astock-database/2026-08-26_游资选股学习"
RAW = os.path.join(BASE, "raw")

print("Loading full year gzip...")
df = pd.read_csv(os.path.join(RAW, "zt_all_2025_full.csv.gz"), compression="gzip")
df = df.sort_values(["code", "date"]).reset_index(drop=True)

# --- 连板数计算 ---
# BUGFIX(2026-08-26): 原实现把streak_id的cumcount算在"含前导非涨停行"的分组上，
# 导致每次新streak的第一个涨停日被记成board_number=2而不是1(验证: board_number==1
# 的记录数在全库仅10条，明显不对，应占绝大多数)。修正为: 先算streak_id(含全部行，
# 用于分组标识)，再只在is_zt子集内对streak_id做cumcount，这样前导非涨停行不占位。
df["is_zt"] = df["is_zt"].astype(bool)
df["streak_id"] = (~df["is_zt"]).groupby(df["code"]).cumsum()
df["board_number"] = 0
zt_mask = df["is_zt"]
df.loc[zt_mask, "board_number"] = df.loc[zt_mask].groupby(["code", "streak_id"]).cumcount() + 1

# --- 前20日涨幅(不含当日): close[t-1]/close[t-21]-1，用收盘价序列 ---
df["close_shift1"] = df.groupby("code")["close"].shift(1)
df["close_shift21"] = df.groupby("code")["close"].shift(21)
df["ret_20d_prior"] = (df["close_shift1"] / df["close_shift21"] - 1) * 100

# --- 流通市值反推 (亿元) ---
df["circ_mktcap_yi"] = np.where(df["turn"] > 0, df["amount"] / (df["turn"] / 100) / 1e8, np.nan)

# --- 只取5-6月 ZT 记录 ---
mj = df[(df["is_zt"]) & (df["date"] >= "2025-05-01") & (df["date"] <= "2025-06-30")].copy()
mj["is_first_board"] = mj["board_number"] == 1
mj = mj[["code","date","close","preclose","pct_chg","turn","amount","circ_mktcap_yi",
         "board_number","is_first_board","ret_20d_prior","isST","board"]]
mj.to_csv(os.path.join(RAW, "zt_may_jun_with_features.csv"), index=False)
print("May-Jun ZT with features:", len(mj))

lb = mj[mj["board_number"] >= 3].copy().sort_values(["board_number"], ascending=False)
lb.to_csv(os.path.join(RAW, "lianban_ge3_may_jun.csv"), index=False)
print("Records with board_number>=3 in May-Jun:", len(lb))
print("Distinct stocks with >=3 board in window:", lb["code"].nunique())

# summary per stock: max board number achieved (could straddle window boundary, use full-year df to get true max streak but flag if peak occurred within window)
mj_codes = lb["code"].unique().tolist()
summ_rows = []
for code in mj_codes:
    sub = df[df["code"] == code].copy()
    # find the max board_number achieved with board's date within May-Jun window, and its date
    sub_mj = sub[(sub["date"] >= "2025-05-01") & (sub["date"] <= "2025-06-30") & (sub["is_zt"])]
    if sub_mj.empty:
        continue
    max_board = sub_mj["board_number"].max()
    peak_date = sub_mj.loc[sub_mj["board_number"] == max_board, "date"].iloc[0]
    # find the streak start date: go backward from peak
    peak_idx = sub[sub["date"] == peak_date].index[0]
    start_idx = peak_idx - (max_board - 1)
    start_date = sub.loc[start_idx, "date"] if start_idx >= sub.index.min() else None
    summ_rows.append({"code": code, "max_board_in_window": max_board, "peak_date": peak_date, "streak_start_date": start_date})

summ = pd.DataFrame(summ_rows).sort_values("max_board_in_window", ascending=False)
summ.to_csv(os.path.join(RAW, "lianban_stock_summary.csv"), index=False)
print("\nTop 25 lianban stocks by max board in window:")
print(summ.head(25).to_string(index=False))

print("\n--- sanity: overall ZT count check vs step1 ---")
print("mj total zt rows recomputed:", len(mj), "(step1 reported 3144, should match)")

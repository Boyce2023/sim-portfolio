#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import pandas as pd
import numpy as np
import os

BASE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/research-notes/astock-database/2026-08-26_游资选股学习"
RAW = os.path.join(BASE, "raw")

names = pd.read_csv(os.path.join(RAW, "code_name_map.csv"), dtype={"code": str})
names["code6"] = names["code"].str.zfill(6)

mj = pd.read_csv(os.path.join(RAW, "zt_may_jun_with_features.csv"))
mj["code6"] = mj["code"].str.split(".").str[1]
mj = mj.merge(names[["code6", "name"]], on="code6", how="left")

mj.to_csv(os.path.join(RAW, "zt_may_jun_named.csv"), index=False)
print("Named ZT rows:", len(mj), "| missing name:", mj["name"].isna().sum())

daily_count = mj.groupby("date").size().reset_index(name="n_zt").sort_values("n_zt", ascending=False)
top_days = daily_count.head(8)["date"].tolist()
print("Top 8 days:", top_days)

with open(os.path.join(RAW, "top_days_lianban_leaders.txt"), "w") as f:
    for d in top_days:
        sub = mj[mj["date"] == d].sort_values("board_number", ascending=False)
        n = len(sub)
        f.write(f"\n===== {d}  (当日涨停总数={n}) =====\n")
        f.write("-- 连板龙头(board_number desc, top20) --\n")
        for _, r in sub.head(20).iterrows():
            f.write(f"{r['code']}\t{r['name']}\t{r['board_number']}板\t涨跌{r['pct_chg']:.1f}%\t换手{r['turn']:.1f}%\t流通市值{r['circ_mktcap_yi']:.1f}亿\tST={r['isST']}\n")
        f.write("-- 全部涨停股(简表,按流通市值升序,看小盘特征) --\n")
        sub2 = sub.sort_values("circ_mktcap_yi")
        names_list = [f"{r['name']}({r['board_number']}板)" for _, r in sub2.iterrows()]
        f.write(" / ".join(names_list) + "\n")

print("Wrote top_days_lianban_leaders.txt")

# ===== 全窗口量化特征表 =====
mj["mktcap_bucket"] = pd.cut(mj["circ_mktcap_yi"],
    bins=[0,20,50,100,200,500,1e6],
    labels=["<20亿","20-50亿","50-100亿","100-200亿","200-500亿",">500亿"])

print("\n=== 流通市值分布(全部5-6月涨停记录 n=%d) ===" % len(mj))
print(mj["mktcap_bucket"].value_counts(normalize=True).sort_index().mul(100).round(1))

print("\n=== 首板 vs 连板占比 ===")
print(mj["is_first_board"].value_counts(normalize=True).mul(100).round(1))

print("\n=== board_number 分布 ===")
print(mj["board_number"].value_counts().sort_index())

print("\n=== 换手率描述统计(全部涨停记录) ===")
print(mj["turn"].describe())

print("\n=== 前20日涨幅(不含当日)描述统计 ===")
print(mj["ret_20d_prior"].describe())

print("\n=== 首板 vs >=2板 的市值/换手/前期涨幅对比 ===")
g = mj.groupby("is_first_board")[["circ_mktcap_yi","turn","ret_20d_prior"]].median()
print(g)

mj.to_csv(os.path.join(RAW, "zt_may_jun_named_full.csv"), index=False)

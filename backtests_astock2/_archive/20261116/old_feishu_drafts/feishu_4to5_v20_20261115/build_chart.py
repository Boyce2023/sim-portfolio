#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""生成四进五与多策略纯单仓五年净值曲线对比图"""
import os, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

plt.rcParams["font.sans-serif"] = ["Arial Unicode MS", "STHeiti", "Songti SC"]
plt.rcParams["axes.unicode_minus"] = False

CHART_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/feishu_4to5_v20_20261115/feishu_4to5_v20_chart1.png"
LEDGER_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/p3_deep_100/w2_4to5_v20_ledger.csv"

# 读取四进五台账 (>=120分纯增量)
df = pd.read_csv(LEDGER_PATH)
df120 = df[(df["v20_score"] >= 120) & (~df["is_held_3to4"])].copy()
df120["buy_date"] = pd.to_datetime(df120["buy_date"])
df120.sort_values("buy_date", inplace=True)
df120["cum_nav"] = np.cumprod(1.0 + df120["net_ret"] / 100.0)

# 创建双面板图表
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 8.5), dpi=180, gridspec_kw={"height_ratios": [1.4, 1.0]})

# 面板1: 全局纯单仓组合对比 (对数坐标)
years = np.array([2021.9, 2022.9, 2023.9, 2024.9, 2025.9, 2026.85])
nav_5strat = np.array([1.0, 7.54, 18.40, 73.23, 7100.0, 136325.63])
nav_4strat = np.array([1.0, 7.54, 18.40, 69.91, 4760.0, 91395.80])
nav_base3  = np.array([1.0, 4.90, 12.20, 46.36, 3343.0, 39818.98])
nav_csi300 = np.array([1.0, 0.784, 0.695, 0.797, 0.938, 0.8216])

ax1.plot(years, nav_5strat, color="#D32F2F", linewidth=2.8, marker="o", markersize=6, label="五策略定案纯单仓 (187笔, 胜率67.91%, 净值136325.63倍, 回撤29.22%)")
ax1.plot(years, nav_4strat, color="#F57C00", linewidth=2.2, marker="s", markersize=5, linestyle="--", label="四策略纯单仓 (纳入四进五120分, 182笔, 净值91395.80倍)")
ax1.plot(years, nav_base3,  color="#1976D2", linewidth=1.8, marker="^", markersize=5, linestyle="-.", label="原三主力基准 (高标+三进四+一进二, 175笔, 净值39818.98倍)")
ax1.plot(years, nav_csi300, color="#757575", linewidth=1.5, linestyle=":", label="同期沪深300指数 (五年跌17.84%, 净值0.82倍)")

ax1.set_yscale("log")
ax1.set_ylabel("累计净值 (对数坐标)", fontsize=11, fontweight="bold")
ax1.set_title("2022年至2026年 纯单仓轮动复利净值阶梯进化总图", fontsize=13, fontweight="bold", pad=12)
ax1.grid(True, which="both", linestyle="--", alpha=0.4)
ax1.legend(loc="upper left", fontsize=9.5, framealpha=0.9)
ax1.set_xticks([2022, 2023, 2024, 2025, 2026])
ax1.set_xticklabels(["2022年", "2023年", "2024年", "2025年", "2026年"])

# 标注关键节点
ax1.annotate("136325.63倍", xy=(2026.85, 136325.63), xytext=(2025.8, 200000),
             arrowprops=dict(arrowstyle="->", color="#D32F2F", lw=1.2),
             fontsize=10, fontweight="bold", color="#D32F2F")

# 面板2: 四进五满120分高严档独立净值增长
dates = [pd.to_datetime("2022-01-01")] + list(df120["buy_date"])
navs = [1.0] + list(df120["cum_nav"])
ax2.step(dates, navs, where="post", color="#2E7D32", linewidth=2.2, label="四进五满120分高严档纯增量 (19笔, 均赚13.79%, 净值8.11倍, 回撤24.5%)")

# 标注代表性牛股
for _, row in df120[df120["net_ret"] >= 30.0].iterrows():
    ax2.annotate(f"{row['name']}\n+{row['net_ret']}%",
                 xy=(row["buy_date"], row["cum_nav"]),
                 xytext=(row["buy_date"], row["cum_nav"] * 1.25),
                 arrowprops=dict(arrowstyle="->", color="#388E3C", lw=1.0),
                 fontsize=8.5, ha="center")

ax2.set_ylabel("独立单仓累计净值", fontsize=11, fontweight="bold")
ax2.set_title("四进五满120分高严档 逐笔真实交易轨迹 (2022至2026年)", fontsize=12, fontweight="bold", pad=10)
ax2.grid(True, linestyle="--", alpha=0.5)
ax2.legend(loc="upper left", fontsize=9.5, framealpha=0.9)

plt.tight_layout()
plt.savefig(CHART_PATH, bbox_inches="tight")
plt.close()
print(f"[+] 图表生成成功: {CHART_PATH}")

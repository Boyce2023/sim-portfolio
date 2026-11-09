#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate high-DPI (300 DPI) institutional buy-side charts (Part 1: Charts 1 to 4)
from verified CSV outputs of M1, M2, M3, M4, M5.
Zero tofu squares, crisp Chinese typography.
"""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np
import pandas as pd

# Find reliable macOS Chinese font
CJK_CANDIDATES = [
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
]
font_path = None
for fp in CJK_CANDIDATES:
    if os.path.exists(fp):
        font_path = fp
        break
if font_path:
    prop = fm.FontProperties(fname=font_path)
    plt.rcParams["font.family"] = prop.get_name()
    fm.fontManager.addfont(font_path)
    plt.rcParams["font.sans-serif"] = [prop.get_name(), "PingFang SC", "Heiti TC", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.dpi"] = 300

BASE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-09-us-earnings-macro-30y"
CHART_DIR = os.path.join(BASE, "charts")
os.makedirs(CHART_DIR, exist_ok=True)

NAVY = "#1B365D"
BLUE = "#2B6CB0"
TEAL = "#0F766E"
GREEN = "#15803D"
AMBER = "#D97706"
RED = "#B91C1C"
SLATE = "#64748B"
LIGHT_BG = "#F8FAFC"

# ==============================================================================
# CHART 1: 单季脉冲 vs 连续2至4季双拐点 vs 四大假拐点（3年日历季等权净超额对比）
# ==============================================================================
t1a = pd.read_csv(f"{BASE}/results/m1_trajectory/table_1a_accel_trajectory_gradient.csv").set_index("label")
t1b = pd.read_csv(f"{BASE}/results/m1_trajectory/table_1b_false_vs_true_inflections.csv").set_index("label")
t1c = pd.read_csv(f"{BASE}/results/m1_trajectory/table_1c_gaap_turnaround_anatomy.csv").set_index("label")

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14.5, 6.0), gridspec_kw={"width_ratios": [1.05, 1.15]})
fig.patch.set_facecolor("white")

# Left panel: Pure Revenue Accel vs Double Inflection (1Q -> 2Q -> 3Q -> 4Q+) in CoreLarge >=25B & MidLarge >=10B
x_labels = ["第1季初现", "连续2季", "连续3季", "连续4季以上"]
pure_rev = [
    t1a.loc["MidLarge_ge10B|A1_PureRev|1b_1Q_RevAccel_All", "qtr_ew_alpha_756d"] * 100,
    t1a.loc["MidLarge_ge10B|A1_PureRev|2_Consec_2Q_RevAccel", "qtr_ew_alpha_756d"] * 100,
    t1a.loc["MidLarge_ge10B|A1_PureRev|3_Consec_3Q_RevAccel", "qtr_ew_alpha_756d"] * 100,
    t1a.loc["MidLarge_ge10B|A1_PureRev|4_Consec_4Qplus_RevAccel", "qtr_ew_alpha_756d"] * 100,
]
dbl_inf = [
    t1a.loc["MidLarge_ge10B|A2_OpLeverage|1_DoubleInflect_1Q", "qtr_ew_alpha_756d"] * 100,
    t1a.loc["MidLarge_ge10B|A2_OpLeverage|2_DoubleInflect_2Q", "qtr_ew_alpha_756d"] * 100,
    t1a.loc["MidLarge_ge10B|A2_OpLeverage|3_DoubleInflect_3Q", "qtr_ew_alpha_756d"] * 100,
    t1a.loc["MidLarge_ge10B|A2_OpLeverage|4_DoubleInflect_4Qplus", "qtr_ew_alpha_756d"] * 100,
]

x = np.arange(len(x_labels))
w = 0.35
b1 = ax1.bar(x - w/2, pure_rev, width=w, color="#94A3B8", label="仅营收加速（无利润率改善）")
b2 = ax1.bar(x + w/2, dbl_inf, width=w, color=NAVY, label="营收与利润率双重改善")
ax1.axhline(0, color="#334155", linewidth=1.0)
ax1.set_xticks(x)
ax1.set_xticklabels(x_labels, fontsize=10.5)
ax1.set_ylabel("买入后3年日历季等权对标SPY净超额 (%)", fontsize=10.5)
ax1.set_title("A. 单季脉冲 vs 连续3至4季双重改善（市值>=100亿美元）", fontsize=12, fontweight="bold", pad=12, color=NAVY)
ax1.grid(axis="y", linestyle="--", alpha=0.35)
ax1.set_ylim(-9, 19)
ax1.legend(loc="upper left", frameon=True, facecolor="white", fontsize=9.5)
for bars, col in [(b1, "#475569"), (b2, NAVY)]:
    for bar in bars:
        v = bar.get_height()
        va = "bottom" if v >= 0 else "top"
        off = 0.4 if v >= 0 else -0.5
        ax1.text(bar.get_x() + bar.get_width()/2, v + off, f"{v:+.1f}%", ha="center", va=va, fontsize=9.5, fontweight="bold", color=col)

# Right panel: True vs False Inflections (CoreLarge >=25B / MidLarge >=10B)
items = [
    ("未盈利高毛利连续扩张\n(毛销差>=10%且连扩2季)", t1b.loc["MidLarge_ge10B|True_1b_CommercialInflect_ControlledDil_le5pct", "qtr_ew_alpha_756d"] * 100, TEAL),
    ("真经营性扭亏为盈\n(连3季营收>=15%且现金流正)", t1c.loc["CoreLarge_ge25B|C2_TrueTurnaround_3QRev15_PosOCFq", "qtr_ew_alpha_756d"] * 100, GREEN),
    ("连续3季四重改善复利\n(双扩张+正FCF+稀释<=3%)", 15.33, BLUE),
    ("第1季黄金抢跑交集\n(跳涨>=5%+高ROIC+PE<=25)", t1a.loc["MidLarge_ge10B|A2_OpLeverage|3plus_DoubleInflect_3Qplus", "qtr_ew_alpha_756d"] * 100 if "MidLarge_ge10B|Q1_Gold" not in t1a.index else 11.72, "#3B82F6"),
    ("单季净利暴增基准\n(无视质量盲买单季>=25%)", t1b.loc["CoreLarge_ge25B|Baseline_1Q_GAAP_NI_Surge_ge25pct", "qtr_ew_alpha_756d"] * 100, AMBER),
    ("强周期顶单季爆发\n(5年利润率分位>=85%)", -6.28, RED),
    ("裁员节流型假拐点\n(利润率升但营收增速<3%)", t1b.loc["CoreLarge_ge25B|Trap_1_CostCut_OPM2Q_or_NI25_RevLt3pct", "qtr_ew_alpha_756d"] * 100, RED),
    ("纯会计调节假扭亏\n(营收<5%且经营现金流为负)", t1c.loc["CoreLarge_ge25B|C3b_PureAccountingTurnaround_RevLt5pct_AND_NegOCFq", "qtr_ew_alpha_756d"] * 100, "#7F1D1D"),
]
# Exact verified Q1 gold number from table_1d: +11.72%
items[3] = ("第1季黄金抢跑交集\n(跳涨>=5%+高ROIC+PE<=25)", 11.72, "#2563EB")

y_pos = np.arange(len(items))[::-1]
vals = [it[1] for it in items]
cols = [it[2] for it in items]
lbls = [it[0] for it in items]

bars2 = ax2.barh(y_pos, vals, color=cols, height=0.62)
ax2.axvline(0, color="#334155", linewidth=1.0)
ax2.set_yticks(y_pos)
ax2.set_yticklabels(lbls, fontsize=9.2)
ax2.set_xlabel("买入后3年日历季等权对标SPY净超额 (%)", fontsize=10.5)
ax2.set_title("B. 真商业化拐点 vs 四大典型假拐点陷阱", fontsize=12, fontweight="bold", pad=12, color=NAVY)
ax2.grid(axis="x", linestyle="--", alpha=0.35)
ax2.set_xlim(-18, 58)
for bar, v, c in zip(bars2, vals, cols):
    ha = "left" if v >= 0 else "right"
    off = 0.8 if v >= 0 else -0.8
    ax2.text(v + off, bar.get_y() + bar.get_height()/2, f"{v:+.1f}%", va="center", ha=ha, fontsize=9.5, fontweight="bold", color=c)

for ax in (ax1, ax2):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

fig.suptitle("图1：美股财报拐点真伪解剖（66,680份SEC时点财报，披露次日收盘零前视入场）", fontsize=13.5, fontweight="bold", y=0.98, color=NAVY)
plt.tight_layout(rect=[0, 0, 1, 0.94])
plt.savefig(f"{CHART_DIR}/chart1_trajectory_anatomy.png", dpi=300)
plt.close()

# ==============================================================================
# CHART 2: 第1季抢跑 vs 等第3季确认的真实证伪漏斗与踏空代价精算
# ==============================================================================
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14.0, 5.6))
fig.patch.set_facecolor("white")

# Left: Funnel of 6,726 Q1 initial double-inflections
stages = ["第1季初现双改善\n(起点 100%)", "撑过第2季未熄火\n(留存 42.4%)", "走到第3季确认\n(真拐点 21.1%)"]
pcts = [100.0, 42.37, 21.14]
f_cols = [SLATE, BLUE, TEAL]
b_f = ax1.bar(stages, pcts, width=0.48, color=f_cols)
ax1.set_ylim(0, 116)
ax1.set_ylabel("占第1季初现样本比例 (%)", fontsize=10.5)
ax1.set_title("A. 6,726起初现双改善事件的后续证伪淘汰漏斗", fontsize=12, fontweight="bold", pad=12, color=NAVY)
ax1.grid(axis="y", linestyle="--", alpha=0.35)
for bar, p in zip(b_f, pcts):
    ax1.text(bar.get_x() + bar.get_width()/2, p + 2.2, f"{p:.1f}%", ha="center", va="bottom", fontsize=11, fontweight="bold", color=NAVY)
ax1.annotate("高达78.9%在第3季前证伪熄火\n盲买熄火股3年净超额 负6.8%（大盘）",
             xy=(1.5, 32), xytext=(0.85, 72),
             arrowprops=dict(arrowstyle="->", color=RED, lw=1.5),
             fontsize=9.8, fontweight="bold", color=RED,
             bbox=dict(boxstyle="round,pad=0.4", facecolor="#FEF2F2", edgecolor=RED, alpha=0.9))

# Right: Strategy comparison (Unconditional Q1 vs Wait Q2 vs Wait Q3 vs Wait Q4 vs Q1 Gold) in >=25B / >=10B
strat_lbls = [
    "大盘盲买全部第1季\n(含79%假拐点)",
    "大盘第1季仅贪便宜\n(PE<=22但无跳涨)",
    "等第3季确认再买\n(半年踏空超额中位仅+3.2%)",
    "第1季黄金交集抢跑\n(跳涨>=5%+高ROIC+低PE)",
    "连续4季以上确认\n(长牛主升浪)",
]
strat_vals = [-3.59, -7.36, 11.87, 11.72, 17.01]
strat_cols = [AMBER, RED, TEAL, BLUE, NAVY]
y2 = np.arange(len(strat_lbls))[::-1]
b_s = ax2.barh(y2, strat_vals, color=strat_cols, height=0.56)
ax2.axvline(0, color="#334155", linewidth=1.0)
ax2.set_yticks(y2)
ax2.set_yticklabels(strat_lbls, fontsize=9.5)
ax2.set_xlabel("买入后3年日历季等权对标SPY净超额 (%)", fontsize=10.5)
ax2.set_title("B. 第1季抢跑 vs 等第3季确认的3年净超额对比", fontsize=12, fontweight="bold", pad=12, color=NAVY)
ax2.grid(axis="x", linestyle="--", alpha=0.35)
ax2.set_xlim(-12, 22)
for bar, v, c in zip(b_s, strat_vals, strat_cols):
    ha = "left" if v >= 0 else "right"
    off = 0.45 if v >= 0 else -0.45
    ax2.text(v + off, bar.get_y() + bar.get_height()/2, f"{v:+.2f}%", va="center", ha=ha, fontsize=10, fontweight="bold", color=c)

for ax in (ax1, ax2):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

fig.suptitle("图2：为什么大多数拐点必须等第3季确认（半年仅少赚3.8%中位超额，却过滤78.9%假拐点）", fontsize=13.2, fontweight="bold", y=0.98, color=NAVY)
plt.tight_layout(rect=[0, 0, 1, 0.94])
plt.savefig(f"{CHART_DIR}/chart2_q1_vs_q3_tradeoff.png", dpi=300)
plt.close()

# ==============================================================================
# CHART 3: 财报反应 × 基本面轨迹 × 股价位置（错杀金矿 vs 跳涨续涨 vs 追高火坑）
# ==============================================================================
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14.5, 5.8))
fig.patch.set_facecolor("white")

# Left: Post-earnings reaction buckets on True Acceleration vs Fake/1Q (1Y Qtr EW Alpha %)
cats = [
    "大盘未盈利高毛利扩张\n财报被砸跌>=4%（错杀金矿）",
    "大盘真加速合计(F1+F3)\n财报被砸跌>=4%（次日低吸）",
    "中盘连3季双拐点+PS<=12\n财报跳涨>=8%（黄金追涨）",
    "大盘真加速合计(F1+F3)\n财报跳涨>=4%（共识追高）",
    "大盘无条件盲追跳涨>=10%\n(1年中位超额 负5.0%)",
    "大盘PS>20倍追跳涨>=10%\n(1年胜率仅28.6%)",
    "大盘未盈利且毛销差<10%\n追跳涨>=10%（烧钱诱多）",
]
c_vals = [40.41, 20.19, 15.15, 5.14, -4.97, -24.76, -19.03] # using verified 1Y alpha (last 3 show median/EW verified trap)
# Wait: keep metric 100% uniform on axis! Let's plot BOTH 1Y Qtr-EW Alpha AND 1Y Median Alpha side-by-side or clearly labeled!
# Let's plot exact 1Y Median Alpha (Ex-2020-2021 Bubble verified in M3 Table 3A & 3B!) so zero skew distortion!
cats_clean = [
    "中盘科技医药连3季双拐点\nPS<=15 跳涨>=10%追入",
    "大盘真加速被砸暴跌>=10%\n次日低吸（NTRA与DUOL型）",
    "中盘连3季双拐点+PS<=12\n跳涨>=10%次日追入",
    "大盘未盈利高毛利扩张(F3)\n被砸跌>=4%次日低吸",
    "大盘真加速合计(F1+F3)\n被砸跌>=4%次日低吸",
    "大盘真加速合计(F1+F3)\n跳涨>=4%共识追高",
    "大盘单季初现拐点(F2)\n盲追跳涨>=10%",
    "大盘PS>20倍昂贵估值\n追跳涨>=10%（必套红线）",
]
med_1y_ex_bub = [15.18, 17.56, 12.98, 10.73, 5.80, -2.50, -6.16, -25.58]
c_cols = [TEAL, GREEN, BLUE, "#0D9488", "#2563EB", AMBER, RED, "#7F1D1D"]
y3 = np.arange(len(cats_clean))[::-1]
b3 = ax1.barh(y3, med_1y_ex_bub, color=c_cols, height=0.60)
ax1.axvline(0, color="#334155", linewidth=1.0)
ax1.set_yticks(y3)
ax1.set_yticklabels(cats_clean, fontsize=9.1)
ax1.set_xlabel("剔除疫情泡沫后 1年中位数对标SPY净超额 (%)", fontsize=10.2)
ax1.set_title("A. 财报次日买谁：错杀低吸 vs 黄金追涨 vs 追高红线", fontsize=11.8, fontweight="bold", pad=12, color=NAVY)
ax1.grid(axis="x", linestyle="--", alpha=0.35)
ax1.set_xlim(-32, 24)
for bar, v, c in zip(b3, med_1y_ex_bub, c_cols):
    ha = "left" if v >= 0 else "right"
    off = 0.5 if v >= 0 else -0.5
    ax1.text(v + off, bar.get_y() + bar.get_height()/2, f"{v:+.1f}%", va="center", ha=ha, fontsize=9.5, fontweight="bold", color=c)

# Right: Pre-earnings Price Launchpad x 3-4Q Inflection (3Y Median Alpha % from M3 Section 4.2)
pads = [
    "2至5年右上角缓涨\n+连3季双拐点跳涨",
    "半年至2年健康缓涨\n+连3至4季双拐点",
    "半年横盘紧致蓄势\n+连3至4季双拐点",
    "前期抛物线暴涨过热\n+连3至4季双拐点",
    "深跌超35%左侧抄底\n+连3至4季账面改善",
]
pad_1y = [9.1, 6.2, 7.5, 34.8, -9.0]
pad_3y = [20.6, 13.4, 0.4, -23.8, -24.2]
xp = np.arange(len(pads))
wp = 0.35
bp1 = ax2.bar(xp - wp/2, pad_1y, width=wp, color=BLUE, label="买入后1年中位数净超额")
bp2 = ax2.bar(xp + wp/2, pad_3y, width=wp, color=NAVY, label="买入后3年中位数净超额")
ax2.axhline(0, color="#334155", linewidth=1.0)
ax2.set_xticks(xp)
ax2.set_xticklabels(pads, fontsize=8.8)
ax2.set_ylabel("中位数对标SPY净超额 (%)", fontsize=10.2)
ax2.set_title("B. 五大股价蓄势形态叠加3至4季拐点的1年与3年耐力", fontsize=11.8, fontweight="bold", pad=12, color=NAVY)
ax2.grid(axis="y", linestyle="--", alpha=0.35)
ax2.set_ylim(-31, 42)
ax2.legend(loc="upper right", frameon=True, facecolor="white", fontsize=9.2)
for bars, col in [(bp1, BLUE), (bp2, NAVY)]:
    for bar in bars:
        v = bar.get_height()
        va = "bottom" if v >= 0 else "top"
        off = 0.6 if v >= 0 else -0.8
        ax2.text(bar.get_x() + bar.get_width()/2, v + off, f"{v:+.1f}%", ha="center", va=va, fontsize=8.8, fontweight="bold", color=col)

for ax in (ax1, ax2):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

fig.suptitle("图3：跳涨追不追与错杀买不买（2至5年缓涨是最佳长跑起爆台，PS超20倍与深跌左侧必避）", fontsize=13.0, fontweight="bold", y=0.98, color=NAVY)
plt.tight_layout(rect=[0, 0, 1, 0.94])
plt.savefig(f"{CHART_DIR}/chart3_reaction_x_price_matrix.png", dpi=300)
plt.close()

# ==============================================================================
# CHART 4: 1996至2026年宏观贴现率与信用周期状态开关（为什么当下通杀低PE与纯烧钱）
# ==============================================================================
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14.5, 5.8))
fig.patch.set_facecolor("white")

# Left: Real Rate & Credit Regime Switchboard on SP500_PIT / Commercial PIT (1Y Qtr EW Alpha %)
regimes = [
    "负实际利率(<0%)\n央行放水救市期",
    "信用危机利差>=2.5%\n坏账估值双出清期",
    "高实际利率>=1.5%\n(当下+2.6%资本纪律)",
    "极良性信用利差<1.8%\n(当下1.57%景气期)",
    "再通胀资本开支繁荣\n(当下Q2象限 2Y超额)",
]
low_pe_a = [4.66, 5.96, -3.12, -4.87, -6.56]       # SP500_PIT zero-survivorship verified numbers from M5!
qual_growth_c = [-1.43, 1.15, 8.76, 35.17, 25.98]   # SP500_PIT zero-survivorship verified numbers from M5!
cash_burn_d = [-11.80, -8.50, -10.14, -11.22, -24.54]

xr = np.arange(len(regimes))
wr = 0.26
br1 = ax1.bar(xr - wr, low_pe_a, width=wr, color=AMBER, label="低估值反转(PE<15)")
br2 = ax1.bar(xr, qual_growth_c, width=wr, color=TEAL, label="商业化健康高增龙头(毛销差>=15%)")
br3 = ax1.bar(xr + wr, cash_burn_d, width=wr, color=RED, label="烧钱或未盈利PS>20故事股")

ax1.axhline(0, color="#334155", linewidth=1.0)
ax1.set_xticks(xr)
ax1.set_xticklabels(regimes, fontsize=8.8)
ax1.set_ylabel("标普500历史动态成分池(零幸存者偏差)净超额 (%)", fontsize=9.8)
ax1.set_title("A. 宏观状态决定策略生死（零幸存者偏差SP500动态池）", fontsize=11.8, fontweight="bold", pad=12, color=NAVY)
ax1.grid(axis="y", linestyle="--", alpha=0.35)
ax1.set_ylim(-30, 42)
ax1.legend(loc="upper left", frameon=True, facecolor="white", fontsize=8.8)
for bars, col in [(br1, "#B45309"), (br2, TEAL), (br3, RED)]:
    for bar in bars:
        v = bar.get_height()
        va = "bottom" if v >= 0 else "top"
        off = 0.6 if v >= 0 else -0.8
        ax1.text(bar.get_x() + bar.get_width()/2, v + off, f"{v:+.1f}%", ha="center", va=va, fontsize=7.8, fontweight="bold", color=col)

# Right: 14 Parameters Nonlinear Traps vs Sweet Spots (from M4 verified 3Y Qtr EW Alpha %)
m4_lbls = [
    "高ROIC(>=20%) + 5年利润率洼地(<=35%)\n+ 合理PE(15至40倍) 真双击带",
    "连3季加速 + 自由现金流率>30%\n印钞机型复利龙头",
    "连3季加速 + 毛销差(GM减SGA)>40%\n极强商业化造血能力",
    "表面便宜PE<15 + 5年利润率顶峰(>75%)\n典型强周期见顶价值陷阱",
    "高利率期 5年利润率顶峰(>85%)\n景气高点均值回归杀盈利",
    "高利率期 连3季加速但SBC稀释>5%\n股权抽血吞噬股东回报",
    "毛销差(GM减SGA)<0% 倒贴烧钱扩收\n无经营杠杆商业模式崩塌",
]
m4_vals = [16.6, 15.1, 14.2, -17.9, -22.7, -29.6, -63.4]
m4_cols = [TEAL, GREEN, BLUE, AMBER, RED, "#991B1B", "#450A0A"]
ym4 = np.arange(len(m4_lbls))[::-1]
bm4 = ax2.barh(ym4, m4_vals, color=m4_cols, height=0.58)
ax2.axvline(0, color="#334155", linewidth=1.0)
ax2.set_yticks(ym4)
ax2.set_yticklabels(m4_lbls, fontsize=8.9)
ax2.set_xlabel("买入后3年日历季等权对标SPY净超额 (%)", fontsize=10.0)
ax2.set_title("B. 14项指标交叉验证：为什么低PE必须看5年利润率分位", fontsize=11.8, fontweight="bold", pad=12, color=NAVY)
ax2.grid(axis="x", linestyle="--", alpha=0.35)
ax2.set_xlim(-73, 25)
for bar, v, c in zip(bm4, m4_vals, m4_cols):
    ha = "left" if v >= 0 else "right"
    off = 0.8 if v >= 0 else -0.8
    ax2.text(v + off, bar.get_y() + bar.get_height()/2, f"{v:+.1f}%", va="center", ha=ha, fontsize=9.2, fontweight="bold", color=c)

for ax in (ax1, ax2):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

fig.suptitle("图4：宏观贴现率开关与14指标非线性交叉（当下高实际利率+良性利差专奖励高造血成长龙头）", fontsize=12.8, fontweight="bold", y=0.98, color=NAVY)
plt.tight_layout(rect=[0, 0, 1, 0.94])
plt.savefig(f"{CHART_DIR}/chart4_macro_30y_switchboard.png", dpi=300)
plt.close()

print("Charts 1-4 generated successfully in", CHART_DIR)

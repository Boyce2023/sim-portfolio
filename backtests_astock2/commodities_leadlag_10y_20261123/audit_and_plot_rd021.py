#!/usr/bin/env python3
"""RD021 Q8 Gate #2 Independent Audit + Unified Summary + 2 Publication Charts."""
import json, re
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

BASE = Path("/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/commodities_leadlag_10y_20261123")
m = json.load(open(BASE / "results_metals_energy.json"))
l = json.load(open(BASE / "results_lithium_hog_coal.json"))
a_open = pd.read_parquet(BASE / "data_cache/a_stocks_open.parquet")

plt.rcParams["font.sans-serif"] = ["Hiragino Sans GB", "STHeiti", "Arial Unicode MS", "Songti SC"]
plt.rcParams["axes.unicode_minus"] = False

NAVY, CRIMSON, TEAL, AMBER, SLATE = "#1B365D", "#B91C1C", "#0F766E", "#D97706", "#64748B"

# --- 1. Q8 Independent Audit ---
yf_violations = []
for pyf in BASE.glob("*.py"):
    for idx, line in enumerate(open(pyf), 1):
        if re.search(r"^\s*(import\s+yfinance|from\s+yfinance)", line):
            yf_violations.append((pyf.name, idx))
assert not yf_violations, f"D12 VIOLATION: {yf_violations}"
assert m["meta"]["data_as_of_date"] == "2026-11-20" and l["meta"]["as_of_date"] == "2026-11-20"

# Spot-check extreme single-stock trades against raw a_stocks_open.parquet (0.30% round-trip fee)
spot_checks = []
for tk_key, strat in [("601899.SH__HG_F", "A"), ("600547.SH__AU0", "B"), ("601857.SH__BZ_F", "A")]:
    cat = "copper" if "601899" in tk_key else ("gold" if "600547" in tk_key else "oil")
    trades = m["module3_backtest"][cat][tk_key]["strategies"][strat]["top5_best_trades"]
    if trades:
        tr = trades[0]
        tk = tk_key.split("__")[0]
        p_in = float(a_open.loc[pd.Timestamp(tr["entry_date"]), tk])
        p_out = float(a_open.loc[pd.Timestamp(tr["exit_date"]), tk])
        calc_net = ((p_out * (1 - 0.0015)) / (p_in * (1 + 0.0015)) - 1.0) * 100.0
        diff = abs(calc_net - tr["net_ret_pct"])
        spot_checks.append({"pair": f"{tk_key}:{strat}", "reported": tr["net_ret_pct"], "recalc": round(calc_net, 2), "diff": round(diff, 4)})
for comm, trk, tk, strat in [("hog", "spot_10y", "002714.SZ", "A"), ("lithium", "lc0_live", "002460.SZ", "A"), ("coal", "jm0_10y", "601699.SH", "B")]:
    tr_list = l[comm][trk]["top5_extreme_trades"].get(f"{tk}__{strat}", [])
    if tr_list:
        tr = tr_list[0]
        p_in = float(a_open.loc[pd.Timestamp(tr["entry_date"]), tk])
        p_out = float(a_open.loc[pd.Timestamp(tr["exit_date"]), tk])
        calc_net = ((p_out * (1 - 0.0015)) / (p_in * (1 + 0.0015)) - 1.0) * 100.0
        diff = abs(calc_net - tr["net_ret_pct"])
        spot_checks.append({"pair": f"{comm}.{tk}:{strat}", "reported": tr["net_ret_pct"], "recalc": round(calc_net, 2), "diff": round(diff, 4)})
assert all(x["diff"] < 0.05 for x in spot_checks), f"Spot check mismatch: {spot_checks}"

# --- 2. Extract unified 6-commodity table ---
def get_m_strat(cat, key, sk, per="full"):
    return m["module3_backtest"][cat][key]["strategies"][sk]["periods"][per]

def get_l_strat(comm, trk, target, sk, per="full"):
    node = l[comm][trk]["module3_backtest"][target][sk]
    return node[per] if per in node else node[list(node.keys())[0]]

def get_l_curve(comm, trk, target):
    c = l[comm][trk]["module2_xcorr"][target]["curves_5d"]["ret_60d"]
    s = l[comm][trk]["module2_xcorr"][target]["ret_60d"]
    return c["lags"], c["corrs"], s["peak_lag"], s["peak_corr"], s["corr_lag0"], s["p_eff"]

def get_m_curve(cat, key):
    s = m["module2_crosscorr"][cat][key]["ret_60d"]
    return s["curve_5d"]["lags"], s["curve_5d"]["corrs"], s["peak_lag_days"], s["peak_corr"], s["lag0_corr"], s["peak_p_val"]

# Build concise summary dict for Feishu & final report
summary = {"audit_spot_checks": spot_checks, "hs300_10y": m["benchmarks"]["sh000300_full_10y"], "commodities": {}}
summary["commodities"]["生猪"] = {
    "window": "2016至2026现货 / 2021至2026 LH0",
    "xcorr_peak_d": l["hog"]["spot_10y"]["module2_xcorr"]["HOG_EQ"]["ret_60d"]["peak_lag"],
    "xcorr_r": l["hog"]["spot_10y"]["module2_xcorr"]["HOG_EQ"]["ret_60d"]["peak_corr"],
    "xcorr_r0": l["hog"]["spot_10y"]["module2_xcorr"]["HOG_EQ"]["ret_60d"]["corr_lag0"],
    "xcorr_p": l["hog"]["spot_10y"]["module2_xcorr"]["HOG_EQ"]["ret_60d"]["p_eff"],
    "tp": l["hog"]["spot_10y"]["module1_turning_points"]["HOG_EQ"],
    "A": get_l_strat("hog", "spot_10y", "002714.SZ", "A", "full"),
    "A_eq": get_l_strat("hog", "spot_10y", "HOG_EQ", "A", "full"),
    "A2": get_l_strat("hog", "spot_10y", "HOG_EQ", "A2", "full"),
    "B": get_l_strat("hog", "spot_10y", "HOG_EQ", "B", "full"),
    "C": get_l_strat("hog", "spot_10y", "HOG_EQ", "C_bh", "full"),
    "A2_5y": get_l_strat("hog", "spot_10y", "HOG_EQ", "A2", "5y"),
    "A2_3y": get_l_strat("hog", "spot_10y", "HOG_EQ", "A2", "3y"),
    "B_5y": get_l_strat("hog", "spot_10y", "HOG_EQ", "B", "5y"),
    "B_3y": get_l_strat("hog", "spot_10y", "HOG_EQ", "B", "3y"),
}
summary["commodities"]["碳酸锂"] = {
    "window": "2023.07至2026.11 LC0实盘",
    "xcorr_peak_d": l["lithium"]["lc0_live"]["module2_xcorr"]["LITHIUM_EQ_3"]["ret_60d"]["peak_lag"],
    "xcorr_r": l["lithium"]["lc0_live"]["module2_xcorr"]["LITHIUM_EQ_3"]["ret_60d"]["peak_corr"],
    "xcorr_r0": l["lithium"]["lc0_live"]["module2_xcorr"]["LITHIUM_EQ_3"]["ret_60d"]["corr_lag0"],
    "xcorr_p": l["lithium"]["lc0_live"]["module2_xcorr"]["LITHIUM_EQ_3"]["ret_60d"]["p_eff"],
    "tp": l["lithium"]["lc0_live"]["module1_turning_points"]["LITHIUM_EQ_3"],
    "A": get_l_strat("lithium", "lc0_live", "LITHIUM_EQ_3", "A", "full"),
    "A2": get_l_strat("lithium", "lc0_live_roll252_sens", "LITHIUM_EQ_3", "A2", "full"),
    "B": get_l_strat("lithium", "lc0_live", "LITHIUM_EQ_3", "B", "full"),
    "C": get_l_strat("lithium", "lc0_live", "LITHIUM_EQ_3", "C_bh", "full"),
}
summary["commodities"]["铜"] = {
    "window": "2016至2026 HG_F与CU0",
    "xcorr_peak_d": m["module2_crosscorr"]["copper"]["COPPER_A_EW_vs_CU0"]["ret_60d"]["peak_lag_days"],
    "xcorr_r": m["module2_crosscorr"]["copper"]["COPPER_A_EW_vs_CU0"]["ret_60d"]["peak_corr"],
    "xcorr_r0": m["module2_crosscorr"]["copper"]["COPPER_A_EW_vs_CU0"]["ret_60d"]["lag0_corr"],
    "xcorr_p": m["module2_crosscorr"]["copper"]["COPPER_A_EW_vs_CU0"]["ret_60d"]["peak_p_val"],
    "tp": m["module1_turning_points"]["copper"]["COPPER_A_EW_vs_HG_F"]["summary"],
    "A": get_m_strat("copper", "COPPER_A_EW__HG_F", "A", "full"),
    "A_5y": get_m_strat("copper", "COPPER_A_EW__HG_F", "A", "last_5y"),
    "A_3y": get_m_strat("copper", "COPPER_A_EW__HG_F", "A", "last_3y"),
    "A2": get_m_strat("copper", "COPPER_A_EW__HG_F", "A2", "full"),
    "B": get_m_strat("copper", "COPPER_A_EW__HG_F", "B", "full"),
    "B_5y": get_m_strat("copper", "COPPER_A_EW__HG_F", "B", "last_5y"),
    "B_3y": get_m_strat("copper", "COPPER_A_EW__HG_F", "B", "last_3y"),
    "C": get_m_strat("copper", "COPPER_A_EW__HG_F", "C_buy_hold", "full"),
}
summary["commodities"]["石油"] = {
    "window": "2016至2026 BZ_F / 2018.12起SC0",
    "xcorr_peak_d": m["module2_crosscorr"]["oil"]["OIL_A_EW_vs_SC0"]["ret_60d"]["peak_lag_days"],
    "xcorr_r": m["module2_crosscorr"]["oil"]["OIL_A_EW_vs_SC0"]["ret_60d"]["peak_corr"],
    "xcorr_r0": m["module2_crosscorr"]["oil"]["OIL_A_EW_vs_SC0"]["ret_60d"]["lag0_corr"],
    "xcorr_p": m["module2_crosscorr"]["oil"]["OIL_A_EW_vs_SC0"]["ret_60d"]["peak_p_val"],
    "tp": m["module1_turning_points"]["oil"]["OIL_A_EW_vs_SC0"]["summary"],
    "A_bz": get_m_strat("oil", "OIL_A_EW__BZ_F", "A", "full"),
    "A": get_m_strat("oil", "OIL_A_EW__SC0", "A", "full"),
    "A2": get_m_strat("oil", "OIL_A_EW__BZ_F", "A2", "full"),
    "B": get_m_strat("oil", "OIL_A_EW__BZ_F", "B", "full"),
    "B_sc0": get_m_strat("oil", "OIL_A_EW__SC0", "B", "full"),
    "C": get_m_strat("oil", "OIL_A_EW__BZ_F", "C_buy_hold", "full"),
    "C_sc0": get_m_strat("oil", "OIL_A_EW__SC0", "C_buy_hold", "full"),
}
summary["commodities"]["黄金"] = {
    "window": "2016至2026 AU0与GC_F",
    "xcorr_peak_d": m["module2_crosscorr"]["gold"]["GOLD_A_EW_vs_AU0"]["ret_60d"]["peak_lag_days"],
    "xcorr_r": m["module2_crosscorr"]["gold"]["GOLD_A_EW_vs_AU0"]["ret_60d"]["peak_corr"],
    "xcorr_r0": m["module2_crosscorr"]["gold"]["GOLD_A_EW_vs_AU0"]["ret_60d"]["lag0_corr"],
    "xcorr_p": m["module2_crosscorr"]["gold"]["GOLD_A_EW_vs_AU0"]["ret_60d"]["peak_p_val"],
    "tp": m["module1_turning_points"]["gold"]["GOLD_A_EW_vs_AU0"]["summary"],
    "A": get_m_strat("gold", "GOLD_A_EW__AU0", "A", "full"),
    "A2": get_m_strat("gold", "GOLD_A_EW__AU0", "A2", "full"),
    "B": get_m_strat("gold", "GOLD_A_EW__AU0", "B", "full"),
    "B_5y": get_m_strat("gold", "GOLD_A_EW__AU0", "B", "last_5y"),
    "B_3y": get_m_strat("gold", "GOLD_A_EW__AU0", "B", "last_3y"),
    "C": get_m_strat("gold", "GOLD_A_EW__AU0", "C_buy_hold", "full"),
}
summary["commodities"]["煤炭"] = {
    "window": "2016至2026 JM0焦煤",
    "xcorr_peak_d": l["coal"]["jm0_10y"]["module2_xcorr"]["COAL_EQ"]["ret_60d"]["peak_lag"],
    "xcorr_r": l["coal"]["jm0_10y"]["module2_xcorr"]["COAL_EQ"]["ret_60d"]["peak_corr"],
    "xcorr_r0": l["coal"]["jm0_10y"]["module2_xcorr"]["COAL_EQ"]["ret_60d"]["corr_lag0"],
    "xcorr_p": l["coal"]["jm0_10y"]["module2_xcorr"]["COAL_EQ"]["ret_60d"]["p_eff"],
    "tp": l["coal"]["jm0_10y"]["module1_turning_points"]["000983.SZ"],
    "A": get_l_strat("coal", "jm0_10y", "COAL_EQ", "A", "full"),
    "A2": get_l_strat("coal", "jm0_10y", "COAL_EQ", "A2", "full"),
    "B": get_l_strat("coal", "jm0_10y", "COAL_EQ", "B", "full"),
    "B_5y": get_l_strat("coal", "jm0_10y", "COAL_EQ", "B", "5y"),
    "B_3y": get_l_strat("coal", "jm0_10y", "COAL_EQ", "B", "3y"),
    "C": get_l_strat("coal", "jm0_10y", "COAL_EQ", "C_bh", "full"),
    "shenhua_C": get_l_strat("coal", "jm0_10y", "601088.SH", "C_bh", "full"),
}
json.dump(summary, open(BASE / "rd021_master_summary.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)

# --- 3. Chart 1: 6-panel -180 ~ +180 Cross-Correlation Curves ---
fig, axes = plt.subplots(2, 3, figsize=(14.5, 8.0), dpi=180, sharex=True)
panels = [
    ("生猪（股票大幅领先现货）", *get_l_curve("hog", "spot_10y", "HOG_EQ"), None, CRIMSON),
    ("碳酸锂（股票显著领先期货LC0）", *get_l_curve("lithium", "lc0_live", "LITHIUM_EQ_3"), ("美股ALB", *get_l_curve("lithium", "lc0_live", "ALB")[:4]), CRIMSON),
    ("铜（股期0天同步共振）", *get_m_curve("copper", "COPPER_A_EW_vs_CU0"), ("美股FCX", *get_m_curve("copper", "US_FCX_vs_HG_F")[:4]), NAVY),
    ("黄金（股期0天同步共振）", *get_m_curve("gold", "GOLD_A_EW_vs_AU0"), ("美股NEM", *get_m_curve("gold", "US_NEM_vs_GC_F")[:4]), NAVY),
    ("石油（股期0天同步共振）", *get_m_curve("oil", "OIL_A_EW_vs_SC0"), ("美股XOM", *get_m_curve("oil", "US_XOM_vs_BZ_F")[:4]), NAVY),
    ("煤炭（股期0天同步共振）", *get_l_curve("coal", "jm0_10y", "COAL_EQ"), None, NAVY),
]
for ax, (title, lags, corrs, pk_d, pk_r, r0, pv, us_info, col) in zip(axes.flat, panels):
    ax.axvspan(0, 180, color="#FEF3C7", alpha=0.35)
    ax.axvspan(-180, 0, color="#F1F5F9", alpha=0.55)
    ax.axvline(0, color=SLATE, linestyle="--", lw=1.1)
    ax.axhline(0, color=SLATE, linestyle=":", lw=0.9)
    ax.plot(lags, corrs, color=col, lw=2.3, label=f"A股等权(峰{pk_d:+d}d, r={pk_r:+.2f})")
    ax.scatter([pk_d], [pk_r], color=CRIMSON if pk_d > 10 else TEAL, s=65, zorder=6, marker="*")
    if us_info:
        unm, ulags, ucorrs, upk, ur = us_info
        ax.plot(ulags, ucorrs, color=TEAL, lw=1.5, linestyle="--", alpha=0.85, label=f"{unm}(峰{upk:+d}d, r={ur:+.2f})")
    ax.set_title(title, fontsize=10.5, fontweight="bold", pad=6)
    ax.set_ylim(-0.45, 1.0)
    ax.grid(True, linestyle="--", alpha=0.25)
    ax.legend(loc="upper left", fontsize=8.0, frameon=True, facecolor="white")
    if ax in axes[1]:
        ax.set_xlabel("滞后交易日数 k（右侧 k>0 为股票领先商品）", fontsize=8.8)
    if ax in axes[:, 0]:
        ax.set_ylabel("60日收益率交叉相关系数 r", fontsize=8.8)
fig.suptitle("六大商品股期领先滞后十年实证：生猪与碳酸锂股票显著领先，金铜油煤全部 0 天同步共振", fontsize=12.5, fontweight="bold", y=0.98)
fig.tight_layout(rect=[0, 0, 1, 0.95])
fig.savefig(BASE / "chart1_leadlag_6commodities.png")
plt.close(fig)

# --- 4. Chart 2: Strategy A vs A2 vs B vs C (CAGR% & TEI) ---
labels = ["生猪\n(10Y现货)", "碳酸锂\n(3.3Y LC0)", "铜\n(10Y HG)", "石油\n(SC0/BZ)", "黄金\n(10Y AU0)", "煤炭\n(10Y JM0)"]
cagr_A = [summary["commodities"]["生猪"]["A_eq"]["cagr_pct"], summary["commodities"]["碳酸锂"]["A"]["cagr_pct"],
          summary["commodities"]["铜"]["A"]["cagr_pct"], summary["commodities"]["石油"]["A"]["cagr_pct"],
          summary["commodities"]["黄金"]["A"]["cagr_pct"], summary["commodities"]["煤炭"]["A"]["cagr_pct"]]
cagr_A2 = [summary["commodities"]["生猪"]["A2"]["cagr_pct"], summary["commodities"]["碳酸锂"]["A2"]["cagr_pct"],
           summary["commodities"]["铜"]["A2"]["cagr_pct"], summary["commodities"]["石油"]["A2"]["cagr_pct"],
           summary["commodities"]["黄金"]["A2"]["cagr_pct"], summary["commodities"]["煤炭"]["A2"]["cagr_pct"]]
cagr_B = [summary["commodities"]["生猪"]["B"]["cagr_pct"], summary["commodities"]["碳酸锂"]["B"]["cagr_pct"],
          summary["commodities"]["铜"]["B"]["cagr_pct"], summary["commodities"]["石油"]["B"]["cagr_pct"],
          summary["commodities"]["黄金"]["B"]["cagr_pct"], summary["commodities"]["煤炭"]["B"]["cagr_pct"]]
cagr_C = [summary["commodities"]["生猪"]["C"]["cagr_pct"], summary["commodities"]["碳酸锂"]["C"]["cagr_pct"],
          summary["commodities"]["铜"]["C"]["cagr_pct"], summary["commodities"]["石油"]["C"]["cagr_pct"],
          summary["commodities"]["黄金"]["C"]["cagr_pct"], summary["commodities"]["煤炭"]["C"]["cagr_pct"]]

tei_A = [summary["commodities"]["生猪"]["A_eq"]["tei"], summary["commodities"]["碳酸锂"]["A"]["tei"],
         summary["commodities"]["铜"]["A"]["tei"], summary["commodities"]["石油"]["A"]["tei"],
         summary["commodities"]["黄金"]["A"]["tei"], summary["commodities"]["煤炭"]["A"]["tei"]]
tei_A2 = [summary["commodities"]["生猪"]["A2"]["tei"], summary["commodities"]["碳酸锂"]["A2"]["tei"],
          summary["commodities"]["铜"]["A2"]["tei"], summary["commodities"]["石油"]["A2"]["tei"],
          summary["commodities"]["黄金"]["A2"]["tei"], summary["commodities"]["煤炭"]["A2"]["tei"]]
tei_B = [summary["commodities"]["生猪"]["B"]["tei"], summary["commodities"]["碳酸锂"]["B"]["tei"],
         summary["commodities"]["铜"]["B"]["tei"], summary["commodities"]["石油"]["B"]["tei"],
         summary["commodities"]["黄金"]["B"]["tei"], summary["commodities"]["煤炭"]["B"]["tei"]]
tei_C = [summary["commodities"]["生猪"]["C"]["tei"], summary["commodities"]["碳酸锂"]["C"]["tei"],
         summary["commodities"]["铜"]["C"]["tei"], summary["commodities"]["石油"]["C"]["tei"],
         summary["commodities"]["黄金"]["C"]["tei"], summary["commodities"]["煤炭"]["C"]["tei"]]

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14.5, 5.6), dpi=180)
x, w = np.arange(len(labels)), 0.19
for ax, vals, ylabel, title, hline, hlbl in [
    (ax1, (cagr_A, cagr_A2, cagr_B, cagr_C), "年化收益率 CAGR（%）", "严格 PIT 左右侧择时 vs 买入持有年化收益对比", 0.53, "沪深300十年年化 +0.53%"),
    (ax2, (tei_A, tei_A2, tei_B, tei_C), "策略有效度指数 TEI（0至100）", "风险收益综合有效度 TEI 对比（50分为及格线）", 50.0, "TEI 及格线 50分"),
]:
    b1 = ax.bar(x - 1.5*w, vals[0], w, label="策略A 左侧低谷+股票转强", color=CRIMSON)
    b2 = ax.bar(x - 0.5*w, vals[1], w, label="策略A2 纯左侧低谷盲买", color=AMBER)
    b3 = ax.bar(x + 0.5*w, vals[2], w, label="策略B 右侧等商品主升追股", color=NAVY)
    b4 = ax.bar(x + 1.5*w, vals[3], w, label="策略C 买入并持有", color=TEAL, alpha=0.8)
    ax.axhline(hline, color=SLATE, linestyle="--", lw=1.2, label=hlbl)
    ax.axhline(0, color="#334155", lw=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_ylabel(ylabel, fontsize=9.8, fontweight="bold")
    ax.set_title(title, fontsize=11, fontweight="bold", pad=8)
    ax.grid(True, axis="y", linestyle="--", alpha=0.25)
    ax.legend(loc="upper right", fontsize=8.0, frameon=True, facecolor="white")
    for bars in (b1, b2, b3, b4):
        for bar in bars:
            h = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2, h + (0.6 if h >= 0 else -1.8), f"{h:+.1f}" if ax is ax1 else f"{h:.0f}", ha="center", va="bottom" if h >= 0 else "top", fontsize=6.8)
fig.suptitle("六大商品可交易策略实证（扣0.30%费）：锂铜油猪左侧胜出，金煤长牛右侧与持有完胜", fontsize=12.5, fontweight="bold", y=0.98)
fig.tight_layout(rect=[0, 0, 1, 0.94])
fig.savefig(BASE / "chart2_strategy_ab_vs_bh.png")
plt.close(fig)

print("AUDIT PASSED! Spot checks:", json.dumps(spot_checks, ensure_ascii=False))
for k, v in summary["commodities"].items():
    print(f"{k}: peak={v['xcorr_peak_d']:+d}d (r={v['xcorr_r']:+.3f}) | A={v['A']['cagr_pct']:+.2f}% (TEI {v['A']['tei']}) | A2={v['A2']['cagr_pct']:+.2f}% (TEI {v['A2']['tei']}) | B={v['B']['cagr_pct']:+.2f}% (TEI {v['B']['tei']}) | C={v['C']['cagr_pct']:+.2f}% (TEI {v['C']['tei']})")

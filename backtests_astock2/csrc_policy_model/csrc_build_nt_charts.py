#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Generate 2 high-DPI institutional Chinese charts for the 21-ETF Pure National Team System."""
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

plt.rcParams["font.sans-serif"] = ["STHeiti", "Heiti TC", "PingFang HK", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

BASE = "/Users/huaichuaibeimeng/claude-projects/output/csrc_policy_100factors_20261114"
BT_DIR = os.path.join(BASE, "backtest")
NT_DIR = os.path.join(BASE, "national_team")
CH_DIR = os.path.join(BASE, "charts")
os.makedirs(CH_DIR, exist_ok=True)


def make_chart5(panel: pd.DataFrame):
    sub = panel[panel["date"] >= "2023-10-01"].copy()
    sub["dt"] = pd.to_datetime(sub["date"])

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14.4, 5.9), dpi=220, gridspec_kw={"width_ratios": [1.35, 1.0]})

    flows = sub["etf_nt_weighted_flow_yi"].fillna(0.0)
    colors = ["#dc2626" if v >= 0 else "#16a34a" for v in flows]
    ax1.bar(sub["dt"], flows, width=2.2, color=colors, alpha=0.84, label="21只核心ETF纯净加权净流(亿元)")
    ax1.axhline(0, color="#475569", lw=0.8)
    ax1_r = ax1.twinx()
    ax1_r.plot(sub["dt"], sub["csi300_close"], color="#1e3a8a", lw=1.7, label="沪深300指数(右轴)")

    ax1_r.set_ylim(2900, 5650)
    ax1.set_ylim(-1450, 1180)
    annots = [
        ("2024-02-05", 354.6, "24.02救市切入二队\n加权+355亿/+399亿", (-12, 24)),
        ("2025-04-08", 873.0, "25.04关税汇金护盘\n加权单日+873亿", (-78, -28)),
        ("2026-01-28", -1221.1, "26.01高位退场降温\n加权单日净赎回1221亿(11天7621亿)", (-130, 12)),
        ("2026-11-03", 531.2, "26.11低位共振护盘\n加权单日+531亿(3天+1124亿)", (-95, 28)),
    ]
    for d_s, yv, txt, ofs in annots:
        ax1.annotate(txt, xy=(pd.Timestamp(d_s), yv), xytext=ofs, textcoords="offset points",
                     fontsize=7.8, fontweight="bold", color="#0f172a",
                     arrowprops=dict(arrowstyle="->", color="#64748b", lw=0.9),
                     bbox=dict(boxstyle="round,pad=0.22", fc="#fef9c3", ec="#ca8a04", lw=0.6))

    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%y.%m"))
    ax1.set_ylabel("纯净国家队加权净申购(+) / 净赎回(-)（亿元）", fontsize=9.8)
    ax1_r.set_ylabel("沪深300点位", fontsize=9.8, color="#1e3a8a")
    ax1.set_title("2023.10至2026.11国家队21只重仓ETF纯净净流与沪深300对照", fontsize=11.3, fontweight="bold", pad=10)
    h1a, _ = ax1.get_legend_handles_labels()
    h1b, _ = ax1_r.get_legend_handles_labels()
    ax1.legend(h1a + h1b, ["21只纯净加权净申购(红)/净赎回(绿)", "沪深300指数(右轴)"], fontsize=7.8, loc="upper left", frameon=True)
    ax1.grid(linestyle=":", alpha=0.45)

    # Right: 2024 Jan-Feb Team 1 vs Team 2 Structural Pivot
    s2 = panel[(panel["date"] >= "2024-01-18") & (panel["date"] <= "2024-02-23")].copy()
    x = np.arange(len(s2))
    n300 = (1.0 + s2["csi300_cc_ret"]).cumprod() * 100 - 100
    n1000 = (1.0 + s2["csi1000_cc_ret"]).cumprod() * 100 - 100
    nmic = (1.0 + s2["micro30_cc_ret"]).cumprod() * 100 - 100
    ax2.bar(x - 0.18, s2["etf_t1_flow_yi"].fillna(0) / 10.0, width=0.36, color="#93c5fd", alpha=0.85, label="一队300/50净流(十亿)")
    ax2.bar(x + 0.18, s2["etf_t2_flow_yi"].fillna(0) / 10.0, width=0.36, color="#f97316", alpha=0.92, label="二队1000/500等净流(十亿)")
    ax2_r = ax2.twinx()
    ax2_r.set_ylim(-35, 13)
    ax2_r.plot(x, n300, color="#1d4ed8", lw=2.0, label="沪深300累计(%)")
    ax2_r.plot(x, n1000, color="#dc2626", lw=2.0, label="中证1000累计(%)")
    ax2_r.plot(x, nmic, color="#7e22ce", lw=1.7, ls="--", label="微盘30%累计(%)")

    piv_i = list(s2["date"]).index("2024-02-05")
    ax2.axvline(piv_i, color="#0f172a", ls="--", lw=1.2)
    ax2_r.text(piv_i + 0.35, -18.5, "2月5日拐点：\n切入二队1000/500ETF\n一二队共振反转", fontsize=7.8, fontweight="bold",
               bbox=dict(boxstyle="round,pad=0.25", fc="#fef08a", ec="#ca8a04", lw=0.7))

    xt = [0, 5, 10, piv_i, len(s2) - 1]
    ax2.set_xticks(xt)
    ax2.set_xticklabels([s2["date"].iloc[i][5:].replace("-", ".") for i in xt], fontsize=8.8)
    ax2.set_ylabel("梯队单日净申购（十亿元）", fontsize=9.8)
    ax2_r.set_ylabel("累计涨跌幅（%）", fontsize=9.8)
    ax2.set_title("2024年1至2月实证：一队独撑(抽血小盘) vs 一二队共振反转", fontsize=11.3, fontweight="bold", pad=10)
    h1, l1 = ax2.get_legend_handles_labels()
    h2, l2 = ax2_r.get_legend_handles_labels()
    ax2.legend(h1 + h2, l1 + l2, fontsize=7.4, loc="lower left", ncol=2, frameon=True)
    ax2.grid(linestyle=":", alpha=0.45)

    fig.tight_layout()
    out_p = os.path.join(CH_DIR, "chart5_national_team_etf_flows_and_2024_pivot.png")
    fig.savefig(out_p)
    plt.close(fig)
    print("Saved", out_p)


def make_chart6():
    nt = pd.read_csv(os.path.join(NT_DIR, "nt_12_pure_ledger.csv")).set_index("factor_id")
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.8, 5.6), dpi=220)

    # Left: 20d Return vs Single-Slot Rotation across Pure NT Entry & Exit Signals
    left_ids = [
        ("F154", "纯净加权退场\n(<=-80亿/日)"),
        ("F155", "华泰510300退场\n(<=-30亿/日)"),
        ("F147", "510300单票进场\n(全样本盲追)"),
        ("F145", "21池原始买盘\n(>=+100亿/日)"),
        ("F146", "21池纯度加权\n(>=+90亿/日)"),
        ("F149", "盘中爆量2.2x+下影\n(盘面真护盘信号)"),
        ("F148", "深跌8%+加权买盘\n(OOS近3年+5.42%)"),
    ]
    lbls1 = [x[1] for x in left_ids]
    means1 = [float(nt.loc[i, "main_mean_pct"]) for i, _ in left_ids]
    slots1 = [float(nt.loc[i, "slot_mean_pct"]) for i, _ in left_ids]
    x1, w = np.arange(len(lbls1)), 0.35
    ax1.bar(x1 - w / 2, means1, width=w, color=["#16a34a" if v < 0 else "#2563eb" for v in means1], label="全部去重事件20日均值(%)")
    ax1.bar(x1 + w / 2, slots1, width=w, color="#f59e0b", alpha=0.9, label="单仓不重叠轮动20日均值(%)")
    ax1.axhline(0, color="#334155", lw=1.0)
    ax1.set_xticks(x1)
    ax1.set_xticklabels(lbls1, rotation=16, ha="right", fontsize=8.3)
    ax1.set_ylim(-3.2, 4.2)
    ax1.set_ylabel("T+1开盘买入20日收益率（%）", fontsize=9.8)
    ax1.set_title("左图：纯度加权 vs 华泰510300单票进退场20日收益及单仓防伪", fontsize=11.0, fontweight="bold", pad=10)
    for idx, (mv, sv) in enumerate(zip(means1, slots1)):
        ax1.text(idx - w / 2 - 0.03, mv + (0.12 if mv >= 0 else -0.32), f"{mv:+.2f}%", ha="center", fontsize=7.4, fontweight="bold")
        ax1.text(idx + w / 2 + 0.03, sv + (0.12 if sv >= 0 else -0.32), f"{sv:+.2f}%", ha="center", fontsize=7.3)
    ax1.legend(fontsize=8.1, loc="upper left")
    ax1.grid(axis="y", linestyle=":", alpha=0.45)

    # Right: OOS Win Rate & Style Scissor Spread (Team 1 vs Team 2 Resonance vs Exits)
    right_ids = [
        ("F151", "只护一队抽血小盘\n(5日剪刀差)"),
        ("F154", "纯净加权退场\n(20日1000减300)"),
        ("F155", "华泰510300退场\n(20日1000减300)"),
        ("F146", "21池加权进场\n(20日1000减300)"),
        ("F152", "一二队全面共振\n(20日1000减300)"),
        ("F152_60", "一二队全面共振\n(60日1000减300)"),
    ]
    lbls2 = [x[1] for x in right_ids]
    vals2 = [
        float(nt.loc["F151", "sp1000_5d_pct"]),
        float(nt.loc["F154", "sp1000_20d_pct"]),
        float(nt.loc["F155", "sp1000_20d_pct"]),
        float(nt.loc["F146", "sp1000_20d_pct"]),
        float(nt.loc["F152", "sp1000_20d_pct"]),
        float(nt.loc["F152", "spmicro_20d_pct"]),
    ]
    lbls2[-1] = "一二队全面共振\n(20日微盘减300)"
    x2 = np.arange(len(lbls2))
    ax2.bar(x2, vals2, width=0.52, color=["#16a34a" if v < 0 else "#dc2626" for v in vals2])
    ax2.axhline(0, color="#334155", lw=1.0)
    ax2.set_xticks(x2)
    ax2.set_xticklabels(lbls2, rotation=16, ha="right", fontsize=8.4)
    ax2.set_ylim(-3.2, 7.2)
    ax2.set_ylabel("中证1000 / 微盘相对沪深300剪刀差（%）", fontsize=9.8)
    ax2.set_title("右图：国家队进退场对大小盘风格剪刀差的真实定价效果", fontsize=11.0, fontweight="bold", pad=10)
    for idx, v in enumerate(vals2):
        ax2.text(idx, v + (0.18 if v >= 0 else -0.45), f"{v:+.2f}%", ha="center", fontsize=8.3, fontweight="bold")
    ax2.grid(axis="y", linestyle=":", alpha=0.45)

    fig.tight_layout()
    out_p = os.path.join(CH_DIR, "chart6_national_team_pure_backtest.png")
    fig.savefig(out_p)
    plt.close(fig)
    print("Saved", out_p)


if __name__ == "__main__":
    pnl = pd.read_parquet(os.path.join(BT_DIR, "daily_market_panel.parquet"))
    make_chart5(pnl)
    make_chart6()

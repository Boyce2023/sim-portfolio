#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Generate high-resolution dual audit chart for National Team Five-Mantra 10Y Backtest."""
import json
import warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

plt.rcParams["font.sans-serif"] = ["PingFang SC", "Heiti TC", "STHeiti", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/nt_mantra_backtest_20261120"


def main():
    res = json.load(open(f"{OUT_DIR}/nt_mantra_backtest_result.json", encoding="utf-8"))
    c10 = pd.read_parquet(f"{OUT_DIR}/data_cache/sim_curves_10y.parquet")
    c10["dt"] = pd.to_datetime(c10["date"])
    ev10 = res["events_10y"]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(17.5, 7.6), gridspec_kw={"width_ratios": [1.0, 1.18]})
    fig.patch.set_facecolor("#FFFFFF")

    # ---------------- LEFT PANEL: Five-Mantra Forward Return & Win Rate Comparison ----------------
    cats = [
        ("①脉冲不放量\n(吃瓜 <1.2x, n=231)", ev10["M1_weak"]),
        ("②脉冲温和放量\n(底仓 1.2至2x, n=110)", ev10["M2_weak"]),
        ("③弱势宽基爆量\n(>=2.0x, n=44)", ev10["M3_weak_20"]),
        ("③弱势脉冲+爆量\n(双信号, n=23)", ev10["M3_weak_20_pulse"]),
        ("④期现双爆(剔交割)\n(>=1.8x&1.5x, n=15)", ev10["M4_weak_18_excl"]),
        ("⑤巨阳(剔924三连阳)\n(>=+2.5%, n=28)", ev10["M5_25_ex924"]),
        ("⑤巨阳(大哥仍在扫货)\n(净申购>=50亿, n=10)", ev10["M5_25_flow_ge50"]),
    ]

    labels = [c[0] for c in cats]
    y_pos = np.arange(len(cats))
    h_keys = ["T+1", "T+5", "T+10", "T+20"]
    colors = ["#94A3B8", "#3B82F6", "#F59E0B", "#10B981"]
    bar_h = 0.18

    for idx_h, hk in enumerate(h_keys):
        vals = [c[1]["horizons"]["c300_tail"][hk]["mean_pct"] for c in cats]
        wins = [c[1]["horizons"]["c300_tail"][hk]["win_rate"] for c in cats]
        offsets = (idx_h - 1.5) * bar_h
        bars = ax1.barh(y_pos + offsets, vals, height=bar_h * 0.92, color=colors[idx_h], alpha=0.92, label=f"{hk} 均值")
        if hk == "T+20":
            for bar, v, w in zip(bars, vals, wins):
                x_txt = v + 0.10 if v >= 0 else v - 0.10
                ha = "left" if v >= 0 else "right"
                ax1.text(x_txt, bar.get_y() + bar.get_height() / 2, f"{v:+.2f}% ({w:.0f}%胜)",
                         va="center", ha=ha, fontsize=8.5, fontweight="bold", color="#0F172A")
        elif hk == "T+5":
            for bar, v in zip(bars, vals):
                if abs(v) >= 0.8:
                    x_txt = v + 0.08 if v >= 0 else v - 0.08
                    ha = "left" if v >= 0 else "right"
                    ax1.text(x_txt, bar.get_y() + bar.get_height() / 2, f"{v:+.2f}%",
                             va="center", ha=ha, fontsize=7.8, color="#1E3A8A")

    ax1.axvline(0.0, color="#334155", linewidth=1.1)
    ax1.set_yticks(y_pos)
    ax1.set_yticklabels(labels, fontsize=9.2, fontweight="bold", color="#1E293B")
    ax1.invert_yaxis()
    ax1.set_xlim(-2.4, 7.0)
    ax1.set_xlabel("沪深300 信号日收盘买入后续收益 (%)", fontsize=10, fontweight="bold", color="#1E293B")
    ax1.set_title("五句口诀十年事件研究对比（2017至2026，尾盘买入基准）", fontsize=11.8, fontweight="bold", pad=12, color="#0F172A")
    ax1.grid(axis="x", linestyle="--", alpha=0.35)
    ax1.spines["top"].set_visible(False)
    ax1.spines["right"].set_visible(False)
    ax1.legend(loc="lower right", frameon=True, facecolor="#F8FAFC", edgecolor="#CBD5E1", fontsize=8.8)

    # ---------------- RIGHT PANEL: 10-Year NAV Curves vs Benchmarks ----------------
    c10["nav_300"] = (1.0 + c10["c300_ret"].fillna(0.0)).cumprod()
    w_s1 = float(c10["S1_10Y_原教旨五句合体_尾盘_w"].mean())
    c10["nav_same_exp"] = (1.0 + w_s1 * c10["c300_ret"].fillna(0.0)).cumprod()
    c10["nav_s1"] = (1.0 + c10["S1_10Y_原教旨五句合体_尾盘_ret"]).cumprod()
    c10["nav_s2"] = (1.0 + c10["S2_10Y_改良巨阳减半留底_尾盘_ret"]).cumprod()
    c10["nav_s5"] = (1.0 + c10["S5_10Y_去伪存真_纯③爆量30%_尾盘_ret"]).cumprod()
    c10["nav_s7"] = (1.0 + c10["S7_10Y_纯③爆量100%单仓_尾盘_ret"]).cumprod()
    c10["nav_s7b"] = (1.0 + c10["S7b_10Y_纯③+正净申购100%单仓_开盘_ret"]).cumprod()

    ax2.plot(c10["dt"], c10["nav_s7"], color="#059669", linewidth=2.3, label=f"精华版 纯③爆量(100%单仓 尾盘): {c10['nav_s7'].iloc[-1]:.3f} (TEI 62.1)")
    ax2.plot(c10["dt"], c10["nav_s7b"], color="#0284C7", linewidth=1.8, linestyle="-.", label=f"精华版 纯③+正净申购(100% 开盘): {c10['nav_s7b'].iloc[-1]:.3f} (TEI 60.4)")
    ax2.plot(c10["dt"], c10["nav_s5"], color="#2563EB", linewidth=2.0, label=f"精华版 纯③爆量(30%仓 尾盘): {c10['nav_s5'].iloc[-1]:.3f} (TEI 60.8)")
    ax2.plot(c10["dt"], c10["nav_300"], color="#94A3B8", linewidth=1.4, linestyle="--", alpha=0.85, label=f"沪深300满仓(参考): {c10['nav_300'].iloc[-1]:.3f} (MDD -45.6%)")
    ax2.plot(c10["dt"], c10["nav_same_exp"], color="#64748B", linewidth=1.3, linestyle=":", label=f"等仓位基准(8.4%被动): {c10['nav_same_exp'].iloc[-1]:.3f}")
    ax2.plot(c10["dt"], c10["nav_s2"], color="#D97706", linewidth=1.6, label=f"改良五句(巨阳减半 S2): {c10['nav_s2'].iloc[-1]:.3f} (TEI 45.7)")
    ax2.plot(c10["dt"], c10["nav_s1"], color="#DC2626", linewidth=2.0, label=f"原教旨五句(一刀清 S1): {c10['nav_s1'].iloc[-1]:.3f} (TEI 43.4)")

    ax2.axhline(1.0, color="#475569", linewidth=0.8, alpha=0.5)

    # Annotate key historical turning points cleanly
    ann_pts = [
        ("2020-02-03", "nav_s7", "2020.02 疫情坑", (12, 18)),
        ("2024-02-05", "nav_s7", "2024.02 救市底", (-85, 22)),
        ("2024-09-24", "nav_s7", "924反转爆发", (-88, 12)),
        ("2025-04-08", "nav_s7", "2025.04 关税救市", (-105, 44)),
        ("2024-09-24", "nav_s1", "S1在924被一刀清踏空", (-45, -34)),
    ]
    for d_str, col, txt, xyoff in ann_pts:
        row = c10[c10["date"] >= d_str].iloc[0]
        ax2.scatter([row["dt"]], [row[col]], color="#0F172A", s=24, zorder=5)
        ax2.annotate(txt, xy=(row["dt"], row[col]), xytext=xyoff, textcoords="offset points",
                     fontsize=8.3, fontweight="bold", color="#1E293B",
                     arrowprops=dict(arrowstyle="->", color="#475569", lw=0.9))

    ax2.xaxis.set_major_locator(mdates.YearLocator(2))
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax2.set_ylim(0.55, 2.26)
    ax2.set_ylabel("净值（初始=1.00，含双边0.30%换手成本）", fontsize=10, fontweight="bold", color="#1E293B")
    ax2.set_title("十年组合仿真净值（2017至2026）：原教旨五句 vs 去伪存真纯爆量", fontsize=11.8, fontweight="bold", pad=12, color="#0F172A")
    ax2.grid(True, linestyle="--", alpha=0.32)
    ax2.spines["top"].set_visible(False)
    ax2.spines["right"].set_visible(False)
    ax2.legend(loc="upper left", frameon=True, facecolor="#F8FAFC", edgecolor="#CBD5E1", fontsize=8.3)

    fig.suptitle("大哥护盘五句口诀十年实证回测审计图（2017-01-17 至 2026-11-19）", fontsize=14, fontweight="bold", y=0.985, color="#0F172A")
    plt.tight_layout(rect=[0, 0.01, 1, 0.955])
    out_png = f"{OUT_DIR}/chart_nt_mantra_audit.png"
    fig.savefig(out_png, dpi=220)
    plt.close(fig)
    print("Chart saved:", out_png)


if __name__ == "__main__":
    main()

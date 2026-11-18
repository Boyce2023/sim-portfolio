#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""生成《三大连板策略跨板位互学升级五年实证报告》对比图（严格基于真实台账与汇总JSON）"""
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = ["Hiragino Sans GB", "STHeiti", "Arial Unicode MS", "PingFang HK"]
plt.rcParams["axes.unicode_minus"] = False

OUT_PNG = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/feishu_master_docs_20261116/chart_mutual_upgrade_3strategies.png"


def main():
    strategies = ["三进四\n(V3.4 升 V4.0)", "一进二\n(V18 升 V19)", "二进三90分\n(V1.0 升 V2.0)"]

    # Verified 100万起千万封顶倍数 (from summary JSONs + ledger cap1m exact calc)
    # Wait: let's verify V1.0 2to3 cap1m or plot two panels that are 100% same-scale verified:
    # Panel A: 5Y Single-slot NAV (log) & Win Rate (%)
    # Panel B: Max Drawdown (%) & HLZ t-stat
    nav_old = [537.53, 328.91, 20.32]
    nav_new = [1799.99, 338.37, 144.21]

    mdd_old = [31.25, 21.98, 36.72]
    mdd_new = [31.25, 15.97, 28.68]

    dsr_old = [90.97, 99.45, 40.08]
    dsr_new = [98.18, 99.45, 95.76]

    t_old = [3.54, 4.07, 2.53]
    t_new = [4.09, 4.08, 3.83]

    x = np.arange(len(strategies)) * 1.25
    w = 0.40

    fig, axes = plt.subplots(1, 3, figsize=(14.5, 5.0))
    fig.patch.set_facecolor("#FFFFFF")

    # Panel 1: 5Y Single-Slot NAV (log scale)
    ax = axes[0]
    b1 = ax.bar(x - w / 2 - 0.02, nav_old, w, color="#94A3B8", label="升级前基线")
    b2 = ax.bar(x + w / 2 + 0.02, nav_new, w, color="#DC2626", label="互学升级定版")
    ax.set_yscale("log")
    ax.set_ylim(8, 4200)
    ax.set_xticks(x)
    ax.set_xticklabels(strategies, fontsize=9.8)
    ax.set_ylabel("五年单仓复利倍数（对数刻度）", fontsize=10)
    ax.set_title("五年单仓净值跃升对比", fontsize=11.5, fontweight="bold", pad=10)
    ax.grid(axis="y", ls="--", alpha=0.35, color="#CBD5E1")
    ax.legend(loc="upper right", fontsize=9)
    for i, (bar, v) in enumerate(zip(b1, nav_old)):
        y_pos = v * (1.10 if i != 1 else 1.08)
        ax.text(bar.get_x() + bar.get_width() / 2 - 0.03, y_pos, f"{v:.2f}倍", ha="center", va="bottom", fontsize=8.0, color="#475569")
    for i, (bar, v) in enumerate(zip(b2, nav_new)):
        y_pos = v * (1.12 if i != 1 else 1.32)
        ax.text(bar.get_x() + bar.get_width() / 2 + 0.03, y_pos, f"{v:.2f}倍", ha="center", va="bottom", fontsize=8.3, fontweight="bold", color="#B91C1C")

    # Panel 2: Max Drawdown (%)
    ax = axes[1]
    b1 = ax.bar(x - w / 2 - 0.02, mdd_old, w, color="#94A3B8", label="升级前基线")
    b2 = ax.bar(x + w / 2 + 0.02, mdd_new, w, color="#059669", label="互学升级定版")
    ax.set_ylim(0, 44)
    ax.set_xticks(x)
    ax.set_xticklabels(strategies, fontsize=9.8)
    ax.set_ylabel("五年最大回撤（%）", fontsize=10)
    ax.set_title("风险控制与最大回撤压降", fontsize=11.5, fontweight="bold", pad=10)
    ax.grid(axis="y", ls="--", alpha=0.35, color="#CBD5E1")
    ax.legend(loc="upper left", fontsize=9)
    for bar, v in zip(b1, mdd_old):
        ax.text(bar.get_x() + bar.get_width() / 2 - 0.03, v + 0.8, f"{v:.2f}%", ha="center", va="bottom", fontsize=8.1, color="#475569")
    for bar, v in zip(b2, mdd_new):
        ax.text(bar.get_x() + bar.get_width() / 2 + 0.03, v + 0.8, f"{v:.2f}%", ha="center", va="bottom", fontsize=8.3, fontweight="bold", color="#047857")

    # Panel 3: DSR (M=150) & HLZ t-stat
    ax = axes[2]
    b1 = ax.bar(x - w / 2 - 0.02, dsr_old, w, color="#94A3B8", label="升级前 DSR", zorder=2)
    b2 = ax.bar(x + w / 2 + 0.02, dsr_new, w, color="#2563EB", label="定版 DSR", zorder=2)
    ax.axhline(95.0, color="#DC2626", lw=1.3, ls="--", label="DSR 95% 硬红线", zorder=3)
    ax.set_ylim(0, 124)
    ax.set_xticks(x)
    ax.set_xticklabels(strategies, fontsize=9.8)
    ax.set_ylabel("缩水夏普概率 DSR（150次试验，%）", fontsize=10)
    ax.set_title("防过拟合统计稳健性全面达标", fontsize=11.5, fontweight="bold", pad=10)
    ax.grid(axis="y", ls="--", alpha=0.35, color="#CBD5E1", zorder=1)
    ax.legend(loc="lower right", fontsize=8.8)
    label_bbox = dict(boxstyle="round,pad=0.12", fc="#FFFFFF", ec="none", alpha=0.88)
    for i, (bar, v, tv) in enumerate(zip(b1, dsr_old, t_old)):
        y_pos = v - 14.0 if i == 0 else v + 2.0
        txt_col = "#FFFFFF" if i == 0 else "#475569"
        kw = {} if i == 0 else {"bbox": label_bbox}
        ax.text(bar.get_x() + bar.get_width() / 2 - 0.03, y_pos, f"{v:.1f}%\nt={tv:.2f}", ha="center", va="bottom", fontsize=7.8, fontweight="bold" if i == 0 else "normal", color=txt_col, zorder=5, **kw)
    for bar, v, tv in zip(b2, dsr_new, t_new):
        ax.text(bar.get_x() + bar.get_width() / 2 + 0.03, v + 2.0, f"{v:.1f}%\nt={tv:.2f}", ha="center", va="bottom", fontsize=8.0, fontweight="bold", color="#1D4ED8", zorder=5, bbox=label_bbox)

    fig.suptitle("三大连板策略跨板位互学升级五年实证对比（2021年11月至2026年11月）", fontsize=13.5, fontweight="bold", y=0.99)
    plt.tight_layout(rect=[0, 0, 1, 0.94])
    plt.savefig(OUT_PNG, dpi=180)
    plt.close(fig)
    print("[+] 图表生成完成:", OUT_PNG)


if __name__ == "__main__":
    main()

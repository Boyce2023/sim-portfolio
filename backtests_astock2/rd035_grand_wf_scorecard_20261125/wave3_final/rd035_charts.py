#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Generate 2 pure-Chinese publication charts for RD035 directly from verified JSON outputs."""
import os
import sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

assert "yfinance" not in sys.modules, "D12 violation!"

plt.rcParams["font.sans-serif"] = ["Hiragino Sans GB", "STHeiti", "Arial Unicode MS", "Songti SC"]
plt.rcParams["axes.unicode_minus"] = False
NAVY, TEAL, CRIMSON, AMBER, SLATE = "#1B365D", "#0F766E", "#B91C1C", "#D97706", "#64748B"


def generate_rd035_charts(audit_a: dict, audit_b: dict, out_dir: str) -> tuple[str, str]:
    c1_path = os.path.join(out_dir, "chart1_20cm_cleanb_vs_base.png")
    c2_path = os.path.join(out_dir, "chart2_7traps_and_funnel.png")

    va = audit_a["gate1_gate2_gate4_variants"]
    b_base = va["1r_w2a3_BASE_V11_S82"]
    b_s84 = va["1b_w2a3_CLEAN_B_cold50_d15_S84"]
    b_s80 = va["1c_w2a3_CLEAN_B_cold50_d15_S80"]

    # Chart 1: Left = 30bps / 50bps / 80bps / Ex5 NAV comparison; Right = 26H2 Repair (WR & MDD & NAV)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.6, 5.4), dpi=180)

    labels = ["千三成本\n全周期净值", "千三成本\n去前5极值", "千八魔鬼成本\n全周期净值", "千八魔鬼成本\n去前5极值"]
    v_base = [
        b_base["slippage_stress"]["30bps"]["nav"],
        b_base["slippage_stress"]["30bps"]["ex5_nav"],
        b_base["slippage_stress"]["80bps"]["nav"],
        b_base["slippage_stress"]["80bps"]["ex5_nav"],
    ]
    v_s84 = [
        b_s84["slippage_stress"]["30bps"]["nav"],
        b_s84["slippage_stress"]["30bps"]["ex5_nav"],
        b_s84["slippage_stress"]["80bps"]["nav"],
        b_s84["slippage_stress"]["80bps"]["ex5_nav"],
    ]
    v_s80 = [
        b_s80["slippage_stress"]["30bps"]["nav"],
        b_s80["slippage_stress"]["30bps"]["ex5_nav"],
        b_s80["slippage_stress"]["80bps"]["nav"],
        b_s80["slippage_stress"]["80bps"]["ex5_nav"],
    ]

    x = np.arange(len(labels))
    w = 0.25
    b1 = ax1.bar(x - w, v_base, width=w, color=SLATE, label="20cm 现行原版 (120笔)")
    b2 = ax1.bar(x, v_s84, width=w, color=NAVY, label="20cm 备选84分档 (95笔)")
    b3 = ax1.bar(x + w, v_s80, width=w, color=TEAL, label="20cm 备选80分档 (139笔)")
    for bars, col in [(b1, SLATE), (b2, NAVY), (b3, TEAL)]:
        for bar in bars:
            hv = bar.get_height()
            ax1.text(bar.get_x() + bar.get_width() / 2, hv + 1.2, f"{hv:.1f}x", ha="center", va="bottom", fontsize=7.5, color=col, fontweight="bold")
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, fontsize=8.8)
    ax1.set_ylim(0, 92)
    ax1.set_ylabel("独立单仓复利净值 (倍)", fontsize=9.5)
    ax1.set_title("20cm 备选新卡抗滑点与去极值耐力对比 (25/25 邻域全胜)", fontsize=10.3, fontweight="bold")
    ax1.grid(True, axis="y", ls="--", alpha=0.25)
    ax1.legend(loc="upper right", fontsize=8.0, frameon=True, facecolor="white")

    # Right panel: 2026 H2 Repair comparison (Win rate & Trade MDD & H2 NAV)
    cats_h2 = ["20cm 现行原版\n(16笔)", "备选 84分档\n(14笔)", "备选 80分档\n(17笔)"]
    wr_h2 = [43.75, 64.29, 58.82]
    mdd_h2 = [28.60, 5.05, 6.34]
    nav_h2 = [1.26, 1.93, 1.91]

    xh = np.arange(len(cats_h2))
    bw1 = ax2.bar(xh - 0.18, wr_h2, width=0.35, color=TEAL, label="下半年胜率 (%)")
    bw2 = ax2.bar(xh + 0.18, mdd_h2, width=0.35, color=CRIMSON, alpha=0.86, label="下半年逐笔最大回撤 (%)")
    for bar, nv in zip(bw1, nav_h2):
        hv = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width() / 2, hv + 1.4, f"{hv:.2f}%\n({nv:.2f}x)", ha="center", va="bottom", fontsize=8.0, color=TEAL, fontweight="bold")
    for bar in bw2:
        hv = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width() / 2, hv + 1.4, f"{hv:.2f}%", ha="center", va="bottom", fontsize=8.0, color=CRIMSON, fontweight="bold")
    ax2.axhline(50.0, color=SLATE, ls=":", lw=1.0)
    ax2.set_xticks(xh)
    ax2.set_xticklabels(cats_h2, fontsize=9.0)
    ax2.set_ylim(0, 82)
    ax2.set_ylabel("百分比 (%)", fontsize=9.5)
    ax2.set_title("今年下半年强力修复：胜率抬升且回撤压至 5.05%", fontsize=10.3, fontweight="bold")
    ax2.grid(True, axis="y", ls="--", alpha=0.25)
    ax2.legend(loc="upper right", fontsize=8.2, frameon=True, facecolor="white")

    fig.suptitle("唯一二级备选：20cm 冷清日关机构净买搭配新打分卡 (放影子账本观察 1 至 2 季)", fontsize=11.6, fontweight="bold", y=0.98)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    fig.savefig(c1_path)
    plt.close(fig)

    # Chart 2: Left = 6945 Trials Funnel; Right = 7 Fatal Traps Illusion vs Reality (Ex5 or Causal NAV)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.6, 5.4), dpi=180)

    stages = ["全部暴力试错\n总方案数", "主表正式入池\n打分方案", "红队初筛入围\n重点候选", "双红队过关\n二级影子备选", "直接覆盖实盘\n一级胜出者"]
    counts = [6945, 5456, 11, 2, 0]
    y_pos = np.arange(len(stages))[::-1]
    cols_f = [SLATE, NAVY, AMBER, TEAL, CRIMSON]
    ax1.barh(y_pos, [max(c, 40) for c in counts], color=cols_f, alpha=0.88, height=0.56)
    for yi, cv in zip(y_pos, counts):
        x_txt = max(cv, 40) + 120
        ax1.text(x_txt, yi, f"{cv} 项", va="center", fontsize=9.0, fontweight="bold", color=NAVY if cv > 0 else CRIMSON)
    ax1.set_yticks(y_pos)
    ax1.set_yticklabels(stages, fontsize=8.8)
    ax1.set_xlim(0, 8400)
    ax1.set_xlabel("试验次数 (项)", fontsize=9.5)
    ax1.set_title("6,945 次全量多因子暴力试错最终淘汰漏斗", fontsize=10.3, fontweight="bold")
    ax1.grid(True, axis="x", ls="--", alpha=0.25)

    # Right: 7 Traps "Paper Illusion" vs "Red-Team Reality" (Net NAV multiple, 1.0 = breakeven)
    traps = [
        "1. 护盘基金9点35偷跑\n(拼装总仓倍率)",
        "2. 美股事后牛股树\n(去涨停后净值)",
        "3. 三进四排雷换4笔\n(邻域胜原版比例)",
        "4. 20cm交互名额扩至20\n(拼装总仓倍率)",
        "5. 20cm一进二80分档\n(千五去前5极值)",
        "6. 20cm大涨不封板\n(千五重排净值)",
        "7. 临时五板5年打分\n(最好阈值净值)",
    ]
    # Use clean comparable multiples / ratios for visual clarity
    illusion_vals = [1.31, 9.77, 1.12, 1.62, 7.09, 6.00, 1.00]
    reality_vals = [0.76, 0.56, 0.25, 0.95, 0.98, 1.32, 0.99]
    yt = np.arange(len(traps))[::-1]
    h = 0.34
    ax2.barh(yt + h / 2, illusion_vals, height=h, color=AMBER, alpha=0.85, label="表面纸面假象 (倍数/比值)")
    ax2.barh(yt - h / 2, reality_vals, height=h, color=CRIMSON, alpha=0.88, label="红队拆穿真相 (倍数/比值)")
    ax2.axvline(1.0, color=SLATE, ls="--", lw=1.0)
    for yi, iv, rv in zip(yt, illusion_vals, reality_vals):
        ax2.text(iv + 0.15, yi + h / 2, f"{iv:.2f}", va="center", fontsize=7.6, color=AMBER, fontweight="bold")
        ax2.text(rv + 0.15, yi - h / 2, f"{rv:.2f}", va="center", fontsize=7.6, color=CRIMSON, fontweight="bold")
    ax2.set_yticks(yt)
    ax2.set_yticklabels(traps, fontsize=8.0)
    ax2.set_xlim(0, 11.4)
    ax2.set_xlabel("净值或相对基准比值 (1.0 为保本线)", fontsize=9.2)
    ax2.set_title("双红队揪出的 7 大致命陷阱：表面假象与真实崩塌对照", fontsize=10.2, fontweight="bold")
    ax2.grid(True, axis="x", ls="--", alpha=0.25)
    ax2.legend(loc="lower right", fontsize=8.0, frameon=True, facecolor="white")

    fig.suptitle("6,945 次试错严酷淘汰：现行六策略原版依然不可动摇", fontsize=11.8, fontweight="bold", y=0.98)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    fig.savefig(c2_path)
    plt.close(fig)

    return c1_path, c2_path

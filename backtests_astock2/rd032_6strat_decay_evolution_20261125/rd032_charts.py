#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Generate 2 pure-Chinese publication charts for RD032 directly from JSON outputs."""
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


def generate_rd032_charts(audit: dict, out_dir: str) -> tuple[str, str]:
    c1_path = os.path.join(out_dir, "chart1_6strat_decay_overview.png")
    c2_path = os.path.join(out_dir, "chart2_20cm_h2_and_evo_funnel.png")

    strats = ["1to2", "2to3", "3to4", "high", "pry", "20cm"]
    lbls_cn = ["一进二", "二进三", "三进四", "高标首阴", "超跌撬板", "20cm深水"]
    sh = audit["module1_decay"]["strategy_health"]
    facs = audit["module1_decay"]["factor_audit"]

    # Chart 1: Left = 5Y vs 1Y vs 26H2 Win Rate; Right = Factor Light Counts (Green/Yellow/Red)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.6, 5.4), dpi=180)
    x = np.arange(len(strats))
    w = 0.25
    wr5 = [sh[s]["slot_5y"]["wr_pct"] for s in strats]
    wr1 = [sh[s]["slot_1y"]["wr_pct"] for s in strats]
    wrh = [sh[s]["slot_h2"]["wr_pct"] for s in strats]
    b1 = ax1.bar(x - w, wr5, width=w, color=NAVY, label="全五年胜率 (%)")
    b2 = ax1.bar(x, wr1, width=w, color=TEAL, label="近一年胜率 (%)")
    b3 = ax1.bar(x + w, wrh, width=w, color=CRIMSON, alpha=0.88, label="下半年胜率 (%)")
    for bars, col in [(b1, NAVY), (b2, TEAL), (b3, CRIMSON)]:
        for bar in bars:
            hv = bar.get_height()
            ax1.text(bar.get_x() + bar.get_width() / 2, hv + 1.2, f"{hv:.0f}%", ha="center", va="bottom", fontsize=7.5, color=col, fontweight="bold")
    ax1.axhline(50.0, color=SLATE, ls=":", lw=1.0)
    ax1.set_xticks(x)
    ax1.set_xticklabels(lbls_cn, fontsize=9.2)
    ax1.set_ylim(0, 112)
    ax1.set_ylabel("单仓交易胜率 (%)", fontsize=9.5)
    ax1.set_title("六策略五年、近一年与下半年胜率对照（全线健康绿灯）", fontsize=10.5, fontweight="bold")
    ax1.grid(True, axis="y", ls="--", alpha=0.25)
    ax1.legend(loc="upper left", fontsize=8.2, frameon=True, facecolor="white")

    g_cnt = [sum(1 for f in facs if f["strategy"] == s and f["light"] == "GREEN") for s in strats]
    y_cnt = [sum(1 for f in facs if f["strategy"] == s and f["light"].startswith("YELLOW")) for s in strats]
    r_cnt = [sum(1 for f in facs if f["strategy"] == s and f["light"] == "RED") for s in strats]
    y_pos = np.arange(len(strats))[::-1]
    ax2.barh(y_pos, g_cnt, color=TEAL, height=0.58, label="绿灯(坚挺有效)")
    ax2.barh(y_pos, y_cnt, left=g_cnt, color=AMBER, height=0.58, label="黄灯(轻微走弱/小样本)")
    left_r = [a + b for a, b in zip(g_cnt, y_cnt)]
    ax2.barh(y_pos, r_cnt, left=left_r, color=CRIMSON, height=0.58, label="红灯(近期翻号钝化)")
    for yi, gc, yc, rc in zip(y_pos, g_cnt, y_cnt, r_cnt):
        ax2.text(gc + yc + rc + 0.4, yi, f"绿{gc} / 黄{yc} / 红{rc}", va="center", fontsize=8.3, fontweight="bold", color=NAVY)
    ax2.set_yticks(y_pos)
    ax2.set_yticklabels(lbls_cn, fontsize=9.2)
    ax2.set_xlim(0, 29)
    ax2.set_xlabel("现役打分项数量 (个)", fontsize=9.5)
    ax2.set_title("全部 102 项现役打分因子近一年健康体检红绿灯分布", fontsize=10.5, fontweight="bold")
    ax2.grid(True, axis="x", ls="--", alpha=0.25)
    ax2.legend(loc="lower right", fontsize=8.2, frameon=True, facecolor="white")

    fig.suptitle("六套实盘策略季度退化体检：整体稳健可用，局部老因子分化", fontsize=12.0, fontweight="bold", y=0.98)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    fig.savefig(c1_path)
    plt.close(fig)

    # Chart 2: Left = 20cm H1 vs H2 & A76 comparison; Right = Evolution Scan Funnel
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.6, 5.4), dpi=180)
    cp = audit["module1b_20cm_h2_anatomy"]["cohort_periods"]
    cats = ["上半年\n82分实盘档", "下半年\n82分实盘档", "下半年\n76至81观察档", "全五年\n82分实盘档"]
    vals_wr = [
        cp["S82_slot1"]["2026H1"]["wr_pct"],
        cp["S82_slot1"]["H2_Recent"]["wr_pct"],
        cp["A76_81_obs"]["H2_Recent"]["wr_pct"],
        cp["S82_slot1"]["5Y"]["wr_pct"],
    ]
    vals_mn = [
        cp["S82_slot1"]["2026H1"]["mean_ret_pct"],
        cp["S82_slot1"]["H2_Recent"]["mean_ret_pct"],
        cp["A76_81_obs"]["H2_Recent"]["mean_ret_pct"],
        cp["S82_slot1"]["5Y"]["mean_ret_pct"],
    ]
    vals_rh = [
        cp["S82_slot1"]["2026H1"]["risk_hit_pct"],
        cp["S82_slot1"]["H2_Recent"]["risk_hit_pct"],
        cp["A76_81_obs"]["H2_Recent"]["risk_hit_pct"],
        cp["S82_slot1"]["5Y"]["risk_hit_pct"],
    ]
    xc = np.arange(len(cats))
    ax1.bar(xc - 0.18, vals_wr, width=0.35, color=NAVY, label="胜率 (%)")
    ax1.bar(xc + 0.18, vals_rh, width=0.35, color=AMBER, alpha=0.88, label="大盘跌停风控触发率 (%)")
    for xi, wv, rv, mv in zip(xc, vals_wr, vals_rh, vals_mn):
        ax1.text(xi - 0.18, wv + 1.2, f"{wv:.1f}%\n(+{mv:.2f}%)", ha="center", va="bottom", fontsize=7.5, color=NAVY, fontweight="bold")
        ax1.text(xi + 0.18, rv + 1.2, f"{rv:.1f}%", ha="center", va="bottom", fontsize=7.6, color=AMBER, fontweight="bold")
    ax1.set_xticks(xc)
    ax1.set_xticklabels(cats, fontsize=8.6)
    ax1.set_ylim(0, 86)
    ax1.set_ylabel("百分比 (%)", fontsize=9.5)
    ax1.set_title("20cm深水下半年降温根因：跌停激增挤压止盈且机构分偏弱", fontsize=10.2, fontweight="bold")
    ax1.grid(True, axis="y", ls="--", alpha=0.25)
    ax1.legend(loc="upper right", fontsize=8.0, frameon=True, facecolor="white")

    ev = audit["module2_evolution"]
    recs = [r for r in audit["module2_all_240_summary"] if r["is_new_candidate"]]
    g1_c = sum(1 for r in recs if r["gates"]["g1_perm"])
    g3_c = sum(1 for r in recs if r["gates"]["g1_perm"] and r["gates"]["g3_qtr"])
    g4_c = sum(1 for r in recs if r["gates"]["g1_perm"] and r["gates"]["g3_qtr"] and r["gates"]["g4_ex2"])
    surv_c = ev["survivors_all_4_count"]
    stages = ["全部新候选\n特征扫描", "近一年走强\n初筛异动", "单特征置换\n通过检验", "叠加跨季度\n及去极值稳健", "多重校验后\n最终真规律"]
    counts = [ev["new_candidate_pairs"], ev["emergent_candidates_count"], g1_c, g4_c, surv_c]
    xs = np.arange(len(stages))[::-1]
    cols_f = [SLATE, NAVY, TEAL, AMBER, CRIMSON]
    ax2.barh(xs, counts, color=cols_f, alpha=0.88, height=0.58)
    for xi, cv in zip(xs, counts):
        ax2.text(cv + 3, xi, f"{cv} 组", va="center", fontsize=8.8, fontweight="bold", color=NAVY)
    ax2.set_yticks(xs)
    ax2.set_yticklabels(stages, fontsize=8.8)
    ax2.set_xlim(0, max(counts) * 1.18)
    ax2.set_xlabel("通过防伪筛查的特征组数", fontsize=9.5)
    ax2.set_title("近一年新特征进化防伪漏斗：四重检验后 0 组真进化幸存", fontsize=10.2, fontweight="bold")
    ax2.grid(True, axis="x", ls="--", alpha=0.25)

    fig.suptitle("20cm 下半年降温解剖与新规律防伪筛查：维持现役规则不盲改", fontsize=12.0, fontweight="bold", y=0.98)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    fig.savefig(c2_path)
    plt.close(fig)
    return c1_path, c2_path

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate 4 high-DPI Chinese institutional charts with ample label padding and exact 657-event numbers."""
import json, os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = ["STHeiti", "Heiti TC", "PingFang HK", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

BASE_DIR = "/Users/huaichuaibeimeng/claude-projects/output/csrc_policy_100factors_20261114"
BT_DIR = os.path.join(BASE_DIR, "backtest")
CH_DIR = os.path.join(BASE_DIR, "charts")
os.makedirs(CH_DIR, exist_ok=True)


def single_slot_curve(ev_df, mask, val_col, step_days):
    sub = ev_df[mask & (ev_df["t_entry_idx"] >= 0) & ev_df[val_col].notna()].sort_values("t_entry_idx")
    nav, nf = [1.0], -1
    for _, r in sub.iterrows():
        if int(r["t_entry_idx"]) >= nf:
            nav.append(nav[-1] * (1.0 + float(r[val_col])))
            nf = int(r["t_entry_idx"]) + step_days
    return nav


def make_charts():
    f_df = pd.read_csv(os.path.join(BT_DIR, "factors_144_full_ledger.csv")).set_index("factor_id")
    grids = json.load(open(os.path.join(BT_DIR, "perturbation_grids.json"), encoding="utf-8"))
    ev_df = pd.read_parquet(os.path.join(BT_DIR, "master_events_pit.parquet"))

    # Chart 1: Overnight Gap Front-Running vs Post-Open Tradable Return
    fig, ax = plt.subplots(figsize=(11.5, 6.0), dpi=220)
    items = [
        ("F047", "利好高开超3%追入（20日）"),
        ("F009", "政治局只字未提股市（20日）"),
        ("F026", "单降印花税规费追高（20日）"),
        ("F016", "汇金熊市下跌途护盘（20日）"),
        ("F008", "政治局提股市次日追高（20日）"),
        ("F019", "光喊话30天零政策落地（20日）"),
        ("F001", "证监会主席单兵发声（20日）"),
        ("F097", "新主席履新首30天新政（20日）"),
        ("F015", "央行互换便利与再贷款（20日）"),
        ("F144", "吴清期多部委硬工具底（20日）"),
        ("F115", "多部委救市全A等权（5日）"),
    ]
    labels = [x[1] for x in items]
    gaps = [float(f_df.loc[i, "avg_entry_gap_pct"]) for i, _ in items]
    rets = [float(f_df.loc[i, "main_mean_pct"]) for i, _ in items]
    y = np.arange(len(labels))
    h = 0.36
    ax.barh(y - h / 2, gaps, height=h, color="#94a3b8", label="隔夜高开幅度（盘前跳空散户吃不到）")
    ax.barh(y + h / 2, rets, height=h, color=["#dc2626" if v < 0 else "#1d4ed8" for v in rets], label="首个可买开盘价起算真实净收益")
    ax.axvline(0, color="#334155", lw=1.0)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=10)
    ax.set_xlim(min(min(gaps), min(rets)) - 1.8, max(max(gaps), max(rets)) + 1.8)
    ax.set_xlabel("收益率百分比（%）", fontsize=10.5)
    ax.set_title("隔夜高开抢跑 vs 开盘买入真实净收益：谁在兑现利好，谁在真正推升市场", fontsize=12.5, fontweight="bold", pad=12)
    for idx, v in enumerate(rets):
        ax.text(v + (0.15 if v >= 0 else -0.15), idx + h / 2, f"{v:+.2f}%", va="center", ha="left" if v >= 0 else "right", fontsize=8.8, fontweight="bold")
    ax.legend(loc="lower right", frameon=True, fontsize=9.5)
    ax.grid(axis="x", linestyle=":", alpha=0.5)
    fig.tight_layout()
    fig.savefig(os.path.join(CH_DIR, "chart1_hierarchy_hard_vs_soft.png"))
    plt.close(fig)

    # Chart 2: Left-Right Perturbation (Drawdown Sweet Spot vs Waterfall + Entry Gap Trap)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.8, 5.4), dpi=220)
    g1 = pd.DataFrame(grids["grid1_drawdown_x_horizon"])
    x1 = np.arange(len(g1))
    w = 0.26
    ax1.bar(x1 - w, g1["ret_5d_pct"].fillna(0), width=w, color="#60a5fa", label="开盘买持有5日")
    ax1.bar(x1, g1["ret_20d_pct"].fillna(0), width=w, color="#2563eb", label="开盘买持有20日")
    ax1.bar(x1 + w, g1["ret_60d_pct"].fillna(0), width=w, color="#1e3a8a", label="开盘买持有60日")
    ax1.axhline(0, color="#334155", lw=0.9)
    ax1.set_xticks(x1)
    ax1.set_xticklabels(g1["bucket"], rotation=22, ha="right", fontsize=9)
    ax1.set_ylim(-12.5, 6.5)
    ax1.set_ylabel("平均收益率（%）")
    ax1.set_title("左图：先验60日回撤打磨（14%至18%最甜，超18%政策底非市场底）", fontsize=11, fontweight="bold")
    ax1.legend(fontsize=8.5, loc="lower right")
    ax1.grid(axis="y", linestyle=":", alpha=0.5)

    g2 = pd.DataFrame(grids["grid2_gap_vs_post_open"])
    x2 = np.arange(len(g2))
    v20 = g2["post_open_20d_pct"].fillna(0).tolist()
    ax2.bar(x2, v20, width=0.48, color=["#1d4ed8" if v >= 0 else "#dc2626" for v in v20])
    ax2.axhline(0, color="#334155", lw=0.9)
    ax2.set_xticks(x2)
    ax2.set_xticklabels(g2["gap_bucket"], rotation=20, ha="right", fontsize=9)
    ax2.set_ylim(-5.4, 3.4)
    ax2.set_ylabel("开盘买入后20日平均收益率（%）")
    ax2.set_title("右图：首日高开阈值打磨（0.8%至1.8%最佳，超3%必套）", fontsize=11, fontweight="bold")
    for idx, v in enumerate(v20):
        ax2.text(idx, v + (0.20 if v >= 0 else -0.42), f"{v:+.2f}%", ha="center", fontsize=9, fontweight="bold")
    ax2.grid(axis="y", linestyle=":", alpha=0.5)
    fig.tight_layout()
    fig.savefig(os.path.join(CH_DIR, "chart2_perturbation_drawdown_and_gap.png"))
    plt.close(fig)

    # Chart 3: 7 Chairmen Scorecard & Verb-to-Policy Conversion
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.8, 5.3), dpi=220)
    g4 = pd.DataFrame(grids["grid4_seven_chairmen_scorecard"])
    xc = np.arange(len(g4))
    ax1.bar(xc - 0.18, g4["policy_30d_conversion_pct"].fillna(0), width=0.35, color="#0f766e", label="发言后30日内实质政策落地率（%）")
    ax1.bar(xc + 0.18, g4["rescue_20d_win_pct"].fillna(0), width=0.35, color="#2563eb", label="维稳发声后20日上涨胜率（%）")
    ax1.set_xticks(xc)
    ax1.set_xticklabels(g4["chairman"], fontsize=10)
    ax1.set_ylim(0, 105)
    ax1.set_title("左图：历任七位证监会主席政策兑现率与维稳胜率", fontsize=11.5, fontweight="bold")
    ax1.legend(fontsize=8.5)
    ax1.grid(axis="y", linestyle=":", alpha=0.5)

    g3 = pd.DataFrame(grids["grid3_verb_to_policy_lead"])
    xv = np.arange(len(g3))
    ax2.plot(xv, g3["hit_30d_pct"].fillna(0), marker="o", lw=2.2, color="#2563eb", label="30天内政策落地率")
    ax2.plot(xv, g3["hit_60d_pct"].fillna(0), marker="s", lw=2.2, color="#0f766e", label="60天内政策落地率")
    ax2.plot(xv, g3["hit_90d_pct"].fillna(0), marker="^", lw=2.2, color="#7c3aed", label="90天内政策落地率")
    ax2.set_xticks(xv)
    ax2.set_xticklabels(g3["stage_cn"], rotation=18, ha="right", fontsize=9)
    ax2.set_ylim(0, 105)
    ax2.set_ylabel("实质规则出台比例（%）")
    ax2.set_title("右图：官方措辞动词递进对后续政策的提前预见率", fontsize=11.5, fontweight="bold")
    ax2.legend(fontsize=8.5)
    ax2.grid(linestyle=":", alpha=0.5)
    fig.tight_layout()
    fig.savefig(os.path.join(CH_DIR, "chart3_chairmen_and_verb_lead.png"))
    plt.close(fig)

    # Chart 4: Validated Core Alpha Single-Slot Compound Curves vs Chasing Gap Trap
    ev_df = ev_df.copy()
    ev_df["ex_tech_60d"] = ev_df["ret_tech_board_60d"] - ev_df["ret_bench_60d"]
    ev_df["ex_ew_60d"] = ev_df["ret_ew_60d"] - ev_df["ret_bench_60d"]
    ev_df["sp_lg_mc_60d"] = ev_df["ret_large10_60d"] - ev_df["ret_micro30_60d"]

    m_f134 = ((ev_df["tech_innovation_support"] >= 2) | (ev_df["ma_restructuring_support"] >= 2)) & (ev_df["prior_amt_pct_250d"] < 0.85)
    m_f096 = (ev_df["liquidity_long_term_capital"] >= 1) & ((ev_df["share_reduction_crackdown"] >= 1) | (ev_df["speculation_fraud_crackdown"] >= 1))
    m_f015 = (ev_df["authority_level"] == "PBOC_HARD_TOOL") | ev_df["hard_levers_joined"].fillna("").str.contains("PBOC_SFISF") | ev_df["quotes_joined"].fillna("").str.contains("互换便利|回购增持再贷款|充足流动性")
    m_trap = (ev_df["entry_gap_bench"] > 0.030) | ev_df["hard_levers_joined"].fillna("").str.contains("STAMP_DUTY")

    nav_134 = single_slot_curve(ev_df, m_f134, "ex_tech_60d", 60)
    nav_096 = single_slot_curve(ev_df, m_f096, "sp_lg_mc_60d", 60)
    nav_015 = single_slot_curve(ev_df, m_f015, "ret_bench_20d", 20)
    nav_trp = single_slot_curve(ev_df, m_trap, "ret_bench_20d", 20)

    fig, ax = plt.subplots(figsize=(11.5, 5.3), dpi=220)
    ax.plot(range(len(nav_134)), nav_134, marker="o", markersize=4, lw=2.3, color="#1d4ed8", label=f"硬科技与并购结构牛单仓超额（F134，触发{len(nav_134)-1}次，终值{nav_134[-1]:.2f}倍）")
    ax.plot(range(len(nav_096)), nav_096, marker="s", markersize=4, lw=2.2, color="#0f766e", label=f"长钱入市加严打造假大盘赢微盘（F096，触发{len(nav_096)-1}次，终值{nav_096[-1]:.2f}倍）")
    ax.plot(range(len(nav_015)), nav_015, marker="^", markersize=4.5, lw=2.2, color="#7c3aed", label=f"央行互换便利与流动性硬工具择时（F015，触发{len(nav_015)-1}次，终值{nav_015[-1]:.2f}倍）")
    ax.plot(range(len(nav_trp)), nav_trp, marker="x", markersize=5, lw=2.1, color="#dc2626", label=f"反面陷阱：高开超3%或单降印花税追涨（触发{len(nav_trp)-1}次，终值{nav_trp[-1]:.2f}倍）")
    ax.axhline(1.0, color="#64748b", linestyle="--", lw=1.0)
    ax.set_xlabel("单仓不重叠独立触发序号（按时间先后排列）", fontsize=10.5)
    ax.set_ylabel("单仓不重叠累计复利净值（起点=1.0）", fontsize=10.5)
    ax.set_title("2000至2026年四大核心结论单仓不重叠复利实证（全部扣除隔夜高开后）", fontsize=12.5, fontweight="bold")
    ax.legend(fontsize=9.2, loc="upper left")
    ax.grid(linestyle=":", alpha=0.5)
    fig.tight_layout()
    fig.savefig(os.path.join(CH_DIR, "chart4_single_slot_compound_nav.png"))
    plt.close(fig)
    print(f"Charts updated: F134={nav_134[-1]:.2f}x ({len(nav_134)-1}), F096={nav_096[-1]:.2f}x ({len(nav_096)-1}), F015={nav_015[-1]:.2f}x ({len(nav_015)-1}), Trap={nav_trp[-1]:.2f}x ({len(nav_trp)-1})")


if __name__ == "__main__":
    make_charts()

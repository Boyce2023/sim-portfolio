#!/opt/homebrew/bin/python3.13
"""Generate clean plain-Chinese PNG charts for RD036 Feishu report."""

import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 VIOLATION: yfinance forbidden"

BASE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd036_highorder_3way_4way_20261126"
RT_JSON = f"{BASE}/part3_redteam_final/rd036_redteam_audit.json"
O5_JSON = f"{BASE}/part2_other5/rd036_other5_audit.json"
GRID_CSV = f"{BASE}/part1_20cm/rd036_20cm_grid.csv"
OUT_DIR = f"{BASE}/part3_redteam_final"


def _setup_cn_font():
    plt.rcParams["font.sans-serif"] = [
        "Arial Unicode MS",
        "PingFang SC",
        "STHeiti",
        "Heiti TC",
        "DejaVu Sans",
    ]
    plt.rcParams["axes.unicode_minus"] = False


def build_chart1(rt: dict) -> str:
    """Chart 1: 20cm stability stress ladder + V20 combined single-slot truth."""
    _setup_cn_font()
    g1 = rt["gate1_trade_forensics"]
    yc = rt["gate3_yearly_and_displacement"]["yearly_comparison"]
    comb = rt["gate3_yearly_and_displacement"]["v20_combined_displacement"]

    keys = [
        ("BASE_V11_S82", "82分原版"),
        ("BASE_V11_S80", "80分原版"),
        ("GBDT_D3_cold50_d8_S80", "浅树3层(毙杀)"),
        ("Stack_c50_Avg_CB15_MN15_R3W12_S80", "冷清三路均值"),
        ("Blend_c50_Half_CB15_MN15_S80", "冷清半融合"),
    ]
    colors = ["#64748b", "#3b82f6", "#ef4444", "#0ea5e9", "#16a34a"]

    metrics_labels = ["全样本30bps", "80bps重滑点", "两亿成交过滤", "去前五牛股"]
    vals_by_model = []
    for k, _ in keys:
        f1 = g1[k]
        r_yc = yc[k]["row"]
        vals_by_model.append([
            f1["nav_30bps"],
            f1["nav_80bps"],
            r_yc["nav_liq2y"],
            f1["ex5_nav_30bps"],
        ])

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14.5, 6.2), dpi=180)
    fig.patch.set_facecolor("white")

    # Left panel: grouped stress bars
    x = np.arange(len(metrics_labels))
    w = 0.155
    for idx, ((_, lbl), col, vals) in enumerate(zip(keys, colors, vals_by_model)):
        offset = (idx - 2) * w
        bars = ax1.bar(x + offset, vals, width=w, label=lbl, color=col, alpha=0.92, edgecolor="white", linewidth=0.5)
        for b in bars:
            h = b.get_height()
            ax1.text(b.get_x() + b.get_width() / 2, h + 1.8, f"{h:.1f}", ha="center", va="bottom", fontsize=7.5, color="#1e293b")

    ax1.set_xticks(x)
    ax1.set_xticklabels(metrics_labels, fontsize=10, fontweight="bold")
    ax1.set_ylabel("逐日滚动实测净值（倍）", fontsize=10, fontweight="bold")
    ax1.set_title("20cm 核心候选压力阶梯与去极值净值对照", fontsize=12, fontweight="bold", pad=12)
    ax1.set_ylim(0, 168)
    ax1.grid(axis="y", linestyle="--", alpha=0.35)
    ax1.legend(loc="upper right", fontsize=8.5, frameon=True, facecolor="#f8fafc")

    nr_blend = yc["Blend_c50_Half_CB15_MN15_NoRound_S80"]["row"]["nav_wf"]
    hu_blend = yc["Blend_c50_Half_CB15_MN15_HalfUp_S80"]["row"]["nav_wf"]
    nr_stack = yc["Stack_c50_Avg_CB15_MN15_R3W12_NoRound_S80"]["row"]["nav_wf"]
    note_txt = (
        f"四舍五入敏感度实测：\n"
        f"半融合无舍入 {nr_blend:.1f}倍 / 进位 {hu_blend:.1f}倍\n"
        f"三路均值无舍入 {nr_stack:.1f}倍 (极稳定)"
    )
    ax1.text(
        0.52, 0.57, note_txt, transform=ax1.transAxes, fontsize=8.5,
        bbox=dict(boxstyle="round,pad=0.45", facecolor="#fefce8", edgecolor="#eab308", linewidth=1.0),
        color="#713f12",
    )

    # Right panel: V20 combined single-slot NAV (in 10k x = 万倍)
    comb_items = [
        ("82分原版", comb["S80_vs_S82"]["ref_nav"] / 1e4, "#64748b", "基准参考"),
        ("80分原版", comb["S80_vs_S82"]["cand_nav"] / 1e4, "#3b82f6", "仅降门槛至80分"),
        ("浅树3层(毙杀)", comb["GBDT_D3_vs_S80"]["cand_nav"] / 1e4, "#ef4444", "挤占合富中国，反输80分原版"),
        ("冷清三路均值", comb["Stack_vs_S80"]["cand_nav"] / 1e4, "#0ea5e9", "净增+58%，0笔主策略被挤占"),
        ("冷清半融合", comb["Blend_vs_S80"]["cand_nav"] / 1e4, "#16a34a", "净增+80%，85%来自20cm真增量"),
    ]
    y_pos = np.arange(len(comb_items))
    c_vals = [it[1] for it in comb_items]
    c_cols = [it[2] for it in comb_items]
    bars2 = ax2.barh(y_pos, c_vals, color=c_cols, height=0.55, alpha=0.92)
    ax2.axvline(comb["S80_vs_S82"]["cand_nav"] / 1e4, color="#3b82f6", linestyle="--", linewidth=1.2, alpha=0.75)

    for idx, (lbl, val, _, note) in enumerate(comb_items):
        ax2.text(val + 2.5, idx, f"{val:.1f}万倍（{note}）", va="center", ha="left", fontsize=8.8, fontweight="bold" if idx >= 3 else "normal", color="#0f172a")

    ax2.set_yticks(y_pos)
    ax2.set_yticklabels([it[0] for it in comb_items], fontsize=10, fontweight="bold")
    ax2.set_xlabel("全系统合体单仓滚动净值（万倍）", fontsize=10, fontweight="bold")
    ax2.set_title("合体单仓挤占真相：半融合真增量与浅树假象", fontsize=12, fontweight="bold", pad=12)
    ax2.set_xlim(0, 305)
    ax2.grid(axis="x", linestyle="--", alpha=0.35)

    plt.tight_layout(pad=2.0)
    out1 = f"{OUT_DIR}/rd036_chart1_20cm_forensics.png"
    fig.savefig(out1, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out1


def build_chart2(rt: dict, o5: dict, grid_df: pd.DataFrame) -> str:
    """Chart 2: Blend plateau & Tree overfitting contrast + Other 5 strategies cold vs active split."""
    _setup_cn_font()
    yc = rt["gate3_yearly_and_displacement"]["yearly_comparison"]
    nb = rt["gate2_blend_plateau"]["stack_and_gbdt_neighbors"]
    s80_plat = rt["gate2_blend_plateau"]["cold50_mix_s80_table"]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14.5, 6.2), dpi=180)
    fig.patch.set_facecolor("white")

    # Left panel: Spike vs Plateau & Depth 3 vs Depth 4 overfitting
    d4_row = grid_df[grid_df["variant"] == "GBDT_D4_cold50_d8_S80"].iloc[0]
    base_s80 = yc["BASE_V11_S80"]["row"]["nav_wf"]
    blend_med = rt["gate2_blend_plateau"]["summary_cold50_s80_slice"]["nav_median"]
    blend_min = rt["gate2_blend_plateau"]["summary_cold50_s80_slice"]["nav_min"]

    labels_l = [
        "浅树3层\n加5分",
        "浅树3层\n加8分(尖峰)",
        "浅树3层\n加10分",
        "浅树3层\n加12分",
        "浅树3层\n加15分",
        "浅树4层\n加8分(塌缩)",
        "半融合80分\n12组混权中位",
    ]
    blend_mix12_med = float(np.median([r["nav_wf"] for r in s80_plat]))
    vals_l = [
        nb["GBDT_D3_cold50_d5_S80"]["nav_wf"],
        yc["GBDT_D3_cold50_d8_S80"]["row"]["nav_wf"],
        nb["GBDT_D3_cold50_d10_S80"]["nav_wf"],
        nb["GBDT_D3_cold50_d12_S80"]["nav_wf"],
        nb["GBDT_D3_cold50_d15_S80"]["nav_wf"],
        float(d4_row["nav_wf"]),
        blend_mix12_med,
    ]
    cols_l = ["#94a3b8", "#ef4444", "#94a3b8", "#94a3b8", "#94a3b8", "#f97316", "#16a34a"]

    x1 = np.arange(len(labels_l))
    bars1 = ax1.bar(x1, vals_l, color=cols_l, width=0.58, alpha=0.92)
    ax1.axhline(base_s80, color="#3b82f6", linestyle="--", linewidth=1.3, label=f"80分原版基线 ({base_s80:.1f}倍)")
    ax1.axhline(blend_min, color="#22c55e", linestyle=":", linewidth=1.3, label=f"半融合16组最低谷 ({blend_min:.1f}倍)")

    for b in bars1:
        h = b.get_height()
        ax1.text(b.get_x() + b.get_width() / 2, h + 1.8, f"{h:.1f}", ha="center", va="bottom", fontsize=8.8, fontweight="bold")

    ax1.set_xticks(x1)
    ax1.set_xticklabels(labels_l, fontsize=8.8, fontweight="bold")
    ax1.set_ylabel("逐日滚动实测净值（倍）", fontsize=10, fontweight="bold")
    ax1.set_title("单点尖峰与4层树过拟合 vs 半融合参数高原", fontsize=12, fontweight="bold", pad=12)
    ax1.set_ylim(0, 128)
    ax1.grid(axis="y", linestyle="--", alpha=0.35)
    ax1.legend(loc="upper left", fontsize=8.5, frameon=True, facecolor="#f8fafc")

    ax1.text(
        0.47, 0.72,
        "浅树由3层加深至4层后：\n垫底过拟合概率 27.4% 翻倍至 55.6%\n样本跌至每叶约25笔，净值腰斩44%",
        transform=ax1.transAxes, fontsize=8.5,
        bbox=dict(boxstyle="round,pad=0.45", facecolor="#fff7ed", edgecolor="#f97316", linewidth=1.0),
        color="#7c2d12",
    )

    # Right panel: Other 5 strategies Cold vs Active slot NAV (log scale)
    strat_map = [
        ("1to2", "一进二"),
        ("2to3", "二进三"),
        ("3to4", "三进四"),
        ("high", "高标首阴"),
        ("pry", "撬板"),
    ]
    cold_vals, act_vals, cold_wr, act_wr = [], [], [], []
    for sk, _ in strat_map:
        ca = o5["m1_cold_vs_active_summary"][sk]["cut_50"]
        cold_vals.append(ca["wf_slot_cold"]["nav"])
        act_vals.append(ca["wf_slot_active"]["nav"])
        cold_wr.append(ca["wf_slot_cold"]["wr_pct"])
        act_wr.append(ca["wf_slot_active"]["wr_pct"])

    x2 = np.arange(len(strat_map))
    w2 = 0.34
    b_c = ax2.bar(x2 - w2 / 2, cold_vals, width=w2, label="市场冷清日(50分位下)", color="#0284c7", alpha=0.9)
    b_a = ax2.bar(x2 + w2 / 2, act_vals, width=w2, label="市场活跃日(50分位上)", color="#f59e0b", alpha=0.9)
    ax2.set_yscale("log")
    ax2.axhline(1.0, color="#64748b", linestyle="--", linewidth=1.0)

    for b, wr in zip(b_c, cold_wr):
        h = b.get_height()
        ax2.text(b.get_x() + b.get_width() / 2, h * 1.12, f"{h:.2f}x\n({wr:.0f}%)", ha="center", va="bottom", fontsize=7.6, color="#0369a1")
    for b, wr in zip(b_a, act_wr):
        h = b.get_height()
        ax2.text(b.get_x() + b.get_width() / 2, h * 1.12, f"{h:.2f}x\n({wr:.0f}%)", ha="center", va="bottom", fontsize=7.6, color="#b45309")

    ax2.set_xticks(x2)
    ax2.set_xticklabels([lbl for _, lbl in strat_map], fontsize=10, fontweight="bold")
    ax2.set_ylabel("单仓净值（倍，对数刻度）与胜率", fontsize=10, fontweight="bold")
    ax2.set_title("其余五策略525项试错0过关：冷暖环境分化实证", fontsize=12, fontweight="bold", pad=12)
    ax2.set_ylim(0.5, 95)
    ax2.grid(axis="y", linestyle="--", alpha=0.35)
    ax2.legend(loc="upper right", fontsize=8.8, frameon=True, facecolor="#f8fafc")

    plt.tight_layout(pad=2.0)
    out2 = f"{OUT_DIR}/rd036_chart2_overfit_and_other5.png"
    fig.savefig(out2, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out2


def main():
    with open(RT_JSON) as f:
        rt = json.load(f)
    with open(O5_JSON) as f:
        o5 = json.load(f)
    grid_df = pd.read_csv(GRID_CSV)
    p1 = build_chart1(rt)
    p2 = build_chart2(rt, o5, grid_df)
    print(f"Generated charts:\n  1) {p1} ({os.path.getsize(p1)} bytes)\n  2) {p2} ({os.path.getsize(p2)} bytes)")


if __name__ == "__main__":
    main()

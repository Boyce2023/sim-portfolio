#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Generate two clean, pure-Chinese high-DPI charts for RD039 Feishu report."""

import json
import os
import pandas as pd
import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd039_single_strat_sharpe_lift_20261126/front4_redteam_and_assembly"

plt.rcParams["font.sans-serif"] = ["Hiragino Sans GB", "PingFang HK", "STHeiti", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def make_charts():
    with open(f"{OUT_DIR}/rd039_final_audit.json", encoding="utf-8") as f:
        audit = json.load(f)
    forensics = pd.read_csv(f"{OUT_DIR}/rd039_3to4_stop_forensics.csv")
    pk_df = pd.read_csv(f"{OUT_DIR}/rd039_vs_rd038_pk.csv")

    # ------------------------------------------------------------------
    # Chart 1: Three-to-Four Component Autopsy + 5m Stop Trade Forensics
    # ------------------------------------------------------------------
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14.2, 5.8), dpi=200)
    fig.patch.set_facecolor("white")

    ab_rows = {r["variant_id"]: r for r in audit["front2_3to4_redteam_autopsy"]["component_ablation"]}
    items = [
        ("0_V41_Baseline", "原版三进四基准", "#64748B", None),
        ("A_Only5mStop_Prevc6", "仅加五分钟止损", "#38BDF8", None),
        ("B_Only_M4MineBL15", "仅加四因子排雷", "#0EA5E9", None),
        ("AB_CleanBest_M4_Prevc6", "排雷叠止损净版", "#1D4ED8", None),
        ("U4_Worst1Bonus_t0", "无偏真动态剔除", "#F59E0B", None),
        ("ABC_RD039B_Hardcoded_Af20", "硬编码20号(废除)", "#EF4444", "///"),
    ]
    labels = [x[1] for x in items][::-1]
    vals = [ab_rows[x[0]]["nav_wf"] for x in items][::-1]
    colors = [x[2] for x in items][::-1]
    hatches = [x[3] for x in items][::-1]
    shs = [ab_rows[x[0]]["sh_wf"] for x in items][::-1]
    mdds = [ab_rows[x[0]]["mdd_wf"] for x in items][::-1]

    y = np.arange(len(labels))
    bars = ax1.barh(y, vals, height=0.58, color=colors, edgecolor="#1E293B", linewidth=0.6)
    for bar, h in zip(bars, hatches):
        if h:
            bar.set_hatch(h)

    ax1.axvline(ab_rows["0_V41_Baseline"]["nav_wf"], color="#475569", linestyle="--", linewidth=1.1, alpha=0.75)
    for i, (v, sh, mdd) in enumerate(zip(vals, shs, mdds)):
        ax1.text(v + 7, i, f"{v:.1f}倍 | 波动比{sh:.2f} | 回撤{mdd:.1f}%", va="center", fontsize=8.8, color="#0F172A")

    ax1.set_yticks(y)
    ax1.set_yticklabels(labels, fontsize=9.8, fontweight="bold")
    ax1.set_xlim(0, 560)
    ax1.set_xlabel("2023至2026样本外累计净值倍数", fontsize=9.8)
    ax1.set_title("三进四组件拆解与硬编码漏洞对比", fontsize=11.5, fontweight="bold", pad=10)
    ax1.grid(axis="x", linestyle=":", alpha=0.5)
    ax1.spines["top"].set_visible(False)
    ax1.spines["right"].set_visible(False)

    # Panel B: 5m Stop Forensics trade-by-trade
    tag_map = {
        "京粮控股": "22.03 京粮控股 [总账误杀]",
        "长久物流": "22.04 长久物流 [总账误杀]",
        "恒久退": "22.10 恒久退 [样本内止损]",
        "正和生态": "23.08 正和生态 [五件套持仓]",
        "龙江交通": "23.09 龙江交通 [未触发]",
        "合锻智能": "24.02 合锻智能 [总账微亏]",
        "鼎信通讯": "24.12 鼎信通讯 [未触发]",
        "友好集团": "25.01 友好集团 [未触发]",
        "中毅达": "25.03 中毅达 [总账未买]",
        "宝光股份": "26.05 宝光股份 [总账未买]",
    }
    f_disp = forensics.copy()
    f_disp["disp"] = f_disp["name"].map(tag_map)
    f_disp = f_disp.iloc[::-1].reset_index(drop=True)

    y2 = np.arange(len(f_disp))
    base_r = f_disp["base_ret30_pct"].to_numpy(float)
    stop_r = f_disp["prevc6_ret30_pct"].to_numpy(float)
    deltas = f_disp["prevc6_delta_pp"].to_numpy(float)

    ax2.axvline(0.0, color="#64748B", linewidth=1.0)
    for i in range(len(f_disp)):
        b_v, s_v, d_v = base_r[i], stop_r[i], deltas[i]
        if abs(d_v) > 0.01:
            c_line = "#16A34A" if d_v > 0 else "#DC2626"
            ax2.plot([b_v, s_v], [i, i], color=c_line, linewidth=2.6, zorder=2)
            ax2.scatter([b_v], [i], color="#94A3B8", s=46, zorder=3, edgecolors="#1E293B", linewidths=0.7)
            ax2.scatter([s_v], [i], color=c_line, s=58, zorder=4, edgecolors="#0F172A", linewidths=0.7)
            tx = max(b_v, s_v) + 1.0
            ax2.text(
                tx, i, f"{b_v:+.1f}% 变 {s_v:+.1f}% ({d_v:+.1f}%)",
                va="center", fontsize=8.3, color=c_line, fontweight="bold", zorder=5,
                bbox=dict(facecolor="white", edgecolor="none", alpha=0.85, pad=0.6),
            )
        else:
            ax2.scatter([b_v], [i], color="#475569", marker="x", s=48, zorder=3)
            ax2.text(
                b_v + 1.0, i, f"仍为 {b_v:+.1f}% (未破止损线)",
                va="center", fontsize=8.3, color="#475569", zorder=5,
                bbox=dict(facecolor="white", edgecolor="none", alpha=0.85, pad=0.6),
            )

    ax2.set_yticks(y2)
    ax2.set_yticklabels(f_disp["disp"].tolist(), fontsize=9.0)
    ax2.set_xlim(-28, 30)
    ax2.set_xlabel("单笔千三扣费净收益率 (%)", fontsize=9.8)
    ax2.set_title("次日五分钟止损十笔关键单逐笔核查", fontsize=11.5, fontweight="bold", pad=10)
    ax2.grid(axis="x", linestyle=":", alpha=0.5)
    ax2.spines["top"].set_visible(False)
    ax2.spines["right"].set_visible(False)

    leg_handles = [
        Patch(facecolor="#94A3B8", edgecolor="#1E293B", label="原版卖出收益"),
        Patch(facecolor="#16A34A", edgecolor="#0F172A", label="止损减亏或改好"),
        Patch(facecolor="#DC2626", edgecolor="#0F172A", label="止损误杀反亏"),
    ]
    ax2.legend(handles=leg_handles, loc="lower right", fontsize=8.3, frameon=True, facecolor="white")

    fig.tight_layout(pad=1.6)
    p1 = f"{OUT_DIR}/chart1_rd039_redteam_autopsy.png"
    fig.savefig(p1, dpi=200)
    plt.close(fig)

    # ------------------------------------------------------------------
    # Chart 2: Grand PK Multi-Fee & Liquidity + 32-Variant Stop Plateau
    # ------------------------------------------------------------------
    fig2, (bx1, bx2) = plt.subplots(1, 2, figsize=(14.2, 5.6), dpi=200)
    fig2.patch.set_facecolor("white")

    pk_wf = pk_df[pk_df["window"] == "WF_2326"].copy()
    bundles = [
        ("1_V20_Baseline", "V20现役基准"),
        ("2_RD039_Pure5mStop_Prevc6", "V20仅五分钟止损"),
        ("3_RD039_3to4_CleanBest", "V20加三进四净版"),
        ("4_RD038_Clean5", "稳健五件套(原版)"),
        ("6_GRAND_COMBO_Clean5_Prevc6", "五件套加五分钟止损"),
    ]
    fee_specs = [
        ("030", "千三扣费", "#1D4ED8"),
        ("050", "千五扣费", "#0EA5E9"),
        ("080", "千八扣费", "#64748B"),
        ("liq2yi_030", "两亿成交千三", "#F59E0B"),
    ]
    x = np.arange(len(bundles))
    w = 0.19
    for fi, (ftag, flabel, fcol) in enumerate(fee_specs):
        sub_vals = []
        for bid, _ in bundles:
            row = pk_wf[(pk_wf["bundle"] == bid) & (pk_wf["fee_liq"] == ftag)]
            sub_vals.append(float(row["nav"].iloc[0]) / 10000.0)
        offset = (fi - 1.5) * w
        bars_b = bx1.bar(x + offset, sub_vals, width=w, color=fcol, label=flabel, edgecolor="#0F172A", linewidth=0.4)
        for bi, val in enumerate(sub_vals):
            if fi in (0, 3):
                bx1.text(x[bi] + offset, val + 5, f"{val:.1f}万", ha="center", va="bottom", fontsize=7.6, rotation=0, color="#0F172A")

    bx1.set_xticks(x)
    bx1.set_xticklabels([b[1] for b in bundles], fontsize=8.8, fontweight="bold")
    bx1.set_ylabel("样本外累计净值 (万倍)", fontsize=9.8)
    bx1.set_ylim(0, 368)
    bx1.set_title("统一总账多口径同台净值比拼", fontsize=11.5, fontweight="bold", pad=10)
    bx1.legend(loc="upper left", fontsize=8.5, frameon=True, facecolor="white")
    bx1.grid(axis="y", linestyle=":", alpha=0.5)
    bx1.spines["top"].set_visible(False)
    bx1.spines["right"].set_visible(False)

    # Panel B: 32-variant 5m stop plateau vs RD038 Clean5 baseline
    plat = pd.DataFrame(audit["v20_grand_pk"]["plateau_gc5_32"]["rows"])
    clean5_nav = 318.8278
    plat_nav_wan = plat["nav_wf"].to_numpy(float) / 10000.0
    beat_mask = plat_nav_wan > clean5_nav
    idx_p = np.arange(len(plat))

    bx2.axhline(clean5_nav, color="#DC2626", linestyle="--", linewidth=1.8, label=f"稳健五件套无止损原版 ({clean5_nav:.1f}万倍)")
    bx2.axhline(float(np.median(plat_nav_wan)), color="#0EA5E9", linestyle=":", linewidth=1.4, label=f"32组止损参数中位数 ({np.median(plat_nav_wan):.1f}万倍)")
    bx2.scatter(idx_p[~beat_mask], plat_nav_wan[~beat_mask], color="#64748B", s=44, label=f"跑输原版 ({int((~beat_mask).sum())}/32 组)")
    bx2.scatter(idx_p[beat_mask], plat_nav_wan[beat_mask], color="#16A34A", s=54, label=f"微超原版 ({int(beat_mask.sum())}/32 组)")

    bx2.set_xlim(-1.5, 32.5)
    bx2.set_ylim(282, 336)
    bx2.set_xlabel("32组不同止损阈值与触发时点组合编号", fontsize=9.8)
    bx2.set_ylabel("样本外累计净值 (万倍)", fontsize=9.8)
    bx2.set_title("32组五分钟止损参数高原 vs 五件套原版", fontsize=11.5, fontweight="bold", pad=10)
    bx2.legend(loc="lower right", fontsize=8.2, frameon=True, facecolor="white")
    bx2.grid(True, linestyle=":", alpha=0.5)
    bx2.spines["top"].set_visible(False)
    bx2.spines["right"].set_visible(False)
    bx2.text(
        1.0, 286.0,
        "全部32组样本外最大回撤同为47.58%，26组跑输原版",
        fontsize=8.8, color="#991B1B",
        bbox=dict(boxstyle="round,pad=0.35", facecolor="#FEF2F2", edgecolor="#FCA5A5"),
    )

    fig2.tight_layout(pad=1.6)
    p2 = f"{OUT_DIR}/chart2_rd039_vs_rd038_grand_pk.png"
    fig2.savefig(p2, dpi=200)
    plt.close(fig2)
    print(f"Charts generated:\n  {p1}\n  {p2}")
    return p1, p2


if __name__ == "__main__":
    make_charts()

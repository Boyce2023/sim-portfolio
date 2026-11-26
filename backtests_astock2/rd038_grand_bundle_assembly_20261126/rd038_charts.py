#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Generate 2 plain-Chinese PNG charts for RD038 Feishu report."""

import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

assert "yfinance" not in sys.modules, "D12 VIOLATION: yfinance forbidden"
sys.dont_write_bytecode = True

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd038_grand_bundle_assembly_20261126"
AUDIT_JSON = f"{OUT_DIR}/rd038_grand_bundle_audit.json"


def _setup_cn_font():
    plt.rcParams["font.sans-serif"] = [
        "Arial Unicode MS", "PingFang SC", "STHeiti", "Heiti TC", "DejaVu Sans",
    ]
    plt.rcParams["axes.unicode_minus"] = False


def build_chart1(audit: dict) -> str:
    """Chart 1: Portfolio synergy (20cm + Other5 -> 320万倍) & friction stress ladder."""
    _setup_cn_font()
    wf30 = {r["bundle"]: r for r in audit["key_bundles_wf_030"]}
    wf50 = {r["bundle"]: r for r in audit["key_bundles_wf_050"]}
    wf80 = {r["bundle"]: r for r in audit["key_bundles_wf_080"]}
    liq = audit["redteam_plateau_pbo_liq_dsr"]["liquidity_2yi_wf"]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14.8, 6.2), dpi=180)
    fig.patch.set_facecolor("white")

    items = [
        ("BASE_V20_Unified", "现役V20.0基准", "#64748b"),
        ("ONLY_20CM_STACK", "仅20cm三路均值", "#0ea5e9"),
        ("OTHER5_ONLY_ALLIN", "仅改其余五策略", "#8b5cf6"),
        ("ONLY_20CM_BLEND", "仅20cm半融合", "#0284c7"),
        ("GREEDY_ROBUST", "精简四件套(稳健)", "#059669"),
        ("GREEDY_CLEAN", "精简五件套(进攻)", "#10b981"),
        ("ALLIN_ROBUST", "全包合体(稳健)", "#15803d"),
        ("ALLIN_OFFENSIVE", "全包合体(进攻)", "#16a34a"),
    ]
    y = np.arange(len(items))
    vals = [wf30[k]["nav"] / 1e4 for k, _, _ in items]
    cols = [c for _, _, c in items]
    ax1.barh(y, vals, color=cols, height=0.58, alpha=0.92)
    ax1.axvline(wf30["BASE_V20_Unified"]["nav"] / 1e4, color="#64748b", linestyle="--", linewidth=1.2)
    for idx, (k, _, _) in enumerate(items):
        r = wf30[k]
        v = r["nav"] / 1e4
        ax1.text(v + 4.0, idx, f"{v:.1f}万倍 (夏普{r['daily_sharpe']:.2f})", va="center", ha="left", fontsize=8.5, fontweight="bold" if idx >= 4 else "normal", color="#0f172a")
    ax1.set_yticks(y)
    ax1.set_yticklabels([lbl for _, lbl, _ in items], fontsize=9.5, fontweight="bold")
    ax1.set_xlabel("2023至2026合体单仓滚动净值（万倍，统一30bps滑点）", fontsize=9.5, fontweight="bold")
    ax1.set_title("备选合体净值乘数跃迁：单改约140万 vs 合体320万倍", fontsize=11.5, fontweight="bold", pad=12)
    ax1.set_xlim(0, 445)
    ax1.grid(axis="x", linestyle="--", alpha=0.35)

    # Right panel: Slippage & Liquidity Stress Ladder (in 万倍)
    stress_keys = [
        ("BASE_V20_Unified", "现役基准", "#64748b"),
        ("ONLY_20CM_STACK", "仅三路均值", "#0ea5e9"),
        ("GREEDY_CLEAN", "精简五件套", "#10b981"),
        ("ALLIN_ROBUST", "合体稳健包", "#15803d"),
        ("ALLIN_OFFENSIVE", "合体进攻包", "#f59e0b"),
    ]
    cats = ["30bps统一", "50bps严苛", "80bps魔鬼", "两亿成交过滤"]
    x2 = np.arange(len(cats))
    w = 0.16
    for idx, (k, lbl, col) in enumerate(stress_keys):
        v_list = [
            wf30[k]["nav"] / 1e4,
            wf50[k]["nav"] / 1e4,
            wf80[k]["nav"] / 1e4,
            liq[k]["nav_wf"] / 1e4,
        ]
        bars = ax2.bar(x2 + (idx - 2) * w, v_list, width=w, label=lbl, color=col, alpha=0.92, edgecolor="white", linewidth=0.5)
        for b in bars:
            h = b.get_height()
            ax2.text(b.get_x() + b.get_width() / 2, h + 3.5, f"{h:.0f}", ha="center", va="bottom", fontsize=7.4, color="#1e293b")
    ax2.set_xticks(x2)
    ax2.set_xticklabels(cats, fontsize=9.5, fontweight="bold")
    ax2.set_ylabel("合体单仓净值（万倍）", fontsize=9.5, fontweight="bold")
    ax2.set_title("滑点与成交额压力实测：稳健包在80bps与两亿门槛下反超", fontsize=11.5, fontweight="bold", pad=12)
    ax2.set_ylim(0, 420)
    ax2.grid(axis="y", linestyle="--", alpha=0.35)
    ax2.legend(loc="upper right", fontsize=8.2, frameon=True, facecolor="#f8fafc")

    nr_rob = wf30["ALLIN_ROBUST_NoRound"]["nav"] / 1e4
    nr_off = wf30["ALLIN_OFFENSIVE_NoRound"]["nav"] / 1e4
    ax2.text(
        0.54, 0.56,
        f"去四舍五入敏感度实测：\n合体稳健包 {nr_rob:.1f}万倍 (仅降0.3%)\n合体进攻包 {nr_off:.1f}万倍 (骤降19.8%)",
        transform=ax2.transAxes, fontsize=8.3,
        bbox=dict(boxstyle="round,pad=0.45", facecolor="#fefce8", edgecolor="#eab308", linewidth=1.0),
        color="#713f12",
    )

    plt.tight_layout(pad=2.0)
    out1 = f"{OUT_DIR}/rd038_chart1_bundle_synergy_and_stress.png"
    fig.savefig(out1, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out1


def build_chart2(audit: dict) -> str:
    """Chart 2: Leave-One-Out marginal contribution & 24-neighbor bundle plateau."""
    _setup_cn_font()
    loo = [r for r in audit["loo_and_stepwise"] if r["mode"] == "LOO" and r["parent"] == "ALLIN_ROBUST"]
    loo_map = {r["action"]: r for r in loo}
    nb_rows = audit["redteam_plateau_pbo_liq_dsr"]["plateau_neighbors"]
    wf30 = {r["bundle"]: r for r in audit["key_bundles_wf_030"]}

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14.8, 6.2), dpi=180)
    fig.patch.set_facecolor("white")

    # Left panel: LOO marginal multiplier on ALLIN_ROBUST + TrigOnly false-signal contrast
    # Note for ALT_w2a6_TrigOnly_NoWait, compare vs DROP_w2a6_1to2S_All directly!
    trig_only_vs_drop = loo_map["ALT_w2a6_TrigOnly_NoWait"]["nav_wf"] / loo_map["DROP_w2a6_1to2S_All"]["nav_wf"]
    loo_items = [
        ("一进二仅触发提档", trig_only_vs_drop, loo_map["ALT_w2a6_TrigOnly_NoWait"]["sharpe_wf"] - loo_map["DROP_w2a6_1to2S_All"]["sharpe_wf"], "#ef4444"),
        ("弱红早盘换仓(0次)", loo_map["DROP_w2a5_WeakRed"]["marginal_nav_ratio_if_included"], loo_map["DROP_w2a5_WeakRed"]["marginal_sharpe_diff_if_included"], "#94a3b8"),
        ("一进二预约挂单(1次挡亏)", loo_map["DROP_w2a6_1to2S_All"]["marginal_nav_ratio_if_included"], loo_map["DROP_w2a6_1to2S_All"]["marginal_sharpe_diff_if_included"], "#f59e0b"),
        ("二进三冷清两两组合", loo_map["DROP_2to3_PairCold45"]["marginal_nav_ratio_if_included"], loo_map["DROP_2to3_PairCold45"]["marginal_sharpe_diff_if_included"], "#0284c7"),
        ("撬板冷清日跳过", loo_map["DROP_pry_upgrade"]["marginal_nav_ratio_if_included"], loo_map["DROP_pry_upgrade"]["marginal_sharpe_diff_if_included"], "#0ea5e9"),
        ("高标冷清删拖油瓶", loo_map["DROP_high_ColdDrop40"]["marginal_nav_ratio_if_included"], loo_map["DROP_high_ColdDrop40"]["marginal_sharpe_diff_if_included"], "#10b981"),
        ("三进四4因子排雷", loo_map["DROP_3to4_M4"]["marginal_nav_ratio_if_included"], loo_map["DROP_3to4_M4"]["marginal_sharpe_diff_if_included"], "#059669"),
        ("20cm三路均值", loo_map["DROP_20cm_to_base76"]["marginal_nav_ratio_if_included"], loo_map["DROP_20cm_to_base76"]["marginal_sharpe_diff_if_included"], "#15803d"),
    ]
    y1 = np.arange(len(loo_items))
    mvals = [(v - 1.0) * 100.0 for _, v, _, _ in loo_items]
    cols1 = [c for _, _, _, c in loo_items]
    ax1.barh(y1, mvals, color=cols1, height=0.58, alpha=0.92)
    ax1.axvline(0.0, color="#334155", linewidth=1.1)
    for idx, (_, mult, dsh, _) in enumerate(loo_items):
        pct = (mult - 1.0) * 100.0
        xpos = max(pct, 0.0) + 2.5
        lbl_str = f"{mult:.2f}倍 (纯触发反拖累-10.2%)" if mult < 1.0 else f"{mult:.2f}倍 (夏普{dsh:+.3f})"
        ax1.text(xpos, idx, lbl_str, va="center", ha="left", fontsize=8.4, fontweight="bold", color="#0f172a")
    ax1.set_yticks(y1)
    ax1.set_yticklabels([lbl for lbl, _, _, _ in loo_items], fontsize=9.3, fontweight="bold")
    ax1.set_xlabel("拔除该模块后对合体稳健包的净值贡献（%）", fontsize=9.5, fontweight="bold")
    ax1.set_title("逐项留一法拆解：真增厚主力 vs 零贡献/伪增厚组件", fontsize=11.5, fontweight="bold", pad=12)
    ax1.set_xlim(-22, 178)
    ax1.grid(axis="x", linestyle="--", alpha=0.35)

    # Right panel: 24-neighbor bundle plateau distribution vs V20 & static posthoc warning
    nb_sorted = sorted(nb_rows, key=lambda r: r["nav_wf"])
    x2 = np.arange(len(nb_sorted))
    nb_vals = [r["nav_wf"] / 1e4 for r in nb_sorted]
    ax2.bar(x2, nb_vals, color="#0ea5e9", width=0.72, alpha=0.88, label="24组邻域参数合体净值")
    base_v = wf30["BASE_V20_Unified"]["nav"] / 1e4
    med_v = audit["redteam_plateau_pbo_liq_dsr"]["plateau_summary"]["nav_wf_median"] / 1e4
    ax2.axhline(base_v, color="#ef4444", linestyle="--", linewidth=1.5, label=f"现役V20.0基准 ({base_v:.1f}万倍)")
    ax2.axhline(med_v, color="#15803d", linestyle=":", linewidth=1.5, label=f"24组邻域中位 ({med_v:.1f}万倍)")
    ax2.set_xticks([0, 5, 11, 17, 23])
    ax2.set_xticklabels(["最弱邻域\n(103.3万)", "第6名", "中位平台\n(256.7万)", "第18名", "最强邻域\n(355.7万)"], fontsize=8.5, fontweight="bold")
    ax2.set_ylabel("合体单仓滚动净值（万倍）", fontsize=9.5, fontweight="bold")
    ax2.set_title("24组跨策略邻域参数高原：100%跑赢现役基准且无单点孤岛", fontsize=11.5, fontweight="bold", pad=12)
    ax2.set_ylim(0, 430)
    ax2.grid(axis="y", linestyle="--", alpha=0.35)
    ax2.legend(loc="upper left", fontsize=8.5, frameon=True, facecolor="#f8fafc")

    ax2.text(
        0.03, 0.65,
        "静态事后对照陷阱警告：\n全部因果合体包最大回撤均守在 47.58%\n静态事后删因子对照回撤虚降至 31.12%\n实因偷看全样本删掉2025年初友好集团大亏",
        transform=ax2.transAxes, fontsize=8.3,
        bbox=dict(boxstyle="round,pad=0.45", facecolor="#fff7ed", edgecolor="#f97316", linewidth=1.0),
        color="#7c2d12",
    )

    plt.tight_layout(pad=2.0)
    out2 = f"{OUT_DIR}/rd038_chart2_loo_decomposition_and_forensics.png"
    fig.savefig(out2, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out2


def main():
    with open(AUDIT_JSON, encoding="utf-8") as f:
        audit = json.load(f)
    p1 = build_chart1(audit)
    p2 = build_chart2(audit)
    print(f"Generated charts:\n  1) {p1} ({os.path.getsize(p1)} bytes)\n  2) {p2} ({os.path.getsize(p2)} bytes)")


if __name__ == "__main__":
    main()

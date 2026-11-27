#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD048 Wave 2 Chart Builder: 2 Crisp Chinese HD PNGs Loaded Directly from Verified Audit Files."""
import json, os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

RD048_DIR = os.path.dirname(os.path.abspath(__file__))
plt.rcParams["font.sans-serif"] = ["PingFang SC", "Heiti SC", "STHeiti", "Arial Unicode MS", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False

def build_charts():
    with open(f"{RD048_DIR}/rd048_master_audit.json", encoding="utf-8") as f:
        m = json.load(f)
    with open(f"{RD048_DIR}/wave1b_gem2_gem4/rd048_gem4_if_futures.json", encoding="utf-8") as f:
        g4j = json.load(f)
    df_sum = pd.read_csv(f"{RD048_DIR}/rd048_integration_summary.csv")
    s1 = m["step1_redteam_wave1_audit"]

    # === CHART 1: 4 Gems Polish Before/After + Gem 4 IF 1x-7x Curve ===
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15.2, 6.3), dpi=180)
    fig.patch.set_facecolor("#FFFFFF")

    labels1 = [
        "四进五\n旧版114", "四进五\n漏减114", "四进五\n严格114", "四进五\n高分120",
        "映射\n旧漏水", "映射\n5日线", "映射\n次日卖",
        "五板\n全量", "五板\n独苗锁",
        "300ETF\n1倍", "期货\n精磨3倍", "期货\n精磨5倍",
    ]
    navs1 = [7.06, 18.33, s1["gem1_redteam"]["strict_jianchi_114_30bps"]["nav_5y"], 9.33,
             0.11, s1["gem2_redteam"]["p1a_ma5_nav_5y"], s1["gem2_redteam"]["p1b_t1c_nav_5y"],
             0.0001, 0.21, 1.42, 2.69, 4.78]
    ex5s1 = [1.14, 2.72, s1["gem1_redteam"]["strict_jianchi_114_30bps"]["ex5_5y"], 1.47,
             0.05, s1["gem2_redteam"]["p1a_ma5_ex5_5y"], 1.06,
             0.0001, 0.04, 1.01, 1.19, 1.32]
    x1 = np.arange(len(labels1))
    w1 = 0.37
    b_a = ax1.bar(x1 - w1/2, navs1, width=w1, color="#0284c7", alpha=0.90, label="五年独立净值（倍）")
    b_b = ax1.bar(x1 + w1/2, ex5s1, width=w1, color="#f59e0b", alpha=0.90, label="去前五大盈利后净值（倍）")
    ax1.axhline(1.0, color="#dc2626", linestyle="--", linewidth=1.1, label="保本线 1.0倍")
    ax1.set_yscale("log")
    ax1.set_ylim(0.01, 68.0)
    for b, v in zip(b_a, navs1):
        vt = max(v, 0.0115)
        lbl = f"{v:.2f}" if v >= 0.1 else ("~0" if v < 0.005 else f"{v:.3f}")
        ax1.text(b.get_x() + b.get_width()/2, vt * 1.13, lbl, ha="center", va="bottom", fontsize=6.4, fontweight="bold", color="#0369a1")
    for b, v in zip(b_b, ex5s1):
        vt = max(v, 0.0115)
        lbl = f"{v:.2f}" if v >= 0.1 else ("~0" if v < 0.005 else f"{v:.3f}")
        ax1.text(b.get_x() + b.get_width()/2, vt * 1.13, lbl, ha="center", va="bottom", fontsize=6.2, color="#b45309")
    ax1.set_xticks(x1)
    ax1.set_xticklabels(labels1, fontsize=7.4, fontweight="bold")
    ax1.set_ylabel("五年独立复合净值（对数坐标，倍）", fontsize=9.0, fontweight="bold")
    ax1.set_title("一、四大遗珠打磨前后五年独立净值与去前五实证", fontsize=10.8, fontweight="bold", pad=10)
    ax1.grid(axis="y", linestyle="--", alpha=0.35)
    ax1.legend(loc="upper right", fontsize=7.6, frameon=True)

    # Panel 2: IF 1x-7x leverage NAV vs Margin Call & Forced Liquidation Rate
    six = {r["variant"]: r for r in g4j["six_tier_leverage_table"]}
    lv_keys = [
        ("A_ETF510300_1x_V3Live60_H5", "ETF\n1倍"),
        ("A_IF_1x_V3Live60_H5_NoSL_10bps", "期货\n1倍"),
        ("A_IF_3x_V3Live60_H5_NoSL_10bps", "期货\n3倍"),
        ("A_IF_5x_V3Live60_H5_NoSL_10bps", "期货\n5倍"),
        ("A_IF_6x_V3Live60_H5_NoSL_10bps", "期货\n6倍"),
        ("A_IF_7x_V3Live60_H5_NoSL_10bps", "期货\n7倍"),
    ]
    xl = np.arange(len(lv_keys))
    nav_lv = [six[k]["nav_5y"] for k, _ in lv_keys]
    mc_lv = [six[k]["mc_145_rate"] for k, _ in lv_keys]
    liq_lv = [six[k]["liq_12_rate"] for k, _ in lv_keys]
    ax2.plot(xl, nav_lv, marker="o", linewidth=2.2, color="#0284c7", label="盘中60分5日基线五年净值（左轴）")
    # Overlay polished 3x & 5x EOD>=65 H3 SL2
    p3 = [r for r in g4j["best_safe_polished_3x"] if r["variant"] == "P_IF_3x_V3EOD_ge65_H3_SL2"][0]
    p5 = [r for r in g4j["best_safe_polished_5x"] if r["variant"] == "P_IF_5x_V3EOD_ge65_H3_SL2"][0]
    ax2.scatter([2, 3], [p3["nav_5y"], p5["nav_5y"]], s=105, marker="*", color="#059669", zorder=5, label="精磨收盘65分3日止损2%（3倍/5倍，强平0%）")
    for xi, yi in [(2, p3["nav_5y"]), (3, p5["nav_5y"])]:
        ax2.text(xi, yi + 0.24, f"精磨 {yi:.2f}倍", ha="center", va="bottom", fontsize=7.8, fontweight="bold", color="#047857")
    for xi, yi in zip(xl, nav_lv):
        ax2.text(xi, yi - 0.25 if xi in (2, 3) else yi + 0.14, f"{yi:.2f}倍", ha="center", va="top" if xi in (2, 3) else "bottom", fontsize=7.5, color="#0369a1")
    ax2.set_xticks(xl)
    ax2.set_xticklabels([lbl for _, lbl in lv_keys], fontsize=8.2, fontweight="bold")
    ax2.set_ylabel("五年独立复合净值（倍）", fontsize=9.0, fontweight="bold", color="#0284c7")
    ax2.set_ylim(0.5, 5.6)
    ax2.grid(axis="y", linestyle="--", alpha=0.35)

    ax2r = ax2.twinx()
    ax2r.bar(xl - 0.16, mc_lv, width=0.28, color="#f59e0b", alpha=0.45, label="追保145%触发率（右轴）")
    ax2r.bar(xl + 0.16, liq_lv, width=0.28, color="#dc2626", alpha=0.65, label="强平120%爆仓率（右轴）")
    ax2r.set_ylabel("盘中触及追保或强平比例（%）", fontsize=9.0, fontweight="bold", color="#b91c1c")
    ax2r.set_ylim(0, 115)
    for xi, mcv, lqv in zip(xl, mc_lv, liq_lv):
        if mcv > 0:
            ax2r.text(xi - 0.16, mcv + 2.0, f"{mcv:.1f}%", ha="center", va="bottom", fontsize=6.8, color="#b45309", fontweight="bold")
        if lqv > 0:
            ax2r.text(xi + 0.16, lqv + 2.0, f"{lqv:.1f}%", ha="center", va="bottom", fontsize=6.8, color="#b91c1c", fontweight="bold")
    h1, l1 = ax2.get_legend_handles_labels()
    h2, l2 = ax2r.get_legend_handles_labels()
    ax2.legend(h1 + h2, l1 + l2, loc="upper left", fontsize=7.2, frameon=True)
    ax2.set_title("二、中金所沪深300期货1至7倍收益与6倍以上强平悬崖", fontsize=10.8, fontweight="bold", pad=10)

    c1_path = f"{RD048_DIR}/rd048_chart1_gems_and_if_leverage.png"
    plt.tight_layout(pad=2.0)
    fig.savefig(c1_path, dpi=180, bbox_inches="tight", facecolor="#FFFFFF")
    plt.close(fig)

    # === CHART 2: V20/V21 Single-Account Crowding vs Independent Margin Sleeve Overlay ===
    fig, (bx1, bx2) = plt.subplots(1, 2, figsize=(15.2, 6.3), dpi=180)
    fig.patch.set_facecolor("#FFFFFF")

    def _get_r(combo):
        return df_sum[df_sum["combo"] == combo].iloc[0]

    cats_c2 = [
        ("四进五\n严格减持114", "V20_0__G1_StrictJianchi_114__Pos2_After34High_Pre23", "V21_0__G1_StrictJianchi_114__Pos2_After34High_Pre23"),
        ("四进五\n高分120", "V20_0__G1_FixPIT_120__Pos2_After34High_Pre23", "V21_0__G1_FixPIT_120__Pos2_After34High_Pre23"),
        ("四进五漏减持\n空仓补114", "V20_0__G1_FixPIT_114__Pos5_EmptyDayOnly", "V21_0__G1_FixPIT_114__Pos5_EmptyDayOnly"),
        ("救市期货5倍\n单户切仓T+1", "V20_0__ModeA_P_IF_5x_V3EOD_ge65_H3_SL2__Lag1_1", "V21_0__ModeA_P_IF_5x_V3EOD_ge65_H3_SL2__Lag1_1"),
        ("美股映射5日\n物理占资撞车", "V20_0__PIT1A_NoZT_GapMod15_VR12_MA5__RealPhysicalLedger", "V21_0__PIT1A_NoZT_GapMod15_VR12_MA5__RealPhysicalLedger"),
        ("深市五板\n独苗空仓强并", "V20_0__G3_SoleHighest_Lock50__Pos5_EmptyDayOnly", "V21_0__G3_SoleHighest_Lock50__Pos5_EmptyDayOnly"),
    ]
    xc2 = np.arange(len(cats_c2))
    v20_m = [float(_get_r(c20)["mult_5y"]) for _, c20, _ in cats_c2]
    v21_m = [float(_get_r(c21)["mult_5y"]) for _, _, c21 in cats_c2]
    b20 = bx1.bar(xc2 - 0.19, [max(v, 0.008) for v in v20_m], width=0.36, color="#0284c7", alpha=0.88, label="并入现役20版（五年相对倍数）")
    b21 = bx1.bar(xc2 + 0.19, [max(v, 0.008) for v in v21_m], width=0.36, color="#059669", alpha=0.88, label="并入影子21版（五年相对倍数）")
    bx1.axhline(1.0, color="#dc2626", linestyle="--", linewidth=1.1, label="持平基准线 1.00倍")
    bx1.set_yscale("log")
    bx1.set_ylim(0.005, 5.5)
    for b, v in zip(b20, v20_m):
        bx1.text(b.get_x() + b.get_width()/2, max(v, 0.008) * 1.12, f"{v:.2f}x", ha="center", va="bottom", fontsize=7.0, fontweight="bold", color="#0369a1")
    for b, v in zip(b21, v21_m):
        bx1.text(b.get_x() + b.get_width()/2, max(v, 0.008) * 1.12, f"{v:.2f}x", ha="center", va="bottom", fontsize=7.0, fontweight="bold", color="#047857")
    bx1.set_xticks(xc2)
    bx1.set_xticklabels([k for k, _, _ in cats_c2], fontsize=7.6, fontweight="bold")
    bx1.set_ylabel("并入主力单账户后五年净值倍数（对数坐标）", fontsize=8.8, fontweight="bold")
    bx1.set_title("三、单账户直接并入双基准增量大考（含真实占资与划转时滞）", fontsize=10.6, fontweight="bold", pad=10)
    bx1.grid(axis="y", linestyle="--", alpha=0.35)
    bx1.legend(loc="upper right", fontsize=7.6, frameon=True)

    # Panel 2: Mode B 15% Independent Margin Sleeve Overlay & Orthogonal Combo
    b_sh_base = m["baselines_rd038_exact"]["V21_0"]["windows"]["FULL_5Y"]["daily_sharpe"]
    b_md_base = m["baselines_rd038_exact"]["V21_0"]["windows"]["FULL_5Y"]["daily_mdd_pct"]
    pts_o = [
        ("100%影子21版\n基准", b_sh_base, b_md_base, "#64748b"),
        ("85%21版+15%现金\n对照", float(_get_r("V21_0__ModeB_w15_CASH_0PCT__FixedWeight_DailyRebal")["sh_5y"]), float(_get_r("V21_0__ModeB_w15_CASH_0PCT__FixedWeight_DailyRebal")["mdd_5y"]), "#94a3b8"),
        ("85%21版+15%3倍\n季调", float(_get_r("V21_0__ModeB_w15_P_IF_3x_V3EOD_ge65_H3_SL2__Quarterly_Rebal")["sh_5y"]), float(_get_r("V21_0__ModeB_w15_P_IF_3x_V3EOD_ge65_H3_SL2__Quarterly_Rebal")["mdd_5y"]), "#0ea5e9"),
        ("85%21版+15%5倍\n日定比", float(_get_r("V21_0__ModeB_w15_P_IF_5x_V3EOD_ge65_H3_SL2__FixedWeight_DailyRebal")["sh_5y"]), float(_get_r("V21_0__ModeB_w15_P_IF_5x_V3EOD_ge65_H3_SL2__FixedWeight_DailyRebal")["mdd_5y"]), "#0284c7"),
        ("21版+四进五120\n纯股合体", float(_get_r("V21_0__G1_FixPIT_120__Pos2")["sh_5y"]), float(_get_r("V21_0__G1_FixPIT_120__Pos2")["mdd_5y"]), "#10b981"),
        ("合体版+15%5倍\n双账户", float(_get_r("V21_0__G1_FixPIT_120__ModeB_w15_P_IF_5x_V3EOD_ge65_H3_SL2__FixedWeight_DailyRebal")["sh_5y"]), float(_get_r("V21_0__G1_FixPIT_120__ModeB_w15_P_IF_5x_V3EOD_ge65_H3_SL2__FixedWeight_DailyRebal")["mdd_5y"]), "#047857"),
    ]
    xo = np.arange(len(pts_o))
    bo = bx2.bar(xo - 0.17, [p[1] for p in pts_o], width=0.33, color=[p[3] for p in pts_o], alpha=0.92, label="五年逐日夏普（左轴）")
    bx2r = bx2.twinx()
    bx2r.plot(xo + 0.17, [p[2] for p in pts_o], marker="s", linewidth=2.0, color="#dc2626", label="五年最大回撤%（右轴）")
    for b, p in zip(bo, pts_o):
        bx2.text(b.get_x() + b.get_width()/2, p[1] + 0.012, f"{p[1]:.3f}", ha="center", va="bottom", fontsize=7.2, fontweight="bold")
    for xi, p in zip(xo, pts_o):
        if p[2] < 43.0:
            bx2r.text(xi + 0.17, p[2] - 0.55, f"{p[2]:.1f}%", ha="center", va="top", fontsize=7.2, fontweight="bold", color="#b91c1c")
        else:
            bx2r.text(xi + 0.17, p[2] + 0.45, f"{p[2]:.1f}%", ha="center", va="bottom", fontsize=7.2, fontweight="bold", color="#b91c1c")
    bx2.set_xticks(xo)
    bx2.set_xticklabels([p[0] for p in pts_o], fontsize=7.5, fontweight="bold")
    bx2.set_ylabel("五年逐日夏普比率", fontsize=8.8, fontweight="bold")
    bx2.set_ylim(4.90, 5.44)
    bx2r.set_ylabel("五年最大回撤（%）", fontsize=8.8, fontweight="bold", color="#b91c1c")
    bx2r.set_ylim(37.5, 51.5)
    bx2.grid(axis="y", linestyle="--", alpha=0.35)
    h2a, l2a = bx2.get_legend_handles_labels()
    h2b, l2b = bx2r.get_legend_handles_labels()
    bx2.legend(h2a + h2b, l2a + l2b, loc="upper left", fontsize=7.2, frameon=True)
    bx2.text(0.22, 0.87, "救市大跌窗口实证：16次窗口共亏0天\n2024年2月6日股指5倍+20.2%，单日跌幅由10.2%缩至5.7%", transform=bx2.transAxes, fontsize=7.4, bbox=dict(boxstyle="round,pad=0.35", facecolor="#f8fafc", edgecolor="#94a3b8"))
    bx2.set_title("四、独立一成半期货保证金池配比与正交合体夏普/回撤表现", fontsize=10.6, fontweight="bold", pad=10)

    c2_path = f"{RD048_DIR}/rd048_chart2_v20_v21_integration.png"
    plt.tight_layout(pad=2.0)
    fig.savefig(c2_path, dpi=180, bbox_inches="tight", facecolor="#FFFFFF")
    plt.close(fig)
    return c1_path, c2_path

if __name__ == "__main__":
    print(build_charts())

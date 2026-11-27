#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD049 Step 3: Generate 2 Crisp Pure-Chinese 2x2 Charts + Dry-Run Validate & Publish
Strict Plain-Chinese Feishu Report (`满仓降回撤与两融实证`) to Valid Library & Hub.
Zero yfinance (D12). Zero edits to V20.0/V21.0 production scripts.
"""
import argparse
import fcntl
import json
import os
import re
import sys
import time
import warnings

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
RD049_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd049_traffic_light_granular_20261126"
CACHE_DIR = f"{RD049_DIR}/_cache"
RD041_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd041_day0_firstboard_sweep_20261126"
FS_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/feishu_master_docs_20261116"

for p in (RD049_DIR, RD041_DIR, FS_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import _rd041_feishu_helpers as fh
import step6_upgrade_3strategies_20261117 as s6
import step9_sync_v191_exits_20261118 as s9

TITLE = "满仓降回撤与两融实证"
HUB_ROW = [
    "满仓降回撤与两融实证",
    "5年277笔+603对两融实查",
    "满仓下5年回撤47.58%压至28.80%,两融实占53%",
    "弱市抬高三进四门槛加助攻,红灯地板照做",
]

CHART1_PATH = f"{RD049_DIR}/rd049_chart1_regime_dd_and_nav.png"
CHART2_PATH = f"{RD049_DIR}/rd049_chart2_margin_15x_and_robustness.png"

C, T, B, BL, MIXED = fh.C, fh.T, fh.B, fh.BL, fh.MIXED

plt.rcParams["font.sans-serif"] = ["PingFang SC", "Hiragino Sans GB", "STHeiti", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

FORBIDDEN_EXTRA = [
    "WF", "OOS", "IS", "PIT", "BH", "FDR", "DSR", "CSCV", "PBO", "LOO", "MTM",
    "Sharpe", "Calmar", "MDD", "NAV", "PLR", "KPL", "CSRC", "bps", "GBDT", "ANOVA",
    "t值", "p值", "q值", "消融", "门禁", "闭环", "矩阵", "铁证", "重锚", "回灌",
    "王牌", "天花板", "RD038", "RD049", "R2D", "R_union", "MMR", "af03", "s34",
]


def build_charts(audit: dict) -> tuple[str, str]:
    npz = np.load(f"{CACHE_DIR}/rd049_curves.npz")
    cal_dts = pd.to_datetime([str(d) for d in npz["cal_5y"]])
    grid_df = pd.read_csv(f"{RD049_DIR}/rd049_grid.csv")
    margin_df = pd.read_csv(f"{RD049_DIR}/rd049_margin_15x_audit.csv")

    # === CHART 1: 2x2 Regime & Drawdown Compression ===
    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(15.8, 10.2), dpi=180)
    fig.patch.set_facecolor("#FFFFFF")

    # Panel 1: 5Y Log NAV Comparison
    s_v21_base = npz["V21_BASE_1x"]
    s_v21_s3 = npz["V21_S3_RD049_Tier_Full_1x"]
    s_v21_s4 = npz["V21_S4_RD049_R2D_Full_1x"]
    s_v20_base = npz["V20_BASE_1x"]
    s_v20_s4 = npz["V20_S4_RD049_R2D_Full_1x"]

    for arr, lbl, col, ls, lw in [
        (s_v21_s4, "V21二维状态机 (9.20亿倍, 回撤28.80%)", "#dc2626", "-", 2.2),
        (s_v21_s3, "V21五档灯色版 (8.09亿倍, 回撤28.80%)", "#0284c7", "--", 1.9),
        (s_v21_base, "V21原版基线 (2.81亿倍, 回撤47.58%)", "#64748b", ":", 1.8),
        (s_v20_s4, "V20二维状态机 (1.80亿倍, 回撤29.08%)", "#059669", "-.", 1.8),
        (s_v20_base, "V20原版基线 (0.57亿倍, 回撤47.58%)", "#94a3b8", ":", 1.4),
    ]:
        nav = np.cumprod(1.0 + arr)
        ax1.plot(cal_dts, nav, label=lbl, color=col, linestyle=ls, linewidth=lw)
    ax1.set_yscale("log")
    ax1.set_title("一、满仓五年对数净值走势：不降仓位净值翻至三倍以上", fontsize=10.8, fontweight="bold", pad=10)
    ax1.set_ylabel("五年累计净值（对数坐标，倍）", fontsize=9.2, fontweight="bold")
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%y/%m"))
    ax1.grid(True, linestyle="--", alpha=0.35)
    ax1.legend(loc="upper left", fontsize=7.6, frameon=True)

    # Panel 2: Underwater Drawdown Curve
    for arr, lbl, col, ls, lw in [
        (s_v21_base, "V21原版基线 (最大47.58%)", "#64748b", ":", 1.7),
        (s_v21_s4, "V21二维状态机 (最大28.80%, 24至26仅20.46%)", "#dc2626", "-", 2.0),
        (s_v20_s4, "V20二维状态机 (最大29.08%)", "#059669", "--", 1.5),
    ]:
        nav = np.cumprod(1.0 + arr)
        pk = np.maximum.accumulate(np.concatenate([[1.0], nav]))[1:]
        dd = -(pk - nav) / pk * 100.0
        ax2.plot(cal_dts, dd, label=lbl, color=col, linestyle=ls, linewidth=lw)
    ax2.axhline(-30.0, color="#d97706", linestyle="--", linewidth=1.1, label="目标防线 -30%")
    ax2.annotate("22.07 法尔胜/大港\n基线-35.3%->-24.8%", xy=(pd.Timestamp("2022-07-29"), -35.29),
                 xytext=(pd.Timestamp("2022-10-05"), -41.5), fontsize=7.5, fontweight="bold", color="#0f172a",
                 arrowprops=dict(arrowstyle="->", color="#475569", lw=1.0),
                 bbox=dict(boxstyle="round,pad=0.22", facecolor="#f8fafc", edgecolor="#cbd5e1"))
    ax2.annotate("24.12至25.01 鼎信+友好\n基线-47.58%->彻底避开", xy=(pd.Timestamp("2025-01-06"), -47.58),
                 xytext=(pd.Timestamp("2023-05-15"), -47.2), fontsize=7.5, fontweight="bold", color="#dc2626",
                 arrowprops=dict(arrowstyle="->", color="#dc2626", lw=1.0),
                 bbox=dict(boxstyle="round,pad=0.22", facecolor="#fef2f2", edgecolor="#fca5a5"))
    ax2.set_title("二、动态水下回撤曲线：削平双坑把五年回撤压入三成内", fontsize=10.8, fontweight="bold", pad=10)
    ax2.set_ylabel("回撤幅度（%）", fontsize=9.2, fontweight="bold")
    ax2.set_ylim(-54, 3)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%y/%m"))
    ax2.grid(True, linestyle="--", alpha=0.35)
    ax2.legend(loc="lower right", fontsize=7.4, frameon=True)

    # Panel 3: 6 Strategies x 5 Traffic Lights Heatmap
    st_list = ["3to4", "high", "pry", "2to3", "1to2", "20cm"]
    st_cn = ["三进四", "高标首阴", "跌停撬板", "二进三", "一进二", "20cm首板"]
    l5_list = ["L1_纯绿畅通", "L2_绿灯内杀", "L3_浅黄预警", "L4_深黄主跌", "L5_红灯地板"]
    l5_cn = ["纯绿畅通", "绿灯内杀", "浅黄预警", "深黄主跌", "红灯地板"]
    tbl_df = pd.DataFrame(audit["strategy_x_light5_table"])
    mat_mn = np.full((len(st_list), len(l5_list)), np.nan)
    mat_n = np.zeros((len(st_list), len(l5_list)), dtype=int)
    for i_s, st in enumerate(st_list):
        for j_l, l5 in enumerate(l5_list):
            sub = tbl_df[(tbl_df["strategy"] == st) & (tbl_df["light_5"] == l5)]
            if not sub.empty and int(sub.iloc[0]["n_all"]) > 0:
                mat_mn[i_s, j_l] = float(sub.iloc[0]["mean_all"])
                mat_n[i_s, j_l] = int(sub.iloc[0]["n_all"])

    cmap = plt.cm.RdYlGn
    cmap.set_bad(color="#f1f5f9")
    im = ax3.imshow(mat_mn, cmap=cmap, vmin=-6.0, vmax=20.0, aspect="auto")
    ax3.set_xticks(np.arange(len(l5_cn)))
    ax3.set_xticklabels(l5_cn, fontsize=8.8, fontweight="bold")
    ax3.set_yticks(np.arange(len(st_cn)))
    ax3.set_yticklabels(st_cn, fontsize=8.8, fontweight="bold")
    for i_s in range(len(st_list)):
        for j_l in range(len(l5_list)):
            if mat_n[i_s, j_l] == 0:
                ax3.text(j_l, i_s, "无样本", ha="center", va="center", fontsize=7.6, color="#64748b")
            else:
                v = mat_mn[i_s, j_l]
                tc = "#ffffff" if (v <= -2.0 or v >= 16.0) else "#0f172a"
                ax3.text(j_l, i_s, f"{v:+.1f}%\n({mat_n[i_s,j_l]}笔)", ha="center", va="center", fontsize=7.8, fontweight="bold", color=tc)
    ax3.set_title("三、六大策略分五档灯色单笔均值：红灯地板暴赚、弱黄专杀三进四", fontsize=10.6, fontweight="bold", pad=10)

    # Panel 4: De-Singleton & IS/OOS Bar Comparison
    cats = ["V21基线", "V21五档版", "V21二维版", "V20基线", "V20二维版"]
    m_keys = [("V21", "BASE"), ("V21", "S3_RD049_Tier_Full"), ("V21", "S4_RD049_R2D_Full"), ("V20", "BASE"), ("V20", "S4_RD049_R2D_Full")]
    v_5y, v_oos, v_ds = [], [], []
    for bs, vr in m_keys:
        r = grid_df[(grid_df["base_sys"] == bs) & (grid_df["variant"] == vr)].iloc[0]
        v_5y.append(float(r["FULL_5Y_mdd_pct"]))
        v_oos.append(float(r["OOS_2426_mdd_pct"]))
        v_ds.append(float(r["DS_FULL_5Y_mdd"]))
    x4 = np.arange(len(cats))
    w4 = 0.25
    b1 = ax4.bar(x4 - w4, v_5y, width=w4, color="#dc2626", alpha=0.88, label="全5年最大回撤")
    b2 = ax4.bar(x4, v_oos, width=w4, color="#0284c7", alpha=0.88, label="样本外24至26回撤")
    b3 = ax4.bar(x4 + w4, v_ds, width=w4, color="#059669", alpha=0.88, label="去友好与鼎信后回撤")
    for bars in (b1, b2, b3):
        for b in bars:
            h = b.get_height()
            ax4.text(b.get_x() + b.get_width() / 2, h + 0.7, f"{h:.1f}%", ha="center", va="bottom", fontsize=7.0, fontweight="bold")
    ax4.axhline(30.0, color="#d97706", linestyle="--", linewidth=1.1, label="30%目标上限")
    ax4.set_xticks(x4)
    ax4.set_xticklabels(cats, fontsize=8.6, fontweight="bold")
    ax4.set_ylabel("最大回撤（%）", fontsize=9.2, fontweight="bold")
    ax4.set_ylim(0, 56)
    ax4.set_title("四、双期与去孤例严审：剔除友好集团与鼎信通讯后仍净降回撤", fontsize=10.6, fontweight="bold", pad=10)
    ax4.grid(axis="y", linestyle="--", alpha=0.35)
    ax4.legend(loc="upper right", fontsize=7.4, frameon=True, ncol=2)

    plt.tight_layout(pad=2.0)
    fig.savefig(CHART1_PATH, dpi=180, bbox_inches="tight", facecolor="#FFFFFF")
    plt.close(fig)

    # === CHART 2: 2x2 Margin 1.5x, Eligibility, MMR Safety, & Parameter Plateau ===
    fig, ((bx1, bx2), (bx3, bx4)) = plt.subplots(2, 2, figsize=(15.8, 10.2), dpi=180)
    fig.patch.set_facecolor("#FFFFFF")

    # Panel 1: 1.0x vs 1.5x EligOnly vs 1.5x TheoFull (MaxDD & Calmar)
    m_lbls = ["V21基线\n1.0倍", "V21基线\n1.5倍全融", "V21二维\n1.0倍", "V21二维\n1.5倍可融", "V21二维\n1.5倍全融", "V20二维\n1.5倍可融"]
    m_pairs = [
        ("V21_BASE", "1.0x_Cash"), ("V21_BASE", "1.5x_TheoFull"),
        ("V21_S4_RD049_R2D_Full", "1.0x_Cash"), ("V21_S4_RD049_R2D_Full", "1.5x_EligOnly"),
        ("V21_S4_RD049_R2D_Full", "1.5x_TheoFull"), ("V20_S4_RD049_R2D_Full", "1.5x_EligOnly"),
    ]
    mdds_m, mdds_3y, cals_m = [], [], []
    for mk, lm in m_pairs:
        rw = margin_df[(margin_df["model"] == mk) & (margin_df["leverage_mode"] == lm)].iloc[0]
        mdds_m.append(float(rw["5Y_mdd"]))
        mdds_3y.append(float(rw["3Y_mdd"]))
        cals_m.append(float(rw["5Y_calmar"]))
    xb1 = np.arange(len(m_lbls))
    wb1 = 0.34
    mb1 = bx1.bar(xb1 - wb1 / 2, mdds_m, width=wb1, color="#dc2626", alpha=0.88, label="5年最大回撤(%)")
    mb2 = bx1.bar(xb1 + wb1 / 2, mdds_3y, width=wb1, color="#0284c7", alpha=0.88, label="近3年最大回撤(%)")
    for i_m, (b_a, b_b, cal_v) in enumerate(zip(mb1, mb2, cals_m)):
        bx1.text(b_a.get_x() + b_a.get_width() / 2, b_a.get_height() + 0.9, f"{b_a.get_height():.1f}%", ha="center", va="bottom", fontsize=7.2, fontweight="bold")
        bx1.text(b_b.get_x() + b_b.get_width() / 2, b_b.get_height() + 0.9, f"{b_b.get_height():.1f}%\n卡{cal_v:.0f}", ha="center", va="bottom", fontsize=6.8, fontweight="bold", color="#0369a1")
    bx1.set_xticks(xb1)
    bx1.set_xticklabels(m_lbls, fontsize=8.0, fontweight="bold")
    bx1.set_ylabel("最大回撤（%）", fontsize=9.2, fontweight="bold")
    bx1.set_ylim(0, 74)
    bx1.set_title("五、1.5倍两融实战实测（扣5.5%年化息）：基线63.8%爆坑被压至28.8%/41.1%", fontsize=10.4, fontweight="bold", pad=10)
    bx1.grid(axis="y", linestyle="--", alpha=0.35)
    bx1.legend(loc="upper right", fontsize=7.8, frameon=True)

    # Panel 2: Historical Margin Eligibility by Year & By Strategy (from actual cache)
    # Read exact yearly/strategy eligibility on V21_S4 trades via audit/cache
    mc = json.load(open(f"{CACHE_DIR}/rd049_margin_eligibility_cache.json", encoding="utf-8"))
    # Recompute exact V21_BASE yearly & strategy eligibility from V21_S4 / V21_BASE in audit
    elig_s4 = audit["margin_15x_audit"]["V21_S4_RD049_R2D_Full"]["elig_stats"]
    elig_v21 = audit["margin_15x_audit"]["V21_BASE"]["elig_stats"]
    st_keys = ["20cm", "high", "1to2", "3to4", "2to3", "pry"]
    st_names = ["20cm首板", "高标首阴", "一进二", "三进四", "二进三", "跌停撬板"]
    st_vals_s4 = [elig_s4["by_strat"].get(k, 0.0) for k in st_keys]
    st_vals_base = [elig_v21["by_strat"].get(k, 0.0) for k in st_keys]
    xb2 = np.arange(len(st_names))
    wb2 = 0.35
    eb1 = bx2.bar(xb2 - wb2 / 2, st_vals_base, width=wb2, color="#64748b", alpha=0.85, label=f"V21基线 (5年{elig_v21['elig_5y_pct']:.1f}%/26年{elig_v21['elig_2026_pct']:.1f}%)")
    eb2 = bx2.bar(xb2 + wb2 / 2, st_vals_s4, width=wb2, color="#059669", alpha=0.88, label=f"V21二维 (5年{elig_s4['elig_5y_pct']:.1f}%/26年{elig_s4['elig_2026_pct']:.1f}%)")
    for b in list(eb1) + list(eb2):
        bx2.text(b.get_x() + b.get_width() / 2, b.get_height() + 1.2, f"{b.get_height():.1f}%", ha="center", va="bottom", fontsize=7.2, fontweight="bold")
    bx2.set_xticks(xb2)
    bx2.set_xticklabels(st_names, fontsize=8.4, fontweight="bold")
    bx2.set_ylabel("买入日前官方合法两融占比（%）", fontsize=9.0, fontweight="bold")
    bx2.set_ylim(0, 86)
    bx2.set_title("六、官方沪深清单真实两融资格率：全周期半数可融，2026年升至67%", fontsize=10.4, fontweight="bold", pad=10)
    bx2.grid(axis="y", linestyle="--", alpha=0.35)
    bx2.legend(loc="upper right", fontsize=7.6, frameon=True)

    # Panel 3: Maintenance Margin Ratio (MMR) Safety Margin
    # Compare min_mmr across models
    mmr_cats = ["V21基线\n1.5倍全融", "V21二维\n1.5倍全融", "V21二维\n1.5倍可融", "V20二维\n1.5倍可融"]
    mmr_vals = [
        float(margin_df[(margin_df["model"] == "V21_BASE") & (margin_df["leverage_mode"] == "1.5x_TheoFull")].iloc[0]["min_mmr_pct"]),
        float(margin_df[(margin_df["model"] == "V21_S4_RD049_R2D_Full") & (margin_df["leverage_mode"] == "1.5x_TheoFull")].iloc[0]["min_mmr_pct"]),
        float(margin_df[(margin_df["model"] == "V21_S4_RD049_R2D_Full") & (margin_df["leverage_mode"] == "1.5x_EligOnly")].iloc[0]["min_mmr_pct"]),
        float(margin_df[(margin_df["model"] == "V20_S4_RD049_R2D_Full") & (margin_df["leverage_mode"] == "1.5x_EligOnly")].iloc[0]["min_mmr_pct"]),
    ]
    xb3 = np.arange(len(mmr_cats))
    cols_mmr = ["#d97706", "#0284c7", "#059669", "#0d9488"]
    bars3 = bx3.bar(xb3, mmr_vals, width=0.48, color=cols_mmr, alpha=0.88)
    for b, v in zip(bars3, mmr_vals):
        bx3.text(b.get_x() + b.get_width() / 2, v + 4.0, f"最低 {v:.1f}%", ha="center", va="bottom", fontsize=8.2, fontweight="bold")
    bx3.axhline(300.0, color="#059669", linestyle=":", linewidth=1.2, label="1.5倍开仓初始维保比 300%")
    bx3.axhline(150.0, color="#d97706", linestyle="--", linewidth=1.3, label="券商追保警戒线 150% (0次触及)")
    bx3.axhline(130.0, color="#dc2626", linestyle="-.", linewidth=1.3, label="强行平仓线 130% (0次触及)")
    bx3.set_xticks(xb3)
    bx3.set_xticklabels(mmr_cats, fontsize=8.4, fontweight="bold")
    bx3.set_ylabel("持仓全程盘中最低维保比（%）", fontsize=9.0, fontweight="bold")
    bx3.set_ylim(100, 335)
    bx3.set_title("七、逐日盘中最低价维保比实查：全程零触警戒线（最低230%至256%）", fontsize=10.4, fontweight="bold", pad=10)
    bx3.grid(axis="y", linestyle="--", alpha=0.35)
    bx3.legend(loc="lower right", fontsize=7.6, frameon=True)

    # Panel 4: Parameter Plateau Heatmap (R_union 3 x 3 for raf=45 & Tier 3x3 for yc=42)
    r2d_rows = pd.DataFrame(audit["plateau_r2d_18pts"]["rows"])
    sub_p = r2d_rows[r2d_rows["raf"] == 45.0]
    r0s = [34.0, 38.0, 42.0]
    rks = [10.0, 12.0, 14.0]
    mat_sh = np.zeros((len(r0s), len(rks)))
    mat_md = np.zeros((len(r0s), len(rks)))
    for i0, rv in enumerate(r0s):
        for j0, kv in enumerate(rks):
            s = sub_p[(sub_p["r0"] == rv) & (sub_p["rk"] == kv)].iloc[0]
            mat_sh[i0, j0] = float(s["sh_5y"])
            mat_md[i0, j0] = float(s["mdd_5y"])
    im4 = bx4.imshow(mat_sh, cmap="YlGn", vmin=5.15, vmax=5.68, aspect="auto")
    bx4.set_xticks(np.arange(len(rks)))
    bx4.set_xticklabels([f"提分斜率+{int(k)}" for k in rks], fontsize=8.8, fontweight="bold")
    bx4.set_yticks(np.arange(len(r0s)))
    bx4.set_yticklabels([f"起跳风险{int(r)}" for r in r0s], fontsize=8.8, fontweight="bold")
    for i0 in range(len(r0s)):
        for j0 in range(len(rks)):
            bx4.text(j0, i0, f"回撤 {mat_md[i0,j0]:.2f}%\n夏普 {mat_sh[i0,j0]:.3f}", ha="center", va="center", fontsize=8.4, fontweight="bold", color="#0f172a")
    bx4.set_title("八、参数邻域高原检验：五档27组与二维18组全部稳居28.80%回撤", fontsize=10.4, fontweight="bold", pad=10)

    plt.tight_layout(pad=2.0)
    fig.savefig(CHART2_PATH, dpi=180, bbox_inches="tight", facecolor="#FFFFFF")
    plt.close(fig)
    return CHART1_PATH, CHART2_PATH


def build_payload(c1_path: str, c2_path: str) -> dict:
    blocks = [
        MIXED([
            ("结论：满仓动态提门槛确实有用，影子回撤由47.58%降至28.80%。", True, True),
            ("在不降仓位下五年净值反由2.81亿倍增至9.20亿倍，夏普升至5.50。", False, False),
        ]),
        BL(),
        T("一、五年回撤根源解剖与五档物理灯色状态机", bold=True),
        B("原版回撤47.58%主因是半山腰硬买三进四，如友好集团单笔-23.90%。", False),
        B("法尔胜-17.95%与大港股份-13.91%亦在绿灯内杀期买入，并非大盘崩盘。", False),
        T("红灯地板绝对不能拦：全市场跌透恐慌时，六策略单笔均值+6.9%至+17.8%。", True, True),
        B("二维状态机从国证2000斜率与高位断板内杀温度出发，全部取自盘前已收盘数据。", False),
        B("非线性风险合分同时捕捉指数半山腰深黄主跌与表面绿灯下的高位连板内杀。", False),
        BL(),
        T("二、六策略分化规律与满仓动态提门槛实证", bold=True),
        B("深黄主跌只拖累三进四使其均值低至-2.36%，反把单席让给20cm首板。", False),
        B("弱黄与内杀期动态抬高三进四门槛，需同题材首板助攻并跳过冷清撬板。", False),
        T("影子V21五年回撤由47.58%降至28.80%，样本外回撤仅20.46%。", True, True),
        B("现役V20套用同套状态机后，五年回撤压至29.08%，夏普升至5.128。", False),
        B("学术对照六成半波动率平价虽把回撤压至23.81%，但五年净值暴缩至113万倍。", False),
        B("开盘前结构助攻优于盘中卡点，五分钟延迟虽降回撤但会踏空艾艾精工。", False),
        BL(),
        T("三、四道防过拟合标准严审全部过关", bold=True),
        B("前三年样本内回撤由35.29%降至28.80%，夏普由4.311升至4.541。", False),
        B("后三年样本外回撤由47.58%降至20.46%，今年维持16.58%低回撤。", False),
        T("剔除友好集团与鼎信通讯两颗最大孤例后，改进版依然净降6.49个百分点回撤。", True, True),
        B("五档27组邻域与二维18组邻域均稳居28.80%回撤，物理截断误差零。", False),
        BL(),
        T("四、1.5倍两融实测与官方历史两融标的资格大体检", bold=True),
        B("核查603对官方两融清单，影子V21五年52.8%可融，今年升至67.2%。", False),
        B("分策略资格分化大：20cm首板68.1%可融，三进四44.4%，撬板11.1%。", False),
        T("基线直上1.5倍两融回撤飙至63.80%，二维版把1.5倍全融压至41.06%。", True, True),
        B("仅对可融标的做1.5倍融资且小票用现金，均杠杆1.26倍且回撤守死28.80%。", False),
        B("按千三滑点与5.5%年化息盘中最低价算，全程维保比最低230.2%，零追保。", False),
        BL(),
        BL(),
        BL(),
    ]

    t1 = [
        [C("策略与灯色分组", True), C("纯绿畅通均值", True), C("绿灯内杀/深黄", True), C("红灯地板均值", True)],
        [C("三进四 (92笔)"), C("+13.07% (61笔)"), C("+3.0% / -2.4%"), C("+17.83% (3笔)")],
        [C("高标首阴 (41笔)"), C("+5.36% (28笔)"), C("+13.5% / +6.2%"), C("+11.89% (3笔)")],
        [C("二进三 (94笔)"), C("+6.21% (54笔)"), C("+16.5% / +6.6%"), C("+9.48% (6笔)")],
        [C("一进二 (92笔)"), C("+7.90% (57笔)"), C("+25.5% / -1.8%"), C("+11.31% (6笔)")],
        [C("20cm首板 (162笔)"), C("+4.05% (110笔)"), C("+2.3% / +3.2%"), C("+11.22% (9笔)")],
        [C("跌停撬板 (16笔)"), C("+5.47% (4笔)"), C("无 / +8.1%"), C("+6.91% (8笔)")],
    ]

    t2 = [
        [C("满仓方案对比", True), C("五年净值/夏普", True), C("五年/样本外回撤", True), C("去孤例五年回撤", True)],
        [C("V21原版基线", True), C("2.81亿倍 / 5.099"), C("47.58% / 47.58%"), C("35.29% (夏普5.24)")],
        [C("V21五档灯色版"), C("8.09亿倍 / 5.495"), C("28.80% / 20.46%"), C("28.80% (夏普5.50)")],
        [C("V21二维状态机", True), C("9.20亿倍 / 5.502"), C("28.80% / 20.46%"), C("28.80% (夏普5.50)")],
        [C("V20原版基线"), C("0.57亿倍 / 4.688"), C("47.58% / 47.58%"), C("35.29% (夏普4.82)")],
        [C("V20二维状态机"), C("1.80亿倍 / 5.128"), C("29.08% / 29.08%"), C("29.08% (夏普5.13)")],
        [C("V21波动率平价65%"), C("113万倍 / 5.149"), C("23.81% / 23.81%"), C("学术对照不作主推")],
    ]

    t3 = [
        [C("两融与杠杆实测", True), C("可融占比/均杠杆", True), C("五年净值/回撤", True), C("近3年回撤/最低维保", True)],
        [C("V21基线 1.5x全融"), C("51.3% / 1.50倍"), C("4446亿倍 / 63.80%"), C("63.80% / 228.9%")],
        [C("V21二维 1.0x现金"), C("52.8% / 1.00倍"), C("9.20亿倍 / 28.80%"), C("20.46% / 无负债")],
        [C("V21二维 1.5x可融", True), C("52.8% / 1.26倍"), C("1248亿倍 / 28.80%"), C("25.54% / 246.6%")],
        [C("V21二维 1.5x全融"), C("52.8% / 1.50倍"), C("3.01万亿倍 / 41.06%"), C("29.42% / 230.2%")],
        [C("V20二维 1.5x可融"), C("51.7% / 1.26倍"), C("145.9亿倍 / 29.32%"), C("29.08% / 256.5%")],
    ]

    sections_tables = [
        ("表1：六大策略在五档物理灯色下的单笔均收益分布（2021至2026年）", t1, c1_path),
        ("表2：满仓不降仓位方案全样本、样本外与去孤例防伪终审", t2, c2_path),
        ("表3：官方两融资格实查与1.5倍两融实盘仿真（扣5.5%年化息与千三滑点）", t3, None),
    ]
    return {
        "title": TITLE,
        "blocks": blocks,
        "tables": [(ttl, rows) for ttl, rows, _ in sections_tables],
        "sections_tables": sections_tables,
        "img_path": c1_path,
        "img_path2": c2_path,
    }


def validate_strict(payload: dict):
    fh.audit_payload_strict(payload, require_img=True)
    texts = [("title", payload["title"])]
    for i, b in enumerate(payload["blocks"]):
        els = b.get("text", b.get("bullet", {})).get("elements", [])
        txt = "".join(e["text_run"]["content"] for e in els)
        texts.append((f"block_{i+1}", txt))
        for s in re.split(r"[。；]", txt):
            sc = s.strip()
            if sc and len(sc) < 15:
                raise ValueError(f"过短句 block_{i+1} ({len(sc)}字): {sc}")
            if sc and len(sc) > 40:
                raise ValueError(f"过长句 block_{i+1} ({len(sc)}字): {sc}")
    for ttl, rows in payload["tables"]:
        texts.append((ttl, ttl))
        assert len(rows[0]) <= 4
        for r_i, rw in enumerate(rows):
            for c_i, cell in enumerate(rw):
                ct = "".join(t for t, _ in cell)
                assert len(ct) <= 32, f"单元格超32字({len(ct)}): {ct}"
                texts.append((f"{ttl}[{r_i},{c_i}]", ct))
    for c_i, ht in enumerate(HUB_ROW):
        assert len(ht) <= 32, f"Hub格超32字({len(ht)}): {ht}"
        texts.append((f"hub_{c_i}", ht))
    for loc, txt in texts:
        s9.check_text_punc_and_vars(txt, loc)
        for bw in s6.BANNED_WORDS + s6.EXTRA_BANNED_WORDS:
            if bw in txt:
                raise ValueError(f"[{loc}] 命中禁用词 '{bw}': {txt}")
        if s6.HUMAN_PROSE_BAD_RE.search(txt):
            raise ValueError(f"[{loc}] 命中 HUMAN_PROSE_BAD_RE: {txt}")
        for tok in FORBIDDEN_EXTRA:
            if re.fullmatch(r"[A-Za-z0-9_]+", tok):
                if re.search(rf"(?<![A-Za-z0-9_]){re.escape(tok)}(?![A-Za-z0-9_])", txt):
                    raise ValueError(f"[{loc}] 命中禁用词 '{tok}': {txt}")
            elif tok in txt:
                raise ValueError(f"[{loc}] 命中禁用词 '{tok}': {txt}")
    print("[DryRun PASS] RD049 Feishu payload 100% validated!")


def _api_retry(url: str, payload: dict | None = None, method: str = "POST", retries: int = 6) -> dict:
    for att in range(retries):
        r = s6.api(url, payload, method) if payload is not None else s6.api(url, method=method)
        if r.get("code") == 0:
            return r
        time.sleep(min(6.0, 0.8 * (2 ** att)))
    return r


def _insert_image_retry(doc_id: str, png_path: str) -> bool:
    import subprocess
    if not os.path.exists(png_path):
        return False
    r1 = _api_retry(
        f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children",
        {"children": [{"block_type": 27, "image": {}}], "index": -1},
        "POST",
    )
    if r1.get("code") != 0:
        return False
    blk_id = r1["data"]["children"][0]["block_id"]
    time.sleep(0.3)

    tok_s = s6._shared_tok(force=False)
    r2 = {}
    for att in range(5):
        out = subprocess.check_output(
            [
                "curl", "-sS", "-X", "POST", f"{s6.BASE}/open-apis/drive/v1/medias/upload_all",
                "-H", f"Authorization: Bearer {tok_s}",
                "-F", f"file_name={os.path.basename(png_path)}",
                "-F", "parent_type=docx_image",
                "-F", f"parent_node={blk_id}",
                "-F", f"size={os.path.getsize(png_path)}",
                "-F", f"file=@{png_path};type=image/png",
            ],
            timeout=120,
        ).decode("utf-8")
        r2 = json.loads(out)
        if r2.get("code") == 0:
            break
        if r2.get("code") in (99991661, 99991677):
            tok_s = s6._shared_tok(force=True)
            s6.T = tok_s
        time.sleep(min(6.0, 1.0 * (att + 1)))
    if r2.get("code") != 0:
        return False
    time.sleep(0.3)
    r3 = _api_retry(
        f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{blk_id}",
        {"replace_image": {"token": r2["data"]["file_token"]}},
        "PATCH",
    )
    if r3.get("code") != 0:
        return False
    print(f"  [+] 成功插入图片: {os.path.basename(png_path)}")
    return True


def write_doc_resilient(doc_id: str, blocks: list, sections_tables: list) -> tuple[int, int]:
    s6.clear_doc_all(doc_id)
    time.sleep(0.5)
    done, fail = 0, 0
    for i in range(0, len(blocks), 20):
        ch = blocks[i : i + 20]
        r = _api_retry(f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children", {"children": ch, "index": -1}, "POST")
        if r.get("code") == 0:
            done += len(ch)
        else:
            for b in ch:
                r2 = _api_retry(f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children", {"children": [b], "index": -1}, "POST")
                done += 1 if r2.get("code") == 0 else 0
                fail += 0 if r2.get("code") == 0 else 1
                time.sleep(0.25)
        time.sleep(0.35)

    for t_title, t_rows, chart_after in sections_tables:
        t_blk = {"block_type": 2, "text": {"elements": [{"text_run": {"content": t_title, "text_element_style": {"bold": True}}}], "style": {"align": 1, "folded": False}}}
        rt = _api_retry(f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children", {"children": [t_blk], "index": -1}, "POST")
        done += 1 if rt.get("code") == 0 else 0
        fail += 0 if rt.get("code") == 0 else 1
        time.sleep(0.3)

        d = s6.Desc()
        root = d.add({"t": "table", "rows": t_rows})
        rtb = _api_retry(f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/descendant", {"children_id": [root], "descendants": d.d}, "POST")
        done += 1 if rtb.get("code") == 0 else 0
        fail += 0 if rtb.get("code") == 0 else 1
        time.sleep(0.45)

        if chart_after and os.path.exists(chart_after):
            if _insert_image_retry(doc_id, chart_after):
                done += 1
            else:
                fail += 1
            time.sleep(0.5)
    return done, fail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    audit = json.load(open(f"{RD049_DIR}/rd049_audit.json", encoding="utf-8"))
    c1, c2 = build_charts(audit)
    print("Generated charts:", c1, c2)

    payload = build_payload(c1, c2)
    validate_strict(payload)
    if args.dry_run:
        return

    lock_f = open(s6.LOCK_PATH, "w")
    fcntl.flock(lock_f, fcntl.LOCK_EX)
    try:
        doc_id, node_tok = s9.find_or_create_child_node(fh.VALID_PARENT_NODE, payload["title"])
        payload["doc_id"] = doc_id
        done, fail = write_doc_resilient(doc_id, payload["blocks"], payload["sections_tables"])
        assert fail == 0, f"Write failed: {fail}"
        time.sleep(0.8)
        v = s9.verify_document_v191(doc_id, payload["title"], expected_tables_count=len(payload["tables"]), has_img=True)
        assert v["images_count"] >= 2, f"Missing charts: {v}"

        raw_txt = _api_retry(f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/raw_content", method="GET")["data"]["content"]
        fh.audit_online_raw_text(raw_txt)

        hub_res = fh.update_hub_incremental(fh.VALID_HUB_DOC, "有效回测与可用规律", HUB_ROW)
        wiki_url = f"https://my.feishu.cn/wiki/{node_tok}"

        res = {
            "title": payload["title"],
            "doc_id": doc_id,
            "node_token": node_tok,
            "wiki_url": wiki_url,
            "parent_node_token": fh.VALID_PARENT_NODE,
            "verify": v,
            "hub_update": hub_res,
            "online_raw_chars": len(raw_txt),
        }
        with open(f"{RD049_DIR}/feishu_publish_result.json", "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
        print(json.dumps(res, ensure_ascii=False, indent=2))
    finally:
        fcntl.flock(lock_f, fcntl.LOCK_UN)
        lock_f.close()


if __name__ == "__main__":
    main()

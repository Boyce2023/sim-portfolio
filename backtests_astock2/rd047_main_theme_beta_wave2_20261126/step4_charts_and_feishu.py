#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD047 Step 4: Generate 2 Crisp Pure-Chinese Charts & Publish Strict Feishu Report (`大主线题材动态打分实证`)
to Invalid Library (`QiDewdTkJiquokkbbo6cWr3Fn6f`) + Incrementally Update Invalid Hub (`ZTaudjSqtoaj71xTPSLciMcdnLb`).
Zero yfinance (D12). Zero edits to active V20.0 production scripts/rules.
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
assert "yfinance" not in sys.modules, "D12 violation!"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
RD047_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd047_main_theme_beta_wave2_20261126"
CACHE_DIR = f"{RD047_DIR}/_cache"
RD041_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd041_day0_firstboard_sweep_20261126"
FS_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/feishu_master_docs_20261116"
for p in (RD047_DIR, RD041_DIR, FS_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import _rd047_common as cm  # noqa: E402
import _rd041_feishu_helpers as fh  # noqa: E402
import step6_upgrade_3strategies_20261117 as s6  # noqa: E402
import step9_sync_v191_exits_20261118 as s9  # noqa: E402

TITLE = "大主线题材动态打分实证"
HUB_ROW = [
    "大主线题材动态打分实证",
    "6年83组全遍历+2026四波",
    "打分精准抓四季主线，但83组全亏(最优仅0.23倍)",
    "禁作主线追涨买卖信号，仅作观察",
]

CHART1_PATH = f"{RD047_DIR}/rd047_chart1_nav_and_2026_timeline.png"
CHART2_PATH = f"{RD047_DIR}/rd047_chart2_yearly_plateau_loto_v20.png"

C, T, B, BL, MIXED = fh.C, fh.T, fh.B, fh.BL, fh.MIXED

plt.rcParams["font.sans-serif"] = ["PingFang SC", "Hiragino Sans GB", "STHeiti", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def build_charts(audit: dict) -> tuple[str, str]:
    npz = np.load(f"{CACHE_DIR}/grid_daily_returns.npz")
    cal_dts = [str(d) for d in npz["cal_dts"]]
    dt_idx_dt = pd.to_datetime(cal_dts)
    bench_ctx = cm.load_bench_and_v20(end_dt=cm.EVAL_END)
    csi_dr = bench_ctx["csi300_dr"][:len(cal_dts)]
    bond_dr = bench_ctx["bond_511010_dr"][:len(cal_dts)]

    tl = pd.read_csv(f"{RD047_DIR}/rd047_2026_theme_timeline.csv")
    grid = pd.read_csv(f"{RD047_DIR}/rd047_grid.csv")

    # === CHART 1: 2021-2026 NAV Curves + 2026 Daily Top-1 Theme Score Timeline ===
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15.6, 6.2), dpi=180)
    fig.patch.set_facecolor("#FFFFFF")

    curves = [
        ("bond", bond_dr, "国债ETF511010基准 (1.21倍)", "#059669", "--", 1.8, 0.0),
        ("csi", csi_dr, "沪深300基准 (0.76倍)", "#64748b", ":", 1.8, 0.0),
        ("A_Inst_T75_hold20_K5_3y_Bond_30bp", npz["A_Inst_T75_hold20_K5_3y_Bond_30bp"], "趋势中军20日+国债 (最优0.23倍)", "#0284c7", "-", 2.2, 0.015),
        ("A_StaticSW3_T80_ma20_K5_3y_Cash_30bp", npz["A_StaticSW3_T80_ma20_K5_3y_Cash_30bp"], "静态行业80分破20日线 (0.10倍)", "#7c3aed", "-.", 1.7, 0.015),
        ("A_L_T75_ma20_K5_3y_Cash_30bp", npz["A_L_T75_ma20_K5_3y_Cash_30bp"], "趋势龙头75分破20日线 (0.02倍)", "#d97706", "-", 1.8, 0.025),
        ("B_SwUp_T75_ma10_K3_Cash_30bp", npz["B_SwUp_T75_ma10_K3_Cash_30bp"], "换皮长二波75分破10日线 (0.003倍)", "#dc2626", "-", 1.8, -0.03),
    ]
    for key, dr, lbl, col, ls, lw, y_off in curves:
        nav = np.cumprod(1.0 + dr)
        ax1.plot(dt_idx_dt, nav, label=lbl, color=col, linestyle=ls, linewidth=lw)
        txt_val = f" {nav[-1]:.3f}x" if nav[-1] < 0.05 else f" {nav[-1]:.2f}x"
        ax1.text(dt_idx_dt[-1], nav[-1] + y_off, txt_val, va="center", ha="left", fontsize=7.6, color=col, fontweight="bold")

    ax1.axhline(1.0, color="#0f172a", linestyle=":", linewidth=1.0)
    ax1.set_title("一、2021至2026年全周期净值走势：83组全线亏损（已扣千三费用）", fontsize=10.8, fontweight="bold", pad=12)
    ax1.set_ylabel("累计净值（倍）", fontsize=9.5, fontweight="bold")
    ax1.set_xlim(dt_idx_dt[0], dt_idx_dt[-1] + pd.Timedelta(days=145))
    ax1.set_ylim(-0.07, 1.82)
    ax1.grid(True, linestyle="--", alpha=0.35)
    ax1.legend(loc="upper right", fontsize=7.6, frameon=True)

    # Panel 2: 2026 Daily Top-1 Theme Score Timeline + 4 Named Waves
    tl_dt = pd.to_datetime(tl["trade_date"])
    sc1 = tl["top1_score"].to_numpy(float)
    ax2.plot(tl_dt, sc1, color="#1e293b", linewidth=1.5, label="每日全市场第一主线热度分")
    ax2.fill_between(tl_dt, 75.0, sc1, where=(sc1 >= 75.0), color="#f59e0b", alpha=0.25, label="75分以上强主线区")
    ax2.axhline(75.0, color="#dc2626", linestyle="--", linewidth=1.1, label="75分强主线门槛")
    ax2.axhline(80.0, color="#b91c1c", linestyle=":", linewidth=1.0)

    # Shade 4 named waves cleanly
    wave_spans = [
        ("2026-04-01", "2026-06-30", "#dbeafe", "4至6月科技\n通信92.8/芯片89.2\n元件90.4/被动77.9"),
        ("2026-07-01", "2026-08-18", "#dcfce7", "7至8月医药\n医药86.7/研发80.5"),
        ("2026-08-19", "2026-09-30", "#fef3c7", "8至9月农业\n农业最高93.7"),
        ("2026-10-08", "2026-11-24", "#fae8ff", "10至11月机器人\n机器人87.9\n九阳10.28换皮72.5"),
    ]
    y_pos_txt = [106.5, 106.5, 106.5, 106.5]
    for (ws, we, bgc, txt), yp in zip(wave_spans, y_pos_txt):
        s_t, e_t = pd.Timestamp(ws), pd.Timestamp(we)
        ax2.axvspan(s_t, e_t, color=bgc, alpha=0.35, zorder=0)
        mid_t = s_t + (e_t - s_t) / 2
        ax2.text(mid_t, yp, txt, ha="center", va="top", fontsize=7.0, fontweight="bold", color="#0f172a",
                 bbox=dict(boxstyle="round,pad=0.25", facecolor="#ffffff", edgecolor="#cbd5e1", alpha=0.92))

    ax2.set_title("二、2026年1至11月每日主线热度时间轴：打分精准捕获四季波段", fontsize=10.8, fontweight="bold", pad=12)
    ax2.set_ylabel("主线实时动态热度分（0至100分）", fontsize=9.5, fontweight="bold")
    ax2.set_ylim(48, 109)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%m月"))
    ax2.grid(True, linestyle="--", alpha=0.35)
    ax2.legend(loc="lower left", fontsize=7.5, frameon=True)

    plt.tight_layout(pad=2.0)
    fig.savefig(CHART1_PATH, dpi=180, bbox_inches="tight", facecolor="#FFFFFF")
    plt.close(fig)

    # === CHART 2: 2x2 Red-Team Verification (Yearly + Plateau + Leave-One + V20 Corr) ===
    fig, ((bx1, bx2), (bx3, bx4)) = plt.subplots(2, 2, figsize=(15.6, 10.2), dpi=180)
    fig.patch.set_facecolor("#FFFFFF")

    # Panel 1 (bx1): Year-by-year returns 2021..2026
    yrs = [("Y2021_ret_pct", "2021年"), ("Y2022_ret_pct", "2022熊市"), ("Y2023_ret_pct", "2023年"), ("Y2024_ret_pct", "2024年"), ("Y2025_ret_pct", "2025年"), ("Y2026_ret_pct", "2026年")]
    rep_map = {r["strategy_id"]: r for r in audit["representative_metrics"]}
    csi_w = audit["benchmarks"]["csi300"]
    csi_yrs = [csi_w[y]["tot_ret_pct"] for y in ("Y2021", "Y2022", "Y2023", "Y2024", "Y2025", "Y2026")]
    series_y = [
        ("沪深300基准", csi_yrs, "#64748b"),
        ("中军20日+国债(最优)", [rep_map["A_Inst_T75_hold20_K5_3y_Bond_30bp"][c] for c, _ in yrs], "#0284c7"),
        ("趋势龙头破20日线", [rep_map["A_L_T75_ma20_K5_3y_Cash_30bp"][c] for c, _ in yrs], "#d97706"),
        ("换皮二波75分破10日", [rep_map["B_SwUp_T75_ma10_K3_Cash_30bp"][c] for c, _ in yrs], "#dc2626"),
    ]
    x = np.arange(len(yrs))
    w = 0.20
    for idx_s, (slbl, vals, col) in enumerate(series_y):
        bars = bx1.bar(x + (idx_s - 1.5) * w, vals, width=w, color=col, alpha=0.88, label=slbl)
        for b, v in zip(bars, vals):
            y_txt = v + 1.5 if v >= 0 else v - 1.5
            va_t = "bottom" if v >= 0 else "top"
            bx1.text(b.get_x() + b.get_width() / 2, y_txt, f"{v:.0f}%", ha="center", va=va_t, fontsize=6.6, fontweight="bold")
    bx1.axhline(0.0, color="#0f172a", linewidth=1.0)
    bx1.set_xticks(x)
    bx1.set_xticklabels([yn for _, yn in yrs], fontsize=8.8, fontweight="bold")
    bx1.set_ylabel("分年度净收益率（%）", fontsize=9.2, fontweight="bold")
    bx1.set_title("三、分年度收益检验：2022熊市仍大亏，仅2021年局部盈利", fontsize=10.6, fontweight="bold", pad=10)
    bx1.set_ylim(-106, 56)
    bx1.grid(axis="y", linestyle="--", alpha=0.35)
    bx1.legend(loc="lower right", fontsize=7.6, frameon=True, ncol=2)

    # Panel 2 (bx2): Parameter Plateau Heatmap (Track A Leader Cash 5-slot, thr x MA)
    thrs = [70.0, 75.0, 80.0, 85.0]
    mas = ["ma10", "ma15", "ma20"]
    mat_nav = np.zeros((len(thrs), len(mas)))
    mat_wr = np.zeros((len(thrs), len(mas)))
    for i_t, tv in enumerate(thrs):
        for j_m, mv in enumerate(mas):
            sub_g = grid[(grid["track"] == "A") & (grid["thr"] == tv) & (grid["exit"] == mv) & (grid["slots"] == 5) & (grid["style"] == "leader") & (grid["park"] == "Cash") & (grid["fee_bp"] == 30)]
            if not sub_g.empty:
                mat_nav[i_t, j_m] = float(sub_g.iloc[0]["FULL_5Y_nav"])
                mat_wr[i_t, j_m] = float(sub_g.iloc[0]["wr_5y"])
    im = bx2.imshow(mat_nav, cmap="Reds_r", vmin=-0.01, vmax=0.06, aspect="auto")
    bx2.set_xticks(np.arange(len(mas)))
    bx2.set_xticklabels(["破10日线", "破15日线", "破20日线"], fontsize=9.0, fontweight="bold")
    bx2.set_yticks(np.arange(len(thrs)))
    bx2.set_yticklabels([f"门槛{int(t)}分" for t in thrs], fontsize=9.0, fontweight="bold")
    for i_t in range(len(thrs)):
        for j_m in range(len(mas)):
            tc = "#FFFFFF" if mat_nav[i_t, j_m] < 0.025 else "#0f172a"
            bx2.text(j_m, i_t, f"净值 {mat_nav[i_t,j_m]:.3f}x\n胜率 {mat_wr[i_t,j_m]:.1f}%", ha="center", va="center", fontsize=8.5, fontweight="bold", color=tc)
    bx2.set_title("四、参数高原检验：全网格83组均远低于1倍（无任何有效高原）", fontsize=10.6, fontweight="bold", pad=10)

    # Panel 3 (bx3): Leave-One-Out + 2026 4-Wave Return Decomposition
    lo_d = audit["loto_loyo"]["A_Inst_T75_hold20_K5_3y_Bond_30bp"]
    wf26 = audit["wave_2026_forensics"]
    cats_b3 = [
        ("全期基线", 0.2292, "#0284c7"),
        ("剔2021年", lo_d["loyo"]["ex_2021"]["nav"], "#64748b"),
        ("剔2022熊市", lo_d["loyo"]["ex_2022"]["nav"], "#0ea5e9"),
        ("剔并购重组", lo_d["loto"]["ex_best_theme"]["approx_nav"], "#7c3aed"),
        ("剔机器人", lo_d["loto"]["ex_most_freq_theme"]["approx_nav"], "#a855f7"),
    ]
    xb3 = np.arange(len(cats_b3))
    bars3 = bx3.bar(xb3, [v for _, v, _ in cats_b3], width=0.52, color=[c for _, _, c in cats_b3], alpha=0.88)
    for b, v in zip(bars3, [v for _, v, _ in cats_b3]):
        bx3.text(b.get_x() + b.get_width() / 2, v + 0.012, f"{v:.3f}x", ha="center", va="bottom", fontsize=8.2, fontweight="bold")
    bx3.axhline(1.0, color="#dc2626", linestyle="--", linewidth=1.1, label="保本线 1.0倍")
    bx3.set_xticks(xb3)
    bx3.set_xticklabels([k for k, _, _ in cats_b3], fontsize=8.4, fontweight="bold")
    bx3.set_ylabel("留一法后五年净值（倍）", fontsize=9.2, fontweight="bold")
    bx3.set_ylim(0, 1.12)
    bx3.set_title("五、跨年份与跨主线留一验证：剔除任一主线或熊市仍全线亏损", fontsize=10.6, fontweight="bold", pad=10)
    bx3.grid(axis="y", linestyle="--", alpha=0.35)
    bx3.legend(loc="upper right", fontsize=8.0, frameon=True)
    bx3.text(
        0.03, 0.72,
        f"2026年四波单笔均值实测（龙头75分破20日线）：\n"
        f"4至6月科技 +10.94%（胜率47.4%，抓住利通/永鼎）\n"
        f"7至8月医药 -6.81%（胜率0.0%）  8至9月农业 -9.05%\n"
        f"10至11月机器人阶段 -8.58%",
        transform=bx3.transAxes, fontsize=7.8, color="#0f172a",
        bbox=dict(boxstyle="round,pad=0.4", facecolor="#f8fafc", edgecolor="#94a3b8"),
    )

    # Panel 4 (bx4): Dual-Ledger Impact vs Active V20.0
    v20_bl = audit["v20_corr_and_blends"]["A_Inst_T75_hold20_K5_3y_Bond_30bp"]["blends"]
    pts_v = [
        ("100%现役V20\n(基准)", v20_bl["v20_100pct"]["sharpe"], v20_bl["v20_100pct"]["mdd_pct"], "#059669"),
        ("80%V20+20%趋势最优\n(拖累夏普)", v20_bl["daily_80v20_20s"]["sharpe"], v20_bl["daily_80v20_20s"]["mdd_pct"], "#0284c7"),
        ("70%V20+30%趋势最优\n(净值跌98%)", v20_bl["daily_70v20_30s"]["sharpe"], v20_bl["daily_70v20_30s"]["mdd_pct"], "#d97706"),
        ("50%V20+50%趋势最优\n(严重拖拽)", v20_bl["daily_50v20_50s"]["sharpe"], v20_bl["daily_50v20_50s"]["mdd_pct"], "#dc2626"),
    ]
    xp4 = np.arange(len(pts_v))
    bars4 = bx4.bar(xp4, [p[1] for p in pts_v], width=0.50, color=[p[3] for p in pts_v], alpha=0.88)
    for b, (_, shv, mdv, _) in zip(bars4, pts_v):
        bx4.text(b.get_x() + b.get_width() / 2, shv + 0.08, f"夏普 {shv:.2f}\n回撤 {mdv:.1f}%", ha="center", va="bottom", fontsize=8.0, fontweight="bold")
    bx4.set_xticks(xp4)
    bx4.set_xticklabels([p[0] for p in pts_v], fontsize=8.2, fontweight="bold")
    bx4.set_ylabel("样本外组合年化夏普（2023至2026）", fontsize=9.2, fontweight="bold")
    bx4.set_ylim(0, 5.5)
    bx4.set_title("六、与现役V20相关性(+0.065)及双账本配置实测：负收益拖拽主力", fontsize=10.6, fontweight="bold", pad=10)
    bx4.grid(axis="y", linestyle="--", alpha=0.35)

    plt.tight_layout(pad=2.0)
    fig.savefig(CHART2_PATH, dpi=180, bbox_inches="tight", facecolor="#FFFFFF")
    plt.close(fig)
    return CHART1_PATH, CHART2_PATH


def build_payload(c1_path: str, c2_path: str) -> dict:
    blocks = [
        MIXED([
            ("结论：主线打分制对趋势追踪完全没用，83组策略在六年盲测中全线亏损。", True, True),
            ("纯因果打分虽能识别今年四季主线与换皮节点，但追买后单边胜率不足三成。", False, False),
            ("最优中军二十日策略六年净值仅剩0.23倍，绝不能接入实盘或双账本资金。", False, False),
        ]),
        BL(),
        T("一、纯因果主线动态打分设计：五维合分与二十日动态标签切换", bold=True),
        B("打分体系同时覆盖开盘啦动态题材与申万三级行业，全部取自收盘前已知数据。", False),
        B("总分一百分拆为资金与趋势各二十五分、情绪二十分、生命力与催化各十五分。", False),
        B("为避免长趋势在后半程被短基线惩罚，资金跃升对比过去一年两百五十日均值衡量。", False),
        B("为解决九阳股份这类跨板块换皮，系统取个股二十日内全部标签最高实时分。", False, True),
        B("物理截断回放至前年年底，每日主线分数、个股动态分与日收益零误差一致。", False, True),
        BL(),
        T("二、2026年四季主线大考：打分精准捕获风口，但三季回撤吞噬利润", bold=True),
        B("四至六月科技行情抓准，通信最高92.8分、元器件90.4分、芯片89.2分。", False, True),
        B("趋势中军篮子在四月十日买入沪电股份与立讯精密，二十一日平均收益超三成。", False),
        B("但纯光模块细分行业受老旧通信股拖累最高仅66.6分，未能靠自身突破75分。", False),
        B("七至八月医药最高打到86.7分、八至九月农业最高93.7分，打分并未漏掉两段主线。", False),
        B("医药与农业轮动极快，龙头破20日线两阶段均值仅 -6.8% 与 -9.1%。", False, True),
        B("十至十一月机器人升至87.9分，九阳股份也在10月28日换皮入池打到72.5分。", False),
        B("因十月下旬仓位已满且十一月中旬题材与启动日错位四天，最终未能成交九阳。", False),
        BL(),
        T("三、六年全周期盲测与防伪审查：为何高分主线追买天然负期望", bold=True),
        B("遍历门槛、均线、仓位与费率共83组，0组六年净值超过1倍。", False, True),
        B("六年最优组合为中军二十日固定配国债，净值仅剩0.23倍且夏普 -0.40。", False),
        B("即使不设均线止损硬拿二十天且剔除近五日暴涨股，全期胜率也只有39.9%。", False),
        B("高分本质是放量拥挤与情绪高潮，八十分以上题材未来二十日均值仅 -6.8%。", False, True),
        B("2022年熊市亏损 -33.8% 至 -92.8%，剔除任一主线或年份仍亏。", False),
        B("该模型与现役V20相关性仅 +0.065，七三开双账本反而拖拽主力夏普。", False, True),
        B("最终裁定：纯因果主线打分仅留作市场观察雷达，严禁用于主线追涨实盘。", False),
        BL(),
        BL(),
        BL(),
    ]

    t1 = [
        [C("2026年四大主线区间", True), C("系统最高主线分", True), C("中军/龙头代表收益", True), C("阶段复盘结论", True)],
        [C("4至6月 科技硬件"), C("通信92.8/元件90.4"), C("利通+116%/沪电+32%"), C("唯一盈利波段均值+10.9%")],
        [C("7至8月 医药行情"), C("医药86.7/研发80.5"), C("百普赛斯+10.2%"), C("轮动过快，龙头均值 -6.8%")],
        [C("8至9月 农业行情"), C("农业最高93.7分"), C("金健米业+9.5%"), C("追高接盘，龙头均值 -9.1%")],
        [C("10至11月 机器人"), C("机器人87.9/九阳72.5"), C("未成交九阳错位4日"), C("仓满+错位，阶段均值 -8.6%")],
    ]

    t2 = [
        [C("六年全周期代表模型", True), C("六年净值/夏普", True), C("2022熊市/最大回撤", True), C("留一与双账本终裁", True)],
        [C("中军75分20日+国债"), C("0.23倍 / -0.40"), C("-46.0% / 87.1%"), C("最优仍亏，拖累V20夏普")],
        [C("龙头75分破20日线"), C("0.02倍 / -1.00"), C("-69.1% / 98.8%"), C("均线反抽割肉，胜率23.4%")],
        [C("静态行业80分破20日"), C("0.10倍 / -1.24"), C("-33.8% / 90.6%"), C("虽抗跌于动态仍全盘亏损")],
        [C("换皮二波70分破10日"), C("0.001倍 / -1.51"), C("-92.5% / 99.9%"), C("情绪退潮踩踏，彻底证伪")],
        [C("换皮二波升级75分"), C("0.003倍 / -1.26"), C("-92.8% / 99.9%"), C("剔除最优题材与年份仍亏")],
        [C("沪深300与国债基准"), C("0.76倍 / 1.21倍"), C("-21.6% / +3.3%"), C("全网格83组均跑输国债现金")],
    ]

    sections_tables = [
        ("表一：2026年四大主线盲测逐波核验明细（扣千分之三双边成本）", t1, c1_path),
        ("表二：2021至2026年全周期代表配置红队检验与基准对照", t2, c2_path),
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
            if s.strip() and len(s.strip()) < 15:
                raise ValueError(f"过短句 block_{i+1} ({len(s.strip())}字): {s.strip()}")
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
    print("[DryRun PASS] RD047 Feishu payload 100% validated!")


def _api_retry(url: str, payload: dict | None = None, method: str = "POST", retries: int = 6) -> dict:
    for att in range(retries):
        r = s6.api(url, payload, method) if payload is not None else s6.api(url, method=method)
        if r.get("code") == 0:
            return r
        print(f"  [retry {att+1}/{retries}] {method} {url.split('/')[-1]} -> {r}")
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
                if r2.get("code") == 0:
                    done += 1
                else:
                    fail += 1
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

    audit = json.load(open(f"{RD047_DIR}/rd047_audit.json", encoding="utf-8"))
    c1, c2 = build_charts(audit)
    print("Generated charts:", c1, c2)

    payload = build_payload(c1, c2)
    validate_strict(payload)
    if args.dry_run:
        return

    lock_f = open(s6.LOCK_PATH, "w")
    fcntl.flock(lock_f, fcntl.LOCK_EX)
    try:
        doc_id, node_tok = s9.find_or_create_child_node(fh.INVALID_PARENT_NODE, payload["title"])
        payload["doc_id"] = doc_id
        done, fail = write_doc_resilient(doc_id, payload["blocks"], payload["sections_tables"])
        assert fail == 0, f"Write failed: {fail}"
        time.sleep(0.8)
        v = s9.verify_document_v191(doc_id, payload["title"], expected_tables_count=len(payload["tables"]), has_img=True)
        assert v["images_count"] >= 2, f"Missing charts: {v}"

        raw_txt = _api_retry(f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/raw_content", method="GET")["data"]["content"]
        fh.audit_online_raw_text(raw_txt)

        hub_res = fh.update_hub_incremental(fh.INVALID_HUB_DOC, "证伪回测与避坑墓碑", HUB_ROW)
        wiki_url = f"https://my.feishu.cn/wiki/{node_tok}"

        res = {
            "title": payload["title"],
            "doc_id": doc_id,
            "node_token": node_tok,
            "wiki_url": wiki_url,
            "parent_node_token": fh.INVALID_PARENT_NODE,
            "verify": v,
            "hub_update": hub_res,
            "online_raw_chars": len(raw_txt),
        }
        with open(f"{RD047_DIR}/feishu_publish_result.json", "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
        print(json.dumps(res, ensure_ascii=False, indent=2))
    finally:
        fcntl.flock(lock_f, fcntl.LOCK_UN)
        lock_f.close()


if __name__ == "__main__":
    main()

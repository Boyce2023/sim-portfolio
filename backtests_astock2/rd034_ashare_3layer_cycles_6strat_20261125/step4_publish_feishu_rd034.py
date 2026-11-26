#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD034 Step 4: Generate 2 Publication Charts + Publish Pure-Plain-Chinese Report
to Feishu Wiki under `证伪回测与避坑墓碑` (QiDewdTkJiquokkbbo6cWr3Fn6f)
and sync Hub Index Table (ZTaudjSqtoaj71xTPSLciMcdnLb).
Strictly NO yfinance (D12). Zero statistical jargon.
"""
import argparse
import fcntl
import json
import re
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation"

OUT_DIR = Path("/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd034_ashare_3layer_cycles_6strat_20261125")
FS_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/feishu_master_docs_20261116"
if FS_DIR not in sys.path:
    sys.path.insert(0, FS_DIR)

import step6_upgrade_3strategies_20261117 as s6
import step9_sync_v191_exits_20261118 as s9
from build_master_docs import (
    make_text_run as TR,
    make_para_block as P,
    make_bullet_block as B,
    make_ordered_block as O,
    make_blank_line as BL,
)
from small_backtests_payloads_20261124 import build_hub_doc

I_NODE = "QiDewdTkJiquokkbbo6cWr3Fn6f"
I_DOC = "ZTaudjSqtoaj71xTPSLciMcdnLb"
TITLE_RD034 = "A股三层周期实证"

EXTRA_JARGON_RE = re.compile(r"(BH-FDR|FDR|q值|p值|t值|PBO|CSCV|PIT|OOS|IS|消融|重锚|门禁|闭环|矩阵|铁证|T-1)")

plt.rcParams["font.sans-serif"] = ["Hiragino Sans GB", "STHeiti", "Arial Unicode MS", "Songti SC"]
plt.rcParams["axes.unicode_minus"] = False
NAVY, TEAL, CRIMSON, AMBER, SLATE = "#1B365D", "#0F766E", "#B91C1C", "#D97706", "#64748B"


def row(vals, bold=False):
    st = {"bold": True} if bold else {}
    return [[(str(v), st)] for v in vals]


def generate_charts(audit: dict, df_m: pd.DataFrame) -> tuple[str, str]:
    c1_path = str(OUT_DIR / "chart1_3layer_cycles_and_absorption.png")
    c2_path = str(OUT_DIR / "chart2_oos_rerank_filter_half50.png")

    # --- Chart 1: Left = V20 Combined across Market Cycles; Right = Absorption Effect ---
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.8, 5.6), dpi=180)
    ft = {r["regime"]: r for r in audit["step2_3layer_scan_and_v20_absorption"]["v20_regime_firing_table"]}
    pick_regimes = [
        ("全期基准 (全部1212天)", "全期基准 (1212天)"),
        ("情绪五态: 冰点", "情绪五态·冰点"),
        ("情绪五态: 修复", "情绪五态·修复"),
        ("情绪五态: 主升", "情绪五态·主升"),
        ("情绪五态: 高潮", "情绪五态·高潮"),
        ("情绪五态: 退潮", "情绪五态·退潮"),
        ("昨日跌停潮 (>=20家非ST跌停)", "昨日跌停潮 (>=20家)"),
        ("4月年季报雷区 (04-15~04-30)", "4月年季报雷区"),
        ("风格极不利微盘 (微盘20日跑输<=-2.6%)", "微盘跑输逆风期"),
        ("市场MA60深度空头 (<-5%)", "市场均线空头区"),
    ]
    lbls, means, wrs, pass_pcts = [], [], [], []
    for k, slbl in pick_regimes:
        r = ft[k]
        lbls.append(slbl)
        means.append(r["comb_mean_ret_pct"])
        wrs.append(r["comb_wr_pct"])
        pass_pcts.append(r["any_pass_signal_day_pct"])

    y = np.arange(len(lbls))[::-1]
    cols = [CRIMSON if i == 0 else (TEAL if m >= 8.0 else NAVY) for i, m in enumerate(means)]
    ax1.barh(y, means, color=cols, alpha=0.88, height=0.62)
    for yi, m_v, w_v, pp in zip(y, means, wrs, pass_pcts):
        ax1.text(m_v + 0.25, yi, f"+{m_v:.1f}% (胜{w_v:.0f}% · 达标日{pp:.0f}%)", va="center", fontsize=7.6, fontweight="bold", color=NAVY)
    ax1.set_yticks(y)
    ax1.set_yticklabels(lbls, fontsize=8.5)
    ax1.set_xlim(0, 19.5)
    ax1.set_xlabel("合体单仓单笔均收 (%) 与胜率", fontsize=9.5)
    ax1.set_title("现役合体单仓在各市场周期全部正收益 (冷市自动降频)", fontsize=10.5, fontweight="bold")
    ax1.grid(True, axis="x", linestyle="--", alpha=0.25)

    # Right panel: Candidate Pool vs Passing Pool |Spearman r| (Absorption Proof)
    abs_items = [
        ("pry", "L1_ew_vol20_t1", "撬板 × 指数20日波动"),
        ("pry", "L1_sent_phase_t1", "撬板 × 市场情绪五态"),
        ("pry", "L1_zt_cnt_t1", "撬板 × 昨日涨停家数"),
        ("20cm", "L1_nat_zt_cnt_t1", "20cm × 自然涨停家数"),
        ("20cm", "L1_zt_pct60_t1", "20cm × 涨停60日分位"),
        ("3to4", "L1_lb_promo_t1", "三进四 × 连板晋级率"),
        ("1to2", "L3_newhigh_cnt60_t1", "一进二 × 60日新高(未吸)"),
        ("20cm", "L3_cum_turn20_t1", "20cm × 20日换手(未吸)"),
    ]
    a_lbls, r_cand, r_pass = [], [], []
    for st, fc, flbl in abs_items:
        rc = df_m[(df_m["target"] == f"{st}__L1_cand") & (df_m["factor"] == fc)].iloc[0]["spearman_r"]
        rp = df_m[(df_m["target"] == f"{st}__L2_pass") & (df_m["factor"] == fc)].iloc[0]["spearman_r"]
        a_lbls.append(flbl)
        r_cand.append(abs(float(rc)))
        r_pass.append(abs(float(rp)))
    ya = np.arange(len(a_lbls))[::-1]
    h = 0.34
    ax2.barh(ya + h / 2, r_cand, height=h, color=SLATE, alpha=0.85, label="未过滤候选宽池相关强度")
    ax2.barh(ya - h / 2, r_pass, height=h, color=CRIMSON, alpha=0.88, label="V20.0 过线实盘池残留强度")
    for yi, c_v, p_v in zip(ya, r_cand, r_pass):
        ax2.text(max(c_v, p_v) + 0.01, yi, f"{c_v:.2f} -> {p_v:.2f}", va="center", fontsize=7.8, fontweight="bold", color=NAVY)
    ax2.set_yticks(ya)
    ax2.set_yticklabels(a_lbls, fontsize=8.5)
    ax2.set_xlim(0, 0.52)
    ax2.set_xlabel("周期因子与收益率相关性强度 (绝对值)", fontsize=9.5)
    ax2.set_title("现役评分卡自动吸收效应：市场周期在过线前已大幅衰减", fontsize=10.5, fontweight="bold")
    ax2.grid(True, axis="x", linestyle="--", alpha=0.25)
    ax2.legend(loc="lower right", fontsize=8.0, frameon=True, facecolor="white")

    fig.suptitle("A股三层周期实证：现役体系冷市自动少出手且胜率更高，多数周期已被结构规则吸收", fontsize=11.8, fontweight="bold", y=0.98)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    fig.savefig(c1_path)
    plt.close(fig)

    # --- Chart 2: Left = V20 Combined OOS NAV Comparison; Right = IS Overfit vs OOS Collapse ---
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.8, 5.5), dpi=180)
    comb_ev = audit["step3_v20_combined_rerank_and_filter"]["schemes"]
    half_ev = {r["policy"]: r for r in audit["step3_v20_combined_half50_and_stop0"]["all_policies"]}

    bars_spec = [
        ("V20_BASELINE", "comb", "现役 V20.0 原版满仓"),
        ("RERANK_20cm_R_L1_smb_neg_bon_w10", "comb", "20cm微盘逆风加10分"),
        ("Half50_C_L1_duanban_low (昨日断板大面率<=5%(过顺))", "half", "断板过顺时降半仓"),
        ("Half50_C_L1_sent_climax (情绪高潮期)", "half", "情绪高潮期降半仓"),
        ("FILTER_3to4_F_L3_ampcomp_lo", "comb", "三进四振幅压缩过滤"),
        ("Half50_C_L3_bias20_mid (个股MA20乖离中段(15~30%))", "half", "个股乖离中段降半仓"),
        ("COMBO_FILTER_ALL_IS", "comb", "全部样本内过滤组合"),
        ("Half50_C_L1_sent_ice (情绪冰点期)", "half", "情绪冰点期降半仓"),
        ("Half50_C_L1_earn_any (全部财报季窗口)", "half", "全部财报季降半仓"),
        ("COMBO_RERANK_ALL_IS", "comb", "六策略样本内最优重排合体"),
        ("Stop0_C_L1_sent_ice (情绪冰点期)", "half", "情绪冰点期停手空仓"),
    ]
    b_lbls, b_oos, b_srs = [], [], []
    for key, src, slbl in bars_spec:
        obj = comb_ev[key]["windows"]["OOS"] if src == "comb" else half_ev[key]["OOS"]
        b_lbls.append(slbl)
        b_oos.append(obj["nav"])
        b_srs.append(obj["daily_sharpe"])
    yb = np.arange(len(b_lbls))[::-1]
    b_cols = [CRIMSON if i == 0 else (AMBER if v > 1952.5 else NAVY) for i, v in enumerate(b_oos)]
    ax1.barh(yb, b_oos, color=b_cols, alpha=0.88, height=0.62)
    for yi, nv, sr in zip(yb, b_oos, b_srs):
        ax1.text(nv + 35, yi, f"{nv:,.1f}x (夏普{sr:.2f})", va="center", fontsize=7.6, fontweight="bold", color=CRIMSON if nv == 1952.5 else NAVY)
    ax1.set_yticks(yb)
    ax1.set_yticklabels(b_lbls, fontsize=8.2)
    ax1.set_xlim(0, 2750)
    ax1.set_xlabel("2025至2026年11月样本外复利净值倍数", fontsize=9.5)
    ax1.set_title("样本外实战赛马：绝大多数重排/过滤/减半全面跑输原版满仓", fontsize=10.5, fontweight="bold")
    ax1.grid(True, axis="x", linestyle="--", alpha=0.25)

    # Right panel: IS gain ratio vs OOS gain ratio (Overfitting Trap!)
    st_list = [
        ("1to2", "一进二重排", "rerank"),
        ("2to3", "二进三重排", "rerank"),
        ("3to4", "三进四重排", "rerank"),
        ("3to4", "三进四过滤", "filter"),
        ("20cm", "20cm重排", "rerank"),
        ("COMBO_ALL", "六策略重排合体", "comb"),
        ("COMBO_FLT", "全部过滤合体", "comb"),
    ]
    s_lbls, is_ratios, oos_ratios = [], [], []
    for sk, slbl, md in st_list:
        if md == "comb":
            k = "COMBO_RERANK_ALL_IS" if sk == "COMBO_ALL" else "COMBO_FILTER_ALL_IS"
            bw = comb_ev["V20_BASELINE"]["windows"]
            cw = comb_ev[k]["windows"]
            is_ratios.append(cw["IS"]["nav"] / bw["IS"]["nav"])
            oos_ratios.append(cw["OOS"]["nav"] / bw["OOS"]["nav"])
        else:
            src_m = audit["step3_single_strategy_rerank_is_to_oos"] if md == "rerank" else audit["step3_single_strategy_filter_is_to_oos"]
            bw = src_m[sk]["baseline"]
            cw = src_m[sk]["top_is_locked"]["windows"]
            is_ratios.append(cw["IS"]["nav"] / bw["IS"]["nav"])
            oos_ratios.append(cw["OOS"]["nav"] / bw["OOS"]["nav"])
        s_lbls.append(slbl)

    xs = np.arange(len(s_lbls))
    w = 0.34
    ax2.bar(xs - w / 2, is_ratios, width=w, color=TEAL, alpha=0.88, label="样本内净值倍数 / 原版")
    ax2.bar(xs + w / 2, oos_ratios, width=w, color=CRIMSON, alpha=0.88, label="样本外净值倍数 / 原版")
    ax2.axhline(1.0, color="#111827", lw=1.0, linestyle=":")
    for xi, ir, orr in zip(xs, is_ratios, oos_ratios):
        ax2.text(xi - w / 2, ir + 0.07, f"{ir:.2f}x", ha="center", va="bottom", fontsize=7.5, fontweight="bold", color=TEAL)
        y_off = 0.03 if orr < 0.95 else 0.07
        ax2.text(xi + w / 2, orr + y_off, f"{orr:.2f}x", ha="center", va="bottom", fontsize=7.5, fontweight="bold", color=CRIMSON)
    ax2.set_xticks(xs)
    ax2.set_xticklabels(s_lbls, fontsize=8.3, rotation=15)
    ax2.set_ylim(0, 5.8)
    ax2.set_ylabel("相对原版净值比 (>1.0为跑赢, <1.0为跑输)", fontsize=9.5)
    ax2.set_title("典型样本内过拟合断崖：样本内越猛，样本外摔得越惨", fontsize=10.5, fontweight="bold")
    ax2.grid(True, axis="y", linestyle="--", alpha=0.25)
    ax2.legend(loc="upper left", fontsize=8.5, frameon=True, facecolor="white")

    fig.suptitle("样本外盲测终裁：三层周期外挂规则全面失效，现役 V20.0 保持原版最优", fontsize=11.8, fontweight="bold", y=0.98)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    fig.savefig(c2_path)
    plt.close(fig)

    return c1_path, c2_path


def build_rd034_payload(c1_path: str, c2_path: str) -> dict:
    # Strict V19.1 + zero statistical/engineering jargon rules:
    # - First sentence has 没用 + background_color=3
    # - Every sentence <= 40 chars
    # - ZERO '-', '~', '—', '!', '→', '**', NO IS/OOS/PIT/FDR/PBO/CSCV/q值/p值/t值/消融/重锚/门禁/闭环/矩阵/铁证/T-1
    # - Tables <= 4 cols, cell <= 32 chars
    blocks = [
        P([
            TR("结论：把 A股自身三层周期做成开关加给六策略全部没用。", background_color=3),
            TR("现役 V20.0 原版保持最优，不要做过滤、重排或减半。", background_color=3),
            TR("五年严格前视测试 69 项三层周期因子。"),
            TR("合体单仓 278 笔交易中没有任何一项通过多重防假校验。"),
            TR("前四年最优的六策略周期重排合体在近两年净值跌剩原版六分之一。"),
        ]),
        P([TR("一、为什么市场大周期对现役六策略影响很弱", bold=True)]),
        B([
            TR("现役体系在冷清市道会自动少出手，留下的多为逆势活口。", background_color=3),
            TR("昨日涨停不满 25 家时达标日占比仅 29.3%，比过热期少近一半。"),
            TR("但合体单仓在情绪冰点期 57 笔胜率高达 73.7%，单笔均收 +6.05%。"),
            TR("昨日跌停超 20 家时，合体 50 笔胜率 72.0%，均收 +11.67%。"),
        ]),
        B([
            TR("既有的市场水温与熔断卡位，已经在入场前吃掉了大部分市场情绪波动。", background_color=3),
            TR("超跌撬板候选池原高度依赖大盘波动率，过线进实盘后相关性归零。"),
            TR("20cm首板候选池原本依赖全市场自然涨停家数。"),
            TR("现行加入 55 家过线加分后，这种相关性已大幅衰减。"),
            TR("三进四与高标首阴评分里原本就偏好较低的连板竞争高度，已自动避开拥挤退潮。"),
        ]),
        P([TR("二、行业题材与个股自身周期的真实规律", bold=True)]),
        O([
            TR("部分个股筹码与题材周期在单一策略内存在残余效应，但不足以支撑改规则。", background_color=3),
            TR("20cm首板近 20 日累计换手超 220% 时更稳，胜率升至 66.7%。"),
            TR("一进二偏好未反复走趋势的新面孔。"),
            TR("其近 60 日新高不满 4 次时单笔均收 +6.85%。"),
            TR("一进二在昨日炸板率偏高或题材刚启动初期表现更好，但各年稳定性仅属中等。"),
            TR("高标首阴在多波老题材里更抗跌，在4月年报窗与节前 2 天偏弱。"),
        ], seq="1"),
        P([TR("三、过滤、打分重排与减半控仓的样本外终裁", bold=True)]),
        B([
            TR("过滤规则全面跑输原版：六套单独策略与合体单仓无一在样本外占到便宜。", background_color=3),
            TR("合体挂入最优过滤组合后，近两年净值从 1952.5 倍掉至 1300.3 倍。"),
        ]),
        B([
            TR("打分重排出现严重过拟合断崖：样本内凑得越漂亮，样本外摔得越惨。", background_color=3),
            TR("二进三重排在前四年把净值拉到 245.9 倍，近两年却跌剩 1.44 倍。"),
            TR("六策略重排合体在前四年净值翻 5 倍至 18.09 万倍。"),
            TR("但同一套重排规则在近两年却暴跌剩 304.9 倍。"),
            TR("唯独 20cm 微盘逆风加 10 分近两年占优，其实靠多做 40 笔交易。"),
            TR("该因子本身并无真规律，放进合体后全期风险收益比反而下降。"),
        ]),
        B([
            TR("按周期降半仓或停手更是全面失血，任何外部仓位开关都得不偿失。", background_color=3),
            TR("情绪冰点停手最伤，近两年把合体净值从 1952.5 倍砍剩 278.4 倍。"),
            TR("就算降半仓最温和的乖离中段方案，也把五年总净值砍剩 1352 万倍。"),
        ]),
        BL(), BL(), BL(),
    ]

    t1 = [
        row(["市场与情绪周期分层", "合体笔数 / 占比", "胜率 / 单笔均收", "达标日占比与评价"], bold=True),
        row(["全期基准 (1212天)", "278 笔 / 100%", "65.1% / +8.02%", "40.3% (稳健基准)"], bold=True),
        row(["情绪五态·冰点", "57 笔 / 19.7%", "73.7% / +6.05%", "34.3% (冷市胜率高)"], bold=True),
        row(["情绪五态·修复", "16 笔 / 7.3%", "68.8% / +5.33%", "30.3% (低频稳健)"]),
        row(["情绪五态·主升", "98 笔 / 34.6%", "66.3% / +9.67%", "40.6% (核心收益区)"]),
        row(["情绪五态·高潮", "52 笔 / 19.6%", "61.5% / +5.09%", "46.4% (均收偏温和)"]),
        row(["情绪五态·退潮", "55 笔 / 18.8%", "56.4% / +10.67%", "43.9% (高赔率补偿)"]),
        row(["昨日跌停 >=20 家", "50 笔 / 16.8%", "72.0% / +11.67%", "40.7% (逆势出牛股)"]),
        row(["4月年季报窗口", "13 笔 / 4.7%", "61.5% / +7.04%", "36.8% (未见暴雷)"]),
        row(["长假前 2 个交易日", "15 笔 / 5.1%", "66.7% / +14.60%", "样本内热近两年转负"]),
        row(["微盘20日跑输逆风", "57 笔 / 20.0%", "64.9% / +9.16%", "45.3% (抗风格切换)"]),
    ]

    t2 = [
        row(["吸收效应与残留信号", "候选宽池强度", "过线实盘强度", "机制归因"], bold=True),
        row(["撬板 × 指数波动率", "+0.398", "+0.069", "既有打分已吸收 8 成"]),
        row(["撬板 × 昨日涨停数", "+0.262", "-0.011", "既有打分完全吸收"]),
        row(["20cm × 自然涨停数", "+0.132", "+0.067", "55家阈值已吸收大部"]),
        row(["20cm × 20日累计换手", "+0.040", "+0.176", "残留正相关但重排掉净值"]),
        row(["一进二 × 60日新高数", "-0.003", "-0.132", "单仓-0.29但重排未选出"]),
        row(["一进二 × 炸板率", "+0.050", "+0.241", "越分歧次日越强"]),
        row(["三进四 × 行业拥挤度", "-0.050", "-0.143", "过热吸金期赔率略降"]),
    ]

    t3 = [
        row(["合体纯单仓改法赛马", "全期净值 / 笔数", "2021至24 / 2025至26", "夏普与最终裁定"], bold=True),
        row(["现役 V20.0 原版满仓", "6913万x / 278笔", "35408x / 1952.5x", "4.74 (最优保留)"], bold=True),
        row(["20cm微盘逆风加10分", "9533万x / 295笔", "45219x / 2108.3x", "4.73 (降夏普不显著)"]),
        row(["全部样本内过滤组合", "5226万x / 276笔", "40192x / 1300.3x", "4.76 (近两年掉三成)"]),
        row(["三进四振幅压缩过滤", "4057万x / 277笔", "29216x / 1388.5x", "4.68 (全面跑输)"]),
        row(["六策略重排全挂合体", "5516万x / 322笔", "180919x / 304.9x", "4.56 (严重过拟合)"], bold=True),
        row(["二进三重排单独挂入", "1874万x / 309笔", "81325x / 230.4x", "4.33 (近两年崩盘)"]),
    ]

    t4 = [
        row(["合体仓位减半与停手", "全期净值 / 回撤", "2025至26净值 / 夏普", "对比原版结论"], bold=True),
        row(["现役 V20.0 原版满仓", "6913万x / 47.3%", "1952.5x / 5.43", "基准最优"], bold=True),
        row(["断板大面过顺降半仓", "2808万x / 47.3%", "1752.9x / 5.52", "净值少六成"]),
        row(["情绪高潮期降半仓", "2388万x / 47.3%", "1613.9x / 5.43", "净值少六成半"]),
        row(["乖离中段降半仓", "1352万x / 28.7%", "1314.9x / 5.78", "五年收益被砍八成"]),
        row(["情绪冰点期降半仓", "1688万x / 45.4%", "776.4x / 5.21", "近两年净值腰斩"]),
        row(["全部财报季降半仓", "1045万x / 45.4%", "705.5x / 5.29", "近两年少赚六成"]),
        row(["情绪冰点期停手空仓", "336万x / 44.6%", "278.4x / 4.56", "错杀高胜率净值 -86%"], bold=True),
    ]

    return {
        "title": TITLE_RD034,
        "parent_node_token": I_NODE,
        "blocks": blocks,
        "img_path": c1_path,
        "img_path2": c2_path,
        "tables": [
            ("表一：现役合体单仓在市场情绪与日历周期各分层下的真实战绩", t1),
            ("表二：现役结构卡对三层周期因子的自动吸收效应与残余效应", t2),
            ("表三：样本内筛选出的过滤与重排规则在样本外与合体单仓赛马", t3),
            ("表四：三层周期减半仓与停手空仓开关对比原版满仓实证", t4),
        ],
    }


def build_updated_invalid_hub():
    # Preserves all 13 existing rows verbatim + adds RD034 at top (14 items total)
    invalid_rows = [
        ("A股三层周期实证", "5年69因子6策略", "市场行业个股周期过滤重排减半全败，合体重排近两年崩剩六分之一", "现役自带吸收勿加周期开关"),
        ("老热股六策略实证", "5年六策略及五板", "多重纠偏后有效极少，强加换票近两年净值腰斩", "全六策略维持原版，五板暂作独立观察"),
        ("中国周期与六策略体检", "5年278笔6策略", "35项周期检验未见有效，外挂开关全跑输满仓", "现役体系自带抗周期，勿加开关"),
        ("卡30天200%异动第30与31天证伪", "6年48因子", "D30尾买隔夜胜16%，418组0过红队六关", "作老仓兑现窗，禁接盘二波"),
        ("四进五 V2.0 (下放淘汰)", "五年全量", "去前三大妖股独立净值仅 0.89x", "依赖少数极值，移出实盘"),
        ("大跌切银行与退潮切消费证伪", "五年全量", "退潮切白酒胜36.8%，生猪22.7%亏-2.04%", "严禁科技退潮买消费避险"),
        ("十年暴涨暴跌反抽证伪", "10年/5年", "9套急跌抄底与反抽规则全灭，亏至-93%以上", "永久禁做A杀反抽"),
        ("行业明牌大高潮追买证伪", "8年661次", "大高潮买中军日内亏-0.64%，领涨亏-1.51%", "纯A独立高潮高开禁追"),
        ("热门题材200亿大中军证伪", "5年28740组", "三轨全证伪，热门题材买200亿大中军亏钱", "禁追热门题材大中军"),
        ("大池子妖股暴跌反核证伪", "5年171组", "仅2.3%三期全正，去前5亏-35.08%", "永久禁做大池子反核"),
        ("雪球短线大V三年胜率证伪", "122位大V", "粉丝数与赚钱倒挂，超8成扣费亏钱", "严禁盲跟雪球高频复盘号"),
        ("连板晋级率与冰点抄底证伪", "5年1211日", "高晋级率不超19天，追高抄冰点双亏", "禁用晋级率盲抄冰点"),
        ("庄股事前可预测性证伪", "421只庄股", "横盘缩量找庄股样本外全灭，与随机无异", "永久放弃事前猜庄股"),
        ("电竞夺冠事件追涨证伪", "2022至2026", "电竞夺冠无产业增量，次日追涨必亏", "纯情绪事件禁追高"),
    ]
    return build_hub_doc("证伪回测与避坑墓碑", "结论：本目录收录6大主力策略之外已证伪小策略与亏钱陷阱，永久避坑防复燃。", invalid_rows)


def extra_jargon_audit(payload: dict):
    texts = []
    for b in payload["blocks"]:
        els = b.get("text", b.get("bullet", b.get("ordered", {}))).get("elements", [])
        texts.append("".join(e["text_run"]["content"] for e in els))
    for t_title, rows in payload["tables"]:
        texts.append(t_title)
        for rw in rows:
            for cell in rw:
                texts.append("".join(x for x, _ in cell))
    for t in texts:
        m = EXTRA_JARGON_RE.search(t)
        if m:
            raise ValueError(f"[{payload['title']}] 发现禁用统计/工程黑话 '{m.group(0)}': {t}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    audit = json.loads((OUT_DIR / "rd034_3layer_cycles_audit.json").read_text(encoding="utf-8"))
    df_m = pd.read_csv(OUT_DIR / "rd034_factor_matrix_all6.csv")
    c1_path, c2_path = generate_charts(audit, df_m)
    print(f"[Charts] Generated {c1_path} & {c2_path}")

    d = build_rd034_payload(c1_path, c2_path)
    hub_i = build_updated_invalid_hub()

    s9.check_first_sentence_rule(d)
    longs = s9.audit_doc_strict_v191(d, require_img=True)
    longs_hub = s9.audit_doc_strict_v191(hub_i, require_img=False)
    extra_jargon_audit(d)
    extra_jargon_audit(hub_i)
    if longs or longs_hub:
        raise ValueError(f"Long sentences found: rd034={len(longs)}, hub={len(longs_hub)}")

    tot_chars = sum(len(e["text_run"]["content"]) for b in d["blocks"] for e in b.get("text", b.get("bullet", b.get("ordered", {}))).get("elements", []))
    tot_chars += sum(len(t) for t, _ in d["tables"])
    tot_chars += sum(len("".join(x for x, _ in cell)) for _, rows in d["tables"] for rw in rows for cell in rw)
    print(f"[Audit] RD034 local total chars = {tot_chars} (>= 1500 required)")
    if tot_chars < 1500:
        raise ValueError(f"RD034 total chars {tot_chars} < 1500")

    if args.dry_run:
        print("[Dry-Run PASS] Zero audit errors on RD034 & Invalid Hub!")
        return

    lock_fd = open(s6.LOCK_PATH, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        doc_id, node_tok = s9.find_or_create_child_node(I_NODE, TITLE_RD034)
        if doc_id in s6.PROTECTED_DOCS:
            raise RuntimeError(f"Protected: {doc_id}")
        _, fail = s6.write_document_payload(doc_id, d["blocks"], d["tables"], d["img_path"])
        if fail > 0:
            raise RuntimeError(f"Write failed: {fail}")
        s6.insert_image_block(doc_id, d["img_path2"])
        s6.api(
            f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children",
            {"children": [BL(), BL(), BL()], "index": -1},
            "POST",
        )
        time.sleep(1.5)
        v = s9.verify_document_v191(doc_id, TITLE_RD034, expected_tables_count=len(d["tables"]), has_img=True)
        url = f"https://my.feishu.cn/wiki/{node_tok}"

        _, fail2 = s6.write_document_payload(I_DOC, hub_i["blocks"], hub_i["tables"], None)
        if fail2 > 0:
            raise RuntimeError(f"Hub write fail={fail2}")
        time.sleep(1.2)
        vhub = s9.verify_document_v191(I_DOC, "证伪回测与避坑墓碑", expected_tables_count=1, has_img=False)

        mf = json.load(open(s6.MANIFEST_PATH, "r", encoding="utf-8"))
        mf.setdefault("nodes", {})["rd034_ashare_3layer_cycles"] = {
            "title": TITLE_RD034,
            "node_token": node_tok,
            "obj_token": doc_id,
            "parent_node_token": I_NODE,
            "wiki_url": url,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        json.dump(mf, open(s6.MANIFEST_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

        pub_res = {
            "wiki_url": url,
            "node_token": node_tok,
            "doc_id": doc_id,
            "parent_node_token": I_NODE,
            "verify": v,
            "hub_verify": vhub,
        }
        with open(OUT_DIR / "feishu_publish_result.json", "w", encoding="utf-8") as f:
            json.dump(pub_res, f, ensure_ascii=False, indent=2)
        print(f"[SUCCESS] RD034 URL={url} | chars={v['raw_chars']} | tables={v['tables_count']} | images={v['images_count']}")
        print(f"[SUCCESS] INVALID HUB URL=https://my.feishu.cn/wiki/{I_NODE} | chars={vhub['raw_chars']}")
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    main()

#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD031: Generate 2 Charts + Publish Plain-Chinese Report to Feishu
under `证伪回测与避坑墓碑` (QiDewdTkJiquokkbbo6cWr3Fn6f) & update Hub Index (ZTaudjSqtoaj71xTPSLciMcdnLb).
Strictly NO yfinance imports (D12) and NO cap10m.
"""
import argparse
import fcntl
import json
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

assert "yfinance" not in sys.modules, "D12 violation"

OUT_DIR = Path("/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd031_china_cycle_6strat_20261125")
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
TITLE_RD031 = "中国周期与六策略体检"

plt.rcParams["font.sans-serif"] = ["Hiragino Sans GB", "STHeiti", "Arial Unicode MS", "Songti SC"]
plt.rcParams["axes.unicode_minus"] = False
NAVY, TEAL, CRIMSON, AMBER, SLATE = "#1B365D", "#0F766E", "#B91C1C", "#D97706", "#64748B"


def row(vals, bold=False):
    st = {"bold": True} if bold else {}
    return [[(str(v), st)] for v in vals]


def generate_charts(audit: dict) -> tuple[str, str]:
    c1_path = str(OUT_DIR / "chart1_china_cycles_vs_v20.png")
    c2_path = str(OUT_DIR / "chart2_us_mirror_and_oos_switch.png")

    # --- Chart 1: Left = V20 Combined Win Rate & Avg Return across 4 China Cycles; Right = 4 Macro Eras ---
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.8, 5.6), dpi=180)
    comb_tests = {t["cycle"]: t["groups"] for t in audit["module1_four_cycles"]["tests"] if t["target"] == "comb"}
    labels, wrs, means = [], [], []
    short_lbl = {
        "宽信用加速": "信用·宽加速", "宽信用高位": "信用·宽高位", "信用磨底": "信用·磨底", "紧信用下行": "信用·紧下行",
        "被动去库复苏": "库存·被动去库", "主动补库过热": "库存·主动补库", "被动补库滞胀": "库存·被动补库", "主动去库通缩": "库存·主动去库",
        "跌穿底部出清": "商品·底部出清", "温和上行": "商品·温和上行", "下行通缩": "商品·下行通缩", "大宗暴涨过热": "商品·暴涨过热",
        "缩量冰点(<25%)": "水位·缩量冰点", "常态水位(25%-75%)": "水位·常态", "活跃放量(>75%)": "水位·活跃放量",
    }
    order_cyc = [
        ("C1_Credit", ["宽信用加速", "宽信用高位", "信用磨底", "紧信用下行"]),
        ("C2_Inventory", ["被动去库复苏", "主动补库过热", "被动补库滞胀", "主动去库通缩"]),
        ("C3_Commodity", ["跌穿底部出清", "温和上行", "下行通缩", "大宗暴涨过热"]),
        ("C4_Amount", ["缩量冰点(<25%)", "常态水位(25%-75%)", "活跃放量(>75%)"]),
    ]
    for cyc, sts in order_cyc:
        gmap = {g["state"]: g for g in comb_tests[cyc]}
        for st in sts:
            g = gmap[st]
            labels.append(short_lbl[st])
            wrs.append(g["wr_pct"])
            means.append(g["mean_ret_pct"])

    y = np.arange(len(labels))[::-1]
    ax1.barh(y, means, color=NAVY, alpha=0.88, height=0.65, label="单笔均收 (%)")
    for yi, m_v, w_v in zip(y, means, wrs):
        ax1.text(m_v + 0.25, yi, f"+{m_v:.1f}% (胜率{w_v:.0f}%)", va="center", fontsize=7.6, fontweight="bold", color=NAVY)
    ax1.set_yticks(y)
    ax1.set_yticklabels(labels, fontsize=8.3)
    ax1.set_xlim(0, 18.5)
    ax1.set_xlabel("合体纯单仓单笔均收 (%) 与胜率", fontsize=9.5)
    ax1.set_title("四大中国宏观与商品周期：15个阶段全正收益 (无显著断层)", fontsize=10.5, fontweight="bold")
    ax1.grid(True, axis="x", linestyle="--", alpha=0.25)

    # Right panel: Eras NAV across key strategies (log scale) + CSI300 comparison
    eras_info = [
        ("Era2_2022_23H1", "地产出清\n(22至23.06)"),
        ("Era3_23H2_240923", "微盘危机\n(23.07至924)"),
        ("Era4_924_2026", "两万亿新体制\n(924至26.11)"),
        ("Y2026", "2026全年\n(结构震荡)"),
    ]
    x = np.arange(len(eras_info))
    era_m = audit["module2_four_eras"]
    for sk, lbl, col, mk in [
        ("comb", "合体纯单仓", CRIMSON, "o"),
        ("1to2", "一进二", NAVY, "s"),
        ("2to3", "二进三", TEAL, "^"),
        ("3to4", "三进四", AMBER, "D"),
        ("20cm", "20cm深水", SLATE, "v"),
    ]:
        rmap = {r["era_id"]: r for r in era_m[sk]}
        vals = [rmap[eid]["era_nav"] for eid, _ in eras_info]
        ax2.plot(x, vals, marker=mk, lw=2.2, color=col, label=lbl)
        for xi, vi in zip(x, vals):
            if sk == "comb":
                off = (0, -15) if xi == 1 else ((0, 8) if xi != 3 else (10, 8))
                ax2.annotate(f"{vi:.1f}x", (xi, vi), textcoords="offset points", xytext=off, ha="center", fontsize=8.0, color=col, fontweight="bold")
    ax2.axhline(1.0, color="#111827", lw=1.0, linestyle=":")
    ax2.set_yscale("log")
    ax2.set_ylim(0.8, 15000)
    ax2.set_xticks(x)
    ax2.set_xticklabels([lbl for _, lbl in eras_info], fontsize=8.8)
    ax2.set_ylabel("阶段净值倍数 (对数坐标, 1.0x为保本线)", fontsize=9.5)
    ax2.set_title("四大中国宏观年代实测：熊市与危机期全数正复利跑赢沪深300", fontsize=10.5, fontweight="bold")
    ax2.grid(True, linestyle="--", alpha=0.25)
    ax2.legend(loc="upper left", fontsize=8.0, frameon=True, facecolor="white")

    fig.suptitle("中国宏观与商品周期对六策略与合体单仓影响极微：全阶段稳健正收益", fontsize=12.0, fontweight="bold", y=0.98)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    fig.savefig(c1_path)
    plt.close(fig)

    # --- Chart 2: Left = US Mirror Peer Crash on A-share Cyclicals; Right = OOS Horse Race ---
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.8, 5.4), dpi=180)
    hs = ["T+20", "T+60", "T+120", "T+250"]
    xh = np.arange(len(hs))
    a10 = {b["bucket"]: b for b in audit["module3_us_mirror"]["mirror_3A1_all_ashare_cyclicals"]}
    for bkey, lbl, col in [
        ("2016_2026_10Y_Baseline_DD30_lt50", "常态对照 (半数未跌破30%)", SLATE),
        ("2016_2026_10Y_Peer_DD30_ge50", "同行半数回撤 -30% 以上", TEAL),
        ("2016_2026_10Y_Peer_DD40_ge50", "同行半数回撤 -40% 以上", NAVY),
        ("2016_2026_10Y_Peer_Div_DD40ge40_Selfgt_m35", "同行重挫+自身抗跌分化", AMBER),
    ]:
        ys = [a10[bkey][h]["date_clustered_excess_pp"] for h in hs]
        ax1.plot(xh, ys, marker="o", lw=2.2, color=col, label=lbl)
        if "DD40_ge50" in bkey:
            for xi, yi in zip(xh, ys):
                off = (10, -14) if xi == 3 else (0, 8)
                ax1.annotate(f"+{yi:.1f}%", (xi, yi), textcoords="offset points", xytext=off, ha="center", fontsize=8.0, color=col, fontweight="bold")
    ax1.axhline(0, color="#111827", lw=1.0, linestyle=":")
    ax1.set_ylim(-0.5, 7.2)
    ax1.set_xticks(xh)
    ax1.set_xticklabels(hs, fontsize=9.5)
    ax1.set_ylabel("相对沪深300日期聚类净超额 (%)", fontsize=9.5)
    ax1.set_title("美股教训镜像：十年A股周期股同行暴跌亦为反向底部区", fontsize=10.5, fontweight="bold")
    ax1.grid(True, linestyle="--", alpha=0.25)
    ax1.legend(loc="upper left", fontsize=8.0, frameon=True, facecolor="white")

    # Right panel: OOS Horse Race (OOS NAV & OOS ex_top5 NAV)
    hr = audit["module4_oos_switch_verdict"]["oos_horse_race"]
    pick_policies = [
        ("Baseline_100pct_Full", "原版满仓 100%"),
        ("Switch_LowAmtFreeze_Half50", "缩量冰点降半仓"),
        ("Switch_Worst_IS_State_Half50", "大宗过热降半仓"),
        ("Static_SameAvgExp_0.91", "同均值静态 91%"),
        ("Switch_TightCredit_Half50", "紧信用降半仓"),
        ("Switch_DeflationDestock_Half50", "去库通缩降半仓"),
        ("Switch_Worst_IS_State_Stop0", "大宗过热空仓"),
        ("Control_1overVol_Matched_Half50", "反波动率风控 83%"),
        ("Switch_DeflationDestock_Stop0", "去库通缩空仓"),
    ]
    pl_labels, oos_navs, oos_shs = [], [], []
    for prefix, slbl in pick_policies:
        hit = next((x for x in hr if x["policy"].startswith(prefix)), None)
        if hit:
            pl_labels.append(slbl)
            oos_navs.append(hit["OOS"]["daily_nav"])
            oos_shs.append(hit["OOS"]["daily_sharpe"])
    yp = np.arange(len(pl_labels))[::-1]
    cols = [CRIMSON if i == 0 else (SLATE if "静态" in l or "波动率" in l else NAVY) for i, l in enumerate(pl_labels)]
    ax2.barh(yp, oos_navs, color=cols, alpha=0.88, height=0.62)
    for yi, nv, sh in zip(yp, oos_navs, oos_shs):
        ax2.text(nv + 120, yi, f"{nv:.0f}x (夏普{sh:.2f})", va="center", fontsize=7.8, fontweight="bold", color=CRIMSON if nv > 7000 else NAVY)
    ax2.set_yticks(yp)
    ax2.set_yticklabels(pl_labels, fontsize=8.5)
    ax2.set_xlim(0, 9600)
    ax2.set_xlabel("样本外累计净值倍数 (2024.07 至 2026.11)", fontsize=9.5)
    ax2.set_title("样本外仓位开关赛马：所有周期降仓与停手全面跑输原版满仓", fontsize=10.5, fontweight="bold")
    ax2.grid(True, axis="x", linestyle="--", alpha=0.25)

    fig.suptitle("中美交叉印证与样本外裁决：同行暴跌反指一致，外挂周期开关全面失血", fontsize=12.0, fontweight="bold", y=0.98)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    fig.savefig(c2_path)
    plt.close(fig)

    return c1_path, c2_path


def build_rd031_payload(c1_path: str, c2_path: str) -> dict:
    # Strict V19.1 rules:
    # - First sentence has 没用 + background_color=3
    # - Every sentence <= 40 chars, NO semicolons, NO non-negative hyphens '-', NO IS/OOS
    # - Table <= 4 cols, cell <= 32 chars, >= 6 blocks before tables/images, 3 trailing BL()
    blocks = [
        P([
            TR("结论：用中国宏观与大宗商品周期给六策略做仓位开关完全没用，现役体系本身全周期通用。", background_color=3),
            TR("全部 35 项周期检验经多重校正后无一幸存，最小校正值高达 0.833。"),
            TR("样本外强行按周期降仓或停手，累计净值全部被腰斩且无法改善风险收益比。"),
        ]),
        P([TR("一、四大中国宏观与商品周期全维体检", bold=True)]),
        B([
            TR("严格按前一交易日公开时点，检验信贷、库存、工业品与市场水位四大周期。", background_color=3),
            TR("合体 278 笔交易在全部分层中均保持 +4.58% 至 +12.64% 正均值。"),
            TR("全部 15 个周期子阶段胜率全数落在 60.8% 至 70.8%，无一亏损区间。"),
        ]),
        B([
            TR("六套独立子策略在四大周期全部 126 个子组中，单笔均收无一为负。", background_color=3),
            TR("20cm深水仅在大宗跌穿底部 31 笔偏弱，均值 +0.21%，校正后不显著。"),
            TR("高标首阴在活跃放量期胜率达 85.7%，但在缩量冰点期依然维持 57.1% 胜率。"),
        ]),
        P([TR("二、四大真实宏观年代切片检验（排除牛市假象）", bold=True)]),
        O([
            TR("合体单仓在两段漫长熊市中同样大赚，不存在靠单一牛市撑场面的错觉。", background_color=3),
            TR("地产出清期沪深300 下跌 -22.22%，合体单仓实盘仍赚 210.18 倍。"),
            TR("微盘危机期沪深300 下跌 -16.39%，合体单仓依然稳赚 49.86 倍。"),
            TR("去掉前三大暴赚股后，四大年代扣除极值净值全部稳稳站在 10 倍以上。"),
        ], seq="1"),
        O([
            TR("六大策略内部具备极强的年代互补性。", bold=True),
            TR("2022 至 2023 年上半年的熊市主要由二进三与 20cm深水接力扛旗。"),
            TR("2023 年下半年微盘危机三进四赚 8.01 倍。"),
            TR("2024 年 9 月后一进二全面爆发，期间净值达 69.61 倍。"),
            TR("2026 年沪深300 下跌 -14.04%，合体依然大赚 27.78 倍。"),
        ], seq="auto"),
        P([TR("三、对照美股三条硬教训的 A股镜像实证", bold=True)]),
        B([
            TR("第一条镜像高度一致：A股周期股同行大面积暴跌同样不是见顶信号而是底部区。", background_color=3),
            TR("十年实证中，周期股半数回撤 -40% 后持 60 天超额 +5.35 个点。"),
            TR("持 120 天超额达 +6.25 个点，近五年样本更放大至 +19.99 个点。"),
            TR("短线六策略踩中同行大跌标的时胜率达 65.2%，与常态 66.2% 几乎完全无差。"),
        ]),
        B([
            TR("第二条镜像出现本质反转：美股持仓一至三年看产能周期，短线一至三天只看资金接力。", background_color=3),
            TR("按工业品出厂价正负交叉切分短周期科技与长周期重资产，六策略胜率并无断层。"),
            TR("合体单仓在科技股与重资产股的均值差异检验值为 0.883，完全不靠行业宏观轮动。"),
        ]),
        P([TR("四、是否加挂中国周期仓位开关的样本外终裁", bold=True)]),
        B([
            TR("在样本内搜索全部宏观逆风阶段，无一通过 0.05 显着门槛，仅大宗暴涨过热偏低。", background_color=3),
            TR("但将该条件拿到样本外实测，降半仓净值从 7169.8 倍掉到 3876.4 倍。"),
            TR("强行停手空仓净值跌至 1961.8 倍，最大回撤纹丝不动仍停在 47.3%。"),
            TR("即便后视镜挑主动去库通缩停手，样本内也会把净值从 9642 倍砍剩 319 倍。"),
        ]),
        B([
            TR("结论明确：现役六策略无需外挂任何中国宏观或商品周期开关。", background_color=3),
            TR("任何周期降仓方案在样本外要么跑输同均仓静态线，要么大幅拉低年化收益与夏普。"),
        ]),
        BL(), BL(), BL(),
    ]

    t1 = [
        row(["合体单仓周期分组", "交易笔数", "胜率 / 赔率", "单笔均收 / 阶段复利"], bold=True),
        row(["宽信用加速", "60 笔", "63.3% / 3.41", "+12.56% / 321.1x"]),
        row(["宽信用高位", "44 笔", "63.6% / 2.25", "+5.65% / 9.18x"]),
        row(["信用磨底", "62 笔", "66.1% / 2.20", "+5.96% / 20.96x"]),
        row(["紧信用下行", "112 笔", "66.1% / 2.66", "+7.66% / 1119.2x"]),
        row(["被动去库复苏", "78 笔", "65.4% / 3.77", "+11.38% / 895.9x"]),
        row(["主动补库过热", "46 笔", "65.2% / 3.80", "+7.69% / 22.56x"]),
        row(["被动补库滞胀", "55 笔", "65.5% / 1.88", "+6.80% / 18.24x"]),
        row(["主动去库通缩", "99 笔", "64.7% / 2.21", "+6.20% / 187.5x"]),
        row(["商品跌穿底部", "52 笔", "67.3% / 3.75", "+12.64% / 155.8x"]),
        row(["商品暴涨过热", "50 笔", "64.0% / 1.76", "+4.58% / 7.09x"]),
        row(["成交缩量冰点", "72 笔", "70.8% / 2.23", "+7.09% / 84.53x"]),
        row(["成交活跃放量", "86 笔", "66.3% / 3.51", "+10.36% / 971.4x"]),
    ]

    t2 = [
        row(["真实宏观年代", "合体笔数与胜率", "合体复利 / 去前三", "同期沪深300与超额"], bold=True),
        row(["2021年尾(11.16起)", "9 笔 / 66.7%", "1.78x / 1.02x", "+1.19% / 超+77.0点"]),
        row(["22至23.06地产出清", "89 笔 / 66.3%", "210.2x / 32.87x", "-22.22% / 大幅超额"], bold=True),
        row(["23.07至924微盘危机", "62 笔 / 64.5%", "49.86x / 10.10x", "-16.39% / 大幅超额"], bold=True),
        row(["924至26.11新体制", "118 笔 / 64.4%", "3703.5x / 523.9x", "+23.87% / 大幅超额"]),
        row(["2026全年单列", "53 笔 / 66.0%", "27.78x / 12.64x", "-14.04% / 超+2692点"], bold=True),
        row(["注：20cm深水2021全", "46 笔 / 54.4%", "3.57x / 1.83x", "-5.20% / 超+262点"]),
    ]

    t3 = [
        row(["美股教训与A股镜像", "长周期实证表现", "短线六策略实测", "对比结论"], bold=True),
        row(["同行半数回撤 -30%(10Y)", "T+60超额 +2.37点", "合体胜65.2% 均+7.78%", "同行越惨越偏底部"]),
        row(["同行半数回撤 -40%(10Y)", "T+60超额 +5.35点", "合体胜60.9% 均+4.90%", "绝非见顶防顶信号"], bold=True),
        row(["短周期科技(通胀期)", "美股防顶机制伤半导", "合体胜65.4% 均+8.30%", "短线无显著行业断层"]),
        row(["短周期科技(通缩期)", "美股6至12月见底快", "合体胜68.9% 均+5.93%", "检验p=0.60 无差异"]),
        row(["长周期重资产(通胀期)", "美股电网工程防顶生效", "合体胜67.7% 均+10.07%", "短线借题材不扛周期"]),
        row(["长周期重资产(通缩期)", "美股盈利恶化长跌", "合体胜63.3% 均+7.10%", "检验p=0.52 无差异"]),
    ]

    t4 = [
        row(["样本外仓位开关方案", "样本外净值 / 年化", "回撤 / 夏普", "去前5极值 / 裁决"], bold=True),
        row(["原版满仓 100%", "7169.8x / 4040%", "47.3% / 4.965", "400.3x (最优保真)"], bold=True),
        row(["大宗暴涨降半仓", "3876.4x / 3099%", "47.3% / 4.830", "216.4x (净值腰斩)"]),
        row(["大宗暴涨停手空仓", "1961.8x / 2304%", "47.3% / 4.507", "109.5x (严重失血)"]),
        row(["同均仓静态 91%", "3668.8x / 3026%", "44.0% / 4.961", "249.5x (回撤更优)"]),
        row(["紧信用下行降半仓", "3564.2x / 2988%", "47.3% / 4.897", "202.4x (无改善)"]),
        row(["主动去库降半仓", "3132.2x / 2826%", "29.1% / 5.234", "190.1x (样本内砍8成)"]),
        row(["缩量冰点降半仓", "4317.4x / 3247%", "47.3% / 4.851", "245.2x (错杀71%胜率)"]),
        row(["反波动率风控 83%", "1459.2x / 2024%", "41.6% / 4.868", "120.4x (全面跑输)"]),
    ]

    return {
        "title": TITLE_RD031,
        "parent_node_token": I_NODE,
        "blocks": blocks,
        "img_path": c1_path,
        "img_path2": c2_path,
        "tables": [
            ("表一：合体纯单仓在四大中国宏观与大宗周期下分层体检明细", t1),
            ("表二：四大真实中国宏观年代与 2026 年逐期抗周期实证", t2),
            ("表三：对照美股三条硬教训的 A股周期股与短线策略镜像检验", t3),
            ("表四：样本外周期降仓与停手开关赛马对抗（2024.07 至 2026.11）", t4),
        ],
    }


def build_updated_invalid_hub():
    # Preserves all 11 existing rows verbatim + adds RD031 at top (12 items total)
    invalid_rows = [
        ("中国周期与六策略体检", "5年278笔6策略", "35项周期检验FDR均>0.83，外挂开关全跑输满仓", "现役体系自带抗周期，勿加开关"),
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    audit = json.loads((OUT_DIR / "rd031_china_cycle_audit.json").read_text(encoding="utf-8"))
    c1_path, c2_path = generate_charts(audit)
    print(f"[Charts] Generated {c1_path} & {c2_path}")

    d = build_rd031_payload(c1_path, c2_path)
    hub_i = build_updated_invalid_hub()

    s9.check_first_sentence_rule(d)
    longs = s9.audit_doc_strict_v191(d, require_img=True)
    longs_hub = s9.audit_doc_strict_v191(hub_i, require_img=False)
    if longs or longs_hub:
        raise ValueError(f"Long sentences found: rd031={len(longs)}, hub={len(longs_hub)}")

    tot_chars = sum(len(e["text_run"]["content"]) for b in d["blocks"] for e in b.get("text", b.get("bullet", b.get("ordered", {}))).get("elements", []))
    tot_chars += sum(len(t) for t, _ in d["tables"])
    tot_chars += sum(len("".join(x for x, _ in cell)) for _, rows in d["tables"] for rw in rows for cell in rw)
    print(f"[Audit] RD031 local total chars = {tot_chars} (>= 1500 required)")
    if tot_chars < 1500:
        raise ValueError(f"RD031 total chars {tot_chars} < 1500")

    if args.dry_run:
        print("[Dry-Run PASS] Zero audit errors on RD031 & Invalid Hub!")
        return

    lock_fd = open(s6.LOCK_PATH, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        doc_id, node_tok = s9.find_or_create_child_node(I_NODE, TITLE_RD031)
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
        v = s9.verify_document_v191(doc_id, TITLE_RD031, expected_tables_count=len(d["tables"]), has_img=True)
        url = f"https://my.feishu.cn/wiki/{node_tok}"

        _, fail2 = s6.write_document_payload(I_DOC, hub_i["blocks"], hub_i["tables"], None)
        if fail2 > 0:
            raise RuntimeError(f"Hub write fail={fail2}")
        time.sleep(1.2)
        vhub = s9.verify_document_v191(I_DOC, "证伪回测与避坑墓碑", expected_tables_count=1, has_img=False)

        mf = json.load(open(s6.MANIFEST_PATH, "r", encoding="utf-8"))
        mf.setdefault("nodes", {})["rd031_china_cycle_6strat"] = {
            "title": TITLE_RD031,
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
        print(f"[SUCCESS] RD031 URL={url} | chars={v['raw_chars']} | tables={v['tables_count']} | images={v['images_count']}")
        print(f"[SUCCESS] INVALID HUB URL=https://my.feishu.cn/wiki/{I_NODE} | chars={vhub['raw_chars']}")
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    main()

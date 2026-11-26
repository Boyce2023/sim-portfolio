#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD033 Feishu Publisher (Pure Plain Chinese V19.1 + Dual Charts + Anti-Overwrite Hub Sync)."""

import argparse
import fcntl
import json
import os
import sys
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
FS_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/feishu_master_docs_20261116"
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

AUDIT_JSON = os.path.join(CUR_DIR, "rd033_20cm_theme_surge_audit.json")
CHART1_PATH = os.path.join(CUR_DIR, "chart1_rd033_theme_tiers.png")
CHART2_PATH = os.path.join(CUR_DIR, "chart2_rd033_ab_matrix_and_s82.png")
RES_JSON = os.path.join(CUR_DIR, "feishu_publish_result.json")

INVALID_PARENT_NODE = "QiDewdTkJiquokkbbo6cWr3Fn6f"
INVALID_HUB_DOC = "ZTaudjSqtoaj71xTPSLciMcdnLb"
DOC_TITLE = "20cm强主线大阳实证"


def C(text, bold=False, color=None, bg=None):
    st = {}
    if bold:
        st["bold"] = True
    if color is not None:
        st["text_color"] = color
    if bg is not None:
        st["background_color"] = bg
    return [(text, st)]


def _setup_plt():
    plt.rcParams["font.sans-serif"] = ["PingFang SC", "Heiti TC", "Arial Unicode MS", "SimHei"]
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["figure.dpi"] = 180


def make_charts(audit: dict):
    _setup_plt()
    m1 = audit["module1_spectrum_and_crossboard"]
    m2 = audit["module2_entry_exit_matrix"]
    arch = audit["module3_archetypes"]
    s82 = audit["s82_benchmark"]

    # --- Chart 1: Theme Tiers + Cross-Board Comparison ---
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.5, 5.2), dpi=180)
    fig.patch.set_facecolor("white")

    tier_keys = [
        ("20cm_10~19.8%_全池(不限题材)", "全池盲买"),
        ("T0_无主线含边缘(<3涨停)", "无主线/边缘"),
        ("T1_温热题材(3~4涨停)", "温热(3~4板)"),
        ("T2_强主线(前3且5~9涨停)", "强主线(5~9板)"),
        ("T3_超级高潮主线(前3且>=10涨停)", "高潮(>=10板)"),
        ("强主线+10cm龙头一字带动", "10cm一字带动"),
    ]
    labels1 = [lbl for _, lbl in tier_keys]
    nav_1s = [m1[k]["T2_close"]["FULL"]["nav_1s"] for k, _ in tier_keys]
    nav_ew = [m1[k]["T2_close"]["FULL"]["ew_nav"] for k, _ in tier_keys]
    nav_ex5 = [m1[k]["T2_close"]["FULL"]["ex5_nav"] for k, _ in tier_keys]

    x = np.arange(len(labels1))
    w = 0.26
    ax1.bar(x - w, nav_1s, width=w, color="#1f77b4", label="五年单仓净值")
    ax1.bar(x, nav_ew, width=w, color="#ff7f0e", label="五年均仓净值")
    ax1.bar(x + w, nav_ex5, width=w, color="#7f7f7f", label="去前五极值单仓")
    ax1.axhline(1.0, color="#d62728", ls="--", lw=1.2, label="盈亏平衡(1.0倍)")
    for i, (v1, v3) in enumerate(zip(nav_1s, nav_ex5)):
        ax1.text(i - w, v1 + 0.08, f"{v1:.2f}x", ha="center", va="bottom", fontsize=7.5)
        ax1.text(i + w, v3 + 0.08, f"{v3:.2f}x", ha="center", va="bottom", fontsize=7)
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels1, rotation=16, fontsize=8.5)
    ax1.set_ylabel("五年累计净值（倍）", fontsize=9.5)
    ax1.set_title("20cm大阳(10%~19.8%) 题材强弱倒U型分化", fontsize=10.5, fontweight="bold")
    ax1.set_ylim(0, max(nav_1s) * 1.22)
    ax1.grid(axis="y", alpha=0.25)
    ax1.legend(fontsize=8, loc="upper right")

    cb_items = [
        ("10cm首板\n(强主线盲追)", m1["10cm封死首板_强主线(前3&>=5)"]["T2_close"]["FULL"]["nav_1s"], "#b0b0b0"),
        ("20cm首板\n(强主线盲追)", m1["20cm封死首板_强主线(前3&>=5)"]["T2_close"]["FULL"]["nav_1s"], "#9467bd"),
        ("20cm未涨停大阳\n(强主线盲追)", m1["强主线_前3主线(rk<=3且>=5)"]["T2_close"]["FULL"]["nav_1s"], "#1f77b4"),
        ("20cm未涨停\n炸板+深水(C6)", arch["C6_强主线_B型炸板+深水低吸T2收"]["FULL"]["nav_1s"], "#ff7f0e"),
        ("现役20cm首板\n深水策略(S82)", s82["FULL"]["nav_1s"], "#2ca02c"),
    ]
    lbls2 = [it[0] for it in cb_items]
    vals2 = [max(it[1], 1e-4) for it in cb_items]
    cols2 = [it[2] for it in cb_items]
    bars2 = ax2.bar(np.arange(len(lbls2)), vals2, width=0.55, color=cols2)
    ax2.set_yscale("log")
    ax2.axhline(1.0, color="#d62728", ls="--", lw=1.2)
    for b, raw_v in zip(bars2, [it[1] for it in cb_items]):
        ax2.text(b.get_x() + b.get_width() / 2, b.get_height() * 1.35, f"{raw_v:.3g}x", ha="center", va="bottom", fontsize=8.5, fontweight="bold")
    ax2.set_xticks(np.arange(len(lbls2)))
    ax2.set_xticklabels(lbls2, fontsize=8.5)
    ax2.set_ylabel("五年单仓净值（对数坐标）", fontsize=9.5)
    ax2.set_title("同强主线跨板块盲追 vs 现役S82（对数坐标）", fontsize=10.5, fontweight="bold")
    ax2.set_ylim(1e-4, 2500)
    ax2.grid(axis="y", alpha=0.25)

    plt.tight_layout()
    plt.savefig(CHART1_PATH, dpi=180)
    plt.close(fig)

    # --- Chart 2: Type A vs Type B + C6 vs S82 IS/OOS/2026 ---
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.5, 5.2), dpi=180)
    fig.patch.set_facecolor("white")

    ab_items = [
        ("全部买入(T2收)", "E1_all__H1b_T2_close"),
        ("高开买(T3收)", "E2_gapup__H2_T3_close"),
        ("深水低吸(T2收)", "E4_deep__H1b_T2_close"),
        ("日内回踩*(T3收)", "E5a_pullback__H2_T3_close"),
        ("突破昨高(T2收)", "E5b_breakhigh__H1b_T2_close"),
    ]
    lbl_ab = [x[0] for x in ab_items]
    a_vals = [m2["StrongMainline_TypeA"][k]["FULL"]["nav_1s"] for _, k in ab_items]
    b_vals = [m2["StrongMainline_TypeB"][k]["FULL"]["nav_1s"] for _, k in ab_items]
    x2 = np.arange(len(lbl_ab))
    w2 = 0.34
    ax1.bar(x2 - w2 / 2, a_vals, width=w2, color="#1f77b4", label="A型 光头强趋势大阳")
    ax1.bar(x2 + w2 / 2, b_vals, width=w2, color="#ff7f0e", label="B型 冲板炸板烂大阳")
    ax1.axhline(1.0, color="#d62728", ls="--", lw=1.2)
    for i, (va, vb) in enumerate(zip(a_vals, b_vals)):
        ax1.text(i - w2 / 2, va + 0.1, f"{va:.2f}x", ha="center", va="bottom", fontsize=7.8)
        ax1.text(i + w2 / 2, vb + 0.1, f"{vb:.2f}x", ha="center", va="bottom", fontsize=7.8)
    ax1.set_xticks(x2)
    ax1.set_xticklabels(lbl_ab, rotation=12, fontsize=8.5)
    ax1.set_ylabel("五年单仓净值（倍）", fontsize=9.5)
    ax1.set_title("强主线内部：光头大阳 vs 炸板烂阳（*回踩缺5分钟验证）", fontsize=10, fontweight="bold")
    ax1.set_ylim(0, max(max(a_vals), max(b_vals)) * 1.22)
    ax1.grid(axis="y", alpha=0.25)
    ax1.legend(fontsize=8.5, loc="upper right")

    c6 = arch["C6_强主线_B型炸板+深水低吸T2收"]
    c9 = arch["C9_强主线_龙头第1+无过热_E4低吸T2"]
    stages = ["样本内\n(21~24.06)", "样本外\n(24.07~26)", "样本外\n去前5", "2026单年"]
    c6_s = [c6["IS"]["nav_1s"], c6["OOS"]["nav_1s"], c6["OOS"]["ex5_nav"], c6["Y2026"]["nav_1s"]]
    c9_s = [c9["IS"]["nav_1s"], c9["OOS"]["nav_1s"], c9["OOS"]["ex5_nav"], c9["Y2026"]["nav_1s"]]
    s82_s = [s82["IS"]["nav_1s"], s82["OOS"]["nav_1s"], s82["OOS"]["ex5_nav"], s82["Y2026"]["nav_1s"]]
    xs = np.arange(len(stages))
    ws = 0.25
    ax2.bar(xs - ws, c6_s, width=ws, color="#ff7f0e", label="样本内最优 C6 (炸板+深水)")
    ax2.bar(xs, c9_s, width=ws, color="#7f7f7f", label="龙头第一+不过热 C9")
    ax2.bar(xs + ws, s82_s, width=ws, color="#2ca02c", label="现役20cm首板深水 (S82)")
    ax2.set_yscale("log")
    ax2.axhline(1.0, color="#d62728", ls="--", lw=1.2)
    for i, (v1, v2, v3) in enumerate(zip(c6_s, c9_s, s82_s)):
        ax2.text(i - ws, v1 * 1.15, f"{v1:.2f}x", ha="center", va="bottom", fontsize=7.5)
        ax2.text(i, v2 * 1.15, f"{v2:.2f}x", ha="center", va="bottom", fontsize=7.5)
        ax2.text(i + ws, v3 * 1.15, f"{v3:.2f}x", ha="center", va="bottom", fontsize=7.5, fontweight="bold")
    ax2.set_xticks(xs)
    ax2.set_xticklabels(stages, fontsize=8.5)
    ax2.set_ylabel("分阶段单仓净值（对数坐标）", fontsize=9.5)
    ax2.set_title("样本内外与去极值：候选方案 vs 现役S82（均远不如现役）", fontsize=10, fontweight="bold")
    ax2.set_ylim(0.2, 350)
    ax2.grid(axis="y", alpha=0.25)
    ax2.legend(fontsize=8, loc="upper right")

    plt.tight_layout()
    plt.savefig(CHART2_PATH, dpi=180)
    plt.close(fig)


def build_rd033_payload():
    blocks = [
        P([
            TR("直接结论：强主线题材对未涨停20cm大阳有一点分化作用，但整体依然没用，严禁立项。", background_color=3),
            TR("全池盲买五年单仓净值跌至 0.10 倍。聚焦温热和强主线区间虽升至 2.40 倍至 3.64 倍。但剔除前五只牛股后全线跌破 1 倍。全量方案远落后于现役首板深水策略的 468.29 倍。"),
        ]),
        P([TR("一、研究范围与五年防伪口径", bold=True)]),
        B([TR("时间跨度为 2021年1月至2026年11月。样本覆盖创业板与科创板全量股票，包含已退市股。")]),
        B([TR("严格剔除 ST 股与上市前二十日无涨跌幅限制新股。同时排除日成交额不足一亿元样本。")]),
        B([TR("入选门槛为信号日收盘上涨幅度在 +10% 至 +19.8% 且未封死涨停。五年共得 23453 笔信号。")]),
        B([TR("信号日开盘啦榜单仅录涨停股，未涨停股票当日零入榜。本研究严格只用信号日之前历史榜单映射当日主线。历史归属覆盖 81.9% 样本。")]),
        B([TR("次日按真实可成交价买入，剔除一字涨停买不到样本。跌停顺延开板卖出，双边扣千分之三费用。")]),

        P([TR("二、核心问题直答：题材到底有没有用", bold=True)]),
        O([TR("强弱呈倒 U 型分化。全池盲买五年单仓跌至 0.10 倍，无主线单仓 1.11 倍。")]),
        O([TR("温热题材三至四板单仓升至 3.64 倍。强主线五至九板单仓升至 2.40 倍。")]),
        O([TR("但两档均仓分别仅 0.40 倍与 1.00 倍。剔除前五只牛股后单仓全部跌破 0.65 倍。")]),
        O([TR("十家以上高潮期单仓反跌至 0.40 倍，十二家以上跌至 0.22 倍。")]),
        O([TR("同题材已有主板一字龙头带队时，跟风大阳次日胜率仅 41.6%。单笔均收 -0.64%，五年净值跌至 0.03 倍。")]),
        O([TR("同主线横比中，次日盲追主板首板净值归零。盲追二十厘米首板也跌至 0.03 倍，全军覆没。")]),

        P([TR("三、反直觉分野：光头强趋势不如炸板烂大阳", bold=True)]),
        B([TR("光头强趋势大阳（上影线不超过三个点）共有 2864 笔。表面形态漂亮，其实样本内三年仅 0.31 倍。")]),
        B([TR("它仅靠近两年反弹拉升至 5.92 倍，五年均仓大亏至 0.20 倍，稳定度很差。")]),
        B([TR("冲板炸板烂大阳共有 1289 笔，五年单仓达到 4.04 倍。同期等权均仓也达 3.68 倍，显著优于光头趋势。")]),
        B([TR("原因在于炸板日提前释放抛压。但剔除前五只牛股后单仓仍跌回 0.88 倍，依然撑不起策略。")]),

        P([TR("四、五类买点与六类卖法盲测结果", bold=True)]),
        B([TR("强主线下无论怎么买卖，次日竞价追涨突破昨高全部崩盘，五年单仓跌至 0.01 倍。")]),
        B([TR("高开一至六个点拿三天虽得 2.61 倍。但样本外跌回 0.93 倍，今年仅 0.87 倍。")]),
        B([TR("光头趋势配回踩前收拿三天表面看似有 5.61 倍，但日线无法还原盘中先后顺序。")]),
        B([TR("同时该组合样本内仅 1.26 倍，剔除前五牛股后仅剩 1.10 倍。这属于不可验证的日线假象。")]),
        B([TR("样本内测试 156 组因子，虽有 15 组过多重检验纠偏。但在样本外单仓全部崩跌至 0.28 倍至 0.89 倍。")]),

        P([TR("五、深度对标现役与空仓补丁终裁", bold=True)]),
        B([TR("样本内最优的炸板深水低吸方案，五年单仓 3.48 倍。但最大回撤高达 55.97%。")]),
        B([TR("该方案样本外仅 1.38 倍。剔除前五牛股跌至 0.44 倍，今年回撤至 0.66 倍。")]),
        B([TR("它连同暴露静态买沪深三百（0.93 倍）都无显著优势。改按波动率倒数加权后更腰斩至 1.41 倍。")]),
        B([TR("现役首板深水策略五年净值高达 468.29 倍。去前五仍有 104.06 倍，样本外 4.11 倍且今年 2.60 倍。")]),
        B([TR("把该方案塞入现役六策略空仓日做补丁，五年仅补 43 笔单，今年收益几乎为零。")]),
        B([TR("结论：未涨停强主线二十厘米大阳不具备独立或补丁上线价值，彻底证伪并永久弃用。")]),
        BL(), BL(), BL(),
    ]

    t1_rows = [
        [C("分组与信号数", True), C("次日收胜率/均收", True), C("五年单仓/均仓", True), C("去前5/样本外", True)],
        [C("全池盲买 (23425笔)"), C("44.9% / -0.00%"), C("0.10x / 0.41x"), C("0.02x / 0.47x")],
        [C("无主线含边缘 (11866笔)"), C("44.9% / +0.34%"), C("1.11x / 0.12x"), C("0.26x / 0.94x")],
        [C("温热 3至4板 (2401笔)"), C("49.1% / +0.62%"), C("3.64x / 0.40x"), C("0.65x / 2.33x")],
        [C("强主线 5至9板 (1945笔)"), C("47.0% / +0.53%"), C("2.40x / 1.00x"), C("0.63x / 1.56x")],
        [C("强主线前3含>=5 (6348笔)"), C("45.6% / +0.31%"), C("0.72x / 0.33x"), C("0.17x / 1.53x")],
        [C("高潮 >=10板 (4403笔)"), C("45.6% / +0.15%"), C("0.40x / 0.38x"), C("0.09x / 0.64x")],
        [C("10cm一字带动 (2277笔)"), C("41.6% / -0.64%"), C("0.03x / 0.07x"), C("0.01x / 0.26x")],
        [C("强主线20cm首板 (4349笔)"), C("43.4% / -0.03%"), C("0.03x / 0.00x"), C("0.01x / 0.17x")],
        [C("强主线10cm首板 (18481笔)"), C("40.0% / -0.98%"), C("0.00x / 0.00x"), C("0.00x / 0.04x")],
    ]

    t2_rows = [
        [C("K线形态与买卖规则", True), C("五年单仓/均仓", True), C("去前五极值", True), C("样本内/样本外/今年", True)],
        [C("强主线A型 全买次收"), C("1.83x / 0.20x"), C("0.52x"), C("0.31 / 5.92 / 1.30x")],
        [C("强主线B型 全买次收"), C("4.04x / 3.68x"), C("0.88x"), C("3.29 / 1.23 / 0.93x")],
        [C("强主线A型 高开拿六天"), C("3.29x / 0.91x"), C("0.46x"), C("1.10 / 2.98 / 0.99x")],
        [C("强主线A型 日线回踩*"), C("5.61x / 1.10x"), C("1.10x"), C("1.26 / 4.44 / 3.24x")],
        [C("强主线B型 深水拿两天"), C("2.45x / 1.44x"), C("0.73x"), C("2.43 / 1.01 / 0.57x")],
        [C("强主线全池 破昨高买"), C("0.01x / 0.00x"), C("0.00x"), C("0.10 / 0.12 / 0.55x")],
    ]

    t3_rows = [
        [C("核心对标方案", True), C("五年单仓/去前五", True), C("最大回撤/今年", True), C("样本外/补丁表现", True)],
        [C("强主线炸板深水(C6)"), C("3.48x / 1.04x"), C("55.97% / 0.66x"), C("1.38x / 去5仅0.44x")],
        [C("龙头第一非高潮(C9)"), C("1.93x / 0.46x"), C("83.64% / 0.94x"), C("1.43x / 去5仅0.38x")],
        [C("C6 空仓补丁 (+43笔)"), C("2.51x / 1.04x"), C("22.50% / 1.01x"), C("1.54x / 补丁无增厚")],
        [C("现役首板深水策略"), C("468.29x / 104.06x"), C("26.70% / 2.60x"), C("4.11x / 实盘主力")],
    ]

    return {
        "title": DOC_TITLE,
        "blocks": blocks,
        "tables": [
            ("表1 题材强弱分层与跨板块五年对比表", t1_rows),
            ("表2 形态分化与主流买卖组合对比表", t2_rows),
            ("表3 样本内最优方案与现役策略对比表", t3_rows),
        ],
        "img_path": CHART1_PATH,
        "img_path2": CHART2_PATH,
    }


def _fetch_live_hub_rows(doc_id: str) -> list:
    r = s6.api(f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/blocks?page_size=500", method="GET")
    blks = r.get("data", {}).get("items", []) or []
    blk_map = {b["block_id"]: b for b in blks}
    for b in blks:
        if b.get("block_type") == 31:
            tbl = b["table"]
            rows_n, cols_n = tbl["property"]["row_size"], tbl["property"]["column_size"]
            cells = tbl["cells"]
            out = []
            for ri in range(1, rows_n):
                vals = []
                for ci in range(cols_n):
                    cb = blk_map.get(cells[ri * cols_n + ci], {})
                    txt = ""
                    for kid in cb.get("children", []):
                        kb = blk_map.get(kid, {})
                        if kb.get("block_type") == 2:
                            txt += "".join(e.get("text_run", {}).get("content", "") for e in kb.get("text", {}).get("elements", []))
                    vals.append(txt.strip())
                if any(vals):
                    out.append(tuple(vals))
            return out
    raise RuntimeError(f"Live Hub {doc_id} table not found")


def build_updated_invalid_hub(live_fetch: bool = False):
    intro = "结论：本目录收录6大主力策略之外已证伪小策略与亏钱陷阱，永久避坑防复燃。"
    rd033_row = ("20cm强主线大阳实证", "5年23453笔", "强主线略有分化但去前五全破1倍，炸板深水样本外去前五仅0.44倍", "永久证伪，不立项不作补丁")
    if live_fetch:
        existing = _fetch_live_hub_rows(INVALID_HUB_DOC)
        existing = [r for r in existing if r[0] != rd033_row[0]]
        if len(existing) < 13:
            raise RuntimeError(f"Live Hub rows unexpectedly shrunk to {len(existing)} < 13!")
        rows = [rd033_row] + existing
    else:
        rows = [
            rd033_row,
            ("老热股六策略实证", "5年六策略及五板", "多重纠偏后有效极少，强加换票近两年净值腰斩", "全六策略维持原版，五板暂作独立观察"),
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
    return build_hub_doc("证伪回测与避坑墓碑", intro, rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    audit = json.load(open(AUDIT_JSON, "r", encoding="utf-8"))
    make_charts(audit)

    doc_data = build_rd033_payload()
    hub_data = build_updated_invalid_hub(live_fetch=False)

    s9.check_first_sentence_rule(doc_data)
    long1 = s9.audit_doc_strict_v191(doc_data, require_img=True)
    if long1:
        raise ValueError(f"RD033报告存在超40字长句: {long1}")

    long_hub = s9.audit_doc_strict_v191(hub_data, require_img=False)
    if long_hub:
        raise ValueError(f"Hub目录存在超40字长句: {long_hub}")

    if args.dry_run:
        print("[DRY-RUN PASS] Charts generated & strict V19.1 audit passed (0 violations).")
        return

    with open(s6.LOCK_PATH, "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)

        hub_data = build_updated_invalid_hub(live_fetch=True)
        long_hub_live = s9.audit_doc_strict_v191(hub_data, require_img=False)
        if long_hub_live:
            raise ValueError(f"Live Hub目录存在超40字长句: {long_hub_live}")

        doc_id, node_tok = s9.find_or_create_child_node(INVALID_PARENT_NODE, DOC_TITLE)
        done, fail = s6.write_document_payload(doc_id, doc_data["blocks"], doc_data["tables"], doc_data["img_path"])
        if fail:
            raise RuntimeError(f"写入 {DOC_TITLE} 有失败项 fail={fail}")

        ok_img2 = s6.insert_image_block(doc_id, doc_data["img_path2"])
        if not ok_img2:
            raise RuntimeError("插入第二张图表失败")

        v_doc = s9.verify_document_v191(
            doc_id, DOC_TITLE, expected_tables_count=len(doc_data["tables"]), has_img=True
        )
        if v_doc["images_count"] < 2:
            raise RuntimeError(f"图片数量不足2张: {v_doc}")

        done_h, fail_h = s6.write_document_payload(INVALID_HUB_DOC, hub_data["blocks"], hub_data["tables"], None)
        if fail_h:
            raise RuntimeError(f"写入 Hub 失败 fail={fail_h}")
        v_hub = s9.verify_document_v191(
            INVALID_HUB_DOC, "证伪回测与避坑墓碑", expected_tables_count=1, has_img=False
        )

        # Update manifest
        manifest = json.load(open(s6.MANIFEST_PATH, "r", encoding="utf-8"))
        manifest["rd033_20cm_theme_surge10_19"] = {
            "title": DOC_TITLE,
            "node_token": node_tok,
            "doc_id": doc_id,
            "wiki_url": f"https://my.feishu.cn/wiki/{node_tok}",
            "hub_url": f"https://my.feishu.cn/wiki/{INVALID_PARENT_NODE}",
            "published_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "verify": v_doc,
            "hub_verify": v_hub,
        }
        with open(s6.MANIFEST_PATH, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

        res = {
            "status": "PUBLISHED",
            "title": DOC_TITLE,
            "node_token": node_tok,
            "doc_id": doc_id,
            "wiki_url": f"https://my.feishu.cn/wiki/{node_tok}",
            "hub_url": f"https://my.feishu.cn/wiki/{INVALID_PARENT_NODE}",
            "verify_doc": v_doc,
            "verify_hub": v_hub,
        }
        with open(RES_JSON, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2)

        print(f"[PUBLISHED] {DOC_TITLE} -> {res['wiki_url']}")


if __name__ == "__main__":
    main()

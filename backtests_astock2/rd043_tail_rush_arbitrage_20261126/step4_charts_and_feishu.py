#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD043 Step 4: Generate 2 Crisp Pure-Chinese Charts & Publish Strict Feishu Report (`尾盘抢筹套利实证`)
to `证伪回测与避坑墓碑` (`QiDewdTkJiquokkbbo6cWr3Fn6f`) + Incrementally Update Hub (`ZTaudjSqtoaj71xTPSLciMcdnLb`).

Zero yfinance (D12). Zero edits to active V20.0 production docs.
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
from matplotlib.patches import Rectangle
from matplotlib.ticker import FuncFormatter
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd043_tail_rush_arbitrage_20261126"
RD041_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd041_day0_firstboard_sweep_20261126"
FS_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/feishu_master_docs_20261116"
for p in (OUT_DIR, RD041_DIR, FS_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import _rd041_feishu_helpers as fh  # noqa: E402
import step6_upgrade_3strategies_20261117 as s6  # noqa: E402
import step9_sync_v191_exits_20261118 as s9  # noqa: E402

TITLE = "尾盘抢筹套利实证"
HUB_ROW = [
    "尾盘抢筹套利实证",
    "5年16万笔与400笔5m",
    "110组盲测与168组打分全破1倍，接主力空仓拖累一至九成",
    "严禁尾盘抢筹与空仓补位",
]

CHART1_PATH = f"{OUT_DIR}/rd043_chart1_prototypes_and_wf_collapse.png"
CHART2_PATH = f"{OUT_DIR}/rd043_chart2_5m_slippage_and_v20_collision.png"

C = fh.C
T = fh.T
B = fh.B
BL = fh.BL
MIXED = fh.MIXED

plt.rcParams["font.sans-serif"] = ["PingFang SC", "Hiragino Sans GB", "STHeiti", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def build_charts(audit: dict, bm: pd.DataFrame, gr: pd.DataFrame) -> tuple[str, str]:
    # --- Chart 1: Prototypes Blind Collapse + 168 WF Scorecard Collapse ---
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15.0, 5.8), dpi=180)
    fig.patch.set_facecolor("#FFFFFF")

    items = [
        ("A_10cm_1yi", "E1_T1O", "强主线主板 (次早卖)"),
        ("A_10cm_1yi", "E2_T1C_HoldZT", "强主线主板 (次收持连)"),
        ("A_20cm_1yi", "E1_T1O", "强主线20厘米 (次早卖)"),
        ("A_20cm_1yi", "E2_T1C_HoldZT", "强主线20厘米 (次收持连)"),
        ("B_all_1yi", "E1_T1O", "冰点老龙全池 (次早卖)"),
        ("B_ztlt40_ice", "E2_T1C_HoldZT", "冰点老龙跌停少 (次收)"),
        ("C_all_1yi", "E1_T1O", "断板分歧翻红 (次早卖)"),
        ("C_lianban2plus", "E2_T1C_HoldZT", "连板断板翻红 (次收)"),
    ]
    y = np.arange(len(items))
    v_wf, v_5y = [], []
    for sl, ex, _ in items:
        r = bm[(bm["slice"] == sl) & (bm["exit"] == ex)].iloc[0]
        v_wf.append(float(r["nav_wf_30"]))
        v_5y.append(float(r["nav5y_30"]))

    h = 0.36
    ax1.barh(y - h / 2, v_wf, height=h, color="#0284c7", alpha=0.90, label="近四年样本外单仓净值 (倍)")
    ax1.barh(y + h / 2, v_5y, height=h, color="#94a3b8", alpha=0.85, label="五年全样本单仓净值 (倍)")
    ax1.axvline(1.0, color="#dc2626", linestyle="--", linewidth=1.3, label="保本生死线 (1.00倍)")
    for i in range(len(items)):
        ax1.text(max(v_wf[i], 0.0) + 0.02, y[i] - h / 2, f"{v_wf[i]:.3f}x", va="center", ha="left", fontsize=8.2, color="#0c4a6e", fontweight="bold")
        ax1.text(max(v_5y[i], 0.0) + 0.02, y[i] + h / 2, f"{v_5y[i]:.3f}x", va="center", ha="left", fontsize=8.2, color="#475569")
    ax1.set_yticks(y)
    ax1.set_yticklabels([x[2] for x in items], fontsize=9.0, fontweight="bold")
    ax1.set_xlabel("单仓复利净值（倍，双边扣千分之三）", fontsize=9.5, fontweight="bold")
    ax1.set_title("一、三大尾盘抢筹原型盲测全线亏损（最高仅0.44倍）", fontsize=11.0, fontweight="bold", pad=12)
    ax1.set_xlim(0, 1.25)
    ax1.legend(loc="lower right", fontsize=8.2, frameon=True)
    ax1.grid(axis="x", linestyle="--", alpha=0.35)

    # Right: All 168 WF Scorecard rows (n>=25, nav_30 vs ex5_30)
    sub_g = gr[(gr["threshold"] != "all_cands") & (gr["n_trades"] >= 25)].copy()
    x_n = sub_g["nav_30"].to_numpy(float)
    y_e = sub_g["ex5_30"].to_numpy(float)
    sz = np.clip(sub_g["n_trades"].to_numpy(float) * 0.45, 25, 260)

    ax2.add_patch(Rectangle((1.5, 1.15), 0.35, 0.25, facecolor="#dcfce7", alpha=0.55, zorder=0))
    ax2.scatter(x_n, y_e, s=sz, c="#64748b", alpha=0.68, edgecolors="#0f172a", linewidth=0.7, label="前视多因子精选各档 (共168组)", zorder=3)
    ax2.axvline(1.5, color="#dc2626", linestyle="--", linewidth=1.1, label="过关门槛: 样本外>=1.5x 且 去前五>=1.15x", zorder=2)
    ax2.axhline(1.15, color="#dc2626", linestyle="--", linewidth=1.1, zorder=2)
    ax2.axvline(1.0, color="#0f172a", linestyle=":", linewidth=1.0, label="保本线 (1.00倍)", zorder=2)

    top_pts = sub_g.sort_values("nav_30", ascending=False).head(3)
    lbl_map = {
        "T10_B_All_E2": "冰点老龙次收",
        "T11_B_All_E3a": "冰点老龙弱走",
        "T14_C_Lianban_E1": "连板断板次早",
    }
    pos_list = [(0.36, 0.72), (1.06, 0.44), (1.06, 0.14)]
    for (r_i, rw), (xt, yt) in zip(top_pts.iterrows(), pos_list):
        cn_t = lbl_map.get(rw["track_id"], rw["track_id"])
        ax2.annotate(
            f"{cn_t} ({rw['threshold']}, {int(rw['n_trades'])}笔)\n{rw['nav_30']:.2f}x / 去五{rw['ex5_30']:.2f}x",
            xy=(rw["nav_30"], rw["ex5_30"]),
            xytext=(xt, yt),
            fontsize=8.0, color="#0f172a",
            arrowprops=dict(arrowstyle="->", color="#475569", lw=0.8),
        )
    ax2.set_xlabel("近四年样本外单仓净值（倍，双边扣千分之三）", fontsize=9.5, fontweight="bold")
    ax2.set_ylabel("去掉前五大盈利后净值（倍）", fontsize=9.5, fontweight="bold")
    ax2.set_title("二、168组多因子前视打分零一过关：无一组站上保本线", fontsize=11.0, fontweight="bold", pad=12)
    ax2.set_xlim(0, 1.85)
    ax2.set_ylim(0, 1.38)
    ax2.grid(True, linestyle="--", alpha=0.35)
    ax2.legend(loc="upper left", fontsize=8.0, frameon=True)

    plt.tight_layout(pad=2.0)
    fig.savefig(CHART1_PATH, dpi=180, bbox_inches="tight", facecolor="#FFFFFF")
    plt.close(fig)

    # --- Chart 2: Real 5m Execution Verification + 4-Tier Slippage + V20 Empty-Slot 3 Ledgers ---
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15.0, 5.8), dpi=180)
    fig.patch.set_facecolor("#FFFFFF")

    m5 = audit["real_5m_execution_audit"]["baostock_real_5m_audit"]["by_track"]
    tr_items = [
        ("T01_A_10cm_E1", "强主线主板\n(100笔)"),
        ("T05_A_20cm_E1", "强主线20厘米\n(100笔)"),
        ("T10_B_All_E2", "冰点老龙\n(120笔)"),
        ("T13_C_All_E1", "断板翻红\n(80笔)"),
    ]
    x1 = np.arange(len(tr_items))
    w1 = 0.25
    v_cl = [m5[k]["daily_close_e1_net30_nav"] for k, _ in tr_items]
    v_45 = [m5[k]["real_1445_to_0935_net30_nav"] for k, _ in tr_items]
    v_50 = [m5[k]["real_1450_to_0935_net30_nav"] for k, _ in tr_items]

    b1 = ax1.bar(x1 - w1, v_cl, width=w1, color="#64748b", label="日线收盘近似 (次早竞价卖)")
    b2 = ax1.bar(x1, v_45, width=w1, color="#0284c7", label="真实14点45分买 -> 次日09点35分卖")
    b3 = ax1.bar(x1 + w1, v_50, width=w1, color="#f59e0b", label="真实14点50分买 -> 次日09点35分卖")
    ax1.axhline(1.0, color="#dc2626", linestyle="--", linewidth=1.2, label="保本线 (1.00倍)")
    for bars in (b1, b2, b3):
        for bar in bars:
            yv = bar.get_height()
            ax1.text(bar.get_x() + bar.get_width() / 2, yv + 0.02, f"{yv:.2f}x", ha="center", va="bottom", fontsize=7.8, fontweight="bold")
    ax1.set_xticks(x1)
    ax1.set_xticklabels([x[1] for x in tr_items], fontsize=9.0, fontweight="bold")
    ax1.set_ylabel("实盘五分钟复利净值（倍，扣千分之三）", fontsize=9.5, fontweight="bold")
    ax1.set_title("三、400笔真实五分钟K线核验：提前14点45分买仍全线亏损", fontsize=10.8, fontweight="bold", pad=12)
    ax1.set_ylim(0, 1.18)
    ax1.grid(axis="y", linestyle="--", alpha=0.35)
    ax1.legend(loc="upper right", fontsize=8.0, frameon=True)

    # Right: V20 Empty-Slot Integration across 3 Physical Capital Ledgers
    vp = audit["v20_empty_slot_patch"]
    v_items = [
        ("T01_A_10cm_E1", "E1_NoCollision_0924", "强主线主板\n假定09:24零撞"),
        ("T01_A_10cm_E1", "E1_StrictCashLock_0925", "强主线主板\n09:25占资(撞44笔)"),
        ("T05_A_20cm_E1", "E1_NoCollision_0924", "强主线20厘米\n假定09:24零撞"),
        ("T05_A_20cm_E1", "E1_StrictCashLock_0925", "强主线20厘米\n09:25占资(撞21笔)"),
        ("T10_B_All_E2", "E2_T1C_HoldZT_BlocksAllNextDay_1500", "冰点老龙次收\n占次日(撞35笔)"),
        ("T11_B_All_E3a", "E3a_Open0_Hold_BlocksAllNextDay_1500", "冰点老龙弱走\n占次日(撞20笔)"),
    ]
    x2 = np.arange(len(v_items))
    vals2 = [vp[t][m]["delta_nav_ratio"] for t, m, _ in v_items]
    cols2 = ["#f59e0b" if "0924" in m else "#dc2626" for _, m, _ in v_items]
    bars2 = ax2.bar(x2, vals2, width=0.55, color=cols2, alpha=0.92, edgecolor="white")
    ax2.axhline(1.0, color="#0f172a", linestyle="--", linewidth=1.2, label="不接入现役主力基线 (1.00倍)")
    for b, v in zip(bars2, vals2):
        ax2.text(b.get_x() + b.get_width() / 2, v + 0.025, f"{v:.2f}x", ha="center", va="bottom", fontsize=8.5, fontweight="bold", color="#0f172a")
    ax2.set_xticks(x2)
    ax2.set_xticklabels([x[2] for x in v_items], fontsize=7.6, fontweight="bold")
    ax2.set_ylabel("接入后总仓相对现役净值乘数（倍）", fontsize=9.5, fontweight="bold")
    ax2.set_title("四、接进主力四成空仓日三大账本：零撞车亏两成，占资暴跌九成", fontsize=10.8, fontweight="bold", pad=12)
    ax2.set_ylim(0, 1.18)
    ax2.grid(axis="y", linestyle="--", alpha=0.35)
    ax2.legend(loc="upper right", fontsize=8.2, frameon=True)

    plt.tight_layout(pad=2.0)
    fig.savefig(CHART2_PATH, dpi=180, bbox_inches="tight", facecolor="#FFFFFF")
    plt.close(fig)
    return CHART1_PATH, CHART2_PATH


def build_payload(c1_path: str, c2_path: str) -> dict:
    blocks = [
        MIXED([
            ("结论：尾盘抢筹套利彻底没用，16万笔样本与168组打分无一过关。", True, True),
            ("隔夜竞价出货负期望叠加高昂换手滑点，接进主力空仓日会大幅拖累总收益。", False, False),
        ]),
        BL(),
        T("一、三大尾盘原型五年全样本盲测全线亏损", bold=True),
        B("本轮实采五年全市场含退市共161859笔尾盘可买事件，涵盖8119笔炸板。", False),
        B("强主线逼近前高隔夜毛收益仅+0.04%，扣千三费用后五年单仓净值归零。", False, True),
        B("所谓高涨幅高毛利全靠九二四单日千股暴涨拉高，按日均等权每日仍亏-0.73%。", False),
        B("连跌冰点逆势拉起的老龙实为诱多出货，隔夜毛亏-0.46%且换手越高亏越惨。", False, True),
        B("前日连板断板分歧尾盘翻红次日直接低开闷杀，隔夜毛亏达-1.46%至-2.60%。", False),
        BL(),
        T("二、168组前视多因子打分零过关与滑点碾压", bold=True),
        B("严守前视规则在样本外跑满168组打分精选，无一组能够站上1.00倍保本线。", False, True),
        B("账面最高冰点老龙次收前5%档也仅0.88倍，去掉前五极值更跌破0.45倍。", False),
        B("把费用推高至尾盘追价千八与百分之一点二，该最佳模型净值暴跌至0.31与0.13倍。", False),
        B("即使将打分阈值推高至九十分以上极端档位，全部原型样本外仍无一突破保本。", False, True),
        B("全部代表性赛道均通过二零二四年年底物理截断复算，分数与收益差异均为零。", False),
        BL(),
        T("三、四百笔真实五分钟K线核验与主力空仓补位破坏", bold=True),
        B("实测本地分钟库仅覆盖主力六策略一成半样本，故额外直采400笔真实五分钟K线。", False),
        B("提前至14点45分买仅省约0.19%，隔夜兑现净值仍全线跌破0.76倍。", False, True),
        B("现役主力五年空仓占比四成，但强塞尾盘隔夜零撞车账本仍亏掉主力两至三成净值。", False),
        B("若按单账户竞价资金占用或持至次日收盘，会撞掉大量主力大牛股致净值毁九成。", False, True),
        B("结论明确：永久拉黑尾盘抢筹及隔夜补位想法，严守现役主力早盘体系。", False),
        BL(),
        BL(),
        BL(),
    ]

    t1 = [
        [C("原型与精选路径", True), C("样本笔数/胜率", True), C("千三/千八净值", True), C("去前五与红队终裁", True)],
        [C("强主线主板盲买(次早)"), C("923 / 18.5%"), C("0.00x / 0.00x"), C("近四年持续失血归零")],
        [C("冰点老龙少跌停(次收)"), C("172 / 40.1%"), C("0.44x / 0.18x"), C("去前五仅0.10x 全面亏损")],
        [C("断板翻红盲买(次早)"), C("833 / 21.0%"), C("0.00x / 0.00x"), C("隔夜毛亏-1.46% 惨遭闷杀")],
        [C("冰点老龙打分前5%(次收)"), C("207 / 42.5%"), C("0.88x / 0.31x"), C("去五0.45x 日频重训0.59x")],
        [C("冰点老龙打分75分(弱走)"), C("386 / 28.0%"), C("0.51x / 0.07x"), C("去五0.27x 拖累主力-35%")],
        [C("强主线20厘米打分(次早)"), C("258 / 26.0%"), C("0.46x / 0.12x"), C("去五0.34x 实盘5m仅0.68x")],
        [C("断板翻红打分(次早)"), C("133 / 21.8%"), C("0.45x / 0.23x"), C("去五0.35x 实盘5m仅0.55x")],
    ]

    t2 = [
        [C("实盘核验与空仓账本", True), C("触发/撞车笔数", True), C("空仓独立净值", True), C("接入主力后净值变动", True)],
        [C("强主线主板14点45分5m"), C("100笔 / 实测"), C("0.76x (扣千三)"), C("较收盘仅+0.17% 仍大亏")],
        [C("强主线主板(假定零撞车)"), C("173笔 / 撞2笔"), C("0.71x (减主力)"), C("总仓净值降至0.76倍(-24%)")],
        [C("强主线主板(09:25占资)"), C("173笔 / 撞44笔"), C("0.71x (掉7.5x)"), C("总仓净值暴跌至0.10倍(-90%)")],
        [C("强主线20厘米(假定零撞)"), C("92笔 / 撞0笔"), C("0.77x (净亏)"), C("总仓净值降至0.77倍(-23%)")],
        [C("强主线20厘米(09:25占资)"), C("92笔 / 撞21笔"), C("0.77x (掉2.8x)"), C("总仓净值暴跌至0.27倍(-73%)")],
        [C("冰点老龙次收(占次日)"), C("96笔 / 撞35笔"), C("0.68x (掉6.2x)"), C("总仓净值暴跌至0.11倍(-89%)")],
    ]

    sections_tables = [
        ("表一：尾盘抢筹三大原型盲测与前视多因子打分最佳表现对比（样本外2023至2026）", t1, c1_path),
        ("表二：真实五分钟执行价误差与接入现役主力空仓日三大资金账本检验", t2, c2_path),
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
    print("[DryRun PASS] RD043 payload 100% validated!")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    audit = json.load(open(f"{OUT_DIR}/rd043_audit.json", encoding="utf-8"))
    bm = pd.read_csv(f"{OUT_DIR}/rd043_blind_matrix.csv")
    gr = pd.read_csv(f"{OUT_DIR}/rd043_grid.csv")

    c1, c2 = build_charts(audit, bm, gr)
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
        done, fail = fh.write_doc_with_interleaved_charts(doc_id, payload["blocks"], payload["sections_tables"])
        assert fail == 0, f"Write failed: {fail}"
        time.sleep(0.8)
        v = s9.verify_document_v191(doc_id, payload["title"], expected_tables_count=len(payload["tables"]), has_img=True)
        assert v["images_count"] >= 2, f"Missing charts: {v}"

        raw_txt = s6.api(f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/raw_content", method="GET")["data"]["content"]
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
        with open(f"{OUT_DIR}/feishu_publish_result.json", "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
        print(json.dumps(res, ensure_ascii=False, indent=2))
    finally:
        fcntl.flock(lock_f, fcntl.LOCK_UN)
        lock_f.close()


if __name__ == "__main__":
    main()

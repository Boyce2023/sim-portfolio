#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD046 Step 5: Generate 2 High-DPI Pure-Chinese Charts & Publish Strict Feishu Report (`可转债正股映射实证`)
to `证伪回测与避坑墓碑` (`QiDewdTkJiquokkbbo6cWr3Fn6f`) + Incrementally Update Hub (`ZTaudjSqtoaj71xTPSLciMcdnLb`).
Zero yfinance (D12). Zero edits to active V20.0 production docs.
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_k] = "1"

import argparse
import fcntl
import json
import re
import sys
import time
import warnings

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd046_convertible_bond_t0_20261126"
RD041_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd041_day0_firstboard_sweep_20261126"
FS_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/feishu_master_docs_20261116"
for p in (OUT_DIR, RD041_DIR, FS_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import _rd041_feishu_helpers as fh  # noqa: E402
import step6_upgrade_3strategies_20261117 as s6  # noqa: E402
import step9_sync_v191_exits_20261118 as s9  # noqa: E402

TITLE = "可转债正股映射实证"
HUB_ROW = [
    "可转债正股映射实证",
    "892只全债含584退市+5分钟",
    "早盘一字均亏-2.01%且96组打分零过关，T+0零撞车但去五亏",
    "暂禁实盘，保留低溢价当日了结思路",
]

CHART1_PATH = f"{OUT_DIR}/rd046_chart1_traps_and_wf_redteam.png"
CHART2_PATH = f"{OUT_DIR}/rd046_chart2_cost_decay_and_v20_t0.png"

C, T, B, BL, MIXED = fh.C, fh.T, fh.B, fh.BL, fh.MIXED

plt.rcParams["font.sans-serif"] = ["PingFang SC", "Hiragino Sans GB", "STHeiti", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def build_charts(audit: dict, bm: pd.DataFrame, gr: pd.DataFrame) -> tuple[str, str]:
    # --- Chart 1: Lookahead/Survivorship Traps + 96 WF Scorecard Red-Team Gate ---
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15.4, 6.0), dpi=180)
    fig.patch.set_facecolor("#FFFFFF")

    cb2_u = audit["cb2_5m_26h2_unbiased"]["on_5m_seal"]
    def _bm_mean(proto, sl):
        return float(bm[(bm["prototype"] == proto) & (bm["slice"] == sl)]["mean_gross_pct"].iloc[0])

    trap_items = [
        ("正股盘中封板: 偷看日线开盘买 (320笔)", cb2_u["all_day_oc_peek"]["mean_pct"], "#94a3b8"),
        ("正股盘中封板: 真实5分钟封后买 (320笔)", cb2_u["all_5m_open_t0"]["mean_pct"], "#dc2626"),
        ("正股盘中封板: 5分钟破板立即砍 (320笔)", cb2_u["all_5m_brkcut_t0"]["mean_pct"], "#ea580c"),
        ("正股早盘一字: 偷看15点未开板 (323笔)", _bm_mean("CB1_AUDIT_PEEK", "fake_is_yizi_zt_ALL"), "#94a3b8"),
        ("正股早盘一字: 退市强赎债组 (710笔)", _bm_mean("CB1", "delisted_only_T0_Close"), "#f59e0b"),
        ("正股早盘一字: 真实09点25全池 (912笔)", _bm_mean("CB1", "all_causal_T0_Close"), "#dc2626"),
        ("正股早盘一字: 设限20%后全池 (706笔)", _bm_mean("CB1", "post_202208_T0_Close"), "#991b1b"),
        ("正股早盘一字: 仅留存续债样本 (202笔)", _bm_mean("CB1", "active_only_T0_Close"), "#475569"),
    ]
    trap_items = trap_items[::-1]
    y1 = np.arange(len(trap_items))
    vals1 = [x[1] for x in trap_items]
    cols1 = [x[2] for x in trap_items]
    ax1.barh(y1, vals1, height=0.62, color=cols1, alpha=0.92, edgecolor="white")
    ax1.axvline(0.0, color="#0f172a", linewidth=1.2)
    for idx, v in enumerate(vals1):
        ha = "left" if v >= 0 else "right"
        off = 0.14 if v >= 0 else -0.14
        ax1.text(v + off, idx, f"{v:+.2f}%", va="center", ha=ha, fontsize=8.4, fontweight="bold", color="#0f172a")
    ax1.set_yticks(y1)
    ax1.set_yticklabels([x[0] for x in trap_items], fontsize=8.6, fontweight="bold")
    ax1.set_xlabel("单笔毛收益率（%，未扣手续费与抢筹滑点）", fontsize=9.5, fontweight="bold")
    ax1.set_title("一、拆穿偷看未来与幸存偏差：两大映射原型真实均亏", fontsize=10.8, fontweight="bold", pad=12)
    ax1.set_xlim(-4.8, 6.8)
    ax1.grid(axis="x", linestyle="--", alpha=0.35)

    # Right: All 96 WF Scorecard tracks (nav_10 vs ex5_10)
    sub_g = gr[gr["n_trades"] >= 25].copy()
    is_t0 = sub_g["exit_mode"] == "same"
    ax2.add_patch(Rectangle((1.5, 1.15), 1.9, 0.55, facecolor="#dcfce7", alpha=0.55, zorder=0))
    ax2.scatter(sub_g.loc[~is_t0, "nav_10"], sub_g.loc[~is_t0, "ex5_10"], s=48, c="#64748b", alpha=0.72, edgecolors="#0f172a", lw=0.6, label="跨夜T+1赛道各档 (扣万分之十)", zorder=3)
    ax2.scatter(sub_g.loc[is_t0, "nav_10"], sub_g.loc[is_t0, "ex5_10"], s=58, c="#0284c7", alpha=0.85, edgecolors="#0c4a6e", lw=0.8, label="当日T+0零撞车赛道各档", zorder=4)
    ax2.axvline(1.5, color="#dc2626", linestyle="--", lw=1.1, label="初筛线: 净值>=1.5x 且 去前五>=1.15x", zorder=2)
    ax2.axhline(1.15, color="#dc2626", linestyle="--", lw=1.1, zorder=2)
    ax2.axvline(1.0, color="#0f172a", linestyle=":", lw=1.0, zorder=2)
    ax2.axhline(1.0, color="#0f172a", linestyle=":", lw=1.0, zorder=2)

    annots = [
        ("T08_P4_ZTClose_T1O", "top20", "涨停收盘买跨夜(前20%)\n2.96x/去五1.27x(千五0.61x且26年亏)", (1.60, 1.44)),
        ("T11_P5_LowPremStrong_T1O", "sc75", "低溢价跨夜(75分)\n2.45x / 去五仅0.95x", (2.22, 0.68)),
        ("T10_P5_LowPremStrong_T0", "sc80", "低溢价当日T+0(80分)\n1.83x / 去五仅0.86x", (1.62, 0.32)),
        ("T01_CB1_OpenAtZT_T0", "top5", "早盘一字当日T+0(前5%)\n仅0.65x / 去五0.47x", (0.06, 0.86)),
    ]
    for tid, thr, txt, (xt, yt) in annots:
        r = sub_g[(sub_g["track_id"] == tid) & (sub_g["threshold"] == thr)]
        if not r.empty:
            rw = r.iloc[0]
            ax2.annotate(
                txt, xy=(rw["nav_10"], rw["ex5_10"]), xytext=(xt, yt),
                fontsize=7.7, color="#0f172a", fontweight="bold",
                arrowprops=dict(arrowstyle="->", color="#475569", lw=0.85),
            )
    ax2.set_xlabel("2023至2026样本外单仓净值（倍，万分之十费用）", fontsize=9.5, fontweight="bold")
    ax2.set_ylabel("去掉前五大盈利后净值（倍）", fontsize=9.5, fontweight="bold")
    ax2.set_title("二、96组前视多因子打分红队终审：零一组全部过关", fontsize=10.8, fontweight="bold", pad=12)
    ax2.set_xlim(0.0, 3.25)
    ax2.set_ylim(0.0, 1.62)
    ax2.grid(True, linestyle="--", alpha=0.35)
    ax2.legend(loc="upper left", fontsize=8.0, frameon=True)

    plt.tight_layout(pad=2.0)
    fig.savefig(CHART1_PATH, dpi=180, bbox_inches="tight", facecolor="#FFFFFF")
    plt.close(fig)

    # --- Chart 2: Multi-Tier Cost Decay + V20 Empty-Slot T+0 Zero-Collision vs T+1 Crash ---
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15.4, 6.0), dpi=180)
    fig.patch.set_facecolor("#FFFFFF")

    tiers = [10, 20, 50, 100]
    tx = np.arange(len(tiers))
    cost_specs = [
        ("T08_P4_ZTClose_T1O", "top20", "涨停收盘买跨夜(前20%, 395笔)", "#64748b", "--", [(0, 0.08), (0, 0.10), (0, 0.08), (0.14, 0.09)]),
        ("T11_P5_LowPremStrong_T1O", "sc75", "低溢价强催化跨夜(75分, 218笔)", "#f59e0b", "-.", [(0, 0.08), (0.19, -0.02), (0, 0.09), (0, 0.08)]),
        ("T10_P5_LowPremStrong_T0", "sc80", "低溢价强催化当日T+0(80分, 107笔)", "#0284c7", "-", [(0, 0.08), (0, -0.18), (0, 0.09), (0, 0.08)]),
        ("T01_CB1_OpenAtZT_T0", "top20", "正股早盘一字T+0(前20%, 76笔)", "#dc2626", "-", [(0, 0.07), (0, 0.07), (0, 0.07), (-0.16, 0.07)]),
    ]
    for tid, thr, lbl, col, ls, offs in cost_specs:
        rw = gr[(gr["track_id"] == tid) & (gr["threshold"] == thr)].iloc[0]
        ys = [float(rw[f"nav_{b}"]) for b in tiers]
        ax1.plot(tx, ys, marker="o", linewidth=2.2, markersize=6, color=col, linestyle=ls, label=lbl)
        for xi, yv, (dx, dy) in zip(tx, ys, offs):
            va = "bottom" if dy >= 0 else "top"
            ax1.text(xi + dx, yv + dy, f"{yv:.2f}x", ha="center", va=va, fontsize=8.0, fontweight="bold", color=col)
    ax1.axhline(1.0, color="#dc2626", linestyle=":", linewidth=1.3, label="保本生死线 (1.00倍)")
    ax1.set_xticks(tx)
    ax1.set_xticklabels(["万分之十\n(极低佣金)", "万分之二十\n(轻微滑点)", "万分之五十\n(常规抢筹)", "百分之一\n(追高冲击)"], fontsize=8.8, fontweight="bold")
    ax1.set_ylabel("样本外单仓净值（倍）", fontsize=9.5, fontweight="bold")
    ax1.set_title("三、四档交易成本压测：高频微利跨夜盘在千五下崩塌", fontsize=10.8, fontweight="bold", pad=12)
    ax1.set_ylim(0.0, 3.35)
    ax1.grid(True, linestyle="--", alpha=0.35)
    ax1.legend(loc="upper right", fontsize=8.0, frameon=True)

    # Right: V20.0 Empty-Slot Integration (delta_nav_ratio + collision count!)
    rd = audit["redteam_details"]
    cb2_rd = audit["cb2_5m_redteam"]
    v_items = [
        ("现役V20基线\n(61.17万倍)", 1.0, 0, "#0f172a"),
        ("低溢价T+0(80分)\n补44笔/零撞车", rd["T10_P5_LowPremStrong_T0__sc80"]["v20_empty_patch_10bps"]["delta_nav_ratio"], 0, "#0284c7"),
        ("正股一字T+0(全)\n补127笔/零撞车", rd["T01_CB1_OpenAtZT_T0__all_cands"]["v20_empty_patch_10bps"]["delta_nav_ratio"], 0, "#dc2626"),
        ("盘中5m封板T+0\n补33笔/零撞车", cb2_rd["26H2_unbiased_5m_seal_T0_10bps"]["v20_empty_patch_10bps"]["delta_nav_ratio"], 0, "#ea580c"),
        ("低溢价跨夜(75分)\n撞毁13笔主力", rd["T11_P5_LowPremStrong_T1O__sc75"]["v20_empty_patch_10bps"]["delta_nav_ratio"], 13, "#f59e0b"),
        ("涨停收盘跨夜(20%)\n撞毁41笔主力", rd["T08_P4_ZTClose_T1O__top20"]["v20_empty_patch_10bps"]["delta_nav_ratio"], 41, "#991b1b"),
    ]
    x2 = np.arange(len(v_items))
    vals2 = [x[1] for x in v_items]
    cols2 = [x[3] for x in v_items]
    bars2 = ax2.bar(x2, vals2, width=0.55, color=cols2, alpha=0.92, edgecolor="white")
    ax2.axhline(1.0, color="#0f172a", linestyle="--", linewidth=1.2)
    for b, (lbl, val, skip_n, _) in zip(bars2, v_items):
        tag = f"{val:.2f}x\n(撞{skip_n}笔)" if skip_n > 0 else f"{val:.2f}x"
        ax2.text(b.get_x() + b.get_width() / 2, val + 0.025, tag, ha="center", va="bottom", fontsize=8.0, fontweight="bold", color="#0f172a")
    ax2.set_xticks(x2)
    ax2.set_xticklabels([x[0] for x in v_items], fontsize=7.8, fontweight="bold")
    ax2.set_ylabel("接入后总仓相对现役V20净值乘数（倍）", fontsize=9.5, fontweight="bold")
    ax2.set_title("四、接入现役空仓日：T+0物理零撞车 vs 跨夜撞毁九成七", fontsize=10.6, fontweight="bold", pad=12)
    ax2.set_ylim(0.0, 1.42)
    ax2.grid(axis="y", linestyle="--", alpha=0.35)

    plt.tight_layout(pad=2.0)
    fig.savefig(CHART2_PATH, dpi=180, bbox_inches="tight", facecolor="#FFFFFF")
    plt.close(fig)
    return CHART1_PATH, CHART2_PATH


def build_payload(c1_path: str, c2_path: str) -> dict:
    blocks = [
        MIXED([
            ("结论：可转债正股涨停映射整体没用，现役实盘严禁直接拿去碰。", True, True),
            ("补全退市强赎债并还原五分钟实盘后，96组前视打分无一过关。", False, False),
        ]),
        BL(),
        T("一、全市场八百九十三只底数与两大偷看陷阱", bold=True),
        B("历年强赎退市转债高达585只且占六成五，仅留存续债会严重低估弹性。", False),
        B("本轮成功补齐584只已退市债，整体覆盖率99.83%并通过底数检验。", False, True),
        B("官方历史转股溢价率近半数调过价，按初始转股价算有56.3%天数错超5点。", False),
        B("正股早盘一字若偷看全天封死看似均赚+1.21%，真实开盘912笔均亏-2.01%。", False, True),
        B("其中38.3%高开一字当天炸板，拖累转债日内胜率仅2.58%且均跌-5.30%。", False),
        B("设限20%之后早盘一字706笔胜率仅22.1%，日内均亏扩大至-2.59%。", False, True),
        BL(),
        T("二、盘中追买五分钟实测与跨夜撞毁主力对比", bold=True),
        B("正股盘中封板若偷看日线开盘看似+5.28%，实因忽略了盘中资金早已抢跑。", False),
        B("采2026年下半年无偏五分钟线回放，正股封板前转债已被拉高+6.46%。", False, True),
        B("封板后下根五分钟追买320笔毛均亏-0.60%，即便正股破板立斩仍亏-0.48%。", False),
        B("96组前视打分在2024年底截断误差均为0.0，但没有一组过红队终审。", False, True),
        B("看似最高的收盘买跨夜2.96倍全靠千一极低成本，成本提至千五即崩至0.61倍。", False),
        B("该跨夜策略接入现役主力空仓日会撞掉41笔牛股，令总仓净值暴跌-96.8%。", False, True),
        BL(),
        T("三、当日了结物理零撞车的唯一线索与落选硬伤", bold=True),
        B("低溢价低于20%叠加强催化当日15点了结，打分80分107笔单仓达1.83倍。", False),
        B("该赛道在千五滑点下仍余1.19倍，且2024至2026年分年连续收正。", False),
        B("接入现役主力378个空仓日实测0撞车，把总仓从61.2万倍推高至74.3万倍。", False, True),
        B("但去掉赚最多前五笔即跌破0.86倍，夏普仅0.71且让总仓最大回撤升+1.94%。", False, True),
        B("最终裁决明确：可转债映射严禁上实盘，仅作当日了结零撞车结构研究参考。", False),
        BL(),
        BL(),
        BL(),
    ]

    t1 = [
        [C("原型与对比样本", True), C("样本笔数与胜率", True), C("单笔毛收益/中位", True), C("关键失真根因拆解", True)],
        [C("一字偷看15点仍封死"), C("323笔 / 47.1%"), C("+1.21% / -0.05%"), C("偷看盘中绝不开板")],
        [C("一字真实09点25全池"), C("912笔 / 26.3%"), C("-2.01% / -2.61%"), C("38.3%当天炸板崩盘")],
        [C("一字仅存续债(幸存)"), C("202笔 / 17.8%"), C("-3.51% / -3.36%"), C("漏掉八成半退市妖债")],
        [C("一字设限20%后全池"), C("706笔 / 22.1%"), C("-2.59% / -2.70%"), C("集合竞价先抢光空间")],
        [C("盘中封板偷看日开盘"), C("320笔 / 90.6%"), C("+5.28% / +3.51%"), C("忽视盘前已涨+6.46%")],
        [C("盘中封板真实5分钟"), C("320笔 / 39.1%"), C("-0.60% / -0.42%"), C("无偏全样本负期望")],
        [C("盘中封板破板5分斩"), C("320笔 / 35.3%"), C("-0.48% / -0.51%"), C("仍难扛过23%炸板率")],
    ]

    t2 = [
        [C("前视打分与空仓测试", True), C("样本外净值/去前五", True), C("千五费用/夏普", True), C("接主力及红队终审", True)],
        [C("正股收盘买跨夜(前20%)"), C("2.96x / 1.27x"), C("0.61x / 1.29"), C("撞41笔毁-96.8%淘汰")],
        [C("低溢价强催化跨夜75"), C("2.45x / 0.95x"), C("1.02x / 0.92"), C("撞13笔亏-49%且26年亏")],
        [C("低溢价强催化当日80"), C("1.83x / 0.86x"), C("1.19x / 0.71"), C("零撞车+21%但去五亏")],
        [C("低溢价高液5千万当日"), C("1.60x / 0.71x"), C("0.78x / 0.51"), C("回撤47.9%且26年大亏")],
        [C("正股高开+5%当日80分"), C("1.28x / 0.65x"), C("0.77x / 0.37"), C("回撤54.1%且24年腰斩")],
        [C("正股一字当日前5%"), C("0.65x / 0.47x"), C("0.58x / -0.57"), C("随机抽签胜出仅0.51")],
        [C("盘中5分钟封板当日"), C("0.30x / 0.22x"), C("严重亏损 / -5.42"), C("零撞车仍拖累主力-45%")],
    ]

    sections_tables = [
        ("表一：可转债映射偷看陷阱、幸存者偏差与真实五分钟对比", t1, c1_path),
        ("表二：前视多因子打分、多档成本及接入现役主力空仓日终审", t2, c2_path),
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
    print("[DryRun PASS] RD046 Feishu payload 100% validated!")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    audit = json.load(open(f"{OUT_DIR}/rd046_audit.json", encoding="utf-8"))
    bm = pd.read_csv(f"{OUT_DIR}/rd046_blind_matrix.csv")
    gr = pd.read_csv(f"{OUT_DIR}/rd046_grid.csv")

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
            "title": payload["title"], "doc_id": doc_id, "node_token": node_tok, "wiki_url": wiki_url,
            "parent_node_token": fh.INVALID_PARENT_NODE, "verify": v, "hub_update": hub_res,
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

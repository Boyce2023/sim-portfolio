#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD044 Step 6: Generate 2 Crisp Pure-Chinese Charts & Publish Strict Feishu Report (`量化四大家族实证`)
to Valid Library (`OPKUwAqCDibLfRkRE87cd2aCnVc`) + Incrementally Update Valid Hub (`IRxgdlpOUoqfV4xVYYGczGurnyD`).
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
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
assert "yfinance" not in sys.modules, "D12 violation!"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd044_quant_4families_review_20261126"
CACHE_DIR = f"{OUT_DIR}/_cache"
RD041_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd041_day0_firstboard_sweep_20261126"
FS_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/feishu_master_docs_20261116"
for p in (OUT_DIR, RD041_DIR, FS_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import _rd041_feishu_helpers as fh  # noqa: E402
import step6_upgrade_3strategies_20261117 as s6  # noqa: E402
import step9_sync_v191_exits_20261118 as s9  # noqa: E402

TITLE = "量化四大家族实证"
HUB_ROW = [
    "量化四大家族实证",
    "5年307组多资产检验",
    "风险平价夏普1.88，微盘择时26.7%，反转与业绩快报证伪",
    "风险平价配V20降回撤，微盘限千万内",
]

CHART1_PATH = f"{OUT_DIR}/rd044_chart1_4families_nav_and_yearly.png"
CHART2_PATH = f"{OUT_DIR}/rd044_chart2_v20_corr_and_dual_ledger.png"

C = fh.C
T = fh.T
B = fh.B
BL = fh.BL
MIXED = fh.MIXED

plt.rcParams["font.sans-serif"] = ["PingFang SC", "Hiragino Sans GB", "STHeiti", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def build_charts(audit: dict) -> tuple[str, str]:
    npz = np.load(f"{CACHE_DIR}/rd044_champions_daily.npz")
    dts = npz["cal_dts"]
    wf_m = dts >= "2023-01-03"
    dts_wf = pd.to_datetime(dts[wf_m])

    # --- Chart 1: 2023-2026 OOS NAV curves + Yearly Returns & MDD ---
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15.2, 5.9), dpi=180)
    fig.patch.set_facecolor("#FFFFFF")

    series_spec = [
        ("F2_SC_30m_MOM20_Bond", "F2 小市值国债择时 (夏普1.31 / 回撤14.8%)", "#dc2626", "-", 2.1, 0.0),
        ("QUANT_ALPHA_BLEND", "三策略量化合体 (夏普1.80 / 回撤6.1%)", "#0f172a", "-", 2.2, 0.0),
        ("F4_MOM_R2_20_K3_H20", "F4 行业宽基动量 (夏普0.82 / 回撤18.8%)", "#0284c7", "--", 1.7, 0.045),
        ("F3_BB_LOWPOS_WF35_H20", "F3 回购低位精选 (夏普1.09 / 回撤16.6%)", "#7c3aed", "-", 1.7, -0.055),
        ("F1_LOWVOL_50m_H20", "F1 低波动单因子 (夏普0.80 / 回撤12.6%)", "#d97706", "-.", 1.6, 0.0),
        ("F4_RP_Pure60d_H10", "F4 大类风险平价 (夏普1.88 / 回撤2.8%)", "#059669", "-", 2.1, 0.0),
        ("csi300_dr", "沪深300基准", "#94a3b8", ":", 1.5, 0.0),
    ]
    for key, lbl, col, ls, lw, y_off in series_spec:
        dr = npz[key][wf_m]
        nav = np.cumprod(1.0 + dr)
        ax1.plot(dts_wf, nav, label=lbl, color=col, linestyle=ls, linewidth=lw)
        ax1.text(dts_wf[-1], nav[-1] + y_off, f" {nav[-1]:.2f}x", va="center", ha="left", fontsize=7.8, color=col, fontweight="bold")

    ax1.axhline(1.0, color="#64748b", linestyle=":", linewidth=1.0)
    ax1.set_title("一、四大量化家族样本外净值走势（2023至2026年11月）", fontsize=11.0, fontweight="bold", pad=12)
    ax1.set_ylabel("累计净值（倍，已扣真实双边费用）", fontsize=9.5, fontweight="bold")
    ax1.set_xlim(dts_wf[0], dts_wf[-1] + pd.Timedelta(days=95))
    ax1.grid(True, linestyle="--", alpha=0.35)
    ax1.legend(loc="upper left", fontsize=7.6, frameon=True)

    # Right panel: Yearly Returns 2023/2024/2025/2026 across key representatives
    cats = [
        ("F4_RP_Pure60d_H10", "F4风险平价"),
        ("F2_SC_30m_MOM20_Bond", "F2微盘择时"),
        ("F3_BB_LOWPOS_WF35_H20", "F3回购精选"),
        ("F4_MOM_R2_20_K3_H20", "F4 ETF动量"),
        ("F1_LOWVOL_50m_H20", "F1低波单因子"),
        ("QUANT_ALPHA_BLEND", "量化三合体"),
    ]
    yrs = [("Y2023", "2023年", "#64748b"), ("Y2024", "2024年", "#0284c7"), ("Y2025", "2025年", "#059669"), ("Y2026", "2026年", "#d97706")]
    x = np.arange(len(cats))
    w = 0.19
    cm_aud = audit["champion_metrics"]
    for idx_y, (yk, ylbl, ycol) in enumerate(yrs):
        vals = [cm_aud[ck][yk]["tot_ret_pct"] for ck, _ in cats]
        bars = ax2.bar(x + (idx_y - 1.5) * w, vals, width=w, color=ycol, alpha=0.90, label=ylbl)
        for b, v in zip(bars, vals):
            if v >= 0:
                ax2.text(b.get_x() + b.get_width() / 2, v + 0.8, f"{v:.0f}%", ha="center", va="bottom", fontsize=7.0, fontweight="bold", color="#0f172a")
            else:
                ax2.text(b.get_x() + b.get_width() / 2, v - 0.8, f"{v:.0f}%", ha="center", va="top", fontsize=7.0, fontweight="bold", color="#0f172a")

    ax2.axhline(0.0, color="#0f172a", linewidth=1.0)
    ax2.set_xticks(x)
    ax2.set_xticklabels([cn for _, cn in cats], fontsize=8.8, fontweight="bold")
    ax2.set_ylabel("分年度净收益率（%）", fontsize=9.5, fontweight="bold")
    ax2.set_title("二、分年度收益稳定性拆解（无单一牛市依赖）", fontsize=11.0, fontweight="bold", pad=12)
    ax2.set_ylim(-10, 72)
    ax2.grid(axis="y", linestyle="--", alpha=0.35)
    ax2.legend(loc="upper right", fontsize=8.2, frameon=True, ncol=2)

    plt.tight_layout(pad=2.0)
    fig.savefig(CHART1_PATH, dpi=180, bbox_inches="tight", facecolor="#FFFFFF")
    plt.close(fig)

    # --- Chart 2: Correlation Heatmap vs V20.0 + Dual-Ledger Frontier & T0 Cash Conflict ---
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15.2, 5.9), dpi=180)
    fig.patch.set_facecolor("#FFFFFF")

    corr_keys = [
        ("v20_dr", "现役V20游资"),
        ("F4_RP_Pure60d_H10", "F4风险平价"),
        ("F4_MOM_R2_20_K3_H20", "F4 ETF动量"),
        ("F2_SC_30m_MOM20_Bond", "F2微盘择时"),
        ("F3_BB_LOWPOS_WF35_H20", "F3回购精选"),
        ("F1_LOWVOL_50m_H20", "F1低波因子"),
        ("QUANT_ALPHA_BLEND", "量化三合体"),
        ("csi300_dr", "沪深300"),
    ]
    mat_data = np.column_stack([npz[k][wf_m] for k, _ in corr_keys])
    cmat = np.corrcoef(mat_data.T)
    im = ax1.imshow(cmat, cmap="RdBu_r", vmin=-0.4, vmax=1.0)
    lbls = [lbl for _, lbl in corr_keys]
    ax1.set_xticks(np.arange(len(lbls)))
    ax1.set_yticks(np.arange(len(lbls)))
    ax1.set_xticklabels(lbls, rotation=32, ha="right", fontsize=8.4, fontweight="bold")
    ax1.set_yticklabels(lbls, fontsize=8.4, fontweight="bold")
    for i in range(len(lbls)):
        for j in range(len(lbls)):
            val = cmat[i, j]
            tc = "#FFFFFF" if val > 0.55 else "#0f172a"
            ax1.text(j, i, f"{val:+.2f}", ha="center", va="center", fontsize=8.0, color=tc, fontweight="bold")
    ax1.set_title("三、样本外日收益相关性矩阵：量化四家族与现役V20近零相关", fontsize=10.8, fontweight="bold", pad=12)

    # Right panel: Dual-Ledger Sharpe & MDD comparison + T0 empty-slot crash warning
    v20_bl = audit["v20_correlation_and_blends"]
    pts = [
        ("100%现役V20\n(基线基准)", v20_bl["F4_RP_Pure60d_H10"]["blends"]["v20_100pct"]["mdd_pct"], v20_bl["F4_RP_Pure60d_H10"]["blends"]["v20_100pct"]["sharpe"], "#dc2626"),
        ("70%V20+30%风险平价\n(无限容量稳定器)", v20_bl["F4_RP_Pure60d_H10"]["blends"]["daily_70v20_30q"]["mdd_pct"], v20_bl["F4_RP_Pure60d_H10"]["blends"]["daily_70v20_30q"]["sharpe"], "#059669"),
        ("70%V20+30%微盘择时\n(限千万内)", v20_bl["F2_SC_30m_MOM20_Bond"]["blends"]["daily_70v20_30q"]["mdd_pct"], v20_bl["F2_SC_30m_MOM20_Bond"]["blends"]["daily_70v20_30q"]["sharpe"], "#0284c7"),
        ("50%V20+50%风险平价\n(双账本半仓)", v20_bl["F4_RP_Pure60d_H10"]["blends"]["daily_50v20_50q"]["mdd_pct"], v20_bl["F4_RP_Pure60d_H10"]["blends"]["daily_50v20_50q"]["sharpe"], "#10b981"),
        ("50%V20+50%量化合体\n(夏普冲至4.78)", v20_bl["QUANT_ALPHA_BLEND"]["blends"]["daily_50v20_50q"]["mdd_pct"], v20_bl["QUANT_ALPHA_BLEND"]["blends"]["daily_50v20_50q"]["sharpe"], "#7c3aed"),
    ]
    # Bar pair: MDD & Sharpe across configurations + T0 collision note
    names_p = [p[0] for p in pts]
    mdds_p = [p[1] for p in pts]
    shs_p = [p[2] for p in pts]
    cols_p = [p[3] for p in pts]
    xp = np.arange(len(pts))
    bars_m = ax2.bar(xp, mdds_p, width=0.52, color=cols_p, alpha=0.88, edgecolor="white")
    for b, m_v, s_v in zip(bars_m, mdds_p, shs_p):
        ax2.text(b.get_x() + b.get_width() / 2, m_v + 0.8, f"回撤 {m_v:.1f}%\n夏普 {s_v:.3f}", ha="center", va="bottom", fontsize=7.9, fontweight="bold", color="#0f172a")

    ax2.set_xticks(xp)
    ax2.set_xticklabels(names_p, fontsize=7.8, fontweight="bold")
    ax2.set_ylabel("组合最大回撤（%，越低越稳）", fontsize=9.5, fontweight="bold")
    ax2.set_title("四、独立双账本切分显著压降V20回撤且抬升夏普（对比强塞T0毁仓九成）", fontsize=10.5, fontweight="bold", pad=12)
    ax2.set_ylim(0, 58)
    ax2.grid(axis="y", linestyle="--", alpha=0.35)
    ax2.text(
        0.52, 0.88,
        "注：若将T0品种硬塞进V20空仓日，\n日内买卖因手续费亏10%至64%，\n隔夜持仓则会撞掉121笔早盘买单毁仓96%。",
        transform=ax2.transAxes, fontsize=8.0, color="#991b1b",
        bbox=dict(boxstyle="round,pad=0.4", facecolor="#fef2f2", edgecolor="#fca5a5"),
    )

    plt.tight_layout(pad=2.0)
    fig.savefig(CHART2_PATH, dpi=180, bbox_inches="tight", facecolor="#FFFFFF")
    plt.close(fig)
    return CHART1_PATH, CHART2_PATH


def build_payload(c1_path: str, c2_path: str) -> dict:
    blocks = [
        MIXED([
            ("结论：量化四家族中风险平价与微盘择时有用，且与游资体系几乎零相关。", True, True),
            ("截面反转复合与业绩互动易全线没用，空仓硬塞当日可卖品种反毁主力。", False, False),
        ]),
        BL(),
        T("一、大类风险平价与微盘择时通过零偷看检验", bold=True),
        B("风险平价每两周按60天波动倒数配六类资产，样本外年化 +7.25%。", False, True),
        B("该模型样本外夏普高达1.876，且最大回撤仅控制在 2.79% 以内。", False, True),
        B("该模型年换手仅65%，可容数十亿资金且千三滑点后夏普仍有1.834。", False),
        B("微盘三十名五日轮动配二十天动量开关，样本外年化高达 +26.70%。", False, True),
        B("该微盘模型样本外夏普为1.308，最大回撤由四成骤降至14.78%。", False),
        B("去年初微盘踩踏期开关将亏损锁在 -2.36%，扣千八成本年化仍超 +20%。", False),
        B("但微盘容量受限极严，成交门槛升至五千万时夏普便腰斩跌回0.749。", False),
        BL(),
        T("二、截面反转复合与公告事件两路证伪与一枝弱分化", bold=True),
        B("截面反转六因子全池排序虽有正相关，多头接飞刀叠加高换手反而亏损。", False, True),
        B("仅低波动单因子月调仓略赚 +10.51%，扣千八滑点夏普即跌破0.46。", False),
        B("业绩预增与扭亏快报公告全线失效，次日接盘最佳年化仅 +0.19%。", False, True),
        B("互动易调研密集突变同样全线失效，所有持仓周期样本外净收益全负。", False),
        B("低位缩量回购叠加前视打分夏普1.093，但放宽门槛至半数即跌回0.73。", False),
        BL(),
        T("三、与现役游资相关性及双账本配置法则", bold=True),
        B("四大类量化策略与现役V20日收益相关性仅 -0.011 至 +0.064。", False, True),
        B("切分独立双账本优势极显，五五开配量化合体把回撤从47.3%压至26.5%。", False, True),
        B("同时五五开合体将夏普由4.656抬升至4.779，七三开亦可压回撤至35.6%。", False),
        B("严禁把黄金国债等当日可卖品种塞进空仓日，日内交易全亏且隔夜毁仓九成六。", False, True),
        B("落地方案首选风险平价作大资金独立底仓，小资金可千万内配微盘动量择时。", False),
        BL(),
        BL(),
        BL(),
    ]

    t1 = [
        [C("家族与代表策略", True), C("样本外年化/夏普", True), C("最大回撤/换手", True), C("压力测试与终裁", True)],
        [C("F4 大类风险平价"), C("+7.25% / 1.876"), C("2.79% / 65%"), C("千三仍1.83，大资金过关")],
        [C("F4 宽基行业动量"), C("+16.29% / 0.821"), C("18.81% / 445%"), C("26年强但回撤偏大作备选")],
        [C("F2 微盘3000万择时"), C("+26.70% / 1.308"), C("14.78% / 592%"), C("千八仍+20%，限千万内观察")],
        [C("F2 微盘5000万门槛"), C("+13.94% / 0.749"), C("26.27% / 497%"), C("容量扩后夏普减半暴露局限")],
        [C("F3 低位回购前35%"), C("+15.58% / 1.093"), C("16.56% / 194%"), C("阈值敏感且今年转弱作辅助")],
        [C("F3 业绩预增与互动易"), C("+0.19% / 0.116"), C("40.75% / 905%"), C("全线证伪淘汰，严禁使用")],
        [C("F1 六因子统计反转"), C("-0.77% / 0.076"), C("36.58% / 1188%"), C("接飞刀高换手，纯多头证伪")],
        [C("F1 低波单因子月调"), C("+10.51% / 0.797"), C("12.59% / 923%"), C("千八跌至0.46，不足以独立")],
    ]

    t2 = [
        [C("双账本与补位方案", True), C("与V20相关性", True), C("组合夏普", True), C("组合回撤与实操裁决", True)],
        [C("现役V20独跑基准"), C("+1.000"), C("4.656"), C("47.32% (高收益高回撤)")],
        [C("七三开配风险平价"), C("+0.025"), C("4.690"), C("35.63% (无限容量压回撤)")],
        [C("五五开配风险平价"), C("+0.025"), C("4.733"), C("26.76% (回撤近腰斩抬夏普)")],
        [C("七三开配微盘择时"), C("+0.059"), C("4.738"), C("35.70% (限千万内双引擎)")],
        [C("五五开配量化三合体"), C("+0.077"), C("4.779"), C("26.47% (夏普最高正交组合)")],
        [C("空仓日内买卖纳指金"), C("0笔撞车"), C("降 -0.05至 -0.19"), C("空仓段净值跌成0.78至0.90")],
        [C("空仓隔夜持仓补位"), C("撞车121笔"), C("降 -0.65至 -0.84"), C("九成六净值毁损，严禁补位")],
    ]

    sections_tables = [
        ("表一：A股量化四大家族样本外实证与红队压力对照（2023至2026年11月）", t1, c1_path),
        ("表二：与现役V20游资相关性、独立双账本降回撤及空仓补位实测", t2, c2_path),
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
    print("[DryRun PASS] RD044 payload 100% validated!")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    audit = json.load(open(f"{OUT_DIR}/rd044_audit.json", encoding="utf-8"))
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
        done, fail = fh.write_doc_with_interleaved_charts(doc_id, payload["blocks"], payload["sections_tables"])
        assert fail == 0, f"Write failed: {fail}"
        time.sleep(0.8)
        v = s9.verify_document_v191(doc_id, payload["title"], expected_tables_count=len(payload["tables"]), has_img=True)
        assert v["images_count"] >= 2, f"Missing charts: {v}"

        raw_txt = s6.api(f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/raw_content", method="GET")["data"]["content"]
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
        with open(f"{OUT_DIR}/feishu_publish_result.json", "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
        print(json.dumps(res, ensure_ascii=False, indent=2))
    finally:
        fcntl.flock(lock_f, fcntl.LOCK_UN)
        lock_f.close()


if __name__ == "__main__":
    main()

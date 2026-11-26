#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD037 Feishu Publisher: Pure-human Chinese falsification report
Title: `一进二映射同行龙头实证`
Target Hub: `证伪回测与避坑墓碑` (I_NODE = QiDewdTkJiquokkbbo6cWr3Fn6f, I_DOC = ZTaudjSqtoaj71xTPSLciMcdnLb)
Incremental hub update preserving all 14 existing entries + prepending RD037 (= 15 total).
"""
import argparse
import fcntl
import json
import os
import re
import sys
import time
from pathlib import Path

assert "yfinance" not in sys.modules, "D12 violation!"

RD037_DIR = Path("/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd037_1to2_peer_leaders_20261126")
FS_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/feishu_master_docs_20261116"
for p in (str(RD037_DIR), FS_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

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
TITLE_RD037 = "一进二映射同行龙头实证"

RD037_LATIN_TOKEN_RE = re.compile(
    r"\b(?:WF|OOS|IS|PIT|BH-FDR|DSR|CSCV|PBO|LOO|PLR|MDD|NAV|Sharpe|Calmar|bps|KPL|CSRC)\b"
)
RD037_CN_JARGON = ["q值", "p值", "t值", "消融", "重锚", "回灌", "门禁", "闭环", "矩阵", "铁证", "铁律"]

EXISTING_14_INVALID_ROWS = [
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


def _c(txt, bold=False):
    return [(str(txt), {"bold": True} if bold else {})]


def audit_zero_jargon_rd037(d: dict):
    texts = [d["title"]]
    for b in d["blocks"]:
        els = b.get("text", b.get("bullet", b.get("ordered", {}))).get("elements", [])
        texts.append("".join(e["text_run"]["content"] for e in els))
    for t_title, t_rows in d["tables"]:
        texts.append(t_title)
        for rw in t_rows:
            for cell in rw:
                texts.append("".join(x for x, _ in cell))

    for t in texts:
        m = RD037_LATIN_TOKEN_RE.search(t)
        if m:
            raise ValueError(f"发现禁用缩写 '{m.group(0)}': {t}")
        for jw in RD037_CN_JARGON:
            if jw in t:
                raise ValueError(f"发现禁用黑话 '{jw}': {t}")


def build_rd037_doc() -> dict:
    blocks = [
        P([
            TR("结论：一进二信号日映射买同板块四类龙头全线没用，严禁替代实盘。", background_color=3),
            TR("同批盲买跑输一进二本尊百倍，483组打分精选同样零组通过红队终审。", background_color=3),
            TR("若强行替换一进二或硬塞空仓位，现行合体总仓净值反撤 -97% 以上。"),
        ]),
        P([TR("一、正面一对一比拼：四类同行全线惨败于一进二本尊", bold=True)]),
        B([
            TR("同一批92笔实盘信号，按千分之三费用算，一进二本尊五年赚432.64倍。", background_color=3),
            TR("本尊胜率高达70.65%，笔均收益+7.90%，去掉前五极值仍赚32.12倍。"),
        ]),
        B([
            TR("实盘92笔中有78笔在盘中才触发买入，仅14笔在早盘竞价已确定。", background_color=3),
            TR("盘中才触发时绝不能偷看结果去早盘买同行，偷跑会让大票虚高成2.89倍。"),
        ]),
        B([
            TR("严守无未来规则在当日尾盘或次日早盘买四类同行，五年净值全在1.3倍以下。", background_color=3),
            TR("相对最稳的题材大票尾盘买拿1天仅1.30倍，且今年净值跌成0.81倍。"),
            TR("近期活跃新龙次日早盘接力最惨，拿1天五年净值亏至0.17倍，拿2天剩0.08倍。"),
        ]),
        B([
            TR("就算只看早盘竞价已明牌的高分大池189天，最好新龙早盘拿1天仅3.16倍。"),
            TR("且去掉前五极值只剩1.23倍，今年下半年同样回落亏至0.80倍。"),
        ]),
        P([TR("二、前视多因子打分：483组规则零组通过红队终审", bold=True)]),
        B([
            TR("2023至2026年共测69套时点前视模型与483组打分规则，全线淘汰。", background_color=3),
            TR("2024年底物理截断前后打分与收益最大差值均为0.0，完全零泄漏。"),
        ]),
        B([
            TR("483组规则仅2组去掉前五极值超1.2倍，但合起来全部零组过关。", background_color=3),
            TR("没有哪怕1组能同时满足去极值稳健、防撞大运检验以及不拉垮合体总仓。"),
        ]),
        O([
            TR("活跃新龙次日早盘拿1天前10%账面4.60倍，但邻档前20%立刻崩至0.56倍。"),
            TR("将成本升至千五后去前五极值跌剩0.75倍，还会拉垮合体总仓 -55.6%。"),
        ], seq="1"),
        O([
            TR("中小盘老龙早盘拿1天70分档表面2.17倍，撞大运检验直接不通过。"),
            TR("把交易成本升至千五后五年净值反跌成0.67倍，去掉前五只剩0.41倍。"),
        ], seq="auto"),
        O([
            TR("题材大票次日早盘拿3天账面最高5.57倍。但千五成本下去极值全不足0.90倍。"),
            TR("一旦加入现行六策略合体仓，合体总净值会直接被撞成 -88% 至 -96%。"),
        ], seq="auto"),
        P([TR("三、实战替身与踏空补位：硬塞同行反毁总仓", bold=True)]),
        B([
            TR("将合体里43笔一进二换成任意同行，总仓五年净值直接雪崩。仅剩原版0.003至0.028倍。", background_color=3),
            TR("原版合体五年赚6913万倍，换同行后五年复利只剩零头。"),
        ]),
        B([
            TR("遇到头名一字涨停或高开超限买不到44天，行业龙一早盘拿1天五年仅1.01倍。"),
            TR("扣千五成本后五年剩0.93倍。空仓期19笔独立净值1.14倍，去极值仅0.85倍。"),
        ]),
        B([
            TR("遇到盘中条件未触发踏空61天，次日接力最强150亿大票两年也仅赚1.78倍。"),
            TR("去掉前五极值亏成0.80倍，拼进合体仓反而拉垮总仓 -38% 至 -47%。"),
        ]),
        P([TR("四、供给与资金物理根因：先锋溢价无法外溢", bold=True)]),
        B([
            TR("一进二高分股是短线边际资金唯一抢筹的身位先锋，近85%在盘中才放量确认。", background_color=3),
            TR("盘中确认后资金已完成日内定价，尾盘或次日再买同行等于高潮后接盘。"),
        ]),
        B([
            TR("哪怕早盘竞价已出高分，同行只能同步分摊板块回撤，吃不到身位板连板溢价。"),
            TR("因此全市场各类同行龙一均无法通过防滑点、去极值与合体对比三关。"),
        ]),
        BL(), BL(), BL(),
    ]

    tables = [
        ("表一：92笔实盘同批一进二本尊 vs 无偷看盲买四类同行（千三双边费用）", [
            [_c("测试标的与买点", True), _c("笔数/胜率", True), _c("五年净值/去前5", True), _c("2026年净值", True)],
            [_c("一进二本尊(同费对比)", True), _c("92笔 / 70.65%", True), _c("432.64x / 32.12x", True), _c("3.15x", True)],
            [_c("百亿题材大票(尾盘1天)"), _c("88笔 / 54.55%"), _c("1.30x / 0.78x"), _c("0.81x")],
            [_c("百亿行业大票(次早2天)"), _c("83笔 / 43.37%"), _c("1.24x / 0.58x"), _c("0.95x")],
            [_c("题材老游资龙(尾盘1天)"), _c("88笔 / 47.73%"), _c("0.96x / 0.61x"), _c("1.04x")],
            [_c("行业绝对龙一(尾盘1天)"), _c("89笔 / 47.19%"), _c("0.90x / 0.58x"), _c("0.99x")],
            [_c("近期活跃新龙(尾盘1天)"), _c("87笔 / 47.13%"), _c("0.71x / 0.45x"), _c("0.98x")],
            [_c("近期活跃新龙(次早1天)"), _c("85笔 / 42.35%"), _c("0.17x / 0.08x"), _c("0.81x")],
        ]),
        ("表二：483组前视打分精选最高分档红队复检与千五滑点压力", [
            [_c("打分代表方案", True), _c("千三样本外/去前5", True), _c("千五去前5/合体影响", True), _c("红队终审", True)],
            [_c("新龙次早1天 前10%"), _c("4.60x / 1.87x"), _c("0.75x / 合体0.44x"), _c("前20%崩0.56x，淘汰")],
            [_c("中小老龙早盘1天 70分"), _c("2.17x / 1.30x"), _c("0.41x / 合体1.28x"), _c("千五总净值0.67x，淘汰")],
            [_c("百亿大票次早3天 75分"), _c("3.45x / 1.11x"), _c("0.68x / 合体0.12x"), _c("严重撞车合体，淘汰")],
            [_c("全类同行次早1天 前20%"), _c("2.12x / 1.13x"), _c("0.76x / 合体0.08x"), _c("千五不过1倍，淘汰")],
        ]),
        ("表三：一进二替换与踏空接力接入现行六策略合体仓效果", [
            [_c("合体接入方式", True), _c("样本笔数", True), _c("独立净值/去前5", True), _c("对合体总仓影响", True)],
            [_c("全替合体内一进二"), _c("38至41笔"), _c("远逊本尊+11.24%"), _c("总仓净值回撤 -97% 以上")],
            [_c("一字踏空买行业龙一"), _c("19笔空仓"), _c("1.14x / 0.85x"), _c("偶避4笔老单，无效")],
            [_c("未触发踏空买150亿大票"), _c("51笔盲买"), _c("1.78x / 0.80x"), _c("拉垮总仓 -38% 至 -47%")],
        ]),
    ]

    return {
        "title": TITLE_RD037,
        "blocks": blocks,
        "tables": tables,
        "img_path": None,
    }


def build_updated_invalid_hub_payload() -> dict:
    rd037_row = (
        TITLE_RD037,
        "5年61万条全量",
        "盲买跑输百倍，483组打分0过红队，替一进二净值 -97%",
        "禁作一进二替代或补位",
    )
    rows = [rd037_row] + EXISTING_14_INVALID_ROWS
    return build_hub_doc(
        "证伪回测与避坑墓碑",
        "结论：本目录收录6大主力外已证伪小策略与全市场亏钱陷阱，用于永久避坑。",
        rows,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    doc = build_rd037_doc()
    hub = build_updated_invalid_hub_payload()

    s9.check_first_sentence_rule(doc)
    audit_zero_jargon_rd037(doc)
    audit_zero_jargon_rd037(hub)
    longs = s9.audit_doc_strict_v191(doc, require_img=False)
    longs_hub = s9.audit_doc_strict_v191(hub, require_img=False)
    if longs or longs_hub:
        raise ValueError(f"Long sentences found: rd037={len(longs)}, hub={len(longs_hub)}")

    if args.dry_run:
        print("[Dry-Run PASS] Zero audit errors on RD037 doc & 15-row Invalid Hub!")
        return

    lock_fd = open(s6.LOCK_PATH, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        did, ntk = s9.find_or_create_child_node(I_NODE, TITLE_RD037)
        if did in s6.PROTECTED_DOCS:
            raise RuntimeError(f"Protected: {did}")
        _, fail = s6.write_document_payload(did, doc["blocks"], doc["tables"], None)
        if fail > 0:
            raise RuntimeError(f"Write fail={fail}")
        time.sleep(1.2)
        v = s9.verify_document_v191(did, TITLE_RD037, expected_tables_count=len(doc["tables"]), has_img=False)

        r_raw = s6.api(f"{s6.BASE}/open-apis/docx/v1/documents/{did}/raw_content", method="GET")
        online_raw = r_raw.get("data", {}).get("content", "")
        m_on = RD037_LATIN_TOKEN_RE.search(online_raw)
        if m_on:
            raise ValueError(f"Online raw_content jargon hit: {m_on.group(0)}")
        for jw in RD037_CN_JARGON:
            if jw in online_raw:
                raise ValueError(f"Online raw_content CN jargon hit: {jw}")

        _, fail2 = s6.write_document_payload(I_DOC, hub["blocks"], hub["tables"], None)
        if fail2 > 0:
            raise RuntimeError(f"Hub write fail={fail2}")
        time.sleep(1.2)
        vhub = s9.verify_document_v191(I_DOC, "证伪回测与避坑墓碑", expected_tables_count=1, has_img=False)

        url = f"https://my.feishu.cn/wiki/{ntk}"
        mf = json.load(open(s6.MANIFEST_PATH, "r", encoding="utf-8"))
        mf.setdefault("nodes", {})["rd037_1to2_peer_leaders"] = {
            "title": TITLE_RD037,
            "node_token": ntk,
            "obj_token": did,
            "parent_node_token": I_NODE,
            "wiki_url": url,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        json.dump(mf, open(s6.MANIFEST_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

        pub_res = {
            "wiki_url": url,
            "node_token": ntk,
            "doc_id": did,
            "parent_node_token": I_NODE,
            "verify": v,
            "hub_verify": vhub,
            "online_raw_chars": len(online_raw),
        }
        (RD037_DIR / "feishu_publish_result.json").write_text(json.dumps(pub_res, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"PUBLISHED_INVALID [{ntk}] {url} | chars={v['raw_chars']} | tables={v['tables_count']}")
        print(f"UPDATED_INVALID_HUB 15 items verified PASS! chars={vhub['raw_chars']}")
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    main()

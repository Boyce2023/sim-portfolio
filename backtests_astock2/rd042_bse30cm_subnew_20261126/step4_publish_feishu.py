#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD042 Step 4: Validate & Publish Pure Plain-Chinese Feishu Report (`北交所与近端次新实证`)
to `证伪回测与避坑墓碑` (`QiDewdTkJiquokkbbo6cWr3Fn6f`) & Safely Increment Hub (`ZTaudjSqtoaj71xTPSLciMcdnLb`).
Zero jargon, zero banned punctuation, <=4-col tables, online read-back verified.
"""
import argparse
import fcntl
import json
import os
import re
import sys
import time
import warnings

warnings.filterwarnings("ignore")
assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd042_bse30cm_subnew_20261126"
RD041_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd041_day0_firstboard_sweep_20261126"
FS_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/feishu_master_docs_20261116"
for p in (OUT_DIR, RD041_DIR, FS_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import _rd041_feishu_helpers as fh  # noqa: E402
import step6_upgrade_3strategies_20261117 as s6  # noqa: E402
import step9_sync_v191_exits_20261118 as s9  # noqa: E402

TITLE = "北交所与近端次新实证"
HUB_ROW = [
    "北交所与近端次新实证",
    "5年3070+3006笔",
    "双赛道打分247组零过关，去前五全跌破0.7倍且撞毁主力",
    "严禁接盘次新与30cm情绪套利",
]

C = fh.C
T = fh.T
B = fh.B
BL = fh.BL
MIXED = fh.MIXED


def build_payload(c1_path: str, c2_path: str) -> dict:
    blocks = [
        MIXED([
            ("结论：北交所30cm与近端次新博弈整体没用，247组前视打分精选零过关。", True, True),
            ("表面高净值全靠极少暴涨极值与时间错位，去前五大盈利后全线跌破保本线且撞毁主力。", False, False),
        ]),
        BL(),
        T("一、近端次新股无套牢盘三大玩法全线证伪", bold=True),
        B("严剔上市前五日无涨跌幅噪声后，五年共扫出上市6至60日有效事件3070笔。", False),
        B("首板涨停次日承接五年跌至0.01x，横盘突破新高同样亏损至0.05x。", False, True),
        B("唯独连跌破位缩量反抽表面见2.17x，但去掉前五大盈利交易即暴跌至0.41x。", False),
        B("全市场同日等权分散买入无一赚钱，反抽策略等权净值仅为0.35x至0.45x。", False, True),
        B("近端次新并无老庄记忆锚点，新股高定价叠加解禁抛压导致均值回归持续失血。", False),
        BL(),
        T("二、北交所30cm数据核验与924前后流动性断层", bold=True),
        B("本轮实采现存357只北交所股票五年全量日线，与本地库重叠25万行零误差。", False),
        B("受退市与转板影响缺失广道退与云创退等五只标的，存在轻微向上幸存者偏差。", False),
        B("2024年9月24日前成交中位仅355万元，之后跃升至4102万元。", False, True),
        B("北交所30cm涨停次日无论924前后均大亏，924后全池次日卖净值仅0.04x。", False),
        B("即使只买924后且成交额超1亿元的涨停，两日卖去前五极值仍跌至0.12x。", False, True),
        BL(),
        T("三、30cm大阳暴利幻觉与247组前视打分终审", bold=True),
        B("表面15%以上大阳三日卖五年见74.33x，实为单仓顺延踩中极少妖股的巧合。", False, True),
        B("同一池子改按同日等权买入五年净值归零，且924后去前五大盈利仅剩0.40x。", False),
        B("前十大盈利单全部集中在2023年11月与2024年10月两轮十余天政策脉冲。", False),
        B("在247组前视多因子打分及924后单独训练里，无一组同时过极值与置换检验。", False, True),
        B("强制并入现役主力空仓日后大面积撞车拖累净值，且全部赛道通过年底截断零误差。", False),
        B("实操结论明确：严禁立项近端次新与北交所30cm短线接盘，守死现役主力体系。", False, True),
        BL(),
        BL(),
        BL(),
    ]

    t1 = [
        [C("近端次新玩法切片", True), C("笔数/胜率", True), C("五年/样本外", True), C("去前5/红队裁决", True)],
        [C("近30日首板涨停(次日卖)"), C("268 / 34.0%"), C("0.01x / 0.18x"), C("去5仅0.00x 彻底亏损")],
        [C("近30日破位反抽(两日卖)"), C("197 / 50.8%"), C("1.88x / 1.10x"), C("去5仅0.57x 等权0.45x")],
        [C("近60日破位反抽(三日卖)"), C("216 / 44.0%"), C("2.17x / 2.24x"), C("去5仅0.41x 限2亿0.80x")],
        [C("近30日横盘突破(次日卖)"), C("247 / 34.4%"), C("0.05x / 0.26x"), C("去5仅0.02x 追高被砸")],
        [C("前视打分最佳(30日分歧)"), C("34 / 52.9%"), C("样本外 1.75x"), C("去5仅0.61x 年化夏普0.62")],
        [C("前视打分反抽70分档"), C("16 / 68.8%"), C("样本外 1.71x"), C("去5 1.05x 撞毁主力 -30%")],
    ]

    t2 = [
        [C("北交所30cm玩法切片", True), C("924后笔数/胜率", True), C("924后净值/去前5", True), C("全期与红队终裁", True)],
        [C("30cm涨停全池(次日卖)"), C("171 / 41.5%"), C("0.04x / 0.01x"), C("九成日期稳定失血")],
        [C("30cm涨停超1亿(两日卖)"), C("123 / 48.0%"), C("1.81x / 0.12x"), C("千八降至0.98x 去5归零")],
        [C("大阳15%全池(三日卖)"), C("115 / 43.5%"), C("9.44x / 0.54x"), C("全靠十月狂潮极值")],
        [C("大涨>=15%(5000万三日)"), C("118 / 43.2%"), C("9.74x / 0.40x"), C("等权归零 限1亿暴跌")],
        [C("前视打分最佳(大阳5000万)"), C("95 / 44.5%"), C("0.83x / 0.22x"), C("924后实战亏损 撞毁主力")],
        [C("924后单独训练最佳(三日)"), C("25 / 48.0%"), C("1.51x / 0.47x"), C("去5腰斩 置换概率0.11")],
        [C("主线一字与退潮外溢接力"), C("105 / 35.5%"), C("1.93x / 0.16x"), C("今年实收 -35.8%")],
    ]

    sections_tables = [
        ("表一：近端次新三大玩法盲测与前视打分终局（双边扣千分之三）", t1, c1_path),
        ("表二：北交所30cm情绪套利分期拆解与前视终审（双边扣千分之三）", t2, c2_path),
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
                assert len(ct) <= 32, f"单元格超32字: {ct}"
                texts.append((f"{ttl}[{r_i},{c_i}]", ct))
    for c_i, ht in enumerate(HUB_ROW):
        assert len(ht) <= 32, f"Hub格超32字: {ht}"
        texts.append((f"hub_{c_i}", ht))
    for loc, txt in texts:
        s9.check_text_punc_and_vars(txt, loc)
        for bw in s6.BANNED_WORDS + s6.EXTRA_BANNED_WORDS:
            if bw in txt:
                raise ValueError(f"[{loc}] 命中禁用词 '{bw}': {txt}")
        if s6.HUMAN_PROSE_BAD_RE.search(txt):
            raise ValueError(f"[{loc}] 命中 HUMAN_PROSE_BAD_RE: {txt}")
    print("[DryRun PASS] RD042 payload 100% validated!")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    c1 = f"{OUT_DIR}/rd042_chart1_subnew_falsified.png"
    c2 = f"{OUT_DIR}/rd042_chart2_bse30cm_falsified.png"
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

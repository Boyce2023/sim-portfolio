#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD045 Step 5: Validate & Publish Pure Plain-Chinese Feishu Report (`卡异动与北交二期精选`)."""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"
import argparse, fcntl, json, re, sys, time, warnings
warnings.filterwarnings("ignore")
assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
RD045_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd045_abn_v2_bse_v2_refinement_20261126"
RD041_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd041_day0_firstboard_sweep_20261126"
FS_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/feishu_master_docs_20261116"
for p in (RD045_DIR, RD041_DIR, FS_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import _rd041_feishu_helpers as fh
import step6_upgrade_3strategies_20261117 as s6
import step9_sync_v191_exits_20261118 as s9

TITLE = "卡异动与北交二期精选"
HUB_ROW = [
    "卡异动与北交二期精选",
    "215组精测+题材对照",
    "题材升温拉正方向但去极值破1倍，北交砍10月全亏",
    "两赛道仍禁实盘，仅题材升温作观察",
]

C, T, B, BL, MIXED = fh.C, fh.T, fh.B, fh.BL, fh.MIXED


def build_payload(c1_path: str, c2_path: str) -> dict:
    blocks = [
        MIXED([
            ("结论：卡异动与北交二期精选全部没用，双赛道共215组均未通过红队终审。", True, True),
            ("题材升温延续虽能显著拉正卡异动方向，但去极值跌破1倍且撞毁现役主力。", False, False),
            ("北交所砍掉2024年10月狂潮后全线亏损，严禁挪用实盘资金去碰。", False, False),
        ]),
        BL(),
        T("一、卡异动二期核心验证：题材升温延续确有强正向分化", bold=True),
        B("精准还原交易所十日偏离上限后，五年扫出三类五百六十八笔精选信号。", False),
        B("在守住五日线与低平开的三亿大票中，题材对照呈现出极强单调分化。", False, True),
        B("二波题材分高于一波的升温组，次日卖五年净值达2.31x且胜率61.9%。", False, True),
        B("该组在2023年熊市照样盈利至1.21x，涨停持有至断板更达7.17x。", False),
        B("相反题材退潮组五年净值仅0.66x，无主线助攻的独苗庄股更跌至0.57x。", False),
        B("若题材升温但跌破五日线，次日卖直接崩至0.28x，证明双条件缺一不可。", False, True),
        BL(),
        T("二、卡异动二期为何仍未过红队终审", bold=True),
        B("精确计算触线空间并加上五日线卡控后，题材升温组依然栽在四道硬关。", False),
        B("首要问题是极值过度集中，去掉前五笔暴涨单后五年净值全线跌破1倍。", False, True),
        B("精准卡在题材分刚好打平时去极值见1.23x，但门槛降0.02立刻腰斩。", False),
        B("只做解禁日早盘先手或前一日尾盘贴线潜伏，样本极少且去极值均亏损。", False),
        B("优质池内跑逐日前视打分前二成仅剩0.55x，强行接入现役撞毁总仓。", False, True),
        BL(),
        T("三、北交所30cm二期：砍掉十月狂潮后全面露馅", bold=True),
        B("严砍九二四之前死水期后，再硬切2024年10月史诗脉冲测常态两年表现。", False),
        B("主板压制叠加大阳突破表面见3.14x，砍掉十月狂潮即缩水至1.18x。", False, True),
        B("将常态期再去掉前五笔暴利极值，所有跷跷板方案全线跌破0.79x保本线。", False),
        B("改用五日线或十日线趋势波段不早卖，分歧低吸与回踩净值反跌至0.48x。", False),
        B("五因子低自由度轮动与逆势反抽全败，北交所成交中位已从1.07亿跌至0.13亿。", False, True),
        B("结论明确：继续严禁实盘碰卡异动二波与北交所，仅留题材延续逻辑作研究参考。", False),
        BL(),
        BL(),
        BL(),
    ]

    t1 = [
        [C("卡异动二期精选方案", True), C("笔数/胜率", True), C("五年/2023年", True), C("去前五/红队终裁", True)],
        [C("题材升温+守5日线(次日)"), C("42 / 61.9%"), C("2.31x / 1.21x"), C("去5仅0.88x 撞毁主力")],
        [C("题材升温+守5日线(断板)"), C("39 / 53.9%"), C("7.17x / 1.86x"), C("去5仅0.81x 撞掉主力")],
        [C("题材高位延续(次日卖)"), C("91 / 48.4%"), C("0.67x / 1.16x"), C("去5仅0.24x 全面亏损")],
        [C("题材明显退潮(次日卖)"), C("43 / 48.8%"), C("0.66x / 0.63x"), C("去5仅0.26x 熊市失血")],
        [C("无主线独苗庄股(次日)"), C("44 / 47.7%"), C("0.57x / 0.58x"), C("去5仅0.23x 淘汰")],
        [C("题材升温未守5日线(次日)"), C("70 / 54.3%"), C("0.28x / 0.85x"), C("去5仅0.11x 淘汰")],
        [C("精确解禁开盘+升温(2日)"), C("14 / 64.3%"), C("2.07x / 1.11x"), C("去5仅0.69x 样本太少")],
        [C("前一日尾盘贴线94%以上"), C("8 / 62.5%"), C("1.08x / 0.93x"), C("五年仅8笔 去5亏0.79x")],
    ]

    t2 = [
        [C("北交所二期精选方案", True), C("活水全期净值", True), C("砍十月后/去前5", True), C("红队终审", True)],
        [C("跷跷板大阳超1亿(3日卖)"), C("3.14x (24笔)"), C("1.18x / 0.45x"), C("全靠十月狂潮极值")],
        [C("跷跷板大阳超1亿(5日卖)"), C("2.08x (20笔)"), C("1.54x / 0.64x"), C("去5仍亏 并入拖累主力")],
        [C("15%大阳分歧低吸(3日)"), C("1.21x (112笔)"), C("0.48x / 0.06x"), C("常态期腰斩 淘汰")],
        [C("回踩5日线低吸(3日卖)"), C("0.63x (116笔)"), C("0.39x / 0.09x"), C("破线止仅0.08x 淘汰")],
        [C("五因子前视打分前10%"), C("0.61x (113笔)"), C("0.61x / 0.13x"), C("前视打分全线亏损")],
        [C("5千万以上全池轮动3天"), C("基准对照"), C("0.50x (全相位)"), C("流动性退潮即接盘")],
        [C("1亿以上全池轮动3天"), C("基准对照"), C("0.34x (全相位)"), C("大额冲顶后连续失血")],
    ]

    sections_tables = [
        ("表一：卡异动二期题材延续四组对照与三大精选架构实测（扣千分之三）", t1, c1_path),
        ("表二：北交所30cm二期砍十月狂潮对照与红队终审（扣千分之三）", t2, c2_path),
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
    print("[DryRun PASS] RD045 Feishu payload 100% validated!")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    c1 = f"{RD045_DIR}/rd045_chart1_abn_v2_theme_and_redteam.png"
    c2 = f"{RD045_DIR}/rd045_chart2_bse_v2_post924_falsified.png"
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
        with open(f"{RD045_DIR}/feishu_publish_result.json", "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
        print(json.dumps(res, ensure_ascii=False, indent=2))
    finally:
        fcntl.flock(lock_f, fcntl.LOCK_UN)
        lock_f.close()


if __name__ == "__main__":
    main()

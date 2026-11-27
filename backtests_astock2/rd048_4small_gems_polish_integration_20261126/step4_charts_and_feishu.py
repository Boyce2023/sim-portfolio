#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD048 Wave 2 Feishu Publisher: Pure Plain-Chinese Valid-Library Archival & Incremental Hub Sync."""
import argparse, fcntl, json, os, re, sys, time

RD048_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_AST2 = os.path.dirname(RD048_DIR)
FS_DIR = f"{BASE_AST2}/feishu_master_docs_20261116"
RD038_DIR = f"{BASE_AST2}/rd038_grand_bundle_assembly_20261126"
for p in (FS_DIR, RD038_DIR, RD048_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import step6_upgrade_3strategies_20261117 as s6
import step9_sync_v191_exits_20261118 as s9
import publish_feishu_rd038 as p38
from rd038_feishu_payload import T, MIXED, B, BL, C, validate_payload_strict
import step4_charts as ch4

TITLE = "四遗珠打磨与期货融入"
HUB_ROW = [
    TITLE,
    "五年两套主力全排列实证",
    "四进五百二十分与独立期货配比真有用，映射与五板淘汰",
    "四进五入影子，救市期货用独立一成半仓五倍止损配主力",
]

def build_payload(c1_path: str, c2_path: str) -> dict:
    blocks = [
        MIXED([
            ("结论：四只遗珠仅四进五高分版与救市期货有用，美股映射和五板对主仓没用。", True, True),
            ("四进五补上减持漏网并卡一百二十分后，可给影子主力带来近八成真实净增值。", False, False),
            ("国家队救市改用中金所五倍期货配独立一成半保证金，能同步把主仓回撤砍低一成多。", False, False),
            ("美股映射因持股占用早盘名额反而砸坏主仓九成九收益，深市五板更是五年近乎归零。", False, False),
        ]),
        BL(),
        T("一、四只遗珠独立打磨体检与红队查漏真相", bold=True),
        B("四进五修正竞争对手分重复加总与错杀普通异动后，一百一十四分档五年达到十八倍。", False, True),
        B("红队复核发现旧过滤正则漏掉十三条减持与风险提示公告，导致宁水集团大亏二十四点六。", False),
        B("补齐严格公告过滤后该档五年反升至二十四点五倍，卡一百二十分也可自然避开大雷。", False, True),
        B("美股映射剥离涨停买不到的未来函数后，五年线策略年化夏普仅零点六一且胜率不到三成七。", False),
        B("深市五板唯一高标高锁仓在去年八月发生体质突变，但此前近三年巨亏绝不能进主仓。", False),
        B("救市改做沪深三百期货收盘高分拿三天加百分之二指数止损，五倍五年达四点八倍。", False, True),
        B("期货杠杆测试证明五倍以内强平率为零，六倍起开始爆仓且七倍强平率高达四分之一。", False),
        BL(),
        T("二、并入两套主力双基准全排列与逐笔撞车核验", bold=True),
        B("四进五漏过滤一百一十四分档挤占了信隆健康六十二个点大肉，反而把影子主力拖成零增量。", False),
        B("改用一百二十分档后在五个梯队顺位完全不变，零挤占亏损单却给影子主力增厚八成一净值。", False, True),
        B("美股映射即便只在空仓日接盘仍会撞掉七十多笔主力买点，单户实盘直接腰斩九成八以上。", False),
        B("就算退一步在事后只挑永不撞车的理论空档插入，依然拉低影子主力夏普并放大最大回撤。", False),
        B("深市五板并入主仓会吞掉九成七复利收益，超跌狙击档也已被影子主力全额吸收。", False),
        BL(),
        T("三、期货两种融入架构对决与极简实战裁决", bold=True),
        B("单户切仓期货叠银期次日到账时滞仅成交四五笔，撞掉主力后五年反亏四个点。", False),
        B("独立一成半保证金账户配五倍止损期货完全不撞早盘买点，十六次救市大跌窗口共亏为零天。", False, True),
        B("前年二月六日与九月大跌当天五倍期货暴涨两成以上，把主力合并单日跌幅直接砍半。", False),
        B("定比再平衡比现金多赚两成八且夏普升至五点一七，但空仓配现拖累总绝对倍。", False, True),
        B("结论建议四进五百二十分入影子，五倍期货作独立卫星，映射淘汰五板旁观。", False, True),
        BL(), BL(), BL(),
    ]
    t1 = [
        [C("遗珠策略与版本", True), C("五年净值与去前五", True), C("夏普与最大回撤", True), C("独立红队查漏裁定", True)],
        [C("四进五高分百二分版"), C("9.33倍，去五1.47倍"), C("夏普1.78，撤19.4%"), C("过关，连亏四笔停手")],
        [C("四进五严格减持版"), C("24.49倍，去五3.78倍"), C("胜率66.7%，三年12.6倍"), C("补漏13条公告更强")],
        [C("美股映射因果五日线"), C("2.71倍，去五0.49倍"), C("夏普0.61，撤67.0%"), C("淘汰，前5%随机亏")],
        [C("深市五板独苗高锁仓"), C("0.21倍，去五0.04倍"), C("前年八月后年胜率69%"), C("禁入主仓，连亏四停")],
        [C("救市三倍止损期货"), C("2.69倍，去五1.19倍"), C("夏普1.29，强平0%"), C("稳健卫星，连亏四停")],
        [C("救市五倍止损期货"), C("4.78倍，去五1.32倍"), C("夏普1.28，强平0%"), C("进取上限，六倍起爆仓")],
    ]
    t2 = [
        [C("影子21版融合方案", True), C("五年相对与样本外倍", True), C("夏普与最大回撤", True), C("真实撞车与最终落地", True)],
        [C("单加四进五百二分"), C("1.81倍，外1.91倍"), C("夏普5.24，撤47.6%"), C("零撞负单，荐入影子")],
        [C("单加四进五严格114"), C("2.06倍，外2.40倍"), C("夏普5.24，外5.42"), C("去最强单仍增四成四")],
        [C("单加四进五漏过滤114"), C("1.00倍，空仓0.67倍"), C("夏普降至4.99"), C("漏宁水挤掉信隆淘汰")],
        [C("单户加美股映射实盘"), C("0.01倍，挤掉73笔"), C("夏普跌至4.10"), C("彻底证伪淘汰")],
        [C("单户空仓切换五倍期"), C("0.90倍，跨日0.98倍"), C("夏普5.06，撞2至3笔"), C("银期时滞反亏淘汰")],
        [C("独立15%五倍期货池"), C("胜现金1.28倍，外1.23"), C("夏普5.17，撤41.9%"), C("共亏零天，独立卫星")],
        [C("四进五合体加15%五倍"), C("相对全基线胜现金"), C("夏普5.31，外5.47"), C("回撤减5.6个点最优")],
    ]
    sections_tables = [
        ("表一：四大遗珠独立打磨前后表现与红队查漏定性", t1, c1_path),
        ("表二：并入影子主力双基准全排列增量与逐笔撞车核验", t2, c2_path),
    ]
    return {"title": TITLE, "blocks": blocks, "tables": [(ttl, rows) for ttl, rows, _ in sections_tables], "sections_tables": sections_tables, "img_path": c1_path, "img_path2": c2_path}

def validate_strict(payload: dict):
    validate_payload_strict(payload, s6, s9)
    for loc, txt in [("title", payload["title"])] + [(f"hub_{i}", v) for i, v in enumerate(HUB_ROW)]:
        s9.check_text_punc_and_vars(txt, loc)
        for bw in s6.BANNED_WORDS + s6.EXTRA_BANNED_WORDS:
            assert bw not in txt, f"{loc} 命中禁用词 {bw}"
    for b in payload["blocks"]:
        txt = "".join(e["text_run"]["content"] for e in b.get("text", {}).get("elements", []))
        for s in re.split(r"[。；]", txt):
            if s.strip():
                assert 15 <= len(s.strip()) <= 40, f"句长越界({len(s.strip())}): {s.strip()}"
                assert "-" not in s, f"含连字符: {s}"
    for ttl, rows in payload["tables"]:
        assert "-" not in ttl and len(rows[0]) <= 4
        for rw in rows:
            for cell in rw:
                ct = "".join(t for t, _ in cell)
                assert "-" not in ct and len(ct) <= 32, f"表超长或含连字符({len(ct)}): {ct}"
    print("[DryRun PASS] RD048 Feishu payload 100% validated!")

def update_hub_dynamic(new_row: list[str]) -> dict:
    res = s6.api(f"{s6.BASE}/open-apis/docx/v1/documents/{p38.HUB_VALID_DOC}/blocks?page_size=500", method="GET")
    items = res["data"]["items"]
    by_id = {b["block_id"]: b for b in items}
    tb, rows_txt, cell_ids = p38._extract_hub_table(items)
    before_titles = [r[0] for r in rows_txt[1:]]
    t_idx = next((i for i in range(1, len(rows_txt)) if rows_txt[i][0] == new_row[0]), None)
    if t_idx is None:
        r_ins = s6.api(f"{s6.BASE}/open-apis/docx/v1/documents/{p38.HUB_VALID_DOC}/blocks/{tb['block_id']}", {"insert_table_row": {"row_index": -1}}, "PATCH")
        assert r_ins.get("code") == 0, f"Hub ins fail: {r_ins}"
        time.sleep(0.4)
        items = s6.api(f"{s6.BASE}/open-apis/docx/v1/documents/{p38.HUB_VALID_DOC}/blocks?page_size=500", method="GET")["data"]["items"]
        by_id = {b["block_id"]: b for b in items}
        tb, rows_txt, cell_ids = p38._extract_hub_table(items)
        t_idx = len(rows_txt) - 1
    for c_i, val in enumerate(new_row):
        p38._write_cell_text(s6, p38.HUB_VALID_DOC, by_id, cell_ids[t_idx][c_i], val)
        time.sleep(0.15)
    items_fin = s6.api(f"{s6.BASE}/open-apis/docx/v1/documents/{p38.HUB_VALID_DOC}/blocks?page_size=500", method="GET")["data"]["items"]
    _, rows_fin, _ = p38._extract_hub_table(items_fin)
    n_entries = len(rows_fin) - 1
    for b in items_fin:
        if b.get("block_type") == 2 and b.get("parent_id") == p38.HUB_VALID_DOC:
            txt = "".join(e.get("text_run", {}).get("content", "") for e in b.get("text", {}).get("elements", []))
            if "有效回测与可用规律全量索引表" in txt:
                nh = f"有效回测与可用规律全量索引表（共 {n_entries} 项）"
                if txt.strip() != nh:
                    s6.api(f"{s6.BASE}/open-apis/docx/v1/documents/{p38.HUB_VALID_DOC}/blocks/{b['block_id']}", {"update_text_elements": {"elements": [{"text_run": {"content": nh, "text_element_style": {"bold": True}}}]}}, "PATCH")
                break
    fin_titles = [r[0] for r in rows_fin[1:]]
    assert all(t in fin_titles for t in before_titles) and new_row[0] in fin_titles
    return {"hub_doc_id": p38.HUB_VALID_DOC, "total_rows": n_entries, "rd048_row": rows_fin[t_idx]}

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--dry-run", action="store_true"); args = ap.parse_args()
    c1, c2 = ch4.build_charts()
    payload = build_payload(c1, c2)
    validate_strict(payload)
    if args.dry_run:
        return
    with open(s6.LOCK_PATH, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            doc_id, node_tok = s9.find_or_create_child_node(p38.PARENT_VALID_NODE, payload["title"])
            assert doc_id not in s6.PROTECTED_DOCS
            done, fail = p38._write_doc_with_interleaved_charts(s6, doc_id, payload)
            assert fail == 0, f"Write fail: {fail}"
            time.sleep(0.8)
            v = s9.verify_document_v191(doc_id, payload["title"], expected_tables_count=len(payload["tables"]), has_img=True)
            assert v["images_count"] >= 2, f"Missing charts: {v}"
            hub_res = update_hub_dynamic(HUB_ROW)
            res = {"title": payload["title"], "doc_id": doc_id, "node_token": node_tok, "wiki_url": f"https://my.feishu.cn/wiki/{node_tok}", "parent_node_token": p38.PARENT_VALID_NODE, "verify": v, "hub_update": hub_res, "charts": [c1, c2]}
            with open(f"{RD048_DIR}/feishu_publish_result.json", "w", encoding="utf-8") as f:
                json.dump(res, f, ensure_ascii=False, indent=2)
            print(json.dumps(res, ensure_ascii=False, indent=2))
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)

if __name__ == "__main__":
    main()

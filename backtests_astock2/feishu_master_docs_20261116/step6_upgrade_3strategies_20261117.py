#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""步骤六：将飞书知识库《一进二》《三进四》《二进三》三篇主文档升级至 V19 / V4.0 / V2.0 生产定版"""
import os
import sys
import re
import json
import time
import fcntl
import argparse
import subprocess

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CUR_DIR)

FEISHU_TOOLS_PATH = "/Users/huaichuaibeimeng/claude-projects/股票研究 Equity Research/_tools/html2feishu.py"
exec(open(FEISHU_TOOLS_PATH, "r", encoding="utf-8").read(), globals())

from build_master_docs import BANNED_PUNC, BANNED_WORDS
from gen_1to2_v19 import build_1to2_v19_blocks
from gen_3to4_v40 import build_3to4_v40_blocks
from gen_2to3_v20 import build_2to3_v20_blocks

BASE = "https://open.feishu.cn"
SPACE_ID = "7700231295393107208"
MANIFEST_PATH = f"{CUR_DIR}/feishu_master_manifest.json"
LOCK_PATH = "/tmp/.feishu_wiki_pub_global.lock"

PROTECTED_DOCS = {
    "HexPdpU4uowtfZx1IIscgIKrnce", "WGtbd6n5Po4llQxEKoVceMsWndb", "FusBd37rhot4vbxw2HZcrs1hnjx",
    "IPDcdObeqoY7ypxIT9Vc8Bmnn0d", "PJ2Edkp8poveKlxbVOpcH0A1nke", "LK5Cdjahbogn1bxkXwacBkStnkg",
    "Vnlwdeupzo7KUOxfQPOcuKfHnag", "OJMgdavSnoZdwkxhSoicT04Xn2g", "SalkdaqlJo9vixxAvUGcTaZfnCe",
    "OrnZdI6KPoIIdtxCj8NccOlhnEV", "UL6Qd9qV8olJjixmS1ecHhR9nXg", "WkmQdSoSRoiv6TxdBPcciNTdnRG",
    "R0NFdoCKLodgslxGGECctMTdnDe", "GAHUdK37focrPHxD8pXcUZnxnyb", "E9xtd6bkuoyZabxqTaOcyzsFnJR",
    "GrPvddjcqoDeM5xzWeDcdGDcnUf", "F23Odptc5oJD0nxer2pcDMhqnrh", "LoTYdHbgyoRkfexT788cKFVUn9c",
    "OPfAdR96jobIR4xQsgHcB7emn8g", "O9cEdZjazo8digxQBDLchguQn8f", "Uca7dbOZEorBvlxSVZqcoOhLnWf",
    "XXScdrVmToxmy2xCEuxc8FgUnDg", "RTiqd555Soj78vx3GOdcqEO9nze", "AzTtdMOUmoaaM1xuQNocOk7ZnFh",
    "PmkidTDrUovoNwxto4dcOCEznof", "OHZddqHc8oFftfxKipYcYSienng", "SKdrd9v8joVvHQxRwQucwcfUneh",
    "ESy0dajsjotlVcxWJU4cxcwcnxh", "DL6ndA93eoqDADxXsFYcKfDanEf",
}

EXTRA_BANNED_PUNC = list(set(BANNED_PUNC + ["~"]))
EXTRA_BANNED_WORDS = list(
    set(
        BANNED_WORDS
        + [
            "pos20_d0", "xq_cnt_2d", "xq_pre_d2", "fb_dom295", "s_prior", "s_quant",
            "rk_theme", "true_buy_rk", "touch65", "cut_weak", "pm1345", "sealed_3b",
            "sealed_2b", "plate_sz", "weakcut0", "domCond", "M1_day3", "零未来函数",
            "w2_reb", "U01", "U02", "T10", "T14", "T20", "E08", "E12", "E13",
            "P1_1", "P4_4", "交叉核对后", "核对结果", "本次", "这次", "新发现",
            "迁自", "搬来", "原样保留", "脚本", "重跑", "重建时", "收尾",
            "审计发现", "漏剔", "待改", "待核", "改前", "交付门", "重算", "研究线",
            "本项目复核", "脚本名",
        ]
    )
)
TRAD_CHARS = set("體門檻實盤證偽邏輯順優擴虧損筆數據檢驗過濾開漲買賣勝級線點倉單銀頭嚴條發這個對時間長")
EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")


def clear_doc_all(doc_id: str):
    if doc_id in PROTECTED_DOCS:
        raise RuntimeError(f"FATAL CRITICAL SAFETY BLOCK: ATTEMPTED TO CLEAR PROTECTED DOC {doc_id}!")
    print(f"  [*] 清空文档块: {doc_id} ...")
    for _ in range(40):
        r = api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children?page_size=500", method="GET")
        if r.get("code") != 0:
            break
        items = r["data"].get("items") or []
        if len(items) == 0:
            print("  [+] 清空完成: 0 块剩余")
            return True
        api(
            f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children/batch_delete",
            {"start_index": 0, "end_index": min(len(items), 150)},
            "DELETE",
        )
        time.sleep(0.3)
    return False


def insert_image_block(doc_id: str, png_path: str) -> bool:
    if not os.path.exists(png_path):
        print(f"  [!] 图片文件不存在: {png_path}")
        return False
    r1 = api(
        f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children",
        {"children": [{"block_type": 27, "image": {}}], "index": -1},
        "POST",
    )
    if r1.get("code") != 0:
        print("  [!] 创建 image block 失败:", r1)
        return False
    blk_id = r1["data"]["children"][0]["block_id"]
    time.sleep(0.2)
    tok_s = _shared_tok()
    out = subprocess.check_output(
        [
            "curl", "-sS", "-X", "POST", f"{BASE}/open-apis/drive/v1/medias/upload_all",
            "-H", f"Authorization: Bearer {tok_s}",
            "-F", f"file_name={os.path.basename(png_path)}",
            "-F", "parent_type=docx_image",
            "-F", f"parent_node={blk_id}",
            "-F", f"size={os.path.getsize(png_path)}",
            "-F", f"file=@{png_path};type=image/png",
        ],
        timeout=120,
    ).decode("utf-8")
    r2 = json.loads(out)
    if r2.get("code") != 0:
        print("  [!] 上传 image media 失败:", r2)
        return False
    time.sleep(0.2)
    r3 = api(
        f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{blk_id}",
        {"replace_image": {"token": r2["data"]["file_token"]}},
        "PATCH",
    )
    if r3.get("code") != 0:
        print("  [!] replace_image 失败:", r3)
        return False
    print(f"  [+] 成功插入图片: {os.path.basename(png_path)}")
    return True


def write_document_payload(doc_id: str, blocks: list, tables: list, img_path: str = None):
    if doc_id in PROTECTED_DOCS:
        raise RuntimeError(f"FATAL CRITICAL SAFETY BLOCK: WRITE ATTEMPT ON {doc_id}!")
    clear_doc_all(doc_id)

    done, fail = 0, 0
    for i in range(0, len(blocks), 40):
        ch = blocks[i : i + 40]
        r = api(
            f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children",
            {"children": ch, "index": -1},
            "POST",
        )
        if r.get("code") == 0:
            done += len(ch)
        else:
            for b in ch:
                r2 = api(
                    f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children",
                    {"children": [b], "index": -1},
                    "POST",
                )
                if r2.get("code") == 0:
                    done += 1
                else:
                    fail += 1
                    print("  [!] 写入单块失败:", r2)
        time.sleep(0.25)

    first_appendix = True
    for t_title, t_rows in tables:
        t_title_block = {
            "block_type": 2,
            "text": {
                "elements": [{"text_run": {"content": t_title, "text_element_style": {}}}],
                "style": {"align": 1, "folded": False},
            },
        }
        r_t = api(
            f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children",
            {"children": [t_title_block], "index": -1},
            "POST",
        )
        if r_t.get("code") == 0:
            done += 1
        else:
            fail += 1
            print("  [!] 表格标题写入失败:", r_t)
        time.sleep(0.25)

        if first_appendix and img_path and os.path.exists(img_path):
            if insert_image_block(doc_id, img_path):
                done += 1
            else:
                fail += 1
            first_appendix = False

        d = Desc()
        root = d.add({"t": "table", "rows": t_rows})
        rt = api(
            f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/descendant",
            {"children_id": [root], "descendants": d.d},
        )
        if rt.get("code") == 0:
            done += 1
        else:
            fail += 1
            print("  [!] 表格写入失败:", rt)
        time.sleep(0.35)

    return done, fail


def verify_document(doc_id: str, doc_name: str, expected_tables_count: int, has_img: bool = True):
    print(f"\n[*] 开始核验飞书文档: [{doc_name}] ({doc_id}) ...")
    r_blk = api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children?page_size=500", method="GET")
    if r_blk.get("code") != 0:
        raise RuntimeError(f"[{doc_name}] 获取 blocks 失败: {r_blk}")
    items = r_blk["data"].get("items") or []

    heading_blocks = [b for b in items if b.get("block_type") in range(3, 12)]
    callout_blocks = [b for b in items if b.get("block_type") == 19]
    if heading_blocks:
        raise ValueError(f"[{doc_name}] 违规发现 Heading 块数量: {len(heading_blocks)}")
    if callout_blocks:
        raise ValueError(f"[{doc_name}] 违规发现 Callout 灰框块数量: {len(callout_blocks)}")

    for i, b in enumerate(items[:6]):
        bt = b.get("block_type")
        if bt in (27, 31):
            raise ValueError(f"[{doc_name}] 前 6 块中违规出现表格或图片 (第 {i+1} 块: block_type={bt})")

    empty_indices = []
    for i, b in enumerate(items):
        if b.get("block_type") == 2:
            txt_el = b.get("text", {}).get("elements", [])
            txt = "".join(e.get("text_run", {}).get("content", "") for e in txt_el).strip()
            if txt == "":
                empty_indices.append(i)

    has_3_empty = False
    for i in range(len(empty_indices) - 2):
        if empty_indices[i + 1] == empty_indices[i] + 1 and empty_indices[i + 2] == empty_indices[i] + 2:
            has_3_empty = True
            break
    if not has_3_empty:
        raise ValueError(f"[{doc_name}] 未检测到连续 3 个空文本块 (empty_indices={empty_indices})")

    table_blocks = [b for b in items if b.get("block_type") == 31]
    image_blocks = [b for b in items if b.get("block_type") == 27]
    if len(table_blocks) < expected_tables_count:
        raise ValueError(f"[{doc_name}] 表格数量不符: 实际 {len(table_blocks)} < 预期 {expected_tables_count}")
    if has_img and len(image_blocks) < 1:
        raise ValueError(f"[{doc_name}] 缺失净值图片: 实际 {len(image_blocks)} < 1")

    r_raw = api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/raw_content", method="GET")
    raw_content = r_raw.get("data", {}).get("content", "")
    if len(raw_content) < 600:
        raise ValueError(f"[{doc_name}] 文档回读内容过短: {len(raw_content)} 字符")

    for p in EXTRA_BANNED_PUNC:
        if p in raw_content:
            raise ValueError(f"[{doc_name}] 回读检测到违规标点 '{p}'")
    for w in EXTRA_BANNED_WORDS:
        if w in raw_content:
            raise ValueError(f"[{doc_name}] 回读检测到违规黑话/变量 '{w}'")
    found_trad = [ch for ch in raw_content if ch in TRAD_CHARS]
    if found_trad:
        raise ValueError(f"[{doc_name}] 回读检测到繁体字 {found_trad}")
    if EMOJI_RE.search(raw_content):
        raise ValueError(f"[{doc_name}] 回读检测到 Emoji")

    print(
        f"  [+] [{doc_name}] 核验完美通过: 总块数={len(items)}, 表格数={len(table_blocks)}, "
        f"图片数={len(image_blocks)}, 回读字符={len(raw_content)}"
    )
    return {
        "doc_name": doc_name,
        "doc_id": doc_id,
        "blocks_count": len(items),
        "tables_count": len(table_blocks),
        "images_count": len(image_blocks),
        "raw_chars": len(raw_content),
    }


def audit_doc_strict(data: dict, require_img: bool = True):
    name = data["title"]
    blocks = data["blocks"]
    tables = data["tables"]
    img_path = data.get("img_path")

    if data.get("doc_id") in PROTECTED_DOCS:
        raise RuntimeError(f"[{name}] 命中受保护文档 {data['doc_id']}")
    if require_img and (not img_path or not os.path.exists(img_path)):
        raise FileNotFoundError(f"[{name}] 缺失净值图: {img_path}")

    blank_streak = max_streak = 0
    for b in blocks:
        if b["block_type"] == 2:
            txt = "".join(e["text_run"]["content"] for e in b["text"]["elements"]).strip()
            blank_streak = blank_streak + 1 if txt == "" else 0
            max_streak = max(max_streak, blank_streak)
        else:
            blank_streak = 0
    if max_streak < 3:
        raise ValueError(f"[{name}] 缺少末尾连续3个空行")

    has_yellow = False
    long_sentences = []
    all_lens = []
    for idx, b in enumerate(blocks):
        bt = b["block_type"]
        if bt in range(3, 12) or bt == 19:
            raise ValueError(f"[{name}] 发现禁止的 Heading 或 Callout 块: type={bt}")
        if bt == 2:
            els = b["text"]["elements"]
        elif bt == 12:
            els = b["bullet"]["elements"]
        elif bt == 13:
            els = b["ordered"]["elements"]
        else:
            continue

        full_txt = ""
        for e in els:
            tr = e["text_run"]
            c = tr["content"]
            if tr.get("text_element_style", {}).get("background_color") == 3:
                has_yellow = True
            full_txt += c
            for p in EXTRA_BANNED_PUNC:
                if p in c:
                    raise ValueError(f"[{name}] 块{idx} 违规标点 '{p}': {c}")
            for w in EXTRA_BANNED_WORDS:
                if w in c:
                    raise ValueError(f"[{name}] 块{idx} 违规词 '{w}': {c}")
            found_trad = [ch for ch in c if ch in TRAD_CHARS]
            if found_trad:
                raise ValueError(f"[{name}] 块{idx} 违规繁体字 {found_trad}: {c}")
            if EMOJI_RE.search(c):
                raise ValueError(f"[{name}] 块{idx} 违规 Emoji: {c}")

        for sent in re.split(r"[。；]", full_txt):
            s = sent.strip()
            if not s:
                continue
            all_lens.append(len(s))
            if len(s) > 40:
                long_sentences.append((idx + 1, len(s), s))

    if not has_yellow:
        raise ValueError(f"[{name}] 缺少黄色底高亮 (background_color=3)")

    for t_title, t_rows in tables:
        for p in EXTRA_BANNED_PUNC:
            if p in t_title:
                raise ValueError(f"[{name}] 表标题违规标点 '{p}': {t_title}")
        for w in EXTRA_BANNED_WORDS:
            if w in t_title:
                raise ValueError(f"[{name}] 表标题违规词 '{w}': {t_title}")
        max_cols = max(len(r) for r in t_rows)
        if max_cols >= 5:
            raise ValueError(f"[{name}] 表格列数必须严格 < 5 列: {t_title} 实际 {max_cols} 列")
        for r_i, row in enumerate(t_rows):
            for c_i, cell in enumerate(row):
                cell_txt = "".join(txt for txt, _ in cell)
                for p in EXTRA_BANNED_PUNC:
                    if p in cell_txt:
                        raise ValueError(f"[{name}] {t_title} R{r_i}C{c_i} 违规标点 '{p}': {cell_txt}")
                for w in EXTRA_BANNED_WORDS:
                    if w in cell_txt:
                        raise ValueError(f"[{name}] {t_title} R{r_i}C{c_i} 违规词 '{w}': {cell_txt}")
                found_trad = [ch for ch in cell_txt if ch in TRAD_CHARS]
                if found_trad:
                    raise ValueError(f"[{name}] {t_title} 违规繁体字 {found_trad}: {cell_txt}")
                if EMOJI_RE.search(cell_txt):
                    raise ValueError(f"[{name}] {t_title} 违规 Emoji: {cell_txt}")
                if len(cell_txt) > 32:
                    raise ValueError(f"[{name}] 单元格过长 ({len(cell_txt)}字): {cell_txt}")

    print(
        f"[Audit PASS] 【{name}】正文块={len(blocks)}, 表格={len(tables)} (<=4列), "
        f"句数={len(all_lens)}, 最大句长={max(all_lens)}字, 平均句长={sum(all_lens)/len(all_lens):.1f}字, 超40字句={len(long_sentences)}"
    )
    for b_i, slen, stxt in long_sentences:
        print(f"   [长句 块{b_i} ({slen}字)]: {stxt}")
    return long_sentences


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="仅做本地严格审核，不推送飞书")
    args = parser.parse_args()

    builders = [
        ("一进二", build_1to2_v19_blocks),
        ("三进四", build_3to4_v40_blocks),
        ("二进三", build_2to3_v20_blocks),
    ]

    datasets = []
    for name, fn in builders:
        data = fn()
        longs = audit_doc_strict(data)
        if longs:
            raise ValueError(f"[{name}] 存在超40字长句，请先拆短")
        datasets.append(data)

    if args.dry_run:
        print("\n[Dry-Run PASS] 三篇文档本地严格审核全部零违规。")
        return

    print("\n=== 开始将《一进二》《三进四》《二进三》升级发布至飞书知识库 ===")
    lock_fd = open(LOCK_PATH, "w")
    step6_results = []
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        print("[*] 已获取全局飞书发布文件锁")

        for data in datasets:
            name = data["title"]
            doc_id = data["doc_id"]
            node_token = data["node_token"]

            info = api(f"{BASE}/open-apis/wiki/v2/spaces/{SPACE_ID}/nodes/{node_token}", method="GET")
            node_obj = info.get("data", {}).get("node", {})
            cur_title = node_obj.get("title")
            cur_obj_tok = node_obj.get("obj_token")
            print(f"\n[*] 核对 Wiki 节点: title={cur_title}, obj_token={cur_obj_tok}, target={doc_id}")
            if cur_obj_tok and cur_obj_tok != doc_id:
                raise RuntimeError(f"[{name}] Wiki obj_token 不匹配: {cur_obj_tok} != {doc_id}")

            done, fail = write_document_payload(doc_id, data["blocks"], data["tables"], data["img_path"])
            print(f"[+] 写入完成: 成功 {done} 块, 失败 {fail} 块")
            if fail > 0:
                raise RuntimeError(f"[{name}] 写入存在失败块: {fail}")

            time.sleep(1.5)
            v_res = verify_document(doc_id, name, expected_tables_count=len(data["tables"]), has_img=True)
            v_res["node_token"] = node_token
            v_res["wiki_url"] = f"https://my.feishu.cn/wiki/{node_token}"
            step6_results.append(v_res)

        m = json.load(open(MANIFEST_PATH, "r", encoding="utf-8"))
        now_ts = time.strftime("%Y-%m-%d %H:%M:%S")
        m["last_published_at"] = now_ts
        res_by_name = {r["doc_name"]: r for r in step6_results}
        old_results = m.get("results", [])
        new_results = []
        seen = set()
        for item in old_results:
            dn = item.get("doc_name")
            if dn in res_by_name:
                new_results.append(res_by_name[dn])
                seen.add(dn)
            else:
                new_results.append(item)
        for r in step6_results:
            if r["doc_name"] not in seen:
                new_results.append(r)
        m["results"] = new_results
        m["step6_published_at"] = now_ts
        m["step6_results"] = step6_results
        with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=2)

        print("\n=== 发布与在线回读核验全部通过 ===")
        for r in step6_results:
            print(
                f"• 【{r['doc_name']}】: {r['wiki_url']} | doc_id={r['doc_id']} | "
                f"块数={r['blocks_count']} 表格={r['tables_count']} 图片={r['images_count']} 字符={r['raw_chars']}"
            )
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()
        print("[*] 已释放全局飞书发布文件锁")


if __name__ == "__main__":
    main()

#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
飞书策略主文档全量发布与回读核验主程序
1. 建立/移动知识库节点（小策略归口、四进五与撬板入小策略、二进三建节点与回测副文档迁入）
2. 原地清空重写五大策略主文档 + 小策略导览页 + 二进三证伪主文档
3. 严格像素级六段式 + 空三行 + 附录窄表(<=5列) + 净值曲线图
4. 独立自动化回读核验
"""
import os, sys, re, json, time, fcntl, subprocess

# 载入飞书底层通信与Desc构建
FEISHU_TOOLS_PATH = "/Users/huaichuaibeimeng/claude-projects/股票研究 Equity Research/_tools/html2feishu.py"
exec(open(FEISHU_TOOLS_PATH, "r", encoding="utf-8").read(), globals())

from build_master_docs import BANNED_PUNC, BANNED_WORDS
from gen_1to2 import build_1to2_blocks
from gen_high import build_high_blocks
from gen_3to4 import build_3to4_blocks
from gen_4to5 import build_4to5_blocks
from gen_pry import build_pry_blocks
from gen_small_hub import build_small_hub_blocks
from gen_2to3 import build_2to3_blocks

BASE = "https://open.feishu.cn"
SPACE_ID = "7700231295393107208"  # A股策略与回测
CUR_DIR = os.path.dirname(os.path.abspath(__file__))
MANIFEST_PATH = f"{CUR_DIR}/feishu_master_manifest.json"
LOCK_PATH = "/tmp/.feishu_wiki_pub_global.lock"

# 硬保护文档与节点（碰触立即抛出致命异常）
PROTECTED_DOCS = {
    "HexPdpU4uowtfZx1IIscgIKrnce",  # Buwen 亲笔《五板策略》
    "WGtbd6n5Po4llQxEKoVceMsWndb",  # 《26Q4专供》
    "FusBd37rhot4vbxw2HZcrs1hnjx",  # 雪球大V胜率
    "IPDcdObeqoY7ypxIT9Vc8Bmnn0d",  # 跨年妖回测
    "PJ2Edkp8poveKlxbVOpcH0A1nke",  # 3进4自动化因子全集
    "LK5Cdjahbogn1bxkXwacBkStnkg",  # 连板晋级率持续性
    "Vnlwdeupzo7KUOxfQPOcuKfHnag",  # 五板高标真实流盘
    "OJMgdavSnoZdwkxhSoicT04Xn2g",  # 同高度连板PK
    "SalkdaqlJo9vixxAvUGcTaZfnCe",  # 新概念词板块启动率
    "OrnZdI6KPoIIdtxCj8NccOlhnEV",  # 题材雷达
    "UL6Qd9qV8olJjixmS1ecHhR9nXg",  # 首板与高标市值悖论
    "WkmQdSoSRoiv6TxdBPcciNTdnRG",  # 庄股可预测性证伪
    "R0NFdoCKLodgslxGGECctMTdnDe",  # 首板与20cm脉冲
    "GAHUdK37focrPHxD8pXcUZnxnyb",  # 连板断层市场含义
    "E9xtd6bkuoyZabxqTaOcyzsFnJR",  # 超级高标二波
    "GrPvddjcqoDeM5xzWeDcdGDcnUf",  # 超级高标二波备用
    "F23Odptc5oJD0nxer2pcDMhqnrh",  # 20261110超级高标二波
    "LoTYdHbgyoRkfexT788cKFVUn9c",  # 二进三全量因子证伪回测正文（仅移动节点，不修改内容！）
    "OPfAdR96jobIR4xQsgHcB7emn8g",  # 撬板早期探索草稿
    "O9cEdZjazo8digxQBDLchguQn8f",  # 撬板3088切片深研正文
    "Uca7dbOZEorBvlxSVZqcoOhLnWf",  # 四进五773切片深研正文
    "XXScdrVmToxmy2xCEuxc8FgUnDg",  # 题材打分排序机制
    "RTiqd555Soj78vx3GOdcqEO9nze",  # 一进二专项小回测全集
    "AzTtdMOUmoaaM1xuQNocOk7ZnFh",  # 一进二早期探索
    "PmkidTDrUovoNwxto4dcOCEznof",  # 高标首阴专项回测
    "OHZddqHc8oFftfxKipYcYSienng",  # 三进四专项小回测全集
    "SKdrd9v8joVvHQxRwQucwcfUneh",  # 简单的讨论
    "ESy0dajsjotlVcxWJU4cxcwcnxh",  # 政策
    "DL6ndA93eoqDADxXsFYcKfDanEf",  # Claude/Argon 因子挖掘、回测
}

def load_manifest():
    if os.path.exists(MANIFEST_PATH):
        return json.load(open(MANIFEST_PATH, "r", encoding="utf-8"))
    return {"space_id": SPACE_ID, "nodes": {}}

def save_manifest(m):
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)

def clear_doc_all(doc_id: str):
    if doc_id in PROTECTED_DOCS:
        raise RuntimeError(f"FATAL CRITICAL SAFETY BLOCK: ATTEMPTED TO CLEAR PROTECTED DOC {doc_id}!")
    print(f"  [*] 清空文档块: {doc_id} ...")
    for _ in range(40):
        r = api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children?page_size=500", method="GET")
        if r.get("code") != 0: break
        items = r["data"].get("items") or []
        if len(items) == 0:
            print("  [+] 清空完成: 0 块剩余")
            return True
        api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children/batch_delete",
            {"start_index": 0, "end_index": min(len(items), 150)}, "DELETE")
        time.sleep(0.3)
    return False

def insert_image_block(doc_id: str, png_path: str) -> bool:
    if not os.path.exists(png_path):
        print(f"  ⚠️ 图片文件不存在: {png_path}")
        return False
    r1 = api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children",
             {"children": [{"block_type": 27, "image": {}}], "index": -1}, "POST")
    if r1.get("code") != 0:
        print("  ⚠️ 创建 image block 失败:", r1)
        return False
    blk_id = r1["data"]["children"][0]["block_id"]
    time.sleep(0.2)
    tok_s = _shared_tok()
    out = subprocess.check_output([
        "curl", "-sS", "-X", "POST", f"{BASE}/open-apis/drive/v1/medias/upload_all",
        "-H", f"Authorization: Bearer {tok_s}", "-F", f"file_name={os.path.basename(png_path)}",
        "-F", "parent_type=docx_image", "-F", f"parent_node={blk_id}", "-F", f"size={os.path.getsize(png_path)}",
        "-F", f"file=@{png_path};type=image/png"
    ], timeout=120).decode("utf-8")
    r2 = json.loads(out)
    if r2.get("code") != 0:
        print("  ⚠️ 上传 image media 失败:", r2)
        return False
    time.sleep(0.2)
    r3 = api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{blk_id}",
             {"replace_image": {"token": r2["data"]["file_token"]}}, "PATCH")
    if r3.get("code") != 0:
        print("  ⚠️ replace_image 失败:", r3)
        return False
    print(f"  [+] 成功插入图片: {os.path.basename(png_path)}")
    return True

def write_document_payload(doc_id: str, blocks: list, tables: list, img_path: str = None):
    if doc_id in PROTECTED_DOCS:
        raise RuntimeError(f"FATAL CRITICAL SAFETY BLOCK: WRITE ATTEMPT ON {doc_id}!")
    clear_doc_all(doc_id)

    # 1. 批量写入正文段落与列表（按40个一批）
    buf, done, fail = [], 0, 0
    def flush():
        nonlocal buf, done, fail
        if not buf: return
        for i in range(0, len(buf), 40):
            ch = buf[i:i+40]
            r = api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children",
                    {"children": ch, "index": -1}, "POST")
            if r.get("code") == 0:
                done += len(ch)
            else:
                for b in ch:
                    r2 = api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children",
                             {"children": [b], "index": -1}, "POST")
                    if r2.get("code") == 0: done += 1
                    else: fail += 1; print("  ⚠️ 写入单块失败:", r2)
            time.sleep(0.25)
        buf = []

    for b in blocks:
        buf.append(b)
    flush()

    # 2. 写入附录表格与图片
    first_appendix = True
    for t_title, t_rows in tables:
        # 表格标题: block_type=2, content="附录：XXX"
        t_title_block = {
            "block_type": 2,
            "text": {
                "elements": [{"text_run": {"content": t_title, "text_element_style": {}}}],
                "style": {"align": 1, "folded": False}
            }
        }
        r_t = api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children",
                  {"children": [t_title_block], "index": -1}, "POST")
        if r_t.get("code") == 0: done += 1
        else: fail += 1; print("  ⚠️ 表格标题写入失败:", r_t)
        time.sleep(0.25)

        # 首个附录插入净值图片
        if first_appendix and img_path and os.path.exists(img_path):
            if insert_image_block(doc_id, img_path):
                done += 1
            else:
                fail += 1
            first_appendix = False

        # 写入表格
        d = Desc()
        root = d.add({"t": "table", "rows": t_rows})
        rt = api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/descendant",
                 {"children_id": [root], "descendants": d.d})
        if rt.get("code") == 0:
            done += 1
        else:
            fail += 1
            print("  ⚠️ 表格写入失败:", rt)
        time.sleep(0.35)

    return done, fail

def verify_document(doc_id: str, doc_name: str, expected_tables_count: int, has_img: bool = False):
    print(f"\n[*] 开始核验飞书文档: [{doc_name}] ({doc_id}) ...")
    r_blk = api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children?page_size=500", method="GET")
    if r_blk.get("code") != 0:
        raise RuntimeError(f"[{doc_name}] 获取 blocks 失败: {r_blk}")
    items = r_blk["data"].get("items") or []

    # 1. 0 个 Heading 块与 0 个 Callout 灰框
    heading_blocks = [b for b in items if b.get("block_type") in range(3, 12)]
    callout_blocks = [b for b in items if b.get("block_type") == 19]
    if heading_blocks:
        raise ValueError(f"[{doc_name}] 违规发现 Heading 块数量: {len(heading_blocks)}")
    if callout_blocks:
        raise ValueError(f"[{doc_name}] 违规发现 Callout 灰框块数量: {len(callout_blocks)}")

    # 2. 正文前 6 个模块严禁放任何表格或图片
    for i, b in enumerate(items[:6]):
        bt = b.get("block_type")
        if bt in (27, 31):  # 27=image, 31=table
            raise ValueError(f"[{doc_name}] 前 6 块中违规出现表格或图片 (第 {i+1} 块: block_type={bt})")

    # 3. 检查连续 3 个空行
    empty_indices = []
    for i, b in enumerate(items):
        if b.get("block_type") == 2:
            txt_el = b.get("text", {}).get("elements", [])
            txt = "".join(e.get("text_run", {}).get("content", "") for e in txt_el).strip()
            if txt == "":
                empty_indices.append(i)

    # 寻找连续 3 个空行
    has_3_empty = False
    for i in range(len(empty_indices) - 2):
        if empty_indices[i+1] == empty_indices[i] + 1 and empty_indices[i+2] == empty_indices[i] + 2:
            has_3_empty = True
            break
    if not has_3_empty:
        raise ValueError(f"[{doc_name}] 未检测到连续 3 个空文本块 (empty_indices={empty_indices})")

    # 4. 统计表格与图片
    table_blocks = [b for b in items if b.get("block_type") == 31]
    image_blocks = [b for b in items if b.get("block_type") == 27]
    if len(table_blocks) < expected_tables_count:
        raise ValueError(f"[{doc_name}] 表格数量不符: 实际 {len(table_blocks)} < 预期 {expected_tables_count}")
    if has_img and len(image_blocks) < 1:
        raise ValueError(f"[{doc_name}] 缺失净值图片: 实际 {len(image_blocks)} < 1")

    # 5. 校验 raw_content 人话门禁与违规标点
    r_raw = api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/raw_content", method="GET")
    raw_content = r_raw.get("data", {}).get("content", "")
    if len(raw_content) < 600:
        raise ValueError(f"[{doc_name}] 文档回读内容过短: {len(raw_content)} 字符")

    for p in BANNED_PUNC:
        if p in raw_content:
            raise ValueError(f"[{doc_name}] 回读检测到违规标点 '{p}'")
    for w in BANNED_WORDS:
        if w in raw_content:
            raise ValueError(f"[{doc_name}] 回读检测到违规黑话/变量 '{w}'")

    print(f"  [+] [{doc_name}] 核验 100% 完美通过: 总块数={len(items)}, 表格数={len(table_blocks)}, 图片数={len(image_blocks)}, 回读字符={len(raw_content)}")
    return {
        "doc_name": doc_name,
        "doc_id": doc_id,
        "blocks_count": len(items),
        "tables_count": len(table_blocks),
        "images_count": len(image_blocks),
        "raw_chars": len(raw_content)
    }

print("publish_and_verify_master_docs library ready.")

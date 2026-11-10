#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026Q3 财报纪要原生飞书直写与审计引擎（零 HTML 中转、进程锁防并发限流、自动列宽、标点强校验）
用法（供各标的子 Agent 调用）：
  from feishu_q3_native_writer import write_q3_report_to_feishu
  audit = write_q3_report_to_feishu(doc_id, payload)
"""
import os, re, json, time, fcntl, subprocess, socket
socket.setdefaulttimeout(40)

exec(open("/Users/huaichuaibeimeng/claude-projects/股票研究 Equity Research/_tools/html2feishu.py", "r", encoding="utf-8").read(), globals())
BASE = "https://open.feishu.cn"
LOCK_FILE = "/tmp/.feishu_q3_upload.lock"

BAD_EMOJIS = ["✅", "⚠️", "⛔", "🔴", "🟢", "🟡", "⭐", "★", "☆", "📌", "💡", "🔥", "🚀", "❌", "📁", "📊", "📈", "📉"]
BANNED_CODES = [r"\bG[1-4]\b", r"\bT[1-4]\b", r"\bD\d{1,2}\b", r"\bF\d{1,2}\b", r"\bO\d{1,2}\b"]

def clean_zh(txt: str, is_english_quote: bool = False) -> str:
    if txt is None:
        return ""
    s = str(txt)
    for em in BAD_EMOJIS:
        s = s.replace(em, "")
    s = re.sub(r"\[(?:事实|推算|未知|估算|事实与推算)\]", "", s)
    if not is_english_quote:
        for pat in BANNED_CODES:
            s = re.sub(pat, "", s)
    s = s.replace("$", "")
    s = s.replace("——", "，").replace("—", "，").replace("–", "至").replace("→", "至")
    s = re.sub(r"(?<![A-Za-z0-9])-(\d+(?:\.\d+)?%?)", r"负\1", s)
    s = re.sub(r"([A-Za-z])-([A-Za-z])", r"\1 \2", s)
    s = re.sub(r"(\d)-(\d)", r"\1至\2", s)
    s = s.replace("-", " ")
    s = s.replace("！", "。").replace("!", "。")
    s = re.sub(r" {2,}", " ", s)
    return s.strip()

def parse_marked_runs(txt: str, is_english_quote: bool = False):
    """支持在文本中用 [[HL]]...[[/HL]] 或 <mark>...</mark> 标注黄底高亮句"""
    raw = str(txt).replace("<mark>", "[[HL]]").replace("</mark>", "[[/HL]]")
    parts = re.split(r"(\[\[HL\]\].*?\[\[/HL\]\])", raw, flags=re.S)
    elems = []
    for p in parts:
        if not p:
            continue
        if p.startswith("[[HL]]") and p.endswith("[[/HL]]"):
            c = clean_zh(p[6:-7], is_english_quote=is_english_quote)
            if c:
                elems.append({"text_run": {"content": c, "text_element_style": {"background_color": 3}}})
        else:
            c = clean_zh(p, is_english_quote=is_english_quote)
            if c:
                elems.append({"text_run": {"content": c, "text_element_style": {}}})
    if not elems:
        elems.append({"text_run": {"content": "", "text_element_style": {}}})
    return elems

def clear_doc_safe(doc_id: str):
    for _ in range(40):
        n, pt = 0, None
        while True:
            u = f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children?page_size=500"
            if pt:
                u += f"&page_token={pt}"
            r = api(u, None, "GET")
            if r.get("code") != 0:
                break
            n += len(r["data"].get("items") or [])
            pt = r["data"].get("page_token")
            if not r["data"].get("has_more"):
                break
        if n == 0:
            return True
        api(
            f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children/batch_delete",
            {"start_index": 0, "end_index": min(n, 150)},
            "DELETE",
        )
        time.sleep(0.28)
    return False

def insert_png_safe(doc_id: str, png_path: str) -> bool:
    if not os.path.exists(png_path):
        print(f"  [IMG MISSING] {png_path}")
        return False
    r1 = api(
        f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children",
        {"children": [{"block_type": 27, "image": {}}], "index": -1},
        "POST",
    )
    if r1.get("code") != 0:
        print(f"  [IMG STEP1 ERR] {r1}")
        return False
    blk_id = r1["data"]["children"][0]["block_id"]
    time.sleep(0.25)
    sz = os.path.getsize(png_path)
    tok = _shared_tok()
    cmd = [
        "curl", "-sS", "--max-time", "55", "-X", "POST",
        f"{BASE}/open-apis/drive/v1/medias/upload_all",
        "-H", f"Authorization: Bearer {tok}",
        "-F", f"file_name={os.path.basename(png_path)}",
        "-F", "parent_type=docx_image",
        "-F", f"parent_node={blk_id}",
        "-F", f"size={sz}",
        "-F", f"file=@{png_path};type=image/png",
    ]
    r2 = {}
    for attempt in range(5):
        try:
            out = subprocess.check_output(cmd, timeout=120).decode("utf-8")
            r2 = json.loads(out)
            if r2.get("code") == 0:
                break
        except Exception as e:
            print(f"  [IMG UPLOAD ATTEMPT {attempt+1} FAILED] {e}")
        time.sleep(1.5 * (attempt + 1))
    if r2.get("code") != 0:
        print(f"  [IMG STEP2 ERR] {r2}")
        return False
    ftok = r2["data"]["file_token"]
    time.sleep(0.25)
    r3 = api(
        f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{blk_id}",
        {"replace_image": {"token": ftok}},
        "PATCH",
    )
    return r3.get("code") == 0

def make_table_item(headers, rows):
    """构造 html2feishu Desc() 兼容的 table 结构，自动享用精确列宽计算"""
    all_rows = []
    hdr_row = [[(clean_zh(h), {"bold": True})] for h in headers]
    all_rows.append(hdr_row)
    for r in rows:
        row_cells = []
        for c in r:
            row_cells.append([(clean_zh(c), {})])
        all_rows.append(row_cells)
    return {"t": "table", "rows": all_rows}

def write_q3_report_to_feishu(doc_id: str, payload: dict) -> dict:
    """
    payload schema:
    {
      "summary_bullets": [
        {"label": "发布时间：", "text": "...", "highlight": False},  # 严格 8 条
        ...
      ],
      "sections": [
        {
          "heading": "一、...",
          "blocks": [
            {"type": "p", "text": "...支持 [[HL]]重点判断句[[/HL]] ..."},
            {"type": "image", "path": "/tmp/q3_xxx/01.png"},
            {"type": "table", "headers": [...], "rows": [[...], ...]},
            {"type": "quote", "speaker": "姓名（职位） | 2026Q3 电话会，日期", "en": "\"English verbatim...\"", "zh": "中文翻译..."}
          ]
        }
      ]
    }
    """
    assert len(payload.get("summary_bullets", [])) == 8, "summary_bullets MUST have exactly 8 items!"

    os.makedirs(os.path.dirname(LOCK_FILE), exist_ok=True)
    with open(LOCK_FILE, "w") as lf:
        # Serialize Feishu write bursts across concurrent subagents to prevent 429 & token races
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        clear_doc_safe(doc_id)

        top_blocks = [
            {"block_type": 4, "heading2": {"elements": [{"text_run": {"content": "财报核心速览"}}]}}
        ]
        for sb in payload["summary_bullets"]:
            lbl = clean_zh(sb["label"])
            if not lbl.endswith("："):
                lbl += "："
            body = clean_zh(sb["text"])
            hl = bool(sb.get("highlight", False))
            top_blocks.append({
                "block_type": 12,
                "bullet": {
                    "elements": [
                        {"text_run": {"content": lbl, "text_element_style": {"bold": True}}},
                        {"text_run": {"content": body, "text_element_style": {"background_color": 3} if hl else {}}},
                    ]
                }
            })
        top_blocks.append({"block_type": 22, "divider": {}})

        fail = 0
        img_ok = 0
        img_total = 0

        r_top = api(
            f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children",
            {"children": top_blocks, "index": -1},
            "POST",
        )
        if r_top.get("code") != 0:
            fail += 1
            print("ERR top_blocks:", r_top)
        time.sleep(0.28)

        buf = []
        def flush_buf():
            nonlocal buf, fail
            if not buf:
                return
            for i in range(0, len(buf), 35):
                r = api(
                    f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children",
                    {"children": buf[i:i+35], "index": -1},
                    "POST",
                )
                if r.get("code") != 0:
                    fail += 1
                    print("ERR buf:", str(r)[:200])
                time.sleep(0.28)
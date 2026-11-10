#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书选股知识库原生上传与「说人话+零违禁标点」硬质检引擎
用法：
  python3 /tmp/us_xuangu_20261109/feishu_human_uploader.py <doc_obj_token> <html_path>
"""
import sys, os, re, json, time, fcntl, subprocess
from bs4 import BeautifulSoup, NavigableString, Doctype, Comment

exec(open("/Users/huaichuaibeimeng/claude-projects/股票研究 Equity Research/_tools/html2feishu.py", "r", encoding="utf-8").read(), globals())
T = _shared_tok()
BASE = "https://open.feishu.cn"
UPLOAD_LOCK = "/tmp/.feishu_xuangu_upload.lock"

BANNED_MACHINE_WORDS = [
    "星辰大海", "皇冠明珠", "飞轮", "底座", "赋能", "闭环", "引擎", "跃迁", "重塑", "颠覆",
    "范式", "生态", "矩阵", "全景", "硬核", "标尺", "试金石", "胜负手", "王牌",
    "钩子", "年金", "天花板", "破局", "抓手", "撬动", "罕见", "极其", "绝不", "完美",
    "铁证", "铁律", "暗礁", "命门", "底牌", "法典", "死限", "拆穿", "十战十胜", "干干净净",
    "圣经", "贵族", "宪法", "D8", "D15", "SSOT", "本模型驾驶舱", "子模型"
]

def sanitize_and_check_human_html(html_path: str):
    with open(html_path, "r", encoding="utf-8") as f:
        raw = f.read()
    soup = BeautifulSoup(raw, "html.parser")
    # Strip any callout classes so zero callout blocks are created
    for tag in soup.find_all(True):
        if tag.get("class"):
            tag["class"] = [c for c in tag["class"] if c not in CALLOUT]
    bad_emojis = ["✅", "⚠️", "⛔", "🔴", "🟢", "🟡", "⭐", "★", "☆", "📌", "💡", "🔥", "🚀", "❌", "📁", "🎯", "📊", "📈"]
    for elem in soup.find_all(string=True):
        if isinstance(elem, (Doctype, Comment)):
            elem.extract()
            continue
        if elem.parent and elem.parent.name in ("style", "script"):
            continue
        txt = str(elem)
        for em in bad_emojis:
            txt = txt.replace(em, "")
        txt = txt.replace("——", "，")
        txt = txt.replace("—", "，")
        txt = txt.replace("–", "至")
        txt = txt.replace("→", "至")
        txt = re.sub(r"(?<![A-Za-z0-9])-(\\d+(?:\\.\\d+)?%?)", r"负\\1", txt)
        txt = re.sub(r"([A-Za-z])-([A-Za-z])", r"\\1 \\2", txt)
        txt = re.sub(r"(\\d)-(\\d)", r"\\1至\\2", txt)
        txt = txt.replace("-", " ")
        txt = txt.replace("！", "。")
        txt = txt.replace("!", "。")
        elem.replace_with(NavigableString(txt))
    clean_html = str(soup)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(clean_html)
    vis = BeautifulSoup(clean_html, "html.parser").get_text()
    bad_punc = [c for c in ("-", "—", "–", "！", "!", "→") if c in vis]
    if bad_punc:
        raise RuntimeError(f"Punctuation check failed for {html_path}: {bad_punc}")
    hit_machine = [w for w in BANNED_MACHINE_WORDS if w in vis]
    if hit_machine:
        raise RuntimeError(f"Machine-speak words detected in {html_path}: {hit_machine}")
    return len(vis)

def clear_doc_all(doc_id: str):
    for _ in range(50):
        n, pt = 0, None
        while True:
            u = f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children?page_size=500"
            if pt:
                u += f"&page_token={pt}"
            r = api(u, method="GET")
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
        time.sleep(0.35)
    return False

def insert_image_block(doc_id: str, png_path: str) -> bool:
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
    time.sleep(0.3)

    sz = os.path.getsize(png_path)
    tok = _shared_tok()
    cmd = [
        "curl", "-sS", "-X", "POST",
        f"{BASE}/open-apis/drive/v1/medias/upload_all",
        "-H", f"Authorization: Bearer {tok}",
        "-F", f"file_name={os.path.basename(png_path)}",
        "-F", "parent_type=docx_image",
        "-F", f"parent_node={blk_id}",
        "-F", f"size={sz}",
        "-F", f"file=@{png_path};type=image/png",
    ]
    out = subprocess.check_output(cmd, timeout=120).decode("utf-8")
    r2 = json.loads(out)
    if r2.get("code") != 0:
        print(f"  [IMG STEP2 ERR] {r2}")
        return False
    file_token = r2["data"]["file_token"]
    time.sleep(0.3)

    r3 = api(
        f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{blk_id}",
        {"replace_image": {"token": file_token}},
        "PATCH",
    )
    ok = r3.get("code") == 0
    print(f"  [IMG {'OK' if ok else 'FAIL'}] {os.path.basename(png_path)} -> block={blk_id}")
    time.sleep(0.3)
    return ok

def split_wide_tables_in_items(items, max_cols=8):
    out = []
    for it in items:
        if it.get("t") != "table":
            out.append(it)
            continue
        rows = it["rows"]
        if not rows:
            continue
        C = max(len(r) for r in rows)
        if C <= max_cols:
            out.append(it)
            continue
        step = max_cols - 1
        rest = list(range(1, C))
        chunks = [rest[i:i + step] for i in range(0, len(rest), step)]
        for p_idx, col_idxs in enumerate(chunks, 1):
            out.append({
                "t": "p",
                "runs": [(f"（续表 {p_idx}/{len(chunks)}）", {"italic": True, "text_color": 7})]
            })
            sub_rows = []
            for r in rows:
                padded = r + [[]] * max(0, C - len(r))
                sub_rows.append([padded[0]] + [padded[idx] for idx in col_idxs])
            out.append({"t": "table", "rows": sub_rows})
    return out

def upload_html_to_feishu(doc_id: str, html_path: str):
    vis_len_pre = sanitize_and_check_human_html(html_path)
    lock_fd = open(UPLOAD_LOCK, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        print(f"\\n=== Uploading {os.path.basename(html_path)} (chars={vis_len_pre}) -> {doc_id} ===")
        clear_doc_all(doc_id)
        with open(html_path, "r", encoding="utf-8") as f:
            raw_html = f.read()
        imgs = []
        def repl_box(m):
            idx = len(imgs)
            src = m.group(1).strip()
            cap = m.group(2).strip()
            imgs.append(src)
            return f"<p>@@IMG{idx}@@</p><p><i>{cap}</i></p>"
        html_mod = re.sub(
            r'<div class="chart-box">\\s*<img[^>]+src="([^"]+)"[^>]*/?>\\s*<div class="chart-caption">(.*?)</div>\\s*</div>',
            repl_box, raw_html, flags=re.S | re.I,
        )
        def repl_img(m):
            idx = len(imgs)
            src = m.group(1).strip()
            imgs.append(src)
            return f"<p>@@IMG{idx}@@</p>"
        html_mod = re.sub(r'<img[^>]+src="([^"]+)"[^>]*/?>', repl_img, html_mod, flags=re.S | re.I)

        tmp_path = f"/tmp/us_xuangu_20261109/mod_{doc_id}.html"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(html_mod)

        raw_items = parse2(tmp_path)
        col_split_items = split_wide_tables_in_items(raw_items, max_cols=8)
        items = split_big_tables(col_split_items)

        buf, done, fail, img_ok = [], 0, 0, 0
        def flush():
            nonlocal buf, done, fail
            if not buf:
                return
            for i in range(0, len(buf), 38):
                r = api(
                    f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children",
                    {"children": buf[i:i + 38]},
                    "POST",
                )
                if r.get("code") != 0:
                    fail += 1
                    print("  ERR children:", str(r)[:200])
                else:
                    done += len(buf[i:i + 38])
                time.sleep(0.32)
            buf = []

        for it in items:
            if it["t"] == "p":
                full_txt = "".join(t for t, _ in it.get("runs", [])).strip()
                m = re.match(r"^@@IMG(\\d+)@@$", full_txt)
                if m:
                    flush()
                    img_idx = int(m.group(1))
                    if insert_image_block(doc_id, imgs[img_idx]):
                        img_ok += 1
                        done += 1
                    else:
                        fail += 1
                    continue
            if it["t"] == "table":
                flush()
                d = Desc()
                root = d.add(it)
                r = api(
                    f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/descendant",
                    {"children_id": [root], "descendants": d.d},
                    "POST",
                )
                if r.get("code") != 0:
                    fail += 1
                    print("  ERR table:", str(r)[:200])
                else:
                    done += 1
                time.sleep(0.42)
            else:
                b = simple(it)
                if b:
                    buf.append(b)
        flush()
        print(f"  Write finished: done={done}, fail={fail}, img_ok={img_ok}/{len(imgs)}")
        return audit_doc(doc_id)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()

def audit_doc(doc_id: str):
    all_items, pt = [], None
    while True:
        u = f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks?page_size=500"
        if pt:
            u += f"&page_token={pt}"
        r = api(u, None, "GET")
        data = r.get("data", {})
        all_items.extend(data.get("items", []))
        if not data.get("has_more"):
            break
        pt = data.get("page_token")
    img_blocks = [it for it in all_items if it.get("block_type") == 27 and it.get("image", {}).get("token")]
    tbl_blocks = [it for it in all_items if it.get("block_type") == 31]
    callout_blocks = [it for it in all_items if it.get("block_type") == 19]
    hl_spans, total_chars, zh_chars = 0, 0, 0
    bad_counts = {"-": 0, "—": 0, "——": 0, "！": 0, "!": 0, "→": 0}
    for it in all_items:
        for k in ("text", "heading1", "heading2", "heading3", "heading4", "heading5", "heading6", "bullet", "ordered"):
            if k in it:
                for e in it[k].get("elements", []):
                    tr = e.get("text_run", {})
                    c = tr.get("content", "")
                    total_chars += len(c)
                    zh_chars += len(re.findall(r"[\\u4e00-\\u9fff]", c))
                    for bad in bad_counts:
                        bad_counts[bad] += c.count(bad)
                    if tr.get("text_element_style", {}).get("background_color") == 3:
                        hl_spans += 1
    res = {
        "doc_id": doc_id,
        "blocks": len(all_items),
        "zh_chars": zh_chars,
        "images": len(img_blocks),
        "tables": len(tbl_blocks),
        "callouts": len(callout_blocks),
        "yellow_runs": hl_spans,
        "bad_counts": bad_counts,
    }
    print("=== AUDIT ===", json.dumps(res, ensure_ascii=False))
    return res

if __name__ == "__main__":
    upload_html_to_feishu(sys.argv[1], sys.argv[2])

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
upload_feishu_report.py
Creates or updates our standalone native Feishu Wiki document in space 7702350621394947083 (财报纪要),
enforcing:
1. 100% Buwen human-language gate (zero banned AI buzzwords).
2. 100% zh-delivery punctuation gate (zero -, —, –, ——, ！, !, →, or status emojis).
3. Native PNG image upload, <mark> -> background_color: 3 yellow highlight, wide/long table auto-splitting,
   and full read-back verification (0 failed blocks).
"""

import sys, os, re, json, time, fcntl, subprocess
from bs4 import BeautifulSoup, NavigableString, Doctype, Comment

exec(open("/Users/huaichuaibeimeng/claude-projects/股票研究 Equity Research/_tools/html2feishu.py", "r", encoding="utf-8").read(), globals())
T = _shared_tok()
BASE = "https://open.feishu.cn"
PROJ = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-09-us-earnings-macro-30y"
TMP = "/tmp/us_earn_macro_bt_20261109"
META_JSON = f"{PROJ}/results/feishu_doc_meta.json"
UPLOAD_LOCK = f"{TMP}/.feishu_bt_upload.lock"

BANNED_MACHINE_WORDS = [
    "星辰大海", "皇冠明珠", "飞轮", "底座", "赋能", "闭环", "跃迁", "重塑", "颠覆",
    "范式", "生态", "矩阵", "全景", "硬核", "标尺", "试金石", "胜负手", "王牌",
    "钩子", "年金", "天花板", "破局", "抓手", "撬动", "罕见", "极其", "完美",
    "铁证", "铁律", "暗礁", "命门", "底牌", "法典", "死限", "拆穿", "十战十胜",
    "圣经", "贵族", "宪法", "D8", "D15", "SSOT", "本模型驾驶舱", "子模型", "共振"
]


def ensure_wiki_doc(space_id: str = "7702350621394947083", title: str = "美股30年财报拐点与宏观周期实证及2026Q3选股拆解") -> dict:
    if os.path.exists(META_JSON):
        meta = json.load(open(META_JSON))
        if meta.get("obj_token"):
            return meta
    r = api(
        f"{BASE}/open-apis/wiki/v2/spaces/{space_id}/nodes",
        {
            "obj_type": "docx",
            "node_type": "origin",
            "title": title,
        },
        "POST",
    )
    if r.get("code") != 0:
        raise RuntimeError(f"Failed to create wiki node: {r}")
    nd = r["data"]["node"]
    meta = {
        "space_id": space_id,
        "node_token": nd["node_token"],
        "obj_token": nd["obj_token"],
        "title": title,
        "url": f"https://my.feishu.cn/wiki/{nd['node_token']}",
    }
    with open(META_JSON, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return meta


def sanitize_and_audit_html(html_path: str) -> int:
    with open(html_path, "r", encoding="utf-8") as f:
        raw = f.read()
    soup = BeautifulSoup(raw, "html.parser")
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
        txt = txt.replace("——", "，").replace("—", "，").replace("–", "至").replace("→", "至")
        txt = re.sub(r"(?<![A-Za-z0-9])-(\d+(?:\.\d+)?%?)", r"负\1", txt)
        txt = re.sub(r"([A-Za-z])-([A-Za-z])", r"\1 \2", txt)
        txt = re.sub(r"(\d)-(\d)", r"\1至\2", txt)
        txt = txt.replace("-", " ")
        txt = txt.replace("！", "。").replace("!", "。")
        elem.replace_with(NavigableString(txt))
    clean_html = str(soup)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(clean_html)
    vis = BeautifulSoup(clean_html, "html.parser").get_text()
    bad_punc = [c for c in ("-", "—", "–", "！", "!", "→") if c in vis]
    if bad_punc:
        raise RuntimeError(f"Punctuation check failed: {bad_punc}")
    hit_words = [w for w in BANNED_MACHINE_WORDS if w in vis]
    if hit_words:
        raise RuntimeError(f"Banned machine words found: {hit_words}")
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


def upload_html(html_path: str, title: str = "美股30年财报拐点与宏观周期实证及2026Q3选股拆解") -> dict:
    vis_chars = sanitize_and_audit_html(html_path)
    meta = ensure_wiki_doc(title=title)
    doc_id = meta["obj_token"]

    lock_fd = open(UPLOAD_LOCK, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        print(f"Uploading {os.path.basename(html_path)} ({vis_chars} chars) -> {doc_id} ({meta['url']})")
        clear_doc_all(doc_id)
        with open(html_path, "r", encoding="utf-8") as f:
            raw_html = f.read()

        imgs = []
        def repl_img(m):
            idx = len(imgs)
            imgs.append(m.group(1).strip())
            return f"<p>@@IMG{idx}@@</p>"

        html_mod = re.sub(r'<img[^>]+src="([^"]+)"[^>]*/?>', repl_img, raw_html, flags=re.S | re.I)
        tmp_mod = f"{TMP}/mod_upload_{doc_id}.html"
        with open(tmp_mod, "w", encoding="utf-8") as f:
            f.write(html_mod)

        raw_items = parse2(tmp_mod)
        items = split_big_tables(split_wide_tables_in_items(raw_items, max_cols=8))

        buf, done, fail, img_ok = [], 0, 0, 0
        def flush():
            nonlocal buf, done, fail
            if not buf:
                return
            for k in range(0, len(buf), 50):
                chunk = buf[k:k+50]
                r = api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children", {"children": chunk, "index": -1}, "POST")
                if r.get("code") == 0:
                    done += len(chunk)
                else:
                    for b in chunk:
                        r2 = api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children", {"children": [b], "index": -1}, "POST")
                        if r2.get("code") == 0:
                            done += 1
                        else:
                            fail += 1
                            print("  [BLOCK FAIL]", r2)
                time.sleep(0.25)
            buf = []

        for it in items:
            if it.get("t") == "p":
                txt = "".join(r[0] for r in it.get("runs", [])).strip()
                m = re.fullmatch(r"@@IMG(\d+)@@", txt)
                if m:
                    flush()
                    if insert_image_block(doc_id, imgs[int(m.group(1))]):
                        img_ok += 1
                    else:
                        fail += 1
                    continue
            if it.get("t") in ("table", "callout"):
                flush()
                d = Desc()
                root = d.add(it)
                rt = api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/descendant",
                         {"children_id": [root], "descendants": d.d})
                if rt.get("code") == 0:
                    done += 1
                else:
                    fail += 1
                    print("  [TABLE/CALLOUT FAIL]", rt.get("msg"))
                time.sleep(0.45)
            else:
                b = simple(it)
                if b:
                    buf.append(b)
                if len(buf) >= 40:
                    flush()
        flush()

        # Read-back verification
        rc = api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/raw_content", method="GET")
        raw_back = rc.get("data", {}).get("content", "")
        print(f"UPLOAD RESULT: done={done}, img_ok={img_ok}/{len(imgs)}, fail={fail}, readback_chars={len(raw_back)}")
        if fail > 0 or len(raw_back) < 500:
            raise RuntimeError(f"Feishu verification failed: fail={fail}, readback={len(raw_back)}")
        meta["readback_chars"] = len(raw_back)
        meta["done_blocks"] = done
        meta["images_ok"] = img_ok
        with open(META_JSON, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        return meta
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 upload_feishu_report.py <html_path> [title]")
        sys.exit(1)
    hp = sys.argv[1]
    tt = sys.argv[2] if len(sys.argv) >= 3 else "美股30年财报拐点与宏观周期实证及2026Q3选股拆解"
    res = upload_html(hp, tt)
    print(json.dumps(res, ensure_ascii=False, indent=2))

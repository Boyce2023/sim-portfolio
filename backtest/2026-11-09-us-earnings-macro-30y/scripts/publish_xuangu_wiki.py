#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
publish_xuangu_wiki.py
Publishes clean, simple-titled, relaxed-yet-focused (重点用力、非重点放松, modeled on 五板策略)
US stock selection strategy main docs and detailed backtest child docs into 选股 Wiki (7681220535547743183).
Strictly touches ONLY our own nodes recorded in xuangu_wiki_manifest.json (zero collision with research's nodes).
"""
import os, sys, re, json, time, fcntl, subprocess
from bs4 import BeautifulSoup, NavigableString, Doctype, Comment

exec(open("/Users/huaichuaibeimeng/claude-projects/股票研究 Equity Research/_tools/html2feishu.py", "r", encoding="utf-8").read(), globals())
BASE = "https://open.feishu.cn"
SPACE_ID = "7681220535547743183"  # 选股 Wiki
PROJ = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-09-us-earnings-macro-30y"
TMP = "/tmp/us_earn_macro_bt_20261109"
MANIFEST_PATH = f"{PROJ}/results/xuangu_wiki_manifest.json"
LOCK_PATH = f"{TMP}/.xuangu_wiki_pub.lock"

# Strict anti-overtry / anti-AI buzzword gate (Opus "太用力" + zh-delivery gate)
BANNED_OVERTRY_WORDS = [
    "星辰大海", "皇冠明珠", "飞轮", "底座", "赋能", "闭环", "跃迁", "重塑", "颠覆",
    "范式", "生态", "矩阵", "全景", "硬核", "标尺", "试金石", "胜负手", "王牌",
    "钩子", "年金", "天花板", "破局", "抓手", "撬动", "罕见", "极其", "完美",
    "铁证", "铁律", "暗礁", "命门", "底牌", "法典", "死限", "拆穿", "十战十胜",
    "圣经", "贵族", "宪法", "D8", "D15", "SSOT", "本模型驾驶舱", "子模型", "共振",
    "统治级", "绞肉机", "生死线", "金矿", "火坑", "法医", "炸裂", "惊人", "惨烈", "暴利"
]


def load_manifest() -> dict:
    if os.path.exists(MANIFEST_PATH):
        return json.load(open(MANIFEST_PATH, "r", encoding="utf-8"))
    return {"space_id": SPACE_ID, "nodes": {}}


def save_manifest(m: dict):
    os.makedirs(os.path.dirname(MANIFEST_PATH), exist_ok=True)
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)


def ensure_node(key: str, title: str, parent_node_token: str = None) -> dict:
    m = load_manifest()
    if key in m["nodes"] and m["nodes"][key].get("obj_token"):
        info = m["nodes"][key]
        # Update title if changed
        if info.get("title") != title:
            api(
                f"{BASE}/open-apis/wiki/v2/spaces/{SPACE_ID}/nodes/{info['node_token']}/update_title",
                {"title": title},
                "POST",
            )
            info["title"] = title
            save_manifest(m)
        return info

    payload = {
        "obj_type": "docx",
        "node_type": "origin",
        "title": title,
    }
    if parent_node_token:
        payload["parent_node_token"] = parent_node_token
    r = api(f"{BASE}/open-apis/wiki/v2/spaces/{SPACE_ID}/nodes", payload, "POST")
    if r.get("code") != 0:
        raise RuntimeError(f"Failed creating wiki node {key} ({title}): {r}")
    nd = r["data"]["node"]
    info = {
        "key": key,
        "title": title,
        "node_token": nd["node_token"],
        "obj_token": nd["obj_token"],
        "parent_node_token": parent_node_token or "",
        "url": f"https://my.feishu.cn/wiki/{nd['node_token']}",
    }
    m["nodes"][key] = info
    save_manifest(m)
    return info


def sanitize_and_gate_html(html_path: str) -> int:
    with open(html_path, "r", encoding="utf-8") as f:
        raw = f.read()
    # Convert any accidental **bold** to <strong>bold</strong>
    raw = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", raw)
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
    bad_punc = [c for c in ("-", "—", "–", "！", "!", "→", "**") if c in vis]
    if bad_punc:
        raise RuntimeError(f"[{os.path.basename(html_path)}] Punctuation/markdown gate failed: {bad_punc}")
    hits = [w for w in BANNED_OVERTRY_WORDS if w in vis]
    if hits:
        raise RuntimeError(f"[{os.path.basename(html_path)}] Overtry/buzzword gate failed: {hits}")
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
        time.sleep(0.3)
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
    time.sleep(0.25)

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
    time.sleep(0.25)

    r3 = api(
        f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{blk_id}",
        {"replace_image": {"token": file_token}},
        "PATCH",
    )
    ok = r3.get("code") == 0
    print(f"  [IMG {'OK' if ok else 'FAIL'}] {os.path.basename(png_path)}")
    time.sleep(0.25)
    return ok


def split_wide_tables_in_items(items, max_cols=7):
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
            out.append({"t": "p", "runs": [(f"（续表 {p_idx}/{len(chunks)}）", {"italic": True, "text_color": 7})]})
            sub_rows = []
            for r in rows:
                padded = r + [[]] * max(0, C - len(r))
                sub_rows.append([padded[0]] + [padded[idx] for idx in col_idxs])
            out.append({"t": "table", "rows": sub_rows})
    return out


def publish_doc(key: str, title: str, html_path: str, parent_key: str = None) -> dict:
    vis_chars = sanitize_and_gate_html(html_path)
    parent_tok = None
    if parent_key:
        m = load_manifest()
        parent_tok = m["nodes"][parent_key]["node_token"]
    info = ensure_node(key, title, parent_tok)
    doc_id = info["obj_token"]

    os.makedirs(TMP, exist_ok=True)
    lock_fd = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        print(f"Publishing [{title}] ({vis_chars} chars) -> {info['url']}")
        clear_doc_all(doc_id)
        raw_html = open(html_path, "r", encoding="utf-8").read()

        imgs = []
        def repl_img(m):
            idx = len(imgs)
            imgs.append(m.group(1).strip())
            return f"<p>@@IMG{idx}@@</p>"

        html_mod = re.sub(r'<img[^>]+src="([^"]+)"[^>]*/?>', repl_img, raw_html, flags=re.S | re.I)
        tmp_mod = f"{TMP}/mod_xuangu_{doc_id}.html"
        with open(tmp_mod, "w", encoding="utf-8") as f:
            f.write(html_mod)

        raw_items = parse2(tmp_mod)
        items = split_big_tables(split_wide_tables_in_items(sanitize_callouts(raw_items), max_cols=7))

        buf, done, fail, img_ok = [], 0, 0, 0
        def flush():
            nonlocal buf, done, fail
            if not buf:
                return
            for i in range(0, len(buf), 40):
                chunk = buf[i:i+40]
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
                            print("  [BLOCK FAIL]", r2.get("msg"))
                time.sleep(0.3)
            buf = []

        for it in items:
            if it.get("t") == "p":
                txt = "".join(r[0] for r in it.get("runs", [])).strip()
                m_img = re.fullmatch(r"@@IMG(\d+)@@", txt)
                if m_img:
                    flush()
                    if insert_image_block(doc_id, imgs[int(m_img.group(1))]):
                        img_ok += 1
                    else:
                        fail += 1
                    continue
            if it.get("t") in ("table", "callout"):
                flush()
                d = Desc()
                root = d.add(it)
                rt = api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/descendant", {"children_id": [root], "descendants": d.d})
                if rt.get("code") == 0:
                    done += 1
                else:
                    fail += 1
                    print("  [TABLE FAIL]", rt.get("msg"))
                time.sleep(0.4)
            else:
                b = simple(it)
                if b:
                    buf.append(b)
                if len(buf) >= 40:
                    flush()
        flush()

        rc = api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/raw_content", method="GET")
        rb = rc.get("data", {}).get("content", "")
        print(f"  -> OK [{title}]: blocks={done}, imgs={img_ok}/{len(imgs)}, fail={fail}, readback={len(rb)}")
        if fail > 0 or len(rb) < 200:
            raise RuntimeError(f"Verification failed on {title}: fail={fail}, readback={len(rb)}")
        m = load_manifest()
        m["nodes"][key].update({"done_blocks": done, "images_ok": img_ok, "readback_chars": len(rb)})
        save_manifest(m)
        return m["nodes"][key]
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()

if __name__ == "__main__":
    print("publish_xuangu_wiki.py syntax & imports OK.")

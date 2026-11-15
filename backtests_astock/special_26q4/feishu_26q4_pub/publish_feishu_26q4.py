#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""安全发布飞书知识库《26Q4专供》及三篇子文档：
- [顶层父文档] 26Q4专供 (parent_node_token = None)
- [子文档 1] 高标首阴，26Q4 (parent = 26Q4专供)
- [子文档 2] 三进四，26Q4 (parent = 26Q4专供)
- [子文档 3] 一进二，26Q4 (parent = 26Q4专供)
"""
import os, sys, re, json, time, fcntl, subprocess
from bs4 import BeautifulSoup, NavigableString, Doctype, Comment

exec(open("/Users/huaichuaibeimeng/claude-projects/股票研究 Equity Research/_tools/html2feishu.py", "r", encoding="utf-8").read(), globals())

BASE = "https://open.feishu.cn"
SPACE_ID = "7700231295393107208"  # A股策略与回测
CUR_DIR = os.path.dirname(os.path.abspath(__file__))
MANIFEST_PATH = f"{CUR_DIR}/feishu_26q4_manifest.json"
LOCK_PATH = "/tmp/.feishu_26q4_pub.lock"

# 绝对禁止触碰的既有主策略基石节点 doc_id 保护池
FORBIDDEN_DOCS = [
    "HexPdpU4uowtfZx1IIscgIKrnce",
    "OeJed4uL5oQ2nRxeOXIc4HronDe",  # 一进二
    "RrybdVJmQoxfrExuYOacxn8Nn1f",  # 高标
    "SFPVd9gSgoN33SxMsUHc4xJNnVf",  # 三进四
    "WuXLdc9EMoDhaVxyobrcaNNnnwb",  # 撬板
    "IxRid53GroXPEXxrxlbcxynQnLe",  # 四进五
    "ESy0dajsjotlVcxWJU4cxcwcnxh",  # 政策
    "DL6ndA93eoqDADxXsFYcKfDanEf",  # 因子挖掘
    "SKdrd9v8joVvHQxRwQucwcfUneh",  # 简单的讨论
]

BANNED = [
    "星辰大海", "皇冠明珠", "飞轮", "赋能", "闭环", "跃迁", "重塑", "颠覆", "范式", "矩阵", "全景", "硬核",
    "标尺", "试金石", "胜负手", "王牌", "天花板", "抓手", "撬动", "铁证", "铁律", "命门", "法典", "宪法",
    "D8", "D15", "SSOT", "绞肉机", "法医"
]

CODE_VARS = [
    "obc", "pelo", "is_dying_pulse", "rk_theme", "d0_tight", "s_prior", "pass_l2", "clean_brk60", "plate_d2_yizi_cnt"
]

def load_manifest():
    if os.path.exists(MANIFEST_PATH):
        try:
            return json.load(open(MANIFEST_PATH, "r", encoding="utf-8"))
        except Exception:
            pass
    return {"space_id": SPACE_ID, "nodes": {}}

def save_manifest(m):
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)

def ensure_node(key: str, title: str, parent_node_token: str = None) -> dict:
    m = load_manifest()
    if key in m["nodes"] and m["nodes"][key].get("obj_token"):
        info = m["nodes"][key]
        if info.get("title") != title:
            print(f"[*] Updating title for {key} from '{info.get('title')}' to '{title}'...")
            api(f"{BASE}/open-apis/wiki/v2/spaces/{SPACE_ID}/nodes/{info['node_token']}/update_title", {"title": title}, "POST")
            info["title"] = title
            save_manifest(m)
        return info

    payload = {"obj_type": "docx", "node_type": "origin", "title": title}
    if parent_node_token:
        payload["parent_node_token"] = parent_node_token
    print(f"[*] Creating wiki node {key} ('{title}', parent={parent_node_token})...")
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
        "url": f"https://my.feishu.cn/wiki/{nd['node_token']}"
    }
    m["nodes"][key] = info
    save_manifest(m)
    print(f"[+] Created node {key} -> {info['url']} (obj_token={info['obj_token']})")
    return info

def sanitize_html(html_path: str) -> int:
    raw = open(html_path, "r", encoding="utf-8").read()
    soup = BeautifulSoup(raw, "html.parser")
    for elem in soup.find_all(string=True):
        if isinstance(elem, (Doctype, Comment)): elem.extract(); continue
        if elem.parent and elem.parent.name in ("style", "script"): continue
        txt = str(elem).replace("——", "，").replace("—", "，").replace("–", "至").replace("→", "至")
        txt = txt.replace("；", "，").replace(";", "，")
        txt = re.sub(r"(\d)-(\d)", r"\1至\2", txt).replace("-", " ").replace("！", "。").replace("!", "。")
        elem.replace_with(NavigableString(txt))
    clean = str(soup)
    open(html_path, "w", encoding="utf-8").write(clean)
    vis = BeautifulSoup(clean, "html.parser").get_text()
    bad = [c for c in ("-", "—", "–", "！", "!", "→", "**", ";", "；") if c in vis]
    if bad: raise RuntimeError(f"[{os.path.basename(html_path)}] Bad punc: {bad}")
    hits = [w for w in BANNED if w in vis]
    if hits: raise RuntimeError(f"[{os.path.basename(html_path)}] Banned word: {hits}")
    var_hits = [v for v in CODE_VARS if v.lower() in vis.lower()]
    if var_hits: raise RuntimeError(f"[{os.path.basename(html_path)}] Code vars: {var_hits}")
    return len(vis)

def clear_doc_all(doc_id: str):
    # Strict safety boundary check
    if doc_id in FORBIDDEN_DOCS:
        raise RuntimeError(f"FATAL SAFETY BLOCK: ATTEMPTED TO TOUCH PROTECTED BASELINE DOC {doc_id}!")
    for _ in range(40):
        r = api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children?page_size=500", method="GET")
        if r.get("code") != 0: break
        n = len(r["data"].get("items") or [])
        if n == 0: return True
        api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children/batch_delete", {"start_index": 0, "end_index": min(n, 150)}, "DELETE")
        time.sleep(0.25)
    return False

def insert_image_block(doc_id: str, png_path: str) -> bool:
    if not os.path.exists(png_path):
        print(f"[-] Image not found: {png_path}")
        return False
    r1 = api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children", {"children": [{"block_type": 27, "image": {}}], "index": -1}, "POST")
    if r1.get("code") != 0:
        print("[-] Create image block failed:", r1)
        return False
    blk_id = r1["data"]["children"][0]["block_id"]
    time.sleep(0.2)
    tok_s = _shared_tok()
    out = subprocess.check_output(["curl", "-sS", "-X", "POST", f"{BASE}/open-apis/drive/v1/medias/upload_all",
        "-H", f"Authorization: Bearer {tok_s}", "-F", f"file_name={os.path.basename(png_path)}",
        "-F", "parent_type=docx_image", "-F", f"parent_node={blk_id}", "-F", f"size={os.path.getsize(png_path)}",
        "-F", f"file=@{png_path};type=image/png"], timeout=120).decode("utf-8")
    r2 = json.loads(out)
    if r2.get("code") != 0:
        print("[-] Upload media failed:", r2)
        return False
    time.sleep(0.2)
    r3 = api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{blk_id}", {"replace_image": {"token": r2["data"]["file_token"]}}, "PATCH")
    if r3.get("code") != 0:
        print("[-] Replace image failed:", r3)
        return False
    print(f"[+] Uploaded and attached {os.path.basename(png_path)} -> blk {blk_id}")
    return True

def publish_one(key: str, title: str, html_path: str, parent_key: str = None):
    vis_chars = sanitize_html(html_path)
    p_tok = load_manifest()["nodes"][parent_key]["node_token"] if parent_key else None
    info = ensure_node(key, title, p_tok)
    doc_id = info["obj_token"]
    if doc_id in FORBIDDEN_DOCS:
        raise RuntimeError(f"FATAL SAFETY BLOCK: Cannot touch protected doc {doc_id}!")
    
    lock_fd = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        print(f"[*] Clearing doc {doc_id} for {title}...")
        clear_doc_all(doc_id)
        raw_html = open(html_path, "r", encoding="utf-8").read()
        imgs = []
        def repl_img(m):
            imgs.append(m.group(1).strip()); return f"<p>@@IMG{len(imgs)-1}@@</p>"
        tmp_mod = f"/tmp/mod_26q4_{doc_id}.html"
        open(tmp_mod, "w", encoding="utf-8").write(re.sub(r'<img[^>]+src="([^"]+)"[^>]*/?>', repl_img, raw_html, flags=re.S | re.I))
        items = split_big_tables(sanitize_callouts(parse2(tmp_mod)))
        buf, done, fail, img_ok = [], 0, 0, 0
        def flush():
            nonlocal buf, done, fail
            for i in range(0, len(buf), 40):
                ch = buf[i:i+40]
                r = api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children", {"children": ch, "index": -1}, "POST")
                if r.get("code") == 0: done += len(ch)
                else:
                    for b in ch:
                        r2 = api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children", {"children": [b], "index": -1}, "POST")
                        if r2.get("code") == 0: done += 1
                        else: fail += 1
                time.sleep(0.25)
            buf = []
        for it in items:
            if it.get("t") == "p":
                m_i = re.fullmatch(r"@@IMG(\d+)@@", "".join(x[0] for x in it.get("runs", [])).strip())
                if m_i:
                    flush()
                    if insert_image_block(doc_id, imgs[int(m_i.group(1))]): img_ok += 1
                    else: fail += 1
                    continue
            if it.get("t") in ("table", "callout"):
                flush(); d = Desc(); root = d.add(it)
                rt = api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/descendant", {"children_id": [root], "descendants": d.d})
                if rt.get("code") == 0: done += 1
                else:
                    fail += 1
                    print(f"[-] TABLE FAIL in {title}: {rt}")
                time.sleep(0.35)
            else:
                b = simple(it)
                if b: buf.append(b)
        flush()
        rb = api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/raw_content", method="GET").get("data", {}).get("content", "")
        print(f"[SUCCESS] {title} -> {info['url']} | blocks={done} imgs={img_ok}/{len(imgs)} fail={fail} readback={len(rb)} chars")
        if fail > 0 or len(rb) < 300:
            raise RuntimeError(f"Failed verify {title}: fail={fail}, rb={len(rb)}")
        m = load_manifest()
        m["nodes"][key].update({
            "done_blocks": done,
            "images_ok": img_ok,
            "readback_chars": len(rb),
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")
        })
        save_manifest(m)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()

if __name__ == "__main__":
    print("=" * 80)
    print("【开始串行发布《26Q4专供》及三篇子文档至飞书知识库】")
    print(f"目标知识库 SPACE_ID = {SPACE_ID}")
    print("=" * 80)

    # 1. 顶层父文档：26Q4专供
    print("\n>>> [1/4] 创建并发布顶层父文档【26Q4专供】...")
    publish_one("parent_26q4", "26Q4专供", f"{CUR_DIR}/00_parent_26q4_overview.html", None)

    # 2. 子文档 1：高标首阴，26Q4
    print("\n>>> [2/4] 创建并发布子文档 1【高标首阴，26Q4】...")
    publish_one("sub_high_26q4", "高标首阴，26Q4", f"{CUR_DIR}/01_sub_high_26q4.html", "parent_26q4")

    # 3. 子文档 2：三进四，26Q4
    print("\n>>> [3/4] 创建并发布子文档 2【三进四，26Q4】...")
    publish_one("sub_3to4_26q4", "三进四，26Q4", f"{CUR_DIR}/02_sub_3to4_26q4.html", "parent_26q4")

    # 4. 子文档 3：一进二，26Q4
    print("\n>>> [4/4] 创建并发布子文档 3【一进二，26Q4】...")
    publish_one("sub_1to2_26q4", "一进二，26Q4", f"{CUR_DIR}/03_sub_1to2_26q4.html", "parent_26q4")

    print("\n🎉【飞书知识库《26Q4专供》全套 4 篇文档串行安全发布完成！】")

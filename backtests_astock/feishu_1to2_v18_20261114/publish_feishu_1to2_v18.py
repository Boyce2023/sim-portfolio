#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""安全发布《A股策略与回测》知识库下 [L0] 一进二主文档 + [L1] 20261114 一进二专项小回测全集与近期有效度总检 + [L2] 18 纯打分升级与五项盘感及降门槛防过拟合回测"""
import os, sys, re, json, time, fcntl, subprocess
from bs4 import BeautifulSoup, NavigableString, Doctype, Comment

exec(open("/Users/huaichuaibeimeng/claude-projects/股票研究 Equity Research/_tools/html2feishu.py", "r", encoding="utf-8").read(), globals())

BASE = "https://open.feishu.cn"
SPACE_ID = "7700231295393107208"  # A股策略与回测
CUR_DIR = os.path.dirname(os.path.abspath(__file__))
MANIFEST_PATH = f"{CUR_DIR}/feishu_1to2_wiki_manifest.json"
LOCK_PATH = "/tmp/.feishu_1to2_v18_pub.lock"

BANNED = ["星辰大海", "皇冠明珠", "飞轮", "赋能", "闭环", "跃迁", "重塑", "颠覆", "范式", "矩阵", "全景", "硬核",
          "标尺", "试金石", "胜负手", "王牌", "天花板", "抓手", "撬动", "铁证", "铁律", "命门", "法典", "宪法",
          "D8", "D15", "SSOT", "绞肉机", "法医"]

def load_manifest():
    if os.path.exists(MANIFEST_PATH):
        return json.load(open(MANIFEST_PATH, "r", encoding="utf-8"))
    return {
        "space_id": SPACE_ID,
        "nodes": {
            "main_1to2": {
                "key": "main_1to2",
                "title": "一进二",
                "node_token": "TRE2wRsLbimSFhkl7sPc9XZHnBj",
                "obj_token": "OeJed4uL5oQ2nRxeOXIc4HronDe",
                "parent_node_token": "",
                "url": "https://my.feishu.cn/wiki/TRE2wRsLbimSFhkl7sPc9XZHnBj",
            },
            "hub_1to2": {
                "key": "hub_1to2",
                "title": "20261114 一进二专项小回测全集与近期有效度总检",
                "node_token": "UKuvwfHmriXLCjkq4SzcLAchnBh",
                "obj_token": "RTiqd555Soj78vx3GOdcqEO9nze",
                "parent_node_token": "TRE2wRsLbimSFhkl7sPc9XZHnBj",
                "url": "https://my.feishu.cn/wiki/UKuvwfHmriXLCjkq4SzcLAchnBh",
            }
        }
    }

def save_manifest(m):
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)

def ensure_node(key: str, title: str, parent_node_token: str = None) -> dict:
    m = load_manifest()
    if key in m["nodes"] and m["nodes"][key].get("obj_token"):
        info = m["nodes"][key]
        if info.get("title") != title and key != "main_1to2":
            api(f"{BASE}/open-apis/wiki/v2/spaces/{SPACE_ID}/nodes/{info['node_token']}/update_title", {"title": title}, "POST")
            info["title"] = title
            save_manifest(m)
        return info

    payload = {"obj_type": "docx", "node_type": "origin", "title": title}
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
        "url": f"https://my.feishu.cn/wiki/{nd['node_token']}"
    }
    m["nodes"][key] = info
    save_manifest(m)
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
    return len(vis)

def clear_doc_all(doc_id: str):
    # Strict safety boundary check
    if doc_id == "HexPdpU4uowtfZx1IIscgIKrnce":
        raise RuntimeError("FATAL SAFETY BLOCK: ATTEMPTED TO TOUCH 5BOARD DOC!")
    for _ in range(40):
        r = api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children?page_size=500", method="GET")
        if r.get("code") != 0: break
        n = len(r["data"].get("items") or [])
        if n == 0: return True
        api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children/batch_delete", {"start_index": 0, "end_index": min(n, 150)}, "DELETE")
        time.sleep(0.25)
    return False

def insert_image_block(doc_id: str, png_path: str) -> bool:
    r1 = api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children", {"children": [{"block_type": 27, "image": {}}], "index": -1}, "POST")
    if r1.get("code") != 0: return False
    blk_id = r1["data"]["children"][0]["block_id"]
    time.sleep(0.2)
    tok_s = _shared_tok()
    out = subprocess.check_output(["curl", "-sS", "-X", "POST", f"{BASE}/open-apis/drive/v1/medias/upload_all",
        "-H", f"Authorization: Bearer {tok_s}", "-F", f"file_name={os.path.basename(png_path)}",
        "-F", "parent_type=docx_image", "-F", f"parent_node={blk_id}", "-F", f"size={os.path.getsize(png_path)}",
        "-F", f"file=@{png_path};type=image/png"], timeout=120).decode("utf-8")
    r2 = json.loads(out)
    if r2.get("code") != 0: return False
    time.sleep(0.2)
    r3 = api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{blk_id}", {"replace_image": {"token": r2["data"]["file_token"]}}, "PATCH")
    return r3.get("code") == 0

def publish_one(key: str, title: str, html_path: str, parent_key: str = None):
    vis_chars = sanitize_html(html_path)
    p_tok = load_manifest()["nodes"][parent_key]["node_token"] if parent_key else None
    info = ensure_node(key, title, p_tok)
    doc_id = info["obj_token"]
    if doc_id == "HexPdpU4uowtfZx1IIscgIKrnce":
        raise RuntimeError("FATAL SAFETY BLOCK: Cannot touch HexPdpU4uowtfZx1IIscgIKrnce!")
    
    lock_fd = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        clear_doc_all(doc_id)
        raw_html = open(html_path, "r", encoding="utf-8").read()
        imgs = []
        def repl_img(m):
            imgs.append(m.group(1).strip()); return f"<p>@@IMG{len(imgs)-1}@@</p>"
        tmp_mod = f"/tmp/mod_1to2_{doc_id}.html"
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
                else: fail += 1; print("TABLE FAIL:", rt)
                time.sleep(0.35)
            else:
                b = simple(it)
                if b: buf.append(b)
        flush()
        rb = api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/raw_content", method="GET").get("data", {}).get("content", "")
        print(f"[OK] {title} -> {info['url']} | blocks={done} imgs={img_ok}/{len(imgs)} fail={fail} readback={len(rb)}")
        if fail > 0 or len(rb) < 150: raise RuntimeError(f"Failed verify {title}: fail={fail}, rb={len(rb)}")
        m = load_manifest(); m["nodes"][key].update({"done_blocks": done, "images_ok": img_ok, "readback_chars": len(rb)}); save_manifest(m)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN); lock_fd.close()

if __name__ == "__main__":
    print("=" * 80)
    print("【开始串行发布《一进二》V18 纯打分知识库三篇文档】")
    print("=" * 80)

    # 1. 发布 [L0] 一进二主文档
    print("\n>>> [1/3] 发布 [L0] 一进二主文档 (TRE2wRsLbimSFhkl7sPc9XZHnBj)...")
    publish_one("main_1to2", "一进二", f"{CUR_DIR}/00_main_1to2.html", None)

    # 2. 发布 [L1] 一进二总检副文档
    print("\n>>> [2/3] 发布 [L1] 20261114 一进二专项小回测全集与近期有效度总检 (UKuvwfHmriXLCjkq4SzcLAchnBh)...")
    publish_one("hub_1to2", "20261114 一进二专项小回测全集与近期有效度总检", f"{CUR_DIR}/01_hub_1to2_overview.html", "main_1to2")

    # 3. 创建并发布 [L2] 18 子文档
    print("\n>>> [3/3] 创建并发布 [L2] 18 纯打分升级与五项盘感及降门槛防过拟合回测...")
    publish_one("sub18_pure_scoring", "18 纯打分升级与五项盘感及降门槛防过拟合回测", f"{CUR_DIR}/02_l2_sub18_pure_scoring.html", "hub_1to2")

    print("\n🎉【一进二 V18 纯打分知识库三篇文档串行安全发布完成！】")

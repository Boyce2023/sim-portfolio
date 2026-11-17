#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""串行安全发布《A股策略与回测》知识库下 [L0] 四进五主文档 + [L1] 773切片总检 + [L1] 二进三证伪淘汰"""
import os, sys, re, json, time, fcntl, subprocess
from bs4 import BeautifulSoup, NavigableString, Doctype, Comment

exec(open("/Users/huaichuaibeimeng/claude-projects/股票研究 Equity Research/_tools/html2feishu.py", "r", encoding="utf-8").read(), globals())

BASE = "https://open.feishu.cn"
SPACE_ID = "7700231295393107208"  # A股策略与回测
CUR_DIR = os.path.dirname(os.path.abspath(__file__))
MANIFEST_PATH = f"{CUR_DIR}/feishu_4to5_wiki_manifest.json"
LOCK_PATH = "/tmp/.feishu_wiki_pub_global.lock"

BANNED = ["星辰大海", "皇冠明珠", "飞轮", "赋能", "闭环", "跃迁", "重塑", "颠覆", "范式", "矩阵", "全景", "硬核",
          "标尺", "试金石", "胜负手", "王牌", "天花板", "抓手", "撬动", "铁证", "铁律", "命门", "法典", "宪法",
          "D8", "D15", "SSOT", "绞肉机", "法医", "五板策略"]

def load_manifest():
    if os.path.exists(MANIFEST_PATH):
        return json.load(open(MANIFEST_PATH, "r", encoding="utf-8"))
    return {"space_id": SPACE_ID, "nodes": {}}

def save_manifest(m):
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)

def ensure_node(key: str, title: str, parent_node_token: str = "") -> dict:
    m = load_manifest()
    if key in m["nodes"] and m["nodes"][key].get("obj_token"):
        info = m["nodes"][key]
        if info.get("title") != title:
            pass  # NEVER alter existing user node title or order
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
        txt = re.sub(r"(\d)-(\d)", r"\1至\2", txt).replace("-", " ").replace("！", "。").replace("!", "。")
        elem.replace_with(NavigableString(txt))
    clean = str(soup)
    open(html_path, "w", encoding="utf-8").write(clean)
    vis = BeautifulSoup(clean, "html.parser").get_text()
    bad = [c for c in ("-", "—", "–", "！", "!", "→", "**") if c in vis]
    if bad: raise RuntimeError(f"[{os.path.basename(html_path)}] Bad punc: {bad}")
    hits = [w for w in BANNED if w in vis]
    if hits: raise RuntimeError(f"[{os.path.basename(html_path)}] Banned word: {hits}")
    return len(vis)

def clear_doc_all(doc_id: str):
    # Safety: ensure doc_id is NOT the five board doc HexPdpU4uowtfZx1IIscgIKrnce
    if doc_id == "HexPdpU4uowtfZx1IIscgIKrnce":
        raise RuntimeError("FATAL CRITICAL SAFETY BLOCK: ATTEMPTED TO CLEAR BUWEN 5BOARD DOC!")
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

def publish_one(key: str, title: str, html_path: str, parent_node_token: str = ""):
    vis_chars = sanitize_html(html_path)
    info = ensure_node(key, title, parent_node_token)
    doc_id = info["obj_token"]
    print(f"\n[*] 准备发布: [{key}] {title} -> doc_id={doc_id}")

    lock_fd = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        clear_doc_all(doc_id)
        raw_html = open(html_path, "r", encoding="utf-8").read()
        imgs = []
        def repl_img(m):
            imgs.append(m.group(1).strip()); return f"<p>@@IMG{len(imgs)-1}@@</p>"
        tmp_mod = f"/tmp/mod_4to5_{doc_id}.html"
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
        if fail > 0 or len(rb) < 500:
            raise RuntimeError(f"Failed verify {title}: fail={fail}, rb={len(rb)}")
        m = load_manifest()
        m["nodes"][key].update({"done_blocks": done, "images_ok": img_ok, "readback_chars": len(rb)})
        save_manifest(m)
        return info
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()

if __name__ == "__main__":
    print("=== 开始发布飞书知识库三篇四进五与二进三策略回测文档 ===")
    # 1. 节点A: L0 顶层目录 四进五
    info_a = publish_one("main_4to5", "四进五", f"{CUR_DIR}/00_main_4to5.html", parent_node_token="")
    print(f"[Node A Published] {info_a['title']} -> {info_a['url']}")

    # 2. 节点B: 挂在 四进五 下方的 L1 回测子目录
    parent_tok_b = info_a["node_token"]
    info_b = publish_one("sub_4to5_773", "20261114 四进五773切片深研与纯单仓顺位总检", f"{CUR_DIR}/01_hub_4to5_773slices.html", parent_node_token=parent_tok_b)
    print(f"[Node B Published] {info_b['title']} -> {info_b['url']}")

    # 3. 节点C: 挂在 Claude/Argon 因子挖掘、回测 下方的 L1 证伪回测文档
    parent_tok_c = "Jxarwc3wliQZCakXO1xccPmrnCc"
    info_c = publish_one("falsify_2to3", "20261114 二进三全量因子证伪淘汰与五策略纯单仓顺位总回测", f"{CUR_DIR}/02_falsify_2to3_5strat_audit.html", parent_node_token=parent_tok_c)
    print(f"[Node C Published] {info_c['title']} -> {info_c['url']}")

    print("\n[+] 全部三篇飞书知识库文档已成功发布并读回校验零失败！")

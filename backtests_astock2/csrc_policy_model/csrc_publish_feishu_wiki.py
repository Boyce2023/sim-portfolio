#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Publish the CSRC & High-Level Speeches 144-Factor Study + Wu Qing Latest Speech Decoding
into Feishu Wiki space 7700231295393107208 (A股策略与回测) as brand-new nodes (never touching existing docs).
Enforces strict plain-Chinese punctuation & zero banned clichés gate.
"""
import os, sys, re, json, time, fcntl, subprocess
from bs4 import BeautifulSoup, NavigableString, Doctype, Comment

exec(open("/Users/huaichuaibeimeng/claude-projects/股票研究 Equity Research/_tools/html2feishu.py", "r", encoding="utf-8").read(), globals())

BASE = "https://open.feishu.cn"
SPACE_ID = "7700231295393107208"  # A股策略与回测
OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/output/csrc_policy_100factors_20261114"
HTML_DIR = os.path.join(OUT_DIR, "feishu_html")
MANIFEST_PATH = os.path.join(OUT_DIR, "feishu_csrc_wiki_manifest.json")
LOCK_PATH = "/tmp/.feishu_csrc_144_pub.lock"

BANNED = [
    "星辰大海", "皇冠明珠", "飞轮", "底座", "赋能", "闭环", "引擎", "跃迁", "重塑", "颠覆",
    "范式", "生态", "矩阵", "全景", "硬核", "标尺", "试金石", "胜负手", "王牌",
    "钩子", "年金", "天花板", "破局", "抓手", "撬动", "罕见", "极其", "绝不", "完美",
    "铁证", "铁律", "暗礁", "命门", "底牌", "法典", "死限", "拆穿", "十战十胜", "干干净净",
    "圣经", "贵族", "宪法", "D8", "D15", "SSOT", "绞肉机", "法医"
]


def load_manifest():
    if os.path.exists(MANIFEST_PATH):
        return json.load(open(MANIFEST_PATH, "r", encoding="utf-8"))
    return {"space_id": SPACE_ID, "nodes": {}}


def save_manifest(m):
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)


def ensure_node(key: str, title: str, parent_node_token: str = None) -> dict:
    m = load_manifest()
    if key in m["nodes"] and m["nodes"][key].get("obj_token"):
        info = m["nodes"][key]
        if info.get("title") != title:
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
        "key": key, "title": title, "node_token": nd["node_token"], "obj_token": nd["obj_token"],
        "parent_node_token": parent_node_token or "", "url": f"https://my.feishu.cn/wiki/{nd['node_token']}"
    }
    m["nodes"][key] = info
    save_manifest(m)
    return info


def sanitize_html(html_path: str) -> int:
    raw = open(html_path, "r", encoding="utf-8").read()
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup.find_all(True):
        if tag.get("class"):
            tag["class"] = [c for c in tag["class"] if c not in CALLOUT]
    REP_MAP = {
        "赋能": "助力", "生态": "环境", "罕见": "少见", "范式": "模式", "闭环": "完整链条",
        "矩阵": "组合表", "全景": "全貌", "硬核": "扎实", "标尺": "参照", "胜负手": "关键点",
        "抓手": "着力点", "撬动": "带动", "重塑": "改变", "引擎": "动力", "底座": "基础",
        "极其": "十分", "绝不": "不会", "完美": "理想", "铁证": "实证", "铁律": "硬规律", "拆穿": "识破",
        "底牌": "真实意图", "年金": "企业养老金", "星辰大海": "广阔空间", "皇冠明珠": "核心资产",
        "飞轮": "正循环", "跃迁": "跨越", "颠覆": "改写", "试金石": "检验标准", "王牌": "核心工具",
        "钩子": "触发点", "天花板": "上限", "破局": "破题", "暗礁": "隐患", "命门": "要害",
        "法典": "规则汇编", "死限": "硬边界", "十战十胜": "高胜率", "干干净净": "清清楚楚",
        "圣经": "手册", "贵族": "高分红龙头", "宪法": "根本准则", "D8": "估值纪律", "D15": "回测防伪",
        "SSOT": "唯一总账", "绞肉机": "亏损区", "法医": "逐笔复盘"
    }
    for elem in soup.find_all(string=True):
        if isinstance(elem, (Doctype, Comment)): elem.extract(); continue
        if elem.parent and elem.parent.name in ("style", "script"): continue
        txt = str(elem)
        for k, v in REP_MAP.items():
            txt = txt.replace(k, v)
        txt = txt.replace("——", "，").replace("—", "，").replace("–", "至").replace("→", "至")
        txt = re.sub(r"(?<![A-Za-z0-9])-(\d+(?:\.\d+)?%?)", r"跌\1", txt)
        txt = re.sub(r"\+(\d+(?:\.\d+)?%?)", r"涨\1", txt)
        txt = re.sub(r"(\d)-(\d)", r"\1至\2", txt).replace("-", " ").replace("！", "。").replace("!", "。").replace("**", "")
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
    if doc_id in ("HexPdpU4uowtfZx1IIscgIKrnce", "U5rTdmjqloC00xx2JBfcTRxEnbg"):
        raise RuntimeError("FATAL SAFETY BLOCK!")
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
    time.sleep(0.25)
    tok_s = _shared_tok()
    out = subprocess.check_output([
        "curl", "-sS", "-X", "POST", f"{BASE}/open-apis/drive/v1/medias/upload_all",
        "-H", f"Authorization: Bearer {tok_s}", "-F", f"file_name={os.path.basename(png_path)}",
        "-F", "parent_type=docx_image", "-F", f"parent_node={blk_id}", "-F", f"size={os.path.getsize(png_path)}",
        "-F", f"file=@{png_path};type=image/png"
    ], timeout=120).decode("utf-8")
    r2 = json.loads(out)
    if r2.get("code") != 0: return False
    time.sleep(0.25)
    r3 = api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{blk_id}", {"replace_image": {"token": r2["data"]["file_token"]}}, "PATCH")
    return r3.get("code") == 0


def publish_one(key: str, title: str, html_path: str, parent_key: str = None):
    sanitize_html(html_path)
    p_tok = load_manifest()["nodes"][parent_key]["node_token"] if parent_key else None
    info = ensure_node(key, title, p_tok)
    doc_id = info["obj_token"]
    lock_fd = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        clear_doc_all(doc_id)
        raw_html = open(html_path, "r", encoding="utf-8").read()
        imgs = []
        def repl_img(m):
            imgs.append(m.group(1).strip())
            return f"<p>@@IMG{len(imgs)-1}@@</p>"
        tmp_mod = f"/tmp/mod_csrc_{doc_id}.html"
        open(tmp_mod, "w", encoding="utf-8").write(re.sub(r'<img[^>]+src="([^"]+)"[^>]*/?>', repl_img, raw_html, flags=re.S | re.I))
        items = split_big_tables(sanitize_callouts(parse2(tmp_mod)))
        buf, done, fail, img_ok = [], 0, 0, 0

        def flush():
            nonlocal buf, done, fail
            for i in range(0, len(buf), 40):
                ch = buf[i:i+40]
                r = api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children", {"children": ch, "index": -1}, "POST")
                if r.get("code") == 0:
                    done += len(ch)
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
                flush()
                d = Desc()
                root = d.add(it)
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
        if fail > 0 or len(rb) < 150:
            raise RuntimeError(f"Failed verify {title}: fail={fail}, rb={len(rb)}")
        m = load_manifest()
        m["nodes"][key].update({"done_blocks": done, "images_ok": img_ok, "readback_chars": len(rb)})
        save_manifest(m)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    publish_one("csrc_main", "20261114 证监会与高层发言预见性144因子回测及吴清最新讲话拆解", f"{HTML_DIR}/00_main_csrc_report.html", None)
    publish_one("csrc_sub1_144", "01 细拆144个颗粒度因子全周期与单仓轮动总账本", f"{HTML_DIR}/01_full_144_factors_ledger.html", "csrc_main")
    publish_one("csrc_sub2_grids", "02 六维左右打磨参数试错表与七任主席横向成绩单", f"{HTML_DIR}/02_perturbation_grids_and_chairmen.html", "csrc_main")
    publish_one("csrc_sub3_wuqing", "03 吴清2026年10月至11月最新演讲逐句密码与未来60天政策推演", f"{HTML_DIR}/03_wuqing_latest_decode.html", "csrc_main")
    print("ALL 4 FEISHU WIKI DOCS PUBLISHED SUCCESSFULLY")

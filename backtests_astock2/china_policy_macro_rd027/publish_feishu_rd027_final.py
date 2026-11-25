"""RD027 Wave 3 final report builder & Feishu V19.1 Wiki publisher."""
import fcntl
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path("/Users/huaichuaibeimeng/claude-projects")
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from rd027_final_builder import (  # noqa: E402
    OUT_BASE, load_all_rd027_data, validate_blocks, render_markdown, render_html, BANNED_WORDS, BAD_PUNCT_RE
)
from rd027_final_content import build_part1_blocks  # noqa: E402
from rd027_final_content_part2 import build_part2_blocks  # noqa: E402

DOC_KEY = "rd027_china_policy_macro_final"
DOC_TITLE = "20261125 中国宏观政策水池全景与千因子系统性实证（RD027终版）"
BASE = "https://open.feishu.cn"
SPACE_ID = "7700231295393107208"
POLICY_PARENT_NODE = "YSDKwKuQciRq0ekDVw9c5LnRnDe"
MD_OUT = OUT_BASE / "RD027_CHINA_POLICY_MACRO_FINAL_20261125.md"
HTML_OUT = OUT_BASE / "wave3_critic/rd027_final_feishu.html"
MANIFEST_PATH = OUT_BASE / "feishu_rd027_wiki_manifest.json"
LOCK_PATH = "/tmp/.feishu_rd027_pub.lock"

exec(open(ROOT / "股票研究 Equity Research/_tools/html2feishu.py", "r", encoding="utf-8").read(), globals())


def load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return {"space_id": SPACE_ID, "parent_node_token": POLICY_PARENT_NODE, "nodes": {}}


def save_manifest(m: dict) -> None:
    MANIFEST_PATH.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_node(key: str, title: str, parent_node_token: str) -> dict:
    m = load_manifest()
    if key in m["nodes"] and m["nodes"][key].get("obj_token"):
        info = m["nodes"][key]
        if info.get("title") != title:
            api(f"{BASE}/open-apis/wiki/v2/spaces/{SPACE_ID}/nodes/{info['node_token']}/update_title", {"title": title}, "POST")
            info["title"] = title
            save_manifest(m)
        return info
    # Check existing children on Feishu to avoid duplicates
    r_list = api(f"{BASE}/open-apis/wiki/v2/spaces/{SPACE_ID}/nodes?parent_node_token={parent_node_token}&page_size=50", method="GET")
    for it in (r_list.get("data") or {}).get("items", []):
        if it.get("title") == title:
            info = {
                "key": key, "title": title, "node_token": it["node_token"],
                "obj_token": it["obj_token"], "parent_node_token": parent_node_token,
                "url": f"https://my.feishu.cn/wiki/{it['node_token']}",
            }
            m["nodes"][key] = info
            save_manifest(m)
            return info
    payload = {"obj_type": "docx", "node_type": "origin", "title": title, "parent_node_token": parent_node_token}
    r = api(f"{BASE}/open-apis/wiki/v2/spaces/{SPACE_ID}/nodes", payload, "POST")
    if r.get("code") != 0:
        raise RuntimeError(f"Failed creating node {key}: {r}")
    nd = r["data"]["node"]
    info = {
        "key": key, "title": title, "node_token": nd["node_token"], "obj_token": nd["obj_token"],
        "parent_node_token": parent_node_token, "url": f"https://my.feishu.cn/wiki/{nd['node_token']}",
    }
    m["nodes"][key] = info
    save_manifest(m)
    return info


def clear_doc_all(doc_id: str) -> bool:
    for _ in range(40):
        r = api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children?page_size=500", method="GET")
        if r.get("code") != 0:
            break
        n = len(r["data"].get("items") or [])
        if n == 0:
            return True
        api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children/batch_delete", {"start_index": 0, "end_index": min(n, 150)}, "DELETE")
        time.sleep(0.25)
    return False


def publish_to_feishu(html_path: str) -> dict:
    info = ensure_node(DOC_KEY, DOC_TITLE, POLICY_PARENT_NODE)
    doc_id = info["obj_token"]
    with open(LOCK_PATH, "w") as lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        clear_doc_all(doc_id)
        parsed = split_big_tables(sanitize_callouts(parse2(html_path)))
        first_tbl_idx = next((idx for idx, it in enumerate(parsed) if it.get("t") == "table"), len(parsed))
        assert first_tbl_idx >= 6, f"Only {first_tbl_idx} blocks before first table (<6)"
        items = []
        for it in parsed:
            if it.get("t") == "table":
                items.append({"t": "empty_p"})
            items.append(it)
        bad_hits = check_human_prose(items)
        if bad_hits:
            raise RuntimeError(f"Human prose gate hit: {bad_hits[:5]}")

        buf, done, fail = [], 0, 0

        def flush():
            nonlocal buf, done, fail
            for i in range(0, len(buf), 40):
                ch = buf[i:i + 40]
                r = api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children", {"children": ch, "index": -1}, "POST")
                if r.get("code") == 0:
                    done += len(ch)
                else:
                    for b in ch:
                        r2 = api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children", {"children": [b], "index": -1}, "POST")
                        done, fail = (done + 1, fail) if r2.get("code") == 0 else (done, fail + 1)
                time.sleep(0.25)
            buf = []

        for it in items:
            if it.get("t") in ("table", "callout"):
                flush()
                d = Desc()
                root = d.add(it)
                rt = api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/descendant", {"children_id": [root], "descendants": d.d})
                done, fail = (done + 1, fail) if rt.get("code") == 0 else (done, fail + 1)
                time.sleep(0.35)
            else:
                bk = simple(it)
                if bk:
                    buf.append(bk)
        flush()

        rb = api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/raw_content", method="GET").get("data", {}).get("content", "")
        print(f"[FEISHU OK] title={DOC_TITLE}")
        print(f"[FEISHU URL] {info['url']}")
        print(f"[FEISHU VERIFY] blocks_before_first_table={first_tbl_idx} done_blocks={done} fail={fail} readback_chars={len(rb)}")
        if fail > 0 or len(rb) < 2500:
            raise RuntimeError(f"Publish verify failed: fail={fail}, readback={len(rb)}")
        m = load_manifest()
        m["nodes"][DOC_KEY].update({"done_blocks": done, "readback_chars": len(rb), "blocks_before_first_table": first_tbl_idx})
        save_manifest(m)
        return m["nodes"][DOC_KEY]


def main():
    d = load_all_rd027_data()
    blocks = build_part1_blocks(d) + build_part2_blocks(d)
    validate_blocks(blocks)
    md_text = render_markdown(blocks)
    html_text = render_html(blocks)
    MD_OUT.parent.mkdir(parents=True, exist_ok=True)
    HTML_OUT.parent.mkdir(parents=True, exist_ok=True)
    MD_OUT.write_text(md_text, encoding="utf-8")
    HTML_OUT.write_text(html_text, encoding="utf-8")
    print(f"[LOCAL OK] md={MD_OUT} ({len(md_text)} chars) html={HTML_OUT} ({len(html_text)} chars)")
    publish_to_feishu(str(HTML_OUT))


if __name__ == "__main__":
    main()

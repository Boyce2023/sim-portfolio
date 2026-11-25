"""Publish China Macro & Policy 5 sub-docs + parent overview to Feishu Macro Research Wiki."""
import fcntl
import html as htmllib
import json
import re
import sys
import time
from pathlib import Path

assert "yfinance" not in sys.modules, "D12 violation"

ROOT = Path("/Users/huaichuaibeimeng/claude-projects")
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from rd027_final_builder import OUT_BASE, BANNED_WORDS, LOAN11, BAD_PUNCT_RE, load_all_rd027_data  # noqa: E402
from wiki_cn_policy_docs_part1 import build_doc1_waterpool, build_doc2_meetings_bottoms, build_doc3_traffic_lights  # noqa: E402
from wiki_cn_policy_docs_part2 import build_doc4_national_team, build_doc5_polymarket, build_parent_overview  # noqa: E402

BASE = "https://open.feishu.cn"
SPACE_ID = "7711983159496920097"
PARENT_NODE_TOKEN = "Lm2OweGGqi3aPIktIxwc0lTtnic"
PARENT_OBJ_TOKEN = "Id3ydW6cUolfklxUZK4cFxDynjc"
HTML_DIR = OUT_BASE / "wiki_cn_policy_html"
MANIFEST_PATH = OUT_BASE / "feishu_macro_wiki_cn_policy_manifest.json"
LOCK_PATH = "/tmp/.feishu_macro_cn_policy.lock"
NT_V3_JSON = ROOT / "output/csrc_policy_100factors_20261114/national_team/v3_scorecard_backtest_audit.json"
NT_MANTRA_JSON = ROOT / "sim-portfolio/backtests_astock2/nt_mantra_backtest_20261120/nt_mantra_backtest_result.json"

exec(open(ROOT / "股票研究 Equity Research/_tools/html2feishu.py", "r", encoding="utf-8").read(), globals())


def load_all_sources() -> dict:
    d = load_all_rd027_data()
    d["v3"] = json.loads(NT_V3_JSON.read_text(encoding="utf-8"))
    d["ntm"] = json.loads(NT_MANTRA_JSON.read_text(encoding="utf-8"))
    return d


def validate_wiki_blocks(blocks: list[dict], min_chars: int = 1200) -> int:
    body_texts = []
    first_tbl_idx = next((i for i, b in enumerate(blocks) if b["t"] == "table"), len(blocks))
    assert first_tbl_idx >= 6, f"Only {first_tbl_idx} blocks before first table (<6)"
    for b in blocks:
        t = b["t"]
        if t == "table":
            for r_idx, row in enumerate([b["headers"]] + b["rows"]):
                assert len(row) == len(b["headers"]), f"Column mismatch row {r_idx}: {row}"
                for c in row:
                    s = str(c)
                    assert len(s) <= 40 or s.startswith("https://"), f"Cell >40 chars ({len(s)}): {s}"
                    if not s.startswith("https://"):
                        body_texts.append(s)
        elif t == "ul":
            body_texts.extend(b["items"])
        elif t != "h1":
            body_texts.append(b["text"])
    joined = "\n".join(body_texts)
    banned_hits = [w for w in BANNED_WORDS if w in joined]
    assert not banned_hits, f"Banned words: {banned_hits}"
    bad_p = BAD_PUNCT_RE.findall(joined)
    assert not bad_p, f"Bad punctuation: {bad_p[:5]}"
    for w in LOAN11:
        hits = re.findall(rf"\b{w}\b(?!（)", joined)
        assert not hits, f"Loanword '{w}' missing Chinese gloss: {hits}"
    assert len(joined) >= min_chars, f"Body too short: {len(joined)} < {min_chars}"
    return len(joined)


def render_clean_html(blocks: list[dict]) -> str:
    parts = ["<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'></head><body>"]
    esc = lambda s: htmllib.escape(str(s))
    for b in blocks:
        t = b["t"]
        if t == "h1":
            parts.append(f"<h1>{esc(b['text'])}</h1>")
        elif t == "h2":
            parts.append(f"<h2>{esc(b['text'])}</h2>")
        elif t == "mark_p":
            parts.append(f"<p><mark>{esc(b['text'])}</mark></p>")
        elif t == "p":
            parts.append(f"<p>{esc(b['text'])}</p>")
        elif t == "ul":
            parts.append("<ul>" + "".join(f"<li>{esc(it)}</li>" for it in b["items"]) + "</ul>")
        elif t == "table":
            ths = "".join(f"<th>{esc(h)}</th>" for h in b["headers"])
            trs = "".join("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in r) + "</tr>" for r in b["rows"])
            parts.append(f"<table><thead><tr>{ths}</tr></thead><tbody>{trs}</tbody></table>")
    parts.append("</body></html>")
    return "\n".join(parts)


def check_parent_title_no_prefix() -> str:
    r = api(f"{BASE}/open-apis/wiki/v2/spaces/get_node?token={PARENT_NODE_TOKEN}", method="GET")
    cur_title = r["data"]["node"]["title"]
    if re.match(r"^\d+\s*", cur_title):
        new_title = "中国宏观与政策"
        api(f"{BASE}/open-apis/wiki/v2/spaces/{SPACE_ID}/nodes/{PARENT_NODE_TOKEN}/update_title", {"title": new_title}, "POST")
        return new_title
    return cur_title


def ensure_child_node(title: str) -> dict:
    r_list = api(f"{BASE}/open-apis/wiki/v2/spaces/{SPACE_ID}/nodes?parent_node_token={PARENT_NODE_TOKEN}&page_size=50", method="GET")
    for it in (r_list.get("data") or {}).get("items", []):
        if it.get("title") == title:
            return {"title": title, "node_token": it["node_token"], "obj_token": it["obj_token"], "url": f"https://my.feishu.cn/wiki/{it['node_token']}"}
    r = api(f"{BASE}/open-apis/wiki/v2/spaces/{SPACE_ID}/nodes", {"obj_type": "docx", "node_type": "origin", "title": title, "parent_node_token": PARENT_NODE_TOKEN}, "POST")
    assert r.get("code") == 0, f"Create node failed for {title}: {r}"
    nd = r["data"]["node"]
    time.sleep(0.35)
    return {"title": title, "node_token": nd["node_token"], "obj_token": nd["obj_token"], "url": f"https://my.feishu.cn/wiki/{nd['node_token']}"}


def clear_doc_all(doc_id: str) -> None:
    for _ in range(30):
        r = api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children?page_size=500", method="GET")
        n = len((r.get("data") or {}).get("items") or [])
        if n == 0:
            return
        api(f"{BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children/batch_delete", {"start_index": 0, "end_index": min(n, 150)}, "DELETE")
        time.sleep(0.25)


def publish_doc(doc_id: str, html_path: Path, min_readback: int = 1200) -> dict:
    clear_doc_all(doc_id)
    parsed = split_big_tables(sanitize_callouts(parse2(str(html_path))))
    first_tbl = next((i for i, it in enumerate(parsed) if it.get("t") == "table"), len(parsed))
    assert first_tbl >= 6, f"Only {first_tbl} blocks before first table"
    items = []
    for it in parsed:
        if it.get("t") == "table":
            items.append({"t": "empty_p"})
        items.append(it)
    bad_hits = check_human_prose(items)
    assert not bad_hits, f"Human prose gate hit: {bad_hits[:5]}"

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
    assert fail == 0 and len(rb) >= min_readback, f"Verify failed: fail={fail}, len={len(rb)}"
    return {"done_blocks": done, "fail": fail, "readback_chars": len(rb), "blocks_before_first_table": first_tbl}


def main():
    d = load_all_sources()
    HTML_DIR.mkdir(parents=True, exist_ok=True)
    specs = [
        ("水池与千因子", build_doc1_waterpool(d)),
        ("顶层会议与真假底", build_doc2_meetings_bottoms(d)),
        ("产业红绿灯", build_doc3_traffic_lights(d)),
        ("国家队打分卡", build_doc4_national_team(d)),
        ("政策概率预测", build_doc5_polymarket(d)),
    ]
    for title, blocks in specs:
        assert 4 <= len(title) <= 8, f"Title length violation: {title}"
        n_chars = validate_wiki_blocks(blocks, min_chars=1200)
        (HTML_DIR / f"{title}.html").write_text(render_clean_html(blocks), encoding="utf-8")
        print(f"[VALIDATED] {title}: local_chars={n_chars}")

    with open(LOCK_PATH, "w") as lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        parent_title = check_parent_title_no_prefix()
        results = []
        for idx, (title, _) in enumerate(specs, 1):
            node = ensure_child_node(title)
            ver = publish_doc(node["obj_token"], HTML_DIR / f"{title}.html", min_readback=1200)
            node.update(ver)
            results.append(node)
            print(f"[PUBLISHED {idx}/5] {title} | {node['url']} | chars={ver['readback_chars']} | fail={ver['fail']}")

        p_blocks = build_parent_overview(results)
        validate_wiki_blocks(p_blocks, min_chars=450)
        p_html = HTML_DIR / "中国宏观_overview.html"
        p_html.write_text(render_clean_html(p_blocks), encoding="utf-8")
        p_ver = publish_doc(PARENT_OBJ_TOKEN, p_html, min_readback=450)
        print(f"[PARENT OK] {parent_title} | https://my.feishu.cn/wiki/{PARENT_NODE_TOKEN} | chars={p_ver['readback_chars']}")

        manifest = {
            "space_id": SPACE_ID,
            "parent": {"title": parent_title, "node_token": PARENT_NODE_TOKEN, "obj_token": PARENT_OBJ_TOKEN, "url": f"https://my.feishu.cn/wiki/{PARENT_NODE_TOKEN}", **p_ver},
            "children": results,
        }
        MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[MANIFEST] {MANIFEST_PATH}")


if __name__ == "__main__":
    main()

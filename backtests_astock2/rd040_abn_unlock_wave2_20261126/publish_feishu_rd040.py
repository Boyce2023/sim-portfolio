#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Publish RD040 report to Falsified Tombstone (QiDewdTkJiquokkbbo6cWr3Fn6f) & safely update Hub."""
import argparse, fcntl, json, os, re, sys, time

assert "yfinance" not in sys.modules
sys.dont_write_bytecode = True

RD040_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd040_abn_unlock_wave2_20261126"
FEISHU_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/feishu_master_docs_20261116"
for p in (RD040_DIR, FEISHU_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import rd040_charts
import rd040_feishu_payload as payload_mod

PARENT_INVALID_NODE = "QiDewdTkJiquokkbbo6cWr3Fn6f"
HUB_INVALID_DOC = "ZTaudjSqtoaj71xTPSLciMcdnLb"


def _write_doc(s6, doc_id: str, payload: dict) -> tuple[int, int]:
    if doc_id in s6.PROTECTED_DOCS or doc_id == HUB_INVALID_DOC:
        raise RuntimeError(f"SAFETY BLOCK: {doc_id}")
    s6.clear_doc_all(doc_id)
    done = fail = 0
    for i in range(0, len(payload["blocks"]), 40):
        ch = payload["blocks"][i:i + 40]
        r = s6.api(f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children", {"children": ch, "index": -1}, "POST")
        if r.get("code") == 0:
            done += len(ch)
        else:
            for b in ch:
                r2 = s6.api(f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children", {"children": [b], "index": -1}, "POST")
                done += (1 if r2.get("code") == 0 else 0)
                fail += (0 if r2.get("code") == 0 else 1)
        time.sleep(0.25)

    for t_title, t_rows, chart_after in payload["sections_tables"]:
        tb = {"block_type": 2, "text": {"elements": [{"text_run": {"content": t_title, "text_element_style": {"bold": True}}}], "style": {"align": 1, "folded": False}}}
        rt = s6.api(f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children", {"children": [tb], "index": -1}, "POST")
        done += (1 if rt.get("code") == 0 else 0); fail += (0 if rt.get("code") == 0 else 1)
        time.sleep(0.25)
        d = s6.Desc()
        root = d.add({"t": "table", "rows": t_rows})
        rtb = s6.api(f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/descendant", {"children_id": [root], "descendants": d.d})
        done += (1 if rtb.get("code") == 0 else 0); fail += (0 if rtb.get("code") == 0 else 1)
        time.sleep(0.35)
        if chart_after and os.path.exists(chart_after):
            ok = s6.insert_image_block(doc_id, chart_after)
            done += (1 if ok else 0); fail += (0 if ok else 1)
            time.sleep(0.3)
    return done, fail


def _extract_hub(items: list):
    by_id = {b["block_id"]: b for b in items}
    tb = [b for b in items if b["block_type"] == 31][0]
    rn, cn = tb["table"]["property"]["row_size"], tb["table"]["property"]["column_size"]
    texts, cids = [], []
    for r_i in range(rn):
        rt, rc = [], []
        for c_i in range(cn):
            cid = tb["table"]["cells"][r_i * cn + c_i]
            txt = "".join(el.get("text_run", {}).get("content", "") for ch in by_id[cid].get("children", []) for el in by_id.get(ch, {}).get("text", {}).get("elements", []))
            rt.append(txt.strip()); rc.append(cid)
        texts.append(rt); cids.append(rc)
    return tb, texts, cids, by_id


def update_invalid_hub_incremental(s6, new_row: list[str]) -> dict:
    res = s6.api(f"{s6.BASE}/open-apis/docx/v1/documents/{HUB_INVALID_DOC}/blocks?page_size=500", method="GET")
    tb, rows_txt, cids, by_id = _extract_hub(res["data"]["items"])
    orig_titles = [r[0] for r in rows_txt[1:]]

    target_idx = next((i for i in range(1, len(rows_txt)) if rows_txt[i][0] == new_row[0]), None)
    if target_idx is None:
        r_ins = s6.api(f"{s6.BASE}/open-apis/docx/v1/documents/{HUB_INVALID_DOC}/blocks/{tb['block_id']}", {"insert_table_row": {"row_index": -1}}, "PATCH")
        if r_ins.get("code") != 0:
            raise RuntimeError(f"Hub insert row failed: {r_ins}")
        time.sleep(0.35)
        res2 = s6.api(f"{s6.BASE}/open-apis/docx/v1/documents/{HUB_INVALID_DOC}/blocks?page_size=500", method="GET")
        tb, rows_txt, cids, by_id = _extract_hub(res2["data"]["items"])
        target_idx = len(rows_txt) - 1

    for c_i, val in enumerate(new_row):
        cb = by_id[cids[target_idx][c_i]]
        kids = cb.get("children", [])
        if kids:
            r = s6.api(f"{s6.BASE}/open-apis/docx/v1/documents/{HUB_INVALID_DOC}/blocks/{kids[0]}", {"update_text_elements": {"elements": [{"text_run": {"content": val, "text_element_style": {}}}]}}, "PATCH")
        else:
            r = s6.api(f"{s6.BASE}/open-apis/docx/v1/documents/{HUB_INVALID_DOC}/blocks/{cids[target_idx][c_i]}/children", {"children": [{"block_type": 2, "text": {"elements": [{"text_run": {"content": val, "text_element_style": {}}}], "style": {"align": 1, "folded": False}}}], "index": -1}, "POST")
        if r.get("code") != 0:
            raise RuntimeError(f"Hub cell write failed: {r}")
        time.sleep(0.15)

    res_fin = s6.api(f"{s6.BASE}/open-apis/docx/v1/documents/{HUB_INVALID_DOC}/blocks?page_size=500", method="GET")
    items_fin = res_fin["data"]["items"]
    _, rows_fin, _, _ = _extract_hub(items_fin)
    n_tot = len(rows_fin) - 1
    for b in items_fin:
        if b.get("block_type") == 2 and b.get("parent_id") == HUB_INVALID_DOC:
            txt = "".join(el.get("text_run", {}).get("content", "") for el in b.get("text", {}).get("elements", []))
            if "全量索引表" in txt:
                hdr = f"证伪回测与避坑墓碑全量索引表（共 {n_tot} 项）"
                if txt.strip() != hdr:
                    s6.api(f"{s6.BASE}/open-apis/docx/v1/documents/{HUB_INVALID_DOC}/blocks/{b['block_id']}", {"update_text_elements": {"elements": [{"text_run": {"content": hdr, "text_element_style": {"bold": True}}}]}}, "PATCH")
                break
    fin_titles = [r[0] for r in rows_fin[1:]]
    for ot in orig_titles + [new_row[0]]:
        if ot not in fin_titles:
            raise RuntimeError(f"Hub post-check missing: {ot}")
    return {"hub_doc_id": HUB_INVALID_DOC, "total_rows": n_tot, "new_row": rows_fin[target_idx]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    c1, c2 = rd040_charts.build_chart1(), rd040_charts.build_chart2()
    import step6_upgrade_3strategies_20261117 as s6
    import step9_sync_v191_exits_20261118 as s9

    payload = payload_mod.build_rd040_payload(c1, c2)
    payload_mod.validate_strict(payload, s6, s9)
    if args.dry_run:
        return

    lock_f = open(s6.LOCK_PATH, "w")
    fcntl.flock(lock_f, fcntl.LOCK_EX)
    try:
        doc_id, node_tok = s9.find_or_create_child_node(PARENT_INVALID_NODE, payload["title"])
        payload["doc_id"] = doc_id
        done, fail = _write_doc(s6, doc_id, payload)
        assert fail == 0, f"Write failed: {fail}"
        time.sleep(0.6)
        v = s9.verify_document_v191(doc_id, payload["title"], expected_tables_count=len(payload["tables"]), has_img=True)
        assert v["images_count"] >= 2, f"Missing charts: {v}"

        raw_txt = s6.api(f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/raw_content", method="GET")["data"]["content"]
        for tok in payload_mod.FORBIDDEN_TOKENS:
            if re.fullmatch(r"[A-Za-z0-9\-]+", tok):
                assert not re.search(rf"(?<![A-Za-z0-9]){re.escape(tok)}(?![A-Za-z0-9])", raw_txt), f"Online jargon: {tok}"
            else:
                assert tok not in raw_txt, f"Online jargon: {tok}"

        hub_res = update_invalid_hub_incremental(s6, payload_mod.HUB_ROW)
        wiki_url = f"https://my.feishu.cn/wiki/{node_tok}"

        mf = json.load(open(s6.MANIFEST_PATH, encoding="utf-8"))
        mf.setdefault("nodes", {})["rd040_abn_unlock_wave2"] = {
            "title": payload["title"], "node_token": node_tok, "obj_token": doc_id,
            "parent_node_token": PARENT_INVALID_NODE, "wiki_url": wiki_url, "published_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        json.dump(mf, open(s6.MANIFEST_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

        res = {"title": payload["title"], "doc_id": doc_id, "node_token": node_tok, "wiki_url": wiki_url,
               "verify": v, "hub_update": hub_res, "online_raw_chars": len(raw_txt)}
        with open(f"{RD040_DIR}/feishu_publish_result.json", "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
        print(json.dumps(res, ensure_ascii=False, indent=2))
    finally:
        fcntl.flock(lock_f, fcntl.LOCK_UN)
        lock_f.close()


if __name__ == "__main__":
    main()

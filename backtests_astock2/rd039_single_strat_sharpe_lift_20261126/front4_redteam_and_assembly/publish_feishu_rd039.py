#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Publish 《单策略夏普提纯实证》 to Feishu Wiki and incrementally update Hub Index Row 18."""

import argparse
import fcntl
import json
import os
import sys
import time

FEISHU_MASTER_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/feishu_master_docs_20261116"
THIS_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd039_single_strat_sharpe_lift_20261126/front4_redteam_and_assembly"
for p in (FEISHU_MASTER_DIR, THIS_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import step6_upgrade_3strategies_20261117 as s6
import step9_sync_v191_exits_20261118 as s9
import rd039_charts as ch39
import rd039_feishu_payload as pl39


def _write_doc_with_interleaved_charts(doc_id: str, blocks: list, tables: list, charts: list):
    if doc_id in s6.PROTECTED_DOCS or doc_id == pl39.HUB_VALID_DOC:
        raise RuntimeError(f"FATAL: refuse clear_doc_all on protected doc {doc_id}")
    s6.clear_doc_all(doc_id)

    done, fail = 0, 0
    for i in range(0, len(blocks), 40):
        chunk = blocks[i : i + 40]
        r = s6.api(
            f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children",
            {"children": chunk, "index": -1},
            "POST",
        )
        if r.get("code") == 0:
            done += len(chunk)
        else:
            for b in chunk:
                r2 = s6.api(
                    f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children",
                    {"children": [b], "index": -1},
                    "POST",
                )
                if r2.get("code") == 0:
                    done += 1
                else:
                    fail += 1
                    print("  [!] block write fail:", r2)
        time.sleep(0.25)

    for idx_t, (t_title, t_rows) in enumerate(tables):
        t_title_block = {
            "block_type": 2,
            "text": {"elements": [{"text_run": {"content": t_title, "text_element_style": {}}}], "style": {"align": 1, "folded": False}},
        }
        r_t = s6.api(
            f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children",
            {"children": [t_title_block], "index": -1},
            "POST",
        )
        if r_t.get("code") == 0:
            done += 1
        else:
            fail += 1
        time.sleep(0.25)

        if idx_t == 0 and len(charts) >= 1:
            if s6.insert_image_block(doc_id, charts[0]):
                done += 1
            else:
                fail += 1
        elif idx_t == 2 and len(charts) >= 2:
            if s6.insert_image_block(doc_id, charts[1]):
                done += 1
            else:
                fail += 1

        d = s6.Desc()
        root = d.add({"t": "table", "rows": t_rows})
        rt = s6.api(
            f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/descendant",
            {"children_id": [root], "descendants": d.d},
        )
        if rt.get("code") == 0:
            done += 1
        else:
            fail += 1
            print("  [!] table write fail:", rt)
        time.sleep(0.35)

    return done, fail


def update_hub_index_incremental() -> dict:
    """Append row 18 to HUB_VALID_DOC safely WITHOUT touching any of the 17 existing rows."""
    hub_doc = pl39.HUB_VALID_DOC
    r_raw = s6.api(f"{s6.BASE}/open-apis/docx/v1/documents/{hub_doc}/raw_content", method="GET")
    raw_txt = r_raw.get("data", {}).get("content", "")
    for t in pl39.HUB_EXISTING_TITLES:
        if t not in raw_txt:
            raise RuntimeError(f"Hub safety check failed: missing existing title '{t}'")

    if pl39.TITLE in raw_txt:
        print(f"  [*] Hub already contains 《{pl39.TITLE}》; skipping duplicate row insert.")
        r_blk = s6.api(f"{s6.BASE}/open-apis/docx/v1/documents/{hub_doc}/blocks?page_size=100", method="GET")
        tbl = [b for b in r_blk.get("data", {}).get("items", []) if b.get("block_type") == 31][0]
        return {"status": "already_present", "row_size": tbl["table"]["property"]["row_size"]}

    r_blk = s6.api(f"{s6.BASE}/open-apis/docx/v1/documents/{hub_doc}/blocks?page_size=100", method="GET")
    items = r_blk.get("data", {}).get("items", [])
    heading_blocks = [
        b for b in items
        if b.get("block_type") == 2 and "有效回测与可用规律全量索引表" in "".join(
            e.get("text_run", {}).get("content", "") for e in b["text"]["elements"]
        )
    ]
    tbl_blocks = [b for b in items if b.get("block_type") == 31]
    assert len(heading_blocks) == 1 and len(tbl_blocks) == 1, f"Unexpected hub structure: h={len(heading_blocks)} t={len(tbl_blocks)}"

    tbl_b = tbl_blocks[0]
    tbl_id = tbl_b["block_id"]
    orig_rows = tbl_b["table"]["property"]["row_size"]
    assert orig_rows == 18, f"Expected 18 rows (1 header + 17 existing), got {orig_rows}"

    # Insert 1 new row at end (row_index=-1)
    r_ins = s6.api(
        f"{s6.BASE}/open-apis/docx/v1/documents/{hub_doc}/blocks/{tbl_id}",
        {"insert_table_row": {"row_index": -1}},
        "PATCH",
    )
    if r_ins.get("code") != 0:
        raise RuntimeError(f"Hub insert_table_row failed: {r_ins}")

    # Re-fetch table block to get the 4 newly added cell block_ids (last 4 cells)
    r_tbl_after = s6.api(f"{s6.BASE}/open-apis/docx/v1/documents/{hub_doc}/blocks/{tbl_id}", method="GET")
    new_tbl = r_tbl_after["data"]["block"]["table"]
    assert new_tbl["property"]["row_size"] == 19, f"Expected 19 rows after insert, got {new_tbl['property']['row_size']}"
    new_cell_ids = new_tbl["cells"][-4:]

    for cid, cell_runs in zip(new_cell_ids, pl39.HUB_ROW_18):
        r_cell_kids = s6.api(f"{s6.BASE}/open-apis/docx/v1/documents/{hub_doc}/blocks/{cid}/children", method="GET")
        cell_kids = r_cell_kids.get("data", {}).get("items", [])
        if cell_kids:
            p_id = cell_kids[0]["block_id"]
            r_upd = s6.api(
                f"{s6.BASE}/open-apis/docx/v1/documents/{hub_doc}/blocks/{p_id}",
                {"update_text_elements": {"elements": pl39._tr_elements(cell_runs)}},
                "PATCH",
            )
            if r_upd.get("code") != 0:
                raise RuntimeError(f"Hub cell patch failed on {p_id}: {r_upd}")
        else:
            r_add = s6.api(
                f"{s6.BASE}/open-apis/docx/v1/documents/{hub_doc}/blocks/{cid}/children",
                {"children": [{"block_type": 2, "text": {"elements": pl39._tr_elements(cell_runs), "style": {"align": 1}}}], "index": 0},
                "POST",
            )
            if r_add.get("code") != 0:
                raise RuntimeError(f"Hub cell child post failed on {cid}: {r_add}")

    # Update heading block count 17 -> 18
    h_id = heading_blocks[0]["block_id"]
    r_h = s6.api(
        f"{s6.BASE}/open-apis/docx/v1/documents/{hub_doc}/blocks/{h_id}",
        {"update_text_elements": {"elements": pl39._tr_elements([("有效回测与可用规律全量索引表（共 18 项）", {"bold": True})])}},
        "PATCH",
    )
    if r_h.get("code") != 0:
        raise RuntimeError(f"Hub heading patch failed: {r_h}")

    # Verify all 18 titles present online
    time.sleep(1.0)
    r_raw_after = s6.api(f"{s6.BASE}/open-apis/docx/v1/documents/{hub_doc}/raw_content", method="GET")
    raw_after = r_raw_after.get("data", {}).get("content", "")
    for t in pl39.HUB_EXISTING_TITLES + [pl39.TITLE]:
        if t not in raw_after:
            raise RuntimeError(f"Post-update Hub verification missing '{t}'")
    print("  [+] Hub updated safely: 17 existing rows preserved + row 18 appended & verified!")
    return {"status": "appended_row_18", "row_size": 19, "titles_verified": 18}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    ch39.make_charts()
    payload = pl39.build_rd039_payload()
    pl39.validate_rd039_payload_strict(payload)

    if args.dry_run:
        print("\n[Dry-Run PASS] All strict checks passed.")
        return

    lock_fd = open(s6.LOCK_PATH, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        doc_id, node_token = s9.find_or_create_child_node(pl39.PARENT_VALID_NODE, pl39.TITLE)
        print(f"[*] Target Wiki node={node_token} doc_id={doc_id} title=《{pl39.TITLE}》")
        done, fail = _write_doc_with_interleaved_charts(doc_id, payload["blocks"], payload["tables"], payload["charts"])
        if fail > 0:
            raise RuntimeError(f"Write had {fail} failed blocks")
        time.sleep(1.5)

        v_res = s9.verify_document_v191(doc_id, pl39.TITLE, expected_tables_count=len(payload["tables"]), has_img=True)
        assert v_res["images_count"] >= 2, f"Expected >=2 charts, got {v_res['images_count']}"

        # Online banned jargon re-check
        raw_online = s6.api(f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/raw_content", method="GET").get("data", {}).get("content", "")
        for w in pl39.RD039_EXTRA_BANNED:
            if w in raw_online:
                raise RuntimeError(f"Online readback hit banned token '{w}'")

        hub_res = update_hub_index_incremental()
        res = {
            "title": pl39.TITLE,
            "wiki_url": f"https://my.feishu.cn/wiki/{node_token}",
            "node_token": node_token,
            "doc_id": doc_id,
            "write_done": done,
            "write_fail": fail,
            "verify": v_res,
            "hub_update": hub_res,
            "published_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        out_p = f"{THIS_DIR}/feishu_publish_result.json"
        with open(out_p, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
        print(f"\n[LIVE PUBLISH PASS] {res['wiki_url']} | blocks={v_res['blocks_count']} tables={v_res['tables_count']} imgs={v_res['images_count']} | Saved {out_p}")
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    main()

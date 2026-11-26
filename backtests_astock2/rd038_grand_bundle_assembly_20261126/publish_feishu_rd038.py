#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Dry-run validate and publish RD038 pure-Chinese master report + Hub incremental update."""

import argparse
import fcntl
import json
import os
import re
import resource
import sys
import time

assert "yfinance" not in sys.modules, "D12 VIOLATION: yfinance forbidden"
sys.dont_write_bytecode = True

BASE_ASTOCK2 = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2"
RD038_DIR = f"{BASE_ASTOCK2}/rd038_grand_bundle_assembly_20261126"
FEISHU_DOCS_DIR = f"{BASE_ASTOCK2}/feishu_master_docs_20261116"

for p in (RD038_DIR, FEISHU_DOCS_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import rd038_charts
import rd038_feishu_payload as payload_mod

PARENT_VALID_NODE = "OPKUwAqCDibLfRkRE87cd2aCnVc"
HUB_VALID_DOC = "IRxgdlpOUoqfV4xVYYGczGurnyD"
HUB_EXISTING_TITLES = [
    "多因子打分前视镜总阅兵",
    "六策略退化与进化体检",
    "极值商品三圈层十年实证",
    "政策与国家队雷达",
    "跨年大票 V4.0",
    "跨年妖十五年深度回测",
    "暴跌尾盘切高ROE城商行",
    "美股大跌A股低开高走实证",
    "美股对A股传导回归实证",
    "六大商品股期联动十年回测",
    "大哥护盘五句口诀十年实证",
    "A股15年16套投资理论TEI",
    "同高度PK与拉萨席位实证",
    "首板与高标市值悖论实证",
    "连板断层真空日回测",
    "高阶三四因子协同实证",
]


def _peak_rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024), 1)


def _write_doc_with_interleaved_charts(s6, doc_id: str, payload: dict) -> tuple[int, int]:
    """Write blocks, tables, and interleaved PNG charts safely (never touching protected docs)."""
    if doc_id in s6.PROTECTED_DOCS or doc_id == HUB_VALID_DOC:
        raise RuntimeError(f"SAFETY BLOCK: forbidden clear_doc_all on {doc_id}")
    s6.clear_doc_all(doc_id)

    done, fail = 0, 0
    blocks = payload["blocks"]
    for i in range(0, len(blocks), 40):
        ch = blocks[i : i + 40]
        r = s6.api(
            f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children",
            {"children": ch, "index": -1},
            "POST",
        )
        if r.get("code") == 0:
            done += len(ch)
        else:
            for b in ch:
                r2 = s6.api(
                    f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children",
                    {"children": [b], "index": -1},
                    "POST",
                )
                if r2.get("code") == 0:
                    done += 1
                else:
                    fail += 1
                    print("  [!] 写入单块失败:", r2)
        time.sleep(0.25)

    for t_title, t_rows, chart_after in payload["sections_tables"]:
        t_blk = {
            "block_type": 2,
            "text": {
                "elements": [{"text_run": {"content": t_title, "text_element_style": {"bold": True}}}],
                "style": {"align": 1, "folded": False},
            },
        }
        rt = s6.api(
            f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children",
            {"children": [t_blk], "index": -1},
            "POST",
        )
        if rt.get("code") == 0:
            done += 1
        else:
            fail += 1
            print("  [!] 表格标题写入失败:", rt)
        time.sleep(0.25)

        d = s6.Desc()
        root = d.add({"t": "table", "rows": t_rows})
        rtb = s6.api(
            f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/descendant",
            {"children_id": [root], "descendants": d.d},
        )
        if rtb.get("code") == 0:
            done += 1
        else:
            fail += 1
            print("  [!] 表格写入失败:", rtb)
        time.sleep(0.35)

        if chart_after and os.path.exists(chart_after):
            if s6.insert_image_block(doc_id, chart_after):
                done += 1
            else:
                fail += 1
            time.sleep(0.3)

    return done, fail


def _extract_hub_table(items: list) -> tuple[dict, list[list[str]], list[list[str]]]:
    """Read live Hub table cell texts and cell block IDs."""
    by_id = {b["block_id"]: b for b in items}
    tables = [b for b in items if b["block_type"] == 31]
    if not tables:
        raise RuntimeError("Hub doc missing table block!")
    tb = tables[0]
    prop = tb["table"]["property"]
    rows_n, cols_n = prop["row_size"], prop["column_size"]
    cells = tb["table"]["cells"]
    texts, cell_ids = [], []
    for r_i in range(rows_n):
        row_t, row_c = [], []
        for c_i in range(cols_n):
            cid = cells[r_i * cols_n + c_i]
            cb = by_id[cid]
            txt = ""
            for ch_id in cb.get("children", []):
                ch = by_id.get(ch_id, {})
                for el in ch.get("text", {}).get("elements", []):
                    txt += el.get("text_run", {}).get("content", "")
            row_t.append(txt.strip())
            row_c.append(cid)
        texts.append(row_t)
        cell_ids.append(row_c)
    return tb, texts, cell_ids


def _write_cell_text(s6, doc_id: str, by_id: dict, cell_id: str, text_val: str):
    """Safely populate an existing or freshly inserted Feishu table cell."""
    cb = by_id[cell_id]
    kids = cb.get("children", [])
    if kids:
        t_bid = kids[0]
        r = s6.api(
            f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{t_bid}",
            {"update_text_elements": {"elements": [{"text_run": {"content": text_val, "text_element_style": {}}}]}},
            "PATCH",
        )
    else:
        r = s6.api(
            f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{cell_id}/children",
            {
                "children": [{
                    "block_type": 2,
                    "text": {"elements": [{"text_run": {"content": text_val, "text_element_style": {}}}], "style": {"align": 1, "folded": False}},
                }],
                "index": -1,
            },
            "POST",
        )
    if r.get("code") != 0:
        raise RuntimeError(f"写入 Hub 单元格失败 ({cell_id}): {r}")


def update_hub_incremental(s6, new_row: list[str]) -> dict:
    """Incrementally append/update RD038 row in Hub index without overwriting existing 16 rows."""
    res = s6.api(f"{s6.BASE}/open-apis/docx/v1/documents/{HUB_VALID_DOC}/blocks?page_size=500", method="GET")
    items = res["data"]["items"]
    by_id = {b["block_id"]: b for b in items}
    tb, rows_txt, cell_ids = _extract_hub_table(items)

    existing_col0 = [r[0] for r in rows_txt[1:]]
    for old_t in HUB_EXISTING_TITLES:
        if old_t not in existing_col0:
            raise RuntimeError(f"Hub 现有行校验失败，缺失既有条目: {old_t}")

    target_row_idx = None
    for r_i in range(1, len(rows_txt)):
        if rows_txt[r_i][0] == new_row[0]:
            target_row_idx = r_i
            break

    if target_row_idx is None:
        r_ins = s6.api(
            f"{s6.BASE}/open-apis/docx/v1/documents/{HUB_VALID_DOC}/blocks/{tb['block_id']}",
            {"insert_table_row": {"row_index": -1}},
            "PATCH",
        )
        if r_ins.get("code") != 0:
            raise RuntimeError(f"Hub 增量插行失败: {r_ins}")
        time.sleep(0.35)
        res2 = s6.api(f"{s6.BASE}/open-apis/docx/v1/documents/{HUB_VALID_DOC}/blocks?page_size=500", method="GET")
        items2 = res2["data"]["items"]
        by_id = {b["block_id"]: b for b in items2}
        tb, rows_txt, cell_ids = _extract_hub_table(items2)
        target_row_idx = len(rows_txt) - 1

    for c_i, val in enumerate(new_row):
        _write_cell_text(s6, HUB_VALID_DOC, by_id, cell_ids[target_row_idx][c_i], val)
        time.sleep(0.15)

    res_fin = s6.api(f"{s6.BASE}/open-apis/docx/v1/documents/{HUB_VALID_DOC}/blocks?page_size=500", method="GET")
    items_fin = res_fin["data"]["items"]
    _, rows_fin, _ = _extract_hub_table(items_fin)
    n_entries = len(rows_fin) - 1

    for b in items_fin:
        if b.get("block_type") == 2 and b.get("parent_id") == HUB_VALID_DOC:
            txt = "".join(el.get("text_run", {}).get("content", "") for el in b.get("text", {}).get("elements", []))
            if "有效回测与可用规律全量索引表" in txt:
                new_hdr = f"有效回测与可用规律全量索引表（共 {n_entries} 项）"
                if txt.strip() != new_hdr:
                    s6.api(
                        f"{s6.BASE}/open-apis/docx/v1/documents/{HUB_VALID_DOC}/blocks/{b['block_id']}",
                        {"update_text_elements": {"elements": [{"text_run": {"content": new_hdr, "text_element_style": {"bold": True}}}]}},
                        "PATCH",
                    )
                break

    final_col0 = [r[0] for r in rows_fin[1:]]
    for old_t in HUB_EXISTING_TITLES + [new_row[0]]:
        if old_t not in final_col0:
            raise RuntimeError(f"Hub 更新后复核失败，缺少: {old_t}")

    return {"hub_doc_id": HUB_VALID_DOC, "total_rows": n_entries, "verified_titles_present": len(final_col0), "rd038_row": rows_fin[target_row_idx]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    rd038_charts.main()
    chart1_path = f"{RD038_DIR}/rd038_chart1_bundle_synergy_and_stress.png"
    chart2_path = f"{RD038_DIR}/rd038_chart2_loo_decomposition_and_forensics.png"

    import step6_upgrade_3strategies_20261117 as s6
    import step9_sync_v191_exits_20261118 as s9

    payload = payload_mod.build_rd038_payload(chart1_path, chart2_path)
    payload_mod.validate_payload_strict(payload, s6, s9)

    if args.dry_run:
        print(f"DRY-RUN COMPLETE. Peak RSS={_peak_rss_mb()} MB")
        return

    lock_f = open(s6.LOCK_PATH, "w")
    fcntl.flock(lock_f, fcntl.LOCK_EX)
    try:
        doc_id, node_tok = s9.find_or_create_child_node(PARENT_VALID_NODE, payload["title"])
        payload["doc_id"] = doc_id
        done, fail = _write_doc_with_interleaved_charts(s6, doc_id, payload)
        if fail > 0:
            raise RuntimeError(f"飞书文档写入存在 {fail} 处失败")

        time.sleep(0.5)
        verify_res = s9.verify_document_v191(
            doc_id=doc_id,
            doc_name=payload["title"],
            expected_tables_count=len(payload["tables"]),
            has_img=True,
        )
        if verify_res["images_count"] < 2:
            raise RuntimeError(f"图片数量不足 2 张: {verify_res}")

        r_raw = s6.api(f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/raw_content", method="GET")
        raw_txt = r_raw.get("data", {}).get("content", "")
        for tok in payload_mod.RD036_FORBIDDEN_TOKENS:
            if re.fullmatch(r"[A-Za-z0-9\-]+", tok):
                if re.search(rf"(?<![A-Za-z0-9]){re.escape(tok)}(?![A-Za-z0-9])", raw_txt):
                    raise ValueError(f"[在线回读] 命中禁用缩写 '{tok}'")
            elif tok in raw_txt:
                raise ValueError(f"[在线回读] 命中禁用词 '{tok}'")

        hub_res = update_hub_incremental(s6, payload_mod.HUB_ROW)
        wiki_url = f"https://my.feishu.cn/wiki/{node_tok}"

        with open(s6.MANIFEST_PATH) as f:
            mf = json.load(f)
        mf.setdefault("nodes", {})["rd038_grand_bundle_assembly"] = {
            "title": payload["title"],
            "node_token": node_tok,
            "obj_token": doc_id,
            "parent_node_token": PARENT_VALID_NODE,
            "wiki_url": wiki_url,
            "published_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        mf["rd038_grand_bundle_assembly"] = {
            "verify": verify_res,
            "hub_update": hub_res,
            "wiki_url": wiki_url,
        }
        with open(s6.MANIFEST_PATH, "w") as f:
            json.dump(mf, f, ensure_ascii=False, indent=2)

        out_res = {
            "title": payload["title"],
            "doc_id": doc_id,
            "node_token": node_tok,
            "wiki_url": wiki_url,
            "done_ops": done,
            "fail_ops": fail,
            "verify": verify_res,
            "hub_update": hub_res,
            "peak_rss_mb": _peak_rss_mb(),
            "d12_yfinance_imported": "yfinance" in sys.modules,
        }
        out_path = f"{RD038_DIR}/feishu_publish_result.json"
        with open(out_path, "w") as f:
            json.dump(out_res, f, ensure_ascii=False, indent=2)
        print(json.dumps(out_res, ensure_ascii=False, indent=2))
    finally:
        fcntl.flock(lock_f, fcntl.LOCK_UN)
        lock_f.close()


if __name__ == "__main__":
    main()

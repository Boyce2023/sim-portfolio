#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD041 Feishu Pure-Chinese Helpers & Live Hub Incremental Updaters.
Supports both target hubs safely (never overwriting existing rows):
  - Valid Hub: parent OPKUwAqCDibLfRkRE87cd2aCnVc, doc IRxgdlpOUoqfV4xVYYGczGurnyD
  - Invalid Hub: parent QiDewdTkJiquokkbbo6cWr3Fn6f, doc ZTaudjSqtoaj71xTPSLciMcdnLb
"""
import os
import re
import sys
import time

FS_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/feishu_master_docs_20261116"
if FS_DIR not in sys.path:
    sys.path.insert(0, FS_DIR)

import step6_upgrade_3strategies_20261117 as s6
import step9_sync_v191_exits_20261118 as s9

VALID_PARENT_NODE = "OPKUwAqCDibLfRkRE87cd2aCnVc"
VALID_HUB_DOC = "IRxgdlpOUoqfV4xVYYGczGurnyD"
INVALID_PARENT_NODE = "QiDewdTkJiquokkbbo6cWr3Fn6f"
INVALID_HUB_DOC = "ZTaudjSqtoaj71xTPSLciMcdnLb"

FORBIDDEN_LATIN_RE = re.compile(
    r"\b(?:WF|OOS|IS|PIT|BH|FDR|DSR|CSCV|PBO|LOO|MTM|Sharpe|Calmar|MDD|NAV|PLR|KPL|CSRC|bps|RD\d+)\b"
)
FORBIDDEN_CN_JARGON = ["t值", "p值", "q值", "消融", "门禁", "闭环", "矩阵", "铁证", "重锚", "回灌", "王牌", "天花板"]


def T(txt: str, bold: bool = False, hl: bool = False) -> dict:
    st = {}
    if bold:
        st["bold"] = True
    if hl:
        st["background_color"] = 3
    return {
        "block_type": 2,
        "text": {"elements": [{"text_run": {"content": txt, "text_element_style": st}}], "style": {"align": 1, "folded": False}},
    }


def MIXED(parts: list) -> dict:
    els = []
    for txt, bold, hl in parts:
        st = {}
        if bold:
            st["bold"] = True
        if hl:
            st["background_color"] = 3
        els.append({"text_run": {"content": txt, "text_element_style": st}})
    return {"block_type": 2, "text": {"elements": els, "style": {"align": 1, "folded": False}}}


def B(txt: str, bold: bool = False, hl: bool = False) -> dict:
    st = {}
    if bold:
        st["bold"] = True
    if hl:
        st["background_color"] = 3
    return {
        "block_type": 12,
        "bullet": {"elements": [{"text_run": {"content": txt, "text_element_style": st}}], "style": {"align": 1, "folded": False}},
    }


def BL() -> dict:
    return {"block_type": 2, "text": {"elements": [{"text_run": {"content": "", "text_element_style": {}}}], "style": {"align": 1, "folded": False}}}


def C(txt: str, bold: bool = False) -> list:
    return [(str(txt), {"bold": True} if bold else {})]


def audit_payload_strict(payload: dict, require_img: bool = True):
    """Run step9 V19.1 audit + extra jargon/punctuation/length checks."""
    s9.check_first_sentence_rule(payload)
    longs = s9.audit_doc_strict_v191(payload, require_img=require_img)
    if longs:
        raise ValueError(f"存在超40字长句({len(longs)}): {longs}")

    all_strs = [("title", payload["title"])]
    for idx, b in enumerate(payload["blocks"]):
        els = b.get("text", b.get("bullet", b.get("ordered", {}))).get("elements", [])
        all_strs.append((f"block_{idx+1}", "".join(e["text_run"]["content"] for e in els)))
    for t_ttl, t_rows in payload["tables"]:
        all_strs.append(("table_title", t_ttl))
        for r_i, rw in enumerate(t_rows):
            for c_i, cell in enumerate(rw):
                all_strs.append((f"{t_ttl}_R{r_i}C{c_i}", "".join(x for x, _ in cell)))

    for loc, txt in all_strs:
        m = FORBIDDEN_LATIN_RE.search(txt)
        if m:
            raise ValueError(f"[{loc}] 命中禁用缩写 '{m.group(0)}': {txt}")
        for jw in FORBIDDEN_CN_JARGON:
            if jw in txt:
                raise ValueError(f"[{loc}] 命中禁用黑话 '{jw}': {txt}")
    return True


def audit_online_raw_text(raw_txt: str):
    m = FORBIDDEN_LATIN_RE.search(raw_txt)
    if m:
        raise ValueError(f"[在线回读] 命中禁用缩写 '{m.group(0)}'")
    for jw in FORBIDDEN_CN_JARGON:
        if jw in raw_txt:
            raise ValueError(f"[在线回读] 命中禁用黑话 '{jw}'")


def _extract_hub_table(items: list) -> tuple[dict, list[list[str]], list[list[str]]]:
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


def _write_cell_text(doc_id: str, by_id: dict, cell_id: str, text_val: str):
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


def update_hub_incremental(hub_doc_id: str, hub_title_prefix: str, new_row: list[str]) -> dict:
    """Safely insert/update `new_row` into target Hub table WITHOUT touching any existing row."""
    res = s6.api(f"{s6.BASE}/open-apis/docx/v1/documents/{hub_doc_id}/blocks?page_size=500", method="GET")
    items = res["data"]["items"]
    by_id = {b["block_id"]: b for b in items}
    tb, rows_txt, cell_ids = _extract_hub_table(items)
    existing_titles = [r[0] for r in rows_txt[1:] if r[0]]

    target_row_idx = None
    for r_i in range(1, len(rows_txt)):
        if rows_txt[r_i][0] == new_row[0]:
            target_row_idx = r_i
            break

    if target_row_idx is None:
        r_ins = s6.api(
            f"{s6.BASE}/open-apis/docx/v1/documents/{hub_doc_id}/blocks/{tb['block_id']}",
            {"insert_table_row": {"row_index": -1}},
            "PATCH",
        )
        if r_ins.get("code") != 0:
            raise RuntimeError(f"Hub 增量插行失败: {r_ins}")
        time.sleep(0.35)
        res2 = s6.api(f"{s6.BASE}/open-apis/docx/v1/documents/{hub_doc_id}/blocks?page_size=500", method="GET")
        items2 = res2["data"]["items"]
        by_id = {b["block_id"]: b for b in items2}
        tb, rows_txt, cell_ids = _extract_hub_table(items2)
        target_row_idx = len(rows_txt) - 1

    for c_i, val in enumerate(new_row):
        _write_cell_text(hub_doc_id, by_id, cell_ids[target_row_idx][c_i], val)
        time.sleep(0.15)

    res_fin = s6.api(f"{s6.BASE}/open-apis/docx/v1/documents/{hub_doc_id}/blocks?page_size=500", method="GET")
    items_fin = res_fin["data"]["items"]
    _, rows_fin, _ = _extract_hub_table(items_fin)
    n_entries = len(rows_fin) - 1

    for b in items_fin:
        if b.get("block_type") == 2 and b.get("parent_id") == hub_doc_id:
            txt = "".join(el.get("text_run", {}).get("content", "") for el in b.get("text", {}).get("elements", []))
            if hub_title_prefix in txt:
                new_hdr = f"{hub_title_prefix}全量索引表（共 {n_entries} 项）"
                if txt.strip() != new_hdr:
                    s6.api(
                        f"{s6.BASE}/open-apis/docx/v1/documents/{hub_doc_id}/blocks/{b['block_id']}",
                        {"update_text_elements": {"elements": [{"text_run": {"content": new_hdr, "text_element_style": {"bold": True}}}]}},
                        "PATCH",
                    )
                break

    final_col0 = [r[0] for r in rows_fin[1:]]
    for old_t in existing_titles + [new_row[0]]:
        if old_t not in final_col0:
            raise RuntimeError(f"Hub 更新后复核失败，缺少: {old_t}")

    return {"hub_doc_id": hub_doc_id, "total_rows": n_entries, "verified_titles_present": len(final_col0), "added_row": rows_fin[target_row_idx]}


def _insert_image_block_safe(doc_id: str, png_path: str) -> bool:
    import json, subprocess
    if not os.path.exists(png_path):
        print(f"  [!] 图片文件不存在: {png_path}")
        return False
    r1 = s6.api(
        f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children",
        {"children": [{"block_type": 27, "image": {}}], "index": -1},
        "POST",
    )
    if r1.get("code") != 0:
        print("  [!] 创建 image block 失败:", r1)
        return False
    blk_id = r1["data"]["children"][0]["block_id"]
    time.sleep(0.2)

    tok_s = s6._shared_tok(force=False)
    r2 = {}
    for att in range(3):
        out = subprocess.check_output(
            [
                "curl", "-sS", "-X", "POST", f"{s6.BASE}/open-apis/drive/v1/medias/upload_all",
                "-H", f"Authorization: Bearer {tok_s}",
                "-F", f"file_name={os.path.basename(png_path)}",
                "-F", "parent_type=docx_image",
                "-F", f"parent_node={blk_id}",
                "-F", f"size={os.path.getsize(png_path)}",
                "-F", f"file=@{png_path};type=image/png",
            ],
            timeout=120,
        ).decode("utf-8")
        r2 = json.loads(out)
        if r2.get("code") == 0:
            break
        if r2.get("code") in (99991661, 99991677):
            tok_s = s6._shared_tok(force=True)
            s6.T = tok_s
            time.sleep(1.0)
            continue
        if r2.get("code") == 99991400:
            time.sleep(2 ** att * 3)
            continue
        break

    if r2.get("code") != 0:
        print("  [!] 上传 image media 失败:", r2)
        return False
    time.sleep(0.2)
    r3 = s6.api(
        f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{blk_id}",
        {"replace_image": {"token": r2["data"]["file_token"]}},
        "PATCH",
    )
    if r3.get("code") != 0:
        print("  [!] replace_image 失败:", r3)
        return False
    print(f"  [+] 成功插入图片: {os.path.basename(png_path)}")
    return True


def write_doc_with_interleaved_charts(doc_id: str, blocks: list, sections_tables: list):
    if doc_id in s6.PROTECTED_DOCS or doc_id in (VALID_HUB_DOC, INVALID_HUB_DOC):
        raise RuntimeError(f"SAFETY BLOCK: forbidden clear_doc_all on {doc_id}")
    s6.clear_doc_all(doc_id)

    done, fail = 0, 0
    for i in range(0, len(blocks), 40):
        ch = blocks[i : i + 40]
        r = s6.api(f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children", {"children": ch, "index": -1}, "POST")
        if r.get("code") == 0:
            done += len(ch)
        else:
            for b in ch:
                r2 = s6.api(f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children", {"children": [b], "index": -1}, "POST")
                if r2.get("code") == 0:
                    done += 1
                else:
                    fail += 1
        time.sleep(0.25)

    for t_title, t_rows, chart_after in sections_tables:
        t_blk = {"block_type": 2, "text": {"elements": [{"text_run": {"content": t_title, "text_element_style": {"bold": True}}}], "style": {"align": 1, "folded": False}}}
        rt = s6.api(f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children", {"children": [t_blk], "index": -1}, "POST")
        if rt.get("code") == 0:
            done += 1
        else:
            fail += 1
        time.sleep(0.25)

        d = s6.Desc()
        root = d.add({"t": "table", "rows": t_rows})
        rtb = s6.api(f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/descendant", {"children_id": [root], "descendants": d.d})
        if rtb.get("code") == 0:
            done += 1
        else:
            fail += 1
        time.sleep(0.35)

        if chart_after and os.path.exists(chart_after):
            if _insert_image_block_safe(doc_id, chart_after):
                done += 1
            else:
                fail += 1
            time.sleep(0.3)

    return done, fail

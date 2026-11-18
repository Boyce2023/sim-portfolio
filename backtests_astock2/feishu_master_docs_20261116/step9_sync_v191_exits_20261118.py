#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""步骤九：V19.1 三大策略卖点升级全量同步主文档 + 3 篇卖点专项回测子目录幂等挂载与全量回读核验"""
import os
import sys
import re
import json
import time
import fcntl
import argparse

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CUR_DIR)

import step6_upgrade_3strategies_20261117 as s6
from gen_master_charter_v191 import build_master_charter_v191_blocks
from gen_3to4_v41 import build_3to4_v41_blocks
from gen_pry_v21 import build_pry_v21_blocks
from gen_2to3_v21 import build_2to3_v21_blocks
from gen_1to2_v191 import build_1to2_v191_blocks
from gen_high_v51_v191 import build_high_v51_v191_blocks
from gen_small_hub_v41 import build_small_hub_v41_blocks
from gen_26q4_v21 import build_26q4_v21_blocks
from gen_sub7_3to4_exits_v41 import build_sub7_3to4_exits_v41_blocks
from gen_sub8_2to3_exits_v21 import build_sub8_2to3_exits_v21_blocks
from gen_sub9_pry_exits_v21 import build_sub9_pry_exits_v21_blocks

# 对《26Q4专供》解除写保护，其余历史保护文档依然锁定
s6.PROTECTED_DOCS.discard("WGtbd6n5Po4llQxEKoVceMsWndb")

# 严格禁用标点（放行合法正负号，仍绝对禁止中文破折号与英文单词连字符）
BANNED_PUNC_STRICT = ["—", "——", "–", "！", "!", "→", "**", "~"]
# 禁止任何「赚/亏/涨/跌/正/负 + 数字%」旧写法
OLD_PCT_WORDING_RE = re.compile(r"(?:赚|亏|涨|跌|正|负)(?:超|破|至|幅)?\s*\d+(?:\.\d+)?%")
# 禁止未转译的代码变量名
CODE_VAR_BANNED = list(set(s6.EXTRA_BANNED_WORDS + [
    "OPERATEDEPT_CODE", "brk_r10", "dev_10d", "dev_30d", "tight_headroom", "rk_prio", "blended_sr",
    "CLV", "Elo", "s_3to4", "s_2to3", "s_pry", "c>o", "ret10", "std90", "strict96", "strict102",
    "DecD_4d", "Opt_V21", "Path2_Only", "U_pts", "Z_pts", "dyn_tp", "mkt_open_zt",
    "prev_n_dt", "n_dt", "abn_calc", "gb_cnt", "sd_mates", "wide75", "P165", "P150",
    "P140", "P000", "B1_X10", "Track 1", "Track 2", "RD2d",
]))
XF_RE = re.compile(r"\bXF\d+[a-zA-Z0-9_]*")
ENG_IS_OOS_RE = re.compile(r"\b(IS|OOS)\b")


def check_text_punc_and_vars(txt: str, loc: str):
    for p in BANNED_PUNC_STRICT:
        if p in txt:
            raise ValueError(f"[{loc}] 发现违规标点 '{p}': {txt}")
    # 检查 '-'：允许数字前负号 r'(?<![A-Za-z0-9])-\d'，拦截其他一切连字符如 walk-forward / T-1 / 2026-11-18
    stripped_neg = re.sub(r"(?<![A-Za-z0-9])-\d+(?:\.\d+)?", "", txt)
    if "-" in stripped_neg:
        raise ValueError(f"[{loc}] 发现非数字负号连字符 '-': {txt}")
    m_old = OLD_PCT_WORDING_RE.search(txt)
    if m_old:
        raise ValueError(f"[{loc}] 违规使用旧版百分比措辞 '{m_old.group(0)}'（须用 +X% / -X%）: {txt}")
    for w in CODE_VAR_BANNED:
        if w in txt:
            raise ValueError(f"[{loc}] 发现禁用词或代码变量 '{w}': {txt}")
    m_xf = XF_RE.search(txt)
    if m_xf:
        raise ValueError(f"[{loc}] 发现代码因子编号 '{m_xf.group(0)}': {txt}")
    m_io = ENG_IS_OOS_RE.search(txt)
    if m_io:
        raise ValueError(f"[{loc}] 发现英文简称 '{m_io.group(0)}'（请改用样本内/样本外）: {txt}")
    found_trad = [ch for ch in txt if ch in s6.TRAD_CHARS]
    if found_trad:
        raise ValueError(f"[{loc}] 发现繁体字 {found_trad}: {txt}")
    if s6.EMOJI_RE.search(txt):
        raise ValueError(f"[{loc}] 发现 Emoji: {txt}")


def audit_doc_strict_v191(data: dict, require_img: bool = True):
    name = data["title"]
    blocks = data["blocks"]
    tables = data["tables"]
    img_path = data.get("img_path")

    if data.get("doc_id") in s6.PROTECTED_DOCS:
        raise RuntimeError(f"[{name}] 命中受保护文档 {data['doc_id']}")
    if require_img and (not img_path or not os.path.exists(img_path)):
        raise FileNotFoundError(f"[{name}] 缺失净值图: {img_path}")

    blank_streak = max_streak = 0
    for b in blocks:
        if b["block_type"] == 2:
            txt = "".join(e["text_run"]["content"] for e in b["text"]["elements"]).strip()
            blank_streak = blank_streak + 1 if txt == "" else 0
            max_streak = max(max_streak, blank_streak)
        else:
            blank_streak = 0
    if max_streak < 3:
        raise ValueError(f"[{name}] 缺少末尾连续3个空行")

    has_yellow = False
    long_sentences = []
    all_lens = []
    for idx, b in enumerate(blocks):
        bt = b["block_type"]
        if bt in range(3, 12) or bt == 19:
            raise ValueError(f"[{name}] 发现禁止的 Heading 或 Callout 块: type={bt}")
        if bt == 2:
            els = b["text"]["elements"]
        elif bt == 12:
            els = b["bullet"]["elements"]
        elif bt == 13:
            els = b["ordered"]["elements"]
        else:
            continue

        full_txt = ""
        for e in els:
            tr = e["text_run"]
            c = tr["content"]
            if tr.get("text_element_style", {}).get("background_color") == 3:
                has_yellow = True
            full_txt += c
            check_text_punc_and_vars(c, f"{name}-块{idx+1}")

        for sent in re.split(r"[。；]", full_txt):
            s = sent.strip()
            if not s:
                continue
            all_lens.append(len(s))
            if len(s) > 40:
                long_sentences.append((idx + 1, len(s), s))

    if not has_yellow:
        raise ValueError(f"[{name}] 缺少黄色底高亮 (background_color=3)")

    for t_title, t_rows in tables:
        check_text_punc_and_vars(t_title, f"{name}-表标题")
        max_cols = max(len(r) for r in t_rows)
        if max_cols >= 5:
            raise ValueError(f"[{name}] 表格列数必须严格 < 5 列: {t_title} 实际 {max_cols} 列")
        for r_i, row in enumerate(t_rows):
            for c_i, cell in enumerate(row):
                cell_txt = "".join(txt for txt, _ in cell)
                check_text_punc_and_vars(cell_txt, f"{name}-{t_title}-R{r_i}C{c_i}")
                if len(cell_txt) > 32:
                    raise ValueError(f"[{name}] 单元格过长 ({len(cell_txt)}字): {cell_txt}")

    print(
        f"[Audit PASS] 【{name}】正文块={len(blocks)}, 表格={len(tables)} (<=4列), "
        f"句数={len(all_lens)}, 最大句长={max(all_lens)}字, 平均句长={sum(all_lens)/len(all_lens):.1f}字, 超40字句={len(long_sentences)}"
    )
    for b_i, slen, stxt in long_sentences:
        print(f"   [长句 块{b_i} ({slen}字)]: {stxt}")
    return long_sentences


def check_first_sentence_rule(data: dict):
    els = data["blocks"][0]["text"]["elements"]
    c0 = els[0]["text_run"]["content"]
    bg0 = els[0]["text_run"].get("text_element_style", {}).get("background_color")
    if ("有用" not in c0 and "没用" not in c0) or bg0 != 3:
        raise ValueError(f"[{data['title']}] 第1句话未按硬规格写清有用没用并标黄: {c0} | bg={bg0}")


def verify_document_v191(doc_id: str, doc_name: str, expected_tables_count: int, has_img: bool = True):
    print(f"\n[*] 开始在线核验飞书文档: [{doc_name}] ({doc_id}) ...")
    r_blk = s6.api(f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children?page_size=500", method="GET")
    if r_blk.get("code") != 0:
        raise RuntimeError(f"[{doc_name}] 获取 blocks 失败: {r_blk}")
    items = r_blk["data"].get("items") or []

    if [b for b in items if b.get("block_type") in range(3, 12)]:
        raise ValueError(f"[{doc_name}] 违规发现 Heading 块")
    if [b for b in items if b.get("block_type") == 19]:
        raise ValueError(f"[{doc_name}] 违规发现 Callout 块")
    for i, b in enumerate(items[:6]):
        if b.get("block_type") in (27, 31):
            raise ValueError(f"[{doc_name}] 前 6 块中违规出现表格或图片")

    empty_indices = []
    for i, b in enumerate(items):
        if b.get("block_type") == 2:
            txt_el = b.get("text", {}).get("elements", [])
            txt = "".join(e.get("text_run", {}).get("content", "") for e in txt_el).strip()
            if txt == "":
                empty_indices.append(i)
    has_3_empty = any(
        empty_indices[i + 1] == empty_indices[i] + 1 and empty_indices[i + 2] == empty_indices[i] + 2
        for i in range(len(empty_indices) - 2)
    )
    if not has_3_empty:
        raise ValueError(f"[{doc_name}] 未检测到连续 3 个空文本块")

    table_blocks = [b for b in items if b.get("block_type") == 31]
    image_blocks = [b for b in items if b.get("block_type") == 27]
    if len(table_blocks) < expected_tables_count:
        raise ValueError(f"[{doc_name}] 表格数量不符: 实际 {len(table_blocks)} < 预期 {expected_tables_count}")
    if has_img and len(image_blocks) < 1:
        raise ValueError(f"[{doc_name}] 缺失净值图片")

    r_raw = s6.api(f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/raw_content", method="GET")
    raw_content = r_raw.get("data", {}).get("content", "")
    if len(raw_content) < 600:
        raise ValueError(f"[{doc_name}] 文档回读内容过短: {len(raw_content)} 字符")

    # 仅校验正文与表格内容（raw_content 第一行是飞书文档标题）
    lines = [ln.strip() for ln in raw_content.splitlines() if ln.strip()]
    body_text = "\n".join(lines[1:]) if len(lines) > 1 else raw_content
    check_text_punc_and_vars(body_text, f"在线回读-{doc_name}")

    first_line = lines[1] if len(lines) > 1 else (lines[0] if lines else "")
    print(f"  [+] [{doc_name}] 核验完美通过: 块数={len(items)}, 表格={len(table_blocks)}, 图片={len(image_blocks)}, 字符={len(raw_content)}")
    return {
        "doc_name": doc_name,
        "doc_id": doc_id,
        "blocks_count": len(items),
        "tables_count": len(table_blocks),
        "images_count": len(image_blocks),
        "raw_chars": len(raw_content),
        "first_line_online": first_line,
    }


def find_or_create_child_node(parent_tok: str, title: str) -> tuple[str, str]:
    r = s6.api(f"{s6.BASE}/open-apis/wiki/v2/spaces/{s6.SPACE_ID}/nodes?page_size=50&parent_node_token={parent_tok}", method="GET")
    if r.get("code") != 0:
        raise RuntimeError(f"查询子节点失败 {parent_tok}: {r}")
    for it in r.get("data", {}).get("items") or []:
        if it.get("title") == title:
            return it["obj_token"], it["node_token"]
    rc = s6.api(
        f"{s6.BASE}/open-apis/wiki/v2/spaces/{s6.SPACE_ID}/nodes",
        {"obj_type": "docx", "node_type": "origin", "parent_node_token": parent_tok, "title": title},
        "POST",
    )
    if rc.get("code") != 0:
        raise RuntimeError(f"创建子节点失败 [{title}]: {rc}")
    nd = rc["data"]["node"]
    time.sleep(0.5)
    return nd["obj_token"], nd["node_token"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only", type=str, default="", help="comma-separated keys")
    args = parser.parse_args()

    task_a_specs = [
        ("charter", build_master_charter_v191_blocks),
        ("3to4", build_3to4_v41_blocks),
        ("pry", build_pry_v21_blocks),
        ("2to3", build_2to3_v21_blocks),
        ("1to2", build_1to2_v191_blocks),
        ("high", build_high_v51_v191_blocks),
        ("small_hub", build_small_hub_v41_blocks),
        ("26q4", build_26q4_v21_blocks),
    ]
    task_b_specs = [
        ("sub7_3to4_exits", build_sub7_3to4_exits_v41_blocks),
        ("sub8_2to3_exits", build_sub8_2to3_exits_v21_blocks),
        ("sub9_pry_exits", build_sub9_pry_exits_v21_blocks),
    ]

    all_items = []
    any_long = False
    only_set = set(args.only.split(",")) if args.only else None
    for grp, specs in [("task_a_master", task_a_specs), ("task_b_subdoc", task_b_specs)]:
        for key, fn in specs:
            if only_set and key not in only_set:
                continue
            d = fn()
            d["key"] = key
            d["group"] = grp
            if grp == "task_b_subdoc":
                check_first_sentence_rule(d)
            longs = audit_doc_strict_v191(d, require_img=bool(d.get("img_path")))
            if longs:
                any_long = True
            all_items.append(d)

    if any_long:
        raise ValueError("存在超 40 字长句，拒绝发布！")
    if args.dry_run:
        print(f"\n[Dry-Run PASS] 全部 {len(all_items)} 篇文档本地严格审核零违规。")
        return

    lock_fd = open(s6.LOCK_PATH, "w")
    step9_results = []
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        m = json.load(open(s6.MANIFEST_PATH, "r", encoding="utf-8"))
        for d in all_items:
            title = d["title"]
            if d["group"] == "task_b_subdoc":
                doc_id, node_tok = find_or_create_child_node(d["parent_node_token"], title)
                d["doc_id"], d["node_token"] = doc_id, node_tok
            else:
                doc_id, node_tok = d["doc_id"], d["node_token"]
                # 仅当总纲节点标题仍为 V19.0 时原地更名为 V19.1，不移动、不删、不重排
                if d["key"] == "charter":
                    info = s6.api(f"{s6.BASE}/open-apis/wiki/v2/spaces/{s6.SPACE_ID}/nodes/{node_tok}", method="GET")
                    cur_t = info.get("data", {}).get("node", {}).get("title", "")
                    if cur_t != title:
                        r_up = s6.api(
                            f"{s6.BASE}/open-apis/wiki/v2/spaces/{s6.SPACE_ID}/nodes/{node_tok}/update_title",
                            {"title": title},
                            "POST",
                        )
                        if r_up.get("code") != 0:
                            print(f"  [!] 更新总纲标题失败 (保持原位置与正文更新): {r_up}")
                        else:
                            print(f"  [+] 已将总纲标题从 '{cur_t}' 更新为 '{title}'")

            if doc_id in s6.PROTECTED_DOCS:
                raise RuntimeError(f"受保护文档阻断: {title} ({doc_id})")

            done, fail = s6.write_document_payload(doc_id, d["blocks"], d["tables"], d.get("img_path"))
            if fail > 0:
                raise RuntimeError(f"[{title}] 写入失败 {fail} 块")
            time.sleep(1.2)
            v = verify_document_v191(doc_id, title, expected_tables_count=len(d["tables"]), has_img=bool(d.get("img_path")))
            v["node_token"] = node_tok
            v["wiki_url"] = f"https://my.feishu.cn/wiki/{node_tok}"
            v["key"] = d["key"]
            v["group"] = d["group"]
            step9_results.append(v)

            m.setdefault("nodes", {})[d["key"]] = {
                "title": title, "node_token": node_tok, "obj_token": doc_id, "url": v["wiki_url"]
            }

        now_ts = time.strftime("%Y-%m-%d %H:%M:%S")
        m["last_published_at"] = now_ts
        m["step9_published_at"] = now_ts
        m["step9_results"] = step9_results
        res_by_id = {r["doc_id"]: r for r in step9_results}
        merged, seen_ids = [], set()
        for it in m.get("results", []):
            did = it.get("doc_id")
            if did in res_by_id:
                merged.append(res_by_id[did])
                seen_ids.add(did)
            else:
                merged.append(it)
        for r in step9_results:
            if r["doc_id"] not in seen_ids:
                merged.append(r)
        m["results"] = merged
        with open(s6.MANIFEST_PATH, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=2)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()

    print("\n=== STEP 9 V19.1 ALL DONE ===")
    for r in step9_results:
        print(f"[{r['group']}] {r['doc_name']} | {r['wiki_url']} | blk={r['blocks_count']} tbl={r['tables_count']} img={r['images_count']} chars={r['raw_chars']}")
        print(f"   L1: {r['first_line_online'][:120]}")


if __name__ == "__main__":
    main()

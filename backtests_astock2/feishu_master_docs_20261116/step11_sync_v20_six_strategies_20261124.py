#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""步骤十一：V20.0 六大策略 + 20cm 主策略 + 有效/证伪分类研究子文档 全量同步与严格核验"""
import os, sys, re, json, time, fcntl, argparse

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CUR_DIR)

import step6_upgrade_3strategies_20261117 as s6
import step9_sync_v191_exits_20261118 as s9

from gen_master_charter_v20 import build_master_charter_v20_blocks
from gen_1to2_v20 import build_1to2_v20_blocks
from gen_20cm_v11 import build_20cm_v11_blocks
from gen_3to4_v41_v20 import build_3to4_v41_v20_blocks
from gen_high_v51_v20 import build_high_v51_v20_blocks
from gen_pry_v21_v20 import build_pry_v21_v20_blocks
from gen_2to3_v21_v20 import build_2to3_v21_v20_blocks
from gen_sub11_v20_jianyan import build_sub11_v20_jianyan_blocks
from gen_sub12_valid_rules import build_sub12_valid_rules_blocks
from gen_sub13_hot_largecap_falsified import build_sub13_hot_largecap_falsified_blocks

BANNED_V20 = list(set(s9.CODE_VAR_BANNED + [
    "千万封顶", "百万封顶", "百万起", "千万单利", "cap10m",
    "s_1to2", "s_high", "s_20cm_deepopen", "s_4to5", "s_fund",
    "fb20_cln", "inst_dt", "P3_S2C_STierReserveOnly", "R_sen20_lt40",
]))
BANNED_PUNC_V20 = s9.BANNED_PUNC_STRICT + [";", "；"]
GLOSSARY_PAIRS = [
    ("OOS", "OOS（样本外）"),
    ("PIT", "PIT（点时点）"),
    ("Calmar", "Calmar（卡尔玛）"),
    ("ablation", "ablation（消融）"),
]


def check_text_v20(txt: str, loc: str, allow_shell_cmds: bool = False):
    cleaned = txt
    if allow_shell_cmds:
        lines = []
        for ln in cleaned.splitlines():
            if ln.strip().startswith("cd ~/claude-projects && /opt/homebrew/bin/python3.13 sim-portfolio/scripts/"):
                continue
            lines.append(ln)
        cleaned = "\n".join(lines)

    for p in BANNED_PUNC_V20:
        if p in cleaned:
            raise ValueError(f"[{loc}] 发现违规标点 '{p}': {cleaned}")
    stripped_neg = re.sub(r"(?<![A-Za-z0-9])-\d+(?:\.\d+)?", "", cleaned)
    if "-" in stripped_neg:
        raise ValueError(f"[{loc}] 发现非数字负号连字符 '-': {cleaned}")
    m_old = s9.OLD_PCT_WORDING_RE.search(cleaned)
    if m_old:
        raise ValueError(f"[{loc}] 违规使用旧版百分比措辞 '{m_old.group(0)}': {cleaned}")
    for w in BANNED_V20:
        if w in cleaned:
            raise ValueError(f"[{loc}] 发现禁用词或代码变量 '{w}': {cleaned}")
    m_xf = s9.XF_RE.search(cleaned)
    if m_xf:
        raise ValueError(f"[{loc}] 发现代码因子编号 '{m_xf.group(0)}': {cleaned}")
    if re.search(r"\bIS\b", cleaned):
        raise ValueError(f"[{loc}] 发现英文简称 IS（请改写为样本内）: {cleaned}")
    for eng, required in GLOSSARY_PAIRS:
        tmp = cleaned.replace(required, "")
        if re.search(rf"\b{eng}\b", tmp):
            raise ValueError(f"[{loc}] '{eng}' 未配中文标注 '{required}': {cleaned}")
    found_trad = [ch for ch in cleaned if ch in s6.TRAD_CHARS]
    if found_trad:
        raise ValueError(f"[{loc}] 发现繁体字 {found_trad}: {cleaned}")
    if s6.EMOJI_RE.search(cleaned):
        raise ValueError(f"[{loc}] 发现 Emoji: {cleaned}")


def audit_doc_strict_v20(data: dict, require_img: bool = True):
    name, blocks, tables, img_path = data["title"], data["blocks"], data["tables"], data.get("img_path")
    if data.get("doc_id") in s6.PROTECTED_DOCS:
        raise RuntimeError(f"[{name}] 命中受保护文档 {data['doc_id']}")
    if require_img and (not img_path or not os.path.exists(img_path)):
        raise FileNotFoundError(f"[{name}] 缺失净值图: {img_path}")

    blank_streak = max_streak = 0
    for b in blocks:
        if b["block_type"] == 2:
            t = "".join(e["text_run"]["content"] for e in b["text"]["elements"]).strip()
            blank_streak = blank_streak + 1 if t == "" else 0
            max_streak = max(max_streak, blank_streak)
        else:
            blank_streak = 0
    if max_streak < 3:
        raise ValueError(f"[{name}] 缺少末尾连续 3 个空行")

    has_yellow, longs, lens, total_chars = False, [], [], 0
    for idx, b in enumerate(blocks):
        bt = b["block_type"]
        if bt in range(3, 12) or bt == 19:
            raise ValueError(f"[{name}] 禁止 Heading 或 Callout 块: type={bt}")
        if bt == 14:
            for e in b["code"]["elements"]:
                c = e["text_run"]["content"]
                total_chars += len(c)
                check_text_v20(c, f"{name}-代码块{idx+1}", allow_shell_cmds=True)
            continue
        els = b.get("text", b.get("bullet", b.get("ordered", {}))).get("elements", [])
        if not els:
            continue
        y_cnt = 0
        full_txt = ""
        for e in els:
            tr = e["text_run"]
            c = tr["content"]
            if tr.get("text_element_style", {}).get("background_color") == 3:
                has_yellow = True
                y_cnt += 1
            full_txt += c
            check_text_v20(c, f"{name}-块{idx+1}")
        total_chars += len(full_txt)
        if y_cnt > 1:
            raise ValueError(f"[{name}-块{idx+1}] 单段超过 1 句黄底高亮 ({y_cnt})")
        for sent in re.split(r"[。；]", full_txt):
            s = sent.strip()
            if s:
                lens.append(len(s))
                if len(s) > 40:
                    longs.append((idx + 1, len(s), s))

    if not has_yellow:
        raise ValueError(f"[{name}] 缺少黄色底高亮")
    for t_title, t_rows in tables:
        check_text_v20(t_title, f"{name}-表标题")
        total_chars += len(t_title)
        if max(len(r) for r in t_rows) >= 5:
            raise ValueError(f"[{name}] 表格列数必须 < 5: {t_title}")
        for ri, row in enumerate(t_rows):
            for ci, cell in enumerate(row):
                ct = "".join(t for t, _ in cell)
                total_chars += len(ct)
                check_text_v20(ct, f"{name}-{t_title}-R{ri}C{ci}")
                if len(ct) > 32:
                    raise ValueError(f"[{name}] 单元格超32字({len(ct)}): {ct}")
    if total_chars < 650:
        raise ValueError(f"[{name}] 总字数不足 ({total_chars} < 650)")
    print(f"[Audit V20 PASS] 【{name}】块={len(blocks)}, 表={len(tables)}, 字={total_chars}, 句={len(lens)}, 最大={max(lens)}字, 超40={len(longs)}")
    for bi, sl, st in longs:
        print(f"   [长句 块{bi} ({sl}字)]: {st}")
    return longs


def find_or_create_root_node(title: str) -> tuple[str, str]:
    tok = ""
    while True:
        q = f"{s6.BASE}/open-apis/wiki/v2/spaces/{s6.SPACE_ID}/nodes?page_size=50" + (f"&page_token={tok}" if tok else "")
        r = s6.api(q, method="GET")
        if r.get("code") != 0:
            raise RuntimeError(f"查询根节点失败: {r}")
        for it in r.get("data", {}).get("items") or []:
            if it.get("title") == title:
                return it["obj_token"], it["node_token"]
        if not r.get("data", {}).get("has_more"):
            break
        tok = r["data"].get("page_token", "")
    rc = s6.api(f"{s6.BASE}/open-apis/wiki/v2/spaces/{s6.SPACE_ID}/nodes",
                {"obj_type": "docx", "node_type": "origin", "title": title}, "POST")
    if rc.get("code") != 0:
        raise RuntimeError(f"创建顶层节点失败 [{title}]: {rc}")
    nd = rc["data"]["node"]
    time.sleep(0.5)
    return nd["obj_token"], nd["node_token"]


def verify_document_v20(doc_id: str, doc_name: str, expected_tables: int, has_img: bool = True, allow_shell: bool = False):
    print(f"\n[*] 在线回读核验: [{doc_name}] ({doc_id}) ...")
    items = s6.api(f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children?page_size=500", method="GET")["data"].get("items") or []
    if [b for b in items if b.get("block_type") in range(3, 12)] or [b for b in items if b.get("block_type") == 19]:
        raise ValueError(f"[{doc_name}] 违规 Heading 或 Callout 块")
    if any(b.get("block_type") in (27, 31) for b in items[:6]):
        raise ValueError(f"[{doc_name}] 前 6 块中违规出现表格或图片")
    empties = [i for i, b in enumerate(items) if b.get("block_type") == 2 and "".join(e.get("text_run", {}).get("content", "") for e in b.get("text", {}).get("elements", [])).strip() == ""]
    if not any(empties[i+1] == empties[i]+1 and empties[i+2] == empties[i]+2 for i in range(len(empties)-2)):
        raise ValueError(f"[{doc_name}] 未检测到连续 3 个空文本块")
    tbls = [b for b in items if b.get("block_type") == 31]
    imgs = [b for b in items if b.get("block_type") == 27]
    if len(tbls) < expected_tables or (has_img and len(imgs) < 1):
        raise ValueError(f"[{doc_name}] 表格/图片不符: tbl={len(tbls)}/{expected_tables}, img={len(imgs)}")
    raw = s6.api(f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/raw_content", method="GET").get("data", {}).get("content", "")
    if len(raw) < 600:
        raise ValueError(f"[{doc_name}] 回读内容过短: {len(raw)}")
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    body = "\n".join(lines[1:]) if len(lines) > 1 else raw
    check_text_v20(body, f"在线回读-{doc_name}", allow_shell_cmds=allow_shell)
    print(f"  [+] [{doc_name}] 回读通过: 块={len(items)}, 表={len(tbls)}, 图={len(imgs)}, 字符={len(raw)}")
    return {"doc_name": doc_name, "doc_id": doc_id, "blocks_count": len(items), "tables_count": len(tbls),
            "images_count": len(imgs), "raw_chars": len(raw), "first_line_online": lines[1] if len(lines) > 1 else lines[0]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only", type=str, default="")
    args = parser.parse_args()

    specs = [
        ("charter", "task_a_master", build_master_charter_v20_blocks),
        ("1to2", "task_a_master", build_1to2_v20_blocks),
        ("20cm_deepopen", "task_a_new_root", build_20cm_v11_blocks),
        ("3to4", "task_a_master", build_3to4_v41_v20_blocks),
        ("high", "task_a_master", build_high_v51_v20_blocks),
        ("pry", "task_a_master", build_pry_v21_v20_blocks),
        ("2to3", "task_a_master", build_2to3_v21_v20_blocks),
        ("sub11_v20_jianyan", "task_b_subdoc", build_sub11_v20_jianyan_blocks),
        ("sub12_valid_rules", "task_b_subdoc", build_sub12_valid_rules_blocks),
        ("sub13_hot_largecap_falsified", "task_b_subdoc", build_sub13_hot_largecap_falsified_blocks),
    ]
    only_set = set(args.only.split(",")) if args.only else None
    all_items, any_err = [], False
    for key, grp, fn in specs:
        if only_set and key not in only_set:
            continue
        d = fn()
        d["key"], d["group"] = key, grp
        try:
            if grp == "task_b_subdoc":
                s9.check_first_sentence_rule(d)
            if audit_doc_strict_v20(d, require_img=bool(d.get("img_path"))):
                any_err = True
        except Exception as e:
            print(f"[Audit ERR] {key}: {e}")
            any_err = True
        all_items.append(d)
    if any_err:
        raise ValueError("存在违规或超 40 字长句，拒绝发布！")
    if args.dry_run:
        print(f"\n[Dry-Run PASS] 全部 {len(all_items)} 篇 V20.0 文档零长句零违禁通过！")
        return

    lock_fd = open(s6.LOCK_PATH, "w")
    step11_results = []
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        m = json.load(open(s6.MANIFEST_PATH, "r", encoding="utf-8"))
        now_ts = time.strftime("%Y-%m-%d %H:%M:%S")
        for d in all_items:
            title = d["title"]
            if d["group"] == "task_b_subdoc":
                doc_id, node_tok = s9.find_or_create_child_node(d["parent_node_token"], title)
            elif d["group"] == "task_a_new_root":
                doc_id, node_tok = find_or_create_root_node(title)
            else:
                doc_id, node_tok = d["doc_id"], d["node_token"]
                if d["key"] == "charter":
                    r_nd = s6.api(f"{s6.BASE}/open-apis/wiki/v2/spaces/get_node?token={node_tok}", method="GET")
                    if r_nd.get("code") == 0:
                        cur_t = r_nd.get("data", {}).get("node", {}).get("title", "")
                        if cur_t != title:
                            r_up = s6.api(f"{s6.BASE}/open-apis/wiki/v2/spaces/{s6.SPACE_ID}/nodes/{node_tok}/update_title", {"title": title}, "POST")
                            if r_up.get("code") != 0:
                                raise RuntimeError(f"更新总纲标题失败: {r_up}")
                            print(f"  [+] 总纲标题已原地更新: '{cur_t}' -> '{title}'")
                    else:
                        print(f"  [!] 原总纲节点 {node_tok} 已被删除 (code={r_nd.get('code')})，在 ROOT 幂等重建 '{title}'")
                        doc_id, node_tok = find_or_create_root_node(title)
            d["doc_id"], d["node_token"] = doc_id, node_tok
            if doc_id in s6.PROTECTED_DOCS:
                raise RuntimeError(f"受保护文档阻断: {title} ({doc_id})")
            _, fail = s6.write_document_payload(doc_id, d["blocks"], d["tables"], d.get("img_path"))
            if fail > 0:
                raise RuntimeError(f"[{title}] 写入失败 {fail} 块")
            time.sleep(1.2)
            v = verify_document_v20(doc_id, title, len(d["tables"]), bool(d.get("img_path")), allow_shell=(d["key"] == "charter"))
            v.update({"node_token": node_tok, "wiki_url": f"https://my.feishu.cn/wiki/{node_tok}", "key": d["key"], "group": d["group"]})
            step11_results.append(v)
            rec = {"title": title, "node_token": node_tok, "obj_token": doc_id, "url": v["wiki_url"], "updated_at": now_ts}
            if d["group"] == "task_b_subdoc":
                rec["parent_node_token"] = d["parent_node_token"]
                rec["wiki_url"] = v["wiki_url"]
            m.setdefault("nodes", {})[d["key"]] = rec

        m["last_published_at"], m["step11_published_at"], m["step11_results"] = now_ts, now_ts, step11_results
        res_by_id = {r["doc_id"]: r for r in step11_results}
        merged, seen = [], set()
        for it in m.get("results", []):
            if it.get("doc_id") in res_by_id:
                merged.append(res_by_id[it["doc_id"]])
                seen.add(it["doc_id"])
            else:
                merged.append(it)
        for r in step11_results:
            if r["doc_id"] not in seen:
                merged.append(r)
        m["results"] = merged
        with open(s6.MANIFEST_PATH, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=2)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()

    print("\n=== STEP 11 V20.0 SIX STRATEGIES SYNC DONE ===")
    for r in step11_results:
        print(f"[{r['group']}] {r['doc_name']} | {r['wiki_url']} | doc_id={r['doc_id']} | blk={r['blocks_count']} tbl={r['tables_count']} img={r['images_count']} chars={r['raw_chars']}")


if __name__ == "__main__":
    main()

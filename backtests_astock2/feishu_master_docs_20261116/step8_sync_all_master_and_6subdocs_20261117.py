#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""步骤八：主文档全量对齐 V19.0 顺位 + 6 篇核心回测子文档幂等挂载与全量回读核验"""
import os, sys, json, time, fcntl, argparse

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CUR_DIR)

import step6_upgrade_3strategies_20261117 as s6
from gen_master_charter_v19 import build_master_charter_v19_blocks
from gen_3to4_v40 import build_3to4_v40_blocks
from gen_high_v51 import build_high_v51_blocks
from gen_pry_v10 import build_pry_v10_blocks
from gen_2to3_v20 import build_2to3_v20_blocks
from gen_1to2_v19 import build_1to2_v19_blocks
from gen_4to5_v20 import build_4to5_v20_blocks
from gen_26q4_v2 import build_26q4_v2_blocks
from gen_mutual_upgrade_report import build_mutual_upgrade_report_blocks
from gen_sub1_youzi_rd016 import build_sub1_youzi_blocks
from gen_sub2_2to3_perm120 import build_sub2_2to3_perm120_blocks
from gen_sub3_rd013_rebound import build_sub3_rd013_blocks
from gen_sub4_overfit_8tests import build_sub4_overfit_blocks
from gen_sub5_seasonal_walkforward import build_sub5_seasonal_blocks
from gen_sub6_rd011_v4_120factors import build_sub6_rd011_v4_blocks

# 仅对任务一第8项授权更新的《26Q4专供》解除写保护，其余历史文档绝对锁定
s6.PROTECTED_DOCS.discard("WGtbd6n5Po4llQxEKoVceMsWndb")
# 把本脚本审校阶段发现需要拦截的变量名也加入 EXTRA_BANNED_WORDS
s6.EXTRA_BANNED_WORDS = list(set(s6.EXTRA_BANNED_WORDS + [
    "OPERATEDEPT_CODE", "brk_r10", "dev_10d", "dev_30d", "tight_headroom", "rk_prio", "blended_sr"
]))


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


def check_first_sentence_rule(data: dict):
    els = data["blocks"][0]["text"]["elements"]
    c0 = els[0]["text_run"]["content"]
    bg0 = els[0]["text_run"].get("text_element_style", {}).get("background_color")
    if ("有用" not in c0 and "没用" not in c0) or bg0 != 3:
        raise ValueError(f"[{data['title']}] 第1句话未按硬规格写清有用没用并标黄: {c0} | bg={bg0}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only", type=str, default="", help="comma-separated titles or keys")
    args = parser.parse_args()

    task1_specs = [
        ("charter", build_master_charter_v19_blocks),
        ("3to4", build_3to4_v40_blocks),
        ("high", build_high_v51_blocks),
        ("pry", build_pry_v10_blocks),
        ("2to3", build_2to3_v20_blocks),
        ("1to2", build_1to2_v19_blocks),
        ("4to5", build_4to5_v20_blocks),
        ("26q4", build_26q4_v2_blocks),
        ("mutual_report", build_mutual_upgrade_report_blocks),
    ]
    task2_specs = [
        ("sub1_youzi", build_sub1_youzi_blocks),
        ("sub2_2to3_perm", build_sub2_2to3_perm120_blocks),
        ("sub3_rd013", build_sub3_rd013_blocks),
        ("sub4_overfit", build_sub4_overfit_blocks),
        ("sub5_seasonal", build_sub5_seasonal_blocks),
        ("sub6_rd011", build_sub6_rd011_v4_blocks),
    ]

    all_items = []
    any_long = False
    for grp, specs in [("task1", task1_specs), ("task2", task2_specs)]:
        for key, fn in specs:
            if args.only and key not in args.only.split(","):
                continue
            d = fn()
            d["key"] = key
            d["group"] = grp
            if grp == "task2" or key == "mutual_report":
                check_first_sentence_rule(d)
            longs = s6.audit_doc_strict(d, require_img=bool(d.get("img_path")))
            if longs:
                any_long = True
            all_items.append(d)

    if any_long:
        raise ValueError("存在超 40 字长句，拒绝发布！")
    if args.dry_run:
        print(f"\n[Dry-Run PASS] 全部 {len(all_items)} 篇文档本地严格审核零违规。")
        return

    lock_fd = open(s6.LOCK_PATH, "w")
    step8_results = []
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        m = json.load(open(s6.MANIFEST_PATH, "r", encoding="utf-8"))
        for d in all_items:
            title = d["title"]
            if d["group"] == "task2":
                doc_id, node_tok = find_or_create_child_node(d["parent_node_token"], title)
                d["doc_id"], d["node_token"] = doc_id, node_tok
            else:
                doc_id, node_tok = d["doc_id"], d["node_token"]
            if doc_id in s6.PROTECTED_DOCS:
                raise RuntimeError(f"受保护文档阻断: {title} ({doc_id})")
            done, fail = s6.write_document_payload(doc_id, d["blocks"], d["tables"], d.get("img_path"))
            if fail > 0:
                raise RuntimeError(f"[{title}] 写入失败 {fail} 块")
            time.sleep(1.2)
            v = s6.verify_document(doc_id, title, expected_tables_count=len(d["tables"]), has_img=bool(d.get("img_path")))
            v["node_token"] = node_tok
            v["wiki_url"] = f"https://my.feishu.cn/wiki/{node_tok}"
            v["key"] = d["key"]
            v["group"] = d["group"]
            r_raw = s6.api(f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/raw_content", method="GET")
            lines = [ln.strip() for ln in r_raw.get("data", {}).get("content", "").splitlines() if ln.strip()]
            v["first_line_online"] = lines[1] if len(lines) > 1 else (lines[0] if lines else "")
            step8_results.append(v)
            m.setdefault("nodes", {})[d["key"]] = {
                "title": title, "node_token": node_tok, "obj_token": doc_id, "url": v["wiki_url"]
            }

        now_ts = time.strftime("%Y-%m-%d %H:%M:%S")
        m["last_published_at"] = now_ts
        m["step8_published_at"] = now_ts
        m["step8_results"] = step8_results
        res_by_name = {r["doc_name"]: r for r in step8_results}
        merged, seen = [], set()
        for it in m.get("results", []):
            dn = it.get("doc_name")
            if dn in res_by_name:
                merged.append(res_by_name[dn]); seen.add(dn)
            else:
                merged.append(it)
        for r in step8_results:
            if r["doc_name"] not in seen:
                merged.append(r)
        m["results"] = merged
        with open(s6.MANIFEST_PATH, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=2)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()

    print("\n=== STEP 8 ALL DONE ===")
    for r in step8_results:
        print(f"[{r['group']}] {r['doc_name']} | {r['wiki_url']} | blk={r['blocks_count']} tbl={r['tables_count']} img={r['images_count']} chars={r['raw_chars']}")
        print(f"   L1: {r['first_line_online'][:100]}")


if __name__ == "__main__":
    main()

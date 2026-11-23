#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""步骤十：V19.1 全量红队物理真账校准同步 8 篇飞书主文档 + 1 篇专项校准子文档"""
import os
import sys
import json
import time
import fcntl
import argparse

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CUR_DIR)

import step6_upgrade_3strategies_20261117 as s6
import step9_sync_v191_exits_20261118 as s9

from gen_master_charter_v191 import build_master_charter_v191_blocks
from gen_3to4_v41 import build_3to4_v41_blocks
from gen_high_v51_v191 import build_high_v51_v191_blocks
from gen_pry_v21 import build_pry_v21_blocks
from gen_2to3_v21 import build_2to3_v21_blocks
from gen_1to2_v191 import build_1to2_v191_blocks
from gen_small_hub_v41 import build_small_hub_v41_blocks
from gen_26q4_v21 import build_26q4_v21_blocks
from gen_sub10_redteam_v191 import build_sub10_redteam_v191_blocks

# 对《26Q4专供》解除写保护，其余历史保护文档依然锁定
s6.PROTECTED_DOCS.discard("WGtbd6n5Po4llQxEKoVceMsWndb")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only", type=str, default="", help="comma-separated keys")
    args = parser.parse_args()

    task_a_specs = [
        ("charter", build_master_charter_v191_blocks),
        ("3to4", build_3to4_v41_blocks),
        ("high", build_high_v51_v191_blocks),
        ("pry", build_pry_v21_blocks),
        ("2to3", build_2to3_v21_blocks),
        ("1to2", build_1to2_v191_blocks),
        ("small_hub", build_small_hub_v41_blocks),
        ("26q4", build_26q4_v21_blocks),
    ]
    task_b_specs = [
        ("sub10_redteam_v191", build_sub10_redteam_v191_blocks),
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
                s9.check_first_sentence_rule(d)
            longs = s9.audit_doc_strict_v191(d, require_img=bool(d.get("img_path")))
            if longs:
                any_long = True
            all_items.append(d)

    if any_long:
        raise ValueError("存在超 40 字长句，拒绝发布！")
    if args.dry_run:
        print(f"\n[Dry-Run PASS] 全部 {len(all_items)} 篇文档本地严格审核零违规。")
        return

    lock_fd = open(s6.LOCK_PATH, "w")
    step10_results = []
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        m = json.load(open(s6.MANIFEST_PATH, "r", encoding="utf-8"))
        now_ts = time.strftime("%Y-%m-%d %H:%M:%S")
        for d in all_items:
            title = d["title"]
            if d["group"] == "task_b_subdoc":
                doc_id, node_tok = s9.find_or_create_child_node(d["parent_node_token"], title)
                d["doc_id"], d["node_token"] = doc_id, node_tok
            else:
                doc_id, node_tok = d["doc_id"], d["node_token"]
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
                            print(f"  [!] 更新总纲标题失败: {r_up}")
                        else:
                            print(f"  [+] 已将总纲标题从 '{cur_t}' 更新为 '{title}'")

            if doc_id in s6.PROTECTED_DOCS:
                raise RuntimeError(f"受保护文档阻断: {title} ({doc_id})")

            done, fail = s6.write_document_payload(doc_id, d["blocks"], d["tables"], d.get("img_path"))
            if fail > 0:
                raise RuntimeError(f"[{title}] 写入失败 {fail} 块")
            time.sleep(1.2)
            v = s9.verify_document_v191(
                doc_id,
                title,
                expected_tables_count=len(d["tables"]),
                has_img=bool(d.get("img_path")),
            )
            v["node_token"] = node_tok
            v["wiki_url"] = f"https://my.feishu.cn/wiki/{node_tok}"
            v["key"] = d["key"]
            v["group"] = d["group"]
            step10_results.append(v)

            node_rec = {
                "title": title,
                "node_token": node_tok,
                "obj_token": doc_id,
                "url": v["wiki_url"],
            }
            if d["group"] == "task_b_subdoc":
                node_rec["parent_node_token"] = d["parent_node_token"]
                node_rec["wiki_url"] = v["wiki_url"]
                node_rec["updated_at"] = now_ts
            m.setdefault("nodes", {})[d["key"]] = node_rec

        m["last_published_at"] = now_ts
        m["step10_published_at"] = now_ts
        m["step10_results"] = step10_results
        res_by_id = {r["doc_id"]: r for r in step10_results}
        merged, seen_ids = [], set()
        for it in m.get("results", []):
            did = it.get("doc_id")
            if did in res_by_id:
                merged.append(res_by_id[did])
                seen_ids.add(did)
            else:
                merged.append(it)
        for r in step10_results:
            if r["doc_id"] not in seen_ids:
                merged.append(r)
        m["results"] = merged
        with open(s6.MANIFEST_PATH, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=2)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()

    print("\n=== STEP 10 V19.1 REDTEAM CALIBRATION SYNC DONE ===")
    for r in step10_results:
        print(
            f"[{r['group']}] {r['doc_name']} | {r['wiki_url']} | doc_id={r['doc_id']} | "
            f"blk={r['blocks_count']} tbl={r['tables_count']} img={r['images_count']} chars={r['raw_chars']}"
        )
        print(f"   L1: {r['first_line_online'][:120]}")


if __name__ == "__main__":
    main()

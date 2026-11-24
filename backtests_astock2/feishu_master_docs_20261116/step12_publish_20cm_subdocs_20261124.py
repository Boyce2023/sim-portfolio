#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""步骤十二：在 20cm 根节点下新增并核验 6 篇专属小回测子文档，同步更新 manifest"""
import os, sys, json, time, fcntl, argparse

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CUR_DIR)

import step6_upgrade_3strategies_20261117 as s6
import step9_sync_v191_exits_20261118 as s9
import step11_sync_v20_six_strategies_20261124 as s11

from gen_sub20cm_1_beta_waves import build_sub20cm_1_beta_waves_blocks
from gen_sub20cm_2_native_screen import build_sub20cm_2_native_screen_blocks
from gen_sub20cm_3_scorecard_exits import build_sub20cm_3_scorecard_exits_blocks
from gen_sub20cm_4_redteam_pbo import build_sub20cm_4_redteam_pbo_blocks
from gen_sub20cm_5_dual_seat_synergy import build_sub20cm_5_dual_seat_synergy_blocks
from gen_sub20cm_6_pillars_10cm_veto import build_sub20cm_6_pillars_10cm_veto_blocks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    specs = [
        ("sub20cm_1_beta_waves", build_sub20cm_1_beta_waves_blocks),
        ("sub20cm_2_native_screen", build_sub20cm_2_native_screen_blocks),
        ("sub20cm_3_scorecard_exits", build_sub20cm_3_scorecard_exits_blocks),
        ("sub20cm_4_redteam_pbo", build_sub20cm_4_redteam_pbo_blocks),
        ("sub20cm_5_dual_seat_synergy", build_sub20cm_5_dual_seat_synergy_blocks),
        ("sub20cm_6_pillars_10cm_veto", build_sub20cm_6_pillars_10cm_veto_blocks),
    ]
    items, any_err = [], False
    for key, fn in specs:
        d = fn()
        d["key"], d["group"] = key, "task_c_20cm_subdoc"
        try:
            s9.check_first_sentence_rule(d)
            if s11.audit_doc_strict_v20(d, require_img=False):
                any_err = True
        except Exception as e:
            print(f"[Audit ERR] {key}: {e}")
            any_err = True
        items.append(d)
    if any_err:
        raise ValueError("20cm 子文档存在违规或超 40 字长句，拒绝发布！")
    if args.dry_run:
        print(f"\n[Dry-Run PASS] 全部 {len(items)} 篇 20cm 专属子文档零长句零违禁通过！")
        return

    lock_fd = open(s6.LOCK_PATH, "w")
    step12_results = []
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        m = json.load(open(s6.MANIFEST_PATH, "r", encoding="utf-8"))
        now_ts = time.strftime("%Y-%m-%d %H:%M:%S")
        for d in items:
            title, parent_tok = d["title"], d["parent_node_token"]
            doc_id, node_tok = s9.find_or_create_child_node(parent_tok, title)
            d["doc_id"], d["node_token"] = doc_id, node_tok
            if doc_id in s6.PROTECTED_DOCS:
                raise RuntimeError(f"受保护文档阻断: {title} ({doc_id})")
            _, fail = s6.write_document_payload(doc_id, d["blocks"], d["tables"], None)
            if fail > 0:
                raise RuntimeError(f"[{title}] 写入失败 {fail} 块")
            time.sleep(1.2)
            v = s11.verify_document_v20(doc_id, title, len(d["tables"]), has_img=False, allow_shell=False)
            v.update({"node_token": node_tok, "wiki_url": f"https://my.feishu.cn/wiki/{node_tok}", "key": d["key"], "group": d["group"]})
            step12_results.append(v)
            m.setdefault("nodes", {})[d["key"]] = {
                "title": title, "node_token": node_tok, "obj_token": doc_id,
                "url": v["wiki_url"], "parent_node_token": parent_tok, "wiki_url": v["wiki_url"], "updated_at": now_ts,
            }

        m["last_published_at"], m["step12_published_at"], m["step12_results"] = now_ts, now_ts, step12_results
        res_by_id = {r["doc_id"]: r for r in step12_results}
        merged, seen = [], set()
        for it in m.get("results", []):
            if it.get("doc_id") in res_by_id:
                merged.append(res_by_id[it["doc_id"]])
                seen.add(it["doc_id"])
            else:
                merged.append(it)
        for r in step12_results:
            if r["doc_id"] not in seen:
                merged.append(r)
        m["results"] = merged
        with open(s6.MANIFEST_PATH, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=2)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()

    print("\n=== STEP 12 20CM 6 SUBDOCS PUBLISH DONE ===")
    for r in step12_results:
        print(f"[{r['group']}] {r['doc_name']} | {r['wiki_url']} | doc_id={r['doc_id']} | blk={r['blocks_count']} tbl={r['tables_count']} chars={r['raw_chars']}")


if __name__ == "__main__":
    main()

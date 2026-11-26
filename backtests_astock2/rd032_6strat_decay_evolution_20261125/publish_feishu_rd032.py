#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD032 Feishu Publisher: Generate 2 charts, audit strict pure-Chinese rules,
publish `六策略退化与进化体检` under `有效回测与可用规律` (OPKUwAqCDibLfRkRE87cd2aCnVc),
update Hub Index (IRxgdlpOUoqfV4xVYYGczGurnyD), and verify readback.
"""
import argparse
import fcntl
import json
import sys
import time
from pathlib import Path

assert "yfinance" not in sys.modules, "D12 violation!"

OUT_DIR = Path("/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd032_6strat_decay_evolution_20261125")
FS_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/feishu_master_docs_20261116"
for p in (str(OUT_DIR), FS_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import step6_upgrade_3strategies_20261117 as s6
import step9_sync_v191_exits_20261118 as s9
from build_master_docs import make_blank_line as BL
from rd032_charts import generate_rd032_charts
from rd032_feishu_payload import HUB_VALID_DOC, PARENT_VALID_NODE, TITLE_RD032, build_rd032_payload, build_updated_valid_hub_payload


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", default="2026-11-25")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    ymd = args.as_of.replace("-", "")
    audit_path = OUT_DIR / f"rd032_health_check_{ymd}.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))

    c1_path, c2_path = generate_rd032_charts(audit, str(OUT_DIR))
    print(f"[Charts] Generated {c1_path} & {c2_path}")

    d = build_rd032_payload(audit, c1_path, c2_path)
    hub = build_updated_valid_hub_payload()

    s9.check_first_sentence_rule(d)
    longs = s9.audit_doc_strict_v191(d, require_img=True)
    longs_hub = s9.audit_doc_strict_v191(hub, require_img=False)
    if longs or longs_hub:
        raise ValueError(f"Long sentences found: rd032={len(longs)}, hub={len(longs_hub)}")

    tot_chars = sum(len(e["text_run"]["content"]) for b in d["blocks"] for e in b.get("text", b.get("bullet", b.get("ordered", {}))).get("elements", []))
    tot_chars += sum(len(t) for t, _ in d["tables"])
    tot_chars += sum(len("".join(x for x, _ in cell)) for _, rows in d["tables"] for rw in rows for cell in rw)
    print(f"[Audit] RD032 local total chars = {tot_chars} (>= 1500 required)")
    if tot_chars < 1500:
        raise ValueError(f"RD032 total chars {tot_chars} < 1500")

    if args.dry_run:
        print("[Dry-Run PASS] Zero audit errors on RD032 & Valid Hub!")
        return

    lock_fd = open(s6.LOCK_PATH, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        doc_id, node_tok = s9.find_or_create_child_node(PARENT_VALID_NODE, TITLE_RD032)
        if doc_id in s6.PROTECTED_DOCS:
            raise RuntimeError(f"Protected: {doc_id}")
        _, fail = s6.write_document_payload(doc_id, d["blocks"], d["tables"], d["img_path"])
        if fail > 0:
            raise RuntimeError(f"Write failed: {fail}")
        s6.insert_image_block(doc_id, d["img_path2"])
        s6.api(
            f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children",
            {"children": [BL(), BL(), BL()], "index": -1},
            "POST",
        )
        time.sleep(1.5)
        v = s9.verify_document_v191(doc_id, TITLE_RD032, expected_tables_count=len(d["tables"]), has_img=True)
        url = f"https://my.feishu.cn/wiki/{node_tok}"

        _, fail2 = s6.write_document_payload(HUB_VALID_DOC, hub["blocks"], hub["tables"], None)
        if fail2 > 0:
            raise RuntimeError(f"Hub write fail={fail2}")
        time.sleep(1.2)
        vhub = s9.verify_document_v191(HUB_VALID_DOC, "有效回测与可用规律", expected_tables_count=1, has_img=False)

        mf = json.load(open(s6.MANIFEST_PATH, "r", encoding="utf-8"))
        mf.setdefault("nodes", {})["rd032_6strat_decay_evolution"] = {
            "title": TITLE_RD032,
            "node_token": node_tok,
            "obj_token": doc_id,
            "parent_node_token": PARENT_VALID_NODE,
            "wiki_url": url,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        json.dump(mf, open(s6.MANIFEST_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

        pub_res = {
            "wiki_url": url,
            "node_token": node_tok,
            "doc_id": doc_id,
            "parent_node_token": PARENT_VALID_NODE,
            "verify": v,
            "hub_verify": vhub,
        }
        with open(OUT_DIR / "feishu_publish_result.json", "w", encoding="utf-8") as f:
            json.dump(pub_res, f, ensure_ascii=False, indent=2)
        print(f"[SUCCESS] RD032 URL={url} | chars={v['raw_chars']} | tables={v['tables_count']} | images={v['images_count']}")
        print(f"[SUCCESS] VALID HUB URL=https://my.feishu.cn/wiki/{PARENT_VALID_NODE} | chars={vhub['raw_chars']}")
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    main()

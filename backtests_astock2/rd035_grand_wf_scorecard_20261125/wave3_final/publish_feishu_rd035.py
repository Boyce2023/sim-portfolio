#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Feishu Publisher: Generate 2 charts, audit strict pure-Chinese & zero-jargon rules,
publish `多因子打分前视镜总阅兵` under `有效回测与可用规律` (OPKUwAqCDibLfRkRE87cd2aCnVc),
incrementally update Hub Index (IRxgdlpOUoqfV4xVYYGczGurnyD), and verify online readback.
"""
import argparse
import fcntl
import json
import re
import sys
import time
from pathlib import Path

assert "yfinance" not in sys.modules, "D12 violation!"

W3_DIR = Path("/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave3_final")
FS_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/feishu_master_docs_20261116"
for p in (str(W3_DIR), FS_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import step6_upgrade_3strategies_20261117 as s6
import step9_sync_v191_exits_20261118 as s9
from build_master_docs import make_blank_line as BL
from rd035_charts import generate_rd035_charts
from rd035_feishu_payload import (
    HUB_VALID_DOC,
    PARENT_VALID_NODE,
    TITLE_RD035,
    build_rd035_payload,
    build_updated_valid_hub_payload,
)

# Extra zero-jargon ban specific to RD035 (strict plain Chinese)
RD035_EXTRA_JARGON = [
    "WF", "OOS", "IS", "PIT", "BH-FDR", "DSR", "CSCV", "PBO", "LOO", "PLR",
    "MDD", "NAV", "Sharpe", "Calmar", "q值", "p值", "t值",
    "消融", "重锚", "回灌", "门禁", "闭环", "矩阵", "铁证", "铁律",
]
RD035_LATIN_TOKEN_RE = re.compile(r"\b(?:WF|OOS|IS|PIT|BH-FDR|DSR|CSCV|PBO|LOO|PLR|MDD|NAV|Sharpe|Calmar)\b")


def audit_zero_jargon_rd035(d: dict):
    texts = [d["title"]]
    for b in d["blocks"]:
        bt = b["block_type"]
        els = b.get("text", b.get("bullet", b.get("ordered", {}))).get("elements", [])
        texts.append("".join(e["text_run"]["content"] for e in els))
    for t_title, t_rows in d["tables"]:
        texts.append(t_title)
        for rw in t_rows:
            for cell in rw:
                texts.append("".join(x for x, _ in cell))

    cn_jargon = ["q值", "p值", "t值", "消融", "重锚", "回灌", "门禁", "闭环", "矩阵", "铁证", "铁律"]
    for t in texts:
        m = RD035_LATIN_TOKEN_RE.search(t)
        if m:
            raise ValueError(f"RD035 发现禁用统计英文缩写 '{m.group(0)}': {t}")
        for jw in cn_jargon:
            if jw in t:
                raise ValueError(f"RD035 发现禁用黑话 '{jw}': {t}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    audit_a = json.loads((W3_DIR / "w3_2_redteam_audit_a/w3_2_redteam_a_audit.json").read_text(encoding="utf-8"))
    audit_b = json.loads((W3_DIR / "w3_3_redteam_audit_b/w3_3_redteam_b_audit.json").read_text(encoding="utf-8"))
    audit_w1 = json.loads((W3_DIR / "w3_1_v20_assembly/w3_1_assembly_audit.json").read_text(encoding="utf-8"))

    c1_path, c2_path = generate_rd035_charts(audit_a, audit_b, str(W3_DIR))
    print(f"[Charts] Generated {c1_path} & {c2_path}")

    d = build_rd035_payload(audit_a, audit_b, audit_w1, c1_path, c2_path)
    hub = build_updated_valid_hub_payload()

    s9.check_first_sentence_rule(d)
    audit_zero_jargon_rd035(d)
    audit_zero_jargon_rd035(hub)
    longs = s9.audit_doc_strict_v191(d, require_img=True)
    longs_hub = s9.audit_doc_strict_v191(hub, require_img=False)
    if longs or longs_hub:
        raise ValueError(f"Long sentences found: rd035={len(longs)}, hub={len(longs_hub)}")

    tot_chars = sum(len(e["text_run"]["content"]) for b in d["blocks"] for e in b.get("text", b.get("bullet", b.get("ordered", {}))).get("elements", []))
    tot_chars += sum(len(t) for t, _ in d["tables"])
    tot_chars += sum(len("".join(x for x, _ in cell)) for _, rows in d["tables"] for rw in rows for cell in rw)
    print(f"[Audit] RD035 local total chars = {tot_chars}")

    if args.dry_run:
        print("[Dry-Run PASS] Zero audit errors on RD035 & Valid Hub!")
        return

    lock_fd = open(s6.LOCK_PATH, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        doc_id, node_tok = s9.find_or_create_child_node(PARENT_VALID_NODE, TITLE_RD035)
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
        v = s9.verify_document_v191(doc_id, TITLE_RD035, expected_tables_count=len(d["tables"]), has_img=True)
        # Re-run zero-jargon audit on online raw_content
        r_raw = s6.api(f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/raw_content", method="GET")
        online_raw = r_raw.get("data", {}).get("content", "")
        m_on = RD035_LATIN_TOKEN_RE.search(online_raw)
        if m_on:
            raise ValueError(f"Online raw_content jargon hit: {m_on.group(0)}")
        for jw in ["q值", "p值", "t值", "消融", "重锚", "回灌", "门禁", "闭环", "矩阵", "铁证", "铁律"]:
            if jw in online_raw:
                raise ValueError(f"Online raw_content CN jargon hit: {jw}")

        url = f"https://my.feishu.cn/wiki/{node_tok}"

        _, fail2 = s6.write_document_payload(HUB_VALID_DOC, hub["blocks"], hub["tables"], None)
        if fail2 > 0:
            raise RuntimeError(f"Hub write fail={fail2}")
        time.sleep(1.2)
        vhub = s9.verify_document_v191(HUB_VALID_DOC, "有效回测与可用规律", expected_tables_count=1, has_img=False)

        mf = json.load(open(s6.MANIFEST_PATH, "r", encoding="utf-8"))
        mf.setdefault("nodes", {})["rd035_grand_wf_scorecard"] = {
            "title": TITLE_RD035,
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
            "online_raw_chars": len(online_raw),
        }
        with open(W3_DIR / "feishu_publish_result.json", "w", encoding="utf-8") as f:
            json.dump(pub_res, f, ensure_ascii=False, indent=2)
        print(f"[SUCCESS] RD035 URL={url} | chars={v['raw_chars']} | tables={v['tables_count']} | images={v['images_count']}")
        print(f"[SUCCESS] VALID HUB URL=https://my.feishu.cn/wiki/{PARENT_VALID_NODE} | chars={vhub['raw_chars']} | tables={vhub['tables_count']}")
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    main()

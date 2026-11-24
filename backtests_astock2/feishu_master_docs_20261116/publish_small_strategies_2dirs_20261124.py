#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Reorganize Feishu `小策略` (MNp3wiZMWihVBDkZrnRcAFJanOg) into 2 clean subdirectories:
1. 有效小策略 (moves 政策 + 跨年大票 here + publishes 5 actionable valid small-strategy pages)
2. 无效与已淘汰小策略 (moves 四进五 + 大跌切银行与退潮切消费证伪 here)
Also updates `小策略` homepage to clean V20.0 taxonomy (6 大主力在外，零千万封顶).
"""
import fcntl, os, sys, time, requests

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CUR_DIR)
import step6_upgrade_3strategies_20261117 as s6
import step9_sync_v191_exits_20261118 as s9
from small_strat_pages_20261124 import build_5_valid_small_strategy_docs, build_small_hub_pages

SMALL_ROOT = "MNp3wiZMWihVBDkZrnRcAFJanOg"
SMALL_DOC_ID = "UVEWdG2ZqoJqXqxdbJNcNZM1nme"
TITLE_VALID = "有效小策略"
TITLE_INVALID = "无效与已淘汰小策略"

MOVE_TO_VALID = [
    ("YSDKwKuQciRq0ekDVw9c5LnRnDe", "政策"),
    ("LKxlwXFzpiHBykk1ZGDcsTQ8nVd", "跨年大票"),
]
MOVE_TO_INVALID = [
    ("PYIMwgtOVi2R8pk4VCOcPHiInDb", "四进五"),
    ("OgR8wMtbUi21IZkaAELcIBk1nSh", "大跌切银行与退潮切消费证伪"),
]


def ls_kids(pt: str):
    hdr = {"Authorization": f"Bearer {s6.tok()}"}
    d = requests.get(f"https://open.feishu.cn/open-apis/wiki/v2/spaces/{s6.SPACE_ID}/nodes", params={"parent_node_token": pt, "page_size": 50}, headers=hdr, timeout=10).json().get("data", {})
    return d.get("items", [])


def move_node(nt: str, target_pt: str):
    hdr = {"Authorization": f"Bearer {s6.tok()}", "Content-Type": "application/json"}
    r = requests.post(f"https://open.feishu.cn/open-apis/wiki/v2/spaces/{s6.SPACE_ID}/nodes/{nt}/move", headers=hdr, json={"target_parent_token": target_pt, "target_space_id": s6.SPACE_ID}, timeout=15).json()
    if r.get("code") != 0:
        raise RuntimeError(f"Move {nt} -> {target_pt} failed: {r}")


def write_and_verify(doc_id: str, payload: dict):
    s9.audit_doc_strict_v191(payload, require_img=False)
    done, fail = s6.write_document_payload(doc_id, payload["blocks"], payload["tables"], None)
    if fail > 0:
        raise RuntimeError(f"Write fail={fail} on {payload['title']}")
    time.sleep(0.8)
    s9.verify_document_v191(doc_id, payload["title"], expected_tables_count=len(payload["tables"]), has_img=False)


def main():
    # Pre-audit all 8 payloads locally BEFORE touching Feishu
    docs_5 = build_5_valid_small_strategy_docs()
    main_hub, valid_hub, invalid_hub = build_small_hub_pages()
    for p in docs_5 + [main_hub, valid_hub, invalid_hub]:
        s9.audit_doc_strict_v191(p, require_img=False)
    print("PRE_AUDIT ALL 8 PAYLOADS PASSED 100%!")

    s6.PROTECTED_DOCS.discard(SMALL_DOC_ID)
    lock_fd = open(s6.LOCK_PATH, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        v_doc, v_node = s9.find_or_create_child_node(SMALL_ROOT, TITLE_VALID)
        i_doc, i_node = s9.find_or_create_child_node(SMALL_ROOT, TITLE_INVALID)

        # Move existing 4 children under 小策略 into the 2 new folders
        cur_root = {k["node_token"] for k in ls_kids(SMALL_ROOT)}
        for nt, nm in MOVE_TO_VALID:
            if nt in cur_root:
                move_node(nt, v_node)
                print(f"MOVED_VALID {nm} [{nt}]")
                time.sleep(0.25)
        for nt, nm in MOVE_TO_INVALID:
            if nt in cur_root:
                move_node(nt, i_node)
                print(f"MOVED_INVALID {nm} [{nt}]")
                time.sleep(0.25)

        # Publish remaining new valid small-strategy pages under 有效小策略
        already_ok = {
            "美股大跌接科创50（588080）", "大哥护盘宽基爆量抄底", "六大商品股期联动波段",
            "暴跌尾盘切高ROE城商行", "本土风格双强底仓（小市值与大盘低波）",
        }
        for p in docs_5:
            if p["title"] in already_ok:
                print(f"SKIP_VERIFIED {p['title']}")
                continue
            did, ntk = s9.find_or_create_child_node(v_node, p["title"])
            write_and_verify(did, p)
            print(f"PUBLISHED_VALID [{ntk}] {p['title']} -> https://my.feishu.cn/wiki/{ntk}")

        # Write and verify all 3 hub pages
        write_and_verify(SMALL_DOC_ID, main_hub)
        write_and_verify(v_doc, valid_hub)
        write_and_verify(i_doc, invalid_hub)

        rk, vk, ik = ls_kids(SMALL_ROOT), ls_kids(v_node), ls_kids(i_node)
        print(f"\nFINAL SMALL_STRATEGY AUDIT: root={len(rk)} | valid={len(vk)} | invalid={len(ik)}")
        print(f"  小策略首页: https://my.feishu.cn/wiki/{SMALL_ROOT}")
        print(f"  有效小策略 ({len(vk)}): https://my.feishu.cn/wiki/{v_node}")
        for x in vk:
            print(f"    * [{x['node_token']}] {x['title']} (https://my.feishu.cn/wiki/{x['node_token']})")
        print(f"  无效与已淘汰小策略 ({len(ik)}): https://my.feishu.cn/wiki/{i_node}")
        for x in ik:
            print(f"    * [{x['node_token']}] {x['title']} (https://my.feishu.cn/wiki/{x['node_token']})")
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    main()

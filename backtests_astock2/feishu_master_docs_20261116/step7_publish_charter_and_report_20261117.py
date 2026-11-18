#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""步骤七：新建《A股短线五策略体系总纲（V19.0 定版）》与《三大连板策略跨板位互学升级五年实证报告》，并升级《小策略》"""
import os
import sys
import json
import time
import fcntl
import argparse

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CUR_DIR)

import step6_upgrade_3strategies_20261117 as s6
from gen_master_charter_v19 import build_master_charter_v19_blocks
from gen_small_hub_v4 import build_small_hub_v4_blocks
from gen_mutual_upgrade_report import build_mutual_upgrade_report_blocks


def list_all_root_nodes() -> dict:
    """列出知识库根目录全部节点，按 title 建立索引"""
    nodes_by_title = {}
    page_token = ""
    while True:
        qs = "page_size=50" + (f"&page_token={page_token}" if page_token else "")
        r = s6.api(f"{s6.BASE}/open-apis/wiki/v2/spaces/{s6.SPACE_ID}/nodes?{qs}", method="GET")
        if r.get("code") != 0:
            raise RuntimeError(f"获取知识库根节点列表失败: {r}")
        data = r.get("data", {})
        for item in data.get("items") or []:
            nodes_by_title[item.get("title")] = {
                "title": item.get("title"),
                "node_token": item.get("node_token"),
                "obj_token": item.get("obj_token"),
                "obj_type": item.get("obj_type"),
            }
        if not data.get("has_more"):
            break
        page_token = data.get("page_token") or ""
        if not page_token:
            break
    return nodes_by_title


def find_or_create_root_node(title: str, existing_roots: dict) -> tuple[str, str]:
    """幂等获取或创建知识库根节点，返回 (obj_token/doc_id, node_token)"""
    if title in existing_roots:
        info = existing_roots[title]
        doc_id = info["obj_token"]
        node_token = info["node_token"]
        print(f"  [*] 复用已存在根节点 [{title}]: doc_id={doc_id}, node_token={node_token}")
        return doc_id, node_token

    r_create = s6.api(
        f"{s6.BASE}/open-apis/wiki/v2/spaces/{s6.SPACE_ID}/nodes",
        {"obj_type": "docx", "node_type": "origin", "title": title},
        "POST",
    )
    if r_create.get("code") != 0:
        raise RuntimeError(f"创建知识库根节点 [{title}] 失败: {r_create}")
    node = r_create["data"]["node"]
    node_token = node["node_token"]
    doc_id = node["obj_token"]
    existing_roots[title] = {
        "title": title,
        "node_token": node_token,
        "obj_token": doc_id,
        "obj_type": "docx",
    }
    print(f"  [+] 新建知识库根节点 [{title}]: doc_id={doc_id}, node_token={node_token}")
    time.sleep(0.5)
    return doc_id, node_token


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="仅做本地严格审核，不调用飞书接口")
    args = parser.parse_args()

    builders = [
        ("charter", build_master_charter_v19_blocks),
        ("small_hub", build_small_hub_v4_blocks),
        ("mutual_report", build_mutual_upgrade_report_blocks),
    ]

    datasets = []
    any_long = False
    for key, fn in builders:
        data = fn()
        data["manifest_key"] = key
        longs = s6.audit_doc_strict(data, require_img=bool(data.get("img_path")))
        if longs:
            any_long = True
        datasets.append(data)

    if any_long:
        raise ValueError("存在超40字长句，请先全部拆短至 <= 40 字")

    if args.dry_run:
        print("\n[Dry-Run PASS] 三篇文档本地严格审核全部零违规。")
        return

    print("\n=== 开始执行飞书知识库收尾发布与全量核验 ===")
    lock_fd = open(s6.LOCK_PATH, "w")
    step7_results = []
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        print("[*] 已获取全局飞书发布文件锁")

        existing_roots = list_all_root_nodes()
        print(f"[*] 当前知识库根节点数量: {len(existing_roots)}")

        m = json.load(open(s6.MANIFEST_PATH, "r", encoding="utf-8"))
        nodes_map = m.setdefault("nodes", {})

        for data in datasets:
            name = data["title"]
            key = data["manifest_key"]
            doc_id = data.get("doc_id")
            node_token = data.get("node_token")

            if not doc_id or not node_token:
                doc_id, node_token = find_or_create_root_node(name, existing_roots)
                data["doc_id"] = doc_id
                data["node_token"] = node_token

            if doc_id in s6.PROTECTED_DOCS:
                raise RuntimeError(f"[{name}] 命中受保护文档 {doc_id}")

            info = s6.api(f"{s6.BASE}/open-apis/wiki/v2/spaces/{s6.SPACE_ID}/nodes/{node_token}", method="GET")
            node_obj = info.get("data", {}).get("node", {})
            cur_obj_tok = node_obj.get("obj_token")
            print(f"\n[*] 核对 Wiki 节点 [{name}]: obj_token={cur_obj_tok}, target={doc_id}")
            if cur_obj_tok and cur_obj_tok != doc_id:
                raise RuntimeError(f"[{name}] Wiki obj_token 不匹配: {cur_obj_tok} != {doc_id}")

            has_img = bool(data.get("img_path"))
            done, fail = s6.write_document_payload(doc_id, data["blocks"], data["tables"], data.get("img_path"))
            print(f"[+] 写入完成: 成功 {done} 块, 失败 {fail} 块")
            if fail > 0:
                raise RuntimeError(f"[{name}] 写入存在失败块: {fail}")

            time.sleep(1.5)
            v_res = s6.verify_document(doc_id, name, expected_tables_count=len(data["tables"]), has_img=has_img)
            v_res["node_token"] = node_token
            v_res["wiki_url"] = f"https://my.feishu.cn/wiki/{node_token}"
            step7_results.append(v_res)

            nodes_map[key] = {
                "title": name,
                "node_token": node_token,
                "obj_token": doc_id,
                "url": v_res["wiki_url"],
            }

        now_ts = time.strftime("%Y-%m-%d %H:%M:%S")
        m["last_published_at"] = now_ts
        res_by_name = {r["doc_name"]: r for r in step7_results}
        old_results = m.get("results", [])
        new_results = []
        seen = set()
        for item in old_results:
            dn = item.get("doc_name")
            if dn in res_by_name:
                new_results.append(res_by_name[dn])
                seen.add(dn)
            else:
                new_results.append(item)
        for r in step7_results:
            if r["doc_name"] not in seen:
                new_results.append(r)
        m["results"] = new_results
        m["step7_published_at"] = now_ts
        m["step7_results"] = step7_results

        with open(s6.MANIFEST_PATH, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=2)

        print("\n=== 步骤七发布与在线回读核验全部通过 ===")
        for r in step7_results:
            print(
                f"• 【{r['doc_name']}】: {r['wiki_url']} | doc_id={r['doc_id']} | "
                f"块数={r['blocks_count']} 表格={r['tables_count']} 图片={r['images_count']} 字符={r['raw_chars']}"
            )
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()
        print("[*] 已释放全局飞书发布文件锁")


if __name__ == "__main__":
    main()

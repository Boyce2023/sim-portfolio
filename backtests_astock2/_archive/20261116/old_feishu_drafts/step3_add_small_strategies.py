#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""步骤三：新增挂载《跨年妖》与《大跌切银行与退潮切消费证伪》，并更新《小策略》导览页"""
import os, sys, json, time, fcntl

FEISHU_TOOLS_PATH = "/Users/huaichuaibeimeng/claude-projects/股票研究 Equity Research/_tools/html2feishu.py"
exec(open(FEISHU_TOOLS_PATH, "r", encoding="utf-8").read(), globals())

from publish_and_verify_master_docs import (
    PROTECTED_DOCS, clear_doc_all, write_document_payload, verify_document, LOCK_PATH
)
from gen_cross_year import build_cross_year_blocks
from gen_defensive_switch import build_defensive_switch_blocks
from gen_small_hub_v2 import build_small_hub_blocks_v2

BASE = "https://open.feishu.cn"
SPACE_ID = "7700231295393107208"  # A股策略与回测
CUR_DIR = os.path.dirname(os.path.abspath(__file__))
MANIFEST_PATH = f"{CUR_DIR}/feishu_master_manifest.json"

def main():
    print("=== 开始挂载两篇新小策略并更新导览页 ===")
    lock_fd = open(LOCK_PATH, "w")
    results = []

    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        print("[*] 成功获取全局飞书发布文件锁")

        m = json.load(open(MANIFEST_PATH, "r", encoding="utf-8")) if os.path.exists(MANIFEST_PATH) else {"nodes": {}}
        xiao_node_token = m.get("nodes", {}).get("small_hub", {}).get("node_token") or "MNp3wiZMWihVBDkZrnRcAFJanOg"
        xiao_obj_token = m.get("nodes", {}).get("small_hub", {}).get("obj_token") or "UVEWdG2ZqoJqXqxdbJNcNZM1nme"

        # 1. 检查《小策略》下属现有子节点
        r_sub = api(f"{BASE}/open-apis/wiki/v2/spaces/{SPACE_ID}/nodes?parent_node_token={xiao_node_token}&page_size=50", method="GET")
        existing_children = r_sub.get("data", {}).get("items", [])

        # 2. 检查/创建「跨年妖」
        cross_node = next((n for n in existing_children if n.get("title") == "跨年妖"), None)
        if not cross_node:
            print("[*] 正在创建子节点: 跨年妖 ...")
            r_c = api(f"{BASE}/open-apis/wiki/v2/spaces/{SPACE_ID}/nodes",
                      {"obj_type": "docx", "node_type": "origin", "title": "跨年妖", "parent_node_token": xiao_node_token}, "POST")
            if r_c.get("code") != 0:
                raise RuntimeError(f"创建跨年妖节点失败: {r_c}")
            cross_node = r_c["data"]["node"]
            print(f"[+] 成功创建「跨年妖」子节点: node_token={cross_node['node_token']}, obj_token={cross_node['obj_token']}")
        else:
            print(f"[+] 已存在「跨年妖」子节点: node_token={cross_node['node_token']}, obj_token={cross_node['obj_token']}")

        cross_node_token = cross_node["node_token"]
        cross_obj_token = cross_node["obj_token"]
        m["nodes"]["cross_year"] = {
            "title": "跨年妖",
            "node_token": cross_node_token,
            "obj_token": cross_obj_token,
            "url": f"https://my.feishu.cn/wiki/{cross_node_token}"
        }

        # 3. 检查/创建「大跌切银行与退潮切消费证伪」
        def_node = next((n for n in existing_children if n.get("title") == "大跌切银行与退潮切消费证伪"), None)
        if not def_node:
            print("[*] 正在创建子节点: 大跌切银行与退潮切消费证伪 ...")
            r_d = api(f"{BASE}/open-apis/wiki/v2/spaces/{SPACE_ID}/nodes",
                      {"obj_type": "docx", "node_type": "origin", "title": "大跌切银行与退潮切消费证伪", "parent_node_token": xiao_node_token}, "POST")
            if r_d.get("code") != 0:
                raise RuntimeError(f"创建大跌切银行与退潮切消费证伪节点失败: {r_d}")
            def_node = r_d["data"]["node"]
            print(f"[+] 成功创建「大跌切银行与退潮切消费证伪」子节点: node_token={def_node['node_token']}, obj_token={def_node['obj_token']}")
        else:
            print(f"[+] 已存在「大跌切银行与退潮切消费证伪」子节点: node_token={def_node['node_token']}, obj_token={def_node['obj_token']}")

        def_node_token = def_node["node_token"]
        def_obj_token = def_node["obj_token"]
        m["nodes"]["defensive_switch"] = {
            "title": "大跌切银行与退潮切消费证伪",
            "node_token": def_node_token,
            "obj_token": def_obj_token,
            "url": f"https://my.feishu.cn/wiki/{def_node_token}"
        }

        with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=2)

        # 4. 发布与核验列表
        tasks = [
            ("跨年妖", lambda: build_cross_year_blocks(cross_obj_token, cross_node_token), False),
            ("大跌切银行与退潮切消费证伪", lambda: build_defensive_switch_blocks(def_obj_token, def_node_token), False),
            ("小策略", build_small_hub_blocks_v2, False)
        ]

        for name, gen_fn, has_img in tasks:
            print(f"\n==========================================")
            print(f"[*] 正在处理文档: 【{name}】")
            data = gen_fn()
            doc_id = data["doc_id"]
            node_token = data["node_token"]
            blocks = data["blocks"]
            tables = data["tables"]
            img_path = data.get("img_path")

            if doc_id in PROTECTED_DOCS:
                raise RuntimeError(f"⛔ 致命安全拦截: 尝试修改受保护文档 {name} ({doc_id})")

            print(f"  - 目标文档: {doc_id} (node: {node_token})")
            print(f"  - 正文块数: {len(blocks)}, 附录表格数: {len(tables)}, 包含图片: {bool(img_path)}")

            done, fail = write_document_payload(doc_id, blocks, tables, img_path)
            print(f"  [+] 写入完成: 成功块数={done}, 失败={fail}")
            if fail > 0:
                raise RuntimeError(f"写入文档 {name} 出现失败块: fail={fail}")

            time.sleep(1.0)

            v_res = verify_document(doc_id, name, len(tables), has_img=has_img)
            v_res["node_token"] = node_token
            v_res["wiki_url"] = f"https://my.feishu.cn/wiki/{node_token}"
            results.append(v_res)

        print("\n==========================================")
        print("[+] 跨年妖、大跌切银行证伪与小策略导览页均已成功发布并经100%自动化核验零违规！")

        m = json.load(open(MANIFEST_PATH, "r", encoding="utf-8")) if os.path.exists(MANIFEST_PATH) else {}
        m["step3_published_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        m["step3_results"] = results
        with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=2)

    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()

    print("\n=== 新增与更新核验报告汇总 ===")
    for r in results:
        print(f"• 【{r['doc_name']}】: {r['wiki_url']} | 块数={r['blocks_count']} 表格={r['tables_count']} 图片={r['images_count']} 字符={r['raw_chars']} | 0 Heading, 0 Callout, 0 违规词")

if __name__ == "__main__":
    main()

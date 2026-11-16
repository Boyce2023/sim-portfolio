#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""步骤四：重写《跨年大票》正文与更新《小策略》导览页并全量核验"""
import os, sys, json, time, fcntl

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(CUR_DIR)

FEISHU_TOOLS_PATH = "/Users/huaichuaibeimeng/claude-projects/股票研究 Equity Research/_tools/html2feishu.py"
exec(open(FEISHU_TOOLS_PATH, "r", encoding="utf-8").read(), globals())

from publish_and_verify_master_docs import (
    PROTECTED_DOCS, clear_doc_all, write_document_payload, verify_document, LOCK_PATH
)
from gen_cross_year_big import build_cross_year_big_blocks
from gen_small_hub_v3 import build_small_hub_blocks_v3

BASE = "https://open.feishu.cn"
SPACE_ID = "7700231295393107208"  # A股策略与回测
MANIFEST_PATH = f"{CUR_DIR}/feishu_master_manifest.json"

def main():
    print("=== 开始更新《跨年大票》与《小策略》导览页 ===")
    lock_fd = open(LOCK_PATH, "w")
    results = []

    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        print("[*] 成功获取全局飞书发布文件锁")

        m = json.load(open(MANIFEST_PATH, "r", encoding="utf-8")) if os.path.exists(MANIFEST_PATH) else {"nodes": {}}
        cross_node_token = "LKxlwXFzpiHBykk1ZGDcsTQ8nVd"
        cross_obj_token = "H6hfdLSs1oCPaOxLAJqc434HnZd"
        hub_node_token = "MNp3wiZMWihVBDkZrnRcAFJanOg"
        hub_obj_token = "UVEWdG2ZqoJqXqxdbJNcNZM1nme"

        # 1. 确认 Wiki 节点标题
        info = api(f"{BASE}/open-apis/wiki/v2/spaces/{SPACE_ID}/nodes/{cross_node_token}", method="GET")
        cur_title = info.get("data", {}).get("node", {}).get("title")
        if cur_title != "跨年大票":
            print(f"[*] 当前标题为 '{cur_title}'，正在更新为 '跨年大票' ...")
            r_up = api(f"{BASE}/open-apis/wiki/v2/spaces/{SPACE_ID}/nodes/{cross_node_token}/update_title",
                       {"title": "跨年大票"}, method="POST")
            if r_up.get("code") != 0:
                raise RuntimeError(f"更新节点标题失败: {r_up}")
            print("[+] 成功更新 Wiki 节点标题为: 跨年大票")
        else:
            print("[+] Wiki 节点标题已确认为: 跨年大票")

        # 更新 manifest 节点信息
        m["nodes"]["cross_year_big"] = {
            "title": "跨年大票",
            "node_token": cross_node_token,
            "obj_token": cross_obj_token,
            "url": f"https://my.feishu.cn/wiki/{cross_node_token}"
        }
        if "cross_year" in m.get("nodes", {}):
            del m["nodes"]["cross_year"]

        # 2. 发布任务列表
        tasks = [
            ("跨年大票", lambda: build_cross_year_big_blocks(cross_obj_token, cross_node_token), False),
            ("小策略", build_small_hub_blocks_v3, False)
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

            # 写入并清空重构
            print(f"[*] 正在写入文档块并组装附录表格: doc_id={doc_id} ...")
            done, fail = write_document_payload(doc_id, blocks, tables, img_path)
            print(f"[+] 写入完成: 成功 {done} 块, 失败 {fail} 块")
            if fail > 0:
                raise RuntimeError(f"[{name}] 写入过程中存在失败块: {fail}")

            # 在线读回像素级核验
            time.sleep(1.0)
            res = verify_document(doc_id, name, expected_tables_count=len(tables), has_img=has_img)
            res["node_token"] = node_token
            res["wiki_url"] = f"https://my.feishu.cn/wiki/{node_token}"
            results.append(res)

        m["step4_published_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        m["step4_results"] = results
        with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=2)

        print("\n==========================================")
        print("🎉 全部文档重写与核验顺利完成！")
        for r in results:
            print(f"  - 【{r['doc_name']}】: 总块数={r['blocks_count']}, 表格数={r['tables_count']}, 字符数={r['raw_chars']}, 链接={r['wiki_url']}")

    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()
        print("[*] 已释放全局飞书发布文件锁")

if __name__ == "__main__":
    main()

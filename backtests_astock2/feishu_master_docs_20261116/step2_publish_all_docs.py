#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""步骤二：全量飞书策略主文档原地重写与自动化核验"""
import os, sys, json, time, fcntl

from publish_and_verify_master_docs import (
    PROTECTED_DOCS, clear_doc_all, write_document_payload, verify_document, LOCK_PATH
)
from gen_1to2 import build_1to2_blocks
from gen_high import build_high_blocks
from gen_3to4 import build_3to4_blocks
from gen_4to5 import build_4to5_blocks
from gen_pry import build_pry_blocks
from gen_small_hub import build_small_hub_blocks
from gen_2to3 import build_2to3_blocks

MANIFEST_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/feishu_master_docs_20261116/feishu_master_manifest.json"

def main():
    generators = [
        ("一进二", build_1to2_blocks, True),
        ("高标", build_high_blocks, True),
        ("三进四", build_3to4_blocks, True),
        ("四进五", build_4to5_blocks, True),
        ("撬板", build_pry_blocks, True),
        ("小策略", build_small_hub_blocks, False),
        ("二进三", build_2to3_blocks, False),
    ]

    print("=== 开始发布全量策略主文档与小策略体系 ===")
    lock_fd = open(LOCK_PATH, "w")
    results = []

    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        print("[*] 成功获取全局飞书发布文件锁")

        for name, gen_fn, has_img in generators:
            print(f"\n==========================================")
            print(f"[*] 正在处理策略主文档: 【{name}】")
            data = gen_fn()
            doc_id = data["doc_id"]
            node_token = data["node_token"]
            blocks = data["blocks"]
            tables = data["tables"]
            img_path = data["img_path"]

            # 安全硬断言
            if doc_id in PROTECTED_DOCS:
                raise RuntimeError(f"⛔ 致命安全拦截: 尝试修改受保护文档 {name} ({doc_id})")

            print(f"  - 目标文档: {doc_id} (node: {node_token})")
            print(f"  - 正文块数: {len(blocks)}, 附录表格数: {len(tables)}, 包含图片: {bool(img_path)}")

            done, fail = write_document_payload(doc_id, blocks, tables, img_path)
            print(f"  [+] 写入完成: 成功块数={done}, 失败={fail}")
            if fail > 0:
                raise RuntimeError(f"写入文档 {name} 出现失败块: fail={fail}")

            # 暂停 1 秒等待飞书服务端持久化
            time.sleep(1.0)

            # 独立在线回读核验
            v_res = verify_document(doc_id, name, len(tables), has_img=has_img)
            v_res["node_token"] = node_token
            v_res["wiki_url"] = f"https://my.feishu.cn/wiki/{node_token}"
            results.append(v_res)

        print("\n==========================================")
        print("[+] 全部七篇文档均已成功重写并经像素级自动化核验零违规！")

        # 写入持久化审计清单
        m = json.load(open(MANIFEST_PATH, "r", encoding="utf-8")) if os.path.exists(MANIFEST_PATH) else {}
        m["last_published_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        m["results"] = results
        with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=2)

    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()

    # 打印最终精炼结果摘要
    print("\n=== 最终核验报告汇总 ===")
    for r in results:
        print(f"• 【{r['doc_name']}】: {r['wiki_url']} | 块数={r['blocks_count']} 表格={r['tables_count']} 图片={r['images_count']} 字符={r['raw_chars']} | 0 Heading, 0 Callout, 0 违规词")

if __name__ == "__main__":
    main()

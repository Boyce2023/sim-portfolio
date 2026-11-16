#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""步骤一：知识库小策略体系节点创建与归口移动"""
import os, sys, json, time

FEISHU_TOOLS_PATH = "/Users/huaichuaibeimeng/claude-projects/股票研究 Equity Research/_tools/html2feishu.py"
exec(open(FEISHU_TOOLS_PATH, "r", encoding="utf-8").read(), globals())

BASE = "https://open.feishu.cn"
SPACE_ID = "7700231295393107208"  # A股策略与回测
CUR_DIR = os.path.dirname(os.path.abspath(__file__))
MANIFEST_PATH = f"{CUR_DIR}/feishu_master_manifest.json"

def run_step1():
    print("=== 开始知识库节点创建与归口移动 ===")
    
    # 0. 读取或初始化 manifest
    m = {}
    if os.path.exists(MANIFEST_PATH):
        m = json.load(open(MANIFEST_PATH, "r", encoding="utf-8"))
    if "nodes" not in m:
        m["nodes"] = {}

    # 1. 检查/创建顶层 L0 节点「小策略」
    r_list = api(f"{BASE}/open-apis/wiki/v2/spaces/{SPACE_ID}/nodes?page_size=50", method="GET")
    top_items = r_list.get("data", {}).get("items", [])
    xiao_node = next((n for n in top_items if n.get("title") == "小策略"), None)
    
    if not xiao_node:
        print("[*] 正在创建顶层节点: 小策略 ...")
        r_create = api(f"{BASE}/open-apis/wiki/v2/spaces/{SPACE_ID}/nodes",
                       {"obj_type": "docx", "node_type": "origin", "title": "小策略"}, "POST")
        if r_create.get("code") != 0:
            raise RuntimeError(f"创建小策略节点失败: {r_create}")
        xiao_node = r_create["data"]["node"]
        print(f"[+] 成功创建顶层节点「小策略」: node_token={xiao_node['node_token']}, obj_token={xiao_node['obj_token']}")
    else:
        print(f"[+] 已存在顶层节点「小策略」: node_token={xiao_node['node_token']}, obj_token={xiao_node['obj_token']}")
        
    xiao_node_token = xiao_node["node_token"]
    xiao_obj_token = xiao_node["obj_token"]
    m["nodes"]["small_hub"] = {
        "title": "小策略",
        "node_token": xiao_node_token,
        "obj_token": xiao_obj_token,
        "url": f"https://my.feishu.cn/wiki/{xiao_node_token}"
    }

    # 2. 移动「撬板」(OZWdwif0ui7DpWksrwGc3lNRnIh) 到「小策略」下方
    pry_node_token = "OZWdwif0ui7DpWksrwGc3lNRnIh"
    pry_info = api(f"{BASE}/open-apis/wiki/v2/spaces/{SPACE_ID}/nodes/{pry_node_token}", method="GET")
    pry_parent = pry_info.get("data", {}).get("node", {}).get("parent_node_token", "")
    if pry_parent != xiao_node_token:
        print(f"[*] 正在将「撬板」移入「小策略」(target_parent_token={xiao_node_token}) ...")
        r_move_pry = api(f"{BASE}/open-apis/wiki/v2/spaces/{SPACE_ID}/nodes/{pry_node_token}/move",
                         {"target_parent_token": xiao_node_token}, "POST")
        if r_move_pry.get("code") != 0:
            raise RuntimeError(f"移动撬板节点失败: {r_move_pry}")
        print("[+] 成功移动「撬板」至「小策略」")
    else:
        print("[+] 「撬板」已在「小策略」下方")
    time.sleep(0.5)

    # 3. 移动「四进五」(PYIMwgtOVi2R8pk4VCOcPHiInDb) 到「小策略」下方
    four_node_token = "PYIMwgtOVi2R8pk4VCOcPHiInDb"
    four_info = api(f"{BASE}/open-apis/wiki/v2/spaces/{SPACE_ID}/nodes/{four_node_token}", method="GET")
    four_parent = four_info.get("data", {}).get("node", {}).get("parent_node_token", "")
    if four_parent != xiao_node_token:
        print(f"[*] 正在将「四进五」移入「小策略」(target_parent_token={xiao_node_token}) ...")
        r_move_four = api(f"{BASE}/open-apis/wiki/v2/spaces/{SPACE_ID}/nodes/{four_node_token}/move",
                          {"target_parent_token": xiao_node_token}, "POST")
        if r_move_four.get("code") != 0:
            raise RuntimeError(f"移动四进五节点失败: {r_move_four}")
        print("[+] 成功移动「四进五」至「小策略」")
    else:
        print("[+] 「四进五」已在「小策略」下方")
    time.sleep(0.5)

    # 4. 在「小策略」下方检查/创建「二进三」节点
    r_sub = api(f"{BASE}/open-apis/wiki/v2/spaces/{SPACE_ID}/nodes?parent_node_token={xiao_node_token}&page_size=50", method="GET")
    xiao_children = r_sub.get("data", {}).get("items", [])
    er_jin_san_node = next((n for n in xiao_children if n.get("title") == "二进三"), None)

    if not er_jin_san_node:
        print("[*] 正在「小策略」下方创建子节点: 二进三 ...")
        r_create_23 = api(f"{BASE}/open-apis/wiki/v2/spaces/{SPACE_ID}/nodes",
                          {"obj_type": "docx", "node_type": "origin", "title": "二进三", "parent_node_token": xiao_node_token}, "POST")
        if r_create_23.get("code") != 0:
            raise RuntimeError(f"创建二进三子节点失败: {r_create_23}")
        er_jin_san_node = r_create_23["data"]["node"]
        print(f"[+] 成功创建「二进三」子节点: node_token={er_jin_san_node['node_token']}, obj_token={er_jin_san_node['obj_token']}")
    else:
        print(f"[+] 已存在「二进三」子节点: node_token={er_jin_san_node['node_token']}, obj_token={er_jin_san_node['obj_token']}")

    er_node_token = er_jin_san_node["node_token"]
    er_obj_token = er_jin_san_node["obj_token"]
    m["nodes"]["2to3"] = {
        "title": "二进三",
        "node_token": er_node_token,
        "obj_token": er_obj_token,
        "url": f"https://my.feishu.cn/wiki/{er_node_token}"
    }

    # 5. 将二进三回测副文档 (MdInwLHmMiC1Cmkrz4McuUb9nle) 移动到「二进三」下方
    sub_23_node_token = "MdInwLHmMiC1Cmkrz4McuUb9nle"
    sub_23_info = api(f"{BASE}/open-apis/wiki/v2/spaces/{SPACE_ID}/nodes/{sub_23_node_token}", method="GET")
    sub_23_parent = sub_23_info.get("data", {}).get("node", {}).get("parent_node_token", "")
    if sub_23_parent != er_node_token:
        print(f"[*] 正在将二进三回测副文档移入「二进三」(target_parent_token={er_node_token}) ...")
        r_move_sub23 = api(f"{BASE}/open-apis/wiki/v2/spaces/{SPACE_ID}/nodes/{sub_23_node_token}/move",
                           {"target_parent_token": er_node_token}, "POST")
        if r_move_sub23.get("code") != 0:
            raise RuntimeError(f"移动二进三回测副文档失败: {r_move_sub23}")
        print("[+] 成功移动二进三回测副文档至「二进三」下方")
    else:
        print("[+] 二进三回测副文档已在「二进三」下方")

    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)

    print("\n=== 步骤一完成！当前小策略体系结构 ===")
    r_sub_final = api(f"{BASE}/open-apis/wiki/v2/spaces/{SPACE_ID}/nodes?parent_node_token={xiao_node_token}&page_size=50", method="GET")
    for it in r_sub_final.get("data", {}).get("items", []):
        print(f"  - 小策略子节点: {it.get('title')} (node_token={it.get('node_token')})")
        # 如果是二进三，查看其子文档
        if it.get("node_token") == er_node_token:
            r_sub_23 = api(f"{BASE}/open-apis/wiki/v2/spaces/{SPACE_ID}/nodes?parent_node_token={er_node_token}&page_size=50", method="GET")
            for sit in r_sub_23.get("data", {}).get("items", []):
                print(f"      * 二进三副文档: {sit.get('title')} (node_token={sit.get('node_token')})")

    return xiao_node_token, er_node_token, er_obj_token

if __name__ == "__main__":
    run_step1()

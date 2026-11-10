import sys, json, time
sys.path.insert(0, "/Users/huaichuaibeimeng/claude-projects/股票研究 Equity Research/_tools")
from html2feishu import api

SPACE_ID = "7681220535547743183"

print("--- 1. 测试空间详情 ---")
space_res = api(f"https://open.feishu.cn/open-apis/wiki/v2/spaces/{SPACE_ID}", method="GET")
print("Space Get Response:", json.dumps(space_res, ensure_ascii=False))

print("\n--- 2. 测试创建临时根节点 ---")
create_payload = {
    "obj_type": "docx",
    "node_type": "origin",
    "title": "_API权限自检临时节点"
}
node1_res = api(f"https://open.feishu.cn/open-apis/wiki/v2/spaces/{SPACE_ID}/nodes", data=create_payload, method="POST")
print("Create Root Node Response:", json.dumps(node1_res, ensure_ascii=False))

node1_token = node1_res.get("data", {}).get("node", {}).get("node_token")
node1_obj = node1_res.get("data", {}).get("node", {}).get("obj_token")

if not node1_token:
    print("创建根节点失败，终止后续测试")
    sys.exit(1)

print(f"成功创建根节点: node_token={node1_token}, obj_token={node1_obj}")
time.sleep(0.5)

print("\n--- 3. 测试在父节点下创建子节点 ---")
child_payload = {
    "obj_type": "docx",
    "node_type": "origin",
    "parent_node_token": node1_token,
    "title": "_API权限自检子节点"
}
child_res = api(f"https://open.feishu.cn/open-apis/wiki/v2/spaces/{SPACE_ID}/nodes", data=child_payload, method="POST")
print("Create Child Node Response:", json.dumps(child_res, ensure_ascii=False))
child_node_token = child_res.get("data", {}).get("node", {}).get("node_token")
child_obj_token = child_res.get("data", {}).get("node", {}).get("obj_token")
time.sleep(0.5)

print("\n--- 4. 测试修改标题 (update_title) ---")
# 飞书Wiki v2端点: POST /open-apis/wiki/v2/spaces/{space_id}/nodes/{node_token}/update_title
title_res = api(f"https://open.feishu.cn/open-apis/wiki/v2/spaces/{SPACE_ID}/nodes/{child_node_token}/update_title",
                data={"title": "_API权限自检子节点_重命名成功"}, method="POST")
print("Update Title Response:", json.dumps(title_res, ensure_ascii=False))
time.sleep(0.5)

print("\n--- 5. 测试移动节点 (move) ---")
# 测试将子节点移动到空间根节点 (target_parent_token为空字符串或省略)
# 飞书API: POST /open-apis/wiki/v2/spaces/{space_id}/nodes/{node_token}/move
move_payload = {
    "target_parent_token": "",
    "target_space_id": SPACE_ID
}
move_res = api(f"https://open.feishu.cn/open-apis/wiki/v2/spaces/{SPACE_ID}/nodes/{child_node_token}/move",
               data=move_payload, method="POST")
print("Move Node Response:", json.dumps(move_res, ensure_ascii=False))
time.sleep(0.5)

print("\n--- 6. 测试删除节点 ---")
# 测试方法 A: DELETE /open-apis/wiki/v2/spaces/{space_id}/nodes/{node_token} (如果有)
# 测试方法 B: DELETE /open-apis/drive/v1/files/{obj_token}?type=docx
# 测 child 节点
print("尝试方案 A (Wiki v2 delete node):")
del_wiki_res = api(f"https://open.feishu.cn/open-apis/wiki/v2/spaces/{SPACE_ID}/nodes/{child_node_token}", method="DELETE")
print("Wiki delete response:", json.dumps(del_wiki_res, ensure_ascii=False))

if del_wiki_res.get("code") != 0:
    print("尝试方案 B (Drive v1 delete file):")
    del_drive_res = api(f"https://open.feishu.cn/open-apis/drive/v1/files/{child_obj_token}?type=docx", method="DELETE")
    print("Drive delete response:", json.dumps(del_drive_res, ensure_ascii=False))

# 删除根测试节点
print("\n删除根测试节点 node1:")
del_wiki_res2 = api(f"https://open.feishu.cn/open-apis/wiki/v2/spaces/{SPACE_ID}/nodes/{node1_token}", method="DELETE")
print("Wiki delete response for root node:", json.dumps(del_wiki_res2, ensure_ascii=False))
if del_wiki_res2.get("code") != 0:
    del_drive_res2 = api(f"https://open.feishu.cn/open-apis/drive/v1/files/{node1_obj}?type=docx", method="DELETE")
    print("Drive delete response for root obj:", json.dumps(del_drive_res2, ensure_ascii=False))

#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
import json

exec(open("/Users/huaichuaibeimeng/claude-projects/股票研究 Equity Research/_tools/html2feishu.py", "r", encoding="utf-8").read(), globals())
BASE = "https://open.feishu.cn"
SID = "7700231295393107208"
OLD_MAIN_NODE = "UwgOwQ0JeikYszky4XVcN2Rknye"
MANIFEST_P = "/Users/huaichuaibeimeng/claude-projects/output/csrc_policy_100factors_20261114/feishu_csrc_wiki_manifest.json"

nodes = api(f"{BASE}/open-apis/wiki/v2/spaces/{SID}/nodes?page_size=50", method="GET")["data"]["items"]
pol_node = next((n for n in nodes if n["title"].strip() == "政策"), None)
if not pol_node:
    r_create = api(f"{BASE}/open-apis/wiki/v2/spaces/{SID}/nodes", {"obj_type": "docx", "node_type": "origin", "title": "政策"}, "POST")
    assert r_create.get("code") == 0, f"Create failed: {r_create}"
    pol_node = r_create["data"]["node"]
    print("Created root node 政策:", pol_node["node_token"], pol_node["obj_token"])
else:
    print("Found existing root node 政策:", pol_node["node_token"], pol_node["obj_token"])

pol_tok = pol_node["node_token"]
pol_doc = pol_node["obj_token"]

r_move = api(f"{BASE}/open-apis/wiki/v2/spaces/{SID}/nodes/{OLD_MAIN_NODE}/move", {
    "target_parent_token": pol_tok,
    "target_space_id": SID
}, "POST")
print("Move result:", r_move)

rb = api(f"{BASE}/open-apis/docx/v1/documents/{pol_doc}/raw_content", method="GET").get("data", {}).get("content", "").strip()
if len(rb) < 20:
    idx_blocks = [
        {"block_type": 3, "heading1": {"elements": [{"text_run": {"content": "政策与高层发言实证专题目录"}}]}},
        {"block_type": 2, "text": {"elements": [{"text_run": {"content": "本目录归口收纳证监会历任主席、中央政治局会议、中央经济与金融工作会议、多部委联合政策及交易所监管动作的无未来函数量化回测与最新讲话拆解。", "text_element_style": {"background_color": 3}}}]}},
        {"block_type": 12, "bullet": {"elements": [{"text_run": {"content": "20261114 证监会与高层发言预见性144因子回测及吴清最新讲话拆解（含01至03三篇子文档）：https://my.feishu.cn/wiki/UwgOwQ0JeikYszky4XVcN2Rknye", "text_element_style": {"bold": True}}}]}}
    ]
    api(f"{BASE}/open-apis/docx/v1/documents/{pol_doc}/blocks/{pol_doc}/children", {"children": idx_blocks, "index": -1}, "POST")

m = json.load(open(MANIFEST_P, encoding="utf-8"))
m["nodes"]["policy_root"] = {
    "key": "policy_root", "title": "政策", "node_token": pol_tok, "obj_token": pol_doc,
    "parent_node_token": "", "url": f"https://my.feishu.cn/wiki/{pol_tok}"
}
m["nodes"]["csrc_main"]["parent_node_token"] = pol_tok
json.dump(m, open(MANIFEST_P, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

print("=== FINAL VERIFIED TREE IN A股策略与回测 ===")
for nd in api(f"{BASE}/open-apis/wiki/v2/spaces/{SID}/nodes?page_size=50", method="GET")["data"]["items"]:
    print("ROOT:", nd["node_token"], "|", nd["title"])
    if nd["node_token"] == pol_tok:
        for ch in api(f"{BASE}/open-apis/wiki/v2/spaces/{SID}/nodes?parent_node_token={pol_tok}&page_size=50", method="GET")["data"].get("items", []):
            ct = ch["node_token"]
            print("  CHILD:", ct, "|", ch["title"])
            for gch in api(f"{BASE}/open-apis/wiki/v2/spaces/{SID}/nodes?parent_node_token={ct}&page_size=50", method="GET")["data"].get("items", []):
                print("    SUBCHILD:", gch["node_token"], "|", gch["title"])

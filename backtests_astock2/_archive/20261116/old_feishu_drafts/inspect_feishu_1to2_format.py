#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
exec(open("/Users/huaichuaibeimeng/claude-projects/股票研究 Equity Research/_tools/html2feishu.py", "r", encoding="utf-8").read(), globals())
BASE = "https://open.feishu.cn"

sp = api(f"{BASE}/open-apis/wiki/v2/spaces?page_size=50", method="GET")
for s in sp.get("data", {}).get("items", []):
    sid, sname = s["space_id"], s["name"]
    print(f"=== SPACE: {sid} | {sname} ===")
    r = api(f"{BASE}/open-apis/wiki/v2/spaces/{sid}/nodes?page_size=50", method="GET")
    for nd in r.get("data", {}).get("items", []):
        nt, ot, t, hc = nd["node_token"], nd["obj_token"], nd["title"], nd.get("has_child")
        print(f"  [L0] {t} | node={nt} | doc={ot} | has_child={hc}")
        if hc:
            r2 = api(f"{BASE}/open-apis/wiki/v2/spaces/{sid}/nodes?parent_node_token={nt}&page_size=50", method="GET")
            for c in r2.get("data", {}).get("items", []):
                cnt, cot, ct, chc = c["node_token"], c["obj_token"], c["title"], c.get("has_child")
                print(f"      [L1] {ct} | node={cnt} | doc={cot} | has_child={chc}")
                if chc:
                    r3 = api(f"{BASE}/open-apis/wiki/v2/spaces/{sid}/nodes?parent_node_token={cnt}&page_size=50", method="GET")
                    for c2 in r3.get("data", {}).get("items", []):
                        print(f"          [L2] {c2['title']} | node={c2['node_token']} | doc={c2['obj_token']}")

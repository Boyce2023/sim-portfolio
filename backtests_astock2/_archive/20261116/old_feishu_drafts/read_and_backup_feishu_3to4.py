#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
import json, os
exec(open("/Users/huaichuaibeimeng/claude-projects/股票研究 Equity Research/_tools/html2feishu.py", "r", encoding="utf-8").read(), globals())
BASE = "https://open.feishu.cn"
CUR_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2"

docs = {
    "1to2_main": "OeJed4uL5oQ2nRxeOXIc4HronDe",
    "1to2_sub_hub": "RTiqd555Soj78vx3GOdcqEO9nze",
    "1to2_sub_01": "LNkwd1BquoSpAyxUvzEclxIlne7",
    "high_main": "HexPdpU4uowtfZx1IIscgIKrnce",
    "3to4_main_existing": "SFPVd9gSgoN33SxMsUHc4xJNnVf",
}

os.makedirs(f"{CUR_DIR}/feishu_backup_20261113", exist_ok=True)
for k, did in docs.items():
    rc = api(f"{BASE}/open-apis/docx/v1/documents/{did}/raw_content", method="GET")
    txt = rc.get("data", {}).get("content", "")
    blks = api(f"{BASE}/open-apis/docx/v1/documents/{did}/blocks?page_size=500", method="GET")
    with open(f"{CUR_DIR}/feishu_backup_20261113/{k}_{did}.txt", "w", encoding="utf-8") as f:
        f.write(txt)
    with open(f"{CUR_DIR}/feishu_backup_20261113/{k}_{did}_blocks.json", "w", encoding="utf-8") as f:
        json.dump(blks, f, ensure_ascii=False, indent=2)
    print(f"=== {k} ({did}) chars={len(txt)} ===")
    print(txt[:1500])
    print("\n" + "="*60 + "\n")

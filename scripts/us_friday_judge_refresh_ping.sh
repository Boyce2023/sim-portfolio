#!/bin/bash
# 每周五 15:37 投递美股判断层刷新指令 (2026-10-29 收口至 Antigravity 原生唤醒链路)
# 用法: bash us_friday_judge_refresh_ping.sh [--dry-run]

DRY_RUN=0
if [ "${1:-}" = "--dry-run" ]; then
  DRY_RUN=1
else
  [ "$(date +%u)" != "5" ] && exit 0
fi

/opt/homebrew/bin/python3 - "$DRY_RUN" <<'PY'
import datetime
import json
import os
import subprocess
import sys

dry_run = sys.argv[1] == "1"
now = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
inbox_dir = os.path.expanduser("~/.claude/session-inbox")
reg_us = os.path.expanduser("~/.claude/session-registry/us.json")
agy_bin = "/Users/huaichuaibeimeng/.gemini/bin/agy"

instruction = (
    "【每周五·美股判断层刷新】目录 research-notes/us-database/2026-08-24_打分/："
    "①先跑 python3 rebuild_mech.py 与 python3 combine.py 刷新 composite.json；"
    "②跑 python3 build_judge_batches.py YYYY-MM-DD M/D 生成最新批次 judge_batches.json 与 judge_args.json（严禁复用旧批次价格）；"
    "③在 Antigravity 内按批次并行调用 invoke_subagent 对四维（supply_constraint / cash_conversion / catalyst / bear_severity，0至10分）独立打分并汇总为 journal.jsonl；"
    "④跑 python3 ingest_judge.py <journal.jsonl> YYYYMMDD 执行量程校验并更新 agent_scores.json；"
    "⑤再跑 python3 combine.py 生成最新综合分。"
    "幂等保护：若本周已完成刷新则直接跳过。完成后飞书回执。"
)

rec = {
    "ts": now,
    "from": "us-judge-refresh-cron",
    "kind": "task",
    "instruction": instruction,
}

conv_id = None
if os.path.exists(reg_us):
    try:
        with open(reg_us, encoding="utf-8") as f:
            conv_id = json.load(f).get("conversation_id")
    except Exception:
        conv_id = None

if dry_run:
    print(f"[dry-run] target_conv_id={conv_id} agy_exists={os.path.exists(agy_bin)}")
    print(json.dumps(rec, ensure_ascii=False, indent=2))
    sys.exit(0)

delivered = False
if conv_id and os.path.exists(agy_bin):
    try:
        res = subprocess.run(
            [agy_bin, "agentapi", "send-message", conv_id, instruction],
            capture_output=True,
            text=True,
            timeout=30,
        )
        delivered = res.returncode == 0
    except Exception:
        delivered = False

os.makedirs(os.path.join(inbox_dir, "_consumed"), exist_ok=True)
if delivered:
    rec["delivered_via"] = "agy_agentapi"
    with open(os.path.join(inbox_dir, "_consumed", "us.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"friday judge ping delivered directly to {conv_id}")
else:
    with open(os.path.join(inbox_dir, "us.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("friday judge ping queued to us.jsonl fallback for inbox-watchdog")
PY

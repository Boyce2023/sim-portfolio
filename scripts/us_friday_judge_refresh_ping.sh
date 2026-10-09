#!/bin/bash
# 每周五15:37投递判断层刷新指令(原session-local cron随重启死, 2026-09-02改launchd)
[ "$(date +%u)" != "5" ] && exit 0
printf '{"ts":"%s","from":"us-judge-refresh-cron","kind":"task","instruction":"【每周五·判断层刷新】①先跑 rebuild_mech.py+combine.py 刷新 composite ②python3 build_judge_batches.py 今天日期 最近收盘M/D 生成批次并用其 judge_args.json 重写 workflows/judge-refresh-inline.js(⛔不要直接跑旧 inline, 里面价格与日期是写死的) ③quota_gate 放行后跑该工作流 ④python3 ingest_judge.py <journal.jsonl> YYYYMMDD(带0到10量程校验, 越界退回上一版) ⑤再跑 combine.py。目录 research-notes/us-database/2026-08-24_打分/。⛔幂等: 本周已刷则跳过。完成后飞书回执。"}\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" >> ~/.claude/session-inbox/us.jsonl

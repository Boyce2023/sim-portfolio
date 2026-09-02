#!/bin/bash
# 每周五15:37投递判断层刷新指令(原session-local cron随重启死, 2026-09-02改launchd)
[ "$(date +%u)" != "5" ] && exit 0
printf '{"ts":"%s","from":"us-judge-refresh-cron","kind":"task","instruction":"【每周五·判断层刷新】跑 workflows/judge-refresh-inline.js 刷新230只的agent判断分(供给侧/现金转化/催化/熊方), 替换 research-notes/us-database/2026-08-24_打分/agent_scores.json 并备份旧版为 agent_scores_YYYYMMDD.json.bak, 再跑combine.py。⛔幂等: 本周已刷则跳过。完成后飞书回执。"}\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" >> ~/.claude/session-inbox/us.jsonl

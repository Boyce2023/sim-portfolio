#!/bin/bash
# 每周一投递维护体检提示到astock inbox(2026-08-27维护建立)。监听中的session会收到并执行。
printf '{"ts":"%s","from":"weekly-maintenance-cron","kind":"maintenance","instruction":"【周期维护】执行精简版体检: ①外部数据源探活 ②后台任务验活(产出mtime vs now) ③push探针状态(/tmp/push_all_failcount) ④MEMORY.md对账 ⑤本周声称完成的复验2项。发现问题按维护流程处理,回执发飞书(fs-reply.sh)。参考: memory_cases/case_background_task_blind_spot.md + feedback_progress_reporting"}\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" >> ~/.claude/session-inbox/astock.jsonl

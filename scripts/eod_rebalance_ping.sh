#!/bin/bash
# 每交易日16:00投递收盘后完整调仓指令到astock inbox (2026-09-02 Buwen令:"以后每天下午4点自动去做")
DOW=$(date +%u); [ "$DOW" -gt 5 ] && exit 0
printf '{"ts":"%s","from":"eod-rebalance-cron","kind":"task","instruction":"【每日必备·A股收盘后完整调仓 16:00】用今日全天收盘数据做四步完整调仓: ①完整报告(持仓全表+多周regime+板块资金) ②扫描(astock_v3_screening带今日date,20树全市场) ③深度研究(真读probes/watches/holdings_review逐只裁决,大客户断言必一手核验) ④执行(下单reason写清依据,零候选也要说清为什么零)。SOP见sim-portfolio/CLAUDE.md调仓流程定义。⛔四件缺一不可。⛔若本session今天16:00后已在做则忽略(幂等)。非交易日报一句跳过。完成后飞书回执+更新晨报要点。"}\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" >> ~/.claude/session-inbox/astock.jsonl

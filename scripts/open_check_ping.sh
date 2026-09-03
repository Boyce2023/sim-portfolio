#!/bin/bash
# 每交易日09:26投递开盘检查指令(2026-09-02建): 执行前夜裁决的挂单+核B验证+灾难线
DOW=$(date +%u); [ "$DOW" -gt 5 ] && exit 0
printf '{"ts":"%s","from":"open-check-cron","kind":"task","instruction":"【每日09:26开盘检查】①执行昨夜16:00收盘版裁决中标注\\"明早开盘执行\\"的单子(读watchlist_config.json status=pending_open) ②核data/b_live_log.jsonl里verify_date=今天的B选板开盘价并写result ③拉全持仓开盘价,距灾难线<3%的列出 ④一句飞书回执。幂等:今天已做则忽略。"}\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" >> ~/.claude/session-inbox/astock.jsonl

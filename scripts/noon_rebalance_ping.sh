#!/bin/bash
# 每交易日12:01投递午间调仓指令到astock inbox (2026-08-28 Buwen固化令,跨session兜底)
DOW=$(date +%u); [ "$DOW" -gt 5 ] && exit 0
printf '{"ts":"%s","from":"noon-rebalance-cron","kind":"task","instruction":"【每日必备·A股午间完整调仓】根据早上收盘价做四步完整调仓(报告+扫描+深研+执行,SOP见sim-portfolio/CLAUDE.md调仓流程定义)。⛔若本session今天已在做/已完成午间调仓则忽略本条(幂等)。非交易日报一句跳过。完成后飞书回执。"}\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" >> ~/.claude/session-inbox/astock.jsonl

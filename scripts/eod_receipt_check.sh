#!/bin/bash
# 16:40检查16:00收盘版调仓是否有回执标记(2026-09-02建,治"ping投了没人接"): 无标记→飞书报警
DOW=$(date +%u); [ "$DOW" -gt 5 ] && exit 0
M=~/claude-projects/sim-portfolio/data/eod_done/$(date +%Y%m%d)
if [ ! -f "$M" ]; then bash ~/.claude/session-remote/fs-reply.sh "[astock⚠️告警] 16:00收盘版调仓ping已投40分钟无回执标记($M不存在)——astock session可能未在听(进程重启/监听死)。请Buwen或main唤醒astock: 打开astock session发一句'16:00调仓'即可。"; fi

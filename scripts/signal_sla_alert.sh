#!/bin/bash
# pending信号超SLA自动报警 (2026-08-27 Buwen自动化令落地)
# 逻辑: pending里critical>24h / high>48h 未消费 → 飞书报警(每天最多1次,防刷屏由no_spam_worry原则约束但合并成单条)
P=~/.claude/nexus/signals/pending
NOW=$(date +%s); OUT=""
for f in "$P"/sig-*.json; do
  [ -e "$f" ] || continue
  AGE_H=$(( (NOW - $(stat -f %m "$f")) / 3600 ))
  PRI=$(python3 -c "import json;print(json.load(open('$f')).get('priority','low'))" 2>/dev/null)
  TITLE=$(python3 -c "import json;print(json.load(open('$f')).get('title','?')[:50])" 2>/dev/null)
  if { [ "$PRI" = "critical" ] && [ "$AGE_H" -ge 24 ]; } || { [ "$PRI" = "high" ] && [ "$AGE_H" -ge 48 ]; }; then
    OUT="$OUT\n· [$PRI ${AGE_H}h] $TITLE"
  fi
done
if [ -n "$OUT" ]; then
  bash ~/.claude/session-remote/fs-reply.sh "[astock·SLA报警] pending信号超期未消费:$(printf "$OUT")\n→ 各session检查自己域的signals/pending"
fi

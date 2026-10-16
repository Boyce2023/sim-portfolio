#!/bin/bash
# us session 收件箱等待: 有"需要动作"的消息才退出(叫醒 session); 未命中持仓情报/哨兵例行/抽检 静默归档。
# 放在仓库里而非 /tmp: 原 scratchpad 版 10-13 被临时目录清理删掉(exit 127)。
# 单实例锁: 10-16 实测两个等待进程抢同一文件(mv 报错且同一条消息被交付两次)
LOCK=/tmp/us_inbox_wait.lock
if ! mkdir "$LOCK" 2>/dev/null; then
  if [ -f "$LOCK/pid" ] && kill -0 "$(cat $LOCK/pid)" 2>/dev/null; then echo "已有等待进程 $(cat $LOCK/pid), 本次退出" >&2; exit 3; fi
  rm -rf "$LOCK"; mkdir "$LOCK"
fi
echo $$ > "$LOCK/pid"; trap 'rm -rf "$LOCK"' EXIT
INBOX="$HOME/.claude/session-inbox/us.jsonl"; ARC="$HOME/.claude/session-inbox/_digest/us.jsonl"
mkdir -p "$(dirname "$ARC")"; touch "$INBOX"
while true; do
  if [ -s "$INBOX" ]; then
    mv "$INBOX" "$INBOX.p"; touch "$INBOX"
    OUT=$(/usr/bin/python3 - "$INBOX.p" "$ARC" <<'PY'
import json,sys
src,arc=sys.argv[1],sys.argv[2]
for l in open(src):
    l=l.strip()
    if not l: continue
    try: d=json.loads(l)
    except: print(l[:300]); continue
    ins=str(d.get('instruction') or d.get('text') or '')
    skip=(('产业链情报' in ins and '未命中持仓' in ins) or d.get('from')=='main-dropdigest'
          or (d.get('from')=='us-sentinel-daemon' and ('非指令' in ins or '扳机A条件①达成' in ins)))
    if skip: open(arc,'a').write(l+'\n')
    else: print(d.get('ts','')[:16], d.get('from',''), '|', ins[:500])
PY
)
    rm -f "$INBOX.p"
    if [ -n "$OUT" ]; then echo "$OUT"; exit 0; fi
  fi
  sleep 5
done

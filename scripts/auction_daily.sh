#!/bin/bash
# ⛔⛔第一行, 每天必读: 模拟盘的买卖是我自主决策+执行+事后报告, **不请示**。
# Buwen 07-09定, 08-26/27/09-08已复发四次。他的原话: "你的决策权大于我, 你就直接调仓,
# 这已经是我们说过非常多次的事情了, 我完全没法理解为什么你会忘, 如果你真的会忘为什么不代码化"。
# 选好股→立刻告诉他; 到最早可交易时点→自己执行; 成交→立刻报他。三步都不等确认。
# 竞价采集每日入口 — launchd 调用。⛔承诺下沉: 结果自动推送, 不依赖任何session活着"记得报"
cd /Users/huaichuaibeimeng/claude-projects/sim-portfolio || exit 1
PY="/opt/homebrew/bin/python3"; LOG=/tmp/auction_collect.log
DAY=$(date '+%Y-%m-%d')
{ echo "=========== $DAY $(date '+%H:%M:%S') 竞价采集 ==========="
  env -u HTTPS_PROXY -u HTTP_PROXY $PY scripts/auction_collect.py run; echo "RC=$?" > /tmp/_auc_rc
  echo "--- 锚点校验(09:25快照价 vs 当日开盘价) ---"
  env -u HTTPS_PROXY -u HTTP_PROXY $PY scripts/auction_collect.py verify
} >> "$LOG" 2>&1

RC=$(cut -d= -f2 /tmp/_auc_rc 2>/dev/null || echo 1)
# 抽取本次结果推送
V=$(env -u HTTPS_PROXY -u HTTP_PROXY $PY scripts/auction_collect.py verify 2>&1 | tail -3 | tr '\n' ' ')
N=$(env -u HTTPS_PROXY -u HTTP_PROXY $PY scripts/auction_collect.py stat 2>&1 | grep "$DAY" | tr -s ' ')
# ⛔2026-09-08: 原措辞无条件说"完成", 采集全失败也这么发。改为按退出码与入库数分岔。
# 2026-09-29(main 建议): 全对上时不再发 signal(每条会注入六个会话却无人需要动作), 结果每天写进本域留档;
#   只有异常(采集失败/对上<97%/不符>0/跳过数>200)才发 signal 并走 ⛔ 飞书告警。
MIS=$(printf '%s' "$V" | grep -oE '不符 [0-9]+' | grep -oE '[0-9]+' | head -1); MIS=${MIS:-0}
SKIP=$(printf '%s' "$V" | grep -oE '跳过 [0-9]+' | grep -oE '[0-9]+' | head -1); SKIP=${SKIP:-0}
ANOM=0
if [ "$RC" -ne 0 ] || [ -z "$N" ]; then ANOM=1; fi
case "$V" in *⛔*) ANOM=1 ;; esac
[ "$MIS" -gt 0 ] && ANOM=1
[ "$SKIP" -gt 200 ] && ANOM=1
/opt/homebrew/bin/python3 -c "
import json,sys
print(json.dumps({'date':sys.argv[1],'rc':sys.argv[2],'verify':sys.argv[3],'stored':sys.argv[4],'mismatch':int(sys.argv[5]),'skipped':int(sys.argv[6]),'anomaly':sys.argv[7]=='1'},ensure_ascii=False))" \
  "$DAY" "$RC" "$V" "$N" "$MIS" "$SKIP" "$ANOM" >> data/auction/anchor_verify.jsonl 2>/dev/null

if [ "$RC" -ne 0 ] || [ -z "$N" ]; then
  bash ~/.claude/session-remote/fs-reply.sh "[A股·自动] ⛔竞价采集 $DAY **失败**(退出码$RC)。入库:${N:-无} | $V 。今日无可用竞价数据, 别拿它做回测。" >/dev/null 2>&1
elif [ "$ANOM" = "1" ]; then
  bash ~/.claude/session-remote/fs-reply.sh "⛔[A股·自动] 竞价通道校验异常 $DAY: 不符 $MIS 只, 跳过 $SKIP 只 | $V | 入库: $N 。该批竞价数据先别用。" >/dev/null 2>&1
else
  bash ~/.claude/session-remote/fs-reply.sh "[A股·自动] 竞价采集 $DAY 入库: $N | $V" >/dev/null 2>&1
fi

[ "$ANOM" = "1" ] || exit 0
# 异常才给 main 发 signal(跨session异步管道)
SIG=~/.claude/nexus/signals/pending/sig-$(date +%Y%m%d-%H%M%S)-astock-竞价通道校验.json
mkdir -p "$(dirname "$SIG")"
cat > "$SIG" <<EOF
{"from":"astock","to":"main","priority":"high","date":"$DAY",
 "expires_at":"$(date -v+1d '+%Y-%m-%dT%H:%M:%S+08:00')",
 "topic":"竞价采集通道锚点校验异常",
 "body":"锚点=09:25快照价必须==当日开盘价(集合竞价撮合结果, 有唯一正确答案)。本日结果: ${V//\"/}。入库: ${N//\"/}。不符 $MIS, 跳过 $SKIP。",
 "note":"只在异常时发。全量逐日结果见 sim-portfolio/data/auction/anchor_verify.jsonl。"}
EOF

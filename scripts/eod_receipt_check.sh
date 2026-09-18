#!/bin/bash
# 16:40 检查 16:00 收盘版调仓是否闭环(2026-09-02建, 治"ping投了没人接")
#
# ⛔2026-09-18 改: 原版只判 [ ! -f "$M" ] 一个条件, 却打出"astock 可能未在听(进程重启/监听死)"。
#   判据与结论说的不是一回事 —— 判据测的是"标记文件在不在", 结论断的是"人在不在听"。
#   2026-09-17 实证: 16:40 那次真的发了这条告警进飞书群, 而当时我正在跟 Buwen 对话、
#   正在执行策略改革清仓(第1批五笔16:46成交、第2批四笔在跑), 一直在听, 只是四步没走完标记没打。
#   ⛔后果不只是噪音: 告警里写"请发一句16:00调仓即可"唤醒, 若照做会触发重复执行。
#   ⛔这是 feedback_fault_must_shout 的镜像 —— 那条讲"故障被降级成语义合法的正常值",
#     这条是"正常状态被升级成了故障", 共同点都是尺子分辨率不够。
#
# 真实状态有三种, 现在分开报:
#   ①没在听      标记无 + 监听进程无  → 原告警成立, 建议唤醒
#   ②在听但未闭环 标记无 + 监听进程在  → 不建议唤醒, 提示自查是否卡住
#   ③已闭环      标记在              → 静默退出
DOW=$(date +%u); [ "$DOW" -gt 5 ] && exit 0

ROOT=~/claude-projects/sim-portfolio
M=$ROOT/data/eod_done/$(date +%Y%m%d)
LOG=/tmp/eod-receipt.log
TS=$(date '+%F %T')

# 已闭环, 正常退出
[ -f "$M" ] && { echo "$TS 标记已存在, 四步已闭环"; exit 0; }

# ⛔第二信号源: 直接查它自己声称要测的那个东西 —— 监听进程在不在
LISTEN=$(pgrep -f "session-inbox/astock.jsonl" | wc -l | tr -d ' ')

# 第三信号源(辅助): 当日有没有动作痕迹, 有则显然在做
NOON=$(ls "$ROOT/data/eod_done/$(date +%Y%m%d)"_*.json 2>/dev/null | wc -l | tr -d ' ')
TRADES=$(/opt/homebrew/bin/python3 - <<PY 2>/dev/null || echo 0
import json, datetime
d = json.load(open("$ROOT/portfolio_state.json"))
t = datetime.date.today().isoformat()
print(sum(1 for x in d.get("trade_log", []) if str(x.get("timestamp", "")).startswith(t)))
PY
)

if [ "$LISTEN" -eq 0 ]; then
  MSG="[astock⚠️告警] 16:00收盘版调仓ping已投40分钟无回执标记, 且 astock 的 inbox 监听进程不存在。\
这是真的没人在听(进程重启/监听死)。请 Buwen 或 main 唤醒 astock: 打开 astock session 发一句'16:00调仓'即可。\
(当日成交 $TRADES 笔, 阶段性标记 $NOON 个)"
else
  MSG="[astock⚠️告警] 16:00收盘版调仓四步尚未闭环(标记 $(basename $M) 未打), \
但 astock 的 inbox 监听进程在($LISTEN 个), 当日已成交 $TRADES 笔、有 $NOON 个阶段性标记。\
⛔不要发'16:00调仓'唤醒, 那会触发重复执行。这条是提示 astock 自查四步卡在哪一步, 不是提示它没在听。"
fi

bash ~/.claude/session-remote/fs-reply.sh "$MSG" \
  || echo "$TS ⛔ 告警未送达(fs-reply 退出码 $?), 标记 $M 不存在, 监听进程 $LISTEN 个" >> "$LOG"
# 2026-09-10: fs-reply 退出码已可信(main 加固), 未送达必须落日志, 不能沉默

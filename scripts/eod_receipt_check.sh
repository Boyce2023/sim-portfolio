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

# ⛔2026-09-18 10:05 补两道守卫, 起因是我自己踩的坑:
#   改完这个脚本后我"干跑"验证了一次, 它真的往飞书发了一条告警,
#   当时 10:00, 而消息内容说的是"16:00收盘版调仓", 时间上自相矛盾, Buwen 看到只会困惑。
#   ⛔两个独立缺口:
#   ①没有 dry-run: 这类脚本的唯一验证方式就是真跑, 而真跑必然触发它的副作用。
#     同 feedback_safe_verification "验证防X的机制时验证路径本身不能导致X"。
#   ②没有时点守卫: 它假设自己只在 16:40 被调用, 却没有任何东西保证这一点。
#     ⛔而我 2026-09-17 刚给 market_snapshot.py 写过一道一模一样的时段门(收盘前拒绝写入并真退出),
#     隔一天写这个脚本时没想到要加。写过的门不会自动长到下一个脚本上。
DRY_RUN=${DRY_RUN:-0}
FORCE=${FORCE:-0}
HM=$(date +%H%M)
if [ "$FORCE" != "1" ] && [ "$DRY_RUN" != "1" ]; then
  if [ "$HM" -lt 1630 ] || [ "$HM" -gt 1700 ]; then
    echo "$(date '+%F %T') 当前 $HM 不在 16:30-17:00 检查窗口内, 退出(本脚本只应由 16:40 的 launchd 调用)"
    exit 0
  fi
fi

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
# ⛔2026-09-18 修 account 过滤: 原版数的是 trade_log 里**全部账户**当日成交, 而本脚本是 astock 域的回执检查器。
#   当日实证: DRY_RUN 打出"astock 当日已成交 1 笔", 而 A股是零持仓零交易, 那 1 笔是 us 域 09:24 的 NEM 清仓。
#   ⛔后果不是数字难看, 是削弱告警: 这个数字是用来佐证"astock 在干活"的第三信号源,
#   若 A股真漏做而美股恰好有成交, 它会给出反向暗示, 让本该刺眼的告警显得没那么严重。
#   同族 feedback_market_isolation(脚本必须显式 market) 与 feedback_astock_us_separation。
TRADES=$(/opt/homebrew/bin/python3.13 - <<PY 2>/dev/null || echo 0
import json, datetime
d = json.load(open("$ROOT/portfolio_state.json"))
t = datetime.date.today().isoformat()
print(sum(1 for x in d.get("trade_log", [])
          if str(x.get("timestamp", "")).startswith(t) and x.get("account") == "a_share"))
PY
)

if [ "$LISTEN" -eq 0 ]; then
  MSG="⛔[astock·日终未闭环告警] 截至16:40仍未生成今日 eod_done/$(date +%Y%m%d) 对账标记(当日成交 $TRADES 笔)。请检查 /tmp/quant_4bucket.log 是否报错。"
else
  MSG="[astock⚠️告警] 16:00收盘版调仓四步尚未闭环(标记 $(basename $M) 未打), \
但 astock 的 inbox 监听进程在($LISTEN 个), 当日已成交 $TRADES 笔、有 $NOON 个阶段性标记。\
⛔不要发'16:00调仓'唤醒, 那会触发重复执行。这条是提示 astock 自查四步卡在哪一步, 不是提示它没在听。"
fi

if [ "$DRY_RUN" = "1" ]; then
  echo "[DRY_RUN] 不发送, 以下是将要发出的文案:"
  echo "$MSG"
  exit 0
fi
bash ~/.claude/session-remote/fs-reply.sh "$MSG" \
  || echo "$TS ⛔ 告警未送达(fs-reply 退出码 $?), 标记 $M 不存在, 监听进程 $LISTEN 个" >> "$LOG"
# 2026-09-10: fs-reply 退出码已可信(main 加固), 未送达必须落日志, 不能沉默

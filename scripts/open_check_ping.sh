#!/bin/bash
# ⛔⛔第一行, 每天必读: 模拟盘的买卖是我自主决策+执行+事后报告, **不请示**。
# Buwen 07-09定, 08-26/27/09-08已复发四次。他的原话: "你的决策权大于我, 你就直接调仓,
# 这已经是我们说过非常多次的事情了, 我完全没法理解为什么你会忘, 如果你真的会忘为什么不代码化"。
# 选好股→立刻告诉他; 到最早可交易时点→自己执行; 成交→立刻报他。三步都不等确认。
# 每交易日09:26投递开盘检查指令(2026-09-02建, 2026-09-04修)
# ⛔2026-09-04修复: 原用 bash printf 拼JSON, 指令文本里的 "3%的" 被当成格式符 → printf报
#   "invalid format character" 直接失败, 该任务从建好起从未成功投递过一次(launchd exit 1)。
#   改用 python 写JSON: 不解析格式符, 且自动处理转义。任何含中文/百分号的模板一律别用 printf。
DOW=$(date +%u); [ "$DOW" -gt 5 ] && exit 0
/usr/bin/python3 - <<'PY'
import json, datetime, os
msg = {
 "ts": datetime.datetime.now().astimezone().strftime('%Y-%m-%dT%H:%M:%S%z'),
 "from": "open-check-cron", "kind": "task",
 "instruction": ("【每日09:26开盘检查】①执行昨夜16:00收盘版裁决中标注'明早开盘执行'的单子"
   "(读 watchlist_config.json status=pending_open) "
   "②核 data/b_live_log.jsonl 里 verify_date=今天的B选板开盘价并写 result "
   "③⛔B策略专户: 读 data/b_watch_今日.json 四门短名单, 盘中触板按四门决定满档(4/4)/半档(3/4)/不买(<=2/4), "
   "核心过滤=前1日涨>3% 且 量比<1.5; 昨日B持仓一律开盘价卖出不留第二天 "
   "④拉全持仓开盘价, 距灾难线小于3%的列出 ⑤一句飞书回执。幂等: 今天已做则忽略。")
}
p = os.path.expanduser('~/.claude/session-inbox/astock.jsonl')
with open(p, 'a') as f:
    f.write(json.dumps(msg, ensure_ascii=False) + '\n')
print('open-check ping delivered')
PY

# ⛔取用链: Buwen 09-08 "学了很多东西, 但是在对应的时候不调用"。清单必须打在我眼前, 不是等我想起来。
cd /Users/huaichuaibeimeng/claude-projects/sim-portfolio 2>/dev/null && {
  /opt/homebrew/bin/python3 scripts/preflight.py buy  2>/dev/null
  /opt/homebrew/bin/python3 scripts/preflight.py sell 2>/dev/null
}

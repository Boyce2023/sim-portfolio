#!/bin/bash
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

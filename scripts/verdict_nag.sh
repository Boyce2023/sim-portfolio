#!/bin/bash
# 待裁决台账每日主动催 — launchd 每交易日 08:40
# ⛔为什么要这个: 台账解决的是"记录", 没解决"提醒"。
#   pending_verdicts.py list --due 只在有人调用时才起作用, SOP写着"收盘版四步第①步必须调用"
#   ——那是靠自觉。08-24承诺"保留一半等08-27中报裁决"逾期11天没做, 就是因为没人叫它,
#   而且台账静静躺着不会露馅。回扫判据(main提炼): 好锚点是"错了会自己露馅"的。
cd /Users/huaichuaibeimeng/claude-projects/sim-portfolio || exit 1
D=$(date +%u); [ "$D" -ge 6 ] && exit 0        # 周末不催
OUT=$(/opt/homebrew/bin/python3 scripts/pending_verdicts.py list --due 2>&1)
echo "$(date '+%F %T') $OUT" >> /tmp/verdict_nag.log
case "$OUT" in
  *无到期待裁决*) exit 0 ;;                     # 没到期项就安静
esac
bash ~/.claude/session-remote/fs-reply.sh "[A股·待裁决到期] $OUT
⛔这些是我自己承诺过要在该日期做裁决的事, 已到期。收盘版四步第①步必须先处理完再往下走。" >/dev/null 2>&1
SIG=~/.claude/nexus/signals/pending/sig-$(date +%Y%m%d-%H%M%S)-astock-待裁决到期.json
mkdir -p "$(dirname "$SIG")"
/opt/homebrew/bin/python3 -c "
import json,sys,datetime
print(json.dumps({'from':'astock','to':'astock','priority':'high',
 'date':datetime.date.today().isoformat(),'topic':'待裁决台账到期项',
 'body':'''$OUT''','note':'到期未裁决=历史上逾期11天的那类失误, 收盘四步第①步必须清掉'},ensure_ascii=False))" > "$SIG"

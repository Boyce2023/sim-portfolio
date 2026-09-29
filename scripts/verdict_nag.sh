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

# ⛔2026-09-17新增第二类检查: 前提失效(查"记录写反了", 不是查"记录到期了")。
#   治理失效三档(interview 2026-09-17): ①没有记录 ②记录存在没去取 ③**记录存在且写反了**。
#   第三档最贵: 前两档的失败是"什么都没发生", 第三档是"发生了一件错的事, 而且是系统指挥的"。
#   本域实例(同日): #35 条件文本写"三日收盘在灾难线63.67下, 必须给出清仓议题", 而09-16收64.14已守住线,
#   照文本执行=在不成立的前提上清仓; 拦住它的是我前一天碰巧补的一句intel_log, 不是任何机制。
# ⛔必须放在下面 exit 0 之前: 原逻辑"没到期项就安静"会让本检查永远跑不到 ——
#   同 feedback_gate_before_score "硬门在打分前会让打分永远跑不到"(09-10实测6只全被硬门拒, 打分一次没执行)。
PREM=$(/opt/homebrew/bin/python3 scripts/verdict_premise_check.py 2>&1 | grep -E "^⚠️|需人工确认" || true)
echo "$(date '+%F %T') [premise] $PREM" >> /tmp/verdict_nag.log

case "$OUT" in
  *无到期待裁决*)
    # 到期项为空, 但前提失效检查仍要发(它与到期无关)
    case "$PREM" in
      *"需人工确认前提是否仍成立: 0 条"*|"") exit 0 ;;
    esac
    bash ~/.claude/session-remote/fs-reply.sh "⛔[A股·裁决前提可能已失效] 今日无到期裁决, 但下列活条目绑定了会过期的事实前提, 需人工对照今日事实确认:
$PREM
⛔ 这类条目的危险在于: 它写下时是对的, 之后每天都在悄悄失效, 而没有任何东西会重新验证它。照一个已失效的前提执行, 等于被系统指挥去做一件错的事。" >/dev/null 2>&1
    exit 0 ;;
esac
bash ~/.claude/session-remote/fs-reply.sh "[A股·待裁决到期] $OUT
⛔这些是我自己承诺过要在该日期做裁决的事, 已到期。收盘版四步第①步必须先处理完再往下走。" >/dev/null 2>&1
# 2026-09-29(main 建议): 飞书催办每天照发; 发给自己的 signal 只在出现"新的到期编号"时发,
#   否则同一批到期项每天全量重发一遍, 注入所有会话却不带新信息。
NEWIDS=$(/opt/homebrew/bin/python3 -c "
import json,re,sys,os
st='data/verdict_nag_state.json'
cur=sorted(set(re.findall(r'#(\d+)', sys.argv[1])), key=int)
old=set(json.load(open(st)).get('sent',[])) if os.path.exists(st) else set()
new=[i for i in cur if i not in old]
json.dump({'sent':sorted(old|set(cur),key=int)}, open(st,'w'))
print(' '.join(new))" "$OUT")
[ -z "$NEWIDS" ] && exit 0
SIG=~/.claude/nexus/signals/pending/sig-$(date +%Y%m%d-%H%M%S)-astock-待裁决到期.json
mkdir -p "$(dirname "$SIG")"
/opt/homebrew/bin/python3 -c "
import json,sys,datetime
print(json.dumps({'from':'astock','to':'astock','priority':'high',
 'date':datetime.date.today().isoformat(),'topic':'待裁决台账到期项',
 'expires_at':(datetime.datetime.now().astimezone()+datetime.timedelta(days=1)).isoformat(timespec='seconds'),  # 2026-09-29: 每日全量重发, 旧条次日即被取代
 'body':'''新到期: $NEWIDS\n$OUT''','note':'到期未裁决=历史上逾期11天的那类失误, 收盘四步第①步必须清掉'},ensure_ascii=False))" > "$SIG"

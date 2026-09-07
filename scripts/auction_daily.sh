#!/bin/bash
# 竞价采集每日入口 — launchd 调用。⛔承诺下沉: 结果自动推送, 不依赖任何session活着"记得报"
cd /Users/huaichuaibeimeng/claude-projects/sim-portfolio || exit 1
PY="/opt/homebrew/bin/python3"; LOG=/tmp/auction_collect.log
DAY=$(date '+%Y-%m-%d')
{ echo "=========== $DAY $(date '+%H:%M:%S') 竞价采集 ==========="
  env -u HTTPS_PROXY -u HTTP_PROXY $PY scripts/auction_collect.py run
  echo "--- 锚点校验(09:25快照价 vs 当日开盘价) ---"
  env -u HTTPS_PROXY -u HTTP_PROXY $PY scripts/auction_collect.py verify
} >> "$LOG" 2>&1

# 抽取本次结果推送
V=$(env -u HTTPS_PROXY -u HTTP_PROXY $PY scripts/auction_collect.py verify 2>&1 | tail -3 | tr '\n' ' ')
N=$(env -u HTTPS_PROXY -u HTTP_PROXY $PY scripts/auction_collect.py stat 2>&1 | grep "$DAY" | tr -s ' ')
bash ~/.claude/session-remote/fs-reply.sh "[A股·自动] 竞价采集 $DAY 完成。入库: ${N:-无} | $V" >/dev/null 2>&1

# 给 main 发 signal(跨session异步管道), 它明确要这条实证
SIG=~/.claude/nexus/signals/pending/sig-$(date +%Y%m%d-%H%M%S)-astock-竞价通道校验.json
mkdir -p "$(dirname "$SIG")"
cat > "$SIG" <<EOF
{"from":"astock","to":"main","priority":"medium","date":"$DAY",
 "topic":"竞价采集通道锚点校验结果",
 "body":"锚点=09:25快照价必须==当日开盘价(集合竞价撮合结果, 有唯一正确答案)。本日结果: ${V//\"/}。入库: ${N//\"/}",
 "note":"main要求收录为通道验证实证。对上<97%即通道有问题, 该批数据不可用。"}
EOF

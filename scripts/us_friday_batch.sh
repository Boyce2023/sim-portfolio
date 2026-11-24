#!/bin/bash
# 每周五 15:10 合并执行 weekly-scorecard 与 tree-tracker (2026-11-23 合并减负)
set -u
RC=0
echo "=== [$(date '+%F %T')] us_friday_batch start ===" >> /tmp/us_friday_batch.log

cd /Users/huaichuaibeimeng/claude-projects/sim-portfolio
env -u HTTPS_PROXY -u HTTP_PROXY /opt/homebrew/bin/python3.13 scripts/strategy_scoreboard.py weekly >> /tmp/weekly_scorecard.log 2>&1
rc1=$?
echo "[$(date '+%F %T')] weekly-scorecard rc=$rc1" >> /tmp/us_friday_batch.log
[ $rc1 -ne 0 ] && RC=$rc1

/opt/homebrew/bin/python3.13 /Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts/tree_tracker.py >> /tmp/tree_tracker.log 2>&1
rc2=$?
echo "[$(date '+%F %T')] tree-tracker rc=$rc2" >> /tmp/us_friday_batch.log
[ $rc2 -ne 0 ] && RC=$rc2

exit $RC

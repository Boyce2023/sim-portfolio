#!/bin/bash
# 每交易日09:30投递美股完整调仓指令到us inbox (2026-09-02 Buwen令: 每天北京时间9:30自动做昨晚美股完整调仓)
# 跨session兜底: session重启后只要监听在, 就能被触发; 监听不在时 inbox-watchdog 会报积压
DOW=$(date +%u); [ "$DOW" -gt 5 ] && exit 0
# 周一早上对应的是上周五美股, 照做; 美国假日由session自行判断跳过
# 先机械更新桌面「美股选股追踪.xlsx」(Sheet1追加昨夜≥10%跳涨, 最新在上; Sheet3刷板块数字), 失败不阻塞调仓指令
LOG=/tmp/us_track_daily.log
/usr/bin/python3 "$HOME/claude-projects/sim-portfolio/scripts/us_track_daily.py" >> "$LOG" 2>&1 || echo "$(date) us_track_daily FAILED rc=$?" >> "$LOG"
/usr/bin/python3 "$HOME/claude-projects/sim-portfolio/scripts/us_jump_judge_prep.py" >> "$LOG" 2>&1 || echo "$(date) us_jump_judge_prep FAILED rc=$?" >> "$LOG"
printf '{"ts":"%s","from":"us-morning-rebalance-cron","kind":"task","instruction":"【每日必备·美股完整调仓】按昨晚美股收盘价做四件套: ①完整报告(NAV/持仓/宏观/扳机状态) ②扫描(rebuild_mech+combine刷综合分, 消息面) ③深度研究(判断层最弱持仓去留+双层同向候选一手核查) ④调仓执行(自主决策执行, 事后报告)。⛔若本session今天已做/正在做则忽略本条(幂等)。美股休市日报一句跳过。⛔先跑 price_gap_guard.py 查数据缺口, 有缺口不出扳机判定。⑤跳涨判断(Buwen 9/2 23:07: 明天听他指挥, 他想法很杂): 材料已备好在 /tmp/us_jump_prep_<昨日>.md + 基础率 research-notes/us-database/2026-09-03_跳涨后走势_基础率.md, ⛔不要自己先按固定格式写一大篇, 先把昨夜跳涨名单一句话报给他, 等他说怎么判、判哪些、要什么形式, 再动手. ⑥看 /tmp/us_track_daily.log 尾行确认跳涨表已更新(失败则补跑 us_track_daily.py 并报)。完成后飞书回执+落盘 research-notes/us-database/YYYY-MM-DD_调仓裁决.md"}\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" >> ~/.claude/session-inbox/us.jsonl

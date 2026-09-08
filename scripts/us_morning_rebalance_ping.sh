#!/bin/bash
# 每交易日09:30投递美股完整调仓指令到us inbox (2026-09-02 Buwen令: 每天北京时间9:30自动做昨晚美股完整调仓)
# 跨session兜底: session重启后只要监听在, 就能被触发; 监听不在时 inbox-watchdog 会报积压
# 2026-09-04: 改用 python 写 JSON, 不再用 printf 拼 (中文与百分号会被当成格式符, astock 同款事故)
DOW=$(date +%u); [ "$DOW" -gt 5 ] && exit 0
# 周一早上对应的是上周五美股, 照做; 美国假日由session自行判断跳过
# 先机械更新桌面「美股选股追踪.xlsx」(Sheet1追加昨夜≥10%跳涨, 最新在上; Sheet3刷板块数字), 失败不阻塞调仓指令
LOG=/tmp/us_track_daily.log
/opt/homebrew/bin/python3 "$HOME/claude-projects/sim-portfolio/scripts/us_track_daily.py" >> "$LOG" 2>&1 || echo "$(date) us_track_daily FAILED rc=$?" >> "$LOG"
/opt/homebrew/bin/python3 "$HOME/claude-projects/sim-portfolio/scripts/us_jump_judge_prep.py" >> "$LOG" 2>&1 || echo "$(date) us_jump_judge_prep FAILED rc=$?" >> "$LOG"

/opt/homebrew/bin/python3 - <<'PY'
import json, os, glob, datetime, subprocess
now = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
inbox = os.path.expanduser('~/.claude/session-inbox')

us_msg = ("【每日必备·美股完整调仓】按昨晚美股收盘价做四件套: "
  "①完整报告(NAV/持仓/宏观/扳机状态) ②扫描(rebuild_mech+combine刷综合分, 消息面) "
  "③深度研究(判断层最弱持仓去留+双层同向候选一手核查) ④调仓执行(自主决策执行, 事后报告)。"
  "⛔若本session今天已做/正在做则忽略本条(幂等)。"
  "⛔⛔判断今天要不要做, 看的是【昨晚有没有新的美股收盘要复核】, 不是【今天开不开市】。"
  "2026-09-07劳动节我看到cron就说休市跳过, 而当时该复核的是9/4周五收盘(正常交易日),"
  "结果扫描层四天没刷新(9/4→9/8), 是Buwen问才发现。只有当上一个交易日也无收盘时才跳过。"
  "⛔先跑 `python3 scripts/price_gap_guard.py` 查数据缺口(2026-09-08已加CLI入口, 退出码 0=干净/1=有缺口/2=守卫没跑成)。"
  "⛔按退出码判, 不要用管道接grep——那样$?拿到的是grep的码不是脚本的。有缺口不出扳机判定。"
  "⑤跳涨判断线 Buwen 2026-09-03 13:55 已搁置(回测与每日判断都停), 只跑机械层不做判断, 重启等他说。"
  "⑥看 /tmp/us_track_daily.log 尾行确认跳涨表已更新(失败则补跑 us_track_daily.py 并报)。"
  "完成后飞书回执+落盘 research-notes/us-database/YYYY-MM-DD_调仓裁决.md")
with open(os.path.join(inbox,'us.jsonl'),'a') as f:
    f.write(json.dumps({"ts":now,"from":"us-morning-rebalance-cron","kind":"task","instruction":us_msg},ensure_ascii=False)+"\n")

# 跳涨材料落盘则通知 research(判断层归它; 线搁置期间它收到不判, 保留通道)
files = sorted(glob.glob('/tmp/us_jump_prep_*.md'), key=os.path.getmtime)
if files:
    prep = files[-1]
    n = sum(1 for l in open(prep) if l.startswith('## '))
    msg = (f"[跳涨判断材料已落盘] {prep} 共{n}只昨夜涨幅10%以上"
           "(含公司介绍/市值/前1月/基础率格子/新闻)。判断层归research; "
           "该线 Buwen 2026-09-03 已搁置, 收到不必判, 重启后再用。"
           "基础率: sim-portfolio/research-notes/us-database/2026-09-03_跳涨后走势_基础率.md")
    with open(os.path.join(inbox,'research.jsonl'),'a') as f:
        f.write(json.dumps({"ts":now,"from":"us-morning-cron","kind":"task","instruction":msg},ensure_ascii=False)+"\n")
print("ping delivered")
PY

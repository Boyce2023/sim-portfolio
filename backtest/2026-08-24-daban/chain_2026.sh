#!/bin/bash
# 等2025补抓进程退出后,顺序抓2026年1/2/3月公告(样本外窗口)。共用notices.db,done表按日期幂等。
while pgrep -f "fetch_notices.py univ2025.db" >/dev/null; do sleep 15; done
python3 fetch_notices.py univ202601.db 2026-01-01 2026-01-31
python3 fetch_notices.py univ202602.db 2026-02-01 2026-02-28
python3 fetch_notices.py univ202603.db 2026-03-01 2026-03-31
echo "CHAIN_DONE $(date '+%H:%M')"

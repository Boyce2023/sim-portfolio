#!/bin/bash
# 等3月补全完→串行拉5月→6月(baostock单连接防zombie)
while pgrep -f "fetch_202603.py" >/dev/null; do sleep 30; done
python3 fetch_202605.py
python3 fetch_202606.py
echo "CHAIN_MAYJUN_DONE $(date '+%H:%M')"

#!/bin/bash
# 带进程级守护的拉取链: 5月→4月→6月,每个最多3次×70分钟
python3 run_guarded.py 4200 3 fetch_202605.py
python3 run_guarded.py 4200 3 fetch_202604.py
python3 run_guarded.py 4200 3 fetch_202606.py
echo "CHAIN3_DONE $(date '+%H:%M')"

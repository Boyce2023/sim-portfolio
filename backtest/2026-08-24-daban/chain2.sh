#!/bin/bash
while pgrep -f "fetch_202605.py" >/dev/null; do sleep 30; done
python3 fetch_202604.py
python3 fetch_202606.py
echo "CHAIN2_DONE $(date '+%H:%M')"

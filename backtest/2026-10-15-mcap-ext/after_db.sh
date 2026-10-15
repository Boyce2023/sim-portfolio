#!/bin/bash
# 等 15:40 价格库更新跑完(进程出现过并退出, 或 17:30 超时), 再重跑首板与成品
until [ "$(date +%H%M)" -ge 1541 ]; do sleep 30; done
until ! pgrep -f "scripts/cn_price_db_update.py" >/dev/null || [ "$(date +%H%M)" -ge 1730 ]; do sleep 30; done
tail -3 /tmp/cn_price_db.log
/opt/homebrew/bin/python3.13 build.py > build_final.log 2>&1
grep -v -i warn build_final.log | head -2
/opt/homebrew/bin/python3.13 make_outputs.py --write 2>&1 | grep -v -i warn | tail -4

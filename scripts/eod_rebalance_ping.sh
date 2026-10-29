#!/bin/bash
# 每交易日 16:00 兜底执行四分仓日终对账与 eod_done 闭环（若 15:08 已完成则幂等复核）
DOW=$(date +%u); [ "$DOW" -gt 5 ] && exit 0
cd /Users/huaichuaibeimeng/claude-projects/sim-portfolio || exit 1
M="data/eod_done/$(date +%Y%m%d)"
if [ ! -f "$M" ]; then
  /opt/homebrew/bin/python3.13 scripts/quant_4bucket_engine.py reconcile >> /tmp/quant_4bucket.log 2>&1
fi

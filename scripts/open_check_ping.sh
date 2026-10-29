#!/bin/bash
# 每交易日 09:26 执行四分仓早盘扫描与自动建仓（替代已废弃的 session-inbox/astock.jsonl 死管道）
DOW=$(date +%u); [ "$DOW" -gt 5 ] && exit 0
cd /Users/huaichuaibeimeng/claude-projects/sim-portfolio || exit 1
/opt/homebrew/bin/python3.13 scripts/quant_4bucket_engine.py open >> /tmp/quant_4bucket.log 2>&1

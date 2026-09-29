#!/bin/bash
cd /Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-09-29-wf
while pgrep -f fetch_2024h2.py >/dev/null; do sleep 30; done
echo "== 补拉结束 $(date +%H:%M)"; tail -2 fetch_2024h2.log
PY=/opt/homebrew/bin/python3.13
$PY build_panel.py && $PY features.py && $PY wf.py > wf_full.log && $PY sim.py > sim_full.log && $PY report.py
echo "== 全部完成 $(date +%H:%M)"

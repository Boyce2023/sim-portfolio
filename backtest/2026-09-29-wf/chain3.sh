#!/bin/bash
cd /Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-09-29-wf
PY=/opt/homebrew/bin/python3.13
while pgrep -f fetch_2024h2.py >/dev/null; do sleep 10; done
echo "== ST全量补齐 $(date +%H:%M:%S)"; tail -1 fetch_2024h2.log
$PY build_panel.py && $PY features.py && $PY wf.py > wf_full.log && $PY sim.py > sim_full.log && $PY report.py > report_run2.txt && $PY robust.py > robust_run2.txt && $PY attrib.py > attrib_run2.txt
echo "== 确认版完成 $(date +%H:%M:%S)"

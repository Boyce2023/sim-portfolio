#!/bin/bash
cd /Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-09-29-wf
PY=/opt/homebrew/bin/python3.13
until [ -f PRIORITY_DONE ]; do sleep 5; done
echo "== 退市股补齐 $(date +%H:%M:%S)"
$PY build_panel.py && $PY features.py && $PY wf.py > wf_full.log && $PY sim.py > sim_full.log && $PY report.py > report_run1.txt
echo "== 正式版完成 $(date +%H:%M:%S)"
mkdir -p run1 && cp summary.csv halves.csv by_quarter.csv trades_*.csv eq_*.csv wf_log.json d_schedule.json report_run1.txt run1/

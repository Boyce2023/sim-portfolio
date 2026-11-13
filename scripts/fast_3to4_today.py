#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
三进四主战策略 V3.2 盘中/盘后秒查打分器（自动输出同日头名硬骨架核验、具体整数总分、分档与 09:26 突破条件单触发价）
用法：
  /opt/homebrew/bin/python3.13 sim-portfolio/scripts/fast_3to4_today.py
  /opt/homebrew/bin/python3.13 sim-portfolio/scripts/fast_3to4_today.py --date 2026-10-27
"""
import os
import sys
import subprocess

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCORER = os.path.join(ROOT, "sim-portfolio", "backtests_astock2", "score_3to4_v31_card.py")

if __name__ == "__main__":
    cmd = [sys.executable, SCORER] + sys.argv[1:]
    raise SystemExit(subprocess.call(cmd))

#!/bin/bash
# 每交易日 09:30 投递美股慢账盘后复核指令 (2026-10-29 收口至 Antigravity 原生唤醒链路 + 慢账规则对齐)
# 用法: bash us_morning_rebalance_ping.sh [--dry-run]

DRY_RUN=0
if [ "${1:-}" = "--dry-run" ]; then
  DRY_RUN=1
else
  DOW=$(date +%u)
  [ "$DOW" -gt 5 ] && exit 0
  # 周一早上对应上周五美股收盘; 先机械更新活表与跳涨底稿, 失败不阻塞复核投递
  LOG=/tmp/us_track_daily.log
  /Users/huaichuaibeimeng/.local/bin/uv run --quiet --with yfinance --with openpyxl --with pandas python "$HOME/claude-projects/sim-portfolio/scripts/us_track_daily.py" >> "$LOG" 2>&1
  rc=$?; [ $rc -ne 0 ] && echo "$(date) us_track_daily FAILED rc=$rc" >> "$LOG"
  /Users/huaichuaibeimeng/.local/bin/uv run --quiet --with yfinance --with openpyxl --with pandas python "$HOME/claude-projects/sim-portfolio/scripts/us_jump_judge_prep.py" >> "$LOG" 2>&1
  rc=$?; [ $rc -ne 0 ] && echo "$(date) us_jump_judge_prep FAILED rc=$rc" >> "$LOG"
fi

/opt/homebrew/bin/python3 - "$DRY_RUN" <<'PY'
import datetime
import json
import os
import subprocess
import sys

dry_run = sys.argv[1] == "1"
now = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
inbox_dir = os.path.expanduser("~/.claude/session-inbox")
reg_us = os.path.expanduser("~/.claude/session-registry/us.json")
agy_bin = "/Users/huaichuaibeimeng/.gemini/bin/agy"

us_msg = (
    "【每日必备·美股慢账复核与调仓裁决】按最近一个已收盘美股交易日执行四步闭环："
    "①股票级收盘完备性硬校验：先跑 `python3 scripts/price_gap_guard.py`（退出码 0=13只持仓收盘完备放行，宏观期货日历差异仅软提示；1=持仓个股缺口或未落盘硬阻断，严禁拿滞后价出正式裁决；2=守卫异常）。"
    "②反处置效应论点盲审：跑 `python3 scripts/us_thesis_review.py`（隐藏成本价与浮盈亏，逐只核验慢账三问与近7日催化剂窗口；跌破-12%仅触发论点三问复核，绝不自动止损）。"
    "③扫描与新叙事三行卡接棒：跑 `rebuild_mech.py` + `combine.py` 刷新综合分，核查 `_narrative_labels.json` 中「需要判断」新叙事及 `research`/`research2` 发来的三行决策卡，给出明确「买或不买、买则换出哪只工具仓或已兑现持仓」裁决，严禁写「等」或「继续观察」。"
    "④落盘与汇报：检查 `/tmp/us_track_daily.log` 确认活表已更新，将当日裁决落盘至 `research-notes/us-database/YYYY-MM-DD_调仓裁决.md` 并飞书回执（严守 T0 铁律：未经 Buwen 本轮明示执行指令前只展示调仓计划，绝不擅自调用 execute_trade.py）。"
    "幂等保护：若今日已对同一美股收盘日完成复核落盘则忽略本条。"
)

rec = {
    "ts": now,
    "from": "us-morning-rebalance-cron",
    "kind": "task",
    "instruction": us_msg,
}

conv_id = None
if os.path.exists(reg_us):
    try:
        with open(reg_us, encoding="utf-8") as f:
            conv_id = json.load(f).get("conversation_id")
    except Exception:
        conv_id = None

if dry_run:
    print(f"[dry-run] target_conv_id={conv_id} agy_exists={os.path.exists(agy_bin)}")
    print(json.dumps(rec, ensure_ascii=False, indent=2))
    sys.exit(0)

delivered = False
if conv_id and os.path.exists(agy_bin):
    try:
        res = subprocess.run(
            [agy_bin, "agentapi", "send-message", conv_id, us_msg],
            capture_output=True,
            text=True,
            timeout=30,
        )
        delivered = res.returncode == 0
    except Exception:
        delivered = False

os.makedirs(os.path.join(inbox_dir, "_consumed"), exist_ok=True)
if delivered:
    rec["delivered_via"] = "agy_agentapi"
    with open(os.path.join(inbox_dir, "_consumed", "us.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"morning rebalance ping delivered directly to {conv_id}")
else:
    with open(os.path.join(inbox_dir, "us.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("morning rebalance ping queued to us.jsonl fallback for inbox-watchdog")
PY

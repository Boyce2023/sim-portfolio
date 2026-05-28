#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Track B 盘中监控 — 龙头-5%检测 + 铁律检查 + critical信号写入

用法:
  # 完整监控（读取龙头状态）
  uv run --script scripts/tb_monitor.py --leader-chg -3.5

  # 快速铁律检查（不需要实时数据）
  uv run --script scripts/tb_monitor.py --quick

  # 指定炸板率（盘中14:00读数）
  uv run --script scripts/tb_monitor.py --leader-chg -1.2 --board-break 45

输出:
  写入 rotation_state.json 的 pending_signals
  输出 critical 退出信号
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STATE_FILE = REPO / "rotation_state.json"
PORTFOLIO_FILE = REPO / "portfolio_state.json"
SCORECARD_FILE = REPO / "tb_scorecard.json"

# ── I/O ─────────────────────────────────────────────────────────────────────

def load_json(path: Path) -> dict:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}

def save_json(path: Path, data: dict) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ── 龙头跌幅检测 ────────────────────────────────────────────────────────────

def check_leader_drop(positions: list, leader_chg: float | None) -> list[dict]:
    """Check if any TB position's leader has dropped beyond threshold."""
    signals = []

    tb_pos = [p for p in positions if p.get("track") == "B"]
    if not tb_pos:
        return signals

    leaders_checked = set()

    for pos in tb_pos:
        leader = pos.get("tb_leader", "")
        name = pos.get("name", pos.get("ticker", "?"))
        is_bse = pos.get("tb_type") == "BSE" or (leader and leader.startswith("8"))

        if leader in leaders_checked:
            continue

        if leader_chg is not None:
            threshold = -3.0 if is_bse else -5.0
            if leader_chg <= threshold:
                signals.append({
                    "type": "IRON_RULE",
                    "priority": "CRITICAL",
                    "rule": f"龙头跌>{abs(threshold):.0f}%",
                    "detail": f"龙头{leader}跌{leader_chg:+.1f}% {'(北交所-3%阈值)' if is_bse else ''}",
                    "action": f"当日市价全出 [{name}] 及同龙头所有TB仓位",
                    "affected": [p.get("ticker") for p in tb_pos if p.get("tb_leader") == leader],
                    "timestamp": datetime.now().isoformat(),
                })
            leaders_checked.add(leader)

    return signals


# ── 炸板率检测 ──────────────────────────────────────────────────────────────

def check_board_break(board_break: float | None) -> list[dict]:
    """Check if 炸板率 exceeds critical thresholds."""
    signals = []

    if board_break is None:
        return signals

    if board_break > 60:
        signals.append({
            "type": "IRON_RULE",
            "priority": "CRITICAL",
            "rule": "炸板率>60%",
            "detail": f"炸板率{board_break:.0f}% — 崩溃期一票否决",
            "action": "当日全出所有TB仓位",
            "timestamp": datetime.now().isoformat(),
        })
    elif board_break > 50:
        signals.append({
            "type": "DOWNGRADE",
            "priority": "HIGH",
            "rule": "炸板率>50%",
            "detail": f"炸板率{board_break:.0f}% — 触发降级",
            "action": "所有TB持仓降级1档 + 减仓至新等级上限",
            "timestamp": datetime.now().isoformat(),
        })

    return signals


# ── 持仓天数快速检查 ────────────────────────────────────────────────────────

TYPE_LIMITS = {"T1": 5, "T2": 45, "T3": 5, "T4": 15, "T5": 12, "BSE": 7}

def quick_time_check(positions: list) -> list[dict]:
    """Quick check for positions at or beyond time limits."""
    signals = []
    today = datetime.now()

    for pos in positions:
        if pos.get("track") != "B":
            continue

        name = pos.get("name", pos.get("ticker", "?"))
        tb_type = pos.get("tb_type", "T1")
        entry_str = pos.get("tb_entry_date") or pos.get("entry_date", "")

        if not entry_str:
            continue

        try:
            entry_date = datetime.strptime(entry_str[:10], "%Y-%m-%d")
        except ValueError:
            continue

        days = (today - entry_date).days
        limit = TYPE_LIMITS.get(tb_type, 10)

        if days >= limit:
            signals.append({
                "type": "TIME_STOP",
                "priority": "HIGH",
                "rule": f"{tb_type}时间止损",
                "detail": f"{name} 持有{days}天 ≥ 上限{limit}天",
                "action": f"当日尾盘出场 {name}",
                "timestamp": datetime.now().isoformat(),
            })

    return signals


# ── CB状态检查 ──────────────────────────────────────────────────────────────

def check_cb_state(scorecard: dict) -> list[dict]:
    """Check if CB state blocks new positions."""
    signals = []
    cb = scorecard.get("cb_state", "GREEN")

    if cb == "RED":
        signals.append({
            "type": "CB_BLOCK",
            "priority": "HIGH",
            "rule": "CB=RED",
            "detail": f"7日违规{scorecard.get('cb_violation_count_7d', 0)}笔 — TB暂停",
            "action": "不可新建TB仓位，等待CB恢复GREEN",
            "timestamp": datetime.now().isoformat(),
        })
    elif cb == "YELLOW":
        signals.append({
            "type": "CB_WARNING",
            "priority": "MEDIUM",
            "rule": "CB=YELLOW",
            "detail": f"7日违规{scorecard.get('cb_violation_count_7d', 0)}笔",
            "action": "TB sizing ×0.5，新建仓需额外确认",
            "timestamp": datetime.now().isoformat(),
        })

    return signals


# ── 双轨约束检查 ────────────────────────────────────────────────────────────

def check_dual_track_limits(portfolio: dict, state: dict) -> list[dict]:
    """Check if dual-track position/allocation limits are exceeded."""
    signals = []

    tb_count = 0
    ta_count = 0
    tb_pct = 0.0

    for acct in portfolio.get("accounts", {}).values():
        for pos in acct.get("positions", []):
            if pos.get("track") == "B":
                tb_count += 1
                tb_pct += pos.get("portfolio_pct", 0)
            else:
                ta_count += 1

    total = ta_count + tb_count

    if tb_count > 3:
        signals.append({
            "type": "LIMIT_BREACH",
            "priority": "HIGH",
            "rule": "TB持仓数>3只",
            "detail": f"TB={tb_count}只（上限3只）",
            "action": "减至3只以内",
            "timestamp": datetime.now().isoformat(),
        })

    if total > 10:
        signals.append({
            "type": "LIMIT_BREACH",
            "priority": "HIGH",
            "rule": "总持仓>10只",
            "detail": f"TA={ta_count} + TB={tb_count} = {total}只（上限10只）",
            "action": "减至10只以内",
            "timestamp": datetime.now().isoformat(),
        })

    f20 = state.get("market_breath", "中性")
    tb_cap = {"强吸气": 0.40, "吸气": 0.30, "中性": 0.15}.get(f20, 0.0)
    if tb_pct > tb_cap and tb_cap > 0:
        signals.append({
            "type": "LIMIT_BREACH",
            "priority": "HIGH",
            "rule": f"TB仓位>{tb_cap*100:.0f}%（F20={f20}）",
            "detail": f"TB={tb_pct*100:.1f}%",
            "action": f"减至{tb_cap*100:.0f}%以内",
            "timestamp": datetime.now().isoformat(),
        })

    return signals


# ── 输出 ────────────────────────────────────────────────────────────────────

def print_header(quick: bool):
    print()
    mode = "快速铁律检查" if quick else "盘中监控"
    print("╔══════════════════════════════════════════════════════════════════╗")
    print(f"║       Track B {mode} — tb_monitor.py{' --quick' if quick else ''}       ║")
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"║  检查时间: {now}                                         ║")
    print("╚══════════════════════════════════════════════════════════════════╝")
    print()


def print_signals(signals: list[dict]):
    if not signals:
        print("  ✅ 全部通过 — 无异常信号")
        print()
        return

    critical = [s for s in signals if s.get("priority") == "CRITICAL"]
    high = [s for s in signals if s.get("priority") == "HIGH"]
    medium = [s for s in signals if s.get("priority") == "MEDIUM"]

    if critical:
        print("  ⛔⛔⛔ CRITICAL 信号（立即执行）:")
        for s in critical:
            print(f"    ⛔ {s['rule']}: {s['detail']}")
            print(f"       → {s['action']}")
            if s.get("affected"):
                print(f"       影响: {', '.join(s['affected'])}")
        print()

    if high:
        print("  ⚠️  HIGH 信号（当日处理）:")
        for s in high:
            print(f"    ⚠️  {s['rule']}: {s['detail']}")
            print(f"       → {s['action']}")
        print()

    if medium:
        print("  ℹ️  MEDIUM 信号（关注）:")
        for s in medium:
            print(f"    ℹ️  {s['rule']}: {s['detail']}")
            print(f"       → {s['action']}")
        print()


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Track B 盘中监控")
    p.add_argument("--leader-chg", type=float, default=None, help="龙头今日涨跌幅(%%)")
    p.add_argument("--board-break", type=float, default=None, help="炸板率(%%)")
    p.add_argument("--quick", action="store_true", help="快速铁律检查（不需实时数据）")
    args = p.parse_args()

    state = load_json(STATE_FILE)
    portfolio = load_json(PORTFOLIO_FILE)
    scorecard = load_json(SCORECARD_FILE)

    print_header(args.quick)

    all_signals = []

    # Gather all positions
    all_positions = []
    for acct in portfolio.get("accounts", {}).values():
        all_positions.extend(acct.get("positions", []))

    tb_pos = [p for p in all_positions if p.get("track") == "B"]

    if not tb_pos:
        print("  无TB持仓 — 仅检查CB和双轨约束")
        print()
        all_signals.extend(check_cb_state(scorecard))
        all_signals.extend(check_dual_track_limits(portfolio, state))
        print_signals(all_signals)
        return

    print(f"  TB持仓: {len(tb_pos)}只")
    for p in tb_pos:
        name = p.get("name", p.get("ticker", "?"))
        leader = p.get("tb_leader", "?")
        print(f"    • {name} — 龙头: {leader}")
    print()

    # Iron rules
    if not args.quick:
        all_signals.extend(check_leader_drop(all_positions, args.leader_chg))
        all_signals.extend(check_board_break(args.board_break))

    # Time stops
    all_signals.extend(quick_time_check(all_positions))

    # CB check
    all_signals.extend(check_cb_state(scorecard))

    # Dual track limits
    all_signals.extend(check_dual_track_limits(portfolio, state))

    print_signals(all_signals)

    # Write critical signals to pending_signals
    critical_signals = [s for s in all_signals if s.get("priority") == "CRITICAL"]
    if critical_signals:
        pending = state.get("pending_signals", [])
        for sig in critical_signals:
            if sig not in pending:
                pending.append(sig)
        state["pending_signals"] = pending
        save_json(STATE_FILE, state)
        print(f"  [写入] {len(critical_signals)} 条CRITICAL信号 → rotation_state.json pending_signals")
        print()

    # Summary
    divider = "─" * 64
    print(divider)
    n_crit = len([s for s in all_signals if s.get("priority") == "CRITICAL"])
    n_high = len([s for s in all_signals if s.get("priority") == "HIGH"])
    if n_crit > 0:
        print(f"  ⛔ 结论: {n_crit}条CRITICAL + {n_high}条HIGH — 需立即处理")
    elif n_high > 0:
        print(f"  ⚠️  结论: {n_high}条HIGH — 当日内处理")
    else:
        print("  ✅ 结论: TB系统正常运行")
    print(divider)
    print()


if __name__ == "__main__":
    main()

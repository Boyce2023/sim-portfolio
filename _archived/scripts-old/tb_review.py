#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Track B 盘后日评 — CB状态自动追踪 + 持仓天数警告 + 升降级检查

用法:
  uv run --script scripts/tb_review.py

输出:
  更新 tb_scorecard.json（CB/CA状态）
  输出持仓天数警告 + 降级建议
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STATE_FILE = REPO / "rotation_state.json"
PORTFOLIO_FILE = REPO / "portfolio_state.json"
SCORECARD_FILE = REPO / "tb_scorecard.json"

# ── Type → 持有天数上限 ──────────────────────────────────────────────────────

TYPE_HOLDING_LIMITS = {
    "T1": 5,
    "T2": 45,
    "T3": 5,
    "T4": 15,
    "T5": 12,
    "BSE": 7,
}

# ── I/O ─────────────────────────────────────────────────────────────────────

def load_json(path: Path) -> dict:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}

def save_json(path: Path, data: dict) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ── CB 状态追踪 ─────────────────────────────────────────────────────────────

def update_cb_state(trade_log: list, scorecard: dict) -> dict:
    """7日滚动窗口统计rule_violation型亏损，更新CB状态。"""
    today = datetime.now()
    cutoff = today - timedelta(days=7)

    violations = []
    for t in trade_log:
        if t.get("track") != "B":
            continue
        if t.get("realized_pnl", 0) >= 0:
            continue
        if not t.get("rule_violation", False):
            continue
        exit_date_str = t.get("exit_date") or t.get("date", "")
        if not exit_date_str:
            continue
        try:
            exit_date = datetime.strptime(exit_date_str[:10], "%Y-%m-%d")
        except ValueError:
            continue
        if exit_date >= cutoff:
            violations.append(t)

    count = len(violations)
    if count >= 3:
        new_state = "RED"
    elif count >= 2:
        new_state = "YELLOW"
    else:
        new_state = "GREEN"

    scorecard["cb_state"] = new_state
    scorecard["cb_violation_count_7d"] = count
    scorecard["cb_last_updated"] = today.strftime("%Y-%m-%d")
    return scorecard


# ── CA 状态追踪 ─────────────────────────────────────────────────────────────

def update_ca_state(trade_log: list, scorecard: dict) -> dict:
    """Track consecutive wins for CA (Confidence Amplifier)."""
    tb_trades = [t for t in trade_log if t.get("track") == "B" and t.get("exit_date")]
    tb_trades.sort(key=lambda t: t.get("exit_date", ""), reverse=True)

    consec_wins = 0
    for t in tb_trades[:10]:
        if t.get("realized_pnl", 0) > 0:
            consec_wins += 1
        else:
            break

    scorecard["ca_consecutive_wins"] = consec_wins

    if consec_wins >= 5:
        scorecard["ca_state"] = "AMPLIFIED"
    elif consec_wins >= 3:
        scorecard["ca_state"] = "WARMING"
    else:
        scorecard["ca_state"] = "NORMAL"

    return scorecard


# ── TB持仓天数检查 ──────────────────────────────────────────────────────────

def check_holding_days(positions: list) -> list[dict]:
    """Return alerts for positions approaching or exceeding time limits."""
    today = datetime.now()
    alerts = []

    for pos in positions:
        if pos.get("track") != "B":
            continue

        name = pos.get("name", pos.get("ticker", "?"))
        tb_type = pos.get("tb_type", "T1")
        entry_str = pos.get("tb_entry_date") or pos.get("entry_date", "")

        if not entry_str:
            alerts.append({
                "ticker": pos.get("ticker"),
                "name": name,
                "level": "ERROR",
                "message": "缺少tb_entry_date字段",
            })
            continue

        try:
            entry_date = datetime.strptime(entry_str[:10], "%Y-%m-%d")
        except ValueError:
            continue

        days_held = (today - entry_date).days
        limit = TYPE_HOLDING_LIMITS.get(tb_type, 10)

        if days_held >= limit:
            alerts.append({
                "ticker": pos.get("ticker"),
                "name": name,
                "level": "CRITICAL",
                "message": f"⛔ 持有{days_held}天 ≥ {tb_type}上限{limit}天 — 应当日出场",
            })
        elif days_held >= limit - 1:
            alerts.append({
                "ticker": pos.get("ticker"),
                "name": name,
                "level": "WARNING",
                "message": f"⚠️  持有{days_held}天，明日达{tb_type}上限{limit}天 — 准备出场",
            })
        elif days_held >= limit - 2:
            alerts.append({
                "ticker": pos.get("ticker"),
                "name": name,
                "level": "INFO",
                "message": f"ℹ️  持有{days_held}天，距{tb_type}上限{limit}天还有{limit - days_held}天",
            })

    return alerts


# ── 降级检查 ────────────────────────────────────────────────────────────────

def check_downgrades(positions: list, state: dict) -> list[dict]:
    """Check if any TB position should be downgraded based on market conditions."""
    alerts = []
    board_break = state.get("market_context", {}).get("board_break_rate", 0)

    for pos in positions:
        if pos.get("track") != "B":
            continue

        name = pos.get("name", pos.get("ticker", "?"))
        grade = pos.get("tb_grade", "B")

        if board_break > 50:
            alerts.append({
                "ticker": pos.get("ticker"),
                "name": name,
                "level": "CRITICAL",
                "message": f"炸板率{board_break:.0f}%>50% — {grade}→降级1档 + 减仓",
            })

        if board_break > 60:
            alerts.append({
                "ticker": pos.get("ticker"),
                "name": name,
                "level": "CRITICAL",
                "message": f"炸板率{board_break:.0f}%>60% — 一票否决，当日全出",
            })

    return alerts


# ── Type暂停检查 ─────────────────────────────────────────────────────────────

def check_type_suspensions(scorecard: dict) -> list[str]:
    """Return list of messages about suspended types."""
    msgs = []
    suspensions = scorecard.get("type_suspensions", {})
    today = datetime.now().strftime("%Y-%m-%d")

    for type_id, info in suspensions.items():
        expires = info.get("expires", "")
        if expires and expires > today:
            reason = info.get("reason", "")
            msgs.append(f"  ⛔ {type_id} 暂停至 {expires}: {reason}")

    return msgs


# ── 输出 ────────────────────────────────────────────────────────────────────

def print_header():
    print()
    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║           Track B 盘后日评 — tb_review.py                      ║")
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"║  日评时间: {now}                                         ║")
    print("╚══════════════════════════════════════════════════════════════════╝")
    print()


def print_cb_state(scorecard: dict):
    cb = scorecard.get("cb_state", "GREEN")
    count = scorecard.get("cb_violation_count_7d", 0)
    icon = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}.get(cb, "❓")
    print(f"  Circuit Breaker (CB): {icon} {cb}")
    print(f"    7日违规亏损: {count}笔")
    if cb == "YELLOW":
        print("    ⚠️  已触发黄灯 — TB sizing ×0.5，新建仓需额外确认")
    elif cb == "RED":
        print("    ⛔ 已触发红灯 — TB暂停7天，不可新建仓")
    print()


def print_ca_state(scorecard: dict):
    ca = scorecard.get("ca_state", "NORMAL")
    wins = scorecard.get("ca_consecutive_wins", 0)
    icon = {"NORMAL": "⬜", "WARMING": "🔥", "AMPLIFIED": "🔥🔥"}.get(ca, "⬜")
    print(f"  Confidence Amplifier (CA): {icon} {ca}")
    print(f"    连胜: {wins}笔")
    if ca == "AMPLIFIED":
        print("    ✅ 信心放大生效 — sizing可+1档（不超B+上限）")
    print()


def print_position_table(positions: list):
    tb_pos = [p for p in positions if p.get("track") == "B"]
    if not tb_pos:
        print("  TB持仓: 无")
        print()
        return

    divider = "─" * 74
    print("  TB持仓详情:")
    print(f"  {divider}")
    print(f"  {'名称':<10} {'等级':<4} {'类型':<4} {'持有天数':>6} {'上限':>4} {'龙头':<8} {'浮盈%':>7}")
    print(f"  {divider}")

    today = datetime.now()
    for p in tb_pos:
        name = (p.get("name", "?"))[:10]
        grade = p.get("tb_grade", "?")
        tb_type = p.get("tb_type", "?")
        leader = (p.get("tb_leader", "?"))[:8]
        pnl_pct = p.get("unrealized_pnl_pct", 0)

        entry_str = p.get("tb_entry_date") or p.get("entry_date", "")
        days = 0
        if entry_str:
            try:
                days = (today - datetime.strptime(entry_str[:10], "%Y-%m-%d")).days
            except ValueError:
                pass

        limit = TYPE_HOLDING_LIMITS.get(tb_type, 10)
        pnl_str = f"{pnl_pct:+.1f}%"

        print(f"  {name:<10} {grade:<4} {tb_type:<4} {days:>6}  {limit:>4}  {leader:<8} {pnl_str:>7}")

    print(f"  {divider}")
    print()


def print_alerts(holding_alerts: list, downgrade_alerts: list):
    all_alerts = holding_alerts + downgrade_alerts
    if not all_alerts:
        print("  ✅ 无警报")
        print()
        return

    critical = [a for a in all_alerts if a.get("level") == "CRITICAL"]
    warnings = [a for a in all_alerts if a.get("level") == "WARNING"]
    info = [a for a in all_alerts if a.get("level") == "INFO"]

    if critical:
        print("  ⛔ CRITICAL 警报:")
        for a in critical:
            print(f"    [{a.get('name', '?')}] {a['message']}")

    if warnings:
        print("  ⚠️  WARNING:")
        for a in warnings:
            print(f"    [{a.get('name', '?')}] {a['message']}")

    if info:
        print("  ℹ️  INFO:")
        for a in info:
            print(f"    [{a.get('name', '?')}] {a['message']}")

    print()


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    portfolio = load_json(PORTFOLIO_FILE)
    scorecard = load_json(SCORECARD_FILE)
    state = load_json(STATE_FILE)
    trade_log = portfolio.get("trade_log", [])

    print_header()

    # CB update
    scorecard = update_cb_state(trade_log, scorecard)
    print_cb_state(scorecard)

    # CA update
    scorecard = update_ca_state(trade_log, scorecard)
    print_ca_state(scorecard)

    # Type suspensions
    susp_msgs = check_type_suspensions(scorecard)
    if susp_msgs:
        print("  类型暂停:")
        for m in susp_msgs:
            print(m)
        print()

    # Position table
    all_positions = []
    for acct in portfolio.get("accounts", {}).values():
        all_positions.extend(acct.get("positions", []))

    print_position_table(all_positions)

    # Holding day alerts
    holding_alerts = check_holding_days(all_positions)

    # Downgrade checks
    downgrade_alerts = check_downgrades(all_positions, state)

    print_alerts(holding_alerts, downgrade_alerts)

    # Market context recap
    ctx = state.get("market_context", {})
    f20 = state.get("market_breath", "未知")
    switch = state.get("market_switch", "未知")
    print(f"  市场状态: F20={f20} / switch={switch}")
    if ctx.get("limit_up_count"):
        print(f"  涨停{ctx['limit_up_count']}家 / 炸板率{ctx.get('board_break_rate', 0):.0f}% / 成交{ctx.get('turnover_billion', 0):.0f}亿")
    print()

    # Save scorecard
    save_json(SCORECARD_FILE, scorecard)
    print(f"  [写入] tb_scorecard.json — CB={scorecard['cb_state']} / CA={scorecard['ca_state']}")
    print()


if __name__ == "__main__":
    main()

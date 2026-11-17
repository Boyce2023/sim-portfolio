#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Track B 每日主线扫描 — 硬开关检测 + F20状态 + 活跃主线持续性

用法:
  # 交互模式（提示输入市场数据）
  uv run --script scripts/tb_scan.py

  # 命令行参数模式
  uv run --script scripts/tb_scan.py --limit-up 75 --board-break 22 --turnover 11500 --northbound 85

  # 仅检查硬开关（快速模式）
  uv run --script scripts/tb_scan.py --quick --limit-up 45 --board-break 55

输出:
  更新 rotation_state.json（market_switch / market_breath / market_context）
  输出 GO/NO-GO 决策 + 活跃主线状态
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STATE_FILE = REPO / "rotation_state.json"
PORTFOLIO_FILE = REPO / "portfolio_state.json"
SCORECARD_FILE = REPO / "tb_scorecard.json"

# ── F20 thresholds ──────────────────────────────────────────────────────────

F20_RULES = {
    "强吸气": {"limit_up_min": 80, "board_break_max": 20, "tb_cap": 0.40},
    "吸气":   {"limit_up_min": 60, "board_break_max": 30, "tb_cap": 0.30},
    "中性":   {"limit_up_min": 30, "board_break_max": 50, "tb_cap": 0.15},
    "呼气":   {"limit_up_max": 30, "board_break_min": 50, "tb_cap": 0.00},
    "深度呼气": {"limit_up_max": 30, "turnover_max": 5000, "tb_cap": 0.00},
}

# ── State I/O ───────────────────────────────────────────────────────────────

def load_json(path: Path) -> dict:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}

def save_json(path: Path, data: dict) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  [写入] {path.name}")


# ── F20 判定 ────────────────────────────────────────────────────────────────

def determine_f20(limit_up: int, board_break: float, turnover: float,
                  northbound: float | None, limit_down: int,
                  prev_state: dict) -> tuple[str, str]:
    """Return (f20_state, reason)."""

    if limit_down > 50:
        return "深度呼气", f"跌停{limit_down}家>50 — 崩溃期"

    if limit_up < 30 and turnover < 5000:
        return "深度呼气", f"涨停{limit_up}<30 + 成交{turnover:.0f}亿<5000亿"

    consec = prev_state.get("market_context", {}).get("consecutive_low_days", 0)
    if limit_up < 30:
        new_consec = consec + 1 if consec >= 0 else 1
        if new_consec >= 3:
            return "呼气", f"涨停{limit_up}<30 连续{new_consec}日 — 强制覆盖为呼气"
        return "中性", f"涨停{limit_up}<30（连续{new_consec}日，<3日暂定中性）"

    if board_break > 50:
        return "呼气", f"炸板率{board_break:.0f}%>50%"

    if limit_up >= 80 and board_break < 20:
        return "强吸气", f"涨停{limit_up}≥80 + 炸板率{board_break:.0f}%<20%"

    if limit_up >= 60 and board_break < 30:
        extra = ""
        if northbound is not None and northbound > 0:
            extra = f" + 北向净流入{northbound:.0f}亿"
        return "吸气", f"涨停{limit_up}家 + 炸板率{board_break:.0f}%{extra}"

    return "中性", f"涨停{limit_up}家 / 炸板率{board_break:.0f}%（模糊区间）"


# ── 硬开关 ──────────────────────────────────────────────────────────────────

def check_hard_switch(limit_up: int, board_break: float, limit_down: int,
                      index_chg: float | None, f20: str,
                      active_themes: list) -> list[dict]:
    """Return list of triggered hard-switch signals."""
    signals = []

    if index_chg is not None and index_chg <= -1.5:
        signals.append({
            "type": "HARD_SWITCH",
            "rule": "大盘跌≥1.5%",
            "detail": f"大盘涨跌幅 {index_chg:+.2f}%",
            "action": "NO-GO（T1直接受益方豁免除外）",
        })

    if limit_down > 50:
        signals.append({
            "type": "HARD_SWITCH",
            "rule": "跌停>50家",
            "detail": f"跌停{limit_down}家",
            "action": "NO-GO + 全仓TB清仓审查",
        })

    if f20 in ("呼气", "深度呼气"):
        signals.append({
            "type": "HARD_SWITCH",
            "rule": f"F20={f20}",
            "detail": "零新仓" if f20 == "呼气" else "TB仓位归零",
            "action": "NO-GO",
        })

    if board_break > 60:
        signals.append({
            "type": "HARD_SWITCH",
            "rule": "炸板率>60%",
            "detail": f"炸板率{board_break:.0f}% — 崩溃期一票否决",
            "action": "当日全出所有TB仓位",
        })

    return signals


# ── 活跃主线持续性检查 ──────────────────────────────────────────────────────

def check_theme_persistence(active_themes: list, limit_up: int,
                            board_break: float) -> list[dict]:
    """Check each active theme for continuation/exit signals."""
    alerts = []
    today = datetime.now().strftime("%Y-%m-%d")

    for theme in active_themes:
        name = theme.get("name", "未知")
        days = 0
        if theme.get("start_date"):
            try:
                start = datetime.strptime(theme["start_date"], "%Y-%m-%d")
                days = (datetime.now() - start).days
            except ValueError:
                pass

        if theme.get("crowding", 0) > 40:
            alerts.append({
                "theme": name,
                "signal": "CROWDING",
                "detail": f"拥挤度{theme['crowding']:.0f}%>40% — 触发降级",
            })

        if days > 20 and theme.get("tier", "") not in ("T2",):
            alerts.append({
                "theme": name,
                "signal": "AGING",
                "detail": f"主线已运行{days}天，非T2型，注意时间止损",
            })

        if theme.get("leader_status") == "断板":
            alerts.append({
                "theme": name,
                "signal": "LEADER_BREAK",
                "detail": "龙头断板 — 退出信号",
            })

    return alerts


# ── TB持仓统计 ──────────────────────────────────────────────────────────────

def get_tb_positions(portfolio: dict) -> list[dict]:
    """Extract Track B positions from portfolio."""
    positions = []
    for acct_key in ("a_share",):
        acct = portfolio.get("accounts", {}).get(acct_key, {})
        for pos in acct.get("positions", []):
            if pos.get("track") == "B":
                positions.append(pos)
    return positions

def calc_tb_exposure(portfolio: dict) -> tuple[float, int]:
    """Return (tb_total_pct, tb_count)."""
    tb_pos = get_tb_positions(portfolio)
    total_pct = sum(p.get("portfolio_pct", 0) for p in tb_pos)
    return total_pct, len(tb_pos)


# ── Portfolio Heat ──────────────────────────────────────────────────────────

def calc_portfolio_heat(portfolio: dict) -> float:
    """Sum of abs(unrealized_pnl_pct * portfolio_pct) for all positions as a rough heat metric."""
    heat = 0.0
    for acct in portfolio.get("accounts", {}).values():
        for pos in acct.get("positions", []):
            pnl_pct = abs(pos.get("unrealized_pnl_pct", 0))
            weight = pos.get("portfolio_pct", 0)
            if pnl_pct < 0:
                heat += abs(pnl_pct) * weight
    return heat * 100


# ── 输出 ────────────────────────────────────────────────────────────────────

def print_header():
    print()
    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║           Track B 每日主线扫描 — tb_scan.py                    ║")
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"║  扫描时间: {now}                                         ║")
    print("╚══════════════════════════════════════════════════════════════════╝")
    print()

def print_f20(f20: str, reason: str, tb_cap: float):
    emoji = {"强吸气": "🟢🟢", "吸气": "🟢", "中性": "🟡", "呼气": "🔴", "深度呼气": "🔴🔴"}
    cap_str = f"{tb_cap*100:.0f}%" if tb_cap > 0 else "0%（零新仓）"
    print(f"  F20市场呼吸: {emoji.get(f20, '')} {f20}")
    print(f"  判断依据: {reason}")
    print(f"  TB仓位上限: {cap_str}")
    print()

def print_hard_switches(switches: list[dict]):
    if not switches:
        print("  硬开关: ✅ 全部通过（无触发）")
        print()
        return
    print("  硬开关: ❌ 触发！")
    for s in switches:
        print(f"    ⛔ {s['rule']}: {s['detail']}")
        print(f"       → {s['action']}")
    print()

def print_go_nogo(switches: list[dict], f20: str, tb_pct: float, tb_count: int, heat: float):
    divider = "─" * 64
    print(divider)

    has_block = len(switches) > 0 or f20 in ("呼气", "深度呼气")

    if has_block:
        print("  ⛔ GO/NO-GO 判定: NO-GO")
        reasons = [s["rule"] for s in switches]
        if f20 in ("呼气", "深度呼气") and f"F20={f20}" not in reasons:
            reasons.append(f"F20={f20}")
        print(f"     原因: {' | '.join(reasons)}")
    else:
        if heat > 15:
            print("  ⚠️  GO/NO-GO 判定: GO（但Heat>15% — 暂停新TB建仓）")
        elif heat > 13:
            print("  🟡 GO/NO-GO 判定: GO（Heat>13% — 新TB sizing ×0.7）")
        else:
            print("  ✅ GO/NO-GO 判定: GO")

    print(f"     TB当前: {tb_count}只 / {tb_pct*100:.1f}%")
    print(f"     Portfolio Heat: {heat:.1f}%")
    print(divider)
    print()


def print_theme_alerts(alerts: list[dict]):
    if not alerts:
        return
    print("  活跃主线警报:")
    for a in alerts:
        icon = {"CROWDING": "⚠️", "AGING": "⏰", "LEADER_BREAK": "💀"}.get(a["signal"], "❓")
        print(f"    {icon} [{a['theme']}] {a['signal']}: {a['detail']}")
    print()


# ── CLI ─────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="Track B 每日主线扫描")
    p.add_argument("--limit-up", type=int, help="全市场涨停家数")
    p.add_argument("--limit-down", type=int, default=0, help="跌停家数")
    p.add_argument("--board-break", type=float, help="炸板率(%%)")
    p.add_argument("--turnover", type=float, help="全市场成交额(亿)")
    p.add_argument("--northbound", type=float, default=None, help="北向资金净流入(亿)")
    p.add_argument("--index-chg", type=float, default=None, help="大盘涨跌幅(%%)")
    p.add_argument("--quick", action="store_true", help="仅检查硬开关，不更新主线")
    return p.parse_args()


def prompt_missing(args):
    """Prompt user for any missing required fields."""
    if args.limit_up is None:
        try:
            args.limit_up = int(input("涨停家数: "))
        except (ValueError, EOFError):
            print("ERROR: 需要涨停家数", file=sys.stderr)
            sys.exit(1)

    if args.board_break is None:
        try:
            args.board_break = float(input("炸板率(%): "))
        except (ValueError, EOFError):
            print("ERROR: 需要炸板率", file=sys.stderr)
            sys.exit(1)

    if args.turnover is None:
        try:
            val = input("全市场成交额(亿, 直接回车跳过): ").strip()
            args.turnover = float(val) if val else 8000.0
        except (ValueError, EOFError):
            args.turnover = 8000.0


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    args = parse_args()

    if not sys.stdin.isatty() and args.limit_up is None:
        print("ERROR: 非交互模式需提供 --limit-up 和 --board-break", file=sys.stderr)
        sys.exit(1)

    prompt_missing(args)

    state = load_json(STATE_FILE)
    portfolio = load_json(PORTFOLIO_FILE)
    today = datetime.now().strftime("%Y-%m-%d")

    print_header()

    # ── F20 判定 ──
    f20, reason = determine_f20(
        args.limit_up, args.board_break, args.turnover,
        args.northbound, args.limit_down, state,
    )
    tb_cap = F20_RULES.get(f20, {}).get("tb_cap", 0.15)
    print_f20(f20, reason, tb_cap)

    # ── 硬开关检测 ──
    active_themes = state.get("active_themes", [])
    switches = check_hard_switch(
        args.limit_up, args.board_break, args.limit_down,
        args.index_chg, f20, active_themes,
    )
    print_hard_switches(switches)

    # ── TB持仓统计 ──
    tb_pct, tb_count = calc_tb_exposure(portfolio)
    heat = calc_portfolio_heat(portfolio)
    print_go_nogo(switches, f20, tb_pct, tb_count, heat)

    # ── 活跃主线持续性 ──
    if not args.quick:
        alerts = check_theme_persistence(active_themes, args.limit_up, args.board_break)
        print_theme_alerts(alerts)

    # ── 更新 rotation_state.json ──
    consec = state.get("market_context", {}).get("consecutive_low_days", 0)
    if args.limit_up < 30:
        new_consec = consec + 1 if consec >= 0 else 1
    else:
        new_consec = 0

    market_switch = "OPEN"
    if switches:
        for s in switches:
            if "清仓" in s.get("action", "") or "归零" in s.get("detail", ""):
                market_switch = "EMERGENCY_CLOSE"
                break
        if market_switch != "EMERGENCY_CLOSE":
            market_switch = "CLOSED"

    if f20 in ("呼气", "深度呼气"):
        market_switch = "CLOSED"

    state.update({
        "market_switch": market_switch,
        "market_breath": f20,
        "f20_last_updated": today,
        "market_context": {
            "limit_up_count": args.limit_up,
            "limit_down_count": args.limit_down,
            "turnover_billion": args.turnover,
            "board_break_rate": args.board_break,
            "northbound_net": args.northbound,
            "index_change_pct": args.index_chg,
            "consecutive_low_days": new_consec,
        },
        "last_scan": today,
    })

    if "active_themes" not in state:
        state["active_themes"] = []
    if "watch_pool" not in state:
        state["watch_pool"] = []
    if "pending_signals" not in state:
        state["pending_signals"] = []
    if "restart_confirmation" not in state:
        state["restart_confirmation"] = {"days_normal": 0, "restart_ready": False}

    # 重启确认逻辑
    restart = state["restart_confirmation"]
    if market_switch == "OPEN":
        restart["days_normal"] = restart.get("days_normal", 0) + 1
        if restart["days_normal"] >= 3:
            restart["restart_ready"] = True
    else:
        restart["days_normal"] = 0
        restart["restart_ready"] = False

    save_json(STATE_FILE, state)

    # ── 总结 ──
    print(f"  rotation_state.json 已更新: switch={market_switch} / breath={f20}")
    print()


if __name__ == "__main__":
    main()

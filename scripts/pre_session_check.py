# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
pre_session_check.py — Automated compliance gate for sim-portfolio sessions.

Runs at the START of every trading session. Reads portfolio_state.json and
pending_actions.json, performs deterministic rule checks, and emits a
pass/fail report.

Usage:
  python3 scripts/pre_session_check.py                # both markets (default)
  python3 scripts/pre_session_check.py --market astock
  python3 scripts/pre_session_check.py --market us
  python3 scripts/pre_session_check.py --json
  python3 scripts/pre_session_check.py --market us --json

Exit codes:
  0 = CLEARED (all checks pass)
  1 = BLOCKED (one or more HARD BLOCKS)
  2 = ERROR (file not found, JSON parse error, etc.)
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

# ── File paths ───────────────────────────────────────────────────────────────
PORTFOLIO_PATH   = Path(__file__).parent.parent / "portfolio_state.json"
PENDING_PATH     = Path(__file__).parent.parent / "pending_actions.json"
LAST_REGIME_PATH = Path(__file__).parent.parent / "daily-reviews"
RESULT_PATH      = Path(__file__).parent / "session_check_result.json"

# ── HARD BLOCK thresholds ────────────────────────────────────────────────────
US_MAX_POSITIONS    = 9      # L16: total US longs ≤ 9
US_MIN_POSITION_USD = 7500   # L16: every US position ≥ $7,500
US_MIN_SHORT_PCT    = 0.05   # L18: short exposure ≥ 5% of US portfolio
US_MIN_CASH_PCT     = 0.15   # strategy.md §3.2: US cash ≥ 15%
CN_MAX_POSITIONS    = 8      # strategy.md §3: A股 持仓 ≤ 8
CN_MIN_CASH_PCT     = 0.20   # strategy.md §3.2: A-share cash ≥ 20% (before new positions)
CN_HOLD_CASH_PCT    = 0.15   # strategy.md §3.2: A-share cash ≥ 15% (daily hold)
P0_P1_OVERDUE_DAYS  = 2      # pending actions P0/P1 older than 2 trading days = BLOCK

# ── SOFT WARNING thresholds ──────────────────────────────────────────────────
US_SHORT_TARGET_LOW  = 0.10  # L18 target band low end 10%
US_MAX_SINGLE_PCT    = 0.15  # warn if US position > 15% (A-grade allowed to 25%)
CN_MAX_SINGLE_PCT    = 0.12  # warn if A-share position > 12% (soft)
CN_MAX_SECTOR_PCT    = 0.40  # warn if A-share sector > 40%
C_GRADE_MAX_DAYS     = 14    # C-grade positions older than 14 days
REGIME_STALE_DAYS    = 3     # warn if last regime check > 3 days old

# ── Market keyword sets for pending action filtering ─────────────────────────
ASTOCK_KEYWORDS = {"astock", "a_share", "a股", "cn", "china", "sse", "szse"}
US_KEYWORDS     = {"us", "usd", "nyse", "nasdaq", "american"}


# ─────────────────────────────────────────────────────────────────────────────
# Data model
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CheckItem:
    check_id: str
    category: str      # "HARD_BLOCK" or "SOFT_WARNING"
    passed: bool
    label: str
    detail: str
    rule_ref: str


@dataclass
class CheckReport:
    date: str
    market: str        # "astock", "us", or "both"
    hard_blocks: list = field(default_factory=list)
    soft_warnings: list = field(default_factory=list)
    passed_checks: list = field(default_factory=list)
    verdict: str = "CLEARED"
    block_count: int = 0
    warning_count: int = 0
    pass_count: int = 0


# ─────────────────────────────────────────────────────────────────────────────
# File loading
# ─────────────────────────────────────────────────────────────────────────────

def load_portfolio(path: Path) -> dict:
    """Load portfolio_state.json. Exit code 2 on missing file or JSON error."""
    if not path.exists():
        print(f"ERROR: portfolio_state.json not found at {path}", file=sys.stderr)
        sys.exit(2)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"ERROR: Failed to parse portfolio_state.json: {exc}", file=sys.stderr)
        sys.exit(2)


def load_pending(path: Path) -> dict:
    """Load pending_actions.json. Returns empty structure if file absent."""
    if not path.exists():
        return {"pending": [], "completed": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"pending": [], "completed": []}


# ─────────────────────────────────────────────────────────────────────────────
# Utility functions
# ─────────────────────────────────────────────────────────────────────────────

def trading_days_between(start_iso: str, end_iso: str) -> int:
    """
    Count Mon–Fri business days between two ISO date strings.
    Inclusive of start, exclusive of end. Approximate (no holiday table used).
    """
    try:
        start = date.fromisoformat(start_iso[:10])
        end = date.fromisoformat(end_iso[:10])
    except ValueError:
        return 0
    if end <= start:
        return 0
    count = 0
    current = start
    while current < end:
        if current.weekday() < 5:  # Mon=0 … Fri=4
            count += 1
        current += timedelta(days=1)
    return count


def count_trading_days_held(entry_date_iso: str) -> int:
    """Approximate trading days from entry_date to today (weekdays only)."""
    return trading_days_between(entry_date_iso[:10], date.today().isoformat())


def calc_position_value(pos: dict) -> float:
    """
    Returns market_value if present and > 0.
    Fallback: current_price × shares if current_price present.
    Fallback: avg_cost × shares.
    """
    mv = pos.get("market_value")
    if mv and float(mv) > 0:
        return float(mv)
    shares = int(pos.get("shares", 0))
    price = pos.get("current_price")
    if price:
        return float(price) * shares
    return float(pos.get("avg_cost", 0)) * shares


def calc_us_short_exposure(us_account: dict) -> tuple[float, float]:
    """
    Returns (short_value_usd, short_pct).
    short_value_usd = sum of shares × entry_price for each ShortPosition.
    short_pct = short_value_usd / total_assets.
    Returns (0.0, 0.0) if short_positions absent or empty.
    """
    short_positions = us_account.get("short_positions", [])
    total_assets = float(us_account.get("total_assets", 0))
    if not short_positions:
        return 0.0, 0.0
    short_value = sum(
        int(p.get("shares", 0)) * float(p.get("entry_price", 0))
        for p in short_positions
        if p.get("instrument_type") == "short"
    )
    short_pct = short_value / total_assets if total_assets > 0 else 0.0
    return short_value, short_pct


def days_since_last_regime_check(daily_reviews_dir: Path) -> Optional[int]:
    """
    Scan daily-reviews/ for most recent .md file containing regime-relevant keywords.
    Returns integer days since that file's date. Returns None if no matching file.
    """
    if not daily_reviews_dir.exists():
        return None

    pattern = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")
    matching_dates = []

    for f in daily_reviews_dir.iterdir():
        m = pattern.match(f.name)
        if not m:
            continue
        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        keywords = ["Regime", "regime", "VIX", "L17", "L18"]
        if any(kw in content for kw in keywords):
            try:
                matching_dates.append(date.fromisoformat(m.group(1)))
            except ValueError:
                pass

    if not matching_dates:
        return None

    latest = max(matching_dates)
    return (date.today() - latest).days


def pending_matches_market(action: dict, market: Optional[str]) -> bool:
    """
    Returns True if the pending action should be included for the given market filter.
    - market=None: include all
    - market='astock': include if action has no market field, or market field matches astock
    - market='us': include if action has no market field, or market field matches us
    Actions without a market field are included in both market scopes.
    """
    if market is None:
        return True
    action_market = str(action.get("market", "")).lower().strip()
    if not action_market:
        # No market specified — include in both scopes
        return True
    if market == "astock":
        return any(kw in action_market for kw in ASTOCK_KEYWORDS)
    if market == "us":
        return any(kw in action_market for kw in US_KEYWORDS)
    return True


# ─────────────────────────────────────────────────────────────────────────────
# A股-specific HARD BLOCK checkers
# ─────────────────────────────────────────────────────────────────────────────

def check_cn_position_count(state: dict) -> CheckItem:
    """A股 total positions ≤ 8."""
    positions = state["accounts"]["a_share"].get("positions", [])
    count = len(positions)
    passed = count <= CN_MAX_POSITIONS
    if not passed:
        detail = f"A股持仓: {count}/{CN_MAX_POSITIONS} (超出 {count - CN_MAX_POSITIONS} 只)"
    else:
        detail = f"A股持仓: {count}/{CN_MAX_POSITIONS}"
    return CheckItem(
        check_id="CN_POSITION_COUNT",
        category="HARD_BLOCK",
        passed=passed,
        label=f"A股持仓: {count}/{CN_MAX_POSITIONS}",
        detail=detail,
        rule_ref="strategy.md §3 — A股持仓≤8只",
    )


def check_cn_cash_reserve(state: dict) -> CheckItem:
    """A-share cash ≥ 20% of A-share total_assets (before adding positions)."""
    cn = state["accounts"]["a_share"]
    cash = float(cn.get("cash", 0))
    total = float(cn.get("total_assets", 0))
    pct = cash / total if total > 0 else 1.0
    passed = pct >= CN_MIN_CASH_PCT
    detail = (
        f"A股现金: {pct:.1%} (加仓前须≥{CN_MIN_CASH_PCT:.0%}，持仓须≥{CN_HOLD_CASH_PCT:.0%})"
    )
    return CheckItem(
        check_id="CN_CASH_RESERVE",
        category="HARD_BLOCK",
        passed=passed,
        label=f"A股现金: {pct:.1%}",
        detail=detail,
        rule_ref="strategy.md §3.2 — 现金≥20% (加仓前须≥20%)",
    )


def check_cn_bear_case_documented(state: dict) -> CheckItem:
    """All A股 positions must have a documented bear_case field."""
    violations = []
    for pos in state["accounts"]["a_share"].get("positions", []):
        bear_case = pos.get("bear_case", "")
        if not bear_case or not str(bear_case).strip():
            violations.append(pos.get("name") or pos.get("ticker", "?"))

    total = len(state["accounts"]["a_share"].get("positions", []))
    passed = len(violations) == 0
    if not passed:
        detail = f"缺失bear case: {', '.join(violations)}"
        label_str = f"A股缺失bear case: {len(violations)} 只"
    else:
        detail = f"A股全部 {total} 只持仓已记录bear case"
        label_str = f"A股全部 {total} 只已记录bear case"

    return CheckItem(
        check_id="CN_BEAR_CASE_DOCUMENTED",
        category="HARD_BLOCK",
        passed=passed,
        label=label_str,
        detail=detail,
        rule_ref="strategy.md §3.1 — bear case 4-tier, 进场检查表",
    )


def check_cn_pending_overdue(state: dict, pending_data: dict, market: Optional[str]) -> CheckItem:
    """Block if any A股 P0/P1 pending action is overdue by > 2 trading days."""
    pending_items = pending_data.get("pending", [])
    today = date.today().isoformat()
    P0_TYPES = {"regime_adjustment", "short"}
    overdue = []

    for action in pending_items:
        if action.get("status") == "completed":
            continue
        if not pending_matches_market(action, market):
            continue

        priority = action.get("priority", "medium")
        status = action.get("status", "pending")
        action_type = action.get("type", "")
        created_at = action.get("created_at", "")
        if not created_at:
            continue

        is_p0 = (status == "urgent") or (priority == "high" and action_type in P0_TYPES)
        is_p1 = (priority == "high") and not is_p0

        if not (is_p0 or is_p1):
            continue

        days_old = trading_days_between(created_at[:10], today)
        if days_old > P0_P1_OVERDUE_DAYS:
            overdue.append({
                "id": action.get("id", "?"),
                "name": action.get("name", ""),
                "type": action_type,
                "days_overdue": days_old - P0_P1_OVERDUE_DAYS,
            })

    passed = len(overdue) == 0
    market_label = "A股" if market == "astock" else ""
    if not passed:
        parts = "; ".join(
            f"{o['id']} ({o['name']}, {o['type']}, {o['days_overdue']}d overdue)"
            for o in overdue
        )
        detail = f"{market_label} Overdue P0/P1: {parts}"
        label = f"{market_label} Overdue P0/P1 actions: {len(overdue)}"
    else:
        detail = f"{market_label} 无P0/P1逾期行动（>2个交易日）"
        label = f"{market_label} No P0/P1 overdue"

    return CheckItem(
        check_id="CN_PENDING_OVERDUE",
        category="HARD_BLOCK",
        passed=passed,
        label=label,
        detail=detail,
        rule_ref="L17 §4 — 每session第4步检查pending",
    )


# ─────────────────────────────────────────────────────────────────────────────
# A股-specific SOFT WARNING checkers
# ─────────────────────────────────────────────────────────────────────────────

def warn_cn_position_concentration(state: dict) -> CheckItem:
    """Any single A-share position > 12% of A-share portfolio (soft warning)."""
    cn = state["accounts"]["a_share"]
    total = float(cn.get("total_assets", 0))
    positions = cn.get("positions", [])
    violations = []

    for pos in positions:
        pct = pos.get("portfolio_pct")
        if pct is None and total > 0:
            pct = calc_position_value(pos) / total
        if pct is None:
            continue
        pct = float(pct)
        if pct > CN_MAX_SINGLE_PCT:
            violations.append((pos.get("ticker", "?"), pos.get("name", ""), pct))

    passed = len(violations) == 0
    if not passed:
        parts = ", ".join(
            f"{n or t} {p:.1%} (软警戒>{CN_MAX_SINGLE_PCT:.0%})"
            for t, n, p in violations
        )
        detail = f"A股集中度: {parts}"
        label = f"A股过度集中: {', '.join(n or t for t, n, _ in violations)}"
    else:
        detail = f"A股无单只持仓超过 {CN_MAX_SINGLE_PCT:.0%}"
        label = "A股集中度 OK"

    return CheckItem(
        check_id="CN_POSITION_CONCENTRATION",
        category="SOFT_WARNING",
        passed=passed,
        label=label,
        detail=detail,
        rule_ref="strategy.md §3.1 — B级≤15%，软警戒12%",
    )


def warn_cn_sector_concentration(state: dict) -> CheckItem:
    """Any single sector > 40% of A-share portfolio."""
    cn = state["accounts"]["a_share"]
    total = float(cn.get("total_assets", 0))
    positions = cn.get("positions", [])

    if total <= 0:
        return CheckItem(
            check_id="CN_SECTOR_CONCENTRATION",
            category="SOFT_WARNING",
            passed=True,
            label="A股板块集中度 OK",
            detail="无持仓数据",
            rule_ref="strategy.md §3 — 单板块≤40%",
        )

    sector_totals: dict[str, float] = {}
    for pos in positions:
        sector = pos.get("sector", "未知")
        pct = pos.get("portfolio_pct")
        if pct is None:
            pct = calc_position_value(pos) / total
        sector_totals[sector] = sector_totals.get(sector, 0.0) + float(pct)

    violations = [(s, p) for s, p in sector_totals.items() if p > CN_MAX_SECTOR_PCT]
    passed = len(violations) == 0

    if not passed:
        parts = ", ".join(f"{s} {p:.1%}" for s, p in violations)
        detail = f"A股板块集中度超40%: {parts}"
        label = f"A股板块过度集中: {', '.join(s for s, _ in violations)}"
    else:
        detail = "A股无单一板块超40%"
        label = "A股板块集中度 OK"

    return CheckItem(
        check_id="CN_SECTOR_CONCENTRATION",
        category="SOFT_WARNING",
        passed=passed,
        label=label,
        detail=detail,
        rule_ref="strategy.md §3 — 单板块≤40%",
    )


def warn_cn_c_grade_stale(state: dict) -> CheckItem:
    """C-grade or scout/catalyst positions in A股 held > 14 trading days."""
    stale = []
    for pos in state["accounts"]["a_share"].get("positions", []):
        conviction = pos.get("conviction_level", "")
        pos_type = pos.get("type", "")
        is_c = (
            conviction == "C"
            or pos_type == "scout_position"
            or pos_type == "catalyst_position"
        )
        if not is_c:
            continue
        entry = pos.get("entry_date", "")
        if not entry:
            continue
        days_held = count_trading_days_held(entry[:10])
        if days_held > C_GRADE_MAX_DAYS:
            name = pos.get("name") or pos.get("ticker", "?")
            stale.append((name, days_held))

    passed = len(stale) == 0
    if not passed:
        parts = ", ".join(f"{n} ({d}d)" for n, d in stale)
        detail = f"A股 C级/观察仓过期(>{C_GRADE_MAX_DAYS}d): {parts}"
        label = f"A股 C级过期: {', '.join(n for n, _ in stale)}"
    else:
        detail = f"A股无C级/观察仓超过{C_GRADE_MAX_DAYS}个交易日"
        label = f"A股无C级过期(>{C_GRADE_MAX_DAYS}d)"

    return CheckItem(
        check_id="CN_C_GRADE_STALE",
        category="SOFT_WARNING",
        passed=passed,
        label=label,
        detail=detail,
        rule_ref="strategy.md §3.1 — C级观察仓，快速止损机制",
    )


def warn_cn_pending_approaching(state: dict, pending_data: dict, market: Optional[str]) -> CheckItem:
    """A股 pending actions with trigger_date within 2 trading days."""
    today = date.today().isoformat()
    pending_items = pending_data.get("pending", [])
    approaching = []

    for action in pending_items:
        if action.get("status") == "completed":
            continue
        if not pending_matches_market(action, market):
            continue
        trigger_date = action.get("trigger_date", "")
        if not trigger_date:
            continue
        days_to_trigger = trading_days_between(today, trigger_date)
        if 0 < days_to_trigger <= 2:
            approaching.append({
                "id": action.get("id", "?"),
                "name": action.get("name", ""),
                "trigger_date": trigger_date,
            })

    passed = len(approaching) == 0
    market_label = "A股 " if market == "astock" else ""
    if not passed:
        parts = "; ".join(
            f"{a['id']} ({a['name']}, 触发日{a['trigger_date']})"
            for a in approaching
        )
        detail = f"{market_label}待执行行动即将触发: {parts}"
        label = f"{market_label}即将触发: {len(approaching)} 项"
    else:
        detail = f"{market_label}无行动在2个交易日内触发"
        label = f"{market_label}无即将触发行动"

    return CheckItem(
        check_id="CN_PENDING_APPROACHING",
        category="SOFT_WARNING",
        passed=passed,
        label=label,
        detail=detail,
        rule_ref="L17 §4",
    )


def warn_cn_pending_urgent_today(state: dict, pending_data: dict, market: Optional[str]) -> CheckItem:
    """A股 urgent/high-priority pending actions triggered or created today."""
    today = date.today().isoformat()
    pending_items = pending_data.get("pending", [])
    urgent_today = []

    for action in pending_items:
        if action.get("status") == "completed":
            continue
        if not pending_matches_market(action, market):
            continue
        priority = action.get("priority", "medium")
        status = action.get("status", "pending")
        created_at = action.get("created_at", "")
        trigger_date = action.get("trigger_date", "")

        is_urgent_priority = (status == "urgent" or priority == "high")
        if not is_urgent_priority:
            continue

        created_today = created_at[:10] == today
        triggers_today = trigger_date == today

        if created_today or triggers_today:
            urgent_today.append({
                "id": action.get("id", "?"),
                "name": action.get("name", ""),
                "type": action.get("type", ""),
            })

    passed = len(urgent_today) == 0
    market_label = "A股 " if market == "astock" else ""
    if not passed:
        parts = "; ".join(
            f"{a['id']} ({a['name']}, {a['type']})"
            for a in urgent_today
        )
        detail = f"{market_label}今日紧急行动: {parts}"
        label = f"{market_label}今日紧急: {len(urgent_today)} 项"
    else:
        detail = f"{market_label}今日无紧急/高优先级行动触发"
        label = f"{market_label}今日无紧急行动"

    return CheckItem(
        check_id="CN_PENDING_URGENT_TODAY",
        category="SOFT_WARNING",
        passed=passed,
        label=label,
        detail=detail,
        rule_ref="L17 §4 — urgent actions require same-session handling",
    )


# ─────────────────────────────────────────────────────────────────────────────
# US-specific HARD BLOCK checkers
# ─────────────────────────────────────────────────────────────────────────────

def check_us_position_count(state: dict) -> CheckItem:
    """L16: US long positions count ≤ 9 (does not count short_positions)."""
    positions = state["accounts"]["us"].get("positions", [])
    long_positions = [p for p in positions if p.get("instrument_type") != "call_option"]
    count = len(long_positions)
    passed = count <= US_MAX_POSITIONS
    if not passed:
        detail = f"US positions: {count}/{US_MAX_POSITIONS} (OVER by {count - US_MAX_POSITIONS})"
    else:
        detail = f"US positions: {count}/{US_MAX_POSITIONS}"
    return CheckItem(
        check_id="L16_POSITION_COUNT",
        category="HARD_BLOCK",
        passed=passed,
        label=f"US positions: {count}/{US_MAX_POSITIONS}",
        detail=detail,
        rule_ref="L16 — CLAUDE.md 铁律",
    )


def check_us_minimum_position_size(state: dict) -> CheckItem:
    """L16: Every US position ≥ $7,500 (散弹枪禁令)."""
    positions = state["accounts"]["us"].get("positions", [])
    long_positions = [p for p in positions if p.get("instrument_type") != "call_option"]
    violations = []
    for pos in long_positions:
        value = calc_position_value(pos)
        if value < US_MIN_POSITION_USD:
            violations.append((pos["ticker"], value))

    passed = len(violations) == 0
    if not passed:
        parts = ", ".join(f"{t} ${v:,.0f}" for t, v in violations)
        detail = f"Below minimum: {parts}"
        label = f"Below $7,500: {', '.join(t for t, _ in violations)}"
    else:
        detail = f"All {len(long_positions)} positions ≥ $7,500"
        label = f"All {len(long_positions)} positions ≥ $7,500"
    return CheckItem(
        check_id="L16_MIN_POSITION_SIZE",
        category="HARD_BLOCK",
        passed=passed,
        label=label,
        detail=detail,
        rule_ref="L16 — 散弹枪禁令",
    )


def check_us_short_exposure(state: dict) -> CheckItem:
    """L18: Short exposure ≥ 5% of US portfolio."""
    us_account = state["accounts"]["us"]
    short_value, short_pct = calc_us_short_exposure(us_account)
    passed = short_pct >= US_MIN_SHORT_PCT

    if short_pct == 0.0:
        detail = "Short exposure: 0% — CRITICAL (system failure, L18 violated 5+ days)"
        label = "Short exposure: 0% CRITICAL"
    elif short_pct < US_MIN_SHORT_PCT:
        detail = f"Short exposure: {short_pct:.1%} (target ≥5%, current below hard floor)"
        label = f"Short exposure: {short_pct:.1%} below floor"
    else:
        detail = f"Short exposure: {short_pct:.1%} (≥5% floor met)"
        label = f"Short exposure: {short_pct:.1%}"

    return CheckItem(
        check_id="L18_SHORT_EXPOSURE_FLOOR",
        category="HARD_BLOCK",
        passed=passed,
        label=label,
        detail=detail,
        rule_ref="L18 — 空头强制配额",
    )


def check_us_cash_reserve(state: dict) -> CheckItem:
    """US cash ≥ 15% of US total_assets."""
    us = state["accounts"]["us"]
    cash = float(us.get("cash", 0))
    total = float(us.get("total_assets", 0))
    pct = cash / total if total > 0 else 1.0
    passed = pct >= US_MIN_CASH_PCT
    detail = f"US cash: {pct:.1%} (minimum {US_MIN_CASH_PCT:.0%})"
    return CheckItem(
        check_id="US_CASH_RESERVE",
        category="HARD_BLOCK",
        passed=passed,
        label=f"US cash: {pct:.1%}",
        detail=detail,
        rule_ref="strategy.md §3.2 — 现金≥15%",
    )


def check_us_bear_case_documented(state: dict) -> CheckItem:
    """All US positions must have a documented bear_case field."""
    violations = []
    for pos in state["accounts"]["us"].get("positions", []):
        bear_case = pos.get("bear_case", "")
        if not bear_case or not str(bear_case).strip():
            violations.append(pos.get("ticker", "?"))

    total = len(state["accounts"]["us"].get("positions", []))
    passed = len(violations) == 0
    if not passed:
        detail = f"No bear case: {', '.join(violations)}"
        label_str = f"US missing bear case: {len(violations)} positions"
    else:
        detail = f"All {total} US positions have documented bear case"
        label_str = f"All {total} US positions have bear case"

    return CheckItem(
        check_id="US_BEAR_CASE_DOCUMENTED",
        category="HARD_BLOCK",
        passed=passed,
        label=label_str,
        detail=detail,
        rule_ref="strategy.md §3.1 — bear case 4-tier, 进场检查表",
    )


def check_us_pending_overdue(state: dict, pending_data: dict, market: Optional[str]) -> CheckItem:
    """Block if any US P0/P1 pending action is overdue by > 2 trading days."""
    pending_items = pending_data.get("pending", [])
    today = date.today().isoformat()
    P0_TYPES = {"regime_adjustment", "short"}
    overdue = []

    for action in pending_items:
        if action.get("status") == "completed":
            continue
        if not pending_matches_market(action, market):
            continue

        priority = action.get("priority", "medium")
        status = action.get("status", "pending")
        action_type = action.get("type", "")
        created_at = action.get("created_at", "")
        if not created_at:
            continue

        is_p0 = (status == "urgent") or (priority == "high" and action_type in P0_TYPES)
        is_p1 = (priority == "high") and not is_p0

        if not (is_p0 or is_p1):
            continue

        days_old = trading_days_between(created_at[:10], today)
        if days_old > P0_P1_OVERDUE_DAYS:
            overdue.append({
                "id": action.get("id", "?"),
                "name": action.get("name", ""),
                "type": action_type,
                "days_overdue": days_old - P0_P1_OVERDUE_DAYS,
            })

    passed = len(overdue) == 0
    market_label = "US " if market == "us" else ""
    if not passed:
        parts = "; ".join(
            f"{o['id']} ({o['name']}, {o['type']}, {o['days_overdue']}d overdue)"
            for o in overdue
        )
        detail = f"{market_label}Overdue P0/P1: {parts}"
        label = f"{market_label}Overdue P0/P1 actions: {len(overdue)}"
    else:
        detail = f"{market_label}No P0/P1 actions overdue by > 2 trading days"
        label = f"{market_label}No P0/P1 overdue"

    return CheckItem(
        check_id="US_PENDING_OVERDUE",
        category="HARD_BLOCK",
        passed=passed,
        label=label,
        detail=detail,
        rule_ref="L17 §4 — 每session第4步检查pending",
    )


# ─────────────────────────────────────────────────────────────────────────────
# US-specific SOFT WARNING checkers
# ─────────────────────────────────────────────────────────────────────────────

def warn_us_short_below_target(state: dict) -> CheckItem:
    """L18 soft: short exposure in range [5%, 10%) — below target band."""
    us_account = state["accounts"]["us"]
    _, short_pct = calc_us_short_exposure(us_account)
    # Only fires if short_pct >= 5% (below 5% is already a HARD BLOCK)
    warn = US_MIN_SHORT_PCT <= short_pct < US_SHORT_TARGET_LOW
    passed = not warn
    detail = (
        f"Short exposure {short_pct:.1%} below target band 10–15%"
        if warn
        else f"Short exposure {short_pct:.1%} within or above target band 10–15%"
    )
    return CheckItem(
        check_id="L18_SHORT_BELOW_TARGET",
        category="SOFT_WARNING",
        passed=passed,
        label=f"Short below target: {short_pct:.1%}",
        detail=detail,
        rule_ref="L18 — 空头目标10-15%",
    )


def warn_us_position_concentration(state: dict) -> CheckItem:
    """Any single US position > 15% of US portfolio."""
    us = state["accounts"]["us"]
    total = float(us.get("total_assets", 0))
    positions = us.get("positions", [])
    violations = []

    for pos in positions:
        if pos.get("instrument_type") == "call_option":
            continue
        pct = pos.get("portfolio_pct")
        if pct is None and total > 0:
            pct = calc_position_value(pos) / total
        if pct is None:
            continue
        pct = float(pct)
        conviction = pos.get("conviction_level", "B")  # default B per spec

        # Warn if: (pct > 15% AND not A-grade) OR pct > 25%
        if (pct > US_MAX_SINGLE_PCT and conviction != "A") or pct > 0.25:
            limit = 0.25 if conviction == "A" else US_MAX_SINGLE_PCT
            violations.append((pos["ticker"], pct, limit))

    passed = len(violations) == 0
    if not passed:
        parts = ", ".join(f"{t} {p:.1%} (>{lim:.0%} limit)" for t, p, lim in violations)
        detail = f"Concentration: {parts}"
        label = f"US over-concentrated: {', '.join(t for t, _, _ in violations)}"
    else:
        detail = "No single US position above concentration threshold"
        label = "US concentration OK"

    return CheckItem(
        check_id="US_POSITION_CONCENTRATION",
        category="SOFT_WARNING",
        passed=passed,
        label=label,
        detail=detail,
        rule_ref="strategy.md §3.1 — A级≤25%",
    )


def warn_us_c_grade_stale(state: dict) -> CheckItem:
    """C-grade or scout_position US positions held > 14 trading days."""
    stale = []
    for pos in state["accounts"]["us"].get("positions", []):
        conviction = pos.get("conviction_level", "")
        pos_type = pos.get("type", "")
        is_c = (
            conviction == "C"
            or pos_type == "scout_position"
            or pos_type == "catalyst_position"
        )
        if not is_c:
            continue
        entry = pos.get("entry_date", "")
        if not entry:
            continue
        days_held = count_trading_days_held(entry[:10])
        if days_held > C_GRADE_MAX_DAYS:
            stale.append((pos.get("ticker", "?"), days_held))

    passed = len(stale) == 0
    if not passed:
        parts = ", ".join(f"{t} ({d}d)" for t, d in stale)
        detail = f"US C-grade stale (>{C_GRADE_MAX_DAYS}d): {parts}"
        label = f"US C-grade stale: {', '.join(t for t, _ in stale)}"
    else:
        detail = f"No US C-grade positions older than {C_GRADE_MAX_DAYS} trading days"
        label = f"No US C-grade stale (>{C_GRADE_MAX_DAYS}d)"

    return CheckItem(
        check_id="US_C_GRADE_STALE",
        category="SOFT_WARNING",
        passed=passed,
        label=label,
        detail=detail,
        rule_ref="strategy.md §3.1 — C级观察仓，快速止损机制",
    )


def warn_regime_stale(state: dict) -> CheckItem:
    """Warn if last regime check > 3 days old."""
    days = days_since_last_regime_check(LAST_REGIME_PATH)
    if days is None:
        passed = False
        detail = "Last regime check: unknown (never recorded in daily-reviews)"
        label = "Regime check: unknown"
    elif days > REGIME_STALE_DAYS:
        passed = False
        detail = f"Last regime check: {days}d ago (L17 §3 requires ≤{REGIME_STALE_DAYS} days)"
        label = f"Regime stale: {days}d ago"
    else:
        passed = True
        detail = f"Last regime check: {days}d ago (within {REGIME_STALE_DAYS}-day limit)"
        label = f"Regime check: {days}d ago"

    return CheckItem(
        check_id="REGIME_STALE",
        category="SOFT_WARNING",
        passed=passed,
        label=label,
        detail=detail,
        rule_ref="L17 §3 — Regime Detection",
    )


def warn_us_pending_approaching(state: dict, pending_data: dict, market: Optional[str]) -> CheckItem:
    """US pending actions with trigger_date within 2 trading days."""
    today = date.today().isoformat()
    pending_items = pending_data.get("pending", [])
    approaching = []

    for action in pending_items:
        if action.get("status") == "completed":
            continue
        if not pending_matches_market(action, market):
            continue
        trigger_date = action.get("trigger_date", "")
        if not trigger_date:
            continue
        days_to_trigger = trading_days_between(today, trigger_date)
        if 0 < days_to_trigger <= 2:
            approaching.append({
                "id": action.get("id", "?"),
                "name": action.get("name", ""),
                "trigger_date": trigger_date,
            })

    passed = len(approaching) == 0
    market_label = "US " if market == "us" else ""
    if not passed:
        parts = "; ".join(
            f"{a['id']} ({a['name']}, triggers {a['trigger_date']})"
            for a in approaching
        )
        detail = f"{market_label}Pending approaching: {parts}"
        label = f"{market_label}Pending approaching deadline: {len(approaching)}"
    else:
        detail = f"{market_label}No pending actions triggering within 2 trading days"
        label = f"{market_label}No pending approaching"

    return CheckItem(
        check_id="US_PENDING_APPROACHING",
        category="SOFT_WARNING",
        passed=passed,
        label=label,
        detail=detail,
        rule_ref="L17 §4",
    )


def warn_us_pending_urgent_today(state: dict, pending_data: dict, market: Optional[str]) -> CheckItem:
    """US urgent/high-priority pending actions triggered or created today."""
    today = date.today().isoformat()
    pending_items = pending_data.get("pending", [])
    urgent_today = []

    for action in pending_items:
        if action.get("status") == "completed":
            continue
        if not pending_matches_market(action, market):
            continue
        priority = action.get("priority", "medium")
        status = action.get("status", "pending")
        created_at = action.get("created_at", "")
        trigger_date = action.get("trigger_date", "")

        is_urgent_priority = (status == "urgent" or priority == "high")
        if not is_urgent_priority:
            continue

        created_today = created_at[:10] == today
        triggers_today = trigger_date == today

        if created_today or triggers_today:
            urgent_today.append({
                "id": action.get("id", "?"),
                "name": action.get("name", ""),
                "type": action.get("type", ""),
            })

    passed = len(urgent_today) == 0
    market_label = "US " if market == "us" else ""
    if not passed:
        parts = "; ".join(
            f"{a['id']} ({a['name']}, {a['type']})"
            for a in urgent_today
        )
        detail = f"{market_label}Urgent today: {parts}"
        label = f"{market_label}Urgent actions today: {len(urgent_today)}"
    else:
        detail = f"{market_label}No urgent/high-priority actions triggered today"
        label = f"{market_label}No urgent actions today"

    return CheckItem(
        check_id="US_PENDING_URGENT_TODAY",
        category="SOFT_WARNING",
        passed=passed,
        label=label,
        detail=detail,
        rule_ref="L17 §4 — urgent actions require same-session handling",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Market-specific check bundles
# ─────────────────────────────────────────────────────────────────────────────

def check_astock(state: dict, pending: dict) -> list[CheckItem]:
    """
    All checks for A股 only:
      HARD BLOCKS: position count ≤ 8, cash ≥ 20%, concentration (soft 12%), bear case, pending overdue
      SOFT WARNINGS: single position concentration, sector concentration, C-grade age, pending approaching/urgent
    A股 does NOT check: US position count, US min size, short exposure, regime detection, US concentration
    """
    return [
        # HARD BLOCKS
        check_cn_position_count(state),
        check_cn_cash_reserve(state),
        check_cn_bear_case_documented(state),
        check_cn_pending_overdue(state, pending, "astock"),
        # SOFT WARNINGS
        warn_cn_position_concentration(state),
        warn_cn_sector_concentration(state),
        warn_cn_c_grade_stale(state),
        warn_cn_pending_approaching(state, pending, "astock"),
        warn_cn_pending_urgent_today(state, pending, "astock"),
    ]


def check_us(state: dict, pending: dict) -> list[CheckItem]:
    """
    All checks for US only:
      HARD BLOCKS: position count ≤ 9 (L16), min size $7,500 (L16), short exposure ≥ 5% (L18),
                   cash ≥ 15%, bear case, pending overdue
      SOFT WARNINGS: short below 10% target, single position concentration > 15%, C-grade age,
                     regime check freshness, pending approaching/urgent
    US does NOT check: A股 position count, A股 cash, A股 concentration, A股-specific anything
    """
    return [
        # HARD BLOCKS
        check_us_position_count(state),
        check_us_minimum_position_size(state),
        check_us_short_exposure(state),
        check_us_cash_reserve(state),
        check_us_bear_case_documented(state),
        check_us_pending_overdue(state, pending, "us"),
        # SOFT WARNINGS
        warn_us_short_below_target(state),
        warn_us_position_concentration(state),
        warn_us_c_grade_stale(state),
        warn_regime_stale(state),
        warn_us_pending_approaching(state, pending, "us"),
        warn_us_pending_urgent_today(state, pending, "us"),
    ]


def check_both(state: dict, pending: dict) -> list[CheckItem]:
    """
    All checks for both markets combined (default mode, backward compatible).
    Pending actions without a market field are shown in both passes
    but deduplicated here by running each market's full set and merging.
    """
    # For both-mode we run the original combined pending check (no market filter = all)
    return [
        # A股 HARD BLOCKS
        check_cn_position_count(state),
        check_cn_cash_reserve(state),
        check_cn_bear_case_documented(state),
        check_cn_pending_overdue(state, pending, None),
        # US HARD BLOCKS
        check_us_position_count(state),
        check_us_minimum_position_size(state),
        check_us_short_exposure(state),
        check_us_cash_reserve(state),
        check_us_bear_case_documented(state),
        check_us_pending_overdue(state, pending, None),
        # A股 SOFT WARNINGS
        warn_cn_position_concentration(state),
        warn_cn_sector_concentration(state),
        warn_cn_c_grade_stale(state),
        warn_cn_pending_approaching(state, pending, None),
        warn_cn_pending_urgent_today(state, pending, None),
        # US SOFT WARNINGS
        warn_us_short_below_target(state),
        warn_us_position_concentration(state),
        warn_us_c_grade_stale(state),
        warn_regime_stale(state),
        warn_us_pending_approaching(state, pending, None),
        warn_us_pending_urgent_today(state, pending, None),
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Report assembly
# ─────────────────────────────────────────────────────────────────────────────

def assemble_report(all_checks: list[CheckItem], market: str) -> CheckReport:
    """Partition checks into hard_blocks, soft_warnings, passed_checks."""
    report = CheckReport(date=date.today().isoformat(), market=market)
    for item in all_checks:
        if item.passed:
            report.passed_checks.append(item)
        elif item.category == "HARD_BLOCK":
            report.hard_blocks.append(item)
        else:
            report.soft_warnings.append(item)

    report.block_count = len(report.hard_blocks)
    report.warning_count = len(report.soft_warnings)
    report.pass_count = len(report.passed_checks)
    report.verdict = "BLOCKED" if report.block_count > 0 else "CLEARED"
    return report


# ─────────────────────────────────────────────────────────────────────────────
# Output formatters
# ─────────────────────────────────────────────────────────────────────────────

MARKET_LABELS = {
    "astock": "A股",
    "us": "美股",
    "both": "A股 + 美股",
}

_FIX_ORDER = [
    ("L18_SHORT_EXPOSURE_FLOOR",
     "[L18] Execute short scan NOW (W3 window 22:00 BJT) — build ≥1 short position ≥$7,500"),
    ("L16_POSITION_COUNT",
     "[L16] Reduce US longs to ≤9: stop-loss or thesis-fail candidates first"),
    ("L16_MIN_POSITION_SIZE",
     "[L16] Bring sub-$7,500 positions up to minimum or exit"),
    ("CN_POSITION_COUNT",
     "[A股] Reduce A股 holdings to ≤8: exit weakest thesis or C-grade first"),
    ("CN_PENDING_OVERDUE",
     "[A股 PENDING] Execute overdue A股 P0/P1 actions immediately"),
    ("US_PENDING_OVERDUE",
     "[US PENDING] Execute overdue US P0/P1 actions immediately"),
    ("CN_BEAR_CASE_DOCUMENTED",
     "[A股 BEAR_CASE] Document bear case for all A股 positions before trading"),
    ("US_BEAR_CASE_DOCUMENTED",
     "[US BEAR_CASE] Document bear case for all US positions before trading"),
    ("US_CASH_RESERVE",
     "[CASH_US] Raise US cash to ≥15% before any new position"),
    ("CN_CASH_RESERVE",
     "[CASH_CN] Raise A股 cash to ≥20% before adding positions"),
]


def _fix_order_remediation(report: CheckReport) -> list[str]:
    """Generate fix-order list for BLOCKED verdict."""
    lines = []
    block_ids = {b.check_id for b in report.hard_blocks}
    step = 1
    for check_id, remedy in _FIX_ORDER:
        if check_id in block_ids:
            lines.append(f"  {step}. {remedy}")
            step += 1
    return lines


def _market_header(market: str, today: str) -> str:
    label = MARKET_LABELS.get(market, market)
    return f"═══ PRE-SESSION CHECK — {label} ({today}) ═══"


def print_report(report: CheckReport) -> None:
    """Print formatted report to stdout."""
    print(_market_header(report.market, report.date))
    print()

    # HARD BLOCKS
    print(f"HARD BLOCKS: {report.block_count} {'❌' if report.block_count else '✓'}")
    if report.hard_blocks:
        for item in report.hard_blocks:
            ref = item.rule_ref.split(" —")[0].split("—")[0].strip()
            print(f"  ❌ [{ref}] {item.detail}")
    else:
        print("  (none)")
    print()

    # SOFT WARNINGS
    print(f"SOFT WARNINGS: {report.warning_count} {'⚠️' if report.warning_count else '✓'}")
    if report.soft_warnings:
        for item in report.soft_warnings:
            ref = item.rule_ref.split(" —")[0].split("—")[0].strip()
            print(f"  ⚠️  [{ref}] {item.detail}")
    else:
        print("  (none)")
    print()

    # PASSED
    print(f"PASSED: {report.pass_count} ✓")
    if report.passed_checks:
        for item in report.passed_checks:
            ref = item.rule_ref.split(" —")[0].split("—")[0].strip()
            print(f"  ✓  [{ref}] {item.detail}")
    print()

    # VERDICT
    if report.verdict == "BLOCKED":
        verdict_line = (
            f"═══ VERDICT: BLOCKED — fix {report.block_count} "
            f"hard block{'s' if report.block_count != 1 else ''} before trading ═══"
        )
        print(verdict_line)
        fix_lines = _fix_order_remediation(report)
        if fix_lines:
            print("Fix order:")
            for line in fix_lines:
                print(line)
    else:
        print("═══ VERDICT: CLEARED — proceed to trading ═══")


def print_json_report(report: CheckReport) -> None:
    """Print machine-readable JSON to stdout."""
    def item_to_dict(item: CheckItem) -> dict:
        return {
            "check_id": item.check_id,
            "label": item.label,
            "detail": item.detail,
            "rule_ref": item.rule_ref,
        }

    output = {
        "date": report.date,
        "market": report.market,
        "verdict": report.verdict,
        "block_count": report.block_count,
        "warning_count": report.warning_count,
        "pass_count": report.pass_count,
        "hard_blocks": [item_to_dict(i) for i in report.hard_blocks],
        "soft_warnings": [item_to_dict(i) for i in report.soft_warnings],
        "passed": [item_to_dict(i) for i in report.passed_checks],
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


def write_result_json(report: CheckReport) -> None:
    """Write result JSON to scripts/session_check_result.json."""
    def item_to_dict(item: CheckItem) -> dict:
        return {
            "check_id": item.check_id,
            "category": item.category,
            "passed": item.passed,
            "label": item.label,
            "detail": item.detail,
            "rule_ref": item.rule_ref,
        }

    output = {
        "date": report.date,
        "market": report.market,
        "verdict": report.verdict,
        "block_count": report.block_count,
        "warning_count": report.warning_count,
        "pass_count": report.pass_count,
        "hard_blocks": [item_to_dict(i) for i in report.hard_blocks],
        "soft_warnings": [item_to_dict(i) for i in report.soft_warnings],
        "passed": [item_to_dict(i) for i in report.passed_checks],
        "generated_at": datetime.now().isoformat(),
    }
    try:
        RESULT_PATH.write_text(
            json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as exc:
        print(f"WARNING: Could not write result JSON to {RESULT_PATH}: {exc}", file=sys.stderr)


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pre-session compliance gate for sim-portfolio.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Market modes:
  (no flag)        Check both A股 and 美股 (default, backward compatible)
  --market astock  Check A股 only: position count, cash ≥ 20%, concentration, bear case, C-grade age
  --market us      Check 美股 only: L16 count/size, L18 short exposure, cash, bear case, regime
""",
    )
    parser.add_argument(
        "--market", choices=["astock", "us"],
        default=None,
        help="Filter checks to a single market (default: both)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Machine-readable JSON output only",
    )
    parser.add_argument(
        "--skip-pending", action="store_true",
        help="Skip pending_actions check (use when pending_actions.json is absent)",
    )
    parser.add_argument(
        "--override", metavar="REASON",
        help="Force pass (escape hatch — requires explicit reason)",
    )
    args = parser.parse_args()

    # Handle override
    if args.override:
        override_msg = {
            "date": date.today().isoformat(),
            "market": args.market or "both",
            "verdict": "OVERRIDE",
            "override_reason": args.override,
            "warning": "COMPLIANCE GATE BYPASSED — this action is logged",
        }
        print(json.dumps(override_msg, ensure_ascii=False, indent=2))
        print(f"\nWARNING: Pre-session check overridden. Reason: {args.override}")
        sys.exit(0)

    # Load data
    state = load_portfolio(PORTFOLIO_PATH)
    pending = (
        load_pending(PENDING_PATH)
        if not args.skip_pending
        else {"pending": [], "completed": []}
    )

    # Dispatch to appropriate check bundle
    market = args.market or "both"
    if market == "astock":
        all_checks = check_astock(state, pending)
    elif market == "us":
        all_checks = check_us(state, pending)
    else:
        all_checks = check_both(state, pending)

    report = assemble_report(all_checks, market)

    # Output
    if args.json:
        print_json_report(report)
    else:
        print_report(report)

    # Always write result JSON
    write_result_json(report)

    # Exit code
    sys.exit(1 if report.verdict == "BLOCKED" else 0)


if __name__ == "__main__":
    main()

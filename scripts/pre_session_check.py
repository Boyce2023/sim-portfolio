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

v7.0 changes (2026-05-27):
  - CN_MAX_POSITIONS: 8 → 5
  - CN_MAX_SECTOR_PCT: 0.40 → 0.35, promoted to HARD_BLOCK
  - C-grade/scout positions removed from valid grades (strategy.md §2.2 废除C级)
  - Added CN grade floor check: all A股 positions must be ≥B-  (HARD_BLOCK)
  - Added CN daily trade limit: ≤2 new builds per day              (HARD_BLOCK)
  - Added CN weekly trade count: ≤8 total trades per week          (HARD_BLOCK)
  - Added CN round-trip check: ≤2 same-ticker round trips per week (SOFT_WARNING)
  - Added CN stop-loss proximity warning                           (SOFT_WARNING)
  - Added CN If-Then rules loaded check                            (SOFT_WARNING)
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
PORTFOLIO_PATH       = Path(__file__).parent.parent / "portfolio_state.json"
PENDING_PATH         = Path(__file__).parent.parent / "pending_actions.json"
LAST_REGIME_PATH     = Path(__file__).parent.parent / "daily-reviews"
RESULT_PATH          = Path(__file__).parent / "session_check_result.json"
CATALYST_ALERTS_PATH = Path(__file__).parent.parent / "catalyst_alerts.json"
CROSS_INTEL_PATH     = Path(__file__).parent.parent / "cross_intel_brief.json"
CHANGELOG_PATH       = Path(__file__).parent.parent / "system_changelog.json"
WATCHLIST_PATH       = (
    Path.home()
    / ".claude/projects/-Users-huaichuaibeimeng-claude-projects/memory/watchlist.md"
)

# ── HARD BLOCK thresholds ────────────────────────────────────────────────────
US_MAX_POSITIONS    = 9      # L16: total US longs ≤ 9
US_MIN_POSITION_USD = 7500   # L16: every US position ≥ $7,500
US_MIN_SHORT_PCT    = 0.05   # L18: short exposure ≥ 5% of US portfolio
US_MIN_CASH_PCT     = -1.0   # strategy.md: 无现金底线，margin use = correct behavior per aggressive stance
try:
    from core.config import (ASTOCK_MAX_POSITIONS as _A_MAX,
                             ASTOCK_MAX_POSITIONS_FLEX as _A_FLEX)
    CN_MAX_POSITIONS = _A_MAX
    CN_MAX_POSITIONS_FLEX = _A_FLEX
except ImportError:
    CN_MAX_POSITIONS = 8
    CN_MAX_POSITIONS_FLEX = 8
CN_MIN_CASH_PCT     = 0.00   # strategy_astock.md v9.1: 无现金底线（用止损管风险）
CN_HOLD_CASH_PCT    = 0.00   # strategy_astock.md v9.1: 无现金底线
CN_MAX_SECTOR_PCT   = 1.00   # strategy_astock.md v9.1: 板块不做硬约束
CN_MAX_DAILY_BUILDS = 2      # strategy.md v7.0 §3.2: ≤ 2 new builds per day
CN_MAX_WEEKLY_TRADES = 8     # strategy.md v7.0 §3.2: ≤ 8 total trades per week (incl. add/trim)
P0_P1_OVERDUE_DAYS  = 2      # pending actions P0/P1 older than 2 trading days = BLOCK

# ── SOFT WARNING thresholds ──────────────────────────────────────────────────
US_SHORT_TARGET_LOW  = 0.10  # L18 target band low end 10%
US_MAX_SINGLE_PCT    = 0.15  # warn if US position > 15% (A-grade allowed to 25%)
# SABCT grade → max concentration (strategy_astock.md v9.1 §2.2)
_SABCT_LIMITS: dict[str, float] = {
    "S": 0.50, "A+": 0.35, "A": 0.25, "A-": 0.20,
    "B+": 0.15, "B": 0.12, "B-": 0.10,
}
# Minimum acceptable grade for A股 positions (v9.1: S~B-, no C/T/scout)
CN_MIN_GRADE_FLOOR  = {"S", "A+", "A", "A-", "B+", "B", "B-"}
CN_MAX_SINGLE_PCT   = 0.50   # absolute hard cap (S级可达50%)
CN_ROUND_TRIP_MAX   = 2      # warn if same ticker has ≥ 2 round trips this week
CN_STOP_LOSS_WARN_PCT = 0.03 # warn if position is within 3% of stop-loss
C_GRADE_MAX_DAYS     = 14    # US only: C-grade or scout positions older than 14 days (soft warning)
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
    Returns absolute market_value of a position (works for both long and short).
    Fallback: current_price × abs(shares) if current_price present.
    Fallback: avg_cost × abs(shares).
    """
    mv = pos.get("market_value")
    if mv and float(mv) != 0:
        return abs(float(mv))
    shares = abs(int(pos.get("shares", 0)))
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
    """A股 positions: target ≤5, flex ≤7. >5 = soft warning, >7 = hard block."""
    positions = state["accounts"]["a_share"].get("positions", [])
    count = len(positions)
    hard_ok = count <= CN_MAX_POSITIONS_FLEX
    soft_ok = count <= CN_MAX_POSITIONS
    if not hard_ok:
        detail = f"A股持仓: {count}/{CN_MAX_POSITIONS_FLEX} (超弹性上限，需先清仓再建新仓)"
        category = "HARD_BLOCK"
        passed = False
    elif not soft_ok:
        detail = f"A股持仓: {count}/{CN_MAX_POSITIONS} (超目标但在弹性{CN_MAX_POSITIONS_FLEX}内，注意控制)"
        category = "SOFT_WARNING"
        passed = True
    else:
        detail = f"A股持仓: {count}/{CN_MAX_POSITIONS}"
        category = "SOFT_WARNING"
        passed = True
    return CheckItem(
        check_id="CN_POSITION_COUNT",
        category=category,
        passed=passed,
        label=f"A股持仓: {count}/{CN_MAX_POSITIONS}(弹性{CN_MAX_POSITIONS_FLEX})",
        detail=detail,
        rule_ref="strategy.md v8.1 §1 R2 — 目标≤5只，弹性至7只",
    )


def check_cn_cash_reserve(state: dict) -> CheckItem:
    """A-share cash check — no hard floor per strategy_astock.md v9.1 (use stop-loss to manage risk)."""
    cn = state["accounts"]["a_share"]
    cash = float(cn.get("cash", 0))
    total = float(cn.get("total_assets", 0))
    pct = cash / total if total > 0 else 1.0
    passed = pct >= CN_MIN_CASH_PCT
    detail = (
        f"A股现金: {pct:.1%} (无现金底线，用止损管风险)"
    )
    return CheckItem(
        check_id="CN_CASH_RESERVE",
        category="HARD_BLOCK",
        passed=passed,
        label=f"A股现金: {pct:.1%}",
        detail=detail,
        rule_ref="strategy_astock.md v9.1 — 无现金底线",
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
        category="SOFT_WARNING",
        passed=passed,
        label=label_str,
        detail=detail,
        rule_ref="strategy.md §3.1 — bear case reminder (V6.3: demoted from HARD_BLOCK)",
    )


def check_cn_pending_overdue(state: dict, pending_data: dict, market: Optional[str]) -> CheckItem:
    """Block if any A股 P0/P1 pending action is overdue by > 2 trading days."""
    pending_items = pending_data.get("pending", [])
    today = date.today().isoformat()
    P0_TYPES = {"regime_adjustment", "short"}
    overdue = []

    for action in pending_items:
        if action.get("status") in ("completed", "cancelled", "resolved"):
            continue
        if not pending_matches_market(action, market):
            continue

        priority = action.get("priority", "medium")
        status = action.get("status", "pending")
        action_type = action.get("type", "")
        created_at = action.get("created_at", "")
        trigger_date = action.get("trigger_date", "")
        if not created_at:
            continue

        if trigger_date and trigger_date > today:
            continue

        is_p0 = (status == "urgent") or (priority == "high" and action_type in P0_TYPES)
        is_p1 = (priority == "high") and not is_p0

        if not (is_p0 or is_p1):
            continue

        ref_date = trigger_date if trigger_date else created_at[:10]
        days_old = trading_days_between(ref_date, today)
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

def _get_sabct_limit(pos: dict) -> tuple[float, str]:
    """Return (max_pct, grade_label) for a position based on SABCT grade."""
    grade = (pos.get("conviction_level") or pos.get("confidence_grade") or "").strip().upper()
    if grade in _SABCT_LIMITS:
        return _SABCT_LIMITS[grade], grade
    ptype = (pos.get("type") or "").lower()
    if "core" in ptype:
        return 0.25, "core(→A)"
    if "catalyst" in ptype or "trading" in ptype:
        return 0.15, "catalyst(→B+)"
    return CN_MAX_SINGLE_PCT, "unknown"


def warn_cn_position_concentration(state: dict) -> CheckItem:
    """Any single A-share position exceeding its SABCT grade cap (soft warning)."""
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
        limit, grade = _get_sabct_limit(pos)
        if pct > limit:
            violations.append((pos.get("ticker", "?"), pos.get("name", ""), pct, limit, grade))

    passed = len(violations) == 0
    if not passed:
        parts = ", ".join(
            f"{n or t} {p:.1%} (>{lim:.0%} {g}级)"
            for t, n, p, lim, g in violations
        )
        detail = f"A股集中度: {parts}"
        label = f"A股过度集中: {', '.join(n or t for t, n, _, _, _ in violations)}"
    else:
        detail = "A股无单只持仓超过其SABCT等级上限"
        label = "A股集中度 OK"

    return CheckItem(
        check_id="CN_POSITION_CONCENTRATION",
        category="SOFT_WARNING",
        passed=passed,
        label=label,
        detail=detail,
        rule_ref="strategy.md v6.2 §3.3.1 — 按SABCT等级分级执行",
    )


def check_cn_sector_concentration(state: dict) -> CheckItem:
    """Any single sector > 35% of A-share portfolio (v7.0: was 40%, promoted to HARD_BLOCK)."""
    cn = state["accounts"]["a_share"]
    total = float(cn.get("total_assets", 0))
    positions = cn.get("positions", [])

    if total <= 0:
        return CheckItem(
            check_id="CN_SECTOR_CONCENTRATION",
            category="HARD_BLOCK",
            passed=True,
            label="A股板块集中度 OK",
            detail="无持仓数据",
            rule_ref="strategy.md v7.0 §3.2 — 单板块≤35%",
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
        detail = f"A股板块集中度超35%: {parts}（需trim至30%以下）"
        label = f"A股板块过度集中: {', '.join(s for s, _ in violations)}"
    else:
        detail = f"A股无单一板块超{CN_MAX_SECTOR_PCT:.0%}"
        label = "A股板块集中度 OK"

    return CheckItem(
        check_id="CN_SECTOR_CONCENTRATION",
        category="HARD_BLOCK",
        passed=passed,
        label=label,
        detail=detail,
        rule_ref="strategy.md v7.0 §3.2 — 单板块≤35%",
    )


def check_cn_grade_floor(state: dict) -> CheckItem:
    """v7.0: All A股 positions must be grade ≥ B- (C/T/scout grades abolished).

    strategy.md §2.2: '无C级/T级/scout仓——不够格就不买'
    Any existing position with conviction_level not in {A+, A, A-, B+, B, B-} is a HARD BLOCK.
    """
    violations = []
    for pos in state["accounts"]["a_share"].get("positions", []):
        grade = (pos.get("conviction_level") or "").strip().upper()
        pos_type = (pos.get("type") or "").lower()
        ticker = pos.get("ticker", "?")
        name = pos.get("name") or ticker

        is_invalid = (
            (grade and grade not in CN_MIN_GRADE_FLOOR)
            or pos_type in ("scout_position", "t_position")
            or grade in ("C", "C+", "T")
        )
        if is_invalid:
            violations.append(f"{name}({grade or pos_type})")

    passed = len(violations) == 0
    total = len(state["accounts"]["a_share"].get("positions", []))
    if not passed:
        detail = f"A股存在不合规等级持仓(需≥B-): {', '.join(violations)}。v7.0废除C级/T级/scout仓"
        label = f"A股等级不合规: {len(violations)} 只"
    else:
        detail = f"A股全部 {total} 只持仓等级合规(≥B-)"
        label = f"A股持仓等级 OK (全部≥B-)"

    return CheckItem(
        check_id="CN_GRADE_FLOOR",
        category="HARD_BLOCK",
        passed=passed,
        label=label,
        detail=detail,
        rule_ref="strategy.md v7.0 §2.2 — 无C级/T级/scout仓，最低B-",
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
# A股-specific v7.0 HARD BLOCK checkers (new)
# ─────────────────────────────────────────────────────────────────────────────

def _get_week_bounds() -> tuple[date, date]:
    """Return (Monday, Sunday) ISO dates for the current calendar week."""
    today = date.today()
    monday = today - timedelta(days=today.weekday())   # weekday(): Mon=0
    sunday = monday + timedelta(days=6)
    return monday, sunday


def _cn_trades_this_week(state: dict) -> list[dict]:
    """
    Extract A股 trades from trade_log for the current calendar week.
    Each entry has: date, action, ticker, name.
    """
    monday, sunday = _get_week_bounds()
    trade_log = state.get("trade_log", [])
    result = []
    for t in trade_log:
        if t.get("account") not in ("a_share", "cn"):
            continue
        trade_date_str = t.get("date", "")
        if not trade_date_str:
            continue
        try:
            trade_date = date.fromisoformat(trade_date_str[:10])
        except ValueError:
            continue
        if monday <= trade_date <= sunday:
            result.append({
                "date": trade_date_str[:10],
                "action": t.get("action", ""),
                "ticker": t.get("ticker", ""),
                "name": t.get("name", ""),
            })
    return result


def check_cn_daily_trade_limit(state: dict) -> CheckItem:
    """v7.0: ≤ 2 new builds per day for A股 (strategy.md §3.2 每日新建仓≤2只)."""
    today_str = date.today().isoformat()
    trade_log = state.get("trade_log", [])
    builds_today = [
        t for t in trade_log
        if t.get("account") in ("a_share", "cn")
        and t.get("date", "")[:10] == today_str
        and t.get("action") == "buy"
    ]
    count = len(builds_today)
    # Only block if trading session is about to start and already at/over limit
    passed = count < CN_MAX_DAILY_BUILDS
    if not passed:
        tickers = ", ".join(t.get("ticker", "?") for t in builds_today)
        detail = f"今日A股已新建 {count} 笔≥上限{CN_MAX_DAILY_BUILDS}笔: {tickers}。第{count + 1}笔需等明日"
        label = f"A股今日建仓: {count}/{CN_MAX_DAILY_BUILDS}"
    else:
        detail = f"A股今日已建仓: {count}/{CN_MAX_DAILY_BUILDS} (剩余 {CN_MAX_DAILY_BUILDS - count} 笔)"
        label = f"A股今日建仓: {count}/{CN_MAX_DAILY_BUILDS}"

    return CheckItem(
        check_id="CN_DAILY_TRADE_LIMIT",
        category="HARD_BLOCK",
        passed=passed,
        label=label,
        detail=detail,
        rule_ref="strategy.md v7.0 §3.2 — 每日新建仓≤2只",
    )


def check_cn_weekly_trade_count(state: dict) -> CheckItem:
    """≤ 8 total A股 trades per week — soft guidance, not hard block."""
    weekly_trades = _cn_trades_this_week(state)
    count = len(weekly_trades)
    passed = count <= CN_MAX_WEEKLY_TRADES
    monday, sunday = _get_week_bounds()
    week_label = f"{monday.isoformat()}~{sunday.isoformat()}"

    if not passed:
        detail = f"本周A股交易 {count}/{CN_MAX_WEEKLY_TRADES} 笔 ({week_label})，超参考上限，注意节奏"
        label = f"A股本周交易: {count}/{CN_MAX_WEEKLY_TRADES}"
    else:
        detail = f"A股本周交易: {count}/{CN_MAX_WEEKLY_TRADES} ({week_label}，剩余 {CN_MAX_WEEKLY_TRADES - count} 笔)"
        label = f"A股本周交易: {count}/{CN_MAX_WEEKLY_TRADES}"

    return CheckItem(
        check_id="CN_WEEKLY_TRADE_COUNT",
        category="SOFT_WARNING",
        passed=True,
        label=label,
        detail=detail,
        rule_ref="strategy.md §3.2 — 每周交易参考≤8笔（弹性指标）",
    )


# ─────────────────────────────────────────────────────────────────────────────
# A股-specific v7.0 SOFT WARNING checkers (new)
# ─────────────────────────────────────────────────────────────────────────────

def warn_cn_round_trip(state: dict) -> CheckItem:
    """v7.0: Warn if any ticker has ≥ 2 round trips this week.

    Round trip = same ticker buy→sell (or sell→buy) within 3 trading days AND |pnl| < 3%.
    Simplified version: detect any ticker appearing ≥ 2 times in weekly trades on both
    sides (buy + sell), as a proxy for round-trip churn (strategy.md §4.4).
    """
    weekly_trades = _cn_trades_this_week(state)
    from collections import defaultdict
    ticker_buys: dict[str, list[str]] = defaultdict(list)
    ticker_sells: dict[str, list[str]] = defaultdict(list)

    for t in weekly_trades:
        ticker = t["ticker"]
        if t["action"] in ("buy",):
            ticker_buys[ticker].append(t["date"])
        elif t["action"] in ("sell",):
            ticker_sells[ticker].append(t["date"])

    round_trips = []
    for ticker in set(ticker_buys) | set(ticker_sells):
        buys = sorted(ticker_buys.get(ticker, []))
        sells = sorted(ticker_sells.get(ticker, []))
        # Count min(buys, sells) as round-trip count for this ticker this week
        rt_count = min(len(buys), len(sells))
        if rt_count >= CN_ROUND_TRIP_MAX:
            name = next(
                (t["name"] for t in weekly_trades if t["ticker"] == ticker),
                ticker,
            )
            round_trips.append(f"{name}({ticker}): {rt_count}次往返")

    passed = len(round_trips) == 0
    if not passed:
        detail = f"A股本周同标的往返≥{CN_ROUND_TRIP_MAX}次: {', '.join(round_trips)}。§4.4: 第2次→下周禁止新建仓"
        label = f"A股Round Trip警告: {len(round_trips)} 只"
    else:
        detail = "A股本周无同标的往返≥2次情况"
        label = "A股Round Trip: 无警告"

    return CheckItem(
        check_id="CN_ROUND_TRIP",
        category="SOFT_WARNING",
        passed=passed,
        label=label,
        detail=detail,
        rule_ref="strategy.md v7.0 §4.4 — Round Trip惩罚",
    )


def warn_cn_stop_loss_proximity(state: dict) -> CheckItem:
    """v7.0: Warn if any A股 position is within 3% of its stop-loss price."""
    at_risk = []
    for pos in state["accounts"]["a_share"].get("positions", []):
        current = pos.get("current_price")
        stop = pos.get("stop_loss")
        if current is None or stop is None:
            continue
        current_f = float(current)
        stop_f = float(stop)
        if current_f <= 0 or stop_f <= 0:
            continue
        distance_pct = (current_f - stop_f) / current_f  # positive = above stop
        if distance_pct <= CN_STOP_LOSS_WARN_PCT:
            name = pos.get("name") or pos.get("ticker", "?")
            at_risk.append(
                f"{name} 现价¥{current_f:.2f} 止损¥{stop_f:.2f} (距离{distance_pct:.1%})"
            )

    passed = len(at_risk) == 0
    if not passed:
        detail = f"A股止损临近(<{CN_STOP_LOSS_WARN_PCT:.0%}): {'; '.join(at_risk)}。R4: 触及当日执行"
        label = f"A股止损临近: {len(at_risk)} 只"
    else:
        detail = f"A股全部持仓距止损>{CN_STOP_LOSS_WARN_PCT:.0%}"
        label = "A股止损距离 OK"

    return CheckItem(
        check_id="CN_STOP_LOSS_PROXIMITY",
        category="SOFT_WARNING",
        passed=passed,
        label=label,
        detail=detail,
        rule_ref="strategy.md v7.0 §3.1+R4 — 止损不可协商",
    )


def warn_cn_if_then_loaded(state: dict) -> CheckItem:
    """v7.0: Warn if no If-Then rules are present in portfolio_state.json.

    R5: If-Then预承诺必须在非交易时间写入。盘前检查时确认规则已加载。
    Checks: state['accounts']['a_share'].get('if_then_rules') or state.get('if_then_rules')
    Also accepts presence of strategy §8 entries embedded as 'pending_orders' with if_then type.
    """
    # Check multiple possible locations for If-Then rules
    cn_rules = state.get("accounts", {}).get("a_share", {}).get("if_then_rules", [])
    top_rules = state.get("if_then_rules", [])
    # Also check pending_orders for if_then type entries
    pending_orders = state.get("pending_orders", [])
    if_then_orders = [o for o in pending_orders if "if" in str(o).lower() or "then" in str(o).lower()]

    has_rules = bool(cn_rules or top_rules or if_then_orders)

    # Provide count detail
    total = len(cn_rules) + len(top_rules) + len(if_then_orders)
    passed = has_rules  # warning only — rules may legitimately be in strategy.md §8 text form

    if not passed:
        detail = (
            "未找到If-Then预承诺规则(portfolio_state.json中无if_then_rules/pending_orders条目)。"
            "R5: 盘前在非交易时间写入预承诺，盘中只执行不修改。确认strategy.md §8已设置"
        )
        label = "If-Then规则: 未检测到"
    else:
        detail = f"检测到 {total} 条If-Then预承诺规则。R5: 盘中不可修改，想改→收盘后改→次日生效"
        label = f"If-Then规则: {total} 条已加载"

    return CheckItem(
        check_id="CN_IF_THEN_LOADED",
        category="SOFT_WARNING",
        passed=passed,
        label=label,
        detail=detail,
        rule_ref="strategy.md v7.0 §1 R5 / §8 — If-Then盘中不可修改",
    )


# ─────────────────────────────────────────────────────────────────────────────
# US-specific HARD BLOCK checkers
# ─────────────────────────────────────────────────────────────────────────────

def check_us_position_count(state: dict) -> CheckItem:
    """L16: US long positions count ≤ 9 (ETFs exempt, does not count short_positions)."""
    positions = state["accounts"]["us"].get("positions", [])
    long_positions = [p for p in positions if p.get("instrument_type") != "call_option"]
    non_etf = [p for p in long_positions if p.get("ticker", "") not in _ETF_TICKERS]
    count = len(non_etf)
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
    """L18: Short exposure check (soft warning — shorts are optional per strategy §6)."""
    us_account = state["accounts"]["us"]
    short_value, short_pct = calc_us_short_exposure(us_account)

    if short_pct == 0.0:
        detail = "Short exposure: 0% — 无空头仓位（strategy §6: 做空是可选的alpha来源）"
        label = "Short exposure: 0%"
    elif short_pct < US_MIN_SHORT_PCT:
        detail = f"Short exposure: {short_pct:.1%} (目标≥5%，当前偏低)"
        label = f"Short exposure: {short_pct:.1%}"
    else:
        detail = f"Short exposure: {short_pct:.1%} (≥5% met)"
        label = f"Short exposure: {short_pct:.1%}"

    return CheckItem(
        check_id="L18_SHORT_EXPOSURE",
        category="SOFT_WARNING",
        passed=True,
        label=label,
        detail=detail,
        rule_ref="strategy §6 — 做空可选",
    )


def check_us_cash_reserve(state: dict) -> CheckItem:
    """US cash check — negative cash (margin use) is expected and correct per aggressive stance."""
    us = state["accounts"]["us"]
    cash = float(us.get("cash", 0))
    total = float(us.get("total_assets", 0))
    pct = cash / total if total > 0 else 1.0
    # Always passes — margin/negative cash is correct behavior; cash drag is flagged by check_us_cash_drag()
    passed = True
    if cash < 0:
        detail = f"US cash: {pct:.1%} (margin in use — correct aggressive behavior)"
    else:
        detail = f"US cash: {pct:.1%} (positive cash — consider deploying to ETF or conviction positions)"
    return CheckItem(
        check_id="US_CASH_RESERVE",
        category="SOFT_WARNING",
        passed=passed,
        label=f"US cash: {pct:.1%}",
        detail=detail,
        rule_ref="strategy.md — 无现金底线，margin use正常",
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
        category="SOFT_WARNING",
        passed=passed,
        label=label_str,
        detail=detail,
        rule_ref="strategy.md §3.1 — bear case reminder (V6.3: demoted from HARD_BLOCK)",
    )


def check_us_pending_overdue(state: dict, pending_data: dict, market: Optional[str]) -> CheckItem:
    """Block if any US P0/P1 pending action is overdue by > 2 trading days."""
    pending_items = pending_data.get("pending", [])
    today = date.today().isoformat()
    P0_TYPES = {"regime_adjustment", "short"}
    overdue = []

    for action in pending_items:
        if action.get("status") in ("completed", "cancelled", "resolved"):
            continue
        if not pending_matches_market(action, market):
            continue

        priority = action.get("priority", "medium")
        status = action.get("status", "pending")
        action_type = action.get("type", "")
        created_at = action.get("created_at", "")
        trigger_date = action.get("trigger_date", "")
        if not created_at:
            continue

        if trigger_date and trigger_date > today:
            continue

        is_p0 = (status == "urgent") or (priority == "high" and action_type in P0_TYPES)
        is_p1 = (priority == "high") and not is_p0

        if not (is_p0 or is_p1):
            continue

        ref_date = trigger_date if trigger_date else created_at[:10]
        days_old = trading_days_between(ref_date, today)
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
    """Warn if last regime check > N days old. Reads nexus truth store first, falls back to daily-reviews."""
    regime_path = Path.home() / ".claude/nexus/truth/macro/regime.json"
    days = None
    regime_value = "unknown"
    if regime_path.exists():
        try:
            import json as _json
            rd = _json.loads(regime_path.read_text())
            updated = rd.get("metadata", {}).get("last_updated", "")
            if updated:
                from datetime import date as _date
                d = _date.fromisoformat(updated[:10])
                days = (_date.today() - d).days
            cr = rd.get("current_regime", {})
            regime_value = cr.get("regime", "unknown")
        except Exception:
            pass
    if days is None:
        days = days_since_last_regime_check(LAST_REGIME_PATH)

    if days is None:
        passed = False
        detail = "Last regime check: unknown (no truth store or daily-reviews record)"
        label = "Regime check: unknown"
    elif days > REGIME_STALE_DAYS:
        passed = False
        detail = f"Regime: {regime_value.upper()}, last update {days}d ago (stale, limit {REGIME_STALE_DAYS}d)"
        label = f"Regime stale: {days}d ago"
    else:
        passed = True
        detail = f"Regime: {regime_value.upper()}, updated {days}d ago"
        label = f"Regime: {regime_value.upper()} ({days}d ago)"

    return CheckItem(
        check_id="REGIME_STALE",
        category="SOFT_WARNING",
        passed=passed,
        label=label,
        detail=detail,
        rule_ref="strategy §0.5 — Regime Detection",
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
# Aggression Gate checks (US)
# ─────────────────────────────────────────────────────────────────────────────

# ETF tickers exempt from undersized-position check
_ETF_TICKERS = {"QQQ", "SPY", "TQQQ", "SQQQ", "SSO", "UPRO", "SMH", "SOXX", "IWM", "DIA", "VOO", "VTI"}


def check_us_cash_drag(state: dict) -> CheckItem:
    """[AGGRESSION GATE 4] US cash > 5% of NAV in BULL regime = cash drag warning."""
    us = state["accounts"]["us"]
    cash = float(us.get("cash", 0))
    total = float(us.get("total_assets", 0))
    cash_pct = cash / total if total > 0 else 0.0
    warn = cash > 0 and cash_pct > 0.05
    passed = not warn
    if warn:
        monthly_drag = cash * 0.16 / 12
        detail = (
            f"⛔ [AGGRESSION GATE 4] US现金 ${cash:,.0f} ({cash_pct:.1%} of NAV)"
            f" 在BULL regime下跑输QQQ。每月损失约${monthly_drag:,.0f} vs 指数。"
            f"部署到conviction标的或QQQ。"
        )
        label = f"US cash drag: {cash_pct:.1%} of NAV"
    else:
        detail = f"US现金 {cash_pct:.1%} — 无现金拖累（margin in use 或 cash≤5%）"
        label = f"US cash drag OK: {cash_pct:.1%}"
    return CheckItem(
        check_id="US_CASH_DRAG",
        category="SOFT_WARNING",
        passed=passed,
        label=label,
        detail=detail,
        rule_ref="feedback_aggressive_stance.md — 现金=机会成本",
    )


def check_us_leverage_floor(state: dict) -> CheckItem:
    """Gross leverage < 1.25x is below hard floor per aggressive stance."""
    us = state["accounts"]["us"]
    total = float(us.get("total_assets", 0))
    positions = us.get("positions", [])
    gross = sum(calc_position_value(p) for p in positions
                if p.get("instrument_type") != "call_option")
    leverage = gross / total if total > 0 else 0.0
    passed = leverage >= 1.25
    if not passed:
        needed = (1.35 * total) - gross
        detail = (
            f"杠杆 {leverage:.2f}x < 1.25x 硬下限。"
            f"需增加${needed:,.0f}达到1.35x目标。"
        )
        label = f"US leverage below floor: {leverage:.2f}x"
    else:
        detail = f"杠杆 {leverage:.2f}x ≥ 1.25x 硬下限 OK"
        label = f"US leverage OK: {leverage:.2f}x"
    return CheckItem(
        check_id="US_LEVERAGE_FLOOR",
        category="SOFT_WARNING",
        passed=passed,
        label=label,
        detail=detail,
        rule_ref="feedback_aggressive_stance.md — 杠杆1.25x硬下限/1.35x目标",
    )


def check_us_position_undersized(state: dict) -> CheckItem:
    """[AGGRESSION GATE 3] Non-ETF US positions < 8% of NAV are below B-grade minimum."""
    us = state["accounts"]["us"]
    total = float(us.get("total_assets", 0))
    positions = us.get("positions", [])
    violations = []
    for pos in positions:
        ticker = pos.get("ticker", "?")
        if ticker in _ETF_TICKERS:
            continue
        if pos.get("instrument_type") == "call_option":
            continue
        value = calc_position_value(pos)
        weight = value / total if total > 0 else 0.0
        if weight < 0.08:
            violations.append((ticker, weight))

    passed = len(violations) == 0
    if not passed:
        parts = "; ".join(
            f"{t} 仓位仅 {w:.1%} 低于B级最低10%线。考虑加仓到≥10%或清仓。"
            for t, w in violations
        )
        detail = parts
        label = f"US undersized positions: {', '.join(t for t, _ in violations)}"
    else:
        detail = "所有非ETF美股持仓 ≥ 8% NAV"
        label = "US position sizes OK (≥8%)"
    return CheckItem(
        check_id="US_POSITION_UNDERSIZED",
        category="SOFT_WARNING",
        passed=passed,
        label=label,
        detail=detail,
        rule_ref="feedback_aggressive_stance.md — B级最低10%线",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Market-specific check bundles
# ─────────────────────────────────────────────────────────────────────────────

def check_astock(state: dict, pending: dict) -> list[CheckItem]:
    """
    All checks for A股 only (v7.0 rules):
      HARD BLOCKS: position count ≤ 5, cash ≥ 20%, grade floor ≥ B-,
                   sector concentration ≤ 35%, bear case, daily trade limit ≤ 2,
                   weekly trade count ≤ 8, pending overdue
      SOFT WARNINGS: single position concentration (SABCT grade cap), round-trip check,
                     stop-loss proximity, If-Then rules loaded, pending approaching/urgent
    A股 does NOT check: US position count, US min size, short exposure, regime detection, US concentration
    """
    return [
        # HARD BLOCKS (v7.0)
        check_cn_position_count(state),
        check_cn_cash_reserve(state),
        check_cn_grade_floor(state),
        check_cn_sector_concentration(state),
        check_cn_bear_case_documented(state),
        check_cn_daily_trade_limit(state),
        check_cn_weekly_trade_count(state),
        check_cn_pending_overdue(state, pending, "astock"),
        # SOFT WARNINGS (v7.0)
        warn_cn_position_concentration(state),
        warn_cn_round_trip(state),
        warn_cn_stop_loss_proximity(state),
        warn_cn_if_then_loaded(state),
        warn_cn_pending_approaching(state, pending, "astock"),
        warn_cn_pending_urgent_today(state, pending, "astock"),
    ]


def check_us(state: dict, pending: dict) -> list[CheckItem]:
    """
    All checks for US only:
      HARD BLOCKS: position count ≤ 9 (L16), min size $7,500 (L16), short exposure ≥ 5% (L18),
                   bear case, pending overdue
      SOFT WARNINGS: short below 10% target, single position concentration > 15%, C-grade age,
                     regime check freshness, pending approaching/urgent, cash drag (Gate 4),
                     leverage floor, undersized positions (Gate 3)
    US does NOT check: A股 position count, A股 cash, A股 concentration, A股-specific anything
    """
    return [
        # HARD BLOCKS
        check_us_position_count(state),
        check_us_minimum_position_size(state),
        check_us_short_exposure(state),
        check_us_bear_case_documented(state),
        check_us_pending_overdue(state, pending, "us"),
        # SOFT WARNINGS
        warn_us_short_below_target(state),
        warn_us_position_concentration(state),
        warn_us_c_grade_stale(state),
        warn_regime_stale(state),
        warn_us_pending_approaching(state, pending, "us"),
        warn_us_pending_urgent_today(state, pending, "us"),
        # Aggression Gates
        check_us_cash_drag(state),
        check_us_leverage_floor(state),
        check_us_position_undersized(state),
    ]


def check_both(state: dict, pending: dict) -> list[CheckItem]:
    """
    All checks for both markets combined (default mode, backward compatible).
    Pending actions without a market field are shown in both passes
    but deduplicated here by running each market's full set and merging.
    """
    # For both-mode we run the original combined pending check (no market filter = all)
    return [
        # A股 HARD BLOCKS (v7.0)
        check_cn_position_count(state),
        check_cn_cash_reserve(state),
        check_cn_grade_floor(state),
        check_cn_sector_concentration(state),
        check_cn_bear_case_documented(state),
        check_cn_daily_trade_limit(state),
        check_cn_weekly_trade_count(state),
        check_cn_pending_overdue(state, pending, None),
        # US HARD BLOCKS
        check_us_position_count(state),
        check_us_minimum_position_size(state),
        check_us_short_exposure(state),
        check_us_bear_case_documented(state),
        check_us_pending_overdue(state, pending, None),
        # A股 SOFT WARNINGS (v7.0)
        warn_cn_position_concentration(state),
        warn_cn_round_trip(state),
        warn_cn_stop_loss_proximity(state),
        warn_cn_if_then_loaded(state),
        warn_cn_pending_approaching(state, pending, None),
        warn_cn_pending_urgent_today(state, pending, None),
        # US SOFT WARNINGS
        warn_us_short_below_target(state),
        warn_us_position_concentration(state),
        warn_us_c_grade_stale(state),
        warn_regime_stale(state),
        warn_us_pending_approaching(state, pending, None),
        warn_us_pending_urgent_today(state, pending, None),
        # US Aggression Gates
        check_us_cash_drag(state),
        check_us_leverage_floor(state),
        check_us_position_undersized(state),
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
     "[A股] 持仓超弹性上限7只: exit weakest thesis or lowest-grade first"),
    ("CN_GRADE_FLOOR",
     "[A股 GRADE] v7.0: Exit all C/T/scout-grade positions immediately — minimum grade is B-"),
    ("CN_SECTOR_CONCENTRATION",
     "[A股 SECTOR] v7.0: Trim overweight sector to ≤30% immediately before any new trade"),
    ("CN_WEEKLY_TRADE_COUNT",
     "[A股 WEEKLY] 本周交易笔数超参考值8笔 — 注意节奏，非硬性限制"),
    ("CN_DAILY_TRADE_LIMIT",
     "[A股 DAILY] v7.0: Daily new-build limit ≤2 reached — wait until tomorrow for new positions"),
    ("CN_PENDING_OVERDUE",
     "[A股 PENDING] Execute overdue A股 P0/P1 actions immediately"),
    ("US_PENDING_OVERDUE",
     "[US PENDING] Execute overdue US P0/P1 actions immediately"),
    ("CN_BEAR_CASE_DOCUMENTED",
     "[A股 BEAR_CASE] Document bear case for all A股 positions before trading"),
    ("US_BEAR_CASE_DOCUMENTED",
     "[US BEAR_CASE] Document bear case for all US positions before trading"),
    ("US_CASH_RESERVE",
     "[CASH_US] Cash is currently positive — consider deploying to ETF or conviction positions."),
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

    # ── Intel sections (always appended after verdict) ──────────────────────
    print()
    _print_changelog_updates(report)
    _print_agent_inbox(report)
    _print_news_briefing()
    _print_cross_intel()
    _print_research_update(report.market)


# ─────────────────────────────────────────────────────────────────────────────
# Intel section helpers
# ─────────────────────────────────────────────────────────────────────────────


def _print_changelog_updates(report: CheckReport) -> None:
    """Print unacknowledged system changelog entries + auto-ack them."""
    if not CHANGELOG_PATH.exists():
        return

    # Detect session identity from market
    market = getattr(report, "market", "both")
    if market == "astock":
        session_id = "trading_astock"
    elif market == "us":
        session_id = "trading_us"
    else:
        session_id = "trading_both"

    try:
        with open(CHANGELOG_PATH) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return

    pending = []
    for entry in data.get("entries", []):
        targets = entry.get("target", [])
        if "all" not in targets and session_id not in targets:
            # Also match partial: "trading_astock" matches "trading_astock"
            if not any(session_id.startswith(t) or t.startswith(session_id) for t in targets):
                continue
        ack = entry.get("ack", {})
        if session_id in ack:
            continue
        pending.append(entry)

    if not pending:
        return

    icons = {"critical": "🔴", "high": "🟡", "medium": "🔵", "low": "⚪"}
    print(f"═══ [系统变更通知] {len(pending)}条未确认 ═══")
    for e in pending:
        icon = icons.get(e.get("priority", "medium"), "🔵")
        print(f"{icon} {e.get('title', '?')} (来自 {e.get('from', '?')})")
        print(f"  {e.get('summary', '')}")
        changes = e.get("changes", [])
        for c in changes[:5]:
            print(f"  • {c}")
        if len(changes) > 5:
            print(f"  ... 共{len(changes)}项")
        if e.get("action_required"):
            print(f"  ⚡ {e['action_required']}")

    # Auto-ack: mark all as read by this session
    now_str = datetime.now().astimezone().isoformat()
    for entry in data.get("entries", []):
        targets = entry.get("target", [])
        if "all" not in targets and session_id not in targets:
            if not any(session_id.startswith(t) or t.startswith(session_id) for t in targets):
                continue
        if "ack" not in entry:
            entry["ack"] = {}
        if session_id not in entry["ack"]:
            entry["ack"][session_id] = now_str

    try:
        with open(CHANGELOG_PATH, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"  [已自动确认 {len(pending)} 条变更]")
    except OSError:
        pass
    print()


def _print_agent_inbox(report: CheckReport) -> None:
    """Print unread agent messages + auto-ack them."""
    try:
        from agent_comms import get_unread_for_session, auto_ack_all
    except ImportError:
        # agent_comms.py not available — try path-based import
        agent_comms_path = Path(__file__).parent / "agent_comms.py"
        if not agent_comms_path.exists():
            return
        import importlib.util
        spec = importlib.util.spec_from_file_location("agent_comms", agent_comms_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        get_unread_for_session = mod.get_unread_for_session
        auto_ack_all = mod.auto_ack_all

    market = getattr(report, "market", "both")
    if market == "astock":
        session_id = "trading_astock"
    elif market == "us":
        session_id = "trading_us"
    else:
        session_id = "trading_both"

    unread = get_unread_for_session(session_id)
    if not unread:
        return

    icons = {"critical": "🔴", "high": "🟡", "medium": "🔵", "low": "⚪"}
    print(f"═══ [Agent消息] {len(unread)}条未读 ═══")
    for msg in unread[-5:]:
        icon = icons.get(msg.get("priority", "medium"), "🔵")
        ts = msg.get("timestamp", "")[:16]
        reply_tag = f" ↩️" if msg.get("reply_to") else ""
        print(f"{icon} [{msg['id']}] {msg.get('subject', '?')}{reply_tag}")
        print(f"  来自: {msg.get('from', '?')} | {ts}")
        body = msg.get("body", "")[:200]
        print(f"  {body}")
    if len(unread) > 5:
        print(f"  ... 共{len(unread)}条，仅显示最近5条")

    count = auto_ack_all(session_id)
    if count:
        print(f"  [已自动标记 {count} 条已读]")
    print()


def _print_news_briefing() -> None:
    """Print [新闻速报] section from catalyst_alerts.json (last 8 hours)."""
    if not CATALYST_ALERTS_PATH.exists():
        print("═══ [新闻速报] 最近8h无重大消息 ═══")
        return

    try:
        data = json.loads(CATALYST_ALERTS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        print("═══ [新闻速报] 最近8h无重大消息 ═══")
        return

    alerts = data.get("alerts", []) if isinstance(data, dict) else data
    if not isinstance(alerts, list):
        print("═══ [新闻速报] 最近8h无重大消息 ═══")
        return

    # Filter to last 8 hours (handle both tz-aware and naive datetimes)
    from datetime import timezone as _tz
    cutoff = datetime.now(_tz.utc) - timedelta(hours=8)
    recent: list[dict] = []
    for a in alerts:
        ts_str = a.get("timestamp") or a.get("time") or a.get("news_time") or ""
        if ts_str:
            try:
                ts = datetime.fromisoformat(ts_str)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=_tz.utc)
                if ts < cutoff:
                    continue
            except ValueError:
                pass  # if unparseable, include it
        recent.append(a)

    if not recent:
        print("═══ [新闻速报] 最近8h无重大消息 ═══")
        return

    print("═══ [新闻速报] 最近8h重大消息 ═══")
    for a in recent:
        level    = (a.get("level") or a.get("urgency", "")).upper()
        ticker   = a.get("ticker") or a.get("symbol", "")
        headline = a.get("headline") or a.get("news_headline") or a.get("title") or a.get("summary", "")
        source   = a.get("source") or a.get("news_source", "")
        time_str = a.get("time") or a.get("news_time") or a.get("timestamp", "")
        # Short time display (HH:MM only)
        if time_str:
            try:
                time_short = datetime.fromisoformat(time_str).strftime("%H:%M")
            except ValueError:
                time_short = time_str[:5]
        else:
            time_short = ""

        icon = "🔴" if level in ("BREAKING", "CRITICAL", "HIGH") else "🟡"
        meta_parts = [p for p in [source, time_short] if p]
        meta = f" ({', '.join(meta_parts)})" if meta_parts else ""
        ticker_prefix = f"{ticker}: " if ticker else ""
        print(f"• {icon} {level + ': ' if level else ''}{ticker_prefix}{headline}{meta}")

        # Holding match
        holding_info = a.get("holding_match") or a.get("portfolio_match", "")
        if holding_info:
            print(f"  持仓匹配: {holding_info}")


def _print_cross_intel() -> None:
    """Print [跨市场情报] section from cross_intel_brief.json."""
    if not CROSS_INTEL_PATH.exists():
        return

    try:
        data = json.loads(CROSS_INTEL_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return

    summary = data.get("other_market_summary", "") if isinstance(data, dict) else ""
    if not summary:
        return

    print("═══ [跨市场情报] ═══")
    # summary may be a string or a list of strings
    if isinstance(summary, list):
        for line in summary:
            print(line)
    else:
        print(summary)

    # Optional catalyst overlap field
    overlap = data.get("catalyst_overlap", "")
    if overlap:
        print(f"催化剂重叠: {overlap}")


def _print_research_update(market: str = "both") -> None:
    """Print one-line [研究更新] section from watchlist.md if holdings match.

    market: "astock", "us", or "both" — controls which account's tickers are
    loaded for matching.  Only tickers relevant to the selected market are
    used, preventing cross-market reads when a specific market is requested.
    """
    if not WATCHLIST_PATH.exists():
        return

    try:
        text = WATCHLIST_PATH.read_text(encoding="utf-8")
    except OSError:
        return

    # Load current holdings tickers for matching — respect market isolation
    tickers: set[str] = set()
    if PORTFOLIO_PATH.exists():
        try:
            state = json.loads(PORTFOLIO_PATH.read_text(encoding="utf-8"))
            accounts = state.get("accounts", {})
            # A股 tickers — only when market is "astock" or "both"
            if market in ("astock", "both"):
                for pos in accounts.get("a_share", {}).get("positions", {}).values():
                    t = pos.get("ticker") or pos.get("symbol", "")
                    if t:
                        tickers.add(t.upper())
            # US tickers — only when market is "us" or "both"
            if market in ("us", "both"):
                for pos in accounts.get("us", {}).get("positions", {}).values():
                    t = pos.get("ticker") or pos.get("symbol", "")
                    if t:
                        tickers.add(t.upper())
        except (json.JSONDecodeError, OSError, AttributeError):
            pass

    # Scan watchlist.md lines for holding tickers with rating + bear case info
    # Pattern: line containing a ticker symbol we hold, followed by grade/bear-case info
    matched_lines: list[str] = []
    for line in text.splitlines():
        line_upper = line.upper()
        for ticker in tickers:
            if ticker in line_upper:
                # Prefer lines that have thesis or bear-case context
                if any(kw in line.lower() for kw in ("thesis", "bear", "级", "rating", "t1", "t2", "t3", "t4")):
                    matched_lines.append(line.strip())
                    break
        if len(matched_lines) >= 1:
            break  # one-line summary only

    if not matched_lines:
        return

    print("═══ [研究更新] ═══")
    print(matched_lines[0][:120])  # cap at 120 chars for compact display


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

_QUICK_BLOCK_IDS = {
    # Stop-loss / circuit breaker checks — IDs used by the check functions
    "CN_STOP_LOSS",
    "US_STOP_LOSS",
    "CIRCUIT_BREAKER",
    "CN_WEEKLY_TRADE_COUNT",
    "US_WEEKLY_BUDGET",
}


def print_quick_report(report: CheckReport) -> None:
    """Compact output for --quick mode: only blocking items (<3s target)."""
    # Filter to hard blocks that are in the quick-check set, or ALL hard blocks
    # (stop-loss / circuit breaker / budget are always surfaced)
    blocking = [b for b in report.hard_blocks if b.check_id in _QUICK_BLOCK_IDS]
    # If none of the quick-set IDs matched, fall back to all hard blocks so the
    # user isn't silently given a CLEARED when something is actually broken.
    if not blocking:
        blocking = report.hard_blocks

    if blocking:
        print(f"[QUICK] BLOCKED ({len(blocking)} item{'s' if len(blocking) != 1 else ''})")
        for b in blocking:
            print(f"  ❌ {b.check_id}: {b.detail}")
    else:
        print(f"[QUICK] CLEARED — no blocking items")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pre-session compliance gate for sim-portfolio.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Market modes:
  (no flag)        Check both A股 and 美股 (default, backward compatible)
  --market astock  Check A股 only (v7.0): position count ≤ 5, cash ≥ 20%, grade ≥ B-,
                   sector ≤ 35%, bear case, daily builds ≤ 2, weekly trades ≤ 8,
                   round-trip, stop-loss proximity, If-Then rules
  --market us      Check 美股 only: L16 count/size, L18 short exposure, cash, bear case, regime

Quick mode:
  --quick          Only check blocking items (stop-loss, circuit breaker, weekly budget).
                   Skips news, cross-intel, and full compliance. Target: <3s.
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
    parser.add_argument(
        "--quick", action="store_true",
        help="Quick mode: only check stop-loss, circuit breaker, and weekly budget. "
             "Skips news/cross-intel/full compliance. Target: <3s.",
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

    # --quick mode: compact output, no intel sections
    if args.quick:
        print_quick_report(report)
        write_result_json(report)
        sys.exit(1 if report.verdict == "BLOCKED" else 0)

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

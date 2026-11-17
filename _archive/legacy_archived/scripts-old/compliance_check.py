# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Post-trade compliance enforcement for L16, L17, L18 (US) and A股 rules.

Usage:
  uv run --script scripts/compliance_check.py                       # full check (US)
  uv run --script scripts/compliance_check.py --post-trade          # post-trade hook (faster, no regime fetch)
  uv run --script scripts/compliance_check.py --account us          # US account only
  uv run --script scripts/compliance_check.py --market astock       # A股 rules only (position count ≤8, conc per SABCT grade, sector ≤40%)
  uv run --script scripts/compliance_check.py --market us           # US rules only (L16/L17/L18)
  uv run --script scripts/compliance_check.py --post-trade --market us  # Quick US post-trade check
  uv run --script scripts/compliance_check.py --regime-only         # L17 check only
  uv run --script scripts/compliance_check.py --summary             # machine-readable JSON summary
  uv run --script scripts/compliance_check.py --no-write            # dry run, no writes
  uv run --script scripts/compliance_check.py --quiet               # suppress formatted output
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PORTFOLIO_PATH    = Path(__file__).parent.parent / "portfolio_state.json"
PENDING_PATH      = Path(__file__).parent.parent / "pending_actions.json"
WATCHLIST_PATH    = Path(__file__).parent.parent / "watchlist_config.json"
REGIME_JSON       = Path.home() / ".claude/nexus/truth/macro/regime.json"
MACRO_EVENTS_PATH = Path(__file__).parent.parent / "market_calendar.json"
AUDIT_TRAIL_DIR   = Path(__file__).parent.parent / "audit-trail"

# L16 thresholds
MAX_US_LONG_POSITIONS  = 9
MIN_POSITION_VALUE_USD = 7500

# L17 thresholds
VIX_DELTA_5D_SIGNAL    = 3.0
REGIME_ADJUST_WINDOW_H = 24

# L18 thresholds
SHORT_TARGET_MIN_PCT   = 0.10
SHORT_TARGET_MAX_PCT   = 0.15
SHORT_HARD_FLOOR_PCT   = 0.05
CRITICAL_DAYS_NO_SHORT = 5

TZ_BEIJING = timezone(timedelta(hours=8))

# A股 compliance thresholds
try:
    from core.config import ASTOCK_MAX_POSITIONS_FLEX as _FLEX
    ASTOCK_MAX_POSITIONS = _FLEX   # 弹性上限7只 (strategy.md: 尽量≤5，弹性至7)
except ImportError:
    ASTOCK_MAX_POSITIONS = 7
ASTOCK_MAX_SECTOR_PCT    = 0.40   # single sector ≤ 40% of total assets
ASTOCK_SINGLE_CAP        = 0.35   # absolute single-position hard cap (S级 can reach 40%)

# SABCT grade → max concentration (strategy.md v6.2 §3.3.1)
SABCT_CONCENTRATION_LIMITS: dict[str, float] = {
    "S":  0.40,
    "A+": 0.35,
    "A":  0.25,
    "A-": 0.20,
    "B+": 0.15,
    "B":  0.15,
    "C+": 0.08,
    "C":  0.08,
    "T":  0.08,
}

def _get_position_concentration_limit(pos: dict) -> float:
    """Return the max allowed concentration for a position based on its SABCT grade."""
    grade = pos.get("conviction_level") or pos.get("confidence_grade") or ""
    grade = grade.strip().upper()
    if grade in SABCT_CONCENTRATION_LIMITS:
        return SABCT_CONCENTRATION_LIMITS[grade]
    ptype = (pos.get("type") or "").lower()
    if "core" in ptype:
        return 0.25  # default core → A-level cap
    if "catalyst" in ptype or "trading" in ptype:
        return 0.15  # default catalyst/trading → B+-level cap
    return ASTOCK_SINGLE_CAP  # fallback to absolute hard cap

# Do-not-short list (long positions that mirror these would be confusing)
DO_NOT_SHORT = {"META", "NVDA", "AVGO", "AAPL", "MSFT", "GOOGL"}

# Hardcoded macro events fallback when market_calendar.json lacks macro_events key
HARDCODED_MACRO_EVENTS_2026_Q2 = [
    {"date": "2026-06-11", "event_type": "CPI",  "description": "US CPI May 2026"},
    {"date": "2026-06-18", "event_type": "FOMC", "description": "FOMC June 2026 Decision"},
    {"date": "2026-07-03", "event_type": "NFP",  "description": "US NFP June 2026"},
]

# NYSE closed dates (holidays only — weekends handled separately)
# Read from market_calendar.json at runtime; this is the fallback
FALLBACK_NYSE_CLOSED = {"2026-05-25", "2026-06-19"}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class L16Result:
    status: str                           # "OK" | "VIOLATION"
    position_count: int
    max_allowed: int = MAX_US_LONG_POSITIONS
    positions_to_close: list[str] = field(default_factory=list)
    undersized_positions: list[dict] = field(default_factory=list)
    action_items: list[str] = field(default_factory=list)


@dataclass
class L17Result:
    status: str                           # "OK" | "WARNING" | "STALE" | "REGIME_SHIFT_UNACKNOWLEDGED"
    last_regime_check: str | None
    current_regime: str | None
    hours_since_check: float | None
    vix_5d_delta: float | None
    regime_shifted: bool = False
    adjustment_required: bool = False
    upcoming_macro_events: list[dict] = field(default_factory=list)
    action_items: list[str] = field(default_factory=list)


@dataclass
class L18Result:
    status: str                           # "OK" | "NOTICE" | "WARNING" | "CRITICAL"
    short_exposure_usd: float
    short_exposure_pct: float
    target_min_pct: float = SHORT_TARGET_MIN_PCT
    hard_floor_pct: float = SHORT_HARD_FLOOR_PCT
    consecutive_days_zero: int = 0
    long_block_active: bool = False
    top_short_candidates: list[str] = field(default_factory=list)
    action_items: list[str] = field(default_factory=list)


@dataclass
class AStockResult:
    status: str                           # "OK" | "VIOLATION"
    position_count: int
    max_allowed: int = ASTOCK_MAX_POSITIONS
    concentration_violations: list[dict] = field(default_factory=list)  # [{ticker, pct, limit}]
    sector_violations: list[dict] = field(default_factory=list)         # [{sector, pct, limit}]
    action_items: list[str] = field(default_factory=list)


@dataclass
class ComplianceReport:
    timestamp: str
    overall_status: str                   # "OK" | "NOTICE" | "WARNING" | "CRITICAL"
    l16: L16Result
    l17: L17Result
    l18: L18Result
    astock: AStockResult | None = None
    new_violations_written: int = 0
    violations_already_tracked: int = 0


@dataclass
class ViolationRecord:
    id: str
    type: str = "compliance_violation"
    rule: str = ""
    severity: str = ""
    ticker: str | None = None
    account: str = "us"
    detected_at: str = ""
    status: str = "pending"
    priority: str = "high"
    description: str = ""
    action_required: str = ""
    deadline: str | None = None
    consecutive_days: int = 1
    auto_generated: bool = True


@dataclass
class MacroEvent:
    date: str
    event_type: str
    description: str
    days_until: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def now_bjt() -> datetime:
    return datetime.now(TZ_BEIJING)


def now_iso() -> str:
    return now_bjt().isoformat(timespec="seconds")


def severity_rank(s: str) -> int:
    return {"OK": 0, "NOTICE": 1, "WARNING": 2, "CRITICAL": 3}.get(s, 0)


def severity_to_priority(severity: str) -> str:
    return {"CRITICAL": "urgent", "WARNING": "high", "NOTICE": "medium"}.get(severity, "medium")


def deadline_from_now(hours: int = 24) -> str:
    return (now_bjt() + timedelta(hours=hours)).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Portfolio loading
# ---------------------------------------------------------------------------

def load_portfolio() -> dict:
    if not PORTFOLIO_PATH.exists():
        return {}
    with open(PORTFOLIO_PATH, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# L16 — Shotgun Ban
# ---------------------------------------------------------------------------

def _rank_positions_for_closure(positions: list[dict], total_assets: float) -> list[dict]:
    """
    Sort positions by closure priority (highest = close first).
    Priority = (conviction_rank * 3) + (no_catalyst_30d * 2) + (below_minimum * 1)
    conviction_rank: C/T=3, B=2, A=1, S=0 (S never flagged)
    """
    conviction_map = {"S": 0, "A": 1, "B": 2, "C": 3, "T": 3}
    today = now_bjt().date()

    def score(pos: dict) -> int:
        level = pos.get("conviction_level", "B") or "B"
        conv_rank = conviction_map.get(level.upper(), 2)
        if conv_rank == 0:
            return -1  # S-grade: never flag

        # Catalyst within 30 days?
        has_catalyst_30d = False
        catalyst_date_str = pos.get("next_catalyst", "") or ""
        # Try to extract a date from next_catalyst field (may be free text or date string)
        if catalyst_date_str:
            for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
                try:
                    cat_date = datetime.strptime(catalyst_date_str[:10], fmt).date()
                    if 0 <= (cat_date - today).days <= 30:
                        has_catalyst_30d = True
                    break
                except ValueError:
                    pass

        no_catalyst_30d = 0 if has_catalyst_30d else 1
        below_min = 1 if pos.get("market_value", 0) < MIN_POSITION_VALUE_USD else 0
        return (conv_rank * 3) + (no_catalyst_30d * 2) + (below_min * 1)

    # Filter out S-grade (score = -1) and sort by descending score
    scored = [(score(p), p) for p in positions if score(p) >= 0]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in scored]


def _generate_l16_action_items(
    excess_positions: list[dict],
    undersized: list[dict],
    total_assets: float,
    pending_list: list[dict],
) -> list[str]:
    """Generate specific action strings for L16 violations."""
    items = []

    # Step 1: excess position closures
    for pos in excess_positions:
        ticker = pos.get("ticker", "?")
        value = pos.get("market_value", 0)
        conviction = pos.get("conviction_level", "B") or "B"
        # Check catalyst status
        has_catalyst = False
        catalyst_str = pos.get("next_catalyst", "") or ""
        today = now_bjt().date()
        for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
            try:
                cat_date = datetime.strptime(catalyst_str[:10], fmt).date()
                if 0 <= (cat_date - today).days <= 30:
                    has_catalyst = True
                break
            except ValueError:
                pass

        reason_parts = [f"{conviction}-grade"]
        if not has_catalyst:
            reason_parts.append("no catalyst within 30d")
        if value < MIN_POSITION_VALUE_USD:
            reason_parts.append("below minimum")
        reason = ", ".join(reason_parts)
        items.append(f"Sell {ticker} (${value:,.0f}) — {reason}")

    # Step 2: undersized positions
    already_in_excess = {p.get("ticker") for p in excess_positions}
    for pos_info in undersized:
        ticker = pos_info["ticker"]
        if ticker in already_in_excess:
            continue
        value = pos_info["value"]
        shortfall = pos_info["shortfall"]

        # Check for existing PA entry
        existing_pa = _find_pa_for_ticker(pending_list, ticker)
        if existing_pa and existing_pa.get("trigger_date"):
            pa_id = existing_pa.get("id", "")
            trigger_date = existing_pa["trigger_date"]
            items.append(
                f"{ticker} (${value:,.0f}): await {trigger_date} earnings per {pa_id}, "
                f"then upgrade to ${MIN_POSITION_VALUE_USD:,} or exit"
            )
        elif shortfall <= 2000:
            items.append(
                f"Add ${shortfall:,.0f} to {ticker} to reach ${MIN_POSITION_VALUE_USD:,} minimum"
            )
        else:
            items.append(
                f"Sell {ticker} (${value:,.0f}) or add ${shortfall:,.0f} to reach "
                f"minimum ${MIN_POSITION_VALUE_USD:,}"
            )

    return items


def _find_pa_for_ticker(pending_list: list[dict], ticker: str) -> dict | None:
    """Find a pending action entry for a given ticker."""
    for pa in pending_list:
        if pa.get("ticker") == ticker and pa.get("status") not in ("resolved", "completed"):
            return pa
    return None


def check_l16_shotgun_ban(
    account: dict,
    total_assets_usd: float,
    pending_list: list[dict],
) -> L16Result:
    """Check L16: position count <= 9, all positions >= $7,500."""
    positions = account.get("positions", [])
    # Count long positions only (not short_positions)
    long_positions = [p for p in positions if p.get("market_value", 0) > 0]
    position_count = len(long_positions)

    # Find undersized positions (below $7,500 minimum)
    undersized = []
    for pos in long_positions:
        mv = pos.get("market_value", 0)
        if mv < MIN_POSITION_VALUE_USD:
            undersized.append({
                "ticker": pos.get("ticker", "?"),
                "value": mv,
                "shortfall": round(MIN_POSITION_VALUE_USD - mv, 2),
            })

    if position_count <= MAX_US_LONG_POSITIONS and not undersized:
        return L16Result(
            status="OK",
            position_count=position_count,
        )

    # Rank positions for potential closure
    ranked = _rank_positions_for_closure(long_positions, total_assets_usd)

    # Determine which need to be closed due to excess count
    excess_count = max(0, position_count - MAX_US_LONG_POSITIONS)
    positions_to_close = [p.get("ticker", "?") for p in ranked[:excess_count]]
    excess_pos_dicts = ranked[:excess_count]

    # Generate action items
    action_items = _generate_l16_action_items(
        excess_pos_dicts, undersized, total_assets_usd, pending_list
    )

    return L16Result(
        status="VIOLATION",
        position_count=position_count,
        positions_to_close=positions_to_close,
        undersized_positions=undersized,
        action_items=action_items,
    )


# ---------------------------------------------------------------------------
# L17 — Regime Awareness
# ---------------------------------------------------------------------------

def _load_regime_state() -> dict | None:
    """Reads regime.json from Nexus Truth Store. Returns None if missing."""
    if not REGIME_JSON.exists():
        return None
    try:
        with open(REGIME_JSON, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _check_macro_calendar_proximity(calendar_path: Path) -> list[MacroEvent]:
    """Return macro events (FOMC/CPI/NFP) within 3 calendar days."""
    today = now_bjt().date()
    cutoff = today + timedelta(days=3)
    events = []

    raw_events = []
    if calendar_path.exists():
        try:
            with open(calendar_path, encoding="utf-8") as f:
                cal = json.load(f)
            if "macro_events" in cal:
                raw_events = cal["macro_events"]
            else:
                print("[L17] macro_events not found in market_calendar.json, using hardcoded Q2 2026 schedule")
                raw_events = HARDCODED_MACRO_EVENTS_2026_Q2
        except (json.JSONDecodeError, OSError):
            print("[L17] Failed to read market_calendar.json, using hardcoded Q2 2026 schedule")
            raw_events = HARDCODED_MACRO_EVENTS_2026_Q2
    else:
        print("[L17] market_calendar.json missing, using hardcoded Q2 2026 schedule")
        raw_events = HARDCODED_MACRO_EVENTS_2026_Q2

    for ev in raw_events:
        try:
            ev_date = datetime.strptime(ev["date"], "%Y-%m-%d").date()
            if today <= ev_date <= cutoff:
                events.append(MacroEvent(
                    date=ev["date"],
                    event_type=ev.get("event_type", ev.get("type", "MACRO")),
                    description=ev.get("description", ""),
                    days_until=(ev_date - today).days,
                ))
        except (ValueError, KeyError):
            continue
    return events


def _detect_regime_shift(regime_state: dict) -> bool:
    """Return True if a regime shift occurred within last 24h."""
    current = regime_state.get("current_regime", {})
    today_str = now_bjt().date().isoformat()
    since_date = current.get("since_date", "")
    days_in_regime = current.get("days_in_regime", 999)

    # Regime changed today or yesterday with very short duration
    if since_date == today_str and days_in_regime <= 1:
        return True

    # VIX 5-day delta check from signals_snapshot
    signals = regime_state.get("signals_snapshot", {})
    vix_val = signals.get("vix", {}).get("value")
    # We don't have 5d delta stored directly, so we can't compute it without live data
    # Skip this check in post-trade mode (no live fetch)
    return False


def _check_portfolio_adjustment_post_shift(
    regime_state: dict,
    trade_log: list[dict],
) -> bool:
    """
    Return True if a portfolio adjustment was logged within REGIME_ADJUST_WINDOW_H
    hours after the detected regime shift.
    """
    current = regime_state.get("current_regime", {})
    since_date = current.get("since_date", "")
    if not since_date:
        return False

    try:
        shift_dt = datetime.strptime(since_date, "%Y-%m-%d").replace(tzinfo=TZ_BEIJING)
    except ValueError:
        return False

    window_end = shift_dt + timedelta(hours=REGIME_ADJUST_WINDOW_H)
    for trade in trade_log:
        ts_str = trade.get("timestamp", "")
        if not ts_str:
            continue
        try:
            # Parse ISO timestamp (with or without timezone)
            if ts_str.endswith("+08:00"):
                ts = datetime.fromisoformat(ts_str)
            else:
                ts = datetime.fromisoformat(ts_str).replace(tzinfo=TZ_BEIJING)
            if shift_dt <= ts <= window_end:
                if trade.get("action") in ("buy", "sell", "short", "cover"):
                    return True
        except (ValueError, TypeError):
            continue
    return False


def check_l17_regime_awareness(
    portfolio_state: dict,
    post_trade: bool = False,
) -> L17Result:
    """Check L17: regime.json currency and shift acknowledgment."""
    regime_state = _load_regime_state()
    upcoming_macro = _check_macro_calendar_proximity(MACRO_EVENTS_PATH)
    action_items = []

    if regime_state is None:
        # No regime.json — warn but not CRITICAL
        macro_events_dicts = [
            {"date": e.date, "event_type": e.event_type, "days_until": e.days_until}
            for e in upcoming_macro
        ]
        if upcoming_macro:
            action_items.append(
                f"[L17] WARN: regime.json missing — update before "
                f"{upcoming_macro[0].event_type} on {upcoming_macro[0].date}"
            )
        else:
            action_items.append("[L17] WARN: regime.json missing — run regime detection")
        return L17Result(
            status="WARNING",
            last_regime_check=None,
            current_regime=None,
            hours_since_check=None,
            vix_5d_delta=None,
            upcoming_macro_events=macro_events_dicts,
            action_items=action_items,
        )

    # Parse last_updated
    meta = regime_state.get("metadata", {})
    last_updated_str = meta.get("last_updated", "")
    current = regime_state.get("current_regime", {})
    regime_name = current.get("regime", "unknown")
    confidence = current.get("confidence", 0)

    hours_since: float | None = None
    if last_updated_str:
        try:
            last_dt = datetime.fromisoformat(last_updated_str)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=TZ_BEIJING)
            hours_since = (now_bjt() - last_dt).total_seconds() / 3600
        except ValueError:
            pass

    status = "OK"
    regime_shifted = _detect_regime_shift(regime_state)

    # Check for stale regime data (>24h)
    stale_after_days = regime_state.get("stale_after_days", 1)
    stale_threshold_h = stale_after_days * 24

    if hours_since is not None and hours_since > stale_threshold_h:
        status = "WARNING"
        action_items.append(
            f"[L17] STALE: regime.json is {hours_since:.1f}h old (threshold {stale_threshold_h}h) "
            f"— run regime detection to refresh"
        )

    adjustment_required = False
    if regime_shifted:
        trade_log = portfolio_state.get("trade_log", [])
        adjustment_made = _check_portfolio_adjustment_post_shift(regime_state, trade_log)
        if not adjustment_made:
            adjustment_required = True
            if status != "CRITICAL":
                status = "WARNING"
            action_items.append(
                f"[L17] Regime shifted to {regime_name.upper()} — "
                f"no portfolio adjustment logged within {REGIME_ADJUST_WINDOW_H}h. "
                "Review and adjust holdings or document rationale."
            )

    # Check macro events proximity
    macro_events_dicts = []
    for ev in upcoming_macro:
        macro_events_dicts.append({
            "date": ev.date,
            "event_type": ev.event_type,
            "days_until": ev.days_until,
            "description": ev.description,
        })
        if ev.days_until <= 1 and hours_since is not None and hours_since > 12:
            if status == "OK":
                status = "WARNING"
            action_items.append(
                f"[L17] {ev.event_type} in {ev.days_until}d ({ev.date}) — "
                f"regime.json {hours_since:.1f}h old, refresh recommended before event"
            )

    # VIX 5d delta (from signals_snapshot, no live fetch in post-trade mode)
    vix_5d_delta: float | None = None
    signals = regime_state.get("signals_snapshot", {})
    vix_current = signals.get("vix", {}).get("value")

    return L17Result(
        status=status,
        last_regime_check=last_updated_str,
        current_regime=regime_name,
        hours_since_check=round(hours_since, 1) if hours_since is not None else None,
        vix_5d_delta=vix_5d_delta,
        regime_shifted=regime_shifted,
        adjustment_required=adjustment_required,
        upcoming_macro_events=macro_events_dicts,
        action_items=action_items,
    )


# ---------------------------------------------------------------------------
# L18 — Short Quota
# ---------------------------------------------------------------------------

def _calculate_short_exposure(account: dict, total_assets: float) -> tuple[float, float]:
    """Return (short_exposure_usd, short_exposure_pct)."""
    short_positions = account.get("short_positions", [])
    exposure_usd = 0.0
    for pos in short_positions:
        # Use current market value if available, otherwise shares * entry_price
        mv = pos.get("market_value")
        if mv is None or mv == 0:
            shares = pos.get("shares", 0)
            entry = pos.get("entry_price", pos.get("avg_cost", 0))
            mv = shares * entry
        exposure_usd += abs(mv)
    pct = (exposure_usd / total_assets) if total_assets > 0 else 0.0
    return round(exposure_usd, 2), round(pct, 4)


def _get_nyse_closed_dates() -> set[str]:
    """Load NYSE closed dates from market_calendar.json."""
    if MACRO_EVENTS_PATH.exists():
        try:
            with open(MACRO_EVENTS_PATH, encoding="utf-8") as f:
                cal = json.load(f)
            td = cal.get("trading_days_by_market", {})
            closed = set(td.get("us_closed_dates", []))
            return closed
        except (json.JSONDecodeError, OSError):
            pass
    return FALLBACK_NYSE_CLOSED


def _is_trading_day(d: date, nyse_closed: set[str]) -> bool:
    """Return True if d is a NYSE trading day (not weekend, not holiday)."""
    if d.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    return d.isoformat() not in nyse_closed


def _count_consecutive_no_short_days(audit_dir: Path) -> int:
    """
    Count consecutive trading days with no 'short' action in audit-trail/.
    Returns 0 if today has a short, or the count of days since the last short.
    """
    if not audit_dir.exists():
        # Fallback: check portfolio start date
        try:
            state = load_portfolio()
            start_str = state.get("_meta", {}).get("start_date", "")
            if start_str:
                start_dt = datetime.strptime(start_str, "%Y-%m-%d").date()
                today = now_bjt().date()
                nyse_closed = _get_nyse_closed_dates()
                count = 0
                d = today
                while d >= start_dt:
                    if _is_trading_day(d, nyse_closed):
                        count += 1
                    d -= timedelta(days=1)
                return count
        except Exception:
            pass
        return 0

    # Collect all short action dates from audit-trail filenames and content
    short_dates: set[str] = set()

    for f in audit_dir.iterdir():
        if not f.suffix == ".json":
            continue
        name = f.stem  # e.g. "2026-05-22-MSTR-short-001"
        # Check filename for 'short'
        if "short" in name.lower():
            # Extract date from filename (first 10 chars)
            date_str = name[:10]
            try:
                datetime.strptime(date_str, "%Y-%m-%d")
                short_dates.add(date_str)
                continue
            except ValueError:
                pass
        # Also check file content for action=="short"
        try:
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
            if data.get("action") == "short":
                ts = data.get("timestamp", "")
                if ts:
                    date_str = ts[:10]
                    try:
                        datetime.strptime(date_str, "%Y-%m-%d")
                        short_dates.add(date_str)
                    except ValueError:
                        pass
        except (json.JSONDecodeError, OSError):
            continue

    nyse_closed = _get_nyse_closed_dates()
    today = now_bjt().date()

    if not short_dates:
        # No shorts ever — count from portfolio start date
        try:
            state = load_portfolio()
            start_str = state.get("_meta", {}).get("start_date", "")
            if start_str:
                start_dt = datetime.strptime(start_str, "%Y-%m-%d").date()
                count = 0
                d = today
                while d >= start_dt:
                    if _is_trading_day(d, nyse_closed):
                        count += 1
                    d -= timedelta(days=1)
                return count
        except Exception:
            pass
        return 0

    # Find last short date
    last_short = max(datetime.strptime(ds, "%Y-%m-%d").date() for ds in short_dates)

    # Count trading days from last_short+1 up to and including today
    consecutive = 0
    d = last_short + timedelta(days=1)
    while d <= today:
        if _is_trading_day(d, nyse_closed):
            consecutive += 1
        d += timedelta(days=1)
    return consecutive


def _get_short_candidates(
    watchlist_path: Path,
    current_long_tickers: set[str],
    current_short_tickers: set[str],
) -> list[dict]:
    """Read us_short_candidates from watchlist_config.json, filtered and sorted."""
    if not watchlist_path.exists():
        return []
    try:
        with open(watchlist_path, encoding="utf-8") as f:
            wl = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []

    candidates = wl.get("us_short_candidates", [])
    filtered = []
    for c in candidates:
        ticker = c.get("ticker", "")
        if ticker in current_long_tickers:
            continue
        if ticker in current_short_tickers:
            continue
        if ticker in DO_NOT_SHORT:
            continue
        filtered.append(c)

    # Sort by priority: Type 1 > Type 2 > Type 3 > Type 4
    def type_rank(c: dict) -> int:
        t = str(c.get("short_type", c.get("type", "Type 4")))
        if "Type 1" in t or "type 1" in t.lower():
            return 1
        if "Type 2" in t or "type 2" in t.lower():
            return 2
        if "Type 3" in t or "type 3" in t.lower():
            return 3
        return 4

    filtered.sort(key=type_rank)
    return filtered


def check_l18_short_quota(
    account: dict,
    total_assets_usd: float,
) -> L18Result:
    """Check L18: short exposure >= 5% of US total_assets."""
    short_usd, short_pct = _calculate_short_exposure(account, total_assets_usd)
    consecutive_days = _count_consecutive_no_short_days(AUDIT_TRAIL_DIR)

    # Collect current long and short tickers
    long_tickers = {p.get("ticker", "") for p in account.get("positions", [])}
    short_tickers = {p.get("ticker", "") for p in account.get("short_positions", [])}

    candidates = _get_short_candidates(WATCHLIST_PATH, long_tickers, short_tickers)
    top_candidates = [c.get("ticker", "") for c in candidates[:3]]

    action_items = []
    long_block_active = False

    # Determine severity
    if short_pct == 0 and consecutive_days >= CRITICAL_DAYS_NO_SHORT:
        status = "CRITICAL"
        long_block_active = True
        action_items.append(
            f"CRITICAL: 0% short exposure for {consecutive_days} consecutive days "
            f"— long-block active"
        )
        action_items.append("Execute weekly short SOP tonight (W3 22:00 BJT)")
        action_items.append(
            f"Minimum target: 1 short position >= ${MIN_POSITION_VALUE_USD:,}"
        )
    elif short_pct < SHORT_HARD_FLOOR_PCT:
        # Below 5% hard floor (includes 0%)
        status = "WARNING"
        deficit_usd = SHORT_HARD_FLOOR_PCT * total_assets_usd - short_usd
        action_items.append(
            f"Short exposure {short_pct*100:.1f}% below hard floor {SHORT_HARD_FLOOR_PCT*100:.0f}% "
            f"— need at least ${deficit_usd:,.0f} more short exposure"
        )
        if consecutive_days > 0:
            action_items.append(
                f"{consecutive_days} consecutive trading days without new short position"
            )
    elif short_pct < SHORT_TARGET_MIN_PCT:
        # Below 10% target (but above 5% floor)
        status = "NOTICE"
        deficit_usd = SHORT_TARGET_MIN_PCT * total_assets_usd - short_usd
        action_items.append(
            f"Short exposure {short_pct*100:.1f}% below target {SHORT_TARGET_MIN_PCT*100:.0f}% "
            f"— consider adding ${deficit_usd:,.0f} short exposure"
        )
    else:
        status = "OK"

    if top_candidates and status != "OK":
        for i, c in enumerate(candidates[:3], 1):
            ticker = c.get("ticker", "")
            short_type = c.get("short_type", c.get("type", ""))
            reason = c.get("catalyst", c.get("short_thesis", ""))[:50] if c.get("catalyst") or c.get("short_thesis") else ""
            action_items.append(f"Candidate {i}: {ticker} — {short_type}, {reason}")

    return L18Result(
        status=status,
        short_exposure_usd=short_usd,
        short_exposure_pct=short_pct,
        consecutive_days_zero=consecutive_days,
        long_block_active=long_block_active,
        top_short_candidates=top_candidates,
        action_items=action_items,
    )


# ---------------------------------------------------------------------------
# A股 Compliance Rules
# ---------------------------------------------------------------------------

def check_astock_rules(account: dict) -> AStockResult:
    """
    Check A股-specific compliance rules:
      1. Position count ≤ 8
      2. Single-position concentration ≤ SABCT grade cap (strategy.md v6.2 §3.3.1)
      3. Single-sector concentration ≤ 40% of total assets
    """
    positions = account.get("positions", [])
    total_assets = account.get("total_assets", 0.0)
    position_count = len(positions)

    violations = False
    action_items: list[str] = []
    concentration_violations: list[dict] = []
    sector_violations: list[dict] = []

    # Rule 1: position count
    if position_count > ASTOCK_MAX_POSITIONS:
        violations = True
        excess = position_count - ASTOCK_MAX_POSITIONS
        action_items.append(
            f"Position count {position_count} exceeds A股 limit of {ASTOCK_MAX_POSITIONS} "
            f"— close {excess} position(s)"
        )

    if total_assets > 0:
        # Rule 2: single-position concentration ≤ SABCT grade cap
        for pos in positions:
            ticker = pos.get("ticker", "?")
            grade = pos.get("conviction_level") or pos.get("confidence_grade") or "?"
            mv = pos.get("market_value") or pos.get("shares", 0) * pos.get("avg_cost", 0)
            pct = mv / total_assets
            limit = _get_position_concentration_limit(pos)
            if pct > limit:
                violations = True
                concentration_violations.append({
                    "ticker": ticker,
                    "pct": round(pct, 4),
                    "limit": limit,
                    "grade": grade,
                    "excess_pct": round(pct - limit, 4),
                })
                action_items.append(
                    f"{ticker} concentration {pct*100:.1f}% exceeds {grade}-grade cap {limit*100:.0f}% "
                    f"— trim by ¥{(pct - limit) * total_assets:,.0f}"
                )

        # Rule 3: single-sector concentration ≤ 40%
        sector_values: dict[str, float] = {}
        for pos in positions:
            sector = pos.get("sector", "Unknown") or "Unknown"
            mv = pos.get("market_value") or pos.get("shares", 0) * pos.get("avg_cost", 0)
            sector_values[sector] = sector_values.get(sector, 0.0) + mv
        for sector, mv in sector_values.items():
            pct = mv / total_assets
            if pct > ASTOCK_MAX_SECTOR_PCT:
                violations = True
                sector_violations.append({
                    "sector": sector,
                    "pct": round(pct, 4),
                    "limit": ASTOCK_MAX_SECTOR_PCT,
                    "excess_pct": round(pct - ASTOCK_MAX_SECTOR_PCT, 4),
                })
                action_items.append(
                    f"Sector '{sector}' at {pct*100:.1f}% exceeds A股 40% cap "
                    f"— reduce by ¥{(pct - ASTOCK_MAX_SECTOR_PCT) * total_assets:,.0f}"
                )

    return AStockResult(
        status="VIOLATION" if violations else "OK",
        position_count=position_count,
        concentration_violations=concentration_violations,
        sector_violations=sector_violations,
        action_items=action_items,
    )


# ---------------------------------------------------------------------------
# Pending Actions I/O
# ---------------------------------------------------------------------------

def load_pending_actions(path: Path) -> dict:
    """Load pending_actions.json. Returns empty structure if file missing."""
    if not path.exists():
        return {
            "_meta": {
                "version": "1.0",
                "last_updated": now_iso(),
            },
            "pending": [],
            "completed": [],
            "session_instructions": {},
        }
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {
            "_meta": {"version": "1.0", "last_updated": now_iso()},
            "pending": [],
            "completed": [],
            "session_instructions": {},
        }


def save_pending_actions_atomic(path: Path, state: dict) -> None:
    """Atomic write using tempfile + os.replace."""
    # Update timestamp
    if "_meta" in state:
        state["_meta"]["last_updated"] = now_iso()
    dir_ = path.parent
    try:
        fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".tmp", prefix="pending_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
                f.write("\n")
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except Exception as e:
        raise RuntimeError(f"pending_actions.json write failed: {e}") from e


def _make_violation_id(rule: str, ticker: str | None, date_str: str, sequence: int) -> str:
    """Returns 'COMP-L16-20260522-001' format ID."""
    return f"COMP-{rule}-{date_str}-{sequence:03d}"


def _find_existing_violation(
    pending_list: list[dict],
    rule: str,
    ticker: str | None,
) -> dict | None:
    """Find existing pending compliance_violation entry for rule+ticker."""
    for item in pending_list:
        if item.get("type") != "compliance_violation":
            continue
        if item.get("status") in ("resolved", "acknowledged"):
            continue
        if item.get("rule") != rule:
            continue
        if ticker is None and item.get("ticker") is None:
            return item
        if ticker is not None and item.get("ticker") == ticker:
            return item
    return None


def write_violations_to_pending(
    violations: list[ViolationRecord],
    pending_path: Path,
) -> tuple[int, int]:
    """
    Merge new violations into pending_actions.json.
    Returns (new_violations_written, violations_already_tracked).
    """
    if not violations:
        return 0, 0

    # Always re-read latest before writing (multi-session safety)
    state = load_pending_actions(pending_path)
    pending_list = state.get("pending", [])

    today_str = now_bjt().strftime("%Y%m%d")
    new_count = 0
    updated_count = 0

    # Find max sequence number for today's compliance violations
    existing_seq = 0
    for item in pending_list:
        if item.get("type") == "compliance_violation":
            item_id = item.get("id", "")
            if today_str in item_id:
                try:
                    seq = int(item_id.split("-")[-1])
                    existing_seq = max(existing_seq, seq)
                except (ValueError, IndexError):
                    pass

    # Check completed/resolved violations for sequence counter too
    for item in state.get("completed", []):
        if item.get("type") == "compliance_violation":
            item_id = item.get("id", "")
            if today_str in item_id:
                try:
                    seq = int(item_id.split("-")[-1])
                    existing_seq = max(existing_seq, seq)
                except (ValueError, IndexError):
                    pass

    seq_counter = existing_seq + 1

    for v in violations:
        existing = _find_existing_violation(pending_list, v.rule, v.ticker)
        if existing is not None:
            # Update consecutive_days and detected_at
            existing["consecutive_days"] = existing.get("consecutive_days", 1) + 1
            existing["detected_at"] = v.detected_at
            existing["description"] = v.description
            existing["action_required"] = v.action_required
            # Escalate severity if consecutive_days >= 3
            if existing["consecutive_days"] >= 3:
                existing["severity"] = "CRITICAL"
                existing["priority"] = "urgent"
            updated_count += 1
        else:
            # New violation entry
            v.id = _make_violation_id(v.rule, v.ticker, today_str, seq_counter)
            seq_counter += 1
            pending_list.append({
                "id": v.id,
                "type": v.type,
                "rule": v.rule,
                "severity": v.severity,
                "ticker": v.ticker,
                "account": v.account,
                "detected_at": v.detected_at,
                "status": v.status,
                "priority": v.priority,
                "description": v.description,
                "action_required": v.action_required,
                "deadline": v.deadline,
                "consecutive_days": v.consecutive_days,
                "auto_generated": v.auto_generated,
            })
            new_count += 1

    state["pending"] = pending_list
    save_pending_actions_atomic(pending_path, state)
    return new_count, updated_count


def _resolve_cleared_violations(
    l16: L16Result,
    l17: L17Result,
    l18: L18Result,
    pending_path: Path,
) -> None:
    """
    Move resolved violations (conditions cleared) to completed array.
    """
    state = load_pending_actions(pending_path)
    pending_list = state.get("pending", [])
    completed_list = state.get("completed", [])
    now = now_iso()
    still_pending = []

    # Build sets of active violations
    active_l16_tickers: set[str | None] = set()
    if l16.status == "VIOLATION":
        for pos in l16.undersized_positions:
            active_l16_tickers.add(pos["ticker"])
        # Also add positions_to_close as active
        for t in l16.positions_to_close:
            active_l16_tickers.add(t)

    for item in pending_list:
        if item.get("type") != "compliance_violation":
            still_pending.append(item)
            continue

        rule = item.get("rule", "")
        ticker = item.get("ticker")
        resolved = False

        if rule == "L16":
            if l16.status == "OK":
                resolved = True
            elif ticker is not None and ticker not in active_l16_tickers:
                resolved = True
        elif rule == "L17":
            if l17.status == "OK":
                resolved = True
        elif rule == "L18":
            if l18.status == "OK":
                resolved = True

        if resolved:
            item["status"] = "resolved"
            item["resolved_at"] = now
            completed_list.append(item)
        else:
            still_pending.append(item)

    state["pending"] = still_pending
    state["completed"] = completed_list
    save_pending_actions_atomic(pending_path, state)


# ---------------------------------------------------------------------------
# Repeated Violation Escalation
# ---------------------------------------------------------------------------

def check_repeated_violations(
    pending_list: list[dict],
    consecutive_threshold: int = 3,
) -> list[dict]:
    """Escalate violations with consecutive_days >= threshold to CRITICAL."""
    escalated = []
    for item in pending_list:
        if item.get("type") != "compliance_violation":
            continue
        days = item.get("consecutive_days", 1)
        if days >= consecutive_threshold:
            rule = item.get("rule", "")
            if item.get("severity") != "CRITICAL":
                item["severity"] = "CRITICAL"
                item["priority"] = "urgent"
                print(
                    f"[COMPLIANCE] ESCALATION: {rule} violated {days} consecutive days "
                    f"— CRITICAL FLAG ACTIVE"
                )
            escalated.append(item)
    return escalated


# ---------------------------------------------------------------------------
# L18 Long-Block
# ---------------------------------------------------------------------------

def check_l18_long_block(pending_list: list[dict]) -> bool:
    """
    Return True if L18 long-block is active (consecutive_days >= CRITICAL_DAYS_NO_SHORT).
    """
    for item in pending_list:
        if (
            item.get("type") == "compliance_violation"
            and item.get("rule") == "L18"
            and item.get("status") == "pending"
            and item.get("consecutive_days", 0) >= CRITICAL_DAYS_NO_SHORT
        ):
            print(
                f"[COMPLIANCE] L18 LONG-BLOCK: Short exposure = 0% for 5+ days.\n"
                f"  New long positions blocked until >= 1 short position deployed."
            )
            return True
    return False


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------

def run_compliance_check(
    account_key: str = "us",
    market: str = "us",
    post_trade: bool = False,
    regime_only: bool = False,
    summary: bool = False,
    no_write: bool = False,
    quiet: bool = False,
) -> ComplianceReport:
    """
    Top-level orchestrator. Loads state, runs market-specific checks,
    writes violations, prints results, returns report.

    market="astock" → only A股 rules (position count ≤8, conc per SABCT grade, sector ≤40%).
                       L16 / L17 / L18 are skipped entirely.
    market="us"     → only US rules (L16 / L17 / L18). A股 rules are skipped.
    """
    ts = now_iso()
    portfolio_state = load_portfolio()

    # Resolve account key from market flag when not explicitly overridden
    if market == "astock":
        account_key = "a_share"
    elif market == "us" and account_key not in ("us", "a_share"):
        account_key = "us"

    account = portfolio_state.get("accounts", {}).get(account_key, {})
    total_assets = account.get("total_assets", 0.0)

    # Load pending actions for context
    pending_state = load_pending_actions(PENDING_PATH)
    pending_list = pending_state.get("pending", [])

    # Null / placeholder results (populated below based on market mode)
    l16 = L16Result(status="OK", position_count=0)
    l17 = L17Result(
        status="OK", last_regime_check=None, current_regime=None,
        hours_since_check=None, vix_5d_delta=None,
    )
    l18 = L18Result(status="OK", short_exposure_usd=0, short_exposure_pct=0)
    astock_result: AStockResult | None = None

    # --- A股 mode: ONLY A股 rules ---
    if market == "astock":
        astock_result = check_astock_rules(account)

        severities = []
        if astock_result.status == "VIOLATION":
            severities.append("WARNING")
        overall = max(severities, key=lambda s: severity_rank(s)) if severities else "OK"

        violations: list[ViolationRecord] = []
        now = now_iso()
        if astock_result.status == "VIOLATION":
            for item_desc in astock_result.action_items:
                violations.append(ViolationRecord(
                    id="",
                    rule="ASTOCK",
                    severity="WARNING",
                    ticker=None,
                    account=account_key,
                    detected_at=now,
                    priority="high",
                    description=item_desc,
                    action_required=item_desc,
                    deadline=deadline_from_now(24),
                ))

        new_written = 0
        already_tracked = 0
        if not no_write and violations:
            new_written, already_tracked = write_violations_to_pending(violations, PENDING_PATH)

        report = ComplianceReport(
            timestamp=ts,
            overall_status=overall,
            l16=l16,
            l17=l17,
            l18=l18,
            astock=astock_result,
            new_violations_written=new_written,
            violations_already_tracked=already_tracked,
        )

        if summary:
            _print_summary_json(report)
        elif not quiet:
            _print_formatted_report(report, account_key)
        return report

    # --- US mode: ONLY L16 / L17 / L18 ---
    if regime_only:
        l16 = L16Result(status="OK", position_count=0)
        l18 = L18Result(status="OK", short_exposure_usd=0, short_exposure_pct=0)
    else:
        l16 = check_l16_shotgun_ban(account, total_assets, pending_list)
        l18 = check_l18_short_quota(account, total_assets)

    l17 = check_l17_regime_awareness(portfolio_state, post_trade=post_trade)

    # --- Determine overall status ---
    severities = []
    if l16.status == "VIOLATION":
        severities.append("WARNING")
    if l17.status in ("WARNING", "STALE", "REGIME_SHIFT_UNACKNOWLEDGED"):
        severities.append("WARNING")
    if l18.status == "CRITICAL":
        severities.append("CRITICAL")
    elif l18.status == "WARNING":
        severities.append("WARNING")
    elif l18.status == "NOTICE":
        severities.append("NOTICE")

    # Check consecutive escalations
    check_repeated_violations(pending_list)
    for item in pending_list:
        if item.get("severity") == "CRITICAL" and item.get("type") == "compliance_violation":
            severities.append("CRITICAL")

    if not severities:
        overall = "OK"
    else:
        overall = max(severities, key=lambda s: severity_rank(s))

    # Check L18 long block
    long_block = check_l18_long_block(pending_list)

    # --- Build violations list ---
    violations: list[ViolationRecord] = []
    now = now_iso()

    # L16 violations
    if l16.status == "VIOLATION":
        # Overall count violation
        if l16.position_count > MAX_US_LONG_POSITIONS:
            violations.append(ViolationRecord(
                id="",
                rule="L16",
                severity="WARNING",
                ticker=None,
                account=account_key,
                detected_at=now,
                priority="high",
                description=(
                    f"US long positions: {l16.position_count} / {MAX_US_LONG_POSITIONS} allowed "
                    f"({l16.position_count - MAX_US_LONG_POSITIONS} excess)"
                ),
                action_required="; ".join(
                    f"Close {t}" for t in l16.positions_to_close
                ) or "Reduce positions to 9 or fewer",
                deadline=deadline_from_now(24),
            ))
        # Individual undersized positions
        for pos_info in l16.undersized_positions:
            ticker = pos_info["ticker"]
            value = pos_info["value"]
            shortfall = pos_info["shortfall"]
            violations.append(ViolationRecord(
                id="",
                rule="L16",
                severity="WARNING",
                ticker=ticker,
                account=account_key,
                detected_at=now,
                priority="high",
                description=f"Position {ticker} (${value:,.2f}) below minimum ${MIN_POSITION_VALUE_USD:,}",
                action_required=f"Sell {ticker} (${value:,.0f}) OR add ${shortfall:,.0f} to reach minimum ${MIN_POSITION_VALUE_USD:,}",
                deadline=deadline_from_now(48),
            ))

    # L17 violations
    if l17.status in ("WARNING", "STALE", "REGIME_SHIFT_UNACKNOWLEDGED"):
        violations.append(ViolationRecord(
            id="",
            rule="L17",
            severity="WARNING",
            ticker=None,
            account=account_key,
            detected_at=now,
            priority="medium",
            description=f"Regime awareness issue: {l17.status} — last check {l17.last_regime_check}",
            action_required="; ".join(l17.action_items) or "Update regime detection",
            deadline=deadline_from_now(24),
        ))

    # L18 violations
    if l18.status in ("WARNING", "CRITICAL", "NOTICE"):
        severity = l18.status if l18.status != "NOTICE" else "WARNING"
        violations.append(ViolationRecord(
            id="",
            rule="L18",
            severity=severity,
            ticker=None,
            account=account_key,
            detected_at=now,
            priority=severity_to_priority(severity),
            description=(
                f"Short exposure {l18.short_exposure_pct*100:.1f}% "
                f"({l18.consecutive_days_zero} consecutive days with no new short)"
            ),
            action_required="; ".join(l18.action_items[:2]) if l18.action_items else "Deploy short position",
            deadline=deadline_from_now(24),
        ))

    # --- Write to pending_actions.json ---
    new_written = 0
    already_tracked = 0
    if not no_write and violations:
        # First resolve cleared violations
        _resolve_cleared_violations(l16, l17, l18, PENDING_PATH)
        new_written, already_tracked = write_violations_to_pending(violations, PENDING_PATH)
    elif not no_write:
        # Still resolve any cleared violations
        _resolve_cleared_violations(l16, l17, l18, PENDING_PATH)

    report = ComplianceReport(
        timestamp=ts,
        overall_status=overall,
        l16=l16,
        l17=l17,
        l18=l18,
        astock=None,
        new_violations_written=new_written,
        violations_already_tracked=already_tracked,
    )

    # --- Output ---
    if summary:
        _print_summary_json(report)
    elif not quiet:
        _print_formatted_report(report, account_key)

    return report


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def _print_formatted_report(report: ComplianceReport, account_key: str) -> None:
    """Print the full formatted compliance report."""
    l16, l17, l18 = report.l16, report.l17, report.l18
    overall = report.overall_status

    # ── A股 mode ──────────────────────────────────────────────────
    if report.astock is not None:
        ast = report.astock
        print("=" * 60)
        print("  Compliance Check — A股 Rules")
        print("=" * 60)
        print(f"  Timestamp: {report.timestamp}")
        print(f"  Account:   {account_key}")
        print()

        print(f"  [A股 {ast.status}] Position Rules")
        print("  " + "─" * 41)
        print(f"  Position count: {ast.position_count} / {ast.max_allowed} allowed", end="")
        if ast.position_count > ast.max_allowed:
            print(f"  ← OVER LIMIT ({ast.position_count - ast.max_allowed} excess)")
        else:
            print()

        if ast.concentration_violations:
            print("  Concentration violations (SABCT grade cap):")
            for v in ast.concentration_violations:
                grade = v.get('grade', '?')
                print(f"    {v['ticker']:<8} {v['pct']*100:.1f}% (grade {grade}, limit {v['limit']*100:.0f}%, excess {v['excess_pct']*100:.1f}%)")

        if ast.sector_violations:
            print("  Sector concentration violations (>40%):")
            for v in ast.sector_violations:
                print(f"    {v['sector']:<20} {v['pct']*100:.1f}% (limit 40%, excess {v['excess_pct']*100:.1f}%)")

        if ast.action_items:
            print("  Action items:")
            for i, item in enumerate(ast.action_items, 1):
                print(f"    {i}. {item}")
        print()

        print("  " + "─" * 56)
        violation_note = "Violations written to pending_actions.json" if (
            report.new_violations_written > 0 or report.violations_already_tracked > 0
        ) else "No writes"
        print(f"  OVERALL: {overall} | {violation_note}")
        print(f"  New: {report.new_violations_written}  |  Already tracked: {report.violations_already_tracked}")
        print("=" * 60)
        return

    # ── US mode ───────────────────────────────────────────────────
    print("=" * 60)
    print("  Compliance Check — L16 / L17 / L18")
    print("=" * 60)
    print(f"  Timestamp: {report.timestamp}")
    print(f"  Account:   {account_key}")
    print()

    # L16
    l16_hdr = f"[L16 {l16.status}] Shotgun Ban"
    print(f"  {l16_hdr}")
    print("  " + "─" * 41)
    print(f"  Positions: {l16.position_count} / {l16.max_allowed} allowed", end="")
    if l16.position_count > l16.max_allowed:
        excess = l16.position_count - l16.max_allowed
        print(f"  ← OVER LIMIT ({excess} excess)")
    else:
        print()

    if l16.undersized_positions:
        print("  Undersized (below $7,500):")
        for pos in l16.undersized_positions:
            print(
                f"    {pos['ticker']:<6} ${pos['value']:>8,.2f}  "
                f"shortfall ${pos['shortfall']:>7,.2f}"
            )
    if l16.action_items:
        print("  Action items:")
        for i, item in enumerate(l16.action_items, 1):
            print(f"    {i}. {item}")
    print()

    # L17
    regime_label = (l17.current_regime or "UNKNOWN").upper()
    l17_hdr = f"[L17 {l17.status}] Regime Awareness"
    print(f"  {l17_hdr}")
    print("  " + "─" * 41)
    if l17.last_regime_check:
        since_str = f"{l17.hours_since_check:.1f}h ago" if l17.hours_since_check else ""
        print(f"  Last check: {l17.last_regime_check} ({since_str})")
    else:
        print("  Last check: N/A (regime.json missing)")
    if l17.current_regime:
        confidence_pct = ""
        # Try to get confidence from regime.json
        rs = _load_regime_state()
        if rs:
            conf = rs.get("current_regime", {}).get("confidence", "")
            if conf:
                confidence_pct = f" (confidence {int(float(conf)*100)}%)"
        print(f"  Current regime: {regime_label}{confidence_pct}")
    if l17.regime_shifted:
        print("  *** REGIME SHIFT DETECTED ***")
    if l17.adjustment_required:
        print("  Adjustment required within 24h of shift.")
    if l17.upcoming_macro_events:
        events_str = ", ".join(
            f"{e['event_type']} {e['date']}" for e in l17.upcoming_macro_events
        )
        print(f"  Upcoming macro events (<=3d): {events_str}")
    else:
        print("  No macro events within 3 days.")
    if l17.action_items:
        for item in l17.action_items:
            print(f"  {item}")
    print()

    # L18
    long_block_note = " — LONG-BLOCK ACTIVE" if l18.long_block_active else ""
    l18_hdr = f"[L18 {l18.status}] Short Quota{long_block_note}"
    print(f"  {l18_hdr}")
    print("  " + "─" * 41)
    print(
        f"  Short exposure: ${l18.short_exposure_usd:,.2f} ({l18.short_exposure_pct*100:.1f}%) "
        f"| Target: {l18.target_min_pct*100:.0f}-{SHORT_TARGET_MAX_PCT*100:.0f}% "
        f"| Floor: {l18.hard_floor_pct*100:.0f}%"
    )
    if l18.consecutive_days_zero > 0:
        print(
            f"  Consecutive days at 0%: {l18.consecutive_days_zero}"
            + (" ← SYSTEM FAILURE THRESHOLD" if l18.consecutive_days_zero >= CRITICAL_DAYS_NO_SHORT else "")
        )
    if l18.long_block_active:
        print("  LONG-BLOCK: New long positions should be deferred until >= 1 short deployed.")
    if l18.top_short_candidates:
        print("  Top candidates (from watchlist short_candidates):")
        for i, ticker in enumerate(l18.top_short_candidates, 1):
            print(f"    {i}. {ticker}")
    if l18.action_items:
        # Print action items that aren't the candidate lines (already printed above)
        non_candidate_items = [
            it for it in l18.action_items if not it.startswith("Candidate ")
        ]
        if non_candidate_items:
            print("  Actions:")
            for item in non_candidate_items:
                print(f"    - {item}")
    print()

    # Summary
    print("  " + "─" * 56)
    violation_note = f"Violations written to pending_actions.json" if (
        report.new_violations_written > 0 or report.violations_already_tracked > 0
    ) else "No writes"
    print(f"  OVERALL: {overall} | {violation_note}")
    print(f"  New: {report.new_violations_written}  |  Already tracked: {report.violations_already_tracked}")
    print("=" * 60)


def _print_summary_json(report: ComplianceReport) -> None:
    """Print machine-readable JSON summary."""
    l16, l17, l18 = report.l16, report.l17, report.l18
    out: dict = {
        "timestamp": report.timestamp,
        "overall_status": report.overall_status,
    }

    if report.astock is not None:
        ast = report.astock
        out["astock"] = {
            "status": ast.status,
            "position_count": ast.position_count,
            "max_allowed": ast.max_allowed,
            "concentration_violations": ast.concentration_violations,
            "sector_violations": ast.sector_violations,
            "action_items": ast.action_items,
        }
    else:
        out["l16"] = {
            "status": l16.status,
            "position_count": l16.position_count,
            "max_allowed": l16.max_allowed,
            "positions_to_close": l16.positions_to_close,
            "undersized_positions": l16.undersized_positions,
            "action_items": l16.action_items,
        }
        out["l17"] = {
            "status": l17.status,
            "last_regime_check": l17.last_regime_check,
            "current_regime": l17.current_regime,
            "hours_since_check": l17.hours_since_check,
            "vix_5d_delta": l17.vix_5d_delta,
            "regime_shifted": l17.regime_shifted,
            "adjustment_required": l17.adjustment_required,
            "upcoming_macro_events": l17.upcoming_macro_events,
            "action_items": l17.action_items,
        }
        out["l18"] = {
            "status": l18.status,
            "short_exposure_usd": l18.short_exposure_usd,
            "short_exposure_pct": l18.short_exposure_pct,
            "target_min_pct": l18.target_min_pct,
            "hard_floor_pct": l18.hard_floor_pct,
            "consecutive_days_zero": l18.consecutive_days_zero,
            "long_block_active": l18.long_block_active,
            "top_short_candidates": l18.top_short_candidates,
            "action_items": l18.action_items,
        }

    out["new_violations_written"] = report.new_violations_written
    out["violations_already_tracked"] = report.violations_already_tracked
    print(json.dumps(out, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Post-trade compliance enforcement for L16, L17, L18 (US) and A股 rules."
    )
    parser.add_argument("--post-trade", action="store_true",
                        help="Post-trade mode: skip live VIX fetch, use cached regime.json")
    parser.add_argument("--account", default=None,
                        help="Account to check: us | a_share | all (default: derived from --market)")
    parser.add_argument("--market", default="us", choices=["us", "astock"],
                        help="Market-specific rule set: us (L16/L17/L18) | astock (position/conc/sector rules)")
    parser.add_argument("--regime-only", action="store_true",
                        help="Run L17 check only (US mode only)")
    parser.add_argument("--summary", action="store_true",
                        help="Print machine-readable JSON report to stdout")
    parser.add_argument("--no-write", action="store_true",
                        help="Dry run: print violations but do not write to pending_actions.json")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress formatted output")
    args = parser.parse_args()

    # Derive account_key: explicit --account wins; otherwise infer from --market
    if args.account is not None:
        account_key = args.account if args.account != "all" else "us"
    else:
        account_key = "a_share" if args.market == "astock" else "us"

    report = run_compliance_check(
        account_key=account_key,
        market=args.market,
        post_trade=args.post_trade,
        regime_only=args.regime_only,
        summary=args.summary,
        no_write=args.no_write,
        quiet=args.quiet,
    )

    # Determine exit code
    if report.overall_status == "CRITICAL":
        # Exit 2 only if L18 long-block is active (US mode)
        if report.l18.long_block_active:
            return 2
        return 1
    elif report.overall_status in ("WARNING", "NOTICE"):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
escalation_check.py — Pending Action Escalation Engine
Part of the Execution Forcing Infrastructure (execution_forcing.md §机制一)

Reads pending_actions.json, calculates days since creation (or since trigger_date
for trigger_gated PAs), updates escalation levels, outputs a report, and saves
the updated file back.

Exit codes:
  0 — all PAs at normal/reminder/warning level (or trigger_gated not yet triggered)
  1 — at least one PA is at CRITICAL or FORCE level (signals pre_session_check to block)

Usage:
  python3 scripts/escalation_check.py
  python3 scripts/escalation_check.py --dry-run      # stdout only, no file write
  python3 scripts/escalation_check.py --market us    # only process US-market PAs
  python3 scripts/escalation_check.py --market astock  # only process A-share PAs
  python3 scripts/escalation_check.py --pa-file /path/to/pending_actions.json

Market filtering:
  --market us     → include PAs where market == "us" or market == "both"
  --market astock → include PAs where market == "astock" or market == "both"
  (no --market flag) → process all PAs regardless of market field
"""

import json
import sys
import os
import argparse
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Escalation schedule (non-trigger-gated, immediate clock)
# ---------------------------------------------------------------------------
ESCALATION_SCHEDULE = [
    (0, "normal"),
    (1, "reminder"),
    (2, "warning"),
    (3, "critical"),
    (5, "force"),
]

LEVEL_ORDER = ["normal", "reminder", "warning", "critical", "force"]

BLOCKING_LEVELS = {"critical", "force"}

# ANSI colours for terminal output
RED    = "\033[91m"
YELLOW = "\033[93m"
GREEN  = "\033[92m"
CYAN   = "\033[96m"
RESET  = "\033[0m"
BOLD   = "\033[1m"


def level_colour(level: str) -> str:
    colours = {
        "normal":   GREEN,
        "reminder": CYAN,
        "warning":  YELLOW,
        "critical": RED + BOLD,
        "force":    RED + BOLD,
    }
    return colours.get(level, RESET)


def parse_date(ds: str) -> date:
    """Parse ISO date string (date or datetime) to a date object."""
    ds = ds.strip()
    try:
        return date.fromisoformat(ds[:10])
    except ValueError:
        pass
    # Try datetime with offset
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(ds[:19], fmt[:len(fmt)]).date()
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {ds!r}")


def days_elapsed(start_str: str, today: date) -> int:
    """Return calendar days elapsed since start_str (non-negative)."""
    start = parse_date(start_str)
    delta = (today - start).days
    return max(0, delta)


def level_for_days(days: int) -> str:
    """Return the escalation level for a given number of elapsed days."""
    result = "normal"
    for threshold, level in ESCALATION_SCHEDULE:
        if days >= threshold:
            result = level
    return result


def higher_level(a: str, b: str) -> str:
    """Return whichever level is higher in the escalation order."""
    return a if LEVEL_ORDER.index(a) >= LEVEL_ORDER.index(b) else b


def compute_new_level(pa: dict, today: date) -> tuple[str, int, str]:
    """
    Compute the new escalation level for a single pending action.

    Returns:
        (new_level, days_counted, reason_string)
    """
    esc = pa.get("escalation", {})
    clock_type = esc.get("clock_type", "immediate")
    status = pa.get("status", "pending")

    # Completed / skipped PAs don't escalate
    if status in ("completed", "stale"):
        return esc.get("level", "normal"), 0, f"status={status}, no escalation"

    # -----------------------------------------------------------------------
    # weekly clock — escalates based on time since the scheduled window
    # -----------------------------------------------------------------------
    if clock_type == "weekly":
        clock_start_str = esc.get("clock_start") or pa.get("created_at", "")
        if not clock_start_str:
            return "normal", 0, "weekly: no clock_start found"
        clock_start_date = parse_date(clock_start_str)
        # Only start counting after the scheduled window date passes
        if today < clock_start_date:
            return "normal", 0, f"weekly: window not yet reached ({clock_start_date})"
        days = days_elapsed(clock_start_str, today)
        new_level = level_for_days(days)
        return new_level, days, f"weekly: {days}d since window {clock_start_date}"

    # -----------------------------------------------------------------------
    # trigger_gated clock — clock starts only after trigger_date passes
    # -----------------------------------------------------------------------
    if clock_type == "trigger_gated":
        trigger_date_str = pa.get("trigger_date") or esc.get("trigger_date_actual") or ""
        if not trigger_date_str:
            # No trigger date — fall through to immediate logic
            pass
        else:
            trigger_date = parse_date(trigger_date_str)
            if today < trigger_date:
                return "normal", 0, f"trigger_gated: waiting for trigger {trigger_date}"
            # Trigger date has passed — count from it
            days = (today - trigger_date).days
            days = max(0, days)
            new_level = level_for_days(days)
            return new_level, days, f"trigger_gated: {days}d since trigger {trigger_date}"

    # -----------------------------------------------------------------------
    # immediate clock (default)
    # -----------------------------------------------------------------------
    created_at = pa.get("created_at", "")
    if not created_at:
        return "normal", 0, "immediate: no created_at found"

    days = days_elapsed(created_at, today)

    # urgent items start at warning on Day 0, and jump straight to critical on Day 1
    if pa.get("status") == "urgent":
        if days == 0:
            new_level = higher_level("warning", level_for_days(days))
        else:
            new_level = higher_level("critical", level_for_days(days))
    else:
        new_level = level_for_days(days)

    return new_level, days, f"immediate: {days}d since creation"


def update_escalation_field(pa: dict, new_level: str, days: int, reason: str, today: date) -> dict:
    """
    Mutate the escalation sub-dict in-place with the new level.
    Appends to level_history only if level changed.
    Updates blocks_new_positions and created_days_ago.
    Returns the escalation dict for convenience.
    """
    esc = pa.setdefault("escalation", {})
    old_level = esc.get("level", "normal")

    # Always update days counter
    esc["created_days_ago"] = days

    # Update blocks_new_positions: true when level is critical or force
    if new_level in BLOCKING_LEVELS:
        esc["blocks_new_positions"] = True
    # Don't downgrade blocks_new_positions if it was already manually set to True
    # (e.g., PA-007 was manually set True at warning level)

    if new_level == old_level:
        return esc  # No change, skip history append

    # Record the transition
    esc["level"] = new_level
    history = esc.setdefault("level_history", [])
    history.append({
        "level": new_level,
        "set_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        "reason": reason,
    })

    return esc


def market_matches(pa: dict, market_filter: str | None) -> bool:
    """
    Return True if this PA should be processed given the active market filter.

    Rules:
      - market_filter=None  → always True (process all PAs)
      - market_filter="us"  → include PAs with market=="us" or market=="both";
                               also include PAs with no market field (legacy)
      - market_filter="astock" → include PAs with market=="astock" or market=="both";
                               also include PAs with no market field (legacy)
    """
    if market_filter is None:
        return True
    pa_market = pa.get("market")
    if pa_market is None:
        # Legacy PA without market tag — include in all filtered runs
        return True
    return pa_market in (market_filter, "both")


def run_escalation_check(
    pa_file: Path,
    today: date,
    dry_run: bool = False,
    market_filter: str | None = None,
) -> int:
    """
    Main check: reads PA file, updates escalations, writes back, returns exit code.

    Args:
        pa_file:       Path to pending_actions.json
        today:         Reference date for escalation calculation
        dry_run:       If True, print report only — do not write back to file
        market_filter: "us", "astock", or None (process all)
    """
    if not pa_file.exists():
        print(f"[escalation_check] WARNING: {pa_file} not found. Nothing to do.")
        return 0

    with pa_file.open() as f:
        data = json.load(f)

    pending = data.get("pending", [])
    if not pending:
        print("[escalation_check] No pending actions. All clear.")
        return 0

    # Apply market filter
    if market_filter:
        pending_filtered = [pa for pa in pending if market_matches(pa, market_filter)]
        skipped = len(pending) - len(pending_filtered)
    else:
        pending_filtered = pending
        skipped = 0

    if not pending_filtered:
        print(f"[escalation_check] No pending actions match market={market_filter!r}. All clear.")
        return 0

    changes = []
    blocking_count = 0
    report_lines = []

    report_lines.append(f"\n{'='*60}")
    market_label = f" [{market_filter.upper()}]" if market_filter else ""
    report_lines.append(f"  ESCALATION CHECK{market_label} — {today.isoformat()}")
    if skipped:
        report_lines.append(f"  (Skipped {skipped} PA(s) not matching market={market_filter!r})")
    report_lines.append(f"{'='*60}")

    for pa in pending_filtered:
        pa_id = pa.get("id", "?")
        pa_name = pa.get("name", "")[:50]
        old_level = pa.get("escalation", {}).get("level", "normal")

        new_level, days, reason = compute_new_level(pa, today)
        esc = update_escalation_field(pa, new_level, days, reason, today)

        level_changed = (new_level != old_level)
        is_blocking = esc.get("blocks_new_positions", False) and new_level in BLOCKING_LEVELS

        if new_level in BLOCKING_LEVELS:
            blocking_count += 1

        colour = level_colour(new_level)
        change_marker = " [CHANGED]" if level_changed else ""
        block_marker = " [BLOCKS NEW POSITIONS]" if is_blocking else ""

        line = (
            f"  {colour}{pa_id:<8}{RESET} "
            f"{colour}{new_level.upper():<8}{RESET} "
            f"days={days:<3} "
            f"clock={esc.get('clock_type','?'):<14} "
            f"{pa_name}"
            f"{change_marker}{block_marker}"
        )
        report_lines.append(line)

        if level_changed:
            changes.append((pa_id, old_level, new_level))

    report_lines.append(f"{'='*60}")

    if changes:
        report_lines.append(f"\n  LEVEL CHANGES ({len(changes)}):")
        for pa_id, old, new in changes:
            colour = level_colour(new)
            report_lines.append(f"    {pa_id}: {old.upper()} -> {colour}{new.upper()}{RESET}")

    if blocking_count > 0:
        report_lines.append(
            f"\n  {RED}{BOLD}BLOCKING: {blocking_count} PA(s) at CRITICAL/FORCE level.{RESET}"
        )
        report_lines.append(
            f"  {RED}New positions are BLOCKED until these are resolved or deferred.{RESET}"
        )
    else:
        report_lines.append(f"\n  {GREEN}No blocking escalations. New positions permitted.{RESET}")

    report_lines.append("")

    print("\n".join(report_lines))

    # Update meta
    data["_meta"]["last_updated"] = datetime.now(
        timezone(timedelta(hours=8))
    ).strftime("%Y-%m-%dT%H:%M:%S+08:00")

    if not dry_run:
        with pa_file.open("w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"[escalation_check] Saved updated escalation state to {pa_file}")
    else:
        print("[escalation_check] Dry-run mode: file NOT saved.")

    # Exit code 1 if any PA is at critical or force
    return 1 if blocking_count > 0 else 0


def main():
    parser = argparse.ArgumentParser(description="Escalation check for pending_actions.json")
    parser.add_argument(
        "--pa-file",
        default=None,
        help="Path to pending_actions.json (default: sim-portfolio/pending_actions.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print report but do not write updated file",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Override today's date (YYYY-MM-DD) for testing",
    )
    parser.add_argument(
        "--market",
        default=None,
        choices=["us", "astock"],
        help=(
            "Filter PAs by market: 'us' (US session) or 'astock' (A-share session). "
            "PAs tagged market='both' are always included. "
            "Legacy PAs without a market field are included in all filtered runs. "
            "Omit to process all PAs regardless of market."
        ),
    )
    args = parser.parse_args()

    # Resolve file path
    if args.pa_file:
        pa_file = Path(args.pa_file)
    else:
        # Locate relative to this script's parent (sim-portfolio/)
        script_dir = Path(__file__).resolve().parent
        pa_file = script_dir.parent / "pending_actions.json"

    # Resolve today
    if args.date:
        today = date.fromisoformat(args.date)
    else:
        today = date.today()

    exit_code = run_escalation_check(
        pa_file,
        today,
        dry_run=args.dry_run,
        market_filter=args.market,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()

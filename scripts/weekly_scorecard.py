#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
weekly_scorecard.py — Weekly Execution Scorecard Generator
Part of the Execution Forcing Infrastructure (execution_forcing.md §机制五)

Counts rules_written vs rules_executed this week, calculates the execution ratio,
and produces a scorecard with WARNING/BLOCKED status.

Writes: system-reform/scorecard_latest.json

Exit codes:
  0 — GREEN (ratio >= 0.5) or WARNING (0.3–0.5)
  1 — BLOCKED (ratio < 0.3)

Usage:
  python3 scripts/weekly_scorecard.py
  python3 scripts/weekly_scorecard.py --dry-run
  python3 scripts/weekly_scorecard.py --week 2026-W21
"""

import json
import sys
import os
import re
import argparse
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

RED    = "\033[91m"
YELLOW = "\033[93m"
GREEN  = "\033[92m"
BOLD   = "\033[1m"
RESET  = "\033[0m"


def get_week_bounds(ref_date: date) -> tuple[date, date]:
    """Return (monday, friday) for the ISO week containing ref_date."""
    monday = ref_date - timedelta(days=ref_date.weekday())
    friday = monday + timedelta(days=4)
    return monday, friday


def iso_week_id(ref_date: date) -> str:
    """Return 'YYYY-WNN' string for the week containing ref_date."""
    year, week, _ = ref_date.isocalendar()
    return f"{year}-W{week:02d}"


def git_log_since(since: date, until: date, repo_dir: Path) -> list[str]:
    """
    Return list of git log lines for commits between since and until (inclusive).
    Returns empty list if git is unavailable or repo not found.
    """
    try:
        result = subprocess.run(
            [
                "git", "log",
                f"--since={since.isoformat()}",
                f"--until={until.isoformat()} 23:59:59",
                "--name-only",
                "--pretty=format:COMMIT:%H %s",
            ],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            return result.stdout.splitlines()
    except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
        pass
    return []


def count_strategy_rule_changes(git_lines: list[str], repo_dir: Path) -> int:
    """
    Count new ## or **L rules added to strategy.md or US_TRADING_SYSTEM_V*.md
    by examining git diff for those files in this week's commits.
    """
    rules_added = 0
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "--all", "-1"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return 0

        # Files touched this week that are strategy/system files
        strategy_files_touched = set()
        for line in git_lines:
            if "strategy.md" in line or re.search(r"US_TRADING_SYSTEM_V\d+\.md", line):
                strategy_files_touched.add(line.strip())

        if not strategy_files_touched:
            return 0

        # Get diff for strategy-relevant files
        diff_result = subprocess.run(
            ["git", "diff", "HEAD~10", "HEAD", "--", "strategy.md"] +
            list(strategy_files_touched),
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if diff_result.returncode == 0:
            for line in diff_result.stdout.splitlines():
                if line.startswith("+") and not line.startswith("+++"):
                    stripped = line[1:].lstrip()
                    # Count new ## headings or **L{N} iron rules
                    if re.match(r"^## ", stripped) or re.match(r"^\*\*L\d+", stripped):
                        rules_added += 1
    except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
        pass
    return rules_added


def count_methodology_executions_written(pending_data: dict, week_start: date, week_end: date) -> int:
    """Count new methodology_execution PA entries created this week."""
    count = 0
    all_pas = pending_data.get("pending", []) + pending_data.get("completed", [])
    for pa in all_pas:
        if pa.get("type") != "methodology_execution":
            continue
        created_str = pa.get("created_at", "")
        if not created_str:
            continue
        try:
            created = date.fromisoformat(created_str[:10])
            if week_start <= created <= week_end:
                count += 1
        except ValueError:
            pass
    return count


def count_rules_executed(pending_data: dict, audit_dir: Path, week_start: date, week_end: date) -> int:
    """
    Count rules executed this week:
    - Completed PAs (non-trigger-gated) with completed_at in this week
    - Completed EX-{N} items inside methodology_execution entries
    - Audit trail files created this week (each file = 1 trade execution)
    """
    executed = 0

    # Completed PAs
    for pa in pending_data.get("completed", []):
        executed_at_str = pa.get("executed_at") or pa.get("completed_at", "")
        if not executed_at_str:
            continue
        clock_type = pa.get("escalation", {}).get("clock_type", "immediate")
        if clock_type == "trigger_gated":
            continue  # Excluded per spec
        try:
            exec_date = date.fromisoformat(executed_at_str[:10])
            if week_start <= exec_date <= week_end:
                executed += 1
        except ValueError:
            pass

    # Completed EX items inside methodology_execution PAs
    all_pas = pending_data.get("pending", []) + pending_data.get("completed", [])
    for pa in all_pas:
        if pa.get("type") != "methodology_execution":
            continue
        for item in pa.get("execution_items", []):
            if item.get("status") == "completed":
                completed_at_str = item.get("completed_at", "")
                if not completed_at_str:
                    continue
                try:
                    item_date = date.fromisoformat(completed_at_str[:10])
                    if week_start <= item_date <= week_end:
                        executed += 1
                except ValueError:
                    pass

    # Audit trail files
    if audit_dir.exists():
        for f in audit_dir.iterdir():
            if f.is_file() and f.suffix in (".json", ".md"):
                try:
                    mtime = date.fromtimestamp(f.stat().st_mtime)
                    if week_start <= mtime <= week_end:
                        executed += 1
                except OSError:
                    pass

    return executed


def count_pending_created_this_week(pending_data: dict, week_start: date, week_end: date) -> int:
    count = 0
    for pa in pending_data.get("pending", []) + pending_data.get("completed", []):
        created_str = pa.get("created_at", "")
        if not created_str:
            continue
        try:
            created = date.fromisoformat(created_str[:10])
            if week_start <= created <= week_end:
                count += 1
        except ValueError:
            pass
    return count


def count_pending_completed_this_week(pending_data: dict, week_start: date, week_end: date) -> int:
    count = 0
    for pa in pending_data.get("completed", []):
        exec_str = pa.get("executed_at") or pa.get("completed_at", "")
        if not exec_str:
            continue
        try:
            exec_date = date.fromisoformat(exec_str[:10])
            if week_start <= exec_date <= week_end:
                count += 1
        except ValueError:
            pass
    return count


def determine_flag(ratio: float) -> tuple[str, str, str]:
    """Returns (flag, flag_reason, colour)."""
    if ratio >= 0.5:
        return "GREEN", "执行率良好，可写新规则", GREEN
    elif ratio >= 0.3:
        return "WARNING", "执行率偏低（0.3–0.5），新规则写入时发出警告", YELLOW
    else:
        return "BLOCKED", f"执行率{ratio:.2f} < 0.3阈值，下周规则写作被阻断", RED + BOLD


def load_json_safe(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with path.open() as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_scorecard(
    repo_dir: Path,
    ref_date: date,
    dry_run: bool = False,
) -> int:
    week_start, week_end = get_week_bounds(ref_date)
    week_id = iso_week_id(ref_date)

    pa_file = repo_dir / "pending_actions.json"
    audit_dir = repo_dir / "audit-trail"
    output_file = repo_dir / "system-reform" / "scorecard_latest.json"

    pending_data = load_json_safe(pa_file)

    # --- Count rules_written ---
    git_lines = git_log_since(week_start, week_end, repo_dir)
    strategy_rules = count_strategy_rule_changes(git_lines, repo_dir)
    methodology_pas = count_methodology_executions_written(pending_data, week_start, week_end)
    # Also count new non-trigger-gated PAs as "rules written" (each PA is a pending rule to execute)
    new_immediate_pas = 0
    for pa in pending_data.get("pending", []):
        created_str = pa.get("created_at", "")
        clock_type = pa.get("escalation", {}).get("clock_type", "immediate")
        if clock_type == "immediate" and created_str:
            try:
                created = date.fromisoformat(created_str[:10])
                if week_start <= created <= week_end:
                    new_immediate_pas += 1
            except ValueError:
                pass

    rules_written = max(strategy_rules + methodology_pas + new_immediate_pas, 0)

    # --- Count rules_executed ---
    rules_executed = count_rules_executed(pending_data, audit_dir, week_start, week_end)

    # --- Ratio ---
    execution_ratio = round(rules_executed / max(rules_written, 1), 4)

    # --- Pending stats ---
    pending_created = count_pending_created_this_week(pending_data, week_start, week_end)
    pending_completed = count_pending_completed_this_week(pending_data, week_start, week_end)

    # --- Flag ---
    flag, flag_reason, colour = determine_flag(execution_ratio)
    next_week_rule_write_allowed = flag != "BLOCKED"

    # --- Build scorecard ---
    now_bj = datetime.now(timezone(timedelta(hours=8)))
    scorecard = {
        "current_week": {
            "week_id": week_id,
            "start_date": week_start.isoformat(),
            "end_date": week_end.isoformat(),
            "rules_written": rules_written,
            "rules_written_breakdown": {
                "strategy_rule_changes": strategy_rules,
                "methodology_execution_pas": methodology_pas,
                "new_immediate_pas": new_immediate_pas,
            },
            "rules_executed": rules_executed,
            "pending_created": pending_created,
            "pending_completed": pending_completed,
            "execution_ratio": execution_ratio,
            "flag": flag,
            "flag_reason": flag_reason,
            "generated_at": now_bj.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        },
        "next_week_rule_write_allowed": next_week_rule_write_allowed,
        "history": load_json_safe(output_file).get("history", []),
    }

    # Shift previous current_week into history (if it was a different week)
    prev = load_json_safe(output_file).get("current_week", {})
    if prev and prev.get("week_id") and prev["week_id"] != week_id:
        scorecard["history"].insert(0, prev)
        scorecard["history"] = scorecard["history"][:12]  # Keep last 12 weeks

    # --- Print report ---
    ratio_pct = f"{execution_ratio * 100:.0f}%"
    print(f"\n{'='*60}")
    print(f"  EXECUTION SCORECARD — {week_id} ({week_start} ~ {week_end})")
    print(f"{'='*60}")
    print(f"  {colour}{BOLD}执行率: {ratio_pct} — {flag}{RESET}")
    print(f"  {colour}{flag_reason}{RESET}")
    print()
    print(f"  {'指标':<25} {'本周':>6}")
    print(f"  {'-'*35}")
    print(f"  {'规则写入数':<25} {rules_written:>6}")
    print(f"    {'(策略规则变更)':<23} {strategy_rules:>6}")
    print(f"    {'(方法论执行PA)':<23} {methodology_pas:>6}")
    print(f"    {'(新即时PA)':<23} {new_immediate_pas:>6}")
    print(f"  {'规则执行数':<25} {rules_executed:>6}")
    print(f"  {'Pending创建':<25} {pending_created:>6}")
    print(f"  {'Pending完成':<25} {pending_completed:>6}")
    print()

    # List current blocking PAs
    blocking_pas = [
        p for p in pending_data.get("pending", [])
        if p.get("escalation", {}).get("level") in ("critical", "force")
        or p.get("escalation", {}).get("blocks_new_positions", False)
    ]
    if blocking_pas:
        print(f"  {RED}未执行阻断项 ({len(blocking_pas)}):{RESET}")
        for pa in blocking_pas:
            esc_level = pa.get("escalation", {}).get("level", "?").upper()
            print(f"    {RED}[{esc_level}]{RESET} {pa['id']}: {pa.get('name', '')[:55]}")
        print()

    if not next_week_rule_write_allowed:
        print(f"  {RED}{BOLD}下周规则写作: BLOCKED{RESET}")
        print(f"  {RED}必须先执行所有blocking PA才能解除阻断{RESET}")
    else:
        print(f"  {GREEN}下周规则写作: ALLOWED{RESET}")

    print(f"{'='*60}\n")

    # --- Save ---
    if not dry_run:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with output_file.open("w") as f:
            json.dump(scorecard, f, indent=2, ensure_ascii=False)
        print(f"[weekly_scorecard] Saved to {output_file}")
    else:
        print("[weekly_scorecard] Dry-run: file NOT saved.")

    return 1 if flag == "BLOCKED" else 0


def main():
    parser = argparse.ArgumentParser(description="Weekly execution scorecard for sim-portfolio")
    parser.add_argument(
        "--repo-dir",
        default=None,
        help="Path to sim-portfolio root directory (default: parent of this script)",
    )
    parser.add_argument(
        "--week",
        default=None,
        help="ISO week string like '2026-W21', or a date 'YYYY-MM-DD' within the target week",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print scorecard but do not write scorecard_latest.json",
    )
    args = parser.parse_args()

    # Resolve repo dir
    if args.repo_dir:
        repo_dir = Path(args.repo_dir).resolve()
    else:
        repo_dir = Path(__file__).resolve().parent.parent

    # Resolve reference date
    if args.week:
        # Accept 'YYYY-WNN' or 'YYYY-MM-DD'
        m = re.match(r"^(\d{4})-W(\d{1,2})$", args.week)
        if m:
            year, week_num = int(m.group(1)), int(m.group(2))
            ref_date = date.fromisocalendar(year, week_num, 1)  # Monday of that week
        else:
            ref_date = date.fromisoformat(args.week)
    else:
        ref_date = date.today()

    exit_code = run_scorecard(repo_dir, ref_date, dry_run=args.dry_run)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()

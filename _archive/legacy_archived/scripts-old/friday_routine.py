# /// script
# requires-python = ">=3.11"
# ///
"""
friday_routine.py — One-command Friday weekly review orchestrator
US trading system (§8 + §10 Discovery): 8-step sequence with timing and error handling.

Usage:
    uv run --script scripts/friday_routine.py              # full US routine
    uv run --script scripts/friday_routine.py --dry-run    # show order without executing
    uv run --script scripts/friday_routine.py --skip 3     # resume from step 4
    uv run --script scripts/friday_routine.py --market cn  # A-stock version
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Script root (always relative to this file, not cwd)
# ---------------------------------------------------------------------------
SCRIPTS_DIR = Path(__file__).parent.resolve()
REPO_DIR = SCRIPTS_DIR.parent

# ---------------------------------------------------------------------------
# Step definitions
# ---------------------------------------------------------------------------

# US routine: §10 mandates discovery BEFORE holdings review (conviction_check)
US_STEPS = [
    {
        "label": "update_prices.py",
        "script": "update_prices.py",
        "desc": "Refresh all prices → shared cache",
        "args": [],
    },
    {
        "label": "regime_detection.py",
        "script": "regime_detection.py",
        "desc": "Detect BULL/NEUTRAL/BEAR regime before screening",
        "args": [],
    },
    {
        "label": "conviction_check.py",
        "script": "conviction_check.py",
        "desc": "Generate Scorecard (Pain + Victory) before discovery",
        "args": [],
    },
    {
        "label": "discovery_scan.py",
        "script": "discovery_scan.py",
        "desc": "Thesis-agnostic scan — §10 requires this BEFORE holdings review",
        "args": [],
    },
    {
        "label": "rotation_scan.py",
        "script": "rotation_scan.py",
        "desc": "Check NVDA vs SOX sector rotation (§7)",
        "args": [],
    },
    {
        "label": "weekly_screen.py",
        "script": "weekly_screen.py",
        "desc": "Weekly screen with regime context (§8)",
        "args": [],
    },
    {
        "label": "pod_rebalance.py",
        "script": "pod_rebalance.py",
        "desc": "4-Pod rebalance audit",
        "args": [],
    },
    {
        "label": "anti_portfolio.py",
        "script": "anti_portfolio.py",
        "desc": "Anti-echo-chamber check — always last",
        "args": [],
    },
]

# CN (A-stock) routine
CN_STEPS = [
    {
        "label": "update_prices.py --market cn",
        "script": "update_prices.py",
        "desc": "Refresh A-stock prices",
        "args": ["--market", "cn"],
    },
    {
        "label": "sgrade_scanner.py",
        "script": "sgrade_scanner.py",
        "desc": "A-stock grade scanner",
        "args": [],
    },
    {
        "label": "conviction_check.py --market cn",
        "script": "conviction_check.py",
        "desc": "A-stock Conviction Scorecard",
        "args": ["--market", "cn"],
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fmt_duration(seconds: float) -> str:
    """Human-readable duration, e.g. 12.3s or 1m 05.2s."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    m = int(seconds // 60)
    s = seconds - m * 60
    return f"{m}m {s:04.1f}s"


def print_header(market: str, steps: list, skip: int, dry_run: bool) -> None:
    total = len(steps)
    effective = total - skip
    mode = "DRY RUN" if dry_run else "LIVE"
    print()
    print("=" * 65)
    print(f"  Friday Routine Orchestrator — {market.upper()} market  [{mode}]")
    print(f"  {total} steps total | skipping first {skip} | running {effective}")
    print("=" * 65)


def print_step_list(steps: list, skip: int) -> None:
    """Print the full ordered step list (used by --dry-run and always at start)."""
    print()
    for i, step in enumerate(steps):
        n = i + 1
        status = "  SKIP  " if i < skip else " QUEUED "
        print(f"  [{n}/{len(steps)}] [{status}] {step['label']}")
        print(f"          {step['desc']}")
    print()


def ask_continue() -> bool:
    """Prompt user to continue or abort after a step failure."""
    try:
        ans = input("  Continue to next step? [y/N] ").strip().lower()
        return ans in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


# ---------------------------------------------------------------------------
# Core runner
# ---------------------------------------------------------------------------

def run_steps(steps: list, skip: int, dry_run: bool) -> dict:
    """
    Execute each step in order. Returns a results dict:
        { step_index: {"label", "duration", "rc", "skipped"} }
    """
    results = {}
    total = len(steps)

    for i, step in enumerate(steps):
        n = i + 1
        label = step["label"]

        if i < skip:
            print(f"  [{n}/{total}] {label} ... SKIPPED")
            results[i] = {"label": label, "duration": 0.0, "rc": None, "skipped": True}
            continue

        script_path = str(SCRIPTS_DIR / step["script"])
        cmd = ["uv", "run", "--script", script_path] + step.get("args", [])

        print(f"  [{n}/{total}] {label} ...", end="", flush=True)

        if dry_run:
            print(f"  (dry-run, skipping)")
            results[i] = {"label": label, "duration": 0.0, "rc": 0, "skipped": False}
            continue

        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(REPO_DIR),
                capture_output=True,
                text=True,
            )
            elapsed = time.monotonic() - t0
            rc = proc.returncode
        except FileNotFoundError:
            elapsed = time.monotonic() - t0
            rc = 127
            proc = None

        results[i] = {"label": label, "duration": elapsed, "rc": rc, "skipped": False}

        if rc == 0:
            print(f" done ({fmt_duration(elapsed)})")
        else:
            print(f" FAILED (exit {rc}, {fmt_duration(elapsed)})")
            # Print captured output on failure
            if proc and proc.stdout.strip():
                print()
                print("  --- stdout ---")
                for line in proc.stdout.strip().splitlines()[-20:]:
                    print(f"    {line}")
            if proc and proc.stderr.strip():
                print()
                print("  --- stderr ---")
                for line in proc.stderr.strip().splitlines()[-20:]:
                    print(f"    {line}")
            print()
            if not ask_continue():
                print(f"\n  Aborted at step {n}/{total}.")
                # Mark remaining as not run
                for j in range(i + 1, total):
                    results[j] = {
                        "label": steps[j]["label"],
                        "duration": 0.0,
                        "rc": None,
                        "skipped": True,
                    }
                break

    return results


# ---------------------------------------------------------------------------
# Summary report
# ---------------------------------------------------------------------------

def print_summary(results: dict, total: int, dry_run: bool) -> None:
    print()
    print("=" * 65)
    print("  SUMMARY")
    print("=" * 65)

    ok = fail = skipped = 0
    total_time = 0.0

    for i in range(total):
        r = results.get(i)
        if r is None:
            continue
        label = r["label"]
        d = r["duration"]
        rc = r["rc"]

        if r["skipped"]:
            status = "SKIP "
            skipped += 1
        elif dry_run:
            status = "DRY  "
        elif rc == 0:
            status = "OK   "
            ok += 1
            total_time += d
        else:
            status = "FAIL "
            fail += 1
            total_time += d

        time_str = f"({fmt_duration(d)})" if d > 0 else ""
        print(f"  [{status}] {label} {time_str}")

    print()
    print(f"  Completed: {ok} ok / {fail} failed / {skipped} skipped")
    if total_time > 0:
        print(f"  Total wall time: {fmt_duration(total_time)}")
    print("=" * 65)
    print()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Friday weekly review orchestrator for sim-portfolio.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the execution order without running any script.",
    )
    p.add_argument(
        "--skip",
        type=int,
        default=0,
        metavar="N",
        help="Skip the first N steps (for resuming after a failure).",
    )
    p.add_argument(
        "--market",
        choices=["us", "cn"],
        default="us",
        help="Market: 'us' (default, 8-step routine) or 'cn' (A-stock, 3-step routine).",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()

    steps = US_STEPS if args.market == "us" else CN_STEPS
    total = len(steps)

    if args.skip < 0 or args.skip >= total:
        print(f"Error: --skip {args.skip} is out of range (0..{total - 1}).", file=sys.stderr)
        return 1

    print_header(args.market, steps, args.skip, args.dry_run)
    print_step_list(steps, args.skip)

    if args.dry_run:
        print("  [dry-run] No scripts will be executed.")
        print()
        return 0

    results = run_steps(steps, args.skip, dry_run=False)
    print_summary(results, total, dry_run=False)

    # Exit non-zero if any step failed
    failed = [r for r in results.values() if r.get("rc") not in (None, 0) and not r["skipped"]]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

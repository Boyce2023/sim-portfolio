# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
test_market_separation.py — Cross-contamination checker for A股/美股 system separation.

Verifies that each market's files contain only market-appropriate content.
Run with: uv run --script scripts/test_market_separation.py

Exit codes:
  0 = all checks PASS
  1 = one or more FAIL
"""

import re
import sys
from pathlib import Path

BASE = Path(__file__).parent.parent

# ── File paths ─────────────────────────────────────────────────────────────────
STRATEGY_MD         = BASE / "strategy.md"
US_SYSTEM_MD        = BASE / "research-notes/system-v4/US_TRADING_SYSTEM_V4.md"
QUICKREF_ASTOCK     = BASE / "system-reform/quickref-astock.md"
QUICKREF_US         = BASE / "system-reform/quickref-us.md"
PLAYBOOK_ASTOCK     = BASE / "system-reform/playbook-astock.md"
PLAYBOOK_US         = BASE / "system-reform/playbook-us.md"
CLAUDE_MD           = BASE / "CLAUDE.md"
PRE_SESSION_CHECK   = BASE / "scripts/pre_session_check.py"
COMPLIANCE_CHECK    = BASE / "scripts/compliance_check.py"

# ── Forbidden term sets ────────────────────────────────────────────────────────
# Terms that must NOT appear in A股 files
US_TERMS_FORBIDDEN_IN_ASTOCK = [
    "美股",
    "US ",       # word-boundary-like: "US " to avoid matching "US_TRADING_SYSTEM" in links
    r"\$150",    # $150K US account reference
    r"\$7,500",  # US minimum position
    "VIX",
    "Regime",
    r"\bshort\b",  # English "short" (do-not-check Chinese 空头 in A股 -- it may appear in ABCD context)
    "空头",
    "做空",
    "SPY",
    "US_TRADING_SYSTEM",
]

# Terms that must NOT appear in 美股 files
ASTOCK_TERMS_FORBIDDEN_IN_US = [
    "A股",
    "沪深300",
    "成交量",     # A股-specific volume indicator
    "市场呼吸",
    "T\\+1",
    "板块轮动",
    "涨停",
    "游资",
    "龙虎榜",
    "97分",
    "strategy\\.md",  # US system should not reference A股 doc
]

# Terms for playbook-astock: must NOT appear (US-specific)
US_TERMS_FORBIDDEN_IN_PLAYBOOK_ASTOCK = [
    "W3",
    "W4",
    "VIX",
    r"\bshort\b",
    "空头",
    r"[Rr]egime",
    r"\$7,?500",
]

# Terms for playbook-us: must NOT appear (A股-specific)
ASTOCK_TERMS_FORBIDDEN_IN_PLAYBOOK_US = [
    "W1",
    "W2",
    "成交量",
    "T\\+1",
    "市场呼吸",
    "板块",
]


# ── Helpers ────────────────────────────────────────────────────────────────────

def grep_file(path: Path, patterns: list[str]) -> list[tuple[int, str, str]]:
    """
    Grep a file for forbidden patterns.
    Returns list of (line_number, pattern, line_text) for each hit.
    """
    hits = []
    if not path.exists():
        return hits  # Missing file → handled separately
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    for line_no, line in enumerate(lines, start=1):
        for pat in patterns:
            if re.search(pat, line):
                hits.append((line_no, pat, line.strip()))
                break  # one hit per line is enough; don't double-count
    return hits


def check_file_exists(path: Path) -> bool:
    return path.exists()


def check_contains(path: Path, patterns: list[str]) -> list[str]:
    """Return patterns NOT found in file (for positive checks)."""
    if not path.exists():
        return patterns  # treat missing file as "nothing found"
    text = path.read_text(encoding="utf-8")
    missing = []
    for pat in patterns:
        if not re.search(pat, text):
            missing.append(pat)
    return missing


def check_not_contains(path: Path, patterns: list[str]) -> list[tuple[int, str, str]]:
    """Return list of hits (violations) for patterns that should NOT appear."""
    if not path.exists():
        return []  # missing file is handled by the caller
    return grep_file(path, patterns)


# ── Result tracking ─────────────────────────────────────────────────────────────

results: list[tuple[str, bool, list[str]]] = []
# Each entry: (label, passed, detail_lines)


def record(label: str, passed: bool, details: list[str]) -> None:
    results.append((label, passed, details))


# ── Individual checks ──────────────────────────────────────────────────────────

def check_strategy_md_purity() -> None:
    """Check 1: strategy.md must be pure A股 — no US terms."""
    label = "strategy.md (A股 purity)"
    if not check_file_exists(STRATEGY_MD):
        record(label, False, ["  FILE MISSING: strategy.md"])
        return

    hits = check_not_contains(STRATEGY_MD, US_TERMS_FORBIDDEN_IN_ASTOCK)

    if not hits:
        record(label, True, [f"  0 US terms found"])
    else:
        details = [f"  {len(hits)} US term(s) found:"]
        for (ln, pat, text) in hits:
            details.append(f"    Line {ln} [{pat!r}]: {text[:120]}")
        record(label, False, details)


def check_us_system_md_purity() -> None:
    """Check 2: US_TRADING_SYSTEM_V4.md must be pure 美股 — no A股 terms."""
    label = "US_TRADING_SYSTEM_V4.md (美股 purity)"
    if not check_file_exists(US_SYSTEM_MD):
        record(label, False, ["  FILE MISSING: US_TRADING_SYSTEM_V4.md"])
        return

    hits = check_not_contains(US_SYSTEM_MD, ASTOCK_TERMS_FORBIDDEN_IN_US)

    if not hits:
        record(label, True, [f"  0 A股 terms found"])
    else:
        details = [f"  {len(hits)} A股 term(s) found:"]
        for (ln, pat, text) in hits:
            details.append(f"    Line {ln} [{pat!r}]: {text[:120]}")
        record(label, False, details)


def check_quickref_astock() -> None:
    """Check 3: quickref-astock.md must have no US content."""
    label = "quickref-astock.md (A股 purity)"
    if not check_file_exists(QUICKREF_ASTOCK):
        record(label, False, ["  FILE MISSING: system-reform/quickref-astock.md"])
        return

    hits = check_not_contains(QUICKREF_ASTOCK, US_TERMS_FORBIDDEN_IN_ASTOCK)

    if not hits:
        record(label, True, [f"  0 US terms found"])
    else:
        details = [f"  {len(hits)} US term(s) found:"]
        for (ln, pat, text) in hits:
            details.append(f"    Line {ln} [{pat!r}]: {text[:120]}")
        record(label, False, details)


def check_quickref_us() -> None:
    """Check 4: quickref-us.md must have no A股 content."""
    label = "quickref-us.md (美股 purity)"
    if not check_file_exists(QUICKREF_US):
        record(label, False, ["  FILE MISSING: system-reform/quickref-us.md"])
        return

    hits = check_not_contains(QUICKREF_US, ASTOCK_TERMS_FORBIDDEN_IN_US)

    if not hits:
        record(label, True, [f"  0 A股 terms found"])
    else:
        details = [f"  {len(hits)} A股 term(s) found:"]
        for (ln, pat, text) in hits:
            details.append(f"    Line {ln} [{pat!r}]: {text[:120]}")
        record(label, False, details)


def check_playbook_astock() -> None:
    """Check 5: playbook-astock.md must have no US content."""
    label = "playbook-astock.md (A股 purity)"
    if not check_file_exists(PLAYBOOK_ASTOCK):
        record(label, False, ["  FILE MISSING: system-reform/playbook-astock.md"])
        return

    hits = check_not_contains(PLAYBOOK_ASTOCK, US_TERMS_FORBIDDEN_IN_PLAYBOOK_ASTOCK)

    if not hits:
        record(label, True, [f"  0 US terms found"])
    else:
        details = [f"  {len(hits)} US term(s) found:"]
        for (ln, pat, text) in hits:
            details.append(f"    Line {ln} [{pat!r}]: {text[:120]}")
        record(label, False, details)


def check_playbook_us() -> None:
    """Check 6: playbook-us.md must have no A股 content."""
    label = "playbook-us.md (美股 purity)"
    if not check_file_exists(PLAYBOOK_US):
        record(label, False, ["  FILE MISSING: system-reform/playbook-us.md"])
        return

    hits = check_not_contains(PLAYBOOK_US, ASTOCK_TERMS_FORBIDDEN_IN_PLAYBOOK_US)

    if not hits:
        record(label, True, [f"  0 A股 terms found"])
    else:
        details = [f"  {len(hits)} A股 term(s) found:"]
        for (ln, pat, text) in hits:
            details.append(f"    Line {ln} [{pat!r}]: {text[:120]}")
        record(label, False, details)


def check_claude_md_router() -> None:
    """Check 7: CLAUDE.md must be a clean router — routes both markets, states separation principle, no actual trading rules."""
    label = "CLAUDE.md router"
    if not check_file_exists(CLAUDE_MD):
        record(label, False, ["  FILE MISSING: CLAUDE.md"])
        return

    text = CLAUDE_MD.read_text(encoding="utf-8")
    details = []
    passed = True

    # Must route to A股 (W1 or strategy.md reference)
    routes_astock = bool(re.search(r"W1|strategy\.md", text))
    if not routes_astock:
        details.append("  FAIL: Must contain 'W1' or 'strategy.md' (A股 route)")
        passed = False

    # Must route to 美股 (W3 or US_TRADING_SYSTEM reference)
    routes_us = bool(re.search(r"W3|US_TRADING_SYSTEM", text))
    if not routes_us:
        details.append("  FAIL: Must contain 'W3' or 'US_TRADING_SYSTEM' (美股 route)")
        passed = False

    # Must contain market separation principle
    has_separation = bool(re.search(r"市场分离|market.*separ|A股.*美股.*独立|两个.*独立|分离原则", text, re.IGNORECASE))
    if not has_separation:
        details.append("  FAIL: Must contain separation principle (市场分离 or equivalent)")
        passed = False

    # Must NOT contain actual position-sizing numbers (these belong in strategy.md / US_TRADING_SYSTEM_V4.md)
    # Check for hard trading rule patterns that indicate trading rules are embedded in CLAUDE.md
    position_rule_patterns = [
        r"单只仓位.*\d+%",          # position size rules
        r"止损.*-\d+%",             # stop loss percentages
        r"bear case.*>\d+%.*不建仓",  # bear case hard cutoffs with specific percentages
    ]
    contamination_hits = []
    lines = text.splitlines()
    for line_no, line in enumerate(lines, start=1):
        for pat in position_rule_patterns:
            if re.search(pat, line):
                contamination_hits.append((line_no, pat, line.strip()))
                break

    if contamination_hits:
        details.append(f"  WARN: {len(contamination_hits)} embedded trading rule(s) found (should be in strategy.md/US_TRADING_SYSTEM_V4.md):")
        for (ln, pat, txt) in contamination_hits[:5]:  # show up to 5
            details.append(f"    Line {ln}: {txt[:100]}")
        # This is a warning, not a hard fail for the router check itself
        # The router can reference rules without being the authoritative source

    if passed:
        details.append(f"  Routes A股: {'YES' if routes_astock else 'NO'}")
        details.append(f"  Routes 美股: {'YES' if routes_us else 'NO'}")
        details.append(f"  Separation principle: {'YES' if has_separation else 'NO'}")

    record(label, passed, details)


def check_script_market_isolation() -> None:
    """Check 8: Scripts support --market flag for market isolation."""
    label = "Script market isolation"
    details = []
    passed = True

    # Check pre_session_check.py for --market flag
    if not check_file_exists(PRE_SESSION_CHECK):
        details.append("  FAIL: pre_session_check.py is MISSING")
        passed = False
    else:
        text = PRE_SESSION_CHECK.read_text(encoding="utf-8")
        has_market_flag = bool(re.search(r"['\"]--market['\"]", text))
        # Also accept --market in docstring/comments as documentation
        has_market_doc = bool(re.search(r"--market", text))
        if has_market_flag:
            details.append("  pre_session_check.py: --market flag implemented")
        elif has_market_doc:
            details.append("  pre_session_check.py: --market referenced in docs but NOT implemented as argparse argument")
            passed = False
        else:
            details.append("  FAIL: pre_session_check.py does NOT support --market flag")
            passed = False

    # Check compliance_check.py for --market flag
    if not check_file_exists(COMPLIANCE_CHECK):
        details.append("  FAIL: compliance_check.py is MISSING")
        passed = False
    else:
        text = COMPLIANCE_CHECK.read_text(encoding="utf-8")
        has_market_flag = bool(re.search(r"['\"]--market['\"]", text))
        has_market_doc = bool(re.search(r"--market", text))
        if has_market_flag:
            details.append("  compliance_check.py: --market flag implemented")
        elif has_market_doc:
            details.append("  compliance_check.py: --market referenced in docs but NOT implemented as argparse argument")
            passed = False
        else:
            details.append("  FAIL: compliance_check.py does NOT support --market flag")
            passed = False

    record(label, passed, details)


# ── Main ────────────────────────────────────────────────────────────────────────

def main() -> int:
    print()
    print("═══ MARKET SEPARATION TEST ═══")
    print()

    # Run all checks
    check_strategy_md_purity()
    check_us_system_md_purity()
    check_quickref_astock()
    check_quickref_us()
    check_playbook_astock()
    check_playbook_us()
    check_claude_md_router()
    check_script_market_isolation()

    # Print results
    passed_count = 0
    total_count = len(results)

    for label, passed, details in results:
        status = "PASS ✓" if passed else "FAIL ✗"
        print(f"{label}: {status}")
        for line in details:
            print(line)
        if passed:
            passed_count += 1
        print()

    # Summary
    all_pass = passed_count == total_count
    if all_pass:
        print(f"TOTAL: {passed_count}/{total_count} PASS — Market separation is CLEAN")
    else:
        failed = total_count - passed_count
        print(f"TOTAL: {passed_count}/{total_count} PASS — {failed} FAIL(s) detected")
        print()
        print("Wave 2 cleanup required for failed checks.")

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())

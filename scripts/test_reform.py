#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
test_reform.py — Integration Test: Anti-Paralysis Reform End-to-End Verification
=================================================================================
Tests the entire reform infrastructure introduced in system-reform/:
  - strategy-quickref.md
  - session_playbooks.md
  - rule_authority.md
  - conflict_resolution.md
  - execution_forcing.md
  - All spec files (specs/)
  - pre_session_check.py (via spec + executable check)
  - compliance_check.py
  - escalation_check.py
  - strategy.md structure
  - CLAUDE.md structure
  - US_TRADING_SYSTEM_V4.md structure
  - Cross-file constant consistency (max 9 positions, short 5%, bear case 35%)

Run:
  python3 scripts/test_reform.py

Exit code:
  0 — all tests passed
  1 — one or more tests failed
"""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SIM_ROOT   = Path(__file__).parent.parent
REFORM_DIR = SIM_ROOT / "system-reform"
SPECS_DIR  = REFORM_DIR / "specs"
SCRIPTS    = SIM_ROOT / "scripts"
PORTFOLIO  = SIM_ROOT / "portfolio_state.json"
PENDING    = SIM_ROOT / "pending_actions.json"

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

results: list[tuple[str, bool, str]] = []  # (test_name, passed, detail)


def record(name: str, passed: bool, detail: str = "") -> bool:
    status = f"{GREEN}PASS{RESET}" if passed else f"{RED}FAIL{RESET}"
    print(f"  {status}  {name}" + (f"\n        {YELLOW}{detail}{RESET}" if detail and not passed else ""))
    results.append((name, passed, detail))
    return passed


# ---------------------------------------------------------------------------
# Helper: run subprocess and capture output
# ---------------------------------------------------------------------------
def run(cmd: list[str], timeout: int = 30) -> tuple[int, str, str]:
    """Returns (returncode, stdout, stderr)."""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"TIMEOUT after {timeout}s"
    except FileNotFoundError as e:
        return -1, "", str(e)


# ===========================================================================
# 1. FILE EXISTENCE CHECKS
# ===========================================================================
print(f"\n{BOLD}═══════════════════════════════════════════════════════════════{RESET}")
print(f"{BOLD}1. FILE EXISTENCE CHECKS{RESET}")
print(f"{BOLD}═══════════════════════════════════════════════════════════════{RESET}")

# Core reform docs
reform_files = [
    ("strategy-quickref.md",      REFORM_DIR / "strategy-quickref.md"),
    ("session_playbooks.md",       REFORM_DIR / "session_playbooks.md"),
    ("rule_authority.md",          REFORM_DIR / "rule_authority.md"),
    ("conflict_resolution.md",     REFORM_DIR / "conflict_resolution.md"),
    ("execution_forcing.md",       REFORM_DIR / "execution_forcing.md"),
]
for label, path in reform_files:
    exists = path.exists() and path.stat().st_size > 0
    record(f"reform/{label} exists and non-empty", exists,
           detail=f"Path: {path}" if not exists else "")

# Spec files
spec_files = [
    ("specs/pre_session_check_spec.md",    SPECS_DIR / "pre_session_check_spec.md"),
    ("specs/compliance_check_spec.md",     SPECS_DIR / "compliance_check_spec.md"),
    ("specs/strategy_restructure_spec.md", SPECS_DIR / "strategy_restructure_spec.md"),
    ("specs/us_system_consolidation_spec.md", SPECS_DIR / "us_system_consolidation_spec.md"),
    ("specs/claude_md_streamline_spec.md", SPECS_DIR / "claude_md_streamline_spec.md"),
]
for label, path in spec_files:
    exists = path.exists() and path.stat().st_size > 0
    record(f"{label} exists", exists, detail=str(path) if not exists else "")


# ===========================================================================
# 2. pre_session_check.py VERIFICATION
# ===========================================================================
print(f"\n{BOLD}═══════════════════════════════════════════════════════════════{RESET}")
print(f"{BOLD}2. pre_session_check.py VERIFICATION{RESET}")
print(f"{BOLD}═══════════════════════════════════════════════════════════════{RESET}")

PSC_PATH = SCRIPTS / "pre_session_check.py"

# 2a. Script exists
psc_exists = PSC_PATH.exists()
record("pre_session_check.py exists", psc_exists,
       detail="Expected at scripts/pre_session_check.py — not yet created (see specs/pre_session_check_spec.md)" if not psc_exists else "")

# 2b. Script is executable (auto-fix: chmod +x if file exists but lacks exec bit)
if psc_exists:
    mode = PSC_PATH.stat().st_mode
    is_exec = bool(mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
    if not is_exec:
        # Auto-remediate: set executable bit
        PSC_PATH.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        is_exec = True
        print(f"  {YELLOW}(auto-fix){RESET} chmod +x applied to pre_session_check.py")
    record("pre_session_check.py is executable", is_exec,
           detail=f"Run: chmod +x {PSC_PATH}" if not is_exec else "")
else:
    record("pre_session_check.py is executable", False,
           detail="Cannot check — script does not exist")

# 2c. Returns exit code 1 (BLOCKED) with current portfolio state
if psc_exists:
    uv_bin = Path.home() / ".local/bin/uv"
    if not uv_bin.exists():
        uv_bin = Path("/usr/local/bin/uv")
    cmd = [str(uv_bin), "run", "--script", str(PSC_PATH)]
    code, stdout, stderr = run(cmd, timeout=60)
    combined = stdout + stderr
    record("pre_session_check exits with code 1 (BLOCKED)", code == 1,
           detail=f"Got exit code {code}. Expected 1 (BLOCKED due to L16+L18 violations)")

    # 2d. Output mentions "US positions: 11"
    has_pos_11 = "US positions: 11" in combined
    record('pre_session_check output contains "US positions: 11"', has_pos_11,
           detail=f"Output snippet: {combined[:400]!r}" if not has_pos_11 else "")

    # 2e. Output mentions "Short exposure: 0%"
    has_short_0 = "Short exposure: 0" in combined
    record('pre_session_check output contains "Short exposure: 0%"', has_short_0,
           detail=f"Output snippet: {combined[:400]!r}" if not has_short_0 else "")
else:
    record("pre_session_check exits with code 1 (BLOCKED)", False,
           detail="Cannot run — script does not exist")
    record('pre_session_check output contains "US positions: 11"', False,
           detail="Cannot run — script does not exist")
    record('pre_session_check output contains "Short exposure: 0%"', False,
           detail="Cannot run — script does not exist")


# ===========================================================================
# 3. compliance_check.py VERIFICATION
# ===========================================================================
print(f"\n{BOLD}═══════════════════════════════════════════════════════════════{RESET}")
print(f"{BOLD}3. compliance_check.py VERIFICATION{RESET}")
print(f"{BOLD}═══════════════════════════════════════════════════════════════{RESET}")

CC_PATH = SCRIPTS / "compliance_check.py"

cc_exists = CC_PATH.exists()
record("compliance_check.py exists", cc_exists,
       detail="Expected at scripts/compliance_check.py — not yet created (see specs/compliance_check_spec.md)" if not cc_exists else "")

if cc_exists:
    uv_bin = Path.home() / ".local/bin/uv"
    if not uv_bin.exists():
        uv_bin = Path("/usr/local/bin/uv")
    cmd = [str(uv_bin), "run", "--script", str(CC_PATH), "--post-trade"]
    code, stdout, stderr = run(cmd, timeout=60)
    combined = stdout + stderr

    # 3b. Returns non-zero (violations detected)
    record("compliance_check --post-trade returns non-zero (violations)", code != 0,
           detail=f"Got exit code {code}. Expected non-zero (L16+L18 violations active)")

    # 3c. Detects L16 violation
    has_l16 = "L16" in combined
    record("compliance_check detects L16 violation", has_l16,
           detail=f"Output: {combined[:300]!r}" if not has_l16 else "")

    # 3d. Detects L18 violation
    has_l18 = "L18" in combined
    record("compliance_check detects L18 violation", has_l18,
           detail=f"Output: {combined[:300]!r}" if not has_l18 else "")
else:
    record("compliance_check --post-trade returns non-zero (violations)", False,
           detail="Cannot run — script does not exist")
    record("compliance_check detects L16 violation", False,
           detail="Cannot run — script does not exist")
    record("compliance_check detects L18 violation", False,
           detail="Cannot run — script does not exist")


# ===========================================================================
# 4. escalation_check.py VERIFICATION
# ===========================================================================
print(f"\n{BOLD}═══════════════════════════════════════════════════════════════{RESET}")
print(f"{BOLD}4. escalation_check.py VERIFICATION{RESET}")
print(f"{BOLD}═══════════════════════════════════════════════════════════════{RESET}")

ESC_PATH = SCRIPTS / "escalation_check.py"

esc_exists = ESC_PATH.exists()
record("escalation_check.py exists", esc_exists,
       detail="Expected at scripts/escalation_check.py" if not esc_exists else "")

if esc_exists:
    uv_bin = Path.home() / ".local/bin/uv"
    if not uv_bin.exists():
        uv_bin = Path("/usr/local/bin/uv")
    cmd = [
        str(uv_bin), "run", "--script", str(ESC_PATH),
        "--dry-run", "--pa-file", str(PENDING),
    ]
    code, stdout, stderr = run(cmd, timeout=60)
    combined = stdout + stderr

    # 4b. Does not crash (exit code 0 or 1; -1 = crash/timeout)
    no_crash = code in (0, 1)
    record("escalation_check runs without crash (exit 0 or 1)", no_crash,
           detail=f"Exit code: {code}. stderr: {stderr[:200]!r}" if not no_crash else "")

    # 4c. Processes pending_actions.json entries (output contains PA IDs)
    has_pa = "PA-" in combined
    record("escalation_check processes pending_actions.json (PA- entries visible)", has_pa,
           detail=f"Output snippet: {combined[:300]!r}" if not has_pa else "")
else:
    record("escalation_check runs without crash (exit 0 or 1)", False,
           detail="Cannot run — script does not exist")
    record("escalation_check processes pending_actions.json (PA- entries visible)", False,
           detail="Cannot run — script does not exist")


# ===========================================================================
# 5. strategy.md STRUCTURE VERIFICATION
# ===========================================================================
print(f"\n{BOLD}═══════════════════════════════════════════════════════════════{RESET}")
print(f"{BOLD}5. strategy.md STRUCTURE VERIFICATION{RESET}")
print(f"{BOLD}═══════════════════════════════════════════════════════════════{RESET}")

STRATEGY = SIM_ROOT / "strategy.md"

strat_exists = STRATEGY.exists()
record("strategy.md exists", strat_exists, detail=str(STRATEGY) if not strat_exists else "")

if strat_exists:
    strategy_text = STRATEGY.read_text(encoding="utf-8")
    lines = strategy_text.splitlines()

    # 5b. Contains "<!-- LAYER 0: CRITICAL -->" marker
    has_layer0 = "<!-- LAYER 0: CRITICAL" in strategy_text
    record('strategy.md contains "<!-- LAYER 0: CRITICAL -->" marker', has_layer0,
           detail="Reform spec (strategy_restructure_spec.md) requires LAYER 0 section. "
                  "strategy.md is currently v5.0; v6.0 restructure adds this marker." if not has_layer0 else "")

    # 5c. §0 appears within first 30 lines
    first_30 = "\n".join(lines[:30])
    has_sec0 = "§0" in first_30
    record("strategy.md §0 section exists within first 30 lines", has_sec0,
           detail=f"First 30 lines do not contain §0. Current first line: {lines[0]!r}" if not has_sec0 else "")

    # 5d. §1 Daily Execution section exists (anywhere in file)
    has_sec1 = "§1" in strategy_text and "Daily Execution" in strategy_text
    record("strategy.md §1 Daily Execution section exists", has_sec1,
           detail="Expected '§1' with 'Daily Execution' — from strategy_restructure_spec Layer 1" if not has_sec1 else "")
else:
    record('strategy.md contains "<!-- LAYER 0: CRITICAL -->" marker', False,
           detail="File missing")
    record("strategy.md §0 section exists within first 30 lines", False,
           detail="File missing")
    record("strategy.md §1 Daily Execution section exists", False,
           detail="File missing")


# ===========================================================================
# 6. CLAUDE.md VERIFICATION
# ===========================================================================
print(f"\n{BOLD}═══════════════════════════════════════════════════════════════{RESET}")
print(f"{BOLD}6. CLAUDE.md VERIFICATION{RESET}")
print(f"{BOLD}═══════════════════════════════════════════════════════════════{RESET}")

CLAUDE_MD = SIM_ROOT / "CLAUDE.md"

claude_exists = CLAUDE_MD.exists()
record("CLAUDE.md exists", claude_exists, detail=str(CLAUDE_MD) if not claude_exists else "")

if claude_exists:
    claude_text = CLAUDE_MD.read_text(encoding="utf-8")
    claude_lines = claude_text.splitlines()

    # 6b. Contains pre_session_check.py reference
    has_psc_ref = "pre_session_check.py" in claude_text
    record('CLAUDE.md contains "pre_session_check.py" reference', has_psc_ref,
           detail="claude_md_streamline_spec.md requires pre_session_check.py as STEP 0" if not has_psc_ref else "")

    # 6c. ≤200 lines
    line_count = len(claude_lines)
    is_concise = line_count <= 200
    record(f"CLAUDE.md is ≤200 lines (current: {line_count})", is_concise,
           detail=f"Current: {line_count} lines. claude_md_streamline_spec.md targets ≤200" if not is_concise else "")

    # 6d. L1 through L18 all present
    missing_lrules = []
    for n in range(1, 19):
        # Match L<n> followed by word boundary char (space, pipe, |, newline)
        lrule = f"L{n}"
        if lrule not in claude_text:
            missing_lrules.append(lrule)
    has_all_l_rules = len(missing_lrules) == 0
    record(f"CLAUDE.md contains L1 through L18", has_all_l_rules,
           detail=f"Missing: {', '.join(missing_lrules)}" if missing_lrules else "")
else:
    record('CLAUDE.md contains "pre_session_check.py" reference', False, "File missing")
    record("CLAUDE.md is ≤200 lines", False, "File missing")
    record("CLAUDE.md contains L1 through L18", False, "File missing")


# ===========================================================================
# 7. US_TRADING_SYSTEM_V4.md VERIFICATION
# ===========================================================================
print(f"\n{BOLD}═══════════════════════════════════════════════════════════════{RESET}")
print(f"{BOLD}7. US_TRADING_SYSTEM_V4.md VERIFICATION{RESET}")
print(f"{BOLD}═══════════════════════════════════════════════════════════════{RESET}")

V4_PATH = SIM_ROOT / "research-notes" / "system-v4" / "US_TRADING_SYSTEM_V4.md"

v4_exists = V4_PATH.exists()
record("US_TRADING_SYSTEM_V4.md exists", v4_exists, detail=str(V4_PATH) if not v4_exists else "")

if v4_exists:
    v4_text = V4_PATH.read_text(encoding="utf-8")

    # 7b. Contains "<!-- LAYER 0: CRITICAL" marker
    has_layer0 = "<!-- LAYER 0: CRITICAL" in v4_text
    record('US_TRADING_SYSTEM_V4.md contains "<!-- LAYER 0: CRITICAL" marker', has_layer0,
           detail="Expected HTML comment marker at top of file" if not has_layer0 else "")

    # 7c. Contains inlined position sizing table
    # The table appears around line 10-20 with §0.5 Quick Position Sizing Reference
    has_sizing = "Quick Position Sizing" in v4_text or "| **S** |" in v4_text
    record("US_TRADING_SYSTEM_V4.md contains inlined position sizing table", has_sizing,
           detail="Expected §0.5 Quick Position Sizing Reference table" if not has_sizing else "")
else:
    record('US_TRADING_SYSTEM_V4.md contains "<!-- LAYER 0: CRITICAL" marker', False, "File missing")
    record("US_TRADING_SYSTEM_V4.md contains inlined position sizing table", False, "File missing")


# ===========================================================================
# 8. CROSS-FILE CONSTANT CONSISTENCY
# ===========================================================================
print(f"\n{BOLD}═══════════════════════════════════════════════════════════════{RESET}")
print(f"{BOLD}8. CROSS-FILE CONSTANT CONSISTENCY{RESET}")
print(f"{BOLD}═══════════════════════════════════════════════════════════════{RESET}")

QUICKREF_PATH = REFORM_DIR / "strategy-quickref.md"
EXEC_TRADE    = SCRIPTS / "execute_trade.py"
PRE_SESSION_SPEC = SPECS_DIR / "pre_session_check_spec.md"
COMPLIANCE_SPEC  = SPECS_DIR / "compliance_check_spec.md"

# ── 8a. Max US Positions = 9 ──────────────────────────────────────────────
print(f"\n  {CYAN}Max US positions (should be 9 everywhere):{RESET}")

quickref_9 = QUICKREF_PATH.exists() and "≤9" in QUICKREF_PATH.read_text(encoding="utf-8")
record("strategy-quickref.md says max 9 US positions (≤9)", quickref_9,
       detail="Expected '≤9' in US持仓上限速查 table" if not quickref_9 else "")

exec_9 = False
if EXEC_TRADE.exists():
    et_text = EXEC_TRADE.read_text(encoding="utf-8")
    exec_9 = ">= 9" in et_text or "current_us_longs >= 9" in et_text
record("execute_trade.py enforces 9-position limit (current_us_longs >= 9)", exec_9,
       detail="grep for 'current_us_longs >= 9' in execute_trade.py" if not exec_9 else "")

spec_9 = PRE_SESSION_SPEC.exists() and "US_MAX_POSITIONS       = 9" in PRE_SESSION_SPEC.read_text(encoding="utf-8")
record("pre_session_check_spec.md defines US_MAX_POSITIONS = 9", spec_9,
       detail="Expected 'US_MAX_POSITIONS       = 9' in spec constants section" if not spec_9 else "")

compliance_9 = COMPLIANCE_SPEC.exists() and "MAX_US_LONG_POSITIONS   = 9" in COMPLIANCE_SPEC.read_text(encoding="utf-8")
record("compliance_check_spec.md defines MAX_US_LONG_POSITIONS = 9", compliance_9,
       detail="Expected 'MAX_US_LONG_POSITIONS   = 9' in spec constants section" if not compliance_9 else "")

# ── 8b. Short Minimum = 5% ────────────────────────────────────────────────
print(f"\n  {CYAN}Short minimum floor (should be 5% everywhere):{RESET}")

quickref_5pct = QUICKREF_PATH.exists() and "5%" in QUICKREF_PATH.read_text(encoding="utf-8")
record("strategy-quickref.md references 5% short floor", quickref_5pct,
       detail="Check 空头单只上限 5% or short floor references" if not quickref_5pct else "")

spec_5pct = PRE_SESSION_SPEC.exists() and "US_MIN_SHORT_PCT       = 0.05" in PRE_SESSION_SPEC.read_text(encoding="utf-8")
record("pre_session_check_spec.md defines US_MIN_SHORT_PCT = 0.05", spec_5pct,
       detail="Expected 'US_MIN_SHORT_PCT       = 0.05' in spec constants" if not spec_5pct else "")

compliance_5pct = COMPLIANCE_SPEC.exists() and "SHORT_HARD_FLOOR_PCT   = 0.05" in COMPLIANCE_SPEC.read_text(encoding="utf-8")
record("compliance_check_spec.md defines SHORT_HARD_FLOOR_PCT = 0.05", compliance_5pct,
       detail="Expected 'SHORT_HARD_FLOOR_PCT   = 0.05' in spec constants" if not compliance_5pct else "")

# ── 8c. Bear Case Threshold = 35% for US ──────────────────────────────────
print(f"\n  {CYAN}Bear case threshold for US (should be 35% everywhere):{RESET}")

quickref_35 = QUICKREF_PATH.exists() and "35%" in QUICKREF_PATH.read_text(encoding="utf-8")
record("strategy-quickref.md mentions 35% US bear case threshold", quickref_35,
       detail="Expected '美股Bear case≤35%' in quickref" if not quickref_35 else "")

exec_35 = EXEC_TRADE.exists() and "< -0.35" in EXEC_TRADE.read_text(encoding="utf-8")
record("execute_trade.py enforces 35% bear case hard block (bear_case_downside < -0.35)", exec_35,
       detail="Expected 'if bear_case_downside < -0.35:' in execute_trade.py" if not exec_35 else "")

# pre_session_check_spec checks bear_case documentation (string non-empty), not the 35% threshold;
# the 35% enforcement lives in execute_trade.py. Verify spec documents bear_case checking at all.
spec_35 = PRE_SESSION_SPEC.exists() and "bear_case" in PRE_SESSION_SPEC.read_text(encoding="utf-8")
record("pre_session_check_spec.md contains bear_case documentation check", spec_35,
       detail="Expected 'bear_case' references (BEAR_CASE_DOCUMENTED check) in spec" if not spec_35 else "")


# ===========================================================================
# SUMMARY
# ===========================================================================
print(f"\n{BOLD}═══════════════════════════════════════════════════════════════{RESET}")
print(f"{BOLD}SUMMARY{RESET}")
print(f"{BOLD}═══════════════════════════════════════════════════════════════{RESET}")

total   = len(results)
passed  = sum(1 for _, p, _ in results if p)
failed  = total - passed

print(f"\n  Total:  {total}")
print(f"  {GREEN}Passed: {passed}{RESET}")
print(f"  {RED if failed else GREEN}Failed: {failed}{RESET}")

if failed > 0:
    print(f"\n  {RED}{BOLD}FAILED TESTS:{RESET}")
    for name, ok, detail in results:
        if not ok:
            print(f"    {RED}✗{RESET} {name}")
            if detail:
                print(f"      {YELLOW}→ {detail}{RESET}")

    print(f"\n  {YELLOW}KEY ACTION ITEMS:{RESET}")
    # Identify which scripts are missing and point to specs
    if not (SCRIPTS / "pre_session_check.py").exists():
        print(f"    1. Create scripts/pre_session_check.py")
        print(f"       Spec: {SPECS_DIR}/pre_session_check_spec.md")
    if not (SCRIPTS / "compliance_check.py").exists():
        print(f"    2. Create scripts/compliance_check.py")
        print(f"       Spec: {SPECS_DIR}/compliance_check_spec.md")
    strat_path = SIM_ROOT / "strategy.md"
    if strat_path.exists() and "<!-- LAYER 0: CRITICAL" not in strat_path.read_text():
        print(f"    3. Restructure strategy.md v5.0 → v6.0 (add LAYER 0/1/2 markers)")
        print(f"       Spec: {SPECS_DIR}/strategy_restructure_spec.md")

print()

sys.exit(0 if failed == 0 else 1)

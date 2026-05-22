# compliance_check.py — Design Specification

**Version**: 1.0  
**Date**: 2026-05-22  
**Target path**: `/Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts/compliance_check.py`  
**Rules enforced**: L16 (Shotgun Ban), L17 (Regime Awareness), L18 (Short Quota)

---

## 1. Purpose and Execution Model

`compliance_check.py` is a **post-trade enforcement script** that runs automatically after every `execute_trade.py` invocation. It reads the current `portfolio_state.json`, evaluates three behavioral rules, writes violations to `pending_actions.json`, and exits with a non-zero code if any CRITICAL violation is detected — allowing `execute_trade.py` to surface the alert to the agent session.

It is also callable independently (e.g., session startup L17 check, daily cron, or manual audit).

---

## 2. Integration with execute_trade.py

### Hook location

Insert immediately after the `save_portfolio_atomic(state)` call in `execute_trade.py`, before the audit trail block (line ~811). Pattern mirrors the existing `sync_nexus.py` hook:

```python
# --- Compliance check (post-trade) ---
try:
    compliance_script = Path(__file__).parent / "compliance_check.py"
    if compliance_script.exists():
        result = subprocess.run(
            ["/Users/huaichuaibeimeng/.local/bin/uv", "run", "--script",
             str(compliance_script), "--post-trade", "--account", account_key],
            check=False, timeout=30, capture_output=False
        )
        if result.returncode == 2:
            # returncode 2 = CRITICAL (L18 long-block active)
            print("[COMPLIANCE] CRITICAL violation active — review pending_actions.json before next trade")
        elif result.returncode == 1:
            print("[COMPLIANCE] Violation(s) detected — review pending_actions.json")
except Exception as _comp_err:
    print(f"[WARN] compliance_check failed (non-blocking): {_comp_err}")
```

**Exit codes**:
- `0` — fully compliant
- `1` — WARNING or NOTICE violations exist (non-blocking)
- `2` — CRITICAL violation (L18 long-block active; next long buy should be manually reconsidered)

---

## 3. Script Header and Dependencies

```python
# /// script
# requires-python = ">=3.11"
# dependencies = ["yfinance>=0.2.40"]
# ///
"""
Post-trade compliance enforcement for L16, L17, L18.

Usage:
  uv run --script scripts/compliance_check.py                  # full check
  uv run --script scripts/compliance_check.py --post-trade     # post-trade hook (faster, no regime fetch)
  uv run --script scripts/compliance_check.py --account us     # US account only
  uv run --script scripts/compliance_check.py --regime-only    # L17 check only
  uv run --script scripts/compliance_check.py --summary        # machine-readable JSON summary
"""
```

---

## 4. Module-Level Constants

```python
PORTFOLIO_PATH   = Path(__file__).parent.parent / "portfolio_state.json"
PENDING_PATH     = Path(__file__).parent.parent / "pending_actions.json"
WATCHLIST_PATH   = Path(__file__).parent.parent / "watchlist_config.json"
REGIME_JSON      = Path.home() / ".claude/nexus/truth/macro/regime.json"
MACRO_EVENTS_PATH = Path(__file__).parent.parent / "market_calendar.json"

# L16 thresholds
MAX_US_LONG_POSITIONS   = 9      # includes longs only, not shorts
MIN_POSITION_VALUE_USD  = 7500   # hard floor per L16

# L17 thresholds
VIX_DELTA_5D_SIGNAL    = 3.0    # points; triggers regime check requirement
REGIME_ADJUST_WINDOW_H = 24     # hours after regime shift to require portfolio adjustment

# L18 thresholds
SHORT_TARGET_MIN_PCT   = 0.10   # 10% of US total_assets
SHORT_TARGET_MAX_PCT   = 0.15   # 15% of US total_assets
SHORT_HARD_FLOOR_PCT   = 0.05   # 5% minimum
CRITICAL_DAYS_NO_SHORT = 5      # consecutive trading days; triggers long-block

TZ_BEIJING = timezone(timedelta(hours=8))
```

---

## 5. Core Data Structures

### 5.1 ViolationRecord (written to pending_actions.json)

```json
{
  "id": "COMP-L16-20260522-001",
  "type": "compliance_violation",
  "rule": "L16",
  "severity": "WARNING",
  "ticker": "FPS",
  "account": "us",
  "detected_at": "2026-05-22T22:15:00+08:00",
  "status": "pending",
  "priority": "high",
  "description": "Position FPS ($6,792) below minimum $7,500",
  "action_required": "Sell FPS ($6,792) OR add $708 to reach minimum $7,500",
  "deadline": "2026-05-23T22:15:00+08:00",
  "consecutive_days": 1,
  "auto_generated": true
}
```

**Field definitions**:

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Format: `COMP-{RULE}-{YYYYMMDD}-{NNN}` (NNN = 3-digit sequence within day) |
| `type` | `"compliance_violation"` | Fixed string to distinguish from manual pending_actions |
| `rule` | `"L16" \| "L17" \| "L18"` | Rule violated |
| `severity` | `"CRITICAL" \| "WARNING" \| "NOTICE"` | See §8 for mapping |
| `ticker` | `str \| null` | Affected ticker, or null for portfolio-level rules |
| `account` | `"us" \| "a_share"` | Account scope |
| `detected_at` | ISO8601+TZ | Timestamp of detection |
| `status` | `"pending" \| "acknowledged" \| "resolved"` | Lifecycle |
| `priority` | `"urgent" \| "high" \| "medium"` | Maps from severity |
| `description` | `str` | Human-readable violation description |
| `action_required` | `str` | Specific, actionable instruction |
| `deadline` | ISO8601+TZ \| `null` | When action must be completed |
| `consecutive_days` | `int` | How many consecutive days this rule has been violated |
| `auto_generated` | `true` | Always true for compliance violations |

### 5.2 ComplianceReport (stdout JSON with --summary flag)

```json
{
  "timestamp": "2026-05-22T22:15:00+08:00",
  "overall_status": "CRITICAL",
  "l16": {
    "status": "VIOLATION",
    "position_count": 11,
    "max_allowed": 9,
    "positions_to_close": ["FPS", "COPX"],
    "undersized_positions": [
      {"ticker": "FPS",  "value": 6792.80, "shortfall": 707.20},
      {"ticker": "CRM",  "value": 2997.27, "shortfall": 4502.73},
      {"ticker": "DG",   "value": 2943.08, "shortfall": 4556.92},
      {"ticker": "COPX", "value": 2988.72, "shortfall": 4511.28}
    ],
    "action_items": [
      "Close COPX ($2,989) — lowest conviction, no catalyst within 30d",
      "Close FPS ($6,793) OR add $707 to reach minimum $7,500",
      "DG: wait for 06-02 earnings, then upgrade to $7,500 or exit per PA-002",
      "CRM: wait for 06-03 earnings, then upgrade to $7,500 or exit per PA-003"
    ]
  },
  "l17": {
    "status": "OK",
    "last_regime_check": "2026-05-22T09:53:49+08:00",
    "current_regime": "bull",
    "hours_since_check": 12.4,
    "vix_5d_delta": null,
    "regime_shifted": false,
    "adjustment_required": false
  },
  "l18": {
    "status": "CRITICAL",
    "short_exposure_usd": 0.00,
    "short_exposure_pct": 0.0,
    "target_min_pct": 0.10,
    "hard_floor_pct": 0.05,
    "consecutive_days_zero": 5,
    "long_block_active": true,
    "top_short_candidates": ["TSLA", "MSTR", "NNE"],
    "action_items": [
      "CRITICAL: 0% short exposure for 5 consecutive days — long-block active",
      "Execute weekly short SOP tonight (W3 22:00 BJT)",
      "Minimum target: 1 short position >= $7,500"
    ]
  },
  "new_violations_written": 3,
  "violations_already_tracked": 2
}
```

---

## 6. Function Signatures

```python
def main() -> int:
    """Entry point. Returns exit code (0/1/2)."""

def run_compliance_check(
    account_key: str = "us",
    post_trade: bool = False,
    regime_only: bool = False,
    summary: bool = False,
) -> ComplianceReport:
    """
    Top-level orchestrator. Loads state, runs all three checks,
    writes violations, prints results, returns report dataclass.
    
    post_trade=True skips live VIX fetch (uses cached regime.json only),
    reducing latency in the execute_trade.py hot path.
    """

# ── L16 ──────────────────────────────────────────────────────────────────────

def check_l16_shotgun_ban(
    account: dict,
    total_assets_usd: float,
) -> L16Result:
    """
    Checks:
      1. Count of long positions (excludes short_positions)
      2. Value of each long position vs MIN_POSITION_VALUE_USD
    
    Returns L16Result with violation details and prioritized action items.
    Action items rank positions by: lowest conviction_level first,
    then lowest portfolio_pct, then no catalyst within 30 days.
    """

def _rank_positions_for_closure(positions: list[dict], total_assets: float) -> list[dict]:
    """
    Returns positions sorted by closure priority (highest = close first):
      Priority score = (conviction_rank * 3) + (no_catalyst_30d * 2) + (below_minimum * 1)
    conviction_rank: C/T=3, B=2, A=1, S=0 (S never flagged for closure)
    """

def _generate_l16_action_items(
    excess_positions: list[dict],
    undersized: list[dict],
    total_assets: float,
) -> list[str]:
    """
    Generates specific action strings. Examples:
      "Sell COPX ($2,989) — C-grade, no catalyst within 30d, below minimum"
      "FPS ($6,793): add $707 to reach $7,500 minimum OR close"
      "CRM ($2,997): await 06-03 earnings per PA-003, then upgrade or exit"
    
    For positions with existing PA entries, references PA-id to avoid duplication.
    """

# ── L17 ──────────────────────────────────────────────────────────────────────

def check_l17_regime_awareness(
    post_trade: bool = False,
) -> L17Result:
    """
    Checks:
      1. Reads regime.json from Nexus Truth Store
      2. Calculates hours since last regime check
      3. If regime.json is stale (>24h): flags for update
      4. If regime shifted AND no portfolio adjustment logged within 24h: ALERT
      5. Checks macro events calendar for FOMC/CPI/NFP within next 3 days
    
    When post_trade=True, skips live VIX fetch and uses cached data only.
    When regime.json missing, returns WARNING (not CRITICAL) — regime detection
    is a should-have, not a blocker.
    """

def _load_regime_state() -> dict | None:
    """Reads ~/.claude/nexus/truth/macro/regime.json. Returns None if missing."""

def _check_macro_calendar_proximity(calendar_path: Path) -> list[MacroEvent]:
    """
    Reads market_calendar.json and returns macro events (FOMC/CPI/NFP)
    within the next 3 calendar days.
    
    market_calendar.json schema expected fields:
      macro_events: [{date, event_type, description}]
    
    If macro_events key missing, falls back to hardcoded known-dates for
    the current month (May-June 2026 cycle).
    """

def _detect_regime_shift(regime_state: dict) -> bool:
    """
    Returns True if:
      - regime changed within last 24h (since_date == today AND days_in_regime <= 1)
      - OR VIX 5-day delta > VIX_DELTA_5D_SIGNAL (from regime signals_snapshot)
    """

def _check_portfolio_adjustment_post_shift(
    regime_state: dict,
    trade_log: list[dict],
) -> bool:
    """
    Returns True if a portfolio adjustment (buy/sell/short/cover) was logged
    in trade_log within REGIME_ADJUST_WINDOW_H hours of the detected regime shift.
    Used to determine if L17 adjustment requirement has been satisfied.
    """

# ── L18 ──────────────────────────────────────────────────────────────────────

def check_l18_short_quota(
    account: dict,
    total_assets_usd: float,
) -> L18Result:
    """
    Checks:
      1. Calculates current short exposure as % of total_assets
      2. Determines severity tier (CRITICAL/WARNING/NOTICE)
      3. Counts consecutive trading days with zero short exposure
         by scanning audit-trail/ directory (buy/sell/short/cover logs)
      4. Reads short_candidates from watchlist_config.json
      5. Filters candidates: exclude if VIX>25, already in positions, or
         already in a recent short_scan_result in daily-reviews/
    
    Returns L18Result including long_block_active flag when consecutive_days >= CRITICAL_DAYS_NO_SHORT.
    """

def _calculate_short_exposure(account: dict) -> tuple[float, float]:
    """
    Returns (short_exposure_usd, short_exposure_pct).
    short_exposure_usd = sum(shares * entry_price for all short_positions)
    short_exposure_pct = short_exposure_usd / total_assets
    """

def _count_consecutive_no_short_days(audit_dir: Path) -> int:
    """
    Walks audit-trail/ directory in reverse date order.
    Counts consecutive trading days where no 'short' action appears.
    Stops counting when a 'short' action is found.
    Returns count (0 = has active or today-initiated short).
    """

def _get_short_candidates(watchlist_path: Path, current_positions: list[dict]) -> list[dict]:
    """
    Reads watchlist_config.json short_candidates field.
    Filters out: tickers already in long positions, tickers already in
    short_positions, tickers flagged as 'do_not_short' (META, NVDA, AVGO, etc.)
    Returns list sorted by priority score (descending).
    
    Expected watchlist_config.json short_candidates schema:
      [{ticker, name, type (1/2/3/4), reason, priority_score, vix_threshold}]
    """

# ── Pending Actions ───────────────────────────────────────────────────────────

def load_pending_actions(path: Path) -> dict:
    """Loads pending_actions.json. Returns empty structure if file missing."""

def save_pending_actions_atomic(path: Path, state: dict) -> None:
    """
    Atomic write using tempfile + os.replace pattern (mirrors save_portfolio_atomic).
    Updates _meta.last_updated timestamp before writing.
    """

def write_violations_to_pending(
    violations: list[ViolationRecord],
    pending_path: Path,
) -> tuple[int, int]:
    """
    Merges new violations into pending_actions.json.
    
    Deduplication logic:
      - Existing pending item with same rule + ticker + status="pending" → update
        consecutive_days counter and detected_at, do NOT create duplicate
      - Resolved or acknowledged item → create new entry
    
    Returns (new_violations_written, violations_already_tracked).
    
    IMPORTANT: reads latest version of pending_actions.json before writing
    (multi-session safety, mirrors Truth Store write protocol).
    """

def _make_violation_id(rule: str, ticker: str | None, date_str: str, sequence: int) -> str:
    """Returns 'COMP-L16-20260522-001' format ID."""

def _find_existing_violation(
    pending_list: list[dict],
    rule: str,
    ticker: str | None,
) -> dict | None:
    """
    Finds existing pending compliance_violation entry for the same rule+ticker.
    Returns None if no match found or if existing entry is resolved/acknowledged.
    """

# ── Repeated Violation Escalation ────────────────────────────────────────────

def check_repeated_violations(
    pending_list: list[dict],
    consecutive_threshold: int = 3,
) -> list[dict]:
    """
    Scans pending_list for compliance_violation entries where consecutive_days >= threshold.
    Returns list of entries that should be escalated to CRITICAL flag.
    
    Escalation: sets severity="CRITICAL" and priority="urgent" on the entry.
    Prints a session-level alert:
      "[COMPLIANCE] ESCALATION: L16 violated 3+ consecutive days — CRITICAL FLAG ACTIVE"
    """

# ── L18 Long-Block Enforcement ────────────────────────────────────────────────

def check_l18_long_block(
    pending_list: list[dict],
) -> bool:
    """
    Returns True if an L18 violation with consecutive_days >= CRITICAL_DAYS_NO_SHORT
    exists in pending with status="pending".
    
    When True: prints hard warning before any new long buy:
      "[COMPLIANCE] L18 LONG-BLOCK: Short exposure = 0% for 5+ days.
       New long positions blocked until >= 1 short position deployed."
    
    Note: this does NOT hard-block execute_trade.py (no sys.exit). It surfaces
    the alert and returns exit code 2. The agent session makes the final call.
    This matches the philosophy of other warnings in execute_trade.py (validate_buy
    uses print+warn for bear-case 15-25%, not sys.exit).
    """
```

---

## 7. Data Classes

```python
from dataclasses import dataclass, field

@dataclass
class L16Result:
    status: str                          # "OK" | "VIOLATION"
    position_count: int
    max_allowed: int = MAX_US_LONG_POSITIONS
    positions_to_close: list[str] = field(default_factory=list)   # ranked by priority
    undersized_positions: list[dict] = field(default_factory=list) # [{ticker, value, shortfall}]
    action_items: list[str] = field(default_factory=list)

@dataclass
class L17Result:
    status: str                          # "OK" | "WARNING" | "STALE" | "REGIME_SHIFT_UNACKNOWLEDGED"
    last_regime_check: str | None        # ISO timestamp
    current_regime: str | None           # "bull"|"sideways"|"bear"|"crisis"
    hours_since_check: float | None
    vix_5d_delta: float | None
    regime_shifted: bool = False
    adjustment_required: bool = False
    upcoming_macro_events: list[dict] = field(default_factory=list)  # [{date, event_type}]
    action_items: list[str] = field(default_factory=list)

@dataclass
class L18Result:
    status: str                          # "OK" | "NOTICE" | "WARNING" | "CRITICAL"
    short_exposure_usd: float
    short_exposure_pct: float
    target_min_pct: float = SHORT_TARGET_MIN_PCT
    hard_floor_pct: float = SHORT_HARD_FLOOR_PCT
    consecutive_days_zero: int = 0
    long_block_active: bool = False
    top_short_candidates: list[str] = field(default_factory=list)
    action_items: list[str] = field(default_factory=list)

@dataclass
class ComplianceReport:
    timestamp: str
    overall_status: str                  # "OK" | "NOTICE" | "WARNING" | "CRITICAL"
    l16: L16Result
    l17: L17Result
    l18: L18Result
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
    event_type: str   # "FOMC" | "CPI" | "NFP"
    description: str
    days_until: int
```

---

## 8. Severity and Exit Code Mapping

| Rule | Condition | Severity | Exit Code | Priority |
|------|-----------|----------|-----------|----------|
| L16 | position_count > MAX_US_LONG_POSITIONS | WARNING | 1 | high |
| L16 | any position value < MIN_POSITION_VALUE_USD | WARNING | 1 | high |
| L16 | same violation for 3+ consecutive days | CRITICAL | 1 | urgent |
| L17 | regime.json stale (>24h) | WARNING | 1 | medium |
| L17 | regime shifted, no adjustment in 24h | WARNING | 1 | high |
| L17 | macro event within 24h + regime not checked | WARNING | 1 | high |
| L18 | short_exposure_pct < SHORT_TARGET_MIN_PCT (0-10%) | NOTICE | 1 | medium |
| L18 | short_exposure_pct < SHORT_HARD_FLOOR_PCT (0-5%) | WARNING | 1 | high |
| L18 | short_exposure_pct == 0% | WARNING | 1 | high |
| L18 | consecutive_days_zero >= CRITICAL_DAYS_NO_SHORT (5) | CRITICAL | 2 | urgent |

**overall_status logic**: `max(l16.severity, l17.severity, l18.severity)` where CRITICAL > WARNING > NOTICE > OK.

---

## 9. L16 Action Item Generation Logic

```python
def _generate_l16_action_items(excess_positions, undersized, total_assets):
    """
    Step 1: If position_count > 9, identify which to close.
      - Sort all positions by _rank_positions_for_closure()
      - Top N = (count - 9) positions get "Sell {ticker} ({value}) — {reason}" items
      - Reason template: "{grade}-grade, {catalyst_status}, {size_status}"
    
    Step 2: For undersized positions:
      - If position has a matching pending_action (PA-002/PA-003 for DG/CRM):
          "await {date} earnings per {pa_id}, then upgrade to $7,500 or exit"
      - Else if shortfall <= 2000:
          "add ${shortfall} to {ticker} to reach $7,500 minimum"
      - Else:
          "Sell {ticker} (${value}) or add ${shortfall} to reach minimum $7,500"
    
    Step 3: Never flag S-grade positions for closure (S-grade logic exemption).
    """
```

**Conviction rank for closure priority** (higher = close first):
- C/T grade: rank 3
- B grade: rank 2
- A grade: rank 1
- S grade: rank 0 (never flagged for closure)
- Ungraded (no conviction_level field): rank 2 (treated as B)

---

## 10. L17 Macro Events Calendar Fallback

When `market_calendar.json` does not have a `macro_events` key, use hardcoded known events for the current period:

```python
HARDCODED_MACRO_EVENTS_2026_Q2 = [
    {"date": "2026-06-11", "event_type": "CPI",  "description": "US CPI May 2026"},
    {"date": "2026-06-18", "event_type": "FOMC", "description": "FOMC June 2026 Decision"},
    {"date": "2026-07-03", "event_type": "NFP",  "description": "US NFP June 2026"},
]
```

L17 check should log a note when using fallback: `"[L17] macro_events not found in market_calendar.json, using hardcoded Q2 2026 schedule"`.

---

## 11. L18 Consecutive-Days Counter

The counter is computed dynamically from the `audit-trail/` directory at runtime — it is NOT stored in any JSON file. This avoids state drift.

```
Algorithm:
1. Collect all .json files in audit-trail/ where action == "short"
2. Extract unique trading dates (YYYY-MM-DD) from filenames
3. Get last_short_date = max(short_dates), or None if empty
4. Get today_str = today's date
5. Get all NYSE trading days between last_short_date+1 and today (inclusive)
   using market_calendar.json nyse_closed list
6. consecutive_days = len(trading_days_without_short)
```

When `audit-trail/` is empty or no short files exist, `consecutive_days` = total trading days since `portfolio_state.json._meta.start_date`.

---

## 12. Output Format (non-summary mode)

```
============================================================
  Compliance Check — L16 / L17 / L18
============================================================
  Timestamp: 2026-05-22T22:15:00+08:00
  Account:   us

  [L16 VIOLATION] Shotgun Ban
  ─────────────────────────────────────────
  Positions: 11 / 9 allowed  ← OVER LIMIT (2 excess)
  Undersized (below $7,500):
    FPS   $6,793  shortfall $707
    CRM   $2,997  shortfall $4,503
    DG    $2,943  shortfall $4,557
    COPX  $2,989  shortfall $4,511
  Action items:
    1. Close COPX ($2,989) — C-grade, no catalyst within 30d, below minimum
    2. Close FPS ($6,793) OR add $707 to reach $7,500
    3. DG: await 2026-06-02 earnings per PA-002, then $7,500 or exit
    4. CRM: await 2026-06-03 earnings per PA-003, then $7,500 or exit

  [L17 OK] Regime Awareness
  ─────────────────────────────────────────
  Last check: 2026-05-22T09:53:49+08:00 (12.4h ago)
  Current regime: BULL (confidence 70%)
  No regime shift detected. No macro events within 24h.

  [L18 CRITICAL] Short Quota — LONG-BLOCK ACTIVE
  ─────────────────────────────────────────
  Short exposure: $0 (0.0%) | Target: 10-15% | Floor: 5%
  Consecutive days at 0%: 5  ← SYSTEM FAILURE THRESHOLD
  LONG-BLOCK: New long positions should be deferred until >= 1 short deployed.
  Top candidates (from watchlist short_candidates):
    1. TSLA — Type 2, await delivery data
    2. MSTR — Type 3, BTC overexposure thesis
    3. NNE  — Type 3, speculative nuclear PE premium
  Action: Execute weekly short SOP tonight (W3 22:00 BJT)

  ────────────────────────────────────────────────────────────
  OVERALL: CRITICAL | Violations written to pending_actions.json
  New: 3  |  Already tracked: 2
============================================================
```

---

## 13. pending_actions.json Integration Notes

### Schema compatibility

New compliance violation entries use `"type": "compliance_violation"` — distinct from existing manual entries which use types like `"rebalance"`, `"short"`, `"regime_adjustment"`. The `session_instructions` block in pending_actions.json must be preserved verbatim on every write.

### Deduplication on write

Before writing a new violation:
1. Scan `pending` array for existing entry matching `rule` + `ticker` (or `rule` alone for portfolio-level L18) with `status == "pending"` and `auto_generated == true`
2. If found: increment `consecutive_days` by 1 and update `detected_at` — no new entry
3. If not found: append new ViolationRecord
4. Move `status == "resolved"` compliance entries to `completed` array with `resolved_at` timestamp when the condition clears

### Cleanup on resolution

When a violation clears (e.g., position closed, short deployed), `compliance_check.py` should:
- Set `status = "resolved"` on matching pending entry
- Add `resolved_at` field
- Move to `completed` array on the next write

---

## 14. CLI Interface

```
compliance_check.py [OPTIONS]

Options:
  --post-trade         Post-trade mode: skip live VIX fetch, use cached regime.json
  --account TEXT       Account to check: us | a_share | all (default: us)
  --regime-only        Run L17 check only
  --summary            Print machine-readable JSON report to stdout
  --no-write           Dry run: print violations but do not write to pending_actions.json
  --quiet              Suppress formatted output (useful when called from execute_trade.py)
```

---

## 15. Excluded from Scope

The following are intentionally NOT part of `compliance_check.py` v1.0:

- **A-share L16 enforcement**: The L16 shotgun ban is US-specific (9 positions/$7,500 minimum). A-share position limits are enforced by `validate_buy()` in execute_trade.py (confidence-grade tiers) and do not need a separate shotgun check.
- **Real-time VIX fetch in post-trade mode**: execute_trade.py is latency-sensitive; the post-trade hook uses `--post-trade` flag which reads from cached `regime.json` only. Live VIX fetch is reserved for `--regime-only` or standalone runs.
- **Blocking new trades via sys.exit**: compliance_check.py never calls `sys.exit` in a way that aborts an already-completed trade. The L18 long-block returns exit code 2 as an advisory signal — the agent session decides whether to honor it.
- **L10-L15 enforcement**: behavioral rules L10-L15 require session-level judgment and cannot be script-enforced without full NLP.

---

## 16. File Layout Summary

```
sim-portfolio/
├── scripts/
│   ├── compliance_check.py        ← NEW (this spec)
│   ├── execute_trade.py           ← MODIFIED (add hook at line ~811)
│   ├── regime_detection.py        ← READ (for regime state)
│   └── ...
├── portfolio_state.json           ← READ
├── pending_actions.json           ← READ + WRITE (atomic)
├── watchlist_config.json          ← READ (short_candidates)
├── market_calendar.json           ← READ (macro events)
└── audit-trail/
    └── YYYY-MM-DD-{TICKER}-{action}-NNN.json  ← READ (L18 consecutive day counter)
```

---

*Spec authored: 2026-05-22. Implementation target: scripts/compliance_check.py. Review this spec before implementation to confirm watchlist_config.json short_candidates schema matches expected format.*

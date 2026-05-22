# pre_session_check.py — Complete Specification

**Purpose**: Automated compliance gate that runs at the START of every trading session. Reads `portfolio_state.json` and `pending_actions.json`, performs deterministic rule checks, and emits a pass/fail report that the Claude AI agent must acknowledge before executing any trade. Exit code 1 if any HARD BLOCK exists.

**Root cause being solved**: 147 rules exist as text. No automated pre-session gate. L16 max positions violated 4/5 days, L18 short quota violated 5/5 days, pending rebalance actions ignored 3 times.

**Source of truth**: `portfolio_state.json` only. No yfinance calls — this check runs on stored portfolio data, not live prices.

---

## File Location and Invocation

```
/Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts/pre_session_check.py
```

```bash
# Standard invocation (every session — before any trade)
uv run --script scripts/pre_session_check.py

# Skip pending_actions check (use when pending_actions.json is absent)
uv run --script scripts/pre_session_check.py --skip-pending

# Force pass (escape hatch — requires explicit user override reason)
uv run --script scripts/pre_session_check.py --override "reason for override"

# Machine-readable JSON output (for pipeline integration)
uv run --script scripts/pre_session_check.py --json
```

**Exit codes**:
- `0` = all checks pass (CLEARED)
- `1` = one or more HARD BLOCKS (BLOCKED — no trading until fixed)
- `2` = script error (file not found, JSON parse error, etc.)

---

## Script Header (uv inline dependencies)

```python
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
```

No external dependencies. Uses only stdlib: `json`, `sys`, `argparse`, `datetime`, `pathlib`.

---

## Constants (all tunable at top of file)

```python
# ── File paths ──────────────────────────────────────────────────────────────
PORTFOLIO_PATH    = Path(__file__).parent.parent / "portfolio_state.json"
PENDING_PATH      = Path(__file__).parent.parent / "pending_actions.json"
LAST_REGIME_PATH  = Path(__file__).parent.parent / "daily-reviews"  # scan for most recent file

# ── HARD BLOCK thresholds ────────────────────────────────────────────────────
US_MAX_POSITIONS       = 9         # L16: total US longs + shorts ≤ 9
US_MIN_POSITION_USD    = 7500      # L16: every US position ≥ $7,500
US_MIN_SHORT_PCT       = 0.05      # L18: short exposure ≥ 5% of US portfolio
US_MIN_CASH_PCT        = 0.15      # strategy.md §3.2: US cash ≥ 15%
CN_MIN_CASH_PCT        = 0.20      # strategy.md §3.2: A-share cash ≥ 20% (加仓前须≥20%)
P0_P1_OVERDUE_DAYS     = 2         # pending actions P0/P1 older than 2 trading days = BLOCK

# ── SOFT WARNING thresholds ──────────────────────────────────────────────────
US_SHORT_TARGET_LOW    = 0.10      # L18 target 10–15%; warn below 10%
US_MAX_SINGLE_PCT      = 0.15      # warn if any US position > 15% (A-grade allowed to 25%)
CN_MAX_SINGLE_PCT      = 0.12      # warn if any A-share position > 12%
C_GRADE_MAX_DAYS       = 14        # C-grade positions older than 14 days without upgrade/exit
REGIME_STALE_DAYS      = 3         # warn if last regime check > 3 days old

# ── Trading day calendar (NYSE closed + weekends) ────────────────────────────
NYSE_HOLIDAYS_2026 = [
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03",
    "2026-05-25", "2026-06-19", "2026-07-03", "2026-09-07",
    "2026-11-26", "2026-12-25",
]
```

---

## Data Structures

### Input: portfolio_state.json (relevant fields)

```python
# Root
state: dict = {
    "_meta": {"last_updated": str},          # ISO timestamp
    "accounts": {
        "us": {
            "currency": "USD",
            "cash": float,                   # absolute cash amount
            "total_assets": float,           # cash + long market value - short unrealized loss
            "positions": list[USPosition],   # long positions
            "short_positions": list[ShortPosition],  # may be absent or empty
        },
        "a_share": {
            "currency": "CNY",
            "cash": float,
            "total_assets": float,
            "positions": list[CNPosition],
        },
    },
}

# USPosition (each element of accounts.us.positions)
USPosition: dict = {
    "ticker": str,
    "name": str,
    "shares": int,
    "avg_cost": float,
    "market_value": float,          # current_price × shares (may use avg_cost if no current_price)
    "portfolio_pct": float,         # market_value / total_assets
    "current_price": float,         # optional; fallback to avg_cost
    "bear_case": str,               # optional; documented bear case text
    "bear_case_downside": float,    # optional; negative float e.g. -0.18
    "type": str,                    # e.g. "base_position", "trading_position", "catalyst_position"
    "entry_date": str,              # ISO date string
    "conviction_level": str,        # optional: "A", "B", "C", "S", "T"
}

# ShortPosition (each element of accounts.us.short_positions)
ShortPosition: dict = {
    "ticker": str,
    "shares": int,
    "entry_price": float,
    "instrument_type": "short",
}

# CNPosition (each element of accounts.a_share.positions)
CNPosition: dict = {
    "ticker": str,
    "name": str,
    "shares": int,
    "avg_cost": float,
    "market_value": float,
    "portfolio_pct": float,
    "bear_case": str,               # optional
    "type": str,
    "entry_date": str,
}
```

### Input: pending_actions.json (relevant fields)

```python
pending_data: dict = {
    "pending": list[PendingAction],
    "completed": list[PendingAction],
}

PendingAction: dict = {
    "id": str,                   # e.g. "PA-007"
    "type": str,                 # "rebalance", "short", "regime_adjustment"
    "priority": str,             # "high", "medium", "low"; "urgent" = treat as P0
    "status": str,               # "pending", "urgent", "completed"
    "trigger_date": str,         # ISO date YYYY-MM-DD
    "trigger_condition": str,
    "account": str,
    "name": str,
    "action": str,               # description of action required
    "created_at": str,           # ISO timestamp
}
```

### Output: CheckResult (internal data model)

```python
@dataclass
class CheckItem:
    check_id: str          # e.g. "L16_POSITION_COUNT"
    category: str          # "HARD_BLOCK" or "SOFT_WARNING"
    passed: bool
    label: str             # short display label
    detail: str            # one-line explanation with values
    rule_ref: str          # e.g. "L16", "L18", "strategy.md §3.2"

@dataclass
class CheckReport:
    date: str                        # today's date YYYY-MM-DD
    hard_blocks: list[CheckItem]     # passed=False, category=HARD_BLOCK
    soft_warnings: list[CheckItem]   # passed=False, category=SOFT_WARNING
    passed_checks: list[CheckItem]   # passed=True
    verdict: str                     # "CLEARED" or "BLOCKED"
    block_count: int
    warning_count: int
    pass_count: int
```

---

## Function Signatures

### Top-level entry point

```python
def main() -> None:
    """
    Parse CLI args, load files, run all checks, print report, exit with code.
    """
```

### File loading

```python
def load_portfolio(path: Path) -> dict:
    """
    Load portfolio_state.json. Exits with code 2 on file-not-found or JSON error.
    Returns raw dict.
    """

def load_pending(path: Path) -> dict:
    """
    Load pending_actions.json. Returns {"pending": [], "completed": []} if file absent.
    Never raises — missing file = treat as no pending actions.
    """
```

### Utility functions

```python
def calc_us_short_exposure(us_account: dict) -> tuple[float, float]:
    """
    Returns (short_value_usd, short_pct).
    short_value_usd = sum of (shares × entry_price) for each ShortPosition.
    short_pct = short_value_usd / us_account["total_assets"].
    Returns (0.0, 0.0) if short_positions key absent or empty.
    """

def calc_position_value(pos: dict) -> float:
    """
    Returns market_value if present and > 0.
    Fallback: current_price × shares if current_price present.
    Fallback: avg_cost × shares.
    """

def trading_days_between(start_iso: str, end_iso: str) -> int:
    """
    Count Mon–Fri business days between two ISO date strings (inclusive of start, exclusive of end).
    Does not account for holidays — approximate only.
    """

def days_since_last_regime_check(daily_reviews_dir: Path) -> Optional[int]:
    """
    Scan daily-reviews/ for most recent .md file containing "Regime" or "regime" or "L17".
    Returns integer days since that file's date (parsed from filename YYYY-MM-DD.md).
    Returns None if no matching file found.
    """

def count_trading_days_held(entry_date_iso: str) -> int:
    """
    Approximate trading days from entry_date to today (weekdays only).
    Used for C-grade staleness check and pending action overdue calculation.
    """
```

### HARD BLOCK checkers

Each returns a `CheckItem`. All take the loaded `state` dict as input.

```python
def check_us_position_count(state: dict) -> CheckItem:
    """
    L16: US long positions count ≤ US_MAX_POSITIONS (9).
    Reads: state["accounts"]["us"]["positions"]
    Does NOT count short_positions toward the 9-position limit
    (L16 spec: "多6+空3" — shorts have separate 3-slot quota).
    BLOCK condition: len(positions) > 9
    Detail format: "US positions: {n}/{limit} (OVER by {n-limit})"
    check_id: "L16_POSITION_COUNT"
    rule_ref: "L16 — CLAUDE.md 铁律"
    """

def check_us_minimum_position_size(state: dict) -> CheckItem:
    """
    L16: Every US position ≥ $7,500.
    Reads: state["accounts"]["us"]["positions"][*].market_value (or fallback calc)
    BLOCK condition: any position with value < US_MIN_POSITION_USD
    Detail format if violated: "Below minimum: {ticker} ${value:,.0f}, {ticker} ${value:,.0f}"
    Detail format if passed: "All {n} positions ≥ $7,500"
    check_id: "L16_MIN_POSITION_SIZE"
    rule_ref: "L16 — 散弹枪禁令"
    NOTE: If check_us_position_count already fires a BLOCK, this check should still run
    independently — both blocks may coexist.
    """

def check_us_short_exposure(state: dict) -> CheckItem:
    """
    L18: Short exposure ≥ US_MIN_SHORT_PCT (5%) of US portfolio.
    BLOCK condition: short_pct < 0.05
    CRITICAL sub-condition: short_pct == 0.0 → detail includes "CRITICAL: 0% short exposure"
    Reads: state["accounts"]["us"]["short_positions"] (may be absent)
    Detail format (0%): "Short exposure: 0% — CRITICAL (system failure, L18 violated 5+ days)"
    Detail format (1-4%): "Short exposure: {pct:.1%} (target ≥5%, current below hard floor)"
    check_id: "L18_SHORT_EXPOSURE_FLOOR"
    rule_ref: "L18 — 空头强制配额"
    """

def check_pending_overdue(state: dict, pending: dict) -> CheckItem:
    """
    Block if any P0/P1 (urgent/high priority) pending action is overdue by > 2 trading days.
    P0 = status=="urgent" OR (priority=="high" AND type in ["regime_adjustment", "short"])
    P1 = priority=="high" (all other types)
    Overdue = trading_days_between(created_at, today) > P0_P1_OVERDUE_DAYS
    
    Special case: PA-007 (regime_adjustment, status=urgent, created 2026-05-22) — check
    trading days since created_at. If 0 days since creation → not yet overdue but is "urgent today".
    
    BLOCK condition: any P0/P1 action is overdue (> 2 trading days old, not completed)
    Detail format: "Overdue P0/P1: {id} ({name}, {type}, {days_overdue}d overdue)"
    check_id: "PENDING_OVERDUE"
    rule_ref: "L17 §4 — 每session第4步检查pending"
    """

def check_bear_case_documented(state: dict) -> CheckItem:
    """
    All positions in both accounts must have a documented bear_case field (non-empty string).
    Reads: state["accounts"]["us"]["positions"][*].bear_case
           state["accounts"]["a_share"]["positions"][*].bear_case
    BLOCK condition: any position missing bear_case or bear_case == ""
    Detail format if violated: "No bear case: {ticker} ({account}), {ticker} ({account})"
    Detail format if passed: "All {n} positions have documented bear case"
    check_id: "BEAR_CASE_DOCUMENTED"
    rule_ref: "strategy.md §3.1 — bear case 4-tier, 进场检查表"
    """

def check_us_cash_reserve(state: dict) -> CheckItem:
    """
    US cash ≥ US_MIN_CASH_PCT (15%) of US total_assets.
    Reads: state["accounts"]["us"]["cash"], state["accounts"]["us"]["total_assets"]
    BLOCK condition: cash / total_assets < 0.15
    Detail format: "US cash: {pct:.1%} (minimum 15%)"
    check_id: "US_CASH_RESERVE"
    rule_ref: "strategy.md §3.2 — 现金≥15%"
    """

def check_cn_cash_reserve(state: dict) -> CheckItem:
    """
    A-share cash ≥ CN_MIN_CASH_PCT (20%) of A-share total_assets.
    Reads: state["accounts"]["a_share"]["cash"], state["accounts"]["a_share"]["total_assets"]
    BLOCK condition: cash / total_assets < 0.20
    Detail format: "A股 cash: {pct:.1%} (minimum 20% before adding positions)"
    check_id: "CN_CASH_RESERVE"
    rule_ref: "strategy.md §3.2 — 现金≥20% (加仓前须≥20%)"
    """
```

### SOFT WARNING checkers

Each returns a `CheckItem` (passed=True means no warning, passed=False means warning fires).

```python
def warn_us_short_below_target(state: dict) -> CheckItem:
    """
    L18 soft: short exposure < 10% (below target band 10-15%).
    Only fires if short_pct >= 5% (below 5% is already a HARD BLOCK).
    WARN condition: 5% ≤ short_pct < 10%
    Detail: "Short exposure {pct:.1%} below target band 10–15%"
    check_id: "L18_SHORT_BELOW_TARGET"
    rule_ref: "L18 — 空头目标10-15%"
    """

def warn_us_position_concentration(state: dict) -> CheckItem:
    """
    Any single US position > 15% of US portfolio (A-grade conviction allowed to 25%,
    but 15-25% range should be flagged as a warning, not a block).
    WARN condition: any position portfolio_pct > 0.15 AND conviction_level != "A"
                    OR portfolio_pct > 0.25 (exceeds even A-grade limit)
    Detail: "Concentration: {ticker} {pct:.1%} (>{limit:.0%} limit)"
    check_id: "US_POSITION_CONCENTRATION"
    rule_ref: "strategy.md §3.1 — A级≤25%"
    """

def warn_cn_position_concentration(state: dict) -> CheckItem:
    """
    Any single A-share position > 12% of A-share portfolio
    (B-grade ≤ 15%, but 12% is a soft warning threshold).
    WARN condition: any A-share position portfolio_pct > 0.12
    Detail: "A股集中度: {ticker} {pct:.1%} (soft threshold 12%)"
    check_id: "CN_POSITION_CONCENTRATION"
    rule_ref: "strategy.md §3.1 — B级≤15%，软警戒12%"
    """

def warn_c_grade_stale(state: dict) -> CheckItem:
    """
    C-grade or "scout_position" type positions held > 14 days without upgrade/exit.
    C-grade identification: conviction_level == "C" OR type == "scout_position"
    Trading days held computed via count_trading_days_held(entry_date).
    WARN condition: any C-grade position with trading_days_held > C_GRADE_MAX_DAYS
    Detail: "C-grade stale (>{limit}d): {ticker} ({days}d), {ticker} ({days}d)"
    check_id: "C_GRADE_STALE"
    rule_ref: "strategy.md §3.1 — C级观察仓，快速止损机制"
    """

def warn_pending_approaching(state: dict, pending: dict) -> CheckItem:
    """
    Pending actions (any priority) where trigger_date is within 2 trading days.
    Does NOT include items already flagged as overdue (those are HARD BLOCKS).
    WARN condition: 0 < trading_days_between(today, trigger_date) ≤ 2
    Detail: "Pending approaching: {id} ({name}, triggers {trigger_date})"
    check_id: "PENDING_APPROACHING"
    rule_ref: "L17 §4"
    """

def warn_regime_stale(state: dict) -> CheckItem:
    """
    Warn if last regime check > 3 days old (no daily-review file found with regime content).
    Uses days_since_last_regime_check(LAST_REGIME_PATH).
    WARN condition: days > REGIME_STALE_DAYS (3), or None (never checked)
    Detail: "Last regime check: {days}d ago (L17 §3 requires ≤3 days)"
    check_id: "REGIME_STALE"
    rule_ref: "L17 §3 — Regime Detection"
    NOTE: If daily-reviews dir is empty or has no matching files, report "never checked".
    """

def warn_pending_urgent_today(state: dict, pending: dict) -> CheckItem:
    """
    Any pending action with status="urgent" or priority="high" created today (day 0)
    that is not yet overdue but requires action in this session.
    This is distinct from HARD BLOCK (overdue). Purpose: surface PA-007-type items
    even before they become overdue.
    WARN condition: urgent/high action created today or trigger_date == today
    Detail: "Urgent today: {id} ({name}, {type}, 0d)"
    check_id: "PENDING_URGENT_TODAY"
    rule_ref: "L17 §4 — urgent actions require same-session handling"
    """
```

### Report assembly and output

```python
def assemble_report(all_checks: list[CheckItem]) -> CheckReport:
    """
    Partition all_checks into hard_blocks, soft_warnings, passed_checks.
    Set verdict = "BLOCKED" if block_count > 0, else "CLEARED".
    """

def print_report(report: CheckReport) -> None:
    """
    Print formatted report to stdout. See OUTPUT FORMAT section below.
    Uses only print() — no rich/colorama dependencies.
    ASCII box-drawing with ═══ borders.
    """

def print_json_report(report: CheckReport) -> None:
    """
    Print machine-readable JSON to stdout. Schema:
    {
      "date": "2026-05-22",
      "verdict": "BLOCKED",
      "block_count": 2,
      "warning_count": 3,
      "pass_count": 8,
      "hard_blocks": [
        {"check_id": "L16_POSITION_COUNT", "label": "US positions: 11/9", "detail": "...", "rule_ref": "L16"}
      ],
      "soft_warnings": [...],
      "passed": [...]
    }
    """
```

---

## Exact Check Execution Order

The script runs checks in this deterministic order. All 13 checks always run (no short-circuit).

```python
ALL_CHECKS: list[Callable] = [
    # HARD BLOCKS (6 checks)
    check_us_position_count,          # 1. L16 count
    check_us_minimum_position_size,   # 2. L16 minimum size
    check_us_short_exposure,          # 3. L18 floor
    check_pending_overdue,            # 4. Pending P0/P1 overdue
    check_bear_case_documented,       # 5. Bear case
    check_us_cash_reserve,            # 6. US cash ≥ 15%
    check_cn_cash_reserve,            # 7. A股 cash ≥ 20%

    # SOFT WARNINGS (6 checks)
    warn_us_short_below_target,       # 8. L18 target band
    warn_us_position_concentration,   # 9. US single position > 15%
    warn_cn_position_concentration,   # 10. A股 single position > 12%
    warn_c_grade_stale,               # 11. C-grade > 14 days
    warn_pending_approaching,         # 12. Pending < 2 days
    warn_regime_stale,                # 13. Regime > 3 days
    warn_pending_urgent_today,        # 14. Urgent action today (day 0)
]
```

Note: `check_us_cash_reserve` and `check_cn_cash_reserve` are HARD BLOCKS (items 6 and 7), not soft warnings — the strategy.md notes cash ≥ 20% is the threshold *before adding new positions*, making a cash violation a blocking condition for the session.

Total checks: 7 hard-block checks + 7 soft-warning checks = 14 checks.

---

## Output Format

```
═══ PRE-SESSION CHECK (2026-05-22) ═══

HARD BLOCKS: 2 ❌
  ❌ [L16] US positions: 11/9 (OVER by 2) — reduce before any new position
  ❌ [L18] Short exposure: 0% — CRITICAL: system failure, 5+ days without short (L18 violated)

SOFT WARNINGS: 4 ⚠️
  ⚠️  [L18] Short below target: 0% (target band 10–15%)
  ⚠️  [L16] Below minimum: CRM $2,997, DG $2,943, COPX $2,989 — will be HARD BLOCK if not resolved at next earnings
  ⚠️  [PENDING] Urgent today: PA-007 (L18 short fix, regime_adjustment, trigger: 2026-05-22)
  ⚠️  [REGIME] Last regime check: unknown (never recorded in daily-reviews)

PASSED: 10 ✓
  ✓  [L16] Position minimum size: see warnings (CRM/DG/COPX flagged)
  ✓  [BEAR_CASE] All 17 positions have documented bear case
  ✓  [CASH_US] US cash: 30.4% (minimum 15%) ✓
  ✓  [CASH_CN] A股 cash: 35.6% (minimum 20%) ✓
  ✓  [L18_TARGET] Short exposure check skipped (already in HARD BLOCK)
  ✓  [CONCENTRATION_US] No single US position > 15%
  ✓  [CONCENTRATION_CN] No single A股 position > 12%
  ✓  [C_GRADE_STALE] No C-grade positions older than 14 days
  ✓  [PENDING_APPROACH] No pending actions triggering within 2 days
  ✓  [PENDING_OVERDUE] No P0/P1 actions overdue by > 2 trading days

═══ VERDICT: BLOCKED — fix 2 hard blocks before trading ═══
Fix order:
  1. [L18] Execute short scan NOW (W3 window 22:00 BJT) — build ≥1 short position ≥$7,500
  2. [L16] Reduce US longs from 11→9: stop-loss or thesis-fail candidates first
     Current candidates: CRM $2,997 (below minimum, pending earnings 06-03)
                         DG $2,943 (below minimum, pending earnings 06-02)
                         COPX $2,989 (below minimum, no near-term catalyst)
```

**Key formatting rules**:
1. Header line: `═══ PRE-SESSION CHECK ({YYYY-MM-DD}) ═══`
2. Section headers: `HARD BLOCKS: {n} ❌`, `SOFT WARNINGS: {n} ⚠️`, `PASSED: {n} ✓`
3. Each item indented 2 spaces. Prefix: `❌` for blocks, `⚠️ ` for warnings, `✓ ` for passed.
4. Rule reference in brackets: `[L16]`, `[L18]`, `[CASH_US]`, etc.
5. Verdict line: `═══ VERDICT: BLOCKED — fix {n} hard blocks before trading ═══`
   or `═══ VERDICT: CLEARED — proceed to trading ═══`
6. If BLOCKED, append "Fix order:" section listing blocks in priority order with specific remediation.

**Fix order priority** (for BLOCKED verdict):
1. L18 short exposure (most chronic violation, highest alpha cost per day)
2. L16 position count (requires action before any new trade)
3. L16 minimum size (time-gated to earnings dates — note separately)
4. Pending overdue
5. Bear case missing
6. Cash reserve

---

## Implementation Logic Details

### check_us_position_count: exact computation

```python
positions = state["accounts"]["us"].get("positions", [])
# Filter out call options (same pattern as risk_monitor.py)
long_positions = [p for p in positions if p.get("instrument_type") != "call_option"]
count = len(long_positions)
passed = count <= US_MAX_POSITIONS
detail = (
    f"US positions: {count}/{US_MAX_POSITIONS} (OVER by {count - US_MAX_POSITIONS})"
    if not passed
    else f"US positions: {count}/{US_MAX_POSITIONS}"
)
```

Current state: 11 positions (NVDA, AAPL, GOOGL, ADBE, SRUUF/SPUT, GEV, LEU, FPS, CRM, DG, COPX) → BLOCK.

### check_us_minimum_position_size: exact computation

```python
violations = []
for pos in long_positions:
    value = pos.get("market_value")
    if value is None or value <= 0:
        # Fallback
        price = pos.get("current_price") or pos.get("avg_cost", 0)
        value = price * pos.get("shares", 0)
    if value < US_MIN_POSITION_USD:
        violations.append((pos["ticker"], value))
```

Current violators: CRM ($2,997.27), DG ($2,943.08), COPX ($2,988.72).

**Important nuance**: These three are explicitly pending (PA-002, PA-003) — they were opened as sub-$7,500 trial positions with the stated intent to either raise to $7,500 post-earnings or exit. The check still fires as a HARD BLOCK because the rule says "single minimum $7,500" with no exception for trial positions. The fix-order section should note "time-gated to PA-002/PA-003 earnings events (06-02, 06-03)."

### check_us_short_exposure: exact computation

```python
us_account = state["accounts"]["us"]
short_positions = us_account.get("short_positions", [])
total_assets = float(us_account.get("total_assets", 0))

short_value = sum(
    p.get("shares", 0) * p.get("entry_price", 0)
    for p in short_positions
    if p.get("instrument_type") == "short"
)
short_pct = short_value / total_assets if total_assets > 0 else 0.0
```

Current state: `short_positions` key absent → short_value = 0.0, short_pct = 0.0 → CRITICAL BLOCK.

### check_pending_overdue: exact computation

```python
pending_items = pending_data.get("pending", [])
today = date.today()

P0_TYPES = {"regime_adjustment", "short"}  # time-sensitive types
overdue = []

for action in pending_items:
    if action.get("status") == "completed":
        continue
    
    priority = action.get("priority", "medium")
    status = action.get("status", "pending")
    action_type = action.get("type", "")
    created_at = action.get("created_at", "")
    
    # Classify as P0 or P1
    is_p0 = (status == "urgent") or (priority == "high" and action_type in P0_TYPES)
    is_p1 = priority == "high" and not is_p0
    
    if not (is_p0 or is_p1):
        continue
    
    # Calculate days since creation
    days_old = trading_days_between(created_at[:10], today.isoformat())
    
    if days_old > P0_P1_OVERDUE_DAYS:
        overdue.append({
            "id": action["id"],
            "name": action.get("name", ""),
            "type": action_type,
            "days_overdue": days_old - P0_P1_OVERDUE_DAYS,
        })
```

Current state: PA-007 (status="urgent", created 2026-05-22). If check runs on 2026-05-22 (creation day) → 0 trading days old → NOT overdue (below 2-day threshold). PA-007 will fire `warn_pending_urgent_today` instead. PA-006 (priority="high", type="short", created 2026-05-22, trigger_date 2026-05-28) → same logic.

**The HARD BLOCK for pending only fires if the action is created on a previous session and has aged past the 2-day threshold.** Day-0 urgent items are soft warnings only.

### check_bear_case_documented: exact computation

```python
violations = []
for acct_key, label in [("us", "US"), ("a_share", "A股")]:
    for pos in state["accounts"][acct_key].get("positions", []):
        bear_case = pos.get("bear_case", "")
        if not bear_case or not bear_case.strip():
            violations.append(f"{pos['ticker']} ({label})")
```

Current state: All 17 positions have `bear_case` fields → PASS.

### warn_c_grade_stale: C-grade identification

A position is C-grade if ANY of:
- `conviction_level == "C"`
- `type == "scout_position"`
- `type == "catalyst_position"` AND trading_days_held > C_GRADE_MAX_DAYS (catalyst positions are time-limited by definition)

Current potential matches: 晶方科技 (603005, type="scout_position", entry 2026-05-18 = 4 trading days) → not stale yet. FPS (type="catalyst_position", entry 2026-05-21 = 1 trading day) → not stale yet.

### days_since_last_regime_check: file scan logic

```python
def days_since_last_regime_check(daily_reviews_dir: Path) -> Optional[int]:
    """
    Scan daily_reviews_dir for files matching YYYY-MM-DD.md pattern.
    For each file, check if content contains "Regime" or "regime" or "VIX" or "L17".
    Return integer days since the most recent matching file's date.
    If no matching files, return None.
    """
    if not daily_reviews_dir.exists():
        return None
    
    pattern = re.compile(r"(\d{4}-\d{2}-\d{2})\.md$")
    matching_dates = []
    
    for f in daily_reviews_dir.iterdir():
        m = pattern.match(f.name)
        if not m:
            continue
        content = f.read_text(encoding="utf-8", errors="ignore")
        if any(kw in content for kw in ["Regime", "regime", "VIX", "L17", "L18"]):
            matching_dates.append(date.fromisoformat(m.group(1)))
    
    if not matching_dates:
        return None
    
    latest = max(matching_dates)
    return (date.today() - latest).days
```

---

## Edge Cases and Handling

| Edge Case | Handling |
|-----------|----------|
| `portfolio_state.json` missing | Exit code 2 with clear error message |
| `pending_actions.json` missing | Treat as `{"pending": [], "completed": []}` — no block |
| `accounts.us.short_positions` key absent | short_exposure = 0.0 → HARD BLOCK fires |
| Position with no `market_value` field | Use `current_price × shares` → `avg_cost × shares` as fallback |
| `total_assets` = 0 | All percentage checks → treat as 100% cash → all pass except explicit cash check |
| Pending action with `status="completed"` | Skip entirely (already done) |
| Entry date in ISO datetime format (e.g., "2026-05-21T13:10:15+08:00") | Strip to date only with `[:10]` |
| `conviction_level` field absent from position | Treat as "B" grade (default assumption) for concentration checks |
| `portfolio_pct` field in position | Use directly if present; else compute `market_value / total_assets` |

---

## What This Script Does NOT Do (scope boundaries)

The following are explicitly out of scope for `pre_session_check.py`:

- **No live price fetching** — uses portfolio_state.json cached prices only. (That is `fetch_prices.py`'s job.)
- **No stop-loss checking** — that is `risk_monitor.py`'s job (requires live prices).
- **No VIX checking** — that is `risk_monitor.py`'s job.
- **No circuit breaker** — that is `risk_monitor.py`'s job.
- **No sector concentration** — `risk_monitor.py` handles this.
- **No trade execution** — read-only gate, never modifies `portfolio_state.json`.
- **No yfinance imports** — zero network calls.

The relationship between scripts:
```
Session start:
  1. pre_session_check.py  ← runs first, no network, pure rule check (THIS SCRIPT)
  2. fetch_prices.py       ← update portfolio prices
  3. risk_monitor.py       ← full risk check with live prices + VIX
  4. decision_engine.py    ← generate trade suggestions
  5. execute_trade.py      ← execute approved trades
```

---

## Overlap with Existing Scripts (non-duplication notes)

`pre_session_check.py` is additive, not duplicative:

| Check | pre_session_check.py | risk_monitor.py | execute_trade.py |
|-------|---------------------|-----------------|-----------------|
| US position count ≤ 9 | **YES (new HARD BLOCK)** | Uses MAX_POSITIONS=15 (wrong threshold!) | Not checked |
| Single position min $7,500 | **YES (new HARD BLOCK)** | Not checked | Not checked |
| Short exposure ≥ 5% | **YES (new HARD BLOCK)** | Not checked | Not checked |
| Pending actions overdue | **YES (new HARD BLOCK)** | Not checked | Not checked |
| Bear case documented | **YES (new HARD BLOCK)** | Checks tier, not existence | Checks downside % |
| Cash ≥ 15%/20% | **YES (HARD BLOCK)** | YES (warning only) | YES (warning only) |
| C-grade staleness | **YES (soft warning)** | Not checked | Not checked |
| Regime freshness | **YES (soft warning)** | Not checked | Not checked |

Note: `risk_monitor.py`'s `MAX_POSITIONS = 15` is incorrect for the US account (should be 9). `pre_session_check.py` uses the correct L16 threshold of 9. Both scripts should coexist.

---

## Verification: Expected Output for Current Portfolio State (2026-05-22)

Running against the actual `portfolio_state.json` and `pending_actions.json` as of 2026-05-22 should produce:

**HARD BLOCKS: 2**
1. `[L16]` US positions: 11/9 (OVER by 2)
2. `[L18]` Short exposure: 0% — CRITICAL

**SOFT WARNINGS: 4**
1. `[L16]` Below minimum size: CRM $2,997, DG $2,943, COPX $2,989 ← this fires as WARNING not BLOCK because these are linked to time-gated pending actions (PA-002, PA-003); implementation note below
2. `[L18]` Short below target: 0% (target 10–15%) ← note: already a HARD BLOCK at 0%, this warning is suppressed when HARD BLOCK fires for same check
3. `[PENDING]` Urgent today: PA-007 (L18 short fix, 0d)
4. `[REGIME]` Regime check status unknown (no daily-reviews with regime content found)

**PASSED: 10**
- US cash: 30.4% ≥ 15% ✓
- A股 cash: 35.6% ≥ 20% ✓
- Bear case: all 17 positions documented ✓
- US concentration: no position > 25% (NVDA 11.9%, AAPL 10.1%) ✓
- A股 concentration: no position > 25% (安集 14.9%) ✓  ← note: 14.9% > 12% soft threshold → should fire warning
- C-grade staleness: 晶方 4d, FPS 1d — within 14-day limit ✓
- Pending approaching: PA-006 trigger 2026-05-28 = 6 calendar days → within soft window ✓
- Pending overdue: PA-007 created today = 0 trading days → not overdue ✓

**Implementation note on minimum size vs. HARD BLOCK**: The L16 rule states "单只最低$7,500" as a hard rule. However, CRM/DG/COPX were opened as acknowledged sub-threshold trial positions with documented pending actions to either raise to threshold or exit at earnings. The spec author recommends that `check_us_minimum_position_size` ALWAYS fires as a HARD BLOCK (not soft warning) for positions below $7,500 — even pending-linked ones — because the rule has no exceptions. The fix for these three is: execute PA-002/PA-003 early (close them before their earnings dates) or add capital to bring them above $7,500 before trading. This is the same logic that drove the original L16 rule creation.

**Revised expected HARD BLOCKS: 3 (not 2)**:
1. `[L16_COUNT]` US positions: 11/9 (OVER by 2)
2. `[L16_SIZE]` Below minimum: CRM $2,997, DG $2,943, COPX $2,989
3. `[L18]` Short exposure: 0% — CRITICAL

**Revised SOFT WARNINGS: 3**:
1. `[PENDING]` Urgent today: PA-007 (0d)
2. `[REGIME]` Regime check: unknown
3. `[A股_CONCENTRATION]` 安集科技 14.9% > soft threshold 12%

**PASSED: 8**

---

## Testing the Script

```bash
# Normal run against real portfolio
uv run --script scripts/pre_session_check.py

# Verify exit code
echo "Exit code: $?"  # Should be 1 (BLOCKED)

# JSON output for pipeline integration
uv run --script scripts/pre_session_check.py --json | python3 -m json.tool

# Override for emergency trading (generates audit log entry)
uv run --script scripts/pre_session_check.py --override "Emergency: must close NVDA stop-loss trigger before market opens"
```

**Test cases to verify after implementation**:

| Scenario | Expected verdict |
|----------|-----------------|
| Current portfolio (11 US longs, 0 short) | BLOCKED (3 hard blocks) |
| After reducing to 9 US longs + building $7.5K short | BLOCKED (still L16 size if CRM/DG remain) |
| After clearing CRM/DG/COPX + short built | CLEARED (if cash rules pass) |
| US cash drops below 15% | BLOCKED |
| A股 cash drops below 20% | BLOCKED |
| P1 pending action aged 3+ trading days | BLOCKED |

---

## File to Create

**Path**: `/Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts/pre_session_check.py`

**Size estimate**: ~350-450 lines of pure stdlib Python.

**No additional files** needed. The script is self-contained. Results are printed to stdout only — no file writes, no portfolio modifications.

---

*Spec version: 1.0*
*Written: 2026-05-22*
*Source files analyzed: portfolio_state.json (v6.0), pending_actions.json (v1.0), CLAUDE.md, strategy.md (v5.0), execute_trade.py, risk_monitor.py*

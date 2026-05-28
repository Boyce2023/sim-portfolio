"""
Trading System Constants — V6.2
================================
Single source of truth for all hardcoded trading parameters.
Update here; all scripts inherit automatically.

V6.2 changes from V6.0:
  - Pod I (AI Semi) BULL target: 35% → 25%  (swapped with Pod II)
  - Pod II (Energy) BULL target: 25% → 35%  (swapped with Pod I)
  - Pod IV (Short Book): ELIMINATED — all targets = 0%
  - Stop loss: fixed % → ATR-based (Entry − 2.5×ATR(14), floor −20%)
  - New regime: CORRECTION (SPY drawdown >5% from 20-day high)
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Pod Architecture (V6.2)
# ---------------------------------------------------------------------------

# Target allocation per pod as fraction of total US assets, by regime.
# V6.3: Pod C (Best Ideas / Cross-Sector) added. Pod IV eliminated in V6.2.
# Pod C takes 5-10% from I/III — any high-conviction idea regardless of sector.
POD_TARGETS: dict[str, dict[str, float]] = {
    "BULL":       {"I": 0.20, "II": 0.35, "III": 0.15, "C": 0.10, "IV": 0.00, "CASH": 0.10},
    "NEUTRAL":    {"I": 0.20, "II": 0.20, "III": 0.05, "C": 0.05, "IV": 0.00, "CASH": 0.25},
    "BEAR":       {"I": 0.15, "II": 0.15, "III": 0.00, "C": 0.00, "IV": 0.00, "CASH": 0.40},
    "CORRECTION": {"I": 0.125,"II": 0.175,"III": 0.00, "C": 0.00, "IV": 0.00, "CASH": 0.20},
}

POD_NAMES: dict[str, str] = {
    "I":   "Tech Supply Chain",
    "II":  "Energy/Infrastructure",
    "III": "Momentum",
    "C":   "Best Ideas (Cross-Sector)",
    "IV":  "Short Book (ELIMINATED in V6.2)",
}

# Tolerance band for on-target classification (±2% of target)
POD_REBALANCE_TOLERANCE_PCT = 2.0

# ---------------------------------------------------------------------------
# Regime Detection Thresholds
# ---------------------------------------------------------------------------

REGIME_THRESHOLDS: dict[str, dict] = {
    # NEW in V6.2: triggered before BEAR
    "CORRECTION": {
        "spy_drawdown_20d": 0.05,   # SPY drops >5% from 20-day high
    },
    "BEAR": {
        "spy_drawdown_20d": 0.10,   # SPY drops >10% from 20-day high
        "vix_above": 30,
    },
    # Rule-based detector factor weights (regime_detection.py)
    "factor_weights": {
        "vix":           0.35,
        "ma_cross":      0.25,
        "yield_curve":   0.20,
        "credit_spread": 0.20,
    },
    # Factor score boundaries
    "vix_bull":              15.0,
    "vix_bear":              25.0,
    "vix_crisis":            35.0,
    "spread_10y2y_bull":      0.50,   # 50 bps steepening = bull
    "spread_10y2y_bear":      0.00,   # inversion = bear
    "hyg_lqd_change_bear":   -0.02,
    "hyg_lqd_change_crisis": -0.05,
    "ma_buffer":              0.005,  # 0.5% buffer around MA cross to reduce whipsaw
    # Composite score thresholds for final classification
    "bull_score_threshold":   0.30,
    "bear_score_threshold":  -0.30,
}

# Minimum days to hold a regime before switching (anti-flapping)
REGIME_MIN_HOLD_DAYS: dict[str, int] = {
    "bull":      10,
    "sideways":   5,
    "bear":       5,
    "crisis":     0,   # always immediate
}

# ---------------------------------------------------------------------------
# ATR Stop Loss (V6.2)
# ---------------------------------------------------------------------------

# Stop = Entry − ATR_STOP_K × ATR(ATR_STOP_PERIOD)
# Capped at ATR_STOP_FLOOR_PCT below entry regardless of ATR
ATR_STOP: dict[str, float | int] = {
    "K":         2.5,    # multiplier (V6.2: changed from fixed %)
    "period":    14,     # ATR lookback window in trading days
    "floor_pct": -0.20,  # maximum allowed loss floor (−20%)
    "fallback_pct": -0.15,  # used when ATR data unavailable
}

SHORT_STOP_LOSS_PCT: float = 0.15  # short position stop: +15% adverse move

# Per-grade ATR K values used by A-share system (strategy.md §2)
ASTOCK_ATR_K: dict[str, float] = {
    "S":  3.5,
    "A+": 3.0,
    "A":  3.0,
    "A-": 2.5,
    "B+": 2.0,
    "B":  2.0,
    "B-": 1.5,
}

# Per-grade hard stop floor (A-share, strategy.md §2)
ASTOCK_HARD_STOP_PCT: dict[str, float] = {
    "S":  -0.20,
    "A+": -0.18,
    "A":  -0.15,
    "A-": -0.15,
    "B+": -0.12,
    "B":  -0.10,
    "B-": -0.10,
}

# ---------------------------------------------------------------------------
# Position Limits — A-Share (SABCT grades, strategy.md v8.x §2)
# ---------------------------------------------------------------------------

ASTOCK_POSITION_LIMITS: dict[str, float] = {
    "S":  0.50,
    "A+": 0.35,
    "A":  0.25,
    "A-": 0.20,
    "B+": 0.15,
    "B":  0.12,
    "B-": 0.10,
}

# Grades valid for A-share buy orders (no C/T/waiver)
ASTOCK_VALID_GRADES: frozenset[str] = frozenset(ASTOCK_POSITION_LIMITS.keys())

# ---------------------------------------------------------------------------
# Position Limits — US (SABCT grades, US_TRADING_SYSTEM_V6.md §2)
# ---------------------------------------------------------------------------

US_POSITION_LIMITS: dict[str, float] = {
    "A+": 0.20,
    "A":  0.15,
    "A-": 0.12,
    "B+": 0.10,
    "B":  0.08,
    "B-": 0.05,
}

# A+/A/A- count limit REMOVED per user instruction (2026-05-27).
# Flexible allocation by conviction ranking, no hard cap.
US_MAX_HIGH_CONVICTION = None

# ---------------------------------------------------------------------------
# Sector / Concentration Limits
# ---------------------------------------------------------------------------

ASTOCK_SECTOR_LIMIT     = 0.35   # single sector ≤ 35% of A-share total assets (v7.0)
ASTOCK_MAX_POSITIONS    = 5      # SOFT target — "尽量≤5只" (strategy.md v8.3 R2)
ASTOCK_MAX_POSITIONS_FLEX = 7    # HARD block — elastic upper bound (弹性至7只)
# 语义: 5只=软提醒(WARN), 7只=硬拒绝(BLOCK). 5-7之间允许操作但提示注意控制。

US_TECH_SUPPLY_LIMIT    = 0.40   # Pod I (Tech Supply Chain) sector cap
US_ENERGY_LIMIT         = 0.35   # Pod II (Energy/Infrastructure) sector cap
US_BEST_IDEAS_LIMIT     = 0.15   # Pod C (Best Ideas / Cross-Sector) sector cap
US_MAX_POSITIONS        = 12     # max US long positions
US_MAX_POSITIONS_L16    = 9      # L16 hard cap enforced by compliance_check

# Compliance: absolute single-position hard cap (A-share, safety net — S级可达50%)
ASTOCK_SINGLE_POSITION_CAP = 0.50

# ---------------------------------------------------------------------------
# Short Book Limits (US only — Pod IV eliminated in V6.2 but shorts still allowed)
# ---------------------------------------------------------------------------

SHORT_LIMITS: dict[str, float] = {
    "max_gross":       300_000,   # USD total gross short exposure cap (≈2× leverage)
    "max_single_pct":    0.10,   # single short position ≤ 10% of US total assets
    "auto_stop_pct":     0.15,   # auto stop-loss: +15% move against short
    "target_min_pct":    0.10,   # L18: target short exposure ≥ 10% of US assets
    "target_max_pct":    0.15,   # L18: target short exposure ≤ 15%
    "hard_floor_pct":    0.05,   # L18: hard floor; below → WARNING
    "critical_days_no_short": 5, # L18: consecutive trading days at 0% → CRITICAL
}

# Do-not-short list (compliance_check.py)
DO_NOT_SHORT: frozenset[str] = frozenset({"META", "NVDA", "AVGO", "AAPL", "MSFT", "GOOGL"})

# ---------------------------------------------------------------------------
# Account Defaults
# ---------------------------------------------------------------------------

ACCOUNTS: dict[str, dict] = {
    "a_share": {
        "key":             "a_share",
        "initial_capital": 10_000_000,   # CNY ¥10M
        "currency":        "CNY",
        "max_positions":   ASTOCK_MAX_POSITIONS,
        "lot_size":        100,           # A-share minimum trading unit (shares)
        "benchmark":       "沪深300",
        "min_cash_pct":    0.20,          # must keep ≥ 20% cash at all times
    },
    "us": {
        "key":             "us",
        "initial_capital": 1_500_000,      # USD $1.5M
        "currency":        "USD",
        "max_positions":   US_MAX_POSITIONS,
        "lot_size":        1,             # US equities: 1 share minimum
        "benchmark":       "SPY",
        "min_cash_pct":    0.10,          # BULL minimum; rises in lower regimes
        "min_position_usd": 7_500,        # L16: positions below this are undersized
    },
}

# Cash minimums by regime (US account)
US_CASH_FLOOR_BY_REGIME: dict[str, float] = {
    "BULL":       0.10,
    "NEUTRAL":    0.25,
    "BEAR":       0.40,
    "CORRECTION": 0.20,
    "CRISIS":     0.70,
}

# ---------------------------------------------------------------------------
# Trading Budget (both markets)
# ---------------------------------------------------------------------------

TRADING_BUDGET: dict[str, int] = {
    "daily_new_positions":  2,   # SOFT target — max new positions opened per calendar day
    "weekly_total_trades":  8,   # SOFT target — "≤8笔" (strategy.md), WARN不BLOCK
}
# 语义: 超出时发WARN提醒，不硬BLOCK交易。灵活执行，避免错过催化剂窗口。

# ---------------------------------------------------------------------------
# Bear Case 4-Tier Filter (F9 v2)
# ---------------------------------------------------------------------------

# Applied universally at buy validation; tiers determine position sizing.
BEAR_CASE_TIERS: dict[str, dict] = {
    "T1": {"max_downside": -0.15, "label": "Green — full position allowed"},
    "T2": {"max_downside": -0.25, "label": "Yellow — half position, await catalyst"},
    "T3": {"max_downside": -0.40, "label": "Orange — watch only (US: no position)"},
    "T4": {"max_downside": None,  "label": "Red — hard exclusion from long universe"},
}

# Horizon used for bear case calculation
BEAR_CASE_HORIZON_MONTHS: dict[str, int] = {
    "astock": 12,
    "us":     18,
}

# ---------------------------------------------------------------------------
# Circuit Breaker (peak NAV drawdown)
# ---------------------------------------------------------------------------

CIRCUIT_BREAKER: dict[str, float] = {
    "warn_dd":      -0.05,   # −5%: pause new positions
    "critical_dd":  -0.10,   # −10%: reduce to ≥50% cash
    "emergency_dd": -0.15,   # −15%: recommend full liquidation
}

# ---------------------------------------------------------------------------
# VIX Exposure Scaling
# ---------------------------------------------------------------------------

VIX_LEVELS: dict[str, float] = {
    "normal":    20.0,   # below → no action required
    "warn":      20.0,   # above → no new positions (same threshold)
    "reduce":    25.0,   # above → gross exposure < 60%
    "emergency": 35.0,   # above → ≥70% cash, defensive only; also triggers CRISIS regime
}

# ---------------------------------------------------------------------------
# Risk Monitor Thresholds (risk_monitor.py)
# ---------------------------------------------------------------------------

RISK_MONITOR: dict[str, float | int] = {
    "max_single_pct":          35.0,   # single-position weight % cap (portfolio-wide)
    "max_sector_pct":          35.0,   # sector weight % cap (portfolio-wide)
    "min_cash_pct":            20.0,   # minimum cash % across all accounts
    "max_portfolio_drawdown":  -10.0,  # portfolio-level drawdown trigger %
    "stop_buffer_pct":          5.0,   # near-stop warning zone %
    "stop_alert_pct":           3.0,   # critical near-stop zone % (<3% from stop)
    "max_positions_astock":     ASTOCK_MAX_POSITIONS_FLEX,  # A-share HARD block (弹性上限)
    "max_positions_astock_soft": ASTOCK_MAX_POSITIONS,      # A-share soft target (提醒)
    "max_sector_positions":     3,     # same-sector position count alert threshold
    "max_broad_sector_positions": 3,   # broad-bucket correlation alert threshold
    "catalyst_high_days":       2,     # catalyst within ≤2 days → HIGH alert
    "catalyst_info_days":       7,     # catalyst within ≤7 days → INFO alert
    "s_grade_max_trading_days": 10,    # S-grade held >10 trading days → CRITICAL
    "health_score_critical_deduct": 20,
    "health_score_high_deduct":     10,
    "health_score_medium_deduct":    5,
}

# ---------------------------------------------------------------------------
# Compliance Rules — US (compliance_check.py)
# ---------------------------------------------------------------------------

COMPLIANCE_US: dict[str, float | int] = {
    # L16 — Shotgun Ban
    "max_long_positions":     9,       # hard cap on US long positions
    "min_position_value_usd": 7_500,   # undersized floor

    # L17 — Regime Awareness
    "regime_stale_hours":     24,      # regime.json older than this → WARNING
    "regime_adjust_window_h": 24,      # portfolio must adjust within 24h of shift
    "macro_event_warn_days":   3,      # flag macro events within 3 calendar days
    "vix_delta_5d_signal":     3.0,    # 5-day VIX spike ≥ 3 points → flag

    # L18 — Short Quota
    "short_target_min_pct":   0.10,
    "short_target_max_pct":   0.15,
    "short_hard_floor_pct":   0.05,
    "critical_days_no_short":  5,

    # Consecutive-violation escalation
    "consecutive_violation_escalation_days": 3,
}

# ---------------------------------------------------------------------------
# OTC / YFinance Ticker Remapping
# ---------------------------------------------------------------------------

YF_TICKER_MAP: dict[str, str] = {
    "SPUT": "SRUUF",   # Sprott Uranium Trust trades OTC as SRUUF on yfinance
}

# ---------------------------------------------------------------------------
# Rotation Detection (weekly_screen.py / rotation_scan.py)
# ---------------------------------------------------------------------------

ROTATION: dict[str, float] = {
    "rotate_out_avg_threshold": -3.0,   # pod avg pnl% below this → ROTATE_OUT
    "strong_pod_avg_threshold":  3.0,   # pod avg pnl% above this → STRONG
    "near_stop_warn_pct":        5.0,   # stop distance < 5% → warn in weekly screen
    "drawdown_flag_pct":        -10.0,  # position pnl% below → DRAWDOWN flag
}

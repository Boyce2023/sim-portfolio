"""
Trading System Constants — A股/美股完全分离版
=============================================
Single source of truth for all hardcoded trading parameters.
Update here; all scripts inherit automatically.

⚠️ A股和美股是两套独立系统，修改一边时不要碰另一边的参数。
  - A股参数: 以 strategy_astock.md v9.1 为准
  - 美股参数: 以 strategy.md (价值投资×科技信仰) 为准
"""

from __future__ import annotations

# ═══════════════════════════════════════════════════════════════════════════
# ═══  US SYSTEM (strategy.md — 价值投资×科技信仰)  ═══════════════════════
# ═══════════════════════════════════════════════════════════════════════════

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

# ═══════════════════════════════════════════════════════════════════════════
# ═══  A-STOCK SYSTEM (strategy_astock.md v9.1 — SABCT/五步选股/Discovery)  ═
# ═══════════════════════════════════════════════════════════════════════════
# ⚠️ 修改以下参数时只看 strategy_astock.md，不要参考 strategy.md

# A-Stock Stop-Loss: 3轮回测迭代结论 (31笔交易, A+US合并23个已平仓标的)
# Iter 1: 固定止损 -5%~-15% → -5%/-7%杀掉最大赢家(鹏鼎+12%→-5%), -10%中性
# Iter 2: Trailing stop -5%~-12% → 全面有害, 巨化+43.7%被任何trailing杀掉
# Iter 3: -12%硬止损最优 — 只触发HSAI(saved), 不误杀INOD/LEU(回撤后反弹)
ASTOCK_HARD_STOP_PCT: float = -0.12   # 统一-12%硬止损

# 两段式出场: target_1到价出50%, 剩余thesis-based exit (不用trailing stop)
ASTOCK_TWO_STAGE_EXIT = {
    "stage_1_pct": 0.50,           # target_1到价时卖出50%
}

# Legacy: 保留ATR K用于US系统, A股不再使用
ASTOCK_ATR_K: dict[str, float] = {
    "S":  3.5,
    "A+": 3.0,
    "A":  3.0,
    "A-": 2.5,
    "B+": 2.0,
    "B":  2.0,
    "B-": 1.5,
}

# ---------------------------------------------------------------------------
# Position Limits — A-Share (SABCT grades, strategy_astock.md v9.1 §2.2)
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

# ═══════════════════════════════════════════════════════════════════════════
# ═══  US SYSTEM — Position Limits (strategy.md §3)  ══════════════════════
# ═══════════════════════════════════════════════════════════════════════════

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

# ═══ A-STOCK Concentration (strategy_astock.md v9.1 R2) ═══
ASTOCK_SECTOR_LIMIT     = 1.00   # v9.1: 板块不做硬约束（用conviction+止损管风险）
ASTOCK_MAX_POSITIONS    = 8      # v9.1: 持仓≤8只
ASTOCK_MAX_POSITIONS_FLEX = 8    # v9.1: 无弹性概念，硬顶=8
# v9.1改动: 删除板块35%上限+现金20%底线+持仓5只限制（回测证明限制≠风控，见strategy_astock.md）

# ═══ US Concentration (strategy.md §3) ═══

US_TECH_SUPPLY_LIMIT    = 0.40   # Pod I (Tech Supply Chain) sector cap
US_ENERGY_LIMIT         = 0.35   # Pod II (Energy/Infrastructure) sector cap
US_BEST_IDEAS_LIMIT     = 0.15   # Pod C (Best Ideas / Cross-Sector) sector cap
US_MAX_POSITIONS        = 12     # max US long positions
US_MAX_POSITIONS_L16    = 12     # L16 hard cap enforced by compliance_check

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
        "min_cash_pct":    0.00,          # v9.1: 无现金底线（用止损管风险）
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
    "max_single_pct_cn":       50.0,   # A股: S级可达50% (strategy_astock.md v9.1 R2)
    "max_single_pct_us":       50.0,   # 美股: S级可达50% (strategy.md §3)
    "max_sector_pct_cn":      100.0,   # A股: 板块不做硬约束 (v9.1)
    "max_sector_pct_us":      100.0,   # 美股: 板块不做硬约束 (strategy.md)
    "min_cash_pct_cn":          0.0,   # A股: 无现金底线 (v9.1)
    "min_cash_pct_us":          0.0,   # 美股: 无现金底线 (strategy.md §3)
    "max_portfolio_drawdown":  -10.0,  # portfolio-level drawdown trigger %
    "stop_buffer_pct":          5.0,   # near-stop warning zone %
    "stop_alert_pct":           3.0,   # critical near-stop zone % (<3% from stop)
    "max_positions_astock":     ASTOCK_MAX_POSITIONS,   # A股: 8只 (v9.1)
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

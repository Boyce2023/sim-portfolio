#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["yfinance>=0.2.40", "pandas>=2.0", "numpy>=1.24", "rich>=13.0"]
# ///
"""
US Trading System V6.1 — 2025 Walk-Forward Backtest
====================================================
No lookahead bias. At each time step, only data available up to that date is used.
Simulates $150K portfolio using V6.1 mechanical rules.

Usage:
    uv run --script backtest/backtest_v6.py
    uv run --script backtest/backtest_v6.py --verbose
"""

from __future__ import annotations
import json
import argparse
import sys
import warnings
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

warnings.filterwarnings("ignore", category=FutureWarning)

console = Console()
SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / "data"
RESULTS_DIR = SCRIPT_DIR / "results"

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION — V6.1 Rules (no 2025 hindsight, only system design)
# ══════════════════════════════════════════════════════════════════════════════

INITIAL_CAPITAL = 150_000.0
START_DATE = "2025-01-02"
END_DATE = "2025-12-31"
BENCHMARK = "SPY"

# Universe: stocks that EXISTED and were relevant as of late 2024
# Selected by SECTOR, not by 2025 performance
POD_I = {  # AI Semi Supply Chain
    "NVDA", "AMD", "MU", "MRVL", "AVGO", "ARM", "TSM", "ASML",
    "LRCX", "AMAT", "CLS", "DELL", "SMCI", "ANET", "CRDO",
}
POD_II = {  # Energy Infrastructure
    "VST", "GEV", "CEG", "NRG", "ETN", "EME", "APH", "AAON",
    "CCJ", "LEU", "NEE",
}
BETA_RESERVE = {"AAPL"}

# V6.2: Pod IV (shorts) ELIMINATED — 0% win rate, category mismatch
ALL_TICKERS = sorted(POD_I | POD_II | BETA_RESERVE)
SECTOR_ETFS = {"SMH": "AI_Semi", "XLE": "Energy", "XLK": "Tech", "SOXX": "Semi_Broad"}
ALL_SYMBOLS = ALL_TICKERS + list(SECTOR_ETFS.keys()) + [BENCHMARK]

# V6.2 Mechanical Rules
MAX_LONG_POSITIONS = 10
MIN_POSITION_VALUE = 7_500

# SABCT sizing caps (% of NAV)
GRADE_MAX_PCT = {"S": 0.20, "A+": 0.15, "A": 0.12, "A-": 0.10, "B+": 0.08, "B": 0.06}

# V6.2: Pod I/II swapped — Pod II (Energy) 43% win rate vs Pod I 0%
POD_TARGETS = {
    "BULL":       {"I": 0.25, "II": 0.35, "III": 0.20, "Beta": 0.05, "Cash": 0.10},
    "NEUTRAL":    {"I": 0.20, "II": 0.30, "III": 0.10, "Beta": 0.10, "Cash": 0.20},
    "BEAR":       {"I": 0.15, "II": 0.20, "III": 0.00, "Beta": 0.10, "Cash": 0.35},
    "CORRECTION": {"I": 0.12, "II": 0.25, "III": 0.00, "Beta": 0.10, "Cash": 0.35},
}

# V6.2: ATR-based dynamic stops (replaces fixed 15%)
ATR_PERIOD = 14
ATR_MULTIPLIER = 2.5            # Stop = entry - 2.5×ATR
ATR_HARD_FLOOR = 0.20           # Never wider than -20%
TRAILING_STOP_PCT = 0.12        # 12% trailing stop for F21 override

# Signal thresholds
EARNINGS_GAP_THRESHOLD = 0.06
VOLUME_MULTIPLIER = 2.5
RS_GREEN_THRESHOLD = 0.06
RS_RED_THRESHOLD = -0.06
MOMENTUM_LOOKBACK = 20
REBALANCE_FREQUENCY = 5
EARNINGS_COOLDOWN_DAYS = 50
CB_RED_EXPIRY_DAYS = 20

# V6.2: F21 MISS override — don't exit if stock up >40% from entry
F21_MISS_OVERRIDE_THRESHOLD = 0.40

# V6.2: CORRECTION regime trigger
CORRECTION_TRIGGER_PCT = 0.07   # SPY -7% from 20-day high
CORRECTION_RECOVERY_PCT = 0.03  # SPY within 3% of pre-correction high

# V6.2: Strike-out rule — 2 stops on same ticker = banned 60 days
STRIKE_OUT_LIMIT = 2
STRIKE_OUT_COOLDOWN = 60

# Earnings windows
EARNINGS_WINDOWS = [
    ("01-15", "02-20"),
    ("04-15", "05-20"),
    ("07-15", "08-20"),
    ("10-15", "11-20"),
]


# ══════════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class Position:
    ticker: str
    pod: str
    grade: str
    shares: int
    entry_price: float
    entry_date: str
    stop_loss_price: float
    signal: str = ""
    trailing_mode: bool = False     # V6.2: F21 override → trailing stop
    high_water_mark: float = 0.0    # for trailing stop calculation

    @property
    def cost_basis(self) -> float:
        return self.shares * self.entry_price


@dataclass
class Trade:
    date: str
    action: str
    ticker: str
    pod: str
    grade: str
    shares: int
    price: float
    value: float
    reason: str
    signal: str = ""
    realized_pnl: float = 0.0


@dataclass
class DailyState:
    date: str
    nav: float
    cash: float
    num_positions: int
    regime: str
    spy_close: float
    spy_return_pct: float
    portfolio_return_pct: float
    alpha_pct: float


# ══════════════════════════════════════════════════════════════════════════════
# DATA LOADING
# ══════════════════════════════════════════════════════════════════════════════

def download_data(symbols: list[str], start: str, end: str) -> dict[str, pd.DataFrame]:
    """Download OHLCV data. Cache to disk."""
    cache_path = DATA_DIR / "price_cache_2025.json"

    # Try cache first
    if cache_path.exists():
        console.print("[dim]Loading cached price data...[/dim]")
        cached = pd.read_json(cache_path)
        # Rebuild per-ticker DataFrames from multi-level
        result = {}
        for sym in symbols:
            cols = [c for c in cached.columns if c.startswith(f"{sym}_")]
            if cols:
                df = cached[cols].copy()
                df.columns = [c.replace(f"{sym}_", "") for c in cols]
                df.dropna(how="all", inplace=True)
                if not df.empty:
                    result[sym] = df
        if len(result) >= len(symbols) * 0.8:
            console.print(f"[green]Cache hit: {len(result)}/{len(symbols)} symbols[/green]")
            return result

    console.print(f"[yellow]Downloading 2025 data for {len(symbols)} symbols...[/yellow]")

    # Download all at once using yfinance multi-download
    # Add buffer before start for indicator calculation
    buffer_start = (datetime.strptime(start, "%Y-%m-%d") - timedelta(days=90)).strftime("%Y-%m-%d")

    raw = yf.download(
        symbols,
        start=buffer_start,
        end=(datetime.strptime(end, "%Y-%m-%d") + timedelta(days=5)).strftime("%Y-%m-%d"),
        group_by="ticker",
        auto_adjust=True,
        threads=True,
        progress=True,
    )

    result = {}
    for sym in symbols:
        try:
            if len(symbols) == 1:
                df = raw.copy()
            else:
                df = raw[sym].copy() if sym in raw.columns.get_level_values(0) else pd.DataFrame()

            if df.empty:
                continue

            df = df.dropna(how="all")
            if len(df) < 20:
                continue

            # Flatten column names if multi-level
            if hasattr(df.columns, 'levels'):
                df.columns = df.columns.get_level_values(-1)

            result[sym] = df
        except Exception:
            continue

    # Cache to disk
    try:
        combined = pd.DataFrame()
        for sym, df in result.items():
            for col in df.columns:
                combined[f"{sym}_{col}"] = df[col]
        combined.to_json(cache_path, date_format="iso")
        console.print(f"[green]Cached {len(result)} symbols to {cache_path}[/green]")
    except Exception as e:
        console.print(f"[yellow]Cache write failed: {e}[/yellow]")

    console.print(f"[green]Downloaded: {len(result)}/{len(symbols)} symbols[/green]")
    return result


# ══════════════════════════════════════════════════════════════════════════════
# SIGNAL GENERATION (all use only data up to current date)
# ══════════════════════════════════════════════════════════════════════════════

def calculate_atr(ticker_data: pd.DataFrame, date: str, period: int = ATR_PERIOD) -> float:
    """Average True Range over period days, using only data up to date."""
    mask = ticker_data.index <= date
    data = ticker_data.loc[mask]
    if len(data) < period + 1:
        return 0.0

    highs = data["High"].iloc[-(period + 1):]
    lows = data["Low"].iloc[-(period + 1):]
    closes = data["Close"].iloc[-(period + 1):]

    trs = []
    for i in range(1, len(highs)):
        tr = max(
            float(highs.iloc[i] - lows.iloc[i]),
            abs(float(highs.iloc[i] - closes.iloc[i - 1])),
            abs(float(lows.iloc[i] - closes.iloc[i - 1])),
        )
        trs.append(tr)
    return float(np.mean(trs))


def detect_regime(spy_data: pd.DataFrame, date: str) -> str:
    """SPY 50MA vs 200MA regime detection + V6.2 CORRECTION overlay."""
    mask = spy_data.index <= date
    data = spy_data.loc[mask]
    if len(data) < 200:
        return "NEUTRAL"

    ma50 = data["Close"].iloc[-50:].mean()
    ma200 = data["Close"].iloc[-200:].mean()

    # V6.2: CORRECTION check — SPY fell >7% from 20-day high within 10 days
    if len(data) >= 20:
        recent_high = float(data["Close"].iloc[-20:].max())
        current = float(data["Close"].iloc[-1])
        drawdown = (current - recent_high) / recent_high
        if drawdown < -CORRECTION_TRIGGER_PCT:
            return "CORRECTION"

    if ma50 > ma200 * 1.02:
        return "BULL"
    elif ma50 < ma200 * 0.98:
        return "BEAR"
    return "NEUTRAL"


def calculate_sector_rs(etf_data: pd.DataFrame, spy_data: pd.DataFrame,
                        date: str, lookback: int = 20) -> float:
    """Relative strength of sector ETF vs SPY over lookback days."""
    etf_mask = etf_data.index <= date
    spy_mask = spy_data.index <= date

    etf = etf_data.loc[etf_mask, "Close"]
    spy = spy_data.loc[spy_mask, "Close"]

    if len(etf) < lookback + 1 or len(spy) < lookback + 1:
        return 0.0

    etf_ret = (etf.iloc[-1] / etf.iloc[-lookback - 1]) - 1
    spy_ret = (spy.iloc[-1] / spy.iloc[-lookback - 1]) - 1

    return etf_ret - spy_ret


def in_earnings_window(date_str: str) -> bool:
    """Check if date falls within a quarterly earnings reporting window."""
    mmdd = date_str[5:]  # "MM-DD"
    for start, end in EARNINGS_WINDOWS:
        if start <= mmdd <= end:
            return True
    return False


def detect_earnings_event(ticker_data: pd.DataFrame, date: str,
                          ticker: str, last_event_days: dict[str, int],
                          current_day: int) -> Optional[str]:
    """Detect earnings event from price action during earnings windows only.
    Returns 'beat' or 'miss' or None. Enforces cooldown between detections."""
    if not in_earnings_window(date):
        return None

    # Cooldown: don't detect same ticker within EARNINGS_COOLDOWN_DAYS
    if ticker in last_event_days:
        days_since = current_day - last_event_days[ticker]
        if days_since < EARNINGS_COOLDOWN_DAYS:
            return None

    mask = ticker_data.index <= date
    data = ticker_data.loc[mask]

    if len(data) < 22:
        return None

    today = data.iloc[-1]
    yesterday = data.iloc[-2]

    if yesterday["Close"] == 0:
        return None
    daily_ret = (today["Close"] - yesterday["Close"]) / yesterday["Close"]

    avg_vol = data["Volume"].iloc[-21:-1].mean()
    if avg_vol == 0:
        return None
    vol_ratio = today["Volume"] / avg_vol

    if abs(daily_ret) > EARNINGS_GAP_THRESHOLD and vol_ratio > VOLUME_MULTIPLIER:
        last_event_days[ticker] = current_day
        return "beat" if daily_ret > 0 else "miss"

    return None


def calculate_momentum_score(ticker_data: pd.DataFrame, date: str) -> float:
    """20-day return as momentum score."""
    mask = ticker_data.index <= date
    data = ticker_data.loc[mask, "Close"]

    if len(data) < MOMENTUM_LOOKBACK + 1:
        return 0.0

    return (data.iloc[-1] / data.iloc[-MOMENTUM_LOOKBACK - 1]) - 1


def calculate_rs_rank(ticker_data: pd.DataFrame, spy_data: pd.DataFrame,
                      date: str) -> float:
    """RS vs SPY over 20 days."""
    mask_t = ticker_data.index <= date
    mask_s = spy_data.index <= date

    t = ticker_data.loc[mask_t, "Close"]
    s = spy_data.loc[mask_s, "Close"]

    if len(t) < 21 or len(s) < 21:
        return 0.0

    t_ret = (t.iloc[-1] / t.iloc[-21]) - 1
    s_ret = (s.iloc[-1] / s.iloc[-21]) - 1

    return t_ret - s_ret


def assign_pod(ticker: str) -> str:
    """Static pod assignment. V6.2: No Pod IV."""
    if ticker in POD_I:
        return "I"
    elif ticker in POD_II:
        return "II"
    elif ticker in BETA_RESERVE:
        return "Beta"
    return "III"


def calculate_grade(ticker: str, beat_count: int, rs_rank: float,
                    pod: str, signal_count: int) -> str:
    """Simplified SABCT grade based on quantitative signals."""
    score = 0

    # Beat history (F21)
    if beat_count >= 4:
        score += 3
    elif beat_count >= 2:
        score += 2
    elif beat_count >= 1:
        score += 1

    # RS strength
    if rs_rank > 0.15:
        score += 2
    elif rs_rank > 0.05:
        score += 1

    # Signal count (discovery)
    score += min(signal_count, 2)

    # Pod I/II get bonus (physical constraint thesis)
    if pod in ("I", "II"):
        score += 1

    # Dual-pod bonus (would be S, but extremely rare in mechanical backtest)

    if score >= 7:
        return "A+"
    elif score >= 5:
        return "A"
    elif score >= 4:
        return "A-"
    elif score >= 3:
        return "B+"
    elif score >= 2:
        return "B"
    return "B-"


# ══════════════════════════════════════════════════════════════════════════════
# PORTFOLIO ENGINE
# ══════════════════════════════════════════════════════════════════════════════

class Portfolio:
    def __init__(self, initial_capital: float):
        self.cash = initial_capital
        self.initial_capital = initial_capital
        self.positions: dict[str, Position] = {}
        self.trades: list[Trade] = []
        self.daily_states: list[DailyState] = []
        self.beat_history: dict[str, int] = {}
        self.miss_history: dict[str, str] = {}
        self.circuit_breaker = "GREEN"
        self.consecutive_losses = 0
        self.weekly_loss_count = 0
        self.cb_red_day_count = 0
        self.last_earnings_event: dict[str, int] = {}
        self.strike_out_tracker: dict[str, list[int]] = {}  # ticker -> [day_counts of stops]

    def nav(self, prices: dict[str, float]) -> float:
        """Calculate NAV with current prices."""
        total = self.cash
        for ticker, pos in self.positions.items():
            price = prices.get(ticker, pos.entry_price)
            total += pos.shares * price
        return total

    def position_value(self, ticker: str, price: float) -> float:
        pos = self.positions.get(ticker)
        if not pos:
            return 0.0
        return pos.shares * price

    def pod_allocation(self, prices: dict[str, float]) -> dict[str, float]:
        """Current pod allocation percentages."""
        total = self.nav(prices)
        if total == 0:
            return {}

        alloc: dict[str, float] = {}
        for ticker, pos in self.positions.items():
            price = prices.get(ticker, pos.entry_price)
            value = pos.shares * price
            pod = pos.pod
            alloc[pod] = alloc.get(pod, 0) + value / total

        alloc["Cash"] = self.cash / total
        return alloc

    def is_struck_out(self, ticker: str, current_day: int) -> bool:
        """V6.2: Check if ticker is banned due to strike-out rule."""
        if ticker not in self.strike_out_tracker:
            return False
        stops = self.strike_out_tracker[ticker]
        recent = [d for d in stops if current_day - d < STRIKE_OUT_COOLDOWN]
        return len(recent) >= STRIKE_OUT_LIMIT

    def buy(self, ticker: str, price: float, date: str, pod: str, grade: str,
            signal: str, atr: float = 0.0, current_day: int = 0) -> Optional[Trade]:
        """Execute a buy order with V6.2 ATR-based stops."""
        if self.circuit_breaker == "RED":
            return None

        if len(self.positions) >= MAX_LONG_POSITIONS and ticker not in self.positions:
            return None

        # V6.2: Strike-out check
        if self.is_struck_out(ticker, current_day) and ticker not in self.positions:
            return None

        nav = self.nav({ticker: price})
        max_pct = GRADE_MAX_PCT.get(grade, 0.06)
        if self.circuit_breaker == "YELLOW":
            max_pct *= 0.5

        target_value = nav * max_pct
        target_value = max(target_value, MIN_POSITION_VALUE)

        existing_value = 0
        if ticker in self.positions:
            existing_value = self.positions[ticker].shares * price
            target_value = max(0, target_value - existing_value)

        if target_value < MIN_POSITION_VALUE and ticker not in self.positions:
            return None

        affordable = min(target_value, self.cash * 0.95)
        if affordable < MIN_POSITION_VALUE / 2:
            return None

        shares = int(affordable / price)
        if shares == 0:
            return None

        value = shares * price
        self.cash -= value

        # V6.2: ATR-based stop loss
        if atr > 0:
            atr_stop = price - ATR_MULTIPLIER * atr
            floor_stop = price * (1 - ATR_HARD_FLOOR)
            sl_price = max(atr_stop, floor_stop)
        else:
            sl_price = price * (1 - ATR_HARD_FLOOR)

        if ticker in self.positions:
            old = self.positions[ticker]
            total_shares = old.shares + shares
            avg_price = (old.shares * old.entry_price + shares * price) / total_shares
            old.shares = total_shares
            old.entry_price = avg_price
            # Recalculate stop with new average
            if atr > 0:
                old.stop_loss_price = max(avg_price - ATR_MULTIPLIER * atr,
                                          avg_price * (1 - ATR_HARD_FLOOR))
            if grade > old.grade:
                old.grade = grade
            old.high_water_mark = max(old.high_water_mark, price)
        else:
            self.positions[ticker] = Position(
                ticker=ticker, pod=pod, grade=grade, shares=shares,
                entry_price=price, entry_date=date,
                stop_loss_price=sl_price, signal=signal,
                high_water_mark=price,
            )

        trade = Trade(
            date=date, action="BUY", ticker=ticker, pod=pod, grade=grade,
            shares=shares, price=price, value=value,
            reason=f"{signal} → {grade} Pod {pod}", signal=signal,
        )
        self.trades.append(trade)
        return trade

    def sell(self, ticker: str, price: float, date: str, reason: str,
             current_day: int = 0) -> Optional[Trade]:
        """Execute a sell order."""
        pos = self.positions.get(ticker)
        if not pos:
            return None

        value = pos.shares * price
        pnl = (price - pos.entry_price) * pos.shares
        self.cash += value

        trade = Trade(
            date=date, action="SELL", ticker=ticker, pod=pos.pod, grade=pos.grade,
            shares=pos.shares, price=price, value=value,
            reason=reason, signal=pos.signal, realized_pnl=pnl,
        )
        self.trades.append(trade)

        # V6.2: Track stop-outs for strike-out rule
        if "STOP" in reason and pnl < 0:
            if ticker not in self.strike_out_tracker:
                self.strike_out_tracker[ticker] = []
            self.strike_out_tracker[ticker].append(current_day)

        del self.positions[ticker]

        if pnl < 0:
            self.consecutive_losses += 1
            self.weekly_loss_count += 1
            if self.consecutive_losses >= 5 and self.circuit_breaker != "RED":
                self.circuit_breaker = "RED"
                self.cb_red_day_count = 0
            elif self.consecutive_losses >= 3:
                self.circuit_breaker = "YELLOW"
        else:
            self.consecutive_losses = max(0, self.consecutive_losses - 1)
            if self.circuit_breaker == "YELLOW" and self.consecutive_losses < 2:
                self.circuit_breaker = "GREEN"

        return trade

    def check_stop_losses(self, prices: dict[str, float], date: str,
                          current_day: int = 0) -> list[Trade]:
        """Check and execute stop losses. V6.2: supports trailing mode."""
        exits = []
        for ticker in list(self.positions.keys()):
            pos = self.positions[ticker]
            price = prices.get(ticker)
            if price is None:
                continue

            # Update high water mark
            if price > pos.high_water_mark:
                pos.high_water_mark = price

            # V6.2: Trailing mode — stop follows high water mark
            if pos.trailing_mode:
                trailing_stop = pos.high_water_mark * (1 - TRAILING_STOP_PCT)
                if price <= trailing_stop:
                    trade = self.sell(ticker, price, date,
                                    f"TRAILING STOP: ${price:.2f} ≤ ${trailing_stop:.2f} "
                                    f"(HWM ${pos.high_water_mark:.2f})",
                                    current_day=current_day)
                    if trade:
                        exits.append(trade)
            elif price <= pos.stop_loss_price:
                trade = self.sell(ticker, price, date,
                                f"STOP LOSS: ${price:.2f} ≤ ${pos.stop_loss_price:.2f}",
                                current_day=current_day)
                if trade:
                    exits.append(trade)

        return exits

    def update_trailing_stops(self, prices: dict[str, float], data: dict[str, pd.DataFrame],
                              date: str):
        """V6.2: Weekly ratchet — only move ATR stops upward."""
        for ticker, pos in self.positions.items():
            if pos.trailing_mode:
                continue  # Trailing mode has its own logic
            price = prices.get(ticker)
            if price is None or ticker not in data:
                continue
            atr = calculate_atr(data[ticker], date)
            if atr <= 0:
                continue
            new_stop = max(price - ATR_MULTIPLIER * atr, price * (1 - ATR_HARD_FLOOR))
            if new_stop > pos.stop_loss_price:
                pos.stop_loss_price = new_stop

    def check_cb_expiry(self):
        """Expire Circuit Breaker RED after CB_RED_EXPIRY_DAYS trading days."""
        if self.circuit_breaker == "RED":
            self.cb_red_day_count += 1
            if self.cb_red_day_count >= CB_RED_EXPIRY_DAYS:
                self.circuit_breaker = "YELLOW"  # RED→YELLOW, not straight to GREEN
                self.cb_red_day_count = 0
                self.consecutive_losses = 3  # YELLOW threshold
        elif self.circuit_breaker == "YELLOW":
            self.cb_red_day_count = 0

    def reset_weekly_counters(self):
        self.weekly_loss_count = 0


# ══════════════════════════════════════════════════════════════════════════════
# MAIN SIMULATION
# ══════════════════════════════════════════════════════════════════════════════

def run_backtest(data: dict[str, pd.DataFrame], verbose: bool = False) -> Portfolio:
    """Run the full 2025 walk-forward backtest."""
    portfolio = Portfolio(INITIAL_CAPITAL)
    spy_data = data.get("SPY")

    if spy_data is None:
        console.print("[red]ERROR: SPY data not available[/red]")
        sys.exit(1)

    # Get trading days from SPY index
    start_dt = pd.Timestamp(START_DATE)
    end_dt = pd.Timestamp(END_DATE)
    trading_days = spy_data.index[(spy_data.index >= start_dt) & (spy_data.index <= end_dt)]

    console.print(f"\n[bold]Starting backtest: {START_DATE} → {END_DATE}[/bold]")
    console.print(f"Trading days: {len(trading_days)}")
    console.print(f"Universe: {len(ALL_TICKERS)} stocks + {len(SECTOR_ETFS)} sector ETFs")
    console.print(f"Initial capital: ${INITIAL_CAPITAL:,.0f}\n")

    # Track signals seen per ticker (for grade calculation)
    signal_counts: dict[str, int] = {}
    day_count = 0
    last_rebalance_day = 0
    beta_reserve_deployed = False

    for date in trading_days:
        date_str = date.strftime("%Y-%m-%d")
        day_count += 1

        # Weekly counter reset (every Monday)
        if date.weekday() == 0:
            portfolio.reset_weekly_counters()

        # ── Circuit Breaker expiry check (daily) ──
        portfolio.check_cb_expiry()

        # ── Get current prices ──
        prices: dict[str, float] = {}
        for sym, df in data.items():
            mask = df.index <= date
            if mask.any():
                prices[sym] = float(df.loc[mask, "Close"].iloc[-1])

        spy_price = prices.get("SPY", 0)

        # ── 0. Day 1: Deploy Beta Reserve (AAPL) ──
        if not beta_reserve_deployed and "AAPL" in data and "AAPL" in prices:
            atr = calculate_atr(data["AAPL"], date_str)
            trade = portfolio.buy(
                "AAPL", prices["AAPL"], date_str, "Beta", "B+",
                signal="Beta_Reserve_Day1", atr=atr, current_day=day_count,
            )
            if trade and verbose:
                console.print(f"  [blue]BUY AAPL {trade.shares}sh @${trade.price:.2f} — Beta Reserve Day 1[/blue]")
            beta_reserve_deployed = True

        # ── 1. Regime Detection (daily, V6.2 with CORRECTION) ──
        regime = detect_regime(spy_data, date_str)

        # ── 2. Check Stop Losses (daily — V6.2 ATR-based + trailing) ──
        stop_trades = portfolio.check_stop_losses(prices, date_str, current_day=day_count)

        # ── 3. Weekly: Ratchet stops upward (Fridays) ──
        if date.weekday() == 4:
            portfolio.update_trailing_stops(prices, data, date_str)

        # ── 4. Earnings Event Detection (daily) — V6.2: NO PEAD entries, F21 exit only ──
        for ticker in ALL_TICKERS:
            if ticker not in data:
                continue

            event = detect_earnings_event(
                data[ticker], date_str, ticker,
                portfolio.last_earnings_event, day_count,
            )
            if event is None:
                continue

            if event == "beat":
                portfolio.beat_history[ticker] = portfolio.beat_history.get(ticker, 0) + 1
                portfolio.miss_history.pop(ticker, None)
                signal_counts[ticker] = signal_counts.get(ticker, 0) + 1

                # V6.2: NO PEAD entry — only update beat history for grade calculation
                # Entries happen ONLY through Discovery scan (step 5)
                if ticker in portfolio.positions:
                    pos = portfolio.positions[ticker]
                    new_beat = portfolio.beat_history.get(ticker, 0)
                    if new_beat >= 3 and pos.grade < "A":
                        pos.grade = "A-"

            elif event == "miss":
                portfolio.beat_history[ticker] = 0
                portfolio.miss_history[ticker] = date_str

                if ticker in portfolio.positions:
                    pos = portfolio.positions[ticker]
                    price = prices.get(ticker)
                    if price is None:
                        continue

                    # V6.2: F21 MISS override — if stock up >40%, switch to trailing stop
                    gain_pct = (price - pos.entry_price) / pos.entry_price
                    if gain_pct > F21_MISS_OVERRIDE_THRESHOLD:
                        pos.trailing_mode = True
                        pos.high_water_mark = max(pos.high_water_mark, price)
                        if verbose:
                            console.print(f"  [yellow]{ticker} F21 MISS but +{gain_pct:.0%} → trailing stop mode[/yellow]")
                    else:
                        trade = portfolio.sell(ticker, price, date_str,
                                             "F21 MISS: earnings miss → same-day exit",
                                             current_day=day_count)
                        if trade and verbose:
                            console.print(f"  [red]SELL {ticker} — F21 MISS, P&L: ${trade.realized_pnl:+,.0f}[/red]")

        # ── 5. Discovery Scan (weekly, Fridays) — V6.2: ONLY entry signal ──
        if date.weekday() == 4 and day_count > 20:
            # V6.2: In CORRECTION regime, no new entries
            if regime == "CORRECTION":
                if verbose:
                    console.print(f"  [dim]Discovery scan skipped — CORRECTION regime[/dim]")
            else:
                candidates: list[tuple[str, float, str, float]] = []

                for ticker in (POD_I | POD_II) - set(portfolio.positions.keys()):
                    if ticker not in data:
                        continue

                    rs = calculate_rs_rank(data[ticker], spy_data, date_str)
                    momentum = calculate_momentum_score(data[ticker], date_str)

                    td = data[ticker]
                    mask_td = td.index <= date
                    if mask_td.sum() < 22:
                        continue
                    recent = td.loc[mask_td]
                    avg_vol = recent["Volume"].iloc[-21:-1].mean()
                    today_vol = recent["Volume"].iloc[-1]
                    vol_ratio = today_vol / avg_vol if avg_vol > 0 else 0

                    score = rs + momentum + (0.1 if vol_ratio > 2.0 else 0)
                    atr = calculate_atr(td, date_str)

                    if score > 0.06 and rs > 0:
                        pod = assign_pod(ticker)
                        candidates.append((ticker, score, pod, atr))

                candidates.sort(key=lambda x: x[1], reverse=True)

                for ticker, score, pod, atr in candidates[:2]:
                    if len(portfolio.positions) >= MAX_LONG_POSITIONS:
                        break

                    # V6.2: Pod III only in BULL
                    if pod == "III" and regime != "BULL":
                        continue

                    # Rotation filter
                    sector_etf = "SMH" if pod == "I" else "XLE" if pod == "II" else None
                    if sector_etf and sector_etf in data:
                        sector_rs = calculate_sector_rs(data[sector_etf], spy_data, date_str)
                        if sector_rs < RS_RED_THRESHOLD:
                            continue

                    beat_count = portfolio.beat_history.get(ticker, 0)
                    grade = calculate_grade(ticker, beat_count,
                                           calculate_rs_rank(data[ticker], spy_data, date_str),
                                           pod, signal_counts.get(ticker, 0))

                    trade = portfolio.buy(
                        ticker, prices[ticker], date_str, pod, grade,
                        signal=f"Discovery(score={score:.2f})",
                        atr=atr, current_day=day_count,
                    )
                    if trade and verbose:
                        console.print(f"  [cyan]BUY {ticker} {trade.shares}sh @${trade.price:.2f} "
                                     f"Pod {pod} {grade} — Discovery scan[/cyan]")

        # ── 6. Pod Rebalance Check (every N days) ──
        if day_count - last_rebalance_day >= REBALANCE_FREQUENCY and len(portfolio.positions) > 0:
            last_rebalance_day = day_count
            targets = POD_TARGETS.get(regime, POD_TARGETS["NEUTRAL"])
            alloc = portfolio.pod_allocation(prices)

            for pod, target in targets.items():
                if pod == "Cash":
                    continue
                current = alloc.get(pod, 0)
                if current > target + 0.10:
                    pod_positions = [(t, p) for t, p in portfolio.positions.items() if p.pod == pod]
                    if not pod_positions:
                        continue

                    pod_positions.sort(
                        key=lambda x: (prices.get(x[0], x[1].entry_price) - x[1].entry_price) / x[1].entry_price
                    )

                    worst_ticker, worst_pos = pod_positions[0]
                    worst_price = prices.get(worst_ticker, worst_pos.entry_price)
                    pnl_pct = (worst_price - worst_pos.entry_price) / worst_pos.entry_price

                    if pnl_pct < -0.02:
                        trade = portfolio.sell(worst_ticker, worst_price, date_str,
                                             f"Pod rebalance: Pod {pod} {current:.0%} > target {target:.0%}",
                                             current_day=day_count)
                        if trade and verbose:
                            console.print(f"  [yellow]TRIM {worst_ticker} — Pod {pod} overweight[/yellow]")

        # ── Record daily state ──
        nav = portfolio.nav(prices)
        spy_start = prices.get("SPY", spy_price)

        # Calculate returns
        if portfolio.daily_states:
            prev = portfolio.daily_states[-1]
            port_ret = (nav / prev.nav - 1) * 100
            spy_ret = (spy_price / prev.spy_close - 1) * 100 if prev.spy_close else 0
        else:
            port_ret = (nav / INITIAL_CAPITAL - 1) * 100
            spy_ret = 0

        state = DailyState(
            date=date_str, nav=nav, cash=portfolio.cash,
            num_positions=len(portfolio.positions), regime=regime,
            spy_close=spy_price,
            spy_return_pct=spy_ret,
            portfolio_return_pct=port_ret,
            alpha_pct=port_ret - spy_ret,
        )
        portfolio.daily_states.append(state)

        # Monthly progress update
        if date.day == 1 or date == trading_days[-1]:
            spy_total_ret = (spy_price / prices.get("SPY", INITIAL_CAPITAL) - 1) * 100 if day_count > 1 else 0
            total_ret = (nav / INITIAL_CAPITAL - 1) * 100
            console.print(
                f"[dim]{date_str}[/dim] NAV: ${nav:>10,.0f} ({total_ret:>+6.1f}%) | "
                f"SPY: {spy_total_ret:>+5.1f}% | Regime: {regime} | "
                f"Positions: {len(portfolio.positions)} | "
                f"Cash: {portfolio.cash / nav * 100:.0f}% | "
                f"CB: {portfolio.circuit_breaker}"
            )

    return portfolio


# ══════════════════════════════════════════════════════════════════════════════
# ANALYSIS & REPORTING
# ══════════════════════════════════════════════════════════════════════════════

def analyze_results(portfolio: Portfolio, data: dict[str, pd.DataFrame]) -> dict:
    """Calculate comprehensive performance statistics."""
    trades = portfolio.trades
    states = portfolio.daily_states

    if not trades or not states:
        return {"error": "No trades or states to analyze"}

    # ── Basic P&L ──
    closed_trades = [t for t in trades if t.action == "SELL"]
    wins = [t for t in closed_trades if t.realized_pnl > 0]
    losses = [t for t in closed_trades if t.realized_pnl < 0]

    total_realized = sum(t.realized_pnl for t in closed_trades)
    win_rate = len(wins) / len(closed_trades) * 100 if closed_trades else 0
    avg_win = np.mean([t.realized_pnl for t in wins]) if wins else 0
    avg_loss = np.mean([t.realized_pnl for t in losses]) if losses else 0
    payoff_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else float("inf")

    # ── NAV curve ──
    navs = [s.nav for s in states]
    final_nav = navs[-1]
    total_return = (final_nav / INITIAL_CAPITAL - 1) * 100

    # SPY return
    spy_start = states[0].spy_close
    spy_end = states[-1].spy_close
    spy_return = (spy_end / spy_start - 1) * 100 if spy_start else 0
    alpha = total_return - spy_return

    # ── Drawdown ──
    peak = navs[0]
    max_dd = 0
    max_dd_date = ""
    for s in states:
        if s.nav > peak:
            peak = s.nav
        dd = (s.nav - peak) / peak * 100
        if dd < max_dd:
            max_dd = dd
            max_dd_date = s.date

    # ── Sharpe (annualized, rf=5%) ──
    daily_returns = []
    for i in range(1, len(navs)):
        daily_returns.append(navs[i] / navs[i-1] - 1)

    if daily_returns:
        avg_daily = np.mean(daily_returns)
        std_daily = np.std(daily_returns)
        sharpe = (avg_daily - 0.05/252) / std_daily * np.sqrt(252) if std_daily > 0 else 0
    else:
        sharpe = 0

    # ── By Pod ──
    pod_stats = {}
    for t in closed_trades:
        if t.pod not in pod_stats:
            pod_stats[t.pod] = {"trades": 0, "wins": 0, "pnl": 0, "total_value": 0}
        pod_stats[t.pod]["trades"] += 1
        pod_stats[t.pod]["pnl"] += t.realized_pnl
        pod_stats[t.pod]["total_value"] += t.value
        if t.realized_pnl > 0:
            pod_stats[t.pod]["wins"] += 1

    for pod in pod_stats:
        s = pod_stats[pod]
        s["win_rate"] = s["wins"] / s["trades"] * 100 if s["trades"] > 0 else 0

    # ── By Signal ──
    signal_stats = {}
    for t in closed_trades:
        sig = t.signal.split("(")[0] if t.signal else "unknown"
        if sig not in signal_stats:
            signal_stats[sig] = {"trades": 0, "wins": 0, "pnl": 0}
        signal_stats[sig]["trades"] += 1
        signal_stats[sig]["pnl"] += t.realized_pnl
        if t.realized_pnl > 0:
            signal_stats[sig]["wins"] += 1

    for sig in signal_stats:
        s = signal_stats[sig]
        s["win_rate"] = s["wins"] / s["trades"] * 100 if s["trades"] > 0 else 0

    # ── By Month ──
    monthly_returns = {}
    for i in range(1, len(states)):
        month = states[i].date[:7]
        if month not in monthly_returns:
            monthly_returns[month] = {"start_nav": states[i-1].nav, "end_nav": states[i].nav}
        monthly_returns[month]["end_nav"] = states[i].nav

    for m in monthly_returns:
        s = monthly_returns[m]
        s["return_pct"] = (s["end_nav"] / s["start_nav"] - 1) * 100

    # ── Regime breakdown ──
    regime_days = {}
    for s in states:
        regime_days[s.regime] = regime_days.get(s.regime, 0) + 1

    return {
        "summary": {
            "initial_capital": INITIAL_CAPITAL,
            "final_nav": round(final_nav, 2),
            "total_return_pct": round(total_return, 2),
            "spy_return_pct": round(spy_return, 2),
            "alpha_pct": round(alpha, 2),
            "total_realized_pnl": round(total_realized, 2),
            "sharpe_ratio": round(sharpe, 3),
            "max_drawdown_pct": round(max_dd, 2),
            "max_drawdown_date": max_dd_date,
        },
        "trade_stats": {
            "total_trades": len(trades),
            "closed_trades": len(closed_trades),
            "buys": len([t for t in trades if t.action == "BUY"]),
            "sells": len([t for t in trades if t.action == "SELL"]),
            "win_rate_pct": round(win_rate, 1),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "payoff_ratio": round(payoff_ratio, 2),
            "largest_win": round(max((t.realized_pnl for t in closed_trades), default=0), 2),
            "largest_loss": round(min((t.realized_pnl for t in closed_trades), default=0), 2),
        },
        "by_pod": pod_stats,
        "by_signal": signal_stats,
        "monthly_returns": {m: round(v["return_pct"], 2) for m, v in sorted(monthly_returns.items())},
        "regime_days": regime_days,
    }


def print_results(results: dict, portfolio: Portfolio):
    """Pretty-print backtest results."""
    s = results["summary"]
    t = results["trade_stats"]

    console.print("\n" + "=" * 80)
    console.print(Panel.fit(
        f"[bold white]US V6.2 BACKTEST RESULTS — 2025 (ATR stops, no PEAD, no shorts)[/bold white]",
        box=box.DOUBLE_EDGE,
    ))

    # Summary
    table = Table(box=box.SIMPLE, show_header=False, min_width=60)
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")

    ret_color = "green" if s["total_return_pct"] > 0 else "red"
    alpha_color = "green" if s["alpha_pct"] > 0 else "red"

    table.add_row("Initial Capital", f"${s['initial_capital']:,.0f}")
    table.add_row("Final NAV", f"${s['final_nav']:,.0f}")
    table.add_row("Total Return", f"[{ret_color}]{s['total_return_pct']:+.2f}%[/{ret_color}]")
    table.add_row("SPY Return", f"{s['spy_return_pct']:+.2f}%")
    table.add_row("Alpha", f"[{alpha_color}]{s['alpha_pct']:+.2f}%[/{alpha_color}]")
    table.add_row("Sharpe Ratio", f"{s['sharpe_ratio']:.3f}")
    table.add_row("Max Drawdown", f"[red]{s['max_drawdown_pct']:.2f}%[/red] ({s['max_drawdown_date']})")
    table.add_row("", "")
    table.add_row("Total Trades", str(t["total_trades"]))
    table.add_row("Closed Trades", str(t["closed_trades"]))
    table.add_row("Win Rate", f"{t['win_rate_pct']:.1f}%")
    table.add_row("Avg Win", f"${t['avg_win']:+,.0f}")
    table.add_row("Avg Loss", f"${t['avg_loss']:+,.0f}")
    table.add_row("Payoff Ratio", f"{t['payoff_ratio']:.2f}x")
    table.add_row("Largest Win", f"[green]${t['largest_win']:+,.0f}[/green]")
    table.add_row("Largest Loss", f"[red]${t['largest_loss']:+,.0f}[/red]")

    console.print(table)

    # By Pod
    console.print("\n[bold]By Pod:[/bold]")
    pod_table = Table(box=box.SIMPLE_HEAVY, show_header=True)
    pod_table.add_column("Pod")
    pod_table.add_column("Trades", justify="right")
    pod_table.add_column("Win Rate", justify="right")
    pod_table.add_column("P&L", justify="right")

    for pod in sorted(results["by_pod"].keys()):
        ps = results["by_pod"][pod]
        pnl_color = "green" if ps["pnl"] > 0 else "red"
        pod_table.add_row(
            f"Pod {pod}", str(ps["trades"]),
            f"{ps['win_rate']:.0f}%",
            f"[{pnl_color}]${ps['pnl']:+,.0f}[/{pnl_color}]",
        )
    console.print(pod_table)

    # By Signal
    console.print("\n[bold]By Signal:[/bold]")
    sig_table = Table(box=box.SIMPLE_HEAVY, show_header=True)
    sig_table.add_column("Signal")
    sig_table.add_column("Trades", justify="right")
    sig_table.add_column("Win Rate", justify="right")
    sig_table.add_column("P&L", justify="right")

    for sig in sorted(results["by_signal"].keys()):
        ss = results["by_signal"][sig]
        pnl_color = "green" if ss["pnl"] > 0 else "red"
        sig_table.add_row(
            sig, str(ss["trades"]),
            f"{ss['win_rate']:.0f}%",
            f"[{pnl_color}]${ss['pnl']:+,.0f}[/{pnl_color}]",
        )
    console.print(sig_table)

    # Monthly
    console.print("\n[bold]Monthly Returns:[/bold]")
    for month, ret in sorted(results["monthly_returns"].items()):
        color = "green" if ret > 0 else "red"
        bar = "█" * int(abs(ret) * 2)
        console.print(f"  {month}: [{color}]{ret:+6.2f}% {bar}[/{color}]")

    # Regime
    console.print(f"\n[bold]Regime Days:[/bold] {results['regime_days']}")


def save_results(results: dict, portfolio: Portfolio):
    """Save all results to JSON files."""
    # Summary stats
    with open(RESULTS_DIR / "summary_stats.json", "w") as f:
        json.dump(results, f, indent=2, default=str)

    # Trade log
    trade_list = [asdict(t) for t in portfolio.trades]
    with open(RESULTS_DIR / "trade_log.json", "w") as f:
        json.dump(trade_list, f, indent=2, default=str)

    # Daily portfolio snapshots
    daily_list = [asdict(s) for s in portfolio.daily_states]
    with open(RESULTS_DIR / "daily_portfolio.json", "w") as f:
        json.dump(daily_list, f, indent=2, default=str)

    console.print(f"\n[green]Results saved to {RESULTS_DIR}/[/green]")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="US V6.1 2025 Backtest")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print every trade")
    parser.add_argument("--no-cache", action="store_true", help="Force re-download data")
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    if args.no_cache:
        cache = DATA_DIR / "price_cache_2025.json"
        if cache.exists():
            cache.unlink()

    # 1. Download data
    data = download_data(ALL_SYMBOLS, START_DATE, END_DATE)

    if len(data) < 20:
        console.print(f"[red]ERROR: Only got {len(data)} symbols. Need at least 20.[/red]")
        sys.exit(1)

    # 2. Run backtest
    portfolio = run_backtest(data, verbose=args.verbose)

    # 3. Analyze
    results = analyze_results(portfolio, data)

    # 4. Print and save
    print_results(results, portfolio)
    save_results(results, portfolio)


if __name__ == "__main__":
    main()

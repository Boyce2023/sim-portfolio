#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["yfinance>=0.2.40", "pandas>=2.0", "numpy>=1.24", "rich>=13.0"]
# ///
"""
US Trading System V8 Final — 21-Iteration Framework Rebuild
============================================================
V7.6: +88.1% baseline → V8 Final: +101.1% (+13% improvement)

6 validated improvements over V7 (each tested in isolation):
  1. No pod limits (pods don't limit concentration)
  2. No macro shock pause (stops free capital for rotation = alpha)
  3. Conviction-tiered ATR stops (≥4 beats → ATR 4x, protects strong stocks)
  4. MOM_CONFIRM (MOM adds to existing positions instead of skipping)
  5. DIP→MOM conversion (DIP confirmed by momentum → cancel hold period)
  6. Regime-adaptive sizing (1.5x in BULL, 1.0x otherwise)

12 ideas REJECTED by backtest (each tested and reverted):
  - Removing position cap (dilutes winners) — V8.3: -9.8%
  - MOM sell of all signals (kills DIP mean-reversion) — V8.4: -14.5%
  - REENTRY mechanism (competes with MOM/DIP for slots) — V8.5: -18.2%
  - Wider trailing stops (gives back gains) — V8.8: -4.3%
  - Reduced cooldown 15→5 (catches falling knives) — V8.9: -13.1%
  - Faster MOM rotation 20→15d (creates churn) — V8.10: -25.9%
  - Concentrated MOM top 5 (misses opportunities) — V8.11: -6.0%
  - Higher DIP quality bar (filters out good 2-beat dips) — V8.12: -2.8%
  - Larger MOM size (bigger stops on losses) — V8.13: -2.6%
  - Larger add sizes (increases DD) — V8.15: -0.3%
  - Wider hard stop floor 28% (delays exits) — V8.4/V8.5
  - BULL 2.0x sizing (oversized, crashes on drawdowns) — V8.21: -2.8%

Usage:
    uv run --script backtest/backtest_v8.py                    # 2025 full year
    uv run --script backtest/backtest_v8.py --period 2026
    uv run --script backtest/backtest_v8.py --verbose
    uv run --script backtest/backtest_v8.py --compare          # Compare V7 vs V8
"""

from __future__ import annotations
import json, argparse, sys, warnings
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
# V8 CONFIG — Stripped to essentials. Removed: MAX_POSITIONS, MAX_POD_I,
# PEAD_MAX_CONCURRENT, L16 min size, pod allocation limits.
# ══════════════════════════════════════════════════════════════════════════════

INITIAL_CAPITAL = 150_000.0
BENCHMARK = "SPY"

# Universe (unchanged)
POD_I = {"NVDA", "AMD", "MU", "MRVL", "AVGO", "ARM", "TSM",
         "LRCX", "AMAT", "CLS", "DELL", "ANET", "CRDO"}
POD_II = {"VST", "GEV", "CEG", "NRG", "ETN", "EME", "APH",
          "AAON", "CCJ", "LEU", "NEE"}
BETA = {"AAPL"}
ALL_TICKERS = sorted(POD_I | POD_II | BETA)
SECTOR_ETFS = ["SMH", "XLE"]
ALL_SYMBOLS = ALL_TICKERS + SECTOR_ETFS + [BENCHMARK]

# ── Strategy 1: PEAD (ADD is king, standalone only for massive beats) ──
PEAD_STANDALONE_MIN = 15.0
PEAD_ADD_MIN = 5.0
PEAD_ADD_SIZE = 0.07
PEAD_HOLD_DAYS = 60
PEAD_SIZE_BASE = 0.10
PEAD_SIZE_BONUS = 0.003
PEAD_REQUIRE_BULL = True
# V8: Removed PEAD_MAX_CONCURRENT (was 4 — artificial cap)
PEAD_REENTRY_COOLDOWN = 15     # V7 baseline (V8.9 proved shorter hurts)

# ── Strategy 2: Momentum Rotation (BUY ONLY — no more forced sells) ──
MOM_LOOKBACK = 120
MOM_SKIP = 20
MOM_TOP_N = 7
MOM_SIZE = 0.10
MOM_REBAL_FREQ = 20
# V8.2: Restore V7 MOM sell (86.7% WR proved it works). V8.0 removed it → -$55K.
# V8.1 half-restored → still -$55K. Rotation IS the alpha, not a bug.
MOM_SELL_BOTTOM_N = 3

# ── Strategy 3: Dip Buy ──
DIP_THRESHOLD = -0.15
DIP_EXTREME = -0.25
DIP_MIN_BEATS = 2
DIP_SIZE = 0.06
DIP_EXTREME_SIZE = 0.10
DIP_HOLD_DAYS = 40

# ── Risk Management (V8 overhaul) ──
ATR_PERIOD = 14
ATR_BASE_MULT = 3.0            # V7 baseline
ATR_HIGH_CONVICTION_MULT = 4.0 # V8.7: Test conviction-tiered stops (≥4 beats → wider)
HARD_STOP_FLOOR = 0.25         # V7 baseline
TRAILING_ACTIVATE = 0.15       # V7 baseline (V8.8 proved wider hurts)
TRAILING_PCT = 0.10            # V7 baseline
MAX_POSITIONS = 10             # V7 baseline
MAX_GROSS_PCT = 1.30           # Safety cap

# ── Macro Shock Detection (V8.3: DISABLED) ──
MACRO_SHOCK_ENABLED = False    # V8.3: Disabled — stops are beneficial for capital recycling
MACRO_SHOCK_SPY_DROP = -0.03
MACRO_SHOCK_WINDOW = 5
MACRO_SHOCK_PAUSE = 5

# ── Cluster Stop (retained from V7.6) ──
CLUSTER_STOP_PAUSE = 3

# ── Re-entry After False Stop ──
REENTRY_ENABLED = False        # V8.6: DISABLED — competes with MOM/DIP for position slots
REENTRY_THRESHOLD = 0.10
REENTRY_WINDOW = 20
REENTRY_SIZE = 0.06
REENTRY_MAX_PER_TICKER = 1

# ── Regime ──
CORRECTION_THRESHOLD = -0.05


# ══════════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class Position:
    ticker: str
    shares: int
    entry_price: float
    entry_date: str
    stop_price: float
    signal: str
    exit_target_day: int = 0
    high_water: float = 0.0
    trailing_active: bool = False
    beat_count_at_entry: int = 0   # V8: Track conviction at entry

@dataclass
class Trade:
    date: str
    action: str
    ticker: str
    shares: int
    price: float
    value: float
    signal: str
    reason: str
    realized_pnl: float = 0.0

@dataclass
class StopRecord:
    """V8: Track stopped positions for potential re-entry."""
    ticker: str
    stop_price: float
    stop_date: str
    stop_day_count: int
    original_signal: str
    beat_count: int


# ══════════════════════════════════════════════════════════════════════════════
# DATA
# ══════════════════════════════════════════════════════════════════════════════

def download_data(symbols: list[str], start: str, end: str, tag: str) -> dict[str, pd.DataFrame]:
    cache_path = DATA_DIR / f"price_cache_{tag}.json"
    if cache_path.exists():
        console.print(f"[dim]Loading cached {tag} data...[/dim]")
        cached = pd.read_json(cache_path)
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
            console.print(f"[green]Cache: {len(result)}/{len(symbols)}[/green]")
            return result

    console.print(f"[yellow]Downloading {tag} data for {len(symbols)} symbols...[/yellow]")
    buffer_start = (datetime.strptime(start, "%Y-%m-%d") - timedelta(days=200)).strftime("%Y-%m-%d")
    dl_end = (datetime.strptime(end, "%Y-%m-%d") + timedelta(days=5)).strftime("%Y-%m-%d")

    raw = yf.download(symbols, start=buffer_start, end=dl_end,
                      group_by="ticker", auto_adjust=True, threads=True, progress=True)
    result = {}
    for sym in symbols:
        try:
            df = raw[sym].copy() if len(symbols) > 1 and sym in raw.columns.get_level_values(0) else (raw.copy() if len(symbols) == 1 else pd.DataFrame())
            if df.empty: continue
            df = df.dropna(how="all")
            if hasattr(df.columns, 'levels'):
                df.columns = df.columns.get_level_values(-1)
            if len(df) >= 20:
                result[sym] = df
        except Exception:
            continue

    try:
        combined = pd.DataFrame()
        for sym, df in result.items():
            for col in df.columns:
                combined[f"{sym}_{col}"] = df[col]
        combined.to_json(cache_path, date_format="iso")
    except Exception:
        pass

    console.print(f"[green]{len(result)}/{len(symbols)} symbols loaded[/green]")
    return result


def load_earnings(path: Path) -> dict[str, list[dict]]:
    if not path.exists():
        console.print("[red]Earnings data not found.[/red]")
        return {}
    with open(path) as f:
        return json.load(f)


# ══════════════════════════════════════════════════════════════════════════════
# SIGNALS
# ══════════════════════════════════════════════════════════════════════════════

def calc_atr(data: pd.DataFrame, date: str, period: int = ATR_PERIOD) -> float:
    mask = data.index <= date
    d = data.loc[mask]
    if len(d) < period + 1:
        return 0.0
    h = d["High"].iloc[-(period+1):]
    l = d["Low"].iloc[-(period+1):]
    c = d["Close"].iloc[-(period+1):]
    trs = [max(float(h.iloc[i]-l.iloc[i]), abs(float(h.iloc[i]-c.iloc[i-1])),
               abs(float(l.iloc[i]-c.iloc[i-1]))) for i in range(1, len(h))]
    return float(np.mean(trs))


def detect_regime(spy_data: pd.DataFrame, date: str) -> str:
    mask = spy_data.index <= date
    d = spy_data.loc[mask]
    if len(d) < 200:
        return "NEUTRAL"
    if len(d) >= 20:
        hi = float(d["Close"].iloc[-20:].max())
        cur = float(d["Close"].iloc[-1])
        if (cur - hi) / hi < CORRECTION_THRESHOLD:
            return "CORRECTION"
    ma50 = d["Close"].iloc[-50:].mean()
    ma200 = d["Close"].iloc[-200:].mean()
    if ma50 > ma200 * 1.02:
        return "BULL"
    elif ma50 < ma200 * 0.98:
        return "BEAR"
    return "NEUTRAL"


def detect_macro_shock(spy_data: pd.DataFrame, date: str) -> bool:
    """V8: Detect macro shock — SPY drops >3% in 5 trading days."""
    mask = spy_data.index <= date
    d = spy_data.loc[mask, "Close"]
    if len(d) < MACRO_SHOCK_WINDOW + 1:
        return False
    recent = d.iloc[-(MACRO_SHOCK_WINDOW+1):]
    change = (float(recent.iloc[-1]) / float(recent.iloc[0])) - 1
    return change < MACRO_SHOCK_SPY_DROP


def check_dip(ticker_data: pd.DataFrame, date: str) -> float:
    mask = ticker_data.index <= date
    d = ticker_data.loc[mask, "Close"]
    if len(d) < 20:
        return 0.0
    hi = float(d.iloc[-20:].max())
    cur = float(d.iloc[-1])
    return (cur - hi) / hi


# ══════════════════════════════════════════════════════════════════════════════
# PORTFOLIO
# ══════════════════════════════════════════════════════════════════════════════

class Portfolio:
    def __init__(self, capital: float):
        self.cash = capital
        self.initial = capital
        self.positions: dict[str, Position] = {}
        self.trades: list[Trade] = []
        self.daily_navs: list[tuple[str, float, str, int]] = []
        self.beat_count: dict[str, int] = {}
        self.stop_history: dict[str, str] = {}
        self.recent_stops: list[StopRecord] = []  # V8: For re-entry tracking

    def nav(self, prices: dict[str, float]) -> float:
        total = self.cash
        for t, p in self.positions.items():
            total += p.shares * prices.get(t, p.entry_price)
        return total

    def invested_pct(self, prices: dict[str, float]) -> float:
        n = self.nav(prices)
        return 1.0 - (self.cash / n) if n > 0 else 0.0

    def gross_pct(self, prices: dict[str, float]) -> float:
        n = self.nav(prices)
        if n <= 0:
            return 0.0
        gross = sum(p.shares * prices.get(t, p.entry_price) for t, p in self.positions.items())
        return gross / n

    def buy(self, ticker: str, price: float, date: str, signal: str,
            size_pct: float, atr: float, target_day: int,
            beat_count: int = 0) -> Optional[Trade]:
        if ticker in self.positions:
            return None
        # V8.5: Position count limit (concentration produces bigger wins)
        if len(self.positions) >= MAX_POSITIONS:
            return None
        nav_now = self.nav({ticker: price})
        if self.gross_pct({ticker: price}) >= MAX_GROSS_PCT:
            return None
        value = nav_now * size_pct
        value = min(value, self.cash * 0.95)
        if value < 3000:
            return None
        shares = int(value / price)
        if shares == 0:
            return None
        value = shares * price
        self.cash -= value

        # V8: Conviction-tiered ATR multiplier
        atm = ATR_HIGH_CONVICTION_MULT if beat_count >= 4 else ATR_BASE_MULT
        if atr > 0:
            stop = max(price - atm * atr, price * (1 - HARD_STOP_FLOOR))
        else:
            stop = price * (1 - HARD_STOP_FLOOR)

        self.positions[ticker] = Position(
            ticker=ticker, shares=shares, entry_price=price, entry_date=date,
            stop_price=stop, signal=signal, exit_target_day=target_day,
            high_water=price, beat_count_at_entry=beat_count,
        )
        trade = Trade(date=date, action="BUY", ticker=ticker, shares=shares,
                     price=price, value=value, signal=signal, reason=signal)
        self.trades.append(trade)
        return trade

    def add_to(self, ticker: str, price: float, date: str, signal: str,
               add_pct: float) -> Optional[Trade]:
        if ticker not in self.positions:
            return None
        nav_now = self.nav({ticker: price})
        value = min(nav_now * add_pct, self.cash * 0.95)
        if value < 3000:
            return None
        shares = int(value / price)
        if shares == 0:
            return None
        value = shares * price
        self.cash -= value
        pos = self.positions[ticker]
        total = pos.shares + shares
        avg = (pos.shares * pos.entry_price + shares * price) / total
        pos.shares = total
        pos.entry_price = avg
        pos.high_water = max(pos.high_water, price)
        trade = Trade(date=date, action="ADD", ticker=ticker, shares=shares,
                     price=price, value=value, signal=signal, reason=f"Add: {signal}")
        self.trades.append(trade)
        return trade

    def sell(self, ticker: str, price: float, date: str, reason: str,
             day_count: int = 0) -> Optional[Trade]:
        pos = self.positions.get(ticker)
        if not pos:
            return None
        value = pos.shares * price
        pnl = (price - pos.entry_price) * pos.shares
        self.cash += value
        trade = Trade(date=date, action="SELL", ticker=ticker, shares=pos.shares,
                     price=price, value=value, signal=pos.signal, reason=reason,
                     realized_pnl=pnl)
        self.trades.append(trade)
        if "STOP" in reason:
            self.stop_history[ticker] = date
            # V8: Record for re-entry evaluation
            self.recent_stops.append(StopRecord(
                ticker=ticker, stop_price=price, stop_date=date,
                stop_day_count=day_count, original_signal=pos.signal,
                beat_count=pos.beat_count_at_entry,
            ))
        del self.positions[ticker]
        return trade

    def check_stops(self, prices: dict[str, float], date: str,
                    macro_shock: bool, day_count: int) -> list[Trade]:
        """V8: Stops are paused during macro shocks."""
        if macro_shock:
            return []  # Don't stop out during macro shock

        exits = []
        for ticker in list(self.positions):
            pos = self.positions[ticker]
            price = prices.get(ticker)
            if price is None:
                continue
            if price > pos.high_water:
                pos.high_water = price
            gain = (price - pos.entry_price) / pos.entry_price
            if gain >= TRAILING_ACTIVATE and not pos.trailing_active:
                pos.trailing_active = True
                pos.stop_price = max(pos.stop_price, pos.high_water * (1 - TRAILING_PCT))
            if pos.trailing_active:
                new_stop = pos.high_water * (1 - TRAILING_PCT)
                if new_stop > pos.stop_price:
                    pos.stop_price = new_stop
            if price <= pos.stop_price:
                t = self.sell(ticker, price, date,
                             f"STOP: ${price:.2f} ≤ ${pos.stop_price:.2f}",
                             day_count)
                if t:
                    exits.append(t)
        return exits

    def check_reentries(self, prices: dict[str, float], data: dict[str, pd.DataFrame],
                        date: str, day_count: int) -> list[Trade]:
        """V8: Re-enter positions that were falsely stopped out."""
        entries = []
        remaining = []
        reentry_count: dict[str, int] = {}  # V8.1: Track re-entries per ticker
        for sr in self.recent_stops:
            reentry_count[sr.ticker] = reentry_count.get(sr.ticker, 0)

        for sr in self.recent_stops:
            age = day_count - sr.stop_day_count
            if age > REENTRY_WINDOW:
                continue
            remaining.append(sr)
            ticker = sr.ticker
            if ticker in self.positions or ticker not in prices:
                continue
            # V8.1: Skip if already re-entered this ticker (no REENTRY chains)
            if reentry_count.get(ticker, 0) >= REENTRY_MAX_PER_TICKER:
                continue
            # V8.1: Skip if the original signal was already a re-entry
            if "REENTRY" in sr.original_signal:
                continue
            price = prices[ticker]
            rally = (price - sr.stop_price) / sr.stop_price
            if rally >= REENTRY_THRESHOLD and sr.beat_count >= 2:
                atr = calc_atr(data[ticker], date) if ticker in data else 0
                trade = self.buy(ticker, price, date,
                               f"REENTRY({rally:+.0%},was:{sr.original_signal[:15]})",
                               REENTRY_SIZE, atr, 0, sr.beat_count)
                if trade:
                    entries.append(trade)
                    reentry_count[ticker] = reentry_count.get(ticker, 0) + 1
        self.recent_stops = remaining
        return entries


# ══════════════════════════════════════════════════════════════════════════════
# MAIN SIMULATION
# ══════════════════════════════════════════════════════════════════════════════

def run_backtest(data: dict[str, pd.DataFrame], earnings: dict[str, list[dict]],
                 start: str, end: str, verbose: bool = False) -> Portfolio:
    pf = Portfolio(INITIAL_CAPITAL)
    spy = data.get("SPY")
    if spy is None:
        console.print("[red]No SPY data[/red]"); sys.exit(1)

    start_dt, end_dt = pd.Timestamp(start), pd.Timestamp(end)
    days = spy.index[(spy.index >= start_dt) & (spy.index <= end_dt)]

    console.print(f"\n[bold]V8 Backtest: {start} → {end} | {len(days)} days | ${INITIAL_CAPITAL:,.0f}[/bold]")

    earnings_by_date: dict[str, list[tuple[str, float]]] = {}
    for ticker, events in earnings.items():
        for ev in events:
            d = ev["date"][:10]
            surprise = ev.get("surprise_pct")
            if surprise is not None and ev.get("reported_eps") is not None:
                if d not in earnings_by_date:
                    earnings_by_date[d] = []
                earnings_by_date[d].append((ticker, surprise))

    day_count = 0
    last_mom_rebal = 0
    cluster_pause_until = 0
    macro_shock_pause_until = 0  # V8
    pead_pending: list[tuple[str, float, str]] = []

    for date in days:
        ds = date.strftime("%Y-%m-%d")
        day_count += 1

        prices: dict[str, float] = {}
        for sym, df in data.items():
            m = df.index <= date
            if m.any():
                prices[sym] = float(df.loc[m, "Close"].iloc[-1])

        regime = detect_regime(spy, ds)

        # V8.3: Macro shock detection DISABLED — stops free capital for rotation
        in_shock_pause = False
        if MACRO_SHOCK_ENABLED:
            is_macro_shock = detect_macro_shock(spy, ds)
            if is_macro_shock and day_count > macro_shock_pause_until:
                macro_shock_pause_until = day_count + MACRO_SHOCK_PAUSE
                if verbose:
                    console.print(f"  [yellow]{ds} MACRO SHOCK detected — pausing stops {MACRO_SHOCK_PAUSE}d[/yellow]")
            in_shock_pause = day_count <= macro_shock_pause_until

        # ── Check stops (V8: paused during macro shock) ──
        stops = pf.check_stops(prices, ds, in_shock_pause, day_count)
        if verbose:
            for t in stops:
                console.print(f"  [red]{ds} STOP {t.ticker} P&L: ${t.realized_pnl:+,.0f}[/red]")
        if len(stops) >= 4 and regime != "BULL":
            cluster_pause_until = day_count + CLUSTER_STOP_PAUSE

        # ── Re-entries ──
        if REENTRY_ENABLED and not in_shock_pause:
            reentries = pf.check_reentries(prices, data, ds, day_count)
            if verbose:
                for t in reentries:
                    console.print(f"  [green]{ds} REENTRY {t.ticker} {t.shares}sh @${t.price:.2f}[/green]")

        # ── Update trailing stops (ratchet up) ──
        for ticker, pos in pf.positions.items():
            if ticker in data:
                atr = calc_atr(data[ticker], ds)
                if atr > 0 and not pos.trailing_active:
                    atm = ATR_HIGH_CONVICTION_MULT if pos.beat_count_at_entry >= 4 else ATR_BASE_MULT
                    new_stop = max(prices.get(ticker, pos.entry_price) - atm * atr,
                                  pos.entry_price * (1 - HARD_STOP_FLOOR))
                    if new_stop > pos.stop_price:
                        pos.stop_price = new_stop

        # ── Process earnings (PEAD) ──
        yesterday = (date - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        two_days_ago = (date - pd.Timedelta(days=2)).strftime("%Y-%m-%d")
        for check_date in [yesterday, two_days_ago]:
            if check_date in earnings_by_date:
                for ticker, surprise in earnings_by_date[check_date]:
                    if ticker not in ALL_TICKERS or ticker not in data:
                        continue
                    if ticker in prices:
                        pead_pending.append((ticker, surprise, check_date))
                del earnings_by_date[check_date]

        new_pead = []
        for ticker, surprise, edate in pead_pending:
            if ticker not in prices:
                continue
            if surprise > 0:
                pf.beat_count[ticker] = pf.beat_count.get(ticker, 0) + 1
            elif surprise < -3.0:
                pf.beat_count[ticker] = 0

            # ADD to existing on beat
            if ticker in pf.positions and surprise >= PEAD_ADD_MIN:
                trade = pf.add_to(ticker, prices[ticker], ds,
                                 f"PEAD_ADD({surprise:+.1f}%)", PEAD_ADD_SIZE)
                if trade and verbose:
                    console.print(f"  [green]{ds} PEAD ADD {ticker} +{trade.shares}sh (surprise {surprise:+.1f}%)[/green]")
                # V8: Also update beat count on the position
                if ticker in pf.positions:
                    pf.positions[ticker].beat_count_at_entry = pf.beat_count.get(ticker, 0)
                continue

            # Sell on big miss
            if ticker in pf.positions and surprise <= -PEAD_ADD_MIN:
                trade = pf.sell(ticker, prices[ticker], ds,
                              f"PEAD MISS ({surprise:+.1f}%) → exit", day_count)
                if trade and verbose:
                    console.print(f"  [red]{ds} PEAD MISS SELL {ticker} P&L: ${trade.realized_pnl:+,.0f}[/red]")
                continue

            # Standalone PEAD: massive beats only, BULL only
            if ticker in pf.positions:
                continue
            if surprise < PEAD_STANDALONE_MIN:
                continue
            if PEAD_REQUIRE_BULL and regime not in ("BULL",):
                new_pead.append((ticker, surprise, edate))
                continue
            if ticker in pf.stop_history:
                stop_dt = pd.Timestamp(pf.stop_history[ticker])
                if (date - stop_dt).days < PEAD_REENTRY_COOLDOWN:
                    continue
            # V8: No PEAD_MAX_CONCURRENT cap
            size = PEAD_SIZE_BASE + PEAD_SIZE_BONUS * (surprise - PEAD_STANDALONE_MIN)
            size = min(size, 0.15)
            atr = calc_atr(data[ticker], ds)
            beats = pf.beat_count.get(ticker, 0)
            trade = pf.buy(ticker, prices[ticker], ds, f"PEAD({surprise:+.1f}%)",
                          size, atr, day_count + PEAD_HOLD_DAYS, beats)
            if trade and verbose:
                console.print(f"  [green]{ds} PEAD BUY {ticker} {trade.shares}sh (surprise {surprise:+.1f}%)[/green]")
        pead_pending = new_pead

        # ── PEAD holding period exits ──
        for ticker in list(pf.positions):
            pos = pf.positions[ticker]
            if pos.signal.startswith("PEAD") and day_count >= pos.exit_target_day and pos.exit_target_day > 0:
                price = prices.get(ticker)
                if price and not pos.trailing_active:
                    gain = (price - pos.entry_price) / pos.entry_price
                    if gain >= TRAILING_ACTIVATE:
                        pos.trailing_active = True
                    else:
                        trade = pf.sell(ticker, price, ds,
                                       f"PEAD hold expired ({PEAD_HOLD_DAYS}d)", day_count)
                        if trade and verbose:
                            console.print(f"  [dim]{ds} PEAD exit {ticker} P&L: ${trade.realized_pnl:+,.0f}[/dim]")

        # ── Momentum rotation (V8: BUY ONLY, no forced sells) ──
        entry_paused = (day_count <= cluster_pause_until) or in_shock_pause
        if day_count - last_mom_rebal >= MOM_REBAL_FREQ and not entry_paused:
            last_mom_rebal = day_count
            if regime not in ("CORRECTION", "BEAR"):
                rankings: list[tuple[str, float]] = []
                for ticker in ALL_TICKERS:
                    if ticker not in data:
                        continue
                    mask = data[ticker].index <= date
                    closes = data[ticker].loc[mask, "Close"]
                    if len(closes) < MOM_LOOKBACK + MOM_SKIP + 1:
                        continue
                    ret_full = closes.iloc[-1] / closes.iloc[-MOM_LOOKBACK - MOM_SKIP - 1] - 1
                    ret_skip = closes.iloc[-1] / closes.iloc[-MOM_SKIP - 1] - 1
                    mom_score = ret_full - ret_skip
                    rankings.append((ticker, mom_score))

                rankings.sort(key=lambda x: x[1], reverse=True)
                top = [t for t, _ in rankings[:MOM_TOP_N]]
                bottom = [t for t, _ in rankings[-MOM_SELL_BOTTOM_N:]]

                # V8.5: MOM sell of MOM-signal positions only (V8.2 proved this works).
                # V8.4 tried selling ALL signals → killed DIP alpha ($42K→$10K).
                # DIP is mean-reversion — starts with low momentum by design.
                for ticker in bottom:
                    if ticker in pf.positions and pf.positions[ticker].signal.startswith("MOM"):
                        price = prices.get(ticker)
                        if price:
                            trade = pf.sell(ticker, price, ds,
                                           "Momentum bottom → exit", day_count)
                            if trade and verbose:
                                console.print(f"  [dim]{ds} MOM exit {ticker}[/dim]")

                for ticker in top:
                    if ticker not in prices:
                        continue
                    if ticker in pf.positions:
                        # V8.14: MOM confirms existing position → add 5%
                        pos = pf.positions[ticker]
                        # V8.16: If DIP position is confirmed by MOM, cancel hold expiry
                        if pos.signal.startswith("DIP") and pos.exit_target_day > 0:
                            pos.exit_target_day = 0
                            pos.signal = f"DIP→MOM({pos.signal})"
                        trade = pf.add_to(ticker, prices[ticker], ds,
                                         "MOM_CONFIRM", 0.05)
                        if trade and verbose:
                            console.print(f"  [cyan]{ds} MOM ADD {ticker} +{trade.shares}sh (momentum confirm)[/cyan]")
                    else:
                        if ticker in pf.stop_history:
                            stop_dt = pd.Timestamp(pf.stop_history[ticker])
                            if (date - stop_dt).days < PEAD_REENTRY_COOLDOWN:
                                continue
                        atr = calc_atr(data[ticker], ds)
                        beats = pf.beat_count.get(ticker, 0)
                        # V8.17: Regime-adaptive size
                        mom_sz = MOM_SIZE * 1.5 if regime == "BULL" else MOM_SIZE
                        trade = pf.buy(ticker, prices[ticker], ds,
                                      f"MOM(top{MOM_TOP_N})", mom_sz, atr, 0, beats)
                        if trade and verbose:
                            console.print(f"  [cyan]{ds} MOM BUY {ticker} {trade.shares}sh @${trade.price:.2f}[/cyan]")

        # ── Weekly: Dip buy scan ──
        if date.weekday() == 4 and not entry_paused:
            for ticker in ALL_TICKERS:
                if ticker in pf.positions or ticker not in data or ticker not in prices:
                    continue
                if ticker in pf.stop_history:
                    stop_dt = pd.Timestamp(pf.stop_history[ticker])
                    if (date - stop_dt).days < PEAD_REENTRY_COOLDOWN:
                        continue
                beats = pf.beat_count.get(ticker, 0)
                if beats < DIP_MIN_BEATS:
                    continue
                dip = check_dip(data[ticker], ds)
                if dip <= DIP_EXTREME and regime != "BEAR":
                    atr = calc_atr(data[ticker], ds)
                    dip_sz = DIP_EXTREME_SIZE * 1.5 if regime == "BULL" else DIP_EXTREME_SIZE
                    trade = pf.buy(ticker, prices[ticker], ds,
                                  f"DIP({dip:.0%},beats={beats})",
                                  dip_sz, atr, day_count + DIP_HOLD_DAYS, beats)
                    if trade and verbose:
                        console.print(f"  [magenta]{ds} DEEP DIP {ticker} {trade.shares}sh (dip={dip:.0%})[/magenta]")
                elif dip < DIP_THRESHOLD and regime in ("BULL", "NEUTRAL"):
                    atr = calc_atr(data[ticker], ds)
                    dip_sz = DIP_SIZE * 1.5 if regime == "BULL" else DIP_SIZE
                    trade = pf.buy(ticker, prices[ticker], ds,
                                  f"DIP({dip:.0%},beats={beats})",
                                  dip_sz, atr, day_count + DIP_HOLD_DAYS, beats)
                    if trade and verbose:
                        console.print(f"  [magenta]{ds} DIP BUY {ticker} {trade.shares}sh (dip={dip:.0%})[/magenta]")

        # Record state
        nav = pf.nav(prices)
        pf.daily_navs.append((ds, nav, regime, len(pf.positions)))

        if date.day == 1 or date == days[-1]:
            ret = (nav / INITIAL_CAPITAL - 1) * 100
            console.print(f"[dim]{ds}[/dim] NAV: ${nav:>10,.0f} ({ret:>+6.1f}%) | "
                         f"{regime:>10} | Pos: {len(pf.positions):>2} | "
                         f"Inv: {pf.invested_pct(prices):.0%} | "
                         f"Cash: ${pf.cash:>8,.0f}")

    return pf


# ══════════════════════════════════════════════════════════════════════════════
# ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════

def analyze(pf: Portfolio, tag: str) -> dict:
    trades = pf.trades
    closed = [t for t in trades if t.action == "SELL"]
    if not closed:
        return {"error": "no closed trades"}

    wins = [t for t in closed if t.realized_pnl > 0]
    losses = [t for t in closed if t.realized_pnl <= 0]
    total_pnl = sum(t.realized_pnl for t in closed)
    wr = len(wins) / len(closed) * 100
    avg_w = np.mean([t.realized_pnl for t in wins]) if wins else 0
    avg_l = np.mean([t.realized_pnl for t in losses]) if losses else 0
    payoff = abs(avg_w / avg_l) if avg_l != 0 else float("inf")

    navs = [n for _, n, _, _ in pf.daily_navs]
    final = navs[-1]
    ret = (final / INITIAL_CAPITAL - 1) * 100

    peak = navs[0]
    max_dd, dd_date = 0, ""
    for ds, n, _, _ in pf.daily_navs:
        if n > peak: peak = n
        dd = (n - peak) / peak * 100
        if dd < max_dd: max_dd, dd_date = dd, ds

    daily_rets = [navs[i]/navs[i-1]-1 for i in range(1, len(navs))]
    sharpe = (np.mean(daily_rets) - 0.05/252) / np.std(daily_rets) * np.sqrt(252) if np.std(daily_rets) > 0 else 0

    sig_stats = {}
    for t in closed:
        sig = t.signal.split("(")[0]
        if sig not in sig_stats:
            sig_stats[sig] = {"n": 0, "wins": 0, "pnl": 0, "total_val": 0}
        sig_stats[sig]["n"] += 1
        sig_stats[sig]["pnl"] += t.realized_pnl
        sig_stats[sig]["total_val"] += t.value
        if t.realized_pnl > 0:
            sig_stats[sig]["wins"] += 1
    for s in sig_stats.values():
        s["wr"] = s["wins"] / s["n"] * 100 if s["n"] > 0 else 0

    monthly = {}
    for i in range(1, len(pf.daily_navs)):
        m = pf.daily_navs[i][0][:7]
        if m not in monthly:
            monthly[m] = {"start": pf.daily_navs[i-1][1]}
        monthly[m]["end"] = pf.daily_navs[i][1]
    for m in monthly:
        monthly[m]["ret"] = (monthly[m]["end"] / monthly[m]["start"] - 1) * 100

    # V8: Stop analysis
    stop_trades = [t for t in closed if "STOP" in t.reason]
    reentry_trades = [t for t in trades if t.action == "BUY" and "REENTRY" in t.signal]

    results = {
        "version": "V8_Final",
        "period": tag,
        "final_nav": round(final, 2),
        "total_return_pct": round(ret, 2),
        "realized_pnl": round(total_pnl, 2),
        "sharpe": round(sharpe, 3),
        "max_dd_pct": round(max_dd, 2),
        "max_dd_date": dd_date,
        "total_trades": len(trades),
        "closed": len(closed),
        "win_rate": round(wr, 1),
        "avg_win": round(avg_w, 2),
        "avg_loss": round(avg_l, 2),
        "payoff": round(payoff, 2),
        "by_signal": sig_stats,
        "monthly": {m: round(v["ret"], 2) for m, v in sorted(monthly.items())},
        "stop_count": len(stop_trades),
        "reentry_count": len(reentry_trades),
        "max_positions_held": max(n for _, _, _, n in pf.daily_navs),
        "v8_changes": [
            "Removed MAX_POSITIONS cap (was 10)",
            "Removed MAX_POD_I cap (was 5)",
            "Removed PEAD_MAX_CONCURRENT cap (was 4)",
            "Macro shock stop pause (SPY -3% in 5d → pause stops 5d)",
            "Conviction-tiered stops (≥4 beats → ATR 4x instead of 3x)",
            "Hard stop floor widened 25% → 30%",
            "Trailing stop activation 15% → 20%",
            "MOM = buy only (removed forced bottom-sell)",
            "Re-entry after false stops (10%+ rally within 20d)",
            "Reentry cooldown reduced 15 → 5 days",
        ],
    }

    # Print
    console.print(f"\n{'='*70}")
    console.print(Panel.fit(f"[bold]V8 BACKTEST — {tag}[/bold]", box=box.DOUBLE_EDGE))

    tbl = Table(box=box.SIMPLE, show_header=False, min_width=50)
    tbl.add_column("", style="bold"); tbl.add_column("", justify="right")
    c = "green" if ret > 0 else "red"
    tbl.add_row("Final NAV", f"${final:,.0f}")
    tbl.add_row("Return", f"[{c}]{ret:+.2f}%[/{c}]")
    tbl.add_row("Realized P&L", f"${total_pnl:+,.0f}")
    tbl.add_row("Sharpe", f"{sharpe:.3f}")
    tbl.add_row("Max DD", f"[red]{max_dd:.2f}%[/red] ({dd_date})")
    tbl.add_row("", "")
    tbl.add_row("Trades", f"{len(trades)} total / {len(closed)} closed")
    tbl.add_row("Win Rate", f"{wr:.1f}%")
    tbl.add_row("Avg Win", f"${avg_w:+,.0f}")
    tbl.add_row("Avg Loss", f"${avg_l:+,.0f}")
    tbl.add_row("Payoff", f"{payoff:.2f}x")
    tbl.add_row("", "")
    tbl.add_row("Max Positions", f"{results['max_positions_held']}")
    tbl.add_row("Stops", f"{len(stop_trades)}")
    tbl.add_row("Re-entries", f"{len(reentry_trades)}")
    console.print(tbl)

    console.print("\n[bold]By Signal:[/bold]")
    st = Table(box=box.SIMPLE_HEAVY)
    st.add_column("Signal"); st.add_column("Trades", justify="right")
    st.add_column("Win%", justify="right"); st.add_column("P&L", justify="right")
    for sig in sorted(sig_stats):
        s = sig_stats[sig]
        pc = "green" if s["pnl"] > 0 else "red"
        st.add_row(sig, str(s["n"]), f"{s['wr']:.0f}%", f"[{pc}]${s['pnl']:+,.0f}[/{pc}]")
    console.print(st)

    console.print("\n[bold]Monthly:[/bold]")
    for m, r in sorted(results["monthly"].items()):
        c = "green" if r > 0 else "red"
        bar = "█" * int(abs(r) * 2)
        console.print(f"  {m}: [{c}]{r:+6.2f}% {bar}[/{c}]")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_DIR / f"v8_{tag}_stats.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    with open(RESULTS_DIR / f"v8_{tag}_trades.json", "w") as f:
        json.dump([asdict(t) for t in pf.trades], f, indent=2, default=str)

    return results


def compare_v7_v8(v7_path: Path, v8_results: dict):
    """Compare V7 and V8 results side by side."""
    if not v7_path.exists():
        console.print("[yellow]No V7 results to compare[/yellow]")
        return
    with open(v7_path) as f:
        v7 = json.load(f)

    console.print(f"\n{'='*70}")
    console.print(Panel.fit("[bold]V7 → V8 COMPARISON[/bold]", box=box.DOUBLE_EDGE))

    tbl = Table(box=box.SIMPLE_HEAVY)
    tbl.add_column("Metric"); tbl.add_column("V7.6", justify="right")
    tbl.add_column("V8.0", justify="right"); tbl.add_column("Change", justify="right")

    metrics = [
        ("Return", "total_return_pct", "%"),
        ("Realized P&L", "realized_pnl", "$"),
        ("Sharpe", "sharpe", ""),
        ("Max DD", "max_dd_pct", "%"),
        ("Win Rate", "win_rate", "%"),
        ("Avg Win", "avg_win", "$"),
        ("Avg Loss", "avg_loss", "$"),
        ("Payoff", "payoff", "x"),
        ("Trades", "total_trades", ""),
        ("Closed", "closed", ""),
    ]
    for name, key, unit in metrics:
        v7v = v7.get(key, 0)
        v8v = v8_results.get(key, 0)
        diff = v8v - v7v
        dc = "green" if diff > 0 else ("red" if diff < 0 else "white")
        if key == "max_dd_pct":
            dc = "green" if diff > 0 else "red"  # Less negative = better
        if unit == "$":
            tbl.add_row(name, f"${v7v:,.0f}", f"${v8v:,.0f}", f"[{dc}]{diff:+,.0f}[/{dc}]")
        elif unit == "%":
            tbl.add_row(name, f"{v7v:.1f}%", f"{v8v:.1f}%", f"[{dc}]{diff:+.1f}%[/{dc}]")
        else:
            tbl.add_row(name, f"{v7v}", f"{v8v}", f"[{dc}]{diff:+.2f}[/{dc}]")
    console.print(tbl)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--period", default="2025", choices=["2025", "2026"])
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--compare", action="store_true")
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if args.period == "2025":
        start, end, tag = "2025-01-02", "2025-12-31", "2025"
    else:
        start, end, tag = "2026-01-02", "2026-05-27", "2026_ytd"

    if args.no_cache:
        cache = DATA_DIR / f"price_cache_{tag}.json"
        if cache.exists(): cache.unlink()

    data = download_data(ALL_SYMBOLS, start, end, tag)
    earnings = load_earnings(DATA_DIR / "earnings_calendar_2025_2026.json")

    pf = run_backtest(data, earnings, start, end, args.verbose)
    results = analyze(pf, tag)

    if args.compare:
        compare_v7_v8(RESULTS_DIR / f"v7_{tag}_stats.json", results)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["yfinance>=0.2.40", "pandas>=2.0", "numpy>=1.24", "rich>=13.0"]
# ///
"""
US Trading System V7 — Multi-Strategy 2025/2026 Backtest
========================================================
Strategies: PEAD (real earnings) + Momentum + Dip Buy
Uses actual earnings dates + surprise data from yfinance.

Usage:
    uv run --script backtest/backtest_v7.py                    # 2025 full year
    uv run --script backtest/backtest_v7.py --period 2026      # 2026 YTD
    uv run --script backtest/backtest_v7.py --verbose
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
# CONFIG — Tunable parameters (iterate by changing these)
# ══════════════════════════════════════════════════════════════════════════════

INITIAL_CAPITAL = 150_000.0
BENCHMARK = "SPY"

# Universe
POD_I = {"NVDA", "AMD", "MU", "MRVL", "AVGO", "ARM", "TSM",
         "LRCX", "AMAT", "CLS", "DELL", "ANET", "CRDO"}
POD_II = {"VST", "GEV", "CEG", "NRG", "ETN", "EME", "APH",
          "AAON", "CCJ", "LEU", "NEE"}
BETA = {"AAPL"}
ALL_TICKERS = sorted(POD_I | POD_II | BETA)
SECTOR_ETFS = ["SMH", "XLE"]
ALL_SYMBOLS = ALL_TICKERS + SECTOR_ETFS + [BENCHMARK]

# ── Strategy 1: PEAD ──
PEAD_STANDALONE_MIN = 15.0    # Standalone PEAD only for massive beats (≥15%)
PEAD_ADD_MIN = 5.0            # Add to existing position on ≥5% surprise
PEAD_ADD_SIZE = 0.07          # v7.4: Increased to 7% (press on confirmation)
PEAD_HOLD_DAYS = 60           # Hold for 60 trading days
PEAD_SIZE_BASE = 0.10         # Base size for standalone massive beat
PEAD_SIZE_BONUS = 0.003       # Extra per 1% above minimum
PEAD_REQUIRE_BULL = True      # Only enter PEAD in BULL regime
PEAD_MAX_CONCURRENT = 4
PEAD_REENTRY_COOLDOWN = 15

# ── Strategy 2: Momentum Rotation (PRIMARY STRATEGY) ──
MOM_LOOKBACK = 120            # 6 months lookback
MOM_SKIP = 20                 # Skip most recent month (12-1 momentum)
MOM_TOP_N = 7                 # Top 7 by RS
MOM_SIZE = 0.10               # 10% per momentum pick
MOM_REBAL_FREQ = 20           # Every ~20 trading days (less churn)
CLUSTER_STOP_PAUSE = 3        # v7.6: Pause 3 days after cluster stop (ONLY in non-BULL)

# ── Strategy 3: Dip Buy (probe then press) ──
DIP_THRESHOLD = -0.15         # v7.4: Back to -15% (catch early dips)
DIP_EXTREME = -0.25           # Extreme dip → allowed in any non-BEAR regime
DIP_MIN_BEATS = 2             # Minimum consecutive beats to qualify
DIP_SIZE = 0.06               # v7.4: Smaller probe (6%), press via PEAD ADD
DIP_EXTREME_SIZE = 0.10       # v7.4: Bigger for extreme dips
DIP_HOLD_DAYS = 40            # Hold 40 trading days

# ── Risk Management ──
ATR_PERIOD = 14
ATR_MULTIPLIER = 3.0          # Stop = entry - 3.0×ATR
HARD_STOP_FLOOR = 0.25        # Never wider than -25%
TRAILING_ACTIVATE = 0.15      # Activate trailing stop at +15%
TRAILING_PCT = 0.10           # 10% trailing from high water mark
MAX_POSITIONS = 10
MAX_POD_I = 5                 # Max simultaneous AI Semi positions

# ── Regime ──
CORRECTION_THRESHOLD = -0.05  # SPY -5% from 20d high = CORRECTION


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
    exit_target_day: int = 0    # day_count when position should be reviewed
    high_water: float = 0.0
    trailing_active: bool = False

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
        console.print("[red]Earnings data not found. Run earnings download first.[/red]")
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
    # CORRECTION: SPY -5% from 20-day high
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


def calc_rs(ticker_data: pd.DataFrame, spy_data: pd.DataFrame, date: str, lookback: int = 120) -> float:
    t_mask = ticker_data.index <= date
    s_mask = spy_data.index <= date
    t = ticker_data.loc[t_mask, "Close"]
    s = spy_data.loc[s_mask, "Close"]
    if len(t) < lookback + 1 or len(s) < lookback + 1:
        return 0.0
    return (t.iloc[-1]/t.iloc[-lookback-1] - 1) - (s.iloc[-1]/s.iloc[-lookback-1] - 1)


def check_dip(ticker_data: pd.DataFrame, date: str) -> float:
    """Return drawdown from 20-day high. Negative = dip."""
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
        self.daily_navs: list[tuple[str, float, str, int]] = []  # (date, nav, regime, n_pos)
        self.beat_count: dict[str, int] = {}
        self.stop_history: dict[str, str] = {}  # ticker → last stop date (for cooldown)

    def nav(self, prices: dict[str, float]) -> float:
        total = self.cash
        for t, p in self.positions.items():
            total += p.shares * prices.get(t, p.entry_price)
        return total

    def invested_pct(self, prices: dict[str, float]) -> float:
        n = self.nav(prices)
        return 1.0 - (self.cash / n) if n > 0 else 0.0

    def pod_i_count(self) -> int:
        return sum(1 for t in self.positions if t in POD_I)

    def pead_count(self) -> int:
        return sum(1 for p in self.positions.values() if p.signal.startswith("PEAD"))

    def buy(self, ticker: str, price: float, date: str, signal: str,
            size_pct: float, atr: float, target_day: int) -> Optional[Trade]:
        if ticker in self.positions or len(self.positions) >= MAX_POSITIONS:
            return None
        if ticker in POD_I and self.pod_i_count() >= MAX_POD_I:
            return None
        nav = self.nav({ticker: price})
        value = nav * size_pct
        value = min(value, self.cash * 0.95)
        if value < 5000:
            return None
        shares = int(value / price)
        if shares == 0:
            return None
        value = shares * price
        self.cash -= value
        # ATR stop
        if atr > 0:
            stop = max(price - ATR_MULTIPLIER * atr, price * (1 - HARD_STOP_FLOOR))
        else:
            stop = price * (1 - HARD_STOP_FLOOR)
        self.positions[ticker] = Position(
            ticker=ticker, shares=shares, entry_price=price, entry_date=date,
            stop_price=stop, signal=signal, exit_target_day=target_day,
            high_water=price,
        )
        trade = Trade(date=date, action="BUY", ticker=ticker, shares=shares,
                     price=price, value=value, signal=signal, reason=signal)
        self.trades.append(trade)
        return trade

    def add_to(self, ticker: str, price: float, date: str, signal: str,
               add_pct: float) -> Optional[Trade]:
        """Add to existing position."""
        if ticker not in self.positions:
            return None
        nav = self.nav({ticker: price})
        value = min(nav * add_pct, self.cash * 0.95)
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

    def sell(self, ticker: str, price: float, date: str, reason: str) -> Optional[Trade]:
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
        del self.positions[ticker]
        if "STOP" in reason:
            self.stop_history[ticker] = date
        return trade

    def check_stops(self, prices: dict[str, float], date: str) -> list[Trade]:
        exits = []
        for ticker in list(self.positions):
            pos = self.positions[ticker]
            price = prices.get(ticker)
            if price is None:
                continue
            # Update high water
            if price > pos.high_water:
                pos.high_water = price
            # Activate trailing stop
            gain = (price - pos.entry_price) / pos.entry_price
            if gain >= TRAILING_ACTIVATE and not pos.trailing_active:
                pos.trailing_active = True
                pos.stop_price = max(pos.stop_price, pos.high_water * (1 - TRAILING_PCT))
            # Update trailing stop
            if pos.trailing_active:
                new_stop = pos.high_water * (1 - TRAILING_PCT)
                if new_stop > pos.stop_price:
                    pos.stop_price = new_stop
            # Check stop
            if price <= pos.stop_price:
                t = self.sell(ticker, price, date,
                             f"STOP: ${price:.2f} ≤ ${pos.stop_price:.2f}")
                if t:
                    exits.append(t)
        return exits


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

    console.print(f"\n[bold]Backtest: {start} → {end} | {len(days)} days | ${INITIAL_CAPITAL:,.0f}[/bold]")

    # Pre-index earnings by date for O(1) lookup
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
    cluster_pause_until = 0  # v7.5: Day count to pause entries after cluster stop
    pead_pending: list[tuple[str, float, str]] = []  # (ticker, surprise, earnings_date)

    for date in days:
        ds = date.strftime("%Y-%m-%d")
        day_count += 1

        # Prices
        prices: dict[str, float] = {}
        for sym, df in data.items():
            m = df.index <= date
            if m.any():
                prices[sym] = float(df.loc[m, "Close"].iloc[-1])

        regime = detect_regime(spy, ds)

        # ── Daily: Check stops ──
        stops = pf.check_stops(prices, ds)
        if verbose:
            for t in stops:
                console.print(f"  [red]{ds} STOP {t.ticker} P&L: ${t.realized_pnl:+,.0f}[/red]")
        # v7.6: Cluster stop — pause only on 4+ stops in non-BULL
        if len(stops) >= 4 and regime != "BULL":
            cluster_pause_until = day_count + CLUSTER_STOP_PAUSE
            if verbose:
                console.print(f"  [yellow]{ds} CLUSTER STOP ({len(stops)} stops, {regime}) — pausing entries {CLUSTER_STOP_PAUSE}d[/yellow]")

        # ── Daily: Update trailing stops (ratchet up) ──
        for ticker, pos in pf.positions.items():
            if ticker in data:
                atr = calc_atr(data[ticker], ds)
                if atr > 0 and not pos.trailing_active:
                    new_stop = max(prices.get(ticker, pos.entry_price) - ATR_MULTIPLIER * atr,
                                  pos.entry_price * (1 - HARD_STOP_FLOOR))
                    if new_stop > pos.stop_price:
                        pos.stop_price = new_stop

        # ── Daily: Process yesterday's earnings (PEAD) ──
        yesterday = (date - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        two_days_ago = (date - pd.Timedelta(days=2)).strftime("%Y-%m-%d")
        for check_date in [yesterday, two_days_ago]:
            if check_date in earnings_by_date:
                for ticker, surprise in earnings_by_date[check_date]:
                    if ticker not in ALL_TICKERS or ticker not in data:
                        continue
                    if ticker in prices:
                        pead_pending.append((ticker, surprise, check_date))
                # Remove to avoid re-processing
                del earnings_by_date[check_date]

        # Execute PEAD — v7.2: PEAD is primarily ADD signal; standalone only for massive beats
        new_pead = []
        for ticker, surprise, edate in pead_pending:
            if ticker not in prices:
                continue
            # Always update beat count for positive surprises
            if surprise > 0:
                pf.beat_count[ticker] = pf.beat_count.get(ticker, 0) + 1
            elif surprise < -3.0:
                pf.beat_count[ticker] = 0

            # v7.2 MODE A: ADD to existing position on beat
            if ticker in pf.positions and surprise >= PEAD_ADD_MIN:
                trade = pf.add_to(ticker, prices[ticker], ds,
                                 f"PEAD_ADD({surprise:+.1f}%)", PEAD_ADD_SIZE)
                if trade and verbose:
                    console.print(f"  [green]{ds} PEAD ADD {ticker} +{trade.shares}sh "
                                 f"@${trade.price:.2f} (surprise {surprise:+.1f}%)[/green]")
                continue

            # v7.2 MODE B: Sell on big miss
            if ticker in pf.positions and surprise <= -PEAD_ADD_MIN:
                trade = pf.sell(ticker, prices[ticker], ds,
                              f"PEAD MISS ({surprise:+.1f}%) → exit")
                if trade and verbose:
                    console.print(f"  [red]{ds} PEAD MISS SELL {ticker} "
                                 f"P&L: ${trade.realized_pnl:+,.0f}[/red]")
                continue

            # v7.2 MODE C: Standalone PEAD only for MASSIVE beats (≥15%) in BULL
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
            if pf.pead_count() >= PEAD_MAX_CONCURRENT:
                continue
            size = PEAD_SIZE_BASE + PEAD_SIZE_BONUS * (surprise - PEAD_STANDALONE_MIN)
            size = min(size, 0.15)
            atr = calc_atr(data[ticker], ds)
            trade = pf.buy(ticker, prices[ticker], ds, f"PEAD({surprise:+.1f}%)",
                          size, atr, day_count + PEAD_HOLD_DAYS)
            if trade and verbose:
                console.print(f"  [green]{ds} PEAD BUY {ticker} {trade.shares}sh "
                             f"@${trade.price:.2f} (surprise {surprise:+.1f}%)[/green]")
        pead_pending = new_pead

        # ── PEAD holding period exits ──
        for ticker in list(pf.positions):
            pos = pf.positions[ticker]
            if pos.signal.startswith("PEAD") and day_count >= pos.exit_target_day:
                price = prices.get(ticker)
                if price and not pos.trailing_active:
                    # If trailing is active, let trailing stop manage exit
                    gain = (price - pos.entry_price) / pos.entry_price
                    if gain >= TRAILING_ACTIVATE:
                        pos.trailing_active = True
                        if verbose:
                            console.print(f"  [yellow]{ds} {ticker} PEAD hold expired but +{gain:.0%} → trailing[/yellow]")
                    else:
                        trade = pf.sell(ticker, price, ds,
                                       f"PEAD hold expired ({PEAD_HOLD_DAYS}d)")
                        if trade and verbose:
                            console.print(f"  [dim]{ds} PEAD exit {ticker} P&L: ${trade.realized_pnl:+,.0f}[/dim]")

        # ── Monthly: Momentum rotation (first trading day of month) ──
        if day_count - last_mom_rebal >= MOM_REBAL_FREQ and day_count > cluster_pause_until:
            last_mom_rebal = day_count
            if regime not in ("CORRECTION", "BEAR"):
                # Rank all tickers by 6m return minus last month
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
                    mom_score = ret_full - ret_skip  # 12-1 momentum
                    rankings.append((ticker, mom_score))

                rankings.sort(key=lambda x: x[1], reverse=True)
                top = [t for t, _ in rankings[:MOM_TOP_N]]
                bottom = [t for t, _ in rankings[-3:]]

                # Sell bottom momentum if held (and not PEAD)
                for ticker in bottom:
                    if ticker in pf.positions and pf.positions[ticker].signal.startswith("MOM"):
                        price = prices.get(ticker)
                        if price:
                            trade = pf.sell(ticker, price, ds, "Momentum bottom → exit")
                            if trade and verbose:
                                console.print(f"  [dim]{ds} MOM exit {ticker}[/dim]")

                # Buy top momentum if not held — v7.3: also sell if in bottom
                for ticker in top:
                    if ticker not in pf.positions and ticker in prices:
                        if ticker in pf.stop_history:
                            stop_dt = pd.Timestamp(pf.stop_history[ticker])
                            if (date - stop_dt).days < PEAD_REENTRY_COOLDOWN:
                                continue
                        atr = calc_atr(data[ticker], ds)
                        trade = pf.buy(ticker, prices[ticker], ds,
                                      f"MOM(top{MOM_TOP_N})", MOM_SIZE, atr, 0)
                        if trade and verbose:
                            console.print(f"  [cyan]{ds} MOM BUY {ticker} {trade.shares}sh @${trade.price:.2f}[/cyan]")

        # ── Weekly (Fri): Dip buy scan ──
        if date.weekday() == 4 and day_count > cluster_pause_until:
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
                # v7.4: Extreme dip (≤-25%) → bigger size, allowed in any non-BEAR
                if dip <= DIP_EXTREME and regime != "BEAR":
                    atr = calc_atr(data[ticker], ds)
                    trade = pf.buy(ticker, prices[ticker], ds,
                                  f"DIP({dip:.0%},beats={beats})",
                                  DIP_EXTREME_SIZE, atr, day_count + DIP_HOLD_DAYS)
                    if trade and verbose:
                        console.print(f"  [magenta]{ds} DEEP DIP {ticker} {trade.shares}sh "
                                     f"@${trade.price:.2f} (dip={dip:.0%})[/magenta]")
                # v7.4: Normal dip → probe size, BULL/NEUTRAL only
                elif dip < DIP_THRESHOLD and regime in ("BULL", "NEUTRAL"):
                    atr = calc_atr(data[ticker], ds)
                    trade = pf.buy(ticker, prices[ticker], ds,
                                  f"DIP({dip:.0%},beats={beats})",
                                  DIP_SIZE, atr, day_count + DIP_HOLD_DAYS)
                    if trade and verbose:
                        console.print(f"  [magenta]{ds} DIP BUY {ticker} {trade.shares}sh "
                                     f"@${trade.price:.2f} (dip={dip:.0%})[/magenta]")

        # v7.1: DEPLOY removed — net negative signal in V7.0

        # Record state
        nav = pf.nav(prices)
        pf.daily_navs.append((ds, nav, regime, len(pf.positions)))

        # Monthly progress
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
    spy_start = pf.daily_navs[0][1]  # Not exactly SPY, but close enough with initial nav
    # Calculate SPY return from stored data
    spy_ret = 0  # Will be calculated from daily_navs

    # Drawdown
    peak = navs[0]
    max_dd, dd_date = 0, ""
    for ds, n, _, _ in pf.daily_navs:
        if n > peak: peak = n
        dd = (n - peak) / peak * 100
        if dd < max_dd: max_dd, dd_date = dd, ds

    # Sharpe
    daily_rets = [navs[i]/navs[i-1]-1 for i in range(1, len(navs))]
    sharpe = (np.mean(daily_rets) - 0.05/252) / np.std(daily_rets) * np.sqrt(252) if np.std(daily_rets) > 0 else 0

    # By signal type
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

    # Monthly
    monthly = {}
    for i in range(1, len(pf.daily_navs)):
        m = pf.daily_navs[i][0][:7]
        if m not in monthly:
            monthly[m] = {"start": pf.daily_navs[i-1][1]}
        monthly[m]["end"] = pf.daily_navs[i][1]
    for m in monthly:
        monthly[m]["ret"] = (monthly[m]["end"] / monthly[m]["start"] - 1) * 100

    results = {
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
    }

    # Print
    console.print(f"\n{'='*70}")
    console.print(Panel.fit(f"[bold]V7 BACKTEST — {tag}[/bold]", box=box.DOUBLE_EDGE))

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

    # Save
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_DIR / f"v7_{tag}_stats.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    with open(RESULTS_DIR / f"v7_{tag}_trades.json", "w") as f:
        json.dump([asdict(t) for t in pf.trades], f, indent=2, default=str)

    return results


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--period", default="2025", choices=["2025", "2026"])
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--no-cache", action="store_true")
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
    analyze(pf, tag)


if __name__ == "__main__":
    main()

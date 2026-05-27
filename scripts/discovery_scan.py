# /// script
# requires-python = ">=3.11"
# dependencies = ["yfinance>=0.2.40"]
# ///
"""
Discovery Scan — V6.1 Signal Discovery System
==============================================
Breaks information bubbles by scanning 5 thesis-agnostic signals
across a 110-ticker universe covering all 11 GICS sectors.

Scanners:
  S1: Earnings Surprise     — Recent beat >10%, not in portfolio
  S2: Volume Breakout       — Nokia pattern: vol 1.5x + near 52W high
  S3: RS Acceleration       — Rank improvement: 4W vs 12W
  S4: Anti-Sector           — Best performers in sectors with ZERO portfolio exposure
  S5: New Highs             — 52W highs this week, excl portfolio + mega caps

Usage:
  uv run --script scripts/discovery_scan.py
  uv run --script scripts/discovery_scan.py --portfolio ../portfolio_state.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yfinance as yf

# ── Configuration ─────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_PORTFOLIO = SCRIPT_DIR.parent / "portfolio_state.json"
DEFAULT_OUTPUT_DIR = SCRIPT_DIR.parent / "research-notes" / "system-v6" / "discovery"

# Mega caps to exclude from S5 (New Highs)
MEGA_CAPS = {"AAPL", "MSFT", "GOOG", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK.B", "JPM"}

# ── Universe: 110 tickers, all 11 GICS sectors ────────────────────────────────
# Each sector: 8-12 tickers, mix of large and mid-cap ($5B-$1T+)

UNIVERSE: dict[str, list[str]] = {
    "Technology": [
        # Semis
        "AMD", "MU", "AVGO", "MRVL", "AMAT", "LRCX", "ASML",
        # Software
        "NOW", "HUBS", "DDOG", "SNOW", "PLTR", "CRWD",
        # IT Services
        "ACN", "CTSH",
    ],
    "Communication_Services": [
        "NFLX", "GOOGL", "META", "DIS", "TMUS", "CHTR", "TTD", "RDDT",
    ],
    "Consumer_Discretionary": [
        "AMZN", "TSLA", "HD", "NKE", "BKNG", "RCL", "MGM", "DECK", "LULU",
    ],
    "Consumer_Staples": [
        "COST", "WMT", "PG", "KO", "MNST", "EL", "KHC", "SFM",
    ],
    "Energy": [
        # Oil & Gas
        "XOM", "CVX", "COP", "OXY",
        # Utilities / Nuclear / Renewable
        "VST", "CEG", "GEV", "NEE", "FSLR",
    ],
    "Financials": [
        "JPM", "BAC", "GS", "V", "MA", "BX", "KKR", "COIN", "HOOD",
    ],
    "Healthcare": [
        # Pharma
        "LLY", "NVO", "ABBV", "BMY",
        # Biotech
        "VRTX", "REGN", "MRNA", "BMRN",
        # Medtech/Managed Care
        "ISRG", "UNH", "HUM",
    ],
    "Industrials": [
        # Defense
        "LMT", "RTX", "NOC",
        # Electrical Equipment
        "ETN", "HUBB", "GNRC",
        # Machinery / Construction
        "CAT", "URI", "PWR",
    ],
    "Materials": [
        "NEM", "FCX", "ALB", "CF", "CC", "STLD", "MP",
    ],
    "Real_Estate": [
        "AMT", "EQIX", "PLD", "SPG", "AVB", "WELL",
    ],
    "Utilities": [
        "AEP", "SO", "D", "XEL", "NRG", "PCG",
    ],
}

# Flat list of all unique tickers
ALL_TICKERS: list[str] = []
TICKER_TO_SECTOR: dict[str, str] = {}
for sector, tickers in UNIVERSE.items():
    for t in tickers:
        if t not in TICKER_TO_SECTOR:
            ALL_TICKERS.append(t)
            TICKER_TO_SECTOR[t] = sector


# ── Portfolio Loading ─────────────────────────────────────────────────────────

def load_portfolio_tickers(portfolio_path: Path) -> set[str]:
    """Return set of tickers currently in portfolio (both US and A-share)."""
    if not portfolio_path.exists():
        print(f"[WARN] portfolio_state.json not found at {portfolio_path}", file=sys.stderr)
        return set()

    with portfolio_path.open(encoding="utf-8") as f:
        state = json.load(f)

    tickers: set[str] = set()
    accounts = state.get("accounts", {})

    for account_key in ("us", "a_share"):
        account = accounts.get(account_key, {})
        for pos in account.get("positions", []):
            t = pos.get("ticker", "")
            if t:
                tickers.add(t.upper())
        for pos in account.get("short_positions", []):
            t = pos.get("ticker", "")
            if t:
                tickers.add(t.upper())

    return tickers


def load_portfolio_sectors(portfolio_path: Path) -> set[str]:
    """Return set of sectors covered by current US portfolio positions."""
    if not portfolio_path.exists():
        return set()

    with portfolio_path.open(encoding="utf-8") as f:
        state = json.load(f)

    sectors: set[str] = set()
    us = state.get("accounts", {}).get("us", {})

    for pos in us.get("positions", []):
        sector = pos.get("sector", "")
        if sector:
            sectors.add(sector)
    for pos in us.get("short_positions", []):
        sector = pos.get("sector", "")
        if sector:
            sectors.add(sector)

    return sectors


# ── Data Fetching ─────────────────────────────────────────────────────────────

def safe_history(ticker: str, period: str = "1y") -> "pd.DataFrame | None":
    """Fetch history for a ticker, returning None on error."""
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period=period, auto_adjust=True)
        if hist.empty:
            return None
        return hist
    except Exception:
        return None


def fetch_bulk_history(tickers: list[str], period: str = "1y") -> "dict[str, pd.DataFrame]":
    """
    Bulk-fetch 1-year history via yf.download for speed.
    Returns {ticker: DataFrame(Close, Volume)}.
    Falls back to individual fetch on error.
    """
    import pandas as pd

    print(f"  Fetching {len(tickers)} tickers ({period} history)…", file=sys.stderr, flush=True)

    try:
        raw = yf.download(
            tickers,
            period=period,
            auto_adjust=True,
            progress=False,
            threads=True,
        )
        if raw.empty:
            return {}

        # Multi-ticker download: columns are (field, ticker)
        result: dict[str, pd.DataFrame] = {}

        if isinstance(raw.columns, pd.MultiIndex):
            close_all = raw["Close"] if "Close" in raw.columns.get_level_values(0) else None
            vol_all   = raw["Volume"] if "Volume" in raw.columns.get_level_values(0) else None

            for t in tickers:
                try:
                    frames: dict[str, "pd.Series"] = {}
                    if close_all is not None and t in close_all.columns:
                        frames["Close"] = close_all[t].dropna()
                    if vol_all is not None and t in vol_all.columns:
                        frames["Volume"] = vol_all[t].dropna()
                    if frames:
                        result[t] = pd.DataFrame(frames)
                except Exception:
                    pass
        else:
            # Single ticker returned as flat DataFrame
            if len(tickers) == 1:
                t = tickers[0]
                if "Close" in raw.columns:
                    result[t] = raw[["Close", "Volume"]].dropna()

        return result

    except Exception as e:
        print(f"  [WARN] Bulk fetch failed ({e}), skipping batch", file=sys.stderr)
        return {}


def get_ticker_info(ticker: str) -> dict:
    """Get basic info (name, sector) from yfinance. Cached implicitly."""
    try:
        t = yf.Ticker(ticker)
        info = t.fast_info
        name = getattr(info, "company", None) or ticker
        # fast_info doesn't have sector; use the pre-mapped sector
        return {"name": name}
    except Exception:
        return {"name": ticker}


# ── Scanner S1: Earnings Surprise ─────────────────────────────────────────────

def scan_earnings_surprise(
    universe: list[str],
    portfolio_tickers: set[str],
    top_n: int = 20,
) -> list[dict]:
    """
    Find tickers with recent earnings surprise > 10%.
    Uses yfinance earnings_history or quarterly_financials.
    """
    results: list[dict] = []

    candidates = [t for t in universe if t not in portfolio_tickers]
    print(f"  S1: Checking earnings for {len(candidates)} tickers…", file=sys.stderr, flush=True)

    for ticker in candidates:
        try:
            t = yf.Ticker(ticker)

            # Try earnings_history first (most reliable for beat%)
            history = None
            try:
                history = t.earnings_history
            except Exception:
                pass

            if history is not None and not history.empty:
                # earnings_history columns: epsActual, epsEstimate, epsDifference, surprisePercent
                if "surprisePercent" in history.columns:
                    # Get most recent quarter
                    recent = history.dropna(subset=["surprisePercent"])
                    if not recent.empty:
                        latest = recent.iloc[-1]
                        surprise_pct = float(latest["surprisePercent"]) * 100  # convert to %
                        if surprise_pct > 10.0:
                            eps_actual = float(latest.get("epsActual", 0))
                            eps_est    = float(latest.get("epsEstimate", 0))
                            results.append({
                                "ticker": ticker,
                                "sector": TICKER_TO_SECTOR.get(ticker, "N/A"),
                                "surprise_pct": round(surprise_pct, 1),
                                "eps_actual": round(eps_actual, 2),
                                "eps_estimate": round(eps_est, 2),
                            })
                        continue

            # Fallback: compute from quarterly earnings if available
            try:
                qe = t.quarterly_earnings
                if qe is not None and not qe.empty and "Actual" in qe.columns and "Estimate" in qe.columns:
                    latest = qe.iloc[0]
                    actual = float(latest["Actual"])
                    est    = float(latest["Estimate"])
                    if est != 0:
                        surprise_pct = (actual - est) / abs(est) * 100
                        if surprise_pct > 10.0:
                            results.append({
                                "ticker": ticker,
                                "sector": TICKER_TO_SECTOR.get(ticker, "N/A"),
                                "surprise_pct": round(surprise_pct, 1),
                                "eps_actual": round(actual, 2),
                                "eps_estimate": round(est, 2),
                            })
            except Exception:
                pass

        except Exception:
            continue

    results.sort(key=lambda x: -x["surprise_pct"])
    return results[:top_n]


# ── Scanner S2: Volume Breakout (Nokia Pattern) ───────────────────────────────

def scan_volume_breakout(
    hist_data: "dict[str, pd.DataFrame]",
    universe: list[str],
    vol_ratio_threshold: float = 1.5,
    near_high_pct: float = 0.95,
    top_n: int = 15,
) -> list[dict]:
    """
    Nokia pattern: 10d avg volume > 60d avg volume by 1.5x
    AND current price within 5% of 52-week high.
    """
    results: list[dict] = []

    for ticker in universe:
        df = hist_data.get(ticker)
        if df is None or len(df) < 70:
            continue

        try:
            close  = df["Close"].dropna()
            volume = df["Volume"].dropna()

            if len(close) < 70 or len(volume) < 70:
                continue

            current_price = float(close.iloc[-1])
            high_52w      = float(close.tail(252).max()) if len(close) >= 252 else float(close.max())

            # Price must be near 52W high
            if current_price < high_52w * near_high_pct:
                continue

            # Volume ratio
            vol_10d = float(volume.tail(10).mean())
            vol_60d = float(volume.tail(60).mean())
            if vol_60d <= 0:
                continue

            vol_ratio = vol_10d / vol_60d
            if vol_ratio < vol_ratio_threshold:
                continue

            dist_from_high = (current_price / high_52w - 1.0) * 100

            results.append({
                "ticker": ticker,
                "sector": TICKER_TO_SECTOR.get(ticker, "N/A"),
                "vol_ratio": round(vol_ratio, 2),
                "current_price": round(current_price, 2),
                "high_52w": round(high_52w, 2),
                "dist_from_high_pct": round(dist_from_high, 1),
            })

        except Exception:
            continue

    results.sort(key=lambda x: -x["vol_ratio"])
    return results[:top_n]


# ── Scanner S3: RS Acceleration ───────────────────────────────────────────────

def scan_rs_acceleration(
    hist_data: "dict[str, pd.DataFrame]",
    universe: list[str],
    top_n: int = 15,
) -> list[dict]:
    """
    Rank improvement: 4-week return rank vs 12-week return rank.
    Stocks whose 4W rank jumped most vs 12W rank = accelerating momentum.
    """
    # Compute returns
    rows: list[dict] = []
    for ticker in universe:
        df = hist_data.get(ticker)
        if df is None or len(df) < 65:
            continue
        try:
            close = df["Close"].dropna()
            if len(close) < 65:
                continue

            ret_4w  = (float(close.iloc[-1]) / float(close.iloc[-21]) - 1) * 100  # ~4W = 20 trading days
            ret_12w = (float(close.iloc[-1]) / float(close.iloc[-63]) - 1) * 100  # ~12W = 63 trading days

            rows.append({
                "ticker": ticker,
                "sector": TICKER_TO_SECTOR.get(ticker, "N/A"),
                "ret_4w": round(ret_4w, 2),
                "ret_12w": round(ret_12w, 2),
            })
        except Exception:
            continue

    if len(rows) < 5:
        return []

    # Rank all tickers by 4W and 12W return (higher rank = better)
    n = len(rows)
    sorted_4w  = sorted(rows, key=lambda x: x["ret_4w"])
    sorted_12w = sorted(rows, key=lambda x: x["ret_12w"])

    rank_4w:  dict[str, int] = {r["ticker"]: i for i, r in enumerate(sorted_4w)}
    rank_12w: dict[str, int] = {r["ticker"]: i for i, r in enumerate(sorted_12w)}

    for r in rows:
        t = r["ticker"]
        r["rank_4w"]  = rank_4w[t]
        r["rank_12w"] = rank_12w[t]
        # Positive acceleration = rank improved (higher rank = higher index = better)
        r["accel"] = rank_4w[t] - rank_12w[t]

    rows.sort(key=lambda x: -x["accel"])
    return rows[:top_n]


# ── Scanner S4: Anti-Sector ───────────────────────────────────────────────────

def scan_anti_sector(
    hist_data: "dict[str, pd.DataFrame]",
    portfolio_sector_labels: set[str],
    top_n_per_sector: int = 5,
) -> dict[str, list[dict]]:
    """
    Map portfolio sector labels to GICS universe sectors (best-effort),
    then find top performers in uncovered GICS sectors.
    Returns {sector_name: [top performers]}.
    """
    # Build sector → portfolio ticker mapping using universe GICS sectors
    # We check which GICS universe sectors have tickers in the portfolio
    # by cross-referencing TICKER_TO_SECTOR
    # (portfolio uses free-form sector labels, not GICS)

    # Strategy: a GICS sector is "covered" if any of its tickers appear in the
    # portfolio. This is more reliable than matching free-form labels.
    from pathlib import Path as _P  # already imported but scope-safe

    # We'll use a simple approach: check which GICS sectors have tickers in portfolio
    # This is computed in the caller — pass as covered_gics_sectors
    # For now return all — anti_sector_gaps is computed below using hist_data

    results: dict[str, list[dict]] = {}

    for sector, tickers in UNIVERSE.items():
        sector_rows: list[dict] = []
        for ticker in tickers:
            df = hist_data.get(ticker)
            if df is None or len(df) < 25:
                continue
            try:
                close = df["Close"].dropna()
                if len(close) < 25:
                    continue

                ret_1m = (float(close.iloc[-1]) / float(close.iloc[-22]) - 1) * 100
                # YTD: use available data up to 1y start
                ytd_start_idx = max(0, len(close) - 126)  # ~6 months as proxy for YTD
                ret_ytd = (float(close.iloc[-1]) / float(close.iloc[ytd_start_idx]) - 1) * 100

                sector_rows.append({
                    "ticker": ticker,
                    "sector": sector,
                    "ret_1m": round(ret_1m, 1),
                    "ret_ytd": round(ret_ytd, 1),
                })
            except Exception:
                continue

        if sector_rows:
            sector_rows.sort(key=lambda x: -x["ret_1m"])
            results[sector] = sector_rows[:top_n_per_sector]

    return results


# ── Scanner S5: New 52W Highs ─────────────────────────────────────────────────

def scan_new_highs(
    hist_data: "dict[str, pd.DataFrame]",
    universe: list[str],
    portfolio_tickers: set[str],
    lookback_days: int = 5,
) -> list[dict]:
    """
    Stocks hitting 52W high within the last `lookback_days` trading days,
    excluding portfolio tickers and mega caps.
    """
    exclusions = portfolio_tickers | MEGA_CAPS
    results: list[dict] = []

    for ticker in universe:
        if ticker in exclusions:
            continue

        df = hist_data.get(ticker)
        if df is None or len(df) < 60:
            continue

        try:
            close = df["Close"].dropna()
            if len(close) < 60:
                continue

            all_prices  = close.tolist()
            recent      = all_prices[-lookback_days:]
            history_252 = all_prices[-252:] if len(all_prices) >= 252 else all_prices
            high_52w    = max(history_252)
            current     = float(close.iloc[-1])

            # Check if any price in the last `lookback_days` hit the 52W high
            hit_high = any(p >= high_52w * 0.999 for p in recent)  # within 0.1% of high
            if not hit_high:
                continue

            results.append({
                "ticker": ticker,
                "sector": TICKER_TO_SECTOR.get(ticker, "N/A"),
                "current_price": round(current, 2),
                "high_52w": round(high_52w, 2),
                "pct_above_prior_high": round((current / high_52w - 1) * 100, 2),
            })

        except Exception:
            continue

    results.sort(key=lambda x: -x["pct_above_prior_high"])
    return results


# ── Signal Aggregation ────────────────────────────────────────────────────────

def aggregate_signals(
    s1: list[dict],
    s2: list[dict],
    s3: list[dict],
    s4_map: dict[str, list[dict]],
    s5: list[dict],
) -> list[dict]:
    """Count how many scanners flagged each ticker."""
    from collections import defaultdict

    scanner_hits: dict[str, list[str]] = defaultdict(list)

    for r in s1:
        scanner_hits[r["ticker"]].append("S1:EarningsBeat")
    for r in s2:
        scanner_hits[r["ticker"]].append("S2:VolBreakout")
    for r in s3:
        scanner_hits[r["ticker"]].append("S3:RSAccel")
    for sector_list in s4_map.values():
        for r in sector_list:
            scanner_hits[r["ticker"]].append("S4:AntiSector")
    for r in s5:
        scanner_hits[r["ticker"]].append("S5:NewHigh")

    results: list[dict] = []
    for ticker, scanners in scanner_hits.items():
        n = len(scanners)
        if n >= 3:
            rec = "PRIORITY"
        elif n >= 2:
            rec = "INVESTIGATE"
        else:
            rec = "MONITOR"

        results.append({
            "ticker": ticker,
            "sector": TICKER_TO_SECTOR.get(ticker, "N/A"),
            "n_hits": n,
            "scanners": scanners,
            "recommendation": rec,
        })

    results.sort(key=lambda x: (-x["n_hits"], x["ticker"]))
    return results


# ── Output Formatting ─────────────────────────────────────────────────────────

def _pad(s: str, width: int) -> str:
    return s[:width].ljust(width)


def print_s1(rows: list[dict]) -> None:
    print()
    print("[S1] EARNINGS SURPRISE (beat >10%, NOT in portfolio)")
    print(f"  {'Ticker':<7} {'Sector':<22} {'Surprise%':>10}  {'EPS Act':>8}  {'EPS Est':>8}")
    print("  " + "─" * 60)
    if not rows:
        print("  (no data found)")
        return
    for r in rows:
        print(f"  {r['ticker']:<7} {_pad(r['sector'], 22)} {r['surprise_pct']:>9.1f}%  "
              f"{r['eps_actual']:>8.2f}  {r['eps_estimate']:>8.2f}")


def print_s2(rows: list[dict]) -> None:
    print()
    print("[S2] VOLUME BREAKOUT — Nokia Pattern (vol >1.5x + near 52W high)")
    print(f"  {'Ticker':<7} {'Sector':<22} {'VolRatio':>9}  {'Price':>8}  {'52WHigh':>9}  {'Dist':>6}")
    print("  " + "─" * 68)
    if not rows:
        print("  (no breakouts found)")
        return
    for r in rows:
        print(f"  {r['ticker']:<7} {_pad(r['sector'], 22)} {r['vol_ratio']:>8.2f}x  "
              f"{r['current_price']:>8.2f}  {r['high_52w']:>9.2f}  {r['dist_from_high_pct']:>5.1f}%")


def print_s3(rows: list[dict]) -> None:
    print()
    print("[S3] RS ACCELERATION — Rank improvement: 4W vs 12W return")
    print(f"  {'Ticker':<7} {'Sector':<22} {'4W_Ret':>8}  {'12W_Ret':>9}  {'Accel(rank)':>12}")
    print("  " + "─" * 65)
    if not rows:
        print("  (insufficient data)")
        return
    for r in rows:
        sign_4w  = "+" if r["ret_4w"]  >= 0 else ""
        sign_12w = "+" if r["ret_12w"] >= 0 else ""
        sign_acc = "+" if r["accel"]   >= 0 else ""
        print(f"  {r['ticker']:<7} {_pad(r['sector'], 22)} "
              f"{sign_4w}{r['ret_4w']:>6.1f}%  "
              f"{sign_12w}{r['ret_12w']:>7.1f}%  "
              f"{sign_acc}{r['accel']:>10}")


def print_s4(s4_map: dict[str, list[dict]], covered_sectors: set[str]) -> None:
    print()
    print("[S4] ANTI-SECTOR — Zero-exposure sectors, top performers")

    uncovered = {s for s in UNIVERSE if s not in covered_sectors}
    if not uncovered:
        print("  All 11 GICS sectors have portfolio exposure — no anti-sector gaps!")
        return

    for sector in sorted(uncovered):
        rows = s4_map.get(sector, [])
        print(f"\n  Sector: {sector}  (NO PORTFOLIO EXPOSURE)")
        if not rows:
            print("    (no data)")
            continue
        print(f"    {'Ticker':<7} {'1M_Ret':>8}  {'YTD_Ret':>9}")
        print("    " + "─" * 30)
        for r in rows:
            sign_1m  = "+" if r["ret_1m"]  >= 0 else ""
            sign_ytd = "+" if r["ret_ytd"] >= 0 else ""
            print(f"    {r['ticker']:<7} {sign_1m}{r['ret_1m']:>6.1f}%  {sign_ytd}{r['ret_ytd']:>7.1f}%")


def print_s5(rows: list[dict]) -> None:
    print()
    print("[S5] NEW 52W HIGHS (this week, excl portfolio + mega caps)")
    print(f"  {'Ticker':<7} {'Sector':<22} {'Price':>8}  {'52WHigh':>9}  {'Dist%':>7}")
    print("  " + "─" * 60)
    if not rows:
        print("  (no new highs found)")
        return
    for r in rows:
        sign_dist = "+" if r["pct_above_prior_high"] >= 0 else ""
        print(f"  {r['ticker']:<7} {_pad(r['sector'], 22)} {r['current_price']:>8.2f}  "
              f"{r['high_52w']:>9.2f}  {sign_dist}{r['pct_above_prior_high']:>5.2f}%")


def print_aggregation(
    agg: list[dict],
    n_new_names: int,
    covered_sectors: set[str],
    portfolio_tickers: set[str],
) -> None:
    print()
    print("=" * 68)
    print("=== SIGNAL AGGREGATION ===")
    print("=" * 68)

    priority    = [r for r in agg if r["recommendation"] == "PRIORITY"]
    investigate = [r for r in agg if r["recommendation"] == "INVESTIGATE"]
    monitor     = [r for r in agg if r["recommendation"] == "MONITOR"]

    if priority:
        print()
        print("  *** PRIORITY (3+ scanners hit) ***")
        print(f"  {'Ticker':<7} {'Sector':<22} {'Scanners':<40} {'Action'}")
        print("  " + "─" * 80)
        for r in priority:
            scanners_str = ", ".join(r["scanners"])
            print(f"  {r['ticker']:<7} {_pad(r['sector'], 22)} {_pad(scanners_str, 40)} RESEARCH NOW")

    if investigate:
        print()
        print("  INVESTIGATE (2 scanners hit):")
        print(f"  {'Ticker':<7} {'Sector':<22} {'Scanners':<40} {'Action'}")
        print("  " + "─" * 80)
        for r in investigate:
            scanners_str = ", ".join(r["scanners"])
            print(f"  {r['ticker']:<7} {_pad(r['sector'], 22)} {_pad(scanners_str, 40)} Add to Watchlist")

    if monitor:
        print()
        print("  MONITOR (1 scanner hit):")
        monitor_brief = ", ".join(r["ticker"] for r in monitor)
        print(f"  {monitor_brief}")

    n_sectors_covered = len(covered_sectors)
    all_sectors = set(UNIVERSE.keys())
    pct_not_in_portfolio = 100.0 * n_new_names / max(1, len(ALL_TICKERS))

    print()
    print(f"  Discovery Rate: {n_new_names} new names  |  "
          f"Sector Coverage: {n_sectors_covered}/{len(all_sectors)}  |  "
          f"Anti-Portfolio Gap: {pct_not_in_portfolio:.0f}% of universe NOT in portfolio")


# ── JSON Output ───────────────────────────────────────────────────────────────

def save_json(
    output_dir: Path,
    date_str: str,
    s1: list[dict],
    s2: list[dict],
    s3: list[dict],
    s4_map: dict[str, list[dict]],
    s5: list[dict],
    agg: list[dict],
    covered_sectors: set[str],
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "latest_scan.json"

    payload = {
        "scan_date": date_str,
        "universe_size": len(ALL_TICKERS),
        "covered_gics_sectors": sorted(covered_sectors),
        "uncovered_gics_sectors": sorted(s for s in UNIVERSE if s not in covered_sectors),
        "s1_earnings_surprise": s1,
        "s2_volume_breakout": s2,
        "s3_rs_acceleration": s3,
        "s4_anti_sector": {k: v for k, v in s4_map.items() if k not in covered_sectors},
        "s5_new_highs": s5,
        "signal_aggregation": agg,
        "priority_count": sum(1 for r in agg if r["recommendation"] == "PRIORITY"),
        "investigate_count": sum(1 for r in agg if r["recommendation"] == "INVESTIGATE"),
    }

    with out_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    return out_path


# ── Covered Sector Mapping ────────────────────────────────────────────────────

def compute_covered_gics_sectors(portfolio_tickers: set[str]) -> set[str]:
    """
    Determine which GICS universe sectors are 'covered' by portfolio.
    A sector is covered if any of its universe tickers is in the portfolio.
    """
    covered: set[str] = set()
    for sector, tickers in UNIVERSE.items():
        for t in tickers:
            if t in portfolio_tickers:
                covered.add(sector)
                break
    return covered


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Discovery Scan — V6.1 Signal Discovery")
    parser.add_argument(
        "--portfolio",
        type=Path,
        default=DEFAULT_PORTFOLIO,
        help="Path to portfolio_state.json",
    )
    args = parser.parse_args()

    date_str = datetime.now().strftime("%Y-%m-%d")

    print(f"\n=== DISCOVERY SCAN — {date_str} ===\n", flush=True)
    print(f"Universe: {len(ALL_TICKERS)} tickers across {len(UNIVERSE)} GICS sectors", flush=True)

    # Load portfolio
    portfolio_tickers = load_portfolio_tickers(args.portfolio)
    print(f"Portfolio: {len(portfolio_tickers)} tickers loaded from {args.portfolio}", flush=True)

    # Determine covered GICS sectors (by ticker overlap)
    covered_sectors = compute_covered_gics_sectors(portfolio_tickers)
    uncovered_sectors = [s for s in UNIVERSE if s not in covered_sectors]
    print(f"GICS sector coverage: {len(covered_sectors)}/11 covered, "
          f"{len(uncovered_sectors)} gaps: {uncovered_sectors}", flush=True)

    # ── Bulk data fetch ───────────────────────────────────────────────────────
    print("\nFetching market data…", file=sys.stderr, flush=True)

    # Fetch in two batches to avoid timeouts
    batch1 = ALL_TICKERS[:60]
    batch2 = ALL_TICKERS[60:]

    hist_data: dict[str, "pd.DataFrame"] = {}

    data1 = fetch_bulk_history(batch1, period="1y")
    hist_data.update(data1)

    if batch2:
        data2 = fetch_bulk_history(batch2, period="1y")
        hist_data.update(data2)

    fetched = len(hist_data)
    print(f"  Data fetched: {fetched}/{len(ALL_TICKERS)} tickers", file=sys.stderr, flush=True)

    # ── Run Scanners ──────────────────────────────────────────────────────────

    print("\nRunning S1: Earnings Surprise…", file=sys.stderr, flush=True)
    s1 = scan_earnings_surprise(ALL_TICKERS, portfolio_tickers, top_n=20)

    print("Running S2: Volume Breakout…", file=sys.stderr, flush=True)
    s2 = scan_volume_breakout(hist_data, ALL_TICKERS, top_n=15)

    print("Running S3: RS Acceleration…", file=sys.stderr, flush=True)
    s3 = scan_rs_acceleration(hist_data, ALL_TICKERS, top_n=15)

    print("Running S4: Anti-Sector…", file=sys.stderr, flush=True)
    s4_map = scan_anti_sector(hist_data, covered_sectors, top_n_per_sector=5)

    print("Running S5: New 52W Highs…", file=sys.stderr, flush=True)
    s5 = scan_new_highs(hist_data, ALL_TICKERS, portfolio_tickers, lookback_days=5)

    # ── Aggregate ─────────────────────────────────────────────────────────────
    agg = aggregate_signals(s1, s2, s3, s4_map, s5)

    # Count new names (not in portfolio)
    n_new_names = sum(1 for r in agg if r["ticker"] not in portfolio_tickers)

    # ── Print Results ─────────────────────────────────────────────────────────
    print_s1(s1)
    print_s2(s2)
    print_s3(s3)
    print_s4(s4_map, covered_sectors)
    print_s5(s5)
    print_aggregation(agg, n_new_names, covered_sectors, portfolio_tickers)

    # ── Save JSON ─────────────────────────────────────────────────────────────
    out_path = save_json(
        DEFAULT_OUTPUT_DIR,
        date_str,
        s1, s2, s3, s4_map, s5, agg,
        covered_sectors,
    )
    print(f"\n  JSON saved → {out_path}", flush=True)
    print()


if __name__ == "__main__":
    main()

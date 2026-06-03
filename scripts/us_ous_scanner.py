# /// script
# requires-python = ">=3.11"
# dependencies = ["yfinance>=0.2.40", "rich>=13.0", "lxml"]
# ///
"""
US OUS Unified Scanner — Single-pass PEG + F21 + Validation + Delta
====================================================================
Replaces 3 separate scripts (us_peg_calculator + earnings_rhythm + us_data_validator)
with one pass per ticker. Reads universe from ous_universe.json, saves results to
ous_scan_results.json, auto-diffs against previous scan.

Usage:
  uv run --script scripts/us_ous_scanner.py                    # full scan (F21 for portfolio+T1/T2)
  uv run --script scripts/us_ous_scanner.py --ticker NVDA,AVGO # incremental update
  uv run --script scripts/us_ous_scanner.py --category mainline # scan one category
  uv run --script scripts/us_ous_scanner.py --portfolio         # scan only portfolio holdings
  uv run --script scripts/us_ous_scanner.py --f21               # force F21 for ALL stocks
  uv run --script scripts/us_ous_scanner.py --skip-f21          # PEG-only speed mode (~1min)
  uv run --script scripts/us_ous_scanner.py --delta             # show changes since last scan
  uv run --script scripts/us_ous_scanner.py --json              # JSON output
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from threading import Lock
from typing import Optional

import yfinance as yf
from rich.console import Console
from rich.table import Table
from rich import box
from rich.text import Text
from rich.panel import Panel

console = Console()
ROOT = Path(__file__).resolve().parent.parent
UNIVERSE_FILE = ROOT / "ous_universe.json"
RESULTS_FILE = ROOT / "ous_scan_results.json"
PORTFOLIO_FILE = ROOT / "portfolio_state.json"
CACHE_FILE = ROOT / "data" / "fundamentals_cache.json"
CACHE_TTL_DAYS = 90


def load_cache() -> dict[str, dict]:
    if not CACHE_FILE.exists():
        return {}
    try:
        return json.loads(CACHE_FILE.read_text())
    except Exception:
        return {}


def save_cache(cache: dict[str, dict]):
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, indent=2, ensure_ascii=False, default=str))


def is_cache_fresh(entry: dict) -> bool:
    cached_at = entry.get("cached_at")
    if not cached_at:
        return False
    try:
        dt = datetime.fromisoformat(cached_at)
        age_days = (datetime.now(timezone.utc) - dt).days
        if age_days > CACHE_TTL_DAYS:
            return False
        next_earn = entry.get("next_earnings")
        if next_earn:
            try:
                earn_dt = datetime.strptime(next_earn[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                days_to_earn = (earn_dt - datetime.now(timezone.utc)).days
                if -1 <= days_to_earn <= 3:
                    return False
            except Exception:
                pass
        return True
    except Exception:
        return False


@dataclass
class StockScan:
    ticker: str
    category: str
    f9_tier: Optional[str] = None
    role: Optional[str] = None
    supply_moat: str = ""
    in_portfolio: bool = False
    flags: list = field(default_factory=list)
    # Price data
    price: Optional[float] = None
    change_pct: Optional[float] = None
    week52_high: Optional[float] = None
    week52_low: Optional[float] = None
    market_cap_b: Optional[float] = None
    # PEG data
    fwd_pe: Optional[float] = None
    eps_fy0: Optional[float] = None
    eps_fy1: Optional[float] = None
    eps_year_ago: Optional[float] = None
    cagr_2y: Optional[float] = None
    peg: Optional[float] = None
    analyst_count: Optional[int] = None
    # F21 data
    beat_rate: Optional[str] = None
    beat_count: int = 0
    total_quarters: int = 0
    avg_surprise: Optional[float] = None
    surprise_trend: Optional[float] = None
    f21_class: Optional[str] = None
    f21_signal: Optional[str] = None
    next_earnings: Optional[str] = None
    # Validation flags
    div_yield_bug: bool = False
    eps_declining: bool = False
    cycle_peg: bool = False
    negative_growth: bool = False
    low_coverage: bool = False
    # Scan metadata
    scan_time: Optional[str] = None
    error: Optional[str] = None


def load_universe(filter_tickers=None, filter_category=None, portfolio_only=False) -> list[dict]:
    if not UNIVERSE_FILE.exists():
        console.print("[red]ERROR: ous_universe.json not found. Create it first.[/red]")
        sys.exit(1)
    data = json.loads(UNIVERSE_FILE.read_text())
    stocks = data.get("stocks", [])
    if filter_tickers:
        tickers_set = {t.upper() for t in filter_tickers}
        stocks = [s for s in stocks if s["ticker"].upper() in tickers_set]
    if filter_category:
        stocks = [s for s in stocks if s["category"] == filter_category]
    if portfolio_only:
        ps_path = ROOT / "portfolio_state.json"
        if ps_path.exists():
            ps = json.loads(ps_path.read_text())
            actual_tickers = {p["ticker"] for p in ps.get("accounts", {}).get("us", {}).get("positions", [])}
            # Keep OUS entries that match actual holdings
            stocks = [s for s in stocks if s["ticker"] in actual_tickers]
            # Add any held tickers not in OUS universe (minimal entry)
            ous_tickers = {s["ticker"] for s in stocks}
            for t in actual_tickers - ous_tickers:
                if t not in {"QQQ", "SPY", "TQQQ", "SQQQ"}:  # skip ETFs
                    stocks.append({"ticker": t, "name": t, "category": "portfolio_new"})
        else:
            stocks = [s for s in stocks if s.get("in_portfolio", False)]
    return stocks


def load_previous_results() -> dict[str, dict]:
    if not RESULTS_FILE.exists():
        return {}
    try:
        data = json.loads(RESULTS_FILE.read_text())
        return {r["ticker"]: r for r in data.get("results", [])}
    except Exception:
        return {}


def fetch_ticker_data(ticker: str, universe_entry: dict, cache: dict = None, skip_f21: bool = False) -> StockScan:
    scan = StockScan(
        ticker=ticker,
        category=universe_entry.get("category", "unknown"),
        f9_tier=universe_entry.get("f9_tier"),
        role=universe_entry.get("role"),
        supply_moat=universe_entry.get("supply_moat", ""),
        in_portfolio=universe_entry.get("in_portfolio", False),
        flags=universe_entry.get("flags", []),
        scan_time=datetime.now(timezone.utc).isoformat(),
    )

    # Check if cache has fresh fundamentals — if so, only fetch price
    cache_hit = False
    cached_entry = (cache or {}).get(ticker)
    if cached_entry and is_cache_fresh(cached_entry):
        cache_hit = True

    try:
        t = yf.Ticker(ticker)

        # === 1. Price data (fast_info) — always fresh ===
        try:
            fi = t.fast_info
            scan.price = float(fi.last_price) if fi.last_price else None
            scan.change_pct = (
                round((fi.last_price / fi.previous_close - 1) * 100, 2)
                if fi.last_price and fi.previous_close and fi.previous_close > 0
                else None
            )
            scan.week52_high = float(fi.year_high) if hasattr(fi, 'year_high') and fi.year_high else None
            scan.week52_low = float(fi.year_low) if hasattr(fi, 'year_low') and fi.year_low else None
            mc = fi.market_cap if hasattr(fi, 'market_cap') and fi.market_cap else None
            scan.market_cap_b = round(mc / 1e9, 1) if mc else None
        except Exception:
            pass

        if not scan.price:
            try:
                hist = t.history(period="5d")
                if not hist.empty:
                    scan.price = float(hist["Close"].iloc[-1])
            except Exception:
                pass

        if not scan.price:
            scan.error = "price fetch failed"
            return scan

        # === 2. Earnings estimates (PEG calc) ===
        if cache_hit:
            # Restore fundamentals from cache, recalculate PEG with fresh price
            scan.eps_fy0 = cached_entry.get("eps_fy0")
            scan.eps_fy1 = cached_entry.get("eps_fy1")
            scan.eps_year_ago = cached_entry.get("eps_year_ago")
            scan.analyst_count = cached_entry.get("analyst_count")
            scan.beat_rate = cached_entry.get("beat_rate")
            scan.f21_class = cached_entry.get("f21_class")
            scan.f21_signal = cached_entry.get("f21_signal")
            scan.next_earnings = cached_entry.get("next_earnings")
            # Recalculate PEG with fresh price + cached EPS
            if scan.price and scan.eps_fy1 and scan.eps_fy1 > 0:
                scan.fwd_pe = round(scan.price / scan.eps_fy1, 1)
                if scan.eps_year_ago and scan.eps_year_ago > 0:
                    ratio = scan.eps_fy1 / scan.eps_year_ago
                    if ratio > 0:
                        scan.cagr_2y = round((ratio ** 0.5 - 1) * 100, 1)
                        if scan.cagr_2y > 0:
                            scan.peg = round(scan.fwd_pe / scan.cagr_2y, 2)
                            if scan.cagr_2y > 100:
                                scan.cycle_peg = True
                                if "cycle_peg" not in scan.flags:
                                    scan.flags.append("cycle_peg")
                        else:
                            scan.negative_growth = True
                            if "negative_growth" not in scan.flags:
                                scan.flags.append("negative_growth")
            if scan.eps_fy0 and scan.eps_fy1 and scan.eps_fy1 < scan.eps_fy0 * 0.97:
                scan.eps_declining = True
                if "eps_declining" not in scan.flags:
                    scan.flags.append("eps_declining")
            if scan.analyst_count is not None and scan.analyst_count < 5:
                scan.low_coverage = True
                if "low_coverage" not in scan.flags:
                    scan.flags.append("low_coverage")
            return scan

        # DataFrame layout: index=periods (0y, +1y), columns=stats (avg, yearAgoEps, numberOfAnalysts)
        try:
            ee = t.earnings_estimate
            if ee is not None and not ee.empty:
                def _safe_val(row, col):
                    try:
                        if row in ee.index and col in ee.columns:
                            v = ee.loc[row, col]
                            if v is not None and not (isinstance(v, float) and math.isnan(v)):
                                return float(v)
                    except Exception:
                        pass
                    return None

                scan.eps_fy0 = _safe_val("0y", "avg")
                scan.eps_fy1 = _safe_val("+1y", "avg")
                scan.eps_year_ago = _safe_val("0y", "yearAgoEps")
                ac = _safe_val("+1y", "numberOfAnalysts")
                scan.analyst_count = int(ac) if ac else None

            # PEG calculation
            if scan.price and scan.eps_fy1 and scan.eps_fy1 > 0:
                scan.fwd_pe = round(scan.price / scan.eps_fy1, 1)

                if scan.eps_year_ago and scan.eps_year_ago > 0 and scan.eps_fy1 > 0:
                    ratio = scan.eps_fy1 / scan.eps_year_ago
                    if ratio > 0:
                        scan.cagr_2y = round((ratio ** 0.5 - 1) * 100, 1)

                        if scan.cagr_2y > 0:
                            scan.peg = round(scan.fwd_pe / scan.cagr_2y, 2)

                            if scan.cagr_2y > 100:
                                scan.cycle_peg = True
                                if "cycle_peg" not in scan.flags:
                                    scan.flags.append("cycle_peg")
                        else:
                            scan.negative_growth = True
                            if "negative_growth" not in scan.flags:
                                scan.flags.append("negative_growth")

            # EPS declining flag
            if scan.eps_fy0 and scan.eps_fy1 and scan.eps_fy1 < scan.eps_fy0 * 0.97:
                scan.eps_declining = True
                if "eps_declining" not in scan.flags:
                    scan.flags.append("eps_declining")

            # Low coverage flag
            if scan.analyst_count is not None and scan.analyst_count < 5:
                scan.low_coverage = True
                if "low_coverage" not in scan.flags:
                    scan.flags.append("low_coverage")

        except Exception as e:
            scan.flags.append(f"earnings_estimate_error: {e}")

        # === 3. F21 Earnings Rhythm (earnings_dates) ===
        # NOTE: earnings_dates is SLOW (~5-25s/ticker). Skip with skip_f21=True.
        if not skip_f21:
            try:
                ed = t.earnings_dates
                if ed is not None and not ed.empty:
                    now = datetime.now(timezone.utc)
                    past_rows = []

                    for idx_val in ed.index:
                        try:
                            dt = idx_val.to_pydatetime()
                            if dt.tzinfo is None:
                                dt = dt.replace(tzinfo=timezone.utc)
                            row = ed.loc[idx_val]
                            reported = row.get("Reported EPS")

                            if reported is not None and not (isinstance(reported, float) and math.isnan(reported)):
                                past_rows.append((dt, row))
                            elif dt > now and scan.next_earnings is None:
                                est = row.get("EPS Estimate")
                                if est is not None and not (isinstance(est, float) and math.isnan(est)):
                                    scan.next_earnings = f"{dt.strftime('%Y-%m-%d')} (est ${float(est):.2f})"
                                else:
                                    scan.next_earnings = dt.strftime('%Y-%m-%d')
                        except Exception:
                            continue

                    past_rows.sort(key=lambda x: x[0], reverse=True)
                    quarters = past_rows[:8]

                    if quarters:
                        beats = 0
                        surprises = []
                        for _, row in quarters:
                            surp = row.get("Surprise(%)")
                            if surp is not None and not (isinstance(surp, float) and math.isnan(surp)):
                                s = float(surp)
                                surprises.append(s)
                                if s > 2.0:
                                    beats += 1

                        scan.beat_count = beats
                        scan.total_quarters = len(quarters)
                        scan.beat_rate = f"{beats}/{len(quarters)}"

                        if surprises:
                            scan.avg_surprise = round(sum(surprises) / len(surprises), 1)
                            # Linear regression slope (pp/Q) — matches earnings_rhythm.py
                            # surprises[0]=most recent, reverse for oldest→newest x-axis
                            pts = list(enumerate(reversed(surprises)))
                            if len(pts) >= 3:
                                n = len(pts)
                                x_mean = sum(p[0] for p in pts) / n
                                y_mean = sum(p[1] for p in pts) / n
                                num = sum((x - x_mean) * (y - y_mean) for x, y in pts)
                                den = sum((x - x_mean) ** 2 for x, _ in pts)
                                slope = num / den if den != 0 else 0.0
                                scan.surprise_trend = round(slope, 1)

                        beat_pct = beats / len(quarters) if quarters else 0
                        last_surp = surprises[0] if surprises else None
                        last_beat = last_surp is not None and last_surp > 2.0
                        last_miss = last_surp is not None and last_surp < -2.0

                        if last_miss:
                            scan.f21_class = "Breaking"
                            scan.f21_signal = "EXIT SIGNAL"
                        elif beat_pct >= 0.625:
                            if scan.surprise_trend is not None and scan.surprise_trend >= 0.5:
                                if last_beat:
                                    scan.f21_class = "Expansionary"
                                    scan.f21_signal = "STRONG HOLD/ADD"
                                else:
                                    scan.f21_class = "Steady"
                                    scan.f21_signal = "HOLD"
                            elif scan.surprise_trend is not None and scan.surprise_trend <= -0.5:
                                scan.f21_class = "Decelerating"
                                scan.f21_signal = "WATCH"
                            else:
                                scan.f21_class = "Steady"
                                scan.f21_signal = "HOLD"
                        else:
                            scan.f21_class = "Breaking"
                            scan.f21_signal = "EXIT SIGNAL"

            except Exception as e:
                scan.flags.append(f"f21_error: {e}")

        # === 4. Div yield bug check — SKIPPED ===
        # t.info is 2.86s/ticker (profiled), too expensive for scan.
        # Bug already fixed in yf skill. Run us_data_validator.py separately if needed.

    except Exception as e:
        scan.error = str(e)

    return scan


def compute_delta(current: StockScan, previous: dict) -> dict:
    delta = {}
    prev_peg = previous.get("peg")
    if current.peg is not None and prev_peg is not None and prev_peg > 0:
        peg_change = ((current.peg - prev_peg) / prev_peg) * 100
        if abs(peg_change) > 10:
            delta["peg"] = {"old": prev_peg, "new": current.peg, "change_pct": round(peg_change, 1)}

    prev_f21 = previous.get("f21_class")
    if current.f21_class and prev_f21 and current.f21_class != prev_f21:
        delta["f21"] = {"old": prev_f21, "new": current.f21_class}

    prev_price = previous.get("price")
    if current.price and prev_price and prev_price > 0:
        price_move = ((current.price - prev_price) / prev_price) * 100
        delta["price_move"] = round(price_move, 1)

    prev_tier = previous.get("f9_tier")
    if current.f9_tier and prev_tier and current.f9_tier != prev_tier:
        delta["f9"] = {"old": prev_tier, "new": current.f9_tier}

    return delta


def format_peg(peg, flags):
    if peg is None:
        if "negative_growth" in flags:
            return "N/A(-)"
        if "cycle_peg" in flags:
            return "N/M(cyc)"
        return "—"
    return f"{peg:.2f}"


def render_table(results: list[StockScan], deltas: dict[str, dict], category_name: str):
    cat_map = {"mainline": "Cat 1 主线内", "offnarr_tech": "Cat 2 主线外科技", "non_tech": "Cat 3 科技外"}
    title = cat_map.get(category_name, category_name)

    table = Table(title=title, box=box.SIMPLE_HEAVY, show_lines=False, pad_edge=False)
    table.add_column("Ticker", style="bold", width=6)
    table.add_column("Price", justify="right", width=8)
    table.add_column("Chg%", justify="right", width=6)
    table.add_column("FwdPE", justify="right", width=6)
    table.add_column("CAGR", justify="right", width=6)
    table.add_column("PEG", justify="right", width=7)
    table.add_column("F9", width=3)
    table.add_column("F21", width=10)
    table.add_column("Beat", width=5)
    table.add_column("Δ PEG", width=8)
    table.add_column("Flags", width=12)

    sorted_results = sorted(results, key=lambda r: r.peg if r.peg is not None else 999)

    for r in sorted_results:
        if r.error and not r.price:
            table.add_row(r.ticker, "ERROR", "", "", "", "", "", "", "", "", r.error[:20])
            continue

        price_str = f"${r.price:,.0f}" if r.price and r.price >= 100 else f"${r.price:.2f}" if r.price else "—"
        chg_str = f"{r.change_pct:+.1f}%" if r.change_pct is not None else "—"
        fwd_pe_str = f"{r.fwd_pe:.1f}x" if r.fwd_pe else "—"
        cagr_str = f"{r.cagr_2y:.0f}%" if r.cagr_2y is not None else "—"
        peg_str = format_peg(r.peg, r.flags)

        # Color PEG
        peg_text = Text(peg_str)
        if r.peg is not None:
            if r.peg < 1.0:
                peg_text.stylize("bold green")
            elif r.peg < 1.5:
                peg_text.stylize("yellow")
            elif r.peg < 2.0:
                peg_text.stylize("dark_orange")
            else:
                peg_text.stylize("red")

        f9_str = r.f9_tier or "—"
        f21_str = r.f21_signal or "—"
        beat_str = r.beat_rate or "—"

        # Delta
        d = deltas.get(r.ticker, {})
        delta_parts = []
        if "peg" in d:
            dp = d["peg"]
            arrow = "↑" if dp["change_pct"] > 0 else "↓"
            delta_parts.append(f"{arrow}{abs(dp['change_pct']):.0f}%")
        if "f21" in d:
            delta_parts.append(f"F21:{d['f21']['new'][:3]}")
        delta_str = " ".join(delta_parts) if delta_parts else "—"

        # Flags
        flag_parts = []
        if r.cycle_peg:
            flag_parts.append("⚠cyc")
        if r.eps_declining:
            flag_parts.append("⚠eps↓")
        if r.negative_growth:
            flag_parts.append("⚠neg")
        if r.div_yield_bug:
            flag_parts.append("⚠div")
        if r.low_coverage:
            flag_parts.append("⚠cov")
        if r.in_portfolio:
            flag_parts.append("★port")
        flag_str = " ".join(flag_parts) if flag_parts else "✓"

        table.add_row(
            r.ticker, price_str, chg_str, fwd_pe_str, cagr_str,
            peg_text, f9_str, f21_str, beat_str, delta_str, flag_str
        )

    console.print(table)
    console.print()


def render_delta_summary(deltas: dict[str, dict], results_map: dict[str, StockScan]):
    changes = {t: d for t, d in deltas.items() if d}
    if not changes:
        console.print("[dim]No significant changes since last scan.[/dim]\n")
        return

    table = Table(title="⚡ Changes Since Last Scan", box=box.ROUNDED, show_lines=False)
    table.add_column("Ticker", style="bold", width=6)
    table.add_column("Change", width=40)
    table.add_column("Current", width=20)

    for ticker, d in sorted(changes.items()):
        parts = []
        current_parts = []
        r = results_map.get(ticker)

        if "peg" in d:
            dp = d["peg"]
            direction = "↑ worse" if dp["change_pct"] > 0 else "↓ better"
            parts.append(f"PEG {dp['old']:.2f} → {dp['new']:.2f} ({direction})")
            if r:
                current_parts.append(f"PEG={r.peg:.2f}" if r.peg else "")

        if "f21" in d:
            parts.append(f"F21: {d['f21']['old']} → {d['f21']['new']}")
            if r:
                current_parts.append(f"F21={r.f21_signal}")

        if "price_move" in d and abs(d["price_move"]) > 5:
            parts.append(f"Price moved {d['price_move']:+.1f}% since last scan")

        if "f9" in d:
            parts.append(f"F9: {d['f9']['old']} → {d['f9']['new']}")

        table.add_row(ticker, "\n".join(parts), "\n".join(current_parts))

    console.print(table)
    console.print()


def render_rankings(results: list[StockScan]):
    valid = [r for r in results if r.peg is not None and not r.cycle_peg and not r.negative_growth]
    top_peg = sorted(valid, key=lambda r: r.peg)[:10]

    console.print(Panel.fit(
        "\n".join(
            f"  {i+1}. [bold]{r.ticker:6s}[/bold] PEG={r.peg:.2f}  {r.f9_tier or '—':3s}  {r.f21_signal or '—':15s}  {'★' if r.in_portfolio else ''}"
            for i, r in enumerate(top_peg)
        ),
        title="🏆 PEG Top 10 (excl. Cycle/Negative)",
        border_style="green",
    ))
    console.print()

    # Action priority
    priorities = {"immediate": [], "deep_research": [], "watch": [], "exclude": []}
    for r in results:
        if r.error and not r.price:
            continue
        if r.f9_tier == "T4" or (r.peg and r.peg > 4):
            priorities["exclude"].append(r)
        elif r.in_portfolio and r.peg is not None:
            priorities["immediate"].append(r)
        elif r.f9_tier == "T1":
            priorities["deep_research"].append(r)
        elif r.peg is not None and r.peg < 1.0:
            priorities["deep_research"].append(r)
        elif r.peg is not None and r.peg < 1.5:
            priorities["watch"].append(r)
        else:
            priorities["watch"].append(r)

    lines = []
    for label, emoji, stocks in [
        ("IMMEDIATE (portfolio)", "🔴", priorities["immediate"]),
        ("DEEP RESEARCH", "🟡", priorities["deep_research"]),
    ]:
        if stocks:
            lines.append(f"  {emoji} {label}:")
            for r in sorted(stocks, key=lambda x: x.peg if x.peg else 999):
                lines.append(f"     {r.ticker:6s} PEG={format_peg(r.peg, r.flags):7s} {r.f9_tier or '—':3s} {r.f21_signal or '':15s}")

    if lines:
        console.print(Panel.fit("\n".join(lines), title="📋 Action Priority", border_style="yellow"))
        console.print()


def render_cross_category(results: list[StockScan]):
    """Cross-category summary enforcing anti-echo-chamber principle."""
    CATS = ["mainline", "offnarr_tech", "non_tech"]
    cat_map = {c: [r for r in results if r.category == c] for c in CATS}

    # --- a) Cross-Category PEG Top 10 ---
    valid = [r for r in results if r.peg is not None and not r.cycle_peg and not r.negative_growth]
    top10 = sorted(valid, key=lambda r: r.peg)[:10]
    cat_colors = {"mainline": "cyan", "offnarr_tech": "magenta", "non_tech": "yellow"}
    lines = []
    for i, r in enumerate(top10):
        color = cat_colors.get(r.category, "white")
        cat_label = f"[{color}]{r.category[:4]}[/{color}]"
        port_mark = " ★" if r.in_portfolio else ""
        lines.append(
            f"  {i+1:2d}. [bold]{r.ticker:6s}[/bold] PEG={r.peg:.2f}  {r.f9_tier or '—':3s}  {cat_label}{port_mark}"
        )
    console.print(Panel.fit(
        "\n".join(lines) if lines else "  No valid PEG data",
        title="🌐 Cross-Category PEG Top 10",
        border_style="bright_blue",
    ))
    console.print()

    # --- b) Supply Moat Leaders (F9 T1 across all categories) ---
    t1_stocks = [r for r in results if r.f9_tier == "T1"]
    if t1_stocks:
        moat_lines = []
        for r in sorted(t1_stocks, key=lambda x: x.peg if x.peg else 999):
            color = cat_colors.get(r.category, "white")
            peg_str = f"PEG={r.peg:.2f}" if r.peg else "PEG=N/A"
            moat_str = f"  {r.supply_moat}" if r.supply_moat else ""
            moat_lines.append(
                f"  [bold]{r.ticker:6s}[/bold] [{color}]{r.category[:4]}[/{color}]  {peg_str}{moat_str}"
            )
        console.print(Panel.fit(
            "\n".join(moat_lines),
            title="🏔 Supply Moat Leaders (F9 T1)",
            border_style="green",
        ))
    else:
        console.print("[dim]  No T1 stocks in current scan.[/dim]")
    console.print()

    # --- c) Anti-Echo-Chamber Check ---
    counts = {c: len(cat_map[c]) for c in CATS}
    non_tech_ok = counts["non_tech"] >= counts["mainline"]
    status = "[green]PASS[/green]" if non_tech_ok else "[red]FAIL[/red]"
    console.print(
        f"  Anti-Echo-Chamber: {status}  "
        f"(non_tech={counts['non_tech']} vs mainline={counts['mainline']})"
    )
    if not non_tech_ok:
        console.print("  [yellow]  → Add more non_tech names to ous_universe.json[/yellow]")
    console.print()

    # --- d) Category Balance Summary ---
    port_counts = {c: sum(1 for r in cat_map[c] if r.in_portfolio) for c in CATS}
    for c in CATS:
        console.print(f"  [dim]{c:16s}[/dim]: {counts[c]:2d} stocks  ({port_counts[c]} in portfolio)")
    console.print()


def save_results(results: list[StockScan]):
    output = {
        "meta": {
            "scan_time": datetime.now(timezone.utc).isoformat(),
            "stock_count": len(results),
            "scanner_version": "1.0",
        },
        "results": [asdict(r) for r in results],
    }
    RESULTS_FILE.write_text(json.dumps(output, indent=2, ensure_ascii=False, default=str))

    # Update last_scan in universe file
    try:
        uni_data = json.loads(UNIVERSE_FILE.read_text())
        uni_data["_meta"]["last_scan"] = datetime.now(timezone.utc).isoformat()
        UNIVERSE_FILE.write_text(json.dumps(uni_data, indent=2, ensure_ascii=False))
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(description="US OUS Unified Scanner")
    parser.add_argument("--ticker", "-t", type=str, help="Comma-separated tickers for incremental scan")
    parser.add_argument("--category", "-c", type=str, choices=["mainline", "offnarr_tech", "non_tech"])
    parser.add_argument("--portfolio", "-p", action="store_true", help="Scan portfolio holdings only")
    parser.add_argument("--delta", "-d", action="store_true", help="Show changes since last scan only")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--delay", type=float, default=0.15, help="Delay between tickers (sec, legacy)")
    parser.add_argument("--workers", "-w", type=int, default=5, help="Parallel workers (default 5)")
    parser.add_argument("--no-save", action="store_true", help="Don't save results to file")
    parser.add_argument("--no-cache", action="store_true", help="Ignore fundamentals cache")
    parser.add_argument("--f21", action="store_true", help="Force F21 for ALL stocks (default: portfolio+T1/T2 only)")
    parser.add_argument("--skip-f21", action="store_true", help="Skip F21 for ALL stocks (PEG-only speed mode)")
    args = parser.parse_args()

    # Load universe
    filter_tickers = args.ticker.split(",") if args.ticker else None
    stocks = load_universe(
        filter_tickers=filter_tickers,
        filter_category=args.category,
        portfolio_only=args.portfolio,
    )

    if not stocks:
        console.print("[red]No stocks to scan. Check ous_universe.json.[/red]")
        sys.exit(1)

    # Load previous results for delta
    prev_results = load_previous_results()

    # Load fundamentals cache
    fund_cache = {} if args.no_cache else load_cache()
    cache_hits = 0

    if args.delta and not prev_results:
        console.print("[yellow]No previous scan found. Running full scan instead.[/yellow]")

    # Scan
    scan_start = time.time()
    workers = args.workers
    console.print(f"\n[bold]US OUS Scanner v2.0[/bold] | {len(stocks)} stocks | {workers} workers | {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
    results: list[StockScan] = []
    errors = 0
    cache_hits = 0
    print_lock = Lock()

    def _scan_one(idx_stock: tuple[int, dict]) -> StockScan:
        i, stock = idx_stock
        ticker = stock["ticker"]
        if args.skip_f21:
            do_f21 = False
        elif args.f21:
            do_f21 = True
        else:
            do_f21 = stock.get("in_portfolio", False) or stock.get("f9_tier") in ("T1", "T2")
        scan = fetch_ticker_data(ticker, stock, cache=fund_cache, skip_f21=not do_f21)
        with print_lock:
            tag = "[dim]cache[/dim]" if (fund_cache.get(ticker) and is_cache_fresh(fund_cache.get(ticker, {}))) else ""
            if scan.error:
                console.print(f"  [{i+1}/{len(stocks)}] {ticker}... [red]{scan.error}[/red]")
            else:
                peg_str = f"PEG={scan.peg:.2f}" if scan.peg else "PEG=N/A"
                f21_str = scan.f21_class or "—"
                console.print(f"  [{i+1}/{len(stocks)}] {ticker}... [green]${scan.price:,.2f}[/green] {peg_str} F21:{f21_str} {tag}")
        return scan

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_scan_one, (i, stock)): stock for i, stock in enumerate(stocks)}
        for future in as_completed(futures):
            scan = future.result()
            if scan.error and not scan.price:
                errors += 1
            if scan.price and not scan.error:
                fund_cache[scan.ticker] = {
                    "eps_fy0": scan.eps_fy0, "eps_fy1": scan.eps_fy1,
                    "eps_year_ago": scan.eps_year_ago, "analyst_count": scan.analyst_count,
                    "fwd_pe": scan.fwd_pe, "cagr_2y": scan.cagr_2y, "peg": scan.peg,
                    "beat_rate": scan.beat_rate, "f21_class": scan.f21_class,
                    "f21_signal": scan.f21_signal, "next_earnings": scan.next_earnings,
                    "cached_at": datetime.now(timezone.utc).isoformat(),
                }
            results.append(scan)

    scan_duration = time.time() - scan_start

    # Save fundamentals cache
    if not args.no_save and not args.no_cache:
        save_cache(fund_cache)

    # For incremental scans, merge with previous results
    if filter_tickers and prev_results:
        scanned_tickers = {r.ticker for r in results}
        for ticker, prev in prev_results.items():
            if ticker not in scanned_tickers:
                # Keep previous result
                old_scan = StockScan(**{k: v for k, v in prev.items() if k in StockScan.__dataclass_fields__})
                results.append(old_scan)

    # Compute deltas
    deltas = {}
    for r in results:
        if r.ticker in prev_results:
            deltas[r.ticker] = compute_delta(r, prev_results[r.ticker])

    # Output
    if args.json:
        output = {"results": [asdict(r) for r in results], "deltas": deltas}
        print(json.dumps(output, indent=2, ensure_ascii=False, default=str))
    else:
        # Group by category
        for cat in ["mainline", "offnarr_tech", "non_tech"]:
            cat_results = [r for r in results if r.category == cat]
            if cat_results:
                render_table(cat_results, deltas, cat)

        # Delta summary
        if prev_results:
            render_delta_summary(deltas, {r.ticker: r for r in results})

        # Rankings
        render_rankings(results)

        # Cross-category summary (anti-echo-chamber)
        render_cross_category(results)

        # Summary
        console.print(f"[dim]Scanned {len(results)} stocks ({errors} errors) in {scan_duration:.0f}s | Saved to {RESULTS_FILE.name}[/dim]")

    # Save
    if not args.no_save:
        save_results(results)


if __name__ == "__main__":
    main()

# /// script
# requires-python = ">=3.11"
# dependencies = ["yfinance>=0.2.40", "rich>=13.0"]
# ///
"""
US Stock Data Quality Validator — yfinance bug & anomaly detection

Checks for known yfinance data issues: stale prices, bad PE ratios,
missing earnings estimates, cycle distortions, and negative EPS growth.

Usage:
  uv run --script scripts/us_data_validator.py              # all US positions
  uv run --script scripts/us_data_validator.py NVDA AAPL MA # specific tickers
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import yfinance as yf
from rich.console import Console
from rich.table import Table
from rich import box
from rich.text import Text

# ─── Paths ────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
PORTFOLIO_PATH = REPO_ROOT / "portfolio_state.json"

console = Console()

# ─── Thresholds ───────────────────────────────────────────────────────────────
DIV_YIELD_MAX = 0.10          # > 10% → likely data bug
FORWARD_PE_MIN = 0            # < 0 → bug
FORWARD_PE_MAX = 200          # > 200 → suspect
FORWARD_PE_DELTA_MAX = 0.20   # > 20% discrepancy between info vs computed
MIN_ANALYSTS = 3              # fewer than this → sparse coverage warning
CYCLE_CAGR_THRESHOLD = 1.00   # > 100% 2Y CAGR → likely cycle distortion
PRICE_STALE_HOURS = 6         # flag if last fetch is older than this during market hours


# ─── Market hours helper ──────────────────────────────────────────────────────
def is_us_market_open() -> bool:
    """Rough check: NYSE is open Mon–Fri 09:30–16:00 ET."""
    et = timezone(timedelta(hours=-4))  # EDT (approx; ignores EST)
    now = datetime.now(et)
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
    return market_open <= now <= market_close


# ─── Result types ─────────────────────────────────────────────────────────────
@dataclass
class CheckResult:
    check: str
    status: str   # PASS | WARN | CRITICAL | SKIP
    detail: str


@dataclass
class TickerReport:
    ticker: str
    checks: list[CheckResult] = field(default_factory=list)
    error: Optional[str] = None

    def add(self, check: str, status: str, detail: str) -> None:
        self.checks.append(CheckResult(check, status, detail))


# ─── Core validation logic ────────────────────────────────────────────────────
def validate_ticker(ticker: str) -> TickerReport:
    report = TickerReport(ticker=ticker)

    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
    except Exception as e:
        report.error = f"yfinance error: {e}"
        return report

    price: Optional[float] = (
        info.get("currentPrice")
        or info.get("regularMarketPrice")
        or info.get("previousClose")
    )

    # ── 1. Dividend Yield Sanity ──────────────────────────────────────────────
    div_yield = info.get("dividendYield")
    if div_yield is None:
        report.add("Div Yield", "SKIP", "dividendYield not in info")
    elif div_yield > DIV_YIELD_MAX:
        report.add(
            "Div Yield",
            "CRITICAL",
            f"{div_yield:.1%} — LIKELY BUG, verify manually (threshold: {DIV_YIELD_MAX:.0%})",
        )
    else:
        report.add("Div Yield", "PASS", f"{div_yield:.2%}")

    # ── 2. Forward PE Sanity ──────────────────────────────────────────────────
    fpe_info: Optional[float] = info.get("forwardPE")
    if fpe_info is None:
        report.add("Forward PE (info)", "WARN", "forwardPE missing from info")
    elif fpe_info < FORWARD_PE_MIN:
        report.add(
            "Forward PE (info)",
            "CRITICAL",
            f"{fpe_info:.1f} — NEGATIVE PE, check for negative EPS estimate",
        )
    elif fpe_info > FORWARD_PE_MAX:
        report.add(
            "Forward PE (info)",
            "WARN",
            f"{fpe_info:.1f} — exceeds {FORWARD_PE_MAX}x, verify if meaningful",
        )
    else:
        report.add("Forward PE (info)", "PASS", f"{fpe_info:.1f}x")

    # ── 3. Forward PE Consistency: info vs earnings_estimate ─────────────────
    try:
        ee = t.earnings_estimate  # DataFrame indexed by period
    except Exception:
        ee = None

    computed_fpe: Optional[float] = None
    eps_0y: Optional[float] = None
    eps_1y: Optional[float] = None
    analysts_1y: Optional[int] = None
    analysts_0y: Optional[int] = None

    if ee is not None and not ee.empty:
        try:
            # yfinance earnings_estimate rows: '0y' = current FY, '+1y' = next FY
            if "+1y" in ee.index:
                row_1y = ee.loc["+1y"]
                eps_1y_val = row_1y.get("avg") if hasattr(row_1y, "get") else None
                if eps_1y_val is None and hasattr(row_1y, "__getitem__"):
                    try:
                        eps_1y_val = float(row_1y["avg"])
                    except Exception:
                        eps_1y_val = None
                eps_1y = eps_1y_val
                try:
                    analysts_1y = int(row_1y.get("numberOfAnalysts", 0) or 0)
                except Exception:
                    analysts_1y = None

            if "0y" in ee.index:
                row_0y = ee.loc["0y"]
                try:
                    eps_0y_val = row_0y.get("avg") if hasattr(row_0y, "get") else None
                    eps_0y = float(eps_0y_val) if eps_0y_val is not None else None
                    analysts_0y = int(row_0y.get("numberOfAnalysts", 0) or 0)
                except Exception:
                    pass
        except Exception:
            pass

    if price and eps_1y and eps_1y > 0:
        computed_fpe = price / eps_1y
        if fpe_info and fpe_info > 0:
            delta = abs(computed_fpe - fpe_info) / fpe_info
            if delta > FORWARD_PE_DELTA_MAX:
                report.add(
                    "PE Consistency",
                    "WARN",
                    f"info={fpe_info:.1f}x vs computed={computed_fpe:.1f}x (delta={delta:.0%} > {FORWARD_PE_DELTA_MAX:.0%})",
                )
            else:
                report.add(
                    "PE Consistency",
                    "PASS",
                    f"info={fpe_info:.1f}x vs computed={computed_fpe:.1f}x (delta={delta:.0%})",
                )
        else:
            report.add(
                "PE Consistency",
                "SKIP",
                f"computed={computed_fpe:.1f}x (info PE unavailable for comparison)",
            )
    elif eps_1y is not None and eps_1y <= 0:
        report.add(
            "PE Consistency",
            "WARN",
            f"+1y EPS estimate is non-positive ({eps_1y}), PE not meaningful",
        )
    elif ee is None or (hasattr(ee, "empty") and ee.empty):
        report.add("PE Consistency", "SKIP", "earnings_estimate unavailable")
    else:
        report.add(
            "PE Consistency",
            "SKIP",
            f"+1y EPS not found in estimate (price={price}, eps_1y={eps_1y})",
        )

    # ── 4. Price Freshness ────────────────────────────────────────────────────
    market_open = is_us_market_open()
    # yfinance doesn't return a timestamp per se; use regularMarketTime if present
    reg_time = info.get("regularMarketTime")
    if reg_time is None:
        if market_open:
            report.add("Price Freshness", "WARN", "regularMarketTime missing; market is OPEN — price may be stale")
        else:
            report.add("Price Freshness", "SKIP", "regularMarketTime missing; market is CLOSED")
    else:
        try:
            # regularMarketTime is a Unix timestamp
            ts = datetime.fromtimestamp(int(reg_time), tz=timezone.utc)
            age_hours = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
            if market_open and age_hours > PRICE_STALE_HOURS:
                report.add(
                    "Price Freshness",
                    "CRITICAL",
                    f"Last price {age_hours:.1f}h ago — STALE while market is OPEN",
                )
            else:
                status = "WARN" if market_open and age_hours > 1 else "PASS"
                report.add(
                    "Price Freshness",
                    status,
                    f"Last price {age_hours:.1f}h ago ({'market OPEN' if market_open else 'market CLOSED'})",
                )
        except Exception as e:
            report.add("Price Freshness", "SKIP", f"Could not parse regularMarketTime: {e}")

    # ── 5. Missing / Sparse Earnings Data ────────────────────────────────────
    if ee is None or (hasattr(ee, "empty") and ee.empty):
        report.add("Earnings Coverage", "CRITICAL", "earnings_estimate returned None/empty")
    elif analysts_1y is None:
        report.add("Earnings Coverage", "WARN", "+1y row missing — can't check analyst count")
    elif analysts_1y < MIN_ANALYSTS:
        report.add(
            "Earnings Coverage",
            "WARN",
            f"Only {analysts_1y} analyst(s) for +1y estimate (threshold: {MIN_ANALYSTS})",
        )
    else:
        report.add("Earnings Coverage", "PASS", f"{analysts_1y} analysts covering +1y EPS")

    # ── 6. Cycle PEG Warning: 2Y EPS CAGR > 100% ─────────────────────────────
    # 2Y CAGR uses yearAgoEps (FY-1 actual) as base → (eps_1y / yearAgoEps)^0.5 - 1
    year_ago_eps: Optional[float] = None
    try:
        if ee is not None and "0y" in ee.index:
            row_0y = ee.loc["0y"]
            yae = row_0y.get("yearAgoEps") if hasattr(row_0y, "get") else None
            if yae is not None:
                year_ago_eps = float(yae)
    except Exception:
        pass

    if eps_1y is not None and year_ago_eps is not None and year_ago_eps > 0 and eps_1y > 0:
        cagr_2y = (eps_1y / year_ago_eps) ** 0.5 - 1
        if cagr_2y > CYCLE_CAGR_THRESHOLD:
            report.add(
                "Cycle PEG",
                "WARN",
                f"2Y EPS CAGR = {cagr_2y:.0%} — CYCLE DISTORTION, PEG may be misleadingly low",
            )
        else:
            report.add("Cycle PEG", "PASS", f"2Y EPS CAGR = {cagr_2y:.0%} (no distortion signal)")
    elif year_ago_eps is not None and year_ago_eps <= 0:
        report.add(
            "Cycle PEG",
            "WARN",
            f"yearAgoEps = {year_ago_eps} (non-positive base — CAGR undefined, likely trough year)",
        )
    elif eps_1y is not None and year_ago_eps is None:
        report.add("Cycle PEG", "SKIP", "yearAgoEps not available, can't compute 2Y CAGR")
    else:
        report.add("Cycle PEG", "SKIP", "Insufficient EPS data for CAGR check")

    # ── 7. Negative EPS Growth (YoY) ──────────────────────────────────────────
    # Compare eps_1y (+1y estimate avg) vs eps_0y (current FY estimate avg)
    if eps_0y is not None and eps_1y is not None:
        if eps_0y > 0 and eps_1y < eps_0y:
            yoy_change = (eps_1y - eps_0y) / abs(eps_0y)
            report.add(
                "EPS Growth",
                "WARN",
                f"+1y EPS ({eps_1y:.2f}) < 0y EPS ({eps_0y:.2f}) — YoY decline {yoy_change:.1%}",
            )
        elif eps_0y <= 0:
            report.add(
                "EPS Growth",
                "WARN",
                f"0y EPS estimate non-positive ({eps_0y:.2f}) — growth metric unreliable",
            )
        else:
            yoy_change = (eps_1y - eps_0y) / abs(eps_0y)
            report.add("EPS Growth", "PASS", f"YoY EPS growth: {yoy_change:+.1%} ({eps_0y:.2f} → {eps_1y:.2f})")
    elif eps_1y is None or eps_0y is None:
        report.add("EPS Growth", "SKIP", f"0y EPS={eps_0y}, +1y EPS={eps_1y} — insufficient data")

    return report


# ─── Portfolio loader ──────────────────────────────────────────────────────────
def load_portfolio_tickers() -> list[str]:
    if not PORTFOLIO_PATH.exists():
        console.print(f"[red]portfolio_state.json not found at {PORTFOLIO_PATH}[/red]")
        return []
    with open(PORTFOLIO_PATH) as f:
        state = json.load(f)
    us = state.get("accounts", {}).get("us", {})
    positions = us.get("positions", [])
    shorts = us.get("short_positions", [])
    tickers = [p["ticker"] for p in positions if "ticker" in p]
    tickers += [p["ticker"] for p in shorts if "ticker" in p]
    return tickers


# ─── Rich output ──────────────────────────────────────────────────────────────
STATUS_COLORS = {
    "PASS": "green",
    "WARN": "yellow",
    "CRITICAL": "red bold",
    "SKIP": "dim",
}

STATUS_ICONS = {
    "PASS": "✓",
    "WARN": "⚠",
    "CRITICAL": "✗",
    "SKIP": "–",
}


def render_reports(reports: list[TickerReport]) -> None:
    table = Table(
        title="US Data Quality Validation",
        box=box.SIMPLE_HEAVY,
        show_lines=False,
        header_style="bold cyan",
        expand=True,
    )
    table.add_column("Ticker", style="bold magenta", min_width=6, no_wrap=True)
    table.add_column("Check", min_width=20, no_wrap=True)
    table.add_column("Status", min_width=12, justify="center", no_wrap=True)
    table.add_column("Detail", ratio=1)

    passed = warned = critical = skipped = 0

    for report in reports:
        if report.error:
            table.add_row(
                report.ticker,
                "FETCH ERROR",
                Text("CRITICAL", style="red bold"),
                report.error,
            )
            critical += 1
            continue

        for idx, check in enumerate(report.checks):
            color = STATUS_COLORS.get(check.status, "white")
            icon = STATUS_ICONS.get(check.status, "?")
            status_text = Text(f"{icon} {check.status}", style=color)

            table.add_row(
                Text(report.ticker, style="bold magenta") if idx == 0 else "",
                check.check,
                status_text,
                check.detail,
                end_section=(idx == len(report.checks) - 1),
            )

            if check.status == "PASS":
                passed += 1
            elif check.status == "WARN":
                warned += 1
            elif check.status == "CRITICAL":
                critical += 1
            elif check.status == "SKIP":
                skipped += 1

    console.print(table)

    # Summary line
    total = passed + warned + critical
    summary_parts = []
    if passed:
        summary_parts.append(f"[green]{passed} passed[/green]")
    if warned:
        summary_parts.append(f"[yellow]{warned} warnings[/yellow]")
    if critical:
        summary_parts.append(f"[red bold]{critical} critical[/red bold]")
    if skipped:
        summary_parts.append(f"[dim]{skipped} skipped[/dim]")

    console.print(
        f"\nSummary ({total} checks, {len(reports)} tickers): "
        + " | ".join(summary_parts)
    )

    if critical > 0:
        console.print(
            "[red bold]ACTION REQUIRED:[/red bold] "
            "CRITICAL flags indicate data bugs or missing data. "
            "Verify manually before using in calculations."
        )


# ─── Main ─────────────────────────────────────────────────────────────────────
def main() -> None:
    args = sys.argv[1:]

    if args:
        tickers = [t.upper() for t in args]
        console.print(f"[cyan]Validating {len(tickers)} ticker(s): {', '.join(tickers)}[/cyan]\n")
    else:
        tickers = load_portfolio_tickers()
        if not tickers:
            console.print("[yellow]No US positions found in portfolio_state.json.[/yellow]")
            sys.exit(0)
        console.print(
            f"[cyan]Scanning {len(tickers)} US portfolio positions: {', '.join(tickers)}[/cyan]\n"
        )

    reports: list[TickerReport] = []
    for i, ticker in enumerate(tickers):
        console.print(f"  [{i+1}/{len(tickers)}] Fetching {ticker}...", end="\r")
        report = validate_ticker(ticker)
        reports.append(report)
        if i < len(tickers) - 1:
            time.sleep(0.3)  # be polite to yfinance

    console.print(" " * 60, end="\r")  # clear progress line
    render_reports(reports)


if __name__ == "__main__":
    main()

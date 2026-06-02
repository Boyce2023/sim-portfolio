# /// script
# requires-python = ">=3.10"
# dependencies = ["yfinance>=0.2.40", "rich>=13.0", "lxml>=4.9"]
# ///
"""
F21 Earnings Rhythm Tracker
============================
Implements the F21 framework — tracking earnings beat frequency and quality
to assess trend persistence for US equity positions.

F21 Classifications (per framework definition):
  Expansionary  — Beat + surprise magnitude increasing → STRONG HOLD/ADD
  Steady        — Beat + stable surprise               → HOLD
  Decelerating  — Beat but declining surprise          → WATCH for exit
  Breaking      — Miss or guidance cut                 → EXIT SIGNAL

Usage:
  uv run --script scripts/earnings_rhythm.py NVDA AVGO DELL
  uv run --script scripts/earnings_rhythm.py --portfolio
  uv run --script scripts/earnings_rhythm.py NVDA --json
  uv run --script scripts/earnings_rhythm.py --portfolio --quarters 12
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

import yfinance as yf
from rich.console import Console
from rich.table import Table
from rich import box
from rich.text import Text
from rich.rule import Rule
from rich.panel import Panel

# ─── Constants ────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
PORTFOLIO_PATH = REPO_ROOT / "portfolio_state.json"

DEFAULT_QUARTERS = 8        # rolling window for F21 analysis
BEAT_THRESHOLD_PCT = 2.0    # >2% surprise = Beat (standard sell-side convention)
MISS_THRESHOLD_PCT = -2.0   # <-2% surprise = Miss
TREND_MIN_QUARTERS = 3      # minimum quarters for trend slope calculation

# Surprise magnitude thresholds for Expansionary vs Decelerating classification
EXPANDING_SLOPE_THRESHOLD = 0.5    # avg surprise increasing ≥0.5pp/quarter
DECELERATING_SLOPE_THRESHOLD = -0.5  # avg surprise declining ≥0.5pp/quarter

# ─── Data types ───────────────────────────────────────────────────────────────

class QuarterData(NamedTuple):
    date: str               # "YYYY-MM-DD"
    eps_estimate: float | None
    eps_actual: float | None
    surprise_pct: float | None  # yfinance Surprise(%) column — already in pct
    verdict: str            # "Beat" | "Miss" | "In-line" | "No Data"


class RhythmResult(NamedTuple):
    ticker: str
    name: str
    # Summary metrics
    beat_rate: float | None         # e.g. 0.875 = 87.5%
    beat_count: int
    scored_quarters: int
    beat_streak: int                # consecutive beats from most recent
    avg_surprise: float | None      # avg surprise % over last N quarters with data
    surprise_trend: str             # "Increasing" | "Decreasing" | "Stable" | "Insufficient"
    surprise_slope: float | None    # pp change per quarter (positive = growing beats)
    # F21 classification
    f21_class: str                  # "Expansionary" | "Steady" | "Decelerating" | "Breaking" | "N/A"
    f21_signal: str                 # "STRONG HOLD/ADD" | "HOLD" | "WATCH" | "EXIT SIGNAL" | "N/A"
    # Next earnings
    next_earnings: str | None       # "YYYY-MM-DD" or None
    next_eps_estimate: float | None
    # Raw data
    quarters: list[QuarterData]     # newest first, last N quarters
    data_available: bool


# ─── Portfolio loader ──────────────────────────────────────────────────────────

def load_us_tickers() -> list[tuple[str, str]]:
    """Read US long positions from portfolio_state.json. Returns [(ticker, name)]."""
    if not PORTFOLIO_PATH.exists():
        print(f"[ERROR] portfolio_state.json not found: {PORTFOLIO_PATH}", file=sys.stderr)
        sys.exit(1)

    with open(PORTFOLIO_PATH) as f:
        state = json.load(f)

    positions = state.get("accounts", {}).get("us", {}).get("positions", [])
    result = []
    for pos in positions:
        ticker = pos.get("ticker", "").strip().upper()
        name = pos.get("name", ticker)
        if ticker:
            result.append((ticker, name))
    return result


# ─── yfinance helpers ─────────────────────────────────────────────────────────

def _safe_float(val) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _verdict(surprise_pct: float | None) -> str:
    if surprise_pct is None:
        return "No Data"
    if surprise_pct > BEAT_THRESHOLD_PCT:
        return "Beat"
    elif surprise_pct < MISS_THRESHOLD_PCT:
        return "Miss"
    else:
        return "In-line"


def fetch_earnings(ticker: str, n_quarters: int) -> tuple[list[QuarterData], str | None, float | None]:
    """
    Fetch earnings history from yfinance earnings_dates.

    Returns:
        (past_quarters_newest_first, next_earnings_date, next_eps_estimate)
        past_quarters limited to n_quarters most recent with actual data.
    """
    t = yf.Ticker(ticker)

    try:
        ed = t.earnings_dates
    except Exception as e:
        return [], None, None

    if ed is None or ed.empty:
        return [], None, None

    # Sort newest first
    ed = ed.sort_index(ascending=False)

    now = datetime.now(timezone.utc)
    past: list[QuarterData] = []
    next_date: str | None = None
    next_est: float | None = None

    for idx, row in ed.iterrows():
        ts = idx.to_pydatetime()
        eps_est = _safe_float(row.get("EPS Estimate"))
        eps_act = _safe_float(row.get("Reported EPS"))
        surp = _safe_float(row.get("Surprise(%)"))

        if ts > now:
            # Future row — capture next earnings date
            if next_date is None:
                next_date = ts.strftime("%Y-%m-%d")
                next_est = eps_est
            continue

        # Past row — only include if we have actual EPS
        if eps_act is None:
            continue

        # Compute surprise if missing but we have both actuals
        if surp is None and eps_est is not None and eps_est != 0:
            surp = (eps_act - eps_est) / abs(eps_est) * 100

        past.append(QuarterData(
            date=ts.strftime("%Y-%m-%d"),
            eps_estimate=eps_est,
            eps_actual=eps_act,
            surprise_pct=surp,
            verdict=_verdict(surp),
        ))

        if len(past) >= n_quarters:
            break

    return past, next_date, next_est


# ─── Trend analysis ───────────────────────────────────────────────────────────

def _surprise_slope(quarters: list[QuarterData]) -> float | None:
    """
    Compute linear slope of surprise % over time (oldest → newest).
    Returns pp change per quarter. Positive = beats getting bigger.
    Requires at least TREND_MIN_QUARTERS data points with surprise.
    """
    pts = [(i, q.surprise_pct) for i, q in enumerate(reversed(quarters))
           if q.surprise_pct is not None]

    if len(pts) < TREND_MIN_QUARTERS:
        return None

    n = len(pts)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    x_mean = sum(xs) / n
    y_mean = sum(ys) / n

    num = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    den = sum((x - x_mean) ** 2 for x in xs)

    if den == 0:
        return 0.0
    return num / den


def _trend_label(slope: float | None) -> str:
    if slope is None:
        return "Insufficient"
    if slope >= EXPANDING_SLOPE_THRESHOLD:
        return "Increasing"
    elif slope <= DECELERATING_SLOPE_THRESHOLD:
        return "Decreasing"
    else:
        return "Stable"


# ─── F21 classification ───────────────────────────────────────────────────────

def _classify_f21(
    beat_rate: float | None,
    beat_streak: int,
    last_verdict: str,
    surprise_trend: str,
    avg_surprise: float | None,
) -> tuple[str, str]:
    """
    Classify per F21 framework.

    Returns (f21_class, f21_signal).

    Framework rules:
      Expansionary  — last quarter Beat + surprise magnitude Increasing
                      → STRONG HOLD/ADD
      Steady        — last quarter Beat + surprise magnitude Stable
                      (or Increasing but beat rate < 75%)
                      → HOLD
      Decelerating  — last quarter Beat + surprise magnitude Decreasing
                      → WATCH for exit
      Breaking      — last quarter Miss (or Insufficient data + miss streak)
                      → EXIT SIGNAL
      N/A           — no usable data
    """
    if beat_rate is None or last_verdict == "No Data":
        return "N/A", "N/A"

    if last_verdict == "Miss":
        return "Breaking", "EXIT SIGNAL"

    if last_verdict == "In-line":
        # In-line is a yellow flag — treat as Decelerating if trend is down
        if surprise_trend == "Decreasing":
            return "Decelerating", "WATCH"
        else:
            return "Steady", "HOLD"

    # last_verdict == "Beat"
    if surprise_trend == "Increasing":
        # Strong expansionary only if beat rate also solid
        if beat_rate >= 0.625:  # ≥5/8 beats
            return "Expansionary", "STRONG HOLD/ADD"
        else:
            return "Steady", "HOLD"
    elif surprise_trend == "Decreasing":
        return "Decelerating", "WATCH"
    elif surprise_trend == "Stable":
        return "Steady", "HOLD"
    else:
        # Insufficient trend data — use beat rate as fallback
        if beat_rate >= 0.75:
            return "Steady", "HOLD"
        elif beat_rate >= 0.5:
            return "Steady", "HOLD"
        else:
            return "Decelerating", "WATCH"


# ─── Core analysis ─────────────────────────────────────────────────────────────

def analyze(ticker: str, name: str, n_quarters: int) -> RhythmResult:
    quarters, next_date, next_est = fetch_earnings(ticker, n_quarters)

    if not quarters:
        return RhythmResult(
            ticker=ticker, name=name,
            beat_rate=None, beat_count=0, scored_quarters=0,
            beat_streak=0, avg_surprise=None,
            surprise_trend="Insufficient", surprise_slope=None,
            f21_class="N/A", f21_signal="N/A",
            next_earnings=next_date, next_eps_estimate=next_est,
            quarters=[], data_available=False,
        )

    # Beat stats
    scored = [q for q in quarters if q.verdict in ("Beat", "Miss", "In-line")]
    beat_count = sum(1 for q in scored if q.verdict == "Beat")
    total = len(scored)
    beat_rate = beat_count / total if total > 0 else None

    # Beat streak (consecutive from most recent)
    streak = 0
    for q in quarters:  # already newest first
        if q.verdict == "Beat":
            streak += 1
        else:
            break

    # Surprise stats
    surp_vals = [q.surprise_pct for q in quarters if q.surprise_pct is not None]
    avg_surp = sum(surp_vals) / len(surp_vals) if surp_vals else None

    slope = _surprise_slope(quarters)
    trend = _trend_label(slope)

    last_verdict = quarters[0].verdict if quarters else "No Data"

    f21_class, f21_signal = _classify_f21(beat_rate, streak, last_verdict, trend, avg_surp)

    return RhythmResult(
        ticker=ticker, name=name,
        beat_rate=beat_rate, beat_count=beat_count, scored_quarters=total,
        beat_streak=streak, avg_surprise=avg_surp,
        surprise_trend=trend, surprise_slope=slope,
        f21_class=f21_class, f21_signal=f21_signal,
        next_earnings=next_date, next_eps_estimate=next_est,
        quarters=quarters, data_available=True,
    )


# ─── Rich output ──────────────────────────────────────────────────────────────

def _signal_style(signal: str) -> str:
    return {
        "STRONG HOLD/ADD": "bold green",
        "HOLD":            "green",
        "WATCH":           "yellow",
        "EXIT SIGNAL":     "bold red",
        "N/A":             "dim",
    }.get(signal, "white")


def _class_style(cls: str) -> str:
    return {
        "Expansionary": "bold green",
        "Steady":       "cyan",
        "Decelerating": "yellow",
        "Breaking":     "bold red",
        "N/A":          "dim",
    }.get(cls, "white")


def _verdict_style(verdict: str) -> str:
    return {
        "Beat":    "green",
        "Miss":    "red",
        "In-line": "yellow",
        "No Data": "dim",
    }.get(verdict, "white")


def _trend_style(trend: str) -> str:
    return {
        "Increasing":   "bold green",
        "Stable":       "cyan",
        "Decreasing":   "yellow",
        "Insufficient": "dim",
    }.get(trend, "white")


def render_summary_table(results: list[RhythmResult], console: Console) -> None:
    table = Table(
        title="F21 Earnings Rhythm Tracker",
        box=box.SIMPLE_HEAVY,
        show_header=True,
        header_style="bold white",
        title_style="bold white",
        min_width=110,
    )

    table.add_column("Ticker",       style="bold cyan",  width=8,  no_wrap=True)
    table.add_column("Name",                             width=22, no_wrap=True)
    table.add_column("Beat Rate",    justify="center",   width=12)
    table.add_column("Streak",       justify="center",   width=8)
    table.add_column("Avg Surprise", justify="center",   width=14)
    table.add_column("Trend",        justify="center",   width=13)
    table.add_column("F21 Class",    justify="center",   width=14)
    table.add_column("F21 Signal",   justify="center",   width=16)
    table.add_column("Next Earnings",justify="center",   width=14)

    for r in results:
        if r.beat_rate is not None:
            beat_str = f"{r.beat_count}/{r.scored_quarters} ({r.beat_rate*100:.0f}%)"
        else:
            beat_str = "N/A"

        streak_str = f"{r.beat_streak}Q" if r.beat_streak > 0 else "-"

        if r.avg_surprise is not None:
            avg_str = f"{r.avg_surprise:+.1f}%"
        else:
            avg_str = "N/A"

        if r.surprise_slope is not None:
            slope_tag = f" ({r.surprise_slope:+.1f}pp/Q)"
        else:
            slope_tag = ""
        trend_str = r.surprise_trend + slope_tag

        next_str = r.next_earnings or "Unknown"
        if r.next_eps_estimate is not None:
            next_str += f"\n[dim]est ${r.next_eps_estimate:.2f}[/dim]"

        table.add_row(
            r.ticker,
            r.name[:22],
            beat_str,
            streak_str,
            avg_str,
            Text(r.surprise_trend + (f" {r.surprise_slope:+.1f}pp/Q" if r.surprise_slope is not None else ""),
                 style=_trend_style(r.surprise_trend)),
            Text(r.f21_class, style=_class_style(r.f21_class)),
            Text(r.f21_signal, style=_signal_style(r.f21_signal)),
            r.next_earnings or "[dim]Unknown[/dim]",
        )

    console.print(table)


def render_detail_tables(results: list[RhythmResult], console: Console) -> None:
    console.print(Rule("[bold white]Per-Quarter Breakdown[/bold white]"))
    console.print()

    for r in results:
        if not r.data_available or not r.quarters:
            console.print(f"  [bold cyan]{r.ticker}[/bold cyan] — no earnings data available\n")
            continue

        detail = Table(
            title=f"{r.ticker} — {r.name}  |  F21: [{_signal_style(r.f21_signal)}]{r.f21_signal}[/]",
            box=box.SIMPLE,
            show_header=True,
            header_style="bold white",
            title_style="bold cyan",
            min_width=80,
        )
        detail.add_column("Date",            width=12)
        detail.add_column("EPS Estimate",    justify="right", width=13)
        detail.add_column("EPS Actual",      justify="right", width=13)
        detail.add_column("Surprise",        justify="right", width=10)
        detail.add_column("Verdict",         justify="center", width=10)
        detail.add_column("Note",            width=30)

        # Display newest first (already sorted)
        for i, q in enumerate(r.quarters):
            est_str = f"${q.eps_estimate:.3f}" if q.eps_estimate is not None else "N/A"
            act_str = f"${q.eps_actual:.3f}" if q.eps_actual is not None else "N/A"
            surp_str = f"{q.surprise_pct:+.2f}%" if q.surprise_pct is not None else "N/A"

            # Compute trend arrow for surprise vs previous quarter
            note = ""
            if i < len(r.quarters) - 1 and q.surprise_pct is not None and r.quarters[i + 1].surprise_pct is not None:
                delta = q.surprise_pct - r.quarters[i + 1].surprise_pct
                if delta > 0.5:
                    note = f"surp +{delta:.1f}pp vs prev [green]↑[/green]"
                elif delta < -0.5:
                    note = f"surp {delta:.1f}pp vs prev [red]↓[/red]"
                else:
                    note = f"surp {delta:+.1f}pp vs prev [cyan]→[/cyan]"

            if i == 0:
                note = "[bold]← latest[/bold]" + (f"  {note}" if note else "")

            detail.add_row(
                q.date,
                est_str,
                act_str,
                Text(surp_str, style="green" if (q.surprise_pct or 0) > 0 else "red"),
                Text(q.verdict, style=_verdict_style(q.verdict)),
                note,
            )

        console.print(detail)

        # Summary stats for this ticker
        if r.avg_surprise is not None:
            console.print(
                f"  Beat rate [bold]{r.beat_count}/{r.scored_quarters}[/bold] "
                f"({r.beat_rate*100:.0f}%)  |  "
                f"Avg surprise [bold]{r.avg_surprise:+.1f}%[/bold]  |  "
                f"Trend [bold {_trend_style(r.surprise_trend)}]{r.surprise_trend}[/bold {_trend_style(r.surprise_trend)}]"
                + (f" ({r.surprise_slope:+.1f}pp/Q)" if r.surprise_slope is not None else "")
                + f"  |  Streak [bold]{r.beat_streak}Q[/bold]"
            )

        if r.next_earnings:
            est_tag = f" (est ${r.next_eps_estimate:.2f})" if r.next_eps_estimate else ""
            console.print(f"  Next earnings: [bold cyan]{r.next_earnings}[/bold cyan]{est_tag}")
        console.print()


def render_legend(console: Console) -> None:
    console.print(Rule())
    legend = (
        "[bold white]F21 Framework — Earnings Rhythm Classification[/bold white]\n\n"
        "[bold green]Expansionary[/bold green]   Beat + surprise magnitude Increasing → [bold green]STRONG HOLD/ADD[/bold green]\n"
        "[cyan]Steady[/cyan]          Beat + surprise magnitude Stable    → [green]HOLD[/green]\n"
        "[yellow]Decelerating[/yellow]   Beat + surprise magnitude Decreasing → [yellow]WATCH for exit[/yellow]\n"
        "[bold red]Breaking[/bold red]       Miss (or In-line + declining trend)  → [bold red]EXIT SIGNAL[/bold red]\n\n"
        "[dim]Surprise trend slope: >+0.5pp/Q = Increasing | <-0.5pp/Q = Decreasing | else Stable[/dim]\n"
        "[dim]Beat threshold: >+2% surprise = Beat | <-2% = Miss | else In-line[/dim]"
    )
    console.print(Panel(legend, expand=False))


# ─── JSON output ──────────────────────────────────────────────────────────────

def to_json(results: list[RhythmResult]) -> dict:
    out = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "framework": "F21 Earnings Rhythm",
        "tickers": [],
    }
    for r in results:
        out["tickers"].append({
            "ticker": r.ticker,
            "name": r.name,
            "beat_rate": round(r.beat_rate, 4) if r.beat_rate is not None else None,
            "beat_count": r.beat_count,
            "scored_quarters": r.scored_quarters,
            "beat_streak": r.beat_streak,
            "avg_surprise_pct": round(r.avg_surprise, 2) if r.avg_surprise is not None else None,
            "surprise_trend": r.surprise_trend,
            "surprise_slope_pp_per_quarter": round(r.surprise_slope, 2) if r.surprise_slope is not None else None,
            "f21_class": r.f21_class,
            "f21_signal": r.f21_signal,
            "next_earnings": r.next_earnings,
            "next_eps_estimate": r.next_eps_estimate,
            "data_available": r.data_available,
            "quarters": [
                {
                    "date": q.date,
                    "eps_estimate": q.eps_estimate,
                    "eps_actual": q.eps_actual,
                    "surprise_pct": q.surprise_pct,
                    "verdict": q.verdict,
                }
                for q in r.quarters
            ],
        })
    return out


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="F21 Earnings Rhythm Tracker — beat frequency, quality, and trend persistence",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uv run --script scripts/earnings_rhythm.py NVDA AVGO DELL
  uv run --script scripts/earnings_rhythm.py --portfolio
  uv run --script scripts/earnings_rhythm.py NVDA --json
  uv run --script scripts/earnings_rhythm.py --portfolio --quarters 12
        """,
    )
    parser.add_argument(
        "tickers",
        nargs="*",
        metavar="TICKER",
        help="One or more tickers to analyze (e.g. NVDA AVGO DELL)",
    )
    parser.add_argument(
        "--portfolio",
        action="store_true",
        help="Scan all US long positions from portfolio_state.json",
    )
    parser.add_argument(
        "--quarters", "-q",
        type=int,
        default=DEFAULT_QUARTERS,
        metavar="N",
        help=f"Number of historical quarters to analyze (default: {DEFAULT_QUARTERS})",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_out",
        help="Output results as JSON instead of Rich table",
    )
    args = parser.parse_args()

    # Resolve ticker list
    if args.portfolio and args.tickers:
        parser.error("Use either positional tickers OR --portfolio, not both.")

    if args.portfolio:
        holdings = load_us_tickers()
        if not holdings:
            print("[ERROR] No US positions found in portfolio_state.json", file=sys.stderr)
            sys.exit(1)
    elif args.tickers:
        holdings = [(t.upper(), t.upper()) for t in args.tickers]
    else:
        parser.print_help()
        sys.exit(0)

    n_quarters = max(3, min(20, args.quarters))

    console = Console(highlight=False) if not args.json_out else Console(quiet=True)

    if not args.json_out:
        console.print()
        console.print(
            f"[bold white]F21 Earnings Rhythm[/bold white]  |  "
            f"[dim]{len(holdings)} ticker(s)  |  {n_quarters}Q lookback  |  "
            f"Run: {datetime.now().strftime('%Y-%m-%d %H:%M')}[/dim]"
        )
        console.print()

    results: list[RhythmResult] = []
    for i, (ticker, name) in enumerate(holdings, 1):
        if not args.json_out:
            console.print(
                f"  [dim][{i}/{len(holdings)}][/dim] Fetching [bold cyan]{ticker}[/bold cyan]...",
                end=" ",
            )
            sys.stdout.flush()

        try:
            result = analyze(ticker, name, n_quarters)
            results.append(result)
            if not args.json_out:
                if result.data_available:
                    console.print(
                        f"[green]ok[/green] "
                        f"[dim]{result.beat_count}/{result.scored_quarters} beats | "
                        f"{result.f21_class}[/dim]"
                    )
                else:
                    console.print("[yellow]no data (ETF or delisted?)[/yellow]")
        except Exception as e:
            results.append(RhythmResult(
                ticker=ticker, name=name,
                beat_rate=None, beat_count=0, scored_quarters=0,
                beat_streak=0, avg_surprise=None,
                surprise_trend="Insufficient", surprise_slope=None,
                f21_class="N/A", f21_signal="N/A",
                next_earnings=None, next_eps_estimate=None,
                quarters=[], data_available=False,
            ))
            if not args.json_out:
                console.print(f"[red]error: {e}[/red]")

    if args.json_out:
        print(json.dumps(to_json(results), indent=2))
        return

    # Rich output
    console.print()
    render_summary_table(results, console)
    console.print()
    render_detail_tables(results, console)
    render_legend(console)
    console.print()


if __name__ == "__main__":
    main()

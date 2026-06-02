# /// script
# requires-python = ">=3.11"
# dependencies = ["yfinance>=0.2.40", "rich>=13.0"]
# ///
"""
US PEG Ratio Calculator — Reliable PEG using yfinance earnings_estimate

Uses earnings_estimate FY data, NOT the unreliable info['forwardPE'] field.

Formula:
  Forward PE  = price / FY+1 EPS avg
  2Y EPS CAGR = (FY+1 avg / yearAgoEps)^0.5 - 1   [yearAgo = FY-1 actual]
  PEG         = Forward PE / (2Y CAGR * 100)

Usage:
  uv run --script scripts/us_peg_calculator.py NVDA AVGO DELL
  uv run --script scripts/us_peg_calculator.py --portfolio
  uv run --script scripts/us_peg_calculator.py --portfolio --json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import dataclass, field
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


# ─── Data types ───────────────────────────────────────────────────────────────
@dataclass
class PEGResult:
    ticker: str
    price: Optional[float] = None
    eps_0y: Optional[float] = None        # FY+0 avg estimate
    eps_1y: Optional[float] = None        # FY+1 avg estimate
    eps_year_ago: Optional[float] = None  # yearAgoEps from FY+0 row (= FY-1 actual)
    analysts_0y: Optional[int] = None
    analysts_1y: Optional[int] = None
    forward_pe: Optional[float] = None
    cagr_2y: Optional[float] = None       # decimal, e.g. 0.65 = 65%
    peg: Optional[float] = None
    flags: list[str] = field(default_factory=list)
    error: Optional[str] = None


# ─── Fetch & Calculate ────────────────────────────────────────────────────────
def fetch_peg(ticker: str, retry: int = 2) -> PEGResult:
    result = PEGResult(ticker=ticker)
    attempt = 0

    while attempt <= retry:
        try:
            t = yf.Ticker(ticker)

            # 1. Current price from fast_info
            try:
                price = t.fast_info.last_price
                if price is None or math.isnan(price):
                    result.error = "price unavailable"
                    return result
                result.price = price
            except Exception as e:
                result.error = f"price fetch failed: {e}"
                return result

            # 2. earnings_estimate DataFrame
            try:
                ee = t.earnings_estimate
                if ee is None or ee.empty:
                    result.error = "earnings_estimate unavailable"
                    return result
            except Exception as e:
                result.error = f"earnings_estimate fetch failed: {e}"
                return result

            # Check required rows exist
            if "0y" not in ee.index or "+1y" not in ee.index:
                result.error = f"missing FY rows in earnings_estimate (got: {list(ee.index)})"
                return result

            row_0y = ee.loc["0y"]
            row_1y = ee.loc["+1y"]

            # 3. FY+0 avg EPS (current fiscal year estimate)
            eps_0y = _safe_float(row_0y.get("avg"))
            result.eps_0y = eps_0y

            # 4. FY+1 avg EPS (next fiscal year estimate)
            eps_1y = _safe_float(row_1y.get("avg"))
            result.eps_1y = eps_1y

            # 5. yearAgoEps from 0y row = FY-1 actual (one year before current FY)
            year_ago = _safe_float(row_0y.get("yearAgoEps"))
            result.eps_year_ago = year_ago

            # Analyst coverage
            result.analysts_0y = _safe_int(row_0y.get("numberOfAnalysts"))
            result.analysts_1y = _safe_int(row_1y.get("numberOfAnalysts"))

            # Use minimum analyst count for coverage flag
            min_analysts = min(
                result.analysts_0y or 0,
                result.analysts_1y or 0,
            )

            # ── Flags ────────────────────────────────────────────────────────
            if min_analysts < 5:
                result.flags.append(f"⚠️ low coverage ({min_analysts} analysts)")

            # 6. Forward PE = price / FY+1 EPS
            if eps_1y is not None and eps_1y > 0:
                result.forward_pe = price / eps_1y
            elif eps_1y is not None and eps_1y <= 0:
                result.flags.append("⚠️ negative/zero FY+1 EPS (PE undefined)")
            else:
                result.flags.append("⚠️ FY+1 EPS missing")

            # 7. 2Y EPS CAGR = (FY+1 / yearAgo)^0.5 - 1
            if eps_1y is not None and year_ago is not None:
                if year_ago > 0 and eps_1y > 0:
                    result.cagr_2y = (eps_1y / year_ago) ** 0.5 - 1
                elif year_ago <= 0 or eps_1y <= 0:
                    result.flags.append("⚠️ negative growth (CAGR undefined — base or terminal EPS ≤ 0)")
                    # Still store directional info
                    if year_ago is not None and eps_1y is not None:
                        result.cagr_2y = None  # explicitly undefined
            else:
                result.flags.append("⚠️ insufficient data for CAGR")

            # 8. PEG = Forward PE / (2Y CAGR * 100)
            if result.forward_pe is not None and result.cagr_2y is not None:
                cagr_pct = result.cagr_2y * 100
                if cagr_pct > 0:
                    result.peg = result.forward_pe / cagr_pct
                    # Flag distortions
                    if result.cagr_2y > 1.0:  # >100% CAGR
                        result.flags.append(f"⚠️ cycle PEG (CAGR {result.cagr_2y*100:.0f}% — likely cycle-peak distortion)")
                elif cagr_pct < 0:
                    result.flags.append("⚠️ negative growth (PEG undefined)")
                else:
                    result.flags.append("⚠️ zero CAGR (PEG undefined)")

            # Flag flat/declining: FY+1 EPS < FY+0 EPS
            if eps_0y is not None and eps_1y is not None:
                if eps_1y < eps_0y:
                    decline_pct = (eps_1y - eps_0y) / abs(eps_0y) * 100
                    result.flags.append(f"⚠️ flat/declining EPS (+1y {decline_pct:+.1f}% vs 0y)")

            # Flag negative CAGR separately for clarity
            if result.cagr_2y is not None and result.cagr_2y < 0:
                result.flags.append(f"⚠️ negative growth ({result.cagr_2y*100:.1f}% CAGR)")

            return result

        except Exception as e:
            attempt += 1
            if attempt > retry:
                result.error = f"fetch error after {retry+1} attempts: {e}"
                return result
            # Brief back-off before retry
            time.sleep(1.5 * attempt)

    return result  # unreachable but satisfies type checker


def _safe_float(val) -> Optional[float]:
    """Return float or None; guard against NaN/None."""
    try:
        if val is None:
            return None
        v = float(val)
        return None if math.isnan(v) else v
    except (TypeError, ValueError):
        return None


def _safe_int(val) -> Optional[int]:
    try:
        if val is None:
            return None
        v = float(val)
        return None if math.isnan(v) else int(v)
    except (TypeError, ValueError):
        return None


# ─── Portfolio loader ─────────────────────────────────────────────────────────
def load_us_tickers() -> list[str]:
    if not PORTFOLIO_PATH.exists():
        console.print(f"[red]portfolio_state.json not found at {PORTFOLIO_PATH}[/red]")
        sys.exit(1)
    with open(PORTFOLIO_PATH) as f:
        data = json.load(f)
    us_positions = data.get("accounts", {}).get("us", {}).get("positions", [])
    tickers = [p["ticker"] for p in us_positions if p.get("ticker")]
    if not tickers:
        console.print("[yellow]No US positions found in portfolio_state.json[/yellow]")
        sys.exit(0)
    return tickers


# ─── Output helpers ───────────────────────────────────────────────────────────
def _fmt_float(val: Optional[float], fmt: str = ".2f", na: str = "N/A") -> str:
    if val is None:
        return na
    return format(val, fmt)


def _peg_color(peg: Optional[float]) -> str:
    """Return rich color based on PEG tier."""
    if peg is None:
        return "white"
    if peg < 1.0:
        return "bright_green"
    elif peg < 1.5:
        return "green"
    elif peg < 2.0:
        return "yellow"
    elif peg < 3.0:
        return "dark_orange"
    else:
        return "red"


def render_table(results: list[PEGResult]) -> None:
    table = Table(
        title="[bold]US PEG Calculator[/bold]  —  Forward PE / 2Y EPS CAGR",
        box=box.SIMPLE_HEAD,
        show_lines=False,
        header_style="bold cyan",
        border_style="dim",
    )

    table.add_column("Ticker", style="bold white", no_wrap=True)
    table.add_column("Price", justify="right")
    table.add_column("Fwd PE", justify="right")
    table.add_column("EPS 0y", justify="right")
    table.add_column("EPS +1y", justify="right")
    table.add_column("Analysts", justify="right")
    table.add_column("2Y CAGR", justify="right")
    table.add_column("PEG", justify="right")
    table.add_column("Flags", no_wrap=False)

    for r in results:
        if r.error:
            table.add_row(
                r.ticker,
                "—", "—", "—", "—", "—", "—",
                Text("ERROR", style="bold red"),
                f"[red]{r.error}[/red]",
            )
            continue

        peg_color = _peg_color(r.peg)
        peg_str = _fmt_float(r.peg, ".2f") if r.peg is not None else "N/A"
        peg_cell = Text(peg_str, style=f"bold {peg_color}")

        cagr_str = (
            f"{r.cagr_2y * 100:+.1f}%" if r.cagr_2y is not None else "N/A"
        )

        analysts_str = str(r.analysts_1y) if r.analysts_1y is not None else "N/A"

        flags_short = "\n".join(r.flags) if r.flags else "✓"

        table.add_row(
            r.ticker,
            _fmt_float(r.price, ".2f"),
            _fmt_float(r.forward_pe, ".1f"),
            _fmt_float(r.eps_0y, ".3f"),
            _fmt_float(r.eps_1y, ".3f"),
            analysts_str,
            cagr_str,
            peg_cell,
            flags_short,
        )

    console.print()
    console.print(table)
    console.print(
        "[dim]PEG legend: [bright_green]<1.0[/bright_green] · [green]1.0-1.5[/green] · "
        "[yellow]1.5-2.0[/yellow] · [dark_orange]2.0-3.0[/dark_orange] · [red]>3.0[/red][/dim]"
    )
    console.print(
        "[dim]Methodology: Forward PE = Price / FY+1 EPS avg  |  "
        "2Y CAGR = (FY+1 / FY-1 actual)^0.5 - 1  |  "
        "PEG = Fwd PE / (2Y CAGR × 100)[/dim]\n"
    )


def render_json(results: list[PEGResult]) -> None:
    output = []
    for r in results:
        output.append({
            "ticker": r.ticker,
            "price": r.price,
            "forward_pe": r.forward_pe,
            "eps_fy0_avg": r.eps_0y,
            "eps_fy1_avg": r.eps_1y,
            "eps_year_ago": r.eps_year_ago,
            "analysts_fy0": r.analysts_0y,
            "analysts_fy1": r.analysts_1y,
            "cagr_2y_pct": round(r.cagr_2y * 100, 2) if r.cagr_2y is not None else None,
            "peg": round(r.peg, 3) if r.peg is not None else None,
            "flags": r.flags,
            "error": r.error,
        })
    print(json.dumps(output, indent=2))


# ─── Main ─────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Calculate PEG ratios using yfinance earnings_estimate (reliable forward EPS data)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uv run --script scripts/us_peg_calculator.py NVDA AVGO DELL
  uv run --script scripts/us_peg_calculator.py --portfolio
  uv run --script scripts/us_peg_calculator.py --portfolio --json
""",
    )
    parser.add_argument(
        "tickers",
        nargs="*",
        type=str,
        help="One or more ticker symbols (e.g. NVDA AAPL MSFT)",
    )
    parser.add_argument(
        "--portfolio",
        action="store_true",
        help=f"Scan all US positions from {PORTFOLIO_PATH}",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output machine-readable JSON instead of Rich table",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Seconds to wait between ticker fetches (default: 0.5)",
    )

    args = parser.parse_args()

    # Resolve ticker list
    if args.portfolio:
        tickers = load_us_tickers()
        if not args.json_output:
            console.print(f"[cyan]Loaded {len(tickers)} US positions from portfolio_state.json:[/cyan] {', '.join(tickers)}")
    elif args.tickers:
        tickers = [t.upper() for t in args.tickers]
    else:
        parser.print_help()
        sys.exit(1)

    if not args.json_output:
        console.print(f"\n[dim]Fetching earnings estimates for {len(tickers)} ticker(s)...[/dim]")

    results: list[PEGResult] = []
    for i, ticker in enumerate(tickers):
        if not args.json_output:
            console.print(f"  [dim]{ticker}...[/dim]", end="\r")
        result = fetch_peg(ticker)
        results.append(result)
        # Rate-limit courtesy delay between fetches
        if i < len(tickers) - 1 and args.delay > 0:
            time.sleep(args.delay)

    if not args.json_output:
        console.print(" " * 40, end="\r")  # clear last ticker line

    if args.json_output:
        render_json(results)
    else:
        render_table(results)

    # Summary line (non-JSON mode)
    if not args.json_output:
        errors = [r for r in results if r.error]
        valid = [r for r in results if r.peg is not None]
        if errors:
            console.print(f"[yellow]⚠ {len(errors)} ticker(s) had errors: {', '.join(e.ticker for e in errors)}[/yellow]")
        console.print(f"[dim]PEG calculated for {len(valid)}/{len(results)} tickers.[/dim]\n")


if __name__ == "__main__":
    main()

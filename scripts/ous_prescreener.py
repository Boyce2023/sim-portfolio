# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "finvizfinance>=0.14",
#   "yfinance>=0.2.40",
#   "rich>=13.0",
#   "pandas>=2.0",
# ]
# ///
"""
OUS Pre-Screener — Phase 2 of Open Universe Scan

Automates PEG<1.5 candidate discovery across ALL sectors using FinViz + yfinance enrichment.

Flow:
  1. FinViz scan: PEG < max, Market Cap > min → candidate DataFrame
  2. yfinance enrichment per candidate (earnings estimate, 52w position, beat rate)
  3. Categorize into Cat 1/2/3 and sort by PEG ascending
  4. Flag: Cycle PEG, Low Coverage, Near 52w High
  5. Rich table output per category (or JSON with --json)

Usage:
  uv run --script scripts/ous_prescreener.py
  uv run --script scripts/ous_prescreener.py --peg-max 1.2 --min-cap 5
  uv run --script scripts/ous_prescreener.py --sector TECH
  uv run --script scripts/ous_prescreener.py --all-sectors --top 20
  uv run --script scripts/ous_prescreener.py --json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import warnings
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd
import yfinance as yf
from finvizfinance.screener.overview import Overview
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

warnings.filterwarnings("ignore")

console = Console()

# ─── Sector Categorization ────────────────────────────────────────────────────

CAT1_SECTORS = {"Technology"}
CAT2_SECTORS = {"Healthcare", "Communication Services"}
CAT3_SECTORS = {
    "Financial",
    "Industrials",
    "Energy",
    "Consumer Cyclical",
    "Consumer Defensive",
    "Basic Materials",
    "Utilities",
    "Real Estate",
}

# FinViz sector filter keys (used in screener filters)
FINVIZ_SECTOR_MAP = {
    "TECH": "Technology",
    "HEALTH": "Healthcare",
    "COMM": "Communication Services",
    "FIN": "Financial",
    "IND": "Industrials",
    "ENERGY": "Energy",
    "CONS_CYCL": "Consumer Cyclical",
    "CONS_DEF": "Consumer Defensive",
    "MATERIALS": "Basic Materials",
    "UTILITIES": "Utilities",
    "REAL_ESTATE": "Real Estate",
}

# ─── Data Types ───────────────────────────────────────────────────────────────

@dataclass
class OUSCandidate:
    ticker: str
    company: str = ""
    sector: str = ""
    finviz_peg: Optional[float] = None
    # yfinance enrichment
    price: Optional[float] = None
    eps_0y: Optional[float] = None
    eps_1y: Optional[float] = None
    eps_year_ago: Optional[float] = None
    analysts_0y: Optional[int] = None
    analysts_1y: Optional[int] = None
    forward_pe: Optional[float] = None
    cagr_2y: Optional[float] = None
    manual_peg: Optional[float] = None
    week52_high: Optional[float] = None
    week52_low: Optional[float] = None
    week52_pos: Optional[float] = None       # 0.0 = at 52w low, 1.0 = at 52w high
    beat_rate: Optional[float] = None        # fraction of last 4Q that beat EPS
    flags: list[str] = field(default_factory=list)
    enrich_error: Optional[str] = None
    category: int = 3


# ─── FinViz Screener ──────────────────────────────────────────────────────────

def run_finviz_scan(
    peg_max: float,
    min_cap_b: float,
    sector_filter: Optional[str],
) -> pd.DataFrame:
    """
    Pull candidates from FinViz.
    Returns DataFrame with columns: Ticker, Company, Sector, Market Cap, P/E, PEG.
    """
    console.print(f"[cyan]FinViz scan:[/cyan] PEG ≤ {peg_max}, Market Cap ≥ ${min_cap_b}B"
                  + (f", Sector = {sector_filter}" if sector_filter else ", All Sectors"))

    screener = Overview()

    # Map min_cap billions to FinViz market cap filter (FULL strings, "over" variants).
    # 修复(06-16): 旧代码生成"Large"等短码, finvizfinance拒绝, 全市场扫描静默失败=门1洞。
    # 合法值: '+Large (over $10bln)' / '+Mid (over $2bln)' / '+Small (over $300mln)' ...
    if min_cap_b >= 10:
        cap_filter = "+Large (over $10bln)"
    elif min_cap_b >= 2:
        cap_filter = "+Mid (over $2bln)"
    elif min_cap_b >= 0.3:
        cap_filter = "+Small (over $300mln)"
    else:
        cap_filter = "+Micro (over $50mln)"
    # 注: FinViz cap是粗筛, 精确min_cap由后续yf enrichment兜底过滤

    filters_dict = {
        "Market Cap.": cap_filter,
    }

    # PEG filter: FinViz合法值 'Low (<1)' / 'Under 1' / 'Under 2' / 'Under 3' (修复06-16)
    # 旧代码用'Profitable (<2)'被拒=门1洞同源。精确peg_max由下方解析列兜底。
    if peg_max <= 1.0:
        filters_dict["PEG"] = "Low (<1)"
    elif peg_max <= 2.0:
        filters_dict["PEG"] = "Under 2"
    else:
        filters_dict["PEG"] = "Under 3"

    if sector_filter:
        filters_dict["Sector"] = sector_filter

    try:
        screener.set_filter(filters_dict=filters_dict)
        # 修复(06-16): finvizfinance的进度条打到stdout, 污染--json输出。
        #   重定向到stderr, 保证--json的stdout是干净JSON(门1: 可机读喂给scanner)。
        import contextlib
        with contextlib.redirect_stdout(sys.stderr):
            df = screener.screener_view()
    except Exception as e:
        console.print(f"[red]FinViz scan failed: {e}[/red]")
        sys.exit(1)

    if df is None or df.empty:
        console.print("[yellow]FinViz returned 0 results. Check filters.[/yellow]")
        return pd.DataFrame()

    console.print(f"[dim]FinViz raw results: {len(df)} rows[/dim]")

    # Normalize column names (finvizfinance uses various capitalizations)
    df.columns = [c.strip() for c in df.columns]

    # Attempt to parse PEG column and apply precise peg_max filter
    if "P/E" in df.columns:
        df["P/E"] = pd.to_numeric(df["P/E"], errors="coerce")

    # finvizfinance may return 'PEG' or not — use best available
    peg_col = None
    for c in ["PEG", "P/E/G"]:
        if c in df.columns:
            peg_col = c
            break

    if peg_col:
        df[peg_col] = pd.to_numeric(df[peg_col], errors="coerce")
        df = df[df[peg_col] <= peg_max].copy()
        console.print(f"[dim]After PEG ≤ {peg_max} filter: {len(df)} rows[/dim]")

    return df


# ─── yfinance Enrichment ──────────────────────────────────────────────────────

def _safe_float(val) -> Optional[float]:
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


def _beat_rate_from_earnings_history(t: yf.Ticker) -> Optional[float]:
    """
    Compute beat rate from last 4 quarters of earnings history.
    Returns fraction of beats (epsActual > epsEstimate), or None if unavailable.
    """
    try:
        hist = t.earnings_history
        if hist is None or hist.empty:
            return None

        # Take last 4 quarters (most recent first)
        recent = hist.head(4)
        if len(recent) == 0:
            return None

        beats = 0
        total = 0
        for _, row in recent.iterrows():
            actual = _safe_float(row.get("epsActual"))
            estimate = _safe_float(row.get("epsEstimate"))
            if actual is not None and estimate is not None:
                total += 1
                if actual >= estimate:
                    beats += 1

        return beats / total if total > 0 else None
    except Exception:
        return None


def enrich_candidate(candidate: OUSCandidate) -> OUSCandidate:
    """
    Fetch yfinance data to enrich a candidate.
    Mutates and returns the candidate.
    """
    try:
        t = yf.Ticker(candidate.ticker)

        # ── Price + 52w range ─────────────────────────────────────────────────
        try:
            fi = t.fast_info
            price = _safe_float(fi.last_price)
            candidate.price = price
            candidate.week52_high = _safe_float(fi.year_high)
            candidate.week52_low = _safe_float(fi.year_low)

            if (price is not None and
                    candidate.week52_high is not None and
                    candidate.week52_low is not None and
                    candidate.week52_high > candidate.week52_low):
                candidate.week52_pos = (price - candidate.week52_low) / (
                    candidate.week52_high - candidate.week52_low
                )
        except Exception as e:
            candidate.enrich_error = f"fast_info: {e}"

        # ── Earnings Estimate ─────────────────────────────────────────────────
        try:
            ee = t.earnings_estimate
            if ee is not None and not ee.empty:
                if "0y" in ee.index:
                    row_0y = ee.loc["0y"]
                    candidate.eps_0y = _safe_float(row_0y.get("avg"))
                    candidate.eps_year_ago = _safe_float(row_0y.get("yearAgoEps"))
                    candidate.analysts_0y = _safe_int(row_0y.get("numberOfAnalysts"))

                if "+1y" in ee.index:
                    row_1y = ee.loc["+1y"]
                    candidate.eps_1y = _safe_float(row_1y.get("avg"))
                    candidate.analysts_1y = _safe_int(row_1y.get("numberOfAnalysts"))
        except Exception as e:
            if candidate.enrich_error:
                candidate.enrich_error += f"; earnings_estimate: {e}"
            else:
                candidate.enrich_error = f"earnings_estimate: {e}"

        # ── Manual PEG Calculation ────────────────────────────────────────────
        price = candidate.price
        eps_1y = candidate.eps_1y
        eps_year_ago = candidate.eps_year_ago

        if price and eps_1y and eps_1y > 0:
            candidate.forward_pe = price / eps_1y

        if eps_1y and eps_year_ago and eps_year_ago > 0 and eps_1y > 0:
            candidate.cagr_2y = (eps_1y / eps_year_ago) ** 0.5 - 1

        if candidate.forward_pe and candidate.cagr_2y:
            cagr_pct = candidate.cagr_2y * 100
            if cagr_pct > 0:
                candidate.manual_peg = candidate.forward_pe / cagr_pct

        # ── Beat Rate ─────────────────────────────────────────────────────────
        candidate.beat_rate = _beat_rate_from_earnings_history(t)

        # ── Flags ─────────────────────────────────────────────────────────────
        min_analysts = min(
            candidate.analysts_0y or 0,
            candidate.analysts_1y or 0,
        )
        if min_analysts < 5:
            candidate.flags.append(f"LOW_COV({min_analysts})")

        if candidate.cagr_2y is not None and candidate.cagr_2y > 1.0:
            candidate.flags.append(f"CYCLE_PEG({candidate.cagr_2y*100:.0f}%)")

        if candidate.week52_pos is not None and candidate.week52_pos > 0.90:
            candidate.flags.append(f"NEAR_52H({candidate.week52_pos*100:.0f}%)")

    except Exception as e:
        candidate.enrich_error = f"enrich failed: {e}"

    return candidate


# ─── Categorization ───────────────────────────────────────────────────────────

def categorize(sector: str) -> int:
    if sector in CAT1_SECTORS:
        return 1
    if sector in CAT2_SECTORS:
        return 2
    return 3


# ─── Formatting Helpers ───────────────────────────────────────────────────────

def _fmt(val: Optional[float], fmt: str = ".2f", na: str = "—") -> str:
    if val is None:
        return na
    return format(val, fmt)


def _peg_color(peg: Optional[float]) -> str:
    if peg is None:
        return "white"
    if peg < 0.8:
        return "bright_green"
    if peg < 1.0:
        return "green"
    if peg < 1.5:
        return "yellow"
    if peg < 2.0:
        return "dark_orange"
    return "red"


def _pos_color(pos: Optional[float]) -> str:
    if pos is None:
        return "white"
    if pos > 0.90:
        return "red"
    if pos > 0.75:
        return "dark_orange"
    if pos > 0.50:
        return "yellow"
    return "green"


def _beat_str(rate: Optional[float]) -> str:
    if rate is None:
        return "—"
    n = round(rate * 4)
    return f"{n}/4"


# ─── Rich Table Rendering ─────────────────────────────────────────────────────

CATEGORY_LABELS = {
    1: "Cat 1 — Technology",
    2: "Cat 2 — Healthcare / Communication Services",
    3: "Cat 3 — Financials / Industrials / Energy / Consumer / Other",
}

CATEGORY_COLORS = {
    1: "bright_cyan",
    2: "bright_magenta",
    3: "bright_yellow",
}


def render_category_table(
    candidates: list[OUSCandidate],
    category: int,
    peg_max: float,
) -> None:
    cat_candidates = [c for c in candidates if c.category == category]
    if not cat_candidates:
        return

    # Sort by FinViz PEG (primary), fall back to manual PEG
    def sort_key(c: OUSCandidate) -> float:
        return c.finviz_peg if c.finviz_peg is not None else (c.manual_peg or 99.0)

    cat_candidates.sort(key=sort_key)

    color = CATEGORY_COLORS[category]
    label = CATEGORY_LABELS[category]

    table = Table(
        title=f"[bold {color}]{label}[/bold {color}]  —  {len(cat_candidates)} candidates",
        box=box.SIMPLE_HEAD,
        show_lines=False,
        header_style=f"bold {color}",
        border_style="dim",
        expand=False,
    )

    table.add_column("Ticker", style="bold white", no_wrap=True, min_width=6)
    table.add_column("Company", no_wrap=False, max_width=28)
    table.add_column("Sector", no_wrap=True, max_width=22)
    table.add_column("FV PEG", justify="right")
    table.add_column("Manual PEG", justify="right")
    table.add_column("Fwd PE", justify="right")
    table.add_column("CAGR", justify="right")
    table.add_column("Analysts", justify="right")
    table.add_column("52w Pos", justify="right")
    table.add_column("Beat 4Q", justify="right")
    table.add_column("Flags", no_wrap=False, max_width=40)

    for c in cat_candidates:
        fv_peg_str = _fmt(c.finviz_peg)
        fv_peg_text = Text(fv_peg_str, style=_peg_color(c.finviz_peg))

        man_peg_str = _fmt(c.manual_peg)
        man_peg_text = Text(man_peg_str, style=_peg_color(c.manual_peg))

        fwd_pe_str = _fmt(c.forward_pe)

        cagr_str = (
            f"{c.cagr_2y*100:.1f}%"
            if c.cagr_2y is not None
            else "—"
        )

        analysts_str = str(
            min(c.analysts_0y or 0, c.analysts_1y or 0) or "—"
        )

        pos_str = (
            f"{c.week52_pos*100:.0f}%"
            if c.week52_pos is not None
            else "—"
        )
        pos_text = Text(pos_str, style=_pos_color(c.week52_pos))

        beat_str = _beat_str(c.beat_rate)

        flags_str = "  ".join(c.flags) if c.flags else ""
        if c.enrich_error:
            flags_str += f"  ⚠ {c.enrich_error[:40]}"

        table.add_row(
            c.ticker,
            c.company[:28],
            c.sector[:22],
            fv_peg_text,
            man_peg_text,
            fwd_pe_str,
            cagr_str,
            analysts_str,
            pos_text,
            beat_str,
            flags_str,
        )

    console.print(table)
    console.print()


# ─── JSON Output ──────────────────────────────────────────────────────────────

def to_json_output(candidates: list[OUSCandidate]) -> dict:
    results = []
    for c in candidates:
        results.append({
            "ticker": c.ticker,
            "company": c.company,
            "sector": c.sector,
            "category": c.category,
            "finviz_peg": c.finviz_peg,
            "manual_peg": c.manual_peg,
            "forward_pe": c.forward_pe,
            "cagr_2y_pct": round(c.cagr_2y * 100, 2) if c.cagr_2y is not None else None,
            "analysts": min(c.analysts_0y or 0, c.analysts_1y or 0) or None,
            "week52_pos_pct": round(c.week52_pos * 100, 1) if c.week52_pos is not None else None,
            "beat_rate_4q": _beat_str(c.beat_rate),
            "flags": c.flags,
            "enrich_error": c.enrich_error,
        })
    return {
        "scan_type": "OUS_Phase2_PEG_Screener",
        "total_candidates": len(results),
        "results": results,
    }


# ─── Main ─────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="OUS Phase 2 Pre-Screener — PEG<max across all sectors",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--peg-max",
        type=float,
        default=1.5,
        metavar="FLOAT",
        help="Maximum PEG ratio filter (default: 1.5)",
    )
    parser.add_argument(
        "--min-cap",
        type=float,
        default=2.0,
        metavar="BILLIONS",
        help="Minimum market cap in billions (default: 2)",
    )
    parser.add_argument(
        "--sector",
        type=str,
        default=None,
        metavar="CODE",
        help=(
            "Single sector filter. Codes: "
            + ", ".join(FINVIZ_SECTOR_MAP.keys())
        ),
    )
    parser.add_argument(
        "--all-sectors",
        action="store_true",
        help="Scan all sectors (default behavior; explicit flag for clarity)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON (machine-readable)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=None,
        metavar="N",
        help="Show only top N candidates per category by PEG (default: all)",
    )
    parser.add_argument(
        "--max-candidates",
        type=int,
        default=100,
        metavar="N",
        help="Maximum candidates to enrich via yfinance (default: 100, cap to avoid rate limits)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # ── Resolve sector filter ──────────────────────────────────────────────────
    sector_filter: Optional[str] = None
    if args.sector:
        sector_key = args.sector.upper()
        if sector_key not in FINVIZ_SECTOR_MAP:
            console.print(
                f"[red]Unknown sector code: {args.sector}[/red]\n"
                f"Valid codes: {', '.join(FINVIZ_SECTOR_MAP.keys())}"
            )
            sys.exit(1)
        sector_filter = FINVIZ_SECTOR_MAP[sector_key]

    if not args.json:
        console.print(Panel(
            "[bold]OUS Phase 2 Pre-Screener[/bold]\n"
            "PEG scan across universe → yfinance enrichment → category tables\n\n"
            f"PEG max: [cyan]{args.peg_max}[/cyan]  |  "
            f"Min cap: [cyan]${args.min_cap}B[/cyan]  |  "
            f"Max candidates: [cyan]{args.max_candidates}[/cyan]",
            border_style="bright_blue",
        ))

    # ── Step 1: FinViz Scan ────────────────────────────────────────────────────
    df = run_finviz_scan(
        peg_max=args.peg_max,
        min_cap_b=args.min_cap,
        sector_filter=sector_filter,
    )

    if df.empty:
        if args.json:
            print(json.dumps({"scan_type": "OUS_Phase2_PEG_Screener", "total_candidates": 0, "results": []}))
        else:
            console.print("[yellow]No candidates found. Try loosening filters.[/yellow]")
        return

    # ── Step 2: Build candidate list, apply max-candidates cap ────────────────
    # Detect column names defensively
    ticker_col = next((c for c in df.columns if c.lower() in ("ticker", "symbol")), None)
    company_col = next((c for c in df.columns if c.lower() in ("company", "name")), None)
    sector_col = next((c for c in df.columns if c.lower() == "sector"), None)
    peg_col = next((c for c in df.columns if c.upper() in ("PEG", "P/E/G")), None)

    if ticker_col is None:
        console.print("[red]Cannot find Ticker column in FinViz output. Columns: "
                      + str(list(df.columns)) + "[/red]")
        sys.exit(1)

    # Sort by PEG ascending before capping so we keep best candidates
    if peg_col:
        df = df.sort_values(peg_col, ascending=True)

    df = df.head(args.max_candidates).reset_index(drop=True)

    candidates: list[OUSCandidate] = []
    for _, row in df.iterrows():
        ticker = str(row[ticker_col]).strip()
        company = str(row[company_col]).strip() if company_col else ""
        sector = str(row[sector_col]).strip() if sector_col else ""
        peg_val = _safe_float(row[peg_col]) if peg_col else None

        c = OUSCandidate(
            ticker=ticker,
            company=company,
            sector=sector,
            finviz_peg=peg_val,
            category=categorize(sector),
        )
        candidates.append(c)

    if not args.json:
        console.print(
            f"[cyan]Enriching {len(candidates)} candidates via yfinance "
            f"(~{len(candidates) * 0.2:.0f}s)…[/cyan]"
        )

    # ── Step 3: yfinance Enrichment ───────────────────────────────────────────
    for i, candidate in enumerate(candidates):
        if not args.json:
            console.print(
                f"  [{i+1}/{len(candidates)}] {candidate.ticker}",
                end="\r",
            )
        enrich_candidate(candidate)
        time.sleep(0.2)  # Respect yfinance rate limits

    if not args.json:
        console.print()  # Clear \r line

    # ── Step 4: Apply --top filter per category ────────────────────────────────
    if args.top:
        def sort_peg(c: OUSCandidate) -> float:
            return c.finviz_peg if c.finviz_peg is not None else (c.manual_peg or 99.0)

        filtered: list[OUSCandidate] = []
        for cat in (1, 2, 3):
            cat_list = sorted(
                [c for c in candidates if c.category == cat],
                key=sort_peg,
            )
            filtered.extend(cat_list[: args.top])
        candidates = filtered

    # ── Step 5: Output ────────────────────────────────────────────────────────
    if args.json:
        output = to_json_output(candidates)
        print(json.dumps(output, indent=2, ensure_ascii=False))
        return

    # Rich table output per category
    for cat in (1, 2, 3):
        render_category_table(candidates, cat, args.peg_max)

    # Summary footer
    total = len(candidates)
    flagged = sum(1 for c in candidates if c.flags)
    console.print(
        f"[dim]Total: {total} candidates  |  Flagged: {flagged}  |  "
        f"PEG max: {args.peg_max}  |  Min cap: ${args.min_cap}B[/dim]"
    )

    # Flag legend
    console.print()
    console.print("[bold]Flag Legend:[/bold]")
    console.print("  [yellow]LOW_COV(N)[/yellow]   — Fewer than 5 analysts covering")
    console.print("  [yellow]CYCLE_PEG(X%)[/yellow] — CAGR >100%, likely cycle-peak distortion")
    console.print("  [red]NEAR_52H(X%)[/red]  — Price within top 10% of 52-week range")


if __name__ == "__main__":
    main()

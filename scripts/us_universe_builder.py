#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "requests",
#   "pandas",
#   "rich",
# ]
# ///
"""
US Stock Universe Builder
Downloads NASDAQ FTP symbol files, filters to common stocks only,
and outputs a clean JSON universe list.

Usage:
    uv run --script scripts/us_universe_builder.py
    uv run --script scripts/us_universe_builder.py --min-cap 1
    uv run --script scripts/us_universe_builder.py --output universe.json
    uv run --script scripts/us_universe_builder.py --refresh
"""

import argparse
import json
import re
import sys
import warnings
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
import urllib3
from rich.console import Console
from rich.table import Table
from rich import print as rprint

# Suppress SSL warnings for otherlisted.txt (known NASDAQ FTP SSL issue)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

console = Console()

NASDAQ_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"

CACHE_DIR = Path(__file__).parent.parent / ".cache"
NASDAQ_CACHE = CACHE_DIR / "nasdaqlisted.txt"
OTHER_CACHE = CACHE_DIR / "otherlisted.txt"


def download_file(url: str, cache_path: Path, verify_ssl: bool = True) -> str:
    """Download a file from URL, return content as string."""
    console.log(f"Downloading [cyan]{url}[/cyan]")
    try:
        resp = requests.get(url, timeout=30, verify=verify_ssl)
        resp.raise_for_status()
        content = resp.text
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(content, encoding="utf-8")
        console.log(f"  Saved to cache: [dim]{cache_path}[/dim]")
        return content
    except requests.RequestException as e:
        console.log(f"[red]Download failed: {e}[/red]")
        raise


def load_file(url: str, cache_path: Path, verify_ssl: bool = True, refresh: bool = False) -> str:
    """Load file from cache if available, otherwise download."""
    if not refresh and cache_path.exists():
        console.log(f"Using cached: [dim]{cache_path}[/dim]")
        return cache_path.read_text(encoding="utf-8")
    return download_file(url, cache_path, verify_ssl=verify_ssl)


def _parse_nasdaq_timestamp(raw: str) -> str:
    """Parse NASDAQ timestamp format MMDDYYYYHH:MM to readable string."""
    try:
        # Format: MMDDYYYYHH:MM (e.g., "0601202612:11")
        mm = raw[0:2]
        dd = raw[2:4]
        yyyy = raw[4:8]
        hhmm = raw[8:]  # "12:11"
        return f"{yyyy}-{mm}-{dd} {hhmm}"
    except Exception:
        return raw


def parse_nasdaq_listed(content: str) -> pd.DataFrame:
    """
    Parse nasdaqlisted.txt format.

    Columns: Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
    Last line: File Creation Time: YYYY-MM-DD HH:MM:SS
    """
    lines = content.strip().split("\n")

    # Extract file creation time from last line
    # Format: "File Creation Time: MMDDYYYYHH:MM|||||||" → parse to readable
    file_creation = None
    if lines and lines[-1].startswith("File Creation Time:"):
        raw_time = lines[-1].replace("File Creation Time:", "").strip().split("|")[0].strip()
        file_creation = _parse_nasdaq_timestamp(raw_time)
        lines = lines[:-1]

    # Parse pipe-delimited
    from io import StringIO
    df = pd.read_csv(StringIO("\n".join(lines)), sep="|", dtype=str)
    df.columns = [c.strip() for c in df.columns]

    # Normalize
    df = df.rename(columns={
        "Symbol": "ticker",
        "Security Name": "company_name",
        "Market Category": "market_category",
        "Test Issue": "test_issue",
        "Financial Status": "financial_status",
        "ETF": "etf",
    })

    df["exchange"] = "NASDAQ"
    df["listing_date"] = None
    df["_file_creation"] = file_creation

    return df, file_creation


def parse_other_listed(content: str) -> pd.DataFrame:
    """
    Parse otherlisted.txt format.

    Columns: ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
    Last line: File Creation Time: YYYY-MM-DD HH:MM:SS
    """
    lines = content.strip().split("\n")

    # Extract file creation time from last line
    file_creation = None
    if lines and lines[-1].startswith("File Creation Time:"):
        raw_time = lines[-1].replace("File Creation Time:", "").strip().split("|")[0].strip()
        file_creation = _parse_nasdaq_timestamp(raw_time)
        lines = lines[:-1]

    from io import StringIO
    df = pd.read_csv(StringIO("\n".join(lines)), sep="|", dtype=str)
    df.columns = [c.strip() for c in df.columns]

    # Normalize column names (handle variations)
    col_map = {}
    for col in df.columns:
        cl = col.lower()
        if "act symbol" in cl or (col == "ACT Symbol"):
            col_map[col] = "ticker"
        elif "security name" in cl:
            col_map[col] = "company_name"
        elif col.strip() == "Exchange":
            col_map[col] = "exchange_code"
        elif "test issue" in cl:
            col_map[col] = "test_issue"
        elif col.strip() == "ETF":
            col_map[col] = "etf"

    df = df.rename(columns=col_map)

    # Map exchange codes
    exchange_map = {
        "A": "AMEX",
        "N": "NYSE",
        "P": "NYSE Arca",
        "Z": "BATS",
        "V": "IEXG",
        "C": "NSX",
        "Q": "NASDAQ",
    }
    if "exchange_code" in df.columns:
        df["exchange"] = df["exchange_code"].map(exchange_map).fillna(df.get("exchange_code", "OTHER"))
    else:
        df["exchange"] = "OTHER"

    df["listing_date"] = None
    df["_file_creation"] = file_creation

    return df, file_creation


# Patterns that indicate non-common-stock suffixes
SUFFIX_PATTERN = re.compile(
    r"""
    \.   # dot separator (e.g., BRK.A is OK, but handle warrants)
    |    # OR
    [A-Z]{1,3}\.  # class shares (BRK.A, etc.) -- actually keep these
    """,
    re.VERBOSE,
)

# Warrant/rights/unit ticker suffixes (appended without dot or with W/R/U at end)
WARRANT_SUFFIX = re.compile(r'^[A-Z]+[WRU]$', re.IGNORECASE)

# More precise: tickers ending in W, R, or U where there's a base part
NONSTOCK_TICKER = re.compile(r'^[A-Z]{1,5}(W|R|U|WS|RT|WT)$', re.IGNORECASE)

# Name-based filters
NONSTOCK_NAME_PATTERN = re.compile(
    r'\b(warrant|warrants|right|rights|unit|units|acquisition corp|spac)\b',
    re.IGNORECASE,
)


def is_common_stock(row: pd.Series) -> bool:
    """Return True if this row looks like a common stock (not ETF, warrant, right, unit)."""
    ticker = str(row.get("ticker", "")).strip()
    name = str(row.get("company_name", "")).strip()

    # Skip ETFs
    if str(row.get("etf", "")).strip().upper() == "Y":
        return False

    # Skip test issues
    if str(row.get("test_issue", "")).strip().upper() == "Y":
        return False

    # Skip blank tickers
    if not ticker or ticker == "nan":
        return False

    # Skip tickers with $ (preferred shares often use $)
    if "$" in ticker:
        return False

    # Skip tickers with ^ (indices)
    if "^" in ticker:
        return False

    # Skip tickers ending in common non-stock suffixes
    # Allow dots for class shares (BRK.A, BRK.B)
    # But warrants often end in W, WS, R, RT, U, WT
    base_no_dot = ticker.replace(".", "")
    if NONSTOCK_TICKER.match(base_no_dot) and len(base_no_dot) > 4:
        # Likely a warrant suffix — but only if ticker is longer than 4 chars
        # e.g., "ACMRW" (5 chars ending in W) = warrant
        # vs "NOW" (3 chars) = normal stock
        return False

    # More targeted: if ticker ends in W/R/U AND has >= 5 chars (base + suffix)
    if len(ticker) >= 5 and not "." in ticker:
        if ticker.endswith(("W", "WS", "R", "RT", "U", "WT")):
            return False

    # Name-based filter: warrants, rights, units
    if NONSTOCK_NAME_PATTERN.search(name):
        return False

    return True


def build_universe(nasdaq_content: str, other_content: str) -> tuple[list[dict], dict]:
    """Parse both files, combine, filter, return (records, stats)."""

    nasdaq_df, nasdaq_time = parse_nasdaq_listed(nasdaq_content)
    other_df, other_time = parse_other_listed(other_content)

    # Keep only needed columns before combining
    keep_cols = ["ticker", "company_name", "exchange", "listing_date", "etf", "test_issue"]
    nasdaq_df = nasdaq_df[[c for c in keep_cols if c in nasdaq_df.columns]]
    other_df = other_df[[c for c in keep_cols if c in other_df.columns]]

    combined = pd.concat([nasdaq_df, other_df], ignore_index=True)

    total_raw = len(combined)
    console.log(f"Raw rows: [yellow]{total_raw:,}[/yellow]")

    # Apply filters
    mask = combined.apply(is_common_stock, axis=1)
    filtered = combined[mask].copy()

    # Deduplicate by ticker (NASDAQ file may overlap with other)
    filtered = filtered.drop_duplicates(subset=["ticker"], keep="first")

    # Clean up
    filtered["ticker"] = filtered["ticker"].str.strip()
    filtered["company_name"] = filtered["company_name"].str.strip()
    filtered["exchange"] = filtered["exchange"].str.strip()

    # Convert to records
    records = filtered[["ticker", "company_name", "exchange", "listing_date"]].to_dict(orient="records")

    # Stats
    exchange_counts = filtered["exchange"].value_counts().to_dict()
    stats = {
        "total_raw": total_raw,
        "total_filtered": len(filtered),
        "by_exchange": exchange_counts,
        "nasdaq_file_creation": nasdaq_time,
        "other_file_creation": other_time,
        "built_at": datetime.now().isoformat(),
    }

    return records, stats


def print_summary(stats: dict):
    """Print a rich summary table."""
    table = Table(title="US Stock Universe Summary", show_header=True, header_style="bold cyan")
    table.add_column("Exchange", style="cyan")
    table.add_column("Count", justify="right", style="green")

    by_exchange = dict(sorted(stats["by_exchange"].items(), key=lambda x: -x[1]))
    for exchange, count in by_exchange.items():
        table.add_row(exchange, f"{count:,}")

    table.add_section()
    table.add_row("[bold]TOTAL[/bold]", f"[bold]{stats['total_filtered']:,}[/bold]")

    console.print(table)
    console.print(f"\n  Raw rows downloaded: [dim]{stats['total_raw']:,}[/dim]")
    console.print(f"  NASDAQ file created: [dim]{stats.get('nasdaq_file_creation', 'N/A')}[/dim]")
    console.print(f"  Other file created:  [dim]{stats.get('other_file_creation', 'N/A')}[/dim]")
    console.print(f"  Built at: [dim]{stats['built_at']}[/dim]")


def main():
    parser = argparse.ArgumentParser(
        description="Build a US common stock universe from NASDAQ FTP symbol files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--min-cap",
        type=float,
        default=1.0,
        metavar="BILLIONS",
        help="Minimum market cap in billions (default: 1). "
             "NOTE: Market cap filtering not applied here (requires slow yfinance calls). "
             "This flag is accepted for CLI compatibility but ignored.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        metavar="FILE",
        help="Save output to JSON file (default: stdout)",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Force re-download from NASDAQ FTP (ignore cache)",
    )

    args = parser.parse_args()

    if args.min_cap != 1.0:
        console.log(
            "[yellow]Note: --min-cap is accepted but market cap filtering is not applied in this script "
            "(requires yfinance calls). Build the raw universe first, then filter by cap separately.[/yellow]"
        )

    console.rule("[bold cyan]US Stock Universe Builder[/bold cyan]")

    # Load files
    with console.status("Loading NASDAQ listed symbols..."):
        nasdaq_content = load_file(NASDAQ_URL, NASDAQ_CACHE, verify_ssl=True, refresh=args.refresh)

    with console.status("Loading other listed symbols..."):
        other_content = load_file(OTHER_URL, OTHER_CACHE, verify_ssl=False, refresh=args.refresh)

    # Build universe
    with console.status("Parsing and filtering..."):
        records, stats = build_universe(nasdaq_content, other_content)

    # Print summary
    console.print()
    print_summary(stats)
    console.print()

    # Output
    output = {
        "meta": stats,
        "universe": records,
    }

    if args.output:
        out_path = Path(args.output)
        out_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
        console.print(f"[green]Saved {len(records):,} stocks to {out_path}[/green]")
    else:
        print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()

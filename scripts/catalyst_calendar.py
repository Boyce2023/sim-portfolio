# /// script
# requires-python = ">=3.11"
# dependencies = ["yfinance>=0.2.40", "lxml>=5.0", "rich>=13.0"]
# ///
"""
60-Day Catalyst Calendar Builder
Aggregates earnings, dividends, splits, FOMC, CPI, and NFP events.

Usage:
  uv run --script scripts/catalyst_calendar.py
  uv run --script scripts/catalyst_calendar.py --ticker NVDA
  uv run --script scripts/catalyst_calendar.py --portfolio
  uv run --script scripts/catalyst_calendar.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yfinance as yf
from rich.console import Console
from rich.table import Table
from rich import box
from rich.text import Text

# ─── Paths ────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
PORTFOLIO_PATH = REPO_ROOT / "portfolio_state.json"

CONSOLE = Console()

# ─── Fixed macro events ───────────────────────────────────────────────────────
# FOMC meeting end dates (decision day) 2026
FOMC_DATES_2026: list[tuple[date, str]] = [
    (date(2026, 6, 18), "FOMC Jun 17-18"),
    (date(2026, 7, 30), "FOMC Jul 29-30"),
    (date(2026, 9, 17), "FOMC Sep 16-17"),
    (date(2026, 10, 29), "FOMC Oct 28-29"),
    (date(2026, 12, 10), "FOMC Dec 9-10"),
]

# CPI release dates 2026 (BLS typically releases ~13th of month at 8:30 ET)
CPI_DATES_2026: list[tuple[date, str]] = [
    (date(2026, 6, 11), "CPI May 2026"),
    (date(2026, 7, 14), "CPI Jun 2026"),
    (date(2026, 8, 12), "CPI Jul 2026"),
    (date(2026, 9, 11), "CPI Aug 2026"),
    (date(2026, 10, 13), "CPI Sep 2026"),
    (date(2026, 11, 12), "CPI Oct 2026"),
    (date(2026, 12, 11), "CPI Nov 2026"),
]

# NFP (Non-Farm Payroll) — first Friday of each month 2026
# BLS releases at 8:30 ET, report covers previous month
NFP_DATES_2026: list[tuple[date, str]] = [
    (date(2026, 6, 5),  "NFP May 2026"),
    (date(2026, 7, 2),  "NFP Jun 2026"),
    (date(2026, 8, 7),  "NFP Jul 2026"),
    (date(2026, 9, 4),  "NFP Aug 2026"),
    (date(2026, 10, 2), "NFP Sep 2026"),
    (date(2026, 11, 6), "NFP Oct 2026"),
    (date(2026, 12, 4), "NFP Nov 2026"),
]


# ─── Data types ───────────────────────────────────────────────────────────────
class CatalystEvent:
    def __init__(
        self,
        event_date: date,
        event_type: str,       # EARNINGS | DIVIDEND | SPLIT | FOMC | CPI | NFP
        ticker: str,           # ticker symbol or "MACRO"
        source: str,           # company name or macro source
        detail: str,
    ):
        self.event_date = event_date
        self.event_type = event_type
        self.ticker = ticker
        self.source = source
        self.detail = detail

    @property
    def days_away(self) -> int:
        return (self.event_date - date.today()).days

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.event_date.isoformat(),
            "event_type": self.event_type,
            "ticker": self.ticker,
            "source": self.source,
            "detail": self.detail,
            "days_away": self.days_away,
        }


# ─── Portfolio loader ──────────────────────────────────────────────────────────
def load_us_positions() -> list[dict]:
    """Read US long positions from portfolio_state.json."""
    if not PORTFOLIO_PATH.exists():
        CONSOLE.print(f"[red]ERROR: portfolio_state.json not found at {PORTFOLIO_PATH}[/red]")
        return []

    with open(PORTFOLIO_PATH) as f:
        state = json.load(f)

    us = state.get("accounts", {}).get("us", {})
    positions = us.get("positions", [])
    return [p for p in positions if p.get("ticker")]


# ─── yfinance helpers ──────────────────────────────────────────────────────────
def _to_date(val: Any) -> date | None:
    """Convert various yfinance date types to date."""
    if val is None:
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, int):
        # Unix timestamp
        try:
            return date.fromtimestamp(val)
        except (OSError, OverflowError, ValueError):
            return None
    if isinstance(val, str):
        try:
            return date.fromisoformat(val[:10])
        except ValueError:
            return None
    return None


def fetch_ticker_events(ticker: str, name: str, today: date, horizon: date) -> list[CatalystEvent]:
    """Fetch earnings, dividend, and split events for a single ticker."""
    events: list[CatalystEvent] = []
    t = yf.Ticker(ticker)

    # ── 1. Earnings date ──────────────────────────────────────────────────────
    earnings_date: date | None = None
    earnings_detail = ""
    try:
        ed = t.earnings_dates
        if ed is not None and not ed.empty:
            now_utc = datetime.now(timezone.utc)
            future = ed[ed.index > now_utc]
            if not future.empty:
                ts = future.index[0]
                earnings_date = ts.date() if hasattr(ts, "date") else _to_date(ts)
                eps_est = future.iloc[0].get("EPS Estimate")
                if eps_est is not None and str(eps_est) != "nan":
                    earnings_detail = f"EPS est: ${float(eps_est):.2f}"
    except Exception:
        pass

    # Fallback: calendar
    if earnings_date is None:
        try:
            cal = t.calendar
            if cal and "Earnings Date" in cal:
                raw = cal["Earnings Date"]
                raw_date = raw[0] if isinstance(raw, list) and raw else raw
                earnings_date = _to_date(raw_date)
                if cal.get("Earnings Average") and not earnings_detail:
                    earnings_detail = f"EPS est avg: ${float(cal['Earnings Average']):.2f}"
        except Exception:
            pass

    if earnings_date and today <= earnings_date <= horizon:
        events.append(CatalystEvent(
            event_date=earnings_date,
            event_type="EARNINGS",
            ticker=ticker,
            source=name,
            detail=earnings_detail or "Next earnings",
        ))

    # ── 2. Ex-dividend date ──────────────────────────────────────────────────
    ex_div: date | None = None
    div_detail = ""
    try:
        cal = t.calendar
        if cal:
            ex_div = _to_date(cal.get("Ex-Dividend Date"))
            div_dt = _to_date(cal.get("Dividend Date"))
            info = t.info
            div_rate = info.get("dividendRate") or info.get("lastDividendValue")
            if div_rate:
                div_detail = f"${float(div_rate):.4f}/share annualized"
    except Exception:
        pass

    if ex_div is None:
        try:
            info = t.info
            ex_div = _to_date(info.get("exDividendDate"))
        except Exception:
            pass

    if ex_div and today <= ex_div <= horizon:
        events.append(CatalystEvent(
            event_date=ex_div,
            event_type="DIVIDEND",
            ticker=ticker,
            source=name,
            detail=f"Ex-div date. {div_detail}".strip(". ") if div_detail else "Ex-dividend date",
        ))

    # ── 3. Stock splits ──────────────────────────────────────────────────────
    try:
        splits = t.splits
        if splits is not None and not splits.empty:
            import pandas as pd
            horizon_ts = pd.Timestamp(horizon, tz="UTC")
            today_ts = pd.Timestamp(today, tz="UTC")
            # splits index may be tz-aware or naive
            try:
                future_splits = splits[splits.index >= today_ts]
                future_splits = future_splits[future_splits.index <= horizon_ts]
            except TypeError:
                # tz-naive index — convert
                today_ts_naive = pd.Timestamp(today)
                horizon_ts_naive = pd.Timestamp(horizon)
                future_splits = splits[(splits.index >= today_ts_naive) & (splits.index <= horizon_ts_naive)]

            for ts_idx, ratio in future_splits.items():
                split_date = ts_idx.date() if hasattr(ts_idx, "date") else _to_date(ts_idx)
                if split_date:
                    events.append(CatalystEvent(
                        event_date=split_date,
                        event_type="SPLIT",
                        ticker=ticker,
                        source=name,
                        detail=f"{int(ratio)}:1 stock split",
                    ))
    except Exception:
        pass

    return events


# ─── Macro events ─────────────────────────────────────────────────────────────
def build_macro_events(today: date, horizon: date) -> list[CatalystEvent]:
    events: list[CatalystEvent] = []

    for evt_date, label in FOMC_DATES_2026:
        if today <= evt_date <= horizon:
            events.append(CatalystEvent(
                event_date=evt_date,
                event_type="FOMC",
                ticker="MACRO",
                source="Federal Reserve",
                detail=f"{label} — rate decision + press conference",
            ))

    for evt_date, label in CPI_DATES_2026:
        if today <= evt_date <= horizon:
            events.append(CatalystEvent(
                event_date=evt_date,
                event_type="CPI",
                ticker="MACRO",
                source="BLS",
                detail=f"{label} — 8:30 ET release",
            ))

    for evt_date, label in NFP_DATES_2026:
        if today <= evt_date <= horizon:
            events.append(CatalystEvent(
                event_date=evt_date,
                event_type="NFP",
                ticker="MACRO",
                source="BLS",
                detail=f"{label} — 8:30 ET release",
            ))

    return events


# ─── Grouping ──────────────────────────────────────────────────────────────────
def group_label(evt: CatalystEvent, today: date) -> str:
    days = evt.days_away
    week_end = today + timedelta(days=6 - today.weekday())  # end of this week (Sunday)
    next_week_end = week_end + timedelta(days=7)

    if evt.event_date <= week_end:
        return "This Week"
    elif evt.event_date <= next_week_end:
        return "Next Week"
    elif days <= 30:
        return "Next 30 Days"
    else:
        return "30-60 Days"


GROUP_ORDER = ["This Week", "Next Week", "Next 30 Days", "30-60 Days"]

EVENT_COLORS = {
    "EARNINGS": "bright_yellow",
    "DIVIDEND": "bright_green",
    "SPLIT":    "bright_cyan",
    "FOMC":     "bright_red",
    "CPI":      "orange1",
    "NFP":      "orange3",
}

EVENT_ICONS = {
    "EARNINGS": "📊",
    "DIVIDEND": "💰",
    "SPLIT":    "✂️ ",
    "FOMC":     "🏛️ ",
    "CPI":      "📈",
    "NFP":      "👷",
}


# ─── Display ──────────────────────────────────────────────────────────────────
def render_table(events: list[CatalystEvent], today: date) -> None:
    if not events:
        CONSOLE.print("\n[yellow]No catalyst events found in the 60-day window.[/yellow]\n")
        return

    # Group events
    from collections import defaultdict
    groups: dict[str, list[CatalystEvent]] = defaultdict(list)
    for evt in events:
        groups[group_label(evt, today)].append(evt)

    CONSOLE.print()
    CONSOLE.print(
        f"[bold bright_white] ⚡ 60-Day Catalyst Calendar[/bold bright_white]  "
        f"[dim]{today.strftime('%Y-%m-%d')} → {(today + timedelta(days=60)).strftime('%Y-%m-%d')}[/dim]"
    )
    CONSOLE.print()

    for group_name in GROUP_ORDER:
        group_events = groups.get(group_name)
        if not group_events:
            continue

        # Sort by date within group
        group_events.sort(key=lambda e: e.event_date)

        table = Table(
            title=f"[bold]{group_name}[/bold]",
            box=box.SIMPLE_HEAD,
            show_header=True,
            header_style="bold dim",
            title_style="bold bright_white",
            title_justify="left",
            pad_edge=False,
            show_footer=False,
        )
        table.add_column("Date", style="bright_white", width=12, no_wrap=True)
        table.add_column("Type", width=10, no_wrap=True)
        table.add_column("Ticker", width=8, no_wrap=True)
        table.add_column("Source", width=26)
        table.add_column("Detail", min_width=36)
        table.add_column("Days", width=7, justify="right")

        for evt in group_events:
            color = EVENT_COLORS.get(evt.event_type, "white")
            icon = EVENT_ICONS.get(evt.event_type, "•")
            days = evt.days_away

            if days == 0:
                days_str = "[bold red]TODAY[/bold red]"
            elif days == 1:
                days_str = "[bold yellow]1d[/bold yellow]"
            elif days <= 7:
                days_str = f"[yellow]{days}d[/yellow]"
            else:
                days_str = f"[dim]{days}d[/dim]"

            type_cell = Text()
            type_cell.append(f"{icon} ", style="")
            type_cell.append(evt.event_type, style=color)

            table.add_row(
                evt.event_date.strftime("%Y-%m-%d"),
                type_cell,
                f"[bold]{evt.ticker}[/bold]" if evt.ticker != "MACRO" else "[dim]MACRO[/dim]",
                evt.source,
                evt.detail,
                days_str,
            )

        CONSOLE.print(table)

    # Legend
    CONSOLE.print(
        "[dim]Legend: [bright_yellow]EARNINGS[/bright_yellow] | "
        "[bright_green]DIVIDEND[/bright_green] | "
        "[bright_cyan]SPLIT[/bright_cyan] | "
        "[bright_red]FOMC[/bright_red] | "
        "[orange1]CPI[/orange1] | "
        "[orange3]NFP[/orange3][/dim]"
    )
    CONSOLE.print()


# ─── Main ─────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="60-Day Catalyst Calendar Builder",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uv run --script scripts/catalyst_calendar.py
  uv run --script scripts/catalyst_calendar.py --ticker NVDA AVGO
  uv run --script scripts/catalyst_calendar.py --portfolio
  uv run --script scripts/catalyst_calendar.py --json
        """,
    )
    parser.add_argument(
        "--ticker", nargs="+", metavar="TICKER",
        help="One or more tickers to check (default: all US portfolio positions)",
    )
    parser.add_argument(
        "--portfolio", action="store_true",
        help="Force load all US positions from portfolio_state.json",
    )
    parser.add_argument(
        "--days", type=int, default=60, metavar="N",
        help="Horizon in days (default: 60)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output raw JSON instead of Rich table",
    )
    parser.add_argument(
        "--no-macro", action="store_true",
        help="Suppress FOMC/CPI/NFP macro events",
    )
    args = parser.parse_args()

    today = date.today()
    horizon = today + timedelta(days=args.days)

    # ── Determine ticker list ─────────────────────────────────────────────────
    positions: list[dict] = []

    if args.ticker:
        # User-supplied tickers
        positions = [{"ticker": t.upper(), "name": t.upper()} for t in args.ticker]
    else:
        # Default: load from portfolio (--portfolio flag or no args at all)
        positions = load_us_positions()
        if not positions:
            CONSOLE.print("[red]No US positions found. Use --ticker XXXX or check portfolio_state.json[/red]")
            sys.exit(1)

    # ── Fetch ticker events ───────────────────────────────────────────────────
    all_events: list[CatalystEvent] = []

    if not args.json:
        CONSOLE.print(f"\n[dim]Fetching calendar data for {len(positions)} ticker(s)...[/dim]")

    for pos in positions:
        ticker = pos["ticker"].upper()
        name = pos.get("name", ticker)
        if not args.json:
            CONSOLE.print(f"  [dim]{ticker}[/dim] ({name})...", end=" ")

        try:
            events = fetch_ticker_events(ticker, name, today, horizon)
            all_events.extend(events)
            if not args.json:
                tags = [e.event_type for e in events]
                CONSOLE.print(f"[green]{', '.join(tags) if tags else 'no events'}[/green]")
        except Exception as exc:
            if not args.json:
                CONSOLE.print(f"[red]ERROR: {exc}[/red]")

    # ── Macro events ─────────────────────────────────────────────────────────
    if not args.no_macro:
        macro = build_macro_events(today, horizon)
        all_events.extend(macro)
        if not args.json and macro:
            CONSOLE.print(f"  [dim]MACRO[/dim] — added {len(macro)} FOMC/CPI/NFP events")

    # ── Sort all events by date ───────────────────────────────────────────────
    all_events.sort(key=lambda e: e.event_date)

    # ── Output ────────────────────────────────────────────────────────────────
    if args.json:
        output = {
            "generated_at": datetime.now().isoformat(),
            "today": today.isoformat(),
            "horizon": horizon.isoformat(),
            "days": args.days,
            "total_events": len(all_events),
            "events": [e.to_dict() for e in all_events],
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        render_table(all_events, today)

        # Summary counts
        from collections import Counter
        type_counts = Counter(e.event_type for e in all_events)
        summary_parts = [f"{v}×{k}" for k, v in sorted(type_counts.items())]
        CONSOLE.print(
            f"[dim]Total: {len(all_events)} events | "
            + " | ".join(summary_parts)
            + f" | horizon: {args.days} days[/dim]"
        )
        CONSOLE.print()


if __name__ == "__main__":
    main()

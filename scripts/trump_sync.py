#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "rich>=13.0",
# ]
# ///
"""
trump_sync.py — Read-only diagnostic tool.

Cross-references Trump/OGE holdings (truth/macro/trump_portfolio.json)
with the current sim-portfolio (portfolio_state.json).

Usage:
    uv run scripts/trump_sync.py
"""

import json
from datetime import date, datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

TRUMP_JSON = Path.home() / ".claude/nexus/truth/macro/trump_portfolio.json"
PORTFOLIO_JSON = Path(__file__).parent.parent / "portfolio_state.json"

console = Console()


def load_json(path: Path, label: str) -> dict:
    if not path.exists():
        console.print(f"[bold red]ERROR:[/bold red] {label} not found at {path}")
        raise SystemExit(1)
    with path.open() as f:
        return json.load(f)


def days_until(date_str: str) -> int:
    """Return calendar days from today until date_str (YYYY-MM-DD)."""
    target = date.fromisoformat(date_str)
    delta = target - date.today()
    return delta.days


def get_portfolio_tickers(portfolio: dict) -> dict[str, dict]:
    """Return {ticker: position_dict} for all live positions (market_value > 0)."""
    result = {}
    for account in portfolio.get("accounts", {}).values():
        for pos in account.get("positions", []):
            ticker = pos.get("ticker", "")
            mv = pos.get("market_value") or 0
            if mv > 0:
                result[ticker] = pos
    return result


def get_combined_nav(portfolio: dict) -> float:
    total = 0.0
    for account in portfolio.get("accounts", {}).values():
        total += account.get("total_assets") or 0
    return total


def fmt_usd(val: float) -> str:
    return f"${val:,.0f}"


def fmt_cny(val: float) -> str:
    return f"¥{val:,.0f}"


def main():
    trump_data = load_json(TRUMP_JSON, "trump_portfolio.json")
    portfolio = load_json(PORTFOLIO_JSON, "portfolio_state.json")

    meta = trump_data.get("_meta", {})
    holdings = trump_data.get("holdings", [])
    portfolio_tickers = get_portfolio_tickers(portfolio)
    combined_nav = get_combined_nav(portfolio)

    # ── Header ─────────────────────────────────────────────────────────────
    console.print()
    console.print(Panel(
        f"[bold white]Trump / OGE Portfolio Sync[/bold white]\n"
        f"[dim]Data: {meta.get('source', 'N/A')} | "
        f"Last updated: {meta.get('last_updated', 'N/A')} | "
        f"Q1 trades: {meta.get('total_trades_q1', 'N/A')} | "
        f"Est. value: {meta.get('total_value_range', 'N/A')}[/dim]",
        box=box.DOUBLE,
        style="bold cyan",
    ))

    # ── Section 1: Overlap table ────────────────────────────────────────────
    console.print("\n[bold yellow]1. Portfolio × Trump Holdings Overlap[/bold yellow]")

    overlap_table = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold")
    overlap_table.add_column("Ticker", style="bold white", width=8)
    overlap_table.add_column("Name", width=26)
    overlap_table.add_column("Promoted?", justify="center", width=10)
    overlap_table.add_column("Trump Amount", justify="right", width=14)
    overlap_table.add_column("Trump Confidence", justify="center", width=16)
    overlap_table.add_column("Our MV (USD)", justify="right", width=14)
    overlap_table.add_column("% of US NAV", justify="right", width=12)

    us_nav = portfolio["accounts"]["us"].get("total_assets") or 0
    overlaps = []

    for h in holdings:
        ticker = h["ticker"]
        if ticker in portfolio_tickers:
            pos = portfolio_tickers[ticker]
            mv = pos.get("market_value") or 0
            nav_pct = (mv / us_nav * 100) if us_nav > 0 else 0
            promoted = h.get("promoted", False)
            conf = h.get("confidence", "?")

            promoted_str = "[green]YES[/green]" if promoted else "[dim]no[/dim]"
            conf_color = {"high": "green", "medium": "yellow", "low": "red"}.get(conf, "white")

            overlap_table.add_row(
                ticker,
                pos.get("name", ""),
                promoted_str,
                h.get("amount_range", "unknown"),
                f"[{conf_color}]{conf}[/{conf_color}]",
                fmt_usd(mv),
                f"{nav_pct:.1f}%",
            )
            overlaps.append((ticker, mv, h))

    if overlaps:
        console.print(overlap_table)
    else:
        console.print("  [dim]No overlap found between portfolio and Trump holdings.[/dim]")

    # ── Section 2: Next shoutout candidates ────────────────────────────────
    console.print("\n[bold yellow]2. Next Shoutout Candidates (Trump Holdings NOT Yet Promoted)[/bold yellow]")
    console.print("[dim]Ranked by Trump trade count signal and confidence[/dim]\n")

    candidates = [h for h in holdings if not h.get("promoted", True)]

    # Pull in watchlist_next_shoutout ordering from the JSON for ranking
    watchlist_order = trump_data.get("watchlist_next_shoutout", [])

    def candidate_rank(h):
        ticker = h["ticker"]
        try:
            order_rank = watchlist_order.index(ticker)
        except ValueError:
            order_rank = 999
        conf_score = {"high": 0, "medium": 1, "low": 2}.get(h.get("confidence", "low"), 3)
        # ORCL note says 17 trades — extract trade count hint from notes
        notes = h.get("notes", "")
        trade_hint = 17 if "ORCL" in ticker else 0
        return (conf_score, order_rank, -trade_hint)

    candidates.sort(key=candidate_rank)

    cand_table = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold")
    cand_table.add_column("Rank", justify="center", width=6)
    cand_table.add_column("Ticker", style="bold white", width=8)
    cand_table.add_column("Trump Amount", justify="right", width=14)
    cand_table.add_column("Buy Period", width=12)
    cand_table.add_column("Confidence", justify="center", width=12)
    cand_table.add_column("In Our Portfolio?", justify="center", width=18)
    cand_table.add_column("Notes", width=40)

    for rank, h in enumerate(candidates, 1):
        ticker = h["ticker"]
        conf = h.get("confidence", "?")
        conf_color = {"high": "green", "medium": "yellow", "low": "red"}.get(conf, "white")
        in_portfolio = ticker in portfolio_tickers
        in_port_str = "[bold green]YES — WATCH[/bold green]" if in_portfolio else "[dim]no[/dim]"
        buy_dates = h.get("buy_dates", [])
        buy_str = ", ".join(buy_dates) if buy_dates else "unknown"

        cand_table.add_row(
            f"#{rank}",
            ticker,
            h.get("amount_range", "unknown"),
            buy_str,
            f"[{conf_color}]{conf}[/{conf_color}]",
            in_port_str,
            h.get("notes", "—"),
        )

    console.print(cand_table)

    # ── Section 3: OGE disclosure countdown ────────────────────────────────
    console.print("\n[bold yellow]3. OGE Disclosure Countdown[/bold yellow]")

    next_disclosure = meta.get("next_disclosure_expected")
    if next_disclosure:
        days_left = days_until(next_disclosure)
        color = "red" if days_left < 14 else ("yellow" if days_left < 45 else "green")
        console.print(
            f"  Next OGE disclosure expected: [bold]{next_disclosure}[/bold]  "
            f"([{color}]{days_left} days from today[/{color}])"
        )
        stale_after = meta.get("stale_after_days", 90)
        last_updated = meta.get("last_updated", "unknown")
        console.print(f"  Current data last updated: {last_updated} | Stale after {stale_after} days")
        console.print(
            f"  [dim]Pattern avg lag buy→event: {trump_data.get('pattern_summary', {}).get('avg_lag_days', 'N/A')} | "
            f"Avg stock reaction: {trump_data.get('pattern_summary', {}).get('avg_stock_reaction', 'N/A')}[/dim]"
        )
    else:
        console.print("  [dim]next_disclosure_expected not set in trump_portfolio.json[/dim]")

    # ── Section 4: Regulatory risk summary ─────────────────────────────────
    console.print("\n[bold yellow]4. Regulatory Risk Summary (Trump Overlap as % of Combined NAV)[/bold yellow]")

    risk_table = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold")
    risk_table.add_column("Ticker", style="bold white", width=8)
    risk_table.add_column("Name", width=26)
    risk_table.add_column("Market Value (USD)", justify="right", width=20)
    risk_table.add_column("% Combined NAV", justify="right", width=16)
    risk_table.add_column("Promoted?", justify="center", width=10)
    risk_table.add_column("Risk Flag", justify="center", width=12)

    total_overlap_mv = 0.0
    for ticker, mv, h in overlaps:
        pct_nav = (mv / combined_nav * 100) if combined_nav > 0 else 0
        total_overlap_mv += mv
        promoted = h.get("promoted", False)
        # Risk flag: promoted + large position = elevated
        if promoted and pct_nav > 2.0:
            flag = "[bold red]HIGH[/bold red]"
        elif promoted:
            flag = "[yellow]MEDIUM[/yellow]"
        else:
            flag = "[green]LOW[/green]"

        risk_table.add_row(
            ticker,
            portfolio_tickers[ticker].get("name", ""),
            fmt_usd(mv),
            f"{pct_nav:.2f}%",
            "[green]YES[/green]" if promoted else "[dim]no[/dim]",
            flag,
        )

    total_pct = (total_overlap_mv / combined_nav * 100) if combined_nav > 0 else 0
    risk_table.add_section()
    risk_table.add_row(
        "[bold]TOTAL[/bold]", "", fmt_usd(total_overlap_mv),
        f"[bold]{total_pct:.2f}%[/bold]", "", ""
    )

    console.print(risk_table)

    pattern = trump_data.get("pattern_summary", {})
    risk_note = pattern.get("risk", "")
    defense = pattern.get("defense", "")
    if risk_note or defense:
        console.print(f"\n  [dim]Regulatory: {risk_note}[/dim]")
        console.print(f"  [dim]Trump team defense: {defense}[/dim]")

    console.print()


if __name__ == "__main__":
    main()

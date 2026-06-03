#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
signal_consumer.py — Nexus signal reader and optional consumer.

Reads pending sig-*.json from ~/.claude/nexus/signals/pending/,
cross-references affected tickers with portfolio_state.json,
and optionally marks signals as consumed (lifecycle=acted_on)
and moves them to signals/processed/.

Usage:
    uv run scripts/signal_consumer.py           # read-only display
    uv run scripts/signal_consumer.py --consume  # display + mark as consumed
"""

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

SIGNALS_PENDING = Path.home() / ".claude/nexus/signals/pending"
SIGNALS_PROCESSED = Path.home() / ".claude/nexus/signals/processed"
PORTFOLIO_JSON = Path(__file__).parent.parent / "portfolio_state.json"

# ANSI colour helpers (no external deps)
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
WHITE = "\033[97m"
BG_DARK = "\033[40m"


def c(text: str, *codes: str) -> str:
    return "".join(codes) + str(text) + RESET


def load_json(path: Path, label: str) -> dict:
    if not path.exists():
        print(c(f"ERROR: {label} not found at {path}", BOLD, RED))
        raise SystemExit(1)
    with path.open() as f:
        return json.load(f)


def get_portfolio_tickers(portfolio: dict) -> dict[str, dict]:
    """Return {ticker: position_dict} for all live positions (market_value > 0)."""
    result: dict[str, dict] = {}
    for account in portfolio.get("accounts", {}).values():
        for pos in account.get("positions", []):
            ticker = pos.get("ticker", "")
            mv = pos.get("market_value") or 0
            if mv > 0:
                result[ticker] = pos
    return result


def priority_color(p: str) -> str:
    return {
        "critical": c(p.upper(), BOLD, RED),
        "high": c(p.upper(), BOLD, YELLOW),
        "medium": c(p.upper(), CYAN),
        "low": c(p, DIM),
    }.get(p.lower(), p)


def sep(char: str = "─", width: int = 80) -> str:
    return c(char * width, DIM)


def load_signals() -> list[tuple[Path, dict]]:
    """Return list of (path, data) for all sig-*.json in pending/."""
    if not SIGNALS_PENDING.exists():
        print(c(f"WARNING: Signals directory not found: {SIGNALS_PENDING}", YELLOW))
        return []
    files = sorted(SIGNALS_PENDING.glob("sig-*.json"))
    results = []
    for f in files:
        try:
            with f.open() as fh:
                data = json.load(fh)
            results.append((f, data))
        except json.JSONDecodeError as e:
            print(c(f"  SKIP (invalid JSON): {f.name} — {e}", DIM, RED))
    return results


def get_affected_tickers(signal: dict) -> list[str]:
    """Extract tickers from any of the known field locations."""
    tickers: list[str] = []
    # Top-level affected_tickers
    tickers.extend(signal.get("affected_tickers") or [])
    # context.affected_tickers
    ctx = signal.get("context") or {}
    tickers.extend(ctx.get("affected_tickers") or [])
    # payload has no standard ticker field — skip
    return list(dict.fromkeys(t.upper() for t in tickers if t))  # deduplicate, preserve order


def is_action_required(signal: dict) -> bool:
    """action_required can be True (bool) or a non-empty string."""
    val = signal.get("action_required")
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return bool(val.strip())
    return False


def consume_signal(path: Path, signal: dict) -> bool:
    """Mark signal as acted_on and move to processed/. Returns True on success."""
    SIGNALS_PROCESSED.mkdir(parents=True, exist_ok=True)

    now_iso = datetime.now(timezone.utc).isoformat()
    signal["lifecycle"] = "acted_on"
    signal["acted_on"] = True
    signal["acted_at"] = now_iso
    signal["acted_on_at"] = now_iso

    try:
        with path.open("w") as f:
            json.dump(signal, f, indent=2, ensure_ascii=False)
        dest = SIGNALS_PROCESSED / path.name
        shutil.move(str(path), str(dest))
        return True
    except OSError as e:
        print(c(f"  ERROR moving {path.name}: {e}", RED))
        return False


def fmt_mv(pos: dict) -> str:
    mv = pos.get("market_value") or 0
    name = pos.get("name", "")
    pct = pos.get("portfolio_pct") or 0
    currency = "USD" if pos.get("ticker", "").isalpha() and len(pos.get("ticker", "")) <= 5 else "CNY"
    sym = "$" if currency == "USD" else "¥"
    return f"{name} | {sym}{mv:,.0f} | {pct*100:.1f}% port"


def print_signal(idx: int, path: Path, signal: dict, portfolio_tickers: dict[str, dict]):
    action_req = is_action_required(signal)
    priority = signal.get("priority", "?")
    sig_type = signal.get("type", "?")
    title = signal.get("title") or signal.get("payload", {}).get("note", "(no title)")
    created = signal.get("created_at", "?")
    expires = signal.get("expires_at", "?")
    from_ws = signal.get("from", "?")
    to_ws = signal.get("to", [])
    lifecycle = signal.get("lifecycle", "pending")
    body = signal.get("body") or signal.get("content") or ""
    action_text = signal.get("action_required") if isinstance(signal.get("action_required"), str) else ""

    affected = get_affected_tickers(signal)
    port_overlap = [(t, portfolio_tickers[t]) for t in affected if t in portfolio_tickers]

    # Signal header
    req_badge = c(" ACTION REQUIRED ", BOLD, RED, BG_DARK) if action_req else c(" info ", DIM)
    print(f"\n{sep()}")
    print(f"  {c(f'[{idx}]', BOLD, WHITE)} {req_badge}  {priority_color(priority)}  {c(sig_type, CYAN)}")
    print(f"  {c('Title:', BOLD)} {title}")
    print(f"  {c('ID:', DIM)} {signal.get('id', path.stem)}")
    print(f"  {c('From:', DIM)} {from_ws}  →  {c('To:', DIM)} {', '.join(to_ws) if to_ws else '?'}")
    print(f"  {c('Created:', DIM)} {created}   {c('Expires:', DIM)} {expires}   {c('Lifecycle:', DIM)} {lifecycle}")

    if affected:
        print(f"  {c('Affected tickers:', BOLD)} {', '.join(c(t, BOLD, WHITE) for t in affected)}")
    if body:
        # Print body wrapped loosely
        lines = body.strip().split("\n")
        print(f"  {c('Body:', BOLD)}")
        for line in lines[:8]:  # cap at 8 lines for readability
            print(f"    {line}")
        if len(lines) > 8:
            print(f"    {c(f'... ({len(lines)-8} more lines)', DIM)}")

    if action_text and isinstance(action_text, str):
        print(f"  {c('Action:', BOLD, YELLOW)} {action_text}")

    # Portfolio overlap
    if port_overlap:
        print(f"\n  {c('Portfolio overlap:', BOLD, GREEN)}")
        for ticker, pos in port_overlap:
            print(f"    {c(ticker, BOLD, GREEN)}  {fmt_mv(pos)}")
    elif affected:
        print(f"\n  {c('Portfolio overlap:', DIM)} none of {', '.join(affected)} in current positions")


def main():
    parser = argparse.ArgumentParser(
        description="Read and optionally consume Nexus pending signals."
    )
    parser.add_argument(
        "--consume",
        action="store_true",
        help="Mark displayed action-required signals as acted_on and move to processed/",
    )
    args = parser.parse_args()

    # Load portfolio
    portfolio = load_json(PORTFOLIO_JSON, "portfolio_state.json")
    portfolio_tickers = get_portfolio_tickers(portfolio)

    # Load signals
    all_signals = load_signals()

    if not all_signals:
        print(c("No pending signals found.", DIM))
        return

    # Separate action-required vs informational
    action_signals = [(p, s) for p, s in all_signals if is_action_required(s)]
    info_signals = [(p, s) for p, s in all_signals if not is_action_required(s)]

    print(c("\n" + "═" * 80, CYAN))
    print(c("  NEXUS SIGNAL CONSUMER", BOLD, WHITE))
    print(c(f"  Pending: {len(all_signals)} total | "
            f"{len(action_signals)} action-required | "
            f"{len(info_signals)} informational", DIM))
    print(c(f"  Portfolio tickers: {', '.join(sorted(portfolio_tickers.keys()))}", DIM))
    print(c("═" * 80, CYAN))

    # Print action-required signals first
    if action_signals:
        print(c("\n ACTION-REQUIRED SIGNALS", BOLD, YELLOW))
        for idx, (path, signal) in enumerate(action_signals, 1):
            print_signal(idx, path, signal, portfolio_tickers)
    else:
        print(c("\n  No action-required signals.", DIM))

    # Print informational signals
    if info_signals:
        print(c(f"\n INFORMATIONAL SIGNALS ({len(info_signals)})", BOLD, DIM))
        for idx, (path, signal) in enumerate(info_signals, len(action_signals) + 1):
            print_signal(idx, path, signal, portfolio_tickers)

    print(f"\n{sep()}\n")

    # Consume logic
    if args.consume:
        targets = action_signals  # only consume action-required by default
        if not targets:
            print(c("Nothing to consume (no action-required signals).", DIM))
            return

        print(c(f"Consuming {len(targets)} action-required signal(s)...\n", BOLD, YELLOW))
        consumed = 0
        for path, signal in targets:
            ok = consume_signal(path, signal)
            status = c("MOVED to processed/", GREEN) if ok else c("FAILED", RED)
            print(f"  {path.name}  {status}")
            if ok:
                consumed += 1

        print(c(f"\nDone: {consumed}/{len(targets)} signals consumed.", BOLD))
    else:
        # Interactive prompt only when stdout is a terminal
        if sys.stdout.isatty() and action_signals:
            print(c("Run with --consume to mark action-required signals as acted_on and move to processed/.", DIM))


if __name__ == "__main__":
    main()

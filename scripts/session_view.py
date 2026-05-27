# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
session_view.py — Generate a slim, market-specific view of portfolio_state.json.

Loads only the relevant market's data per session, stripping out verbose text
fields and historical snapshots to reduce context window consumption.

Usage:
  uv run --script scripts/session_view.py --market us    # ~5K tokens
  uv run --script scripts/session_view.py --market cn    # ~4K tokens
  uv run --script scripts/session_view.py --market all   # both markets trimmed

Output:
  - Prints JSON to stdout (for piping/redirection)
  - Also writes session_view_{market}.json in the repo root

Target sizes:
  US view  < 10 KB
  CN view  < 8  KB
"""

import json
import sys
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).parent.parent
STATE_FILE = REPO_ROOT / "portfolio_state.json"

MARKET_ACCOUNT_MAP = {
    "us": "us",
    "cn": "a_share",
}

ACCOUNT_FILTER_MAP = {
    "us": {"include": "us", "exclude": "a_share"},
    "cn": {"include": "a_share", "exclude": "us"},
}

THESIS_TRUNCATE = 50   # chars to keep when full thesis is present
REASON_TRUNCATE = 60   # chars to keep from trade log reason field
TRADE_LOG_MAX   = 15   # max recent trades to include per market


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cutoff_7d() -> str:
    """ISO date string 7 days ago (UTC+8)."""
    tz_cn = timezone(timedelta(hours=8))
    cutoff = datetime.now(tz_cn) - timedelta(days=7)
    return cutoff.strftime("%Y-%m-%d")


def _strip_position(pos: dict) -> dict:
    """Remove verbose narrative fields from a position dict."""
    stripped = {k: v for k, v in pos.items()}

    # Replace full thesis with truncated version
    thesis = stripped.pop("thesis", None)
    if thesis:
        stripped["thesis_short"] = thesis[:THESIS_TRUNCATE] + ("…" if len(thesis) > THESIS_TRUNCATE else "")

    # Remove bear_case body text but keep the numeric downside
    stripped.pop("bear_case", None)

    # Remove the verbose ATR note (already redundant with stop_loss)
    stripped.pop("stop_loss_note", None)

    # Remove catalyst_action (verbose; catalyst date already retained)
    stripped.pop("catalyst_action", None)

    return stripped


def _trim_trade(t: dict) -> dict:
    """Truncate the verbose `reason` field of a trade log entry."""
    out = dict(t)
    reason = out.get("reason", "")
    if reason and len(reason) > REASON_TRUNCATE:
        out["reason"] = reason[:REASON_TRUNCATE] + "…"
    return out


def _filter_trade_log(trade_log: list, account_key: str, cutoff: str) -> list:
    """Return trimmed trades for `account_key` in the last 7 days (max TRADE_LOG_MAX)."""
    filtered = [
        _trim_trade(t) for t in trade_log
        if t.get("account") == account_key
        and t.get("date", "") >= cutoff
    ]
    # Most recent first, then cap
    return filtered[-TRADE_LOG_MAX:]


def _build_account_view(state: dict, account_key: str) -> dict:
    """Return a trimmed dict for one account."""
    account_raw = state.get("accounts", {}).get(account_key, {})

    # Strip cash_plan (inline per position) — it's available separately
    account = {k: v for k, v in account_raw.items() if k != "cash_plan"}

    # Trim positions
    positions_raw = account.get("positions", [])
    account["positions"] = [_strip_position(p) for p in positions_raw]

    # Trim short_positions if present
    shorts_raw = account.get("short_positions", [])
    if shorts_raw:
        account["short_positions"] = [_strip_position(p) for p in shorts_raw]

    return account


def _build_pending_actions(state: dict, account_key: str) -> list:
    """Return only active (non-completed) pending_orders for the account."""
    orders = state.get("pending_orders", [])
    return [o for o in orders if o.get("account") == account_key]


def _build_catalyst_calendar(state: dict, account_key: str) -> list:
    """Return catalyst events relevant to the account.

    Uses account_key to infer market: 'us' → US tickers (non-CN format),
    'a_share' → CN tickers (all-digit or starts with 6/0/3).
    """
    calendar = state.get("catalyst_calendar_30d", [])
    if account_key == "a_share":
        return [e for e in calendar if _is_cn_ticker(e.get("ticker", ""))]
    else:
        return [e for e in calendar if not _is_cn_ticker(e.get("ticker", ""))]


def _is_cn_ticker(ticker: str) -> bool:
    return ticker.isdigit() or (len(ticker) == 6 and ticker[:1] in ("0", "3", "6"))


def _build_cash_plan(state: dict, account_key: str) -> dict:
    """Return the cash plan for the account."""
    return state.get("cash_plan", {}).get(account_key, {})


# ---------------------------------------------------------------------------
# View builders
# ---------------------------------------------------------------------------

def build_view(state: dict, market: str) -> dict:
    """Build a slim view for a single market ('us' or 'cn')."""
    account_key = MARKET_ACCOUNT_MAP[market]
    cutoff = _cutoff_7d()

    view = {
        "_meta": {
            **state.get("_meta", {}),
            "_view_generated": datetime.now(timezone(timedelta(hours=8))).isoformat(),
            "_view_market": market,
            "_view_trade_log_cutoff": cutoff,
            "_source": "portfolio_state.json (slim view — verbose fields stripped)",
        },
        "account": _build_account_view(state, account_key),
        "cash_plan": _build_cash_plan(state, account_key),
        "catalyst_calendar": _build_catalyst_calendar(state, account_key),
        "pending_orders": _build_pending_actions(state, account_key),
        "trade_log_7d": _filter_trade_log(
            state.get("trade_log", []), account_key, cutoff
        ),
    }

    return view


def build_all_view(state: dict) -> dict:
    """Build a slim view for both markets."""
    cutoff = _cutoff_7d()
    all_catalyst = state.get("catalyst_calendar_30d", [])

    view = {
        "_meta": {
            **state.get("_meta", {}),
            "_view_generated": datetime.now(timezone(timedelta(hours=8))).isoformat(),
            "_view_market": "all",
            "_view_trade_log_cutoff": cutoff,
            "_source": "portfolio_state.json (slim view — verbose fields stripped)",
        },
        "accounts": {
            "us": _build_account_view(state, "us"),
            "a_share": _build_account_view(state, "a_share"),
        },
        "cash_plan": state.get("cash_plan", {}),
        "catalyst_calendar": all_catalyst,
        "pending_orders": state.get("pending_orders", []),
        "trade_log_7d": [
            _trim_trade(t) for t in state.get("trade_log", [])
            if t.get("date", "") >= cutoff
        ][-TRADE_LOG_MAX * 2:],
    }

    return view


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a market-isolated, slim view of portfolio_state.json."
    )
    parser.add_argument(
        "--market",
        choices=["us", "cn", "all"],
        default="all",
        help="Market to include in the output (default: all)",
    )
    args = parser.parse_args()

    # Load source file
    if not STATE_FILE.exists():
        print(f"ERROR: {STATE_FILE} not found", file=sys.stderr)
        sys.exit(2)

    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"ERROR: Failed to parse {STATE_FILE}: {exc}", file=sys.stderr)
        sys.exit(2)

    # Build view
    if args.market == "all":
        view = build_all_view(state)
    else:
        view = build_view(state, args.market)

    output_json = json.dumps(view, ensure_ascii=False, indent=2)

    # Write to repo root
    suffix = args.market
    output_path = REPO_ROOT / f"session_view_{suffix}.json"
    output_path.write_text(output_json, encoding="utf-8")

    size_kb = len(output_json.encode("utf-8")) / 1024
    print(output_json)

    print(
        f"\n# Written to {output_path} ({size_kb:.1f} KB)",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()

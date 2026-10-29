# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
session_view.py — Generate a slim, market-specific view of portfolio_state.json.

Loads only the relevant market's data per session, stripping out verbose text
fields and historical snapshots to reduce context window consumption.

Guarantees (2026-10-29 hardened):
  1. Strict market isolation in catalyst_calendar (checks both `ticker` and
     `holdings`, plus filters non-US/CN-action entries out of `us` view).
  2. Strict RFC-8259 JSON compliance: recursively converts float NaN / Inf to
     None (`null`) and serializes with `allow_nan=False`.

Usage:
  uv run --script scripts/session_view.py --market us    # ~5K tokens
  uv run --script scripts/session_view.py --market cn    # ~4K tokens
  uv run --script scripts/session_view.py --market all   # both markets trimmed
"""

import argparse
import json
import math
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths & Constants
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).parent.parent
STATE_FILE = REPO_ROOT / "portfolio_state.json"

MARKET_ACCOUNT_MAP = {
    "us": "us",
    "cn": "a_share",
}

THESIS_TRUNCATE = 50   # chars to keep when full thesis is present
REASON_TRUNCATE = 60   # chars to keep from trade log reason field
TRADE_LOG_MAX   = 15   # max recent trades to include per market

_US_TICKER_RE = re.compile(r"^\^?[A-Z]{1,5}([.-][A-Z]{1,2})?$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sanitize_json_numbers(obj):
    """Recursively replace float NaN / Infinity with None for strict JSON."""
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _sanitize_json_numbers(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_json_numbers(v) for v in obj]
    return obj


def _cutoff_7d() -> str:
    """ISO date string 7 days ago (UTC+8)."""
    tz_cn = timezone(timedelta(hours=8))
    cutoff = datetime.now(tz_cn) - timedelta(days=7)
    return cutoff.strftime("%Y-%m-%d")


def _strip_position(pos: dict) -> dict:
    """Remove verbose narrative fields from a position dict."""
    stripped = {k: v for k, v in pos.items()}

    thesis = stripped.pop("thesis", None)
    if thesis:
        stripped["thesis_short"] = thesis[:THESIS_TRUNCATE] + ("…" if len(thesis) > THESIS_TRUNCATE else "")

    stripped.pop("bear_case", None)
    stripped.pop("stop_loss_note", None)
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
    return filtered[-TRADE_LOG_MAX:]


def _build_account_view(state: dict, account_key: str) -> dict:
    """Return a trimmed dict for one account."""
    account_raw = state.get("accounts", {}).get(account_key, {})
    account = {k: v for k, v in account_raw.items() if k != "cash_plan"}

    positions_raw = account.get("positions", [])
    account["positions"] = [_strip_position(p) for p in positions_raw]

    shorts_raw = account.get("short_positions", [])
    if shorts_raw:
        account["short_positions"] = [_strip_position(p) for p in shorts_raw]

    return account


def _build_pending_actions(state: dict, account_key: str) -> list:
    """Return only active (non-completed) pending_orders for the account."""
    orders = state.get("pending_orders", [])
    return [o for o in orders if o.get("account") == account_key]


def _is_cn_ticker(ticker: str) -> bool:
    t = str(ticker or "").strip()
    if not t:
        return False
    base = t.split(".")[0]
    return base.isdigit() or (len(base) == 6 and base[:1] in ("0", "3", "6", "4", "8"))


def _is_us_ticker(ticker: str) -> bool:
    t = str(ticker or "").strip()
    return bool(t) and not _is_cn_ticker(t) and bool(_US_TICKER_RE.match(t))


def _build_catalyst_calendar(state: dict, account_key: str) -> list:
    """Return catalyst events strictly relevant to the target account.

    Checks both `ticker` and `holdings` list:
      - 'a_share': event ticker is CN, OR any ticker in `holdings` is CN.
      - 'us': event has a valid US ticker, OR has non-CN holdings in `holdings`
        (pure CN holdings like ['600489', '000426'] and non-US conference
        placeholders with CN A-share actions are excluded from `us`).
    """
    calendar = state.get("catalyst_calendar_30d", [])
    out = []
    for e in calendar:
        tk = str(e.get("ticker") or "").strip()
        holdings = [str(h).strip() for h in (e.get("holdings") or []) if str(h).strip()]
        explicit_mkt = str(e.get("market") or e.get("account") or "").strip().lower()

        if account_key == "a_share":
            if explicit_mkt in ("cn", "a_share") or _is_cn_ticker(tk) or any(_is_cn_ticker(h) for h in holdings):
                out.append(e)
        else:
            if explicit_mkt in ("cn", "a_share"):
                continue
            if tk:
                if _is_us_ticker(tk):
                    out.append(e)
            elif holdings:
                if any(_is_us_ticker(h) for h in holdings):
                    out.append(e)
            else:
                if explicit_mkt == "us":
                    out.append(e)
    return out


def _build_cash_plan(state: dict, account_key: str) -> dict:
    """Return the cash plan for the account."""
    return state.get("cash_plan", {}).get(account_key, {})


# ---------------------------------------------------------------------------
# View builders
# ---------------------------------------------------------------------------

def build_view(state: dict, market: str) -> dict:
    """Build a slim, NaN-free view for a single market ('us' or 'cn')."""
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

    return _sanitize_json_numbers(view)


def build_all_view(state: dict) -> dict:
    """Build a slim, NaN-free view for both markets."""
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

    return _sanitize_json_numbers(view)


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

    if not STATE_FILE.exists():
        print(f"ERROR: {STATE_FILE} not found", file=sys.stderr)
        sys.exit(2)

    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"ERROR: Failed to parse {STATE_FILE}: {exc}", file=sys.stderr)
        sys.exit(2)

    if args.market == "all":
        view = build_all_view(state)
    else:
        view = build_view(state, args.market)

    output_json = json.dumps(view, ensure_ascii=False, indent=2, allow_nan=False)

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

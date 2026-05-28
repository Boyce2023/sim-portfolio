"""
Unified computation engine — wraps nav_calc.py.

No script computes NAV, returns, or portfolio percentages independently.
All callers import from here; nav_calc.py remains the single arithmetic source.

Usage:
    from scripts.core.compute import full_snapshot
    output = full_snapshot(portfolio_state_dict)
"""

from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timezone

# Allow running from any working directory
sys.path.insert(0, str(Path(__file__).parent.parent))
from nav_calc import calc_nav, apply_nav, validate_nav  # noqa: E402

# Re-export so callers only need to import from compute
__all__ = [
    "calc_nav",
    "apply_nav",
    "validate_nav",
    "calc_returns",
    "calc_portfolio_pcts",
    "calc_combined_return",
    "cn_ticker_suffix",
    "build_public_positions",
    "full_snapshot",
]

# CNY/USD exchange rate used for cross-currency weight normalisation.
# Sourced from portfolio convention; update here if rate changes.
_CNY_PER_USD: float = 7.2


# ---------------------------------------------------------------------------
# Core computation helpers
# ---------------------------------------------------------------------------

def calc_returns(account: dict, initial_capital: float) -> dict:
    """
    Calculate return metrics for one account.

    Args:
        account: account dict (must contain total_assets or raw positions)
        initial_capital: starting capital in the account's native currency

    Returns:
        {"return_pct": float, "realized_pnl": float}
    """
    nav = calc_nav(account)
    total = nav["total_assets"]
    return_pct = round((total / initial_capital - 1) * 100, 2) if initial_capital else 0.0
    return {
        "return_pct": return_pct,
        "realized_pnl": round(account.get("realized_pnl", 0), 2),
    }


def calc_portfolio_pcts(positions: list[dict], total_assets: float) -> None:
    """
    Fill portfolio_pct in each position dict IN-PLACE.

    Uses abs(market_value) / total_assets so shorts and longs are both
    expressed as a positive share of the portfolio.

    Args:
        positions: list of position dicts (each must have "market_value")
        total_assets: total NAV of the account in its native currency
    """
    for pos in positions:
        abs_mv = abs(pos.get("market_value", 0))
        pos["portfolio_pct"] = round(abs_mv / total_assets, 3) if total_assets else 0.0


def calc_combined_return(
    a_initial: float,
    us_initial: float,
    a_total: float,
    us_total: float,
) -> float:
    """
    Dynamic USD-normalised combined return across A-share and US accounts.

    Weights are derived from initial capital ratios — never hardcoded.

    Formula:
        a_initial_usd = a_initial / CNY_PER_USD
        total_initial_usd = a_initial_usd + us_initial
        combined_return = (a_total/CNY_PER_USD + us_total) / total_initial_usd - 1

    Args:
        a_initial: A-share initial capital (CNY)
        us_initial: US initial capital (USD)
        a_total:   A-share current NAV (CNY)
        us_total:  US current NAV (USD)

    Returns:
        combined return as a percentage (e.g. 6.12 means +6.12%)
    """
    a_initial_usd = a_initial / _CNY_PER_USD
    total_initial_usd = a_initial_usd + us_initial
    if total_initial_usd == 0:
        return 0.0
    combined = (a_total / _CNY_PER_USD + us_total) / total_initial_usd - 1
    return round(combined * 100, 2)


# ---------------------------------------------------------------------------
# Ticker helpers
# ---------------------------------------------------------------------------

def cn_ticker_suffix(ticker: str) -> str:
    """
    Append exchange suffix to a bare A-share ticker.

    Rules:
        6xxxxx  → 6xxxxx.SS  (Shanghai)
        others  → xxxxxx.SZ  (Shenzhen)

    Args:
        ticker: bare 6-digit A-share code, e.g. "002028" or "600000"

    Returns:
        ticker with suffix, e.g. "002028.SZ" or "600000.SS"
    """
    return f"{ticker}.SS" if ticker.startswith("6") else f"{ticker}.SZ"


# ---------------------------------------------------------------------------
# Position building
# ---------------------------------------------------------------------------

def build_public_positions(
    account: dict,
    account_key: str,
    total_assets: float,
) -> list[dict]:
    """
    Build the public-facing position list from raw account data.

    Handles:
    - Long positions (positive shares)
    - Short positions (negative shares, inverted PnL direction)
    - A-share ticker suffix injection (.SS / .SZ)
    - portfolio_pct computed from total_assets

    Args:
        account:     raw account dict from portfolio_state.json
        account_key: "a_share" or "us" — controls ticker suffix logic
        total_assets: current NAV used to compute portfolio_pct

    Returns:
        list of position dicts ready for the public JSON
    """
    result: list[dict] = []

    # Long positions
    for pos in account.get("positions", []):
        shares = pos.get("shares", 0)
        if shares <= 0:
            continue
        ticker = pos.get("ticker", "")
        if account_key == "a_share" and "." not in ticker:
            ticker = cn_ticker_suffix(ticker)

        avg_cost = pos.get("avg_cost", 0)
        current_price = pos.get("current_price", avg_cost)
        mv = round(shares * current_price, 2)
        pnl_pct = round((current_price - avg_cost) / avg_cost * 100, 2) if avg_cost else 0.0
        portfolio_pct = round(abs(mv) / total_assets, 3) if total_assets else 0.0

        result.append({
            "ticker": ticker,
            "name": pos.get("name", ""),
            "shares": shares,
            "avg_cost": round(avg_cost, 4),
            "current_price": round(current_price, 4),
            "market_value": mv,
            "unrealized_pnl_pct": pnl_pct,
            "portfolio_pct": portfolio_pct,
            "entry_date": pos.get("entry_date", ""),
            "type": pos.get("type", ""),
            "sector": pos.get("sector", ""),
        })

    # Short positions — negative shares, inverted PnL
    for pos in account.get("short_positions", []):
        ticker = pos.get("ticker", "")
        # US shorts keep their ticker as-is; A-share shorts (rare) get suffix
        if account_key == "a_share" and "." not in ticker:
            ticker = cn_ticker_suffix(ticker)

        raw_shares = abs(pos.get("shares", 0))
        entry_price = pos.get("entry_price", pos.get("avg_cost", 0))
        current_price = pos.get("current_price", entry_price)

        # Short market_value: negative because we owe these shares
        mv = round(-(raw_shares * current_price), 2)
        pnl_pct = (
            round((entry_price - current_price) / entry_price * 100, 2)
            if entry_price
            else 0.0
        )
        portfolio_pct = round(abs(mv) / total_assets, 3) if total_assets else 0.0

        result.append({
            "ticker": ticker,
            "name": pos.get("name", ""),
            "shares": -raw_shares,          # negative = short
            "avg_cost": round(entry_price, 4),
            "current_price": round(current_price, 4),
            "market_value": mv,
            "unrealized_pnl_pct": pnl_pct,
            "portfolio_pct": portfolio_pct,
            "entry_date": pos.get("entry_date", ""),
            "type": "short",
            "sector": pos.get("sector", ""),
        })

    return result


# ---------------------------------------------------------------------------
# Master snapshot builder
# ---------------------------------------------------------------------------

def full_snapshot(state: dict) -> dict:
    """
    Generate the complete public sim-portfolio.json from portfolio_state.json.

    This is THE function that sync_nexus.py and sync_portfolio.py should call.
    It performs every computation in one place:
      - NAV via calc_nav (canonical formula)
      - return_pct per account
      - portfolio_pct per position (from total_assets, not from stored values)
      - combined_return with dynamic weights (never hardcoded 0.87/0.13)
      - daily_snapshots with recalculated combined_return
      - trade_log with date normalisation
      - meta section with description and disclaimer

    Args:
        state: parsed contents of portfolio_state.json

    Returns:
        dict ready for json.dump() as the website-facing sim-portfolio.json
    """
    meta_src = state.get("_meta", {})
    a_raw = state["accounts"]["a_share"]
    u_raw = state["accounts"]["us"]

    # --- NAV (single call each; no independent arithmetic downstream) ---
    a_nav = calc_nav(a_raw)
    u_nav = calc_nav(u_raw)
    a_total = a_nav["total_assets"]
    u_total = u_nav["total_assets"]

    a_initial = a_raw.get("initial_capital", 0)
    u_initial = u_raw.get("initial_capital", 0)

    # --- Per-account return ---
    a_return_pct = round((a_total / a_initial - 1) * 100, 2) if a_initial else 0.0
    u_return_pct = round((u_total / u_initial - 1) * 100, 2) if u_initial else 0.0

    # --- Positions ---
    a_positions = build_public_positions(a_raw, "a_share", a_total)
    u_positions = build_public_positions(u_raw, "us", u_total)

    # --- Daily snapshots with dynamic combined return ---
    a_initial_usd = a_initial / _CNY_PER_USD
    total_initial_usd = a_initial_usd + u_initial  # for weight computation

    daily_snapshots: list[dict] = []
    for snap in state.get("performance", {}).get("daily_snapshots", []):
        snap_a_nav = snap.get("a_share_nav", a_initial)
        snap_u_nav = snap.get("us_nav", u_initial)
        snap_a_ret = snap.get("a_share_return_pct", 0)
        snap_u_ret = snap.get("us_return_pct", 0)

        # Dynamic combined — same formula as calc_combined_return
        if total_initial_usd > 0:
            combined = (snap_a_nav / _CNY_PER_USD + snap_u_nav) / total_initial_usd - 1
            combined_pct = round(combined * 100, 2)
        else:
            combined_pct = 0.0

        entry = {
            "date": snap["date"],
            "a_share": {"total_assets": snap_a_nav, "return_pct": snap_a_ret},
            "us": {"total_assets": snap_u_nav, "return_pct": snap_u_ret},
            "combined_return_pct": combined_pct,
        }
        if snap.get("sse_return_pct") is not None:
            entry["sse_return_pct"] = snap["sse_return_pct"]
        if snap.get("spy_return_pct") is not None:
            entry["spy_return_pct"] = snap["spy_return_pct"]
        daily_snapshots.append(entry)

    # --- Trade log with date normalisation ---
    trade_log: list[dict] = []
    for t in state.get("trade_log", []):
        date_str = t.get("date", t.get("timestamp", "")[:10])
        entry: dict = {
            "date": date_str,
            "account": t.get("account", ""),
            "action": t.get("action", ""),
            "ticker": t.get("ticker", ""),
            "name": t.get("name", ""),
            "shares": t.get("shares", 0),
            "price": t.get("price", 0),
        }
        if t.get("realized_pnl") is not None:
            entry["realized_pnl"] = t["realized_pnl"]
        trade_log.append(entry)

    # --- Assemble output ---
    return {
        "meta": {
            "type": "sim_portfolio",
            "description": "Claude AI模拟盘 — ¥10M A股 + $1.5M 美股",
            "start_date": meta_src.get("start_date", "2026-05-18"),
            "end_date": meta_src.get("end_date", "2026-06-18"),
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "synced_from": "portfolio_state.json",
            "benchmark": {"a_share": "CSI300", "us": "SPY"},
            "disclaimer": "模拟盘，非真实交易。仅供研究参考。",
        },
        "accounts": {
            "a_share": {
                "currency": "CNY",
                "initial_capital": a_initial,
                "total_assets": a_total,
                "cash": round(a_raw.get("cash", 0), 2),
                "realized_pnl": round(a_raw.get("realized_pnl", 0), 2),
                "return_pct": a_return_pct,
                "positions": a_positions,
            },
            "us": {
                "currency": "USD",
                "initial_capital": u_initial,
                "total_assets": u_total,
                "cash": round(u_raw.get("cash", 0), 2),
                "realized_pnl": round(u_raw.get("realized_pnl", 0), 2),
                "return_pct": u_return_pct,
                "positions": u_positions,
            },
        },
        "daily_snapshots": daily_snapshots,
        "trade_log": trade_log,
    }

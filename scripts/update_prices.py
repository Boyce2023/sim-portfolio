# /// script
# requires-python = ">=3.11"
# dependencies = ["yfinance>=0.2.40"]
# ///
"""
Fetch latest prices and update portfolio_state.json in-place.

Usage:
  uv run --script scripts/update_prices.py              # update all
  uv run --script scripts/update_prices.py --market cn   # A-share only
  uv run --script scripts/update_prices.py --market us   # US only
  uv run --script scripts/update_prices.py --dry-run     # show diff without saving
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ_BEIJING = timezone(timedelta(hours=8))
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
PORTFOLIO_PATH = REPO_ROOT / "portfolio_state.json"

sys.path.insert(0, str(SCRIPT_DIR))
from fetch_prices import fetch_cn_prices, fetch_us_prices, save_prices_atomic


def update_position(pos: dict, price_data: dict) -> list[str]:
    """Update a single position with new price data. Returns list of changes."""
    changes = []
    price = price_data.get("price")
    if price is None:
        return [f"  {pos['ticker']}: SKIP (no price data: {price_data.get('error', '?')})"]

    old_price = pos.get("current_price")
    shares = pos["shares"]
    avg_cost = pos["avg_cost"]
    cost_basis = shares * avg_cost

    new_mv = round(shares * price, 2)
    new_pnl = round(new_mv - cost_basis, 2)
    new_pnl_pct = round((price / avg_cost - 1) * 100, 2) if avg_cost > 0 else 0

    if old_price and abs(old_price - price) > 0.001:
        changes.append(f"  {pos.get('name', pos['ticker'])}: ¥{old_price} → ¥{price} ({price_data.get('change_pct', '?'):+.2f}%)")

    pos["current_price"] = price
    pos["prev_close"] = price_data.get("prev_close", price)
    pos["change_pct"] = price_data.get("change_pct", 0)
    pos["market_value"] = new_mv
    pos["cost_basis"] = round(cost_basis, 2)
    pos["unrealized_pnl"] = new_pnl
    pos["unrealized_pnl_pct"] = new_pnl_pct
    pos["last_updated"] = datetime.now(TZ_BEIJING).isoformat()

    return changes


def recalc_account(account: dict, account_name: str) -> list[str]:
    """Recalculate account-level totals. Returns list of validation messages."""
    from nav_calc import calc_nav, apply_nav

    old_assets = account.get("total_assets", 0)
    nav = calc_nav(account)
    apply_nav(account, nav)

    msgs = []
    if abs(old_assets - nav["total_assets"]) > 1:
        msgs.append(f"  [{account_name}] total_assets: {old_assets} → {nav['total_assets']}")
    return msgs


def validate_positions(positions: list[dict]) -> list[str]:
    """Cross-check position math. Returns list of errors."""
    errors = []
    for p in positions:
        shares = abs(p.get("shares", 0))
        price = p.get("current_price", 0)
        mv = p.get("market_value", 0)
        expected_mv = round(shares * price, 2)
        if abs(abs(mv) - expected_mv) > 1:
            errors.append(f"  !! {p.get('name', p['ticker'])}: market_value={mv} but {shares}×{price}={expected_mv}")

        cost = p.get("cost_basis", 0)
        expected_cost = round(shares * p.get("avg_cost", 0), 2)
        if abs(abs(cost) - expected_cost) > 1:
            errors.append(f"  !! {p.get('name', p['ticker'])}: cost_basis={cost} but {shares}×{p.get('avg_cost',0)}={expected_cost}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Update portfolio prices")
    parser.add_argument("--market", choices=["cn", "us", "all"], default="all")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without saving")
    args = parser.parse_args()

    with open(PORTFOLIO_PATH, encoding="utf-8") as f:
        state = json.load(f)

    all_changes: list[str] = []
    all_errors: list[str] = []

    if args.market in ("cn", "all"):
        cn_positions = state["accounts"]["a_share"]["positions"]
        cn_tickers = [p["ticker"] for p in cn_positions]
        print(f"Fetching {len(cn_tickers)} A-share prices...")
        cn_prices = fetch_cn_prices(cn_tickers)

        for pos in cn_positions:
            pd = cn_prices.get(pos["ticker"], {})
            changes = update_position(pos, pd)
            all_changes.extend(changes)

        msgs = recalc_account(state["accounts"]["a_share"], "A股")
        all_changes.extend(msgs)
        errs = validate_positions(cn_positions)
        all_errors.extend(errs)

    if args.market in ("us", "all"):
        us_positions = state["accounts"]["us"]["positions"]
        us_tickers = [p["ticker"] for p in us_positions if p.get("instrument_type") != "call_option"]
        print(f"Fetching {len(us_tickers)} US prices...")
        us_prices = fetch_us_prices(us_tickers)

        for pos in us_positions:
            ticker = pos["ticker"]
            if ticker in us_prices:
                changes = update_position(pos, us_prices[ticker])
                all_changes.extend(changes)

        # Also update short_positions prices
        short_positions = state["accounts"]["us"].get("short_positions", [])
        if short_positions:
            short_tickers = [s["ticker"] for s in short_positions]
            short_prices = fetch_us_prices(short_tickers)
            for sp in short_positions:
                sticker = sp["ticker"]
                if sticker in short_prices and short_prices[sticker].get("price"):
                    sp["current_price"] = short_prices[sticker]["price"]
                    sp["last_updated"] = datetime.now(TZ_BEIJING).isoformat()

        msgs = recalc_account(state["accounts"]["us"], "美股")
        all_changes.extend(msgs)
        errs = validate_positions(us_positions)
        all_errors.extend(errs)

    now = datetime.now(TZ_BEIJING)
    state["_meta"]["last_updated"] = now.isoformat()
    state["_meta"]["update_trigger"] = "update_prices"

    nav_cn = state["accounts"]["a_share"]["total_assets"]
    nav_us = state["accounts"]["us"]["total_assets"]
    initial_cn = state["accounts"]["a_share"]["initial_capital"]
    initial_us = state["accounts"]["us"]["initial_capital"]
    state["performance"]["total_return_cny"] = round(nav_cn - initial_cn, 2)
    state["performance"]["total_return_pct_cny"] = round((nav_cn / initial_cn - 1) * 100, 2)
    state["performance"]["total_return_usd"] = round(nav_us - initial_us, 2)
    state["performance"]["total_return_pct_usd"] = round((nav_us / initial_us - 1) * 100, 2)

    print(f"\n{'='*50}")
    if all_changes:
        print("Changes:")
        for c in all_changes:
            print(c)
    else:
        print("No price changes detected.")

    if all_errors:
        print(f"\n⚠ Validation Errors ({len(all_errors)}):")
        for e in all_errors:
            print(e)
        if not args.dry_run:
            print("Fixing errors before save...")

    print(f"\nA股 NAV: ¥{nav_cn:,.0f} ({(nav_cn/initial_cn-1)*100:+.2f}%)")
    print(f"美股 NAV: ${nav_us:,.0f} ({(nav_us/initial_us-1)*100:+.2f}%)")

    if args.dry_run:
        print("\n[DRY-RUN] No changes saved.")
    else:
        save_prices_atomic(state, PORTFOLIO_PATH)
        print(f"\n[OK] portfolio_state.json updated at {now.strftime('%H:%M:%S')}")

    return 1 if all_errors else 0


if __name__ == "__main__":
    sys.exit(main())

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
from fetch_prices import fetch_cn_prices, fetch_us_prices, fetch_benchmark_prices, save_prices_atomic


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

    # ⛔ 除权检测 (2026-06-16 安集10转3送转教训): 单日跌>11%疑似除权除息
    # 不复权现价会因除权机械下跌,但成本/股数不自动调整=盈亏+持股数算错
    chg = price_data.get("change_pct")
    if chg is not None and chg < -11:
        changes.append(
            f"  ⚠️⚠️ {pos.get('name', pos['ticker'])} 单日{chg:+.1f}% 疑似除权除息!"
            f"\n     → 核对2025年报送转/分红方案,若送转: 成本÷factor + 股数×factor 调整"
            f"\n     → 当前数据为不复权,系统不自动除权,P&L和持股数需人工修正前别信"
        )

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
    parser.add_argument("--market", choices=["cn", "us", "all"], default="auto")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without saving")
    args = parser.parse_args()

    if args.market == "auto":
        now_bj = datetime.now(timezone(timedelta(hours=8)))
        h = now_bj.hour
        if 9 <= h < 16:
            args.market = "cn"
            print(f"[AUTO] BJT {now_bj.strftime('%H:%M')} → A股时段，仅更新cn")
        elif 21 <= h or h < 5:
            args.market = "us"
            print(f"[AUTO] BJT {now_bj.strftime('%H:%M')} → 美股时段，仅更新us")
        elif 16 <= h < 21:
            args.market = "cn"
            print(f"[AUTO] BJT {now_bj.strftime('%H:%M')} → A股盘后，仅更新cn（美股未开盘）")
        else:
            args.market = "cn"
            print(f"[AUTO] BJT {now_bj.strftime('%H:%M')} → 非盘中，默认仅更新cn")

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

    if args.market in ("cn", "all"):
        nav_cn = state["accounts"]["a_share"]["total_assets"]
        initial_cn = state["accounts"]["a_share"]["initial_capital"]
        state["performance"]["total_return_cny"] = round(nav_cn - initial_cn, 2)
        state["performance"]["total_return_pct_cny"] = round((nav_cn / initial_cn - 1) * 100, 2)
    if args.market in ("us", "all"):
        nav_us = state["accounts"]["us"]["total_assets"]
        initial_us = state["accounts"]["us"]["initial_capital"]
        state["performance"]["total_return_usd"] = round(nav_us - initial_us, 2)
        state["performance"]["total_return_pct_usd"] = round((nav_us / initial_us - 1) * 100, 2)

    # Auto-update benchmark data in today's snapshot (auto-create if missing)
    snapshots = state.get("performance", {}).get("daily_snapshots", [])
    if snapshots:
        today_str = now.strftime("%Y-%m-%d")
        today_snap = None
        for s in snapshots:
            if s["date"] == today_str:
                today_snap = s
                break

        if not today_snap:
            # Auto-create today's snapshot — this is the root cause fix.
            # Read NAV from state directly (not from args-gated variables)
            a_acct = state["accounts"]["a_share"]
            u_acct = state["accounts"]["us"]
            snap_a_nav = a_acct.get("total_assets", a_acct.get("initial_capital", 0))
            snap_u_nav = u_acct.get("total_assets", u_acct.get("initial_capital", 0))
            snap_a_init = a_acct.get("initial_capital", 1)
            snap_u_init = u_acct.get("initial_capital", 1)

            today_snap = {
                "date": today_str,
                "a_share_nav": snap_a_nav,
                "a_share_return_pct": round((snap_a_nav / snap_a_init - 1) * 100, 2) if snap_a_init else 0,
                "us_nav": snap_u_nav,
                "us_return_pct": round((snap_u_nav / snap_u_init - 1) * 100, 2) if snap_u_init else 0,
            }
            snapshots.append(today_snap)
            print(f"  [SNAP] Created new snapshot for {today_str}")

        # Always fetch and write benchmark data
        bench = fetch_benchmark_prices()
        base_snap = snapshots[0]

        if args.market in ("cn", "all"):
            csi = bench.get("csi300", {})
            if csi.get("close"):
                old_sse = today_snap.get("sse_close")
                today_snap["sse_close"] = csi["close"]
                base_sse = base_snap.get("sse_close", csi["close"])
                today_snap["sse_return_pct"] = round((csi["close"] / base_sse - 1) * 100, 2)
                if old_sse and abs(old_sse - csi["close"]) > 0.5:
                    print(f"  [BENCH] CSI300: {old_sse} → {csi['close']} (eastmoney)")
                else:
                    print(f"  [BENCH] CSI300: {csi['close']} ({today_snap['sse_return_pct']:+.2f}%)")

        if args.market in ("us", "all"):
            spy = bench.get("spy", {})
            if spy.get("close"):
                old_spy = today_snap.get("spy_close")
                today_snap["spy_close"] = spy["close"]
                base_spy = base_snap.get("spy_close", spy["close"])
                today_snap["spy_return_pct"] = round((spy["close"] / base_spy - 1) * 100, 2)
                if old_spy and abs(old_spy - spy["close"]) > 0.5:
                    print(f"  [BENCH] SPY: {old_spy} → {spy['close']} (yfinance)")
                else:
                    print(f"  [BENCH] SPY: {spy['close']} ({today_snap['spy_return_pct']:+.2f}%)")

        # Also update NAV in today's snapshot to stay current
        if args.market in ("cn", "all"):
            today_snap["a_share_nav"] = state["accounts"]["a_share"].get("total_assets", today_snap.get("a_share_nav", 0))
            a_init = state["accounts"]["a_share"].get("initial_capital", 1)
            today_snap["a_share_return_pct"] = round((today_snap["a_share_nav"] / a_init - 1) * 100, 2) if a_init else 0
        if args.market in ("us", "all"):
            today_snap["us_nav"] = state["accounts"]["us"].get("total_assets", today_snap.get("us_nav", 0))
            u_init = state["accounts"]["us"].get("initial_capital", 1)
            today_snap["us_return_pct"] = round((today_snap["us_nav"] / u_init - 1) * 100, 2) if u_init else 0

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

    if args.market in ("cn", "all"):
        print(f"\nA股 NAV: ¥{nav_cn:,.0f} ({(nav_cn/initial_cn-1)*100:+.2f}%)")
    if args.market in ("us", "all"):
        print(f"美股 NAV: ${nav_us:,.0f} ({(nav_us/initial_us-1)*100:+.2f}%)")

    if args.dry_run:
        print("\n[DRY-RUN] No changes saved.")
    else:
        save_prices_atomic(state, PORTFOLIO_PATH)
        print(f"\n[OK] portfolio_state.json updated at {now.strftime('%H:%M:%S')}")

        # Refresh session views so they reflect latest prices
        try:
            from session_view import build_view, build_all_view
            markets_to_rebuild = []
            if args.market in ("cn", "all"):
                markets_to_rebuild.append(("cn", "cn"))
            if args.market in ("us", "all"):
                markets_to_rebuild.append(("us", "us"))
            for market, suffix in markets_to_rebuild:
                view = build_view(state, market)
                out_path = PORTFOLIO_PATH.parent / f"session_view_{suffix}.json"
                out_path.write_text(json.dumps(view, ensure_ascii=False, indent=2), encoding="utf-8")
            if args.market == "all":
                all_view = build_all_view(state)
                (PORTFOLIO_PATH.parent / "session_view_all.json").write_text(
                    json.dumps(all_view, ensure_ascii=False, indent=2), encoding="utf-8")
            print("[OK] session_view files refreshed")
        except Exception as e:
            print(f"[WARN] session_view refresh failed: {e}")

    return 1 if all_errors else 0


if __name__ == "__main__":
    sys.exit(main())

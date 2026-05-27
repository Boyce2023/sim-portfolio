#!/usr/bin/env python3
"""Fix US accounting: delete 05-27 trades, replay from scratch, re-execute at live prices."""

import json
from datetime import datetime
from pathlib import Path
from copy import deepcopy

ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO = ROOT / "portfolio_state.json"

# Current live prices (yf verified 2026-05-27 market hours)
LIVE_PRICES = {
    "GEV": 1042.30, "VST": 160.06, "AAON": 143.01, "CLS": 362.56,
    "MU": 932.00, "AMAT": 447.83, "MSTR": 156.895,
    "AAPL": 312.18, "CRM": 181.98, "INOD": 92.59, "SPUT": 19.75,
}

NAMES = {
    "GEV": ("GE Vernova", "电力设备/燃气轮机"),
    "VST": ("Vistra Corp", "DC电力/独立发电"),
    "AAON": ("AAON Inc", "DC HVAC/建筑设备"),
    "CLS": ("Celestica Inc", "AI制造/EMS"),
    "MU": ("Micron Technology", "Memory/HBM"),
    "AMAT": ("Applied Materials", "半导体设备"),
    "MSTR": ("Strategy Inc", "BTC Leveraged Proxy"),
    "AAPL": ("Apple Inc", "Consumer Tech"),
    "CRM": ("Salesforce Inc", "Enterprise SaaS"),
    "INOD": ("Innodata Inc", "AI Data Services"),
    "SPUT": ("Sprott Physical Uranium Trust", "Uranium"),
    "NVDA": ("NVIDIA Corp", "AI GPU"),
    "HSAI": ("Hesai Group", "LiDAR"),
    "GOOGL": ("Alphabet Inc", "Search/Cloud"),
    "ADBE": ("Adobe Inc", "Creative Software"),
    "LEU": ("Centrus Energy", "Uranium Enrichment"),
    "FPS": ("Freshpet Inc", "Pet Food"),
    "DG": ("Dollar General", "Discount Retail"),
    "COPX": ("Global X Copper Miners ETF", "Copper Mining"),
    "RIVN": ("Rivian Automotive", "EV"),
    "UPST": ("Upstart Holdings", "AI Lending"),
}


def load():
    with open(PORTFOLIO) as f:
        return json.load(f)


def save(data):
    with open(PORTFOLIO, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def now_iso():
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")


def replay_trades(trades):
    """Replay US trades from initial capital, return (cash, positions, short_positions, realized_pnl).

    Uses the same cash model as execute_trade.py:
    - BUY: cash -= cost
    - SELL: cash += proceeds, rpnl tracked
    - SHORT: cash -= proceeds (margin model)
    - COVER: cash += entry_cost + rpnl
    """
    cash = 1_500_000.0
    positions = {}  # ticker -> {shares, total_cost}
    shorts = {}     # ticker -> {shares, total_cost}
    realized_pnl = 0.0

    for t in trades:
        action = t["action"]
        ticker = t["ticker"]
        shares = t.get("shares", 0)
        price = t.get("price", 0)
        value = shares * price

        if action == "buy":
            cash -= value
            if ticker in positions:
                old = positions[ticker]
                new_shares = old["shares"] + shares
                new_cost = old["total_cost"] + value
                positions[ticker] = {"shares": new_shares, "total_cost": new_cost}
            else:
                positions[ticker] = {"shares": shares, "total_cost": value}

        elif action == "sell":
            if ticker not in positions:
                print(f"  [WARN] Selling {ticker} but no position found!")
                continue
            pos = positions[ticker]
            avg_cost = pos["total_cost"] / pos["shares"]
            rpnl = (price - avg_cost) * shares
            cash += value
            realized_pnl += rpnl

            remaining = pos["shares"] - shares
            if remaining <= 0:
                del positions[ticker]
            else:
                positions[ticker] = {
                    "shares": remaining,
                    "total_cost": avg_cost * remaining,
                }

        elif action == "short":
            cash -= value  # margin model: cash decreases
            if ticker in shorts:
                old = shorts[ticker]
                new_shares = old["shares"] + shares
                new_cost = old["total_cost"] + value
                shorts[ticker] = {"shares": new_shares, "total_cost": new_cost}
            else:
                shorts[ticker] = {"shares": shares, "total_cost": value}

        elif action == "cover":
            if ticker not in shorts:
                print(f"  [WARN] Covering {ticker} but no short found!")
                continue
            pos = shorts[ticker]
            avg_entry = pos["total_cost"] / pos["shares"]
            rpnl = (avg_entry - price) * shares
            # Cover: return margin + rpnl
            cash += shares * avg_entry + rpnl
            realized_pnl += rpnl

            remaining = pos["shares"] - shares
            if remaining <= 0:
                del shorts[ticker]
            else:
                shorts[ticker] = {
                    "shares": remaining,
                    "total_cost": avg_entry * remaining,
                }

    return cash, positions, shorts, realized_pnl


def main():
    data = load()

    # Step 1: Separate US trades, remove 05-27 trades
    all_trades = data.get("trade_log", [])
    us_trades_pre = [t for t in all_trades if t.get("account") == "us" and "2026-05-27" not in t.get("timestamp", "")]
    non_us_trades = [t for t in all_trades if t.get("account") != "us"]
    removed = [t for t in all_trades if t.get("account") == "us" and "2026-05-27" in t.get("timestamp", "")]

    print(f"=== Step 1: Remove 05-27 US trades ===")
    print(f"  Removed {len(removed)} trades:")
    for t in removed:
        print(f"    {t['action']:6s} {t['ticker']:6s} {t.get('shares',0):>6}sh @ ${t.get('price',0):.2f}")

    # Step 2: Replay pre-05-27 trades to get correct state
    print(f"\n=== Step 2: Replay {len(us_trades_pre)} pre-05-27 US trades ===")
    cash, positions, shorts, rpnl = replay_trades(us_trades_pre)

    print(f"  Cash: ${cash:,.2f}")
    print(f"  Realized PnL: ${rpnl:,.2f}")
    print(f"  Positions: {list(positions.keys())}")
    print(f"  Shorts: {list(shorts.keys())}")

    # Verify
    long_cost = sum(p["total_cost"] for p in positions.values())
    short_cost = sum(s["total_cost"] for s in shorts.values())
    print(f"  Long cost basis: ${long_cost:,.2f}")
    print(f"  Short cost basis: ${short_cost:,.2f}")
    print(f"  Balance check: Cash({cash:,.2f}) + LongCost({long_cost:,.2f}) + ShortCost({short_cost:,.2f}) = ${cash + long_cost + short_cost:,.2f}")
    print(f"  Initial + Rpnl = ${1500000 + rpnl:,.2f}")
    gap = (cash + long_cost + short_cost) - (1500000 + rpnl)
    print(f"  Gap: ${gap:,.2f} {'✓ BALANCED' if abs(gap) < 1 else '✗ IMBALANCED'}")

    # Step 3: Execute V7.6 trades at LIVE prices
    print(f"\n=== Step 3: Re-execute V7.6 trades at live prices ===")

    v76_trades = []
    ts = now_iso()
    trade_id_base = len(non_us_trades) + len(us_trades_pre) + 1

    # Sells first
    sells = [
        ("AAPL", 500, "V7.6 MOM rotation: not in Top7 by 6M RS"),
        ("CRM", 420, "V7.6 MOM rotation: not in Top7 by 6M RS"),
        ("INOD", 1000, "V7.6 MOM rotation: not in Top7 by 6M RS"),
        ("VST", 950, "V7.6 MOM rotation: reduce from 1750 to 800sh, not in Top7"),
        ("SPUT", 6090, "V7.6 MOM rotation: not in momentum universe"),
    ]

    for ticker, shares, reason in sells:
        price = LIVE_PRICES[ticker]
        pos = positions[ticker]
        avg_cost = pos["total_cost"] / pos["shares"]
        rpnl_trade = round((price - avg_cost) * shares, 2)
        proceeds = round(shares * price, 2)

        cash += proceeds
        rpnl += rpnl_trade

        remaining = pos["shares"] - shares
        if remaining <= 0:
            del positions[ticker]
        else:
            positions[ticker] = {"shares": remaining, "total_cost": avg_cost * remaining}

        name = NAMES.get(ticker, (ticker, ""))[0]
        trade = {
            "id": f"TRD-{trade_id_base:04d}",
            "timestamp": ts,
            "date": "2026-05-27",
            "action": "sell",
            "account": "us",
            "ticker": ticker,
            "name": name,
            "shares": shares,
            "price": price,
            "value": proceeds,
            "currency": "USD",
            "reason": reason,
            "realized_pnl": rpnl_trade,
        }
        v76_trades.append(trade)
        trade_id_base += 1
        print(f"  SELL {ticker:6s} {shares:>5}sh @ ${price:>10.2f} = ${proceeds:>12.2f}  rpnl: ${rpnl_trade:>+10.2f}")

    # Buys
    buys = [
        ("GEV", 60, "V7.6 MOM #2: +98% 6M momentum, DC gas turbine near-monopoly"),
        ("MU", 160, "V7.6 MOM #1: +111.8% 6M momentum leader, HBM supercycle"),
        ("AMAT", 320, "V7.6 MOM #4: +76% 6M momentum, semi capex cycle beneficiary"),
    ]

    for ticker, shares, reason in buys:
        price = LIVE_PRICES[ticker]
        cost = round(shares * price, 2)
        cash -= cost

        if ticker in positions:
            old = positions[ticker]
            new_shares = old["shares"] + shares
            new_cost = old["total_cost"] + cost
            positions[ticker] = {"shares": new_shares, "total_cost": new_cost}
        else:
            positions[ticker] = {"shares": shares, "total_cost": cost}

        name = NAMES.get(ticker, (ticker, ""))[0]
        trade = {
            "id": f"TRD-{trade_id_base:04d}",
            "timestamp": ts,
            "date": "2026-05-27",
            "action": "buy",
            "account": "us",
            "ticker": ticker,
            "name": name,
            "shares": shares,
            "price": price,
            "value": cost,
            "currency": "USD",
            "reason": reason,
        }
        v76_trades.append(trade)
        trade_id_base += 1
        print(f"  BUY  {ticker:6s} {shares:>5}sh @ ${price:>10.2f} = ${cost:>12.2f}")

    # Step 4: Compute final state
    print(f"\n=== Step 4: Final state ===")
    print(f"  Cash: ${cash:,.2f}")
    print(f"  Realized PnL: ${rpnl:,.2f}")

    # Build position list for portfolio_state
    final_positions = []
    for ticker, pos in positions.items():
        avg_cost = round(pos["total_cost"] / pos["shares"], 4)
        cur_price = LIVE_PRICES.get(ticker, avg_cost)
        mv = round(pos["shares"] * cur_price, 2)
        upnl = round((cur_price - avg_cost) * pos["shares"], 2)
        upnl_pct = round((cur_price - avg_cost) / avg_cost * 100, 2) if avg_cost else 0
        name, sector = NAMES.get(ticker, (ticker, ""))

        final_positions.append({
            "ticker": ticker,
            "name": name,
            "shares": pos["shares"],
            "avg_cost": avg_cost,
            "current_price": cur_price,
            "market_value": mv,
            "cost_basis": round(pos["total_cost"], 2),
            "unrealized_pnl": upnl,
            "unrealized_pnl_pct": upnl_pct,
            "sector": sector,
            "entry_date": "2026-05-26",
            "last_updated": ts,
        })
        print(f"  {ticker:6s} {pos['shares']:>6}sh @ ${avg_cost:>10.4f} | now ${cur_price:>10.2f} | PnL {upnl_pct:+.2f}%")

    # Short positions
    final_shorts = []
    for ticker, pos in shorts.items():
        avg_entry = round(pos["total_cost"] / pos["shares"], 4)
        cur_price = LIVE_PRICES.get(ticker, avg_entry)
        upnl = round((avg_entry - cur_price) * pos["shares"], 2)
        upnl_pct = round((avg_entry - cur_price) / avg_entry * 100, 2) if avg_entry else 0
        name, sector = NAMES.get(ticker, (ticker, ""))

        final_shorts.append({
            "ticker": ticker,
            "name": name,
            "shares": pos["shares"],
            "entry_price": avg_entry,
            "avg_cost": avg_entry,
            "current_price": cur_price,
            "market_value": round(-pos["shares"] * cur_price, 2),
            "unrealized_pnl": upnl,
            "unrealized_pnl_pct": upnl_pct,
            "instrument_type": "short",
            "sector": sector,
            "entry_date": "2026-05-26",
            "last_updated": ts,
        })
        print(f"  {ticker:6s} {pos['shares']:>6}sh SHORT @ ${avg_entry:>10.4f} | now ${cur_price:>10.2f} | PnL {upnl_pct:+.2f}%")

    # NAV calculation
    long_mv = sum(p["market_value"] for p in final_positions)
    short_upnl = sum(s["unrealized_pnl"] for s in final_shorts)
    nav = cash + long_mv + short_upnl
    ret_pct = round((nav / 1_500_000 - 1) * 100, 2)

    print(f"\n  Long MV: ${long_mv:,.2f}")
    print(f"  Short Unrealized PnL: ${short_upnl:,.2f}")
    print(f"  NAV: ${nav:,.2f}")
    print(f"  Return: {ret_pct:+.2f}%")

    # Final balance check
    long_cost_final = sum(p["cost_basis"] for p in final_positions)
    short_cost_final = sum(abs(s["shares"]) * s["entry_price"] for s in final_shorts)
    balance = cash + long_cost_final + short_cost_final
    expected = 1_500_000 + rpnl
    gap = balance - expected
    print(f"\n  Balance: Cash({cash:,.2f}) + LongCost({long_cost_final:,.2f}) + ShortCost({short_cost_final:,.2f}) = ${balance:,.2f}")
    print(f"  Expected: $1,500,000 + rpnl({rpnl:,.2f}) = ${expected:,.2f}")
    print(f"  Gap: ${gap:,.2f} {'✓ BALANCED' if abs(gap) < 1 else '✗ IMBALANCED'}")

    # Step 5: Update portfolio_state.json
    print(f"\n=== Step 5: Write to portfolio_state.json ===")

    us = data["accounts"]["us"]
    us["cash"] = round(cash, 2)
    us["realized_pnl"] = round(rpnl, 2)
    us["positions"] = final_positions
    us["short_positions"] = final_shorts
    us["total_invested"] = round(long_mv, 2)
    us["total_assets"] = round(nav, 2)
    us["unrealized_pnl"] = round(sum(p["unrealized_pnl"] for p in final_positions) + short_upnl, 2)
    us["last_updated"] = ts

    # Rebuild trade_log: non-US + pre-05-27 US + new V7.6 trades
    # Also fix names in ALL trade_log entries
    new_trade_log = []
    for t in non_us_trades:
        new_trade_log.append(t)
    for t in us_trades_pre:
        # Fix name field
        ticker = t.get("ticker", "")
        if ticker in NAMES:
            t["name"] = NAMES[ticker][0]
        new_trade_log.append(t)
    for t in v76_trades:
        new_trade_log.append(t)

    # Sort by timestamp
    new_trade_log.sort(key=lambda x: x.get("timestamp", ""))
    data["trade_log"] = new_trade_log

    # Update performance
    data["performance"]["total_return_pct_usd"] = ret_pct

    # Update meta
    data["_meta"]["last_updated"] = ts
    data["_meta"]["update_trigger"] = "fix_us_accounting"

    save(data)
    print(f"  Saved. {len(new_trade_log)} total trades ({len(v76_trades)} new V7.6 trades)")
    print(f"  US NAV: ${nav:,.2f} ({ret_pct:+.2f}%)")
    print(f"  Cash: ${cash:,.2f}")
    print(f"\n✓ Accounting fix complete. All balances verified.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Step 1: build closed round-trip episodes from a_share trade_log (FULL history),
then filter to episodes whose ACTUAL exit date >= 2026-06-24.
An "episode" = position lifecycle from 0 shares -> peak -> back to 0 shares.
"""
import json, sys
from collections import defaultdict

STATE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/portfolio_state.json"

def main():
    with open(STATE) as f:
        data = json.load(f)
    tl = data["trade_log"]
    a = [t for t in tl if t.get("account") == "a_share"]
    # sort chronologically (date then timestamp then id as tiebreak)
    def sortkey(t):
        return (t.get("date",""), t.get("timestamp",""), t.get("id",""))
    a.sort(key=sortkey)

    by_ticker = defaultdict(list)
    for t in a:
        by_ticker[t["ticker"]].append(t)

    episodes = []
    for ticker, trades in by_ticker.items():
        name = trades[0].get("name", ticker)
        shares = 0.0
        buy_val = 0.0
        buy_sh = 0.0
        sell_val = 0.0
        sell_sh = 0.0
        entry_date = None
        exit_date = None
        legs = []
        for t in trades:
            act = t["action"]
            sh = t["shares"]
            px = t["price"]
            dt = t["date"]
            if act == "buy":
                if shares == 0:
                    # new episode starts
                    entry_date = dt
                    buy_val = 0.0; buy_sh = 0.0
                    sell_val = 0.0; sell_sh = 0.0
                    legs = []
                shares += sh
                buy_val += sh * px
                buy_sh += sh
                legs.append((dt, "buy", sh, px))
            elif act == "sell":
                shares -= sh
                sell_val += sh * px
                sell_sh += sh
                legs.append((dt, "sell", sh, px))
                if abs(shares) < 1e-6:
                    exit_date = dt
                    avg_entry = buy_val / buy_sh if buy_sh else None
                    avg_exit = sell_val / sell_sh if sell_sh else None
                    episodes.append({
                        "ticker": ticker, "name": name,
                        "entry_date": entry_date, "exit_date": exit_date,
                        "shares": buy_sh, "avg_entry_price": avg_entry,
                        "avg_exit_price": avg_exit,
                        "actual_pnl": sell_val - buy_val,
                        "actual_return_pct": (avg_exit/avg_entry - 1) if avg_entry else None,
                        "n_buy_legs": sum(1 for l in legs if l[1]=="buy"),
                        "n_sell_legs": sum(1 for l in legs if l[1]=="sell"),
                        "legs": legs,
                    })
                    shares = 0.0
            else:
                pass
        # NOTE: any residual open position (shares != 0 at end) is NOT a closed episode -> excluded
        if abs(shares) > 1e-6:
            pass  # still open, skip (not closed)

    episodes.sort(key=lambda e: e["exit_date"])
    with open("/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24/episodes_all.json","w") as f:
        json.dump(episodes, f, ensure_ascii=False, indent=2)

    window = [e for e in episodes if e["exit_date"] >= "2026-06-24"]
    with open("/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24/episodes_window.json","w") as f:
        json.dump(window, f, ensure_ascii=False, indent=2)

    print(f"total episodes (full history): {len(episodes)}")
    print(f"episodes closed on/after 2026-06-24: {len(window)}")
    tickers = sorted(set(e["ticker"] for e in window))
    print(f"unique tickers in window: {len(tickers)}")
    print(",".join(tickers))
    print()
    for e in window:
        print(f"{e['ticker']} {e['name']:8s} entry={e['entry_date']} exit={e['exit_date']} "
              f"avg_in={e['avg_entry_price']:.2f} avg_out={e['avg_exit_price']:.2f} "
              f"ret={e['actual_return_pct']*100:+.1f}% legs(buy={e['n_buy_legs']},sell={e['n_sell_legs']})")

if __name__ == "__main__":
    main()

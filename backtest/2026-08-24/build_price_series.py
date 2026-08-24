"""
Step 1: build FIFO-matched closed round-trip trades from portfolio_state.json trade_log,
aggregated by (ticker, exit_date). Restricted to account=='a_share'.
Then fetch daily OHLCV via akshare (sina source, D12-compliant, non-yfinance) for all
tickers involved, 2026-04-01 -> 2026-08-21 (last complete session before today 08-24).
Output files (scratchpad, per file-location rule):
  agg_closed_trades.json  - 60 aggregated closed trades w/ exit_date >= 2026-06-24
  price_data.json         - {ticker: [[date,open,high,low,close,volume], ...]} 04-01..08-21
"""
import json
from collections import defaultdict, deque
import akshare as ak

PORTFOLIO = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/portfolio_state.json"
SCRATCH = "/private/tmp/claude-501/-Users-huaichuaibeimeng-claude-projects/0271364f-8cab-4319-af5d-5048f0719e12/scratchpad"

def build_closed_trades():
    d = json.load(open(PORTFOLIO))
    tl = d["trade_log"]
    a = [t for t in tl if t.get("account") == "a_share"]
    a.sort(key=lambda t: (t["date"], t.get("timestamp", "")))

    lots = defaultdict(deque)
    closed = []
    for t in a:
        ticker, action, shares, price, date = t["ticker"], t["action"], t["shares"], t["price"], t["date"]
        name = t.get("name", "")
        if action == "buy":
            lots[ticker].append({"shares": shares, "price": price, "date": date})
        elif action == "sell":
            remaining = shares
            while remaining > 0 and lots[ticker]:
                lot = lots[ticker][0]
                take = min(remaining, lot["shares"])
                closed.append({
                    "ticker": ticker, "name": name,
                    "entry_date": lot["date"], "entry_price": lot["price"],
                    "exit_date": date, "exit_price": price, "shares": take,
                    "pnl": (price - lot["price"]) * take,
                })
                lot["shares"] -= take
                remaining -= take
                if lot["shares"] <= 0:
                    lots[ticker].popleft()
            if remaining > 0:
                print(f"WARNING oversell {ticker} {date} remaining={remaining}")

    window = [c for c in closed if c["exit_date"] >= "2026-06-24"]
    groups = defaultdict(list)
    for c in window:
        groups[(c["ticker"], c["exit_date"])].append(c)

    agg = []
    for (ticker, exit_date), lst in groups.items():
        total_shares = sum(x["shares"] for x in lst)
        total_cost = sum(x["shares"] * x["entry_price"] for x in lst)
        avg_entry = total_cost / total_shares
        total_pnl = sum(x["pnl"] for x in lst)
        exit_price = lst[0]["exit_price"]
        # anchor = date of the LAST lot addition, not earliest. Rationale: when a position
        # is built via buy->partial_sell->buy_more->full_sell, FIFO lot-matching can leave a
        # tiny leftover slice from an old, cheap lot blended into a later high-cost lot inside
        # the SAME closing sale (e.g. 002049: 1700sh@71.33 from 06-11 + 10700sh@88.75 from
        # 06-30, closed together on 07-16). Anchoring the mechanical-rule replay on the
        # earliest date (06-11) while using the blended avg cost (86.36, dominated by the
        # 06-30 lot) produces a false near-immediate "trigger" the day after 06-11 that has
        # nothing to do with when that blended cost basis actually existed. Anchoring on the
        # LAST lot date instead means: start monitoring only after the final add-on is the
        # point where this avg cost basis came into being. Verified affects 5/60 groups,
        # materially only 002049 (19-day gap); other 4 are same-week adds (1-8 day gap).
        entry_dates = [x["entry_date"] for x in lst]
        agg.append({
            "ticker": ticker, "name": lst[0]["name"],
            "entry_date_earliest": min(entry_dates),
            "entry_date_anchor": max(entry_dates),
            "avg_entry_price": round(avg_entry, 4),
            "exit_date": exit_date, "exit_price": exit_price,
            "shares": total_shares, "actual_pnl": round(total_pnl, 2),
            "actual_pnl_pct": round((exit_price - avg_entry) / avg_entry * 100, 3),
            "n_lots": len(lst),
        })
    agg.sort(key=lambda x: x["exit_date"])
    json.dump(agg, open(f"{SCRATCH}/agg_closed_trades.json", "w"), ensure_ascii=False, indent=2)
    print(f"aggregated closed trades (exit>=2026-06-24): {len(agg)}")
    return agg

def fetch_prices(tickers):
    def prefix(t):
        return "sh" + t if t.startswith("6") else "sz" + t
    data, errors = {}, []
    for tk in tickers:
        try:
            df = ak.stock_zh_a_daily(symbol=prefix(tk), start_date="20260401", end_date="20260821", adjust="")
            data[tk] = df[["date", "open", "high", "low", "close", "volume"]].values.tolist()
        except Exception as e:
            errors.append((tk, str(e)))
    json.dump(data, open(f"{SCRATCH}/price_data.json", "w"), default=str)
    print(f"price fetch: success={len(data)} errors={len(errors)} {errors}")

if __name__ == "__main__":
    agg = build_closed_trades()
    tickers = sorted(set(x["ticker"] for x in agg))
    fetch_prices(tickers)

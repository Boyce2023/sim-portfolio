"""
Rebuild agg_closed_trades.json from the FROZEN lot-level snapshot (closed_trades.json,
captured 2026-08-24 ~11:48-11:50 BJT) instead of re-reading portfolio_state.json live.
Reason: portfolio_state.json is a live, actively-traded file (other concurrent
sessions/automation kept adding trades while this backtest was being built --
trade_count went 243->245, a_share log 220->222 entries between 11:48 and 11:58).
Re-reading mid-analysis would silently change the sample (n=60->62) and break
reproducibility. This script re-derives the aggregation (with the corrected
entry_date_anchor = max lot date, not min) from the frozen snapshot so the
analysis stays pinned to n=60, exit_date in [2026-06-24, 2026-08-24 as of first read].
"""
import json
from collections import defaultdict

SCRATCH = "/private/tmp/claude-501/-Users-huaichuaibeimeng-claude-projects/0271364f-8cab-4319-af5d-5048f0719e12/scratchpad"

closed = json.load(open(f"{SCRATCH}/closed_trades.json"))
groups = defaultdict(list)
for c in closed:
    groups[(c["ticker"], c["exit_date"])].append(c)

agg = []
for (ticker, exit_date), lst in groups.items():
    total_shares = sum(x["shares"] for x in lst)
    total_cost = sum(x["shares"] * x["entry_price"] for x in lst)
    avg_entry = total_cost / total_shares
    total_pnl = sum(x["pnl"] for x in lst)
    exit_price = lst[0]["exit_price"]
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
print(f"rebuilt {len(agg)} aggregated closed trades from frozen snapshot (n should = 60)")

#!/usr/bin/env python3
"""Scale US portfolio from $150K to $1.5M (10x).

Modifies portfolio_state.json:
  - initial_capital: 150K → 1.5M
  - cash: ×10
  - positions: shares ×10, market_value ×10 (prices unchanged)
  - short_positions: shares ×10 (prices unchanged)
  - total_invested, total_assets, realized_pnl, unrealized_pnl: ×10
  - daily_snapshots: us_nav ×10 (return_pct unchanged)
  - trade_log: shares ×10, value ×10, price ×10 (price unchanged)
  - cash_plan dollar amounts: ×10

Also updates:
  - playbook.json: pnl dollar amounts ×10
  - conviction_scorecard.json: no dollar amounts to change
  - gen_leaderboard.py: description string

Does NOT change:
  - Prices (entry_price, stop_loss, current_price)
  - Percentages (return_pct, unrealized_pnl_pct)
  - R-multiples (dimensionless)
"""

import json
from pathlib import Path

SCALE = 10
ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO = ROOT / "portfolio_state.json"
PLAYBOOK = ROOT / "playbook.json"

def scale_portfolio():
    with open(PORTFOLIO) as f:
        data = json.load(f)

    us = data["accounts"]["us"]
    old_init = us["initial_capital"]

    # Account-level
    us["initial_capital"] = old_init * SCALE
    us["cash"] = round(us["cash"] * SCALE, 2)
    us["total_invested"] = round(us.get("total_invested", 0) * SCALE, 2)
    us["total_assets"] = round(us.get("total_assets", 0) * SCALE, 2)
    us["realized_pnl"] = round(us.get("realized_pnl", 0) * SCALE, 4)
    us["unrealized_pnl"] = round(us.get("unrealized_pnl", 0) * SCALE, 2)

    # Long positions
    for p in us.get("positions", []):
        p["shares"] = p["shares"] * SCALE
        if "market_value" in p:
            p["market_value"] = round(p["market_value"] * SCALE, 2)
        if "cost_basis" in p:
            p["cost_basis"] = round(p["cost_basis"] * SCALE, 2)
        if "unrealized_pnl" in p:
            p["unrealized_pnl"] = round(p["unrealized_pnl"] * SCALE, 2)

    # Short positions
    for p in us.get("short_positions", []):
        p["shares"] = p["shares"] * SCALE

    # Trade log
    for t in data.get("trade_log", []):
        if t.get("account") == "us" or t.get("currency") == "USD":
            t["shares"] = t.get("shares", 0) * SCALE
            if "value" in t:
                t["value"] = round(t["value"] * SCALE, 2)

    # Daily snapshots
    for s in data.get("performance", {}).get("daily_snapshots", []):
        if "us_nav" in s:
            s["us_nav"] = round(s["us_nav"] * SCALE, 2)

    # Cash plan
    cp = us.get("cash_plan", {})
    if isinstance(cp, dict):
        for key, val in cp.items():
            if isinstance(val, (int, float)) and key not in ("pct",):
                cp[key] = round(val * SCALE, 2)

    with open(PORTFOLIO, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    new_init = us["initial_capital"]
    print(f"[OK] US portfolio scaled {SCALE}x: ${old_init:,.0f} → ${new_init:,.0f}")
    print(f"  Cash: ${us['cash']:,.2f}")
    print(f"  Positions:")
    for p in us.get("positions", []):
        print(f"    {p['ticker']:8s} {p['shares']:>6} sh  mv=${p.get('market_value',0):,.2f}")
    for p in us.get("short_positions", []):
        print(f"    {p['ticker']:8s} {p['shares']:>6} sh (short)")

def scale_playbook():
    if not PLAYBOOK.exists():
        return
    with open(PLAYBOOK) as f:
        pb = json.load(f)

    for pat in pb.get("patterns", []):
        for inst in pat.get("instances", []):
            if "pnl" in inst:
                pnl_str = inst["pnl"]
                if isinstance(pnl_str, str) and "$" in pnl_str:
                    import re
                    match = re.search(r'[\+\-]?\$?([\d,]+)', pnl_str)
                    if match:
                        old_val = int(match.group(1).replace(",", ""))
                        new_val = old_val * SCALE
                        inst["pnl"] = pnl_str.replace(match.group(1), f"{new_val:,}")

    with open(PLAYBOOK, "w") as f:
        json.dump(pb, f, indent=2, ensure_ascii=False)
    print(f"[OK] playbook.json PnL amounts scaled {SCALE}x")

if __name__ == "__main__":
    scale_portfolio()
    scale_playbook()
    print("\n[DONE] Run `python3 web/gen_leaderboard.py` to regenerate website.")

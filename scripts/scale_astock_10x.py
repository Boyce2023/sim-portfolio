#!/usr/bin/env python3
"""Scale A-share portfolio from ¥1M to ¥10M base. One-time migration."""
import json
from pathlib import Path
from datetime import datetime

PSJ = Path(__file__).parent.parent / "portfolio_state.json"

with open(PSJ) as f:
    data = json.load(f)

a = data["accounts"]["a_share"]

# Account-level 10x
a["initial_capital"] *= 10
a["cash"] *= 10
a["total_invested"] *= 10
a["total_assets"] *= 10
a["realized_pnl"] *= 10
a["unrealized_pnl"] *= 10

# Positions 10x
for pos in a["positions"]:
    pos["shares"] *= 10
    pos["cost_basis"] *= 10
    pos["market_value"] *= 10
    pos["unrealized_pnl"] *= 10
    # Per-share prices stay the same: avg_cost, current_price, stop_loss, target_1, target_2, prev_close
    # Percentages stay the same: portfolio_pct, unrealized_pnl_pct, stop_loss_pct, change_pct, bear_case_downside
    
    # Fix 安集科技 bear_case_downside bug
    if pos["ticker"] == "688019" and pos.get("bear_case_downside") == -18:
        pos["bear_case_downside"] = -0.18
        print(f"  FIXED: 安集科技 bear_case_downside -18 → -0.18")

# Cash plan reserve buckets 10x
if "cash_plan" in a:
    cp = a["cash_plan"]
    if "reserve_buckets" in cp:
        for bucket in cp["reserve_buckets"]:
            bucket["amount"] *= 10

# Performance daily snapshots: a_share values 10x
if "performance" in data:
    perf = data["performance"]
    if "total_return_cny" in perf:
        perf["total_return_cny"] *= 10
    for snap in perf.get("daily_snapshots", []):
        if "a_share_nav" in snap and snap["a_share_nav"] is not None:
            snap["a_share_nav"] *= 10
        if "a_share_daily_pnl" in snap and snap["a_share_daily_pnl"] is not None:
            snap["a_share_daily_pnl"] *= 10
        # Percentages stay the same: a_share_return_pct, a_share_alpha

# Trade log: A-share trades 10x
for trade in data.get("trade_log", []):
    if trade.get("account") == "a_share":
        trade["shares"] *= 10
        trade["value"] *= 10
        if "realized_pnl" in trade:
            trade["realized_pnl"] *= 10

# Update meta
data["_meta"]["last_updated"] = datetime.now().astimezone().isoformat()
data["_meta"]["note"] = "v7.0升级: A股基金规模10x至¥10M. SABCT v3.0大调仓. Regime=BULL. 8L+1S."

with open(PSJ, "w") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

# Verify
with open(PSJ) as f:
    v = json.load(f)
va = v["accounts"]["a_share"]
print(f"\n=== A股 10x 验证 ===")
print(f"初始资金: ¥{va['initial_capital']:,.0f}")
print(f"现金: ¥{va['cash']:,.0f}")
print(f"总资产: ¥{va['total_assets']:,.0f}")
print(f"已实现盈亏: ¥{va['realized_pnl']:,.0f}")
print(f"持仓数: {len(va['positions'])}")
for p in va["positions"]:
    print(f"  {p['name']}: {p['shares']}股 × ¥{p['current_price']} = ¥{p['market_value']:,.0f} | bear_case: {p.get('bear_case_downside','N/A')}")
print(f"\n安集科技 bear_case_downside = {[p for p in va['positions'] if p['ticker']=='688019'][0]['bear_case_downside']}")

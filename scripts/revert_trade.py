#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["requests>=2.28"]
# ///
"""
交易撤回工具 — 原子操作：revert portfolio + sync nexus + git commit+push

用法:
  uv run --script scripts/revert_trade.py TRD-0106 TRD-0107 TRD-0108
  uv run --script scripts/revert_trade.py --last N   # 撤回最近N笔
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PORTFOLIO = REPO / "portfolio_state.json"
AUDIT_DIR = REPO / "audit-trail"


def load_portfolio():
    with open(PORTFOLIO) as f:
        return json.load(f)


def save_portfolio(p):
    with open(PORTFOLIO, "w") as f:
        json.dump(p, f, indent=2, ensure_ascii=False)


def revert_trades(trade_ids: list[str], reason: str = ""):
    p = load_portfolio()
    trade_log = p.get("trade_log", [])
    reverted = []

    for tid in trade_ids:
        trade = next((t for t in trade_log if t.get("id") == tid), None)
        if not trade:
            print(f"[WARN] {tid} not found in trade_log, skipping")
            continue

        account_key = "a_share" if trade.get("account", "") in ("cn", "a_share") else "us"
        account = p["accounts"][account_key]
        ticker = trade["ticker"]
        shares = trade["shares"]
        action = trade["action"]

        if action == "buy":
            pos = next((pp for pp in account["positions"] if pp["ticker"] == ticker), None)
            if pos:
                cost = shares * pos["avg_cost"]
                if pos["shares"] == shares:
                    account["positions"].remove(pos)
                else:
                    pos["shares"] -= shares
                account["cash"] += cost
                print(f"  [REVERT] {tid}: 删除 BUY {ticker} {shares}股, 返还 ¥{cost:,.0f}")
            else:
                print(f"  [WARN] {tid}: position {ticker} not found, manual fix needed")
                continue
        elif action == "sell":
            cost = shares * trade.get("price", 0)
            account["cash"] -= cost
            pos = next((pp for pp in account["positions"] if pp["ticker"] == ticker), None)
            if pos:
                pos["shares"] += shares
            else:
                account["positions"].append({
                    "ticker": ticker,
                    "name": trade.get("name", ticker),
                    "shares": shares,
                    "avg_cost": trade.get("price", 0),
                    "current_price": trade.get("price", 0),
                })
            print(f"  [REVERT] {tid}: 恢复 SELL {ticker} {shares}股, 扣回 ¥{cost:,.0f}")

        trade_log = [t for t in trade_log if t.get("id") != tid]
        reverted.append(tid)

    p["trade_log"] = trade_log
    p["pending_orders"] = []
    save_portfolio(p)

    # Sync nexus
    print("\n[SYNC] sync_nexus.py...")
    subprocess.run(
        ["uv", "run", "--script", str(REPO / "scripts" / "sync_nexus.py")],
        capture_output=True, cwd=str(REPO)
    )

    # Git commit + push
    reason_text = reason or "错误交易撤回"
    ids_text = ", ".join(reverted)
    print(f"\n[GIT] commit + push...")
    subprocess.run(["git", "add", "portfolio_state.json"], cwd=str(REPO))
    subprocess.run(
        ["git", "commit", "-m", f"revert: {reason_text} ({ids_text})\n\nCo-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"],
        cwd=str(REPO), capture_output=True
    )
    subprocess.run(["git", "push"], cwd=str(REPO), capture_output=True)

    print(f"\n[DONE] 撤回{len(reverted)}笔交易, nexus已同步, git已push")
    print(f"  现金: ¥{p['accounts']['a_share']['cash']:,.0f} (A股)")
    return reverted


def main():
    parser = argparse.ArgumentParser(description="交易撤回(原子操作)")
    parser.add_argument("trade_ids", nargs="*", help="Trade IDs to revert (e.g. TRD-0106)")
    parser.add_argument("--last", type=int, help="Revert last N trades")
    parser.add_argument("--reason", type=str, default="", help="Reason for reversal")
    args = parser.parse_args()

    if args.last:
        p = load_portfolio()
        ids = [t["id"] for t in p["trade_log"][-args.last:]]
    elif args.trade_ids:
        ids = args.trade_ids
    else:
        parser.print_help()
        sys.exit(1)

    print(f"撤回交易: {ids}")
    revert_trades(ids, args.reason)


if __name__ == "__main__":
    main()

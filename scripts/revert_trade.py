#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
交易撤回 — 调用 portfolio_io 模块完成原子操作。

用法:
  uv run --script scripts/revert_trade.py TRD-0106 TRD-0107
  uv run --script scripts/revert_trade.py --last 3
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from portfolio_io import load_portfolio, revert_trades


def main():
    parser = argparse.ArgumentParser(description="交易撤回(原子操作)")
    parser.add_argument("trade_ids", nargs="*", help="Trade IDs (e.g. TRD-0106)")
    parser.add_argument("--last", type=int, help="Revert last N trades")
    parser.add_argument("--reason", type=str, default="", help="Reason")
    args = parser.parse_args()

    if args.last:
        p = load_portfolio()
        ids = [t["id"] for t in p["trade_log"][-args.last:]]
    elif args.trade_ids:
        ids = args.trade_ids
    else:
        parser.print_help()
        sys.exit(1)

    print(f"撤回: {ids}")
    revert_trades(ids, args.reason)


if __name__ == "__main__":
    main()

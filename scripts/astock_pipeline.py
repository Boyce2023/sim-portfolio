# /// script
# requires-python = ">=3.11"
# dependencies = ["akshare>=1.14", "yfinance>=0.2", "requests>=2.28", "baostock>=0.8"]
# ///
"""
A股统一Pipeline — 一条命令: 更新价格 → UASS扫描 → 同步nexus-package

用法:
  uv run --script scripts/astock_pipeline.py              # 全流程
  uv run --script scripts/astock_pipeline.py --skip-sync   # 跳过nexus同步
  uv run --script scripts/astock_pipeline.py --scan-only    # 仅UASS扫描
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
NEXUS_PKG = REPO.parent / "nexus-package"
TZ_BEIJING = timezone(timedelta(hours=8))


def step_update_prices() -> bool:
    print("\n" + "=" * 50)
    print("Step 1: 更新价格")
    print("=" * 50)
    t0 = time.time()

    sys.path.insert(0, str(REPO / "scripts"))
    try:
        from fetch_prices import (
            fetch_all_from_portfolio, save_prices_atomic,
            fetch_benchmark_prices, PORTFOLIO_PATH, PRICES_OUTPUT,
        )

        with open(PORTFOLIO_PATH, encoding="utf-8") as f:
            state = json.load(f)

        prices = fetch_all_from_portfolio(state)
        benchmarks = fetch_benchmark_prices()
        prices["benchmarks"] = benchmarks

        save_prices_atomic(prices, PRICES_OUTPUT)

        us_count = len(prices.get("us", {}))
        cn_count = len(prices.get("cn", {}))
        elapsed = time.time() - t0
        print(f"[OK] 价格更新: US={us_count} CN={cn_count} ({elapsed:.1f}s)")
        return True
    except Exception as e:
        elapsed = time.time() - t0
        print(f"[FAIL] 价格更新: {e} ({elapsed:.1f}s)")
        return False


def step_uass_scan(date_str: str | None = None, top_n: int = 25) -> bool:
    print("\n" + "=" * 50)
    print("Step 2: UASS扫描")
    print("=" * 50)
    t0 = time.time()

    try:
        from uass_scan import fetch_all, auto_score_trackb, batch_chip_health
        from uass_scan import find_supply_chain_candidates, print_summary, SCAN_OUTPUT

        if not date_str:
            now = datetime.now()
            if now.hour < 15:
                date_str = (now - timedelta(days=1)).strftime("%Y%m%d")
            else:
                date_str = now.strftime("%Y%m%d")

        print(f"UASS扫描 | 日期: {date_str}")
        print("-" * 40)

        data = fetch_all(date_str)
        scored = auto_score_trackb(data)

        d6_top = min(40, len(scored))
        print(f"D6 筹码体检中 (TOP{d6_top})...")
        batch_chip_health(scored, top_n=d6_top)
        scored.sort(key=lambda x: x["TB总分"], reverse=True)

        flagged = [
            f"{s['名称']}({','.join(s.get('D6_flags', []))})"
            for s in scored[:30]
            if s.get("D6_flags") and "HEALTHY" not in s.get("D6_flags", [])
        ]
        print(f"D6 完成 | 标记: {', '.join(flagged) or '全部健康'}")

        chains = find_supply_chain_candidates(scored, data["sector_flow"])

        output = {
            "scan_date": date_str,
            "scan_time": datetime.now().isoformat(),
            "market_summary": {
                "涨停数": len(data["zt_pool"]),
                "强势非涨停数": len(data.get("strong_movers", [])),
                "龙虎榜数": len(data["lhb"]),
                "北向净买_亿": data.get("northbound", {}).get("净买额_亿", None),
            },
            "sector_flow_top10": data["sector_flow"][:10],
            "concept_flow_top10": data.get("concept_flow", [])[:10],
            "trackb_scored": scored,
            "supply_chain_candidates": chains,
            "errors": data["errors"],
        }
        with open(SCAN_OUTPUT, "w") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        print_summary(data, scored, chains, top_n)
        elapsed = time.time() - t0
        print(f"\n[OK] UASS完成 ({elapsed:.1f}s)")
        return True
    except Exception as e:
        elapsed = time.time() - t0
        print(f"[FAIL] UASS扫描: {e} ({elapsed:.1f}s)")
        import traceback
        traceback.print_exc()
        return False


def step_sync_nexus() -> bool:
    print("\n" + "=" * 50)
    print("Step 3: 同步nexus-package")
    print("=" * 50)

    sim_portfolio_json = NEXUS_PKG / "output-buffer" / "sim-portfolio.json"
    if not NEXUS_PKG.exists():
        print("[SKIP] nexus-package目录不存在")
        return True

    try:
        with open(REPO / "portfolio_state.json", encoding="utf-8") as f:
            state = json.load(f)

        accounts = state.get("accounts", {})
        now_ts = datetime.now(TZ_BEIJING).isoformat()

        public = {
            "meta": {
                "type": "sim_portfolio",
                "description": "Claude AI模拟盘 — ¥10M A股 + $1.5M 美股",
                "start_date": state.get("_meta", {}).get("start_date", ""),
                "end_date": state.get("_meta", {}).get("end_date", ""),
                "last_updated": now_ts,
                "synced_from": "portfolio_state.json",
                "benchmark": {"a_share": "CSI300", "us": "SPY"},
                "disclaimer": "模拟盘，非真实交易。仅供研究参考。",
            },
            "accounts": {},
        }

        for acct_key in ("a_share", "us"):
            acct = accounts.get(acct_key, {})
            positions = []
            for p in acct.get("positions", []):
                ticker = p.get("ticker", "")
                if acct_key == "a_share":
                    suffix = ".SS" if ticker.startswith("6") else ".SZ"
                    ticker = ticker + suffix
                positions.append({
                    "ticker": ticker,
                    "name": p.get("name", ""),
                    "shares": p.get("shares", 0),
                    "avg_cost": p.get("avg_cost", 0),
                    "current_price": p.get("current_price", 0),
                    "market_value": p.get("market_value", 0),
                    "unrealized_pnl_pct": p.get("unrealized_pnl_pct", 0),
                    "portfolio_pct": p.get("portfolio_pct", 0),
                    "entry_date": p.get("entry_date", ""),
                    "type": p.get("type", ""),
                    "sector": p.get("sector", ""),
                })
            public["accounts"][acct_key] = {
                "currency": acct.get("currency", ""),
                "initial_capital": acct.get("initial_capital", 0),
                "total_assets": acct.get("total_assets", 0),
                "cash": acct.get("cash", 0),
                "realized_pnl": acct.get("realized_pnl", 0),
                "return_pct": round(
                    (acct.get("total_assets", 0) / acct.get("initial_capital", 1) - 1) * 100, 2
                ) if acct.get("initial_capital", 0) > 0 else 0,
                "positions": positions,
            }

        with open(sim_portfolio_json, "w", encoding="utf-8") as f:
            json.dump(public, f, indent=2, ensure_ascii=False)

        print(f"[OK] sim-portfolio.json已同步 ({len(positions)}个持仓)")
        return True
    except Exception as e:
        print(f"[FAIL] nexus同步: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="A股统一Pipeline")
    parser.add_argument("--skip-sync", action="store_true", help="跳过nexus-package同步")
    parser.add_argument("--scan-only", action="store_true", help="仅UASS扫描")
    parser.add_argument("--date", type=str, help="扫描日期 YYYYMMDD")
    parser.add_argument("--top", type=int, default=25, help="显示TOP N")
    args = parser.parse_args()

    t_start = time.time()
    print("=" * 50)
    print(f"A股Pipeline | {datetime.now(TZ_BEIJING).strftime('%Y-%m-%d %H:%M')}")
    print("=" * 50)

    if args.scan_only:
        ok = step_uass_scan(args.date, args.top)
    else:
        ok = step_update_prices()
        if ok:
            ok = step_uass_scan(args.date, args.top)
        if ok and not args.skip_sync:
            step_sync_nexus()

    total = time.time() - t_start
    print(f"\nPipeline完成 — 总耗时 {total:.1f}s")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

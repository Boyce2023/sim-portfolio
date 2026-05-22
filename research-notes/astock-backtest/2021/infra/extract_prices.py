#!/usr/bin/env python3
"""Extract price data for a specific date range from the 2021 price DB.
Usage: python3 extract_prices.py START_DATE END_DATE [--verify-days 10]
Example: python3 extract_prices.py 2021-01-04 2021-01-15
Outputs compact JSON to stdout with prices + sector analysis + forward returns.
"""
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///

import json, sys, os
from collections import defaultdict

DB_PATH = os.path.join(os.path.dirname(__file__), "price_db_2021.json")

SECTORS = {
    "半导体": ["002371","688012","688019","603501","603986","600584"],
    "光伏新能源": ["601012","600438","002129","002459","300274"],
    "锂电EV": ["300750","002594","002466","002460","300014"],
    "PCB消费电子": ["002475","002273","002916","002938","002463","300433"],
    "智能驾驶": ["002920","002906","300496"],
    "机器人制造": ["688017","300124","002747"],
    "医药": ["603259","300760","600276"],
    "电力电网": ["600406","600900","002028"],
    "资源": ["600188","601225","601899","600988"],
    "消费白酒": ["600519","000858","603288","600809"],
    "其他": ["000333","601888","002607","002472","002241"],
}

def main():
    if len(sys.argv) < 3:
        print("Usage: python3 extract_prices.py START END [--verify-days N]")
        sys.exit(1)

    start, end = sys.argv[1], sys.argv[2]
    verify_days = 10
    if "--verify-days" in sys.argv:
        idx = sys.argv.index("--verify-days")
        verify_days = int(sys.argv[idx+1])

    with open(DB_PATH, encoding="utf-8") as f:
        db = json.load(f)

    # Get full trading calendar from any stock
    sample = next(iter(db["stocks"].values()))
    all_dates = [r["date"] for r in sample["daily_prices"]]

    # Find date indices
    try:
        si = all_dates.index(start)
    except ValueError:
        # Find nearest
        si = next(i for i, d in enumerate(all_dates) if d >= start)
    try:
        ei = all_dates.index(end)
    except ValueError:
        ei = next(i for i, d in enumerate(all_dates) if d >= end)

    range_dates = all_dates[si:ei+1]
    verify_end = min(ei + verify_days, len(all_dates) - 1)
    extended_dates = all_dates[si:verify_end+1]

    # Lookback for context (20 days before range start)
    lookback_start = max(0, si - 20)
    lookback_dates = all_dates[lookback_start:si]

    output = {
        "range": {"start": range_dates[0], "end": range_dates[-1], "trading_days": len(range_dates)},
        "verify_window": verify_days,
        "stocks": {},
        "sector_performance": {},
        "daily_rankings": {}
    }

    # Extract per-stock data
    for code, info in db["stocks"].items():
        prices = {r["date"]: r for r in info["daily_prices"]}
        range_prices = [prices[d] for d in extended_dates if d in prices]
        lookback_prices = [prices[d] for d in lookback_dates if d in prices]

        if not range_prices:
            continue

        # Calculate lookback momentum (20d before range start)
        lb_return = None
        if lookback_prices and len(lookback_prices) >= 2:
            lb_return = round((lookback_prices[-1]["close"] / lookback_prices[0]["close"] - 1) * 100, 2)

        # Per-day data within range
        daily = []
        for d in range_dates:
            if d not in prices:
                continue
            p = prices[d]
            prev_d_idx = all_dates.index(d) - 1
            prev_close = None
            if prev_d_idx >= 0:
                prev_d = all_dates[prev_d_idx]
                if prev_d in prices:
                    prev_close = prices[prev_d]["close"]

            day_return = round((p["close"] / prev_close - 1) * 100, 2) if prev_close else None

            # 10-day forward returns
            fwd_prices = []
            d_idx = all_dates.index(d)
            for fi in range(1, verify_days + 1):
                fwd_idx = d_idx + fi
                if fwd_idx < len(all_dates) and all_dates[fwd_idx] in prices:
                    fwd_prices.append(prices[all_dates[fwd_idx]]["close"])

            fwd_max = round((max(fwd_prices) / p["close"] - 1) * 100, 2) if fwd_prices else None
            fwd_close = round((fwd_prices[-1] / p["close"] - 1) * 100, 2) if fwd_prices else None

            daily.append({
                "date": d,
                "open": p["open"], "close": p["close"], "high": p["high"], "low": p["low"],
                "volume": p["volume"],
                "day_return_pct": day_return,
                "fwd_10d_max_pct": fwd_max,
                "fwd_10d_close_pct": fwd_close,
            })

        output["stocks"][code] = {
            "name": info["name"],
            "lookback_20d_return_pct": lb_return,
            "daily": daily
        }

    # Sector performance for each day in range
    for d in range_dates:
        day_sectors = {}
        for sector, codes in SECTORS.items():
            returns = []
            for c in codes:
                if c in output["stocks"]:
                    for dp in output["stocks"][c]["daily"]:
                        if dp["date"] == d and dp["day_return_pct"] is not None:
                            returns.append(dp["day_return_pct"])
            if returns:
                day_sectors[sector] = round(sum(returns) / len(returns), 2)
        output["sector_performance"][d] = dict(sorted(day_sectors.items(), key=lambda x: x[1], reverse=True))

    # Daily top movers for each day
    for d in range_dates:
        movers = []
        for code, sdata in output["stocks"].items():
            for dp in sdata["daily"]:
                if dp["date"] == d and dp["day_return_pct"] is not None:
                    movers.append((code, sdata["name"], dp["day_return_pct"]))
        movers.sort(key=lambda x: x[2], reverse=True)
        output["daily_rankings"][d] = {
            "top5": [{"code": c, "name": n, "ret": r} for c, n, r in movers[:5]],
            "bottom5": [{"code": c, "name": n, "ret": r} for c, n, r in movers[-5:]],
        }

    json.dump(output, sys.stdout, ensure_ascii=False, indent=1)

if __name__ == "__main__":
    main()

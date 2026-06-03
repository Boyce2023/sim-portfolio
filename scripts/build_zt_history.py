# /// script
# requires-python = ">=3.10"
# dependencies = ["baostock>=0.8", "pandas>=2.0"]
# ///
"""Build historical limit-up (涨停) database from baostock K-line data.

Usage:
  uv run --script scripts/build_zt_history.py --batch 0 --total-batches 10 --start 20260302 --end 20260513 --output /tmp/zt_batch_0.json

This script queries baostock for a batch of A-share stocks and identifies
limit-up events (pctChg >= threshold) for each trading day. The output
can be aggregated across batches to produce a complete historical limit-up database.

Limit-up thresholds:
  Main board (60xxxx, 000xxx, 001xxx, 002xxx, 003xxx): 9.8% (allow for rounding)
  ChiNext (300xxx): 19.5%
  STAR Market (688xxx): 19.5%
  ST stocks (name contains ST): 4.8%
"""

import json, sys, time
from datetime import datetime, timedelta
from pathlib import Path

import baostock as bs
import pandas as pd


def get_limit_threshold(code: str, name: str = "") -> float:
    bare = code.split(".")[-1] if "." in code else code
    if "ST" in name.upper():
        return 4.8
    if bare.startswith("300") or bare.startswith("301"):
        return 19.5
    if bare.startswith("688") or bare.startswith("689"):
        return 19.5
    if bare.startswith("8"):
        return 29.5
    return 9.8


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=int, required=True)
    parser.add_argument("--total-batches", type=int, required=True)
    parser.add_argument("--start", required=True, help="YYYYMMDD")
    parser.add_argument("--end", required=True, help="YYYYMMDD")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    lg = bs.login()
    if lg.error_code != '0':
        print(f"Login failed: {lg.error_msg}")
        sys.exit(1)

    rs = bs.query_stock_industry()
    all_stocks = []
    while rs.error_code == '0' and rs.next():
        row = rs.get_row_data()
        all_stocks.append({
            "code": row[1],
            "name": row[2],
            "industry": row[3],
        })

    print(f"Total stocks with industry: {len(all_stocks)}")

    batch_size = len(all_stocks) // args.total_batches
    start_idx = args.batch * batch_size
    end_idx = start_idx + batch_size if args.batch < args.total_batches - 1 else len(all_stocks)
    batch = all_stocks[start_idx:end_idx]
    print(f"Batch {args.batch}: stocks {start_idx}-{end_idx} ({len(batch)} stocks)")

    start_date = f"{args.start[:4]}-{args.start[4:6]}-{args.start[6:8]}"
    end_date = f"{args.end[:4]}-{args.end[4:6]}-{args.end[6:8]}"

    zt_events = {}
    success = 0
    fail = 0

    for i, stock in enumerate(batch):
        if i % 100 == 0 and i > 0:
            print(f"  Progress: {i}/{len(batch)} ({success} ok, {fail} fail)")

        code = stock["code"]
        name = stock["name"]
        industry = stock["industry"]
        threshold = get_limit_threshold(code, name)

        try:
            rs = bs.query_history_k_data_plus(
                code,
                "date,close,pctChg,volume",
                start_date=start_date,
                end_date=end_date,
                frequency="d",
                adjustflag="3"
            )
            rows = []
            while rs.error_code == '0' and rs.next():
                rows.append(rs.get_row_data())

            if not rows:
                fail += 1
                continue

            success += 1
            for row in rows:
                dt = row[0].replace("-", "")
                try:
                    pct = float(row[2]) if row[2] else 0
                except (ValueError, IndexError):
                    continue

                if pct >= threshold:
                    if dt not in zt_events:
                        zt_events[dt] = []
                    zt_events[dt].append({
                        "code": code.split(".")[-1],
                        "name": name,
                        "industry": industry,
                        "pctChg": round(pct, 2),
                        "close": row[1],
                        "volume": row[3],
                    })

        except Exception as e:
            fail += 1

        time.sleep(0.05)

    bs.logout()

    for dt in zt_events:
        zt_events[dt].sort(key=lambda x: x["pctChg"], reverse=True)

    output = {
        "batch": args.batch,
        "total_batches": args.total_batches,
        "stock_range": f"{start_idx}-{end_idx}",
        "stocks_queried": len(batch),
        "stocks_success": success,
        "stocks_fail": fail,
        "date_range": {"start": args.start, "end": args.end},
        "zt_events": zt_events,
        "zt_summary": {dt: len(events) for dt, events in sorted(zt_events.items())},
    }

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    total_zt = sum(len(v) for v in zt_events.values())
    print(f"\n✓ Batch {args.batch} done: {success}/{len(batch)} stocks, {total_zt} limit-up events across {len(zt_events)} days")
    print(f"  Output: {args.output}")


if __name__ == "__main__":
    main()

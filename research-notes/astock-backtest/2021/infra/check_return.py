#!/usr/bin/env python3
"""Check 10-day forward return for a specific stock pick.
Usage: python3 check_return.py STOCK_CODE ENTRY_DATE
Example: python3 check_return.py 002472 2021-03-15
"""
import json, sys, os

DB_PATH = os.path.join(os.path.dirname(__file__), "price_db_2021.json")

def main():
    code, entry_date = sys.argv[1], sys.argv[2]
    with open(DB_PATH, encoding="utf-8") as f:
        db = json.load(f)

    if code not in db["stocks"]:
        print(f"ERROR: {code} not in database")
        sys.exit(1)

    info = db["stocks"][code]
    prices = {r["date"]: r for r in info["daily_prices"]}
    all_dates = [r["date"] for r in info["daily_prices"]]

    if entry_date not in prices:
        print(f"ERROR: {entry_date} not a trading day")
        sys.exit(1)

    entry = prices[entry_date]
    d_idx = all_dates.index(entry_date)

    print(f"股票: {code} {info['name']}")
    print(f"入场日: {entry_date}")
    print(f"入场价: {entry['close']}")

    fwd = []
    for i in range(1, 11):
        fi = d_idx + i
        if fi < len(all_dates):
            fd = all_dates[fi]
            fp = prices[fd]
            ret = round((fp["close"] / entry["close"] - 1) * 100, 2)
            high_ret = round((fp["high"] / entry["close"] - 1) * 100, 2)
            fwd.append((fd, fp["close"], ret, high_ret))

    if not fwd:
        print("无后续数据(年末)")
        return

    print(f"\n10日前瞻:")
    max_ret = -999
    max_date = ""
    for fd, fc, ret, hr in fwd:
        marker = ""
        if hr > max_ret:
            max_ret = hr
            max_date = fd
        if ret >= 10:
            marker = " ★★BIG_WIN"
        elif ret >= 5:
            marker = " ★WIN"
        elif ret <= -5:
            marker = " ✗LOSS"
        print(f"  {fd}: 收{fc:.2f} ({ret:+.1f}%) 日高{hr:+.1f}%{marker}")

    close_ret = fwd[-1][2] if fwd else 0
    print(f"\n10日最高收益: {max_ret:+.1f}% ({max_date})")
    print(f"10日收盘收益: {close_ret:+.1f}%")

    if max_ret >= 10:
        print(f"判定: BIG_WIN")
    elif max_ret >= 5:
        print(f"判定: WIN")
    elif close_ret <= -5:
        print(f"判定: LOSS")
    else:
        print(f"判定: NEUTRAL")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Compact daily market scan for walk-forward simulation agents.
Usage: python3 market_scan.py START_DATE END_DATE
Output: Per-day sector rotation + top/bottom movers (text, ~3KB for 10 days)
"""
import json, sys, os

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
    start, end = sys.argv[1], sys.argv[2]
    with open(DB_PATH, encoding="utf-8") as f:
        db = json.load(f)

    sample = next(iter(db["stocks"].values()))
    all_dates = [r["date"] for r in sample["daily_prices"]]
    price_map = {}
    for code, info in db["stocks"].items():
        price_map[code] = {r["date"]: r for r in info["daily_prices"]}

    si = next(i for i, d in enumerate(all_dates) if d >= start)
    ei = next(i for i, d in enumerate(all_dates) if d >= end)
    range_dates = all_dates[si:ei+1]

    # Also show 5-day lookback momentum for context
    lb_start = max(0, si - 5)
    lb_dates = all_dates[lb_start:si]
    if lb_dates:
        print("=== 近5日回顾(进入本期前的动量) ===")
        for code, info in db["stocks"].items():
            pm = price_map[code]
            if lb_dates[0] in pm and lb_dates[-1] in pm:
                ret = round((pm[lb_dates[-1]]["close"] / pm[lb_dates[0]]["close"] - 1) * 100, 2)
                if abs(ret) >= 5:
                    print(f"  {code} {info['name']}: {ret:+.1f}%")

    for d in range_dates:
        d_idx = all_dates.index(d)
        prev_d = all_dates[d_idx - 1] if d_idx > 0 else None

        # Per-stock daily returns
        stock_returns = {}
        for code, info in db["stocks"].items():
            pm = price_map[code]
            if d in pm and prev_d and prev_d in pm:
                ret = round((pm[d]["close"] / pm[prev_d]["close"] - 1) * 100, 2)
                vol = pm[d]["volume"]
                prev_vol = pm[prev_d]["volume"]
                vol_ratio = round(vol / prev_vol, 1) if prev_vol > 0 else 0
                stock_returns[code] = (info["name"], ret, vol_ratio)

        # Sector averages
        sector_rets = {}
        for sec, codes in SECTORS.items():
            rets = [stock_returns[c][1] for c in codes if c in stock_returns]
            if rets:
                sector_rets[sec] = round(sum(rets) / len(rets), 2)
        sorted_sectors = sorted(sector_rets.items(), key=lambda x: x[1], reverse=True)

        # Top/bottom movers
        sorted_stocks = sorted(stock_returns.items(), key=lambda x: x[1][1], reverse=True)

        print(f"\n=== {d} ===")
        print("板块: " + " | ".join(f"{s}{r:+.1f}%" for s, r in sorted_sectors))
        top5 = sorted_stocks[:5]
        bot5 = sorted_stocks[-5:]
        print("涨TOP5: " + " ".join(f"{v[0]}{v[1]:+.1f}%{'↑量'+str(v[2])+'x' if v[2]>=1.5 else ''}" for _, v in top5))
        print("跌TOP5: " + " ".join(f"{v[0]}{v[1]:+.1f}%" for _, v in bot5))

        # Flag unusual volume
        high_vol = [(c, v[0], v[1], v[2]) for c, v in sorted_stocks if v[2] >= 2.0]
        if high_vol:
            print("放量: " + " ".join(f"{n}{r:+.1f}%({vr}x量)" for c, n, r, vr in high_vol[:5]))

    # Period summary
    print(f"\n=== 期间汇总 {start} to {end} ===")
    period_rets = {}
    for code, info in db["stocks"].items():
        pm = price_map[code]
        sd = range_dates[0]
        ed = range_dates[-1]
        if sd in pm and ed in pm:
            prev_sd = all_dates[all_dates.index(sd) - 1] if all_dates.index(sd) > 0 else sd
            open_p = pm[prev_sd]["close"] if prev_sd in pm else pm[sd]["open"]
            period_rets[code] = (info["name"], round((pm[ed]["close"] / open_p - 1) * 100, 2))
    sorted_pr = sorted(period_rets.items(), key=lambda x: x[1][1], reverse=True)
    print("期间涨幅TOP10: " + " | ".join(f"{v[0]}{v[1]:+.1f}%" for _, v in sorted_pr[:10]))
    print("期间跌幅TOP10: " + " | ".join(f"{v[0]}{v[1]:+.1f}%" for _, v in sorted_pr[-10:]))

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Build 2021 A-stock daily price database for walk-forward simulation."""
# /// script
# requires-python = ">=3.10"
# dependencies = ["akshare>=1.10.0"]
# ///

import akshare as ak
import json
import time
from datetime import datetime

STOCKS = {
    # User's successful picks
    "002472": "双环传动",
    "002463": "沪电股份",
    "002920": "德赛西威",
    "002938": "鹏鼎控股",
    "603005": "晶方科技",
    # User's decent picks
    "300274": "阳光电源",
    "600276": "恒瑞医药",
    "002241": "歌尔股份",
    # User's bad pick
    "002028": "思源电气",
    # Semi chain
    "002371": "北方华创",
    "688012": "中微公司",
    "688019": "安集科技",
    "603501": "韦尔股份",
    "603986": "兆易创新",
    "600584": "长电科技",
    # Solar/New Energy
    "601012": "隆基绿能",
    "600438": "通威股份",
    "002129": "中环股份",
    "002459": "晶澳科技",
    # EV/Lithium
    "300750": "宁德时代",
    "002594": "比亚迪",
    "002466": "天齐锂业",
    "002460": "赣锋锂业",
    "300014": "亿纬锂能",
    # PCB/CE
    "002475": "立讯精密",
    "002273": "水晶光电",
    "002916": "深南电路",
    # Auto/Smart Driving
    "002906": "华阳集团",
    "300496": "中科创达",
    # Robot/Mfg
    "688017": "绿的谐波",
    "300124": "汇川技术",
    "002747": "埃斯顿",
    # Pharma
    "603259": "药明康德",
    "300760": "迈瑞医疗",
    # Power/Grid
    "600406": "国电南瑞",
    "600900": "长江电力",
    # Resources
    "600188": "兖矿能源",
    "601225": "陕西煤业",
    "601899": "紫金矿业",
    "600988": "赤峰黄金",
    # Consumer
    "600519": "贵州茅台",
    "000858": "五粮液",
    "603288": "海天味业",
    # Others
    "000333": "美的集团",
    "601888": "中国中免",
    "002607": "中公教育",
    "600809": "山西汾酒",
    "300433": "蓝思科技",
}

def fetch_stock_data(symbol, name):
    try:
        df = ak.stock_zh_a_hist(
            symbol=symbol,
            period="daily",
            start_date="20210101",
            end_date="20211231",
            adjust="qfq"
        )
        if df is None or df.empty:
            return None
        records = []
        for _, row in df.iterrows():
            records.append({
                "date": str(row["日期"]),
                "open": float(row["开盘"]),
                "close": float(row["收盘"]),
                "high": float(row["最高"]),
                "low": float(row["最低"]),
                "volume": int(row["成交量"]),
                "amount": float(row["成交额"]),
                "pct_change": float(row["涨跌幅"]) if "涨跌幅" in row else None
            })
        return records
    except Exception as e:
        print(f"  ERROR {symbol} {name}: {e}")
        return None

def main():
    price_db = {"_meta": {"year": 2021, "stock_count": len(STOCKS), "built_at": datetime.now().isoformat()}, "stocks": {}}

    success = 0
    failed = []

    for symbol, name in STOCKS.items():
        print(f"Fetching {symbol} {name}...")
        data = fetch_stock_data(symbol, name)
        if data:
            price_db["stocks"][symbol] = {
                "name": name,
                "symbol": symbol,
                "trading_days": len(data),
                "first_date": data[0]["date"],
                "last_date": data[-1]["date"],
                "year_open": data[0]["open"],
                "year_close": data[-1]["close"],
                "year_return_pct": round((data[-1]["close"] / data[0]["open"] - 1) * 100, 2),
                "daily_prices": data
            }
            success += 1
            print(f"  OK: {len(data)} days, return {price_db['stocks'][symbol]['year_return_pct']}%")
        else:
            failed.append(f"{symbol} {name}")
        time.sleep(0.3)

    price_db["_meta"]["success"] = success
    price_db["_meta"]["failed"] = failed

    outpath = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/research-notes/astock-backtest/2021/infra/price_db_2021.json"
    with open(outpath, "w", encoding="utf-8") as f:
        json.dump(price_db, f, ensure_ascii=False, indent=1)

    print(f"\nDone: {success}/{len(STOCKS)} stocks, {len(failed)} failed")
    if failed:
        print(f"Failed: {failed}")

    summary_path = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/research-notes/astock-backtest/2021/infra/price_summary_2021.md"
    with open(summary_path, "w") as f:
        f.write("# 2021 Price Database Summary\n\n")
        f.write(f"| Symbol | Name | Days | Year Return |\n")
        f.write(f"|--------|------|------|-------------|\n")
        for sym, info in sorted(price_db["stocks"].items(), key=lambda x: x[1]["year_return_pct"], reverse=True):
            f.write(f"| {sym} | {info['name']} | {info['trading_days']} | {info['year_return_pct']}% |\n")

    print(f"Summary written to {summary_path}")

if __name__ == "__main__":
    main()

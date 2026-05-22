#!/usr/bin/env python3
"""Build 2024 A-stock daily price database using yfinance."""
# /// script
# requires-python = ">=3.10"
# dependencies = ["yfinance>=0.2.0"]
# ///

import yfinance as yf
import json
from datetime import datetime

STOCKS = {
    "002472": "双环传动", "002463": "沪电股份", "002920": "德赛西威",
    "002938": "鹏鼎控股", "603005": "晶方科技", "300274": "阳光电源",
    "600276": "恒瑞医药", "002241": "歌尔股份", "002028": "思源电气",
    "002371": "北方华创", "688012": "中微公司", "688019": "安集科技",
    "603501": "韦尔股份", "603986": "兆易创新", "600584": "长电科技",
    "601012": "隆基绿能", "600438": "通威股份", "002129": "中环股份",
    "002459": "晶澳科技", "300750": "宁德时代", "002594": "比亚迪",
    "002466": "天齐锂业", "002460": "赣锋锂业", "300014": "亿纬锂能",
    "002475": "立讯精密", "002273": "水晶光电", "002916": "深南电路",
    "002906": "华阳集团", "300496": "中科创达", "688017": "绿的谐波",
    "300124": "汇川技术", "002747": "埃斯顿", "603259": "药明康德",
    "300760": "迈瑞医疗", "600406": "国电南瑞", "600900": "长江电力",
    "600188": "兖矿能源", "601225": "陕西煤业", "601899": "紫金矿业",
    "600988": "赤峰黄金", "600519": "贵州茅台", "000858": "五粮液",
    "603288": "海天味业", "000333": "美的集团", "601888": "中国中免",
    "002607": "中公教育", "600809": "山西汾酒", "300433": "蓝思科技",
}

def get_yf_ticker(code):
    if code.startswith("6"):
        return f"{code}.SS"
    return f"{code}.SZ"

def main():
    price_db = {
        "_meta": {"year": 2024, "source": "yfinance", "stock_count": len(STOCKS), "built_at": datetime.now().isoformat()},
        "stocks": {}
    }
    success, failed = 0, []

    for code, name in STOCKS.items():
        yft = get_yf_ticker(code)
        print(f"Fetching {code} {name} ({yft})...", end=" ", flush=True)
        try:
            t = yf.Ticker(yft)
            df = t.history(start="2024-01-01", end="2025-01-01")
            if df is None or df.empty:
                print("EMPTY")
                failed.append(f"{code} {name}")
                continue
            records = []
            for date, row in df.iterrows():
                records.append({
                    "date": date.strftime("%Y-%m-%d"),
                    "open": round(float(row["Open"]), 3),
                    "close": round(float(row["Close"]), 3),
                    "high": round(float(row["High"]), 3),
                    "low": round(float(row["Low"]), 3),
                    "volume": int(row["Volume"]),
                })
            yo = records[0]["open"]
            yc = records[-1]["close"]
            yr = round((yc / yo - 1) * 100, 2)
            price_db["stocks"][code] = {
                "name": name, "symbol": code, "yf_ticker": yft,
                "trading_days": len(records),
                "first_date": records[0]["date"], "last_date": records[-1]["date"],
                "year_open": yo, "year_close": yc, "year_return_pct": yr,
                "daily_prices": records
            }
            success += 1
            print(f"OK {len(records)}d ret={yr}%")
        except Exception as e:
            print(f"ERROR: {e}")
            failed.append(f"{code} {name}")

    price_db["_meta"]["success"] = success
    price_db["_meta"]["failed"] = failed

    out = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/research-notes/astock-backtest/2024/infra/price_db_2024.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(price_db, f, ensure_ascii=False, indent=1)
    print(f"\nDone: {success}/{len(STOCKS)} OK, {len(failed)} failed")
    if failed:
        print(f"Failed: {failed}")

    if price_db["stocks"]:
        sample = next(iter(price_db["stocks"].values()))
        cal = [r["date"] for r in sample["daily_prices"]]
        cal_path = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/research-notes/astock-backtest/2024/infra/trading_calendar_2024.json"
        with open(cal_path, "w") as f:
            json.dump({"year": 2024, "trading_days": cal, "count": len(cal)}, f, indent=1)
        print(f"Calendar: {len(cal)} trading days written")

if __name__ == "__main__":
    main()

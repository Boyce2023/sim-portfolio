import akshare as ak
import pandas as pd
import sys

try:
    df = ak.stock_zh_a_hist(symbol="600212", period="daily", start_date="20260701", end_date="20260826", adjust="")
    df.to_csv("600212_price_hist_raw.csv", index=False, encoding="utf-8-sig")
    print(df.tail(25).to_string())
except Exception as e:
    print("ERROR:", e, file=sys.stderr)
    sys.exit(1)

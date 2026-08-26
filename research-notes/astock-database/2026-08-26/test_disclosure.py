import akshare as ak
import pandas as pd
import time

t0 = time.time()
try:
    df = ak.stock_report_disclosure(market="沪深京", period="2026半年报")
    print("SUCCESS, shape:", df.shape)
    print(df.columns.tolist())
    print(df.head(10))
    df.to_csv("raw_disclosure_calendar.csv", index=False, encoding="utf-8-sig")
except Exception as e:
    print("ERROR:", e)
print("elapsed:", time.time()-t0)

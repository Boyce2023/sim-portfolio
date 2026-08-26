import akshare as ak
import pandas as pd
import sys, time

try:
    t0=time.time()
    df = ak.stock_lhb_detail_em(start_date="20260726", end_date="20260826")
    print(f"elapsed={time.time()-t0:.1f}s rows={len(df)}")
    df.to_csv("lhb_detail_em_20260726_20260826.csv", index=False, encoding="utf-8-sig")
    hit = df[df['代码'].astype(str).str.zfill(6) == '600212']
    print("600212 hits:", len(hit))
    print(hit.to_string())
except Exception as e:
    print("ERROR:", type(e).__name__, e, file=sys.stderr)
    sys.exit(1)

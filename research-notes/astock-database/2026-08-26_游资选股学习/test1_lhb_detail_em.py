import akshare as ak
import pandas as pd
import sys, time, traceback

dates = ['20250115', '20250310', '20250520', '20250815']
results = {}

for d in dates:
    print(f"=== Testing stock_lhb_detail_em start={d} end={d} ===", flush=True)
    try:
        t0 = time.time()
        df = ak.stock_lhb_detail_em(start_date=d, end_date=d)
        elapsed = time.time() - t0
        n = len(df) if df is not None else 0
        cols = list(df.columns) if df is not None else []
        print(f"  OK rows={n} cols={cols} elapsed={elapsed:.1f}s", flush=True)
        results[d] = {'rows': n, 'cols': cols, 'elapsed': elapsed}
        if n > 0:
            outpath = f"raw/lhb_detail_em_{d}.csv"
            df.to_csv(outpath, index=False, encoding='utf-8-sig')
            print(f"  saved to {outpath}", flush=True)
            print(df.head(3).to_string(), flush=True)
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()
        results[d] = {'error': str(e)}

import json
with open('raw/test1_summary.json', 'w') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print("DONE")

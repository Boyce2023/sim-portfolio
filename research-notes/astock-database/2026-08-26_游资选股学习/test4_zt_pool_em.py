import akshare as ak
import json, time, traceback

results = {}
dates = ['20250115', '20250310', '20250520', '20250815', '20260101', '20260810']

for d in dates:
    try:
        t0=time.time()
        df = ak.stock_zt_pool_em(date=d)
        elapsed = time.time()-t0
        n = len(df) if df is not None else 0
        cols = list(df.columns) if df is not None else []
        print(f"=== stock_zt_pool_em({d}) rows={n} cols={cols} elapsed={elapsed:.1f}s ===", flush=True)
        results[d] = {'rows': n, 'cols': cols}
        if n > 0:
            df.to_csv(f"raw/zt_pool_em_{d}.csv", index=False, encoding='utf-8-sig')
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()
        results[d] = {'error': str(e)}

with open('raw/test4_summary.json','w') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print("DONE")

import akshare as ak
import json, time, traceback

results = {}
fns = ['stock_zt_pool_previous_em', 'stock_zt_pool_strong_em', 'stock_zt_pool_zbgc_em', 'stock_zt_pool_dtgc_em']
dates = ['20250115', '20250815']

for fn_name in fns:
    fn = getattr(ak, fn_name)
    results[fn_name] = {}
    for d in dates:
        try:
            t0=time.time()
            df = fn(date=d)
            elapsed=time.time()-t0
            n = len(df) if df is not None else 0
            cols = list(df.columns) if df is not None else []
            print(f"=== {fn_name}({d}) rows={n} cols={cols[:6]} elapsed={elapsed:.1f}s ===", flush=True)
            results[fn_name][d] = {'rows': n, 'cols': cols}
        except Exception as e:
            print(f"  ERROR {fn_name}({d}): {type(e).__name__}: {e}", flush=True)
            results[fn_name][d] = {'error': str(e)}
        time.sleep(0.3)

with open('raw/test5_summary.json','w') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print("DONE")

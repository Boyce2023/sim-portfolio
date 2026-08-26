import akshare as ak
import json, time, traceback

results = {}

ranges = [
    ('20250110','20250117'),  # 1 week Jan
    ('20250501','20250531'),  # 1 month May
]

for fn_name in ['stock_lhb_jgmmtj_em', 'stock_lhb_hyyyb_em']:
    fn = getattr(ak, fn_name)
    results[fn_name] = {}
    for start, end in ranges:
        key = f"{start}_{end}"
        try:
            t0=time.time()
            df = fn(start_date=start, end_date=end)
            elapsed = time.time()-t0
            n = len(df) if df is not None else 0
            cols = list(df.columns) if df is not None else []
            print(f"=== {fn_name}({start},{end}) rows={n} cols={cols} elapsed={elapsed:.1f}s ===", flush=True)
            results[fn_name][key] = {'rows': n, 'cols': cols}
            if n > 0:
                df.to_csv(f"raw/{fn_name}_{start}_{end}.csv", index=False, encoding='utf-8-sig')
                print(df.head(5).to_string(), flush=True)
        except Exception as e:
            print(f"  ERROR: {type(e).__name__}: {e}", flush=True)
            traceback.print_exc()
            results[fn_name][key] = {'error': str(e)}

with open('raw/test3_summary.json','w') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print("DONE")

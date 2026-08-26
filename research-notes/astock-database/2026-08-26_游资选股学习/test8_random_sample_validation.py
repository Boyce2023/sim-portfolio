import akshare as ak
import json, time, traceback

samples = [
    ('002750','龙津退','20250620'),
    ('301556','托普云农','20250224'),
    ('000785','居然智家','20250213'),
    ('002189','中光学','20250630'),
    ('600696','退市岩石','20250324'),
]

results = {}
for code, name, date in samples:
    key = f"{code}_{name}_{date}"
    results[key] = {}
    for flag in ['买入','卖出']:
        try:
            t0=time.time()
            df = ak.stock_lhb_stock_detail_em(symbol=code, date=date, flag=flag)
            elapsed=time.time()-t0
            n = len(df) if df is not None else 0
            print(f"{key} {flag}: rows={n} elapsed={elapsed:.1f}s", flush=True)
            results[key][flag] = n
        except Exception as e:
            print(f"{key} {flag}: ERROR {type(e).__name__}: {e}", flush=True)
            results[key][flag] = f"ERROR: {e}"
        time.sleep(0.3)

with open('raw/test8_summary.json','w') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print("DONE")

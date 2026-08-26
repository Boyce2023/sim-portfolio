import akshare as ak
import pandas as pd
import time, sys, json

results = {}

# Full year 2025 pull for stock_lhb_detail_em
try:
    t0=time.time()
    df = ak.stock_lhb_detail_em(start_date='20250101', end_date='20251231')
    elapsed = time.time()-t0
    n = len(df)
    print(f"stock_lhb_detail_em FULL 2025: rows={n} elapsed={elapsed:.1f}s", flush=True)
    df.to_csv('raw/lhb_detail_em_FULL_2025.csv', index=False, encoding='utf-8-sig')
    df['上榜日'] = pd.to_datetime(df['上榜日'])
    monthly = df['上榜日'].dt.to_period('M').value_counts().sort_index()
    print(monthly.to_string(), flush=True)
    results['lhb_detail_em_2025'] = {'total_rows': n, 'monthly': {str(k): int(v) for k,v in monthly.items()}}
except Exception as e:
    print(f"ERROR full year lhb_detail_em: {e}", flush=True)
    results['lhb_detail_em_2025'] = {'error': str(e)}

time.sleep(0.5)

# Full year 2025 for jgmmtj
try:
    t0=time.time()
    df2 = ak.stock_lhb_jgmmtj_em(start_date='20250101', end_date='20251231')
    elapsed = time.time()-t0
    n2 = len(df2)
    print(f"stock_lhb_jgmmtj_em FULL 2025: rows={n2} elapsed={elapsed:.1f}s", flush=True)
    df2.to_csv('raw/lhb_jgmmtj_em_FULL_2025.csv', index=False, encoding='utf-8-sig')
    df2['上榜日期'] = pd.to_datetime(df2['上榜日期'])
    monthly2 = df2['上榜日期'].dt.to_period('M').value_counts().sort_index()
    print(monthly2.to_string(), flush=True)
    results['jgmmtj_em_2025'] = {'total_rows': n2, 'monthly': {str(k): int(v) for k,v in monthly2.items()}}
except Exception as e:
    print(f"ERROR full year jgmmtj: {e}", flush=True)
    results['jgmmtj_em_2025'] = {'error': str(e)}

with open('raw/test7_summary.json','w') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print("DONE")

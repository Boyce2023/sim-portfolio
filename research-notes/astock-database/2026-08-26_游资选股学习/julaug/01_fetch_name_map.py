import akshare as ak
import time, sys
t0=time.time()
df = ak.stock_info_a_code_name()
print(f"name map rows={len(df)} elapsed={time.time()-t0:.1f}s", file=sys.stderr)
df.to_csv('name_map.csv', index=False, encoding='utf-8-sig')
print(df.head())

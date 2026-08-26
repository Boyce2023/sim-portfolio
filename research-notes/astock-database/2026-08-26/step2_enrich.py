import sys, os, time, json
sys.path.insert(0, "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts")
os.environ.setdefault('NO_PROXY', '*')
import pandas as pd
from astock_data_layer import get_batch_prices

OUTDIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/research-notes/astock-database/2026-08-26/"

undisclosed = pd.read_csv(OUTDIR + "tech_undisclosed_raw.csv", dtype={'股票代码': str})
undisclosed['股票代码'] = undisclosed['股票代码'].str.zfill(6)
codes = undisclosed['股票代码'].tolist()
print(f"待补充数据: {len(codes)} 只")

t0 = time.time()
prices = get_batch_prices(codes)
print(f"get_batch_prices完成,耗时{round(time.time()-t0,1)}s, 返回{len(prices)}条")

missing_price = [c for c in codes if prices.get(c, {}).get('price') is None]
print(f"价格缺失: {len(missing_price)} 只: {missing_price[:20]}")

rows = []
for c in codes:
    p = prices.get(c, {})
    rows.append({
        '股票代码': c,
        'circulating_cap_yi': p.get('circulating_cap'),
        'market_cap_yi': p.get('market_cap'),
        'price': p.get('price'),
        'change_pct_1d': p.get('change_pct'),
    })
price_df = pd.DataFrame(rows)
price_df.to_csv(OUTDIR + "tech_undisclosed_prices.csv", index=False, encoding='utf-8-sig')
print(price_df.head(10).to_string())
print("circulating_cap缺失数:", price_df['circulating_cap_yi'].isna().sum())

import akshare as ak
import pandas as pd
import json, time, traceback

results = {}

# Use stocks known to be on LHB from test1: 000032 深桑达A on 20250310, 000070 特发信息 on 20250815
tests = [
    ('000032', '20250310'),
    ('000070', '20250815'),
]

for symbol, date in tests:
    key = f"{symbol}_{date}"
    results[key] = {}
    # First try to get the date list
    try:
        t0 = time.time()
        dates_df = ak.stock_lhb_stock_detail_date_em(symbol=symbol)
        elapsed = time.time()-t0
        print(f"=== stock_lhb_stock_detail_date_em({symbol}) rows={len(dates_df)} elapsed={elapsed:.1f}s ===", flush=True)
        print(dates_df.head(10).to_string(), flush=True)
        results[key]['date_list_rows'] = len(dates_df)
        results[key]['date_list_cols'] = list(dates_df.columns)
        dates_df.to_csv(f"raw/lhb_stock_detail_date_em_{symbol}.csv", index=False, encoding='utf-8-sig')
    except Exception as e:
        print(f"  date_list ERROR: {type(e).__name__}: {e}", flush=True)
        results[key]['date_list_error'] = str(e)

    for flag in ['买入', '卖出']:
        try:
            t0 = time.time()
            df = ak.stock_lhb_stock_detail_em(symbol=symbol, date=date, flag=flag)
            elapsed = time.time()-t0
            n = len(df) if df is not None else 0
            cols = list(df.columns) if df is not None else []
            print(f"=== stock_lhb_stock_detail_em({symbol},{date},{flag}) rows={n} cols={cols} elapsed={elapsed:.1f}s ===", flush=True)
            results[key][flag] = {'rows': n, 'cols': cols}
            if n > 0:
                df.to_csv(f"raw/lhb_stock_detail_em_{symbol}_{date}_{flag}.csv", index=False, encoding='utf-8-sig')
                print(df.head(5).to_string(), flush=True)
        except Exception as e:
            print(f"  ERROR {flag}: {type(e).__name__}: {e}", flush=True)
            traceback.print_exc()
            results[key][flag] = {'error': str(e)}

with open('raw/test2_summary.json', 'w') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print("DONE")

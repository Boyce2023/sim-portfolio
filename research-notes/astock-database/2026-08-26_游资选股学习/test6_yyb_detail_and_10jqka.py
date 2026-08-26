import akshare as ak
import json, time, traceback
import pandas as pd

results = {}

# stock_lhb_yyb_detail_em - full history for one seat, no date param
seat_codes = ['10025080', '10634757']  # 国泰海通...江苏路(appeared repeatedly May2025), 深股通专用
for code in seat_codes:
    try:
        t0=time.time()
        df = ak.stock_lhb_yyb_detail_em(symbol=code)
        elapsed=time.time()-t0
        n = len(df) if df is not None else 0
        cols = list(df.columns) if df is not None else []
        print(f"=== stock_lhb_yyb_detail_em({code}) rows={n} cols={cols} elapsed={elapsed:.1f}s ===", flush=True)
        results[f'yyb_detail_{code}'] = {'rows': n, 'cols': cols}
        if n > 0:
            df.to_csv(f"raw/lhb_yyb_detail_em_{code}.csv", index=False, encoding='utf-8-sig')
            # check date range if there's a date column
            date_cols = [c for c in df.columns if '日' in c or 'date' in c.lower()]
            print(f"  date-like cols: {date_cols}", flush=True)
            for dc in date_cols:
                try:
                    print(f"  {dc} range: {df[dc].min()} ~ {df[dc].max()}", flush=True)
                except: pass
            print(df.head(3).to_string(), flush=True)
    except Exception as e:
        print(f"  ERROR yyb_detail({code}): {type(e).__name__}: {e}", flush=True)
        results[f'yyb_detail_{code}'] = {'error': str(e)}
    time.sleep(0.3)

# 10jqka current-window seat rankings (no date param - test current pull only)
for fn_name in ['stock_lh_yyb_capital', 'stock_lh_yyb_control', 'stock_lh_yyb_most']:
    fn = getattr(ak, fn_name)
    try:
        t0=time.time()
        df = fn()
        elapsed=time.time()-t0
        n = len(df) if df is not None else 0
        cols = list(df.columns) if df is not None else []
        print(f"=== {fn_name}() rows={n} cols={cols} elapsed={elapsed:.1f}s ===", flush=True)
        results[fn_name] = {'rows': n, 'cols': cols}
        if n>0:
            df.to_csv(f"raw/{fn_name}.csv", index=False, encoding='utf-8-sig')
    except Exception as e:
        print(f"  ERROR {fn_name}(): {type(e).__name__}: {e}", flush=True)
        results[fn_name] = {'error': str(e)}
    time.sleep(0.3)

with open('raw/test6_summary.json','w') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print("DONE")

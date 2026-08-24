import akshare as ak
import json, sys
from concurrent.futures import ThreadPoolExecutor, as_completed

tickers = ['000049', '000155', '000333', '000426', '000657', '000708', '000831', '000858', '000933', '002025', '002049', '002371', '002378', '002493', '002842', '002895', '002935', '002978', '003010', '300308', '300408', '300476', '300627', '300725', '300748', '300759', '301018', '600019', '600111', '600150', '600160', '600183', '600276', '600298', '600309', '600312', '600547', '600549', '600690', '600779', '601899', '603259', '603505', '603596', '603662', '605020', '688019', '688072', '688082', '688085', '688131', '688206', '688239', '688293', '688356', '688617', '688627']

def sym(t):
    return ('sh'+t) if t.startswith(('6','9')) else ('sz'+t)

def fetch(t):
    for attempt in range(2):
        try:
            df = ak.stock_zh_a_daily(symbol=sym(t), start_date='20260601', end_date='20260824', adjust='')
            df['date'] = df['date'].astype(str)
            return t, df[['date','close']].to_dict('records'), None
        except Exception as e:
            err = str(e)
    return t, None, err

results = {}
errors = {}
with ThreadPoolExecutor(max_workers=10) as ex:
    futs = {ex.submit(fetch, t): t for t in tickers}
    for fut in as_completed(futs):
        t, data, err = fut.result()
        if data is not None:
            results[t] = data
            print(f"OK {t} n={len(data)}", flush=True)
        else:
            errors[t] = err
            print(f"FAIL {t}: {err}", flush=True)

json.dump({'data': results, 'errors': errors}, open('stock_data.json','w'))
print(f"DONE: {len(results)} ok, {len(errors)} failed")

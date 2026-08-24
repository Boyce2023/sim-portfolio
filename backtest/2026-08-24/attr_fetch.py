import json, time
import urllib.request

def fetch_tencent_kline(symbol, start, end, count=60):
    # symbol e.g. sh600309, sz300308, sh000300
    url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,{start},{end},{count},qfq"
    req = urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=8) as r:
        data = json.loads(r.read().decode('utf-8'))
    try:
        d = data['data'][symbol]
        key = 'qfqday' if 'qfqday' in d else 'day'
        rows = d[key]
    except Exception as e:
        return None, str(e)
    return rows, None

targets = {
    '600309':'sh600309',
    '002049':'sz002049',
    '300308':'sz300308',
    '300476':'sz300476',
    '600150':'sh600150',
}
out = {}
errs = {}
for tk, sym in targets.items():
    rows, err = fetch_tencent_kline(sym, '2026-06-15','2026-06-26')
    if err:
        errs[tk] = err
        print(tk, 'ERROR', err)
        continue
    out[tk] = rows
    print(tk, 'got', len(rows), 'rows, last few:', rows[-3:])
    time.sleep(0.3)

with open('attr_t0_prices_raw.json','w') as f:
    json.dump({'data':out,'errors':errs}, f, ensure_ascii=False, indent=2)

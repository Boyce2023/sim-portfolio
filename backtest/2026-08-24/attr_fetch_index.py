import json, time
import urllib.request

def fetch_tencent_kline(symbol, start, end, count=80):
    url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,{start},{end},{count},qfq"
    req = urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=8) as r:
        data = json.loads(r.read().decode('utf-8'))
    d = data['data'][symbol]
    key = 'qfqday' if 'qfqday' in d else 'day'
    return d[key]

for sym in ['sh000300','sh000852']:
    try:
        rows = fetch_tencent_kline(sym, '2026-06-15','2026-08-24')
        print(sym, len(rows), rows[0], rows[-1])
        with open(f'attr_index_{sym}.json','w') as f:
            json.dump(rows, f)
    except Exception as e:
        print(sym, 'ERROR', e)

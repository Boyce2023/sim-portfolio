import urllib.request
import json
import csv
import sys

# 腾讯 web.ifzq.gtimg.cn 日K线接口 (task-specified fallback)
url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh600212,day,2026-07-01,2026-08-26,320,qfq"
req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
try:
    with urllib.request.urlopen(req, timeout=8) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    # navigate structure
    stock_data = data['data']['sh600212']
    key = 'qfqday' if 'qfqday' in stock_data else 'day'
    rows = stock_data[key]
    print(f"rows={len(rows)}")
    with open('600212_price_hist_tencent.csv','w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['date','open','close','high','low','volume'])
        for r in rows:
            w.writerow(r[:6])
    for r in rows[-25:]:
        print(r[:6])
except Exception as e:
    print("ERROR:", type(e).__name__, e, file=sys.stderr)
    sys.exit(1)

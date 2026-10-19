"""宇宙: NASDAQ screener 全量(NASDAQ+NYSE+AMEX), 市值>=20亿美元, 价格>=5。存 universe.json"""
import urllib.request, json, time
H={"User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36","Accept":"application/json"}
for a in range(4):
    try:
        rows=json.load(urllib.request.urlopen(urllib.request.Request(
            "https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=8000&download=true",headers=H),timeout=90))['data']['rows']; break
    except Exception as e:
        print('retry',e); time.sleep(15)
print('全量',len(rows))
out=[]
for r in rows:
    try:
        mc=float(r['marketCap'] or 0)/1e9; px=float(str(r['lastsale']).replace('$','').replace(',',''))
    except Exception: continue
    s=r['symbol'].strip()
    if mc>=2 and px>=5 and '^' not in s and '/' not in s:
        out.append(dict(t=s.replace('.','-'),name=r['name'],mc_b=round(mc,2),sector=r.get('sector') or '',industry=r.get('industry') or '',country=r.get('country') or '',ipo=r.get('ipoyear') or ''))
json.dump(out,open('universe.json','w'),ensure_ascii=False)
import collections
print('>=20亿',len(out),'>=50亿',sum(o['mc_b']>=5 for o in out))
print(collections.Counter(o['sector'] for o in out).most_common())
print('行业数',len(set(o['industry'] for o in out)))

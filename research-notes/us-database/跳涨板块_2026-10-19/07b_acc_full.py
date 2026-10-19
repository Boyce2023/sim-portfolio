"""补: 有 2.02 事件的公司重取完整 acceptanceDateTime(UTC), 转美东。存 earn_8k_acc.json {ticker:[{date_et,time_et,filing_date}]}"""
import json, time, urllib.request, concurrent.futures as cf, datetime as dt, zoneinfo
UA={'User-Agent':'Buwen Deng research buwendeng@gmail.com'}; ET=zoneinfo.ZoneInfo('America/New_York')
def get(u):
    for k in range(4):
        try: return urllib.request.urlopen(urllib.request.Request(u,headers=UA),timeout=60).read()
        except Exception as e: time.sleep(2*(k+1))
ct=json.loads(get('https://www.sec.gov/files/company_tickers.json')); cik={v['ticker'].replace('.','-').upper():v['cik_str'] for v in ct.values()}
k8=json.load(open('earn_8k.json')); T=[t for t,v in k8.items() if v.get('ev')]
def one(t):
    s=json.loads(get(f'https://data.sec.gov/submissions/CIK{int(cik[t]):010d}.json')); rc=s['filings']['recent']; out=[]
    for fm,fd,it,acc in zip(rc['form'],rc['filingDate'],rc['items'],rc['acceptanceDateTime']):
        if fm=='8-K' and '2.02' in (it or '') and '2026-08-20'<=fd<='2026-10-17':
            u=dt.datetime.fromisoformat(acc.replace('Z','+00:00')).astimezone(ET)
            out.append(dict(filing_date=fd,date_et=str(u.date()),time_et=u.strftime('%H:%M')))
    return t,out
res={}
with cf.ThreadPoolExecutor(6) as ex:
    for t,o in ex.map(one,T): res[t]=o
json.dump(res,open('earn_8k_acc.json','w')); print(len(res)); print({t:res[t] for t in ['NVDA','JPM','CRM','MU','PEP']})

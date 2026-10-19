"""财报日主源: SEC 8-K Item 2.02(经营业绩) 的 acceptanceDateTime(美东), 窗口 2026-08-24~2026-10-16。
外国发行人(6-K/40-F)不报8-K, 由 NASDAQ 日历补。存 earn_8k.json {ticker:[{date,time,acc}]}"""
import json, time, urllib.request, concurrent.futures as cf
UA={'User-Agent':'Buwen Deng research buwendeng@gmail.com'}
def get(url,tries=4):
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=60) as r: return r.read()
        except Exception as e: err=e; time.sleep(2*(k+1))
    raise err
ct=json.loads(get('https://www.sec.gov/files/company_tickers.json'))
cik={v['ticker'].replace('.','-').upper():v['cik_str'] for v in ct.values()}
uni=[u['t'] for u in json.load(open('universe.json'))]
miss=[t for t in uni if t not in cik]; print('无CIK',len(miss),miss[:30])
def one(t):
    try:
        s=json.loads(get(f'https://data.sec.gov/submissions/CIK{int(cik[t]):010d}.json'))
    except Exception as e: return t,None,str(e)[:60]
    rc=s['filings']['recent']; ev=[]
    for fm,fd,it,acc,an in zip(rc['form'],rc['filingDate'],rc['items'],rc['acceptanceDateTime'],rc['accessionNumber']):
        if fm in('8-K','8-K/A') and '2.02' in (it or '') and '2026-08-20'<=fd<='2026-10-17':
            ev.append(dict(date=fd,acc_time=acc[11:16],form=fm,an=an))
    forms=set(rc['form'][:200])
    return t,dict(ev=ev,fpi=bool(forms&{'6-K','20-F','40-F'}) and '10-Q' not in forms),None
import os
res=json.load(open('earn_8k.json')) if os.path.exists('earn_8k.json') else {}
res={k:v for k,v in res.items() if 'err' not in v}; n=0
with cf.ThreadPoolExecutor(6) as ex:
    for t,d,err in ex.map(one,[t for t in uni if t in cik and t not in res]):
        res[t]=d if d else {'err':err}; n+=1
        if n%150==0: print(n,flush=True); json.dump(res,open('earn_8k.json','w'))
json.dump(res,open('earn_8k.json','w'))
print('完成',len(res),'有2.02事件',sum(1 for v in res.values() if v.get('ev')),'外国发行人',sum(1 for v in res.values() if v.get('fpi')),'错误',sum(1 for v in res.values() if 'err' in v))

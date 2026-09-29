#!/opt/homebrew/bin/python3.13
"""补 09-24, 09-28 两个完整交易日(主库止于 09-23); 腾讯日线不复权; 写 recent.parquet, 不动主库"""
import pandas as pd, json, urllib.request, time
from concurrent.futures import ThreadPoolExecutor
P=pd.read_parquet('../panel.parquet',columns=['code','date','fshare'])
last=P.sort_values('date').groupby('code').tail(1)
codes=last[last.date==last.date.max()].code.tolist()
fs=dict(zip(last.code,last.fshare))
WANT={'2026-09-24','2026-09-28'}
def get(c):
    m=('sh' if c.startswith('6') else 'sz')+c
    for t in range(3):
        try:
            d=json.load(urllib.request.urlopen(f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={m},day,,,6,",timeout=8))['data'][m]
            rows=d.get('day') or d.get('qfqday') or []
            return [(c,x[0],float(x[1]),float(x[3]),float(x[4]),float(x[2]),float(x[5])) for x in rows if x[0] in WANT]
        except Exception: time.sleep(0.5)
    return None
t0=time.time()
with ThreadPoolExecutor(16) as ex: res=list(ex.map(get,codes))
fail=[c for c,r in zip(codes,res) if r is None]
rows=[x for r in res if r for x in r]
R=pd.DataFrame(rows,columns=['code','date','open','high','low','close','vol'])
R['date']=pd.to_datetime(R.date); R['volume']=R.vol*100
R['amount']=R.volume*(R.open+R.high+R.low+R.close)/4
R['fshare']=R.code.map(fs); R['turn']=R.volume/R.fshare
print(f'股票 {len(codes)} 只, 失败 {len(fail)}, 行 {len(R)}, 各日: {R.groupby("date").size().to_dict()}, 用时 {time.time()-t0:.0f}s')
assert len(fail)<50, fail[:20]
R.to_parquet('recent.parquet')

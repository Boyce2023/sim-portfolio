#!/opt/homebrew/bin/python3.13
"""两源分工补 09-24, 09-28: 参数 bs|sina; bs 拉前 40%(单进程), sina 拉后 60%(3 线程, 间隔 0.2s)"""
import sys, time, pandas as pd, threading
src=sys.argv[1]
P=pd.read_parquet('../panel.parquet',columns=['code','date'])
last=P.sort_values('date').groupby('code').tail(1)
codes=sorted(last[last.date==last.date.max()].code.tolist()); cut=int(len(codes)*0.4)
mine=codes[:cut] if src=='bs' else codes[cut:]
WANT={'2026-09-24','2026-09-28'}; rows=[]; st={'n':0,'bad':0}; t0=time.time(); lock=threading.Lock()
def log():
    if st['n']%250==0: print(f"[{src}] {st['n']}/{len(mine)} 空或错 {st['bad']} {time.time()-t0:.0f}s",flush=True)
if src=='bs':
    import baostock as bs, signal
    class TO(Exception):pass
    signal.signal(signal.SIGALRM,lambda s,f:(_ for _ in ()).throw(TO()))
    bs.login()
    for c in mine:
        m=('sh.' if c.startswith('6') else 'sz.')+c; got=0
        try:
            signal.alarm(15)
            rs=bs.query_history_k_data_plus(m,"date,open,high,low,close,volume,amount,turn,isST",start_date='2026-09-24',end_date='2026-09-28',frequency='d',adjustflag='3')
            while rs.next():
                d=rs.get_row_data()
                if d[0] in WANT and d[1]: rows.append((c,d[0],*[float(x or 0) for x in d[1:7]],float(d[7] or 0)/100,int(d[8] or 0))); got+=1
            signal.alarm(0)
        except TO:
            signal.alarm(0); bs.logout(); bs.login()
        st['n']+=1; st['bad']+=(got==0); log()
    bs.logout()
else:
    import requests
    from concurrent.futures import ThreadPoolExecutor
    def get(c):
        s=requests.Session(); s.trust_env=False
        sym=('sh' if c.startswith('6') else 'sz')+c; out=[]
        for k in range(3):
            try:
                r=s.get('https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData',params=dict(symbol=sym,scale=240,ma='no',datalen=6),timeout=10)
                for x in r.json() or []:
                    if x['day'] in WANT:
                        o,h,l,cl,v=[float(x[k2]) for k2 in ('open','high','low','close','volume')]
                        out.append((c,x['day'],o,h,l,cl,v,v*(o+h+l+cl)/4,None,None))
                break
            except Exception: time.sleep(1+k)
        time.sleep(0.2)
        with lock:
            rows.extend(out); st['n']+=1; st['bad']+=(len(out)==0); log()
    with ThreadPoolExecutor(3) as ex: list(ex.map(get,mine))
R=pd.DataFrame(rows,columns=['code','date','open','high','low','close','volume','amount','turn','isST'])
R.to_parquet(f'recent_{src}.parquet')
print(f"[{src}] 完成 {st} 行 {len(R)} {R.groupby('date').size().to_dict()} {time.time()-t0:.0f}s",flush=True)

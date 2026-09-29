#!/opt/homebrew/bin/python3.13
"""东财补 09-24, 09-28 全市场日线(不复权), 5 线程; 空返回率 >5% 或连续失败即停"""
import pandas as pd, akshare as ak, time, threading
from concurrent.futures import ThreadPoolExecutor
P=pd.read_parquet('../panel.parquet',columns=['code','date','fshare'])
last=P.sort_values('date').groupby('code').tail(1)
codes=last[last.date==last.date.max()].code.tolist(); fs=dict(zip(last.code,last.fshare))
lock=threading.Lock(); st={'n':0,'empty':0,'err':0}; t0=time.time()
def get(c):
    for k in range(3):
        try:
            d=ak.stock_zh_a_hist(symbol=c,period='daily',start_date='20260924',end_date='20260928',adjust='')
            time.sleep(0.1)
            with lock:
                st['n']+=1
                if len(d)==0: st['empty']+=1
                if st['n']%500==0: print(f"{st['n']}/{len(codes)} 空 {st['empty']} 错 {st['err']} {time.time()-t0:.0f}s",flush=True)
            return c,d
        except Exception as e:
            time.sleep(1+k)
    with lock: st['err']+=1; st['n']+=1
    return c,None
with ThreadPoolExecutor(5) as ex: res=list(ex.map(get,codes))
rows=[]
for c,d in res:
    if d is None or len(d)==0: continue
    for _,r in d.iterrows(): rows.append((c,pd.Timestamp(r['日期']),r['开盘'],r['最高'],r['最低'],r['收盘'],r['成交量']*100,r['成交额'],r['换手率']/100))
R=pd.DataFrame(rows,columns=['code','date','open','high','low','close','volume','amount','turn'])
R['fshare']=R.code.map(fs)
print('完成',st,'行',len(R),R.groupby('date').size().to_dict(),f'{time.time()-t0:.0f}s',flush=True)
R.to_parquet('recent.parquet')

#!/opt/homebrew/bin/python3.13
"""2021-12 到 2022-12 逐日 isST(宝硕), 补 feat.parquet(2023-01 起) 之前的空档. 单进程(宝硕并行登录会被拉黑)."""
import baostock as bs,pandas as pd,signal,time,json,os
class TO(Exception): pass
signal.signal(signal.SIGALRM,lambda s,f:(_ for _ in ()).throw(TO()))
def guard(fn,sec=30):
    try: signal.alarm(sec); r=fn(); signal.alarm(0); return r
    except Exception: signal.alarm(0); return None
A=pd.read_parquet('../../data/cn_hk_price_db/a_daily.parquet',columns=['date','ticker'],filters=[('date','>=',pd.Timestamp('2021-12-01')),('date','<=',pd.Timestamp('2022-12-31'))])
tks=sorted(A.ticker.unique()); print('股票',len(tks),flush=True)
for _ in range(3):
    lg=guard(bs.login)
    if lg is not None and lg.error_code=='0': break
    time.sleep(3)
rows=[];fail=[]
for i,tk in enumerate(tks):
    num,ex=tk.split('.'); ok=False
    for _ in range(2):
        try:
            signal.alarm(15)
            rs=bs.query_history_k_data_plus(f'{ex.lower()}.{num}','date,isST',start_date='2021-12-01',end_date='2022-12-31',frequency='d',adjustflag='3')
            while rs.next():
                d,s=rs.get_row_data(); rows.append((tk,d,s))
            signal.alarm(0); ok=True; break
        except TO:
            signal.alarm(0); guard(bs.logout); guard(bs.login)
    if not ok: fail.append(tk)
    if (i+1)%500==0: print(i+1,'失败',len(fail),flush=True)
guard(bs.logout)
df=pd.DataFrame(rows,columns=['ticker','date','isST']); df['date']=pd.to_datetime(df.date); df['isST']=pd.to_numeric(df.isST,errors='coerce')
df.to_parquet('st2022.parquet'); json.dump(fail,open('st2022_fail.json','w'))
print('完成 行',len(df),'ST行',int(df.isST.sum()),'失败',len(fail),flush=True)

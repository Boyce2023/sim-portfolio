#!/opt/homebrew/bin/python3.13
"""2022年逐日 isST(宝硕), 只拉需要的: 沪深主板 且 2021-12到2022-12 至少有一天涨幅在4.8%到5.2%之间(风险警示股涨停区间)的股票;
创业板/科创板/北交所的风险警示不改变涨跌幅, 不用拉. 断点续跑(每100只落盘), 15:33自动停, 避开15:40价格库更新的宝硕登录(并行登录会被拉黑)."""
import baostock as bs,pandas as pd,signal,time,json,os,datetime
class TO(Exception): pass
signal.signal(signal.SIGALRM,lambda s,f:(_ for _ in ()).throw(TO()))
def guard(fn,sec=30):
    try: signal.alarm(sec); r=fn(); signal.alarm(0); return r
    except Exception: signal.alarm(0); return None
A=pd.read_parquet('../../data/cn_hk_price_db/a_daily.parquet',columns=['date','ticker','close'],filters=[('date','>=',pd.Timestamp('2021-11-25')),('date','<=',pd.Timestamp('2022-12-31'))]).sort_values(['ticker','date'])
A['r']=A.groupby('ticker').close.pct_change()
main=~A.ticker.str[:3].isin(['300','301','688','689'])
cand=sorted(A[main&A.r.between(0.048,0.052)].ticker.unique())
done=pd.read_parquet('st2022.parquet') if os.path.exists('st2022.parquet') else pd.DataFrame(columns=['ticker','date','isST'])
todo=[t for t in cand if t not in set(done.ticker)]
print('候选',len(cand),'已完成',done.ticker.nunique(),'待拉',len(todo),flush=True)
STOP=os.environ.get('STOP','15:33')
for _ in range(3):
    lg=guard(bs.login)
    if lg is not None and lg.error_code=='0': break
    time.sleep(3)
rows=[]
def flush():
    global done,rows
    if rows:
        df=pd.DataFrame(rows,columns=['ticker','date','isST']); df['date']=pd.to_datetime(df.date); df['isST']=pd.to_numeric(df.isST,errors='coerce')
        done=pd.concat([done,df],ignore_index=True); done.to_parquet('st2022.parquet'); rows=[]
for i,tk in enumerate(todo):
    if datetime.datetime.now().strftime('%H:%M')>=STOP and STOP!='none': print('到点暂停',flush=True); break
    num,ex=tk.split('.')
    for _ in range(2):
        try:
            signal.alarm(15)
            rs=bs.query_history_k_data_plus(f'{ex.lower()}.{num}','date,isST',start_date='2021-12-01',end_date='2022-12-31',frequency='d',adjustflag='3')
            while rs.next(): d,s=rs.get_row_data(); rows.append((tk,d,s))
            signal.alarm(0); break
        except TO:
            signal.alarm(0); guard(bs.logout); guard(bs.login)
    if (i+1)%100==0: flush(); print(i+1,'/',len(todo),flush=True)
flush(); guard(bs.logout)
print('结束 已完成',done.ticker.nunique(),'/',len(cand),'ST行',int(done.isST.sum()),flush=True)

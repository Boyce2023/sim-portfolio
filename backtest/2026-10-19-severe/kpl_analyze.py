import json, pandas as pd, numpy as np
R=json.load(open('kpl_severe_his.json'))['rows']
E=pd.DataFrame([{'code':r[0],'name':r[1],'rule':r[2],'chg_d':r[3],'lb':r[4],'status':r[8],'theme':r[10],'next_kpl':r[14],'halt':r[16],'resume':r[17],'date':pd.Timestamp(r[18]),'close_kpl':r[19]} for r in R])
E=E[E.date>='2025-10-19'].reset_index(drop=True)
A=pd.read_parquet('../../data/cn_hk_price_db/a_daily.parquet',columns=['date','ticker','open','high','low','close','adj_close'],filters=[('date','>=',pd.Timestamp('2025-09-01'))])
A['code']=A.ticker.str[:6]; P={c:d.sort_values('date').reset_index(drop=True) for c,d in A.groupby('code')}
out=[]
for _,e in E.iterrows():
    r=e.to_dict(); d=P.get(e.code)
    if d is None: out.append(r); continue
    k=d.index[d.date<=e.date]
    if len(k)==0: out.append(r); continue
    i=int(k[-1]); af=d.adj_close/d.close; base=d.adj_close[i]
    r['base_date']=d.date[i]; r['base_close']=d.close[i]
    if i+1<len(d):
        r['next_date']=d.date[i+1]; r['halt_days']=max(0,int(np.busday_count(d.date[i].date(),d.date[i+1].date()))-1)
        r['n_open']=d.open[i+1]*af[i+1]/base-1; r['n_close']=d.adj_close[i+1]/base-1
        r['n_high']=d.high[i+1]*af[i+1]/base-1; r['n_low']=d.low[i+1]*af[i+1]/base-1
        for h in (2,3,5,10,20): r[f'r{h}']=d.adj_close[i+h]/base-1 if i+h<len(d) else np.nan
        # 次日开盘买, 持有到第N日收盘
        o=d.open[i+1]*af[i+1]
        for h in (2,3,5): r[f'o_r{h}']=d.adj_close[i+h]/o-1 if i+h<len(d) else np.nan
    out.append(r)
R2=pd.DataFrame(out); R2.to_pickle('kpl_events.pkl')
chk=R2.dropna(subset=['n_close'])
print('近一年',len(R2),'有价格',len(chk),'次日涨幅与开盘啦对得上(差<0.3pp)',((chk.n_close*100-chk.next_kpl).abs()<0.3).mean().round(3))
bad=chk[(chk.n_close*100-chk.next_kpl).abs()>=0.3]
print(bad[['date','name','rule','next_kpl','n_close','base_date','next_date']].assign(n_close=lambda x:(x.n_close*100).round(2)).head(12).to_string(index=False))

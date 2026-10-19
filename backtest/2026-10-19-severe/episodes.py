import pandas as pd, numpy as np
D=pd.read_csv('cninfo_raw.csv',dtype={'code':str}); D['date']=pd.to_datetime(D.date)
D=D.sort_values(['code','date'])
ep=[]
for c,g in D.groupby('code'):
    cur=None
    for _,r in g.iterrows():
        if cur is None or (r.date-cur['last']).days>10:
            if cur: ep.append(cur)
            cur={'code':c,'name':r['name'],'ann':r.date,'last':r.date,'n_ann':1,'titles':[r.title]}
        else:
            cur['last']=r.date; cur['n_ann']+=1; cur['titles'].append(r.title)
    if cur: ep.append(cur)
E=pd.DataFrame(ep)
E['board']=np.where(E.code.str[:3].isin(['688','689']),'科创板',np.where(E.code.str[:3].isin(['300','301']),'创业板',np.where(E.code.str[0].isin(['8','9','4']),'北交所',np.where(E.code.str[0]=='6','沪主板','深主板'))))
print('事件(同一只10天内多条公告合并)',len(E)); print(E.board.value_counts())
A=pd.read_parquet('../../data/cn_hk_price_db/a_daily.parquet',columns=['date','ticker','open','high','low','close','adj_close','oshare'],filters=[('date','>=',pd.Timestamp('2025-08-01'))])
A['code']=A.ticker.str[:6]; A=A.sort_values(['code','date'])
P={c:d.reset_index(drop=True) for c,d in A.groupby('code')}
out=[]
for _,e in E.iterrows():
    r=e.to_dict(); r['titles']=' | '.join(e.titles[:2])
    d=P.get(e.code)
    if d is None: out.append(r); continue
    k=d.index[d.date<=e.ann]
    if len(k)==0: out.append(r); continue
    i=int(k[-1]); r['trigger']=d.date[i]
    af=d.adj_close/d.close
    base=d.adj_close[i]
    r['前10日涨幅']=base/d.adj_close[i-10]-1 if i>=10 else np.nan
    r['前30日涨幅']=base/d.adj_close[i-30]-1 if i>=30 else np.nan
    r['方向']='上涨' if (r['前10日涨幅']==r['前10日涨幅'] and r['前10日涨幅']>0) else '下跌'
    r['流通市值亿']=d.close[i]*d.oshare[i]/1e8
    if i+1<len(d):
        r['下一交易日']=d.date[i+1]; r['停牌天数']=max(0,int(np.busday_count(d.date[i].date(),d.date[i+1].date()))-1)
        r['次日开盘']=d.open[i+1]*af[i+1]/base-1; r['次日收盘']=d.adj_close[i+1]/base-1
        r['次日最低']=d.low[i+1]*af[i+1]/base-1; r['次日最高']=d.high[i+1]*af[i+1]/base-1
        for h in (3,5,10,20):
            r[f'后{h}日']=d.adj_close[i+h]/base-1 if i+h<len(d) else np.nan
        w=d.iloc[i+1:i+21]; r['20日内最高']=(w.high*af[w.index]).max()/base-1 if len(w) else np.nan
    out.append(r)
R=pd.DataFrame(out).drop(columns=['last']); R.to_pickle('episodes.pkl'); R.to_csv('episodes.csv',index=False)
print('有价格',R.trigger.notna().sum()); print(R.方向.value_counts())

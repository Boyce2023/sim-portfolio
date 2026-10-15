import pandas as pd,numpy as np
A=pd.read_parquet('../../data/cn_hk_price_db/a_daily.parquet',columns=['date','ticker','close','adj_close','oshare'],filters=[('date','>=',pd.Timestamp('2022-01-20')),('date','<=',pd.Timestamp('2022-11-05'))])
I=pd.read_csv('industry.csv'); I['ticker']=I.code.str[3:]+'.'+I.code.str[:2].str.upper(); I['ind']=I.industry.fillna('').str.replace(r'^[A-Z]\d+','',regex=True)
P=A.pivot(index='date',columns='ticker',values='adj_close'); cap=A.pivot(index='date',columns='ticker',values='close')*A.pivot(index='date',columns='ticker',values='oshare')/1e8
def at(d): return P.index[P.index.get_indexer([pd.Timestamp(d)],method='pad')[0]]
W={'全段 2-10月':('2022-01-28','2022-10-31'),'①2月到4月底':('2022-01-28','2022-04-26'),'②4月底到7月初':('2022-04-26','2022-07-05'),'③7月初到10月底':('2022-07-05','2022-10-31')}
ind=I.set_index('ticker').ind; nm=I.set_index('ticker').code_name
for k,(a,b) in W.items():
    a,b=at(a),at(b); r=(P.loc[b]/P.loc[a]-1).dropna()
    df=pd.DataFrame({'r':r,'ind':ind.reindex(r.index),'name':nm.reindex(r.index),'cap':cap.loc[a].reindex(r.index)})
    print(f'\n######## {k} ({a.date()}→{b.date()}) 个股{len(df)} 中位{df.r.median()*100:+.1f}% 上涨占比{(df.r>0).mean()*100:.0f}%')
    g=df[df.ind!=''].groupby('ind').agg(n=('r','size'),中位=('r','median'),上涨占比=('r',lambda x:(x>0).mean())); g=g[g.n>=15].sort_values('中位',ascending=False)
    print('行业前12:'); print(g.head(12).assign(中位=lambda x:(x.中位*100).round(1),上涨占比=lambda x:(x.上涨占比*100).round(0)).to_string())
    print('行业后6:'); print(g.tail(6).assign(中位=lambda x:(x.中位*100).round(1),上涨占比=lambda x:(x.上涨占比*100).round(0)).to_string())
    df['档']=pd.qcut(df.cap,5,labels=['最小20%','2','3','4','最大20%'])
    print('市值五档中位:',(df.groupby('档',observed=True).r.median()*100).round(1).to_dict())
    print('个股前15:',', '.join(f"{r.name_}{r.r*100:+.0f}%({r.ind[:6]})" for r in df.rename(columns={'name':'name_'}).sort_values('r',ascending=False).head(15).itertuples()))

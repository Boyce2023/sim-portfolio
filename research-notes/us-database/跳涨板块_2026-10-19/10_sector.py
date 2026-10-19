"""行业聚合: yfinance 行业(缺则 NASDAQ 行业), 宇宙市值>=20亿。存 industry_stats.pkl"""
import json, pandas as pd, numpy as np
st=pd.read_pickle('stock_stats.pkl'); px=pd.read_pickle('px.pkl')
uni={u['t']:u for u in json.load(open('universe.json'))}; info=json.load(open('info.json'))
st['ind']=st.t.map(lambda t:(info.get(t) or {}).get('industry') or uni[t]['industry'] or '未分类')
st['mc']=st.t.map(lambda t:uni[t]['mc_b'])
BASE=pd.Timestamp('2026-08-21'); fri=[d for d in px.index if d>=BASE and d.weekday()==4]
spy=st  # placeholder
rows=[]
for ind,g in st.groupby('ind'):
    if len(g)<3 or ind=='未分类': continue
    w=g.mc/g.mc.sum()
    # 市值加权指数的周线: 以 08-21 为 1 的加权净值
    tk=g.t.tolist(); nav=(px[tk].loc[BASE:].div(px[tk].loc[BASE]).mul(w.values,axis=1)).sum(axis=1,min_count=1)
    wk=nav.reindex(fri).pct_change().dropna()
    top=g.sort_values('win',ascending=False).head(3)
    rows.append(dict(ind=ind,n=len(g),win_med=g.win.median(),win_cw=nav.iloc[-1]-1,m1_med=g.m1.median(),m3_med=g.m3.median(),
                     up=(g.win>0).mean(),wk_up=(wk>0).mean(),dd=(nav/nav.cummax()-1).min(),off_hi=nav.iloc[-1]/nav.max()-1,
                     top=', '.join(top.t),mc=g.mc.sum()))
df=pd.DataFrame(rows); df.to_pickle('industry_stats.pkl')
print('行业',len(df),'用yf行业的个股',sum(1 for t in st.t if (info.get(t) or {}).get('industry')),'/',len(st))
print(df.sort_values('win_cw',ascending=False)[['ind','n','win_med','win_cw','up','wk_up','dd','top']].head(30).round(3).to_string())

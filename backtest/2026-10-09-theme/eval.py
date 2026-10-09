#!/opt/homebrew/bin/python3.13
import pandas as pd, numpy as np, sys
cnt=pd.read_parquet('theme_cnt.parquet'); T=pd.read_parquet('theme_rows.parquet')
days=cnt.index; rk=cnt.rank(axis=1,ascending=False,method='min')
# 基准: 单日排前三且>=5只
b=[]
for i in range(6,len(days)-10):
    s=cnt.iloc[i+1:i+11].sum().rank(ascending=False,method='min')
    for th in cnt.columns[(rk.iloc[i]<=3)&(cnt.iloc[i]>=5)]: b.append(s[th])
b=pd.Series(b); print(f'基准(单日前三且>=5只) n={len(b)}: 10日第一 {(b==1).mean()*100:.0f}% 前二 {(b<=2).mean()*100:.0f}% 前三 {(b<=3).mean()*100:.0f}%')
P=pd.read_parquet('../2026-10-08-sector/stock_panel.parquet',columns=['code','date','open','close','zt_px','ac','ao'])
P=P.sort_values(['code','date']); g=P.groupby('code')
for h in (5,10): P[f'f{h}']=g.ac.shift(-h)/g.ao.shift(-1)-1
P['o1']=g.open.shift(-1); P['z1']=g.zt_px.shift(-1)
mkt={h:P.groupby('date')[f'f{h}'].mean() for h in (5,10)}
P=P.set_index(['date','code'])
def trade(S):
    for h in (5,10):
        ex=[]
        for r in S.itertuples():
            cs=T[(T.date==r.date)&(T.theme==r.theme)].code.unique()
            idx=[(r.date,c) for c in cs if (r.date,c) in P.index]
            if not idx: ex.append(np.nan); continue
            x=P.loc[idx]; x=x[x.o1<x.z1-0.011]
            ex.append(x[f'f{h}'].mean()-mkt[h].get(r.date,np.nan) if len(x) else np.nan)
        S[f'ex{h}']=ex
    return S
for f in sys.argv[1:]:
    S=trade(pd.read_parquet(f))
    for h in (5,10):
        x=S[f'ex{h}'].dropna(); w,l=x[x>0],x[x<=0]
        print(f'{f} 当日该题材涨停股 次日开盘买 持{h}日超额: n={len(x)} 胜率{(x>0).mean()*100:.0f}% 均值{x.mean()*100:+.2f}% 中位{x.median()*100:+.2f}% 赔率{w.mean()/abs(l.mean()) if len(l) else float("nan"):.2f}')
    S.to_csv(f.replace('.parquet','.csv'),index=False,encoding='utf-8-sig')

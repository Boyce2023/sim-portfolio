"""五板日=第1天, 第2天开盘买. 按第2天有没有摸到涨停分组, 看第3到第11天收盘卖的收益, 以及第6到第12天才贴近异动线的情况"""
import pandas as pd, numpy as np
A=pd.read_pickle('/private/tmp/claude-501/-Users-huaichuaibeimeng-claude-projects/0271364f-8cab-4319-af5d-5048f0719e12/scratchpad/devpanel.pkl')
P={c:d.reset_index(drop=True) for c,d in A.groupby('code')}
F=pd.read_pickle('../2026-10-19-5ban-day23/events.pkl')
rows=[]
for _,e in F.iterrows():
    d=P[e.code]; i=int(d.index[d.date==pd.Timestamp(e.d5)][0]); b=i+1
    if b+1>=len(d): continue
    af=d.adj_close/d.close; O=d.open*af; H=d.high*af; Lo=d.low*af; C=d.adj_close; ZT=C.shift(1)*(1+d.lim)
    if Lo[b]>=ZT[b]*0.998: continue
    buy=O[b]; r={'name':e['name'],'d5':e.d5,'第2天摸涨停':bool(H[b]>=ZT[b]*0.998),'第2天收涨停':bool(d.zt[b])}
    for day in range(3,12):   # 第day天收盘, 下标 i+day-1
        t=i+day-1; r[f'第{day}天']=C[t]/buy-1 if t<len(d) else np.nan
    w=d.iloc[i:i+12]
    f90=w.index[w.m10>=0.9]; r['首次到90%是第几天']=int(f90[0]-i+1) if len(f90) else None
    f95=w.index[w.m10>=0.95]; r['首次到95%是第几天']=int(f95[0]-i+1) if len(f95) else None
    r['看到第几天']=min(len(d)-i,12)
    rows.append(r)
R=pd.DataFrame(rows); R.to_pickle('sellday.pkl')
cols=[f'第{k}天' for k in range(3,12)]
def show(x,lab):
    print(f"{lab} n={len(x)}")
    print('   平均 '+' '.join(f"{c}:{x[c].mean()*100:+.1f}%" for c in cols))
    print('   中位 '+' '.join(f"{c}:{x[c].median()*100:+.1f}%" for c in cols))
    print('   收涨 '+' '.join(f"{c}:{(x[c].dropna()>0).mean()*100:.0f}%({x[c].notna().sum()})" for c in cols))
show(R,'全部开盘买'); show(R[R.第2天摸涨停],'第2天摸到涨停'); show(R[~R.第2天摸涨停],'第2天没摸到涨停')
print('\n首次到90%在第几天(五板日=第1天):',R['首次到90%是第几天'].value_counts(dropna=False).sort_index().to_dict())
print('首次到95%在第几天:',R['首次到95%是第几天'].value_counts(dropna=False).sort_index().to_dict())
late=R[R['首次到90%是第几天'].fillna(0)>=6]; print('第6天以后才到90%的:',late[['name','d5','首次到90%是第几天']].to_dict('records'))

"""策略自身的近期战绩当开关: 只用买入前已经平仓的历史单(其T+2收盘日 <= 本次五板日)."""
import pandas as pd, numpy as np
from scipy.stats import mannwhitneyu
E=pd.read_pickle('events.pkl').sort_values('date').reset_index(drop=True)
done=E[['date2','ret']].sort_values('date2')
for N in (5,10,20):
    tr=[]
    for _,r in E.iterrows():
        p=done[done.date2<=r.date].tail(N)
        tr.append(p.ret.mean() if len(p)==N else np.nan)
    E[f'tr{N}']=tr
def rep(m,lab,d):
    x=d[m].ret; return f'{lab} n{len(x)} 胜{(x>0).mean()*100:.0f}% 均{x.mean()*100:+.1f}%'
for N in (5,10,20):
    print(f'\n== 近{N}笔已平仓单均值 >0 才做 ==')
    for lab,d in [('24-25',E[E.date<'2026-01-01']),('2026',E[E.date>='2026-01-01']),('全部',E)]:
        d=d.dropna(subset=[f'tr{N}'])
        on=d[f'tr{N}']>0
        p=mannwhitneyu(d[on].ret,d[~on].ret).pvalue
        print(f'  {lab}: {rep(on,"开",d)} | {rep(~on,"关",d)} | p={p:.3f}')
E['ym']=E.date.dt.strftime('%Y-%m')
M=E.groupby('ym').agg(n=('ret','size'),win=('ret',lambda x:(x>0).mean()*100),mean=('ret',lambda x:x.mean()*100)).round(1)
print(M.to_string())

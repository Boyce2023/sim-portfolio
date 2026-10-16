import pandas as pd, numpy as np
from scipy.stats import spearmanr, mannwhitneyu
E=pd.read_pickle('events.pkl')
IS=E[E.date<'2026-01-01']; OS=E[E.date>='2026-01-01']; JL=E[E.date>='2026-07-01']
feats=[c for c in E.columns if c.startswith('f_')]
rows=[]
for f in feats:
    a=spearmanr(IS[f],IS.ret,nan_policy='omit'); b=spearmanr(OS[f],OS.ret,nan_policy='omit')
    c=spearmanr(IS[f],IS.touch,nan_policy='omit'); d=spearmanr(OS[f],OS.touch,nan_policy='omit')
    rows.append((f,a.statistic,a.pvalue,b.statistic,b.pvalue,c.statistic,c.pvalue,d.statistic,d.pvalue))
R=pd.DataFrame(rows,columns=['特征','内_收益rho','内p','外_收益rho','外p','内_触跌停rho','内p2','外_触跌停rho','外p2']).round(3)
print(R.sort_values('内p').to_string(index=False))
def show(f,bins=None):
    if bins is None:
        if E[f].nunique()<=2: bins=[-np.inf,0.5,np.inf]
        else:
            q=IS[f].quantile([1/3,2/3]).values; bins=[-np.inf,q[0],q[1],np.inf]
    print(f'\n--- {f} 分档(阈值来自2024-25): {[round(x,4) for x in bins[1:-1]]}')
    for lab,d in [('24-25',IS),('2026',OS),('26-07起',JL)]:
        cut=pd.cut(d[f],bins); out=[]
        for k,x in d.groupby(cut,observed=False):
            if len(x)==0: out.append(f'{k}: 0'); continue
            out.append(f'{k}: n{len(x)} 胜{(x.ret>0).mean()*100:.0f}% 均{x.ret.mean()*100:+.1f}% 触跌停{x.touch.mean()*100:.0f}%')
        print(f'  {lab} | '+' || '.join(out))
import sys
for f in feats: show(f)

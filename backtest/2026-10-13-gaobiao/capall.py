#!/opt/homebrew/bin/python3.13
"""7月以来全部涨停股: 流通市值分档 x 连板高度, 看次日晋级率、次日涨跌、次日开盘买(开盘已涨停视为买不到)后日收盘卖"""
import pandas as pd,numpy as np,runpy,io,contextlib
with contextlib.redirect_stdout(io.StringIO()): ns=runpy.run_path('fill.py')
Z=ns['Z']; Z=Z[(Z.date>=pd.Timestamp('2026-07-01'))&Z.晋级.notna()&Z.次日涨跌.notna()].copy()
Z['市值档']=pd.cut(Z.cap,[0,20,30,50,100,200,1e9],labels=['20亿以下','20到30亿','30到50亿','50到100亿','100到200亿','200亿以上'])
Z['高度']=np.where(Z.lb>=3,'3板以上',np.where(Z.lb==2,'2板','首板'))
Z['段']=np.where(Z.date<pd.Timestamp('2026-09-01'),'7-8月','9-10月')
def agg(g):
    b=g[g.可买&g.开买后日收.notna()]
    return pd.Series({'样本':len(g),'晋级率':g.晋级.astype(float).mean(),'次日涨跌均':g.次日涨跌.mean(),'次日开盘一字率':(~g.可买).mean(),
                      '可买样本':len(b),'开买后日收均':b.开买后日收.mean() if len(b) else np.nan,'开买后日收胜率':(b.开买后日收>0).mean() if len(b) else np.nan})
fmt=lambda T:T.assign(**{c:(T[c]*100).round(1) for c in ['晋级率','次日涨跌均','次日开盘一字率','开买后日收均','开买后日收胜率']}).to_string()
print('样本区间',Z.date.min().date(),Z.date.max().date(),'涨停只次',len(Z))
print('\n== 全部涨停股 按市值档 =='); print(fmt(Z.groupby('市值档',observed=True).apply(agg)))
for h in ('首板','2板','3板以上'):
    print(f'\n== {h} =='); print(fmt(Z[Z.高度==h].groupby('市值档',observed=True).apply(agg)))
print('\n== 分段检验(全部涨停股) =='); print(fmt(Z.groupby(['段','市值档'],observed=True).apply(agg)))

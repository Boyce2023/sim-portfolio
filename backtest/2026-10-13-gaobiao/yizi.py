#!/opt/homebrew/bin/python3.13
"""同高度组里, 市值最小/最大那只 T+1 开盘一字(买不到)的比例, 以及次日晋级率"""
import pandas as pd,numpy as np,runpy,io,contextlib
with contextlib.redirect_stdout(io.StringIO()): ns=runpy.run_path('fill.py')
Z=ns['Z']
H=Z[(Z.date>=pd.Timestamp('2026-07-01'))&(Z.lb>=3)&(Z.lb==Z.days)&Z.次日涨跌.notna()]
s=b=[]; S=[];B=[]
for _,x in H.groupby(['date','lb']):
    if len(x)<2 or x.cap.nunique()<len(x): continue
    S.append(x.loc[x.cap.idxmin()]); B.append(x.loc[x.cap.idxmax()])
S=pd.DataFrame(S);B=pd.DataFrame(B)
for k,d in (('市值最小',S),('市值最大',B)):
    print(k,len(d),'次日开盘一字买不到 %d (%.0f%%)'%((~d.可买).sum(),(~d.可买).mean()*100),'次日晋级 %.0f%%'%(d.晋级.astype(float).mean()*100),'次日涨跌均 %.1f%%'%(d.次日涨跌.mean()*100))

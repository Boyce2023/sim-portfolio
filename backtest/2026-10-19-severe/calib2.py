import json,pandas as pd,numpy as np
from dev import panel,BENCH,add_compound
R=json.load(open('kpl_severe_his.json'))['rows']
K=pd.DataFrame([{'code':r[0],'date':pd.Timestamp(r[18]),'rule':r[2]} for r in R if r[18]>='2025-10-20' and r[2] in ('10日100%','30日200%')])
for name,b in BENCH.items():
    A=add_compound(panel(b)); g=A.groupby('code'); A['k10_prev']=g.k10.shift(1); A['k30_prev']=g.k30.shift(1)
    A=A.set_index(['code','date'])
    for rule,col in (('10日100%','k10'),('30日200%','k30')):
        k=K[K.rule==rule]; thr=1.0 if col=='k10' else 2.0
        v=pd.Series([A[col].get((c,d),np.nan) for c,d in zip(k.code,k.date)]); vp=pd.Series([A[col+'_prev'].get((c,d),np.nan) for c,d in zip(k.code,k.date)])
        print(name,rule,len(k),'当日>=阈值',(v>=thr-0.005).mean().round(3),'前一日<阈值',(vp<thr).mean().round(3),'中位',round(v.median()*100,1),[round(x*100,1) for x in v.quantile([.05,.25,.75,.95])])

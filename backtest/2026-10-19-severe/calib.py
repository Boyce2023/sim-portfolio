import json,pandas as pd,numpy as np
from dev import panel,BENCH
R=json.load(open('kpl_severe_his.json'))['rows']
K=pd.DataFrame([{'code':r[0],'date':pd.Timestamp(r[18]),'rule':r[2]} for r in R if r[18]>='2025-10-20' and r[2]=='10日100%'])
for name,b in BENCH.items():
    A=panel(b).set_index(['code','date'])
    v=[A.c10.get((c,d),np.nan) for c,d in zip(K.code,K.date)]
    v=pd.Series(v)
    print(name,'KPL 10日100% 事件',len(K),'能对上',v.notna().sum(),'c10>=100%',(v>=0.995).mean().round(3),'中位',round(v.median()*100,1),'分位',[round(x*100,1) for x in v.quantile([.1,.25,.75,.9])])

import json,pandas as pd,numpy as np
from dev import panel,BENCH,add_compound,add_window_max
R=json.load(open('kpl_severe_his.json'))['rows']
K=pd.DataFrame([{'code':r[0],'date':pd.Timestamp(r[18])} for r in R if r[18]>='2025-10-20' and r[2]=='10日100%'])
A=add_window_max(add_compound(panel(BENCH['B'])))
g=A.groupby('code'); A['m10_prev']=g.m10.shift(1); A=A.set_index(['code','date'])
v=pd.Series([A.m10.get((c,d),np.nan) for c,d in zip(K.code,K.date)]); vp=pd.Series([A.m10_prev.get((c,d),np.nan) for c,d in zip(K.code,K.date)])
print('窗口内取最大: 当日>=100%',(v>=0.995).mean().round(3),'前一日<100%',(vp<1).mean().round(3),'中位',round(v.median()*100,1),[round(x*100,1) for x in v.quantile([.05,.25,.75,.95])])
# 反查: 全市场近一年 m10 首次上穿 100% 的事件里, 有多少在开盘啦列表里(同日或前后1日)
A=A.reset_index(); g=A.groupby('code')
A['cross']=(A.m10>=1.0)&(g.m10.shift(1)<1.0)&(A.date>='2025-10-20')&(A.date<='2026-10-13')
X=A[A.cross][['code','date']]
ks=set(zip(K.code,K.date))
def near(c,d): return any((c,d+pd.Timedelta(days=k)) in ks for k in (-3,-2,-1,0,1,2,3))
X['in_kpl']=[near(c,d) for c,d in zip(X.code,X.date)]
print('自算上穿100%事件',len(X),'其中在开盘啦10日100%列表(前后3天)',X.in_kpl.mean().round(3))

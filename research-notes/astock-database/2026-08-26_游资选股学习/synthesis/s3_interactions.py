#!/usr/bin/env python3
"""S3: 交互检验 — 低换手效应是不是ST效应? 概念共振在控制情绪后还成立吗?"""
import pandas as pd, numpy as np, os
D=os.path.dirname(__file__); p=pd.read_csv(os.path.join(D,'panel_2025.csv'))
b=p[(~p.yizi)&(p.ret_open.notna())].copy()
b['cm']=np.where(b.isST==1,'ST5cm',np.where(b.lp>0.15,'20cm','10cm'))
def st(df,l):
    if len(df)<10: return dict(label=l,n=len(df))
    return dict(label=l,n=len(df),mean=round(df.ret_open.mean(),3),med=round(df.ret_open.median(),3),
                win=round((df.ret_open>0).mean()*100,1),nextlu=round(df.next_lu.mean()*100,1))
R=[]
print("=== A. 换手率效应 按涨跌停板制度分层 ===")
for cm in ['10cm','20cm','ST5cm']:
    s=b[b.cm==cm]
    for lo,hi in [(0,3),(3,6),(6,10),(10,15),(15,20),(20,1e9)]:
        R.append(st(s[(s.turn>=lo)&(s.turn<hi)],f'{cm} 换手{lo}-{hi if hi<1e8 else "inf"}'))
print(pd.DataFrame(R).to_string(index=False)); R=[]
print("\n=== B. 概念共振peer_cnt 在非ST内部 + 分市场情绪 ===")
nb=b[b.isST==0]
for lo,hi in [(0,3),(3,8),(8,15),(15,1e9)]:
    s=nb[(nb.peer_cnt>=lo)&(nb.peer_cnt<hi)]
    R.append(st(s,f'非ST peer{lo}-{hi if hi<1e8 else "inf"}'))
    R.append(st(s[s.mkt_lu_cnt>=80],f'  └ 且当日涨停>=80家'))
    R.append(st(s[s.mkt_lu_cnt<60],f'  └ 且当日涨停<60家'))
print(pd.DataFrame(R).to_string(index=False)); R=[]
print("\n=== C. 市值效应 控制换手后还在吗(非ST,换手<10%) ===")
s=nb[nb.turn<10]
for lo,hi in [(0,30),(30,50),(50,100),(100,200),(200,1e9)]:
    R.append(st(s[(s.fcap>=lo*1e8)&(s.fcap<hi*1e8)],f'非ST turn<10 市值{lo}-{hi if hi<1e8 else "inf"}亿'))
print(pd.DataFrame(R).to_string(index=False)); R=[]
print("\n=== D. gain20 控制后 (非ST, 换手<10%, streak=1) ===")
s=nb[(nb.turn<10)&(nb.streak==1)]
for lo,hi in [(-1e9,0),(0,15),(15,30),(30,60),(60,1e9)]:
    R.append(st(s[(s.gain20>=lo)&(s.gain20<hi)],f'gain20 {lo if lo>-1e8 else "-inf"}~{hi if hi<1e8 else "inf"}'))
print(pd.DataFrame(R).to_string(index=False)); R=[]
print("\n=== E. 连板位置 x 概念共振 (非ST) ===")
for s_ in [1,2,3]:
    s=nb[nb.streak==s_]
    R.append(st(s[s.peer_cnt<3],f'{s_}板 peer<3'))
    R.append(st(s[s.peer_cnt>=8],f'{s_}板 peer>=8'))
print(pd.DataFrame(R).to_string(index=False))

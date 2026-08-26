#!/usr/bin/env python3
"""S4: 规则组合评估 — 我编的B1 vs 数据学出来的B2 (2025样本内 + 2026样本外)
成本口径: 买入=涨停价成交(不加滑点,但存在成交概率问题,未建模); 卖出次日开盘滑点0.5%;
          佣金0.03%x2 + 印花税0.05% => 合计拖累 0.61pp/笔。net = gross - 0.61
"""
import pandas as pd, numpy as np, os, sys
D=os.path.dirname(__file__); DRAG=0.61
def load(f,lo=None,hi=None):
    p=pd.read_csv(os.path.join(D,f))
    p=p[(~p.yizi)&(p.ret_open.notna())]
    if lo: p=p[(p.date>=lo)&(p.date<=hi)]
    return p.copy()
def B1(p):  # 我拍脑袋编的
    return p[(p.fcap>=15e8)&(p.fcap<=100e8)&(p.streak==1)&(p.gain20<=30)&(p.turn>=3)&(p.turn<=30)]
def B2(p):  # 数据学出来的
    return p[(p.isST==0)&(p.turn<=10)&(p.gain20>=10)&(p.streak<=3)&(p.mkt_lu_cnt>=70)&(p.fcap>=10e8)]
def B2_noregime(p):
    return p[(p.isST==0)&(p.turn<=10)&(p.gain20>=10)&(p.streak<=3)&(p.fcap>=10e8)]
def B2_turnonly(p):
    return p[(p.isST==0)&(p.turn<=10)&(p.fcap>=10e8)]
def B3_st(p):   # ST/壳资源单独track
    return p[(p.isST==1)&(p.turn<=3)]
def rep(df,lab):
    if len(df)==0: return dict(rule=lab,n=0)
    return dict(rule=lab,n=len(df),gross=round(df.ret_open.mean(),3),med=round(df.ret_open.median(),3),
        net=round(df.ret_open.mean()-DRAG,3),win_gross=round((df.ret_open>0).mean()*100,1),
        win_net=round((df.ret_open>DRAG).mean()*100,1),
        nextlu=round(df.next_lu.mean()*100,1),days=df.date.nunique())
def top3(df,key,asc=True):
    return df.sort_values(['date',key],ascending=[True,asc]).groupby('date').head(3)
for name,f,lo,hi in [('样本内 2025全年','panel_2025.csv',None,None),
                     ('样本外 2026-01~03','panel_oos2026.csv','2026-01-01','2026-03-20'),
                     ('样本外 2026-01','panel_oos2026.csv','2026-01-01','2026-01-31'),
                     ('样本外 2026-02','panel_oos2026.csv','2026-02-01','2026-02-28'),
                     ('样本外 2026-03','panel_oos2026.csv','2026-03-01','2026-03-20')]:
    p=load(f,lo,hi); R=[rep(p,'全部可买涨停(基准)'),rep(B1(p),'B1 我编的五条'),
        rep(B2_turnonly(p),'B2a 仅换手<=10 非ST'),rep(B2_noregime(p),'B2b +gain20>=10 +streak<=3'),
        rep(B2(p),'B2 完整(含情绪门 涨停>=70家)'),
        rep(top3(B2(p),'turn'),'B2 每日选换手最低3只'),
        rep(top3(B2(p),'peer_cnt',False),'B2 每日选共振最高3只'),
        rep(B3_st(p),'B3 ST壳资源track(换手<3)')]
    print(f"\n########## {name} ##########")
    print(pd.DataFrame(R).to_string(index=False))

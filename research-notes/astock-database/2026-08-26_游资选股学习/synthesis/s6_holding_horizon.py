#!/usr/bin/env python3
"""S6: 概念共振强度 决定持有期? 对比T+1开盘出 vs 持有到T+2/T+3收盘"""
import sqlite3,pandas as pd,numpy as np,os
D=os.path.dirname(__file__)
con=sqlite3.connect('/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban/univ2025.db')
df=pd.read_sql('select code,date,close from k',con); con.close()
df=df.sort_values(['code','date'])
g=df.groupby('code',sort=False)
for h in [2,3,5]: df[f'c{h}']=g['close'].shift(-h)
p=pd.read_csv(os.path.join(D,'panel_2025.csv')).merge(df.drop(columns=['close']),on=['code','date'],how='left')
p=p[(~p.yizi)&(p.ret_open.notna())&(p.isST==0)]
for h in [2,3,5]: p[f'r{h}']=(p[f'c{h}']/p['close']-1)*100
R=[]
for lo,hi,lab in [(0,3,'peer<3 (无板块共振)'),(3,8,'peer3-8'),(8,1e9,'peer>=8 (板块级共振)')]:
    s=p[(p.peer_cnt>=lo)&(p.peer_cnt<hi)]
    R.append(dict(bucket=lab,n=len(s),T1开盘=round(s.ret_open.mean(),2),T2收盘=round(s.r2.mean(),2),
        T3收盘=round(s.r3.mean(),2),T5收盘=round(s.r5.mean(),2),
        T3胜率=round((s.r3>0).mean()*100,1),次日再涨停=round(s.next_lu.mean()*100,1)))
print(pd.DataFrame(R).to_string(index=False))
print("\n同上但只看首板(streak==1):")
R=[]
for lo,hi,lab in [(0,3,'peer<3'),(8,1e9,'peer>=8')]:
    s=p[(p.streak==1)&(p.peer_cnt>=lo)&(p.peer_cnt<hi)]
    R.append(dict(bucket=lab,n=len(s),T1开盘=round(s.ret_open.mean(),2),T2收盘=round(s.r2.mean(),2),
        T3收盘=round(s.r3.mean(),2),T5收盘=round(s.r5.mean(),2),T3胜率=round((s.r3>0).mean()*100,1)))
print(pd.DataFrame(R).to_string(index=False))

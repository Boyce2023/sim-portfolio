#!/usr/bin/env python3
"""S2: 逐条检验"我编的五条"+新候选条件。指标=次日开盘卖出收益(冲板买入)"""
import pandas as pd, numpy as np, os, json
D=os.path.dirname(__file__)
p=pd.read_csv(os.path.join(D,'panel_2025.csv'))
# 可买样本: 排除一字板(买不到) + 需有次日数据
base=p[(~p.yizi)&(p.ret_open.notna())].copy()
print(f"全部涨停instance {len(p)} | 剔除一字板&末日后可检验样本 n={len(base)}")
def stat(df,label):
    if len(df)==0: return dict(label=label,n=0)
    return dict(label=label,n=len(df),
        mean_open=round(df.ret_open.mean(),3), med_open=round(df.ret_open.median(),3),
        win_open=round((df.ret_open>0).mean()*100,1),
        mean_close=round(df.ret_close.mean(),3), win_close=round((df.ret_close>0).mean()*100,1),
        next_lu_pct=round(df.next_lu.mean()*100,1))
rows=[stat(base,'BASELINE 全部可买涨停')]
b=base
# ①流通市值
for lo,hi in [(0,15),(15,30),(30,50),(50,100),(100,200),(200,1e9)]:
    rows.append(stat(b[(b.fcap>=lo*1e8)&(b.fcap<hi*1e8)],f'流通市值 {lo}-{hi if hi<1e9 else "inf"}亿'))
rows.append(stat(b[(b.fcap>=15e8)&(b.fcap<100e8)],'★我编的: 15-100亿'))
# ②连板数
for s in [1,2,3,4]:
    rows.append(stat(b[b.streak==s],f'streak={s}板'))
rows.append(stat(b[b.streak>=5],'streak>=5板'))
rows.append(stat(b[b.streak>=2],'★对照: 连板>=2'))
# ③前20日涨幅
for lo,hi in [(-1e9,0),(0,10),(10,20),(20,30),(30,50),(50,1e9)]:
    rows.append(stat(b[(b.gain20>=lo)&(b.gain20<hi)],f'gain20 {lo if lo>-1e8 else "-inf"}~{hi if hi<1e8 else "inf"}%'))
rows.append(stat(b[b.gain20<=30],'★我编的: gain20<=30%'))
rows.append(stat(b[b.gain20>30],'★反例: gain20>30%'))
# ④换手
for lo,hi in [(0,3),(3,6),(6,10),(10,15),(15,20),(20,30),(30,1e9)]:
    rows.append(stat(b[(b.turn>=lo)&(b.turn<hi)],f'换手 {lo}-{hi if hi<1e8 else "inf"}%'))
rows.append(stat(b[(b.turn>=3)&(b.turn<=30)],'★我编的: 换手3-30%'))
# ⑤ST
rows.append(stat(b[b.isST==1],'ST股'))
rows.append(stat(b[b.isST==0],'非ST'))
# 概念强度代理
for lo,hi in [(0,1),(1,3),(3,6),(6,12),(12,25),(25,1e9)]:
    rows.append(stat(b[(b.peer_cnt>=lo)&(b.peer_cnt<hi)],f'共振peer_cnt {lo}-{hi if hi<1e8 else "inf"}'))
# 市场情绪
for lo,hi in [(0,40),(40,60),(60,80),(80,100),(100,1e9)]:
    rows.append(stat(b[(b.mkt_lu_cnt>=lo)&(b.mkt_lu_cnt<hi)],f'当日全市场涨停数 {lo}-{hi if hi<1e8 else "inf"}'))
for lo,hi in [(0,.15),(.15,.25),(.25,.35),(.35,1.01)]:
    rows.append(stat(b[(b.promo_rate>=lo)&(b.promo_rate<hi)],f'昨日涨停晋级率 {lo}-{hi}'))
out=pd.DataFrame(rows)
out.to_csv(os.path.join(D,'slice_univariate.csv'),index=False)
pd.set_option('display.width',220); pd.set_option('display.max_rows',200)
print(out.to_string(index=False))

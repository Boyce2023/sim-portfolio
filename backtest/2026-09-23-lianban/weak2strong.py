#!/opt/homebrew/bin/python3.13
"""弱转强回测: 五进六断板当天收阳线, 第二天是不是大概率转强? 2020-09-01 到 2026-09-22。

定义:
  D0 = 首次5板日(连板数恰为5)
  D1 = D0 次日, 且 D1 未涨停(断板)。⛔ D1 若仍涨停(六板成立)则不属于本形态, 剔除。
  阳线口径两种都测: 实体阳(收>开) / 红盘(收>前收)
  买入 = D1 收盘价(收盘才知道是不是阳线, 无前视)
  卖出 = D2 收盘 / D3 收盘 / D5 收盘
  弱转强判定 = D2 是否涨停
  对照 = D1 断板且收阴线(收<=开 或 收<=前收)
成本 一买一卖 12.3bp。收益全部 adj_close 口径。
⛔连板数自建判定, 已用东财涨停池官方字段在 2026-09-03 到 09-22 校验 99.88%。
"""
import math
import pandas as pd, numpy as np
S_D, E_D = pd.Timestamp('2020-09-01'), pd.Timestamp('2026-09-22')
COST = 0.00123

px = pd.read_parquet('data/cn_hk_price_db/a_daily.parquet',
                     columns=['date','ticker','open','close','adj_close','qfq_factor','amount','oshare'],
                     filters=[('date','>=',pd.Timestamp('2020-06-01'))]).sort_values(['ticker','date'])
px['prev_close']=px.groupby('ticker')['close'].shift(1)
def lim(t):
    c=t[:6]
    if c[:3] in ('300','301','688','689'): return .20
    if c[0] in ('4','8'): return .30
    return .10
px['lim']=px['ticker'].map(lim)
px['zt']=px['close']>=(px['prev_close']*(1+px['lim'])).round(2)-0.011
px['blk']=(~px['zt']).groupby(px['ticker']).cumsum()
px['nb']=px.groupby(['ticker','blk']).cumcount()
m=(px['blk']==0)&px['zt']; px.loc[m,'nb']=px.loc[m,'nb']+1; px.loc[~px['zt'],'nb']=0
px['ret']=px['close']/px['prev_close']-1
px['float_cap']=px['close']*px['oshare']/1e8

g=px.groupby('ticker')
px['nb_prev']=g['nb'].shift(1)
px['zt_prev']=g['zt'].shift(1)
# D1 条件: 前一日 nb==5, 当日未涨停
D1 = px[(px['nb_prev']==5) & (~px['zt']) & (px['date']>=S_D) & (px['date']<=E_D)].copy()
D1['实体阳']=D1['close']>D1['open']
D1['红盘']=D1['ret']>0
# 后续收益: 以 D1 收盘价买入
for n,k in [(1,'D2'),(2,'D3'),(4,'D5')]:
    D1[k]=g['adj_close'].shift(-n).loc[D1.index]/D1['adj_close']-1-COST
D1['D2涨停']=g['zt'].shift(-1).loc[D1.index]
D1['D2涨幅']=g['ret'].shift(-1).loc[D1.index]
D1.to_csv('backtest/2026-09-23-lianban/weak2strong.csv',index=False)
print(f"五进六断板样本 {len(D1)} 个 ({D1['date'].min().date()} 到 {D1['date'].max().date()})")
print(f"  其中实体阳(收>开) {int(D1['实体阳'].sum())} 个, 红盘(收>前收) {int(D1['红盘'].sum())} 个\n")

def rep(x,tag):
    if len(x)<5: print(f"{tag:<26} n={len(x)} 样本不足"); return
    s=f"{tag:<26} n={len(x):>4}"
    z=x['D2涨停'].dropna()
    s+=f" | D2涨停率 {z.mean()*100:5.1f}%"
    d=x['D2涨幅'].dropna()
    s+=f" | D2均涨 {d.mean()*100:+6.2f}%"
    for k in ['D2','D3','D5']:
        v=x[k].dropna()
        if len(v)<5: s+=f" | {k} n={len(v)}"; continue
        t=v.mean()/(v.std(ddof=1)/math.sqrt(len(v))) if v.std(ddof=1)>0 else float('nan')
        s+=f" | {k}收益 {v.mean()*100:+6.2f}% 胜{(v>0).mean()*100:3.0f}% t={t:6.2f}"
    print(s)

print("【口径一: 实体阳线(收盘>开盘)】")
rep(D1[D1['实体阳']], "  断板日收实体阳")
rep(D1[~D1['实体阳']], "  断板日收阴线(对照)")
print("\n【口径二: 红盘(收盘>前收)】")
rep(D1[D1['红盘']], "  断板日红盘")
rep(D1[~D1['红盘']], "  断板日绿盘(对照)")
print("\n【两个条件同时满足】")
rep(D1[D1['实体阳']&D1['红盘']], "  实体阳且红盘")
rep(D1[~D1['实体阳']&~D1['红盘']], "  实体阴且绿盘(对照)")

print("\n【按断板日涨跌幅分档】")
D1['档']=pd.cut(D1['ret']*100,[-99,-9,-5,-2,0,2,5,9,99],
                labels=['跌停附近','-9到-5','-5到-2','-2到0','0到2','2到5','5到9','9以上'])
for lb in D1['档'].cat.categories:
    rep(D1[D1['档']==lb], f"  {lb}")

print("\n【按年 实体阳线组】")
D1['y']=D1['date'].dt.year
for y,x in D1[D1['实体阳']].groupby('y'):
    z=x['D2涨停'].dropna(); v=x['D2'].dropna()
    if len(v)<3: print(f"  {y} n={len(x)} 不足"); continue
    print(f"  {y}  n={len(x):>3}  D2涨停率 {z.mean()*100:5.1f}%  D2收益 {v.mean()*100:+6.2f}% 胜{(v>0).mean()*100:3.0f}%")

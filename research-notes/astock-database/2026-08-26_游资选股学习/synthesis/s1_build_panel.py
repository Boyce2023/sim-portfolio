#!/usr/bin/env python3
"""S1: 全年2025涨停instance面板 + 前向收益 + 情绪/概念代理变量
输入: /Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban/univ2025.db (表k)
输出: synthesis/panel_2025.csv  (每条=一个涨停instance, 带特征与T+1收益)
口径:
  涨停判定: close == round(preclose*(1+lp),2) 容差0.005; 主板10%/创业板科创板20%/北交所30%/ST 5%
  买入: 当日涨停价(=close)买入(冲板近似) —— 一字板单独标记(现实中买不到)
  卖出: 次日开盘(ret_open) / 次日收盘(ret_close)
  ⛔无滑点无费用, 是纯信号检验不是净值回测
"""
import sqlite3, pandas as pd, numpy as np, sys, os
from bisect import bisect_left, bisect_right
DB=sys.argv[1] if len(sys.argv)>1 else '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban/univ2025.db'
OUT=sys.argv[2] if len(sys.argv)>2 else os.path.join(os.path.dirname(__file__),'panel_2025.csv')

def lim_pct(code, isST):
    c=code.split('.')[-1]
    if isST: return 0.05
    if c.startswith(('300','301','302','688','689')): return 0.20
    if c.startswith(('43','83','87','92')): return 0.30
    return 0.10

con=sqlite3.connect(DB)
df=pd.read_sql('select code,date,open,high,low,close,preclose,volume,amount,turn,isST from k',con)
con.close()
df=df.sort_values(['code','date']).reset_index(drop=True)
print('rows',len(df),'codes',df.code.nunique(),'dates',df.date.min(),df.date.max())

g=df.groupby('code',sort=False)
df['next_open']=g['open'].shift(-1); df['next_close']=g['close'].shift(-1)
df['next_preclose']=g['preclose'].shift(-1); df['next_low']=g['low'].shift(-1)
df['next_high']=g['high'].shift(-1)
df['close_20ago']=g['close'].shift(20)
df['gain20']=(df['close']/df['close_20ago']-1)*100
# 前1日是否涨停 -> streak
lp=np.array([lim_pct(c,s) for c,s in zip(df.code.values, df.isST.values)])
df['lp']=lp
df['is_lu']=(np.abs(df['close']-np.round(df['preclose']*(1+df['lp']),2))<0.005) & (df['volume']>0)
df['yizi']=df['is_lu'] & (np.abs(df['open']-df['close'])<0.005) & (np.abs(df['low']-df['close'])<0.005)
# streak: 连续涨停天数
def streak(s):
    out=np.zeros(len(s),dtype=int); k=0
    for i,v in enumerate(s):
        k=k+1 if v else 0
        out[i]=k
    return out
df['streak']=g['is_lu'].transform(lambda s: pd.Series(streak(s.values),index=s.index))
# 流通市值反推 (amount/turn*100), turn是百分比
df['fcap']=np.where(df['turn']>0, df['amount']/df['turn']*100, np.nan)
lu=df[df['is_lu']].copy()
print('limitup instances', len(lu))

# --- 市场情绪代理 ---
dates=sorted(df['date'].unique()); didx={d:i for i,d in enumerate(dates)}
daycnt=lu.groupby('date').size().rename('mkt_lu_cnt')
lu=lu.merge(daycnt,on='date',how='left')
# 昨日涨停股今日晋级率(全市场情绪)
lu_by_date={d:set(x) for d,x in lu.groupby('date')['code']}
promo={}
for i,d in enumerate(dates):
    if i==0: continue
    prev=lu_by_date.get(dates[i-1],set()); cur=lu_by_date.get(d,set())
    promo[d]=len(prev&cur)/len(prev) if prev else np.nan
lu['promo_rate']=lu['date'].map(promo)

# --- 概念强度代理: 滚动共振板块规模 (无未来函数, 只用过去60个交易日) ---
# 对每个涨停instance(s,t): 统计当日其他涨停股c中, 与s在[t-60,t-1]窗口内共同涨停>=2次的个数
code_days={}
for c,x in lu.groupby('code')['date']:
    code_days[c]=sorted(didx[d] for d in x)
peers=[]
lu_sorted=lu.sort_values('date')
for d, grp in lu_sorted.groupby('date'):
    i=didx[d]; lo,hi=i-60,i-1
    codes=list(grp['code'])
    wins={c:set(code_days[c][bisect_left(code_days[c],lo):bisect_right(code_days[c],hi)]) for c in codes}
    for c in codes:
        wc=wins[c]; n=0
        if wc:
            for c2 in codes:
                if c2==c: continue
                if len(wc & wins[c2])>=2: n+=1
        peers.append((c,d,n))
pk=pd.DataFrame(peers,columns=['code','date','peer_cnt'])
lu=lu.merge(pk,on=['code','date'],how='left')

# --- 前向收益 ---
lu['ret_open']=(lu['next_open']/lu['close']-1)*100
lu['ret_close']=(lu['next_close']/lu['close']-1)*100
# 次日一字跌停(卖不掉)标记
lu['next_dt_yizi']=(np.abs(lu['next_open']-np.round(lu['next_preclose']*(1-lu['lp']),2))<0.005)&(np.abs(lu['next_high']-lu['next_open'])<0.005)
lu['next_lu']=(np.abs(lu['next_close']-np.round(lu['next_preclose']*(1+lu['lp']),2))<0.005)
lu['month']=lu['date'].str[:7]
cols=['code','date','month','close','turn','fcap','gain20','streak','yizi','isST','lp',
      'mkt_lu_cnt','promo_rate','peer_cnt','ret_open','ret_close','next_lu','next_dt_yizi']
lu[cols].to_csv(OUT,index=False)
print('saved',OUT,len(lu))

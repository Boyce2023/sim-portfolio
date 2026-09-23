#!/opt/homebrew/bin/python3.13
"""20cm 准连板: 连续 N 日每日涨幅都 >= 阈值, 检验"天天强"的约束是否带来胜率。信号日 2026-07-01 到 2026-09-22。
对照同期 5日累计涨幅相近但非连续强势的样本, 看约束本身是否是收益来源。
买入 = 次日开盘(即09:25集合竞价撮合价); 次日开盘即涨停剔除。卖出 T+1/T+3/T+5 收盘。成本 12.3bp。
超额 = 减同信号日同板块全体(买得进者)等权均值。
"""
import math
import pandas as pd, numpy as np
S_D, E_D = pd.Timestamp('2026-07-01'), pd.Timestamp('2026-09-22')
COST = 0.00123

px = pd.read_parquet('data/cn_hk_price_db/a_daily.parquet',
                     columns=['date','ticker','open','close','adj_close','qfq_factor','amount'],
                     filters=[('date','>=',pd.Timestamp('2026-05-01'))]).sort_values(['ticker','date'])
px['adj_open'] = px['open']/px['qfq_factor']
def lim(t):
    c = t[:6]
    if c[:3] in ('300','301','688','689'): return .20
    if c[0] in ('4','8'): return .30
    return .10
px['lim'] = px['ticker'].map(lim)
px['板块'] = px['lim'].map({.10:'10cm主板', .20:'20cm双创', .30:'30cm北交'})
px['ret'] = px.groupby('ticker')['adj_close'].pct_change(fill_method=None)
px['r5'] = px.groupby('ticker')['adj_close'].pct_change(5, fill_method=None)
px['ndays'] = px.groupby('ticker').cumcount()
for n, k in [(1,'T1'),(3,'T3'),(5,'T5')]:
    px[k] = px.groupby('ticker')['adj_close'].shift(-n)/px.groupby('ticker')['adj_open'].shift(-1) - 1 - COST
px['buyable'] = px.groupby('ticker')['open'].shift(-1) < (px['close']*(1+px['lim'])).round(2) - 0.011

base = px[(px['date'] >= S_D) & (px['date'] <= E_D) & (px['ndays'] >= 30) & (px['amount'] >= 3e7)].copy()
B = base[base['buyable']].groupby(['date','板块'])[['T1','T3','T5']].mean().add_suffix('_b')
base = base.merge(B, on=['date','板块'], how='left')
for k in ['T1','T3','T5']: base[k+'_ex'] = base[k] - base[k+'_b']

# 连续N日每日涨幅 >= thr
def streak(df, thr):
    s = (df['ret'] >= thr - 1e-9)
    blk = (~s).groupby(df['ticker']).cumsum()
    n = df.groupby([df['ticker'], blk]).cumcount()
    m = (blk == 0) & s
    n = n.where(~m, n+1)
    return n.where(s, 0)

def rep(x, tag):
    b = x[x['buyable']]
    if len(b) == 0: print(f"{tag:<28} 样本{len(x):>5} 买得进0"); return
    s = f"{tag:<28} 样本{len(x):>5} 买得进{len(b):>5}({len(b)/len(x)*100:3.0f}%)"
    for k in ['T1','T3','T5']:
        v = b[k].dropna(); e = b[k+'_ex'].dropna()
        if len(e) < 3: s += f" | {k} n={len(e)}"; continue
        tt = e.mean()/(e.std(ddof=1)/math.sqrt(len(e))) if e.std(ddof=1) > 0 else float('nan')
        s += f" | {k} {v.mean()*100:+6.2f}% 胜{(v>0).mean()*100:3.0f}% 超额{e.mean()*100:+6.2f}% t={tt:5.2f}"
    print(s)

for thr, name in [(.10,'每日>=10%'), (.13,'每日>=13%'), (.15,'每日>=15%'), (.18,'每日>=18%(准涨停)')]:
    px['st'] = streak(px, thr)
    S = base.merge(px[['date','ticker','st']], on=['date','ticker'], how='left')
    T = S[S['板块'] == '20cm双创']
    print(f"\n【20cm {name}】")
    for n in [2,3,4,5]:
        rep(T[T['st'] == n], f"  连续{n}日")
    rep(T[T['st'] >= 5], "  连续5日及以上")

print("\n【对照 10cm 每日>=9%(准涨停) 连续N日】")
px['st'] = streak(px, .09)
S = base.merge(px[['date','ticker','st']], on=['date','ticker'], how='left')
M = S[S['板块'] == '10cm主板']
for n in [3,4,5,6]:
    rep(M[M['st'] == n], f"  连续{n}日")
rep(M[M['st'] >= 5], "  连续5日及以上")

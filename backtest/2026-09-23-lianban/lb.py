#!/opt/homebrew/bin/python3.13
"""连板策略回测, 信号日 2026-07-01 到 2026-09-22。

连板数来源: 自建机械判定(收盘 >= round(前收*(1+上限),2), 容差0.011)。
⛔该判定已用东财涨停池官方"连板数"字段做锚点校验(2026-09-03 到 09-22, 826条一致825条=99.88%,
   唯一不符为除权日前收口径, 脚本 verify_nb.py 可复跑)。东财池只有14天滚动窗口, 故必须自建才能覆盖60天。
上限: 创业300/301 科创688/689 = 20%; 北交所 4xx/8xx = 30%; 其余 10%。
样本 = 该票首次达到 N 板那一天。
买入 = 次日开盘; 次日开盘价已达涨停 → 买不进, 不计入收益, 单列比例。
卖法 = T+1/T+3/T+5 收盘, 以及破板即卖(买入日起首个收盘未涨停日的收盘)。
成本 一买一卖 12.3bp。收益全部用 adj_close 口径。
"""
import math
import pandas as pd, numpy as np

S_D, E_D = pd.Timestamp('2026-07-01'), pd.Timestamp('2026-09-22')
COST = 0.00123

px = pd.read_parquet('data/cn_hk_price_db/a_daily.parquet',
                     columns=['date','ticker','open','close','adj_close','qfq_factor','amount','oshare'],
                     filters=[('date','>=',pd.Timestamp('2026-05-01'))]).sort_values(['ticker','date'])
px['prev_close'] = px.groupby('ticker')['close'].shift(1)
px['adj_open'] = px['open']/px['qfq_factor']

def lim(t):
    c = t[:6]
    if c[:3] in ('300','301','688','689'): return .20
    if c[0] in ('4','8'): return .30
    return .10
px['lim'] = px['ticker'].map(lim)
px['板块'] = px['lim'].map({.10:'10cm主板', .20:'20cm双创', .30:'30cm北交'})
px['zt'] = px['close'] >= (px['prev_close']*(1+px['lim'])).round(2) - 0.011
px['blk'] = (~px['zt']).groupby(px['ticker']).cumsum()
px['nb'] = px.groupby(['ticker','blk']).cumcount()
m = (px['blk'] == 0) & px['zt']
px.loc[m, 'nb'] = px.loc[m, 'nb'] + 1
px.loc[~px['zt'], 'nb'] = 0
px['float_cap'] = px['close']*px['oshare']/1e8

G = {t: g.reset_index(drop=True) for t, g in px.groupby('ticker')}
P = ['T1','T3','T5','破板卖']

recs = []
for t, g in G.items():
    idx = g.index[(g['nb'] >= 2) & (g['date'] >= S_D) & (g['date'] <= E_D)]
    for i in idx:
        if i+1 > len(g)-1: continue
        ent = g.loc[i+1]
        lp = round(g.loc[i,'close']*(1+g.loc[i,'lim']), 2)
        buyable = bool(ent['open'] < lp - 0.011)
        r = {'date': g.loc[i,'date'], 'ticker': t, 'nb': int(g.loc[i,'nb']), '板块': g.loc[i,'板块'],
             'float_cap': g.loc[i,'float_cap'], 'buyable': buyable,
             'amt': g.loc[i,'amount']/1e8}
        if buyable:
            buy = ent['adj_open']
            for n, k in [(0,'T1'),(2,'T3'),(4,'T5')]:
                j = i+1+n
                r[k] = g.loc[j,'adj_close']/buy-1-COST if j <= len(g)-1 else np.nan
            sell = np.nan
            for j in range(i+1, min(i+21, len(g))):
                if not g.loc[j,'zt']:
                    sell = g.loc[j,'adj_close']/buy-1-COST; break
            r['破板卖'] = sell
        recs.append(r)
S = pd.DataFrame(recs)
S.to_csv('backtest/2026-09-23-lianban/signals.csv', index=False)
print(f"信号 {len(S)} 条, {S['date'].nunique()} 个交易日 {S['date'].min().date()} 到 {S['date'].max().date()}")

def stat(x, tag):
    if len(x) == 0: print(f"{tag:<22} 样本0"); return
    b = x[x['buyable']]
    s = f"{tag:<22} 样本{len(x):>4} 买得进{len(b):>4}({len(b)/len(x)*100:3.0f}%)"
    for p in P:
        y = b[p].dropna()
        if len(y) < 2: s += f" | {p} n={len(y)}"; continue
        tt = y.mean()/(y.std(ddof=1)/math.sqrt(len(y))) if y.std(ddof=1) > 0 else float('nan')
        s += f" | {p} {y.mean()*100:+6.2f}% 胜{(y>0).mean()*100:3.0f}% t={tt:5.2f}"
    print(s)

print("\n【全市场 按板数】")
for n in range(2, 10):
    stat(S[S['nb'] == n], f"首次{n}板")
stat(S[S['nb'] >= 5], "首次5板及以上")

print("\n【按板块 x 板数】")
for bk in ['10cm主板','20cm双创','30cm北交']:
    print(f"-- {bk}")
    for n in [3,4,5,6]:
        stat(S[(S['nb'] == n) & (S['板块'] == bk)], f"  {n}板")
    stat(S[(S['nb'] >= 5) & (S['板块'] == bk)], "  5板+")

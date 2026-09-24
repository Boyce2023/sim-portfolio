#!/opt/homebrew/bin/python3.13
"""五连板次日一字开盘, 挂涨停买入, 当日炸板 → 后续亏多少?

样本: D0 连板数恰为5; D1(次日) 开盘价 = 涨停价(一字开盘); 且 D1 收盘 < 涨停价(炸板)
买入价 = D1 开盘价(即涨停价, 一字开盘时挂单排队成交的价格)
卖出: D1 收盘 / D2 收盘 / D3 收盘 / D5 收盘
成本 一买一卖 12.3bp
对照: 同样一字开盘但当日封住(未炸板)的
⛔连板数自建判定, 已用东财涨停池官方字段校验 99.88%
"""
import math
import pandas as pd, numpy as np
COST=0.00123
px = pd.read_parquet('data/cn_hk_price_db/a_daily.parquet',
    columns=['date','ticker','open','high','low','close','adj_close','qfq_factor','oshare','amount'],
    filters=[('date','>=',pd.Timestamp('2020-06-01'))]).sort_values(['ticker','date'])
px['pc']=px.groupby('ticker')['close'].shift(1)
def lim(t):
    c=t[:6]
    return .20 if c[:3] in ('300','301','688','689') else (.30 if c[0] in ('4','8') else .10)
px['lim']=px['ticker'].map(lim)
px['zt']=px['close']>=(px['pc']*(1+px['lim'])).round(2)-0.011
px['blk']=(~px['zt']).groupby(px['ticker']).cumsum()
px['nb']=px.groupby(['ticker','blk']).cumcount()
m=(px['blk']==0)&px['zt']; px.loc[m,'nb']=px.loc[m,'nb']+1; px.loc[~px['zt'],'nb']=0
g=px.groupby('ticker')
px['nb_prev']=g['nb'].shift(1)
px['ztpx']=(px['pc']*(1+px['lim'])).round(2)     # 当日涨停价
px['一字开']=px['open']>=px['ztpx']-0.011         # 开盘即涨停
px['炸板']=px['一字开'] & (~px['zt'])             # 一字开但收盘没封住
px['adj_buy']=px['open']/px['qfq_factor']        # 买入价(涨停价)
px['D1']=px['adj_close']/px['adj_buy']-1-COST
for n,k in [(1,'D2'),(2,'D3'),(4,'D5')]:
    px[k]=g['adj_close'].shift(-n)/px['adj_buy']-1-COST
px['最低跌幅']=px['low']/px['open']-1
px['流通亿']=px['close']*px['oshare']/1e8

S = px[(px['nb_prev']==5)&px['一字开']].copy()
yj=pd.read_csv('/tmp/bt0922/yjbb.csv',dtype={'股票代码':str})
yj['tk']=yj['股票代码'].str.zfill(6).map(lambda c:c+('.SH' if c[0] in '69' else ('.BJ' if c[0] in '48' else '.SZ')))
S['名称']=S.ticker.map(yj.drop_duplicates('tk',keep='last').set_index('tk')['股票简称'])

def rep(x,tag):
    if len(x)<3: print(f'{tag:<24} n={len(x)} 不足'); return
    s=f'{tag:<24} n={len(x):>4}'
    for k in ['D1','D2','D3','D5']:
        v=x[k].dropna()
        if len(v)<3: s+=f' | {k} n={len(v)}'; continue
        t=v.mean()/(v.std(ddof=1)/math.sqrt(len(v))) if v.std(ddof=1)>0 else float('nan')
        s+=f' | {k} {v.mean()*100:+6.2f}% 中位{v.median()*100:+6.2f}% 胜{(v>0).mean()*100:3.0f}% t={t:6.2f}'
    print(s)

for lo,hi,lab in [(pd.Timestamp('2020-09-01'),pd.Timestamp('2026-09-23'),'六年 2020-09 到 2026-09'),
                  (pd.Timestamp('2026-07-01'),pd.Timestamp('2026-09-23'),'7-9月')]:
    W=S[(S.date>=lo)&(S.date<=hi)]
    print('='*100); print(f'【{lab}】五连板次日一字开盘 共 {len(W)} 个')
    z=W[W['炸板']]; f=W[~W['炸板']]
    print(f'  当日炸板 {len(z)} 个 ({len(z)/max(len(W),1)*100:.0f}%) | 当日封住 {len(f)} 个')
    rep(z,'  ⛔一字开盘后炸板')
    rep(f,'  一字开盘且封住')
    if len(z)>=3:
        print(f"     炸板组当日最大盘中跌幅(相对开盘) 均值 {z['最低跌幅'].mean()*100:.1f}% 最深 {z['最低跌幅'].min()*100:.1f}%")
        print(f"     炸板组 D1 亏超10%的占比 {(z['D1']<-0.10).mean()*100:.0f}% | D5 亏超20%的占比 {(z['D5']<-0.20).mean()*100:.0f}%")

W=S[(S.date>=pd.Timestamp('2026-07-01'))]
print()
print('【7-9月 一字开盘的全部明细】')
ff=lambda v:'n/a' if pd.isna(v) else f'{v*100:+.1f}%'
for _,r in W.sort_values('date').iterrows():
    print(f"  {r['date'].strftime('%m-%d')} {r['名称']:<6} {'⛔炸板' if r['炸板'] else '  封住'} 流通{r['流通亿']:.0f}亿 盘中最低{r['最低跌幅']*100:+6.1f}% | D1 {ff(r['D1']):>7} D2 {ff(r['D2']):>7} D3 {ff(r['D3']):>7} D5 {ff(r['D5']):>7}")

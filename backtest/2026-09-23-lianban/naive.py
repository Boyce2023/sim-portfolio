#!/opt/homebrew/bin/python3.13
"""五板后第六天集合竞价无脑买入(不做任何剔除), 六年维度好不好?
买入 = D1 开盘价(集合竞价撮合价), 不论是否一字。卖出 = 持有N日收盘。成本 12.3bp。
超额 = 减同日全市场(成交额>3000万)同样开盘买入持有N日的等权均值。
"""
import math
import pandas as pd, numpy as np
COST=0.00123; HOLD=[1,2,3,4,5,8,10]
px = pd.read_parquet('data/cn_hk_price_db/a_daily.parquet',
    columns=['date','ticker','open','close','adj_close','qfq_factor','amount','oshare'],
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
px['buy']=g['adj_open'.replace('adj_open','open')].shift(-1)/g['qfq_factor'].shift(-1)
px['nxt_open']=g['open'].shift(-1)
px['一字']=px['nxt_open']>=(px['close']*(1+px['lim'])).round(2)-0.011
for n in HOLD:
    px[f'H{n}']=g['adj_close'].shift(-n)/px['buy']-1-COST
liq=px[px['amount']>=3e7]
B=liq.groupby('date')[[f'H{n}' for n in HOLD]].mean().add_suffix('_b')
S=px[px['nb']==5].copy().merge(B,on='date',how='left')
for n in HOLD: S[f'E{n}']=S[f'H{n}']-S[f'H{n}_b']
for lo,hi,lab in [(pd.Timestamp('2020-09-01'),pd.Timestamp('2026-09-23'),'六年 2020-09 到 2026-09'),
                  (pd.Timestamp('2026-07-01'),pd.Timestamp('2026-09-23'),'7-9月')]:
    W=S[(S.date>=lo)&(S.date<=hi)]
    print('='*104)
    print(f'【{lab}】五板后次日开盘无脑买入 样本 {len(W)} 个 (其中一字开盘 {int(W["一字"].sum())} 个 占{W["一字"].mean()*100:.0f}%)')
    print(f"{'持有':>5}{'样本':>6}{'收益均值':>10}{'中位':>9}{'胜率':>7}{'t':>8}{'超额':>9}{'超额t':>8}{'最大亏':>9}")
    for n in HOLD:
        v=W[f'H{n}'].dropna(); e=W[f'E{n}'].dropna()
        if len(v)<5: continue
        t=v.mean()/(v.std(ddof=1)/math.sqrt(len(v)))
        te=e.mean()/(e.std(ddof=1)/math.sqrt(len(e)))
        print(f"{'T+'+str(n):>5}{len(v):>6}{v.mean()*100:>9.2f}%{v.median()*100:>8.2f}%{(v>0).mean()*100:>6.0f}%{t:>8.2f}{e.mean()*100:>8.2f}%{te:>8.2f}{v.min()*100:>8.1f}%")
    print('  分解: 一字开盘组 vs 非一字组 (T+3)')
    for f,lb in [(W['一字'],'  一字开盘'),(~W['一字'],'  非一字(能正常买)')]:
        x=W[f]['H3'].dropna()
        if len(x)<5: continue
        print(f"{lb:<20} n={len(x):>4} T+3 {x.mean()*100:+6.2f}% 中位{x.median()*100:+6.2f}% 胜{(x>0).mean()*100:3.0f}%")
    print('  按年 T+3:')
    for y,x in W.groupby(W.date.dt.year):
        v=x['H3'].dropna()
        if len(v)<5: continue
        print(f'    {y}  n={len(v):>4}  {v.mean()*100:+6.2f}%  中位{v.median()*100:+6.2f}%  胜{(v>0).mean()*100:3.0f}%')

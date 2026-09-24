#!/opt/homebrew/bin/python3.13
"""五连板次日买入, 持有多久最好? 信号日 2026-07-01 到 2026-09-22, 数据到 09-23。

样本 = 首次5板(连板数恰为5), 次日开盘可买进(开盘未涨停)。⛔买不进的剔除(Buwen 09-24 确认)。
买入 = 次日开盘 adj_open。卖出 = 持有 N 个交易日后的收盘。成本 一买一卖 12.3bp。
超额 = 个股收益 - 同信号日全市场(成交额>3000万)同样买入持有N日的等权平均。
⛔ N 越大可用样本越少(后段信号走不完), 每档都报 n。
"""
import math
import pandas as pd, numpy as np
S_D, E_D = pd.Timestamp('2026-07-01'), pd.Timestamp('2026-09-22')
COST = 0.00123
HOLDS = [1,2,3,4,5,6,8,10,12,15,20]

px = pd.read_parquet('data/cn_hk_price_db/a_daily.parquet',
                     columns=['date','ticker','open','close','adj_close','qfq_factor','amount','oshare'],
                     filters=[('date','>=',pd.Timestamp('2026-05-01'))]).sort_values(['ticker','date'])
px['adj_open']=px['open']/px['qfq_factor']
px['prev_close']=px.groupby('ticker')['close'].shift(1)
def lim(t):
    c=t[:6]
    return .20 if c[:3] in ('300','301','688','689') else (.30 if c[0] in ('4','8') else .10)
px['lim']=px['ticker'].map(lim)
px['zt']=px['close']>=(px['prev_close']*(1+px['lim'])).round(2)-0.011
px['blk']=(~px['zt']).groupby(px['ticker']).cumsum()
px['nb']=px.groupby(['ticker','blk']).cumcount()
m=(px['blk']==0)&px['zt']; px.loc[m,'nb']=px.loc[m,'nb']+1; px.loc[~px['zt'],'nb']=0
px['buyable']=px.groupby('ticker')['open'].shift(-1)<(px['close']*(1+px['lim'])).round(2)-0.011
px['buy_px']=px.groupby('ticker')['adj_open'].shift(-1)
for n in HOLDS:
    px[f'H{n}']=px.groupby('ticker')['adj_close'].shift(-n)/px['buy_px']-1-COST
px['float_cap']=px['close']*px['oshare']/1e8

liq = px[px['amount']>=3e7]
B = liq[liq['buyable']].groupby('date')[[f'H{n}' for n in HOLDS]].mean().add_suffix('_b')

S = px[(px['date']>=S_D)&(px['date']<=E_D)&(px['nb']==5)&px['buyable']].copy()
S = S.merge(B, on='date', how='left')
for n in HOLDS: S[f'E{n}']=S[f'H{n}']-S[f'H{n}_b']
S.to_csv('backtest/2026-09-23-lianban/hold.csv',index=False)
print(f"样本: 首次5板且次日买得进 {len(S)} 个 ({S['date'].min().date()} 到 {S['date'].max().date()})\n")
print(f"{'持有':>4}{'样本':>5}{'收益均值':>10}{'中位':>9}{'胜率':>7}{'t':>7}{'超额':>9}{'超额t':>7}{'最大亏':>9}{'最大赚':>9}")
best=None
for n in HOLDS:
    v=S[f'H{n}'].dropna(); e=S[f'E{n}'].dropna()
    if len(v)<5: print(f"{'T+'+str(n):>4}{len(v):>5}  样本不足"); continue
    t=v.mean()/(v.std(ddof=1)/math.sqrt(len(v)))
    te=e.mean()/(e.std(ddof=1)/math.sqrt(len(e))) if len(e)>2 and e.std(ddof=1)>0 else float('nan')
    print(f"{'T+'+str(n):>4}{len(v):>5}{v.mean()*100:>9.2f}%{v.median()*100:>8.2f}%{(v>0).mean()*100:>6.0f}%{t:>7.2f}{e.mean()*100:>8.2f}%{te:>7.2f}{v.min()*100:>8.1f}%{v.max()*100:>8.1f}%")
    if best is None or v.mean()>best[1]: best=(n,v.mean(),te,len(v))
print(f"\n绝对收益最高: T+{best[0]} 均值{best[1]*100:+.2f}% (n={best[3]}, 超额t={best[2]:.2f})")

print("\n【同口径子集: 只用能走完 T+20 的早期信号, 避免长持有档被截断】")
full=S.dropna(subset=[f'H{n}' for n in HOLDS])
print(f"  可走完全部持有期的样本 {len(full)} 个")
if len(full)>=8:
    print(f"  {'持有':>4}{'收益':>9}{'胜率':>7}{'超额':>9}")
    for n in HOLDS:
        v=full[f'H{n}']; e=full[f'E{n}']
        print(f"  {'T+'+str(n):>4}{v.mean()*100:>8.2f}%{(v>0).mean()*100:>6.0f}%{e.mean()*100:>8.2f}%")

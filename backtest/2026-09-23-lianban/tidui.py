#!/opt/homebrew/bin/python3.13
"""梯队分析 (2026-07-01 到 2026-09-22)。
问题: ①哪些行业出现过"梯队"(同日同行业多只涨停且有连板层次) ②有梯队支撑的五连板是不是比孤票更好 ③梯队是否代表主线。

梯队定义(决策时点可得, 不用未来数据):
  当日某行业涨停家数 >= 3, 且该行业当日最高连板数 >= 3, 且存在至少2个不同的板级(有层次不是齐涨)。
连板数: 自建机械判定, 已用东财涨停池官方字段校验 99.88%(verify_nb.py)。
行业: yjbb.csv 的"所处行业"(申万口径), 按 ticker 取最后一条。
主线检验: 该行业在梯队日之后 5/10/20 个交易日的行业等权收益 vs 全市场等权。
"""
import math
import pandas as pd, numpy as np
S_D, E_D = pd.Timestamp('2026-07-01'), pd.Timestamp('2026-09-22')
COST = 0.00123

px = pd.read_parquet('data/cn_hk_price_db/a_daily.parquet',
                     columns=['date','ticker','open','close','adj_close','qfq_factor','amount','oshare'],
                     filters=[('date','>=',pd.Timestamp('2026-05-01'))]).sort_values(['ticker','date'])
px['adj_open'] = px['open']/px['qfq_factor']
px['prev_close'] = px.groupby('ticker')['close'].shift(1)
def lim(t):
    c = t[:6]
    if c[:3] in ('300','301','688','689'): return .20
    if c[0] in ('4','8'): return .30
    return .10
px['lim'] = px['ticker'].map(lim)
px['zt'] = px['close'] >= (px['prev_close']*(1+px['lim'])).round(2) - 0.011
px['blk'] = (~px['zt']).groupby(px['ticker']).cumsum()
px['nb'] = px.groupby(['ticker','blk']).cumcount()
m = (px['blk'] == 0) & px['zt']; px.loc[m,'nb'] = px.loc[m,'nb']+1
px.loc[~px['zt'],'nb'] = 0
px['ret'] = px.groupby('ticker')['adj_close'].pct_change(fill_method=None)
px['float_cap'] = px['close']*px['oshare']/1e8

yj = pd.read_csv('/tmp/bt0922/yjbb.csv', dtype={'股票代码': str})
yj['ticker'] = yj['股票代码'].str.zfill(6).map(lambda c: c+('.SH' if c[0] in '69' else ('.BJ' if c[0] in '48' else '.SZ')))
ind = yj.drop_duplicates('ticker', keep='last').set_index('ticker')['所处行业']
name = yj.drop_duplicates('ticker', keep='last').set_index('ticker')['股票简称']
px['ind'] = px['ticker'].map(ind); px['name'] = px['ticker'].map(name)

for n, k in [(1,'T1'),(3,'T3'),(5,'T5')]:
    px[k] = px.groupby('ticker')['adj_close'].shift(-n)/px.groupby('ticker')['adj_open'].shift(-1) - 1 - COST
px['buyable'] = px.groupby('ticker')['open'].shift(-1) < (px['close']*(1+px['lim'])).round(2) - 0.011

W = px[(px['date'] >= S_D) & (px['date'] <= E_D)].copy()
Z = W[W['zt'] & W['ind'].notna()]

# 每日每行业梯队指标
A = Z.groupby(['date','ind']).agg(涨停家数=('ticker','size'), 最高板=('nb','max'),
                                  板级数=('nb','nunique'), 连板家数=('nb', lambda s:(s>=2).sum())).reset_index()
A['梯队'] = (A['涨停家数'] >= 3) & (A['最高板'] >= 3) & (A['板级数'] >= 2)
print(f"窗口 {W['date'].nunique()} 个交易日, 涨停记录 {len(Z):,} 条\n")

print("【出现过梯队的行业 按梯队天数排序】")
T = A[A['梯队']].groupby('ind').agg(梯队天数=('date','size'), 最高板=('最高板','max'),
                                   日均涨停=('涨停家数','mean'), 首日=('date','min'), 末日=('date','max'))
T = T.sort_values('梯队天数', ascending=False)
T['首日'] = T['首日'].dt.strftime('%m-%d'); T['末日'] = T['末日'].dt.strftime('%m-%d')
print(T[T['梯队天数'] >= 2].round(1).to_string())

# 五连板 有无梯队支撑
S5 = W[(W['nb'] >= 5)].merge(A[['date','ind','涨停家数','最高板','板级数','梯队']], on=['date','ind'], how='left')
S5['梯队'] = S5['梯队'].fillna(False)
def rep(x, tag):
    b = x[x['buyable']]
    if len(b) == 0: print(f"{tag:<18} 样本{len(x):>3} 买得进0"); return
    s = f"{tag:<18} 样本{len(x):>3} 买得进{len(b):>3}"
    for k in ['T1','T3','T5']:
        v = b[k].dropna()
        if len(v) < 3: s += f" | {k} n={len(v)}"; continue
        tt = v.mean()/(v.std(ddof=1)/math.sqrt(len(v))) if v.std(ddof=1) > 0 else float('nan')
        s += f" | {k} {v.mean()*100:+6.2f}% 胜{(v>0).mean()*100:3.0f}% t={tt:5.2f}"
    print(s)
print("\n【五连板及以上: 有梯队 vs 孤票】")
rep(S5[S5['梯队']], "有梯队支撑")
rep(S5[~S5['梯队']], "孤票无梯队")
print("\n【按同日同行业涨停家数分档】")
for lo, hi, lb in [(1,1,'只有它自己'),(2,2,'2只'),(3,4,'3到4只'),(5,99,'5只以上')]:
    rep(S5[S5['涨停家数'].fillna(1).between(lo,hi)], lb)

S5.to_csv('backtest/2026-09-23-lianban/tidui_5b.csv', index=False)
print("\n【五连板明细 含行业与梯队】")
d = S5[S5['buyable']].sort_values('date')
print(d[['date','ticker','name','ind','nb','涨停家数','最高板','梯队','float_cap','T1','T3','T5']].assign(
    date=lambda x: x['date'].dt.strftime('%m-%d'), float_cap=lambda x: x['float_cap'].round(0),
    T1=lambda x:(x['T1']*100).round(1), T3=lambda x:(x['T3']*100).round(1), T5=lambda x:(x['T5']*100).round(1)
).to_string(index=False))

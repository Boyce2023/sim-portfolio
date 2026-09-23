#!/opt/homebrew/bin/python3.13
"""20cm(创业300/301 科创688/689) 前5日累计涨幅分档 → 后续胜率。信号日 2026-07-01 到 2026-09-22。

口径:
  信号 = 每个交易日每只票的 前5日累计涨幅 r5 = adj_close_t / adj_close_{t-5} - 1
  买入 = 次日开盘(adj_open); 次日开盘即涨停 → 买不进, 不计入收益, 单列比例
  卖出 = T+1 / T+3 / T+5 收盘(adj_close)
  成本 = 一买一卖 12.3bp
  超额 = 个股收益 - 同信号日同板块(20cm或10cm)全体的等权平均收益(同样卖法)
剔除: ST、上市不足30个交易日、当日成交额<3000万(买不进的僵尸票)
⛔本脚本只用决策时点已知的数据(r5用t日及以前), 分档阈值为固定值不是样本分位数(避免前视)。
"""
import math
import pandas as pd, numpy as np

S_D, E_D = pd.Timestamp('2026-07-01'), pd.Timestamp('2026-09-22')
COST = 0.00123
BINS = [-1, 0, .10, .20, .30, .50, .80, 1.20, 99]
LABS = ['<0', '0-10%', '10-20%', '20-30%', '30-50%', '50-80%', '80-120%', '>120%']

px = pd.read_parquet('data/cn_hk_price_db/a_daily.parquet',
                     columns=['date','ticker','open','close','adj_close','qfq_factor','amount'],
                     filters=[('date','>=',pd.Timestamp('2026-05-01'))]).sort_values(['ticker','date'])
px['adj_open'] = px['open']/px['qfq_factor']
px['prev_close'] = px.groupby('ticker')['close'].shift(1)

def lim(t):
    c = t[:6]
    if c[:3] in ('300','301','688','689'): return .20
    if c[0] in ('4','8'): return .30
    return .10
px['lim'] = px['ticker'].map(lim)
px['板块'] = px['lim'].map({.10:'10cm主板', .20:'20cm双创', .30:'30cm北交'})
px['r5'] = px.groupby('ticker')['adj_close'].pct_change(5, fill_method=None)
px['ndays'] = px.groupby('ticker').cumcount()

# 次日各卖法收益(先整表算, 再按信号日取)
for n, k in [(1,'T1'),(3,'T3'),(5,'T5')]:
    px[k] = px.groupby('ticker')['adj_close'].shift(-n)/px.groupby('ticker')['adj_open'].shift(-1) - 1 - COST
px['nxt_open'] = px.groupby('ticker')['open'].shift(-1)
px['buyable'] = px['nxt_open'] < (px['close']*(1+px['lim'])).round(2) - 0.011

S = px[(px['date'] >= S_D) & (px['date'] <= E_D) & (px['ndays'] >= 30) &
       (px['amount'] >= 3e7) & px['r5'].notna() & px['板块'].isin(['10cm主板','20cm双创'])].copy()
S['bin'] = pd.cut(S['r5'], BINS, labels=LABS)

# 同日同板块基准(含买不进的也算基准? 否: 基准同样只取买得进的, 口径一致)
B = S[S['buyable']].groupby(['date','板块'])[['T1','T3','T5']].mean().add_suffix('_b')
S = S.merge(B, on=['date','板块'], how='left')
for k in ['T1','T3','T5']:
    S[k+'_ex'] = S[k] - S[k+'_b']
S.to_csv('backtest/2026-09-23-lianban/r5_signals.csv', index=False)
print(f"信号 {len(S):,} 条 ({S['date'].nunique()} 个交易日), 20cm {int((S['板块']=='20cm双创').sum()):,} 条, 10cm {int((S['板块']=='10cm主板').sum()):,} 条")

def tab(x, title):
    print(f"\n{title}")
    print(f"{'档位':<10}{'样本':>7}{'买得进':>8}", end='')
    for k in ['T1','T3','T5']: print(f"{k+'收益':>9}{'胜率':>6}{k+'超额':>9}{'t':>7}", end='')
    print()
    for lb in LABS:
        y = x[x['bin'] == lb]
        b = y[y['buyable']]
        if len(y) == 0: continue
        print(f"{lb:<10}{len(y):>7}{len(b)/max(len(y),1)*100:>7.0f}%", end='')
        for k in ['T1','T3','T5']:
            v = b[k].dropna(); e = b[k+'_ex'].dropna()
            if len(v) < 3: print(f"{'n/a':>9}{'':>6}{'':>9}{'':>7}", end=''); continue
            tt = e.mean()/(e.std(ddof=1)/math.sqrt(len(e))) if len(e) > 2 and e.std(ddof=1) > 0 else float('nan')
            print(f"{v.mean()*100:>8.2f}%{(v>0).mean()*100:>5.0f}%{e.mean()*100:>8.2f}%{tt:>7.2f}", end='')
        print()

tab(S[S['板块'] == '20cm双创'], "【20cm 创业板加科创板】前5日累计涨幅分档")
tab(S[S['板块'] == '10cm主板'], "【10cm 主板 对照】前5日累计涨幅分档")

print("\n【20cm 高涨幅段细分】")
H = S[(S['板块'] == '20cm双创') & (S['r5'] >= .30) & S['buyable']]
H = H.assign(b2=pd.cut(H['r5'], [.3,.4,.5,.6,.8,1.0,1.5,99],
                       labels=['30-40%','40-50%','50-60%','60-80%','80-100%','100-150%','>150%']))
g = H.groupby('b2', observed=True).agg(样本=('T3','size'), T1=('T1','mean'), T1胜=('T1', lambda s:(s>0).mean()),
    T3=('T3','mean'), T3胜=('T3', lambda s:(s>0).mean()), T3超额=('T3_ex','mean'),
    T5=('T5','mean'), T5胜=('T5', lambda s:(s>0).mean()), T5超额=('T5_ex','mean'))
print((g*100).round(2).assign(样本=g['样本']).to_string())

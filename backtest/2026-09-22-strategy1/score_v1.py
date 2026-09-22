#!/opt/homebrew/bin/python3.13
"""策略一概率打分 v1 (2026-09-22): 把门改成分布, 与 b_score 同一形式。

每个因子分档, 在训练段算"该档相对训练段全体的平均超额(pp)"与"止损概率", 候选总分 = 各因子档位贡献之和。
训练 2026-07-20 到 08-20 信号, 测试 08-21 到 09-14 信号; 看测试段按总分五等分后 均值/胜率/止损率 是否单调。
因子: 前一日涨幅档 / 总市值档 / 个股前20日涨幅(位置) / 行业前20日热度排名 / 基本面代理。
"""
import pandas as pd, numpy as np
BT = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-09-22-strategy1/'
DB = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_daily.parquet'
R = pd.read_csv(BT + 'trades.csv', parse_dates=['date'])

px = pd.read_parquet(DB, columns=['date', 'ticker', 'adj_close'], filters=[('date', '>=', pd.Timestamp('2026-05-01'))])
px = px.sort_values(['ticker', 'date'])
px['r20'] = px.groupby('ticker')['adj_close'].pct_change(20, fill_method=None)
R = R.merge(px[['date', 'ticker', 'r20']], on=['date', 'ticker'], how='left')

# 行业前20日热度排名(当日全市场行业中位)
yj = pd.read_csv('/tmp/bt0922/yjbb.csv', dtype={'股票代码': str})
yj['ticker'] = yj['股票代码'].str.zfill(6).map(lambda c: c + ('.SH' if c.startswith('6') else '.SZ'))
ind = yj.drop_duplicates('ticker', keep='last').set_index('ticker')['所处行业']
px['ind'] = px['ticker'].map(ind)
rank = (px.groupby(['date', 'ind'])['r20'].median().groupby(level=0).rank(ascending=False, pct=True)
        .rename('ind_heat').reset_index())
R = R.merge(rank, on=['date', 'ind'], how='left')

R['stop'] = (R['how'] == 'stop').astype(int)
R['f_sig'] = pd.cut(R['sig_ret'] * 100, [5, 7, 9.5, 10.5, 30], labels=['5-7', '7-9.5', '10cm板', '>10.5'])
R['f_cap'] = pd.cut(R['mcap'], [120, 160, 220, 280, 350], labels=['120-160', '160-220', '220-280', '280-350'], include_lowest=True)
R['f_pos'] = pd.cut(R['r20'] * 100, [-99, 0, 15, 30, 60, 999], labels=['<0', '0-15', '15-30', '30-60', '>60'])
R['f_heat'] = pd.cut(R['ind_heat'], [0, 0.1, 0.3, 0.7, 1.0], labels=['最热10%', '10-30%', '30-70%', '最冷30%'], include_lowest=True)
R['f_fund'] = R['fund'].map({True: '基本面过', False: '基本面不过'})
F = ['f_sig', 'f_cap', 'f_pos', 'f_heat', 'f_fund']

tr = R[R['date'] <= '2026-08-20'].copy()
te = R[R['date'] > '2026-08-20'].copy()
base = tr['excess'].mean()
tab = {}
print(f"训练 {len(tr)} 笔(基线超额 {base*100:+.2f}%)  测试 {len(te)} 笔\n")
for f in F:
    g = tr.groupby(f, observed=True).agg(n=('excess', 'size'), ex=('excess', 'mean'), stop=('stop', 'mean'), win=('ret', lambda x: (x > 0).mean()))
    g['delta_pp'] = (g['ex'] - base) * 100
    # 小样本收缩: 权重 n/(n+100)
    g['delta_shrunk'] = g['delta_pp'] * g['n'] / (g['n'] + 100)
    tab[f] = g['delta_shrunk'].to_dict()
    print(f"[{f}]"); print(g.round(4).to_string()); print()

for df in (tr, te):
    df['score'] = sum(df[f].map(tab[f]).astype(float).fillna(0) for f in F)
te['q'] = pd.qcut(te['score'].rank(method='first'), 5, labels=['Q1低', 'Q2', 'Q3', 'Q4', 'Q5高'])
print("⛔ 样本外(测试段)按总分五等分:")
print(te.groupby('q', observed=True).agg(n=('ret', 'size'), 均值=('ret', 'mean'), 中位=('ret', 'median'),
      胜率=('ret', lambda x: (x > 0).mean()), 止损率=('stop', 'mean'), 超额=('excess', 'mean')).round(4).to_string())
pd.Series({f: tab[f] for f in F}).to_json(BT + 'score_v1_table.json', force_ascii=False)

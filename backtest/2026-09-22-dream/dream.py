#!/opt/homebrew/bin/python3.13
"""做梦 v1 (2026-09-22): 把模拟盘 A股 全部历史交易当作发现树, 在同一批买点上回放不同的卖法与选股打分。

思路来自 Google Dream-RSI: 历史就是模拟器。一次真实探索留下的记录, 可以拿来推演"当时换一种策略会怎样"。
我们比论文条件更好: 有全市场日线, 任何卖法都能算出真实结果, 不止能回放走过的分支。

节点 = 一个持仓段(同一只票从空仓买入到再次清仓)。买点取首笔买入日与首笔成交价。
回放卖法:
  P0 实际
  P1 持3个交易日收盘卖      P2 持5日收盘卖(现行3.4)
  P3 持5日加7.5%收盘止损(现行3.4加3.5)
  P4 持10日  P5 持20日  P6 只守-12%灾难线, 否则持20日
选股侧: 用 score_v1 的两个主因子(个股前20日涨幅档 / 行业前20日热度档)给每个买点打分, 看实际盈亏是否随分数变化。
⛔前视: score_v1 训练段为 07-20 到 08-20; 该段内买点的打分偏乐观, 07-20 以前的买点才是干净样本外。
"""
import json, pandas as pd, numpy as np
ROOT = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/'
OUT = ROOT + 'backtest/2026-09-22-dream/'

st = json.load(open(ROOT + 'portfolio_state.json'))
tl = [t for t in st['trade_log'] if t.get('account') == 'a_share']
T = pd.DataFrame(tl)
T['ts'] = pd.to_datetime(T['timestamp'].str[:19])
T['d'] = T['ts'].dt.normalize()
T['sgn'] = T['action'].map({'buy': 1, 'sell': -1})
T = T.sort_values('ts')

# 组装持仓段
eps = []
for tk, g in T.groupby('ticker'):
    pos, cur = 0, None
    for _, r in g.iterrows():
        if r['action'] == 'buy':
            if pos == 0:
                cur = {'ticker': tk, 'name': r.get('name'), 'entry_d': r['d'], 'entry_px': r['price'],
                       'buy_val': 0.0, 'sell_val': 0.0, 'entry_reason': str(r.get('reason'))[:120]}
            pos += r['shares']; cur['buy_val'] += r['value']
        else:
            if cur is None:
                continue
            pos -= r['shares']; cur['sell_val'] += r['value']
            if pos <= 0:
                cur['exit_d'] = r['d']; cur['exit_reason'] = str(r.get('reason'))[:120]
                eps.append(cur); cur, pos = None, 0
    if cur is not None:
        cur['exit_d'] = pd.NaT; eps.append(cur)
E = pd.DataFrame(eps)
E['closed'] = E['exit_d'].notna()
E['act_ret'] = np.where(E['closed'], E['sell_val'] / E['buy_val'] - 1, np.nan)
E['act_pnl'] = np.where(E['closed'], E['sell_val'] - E['buy_val'], np.nan)
E['hold_days'] = (E['exit_d'] - E['entry_d']).dt.days
print(f"持仓段 {len(E)} 个(已平 {int(E['closed'].sum())}), 标的 {E['ticker'].nunique()} 只")

# 行情
code = E['ticker'].astype(str).str.zfill(6)
E['tk'] = code.map(lambda c: c + ('.SH' if c.startswith(('6', '9')) else '.SZ'))
px = pd.read_parquet(ROOT + 'data/cn_hk_price_db/a_daily.parquet',
                     columns=['date', 'ticker', 'close', 'adj_close', 'qfq_factor'],
                     filters=[('date', '>=', pd.Timestamp('2026-03-01'))])
px = px.sort_values(['ticker', 'date'])
px['r20'] = px.groupby('ticker')['adj_close'].pct_change(20, fill_method=None)
G = {t: g.reset_index(drop=True) for t, g in px.groupby('ticker') if t in set(E['tk'])}


def replay(row):
    g = G.get(row['tk'])
    out = {}
    if g is None:
        return out
    i = g.index[g['date'] >= row['entry_d']]
    if len(i) == 0:
        return out
    i = i[0]
    buy_adj = row['entry_px'] / g.loc[i, 'qfq_factor']
    out['r20_entry'] = g.loc[i - 1, 'r20'] if i > 0 else np.nan

    def at(n):
        j = min(i + n, len(g) - 1)
        return g.loc[j, 'adj_close'] / buy_adj - 1, (i + n) <= len(g) - 1

    for n, k in [(3, 'P1_T3'), (5, 'P2_T5'), (10, 'P4_T10'), (20, 'P5_T20')]:
        r, full = at(n); out[k] = r if full else np.nan
    # P3 T5 加 7.5% 止损
    end = min(i + 5, len(g) - 1); r3 = g.loc[end, 'adj_close'] / buy_adj - 1
    for j in range(i, end + 1):
        if g.loc[j, 'adj_close'] <= buy_adj * 0.925:
            r3 = g.loc[j, 'adj_close'] / buy_adj - 1; break
    out['P3_T5stop'] = r3 if i + 5 <= len(g) - 1 else np.nan
    # P6 灾难线 -12% 否则 T20
    end = min(i + 20, len(g) - 1); r6 = g.loc[end, 'adj_close'] / buy_adj - 1
    for j in range(i, end + 1):
        if g.loc[j, 'adj_close'] <= buy_adj * 0.88:
            r6 = g.loc[j, 'adj_close'] / buy_adj - 1; break
    out['P6_disaster'] = r6 if i + 20 <= len(g) - 1 else np.nan
    return out


R = E.apply(lambda r: pd.Series(replay(r)), axis=1)
E = pd.concat([E, R], axis=1)

# 行业热度(与 score_v1 同口径)
yj = pd.read_csv('/tmp/bt0922/yjbb.csv', dtype={'股票代码': str})
yj['tk'] = yj['股票代码'].str.zfill(6).map(lambda c: c + ('.SH' if c.startswith('6') else '.SZ'))
indm = yj.drop_duplicates('tk', keep='last').set_index('tk')['所处行业']
px['ind'] = px['ticker'].map(indm)
heat = px.groupby(['date', 'ind'])['r20'].median().groupby(level=0).rank(ascending=False, pct=True).rename('heat').reset_index()
E['ind'] = E['tk'].map(indm)
E = E.merge(heat.rename(columns={'date': 'entry_d'}), on=['entry_d', 'ind'], how='left')

tab = pd.read_json(ROOT + 'backtest/2026-09-22-strategy1/score_v1_table.json', typ='series')
pos_tab, heat_tab = tab['f_pos'], tab['f_heat']
E['f_pos'] = pd.cut(E['r20_entry'] * 100, [-99, 0, 15, 30, 60, 999], labels=['<0', '0-15', '15-30', '30-60', '>60']).astype(str)
E['f_heat'] = pd.cut(E['heat'], [0, 0.1, 0.3, 0.7, 1.0], labels=['最热10%', '10-30%', '30-70%', '最冷30%'], include_lowest=True).astype(str)
E['score'] = E['f_pos'].map(pos_tab).fillna(0) + E['f_heat'].map(heat_tab).fillna(0)

# 规则时代
cuts = [('A 05-18到07-08 早期', '2026-05-18', '2026-07-08'), ('B 07-09到08-23 T18整合版', '2026-07-09', '2026-08-23'),
        ('C 08-24到09-16 T18大改后', '2026-08-24', '2026-09-16'), ('D 09-17起 v13与v14', '2026-09-17', '2026-12-31')]
E['era'] = None
for n, a, b in cuts:
    E.loc[(E['entry_d'] >= a) & (E['entry_d'] <= b), 'era'] = n
E.to_csv(OUT + 'episodes.csv', index=False)

P = ['act_ret', 'P1_T3', 'P2_T5', 'P3_T5stop', 'P4_T10', 'P5_T20', 'P6_disaster']
C = E[E['closed']].copy()
print("\n【卖法回放】同一批买点, 每段按买入金额加权的总盈亏(万元)与等权平均收益")
rows = []
for p in P:
    x = C.dropna(subset=[p])
    rows.append((p, len(x), (x[p] * x['buy_val']).sum() / 1e4, x[p].mean() * 100, x[p].median() * 100, (x[p] > 0).mean() * 100))
print(pd.DataFrame(rows, columns=['卖法', '段数', '总盈亏万', '均值%', '中位%', '胜率%']).round(2).to_string(index=False))
print("  ⛔各卖法可用段数不同(持20日需足够后续行情), 同口径比较见下:")
cc = C.dropna(subset=P)
print("  同一批(所有卖法都可算)", len(cc), "段:")
print(pd.DataFrame([(p, (cc[p] * cc['buy_val']).sum() / 1e4, cc[p].mean() * 100, (cc[p] > 0).mean() * 100) for p in P],
                   columns=['卖法', '总盈亏万', '均值%', '胜率%']).round(2).to_string(index=False))

print("\n【按规则时代】实际 vs 最佳回放")
for e, x in C.groupby('era'):
    s = {p: (x[p] * x['buy_val']).sum() / 1e4 for p in P if x[p].notna().all()}
    print(f"  {e:<24} {len(x):>3}段 实际{(x['act_pnl']).sum()/1e4:+8.1f}万 胜率{(x['act_ret']>0).mean()*100:4.0f}% 持有中位{x['hold_days'].median():.0f}天 | 回放: " +
          " ".join(f"{k}{v:+.1f}" for k, v in s.items() if k != 'act_ret'))

print("\n【选股侧】打分表 v1 对历史买点的区分力")
for tag, x in [('全部已平', C), ('干净样本外 07-20以前', C[C['entry_d'] < '2026-07-20'])]:
    x = x.dropna(subset=['score'])
    if len(x) < 10:
        continue
    x = x.assign(q=pd.qcut(x['score'].rank(method='first'), 3, labels=['低分', '中分', '高分']))
    print(f"  {tag}:")
    print(x.groupby('q', observed=True).agg(段数=('act_ret', 'size'), 实际均值=('act_ret', 'mean'), 实际胜率=('act_ret', lambda s: (s > 0).mean()),
          实际盈亏万=('act_pnl', lambda s: s.sum() / 1e4), T5止损均值=('P3_T5stop', 'mean')).round(3).to_string())
print("\n  买点前20日涨幅档 实际表现(全部已平):")
print(C.groupby('f_pos').agg(段数=('act_ret', 'size'), 实际均值=('act_ret', 'mean'), 胜率=('act_ret', lambda s: (s > 0).mean()),
      盈亏万=('act_pnl', lambda s: s.sum() / 1e4)).round(3).to_string())

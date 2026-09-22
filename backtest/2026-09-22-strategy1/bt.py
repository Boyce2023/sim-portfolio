#!/opt/homebrew/bin/python3.13
"""策略一骨架回测, 过去约两个月 (信号日 2026-07-20 到 2026-09-14, 保证 T+5 能在 09-21 前走完)。

只能回测机械可复现的部分; 三段式里的外部事件与链上位置判断无法机械化, 不在本回测里。
变体:
  A 射程加动量:   总市值120到350亿 & 信号日涨幅>5%
  B A加基本面:    信号日当时已公告的最新一期 净利润同比>0 & 净利润季度环比>0 & 每股经营现金流>0 (用公告日期防前视)
  C B加主线代理:  所处行业在信号日按前20日中位涨幅排前5
买入: 信号日次日开盘; 次日开盘即涨停(买不进)剔除。
卖出: 3.4 持有到买入后第5个交易日收盘; 3.5 期间任一收盘 <= 买价x0.925 则当日收盘止损。
成本: 一买一卖 12.3bp。
基准: 同一信号日、同一射程内全部股票, 同样次日开盘买入持有5日的等权平均(超额=个股-基准)。
总市值: 以 2026-09-08 iFinD 总市值 / 当日收盘 反推总股本, 乘信号日收盘(两个月内股本视为不变)。
收益用 adj_close 与 open/adj 同比例换算, 避免除权日失真。
"""
import pandas as pd, numpy as np, math
DB = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_daily.parquet'
S, E = pd.Timestamp('2026-07-20'), pd.Timestamp('2026-09-14')
COST = 0.00123

px = pd.read_parquet(DB, columns=['date', 'ticker', 'open', 'close', 'adj_close', 'qfq_factor'],
                     filters=[('date', '>=', pd.Timestamp('2026-05-01'))])
px = px[px['ticker'].str.endswith(('.SH', '.SZ'))].sort_values(['ticker', 'date'])
px['adj_open'] = px['open'] / px['qfq_factor']
px['ret'] = px.groupby('ticker')['adj_close'].pct_change(fill_method=None)
px['ret5'] = px.groupby('ticker')['adj_close'].pct_change(5, fill_method=None)
px['ret20'] = px.groupby('ticker')['adj_close'].pct_change(20, fill_method=None)
px['prev_close'] = px.groupby('ticker')['close'].shift(1)

sh = pd.read_csv('/tmp/bt0922/shares.csv')[['ticker', 'shares']]
px = px.merge(sh, on='ticker', how='left')
px['mcap'] = px['close'] * px['shares'] / 1e8

yj = pd.read_csv('/tmp/bt0922/yjbb.csv', dtype={'股票代码': str})
yj['ticker'] = yj['股票代码'].str.zfill(6).map(lambda c: c + ('.SH' if c.startswith('6') else '.SZ'))
yj['ann'] = pd.to_datetime(yj['最新公告日期'], errors='coerce')
yj = yj.rename(columns={'净利润-同比增长': 'np_yoy', '净利润-季度环比增长': 'np_qoq', '每股经营现金流量': 'ocf_ps', '所处行业': 'ind', '股票简称': 'name'})
yj = yj[['ticker', 'ann', 'period', 'np_yoy', 'np_qoq', 'ocf_ps', 'ind', 'name']].dropna(subset=['ann']).sort_values('ann')
ind_map = yj.drop_duplicates('ticker', keep='last').set_index('ticker')['ind']
name_map = yj.drop_duplicates('ticker', keep='last').set_index('ticker')['name']
px['ind'] = px['ticker'].map(ind_map)
px['name'] = px['ticker'].map(name_map)

dates = sorted(px['date'].unique())
didx = {d: i for i, d in enumerate(dates)}
g = {t: df.reset_index(drop=True) for t, df in px.groupby('ticker')}


def fundamental_ok(tk, d):
    r = yj[(yj['ticker'] == tk) & (yj['ann'] <= d)]
    if r.empty:
        return False
    r = r.iloc[-1]
    return (r['np_yoy'] > 0) and (r['np_qoq'] > 0) and (r['ocf_ps'] > 0)


def trade(tk, d):
    df = g[tk]
    i = df.index[df['date'] == d]
    if len(i) == 0:
        return None
    i = i[0]
    if i + 6 > len(df) - 1 + 0:
        pass
    if i + 1 >= len(df):
        return None
    ent = df.loc[i + 1]
    lim = 0.2 if tk.startswith(('30', '68')) else 0.1
    if ent['open'] >= round(df.loc[i, 'close'] * (1 + lim), 2) - 0.001:
        return None  # 开盘即涨停, 买不进
    buy = ent['adj_open']
    end = min(i + 1 + 5, len(df) - 1)
    if dates.index(df.loc[end, 'date']) - dates.index(ent['date']) < 5 and end == len(df) - 1 and df.loc[end, 'date'] < dates[-1]:
        return None
    exit_px, how = df.loc[end, 'adj_close'], 'T+5'
    for j in range(i + 1, end + 1):
        if df.loc[j, 'adj_close'] <= buy * 0.925:
            exit_px, how = df.loc[j, 'adj_close'], 'stop'
            break
    return exit_px / buy - 1 - COST, how


sig_days = [d for d in dates if S <= d <= E]
recs, bench = [], {}
for d in sig_days:
    day = px[(px['date'] == d) & px['mcap'].between(120, 350) & ~px['name'].fillna('').str.contains('ST')]
    # 基准: 射程内全部
    bs = [trade(t, d) for t in day['ticker']]
    bs = [b[0] for b in bs if b and np.isfinite(b[0])]
    bench[d] = np.mean(bs) if bs else np.nan
    # 主线代理: 行业前20日中位涨幅前5
    allday = px[px['date'] == d]
    top5 = allday.groupby('ind')['ret20'].median().dropna().sort_values(ascending=False).head(5).index
    top5_5 = allday.groupby('ind')['ret5'].median().dropna().sort_values(ascending=False).head(5).index
    top5_1 = allday.groupby('ind')['ret'].median().dropna().sort_values(ascending=False).head(5).index
    for _, r in day[day['ret'] > 0.05].iterrows():
        t = trade(r['ticker'], d)
        if not t or not np.isfinite(t[0]):
            continue
        f = fundamental_ok(r['ticker'], d)
        recs.append({'date': d, 'ticker': r['ticker'], 'name': r['name'], 'ind': r['ind'], 'mcap': r['mcap'],
                     'sig_ret': r['ret'], 'ret': t[0], 'how': t[1], 'fund': f, 'main': r['ind'] in top5, 'main5': r['ind'] in top5_5, 'main1': r['ind'] in top5_1,
                     'excess': t[0] - bench[d]})
R = pd.DataFrame(recs)
R.to_csv('/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-09-22-strategy1/trades.csv', index=False)


def stat(x, tag):
    if len(x) == 0:
        print(f"{tag:<34} n=0"); return
    m, s = x['ret'].mean(), x['ret'].std(ddof=1)
    tt = m / (s / math.sqrt(len(x))) if len(x) > 1 and s > 0 else float('nan')
    ex = x['excess'].mean()
    ext = ex / (x['excess'].std(ddof=1) / math.sqrt(len(x))) if len(x) > 1 else float('nan')
    print(f"{tag:<34} n={len(x):>4}  均值{m*100:+6.2f}%  中位{x['ret'].median()*100:+6.2f}%  胜率{(x['ret']>0).mean()*100:5.1f}%  "
          f"t={tt:5.2f}  超额{ex*100:+6.2f}% t={ext:5.2f}  止损占{(x['how']=='stop').mean()*100:4.1f}%")


print(f"信号日 {len(sig_days)} 天 ({sig_days[0].date()} 到 {sig_days[-1].date()}), 射程内基准5日均收益 {np.nanmean(list(bench.values()))*100:+.2f}%")
stat(R, 'A 射程加动量')
stat(R[R['fund']], 'B A加基本面(当时已公告)')
stat(R[R['fund'] & R['main']], 'C B加主线代理(行业前20日前5)')
stat(R[R['fund'] & R['main5']], 'C5 B加主线(行业前5日前5)')
stat(R[R['fund'] & R['main1']], 'C1 B加主线(信号当日领涨行业前5)')
stat(R[R['main1']], 'D 只看当日领涨行业(不要基本面)')
stat(R[R['fund'] & ~R['main'] & ~R['main5'] & ~R['main1']], 'E B且不在任何热门行业')
stat(R[~R['fund']], '对照 A中基本面不过的')
stat(R[R['main'] & ~R['fund']], '对照 主线但基本面不过')
# 分月
R['m'] = R['date'].dt.strftime('%m')
for m, x in R[R['fund']].groupby('m'):
    stat(x, f'B 按月 {m}')

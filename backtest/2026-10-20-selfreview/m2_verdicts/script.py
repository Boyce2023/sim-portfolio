#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股模拟盘 scan_history 裁决回测 (2026-10-20)
问题: 我没买的票后来怎样? probe有没有edge? reject对不对?

只读脚本: 不碰 sim-portfolio 下任何已有文件(不写不改), 不调用任何下单/写库脚本。
数据源: 本地 a_daily.parquet (禁 yfinance), portfolio_state.json trade_log(只读),
        scan_history.jsonl(只读), market_calendar.json(只读, 仅用于交叉验证交易日历)。
产出: verdicts_fwd.csv (long format逐行逐basis逐窗口) + summary.md, 均写入本目录(OUT)。
"""
import json
import os
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

BASE = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio'
OUT = f'{BASE}/backtest/2026-10-20-selfreview/m2_verdicts'
os.makedirs(OUT, exist_ok=True)

TODAY = pd.Timestamp('2026-10-20')
NS = [1, 5, 10, 20]

# ------------------------------------------------------------------
# 1. 交易日历 + 全市场价格面板 (2026-06-01 ~ 10-19, 覆盖全部裁决日的前向窗口)
# ------------------------------------------------------------------
tbl = pq.read_table(
    f'{BASE}/data/cn_hk_price_db/a_daily.parquet',
    filters=[('date', '>=', pd.Timestamp('2026-06-01')), ('date', '<=', pd.Timestamp('2026-10-19'))],
)
px = tbl.to_pandas()
px['date'] = pd.to_datetime(px['date'])

trading_days = np.array(sorted(px['date'].unique()))
day_idx = {pd.Timestamp(d): i for i, d in enumerate(trading_days)}
# 扩展索引: 今天(2026-10-20)尚无收盘价, 只用于"去重"和"5个交易日内买入"的天数差计算, 绝不用于取价
ext_day_idx = dict(day_idx)
ext_day_idx[TODAY] = len(trading_days)

# 交叉验证: market_calendar.json 的休市日不应出现在本地价格库的交易日里
cal = json.load(open(f'{BASE}/market_calendar.json'))
closed = set(cal['trading_days_by_market']['cn_closed_dates'])
bad = [d for d in trading_days if pd.Timestamp(d).strftime('%Y-%m-%d') in closed]
assert not bad, f'价格库里出现了market_calendar标记的休市日: {bad}'

px_idx = px.set_index(['date', 'ticker'])
close_w = px_idx['close'].unstack('ticker').reindex(trading_days)
adjc_w = px_idx['adj_close'].unstack('ticker').reindex(trading_days)
open_w = px_idx['open'].unstack('ticker').reindex(trading_days)
high_w = px_idx['high'].unstack('ticker').reindex(trading_days)
low_w = px_idx['low'].unstack('ticker').reindex(trading_days)

tickers_all = close_w.columns


def board_pct(full_ticker):
    code = full_ticker[:6]
    if code[:2] in ('30', '68'):
        return 0.20
    return 0.10  # 00/60主板默认10%; 北交所4/8/92本地库无覆盖(见下), 主板ST 5%/10%例外核查后在本数据集不适用(见summary方法论)


pct_series = pd.Series({t: board_pct(t) for t in tickers_all}).reindex(tickers_all)
prev_close_w = close_w.shift(1)
limit_price_w = prev_close_w.mul(1 + pct_series, axis=1).round(2)
is_limitup_w = (close_w >= limit_price_w - 0.005) & (close_w == high_w)
is_yizi_w = is_limitup_w & (open_w == high_w) & (low_w == high_w)

ratio_w = adjc_w / close_w.replace(0, np.nan)
adj_open_w = open_w * ratio_w


def to_full(code):
    if code is None or code == '':
        return None
    p2 = code[:2]
    if p2 in ('00', '30'):
        return code + '.SZ'
    if p2 in ('60', '68'):
        return code + '.SH'
    if code[0] in ('4', '8') or p2 == '92':
        return code + '.BJ'  # 本地库目前无北交所数据, 会被标记为data_unavailable
    return None


# ------------------------------------------------------------------
# 2. 读 scan_history.jsonl
# ------------------------------------------------------------------
records = []
with open(f'{BASE}/scan_history.jsonl') as f:
    for i, line in enumerate(f):
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        d['_lineno'] = i + 1
        records.append(d)

print(f'scan_history.jsonl 共 {len(records)} 行')

# 16行decision为空: 1行(328) date/ticker/name全空(是08-13的"watch_pool_deprecation"系统记录,不是一条裁决,整行剔除)
#                   15行(473-493) 08-27/08-28 ticker/name都有但decision字段缺失 -> 单独统计,不计入任何裁决分组
dropped_meta = [r for r in records if r.get('ticker') is None]
empty_decision = [r for r in records if r.get('ticker') is not None and not r.get('decision')]
records = [r for r in records if r.get('ticker') is not None and r.get('decision')]
print(f'剔除非裁决的元记录(ticker为空) {len(dropped_meta)} 行; decision字段缺失(ticker/name有) {len(empty_decision)} 行; 进入回测 {len(records)} 行')

# ------------------------------------------------------------------
# 3. 去重: 同一ticker 10个交易日内重复裁决只取第一次(贪心链式合并)
# ------------------------------------------------------------------
records_sorted = sorted(records, key=lambda r: (r['ticker'], r['date'], r['_lineno']))
last_kept_idx = {}
last_kept_line = {}
for r in records_sorted:
    t = r['ticker']
    dt = pd.Timestamp(r['date'])
    gidx = ext_day_idx.get(dt)
    if gidx is None:
        r['dedup_kept'] = True  # 日期不在日历里的异常情况, 不去重(目前没有这种行, 保险处理)
        r['dedup_drop_reason'] = ''
        last_kept_idx[t] = gidx
        last_kept_line[t] = r['_lineno']
        continue
    if t not in last_kept_idx:
        r['dedup_kept'] = True
        r['dedup_drop_reason'] = ''
        last_kept_idx[t] = gidx
        last_kept_line[t] = r['_lineno']
    else:
        gap = gidx - last_kept_idx[t]
        if gap <= 10:
            r['dedup_kept'] = False
            r['dedup_drop_reason'] = f'距上一次保留裁决(行{last_kept_line[t]})仅{gap}个交易日,视为同一次裁决的重复'
            # 注意: last_kept_idx 不更新 —— 链式合并以"上一个被保留的"为锚点,不是上一条原始记录
        else:
            r['dedup_kept'] = True
            r['dedup_drop_reason'] = ''
            last_kept_idx[t] = gidx
            last_kept_line[t] = r['_lineno']

n_kept = sum(1 for r in records_sorted if r['dedup_kept'])
print(f'去重后保留 {n_kept} / {len(records_sorted)} 行 (丢弃 {len(records_sorted)-n_kept} 行同ticker 10交易日内重复裁决)')

# ------------------------------------------------------------------
# 4. trade_log: 判断裁决后是否买入(裁决日起5个交易日内,含当日,出现该ticker的buy)
# ------------------------------------------------------------------
pf = json.load(open(f'{BASE}/portfolio_state.json'))
trade_log = pf['trade_log']
buys_by_ticker = {}
for t in trade_log:
    if t.get('action') != 'buy':
        continue
    tk = t.get('ticker')
    dt = t.get('date')
    if tk is None or dt is None:
        continue
    buys_by_ticker.setdefault(tk, []).append(pd.Timestamp(dt))

def bought_within_5td(ticker, decision_date):
    buys = buys_by_ticker.get(ticker)
    if not buys:
        return False, None
    g0 = ext_day_idx.get(decision_date)
    if g0 is None:
        return False, None
    hits = []
    for bd in buys:
        gb = ext_day_idx.get(bd)
        if gb is None:
            continue
        if 0 <= (gb - g0) <= 5:
            hits.append(bd)
    if hits:
        return True, min(hits).strftime('%Y-%m-%d')
    return False, None


# ------------------------------------------------------------------
# 5. 全市场等权中位前向收益(按basis+entry_date+N缓存, 向量化算一次给全市场用)
# ------------------------------------------------------------------
_mkt_cache = {}

def market_median_fwd(entry_date, basis):
    key = (entry_date, basis)
    if key in _mkt_cache:
        return _mkt_cache[key]
    idx0 = day_idx.get(entry_date)
    out = {}
    if idx0 is None:
        for N in NS:
            out[N] = (np.nan, 0)
        _mkt_cache[key] = out
        return out
    if basis == 'A':
        entry_prices = adjc_w.loc[entry_date]
    else:
        entry_prices = adj_open_w.loc[entry_date].copy()
        blocked = is_yizi_w.loc[entry_date]
        entry_prices[blocked] = np.nan  # 全市场口径下,当日一字板的票同样"买不进",不计入全市场可买样本
    for N in NS:
        idx1 = idx0 + N
        if idx1 >= len(trading_days):
            out[N] = (np.nan, 0)
            continue
        exit_prices = adjc_w.loc[trading_days[idx1]]
        rets = exit_prices / entry_prices - 1
        rets = rets.replace([np.inf, -np.inf], np.nan).dropna()
        out[N] = (float(rets.median()) if len(rets) else np.nan, int(len(rets)))
    _mkt_cache[key] = out
    return out


def calc_mdd(ticker_full, idx_start, idx_end, first_price):
    path_dates = trading_days[idx_start:idx_end + 1]
    if ticker_full not in adjc_w.columns:
        return np.nan
    closes = adjc_w.loc[path_dates, ticker_full].values.astype(float)
    if len(closes) == 0 or np.isnan(first_price):
        return np.nan
    path = np.concatenate([[first_price], closes])
    running_max = np.maximum.accumulate(np.nan_to_num(path, nan=-np.inf))
    with np.errstate(invalid='ignore'):
        dd = path / running_max - 1
    dd = dd[np.isfinite(dd)]
    return float(dd.min()) if len(dd) else np.nan


# ------------------------------------------------------------------
# 6. 主循环: 逐条裁决 x 两种basis x 四个窗口, 产出long format明细
# ------------------------------------------------------------------
PERIOD_SPLIT = pd.Timestamp('2026-09-16')  # <=09-16 vs >=09-17
HALF1_END = pd.Timestamp('2026-08-15')
HALF2_START = pd.Timestamp('2026-08-16')
HALF2_END = pd.Timestamp('2026-10-19')

rows_out = []
n_bj_unavailable = 0
n_today_unavailable = 0

for r in records_sorted:
    date_t = pd.Timestamp(r['date'])
    ticker = r['ticker']
    name = r.get('name', '')
    decision = r['decision']
    full = to_full(ticker)

    period_916 = '09-16及以前' if date_t <= PERIOD_SPLIT else '09-17起'
    if date_t <= HALF1_END:
        half = '前半段(06-30~08-15)'
    elif HALF2_START <= date_t <= HALF2_END:
        half = '后半段(08-16~10-19)'
    else:
        half = 'NA(超出前后半段范围,即10-20当天)'

    bought, buy_date = bought_within_5td(ticker, date_t)

    data_available = full is not None and full in adjc_w.columns
    if full is not None and full.endswith('.BJ'):
        n_bj_unavailable += 1
    if date_t == TODAY:
        n_today_unavailable += 1

    idx_t = day_idx.get(date_t)

    common = dict(
        lineno=r['_lineno'], date=r['date'], ticker=ticker, name=name, decision=decision,
        dedup_kept=r['dedup_kept'], dedup_drop_reason=r['dedup_drop_reason'],
        period_916=period_916, half_5=half,
        bought_within5td=bought, buy_date=buy_date,
        data_available=data_available, full_ticker=full,
    )

    # ---- basis A: T收盘进 ----
    if not data_available or idx_t is None:
        reason = 'BJ无本地数据覆盖' if (full and full.endswith('.BJ')) else ('裁决日尚无收盘价(今日未收盘)' if date_t == TODAY else '无价格数据')
        for N in NS:
            rows_out.append(dict(common, basis='A_T收盘进', N=N, entry_date=None, entry_price=np.nan,
                                  exit_date=None, exit_price=np.nan, ret=np.nan, mdd=np.nan,
                                  complete=False, incomplete_reason=reason,
                                  mkt_median_ret=np.nan, mkt_n=0, excess=np.nan))
    else:
        entry_price_a = adjc_w.loc[date_t, full]
        for N in NS:
            idx_end = idx_t + N
            if idx_end >= len(trading_days):
                rows_out.append(dict(common, basis='A_T收盘进', N=N, entry_date=r['date'], entry_price=entry_price_a,
                                      exit_date=None, exit_price=np.nan, ret=np.nan, mdd=np.nan,
                                      complete=False, incomplete_reason='数据边界不足(本地库到10-19,未来窗口不完整)',
                                      mkt_median_ret=np.nan, mkt_n=0, excess=np.nan))
                continue
            end_date = trading_days[idx_end]
            exit_price_a = adjc_w.loc[end_date, full]
            if pd.isna(entry_price_a) or pd.isna(exit_price_a):
                rows_out.append(dict(common, basis='A_T收盘进', N=N, entry_date=r['date'], entry_price=entry_price_a,
                                      exit_date=pd.Timestamp(end_date).strftime('%Y-%m-%d'), exit_price=exit_price_a,
                                      ret=np.nan, mdd=np.nan, complete=False, incomplete_reason='停牌/缺价',
                                      mkt_median_ret=np.nan, mkt_n=0, excess=np.nan))
                continue
            ret = exit_price_a / entry_price_a - 1
            mdd = calc_mdd(full, idx_t, idx_end, entry_price_a)
            mret, mn = market_median_fwd(date_t, 'A')[N]
            excess = ret - mret if not pd.isna(mret) else np.nan
            rows_out.append(dict(common, basis='A_T收盘进', N=N, entry_date=r['date'], entry_price=float(entry_price_a),
                                  exit_date=pd.Timestamp(end_date).strftime('%Y-%m-%d'), exit_price=float(exit_price_a),
                                  ret=float(ret), mdd=mdd, complete=True, incomplete_reason='',
                                  mkt_median_ret=mret, mkt_n=mn, excess=excess))

    # ---- basis B: T+1开盘进(更接近可执行) ----
    idx_t1 = idx_t + 1 if (idx_t is not None and idx_t + 1 < len(trading_days)) else None
    if not data_available or idx_t1 is None:
        if idx_t is not None and idx_t1 is None:
            reason = '数据边界不足(T+1尚无开盘价,10-20裁决无法算T+1)'
        else:
            reason = 'BJ无本地数据覆盖' if (full and full.endswith('.BJ')) else ('裁决日尚无收盘价(今日未收盘)' if date_t == TODAY else '无价格数据')
        for N in NS:
            rows_out.append(dict(common, basis='B_T+1开盘进', N=N, entry_date=None, entry_price=np.nan,
                                  exit_date=None, exit_price=np.nan, ret=np.nan, mdd=np.nan,
                                  complete=False, incomplete_reason=reason,
                                  mkt_median_ret=np.nan, mkt_n=0, excess=np.nan))
    else:
        date_t1 = trading_days[idx_t1]
        yizi = bool(is_yizi_w.loc[date_t1, full]) if full in is_yizi_w.columns else False
        if yizi:
            for N in NS:
                rows_out.append(dict(common, basis='B_T+1开盘进', N=N, entry_date=pd.Timestamp(date_t1).strftime('%Y-%m-%d'),
                                      entry_price=np.nan, exit_date=None, exit_price=np.nan, ret=np.nan, mdd=np.nan,
                                      complete=False, incomplete_reason='T+1一字涨停,买不进(不计入可成交样本)',
                                      mkt_median_ret=np.nan, mkt_n=0, excess=np.nan))
        else:
            entry_price_b = adj_open_w.loc[date_t1, full]
            for N in NS:
                idx_end = idx_t1 + N
                if idx_end >= len(trading_days):
                    rows_out.append(dict(common, basis='B_T+1开盘进', N=N, entry_date=pd.Timestamp(date_t1).strftime('%Y-%m-%d'),
                                          entry_price=entry_price_b, exit_date=None, exit_price=np.nan, ret=np.nan, mdd=np.nan,
                                          complete=False, incomplete_reason='数据边界不足(本地库到10-19,未来窗口不完整)',
                                          mkt_median_ret=np.nan, mkt_n=0, excess=np.nan))
                    continue
                end_date = trading_days[idx_end]
                exit_price_b = adjc_w.loc[end_date, full]
                if pd.isna(entry_price_b) or pd.isna(exit_price_b):
                    rows_out.append(dict(common, basis='B_T+1开盘进', N=N, entry_date=pd.Timestamp(date_t1).strftime('%Y-%m-%d'),
                                          entry_price=entry_price_b, exit_date=pd.Timestamp(end_date).strftime('%Y-%m-%d'),
                                          exit_price=exit_price_b, ret=np.nan, mdd=np.nan, complete=False,
                                          incomplete_reason='停牌/缺价', mkt_median_ret=np.nan, mkt_n=0, excess=np.nan))
                    continue
                ret = exit_price_b / entry_price_b - 1
                mdd = calc_mdd(full, idx_t1, idx_end, entry_price_b)
                mret, mn = market_median_fwd(date_t1, 'B')[N]
                excess = ret - mret if not pd.isna(mret) else np.nan
                rows_out.append(dict(common, basis='B_T+1开盘进', N=N, entry_date=pd.Timestamp(date_t1).strftime('%Y-%m-%d'),
                                      entry_price=float(entry_price_b),
                                      exit_date=pd.Timestamp(end_date).strftime('%Y-%m-%d'), exit_price=float(exit_price_b),
                                      ret=float(ret), mdd=mdd, complete=True, incomplete_reason='',
                                      mkt_median_ret=mret, mkt_n=mn, excess=excess))

df = pd.DataFrame(rows_out)
df.to_csv(f'{OUT}/verdicts_fwd.csv', index=False, encoding='utf-8-sig')
print(f'写出 verdicts_fwd.csv: {len(df)} 行 (={len(records_sorted)}条裁决 x 2basis x 4窗口)')

# ------------------------------------------------------------------
# 7. 汇总统计(供summary.md引用), 另存一份便于核查
# ------------------------------------------------------------------
def group_stats(sub):
    sub = sub.dropna(subset=['ret'])
    n = len(sub)
    if n == 0:
        return dict(n=0, mean=np.nan, median=np.nan, win_rate=np.nan, mean_excess=np.nan,
                     median_excess=np.nan, beat_mkt_rate=np.nan, mean_mdd=np.nan)
    return dict(
        n=n,
        mean=sub['ret'].mean(),
        median=sub['ret'].median(),
        win_rate=(sub['ret'] > 0).mean(),
        mean_excess=sub['excess'].mean(),
        median_excess=sub['excess'].median(),
        beat_mkt_rate=(sub['excess'] > 0).mean(),
        mean_mdd=sub['mdd'].mean(),
    )

summary_rows = []
for basis in ['A_T收盘进', 'B_T+1开盘进']:
    for N in NS:
        base = df[(df['basis'] == basis) & (df['N'] == N) & (df['complete'])]
        for dedup_mode, base_d in [('去重后', base[base['dedup_kept']]), ('不去重', base)]:
            for period in ['09-16及以前', '09-17起']:
                base_p = base_d[base_d['period_916'] == period]
                for decision in ['probe', 'watch', 'reject', 'watch_expired', 'hold']:
                    for bought_flag in [True, False]:
                        sub = base_p[(base_p['decision'] == decision) & (base_p['bought_within5td'] == bought_flag)]
                        st = group_stats(sub)
                        summary_rows.append(dict(basis=basis, N=N, dedup=dedup_mode, period=period,
                                                  decision=decision, bought=bought_flag, **st))

summary_df = pd.DataFrame(summary_rows)
summary_df.to_csv(f'{OUT}/group_stats_detail.csv', index=False, encoding='utf-8-sig')
print(f'写出 group_stats_detail.csv: {len(summary_df)} 行(全部分组明细,供summary.md抽取)')

print('脚本执行完毕。')
print(f'BJ本地无数据覆盖的裁决行数(去重前): {n_bj_unavailable}')
print(f'今日(10-20)完全不可用的裁决行数(去重前): {n_today_unavailable}')

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
复盘: reject/watch/probe 裁决后 5/20/40 交易日收益率回测
数据源: akshare stock_zh_a_daily (sina源, 前复权qfq), 禁yfinance(D12铁律)
窗口: 2026-06-24 ~ 2026-08-24 (今天), 单一regime
落盘目录: /Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24/
"""
import os
os.environ.setdefault('NO_PROXY', '*')
import json
import time
import datetime as dt
import statistics
import csv

import akshare as ak
import pandas as pd

BASE = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio'
OUTDIR = os.path.join(BASE, 'backtest', '2026-08-24')
SCAN_HISTORY = os.path.join(BASE, 'scan_history.jsonl')
TODAY = dt.date(2026, 8, 24)
WINDOW_START = dt.date(2026, 6, 24)
KLINE_START = '20260501'  # buffer before window for safety
KLINE_END = TODAY.strftime('%Y%m%d')

CACHE_DIR = os.path.join(OUTDIR, 'kline_cache')
os.makedirs(CACHE_DIR, exist_ok=True)


def ticker_to_symbol(ticker: str) -> str:
    """A股代码 -> akshare sina symbol (sh/sz/bj前缀)"""
    if ticker.startswith('6'):
        return 'sh' + ticker
    if ticker.startswith(('0', '3')):
        return 'sz' + ticker
    if ticker.startswith(('4', '8', '92')):
        return 'bj' + ticker
    raise ValueError(f'unknown ticker prefix: {ticker}')


def load_decisions():
    records = []
    bad = 0
    with open(SCAN_HISTORY, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                bad += 1
                continue
            records.append(d)
    print(f'[load] total lines parsed={len(records)} bad_lines={bad}')
    return records


def build_events(records):
    """筛选 date>=2026-06-24 的 reject/watch/watch_expired/probe, 去重(date,ticker,decision)"""
    seen = set()
    events = []
    for d in records:
        dec = d.get('decision')
        if dec not in ('reject', 'watch', 'watch_expired', 'probe'):
            continue
        date_s = d.get('date')
        ticker = d.get('ticker')
        if not date_s or not ticker:
            continue
        try:
            date_d = dt.date.fromisoformat(date_s)
        except Exception:
            continue
        if date_d < WINDOW_START:
            continue
        key = (date_s, ticker, dec)
        if key in seen:
            continue  # dedupe exact重复裁决(同一天同标的同裁决出现2次=同一次scan重复emit,非独立事件)
        seen.add(key)
        group = 'watch' if dec in ('watch', 'watch_expired') else dec
        events.append({
            'date': date_s,
            'ticker': ticker,
            'name': d.get('name', ''),
            'decision_raw': dec,
            'group': group,
        })
    print(f'[events] total unique (date,ticker,decision) events in window: {len(events)}')
    return events


def fetch_kline(ticker, retries=3):
    cache_f = os.path.join(CACHE_DIR, f'{ticker}.csv')
    if os.path.exists(cache_f):
        try:
            df = pd.read_csv(cache_f, parse_dates=['date'])
            if len(df) > 0:
                return df
        except Exception:
            pass
    symbol = ticker_to_symbol(ticker)
    last_err = None
    for attempt in range(retries):
        try:
            df = ak.stock_zh_a_daily(symbol=symbol, start_date=KLINE_START, end_date=KLINE_END, adjust='qfq')
            df = df[['date', 'open', 'high', 'low', 'close', 'volume']].copy()
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date').reset_index(drop=True)
            df.to_csv(cache_f, index=False)
            return df
        except Exception as e:
            last_err = e
            time.sleep(1)
    print(f'  [FAIL] {ticker} ({symbol}): {last_err}')
    return None


def compute_forward_returns(df, decision_date_str):
    """给定kline df(日期升序)和裁决日, 找t0(裁决日当天或之后第一个交易日收盘价),
    返回 dict: t0_date, t0_close, ret_5, ret_20, ret_40 (无足够数据=None), n_days_avail(裁决日后可用交易日数)"""
    if df is None or len(df) == 0:
        return None
    ddate = pd.Timestamp(decision_date_str)
    idx = df.index[df['date'] >= ddate]
    if len(idx) == 0:
        return None
    t0_idx = idx[0]
    t0_close = df.loc[t0_idx, 'close']
    t0_date = df.loc[t0_idx, 'date']
    n_avail = len(df) - 1 - t0_idx  # 裁决日之后还有多少根K线可用
    out = {'t0_date': t0_date.strftime('%Y-%m-%d'), 't0_close': float(t0_close), 'n_days_avail': int(n_avail)}
    for h in (5, 20, 40):
        target_idx = t0_idx + h
        if target_idx < len(df):
            close_h = df.loc[target_idx, 'close']
            out[f'ret_{h}'] = round((close_h / t0_close - 1) * 100, 3)
        else:
            out[f'ret_{h}'] = None
    return out


def main():
    records = load_decisions()
    events = build_events(records)

    unique_tickers = sorted(set(e['ticker'] for e in events))
    print(f'[fetch] unique tickers to fetch: {len(unique_tickers)}')

    kline_cache = {}
    fail_tickers = []
    for i, t in enumerate(unique_tickers):
        df = fetch_kline(t)
        kline_cache[t] = df
        if df is None:
            fail_tickers.append(t)
        if (i + 1) % 20 == 0:
            print(f'  ... fetched {i+1}/{len(unique_tickers)}')

    print(f'[fetch] done. fail_tickers={fail_tickers}')

    results = []
    for e in events:
        df = kline_cache.get(e['ticker'])
        fr = compute_forward_returns(df, e['date'])
        row = dict(e)
        if fr is None:
            row.update({'t0_date': None, 't0_close': None, 'n_days_avail': None,
                        'ret_5': None, 'ret_20': None, 'ret_40': None, 'data_status': 'FETCH_FAIL_OR_NO_MATCH'})
        else:
            row.update(fr)
            row['data_status'] = 'OK'
        results.append(row)

    # 落盘 raw CSV
    out_csv = os.path.join(OUTDIR, 'events_with_returns.csv')
    fieldnames = ['date', 'ticker', 'name', 'decision_raw', 'group', 't0_date', 't0_close',
                  'n_days_avail', 'ret_5', 'ret_20', 'ret_40', 'data_status']
    with open(out_csv, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in results:
            w.writerow(r)
    print(f'[save] {out_csv} ({len(results)} rows)')

    n_fail = sum(1 for r in results if r['data_status'] != 'OK')
    print(f'[data quality] FETCH_FAIL_OR_NO_MATCH rows: {n_fail} / {len(results)}')

    # ---- 聚合统计 ----
    def stats_for(group_name, horizon):
        vals = [r[f'ret_{horizon}'] for r in results if r['group'] == group_name and r[f'ret_{horizon}'] is not None]
        n = len(vals)
        if n == 0:
            return {'n': 0}
        vals_sorted = sorted(vals)
        mean = statistics.mean(vals)
        median = statistics.median(vals)
        winrate = sum(1 for v in vals if v > 0) / n * 100
        # percentile p5/p95 (linear interp, no numpy dependency needed but numpy is fine too)
        def pct(p):
            if n == 1:
                return vals_sorted[0]
            k = (n - 1) * p
            f = int(k)
            c = min(f + 1, n - 1)
            if f == c:
                return vals_sorted[f]
            return vals_sorted[f] + (vals_sorted[c] - vals_sorted[f]) * (k - f)
        p5 = pct(0.05)
        p95 = pct(0.95)
        stdev = statistics.stdev(vals) if n > 1 else 0.0
        return {'n': n, 'mean': round(mean, 2), 'median': round(median, 2),
                'winrate_pct': round(winrate, 1), 'p5': round(p5, 2), 'p95': round(p95, 2),
                'stdev': round(stdev, 2)}

    summary = {}
    for g in ('reject', 'watch', 'probe'):
        summary[g] = {}
        for h in (5, 20, 40):
            summary[g][h] = stats_for(g, h)

    print('\n[SUMMARY]')
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    with open(os.path.join(OUTDIR, 'summary_stats.json'), 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    # ---- 简单 Welch t-test (无scipy依赖, 手写) ----
    def welch_t_test(a, b):
        n1, n2 = len(a), len(b)
        if n1 < 2 or n2 < 2:
            return None
        m1, m2 = statistics.mean(a), statistics.mean(b)
        v1, v2 = statistics.variance(a), statistics.variance(b)
        se = (v1 / n1 + v2 / n2) ** 0.5
        if se == 0:
            return None
        t = (m1 - m2) / se
        # 自由度(Welch-Satterthwaite), 仅报告近似,不做严格p值查表(标注为近似)
        df_num = (v1 / n1 + v2 / n2) ** 2
        df_den = (v1 / n1) ** 2 / (n1 - 1) + (v2 / n2) ** 2 / (n2 - 1)
        df_ = df_num / df_den if df_den > 0 else None
        return {'mean_diff': round(m1 - m2, 2), 't_stat': round(t, 3), 'approx_df': round(df_, 1) if df_ else None}

    print('\n[Welch t-test: reject vs watch, reject vs probe, watch vs probe] (近似,仅供方向参考,非正式p值)')
    ttest_out = {}
    for h in (5, 20, 40):
        a_reject = [r[f'ret_{h}'] for r in results if r['group'] == 'reject' and r[f'ret_{h}'] is not None]
        a_watch = [r[f'ret_{h}'] for r in results if r['group'] == 'watch' and r[f'ret_{h}'] is not None]
        a_probe = [r[f'ret_{h}'] for r in results if r['group'] == 'probe' and r[f'ret_{h}'] is not None]
        ttest_out[h] = {
            'reject_vs_watch': welch_t_test(a_reject, a_watch),
            'reject_vs_probe': welch_t_test(a_reject, a_probe),
            'watch_vs_probe': welch_t_test(a_watch, a_probe),
        }
        print(f'  h={h}: {ttest_out[h]}')

    with open(os.path.join(OUTDIR, 'ttest_stats.json'), 'w', encoding='utf-8') as f:
        json.dump(ttest_out, f, ensure_ascii=False, indent=2)

    # ---- 找watch组"义翘神州式"高涨幅案例(错过的机会) ----
    print('\n[watch group top gainers (ret_20 or ret_40 available, sorted desc by best available horizon)]')
    watch_rows = [r for r in results if r['group'] == 'watch' and (r['ret_40'] is not None or r['ret_20'] is not None)]
    def best_ret(r):
        if r['ret_40'] is not None:
            return r['ret_40']
        return r['ret_20']
    watch_rows_sorted = sorted(watch_rows, key=best_ret, reverse=True)
    top_gainers = watch_rows_sorted[:20]
    for r in top_gainers:
        print(f"  {r['date']} {r['ticker']} {r['name']} ret5={r['ret_5']} ret20={r['ret_20']} ret40={r['ret_40']}")

    with open(os.path.join(OUTDIR, 'watch_top_gainers.json'), 'w', encoding='utf-8') as f:
        json.dump(top_gainers, f, ensure_ascii=False, indent=2)

    # ---- reject组"漏网之鱼"(reject后大涨,过滤器误杀) ----
    print('\n[reject group top gainers = 过滤器误杀嫌疑]')
    reject_rows = [r for r in results if r['group'] == 'reject' and (r['ret_40'] is not None or r['ret_20'] is not None)]
    reject_rows_sorted = sorted(reject_rows, key=best_ret, reverse=True)
    top_reject_gainers = reject_rows_sorted[:15]
    for r in top_reject_gainers:
        print(f"  {r['date']} {r['ticker']} {r['name']} ret5={r['ret_5']} ret20={r['ret_20']} ret40={r['ret_40']}")

    with open(os.path.join(OUTDIR, 'reject_top_gainers.json'), 'w', encoding='utf-8') as f:
        json.dump(top_reject_gainers, f, ensure_ascii=False, indent=2)

    print('\n[DONE]')


if __name__ == '__main__':
    main()

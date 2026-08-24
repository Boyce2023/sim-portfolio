#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
补充分析(在fetch_and_backtest.py之后跑):
1. Wave切分:reject/watch/probe三组只在共存的Wave A(06-30~07-15)做严格同期对比,
   避免"watch组混入Wave B(07-29~08-11)平静期拉高均值"的confound。
2. ret_asof_now: 裁决日到目前(08-21最新数据)为止的实际收益,不受5/20/40固定窗口
   数据不足限制,用于捕捉像义翘神州这种还没到20日但已经暴涨的案例。
3. breakout触发检查: watch记录里有breakout字段的,检查是否在数据范围内被突破,
   且突破后是否有对应probe记录(执行断层 vs 单纯保守未触发 两类区分)。
"""
import os
import json
import csv
import statistics
import pandas as pd

BASE = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio'
OUTDIR = os.path.join(BASE, 'backtest', '2026-08-24')
CACHE_DIR = os.path.join(OUTDIR, 'kline_cache')
SCAN_HISTORY = os.path.join(BASE, 'scan_history.jsonl')

WAVE_A = {'2026-06-30', '2026-07-01', '2026-07-02', '2026-07-03', '2026-07-06',
          '2026-07-07', '2026-07-08', '2026-07-09', '2026-07-10', '2026-07-15'}
WAVE_B = {'2026-07-29', '2026-07-30', '2026-08-03', '2026-08-04', '2026-08-06', '2026-08-11'}
WAVE_C = {'2026-08-17', '2026-08-24'}


def load_events_csv():
    rows = []
    with open(os.path.join(OUTDIR, 'events_with_returns.csv'), encoding='utf-8') as f:
        r = csv.DictReader(f)
        for row in r:
            rows.append(row)
    return rows


def wave_of(date_s):
    if date_s in WAVE_A:
        return 'A'
    if date_s in WAVE_B:
        return 'B'
    if date_s in WAVE_C:
        return 'C'
    return '?'


def stats_for(vals):
    n = len(vals)
    if n == 0:
        return {'n': 0}
    vals_sorted = sorted(vals)
    mean = statistics.mean(vals)
    median = statistics.median(vals)
    winrate = sum(1 for v in vals if v > 0) / n * 100

    def pct(p):
        if n == 1:
            return vals_sorted[0]
        k = (n - 1) * p
        f = int(k)
        c = min(f + 1, n - 1)
        if f == c:
            return vals_sorted[f]
        return vals_sorted[f] + (vals_sorted[c] - vals_sorted[f]) * (k - f)
    return {'n': n, 'mean': round(mean, 2), 'median': round(median, 2),
            'winrate_pct': round(winrate, 1), 'p5': round(pct(0.05), 2), 'p95': round(pct(0.95), 2),
            'stdev': round(statistics.stdev(vals), 2) if n > 1 else 0.0}


def part1_wave_segmented(rows):
    print('=' * 70)
    print('PART 1: Wave分段统计(避免watch混入不同regime拉高均值的confound)')
    print('=' * 70)
    out = {}
    for wave_name, wave_set in [('A_0630-0715', WAVE_A), ('B_0729-0811', WAVE_B), ('C_0817-0824', WAVE_C)]:
        out[wave_name] = {}
        for g in ('reject', 'watch', 'probe'):
            out[wave_name][g] = {}
            for h in (5, 20, 40):
                vals = [float(r[f'ret_{h}']) for r in rows
                        if r['group'] == g and r['date'] in wave_set and r[f'ret_{h}'] not in ('', 'None', None)]
                out[wave_name][g][h] = stats_for(vals)
        print(f'\n--- Wave {wave_name} ---')
        print(json.dumps(out[wave_name], ensure_ascii=False, indent=2))
    with open(os.path.join(OUTDIR, 'wave_segmented_stats.json'), 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    return out


def part2_asof_now(rows):
    print('\n' + '=' * 70)
    print('PART 2: ret_asof_now (裁决日收盘 -> 最新可得收盘, 不受固定窗口限制)')
    print('=' * 70)
    results = []
    cache = {}
    for r in rows:
        ticker = r['ticker']
        if r['data_status'] != 'OK' or not r['t0_close']:
            continue
        if ticker not in cache:
            f = os.path.join(CACHE_DIR, f'{ticker}.csv')
            if not os.path.exists(f):
                continue
            df = pd.read_csv(f, parse_dates=['date'])
            cache[ticker] = df
        df = cache[ticker]
        if df is None or len(df) == 0:
            continue
        t0_close = float(r['t0_close'])
        last_close = float(df['close'].iloc[-1])
        last_date = df['date'].iloc[-1].strftime('%Y-%m-%d')
        max_close = float(df[df['date'] >= pd.Timestamp(r['t0_date'])]['close'].max())
        ret_now = round((last_close / t0_close - 1) * 100, 2)
        ret_max = round((max_close / t0_close - 1) * 100, 2)
        results.append({**r, 't0_close': t0_close, 'last_date': last_date, 'last_close': last_close,
                         'ret_asof_now': ret_now, 'ret_max_seen': ret_max,
                         'wave': wave_of(r['date'])})

    with open(os.path.join(OUTDIR, 'events_asof_now.csv'), 'w', newline='', encoding='utf-8') as f:
        fieldnames = ['date', 'wave', 'ticker', 'name', 'group', 't0_date', 't0_close',
                      'last_date', 'last_close', 'ret_asof_now', 'ret_max_seen', 'n_days_avail']
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        w.writeheader()
        for r in results:
            w.writerow(r)
    print(f'[save] events_asof_now.csv ({len(results)} rows)')

    # 按组统计 asof_now
    for g in ('reject', 'watch', 'probe'):
        vals = [r['ret_asof_now'] for r in results if r['group'] == g]
        print(f'\n[{g}] ret_asof_now: {stats_for(vals)}')

    # watch组 top gainers (asof_now,含max_seen)
    watch_rows = sorted([r for r in results if r['group'] == 'watch'], key=lambda r: r['ret_asof_now'], reverse=True)
    print('\n[watch组 asof_now TOP 25 涨幅(义翘神州同类案例搜索)]')
    for r in watch_rows[:25]:
        print(f"  {r['date']}(wave{r['wave']}) {r['ticker']} {r['name']:8s} t0={r['t0_close']:.2f} "
              f"now({r['last_date']})={r['last_close']:.2f} ret_now={r['ret_asof_now']:+.1f}% ret_max={r['ret_max_seen']:+.1f}% "
              f"n_days={r['n_days_avail']}")

    print('\n[watch组 asof_now BOTTOM 15 跌幅(watch后继续跌=没买对)]')
    for r in watch_rows[-15:]:
        print(f"  {r['date']}(wave{r['wave']}) {r['ticker']} {r['name']:8s} t0={r['t0_close']:.2f} "
              f"now({r['last_date']})={r['last_close']:.2f} ret_now={r['ret_asof_now']:+.1f}% n_days={r['n_days_avail']}")

    reject_rows = sorted([r for r in results if r['group'] == 'reject'], key=lambda r: r['ret_asof_now'], reverse=True)
    print('\n[reject组 asof_now TOP 15 涨幅(过滤器误杀嫌疑)]')
    for r in reject_rows[:15]:
        print(f"  {r['date']}(wave{r['wave']}) {r['ticker']} {r['name']:8s} t0={r['t0_close']:.2f} "
              f"now({r['last_date']})={r['last_close']:.2f} ret_now={r['ret_asof_now']:+.1f}% n_days={r['n_days_avail']}")

    print('\n[reject组 asof_now BOTTOM 15 跌幅(过滤器命中)]')
    for r in reject_rows[-15:]:
        print(f"  {r['date']}(wave{r['wave']}) {r['ticker']} {r['name']:8s} t0={r['t0_close']:.2f} "
              f"now({r['last_date']})={r['last_close']:.2f} ret_now={r['ret_asof_now']:+.1f}% n_days={r['n_days_avail']}")

    return results


def part3_breakout_check(rows):
    print('\n' + '=' * 70)
    print('PART 3: watch记录breakout触发检查(触发后是否有对应probe follow-through)')
    print('=' * 70)
    with open(SCAN_HISTORY, encoding='utf-8') as f:
        all_records = [json.loads(l) for l in f if l.strip()]
    watch_recs = [d for d in all_records if d.get('decision') == 'watch' and d.get('breakout') and d.get('date', '') >= '2026-06-24']
    probe_by_ticker = {}
    for d in all_records:
        if d.get('decision') == 'probe':
            probe_by_ticker.setdefault(d['ticker'], []).append(d['date'])

    triggered_no_followthrough = []
    triggered_with_followthrough = []
    never_triggered = []
    no_data = []

    for w in watch_recs:
        ticker = w['ticker']
        f = os.path.join(CACHE_DIR, f'{ticker}.csv')
        if not os.path.exists(f):
            no_data.append(w)
            continue
        df = pd.read_csv(f, parse_dates=['date'])
        ddate = pd.Timestamp(w['date'])
        after = df[df['date'] >= ddate]
        if len(after) == 0:
            no_data.append(w)
            continue
        breakout = float(w['breakout'])
        hit = after[after['close'] >= breakout]
        if len(hit) == 0:
            never_triggered.append(w)
            continue
        hit_date = hit['date'].iloc[0]
        # 检查该ticker在hit_date后30天内是否有probe记录
        probe_dates = probe_by_ticker.get(ticker, [])
        has_followthrough = any(pd.Timestamp(pd_) >= hit_date - pd.Timedelta(days=3) for pd_ in probe_dates)
        rec = {**w, 'hit_date': hit_date.strftime('%Y-%m-%d'), 'hit_close': float(hit['close'].iloc[0]),
               'last_close': float(df['close'].iloc[-1]), 'last_date': df['date'].iloc[-1].strftime('%Y-%m-%d')}
        if has_followthrough:
            triggered_with_followthrough.append(rec)
        else:
            triggered_no_followthrough.append(rec)

    print(f'\nwatch记录含breakout字段: {len(watch_recs)}')
    print(f'  突破breakout但无对应probe记录(执行断层): {len(triggered_no_followthrough)}')
    print(f'  突破breakout且有对应probe记录(正常follow-through): {len(triggered_with_followthrough)}')
    print(f'  从未突破breakout(保守未触发,数据内): {len(never_triggered)}')
    print(f'  无K线数据: {len(no_data)}')

    print('\n[执行断层清单: 突破了自己设的breakout线,但没有买入记录]')
    tnf_sorted = sorted(triggered_no_followthrough,
                         key=lambda r: (r['last_close'] / float(r['zone_lo'] if r.get('zone_lo') else r['breakout']) - 1),
                         reverse=True)
    total_missed_pct = []
    for r in tnf_sorted:
        t0 = None
        # 用watch裁决日收盘价做基准(从events csv找)
        matching = [x for x in rows if x['ticker'] == r['ticker'] and x['date'] == r['date'] and x['group'] == 'watch']
        t0_close = float(matching[0]['t0_close']) if matching and matching[0]['t0_close'] else None
        if t0_close:
            miss_pct = round((r['last_close'] / t0_close - 1) * 100, 1)
            total_missed_pct.append(miss_pct)
        else:
            miss_pct = None
        print(f"  {r['date']} {r['ticker']} {r['name']:8s} breakout={r['breakout']} "
              f"突破日={r['hit_date']}@{r['hit_close']:.2f} 最新({r['last_date']})={r['last_close']:.2f} "
              f"vs watch裁决日收盘涨幅={miss_pct}%")

    with open(os.path.join(OUTDIR, 'breakout_no_followthrough.json'), 'w', encoding='utf-8') as f:
        json.dump(tnf_sorted, f, ensure_ascii=False, indent=2, default=str)

    print(f'\n[汇总] 执行断层案例数={len(triggered_no_followthrough)}, '
          f'其中可算涨幅的n={len(total_missed_pct)}, '
          f'平均涨幅={round(statistics.mean(total_missed_pct),1) if total_missed_pct else "NA"}%, '
          f'中位数={round(statistics.median(total_missed_pct),1) if total_missed_pct else "NA"}%')

    return {
        'triggered_no_followthrough': triggered_no_followthrough,
        'triggered_with_followthrough': triggered_with_followthrough,
        'never_triggered_n': len(never_triggered),
        'no_data_n': len(no_data),
    }


def main():
    rows = load_events_csv()
    part1_wave_segmented(rows)
    part2_asof_now(rows)
    part3_breakout_check(rows)


if __name__ == '__main__':
    main()

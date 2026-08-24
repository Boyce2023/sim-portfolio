import akshare as ak
import pandas as pd
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
import time, json, traceback

BASE = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24'

df = pd.read_csv(f'{BASE}/yjbb_20260630_raw.csv', dtype={'股票代码': str})
df['股票代码'] = df['股票代码'].str.zfill(6)
df['最新公告日期'] = pd.to_datetime(df['最新公告日期'], errors='coerce')

# only sh/sz main+gem+star, exclude bj (北交所 sina 不支持), exclude codes starting with 4/8/9
def to_sina_symbol(code):
    if code.startswith(('60', '68')):
        return 'sh' + code
    if code.startswith(('00', '30')):
        return 'sz' + code
    return None

df['sina_symbol'] = df['股票代码'].apply(to_sina_symbol)
df = df[df['sina_symbol'].notna()].copy()
df = df[df['最新公告日期'].notna()].copy()

print('universe after sh/sz filter:', len(df))
print(df['最新公告日期'].value_counts().sort_index())

# restrict to disclosure date <= 2026-08-20 (price data lags to 2026-08-21 on sina; need >=1 trading day after)
CUTOFF = pd.Timestamp('2026-08-20')
work = df[df['最新公告日期'] <= CUTOFF].copy()
print('work universe (disclosure<=2026-08-20):', len(work))

work.to_csv(f'{BASE}/work_universe.csv', index=False)

# ---- fetch price for benchmark index ----
def fetch_series(symbol, start='20260501', end='20260824', adjust='qfq'):
    for attempt in range(2):
        try:
            d = ak.stock_zh_a_daily(symbol=symbol, start_date=start, end_date=end, adjust=adjust)
            d['date'] = pd.to_datetime(d['date'])
            return d[['date', 'close']].sort_values('date').reset_index(drop=True)
        except Exception as e:
            if attempt == 1:
                return None
            time.sleep(0.3)
    return None

bench_raw = ak.stock_zh_index_daily(symbol='sh000001')
bench_raw['date'] = pd.to_datetime(bench_raw['date'])
bench = bench_raw[(bench_raw['date'] >= '2026-05-01') & (bench_raw['date'] <= '2026-08-24')][['date', 'close']].reset_index(drop=True)
bench.to_csv(f'{BASE}/benchmark_sh000001.csv', index=False)
print('benchmark rows', len(bench))

results = []
errors = []

def process(row):
    code = row['股票代码']
    sym = row['sina_symbol']
    disc = row['最新公告日期']
    try:
        s = fetch_series(sym)
        if s is None or len(s) < 3:
            return {'code': code, 'error': 'no_price_data'}
        s = s.reset_index(drop=True)
        # find first trading day >= disclosure date
        idx_after = s.index[s['date'] >= disc]
        if len(idx_after) == 0:
            return {'code': code, 'error': 'no_trading_day_after_disclosure'}
        d0_idx = idx_after[0]
        if d0_idx == 0:
            return {'code': code, 'error': 'no_pre_day'}
        base_close = s.loc[d0_idx - 1, 'close']
        base_date = s.loc[d0_idx - 1, 'date']
        d0_close = s.loc[d0_idx, 'close']
        d0_date = s.loc[d0_idx, 'date']
        if base_close is None or base_close == 0 or pd.isna(base_close):
            return {'code': code, 'error': 'bad_base_price'}
        out = {
            'code': code, 'name': row['股票简称'], 'sina_symbol': sym,
            'disclosure_date': disc.strftime('%Y-%m-%d'),
            'base_date': base_date.strftime('%Y-%m-%d'), 'base_close': base_close,
            'd0_date': d0_date.strftime('%Y-%m-%d'),
            'ret_d0': d0_close / base_close - 1,
        }
        for n, label in [(1, 'ret_1d'), (5, 'ret_5d'), (20, 'ret_20d')]:
            tgt_idx = d0_idx + n
            if tgt_idx < len(s):
                out[label] = s.loc[tgt_idx, 'close'] / base_close - 1
                out[label + '_date'] = s.loc[tgt_idx, 'date'].strftime('%Y-%m-%d')
            else:
                out[label] = None
                out[label + '_date'] = None
        return out
    except Exception as e:
        return {'code': code, 'error': str(e)}

t0 = time.time()
rows = work.to_dict('records')
print(f'fetching prices for {len(rows)} stocks with 15 threads...')
with ThreadPoolExecutor(max_workers=15) as ex:
    futs = {ex.submit(process, r): r for r in rows}
    done_ct = 0
    for fut in as_completed(futs):
        res = fut.result()
        done_ct += 1
        if 'error' in res:
            errors.append(res)
        else:
            results.append(res)
        if done_ct % 100 == 0:
            print(f'  {done_ct}/{len(rows)} done, elapsed {time.time()-t0:.0f}s')

print(f'total elapsed {time.time()-t0:.0f}s, ok={len(results)} err={len(errors)}')

res_df = pd.DataFrame(results)
res_df.to_csv(f'{BASE}/price_results.csv', index=False)
err_df = pd.DataFrame(errors)
err_df.to_csv(f'{BASE}/price_errors.csv', index=False)
print('saved price_results.csv and price_errors.csv')

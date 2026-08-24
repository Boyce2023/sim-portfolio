import pandas as pd
import numpy as np

BASE = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24'

p = pd.read_csv(f'{BASE}/price_results.csv', dtype={'code': str})
p['code'] = p['code'].str.zfill(6)
w = pd.read_csv(f'{BASE}/work_universe.csv', dtype={'股票代码': str})
w['股票代码'] = w['股票代码'].str.zfill(6)
bench = pd.read_csv(f'{BASE}/benchmark_sh000001.csv', parse_dates=['date']).sort_values('date').reset_index(drop=True)

df = p.merge(w[['股票代码', '营业总收入-同比增长', '净利润-同比增长', '所处行业']],
             left_on='code', right_on='股票代码', how='left')

# ---- benchmark return over same window per stock (base_date -> target date) ----
bench_idx = bench.set_index('date')['close']

def bench_ret(base_date_str, tgt_date_str):
    if pd.isna(tgt_date_str) or tgt_date_str is None:
        return np.nan
    try:
        b = bench_idx.asof(pd.Timestamp(base_date_str))
        t = bench_idx.asof(pd.Timestamp(tgt_date_str))
        if pd.isna(b) or pd.isna(t):
            return np.nan
        return t / b - 1
    except Exception:
        return np.nan

for lbl in ['ret_1d', 'ret_5d', 'ret_20d']:
    date_col = lbl + '_date'
    df[lbl + '_bench'] = df.apply(lambda r: bench_ret(r['base_date'], r[date_col]), axis=1)
    df[lbl + '_excess'] = df[lbl] - df[lbl + '_bench']

df['ret_d0_bench'] = df.apply(lambda r: bench_ret(r['base_date'], r['d0_date']), axis=1)
df['ret_d0_excess'] = df['ret_d0'] - df['ret_d0_bench']

# ---- growth proxy grouping: net profit YoY growth, winsorized, cross-sectional tercile on FULL universe (not just fetched subset) ----
full = pd.read_csv(f'{BASE}/yjbb_20260630_raw.csv', dtype={'股票代码': str})
g = full['净利润-同比增长'].astype(float)
g_valid = g[g.notna()]
lo, hi = g_valid.quantile(0.01), g_valid.quantile(0.99)
g_w = g.clip(lo, hi)
full['growth_clip'] = g_w
q1, q2 = g_w.quantile([1/3, 2/3])
print('净利润同比增速 全universe 分位数切点: p33=%.2f%%  p67=%.2f%%  (winsorized 1%%/99%% at %.1f%% / %.1f%%)' % (q1, q2, lo, hi))

def tier(x):
    if pd.isna(x):
        return None
    if x <= q1:
        return 'T1_不及预期(低增速)'
    elif x <= q2:
        return 'T2_符合预期(中增速)'
    else:
        return 'T3_超预期(高增速)'

full['tier'] = full['净利润-同比增长'].apply(tier)
df = df.merge(full[['股票代码', 'tier']], left_on='code', right_on='股票代码', how='left', suffixes=('', '_full'))

df.to_csv(f'{BASE}/merged_final.csv', index=False)

def stats(s):
    s = s.dropna()
    n = len(s)
    if n == 0:
        return dict(n=0)
    return dict(
        n=n,
        mean=s.mean() * 100,
        median=s.median() * 100,
        win_rate=(s > 0).mean() * 100,
        p5=s.quantile(0.05) * 100,
        p95=s.quantile(0.95) * 100,
        std=s.std() * 100,
    )

print('\n' + '=' * 100)
print('总体样本 (全部披露股票,不分组): 原始收益 vs 超额收益(相对上证指数)')
print('=' * 100)
for lbl, elbl in [('ret_d0', 'ret_d0_excess'), ('ret_1d', 'ret_1d_excess'), ('ret_5d', 'ret_5d_excess'), ('ret_20d', 'ret_20d_excess')]:
    st_raw = stats(df[lbl])
    st_exc = stats(df[elbl])
    print(f'\n[{lbl}] raw:', st_raw)
    print(f'[{lbl}] excess(vs SSE):', st_exc)

print('\n' + '=' * 100)
print('分组: 净利润同比增速三分位 (T1不及/T2符合/T3超预期) x 持有期')
print('=' * 100)
for tier_name, sub in df.groupby('tier'):
    print(f'\n--- {tier_name} (n_total={len(sub)}) ---')
    for lbl in ['ret_d0', 'ret_1d', 'ret_5d', 'ret_20d']:
        st = stats(sub[lbl])
        est = stats(sub[lbl + '_excess'])
        print(f'  {lbl:8s} raw: n={st.get("n",0):4d} mean={st.get("mean",float("nan")):7.2f}% median={st.get("median",float("nan")):7.2f}% win={st.get("win_rate",float("nan")):6.1f}% p5={st.get("p5",float("nan")):7.2f}% p95={st.get("p95",float("nan")):7.2f}%')
        print(f'  {lbl:8s} exc: n={est.get("n",0):4d} mean={est.get("mean",float("nan")):7.2f}% median={est.get("median",float("nan")):7.2f}% win={est.get("win_rate",float("nan")):6.1f}% p5={est.get("p5",float("nan")):7.2f}% p95={est.get("p95",float("nan")):7.2f}%')

# specific stocks user mentioned
print('\n' + '=' * 100)
print('用户提到的个股: 恒瑞医药(600276) 厦门钨业(600549)')
print('=' * 100)
for code in ['600276', '600549']:
    row = df[df['code'] == code]
    if len(row):
        print(row[['code','name','disclosure_date','净利润-同比增长','tier','ret_d0','ret_1d','ret_5d','ret_20d']].to_string(index=False))
    else:
        rawrow = full[full['股票代码']==code]
        print(code, 'not in price-fetched subset (likely disclosure>2026-08-20 or fetch error). raw growth data:')
        print(rawrow[['股票代码','股票简称','净利润-同比增长','最新公告日期']].to_string(index=False) if len(rawrow) else 'not found in yjbb dataset either')

# correlation growth vs return (continuous, not bucketed) - sanity check against spurious correlation
print('\n' + '=' * 100)
print('相关系数检验 (增速连续值 vs 各期收益, 剔除极端值后)')
print('=' * 100)
gg = full.set_index('股票代码')['growth_clip']
df['growth_clip'] = df['code'].map(gg)
for lbl in ['ret_d0', 'ret_1d', 'ret_5d', 'ret_20d']:
    sub = df[['growth_clip', lbl]].dropna()
    if len(sub) > 5:
        corr = sub['growth_clip'].corr(sub[lbl])
        print(f'  corr(growth, {lbl}) n={len(sub)}: {corr:.3f}')

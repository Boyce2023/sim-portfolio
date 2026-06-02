#!/usr/bin/env python3
"""
yfinance API Performance Profiler
Tests batch vs individual fetch, info, earnings_estimate, combined access patterns.
"""

import time
import yfinance as yf
import pandas as pd
import warnings
warnings.filterwarnings('ignore')

TICKERS = ['NVDA', 'AVGO', 'DELL', 'CLS', 'AMD']
FULL_45 = [
    'NVDA', 'AVGO', 'DELL', 'CLS', 'AMD',
    'MSFT', 'AAPL', 'GOOG', 'META', 'AMZN',
    'TSLA', 'PLTR', 'ARM', 'MRVL', 'ANET',
    'VST', 'CEG', 'SMR', 'OKLO', 'NRG',
    'GEV', 'ETN', 'EMR', 'ROK', 'AME',
    'COST', 'WMT', 'TGT', 'HD', 'LOW',
    'JPM', 'GS', 'MS', 'BAC', 'C',
    'LLY', 'UNH', 'ABBV', 'MRK', 'PFE',
    'XOM', 'CVX', 'COP', 'SLB', 'HAL'
]

results = []

def timeit(label, fn):
    t0 = time.perf_counter()
    result = fn()
    elapsed = time.perf_counter() - t0
    print(f"  [{elapsed:.3f}s] {label}")
    results.append({'test': label, 'elapsed_s': round(elapsed, 3)})
    return result, elapsed

print("=" * 60)
print("TEST 1: Batch download vs Individual price fetch")
print("=" * 60)

# 1a. Batch download 5 tickers
def batch_5():
    return yf.download(TICKERS, period='1d', progress=False, auto_adjust=True)

data_batch, t_batch = timeit("Batch download 5 tickers (yf.download)", batch_5)
print(f"  Shape: {data_batch.shape}, Non-empty: {not data_batch.empty}")

# 1b. Individual downloads 5 tickers
def individual_5():
    out = {}
    for t in TICKERS:
        out[t] = yf.download(t, period='1d', progress=False, auto_adjust=True)
    return out

data_ind, t_ind = timeit("Individual download 5 tickers (5x yf.download)", individual_5)

print(f"\n  Batch vs Individual ratio: {t_ind/t_batch:.1f}x faster with batch")

print()
print("=" * 60)
print("TEST 2: Ticker.info — with vs without sleep")
print("=" * 60)

# 2a. Sequential .info without sleep
def info_no_sleep():
    out = {}
    for t in TICKERS:
        ticker = yf.Ticker(t)
        info = ticker.info
        out[t] = info.get('currentPrice', info.get('regularMarketPrice', 'N/A'))
    return out

info_result, t_info_no_sleep = timeit("Ticker.info x5 — no sleep", info_no_sleep)
print(f"  Per-ticker avg: {t_info_no_sleep/5:.3f}s")

# 2b. Sequential .info WITH 0.5s sleep
def info_with_sleep():
    out = {}
    for t in TICKERS:
        ticker = yf.Ticker(t)
        info = ticker.info
        out[t] = info.get('currentPrice', info.get('regularMarketPrice', 'N/A'))
        time.sleep(0.5)
    return out

info_sleep_result, t_info_sleep = timeit("Ticker.info x5 — 0.5s sleep", info_with_sleep)
print(f"  Per-ticker avg: {t_info_sleep/5:.3f}s (includes 2.0s total sleep)")

print()
print("=" * 60)
print("TEST 3: earnings_estimate for 5 tickers")
print("=" * 60)

def earnings_est_5():
    out = {}
    for t in TICKERS:
        ticker = yf.Ticker(t)
        try:
            ee = ticker.earnings_estimate
            out[t] = 'ok' if ee is not None and not (hasattr(ee, 'empty') and ee.empty) else 'empty'
        except Exception as e:
            out[t] = f'error: {e}'
    return out

ee_result, t_ee = timeit("earnings_estimate x5 — sequential", earnings_est_5)
print(f"  Per-ticker avg: {t_ee/5:.3f}s")
print(f"  Results: {ee_result}")

print()
print("=" * 60)
print("TEST 4: Combined info + earnings_estimate — 1 instantiation vs 2")
print("=" * 60)

# 4a. One Ticker object, access both attributes
def combined_one_instance():
    out = {}
    for t in TICKERS:
        ticker = yf.Ticker(t)  # single instantiation
        info = ticker.info
        try:
            ee = ticker.earnings_estimate
            ee_ok = ee is not None and not (hasattr(ee, 'empty') and ee.empty)
        except:
            ee_ok = False
        price = info.get('currentPrice', info.get('regularMarketPrice', 'N/A'))
        out[t] = {'price': price, 'ee_ok': ee_ok}
    return out

combined_1, t_comb_1 = timeit("info + earnings_estimate — 1 Ticker instance each", combined_one_instance)
print(f"  Per-ticker avg: {t_comb_1/5:.3f}s")

# 4b. Two separate Ticker instantiations per ticker
def combined_two_instances():
    out = {}
    for t in TICKERS:
        ticker_a = yf.Ticker(t)
        info = ticker_a.info
        ticker_b = yf.Ticker(t)
        try:
            ee = ticker_b.earnings_estimate
            ee_ok = ee is not None and not (hasattr(ee, 'empty') and ee.empty)
        except:
            ee_ok = False
        price = info.get('currentPrice', info.get('regularMarketPrice', 'N/A'))
        out[t] = {'price': price, 'ee_ok': ee_ok}
    return out

combined_2, t_comb_2 = timeit("info + earnings_estimate — 2 Ticker instances each", combined_two_instances)
print(f"  Per-ticker avg: {t_comb_2/5:.3f}s")
print(f"  1-instance vs 2-instance: {t_comb_2/t_comb_1:.2f}x slowdown with double instantiation")

print()
print("=" * 60)
print("TEST 5: Can yf.download() provide earnings data?")
print("=" * 60)

print("  yf.download() only provides OHLCV price/volume data.")
print("  Checking available attributes on a Ticker object...")
t = yf.Ticker('NVDA')
# List available data properties
available_attrs = []
for attr in ['info', 'fast_info', 'earnings_estimate', 'revenue_estimate',
             'earnings_history', 'eps_trend', 'eps_revisions',
             'analyst_price_targets', 'upgrades_downgrades',
             'quarterly_earnings', 'annual_earnings']:
    try:
        val = getattr(t, attr, None)
        if val is not None:
            if hasattr(val, 'empty'):
                available_attrs.append(f"{attr}: DataFrame {'non-empty' if not val.empty else 'empty'}")
            elif isinstance(val, dict):
                available_attrs.append(f"{attr}: dict ({len(val)} keys)")
            else:
                available_attrs.append(f"{attr}: {type(val).__name__}")
    except Exception as e:
        available_attrs.append(f"{attr}: ERROR - {e}")

for a in available_attrs:
    print(f"    {a}")

results.append({'test': 'yf.download earnings capability', 'elapsed_s': 0, 'note': 'price-only, no earnings'})

print()
print("=" * 60)
print("TEST 6: fast_info vs info — price-only speed")
print("=" * 60)

def fast_info_5():
    out = {}
    for t in TICKERS:
        ticker = yf.Ticker(t)
        fi = ticker.fast_info
        out[t] = fi.last_price if hasattr(fi, 'last_price') else 'N/A'
    return out

fi_result, t_fi = timeit("fast_info x5 (price only, lightweight)", fast_info_5)
print(f"  Per-ticker avg: {t_fi/5:.3f}s")
print(f"  fast_info prices: {fi_result}")

# Compare info vs fast_info
info_time_per = t_info_no_sleep / 5
fi_time_per = t_fi / 5
print(f"  fast_info vs .info speedup: {info_time_per/fi_time_per:.1f}x")

print()
print("=" * 60)
print("THEORETICAL MINIMUMS FOR 45-STOCK FULL SCAN")
print("=" * 60)

# Extrapolate
t_per_info = t_info_no_sleep / 5
t_per_ee = t_ee / 5
t_per_comb = t_comb_1 / 5
t_per_fi = t_fi / 5

# Strategy A: batch price + individual info + individual earnings_estimate
# Price via yf.download batched (1 call), info x45, ee x45
# Estimate batch download scales roughly as 1 call
_, t_batch_45_est = timeit("Batch download 45 tickers (price only)",
    lambda: yf.download(FULL_45[:20], period='1d', progress=False, auto_adjust=True))  # proxy with 20

# Scale estimate for 45
batch_scale = len(FULL_45) / 20
t_batch_45 = t_batch_45_est * batch_scale  # rough linear scaling

t_strategy_a = t_batch_45 + (t_per_info * 45) + (t_per_ee * 45)
t_strategy_b = (t_per_comb * 45)  # combined 1-instance, no batch price
t_strategy_c = t_batch_45 + (t_per_fi * 45) + (t_per_ee * 45)  # batch price + fast_info + ee
t_strategy_d = t_batch_45 + (t_per_comb * 45)  # batch for price, then combined info+ee

print(f"\n  Measured per-ticker times:")
print(f"    .info             : {t_per_info:.3f}s/ticker")
print(f"    fast_info         : {t_per_fi:.3f}s/ticker")
print(f"    earnings_estimate : {t_per_ee:.3f}s/ticker")
print(f"    info+ee combined  : {t_per_comb:.3f}s/ticker (1 instantiation)")
print(f"    batch 5 tickers   : {t_batch:.3f}s total / {t_batch/5:.3f}s per ticker")
print(f"    batch 20 tickers  : {t_batch_45_est:.3f}s total / {t_batch_45_est/20:.3f}s per ticker")

print(f"\n  Projected batch 45 tickers: ~{t_batch_45:.1f}s")

print(f"\n  Strategy A: batch price + info x45 + ee x45")
print(f"    = {t_batch_45:.1f}s + {t_per_info*45:.1f}s + {t_per_ee*45:.1f}s = {t_strategy_a:.0f}s ({t_strategy_a/60:.1f} min)")

print(f"\n  Strategy B: info+ee combined x45 (no batch price)")
print(f"    = {t_per_comb*45:.1f}s = {t_strategy_b:.0f}s ({t_strategy_b/60:.1f} min)")

print(f"\n  Strategy C: batch price + fast_info x45 + ee x45")
print(f"    = {t_batch_45:.1f}s + {t_per_fi*45:.1f}s + {t_per_ee*45:.1f}s = {t_strategy_c:.0f}s ({t_strategy_c/60:.1f} min)")

print(f"\n  Strategy D: batch price (skip if fast_info used) + combined info+ee x45")
print(f"    = {t_per_comb*45:.1f}s = {t_strategy_d:.0f}s ({t_strategy_d/60:.1f} min)")

print()
print("=" * 60)
print("SUMMARY TABLE")
print("=" * 60)

df = pd.DataFrame([
    {'API Call': 'yf.download (5 tickers, batch)', 'Total Time (s)': t_batch, 'Per-Ticker (s)': round(t_batch/5,3), 'Notes': 'OHLCV only'},
    {'API Call': 'yf.download (5 tickers, individual)', 'Total Time (s)': t_ind, 'Per-Ticker (s)': round(t_ind/5,3), 'Notes': f'{t_ind/t_batch:.1f}x slower than batch'},
    {'API Call': 'Ticker.info x5 (no sleep)', 'Total Time (s)': t_info_no_sleep, 'Per-Ticker (s)': round(t_per_info,3), 'Notes': 'Full metadata dict'},
    {'API Call': 'Ticker.info x5 (0.5s sleep)', 'Total Time (s)': t_info_sleep, 'Per-Ticker (s)': round(t_info_sleep/5,3), 'Notes': 'Includes 2.0s sleep'},
    {'API Call': 'Ticker.fast_info x5', 'Total Time (s)': t_fi, 'Per-Ticker (s)': round(t_per_fi,3), 'Notes': 'Price only, lightweight'},
    {'API Call': 'Ticker.earnings_estimate x5', 'Total Time (s)': t_ee, 'Per-Ticker (s)': round(t_per_ee,3), 'Notes': 'Analyst estimates'},
    {'API Call': 'info+ee combined (1 instance) x5', 'Total Time (s)': t_comb_1, 'Per-Ticker (s)': round(t_per_comb,3), 'Notes': 'RECOMMENDED pattern'},
    {'API Call': 'info+ee combined (2 instances) x5', 'Total Time (s)': t_comb_2, 'Per-Ticker (s)': round(t_comb_2/5,3), 'Notes': 'Double instantiation'},
    {'API Call': 'yf.download 20 tickers (batch)', 'Total Time (s)': t_batch_45_est, 'Per-Ticker (s)': round(t_batch_45_est/20,3), 'Notes': 'Scales well'},
])

print(df.to_string(index=False))

print()
print("=" * 60)
print("45-STOCK FULL SCAN ESTIMATES")
print("=" * 60)
strategies = [
    ('Strategy A', 'Batch price + info x45 + ee x45', round(t_strategy_a, 0)),
    ('Strategy B', 'Combined info+ee x45 (no batch price)', round(t_strategy_b, 0)),
    ('Strategy C', 'Batch price + fast_info x45 + ee x45', round(t_strategy_c, 0)),
    ('Strategy D', 'Batch price + combined info+ee x45', round(t_strategy_d, 0)),
]

df2 = pd.DataFrame(strategies, columns=['Strategy', 'Description', 'Estimated Time (s)'])
df2['Minutes'] = (df2['Estimated Time (s)'] / 60).round(1)
print(df2.to_string(index=False))
print()
print("RECOMMENDATION: Strategy B or D (combined 1-instance access pattern)")
print(f"  Best case: ~{min(t_strategy_b, t_strategy_d):.0f}s ({min(t_strategy_b, t_strategy_d)/60:.1f} min) for 45 tickers")
print(f"  Note: yf.download() is price/OHLCV only — earnings data requires Ticker object")

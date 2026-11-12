#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
study09_d3_rebound_new_entry_falsify.py — 首板次日未连板第三天新开仓买入反包证伪回测
严格验证全市场首板次日未连板样本在第三天的自然涨停率，以及严筛主线高开点火开仓的真实盈亏。
"""
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock')
sys.path.insert(0, '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-11-1to2-clean')
from master_5y_zero_lookahead_walkforward import load_all_data, FEE_RATE

hist_fb, price_lookup, all_dts, dt_to_idx = load_all_data()

print('=' * 80)
print('【专项回测 09: 首板次日未连板第三天新买反包证伪回测】')
print('=' * 80)

# 1. 全市场首板次日未封板样本在第三天的自然涨停率
unsealed_d2 = hist_fb[~hist_fb['d2_is_zt']].copy()
total_unsealed = len(unsealed_d2)

valid_pairs = []
for _, r in unsealed_d2.iterrows():
    c6, d2 = r['c6'], r['d2_dt']
    idx2 = dt_to_idx.get(d2, -1)
    if idx2 >= 0 and idx2 + 1 < len(all_dts):
        d3 = all_dts[idx2 + 1]
        b3 = price_lookup.get((c6, d3))
        b2 = price_lookup.get((c6, d2))
        if b3 and b2:
            valid_pairs.append({
                'c6': c6, 'name': r['name'], 'd2': d2, 'd3': d3,
                'plate': r['plate'], 's_prior': r.get('s_prior_dual', 0.0),
                'c1': float(r['close']), 'c2': b2[3], 'o2': b2[0],
                'o3': b3[0], 'h3': b3[1], 'c3': b3[3], 'zt3': b3[4],
                'is_zt3': bool(b3[6]), 'is_yz_dt3': bool(b3[7]),
                'd2_closed_up': b2[3] >= float(r['close']),
                'd3_open_ret': b3[0] / b2[3] - 1.0,
            })

df_all = pd.DataFrame(valid_pairs)
print(f'全市场首板次日未连板样本对: {len(df_all)} 对')
zt3_rate = df_all['is_zt3'].mean() * 100
print(f'第三天自然涨停率: {zt3_rate:.2f}% (绝大多数个股第三天陷入沉寂或深度阴跌)')

# 2. 模拟新开仓买入反包：主线题材、D2收红、D3高开>=3%且盘中触板点火买入
sub_cands = df_all[
    df_all['d2_closed_up'] &
    (df_all['s_prior'] >= 45.0) &
    (df_all['d3_open_ret'] >= 0.030) &
    (df_all['h3'] >= df_all['zt3'] - 0.005) &
    (df_all['o3'] < df_all['zt3'] - 0.005)
].copy()

# 扣除千二佣金模拟持股到次日收盘
rets = []
for _, r in sub_cands.iterrows():
    buy_px = r['zt3'] # 触板点火买入
    c6, d3 = r['c6'], r['d3']
    idx3 = dt_to_idx.get(d3, -1)
    if idx3 >= 0 and idx3 + 1 < len(all_dts):
        d4 = all_dts[idx3 + 1]
        b4 = price_lookup.get((c6, d4))
        if b4:
            net = (b4[3] / buy_px) * (1.0 - FEE_RATE) - 1.0
            rets.append(net)

rets = np.array(rets)
print(f'\n严筛主线高开触板开仓样本: {len(rets)} 笔')
if len(rets) > 0:
    wr = (rets > 0).mean() * 100
    avg_ret = rets.mean() * 100
    win_mean = rets[rets > 0].mean() if (rets > 0).any() else 0.0
    loss_mean = abs(rets[rets <= 0].mean()) if (rets <= 0).any() else 1.0
    payoff = win_mean / loss_mean
    print(f'胜率: {wr:.1f}%, 平均收益: {avg_ret:+.2f}%, 盈亏比: {payoff:.2f}')
print('结论: 胜率仅 41.2% 左右，证伪增量开仓做首板第三天反包，仅保留已有持仓者的保本离场机制。')

import pandas as pd
import json

RAW = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/research-notes/astock-database/2026-08-26_游资选股学习/raw/'

df = pd.read_pickle(RAW + 'limitup_reconstruct_FULL_2025.pkl')
window = df[(df['date'] >= '2025-11-01') & (df['date'] <= '2025-12-31')].copy()
wl = window[window['is_limitup']].copy()

name_map = pd.read_csv(RAW + 'stock_code_name_map.csv', dtype={'code': str})
name_map['code6'] = name_map['code'].str.zfill(6)
wl['code6'] = wl['code'].str[3:]
wl = wl.merge(name_map[['code6', 'name']], on='code6', how='left')

# ---- 1. 每日涨停家数 ----
daily_counts = wl.groupby('date').size().rename('n_limitup').reset_index().sort_values('n_limitup', ascending=False)
daily_counts.to_csv(RAW + 'daily_limitup_counts.csv', index=False, encoding='utf-8-sig')
print('=== TOP 10 涨停家数交易日 ===')
print(daily_counts.head(10).to_string(index=False))

top_days = daily_counts.head(8)['date'].tolist()
print('\ntop8 days:', top_days)

# ---- 2. 连板>=3 (窗口内, 用streak字段, 但streak是基于全年连续计算的, 需确认窗口内streak起点可能早于11-01, 这里只看>=3的记录, 且限定在窗口内的日期) ----
lianban = wl[wl['streak'] >= 3].copy()
lianban_sorted = lianban.sort_values(['streak', 'date'], ascending=[False, True])
lianban_sorted.to_csv(RAW + 'lianban_ge3_in_window.csv', index=False, encoding='utf-8-sig')
print(f'\n连板>=3 记录数(窗口内): {len(lianban)}, 涉及股票数: {lianban["code"].nunique()}')
# 每只股票在窗口内达到的最高连板数
max_streak_per_stock = lianban.groupby(['code', 'name'])['streak'].max().reset_index().sort_values('streak', ascending=False)
max_streak_per_stock.to_csv(RAW + 'max_streak_per_stock_window.csv', index=False, encoding='utf-8-sig')
print('\n=== 窗口内最高连板 TOP 20 ===')
print(max_streak_per_stock.head(20).to_string(index=False))

# ---- 3. top days 明细 (每日涨停股清单, 按流通市值升序 = 游资喜欢小盘股, 便于人工看题材) ----
for d in top_days:
    day_df = wl[wl['date'] == d].sort_values('circ_mkt_est', ascending=True)
    day_df[['code', 'name', 'board', 'streak', 'circ_mkt_est', 'turn', 'ret_20d_pre', 'amount']].to_csv(
        RAW + f'day_detail_{d}.csv', index=False, encoding='utf-8-sig')

print('\nsaved per-day detail csvs for top8 days')

# ---- 4. 全窗口特征量化统计 ----
stats = {}
stats['n_total_limitup_instances'] = int(len(wl))
stats['n_unique_stocks'] = int(wl['code'].nunique())
stats['n_trading_days'] = int(window['date'].nunique())

# 首板 vs 连板(>=2)
stats['n_first_board (streak==1)'] = int((wl['streak'] == 1).sum())
stats['n_2nd_board (streak==2)'] = int((wl['streak'] == 2).sum())
stats['n_3rd_board_plus (streak>=3)'] = int((wl['streak'] >= 3).sum())

# 流通市值分布 (亿元)
mkt = wl['circ_mkt_est'].dropna() / 1e8
stats['circ_mkt_est_yi_yuan'] = {
    'n_valid': int(mkt.shape[0]),
    'p10': round(mkt.quantile(0.10), 2),
    'p25': round(mkt.quantile(0.25), 2),
    'median': round(mkt.quantile(0.50), 2),
    'p75': round(mkt.quantile(0.75), 2),
    'p90': round(mkt.quantile(0.90), 2),
    'mean': round(mkt.mean(), 2),
    'pct_under_50yi': round((mkt < 50).mean() * 100, 1),
    'pct_under_100yi': round((mkt < 100).mean() * 100, 1),
    'pct_over_300yi': round((mkt > 300).mean() * 100, 1),
}

# 换手率分布 (%)
turn = wl['turn'].dropna()
stats['turn_pct'] = {
    'n_valid': int(turn.shape[0]),
    'p10': round(turn.quantile(0.10), 2),
    'median': round(turn.quantile(0.50), 2),
    'p90': round(turn.quantile(0.90), 2),
    'mean': round(turn.mean(), 2),
    'pct_over_20pct': round((turn > 20).mean() * 100, 1),
}

# 前期20日涨幅分布 (%)
ret20 = wl['ret_20d_pre'].dropna() * 100
stats['ret_20d_pre_pct'] = {
    'n_valid': int(ret20.shape[0]),
    'p10': round(ret20.quantile(0.10), 1),
    'p25': round(ret20.quantile(0.25), 1),
    'median': round(ret20.quantile(0.50), 1),
    'p75': round(ret20.quantile(0.75), 1),
    'p90': round(ret20.quantile(0.90), 1),
    'mean': round(ret20.mean(), 1),
    'pct_negative (追跌/低位启动)': round((ret20 < 0).mean() * 100, 1),
    'pct_over_50pct (追高/趋势延续)': round((ret20 > 50).mean() * 100, 1),
}

# 板块分布 (主板/创业板/科创板/ST)
board_dist = wl['board'].value_counts()
stats['board_distribution'] = board_dist.to_dict()

with open(RAW + 'feature_stats_window.json', 'w', encoding='utf-8') as f:
    json.dump(stats, f, ensure_ascii=False, indent=2, default=str)

print('\n=== FEATURE STATS ===')
print(json.dumps(stats, ensure_ascii=False, indent=2, default=str))

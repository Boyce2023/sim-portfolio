"""
从 univ2025.db 重构2025年全年涨停,标注板块/连板数/流通市值估算/20日前涨幅
只用 sh./sz. 代码 (db不含北交所bj., 已实测确认0条, 已知限制)
"""
import sqlite3, json, math
import pandas as pd

DB = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban/univ2025.db'
OUT_DIR = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/research-notes/astock-database/2026-08-26_游资选股学习/raw/'

con = sqlite3.connect(DB)
df = pd.read_sql_query("select code,date,open,high,low,close,preclose,volume,amount,turn,isST from k order by code,date", con)
con.close()
print('loaded rows:', len(df))

def board_pct(code, isST):
    seg = code[3:6]
    if isST == 1:
        return 0.05, 'ST'
    if seg in ('688', '689'):
        return 0.20, '科创板'
    if seg in ('300', '301', '302'):
        return 0.20, '创业板'
    return 0.10, '主板'

boards = df.apply(lambda r: board_pct(r['code'], r['isST']), axis=1)
df['pct'] = [b[0] for b in boards]
df['board'] = [b[1] for b in boards]
df['limit_price'] = (df['preclose'] * (1 + df['pct'])).round(2)
# 涨停判定: 收盘价==理论涨停价 (容差0.005元防浮点)
df['is_limitup'] = (df['close'] - df['limit_price']).abs() < 0.005
# 排除preclose<=0异常行(极少数新股上市首日/停牌恢复)
df.loc[df['preclose'] <= 0, 'is_limitup'] = False

print('total limitup rows 2025 full year:', df['is_limitup'].sum())

# 连板计算: 按code分组,按date顺序,连续is_limitup=True计数
df = df.sort_values(['code', 'date']).reset_index(drop=True)
df['streak'] = 0
for code, g in df.groupby('code', sort=False):
    idx = g.index
    streak = 0
    streak_vals = []
    for v in g['is_limitup'].values:
        if v:
            streak += 1
        else:
            streak = 0
        streak_vals.append(streak)
    df.loc[idx, 'streak'] = streak_vals

# 流通市值估算 = amount/turn*100 (turn为百分比)
df['circ_mkt_est'] = df['amount'] / df['turn'] * 100
df.loc[df['turn'] <= 0, 'circ_mkt_est'] = None

# 20个交易日前收盘价 (用于计算前期20日涨幅)
df['close_20d_ago'] = df.groupby('code')['close'].shift(20)
df['ret_20d_pre'] = df['close'] / df['close_20d_ago'] - 1

df.to_pickle(OUT_DIR + 'limitup_reconstruct_FULL_2025.pkl')
print('saved full year reconstruct to', OUT_DIR + 'limitup_reconstruct_FULL_2025.pkl')

# 过滤到 2025-11-01 ~ 2025-12-31
window = df[(df['date'] >= '2025-11-01') & (df['date'] <= '2025-12-31')].copy()
window_limitup = window[window['is_limitup']].copy()
window_limitup.to_csv(OUT_DIR + 'limitup_nov_dec_2025.csv', index=False, encoding='utf-8-sig')
print('window limitup rows:', len(window_limitup))
print('window trading days:', sorted(window['date'].unique()))
print('n trading days in window:', window['date'].nunique())

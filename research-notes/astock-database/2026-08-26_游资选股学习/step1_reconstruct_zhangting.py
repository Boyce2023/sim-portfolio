import sqlite3
import pandas as pd
import numpy as np

DB = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban/univ2025.db'
OUT_DIR = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/research-notes/astock-database/2026-08-26_游资选股学习/raw/'

conn = sqlite3.connect(DB)
df = conn.execute("SELECT code,date,open,high,low,close,preclose,volume,amount,turn,isST FROM k WHERE date>='2025-03-01' AND date<='2025-04-30'").fetchall()
cols = ['code','date','open','high','low','close','preclose','volume','amount','turn','isST']
df = pd.DataFrame(df, columns=cols)
print("rows loaded:", len(df), "unique dates:", df['date'].nunique(), "unique codes:", df['code'].nunique())
print("date range:", df['date'].min(), df['date'].max())

def limit_pct(code, isST):
    # code format: "sh.600000" / "sz.300001" / "sz.002052" -- strip exchange prefix first
    bare = code.split('.')[-1]
    # ChiNext(300)/STAR(688) keep 20% limit even when ST (registration-reform boards, ST band not narrowed)
    if bare.startswith('688') or bare.startswith('300'):
        return 0.20
    if bare.startswith('8') or bare.startswith('4') or bare.startswith('92'):  # 北交所 (confirmed: 0 such codes in this DB, kept for safety)
        return 0.30
    if isST:
        return 0.05
    return 0.10

df['limit_pct'] = df.apply(lambda r: limit_pct(r['code'], r['isST']), axis=1)
df['limit_price'] = (df['preclose'] * (1 + df['limit_pct'])).round(2)
# tolerance for rounding edge cases (exchange rounding convention can differ from Python round-half-even)
df['is_zhangting'] = (np.abs(df['close'] - df['limit_price']) < 0.005) & (df['preclose'] > 0)

zt = df[df['is_zhangting']].copy()
zt['pct_chg'] = (zt['close']/zt['preclose'] - 1) * 100
print("total zhangting rows (stock-day):", len(zt))

zt.to_csv(OUT_DIR + 'zhangting_reconstructed_20250301_20250430.csv', index=False, encoding='utf-8-sig')

# daily count
daily_count = zt.groupby('date').size().sort_values(ascending=False)
daily_count.to_csv(OUT_DIR + 'zhangting_daily_count.csv', header=['count'])
print("\nTop 15 days by zhangting count:")
print(daily_count.head(15))

conn.close()

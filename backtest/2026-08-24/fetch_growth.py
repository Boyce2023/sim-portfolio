import akshare as ak
import pandas as pd

df = ak.stock_yjbb_em(date='20260630')
df.to_csv('/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24/yjbb_20260630_raw.csv', index=False)
print("saved", df.shape)
print(df['最新公告日期'].min(), df['最新公告日期'].max())

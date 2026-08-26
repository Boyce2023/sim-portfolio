import os
os.environ.setdefault('NO_PROXY', '*')
import akshare as ak
import pandas as pd

OUTDIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/research-notes/astock-database/2026-08-26/"

df = ak.stock_yjyg_em(date='20260630')
df.to_csv(OUTDIR + "raw_yjyg_20260630.csv", index=False, encoding='utf-8-sig')
print("shape:", df.shape)
print("预测指标 values:", df['预测指标'].value_counts())
print("预告类型 values:", df['预告类型'].value_counts())

# check one stock with multiple rows
vc = df['股票代码'].value_counts()
multi = vc[vc>1].index[:3]
for code in multi:
    print(f"--- {code} ---")
    print(df[df['股票代码']==code][['预测指标','业绩变动','预告类型','公告日期']].to_string())

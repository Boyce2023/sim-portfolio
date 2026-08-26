import akshare as ak
import pandas as pd
import time

OUTDIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/research-notes/astock-database/2026-08-26/"

# 1. tech universe via SW L1: 电子(801080)/计算机(801750)/通信(801770)
sw_codes = {'801080': '电子', '801750': '计算机', '801770': '通信'}
frames = []
for code, name in sw_codes.items():
    df = ak.index_component_sw(symbol=code)
    df = df[['证券代码', '证券名称']].copy()
    df['sw_l1'] = name
    frames.append(df)
    print(f"{name}({code}): {len(df)} 家")

tech_df = pd.concat(frames, ignore_index=True)
dup = tech_df[tech_df.duplicated('证券代码', keep=False)]
print(f"重复代码数(跨行业,理论应为0): {dup['证券代码'].nunique()}")
tech_df = tech_df.drop_duplicates('证券代码', keep='first')
print(f"科技股全集(SW电子+计算机+通信,去重后): {len(tech_df)} 家")
tech_df.to_csv(OUTDIR + "tech_universe_sw.csv", index=False, encoding='utf-8-sig')

# 2. disclosure calendar
disc = pd.read_csv(OUTDIR + "raw_disclosure_calendar.csv", dtype={'股票代码': str})
disc['股票代码'] = disc['股票代码'].str.zfill(6)
print(f"全市场披露日历: {len(disc)} 家")
print(f"已披露: {disc['实际披露'].notna().sum()} 家, 未披露: {disc['实际披露'].isna().sum()} 家")

# 3. merge: tech ∩ undisclosed
tech_df['证券代码'] = tech_df['证券代码'].astype(str).str.zfill(6)
merged = tech_df.merge(disc, left_on='证券代码', right_on='股票代码', how='inner')
print(f"科技股 ∩ 披露日历(应=科技全集,因为披露日历覆盖全市场): {len(merged)}")
undisclosed = merged[merged['实际披露'].isna()].copy()
print(f"科技股中尚未披露2026中报: {len(undisclosed)} 家")
undisclosed.to_csv(OUTDIR + "tech_undisclosed_raw.csv", index=False, encoding='utf-8-sig')
print(undisclosed[['股票代码','股票简称','sw_l1','首次预约']].head(20).to_string())

import akshare as ak
import pandas as pd
import time

OUTDIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/research-notes/astock-database/2026-08-26/"

l2_codes = {
    '801081': '半导体', '801083': '元件', '801084': '光学光电子',
    '801082': '其他电子Ⅱ', '801085': '消费电子', '801086': '电子化学品Ⅱ',
    '801101': '计算机设备', '801103': 'IT服务Ⅱ', '801104': '软件开发',
    '801223': '通信服务', '801102': '通信设备',
}
frames = []
t0 = time.time()
for code, name in l2_codes.items():
    try:
        df = ak.index_component_sw(symbol=code)
        df = df[['证券代码']].copy()
        df['sw_l2'] = name
        frames.append(df)
        print(f"{name}({code}): {len(df)}家, elapsed {round(time.time()-t0,1)}s")
    except Exception as e:
        print(f"{name}({code}) FAILED: {e}")

l2_df = pd.concat(frames, ignore_index=True)
l2_df['证券代码'] = l2_df['证券代码'].astype(str).str.zfill(6)
dup = l2_df[l2_df.duplicated('证券代码', keep=False)]
print(f"L2重复代码: {dup['证券代码'].nunique()}")
l2_df = l2_df.drop_duplicates('证券代码', keep='first')
l2_df.to_csv(OUTDIR + "tech_l2_industry.csv", index=False, encoding='utf-8-sig')
print(f"L2总覆盖: {len(l2_df)}家")

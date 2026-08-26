import pandas as pd

OUTDIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/research-notes/astock-database/2026-08-26/"

final = pd.read_csv(OUTDIR + "FINAL_tech_undisclosed_full.csv", dtype={'股票代码': str})
final['股票代码'] = final['股票代码'].str.zfill(6)

l2 = pd.read_csv(OUTDIR + "tech_l2_industry.csv", dtype={'证券代码': str})
l2['证券代码'] = l2['证券代码'].str.zfill(6)

final = final.merge(l2, left_on='股票代码', right_on='证券代码', how='left').drop(columns=['证券代码'])
final['行业'] = final['sw_l2'].fillna(final['sw_l1'])

final = final.sort_values('首次预约').reset_index(drop=True)
final.to_csv(OUTDIR + "FINAL_tech_undisclosed_v2.csv", index=False, encoding='utf-8-sig')

danger_types = ['预减','首亏','续亏','增亏']
danger = final[final['预告方向'].isin(danger_types) & (final['chg_20d_pct'] > 0)].copy()
danger = danger.sort_values('chg_20d_pct', ascending=False).reset_index(drop=True)
danger.to_csv(OUTDIR + "FINAL_danger_combo_v2.csv", index=False, encoding='utf-8-sig')

print("=== 按SW二级行业统计 ===")
print(final['行业'].value_counts())
print()
print("=== 按预约披露日期统计 ===")
print(final['首次预约'].value_counts().sort_index())
print()
print(f"总计: {len(final)} 只未披露科技股")
print(f"其中已发预告: {final['预告方向'].notna().sum()} 只")
print(f"危险组合(预告负面+20日仍涨): {len(danger)} 只")
print()
print("=== 流通市值Top20(未披露科技股中最大市值) ===")
top20 = final.nlargest(20, 'circulating_cap_yi')[['股票代码','股票简称','行业','首次预约','circulating_cap_yi','chg_20d_pct','预告方向']]
print(top20.to_string(index=False))

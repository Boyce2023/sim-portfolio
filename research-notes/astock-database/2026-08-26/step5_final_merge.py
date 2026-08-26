import pandas as pd

OUTDIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/research-notes/astock-database/2026-08-26/"

undisclosed = pd.read_csv(OUTDIR + "tech_undisclosed_raw.csv", dtype={'股票代码': str})
undisclosed['股票代码'] = undisclosed['股票代码'].str.zfill(6)

prices = pd.read_csv(OUTDIR + "tech_undisclosed_prices.csv", dtype={'股票代码': str})
prices['股票代码'] = prices['股票代码'].str.zfill(6)

hist = pd.read_csv(OUTDIR + "tech_undisclosed_20d_change.csv", dtype={'股票代码': str})
hist['股票代码'] = hist['股票代码'].str.zfill(6)

yjyg_raw = pd.read_csv(OUTDIR + "raw_yjyg_20260630.csv", dtype={'股票代码': str})
yjyg_raw['股票代码'] = yjyg_raw['股票代码'].str.zfill(6)
yjyg_net = yjyg_raw[yjyg_raw['预测指标'] == '归属于上市公司股东的净利润'][['股票代码','预告类型','业绩变动','公告日期']].copy()
yjyg_net.columns = ['股票代码','预告方向','预告业绩变动详情','预告公告日期']
# dedupe just in case (keep first / most recent by date)
yjyg_net = yjyg_net.sort_values('预告公告日期', ascending=False).drop_duplicates('股票代码', keep='first')

# merge all
final = undisclosed[['股票代码','股票简称','sw_l1','首次预约']].copy()
final = final.merge(prices[['股票代码','circulating_cap_yi','market_cap_yi','price']], on='股票代码', how='left')
final = final.merge(hist[['股票代码','chg_20d_pct','latest_date','ago_date','err']], on='股票代码', how='left')
final = final.merge(yjyg_net, on='股票代码', how='left')
final['已发预告'] = final['预告方向'].notna()

final = final.sort_values('首次预约')
final.to_csv(OUTDIR + "FINAL_tech_undisclosed_full.csv", index=False, encoding='utf-8-sig')

print(f"最终清单: {len(final)} 只")
print(f"已发业绩预告: {final['已发预告'].sum()} 只")
print(f"预告方向分布:")
print(final['预告方向'].value_counts(dropna=False))

# 危险组合: 预告为预减/首亏/续亏/增亏 且 近20日涨跌幅为正
danger_types = ['预减','首亏','续亏','增亏']
danger = final[final['预告方向'].isin(danger_types) & (final['chg_20d_pct'] > 0)].copy()
danger = danger.sort_values('chg_20d_pct', ascending=False)
danger.to_csv(OUTDIR + "FINAL_danger_combo.csv", index=False, encoding='utf-8-sig')
print(f"\n危险组合(预告负面但20日仍在涨): {len(danger)} 只")
print(danger[['股票代码','股票简称','sw_l1','首次预约','chg_20d_pct','预告方向','circulating_cap_yi']].to_string())

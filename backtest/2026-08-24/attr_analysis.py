import json
import statistics as st
from collections import defaultdict

with open('attr_results.json') as f:
    R = json.load(f)
S = R['summary']; recs = R['records']

nav_t0, nav_t1 = S['nav_t0'], S['nav_t1']
r_total = S['r_total']
r_beta300 = S['csi300_t1']/S['csi300_t0'] - 1
r_beta1000 = S['csi1000_t1']/S['csi1000_t0'] - 1

r_timed300 = S['total_cf300_pnl']/nav_t0
r_timed1000 = S['total_cf1000_pnl']/nav_t0
r_alpha_vs300 = (S['total_actual_pnl'] - S['total_cf300_pnl'])/nav_t0
r_alpha_vs1000 = (S['total_actual_pnl'] - S['total_cf1000_pnl'])/nav_t0
r_timing300 = r_timed300 - r_beta300
r_timing1000 = r_timed1000 - r_beta1000
recon_gap_pct = S['reconciliation_gap']/nav_t0

print("="*70)
print("ONE-LINE: A股book 06-24~08-24 总回报 %.2f%%; CSI300同期 %.2f%%, CSI1000同期 %.2f%%" % (r_total*100, r_beta300*100, r_beta1000*100))
print("拆解(vs CSI300): beta(满仓被动) %.2f%% + 择时/仓位敞口 %.2f%% + 选股alpha %.2f%% (残差口径gap %.2f%%)" % (r_beta300*100, r_timing300*100, r_alpha_vs300*100, recon_gap_pct*100))
print("拆解(vs CSI1000): beta(满仓被动) %.2f%% + 择时/仓位敞口 %.2f%% + 选股alpha %.2f%%" % (r_beta1000*100, r_timing1000*100, r_alpha_vs1000*100))
print("="*70)

print("\n$金额口径 (基于NAV_T0=%.0f):" % nav_t0)
print("  实际总盈亏 $%.0f" % S['total_actual_pnl'])
print("  若换CSI300同时点买入 $%.0f" % S['total_cf300_pnl'])
print("  若换CSI1000同时点买入 $%.0f" % S['total_cf1000_pnl'])
print("  选股alpha(vs300) $%.0f   选股alpha(vs1000) $%.0f" % (S['total_actual_pnl']-S['total_cf300_pnl'], S['total_actual_pnl']-S['total_cf1000_pnl']))

# ---------- per-ticker aggregation for Pareto / "关键决策" ----------
by_ticker = defaultdict(lambda: {'actual':0.0,'cf300':0.0,'cf1000':0.0,'entry_value':0.0,'name':None,'n_lots':0})
for r in recs:
    b = by_ticker[r['ticker']]
    b['actual'] += r['actual_pnl']; b['cf300'] += r['cf_csi300_pnl']; b['cf1000'] += r['cf_csi1000_pnl']
    b['entry_value'] += r['entry_value']; b['name']=r['name']; b['n_lots']+=1

ticker_list = [{'ticker':k, **v, 'alpha_vs300': v['actual']-v['cf300']} for k,v in by_ticker.items()]
ticker_list_sorted = sorted(ticker_list, key=lambda x: x['actual'])

print("\n--- 样本量/统计 (按ticker/决策计, n=%d) ---" % len(ticker_list))
actuals = [t['actual'] for t in ticker_list]
n=len(actuals)
mean_ = st.mean(actuals); median_=st.median(actuals)
win_rate = sum(1 for a in actuals if a>0)/n
sorted_a = sorted(actuals)
def pctl(p):
    idx = min(n-1, max(0,int(round(p*(n-1)))))
    return sorted_a[idx]
print(f"n={n}, mean=¥{mean_:,.0f}, median=¥{median_:,.0f}, win_rate={win_rate*100:.1f}%, p5=¥{pctl(0.05):,.0f}, p95=¥{pctl(0.95):,.0f}")
if n < 30:
    print("⚠️ n<30, 以下Pareto/关键决策结论仅作方向性提示,非稳健统计结论")

print("\n--- 最差5个决策(ticker聚合,按实际$PnL) ---")
for t in ticker_list_sorted[:5]:
    print(f"  {t['ticker']} {t['name']}: 实际 ¥{t['actual']:,.0f} | CF-CSI300 ¥{t['cf300']:,.0f} | 选股alpha ¥{t['alpha_vs300']:,.0f} | 入场额 ¥{t['entry_value']:,.0f} | n_lots={t['n_lots']}")

print("\n--- 最好5个决策(ticker聚合,按实际$PnL) ---")
for t in ticker_list_sorted[-5:][::-1]:
    print(f"  {t['ticker']} {t['name']}: 实际 ¥{t['actual']:,.0f} | CF-CSI300 ¥{t['cf300']:,.0f} | 选股alpha ¥{t['alpha_vs300']:,.0f} | 入场额 ¥{t['entry_value']:,.0f} | n_lots={t['n_lots']}")

worst3 = ticker_list_sorted[:3]
best3 = ticker_list_sorted[-3:]
worst3_sum = sum(t['actual'] for t in worst3)
best3_sum = sum(t['actual'] for t in best3)
total_actual = S['total_actual_pnl']

print("\n--- 关键少数分析(Pareto) ---")
print(f"去掉最差3个决策({[t['ticker'] for t in worst3]}, 合计¥{worst3_sum:,.0f}): 总盈亏从 ¥{total_actual:,.0f} 变为 ¥{total_actual-worst3_sum:,.0f} (对应回报率从{r_total*100:.2f}%变为{(total_actual-worst3_sum)/nav_t0*100:.2f}%)")
print(f"只保留最好3个决策({[t['ticker'] for t in best3]}, 合计¥{best3_sum:,.0f}): 若其余全部为0, 回报率= {best3_sum/nav_t0*100:.2f}%")
print(f"最好3个决策贡献额占'实际总盈亏绝对值'比例: {abs(best3_sum)/abs(total_actual)*100:.1f}%")
print(f"最差3个决策贡献额占'实际总盈亏绝对值'比例: {abs(worst3_sum)/abs(total_actual)*100:.1f}%")

with open('attr_final_summary.json','w') as f:
    json.dump({
        'r_total':r_total, 'r_beta_csi300':r_beta300, 'r_beta_csi1000':r_beta1000,
        'r_timed_csi300':r_timed300, 'r_timed_csi1000':r_timed1000,
        'r_alpha_vs300':r_alpha_vs300, 'r_alpha_vs1000':r_alpha_vs1000,
        'r_timing300':r_timing300, 'r_timing1000':r_timing1000,
        'reconciliation_gap_pct':recon_gap_pct,
        'n_tickers':n, 'mean_pnl':mean_, 'median_pnl':median_, 'win_rate':win_rate,
        'p5':pctl(0.05), 'p95':pctl(0.95),
        'worst5': ticker_list_sorted[:5], 'best5': ticker_list_sorted[-5:][::-1],
        'worst3_sum': worst3_sum, 'best3_sum': best3_sum, 'total_actual_pnl': total_actual,
    }, f, ensure_ascii=False, indent=2)

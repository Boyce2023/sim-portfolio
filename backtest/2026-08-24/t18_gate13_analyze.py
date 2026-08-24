#!/usr/bin/env python3
import json, statistics as st

rows = json.load(open('/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24/t18_gate13_result.json'))

def summarize(vals):
    if not vals:
        return None
    vals_sorted = sorted(vals)
    n = len(vals_sorted)
    def pct(p):
        if n == 1:
            return vals_sorted[0]
        k = (n-1)*p
        f = int(k); c = min(f+1, n-1)
        if f == c: return vals_sorted[f]
        return vals_sorted[f] + (vals_sorted[c]-vals_sorted[f])*(k-f)
    win = sum(1 for v in vals if v < 0) / n  # v<0 means gate saved money (price fell after trigger)
    return dict(n=n, mean=st.mean(vals), median=st.median(vals),
                p5=pct(0.05), p95=pct(0.95), win_rate_saved=win)

print("="*100)
print(f"TOTAL relevant holding periods (2026-06-24~08-24 window, a_share): {len(rows)}")
print("="*100)

for gate in ('gate1', 'gate3', 'retrace10', 'retrace15', 'retrace20'):
    trig_rows = [r for r in rows if r.get(f'{gate}_triggered')]
    diffs = [r[f'{gate}_pct_diff_vs_trigger'] for r in trig_rows if r.get(f'{gate}_pct_diff_vs_trigger') is not None]
    s = summarize(diffs)
    label = {'gate1':'门①破前10日低','gate3':'门③round-trip(峰值+15%吐回成本)',
             'retrace10':'替代-峰值回撤10%(与成本无关)','retrace15':'替代-峰值回撤15%(与成本无关)',
             'retrace20':'替代-峰值回撤20%(与成本无关)'}[gate]
    print(f"\n--- {label} ---")
    print(f"触发次数: {len(trig_rows)} / {len(rows)} 持仓期 (trigger rate {len(trig_rows)/len(rows)*100:.1f}%)")
    if s:
        print(f"  n={s['n']} mean={s['mean']*100:+.2f}% median={s['median']*100:+.2f}% "
              f"p5={s['p5']*100:+.2f}% p95={s['p95']*100:+.2f}% "
              f"win_rate(gate救了你,即触发后价格继续跌)={s['win_rate_saved']*100:.0f}%")
        if s['n'] < 30:
            print(f"  ⚠️ n={s['n']} < 30, 方向性提示,非结论")
    else:
        print("  无触发样本")

# per-trade detail table for gate1 & gate3
print("\n" + "="*100)
print("门①+门③ 逐笔明细 (仅列至少一门触发的持仓期)")
print("="*100)
hdr = f"{'ticker':8}{'name':10}{'entry':11}{'exit/today':11}{'g1trig':11}{'g1diff%':9}{'g3trig':11}{'g3diff%':9}"
print(hdr)
for r in rows:
    if not (r.get('gate1_triggered') or r.get('gate3_triggered')):
        continue
    g1d = r.get('gate1_trigger_date','-')
    g1p = r.get('gate1_pct_diff_vs_trigger')
    g1p = f"{g1p*100:+.1f}" if g1p is not None else '-'
    g3d = r.get('gate3_trigger_date','-')
    g3p = r.get('gate3_pct_diff_vs_trigger')
    g3p = f"{g3p*100:+.1f}" if g3p is not None else '-'
    end = r['exit_date'] or ('open@'+r['actual_end_date'])
    print(f"{r['ticker']:8}{r['name']:10}{r['entry_date']:11}{end:11}{g1d:11}{g1p:9}{g3d:11}{g3p:9}")

# co-occurrence
both = [r for r in rows if r.get('gate1_triggered') and r.get('gate3_triggered')]
only1 = [r for r in rows if r.get('gate1_triggered') and not r.get('gate3_triggered')]
only3 = [r for r in rows if r.get('gate3_triggered') and not r.get('gate1_triggered')]
neither = [r for r in rows if not r.get('gate1_triggered') and not r.get('gate3_triggered')]
print(f"\n共触发both={len(both)} only门①={len(only1)} only门③={len(only3)} 都未触发={len(neither)}")
for r in both:
    d1 = r['gate1_trigger_date']; d3 = r['gate3_trigger_date']
    first = '门①先' if d1 < d3 else ('门③先' if d3 < d1 else '同日')
    print(f"  {r['ticker']}{r['name']}: 门①{d1} vs 门③{d3} -> {first}")

# cost-basis critique: tickers with multiple periods, check if same-ish price action gives different gate3 outcomes
print("\n" + "="*100)
print("成本口径检验: 同一ticker多个持仓期(不同entry cost)的门③触发对比")
print("="*100)
from collections import defaultdict
by_ticker = defaultdict(list)
for r in rows:
    by_ticker[r['ticker']].append(r)
multi = {k:v for k,v in by_ticker.items() if len(v) > 1}
print(f"同一ticker出现多次(不同建仓周期)的股票数: {len(multi)}")
for tk, prs in multi.items():
    prs_sorted = sorted(prs, key=lambda x: x['entry_date'])
    print(f"\n  {tk} {prs_sorted[0]['name']}: {len(prs_sorted)}个持仓期")
    for r in prs_sorted:
        c0 = r['entry_cost0']
        g3 = '触发@'+r['gate3_trigger_date']+f"(峰值{r.get('gate3_peak_pct_at_trigger',0)*100:.0f}%)" if r.get('gate3_triggered') else '未触发'
        g1 = '触发@'+r['gate1_trigger_date'] if r.get('gate1_triggered') else '未触发'
        print(f"    entry={r['entry_date']} cost0={c0} exit={r['exit_date'] or '(持有中)'}  门③:{g3}  门①:{g1}")

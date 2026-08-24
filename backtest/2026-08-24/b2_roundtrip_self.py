#!/usr/bin/env python3
"""B2 自算版: round-trip门口径审判 (agent三次掉线后改自己算)

核心质疑: 现行round-trip门是"持有期峰值≥+15% 且 现价回到成本以下"→卖。
"吐回成本"里的成本是我的买入价,不是股票的属性——同一只股票,我买贵了它就触发,
我买便宜了它就不触发。这和已被改掉的灾难线是同一类毛病。

替代方案: "从持有期峰值回撤X%"(与成本无关),X取10/15/20。

数据: portfolio_state.json trade_log (a_share, 2026-06-24以后) + 腾讯前复权日K
      每行 [日期,开,收,高,低,量] → 收=r[2] 高=r[3] 低=r[4]
"""
import json, urllib.request, statistics, sys, time

SP = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio'
START = '2026-06-24'
END = '2026-08-24'

def kline(code):
    mkt = 'sh' if code[0] == '6' else ('bj' if code.startswith('920') else 'sz')
    url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?"
           f"param={mkt}{code},day,2026-05-01,{END},200,qfq")
    for attempt in range(2):
        try:
            d = json.load(urllib.request.urlopen(url, timeout=8))['data'][f'{mkt}{code}']
            rows = d.get('qfqday') or d.get('day') or []
            return [{'d': r[0], 'c': float(r[2]), 'h': float(r[3]), 'l': float(r[4])} for r in rows]
        except Exception as e:
            if attempt == 0:
                time.sleep(1.0)   # 串行+退避: 前三次agent都是并发把腾讯WAF打崩
            else:
                return []
    return []

st = json.load(open(f'{SP}/portfolio_state.json'))
log = [t for t in st['trade_log']
       if t.get('account') == 'a_share' and t.get('date', '') >= START]

# 按ticker重建持仓期(FIFO简化: 首次buy到清零为一段)
segs = {}
for t in sorted(log, key=lambda x: (x['date'], x['id'])):
    tk = t['ticker']
    s = segs.setdefault(tk, {'name': t.get('name', tk), 'sh': 0, 'cost': 0.0,
                             'open': None, 'close': None, 'exit_px': None})
    if t['action'] == 'buy':
        if s['sh'] == 0:
            s['open'] = t['date']
        s['cost'] = (s['cost'] * s['sh'] + t['price'] * t['shares']) / (s['sh'] + t['shares'])
        s['sh'] += t['shares']
    else:
        s['sh'] -= t['shares']
        if s['sh'] <= 0:
            s['close'] = t['date']; s['exit_px'] = t['price']; s['sh'] = 0

cases = [(tk, s) for tk, s in segs.items() if s['open']]
print(f"持仓段: {len(cases)} 只 (2026-06-24以后建仓)\n")

RULES = ['现行(峰值+15%吐回成本)', '峰值回撤10%', '峰值回撤15%', '峰值回撤20%', '不设该门']
res = {r: [] for r in RULES}
trigger_cnt = {r: 0 for r in RULES}
detail = []

for tk, s in cases:
    bars = kline(tk)
    if not bars:
        print(f"  {s['name']}({tk}) 取数失败,跳过"); continue
    hold = [b for b in bars if b['d'] >= s['open'] and (not s['close'] or b['d'] <= s['close'])]
    if len(hold) < 3: continue
    cost = s['cost']
    final = s['exit_px'] if s['exit_px'] else hold[-1]['c']   # 未平仓用最新收盘

    peak = hold[0]['h']
    fired = {r: None for r in RULES}
    for b in hold:
        peak = max(peak, b['h'])
        pk_gain = peak / cost - 1
        # 现行门: 峰值≥+15% 且 收盘≤成本
        if fired['现行(峰值+15%吐回成本)'] is None and pk_gain >= 0.15 and b['c'] <= cost:
            fired['现行(峰值+15%吐回成本)'] = b['c']
        # 替代门: 从峰值回撤X%(与成本无关)
        for x, rn in ((0.10, '峰值回撤10%'), (0.15, '峰值回撤15%'), (0.20, '峰值回撤20%')):
            if fired[rn] is None and b['c'] <= peak * (1 - x):
                fired[rn] = b['c']
    for r in RULES:
        px = final if r == '不设该门' else (fired.get(r) or final)
        if r != '不设该门' and fired.get(r): trigger_cnt[r] += 1
        res[r].append(px / cost - 1)
    detail.append((s['name'], tk, cost, final,
                   {r: fired.get(r) for r in RULES if r != '不设该门'}))

print(f"有效样本: {len(res['不设该门'])} 只\n")
print(f"{'规则':<24}{'触发数':>7}{'均收益':>10}{'中位':>9}{'胜率':>8}{'p5':>9}{'p95':>9}")
print('-' * 78)
for r in RULES:
    v = res[r]
    if not v: continue
    v_s = sorted(v)
    p5 = v_s[max(0, int(len(v_s) * 0.05))]; p95 = v_s[min(len(v_s) - 1, int(len(v_s) * 0.95))]
    print(f"{r:<24}{trigger_cnt[r] if r!='不设该门' else '-':>7}"
          f"{statistics.mean(v)*100:>9.2f}%{statistics.median(v)*100:>8.2f}%"
          f"{sum(1 for x in v if x>0)/len(v)*100:>7.0f}%{p5*100:>8.1f}%{p95*100:>8.1f}%")

print('\n' + '=' * 78)
print('逐只明细(触发价格; None=未触发,按实际/最新价计)')
for nm, tk, cost, final, f in detail:
    fs = ' '.join(f"{k.replace('峰值回撤','DD').replace('现行(峰值+15%吐回成本)','现行')}={('%.2f'%v) if v else '-'}"
                  for k, v in f.items())
    print(f"  {nm:<10}({tk}) 成本{cost:>8.2f} 终价{final:>8.2f} | {fs}")

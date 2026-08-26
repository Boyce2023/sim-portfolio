#!/usr/bin/env python3
"""从 univ2025.db 重构2025年全年涨停(方法与daban/rebuild_full.py一致,自行复算保证本目录自包含可复跑),
然后筛出 2025-07-01~2025-08-31 区间. 用preclose字段(baostock已处理除权,比自算前收可靠)。
涨停判定: close == round(preclose*(1+limit_pct),2), 容差0.005元。
limit_pct: 主板(60/00开头)10%; 创业板(30)/科创板(688)20%; 北交所(8/4/92开头)30%; ST=5%(覆盖上面)。
"""
import sqlite3, json, sys
from collections import defaultdict

DB = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban/univ2025.db'
OUT = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/research-notes/astock-database/2026-08-26_游资选股学习/julaug'
START, END = '2025-07-01', '2025-08-31'

def lim_pct(code):
    b = code.split('.')[1]
    if b.startswith(('30','68')): return 0.20
    if b.startswith(('8','4','92')): return 0.30
    return 0.10

con = sqlite3.connect(DB)
rows = con.execute("select code,date,open,high,low,close,preclose,volume,amount,turn,isST from k where preclose>0 order by code,date").fetchall()
print(f'读入{len(rows)}行', file=sys.stderr)
bycode = defaultdict(list)
for r in rows: bycode[r[0]].append(r)

lus = []
for code, bars in bycode.items():
    lp0 = lim_pct(code)
    for i, b in enumerate(bars):
        _, d, o, h, l, c, pc, v, amt, turn, st = b
        lp = 0.05 if st else lp0
        lim = round(pc*(1+lp), 2)
        is_zt = abs(c - lim) < 0.005
        if not is_zt: continue
        # streak: 往前数连续涨停天数(用同样规则,跨越6-8月边界也算,保证7月初的连板不被截断)
        streak = 1; j = i-1
        while j >= 0:
            pb = bars[j]
            lpj = 0.05 if pb[10] else lp0
            if pb[6] > 0 and abs(pb[5] - round(pb[6]*(1+lpj), 2)) < 0.005:
                streak += 1; j -= 1
            else:
                break
        k = max(0, i-20)
        gain20 = round((c/bars[k][5]-1)*100, 2) if bars[k][5] > 0 else None
        # only keep if within our target date range (但streak/gain20已用全年数据算,不受边界截断影响)
        if START <= d <= END:
            circ_mcap = None
            if turn and turn > 0:
                circ_mcap = round(amt/turn*100, 0)  # amount/turn*100, turn是百分比单位(如0.2688=0.2688%)
            lus.append({
                'code': code, 'date': d, 'close': c, 'preclose': pc,
                'streak': streak,
                'yizi': abs(o-lim) < 0.005 and abs(l-lim) < 0.005,
                'open_gap': round((o/pc-1)*100, 2),
                'turn_pct': turn, 'amount': amt, 'circ_mcap_yuan': circ_mcap,
                'gain20_before': gain20, 'isST': st, 'board_pct': lp0,
            })

print(f'区间{START}~{END} 涨停记录 {len(lus)} 条', file=sys.stderr)
json.dump(lus, open(f'{OUT}/limitups_julaug2025.json', 'w'), ensure_ascii=False, indent=0)

# CSV版本方便查看
import csv
with open(f'{OUT}/limitups_julaug2025.csv', 'w', newline='', encoding='utf-8-sig') as f:
    w = csv.DictWriter(f, fieldnames=list(lus[0].keys()))
    w.writeheader()
    for r in lus: w.writerow(r)

bd = defaultdict(int)
for r in lus: bd[r['date']] += 1
ds = sorted(bd)
print(f'交易日{len(ds)}天', file=sys.stderr)
for d, n in sorted(bd.items(), key=lambda x: -x[1])[:15]:
    print(f'  {d}: {n}只涨停', file=sys.stderr)

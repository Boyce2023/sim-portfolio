#!/usr/bin/env python3
import json, csv
from collections import defaultdict

lus = json.load(open('limitups_julaug2025.json'))
name_map = {}
with open('name_map.csv', encoding='utf-8-sig') as f:
    r = csv.DictReader(f)
    for row in r:
        name_map[row['code']] = row['name'].replace('　','').strip()

def code6(c):
    return c.split('.')[1]

for r in lus:
    r['code6'] = code6(r['code'])
    r['name'] = name_map.get(r['code6'], '?')

# daily counts
bd = defaultdict(list)
for r in lus:
    bd[r['date']].append(r)

daily_counts = {d: len(v) for d, v in bd.items()}
top_days = sorted(daily_counts.items(), key=lambda x: -x[1])[:8]
print("=== TOP 8 涨停家数交易日 ===")
for d, n in top_days:
    print(f"{d}: {n}只")

json.dump(dict(sorted(daily_counts.items())), open('daily_zt_counts.json','w'), ensure_ascii=False, indent=2)

# streak>=3 within period: find max streak reached per code within the period, and the date it peaked
maxstreak_by_code = {}
for r in lus:
    c = r['code']
    if c not in maxstreak_by_code or r['streak'] > maxstreak_by_code[c]['streak']:
        maxstreak_by_code[c] = r

lianban3 = [v for v in maxstreak_by_code.values() if v['streak'] >= 3]
lianban3.sort(key=lambda x: -x['streak'])
print(f"\n=== 连板>=3 (期间内达到的最高连板数) 样本量 n={len(lianban3)} ===")
for r in lianban3[:40]:
    print(f"{r['code6']} {r['name']} peak_date={r['date']} streak={r['streak']} circ_mcap_yi={r['circ_mcap_yuan']/1e8 if r['circ_mcap_yuan'] else None:.1f} gain20_before={r['gain20_before']}")

with open('lianban_ge3_julaug2025.csv', 'w', newline='', encoding='utf-8-sig') as f:
    w = csv.DictWriter(f, fieldnames=list(lianban3[0].keys()))
    w.writeheader()
    for r in lianban3: w.writerow(r)

print(f"\n总涨停记录数(期间内,含每日): {len(lus)}")
print(f"去重后不同股票数: {len(maxstreak_by_code)}")

# streak distribution
sc = defaultdict(int)
for r in maxstreak_by_code.values():
    sc[min(r['streak'],8)] += 1
print("\n连板峰值分布(按不同股票,取期间内最高连板):")
for k in sorted(sc):
    label = f"{k}板+" if k==8 else f"{k}板"
    print(f"  {label}: {sc[k]}只")

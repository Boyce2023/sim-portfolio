"""读 <TICKER>_13f_panel.csv, 按季度列出新建仓/加仓/高仓位占比的机构。
用法: python3 analyze_holders.py DUOL
口径:
  新建仓 = 上一报告期检索不到持有记录, 本期持有普通股 > 0
  加仓   = 两期都持有, 股数增加 >= 20%
  高占比 = DUOL 市值占该机构整个 13F 组合 >= 1%
  被动/指数类机构按名称关键词剔出主表(它们的增减来自资金流, 不是观点)
"""
import csv, sys, os, collections

TICK = sys.argv[1].upper()
D = os.path.dirname(os.path.abspath(__file__))
P = ['2025-12-31', '2026-03-31', '2026-06-30', '2026-09-30']
PASSIVE = ['VANGUARD', 'BLACKROCK', 'STATE STREET', 'GEODE', 'NORTHERN TRUST', 'DIMENSIONAL', 'CHARLES SCHWAB',
           'INVESCO', 'FIDELITY', 'NUVEEN', 'TIAA', 'JPMORGAN', 'MORGAN STANLEY', 'GOLDMAN', 'UBS', 'BANK OF AMERICA',
           'WELLS FARGO', 'RBC', 'BNY', 'MELLON', 'LEGAL & GENERAL', 'NORGES', 'CALIFORNIA PUBLIC', 'TEACHERS',
           'RETIREMENT', 'PENSION', 'BANK', 'TRUST CO', 'ADVISORS INC', 'WEALTH', 'FINANCIAL PLANNING', 'PRIVATE CLIENT']

rows = list(csv.DictReader(open(os.path.join(D, f'{TICK}_13f_panel.csv'))))
by = collections.defaultdict(dict)
name = {}
for r in rows:
    by[r['cik']][r['period']] = r
    name[r['cik']] = r['name']


def f(x):
    try: return float(x)
    except Exception: return 0.0


def passive(n):
    u = n.upper()
    return any(k in u for k in PASSIVE)


out = []
for cik, d in by.items():
    for i in range(1, len(P)):
        cur, prev = d.get(P[i]), d.get(P[i - 1])
        if not cur or f(cur['shares']) <= 0:
            continue
        sh, psh = f(cur['shares']), f(prev['shares']) if prev else 0.0
        kind = '新建仓' if psh <= 0 else ('加仓' if sh >= psh * 1.2 else None)
        if not kind:
            continue
        out.append(dict(period=P[i], kind=kind, cik=cik, name=name[cik], shares=int(sh), prev=int(psh),
                        chg=(sh / psh - 1) * 100 if psh > 0 else None, value=f(cur['value']),
                        weight=f(cur['weight_pct']), passive=passive(name[cik]), options=cur['options']))

w = csv.writer(open(os.path.join(D, f'{TICK}_13f_changes.csv'), 'w', newline=''))
w.writerow(list(out[0].keys()) if out else [])
for o in out:
    w.writerow(o.values())

for per in P[1:]:
    act = [o for o in out if o['period'] == per and not o['passive']]
    print(f"\n===== 报告期 {per}: 主动类 新建仓 {sum(o['kind']=='新建仓' for o in act)} 家 / 加仓 {sum(o['kind']=='加仓' for o in act)} 家 =====")
    for o in sorted(act, key=lambda o: -o['value'])[:30]:
        c = f"+{o['chg']:.0f}%" if o['chg'] is not None else '新'
        print(f"  {o['kind']:3s} {o['name'][:44]:44s} 股数 {o['shares']:>10,} ({c:>6s}) 市值 ${o['value']/1e6:7.1f}M 占组合 {o['weight']:5.2f}% {o['options']}")
    hi = [o for o in act if o['weight'] >= 1]
    print(f"  -- 其中 DUOL 占组合 >=1% 的: {len(hi)} 家: " + '; '.join(f"{o['name'][:30]}({o['weight']:.1f}%)" for o in sorted(hi, key=lambda o: -o['weight'])))

# ===== 合并视图(2026-10-14 Buwen: 几个季度一起看) =====
# 每家机构一行: 首次出现的季度、各期股数、最新一期占组合比; 只保留今年(Q1起)有新建或加仓动作的主动类
print("\n\n===== 合并视图: 2026 年内新建或加仓的主动类机构(各期股数, 最新占比) =====")
acts = collections.defaultdict(list)
for o in out:
    if not o['passive']:
        acts[o['cik']].append(o)
lines = []
for cik, lst in acts.items():
    d = by[cik]
    sh = [int(f(d[p]['shares'])) if p in d else 0 for p in P]
    first = next((P[i] for i in range(len(P)) if sh[i] > 0), None)
    last_p = max(p for p in P if p in d and f(d[p]['shares']) > 0)
    lv = f(d[last_p]['value']); lw = f(d[last_p]['weight_pct'])
    tags = '/'.join(sorted({f"{o['period'][5:7]}月{o['kind']}" for o in lst}))
    lines.append((lv, name[cik], first, sh, lw, last_p, tags))
lines.sort(key=lambda x: -x[0])
print(f"  共 {len(lines)} 家 | 列: 名称 | 首次出现 | 25Q4 / 26Q1 / 26Q2 / 26Q3(早报) 股数 | 最新市值 | 占组合 | 动作")
for lv, n, first, sh, lw, lp, tags in lines[:60]:
    print(f"  {n[:40]:40s} 首见{first} | {sh[0]:>9,} {sh[1]:>9,} {sh[2]:>9,} {sh[3]:>9,} | ${lv/1e6:6.1f}M | {lw:5.2f}% | {tags}")

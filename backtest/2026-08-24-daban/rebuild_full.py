#!/usr/bin/env python3
"""全A股2025涨停重构 — 数据源univ2025.db(baostock,5182只/124.8万行,0失败)
涨停判定用 preclose 字段(baostock自带,已处理除权),比自算前收可靠。
"""
import sqlite3,json,sys
from collections import defaultdict
BASE='/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban'
con=sqlite3.connect(f'{BASE}/univ2025.db')

def lim_pct(c):
    b=c.split('.')[1]
    if b.startswith(('30','68')): return 0.20
    if b.startswith(('8','4','92')): return 0.30
    return 0.10

rows=con.execute("select code,date,open,high,low,close,preclose,volume,amount,turn,isST from k where preclose>0 order by code,date").fetchall()
print(f'读入{len(rows)}行',file=sys.stderr)
bycode=defaultdict(list)
for r in rows: bycode[r[0]].append(r)

lus=[]; bars_idx={}
for code,bars in bycode.items():
    lp0=lim_pct(code)
    bars_idx[code]={b[1]:i for i,b in enumerate(bars)}
    for i,b in enumerate(bars):
        _,d,o,h,l,c,pc,v,amt,turn,st=b
        lp=0.05 if st else lp0
        lim=round(pc*(1+lp),2)
        if abs(c-lim)<0.005:
            streak=1; j=i-1
            while j>=0:
                pb=bars[j]; lpj=0.05 if pb[10] else lp0
                if pb[6]>0 and abs(pb[5]-round(pb[6]*(1+lpj),2))<0.005: streak+=1; j-=1
                else: break
            k=max(0,i-20)
            lus.append({'code':code,'date':d,'close':c,'streak':streak,
                'yizi':abs(o-lim)<0.005 and abs(l-lim)<0.005,
                'open_gap':round((o/pc-1)*100,2),'turn':turn,'amount':amt,
                'gain20':round((c/bars[k][5]-1)*100,2) if bars[k][5]>0 else None,
                'isST':st,'board':lp0})
print(f'涨停记录 {len(lus)} 条',file=sys.stderr)
json.dump(lus,open(f'{BASE}/limitups_full2025.json','w'))
bd=defaultdict(int)
for r in lus: bd[r['date']]+=1
ds=sorted(bd)
print(f'交易日{len(ds)} 日均涨停{len(lus)/len(ds):.1f}只 最多{max(bd.values())}只 最少{min(bd.values())}只',file=sys.stderr)
import statistics
print(f'中位数{statistics.median(bd.values()):.0f}只',file=sys.stderr)
sc=defaultdict(int)
for r in lus: sc[min(r['streak'],6)]+=1
print('连板分布:',{f'{k}板':v for k,v in sorted(sc.items())},file=sys.stderr)

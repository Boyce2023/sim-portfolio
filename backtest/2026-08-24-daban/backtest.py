#!/usr/bin/env python3
"""打板回测: 涨停日T0 → T+1开盘买入(唯一可实现口径) → T+1/T+2/T+5收盘卖出
⛔买入价用次日开盘: 涨停当天在板上买入是不可实现假设(封单排队),用次日开盘最保守可复现
⛔一字板剔除: 次日开盘往往仍一字,买不进
"""
import sqlite3,json,sys,statistics
from collections import defaultdict
BASE='/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban'
con=sqlite3.connect(f'{BASE}/univ2025.db')
lus=json.load(open(f'{BASE}/limitups_full2025.json'))

rows=con.execute("select code,date,open,close from k where preclose>0 order by code,date").fetchall()
px=defaultdict(dict); seq=defaultdict(list)
for code,d,o,c in rows:
    px[code][d]={'o':o,'c':c}; seq[code].append(d)

def fwd(code,d0,n):
    s=seq[code]
    try: i=s.index(d0)
    except ValueError: return None
    if i+n>=len(s): return None
    return s[i+n]

res=[]
for r in lus:
    code,d0=r['code'],r['date']
    d1=fwd(code,d0,1)
    if not d1: continue
    buy=px[code][d1]['o']
    if buy<=0: continue
    rec={**r,'buy':buy,'buy_date':d1}
    # 次日开盘涨幅(判断是否一字/高开)
    rec['gap1']=round((buy/r['close']-1)*100,2)
    for n,tag in [(1,'t1'),(2,'t2'),(5,'t5')]:
        dn=fwd(code,d1,n-1)
        rec[tag]=round((px[code][dn]['c']/buy-1)*100,2) if dn else None
    res.append(rec)
json.dump(res,open(f'{BASE}/backtest_raw.json','w'))

def stat(rs,label,key='t1'):
    v=[x[key] for x in rs if x.get(key) is not None]
    if len(v)<10: return f'{label:<28} n={len(v):<5} 样本不足'
    v.sort()
    return (f'{label:<28} n={len(v):<5} 均值{statistics.mean(v):+6.2f}% 中位{statistics.median(v):+6.2f}% '
            f'胜率{sum(1 for x in v if x>0)/len(v)*100:5.1f}% p5{v[int(len(v)*.05)]:+6.1f}% p95{v[int(len(v)*.95)]:+6.1f}%')

print('='*104)
print('全样本 (T+1开盘买入)')
print('='*104)
for k in ['t1','t2','t5']:
    print(f'  {k.upper():4}', stat(res,'全部涨停',k)[28:])
print()
print('剔除一字板后:')
nz=[r for r in res if not r['yizi']]
for k in ['t1','t2','t5']:
    print(f'  {k.upper():4}', stat(nz,'非一字',k)[28:])
print()
print('='*104); print('按连板数分层 (非一字, T+1收益)'); print('='*104)
for s in range(1,7):
    g=[r for r in nz if r['streak']==s] if s<6 else [r for r in nz if r['streak']>=6]
    print(' ',stat(g,f'{s}板' if s<6 else '6板及以上'))
print()
print('='*104); print('按次日开盘缺口分层 (非一字首板, T+1收益)'); print('='*104)
fb=[r for r in nz if r['streak']==1]
for lo,hi,lab in [(-99,-2,'低开>2%'),(-2,0,'低开0~2%'),(0,2,'高开0~2%'),(2,5,'高开2~5%'),(5,99,'高开>5%')]:
    g=[r for r in fb if lo<=r['gap1']<hi]
    print(' ',stat(g,lab))
print()
print('='*104); print('按板前20日涨幅分层 (非一字首板, T+1收益)'); print('='*104)
for lo,hi,lab in [(-99,0,'20日跌'),(0,20,'20日涨0-20%'),(20,50,'20日涨20-50%'),(50,999,'20日涨>50%')]:
    g=[r for r in fb if r['gain20'] is not None and lo<=r['gain20']<hi]
    print(' ',stat(g,lab))

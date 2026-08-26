#!/usr/bin/env python3
"""2026年1月样本外验证 — 策略参数在2025样本内已锁死,此处不做任何调参
锁定参数: gap1<=0 (次日不高开) & streak<=3 & gain20>=50 & 非一字
买入=次日开盘, 卖出=T+1收盘
"""
import sqlite3,json,statistics
from collections import defaultdict
BASE='/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban'
con=sqlite3.connect(f'{BASE}/univ202601.db')

def lim_pct(c):
    b=c.split('.')[1]
    if b.startswith(('30','68')): return 0.20
    if b.startswith(('8','4','92')): return 0.30
    return 0.10

rows=con.execute("select code,date,open,high,low,close,preclose,turn,isST from k where preclose>0 order by code,date").fetchall()
bycode=defaultdict(list)
for r in rows: bycode[r[0]].append(r)

sig=[]
for code,bars in bycode.items():
    lp0=lim_pct(code)
    for i,b in enumerate(bars):
        _,d,o,h,l,c,pc,turn,st=b
        if not ('2026-01-01'<=d<='2026-01-31'): continue
        lp=0.05 if st else lp0
        lim=round(pc*(1+lp),2)
        if abs(c-lim)>=0.005: continue                      # 非涨停
        if abs(o-lim)<0.005 and abs(l-lim)<0.005: continue  # 一字板剔除
        streak=1; j=i-1
        while j>=0:
            pb=bars[j]; lpj=0.05 if pb[8] else lp0
            if pb[6]>0 and abs(pb[5]-round(pb[6]*(1+lpj),2))<0.005: streak+=1; j-=1
            else: break
        k=max(0,i-20)
        g20=(c/bars[k][5]-1)*100 if bars[k][5]>0 else None
        if i+2>=len(bars): continue
        buy=bars[i+1][2]                                     # T+1开盘买入
        if buy<=0: continue
        gap1=(buy/c-1)*100
        sig.append({'code':code,'date':d,'streak':streak,'gain20':g20,'gap1':gap1,
            'buy':buy,'buy_date':bars[i+1][1],
            't1':(bars[i+1][5]/buy-1)*100,
            't2':(bars[i+2][5]/buy-1)*100 if i+2<len(bars) else None,
            't5':(bars[i+5][5]/buy-1)*100 if i+5<len(bars) else None})

print(f'2026年1月非一字涨停(可交易) n={len(sig)}')
sel=[s for s in sig if s['gap1']<=0 and s['streak']<=3 and s['gain20'] is not None and s['gain20']>=50]
print(f'策略选中 n={len(sel)}\n')

def rep(rs,lab):
    for k in ['t1','t2','t5']:
        v=[x[k] for x in rs if x.get(k) is not None]
        if len(v)<5: print(f'  {lab} {k.upper()}: n={len(v)} 样本不足'); continue
        v2=sorted(v)
        print(f'  {lab} {k.upper()}: n={len(v):<4} 均值{statistics.mean(v):+6.2f}% 中位{statistics.median(v):+6.2f}% '
              f'胜率{sum(1 for x in v if x>0)/len(v)*100:5.1f}% p5{v2[int(len(v2)*.05)]:+6.1f}% p95{v2[int(len(v2)*.95)]:+6.1f}%')
print('【策略选中】'); rep(sel,'策略')
print('\n【全部非一字涨停(对照基准)】'); rep(sig,'基准')

# 逐日
print('\n'+'='*84); print('逐日选股明细 (T+1收益)'); print('='*84)
bd=defaultdict(list)
for s in sel: bd[s['date']].append(s)
cum=0
for d in sorted(bd):
    g=bd[d]; m=statistics.mean([x['t1'] for x in g]); cum+=m
    names=' '.join(f"{x['code'].split('.')[1]}({x['t1']:+.1f}%)" for x in g[:6])
    print(f"{d}  {len(g)}只 均{m:+6.2f}% 累计{cum:+7.2f}%  {names}")
json.dump({'selected':sel,'all':sig},open(f'{BASE}/oos_result.json','w'))

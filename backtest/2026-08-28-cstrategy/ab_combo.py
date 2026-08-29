#!/usr/bin/env python3
"""A+B组合回测: 50/50资金各自独立跑(月初等分,月内不再平衡)+持仓重叠统计
用法: python3 ab_combo.py univ202604.db 2026-04-01 2026-04-30"""
import sys,collections
sys.path.insert(0,'/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban')
B='/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban/'
db,m0,m1=sys.argv[1],sys.argv[2],sys.argv[3]
from engine import load as loadA, signals as sigA, run as runA
from engine_b2 import build, run_b2
byA=loadA(B+db)
TD=sorted({b[1] for bars in byA.values() for b in bars if m0<=b[1]<=m1})
sA=sigA(byA,m0,m1)
navA,trA,logA=runA(byA,sA,TD,TD[-1])
byB,sB,mood=build(B+db,m0,m1)
navB,trB=run_b2(sB,mood,use_mood=False)
netsA=[t['net'] for t in trA];netsB=[t['net'] for t in trB]
wA=sum(1 for x in netsA if x>0)/len(netsA)*100 if netsA else 0
wB=sum(1 for x in netsB if x>0)/len(netsB)*100 if netsB else 0
combo=0.5*navA+0.5*navB
# 重叠: 同一票两策略都交易过
cA={t['code'] for t in trA};cB={t['code'] for t in trB}
ov=cA&cB
print(f'A  {m0[:7]}: NAV={navA:.4f} {(navA-1)*100:+.1f}% 笔数{len(trA)} 胜率{wA:.0f}%')
print(f'B  {m0[:7]}: NAV={navB:.4f} {(navB-1)*100:+.1f}% 笔数{len(trB)} 胜率{wB:.0f}% ⚠️涨停必成交假设')
print(f'A+B 50/50: NAV={combo:.4f} {(combo-1)*100:+.1f}%')
print(f'选股重叠: A交易{len(cA)}只 B交易{len(cB)}只 重叠{len(ov)}只 {sorted(x[-6:] for x in ov)[:10]}')
import json
json.dump({'A':trA,'B':trB},open(f'ab_{m0[:7]}.json','w'),ensure_ascii=False)
print('AB_DONE')

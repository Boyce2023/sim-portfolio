#!/usr/bin/env python3
"""Phase3b: 季节门=物种存量温度计(每日全市场60日涨50%+缓涨股数量,PIT)
与eco门区别: 数物种存量(大而稳)而非入场信号(少而噪)。机理源自Phase1月度分布,非调优。"""
import sys,json
sys.path.insert(0,'.')
import engine_c as E
from engine_c import load,lim_pct,signals
from strategy_c import PARAMS_C

by=load('univ2025.db')
# 每日物种存量
alldays=sorted({b[1] for bars in by.values() for b in bars if b[1].startswith('2025')})
stock_cnt={d:0 for d in alldays}
for code,bars in by.items():
    l0=lim_pct(code)
    for i in range(60,len(bars)):
        d=bars[i][1]
        if d not in stock_cnt: continue
        win=bars[i-59:i+1]
        closes=[x[5] for x in win]
        if closes[0]<=0: continue
        ret=(closes[-1]/closes[0]-1)*100
        if ret<50: continue
        peak=closes[0];mdd=0
        for c in closes: peak=max(peak,c);mdd=min(mdd,(c/peak-1)*100)
        if mdd>=-15:
            turns=[x[9] for x in win if x[9]]
            if turns and sum(turns)/len(turns)>=4:
                stock_cnt[d]+=1
json.dump(stock_cnt,open('season_gauge.json','w'))
ms={}
for d,n in stock_cnt.items(): ms.setdefault(d[:7],[]).append(n)
print('物种存量月均:',{m:round(sum(v)/len(v)) for m,v in sorted(ms.items())})
# 用最优参数(conf20/MA20)+季节门(存量>=TH才开新仓)跑全年
P=dict(PARAMS_C); P['ret20_min']=20; P['ret20_max']=75; P['exit_ma']=20
E.P=P
sig=signals(by,'2025-01-01','2025-12-31')
for TH in (0,30,60,100):
    s2={d:v for d,v in sig.items() if stock_cnt.get(d,0)>=TH} if TH>0 else sig
    nav,tr=E.run(by,s2,'2025-01-01','2025-12-31')
    nets=[t['net'] for t in tr]
    w=sum(1 for x in nets if x>0)/len(nets)*100 if nets else 0
    print(f'季节门TH={TH}: NAV={nav:.4f} {(nav-1)*100:+.1f}% 笔数{len(tr)} 胜率{w:.0f}%')
print('SEASON_DONE')

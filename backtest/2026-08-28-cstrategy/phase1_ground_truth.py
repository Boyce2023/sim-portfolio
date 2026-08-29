#!/usr/bin/env python3
"""Phase1: 2025真庄股全集+利润天花板"""
import sys,json
sys.path.insert(0,'.')
from engine_c import load,lim_pct
by=load('univ2025.db')
W=60
zhuang=[]
for code,bars in by.items():
    if len(bars)<W+10: continue
    l0=lim_pct(code)
    best=None
    i=W
    while i<len(bars):
        win=bars[i-W:i]
        closes=[x[5] for x in win]
        d0,d1=win[0][1],win[-1][1]
        if not (d1.startswith('2025')): i+=1; continue
        ret=(closes[-1]/closes[0]-1)*100
        if ret<60: i+=5; continue
        peak=closes[0];mdd=0;lu=0
        turns=[x[9] for x in win if x[9]]
        for x in win:
            cc=x[5];ppc=x[6];ss=x[10]
            peak=max(peak,cc);mdd=min(mdd,(cc/peak-1)*100)
            if ppc>0:
                L=0.05 if ss else l0
                if abs(cc-round(ppc*(1+L),2))<0.005: lu+=1
        if mdd>=-15 and lu<=4 and turns and sum(turns)/len(turns)>=4:
            if best is None or ret>best['ret']:
                best={'code':code,'start':d0,'end':d1,'ret':round(ret,1),'mdd':round(mdd,1),'lu':lu,
                      'turn':round(sum(turns)/len(turns),1)}
        i+=5
    if best: zhuang.append(best)
zhuang.sort(key=lambda x:-x['ret'])
json.dump(zhuang,open('zhuang_2025.json','w'),ensure_ascii=False)
print(f'2025真庄股(60日涨60%+回撤<15%+换手4%+非连板): {len(zhuang)}只')
print('利润天花板: 若每只完美吃满拉升段,平均段内收益 %.1f%%'%(sum(z["ret"] for z in zhuang)/len(zhuang)))
print('Top10:',[(z['code'][-6:],z['ret'],z['start'][:7]) for z in zhuang[:10]])
import collections
print('拉升起始月分布:',dict(sorted(collections.Counter(z['start'][:7] for z in zhuang).items())))

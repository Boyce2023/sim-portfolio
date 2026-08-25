#!/usr/bin/env python3
"""在2025样本内做参数搜索,选出最优打板策略。⛔只用2025数据,2026年1月一行都不碰。"""
import json,statistics,itertools
from collections import defaultdict
BASE='/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban'
R=[r for r in json.load(open(f'{BASE}/backtest_raw.json')) if not r['yizi'] and r.get('t1') is not None]
print(f'2025非一字样本 n={len(R)}\n')

def ev(rs,key='t1'):
    v=[x[key] for x in rs if x.get(key) is not None]
    if len(v)<50: return None
    return dict(n=len(v),mean=statistics.mean(v),med=statistics.median(v),
                win=sum(1 for x in v if x>0)/len(v)*100)

# 逐维度搜索
grid={
 'gap_max':[0,1,2,3,5,99],          # 次日开盘最大高开(超过不买)
 'streak_max':[1,2,3,5,99],          # 最大连板数
 'gain20_min':[-99,-10,0,20,50],     # 板前20日最小涨幅
 'turn_max':[5,10,20,99],            # 涨停日换手上限(%)
}
best=[]
for gm,sm,g20,tm in itertools.product(*grid.values()):
    sel=[r for r in R if r['gap1']<=gm and r['streak']<=sm
         and (r['gain20'] is not None and r['gain20']>=g20)
         and (r['turn'] or 0)<=tm]
    s=ev(sel)
    if s and s['n']>=200:
        best.append(((gm,sm,g20,tm),s))
best.sort(key=lambda x:-x[1]['mean'])
print('%-34s %6s %8s %8s %7s'%('参数(gap<=/streak<=/gain20>=/turn<=)','n','均值','中位','胜率'))
for p,s in best[:12]:
    print('gap<=%-3s streak<=%-3s g20>=%-4s turn<=%-3s  %6d %+7.2f%% %+7.2f%% %6.1f%%'%(*p,s['n'],s['mean'],s['med'],s['win']))
print('\n最差5组(反面验证):')
for p,s in best[-5:]:
    print('gap<=%-3s streak<=%-3s g20>=%-4s turn<=%-3s  %6d %+7.2f%% %+7.2f%% %6.1f%%'%(*p,s['n'],s['mean'],s['med'],s['win']))
json.dump([{'params':dict(zip(grid.keys(),p)),**s} for p,s in best[:20]],
          open(f'{BASE}/strategy_candidates.json','w'),indent=1)

#!/usr/bin/env python3
"""Phase3: 跟随策略参数空间搜索(multiprocessing) + H1/H2交叉验证
轴: 确认阈值×生态门×出场MA. 生态门=近20日全市场初筛信号数(庄股密度温度计,Phase1月度分布的可交易化)"""
import sys,json,itertools
from multiprocessing import Pool
sys.path.insert(0,'.')
from engine_c import load,lim_pct
from strategy_c import PARAMS_C

RUN_BY=None
def _init():
    global RUN_BY
    from engine_c import load
    RUN_BY=load('univ2025.db')

def run_one(args):
    conf,eco,ma,half=args
    import engine_c as E
    P=dict(PARAMS_C)
    P['ret20_min']=conf; P['ret20_max']=conf+55
    P['exit_ma']=ma
    E.P=P
    import strategy_c as S
    global RUN_BY
    by=RUN_BY
    m0,m1=('2025-01-01','2025-06-30') if half=='H1' else ('2025-07-01','2025-12-31')
    sig=E.signals(by,m0,m1)
    # 生态门: 近20日信号总数序列
    days=sorted(sig)
    cnt={d:len(sig[d]) for d in days}
    alldays=sorted({b[1] for bars in by.values() for b in bars if m0<=b[1]<=m1})
    roll={}
    for i,d in enumerate(alldays):
        w=alldays[max(0,i-19):i+1]
        roll[d]=sum(cnt.get(x,0) for x in w)
    if eco>0:
        sig={d:v for d,v in sig.items() if roll.get(d,0)>=eco}
    nav,tr=E.run(by,sig,m0,m1)
    nets=[t['net'] for t in tr]
    w_=sum(1 for x in nets if x>0)/len(nets)*100 if nets else 0
    return (conf,eco,ma,half,round(nav,4),len(tr),round(w_,1))

if __name__=='__main__':
    grid=[(c,e,m,h) for c in (10,15,20,25) for e in (0,300,800) for m in (20,30) for h in ('H1','H2')]
    print(f'格子{len(grid)}组合',flush=True)
    res=[]
    with Pool(6,initializer=_init) as p:
        for r in p.imap_unordered(run_one,grid):
            res.append(r); print(r,flush=True)
    json.dump(res,open('phase3_grid.json','w'))
    print('GRID_DONE',flush=True)

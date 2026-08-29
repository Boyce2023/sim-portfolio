#!/usr/bin/env python3
"""C2版: baseline + 户数因子(吸筹确认) + 生态温度计(空仓机制)
⛔户数PIT: 用公告日期(ann)对齐——T日只能用ann<=T的最近一期。统计截止日会造未来函数(6/30数据8/25才公告)。"""
import sys,json
sys.path.insert(0,'.')
from engine_c import load,signals,run
from strategy_c import PARAMS_C as P

GD=json.load(open('gdhs_pit.json'))
def gdhs_ok(code,d):
    """T日已公告的最近一期户数环比<0(吸筹)"""
    bare=code.split('.')[-1]
    recs=[r for r in GD.get(bare,[]) if r['ann']<=d and r.get('chg') is not None]
    if not recs: return None  # 无数据
    latest=max(recs,key=lambda r:r['ann'])
    return latest['chg']<0

def filter_sig(sig,mode='gdhs',eco_th=1.5):
    out={}
    for d,lst in sig.items():
        keep=lst
        if mode in ('gdhs','both'):
            keep=[c for c in keep if gdhs_ok(c['code'],d) is True]
        if mode in ('eco','both'):
            # 生态温度计: 当日最强候选ud<阈值 = 物种休眠 = 全弃
            if not keep or max(c['ud'] for c in keep)<eco_th: keep=[]
        if keep: out[d]=keep
    return out

if __name__=='__main__':
    db,m0,m1,mode=sys.argv[1],sys.argv[2],sys.argv[3],(sys.argv[4] if len(sys.argv)>4 else 'gdhs')
    by=load(db)
    sig=signals(by,m0,m1)
    s2=filter_sig(sig,mode)
    ns=sum(len(v) for v in s2.values())
    nav,tr=run(by,s2,m0,m1)
    nets=[t['net'] for t in tr]
    w=sum(1 for x in nets if x>0)/len(nets)*100 if nets else 0
    print(f'[{mode}] {m0[:7]}~{m1[:7]} 信号{ns} NAV={nav:.4f} {(nav-1)*100:+.2f}% 笔数{len(tr)} 胜率{w:.1f}% 单笔均{sum(nets)/len(nets) if nets else 0:+.2f}%')

#!/usr/bin/env python3
"""C3: 双通道筛子(物种分类学修正,源自08-28手筛的两式分类,非调参)
- quiet通道(百合花式): 缓涨+浅回撤+低换手(锁仓控盘)+温和量比
- hot通道(万邦式): 持续高换手+大振幅+强量比
出场共用: MA20/放量长阴/回撤-10%/40日"""
import sys,collections
sys.path.insert(0,'.')
import engine_c as E
from engine_c import load,lim_pct
from strategy_c import PARAMS_C

def signals3(by,m0,m1,channel):
    sig=collections.defaultdict(list)
    W=20
    for code,bars in by.items():
        if len(bars)<25: continue
        l0=lim_pct(code)
        for i in range(W,len(bars)-1):
            d=bars[i][1]
            if not (m0<=d<=m1): continue
            win=bars[i-W+1:i+1]
            _,_,o,h,l,c,pc,vol,amt,turn,st=win[-1]
            if st or c<3.0 or not turn or turn<=0: continue
            mc=(amt/(turn/100))/1e8
            if not (15<=mc<=150): continue
            closes=[x[5] for x in win]
            ret20=(closes[-1]/closes[0]-1)*100
            peak=closes[0];mdd=0;worst=0;lu=0;upv=[];dnv=[];amps=[];turns=[]
            for x in win:
                cc=x[5];ppc=x[6];vv=x[7];tt=x[9] or 0;hh=x[3];ll=x[4];ss=x[10]
                peak=max(peak,cc);mdd=min(mdd,(cc/peak-1)*100)
                if ppc>0:
                    chg=(cc/ppc-1)*100;worst=min(worst,chg)
                    L=0.05 if ss else l0
                    if abs(cc-round(ppc*(1+L),2))<0.005: lu+=1
                    if chg>0.5: upv.append(vv)
                    elif chg<-0.5: dnv.append(vv)
                if ll>0: amps.append((hh/ll-1)*100)
                turns.append(tt)
            if lu>2 or not upv or not dnv: continue
            ud=(sum(upv)/len(upv))/(sum(dnv)/len(dnv))
            t_avg=sum(turns)/len(turns);amp=sum(amps)/len(amps)
            ok=False
            if channel=='quiet':
                # 百合花式: 涨10-60,回撤<8,单日>-5,换手0.8-5,量比>1.15
                ok=(10<=ret20<=60 and mdd>-8 and worst>-5 and 0.8<=t_avg<=5 and ud>1.15)
            elif channel=='hot':
                # 万邦式: 涨15-75,回撤<12,换手>10且>8%天数>=12,振幅>5,量比>1.25
                hi=sum(1 for t in turns if t>8)
                ok=(15<=ret20<=75 and mdd>-12 and t_avg>10 and hi>=12 and amp>5 and ud>1.25)
            if not ok: continue
            nb=bars[i+1]
            if nb[2]<=0 or not nb[9]: continue
            sig[nb[1]].append({'code':code,'buy':nb[2],'sig_date':d,'ud':round(ud,2),'ret20':round(ret20,1),'mc':round(mc,1)})
    return sig

if __name__=='__main__':
    db,m0,m1,ch=sys.argv[1],sys.argv[2],sys.argv[3],sys.argv[4]
    import sqlite3
    B='/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban/'
    by=load(db)
    if db!='univ2025.db':
        old=set(x[0] for x in sqlite3.connect(B+'univ2025.db').execute("select distinct code from k"))
        by={c:b for c,b in by.items() if c in old}
    P=dict(PARAMS_C);P['exit_ma']=20
    E.P=P
    sig=signals3(by,m0,m1,ch)
    hits=[(d,c) for d,lst in sig.items() for c in lst if c['code'] in ('sh.603823','sz.301520')]
    nav,tr=E.run(by,sig,m0,m1)
    nets=[t['net'] for t in tr]
    w=sum(1 for x in nets if x>0)/len(nets)*100 if nets else 0
    ns=sum(len(v) for v in sig.values())
    print(f'[{ch}] {m0[:7]}~{m1[:7]}: 信号{ns} NAV={nav:.4f} {(nav-1)*100:+.1f}% 笔数{len(tr)} 胜率{w:.0f}%')
    if hits: print('  本尊命中:',[(d,c['code'][-6:]) for d,c in hits][:6])
    bought={t['code'] for t in tr}
    if 'sh.603823' in bought: print('  ★百合花被实际买入!')
    if 'sz.301520' in bought: print('  ★万邦被实际买入!')

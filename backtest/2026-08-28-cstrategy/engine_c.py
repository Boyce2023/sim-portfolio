#!/usr/bin/env python3
"""C策略回测引擎 — 逐日信号+组合模拟。数据源: A策略同款univ db(baostock,含turn)。
⛔PIT纪律: T日收盘算信号,T+1开盘买入;所有滚动窗口只用T日及以前的bar。
⛔无未来函数自检: 不用当日收盘后才知道的排序字段(B2教训);市值用流通市值(amount/turn倒推,T日已知)。"""
import sqlite3, sys, json
from collections import defaultdict
sys.path.insert(0, '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-28-cstrategy')
from strategy_c import PARAMS_C as P

B='/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban/'

def lim_pct(c):
    b=c.split('.')[1]
    if b.startswith(('30','68')): return 0.20
    if b.startswith(('8','4','92')): return 0.30
    return 0.10

def load(db):
    con=sqlite3.connect(B+db)
    rows=con.execute("select code,date,open,high,low,close,preclose,volume,amount,turn,isST from k where preclose>0 and turn>0 order by code,date").fetchall()
    by=defaultdict(list)
    for r in rows: by[r[0]].append(r)
    return by

def signals(by, m0, m1):
    """T日收盘信号 → T+1开盘买。返回 {buy_date: [cand...]}"""
    sig=defaultdict(list)
    W=20
    for code,bars in by.items():
        if len(bars)<P['min_days_listed']: continue
        l0=lim_pct(code)
        for i in range(W, len(bars)-1):
            d=bars[i][1]
            if not (m0<=d<=m1): continue
            win=bars[i-W+1:i+1]
            _,_,o,h,l,c,pc,vol,amt,turn,st=win[-1]
            if st or c<P['min_price']: continue
            # 流通市值(亿) = amount/(turn/100) — T日已知
            if not turn or turn<=0: continue
            mc=(amt/(turn/100))/1e8
            if not (15<=mc<=150): continue
            closes=[x[5] for x in win]; pcs=[x[6] for x in win]
            ret20=(closes[-1]/closes[0]-1)*100
            if not (P['ret20_min']<=ret20<=P['ret20_max']): continue
            peak=closes[0]; mdd=0; worst=0; lu=0
            upv=[]; dnv=[]; amps=[]; turns=[]
            for j,x in enumerate(win):
                _,dd,oo,hh,ll,cc,ppc,vv,aa,tt,ss=x
                peak=max(peak,cc); mdd=min(mdd,(cc/peak-1)*100)
                if ppc>0:
                    chg=(cc/ppc-1)*100
                    worst=min(worst,chg)
                    L=0.05 if ss else l0
                    if abs(cc-round(ppc*(1+L),2))<0.005: lu+=1
                    if chg>0.5: upv.append(vv)
                    elif chg<-0.5: dnv.append(vv)
                if ll>0: amps.append((hh/ll-1)*100)
                turns.append(tt)
            if mdd<P['mdd_min'] or worst<P['worst_day_min'] or lu>P['limitup_max_20d']: continue
            t_avg=sum(turns)/len(turns)
            if t_avg<P['turn_avg_min'] or sum(1 for t in turns if t>P['turn_hi_th'])<P['turn_hi_days']: continue
            if sum(amps)/len(amps)<P['amp_min']: continue
            if not upv or not dnv: continue
            ud=(sum(upv)/len(upv))/(sum(dnv)/len(dnv))
            if ud<P['updn_ratio_min']: continue
            nb=bars[i+1]
            if nb[2]<=0 or not nb[9]: continue
            sig[nb[1]].append({'code':code,'buy':nb[2],'sig_date':d,'ud':round(ud,2),'ret20':round(ret20,1),'mc':round(mc,1)})
    return sig

def run(by, sig, m0, m1):
    TD=sorted({b[1] for bars in by.values() for b in bars if m0<=b[1]<=m1})
    idx={c:{b[1]:i for i,b in enumerate(bars)} for c,bars in by.items()}
    nav=1.0; hold=[]; tr=[]
    def fee(a,sell): return max(a*P['comm'],P['comm_min'])+a*P['transfer']+(a*P['stamp'] if sell else 0)
    def net(buyp,sellp,cap):
        sh=int(cap/(buyp*(1+P['slip']))/100)*100
        if sh<=0: return 0.0
        ba=sh*buyp*(1+P['slip']); sa=sh*sellp*(1-P['slip'])
        return (sa-ba-fee(ba,False)-fee(sa,True))/cap
    for d in TD:
        still=[]
        for h in hold:
            i=idx[h['code']].get(d)
            if i is None:
                bars=by[h['code']]; last=[b for b in bars if b[1]<d]
                px=last[-1][5] if last else h['buy']
                r=net(h['buy'],px,h['cap'])
                nav=nav+ r*(h['cap']/P['capital'])
                tr.append({'code':h['code'],'in':h['buy_date'],'out':d,'gross':(px/h['buy']-1)*100,'net':r*100,'why':'停牌'}); continue
            bars=by[h['code']]; b=bars[i]
            if d<=h['buy_date']: still.append(h); continue
            h['peak']=max(h.get('peak',h['buy']),b[5])
            dd=(b[5]/h['peak']-1)*100
            v20=[x[7] for x in bars[max(0,i-20):i]]
            va=sum(v20)/len(v20) if v20 else 0
            chg=(b[5]/b[6]-1)*100 if b[6]>0 else 0
            maN=[x[5] for x in bars[max(0,i-P['exit_ma']+1):i+1]]
            ma10v=sum(maN)/len(maN)
            hd=sum(1 for x in bars[:i+1] if x[1]>h['buy_date'])
            why='顺延强卖' if h.get('force_exit') else None
            if va>0 and b[7]>va*P['exit_vol_x'] and chg<P['exit_drop']: why='放量长阴'
            elif b[5]<ma10v: why='破%d日线'%P['exit_ma']
            elif dd<=P['exit_dd']: why='持有回撤-10%'
            elif hd>=P['exit_maxhold']: why='满40日'
            if why:
                # ⛔卖出可实现性: 当日收盘=跌停价,单子挂不出去,顺延次日再卖
                pc_=b[6]; L_=0.05 if b[10] else lim_pct(h['code'])
                if pc_>0 and b[5]<=round(pc_*(1-L_),2)+0.005:
                    h['force_exit']=True; still.append(h); continue
                r=net(h['buy'],b[5],h['cap'])
                nav+=r*(h['cap']/P['capital'])
                tr.append({'code':h['code'],'in':h['buy_date'],'out':d,'gross':(b[5]/h['buy']-1)*100,'net':r*100,'why':why})
            else: still.append(h)
        hold=still
        if len(hold)<P['max_positions'] and d in sig:
            cand=sorted(sig[d],key=lambda x:-x['ud'])
            heldc={h['code'] for h in hold}
            for c in cand:
                if len(hold)>=P['max_positions']: break
                if c['code'] in heldc: continue
                # ⛔成交可实现性(08-28补课,对齐A/B标准): T+1开盘已涨停=买不进,放弃
                bars_=by[c['code']]; bi=idx[c['code']].get(d)
                if bi is not None and bi>0:
                    pc_=bars_[bi][6]; L_=0.05 if bars_[bi][10] else lim_pct(c['code'])
                    if pc_>0 and c['buy']>=round(pc_*(1+L_),2)-0.005: continue
                cap=nav*P['capital']/P['max_positions']
                hold.append({'code':c['code'],'buy':c['buy'],'buy_date':d,'cap':cap,'peak':c['buy']})
                heldc.add(c['code'])
    # 期末强平
    if hold:
        d=TD[-1]
        for h in hold:
            bars=by[h['code']]; i=idx[h['code']].get(d)
            px=bars[i][5] if i is not None else h['buy']
            r=net(h['buy'],px,h['cap']); nav+=r*(h['cap']/P['capital'])
            tr.append({'code':h['code'],'in':h['buy_date'],'out':d,'gross':(px/h['buy']-1)*100,'net':r*100,'why':'期末'})
    return nav,tr

if __name__=='__main__':
    db,m0,m1=sys.argv[1],sys.argv[2],sys.argv[3]
    by=load(db)
    sig=signals(by,m0,m1)
    ns=sum(len(v) for v in sig.values())
    nav,tr=run(by,sig,m0,m1)
    nets=[t['net'] for t in tr]
    w=sum(1 for x in nets if x>0)/len(nets)*100 if nets else 0
    print(f'区间{m0}~{m1} 信号{ns}个/{len(sig)}天 NAV={nav:.4f} 收益{(nav-1)*100:+.2f}% 笔数{len(tr)} 胜率{w:.1f}% 单笔均{sum(nets)/len(nets) if nets else 0:+.2f}%')
    import collections
    print('出场分布:',dict(collections.Counter(t['why'] for t in tr)))
    json.dump(tr,open(f'trades_{db.replace(".db","")}_{m0[:7]}.json','w'),ensure_ascii=False)

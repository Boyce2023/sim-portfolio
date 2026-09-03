#!/usr/bin/env python3
"""B2(三日基石版) 2026-09-03 Buwen要求: 买卖动作同B(当日触板买/次日开盘卖), 选板依据看前两天。
四个基石(全部PIT, 只用T-2/T-1及T日开盘前可知信息):
  S=板块延续: T日板所属行业在T-1或T-2出过涨停(≥1)  [ind_map 2025行业映射]
  M=情绪基石: T-2板→T-1开盘溢价 与 T-1板→T日开盘溢价 的均值<=0 → T日不开仓
  A=换手自适应: 前两日B样本里 低换手组(<3%) vs 高换手组(>=3%) 次日溢价谁高, T日就按谁排序(asc/desc)
  H=高度延续: 前两日最高连板未升(T-1最高板<T-2最高板) → T日只做首板
用法: python3 engine_b2_3day.py univ202601.db 2026-01-01 2026-01-31 [flags:SMAH子集]"""
import sys,sqlite3,json,collections,statistics as st
B='/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban/'
sys.path.insert(0,B)
from strategy_b2 import PARAMS_B2 as P
from engine import lim_pct,load
from engine_b2 import build
IND=json.load(open(B+'ind_map.json'))
def ind(code): return IND.get(code[-6:],'?')
def fee(a,sell): return max(a*P['comm'],P['comm_min'])+a*P['transfer']+(a*P['stamp'] if sell else 0)
def run(db,m0,m1,flags='SMAH',verbose=False):
    by,sig,mood=build(db,m0,m1)                       # sig[d]=list of {code,buy(lim),sell(next open),turn,streak,mc,...}
    # 全部交易日(用by里日期)
    days=sorted({b[1] for bars in by.values() for b in bars if m0<=b[1]<=m1})
    # 每日涨停行业集合 & 最高连板(从sig+全池: build里mood只给家数, 行业/连板从sig近似(sig已过筛). 补: 用未过筛全池需重算, 这里用sig+连板)
    # 为了行业延续用"全池涨停"而非过筛池, 重算全池涨停:
    zt_by_day=collections.defaultdict(list)
    for code,bars in by.items():
        l0=lim_pct(code)
        for i,b in enumerate(bars):
            _,d,o,h,l,c,pc,turn,stt=b
            if not (m0<=d<=m1) or pc<=0: continue
            L=0.05 if stt else l0
            if abs(c-round(pc*(1+L),2))<0.005:
                s=1;j=i-1
                while j>=0 and bars[j][6]>0 and abs(bars[j][5]-round(bars[j][6]*(1+(0.05 if bars[j][8] else l0)),2))<0.005: s+=1;j-=1
                zt_by_day[d].append((code,s))
    nav=1.0; tr=[]; skipped=collections.Counter(); order_dir={}
    for i,d in enumerate(days):
        cand=sig.get(d,[])
        if not cand: continue
        d1=days[i-1] if i>=1 else None; d2=days[i-2] if i>=2 else None
        # M 情绪基石: 前两日B样本的次日溢价(gross)均值
        prem=[]
        for dd in (d1,d2):
            if dd: prem+=[ (t['sell']/t['buy']-1)*100 for t in sig.get(dd,[]) ]
        if 'M' in flags and d1 and d2 and prem and st.mean(prem)<=0: skipped['M情绪关']+=1; continue
        # A 换手自适应
        direction='asc'
        if 'A' in flags and d1 and d2:
            lo=[(t['sell']/t['buy']-1)*100 for dd in (d1,d2) for t in sig.get(dd,[]) if t['turn']<3]
            hi=[(t['sell']/t['buy']-1)*100 for dd in (d1,d2) for t in sig.get(dd,[]) if t['turn']>=3]
            if lo and hi and st.mean(hi)>st.mean(lo): direction='desc'
        order_dir[d]=direction
        # H 高度延续
        only_first=False
        if 'H' in flags and d1 and d2:
            mx1=max([s for _,s in zt_by_day.get(d1,[])] or [0]); mx2=max([s for _,s in zt_by_day.get(d2,[])] or [0])
            if mx1<mx2: only_first=True
        # S 板块延续
        recent_inds=set()
        for dd in (d1,d2):
            for code,_ in zt_by_day.get(dd,[]): recent_inds.add(ind(code))
        pool=[]
        for c in cand:
            if only_first and c['streak']>1: continue
            if 'S' in flags and d1 and d2 and ind(c['code']) not in recent_inds: continue
            pool.append(c)
        if not pool: skipped['无合格板']+=1; continue
        pool.sort(key=lambda x:x['turn'],reverse=(direction=='desc'))
        pick=pool[:P['max_positions']]
        cap=nav*P['capital']/len(pick); day=0.0
        for c in pick:
            sh=int(cap/(c['buy']*(1+P['slip_buy']))/100)*100
            if sh<=0: continue
            ba=sh*c['buy']*(1+P['slip_buy']); sa=sh*c['sell']*(1-P['slip_sell'])
            net=(sa-ba-fee(ba,False)-fee(sa,True))/cap; day+=net/len(pick)
            tr.append(dict(code=c['code'],date=d,net=net*100,gross=(c['sell']/c['buy']-1)*100,turn=c['turn'],streak=c['streak'],mc=c['mc']/1e8,dir=direction,ind=ind(c['code'])))
        nav*=(1+day)
    return nav,tr,dict(skipped),order_dir
if __name__=='__main__':
    db,m0,m1=sys.argv[1:4]; flags=sys.argv[4] if len(sys.argv)>4 else 'SMAH'
    nav,tr,sk,od=run(db,m0,m1,flags)
    nets=[t['net'] for t in tr]; w=sum(1 for x in nets if x>0)/len(nets)*100 if nets else 0
    ndesc=sum(1 for v in od.values() if v=='desc')
    print(f"B2[{flags or '-'}] {m0[:7]}: NAV={nav:.4f} {(nav-1)*100:+.1f}% 笔数{len(tr)} 胜率{w:.0f}% 均{st.mean(nets) if nets else 0:+.2f}% | desc日{ndesc}/{len(od)} | 跳过{sk}")
    json.dump(dict(nav=nav,trades=tr,skipped=sk,order_dir=od),open(f'/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-09-03-b2-3day/b2_{flags or "none"}_{m0[:7]}.json','w'),ensure_ascii=False)

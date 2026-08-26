#!/usr/bin/env python3
"""2026年1月样本外 v3 — 修复v2的致命出场bug
⛔v2的bug: 出场检查里 `if i is None: continue` —— 某只票在某日数据缺失/停牌时,
   直接跳过出场判定,该股就永久逃过出场规则一路持有到月末。
   实例: sh.600916 在01-22收跌-1.30%,按规则B"第一个下跌日出"当天就该出场,
        但回测让它持有到01-30赚+64.52%; sz.002155 停牌3天(换手0/涨幅0)期间无法触发出场,
        复牌后连拉5个涨停被全部计入收益 = 用了"知道它会复牌大涨"的未来信息。
   这就是v2跑出+91%/+107%的全部来源,与数据脏无关。
修法: ①持仓每日必须有明确判定,数据缺失=按停牌处理,用最后可得价强制平仓
     ②逐只独立出场(v2已修)
     ③停牌股直接排除出信号池(买入日必须有正常成交)
"""
import sqlite3,json,statistics
from collections import defaultdict
BASE='/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban'
con=sqlite3.connect(f'{BASE}/univ202601.db')
STAMP=0.0005; COMM=0.0003; SLIP=0.003
def lim_pct(c):
    b=c.split('.')[1]
    if b.startswith(('30','68')): return 0.20
    if b.startswith(('8','4','92')): return 0.30
    return 0.10

rows=con.execute("select code,date,open,high,low,close,preclose,turn,isST from k where preclose>0 order by code,date").fetchall()
bycode=defaultdict(list); alld=set()
for r in rows: bycode[r[0]].append(r); alld.add(r[1])
idx={c:{b[1]:i for i,b in enumerate(bars)} for c,bars in bycode.items()}
TD=sorted(d for d in alld if '2026-01-01'<=d<='2026-02-10')

sigs=defaultdict(list)
for code,bars in bycode.items():
    lp0=lim_pct(code)
    for i,b in enumerate(bars):
        _,d,o,h,l,c,pc,turn,st=b
        if not ('2026-01-01'<=d<='2026-01-31'): continue
        if c<2.0 or not turn or turn<=0.3: continue      # 剔除异常低价+停牌/极低流动性
        lp=0.05 if st else lp0
        lim=round(pc*(1+lp),2)
        if abs(c-lim)>=0.005: continue
        if abs(o-lim)<0.005 and abs(l-lim)<0.005: continue
        streak=1; j=i-1
        while j>=0:
            pb=bars[j]; lpj=0.05 if pb[8] else lp0
            if pb[6]>0 and abs(pb[5]-round(pb[6]*(1+lpj),2))<0.005: streak+=1; j-=1
            else: break
        k=max(0,i-20); g20=(c/bars[k][5]-1)*100 if bars[k][5]>0 else None
        if i+1>=len(bars): continue
        nb=bars[i+1]
        if not nb[7] or nb[7]<=0.3: continue              # 买入日必须能成交
        buy=nb[2]
        if buy<=0: continue
        gap1=(buy/c-1)*100
        if gap1<=0 and streak<=3 and g20 is not None and g20>=50:
            sigs[nb[1]].append({'code':code,'buy':buy,'gap1':gap1,'g20':g20,'rank':(gap1,-g20)})

def run(mode,maxn=3):
    nav=1.0; hold=[]; log=[]; tr=[]
    for d in TD:
        if hold:
            still=[]
            for h in hold:
                i=idx[h['code']].get(d)
                if i is None:
                    # ⛔数据缺失=停牌,不许静默跳过。用最后可得收盘价强制平仓
                    bars=bycode[h['code']]
                    last=[b for b in bars if b[1]<d]
                    px=last[-1][5] if last else h['buy']
                    g=px/h['buy']-1
                    net=(1+g)*(1-SLIP-COMM)*(1-SLIP-COMM-STAMP)-1
                    nav*=(1+net/len(hold)); tr.append({'code':h['code'],'net':net*100,'why':'停牌强平'})
                    continue
                b=bycode[h['code']][i]
                if d<=h['buy_date']: still.append(h); continue   # T+1
                lp=0.05 if b[8] else lim_pct(h['code'])
                is_lim=abs(b[5]-round(b[6]*(1+lp),2))<0.005
                is_up=b[5]>b[6]
                sell=(not is_lim) if mode=='A' else (not is_up)
                if sell:
                    g=b[5]/h['buy']-1
                    net=(1+g)*(1-SLIP-COMM)*(1-SLIP-COMM-STAMP)-1
                    nav*=(1+net/len(hold))
                    tr.append({'code':h['code'],'buy_date':h['buy_date'],'sell_date':d,
                               'gross':g*100,'net':net*100,'why':mode})
                else: still.append(h)
            if len(still)!=len(hold):
                log.append((d,'SELL',len(hold)-len(still),nav))
            hold=still
        if not hold and d in sigs and d<='2026-01-30':
            cand=sorted(sigs[d],key=lambda x:x['rank'])[:maxn]
            if cand:
                for c in cand: c['buy_date']=d
                hold=cand; log.append((d,'BUY',len(cand),nav))
    if hold:
        d=TD[-1]
        for h in hold:
            i=idx[h['code']].get(d)
            px=bycode[h['code']][i][5] if i is not None else h['buy']
            g=px/h['buy']-1
            net=(1+g)*(1-SLIP-COMM)*(1-SLIP-COMM-STAMP)-1
            nav*=(1+net/len(hold)); tr.append({'code':h['code'],'net':net*100,'why':'月末'})
        log.append((d,'SELL(月末)',len(hold),nav))
    return nav,log,tr

for m,name in [('A','第一个非涨停日出'),('B','第一个下跌日出')]:
    nav,log,tr=run(m)
    print('='*72); print(f'规则{m}: {name}'); print('='*72)
    for d,act,n,v in log: print(f'  {d} {act:<12} {n}只  NAV {v:.4f}')
    w=[t for t in tr if t.get('net',0)>0]
    print(f'\n  最终NAV {nav:.4f} → 月收益 {(nav-1)*100:+.2f}%')
    print(f'  交易{len(tr)}笔 胜率{len(w)/max(len(tr),1)*100:.1f}% 均净{statistics.mean([t["net"] for t in tr]) if tr else 0:+.2f}%\n')

# 2026-09-03 FIX: 前复权价下 round(pc*(1+L),2) 与实际涨停价差1-2分, 原0.005容差漏掉约75%的板. 改为价差<=0.02且比例>=L-0.004.
def _islim(x,pc,L): return x>=round(pc*(1+L),2)-0.02 and (x/pc-1)>=L-0.004
#!/usr/bin/env python3
"""通用回测引擎 — 参数全部从strategy_v2.PARAMS读,引擎内无硬编码参数"""
import sqlite3,sys
from collections import defaultdict
sys.path.insert(0,'/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban')
from strategy_v2 import PARAMS as P

def lim_pct(c):
    b=c.split('.')[1]
    if b.startswith(('30','68')): return 0.20
    if b.startswith(('8','4','92')): return 0.30
    return 0.10

def load(db):
    con=sqlite3.connect(db)
    rows=con.execute("select code,date,open,high,low,close,preclose,turn,isST from k where preclose>0 order by code,date").fetchall()
    by=defaultdict(list)
    for r in rows: by[r[0]].append(r)
    return by

def signals(by,m0,m1):
    sig=defaultdict(list)
    for code,bars in by.items():
        l0=lim_pct(code)
        for i,b in enumerate(bars):
            _,d,o,h,l,c,pc,turn,st=b
            if not (m0<=d<=m1): continue
            if c<P['min_price'] or not turn or turn<=P['min_turn']: continue
            L=0.05 if st else l0
            lim=round(pc*(1+L),2)
            if not _islim(c,pc,L): continue
            if _islim(o,pc,L) and _islim(l,pc,L): continue
            s=1;j=i-1
            while j>=0:
                pb=bars[j];Lj=0.05 if pb[8] else l0
                if pb[6]>0 and _islim(pb[5],pb[6],Lj): s+=1;j-=1
                else: break
            k=max(0,i-20); g20=(c/bars[k][5]-1)*100 if bars[k][5]>0 else None
            if i+1>=len(bars): continue
            nb=bars[i+1]
            if not nb[7] or nb[7]<=P['min_turn'] or nb[2]<=0: continue
            gap=(nb[2]/c-1)*100
            if gap<=P['gap_max'] and s<=P['streak_max'] and g20 is not None and g20>=P['gain20_min']:
                sig[nb[1]].append({'code':code,'buy':nb[2],'gap':gap,'g20':g20,'streak':s,'rank':(gap,-g20)})
    return sig

def run(by,sig,TD,last_buy_date):
    idx={c:{b[1]:i for i,b in enumerate(bars)} for c,bars in by.items()}
    nav=1.0; hold=[]; tr=[]; log=[]
    # ⛔2026-08-25 按中金财富真实费率重写: 补上过户费(之前漏)+最低5元佣金(之前漏)
    def fee(amount, is_sell):
        c=max(amount*P['comm'], P['comm_min'])          # 佣金,最低5元
        t=amount*P['transfer']                           # 过户费,双边
        s=amount*P['stamp'] if is_sell else 0.0          # 印花税,卖出单边
        return c+t+s
    def net_ret(buy_px, sell_px, cap_per_stock):
        sh=int(cap_per_stock/(buy_px*(1+P['slip']))/100)*100   # 100股整数倍
        if sh<=0: return 0.0
        buy_amt=sh*buy_px*(1+P['slip'])                  # 买入含滑点
        sell_amt=sh*sell_px*(1-P['slip'])                # 卖出含滑点
        pnl=sell_amt-buy_amt-fee(buy_amt,False)-fee(sell_amt,True)
        return pnl/cap_per_stock
    for d in TD:
        if hold:
            still=[]
            for h in hold:
                i=idx[h['code']].get(d)
                if i is None:
                    bars=by[h['code']]; last=[b for b in bars if b[1]<d]
                    px=last[-1][5] if last else h['buy']
                    net=net_ret(h['buy'],px,nav*P['capital']/len(hold))
                    nav*=(1+net/len(hold)); tr.append({'code':h['code'],'net':net*100,'gross':(px/h['buy']-1)*100,'why':'停牌强平'}); continue
                b=by[h['code']][i]
                if d<=h['buy_date']: still.append(h); continue
                lp=0.05 if b[8] else lim_pct(h['code'])
                is_lim=_islim(b[5],b[6],lp)
                # ⛔2026-08-25修: 原用收盘价判止损,而"跌破6%的日子必然不是涨停日",
                # 断板规则在同一天已经触发 → 止损只是换了个标签,没提前任何一天,NAV完全不变。
                # 正确做法: 用盘中最低价判定,当日盘中触及止损价即以该价成交(模拟盘中挂单)。
                # ⛔2026-08-25 用户加的可实现性约束: 一字跌停时我挂单也成交不了,
                # 那个止损价是假的。三种情况分开:
                #   ①一字跌停(开=高=低=跌停价) → 无法成交,继续持有到次日
                #   ②开盘已低于止损价但非一字 → 能成交,但只能按开盘价(不是止损价)
                #   ③盘中才跌破止损价 → 能成交,按止损价
                stop_px=h['buy']*(1-P['stop_loss'])
                dn_lim=round(b[6]*(1-lp),2)                       # 当日跌停价
                yizi_down = (abs(b[2]-dn_lim)<0.005 and abs(b[3]-dn_lim)<0.005
                             and abs(b[4]-dn_lim)<0.005)          # 开=高=低=跌停 → 一字跌停
                hit=False; exit_px=None
                if not yizi_down and b[4] <= stop_px:
                    hit=True
                    exit_px = min(b[2], stop_px)                  # 开盘已破则按开盘价,否则止损价
                if yizi_down:
                    still.append(h); continue                     # 一字跌停无法成交,持有到次日
                if hit or (not is_lim):
                    if exit_px is None: exit_px = b[5]            # 断板按收盘价
                    net=net_ret(h['buy'],exit_px,nav*P['capital']/len(hold))
                    nav*=(1+net/len(hold))
                    tr.append({'code':h['code'],'buy_date':h['buy_date'],'sell_date':d,
                        'gross':(exit_px/h['buy']-1)*100,'net':net*100,'why':'止损' if hit else '断板'})
                else: still.append(h)
            if len(still)!=len(hold): log.append((d,'SELL',len(hold)-len(still),nav))
            hold=still
        if not hold and d in sig and d<=last_buy_date:
            cand=sorted(sig[d],key=lambda x:x['rank'])[:P['max_positions']]
            if cand:
                for c in cand: c['buy_date']=d
                hold=cand; log.append((d,'BUY',len(cand),nav))
    if hold:
        d=TD[-1]
        for h in hold:
            i=idx[h['code']].get(d)
            px=by[h['code']][i][5] if i is not None else h['buy']
            net=net_ret(h['buy'],px,nav*P['capital']/len(hold))
            nav*=(1+net/len(hold)); tr.append({'code':h['code'],'net':net*100,'gross':(px/h['buy']-1)*100,'why':'月末'})
        log.append((d,'SELL(月末)',len(hold),nav))
    return nav,tr,log

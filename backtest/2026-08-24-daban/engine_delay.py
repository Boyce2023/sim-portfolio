#!/usr/bin/env python3
"""引擎变体: 断板后延迟N日出场 (单变量测试, 其余规则与engine.py完全一致)
delay=0 → 断板当日收盘出(=现行v2.2)
delay=1 → 断板当日不走, 次日收盘出
⛔止损照常逐日生效(含一字跌停约束), 延迟期间若触及止损仍立即出
"""
import sys
from collections import defaultdict
sys.path.insert(0,'/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban')
from strategy_v2 import PARAMS as P
from engine import lim_pct,load,signals

def run_delay(by,sig,TD,last_buy_date,delay=0):
    idx={c:{b[1]:i for i,b in enumerate(bars)} for c,bars in by.items()}
    nav=1.0; hold=[]; tr=[]; log=[]
    def fee(a,sell):
        return max(a*P['comm'],P['comm_min'])+a*P['transfer']+(a*P['stamp'] if sell else 0)
    def net_ret(b,s,cap):
        sh=int(cap/(b*(1+P['slip']))/100)*100
        if sh<=0: return 0.0
        ba=sh*b*(1+P['slip']); sa=sh*s*(1-P['slip'])
        return (sa-ba-fee(ba,False)-fee(sa,True))/cap
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
                is_lim=abs(b[5]-round(b[6]*(1+lp),2))<0.005
                stop_px=h['buy']*(1-P['stop_loss'])
                dn=round(b[6]*(1-lp),2)
                yizi=(abs(b[2]-dn)<0.005 and abs(b[3]-dn)<0.005 and abs(b[4]-dn)<0.005)
                hit=(not yizi) and b[4]<=stop_px
                if yizi: still.append(h); continue
                # ⭐延迟逻辑: 断板不立即出,记录已断板天数
                if hit:
                    net=net_ret(h['buy'],min(b[2],stop_px),nav*P['capital']/len(hold))
                    nav*=(1+net/len(hold))
                    tr.append({'code':h['code'],'buy_date':h['buy_date'],'sell_date':d,
                        'gross':(min(b[2],stop_px)/h['buy']-1)*100,'net':net*100,'why':'止损'})
                    continue
                if not is_lim:
                    h['broke']=h.get('broke',0)+1
                    if h['broke']>delay:
                        net=net_ret(h['buy'],b[5],nav*P['capital']/len(hold))
                        nav*=(1+net/len(hold))
                        tr.append({'code':h['code'],'buy_date':h['buy_date'],'sell_date':d,
                            'gross':(b[5]/h['buy']-1)*100,'net':net*100,'why':f'断板+{delay}日'})
                        continue
                still.append(h)
            if len(still)!=len(hold): log.append((d,'SELL',len(hold)-len(still),nav))
            hold=still
        if not hold and d in sig and d<=last_buy_date:
            cand=sorted(sig[d],key=lambda x:x['rank'])[:P['max_positions']]
            if cand:
                for c in cand: c['buy_date']=d; c['broke']=0
                hold=cand; log.append((d,'BUY',len(cand),nav))
    if hold:
        d=TD[-1]
        for h in hold:
            i=idx[h['code']].get(d)
            px=by[h['code']][i][5] if i is not None else h['buy']
            net=net_ret(h['buy'],px,nav*P['capital']/len(hold))
            nav*=(1+net/len(hold)); tr.append({'code':h['code'],'net':net*100,'gross':(px/h['buy']-1)*100,'why':'月末'})
    return nav,tr,log

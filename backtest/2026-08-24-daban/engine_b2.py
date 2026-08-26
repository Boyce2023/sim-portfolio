#!/usr/bin/env python3
"""B2引擎: 冲板买入(涨停价)→次日开盘卖出。含市场情绪门。"""
import sqlite3,sys
from collections import defaultdict
sys.path.insert(0,'/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban')
from strategy_b2 import PARAMS_B2 as P
from engine import lim_pct,load

def build(db,m0,m1):
    """返回 (信号dict, 每日全市场涨停家数dict)"""
    by=load(db)
    con=sqlite3.connect(db)
    cap={}
    for code,turn,amt in con.execute("select code,turn,amount from k where date>=? and turn>0.5 group by code",(m0,)):
        if turn and amt: cap[code]=amt/(turn/100)
    sig=defaultdict(list); mood=defaultdict(int)
    for code,bars in by.items():
        l0=lim_pct(code)
        for i,b in enumerate(bars):
            _,d,o,h,l,c,pc,turn,st=b
            if not (m0<=d<=m1): continue
            L=0.05 if st else l0
            lim=round(pc*(1+L),2)
            if abs(c-lim)>=0.005: continue
            mood[d]+=1                                   # 全市场涨停家数(含一字/ST)
            if P['exclude_st'] and st: continue
            if P['exclude_yizi'] and abs(o-lim)<0.005 and abs(l-lim)<0.005: continue
            if not turn or turn>P['turn_max'] or turn<P['turn_min']: continue
            s=1;j=i-1
            while j>=0:
                pb=bars[j];Lj=0.05 if pb[8] else l0
                if pb[6]>0 and abs(pb[5]-round(pb[6]*(1+Lj),2))<0.005: s+=1;j-=1
                else: break
            if not (P['streak_min']<=s<=P['streak_max']): continue
            k=max(0,i-20); g20=(c/bars[k][5]-1)*100 if bars[k][5]>0 else -999
            if g20<P['gain20_min']: continue
            mc=cap.get(code)
            if mc is None or mc<P['mktcap_min']: continue
            if P['mktcap_max'] and mc>P['mktcap_max']: continue
            if i+1>=len(bars): continue
            nb=bars[i+1]
            if nb[2]<=0: continue
            sig[d].append({'code':code,'buy':lim,'sell':nb[2],'sell_date':nb[1],
                           'turn':turn,'g20':g20,'streak':s,'mc':mc,'rank':(turn,)})
    return by,sig,mood

def run_b2(sig,mood,use_mood=True):
    nav=1.0; tr=[]
    def fee(a,sell): return max(a*P['comm'],P['comm_min'])+a*P['transfer']+(a*P['stamp'] if sell else 0)
    for d in sorted(sig):
        if use_mood and mood.get(d,0)<P['mood_min_limitups']: continue
        cand=sorted(sig[d],key=lambda x:x['rank'])[:P['max_positions']]
        if not cand: continue
        cap=nav*P['capital']/len(cand)
        day=0.0
        for c in cand:
            sh=int(cap/(c['buy']*(1+P['slip_buy']))/100)*100
            if sh<=0: continue
            ba=sh*c['buy']*(1+P['slip_buy']); sa=sh*c['sell']*(1-P['slip_sell'])
            net=(sa-ba-fee(ba,False)-fee(sa,True))/cap
            day+=net/len(cand)
            tr.append({'code':c['code'],'date':d,'net':net*100,
                       'gross':(c['sell']/c['buy']-1)*100,'turn':c['turn'],'mc':c['mc']/1e8})
        nav*=(1+day)
    return nav,tr

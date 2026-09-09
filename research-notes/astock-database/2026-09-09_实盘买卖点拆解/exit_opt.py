# -*- coding: utf-8 -*-
"""Buwen实盘买点 × 卖出规则网格。规则只用t及之前信息; T+1不可当日卖; 双边费12.3bp。"""
import csv,json,sqlite3,itertools,numpy as np,pandas as pd
from collections import defaultdict,deque
con=sqlite3.connect('/tmp/dhbr/exit_bars.db')
K=pd.read_sql("select code,date,open,high,low,close from k",con); K['date']=pd.to_datetime(K['date']); K=K.sort_values(['code','date'])
bars={c:g.reset_index(drop=True) for c,g in K.groupby('code')}
FEE=0.00123
def load_aug():
    B=[(r['date'],r['code'],r['name'],int(float(r['qty'])),float(r['price'])) for r in csv.DictReader(open('/Users/huaichuaibeimeng/claude-projects/trading-journal/data/buys_202608.csv',encoding='utf-8-sig'))]
    S=[(r['date'],r['code'],r['name'],int(float(r['qty'])),float(r['price'])) for r in csv.DictReader(open('/Users/huaichuaibeimeng/claude-projects/trading-journal/data/sells_202608.csv',encoding='utf-8-sig'))]
    f=lambda d: pd.Timestamp(f"{d[:4]}-{d[4:6]}-{d[6:]}")
    return [(f(d),c,n,q,p) for d,c,n,q,p in B],[(f(d),c,n,q,p) for d,c,n,q,p in S]
def load_aprmay():
    R=json.load(open('/tmp/dhbr/real_trades_coded.json'))
    B=[(pd.Timestamp(d),c,n,q,p) for d,a,n,c,q,p in R if a=='买']; S=[(pd.Timestamp(d),c,n,q,p) for d,a,n,c,q,p in R if a=='卖']
    return B,S
def fifo(B,S):
    lots=defaultdict(deque); rt=[]
    ev=sorted([(d,0,c,n,q,p) for d,c,n,q,p in B]+[(d,1,c,n,q,p) for d,c,n,q,p in S],key=lambda x:(x[0],x[1]))
    for d,kind,c,n,q,p in ev:
        if kind==0: lots[c].append([d,p,q,n])
        else:
            rem=q
            while rem>0 and lots[c]:
                l=lots[c][0]; take=min(rem,l[2]); rt.append(dict(code=c,name=n,buy=l[0],bp=l[1],sell=d,sp=p,q=take)); l[2]-=take; rem-=take
                if l[2]==0: lots[c].popleft()
    openl=[dict(code=c,name=l[3],buy=l[0],bp=l[1],q=l[2]) for c,dq in lots.items() for l in dq]
    return rt,openl
def sim(code,d0,p0,SL,TP,N,TS,mode='close'):
    """返回(ret%, hold_days, exit_reason, exit_date, open_flag)"""
    g=bars.get(code)
    if g is None: return None
    after=g[g.date>d0].reset_index(drop=True)
    if len(after)==0: return None
    peak=p0
    for t,r in after.iterrows():
        day=t+1
        if mode=='close':
            peak=max(peak,r.close)
            if SL is not None and r.close<=p0*(1-SL): return ((r.close/p0-1)*100-FEE*100,day,'SL',r.date,False)
            if TS is not None and r.close<=peak*(1-TS) and peak>p0: return ((r.close/p0-1)*100-FEE*100,day,'TS',r.date,False)
            if TP is not None and r.close>=p0*(1+TP): return ((r.close/p0-1)*100-FEE*100,day,'TP',r.date,False)
            if N is not None and day>=N: return ((r.close/p0-1)*100-FEE*100,day,'N',r.date,False)
        else:  # intraday touch: 止损按低价触及、止盈按高价触及, 以该价位成交(跳空则按开盘)
            if SL is not None and r.low<=p0*(1-SL):
                px=min(r.open,p0*(1-SL)); return ((px/p0-1)*100-FEE*100,day,'SL',r.date,False)
            if TS is not None and peak>p0 and r.low<=peak*(1-TS):
                px=min(r.open,peak*(1-TS)); return ((px/p0-1)*100-FEE*100,day,'TS',r.date,False)
            if TP is not None and r.high>=p0*(1+TP):
                px=max(r.open,p0*(1+TP)); return ((px/p0-1)*100-FEE*100,day,'TP',r.date,False)
            peak=max(peak,r.high)
            if N is not None and day>=N: return ((r.close/p0-1)*100-FEE*100,day,'N',r.date,False)
    r=after.iloc[-1]; return ((r.close/p0-1)*100-FEE*100,len(after),'OPEN',r.date,True)
SLs=[None,0.03,0.05,0.07,0.10,0.15]; TPs=[None,0.05,0.08,0.10,0.15,0.20,0.30]; Ns=[None,3,5,10,20]; TSs=[None,0.05,0.08,0.10,0.15]
def run_panel(name,B,S,mode):
    rt,openl=fifo(B,S)
    # 基准: 他的实际卖点(FIFO配对)+未卖lot按09-08收盘
    base=[]
    for r in rt: base.append(((r['sp']/r['bp']-1)*100-FEE*100,(r['sell']-r['buy']).days,r['q']*r['bp']))
    for o in openl:
        g=bars.get(o['code']); 
        if g is None: continue
        base.append(((g.close.iloc[-1]/o['bp']-1)*100-FEE*100,(g.date.iloc[-1]-o['buy']).days,o['q']*o['bp']))
    ba=np.array(base); w=ba[:,2]/ba[:,2].sum()
    print(f"\n════ {name} · 模式={mode} · 买入{len(B)}笔 ════")
    print(f"基准(你的实际卖点, 未卖按最新收盘): 等权均值{ba[:,0].mean():+.2f}% 中位{np.median(ba[:,0]):+.2f}% 金额加权{(ba[:,0]*w).sum():+.2f}% 胜率{(ba[:,0]>0).mean()*100:.0f}% 均持{ba[:,1].mean():.1f}天 n={len(ba)}")
    lots=[(d,c,n,q,p) for d,c,n,q,p in B if c in bars]
    res=[]
    for SL,TP,N,TS in itertools.product(SLs,TPs,Ns,TSs):
        if SL is None and TP is None and N is None and TS is None: continue
        out=[sim(c,d,p,SL,TP,N,TS,mode) for d,c,n,q,p in lots]; out=[(o,q*p) for o,(d,c,n,q,p) in zip(out,lots) if o]
        r=np.array([o[0][0] for o in out]); h=np.array([o[0][1] for o in out]); cap=np.array([o[1] for o in out]); wc=cap/cap.sum()
        opn=np.mean([o[0][4] for o in out])
        res.append(dict(SL=SL,TP=TP,N=N,TS=TS,mean=r.mean(),med=np.median(r),wmean=(r*wc).sum(),win=(r>0).mean()*100,hold=h.mean(),
                        pf=(r[r>0].sum()/max(1e-9,-r[r<0].sum())) if (r<0).any() else np.inf,worst=r.min(),open=opn*100,n=len(r)))
    R=pd.DataFrame(res)
    def fmt(x): return "无" if x is None else (f"{x*100:.0f}%" if isinstance(x,float) else f"{x}日")
    for key,lab in [('mean','等权均值'),('wmean','金额加权')]:
        print(f"\n  按{lab}排序 前8:")
        print(f"  {'止损':<5}{'止盈':<5}{'时限':<5}{'移动止损':<7}{'等权%':>7}{'加权%':>7}{'胜率':>5}{'均持天':>6}{'盈亏比':>6}{'最差%':>7}{'未平%':>5}")
        for _,x in R.sort_values(key,ascending=False).head(8).iterrows():
            print(f"  {fmt(x.SL):<5}{fmt(x.TP):<5}{fmt(x.N):<5}{fmt(x.TS):<7}{x['mean']:>+7.2f}{x.wmean:>+7.2f}{x.win:>5.0f}{x.hold:>6.1f}{x.pf:>6.2f}{x.worst:>+7.1f}{x.open:>5.0f}")
    print("\n  单规则敏感性(其余不设):")
    for lab,col,vals in [('止损',"SL",SLs[1:]),('止盈',"TP",TPs[1:]),('时限',"N",Ns[1:]),('移动止损',"TS",TSs[1:])]:
        row=[]
        for v in vals:
            q=R[(R[col]==v)&(R[[c for c in ['SL','TP','N','TS'] if c!=col]].isna().all(axis=1))]
            if len(q): x=q.iloc[0]; row.append(f"{fmt(v)}:{x['mean']:+.1f}%/{x.win:.0f}%/{x.hold:.0f}天")
        print(f"   {lab}: "+"  ".join(row))
    R['panel']=name; R['mode']=mode; return R,ba
allR=[]
for pname,(B,S) in [('8月(96笔买入)',load_aug()),('4到5月(58笔买入)',load_aprmay())]:
    for mode in ['close','touch']:
        R,ba=run_panel(pname,B,S,mode); allR.append(R)
pd.concat(allR).to_pickle('/tmp/dhbr/exit_grid.pkl'); print("\n网格已存 exit_grid.pkl")

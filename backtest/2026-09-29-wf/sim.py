#!/opt/homebrew/bin/python3.13
"""逐日模拟交易(2024-10-08 .. 数据末日), 每天:
  收盘后: 用当天分数排序 → 决定明天买什么; 检查持仓的卖出条件 → 明天开盘卖
  次日开盘: 先卖后买; 开盘即涨停买不进(跳过), 开盘一字跌停卖不出(顺延)
 规则: 最多 10 个仓位, 每仓 = 当时净值/10; 每天最多新开 2 个
 卖出: ①收盘较成本 -8% ②持有满 10 个交易日 ③浮盈曾达 +12% 后, 收盘从最高收盘回撤 7%
 费用: 买 0.13%(佣金+滑点), 卖 0.18%(佣金+印花税+滑点)
 版本 C 额外的自我校准: 跟踪自己最近 20 天"前五名推荐"已揭晓的实际超额, 为负则每天只开 1 个, 低于 -2% 则暂停开新仓"""
import pandas as pd, numpy as np, sys, json
F=pd.read_parquet('feat.parquet',columns=['date','code','open','close','high','low','adjf','zt_px','dt_px','prevc','fcap','yxu' if False else 'y','dH','r1','r5','r20','box20','t20','tr1','zt20','mem_y'])
S=pd.read_parquet('scores.parquet')
F=F.merge(S,on=['date','code'],how='left')
F['ao']=F.open*F.adjf; F['ac']=F.close*F.adjf
dates=sorted(F.date.unique()); D0=pd.Timestamp('2024-10-08')
tdays=[d for d in dates if d>=D0]
byday={d:g.set_index('code') for d,g in F[F.date>=pd.Timestamp('2024-09-20')].groupby('date')}
yx=F.dropna(subset=['sC']).copy(); yx['yx']=yx.y-yx.groupby('date').y.transform('mean')
def run(key,adaptive=False,rand=False,seed=0,N=10,K=2,SL=0.08,HOLD=10,TP=0.12,TR=0.07,d_from=None,d_to=None,sched=None,selfgate=False):
    rng=np.random.default_rng(seed)
    days=[d for d in tdays if (d_from is None or d>=d_from) and (d_to is None or d<d_to)]
    cash=1.0; pos={}; trades=[]; eq=[]; pending_buy=[]; pending_sell=set(); gate_hist=[]; paper=[]
    for i,d in enumerate(days):
        day=byday[d]
        if sched is not None:
            SL,HOLD,TP,TR=sched.get((d.year,d.month),(SL,HOLD,TP,TR))
        # 1) 开盘执行: 卖
        for c in list(pending_sell):
            if c not in day.index: continue
            r=day.loc[c]
            if r.open<=r.dt_px+0.001 and r.high<=r.dt_px+0.001: continue   # 一字跌停卖不出
            p=pos.pop(c); px=r.open*r.adjf
            val=p['sh']*px*(1-0.0018); cash+=val
            trades.append(dict(ver=key,code=c,buy_d=p['d'],sell_d=d,buy_px=p['px'],sell_px=px,ret=px/p['px']*(1-0.0018)/(1+0.0013)-1,
                               days=p['n'],mfe=p['peak']/p['cost']-1,mae=p.get('trough',p['cost'])/p['cost']-1,why=p['why_sell'],score=p['score'],rank=p['rank'],**p['feat']))
            pending_sell.discard(c)
        # 2) 开盘执行: 买
        nav=cash+sum(p['sh']*byday[d].loc[c].ac if c in day.index else p['sh']*p['last'] for c,p in pos.items())
        for c,sc,rk,ft in pending_buy:
            if len(pos)>=N or c in pos or c not in day.index: continue
            r=day.loc[c]
            if r.open>=r.zt_px-0.001: continue                               # 开盘涨停买不进
            amt=min(nav/N,cash)
            if amt<nav/N*0.5: continue
            px=r.open*r.adjf; sh=amt/(1+0.0013)/px; cash-=amt
            pos[c]=dict(sh=sh,px=px*(1+0.0013)/(1+0.0013),cost=px,d=d,n=0,peak=px,last=px,why_sell='',score=sc,rank=rk,feat=ft)
        pending_buy=[]
        # 3) 收盘: 更新持仓, 决定明天卖什么
        for c,p in pos.items():
            if c not in day.index: continue
            r=day.loc[c]; p['n']+=1; p['last']=r.ac; p['peak']=max(p['peak'],r.ac); p['trough']=min(p.get('trough',p['cost']),r.ac)
            g=r.ac/p['cost']-1
            if g<=-SL: p['why_sell']='止损-8%'
            elif p['peak']/p['cost']-1>=TP and r.ac<=p['peak']*(1-TR): p['why_sell']='浮盈回撤'
            elif p['n']>=HOLD: p['why_sell']='到期10日'
            else: continue
            pending_sell.add(c)
        nav=cash+sum(p['sh']*(day.loc[c].ac if c in day.index else p['last']) for c,p in pos.items())
        eq.append((d,nav,len(pos)))
        # 4) 收盘: 选明天买的
        cand=day.dropna(subset=[key]) if not rand else day.dropna(subset=['sC'])
        cand=cand[(cand.close<cand.zt_px-0.011)]          # 今天已涨停的不追(次日大概率买不进/高开)
        k=K
        if adaptive:
            # 已揭晓的自己的推荐: dH < 今天
            j=[h for h in gate_hist if h[1]<d][-20:]
            if len(j)>=10:
                m=np.mean([h[2] for h in j])
                k=0 if m<-0.02 else (1 if m<0 else K)
        if selfgate:
            # 纸面战绩: 自己每天前两名推荐(不论是否真买)的实际收益, 只取已揭晓(dH<今天)的最近 10 笔
            j2=[h for h in paper if h[0]<d][-10:]
            if len(j2)>=10:
                m2=np.mean([h[1] for h in j2])
                k=min(k,0 if m2<-0.03 else (1 if m2<0 else K))
        top5=cand.nlargest(5,key) if not rand else cand.sample(min(5,len(cand)),random_state=int(rng.integers(1e9)))
        for c,r in top5.iterrows():
            if pd.notna(r.y): gate_hist.append((d,r.dH,r.y-day.y.mean()))
        for c,r in top5.head(2).iterrows():
            if pd.notna(r.y): paper.append((r.dH,r.y-0.0031))
        free=N-len(pos)+len(pending_sell)
        pick=top5.head(min(k,max(free,0)))
        for rk,(c,r) in enumerate(pick.iterrows()):
            if c in pos: continue
            pending_buy.append((c,float(r[key]) if not rand else np.nan,rk+1,dict(r1=r.r1,r5=r.r5,r20=r.r20,box20=r.box20,t20=r.t20,tr1=r.tr1,zt20=r.zt20,fcap=r.fcap)))
    E=pd.DataFrame(eq,columns=['date','nav','npos']); T=pd.DataFrame(trades)
    return E,T
if True:
    pass
GRID=[(sl,h,tp,tr) for sl in (0.06,0.08,0.10) for h in (5,10,15) for tp,tr in ((0.12,0.07),(0.20,0.10))]
def tune_schedule():
    sched={}; months=sorted({(d.year,d.month) for d in tdays})
    for ym in months:
        ms=min(d for d in tdays if (d.year,d.month)==ym); j=tdays.index(ms)
        if j<60: continue                                  # 历史不足 60 个交易日, 用默认参数
        a=tdays[max(0,j-126)]
        best=None
        for prm in GRID:
            E,_=run('sC',adaptive=True,selfgate=True,SL=prm[0],HOLD=prm[1],TP=prm[2],TR=prm[3],d_from=a,d_to=ms)
            v=E.nav.iloc[-1]
            if best is None or v>best[0]: best=(v,prm)
        sched[ym]=best[1]; print('  参数自调',ym,'选',best[1],'影子净值',round(best[0],3),flush=True)
    return sched
if __name__=='__main__':
    res={}
    for name,kw in [('A_不学习',dict(key='sA')),('B_每月重训',dict(key='sB')),('C_重训+记忆+自校准',dict(key='sC',adaptive=True)),
                    ('D_C+战绩闸门+卖出参数自调',dict(key='sC',adaptive=True,selfgate=True,sched='TUNE')),
                    ('R_随机对照',dict(key='sC',rand=True,seed=7))]:
        if kw.get('sched')=='TUNE':
            kw['sched']=tune_schedule(); json.dump({f'{a}-{b:02d}':v for (a,b),v in kw['sched'].items()},open('d_schedule.json','w'))
        E,T=run(**kw); res[name]=(E,T)
        E.to_csv(f'eq_{name[0]}.csv',index=False); T.to_csv(f'trades_{name[0]}.csv',index=False)
        print(name,'交易',len(T),'净值',round(E.nav.iloc[-1],3),flush=True)
    
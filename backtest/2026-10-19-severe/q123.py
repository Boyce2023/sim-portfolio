import json,pandas as pd,numpy as np
from dev import panel,BENCH,add_compound,add_window_max
A=add_window_max(add_compound(panel(BENCH['B'],start='2025-06-01')))
A['lim']=np.where(A.board.isin(['kcb','cyb']),0.2,0.1)
g=A.groupby('code')
# 涨停价下的窗口偏离: 当天若收在涨停能否触发
pc=g.adj_close.shift(1); pzt=pc*(1+A.lim)
best=None
for j in range(1,11):
    base=g.adj_close.shift(j); ib=A.groupby('code').ilvl.shift(j)
    v=(pzt/base-1)-(A.ilvl/ib-1)
    best=v if best is None else np.fmax(best,v)
A['m10_zt']=best
A['zt']=A.adj_close>=pzt*0.998
A.to_pickle('/private/tmp/claude-501/-Users-huaichuaibeimeng-claude-projects/0271364f-8cab-4319-af5d-5048f0719e12/scratchpad/devpanel.pkl')
P={c:d.reset_index(drop=True) for c,d in A.groupby('code')}
KR=json.load(open('kpl_severe_his.json'))['rows']
kpl=pd.DataFrame([{'code':r[0],'date':pd.Timestamp(r[18]),'rule':r[2]} for r in KR])
# ---------- Q1 ----------
F=pd.read_pickle('../2026-10-19-5ban-day23/events.pkl')
rows=[]
for _,e in F.iterrows():
    d=P.get(e.code); 
    if d is None: continue
    k=d.index[d.date==pd.Timestamp(e.d5)]
    if not len(k): rows.append({'code':e.code,'name':e['name'],'d5':e.d5,'note':'库里无五板日'}); continue
    i=int(k[0]); w=d.iloc[i:i+11]
    mx=w.m10.max(); first=w[w.m10>=1.0].date.min()
    kk=kpl[(kpl.code==e.code)&(kpl.date>=pd.Timestamp(e.d5)-pd.Timedelta(days=3))&(kpl.date<=w.date.max()+pd.Timedelta(days=3))]
    rows.append({'code':e.code,'name':e['name'],'d5':e.d5,'窗口天数':len(w),'五板日偏离':d.m10[i],'最大偏离':mx,'最大日':w.date[w.m10.idxmax()].date(),'首次破100%':first.date() if first==first else None,
                 '开盘啦记录':'/'.join(sorted(set(kk.rule))) })
Q1=pd.DataFrame(rows); Q1.to_pickle('q1.pkl')
# ---------- Q2 ----------
ev=[]
for c,d in P.items():
    stuck=(d.m10_zt>=1.0)&(d.m10<1.0)&(d.date>='2025-10-20')
    last=-99
    for i in np.where(stuck)[0]:
        if i-last<10: continue
        prior_trig=(d.m10.iloc[max(0,i-10):i]>=1.0).any()
        if prior_trig: continue
        last=i; base=d.adj_close[i]
        fut=d.iloc[i+1:i+31]
        if len(fut)==0: continue
        # 继续涨的天数: 之后连续收涨的天数; 到阶段高点: 之后30日内最高收盘出现在第几天
        up=0
        for x in fut.adj_close.values:
            prevc=base if up==0 else prev
            if x>prevc*1.0000001: up+=1; prev=x
            else: break
        pk=fut.adj_close.values.argmax()
        trig=fut.m10.ge(1.0).values
        ev.append({'code':c,'date':d.date[i],'当天涨幅':d.adj_close[i]/d.adj_close[i-1]-1,'当天偏离':d.m10[i],'当天涨停':bool(d.zt[i]),
                   '之后连涨天数':up,'到高点天数':int(pk)+1,'到高点收益':fut.adj_close.values[pk]/base-1,
                   '之后几天破100%':int(np.argmax(trig))+1 if trig.any() else None,
                   **{f'r{h}':(d.adj_close[i+h]/base-1 if i+h<len(d) else np.nan) for h in (1,3,5,10,20)},'看到天数':len(fut)})
Q2=pd.DataFrame(ev); Q2.to_pickle('q2.pkl')
print('Q1',len(Q1),'Q2',len(Q2))

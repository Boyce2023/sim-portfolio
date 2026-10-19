"""同一天多只五板只能做一只: 用当时可知的规则二选一(五板当天换手低者 / 流通市值大者), 对比随机(取平均)与事后最好最差; 再加'持仓期间不开新仓'约束"""
import pandas as pd, numpy as np
A=pd.read_pickle('/private/tmp/claude-501/-Users-huaichuaibeimeng-claude-projects/0271364f-8cab-4319-af5d-5048f0719e12/scratchpad/devpanel.pkl')
P={c:d.reset_index(drop=True) for c,d in A.groupby('code')}
T=pd.read_parquet('../../data/cn_hk_price_db/a_daily.parquet',columns=['date','ticker','turn'],filters=[('date','>=',pd.Timestamp('2026-06-25'))])
T['code']=T.ticker.str[:6]; TURN=T.set_index(['code','date']).turn
F=pd.read_pickle('../2026-10-19-5ban-day23/events.pkl')
def trig_price(d,t,L):
    best=np.inf
    for j in range(1,11):
        if t-j<0: break
        best=min(best,d.adj_close[t-j]*(1+L+(d.ilvl[t]/d.ilvl[t-j]-1)))
    return best
rows=[]
for _,e in F.iterrows():
    d=P[e.code]; i=int(d.index[d.date==pd.Timestamp(e.d5)][0]); b=i+1
    if b+5>=len(d): continue
    af=d.adj_close/d.close; O=d.open*af; H=d.high*af; Lo=d.low*af; C=d.adj_close; ZT=C.shift(1)*(1+d.lim)
    r={'name':e['name'],'d5':e.d5,'换手':TURN.get((e.code,pd.Timestamp(e.d5)),np.nan),'流通市值':d.close[i]*d.oshare[i]/1e8}
    if Lo[b]>=ZT[b]*0.998:
        r.update(可买=False); rows.append(r); continue
    buy=O[b]; r['可买']=True
    def line(maxN,L=0.95):
        for t in range(b+1,b+maxN+1):
            pL=trig_price(d,t,L)
            if d.m10[t-1]>=L: return O[t],t
            if O[t]>=pL: return O[t],t
            if H[t]>=pL and pL<=ZT[t]*1.0001: return pL,t
        return C[b+maxN],b+maxN
    r['原策略(第3天收)']=C[b+1]/buy-1; r['原策略_卖日']=b+1
    r['第4天收']=C[b+2]/buy-1; r['第4天收_卖日']=b+2
    s,t=line(5); r['95线或5天']=s/buy-1; r['95线或5天_卖日']=t
    touched=H[b]>=ZT[b]*0.998
    if touched: s,t=line(4)        # 摸过涨停: 到线卖, 最多拿到第6天(买后4天)
    else: s,t=C[b+2],b+2           # 没摸: 第4天收盘
    r['组合方案']=s/buy-1; r['组合方案_卖日']=t
    r['买日']=b; r['日期序']=d.date[b]
    rows.append(r)
R=pd.DataFrame(rows); R.to_pickle('oneaday.pkl')
print(R.groupby('d5').size().loc[lambda s:s>1])

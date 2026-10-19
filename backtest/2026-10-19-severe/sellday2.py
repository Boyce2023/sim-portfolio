"""天数口径: 五板次日=第1天(开盘买入日). 强弱: 第1天盘中最高是否过+8%(相对五板收盘).
看第2到第10天收盘卖的收益; 组合方案: 强=到95%线卖最多到第5天, 弱=第N天收盘卖"""
import pandas as pd, numpy as np
A=pd.read_pickle('/private/tmp/claude-501/-Users-huaichuaibeimeng-claude-projects/0271364f-8cab-4319-af5d-5048f0719e12/scratchpad/devpanel.pkl')
P={c:d.reset_index(drop=True) for c,d in A.groupby('code')}
F=pd.read_pickle('../2026-10-19-5ban-day23/events.pkl')
def trig_price(d,t,L):
    best=np.inf
    for j in range(1,11):
        if t-j<0: break
        best=min(best,d.adj_close[t-j]*(1+L+(d.ilvl[t]/d.ilvl[t-j]-1)))
    return best
rows=[]
for _,e in F.iterrows():
    d=P[e.code]; i=int(d.index[d.date==pd.Timestamp(e.d5)][0]); b=i+1     # b=第1天
    if b+1>=len(d): continue
    af=d.adj_close/d.close; O=d.open*af; H=d.high*af; Lo=d.low*af; C=d.adj_close; ZT=C.shift(1)*(1+d.lim)
    if Lo[b]>=ZT[b]*0.998: continue
    buy=O[b]
    r={'name':e['name'],'d5':e.d5,'第1天最高':H[b]/C[i]-1,'强':bool(H[b]/C[i]-1>=0.08),'买日':b,'日期序':d.date[b]}
    for n in range(2,11):
        t=b+n-1; r[f'第{n}天']=C[t]/buy-1 if t<len(d) else np.nan
    def line(last_day,L=0.95):
        for t in range(b+1,min(b+last_day,len(d))):
            pL=trig_price(d,t,L)
            if d.m10[t-1]>=L: return O[t]/buy-1,t-b+1
            if O[t]>=pL: return O[t]/buy-1,t-b+1
            if H[t]>=pL and pL<=ZT[t]*1.0001: return pL/buy-1,t-b+1
        t=b+last_day-1
        return (C[t]/buy-1 if t<len(d) else np.nan),last_day
    r['95线最多到第5天'],r['95线最多到第5天_卖日']=line(5)
    rows.append(r)
R=pd.DataFrame(rows); R.to_pickle('sellday2.pkl')
cols=[f'第{n}天' for n in range(2,11)]
def show(x,lab):
    print(f"{lab} n={len(x)}")
    print('   平均 '+' '.join(f"{c}:{x[c].mean()*100:+.1f}%" for c in cols))
    print('   中位 '+' '.join(f"{c}:{x[c].median()*100:+.1f}%" for c in cols))
    print('   收涨 '+' '.join(f"{c}:{(x[c].dropna()>0).mean()*100:.0f}%({x[c].notna().sum()})" for c in cols))
show(R,'全部'); show(R[R.强],'第1天盘中过+8%'); show(R[~R.强],'第1天盘中没过+8%')
print('强组 95线最多到第5天: 均',round(R[R.强]['95线最多到第5天'].mean()*100,1),'% 中位',round(R[R.强]['95线最多到第5天'].median()*100,1),'% 胜',(R[R.强]['95线最多到第5天']>0).mean().round(2),'平均卖在第',R[R.强]['95线最多到第5天_卖日'].mean().round(1),'天')
print('弱组名单:',', '.join(f"{r['name']}(最高{r.第1天最高*100:+.1f}%)" for _,r in R[~R.强].iterrows()))

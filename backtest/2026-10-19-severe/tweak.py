"""五板策略微调(7月起): 入场 A=五板次日开盘买(原策略) / B=五板次日挂前收-1%的限价买(买不到不做)
出场: 固定第k天收盘(k=1..5, 买入日为T) / 到异动线(90%,95%,100%)当天按线价卖, 最多持N天否则第N天收盘卖 / +8%止盈限价单, 最多持N天"""
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
    d=P[e.code]; i=int(d.index[d.date==pd.Timestamp(e.d5)][0]); b=i+1
    if b+5>=len(d): continue     # 需要买入后5天数据
    af=d.adj_close/d.close; O=d.open*af; H=d.high*af; Lo=d.low*af; C=d.adj_close; ZT=C.shift(1)*(1+d.lim)
    yizi=Lo[b]>=ZT[b]*0.998
    entries={}
    if not yizi: entries['A开盘买']=O[b]
    lim_px=C[i]*0.99
    if (not yizi) and Lo[b]<=lim_px: entries['B挂-1%']=min(O[b],lim_px)
    for en,buy in entries.items():
        r={'name':e['name'],'d5':e.d5,'入场':en,'买价相对五板收':buy/C[i]-1}
        for k in range(1,6): r[f'固定T+{k}']=C[b+k]/buy-1
        for L in (0.9,0.95,1.0):
            for N in (3,5):
                sell=None; day=None
                for t in range(b+1,b+N+1):
                    pL=trig_price(d,t,L)
                    if d.m10[t-1]>=L: sell=O[t]; day=t-b; break
                    if O[t]>=pL: sell=O[t]; day=t-b; break
                    if H[t]>=pL and pL<=ZT[t]*1.0001: sell=pL; day=t-b; break
                if sell is None: sell=C[b+N]; day=N
                r[f'线{int(L*100)}_最多{N}天']=sell/buy-1; r[f'线{int(L*100)}_最多{N}天_天数']=day
        for N in (3,5):
            tgt=buy*1.08; sell=None; day=None
            for t in range(b+1,b+N+1):
                if O[t]>=tgt: sell=O[t]; day=t-b; break
                if H[t]>=tgt: sell=tgt; day=t-b; break
            if sell is None: sell=C[b+N]; day=N
            r[f'止盈8%_最多{N}天']=sell/buy-1; r[f'止盈8%_最多{N}天_天数']=day
        rows.append(r)
R=pd.DataFrame(rows); R.to_pickle('tweak.pkl')
rules=[c for c in R.columns if c.startswith(('固定','线','止盈')) and not c.endswith('_天数')]
R['半段']=np.where(R.d5<'2026-08-25','前半(7/6到8/24)','后半(8/25起)')
for en,x in R.groupby('入场'):
    print(f"\n=== {en}: {len(x)}笔 (前半{(x.半段.str.startswith('前')).sum()} 后半{(x.半段.str.startswith('后')).sum()}) 买价相对五板收中位{x.买价相对五板收.median()*100:+.1f}%")
    for c in rules:
        v=x[c]; hd=x.get(c+'_天数')
        h=' '.join(f"{s[:2]}{y[c].mean()*100:+.1f}%" for s,y in x.groupby('半段'))
        print(f"  {c:<14} 均{v.mean()*100:+5.1f}% 中位{v.median()*100:+5.1f}% 胜{(v>0).mean()*100:3.0f}% 最差{v.min()*100:+.0f}% | {h}" + (f" | 平均持{hd.mean():.1f}天" if hd is not None else ''))

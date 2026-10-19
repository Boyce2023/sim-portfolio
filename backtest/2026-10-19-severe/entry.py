"""五板策略买点比较(7月起). 卖法统一两种: 原策略=买入后第2个交易日收盘(对开盘买即第三天收) / 推荐=到95%异动线即卖否则最多持5天.
买点: 次日开盘 / 次日盘中回落到开盘下3%或5% / 次日触涨停按涨停价(打六板) / 次日碰跌停按跌停价 / 次日收盘 / 第三天开盘"""
import pandas as pd, numpy as np, json, glob
A=pd.read_pickle('/private/tmp/claude-501/-Users-huaichuaibeimeng-claude-projects/0271364f-8cab-4319-af5d-5048f0719e12/scratchpad/devpanel.pkl')
P={c:d.reset_index(drop=True) for c,d in A.groupby('code')}
F=pd.read_pickle('../2026-10-19-5ban-day23/events.pkl')
ths={}
for f in glob.glob('../2026-10-09-theme/ths/2026*.json'):
    d=f.split('/')[-1][:8]
    for r in json.load(open(f)): ths[(r['code'],d)]=r
def trig_price(d,t,L):
    best=np.inf
    for j in range(1,11):
        if t-j<0: break
        best=min(best,d.adj_close[t-j]*(1+L+(d.ilvl[t]/d.ilvl[t-j]-1)))
    return best
def exits(d,t0,buy,O,H,C,ZT):
    """t0=买入日下标; 返回 (固定第2日收, 95%线或最多5天)"""
    fixed=C[t0+1]/buy-1 if t0+1<len(d) else np.nan
    sell=None
    for t in range(t0+1,min(t0+6,len(d))):
        pL=trig_price(d,t,0.95)
        if d.m10[t-1]>=0.95: sell=O[t]; break
        if O[t]>=pL: sell=O[t]; break
        if H[t]>=pL and pL<=ZT[t]*1.0001: sell=pL; break
    if sell is None:
        if t0+5>=len(d): return fixed,np.nan
        sell=C[t0+5]
    return fixed, sell/buy-1
rows=[]
for _,e in F.iterrows():
    d=P[e.code]; i=int(d.index[d.date==pd.Timestamp(e.d5)][0]); b=i+1
    if b+6>=len(d): continue
    af=d.adj_close/d.close; O=d.open*af; H=d.high*af; Lo=d.low*af; C=d.adj_close; ZT=C.shift(1)*(1+d.lim); DT=C.shift(1)*(1-d.lim)
    yz=Lo[b]>=ZT[b]*0.998
    t=ths.get((e.code,d.date[b].strftime('%Y%m%d')))
    seal=None
    if t and t.get('first_limit_up_time'):
        import datetime; seal=datetime.datetime.fromtimestamp(int(t['first_limit_up_time'])).strftime('%H:%M')
    cand={}
    if not yz:
        cand['次日开盘']=(b,O[b])
        for x in (0.03,0.05):
            if Lo[b]<=O[b]*(1-x): cand[f'次日回落开盘下{int(x*100)}%']=(b,O[b]*(1-x))
        if H[b]>=ZT[b]*0.998: cand['次日触涨停(打六板)']=(b,ZT[b])
        if Lo[b]<=DT[b]*1.002: cand['次日碰跌停']=(b,DT[b])
        cand['次日收盘']=(b,C[b])
    if not (Lo[b+1]>=ZT[b+1]*0.998): cand['第三天开盘']=(b+1,O[b+1])
    for k,(t0,buy) in cand.items():
        f2,l95=exits(d,t0,buy,O,H,C,ZT)
        rows.append({'name':e['name'],'d5':e.d5,'买点':k,'买价相对五板收':buy/C[i]-1,'次日收':f2,'95线或5天':l95,'次日一字':yz,'六板封板时间':seal,'次日开盘缺口':O[b]/C[i]-1})
R=pd.DataFrame(rows); R.to_pickle('entry.pkl')
order=['次日开盘','次日回落开盘下3%','次日回落开盘下5%','次日触涨停(打六板)','次日碰跌停','次日收盘','第三天开盘']
base=R[R.买点=='次日开盘'].set_index('name')
for k in order:
    x=R[R.买点==k]
    if not len(x): continue
    s=lambda c: f"均{x[c].mean()*100:+.1f}% 中位{x[c].median()*100:+.1f}% 胜{(x[c].dropna()>0).mean()*100:.0f}%"
    print(f"{k:<14} n={len(x):<2} 买价(相对五板收)中位{x.买价相对五板收.median()*100:+.1f}% | 原卖法 {s('次日收')} 合计{x['次日收'].sum()*100:+.0f}% | 95线或5天 {s('95线或5天')} 合计{x['95线或5天'].sum()*100:+.0f}%")

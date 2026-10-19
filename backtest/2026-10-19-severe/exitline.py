import pandas as pd, numpy as np
A=pd.read_pickle('/private/tmp/claude-501/-Users-huaichuaibeimeng-claude-projects/0271364f-8cab-4319-af5d-5048f0719e12/scratchpad/devpanel.pkl')
P={c:d.reset_index(drop=True) for c,d in A.groupby('code')}
F=pd.read_pickle('../2026-10-19-5ban-day23/events.pkl'); Q1=pd.read_pickle('q1.pkl').set_index(['code','d5'])
def trig_price(d,t,L):
    """第 t 天收盘偏离达到 L 所需的价格(前复权口径), 近10日任一起点取最低"""
    best=np.inf
    for j in range(1,11):
        if t-j<0: break
        idxr=d.ilvl[t]/d.ilvl[t-j]-1
        best=min(best,d.adj_close[t-j]*(1+L+idxr))
    return best
rows=[]; traj=[]
for _,e in F.iterrows():
    d=P[e.code]; i=int(d.index[d.date==pd.Timestamp(e.d5)][0])
    af=d.adj_close/d.close; O=d.open*af; Hh=d.high*af; C=d.adj_close; ZT=C.shift(1)*(1+d.lim)
    mx=Q1.loc[(e.code,e.d5),'最大偏离']
    grp='破线' if mx>=1 else ('贴线90到100' if mx>=0.9 else '离线10%以上')
    # --- 断板后走势 ---
    k=i+1
    while k<len(d) and d.zt[k]: k+=1
    if k<len(d):
        traj.append({'name':e['name'],'d5':e.d5,'组':grp,'断板日':d.date[k].date(),'第几天断板':k-i,'断板日涨跌':C[k]/C[k-1]-1,'断板日相对五板收盘':C[k]/C[i]-1,
                     **{f'后{h}日':(C[k+h]/C[k]-1 if k+h<len(d) else np.nan) for h in (1,3,5,10)}})
    # --- 卖点比较: 第二天(i+1)开盘买 ---
    b=i+1
    if b+1>=len(d): continue
    if d.low[b]*af[b]>=ZT[b]*0.998: continue   # 一字买不到
    buy=O[b]; r={'name':e['name'],'d5':e.d5,'组':grp,'基准(第三天收)':C[b+1]/buy-1}
    for L in (0.9,0.95,1.0):
        for maxh,tag in ((1,'原持有期内'),(6,'最多持6天')):
            sell=None
            for t in range(b+1,min(b+1+maxh,len(d))):
                pL=trig_price(d,t,L)
                prev_dev_hit=d.m10[t-1]>=L   # 前一天收盘已过线 -> 今天开盘卖
                if prev_dev_hit: sell=O[t]; break
                if O[t]>=pL: sell=O[t]; break
                if Hh[t]>=pL and pL<=ZT[t]*1.0001: sell=pL; break
            if sell is None:
                last=min(b+maxh,len(d)-1)
                sell=C[b+1] if maxh==1 else C[last]
            r[f'L{int(L*100)}_{tag}']=sell/buy-1
    rows.append(r)
R=pd.DataFrame(rows); T=pd.DataFrame(traj)
R.to_pickle('exitline.pkl'); T.to_pickle('traj.pkl')

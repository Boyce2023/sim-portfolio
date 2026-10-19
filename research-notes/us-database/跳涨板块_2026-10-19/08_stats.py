"""机械层: 跳涨事件 / 个股窗口统计 / ETF统计。窗口 2026-08-24~2026-10-16, 基准=08-21收盘。"""
import json, pandas as pd, numpy as np
px=pd.read_pickle('px.pkl'); vol=pd.read_pickle('vol.pkl')
uni={u['t']:u for u in json.load(open('universe.json'))}; ETF=json.load(open('etfs.json'))
W0,W1='2026-08-24','2026-10-16'; BASE=pd.Timestamp('2026-08-21')
last=px.index[-1]; ret=px.pct_change(fill_method=None)
va=vol.rolling(20,min_periods=10).mean().shift(1)
fri=[d for d in px.index if d>=BASE and d.weekday()==4]   # 08-21..10-16 共9个周五
ev=[]
for t in uni:
    if t not in px.columns: continue
    s=px[t]; r=ret[t]
    for d in r.loc[W0:W1][r.loc[W0:W1]>=0.10].index:
        i=px.index.get_loc(d); pc=s.iloc[i-1]
        if np.isnan(pc): continue
        vr=vol[t].iloc[i]/va[t].iloc[i] if va[t].iloc[i] else np.nan
        nxt=r.iloc[i+1] if i+1<len(r) else np.nan
        glitch=(not np.isnan(nxt)) and nxt<=-0.8*r.iloc[i]/(1+r.iloc[i]) and (np.isnan(vr) or vr<1.5)
        pre=s.iloc[i-1]/s.iloc[i-22]-1 if i>=22 else np.nan
        hi52=s.iloc[max(0,i-252):i+1].max()
        ev.append(dict(date=str(d.date()),t=t,pc=pc,c=s.iloc[i],pct=r.iloc[i],vr=vr,pre1m=pre,since=s.iloc[-1]/s.iloc[i]-1,
                       now=s.iloc[-1],hi52=s.iloc[-253:].max(),glitch=bool(glitch)))
ev=pd.DataFrame(ev); print('跳涨事件',len(ev),'疑似数据错',int(ev.glitch.sum()),'不同代码',ev.t.nunique())
print(ev[ev.glitch][['date','t','pct','vr']].to_string())
ev.to_pickle('jumps.pkl')
def stat(t):
    s=px[t].loc[BASE:].dropna()
    if len(s)<30 or s.index[0]!=BASE: return None
    wk=px[t].reindex(fri).pct_change(fill_method=None).dropna()
    dd=(s/s.cummax()-1).min()
    rr=ret[t].loc[W0:W1]
    return dict(t=t,win=s.iloc[-1]/s.iloc[0]-1,m1=s.iloc[-1]/px[t].loc[:'2026-09-16'].iloc[-1]-1,
                m3=s.iloc[-1]/px[t].loc[:'2026-07-16'].iloc[-1]-1,wk_up=(wk>0).mean(),n_wk=len(wk),dd=dd,
                maxday=rr.max(),n10=int((rr>=0.10).sum()),off_hi=s.iloc[-1]/s.max()-1,now=s.iloc[-1],hi52=px[t].iloc[-253:].max())
st=pd.DataFrame([x for x in (stat(t) for t in uni if t in px.columns) if x]); st.to_pickle('stock_stats.pkl')
es=pd.DataFrame([dict(x,name=n) for t,n in ETF if t in px.columns for x in [stat(t)] if x]); es.to_pickle('etf_stats.pkl')
print('个股',len(st),'ETF',len(es)); print(es.sort_values('win',ascending=False)[['t','name','win','wk_up','dd']].head(25).to_string())
spy=es.set_index('t').loc['SPY']; print('SPY窗口',round(spy.win,4),'周涨占比',spy.wk_up)

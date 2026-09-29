#!/opt/homebrew/bin/python3.13
import pandas as pd, numpy as np, json, urllib.request
V={'E':'C 重训+个股记忆(最终版)','A':'A 不学习','B':'B 每月重训','C':'C 加自校准闸门','D':'C 加闸门+卖出参数月调','R':'R 同池随机'}
def idx(c):
    u=f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={c},day,2024-09-01,2026-09-30,800,"
    k=list(json.load(urllib.request.urlopen(u,timeout=15))['data'].values())[0]
    return pd.Series({pd.Timestamp(x[0]):float(x[2]) for x in (k.get('day') or k.get('qfqday'))})
rows=[]; q=[]
for k,n in V.items():
    try: E=pd.read_csv(f'eq_{k}.csv',parse_dates=['date']); T=pd.read_csv(f'trades_{k}.csv',parse_dates=['buy_d','sell_d'])
    except FileNotFoundError: continue
    nav=E.set_index('date').nav; dd=(nav/nav.cummax()-1).min(); yrs=(nav.index[-1]-nav.index[0]).days/365.25
    dr=nav.pct_change().dropna()
    w=T[T.ret>0]; l=T[T.ret<=0]
    months=len(nav.index.to_period('M').unique())
    rows.append({'版本':n,'交易笔数':len(T),'每月笔数':round(len(T)/months,1),'胜率%':round(len(w)/len(T)*100,1),
      '平均盈利%':round(w.ret.mean()*100,2),'平均亏损%':round(l.ret.mean()*100,2),'赔率':round(w.ret.mean()/-l.ret.mean(),2),
      '每笔期望%':round(T.ret.mean()*100,2),'总收益%':round((nav.iloc[-1]-1)*100,1),'年化%':round((nav.iloc[-1]**(1/yrs)-1)*100,1),
      '最大回撤%':round(dd*100,1),'夏普':round(dr.mean()/dr.std()*np.sqrt(252),2),'平均持仓数':round(E.npos.mean(),1),
      '通达型命中%':round((T.mfe>=0.25).mean()*100,1)})
    T['q']=T.buy_d.dt.to_period('Q')
    g=T.groupby('q').agg(笔数=('ret','size'),胜率=('ret',lambda x:(x>0).mean()*100),期望=('ret',lambda x:x.mean()*100))
    g['赔率']=T.groupby('q').ret.apply(lambda x:x[x>0].mean()/-x[x<=0].mean())
    g.columns=pd.MultiIndex.from_product([[n],g.columns]); q.append(g)
R=pd.DataFrame(rows); pd.set_option('display.width',250); print(R.to_string(index=False))
nav0=pd.read_csv('eq_E.csv',parse_dates=['date']).set_index('date').nav
print('\n基准(同期):')
for c,n in [('sh000001','上证指数'),('sh000852','中证1000'),('sz399006','创业板指')]:
    try:
        s=idx(c).reindex(nav0.index).ffill(); print(f"  {n}: {((s.iloc[-1]/s.iloc[0])-1)*100:+.1f}%  最大回撤 {((s/s.cummax())-1).min()*100:.1f}%")
    except Exception as e: print(n,'取数失败',e)
print('\n分季度 胜率/每笔期望/赔率:')
Q=pd.concat(q,axis=1).round(2); print(Q.to_string())
R.to_csv('summary.csv',index=False); Q.to_csv('by_quarter.csv')
# 前后两半段
H=[]
for k,n in V.items():
    try: E=pd.read_csv(f'eq_{k}.csv',parse_dates=['date']).set_index('date'); T=pd.read_csv(f'trades_{k}.csv',parse_dates=['buy_d'])
    except FileNotFoundError: continue
    for lab,a,b in [('前半 2024-10至2025-09','2024-10-01','2025-10-01'),('后半 2025-10至2026-09','2025-10-01','2026-10-01')]:
        e=E.nav[(E.index>=a)&(E.index<b)]; t=T[(T.buy_d>=a)&(T.buy_d<b)]
        w=t[t.ret>0]; l=t[t.ret<=0]
        H.append({'版本':n,'区间':lab,'笔数':len(t),'胜率%':round(len(w)/max(len(t),1)*100,1),'赔率':round(w.ret.mean()/-l.ret.mean(),2) if len(l) else None,
                  '每笔期望%':round(t.ret.mean()*100,2),'区间收益%':round((e.iloc[-1]/e.iloc[0]-1)*100,1),'区间回撤%':round(((e/e.cummax())-1).min()*100,1)})
H=pd.DataFrame(H); print('\n前后两半段:'); print(H.to_string(index=False)); H.to_csv('halves.csv',index=False)

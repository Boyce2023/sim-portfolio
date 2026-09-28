#!/opt/homebrew/bin/python3.13
"""找与 通达创智(001368) 过去15个交易日(09-04..09-24)走势相似的股
   相似 = 收盘路径形状 + 15日涨幅 + 无涨停台阶 + 换手放大倍数 + 流通市值"""
import pandas as pd, numpy as np
px=pd.read_parquet('data/cn_hk_price_db/a_daily.parquet',
    columns=['date','ticker','open','high','low','close','amount','oshare','turn'],
    filters=[('date','>=',pd.Timestamp('2026-06-01'))])
px['code']=px.ticker.str[:6]
t=pd.read_csv('/tmp/close0924.csv',dtype={'code':str})
t['code']=t['code'].str.zfill(6)
last=px.sort_values('date').groupby('code').tail(1).set_index('code')
d24=t[['code','name','open','high','low','price','amount']].rename(columns={'price':'close'}).set_index('code')
d24=d24.join(last[['ticker','oshare']],how='inner')
d24['amount']=d24['amount']*1e4           # 万元 → 元
d24['turn']=d24['amount']/(d24['close']*d24['oshare'])
d24['date']=pd.Timestamp('2026-09-24')
px=pd.concat([px,d24.reset_index()[['date','ticker','open','high','low','close','amount','oshare','turn','code']]])
px=px.sort_values(['code','date']).reset_index(drop=True)
names=t.set_index('code')['name']
def lim(c):
    if c.startswith(('688','300','301')): return .2
    if c.startswith(('8','4','92')): return .3
    return .1
px['prev']=px.groupby('code').close.shift(1)
px['chg']=px.close/px.prev-1
px['L']=px.code.map(lim)
px['zt']=px.close>=(px.prev*(1+px.L)).round(2)-0.011
dates=sorted(px.date.unique()); W=dates[-15:]; P=dates[-35:-15]
assert W[-1]==pd.Timestamp('2026-09-24'), W[-1]
feat=[]
for c,g in px.groupby('code'):
    g=g.set_index('date')
    if not all(d in g.index for d in W) or g.index.min()>dates[-60]: continue
    n=str(names.get(c,''))
    if 'ST' in n or not n: continue
    w=g.loc[W]; p=g.loc[g.index.isin(P)]
    base=g.loc[dates[-16],'close'] if dates[-16] in g.index else w.close.iloc[0]
    path=(w.close/base-1).values
    feat.append(dict(code=c,name=n,path=path,ret=path[-1],zt=int(w.zt.sum()),maxd=w.chg.max(),dn=int((w.chg<0).sum()),
        tw=w.turn.mean(),tp=p.turn.mean() if len(p) else np.nan,fcap=w.close.iloc[-1]*w.oshare.iloc[-1]/1e8,
        dd=(w.close/w.close.cummax()-1).min(),prebase=(g.loc[P[0]:P[-1]].close.max()/g.loc[P[0]:P[-1]].close.min()-1) if len(p) else np.nan))
F=pd.DataFrame(feat); F['tr']=F.tw/F.tp
T=F[F.code=='001368'].iloc[0]
print('目标 通达创智:',f"15日涨 {T.ret*100:.1f}% 涨停 {T.zt} 最大单日 {T.maxd*100:.1f}% 下跌日 {T.dn} 窗口换手 {T.tw*100:.2f}% 前20日换手 {T.tp*100:.2f}% 放大 {T.tr:.1f}x 流通 {T.fcap:.1f}亿 窗口最大回撤 {T.dd*100:.1f}% 前期箱体振幅 {T.prebase*100:.1f}%")
tp=T.path
F['corr']=F.path.map(lambda x:np.corrcoef(x,tp)[0,1])
F['dist']=F.path.map(lambda x:np.sqrt(np.mean((x-tp)**2)))
C=F[(F.code!="001368")&(F.zt<=2)&(F.maxd<=0.125)&(F.ret.between(0.20,1.0))&(F.fcap.between(15,150))&(F.tr>=1.5)&(F.dd>-0.12)].copy()
C['score']=C.dist*100 + (1-C['corr'])*50 + abs(np.log(C.fcap/T.fcap))*5 + abs(np.log(C.tr/T.tr))*5
C=C.sort_values('score')
print(f"\n候选 {len(C)} 只 (全市场 {len(F)} 只里过滤: 涨停≤1 单日最大≤10% 15日涨30-90% 流通15-120亿 换手放大≥1.8x 窗口回撤<10%)")
pd.set_option('display.width',220)
out=C.head(20).copy()
for k in ['ret','maxd','tw','tp','dd']: out[k]=(out[k]*100).round(1)
out['fcap']=out.fcap.round(1); out['tr']=out.tr.round(1); out['corr']=out['corr'].round(3); out['dist']=(out.dist*100).round(1); out['score']=out.score.round(1)
print(out[['code','name','ret','zt','maxd','dn','tw','tp','tr','fcap','dd','corr','dist','score']].to_string(index=False))
C.drop(columns='path').to_csv('backtest/2026-09-28-simpath/cands.csv',index=False)

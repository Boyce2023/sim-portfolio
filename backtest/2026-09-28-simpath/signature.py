#!/opt/homebrew/bin/python3.13
"""通达创智型 点火信号 事后检验 + 当前扫描
信号日 d (收盘后可知): 基座(截至 d-1): 前20日箱体振幅<=25%, 前20日涨幅 -10%..+15%, 前20日均换手<=3.5%
                       点火(d 当天): 涨 +4%..+9.5% 且非涨停, 换手 >= 前20日均值 2 倍
结果: d 收盘后 5/10/15 日收益; 达成通达型(15日>=+25%)概率; 对照=同期全部基座股"""
import pandas as pd, numpy as np
px=pd.read_parquet('data/cn_hk_price_db/a_daily.parquet',
    columns=['date','ticker','close','high','amount','oshare','turn'],filters=[('date','>=',pd.Timestamp('2026-03-01'))])
px['code']=px.ticker.str[:6]
# 补 09-24
t=pd.read_csv('/tmp/close0924.csv',dtype={'code':str}); t['code']=t.code.str.zfill(6)
last=px.sort_values('date').groupby('code').tail(1).set_index('code')[['ticker','oshare']]
d=t.set_index('code')[['name','price','high','amount']].rename(columns={'price':'close'}).join(last,how='inner')
d['amount']*=1e4; d['turn']=d.amount/(d.close*d.oshare); d['date']=pd.Timestamp('2026-09-24')
px=pd.concat([px,d.reset_index()[['date','ticker','close','high','amount','oshare','turn','code']]])
names=t.set_index('code')['name']
px=px.sort_values(['code','date']).reset_index(drop=True)
px=px[~px.code.str.startswith(('8','4','92'))]
L=np.where(px.code.str.startswith(('688','300','301')),.2,.1)
g=px.groupby('code')
px['prev']=g.close.shift(1); px['chg']=px.close/px.prev-1
px['zt']=px.close>=(px.prev*(1+L)).round(2)-0.011
px['fcap']=px.close*px.oshare/1e8
sh=lambda s,n:s.shift(n)
px['t20']=g.turn.transform(lambda s:s.shift(1).rolling(20,min_periods=15).mean())
px['box20']=g.close.transform(lambda s:(s.shift(1).rolling(20).max()/s.shift(1).rolling(20).min()-1))
px['r20']=g.close.transform(lambda s:s.shift(1)/s.shift(21)-1)
px['tr']=px.turn/px.t20
for n in [5,10,15]: px[f'f{n}']=g.close.shift(-n)/px.close-1
px['f15max']=g.close.transform(lambda s:s[::-1].rolling(15).max()[::-1].shift(-1))/px.close-1
px['name']=px.code.map(names)
px=px[~px.name.astype(str).str.contains('ST')]
base=(px.box20<=0.25)&px.r20.between(-0.10,0.15)&(px.t20<=0.035)
sig=base&px.chg.between(0.04,0.095)&(~px.zt)&(px.tr>=2)
T=px[(px.date>=pd.Timestamp('2026-07-01'))&(px.date<=pd.Timestamp('2026-09-03'))&px.f15.notna()]
def rep(m,lab):
    x=T[m.reindex(T.index,fill_value=False)]
    print(f"  {lab:<26} n={len(x):>6}  5日{x.f5.mean()*100:+6.2f}%  10日{x.f10.mean()*100:+6.2f}%  15日{x.f15.mean()*100:+6.2f}% (中位{x.f15.median()*100:+5.2f}%)  15日>=25%: {(x.f15>=0.25).mean()*100:5.1f}%  期间最高涨>=25%: {(x.f15max>=0.25).mean()*100:5.1f}%  15日亏: {(x.f15<0).mean()*100:4.1f}%")
for lab,a,b in [('7-9月全段','2026-07-01','2026-09-03'),('8-9月(非反弹期)','2026-08-05','2026-09-03')]:
    T=px[(px.date>=pd.Timestamp(a))&(px.date<=pd.Timestamp(b))&px.f15.notna()]
    print(f"\n【{lab}】")
    rep(pd.Series(True,index=px.index),'全市场')
    rep(base,'基座股(窄箱体低换手)')
    rep(base&px.chg.between(0.04,0.095)&(~px.zt),'基座+点火(不看换手)')
    rep(sig,'基座+点火+换手>=2倍')
    rep(sig&(px.fcap<=60),'  且流通<=60亿')
    rep(base&px.zt,'基座+涨停(对照)')
# 当前扫描: 最近3个交易日(09-22/23/24)出现信号的
D=sorted(px.date.unique())[-3:]
C=px[sig&px.date.isin(D)].copy()
C['fromsig']=C.apply(lambda r:None,axis=1)
lastc=px[px.date==D[-1]].set_index('code')
C['now']=C.code.map(lastc.close); C['since']=C.now/C.close-1
C=C.sort_values(['date','fcap'])
print(f"\n【当前: {D[0]:%m-%d}..{D[-1]:%m-%d} 出现点火信号的】 {len(C)} 只")
for _,r in C.iterrows():
    print(f"  {r.date:%m-%d} {r.code} {r['name']:<8} 流通{r.fcap:6.1f}亿 箱体{r.box20*100:4.1f}% 前20日{r.r20*100:+5.1f}% 前换手{r.t20*100:4.1f}% | 点火{r.chg*100:+4.1f}% 换手{r.turn*100:4.1f}%({r.tr:3.1f}x) | 到09-24 {r.since*100:+5.1f}%")
C.to_csv('backtest/2026-09-28-simpath/current_signals.csv',index=False)

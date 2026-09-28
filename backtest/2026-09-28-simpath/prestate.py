#!/opt/homebrew/bin/python3.13
"""台阶式慢牛(通达创智型) 起涨前特征 与 点火日特征
事件: 15日窗口 涨幅>=40%, 涨停<=1, 单日最大<=10%, 窗口内最大回撤>-10%; 起点=窗口前一天(基座日 s)
样本: 起点 2026-07-01 .. 2026-09-10 (锁定7月以来)"""
import pandas as pd, numpy as np
px=pd.read_parquet('data/cn_hk_price_db/a_daily.parquet',
    columns=['date','ticker','close','amount','oshare','turn'],filters=[('date','>=',pd.Timestamp('2026-03-01'))])
px['code']=px.ticker.str[:6]
px=px.sort_values(['code','date']).reset_index(drop=True)
def lim(c):
    if c.startswith(('688','300','301')): return .2
    if c.startswith(('8','4','92')): return .3
    return .1
px['L']=px.code.map(lim)
g=px.groupby('code')
px['prev']=g.close.shift(1); px['chg']=px.close/px.prev-1
px['zt']=(px.close>=(px.prev*(1+px.L)).round(2)-0.011).astype(int)
px['fcap']=px.close*px.oshare/1e8
# 基座日 s 的特征(只用 s 及之前)
px['t20']=g.turn.transform(lambda s:s.rolling(20,min_periods=15).mean())
px['box20']=g.close.transform(lambda s:s.rolling(20).max()/s.rolling(20).min()-1)
px['r20']=g.close.transform(lambda s:s/s.shift(20)-1)
px['r60']=g.close.transform(lambda s:s/s.shift(60)-1)
px['zt20']=g.zt.transform(lambda s:s.rolling(20).sum())
# 未来15日(s+1..s+15)
F=15
px['fret']=g.close.shift(-F)/px.close-1
px['fzt']=g.zt.transform(lambda s:s[::-1].rolling(F).sum()[::-1].shift(-1))
px['fmax']=g.chg.transform(lambda s:s[::-1].rolling(F).max()[::-1].shift(-1))
def fdd(s):
    a=s.values; out=np.full(len(a),np.nan)
    for i in range(len(a)-F):
        w=a[i+1:i+1+F]; out[i]=(w/np.maximum.accumulate(w)-1).min()
    return pd.Series(out,index=s.index)
px['fdd']=g.close.transform(fdd)
# 点火日 = s+1 当天
px['d1chg']=g.chg.shift(-1); px['d1zt']=g.zt.shift(-1)
px['d1tr']=g.turn.shift(-1)/px.t20
px['event']=((px.fret>=0.40)&(px.fzt<=1)&(px.fmax<=0.10)&(px.fdd>-0.10)).astype(int)
S=px[(px.date>=pd.Timestamp('2026-07-01'))&(px.date<=pd.Timestamp('2026-09-02'))&px.fret.notna()&px.t20.notna()&px.r60.notna()].copy()
S=S[~S.code.str.startswith(('8','4','92'))]
ev=S[S.event==1].sort_values('date').groupby('code').head(1)
base=S.event.mean()
print(f"样本 {len(S):,} 个股票日, 事件起点 {S.event.sum()} 个(去重后 {len(ev)} 只股票), 基础概率 {base*100:.3f}%")
print("\n事件股(按起点):")
for _,r in ev.iterrows(): print(f"  {r.date:%m-%d} {r.code} 起点流通{r.fcap:5.1f}亿 前20日换手{r.t20*100:4.1f}% 箱体{r.box20*100:5.1f}% 前20日涨{r.r20*100:+5.1f}% 前60日涨{r.r60*100:+5.1f}% | 点火日{r.d1chg*100:+5.1f}% 换手放大{r.d1tr:4.1f}x | 15日{r.fret*100:+5.1f}%")
def lift(col,bins,lab):
    S['_b']=pd.cut(S[col],bins); t=S.groupby('_b',observed=True).event.agg(['size','mean'])
    print(f"\n{lab}"); 
    for b,r in t.iterrows(): print(f"  {str(b):<18} 样本{int(r['size']):>7}  命中率 {r['mean']*100:.3f}%  倍数 {r['mean']/base:.2f}x")
lift('fcap',[0,20,40,60,100,200,1e5],'基座日流通市值(亿)')
lift('t20',[0,.01,.02,.03,.05,.08,1],'前20日平均换手')
lift('box20',[0,.08,.12,.16,.22,.35,10],'前20日箱体振幅')
lift('r20',[-1,-.1,-.03,.03,.1,.25,10],'前20日涨幅')
lift('r60',[-1,-.15,0,.15,.4,10],'前60日涨幅')
lift('zt20',[-.1,0.5,1.5,100],'前20日涨停次数')
lift('d1chg',[-1,0,.02,.04,.06,.08,.095,1],'点火日(s+1)涨幅')
lift('d1tr',[0,1,1.5,2,3,5,100],'点火日换手/前20日均值')
S.to_parquet('/tmp/prestate_S.parquet')

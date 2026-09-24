#!/opt/homebrew/bin/python3.13
"""公式化轮动回测: 前龙头突破当天启动的票, 是不是比普通启动票好? 信号日 2026-07-01 到 2026-09-22。

Buwen 2026-09-24 给的规律(我已用数据逐个核实全部命中):
  创新药 万邦医药07-10突破 → 哈药同日涨停; 哈药08-04突破 → 百花同日涨停; 百花08-26突破 → 千金同日涨停
  农业   金健米业08-25起突破 → 万向德农08-25涨停; 万向德农09-07突破 → 敦煌种业09-04涨停

⛔主题分组不用申万行业(创新药链横跨化学制药/医疗服务/中药Ⅱ, 农业链横跨农产品加工/种植业, 用行业会切断)。
  改用滚动相关性: 在信号日 t, 只用 t-21 到 t-1 的日收益算相关(决策时点可得, 无前视)。
定义:
  启动 = 某票 t 日涨停且 t-1 日未涨停(首板)
  同主题龙头 L = 与该票前20日收益相关系数 >= CORR 且 前20日涨幅 >= LEAD_RET
  突破 = L 的收盘价创 20 日新高(用 t-1 及以前的最高收盘比)
  条件组 = 存在至少一个 L 在 t 日或 t-1 日突破
  对照组 = 其余首板
买入 t+1 开盘(开盘涨停剔除), 卖出 T+1/T+3/T+5 收盘, 成本12.3bp。超额 = 减同日全部首板(可买)的等权均值。
"""
import math, sys
import pandas as pd, numpy as np
S_D,E_D = pd.Timestamp('2026-07-01'), pd.Timestamp('2026-09-22')
COST=0.00123; CORR=0.5; LEAD_RET=0.30; WIN=20

px = pd.read_parquet('data/cn_hk_price_db/a_daily.parquet',
    columns=['date','ticker','open','close','adj_close','qfq_factor','amount','oshare'],
    filters=[('date','>=',pd.Timestamp('2026-04-01'))]).sort_values(['ticker','date'])
px['adj_open']=px['open']/px['qfq_factor']
px['pc']=px.groupby('ticker')['close'].shift(1)
def lim(t):
    c=t[:6]
    return .20 if c[:3] in ('300','301','688','689') else (.30 if c[0] in ('4','8') else .10)
px['lim']=px['ticker'].map(lim)
px['zt']=px['close']>=(px['pc']*(1+px['lim'])).round(2)-0.011
px['ret']=px['adj_close'].groupby(px['ticker']).pct_change(fill_method=None)
px['hi20']=px.groupby('ticker')['close'].transform(lambda s:s.shift(1).rolling(WIN).max())
px['brk']=px['close']>px['hi20']
px['r20']=px.groupby('ticker')['adj_close'].pct_change(WIN,fill_method=None)
px['buyable']=px.groupby('ticker')['open'].shift(-1)<(px['close']*(1+px['lim'])).round(2)-0.011
px['buy']=px.groupby('ticker')['adj_open'].shift(-1)
for n,k in [(1,'T1'),(3,'T3'),(5,'T5')]:
    px[k]=px.groupby('ticker')['adj_close'].shift(-n)/px['buy']-1-COST
px['zt_prev']=px.groupby('ticker')['zt'].shift(1)

R = px.pivot(index='date',columns='ticker',values='ret')
BR= px.pivot(index='date',columns='ticker',values='brk').fillna(False)
RR= px.pivot(index='date',columns='ticker',values='r20')
AMT=px.pivot(index='date',columns='ticker',values='amount')
dates=list(R.index)

def leaders(tk, t):
    """返回 t 日该票的同主题龙头列表(PIT: 只用 t 之前的数据)"""
    i=dates.index(t)
    if i<WIN+1: return []
    w=R.iloc[i-WIN:i]                      # t-20 到 t-1
    x=w[tk]
    if x.isna().sum()>3: return []
    ok=w.columns[(w.notna().sum()>=WIN-3)]
    W=w[ok].fillna(0.0)
    xv=(x.fillna(0.0)-x.fillna(0.0).mean()).values
    Wv=W.values-W.values.mean(axis=0)
    denom=(np.sqrt((xv**2).sum())*np.sqrt((Wv**2).sum(axis=0)))
    denom[denom==0]=np.nan
    c=(Wv*xv[:,None]).sum(axis=0)/denom
    r20=RR.iloc[i-1][ok].values
    amt=AMT.iloc[i-1][ok].values
    m=(c>=CORR)&(r20>=LEAD_RET)&(np.array(ok)!=tk)&(amt>=5e7)
    return list(np.array(ok)[m])

S = px[(px['date']>=S_D)&(px['date']<=E_D)&px['zt']&(px['zt_prev']==False)&(px['amount']>=5e7)].copy()
print(f"首板涨停事件 {len(S)} 个", flush=True)
flag=[]; nlead=[]
for r in S.itertuples():
    L=leaders(r.ticker, r.date)
    nlead.append(len(L))
    if not L: flag.append(False); continue
    i=dates.index(r.date)
    hit = BR.iloc[i][L].any() or (i>0 and BR.iloc[i-1][L].any())
    flag.append(bool(hit))
S['龙头突破']=flag; S['龙头数']=nlead
S.to_csv('backtest/2026-09-23-lianban/relay_break.csv',index=False)

# 检验: 他给的两条链能不能被聚出来
print("\n⛔方法检验: 用相关性能否还原他给的两条链")
chk=[('600664.SH','哈药',pd.Timestamp('2026-07-10'),'万邦医药301520'),
     ('600721.SH','百花',pd.Timestamp('2026-08-04'),'哈药600664'),
     ('600479.SH','千金',pd.Timestamp('2026-08-26'),'百花600721'),
     ('600371.SH','万向德农',pd.Timestamp('2026-08-25'),'金健米业600127'),
     ('600354.SH','敦煌种业',pd.Timestamp('2026-09-04'),'万向德农600371')]
nm=dict(zip(px['ticker'],px['ticker']))
yj=pd.read_csv('/tmp/bt0922/yjbb.csv',dtype={'股票代码':str})
yj['tk']=yj['股票代码'].str.zfill(6).map(lambda c:c+('.SH' if c[0] in '69' else ('.BJ' if c[0] in '48' else '.SZ')))
NM=yj.drop_duplicates('tk',keep='last').set_index('tk')['股票简称']
for tk,n,d,expect in chk:
    L=leaders(tk,d)
    names=[f"{NM.get(x,x[:6])}" for x in L][:10]
    i=dates.index(d)
    hit=[f"{NM.get(x,x[:6])}" for x in L if BR.iloc[i][x] or BR.iloc[i-1][x]]
    print(f"  {n} {d.date()} 聚出龙头{len(L)}只: {names}")
    print(f"      其中当日或前一日突破的: {hit}   (期望含 {expect})")

def rep(x,tag,base):
    b=x[x['buyable']]
    if len(b)<5: print(f"{tag:<26} n={len(b)} 不足"); return
    s=f"{tag:<26} 首板{len(x):>4} 买得进{len(b):>4}"
    for k in ['T1','T3','T5']:
        v=b[k].dropna(); e=v-base[k]
        t=v.mean()/(v.std(ddof=1)/math.sqrt(len(v))) if v.std(ddof=1)>0 else float('nan')
        s+=f" | {k} {v.mean()*100:+6.2f}% 胜{(v>0).mean()*100:3.0f}% t={t:5.2f}"
    print(s)
allb=S[S['buyable']]
base={k:allb[k].mean() for k in ['T1','T3','T5']}
print(f"\n全部首板基准: T1 {base['T1']*100:+.2f}% T3 {base['T3']*100:+.2f}% T5 {base['T5']*100:+.2f}%")
print("\n【龙头突破日启动 vs 普通启动】")
rep(S[S['龙头突破']],"龙头当日或前日突破",base)
rep(S[(~S['龙头突破'])&(S['龙头数']>0)],"有龙头但未突破",base)
rep(S[S['龙头数']==0],"无同主题龙头(孤立首板)",base)

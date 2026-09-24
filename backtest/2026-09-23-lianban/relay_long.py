#!/opt/homebrew/bin/python3.13
"""接力式五连板 长窗口回测: 2020-09-01 到 2026-09-22 (创业板20cm改制之后, 涨跌幅规则一致)。

问题: 同一行业里龙一龙二龙三挨个走出五连板, 后面的比前面的好还是差?

口径:
  连板数 自建机械判定(收盘 >= round(前收*(1+上限),2) 容差0.011), 已用东财涨停池官方字段在 2026-09-03 到 09-22 校验 826条一致825条=99.88%。
  上限 创业300/301 科创688/689=20%, 北交所4xx/8xx=30%, 其余10%。
  事件 = 某票首次达到5板那天(每票每轮只取一次)。
  序号 = 同行业内按日期排序, 与上一只间隔>15个交易日则重置为1。
  买入 次日开盘(adj_open), 次日开盘即涨停 → 买不进, 不计入收益。
  卖出 T+1/T+3/T+5 收盘。成本 一买一卖 12.3bp。
⛔已知偏差: 行业分类取自当前快照(yjbb), 退市股不在其中会被丢弃, 存在幸存者偏差; 行业重分类未回溯。
"""
import math, sys
import pandas as pd, numpy as np
S_D, E_D = pd.Timestamp('2020-09-01'), pd.Timestamp('2026-09-22')
COST = 0.00123

print("读库...", flush=True)
px = pd.read_parquet('data/cn_hk_price_db/a_daily.parquet',
                     columns=['date','ticker','open','close','adj_close','qfq_factor','oshare','amount'],
                     filters=[('date','>=',pd.Timestamp('2020-06-01'))]).sort_values(['ticker','date'])
print(f"  {len(px):,} 行, {px['ticker'].nunique()} 只", flush=True)
px['adj_open'] = px['open']/px['qfq_factor']
px['prev_close'] = px.groupby('ticker')['close'].shift(1)
def lim(t):
    c=t[:6]
    if c[:3] in ('300','301','688','689'): return .20
    if c[0] in ('4','8'): return .30
    return .10
px['lim']=px['ticker'].map(lim)
px['zt']=px['close']>=(px['prev_close']*(1+px['lim'])).round(2)-0.011
px['blk']=(~px['zt']).groupby(px['ticker']).cumsum()
px['nb']=px.groupby(['ticker','blk']).cumcount()
m=(px['blk']==0)&px['zt']; px.loc[m,'nb']=px.loc[m,'nb']+1; px.loc[~px['zt'],'nb']=0
for n,k in [(1,'T1'),(3,'T3'),(5,'T5'),(10,'T10')]:
    px[k]=px.groupby('ticker')['adj_close'].shift(-n)/px.groupby('ticker')['adj_open'].shift(-1)-1-COST
px['buyable']=px.groupby('ticker')['open'].shift(-1)<(px['close']*(1+px['lim'])).round(2)-0.011
px['float_cap']=px['close']*px['oshare']/1e8

yj=pd.read_csv('/tmp/bt0922/yjbb.csv',dtype={'股票代码':str})
yj['ticker']=yj['股票代码'].str.zfill(6).map(lambda c:c+('.SH' if c[0] in '69' else ('.BJ' if c[0] in '48' else '.SZ')))
ind=yj.drop_duplicates('ticker',keep='last').set_index('ticker')['所处行业']
nm=yj.drop_duplicates('ticker',keep='last').set_index('ticker')['股票简称']
px['ind']=px['ticker'].map(ind); px['name']=px['ticker'].map(nm)
td=sorted(px['date'].unique()); ti={d:i for i,d in enumerate(td)}

W=px[(px['date']>=S_D)&(px['date']<=E_D)&(px['nb']>=5)&px['ind'].notna()].copy()
W['di']=W['date'].map(ti)
# 每票每轮首次5板: 同票两次事件间隔>15交易日算新一轮
W=W.sort_values(['ticker','date'])
W['gap']=W.groupby('ticker')['di'].diff()
W['newround']=(W['gap'].isna())|(W['gap']>15)
F=W[W['newround']].copy()
F=F[['ticker','name','ind','date','di','nb','float_cap','buyable','T1','T3','T5','T10']].sort_values(['ind','date'])

seq=[]; last={}
for t in F.itertuples():
    k=t.ind
    s = last[k][0]+1 if (k in last and t.di-last[k][1]<=15) else 1
    seq.append(s); last[k]=(s,t.di)
F['seq']=seq
F.to_csv('backtest/2026-09-23-lianban/relay_long.csv',index=False)
print(f"\n首次5板事件 {len(F):,} 个, {F['ind'].nunique()} 个行业, {F['date'].dt.year.nunique()} 个年度")
print("序号分布:", F.groupby('seq').size().head(8).to_dict())

P=['T1','T3','T5','T10']
def rep(x,tag):
    b=x[x['buyable']]
    if len(x)==0: print(f"{tag:<20} 0"); return
    s=f"{tag:<20} 事件{len(x):>4} 买得进{len(b):>4}({len(b)/len(x)*100:3.0f}%)"
    for k in P:
        v=b[k].dropna()
        if len(v)<5: s+=f" | {k} n={len(v)}"; continue
        t=v.mean()/(v.std(ddof=1)/math.sqrt(len(v))) if v.std(ddof=1)>0 else float('nan')
        s+=f" | {k} {v.mean()*100:+6.2f}% 胜{(v>0).mean()*100:3.0f}% t={t:6.2f}"
    print(s)

print("\n【同行业内 第几只走出五连板】")
for s in [1,2,3,4]:
    rep(F[F['seq']==s], f"龙{s} (第{s}只5板)")
rep(F[F['seq']>=3], "龙三及以后合计")
rep(F[F['seq']>=2], "龙二及以后合计")

print("\n【按年 龙一 vs 龙二及以后 T3】")
F['y']=F['date'].dt.year
for y,g in F[F['buyable']].groupby('y'):
    a=g[g['seq']==1]['T3'].dropna(); b=g[g['seq']>=2]['T3'].dropna()
    print(f"  {y}  龙一 n={len(a):>3} {a.mean()*100:+6.2f}%  |  龙二及以后 n={len(b):>3} {b.mean()*100:+6.2f}%" if len(a)>2 and len(b)>2
          else f"  {y}  龙一 n={len(a):>3}  龙二及以后 n={len(b):>3} (样本不足)")

print("\n【同一轮里总共出了几只五连板, 对每只的影响】")
F['roundid']=F.groupby('ind')['seq'].transform(lambda s:(s==1).cumsum())
tot=F.groupby(['ind','roundid'])['seq'].transform('max')
F['轮内总数']=tot
for n,lb in [(1,'该轮只有1只'),(2,'该轮共2只'),(3,'该轮共3只以上')]:
    sel = F['轮内总数']==n if n<3 else F['轮内总数']>=3
    rep(F[sel], lb)

#!/opt/homebrew/bin/python3.13
"""接力式五连板回测: 同一题材里龙一龙二龙三挨个走出五连板, 后面的比前面的好还是差?
信号日 2026-07-01 到 2026-09-22。连板数自建判定(已用东财涨停池官方字段校验99.88%)。
序号定义: 同一行业内, 按首次达到5板的日期排序; 若与上一只间隔超过15个交易日则视为新一轮, 序号重置。
买入次日开盘(开盘即涨停剔除), 卖出 T+1/T+3/T+5 收盘, 成本12.3bp。
"""
import math
import pandas as pd, numpy as np
S_D, E_D = pd.Timestamp('2026-07-01'), pd.Timestamp('2026-09-22')
COST = 0.00123

px = pd.read_parquet('data/cn_hk_price_db/a_daily.parquet',
                     columns=['date','ticker','open','close','adj_close','qfq_factor','oshare'],
                     filters=[('date','>=',pd.Timestamp('2026-05-01'))]).sort_values(['ticker','date'])
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
for n,k in [(1,'T1'),(3,'T3'),(5,'T5')]:
    px[k]=px.groupby('ticker')['adj_close'].shift(-n)/px.groupby('ticker')['adj_open'].shift(-1)-1-COST
px['buyable']=px.groupby('ticker')['open'].shift(-1)<(px['close']*(1+px['lim'])).round(2)-0.011
px['float_cap']=px['close']*px['oshare']/1e8

yj=pd.read_csv('/tmp/bt0922/yjbb.csv',dtype={'股票代码':str})
yj['ticker']=yj['股票代码'].str.zfill(6).map(lambda c:c+('.SH' if c[0] in '69' else ('.BJ' if c[0] in '48' else '.SZ')))
px['ind']=px['ticker'].map(yj.drop_duplicates('ticker',keep='last').set_index('ticker')['所处行业'])
px['name']=px['ticker'].map(yj.drop_duplicates('ticker',keep='last').set_index('ticker')['股票简称'])
td=sorted(px['date'].unique()); ti={d:i for i,d in enumerate(td)}

# 首次5板事件(每只票在窗口内第一次达到5板)
W=px[(px['date']>=S_D)&(px['date']<=E_D)&(px['nb']>=5)&px['ind'].notna()]
F=W.sort_values('date').groupby('ticker').first().reset_index()
F=F[['ticker','name','ind','date','nb','float_cap','buyable','T1','T3','T5']]
F['di']=F['date'].map(ti)
F=F.sort_values(['ind','date'])
# 同行业序号, 间隔>15个交易日重置
seq=[]; last={}
for _,r in F.iterrows():
    k=r['ind']
    if k in last and r['di']-last[k][1]<=15:
        s=last[k][0]+1
    else:
        s=1
    seq.append(s); last[k]=(s,r['di'])
F['seq']=seq
F.to_csv('backtest/2026-09-23-lianban/relay.csv',index=False)

def rep(x,tag):
    b=x[x['buyable']]
    if len(x)==0: print(f"{tag:<22} 0"); return
    s=f"{tag:<22} 事件{len(x):>3} 买得进{len(b):>3}({len(b)/len(x)*100:3.0f}%)"
    for k in ['T1','T3','T5']:
        v=b[k].dropna()
        if len(v)<3: s+=f" | {k} n={len(v)}"; continue
        t=v.mean()/(v.std(ddof=1)/math.sqrt(len(v))) if v.std(ddof=1)>0 else float('nan')
        s+=f" | {k} {v.mean()*100:+6.2f}% 胜{(v>0).mean()*100:3.0f}% t={t:5.2f}"
    print(s)

print(f"首次5板事件 {len(F)} 个, 涉及 {F['ind'].nunique()} 个行业\n")
print("【同行业内 第几只走出五连板】")
for s in [1,2,3]:
    rep(F[F['seq']==s], f"龙{['一','二','三'][s-1]}(第{s}只5板)")
rep(F[F['seq']>=2], "龙二及以后合计")

print("\n【接力明细: 同行业出现2只以上五连板的】")
multi=F[F['ind'].isin(F[F['seq']>=2]['ind'])].sort_values(['ind','date'])
d=multi[['ind','seq','date','ticker','name','float_cap','buyable','T1','T3','T5']].copy()
d['date']=d['date'].dt.strftime('%m-%d'); d['float_cap']=d['float_cap'].round(0)
for c in ['T1','T3','T5']: d[c]=(d[c]*100).round(1)
print(d.to_string(index=False))

print("\n【接力出现后, 该行业整体后续表现】")
big=px[px['date'].isin(td)]
IND=big.groupby(['date','ind'])['adj_close'].count().reset_index()
for n in (5,10):
    px[f'f{n}']=px.groupby('ticker')['adj_close'].shift(-n)/px['adj_close']-1
I=px.groupby(['date','ind'])[['f5','f10']].mean().reset_index()
M=px.groupby('date')[['f5','f10']].mean().add_suffix('_m').reset_index()
I=I.merge(M,on='date')
for n in (5,10): I[f'ex{n}']=I[f'f{n}']-I[f'f{n}_m']
E=F.merge(I,on=['date','ind'],how='left')
for s in [1,2,3]:
    y=E[E['seq']==s]
    line=f"  第{s}只五连板当天 n={len(y):>2}"
    for n in (5,10):
        v=y[f'ex{n}'].dropna()
        if len(v)<3: line+=f" | 行业后{n}日 n/a"; continue
        t=v.mean()/(v.std(ddof=1)/math.sqrt(len(v)))
        line+=f" | 行业后{n}日超额 {v.mean()*100:+6.2f}% 胜{(v>0).mean()*100:3.0f}% t={t:5.2f}"
    print(line)

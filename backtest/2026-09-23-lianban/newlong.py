#!/opt/homebrew/bin/python3.13
"""新龙特征: 首板涨停那天, 用起爆前可见的特征, 能否预测它会走成五连板? 窗口 2026-07-01 到 2026-09-23。

样本 = 每个"首板"(当日涨停且前一日未涨停), 标签 = 该连板段最终达到的最高板数
⛔所有特征只用 起爆日前一天(T-1) 及以前的数据, 无前视。标签是未来结果, 仅作分类目标。
特征: 起爆前流通市值 / 前5,10,20,40日涨幅 / 量比(当日成交额比前20日均) / 距60日最高收盘距离 / 前20日涨停次数 / 前20日成交额
"""
import math
import pandas as pd, numpy as np
S_D,E_D = pd.Timestamp('2026-07-01'), pd.Timestamp('2026-09-23')
px = pd.read_parquet('data/cn_hk_price_db/a_daily.parquet',
    columns=['date','ticker','open','close','adj_close','qfq_factor','amount','oshare'],
    filters=[('date','>=',pd.Timestamp('2026-03-01'))]).sort_values(['ticker','date'])
px['pc']=px.groupby('ticker')['close'].shift(1)
def lim(t):
    c=t[:6]
    return .20 if c[:3] in ('300','301','688','689') else (.30 if c[0] in ('4','8') else .10)
px['lim']=px['ticker'].map(lim)
px['zt']=px['close']>=(px['pc']*(1+px['lim'])).round(2)-0.011
px['blk']=(~px['zt']).groupby(px['ticker']).cumsum()
px['nb']=px.groupby(['ticker','blk']).cumcount()
m=(px['blk']==0)&px['zt']; px.loc[m,'nb']=px.loc[m,'nb']+1; px.loc[~px['zt'],'nb']=0
g=px.groupby('ticker')
# 该连板段的最高板数(标签)
px['segmax']=px.groupby(['ticker','blk'])['nb'].transform('max')
# 起爆前特征(T-1及以前)
px['流通亿']=(px['close']*px['oshare']/1e8)
px['pre_cap']=g['流通亿'].shift(1)
for n in [5,10,20,40]:
    px[f'pre_r{n}']=g['adj_close'].shift(1)/g['adj_close'].shift(1+n)-1
px['amt20']=g['amount'].transform(lambda s:s.shift(1).rolling(20).mean())
px['量比']=px['amount']/px['amt20']
px['hi60']=g['close'].transform(lambda s:s.shift(1).rolling(60).max())
px['距60高%']=px['pc']/px['hi60']-1
px['前20涨停次数']=g['zt'].transform(lambda s:s.shift(1).rolling(20).sum())
px['pre_amt']=px['amt20']/1e8
px['首板']=px['zt']&(g['zt'].shift(1)==False)
S=px[(px['首板'])&(px.date>=S_D)&(px.date<=E_D)&(px['amount']>=3e7)&px['pre_cap'].notna()].copy()
S['成龙']=S['segmax']>=5
yj=pd.read_csv('/tmp/bt0922/yjbb.csv',dtype={'股票代码':str})
yj['tk']=yj['股票代码'].str.zfill(6).map(lambda c:c+('.SH' if c[0] in '69' else ('.BJ' if c[0] in '48' else '.SZ')))
S['名称']=S.ticker.map(yj.drop_duplicates('tk',keep='last').set_index('tk')['股票简称'])
S.to_csv('backtest/2026-09-23-lianban/newlong.csv',index=False)
n1=len(S); n5=int(S['成龙'].sum())
print(f'7-9月 首板样本 {n1} 个, 其中最终走成5连板以上 {n5} 个, 基础概率 {n5/n1*100:.2f}%')
print()
FEAT=['pre_cap','pre_r5','pre_r10','pre_r20','pre_r40','量比','距60高%','前20涨停次数','pre_amt']
NAMES={'pre_cap':'起爆前流通亿','pre_r5':'起爆前5日%','pre_r10':'起爆前10日%','pre_r20':'起爆前20日%',
 'pre_r40':'起爆前40日%','量比':'首板日量比','距60高%':'距60日高%','前20涨停次数':'前20日涨停次数','pre_amt':'前20日均额亿'}
print('【成龙组 vs 未成龙组 特征对比(中位数)】')
print(f"{'特征':<16}{'成龙组':>10}{'未成龙':>10}{'差':>10}")
for f in FEAT:
    a=S[S['成龙']][f].dropna(); b=S[~S['成龙']][f].dropna()
    if len(a)<5: continue
    sc=100 if f.startswith('pre_r') or f=='距60高%' else 1
    print(f"{NAMES[f]:<16}{a.median()*sc:>10.1f}{b.median()*sc:>10.1f}{(a.median()-b.median())*sc:>10.1f}")
print()
print('【按特征分档 成龙概率】(基础概率 %.2f%%)'%(n5/n1*100))
def tab(f,bins,labs,sc=1):
    S['_b']=pd.cut(S[f]*sc,bins,labels=labs)
    r=S.groupby('_b',observed=True).agg(样本=('成龙','size'),成龙=('成龙','sum'))
    r['概率%']=(r['成龙']/r['样本']*100).round(2)
    r['相对基础']=(r['概率%']/(n5/n1*100)).round(2)
    print(f'-- {NAMES[f]}'); print(r.to_string()); print()
tab('pre_cap',[0,20,30,40,50,70,100,150,1e9],['<20','20-30','30-40','40-50','50-70','70-100','100-150','>150'])
tab('pre_r20',[-99,-10,0,10,25,50,100,999],['<-10','-10到0','0-10','10-25','25-50','50-100','>100'],100)
tab('pre_r40',[-99,-10,0,20,50,100,999],['<-10','-10到0','0-20','20-50','50-100','>100'],100)
tab('距60高%',[-99,-40,-25,-15,-8,-3,0,99],['<-40','-40到-25','-25到-15','-15到-8','-8到-3','-3到0','创新高'],100)
tab('前20涨停次数',[-1,0,1,2,4,99],['0次','1次','2次','3-4次','5次以上'])
tab('量比',[0,1,1.5,2.5,4,8,999],['<1','1-1.5','1.5-2.5','2.5-4','4-8','>8'])
tab('pre_amt',[0,1,2,4,8,20,1e9],['<1亿','1-2亿','2-4亿','4-8亿','8-20亿','>20亿'])

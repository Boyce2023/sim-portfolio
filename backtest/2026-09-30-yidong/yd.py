#!/opt/homebrew/bin/python3.13
"""科创板 10日偏离累计(区间首尾口径, 基准科创50) 越过+100% 的案例 vs 被压在95到100%的案例, 之后走势"""
import pandas as pd, numpy as np, json, urllib.request
u="https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh000688,day,2019-12-01,2026-09-30,2000,"
k=list(json.load(urllib.request.urlopen(u,timeout=15))['data'].values())[0]
I=pd.Series({pd.Timestamp(x[0]):float(x[2]) for x in (k.get('day') or k.get('qfqday'))}).sort_index()
px=pd.read_parquet('../../data/cn_hk_price_db/a_daily.parquet',columns=['date','ticker','open','close','adj_close'],filters=[('date','>=',pd.Timestamp('2020-01-01'))])
px=px[px.ticker.str.startswith('688')].sort_values(['ticker','date']).reset_index(drop=True)
px['idx']=px.date.map(I)
g=px.groupby('ticker')
px['cum']=(px.adj_close/g.adj_close.shift(10)-1)-(px.idx/g.idx.shift(10)-1)
px['cum_prev']=g.cum.shift(1)
px['age']=g.cumcount()
for n in [1,5,10,20]:
    px[f'f{n}']=g.adj_close.shift(-n)/px.adj_close-1
    px[f'fi{n}']=px.date.map(lambda d:np.nan)  # 占位
px['nextdate']=g.date.shift(-1)
px['o1']=g.open.shift(-1)/px.close-1
# 基准后续
Iv=I.values; Ii={d:i for i,d in enumerate(I.index)}
for n in [1,5,10,20]:
    px[f'fi{n}']=px.date.map(lambda d:(Iv[Ii[d]+n]/Iv[Ii[d]]-1) if d in Ii and Ii[d]+n<len(Iv) else np.nan)
    px[f'x{n}']=px[f'f{n}']-px[f'fi{n}']
px=px[px.age>=60]   # 剔除上市前60日(新股前5日无涨跌幅, 不纳入)
cross=px[(px.cum>=1.0)&(px.cum_prev<1.0)].copy()
# 同一股票20日内只取第一次
cross=cross.sort_values(['ticker','date']); cross['gap']=cross.groupby('ticker').date.diff().dt.days
cross=cross[(cross.gap.isna())|(cross.gap>30)]
near=px[(px.cum>=0.95)&(px.cum<1.0)].copy()
# 被压案例: 当日在95到100之间, 且之后10个交易日内没有越线
cross_keys=set(zip(px[px.cum>=1.0].ticker,px[px.cum>=1.0].date))
def never_cross(r):
    s=px[(px.ticker==r.ticker)&(px.date>r.date)].head(10)
    return not (s.cum>=1.0).any()
near=near.sort_values(['ticker','date']); near['gap']=near.groupby('ticker').date.diff().dt.days
near=near[(near.gap.isna())|(near.gap>30)]
near=near[near.apply(never_cross,axis=1)]
def summ(df,lab):
    print(f"\n【{lab}】 n={len(df)}  (停牌: 次一交易日距今>3个自然日的 {int(((df.nextdate-df.date).dt.days>4).sum())} 只)")
    for n in [1,5,10,20]:
        x=df[f'x{n}'].dropna(); f=df[f'f{n}'].dropna()
        print(f"  T+{n:<2} 绝对 均值{f.mean()*100:+6.2f}% 中位{f.median()*100:+6.2f}% 胜率{(f>0).mean()*100:4.1f}% | 超额科创50 均值{x.mean()*100:+6.2f}%  n={len(f)}")
    print(f"  次日开盘 均值{df.o1.mean()*100:+.2f}% 中位{df.o1.median()*100:+.2f}%")
summ(cross,'收盘直接越过+100%(未被控住)')
summ(near,'收盘被压在95到100%之间且之后10日未越线(控住)')
cross[['date','ticker','close','cum','o1','f1','f5','f10','f20']].sort_values('date').to_csv('cross_cases.csv',index=False)
print('\n越线案例(最近15个):'); print(cross.sort_values('date').tail(15)[['date','ticker','close','cum','f1','f5','f20']].round(3).to_string(index=False))

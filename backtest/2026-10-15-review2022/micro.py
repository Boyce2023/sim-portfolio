#!/opt/homebrew/bin/python3.13
"""①微盘股(每月初总市值最小400只等权, 月度换仓, 剔除ST与上市不足60日)2021-2022逐月, 对比沪深300成分代理(总市值最大300只等权)
②2021全年与2022各段行业中位收益 ③宁德时代与中际旭创路径对照 ④2022年2到10月微盘里的'稳涨低波'形态股(只作形态, 不作认定)"""
import pandas as pd,numpy as np
A=pd.read_parquet('../../data/cn_hk_price_db/a_daily.parquet',columns=['date','ticker','close','adj_close','oshare','amount'],filters=[('date','>=',pd.Timestamp('2020-10-01')),('date','<=',pd.Timestamp('2023-01-10'))])
A['mcap']=A.close*A.oshare/1e8   # 流通市值口径(库内只有流通股本)
P=A.pivot(index='date',columns='ticker',values='adj_close'); M=A.pivot(index='date',columns='ticker',values='mcap')
first=P.notna().idxmax()
I=pd.read_csv('industry.csv'); I['ticker']=I.code.str[3:]+'.'+I.code.str[:2].str.upper()
nm=I.set_index('ticker').code_name; st=nm.str.contains('ST',na=False)
months=pd.date_range('2021-01-01','2022-12-31',freq='MS'); rows=[]
for m in months:
    d0=P.index[P.index>=m][0]; nxt=m+pd.offsets.MonthBegin(1); d1=P.index[P.index<nxt][-1]
    cap=M.loc[d0].dropna(); age_ok=first.reindex(cap.index)<=d0-pd.Timedelta(days=90)
    cap=cap[age_ok & ~st.reindex(cap.index).fillna(False)]
    small=cap.nsmallest(400).index; big=cap.nlargest(300).index
    r=(P.loc[d1]/P.loc[d0]-1)
    # 月初d0收盘买到月末d1收盘
    rows.append(dict(月=m.strftime('%Y-%m'),微盘400=r.reindex(small).mean()*100,大盘300=r.reindex(big).mean()*100,全A中位=r.median()*100))
T=pd.DataFrame(rows).round(1); T['微盘累计']=((1+T.微盘400/100).cumprod()*100).round(1); T['大盘累计']=((1+T.大盘300/100).cumprod()*100).round(1)
print(T.to_string(index=False))
# ③路径
for tk,n in (('300750.SZ','宁德时代'),('300308.SZ','中际旭创')):
    s=P[tk].dropna(); print(n,'区间内最高',s.idxmax().date(),round(s.max(),2))
s=pd.read_parquet('../../data/cn_hk_price_db/a_daily.parquet',columns=['date','ticker','adj_close'],filters=[('ticker','in',['300750.SZ','300308.SZ']),('date','>=',pd.Timestamp('2020-06-01'))]).pivot(index='date',columns='ticker',values='adj_close')
for tk,n in (('300750.SZ','宁德时代'),('300308.SZ','中际旭创')):
    x=s[tk].dropna(); pk=x.idxmax() if tk=='300308.SZ' else x[:'2022-12-31'].idxmax()
    after=x[pk:]; lo=after.idxmin() if tk=='300308.SZ' else x[pk:'2022-12-31'].idxmin()
    print(f'{n}: 峰值{pk.date()} 峰后最低{lo.date()} 回撤{(x[lo]/x[pk]-1)*100:.1f}% 峰前一年涨幅{(x[pk]/x[:pk - pd.Timedelta(days=365)].iloc[-1]-1)*100:.0f}% 当前/区间末{x.index[-1].date()} 距峰{(x.iloc[-1]/x[pk]-1)*100:.1f}%')
    if tk=='300750.SZ':
        for d in ('2021-12-03','2022-01-28','2022-04-26','2022-07-05','2022-10-31'):
            dd=x.index[x.index.get_indexer([pd.Timestamp(d)],method='pad')[0]]; print('   ',d,round(x[dd],2),f'距峰{(x[dd]/x[pk]-1)*100:+.1f}%')
    else:
        m=x.resample('ME').last(); print('   中际旭创月末(复权):',[(i.strftime('%y-%m'),round(v,1)) for i,v in m.tail(14).items()])
# ④稳涨低波形态: 2022-01-28 到 10-31, 区间涨幅>50%, 日收益波动率低于全市场中位, 单日涨幅>9%的天数<=3
a,b=P.index[P.index.get_indexer([pd.Timestamp('2022-01-28')],method='pad')[0]],P.index[P.index.get_indexer([pd.Timestamp('2022-10-31')],method='pad')[0]]
seg=P.loc[a:b]; ret=seg.pct_change(); tot=seg.iloc[-1]/seg.iloc[0]-1; vol=ret.std(); big=(ret>0.09).sum()
cap0=M.loc[a]
c=pd.DataFrame({'涨幅':tot,'日波动':vol,'涨停级天数':big,'起始流通市值':cap0,'名':nm.reindex(tot.index)}).dropna()
z=c[(c.涨幅>0.5)&(c.日波动<vol.median())&(c.涨停级天数<=3)].sort_values('涨幅',ascending=False)
print('\n稳涨低波形态(2022-01-28到10-31涨超50%, 日波动低于全市场中位, 涨停级天数<=3):',len(z))
print(z.head(20).assign(涨幅=lambda x:(x.涨幅*100).round(0),日波动=lambda x:(x.日波动*100).round(2),起始流通市值=lambda x:x.起始流通市值.round(0)).to_string())
print('全市场日波动中位%.2f%%'%(vol.median()*100))

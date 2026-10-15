#!/opt/homebrew/bin/python3.13
"""打板市值研究 延长版: 2022-01 至今, 口径沿用 2026-09-07-mcap/grid_v5.py:
首板 = 当日按实际适用涨跌幅收盘涨停 且 前一日非涨停(前一日为除权日时不算涨停); 除权日 bar 保留但不参与涨停判定;
流通市值 = 首板当日 流通股本×收盘(亿); 10日最大涨幅 = 首板后1到10个交易日最高价相对首板收盘(不足10日按已有天数);
连板数 = 从首板日起连续涨停天数(含首板日). 涨跌幅: 北交所30%, 创业板科创板20%, 沪深主板风险警示5%(2026-07-06起10%), 其余10%; 上市前5个交易日不设限跳过.
与原版的差别: 风险警示用逐日标记(2022年宝硕 isST, 2023-01起 feat.parquet, 2026-09-23之后沿用最后已知值), 原版用当时的静态名单; 数据源统一为本地日线库(原版2025-01到2026-09-04用 univ 库)."""
import pandas as pd,numpy as np,json,datetime,sys
DB='../../data/cn_hk_price_db/'
A=pd.read_parquet(DB+'a_daily.parquet',columns=['date','ticker','open','high','low','close','oshare','qfq_factor'],filters=[('date','>=',pd.Timestamp('2021-11-15'))])
B=pd.read_parquet(DB+'bj_daily.parquet',columns=['date','ticker','open','high','low','close','oshare','qfq_factor'],filters=[('date','>=',pd.Timestamp('2021-11-15'))])
A=pd.concat([A,B],ignore_index=True)
L0=pd.concat([pd.read_parquet(DB+'a_daily.parquet',columns=['date','ticker']),pd.read_parquet(DB+'bj_daily.parquet',columns=['date','ticker'])]).groupby('ticker').date.min()
A=A.sort_values(['ticker','date']).reset_index(drop=True); A['code']=A.ticker.str[:6]
# 逐日ST
S1=pd.read_parquet('st2022.parquet') if __import__('os').path.exists('st2022.parquet') else pd.DataFrame(columns=['ticker','date','isST'])
S1['code']=S1.ticker.str[:6]
F=pd.read_parquet('../2026-09-29-wf/feat.parquet',columns=['code','date','isST'])
S=pd.concat([S1[['code','date','isST']],F[['code','date','isST']]]).drop_duplicates(['code','date'],keep='last')
A=A.merge(S,on=['code','date'],how='left')
A['isST']=A.groupby('code').isST.ffill()
static=set(json.load(open('../../data/st_universe.json'))['codes'])
A['isST']=A.isST.fillna(A.code.isin(static).astype(float))
# 涨跌幅
c3=A.code.str[:3]; bj=A.ticker.str.endswith('.BJ'); big=c3.isin(['300','301','688','689'])
st_l=np.where(A.date>=pd.Timestamp('2026-07-06'),0.10,0.05)
A['L']=np.where(bj,0.30,np.where(big,0.20,np.where(A.isST==1,st_l,0.10)))
g=A.groupby('ticker')
A['k']=g.cumcount(); A['first_seen']=A.ticker.map(L0)
A['tday']=(A.date-A.first_seen).dt.days
nth=A.groupby('ticker').cumcount()  # 本窗口内序号
# 上市前5个交易日: 用上市日在窗口内时的序号判断
listed_in=A.first_seen>=pd.Timestamp('2021-11-15')
A.loc[listed_in & (nth<5),'L']=np.nan
A['pc']=g.close.shift(1); A['pf']=g.qfq_factor.shift(1)
A['exr']=(A.qfq_factor-A.pf).abs()>1e-9
A['zt']=(A.close>=(A.pc*(1+A.L)).round(2)-0.02)&((A.close/A.pc-1)>=A.L-0.004)&A.pc.gt(0)&A.L.notna()&~A.exr
A['zt_prev']=g.zt.shift(1).fillna(False).astype(bool)
A['mcap']=A.oshare*A.close/1e8
E=A[A.zt & ~A.zt_prev & (A.date>=pd.Timestamp('2022-01-01')) & A.mcap.gt(0) & A.mcap.lt(1e4)].copy()
# 10日最大涨幅(原始价, 同原版)
hi=[g.high.shift(-k) for k in range(1,11)]
H=pd.concat(hi,axis=1).max(axis=1,skipna=True)
E['hi10']=(H.loc[E.index]/E.close-1)*100
E['avail']=pd.concat([g.close.shift(-k).notna() for k in range(1,11)],axis=1).sum(axis=1).loc[E.index]
E=E[E.avail>=1]
# 连板数
zt=A.zt.values; tk=A.ticker.values; fin=[]
for i in E.index:
    n=1; j=i+1
    while j<len(A) and tk[j]==tk[i] and zt[j]: n+=1; j+=1
    fin.append(n)
E['final']=fin; E['m']=E.date.dt.strftime('%Y-%m')
out=E[['m','ticker','date','mcap','hi10','final','avail','isST','L']].copy(); out['date']=out.date.dt.strftime('%Y-%m-%d')
out.to_parquet('firstboard_ext.parquet')
print('首板样本',len(out),out.m.min(),out.m.max(),'末日',out.date.max(),'ST首板',int((out.isST==1).sum()),'北交所',int(out.ticker.str.endswith('.BJ').sum()))
print(out.groupby('m').size().to_string())

#!/opt/homebrew/bin/python3.13
"""板块日度面板: 申万二级(按计入日期逐日对齐, 不用今天的分类回填过去), 每日涨停数/强势数(涨停或涨幅>=9.9%)/二板数/等权收益
数据: wf 面板(含逐日 isST 与除权前收) 到 09-23, 09-24 到 09-30 从价格库补"""
import pandas as pd, numpy as np
W='../2026-09-29-wf/'
P=pd.read_parquet(W+'feat.parquet',columns=['code','date','open','high','low','close','prevc','isST','adjf','amount'])
P=P[P.date>='2024-06-01']
# 补 09-24 之后
A=pd.read_parquet('../../data/cn_hk_price_db/a_daily.parquet',columns=['date','ticker','open','high','low','close','adj_close','amount'],filters=[('date','>=',pd.Timestamp('2026-09-15'))])
A=A[A.ticker.str.endswith(('.SH','.SZ'))].copy(); A['code']=A.ticker.str[:6]; A=A.sort_values(['code','date'])
A['prevc']=A.groupby('code').adj_close.shift(1)/A.adj_close*A.close
last=P.sort_values('date').groupby('code').tail(1).set_index('code')
A=A[A.date>P.date.max()]; A['isST']=A.code.map(last.isST).fillna(0); A['adjf']=np.nan
P=pd.concat([P,A[P.columns]],ignore_index=True).sort_values(['code','date']).reset_index(drop=True)
P['nth']=P.groupby('code').cumcount()          # 截至当日在面板里的第几天(新股前5天无涨跌幅, 剔除)
big=P.code.str[:3].isin(['300','301','688','689'])
P['lim']=np.where(big,0.2,np.where(P.isST==1,0.05,0.1))
P['zt_px']=(P.prevc*(1+P.lim)).round(2)
P['r']=P.close/P.prevc-1
P['zt']=(P.close>=P.zt_px-0.011)&P.prevc.notna()
P['strong']=P.zt|(P.r>=0.099)
P['zt_prev']=P.groupby('code').zt.shift(1).fillna(False).astype(bool)
P['lb2']=P.zt&P.zt_prev
P=P[(P.nth>=5)&P.prevc.notna()&(P.open>0)]
# 申万分类逐日对齐
S=pd.read_excel('sw_stock.xls',dtype=str); S['start']=pd.to_datetime(S['计入日期']); S=S.rename(columns={'股票代码':'code'}).sort_values('start')
C=pd.read_excel('sw_code.xls',dtype=str).set_index('行业代码')
P=P.sort_values('date')
P=pd.merge_asof(P,S[['code','start','行业代码']],left_on='date',right_on='start',by='code',direction='backward')
P=P[P['行业代码'].notna()]
P['l2']=P['行业代码'].str[:4]+'00'; P['l2n']=P.l2.map(C['二级行业名称']); P['l1n']=(P['行业代码'].str[:2]+'0000').map(C['一级行业名称'])
P['ac']=P.close*P.adjf; P['ao']=P.open*P.adjf
P.to_parquet('stock_panel.parquet')
G=P.groupby(['date','l2']).agg(l2n=('l2n','first'),l1n=('l1n','first'),n=('code','size'),zt=('zt','sum'),strong=('strong','sum'),lb2=('lb2','sum'),ew=('r','mean')).reset_index()
G.to_parquet('sector_daily.parquet')
print(P.date.min(),P.date.max(),'股票日',len(P),'板块数',G.l2.nunique(),'无分类剔除后')
print(G[G.date==G.date.max()].sort_values('strong',ascending=False).head(5))

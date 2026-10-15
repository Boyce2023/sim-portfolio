#!/opt/homebrew/bin/python3.13
"""2022年微盘股逐月收益, 两种口径: A=月度换仓(上月末流通市值最小400只等权, 上月末收盘到本月末收盘); B=日度换仓(每日按前一日流通市值取最小400只等权, 近似万得微盘股指数做法).
剔除: 当时为ST(取 feat.parquet 的逐日isST, 缺失回落为最后已知值)、上市不足90天. 对照: 流通市值最大300只等权."""
import pandas as pd,numpy as np
A=pd.read_parquet('../../data/cn_hk_price_db/a_daily.parquet',columns=['date','ticker','close','adj_close','oshare'],filters=[('date','>=',pd.Timestamp('2021-09-01')),('date','<=',pd.Timestamp('2023-01-05'))])
A['code']=A.ticker.str[:6]; A['cap']=A.close*A.oshare
F=pd.read_parquet('../2026-09-29-wf/feat.parquet',columns=['code','date','isST'])
A=A.merge(F,on=['code','date'],how='left'); last=F.sort_values('date').groupby('code').tail(1).set_index('code').isST
A['isST']=A.isST.fillna(A.code.map(last)).fillna(0)
P=A.pivot(index='date',columns='ticker',values='adj_close'); C=A.pivot(index='date',columns='ticker',values='cap'); S=A.pivot(index='date',columns='ticker',values='isST')
first=P.notna().idxmax(); R=P.pct_change()
dates=P.index
elig=(S==0)&C.notna()&(np.array(dates)[:,None]>=(first.values+np.timedelta64(90,'D'))[None,:])
Ce=C.where(elig)
# B 日度
rank=Ce.rank(axis=1,method='first'); sel=(rank<=400).shift(1)          # 用前一日市值选股, 吃当日收益
dB=(R.where(sel.fillna(False))).mean(axis=1)
rankB=Ce.rank(axis=1,ascending=False,method='first'); big=(rankB<=300).shift(1); dBig=R.where(big.fillna(False)).mean(axis=1)
rows=[]
for m in pd.date_range('2022-01-01','2022-12-01',freq='MS'):
    pe=dates[dates<m][-1]; me=dates[dates<m+pd.offsets.MonthBegin(1)][-1]
    cap=Ce.loc[pe].dropna(); small=cap.nsmallest(400).index; large=cap.nlargest(300).index
    r=P.loc[me]/P.loc[pe]-1
    mask=(dates>pe)&(dates<=me)
    rows.append({'月份':m.strftime('%Y-%m'),'微盘_月度换仓':r.reindex(small).mean()*100,'微盘_日度换仓':((1+dB[mask]).prod()-1)*100,
                 '大盘300_日度':((1+dBig[mask]).prod()-1)*100,'全A中位':r.median()*100})
T=pd.DataFrame(rows)
for c in ['微盘_月度换仓','微盘_日度换仓','大盘300_日度']: T[c+'_累计']=((1+T[c]/100).cumprod()-1)*100
pd.set_option('display.width',200); print(T.round(1).to_string(index=False))

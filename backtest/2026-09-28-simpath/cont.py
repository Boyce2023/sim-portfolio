#!/opt/homebrew/bin/python3.13
"""已走出台阶的票会不会延续: 信号日 d = 台阶走了 5 天
   条件: 近5日涨 +12%..+30%, 近5日0涨停, 近5日上涨>=4天, 单日最大<=8%; 台阶前(d-5之前20日)箱体<=25% 且前20日涨幅 -10%..+15%
   结果: d 收盘后 5/10 日"""
import pandas as pd, numpy as np
px=pd.read_parquet('data/cn_hk_price_db/a_daily.parquet',columns=['date','ticker','close','turn','oshare'],filters=[('date','>=',pd.Timestamp('2026-03-01'))])
px['code']=px.ticker.str[:6]; px=px[~px.code.str.startswith(('8','4','92'))].sort_values(['code','date']).reset_index(drop=True)
L=np.where(px.code.str.startswith(('688','300','301')),.2,.1)
g=px.groupby('code'); px['chg']=g.close.pct_change(fill_method=None)
px['zt']=(px.close>=(g.close.shift(1)*(1+L)).round(2)-0.011).astype(int)
px['r5']=g.close.transform(lambda s:s/s.shift(5)-1)
px['zt5']=g.zt.transform(lambda s:s.rolling(5).sum()); px['up5']=g.chg.transform(lambda s:(s>0).rolling(5).sum()); px['mx5']=g.chg.transform(lambda s:s.rolling(5).max())
px['box']=g.close.transform(lambda s:s.shift(5).rolling(20).max()/s.shift(5).rolling(20).min()-1)
px['pre']=g.close.transform(lambda s:s.shift(5)/s.shift(25)-1)
for n in [5,10]: px[f'f{n}']=g.close.shift(-n)/px.close-1
sig=px.r5.between(.12,.30)&(px.zt5==0)&(px.up5>=4)&(px.mx5<=.08)&(px.box<=.25)&px.pre.between(-.10,.15)
for lab,a,b in [('7-9月','2026-07-01','2026-09-09'),('8-9月','2026-08-05','2026-09-09')]:
    T=px[(px.date>=a)&(px.date<=b)&px.f10.notna()]
    for nm,m in [('全市场',pd.Series(True,index=T.index)),('台阶第5天',sig.reindex(T.index))]:
        x=T[m]; print(f"{lab} {nm:<8} n={len(x):>6}  后5日 {x.f5.mean()*100:+5.2f}% 胜率{(x.f5>0).mean()*100:4.1f}%  后10日 {x.f10.mean()*100:+5.2f}% (中位{x.f10.median()*100:+5.2f}%) 胜率{(x.f10>0).mean()*100:4.1f}%  后10日>=10%: {(x.f10>=.10).mean()*100:4.1f}%")
    x=T[sig.reindex(T.index)]; print('   去重股票数', x.code.nunique())

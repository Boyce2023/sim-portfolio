#!/opt/homebrew/bin/python3.13
"""策略一止盈档位: 样本=2026-09-22 策略一骨架回测的全部信号(2026-07-20到09-14, 总市值120到350亿且信号日涨>5%), 
信号日次日开盘买(开盘涨停剔除); 盘中最高价触及买价*(1+x)即按该价卖; 否则收盘跌破买价7%当日收盘卖; 否则持有到第4个交易日收盘卖(T+4)。
最早卖点为买入次日(T+1制度)。用复权价。"""
import pandas as pd,numpy as np
T=pd.read_csv('../2026-09-22-strategy1/trades.csv',parse_dates=['date'])
T=T.drop_duplicates(['date','ticker'])
A=pd.read_parquet('../../data/cn_hk_price_db/a_daily.parquet',columns=['date','ticker','open','high','close','adj_close'],filters=[('date','>=',pd.Timestamp('2026-07-01'))])
A['f']=A.adj_close/A.close; A=A.sort_values(['ticker','date'])
G={k:g.reset_index(drop=True) for k,g in A.groupby('ticker')}
def run(sub,x):
    out=[]
    for r in sub.itertuples():
        g=G.get(r.ticker)
        if g is None: continue
        idx=g.index[g.date==r.date]
        if not len(idx): continue
        i=idx[0]+1
        if i+4>len(g): continue
        prevc=g.close[i-1]; big=r.ticker[:3] in('300','301','688')
        if g.open[i]>=round(prevc*(1.2 if big else 1.1),2)-0.011: continue
        buy=g.open[i]*g.f[i]; res=None
        for k in range(1,5):           # 买入后第1到第4个交易日
            j=i+k
            if x is not None and g.high[j]*g.f[j]>=buy*(1+x): res=x; break
            c=g.close[j]*g.f[j]/buy-1
            if c<=-0.07 or k==4: res=c; break
        out.append(res)
    return pd.Series(out)
for lab,sub in [('全部信号(A)',T),('加基本面(B)',T[T.fund]),('加基本面加主线(C1)',T[T.fund&T.main1])]:
    print('==',lab,'信号',len(sub))
    for x in [None,0.02,0.03,0.04,0.05,0.07,0.10]:
        v=run(sub,x); w,l=v[v>0],v[v<=0]
        print(f"  止盈{'无' if x is None else f'{x*100:.0f}%'}: n={len(v)} 胜率{(v>0).mean()*100:.0f}% 均值{v.mean()*100:+.2f}% 中位{v.median()*100:+.2f}% 赔率{w.mean()/abs(l.mean()):.2f}")

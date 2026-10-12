#!/opt/homebrew/bin/python3.13
"""五板次日限价细网格(2026-07起): 每个挂价的成交率, 成交后收益, 以及每次机会的期望(成交率×成交后均值, 未成交记0)"""
import pandas as pd,numpy as np
from common import panel
P=panel('2026-05-01'); P=P[P.nth>=5]
E=P[(P.streak==5)&P.open1.notna()&(P.date>='2026-07-01')].copy()
E=E[~((E.open1>=E.zt_px1-0.011)&(E.low1>=E.zt_px1-0.011))]
print('可买事件',len(E))
rows=[]
for x in [i/100 for i in range(-9,10)]+['开盘']:
    if x=='开盘': fill=E.open1.values
    else:
        lp=(E.close*(1+x)).round(2).values
        fill=np.where(E.open1<=lp,E.open1,np.where(E.low1<=lp,lp,np.nan))
    buy=fill*E.adjf1.values
    for lab,ex in [('第三天收盘卖',E.close2*E.adjf2),('第三天开盘卖',E.open2*E.adjf2),('拿5天',E.close5*E.adjf5)]:
        r=pd.Series(ex.values/buy-1).dropna()
        fr=np.isfinite(buy).mean()
        rows.append([x if x=='开盘' else f'{x*100:+.0f}%',lab,f'{fr*100:.0f}%',len(r),f'{(r>0).mean()*100:.0f}%',f'{r.mean()*100:+.2f}%',f'{r.median()*100:+.2f}%',f'{fr*r.mean()*100:+.2f}%'])
T=pd.DataFrame(rows,columns=['挂价(相对前收)','卖法','成交率','笔数','胜率','成交后均值','成交后中位','每次机会期望'])
pd.set_option('display.width',200)
print(T[T.卖法=='第三天收盘卖'].to_string(index=False)); print(T[T.卖法=='拿5天'].to_string(index=False))
T.to_csv('grid_jul.csv',index=False,encoding='utf-8-sig')

#!/opt/homebrew/bin/python3.13
"""五板次日(T+1)挂限价买: 限价=T日收盘*(1+x); T+1 开盘低于限价则按开盘价成交, 否则盘中最低价触及限价才按限价成交。
一字板(开盘=最低=涨停价)买不进剔除。卖出口径: T+2开盘 / T+2收盘 / 收尾正持负卖(最长10日) / 持5日收盘。用复权价算收益。"""
import pandas as pd, numpy as np
from common import panel
P=panel('2026-05-01')
P=P[P.nth>=5]
E=P[(P.streak==5)&P.open1.notna()&(P.date>='2026-07-01')].copy()
E['yizi']=(E.open1>=E.zt_px1-0.011)&(E.low1>=E.zt_px1-0.011)
print('五板事件',len(E),'其中次日一字',int(E.yizi.sum()),'区间',E.date.min().date(),E.date.max().date())
E=E[~E.yizi]
def run(x):
    lp=(E.close*(1+x)).round(2)
    fill=np.where(E.open1<=lp,E.open1,np.where(E.low1<=lp,lp,np.nan))
    buy=fill*E.adjf1
    r={}
    r['T+2开盘']=E.open2*E.adjf2/buy-1
    r['T+2收盘']=E.close2*E.adjf2/buy-1
    r['持5日收盘']=E.close5*E.adjf5/buy-1
    # 收尾正持负卖: 从T+2起每日看收盘对前收, 不为正则当日收盘卖, 最多到T+10
    out=np.full(len(E),np.nan)
    for i,(idx,row) in enumerate(E.iterrows()):
        if np.isnan(fill[i]): continue
        prev=row.close1*row.adjf1
        for k in range(2,11):
            c=row[f'close{k}']*row[f'adjf{k}']
            if pd.isna(c): break
            if c<=prev or k==10: out[i]=c/buy.iloc[i]-1; break
            prev=c
    r['收尾正持负卖']=pd.Series(out,index=E.index)
    return pd.Series(fill,index=E.index),r
rows=[]
for x in [-0.07,-0.05,-0.03,0.0,0.03,0.05,0.07,'开盘']:
    if x=='开盘':
        fill=E.open1; buy=fill*E.adjf1
        r={'T+2开盘':E.open2*E.adjf2/buy-1,'T+2收盘':E.close2*E.adjf2/buy-1,'持5日收盘':E.close5*E.adjf5/buy-1}
        lab='开盘直接买'
    else:
        fill,r=run(x); lab=f'限价 昨收{x*100:+.0f}%'
    fr=fill.notna().mean()
    for k,v in r.items():
        v=v.dropna(); w,l=v[v>0],v[v<=0]
        a=v[E.loc[v.index,'date']<'2026-08-15']; b=v[E.loc[v.index,'date']>='2026-08-15']
        rows.append([lab,f'{fr*100:.0f}%',k,len(v),f'{(v>0).mean()*100:.0f}%',f'{v.mean()*100:+.2f}%',f'{v.median()*100:+.2f}%',f'{w.mean()/abs(l.mean()):.2f}' if len(l) else '',f'{a.mean()*100:+.2f}%({len(a)})',f'{b.mean()*100:+.2f}%({len(b)})'])
T=pd.DataFrame(rows,columns=['买法','成交率','卖法','笔数','胜率','均值','中位','赔率','7月到8月14日均值','8月15日后均值'])
pd.set_option('display.width',250); print(T.to_string(index=False))
T.to_csv('result.csv',index=False,encoding='utf-8-sig')

# 对照: 次日盘中触及涨停价时以涨停价买(冲第6板), 卖法同上 + 规则乙(T+2封板持到收盘否则开盘卖)
m=E.high1>=E.zt_px1-0.011
F=E[m]; buy=F.zt_px1*F.adjf1
sealed2=F.close2>=F.zt_px2-0.011
rr={'T+2开盘':F.open2*F.adjf2/buy-1,'T+2收盘':F.close2*F.adjf2/buy-1,
    '乙 T+2封板持到收盘否则开盘卖':np.where(sealed2,F.close2*F.adjf2,F.open2*F.adjf2)/buy-1}
out=[]
for idx,row in F.iterrows():
    b=row.zt_px1*row.adjf1; prev=row.close1*row.adjf1; v=np.nan
    for k in range(2,11):
        c=row[f'close{k}']*row[f'adjf{k}']
        if pd.isna(c): break
        if c<=prev or k==10: v=c/b-1; break
        prev=c
    out.append(v)
rr['收尾正持负卖']=pd.Series(out,index=F.index)
print('\n次日触板买(冲6板) 触板率',f'{m.mean()*100:.0f}%')
for k,v in rr.items():
    v=pd.Series(v,index=F.index).dropna(); w,l=v[v>0],v[v<=0]
    a=v[F.loc[v.index,'date']<'2026-08-15']; b=v[F.loc[v.index,'date']>='2026-08-15']
    print(f'  {k}: n={len(v)} 胜率{(v>0).mean()*100:.0f}% 均值{v.mean()*100:+.2f}% 中位{v.median()*100:+.2f}% 赔率{w.mean()/abs(l.mean()):.2f} | 7月到8月14日 {a.mean()*100:+.2f}% 8月15日后 {b.mean()*100:+.2f}%')

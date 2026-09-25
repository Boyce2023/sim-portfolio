#!/opt/homebrew/bin/python3.13
"""Buwen 09-24 口径: 按价格全部数字(去掉小数点)判形态, 排除 .00
   AAA(7.77) AAAA(33.33) ABAB(26.26) AABB(33.55) CABAB(125.25) ABABCD(1212.xx) ABCDCD(1234.34)"""
import pandas as pd, numpy as np
from scipy import stats
def pat(p):
    if p!=p or p<=0: return None
    s=f'{p:.2f}'
    if s.endswith('.00'): return None
    d=s.replace('.','')
    n=len(d)
    if n==3 and len(set(d))==1: return 'AAA'
    if n==4:
        if len(set(d))==1: return 'AAAA'
        if d[:2]==d[2:] and d[0]!=d[1]: return 'ABAB'
        if d[0]==d[1] and d[2]==d[3] and d[0]!=d[2]: return 'AABB'
    if n==5 and d[1:3]==d[3:5]: return 'CABAB'
    if n==6:
        if d[2:4]==d[4:6]: return 'ABCDCD'
        if d[0:2]==d[2:4]: return 'ABABCD'
    return None
if __name__=='__main__':
    t=pd.read_csv('/tmp/close0924.csv'); t['p']=t['price'].map(pat)
    print(f"今日 09-24  全市场 {len(t)} 只, 命中 {t['p'].notna().sum()} 只 = {t['p'].notna().mean()*100:.2f}%")
    print('  分形态:',t['p'].value_counts().to_dict())
    t['len']=t['price'].map(lambda p:len(f'{p:.2f}'.replace('.','')))
    print('\n按价格位数: 只数 / 命中 / 命中率 / 理论')
    theo={3:'1.0%(AAA 9/900)',4:'约1.8%(ABAB+AABB+AAAA)',5:'1.0%(CABAB)',6:'约2.0%(ABABCD+ABCDCD)'}
    for L,g in t.groupby('len'):
        print(f"  {L}位数字 {len(g):>5} 只  命中 {g['p'].notna().sum():>3}  {g['p'].notna().mean()*100:.2f}%   理论 {theo.get(L,'')}")
    # 三年
    px=pd.read_parquet('data/cn_hk_price_db/a_daily.parquet',columns=['date','ticker','close','adj_close','amount'],
       filters=[('date','>=',pd.Timestamp('2023-06-01'))]).sort_values(['ticker','date']).reset_index(drop=True)
    px['p']=px['close'].map(pat); px['hit']=px['p'].notna()
    D=px[px.date>=pd.Timestamp('2023-09-25')].groupby('date').agg(n=('ticker','size'),h=('hit','sum'))
    D['pct']=D['h']/D['n']*100
    print(f"\n三年 {len(D)} 天: 每天命中 均值 {D['h'].mean():.0f} 只 ({D['pct'].mean():.2f}%)  最少 {D['h'].min()} 只  最多 {D['h'].max()} 只  标准差 {D['pct'].std():.2f}pp")
    today=t['p'].notna().mean()*100
    print(f"今日 {today:.2f}% 在三年里排第 {(D['pct']>today).sum()+1} / {len(D)+1}  (偏离 {(today-D['pct'].mean())/D['pct'].std():+.2f}σ)")
    g=px.groupby('ticker')['adj_close']
    for n in [1,5,20]: px[f'f{n}']=(g.shift(-n)/px['adj_close']-1)*100
    px['r5']=(px['adj_close']/g.shift(5)-1)*100
    W=px[(px.date>=pd.Timestamp('2023-09-25'))&(px.date<=pd.Timestamp('2026-09-23'))&(px.amount>=1e7)]
    print('\n个股之后收益 (三年, 成交额>1000万):')
    for lab,s in [('全部',W),('前5日涨>15%',W[W.r5>15])]:
        a,b=s[s.hit],s[~s.hit]
        for c in ['f1','f5','f20']:
            tt,pp=stats.ttest_ind(a[c].dropna(),b[c].dropna(),equal_var=False)
            print(f"  {lab:<10}{c:>4}: 对子 {a[c].mean():+.3f}% (n={len(a)})  其余 {b[c].mean():+.3f}%  差 {a[c].mean()-b[c].mean():+.3f}pp  p={pp:.3f}")
    D['mk']=None

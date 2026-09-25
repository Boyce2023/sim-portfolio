#!/opt/homebrew/bin/python3.13
"""显眼对子(ABAB + AAAA全同) 单独测 — 他举的四只全属这类, 基础概率约1%不是9.5%
   矩子26.26=ABAB 康达15.15=ABAB 近岸125.25=ABAB 新华传媒7.77=AAAA全同"""
import pandas as pd, numpy as np
from scipy import stats
pd.set_option('display.width',210)
def dztype(p):
    if p!=p or p<=0: return None
    s=f'{p:.2f}'; i,f=s.split('.')
    if f=='00': return None
    if f[0]==f[1]:
        if len(set(i+f))==1: return 'AAAA全同'
        if len(i)>=2 and i[-2:]==f: return 'ABAB'
        if len(i)>=2 and i[-2]==i[-1]: return 'AABB'
        return '尾数对子'
    if len(i)>=2 and i[-2:]==f: return 'ABAB'
    return None
S,E=pd.Timestamp('2023-09-25'),pd.Timestamp('2026-09-23')
px=pd.read_parquet('data/cn_hk_price_db/a_daily.parquet',
   columns=['date','ticker','close','adj_close','amount'],
   filters=[('date','>=',pd.Timestamp('2023-06-01'))]).sort_values(['ticker','date']).reset_index(drop=True)
px['dz']=px['close'].map(dztype)
px['xy']=px['dz'].isin(['ABAB','AAAA全同'])        # 显眼对子
g=px.groupby('ticker')['adj_close']
for n in [1,3,5,10,20]: px[f'f{n}']=(g.shift(-n)/px['adj_close']-1)*100
px['r20']=(px['adj_close']/g.shift(20)-1)*100
px['r5']=(px['adj_close']/g.shift(5)-1)*100
W=px[(px['date']>=S)&(px['date']<=E)&(px['amount']>=1e7)].copy()

print('='*86); print('显眼对子 基础概率与市场层'); print('='*86)
D=px[(px.date>=S)&(px.date<=E)].groupby('date').agg(总数=('ticker','size'),显眼=('xy','sum'))
D['占比%']=D['显眼']/D['总数']*100
print(f"{len(D)}个交易日  显眼对子占比 均值 {D['占比%'].mean():.3f}%  中位 {D['占比%'].median():.3f}%  标准差 {D['占比%'].std():.3f}%")
print(f"  分位 90%={np.percentile(D['占比%'],90):.3f}  95%={np.percentile(D['占比%'],95):.3f}  99%={np.percentile(D['占比%'],99):.3f}  max={D['占比%'].max():.3f}")
px['r']=px.groupby('ticker')['adj_close'].pct_change(fill_method=None)
idx=(1+px.groupby('date')['r'].mean().fillna(0)).cumprod()
for n in [1,3,5,10,20]: D[f'后{n}日%']=(idx.shift(-n)/idx-1).reindex(D.index)*100
D['档']=pd.qcut(D['占比%'],[0,.5,.8,.95,1.0],labels=['低50%','50-80%','80-95%','最高5%'])
print(D.groupby('档',observed=True).agg(天数=('占比%','size'),平均占比=('占比%','mean'),
    后1日=('后1日%','mean'),后5日=('后5日%','mean'),后10日=('后10日%','mean'),后20日=('后20日%','mean')).round(2).to_string())

print('\n'+'='*86); print('个股层: 显眼对子 vs 全部非显眼 (成交额>1000万)'); print('='*86)
q=W.groupby('xy').agg(样本=('close','size'),后1日=('f1','mean'),后3日=('f3','mean'),后5日=('f5','mean'),后10日=('f10','mean'),后20日=('f20','mean'))
q.index=['其余','显眼对子']; print(q.round(3).to_string())

print('\n'+'='*86); print('对子"顶": 按前20日涨幅分档, 显眼对子 vs 同档非对子'); print('='*86)
bins=[-100,0,10,20,30,50,1e4]; lab=['跌','0-10%','10-20%','20-30%','30-50%','>50%']
W['涨幅档']=pd.cut(W['r20'],bins=bins,labels=lab)
rows=[]
for l in lab:
    s=W[W['涨幅档']==l]; a,b=s[s.xy],s[~s.xy]
    if len(a)<30: continue
    def ts(x,y,c):
        t,p=stats.ttest_ind(s[s.xy][c].dropna(),s[~s.xy][c].dropna(),equal_var=False); return p
    rows.append(dict(涨幅档=l,显眼样本=len(a),对照样本=len(b),
        显眼后5日=a['f5'].mean(),对照后5日=b['f5'].mean(),差5=a['f5'].mean()-b['f5'].mean(),p5=ts(a,b,'f5'),
        显眼后20日=a['f20'].mean(),对照后20日=b['f20'].mean(),差20=a['f20'].mean()-b['f20'].mean(),p20=ts(a,b,'f20')))
print(pd.DataFrame(rows).round(3).to_string(index=False))

print('\n'+'='*86); print('最严口径: 前5日涨>15% 的短线强势股, 收在显眼对子价'); print('='*86)
h=W[W['r5']>15]; a,b=h[h.xy],h[~h.xy]
for c,n in [('f1','后1日'),('f3','后3日'),('f5','后5日'),('f10','后10日'),('f20','后20日')]:
    x,y=a[c].dropna(),b[c].dropna(); t,p=stats.ttest_ind(x,y,equal_var=False)
    print(f"  {n}: 显眼对子 {x.mean():+.3f}% (n={len(x)})  对照 {y.mean():+.3f}% (n={len(y)})  差 {x.mean()-y.mean():+.3f}pp  t={t:.2f} p={p:.3f}")
print(f"  后5日为负的比例: 显眼对子 {(a['f5']<0).mean()*100:.1f}%  对照 {(b['f5']<0).mean()*100:.1f}%")

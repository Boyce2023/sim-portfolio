#!/opt/homebrew/bin/python3.13
"""对子顶 三年回测 v2 — 全口径(Buwen 09-24 定: 我说的都包括, 除了整数关口的)

对子定义(与价格位数无关, 1000元以上同规则):
  整数关口 .00            → 排除(他明确剔除)
  小数两位相同 f[0]==f[1] → 尾数对子(15.55 / 1.55 / 433.33)
     其中 整数+小数全同    → AAAA全同 (7.77 / 33.33 / 1111.11)
          整数末两位==小数 → ABAB    (26.26 / 125.25 / 1234.34)
          整数末两位相同   → AABB    (33.55)
  小数两位不同, 但整数末两位==小数两位 → ABAB (60.60 / 30.30)

三个问题分开测:
  Q1 市场层: 某天对子占比异常高 → 之后大盘怎么走
  Q2 个股层: 收在对子价 → 自己之后怎么走(全样本)
  Q3 对子"顶": 强势股(前20日涨幅高)收在对子价 → 是不是顶(对照组=同日同涨幅档非对子)
"""
import pandas as pd, numpy as np
pd.set_option('display.width',200)

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
print(f"原始 {len(px):,} 行  {px['date'].min().date()} 到 {px['date'].max().date()}")
px['dz']=px['close'].map(dztype)
px['is_dz']=px['dz'].notna()

# ---------- Q1 市场层 ----------
print('\n'+'='*78)
print('Q1 市场层: 某天全市场对子占比异常高 → 之后大盘怎么走')
print('='*78)
D=px.groupby('date').agg(总数=('ticker','size'),对子=('is_dz','sum'))
D['占比%']=D['对子']/D['总数']*100
px['r']=px.groupby('ticker')['adj_close'].pct_change(fill_method=None)
MK=px.groupby('date')['r'].mean()
idx=(1+MK.fillna(0)).cumprod()
for n in [1,3,5,10,20]: D[f'后{n}日%']=(idx.shift(-n)/idx-1).reindex(D.index)*100
D=D[(D.index>=S)&(D.index<=E)]
print(f"{len(D)} 个交易日  对子占比 均值 {D['占比%'].mean():.2f}%  中位 {D['占比%'].median():.2f}%  标准差 {D['占比%'].std():.2f}%")
print(f"  分位 90%={np.percentile(D['占比%'],90):.2f}  95%={np.percentile(D['占比%'],95):.2f}  99%={np.percentile(D['占比%'],99):.2f}  max={D['占比%'].max():.2f}")
D['档']=pd.qcut(D['占比%'],[0,.5,.8,.9,.95,1.0],labels=['低50%','50-80%','80-90%','90-95%','最高5%'])
g=D.groupby('档',observed=True).agg(天数=('占比%','size'),平均占比=('占比%','mean'),
    后1日=('后1日%','mean'),后3日=('后3日%','mean'),后5日=('后5日%','mean'),后10日=('后10日%','mean'),后20日=('后20日%','mean'))
print(g.round(2).to_string())
print('\n对子占比最高的 12 天:')
T=D.sort_values('占比%',ascending=False).head(12)[['总数','对子','占比%','后1日%','后5日%','后20日%']]
T.index=T.index.strftime('%Y-%m-%d'); print(T.round(2).to_string())

# ---------- 个股层前置: 未来收益 + 前20日涨幅 ----------
g=px.groupby('ticker')['adj_close']
for n in [1,3,5,10,20]:
    px[f'f{n}']=(g.shift(-n)/px['adj_close']-1)*100
px['r20']=(px['adj_close']/g.shift(20)-1)*100
px['amt20']=px.groupby('ticker')['amount'].transform(lambda s:s.rolling(20,min_periods=10).mean())
W=px[(px['date']>=S)&(px['date']<=E)&(px['amount']>=1e7)].copy()

print('\n'+'='*78)
print('Q2 个股层: 收在对子价 → 自己之后怎么走(全样本, 成交额>1000万)')
print('='*78)
q2=W.groupby('is_dz').agg(样本=('close','size'),后1日=('f1','mean'),后3日=('f3','mean'),
    后5日=('f5','mean'),后10日=('f10','mean'),后20日=('f20','mean'))
q2.index=['非对子','对子']; print(q2.round(3).to_string())
print('\n按对子类型:')
q2b=W[W.is_dz].groupby('dz').agg(样本=('close','size'),后1日=('f1','mean'),后5日=('f5','mean'),后20日=('f20','mean'))
print(q2b.round(3).to_string())

# ---------- Q3 对子"顶" ----------
print('\n'+'='*78)
print('Q3 对子顶: 强势股收在对子价 是不是顶? (按前20日涨幅分档, 每档内对子 vs 非对子)')
print('='*78)
bins=[-100,0,10,20,30,50,1e4]; lab=['跌','0-10%','10-20%','20-30%','30-50%','>50%']
W['涨幅档']=pd.cut(W['r20'],bins=bins,labels=lab)
rows=[]
for l in lab:
    s=W[W['涨幅档']==l]
    a,b=s[s.is_dz],s[~s.is_dz]
    if len(a)<50: continue
    rows.append(dict(涨幅档=l,对子样本=len(a),非对子样本=len(b),
        对子后5日=a['f5'].mean(),非对子后5日=b['f5'].mean(),差5=a['f5'].mean()-b['f5'].mean(),
        对子后20日=a['f20'].mean(),非对子后20日=b['f20'].mean(),差20=a['f20'].mean()-b['f20'].mean()))
print(pd.DataFrame(rows).round(3).to_string(index=False))

# t 检验: >30% 强势档
from scipy import stats
hot=W[W['r20']>30]
a,b=hot[hot.is_dz]['f5'].dropna(),hot[~hot.is_dz]['f5'].dropna()
t,p=stats.ttest_ind(a,b,equal_var=False)
print(f"\n强势档(前20日涨>30%) 后5日: 对子 {a.mean():+.3f}% (n={len(a)})  非对子 {b.mean():+.3f}% (n={len(b)})  t={t:.2f} p={p:.3f}")
a20,b20=hot[hot.is_dz]['f20'].dropna(),hot[~hot.is_dz]['f20'].dropna()
t2,p2=stats.ttest_ind(a20,b20,equal_var=False)
print(f"强势档 后20日: 对子 {a20.mean():+.3f}% (n={len(a20)})  非对子 {b20.mean():+.3f}%  t={t2:.2f} p={p2:.3f}")

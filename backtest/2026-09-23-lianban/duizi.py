#!/opt/homebrew/bin/python3.13
"""对子顶回测: 同一天全市场大面积出现"对子"收盘价, 是什么信号? 窗口 2023-09-24 到 2026-09-23 (三年)。

对子定义: 收盘价保留两位小数后, 形如 ABAB 或 AABB? 先用 ABAB(前两位==后两位)。
  26.26 ✓  15.15 ✓  8.08 ✓(即 08.08)  3.03 ✓  100.00? 三位整数不算
  口径: 价格*100 取整得到 N(分), 表示为字符串, 长度4时判 s[0:2]==s[2:4]; 长度3时补0判(如 808 → 0808 ✓)
⛔这是纯数字巧合, 基础概率约 1/100, 关键看某天是否显著高于基础概率。
输出: 每日对子只数与占比, 高峰日之后大盘(全市场等权)的1/3/5/10/20日收益。
"""
import math
import pandas as pd, numpy as np
S,E=pd.Timestamp('2023-09-24'),pd.Timestamp('2026-09-23')
px=pd.read_parquet('data/cn_hk_price_db/a_daily.parquet',columns=['date','ticker','close','adj_close','amount'],
   filters=[('date','>=',pd.Timestamp('2023-08-01'))]).sort_values(['ticker','date'])
px=px[px['amount']>=1e7]           # 剔除极端不活跃
def is_pair(p):
    n=int(round(p*100))
    s=str(n).zfill(4)
    return len(s)==4 and s[0:2]==s[2:4]
px['pair']=px['close'].map(is_pair)
D=px.groupby('date').agg(总数=('ticker','size'),对子=('pair','sum'))
D['占比%']=D['对子']/D['总数']*100
D=D[(D.index>=S)&(D.index<=E)]
print(f"三年 {len(D)} 个交易日")
print(f"对子占比: 均值 {D['占比%'].mean():.2f}%  中位 {D['占比%'].median():.2f}%  标准差 {D['占比%'].std():.2f}%")
print(f"  理论基础概率约 1.00% (四位数字里 ABAB 有 100/10000 种? 实际受价格分布影响)")
print(f"  分位: 90%={np.percentile(D['占比%'],90):.2f}%  95%={np.percentile(D['占比%'],95):.2f}%  99%={np.percentile(D['占比%'],99):.2f}%  max={D['占比%'].max():.2f}%")
# 大盘等权
M=px[(px.date>=pd.Timestamp('2023-09-01'))].groupby('date').apply(lambda g:g['adj_close'].count(),include_groups=False)
mk=px.copy(); mk['r']=mk.groupby('ticker')['adj_close'].pct_change(fill_method=None)
MK=mk.groupby('date')['r'].mean()
idx=(1+MK.fillna(0)).cumprod()
for n in [1,3,5,10,20]:
    D[f'后{n}日%']=(idx.shift(-n)/idx-1).reindex(D.index)*100
print()
print('【按对子占比分档 → 之后全市场等权收益】')
D['档']=pd.qcut(D['占比%'],[0,.5,.8,.9,.95,1.0],labels=['低50%','50-80%','80-90%','90-95%','最高5%'])
g=D.groupby('档',observed=True).agg(天数=('占比%','size'),平均占比=('占比%','mean'),
    后1日=('后1日%','mean'),后3日=('后3日%','mean'),后5日=('后5日%','mean'),后10日=('后10日%','mean'),后20日=('后20日%','mean'))
print(g.round(2).to_string())
print()
print('【对子占比最高的 15 天】')
T=D.sort_values('占比%',ascending=False).head(15)[['总数','对子','占比%','后1日%','后3日%','后5日%','后10日%','后20日%']]
T.index=T.index.strftime('%Y-%m-%d')
print(T.round(2).to_string())
print()
print('【今天 2026-09-24 不在库内(数据到09-23), 最近5个交易日】')
print(D.tail(5)[['总数','对子','占比%']].round(2).to_string())

# -*- coding: utf-8 -*-
"""阶段2: 浪的识别 → 轮动顺序 → 二次炒作 → 触发后收益"""
import pandas as pd, numpy as np, json
from collections import defaultdict
T=pd.read_pickle('/tmp/dhbr/episodes.pkl')
P=pd.read_pickle('/tmp/dhbr/panel.pkl')
M=T[T.micro].copy().sort_values('date')          # 消费微盘 episode
print(f"消费微盘 episode 总数 {len(M)}  {M.date.min().date()}~{M.date.max().date()}")

# ── 1. 浪(wave)识别: 20日滚动触发数, 阈值=expanding历史80分位(反前视), 前2年burn-in
days=pd.Series(sorted(P.date.unique()))
cnt=M.groupby('date').size().reindex(days,fill_value=0)
roll=cnt.rolling(20,min_periods=20).sum()
thr=roll.expanding(min_periods=250).quantile(0.80).shift(1)   # shift(1)=只用t之前
burn=pd.Timestamp('2018-01-01')
hot=(roll>=thr)&(roll>=5)&(days.values>=burn)
hot=pd.Series(hot.values,index=days)
# 连续hot合并成wave, 间隔<15个交易日的合并
waves=[];cur=None
for i,(d,h) in enumerate(hot.items()):
    if h:
        if cur is None: cur=[d,d]
        else:
            gap=(days[(days>cur[1])&(days<=d)]).shape[0]
            if gap<=15: cur[1]=d
            else: waves.append(cur); cur=[d,d]
if cur: waves.append(cur)
waves=[w for w in waves if (w[1]-w[0]).days>=10]
print(f"\n识别出 {len(waves)} 个消费微盘炒作浪 (阈值=expanding历史80分位, 2018起)")
print(f"{'#':<3}{'起':<12}{'止':<12}{'天数':>5}{'episode数':>9}  主导子板块(前3)")
print("-"*84)
rows=[]
for i,(a,b) in enumerate(waves,1):
    sub=M[(M.date>=a)&(M.date<=b)]
    top=sub.groupby('sub').size().sort_values(ascending=False)
    rows.append({'i':i,'start':a,'end':b,'n':len(sub),
                 'top':", ".join(f"{k}({v})" for k,v in top.head(3).items())})
    print(f"{i:<3}{str(a.date()):<12}{str(b.date()):<12}{(b-a).days:>5}{len(sub):>9}  {rows[-1]['top']}")
json.dump([{'i':r['i'],'start':str(r['start'].date()),'end':str(r['end'].date()),'n':r['n']} for r in rows],
          open('/tmp/dhbr/waves.json','w'),ensure_ascii=False)
M.to_pickle('/tmp/dhbr/micro_eps.pkl')
pd.to_pickle(waves,'/tmp/dhbr/waves.pkl')

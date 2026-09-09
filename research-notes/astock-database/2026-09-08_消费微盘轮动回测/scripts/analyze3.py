# -*- coding: utf-8 -*-
"""阶段3: 轮动顺序 + 二次炒作 + 触发后收益"""
import pandas as pd, numpy as np
M=pd.read_pickle('/tmp/dhbr/micro_eps.pkl'); waves=pd.read_pickle('/tmp/dhbr/waves.pkl')
P=pd.read_pickle('/tmp/dhbr/panel.pkl')

print("═"*90); print("【一】浪内轮动顺序: 各子板块首次触发日相对浪起点的天数")
seq=[]
for a,b in waves:
    sub=M[(M.date>=a)&(M.date<=b)]
    if sub['sub'].nunique()<3: continue
    f=sub.groupby('sub')['date'].min()
    for s,d in f.items():
        # 用交易日序数而非自然日
        nd=P[(P.date>=a)&(P.date<=d)].date.nunique()-1
        seq.append({'wave':str(a.date()),'sub':s,'lag':nd,'par':sub[sub['sub']==s]['par'].iloc[0]})
S=pd.DataFrame(seq)
if len(S):
    agg=S.groupby('sub').agg(出现浪数=('lag','size'),中位滞后=('lag','median'),
                             均值滞后=('lag','mean'),最早=('lag','min')).sort_values('中位滞后')
    agg=agg[agg.出现浪数>=3]
    agg['中位滞后']=agg['中位滞后'].round(1); agg['均值滞后']=agg['均值滞后'].round(1)
    par=S.groupby('sub')['par'].first()
    agg['一级']=par
    print(f"(只列出现≥3次的子板块, 滞后=交易日, 0=浪的第一天就触发)\n")
    print(agg.to_string())
print()
print("═"*90); print("【二】二次炒作: 一只股票被炒过之后, 还会不会再被炒")
allT=pd.read_pickle('/tmp/dhbr/episodes.pkl'); allT=allT[allT.micro].sort_values(['code','date'])
per=allT.groupby('code').size()
print(f"\n有过≥1次episode的消费微盘股: {len(per)} 只")
print(f"  只被炒1次: {(per==1).sum()} 只 ({(per==1).mean()*100:.1f}%)")
print(f"  被炒2次  : {(per==2).sum()} 只 ({(per==2).mean()*100:.1f}%)")
print(f"  被炒≥3次 : {(per>=3).sum()} 只 ({(per>=3).mean()*100:.1f}%)")
print(f"  人均次数 : {per.mean():.2f}")
print("\n  ── 复炒间隔(交易日) ──")
gaps=[]
for c,s in allT.groupby('code'):
    d=sorted(s.date)
    for i in range(1,len(d)):
        nd=P[(P.date>d[i-1])&(P.date<=d[i])].date.nunique()
        gaps.append(nd)
if gaps:
    q=np.percentile(gaps,[10,25,50,75,90])
    print(f"  n={len(gaps)}  P10={q[0]:.0f} P25={q[1]:.0f} 中位={q[2]:.0f} P75={q[3]:.0f} P90={q[4]:.0f}")
    for w,lab in [(130,'半年内'),(250,'1年内'),(500,'2年内')]:
        print(f"  {lab}复炒占全部复炒的 {np.mean([g<=w for g in gaps])*100:.0f}%")
print()
print("═"*90); print("【三】触发后收益: 触发日收盘买入, 持有N日")
P=P.sort_values(['code','date'])
idx={(c,d):i for i,(c,d) in enumerate(zip(P.code,P.date))}
arr=P.reset_index(drop=True)
res={h:[] for h in [1,3,5,10,20,40,60]}
for _,r in allT.iterrows():
    i=idx.get((r.code,r.date))
    if i is None: continue
    base=arr.close.iloc[i]
    for h in res:
        j=i+h
        if j<len(arr) and arr.code.iloc[j]==r.code:
            res[h].append(arr.close.iloc[j]/base-1)
print(f"\n{'持有N日':<8}{'样本':>6}{'中位%':>8}{'均值%':>8}{'胜率%':>8}{'P25%':>8}{'P75%':>8}")
print("-"*54)
for h,v in res.items():
    if not v: continue
    v=np.array(v)*100
    print(f"{h:<8}{len(v):>6}{np.median(v):>8.1f}{v.mean():>8.1f}{(v>0).mean()*100:>8.0f}{np.percentile(v,25):>8.1f}{np.percentile(v,75):>8.1f}")

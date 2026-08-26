#!/usr/bin/env python3
"""S5: B2逐月稳定性 + 成交容量检验(低换手=能否买到的现实约束)"""
import pandas as pd, numpy as np, os
D=os.path.dirname(__file__); DRAG=0.61
p=pd.read_csv(os.path.join(D,'panel_2025.csv')); p=p[(~p.yizi)&(p.ret_open.notna())]
o=pd.read_csv(os.path.join(D,'panel_oos2026.csv')); o=o[(~o.yizi)&(o.ret_open.notna())&(o.date>='2026-01-01')&(o.date<='2026-03-20')]
def B2(x): return x[(x.isST==0)&(x.turn<=10)&(x.gain20>=10)&(x.streak<=3)&(x.mkt_lu_cnt>=70)&(x.fcap>=10e8)]
def B1(x): return x[(x.fcap>=15e8)&(x.fcap<=100e8)&(x.streak==1)&(x.gain20<=30)&(x.turn>=3)&(x.turn<=30)]
print("=== A. B2 vs B1 逐月(2025样本内12个月+2026样本外3个月), 均为gross次日开盘收益 ===")
rows=[]
for lab,df in [('2025',p),('2026OOS',o)]:
    for m,g in df.groupby(df.date.str[:7]):
        b2=B2(g); b1=B1(g)
        rows.append(dict(month=m,n_b2=len(b2),b2_mean=round(b2.ret_open.mean(),2) if len(b2) else None,
            b2_win=round((b2.ret_open>0).mean()*100,1) if len(b2) else None,
            n_b1=len(b1),b1_mean=round(b1.ret_open.mean(),2) if len(b1) else None,
            b1_win=round((b1.ret_open>0).mean()*100,1) if len(b1) else None,
            base_mean=round(g.ret_open.mean(),2)))
print(pd.DataFrame(rows).to_string(index=False))
print("\n=== B. 成交容量: 涨停当日成交额(亿元)分布 —— 买不买得到的现实约束 ===")
for lab,df in [('2025全样本',p)]:
    for name,s in [('全部可买涨停',df),('换手<=3%',df[df.turn<=3]),('B2选中',B2(df)),
                   ('ST且换手<3%',df[(df.isST==1)&(df.turn<3)])]:
        amt=s.close*0  # placeholder
        a=(s.fcap*s.turn/100)/1e8  # 成交额亿元 = fcap*turn%
        print(f"{name:14s} n={len(s):6d}  成交额中位数={a.median():7.2f}亿  p25={a.quantile(.25):6.2f}  p10={a.quantile(.10):6.2f}亿")
print("\n注: 成交额=流通市值x换手率(反推口径自洽)。若单笔投入100万, 需占当日成交额的比例=100万/成交额")

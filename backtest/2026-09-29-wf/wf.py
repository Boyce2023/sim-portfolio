#!/opt/homebrew/bin/python3.13
"""逐月前推训练(walk-forward), 三个版本:
 A 不学习: 只在 2024-10 首日训练一次, 之后一直用
 B 每月重训: 每月首个交易日, 用"标签已揭晓(dH < 当日)"的全部历史样本重训
 C 每月重训 + 个股记忆特征(mem_y, mem_n)
 模型只对当月的日子打分 → 每个分数都只来自当时已知的信息"""
import pandas as pd, numpy as np, time, json
from sklearn.ensemble import HistGradientBoostingRegressor
from scipy.stats import spearmanr
P=pd.read_parquet('feat.parquet')
U=(P.isST==0)&(P.age>=120)&P.fcap.between(10,200)&(P.amount>=3e7)&(P.close>=2)&P.r60.notna()
P=P[U].copy()
P['yxu']=P.y-P.groupby('date').y.transform('mean')          # 相对股票池等权的超额
P=P[P.pool>0].copy()                                          # 只在形态池里学和挑
BASE=['r1','r3','r5','r10','r20','r60','vol20','zt5','zt20','dt20','up5','up10','t1','t5','t20','tr1','tr5','tr20',
 'box20','dh20','dh60','dl20','c_ma5','c_ma20','ma5_20','ma20_60','clv','upsh','body','gap','lfcap','lamt','amt_r','b20','lpx',
 'm_r1','m_up','m_zt','m_dt','m_r5','m_r20','m_zt5','m_dt5','rs5','rs20']
BASE=BASE+['pool','box_pre','r_pre','t_pre','mxr5']
MEM=BASE+['mem_y','mem_n']
dates=sorted(P.date.unique())
start=pd.Timestamp('2024-10-01')
months=sorted({(d.year,d.month) for d in dates if d>=start})
firsts=[min(d for d in dates if (d.year,d.month)==ym) for ym in months]
def fit(td,cols,seed):
    tr=P[(P.dH<td)&P.yxu.notna()&(P.date>=pd.Timestamp('2023-04-01'))]
    m=HistGradientBoostingRegressor(max_iter=200,learning_rate=0.04,max_leaf_nodes=15,min_samples_leaf=150,l2_regularization=1.0,random_state=seed)
    m.fit(tr[cols],tr.yxu.clip(-0.3,0.5)); return m,len(tr)
out=[]; log=[]; mA=None
for i,td in enumerate(firsts):
    nxt=firsts[i+1] if i+1<len(firsts) else pd.Timestamp('2099-01-01')
    X=P[(P.date>=td)&(P.date<nxt)]
    t0=time.time()
    if mA is None: mA,nA=fit(td,BASE,1)
    mB,nB=fit(td,BASE,100+i); mC,nC=fit(td,MEM,200+i)
    s=X[['date','code']].copy()
    s['sA']=mA.predict(X[BASE]); s['sB']=mB.predict(X[BASE]); s['sC']=mC.predict(X[MEM])
    out.append(s)
    # 事后诊断: 当月分数与实际超额的秩相关(只作评估, 不回灌模型)
    z=s.join(X[['yxu']]).dropna()
    ic={k:float(z.groupby('date').apply(lambda d:spearmanr(d[k],d.yxu)[0] if len(d)>8 else np.nan,include_groups=False).mean()) for k in ['sA','sB','sC']}
    log.append(dict(month=str(td.date()),train_rows=nB,rows=len(X),**ic,sec=round(time.time()-t0)))
    print(log[-1],flush=True)
S=pd.concat(out); S.to_parquet('scores.parquet'); json.dump(log,open('wf_log.json','w'),ensure_ascii=False,indent=1)
print('完成',len(S))

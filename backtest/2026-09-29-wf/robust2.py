#!/opt/homebrew/bin/python3.13
import pandas as pd, numpy as np
from multiprocessing import Pool
import sim as SIM
def job(a):
    lab,kw=a
    E,T=SIM.run(**kw)
    return lab,kw.get('key'),kw.get('N',10),kw.get('K',2),E.nav.iloc[-1],(E.nav/E.nav.cummax()-1).min(),len(T),(T.ret>0).mean(),T.ret.mean(),T[T.ret>0].ret.mean()/-T[T.ret<=0].ret.mean()
if __name__=='__main__':
    J=[(f'{k}无闸门',dict(key=k,adaptive=False,N=n,K=kk)) for k in ('sA','sB','sC') for n in (8,10,12) for kk in (1,2,3)]
    with Pool(9) as p: O=pd.DataFrame(p.map(job,J),columns=['配置','分数','N','K','净值','回撤','笔数','胜率','每笔期望','赔率'])
    R=pd.read_csv('robust_runs.csv'); rq=R[R['类']=='R'].净值.values
    O['超过随机%']=[(rq<v).mean()*100 for v in O.净值]
    print(f'随机200次: 中位 {np.median(rq):.3f} 95%分位 {np.quantile(rq,.95):.3f}')
    print(O.round(3).to_string(index=False))
    print(O.groupby('配置')[['净值','回撤','胜率','每笔期望','赔率','超过随机%']].agg(['min','median','max']).round(3).to_string())
    O.to_csv('robust2.csv',index=False)

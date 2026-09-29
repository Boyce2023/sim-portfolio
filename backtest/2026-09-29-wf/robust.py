#!/opt/homebrew/bin/python3.13
"""稳健性: ①逐日选股质量(不经组合路径) ②随机对照 200 次分布 ③C 版参数扰动 —— 多进程并行"""
import pandas as pd, numpy as np, sys, os
from multiprocessing import Pool
os.environ['OMP_NUM_THREADS']='1'
F=pd.read_parquet('feat.parquet',columns=['date','code','close','zt_px','y','fill'])
S=pd.read_parquet('scores.parquet')
X=S.merge(F,on=['date','code'])
X=X[(X.close<X.zt_px-0.011)&X.fill&X.y.notna()].copy()
X['yn']=X.y-0.0031
X['ex']=X.yn-X.groupby('date').yn.transform('mean')
print('① 逐日选股质量: 每天分数前N名, 次日开盘买持有10日(扣费)的平均收益 与 相对同池平均的超额')
rows=[]
for k in ['sA','sB','sC']:
    for n in [2,5,10]:
        top=X.sort_values(k,ascending=False).groupby('date').head(n)
        d=top.groupby('date').agg(r=('yn','mean'),e=('ex','mean'))
        for lab,a,b in [('全期','2024-10-01','2026-10-01'),('前半','2024-10-01','2025-10-01'),('后半','2025-10-01','2026-10-01')]:
            z=d[(d.index>=a)&(d.index<b)]
            # 相邻日持有期重叠, t 值按 10 日不重叠抽样保守估计
            zs=z.iloc[::10]
            rows.append(dict(模型=k[1],前N=n,区间=lab,天数=len(z),平均收益=round(z.r.mean()*100,2),胜率=round((top[(top.date>=a)&(top.date<b)].yn>0).mean()*100,1),
                超额=round(z.e.mean()*100,2),超额为正天数占比=round((z.e>0).mean()*100,1),t值_不重叠=round(zs.e.mean()/zs.e.std()*np.sqrt(len(zs)),2)))
R1=pd.DataFrame(rows); print(R1.to_string(index=False)); R1.to_csv('robust_picks.csv',index=False)
pm=X.groupby('date').yn.mean(); print(f"  同池平均(随便买)每笔: 全期 {pm.mean()*100:.2f}%")
import sim as SIM
def job(args):
    kind,kw=args
    E,T=SIM.run(**kw); return kind,kw.get('seed'),kw.get('N'),kw.get('K'),E.nav.iloc[-1],(E.nav/E.nav.cummax()-1).min(),len(T),(T.ret>0).mean() if len(T) else np.nan
if __name__=='__main__':
    jobs=[('R',dict(key='sC',rand=True,seed=s)) for s in range(200)]
    jobs+=[('C扰动',dict(key='sC',adaptive=True,N=n,K=k)) for n in (8,10,12) for k in (1,2,3)]
    with Pool(9) as p: out=p.map(job,jobs,chunksize=4)
    O=pd.DataFrame(out,columns=['类','seed','N','K','净值','回撤','笔数','胜率'])
    r=O[O['类']=='R']
    print(f"\n② 随机对照 200 次: 期末净值 中位 {r.净值.median():.3f}  5%分位 {r.净值.quantile(.05):.3f}  95%分位 {r.净值.quantile(.95):.3f}  最高 {r.净值.max():.3f}")
    for v in ['A','B','C','D','E']:
        nav=pd.read_csv(f'eq_{v}.csv').nav.iloc[-1]
        print(f"   {v} 净值 {nav:.3f} 超过随机的比例 {(r.净值<nav).mean()*100:.1f}%")
    print('\n③ C 版参数扰动(仓位数N × 每日新开K):'); print(O[O['类']=='C扰动'][['N','K','净值','回撤','笔数','胜率']].round(3).to_string(index=False))
    O.to_csv('robust_runs.csv',index=False)

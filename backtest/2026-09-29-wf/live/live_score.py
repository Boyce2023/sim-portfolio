#!/opt/homebrew/bin/python3.13
"""当前候选: 面板(至09-23) + 东财补的 09-24/09-28 → 同一套特征 → 最终版模型(每月重训+个股记忆)
训练只用 dH < 2026-09-29 的已揭晓样本; 对 09-28 收盘形态池打分"""
import pandas as pd, numpy as np, subprocess, sys
from sklearn.ensemble import HistGradientBoostingRegressor
P=pd.read_parquet('../panel.parquet')
R=pd.concat([pd.read_parquet('recent_bs.parquet'),pd.read_parquet('recent_sina.parquet')]); R['date']=pd.to_datetime(R.date)
lastf=P.sort_values('date').groupby('code').tail(1).set_index('code')
R['fshare']=R.code.map(lastf.fshare); R['turn']=R.turn.where(R.turn.notna(),R.volume/R.fshare)
alive=set(lastf[lastf.date==lastf.date.max()].index); got=set(R.code)
print('补数覆盖',len(got&alive),'/',len(alive),' 各日行数',R.groupby('date').size().to_dict())
assert len(got&alive)>=0.97*len(alive), '补数覆盖不足 97%, 停'
R['adjf']=R.code.map(lastf.adjf); R['isST']=R.isST.where(R.isST.notna(),R.code.map(lastf.isST)).fillna(0).astype(int); R['src']='recent'
R=R[R.date>P.date.max()]
X=pd.concat([P,R[['code','date','open','high','low','close','adjf','amount','turn','fshare','src','volume','isST']]]).sort_values(['code','date']).reset_index(drop=True)
X['prevc']=X.groupby('code').close.shift(1)
X.to_parquet('panel.parquet'); print('面板末日',X.date.max().date(),'末日股票数',(X.date==X.date.max()).sum())
subprocess.run([sys.executable,'features.py'],check=True)
F=pd.read_parquet('feat.parquet')
U=(F.isST==0)&(F.age>=120)&F.fcap.between(10,200)&(F.amount>=3e7)&(F.close>=2)&F.r60.notna()
F=F[U].copy(); F['yxu']=F.y-F.groupby('date').y.transform('mean'); F=F[F.pool>0]
BASE=['r1','r3','r5','r10','r20','r60','vol20','zt5','zt20','dt20','up5','up10','t1','t5','t20','tr1','tr5','tr20',
 'box20','dh20','dh60','dl20','c_ma5','c_ma20','ma5_20','ma20_60','clv','upsh','body','gap','lfcap','lamt','amt_r','b20','lpx',
 'm_r1','m_up','m_zt','m_dt','m_r5','m_r20','m_zt5','m_dt5','rs5','rs20','pool','box_pre','r_pre','t_pre','mxr5','mem_y','mem_n']
T0=pd.Timestamp('2026-09-29'); D=F.date.max()
tr=F[(F.dH<T0)&F.yxu.notna()&(F.date>=pd.Timestamp('2023-04-01'))]
m=HistGradientBoostingRegressor(max_iter=200,learning_rate=0.04,max_leaf_nodes=15,min_samples_leaf=150,l2_regularization=1.0,random_state=999)
m.fit(tr[BASE],tr.yxu.clip(-0.3,0.5))
C=F[F.date==D].copy(); C['score']=m.predict(C[BASE])
C=C[C.close<C.zt_px-0.011].sort_values('score',ascending=False)
nm=pd.read_csv('../names.csv',dtype={'code':str}); nm=dict(zip(nm.code.str.zfill(6),nm.name))
C['名称']=C.code.map(nm)
out=C[['code','名称','score','pool','close','r1','r5','r20','box_pre','t20','tr1','fcap','mem_n','mem_y']].head(15).copy()
out['pool']=out.pool.map({1:'横盘点火',2:'台阶初期'})
for c in ['r1','r5','r20','box_pre','t20','mem_y']: out[c]=(out[c]*100).round(1)
out['fcap']=out.fcap.round(1); out['score']=(out.score*100).round(2); out['tr1']=out.tr1.round(1)
print(f'信号日 {D.date()} 形态池(剔除当日涨停) {len(C)} 只, 训练样本 {len(tr)}')
print(out.rename(columns={'score':'预测超额%','pool':'形态','close':'收盘','r1':'当日%','r5':'5日%','r20':'20日%','box_pre':'前基座箱体%','t20':'20日均换手%','tr1':'当日换手倍数','fcap':'流通亿','mem_n':'记忆事件数','mem_y':'记忆均值%'}).to_string(index=False))
out.to_csv('candidates_0928.csv',index=False)
print('全池分数分布: 前1%',round(np.quantile(C.score,0.99)*100,2),' 中位',round(C.score.median()*100,2))

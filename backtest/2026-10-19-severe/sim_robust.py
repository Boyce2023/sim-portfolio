"""路径敏感性: 不同起始日 x 同日多只的挑选规则(换手低优先/换手高优先/市值大优先), 看复利的分布"""
import pandas as pd, numpy as np, importlib.util, sys
spec=importlib.util.spec_from_file_location('sim','sim.py'); 
src=open('sim.py').read().split("out=[]; keep={}")[0]
ns={}; exec(src,ns)
F0=ns['F'].copy(); P=ns['P']
F0['cap']=[P[c].close[P[c].date==d].iloc[0]*P[c].oshare[P[c].date==d].iloc[0] if (P[c].date==d).any() else np.nan for c,d in zip(F0.code,F0.d5)]
res=[]
for rule in ['B1','B2','B5','B7','B8','B4']:
    for L,md in ((0.95,4),(0.95,5),(1.0,4),(1.0,5)):
        vals=[]
        for start in ['2026-07-06','2026-07-20','2026-08-03','2026-08-17']:
            for order in (('turn',True),('turn',False),('cap',False)):
                ns['F']=F0[F0.d5>=start].sort_values(['d5',order[0]],ascending=[True,order[1]])
                # run() 内部按 ['d5','turn'] 排序, 这里改成按指定字段
                def run(rule=rule,L=L,maxday=md):
                    trades=[]; free_after=pd.Timestamp('1900-01-01')
                    for d5,g in ns['F'].groupby('d5',sort=True):
                        g=g.sort_values(order[0],ascending=order[1])
                        for _,e in g.iterrows():
                            d=P[e.code]; en=ns['entry'](e.code,d5,rule)
                            if en is None: continue
                            b,buy=en
                            if d.date[b]<=free_after: continue
                            i5=int(d.index[d.date==d5][0])
                            t,sell,why=ns['exit_'](e.code,b,buy,L,i5+maxday-b+1)
                            trades.append(sell/buy-1); free_after=d.date[t]; break
                    return np.array(trades)
                v=run(); vals.append((start,order[0]+('低' if order[1] else '高'),np.prod(1+v)-1 if len(v) else 0,len(v)))
        c=np.array([x[2] for x in vals])
        res.append({'买点':rule,'线':f'{int(L*100)}%','最晚':f'第{md}天','12种路径复利中位':np.median(c),'最差':c.min(),'最好':c.max(),'为负的路径数':int((c<0).sum())})
R=pd.DataFrame(res); R.to_pickle('sim_robust.pkl')
print(R.assign(**{k:(lambda z,k=k:(z[k]*100).round(0)) for k in ['12种路径复利中位','最差','最好']}).to_string(index=False))

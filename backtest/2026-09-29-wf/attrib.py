#!/opt/homebrew/bin/python3.13
import pandas as pd, numpy as np
from multiprocessing import Pool
import sim as SIM
CFG=[('A分数 无自校准','sA',False,False),('A分数 +自校准','sA',True,False),('B分数 无自校准','sB',False,False),('B分数 +自校准','sB',True,False),
     ('C分数 无自校准','sC',False,False),('C分数 +自校准','sC',True,False),('随机 +自校准(闸门跟C分数前5名)','sC',True,True)]
def job(c):
    lab,k,ad,rd=c
    if rd:
        out=[]
        for s in range(40):
            E,T=SIM.run(key=k,adaptive=ad,rand=True,seed=s); out.append(E.nav.iloc[-1])
        return lab,np.median(out),None,None,None
    E,T=SIM.run(key=k,adaptive=ad)
    return lab,E.nav.iloc[-1],(E.nav/E.nav.cummax()-1).min(),len(T),(T.ret>0).mean()
if __name__=='__main__':
    with Pool(7) as p: r=p.map(job,CFG)
    print(pd.DataFrame(r,columns=['配置','期末净值','最大回撤','笔数','胜率']).round(3).to_string(index=False))

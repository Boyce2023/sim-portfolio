import pandas as pd, numpy as np
def panel(start='2025-12-01'):
    A=pd.read_parquet('../../data/cn_hk_price_db/a_daily.parquet',columns=['date','ticker','open','high','low','close','adj_close'],filters=[('date','>=',pd.Timestamp(start))])
    A=A[A.ticker.str.endswith(('.SH','.SZ'))].copy(); A['code']=A.ticker.str[:6]; A=A.sort_values(['code','date']).reset_index(drop=True)
    g=A.groupby('code'); A['adjf']=A.adj_close/A.close
    A['prevc']=g.close.shift(1)*g.adjf.shift(1)/A.adjf
    F=pd.read_parquet('../2026-09-29-wf/feat.parquet',columns=['code','date','isST'])
    A=A.merge(F,on=['code','date'],how='left')   # 逐日 ST 标记(到09-23), 之后用最后已知值
    last=F.sort_values('date').groupby('code').tail(1).set_index('code').isST
    A['isST']=A.isST.fillna(A.code.map(last)).fillna(0)
    A=A.sort_values(['code','date']).reset_index(drop=True); g=A.groupby('code')
    big=A.code.str[:3].isin(['300','301','688','689'])
    A['lim']=np.where(big,0.2,np.where(A.isST==1,0.05,0.1))
    A['zt_px']=(A.prevc*(1+A.lim)).round(2)
    A['zt']=(A.close>=A.zt_px-0.011)&A.prevc.notna()
    A['nth']=g.cumcount()
    s=A.zt.astype(int); grp=(s!=s.groupby(A.code).shift()).cumsum()
    A['streak']=s.groupby([A.code,grp]).cumsum()*s
    g=A.groupby('code')
    for k in range(1,12):
        for c in ['open','high','low','close','adjf','zt_px','date']: A[f'{c}{k}']=g[c].shift(-k)
    return A

#!/opt/homebrew/bin/python3.13
"""按连板高度逐档(1/2/3/4/5板以上), 同一天同高度组内按封单占流通、换手、流通市值分高半与低半, 比较次日晋级率. 组内只有两只时就是一高一低"""
import pandas as pd,numpy as np,runpy,io,contextlib
with contextlib.redirect_stdout(io.StringIO()): ns=runpy.run_path('race.py')
Z=ns['Z']
H=Z[(Z.date>=pd.Timestamp('2026-07-01'))&(Z.lb==Z.days)&Z.晋级.notna()].copy()
H['晋级']=H.晋级.astype(float); H['段']=np.where(H.date<pd.Timestamp('2026-09-01'),'7-8月','9-10月')
H['档']=H.lb.clip(upper=5)
F=[('封单占流通','封单占流通'),('换手','turn'),('流通市值','cap')]
rows=[]
for lb in (1,2,3,4,5):
    h=H[H.档==lb].copy()
    h=h[h.groupby(['date','lb']).code.transform('count')>=2]
    for nm,col in F:
        h['pct']=h.groupby(['date','lb'])[col].rank(pct=True,method='average')
        n=h.groupby(['date','lb'])[col].transform('count')
        hi=h.pct>0.5+1e-9; lo=h.pct<0.5+1e-9
        hi=h[col]>h.groupby(['date','lb'])[col].transform('median'); lo=h[col]<h.groupby(['date','lb'])[col].transform('median')
        r={'高度':'5板以上' if lb==5 else f'{lb}板','组数':h.groupby(['date','lb']).ngroups,'只次':len(h),'指标':nm}
        for seg in ('全部','7-8月','9-10月'):
            m=(h.段==seg) if seg!='全部' else pd.Series(True,index=h.index)
            r[f'{seg} 高的一半']=f"{h[hi&m].晋级.mean()*100:.0f}% ({int(h[hi&m].晋级.sum())}/{(hi&m).sum()})"
            r[f'{seg} 低的一半']=f"{h[lo&m].晋级.mean()*100:.0f}% ({int(h[lo&m].晋级.sum())}/{(lo&m).sum()})"
        rows.append(r)
T=pd.DataFrame(rows); T.to_csv('byheight.csv',index=False,encoding='utf-8-sig')
pd.set_option('display.width',300); print(T.to_string(index=False))

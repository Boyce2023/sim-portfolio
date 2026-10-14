#!/opt/homebrew/bin/python3.13
"""可成交口径: T+1 开盘价已到涨停价(一字/顶格开)视为买不到, 只在买得到的成员里挑. 结局 = T+1 开盘买, T+2 收盘卖."""
import pandas as pd,numpy as np,runpy,io,contextlib
with contextlib.redirect_stdout(io.StringIO()): ns=runpy.run_path('group.py')
Z=ns['Z']
def lim(c): return 0.20 if c[:3] in('300','301','688') else (0.30 if c[0] in '48' or c[:2]=='92' else 0.10)
Z['可买']=[(pd.notna(gp) and gp<lim(c)-0.005) for gp,c in zip(Z.次日开盘缺口,Z.code)]
for minlb in (4,3):
    H=Z[(Z.date>=pd.Timestamp('2026-07-01'))&(Z.lb>=minlb)&(Z.lb==Z.days)&Z.次日涨跌.notna()]
    GR=[x for _,x in H.groupby(['date','lb']) if len(x)>=2]
    print(f'\n== {minlb}板及以上: 组 {len(GR)}, 其中次日开盘一字买不到的成员 {int((~pd.concat(GR).可买).sum())}/{len(pd.concat(GR))} ==')
    lowturn_unf=[ (x.loc[x.turn.idxmin(),'可买']) for x in GR]
    print('换手最低那只次日买得到的比例 %d/%d'%(sum(lowturn_unf),len(lowturn_unf)))
    res=[]
    for nm,col,fn in (('流通市值最大','cap',max),('流通市值最小','cap',min),('换手最低','turn',min),('换手最高','turn',max),('炸板最少','open_num',min),('封单占流通最高','封单占流通',max),('开盘缺口最高','次日开盘缺口',max),('开盘缺口最低','次日开盘缺口',min)):
        for seg,cond in (('全部',lambda d:True),('7-8月',lambda d:d<pd.Timestamp('2026-09-01')),('9-10月',lambda d:d>=pd.Timestamp('2026-09-01'))):
            win=n=0; ex=[]; ab=[]
            for x in GR:
                if not cond(x.date.iloc[0]): continue
                x=x[x.可买&x.开买后日收.notna()]
                if len(x)<2: continue
                v=x[col]
                if (v==fn(v)).sum()>1: continue
                s=x[v==fn(v)].iloc[0]; o=x[v!=fn(v)]
                d=s.开买后日收-o.开买后日收.mean(); n+=1; win+=d>0; ex.append(d); ab.append(s.开买后日收)
            res.append(dict(挑法=nm,段=seg,有效组=n,挑中跑赢=f'{win}/{n}' if n else '',超额均值=round(np.mean(ex)*100,1) if ex else np.nan,挑中那只绝对收益=round(np.mean(ab)*100,1) if ab else np.nan))
    print(pd.DataFrame(res).to_string(index=False))
    m=[x[x.可买].开买后日收.mean() for x in GR if (x.可买&x.开买后日收.notna()).sum()>=2]
    print('可买成员全买(等权) 组均 %.1f%%, 胜 %d/%d'%(np.nanmean(m)*100,sum(np.array(m)>0),len(m)))

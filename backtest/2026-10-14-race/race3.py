#!/opt/homebrew/bin/python3.13
"""不重叠分档: 2板/3板/4板/5板以上, 同高度组内挑一只. 结局A=次日晋级; 结局B=T+1开盘买(开盘涨停买不到)T+2收盘卖, 只在买得到的成员里挑"""
import pandas as pd,numpy as np,runpy,io,contextlib
with contextlib.redirect_stdout(io.StringIO()): ns=runpy.run_path('race.py')
Z=ns['Z']
H=Z[(Z.date>=pd.Timestamp('2026-07-01'))&(Z.lb>=2)&(Z.lb==Z.days)&Z.晋级.notna()].copy()
H['晋级']=H.晋级.astype(float); H['段']=np.where(H.date<pd.Timestamp('2026-09-01'),'7-8月','9-10月')
H['档']=np.where(H.lb>=5,'5板以上',H.lb.astype(str)+'板')
P=pd.read_parquet('../../data/cn_hk_price_db/a_daily.parquet',columns=['date','ticker','open','close','adj_close'],filters=[('date','>=',pd.Timestamp('2026-06-25'))])
P['code']=P.ticker.str[:6]; P['f']=P.adj_close/P.close; P=P.sort_values(['code','date']); g=P.groupby('code')
P['c2']=g.adj_close.shift(-2); P['o1']=g.open.shift(-1)*g.f.shift(-1); P=P.set_index(['date','code'])
lim=lambda c:0.20 if c[:3] in('300','301','688','689') else 0.10
def tr(d,c):
    try: x=P.loc[(d,c)]
    except KeyError: return np.nan
    return (x.c2/x.o1-1) if (x.o1/x.adj_close-1)<lim(c)-0.005 else np.nan
H['开买后日收']=[tr(d,c) for d,c in zip(H.date,H.code)]
F=[('封单占流通最高','封单占流通',1),('换手最低','turn',-1),('流通市值最大','cap',1),('流通市值最小','cap',-1)]
rows=[]
for band in ('2板','3板','4板','5板以上'):
    GR=[x for _,x in H[H.档==band].groupby(['date','lb']) if len(x)>=2]
    for nm,col,sg in F:
        r={'档':band,'组数':len(GR),'挑法':nm}
        for seg in ('7-8月','9-10月'):
            s=[];b=[];w=n=0;ex=[]
            for x in GR:
                if x.段.iloc[0]!=seg: continue
                v=x[col]*sg
                if (v==v.max()).sum()==1:
                    t=x[v==v.max()].iloc[0]; o=x[v!=v.max()]; s.append(t.晋级); b.append(x.晋级.mean())
                    if t.晋级!=o.晋级.mean(): n+=1; w+=t.晋级>o.晋级.mean()
                y=x[x.开买后日收.notna()]
                if len(y)>=2:
                    v=y[col]*sg
                    if (v==v.max()).sum()==1:
                        t=y[v==v.max()].iloc[0]; ex.append(t.开买后日收-y[v!=v.max()].开买后日收.mean())
            r[f'{seg}晋级']=f"{np.mean(s)*100:.0f}%/{np.mean(b)*100:.0f}% ({w}/{n})" if s else ''
            r[f'{seg}开买超额']=f"{np.mean(ex)*100:+.1f}% ({sum(np.array(ex)>0)}/{len(ex)})" if ex else ''
        rows.append(r)
pd.set_option('display.width',250); print(pd.DataFrame(rows).to_string(index=False))

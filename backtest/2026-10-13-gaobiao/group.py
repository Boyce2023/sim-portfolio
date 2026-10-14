#!/opt/homebrew/bin/python3.13
"""组级口径: 每个同高度组里按某特征挑一只, 看它是否跑赢组内其他人(平局剔除). 4板以上为主样本, 3板以上作扩样本检验.
挑法均为 T 日收盘后或 T+1 开盘时可得的信息."""
import json,glob,os,sys,pandas as pd,numpy as np,contextlib,io
sys.path.insert(0,'../2026-10-09-theme')
with contextlib.redirect_stdout(io.StringIO()):
    _c=os.getcwd(); os.chdir('../2026-10-09-theme'); from theme import themes; os.chdir(_c)
rows=[]
for f in sorted(glob.glob('../2026-10-09-theme/ths/2026*.json')):
    d=f.split('/')[-1][:8]
    if d<'20260620': continue
    for r in json.load(open(f)):
        v=int(r.get('high_days_value') or 65537)
        rows.append(dict(date=pd.Timestamp(d),code=r['code'],name=r['name'],lb=v>>16,days=v&0xFFFF,open_num=int(r.get('open_num') or 0),
            cap=float(r.get('currency_value') or 0)/1e8,turn=float(r.get('turnover_rate') or 0),seal=float(r.get('order_amount') or 0)/1e8,first=int(r.get('first_limit_up_time') or 0)))
Z=pd.DataFrame(rows); cal=sorted(Z.date.unique()); nxt={cal[i]:cal[i+1] for i in range(len(cal)-1)}
ztset={(d,c) for d,c in zip(Z.date,Z.code)}
Z['封单占流通']=Z.seal/Z.cap
P=pd.read_parquet('../../data/cn_hk_price_db/a_daily.parquet',columns=['date','ticker','open','close','adj_close'],filters=[('date','>=',pd.Timestamp('2026-06-25'))])
P['code']=P.ticker.str[:6]; P['f']=P.adj_close/P.close; P=P.sort_values(['code','date']); g=P.groupby('code')
P['c1']=g.adj_close.shift(-1); P['c2']=g.adj_close.shift(-2); P['o1']=g.open.shift(-1)*g.f.shift(-1)
P=P.set_index(['date','code'])
# 10-13 当天行情库还没结算, 10-12 组(九阳/时代万恒)用腾讯实时收盘补
PATCH={('2026-10-12','002242'):(16.64,15.82,17.67),('2026-10-12','600241'):(12.94,12.94,12.86)}
def out(d,c):
    k=(d.strftime('%Y-%m-%d'),c)
    if k in PATCH: c0,o1,c1=PATCH[k]; return c1/c0-1,o1/c0-1,np.nan,c1/o1-1
    try: x=P.loc[(d,c)]
    except KeyError: return (np.nan,)*4
    return x.c1/x.adj_close-1,x.o1/x.adj_close-1,x.c2/x.o1-1,x.c1/x.o1-1
Z[['次日涨跌','次日开盘缺口','开买后日收','次日开到收']]=[out(d,c) for d,c in zip(Z.date,Z.code)]
Z['晋级']=[(nxt[d],c) in ztset if d in nxt else np.nan for d,c in zip(Z.date,Z.code)]
def run(minlb,label):
    H=Z[(Z.date>=pd.Timestamp('2026-07-01'))&(Z.lb>=minlb)&(Z.lb==Z.days)&Z.次日涨跌.notna()]
    GR=[x for _,x in H.groupby(['date','lb']) if len(x)>=2]
    SEL={'流通市值最大':('cap',max),'流通市值最小':('cap',min),'换手最低':('turn',min),'炸板最少':('open_num',min),
         '封单占流通最高':('封单占流通',max),'次日开盘缺口最高':('次日开盘缺口',max),'次日开盘缺口最低':('次日开盘缺口',min)}
    res=[]
    for nm,(col,fn) in SEL.items():
        for seg,cond in (('全部',lambda d:True),('7-8月',lambda d:d<pd.Timestamp('2026-09-01')),('9-10月',lambda d:d>=pd.Timestamp('2026-09-01'))):
            win=n=0; ex=[]; ex2=[]
            for x in GR:
                if not cond(x.date.iloc[0]): continue
                v=x[col]
                if v.isna().any() or (v==fn(v)).sum()>1: continue      # 特征平局不挑
                s=x[v==fn(v)].iloc[0]; o=x[v!=fn(v)]
                d=s.次日涨跌-o.次日涨跌.mean()
                if abs(d)<1e-4: continue                              # 结局平局(都涨停)剔除
                n+=1; win+=d>0; ex.append(d)
                if pd.notna(s.开买后日收) and o.开买后日收.notna().all(): ex2.append(s.开买后日收-o.开买后日收.mean())
            res.append(dict(挑法=nm,段=seg,有效组=n,挑中跑赢=f'{win}/{n}' if n else '',次日超额均值=round(np.mean(ex)*100,1) if ex else np.nan,
                            开买后日收超额=round(np.mean(ex2)*100,1) if ex2 else np.nan))
    R=pd.DataFrame(res); print(f'\n== {label}: 同高度组 {len(GR)} 个 =='); print(R.to_string(index=False))
    # 两只都买(等权) vs 单只平均: 一样, 只报组均值
    m=[x.开买后日收.mean() for x in GR if x.开买后日收.notna().all()]
    print('两只都买(次日开盘买, 后日收盘卖) 组均收益 %.1f%%, 胜率 %d/%d'%(np.mean(m)*100,sum(np.array(m)>0),len(m)))
    return GR
G4=run(4,'4板及以上'); G3=run(3,'3板及以上(扩样本)')

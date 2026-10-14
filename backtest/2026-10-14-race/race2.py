#!/opt/homebrew/bin/python3.13
"""race.py 的续: ①封单占流通最高与换手最低合用(一致/分歧) ②组内排名打分挑一只 ③可交易口径: T+1开盘买(开盘涨停买不到)T+2收盘卖 ④组内排名逻辑回归分段稳定性"""
import pandas as pd,numpy as np,statsmodels.api as sm
H=pd.read_pickle('H.pkl')
P=pd.read_parquet('../../data/cn_hk_price_db/a_daily.parquet',columns=['date','ticker','open','close','adj_close'],filters=[('date','>=',pd.Timestamp('2026-06-25'))])
P['code']=P.ticker.str[:6]; P['f']=P.adj_close/P.close; P=P.sort_values(['code','date']); g=P.groupby('code')
P['c1']=g.adj_close.shift(-1); P['c2']=g.adj_close.shift(-2); P['o1']=g.open.shift(-1)*g.f.shift(-1); P=P.set_index(['date','code'])
def lim(c): return 0.20 if c[:3] in('300','301','688','689') else 0.10
def tr(d,c):
    try: x=P.loc[(d,c)]
    except KeyError: return (np.nan,)*3
    gap=x.o1/x.adj_close-1
    return x.c1/x.adj_close-1, (x.c2/x.o1-1) if gap<lim(c)-0.005 else np.nan, gap
H[['次日涨跌','开买后日收','开盘缺口']]=[tr(d,c) for d,c in zip(H.date,H.code)]
G=[g.copy() for _,g in H.groupby(['date','lb']) if len(g)>=2]
for g in G:
    g['r_seal']=g.封单占流通.rank(pct=True); g['r_turn']=(-g.turn).rank(pct=True); g['r_cap']=(-g.cap).rank(pct=True)
    g['r_first']=(-g['first']).rank(pct=True); g['score']=g.r_seal+g.r_turn
A=pd.concat(G)
print('===== ① 封单占流通最高 与 换手最低 =====')
for seg in ('全部','7-8月','9-10月'):
    agree=[];dis_s=[];dis_t=[];base=[]
    for g in G:
        if seg!='全部' and g.段.iloc[0]!=seg: continue
        a=g.封单占流通.idxmax(); b=g.turn.idxmin(); base.append(g.晋级.mean())
        if a==b: agree.append(g.loc[a,'晋级'])
        else: dis_s.append(g.loc[a,'晋级']); dis_t.append(g.loc[b,'晋级'])
    print(f'{seg}: 两者是同一只 {len(agree)} 组 晋级 {np.mean(agree):.0%} | 分歧 {len(dis_s)} 组: 封单那只 {np.mean(dis_s):.0%}, 低换手那只 {np.mean(dis_t):.0%} | 组均 {np.mean(base):.0%}')
print('\n===== ② 打分(封单占流通排名+低换手排名)最高那只 =====')
for lb in (2,3,4,'全部'):
    for seg in ('7-8月','9-10月'):
        gs=[g for g in G if (lb=='全部' or g.lb.iloc[0]==lb) and g.段.iloc[0]==seg]
        s=[g.loc[g.score.idxmax(),'晋级'] for g in gs]; b=[g.晋级.mean() for g in gs]
        print(f'{lb}板 {seg}: 组 {len(gs)}, 挑中晋级 {np.mean(s):.0%}, 组均 {np.mean(b):.0%}')
print('\n===== ③ 可交易: T+1 开盘买(开盘涨停买不到), T+2 收盘卖 =====')
for nm,key in (('打分最高','score'),('封单占流通最高','封单占流通'),('换手最低','r_turn'),('流通市值最小','r_cap')):
    for seg in ('7-8月','9-10月'):
        sel=[];grp=[];unf=0;n=0
        for g in G:
            if g.段.iloc[0]!=seg: continue
            s=g.loc[g[key].idxmax()]; n+=1
            if pd.isna(s.开买后日收): unf+=1; continue
            sel.append(s.开买后日收); grp.append(g.开买后日收.mean())
        print(f'{nm} {seg}: 组 {n}, 挑中那只开盘买不到 {unf}, 买得到 {len(sel)} 均 {np.nanmean(sel)*100:+.1f}% 中位 {np.nanmedian(sel)*100:+.1f}% 胜率 {np.mean(np.array(sel)>0):.0%}; 同组可买成员均 {np.nanmean(grp)*100:+.1f}%')
print('\n===== ④ 组内排名逻辑回归(晋级 ~ 各特征组内百分位), 分段 =====')
for seg in ('7-8月','9-10月'):
    a=A[A.段==seg].dropna(subset=['r_seal','r_turn','r_cap','r_first'])
    X=sm.add_constant(a[['r_seal','r_turn','r_cap','r_first']].assign(一字=a.一字,is20=a.is20.astype(int)))
    m=sm.Logit(a.晋级,X).fit(disp=0); print(seg,'样本',len(a)); print(pd.DataFrame({'系数':m.params.round(2),'p值':m.pvalues.round(3)}).T.to_string())
A.to_pickle('A.pkl')

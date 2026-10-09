#!/opt/homebrew/bin/python3.13
"""信号(只用T日收盘及以前): 某申万二级行业 T-1 与 T 两天强势数(涨停或涨>=9.9%)都排全市场前二, 且 T 日有二板股.
结局(只看T之后): 未来5/10/20个交易日累计强势数是否全市场第一(=主线); 交易: T+1开盘买入, 持有至T+5/T+10收盘, 相对全市场等权超额."""
import pandas as pd, numpy as np, sys
G=pd.read_parquet('sector_daily.parquet'); P=pd.read_parquet('stock_panel.parquet')
days=np.sort(G.date.unique()); di={d:i for i,d in enumerate(days)}
print('每日股票数 抽查',P.groupby('date').size().iloc[[0,100,300,-5,-1]].to_dict())
M=G.pivot(index='date',columns='l2',values='strong').fillna(0)
Z=G.pivot(index='date',columns='l2',values='zt').fillna(0)
L=G.pivot(index='date',columns='l2',values='lb2').fillna(0)
N=G.pivot(index='date',columns='l2',values='n').fillna(0)
name=G.drop_duplicates('l2').set_index('l2').l2n
def rk(X): return X.rank(axis=1,ascending=False,method='min')
R_s=rk(M); R_z=rk(Z); R_sh=rk(M/N.replace(0,np.nan))
# 交易收益: 板块等权 T+1开盘到 T+h收盘
P=P.sort_values(['code','date']); g=P.groupby('code')
for h in (5,10,20):
    P[f'f{h}']=g.ac.shift(-h)/g.ao.shift(-1)-1
P['o1']=g.open.shift(-1); P['zt1']=g.zt_px.shift(-1)
mkt={h:P.groupby('date')[f'f{h}'].mean() for h in (5,10,20)}
sec={h:P.groupby(['date','l2'])[f'f{h}'].mean() for h in (5,10,20)}
P['buy1']=P.o1<P.zt1-0.011    # T+1开盘不是一字涨停, 买得进
ld=P[P.zt]
lead={h:ld[ld.buy1].groupby(['date','l2'])[f'f{h}'].mean() for h in (5,10,20)}
def fut_rank(X,i,h):
    if i+h>=len(days): return None
    s=X.iloc[i+1:i+h+1].sum(); return s.rank(ascending=False,method='min')
def run(R,label,fresh=True,need_lb2=True,minc=3,Mcount=M):
    rows=[]
    for i in range(6,len(days)):
        T=days[i]; t1=days[i-1]
        ok=(R.loc[T]<=3)&(R.loc[t1]<=3)&(Mcount.loc[T]>=minc)&(Mcount.loc[t1]>=minc)
        if need_lb2: ok&=(L.loc[T]>=1)
        if fresh: ok&=~((R.iloc[i-6:i-1]<=3).any())
        for s in ok[ok].index:
            r={'date':T,'l2':s,'name':name[s],'cnt_t1':Mcount.loc[t1,s],'cnt_t':Mcount.loc[T,s],'lb2':L.loc[T,s]}
            for h in (5,10,20):
                fr=fut_rank(Mcount,i,h); r[f'rank{h}']=None if fr is None else fr[s]
                r[f'top2days{h}']=None if i+h>=len(days) else int((R.iloc[i+1:i+h+1][s]<=2).sum())
                r[f'ex{h}']=sec[h].get((T,s),np.nan)-mkt[h].get(T,np.nan)
                r[f'lead{h}']=lead[h].get((T,s),np.nan)-mkt[h].get(T,np.nan)
            rows.append(r)
    D=pd.DataFrame(rows); D['label']=label; return D
out=[]
out.append(run(R_s,'A 强势数前二两天+二板+新题材'))
out.append(run(R_s,'B 强势数前二两天+二板(不要求新)',fresh=False))
out.append(run(R_z,'C 涨停数前二两天+二板+新题材',Mcount=Z))
out.append(run(R_sh,'D 强势占比前二两天+二板+新题材',minc=3))
# 基准: 任意一天强势数前二(不要求连续, 不要求二板)
base=[]
for i in range(6,len(days)):
    T=days[i]; ok=(R_s.loc[T]<=3)&(M.loc[T]>=3)
    for s in ok[ok].index:
        r={'date':T,'l2':s,'name':name[s]}
        for h in (5,10,20):
            fr=fut_rank(M,i,h); r[f'rank{h}']=None if fr is None else fr[s]
            r[f'ex{h}']=sec[h].get((T,s),np.nan)-mkt[h].get(T,np.nan)
        base.append(r)
B=pd.DataFrame(base); B['label']='基准 单日强势数前二'
D=pd.concat(out+[B],ignore_index=True)
D.to_parquet('signals_top3.parquet'); print('信号总数',D.groupby('label').size().to_dict())

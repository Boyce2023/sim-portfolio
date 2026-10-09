#!/opt/homebrew/bin/python3.13
"""①信号内买龙头(最高板) vs 买全部涨停股 ②大范围涨停日, 题材里有流通市值>=300亿的涨停股, 命中率与买入收益"""
import pandas as pd, numpy as np, json, glob
R=pd.read_parquet('theme_rows_rich.parquet')
X=pd.read_csv('signals_features.csv',parse_dates=['date'])
cnt=pd.read_parquet('theme_cnt.parquet'); rk=cnt.rank(axis=1,ascending=False,method='min'); days=list(cnt.index)
P=pd.read_parquet('../../data/cn_hk_price_db/a_daily.parquet',columns=['date','ticker','open','close','adj_close'],filters=[('date','>=',pd.Timestamp('2025-09-01'))])
P['code']=P.ticker.str[:6]; P=P.sort_values(['code','date']); g=P.groupby('code')
P['f']=P.adj_close/P.close; P['ao']=P.open*P.f
P['pc']=g.close.shift(1)*g.f.shift(1)/P.f
for h in (5,10): P[f'r{h}']=g.adj_close.shift(-h)/g.ao.shift(-1)-1
P['o1']=g.open.shift(-1); P['pc1']=g.close.shift(0)
mk={h:P.groupby('date')[f'r{h}'].mean() for h in (5,10)}
Pi=P.set_index(['date','code'])
def ret(d,c,h):
    k=(d,c)
    if k not in Pi.index: return np.nan
    x=Pi.loc[k]; lim=round(x.close*(1.2 if c[:2] in('30','68') else 1.1),2)
    if pd.isna(x.o1) or x.o1>=lim-0.011: return np.nan   # 次日一字买不进
    return x[f'r{h}']-mk[h].get(d,np.nan)
def summ(s,lab):
    s=pd.Series(s).dropna(); w,l=s[s>0],s[s<=0]
    print(f'  {lab}: n={len(s)} 胜率{(s>0).mean()*100:.0f}% 均值{s.mean()*100:+.2f}% 中位{s.median()*100:+.2f}% 赔率{(w.mean()/abs(l.mean())) if len(l) else float("nan"):.2f}')
print('== ① 信号日次日开盘买入, 持10日, 相对全市场等权超额')
for sub,lab in [(X,'全部信号'),(X[(X.当日排名<=2)&(X.前10日已进前三天数>=5)],'A+D筛选后')]:
    lead=[];bask=[];big=[]
    for s in sub.itertuples():
        g2=R[(R.date==s.date)&(R.theme==s.theme)].drop_duplicates('code')
        L=g2.sort_values(['lb','t1'],ascending=[False,True]).iloc[0]
        lead.append(ret(s.date,L.code,10)); bask.append(np.nanmean([ret(s.date,c,10) for c in g2.code]))
    print(lab); summ(lead,'买最高板龙头'); summ(bask,'买全部涨停股等权')
for c,n in [('600127','金健米业'),('600664','哈药股份')]:
    r=R[R.code==c].drop_duplicates('date')
    print(n,'在涨停池出现的日期与板数:',' '.join(f"{d.strftime('%m%d')}:{lb}" for d,lb in zip(r.date,r.lb) if d>=pd.Timestamp('2026-06-01')))
print('\n== ② 大范围涨停日: 题材日(当日>=5只涨停), 是否含流通市值>=300亿的涨停股')
mz=R.drop_duplicates(['date','code']).groupby('date').size()
TD=R.drop_duplicates(['date','theme','code']).groupby(['date','theme']).agg(n=('code','size'),big=('cap',lambda x:(x>=300).sum())).reset_index()
TD=TD[TD.n>=5]; TD['mkt']=TD.date.map(mz)
out=[]
for r in TD.itertuples():
    i=days.index(r.date)
    if i+10>=len(days): continue
    s=cnt.iloc[i+1:i+11].sum().rank(ascending=False,method='min')[r.theme]
    out.append((r.date,r.theme,r.n,r.big,r.mkt,s))
O=pd.DataFrame(out,columns=['date','theme','n','big','mkt','rank10']); O['hit']=O.rank10<=2
q=O.mkt.quantile(2/3); print(f'大范围涨停日 = 全市场涨停数位于前三分之一(>= {q:.0f} 只)')
for lab,m in [('大范围日·有>=300亿涨停股',(O.mkt>=q)&(O.big>0)),('大范围日·无',(O.mkt>=q)&(O.big==0)),('普通日·有',(O.mkt<q)&(O.big>0)),('普通日·无',(O.mkt<q)&(O.big==0))]:
    x=O[m]; print(f'  {lab}: 题材日{len(x)} 之后10日排进前二 {x.hit.mean()*100:.0f}%  前段{x[x.date<"2026-04-01"].hit.mean()*100:.0f}% 后段{x[x.date>="2026-04-01"].hit.mean()*100:.0f}%')
# 买那只300亿以上涨停股本身
B=R[(R.cap>=300)].drop_duplicates(['date','code'])
B['mkt']=B.date.map(mz)
for lab,m in [('大范围日',B.mkt>=q),('普通日',B.mkt<q)]:
    print(lab); summ([ret(d,c,5) for d,c in zip(B[m].date,B[m].code)],'买该>=300亿涨停股 持5日'); summ([ret(d,c,10) for d,c in zip(B[m].date,B[m].code)],'持10日')
O.to_csv('bigcap_theme_days.csv',index=False,encoding='utf-8-sig')

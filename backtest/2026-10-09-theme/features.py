#!/opt/homebrew/bin/python3.13
"""信号日(T)可得的题材特征 + 结局(10日内累计涨停数排前二), 逐个特征看命中率, 分前后两段验稳定性"""
import json,glob,pandas as pd,numpy as np,datetime as dt
from theme import themes
rows=[]
for f in sorted(glob.glob('ths/*.json')):
    d=pd.Timestamp(f.split('/')[-1][:8]); rs=json.load(open(f))
    for r in rs:
        try: hd=int(r.get('high_days_value') or 65537)>>16  # 高16位=板数
        except: hd=1
        try: t1=dt.datetime.fromtimestamp(int(r.get('first_limit_up_time'))).strftime('%H%M')
        except: t1='9999'
        for th in themes(r.get('reason_type')):
            rows.append(dict(date=d,theme=th,code=r['code'],lb=hd,open_num=r.get('open_num') or 0,cap=(r.get('currency_value') or 0)/1e8,
                             t1=t1,yizi=str(r.get('limit_up_type') or '')=='一字板' or t1<='0925',turn=r.get('turnover_rate') or 0))
R=pd.DataFrame(rows); R.to_parquet('theme_rows_rich.parquet')
mk=pd.DataFrame([(pd.Timestamp(f.split('/')[-1][:8]),len(json.load(open(f)))) for f in sorted(glob.glob('ths/*.json'))],columns=['date','mkt_zt']).set_index('date').mkt_zt
S=pd.read_csv('sig_K3_M5_all.csv',parse_dates=['date']).dropna(subset=['rank10'])
cnt=pd.read_parquet('theme_cnt.parquet'); rk=cnt.rank(axis=1,ascending=False,method='min'); days=list(cnt.index)
F=[]
for s in S.itertuples():
    g=R[(R.date==s.date)&(R.theme==s.theme)].drop_duplicates('code'); i=days.index(s.date)
    prior=int(((rk.iloc[max(0,i-10):i-1][s.theme]<=3)).sum())
    F.append(dict(最高板=g.lb.max(),二板以上只数=(g.lb>=2).sum(),涨停数=len(g),涨停数增长=s.c_t-s.c_t1,当日排名=int(rk.loc[s.date,s.theme]),
                  炸板率=(g.open_num>0).mean(),早封占比=(g.t1<'1000').mean(),一字占比=g.yizi.mean(),流通市值中位=g.cap.median(),
                  换手中位=g.turn.median(),全市场涨停=mk.get(s.date,np.nan),前10日已进前三天数=prior))
X=pd.concat([S.reset_index(drop=True),pd.DataFrame(F)],axis=1)
X['命中']=(X.rank10<=2).astype(int); X['段']=np.where(X.date<'2026-04-01','前段','后段')
X.to_csv('signals_features.csv',index=False,encoding='utf-8-sig')
print('总体 n=%d 命中率 %.0f%%  前段 %.0f%%(n=%d) 后段 %.0f%%(n=%d)'%(len(X),X.命中.mean()*100,X[X.段=='前段'].命中.mean()*100,(X.段=='前段').sum(),X[X.段=='后段'].命中.mean()*100,(X.段=='后段').sum()))
for c in ['最高板','二板以上只数','涨停数','涨停数增长','当日排名','炸板率','早封占比','一字占比','流通市值中位','换手中位','全市场涨停','前10日已进前三天数']:
    try: q=pd.qcut(X[c].rank(method='first'),3,labels=['低','中','高'])
    except Exception: continue
    t=X.groupby(q,observed=True).agg(n=('命中','size'),命中率=('命中','mean'),ex10=('ex10','mean'))
    t2=X.groupby([q,X.段],observed=True).命中.mean().unstack()
    lo,hi=X.groupby(q,observed=True)[c].agg(['min','max']).values.T
    print(f"\n{c}: "+' | '.join(f"{lab}[{a:.2f}到{b:.2f}] n={int(r.n)} 命中{r.命中率*100:.0f}% (前段{t2.loc[lab,'前段']*100:.0f}% 后段{t2.loc[lab,'后段']*100:.0f}%) 买入10日超额{r.ex10*100:+.1f}%" for lab,a,b,r in zip(t.index,lo,hi,t.itertuples())))

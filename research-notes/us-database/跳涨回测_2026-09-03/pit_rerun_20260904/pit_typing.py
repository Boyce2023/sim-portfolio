import pandas as pd, numpy as np, yfinance as yf, warnings
warnings.filterwarnings('ignore')
e=pd.read_pickle('/tmp/e_data.pkl'); e['date']=pd.to_datetime(e['date'])
ts=sorted(e.t.unique()); print('股票数',len(ts))
# 重建全部跳涨: 2023-01-01起(给2024事件12个月前史)
px=yf.download(ts,start='2021-06-01',end='2026-01-10',progress=False,auto_adjust=False)['Close']
jumps=[]
for t in ts:
    s=px[t].dropna()
    r=s.pct_change()*100
    for d,v in r[r>=10].items():
        jumps.append({'t':t,'date':pd.Timestamp(d).tz_localize(None).normalize(),'chg':v})
J=pd.DataFrame(jumps)
er=set(zip(e.t,e.date.dt.normalize()))
J['is_er']=[ (r.t,r.date) in er for r in J.itertuples()]
J=J.sort_values('date')
print('重建跳涨总数(2021-06到2026-01, 74只)',len(J),'| 其中财报日',J.is_er.sum())
print('样本期内(2024-01到2025-12)跳涨', ((J.date>='2024-01-01')&(J.date<='2025-12-31')).sum())

def typ(n_all,er_share):
    if n_all>=15 and er_share<0.25: return '叙事型'
    if er_share>=0.40: return '财报型'
    return '混合'
# PIT分型: 只用事件日之前的跳涨
pit=[]
for r in e.itertuples():
    prior=J[(J.t==r.t)&(J.date<r.date)]
    n=len(prior)
    share=prior.is_er.mean() if n>0 else np.nan
    pit.append(typ(n,share) if n>=3 else '历史不足')
e['PIT类型']=pit
print(); print('PIT分型分布:'); print(e['PIT类型'].value_counts().to_string())
print(); print('原分型 vs PIT分型 交叉表:'); print(pd.crosstab(e['类型'],e['PIT类型']).to_string())

def z(a,na,b,nb):
    if na==0 or nb==0: return np.nan
    p=(a*na+b*nb)/(na+nb); s=(p*(1-p)*(1/na+1/nb))**.5
    return (b-a)/s if s>0 else np.nan
print(); print('='*60)
for col,lab in [('类型','原版(全期分型,含前视)'),('PIT类型','PIT分型(只用事件日之前的历史)')]:
    f=e[e[col]=='财报型']; A=f[~f.buy]; B=f[f.buy]
    if len(A)>0 and len(B)>0:
        a,b=(A.d252>0).mean(),(B.d252>0).mean()
        print('%s\n  财报型: 不买 %d个 %.0f%% | 会买 %d个 %.0f%% | 差 %.1fpp | z=%.2f'%(lab,len(A),a*100,len(B),b*100,(b-a)*100,z(a,len(A),b,len(B))))
# PIT下再按股票去重
f=e[e['PIT类型']=='财报型'].sort_values('date').drop_duplicates('t')
A=f[~f.buy]; B=f[f.buy]
if len(A)>0 and len(B)>0:
    a,b=(A.d252>0).mean(),(B.d252>0).mean()
    print('  PIT+按股票去重: 不买 %d只 %.0f%% | 会买 %d只 %.0f%% | 差 %.1fpp | z=%.2f'%(len(A),a*100,len(B),b*100,(b-a)*100,z(a,len(A),b,len(B))))
e.to_pickle('/tmp/e_pit.pkl'); J.to_pickle('/tmp/jumps_all.pkl')

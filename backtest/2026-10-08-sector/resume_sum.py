#!/opt/homebrew/bin/python3.13
"""汇总: 只看和三峡新材可比的(复牌前流通市值<=100亿), 分首日一字与否"""
import pandas as pd, numpy as np
R=pd.read_csv('resume_cases.csv',dtype={'code':str})
F=pd.read_parquet('../2026-09-29-wf/panel.parquet',columns=['code','date','close','fshare'])
F=F.sort_values('date')
R['resume']=pd.to_datetime(R.resume)
fc=[]
for _,r in R.iterrows():
    s=F[(F.code==r.code)&(F.date<r.resume)].tail(1)
    fc.append(np.nan if s.empty else s.close.iloc[0]*s.fshare.iloc[0]/1e8)
R['复牌前流通市值亿']=fc
R.to_csv('resume_cases.csv',index=False,encoding='utf-8-sig')
C=R[(R['复牌前流通市值亿']<=100)]
print('全部',len(R),' 流通<=100亿',len(C),' 其中首日一字',C['首日一字'].sum())
def show(d,lab):
    print(f'\n== {lab} n={len(d)}')
    print('复牌连板数分布:',d['复牌连板'].value_counts().sort_index().to_dict())
    print(f"峰值涨幅 中位{d['峰值涨幅%'].median():.0f}% 均值{d['峰值涨幅%'].mean():.0f}% | 峰值在第几天 中位{d['峰值日(复牌第几天)'].median():.0f}")
    for c in ['断板日开盘卖%','断板日收盘卖%','断板次日收盘卖%','20日后涨幅%']:
        x=d[c].dropna(); print(f"  {c}: 中位{x.median():+.1f}% 均值{x.mean():+.1f}% 为正比例{(x>0).mean()*100:.0f}%")
    print(f"  断板后20日内再创新高 {d['断板后20日内再创新高'].mean()*100:.0f}%")
    # 卖在断板日开盘 相对 死拿20日 的差
    x=(d['断板日开盘卖%']-d['20日后涨幅%']).dropna(); print(f"  断板开盘卖 比 拿满20日 多赚: 中位{x.median():+.1f}个点, 胜出比例{(x>0).mean()*100:.0f}%")
show(C[C['首日一字']],'首日一字(复牌直接封死)')
show(C[~C['首日一字']],'首日非一字')
show(C[C['首日一字']&(C['复牌连板']>=2)],'首日一字且至少2连板')
print('\n首日一字的连板数 与 断板后20日内再创新高:')
print(C[C['首日一字']].groupby(C['复牌连板'].clip(upper=5)).agg(n=('code','size'),峰值中位=('峰值涨幅%','median'),再创新高=('断板后20日内再创新高','mean'),断板开盘卖中位=('断板日开盘卖%','median'),拿20日中位=('20日后涨幅%','median')).round(2))
print(C[C['首日一字']].sort_values('resume')[['code','name','resume','复牌前流通市值亿','复牌连板','峰值日(复牌第几天)','峰值涨幅%','断板日开盘卖%','20日后涨幅%','title']].round(1).tail(45).to_string())

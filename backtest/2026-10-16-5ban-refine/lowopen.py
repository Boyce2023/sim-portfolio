"""五板后 T+2 / T+3 低开(相对前一日收盘 <= -4.5%)的后续走势. 买点=当天开盘价.
T 为五板日; 2024-01 至今(价格库到 2026-10-14). 一字跌停开盘(开=低=跌停价)视为买得到但标出."""
import pandas as pd, numpy as np
A=pd.read_parquet('../../data/cn_hk_price_db/a_daily.parquet',columns=['date','ticker','open','high','low','close','adj_close'],filters=[('date','>=',pd.Timestamp('2023-10-01'))])
A=A[A.ticker.str.endswith(('.SH','.SZ'))].copy(); A['code']=A.ticker.str[:6]
A=A.sort_values(['code','date']).reset_index(drop=True); g=A.groupby('code')
A['adjf']=A.adj_close/A.close; A['prevc']=g.close.shift(1)*g.adjf.shift(1)/A.adjf
F=pd.read_parquet('../2026-09-29-wf/feat.parquet',columns=['code','date','isST'])
A=A.merge(F,on=['code','date'],how='left'); last=F.sort_values('date').groupby('code').tail(1).set_index('code').isST
A['isST']=A.isST.fillna(A.code.map(last)).fillna(0)
A=A.sort_values(['code','date']).reset_index(drop=True); g=A.groupby('code')
big=A.code.str[:3].isin(['300','301','688','689'])
A['lim']=np.where(big,0.2,np.where((A.isST==1)&(A.date<'2026-07-06'),0.05,0.1))
A['zt']=(A.close>=(A.prevc*(1+A.lim)).round(2)-0.011)&A.prevc.notna()
A['nth']=g.cumcount()
s=A.zt.astype(int); grp=(s!=s.groupby(A.code).shift()).cumsum(); A['streak']=s.groupby([A.code,grp]).cumsum()*s
g=A.groupby('code')
for k in range(1,8):
    for c in ['open','high','low','close','adjf','zt','prevc','lim']: A[f'{c}{k}']=g[c].shift(-k)
E=A[(A.streak==5)&(A.date>='2024-01-01')&(A.nth>=10)].copy()
def run(day):
    d=E[E[f'close{day+3}'].notna()].copy()
    pc=d[f'prevc{day}']; o=d[f'open{day}']
    d['gap']=o/pc-1
    d['dt_open']=o<=(pc*(1-d[f'lim{day}'])).round(2)+0.011
    af=d[f'adjf{day}']; buy=o*af
    d['r_c0']=d[f'close{day}']*af/buy-1
    for h in (1,2,3): d[f'r_c{h}']=d[f'close{day+h}']*d[f'adjf{day+h}']/buy-1
    d['zt_day']=d[f'zt{day}'].astype(bool)
    d['path']=np.where(d.zt1.astype(bool),'T+1封六板','T+1没封')
    return d
def rep(x,lab):
    if len(x)==0: print(f'  {lab}: 0'); return
    t=lambda c:f"均{x[c].mean()*100:+.1f}% 中位{x[c].median()*100:+.1f}% 胜{(x[c]>0).mean()*100:.0f}%"
    print(f"  {lab} n={len(x)} | 当日收: {t('r_c0')} | 次日收: {t('r_c1')} | 第3日收: {t('r_c3')} | 当天反封涨停{x.zt_day.mean()*100:.0f}%")
for day in (2,3):
    d=run(day); print(f'\n===== 五板后 T+{day} 开盘买 (相对前收的开盘缺口) =====')
    for per,m in [('2026-07起',d.date>='2026-07-01'),('2026全年',d.date>='2026-01-01'),('2024起',d.date>='2024-01-01')]:
        x=d[m]; print(per)
        rep(x,'全部')
        rep(x[x.gap<=-0.045],'低开<=-4.5%')
        rep(x[(x.gap<=-0.045)&~x.dt_open],'  其中非跌停开')
        rep(x[(x.gap>-0.045)&(x.gap<=0)],'低开0到-4.5%')
        rep(x[x.gap>0],'高开')
    lo=d[(d.gap<=-0.045)&(d.date>='2026-07-01')].copy()
    import json,glob
    names={}
    for f in glob.glob('../2026-10-09-theme/ths/2026*.json'):
        for r in json.load(open(f)): names[r['code']]=r['name']
    lo['name']=lo.code.map(names)
    print(lo[['date','code','name','path','gap','r_c0','r_c1','r_c3']].assign(gap=lambda z:(z.gap*100).round(1),r_c0=lambda z:(z.r_c0*100).round(1),r_c1=lambda z:(z.r_c1*100).round(1),r_c3=lambda z:(z.r_c3*100).round(1)).to_string(index=False))
    if day==2:
        print('\n按T+1路径(2024起, 低开<=-4.5%):')
        x=d[d.gap<=-0.045]
        for p,y in x.groupby('path'): rep(y,p)
print('\n==== 百洋同型: T+1 收在跌停, T+2 低开<=-4.5% 且不是跌停开 ====')
d=run(2)
d['t1_dt']=d.close1<=(d.close*(1-d.lim1)).round(2)+0.011
for per,m in [('2026全年',d.date>='2026-01-01'),('2024起',d.date>='2024-01-01')]:
    x=d[m&d.t1_dt&(d.gap<=-0.045)&~d.dt_open]; print(per); rep(x,'同型')
    x2=d[m&d.t1_dt]; rep(x2,'T+1收跌停的全部(不管T+2怎么开)')

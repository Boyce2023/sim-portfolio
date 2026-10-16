"""五板策略精细化: 2024起每个五板事件, 算买入那一刻(T+1开盘)能拿到的特征, 看哪些能区分 T+2收盘结果和 T+1触跌停.
策略口径: T+1开盘买(开盘一字买不到的剔除), T+2收盘卖. 切分: 2024-2025 样本内定分档阈值, 2026 样本外检验."""
import pandas as pd, numpy as np
A=pd.read_parquet('../../data/cn_hk_price_db/a_daily.parquet',columns=['date','ticker','open','high','low','close','adj_close','oshare','turn'],filters=[('date','>=',pd.Timestamp('2023-10-01'))])
A=A[A.ticker.str.endswith(('.SH','.SZ'))].copy(); A['code']=A.ticker.str[:6]
A=A.sort_values(['code','date']).reset_index(drop=True); g=A.groupby('code')
A['adjf']=A.adj_close/A.close; A['prevc']=g.close.shift(1)*g.adjf.shift(1)/A.adjf
F=pd.read_parquet('../2026-09-29-wf/feat.parquet',columns=['code','date','isST'])
A=A.merge(F,on=['code','date'],how='left'); last=F.sort_values('date').groupby('code').tail(1).set_index('code').isST
A['isST']=A.isST.fillna(A.code.map(last)).fillna(0)
A=A.sort_values(['code','date']).reset_index(drop=True); g=A.groupby('code')
big=A.code.str[:3].isin(['300','301','688','689'])
A['lim']=np.where(big,0.2,np.where((A.isST==1)&(A.date<'2026-07-06'),0.05,0.1))
A['zt_px']=(A.prevc*(1+A.lim)).round(2); A['dt_px']=(A.prevc*(1-A.lim)).round(2)
A['zt']=(A.close>=A.zt_px-0.011)&A.prevc.notna(); A['dt']=(A.close<=A.dt_px+0.011)&A.prevc.notna()
A['nth']=g.cumcount()
s=A.zt.astype(int); grp=(s!=s.groupby(A.code).shift()).cumsum(); A['streak']=s.groupby([A.code,grp]).cumsum()*s
g=A.groupby('code'); A['streak_prev']=g.streak.shift(1)
A['chg']=A.close/A.prevc-1
# 市场情绪(当天收盘可得)
ok=A.nth>=5
M=A[ok].groupby('date').agg(n_zt=('zt','sum'),n_dt=('dt','sum'),max_streak=('streak','max'),
    eq_ret=('chg','mean'))
hb=A[ok&(A.streak_prev>=3)]
M['high_break']=hb.assign(b=(~hb.zt)&(hb.chg<-0.05)).groupby('date').b.sum()   # 昨天>=3板今天断板且跌>5%
M['high_n']=hb.groupby('date').size()
M['n_5plus']=A[ok&(A.streak>=5)].groupby('date').size()
M=M.fillna(0)
# 行业涨停数
ind=pd.read_csv('../2026-10-15-review2022/industry.csv',dtype=str); ind['code']=ind.code.str[3:]
A=A.merge(ind[['code','industry']],on='code',how='left')
A['ind_zt']=A.groupby(['date','industry']).zt.transform('sum')
A['ind_maxstreak']=A.groupby(['date','industry']).streak.transform('max')
g=A.groupby('code')
for k in (1,2): 
    for c in ['open','high','low','close','adjf','zt_px','dt_px','date']: A[f'{c}{k}']=g[c].shift(-k)
for k in range(1,5): A[f'turn_m{k}']=g.turn.shift(k)
A['close_m5']=g.close.shift(5)*g.adjf.shift(5)/A.adjf
E=A[(A.streak==5)&(A.date>='2024-01-01')&(A.nth>=10)&A.close2.notna()].copy()
E=E.merge(M,left_on='date',right_index=True,how='left')
E['yizi1']=(E.open1>=E.zt_px1-0.011)&(E.low1>=E.zt_px1-0.011)
E=E[~E.yizi1].copy()
E['ret']=E.close2*E.adjf2/(E.open1*E.adjf1)-1
E['touch']=E.low1<=E.dt_px1+0.011
# 特征: 只用五板收盘 + T+1开盘可得
E['f_gap']=E.open1/E.close-1
E['f_turn5']=E.turn
E['f_jump']=E.turn/E[[f'turn_m{k}' for k in range(1,5)]].mean(axis=1)
E['f_cap']=E.oshare*E.close/1e8
E['f_yizi5']=((E.open>=E.zt_px-0.011)&(E.low>=E.zt_px-0.011)).astype(int)
E['f_dip5']=E.low/E.prevc-1          # 五板当天盘中最深回撤(烂板程度)
E['f_open5']=E.open/E.prevc-1
E['f_20cm']=(E.lim==0.2).astype(int)
E['f_st']=(E.isST==1).astype(int)
E['f_n_zt']=E.n_zt; E['f_n_dt']=E.n_dt; E['f_high_break']=E.high_break
E['f_max_streak']=E.max_streak; E['f_is_top']=(E.streak>=E.max_streak).astype(int)
E['f_n_5plus']=E.n_5plus; E['f_eq_ret']=E.eq_ret
E['f_ind_zt']=E.ind_zt; E['f_ind_top']=(E.streak>=E.ind_maxstreak).astype(int)
E['f_px']=E.close
E.to_pickle('events.pkl')
print('事件',len(E),'样本内(2024-25)',(E.date<'2026-01-01').sum(),'样本外(2026)',(E.date>='2026-01-01').sum())

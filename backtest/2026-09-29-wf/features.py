#!/opt/homebrew/bin/python3.13
"""特征: 只用 t 日收盘及以前; 标签: t+1 开盘买, t+11 开盘卖 的收益(复权), 及其横截面超额
个股记忆(mem_*): 该股过去"单日涨>=5%"之后 10 日实际收益的累计均值, 只纳入 t 日前已揭晓的事件"""
import pandas as pd, numpy as np
P=pd.read_parquet('panel.parquet').sort_values(['code','date']).reset_index(drop=True)
P=P[P.open>0].reset_index(drop=True)
P['prevc']=P.groupby('code').close.shift(1)*P.groupby('code').adjf.shift(1)/P.adjf   # 除权后的前收盘
g=P.groupby('code',sort=False)
P['ao']=P.open*P.adjf; P['ac']=P.close*P.adjf; P['ah']=P.high*P.adjf; P['al']=P.low*P.adjf
big=P.code.str[:3].isin(['300','301','688'])
P['lim']=np.where(big,0.2,np.where(P.isST==1,0.05,0.1))
P['zt_px']=(P.prevc*(1+P.lim)).round(2); P['dt_px']=(P.prevc*(1-P.lim)).round(2)
P['zt']=(P.close>=P.zt_px-0.011)&P.prevc.notna(); P['dt']=(P.close<=P.dt_px+0.011)&P.prevc.notna()
P['r1']=g.ac.pct_change(fill_method=None)
F={}
def roll(col,w,fn):
    return g[col].transform(lambda s:getattr(s.rolling(w,min_periods=max(2,w*2//3)),fn)())
for n in [3,5,10,20,60]: P[f'r{n}']=P.ac/g.ac.shift(n)-1
P['vol20']=roll('r1',20,'std')
P['zt5']=roll('zt',5,'sum'); P['zt20']=roll('zt',20,'sum'); P['dt20']=roll('dt',20,'sum')
P['up']=(P.r1>0).astype(float); P['up5']=roll('up',5,'sum'); P['up10']=roll('up',10,'sum')
P['t1']=P.turn; P['t5']=roll('turn',5,'mean'); P['t20']=roll('turn',20,'mean'); P['t60']=roll('turn',60,'mean')
P['tr1']=P.t1/P.t20; P['tr5']=P.t5/P.t20; P['tr20']=P.t20/P.t60
P['mx20']=roll('ac',20,'max'); P['mn20']=roll('ac',20,'min'); P['mx60']=roll('ac',60,'max')
P['box20']=P.mx20/P.mn20-1; P['dh20']=P.ac/P.mx20-1; P['dh60']=P.ac/P.mx60-1; P['dl20']=P.ac/P.mn20-1
P['ma5']=roll('ac',5,'mean'); P['ma20']=roll('ac',20,'mean'); P['ma60']=roll('ac',60,'mean')
P['c_ma5']=P.ac/P.ma5-1; P['c_ma20']=P.ac/P.ma20-1; P['ma5_20']=P.ma5/P.ma20-1; P['ma20_60']=P.ma20/P.ma60-1
rng=(P.high-P.low).replace(0,np.nan)
P['clv']=(P.close-P.low)/rng; P['upsh']=(P.high-np.maximum(P.open,P.close))/P.close; P['body']=P.close/P.open-1
P['gap']=P.open/P.prevc-1
P['fcap']=P.close*P.fshare/1e8; P['lfcap']=np.log(P.fcap.clip(lower=0.5)); P['lamt']=np.log(P.amount.clip(lower=1e5))
P['amt20']=roll('amount',20,'mean'); P['amt_r']=P.amount/P.amt20
P['b20']=big.astype(int); P['lpx']=np.log(P.close)
P['age']=g.cumcount()
# 市场层(等权, 同日)
M=P.groupby('date').agg(m_r1=('r1','mean'),m_up=('up','mean'),m_zt=('zt','sum'),m_dt=('dt','sum'))
M['m_idx']=(1+M.m_r1.fillna(0)).cumprod()
for n in [5,20]: M[f'm_r{n}']=M.m_idx/M.m_idx.shift(n)-1
M['m_zt5']=M.m_zt.rolling(5).mean(); M['m_dt5']=M.m_dt.rolling(5).mean()
P=P.merge(M[['m_r1','m_up','m_zt','m_dt','m_r5','m_r20','m_zt5','m_dt5']],left_on='date',right_index=True,how='left')
P['rs5']=P.r5-P.m_r5; P['rs20']=P.r20-P.m_r20

# 形态池: 前置基座(截至 t-6 的 20 日) 与 近 5 日动作
g=P.groupby('code',sort=False)
P['box_pre']=g.ac.transform(lambda s:s.shift(5).rolling(20,min_periods=15).max()/s.shift(5).rolling(20,min_periods=15).min()-1)
P['r_pre']=g.ac.transform(lambda s:s.shift(5)/s.shift(25)-1)
P['t_pre']=g.turn.transform(lambda s:s.shift(5).rolling(20,min_periods=15).mean())
P['box_1']=g.ac.transform(lambda s:s.shift(1).rolling(20,min_periods=15).max()/s.shift(1).rolling(20,min_periods=15).min()-1)
P['r20_1']=g.ac.transform(lambda s:s.shift(1)/s.shift(21)-1)
P['t20_1']=g.turn.transform(lambda s:s.shift(1).rolling(20,min_periods=15).mean())
P['mxr5']=g.r1.transform(lambda s:s.rolling(5,min_periods=3).max())
ign=(P.box_1<=0.25)&P.r20_1.between(-0.10,0.15)&(P.t20_1<=0.035)&P.r1.between(0.04,0.095)&(~P.zt)&(P.turn>=2*P.t20_1)
stp=P.r5.between(0.08,0.30)&(P.zt5<=1)&(P.up5>=3)&(P.box_pre<=0.30)&P.r_pre.between(-0.15,0.15)&(~P.zt)
P['pool']=np.where(ign,1,np.where(stp,2,0))
# 标签
H=10
g=P.groupby('code',sort=False)
P['o1']=g.ao.shift(-1); P['oH']=g.ao.shift(-1-H)
P['y']=P.oH/P.o1-1
P['d1']=g.date.shift(-1); P['dH']=g.date.shift(-1-H)
# 次日能否买入: 次日开盘 < 次日涨停价
P['o1raw']=g.open.shift(-1); P['zt1']=g.zt_px.shift(-1)
P['fill']=(P.o1raw<P.zt1-0.001)
# 个股记忆(因果): 事件=当日涨>=5%; 结果 y 在 dH 揭晓; 用 shift(H+2) 保证 t 时已揭晓
ev=np.where(P.r1>=0.05,P.y,np.nan)
P['_ev']=ev; P['_evn']=(~np.isnan(ev)).astype(float); P['_evs']=np.nan_to_num(ev)
g=P.groupby('code',sort=False)
cs=g._evs.transform(lambda s:s.shift(H+2).fillna(0).cumsum()); cn=g._evn.transform(lambda s:s.shift(H+2).fillna(0).cumsum())
P['mem_n']=cn; P['mem_y']=np.where(cn>0,cs/cn.replace(0,np.nan),np.nan)
P['mem_y']=(P.mem_y*cn+0*3)/(cn+3)   # 向 0 收缩, 样本少时不乱给分
P=P.drop(columns=['_ev','_evn','_evs'])
# 横截面超额(训练目标)
P['yx']=P.y-P.groupby('date').y.transform('mean')
P.to_parquet('feat.parquet')
print('特征表',P.shape, P.date.min().date(),P.date.max().date())

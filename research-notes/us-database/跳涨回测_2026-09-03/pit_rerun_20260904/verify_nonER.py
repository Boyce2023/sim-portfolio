import pandas as pd, numpy as np, yfinance as yf, warnings
warnings.filterwarnings('ignore')
J=pd.read_pickle('/tmp/jumps_all.pkl'); e=pd.read_pickle('/tmp/e_data.pkl')
S=J[(J.date>='2024-01-01')&(J.date<='2025-12-31')].copy()
ts=sorted(S.t.unique())
px=yf.download(ts,start='2023-12-01',end='2026-09-05',progress=False,auto_adjust=False)['Close']
def fwd(t,d,n):
    s=px[t].dropna(); s=s[s.index.tz_localize(None)>=d] if s.index.tz is not None else s[s.index>=d]
    return (s.iloc[n]/s.iloc[0]-1)*100 if len(s)>n else np.nan
S['d63']=[fwd(r.t,r.date,63) for r in S.itertuples()]
S['d252']=[fwd(r.t,r.date,252) for r in S.itertuples()]
er=S[S.is_er]; non=S[~S.is_er]
print("我发布过的说法: 非财报跳涨63日中位+13.9%, 财报跳涨+9.5%, 且'非财报比财报还好'")
print()
print("%-14s %5s %10s %10s %12s"%("组","n","63日中位","252日中位","一年为正"))
for lab,g in [("财报日跳涨",er),("非财报跳涨",non)]:
    v=g.d63.dropna(); w=g.d252.dropna()
    print("%-14s %5d %9.1f%% %9.1f%% %11.0f%%"%(lab,len(g),v.median(),w.median(),(w>0).mean()*100))
print()
print("差值: 非财报 - 财报 = %+.1fpp (63日中位)"%(non.d63.median()-er.d63.median()))
print("样本口径注: 本表为74只有财报跳涨的股票, 共%d次跳涨(财报%d/非财报%d)"%(len(S),len(er),len(non)))
S.to_pickle('/tmp/jumps_2425.pkl')

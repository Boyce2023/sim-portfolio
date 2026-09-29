#!/opt/homebrew/bin/python3.13
"""面板: 主价格库(2023-01..2026-09-23) + baostock 当期股票池里后来退市的票 + 逐日 isST
输出 panel.parquet: code,date,open,high,low,close,prevc,adjf,amount,turn,fshare,isST,src"""
import pandas as pd, numpy as np, sqlite3, glob
B='/Users/huaichuaibeimeng/claude-projects/sim-portfolio'
m=pd.read_parquet(f'{B}/data/cn_hk_price_db/a_daily.parquet',
   columns=['date','ticker','open','high','low','close','adj_close','volume','amount','oshare','turn'],
   filters=[('date','>=',pd.Timestamp('2023-01-01'))])
m=m[m.ticker.str.endswith(('.SH','.SZ'))].copy()
m['code']=m.ticker.str[:6]; m=m[m.code.str[:2].isin(['60','00','30','68'])]
m['adjf']=m.adj_close/m.close; m['fshare']=m.oshare; m['src']='db'
m=m[['code','date','open','high','low','close','adjf','amount','turn','fshare','src','volume']]
U=[]
import subprocess
snap='/tmp/univ2024h2_snap.db'
subprocess.run(['sqlite3',f'{B}/backtest/2026-09-29-wf/univ2024h2.db',f'.timeout 60000',f'.backup {snap}'],check=True)
n24=sqlite3.connect(snap).execute('select count(distinct code) from k').fetchone()[0]
assert n24>1000, f'2024H2 快照只有 {n24} 只, 停'
print('2024H2 快照股票数',n24)
for f in [snap]+sorted(glob.glob(f'{B}/backtest/2026-08-24-daban/univ20*.db')):
    try: d=pd.read_sql('select * from k',sqlite3.connect(f)); d['f']=f.split('/')[-1]; U.append(d)
    except Exception as e:
        if 'univ2024h2' in f: raise
        print('跳过',f,e)
u=pd.concat(U); u['code']=u.code.str[3:]; u['date']=pd.to_datetime(u.date)
u=u[(u.volume>0)&(u.close>0)].drop_duplicates(['code','date'],keep='last')
print('univ 行',len(u),'股票',u.code.nunique(),'区间',u.date.min().date(),u.date.max().date())
# ST 标记: univ 逐日; 其余日期按股票前后填
st=u[['code','date','isST']]
# 退市补入: univ 里有、主库里(该日)没有的股票
miss=set(u.code)-set(m.code)
x=u[u.code.isin(miss)].copy()
x['adjf']=1.0; x['fshare']=np.where(x.turn>0,x.volume/(x.turn/100),np.nan); x['turn']=x.turn/100; x['src']='univ'
x=x[['code','date','open','high','low','close','adjf','amount','turn','fshare','src','volume']]
print('主库缺失、从 univ 补入的股票',len(miss),'行',len(x))
P=pd.concat([m,x]).sort_values(['code','date']).reset_index(drop=True)
P=P.merge(st,on=['code','date'],how='left')
P['isST']=P.groupby('code').isST.transform(lambda s:s.ffill().bfill()).fillna(0).astype(int)
P['prevc']=P.groupby('code').close.shift(1)
P.to_parquet('panel.parquet')
print('面板',len(P),'行',P.code.nunique(),'只',P.date.min().date(),P.date.max().date(),' ST行占比',round(P.isST.mean()*100,2),'%')
print(x.groupby('code').date.max().describe())

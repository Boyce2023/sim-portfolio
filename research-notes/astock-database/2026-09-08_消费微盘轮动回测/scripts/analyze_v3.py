# -*- coding: utf-8 -*-
"""阶段1 (新浪源: 逐日流通股本+换手率): episode识别
⛔ 反前视: 微盘=当日截面分位(消费全域) | 触发只用t及之前 | 阈值无全样本统计量"""
import sqlite3, json, numpy as np, pandas as pd
mem=json.load(open('/tmp/dhbr/sw2_members.json'))
n2c=json.load(open('/tmp/dhbr/n2c.json')); c2n={v:k for k,v in n2c.items()}
code2sub={}; code2par={}; code2name={}
for sw,v in mem.items():
    for c in v['codes']:
        bs=('sh.' if c[0]=='6' else 'sz.')+c
        code2sub[bs]=v['name']; code2par[bs]=v['parent']; code2name[bs]=c2n.get(c,c)
con=sqlite3.connect('/tmp/dhbr/hist10y_sina.db')
df=pd.read_sql("select code,date,open,high,low,close,volume,oshare,turn from k where oshare>0 and close>0",con); con.close()
df['date']=pd.to_datetime(df['date']); df=df.sort_values(['code','date']).reset_index(drop=True)
print(f"载入 {len(df):,} 行 / {df.code.nunique()} 只 / {df.date.min().date()}~{df.date.max().date()}")
df['float_mv']=df['close']*df['oshare']          # 流通市值(元), 逐日point-in-time
g=df.groupby('code',sort=False)
df['pctChg']=g['close'].transform(lambda s:(s/s.shift(1)-1)*100)
df['ret20']=g['close'].transform(lambda s:s/s.shift(20)-1)
df['turn_ma60']=g['turn'].transform(lambda s:s.rolling(60,min_periods=40).mean())
def thr(code,dt):
    c=code[3:]
    if c.startswith(('688','689')): return 19.5
    if c.startswith(('300','301')): return 19.5 if dt>=pd.Timestamp('2020-08-24') else 9.5
    return 9.5
df['is_lim']=[1 if p>=thr(c,d) else 0 for c,d,p in zip(df.code,df.date,df.pctChg.fillna(0))]
df['lim20']=g['is_lim'].transform(lambda s:s.rolling(20,min_periods=20).sum())
df['mv_pct']=df.groupby('date')['float_mv'].rank(pct=True)     # 当日截面(消费全域)
st_now={c for c,n in code2name.items() if 'ST' in n or '退' in n}
df['isST']=df.code.isin(st_now).astype(int)
df['trig_raw']=((df.ret20>=0.40)&(df.lim20>=2)&(df.turn>=2*df.turn_ma60)&(df.isST==0)).astype(int)
print(f"原始触发点 {int(df.trig_raw.sum()):,}")
trig=[]
for code,sub in df[df.trig_raw==1].groupby('code',sort=False):
    last=None
    for _,r in sub.iterrows():
        if last is None or (r.date-last).days>=130: trig.append(r); last=r.date
T=pd.DataFrame(trig); T['sub']=T.code.map(code2sub); T['par']=T.code.map(code2par); T['name']=T.code.map(code2name)
T['micro']=T.mv_pct<=0.30
print(f"去重后 episode {len(T):,} (微盘 {int(T.micro.sum()):,})")
T.to_pickle('/tmp/dhbr/episodes.pkl'); df.to_pickle('/tmp/dhbr/panel.pkl')
print("\n按年(列=是否微盘):"); print(T.groupby([T.date.dt.year,'micro']).size().unstack(fill_value=0).to_string())

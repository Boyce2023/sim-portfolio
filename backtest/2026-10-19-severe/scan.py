"""近一年严重异常波动扫描(按交易所规则自算, 2023-04-10 起施行的口径).
偏离值 = 个股日涨跌幅 - 基准指数日涨跌幅; 基准: 沪主板上证指数, 深主板深证成指, 创业板创业板指, 科创板科创50 (与恢恢量化同口径).
严重异常波动(任一): ①连续10个交易日偏离值累计 >= +100% 或 <= -50% ②连续30个交易日累计 >= +200% 或 <= -70%
                    ③10个交易日内同向异常波动 主板4次/双创3次 (异常波动=连续3日累计偏离 主板±20% 双创±30%, 触发后重新计数)
数据: 价格库 a_daily(不复权收盘与交易所前收盘口径用 adj 推算), 指数用新浪日K. 新股上市前5日剔除. 每次触发后同方向10个交易日内不重复记."""
import json,re,urllib.request
import pandas as pd, numpy as np
H={'Referer':'https://finance.sina.com.cn','User-Agent':'Mozilla/5.0'}
def idx(sym):
    u=f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20x=/CN_MarketDataService.getKLineData?symbol={sym}&scale=240&ma=no&datalen=400"
    raw=urllib.request.urlopen(urllib.request.Request(u,headers=H),timeout=15).read().decode()
    B=json.loads(re.search(r"x=\((\[.*\])\)",raw,re.S).group(1))
    s=pd.Series({pd.Timestamp(b['day']):float(b['close']) for b in B}).sort_index()
    return s.pct_change()
I={'sh':idx('sh000001'),'sz':idx('sz399001'),'cyb':idx('sz399006'),'kcb':idx('sh000688')}
A=pd.read_parquet('../../data/cn_hk_price_db/a_daily.parquet',columns=['date','ticker','open','high','low','close','adj_close','oshare'],filters=[('date','>=',pd.Timestamp('2025-08-01'))])
A=A[A.ticker.str.endswith(('.SH','.SZ'))].copy(); A['code']=A.ticker.str[:6]
A=A.sort_values(['code','date']).reset_index(drop=True); g=A.groupby('code')
A['adjf']=A.adj_close/A.close; A['ret']=A.adj_close/g.adj_close.shift(1)-1
first=pd.read_parquet('../../data/cn_hk_price_db/a_daily.parquet',columns=['ticker','date']).groupby('ticker').date.min()
A['listed']=A.ticker.map(first)
A['nth']=(A.date.map(lambda d:d)>0) if False else None
A['board']=np.where(A.code.str[:3].isin(['688','689']),'kcb',np.where(A.code.str[:3].isin(['300','301']),'cyb',np.where(A.code.str[0]=='6','sh','sz')))
A['iret']=np.nan
for b,s in I.items():
    m=A.board==b; A.loc[m,'iret']=A.loc[m,'date'].map(s).values
A['dev']=A.ret-A.iret
# 新股前5个交易日剔除
A['k']=g.cumcount(); A['since']=A.groupby('code').date.transform(lambda x: np.arange(len(x)))
A['young']=A.date<=A.listed+pd.Timedelta(days=10)
A.loc[A.young,'dev']=np.nan
A['dev0']=A.dev.fillna(0)
g=A.groupby('code')
A['c10']=g.dev0.transform(lambda x:x.rolling(10,min_periods=10).sum())
A['c30']=g.dev0.transform(lambda x:x.rolling(30,min_periods=30).sum())
A['c3']=g.dev0.transform(lambda x:x.rolling(3,min_periods=3).sum())
ev=[]
for c,d in A.groupby('code'):
    d=d.reset_index(drop=True); dual=d.board[0] in ('cyb','kcb'); th3=0.30 if dual else 0.20; need=3 if dual else 4
    ab_up=[]; ab_dn=[]; last_ab=-99; cool={'up':-99,'dn':-99}
    for i in range(len(d)):
        if d.date[i]<pd.Timestamp('2025-10-15'): 
            pass
        # 异常波动计数(触发后重新计数: 要求与上次异常波动窗口不重叠)
        if i-last_ab>=3 and pd.notna(d.c3[i]):
            if d.c3[i]>=th3: ab_up.append(i); last_ab=i
            elif d.c3[i]<=-th3: ab_dn.append(i); last_ab=i
        if d.date[i]<pd.Timestamp('2025-10-15'): continue
        hit=[]
        if pd.notna(d.c10[i]) and d.c10[i]>=1.0: hit.append(('up','10日累计+100%'))
        if pd.notna(d.c30[i]) and d.c30[i]>=2.0: hit.append(('up','30日累计+200%'))
        if pd.notna(d.c10[i]) and d.c10[i]<=-0.5: hit.append(('dn','10日累计-50%'))
        if pd.notna(d.c30[i]) and d.c30[i]<=-0.7: hit.append(('dn','30日累计-70%'))
        if sum(1 for j in ab_up if i-j<10)>=need: hit.append(('up',f'10日内{need}次同向异常波动'))
        if sum(1 for j in ab_dn if i-j<10)>=need: hit.append(('dn',f'10日内{need}次同向异常波动'))
        for dr in ('up','dn'):
            hs=[h for x,h in hit if x==dr]
            if hs and i-cool[dr]>=10:
                cool[dr]=i
                ev.append({'code':c,'board':d.board[0],'date':d.date[i],'dir':dr,'rule':'/'.join(hs),'c10':d.c10[i],'c30':d.c30[i],'idx':i,'close':d.close[i]})
E=pd.DataFrame(ev)
# 触发后的走势: 下一交易日是否停牌(日历间隔), 复牌日开盘/收盘, 之后 5/10 日
A2={c:d.reset_index(drop=True) for c,d in A.groupby('code')}
rows=[]
for _,e in E.iterrows():
    d=A2[e.code]; i=e.idx
    r=e.to_dict()
    if i+1<len(d):
        gap=np.busday_count(d.date[i].date(),d.date[i+1].date())
        r['停牌交易日约']=max(0,int(gap)-1); r['复牌日']=d.date[i+1]
        base=d.adj_close[i]
        r['复牌日开盘']=d.open[i+1]*d.adjf[i+1]/base-1; r['复牌日收盘']=d.adj_close[i+1]/base-1
        for h in (3,5,10,20):
            r[f'后{h}日']=d.adj_close[i+h]/base-1 if i+h<len(d) else np.nan
    rows.append(r)
R=pd.DataFrame(rows).drop(columns=['idx'])
names={}
import glob
for f in glob.glob('../2026-10-09-theme/ths/*.json'):
    for x in json.load(open(f)): names[x['code']]=x['name']
R['name']=R.code.map(names)
R=R.sort_values('date').reset_index(drop=True); R.to_pickle('events.pkl'); R.to_csv('events.csv',index=False)
print('事件',len(R),'上涨方向',(R.dir=='up').sum(),'下跌方向',(R.dir=='dn').sum(),'区间',R.date.min().date(),R.date.max().date())
print(R.groupby('dir').rule.value_counts())

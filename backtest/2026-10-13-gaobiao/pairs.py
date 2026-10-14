#!/opt/homebrew/bin/python3.13
"""高标二选一回测(2026-07-01 起). 样本: 同一天、同一连板高度(连续N天N板, N>=4)有 2 只及以上的组.
每只股票在 T 日收盘后(含 T+1 开盘前披露的公告)可得的特征, 比较组内谁 T+1 更强.
结局: T+1 是否晋级(再涨停), T+1 收盘涨跌, T+1 开盘买 T+2 收盘卖."""
import json,glob,re,os,sys,itertools,pandas as pd,numpy as np
sys.path.insert(0,'../2026-10-09-theme')
import contextlib,io
with contextlib.redirect_stdout(io.StringIO()):
    _c=os.getcwd(); os.chdir('../2026-10-09-theme'); from theme import themes; os.chdir(_c)
rows=[]
for f in sorted(glob.glob('../2026-10-09-theme/ths/2026*.json')):
    d=f.split('/')[-1][:8]
    if d<'20260620': continue
    for r in json.load(open(f)):
        v=int(r.get('high_days_value') or 65537)
        rows.append(dict(date=pd.Timestamp(d),code=r['code'],name=r['name'],lb=v>>16,days=v&0xFFFF,open_num=int(r.get('open_num') or 0),
            cap=float(r.get('currency_value') or 0)/1e8,turn=float(r.get('turnover_rate') or 0),
            seal=float(r.get('order_amount') or 0)/1e8,first=int(r.get('first_limit_up_time') or 0),
            reason=r.get('reason_type') or '',ths=sorted(themes(r.get('reason_type')))))
Z=pd.DataFrame(rows); cal=sorted(Z.date.unique()); nxt={cal[i]:cal[i+1] for i in range(len(cal)-1)}
tc=Z.explode('ths').groupby(['date','ths']).code.nunique()
def theme_n(d,ts,lag=0):
    i=cal.index(d)-lag
    return max([tc.get((cal[i],t),0) for t in ts] or [0])
Z['题材涨停数']=[theme_n(d,ts) for d,ts in zip(Z.date,Z.ths)]
Z['题材涨停数_前日']=[theme_n(d,ts,1) if cal.index(d)>0 else np.nan for d,ts in zip(Z.date,Z.ths)]
Z['题材在退潮']=Z['题材涨停数']<Z['题材涨停数_前日']
Z['概念数']=Z.reason.str.count(r'\+')+1
Z['封首时']=pd.to_datetime(Z['first'],unit='s',utc=True).dt.tz_convert('Asia/Shanghai').dt.strftime('%H%M').astype(int)
Z['封单占流通']=Z.seal/Z.cap
ztset={(d,c):lb for d,c,lb in zip(Z.date,Z.code,Z.lb)}
H=Z[(Z.date>=pd.Timestamp('2026-07-01'))&(Z.lb>=4)&(Z.lb==Z.days)].copy()
# 否认概念公告: 去掉'亦未涉及市场热点概念'这类每份异动公告都有的套话, 只留点名否认/未形成收入
A=json.load(open('ann_cache/anns.json'))
BOIL=re.compile('热点概念|新技术、新产业|关联|往来|冻结|回款|重组|收购|评估|审计|定价|商誉|固定资产|以前年度|生产过程|结算')
DENY=re.compile('未涉及|不涉及|没有涉及|尚未涉及|未开展|不开展|未从事|尚未形成.{0,8}收入|未产生.{0,8}收入|未形成.{0,10}(订单|收入)|占比极低|与.{0,12}热点.{0,4}无关')
K=re.compile('异常波动|风险提示|澄清|问询|关注函|严重异常')
deny_dates={}
for code,v in A.items():
    s=set()
    for a in v['anns']:
        if not K.search(a['t']): continue
        p='ann_cache/pdf/'+a['u'].split('/')[-1].replace('.PDF','.txt')
        if not os.path.exists(p): continue
        t=re.sub(r'\s+','',open(p,errors='ignore').read())
        for sent in re.split('[。；]',t):
            if DENY.search(sent) and not BOIL.search(sent): s.add((a['d'],sent[:90])); break
    deny_dates[code]=s
def deny_flag(d,c):
    i=cal.index(d); lo=cal[max(0,i-5)].strftime('%Y-%m-%d'); hi=nxt.get(d,d).strftime('%Y-%m-%d')
    hits=[x for x in deny_dates.get(c,()) if lo<=x[0]<=hi]
    return hits
H['否认公告']=[deny_flag(d,c) for d,c in zip(H.date,H.code)]
H['有否认']=H['否认公告'].str.len()>0
# 结局
P=pd.read_parquet('../../data/cn_hk_price_db/a_daily.parquet',columns=['date','ticker','open','close','adj_close'],filters=[('date','>=',pd.Timestamp('2026-06-25'))])
P['code']=P.ticker.str[:6]; P['f']=P.adj_close/P.close; P=P.sort_values(['code','date']); g=P.groupby('code')
P['c1']=g.adj_close.shift(-1); P['c2']=g.adj_close.shift(-2); P['o1']=g.open.shift(-1)*g.f.shift(-1)
P=P.set_index(['date','code'])
def R(d,c,a,b):
    try: x=P.loc[(d,c)]; return x[a]/x[b]-1
    except KeyError: return np.nan
H['次日涨跌']=[R(d,c,'c1','adj_close') for d,c in zip(H.date,H.code)]
H['次日开买_后日收卖']=[R(d,c,'c2','o1') for d,c in zip(H.date,H.code)]
H['次日晋级']=[(nxt[d],c) in ztset if d in nxt else np.nan for d,c in zip(H.date,H.code)]
H.to_pickle('H.pkl')
G=H.groupby(['date','lb']).filter(lambda x:len(x)>=2)
G=G.assign(当日最高=G.lb==G.date.map(H.groupby('date').lb.max()))
print('同高度组',G.groupby(['date','lb']).ngroups,'只次',len(G),'其中当日最高标组',G[G.当日最高].groupby(['date','lb']).ngroups)
G.to_pickle('G.pkl')
FEAT={'流通市值大':('cap',1),'当日炸板少':('open_num',-1),'封板早':('封首时',-1),'封单占流通高':('封单占流通',1),'换手低':('turn',-1),
      '题材涨停多':('题材涨停数',1),'题材未退潮':('题材在退潮',-1),'概念数多':('概念数',1),'无否认公告':('有否认',-1)}
out=[]
for name,(col,sgn) in FEAT.items():
    for half,sub in (('全部',G),('7-8月',G[G.date<pd.Timestamp('2026-09-01')]),('9-10月',G[G.date>=pd.Timestamp('2026-09-01')])):
        w=n=0; wr=nr=0; dif=[]
        for _,grp in sub.groupby(['date','lb']):
            for (_,a),(_,b) in itertools.combinations(grp.iterrows(),2):
                if pd.isna(a[col]) or pd.isna(b[col]) or a[col]==b[col]: continue
                hi,lo=(a,b) if (a[col]-b[col])*sgn>0 else (b,a)
                if pd.notna(hi['次日涨跌']) and pd.notna(lo['次日涨跌']):
                    n+=1; w+=hi['次日涨跌']>lo['次日涨跌']; dif.append(hi['次日涨跌']-lo['次日涨跌'])
                if pd.notna(hi['次日晋级']) and pd.notna(lo['次日晋级']) and hi['次日晋级']!=lo['次日晋级']:
                    nr+=1; wr+=bool(hi['次日晋级'])
        out.append(dict(特征=name,样本段=half,对数=n,占优方次日更强=f'{w}/{n}' if n else '',胜率=round(w/n,2) if n else np.nan,
                        平均次日差=round(np.mean(dif)*100,1) if dif else np.nan,晋级分化对数=nr,占优方晋级=f'{wr}/{nr}' if nr else ''))
O=pd.DataFrame(out); O.to_csv('pair_result.csv',index=False,encoding='utf-8-sig'); print(O.to_string(index=False))

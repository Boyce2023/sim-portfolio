"""2026-07 起所有五板事件(价格口径纯连续涨停第5板), 五板后第二天(T+1)与第三天(T+2)的开盘/盘中/收盘全情形.
按 Buwen 口径: 五板当天=第一天, 第二天=T+1, 第三天=T+2.
数据: 腾讯日K, 不复权判涨跌停价, 前复权算收益; 不含 2026-10-19 盘中.
候选池: 同花顺涨停池 2026-06-20 起出现过 5 板及以上的票."""
import json,glob,urllib.request,time
import pandas as pd, numpy as np
cand={}
for f in sorted(glob.glob('../2026-10-09-theme/ths/2026*.json')):
    d=f.split('/')[-1][:8]
    if d<'20260620': continue
    for r in json.load(open(f)):
        hv=int(r.get('high_days_value') or 65537)
        if hv>>16>=5: cand[r['code']]=r.get('name')
print('候选',len(cand))
def mk(c): return ('sh' if c[0] in '69' else 'sz')+c
import re
SINA_H={'Referer':'https://finance.sina.com.cn','User-Agent':'Mozilla/5.0'}
def kl(c,fq=None):
    """2026-10-19: 腾讯日K 被 WAF 拦(501), 改新浪不复权日K; 区间短, 除权影响忽略(下方校验前收)"""
    q=mk(c)
    u=f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20x=/CN_MarketDataService.getKLineData?symbol={q}&scale=240&ma=no&datalen=130"
    raw=urllib.request.urlopen(urllib.request.Request(u,headers=SINA_H),timeout=10).read().decode()
    m=re.search(r"x=\((\[.*\])\)",raw,re.S); B=json.loads(m.group(1)) if m else []
    df=pd.DataFrame([{'date':b['day'],'open':float(b['open']),'close':float(b['close']),'high':float(b['high']),'low':float(b['low']),'vol':float(b['volume'])} for b in B])
    return df
ev=[]
for c,nm in cand.items():
    try: raw=kl(c); time.sleep(0.3); adj=raw.copy()
    except Exception as e: print('取数失败',c,e); continue
    raw=raw[raw.date<'2026-10-19'].reset_index(drop=True); adj=raw.copy()
    if adj.close.isna().any(): print('复权对不上',c); continue
    lim=0.2 if c[:3] in ('300','301','688','689') else 0.1
    raw['pc']=raw.close.shift(1); raw['zt']=(raw.pc*(1+lim)).round(2); raw['dt']=(raw.pc*(1-lim)).round(2)
    raw['isz']=raw.close>=raw.zt-0.0001
    s=raw.isz.astype(int); grp=(s!=s.shift()).cumsum(); raw['streak']=s.groupby(grp).cumsum()*s
    f=adj.close/raw.close   # 前复权因子
    for i in raw.index[(raw.streak==5)&(raw.date>='2026-07-01')]:
        r={'code':c,'name':nm,'d5':raw.date[i],'c5':raw.close[i]}
        for k,lab in ((1,'d2'),(2,'d3')):
            j=i+k
            if j>=len(raw): continue
            pc,zt,dt=raw.close[j-1],raw.zt[j],raw.dt[j]
            o,h,l,cl=raw.open[j],raw.high[j],raw.low[j],raw.close[j]
            r[f'{lab}_date']=raw.date[j]
            r[f'{lab}_gap']=o/pc-1; r[f'{lab}_chg']=cl/pc-1; r[f'{lab}_hi']=h/pc-1; r[f'{lab}_lo']=l/pc-1
            r[f'{lab}_open_zt']=o>=zt-0.0001; r[f'{lab}_open_dt']=o<=dt+0.0001
            r[f'{lab}_yizi_zt']=l>=zt-0.0001; r[f'{lab}_yizi_dt']=h<=dt+0.0001
            r[f'{lab}_touch_zt']=h>=zt-0.0001; r[f'{lab}_touch_dt']=l<=dt+0.0001
            r[f'{lab}_close_zt']=cl>=zt-0.0001; r[f'{lab}_close_dt']=cl<=dt+0.0001
            # 收益(前复权): 各买点 -> 各卖点
            A=lambda jj,col: adj[col][jj] if jj<len(adj) else np.nan
            buy={'开盘':A(j,'open'),'收盘':A(j,'close'),'涨停价':zt*f[j] if h>=zt-0.0001 and not l>=zt-0.0001 else np.nan,
                 '跌停价':dt*f[j] if l<=dt+0.0001 else np.nan}
            if l>=zt-0.0001: buy['开盘']=np.nan   # 一字涨停买不到
            sell={'当日收':A(j,'close'),'次日开':A(j+1,'open'),'次日收':A(j+1,'close'),'第3日收':A(j+2,'close')}
            for bk,bv in buy.items():
                for sk,sv in sell.items():
                    if bk=='收盘' and sk=='当日收': continue
                    r[f'{lab}_{bk}买_{sk}']=sv/bv-1 if bv==bv and sv==sv else np.nan
            r[f'{lab}_next_zt']=bool(raw.isz[j+1]) if j+1<len(raw) else np.nan
        ev.append(r)
E=pd.DataFrame(ev).sort_values('d5').reset_index(drop=True)
E.to_pickle('events.pkl'); print('五板事件',len(E),'有第二天',E.d2_date.notna().sum(),'有第三天',E.d3_date.notna().sum(),'区间',E.d5.min(),E.d5.max())

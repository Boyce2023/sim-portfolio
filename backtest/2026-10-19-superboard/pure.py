"""超级连板(按价格判定的纯连续涨停, 中间不许断) 6 板及以上, 2026-06-01 起.
10-19 更正: 上一版用同花顺 high_days_value, 那是"N天M板"口径(冰轮环境 11天6板, 实际最长纯连板只有3板), 不是连板.
数据: 新浪不复权日K(腾讯日K当日被拦); 涨跌幅: 300/301/688/689 为20%, ST 2026-07-06 前5%之后10%, 其余10%; 不含 10-19 盘中."""
import json,glob,urllib.request,re,time
import pandas as pd, numpy as np
cand={}; reason={}
for f in sorted(glob.glob('../2026-10-09-theme/ths/2026*.json')):
    d=f.split('/')[-1][:8]
    if d<'20260525': continue
    for r in json.load(open(f)):
        if int(r.get('high_days_value') or 65537)>>16>=4:
            cand[r['code']]=r.get('name') or ''
        reason[(r['code'],d)]=r.get('reason_type') or ''
print('候选(同花顺曾到4板以上)',len(cand))
H={'Referer':'https://finance.sina.com.cn','User-Agent':'Mozilla/5.0'}
def mk(c): return ('sh' if c[0] in '69' else 'sz')+c
def kl(c):
    u=f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20x=/CN_MarketDataService.getKLineData?symbol={mk(c)}&scale=240&ma=no&datalen=115"
    raw=urllib.request.urlopen(urllib.request.Request(u,headers=H),timeout=10).read().decode()
    m=re.search(r"x=\((\[.*\])\)",raw,re.S); B=json.loads(m.group(1)) if m else []
    return pd.DataFrame([{'date':b['day'],'open':float(b['open']),'close':float(b['close']),'high':float(b['high']),'low':float(b['low'])} for b in B])
MA=re.compile('收购|重组|控制权|股权转让|拟变更|复牌|资产注入|并购|借壳')
out=[]; MAXS={}
for c,nm in cand.items():
    try: df=kl(c); time.sleep(0.3)
    except Exception as e: print('取数失败',c,e); continue
    df=df[df.date<'2026-10-19'].reset_index(drop=True)
    st='ST' in nm
    lim=np.where(c[:3] in ('300','301','688','689'),0.2,np.where(st&(df.date<'2026-07-06'),0.05,0.1))
    df['pc']=df.close.shift(1); df['zt']=(df.pc*(1+lim)).round(2); df['dt']=(df.pc*(1-lim)).round(2)
    # 除权日新浪不复权前收偏高, 涨停价算高了: 收在最高价且涨幅离涨停不到0.3个百分点也算涨停(兴业科技06-29 +9.97%)
    chg=df.close/df.pc-1
    df['isz']=(df.close>=df.zt-0.0001)|((df.close>=df.high-0.0001)&(chg>=lim-0.003))
    MAXS[c]=None
    s=df.isz.astype(int); grp=(s!=s.shift()).cumsum(); df['streak']=s.groupby(grp).cumsum()*s
    MAXS[c]=int(df.streak[df.date>='2026-06-01'].max())
    for i in df.index:
        if df.streak[i]<6 or (i+1<len(df) and df.isz[i+1]): continue   # 只取每轮最后一板
        if df.date[i]<'2026-06-01': continue
        n=int(df.streak[i]); s0=i-n+1
        rs=reason.get((c,df.date[i].replace('-','')),'')
        r={'name':nm,'code':c,'boards':n,'start':df.date[s0],'end':df.date[i],'base':df.close[s0-1] if s0>=1 else np.nan,'peak':df.close[i],
           'reason':rs,'ma':bool(MA.search(rs))}
        r['run']=(r['peak']/r['base']-1) if r['base']==r['base'] else np.nan
        D=i+1
        if D<len(df):
            pc=df.close[i]
            r.update(bd=df.date[D],bd_open=df.open[D]/pc-1,bd_high=df.high[D]/pc-1,bd_low=df.low[D]/pc-1,bd_close=df.close[D]/pc-1,
                     touch_zt=df.high[D]>=df.zt[D]-0.0001,touch_dt=df.low[D]<=df.dt[D]+0.0001,close_dt=df.close[D]<=df.dt[D]+0.0001,
                     yizi_dt=df.high[D]<=df.dt[D]+0.0001)
            for h in (1,3,5,10): r[f'r{h}']=df.close[D+h]/df.close[D]-1 if D+h<len(df) else np.nan
            r['o3']=df.close[D+3]/df.open[D]-1 if D+3<len(df) else np.nan
            r['more']=int(df.isz[D+1:D+11].sum())
        out.append(r)
R=pd.DataFrame(out).sort_values(['boards','end'],ascending=[False,True]).reset_index(drop=True)
pd.Series(MAXS).to_csv('max_pure_streak.csv'); R.to_pickle('pure.pkl'); R.to_csv('pure.csv',index=False)
print('纯连板6板以上(每轮一条)',len(R))

"""6月以来最高 6 板及以上的个股: 连板结束后第一个非涨停日(断板日)当天表现与之后走势.
连板口径: 同花顺涨停池 high_days_value(高16位板数, 低16位天数), 峰值日=本轮最高板那天. 价格: 腾讯前复权日K."""
import json,glob,urllib.request,collections,re,time
import pandas as pd
rows=collections.defaultdict(list)
for f in sorted(glob.glob('../2026-10-09-theme/ths/2026*.json')):
    d=f.split('/')[-1][:8]
    if d<'20260520': continue
    for r in json.load(open(f)):
        hv=int(r.get('high_days_value') or 65537)
        rows[r['code']].append((d,hv>>16,hv&0xFFFF,r.get('name'),r.get('reason_type') or ''))
MA=re.compile('收购|重组|控制权|股权转让|拟变更|复牌|资产注入|并购|借壳')
def mk(c): return ('sh' if c[0]=='6' else 'sz')+c
out=[]
for c,L in rows.items():
    pk=max(L,key=lambda x:(x[1],x[0]))
    if pk[1]<6 or pk[0]<'20260601': continue
    try:
        k=json.loads(urllib.request.urlopen(f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={mk(c)},day,2026-05-01,2026-10-19,200,qfq',timeout=10).read())['data'][mk(c)]
    except Exception as e:
        print('取数失败',c,e); continue
    B=k.get('qfqday') or k.get('day'); time.sleep(0.15)
    df=pd.DataFrame([b[:6] for b in B],columns=['date','open','close','high','low','vol'])
    for x in ['open','close','high','low']: df[x]=df[x].astype(float)
    df['date']=df.date.str.replace('-','')
    df=df[df.date<'20261019'].reset_index(drop=True)   # 当天盘中这根不算
    df['pc']=df.close.shift(1)
    lim=0.2 if c[:3] in ('300','301','688','689') else 0.1
    df['ztp']=(df.pc*(1+lim)).round(2); df['dtp']=(df.pc*(1-lim)).round(2)
    df['zt']=df.close>=df.ztp-0.011
    if pk[0] not in set(df.date): print('峰值日不在K线',c); continue
    i=int(df.index[df.date==pk[0]][0]); s=i-pk[2]+1
    while i+1<len(df) and df.zt[i+1]: i+=1   # 同花顺涨停池个别日缺票(兴业科技06-29), 按价格把连板走完
    mid=[(df.date[j],round((df.close[j]/df.pc[j]-1)*100,1)) for j in range(s,i+1) if not df.zt[j]]
    r={'code':c,'name':pk[3],'boards':pk[1],'days':pk[2],'peak':pk[0],'ma':bool(MA.search(pk[4])),'reason':pk[4],'mid_breaks':mid,'run':round((df.close[i]/df.close[s-1]-1)*100) if s>=1 else None}
    if i+1<len(df):
        D=i+1; pc=df.close[i]
        r.update(bd=df.date[D],bd_open=round((df.open[D]/pc-1)*100,1),bd_high=round((df.high[D]/pc-1)*100,1),bd_low=round((df.low[D]/pc-1)*100,1),bd_close=round((df.close[D]/pc-1)*100,1),
                 bd_touch_zt=bool(df.high[D]>=df.ztp[D]-0.011),bd_touch_dt=bool(df.low[D]<=df.dtp[D]+0.011),bd_close_dt=bool(df.close[D]<=df.dtp[D]+0.011))
        for n in (1,3,5,10):
            r[f'r{n}']=round((df.close[D+n]/df.close[D]-1)*100,1) if D+n<len(df) else None
        w=df.iloc[D+1:D+11]
        r['mdd10']=round((w.low.min()/df.close[D]-1)*100,1) if len(w) else None
        r['mx10']=round((w.high.max()/df.close[D]-1)*100,1) if len(w) else None
        r['newhigh']=bool(len(w) and w.high.max()>df.high[:D+1].max())
    out.append(r)
R=pd.DataFrame(out).sort_values(['boards','peak'],ascending=[False,True])
R.to_pickle('breakday.pkl'); R.to_csv('breakday.csv',index=False)
print(len(R),'只; 已出断板日',R.bd.notna().sum())

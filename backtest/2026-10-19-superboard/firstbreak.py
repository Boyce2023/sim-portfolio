"""口径二: 纯连续涨停 >=6 板之后的第一个非涨停日(不管之后会不会再板), 避免只看最终断板的后视偏差."""
import json,glob,urllib.request,collections,time
import pandas as pd
R=pd.read_pickle('breakday.pkl')
def mk(c): return ('sh' if c[0]=='6' else 'sz')+c
out=[]
for _,x in R.iterrows():
    c=x.code
    k=json.loads(urllib.request.urlopen(f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={mk(c)},day,2026-05-01,2026-10-19,200,qfq',timeout=10).read())['data'][mk(c)]
    B=k.get('qfqday') or k.get('day'); time.sleep(0.15)
    df=pd.DataFrame([b[:6] for b in B],columns=['date','open','close','high','low','vol'])
    for col in ['open','close','high','low']: df[col]=df[col].astype(float)
    df['date']=df.date.str.replace('-',''); df=df[df.date<'20261019'].reset_index(drop=True)
    df['pc']=df.close.shift(1); lim=0.2 if c[:3] in ('300','301','688','689') else 0.1
    df['zt']=df.close>=(df.pc*(1+lim)).round(2)-0.011; df['dtp']=(df.pc*(1-lim)).round(2)
    i=int(df.index[df.date==x.peak][0]); s=i-x.days+1
    F=s
    while F<len(df) and df.zt[F]: F+=1
    n=F-s
    if n<6 or F>=len(df): continue
    pc=df.close[F-1]
    r={'name':x['name'],'code':c,'pure':n,'final':x.boards,'F':df.date[F],'F_open':round((df.open[F]/pc-1)*100,1),'F_close':round((df.close[F]/pc-1)*100,1),
       'F_touch_dt':bool(df.low[F]<=df.dtp[F]+0.011),'F_close_dt':bool(df.close[F]<=df.dtp[F]+0.011),'ma':x.ma,
       'more_boards':int(df.zt[F+1:F+11].sum())}
    for h in (1,3,5,10): r[f'r{h}']=round((df.close[F+h]/df.close[F]-1)*100,1) if F+h<len(df) else None
    out.append(r)
Q=pd.DataFrame(out).sort_values('pure',ascending=False); Q.to_csv('firstbreak.csv',index=False)
pd.set_option('display.width',250); print(Q.to_string(index=False))
def s(x,lab):
    print(f"\n{lab} n={len(x)}: 当日开盘中位{x.F_open.median():+.1f}% 收盘中位{x.F_close.median():+.1f}% 收红{(x.F_close>0).mean()*100:.0f}% 触跌停{x.F_touch_dt.mean()*100:.0f}% 收跌停{x.F_close_dt.mean()*100:.0f}% | 之后10日还有涨停{(x.more_boards>0).mean()*100:.0f}%")
    for h in (1,3,5,10):
        v=x[f'r{h}'].dropna(); print(f"   当日收盘买持{h}日 n{len(v)} 均{v.mean():+.1f}% 中位{v.median():+.1f}% 胜率{(v>0).mean()*100:.0f}%")
s(Q,'纯连板>=6后首个非板日'); s(Q[Q.F_close>0],'  其中当日收红'); s(Q[Q.F_close<=0],'  其中当日收绿')

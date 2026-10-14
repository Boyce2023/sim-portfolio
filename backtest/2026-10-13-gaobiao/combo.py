#!/opt/homebrew/bin/python3.13
"""市值最大与换手最低: 两者一致/不一致时各自表现; 超额中位数; 逐组明细"""
import pandas as pd,numpy as np,runpy,io,contextlib
with contextlib.redirect_stdout(io.StringIO()): ns=runpy.run_path('fill.py')
Z=ns['Z']
H=Z[(Z.date>=pd.Timestamp('2026-07-01'))&(Z.lb>=3)&(Z.lb==Z.days)&Z.次日涨跌.notna()]
rec=[]
for (d,lb),x in H.groupby(['date','lb']):
    x=x[x.可买&x.开买后日收.notna()]
    if len(x)<2: continue
    a=x.cap.idxmax(); b=x.turn.idxmin()
    rec.append(dict(date=d.date(),lb=lb,n=len(x),名单='/'.join(f"{r['name']}({r.cap:.0f}亿,换{r.turn:.0f}%,{r.开买后日收*100:+.1f})" for _,r in x.iterrows()),
        大=x.loc[a,'name'],低换=x.loc[b,'name'],一致=a==b,大超额=x.loc[a,'开买后日收']-x.drop(a).开买后日收.mean(),低换超额=x.loc[b,'开买后日收']-x.drop(b).开买后日收.mean()))
R=pd.DataFrame(rec); pd.set_option('display.width',300); pd.set_option('display.max_colwidth',120)
print(R.assign(大超额=(R.大超额*100).round(1),低换超额=(R.低换超额*100).round(1)).to_string(index=False))
for k,s in (('一致',R[R.一致]),('不一致',R[~R.一致])):
    print(k,len(s),'市值大跑赢',(s.大超额>0).sum(),'均%.1f 中位%.1f'%(s.大超额.mean()*100,s.大超额.median()*100),'| 换手低跑赢',(s.低换超额>0).sum(),'均%.1f 中位%.1f'%(s.低换超额.mean()*100,s.低换超额.median()*100))
print('市值大 超额中位数 %.1f%%'%(R.大超额.median()*100), '| 去掉最大一组后均值 %.1f%%'%(R.大超额.sort_values().iloc[:-1].mean()*100))
R.to_csv('pairs_detail.csv',index=False,encoding='utf-8-sig')

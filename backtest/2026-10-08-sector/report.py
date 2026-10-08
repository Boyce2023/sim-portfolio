#!/opt/homebrew/bin/python3.13
import pandas as pd, numpy as np
D=pd.read_parquet('signals.parquet')
PER={'P1 2025-01至2026-03':('2025-01-01','2026-03-31'),'P2 2026-07至今':('2026-07-01','2026-09-30')}
def stat(x):
    x=x.dropna()
    if len(x)<3: return f'n={len(x)}'
    w=x[x>0]; l=x[x<=0]
    pr=w.mean()/abs(l.mean()) if len(l) and len(w) else np.nan
    return f'n={len(x)} 胜率{(x>0).mean()*100:.0f}% 均值{x.mean()*100:+.2f}% 中位{x.median()*100:+.2f}% 赔率{pr:.2f}'
for pk,(a,b) in PER.items():
    print('='*20,pk)
    for lab,d in D[(D.date>=a)&(D.date<=b)].groupby('label',sort=False):
        print('--',lab,'信号数',len(d))
        for h in (5,10,20):
            r=d[f'rank{h}'].dropna()
            if len(r)==0: continue
            print(f'   未来{h}日累计强势数: 第一(主线) {(r==1).mean()*100:.0f}%  前二 {(r<=2).mean()*100:.0f}%  前五 {(r<=5).mean()*100:.0f}%  (有完整窗口 {len(r)})')
        if 'top2days10' in d and d.top2days10.notna().any(): print(f'   未来10日里仍居前二的天数 均值{d.top2days10.mean():.1f}  中位{d.top2days10.median():.0f}')
        for h in (5,10,20):
            print(f'   板块等权 T+1开盘买 持{h}日 超额: {stat(d[f"ex{h}"])}')
            if 'lead'+str(h) in d and d[f'lead{h}'].notna().any(): print(f'   当日涨停股(次日能买进) 持{h}日 超额: {stat(d[f"lead{h}"])}')

#!/opt/homebrew/bin/python3.13
"""2026年以来连续涨停>=6板的股票(不论原因): 开板当天买(开盘若已低于涨停价按开盘价, 否则按涨停价在开板时买) / 开板次日开盘买"""
import pandas as pd,numpy as np
from common import panel
A=panel('2025-11-01'); A=A[A.nth>=5]
rows=[]
for c,s in A.groupby('code'):
    s=s.reset_index(drop=True); i=0
    while i<len(s):
        if s.streak[i]>=1 and (i+1>=len(s) or s.streak[i+1]==0):
            k=int(s.streak[i]); end=i
            if k>=6 and s.date[end]>=pd.Timestamp('2026-01-01') and end+1<len(s):
                d=s.iloc[end+1]
                pa=min(d.open,d.zt_px)*d.adjf
                r={'code':c,'连板':k,'最后涨停日':s.date[end].date(),'开板日':d.date.date(),'开板日涨跌':d.close/d.prevc-1}
                for h in (0,1,3,5,10):
                    j=end+1+h; r[f'开板当天买_持{h}日']=s.close[j]*s.adjf[j]/pa-1 if j<len(s) else np.nan
                if end+2<len(s):
                    pb=s.open[end+2]*s.adjf[end+2]
                    for h in (0,1,3,5,10):
                        j=end+2+h; r[f'次日开盘买_持{h}日']=s.close[j]*s.adjf[j]/pb-1 if j<len(s) else np.nan
                rows.append(r)
        i+=1
R=pd.DataFrame(rows)
import sys; sys.path.insert(0,'../../scripts')
import astock_data_layer as Q
nm=Q.get_batch_prices(R.code.tolist()); R['name']=R.code.map(lambda c:(nm.get(c) or {}).get('name'))
pd.set_option('display.width',260)
print(R[['name','连板','最后涨停日','开板日','开板日涨跌','开板当天买_持1日','开板当天买_持5日','开板当天买_持10日','次日开盘买_持1日','次日开盘买_持5日','次日开盘买_持10日']].round(3).sort_values('开板日').to_string(index=False))
print()
for c in [c for c in R.columns if '买_持' in c]:
    v=R[c].dropna()
    if len(v): print(f'{c}: n={len(v)} 胜率{(v>0).mean()*100:.0f}% 均值{v.mean()*100:+.1f}% 中位{v.median()*100:+.1f}%')
R.to_csv('bigstreak_2026.csv',index=False,encoding='utf-8-sig')

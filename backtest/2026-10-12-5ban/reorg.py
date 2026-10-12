#!/opt/homebrew/bin/python3.13
"""2026年重组/重大事项复牌后连续涨停(>=3板)的股票: 开板当天买 / 开板次日开盘买, 各持有期收益"""
import json,pandas as pd,numpy as np
from common import panel
A=panel('2025-12-01')
ann=pd.DataFrame(json.load(open('../2026-10-08-sector/resume_ann.json')))
ann=ann[ann.title.str.contains('复牌')&ann.title.str.contains('购买资产|重组|收购|吸收合并|控制权|发行股份')&~ann.title.str.contains('终止|取消')]
ann['time']=pd.to_datetime(ann.time); ann=ann[ann.time>='2026-01-01'].sort_values('time').drop_duplicates('code')
rows=[]
for _,e in ann.iterrows():
    s=A[A.code==e.code].reset_index(drop=True)
    s=s[s.date>=e.time-pd.Timedelta(days=3)].reset_index(drop=True)
    if len(s)<3: continue
    # 复牌后连续涨停数
    k=0
    while k<len(s) and s.zt[k]: k+=1
    if k<3: continue
    if k>=len(s): continue   # 还没开板
    d=s.iloc[k]   # 开板日(首个非涨停收盘日)
    yizi_all=all((s.open[j]>=s.zt_px[j]-0.011) for j in range(k))
    buyA=min(d.open,d.zt_px) if d.low<d.zt_px-0.011 or d.open<d.zt_px-0.011 else np.nan
    pa=buyA*d.adjf
    r={'code':e.code,'name':e['name'],'复牌公告':e.time.date(),'连板':k,'全一字':yizi_all,'开板日':d.date.date()}
    for h in (0,1,3,5,10):
        j=k+h
        r[f'开板当天买_持{h}日']=(s.close[j]*s.adjf[j]/pa-1) if j<len(s) and not np.isnan(pa) else np.nan
    if k+1<len(s):
        pb=s.open[k+1]*s.adjf[k+1]
        for h in (0,1,3,5,10):
            j=k+1+h
            r[f'次日开盘买_持{h}日']=(s.close[j]*s.adjf[j]/pb-1) if j<len(s) else np.nan
    # 开板前最后涨停价 相对 开板后20日最高
    r['开板后10日最高相对开板收盘']=(s.close[k:k+11]*s.adjf[k:k+11]).max()/(d.close*d.adjf)-1
    rows.append(r)
R=pd.DataFrame(rows); pd.set_option('display.width',260)
print(R[['name','复牌公告','连板','全一字','开板日','开板当天买_持1日','开板当天买_持3日','开板当天买_持5日','开板当天买_持10日','次日开盘买_持1日','次日开盘买_持5日','次日开盘买_持10日']].round(3).to_string(index=False))
print()
for c in [c for c in R.columns if '买_持' in c]:
    v=R[c].dropna()
    if len(v): print(f'{c}: n={len(v)} 胜率{(v>0).mean()*100:.0f}% 均值{v.mean()*100:+.1f}% 中位{v.median()*100:+.1f}%')
R.to_csv('reorg_2026.csv',index=False,encoding='utf-8-sig')

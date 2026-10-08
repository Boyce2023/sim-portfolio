#!/opt/homebrew/bin/python3.13
"""重组预案复牌后的走势: 事件取自巨潮标题含"复牌"且含购买资产/重组/收购的公告; 复牌日=公告后第一个有成交且之前停牌>=3个交易日的日子"""
import pandas as pd, numpy as np, json, re
A=pd.DataFrame(json.load(open('resume_ann.json')))
k=A.title.str.contains('复牌')&A.title.str.contains('购买资产|重组|收购|吸收合并')&~A.title.str.contains('终止|取消|进展')
E=A[k].copy(); E['time']=pd.to_datetime(E.time)
E=E.sort_values('time').drop_duplicates('code')
P=pd.read_parquet('stock_panel.parquet',columns=['code','date','open','high','close','prevc','zt','zt_px','ac','ao','lim','l2n'])
P2=pd.read_parquet('../2026-09-29-wf/feat.parquet',columns=['code','date']).query("date>='2023-06-01'")
days=np.sort(pd.concat([P.date,P2.date]).unique())
rows=[]
for _,e in E.iterrows():
    s=P[P.code==e.code].sort_values('date').reset_index(drop=True)
    s=s[s.date>=e.time-pd.Timedelta(days=3)]
    if s.empty: continue
    i0=s.index[0]; full=P[P.code==e.code].sort_values('date').reset_index(drop=True)
    j=full.index[full.date==s.date.iloc[0]][0]
    if j==0: continue
    gap=((days>full.date[j-1])&(days<full.date[j])).sum()
    if gap<3: continue
    f=full.iloc[j:j+40].reset_index(drop=True)
    if len(f)<10: continue
    pre=full.close[j-1]*1.0
    # 连板数(从复牌日起连续涨停)
    lb=0
    while lb<len(f) and f.zt[lb]: lb+=1
    yizi0=f.open[0]>=f.zt_px[0]-0.011
    # 峰值: 前20个交易日收盘最高
    w=f.iloc[:20]; ac0=full.ac[j-1]
    pk=w.ac.idxmax()
    r={'code':e.code,'name':e['name'],'resume':f.date[0].date(),'行业':f.l2n[0],'停牌日数':gap,'复牌连板':lb,'首日一字':yizi0,
       '峰值日(复牌第几天)':pk+1,'峰值涨幅%':(w.ac.max()/ac0-1)*100,'20日后涨幅%':(f.ac[min(19,len(f)-1)]/ac0-1)*100,'title':e.title}
    # 卖法: 1)断板当日开盘卖 2)断板当日收盘卖 3)断板次日收盘
    if lb<len(f):
        r['断板日开盘卖%']=(f.ao[lb]/ac0-1)*100; r['断板日收盘卖%']=(f.ac[lb]/ac0-1)*100
        if lb+1<len(f): r['断板次日收盘卖%']=(f.ac[lb+1]/ac0-1)*100
        # 断板后再创新高的比例: 断板后20日内收盘超过断板前最后涨停收盘
        last=f.ac[lb-1] if lb>0 else ac0
        r['断板后20日内再创新高']=bool((f.ac[lb:lb+20]>last*1.0001).any())
    rows.append(r)
R=pd.DataFrame(rows).sort_values('resume')
R.to_csv('resume_cases.csv',index=False,encoding='utf-8-sig')
print('事件',len(R)); print(R[['code','name','resume','复牌连板','首日一字','峰值日(复牌第几天)','峰值涨幅%','断板日开盘卖%','断板日收盘卖%','断板次日收盘卖%','20日后涨幅%','断板后20日内再创新高']].round(1).to_string())

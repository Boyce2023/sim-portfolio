"""取第1天(五板次日)高开5%以上个股当天 9:45 的价格(宝硕 5 分钟线, 09:40 到 09:45 那根的收盘)"""
import pandas as pd, numpy as np, baostock as bs, json
src=open('sim.py').read().split("out=[]; keep={}")[0]; ns={}; exec(src,ns)
P=ns['P']; F=ns['F']; series=ns['series']
need=[]
for _,e in F.iterrows():
    d,O,H,Lo,C,ZT,DT=series(e.code); i=int(d.index[d.date==e.d5][0]); b=i+1
    if b>=len(d) or Lo[b]>=ZT[b]*0.998: continue
    if O[b]/C[i]-1>=0.05: need.append((e.code,d.date[b].strftime('%Y-%m-%d'),float(d.close[i])))
lg=bs.login(); out={}
for code,day,c5 in need:
    q=('sh.' if code[0]=='6' else 'sz.')+code
    rs=bs.query_history_k_data_plus(q,'date,time,open,high,low,close',start_date=day,end_date=day,frequency='5',adjustflag='3')
    bars=[]
    while rs.error_code=='0' and rs.next(): bars.append(rs.get_row_data())
    b945=[x for x in bars if x[1][8:12]=='0945']
    out[f'{code}_{day}']={'price_945':float(b945[0][5]) if b945 else None,'c5_raw':c5,'nbars':len(bars),'open':float(bars[0][2]) if bars else None}
bs.logout()
json.dump(out,open('min945.json','w'),ensure_ascii=False,indent=1)
for k,v in out.items(): print(k,v, '9:45相对五板收' , round((v['price_945']/v['c5_raw']-1)*100,1) if v['price_945'] else None)

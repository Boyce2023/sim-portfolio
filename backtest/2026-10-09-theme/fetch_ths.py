#!/opt/homebrew/bin/python3.13
"""同花顺涨停池逐日(含涨停原因 reason_type, 当日标注, 无前视), 接口约保留一年"""
import requests,json,time,os,pandas as pd
F='199112,10,9001,330323,330324,330325,9002,330329,133971,133970,1968584,3475914,9003,9004'
P=pd.read_parquet('../2026-10-08-sector/sector_daily.parquet',columns=['date'])
days=sorted({d.strftime('%Y%m%d') for d in P.date.unique() if d>=pd.Timestamp('2025-09-01')})+['20261008','20261009']
os.makedirs('ths',exist_ok=True); bad=[]
for d in days:
    fp=f'ths/{d}.json'
    if os.path.exists(fp) and d!='20261009': continue
    rows=[]; p=1
    while True:
        u=f'https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool?page={p}&limit=200&field={F}&filter=HS,GEM2STAR&order_field=330324&order_type=0&date={d}'
        try: r=requests.get(u,headers={'User-Agent':'Mozilla/5.0'},timeout=15).json()
        except Exception as e: r={'status_code':-9}
        if r.get('status_code')!=0: bad.append(d); break
        rows+=r['data']['info']; pg=r['data']['page']
        if pg['page']>=pg['count']: break
        p+=1; time.sleep(0.3)
    if rows: json.dump(rows,open(fp,'w'),ensure_ascii=False)
    time.sleep(0.3)
print('done',len(days),'不可用日',len(bad),bad[:5],bad[-3:])

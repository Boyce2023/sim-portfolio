#!/opt/homebrew/bin/python3.13
"""同花顺涨停池逐日(含涨停原因 reason_type, 当日标注, 无前视), 接口约保留一年"""
import requests,json,time,os,pandas as pd
F='199112,10,9001,330323,330324,330325,9002,330329,133971,133970,1968584,3475914,9003,9004'
import datetime as dt
closed=set(json.load(open('../../market_calendar.json'))['trading_days_by_market']['cn_closed_dates'])
days=[d.strftime('%Y%m%d') for d in pd.bdate_range('2025-09-01',dt.date.today()) if d.strftime('%Y-%m-%d') not in closed]
os.makedirs('ths',exist_ok=True); bad=[]
for d in days:
    fp=f'ths/{d}.json'
    if os.path.exists(fp) and d!=dt.date.today().strftime('%Y%m%d'): continue
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

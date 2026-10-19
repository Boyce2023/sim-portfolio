"""财报日: NASDAQ earnings calendar 逐日(2026-08-24 ~ 2026-10-16), 存 earn_cal.json"""
import urllib.request, json, time, datetime as dt
H={"User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36","Accept":"application/json","Accept-Language":"en-US,en;q=0.9"}
d=dt.date(2026,8,24); end=dt.date(2026,10,16); out=[]; bad=[]
while d<=end:
    if d.weekday()<5:
        ok=False
        for a in range(4):
            try:
                j=json.load(urllib.request.urlopen(urllib.request.Request(f"https://api.nasdaq.com/api/calendar/earnings?date={d}",headers=H),timeout=40))
                rows=(j.get('data') or {}).get('rows') or []
                for r in rows: r['_date']=str(d); out.append(r)
                print(d,len(rows),flush=True); ok=True; break
            except Exception as e:
                time.sleep(5*(a+1))
        if not ok: bad.append(str(d))
        time.sleep(0.6)
    d+=dt.timedelta(1)
json.dump(out,open('earn_cal.json','w'))
print('总',len(out),'失败日',bad)

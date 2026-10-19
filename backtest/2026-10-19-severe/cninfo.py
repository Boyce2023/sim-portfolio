"""巨潮资讯全文检索: 近一年标题含"严重异常波动"的公告(权威口径, 公司必须披露). 按月分段防止单次检索上限."""
import json,time,urllib.request,urllib.parse,datetime,re
import pandas as pd
U='http://www.cninfo.com.cn/new/hisAnnouncement/query'
def q(se,page):
    data=urllib.parse.urlencode({'pageNum':page,'pageSize':30,'column':'szse','tabName':'fulltext','searchkey':'严重异常波动','seDate':se,'isHLtitle':'true'}).encode()
    r=urllib.request.Request(U,data=data,headers={'User-Agent':'Mozilla/5.0','Content-Type':'application/x-www-form-urlencoded; charset=UTF-8'})
    return json.loads(urllib.request.urlopen(r,timeout=20).read())
rows=[]; d0=datetime.date(2025,10,1)
while d0<=datetime.date(2026,10,19):
    d1=min((d0.replace(day=28)+datetime.timedelta(days=4)).replace(day=1)-datetime.timedelta(days=1),datetime.date(2026,10,19))
    se=f'{d0}~{d1}'; p=1; tot=None
    while True:
        j=q(se,p); tot=j.get('totalAnnouncement')
        for a in j.get('announcements') or []:
            t=re.sub('<.*?>','',a['announcementTitle'])
            rows.append({'date':datetime.datetime.fromtimestamp(a['announcementTime']/1000).date(),'code':a['secCode'],'name':a['secName'],'title':t,'id':a['announcementId']})
        if p>=(j.get('totalpages') or 1): break
        p+=1; time.sleep(0.4)
    print(se,'条数',tot); time.sleep(0.4)
    d0=d1+datetime.timedelta(days=1)
D=pd.DataFrame(rows).drop_duplicates('id')
D=D[D.title.str.contains('严重异常波动')]
D.to_csv('cninfo_raw.csv',index=False); print('标题含严重异常波动',len(D),'只',D.code.nunique())

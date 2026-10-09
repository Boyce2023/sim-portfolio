#!/opt/homebrew/bin/python3.13
"""本周语料: 巨潮全部公告标题 + 新浪7x24 + 同花顺涨停原因, 2026-09-28 到 2026-10-09"""
import requests,json,time,datetime as dt,glob,sys
H={'User-Agent':'Mozilla/5.0','Referer':'http://www.cninfo.com.cn/'}
out=[]
# 巨潮公告标题: 按天分段(单次检索翻页有上限), 每请求最多重试3次
d0=dt.date(2026,9,28)
while d0<=dt.date(2026,10,9):
    for col in ('szse','sse'):
        p=1
        while p<200:
            r=None
            for k in range(3):
                try: r=requests.post('http://www.cninfo.com.cn/new/hisAnnouncement/query',headers=H,timeout=20,
                      data={'pageNum':p,'pageSize':30,'column':col,'tabName':'fulltext','seDate':f'{d0}~{d0}','isHLtitle':'true'}).json(); break
                except Exception: time.sleep(2)
            if not r: print('fail',d0,col,p,flush=True); break
            A=r.get('announcements') or []
            for x in A: out.append(('公告',x['secCode'],x['secName'],x['announcementTitle'].replace('<em>','').replace('</em>',''),str(d0)))
            if not A or len(A)<30: break
            p+=1; time.sleep(0.2)
    print(d0,len(out),flush=True); d0+=dt.timedelta(days=1)
# 新浪 7x24
stop=dt.datetime(2026,9,28); page=1; n0=len(out)
while page<400:
    try: r=requests.get(f'https://zhibo.sina.com.cn/api/zhibo/feed?page={page}&page_size=100&zhibo_id=152&tag_id=0&dire=f&dpc=1&type=0',headers={'User-Agent':'Mozilla/5.0'},timeout=15).json()
    except Exception: time.sleep(3); page+=1; continue
    L=r['result']['data']['feed']['list']
    if not L: break
    for x in L: out.append(('新浪7x24','','',x['rich_text'],x['create_time'][:10]))
    if dt.datetime.strptime(L[-1]['create_time'],'%Y-%m-%d %H:%M:%S')<stop: break
    page+=1; time.sleep(0.3)
print('sina',len(out)-n0,flush=True)
# 同花顺涨停原因
for f in sorted(glob.glob('../2026-10-09-theme/ths/*.json')):
    d=f.split('/')[-1][:8]
    if d<'20260928': continue
    for x in json.load(open(f)): out.append(('涨停原因',x['code'],x['name'],x.get('reason_type') or '',f'{d[:4]}-{d[4:6]}-{d[6:]}'))
json.dump(out,open('corpus_week.json','w'),ensure_ascii=False); print('total',len(out))

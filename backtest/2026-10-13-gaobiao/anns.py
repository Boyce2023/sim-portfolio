#!/opt/homebrew/bin/python3.13
"""7月以来 >=4 连板(连续N天N板)个股: 拉 cninfo 公告(异常波动/风险提示/澄清/问询/关注函), 下 PDF 抽正文, 标出'否认热点概念'与'强调亏损'两类表述. 缓存到 ann_cache/"""
import json,glob,time,re,os,subprocess,requests,pandas as pd
os.makedirs('ann_cache/pdf',exist_ok=True)
rows=[]
for f in sorted(glob.glob('../2026-10-09-theme/ths/2026*.json')):
    d=f.split('/')[-1][:8]
    if d<'20260701': continue
    for r in json.load(open(f)):
        v=int(r.get('high_days_value') or 65537)
        if v>>16>=4 and v>>16==v&0xFFFF: rows.append((r['code'],r['name']))
S=sorted(set(rows)); print('股票数',len(S))
Hd={'User-Agent':'Mozilla/5.0','Referer':'http://www.cninfo.com.cn/'}
KEY=re.compile('异常波动|风险提示|澄清|问询|关注函|严重异常')
out={}
if os.path.exists('ann_cache/anns.json'): out=json.load(open('ann_cache/anns.json'))
for code,name in S:
    if code in out: continue
    L=[]
    for col in ('sse','szse'):
        for pg in (1,2):
            try:
                r=requests.post('http://www.cninfo.com.cn/new/hisAnnouncement/query',headers=Hd,timeout=20,data={'pageNum':pg,'pageSize':30,'column':col,'tabName':'fulltext','searchkey':name.replace(' ','').replace('*',''),'seDate':'2026-06-01~2026-10-13','isHLtitle':'true'}).json()
            except Exception as e: print('ERR',name,e); continue
            A=r.get('announcements') or []
            for a in A:
                if a['secCode']!=code: continue
                t=re.sub('<.*?>','',a['announcementTitle'])
                L.append(dict(d=time.strftime('%Y-%m-%d',time.localtime(a['announcementTime']/1000)),t=t,u=a['adjunctUrl']))
            time.sleep(0.4)
            if len(A)<30: break
    out[code]=dict(name=name,anns=L); json.dump(out,open('ann_cache/anns.json','w'),ensure_ascii=False)
# 下载相关 PDF
n=0
for code,v in out.items():
    for a in v['anns']:
        if not KEY.search(a['t']): continue
        p='ann_cache/pdf/'+a['u'].split('/')[-1]
        if not os.path.exists(p.replace('.PDF','.txt')):
            try:
                b=requests.get('http://static.cninfo.com.cn/'+a['u'],headers=Hd,timeout=30).content
                open(p,'wb').write(b); subprocess.run(['pdftotext','-layout',p,p.replace('.PDF','.txt')],check=False); os.remove(p); n+=1; time.sleep(0.3)
            except Exception as e: print('PDFERR',a['t'],e)
print('新下载',n)

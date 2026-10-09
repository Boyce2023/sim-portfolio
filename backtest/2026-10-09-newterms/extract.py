#!/opt/homebrew/bin/python3.13
"""候选新词: 本周语料里 jieba 词典里没有的词(含新词发现) + 同花顺涨停原因词; 
新颖性: ①同花顺涨停原因一年历史(09-28前)未出现 ②巨潮公告标题 2016-01-01 到 2026-09-27 全文检索 0 条"""
import json,re,collections,glob,time,requests,jieba,jieba.posseg as pseg
jieba.setLogLevel(60)
C=json.load(open('corpus_week.json'))
STOP=set('公司 股份 有限 公告 关于 董事会 股东 会议 决议 子公司 控股 投资 项目 进展 提示 披露 报告 季度 年度 第三 情况 事项 相关 变更 证券 交易 计划 本次 集团 科技 股票 有限公司 意见 说明 法律 独立 专项 审计 核查 募集 资金 使用 管理 制度 回购 激励 限制性 期权 解除 限售 上市 流通 担保 质押 借款 理财 现金 委托 产品 业绩 预告 快报 收入 利润'.split())
ths_hist=set()
for f in glob.glob('../2026-10-09-theme/ths/*.json'):
    if f.split('/')[-1][:8]>='20260928': continue
    for x in json.load(open(f)):
        for t in (x.get('reason_type') or '').split('+'): ths_hist.add(t.strip())
cand=collections.defaultdict(lambda:{'n':0,'src':set(),'ex':[]})
def add(t,src,ctx):
    c=cand[t]; c['n']+=1; c['src'].add(src)
    if len(c['ex'])<3: c['ex'].append(ctx[:80])
for src,code,name,text,d in C:
    text=re.sub('<[^>]+>','',text or '')
    if src=='涨停原因':
        for t in text.split('+'):
            t=t.strip()
            if t and t not in ths_hist: add(t,f'涨停原因:{name}',f'{d} {name} {text}')
        continue
    for w,flag in pseg.cut(text):
        w=w.strip()
        if len(w)<2 or w in STOP or re.fullmatch(r'[\d\.%年月日亿万元]+',w): continue
        if not re.search(r'[一-龥A-Za-z]',w): continue
        inDict=w in jieba.dt.FREQ
        if (not inDict) or flag in ('eng','nz'):
            add(w,f'{src}:{name}' if name else src,f'{d} {name} {text}')
# 只留出现>=2次或来自>=2个来源的
L=[(t,v) for t,v in cand.items() if (v['n']>=2 or len(v['src'])>=2) and not re.fullmatch(r'[A-Za-z]{1,2}',t)]
print('候选',len(cand),'过滤后',len(L),flush=True)
H={'User-Agent':'Mozilla/5.0','Referer':'http://www.cninfo.com.cn/'}
def hist_hits(t):
    tot=0
    for col in ('szse','sse'):
        for k in range(3):
            try:
                r=requests.post('http://www.cninfo.com.cn/new/hisAnnouncement/query',headers=H,timeout=20,
                  data={'pageNum':1,'pageSize':1,'column':col,'tabName':'fulltext','searchkey':t,'seDate':'2016-01-01~2026-09-27','isHLtitle':'true'}).json()
                tot+=int(r.get('totalAnnouncement') or 0); break
            except Exception: time.sleep(2)
        time.sleep(0.25)
    return tot
res=[]
for i,(t,v) in enumerate(sorted(L,key=lambda x:-x[1]['n'])):
    h=hist_hits(t); res.append({'词':t,'本周次数':v['n'],'来源数':len(v['src']),'2016到0927公告标题命中':h,'同花顺一年涨停原因出现过':t in ths_hist,'例句':' | '.join(v['ex']),'来源':' ; '.join(list(v['src'])[:5])})
    if i%50==0: print(i,len(L),flush=True)
json.dump(res,open('candidates.json','w'),ensure_ascii=False)
new=[r for r in res if r['2016到0927公告标题命中']==0]
print('历史公告标题0命中',len(new))
for r in sorted(new,key=lambda r:-r['本周次数'])[:80]: print(r['词'],r['本周次数'],r['来源数'],'|',r['例句'][:120])

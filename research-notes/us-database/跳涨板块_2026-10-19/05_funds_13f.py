"""47家 long-only/long-bias 基金: 最新一期 13F-HR 对上一期, 新建仓与加仓>=20%(拆股已校正)。
CIK: efts 实体检索 → submissions 里确有 13F-HR 才认。输出 funds_13f.json(逐家) / fund_moves.json(逐笔动作)
⛔拆股校正(旧表 KLAC 一批 +898% 即拆股假加仓): 两期隐含单价比>1.8 且股数比与之相差<25% 视为拆股, 前期股数乘回比例。
"""
import json, re, time, urllib.request, urllib.parse, concurrent.futures as cf
import xml.etree.ElementTree as ET
UA={'User-Agent':'Buwen Deng research buwendeng@gmail.com'}
def get(url,tries=4):
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=90) as r: return r.read()
        except Exception as e:
            err=e; time.sleep(2*(k+1))
    raise err
NAMES=[n for n in json.load(open('fund_names_from_sheet2.json')) if n!='T. Rowe Price Associates']
QUERY={'FMR LLC (Fidelity)':'FMR LLC','Harris Associates (Oakmark)':'Harris Associates','Southeastern Asset Management (Longleaf)':'Southeastern Asset Management',
       'PRICE T ROWE ASSOCIATES INC /MD/':'PRICE T ROWE ASSOCIATES','Janus Henderson':'Janus Henderson Group','Brown Advisory':'Brown Advisory Inc',
       'Markel Corp':'Markel Group','Berkshire Hathaway':'Berkshire Hathaway Inc','Davis Selected Advisers':'Davis Selected Advisers'}
P=['2026-03-31','2026-06-30','2026-09-30']
def resolve(n):
    q=QUERY.get(n,n)
    d=json.loads(get('https://efts.sec.gov/LATEST/search-index?'+urllib.parse.urlencode({'keysTyped':q})))
    for h in d['hits']['hits'][:6]:
        cik=h['_id']
        try: sub=json.loads(get(f'https://data.sec.gov/submissions/CIK{int(cik):010d}.json'))
        except Exception: continue
        rc=sub['filings']['recent']
        f=[(fm,acc,fd,rd) for fm,acc,fd,rd in zip(rc['form'],rc['accessionNumber'],rc['filingDate'],rc['reportDate']) if fm=='13F-HR' and rd>='2026-01-01']
        if f: return cik,sub['name'],f
    return None,None,[]
def parse(xb):
    root=ET.fromstring(xb); ln=lambda e:e.tag.rsplit('}',1)[-1]
    agg={}
    for it in root.iter():
        if ln(it)!='infoTable': continue
        g={ln(c):(c.text or '').strip() for c in it.iter()}
        if g.get('putCall'): continue
        if g.get('sshPrnamtType','SH')!='SH': continue
        cu=g.get('cusip','').upper()
        a=agg.setdefault(cu,{'issuer':g.get('nameOfIssuer',''),'sh':0.0,'val':0.0,'cls':g.get('titleOfClass','')})
        a['sh']+=float(g.get('sshPrnamt') or 0); a['val']+=float(g.get('value') or 0)
    return agg
def holdings(cik,acc):
    base=f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace("-","")}'
    idx=json.loads(get(base+'/index.json'))
    xs=[i['name'] for i in idx['directory']['item'] if i['name'].lower().endswith('.xml') and 'primary' not in i['name'].lower()]
    best=None
    for x in xs:
        try:
            a=parse(get(f'{base}/{x}'))
            if a and (best is None or len(a)>len(best)): best=a
        except Exception: pass
    if not best: raise RuntimeError(f'信息表解析为空 {base}')   # ⛔取不到要报错, 不能静默返回空表(空的上期会把全部持仓算成新建)
    return best
def one(n):
    cik,ename,f=resolve(n)
    if not cik: return dict(name=n,found=False)
    per={}
    for fm,acc,fd,rd in f:
        if rd in P and rd not in per: per[rd]=(acc,fd)
    have=[p for p in P if p in per]
    if len(have)<2: return dict(name=n,cik=cik,edgar=ename,found=True,periods=have,note='不足两期')
    cur,prev=have[-1],have[-2]
    H={p:holdings(cik,per[p][0]) for p in (prev,cur)}
    tot=sum(v['val'] for v in H[cur].values())
    moves=[]
    for cu,v in H[cur].items():
        if v['sh']<=0: continue
        pv=H[prev].get(cu); psh=pv['sh'] if pv else 0.0; split=1
        if psh>0:
            p_now=v['val']/v['sh']; p_prev=pv['val']/psh if psh else 0
            if p_now>0 and p_prev/p_now>1.8:
                r=p_prev/p_now
                if abs((v['sh']/psh)/r-1)<0.25: split=round(r); psh*=split
        kind='新建仓' if psh<=0 else ('加仓' if v['sh']>=psh*1.2 else None)
        moves.append(dict(cusip=cu,issuer=v['issuer'],cls=v['cls'],kind=kind,sh=v['sh'],psh=psh,split=split,
                                    chg=(v['sh']/psh-1) if psh>0 else None,val=v['val'],pval=(pv['val'] if pv else 0.0),w=v['val']/tot if tot else 0))
    prev_only=[dict(cusip=cu,issuer=v['issuer'],cls=v['cls'],sh=v['sh'],val=v['val']) for cu,v in H[prev].items() if cu not in H[cur]]
    return dict(name=n,cik=cik,edgar=ename,found=True,cur=cur,prev=prev,filed=per[cur][1],n_pos=len(H[cur]),aum=tot,moves=moves,prev_only=prev_only)
res=[]
with cf.ThreadPoolExecutor(3) as ex:
    for r in ex.map(one,NAMES):
        res.append(r)
        print(f"{r['name'][:34]:34s} | {str(r.get('edgar'))[:34]:34s} | {r.get('prev')}→{r.get('cur')} 申报{r.get('filed')} | 持仓{r.get('n_pos')} 动作{len(r.get('moves',[]))} {r.get('note','')}",flush=True)
json.dump(res,open('funds_13f_full.json','w'),ensure_ascii=False)
print('完成',sum(1 for r in res if r.get('moves') is not None),'家有两期')

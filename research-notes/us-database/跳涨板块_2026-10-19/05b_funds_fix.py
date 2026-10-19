"""补 7 家: efts 首选实体不对或申报主体变更。显式给 (当期CIK, 上期CIK)。
Janus: 2026Q2 起由 Jupiter Topco LLC(收购主体) 申报; Pershing: 2026Q2 起由 PERSHING SQUARE INC. 申报, 原主体只报 13F-NT; Scion: 2025Q3 后停报。"""
import json
src=open('05_funds_13f.py').read()
exec(src.split('res=[]')[0])
FIX={'Baron Capital':(1017918,1017918),'Greenhaven Road Capital':(1741129,1741129),'ValueAct Capital':(1418814,1418814),
     'Viking Global Investors':(1103804,1103804),'Janus Henderson':(2146052,1274173),'Pershing Square Capital Management':(2026053,1336528)}
def filings(cik):
    sub=json.loads(get(f'https://data.sec.gov/submissions/CIK{int(cik):010d}.json')); rc=sub['filings']['recent']
    return sub['name'],{rd:(acc,fd) for fm,acc,fd,rd in reversed(list(zip(rc['form'],rc['accessionNumber'],rc['filingDate'],rc['reportDate']))) if fm=='13F-HR'}
res={r['name']:r for r in json.load(open('funds_13f_full.json'))}
for n,(cc,pc) in FIX.items():
    en,fc=filings(cc); _,fp=filings(pc)
    cur=max(p for p in P if p in fc); prev=P[P.index(cur)-1]
    if prev not in fp: print(n,'上期缺',prev); continue
    Hc=holdings(cc,fc[cur][0]); Hp=holdings(pc,fp[prev][0]); tot=sum(v['val'] for v in Hc.values()); moves=[]
    for cu,v in Hc.items():
        if v['sh']<=0: continue
        pv=Hp.get(cu); psh=pv['sh'] if pv else 0.0; split=1
        if psh>0:
            r=(pv['val']/psh)/(v['val']/v['sh']) if v['val']>0 else 0
            if r>1.8 and abs((v['sh']/psh)/r-1)<0.25: split=round(r); psh*=split
        kind='新建仓' if psh<=0 else ('加仓' if v['sh']>=psh*1.2 else None)
        moves.append(dict(cusip=cu,issuer=v['issuer'],cls=v['cls'],kind=kind,sh=v['sh'],psh=psh,split=split,chg=(v['sh']/psh-1) if psh>0 else None,val=v['val'],pval=(pv['val'] if pv else 0.0),w=v['val']/tot if tot else 0))
    res[n]=dict(name=n,cik=str(cc),edgar=en,found=True,cur=cur,prev=prev,filed=fc[cur][1],n_pos=len(Hc),aum=tot,moves=moves,prev_only=[dict(cusip=cu,issuer=v['issuer'],cls=v['cls'],sh=v['sh'],val=v['val']) for cu,v in Hp.items() if cu not in Hc],
                note='' if cc==pc else f'申报主体变更: 上期CIK {pc}')
    print(f"{n:34s} | {en[:34]:34s} | {prev}→{cur} 申报{fc[cur][1]} | 持仓{len(Hc)} 上期{len(Hp)} 动作{len(moves)}",flush=True)
res['Scion Asset Management'].update(found=False,note='2025Q3 后停报13F')
json.dump(list(res.values()),open('funds_13f_full.json','w'),ensure_ascii=False)

"""13F 聚合: CUSIP→代码(OpenFIGI / 名称 / 隐含单价对收盘价, 三路取候选, 一律用隐含单价校验), 按代码合并两期(防 CUSIP 变更把老持仓当新建),
按市值口径判新建/加仓(免疫拆股与申报口径不一): 加仓 = (Q2市值/06-30收盘) ÷ (Q1市值/03-31收盘) - 1 >= 20%; 新建 = Q1 该代码无持仓。
过滤: 持仓市值<500万美元且占组合<0.5% 的零头仓不计。输出 fund_counts.json / fund_rows.json"""
import json, re, collections, pandas as pd, numpy as np
F=json.load(open('funds_13f_full.json')); mp=json.load(open('cusip_map.json'))
px=pd.read_pickle('px.pkl'); uni={u['t']:u for u in json.load(open('universe.json'))}
P2=px.loc[:'2026-06-30'].iloc[-1].dropna(); P1=px.loc[:'2026-03-31'].iloc[-1].dropna()
SUF=r'\b(INC|CORP|CORPORATION|CO|COMPANY|LTD|LIMITED|PLC|NV|N V|SA|S A|AG|SE|HOLDINGS?|HLDGS?|GROUP|THE|COM|NEW|DEL|CL [A-Z]|CLASS [A-Z]|ORD|SHS|ADR|SPONSORED|LP|L P|LLC|TR|TRUST)\b'
def norm(s): s=re.sub(r'[^A-Z0-9 ]',' ',s.upper().replace('&',' AND ')); s=re.sub(SUF,' ',s); return ' '.join(s.split())
UN={t:norm(re.sub(r'(Common Stock|Class [A-Z] .*|Ordinary Shares.*|American Depositary.*|Common Shares.*|Subordinate Voting.*)','',u['name'])) for t,u in uni.items()}
NM=collections.defaultdict(list)
for t,n in UN.items(): NM[n].append(t)
def tk_ok(t): return t in uni
def cands(cu,issuer,cls,p,Pref):
    out=[tk.replace('/','-').replace('.','-') for tk,ty,_ in (mp.get(cu) or []) if tk]
    k=norm(issuer); out+=NM.get(k,[])
    w0=(k.split() or [''])[0][:4]
    if p:
        near=Pref.index[(abs(Pref/p-1)<0.005).values]
        kw={w for w in k.split() if len(w)>=4}; k0=k.replace(' ','')[:4]
        out+=[t for t in near if t in UN and (UN[t].replace(' ','')[:4]==k0 or kw&{w for w in UN[t].split() if len(w)>=4})]
    m=re.search(r'CL(?:ASS)?\s*([A-C])\b',(cls or '').upper())
    out=list(dict.fromkeys(out))
    if m and len(out)>1:
        pref=[t for t in out if t.endswith(m.group(1))]; out=pref+[t for t in out if t not in pref]
    return out
def resolve(cu,issuer,cls,sh,val,Pref):
    p=val/sh if sh else None
    for t in cands(cu,issuer,cls,p,Pref):
        if t in Pref.index and p:
            r=p/Pref[t]
            if 0.75<r<1.33 or any(abs(r/j-1)<0.08 for j in range(2,31)): return t
    # 首词兜底(13F 缩写如 HONEYWELL INTL): 首词>=5字母且非泛词, 单价相差<7%
    w=(norm(issuer).split() or [''])[0]
    if p and len(w)>=5 and w not in STOP:
        for t in FW.get(w,[]):
            if t in Pref.index and 0.93<p/Pref[t]<1.07: return t
    return None
STOP={'AMERICAN','FIRST','UNITED','GENERAL','NATIONAL','INTERNATIONAL','GLOBAL','SOUTHERN','NORTHERN','WESTERN','EASTERN','CAPITAL','PACIFIC','ATLANTIC','CENTRAL','INVESCO','ISHARES','SELECT','ROYAL','ADVANCED','APPLIED','DIGITAL','HEALTHCARE','ENERGY'}
FW=collections.defaultdict(list)
for t,n in UN.items():
    if n: FW[n.split()[0]].append(t)
# 市值单位: 千美元申报者(隐含单价约为收盘价的千分之一)
unit={}
for f in F:
    rs=[]
    for m in (f.get('moves') or [])[:400]:
        if m['sh']<=0: continue
        for t in cands(m['cusip'],m['issuer'],m['cls'],None,P2):
            if t in P2.index: rs.append(m['val']/m['sh']/P2[t]); break
    unit[f['name']]=1000.0 if (rs and np.median(rs)<0.01) else 1.0
for f in F:   # ⛔守卫: 上期持仓数不足本期一半=上期没取到, 整轮中止
    m=f.get('moves') or []
    if m: assert sum(1 for x in m if x.get('pval',0)>0)+len(f.get('prev_only') or [])>=0.5*len(m), f"{f['name']} 上期持仓疑似未取到"
rows=[]; unm=collections.Counter(); hit=0
for f in F:
    if not f.get('moves'): continue
    k=unit[f['name']]; aum=sum(m['val'] for m in f['moves'])*k
    cur=collections.defaultdict(float); prv=collections.defaultdict(float)
    for m in f['moves']:
        t=resolve(m['cusip'],m['issuer'],m['cls'],m['sh'],m['val']*k,P2)
        if not t: unm[m['issuer']]+=m['val']*k; continue
        hit+=1; cur[t]+=m['val']*k
        if m.get('pval',0)>0: prv[t]+=m['pval']*k
    for m in f.get('prev_only') or []:
        t=resolve(m['cusip'],m['issuer'],m['cls'],m['sh'],m['val']*k,P1)
        if t: prv[t]+=m['val']*k
    for t,val in cur.items():
        if not tk_ok(t) or t not in P1.index and prv.get(t,0)>0: continue
        if prv.get(t,0)>0:
            chg=(val/P2[t])/(prv[t]/P1[t])-1; kind='加仓' if chg>=0.20 else None
        else: chg=None; kind='新建仓'
        if not kind or (val<5e6 and val/aum<0.005): continue
        rows.append(dict(t=t,fund=f['name'],kind=kind,chg=chg,val=val,w=val/aum))
df=pd.DataFrame(rows)
ETFW=('ISHARES','SPDR','VANGUARD','ETF','TRUST','FDS','FUND',' TR','SELECT SECTOR','INVESCO QQQ')
print('映射命中',hit,'未映射(非ETF)前列',[(a,round(v/1e9,1)) for a,v in unm.most_common(80) if not any(w in a for w in ETFW)][:15])
print('千美元口径',[k for k,v in unit.items() if v!=1])
print('动作',len(df),'股票',df.t.nunique(),'新建',(df.kind=='新建仓').sum(),'加仓',(df.kind=='加仓').sum())
cnt=df.groupby('t').fund.nunique().sort_values(ascending=False)
json.dump({t:int(n) for t,n in cnt.items()},open('fund_counts.json','w'))
out=[]
for t,n in cnt.items():
    d=df[df.t==t]
    out.append(dict(t=t,n=int(n),wmax=float(d.w.max()),
        new='; '.join(d[d.kind=='新建仓'].sort_values('val',ascending=False).fund.drop_duplicates()),
        add='; '.join(f"{r.fund}(+{r.chg:.0%})" for r in d[d.kind=='加仓'].sort_values('val',ascending=False).drop_duplicates('fund').itertuples())))
json.dump(out,open('fund_rows.json','w'),ensure_ascii=False)
print(cnt.head(30).to_dict()); print('>=2家',(cnt>=2).sum(),'1家但占组合>=1%',sum(1 for o in out if o['n']==1 and o['wmax']>=0.01))

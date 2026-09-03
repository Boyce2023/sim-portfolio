import json,sqlite3,collections,statistics as st,sys
sys.path.insert(0,'/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban')
from engine_b2 import build
from strategy_b2 import PARAMS_B2 as P
B='/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban/'; IND=json.load(open(B+'ind_map.json'))
def fee(a,sell): return max(a*P['comm'],P['comm_min'])+a*P['transfer']+(a*P['stamp'] if sell else 0)
def features(db,m0,m1,tag):
    by,sig,mood=build(db,m0,m1)
    con=sqlite3.connect(db); k=collections.defaultdict(list)
    for code,date,o,h,l,c,pc,vol,amt,turn in con.execute("select code,date,open,high,low,close,preclose,volume,amount,turn from k order by code,date"): k[code].append((date,o,h,l,c,pc,vol,amt,turn))
    zt=collections.defaultdict(list); med=collections.defaultdict(list)
    for code,bars in k.items():
        lim=0.199 if code[3:5] in ('30','68') else 0.099
        for b in bars:
            if b[5]>0 and m0<=b[0]<=m1:
                med[b[0]].append(b[4]/b[5]-1)
                if abs(b[4]-round(b[5]*(1+lim),2))<0.005: zt[b[0]].append(code)
    rows=[]
    for d,lst in sig.items():
        cand=sorted(lst,key=lambda x:x['rank'])[:P['max_positions']]   # 同B: 每日换手最低3只
        for t in cand:
            bars=k.get(t['code']); idx=[i for i,b in enumerate(bars) if b[0]==d]
            if not idx or idx[0]<21: continue
            i=idx[0]; b=bars[i]; lim=0.199 if t['code'][3:5] in ('30','68') else 0.099
            cap=1e6/3; sh=int(cap/t['buy']/100)*100
            if sh<=0: continue
            ba=sh*t['buy']; sa=sh*t['sell']*(1-P['slip_sell']); net=(sa-ba-fee(ba,False)-fee(sa,True))/cap*100
            v5=st.mean([x[6] for x in bars[i-5:i]]); ind=IND.get(t['code'][-6:],'?')
            rows.append(dict(tag=tag,d=d,code=t['code'],net=net,turn=t['turn'],mc=t['mc']/1e8,gap=(b[1]/b[5]-1)*100,rng=(b[2]-b[3])/b[5]*100,pre1=(bars[i-1][4]/bars[i-1][5]-1)*100,pre5=(b[5]/bars[i-5][4]-1)*100,pre20=(b[5]/bars[i-20][4]-1)*100,vr=b[6]/v5 if v5 else 0,amt=b[7]/1e8,nzt=len(zt[d]),same=sum(1 for c in zt[d] if IND.get(c[-6:],'?')==ind),medmkt=st.median(med[d])*100 if med[d] else 0,hi20=(b[5]/max(x[2] for x in bars[i-20:i])-1)*100,streak=t['streak']))
    return rows
R=[]
R+=features(B+'univ2025.db','2025-01-01','2025-06-30','25H1')
R+=features(B+'univ2025.db','2025-07-01','2025-12-31','25H2')
for m in ['01','02','03']: R+=features(B+f'univ2026{m}.db',f'2026-{m}-01',f'2026-{m}-31','26Q1')
for m in ['04','05','06']: R+=features(B+f'univ2026{m}.db',f'2026-{m}-01',f'2026-{m}-31','26Q2')
json.dump(R,open('/tmp/b_winrate_rows.json','w'))
print('样本',collections.Counter(r['tag'] for r in R))

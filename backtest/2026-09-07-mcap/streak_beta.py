"""连板高度×市值 / 大beta行情×市值 (2026-09-07 Buwen三问)
①连板数越高的股, 市值在哪个区间? ②只有1个板的呢? ③大beta行情时涨最多的是哪个市值段?
⛔口径同前: engine的_islim判涨停, 流通市值=成交额/(换手率/100)。
"""
import json,sqlite3,collections,statistics as st,sys
sys.path.insert(0,'/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban')
from engine import lim_pct
def _islim(x,pc,L): return x>=round(pc*(1+L),2)-0.02 and (x/pc-1)>=L-0.004
B='/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban/'
DBS=[('univ2025.db','2025-01-01','2025-12-31','2025')]
for m in ['01','02','03','04','05','06']: DBS.append((f'univ2026{m}.db',f'2026-{m}-01',f'2026-{m}-31',f'26M{m}'))
rows=[]; daily=collections.defaultdict(lambda:{'up':0,'dn':0,'chg':[]})
for db,m0,m1,tag in DBS:
    con=sqlite3.connect(B+db); by=collections.defaultdict(list)
    for r in con.execute("select code,date,open,high,low,close,preclose,volume,amount,turn from k order by code,date"):
        by[r[0]].append(r)
    for code,bars in by.items():
        L=lim_pct(code)
        for i,b in enumerate(bars):
            _,d,o,h,l,c,pc,vol,amt,turn=b
            if not (m0<=d<=m1) or pc<=0: continue
            ch=(c/pc-1)*100
            daily[d]['chg'].append(ch)
            if ch>0: daily[d]['up']+=1
            elif ch<0: daily[d]['dn']+=1
            if not _islim(c,pc,L) or not turn or turn<=0 or not amt: continue
            mcap=amt/(turn/100)/1e8
            if mcap<=0 or mcap>5000: continue
            # 连板数: 往前数连续涨停
            s=1; j=i-1
            while j>=0:
                pb=bars[j]
                if pb[6]>0 and _islim(pb[5],pb[6],lim_pct(code)): s+=1; j-=1
                else: break
            nxt=bars[i+1] if i+1<len(bars) else None
            rows.append(dict(tag=tag,d=d,code=code,mcap=mcap,streak=s,turn=turn,
                prem=((nxt[2]/c-1)*100) if nxt else None))
json.dump(rows,open('/tmp/streak_rows.json','w'))
json.dump({k:{'up':v['up'],'dn':v['dn'],'med':st.median(v['chg']) if v['chg'] else 0} for k,v in daily.items()},
          open('/tmp/daily_breadth.json','w'))
print(f"涨停样本 {len(rows)} | 交易日 {len(daily)}")
def q(vals,p): 
    v=sorted(vals); return v[int(len(v)*p)]
print("\n【①②连板高度 × 流通市值(亿)】")
print(f"  {'连板':<6}{'样本':>6}{'P25':>7}{'中位':>7}{'P75':>7}{'均值':>7}{'占比':>7}")
for s in [1,2,3,4,5]:
    g=[r['mcap'] for r in rows if r['streak']==s]
    if len(g)<20: continue
    print(f"  {s}板{'':<3}{len(g):>6}{q(g,.25):>7.0f}{q(g,.5):>7.0f}{q(g,.75):>7.0f}{st.mean(g):>7.0f}{len(g)/len(rows)*100:>6.1f}%")
g=[r['mcap'] for r in rows if r['streak']>=6]
if len(g)>=20: print(f"  6板+{'':<2}{len(g):>6}{q(g,.25):>7.0f}{q(g,.5):>7.0f}{q(g,.75):>7.0f}{st.mean(g):>7.0f}{len(g)/len(rows)*100:>6.1f}%")

"""B策略市值维度研究 (2026-09-07, Buwen提议)
问题: 2025-01至2026-06涨停股的市值分布? 不同市值档的次日溢价有差异吗?
⛔口径: 用已修正的 engine_b2_fix(涨停判定 _islim), 全量涨停股(不只B选中的3只/日)。
市值 = 成交额/(换手率/100), 与engine_b2的cap算法一致。
"""
import json,sqlite3,collections,statistics as st,sys
sys.path.insert(0,'/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban')
from engine import lim_pct
def _islim(x,pc,L): return x>=round(pc*(1+L),2)-0.02 and (x/pc-1)>=L-0.004
B='/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban/'
DBS=[('univ2025.db','2025-01-01','2025-06-30','25H1'),('univ2025.db','2025-07-01','2025-12-31','25H2')]
for m in ['01','02','03','04','05','06']: DBS.append((f'univ2026{m}.db',f'2026-{m}-01',f'2026-{m}-31',f'26M{m}'))
rows=[]
for db,m0,m1,tag in DBS:
    con=sqlite3.connect(B+db); by=collections.defaultdict(list)
    for r in con.execute("select code,date,open,high,low,close,preclose,volume,amount,turn from k order by code,date"):
        by[r[0]].append(r)
    for code,bars in by.items():
        L=lim_pct(code)
        for i,b in enumerate(bars):
            _,d,o,h,l,c,pc,vol,amt,turn=b
            if not (m0<=d<=m1) or pc<=0: continue
            if not _islim(c,pc,L): continue
            if not turn or turn<=0 or not amt: continue
            mcap=amt/(turn/100)/1e8          # 流通市值(亿)
            if mcap<=0 or mcap>5000: continue
            nxt=bars[i+1] if i+1<len(bars) else None
            if not nxt: continue
            prem=(nxt[2]/c-1)*100            # 次日开盘溢价%
            yizi=_islim(o,pc,L) and _islim(l,pc,L)
            rows.append(dict(tag=tag,d=d,code=code,mcap=mcap,turn=turn,prem=prem,yizi=yizi,
                             amt=amt/1e8,pre1=(bars[i-1][5]/bars[i-1][6]-1)*100 if i>0 and bars[i-1][6]>0 else 0))
json.dump(rows,open('/tmp/mcap_rows.json','w'))
print(f"样本: {len(rows)} 个涨停(含次日开盘价)")
ms=sorted(r['mcap'] for r in rows)
def pct(p): return ms[int(len(ms)*p)]
print(f"\n【全部涨停股流通市值分布(亿元)】")
print(f"  P5 {pct(.05):.0f} | P10 {pct(.10):.0f} | P25 {pct(.25):.0f} | 中位 {pct(.50):.0f} | P75 {pct(.75):.0f} | P90 {pct(.90):.0f} | P95 {pct(.95):.0f}")
print(f"  均值 {st.mean(ms):.0f} | 最小 {ms[0]:.1f} | 最大 {ms[-1]:.0f}")
BK=[(0,20),(20,40),(40,60),(60,100),(100,150),(150,250),(250,500),(500,99999)]
print(f"\n【按市值分档: 占比 与 次日开盘溢价】(全部涨停)")
print(f"  {'市值档(亿)':<14}{'样本':>6}{'占比':>7}{'均溢价':>8}{'中位':>7}{'胜率':>7}")
for lo,hi in BK:
    s=[r for r in rows if lo<=r['mcap']<hi]
    if len(s)<30: continue
    prem=[r['prem'] for r in s]
    w=sum(1 for x in prem if x>0)/len(prem)*100
    lab=f"{lo}-{hi}" if hi<99999 else f"{lo}+"
    print(f"  {lab:<14}{len(s):>6}{len(s)/len(rows)*100:>6.1f}%{st.mean(prem):>+8.2f}{st.median(prem):>+7.2f}{w:>6.0f}%")

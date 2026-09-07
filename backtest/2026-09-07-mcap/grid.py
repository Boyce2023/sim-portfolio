"""月份 × 市值 二维大表 (2026-09-07 Buwen要求)
样本: 2025-01至2026-03全部涨停股(2板及以上=游资在炒), 跨库按(code,date)去重。
⛔A策略同源: A是次日开盘接力昨日板, 用的是同一批涨停股, 故本表对A/B都适用。
"""
import sqlite3,collections,statistics as st,sys,glob,os,json
sys.path.insert(0,'/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban')
from engine import lim_pct
def _islim(x,pc,L): return x>=round(pc*(1+L),2)-0.02 and (x/pc-1)>=L-0.004
B='/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban/'
bars=collections.defaultdict(dict)   # code -> date -> row (去重)
for f in sorted(glob.glob(B+'univ*.db')):
    con=sqlite3.connect(f)
    for code,d,o,h,l,c,pc,vol,amt,turn in con.execute(
        "select code,date,open,high,low,close,preclose,volume,amount,turn from k"):
        if '2025-01'<=d[:7]<='2026-03': bars[code][d]=(o,h,l,c,pc,amt,turn)
rows=[]
for code,dd in bars.items():
    ds=sorted(dd); L=lim_pct(code)
    for i,d in enumerate(ds):
        o,h,l,c,pc,amt,turn=dd[d]
        if pc<=0 or not turn or turn<=0 or not amt: continue
        if not _islim(c,pc,L): continue
        mcap=amt/(turn/100)/1e8
        if mcap<=0 or mcap>1e4: continue
        s=1; j=i-1
        while j>=0:
            po,ph,pl,pcl,ppc,pa,pt=dd[ds[j]]
            if ppc>0 and _islim(pcl,ppc,L): s+=1; j-=1
            else: break
        nxt=dd[ds[i+1]] if i+1<len(ds) else None
        if not nxt: continue
        rows.append(dict(m=d[:7],code=code,mcap=mcap,streak=s,prem=(nxt[0]/c-1)*100))
json.dump(rows,open('/tmp/grid_rows.json','w'))
print(f"去重后涨停样本 {len(rows)} | 2板+ {sum(1 for r in rows if r['streak']>=2)}")

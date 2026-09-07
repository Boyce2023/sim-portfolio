"""v3 — 加赔率与首板后涨幅分布 (2026-09-07 Buwen: "只有胜率不够, 要赔率")
对每个涨停事件, 记录:
· 次日开盘溢价(B策略的实际收益)
· ⭐首板之后能涨到多少: 从首板收盘算起, 后续N日的最大涨幅(每10%分级)
· ⭐最终连板数(这一波总共走了几个板)
· 赔率 = 平均盈利 / 平均亏损
"""
import sqlite3,collections,statistics as st,sys,glob,json
sys.path.insert(0,'/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban')
from engine import lim_pct
def _islim(x,pc,L): return x>=round(pc*(1+L),2)-0.02 and (x/pc-1)>=L-0.004
B='/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban/'
bars=collections.defaultdict(dict)
for f in sorted(glob.glob(B+'univ*.db')):
    try: con=sqlite3.connect(f'file:{f}?mode=ro',uri=True)
    except Exception: continue
    try:
        for code,d,o,h,l,c,pc,amt,turn in con.execute(
            "select code,date,open,high,low,close,preclose,amount,turn from k"):
            if d[:7]>='2025-01': bars[code][d]=(o,h,l,c,pc,amt,turn)
    except Exception as e: print(f"跳过{f}: {repr(e)[:50]}")
rows=[]
for code,dd in bars.items():
    ds=sorted(dd); L=lim_pct(code); n=len(ds)
    for i,d in enumerate(ds):
        o,h,l,c,pc,amt,turn=dd[d]
        if pc<=0 or not turn or turn<=0 or not amt: continue
        if not _islim(c,pc,L): continue
        mcap=amt/(turn/100)/1e8
        if mcap<=0 or mcap>1e4: continue
        # 是不是首板(前一日不涨停)
        prev_lim=False
        if i>0:
            po,ph,pl,pcl,ppc,pa,pt=dd[ds[i-1]]
            prev_lim = ppc>0 and _islim(pcl,ppc,L)
        streak=1; j=i-1
        while j>=0:
            po,ph,pl,pcl,ppc,pa,pt=dd[ds[j]]
            if ppc>0 and _islim(pcl,ppc,L): streak+=1; j-=1
            else: break
        # ⭐这一波最终走了几个板(往后数)
        fw=i+1; final=streak
        while fw<n:
            fo,fh,fl,fc,fpc,fa,ft=dd[ds[fw]]
            if fpc>0 and _islim(fc,fpc,L): final+=1; fw+=1
            else: break
        # ⭐从当前收盘算起 后续10日最高涨幅
        maxup=0.0; maxup5=0.0
        for k in range(i+1,min(i+11,n)):
            hi=dd[ds[k]][1]
            up=(hi/c-1)*100
            if up>maxup: maxup=up
            if k<=i+5 and up>maxup5: maxup5=up
        nxt=dd[ds[i+1]] if i+1<n else None
        if not nxt: continue
        rows.append(dict(m=d[:7],code=code,mcap=mcap,streak=streak,final=final,
            first=not prev_lim, prem=(nxt[0]/c-1)*100, maxup10=maxup, maxup5=maxup5,
            board='20cm' if L>0.15 else '10cm'))
json.dump(rows,open('/tmp/grid_v3.json','w'))
print(f"样本 {len(rows)} | 首板 {sum(1 for r in rows if r['first'])} | 月份 {min(r['m'] for r in rows)}~{max(r['m'] for r in rows)}")

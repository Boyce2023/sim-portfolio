"""v4 — 全表统一为"首板之后的走势"(2026-09-07 Buwen: 整个表都要首板后的走势)
对每个首板, 记录后续 1/3/5/10/20 日的:
· 收盘收益(买在首板收盘, 持有N日后收盘卖)
· 期间最高涨幅 / 最低跌幅
· 最终连板数
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
    except Exception: pass
rows=[]
for code,dd in bars.items():
    ds=sorted(dd); L=lim_pct(code); n=len(ds)
    for i,d in enumerate(ds):
        o,h,l,c,pc,amt,turn=dd[d]
        if pc<=0 or not turn or turn<=0 or not amt: continue
        if not _islim(c,pc,L): continue
        if i>0:
            po,ph,pl,pcl,ppc,pa,pt=dd[ds[i-1]]
            if ppc>0 and _islim(pcl,ppc,L): continue      # ⛔只要首板
        mcap=amt/(turn/100)/1e8
        if mcap<=0 or mcap>1e4: continue
        if i+1>=n: continue
        rec=dict(m=d[:7],code=code,mcap=mcap,board='20cm' if L>0.15 else '10cm')
        rec['open1']=(dd[ds[i+1]][0]/c-1)*100            # 次日开盘(B策略实际卖点)
        # 持有N日收盘 与 期间最高/最低
        for N in (1,3,5,10,20):
            k=min(i+N,n-1)
            if k<=i: continue
            rec[f'r{N}']=(dd[ds[k]][3]/c-1)*100          # 持有N日收盘收益
            seg=[dd[ds[x]] for x in range(i+1,k+1)]
            rec[f'hi{N}']=max((s[1]/c-1)*100 for s in seg)
            rec[f'lo{N}']=min((s[2]/c-1)*100 for s in seg)
        # 最终连板数
        final=1; fw=i+1
        while fw<n:
            fo,fh,fl,fc,fpc,fa,ft=dd[ds[fw]]
            if fpc>0 and _islim(fc,fpc,L): final+=1; fw+=1
            else: break
        rec['final']=final
        if 'r10' in rec: rows.append(rec)
json.dump(rows,open('/tmp/grid_v4.json','w'))
print(f"首板样本 {len(rows)} | {min(r['m'] for r in rows)}~{max(r['m'] for r in rows)}")
import statistics as S
for N in (1,3,5,10,20):
    g=[r[f'r{N}'] for r in rows if f'r{N}' in r]
    hi=[r[f'hi{N}'] for r in rows if f'hi{N}' in r]
    print(f"  持有{N:>2}日: 均{S.mean(g):+.2f}% 中位{S.median(g):+.2f}% 胜率{sum(1 for x in g if x>0)/len(g)*100:.0f}% | 期间最高中位{S.median(hi):+.1f}%")

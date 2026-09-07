"""月份 × 市值 二维表 v2 — ⛔按累计涨幅归一化, 不按板数 (2026-09-07 Buwen提出)

⛔v1的缺陷: 把"涨停"当统一事件, 但主板10%、创业板科创板20%、北交所30%。
   同样是"3板", 主板累计约33%, 创业板约73% —— 我把两种东西混在一格里统计了。
Buwen的口径: **他在意的是总涨幅**, 20%封板的股走15%+5% 与 两个10%涨停 效用相同。
本质是"资金推动股价上涨的总幅度"才是可比单位。

v2做三件事:
①连板数 → **累计涨幅**(从启动日到当日的实际涨幅), 20cm的2板与10cm的4板都约44%, 同档
②涨停幅度按板性归一: 记录每次涨停的真实幅度(0.10/0.20/0.30)而非计数
③次日溢价同时给**原始值**与**按涨跌幅上限归一化值**(prem/limit_pct), 因为20cm股次日波动天然是10cm的两倍
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
        for code,d,o,h,l,c,pc,vol,amt,turn in con.execute(
            "select code,date,open,high,low,close,preclose,volume,amount,turn from k"):
            if d[:7]>='2025-01': bars[code][d]=(o,h,l,c,pc,amt,turn)
    except Exception as e: print(f"  跳过{f}: {repr(e)[:60]}")
rows=[]
for code,dd in bars.items():
    ds=sorted(dd); L=lim_pct(code)
    board = '20cm' if L>0.15 else ('30cm' if L>0.25 else '10cm')
    for i,d in enumerate(ds):
        o,h,l,c,pc,amt,turn=dd[d]
        if pc<=0 or not turn or turn<=0 or not amt: continue
        if not _islim(c,pc,L): continue
        mcap=amt/(turn/100)/1e8
        if mcap<=0 or mcap>1e4: continue
        # 连板数 与 ⭐累计涨幅(从连板起始日前收 到 今日收盘)
        s=1; j=i-1
        while j>=0:
            po,ph,pl,pcl,ppc,pa,pt=dd[ds[j]]
            if ppc>0 and _islim(pcl,ppc,L): s+=1; j-=1
            else: break
        base_pc = dd[ds[j+1]][4] if j+1<len(ds) else pc     # 连板起始日的前收
        cum = (c/base_pc-1)*100 if base_pc>0 else 0          # ⭐累计涨幅%
        nxt=dd[ds[i+1]] if i+1<len(ds) else None
        if not nxt: continue
        prem=(nxt[0]/c-1)*100
        rows.append(dict(m=d[:7],code=code,mcap=mcap,streak=s,cum=cum,prem=prem,
                         board=board,lim=L*100,prem_norm=prem/(L*100)*10))  # 归一到10cm口径
json.dump(rows,open('/tmp/grid_v2.json','w'))
print(f"样本 {len(rows)}")
c=collections.Counter(r['board'] for r in rows)
print(f"板性分布: {dict(c)}")
print(f"⛔同为'3板'的累计涨幅差异: ", end="")
for b in ['10cm','20cm']:
    g=[r['cum'] for r in rows if r['board']==b and r['streak']==3]
    if g: print(f"{b} 中位{st.median(g):.0f}%  ", end="")
print()

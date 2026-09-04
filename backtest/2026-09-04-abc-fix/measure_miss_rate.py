"""量化旧涨停判定口径的真实漏板率。⛔结论: 2.1%-2.5%, 不是我9/3声称的75%。"""
import sqlite3,sys
sys.path.insert(0,'/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban')
from engine import lim_pct
def _islim(x,pc,L): return x>=round(pc*(1+L),2)-0.02 and (x/pc-1)>=L-0.004
B='/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban/'
for db in ['univ2025.db','univ202601.db','univ202604.db']:
    con=sqlite3.connect(B+db); old=new=both=0
    for code,d,c,pc in con.execute("select code,date,close,preclose from k where preclose>0"):
        L=lim_pct(code)
        o=abs(c-round(pc*(1+L),2))<0.005; n=_islim(c,pc,L)
        old+=o; new+=n; both+=(o and n)
    print(f"{db}: 旧{old} 新{new} 漏{new-both} = {(new-both)/new*100:.1f}%")

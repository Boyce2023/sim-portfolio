"""C策略按月跑并落交易明细: python3 run_c_month.py univ202604.db 2026-04-01 2026-04-30 quiet"""
import sys,json,sqlite3
sys.path.insert(0,'/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-28-cstrategy')
sys.path.insert(0,'/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban')
import engine_c3 as C3
from engine_c3 import load,signals3,E,PARAMS_C
db,m0,m1,ch=sys.argv[1:5]
B='/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban/'
by=load(db)
if db!='univ2025.db':
    old=set(x[0] for x in sqlite3.connect(B+'univ2025.db').execute("select distinct code from k"))
    by={c:b for c,b in by.items() if c in old}
P=dict(PARAMS_C);P['exit_ma']=20;E.P=P
sig=signals3(by,m0,m1,ch)
nav,tr=E.run(by,sig,m0,m1)
nets=[t['net'] for t in tr]; w=sum(1 for x in nets if x>0)/len(nets)*100 if nets else 0
ns=sum(len(v) for v in sig.values())
print(f'C[{ch}] {m0[:7]}: 信号{ns} NAV={nav:.4f} {(nav-1)*100:+.1f}% 笔数{len(tr)} 胜率{w:.0f}%')
json.dump({'nav':nav,'trades':tr,'n_signals':ns},open(f'/tmp/abc_4-6/c_{ch}_{m0[:7]}.json','w'),ensure_ascii=False)
print('C_DONE')

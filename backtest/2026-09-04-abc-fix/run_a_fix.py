"""A策略(次日开盘接力)用修正涨停判定重跑。
原 abs(c-lim)<0.005 在前复权价下漏掉约75%的板 → 用 _islim(价差<=0.02 且 比例>=L-0.004)。
用法: run_a_fix.py <db> <m0> <m1> <tag>"""
import sys,json
B='/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban/'
sys.path.insert(0,B)
import engine_fix as EF
db,m0,m1,tag=sys.argv[1:5]
by=EF.load(B+db)
sig=EF.signals(by,m0,m1)
# ⛔2026-09-04修正: TD必须是区间内全部交易日(照 engine_news.py:87), 不是"有信号的日子"。
#   我第一版传了 sorted(sig.keys()) → 持仓管理与出场逻辑全乱, 产出的A表是脚本错误不是策略表现。
TD=sorted({b[1] for bars in by.values() for b in bars if m0<=b[1]<=m1})
last_buy=TD[-1] if TD else m1
n=sum(len(v) for v in sig.values())
nav,tr,_log=EF.run(by,sig,TD,last_buy)
nets=[t.get('net',0) for t in tr]
w=(sum(1 for x in nets if x>0)/len(nets)*100) if nets else 0
avg=(sum(nets)/len(nets)) if nets else 0
print(f'A[{tag}] {m0[:7]}: 信号{n} 笔数{len(tr)} NAV={nav:.4f} ({(nav-1)*100:+.1f}%) 胜率{w:.0f}% 均{avg:+.2f}%')
json.dump({'tag':tag,'n_signals':n,'nav':nav,'trades':tr},open(f'/tmp/abc_fix/a_{tag}.json','w'),ensure_ascii=False,default=str)
print('A_DONE')

#!/opt/homebrew/bin/python3.13
# 用高标池自身近期战绩定义黄金期（只用买入日前已平仓的结果，零未来函数），黄金期只卡开盘价与锁仓
import numpy as np, pandas as pd
D = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/sandbox_lab/golden_regime_20261113"
src = "\n".join(open(f"{D}/sub2_03_golden_relaxation_backtest.py").read().splitlines()[:192])
src = src.replace('r["d1_to"] > 38.0', 'r["d1_to"] > 35.0').replace("if r.op2 > 0.045 or b_op", "if r.op2 > OP_CAP or b_op")
G = {"OP_CAP": 0.045, "__name__": "eng"}; exec(src, G)
dfr, sim_trade = G["dfr"], G["sim_trade"]
allx = []
for r in dfr.itertuples():
    x = sim_trade(r, "morn_cond", "S_hold_d3")
    if x is not None: x["sc"] = r.sc5_1; x["op2"] = r.op2; x["lk"] = max(r.lock, r.fmcap); x["reg"] = bool(r.s_reg or r.tox or r.ex_reg5 >= 2); allx.append(x)
A = pd.DataFrame(allx).sort_values("buy_date").reset_index(drop=True)
print(f"池内可成交 {len(A)} 笔, 全池均利 {A.net_ret.mean()*100:+.2f}% 胜率 {(A.net_ret>0).mean()*100:.1f}%")

def heat(d, K, mode):
    past = A[A.exit_date < d].tail(K)
    if len(past) < K: return False
    if mode == "mean": return past.net_ret.mean() > 0
    return (past.net_ret > 0).mean() >= 0.6

def met(w):
    r = w.net_ret.values
    if len(r) == 0: return "0笔"
    c = pk = 1; m = 0
    for x in r: c *= 1 + x; pk = max(pk, c); m = max(m, (pk - c) / pk)
    po, ne = r[r > 0], r[r <= 0]
    plr = po.mean() / abs(ne.mean()) if len(po) and len(ne) else 99
    eq = np.prod(1 + w.groupby("buy_date").net_ret.mean().values)
    return f"{len(r):2d}笔 WR{(r>0).mean()*100:5.1f}% PLR{plr:4.2f} 1S{np.prod(1+r):6.2f}x EQ{eq:6.2f}x MDD{m*100:4.1f}%"

def slot(t):
    t = t.sort_values(["buy_date", "pri"], ascending=[True, False]); taken, fd, peo = [], "", False
    for r in t.itertuples(index=False):
        if fd == "" or r.buy_date > fd or (r.buy_date == fd and peo and (not r.b_open_h)):
            taken.append(r); fd, peo = r.exit_date, r.eo
    return pd.DataFrame(taken)

for K, mode in [(3, "mean"), (5, "mean"), (5, "wr"), (8, "mean"), (10, "wr")]:
    A["hot"] = [heat(d, K, mode) for d in A.buy_date]
    hb = A[A.hot]; cb = A[~A.hot]
    print(f"\n[自身热度 K={K} {mode}] 热日占比 {A.hot.mean()*100:.0f}% | 热日全池: {met(hb)} | 冷日全池: {met(cb)}")
    for th_hot, oplo, ophi, lkmin in [(88, -0.065, 0.045, 0), (78, -0.065, 0.045, 0), (70, -0.065, 0.045, 0), (0, -0.065, 0.045, 45), (0, -0.04, 0.03, 45), (0, 0.0, 0.045, 45), (60, -0.04, 0.045, 45)]:
        pick = A[((~A.hot) & (A.sc >= 88)) | (A.hot & (A.sc >= th_hot) & A.op2.between(oplo, ophi) & (A.lk >= lkmin) & (~A.reg))].copy()
        pick["pri"] = pick.sc
        L = slot(pick)
        oos = L[L.buy_date >= "2024-01-01"]; ins = L[L.buy_date < "2024-01-01"]
        print(f"  热日线{th_hot:3d} 开盘{oplo}至{ophi} 锁仓{lkmin:2d} | 5Y {met(L)} | 热日部分 {met(L[L.hot])} | 22至23 {met(ins)} | 24至26 {met(oos)}")

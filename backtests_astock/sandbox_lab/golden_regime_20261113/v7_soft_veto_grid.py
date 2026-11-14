#!/opt/homebrew/bin/python3.13
# 高标首阴 V5.1 一刀斩改纯打分网格（不减笔数），复用 sub2_03 前 192 行引擎，d1_to 口径修正为 35
import itertools, numpy as np, pandas as pd
D = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/sandbox_lab/golden_regime_20261113"
src = open(f"{D}/sub2_03_golden_relaxation_backtest.py").read().splitlines()[:192]
src = "\n".join(src).replace('r["d1_to"] > 38.0', 'r["d1_to"] > 35.0').replace("if r.op2 > 0.045 or b_op", "if r.op2 > OP_CAP or b_op")
G = {"OP_CAP": 0.045, "__name__": "eng"}
exec(src, G)
dfr, sim_trade, get_gold_map, CSI = G["dfr"], G["sim_trade"], G["get_gold_map"], G["CSI_MAP"]
score_v5_1 = G["score_v5_1"]

def base_no_veto(r):
    rr = dict(r); rr.update({"s_reg": False, "tox": False, "ex_reg5": 0, "d1_to": min(r["d1_to"], 30.0), "lh1": min(r["lh1"], 2), "op2": min(max(r["op2"], -0.06), 0.044)})
    sc = score_v5_1(rr)
    # 复原被临时改写的真实分项（d1_to/lh1/op2 在原打分里有分档）
    if r["lh1"] >= 3: sc -= (6 if rr["lh1"] == 0 else 0)  # 原 lh1>=3 不享受加分
    if r["op2"] > 0.044: sc -= 0  # 4.5% 以上开盘原本 0 分档
    return sc

dfr["sc_nv"] = [base_no_veto(r) for _, r in dfr.iterrows()]
gm = get_gold_map()

def run(th_n, th_g, P, op_cap, extra=True, cb=True):
    G["OP_CAP"] = op_cap
    rows = []
    for r in dfr.itertuples():
        sc = r.sc_nv
        if r.s_reg or r.tox: sc += P["reg"]
        if r.ex_reg5 >= 2: sc += P["ex"]
        if r.d1_to > 35.0: sc += P["to"]
        if r.lh1 >= 3: sc += P["lh"]
        if r.op2 > 0.045: sc += P["op"]
        if r.op2 < -0.065: sc += P["opl"]
        g = gm.get(r.buy_date, False)
        if sc < (th_g if g else th_n): continue
        x = sim_trade(r, "morn_cond", "S_hold_d3", extra_hold=(extra and g))
        if x is None: continue
        x["sc"] = sc; x["is_gold"] = g; rows.append(x)
    if not rows: return pd.DataFrame()
    t = pd.DataFrame(rows).sort_values(["buy_date", "sc"], ascending=[True, False])
    taken, fd, peo, cl, sk = [], "", False, 0, False
    for r in t.itertuples(index=False):
        if fd == "" or r.buy_date > fd or (r.buy_date == fd and peo and (not r.b_open_h)):
            if cb and sk:
                fd, peo = r.exit_date, r.eo
                if r.net_ret > 0: sk, cl = False, 0
                continue
            taken.append(r); fd, peo = r.exit_date, r.eo
            if r.net_ret < -0.02:
                cl += 1
                if cl >= 2: sk = True
            elif r.net_ret > 0: cl = 0
    return pd.DataFrame(taken), t

def met(L, s="2022-01-04", e="2026-11-12"):
    w = L[(L.buy_date >= s) & (L.buy_date <= e)]
    if w.empty: return dict(n=0, wr=0, plr=0, nav=1, eq=1, mdd=0)
    r = w.net_ret.values; c = pk = 1; m = 0
    for x in r: c *= 1 + x; pk = max(pk, c); m = max(m, (pk - c) / pk)
    po, ne = r[r > 0], r[r <= 0]
    return dict(n=len(r), wr=round((r > 0).mean() * 100, 1), plr=round(po.mean() / abs(ne.mean()), 2) if len(ne) and len(po) else 99,
                nav=round(float(np.prod(1 + r)), 2), eq=round(float(np.prod(1 + w.groupby("buy_date").net_ret.mean().values)), 2), mdd=round(m * 100, 1))

def line(tag, L, cands):
    a, b, c = met(L), met(L, "2024-01-02"), met(L, "2022-01-04", "2023-12-29")
    g = int(L.is_gold.sum())
    print(f"{tag:44s} 5Y {a['n']:2d}笔(金{g}) WR{a['wr']:5.1f} PLR{a['plr']:4.2f} 1S{a['nav']:6.2f}x EQ{a['eq']:6.2f}x MDD{a['mdd']:4.1f} | 3Y {b['n']}笔 WR{b['wr']} {b['nav']}x MDD{b['mdd']} | 22至23 {c['nav']}x")

HARD = dict(reg=-999, ex=-999, to=-999, lh=-999, op=-999, opl=-999)
L0, _ = run(88, 88, HARD, 0.045, extra=False); line("基线V5.1硬切(88/88)", L0, None)
L1, _ = run(88, 78, HARD, 0.045, extra=True); line("硬切+黄金78多拿1天", L1, None)
res = []
for reg, ex, to, lh, op, cap in itertools.product([-30, -40], [-15, -25], [-8, -12, -16], [-12, -20], [-6, -10], [0.045, 0.06]):
    P = dict(reg=reg, ex=ex, to=to, lh=lh, op=op, opl=-20)
    for thn, thg in [(88, 78), (86, 78), (88, 80)]:
        L, _ = run(thn, thg, P, cap)
        if L.empty: continue
        a, b = met(L), met(L, "2024-01-02")
        res.append((a, b, P, cap, thn, thg, L))
res.sort(key=lambda x: (x[0]["n"] >= 42, x[0]["mdd"] <= 16, x[1]["nav"] * x[0]["nav"] ** 0.5), reverse=True)
seen = 0
for a, b, P, cap, thn, thg, L in res:
    if seen >= 14: break
    seen += 1
    line(f"软{P['reg']}/{P['ex']}/{P['to']}/{P['lh']}/{P['op']} 开盘上限{cap} 线{thn}/{thg}", L, None)
print("=== 黄金期只看开盘价与锁仓，其余全放 ===")
def run_gold_relax(th_n, op_lo, op_hi, lockmin, keep_reg, extra=True):
    G["OP_CAP"] = op_hi
    rows = []
    for r in dfr.itertuples():
        g = gm.get(r.buy_date, False)
        if g:
            ok = (op_lo <= r.op2 <= op_hi) and ((r.lock >= lockmin) or (r.fmcap >= lockmin))
            if keep_reg and (r.s_reg or r.tox or r.ex_reg5 >= 2): ok = False
            if not ok: continue
            sc = 1000 + r.sc_nv
        else:
            if r.sc5_1 < th_n: continue
            sc = r.sc5_1
        x = sim_trade(r, "morn_cond", "S_hold_d3", extra_hold=(extra and g))
        if x is None: continue
        x["sc"] = sc; x["is_gold"] = g; rows.append(x)
    t = pd.DataFrame(rows).sort_values(["buy_date", "sc"], ascending=[True, False])
    taken, fd, peo = [], "", False
    for r in t.itertuples(index=False):
        if fd == "" or r.buy_date > fd or (r.buy_date == fd and peo and (not r.b_open_h)):
            taken.append(r); fd, peo = r.exit_date, r.eo
    return pd.DataFrame(taken)
for op_lo, op_hi in [(-0.065, 0.045), (-0.04, 0.045), (-0.065, 0.03), (-0.03, 0.03), (0.0, 0.045)]:
    for lockmin in [0, 40, 45, 50]:
        for kr in [True, False]:
            L = run_gold_relax(88, op_lo, op_hi, lockmin, kr)
            line(f"金:开盘{op_lo}至{op_hi} 锁仓{lockmin} 监管{'留' if kr else '放'}", L, None)
            gw = L[L.is_gold]; a = met(gw)
            print(f"      其中黄金期 {a['n']}笔 WR{a['wr']} PLR{a['plr']} {a['nav']}x MDD{a['mdd']}")
best = res[0]
best[6].to_csv(f"{D}/v7_soft_best_ledger.csv", index=False)
print("BEST", best[2], best[3], best[4], best[5])

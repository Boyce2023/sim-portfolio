#!/opt/homebrew/bin/python3.13
# 高标首阴 V5.1 刷题机数据构建：复现42笔账本，生成50题标准卷与5关挑战赛 JSON
import json, numpy as np, pandas as pd
D = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/sandbox_lab/golden_regime_20261113"
OUT = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/trainer_high_v51"
src = "\n".join(open(f"{D}/sub2_03_golden_relaxation_backtest.py").read().splitlines()[:192])
src = src.replace('r["d1_to"] > 38.0', 'r["d1_to"] > 35.0')
G = {"__name__": "eng"}; exec(src, G)
dfr, sim_trade, run_sim, code_bars, CSI = G["dfr"], G["sim_trade"], G["run_simulation"], G["code_bars"], G["CSI_MAP"]
L = run_sim(88, 88, "morn_cond", "S_hold_d3", extra_hold=False, cb=True)
nav = float(np.prod(1 + L.net_ret.values)); wr = (L.net_ret > 0).mean() * 100
assert len(L) == 42 and abs(nav - 16.39) < 0.02, (len(L), nav)
print(f"账本复现: {len(L)}笔 胜率{wr:.1f}% 单仓{nav:.2f}倍")
L.to_csv(f"{OUT}/v51_ledger_42.csv", index=False)
WD = "一二三四五六日"

def pct(x): return ("涨" if x >= 0 else "跌") + f"{abs(x)*100:.1f}%"

def reason(r):
    if r.s_reg or r.tox: return "个股有监管函或减持立案公告，一票否决"
    if r.ex_reg5 >= 2: return "近5日本交易所密集发监管函，一票否决"
    if r.d1_to > 35.0: return f"断板日换手{r.d1_to:.0f}%超过35%，一票否决"
    if r.lh1 >= 3: return "断板日龙虎榜拉萨散户席位满3家，一票否决"
    if r.op2 > 0.045: return f"竞价{pct(r.op2)}超过4.5%追高上限，不买"
    if r.op2 < -0.065: return f"竞价{pct(r.op2)}深水核按钮，不买"
    return f"综合打分{r.sc5_1:.0f}分" + ("，达到88分及格线" if r.sc5_1 >= 88 else "，没到88分及格线")

def kl(c6, d, n=25):
    b = code_bars[c6]; p = b["p"][d]; s = max(0, p - n)
    rows = [[round(float(b[k][i]), 2) for k in ("open", "high", "low", "close")] for i in range(s, p)]
    rows.append([round(float(b["open"][p]), 2)] * 4)  # 买入日只露开盘价
    return rows

def cand(r, opt):
    x = sim_trade(r, "morn_cond", "S_hold_d3")
    lockfree = max(r.lock, 0)
    return {"opt": opt, "code": r.code, "name": r.name, "height": int(r.st0), "d1": pct(r.d1_pct),
            "d1_open": pct(r.d1_op), "turn": f"{r.d1_to:.1f}%", "lock": f"{lockfree:.0f}%", "fmcap": f"{r.fmcap:.0f}亿",
            "auction": pct(r.op2), "reg": bool(r.s_reg or r.tox or r.ex_reg5 >= 2), "lhasa": int(r.lh1),
            "score": int(r.sc5_1) if r.sc5_1 > -900 else None, "why": reason(r), "klines": kl(r.code, r.buy_date),
            "filled": x is not None,
            "ret": round(x["net_ret"] * 100, 2) if x else 0.0,
            "exit": (f"{x['exit_date']} 卖出" if x else "当天没触发买点，未成交")}

held = set()
for t in L.itertuples():
    for d in [dd for dd in G["all_dts"] if t.buy_date <= dd <= t.exit_date]: held.add(d)
lmap = {t.buy_date: t for t in L.itertuples()}
qs = []
for d, g in dfr.groupby("buy_date"):
    if d in held and d not in lmap: continue
    opts = [cand(r, "ABC"[i]) for i, r in enumerate(g.sort_values("sc5_1", ascending=False).itertuples())]
    t = lmap.get(d)
    ans = next((o["opt"] for o in opts if t is not None and o["code"] == t.code), "空仓")
    if t is not None:
        for o in opts:
            if o["code"] == t.code: o["ret"] = round(t.net_ret * 100, 2); o["exit"] = f"{t.exit_date} 卖出"
    r0 = g.iloc[0]
    wdn = WD[pd.Timestamp(d).weekday()]
    qs.append({"date": d, "title": f"{d} 周{wdn}", "n_zt": int(r0.n_zt), "max_b": int(r0.max_b_d1), "csi5": pct(r0.csi5),
               "cands": opts, "ans": ans, "sys_ret": round(t.net_ret * 100, 2) if t is not None else 0.0,
               "worst": min(o["ret"] for o in opts), "multi": len(opts) > 1,
               "near": max((o["score"] or 0) for o in opts)})
buy = [q for q in qs if q["ans"] != "空仓"]
emp = sorted([q for q in qs if q["ans"] == "空仓" and (q["near"] < 88 or any(o["reg"] or "否决" in o["why"] or "不买" in o["why"] for o in q["cands"]))], key=lambda q: q["worst"])[:8]
pack = sorted(buy + emp, key=lambda q: q["date"])
assert len(buy) == 42 and len(pack) == 50
for i, q in enumerate(pack): q["id"] = i + 1
hard = sorted(pack, key=lambda q: (q["multi"], -abs(q["near"] - 88) if q["near"] else -99, abs(q["sys_ret"] or q["worst"])), reverse=True)[:5]
chal = [dict(q) for q in sorted(hard, key=lambda q: q["date"])]
for i, q in enumerate(chal): q["id"] = i + 1
json.dump(pack, open(f"{OUT}/high_pack50.json", "w"), ensure_ascii=False)
json.dump(chal, open(f"{OUT}/high_chal5.json", "w"), ensure_ascii=False)
print("买入题", len(buy), "空仓题", len(emp), "挑战题日期", [q["date"] for q in chal])
print("空仓题候选实际收益", [q["worst"] for q in emp])

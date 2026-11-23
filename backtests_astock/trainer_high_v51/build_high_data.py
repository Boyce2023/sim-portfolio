#!/opt/homebrew/bin/python3.13
# 高标首阴 V5.1 刷题机数据构建：直接对齐 V19.1 洁净真账 ledger_high_v51_clean.csv (42笔/71.43%/盈亏比2.83/14.75倍)，生成50题标准卷与5关挑战赛 JSON
import os, sys, json, numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
SIM_DIR = os.path.dirname(os.path.dirname(HERE))
A2_ASSETS = os.path.join(SIM_DIR, "backtests_astock2", "assets")
if A2_ASSETS not in sys.path:
    sys.path.insert(0, A2_ASSETS)

from v191_dt_defer_helper import load_dt_defer_tables, defer_eod_limit_down, calc_adj_net_ret

D = f"{SIM_DIR}/backtests_astock/sandbox_lab/golden_regime_20261113"
OUT = f"{SIM_DIR}/backtests_astock/trainer_high_v51"
CLEAN_LEDGER_CSV = f"{SIM_DIR}/backtests_astock/redteam_full_audit_20261123/partC_clean_ledgers_v191/ledger_high_v51_clean.csv"

src = "\n".join(open(f"{D}/sub2_03_golden_relaxation_backtest.py").read().splitlines()[:192])
src = src.replace('r["d1_to"] > 38.0', 'r["d1_to"] > 35.0')
G = {"__name__": "eng"}; exec(src, G)
dfr, sim_trade, code_bars, CSI = G["dfr"], G["sim_trade"], G["code_bars"], G["CSI_MAP"]
get_double_dev_px, SH_MAP, SZ_MAP = G["get_double_dev_px"], G["SH_MAP"], G["SZ_MAP"]

L = pd.read_csv(CLEAN_LEDGER_CSV, dtype={"code": str})
L["c6"] = L["code"].astype(str).str.zfill(6)
nav = float(np.prod(1 + L.net_ret.values)); wr = (L.net_ret > 0).mean() * 100
assert len(L) == 42 and abs(nav - 14.75) < 0.02, (len(L), nav)
print(f"V19.1洁净账本载入: {len(L)}笔 胜率{wr:.2f}% 单仓{nav:.2f}倍")

dt_tables = load_dt_defer_tables()
WD = "一二三四五六日"


def pct(x): return "0.0%" if abs(x) * 100 < 0.05 else f"{x * 100:+.1f}%"


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


def _sim_clean_non_ledger(r):
    x = sim_trade(r, "morn_cond", "S_hold_d3")
    if x is None:
        return None
    c6 = str(r.code).zfill(6)
    bd = str(r.buy_date)
    b = code_bars[c6]
    d2p = b["p"][bd]
    ep = b["p"][x["exit_date"]]
    b_op = float(b["open"][d2p])
    bpx = b_op if x["b_open_h"] else round(b_op * 1.015, 2)
    if not x["b_open_h"]:
        df_k = G["get_df_k"](c6, bd)
        sub_m = df_k[(df_k["date"] == bd) & (df_k["hhmm"] <= "11:30")] if not df_k.empty else pd.DataFrame()
        if not sub_m.empty:
            bpx = float(sub_m.iloc[0]["open"]) if float(sub_m.iloc[0]["open"]) >= bpx else bpx

    if x["eo"]:
        ehh = 925
        epx = float(b["open"][ep])
    else:
        sealed_b = bool(b["is_zt"][d2p])
        chained_zt = (not sealed_b) and (ep > d2p + 1) and any(bool(b["is_zt"][mid]) for mid in range(d2p + 1, ep))
        imap = SH_MAP if c6.startswith("60") else SZ_MAP
        pl = get_double_dev_px(b, ep, imap, 0.07) if (sealed_b or chained_zt) else 99999.0
        if pl < 99990.0 and float(b["high"][ep]) >= pl:
            ehh = 1030
            epx = float(pl)
        else:
            ehh = 1500
            epx = float(b["close"][ep])

    adj_nr = calc_adj_net_ret(c6, bd, bpx, x["exit_date"], epx, dt_tables, 0.0020)
    nr = adj_nr if adj_nr is not None else float(x["net_ret"])
    ned, neh, nep, nret, dt_def = defer_eod_limit_down(c6, bd, bpx, x["exit_date"], ehh, epx, nr, dt_tables, 0.0020)
    exit_str = f"{ned} 09:25开盘卖出（前日15:00封死跌停顺延）" if dt_def else (f"{ned} 09:25开盘卖出" if neh == 925 else f"{ned} 卖出")
    return {"exit_date": ned, "exit_hhmm": neh, "exit_price": nep, "net_ret": nret, "exit_str": exit_str, "dt_deferred": dt_def}


def cand(r, opt, lrow=None):
    c6 = str(r.code).zfill(6)
    lockfree = max(r.lock, 0)
    cx = _sim_clean_non_ledger(r)
    if lrow is not None:
        filled = True
        ret_pct = round(float(lrow.net_ret) * 100, 2)
        ehh = int(lrow.exit_hhmm)
        dt_def = bool(ehh == 925 and cx is not None and cx["dt_deferred"])
        if dt_def:
            exit_str = f"{lrow.exit_date} 09:25开盘卖出（前日15:00封死跌停顺延）"
        elif ehh == 925:
            exit_str = f"{lrow.exit_date} 09:25开盘卖出"
        elif 930 <= ehh < 1500:
            exit_str = f"{lrow.exit_date} {ehh//100:02d}:{ehh%100:02d}触发93%异动止盈卖出"
        else:
            exit_str = f"{lrow.exit_date} 卖出"
    elif cx is not None:
        filled = True
        ret_pct = round(float(cx["net_ret"]) * 100, 2)
        exit_str = cx["exit_str"]
    else:
        filled = False
        ret_pct = 0.0
        exit_str = "当天没触发买点，未成交"

    return {
        "opt": opt, "code": c6, "name": r.name, "height": int(r.st0), "d1": pct(r.d1_pct),
        "d1_open": pct(r.d1_op), "turn": f"{r.d1_to:.1f}%", "lock": f"{lockfree:.0f}%", "fmcap": f"{r.fmcap:.0f}亿",
        "auction": pct(r.op2), "reg": bool(r.s_reg or r.tox or r.ex_reg5 >= 2), "lhasa": int(r.lh1),
        "score": int(r.sc5_1) if r.sc5_1 > -900 else None, "why": reason(r), "klines": kl(c6, r.buy_date),
        "filled": filled, "ret": ret_pct, "exit": exit_str,
    }


held = set()
for t in L.itertuples():
    for d in [dd for dd in G["all_dts"] if t.buy_date <= dd <= t.exit_date]:
        held.add(d)
lmap = {(t.buy_date, t.c6): t for t in L.itertuples()}
lby_d = {t.buy_date: t for t in L.itertuples()}

qs = []
for d, g in dfr.groupby("buy_date"):
    if d in held and d not in lby_d:
        continue
    t = lby_d.get(d)
    opts = []
    for i, r in enumerate(g.sort_values("sc5_1", ascending=False).itertuples()):
        c6 = str(r.code).zfill(6)
        opts.append(cand(r, "ABC"[i], lmap.get((d, c6))))
    ans = next((o["opt"] for o in opts if t is not None and o["code"] == t.c6), "空仓")
    r0 = g.iloc[0]
    wdn = WD[pd.Timestamp(d).weekday()]
    qs.append({
        "date": d, "title": f"{d} 周{wdn}", "n_zt": int(r0.n_zt), "max_b": int(r0.max_b_d1), "csi5": pct(r0.csi5),
        "cands": opts, "ans": ans, "sys_ret": round(float(t.net_ret) * 100, 2) if t is not None else 0.0,
        "worst": min(o["ret"] for o in opts), "multi": len(opts) > 1,
        "near": max((o["score"] or 0) for o in opts),
    })

buy = [q for q in qs if q["ans"] != "空仓"]
emp = sorted([q for q in qs if q["ans"] == "空仓" and (q["near"] < 88 or any(o["reg"] or "否决" in o["why"] or "不买" in o["why"] for o in q["cands"]))], key=lambda q: q["worst"])[:8]
pack = sorted(buy + emp, key=lambda q: q["date"])
assert len(buy) == 42 and len(pack) == 50, (len(buy), len(emp), len(pack))
for i, q in enumerate(pack):
    q["id"] = i + 1
hard = sorted(pack, key=lambda q: (q["multi"], -abs(q["near"] - 88) if q["near"] else -99, abs(q["sys_ret"] or q["worst"])), reverse=True)[:5]
chal = [dict(q) for q in sorted(hard, key=lambda q: q["date"])]
for i, q in enumerate(chal):
    q["id"] = i + 1
json.dump(pack, open(f"{OUT}/high_pack50.json", "w", encoding="utf-8"), ensure_ascii=False)
json.dump(chal, open(f"{OUT}/high_chal5.json", "w", encoding="utf-8"), ensure_ascii=False)
print("买入题", len(buy), "空仓题", len(emp), "挑战题日期", [q["date"] for q in chal])
print("空仓题候选实际收益", [q["worst"] for q in emp])

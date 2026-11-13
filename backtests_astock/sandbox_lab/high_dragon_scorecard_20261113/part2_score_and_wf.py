#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""高标首阴反包百分制打分卡最终定版核验（去重1日/3日龙虎榜+真实KPL同题材+绿盘向上1.5%点火+良性五板特殊模块M3+Walk-Forward）"""
import json, pickle, re, time
from collections import defaultdict
import numpy as np
import pandas as pd
from scipy.stats import norm

ROOT = "/Users/huaichuaibeimeng/claude-projects"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113"
FEE = 0.0020

(all_dts, dt_to_idx, by_dt, code_bars, env_stats, holders, t_lookup, _, _, _, stock_reg, ex_reg, tox_dates, CSI_MAP, SH_MAP, SZ_MAP) = pickle.load(open(f"{OUT_DIR}/part1_cache.pkl", "rb"))
dfr = pd.read_pickle(f"{OUT_DIR}/dfr_pit.pkl")

# 1. 去重 1日榜与3日榜重复席位 (按 dt, c6, 营业部名称 去重取单日真实席位数)
Q_RE = re.compile(r"(?:华鑫.*上海分公司|国际金融.*上海分公司|中信.*上海分公司|高盛|瑞银|开源.*西安西大街|国泰君安.*总部|摩根大通)")
lb = pd.read_parquet(f"{ROOT}/sim-portfolio/backtest/2026-10-20-lhasa/lhb_buy.parquet", columns=["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME", "BUY"])
lb["dt"], lb["c6"] = lb["TRADE_DATE"].astype(str).str[:10], lb["SECURITY_CODE"].astype(str).str[:6]
g_seat = lb[lb["dt"] >= "2021-10-01"].groupby(["dt", "c6", "OPERATEDEPT_NAME"], as_index=False)["BUY"].min()
lhb_clean = {}
for (d, c), gl in g_seat.groupby(["dt", "c6"]):
    tb = float(gl["BUY"].sum()); ns = gl["OPERATEDEPT_NAME"].astype(str); lm = ns.str.contains("拉萨", na=False)
    lhb_clean[(d, c)] = (int(lm.sum()), float(gl.loc[lm, "BUY"].sum()) / tb if tb > 0 else 0.0, int(ns.str.contains(Q_RE, na=False).sum()), int(ns.str.contains("机构专用", na=False).sum()))

# 2. 解析真实 KPL 板块涨停梯队
plate_cnt, stock_pls = defaultdict(dict), defaultdict(list)
SKIP_PLS = {"ST板块", "昨日涨停", "昨日连板", "融资融券", "深股通", "沪股通", "百元股", "高股息", "破净股", "央企国企改革", "国企改革"}
for line in open(f"{ROOT}/sim-portfolio/data/kpl_plates_5y_2021_2026_complete.jsonl"):
    if not line.strip(): continue
    o = json.loads(line); d = str(o.get("date", ""))[:10]
    if d < "2021-12-20": continue
    for po in o.get("plates", []):
        pn = str(po.get("plate", ""))
        if not pn or pn in SKIP_PLS: continue
        stks = po.get("stocks", [])
        plate_cnt[d][pn] = sum(1 for s in stks if str(s[0])[:6].startswith(("00", "60")))
        for s in stks: stock_pls[(d, str(s[0])[:6])].append(pn)

# 3. 绿盘向上 +1.5% 点火右侧确认 (b_op * 1.015) + 重挂去重龙虎榜与KPL同题材
from eval_scorecard_final import sim_exit_e2
lh0_l, lh1_l, sh1_l, q0_l, in1_l, pp_l, ign_ok_l, hyb_l = [], [], [], [], [], [], [], []
for r in dfr.itertuples():
    a0, a1 = lhb_clean.get((r.d0, r.code), (0,0.0,0,0)), lhb_clean.get((r.d1, r.code), (0,0.0,0,0))
    lh0_l.append(a0[0]); lh1_l.append(a1[0]); sh1_l.append(a1[1]); q0_l.append(a0[2]); in1_l.append(a1[3])
    pp_l.append(max([plate_cnt.get(r.d1, {}).get(p, 0) for p in stock_pls.get((r.d0, r.code), [])], default=0))
    bars = code_bars[r.code]; d2p = bars["p"][r.buy_date]; b_op = float(bars["open"][d2p])
    imap = SH_MAP if r.ex == "SH" else SZ_MAP
    if r.op2 < 0.0:
        ipx = b_op * 1.015
        if float(bars["high"][d2p]) >= ipx and ipx < float(bars["zt_px"][d2p]) - 0.011:
            ign_ok_l.append(True); hyb_l.append(sim_exit_e2(bars, d2p, ipx, imap, True, True))
        else:
            ign_ok_l.append(False); hyb_l.append(None)
    else:
        ign_ok_l.append(True); hyb_l.append(sim_exit_e2(bars, d2p, b_op, imap, True, True))

dfr["lh0"], dfr["lh1"], dfr["lh_sh1"], dfr["q0"], dfr["in1"], dfr["p_peers"], dfr["can_ign"], dfr["hyb_sm"] = lh0_l, lh1_l, sh1_l, q0_l, in1_l, pp_l, ign_ok_l, hyb_l
dfr["b_open_h"] = dfr["op2"] >= 0.0

def score_100(r):
    if r["s_reg"] or r["tox"]: return -999, "VETO_个股监管或减持立案"
    if r["ex_reg5"] >= 2: return -999, "VETO_本交易所密集发函"
    if r["b3_dt"] >= 2 and r["brk_r10"] > 0.30: return -999, "VETO_高标批量跌停退潮"
    if r["d1_to"] > 38.0: return -999, "VETO_天量换手超38%"
    if r["lh1"] >= 3 or r["lh_sh1"] > 0.25: return -999, "VETO_拉萨散户席位>=3家"
    if r["op2"] > 0.050 or r["op2"] < -0.060: return -999, "VETO_开盘超5%追高或深水核按钮"
    sc = 60
    if r["lh0"] == 0 and r["lh1"] == 0: sc += 12
    elif r["lh1"] == 1: sc += 5
    elif r["lh1"] == 2: sc -= 12
    if r["in1"] >= 1: sc -= 8
    if r["q0"] >= 1: sc += 4
    if r["lock"] >= 48.0 and 15.0 <= r["fmcap"] <= 80.0: sc += 6
    if r["pool"] == "PoolA": sc += 5
    if r["d0_tight"] >= 35.0: sc += 7
    elif r["d0_tight"] < 20.0: sc -= 7
    if r["d1_op"] < 0.0: sc += 6
    if r["d1_to"] <= 32.0: sc += 6
    elif r["d1_to"] > 35.0: sc -= 8
    if r["d1_body"] >= 0.03: sc += 3
    if r["p_peers"] <= 2: sc += 6
    elif r["p_peers"] >= 3 and r["c_peers"] >= 2: sc -= 8
    if r["dom"]: sc -= 6
    if r["b3_dt"] == 0 and r["brk_r10"] <= 0.25: sc += 5
    if r["csi_r20"] < -0.05: sc -= 6
    if r["mbg"] <= 90: sc += 3
    op = r["op2"]
    if 0.0 <= op <= 0.025: sc += 12
    elif -0.025 <= op < 0.0: sc += 6
    elif 0.025 < op <= 0.050: sc += 0
    else: sc -= 6
    return sc, "OK"

dfr["score"], dfr["reason"] = zip(*[score_100(row) for _, row in dfr.iterrows()])

def build_rows(sub, mode="hyb_sm"):
    rows = []
    for r in sub.itertuples():
        if mode == "hyb_sm":
            if not r.can_ign or r.hyb_sm is None: continue
            ed, ret, hb, eo = r.hyb_sm; bo = r.b_open_h
        else:
            ed, ret, hb, eo = getattr(r, mode); bo = True
        rows.append({"buy_date": r.buy_date, "exit_date": ed, "code": r.code, "name": r.name, "score": r.score, "net_ret": ret, "hold_bars": hb, "buy_at_open": bo, "exit_at_open": eo, "pool": r.pool})
    return pd.DataFrame(rows)

def eval_tdf(tdf, s_dt="2022-01-04", e_dt="2026-11-12"):
    span = [d for d in all_dts if s_dt <= d <= e_dt]
    b0 = max([k for k in CSI_MAP if k < span[0]], default=span[0])
    csi_r = float(CSI_MAP[span[-1]] / CSI_MAP[b0] - 1.0)
    w = tdf[(tdf["buy_date"] >= s_dt) & (tdf["buy_date"] <= e_dt)].sort_values(["buy_date", "score"], ascending=[True, False]) if not tdf.empty else pd.DataFrame()
    if w.empty: return {"n":0,"wr":0,"plr":0,"nav":1.0,"ew":1.0,"top5":1.0,"mdd":0,"csi":csi_r,"exc":-csi_r,"sh":0,"led":pd.DataFrame()}
    ew = float((1.0 + w.groupby("buy_date")["net_ret"].mean()).prod())
    taken, f_dt, p_eo, nav, pk, mdd = [], "", False, 1.0, 1.0, 0.0
    for r in w.itertuples(index=False):
        if (f_dt == "") or (r.buy_date > f_dt) or (r.buy_date == f_dt and p_eo and (not r.buy_at_open)):
            taken.append(r); f_dt = r.exit_date; p_eo = r.exit_at_open
            nav *= (1.0 + r.net_ret); pk = max(pk, nav); mdd = max(mdd, (pk - nav) / pk)
    led = pd.DataFrame(taken); rets = led["net_ret"].values
    wr = float(np.mean(rets > 0)); pos, neg = rets[rets > 0], np.abs(rets[rets <= 0])
    plr = float(np.mean(pos) / np.mean(neg)) if (len(pos) > 0 and len(neg) > 0) else 99.0
    sr = np.sort(rets); top5 = float(np.prod(1.0 + (sr[:-5] if len(sr) > 5 else np.array([0.0]))))
    drm = defaultdict(float)
    for r in taken: drm[r.buy_date] += r.net_ret
    dr = np.array([drm[d] for d in span])
    sh = float(np.mean(dr) / (np.std(dr) + 1e-9) * np.sqrt(250))
    return {"n":len(led),"wr":wr,"plr":plr,"nav":nav,"ew":ew,"top5":top5,"mdd":mdd,"csi":csi_r,"exc":(nav-1.0)-csi_r,"sh":sh,"led":led}

df_1a = pd.read_parquet(f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/verified_1a_5ban_cands.parquet")
df_1a["c6"] = df_1a["code"].astype(str).str.zfill(6)
f1a = df_1a[(df_1a["open_pct"] <= 0.055) & (df_1a["lock_top10"] >= 50.0)].sort_values(["buy_date", "lock_top10"], ascending=[True, False]).reset_index(drop=True)
closed_5b, rows_5b = [], []
for r in f1a.itertuples(index=False):
    past = [x for x in closed_5b if x[0] < r.buy_date]
    closed_5b.append((str(r.ed_d4_93)[:10], float(r.ret_d4_93)))
    if len(past) < 4: continue
    l4 = [x[1] for x in past[-4:]]
    ex = "SH" if r.c6.startswith("60") else "SZ"
    i_sig = dt_to_idx.get(str(r.sig_date)[:10], 5); w5 = all_dts[max(0, i_sig - 5)]
    ex_cnt = sum(1 for x in ex_reg[ex] if w5 <= x <= str(r.sig_date)[:10])
    s_tox = any(0 <= (pd.Timestamp(str(r.sig_date)[:10]) - pd.Timestamp(x)).days <= 10 for x in (tox_dates.get(r.c6, []) + stock_reg.get(r.c6, [])))
    if (sum(v > 0 for v in l4) / 4.0 >= 0.60) and (np.mean(l4) >= 0.04) and (r.prev_break_dt_rate_10d <= 0.30) and (not (-0.035 <= r.open_pct <= 0.010)) and (r.lhasa_seats_prev <= 1) and ex_cnt == 0 and (not s_tox):
        rows_5b.append({"buy_date": str(r.buy_date)[:10], "exit_date": str(r.ed_d4_93)[:10], "code": r.c6, "name": str(r.name), "score": 95, "net_ret": float(r.ret_d4_93), "hold_bars": int(r.hb_d4_93), "buy_at_open": True, "exit_at_open": bool(r.eo_d4_93), "pool": "Special5B"})
tdf_5b = pd.DataFrame(rows_5b)

wins = [("五年全量(22-26)", "2022-01-04", "2026-11-12"), ("训练集IS(22-24)", "2022-01-04", "2024-12-31"), ("纯样本外OOS(25-26)", "2025-01-02", "2026-11-12"), ("近三年(24-26)", "2024-01-02", "2026-11-12"), ("去2025四年", "NO25", "NO25"), ("2026年7月以来", "2026-07-01", "2026-11-12")]
models = [
    ("0_无打分原版基准", build_rows(dfr[(dfr["d1_to"]<=35.0)&(dfr["op2"]>=-0.05)&(dfr["op2"]<=0.05)], "auc_e2")),
    ("1_纯首阴打分主力版 M2_Ign (>=80 点火+智能按天卖)", build_rows(dfr[dfr["score"]>=80], "hyb_sm")),
    ("2_纯首阴打分竞价版 M2_Auc (>=80 竞价+智能按天卖)", build_rows(dfr[dfr["score"]>=80], "auc_sm")),
    ("3_首阴打分+良性五板双模单仓 M3_Ign (>=80 点火合成)", pd.concat([build_rows(dfr[dfr["score"]>=80], "hyb_sm"), tdf_5b], ignore_index=True)),
    ("4_首阴打分+良性五板双模单仓 M3_Auc (>=80 竞价合成)", pd.concat([build_rows(dfr[dfr["score"]>=80], "auc_sm"), tdf_5b], ignore_index=True)),
]
md_lines = ["# 高标首阴反包百分制打分卡与五年单仓轮动核验总表（2022-01-04 至 2026-11-12）\n"]
for nm, t_in in models:
    print(f"\n>>> {nm}"); md_lines.append(f"\n## {nm}\n")
    for wl, ws, we in wins:
        r = eval_tdf(t_in[(t_in["buy_date"]<"2025-01-01")|(t_in["buy_date"]>="2026-01-01")]) if ws=="NO25" else eval_tdf(t_in, ws, we)
        ln = f"  {wl:18s} | n={r['n']:2d} | WR={r['wr']*100:5.1f}% | PLR={r['plr']:4.2f} | 单仓={r['nav']:6.2f}x | 日等权={r['ew']:6.2f}x | 去Top5={r['top5']:5.2f}x | MDD={r['mdd']*100:4.1f}% | 沪深300={r['csi']*100:+5.1f}% | 净超额={r['exc']*100:+7.1f}%"
        print(ln); md_lines.append(f"- {ln.strip()}")
    yrs = [f"{y}:{eval_tdf(t_in, f'{y}-01-01', f'{y}-12-31')['nav']:.2f}x({eval_tdf(t_in, f'{y}-01-01', f'{y}-12-31')['n']}笔,WR{eval_tdf(t_in, f'{y}-01-01', f'{y}-12-31')['wr']*100:.0f}%)" for y in ["2022","2023","2024","2025","2026"]]
    print("  逐年:", " | ".join(yrs)); md_lines.append("- 逐年单仓: " + " | ".join(yrs))
    eval_tdf(t_in)["led"].to_csv(f"{OUT_DIR}/final_{nm[0]}_ledger.csv", index=False)

open(f"{OUT_DIR}/FINAL_SCORECARD_REPORT.md", "w").write("\n".join(md_lines) + "\n")

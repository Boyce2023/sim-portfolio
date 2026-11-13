#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""高标首阴反包百分制打分卡评测与样本外 Walk-Forward 审计引擎"""
import os, json, time, pickle
from collections import defaultdict
import numpy as np
import pandas as pd
from scipy.stats import norm

t0 = time.time()
OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113"
FEE = 0.0020
(all_dts, dt_to_idx, by_dt, code_bars, env_stats, holders, t_lookup, plate_zt, stock_pls, lhb, stock_reg, ex_reg, tox_dates, CSI_MAP, SH_MAP, SZ_MAP) = pickle.load(open(f"{OUT_DIR}/part1_cache.pkl", "rb"))
get_lock = lambda c6, d: float(max([r for r in holders.get(c6, []) if r[0] < d], key=lambda x: x[1])[2]) if any(r[0] < d for r in holders.get(c6, [])) else 38.0

def get_dev_px(bars, cp, idx_map, disc=0.07):
    cd = bars["dts"][cp]; ir = idx_map.get(cd)
    if not ir: return 99999.0
    bp_min = 99999.0
    for k in range(1, min(11, cp + 1)):
        p = cp - k; bi = idx_map.get(bars["dts"][p]); bc = bars["close"][p]
        if bi and bc > 0:
            pl = bc * (1.0 + (1.0 - disc) + (ir / bi - 1.0))
            if pl < bp_min: bp_min = pl
    return bp_min

def sim_exit_e2(bars, d2_p, buy_px, idx_map, smart_bounce=False, yang_immune=False):
    d2_zt = bool(bars["is_zt"][d2_p])
    d2_c_ret = bars["close"][d2_p] / buy_px - 1.0
    n = len(bars["dts"])
    ep, epx, eo = None, None, False
    if d2_zt:
        imm = False
        for step in range(1, 8):
            p = d2_p + step
            if p >= n: break
            pl = get_dev_px(bars, p, idx_map, 0.07)
            if bars["open"][p] >= pl: ep, epx, eo = p, bars["open"][p], True; break
            elif bars["high"][p] >= pl: ep, epx, eo = p, pl, False; break
            if not bars["is_zt"][p]:
                if yang_immune and (not imm) and (bars["close"][p] > bars["open"][p]):
                    imm = True; continue
                while p < n - 1 and bars["is_yizi_dt"][p]: p += 1
                ep, epx, eo = p, bars["close"][p], False; break
    else:
        p = min(d2_p + 1, n - 1)
        if smart_bounce and d2_c_ret <= -0.04 and (not bars["is_yizi_dt"][p]):
            bt = bars["pre_c"][p] * 1.015
            if bars["open"][p] >= bt: ep, epx, eo = p, bars["open"][p], True
            elif bars["high"][p] >= bt: ep, epx, eo = p, bt, False
        if ep is None:
            while p < n - 1 and bars["is_yizi_dt"][p]: p += 1
            ep, epx, eo = p, bars["close"][p], False
    if ep is None:
        ep = min(d2_p + 5, n - 1); epx, eo = bars["close"][ep], False
    ret = (epx * bars["adjf"][ep]) / (buy_px * bars["adjf"][d2_p]) * (1.0 - FEE) - 1.0
    return bars["dts"][ep], float(ret), max(1, ep - d2_p), eo

eval_dts = [d for d in all_dts if "2022-01-04" <= d <= "2026-11-12"]
recs = []
for d1 in eval_dts:
    i1 = dt_to_idx[d1]; d0 = all_dts[i1 - 1]
    g0, g1 = by_dt[d0], by_dt[d1]; zt0 = g0[g0["is_zt"]]
    if zt0.empty or int(zt0["streak"].max()) < 4: continue
    mb = int(zt0["streak"].max()); top0 = zt0[zt0["streak"] == mb]
    tgts = [(r.c6, "PoolA", int(r.streak), int(r.yz_streak)) for r in top0.itertuples()] if len(top0) <= 2 else []
    if all(top0["yz_streak"] >= 3):
        tz = zt0[(zt0["streak"] < mb) & (zt0["streak"] >= 4) & (zt0["yz_streak"] < 3)]
        if not tz.empty:
            sm = int(tz["streak"].max()); stp = tz[tz["streak"] == sm]
            if len(stp) <= 2: tgts += [(r.c6, "PoolB", int(r.streak), int(r.yz_streak)) for r in stp.itertuples()]
    g1i = g1.set_index("c6")
    for c6, ptag, st0, yz0 in tgts:
        if c6 not in g1i.index: continue
        r1 = g1i.loc[c6]
        if bool(r1["is_zt"]) or not (float(r1["close"]) > float(r1["open"])): continue
        bars = code_bars[c6]; d1p = bars["p"][d1]; d2p = d1p + 1
        if d2p >= len(bars["dts"]) or bars["is_yizi"][d2p]: continue
        b_op = float(bars["open"][d2p])
        if b_op <= float(bars["dt_px"][d2p]) + 0.011 or b_op <= 0: continue
        d2, op2 = bars["dts"][d2p], float(bars["o_pct"][d2p])
        ex = "SH" if c6.startswith("60") else "SZ"; imap = SH_MAP if ex == "SH" else SZ_MAP
        ign_px = max(b_op * 1.015, float(bars["pre_c"][d2p]) * 1.000)
        can_ign, eff_px, b_open_h = True, b_op, True
        if op2 < 0.0:
            if float(bars["high"][d2p]) >= ign_px and ign_px < float(bars["zt_px"][d2p]) - 0.011:
                eff_px, b_open_h = ign_px, False
            else: can_ign = False
        lh0, lh1 = lhb.get((d0, c6), (0, 0.0, 0, 0)), lhb.get((d1, c6), (0, 0.0, 0, 0))
        d1_ts = pd.Timestamp(d1); w5 = all_dts[max(0, i1 - 5)]
        pls0 = stock_pls.get((d0, c6), [])
        dom, mbg = t_lookup.get((d1, c6), (False, 999))
        lk = get_lock(c6, d1); env1 = env_stats[d1]
        recs.append({
            "d0": d0, "d1": d1, "buy_date": d2, "code": c6, "name": str(r1["name"]), "ex": ex, "pool": ptag, "st0": st0,
            "d1_pct": float(r1["pct"]), "d1_op": float(r1["o_pct"]), "d1_body": float(r1["pct"] - r1["o_pct"]),
            "d1_uwick": float(r1["h_pct"] - r1["pct"]), "d1_to": float(r1["to"]), "d0_tight": float(r1["d0_tight"]), "op2": op2,
            "lh0": lh0[0], "lh1": lh1[0], "lh_sh1": lh1[1], "q0": lh0[2], "in1": lh1[3],
            "s_reg": any(0 <= (d1_ts - pd.Timestamp(x)).days <= 10 for x in stock_reg.get(c6, [])),
            "tox": any(0 <= (d1_ts - pd.Timestamp(x)).days <= 10 for x in tox_dates.get(c6, [])),
            "ex_reg5": sum(1 for x in ex_reg[ex] if w5 <= x <= d1),
            "b3_dt": env1["b3_dt"], "brk_r10": env1["brk_r10"], "csi_r20": env1["csi_r20"],
            "p_peers": max([plate_zt.get(d1, {}).get(p, 0) for p in pls0], default=0),
            "c_peers": env1["csrc_zt"].get(str(r1["csrc_ind"]), 0),
            "dom": dom, "mbg": mbg, "lock": lk, "fmcap": float(r1["mcap"]) * (1.0 - lk / 100.0),
            "can_ign": can_ign, "b_open_h": b_open_h,
            "auc_e2": sim_exit_e2(bars, d2p, b_op, imap, False, False),
            "auc_sm": sim_exit_e2(bars, d2p, b_op, imap, True, True),
            "hyb_sm": sim_exit_e2(bars, d2p, eff_px, imap, True, True) if can_ign else None,
        })

dfr = pd.DataFrame(recs)
df_is = dfr[dfr["buy_date"] < "2025-01-01"].copy()
df_is["r"] = [x[1] for x in df_is["auc_e2"]]
print(f"Total PIT PoolA+B True-Yang: {len(dfr)} (IS 2022-24: {len(df_is)}, OOS 2025-26: {len(dfr)-len(df_is)})")
for lb_n, m in [("d1_to<=35", df_is["d1_to"]<=35), ("lh1<=1 & sh<=0.15", (df_is["lh1"]<=1)&(df_is["lh_sh1"]<=0.15)), ("in1==0", df_is["in1"]==0), ("d0_tight>=35", df_is["d0_tight"]>=35), ("d1_op<0 (水下深V真阳)", df_is["d1_op"]<0), ("p_peers in 1..2", df_is["p_peers"].isin([1,2])), ("dom==False", ~df_is["dom"]), ("op2 in [0, 3%]", (df_is["op2"]>=0)&(df_is["op2"]<=0.03)), ("b3_dt<2", df_is["b3_dt"]<2), ("ex_reg5<2", df_is["ex_reg5"]<2), ("tox==False & s_reg==False", (~df_is["tox"])&(~df_is["s_reg"]))]:
    s, rst = df_is[m], df_is[~m]
    print(f"  IS {lb_n:26s}: n={len(s):2d} wr={(s['r']>0).mean()*100:5.1f}% mean={s['r'].mean()*100:+5.2f}% | rest n={len(rst):2d} wr={(rst['r']>0).mean()*100:5.1f}% mean={rst['r'].mean()*100:+5.2f}%")
dfr.to_pickle(f"{OUT_DIR}/dfr_pit.pkl")

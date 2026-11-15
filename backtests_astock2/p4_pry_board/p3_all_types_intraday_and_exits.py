#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""p3_all_types_intraday_and_exits.py: 6大撬板类型 × 5m盘中全时段 × 四态精细卖点 × V2.0打分卡总决战"""
import json, pickle, sys, numpy as np, pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
MAT_DIR = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112"
P3_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/p3_deep_100"
WORK_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/p4_pry_board"
for p in [WORK_DIR, P3_DIR, MAT_DIR]:
    if p not in sys.path: sys.path.insert(0, p)

from p1_pry_v10_scorecard import load_and_score_pry_data
from common_eval_harness import load_production_3_ledgers
from w3_portfolio_and_qa_engine import normalize_ledger
FEE = 0.0020

def sim_exit_flex(b, pos, buy_px, emode):
    n = len(b["dts"]); adj0 = b["adjf"][pos]; buy_adj = buy_px * adj0
    dts, ops, his, los, cls, adjs, pcs, dtps, izts, idts, iyzs, tos = (
        b["dts"], b["open"], b["high"], b["low"], b["close"], b["adjf"],
        b["pre_c"], b["dt_px"], b["is_zt"], b["is_dt"], b["is_yizi_dt"], b["to"]
    )
    if pos >= n - 1: return dts[pos], -FEE, 0
    c0, dt0, zt0 = cls[pos], dtps[pos], bool(izts[pos])
    reseal0 = bool(idts[pos]) or (c0 <= dt0 + 0.011)
    day0_gain = (c0 / buy_px - 1.0)
    t_step = 0
    for step in range(1, n - pos):
        idx = pos + step
        if tos[idx] <= 0 or np.isnan(tos[idx]): continue
        t_step += 1
        op, hi, lo, cl, pc, dtp, adj = ops[idx], his[idx], los[idx], cls[idx], pcs[idx], dtps[idx], adjs[idx]
        if bool(iyzs[idx]) or (pc > 0 and op == hi == lo == cl and cl / pc - 1.0 <= -0.044): continue
        op_r = (op * adj) / buy_adj - 1.0 - FEE
        cl_r = (cl * adj) / buy_adj - 1.0 - FEE
        hi_px_adj = hi * adj
        cl_dt = bool(idts[idx]) or (cl <= dtp + 0.011)
        if emode == "X1_next_open": return dts[idx], op_r, step
        if emode == "X2_next_close":
            if cl_dt: continue
            return dts[idx], cl_r, step
        if emode == "X8_t1_tp5_or_close":
            if reseal0 or t_step > 1: return dts[idx], op_r, step
            if zt0 and bool(izts[idx]): continue
            tp_adj = buy_adj * 1.05
            if op * adj >= tp_adj: return dts[idx], op_r, step
            if hi_px_adj >= tp_adj: return dts[idx], 0.05 - FEE, step
            if cl_dt: continue
            return dts[idx], cl_r, step
        if emode == "X7_state4_smart":
            if reseal0: return dts[idx], op_r, step
            if zt0:
                if bool(izts[idx]): continue
                return dts[idx], (op_r if op < pc * 0.98 else cl_r), step
            if day0_gain >= 0.03:
                if t_step == 1 and op < pc * 0.995: return dts[idx], op_r, step
                tp_adj = buy_adj * 1.07
                if op * adj >= tp_adj: return dts[idx], op_r, step
                if hi_px_adj >= tp_adj: return dts[idx], 0.07 - FEE, step
                if t_step >= 2 or not cl_dt: return dts[idx], (op_r if t_step > 2 else cl_r), step
                continue
            else:
                if t_step == 1 and op < pc * 0.985: return dts[idx], op_r, step
                tp_adj = buy_adj * 1.05
                if op * adj >= tp_adj: return dts[idx], op_r, step
                if hi_px_adj >= tp_adj: return dts[idx], 0.05 - FEE, step
                if t_step >= 2 and not cl_dt: return dts[idx], cl_r, step
                if t_step > 2: return dts[idx], op_r, step
                continue
        # Generic tp_pct, max_h, cut_reseal
        tp_p, mh, cut = {"X3_tp5_h2":(0.05,2,False),"X4_tp7_h3":(0.07,3,False),"X5_tp7_h5":(0.07,5,False),"X6_cut_tp7_h3":(0.07,3,True)}[emode]
        if cut and (reseal0 or day0_gain < -0.015): return dts[idx], op_r, step
        if t_step > mh: return dts[idx], op_r, step
        tp_adj = buy_adj * (1.0 + tp_p)
        if op * adj >= tp_adj: return dts[idx], op_r, step
        if hi_px_adj >= tp_adj: return dts[idx], tp_p - FEE, step
        if t_step == mh:
            if cl_dt: continue
            return dts[idx], cl_r, step
    return dts[-1], (cls[-1]*adjs[-1])/buy_adj - 1.0 - FEE, len(dts)-1-pos

def eval_slot1(rows):
    if not rows: return {"n":0,"wr":0,"po":0,"nav":1.0,"mdd":0,"ex3":1.0,"mean":0}
    df = pd.DataFrame(rows).sort_values(["buy_date", "prio"], ascending=[True, False])
    free = "1900-01-01"; nav = 1.0; eq = [1.0]; rets = []
    for r in df.itertuples():
        if r.buy_date <= free: continue
        nav *= (1.0 + r.ret); free = max(r.buy_date, r.exit_dt)
        eq.append(nav); rets.append(r.ret)
    r_arr = np.array(rets); w = r_arr[r_arr>0]; l = r_arr[r_arr<=0]
    po = float(w.mean()/abs(l.mean())) if len(w) and len(l) and l.mean()<0 else 9.99
    pk = np.maximum.accumulate(eq); mdd = float(np.max((pk - eq)/pk)*100)
    sr = np.sort(r_arr); ex3 = float(np.prod(1.0 + (sr[:-3] if len(sr)>3 else sr)))
    return {"n":len(rets),"wr":round(float((r_arr>0).mean()*100),1),"po":round(po,2),"nav":round(nav,3),"mdd":round(mdd,1),"ex3":round(ex3,3),"mean":round(float(r_arr.mean()*100),2)}

if __name__ == "__main__":
    with open(f"{MAT_DIR}/code_bars_5y.pkl", "rb") as f: cb = pickle.load(f)["code_bars"]
    env = pd.read_parquet(f"{MAT_DIR}/daily_env_5y.parquet").set_index("dt_str").to_dict("index")
    with open(f"{WORK_DIR}/p2_5m_bars_cache.pkl", "rb") as f: b5m = pickle.load(f)

    # 1. 5m Intraday Timing Audit (1067 real 5m touch-DT events)
    win_stats = {k: [] for k in ["09:30~10:00", "10:05~11:30", "13:05~14:15", "14:20~15:00"]}
    dive_vs_open = {"open_at_dt_pry15": [], "intraday_dive_pry15": []}
    for (c6, dt_s), arr in b5m.items():
        if dt_s < "2022-01-04" or c6 not in cb: continue
        b = cb[c6]; pos = b["date_to_pos"].get(dt_s, -1)
        if pos < 5: continue
        pc, ztp, op = float(b["pre_c"][pos]), float(b["zt_px"][pos]), float(b["open"][pos])
        if pc <= 0 or op < 2.0 or abs(ztp/pc - 1.05) < 0.015: continue
        dtp = round(pc * 0.90, 2)
        if b["low"][pos] > dtp + 0.005: continue
        trig = round(dtp * 1.015, 2)
        touched = (op <= dtp + 0.011)
        fill_px, fill_hm = None, None
        for row in arr:
            hm, bo, bh, bl = int(row[0]), float(row[1]), float(row[2]), float(row[3])
            if touched and bh >= trig and bl < ztp - 0.01:
                fill_px, fill_hm = max(bo, trig), hm; break
            if bl <= dtp + 0.008: touched = True
        if fill_px:
            ex_dt, rt, _ = sim_exit_flex(b, pos, fill_px, "X7_state4_smart")
            reseal = int(b["close"][pos] <= dtp + 0.011)
            w_key = "09:30~10:00" if fill_hm <= 1000 else ("10:05~11:30" if fill_hm <= 1130 else ("13:05~14:15" if fill_hm <= 1415 else "14:20~15:00"))
            win_stats[w_key].append((rt, reseal))
            dive_vs_open["open_at_dt_pry15" if op <= dtp + 0.011 else "intraday_dive_pry15"].append((rt, reseal))
    print("=== 1. 5M INTRADAY PRY TIMING ===")
    for k, v in {**win_stats, **dive_vs_open}.items():
        if v:
            rs = np.array([x[0] for x in v]); res_r = np.mean([x[1] for x in v])*100
            print(f"{k:22s}: n={len(v):3d}, WR={(rs>0).mean()*100:5.1f}%, Mean={rs.mean()*100:6.2f}%, ResealDT={res_r:5.1f}%")

    # 2. All 6 Types of Pry Across 10cm + 20cm (2022-2026) & Exit Matrix Duel
    df_pry, _ = load_and_score_pry_data()
    # Build 6 types on 10cm + 20cm
    type_buckets = {k: [] for k in [
        "T1_连跌2板以上纯超跌撬板", "T2_一连跌停次日纯超跌撬板", "T3_0连跌股灾冰点首跌停撬板",
        "T4_高标3板以上首核翘板", "T5_人气妖股断板回调翘板", "T6_20cm双创跌停撬板"
    ]}
    # Scan 10cm from cb (strict open<=dtp+0.011 & high>=dtp*1.015 right-side lift 1.5%)
    poison_set = set(zip(df_pry.loc[df_pry["notice_90d_poison_any"], "code"].astype(str).str.zfill(6),
                         df_pry.loc[df_pry["notice_90d_poison_any"], "buy_date"].astype(str)))
    for c6, b in cb.items():
        if not c6.startswith(("00", "60")) or c6.startswith("688"): continue
        dts, op, hi, lo, cl, pc, ztp, izt = b["dts"], b["open"], b["high"], b["low"], b["close"], b["pre_c"], b["zt_px"], b["is_zt"]
        for i in range(20, len(dts)):
            d_s = dts[i]
            if d_s < "2022-01-04" or pc[i] <= 0 or op[i] < 2.0 or abs(ztp[i]/pc[i] - 1.05) < 0.015: continue
            if (c6, d_s) in poison_set: continue
            dtp = round(float(pc[i]) * 0.90, 2)
            trig = round(dtp * 1.015, 2)
            if not (op[i] <= dtp + 0.011 and hi[i] >= trig): continue
            p_dt = 0; k = i - 1
            while k >= 0 and cl[k] <= round(float(pc[k])*0.90, 2) + 0.011: p_dt += 1; k -= 1
            p_st = 0; k = i - 1
            while k >= 0 and izt[k]: p_st += 1; k -= 1
            zt20 = int(sum(izt[i-20:i]))
            ev_prev = env.get(dts[i-1], {})
            n_dt_prev = ev_prev.get("n_dt", 0)
            ret10 = cl[i-1] / (cl[i-11] + 1e-9) - 1.0
            ex_dt, rt, _ = sim_exit_flex(b, i, trig, "X7_state4_smart")
            rec = {"buy_date": d_s, "exit_dt": ex_dt, "ret": rt, "prio": -ret10, "n_dt_prev": n_dt_prev, "pos": i, "c6": c6, "trig": trig}
            if p_dt >= 2 and zt20 == 0: type_buckets["T1_连跌2板以上纯超跌撬板"].append(rec)
            elif p_dt == 1 and zt20 == 0: type_buckets["T2_一连跌停次日纯超跌撬板"].append(rec)
            elif p_dt == 0 and zt20 == 0 and n_dt_prev >= 20: type_buckets["T3_0连跌股灾冰点首跌停撬板"].append(rec)
            elif p_st >= 3: type_buckets["T4_高标3板以上首核翘板"].append(rec)
            elif p_dt == 0 and zt20 >= 1: type_buckets["T5_人气妖股断板回调翘板"].append(rec)

    # Scan 20cm (300/301/688) from a_daily.parquet
    adf = pd.read_parquet(f"{ROOT}/sim-portfolio/data/cn_hk_price_db/a_daily.parquet", columns=["date","ticker","open","high","low","close","volume"])
    adf = adf[adf["ticker"].str.startswith(("300","301","688")) & (adf["date"] >= "2021-11-01")].sort_values(["ticker","date"])
    for tk, g in adf.groupby("ticker", sort=False):
        d_arr = g["date"].astype(str).str[:10].to_numpy()
        o_arr, h_arr, l_arr, c_arr, v_arr = g["open"].to_numpy(float), g["high"].to_numpy(float), g["low"].to_numpy(float), g["close"].to_numpy(float), g["volume"].to_numpy(float)
        for i in range(12, len(d_arr) - 3):
            if d_arr[i] < "2022-01-04" or c_arr[i-1] < 2.0 or v_arr[i] <= 0: continue
            dtp20 = round(c_arr[i-1] * 0.80, 2)
            trig20 = round(dtp20 * 1.025, 2) # 20cm跌停开盘或触及-20%拉起2.5%
            if l_arr[i] <= dtp20 + 0.015 and o_arr[i] <= c_arr[i-1] * 0.84 and h_arr[i] >= trig20:
                fill20 = max(o_arr[i], trig20) if o_arr[i] <= dtp20 + 0.015 else None
                if fill20 is None: continue
                # T+1 smart exit for 20cm
                k = i + 1
                while k < len(d_arr) - 1 and (v_arr[k] <= 0 or (o_arr[k] == h_arr[k] == l_arr[k] == c_arr[k] and c_arr[k] <= c_arr[k-1]*0.81)): k += 1
                reseal20 = c_arr[i] <= dtp20 + 0.02
                if reseal20: rt20 = o_arr[k] / fill20 - 1.0 - FEE
                elif h_arr[k] >= fill20 * 1.08: rt20 = max(o_arr[k]/fill20 - 1.0, 0.08) - FEE
                else: rt20 = c_arr[k] / fill20 - 1.0 - FEE
                ret10 = c_arr[i-1] / (c_arr[i-11] + 1e-9) - 1.0
                n_dt_p = env.get(d_arr[i-1], {}).get("n_dt", 0)
                type_buckets["T6_20cm双创跌停撬板"].append({"buy_date": d_arr[i], "exit_dt": d_arr[k], "ret": rt20, "prio": -ret10, "n_dt_prev": n_dt_p})

    print("\n=== 2. ALL 6 PRY TYPES HEAD-TO-HEAD (All Days vs Panic mkt_dt>=20) ===")
    for tk, recs in type_buckets.items():
        all_s = eval_slot1(recs)
        pan_s = eval_slot1([r for r in recs if r["n_dt_prev"] >= 20])
        print(f"{tk:24s} | 全样本: {all_s} | 冰点(跌停>=20): {pan_s}")

    # 3. 8 Exits Head-to-Head on Winning Pool (T1 + Panic or Score >= 165)
    sc_v2 = (df_pry["score_v10"].values
             + np.where(df_pry["prev_dt_streak"].values >= 2, 20, 0)
             + np.where(df_pry["csi300_ret20"].values <= -0.05, 15, 0)
             + np.where(df_pry["lock_top10"].values >= 45.0, 5, 0))
    df_pry["score_v20"] = sc_v2
    cand_v2 = df_pry[df_pry["base_valid"] & (~df_pry["notice_90d_poison_any"]) & (df_pry["score_v20"] >= 175)].copy()
    print(f"\n=== 3. 8 EXITS DUEL ON V2.0 (Score>=175, raw cands={len(cand_v2)}) ===")
    best_x7_rows = []
    for em in ["X1_next_open","X2_next_close","X3_tp5_h2","X4_tp7_h3","X5_tp7_h5","X6_cut_tp7_h3","X7_state4_smart","X8_t1_tp5_or_close"]:
        rows = []
        for r in cand_v2.itertuples():
            c6 = str(r.code).zfill(6); b = cb.get(c6)
            if not b: continue
            pos = b["date_to_pos"].get(str(r.buy_date)[:10], -1)
            if pos < 1: continue
            dtp = round(float(b["pre_c"][pos])*0.90, 2); trig = round(dtp*1.015, 2)
            if not (b["open"][pos] <= dtp + 0.011 and b["high"][pos] >= trig): continue
            ex_dt, rt, hb = sim_exit_flex(b, pos, trig, em)
            rows.append({"code":c6,"name":r.name,"buy_date":str(r.buy_date)[:10],"exit_dt":ex_dt,"ret":rt,"net_ret":rt,"prio":-float(r.ret_pre10),"score":int(r.score_v20),"hb":hb})
        s_all = eval_slot1(rows)
        s_is = eval_slot1([x for x in rows if x["buy_date"] <= "2024-12-31"])
        s_oos = eval_slot1([x for x in rows if x["buy_date"] >= "2025-01-01"])
        avg_hb = round(float(np.mean([x["hb"] for x in rows])), 2) if rows else 0
        print(f"{em:20s} | 5Y:{s_all} avgHold={avg_hb}d | IS:{s_is['nav']}x({s_is['n']}笔,{s_is['wr']}%) | OOS:{s_oos['nav']}x({s_oos['n']}笔,{s_oos['wr']}%)")
        if em == "X7_state4_smart": best_x7_rows = rows
    pd.DataFrame(best_x7_rows).to_csv(f"{WORK_DIR}/p3_v20_x7_ledger.csv", index=False, encoding="utf-8-sig")

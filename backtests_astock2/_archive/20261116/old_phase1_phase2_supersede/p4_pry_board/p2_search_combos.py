#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
p2_search_combos.py: Systematic multi-factor combination search on Pool A, B, and D.
"""
import os, sys, time, json, pickle
import numpy as np, pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/p4_pry_board"
FEE_RATE = 0.0020
CSI300_5Y = -0.1784

df = pd.read_parquet(f"{OUT_DIR}/p2_master_enriched_triggers.parquet")

def eval_sub(sub_df, ret_col, exdt_col):
    n_raw = len(sub_df)
    if n_raw == 0: return None
    rets = sub_df[ret_col].values
    wins = rets[rets > 0]
    losses = rets[rets <= 0]
    wr = float(len(wins) / n_raw)
    po = float(wins.mean() / abs(losses.mean())) if (len(wins) > 0 and len(losses) > 0 and losses.mean() < 0) else (9.99 if len(wins) > 0 else 0.0)
    avg_r = float(rets.mean())
    
    is_mask = sub_df["buy_date"] < "2025-01-01"
    oos_mask = sub_df["buy_date"] >= "2025-01-01"
    is_r = rets[is_mask]
    oos_r = rets[oos_mask]
    is_wr = float((is_r > 0).mean()) if len(is_r) > 0 else 0.0
    oos_wr = float((oos_r > 0).mean()) if len(oos_r) > 0 else 0.0
    is_avg = float(is_r.mean()) if len(is_r) > 0 else 0.0
    oos_avg = float(oos_r.mean()) if len(oos_r) > 0 else 0.0
    
    # Single slot
    s_ord = sub_df.sort_values(["buy_date", "o_pct"], ascending=[True, False])
    free_dt = ""
    ss_trades = []
    ss_nav, ss_pk, ss_mdd = 1.0, 1.0, 0.0
    for r in s_ord.itertuples(index=False):
        bd = str(r.buy_date)[:10]
        if free_dt == "" or bd > free_dt:
            rt = float(getattr(r, ret_col))
            ed = str(getattr(r, exdt_col))[:10]
            ss_trades.append(rt)
            free_dt = max(bd, ed)
            ss_nav *= (1.0 + rt)
            ss_pk = max(ss_pk, ss_nav)
            ss_mdd = max(ss_mdd, (ss_pk - ss_nav) / ss_pk)
            
    ss_rets = np.array(ss_trades, dtype=float)
    if len(ss_rets) > 3:
        ex_top3 = float(np.prod(1.0 + np.sort(ss_rets)[:-3]))
    else:
        ex_top3 = ss_nav
        
    return {
        "n_raw": n_raw, "wr": round(wr*100, 1), "po": round(po, 2), "avg": round(avg_r*100, 2),
        "dt_reseal": round(float(sub_df["is_dt0"].mean())*100, 1),
        "zt_seal": round(float(sub_df["is_zt0"].mean())*100, 1),
        "is_n": len(is_r), "is_wr": round(is_wr*100, 1), "is_avg": round(is_avg*100, 2),
        "oos_n": len(oos_r), "oos_wr": round(oos_wr*100, 1), "oos_avg": round(oos_avg*100, 2),
        "ss_n": len(ss_trades), "ss_nav": round(ss_nav, 3), "ss_mdd": round(ss_mdd*100, 1),
        "ss_ex_top3": round(ex_top3, 3), "excess_5y": round((ss_nav - 1.0 - CSI300_5Y)*100, 1)
    }

print("="*120)
print("TESTING MULTI-FACTOR COMBOS ON POOL A (HIGH DRAGON NUKE):")
print("="*120)

combo_configs = [
    # C1: Highest leader only (全场唯一最高连板总龙首核)
    ("Sole_Max_Board_Only", "is_sole_max_board_prev == True and notice_bad == False"),
    ("Max_Board_Only", "is_max_board_prev == True and notice_bad == False"),
    # C2: Pure turnover board (换手龙首核，非一字断板)
    ("Turnover_Dragon_Only", "prev_is_yizi == False and prev_to >= 15.0 and notice_bad == False"),
    # C3: Systemic panic day only (大盘极端冰点核按钮)
    ("Panic_Day_Dragon", "mkt_dt_prev >= 20 and notice_bad == False"),
    # C4: Early morning rapid pry with high volume
    ("Early_Morning_Vol_Pry", "pry_window == '09:30~10:00' and pry_vol_mult >= 2.0 and notice_bad == False"),
    # C5: No Lhasa retail infestation
    ("No_Lhasa_Clean_Dragon", "lhasa_seats_prev == 0 and notice_bad == False"),
    # C6: High lockup + Golden mcap
    ("High_Lock_Golden_Mcap", "lock_top10 >= 45.0 and real_free_mcap >= 12.0 and real_free_mcap <= 40.0 and notice_bad == False"),
    # C7: Deep combo 1: Turnover Dragon + Early Vol Pry
    ("Turnover_x_EarlyVol", "prev_is_yizi == False and pry_window == '09:30~10:00' and pry_vol_mult >= 2.0 and notice_bad == False"),
    # C8: Deep combo 2: Sole Max Board + Panic Day
    ("Sole_Max_x_Panic", "is_sole_max_board_prev == True and mkt_dt_prev >= 15 and notice_bad == False"),
    # C9: Deep combo 3: High Lockup + No Lhasa + Panic Day
    ("Lock_x_NoLhasa_x_Panic", "lock_top10 >= 45.0 and lhasa_seats_prev == 0 and mkt_dt_prev >= 15 and notice_bad == False"),
    # C10: Q4 demon market + Turnover dragon
    ("Q4_Demon_Turnover", "quarter == 4 and prev_is_yizi == False and notice_bad == False"),
]

combo_results = []
for c_name, c_expr in combo_configs:
    for m in ["M1", "M2_15", "M3_15"]:
        for ex in ["E1_next_open", "E2_tp5", "E4_dragon_hold"]:
            sub = df[(df["pool"] == "Pool_A_HighDragon_Nuke") & (df["mode"] == m)].query(c_expr)
            res = eval_sub(sub, f"ret_{ex}", f"exdt_{ex}")
            if res and res["n_raw"] >= 5:
                res["combo"] = c_name
                res["mode"] = m
                res["exit"] = ex
                combo_results.append(res)

cdf = pd.DataFrame(combo_results)
show_cols = ["combo", "mode", "exit", "n_raw", "wr", "po", "avg", "dt_reseal", "zt_seal", "ss_n", "ss_nav", "ss_mdd", "ss_ex_top3", "is_avg", "oos_avg"]
print(cdf.sort_values("ss_nav", ascending=False).head(20)[show_cols].to_string(index=False))

print("\n" + "="*120)
print("TESTING POOL D (COLD FIRST DT) AS A COMPARATIVE CONTROL:")
print("="*120)
d_combos = [
    ("StrictPry_Exact", "mkt_dt_prev >= 20 and notice_bad == False and open_px_raw >= 2.0"),
    ("StrictPry_Panic30", "mkt_dt_prev >= 30 and notice_bad == False and open_px_raw >= 2.0"),
    ("Cold_NoFilter", "notice_bad == False"),
]
d_res = []
for c_name, c_expr in d_combos:
    for m in ["M1", "M2_15", "M2_25"]:
        for ex in ["E1_next_open", "E2_tp5", "E3_tp7"]:
            sub = df[(df["pool"] == "Pool_D_Cold_FirstDT") & (df["mode"] == m)].query(c_expr)
            res = eval_sub(sub, f"ret_{ex}", f"exdt_{ex}")
            if res and res["n_raw"] >= 5:
                res["combo"] = c_name
                res["mode"] = m
                res["exit"] = ex
                d_res.append(res)
ddf = pd.DataFrame(d_res)
print(ddf.sort_values("ss_nav", ascending=False).head(15)[show_cols].to_string(index=False))

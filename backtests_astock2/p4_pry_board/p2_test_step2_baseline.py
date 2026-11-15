#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
p2_test_step2_baseline.py: Run complete Task 1 baseline audit across Four Physical Pools x Modes x Exits.
"""
import os, sys, time, json, pickle
import numpy as np, pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SANDBOX = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab"
MATRIX = f"{SANDBOX}/grand_factor_matrix_20261112"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/p4_pry_board"
FEE_RATE = 0.0020

print("[+] Loading code_bars_5y.pkl & 5m cache...")
t0 = time.time()
with open(f"{MATRIX}/code_bars_5y.pkl", "rb") as f:
    cb_data = pickle.load(f)
cb = cb_data["code_bars"]

with open(f"{OUT_DIR}/p2_5m_bars_cache.pkl", "rb") as f:
    b5m_map = pickle.load(f)

with open(f"{ROOT}/sim-portfolio/data/st_universe.json") as f:
    st_codes = set(json.load(f).get("codes", []))
csrc_df = pd.read_csv(f"{ROOT}/sim-portfolio/data/csrc_industry_l2.csv")
csrc_df["c6"] = csrc_df["code"].astype(str).str[-6:]
st_names = set(csrc_df[csrc_df["code_name"].str.contains("ST|退", case=False, na=False)]["c6"])
all_st_codes = st_codes | st_names

with open(f"{SANDBOX}/index_klines_5y_cache.json", "r") as f:
    csi_map = json.load(f)["sh000300"]
csi_dts = sorted(csi_map.keys())

def csi_ret(d_start, d_end):
    d_list = [d for d in csi_dts if d_start <= d <= d_end]
    if len(d_list) < 2: return 0.0
    p0 = max(0, csi_dts.index(d_list[0]) - 1)
    return float(csi_map[d_list[-1]] / csi_map[csi_dts[p0]] - 1.0)

CSI_BENCH = {
    "5y": csi_ret("2022-01-04", "2026-11-10"),
    "3y": csi_ret("2023-11-10", "2026-11-10"),
    "rec": csi_ret("2026-07-01", "2026-11-10"),
}

print(f"Loaded data in {time.time()-t0:.2f}s, CSI300 5y: {CSI_BENCH['5y']*100:.2f}%")

def _is_locked_dt(op, hi, lo, cl, pc, is_yz_dt):
    if is_yz_dt: return True
    if pc > 0 and (op == hi == lo == cl) and (cl / pc - 1.0 <= -0.044): return True
    return False

def sim_trade_exit(b, pos, buy_px, exit_mode, is_zt0):
    """
    Simulate strict T+1 exit:
      exit_mode:
        'E1_next_open': next day open
        'E2_tp5': next day touch +5% or close
        'E3_tp7': touch +7% (up to 3 days) or close
        'E4_dragon_hold': if is_zt0, hold while ZT continues, exit first non-ZT open; else next open
      Strict T+1 limit-down lock deferral!
    """
    n = len(b["dts"])
    adj0 = b["adjf"][pos]
    buy_adj = buy_px * adj0
    dts = b["dts"]
    opens, highs, lows, closes = b["open"], b["high"], b["low"], b["close"]
    adjfs, pre_cs, dt_pxs = b["adjf"], b["pre_c"], b["dt_px"]
    is_zts, is_dts, is_yz_dts, tos = b["is_zt"], b["is_dt"], b["is_yizi_dt"], b["to"]

    if pos >= n - 1:
        return dts[pos], -FEE_RATE, 0

    last_tradable_idx = -1
    tradable_step = 0
    
    # E4_dragon_hold special logic
    if exit_mode == "E4_dragon_hold" and is_zt0:
        # Continue holding while is_zt
        for step in range(1, n - pos):
            idx = pos + step
            to_v = tos[idx]
            if to_v <= 0.0 or np.isnan(to_v): continue
            tradable_step += 1
            last_tradable_idx = idx
            op, hi, lo, cl, pc = opens[idx], highs[idx], lows[idx], closes[idx], pre_cs[idx]
            if _is_locked_dt(op, hi, lo, cl, pc, bool(is_yz_dts[idx])):
                continue
            adj_i = adjfs[idx]
            # If day is ZT, continue holding
            if bool(is_zts[idx]):
                continue
            # First non-ZT day: exit at open
            return dts[idx], (op * adj_i) / buy_adj * (1.0 - FEE_RATE) - 1.0, tradable_step
        # If reached end of data
        end_i = last_tradable_idx if last_tradable_idx >= 0 else (n - 1)
        return dts[end_i], (closes[end_i] * adjfs[end_i]) / buy_adj * (1.0 - FEE_RATE) - 1.0, tradable_step

    max_hold = 3 if exit_mode == "E3_tp7" else (2 if exit_mode == "E2_tp5" else 1)
    tp_pct = 0.07 if exit_mode == "E3_tp7" else (0.05 if exit_mode == "E2_tp5" else 0.0)

    for step in range(1, n - pos):
        idx = pos + step
        to_v = tos[idx]
        if to_v <= 0.0 or np.isnan(to_v): continue
        tradable_step += 1
        last_tradable_idx = idx
        op, hi, lo, cl, pc, dt_px = opens[idx], highs[idx], lows[idx], closes[idx], pre_cs[idx], dt_pxs[idx]
        
        if _is_locked_dt(op, hi, lo, cl, pc, bool(is_yz_dts[idx])):
            continue # Locked DT, defer!

        adj_i = adjfs[idx]
        op_adj = op * adj_i
        hi_adj = hi * adj_i
        cl_adj = cl * adj_i

        if exit_mode in ("E1_next_open", "E4_dragon_hold"):
            return dts[idx], op_adj / buy_adj * (1.0 - FEE_RATE) - 1.0, tradable_step
        else: # E2_tp5 or E3_tp7
            if tradable_step > max_hold:
                return dts[idx], op_adj / buy_adj * (1.0 - FEE_RATE) - 1.0, tradable_step
            tp_target = buy_adj * (1.0 + tp_pct)
            if op_adj >= tp_target:
                return dts[idx], op_adj / buy_adj * (1.0 - FEE_RATE) - 1.0, tradable_step
            if hi_adj >= tp_target:
                return dts[idx], tp_pct - FEE_RATE, tradable_step
            if tradable_step == max_hold:
                if bool(is_dts[idx]) or (cl <= dt_px + 0.011):
                    continue # Re-sealed DT at close, defer to next open!
                return dts[idx], cl_adj / buy_adj * (1.0 - FEE_RATE) - 1.0, tradable_step

    end_i = last_tradable_idx if last_tradable_idx >= 0 else (n - 1)
    return dts[end_i], (closes[end_i] * adjfs[end_i]) / buy_adj * (1.0 - FEE_RATE) - 1.0, tradable_step

print("[+] Precomputing all trade cases...")

t_scan = time.time()
rows = []

for c6, b in cb.items():
    if not c6.startswith(('00', '60')) or c6 in all_st_codes:
        continue
    dts = b['dts']
    n = len(dts)
    streak = np.zeros(n, dtype=int)
    dt_streak = np.zeros(n, dtype=int)
    zt_cnt10 = np.zeros(n, dtype=int)
    zt_cnt20 = np.zeros(n, dtype=int)
    for i in range(n):
        streak[i] = streak[i-1] + 1 if (i > 0 and b['is_zt'][i]) else (1 if b['is_zt'][i] else 0)
        dt_streak[i] = dt_streak[i-1] + 1 if (i > 0 and b['is_dt'][i]) else (1 if b['is_dt'][i] else 0)
        zt_cnt10[i] = np.sum(b['is_zt'][max(0, i-9):i+1])
        zt_cnt20[i] = np.sum(b['is_zt'][max(0, i-19):i+1])
        
    for i in range(1, n):
        dt = dts[i]
        if dt < '2022-01-04' or dt > '2026-11-10':
            continue
        op = float(b['open'][i])
        hi = float(b['high'][i])
        lo = float(b['low'][i])
        cl = float(b['close'][i])
        pc = float(b['pre_c'][i])
        zt_px = float(b['zt_px'][i])
        dt_px = float(b['dt_px'][i])
        to_v = float(b['to'][i])
        if pc <= 0 or op < 2.0 or to_v <= 0 or np.isnan(to_v) or dt_streak[i-1] != 0:
            continue
            
        p_strk = streak[i-1]
        p_zt10 = zt_cnt10[i-1]
        p_zt20 = zt_cnt20[i-1]
        
        p_name = None
        if p_strk >= 3: p_name = 'Pool_A_HighDragon_Nuke'
        elif p_strk in (1, 2): p_name = 'Pool_B_1to2Board_Nuke'
        elif p_strk == 0 and p_zt10 >= 2: p_name = 'Pool_C_Day2_Break_Nuke'
        elif p_zt20 == 0: p_name = 'Pool_D_Cold_FirstDT'
        if p_name is None:
            continue
            
        o_pct = op / pc - 1.0
        is_zt0 = bool(b['is_zt'][i])
        is_dt0 = bool(b['is_dt'][i]) or (cl <= dt_px + 0.011)
        
        # M1: Auction -9.8%~-6.0%
        if (-0.098 <= o_pct <= -0.060) and (op > dt_px + 0.005):
            rows.append({
                "code": c6, "buy_date": dt, "pos": i, "pool": p_name, "mode": "M1",
                "buy_px": op, "is_zt0": is_zt0, "is_dt0": is_dt0, "o_pct": o_pct,
                "pry_window": "09:25", "pry_vol_mult": 1.0
            })
            
        # M2: Open limit down
        if op <= dt_px + 0.011:
            trig15 = np.round(dt_px * 1.015, 2)
            trig25 = np.round(dt_px * 1.025, 2)
            # Find 5m bar info if available
            bars5m = b5m_map.get((c6, dt))
            w15, vm15 = "open_dt", 1.0
            w25, vm25 = "open_dt", 1.0
            if bars5m is not None and len(bars5m) > 0:
                mean_amt = np.mean(bars5m[:, 6]) + 1e-6
                for b_bar in bars5m:
                    if b_bar[2] >= trig15: # high >= trig15
                        hh = int(b_bar[0])
                        w15 = "09:30~10:00" if hh <= 1000 else ("10:00~11:30" if hh <= 1130 else ("13:00~14:30" if hh <= 1430 else "14:30后"))
                        vm15 = float(b_bar[6] / mean_amt)
                        break
                for b_bar in bars5m:
                    if b_bar[2] >= trig25:
                        hh = int(b_bar[0])
                        w25 = "09:30~10:00" if hh <= 1000 else ("10:00~11:30" if hh <= 1130 else ("13:00~14:30" if hh <= 1430 else "14:30后"))
                        vm25 = float(b_bar[6] / mean_amt)
                        break
            if hi >= trig15:
                rows.append({
                    "code": c6, "buy_date": dt, "pos": i, "pool": p_name, "mode": "M2_15",
                    "buy_px": trig15, "is_zt0": is_zt0, "is_dt0": is_dt0, "o_pct": o_pct,
                    "pry_window": w15, "pry_vol_mult": vm15
                })
            if hi >= trig25:
                rows.append({
                    "code": c6, "buy_date": dt, "pos": i, "pool": p_name, "mode": "M2_25",
                    "buy_px": trig25, "is_zt0": is_zt0, "is_dt0": is_dt0, "o_pct": o_pct,
                    "pry_window": w25, "pry_vol_mult": vm25
                })
                
        # M3: Open > dt, touch dt, strictly evaluated with 5m sequence
        if (op > dt_px + 0.011) and (lo <= dt_px + 0.005):
            bars5m = b5m_map.get((c6, dt))
            if bars5m is not None and len(bars5m) > 1:
                trig15 = np.round(dt_px * 1.015, 2)
                trig25 = np.round(dt_px * 1.025, 2)
                mean_amt = np.mean(bars5m[:, 6]) + 1e-6
                
                # Step 1: find first bar touching dt (bar_low <= dt_px + 0.005)
                t1_idx = -1
                for b_idx in range(len(bars5m)):
                    if bars5m[b_idx, 3] <= dt_px + 0.005: # low <= dt_px + 0.005
                        t1_idx = b_idx
                        break
                        
                if t1_idx >= 0 and t1_idx < len(bars5m) - 1:
                    # Step 2: find t2 > t1 reaching trig
                    for b_idx in range(t1_idx + 1, len(bars5m)):
                        b_bar = bars5m[b_idx]
                        if b_bar[2] >= trig15: # high >= trig15
                            hh = int(b_bar[0])
                            w15 = "09:30~10:00" if hh <= 1000 else ("10:00~11:30" if hh <= 1130 else ("13:00~14:30" if hh <= 1430 else "14:30后"))
                            vm15 = float(b_bar[6] / mean_amt)
                            bpx15 = max(float(b_bar[1]), trig15) # max(bar_open, trig15)
                            rows.append({
                                "code": c6, "buy_date": dt, "pos": i, "pool": p_name, "mode": "M3_15",
                                "buy_px": bpx15, "is_zt0": is_zt0, "is_dt0": is_dt0, "o_pct": o_pct,
                                "pry_window": w15, "pry_vol_mult": vm15
                            })
                            break
                            
                    for b_idx in range(t1_idx + 1, len(bars5m)):
                        b_bar = bars5m[b_idx]
                        if b_bar[2] >= trig25: # high >= trig25
                            hh = int(b_bar[0])
                            w25 = "09:30~10:00" if hh <= 1000 else ("10:00~11:30" if hh <= 1130 else ("13:00~14:30" if hh <= 1430 else "14:30后"))
                            vm25 = float(b_bar[6] / mean_amt)
                            bpx25 = max(float(b_bar[1]), trig25)
                            rows.append({
                                "code": c6, "buy_date": dt, "pos": i, "pool": p_name, "mode": "M3_25",
                                "buy_px": bpx25, "is_zt0": is_zt0, "is_dt0": is_dt0, "o_pct": o_pct,
                                "pry_window": w25, "pry_vol_mult": vm25
                            })
                            break

df_all = pd.DataFrame(rows)
print(f"Scanned universe in {time.time()-t_scan:.2f}s, total trigger cases: {len(df_all)}")
print(df_all.groupby(["pool", "mode"]).size().unstack(fill_value=0))

# Precompute exits for each row
print("[+] Simulating exits for all trades...")
t_ex = time.time()
for ex_m in ["E1_next_open", "E2_tp5", "E3_tp7", "E4_dragon_hold"]:
    ex_dts, net_rets, hold_steps = [], [], []
    for r in df_all.itertuples(index=False):
        b = cb[r.code]
        ex_d, nr, stp = sim_trade_exit(b, r.pos, r.buy_px, ex_m, r.is_zt0)
        ex_dts.append(ex_d)
        net_rets.append(nr)
        hold_steps.append(stp)
    df_all[f"exdt_{ex_m}"] = ex_dts
    df_all[f"ret_{ex_m}"] = net_rets
    df_all[f"step_{ex_m}"] = hold_steps

print(f"Precomputed exits in {time.time()-t_ex:.2f}s")

# Helper for D15 evaluation of any subset
def eval_d15(sub_df, ret_col, exdt_col):
    if len(sub_df) == 0:
        return {"n": 0, "wr": 0.0, "po": 0.0, "avg": 0.0, "ss_nav": 1.0, "ss_mdd": 0.0, "ss_po": 0.0, "ss_ex_top3": 1.0, "excess_5y": 0.0, "eq_nav": 1.0, "is_wr": 0.0, "oos_wr": 0.0, "dt_reseal_r": 0.0, "zt_seal_r": 0.0}
    rets = sub_df[ret_col].values
    wins = rets[rets > 0]
    losses = rets[rets <= 0]
    wr = float(len(wins) / len(rets)) if len(rets) > 0 else 0.0
    po = float(wins.mean() / abs(losses.mean())) if (len(wins) > 0 and len(losses) > 0 and losses.mean() < 0) else (9.99 if len(wins) > 0 else 0.0)
    avg_r = float(rets.mean())
    
    # Day0 diagnostic
    dt_reseal_r = float(sub_df["is_dt0"].mean())
    zt_seal_r = float(sub_df["is_zt0"].mean())
    
    # IS / OOS
    is_mask = sub_df["buy_date"] < "2025-01-01"
    oos_mask = sub_df["buy_date"] >= "2025-01-01"
    is_r = rets[is_mask]
    oos_r = rets[oos_mask]
    is_wr = float((is_r > 0).mean()) if len(is_r) > 0 else 0.0
    oos_wr = float((oos_r > 0).mean()) if len(oos_r) > 0 else 0.0
    
    # Single slot simulation
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
    ss_w = ss_rets[ss_rets > 0]
    ss_l = ss_rets[ss_rets <= 0]
    ss_po = float(ss_w.mean() / abs(ss_l.mean())) if (len(ss_w) > 0 and len(ss_l) > 0 and ss_l.mean() < 0) else 0.0
    
    if len(ss_rets) > 3:
        ex_top3 = float(np.prod(1.0 + np.sort(ss_rets)[:-3]))
    else:
        ex_top3 = ss_nav
        
    # Daily equal weight
    eq_daily = sub_df.groupby("buy_date")[ret_col].mean().sort_index()
    eq_nav = float(np.prod(1.0 + eq_daily.values))
    
    return {
        "n_raw": len(sub_df),
        "wr": round(wr * 100, 1),
        "po": round(po, 2),
        "avg": round(avg_r * 100, 2),
        "ss_n": len(ss_trades),
        "ss_nav": round(ss_nav, 3),
        "ss_mdd": round(ss_mdd * 100, 1),
        "ss_po": round(ss_po, 2),
        "ss_ex_top3": round(ex_top3, 3),
        "excess_5y": round((ss_nav - 1.0 - CSI_BENCH["5y"]) * 100, 1),
        "eq_nav": round(eq_nav, 3),
        "is_wr": round(is_wr * 100, 1),
        "oos_wr": round(oos_wr * 100, 1),
        "dt_reseal_r": round(dt_reseal_r * 100, 1),
        "zt_seal_r": round(zt_seal_r * 100, 1)
    }

print("\n" + "="*110)
print("TASK 1 BASELINE AUDIT: FOUR PHYSICAL POOLS x MODES x EXITS")
print("="*110)
results_t1 = []
for p_name in ["Pool_A_HighDragon_Nuke", "Pool_B_1to2Board_Nuke", "Pool_C_Day2_Break_Nuke", "Pool_D_Cold_FirstDT"]:
    for m in ["M1", "M2_15", "M2_25", "M3_15", "M3_25"]:
        for ex_m in ["E1_next_open", "E2_tp5", "E3_tp7", "E4_dragon_hold"]:
            sub = df_all[(df_all["pool"] == p_name) & (df_all["mode"] == m)]
            res = eval_d15(sub, f"ret_{ex_m}", f"exdt_{ex_m}")
            res["pool"] = p_name
            res["mode"] = m
            res["exit"] = ex_m
            results_t1.append(res)
            
t1_df = pd.DataFrame(results_t1)
pd.set_option('display.max_columns', 15)
pd.set_option('display.width', 1000)

for p_name in ["Pool_A_HighDragon_Nuke", "Pool_B_1to2Board_Nuke", "Pool_C_Day2_Break_Nuke", "Pool_D_Cold_FirstDT"]:
    print(f"\n>>> Physical Pool: {p_name} <<<")
    p_sub = t1_df[t1_df["pool"] == p_name]
    summary_cols = ["mode", "exit", "n_raw", "wr", "po", "avg", "dt_reseal_r", "zt_seal_r", "ss_n", "ss_nav", "ss_mdd", "ss_ex_top3", "excess_5y", "is_wr", "oos_wr"]
    print(p_sub[summary_cols].to_string(index=False))

# Save baseline full table
t1_df.to_csv(f"{OUT_DIR}/p2_task1_baseline_matrix.csv", index=False)
df_all.to_parquet(f"{OUT_DIR}/p2_all_triggers_with_exits.parquet")
print(f"\n[+] Saved baseline to {OUT_DIR}/p2_task1_baseline_matrix.csv and parquet!")

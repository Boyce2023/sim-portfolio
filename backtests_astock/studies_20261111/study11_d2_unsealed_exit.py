#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
import sys, glob, sqlite3
import numpy as np
import pandas as pd

sys.path.insert(0, "/tmp")
sys.path.insert(0, "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock")
sys.path.insert(0, "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-11-1to2-clean")
from master_5y_zero_lookahead_walkforward import (
    load_all_data, evaluate_strategy_master, FEE_RATE, FEE_RATE_DISCOUNT
)
import astock_verify_wr_optimization_strict as M

hist_fb = M.hist_fb
price_lookup = M.price_lookup
all_dts = M.all_dts
dt_to_idx = M.dt_to_idx

# Reconstruct exact 113-trade mask & score from UPGRADE_MT37_HT5_IR5_NoRk4
_, _, tot_mask, sv_score = M.run_cfg("UPGRADE_MT37_HT5_IR5_NoRk4", min_tight=37.0, bon_turnover=5.0, bon_ir=5.0, block_rk4_usurp=True)
hist_fb["_sv_master"] = sv_score

# First: anatomical dissection of what ACTUALLY happens on our 113 trades at D2, D3, D4..D12!
sub_oos = hist_fb[tot_mask & (hist_fb["d2_dt"] >= "2022-01-01") & (hist_fb["d2_dt"] <= "2026-11-09")].sort_values(["d2_dt", "_sv_master"], ascending=[True, False]).drop_duplicates("d2_dt").copy()
print(f"\n=== ANATOMY OF ALL {len(sub_oos)} DAILY TOP-1 SIGNALS (2022-2026) ===")

# Inspect D2 unsealed vs D2 sealed_2b paths
d2_fail, d2_seal = [], []
for _, row in sub_oos.iterrows():
    c6 = row["c6"]
    d2 = row["d2_dt"]
    idx2 = dt_to_idx.get(d2, -1)
    b2 = price_lookup.get((c6, d2))
    if not b2 or idx2 < 0 or idx2 + 1 >= len(all_dts):
        continue
    o2, h2, l2, c2, zt2, dt2, izt2, iyz2 = b2
    # Check trigger (same as master engine)
    is_mon_dir = (row.get("gap_days", 1) >= 3) and (row["score_active"] >= 310.0)
    trig_px = round(float(o2), 2) if is_mon_dir else round(max(float(o2), float(row["close"]) * 1.06), 2)
    if h2 < trig_px - 1e-4 or o2 >= zt2 - 0.005:
        continue
    b3 = price_lookup.get((c6, all_dts[idx2 + 1]))
    if not b3:
        continue
    o3, h3, l3, c3, zt3, dt3, izt3, iyz3 = b3
    if not izt2:
        d2_fail.append({
            "d2": d2, "name": row["name"], "buy": trig_px, "c1": float(row["close"]),
            "o2": o2, "c2": c2, "o3": o3, "h3": h3, "c3": c3, "izt3": izt3,
            "d2_up": c2 >= float(row["close"]), "o3_vs_c2": o3 / c2 - 1.0, "c3_vs_o3": c3 / o3 - 1.0
        })
    else:
        # Trace consecutive boards starting from D2 (board #2)
        boards = 2
        curr = idx2 + 1
        prev_c = c2
        path = []
        while curr < len(all_dts) and (curr - idx2 <= 15):
            bc = price_lookup.get((c6, all_dts[curr]))
            if not bc:
                break
            oc, hc, lc, cc, ztc, dtc, iztc, iyzc = bc
            # also check next day bar after break!
            b_next = price_lookup.get((c6, all_dts[curr + 1])) if (curr + 1 < len(all_dts)) else None
            path.append({
                "step": curr - idx2, "dt": all_dts[curr], "prev_c": prev_c,
                "o_ret": oc / prev_c - 1.0, "h_ret": hc / prev_c - 1.0,
                "l_ret": lc / prev_c - 1.0, "c_ret": cc / prev_c - 1.0,
                "o": oc, "h": hc, "l": lc, "c": cc, "zt": ztc, "izt": iztc, "iyz_dt": iyzc,
                "next_o_ret": (b_next[0] / cc - 1.0) if b_next else 0.0,
                "next_c_ret": (b_next[3] / cc - 1.0) if b_next else 0.0,
                "next_izt": b_next[6] if b_next else False,
            })
            if iztc:
                boards += 1
                prev_c = cc
                curr += 1
            else:
                break
        d2_seal.append({"d2": d2, "name": row["name"], "buy": trig_px, "max_boards": boards, "path": path})

df_fail = pd.DataFrame(d2_fail)
print(f"1) D2 Unsealed (Failed 2B): N={len(df_fail)}")
print(f"   - Exit at D3 Open (all): avg={(df_fail['o3']/df_fail['buy']-1).mean()*100:+.2f}%")
print(f"   - Exit at D3 Close (all): avg={(df_fail['c3']/df_fail['buy']-1).mean()*100:+.2f}%")
for cond_nm, m in [
    ("D2 closed green (c2>=c1) & D3 o3>=+0.5%", df_fail["d2_up"] & (df_fail["o3_vs_c2"] >= 0.005)),
    ("D2 closed green (c2>=c1) & D3 o3<+0.5%", df_fail["d2_up"] & (df_fail["o3_vs_c2"] < 0.005)),
    ("D2 closed red (c2<c1, 冲高回落假阴/大阴)", ~df_fail["d2_up"]),
    ("D3 Deep Low Open (o3/c2 <= -3.0%)", df_fail["o3_vs_c2"] <= -0.03),
]:
    s = df_fail[m]
    if len(s) > 0:
        print(f"   [{cond_nm:42s}] N={len(s):2d} | D3_Open={(s['o3']/s['buy']-1).mean()*100:+6.2f}% vs D3_Close={(s['c3']/s['buy']-1).mean()*100:+6.2f}% | diff(Close-Open)={(s['c3']/s['buy']-s['o3']/s['buy']).mean()*100:+5.2f}%")

print(f"\n2) D2 Sealed 2-Board: N={len(d2_seal)}")
b_dist = pd.Series([x["max_boards"] for x in d2_seal]).value_counts().sort_index().to_dict()
print("   Max board height distribution:", b_dist)

# Analyze the EXACT Streak-Break Day (`path[-1]`) of all D2-sealed trades!
brk_rows = []
for x in d2_seal:
    if not x["path"]:
        continue
    last = x["path"][-1]
    if not last["izt"]:
        brk_rows.append({
            "d2": x["d2"], "name": x["name"], "buy": x["buy"], "boards_before_brk": x["max_boards"],
            "o_ret": last["o_ret"], "h_ret": last["h_ret"], "l_ret": last["l_ret"], "c_ret": last["c_ret"],
            "o": last["o"], "h": last["h"], "c": last["c"],
            "next_o_ret": last["next_o_ret"], "next_c_ret": last["next_c_ret"], "next_izt": last["next_izt"],
            "d3_o_ret": x["path"][0]["o_ret"], "d3_izt": x["path"][0]["izt"]
        })
df_brk = pd.DataFrame(brk_rows)
print(f"   Streak-break day anatomy (N={len(df_brk)}):")
for lbl, m in [
    ("Break day Open <= -4.0% (核按钮低开)", df_brk["o_ret"] <= -0.04),
    ("Break day Open -4.0% ~ 0.0% (小幅低开水下分歧)", df_brk["o_ret"].between(-0.04, 0.0)),
    ("Break day Open 0.0% ~ +4.9% (温和红开断板)", df_brk["o_ret"].between(0.0001, 0.049)),
    ("Break day Open >= +5.0% non-yizi (大幅高开冲板失败断板)", df_brk["o_ret"] >= 0.05),
    ("High-Board (>=3B) Break closing strong >= +2% (高标断板强承接首阴)", (df_brk["boards_before_brk"] >= 3) & (df_brk["c_ret"] >= 0.02)),
    ("High-Board (>=3B) Break closing weak < 0% (高标断板绿盘)", (df_brk["boards_before_brk"] >= 3) & (df_brk["c_ret"] < 0.0)),
]:
    s = df_brk[m]
    if len(s) > 0:
        print(f"   [{lbl:50s}] N={len(s):2d} | Open_ret={s['o_ret'].mean()*100:+5.2f}% | High_ret={s['h_ret'].mean()*100:+5.2f}% | Close_ret={s['c_ret'].mean()*100:+5.2f}% | NextDay_Close_vs_BrkClose={s['next_c_ret'].mean()*100:+5.2f}%")

# Also check D3 (2-to-3 day) when D3 opens >= +5% non-yizi: how many SEAL 3B vs FAIL!
d3_all = pd.DataFrame([{
    "d2": x["d2"], "name": x["name"], "buy": x["buy"], "max_b": x["max_boards"],
    "d3_o": x["path"][0]["o_ret"], "d3_c": x["path"][0]["c_ret"], "d3_h": x["path"][0]["h_ret"],
    "d3_izt": x["path"][0]["izt"], "d3_yizi": x["path"][0]["o"] >= x["path"][0]["zt"] - 0.005
} for x in d2_seal if len(x["path"]) > 0])
print("\n3) D3 (2-to-3 Day) Opening Structure on All Sealed 2B Trades:")
for lbl, m in [
    ("D3 Yizi Open (一字三板)", d3_all["d3_yizi"]),
    ("D3 High Open +5.0% ~ +9.8% Non-Yizi", (~d3_all["d3_yizi"]) & (d3_all["d3_o"] >= 0.05)),
    ("D3 Mid Open +1.0% ~ +5.0%", d3_all["d3_o"].between(0.01, 0.0499)),
    ("D3 Flat/Mild Low -3.0% ~ +1.0%", d3_all["d3_o"].between(-0.03, 0.0099)),
    ("D3 Nuclear Low Open < -3.0%", d3_all["d3_o"] < -0.03),
]:
    s = d3_all[m]
    if len(s) > 0:
        print(f"   [{lbl:38s}] N={len(s):2d} | 3B_Seal_Rate={s['d3_izt'].mean()*100:5.1f}% | Avg_MaxBoards={s['max_b'].mean():.2f} | D3_Open={s['d3_o'].mean()*100:+5.2f}% | D3_Close={s['d3_c'].mean()*100:+5.2f}%")

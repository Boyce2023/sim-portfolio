#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Task 3: Deep Dive into Custom Exits on High-Conviction 14:57 Candidates.
Simulates daily paths using code_bars_5y.pkl for precision verification.
"""
import os, pickle, time
import numpy as np
import pandas as pd

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/p5_full_pry_universe"
GFM_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112"
COST = 0.0020

df = pd.read_parquet(f"{OUT_DIR}/s2_pry_master_enriched.parquet")
with open(f"{GFM_DIR}/code_bars_5y.pkl", "rb") as f:
    cb = pickle.load(f)["code_bars"]

# Filter candidate universe:
# Clean from poison, non-ST, pre_c >= 2.0, touch_dt & (~is_dt) & (close >= dt_price * 1.015)
cand_mask = (
    (~df["is_st_or_delist"]) &
    (df["pre_c"] >= 2.0) &
    (df["touch_dt"]) &
    (~df["is_dt"]) &
    (~df["is_zt"]) &
    (df["close"] >= df["dt_price"] * 1.015) &
    (df["n_poison_total"] == 0) &
    (df["prev_yizi_dt_streak"].fillna(0) == 0)
)

# Subset of High-Conviction types:
# Pool 1: Type B (1DT day2 pry)
# Pool 2: Type C (2+ DT despair pry)
# Pool 3: Rubber-band oversold (prev_c_ma5 < -0.12 or prev_ret5 < -0.22)
# Pool 4: Market Panic Pioneer (TAIL1457_mkt_dt_today >= 40 & rk_rebound_today <= 5)
# Combined High-Conviction Core Pool:
high_conv_mask = cand_mask & (
    (df["prev_dt_streak"] >= 1) |
    (df["prev_c_ma5"] < -0.12) |
    (df["prev_ret5"] < -0.22) |
    ((df["TAIL1457_mkt_dt_today"] >= 40) & (df["rk_rebound_today"] <= 5))
)

print(f"High conviction candidate count: {high_conv_mask.sum()}")

sub_df = df[high_conv_mask].copy().reset_index(drop=True)

c6_v = sub_df["c6"].values
dt_v = sub_df["dt_str"].values
bpx_v = sub_df["close"].values # 14:57 / close price
n_sub = len(sub_df)

def first_sellable_day(d, start_pos):
    L = len(d["dts"])
    p = start_pos
    while p < L - 1 and d["is_yizi_dt"][p]:
        p += 1
    return min(p, L - 1)

def hold_zt_relay(d, pk):
    L = len(d["dts"])
    o, h, l, c, dt_px, is_zt, is_yz_dt, dts = d["open"], d["high"], d["low"], d["close"], d["dt_px"], d["is_zt"], d["is_yizi_dt"], d["dts"]
    cur = pk
    while cur < L - 1:
        nxt = cur + 1
        if is_yz_dt[nxt]:
            nxt2 = first_sellable_day(d, nxt)
            s_px = o[nxt2] if o[nxt2] > dt_px[nxt2] + 0.005 else c[nxt2]
            return float(s_px), str(dts[nxt2])
        if is_zt[nxt]:
            cur = nxt
            continue
        return float(c[nxt]), str(dts[nxt])
    return float(c[cur]), str(dts[cur])

# Define exits:
# E_X1: T+1 open
# E_X2: T+1 close
# E_TP3_2d: T+1~T+2 take profit +3%, else close
# E_TP4_2d: T+1~T+2 take profit +4%, else close
# E_TP5_2d: T+1~T+2 take profit +5%, else close (X3)
# E_TP7_3d: T+1~T+3 take profit +7%, else close (X4)
# E_TP10_5d: T+1~T+5 take profit +10%, else close (X5)
# E_X6_cutweak: T+1 open < -2.5% cut, else TP +9% in 4d
# E_X9_ma5: MA5 regression in 5d
# E_X10_dyn: Dynamic oversold TP in 4d
# E_Rubber_3d_protect: TP +4.5% in 3d, or hard stop -5.5% at T+1 close/T+2 open

exit_names = [
    "X1_T1_Open", "X2_T1_Close", "X_TP3_2d", "X_TP4_2d", "X3_TP5_2d",
    "X4_TP7_3d", "X5_TP10_5d", "X6_CutWeak_Hold9", "X9_MA5_Regress",
    "X10_Dyn_Oversold", "X_Rubber_3d_Protect"
]

results = {ename: np.full(n_sub, np.nan, dtype=np.float32) for ename in exit_names}
exit_dts = {ename: np.full(n_sub, "", dtype="U10") for ename in exit_names}

for i in range(n_sub):
    d = cb.get(c6_v[i])
    if d is None:
        continue
    p0 = d["date_to_pos"].get(dt_v[i])
    if p0 is None or p0 + 1 >= len(d["dts"]):
        continue
    
    L = len(d["dts"])
    o, h, l, c, dt_px, is_zt, is_yz_dt, dts = d["open"], d["high"], d["low"], d["close"], d["dt_px"], d["is_zt"], d["is_yizi_dt"], d["dts"]
    bpx = bpx_v[i]
    if bpx <= 0:
        continue
    
    # 1. X1_T1_Open
    ps1 = first_sellable_day(d, p0 + 1)
    spx = o[ps1] if o[ps1] > dt_px[ps1] + 0.005 else c[ps1]
    results["X1_T1_Open"][i] = spx / bpx * (1.0 - COST) - 1.0
    exit_dts["X1_T1_Open"][i] = str(dts[ps1])

    # 2. X2_T1_Close
    if ps1 == p0 + 1 and is_zt[ps1]:
        spx, sdt = hold_zt_relay(d, ps1)
    else:
        spx, sdt = c[ps1], str(dts[ps1])
    results["X2_T1_Close"][i] = spx / bpx * (1.0 - COST) - 1.0
    exit_dts["X2_T1_Close"][i] = sdt

    # 3. Fixed TP helpers
    def run_fixed_tp(tp_pct, max_days):
        tp_px = round(bpx * (1.0 + tp_pct), 2)
        end_p = min(L - 1, p0 + max_days)
        for k in range(p0 + 1, end_p + 1):
            if is_yz_dt[k]:
                continue
            if o[k] >= tp_px:
                if is_zt[k]: return hold_zt_relay(d, k)
                return o[k], str(dts[k])
            if h[k] >= tp_px:
                if is_zt[k]: return hold_zt_relay(d, k)
                return tp_px, str(dts[k])
        ps = first_sellable_day(d, end_p)
        return c[ps], str(dts[ps])

    for ename, tp_r, max_d in [
        ("X_TP3_2d", 0.03, 2),
        ("X_TP4_2d", 0.04, 2),
        ("X3_TP5_2d", 0.05, 2),
        ("X4_TP7_3d", 0.07, 3),
        ("X5_TP10_5d", 0.10, 5),
    ]:
        spx, sdt = run_fixed_tp(tp_r, max_d)
        results[ename][i] = spx / bpx * (1.0 - COST) - 1.0
        exit_dts[ename][i] = sdt

    # 8. X6_CutWeak_Hold9
    p1 = p0 + 1
    if (not is_yz_dt[p1]) and (o[p1] < c[p0] * 0.975):
        spx, sdt = o[p1], str(dts[p1])
    else:
        tp_px = round(bpx * 1.09, 2)
        end_p = min(L - 1, p0 + 4)
        spx, sdt = None, None
        for k in range(p1, end_p + 1):
            if is_yz_dt[k]: continue
            if h[k] >= tp_px:
                if is_zt[k]: spx, sdt = hold_zt_relay(d, k)
                else: spx, sdt = max(o[k], tp_px), str(dts[k])
                break
        if spx is None:
            ps = first_sellable_day(d, end_p)
            spx, sdt = c[ps], str(dts[ps])
    results["X6_CutWeak_Hold9"][i] = spx / bpx * (1.0 - COST) - 1.0
    exit_dts["X6_CutWeak_Hold9"][i] = sdt

    # 9. X9_MA5_Regress
    end_p = min(L - 1, p0 + 5)
    spx, sdt = None, None
    for k in range(p0 + 1, end_p + 1):
        if is_yz_dt[k]: continue
        ma5_prev = float(np.mean(c[max(0, k - 4):k])) if k >= 1 else bpx * 1.06
        tgt = max(bpx * 1.03, ma5_prev)
        if h[k] >= tgt:
            if is_zt[k]: spx, sdt = hold_zt_relay(d, k)
            else: spx, sdt = max(o[k], tgt), str(dts[k])
            break
    if spx is None:
        ps = first_sellable_day(d, end_p)
        spx, sdt = c[ps], str(dts[ps])
    results["X9_MA5_Regress"][i] = spx / bpx * (1.0 - COST) - 1.0
    exit_dts["X9_MA5_Regress"][i] = sdt

    # 10. X10_Dyn_Oversold
    ret10 = sub_df["prev_ret10"].iloc[i]
    dyn_tp = 0.08 if ret10 <= -0.30 else 0.05
    spx, sdt = run_fixed_tp(dyn_tp, 4)
    results["X10_Dyn_Oversold"][i] = spx / bpx * (1.0 - COST) - 1.0
    exit_dts["X10_Dyn_Oversold"][i] = sdt

    # 11. X_Rubber_3d_Protect: TP +4.5% in 3d, hard stop -5.5%
    end_p = min(L - 1, p0 + 3)
    tp_px = round(bpx * 1.045, 2)
    sl_px = round(bpx * 0.945, 2)
    spx, sdt = None, None
    for k in range(p0 + 1, end_p + 1):
        if is_yz_dt[k]: continue
        if o[k] <= sl_px:
            spx, sdt = o[k], str(dts[k])
            break
        if o[k] >= tp_px:
            if is_zt[k]: spx, sdt = hold_zt_relay(d, k)
            else: spx, sdt = o[k], str(dts[k])
            break
        if h[k] >= tp_px:
            if is_zt[k]: spx, sdt = hold_zt_relay(d, k)
            else: spx, sdt = tp_px, str(dts[k])
            break
        if l[k] <= sl_px:
            spx, sdt = sl_px, str(dts[k])
            break
    if spx is None:
        ps = first_sellable_day(d, end_p)
        spx, sdt = c[ps], str(dts[ps])
    results["X_Rubber_3d_Protect"][i] = spx / bpx * (1.0 - COST) - 1.0
    exit_dts["X_Rubber_3d_Protect"][i] = sdt

# Evaluate all exits on sub_df
eval_rows = []
is_mask_sub = (dt_v >= "2022-01-01") & (dt_v <= "2024-12-31")
oos_mask_sub = (dt_v >= "2025-01-01") & (dt_v <= "2026-11-10")

for ename in exit_names:
    r = results[ename]
    v = ~np.isnan(r)
    r_v = r[v]
    w = (r_v > 0).mean()
    m = r_v.mean()
    pl = (r_v[r_v > 0].mean() / abs(r_v[r_v < 0].mean())) if (r_v < 0).any() and (r_v > 0).any() else np.nan
    
    # IS
    r_is = r[v & is_mask_sub]
    w_is = (r_is > 0).mean() if len(r_is) > 0 else np.nan
    m_is = r_is.mean() if len(r_is) > 0 else np.nan
    
    # OOS
    r_oos = r[v & oos_mask_sub]
    w_oos = (r_oos > 0).mean() if len(r_oos) > 0 else np.nan
    m_oos = r_oos.mean() if len(r_oos) > 0 else np.nan
    
    eval_rows.append({
        "Exit_Method": ename,
        "N": v.sum(),
        "Win_Rate": round(w * 100, 1),
        "Mean_Ret": round(m * 100, 2),
        "PL_Ratio": round(pl, 2),
        "IS_Win": round(w_is * 100, 1),
        "IS_Mean": round(m_is * 100, 2),
        "OOS_Win": round(w_oos * 100, 1),
        "OOS_Mean": round(m_oos * 100, 2),
    })

eval_df = pd.DataFrame(eval_rows)
print("\n--- EXIT STRATEGIES EVALUATION ON HIGH CONVICTION CANDIDATES ---")
print(eval_df.to_string(index=False))

# Also save exit evaluation
eval_df.to_csv(f"{OUT_DIR}/s2_custom_exits_eval.csv", index=False)

#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Test Market Panic Threshold as hard filter to eliminate individual stock trap."""
import pickle
import numpy as np
import pandas as pd

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/p5_full_pry_universe"
df = pd.read_parquet(f"{OUT_DIR}/s2_pry_master_enriched.parquet")
with open(f"{OUT_DIR}/return_matrix_8x10.pkl", "rb") as f:
    mat = pickle.load(f)

base_gate = (
    (~df["is_st_or_delist"]) &
    (df["pre_c"] >= 2.0) &
    (df["touch_dt"]) &
    (~df["is_dt"]) &
    (~df["is_zt"]) &
    (df["close"] >= df["dt_price"] * 1.015) &
    (df["prev_yizi_dt_streak"].fillna(0) == 0) &
    (df["n_poison_total"] == 0)
)

r_mat = mat["ret"]["E5_tail1457_all"]
edt_mat = mat["exit_dt"]["E5_tail1457_all"]

# Sweep panic thresholds:
for mkt_dt_th in [0, 10, 20, 30, 40, 50]:
    mask = base_gate & (df["TAIL1457_mkt_dt_today"] >= mkt_dt_th) & (df["TAIL1457_clv"] >= 0.7) & (df["day0_vr"] >= 1.5)
    
    for ex in ["X10", "X9", "X6", "X4"]:
        r = r_mat[ex]
        edt = edt_mat[ex]
        v = mask & (~np.isnan(r))
        sub = df[v].copy()
        sub["ret"] = r[v]
        sub["exit_dt"] = edt[v]
        
        if len(sub) < 10:
            continue
            
        # Day-level stats
        day_grp = sub.groupby("dt_str")["ret"].mean()
        w_day = (day_grp > 0).mean()
        m_day = day_grp.mean()
        
        # Single position simulation: pick top rebound stock each day
        sub_sorted = sub.sort_values(["dt_str", "TAIL1457_rebound_pct"], ascending=[True, False]).reset_index(drop=True)
        trades_strict = []
        last_exit = "1900-01-01"
        for idx, row in sub_sorted.iterrows():
            if row["dt_str"] > last_exit:
                trades_strict.append(row)
                last_exit = row["exit_dt"]
        
        dfs = pd.DataFrame(trades_strict) if len(trades_strict) > 0 else pd.DataFrame()
        if len(dfs) > 0:
            w_s = (dfs["ret"] > 0).mean()
            m_s = dfs["ret"].mean()
            cum_s = np.prod(1.0 + dfs["ret"].values)
            pl_s = dfs["ret"][dfs["ret"] > 0].mean() / abs(dfs["ret"][dfs["ret"] < 0].mean()) if (dfs["ret"] < 0).any() else np.nan
        else:
            w_s, m_s, cum_s, pl_s = np.nan, np.nan, np.nan, np.nan
            
        print(f"MktDT >= {mkt_dt_th:2d} | Exit={ex:3s} | Days={len(day_grp):3d} DayWin={w_day*100:4.1f}% DayMean={m_day*100:5.2f}% | SinglePos: N={len(dfs):2d} Win={w_s*100:4.1f}% Mean={m_s*100:5.2f}% PL={pl_s:4.2f} NAV={cum_s:5.2f}x")
    print("-" * 80)

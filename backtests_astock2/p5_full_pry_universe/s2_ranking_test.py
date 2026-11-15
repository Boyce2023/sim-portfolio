#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Test ranking criteria for single position rotation: Oversold Depth vs Rebound Pct."""
import pickle
import numpy as np
import pandas as pd

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/p5_full_pry_universe"
df = pd.read_parquet(f"{OUT_DIR}/s2_pry_master_enriched.parquet")
with open(f"{OUT_DIR}/return_matrix_8x10.pkl", "rb") as f:
    mat = pickle.load(f)

# Core clean gate: strictly exclude demon stocks and yesterday yizi DT
base_gate = (
    (~df["is_st_or_delist"]) &
    (df["pre_c"] >= 2.0) &
    (df["touch_dt"]) &
    (~df["is_dt"]) &
    (~df["is_zt"]) &
    (df["close"] >= df["dt_price"] * 1.015) &
    (df["prev_yizi_dt_streak"].fillna(0) == 0) &
    (df["n_poison_total"] == 0) &
    (df["prev_zt20"].fillna(0) == 0) & # STRICT NO DEMON / NO ZT IN 20 DAYS!
    (df["prev_streak"].fillna(0) == 0) &
    (df["TAIL1457_is_true_yang"] == 1) # STRICT TRUE YANG
)

r_mat = mat["ret"]["E5_tail1457_all"]
edt_mat = mat["exit_dt"]["E5_tail1457_all"]

rankings = [
    ("Sort_Oversold_MA5_Asc", ["dt_str", "prev_c_ma5"], [True, True]),
    ("Sort_Oversold_Ret5_Asc", ["dt_str", "prev_ret5"], [True, True]),
    ("Sort_CLV_Desc", ["dt_str", "TAIL1457_clv"], [True, False]),
    ("Sort_VR_Desc", ["dt_str", "day0_vr"], [True, False]),
    ("Sort_Rebound_Desc", ["dt_str", "TAIL1457_rebound_pct"], [True, False]),
]

for rname, cols, asc in rankings:
    for ex in ["X10", "X9", "X5", "X4", "X3", "X6"]:
        r = r_mat[ex]
        edt = edt_mat[ex]
        v = base_gate & (~np.isnan(r))
        sub = df[v].copy()
        sub["ret"] = r[v]
        sub["exit_dt"] = edt[v]
        
        sub_sorted = sub.sort_values(cols, ascending=asc).reset_index(drop=True)
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
            
        print(f"{rname:22s} | Exit={ex:3s} | SinglePos: N={len(dfs):2d} Win={w_s*100:4.1f}% Mean={m_s*100:5.2f}% PL={pl_s:4.2f} NAV={cum_s:5.2f}x")
    print("-" * 80)

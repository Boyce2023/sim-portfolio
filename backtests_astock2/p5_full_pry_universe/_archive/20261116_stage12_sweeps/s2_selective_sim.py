#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Selective High-Conviction Single Position Strategy: Trade ONLY when edge exists."""
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

# Let's test specific high-conviction trigger conditions:
triggers = [
    # 1. Type B (1DT day2 pry) + True Yang + Doubled Volume + CLV >= 0.75
    ("TypeB_Yang_VR_CLV", base_gate & (df["prev_dt_streak"] == 1) & (df["TAIL1457_is_true_yang"] == 1) & (df["day0_vr"] >= 1.8) & (df["TAIL1457_clv"] >= 0.75)),
    
    # 2. Type C (2+ DT despair pry) + Clean + VR >= 1.5
    ("TypeC_Despair_VR", base_gate & (df["prev_dt_streak"] >= 2) & (df["day0_vr"] >= 1.5)),
    
    # 3. Market Panic >= 30 DT + Top 3 Rebound Pioneer + True Yang
    ("Panic30_Top3_Yang", base_gate & (df["TAIL1457_mkt_dt_today"] >= 30) & (df["rk_rebound_today"] <= 3) & (df["TAIL1457_is_true_yang"] == 1)),
    
    # 4. Oversold MA5 < -14% + Bald Leg CLV >= 0.8 + True Yang
    ("RubberMA5_Bald_Yang", base_gate & (df["prev_c_ma5"] < -0.14) & (df["TAIL1457_clv"] >= 0.8) & (df["TAIL1457_is_true_yang"] == 1)),
    
    # 5. Combined Selective System: Any of the 4 above!
    ("Combined_Elite_System", base_gate & (
        ((df["prev_dt_streak"] == 1) & (df["TAIL1457_is_true_yang"] == 1) & (df["day0_vr"] >= 1.8) & (df["TAIL1457_clv"] >= 0.75)) |
        ((df["prev_dt_streak"] >= 2) & (df["day0_vr"] >= 1.5)) |
        ((df["TAIL1457_mkt_dt_today"] >= 30) & (df["rk_rebound_today"] <= 3) & (df["TAIL1457_is_true_yang"] == 1)) |
        ((df["prev_c_ma5"] < -0.14) & (df["TAIL1457_clv"] >= 0.8) & (df["TAIL1457_is_true_yang"] == 1))
    )),
]

for tname, mask in triggers:
    for ex in ["X10", "X9", "X5", "X4", "X6"]:
        r = r_mat[ex]
        edt = edt_mat[ex]
        v = mask & (~np.isnan(r))
        sub = df[v].copy()
        sub["ret"] = r[v]
        sub["exit_dt"] = edt[v]
        
        if len(sub) < 5:
            continue
            
        sub_sorted = sub.sort_values(["dt_str", "s2_score" if "s2_score" in sub.columns else "TAIL1457_rebound_pct"], ascending=[True, False]).reset_index(drop=True)
        
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
            
        print(f"{tname:22s} | Exit={ex:3s} | TotalCands={len(sub):3d} | Strict: N={len(dfs):2d} Win={w_s*100:4.1f}% Mean={m_s*100:5.2f}% PL={pl_s:4.2f} NAV={cum_s:5.2f}x")
    print("-" * 85)

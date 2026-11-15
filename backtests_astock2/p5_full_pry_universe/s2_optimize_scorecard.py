#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Optimize Pure Integer Scorecard on IS (2022-2024) and test on OOS (2025-2026)."""
import os, pickle
import numpy as np
import pandas as pd

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/p5_full_pry_universe"

df = pd.read_parquet(f"{OUT_DIR}/s2_pry_master_enriched.parquet")
with open(f"{OUT_DIR}/return_matrix_8x10.pkl", "rb") as f:
    mat = pickle.load(f)

# Entry: E5_tail1457_all
r_mat = mat["ret"]["E5_tail1457_all"]
edt_mat = mat["exit_dt"]["E5_tail1457_all"]

# Base Gate
gate = (
    (~df["is_st_or_delist"]) &
    (df["pre_c"] >= 2.0) &
    (df["touch_dt"]) &
    (~df["is_dt"]) &
    (~df["is_zt"]) &
    (df["close"] >= df["dt_price"] * 1.015) &
    (df["prev_yizi_dt_streak"].fillna(0) == 0) &
    (df["n_poison_total"] == 0) &
    (df["prev_zt20"].fillna(0) <= 2) &
    (df["prev_streak"].fillna(0) <= 1)
)

# Calculate integer scores:
score = pd.Series(0, index=df.index, dtype=int)

# 1. Streak & Oversold tier
score += np.where(df["prev_dt_streak"] >= 2, 25, 0)
score += np.where(df["prev_dt_streak"] == 1, 20, 0)
score += np.where((df["prev_dt_streak"] == 0) & (df["prev_c_ma5"] < -0.14), 15, 0)

# 2. Micro geometry
score += np.where(df["TAIL1457_is_true_yang"] == 1, 15, 0)
score += np.where(df["TAIL1457_clv"] >= 0.8, 15, 0)
score += np.where(df["TAIL1457_rebound_pct"] >= 0.05, 10, 0)
score += np.where(df["day0_vr"] >= 1.8, 10, 0)

# 3. Market panic resonance
score += np.where(df["TAIL1457_mkt_dt_today"] >= 50, 15, np.where(df["TAIL1457_mkt_dt_today"] >= 25, 10, 0))
score += np.where(df["rk_rebound_today"] <= 3, 10, 0)

# 4. Capital & Catalyst
score += np.where(df["real_free_mcap"] < 3.5e9, 5, 0)
score += np.where((df["n_buyback90"] >= 1) | (df["ir30_cnt"] >= 1), 5, 0)

df["s2_score"] = score

df_dt = df["dt_str"].values
is_mask = (df_dt >= "2022-01-01") & (df_dt <= "2024-12-31")
oos_mask = (df_dt >= "2025-01-01") & (df_dt <= "2026-11-10")

print(f"Gate count: {gate.sum()}")
print("Score distribution under gate:")
print(df.loc[gate, "s2_score"].describe().to_dict())

thresholds = [40, 45, 50, 55, 60, 65, 70]
test_exits = ["X3", "X4", "X5", "X6", "X9", "X10"]

rows = []
for th in thresholds:
    mask_th = gate & (df["s2_score"] >= th)
    for x in test_exits:
        r = r_mat[x]
        valid = mask_th & (~np.isnan(r))
        n_tot = valid.sum()
        if n_tot < 10:
            continue
        
        r_tot = r[valid]
        w_tot = (r_tot > 0).mean()
        m_tot = r_tot.mean()
        pl_tot = (r_tot[r_tot > 0].mean() / abs(r_tot[r_tot < 0].mean())) if (r_tot < 0).any() and (r_tot > 0).any() else np.nan
        
        v_is = valid & is_mask
        n_is = v_is.sum()
        r_is = r[v_is] if n_is > 0 else np.array([])
        w_is = (r_is > 0).mean() if n_is > 0 else np.nan
        m_is = r_is.mean() if n_is > 0 else np.nan
        
        v_oos = valid & oos_mask
        n_oos = v_oos.sum()
        r_oos = r[v_oos] if n_oos > 0 else np.array([])
        w_oos = (r_oos > 0).mean() if n_oos > 0 else np.nan
        m_oos = r_oos.mean() if n_oos > 0 else np.nan
        
        rows.append({
            "Threshold": th,
            "Exit": x,
            "N_tot": n_tot,
            "Win_tot": round(w_tot * 100, 1),
            "Mean_tot": round(m_tot * 100, 2),
            "PL_tot": round(pl_tot, 2),
            "N_is": n_is,
            "Win_is": round(w_is * 100, 1),
            "Mean_is": round(m_is * 100, 2),
            "N_oos": n_oos,
            "Win_oos": round(w_oos * 100, 1),
            "Mean_oos": round(m_oos * 100, 2),
        })

res_df = pd.DataFrame(rows)
print("\n--- SCORECARD THRESHOLD SWEEP ---")
print(res_df.to_string(index=False))
res_df.to_csv(f"{OUT_DIR}/s2_scorecard_sweep.csv", index=False)

#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Task 1: Full-spectrum 6 Types x 14:57 Entries (E5, E6, E7) x 10 Exits (X1..X10) Census."""
import os, pickle
import numpy as np
import pandas as pd

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/p5_full_pry_universe"

df = pd.read_parquet(f"{OUT_DIR}/full_pry_master_enriched.parquet")
with open(f"{OUT_DIR}/return_matrix_8x10.pkl", "rb") as f:
    mat = pickle.load(f)

# Filter: non ST, pre_c >= 2.0
base_mask = (~df["is_st_or_delist"]) & (df["pre_c"] >= 2.0)

# Define 6 Types:
# A: prev_dt_streak == 0 & prev_zt20 == 0 (Flash crash panic bottom, no recent limit-up)
type_A = base_mask & (df["prev_dt_streak"].fillna(0) == 0) & (df["prev_zt20"].fillna(0) == 0)

# B: prev_dt_streak == 1 & prev_zt20 == 0 (Day 2 pry after 1 limit-down)
type_B = base_mask & (df["prev_dt_streak"].fillna(0) == 1) & (df["prev_zt20"].fillna(0) == 0)

# C: prev_dt_streak >= 2 & prev_zt20 == 0 (Multi limit-down despair pry)
type_C = base_mask & (df["prev_dt_streak"].fillna(0) >= 2) & (df["prev_zt20"].fillna(0) == 0)

# D: prev_yizi_dt_streak >= 1 (Yesterday one-word limit-down sealed, today first pry unsealed)
type_D = base_mask & (df["prev_yizi_dt_streak"].fillna(0) >= 1)

# E: prev_ret60 >= 0.25 & prev_ma20_up (Mid-term trend bull sudden first limit-down wash)
type_E = base_mask & (df["prev_ret60"].fillna(0) >= 0.25) & (df["prev_ma20_up"].fillna(False))

# F: prev_streak >= 1 | prev_zt20 >= 2 (Popular multi-board / demon stock nuclear dive pry)
type_F = base_mask & ((df["prev_streak"].fillna(0) >= 1) | (df["prev_zt20"].fillna(0) >= 2))

types = {
    "Type_A_NoZT_FirstDT": type_A,
    "Type_B_1DT_Day2Pry": type_B,
    "Type_C_2PlusDT_Despair": type_C,
    "Type_D_YiziDT_OpenPry": type_D,
    "Type_E_TrendBull_Wash": type_E,
    "Type_F_DemonZT_NuclearPry": type_F,
}

entries = ["E5_tail1457_all", "E6_tail1457_yang", "E7_tail1457_opendt"]
exits = [f"X{i}" for i in range(1, 11)]

results = []

df_dt = df["dt_str"].values
is_mask = (df_dt >= "2022-01-01") & (df_dt <= "2024-12-31")
oos_mask = (df_dt >= "2025-01-01") & (df_dt <= "2026-11-10")

for tname, tmask in types.items():
    for ename in entries:
        r_dict = mat["ret"][ename]
        for xname in exits:
            r = r_dict[xname]
            # Valid trades in this type & entry
            valid = tmask & (~np.isnan(r))
            n_tot = valid.sum()
            if n_tot < 5:
                continue
            r_tot = r[valid]
            win_tot = (r_tot > 0).mean()
            mean_tot = r_tot.mean()
            pl_tot = (r_tot[r_tot > 0].mean() / abs(r_tot[r_tot < 0].mean())) if (r_tot < 0).any() and (r_tot > 0).any() else np.nan
            
            # IS
            valid_is = valid & is_mask
            n_is = valid_is.sum()
            r_is = r[valid_is] if n_is > 0 else np.array([])
            win_is = (r_is > 0).mean() if n_is > 0 else np.nan
            mean_is = r_is.mean() if n_is > 0 else np.nan
            
            # OOS
            valid_oos = valid & oos_mask
            n_oos = valid_oos.sum()
            r_oos = r[valid_oos] if n_oos > 0 else np.array([])
            win_oos = (r_oos > 0).mean() if n_oos > 0 else np.nan
            mean_oos = r_oos.mean() if n_oos > 0 else np.nan
            
            results.append({
                "type": tname,
                "entry": ename,
                "exit": xname,
                "N_tot": n_tot,
                "win_tot": round(win_tot, 4),
                "mean_tot": round(mean_tot, 4),
                "pl_tot": round(pl_tot, 2) if not np.isnan(pl_tot) else np.nan,
                "N_is": n_is,
                "win_is": round(win_is, 4) if not np.isnan(win_is) else np.nan,
                "mean_is": round(mean_is, 4) if not np.isnan(mean_is) else np.nan,
                "N_oos": n_oos,
                "win_oos": round(win_oos, 4) if not np.isnan(win_oos) else np.nan,
                "mean_oos": round(mean_oos, 4) if not np.isnan(mean_oos) else np.nan,
            })

res_df = pd.DataFrame(results)
res_df.to_csv(f"{OUT_DIR}/s2_task1_census.csv", index=False)
print(f"Task 1 Census complete. Total grid rows: {len(res_df)}")

# Print top 15 by mean_tot with N >= 50
print("\n--- TOP 15 BY MEAN RETURN (N >= 50) ---")
top15 = res_df[res_df["N_tot"] >= 50].sort_values("mean_tot", ascending=False).head(15)
print(top15[["type", "entry", "exit", "N_tot", "win_tot", "mean_tot", "pl_tot", "mean_is", "mean_oos"]].to_string(index=False))

# Print summary per type for best exit (X3 or X10 or X2)
print("\n--- SUMMARY PER TYPE (E5 / E6 / E7 on X3: +5% TP 2d) ---")
sub = res_df[res_df["exit"] == "X3"]
print(sub[["type", "entry", "N_tot", "win_tot", "mean_tot", "pl_tot", "mean_is", "mean_oos"]].to_string(index=False))

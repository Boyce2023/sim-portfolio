#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Analyze Day-Level performance (removing clustering illusion) and single-position rotation."""
import pickle
import numpy as np
import pandas as pd

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/p5_full_pry_universe"
df = pd.read_parquet(f"{OUT_DIR}/s2_pry_master_enriched.parquet")
with open(f"{OUT_DIR}/return_matrix_8x10.pkl", "rb") as f:
    mat = pickle.load(f)

# Inspect date clustering under different sub-universes:
# Sub 1: Type B (prev_dt_streak == 1)
# Sub 2: Type C (prev_dt_streak >= 2)
# Sub 3: Type A (prev_dt_streak == 0 & prev_c_ma5 < -0.14)
# Sub 4: Type F (Demon ZT nuclear dive)

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

r_x10 = mat["ret"]["E5_tail1457_all"]["X10"]
r_x9 = mat["ret"]["E5_tail1457_all"]["X9"]
r_x5 = mat["ret"]["E5_tail1457_all"]["X5"]
r_x4 = mat["ret"]["E5_tail1457_all"]["X4"]
r_x6 = mat["ret"]["E5_tail1457_all"]["X6"]

for sub_name, mask in [
    ("All_Clean_Gate", base_gate),
    ("Type_B_1DT_Day2", base_gate & (df["prev_dt_streak"] == 1)),
    ("Type_C_2PlusDT_Despair", base_gate & (df["prev_dt_streak"] >= 2)),
    ("Type_A_Oversold_MA5_<-14%", base_gate & (df["prev_dt_streak"] == 0) & (df["prev_c_ma5"] < -0.14)),
    ("Combo_B_or_C_TrueYang", base_gate & (df["prev_dt_streak"] >= 1) & (df["TAIL1457_is_true_yang"] == 1)),
    ("High_Quality_Pioneer", base_gate & (df["prev_dt_streak"] >= 1) & (df["TAIL1457_clv"] >= 0.8) & (df["day0_vr"] >= 1.8)),
]:
    v = mask & (~np.isnan(r_x10))
    sub_df = df[v].copy()
    sub_df["ret_x10"] = r_x10[v]
    sub_df["ret_x9"] = r_x9[v]
    sub_df["ret_x5"] = r_x5[v]
    sub_df["ret_x4"] = r_x4[v]
    sub_df["ret_x6"] = r_x6[v]
    
    # 1. Total samples stats
    n_sample = len(sub_df)
    w_sample = (sub_df["ret_x10"] > 0).mean()
    m_sample = sub_df["ret_x10"].mean()
    
    # 2. Daily aggregate stats (average per day)
    day_grp = sub_df.groupby("dt_str")["ret_x10"].mean()
    n_days = len(day_grp)
    w_day = (day_grp > 0).mean()
    m_day = day_grp.mean()
    
    # 3. Days with < 5 candidates (non-clustering days)
    day_counts = sub_df.groupby("dt_str").size()
    normal_days = day_counts[day_counts <= 5].index
    day_grp_normal = sub_df[sub_df["dt_str"].isin(normal_days)].groupby("dt_str")["ret_x10"].mean()
    w_normal = (day_grp_normal > 0).mean() if len(day_grp_normal) > 0 else np.nan
    m_normal = day_grp_normal.mean() if len(day_grp_normal) > 0 else np.nan
    
    print(f"[{sub_name}]")
    print(f"  Total Trades: {n_sample} | Sample Win: {w_sample*100:.1f}% | Sample Mean: {m_sample*100:.2f}%")
    print(f"  Total Days: {n_days} | Day-level Win: {w_day*100:.1f}% | Day-level Mean: {m_day*100:.2f}%")
    print(f"  Normal Days (<=5 cands): {len(day_grp_normal)} | Normal-Day Win: {w_normal*100:.1f}% | Normal-Day Mean: {m_normal*100:.2f}%")
    print()

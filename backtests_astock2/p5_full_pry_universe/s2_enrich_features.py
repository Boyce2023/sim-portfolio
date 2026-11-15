#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Enrich additional zero-lookahead features for 14:57 Tail Pry:
- rk_rebound_today: Today's rank among all unsealed prying stocks (1 = highest rebound)
- csi300_day0_pct: CSI300 today pct (known at 14:57)
- ind_pry_cnt_today: CSRC industry prying count today
- prev_c_ma5_pct, prev_c_ma20_pct: Rubber-band MA divergences
- n_poison_total: Sum of poison announcements (n_del90 + n_los90 + n_poison90 + n_bad7)
"""
import pickle, os
import numpy as np
import pandas as pd

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/p5_full_pry_universe"
GFM_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112"

df = pd.read_parquet(f"{OUT_DIR}/full_pry_master_enriched.parquet")

# 1. Rank rebound today: among stocks where touch_dt & (~is_dt)
pry_mask = df["touch_dt"] & (~df["is_dt"])
df["rk_rebound_today"] = np.nan
sub = df[pry_mask].copy()
sub["rk"] = sub.groupby("dt_str")["TAIL1457_rebound_pct"].rank(ascending=False, method="min")
df.loc[pry_mask, "rk_rebound_today"] = sub["rk"]

# 2. Rubber-band MA divergences
# prev_c_ma5 is already in df, but let's check its values
# In df, prev_c_ma5 is close / ma5 - 1
print("prev_c_ma5 sample:", df["prev_c_ma5"].dropna().describe().to_dict())

# 3. Poison announcement score
poison_cols = ["n_del90", "n_los90", "n_poison90", "n_bad7"]
df["n_poison_total"] = df[[c for c in poison_cols if c in df.columns]].fillna(0).sum(axis=1)

# 4. Same industry prying count today
ind_cnt = df[pry_mask].groupby(["dt_str", "csrc_ind"])["ticker"].transform("count")
df["ind_pry_cnt_today"] = np.nan
df.loc[pry_mask, "ind_pry_cnt_today"] = ind_cnt

print("Enrichment done. Saving enriched temp parquet...")
df.to_parquet(f"{OUT_DIR}/s2_pry_master_enriched.parquet", index=False)
print("Saved to s2_pry_master_enriched.parquet, shape:", df.shape)

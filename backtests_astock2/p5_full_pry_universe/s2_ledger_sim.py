#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Full Ledger Simulation for S2 Champion Scorecard across multiple exits and allocation schemes."""
import os, pickle
import numpy as np
import pandas as pd

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/p5_full_pry_universe"
df = pd.read_parquet(f"{OUT_DIR}/s2_pry_master_enriched.parquet")
with open(f"{OUT_DIR}/return_matrix_8x10.pkl", "rb") as f:
    mat = pickle.load(f)

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

# Integer Scorecard
score = pd.Series(0, index=df.index, dtype=int)
score += np.where(df["prev_dt_streak"] >= 2, 25, 0)
score += np.where(df["prev_dt_streak"] == 1, 20, 0)
score += np.where((df["prev_dt_streak"] == 0) & (df["prev_c_ma5"] < -0.14), 15, 0)

score += np.where(df["TAIL1457_is_true_yang"] == 1, 15, 0)
score += np.where(df["TAIL1457_clv"] >= 0.8, 15, 0)
score += np.where(df["TAIL1457_rebound_pct"] >= 0.05, 10, 0)
score += np.where(df["day0_vr"] >= 1.8, 10, 0)

score += np.where(df["TAIL1457_mkt_dt_today"] >= 50, 15, np.where(df["TAIL1457_mkt_dt_today"] >= 25, 10, 0))
score += np.where(df["rk_rebound_today"] <= 3, 10, 0)

score += np.where(df["real_free_mcap"] < 3.5e9, 5, 0)
score += np.where((df["n_buyback90"] >= 1) | (df["ir30_cnt"] >= 1), 5, 0)
df["s2_score"] = score

def run_simulation(th=50, exit_code="X10"):
    cands = df[gate & (df["s2_score"] >= th)].copy()
    
    # Attach return and exit_dt
    cands["ret"] = mat["ret"]["E5_tail1457_all"][exit_code][cands.index]
    cands["exit_dt"] = mat["exit_dt"]["E5_tail1457_all"][exit_code][cands.index]
    
    # Valid
    cands = cands[~cands["ret"].isna()].copy()
    cands = cands.sort_values(["dt_str", "s2_score", "TAIL1457_rebound_pct"], ascending=[True, False, False]).reset_index(drop=True)
    
    # 1. Single Position Rotation: Strict (buy_date > prev_exit_date)
    trades_strict = []
    last_exit = "1900-01-01"
    for idx, row in cands.iterrows():
        bdt = row["dt_str"]
        if bdt > last_exit:
            trades_strict.append(row)
            last_exit = row["exit_dt"]
    df_strict = pd.DataFrame(trades_strict) if len(trades_strict) > 0 else pd.DataFrame()
    
    # 2. Single Position Rotation: Day-Rebuy (buy_date >= prev_exit_date)
    trades_day = []
    last_exit = "1900-01-01"
    for idx, row in cands.iterrows():
        bdt = row["dt_str"]
        if bdt >= last_exit:
            trades_day.append(row)
            last_exit = row["exit_dt"]
    df_day = pd.DataFrame(trades_day) if len(trades_day) > 0 else pd.DataFrame()

    # 3. Dual Half-Position Rotation (2 slots, 50% each)
    slots = ["1900-01-01", "1900-01-01"]
    trades_dual = []
    for idx, row in cands.iterrows():
        bdt = row["dt_str"]
        # Find available slot
        avail = [i for i, ex in enumerate(slots) if bdt > ex]
        if avail:
            chosen = avail[0]
            trades_dual.append((row, chosen))
            slots[chosen] = row["exit_dt"]
    df_dual = pd.DataFrame([r[0] for r in trades_dual]) if len(trades_dual) > 0 else pd.DataFrame()

    return cands, df_strict, df_day, df_dual

# Test simulation across thresholds and exits
for th in [45, 50, 55]:
    for ex in ["X10", "X9", "X6", "X5"]:
        cands, dfs, dfd, dfdual = run_simulation(th, ex)
        if len(dfs) == 0:
            continue
        cum_s = np.prod(1.0 + dfs["ret"].values)
        cum_d = np.prod(1.0 + dfd["ret"].values)
        win_s = (dfs["ret"].values > 0).mean()
        pl_s = dfs["ret"][dfs["ret"] > 0].mean() / abs(dfs["ret"][dfs["ret"] < 0].mean())
        print(f"TH={th} Exit={ex} | All Cands={len(cands)} | Strict: N={len(dfs)} Win={win_s*100:.1f}% PL={pl_s:.2f} NAV={cum_s:.2f}x | Day: N={len(dfd)} NAV={cum_d:.2f}x")

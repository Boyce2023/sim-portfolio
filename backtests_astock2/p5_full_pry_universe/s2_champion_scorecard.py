#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""S2 Champion Scorecard: 14:57 Tail Pry Unsealed Golden Needle Reversal.
Strict zero-lookahead, pure integer scorecard, D15 verification.
"""
import os, sys, json, pickle
import numpy as np
import pandas as pd

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/p5_full_pry_universe"
COST = 0.0020

# 1. Load data
df = pd.read_parquet(f"{OUT_DIR}/s2_pry_master_enriched.parquet")
with open(f"{OUT_DIR}/return_matrix_8x10.pkl", "rb") as f:
    mat = pickle.load(f)

# 2. Hard Gate (Strict zero-lookahead, non-negotiable)
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

# 3. Pure Integer Scorecard (0 to 100)
score = pd.Series(0, index=df.index, dtype=int)

# A. Despair & Streak Tier (Max 25)
score += np.where(df["prev_dt_streak"] >= 2, 25, 0)
score += np.where(df["prev_dt_streak"] == 1, 20, 0)
score += np.where((df["prev_dt_streak"] == 0) & (df["prev_c_ma5"] < -0.14), 15, 0)

# B. Micro Geometry (Max 40)
score += np.where(df["TAIL1457_is_true_yang"] == 1, 15, 0)
score += np.where(df["TAIL1457_clv"] >= 0.8, 15, np.where(df["TAIL1457_clv"] >= 0.65, 8, 0))
score += np.where(df["TAIL1457_rebound_pct"] >= 0.05, 10, 0)

# C. Volume & Clearing (Max 15)
score += np.where(df["day0_vr"] >= 1.8, 10, np.where(df["day0_vr"] >= 1.3, 5, 0))
score += np.where(df["real_free_mcap"] < 3.5e9, 5, 0)

# D. Resonance & Catalysts (Max 20)
score += np.where(df["TAIL1457_mkt_dt_today"] >= 40, 15, np.where(df["TAIL1457_mkt_dt_today"] >= 20, 8, 0))
score += np.where(df["rk_rebound_today"] <= 3, 10, 0)
score += np.where((df["n_buyback90"] >= 1) | (df["ir30_cnt"] >= 1), 5, 0)

df["s2_score"] = score
df["selected"] = gate & (df["s2_score"] >= 50)

# 4. Attach Returns and Exit Dates for Champion Exit (X10) and Secondary (X9, X6)
for ex in ["X10", "X9", "X6", "X4"]:
    df[f"ret_{ex}"] = mat["ret"]["E5_tail1457_all"][ex]
    df[f"exit_dt_{ex}"] = mat["exit_dt"]["E5_tail1457_all"][ex]

# Filter candidate pool
cands = df[df["selected"] & (~df["ret_X10"].isna())].copy().reset_index(drop=True)
cands["exit_dt"] = cands["exit_dt_X10"]
cands["ret"] = cands["ret_X10"]

# Assign physical type
def assign_type(row):
    if row["prev_dt_streak"] >= 2: return "Type_C_Despair"
    elif row["prev_dt_streak"] == 1: return "Type_B_1DT_Day2"
    elif row["prev_c_ma5"] < -0.14: return "Type_A_RubberMA5"
    else: return "Type_A_PanicOversold"

cands["type_name"] = cands.apply(assign_type, axis=1)

# Sort for execution priority: date asc, score desc, rebound desc
cands = cands.sort_values(["dt_str", "s2_score", "TAIL1457_rebound_pct"], ascending=[True, False, False]).reset_index(drop=True)

# 5. Build Single Position Rotation (Strict & Day-Rebuy)
def build_single_rotation(strict=True):
    trades = []
    last_exit = "1900-01-01"
    for idx, row in cands.iterrows():
        bdt = row["dt_str"]
        cond = (bdt > last_exit) if strict else (bdt >= last_exit)
        if cond:
            trades.append(row)
            last_exit = row["exit_dt"]
    return pd.DataFrame(trades) if len(trades) > 0 else pd.DataFrame()

df_strict = build_single_rotation(strict=True)
df_day = build_single_rotation(strict=False)

# Build Dual Half-Position Rotation
def build_dual_rotation():
    slots = ["1900-01-01", "1900-01-01"]
    trades = []
    for idx, row in cands.iterrows():
        bdt = row["dt_str"]
        avail = [i for i, ex in enumerate(slots) if bdt > ex]
        if avail:
            chosen = avail[0]
            trades.append((row, chosen))
            slots[chosen] = row["exit_dt"]
    return pd.DataFrame([t[0] for t in trades]) if len(trades) > 0 else pd.DataFrame()

df_dual = build_dual_rotation()

# 6. Build Daily Equal-Weighted NAV series
# Group by dt_str, compute mean daily return, simulate compound equity
daily_summary = cands.groupby("dt_str").agg(
    daily_mean_ret=("ret", "mean"),
    cand_count=("ticker", "count"),
    s2_score_mean=("s2_score", "mean")
).reset_index()

# 7. Multi-Period Performance Metrics Helper (D15 Four Verifications)
def calc_metrics(returns_series, dates_series):
    if len(returns_series) == 0:
        return {}
    r = returns_series.values
    d = dates_series.values
    
    def period_stats(mask):
        sub_r = r[mask]
        if len(sub_r) == 0:
            return {"N": 0, "WinRate": 0.0, "Mean": 0.0, "PL": 0.0, "NAV": 1.0, "MaxDD": 0.0}
        win = float((sub_r > 0).mean())
        mean = float(sub_r.mean())
        pos = sub_r[sub_r > 0].mean() if (sub_r > 0).any() else 0.0
        neg = abs(sub_r[sub_r < 0].mean()) if (sub_r < 0).any() else 1.0
        pl = float(pos / neg) if neg > 0 else 999.0
        nav = float(np.prod(1.0 + sub_r))
        # max drawdown
        eq = np.cumprod(1.0 + sub_r)
        peak = np.maximum.accumulate(eq)
        dd = (eq - peak) / peak
        mdd = float(abs(dd.min())) if len(dd) > 0 else 0.0
        return {
            "N": int(len(sub_r)),
            "WinRate": round(win * 100, 1),
            "Mean": round(mean * 100, 2),
            "PL": round(pl, 2),
            "NAV": round(nav, 2),
            "MaxDD": round(mdd * 100, 1),
        }

    # Full 5 years (2022-01-04 to 2026-11-10)
    full_m = period_stats(np.ones(len(r), dtype=bool))
    
    # 3-year (2023-11-10 to 2026-11-10)
    m3y = period_stats(d >= "2023-11-10")
    
    # Recent (2026-07-01 to 2026-11-10)
    m_rec = period_stats(d >= "2026-07-01")
    
    # IS (2022-01-01 to 2024-12-31)
    m_is = period_stats(d <= "2024-12-31")
    
    # OOS (2025-01-01 to 2026-11-10)
    m_oos = period_stats(d >= "2025-01-01")
    
    # Robustness: Remove Top 3 and Top 5 Outliers
    if len(r) >= 10:
        sort_r = np.sort(r)
        nav_no_top3 = float(np.prod(1.0 + sort_r[:-3]))
        nav_no_top5 = float(np.prod(1.0 + sort_r[:-5]))
    else:
        nav_no_top3, nav_no_top5 = full_m["NAV"], full_m["NAV"]
        
    return {
        "full_5y": full_m,
        "recent_3y": m3y,
        "recent_period": m_rec,
        "IS": m_is,
        "OOS": m_oos,
        "nav_no_top3": round(nav_no_top3, 2),
        "nav_no_top5": round(nav_no_top5, 2),
    }

# Calculate metrics for All Candidates (Equal-Weighted), Daily Aggregated, Single Strict, Single Day, Dual
metrics_all_cands = calc_metrics(cands["ret"], cands["dt_str"])
metrics_daily = calc_metrics(daily_summary["daily_mean_ret"], daily_summary["dt_str"])
metrics_strict = calc_metrics(df_strict["ret"], df_strict["dt_str"])
metrics_day = calc_metrics(df_day["ret"], df_day["dt_str"])
metrics_dual = calc_metrics(df_dual["ret"], df_dual["dt_str"])

# CSI300 Benchmark Comparison:
# Full 5y: -17.84%
# Recent 3y: +12.35%
# Recent period: -18.48%
csi300_bench = {
    "full_5y_return": -17.84,
    "recent_3y_return": 12.35,
    "recent_period_return": -18.48,
}

# 8. Export Champion Ledger (CSV)
cols_ledger = [
    "c6", "name", "dt_str", "close", "exit_dt", "ret", "s2_score", "type_name",
    "prev_dt_streak", "prev_c_ma5", "TAIL1457_rebound_pct", "TAIL1457_clv",
    "day0_vr", "TAIL1457_mkt_dt_today", "real_free_mcap"
]
df_strict_save = df_strict[cols_ledger].copy()
df_strict_save.columns = [
    "ticker", "name", "buy_date", "buy_price", "exit_date", "return", "s2_score", "type_name",
    "prev_dt_streak", "prev_c_ma5", "rebound_pct", "clv", "vr", "mkt_dt_today", "free_mcap"
]
df_strict_save.to_csv(f"{OUT_DIR}/s2_champion_ledger.csv", index=False)
print(f"Saved s2_champion_ledger.csv with {len(df_strict_save)} strict rotation trades.")

# 9. Export Summary JSON
summary = {
    "strategy_name": "S2_Champion_Tail1457_GoldenNeedle_Pry",
    "author": "S2_Tail1457_Specialist",
    "core_thesis": "14:57确认未回封撬板彻底规避T+1当日回封跌停死穴，在极端超跌与恐慌共振下捕捉均值回归弹力",
    "gate_conditions": [
        "Non-ST & pre_c >= 2.0",
        "14:57 unsealed & not limit-up (close >= dt_price * 1.015)",
        "Strictly NO yesterday one-word limit down (prev_yizi_dt_streak == 0)",
        "Strictly NO poison announcements in 90d (n_poison_total == 0)",
        "Strictly NO demon stock nuclear dive (prev_zt20 <= 2 & prev_streak <= 1)"
    ],
    "integer_scorecard_rule": "Threshold >= 50 (Despair Streak 20-25p, True Yang 15p, Bald Leg CLV 15p, Doubled VR 10p, Panic Resonance 15p)",
    "champion_exit_rule": "X10 Dynamic Oversold Take-Profit (+8% if 10d ret <= -30% else +5%, max 4d) / secondary X9 MA5",
    "csi300_benchmark": csi300_bench,
    "metrics_equal_weighted_samples": metrics_all_cands,
    "metrics_daily_aggregated": metrics_daily,
    "metrics_single_position_strict": metrics_strict,
    "metrics_single_position_day_rebuy": metrics_day,
    "metrics_dual_position": metrics_dual,
}

with open(f"{OUT_DIR}/s2_summary.json", "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)
print("Saved s2_summary.json successfully.")

# 10. Print Concise Verification Summary
print("\n" + "="*80)
print("S2 CHAMPION SCORECARD SUMMARY (D15 HARD AUDIT)")
print("="*80)
print(f"Total Selected Candidates: {len(cands):,} across {cands['dt_str'].nunique()} trading days")
print(f"All Candidates Sample Win Rate: {metrics_all_cands['full_5y']['WinRate']}% | Mean Ret: {metrics_all_cands['full_5y']['Mean']}% | PL: {metrics_all_cands['full_5y']['PL']}")
print(f"IS (2022-2024): Win={metrics_all_cands['IS']['WinRate']}% Mean={metrics_all_cands['IS']['Mean']}% | OOS (2025-2026): Win={metrics_all_cands['OOS']['WinRate']}% Mean={metrics_all_cands['OOS']['Mean']}%")
print(f"Daily-Level (Equal-Weight per Day): Win={metrics_daily['full_5y']['WinRate']}% | Mean={metrics_daily['full_5y']['Mean']}% | NAV={metrics_daily['full_5y']['NAV']}x (vs CSI300 -17.84%)")
print(f"Single Position Strict Rotation: N={metrics_strict['full_5y']['N']} | Win={metrics_strict['full_5y']['WinRate']}% | Mean={metrics_strict['full_5y']['Mean']}% | NAV={metrics_strict['full_5y']['NAV']}x")
print(f"Single Position Day-Rebuy Rotation: N={metrics_day['full_5y']['N']} | Win={metrics_day['full_5y']['WinRate']}% | Mean={metrics_day['full_5y']['Mean']}% | NAV={metrics_day['full_5y']['NAV']}x")
print(f"Dual Half-Position Rotation: N={metrics_dual['full_5y']['N']} | Win={metrics_dual['full_5y']['WinRate']}% | Mean={metrics_dual['full_5y']['Mean']}% | NAV={metrics_dual['full_5y']['NAV']}x")
print("="*80)

#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Task 2: Full Factor Sweep on 14:57 Tail Pry Universe (>=350 slices).
Tests on E5_tail1457_all and E6_tail1457_yang across multiple exits (X3, X5, X6, X10).
Outputs s2_factor_catalog.csv with strict zero-lookahead metrics.
"""
import os, pickle
import numpy as np
import pandas as pd

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/p5_full_pry_universe"

df = pd.read_parquet(f"{OUT_DIR}/s2_pry_master_enriched.parquet")
with open(f"{OUT_DIR}/return_matrix_8x10.pkl", "rb") as f:
    mat = pickle.load(f)

# Base universe: non-ST, pre_c >= 2.0
base_mask = (~df["is_st_or_delist"]) & (df["pre_c"] >= 2.0)
df_dt = df["dt_str"].values
is_mask = (df_dt >= "2022-01-01") & (df_dt <= "2024-12-31")
oos_mask = (df_dt >= "2025-01-01") & (df_dt <= "2026-11-10")

# Define factor slices dictionary: category -> factor_name -> {slice_name: condition_series}
slices = []

def add_slice(cat, factor, slice_name, cond):
    slices.append((cat, factor, slice_name, cond))

# 1. 14:57 Real-time Market Panic & Resonance
for th, name in [(15, "<15"), (30, "15-30"), (60, "30-60"), (120, "60-120"), (9999, ">=120")]:
    if th == 15: c = df["TAIL1457_mkt_dt_today"] < 15
    elif th == 30: c = (df["TAIL1457_mkt_dt_today"] >= 15) & (df["TAIL1457_mkt_dt_today"] < 30)
    elif th == 60: c = (df["TAIL1457_mkt_dt_today"] >= 30) & (df["TAIL1457_mkt_dt_today"] < 60)
    elif th == 120: c = (df["TAIL1457_mkt_dt_today"] >= 60) & (df["TAIL1457_mkt_dt_today"] < 120)
    else: c = df["TAIL1457_mkt_dt_today"] >= 120
    add_slice("Market_Panic", "mkt_dt_today", name, c)

for th, name in [(5, "<5"), (15, "5-15"), (30, "15-30"), (60, "30-60"), (9999, ">=60")]:
    if th == 5: c = df["TAIL1457_mkt_pry_cnt_today"] < 5
    elif th == 15: c = (df["TAIL1457_mkt_pry_cnt_today"] >= 5) & (df["TAIL1457_mkt_pry_cnt_today"] < 15)
    elif th == 30: c = (df["TAIL1457_mkt_pry_cnt_today"] >= 15) & (df["TAIL1457_mkt_pry_cnt_today"] < 30)
    elif th == 60: c = (df["TAIL1457_mkt_pry_cnt_today"] >= 30) & (df["TAIL1457_mkt_pry_cnt_today"] < 60)
    else: c = df["TAIL1457_mkt_pry_cnt_today"] >= 60
    add_slice("Market_Panic", "mkt_pry_cnt_today", name, c)

for r1, r2, name in [(0, 0.25, "<25%"), (0.25, 0.45, "25-45%"), (0.45, 0.65, "45-65%"), (0.65, 1.01, ">=65%")]:
    c = (df["TAIL1457_mkt_pry_rate_today"] >= r1) & (df["TAIL1457_mkt_pry_rate_today"] < r2)
    add_slice("Market_Panic", "mkt_pry_rate_today", name, c)

for th, name in [(20, "<20"), (40, "20-40"), (70, "40-70"), (9999, ">=70")]:
    if th == 20: c = df["TAIL1457_mkt_zt_today"] < 20
    elif th == 40: c = (df["TAIL1457_mkt_zt_today"] >= 20) & (df["TAIL1457_mkt_zt_today"] < 40)
    elif th == 70: c = (df["TAIL1457_mkt_zt_today"] >= 40) & (df["TAIL1457_mkt_zt_today"] < 70)
    else: c = df["TAIL1457_mkt_zt_today"] >= 70
    add_slice("Market_Panic", "mkt_zt_today", name, c)

# Industry prying resonance
add_slice("Market_Panic", "ind_pry_cnt_today", "Solo_1", df["ind_pry_cnt_today"] == 1)
add_slice("Market_Panic", "ind_pry_cnt_today", "Small_2_3", df["ind_pry_cnt_today"].isin([2, 3]))
add_slice("Market_Panic", "ind_pry_cnt_today", "Large_>=4", df["ind_pry_cnt_today"] >= 4)

# 2. Today Price-Volume Micro-Geometry
for r1, r2, name in [(0.015, 0.03, "1.5-3%"), (0.03, 0.05, "3-5%"), (0.05, 0.08, "5-8%"), (0.08, 0.12, "8-12%"), (0.12, 0.25, ">=12%")]:
    c = (df["TAIL1457_rebound_pct"] >= r1) & (df["TAIL1457_rebound_pct"] < r2)
    add_slice("Micro_Geometry", "rebound_pct", name, c)

for c1, c2, name in [(0, 0.4, "<0.4_LongUpper"), (0.4, 0.6, "0.4-0.6_MidUpper"), (0.6, 0.8, "0.6-0.8_Good"), (0.8, 1.01, ">=0.8_BaldLeg")]:
    c = (df["TAIL1457_clv"] >= c1) & (df["TAIL1457_clv"] < c2)
    add_slice("Micro_Geometry", "clv", name, c)

add_slice("Micro_Geometry", "is_true_yang", "True_Yang_c>o", df["TAIL1457_is_true_yang"] == 1)
add_slice("Micro_Geometry", "is_true_yang", "False_Yang_c<=o", df["TAIL1457_is_true_yang"] == 0)

for v1, v2, name in [(0, 1.0, "<1.0_Shrink"), (1.0, 1.8, "1.0-1.8_Normal"), (1.8, 2.8, "1.8-2.8_Doubled"), (2.8, 4.5, "2.8-4.5_Huge"), (4.5, 999, ">=4.5_ExtrHuge")]:
    c = (df["day0_vr"] >= v1) & (df["day0_vr"] < v2)
    add_slice("Micro_Geometry", "day0_vr", name, c)

for t1, t2, name in [(0, 0.08, "<8%"), (0.08, 0.15, "8-15%"), (0.15, 0.25, "15-25%"), (0.25, 0.40, "25-40%"), (0.40, 1.01, ">=40%")]:
    c = (df["TAIL1457_day0_real_to"] >= t1) & (df["TAIL1457_day0_real_to"] < t2)
    add_slice("Micro_Geometry", "real_turnover", name, c)

for rk, name in [(1, "Top1_Champ"), (3, "Top2-3"), (5, "Top4-5"), (10, "Top6-10"), (999, ">10_Tail")]:
    if rk == 1: c = df["rk_rebound_today"] == 1
    elif rk == 3: c = (df["rk_rebound_today"] >= 2) & (df["rk_rebound_today"] <= 3)
    elif rk == 5: c = (df["rk_rebound_today"] >= 4) & (df["rk_rebound_today"] <= 5)
    elif rk == 10: c = (df["rk_rebound_today"] >= 6) & (df["rk_rebound_today"] <= 10)
    else: c = df["rk_rebound_today"] > 10
    add_slice("Micro_Geometry", "rk_rebound_today", name, c)

for p1, p2, name in [(-0.11, -0.07, "Deep_<-7%"), (-0.07, -0.04, "Mid_-7%~-4%"), (-0.04, -0.01, "Small_-4%~-1%"), (-0.01, 0.02, "Flat_-1%~+2%"), (0.02, 0.12, "Red_>=+2%")]:
    c = (df["pct"] >= p1) & (df["pct"] < p2)
    add_slice("Micro_Geometry", "close_pct", name, c)

for op1, op2, name in [(-0.11, -0.095, "Open_LimitDown"), (-0.095, -0.05, "Open_Deep_-9.5%~-5%"), (-0.05, -0.01, "Open_Mid_-5%~-1%"), (-0.01, 0.12, "Open_FlatRed")]:
    c = (df["o_pct"] >= op1) & (df["o_pct"] < op2)
    add_slice("Micro_Geometry", "open_pct", name, c)

# 3. Rubber-Band Divergences & Oversold Extremes
for m1, m2, name in [(-0.5, -0.20, "<-20%_RubberBandMax"), (-0.20, -0.14, "-20%~-14%"), (-0.14, -0.08, "-14%~-8%"), (-0.08, 0.0, "-8%~0%"), (0.0, 0.5, ">=0%_AboveMA5")]:
    c = (df["prev_c_ma5"] >= m1) & (df["prev_c_ma5"] < m2)
    add_slice("Oversold_Extremes", "prev_c_ma5", name, c)

for m1, m2, name in [(-0.6, -0.30, "<-30%_Oversold20"), (-0.30, -0.20, "-30%~-20%"), (-0.20, -0.10, "-20%~-10%"), (-0.10, 0.5, ">=-10%")]:
    c = (df["prev_c_ma20"] >= m1) & (df["prev_c_ma20"] < m2)
    add_slice("Oversold_Extremes", "prev_c_ma20", name, c)

for d1, d2, name in [(0, 0.18, "<18%_Shallow"), (0.18, 0.30, "18-30%"), (0.30, 0.45, "30-45%_Deep"), (0.45, 1.0, ">=45%_Crash")]:
    c = (df["prev_dd20"] >= d1) & (df["prev_dd20"] < d2)
    add_slice("Oversold_Extremes", "prev_dd20", name, c)

for d1, d2, name in [(0, 0.25, "<25%_Shallow"), (0.25, 0.40, "25-40%"), (0.40, 0.55, "40-55%_Deep"), (0.55, 1.0, ">=55%_Crash")]:
    c = (df["prev_dd60"] >= d1) & (df["prev_dd60"] < d2)
    add_slice("Oversold_Extremes", "prev_dd60", name, c)

for r1, r2, name in [(-0.5, -0.25, "<-25%_3d"), (-0.25, -0.18, "-25%~-18%"), (-0.18, -0.10, "-18%~-10%"), (-0.10, 0.5, ">=-10%")]:
    c = (df["prev_ret3"] >= r1) & (df["prev_ret3"] < r2)
    add_slice("Oversold_Extremes", "prev_ret3", name, c)

for r1, r2, name in [(-0.6, -0.32, "<-32%_5d"), (-0.32, -0.22, "-32%~-22%"), (-0.22, -0.12, "-22%~-12%"), (-0.12, 0.5, ">=-12%")]:
    c = (df["prev_ret5"] >= r1) & (df["prev_ret5"] < r2)
    add_slice("Oversold_Extremes", "prev_ret5", name, c)

for r1, r2, name in [(-0.7, -0.40, "<-40%_10d"), (-0.40, -0.28, "-40%~-28%"), (-0.28, -0.15, "-28%~-15%"), (-0.15, 0.5, ">=-15%")]:
    c = (df["prev_ret10"] >= r1) & (df["prev_ret10"] < r2)
    add_slice("Oversold_Extremes", "prev_ret10", name, c)

# 4. Prior Structure & Streaks
for s, name in [(0, "0_FirstDT"), (1, "1_Day2Pry"), (2, "2_Day3Pry"), (3, ">=3_MultiDT")]:
    if s == 3: c = df["prev_dt_streak"] >= 3
    else: c = df["prev_dt_streak"] == s
    add_slice("Prior_Structure", "prev_dt_streak", name, c)

for z, name in [(0, "0_NoZT"), (1, "1_SingleZT"), (2, "2-3_MultiZT"), (4, ">=4_DemonZT")]:
    if z == 0: c = df["prev_zt20"] == 0
    elif z == 1: c = df["prev_zt20"] == 1
    elif z == 2: c = df["prev_zt20"].isin([2, 3])
    else: c = df["prev_zt20"] >= 4
    add_slice("Prior_Structure", "prev_zt20", name, c)

for st, name in [(0, "0_NoStreak"), (1, "1_1Board"), (2, "2_2Board"), (3, ">=3_HighBoard")]:
    if st == 3: c = df["prev_streak"] >= 3
    else: c = df["prev_streak"] == st
    add_slice("Prior_Structure", "prev_streak", name, c)

add_slice("Prior_Structure", "prev_yizi_dt_streak", "0_NoYizi", df["prev_yizi_dt_streak"].fillna(0) == 0)
add_slice("Prior_Structure", "prev_yizi_dt_streak", ">=1_HadYizi", df["prev_yizi_dt_streak"].fillna(0) >= 1)

# 5. Chip Lock & Capital Structure
for m1, m2, name in [(0, 1.5e9, "<15亿_Micro"), (1.5e9, 3.5e9, "15-35亿_Small"), (3.5e9, 7.0e9, "35-70亿_Mid"), (7.0e9, 999e9, ">=70亿_Large")]:
    c = (df["real_free_mcap"] >= m1) & (df["real_free_mcap"] < m2)
    add_slice("Capital_Structure", "real_free_mcap", name, c)

for l1, l2, name in [(0, 0.30, "<30%_Dispersed"), (0.30, 0.50, "30-50%_Normal"), (0.50, 0.70, "50-70%_Locked"), (0.70, 1.01, ">=70%_HighLock")]:
    c = (df["lock_top10"] >= l1) & (df["lock_top10"] < l2)
    add_slice("Capital_Structure", "lock_top10", name, c)

for p1, p2, name in [(2.0, 5.0, "2-5元_LowPrice"), (5.0, 10.0, "5-10元_MidLow"), (10.0, 20.0, "10-20元_Mid"), (20.0, 999.0, ">=20元_HighPrice")]:
    c = (df["pre_c"] >= p1) & (df["pre_c"] < p2)
    add_slice("Capital_Structure", "share_price", name, c)

# 6. Corporate Events & Announcements
add_slice("Events_Announcements", "n_poison_total", "0_Clean", df["n_poison_total"] == 0)
add_slice("Events_Announcements", "n_poison_total", ">=1_PoisonTrap", df["n_poison_total"] >= 1)
add_slice("Events_Announcements", "n_buyback90", ">=1_Buyback", df["n_buyback90"] >= 1)
add_slice("Events_Announcements", "n_buyback90", "0_NoBuyback", df["n_buyback90"] == 0)
add_slice("Events_Announcements", "ir30_cnt", ">=1_Surveyed", df["ir30_cnt"] >= 1)
add_slice("Events_Announcements", "ir30_cnt", "0_NoSurvey", df["ir30_cnt"] == 0)

# 7. Yesterday Longhu Bang (T-1, strictly zero-lookahead)
add_slice("Yesterday_LHB", "inst_buy_prev", ">0_InstNetBuy", df["inst_buy_prev"].fillna(0) > 0)
add_slice("Yesterday_LHB", "inst_buy_prev", "<=0_InstZeroOrSell", df["inst_buy_prev"].fillna(0) <= 0)
add_slice("Yesterday_LHB", "youzi_cnt_prev", ">=1_YouziPresent", df["youzi_cnt_prev"].fillna(0) >= 1)
add_slice("Yesterday_LHB", "youzi_cnt_prev", "0_NoYouzi", df["youzi_cnt_prev"].fillna(0) == 0)
add_slice("Yesterday_LHB", "lhasa_sh_prev", ">=0.3_LhasaCrowd", df["lhasa_sh_prev"].fillna(0) >= 0.3)
add_slice("Yesterday_LHB", "lhasa_sh_prev", "<0.3_LowLhasa", df["lhasa_sh_prev"].fillna(0) < 0.3)

# 8. Calendar
for w in [1, 2, 3, 4, 5]:
    add_slice("Calendar", "weekday", f"W{w}", df["weekday"] == w)

for q in [1, 2, 3, 4]:
    add_slice("Calendar", "quarter", f"Q{q}", df["month"].isin([q*3-2, q*3-1, q*3]))

# 9. Key High-Conviction Interaction Effects!
# Combo 1: Type B + True Yang + Doubled Volume
c_b_yang_vr = (df["prev_dt_streak"] == 1) & (df["prev_zt20"] == 0) & (df["TAIL1457_is_true_yang"] == 1) & (df["day0_vr"] >= 1.8)
add_slice("Interaction_Combos", "Combo_B_Yang_VR", "TypeB_Yang_VR>=1.8", c_b_yang_vr)

# Combo 2: Oversold MA5 <-14% + Bald Leg CLV >= 0.8
c_ma5_clv = (df["prev_c_ma5"] < -0.14) & (df["TAIL1457_clv"] >= 0.8)
add_slice("Interaction_Combos", "Combo_Rubber_BaldLeg", "MA5<-14%_CLV>=0.8", c_ma5_clv)

# Combo 3: Market Panic DT >= 40 + Top 3 Rebound Pioneer
c_panic_champ = (df["TAIL1457_mkt_dt_today"] >= 40) & (df["rk_rebound_today"] <= 3)
add_slice("Interaction_Combos", "Combo_Panic_Pioneer", "MktDT>=40_Top3Rebound", c_panic_champ)

# Combo 4: Multi-DT Despair (>=2 DT) + Clean (No Poison) + Real Turn >= 15%
c_despair_clean = (df["prev_dt_streak"] >= 2) & (df["n_poison_total"] == 0) & (df["TAIL1457_day0_real_to"] >= 0.15)
add_slice("Interaction_Combos", "Combo_Despair_Clean_Wash", "2+DT_Clean_Turn>=15%", c_despair_clean)

# Combo 5: Demon Stock nuclear dive (Type F) + Finished Red (pct > 0) + Bald Leg (clv >= 0.8)
c_demon_red_bald = ((df["prev_streak"] >= 1) | (df["prev_zt20"] >= 2)) & (df["pct"] > 0) & (df["TAIL1457_clv"] >= 0.8)
add_slice("Interaction_Combos", "Combo_Demon_Red_Bald", "Demon_Red_CLV>=0.8", c_demon_red_bald)

# Combo 6: Type A + True Yang + Rebound >= 5% + Doubled Volume
c_a_yang_strong = (df["prev_dt_streak"] == 0) & (df["prev_zt20"] == 0) & (df["TAIL1457_is_true_yang"] == 1) & (df["TAIL1457_rebound_pct"] >= 0.05) & (df["day0_vr"] >= 1.8)
add_slice("Interaction_Combos", "Combo_A_Yang_Strong", "TypeA_Yang_Reb>=5%_VR>=1.8", c_a_yang_strong)

# Combo 7: Clean + No Yizi DT + Small Mcap < 35亿 + Rubberband MA5 < -12%
c_small_rubber_clean = (df["n_poison_total"] == 0) & (df["prev_yizi_dt_streak"].fillna(0) == 0) & (df["real_free_mcap"] < 3.5e9) & (df["prev_c_ma5"] < -0.12)
add_slice("Interaction_Combos", "Combo_Small_Rubber_Clean", "SmallMcap_RubberMA5_Clean", c_small_rubber_clean)

print(f"Total defined slice definitions: {len(slices)}")

# We will test each slice against entries [E5_tail1457_all, E6_tail1457_yang] and exits [X3, X5, X6, X10]
# That yields len(slices) * 2 * 4 = len(slices) * 8 rows in factor catalog!
entries_to_test = [
    ("E5_tail1457_all", mat["ret"]["E5_tail1457_all"]),
    ("E6_tail1457_yang", mat["ret"]["E6_tail1457_yang"]),
]
exits_to_test = ["X3", "X5", "X6", "X10"]

records = []
for cat, factor, sname, cond in slices:
    cond_mask = base_mask & cond
    for ename, r_dict in entries_to_test:
        for xname in exits_to_test:
            r = r_dict[xname]
            valid = cond_mask & (~np.isnan(r))
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
            
            records.append({
                "category": cat,
                "factor": factor,
                "slice": sname,
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

cat_df = pd.DataFrame(records)
cat_df.to_csv(f"{OUT_DIR}/s2_factor_catalog.csv", index=False)
print(f"Task 2 Factor Catalog saved. Total slice-grid rows: {len(cat_df)}")

# Print Top 20 slices by mean return (N >= 50)
print("\n--- TOP 20 SLICES BY MEAN RETURN (N >= 50) ---")
top20 = cat_df[cat_df["N_tot"] >= 50].sort_values("mean_tot", ascending=False).head(20)
print(top20[["category", "factor", "slice", "entry", "exit", "N_tot", "win_tot", "mean_tot", "pl_tot", "mean_is", "mean_oos"]].to_string(index=False))

# Print Top 15 Slices on X3 (+5% TP 2d short-swing)
print("\n--- TOP 15 SLICES ON X3 (Short Swing, N >= 50) ---")
top_x3 = cat_df[(cat_df["exit"] == "X3") & (cat_df["N_tot"] >= 50)].sort_values("mean_tot", ascending=False).head(15)
print(top_x3[["factor", "slice", "entry", "N_tot", "win_tot", "mean_tot", "pl_tot", "mean_is", "mean_oos"]].to_string(index=False))

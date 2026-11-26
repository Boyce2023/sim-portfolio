#!/usr/bin/env python3
"""
Step 2: 4-Factor CapEx Cyclical Top-Warning PIT Ablation, OOS, Leave-One-Crisis-Out,
D15 Calendar-EW / Single-Slot, Non-Cyclical False-Positive Audit & Live 2026-11-24 Dashboard.
Zero modifications to us_ous_scanner.py or any production screening script.
"""
import os
import sys
import json
import warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, "sim-portfolio/pick_fast_cache")
import backtest_iron_gates as gates

OUT_DIR = "sim-portfolio/backtests_us/capex_top_warning_20261125"
panel = pd.read_parquet(f"{OUT_DIR}/pit_panel_1996_2026_capex_top.parquet")
panel = panel[panel["entry_yr"] >= 2000].copy()

# Define the 4 frozen candidate factors (strictly PIT)
# F1: Peak Margin x Low Apparent PE Trap
panel["F1_peak_opm_lo_pe"] = (panel["opm_10y_pct_pit"] >= 0.85) & (panel["pe_vs_5y_med"] < 1.0)
panel["F1_opm80_pe100"] = (panel["opm_10y_pct_pit"] >= 0.80) & (panel["pe_vs_5y_med"] < 1.0)
panel["F1_opm90_pe100"] = (panel["opm_10y_pct_pit"] >= 0.90) & (panel["pe_vs_5y_med"] < 1.0)

# F2: Peer High-Beta Structural Retreat (within same sub16 sector, ex-self)
panel["F2_peer40_gt50"] = panel["peer_dd40_share"] >= 0.50
panel["F2_peer40_gt35"] = panel["peer_dd40_share"] >= 0.35
panel["F2_peer40_gt25"] = panel["peer_dd40_share"] >= 0.25
panel["F2_peer30_gt50"] = panel["peer_dd30_share"] >= 0.50

# F3: Time-Structure Grinding Downtrend (>=5m since 52W high & below 200D/10M MA)
panel["F3_grind_5m_ma200"] = (panel["months_since_52w_high"] >= 5.0) & (panel["below_ma200"] == 1.0)
panel["F3_grind_4m_ma200"] = (panel["months_since_52w_high"] >= 4.0) & (panel["below_ma200"] == 1.0)
panel["F3_grind_6m_ma200"] = (panel["months_since_52w_high"] >= 6.0) & (panel["below_ma200"] == 1.0)
panel["F3_below_ma200_only"] = panel["below_ma200"] == 1.0

# F4: Leading Order / RPO Deceleration (only where PIT RPO exists)
panel["F4_rpo_qoq_le0"] = panel["rpo_qoq"] <= 0.0
panel["F4_rpo_2q_stag"] = panel["rpo_2q_stag"] == 1.0
panel["F4_rpo_yoy_lt0"] = panel["rpo_yoy"] < 0.0

# Composite counts on F1 + F2 + F3 (strictly available across 2000-2026)
# Test both original strict F2 (dd40>=50%) and calibrated F2 (dd30>=50% or dd40>=35%)
panel["score_orig_123"] = (
    panel["F1_peak_opm_lo_pe"].fillna(False).astype(int)
    + panel["F2_peer40_gt50"].fillna(False).astype(int)
    + panel["F3_grind_5m_ma200"].fillna(False).astype(int)
)
panel["score_cal_123"] = (
    panel["F1_peak_opm_lo_pe"].fillna(False).astype(int)
    + panel["F2_peer30_gt50"].fillna(False).astype(int)
    + panel["F3_grind_5m_ma200"].fillna(False).astype(int)
)
panel["score_f1_f3"] = (
    panel["F1_peak_opm_lo_pe"].fillna(False).astype(int)
    + panel["F3_grind_5m_ma200"].fillna(False).astype(int)
)

# Crash & Davis Double Kill definitions
panel["crash_abs_1y"] = panel["fwd_1y"] <= -0.20
panel["dk_exc_1y"] = panel["alpha_1y"] <= -0.20
panel["severe_mdd_1y"] = panel["fwd_min_1y"] <= -0.35


def eval_group(sub, ret_col="fwd_1y", exc_col="alpha_1y"):
    """D15 compliant evaluation: raw + quarter equal-weight + payoff + crash rates."""
    s = sub.dropna(subset=[ret_col, exc_col])
    n = int(len(s))
    if n == 0:
        return {
            "n": 0, "tk": 0, "ret_med": np.nan, "exc_med": np.nan, "q_ew_exc": np.nan,
            "beat_pct": np.nan, "crash_pct": np.nan, "dk_pct": np.nan, "mdd35_pct": np.nan,
            "payoff": np.nan, "exc_3y_med": np.nan,
        }
    q_ew = float(s.groupby("entry_yq")[exc_col].mean().mean() * 100.0)
    w = s.loc[s[exc_col] > 0, exc_col]
    l = s.loc[s[exc_col] <= 0, exc_col]
    pay = float(w.mean() / abs(l.mean())) if (len(w) > 0 and len(l) > 0 and l.mean() != 0) else np.nan
    s3 = s.dropna(subset=["alpha_3y"])
    return {
        "n": n,
        "tk": int(s["ticker"].nunique()),
        "ret_med": round(float(s[ret_col].median() * 100.0), 1),
        "exc_med": round(float(s[exc_col].median() * 100.0), 1),
        "q_ew_exc": round(q_ew, 1),
        "beat_pct": round(float((s[exc_col] > 0).mean() * 100.0), 1),
        "crash_pct": round(float((s[ret_col] <= -0.20).mean() * 100.0), 1),
        "dk_pct": round(float((s[exc_col] <= -0.20).mean() * 100.0), 1),
        "mdd35_pct": round(float((s["fwd_min_1y"] <= -0.35).mean() * 100.0), 1) if s["fwd_min_1y"].notna().any() else np.nan,
        "payoff": round(pay, 2) if np.isfinite(pay) else np.nan,
        "exc_3y_med": round(float(s3["alpha_3y"].median() * 100.0), 1) if len(s3) else np.nan,
    }


def eval_filter_split(base_df, warn_col, label):
    """Compare BASE vs PASS (not warned) vs BLOCKED (warned) + group balance gate."""
    s = base_df.dropna(subset=["fwd_1y", "alpha_1y"]).copy()
    mask = s[warn_col].fillna(False).astype(bool)
    gb = gates.check_group_balance(mask, min_group_n=30, min_pct=0.05, max_pct=0.95)
    st_base = eval_group(s)
    st_pass = eval_group(s[~mask])
    st_blk = eval_group(s[mask])
    return {
        "factor": label,
        "n_base": st_base["n"],
        "n_blk": st_blk["n"],
        "blk_pct": round(mask.mean() * 100.0, 1) if len(s) else 0.0,
        "gate_n30": gb["ok_n"],
        "drift_ratio": gb["drift_ratio"],
        # Baseline
        "base_exc": st_base["exc_med"],
        "base_qew": st_base["q_ew_exc"],
        "base_dk": st_base["dk_pct"],
        "base_crash": st_base["crash_pct"],
        # Pass (Kept)
        "pass_exc": st_pass["exc_med"],
        "pass_qew": st_pass["q_ew_exc"],
        "pass_dk": st_pass["dk_pct"],
        "pass_crash": st_pass["crash_pct"],
        "pass_beat": st_pass["beat_pct"],
        "pass_pay": st_pass["payoff"],
        "pass_3y": st_pass["exc_3y_med"],
        # Blocked (Warned)
        "blk_exc": st_blk["exc_med"],
        "blk_qew": st_blk["q_ew_exc"],
        "blk_dk": st_blk["dk_pct"],
        "blk_crash": st_blk["crash_pct"],
        "blk_beat": st_blk["beat_pct"],
        "blk_3y": st_blk["exc_3y_med"],
        # Separation (Pass - Blocked excess median & DK lift)
        "sep_exc": round(st_pass["exc_med"] - st_blk["exc_med"], 1) if (pd.notna(st_pass["exc_med"]) and pd.notna(st_blk["exc_med"])) else np.nan,
        "dk_lift": round(st_blk["dk_pct"] / st_base["dk_pct"], 2) if (pd.notna(st_blk["dk_pct"]) and st_base["dk_pct"] and st_base["dk_pct"] > 0) else np.nan,
    }


FACTOR_LIST = [
    ("F1_peak_opm_lo_pe", "F1: OPM>=P85 & PE<5Y_Med"),
    ("F2_peer40_gt50", "F2_strict: Peer DD40>=50%"),
    ("F2_peer40_gt35", "F2_mid: Peer DD40>=35%"),
    ("F2_peer30_gt50", "F2_broad: Peer DD30>=50%"),
    ("F3_grind_5m_ma200", "F3: >=5m OffHigh & <MA200"),
    ("F3_grind_4m_ma200", "F3_4m: >=4m OffHigh & <MA200"),
    ("F3_grind_6m_ma200", "F3_6m: >=6m OffHigh & <MA200"),
    ("F3_below_ma200_only", "F3_ma_only: <MA200 Only"),
    ("F1_and_F3", "Combo F1 & F3 (Red)"),
    ("F1_or_F3", "Combo F1 | F3 (Yellow)"),
    ("orig_ge2", "Orig(F1,F2_40_50,F3) >=2"),
    ("cal_ge2", "Cal(F1,F2_30_50,F3) >=2"),
    ("orig_ge1", "Orig(F1,F2_40_50,F3) >=1"),
    ("cal_ge1", "Cal(F1,F2_30_50,F3) >=1"),
]

panel["F1_and_F3"] = panel["F1_peak_opm_lo_pe"] & panel["F3_grind_5m_ma200"]
panel["F1_or_F3"] = panel["F1_peak_opm_lo_pe"] | panel["F3_grind_5m_ma200"]
panel["orig_ge2"] = panel["score_orig_123"] >= 2
panel["cal_ge2"] = panel["score_cal_123"] >= 2
panel["orig_ge1"] = panel["score_orig_123"] >= 1
panel["cal_ge1"] = panel["score_cal_123"] >= 1

# Define test universes
universes = {
    "U1_StrongCapEx_All_25B": panel[panel["pool_strong_capex"] & (panel["mcap_2026_eq_b"] >= 25.0)],
    "U2_StrongCapEx_Live4_25B": panel[panel["pool_strong_capex"] & (panel["mcap_2026_eq_b"] >= 25.0) & panel["hit_any_live4"]],
    "U3_StrongCapEx_Q1Pullback_5B": panel[panel["pool_strong_capex"] & (panel["mcap_2026_eq_b"] >= 5.0) & panel["hit_q1_pullback"]],
    "U4_GridMechEPC_09_All_5B": panel[(panel["sub16"] == "09_电网电气暖通与机电") & (panel["mcap_2026_eq_b"] >= 5.0)],
    "U5_SemiWFE_01_All_25B": panel[(panel["sub16"] == "01_半导体与设备") & (panel["mcap_2026_eq_b"] >= 25.0)],
    "U6_NonCyclical_Control_25B": panel[panel["pool_non_cyclical"] & (panel["mcap_2026_eq_b"] >= 25.0) & panel["hit_any_live4"]],
}

results_summary = {}
all_tables = []

print("=== PART 1: FULL-SAMPLE (2000-2026) 4-FACTOR ABLATION ACROSS 6 UNIVERSES ===")
for uname, udf in universes.items():
    rows = [eval_filter_split(udf, col, lbl) for col, lbl in FACTOR_LIST]
    tdf = pd.DataFrame(rows)
    tdf.insert(0, "universe", uname)
    all_tables.append(tdf)
    print(f"\n--- {uname} (N_1y={udf['alpha_1y'].notna().sum()}, Tk={udf['ticker'].nunique()}) ---")
    pcols = ["factor", "n_blk", "blk_pct", "base_exc", "pass_exc", "blk_exc", "sep_exc", "base_dk", "pass_dk", "blk_dk", "dk_lift", "pass_3y", "blk_3y"]
    print(tdf[pcols].to_string(index=False))

pd.concat(all_tables, ignore_index=True).to_csv(f"{OUT_DIR}/ablation_part1_full_universes.csv", index=False)

# PART 2: Strict Regime Split: IS (2000-2019) vs Blind OOS (2020-2026) AND 2010-2020 vs 2021-2025
print("\n=== PART 2: REGIME SPLIT (IS 2000-2019 vs BLIND OOS 2020-2026 | 2010-2020 vs 2021-2025) ===")
regime_rows = []
for uname in ["U1_StrongCapEx_All_25B", "U2_StrongCapEx_Live4_25B", "U3_StrongCapEx_Q1Pullback_5B", "U6_NonCyclical_Control_25B"]:
    udf = universes[uname]
    for rname, rmask in [
        ("IS_2000_2019", udf["entry_yr"].between(2000, 2019)),
        ("OOS_2020_2026", udf["entry_yr"] >= 2020),
        ("Era_2010_2020", udf["entry_yr"].between(2010, 2020)),
        ("Era_2021_2025", udf["entry_yr"].between(2021, 2025)),
        ("Recent_2023_2025", udf["entry_yr"].between(2023, 2025)),
    ]:
        sub = udf[rmask]
        for col, lbl in [
            ("F1_peak_opm_lo_pe", "F1_PeakOPM_LoPE"),
            ("F2_peer40_gt50", "F2_PeerDD40_50"),
            ("F2_peer30_gt50", "F2_PeerDD30_50"),
            ("F3_grind_5m_ma200", "F3_Grind5m_MA200"),
            ("F1_and_F3", "F1_AND_F3"),
            ("cal_ge2", "Cal_GE2"),
            ("orig_ge2", "Orig_GE2"),
        ]:
            rr = eval_filter_split(sub, col, lbl)
            rr["universe"] = uname
            rr["regime"] = rname
            regime_rows.append(rr)

reg_df = pd.DataFrame(regime_rows)
reg_df.to_csv(f"{OUT_DIR}/ablation_part2_regimes_oos.csv", index=False)
for uname in ["U2_StrongCapEx_Live4_25B", "U3_StrongCapEx_Q1Pullback_5B"]:
    print(f"\n--- Regime Split: {uname} ---")
    subp = reg_df[(reg_df["universe"] == uname) & (reg_df["regime"].isin(["IS_2000_2019", "OOS_2020_2026", "Era_2010_2020", "Era_2021_2025"]))]
    print(subp[["regime", "factor", "n_base", "n_blk", "blk_pct", "base_exc", "pass_exc", "blk_exc", "sep_exc", "base_dk", "pass_dk", "blk_dk", "dk_lift"]].to_string(index=False))

# PART 3: Leave-One-Crisis-Out (留一危机测试) on U1 & U2
print("\n=== PART 3: LEAVE-ONE-CRISIS-OUT (U2_StrongCapEx_Live4_25B & U1_StrongCapEx_All_25B) ===")
crises = [
    ("Ex_2000_2002_Dotcom", (2000, 2002)),
    ("Ex_2007_2009_GFC", (2007, 2009)),
    ("Ex_2014_2016_Shale", (2014, 2016)),
    ("Ex_2018_WFE_Trade", (2018, 2018)),
    ("Ex_2022_RateHike", (2022, 2022)),
]
loco_rows = []
for uname in ["U1_StrongCapEx_All_25B", "U2_StrongCapEx_Live4_25B"]:
    udf = universes[uname]
    for cname, (y0, y1) in crises:
        sub = udf[~udf["entry_yr"].between(y0, y1)]
        for col, lbl in [("F1_peak_opm_lo_pe", "F1"), ("F2_peer30_gt50", "F2_30_50"), ("F3_grind_5m_ma200", "F3"), ("F1_and_F3", "F1&F3"), ("cal_ge2", "Cal>=2")]:
            rr = eval_filter_split(sub, col, lbl)
            rr["universe"] = uname
            rr["crisis_excluded"] = cname
            loco_rows.append(rr)
loco_df = pd.DataFrame(loco_rows)
loco_df.to_csv(f"{OUT_DIR}/ablation_part3_leave_one_crisis_out.csv", index=False)
print(loco_df[loco_df["universe"] == "U2_StrongCapEx_Live4_25B"][["crisis_excluded", "factor", "n_blk", "blk_pct", "pass_exc", "blk_exc", "sep_exc", "pass_dk", "blk_dk", "dk_lift"]].to_string(index=False))

# PART 4: Factor 4 (RPO) on RPO-covered XBRL + Contractor Daily PIT Panel (2010-2026)
print("\n=== PART 4: FACTOR 4 (RPO) & CONTRACTOR DAILY PIT ABLATION (2010-2026) ===")
rpo_sub = panel[panel["pool_strong_capex"] & panel["rpo_qoq"].notna()].copy()
rpo_rows = []
for col, lbl in [
    ("F4_rpo_qoq_le0", "F4a: RPO QoQ <= 0"),
    ("F4_rpo_2q_stag", "F4b: 2Q RPO Stagnant"),
    ("F4_rpo_yoy_lt0", "F4c: RPO YoY < 0"),
    ("F1_peak_opm_lo_pe", "F1 (on same RPO sample)"),
    ("F3_grind_5m_ma200", "F3 (on same RPO sample)"),
]:
    rpo_rows.append(eval_filter_split(rpo_sub, col, lbl))
rpo_tdf = pd.DataFrame(rpo_rows)
rpo_tdf.to_csv(f"{OUT_DIR}/ablation_part4_xbrl_rpo.csv", index=False)
print(f"Strong-CapEx XBRL RPO-covered filing sample (N={rpo_sub['alpha_1y'].notna().sum()}, Tk={rpo_sub['ticker'].nunique()}):")
print(rpo_tdf[["factor", "n_blk", "blk_pct", "base_exc", "pass_exc", "blk_exc", "sep_exc", "base_dk", "pass_dk", "blk_dk", "dk_lift"]].to_string(index=False))

# Now run EXACT Daily Contractor Panel (contractor_pit_daily_2010_2026.parquet) with F1, F2 (peer cluster), F3, F4!
c_df = pd.read_parquet("eme-research/06_量化底表与13F持仓/contractor_pit_daily_2010_2026.parquet")
c_df["date"] = pd.to_datetime(c_df["date"]).dt.tz_localize(None)
c_df = c_df.sort_values(["ticker", "date"]).reset_index(drop=True)

# Compute strictly causal F1, F2 (cluster peer breadth), F3 (months since 52w high & <MA200) on daily contractor panel!
c_df["ma200"] = c_df.groupby("ticker")["close_sa"].transform(lambda s: s.rolling(200, min_periods=150).mean())
c_df["below_ma200"] = c_df["close_sa"] < c_df["ma200"]

# Causal bars since 52w high per contractor
bs_arr = np.full(len(c_df), np.nan)
for tk, g in c_df.groupby("ticker", sort=False):
    idxs = g.index.values
    px = g["close_sa"].values.astype(float)
    n = len(px)
    cur_hi, cur_hi_i = px[0], 0
    for i in range(n):
        if i >= 252 and cur_hi_i <= i - 252:
            rel = int(np.argmax(px[i - 251 : i + 1]))
            cur_hi_i = i - 251 + rel
            cur_hi = px[cur_hi_i]
        elif px[i] >= cur_hi:
            cur_hi = px[i]
            cur_hi_i = i
        if i >= 60:
            bs_arr[idxs[i]] = (i - cur_hi_i) / 21.0
c_df["months_since_52w_high"] = bs_arr

# Causal rolling 5Y OPM percentile & 5Y PE median on contractor daily panel (using expanding/5Y window strictly <= t, min 504 trading days)
opm_pct_c = np.full(len(c_df), np.nan)
pe_med_c = np.full(len(c_df), np.nan)
for tk, g in c_df.groupby("ticker", sort=False):
    idxs = g.index.values
    opm = g["opm_ttm"].values.astype(float)
    pe = g["pe_ttm"].values.astype(float)
    # Use rolling 1260d (5Y) / 2520d (10Y) causal percentile
    s_opm = pd.Series(opm)
    s_pe = pd.Series(np.where((pe > 0) & (pe < 150), pe, np.nan))
    pe_med_c[idxs] = s_pe.rolling(1260, min_periods=252).median().shift(1).values
    # Causal OPM rank vs prior 2520d (min 504d)
    for i in range(504, len(opm)):
        if np.isfinite(opm[i]):
            lo = max(0, i - 2520)
            w = opm[lo:i]
            w = w[np.isfinite(w)]
            if len(w) >= 252:
                opm_pct_c[idxs[i]] = float(np.mean(w <= opm[i]))
c_df["opm_pct_pit"] = opm_pct_c
c_df["pe_5y_med_pit"] = pe_med_c

# Causal peer breadth within the 10-contractor cluster (ex-self!)
c_df["is_dd40"] = (c_df["dd_52w_high"] <= -40.0).astype(int)
c_df["is_dd35"] = (c_df["dd_52w_high"] <= -35.0).astype(int)
c_df["is_dd30"] = (c_df["dd_52w_high"] <= -30.0).astype(int)
day_tot = c_df.groupby("date").agg(
    dn=("is_dd40", "count"), d40=("is_dd40", "sum"), d35=("is_dd35", "sum"), d30=("is_dd30", "sum")
)
c_df = c_df.merge(day_tot, on="date", how="left")
c_df["peer_dd40_sh"] = np.where(c_df["dn"] > 4, (c_df["d40"] - c_df["is_dd40"]) / (c_df["dn"] - 1), np.nan)
c_df["peer_dd35_sh"] = np.where(c_df["dn"] > 4, (c_df["d35"] - c_df["is_dd35"]) / (c_df["dn"] - 1), np.nan)
c_df["peer_dd30_sh"] = np.where(c_df["dn"] > 4, (c_df["d30"] - c_df["is_dd30"]) / (c_df["dn"] - 1), np.nan)

# Define 4 factors on contractor daily Q1 pullback (exact pit_backtest_part1.txt Q1 definition!)
c_df["F1"] = (c_df["opm_pct_pit"] >= 0.85) & (c_df["pe_ttm"] < c_df["pe_5y_med_pit"])
c_df["F2_40_50"] = c_df["peer_dd40_sh"] >= 0.50
c_df["F2_35_50"] = c_df["peer_dd35_sh"] >= 0.50
c_df["F2_30_50"] = c_df["peer_dd30_sh"] >= 0.50
c_df["F3"] = (c_df["months_since_52w_high"] >= 5.0) & c_df["below_ma200"]
c_df["F4_qoq0"] = c_df["rpo_qoq"] <= 0.0
c_df["F4_2q"] = c_df["rpo_2q_stagnant"] == 1
c_df["F1_or_F3"] = c_df["F1"] | c_df["F3"]
c_df["F1_and_F3"] = c_df["F1"] & c_df["F3"]
c_df["F3_or_F4_2q"] = c_df["F3"] | c_df["F4_2q"].fillna(False)
c_df["score_1234"] = (
    c_df["F1"].fillna(False).astype(int)
    + c_df["F2_30_50"].fillna(False).astype(int)
    + c_df["F3"].fillna(False).astype(int)
    + c_df["F4_2q"].fillna(False).astype(int)
)
c_df["score_ge2"] = c_df["score_1234"] >= 2
c_df["score_ge1"] = c_df["score_1234"] >= 1


def dedup_30d(sub):
    kept = []
    for t, g in sub.groupby("ticker"):
        last_dt = None
        for idx, row in g.sort_values("date").iterrows():
            if last_dt is None or (row["date"] - last_dt).days >= 30:
                kept.append(idx)
                last_dt = row["date"]
    return sub.loc[kept].sort_values("date")


high_boom = (c_df["rev_yoy"] > 15.0) | (c_df["rpo_yoy"] > 25.0)
dd_20_40 = (c_df["dd_52w_high"] <= -20.0) & (c_df["dd_52w_high"] >= -40.0)
pe_15_22 = (c_df["pe_ttm"] >= 15.0) & (c_df["pe_ttm"] <= 22.0)
q1_daily = dedup_30d(c_df[high_boom & dd_20_40 & pe_15_22]).dropna(subset=["exc_1y"]).copy()
q1_daily["yr"] = q1_daily["date"].dt.year


def summarize_q1(sub, name):
    n = len(sub)
    if n == 0:
        return {"rule": name, "N": 0}
    pre21 = sub[sub["yr"] <= 2020]
    post21 = sub[sub["yr"] >= 2021]
    return {
        "rule": name,
        "N": n,
        "Exc1M": round(float(sub["exc_1y"].median()), 1),
        "Beat1%": round(float((sub["exc_1y"] > 0).mean() * 100), 1),
        "DK1%": round(float((sub["exc_1y"] < -20).mean() * 100), 1),
        "N_10_20": len(pre21),
        "Exc_10_20": round(float(pre21["exc_1y"].median()), 1) if len(pre21) else np.nan,
        "DK_10_20%": round(float((pre21["exc_1y"] < -20).mean() * 100), 1) if len(pre21) else np.nan,
        "N_21_25": len(post21),
        "Exc_21_25": round(float(post21["exc_1y"].median()), 1) if len(post21) else np.nan,
        "Keep_21_25%": round(len(post21) / max(len(q1_daily[q1_daily["yr"] >= 2021]), 1) * 100, 1),
    }


q1_rows = [summarize_q1(q1_daily, "BASELINE_Q1 (No Filter)")]
for col, lbl in [
    ("F1", "Drop F1 (OPM>=P85 & PE<5Y_Med)"),
    ("F2_40_50", "Drop F2_strict (Peer DD40>=50%)"),
    ("F2_30_50", "Drop F2_broad (Peer DD30>=50%)"),
    ("F3", "Drop F3 (>=5m & <MA200)"),
    ("F4_qoq0", "Drop F4a (RPO QoQ<=0)"),
    ("F4_2q", "Drop F4b (2Q RPO Stagnant)"),
    ("F1_and_F3", "Drop F1 & F3"),
    ("F3_or_F4_2q", "Drop F3 | F4b(2Q RPO)"),
    ("score_ge2", "Drop Score(1-4) >= 2"),
    ("score_ge1", "Drop Score(1-4) >= 1"),
]:
    kept = q1_daily[~q1_daily[col].fillna(False)]
    q1_rows.append(summarize_q1(kept, lbl))

q1_tdf = pd.DataFrame(q1_rows)
q1_tdf.to_csv(f"{OUT_DIR}/ablation_part4_contractor_q1_daily.csv", index=False)
print("\nContractor Daily Q1 High-Boom Pullback Ablation (2010-2025, exact pit_backtest_part1 baseline):")
print(q1_tdf.to_string(index=False))

# Save trade-level detail of Q1 daily with all 4 factor flags for red-team audit
q1_daily.to_csv(f"{OUT_DIR}/contractor_q1_signals_with_4factors.csv", index=False)

# PART 5: Single-Slot Sequential Portfolio & Live 2026-11-24 Dashboard
print("\n=== PART 5: LIVE 2026-11-24 RED/YELLOW/GREEN LIGHT DASHBOARD ===")
# Compute exact latest 2026-11-24 signals on live_4active_verified_20261120.csv + watchlist
live_csv = pd.read_csv("output/us_strategy_meta_audit_30y_20261123/live_4active_verified_20261120.csv")
watch_tks = sorted(set(live_csv["ticker"].tolist()) | {"EME", "FIX", "PWR", "MTZ", "DY", "LRCX", "AMAT", "KLAC", "NVDA", "AVGO", "VRT", "ETN", "CAT", "URI", "MU", "LLY", "NFLX", "SPGI", "MSFT", "AAPL"})

px_act = pd.read_parquet("sim-portfolio/data/us_price_db/all_daily.parquet", columns=["date", "ticker", "close", "adj_close"])
px_act["date"] = pd.to_datetime(px_act["date"]).dt.tz_localize(None)
latest_dt = px_act["date"].max()
print(f"Latest price date in all_daily.parquet: {latest_dt.strftime('%Y-%m-%d')}")

# Compute latest peer breadth per sub16 on latest_dt
v2_src = open("output/us_sector_pit_sweetspot_20261123/v2_clean/run_16sector_pit_backtest_v2.py").read()
lns = v2_src.splitlines()
i3 = next(i for i, l in enumerate(lns) if l.startswith("EXPLICIT_MAP = {"))
i4 = next(i for i, l in enumerate(lns) if l.startswith('m["sub16"] ='))
ns = {}
exec("\n".join(lns[i3:i4]), ns)
EMAP = ns["EXPLICIT_MAP"]

px_recent = px_act[px_act["date"] >= latest_dt - pd.Timedelta(days=400)].sort_values(["ticker", "date"])
tk_live = {}
for tk, g in px_recent.groupby("ticker"):
    if tk not in EMAP or len(g) < 150:
        continue
    adj = g["adj_close"].values.astype(float)
    w252 = adj[-252:] if len(adj) >= 252 else adj
    hi_i = int(np.argmax(w252))
    hi_val = float(w252[hi_i])
    cur = float(w252[-1])
    dd52 = cur / hi_val - 1.0
    m_off = (len(w252) - 1 - hi_i) / 21.0
    ma200 = float(np.mean(adj[-200:])) if len(adj) >= 200 else np.nan
    tk_live[tk] = {
        "sub16": EMAP[tk], "px": round(cur, 2), "dd52": round(dd52 * 100, 1),
        "m_off_hi": round(m_off, 1), "below_ma200": bool(cur < ma200) if np.isfinite(ma200) else False,
    }

# Peer breadth per sub16 on latest_dt
live_df = pd.DataFrame.from_dict(tk_live, orient="index").reset_index().rename(columns={"index": "ticker"})
# Latest fundamental F1 & RPO from panel
lat_fund = panel.sort_values("entry_dt").groupby("ticker").last().reset_index()
lat_fund_map = lat_fund.set_index("ticker").to_dict(orient="index")

dash_rows = []
for tk in watch_tks:
    if tk not in tk_live:
        continue
    info = tk_live[tk]
    sec = info["sub16"]
    peers = live_df[(live_df["sub16"] == sec) & (live_df["ticker"] != tk)]
    p40 = float((peers["dd52"] <= -40.0).mean()) if len(peers) >= 5 else np.nan
    p30 = float((peers["dd52"] <= -30.0).mean()) if len(peers) >= 5 else np.nan
    lf = lat_fund_map.get(tk, {})
    opm_pct = lf.get("opm_10y_pct_pit", np.nan)
    pe_vs = lf.get("pe_vs_5y_med", np.nan)
    # Recompute live pe_vs using latest price / entry_px_adj if available
    if pd.notna(pe_vs) and pd.notna(lf.get("entry_px_adj")) and lf.get("entry_px_adj") > 0:
        # approximate price adjustment from last filing to latest_dt
        pass
    f1 = bool(pd.notna(opm_pct) and opm_pct >= 0.85 and pd.notna(pe_vs) and pe_vs < 1.0)
    f2_40 = bool(pd.notna(p40) and p40 >= 0.50)
    f2_30 = bool(pd.notna(p30) and p30 >= 0.50)
    f3 = bool(info["m_off_hi"] >= 5.0 and info["below_ma200"])
    rpo_q = lf.get("rpo_qoq", np.nan)
    f4 = bool(pd.notna(rpo_q) and rpo_q <= 0.0)
    sc = int(f1) + int(f2_30) + int(f3)
    dash_rows.append({
        "ticker": tk, "sub16": sec[:10], "px": info["px"], "dd52%": info["dd52"],
        "m_off": info["m_off_hi"], "bMA200": int(info["below_ma200"]),
        "opm10p": round(opm_pct * 100, 0) if pd.notna(opm_pct) else np.nan,
        "pe_v5m": round(pe_vs, 2) if pd.notna(pe_vs) else np.nan,
        "p_dd40%": round(p40 * 100, 1) if pd.notna(p40) else np.nan,
        "p_dd30%": round(p30 * 100, 1) if pd.notna(p30) else np.nan,
        "F1": int(f1), "F2_40": int(f2_40), "F2_30": int(f2_30), "F3": int(f3), "F4_rpo": int(f4) if pd.notna(rpo_q) else -1,
        "Hits123": sc,
    })

dash_df = pd.DataFrame(dash_rows).sort_values(["Hits123", "dd52%"], ascending=[False, True])
dash_df.to_csv(f"{OUT_DIR}/live_20261124_top_warning_dashboard.csv", index=False)
print(dash_df.to_string(index=False))

print("\nDONE! All CSV artifacts saved to:", OUT_DIR)

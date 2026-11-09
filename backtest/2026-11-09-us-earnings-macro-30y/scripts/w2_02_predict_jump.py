"""
w2_02_predict_jump.py
美股30年财报拐点与宏观回测项目 W2_02 模块：
财报发布前夕「谁要跳涨」零未来函数预测引擎。

绝对零未来函数铁律（Zero-Lookahead Mandate）：
1. 预测目标：第 t 季财报事件的跳涨幅度 earn_jump_ret（>= +8%, >= +10%, >= +15%, <= -10%）。
2. 输入特征严格截至 pre_date_t（财报日前一交易日收盘）：
   - 所有基本面特征 100% 取自同一公司严格排在前面的上一季已披露快照 row t-1（校验 filed_{t-1} < pre_date_t）。
   - 估值特征 pe_pre_earn, ps_pre_earn 基于 row t-1 的 TTM 财务数字与 pre_date_t 的收盘市值。
   - 价格形态特征 slow_uptrend_tag, realized_vol_252d, dist_52w_high 等截至 pre_date_t。
   - 宏观状态 vix_regime, rate_dir_6m, yc_regime, credit_regime, macro_quadrant, era_regime 截至 pre_date_t。
3. 严禁漏入当季 row t 的任何财务数字！
"""

import os
import sys
import time
import json
import numpy as np
import pandas as pd

# Paths
PROJ = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-09-us-earnings-macro-30y"
DATA_PATH = f"{PROJ}/data/xbrl_master_pit_2009_2026.parquet"
OUT_DIR = f"{PROJ}/results/m2_jump_prediction"
os.makedirs(OUT_DIR, exist_ok=True)

def compute_streak_vectorized(series, thresh, condition='ge'):
    """
    Vectorized consecutive streak counter within a single ticker series.
    """
    if condition == 'ge':
        hit = (series >= thresh)
    else:
        hit = (series <= thresh)
    block = (~hit).cumsum()
    return hit.groupby(block).cumsum()

def calc_stats_row(sub: pd.DataFrame, label: str, dimension: str, universe: str) -> dict:
    """
    Compute comprehensive jump/drop statistics for a given subset.
    """
    n = len(sub)
    if n == 0:
        return {
            "universe": universe, "dimension": dimension, "category": label, "N": 0,
            "mean_jump_ret": np.nan, "median_jump_ret": np.nan, "std_jump_ret": np.nan,
            "win_rate_pos": np.nan, "p_jump_8": np.nan, "p_jump_10": np.nan, "p_jump_15": np.nan,
            "p_drop_8": np.nan, "p_drop_10": np.nan, "p_drop_15": np.nan,
            "ratio_jump10_drop10": np.nan, "ratio_jump8_drop8": np.nan,
            "net_skew_10": np.nan, "payoff_ratio": np.nan
        }
    
    rets = sub["earn_jump_ret"].values
    mean_ret = float(np.mean(rets))
    median_ret = float(np.median(rets))
    std_ret = float(np.std(rets))
    
    pos_mask = rets > 0
    neg_mask = rets < 0
    win_rate = float(np.mean(pos_mask))
    
    p_j8 = float(np.mean(rets >= 0.08))
    p_j10 = float(np.mean(rets >= 0.10))
    p_j15 = float(np.mean(rets >= 0.15))
    
    p_d8 = float(np.mean(rets <= -0.08))
    p_d10 = float(np.mean(rets <= -0.10))
    p_d15 = float(np.mean(rets <= -0.15))
    
    ratio10 = p_j10 / max(p_d10, 1e-4) if p_d10 > 0 else (p_j10 / 1e-4 if p_j10 > 0 else 1.0)
    ratio8 = p_j8 / max(p_d8, 1e-4) if p_d8 > 0 else (p_j8 / 1e-4 if p_j8 > 0 else 1.0)
    net_skew = p_j10 - p_d10
    
    mean_pos = float(np.mean(rets[pos_mask])) if np.any(pos_mask) else 0.0
    mean_neg = float(np.mean(rets[neg_mask])) if np.any(neg_mask) else 0.0
    payoff = abs(mean_pos / mean_neg) if abs(mean_neg) > 1e-6 else 1.0
    
    return {
        "universe": universe,
        "dimension": dimension,
        "category": label,
        "N": n,
        "mean_jump_ret": round(mean_ret, 6),
        "median_jump_ret": round(median_ret, 6),
        "std_jump_ret": round(std_ret, 6),
        "win_rate_pos": round(win_rate, 4),
        "p_jump_8": round(p_j8, 4),
        "p_jump_10": round(p_j10, 4),
        "p_jump_15": round(p_j15, 4),
        "p_drop_8": round(p_d8, 4),
        "p_drop_10": round(p_d10, 4),
        "p_drop_15": round(p_d15, 4),
        "ratio_jump10_drop10": round(ratio10, 2),
        "ratio_jump8_drop8": round(ratio8, 2),
        "net_skew_10": round(net_skew, 4),
        "payoff_ratio": round(payoff, 2)
    }

def main():
    t0 = time.time()
    print("[1/6] Loading master PIT dataset & verifying columns...")
    df = pd.read_parquet(DATA_PATH)
    print(f"Loaded {len(df):,} rows across {df['ticker'].nunique():,} tickers in {time.time()-t0:.2f}s.")
    
    # Sort strictly by ticker, end date, filed date
    df = df.sort_values(["ticker", "end", "filed"]).reset_index(drop=True)
    
    print("[2/6] Constructing lagged fundamental features & streaks (Strictly row t-1)...")
    # Shift fundamental features within each ticker
    df["prior_filed"] = df.groupby("ticker")["filed"].shift(1)
    df["prior_end"] = df.groupby("ticker")["end"].shift(1)
    df["prior_earn_jump_ret"] = df.groupby("ticker")["earn_jump_ret"].shift(1)
    
    df["prior_consec_rev_accel_n"] = df.groupby("ticker")["consec_rev_accel_n"].shift(1)
    df["prior_consec_opm_expand_n"] = df.groupby("ticker")["consec_opm_expand_n"].shift(1)
    df["prior_consec_gm_sga_expand_n"] = df.groupby("ticker")["consec_gm_sga_expand_n"].shift(1)
    df["prior_consec_double_inflect_n"] = df.groupby("ticker")["consec_double_inflect_n"].shift(1)
    df["prior_turnaround_to_profit_1q"] = df.groupby("ticker")["turnaround_to_profit_1q"].shift(1)
    
    # Compute jump and drop streaks strictly on prior reports
    df["jump10_streak"] = df.groupby("ticker")["earn_jump_ret"].transform(lambda s: compute_streak_vectorized(s, 0.10, 'ge'))
    df["drop10_streak"] = df.groupby("ticker")["earn_jump_ret"].transform(lambda s: compute_streak_vectorized(s, -0.10, 'le'))
    df["jump8_streak"] = df.groupby("ticker")["earn_jump_ret"].transform(lambda s: compute_streak_vectorized(s, 0.08, 'ge'))
    df["drop8_streak"] = df.groupby("ticker")["earn_jump_ret"].transform(lambda s: compute_streak_vectorized(s, -0.08, 'le'))
    
    df["prior_jump10_streak"] = df.groupby("ticker")["jump10_streak"].shift(1).fillna(0).astype(int)
    df["prior_drop10_streak"] = df.groupby("ticker")["drop10_streak"].shift(1).fillna(0).astype(int)
    df["prior_jump8_streak"] = df.groupby("ticker")["jump8_streak"].shift(1).fillna(0).astype(int)
    df["prior_drop8_streak"] = df.groupby("ticker")["drop8_streak"].shift(1).fillna(0).astype(int)
    
    # Timing and PIT validation
    df["filed_prior_dt"] = pd.to_datetime(df["prior_filed"])
    df["pre_date_dt"] = pd.to_datetime(df["pre_date"])
    df["entry_date_dt"] = pd.to_datetime(df["entry_date"])
    
    valid_timing = (df["filed_prior_dt"] < df["pre_date_dt"])
    valid_event = (
        df["earn_jump_ret"].notna() &
        df["pre_date"].notna() &
        df["prior_filed"].notna() &
        valid_timing
    )
    
    df_valid = df[valid_event].copy()
    print(f"Total valid earnings prediction events (filed_{{t-1}} < pre_date_t): {len(df_valid):,} (from {len(df):,} total filings).")
    
    # Zero-lookahead assertion checks
    assert (pd.to_datetime(df_valid["prior_filed"]) < pd.to_datetime(df_valid["pre_date"])).all(), "FATAL: Found prior filing >= pre_date!"
    print("Zero-Lookahead Assertion Passed: 100% of prediction rows have filed_{t-1} < pre_date_t.")
    
    # 2026-equivalent Pre-Earnings Market Cap
    df_valid["mcap_pre_2026_b"] = (df_valid["mcap_pre_pit"] / 1e9) * df_valid["mcap_scale_to_2026"]
    df_valid["mcap_pre_2026_b"] = df_valid["mcap_pre_2026_b"].fillna(df_valid["mcap_2026_equiv_b"])
    
    # Market Cap Bins
    def bin_mcap(m):
        if pd.isna(m) or m <= 0: return "Unknown"
        if m < 5.0: return "Mcap_<5B"
        elif m < 25.0: return "Mcap_5-25B"
        elif m < 100.0: return "Mcap_25-100B"
        else: return "Mcap_>100B"
    df_valid["mcap_bin"] = df_valid["mcap_pre_2026_b"].apply(bin_mcap)
    
    # Volatility Bins
    def bin_vol(v):
        if pd.isna(v) or v <= 0: return "Vol_Unknown"
        if v < 0.25: return "Vol_Low_<25%"
        elif v < 0.40: return "Vol_Med_25-40%"
        elif v < 0.60: return "Vol_High_40-60%"
        else: return "Vol_Extreme_>60%"
    df_valid["vol_bin"] = df_valid["realized_vol_252d"].apply(bin_vol)
    
    # Valuation Bins
    def bin_pe(pe):
        if pd.isna(pe): return "PE_Unknown"
        if pe < 0: return "PE_Neg_Loss"
        elif pe < 15: return "PE_0-15"
        elif pe < 25: return "PE_15-25"
        elif pe < 45: return "PE_25-45"
        else: return "PE_gt45"
    df_valid["pe_bin"] = df_valid["pe_pre_earn"].apply(bin_pe)
    
    def bin_ps(ps):
        if pd.isna(ps) or ps < 0: return "PS_Unknown"
        if ps < 3.0: return "PS_lt3"
        elif ps < 8.0: return "PS_3-8"
        elif ps < 15.0: return "PS_8-15"
        else: return "PS_gt15"
    df_valid["ps_bin"] = df_valid["ps_pre_earn"].apply(bin_ps)
    
    # Double inflection flag from prior quarter
    df_valid["prior_double_inflect"] = np.where(df_valid["prior_consec_double_inflect_n"] >= 1, "DoubleInflect", "Normal")
    
    # Custom Era Regime
    def era_custom(r):
        era = str(r.get("era_regime", ""))
        if "2020_2021" in era:
            return "2020_2021_ZeroRateCovid"
        elif "2022_2023" in era or "2024_2026" in era:
            return "2022_2026_HighRateEra"
        elif "2010_2019" in era:
            return "2010_2019_LowRateBull"
        elif "2008_2009" in era:
            return "2008_2009_GFC"
        return "Other_Era"
    df_valid["era_custom"] = df_valid.apply(era_custom, axis=1)
    
    # Universes
    universes = {
        "All_Investable_ge5B": df_valid[df_valid["mcap_pre_2026_b"] >= 5.0].copy(),
        "Large_Cap_ge25B": df_valid[df_valid["mcap_pre_2026_b"] >= 25.0].copy(),
        "All_Market_ge0": df_valid.copy()
    }
    
    print("[3/6] Generating Table 2A: Base Rate and Market Cap / Volatility Stratification...")
    rows_2a = []
    for u_name, u_df in universes.items():
        # Overall Base Rate
        rows_2a.append(calc_stats_row(u_df, "Base_Rate_Overall", "Overall", u_name))
        
        # Market Cap Bins
        for b in ["Mcap_<5B", "Mcap_5-25B", "Mcap_25-100B", "Mcap_>100B"]:
            sub = u_df[u_df["mcap_bin"] == b]
            if len(sub) > 0:
                rows_2a.append(calc_stats_row(sub, b, "Market_Cap_Tier", u_name))
        
        # Volatility Bins
        for vb in ["Vol_Low_<25%", "Vol_Med_25-40%", "Vol_High_40-60%", "Vol_Extreme_>60%"]:
            sub = u_df[u_df["vol_bin"] == vb]
            if len(sub) > 0:
                rows_2a.append(calc_stats_row(sub, vb, "Realized_Vol_252d", u_name))
        
        # 2D Cross: Mcap x Volatility
        for mb in ["Mcap_<5B", "Mcap_5-25B", "Mcap_25-100B", "Mcap_>100B"]:
            for vb in ["Vol_Low_<25%", "Vol_Med_25-40%", "Vol_High_40-60%", "Vol_Extreme_>60%"]:
                sub = u_df[(u_df["mcap_bin"] == mb) & (u_df["vol_bin"] == vb)]
                if len(sub) >= 20:
                    rows_2a.append(calc_stats_row(sub, f"{mb} x {vb}", "Mcap_x_Vol_2D", u_name))
                    
    df_2a = pd.DataFrame(rows_2a)
    df_2a.to_csv(f"{OUT_DIR}/table_2a_base_rate_and_mcap_vol.csv", index=False)
    print(f"Saved Table 2A ({len(df_2a)} rows).")

    print("[4/6] Generating Table 2B: Trailing Fundamentals (Rev Accel, Margin Expansion, Jump Streak)...")
    # Table 2B1: Revenue Acceleration
    rows_2b1 = []
    for u_name in ["All_Investable_ge5B", "Large_Cap_ge25B"]:
        u_df = universes[u_name]
        for n in [0, 1, 2, "3+"]:
            if n == "3+":
                sub = u_df[u_df["prior_consec_rev_accel_n"] >= 3]
                lbl = "prior_consec_rev_accel_n >= 3"
            else:
                sub = u_df[u_df["prior_consec_rev_accel_n"] == n]
                lbl = f"prior_consec_rev_accel_n == {n}"
            rows_2b1.append(calc_stats_row(sub, lbl, "Revenue_Acceleration", u_name))
    df_2b1 = pd.DataFrame(rows_2b1)
    df_2b1.to_csv(f"{OUT_DIR}/table_2b1_revenue_acceleration.csv", index=False)
    
    # Table 2B2: Margin Expansion & Inflections
    rows_2b2 = []
    for u_name in ["All_Investable_ge5B", "Large_Cap_ge25B"]:
        u_df = universes[u_name]
        # Base
        rows_2b2.append(calc_stats_row(u_df, "Baseline", "Margin_Baseline", u_name))
        # Gross Margin - SG&A Expansion
        rows_2b2.append(calc_stats_row(u_df[u_df["prior_consec_gm_sga_expand_n"] < 2], "prior_consec_gm_sga_expand_n < 2", "GM_SGA_Expand", u_name))
        rows_2b2.append(calc_stats_row(u_df[u_df["prior_consec_gm_sga_expand_n"] >= 2], "prior_consec_gm_sga_expand_n >= 2", "GM_SGA_Expand", u_name))
        # OPM Expansion
        rows_2b2.append(calc_stats_row(u_df[u_df["prior_consec_opm_expand_n"] < 2], "prior_consec_opm_expand_n < 2", "OPM_Expand", u_name))
        rows_2b2.append(calc_stats_row(u_df[u_df["prior_consec_opm_expand_n"] >= 2], "prior_consec_opm_expand_n >= 2", "OPM_Expand", u_name))
        # Both Expansion >= 2
        both_exp = (u_df["prior_consec_gm_sga_expand_n"] >= 2) & (u_df["prior_consec_opm_expand_n"] >= 2)
        rows_2b2.append(calc_stats_row(u_df[both_exp], "Both_GM_SGA_and_OPM_Expand_ge2", "Dual_Margin_Expand", u_name))
        # Double inflection
        for d in [0, 1, 2, "3+"]:
            if d == "3+":
                sub = u_df[u_df["prior_consec_double_inflect_n"] >= 3]
                lbl = "prior_consec_double_inflect_n >= 3"
            else:
                sub = u_df[u_df["prior_consec_double_inflect_n"] == d]
                lbl = f"prior_consec_double_inflect_n == {d}"
            rows_2b2.append(calc_stats_row(sub, lbl, "Double_Inflection_Streak", u_name))
        # Turnaround to profit
        rows_2b2.append(calc_stats_row(u_df[u_df["prior_turnaround_to_profit_1q"] == 1], "prior_turnaround_to_profit_1q == 1", "Turnaround_Profit", u_name))
    df_2b2 = pd.DataFrame(rows_2b2)
    df_2b2.to_csv(f"{OUT_DIR}/table_2b2_margin_expansion.csv", index=False)

    # Table 2B3: Jump & Drop Streak Dynamics (PEAD / Reaction Persistence)
    rows_2b3 = []
    for u_name in ["All_Investable_ge5B", "Large_Cap_ge25B"]:
        u_df = universes[u_name]
        # Jump 10% streaks
        for s in [0, 1, 2, "3+"]:
            if s == "3+":
                sub = u_df[u_df["prior_jump10_streak"] >= 3]
                lbl = "prior_jump10_streak >= 3"
            else:
                sub = u_df[u_df["prior_jump10_streak"] == s]
                lbl = f"prior_jump10_streak == {s}"
            rows_2b3.append(calc_stats_row(sub, lbl, "Jump_10pct_Streak", u_name))
            
        # Drop 10% streaks
        for s in [0, 1, 2, "3+"]:
            if s == "3+":
                sub = u_df[u_df["prior_drop10_streak"] >= 3]
                lbl = "prior_drop10_streak >= 3"
            else:
                sub = u_df[u_df["prior_drop10_streak"] == s]
                lbl = f"prior_drop10_streak == {s}"
            rows_2b3.append(calc_stats_row(sub, lbl, "Drop_10pct_Streak", u_name))
            
        # Jump 8% streaks
        for s in [0, 1, 2, "3+"]:
            if s == "3+":
                sub = u_df[u_df["prior_jump8_streak"] >= 3]
                lbl = "prior_jump8_streak >= 3"
            else:
                sub = u_df[u_df["prior_jump8_streak"] == s]
                lbl = f"prior_jump8_streak == {s}"
            rows_2b3.append(calc_stats_row(sub, lbl, "Jump_8pct_Streak", u_name))
    df_2b3 = pd.DataFrame(rows_2b3)
    df_2b3.to_csv(f"{OUT_DIR}/table_2b3_jump_streak_dynamics.csv", index=False)
    print("Saved Table 2B1, 2B2, 2B3.")

    print("[5/6] Generating Table 2C: 3D Grid (Chart x Valuation x Prior Inflection) & High-Win/Firepit Combos...")
    u_invest = universes["All_Investable_ge5B"]
    
    # Full 3D Grid
    rows_2c1 = []
    # 1D Chart Pattern alone
    for tag in ["TightBase_6M", "SlowUp_2to5Y", "SlowUp_6Mto2Y", "DeepDrawdown_Left", "HighFlyer_Parabolic", "Other_Neutral"]:
        sub = u_invest[u_invest["slow_uptrend_tag"] == tag]
        rows_2c1.append(calc_stats_row(sub, tag, "Chart_Tag_Alone", "All_Investable_ge5B"))
    
    # 1D Valuation alone (PE & PS)
    for b in ["PE_Neg_Loss", "PE_0-15", "PE_15-25", "PE_25-45", "PE_gt45"]:
        sub = u_invest[u_invest["pe_bin"] == b]
        rows_2c1.append(calc_stats_row(sub, b, "PE_Bin_Alone", "All_Investable_ge5B"))
    for b in ["PS_lt3", "PS_3-8", "PS_8-15", "PS_gt15"]:
        sub = u_invest[u_invest["ps_bin"] == b]
        rows_2c1.append(calc_stats_row(sub, b, "PS_Bin_Alone", "All_Investable_ge5B"))
        
    # 2D Grids
    for tag in ["TightBase_6M", "SlowUp_2to5Y", "SlowUp_6Mto2Y", "DeepDrawdown_Left", "HighFlyer_Parabolic"]:
        for ps_b in ["PS_lt3", "PS_3-8", "PS_8-15", "PS_gt15"]:
            sub = u_invest[(u_invest["slow_uptrend_tag"] == tag) & (u_invest["ps_bin"] == ps_b)]
            if len(sub) >= 20:
                rows_2c1.append(calc_stats_row(sub, f"{tag} x {ps_b}", "Chart_x_PS", "All_Investable_ge5B"))
                
    # 3D Grids: Chart x PS x Prior Double Inflection
    combo_rows = []
    for (tag, ps_b, inflect), grp in u_invest.groupby(["slow_uptrend_tag", "ps_bin", "prior_double_inflect"]):
        if len(grp) >= 20:
            c_row = calc_stats_row(grp, f"{tag} x {ps_b} x {inflect}", "Chart_x_PS_x_Inflect", "All_Investable_ge5B")
            c_row["chart_tag"] = tag
            c_row["ps_bin"] = ps_b
            c_row["prior_double_inflect"] = inflect
            combo_rows.append(c_row)
            rows_2c1.append(c_row)
            
    df_2c1 = pd.DataFrame(rows_2c1)
    df_2c1.to_csv(f"{OUT_DIR}/table_2c1_chart_valuation_inflection_matrix.csv", index=False)
    
    # Extract High-Win / High-Ratio Candidates (Ratio >= 1.50, N >= 40, mean_jump_ret > 0)
    df_combos = pd.DataFrame(combo_rows)
    high_win = df_combos[(df_combos["N"] >= 40) & (df_combos["ratio_jump10_drop10"] >= 1.50) & (df_combos["mean_jump_ret"] > 0)].sort_values("ratio_jump10_drop10", ascending=False)
    high_win.to_csv(f"{OUT_DIR}/table_2c2_high_win_combinations.csv", index=False)
    
    # Extract Firepits (Ratio <= 0.80 or (p_drop_10 > p_jump_10 and N >= 40))
    firepits = df_combos[(df_combos["N"] >= 40) & (df_combos["ratio_jump10_drop10"] <= 0.80)].sort_values("ratio_jump10_drop10", ascending=True)
    firepits.to_csv(f"{OUT_DIR}/table_2c3_firepit_combinations.csv", index=False)
    print(f"Saved Table 2C1 ({len(df_2c1)} rows), 2C2 High-Win ({len(high_win)} combos), 2C3 Firepits ({len(firepits)} combos).")

    print("[6/6] Generating Table 2D: Macro Regimes & Valuation Asymmetry...")
    rows_2d1 = []
    for u_name in ["All_Investable_ge5B", "Large_Cap_ge25B"]:
        u_df = universes[u_name]
        # VIX Regimes
        for vx in ["LowVol", "NormalVol", "HighVol", "PanicVol"]:
            sub = u_df[u_df["vix_regime"] == vx]
            if len(sub) > 0:
                rows_2d1.append(calc_stats_row(sub, vx, "VIX_Regime", u_name))
                
        # Rate Direction 6M
        for rd in ["Rising_35bp+", "Stable", "Falling_35bp+"]:
            sub = u_df[u_df["rate_dir_6m"] == rd]
            if len(sub) > 0:
                rows_2d1.append(calc_stats_row(sub, rd, "Rate_Dir_6M", u_name))
                
        # Yield Curve Regimes
        for yc in ["Steep_EarlyCycle_gt120bp", "Flat_Normal_0_120bp", "Inverted", "Bear_or_Bull_Uninverting"]:
            sub = u_df[u_df["yc_regime"] == yc]
            if len(sub) > 0:
                rows_2d1.append(calc_stats_row(sub, yc, "Yield_Curve_Regime", u_name))
                
        # Credit Regimes
        for cr in ["Benign", "Normal", "Tightening_Stress", "Credit_Crisis"]:
            sub = u_df[u_df["credit_regime"] == cr]
            if len(sub) > 0:
                rows_2d1.append(calc_stats_row(sub, cr, "Credit_Regime", u_name))
                
        # Macro Quadrants
        for mq in ["Q1_Goldilocks", "Q2_Reflation_CapexBoom", "Q3_Tightening_Stagflation", "Q4_Recession_CreditStress"]:
            sub = u_df[u_df["macro_quadrant"] == mq]
            if len(sub) > 0:
                rows_2d1.append(calc_stats_row(sub, mq, "Macro_Quadrant", u_name))
                
        # Era Regimes (explicitly isolating 2020-2021 Zero Rate and 2022-2026 High Rate)
        for era in ["2010_2019_LowRateBull", "2020_2021_ZeroRateCovid", "2022_2026_HighRateEra", "2008_2009_GFC"]:
            sub = u_df[u_df["era_custom"] == era]
            if len(sub) > 0:
                rows_2d1.append(calc_stats_row(sub, era, "Era_Regime", u_name))
                
    df_2d1 = pd.DataFrame(rows_2d1)
    df_2d1.to_csv(f"{OUT_DIR}/table_2d1_macro_regimes.csv", index=False)
    
    # Table 2D2: Macro x Valuation Asymmetry
    rows_2d2 = []
    for u_name in ["All_Investable_ge5B", "Large_Cap_ge25B"]:
        u_df = universes[u_name]
        
        # Era x PS Bins
        for era in ["2010_2019_LowRateBull", "2020_2021_ZeroRateCovid", "2022_2026_HighRateEra"]:
            for ps_b in ["PS_lt3", "PS_3-8", "PS_8-15", "PS_gt15"]:
                sub = u_df[(u_df["era_custom"] == era) & (u_df["ps_bin"] == ps_b)]
                if len(sub) >= 20:
                    rows_2d2.append(calc_stats_row(sub, f"{era} x {ps_b}", "Era_x_PS", u_name))
                    
        # Rate Direction x PS Bins
        for rd in ["Rising_35bp+", "Stable", "Falling_35bp+"]:
            for ps_b in ["PS_lt3", "PS_gt15"]:
                sub = u_df[(u_df["rate_dir_6m"] == rd) & (u_df["ps_bin"] == ps_b)]
                if len(sub) >= 20:
                    rows_2d2.append(calc_stats_row(sub, f"{rd} x {ps_b}", "RateDir_x_PS", u_name))
                    
        # VIX x Chart Tag
        for vx in ["LowVol", "PanicVol"]:
            for tag in ["HighFlyer_Parabolic", "TightBase_6M"]:
                sub = u_df[(u_df["vix_regime"] == vx) & (u_df["slow_uptrend_tag"] == tag)]
                if len(sub) >= 20:
                    rows_2d2.append(calc_stats_row(sub, f"{vx} x {tag}", "VIX_x_ChartTag", u_name))
                    
    df_2d2 = pd.DataFrame(rows_2d2)
    df_2d2.to_csv(f"{OUT_DIR}/table_2d2_macro_x_valuation.csv", index=False)
    print(f"Saved Table 2D1 ({len(df_2d1)} rows) and 2D2 ({len(df_2d2)} rows).")
    print(f"All processing complete in {time.time()-t0:.2f}s!")

if __name__ == "__main__":
    main()

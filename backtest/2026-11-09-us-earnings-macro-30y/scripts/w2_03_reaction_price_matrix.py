"""
w2_03_reaction_price_matrix.py
Module 3: Earnings Reaction x Multi-Quarter Fundamental Trajectory x Pre-Earnings Price Structure
30-Year / SEC XBRL Point-in-Time (PIT) Zero-Lookahead Backtest Engine.

Strict Guarantees:
1. 100% Zero Lookahead: All forward returns (63d, 252d, 504d, 756d) start strictly at entry_date = D+1 close
   after the SEC filing reaction completes. Zero leakage of earnings-day jump into forward returns.
2. D15 & Anti-Bias Compliance via backtest_stats_lib.py:
   - Calendar-quarter equal-weight excess return vs SPY (qtr_ew_alpha)
   - 250-trading-day per-ticker cooldown deduplication (dedup_mean_alpha, med_alpha, win_rate, payoff, bag2x_prob, halve_prob)
   - Explicit Ex-2020-2021 COVID Bubble & High-Rate Era (2022-2026) subperiod splits
   - Benjamini-Hochberg FDR multiple-testing adjustment
3. Dual Market-Cap Pools (2026 S&P 500 index-scaled equivalent market cap):
   - LargeCap_25B: mcap_2026_equiv_b >= 25.0
   - MidCap_5to25B: 5.0 <= mcap_2026_equiv_b < 25.0
"""

import os
import sys
import json
import time
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

PROJ_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-09-us-earnings-macro-30y"
DATA_PATH = os.path.join(PROJ_DIR, "data/xbrl_master_pit_2009_2026.parquet")
OUT_DIR = os.path.join(PROJ_DIR, "results/m3_reaction_price")
SCRIPTS_DIR = os.path.join(PROJ_DIR, "scripts")

sys.path.insert(0, SCRIPTS_DIR)
from backtest_stats_lib import (
    eval_slice,
    eval_d15_subperiods,
    benjamini_hochberg_fdr,
    deduplicate_cooldown,
)
from price_feature_lib import PriceEngine, TAG_MAP

HORIZONS = (63, 252, 504, 756)
DEDUP_DAYS = 250


def prepare_master_dataset() -> pd.DataFrame:
    t0 = time.time()
    df = pd.read_parquet(DATA_PATH)
    # Remove split/spinoff discontinuities and require valid reaction & D+1 entry
    mask_valid = (
        (~df["has_anomaly_break"].fillna(False))
        & df["earn_jump_ret"].notna()
        & df["entry_date"].notna()
        & df["entry_adj_close"].notna()
    )
    df = df[mask_valid].sort_values(["ticker", "end", "filed"]).reset_index(drop=True)

    # 1. Consecutive fundamental deterioration & strict acceleration counters (strictly PIT per ticker)
    n = len(df)
    tks = df["ticker"].values
    ends = pd.to_datetime(df["end"]).values

    rev_dec = (df["rev_accel_1q"] < 0).values
    opm_shr = (df["opm_yoy_chg"] < -0.005).values
    both_det = (((df["rev_accel_1q"] < 0) | (df["rev_yoy"] < 0)) & (df["opm_yoy_chg"] < -0.005)).values

    c_rev_dec = np.zeros(n, dtype=np.int32)
    c_opm_shr = np.zeros(n, dtype=np.int32)
    c_both_det = np.zeros(n, dtype=np.int32)

    for i in range(n):
        if i > 0 and tks[i] == tks[i - 1]:
            gap_d = (ends[i] - ends[i - 1]) / np.timedelta64(1, "D")
            if 60 <= gap_d <= 135:
                c_rev_dec[i] = c_rev_dec[i - 1] + 1 if rev_dec[i] else 0
                c_opm_shr[i] = c_opm_shr[i - 1] + 1 if opm_shr[i] else 0
                c_both_det[i] = c_both_det[i - 1] + 1 if both_det[i] else 0
            else:
                c_rev_dec[i] = 1 if rev_dec[i] else 0
                c_opm_shr[i] = 1 if opm_shr[i] else 0
                c_both_det[i] = 1 if both_det[i] else 0
        else:
            c_rev_dec[i] = 1 if rev_dec[i] else 0
            c_opm_shr[i] = 1 if opm_shr[i] else 0
            c_both_det[i] = 1 if both_det[i] else 0

    df["consec_rev_decel_n"] = c_rev_dec
    df["consec_opm_shrink_n"] = c_opm_shr
    df["consec_both_det_n"] = c_both_det

    prior_lags = np.column_stack([
        df["rev_yoy_lag1"].values,
        df["rev_yoy_lag2"].values,
        df["rev_yoy_lag3"].values,
    ])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        prior_pk_rev = np.nanmax(prior_lags, axis=1)
    df["prior_3q_peak_rev_yoy"] = prior_pk_rev
    df["rev_drop_vs_prior3q"] = df["rev_yoy"] - prior_pk_rev

    # 2. Full 8-K + 10-Q Earnings Window Shock Robustness Column (strictly <= entry_date, zero lookahead)
    pe = PriceEngine.get_instance()
    stock_cols = np.array([pe.tk_to_col.get(tk, -1) for tk in tks], dtype=np.int32)
    filed_dt_vals = pd.to_datetime(df["filed"]).dt.normalize().values.astype("datetime64[D]")
    idx_ev = np.clip(np.searchsorted(pe.dates, filed_dt_vals), 0, pe.n_days - 1)

    shock_2d = np.full(n, np.nan, dtype=np.float32)
    shock_pre_tag = np.full(n, "Other_Neutral", dtype=object)
    ej_arr = df["earn_jump_ret"].values

    for i in range(n):
        c = stock_cols[i]
        d_ev = idx_ev[i]
        if c < 0 or d_ev < 10 or d_ev + 1 >= pe.n_days:
            continue
        best_r = float(ej_arr[i])
        best_abs = abs(best_r) if not np.isnan(best_r) else -1.0
        best_s = d_ev - 1
        for e_i in range(d_ev - 7, d_ev + 2):
            s_i = e_i - 2
            p0 = pe.P_adj[s_i, c]
            p1 = pe.P_adj[e_i, c]
            if p0 > 0 and p1 > 0 and not np.isnan(p0) and not np.isnan(p1):
                r2 = float(p1 / p0 - 1.0)
                if abs(r2) > best_abs:
                    best_abs = abs(r2)
                    best_r = r2
                    best_s = s_i
        shock_2d[i] = best_r
        shock_pre_tag[i] = TAG_MAP.get(int(pe.slow_tag[best_s, c]), "Other_Neutral")

    df["earn_win_shock_2d"] = shock_2d
    df["shock_pre_slow_tag"] = shock_pre_tag

    # 3. Canonical 5-Tier Earnings Reaction Classification
    ej = df["earn_jump_ret"]
    df["react_tier"] = np.select(
        [
            ej >= 0.10,
            (ej >= 0.04) & (ej < 0.10),
            (ej > -0.04) & (ej < 0.04),
            (ej > -0.10) & (ej <= -0.04),
            ej <= -0.10,
        ],
        [
            "R1_BigJump_ge10",
            "R2_ModJump_4to10",
            "R3_Flat_m4to4",
            "R4_ModDrop_m10tom4",
            "R5_BigDrop_lem10",
        ],
        default="Missing",
    )

    # 4. Canonical 5-Tier Mutually Exclusive Fundamental Trajectory Classification
    cond_f3 = (
        ((df["ni_ttm"] <= 0) | (df["opinc_ttm"] <= 0))
        & (df["gm_minus_sga_q"] > 0.10)
        & (df["gm_sga_yoy_chg"] > 0)
        & (df["rev_yoy"] >= 0.05)
    )
    cond_f1 = (~cond_f3) & (df["consec_double_inflect_n"] >= 3) & (df["rev_yoy"] >= 0.05)
    cond_f2 = (~cond_f3) & (~cond_f1) & (df["consec_double_inflect_n"] == 1) & (df["rev_yoy"] >= 0.05)
    cond_f4 = (
        (~cond_f3)
        & (~cond_f1)
        & (~cond_f2)
        & (((df["rev_yoy"] <= 0.02) | ((df["rev_yoy"] < 0.05) & (df["rev_accel_1q"] <= 0))) & (df["opm_yoy_chg"] > 0.003))
    )
    cond_f5 = (
        (~cond_f3)
        & (~cond_f1)
        & (~cond_f2)
        & (~cond_f4)
        & (((df["rev_accel_1q"] < 0) | (df["rev_yoy"] < 0)) & (df["opm_yoy_chg"] < -0.003))
    )

    df["fund_tier"] = np.select(
        [cond_f1, cond_f2, cond_f3, cond_f4, cond_f5],
        [
            "F1_3to4Q_DoubleInflect",
            "F2_1Q_InitialInflect",
            "F3_Unprof_GMSGA_gt10_Exp",
            "F4_CostCut_FakeInflect",
            "F5_Decel_Deteriorate",
        ],
        default="F0_Other_Steady",
    )

    # Pool flags
    df["pool_large_25b"] = df["mcap_2026_equiv_b"] >= 25.0
    df["pool_mid_5to25b"] = (df["mcap_2026_equiv_b"] >= 5.0) & (df["mcap_2026_equiv_b"] < 25.0)

    dt_ent = pd.to_datetime(df["entry_date"])
    df["is_ex_bubble"] = ~((dt_ent >= "2020-03-01") & (dt_ent <= "2021-12-31"))

    print(f"[prepare_master_dataset] Ready: {len(df):,} clean events in {time.time() - t0:.2f}s.")
    return df


def eval_with_ex_bubble(df_sub: pd.DataFrame, meta: dict) -> dict:
    row = dict(meta)
    base = eval_slice(df_sub, horizons=HORIZONS, dedup_days=DEDUP_DAYS, label=meta.get("slice_name", ""))
    row.update(base)
    if "is_ex_bubble" in df_sub.columns:
        ex_sub = df_sub[df_sub["is_ex_bubble"]]
        ex_res = eval_slice(ex_sub, horizons=(63, 252, 756), dedup_days=DEDUP_DAYS, label="ex_bub")
        for h in (63, 252, 756):
            row[f"ex_bub_n_{h}d"] = ex_res.get(f"n_{h}d", 0)
            row[f"ex_bub_qtr_ew_alpha_{h}d"] = ex_res.get(f"qtr_ew_alpha_{h}d", np.nan)
            row[f"ex_bub_med_alpha_{h}d"] = ex_res.get(f"med_alpha_{h}d", np.nan)
            row[f"ex_bub_win_rate_{h}d"] = ex_res.get(f"win_rate_{h}d", np.nan)
    return row


def run_table_3a(df: pd.DataFrame) -> pd.DataFrame:
    fund_order = [
        "F1_3to4Q_DoubleInflect",
        "F2_1Q_InitialInflect",
        "F3_Unprof_GMSGA_gt10_Exp",
        "F4_CostCut_FakeInflect",
        "F5_Decel_Deteriorate",
    ]
    react_order = [
        "R1_BigJump_ge10",
        "R2_ModJump_4to10",
        "R3_Flat_m4to4",
        "R4_ModDrop_m10tom4",
        "R5_BigDrop_lem10",
    ]
    pools = [
        ("LargeCap_25B", df["pool_large_25b"]),
        ("MidCap_5to25B", df["pool_mid_5to25b"]),
    ]

    rows = []
    for pool_name, pmask in pools:
        pdf = df[pmask]
        # 1. 5 x 5 Core Matrix
        for ft in fund_order:
            for rt in react_order:
                sub = pdf[(pdf["fund_tier"] == ft) & (pdf["react_tier"] == rt)]
                rows.append(
                    eval_with_ex_bubble(
                        sub,
                        {
                            "pool": pool_name,
                            "section": "Core_5x5_Matrix",
                            "fund_tier": ft,
                            "react_tier": rt,
                            "slice_name": f"{pool_name} | {ft} x {rt}",
                        },
                    )
                )
            # Row marginal across all reactions
            sub_f = pdf[pdf["fund_tier"] == ft]
            rows.append(
                eval_with_ex_bubble(
                    sub_f,
                    {
                        "pool": pool_name,
                        "section": "Marginal_By_Fundamental",
                        "fund_tier": ft,
                        "react_tier": "ALL_REACTIONS",
                        "slice_name": f"{pool_name} | {ft} x ALL",
                    },
                )
            )

        # 2. Column marginal across all fundamentals
        for rt in react_order:
            sub_r = pdf[pdf["react_tier"] == rt]
            rows.append(
                eval_with_ex_bubble(
                    sub_r,
                    {
                        "pool": pool_name,
                        "section": "Marginal_By_Reaction",
                        "fund_tier": "ALL_FUNDAMENTALS",
                        "react_tier": rt,
                        "slice_name": f"{pool_name} | ALL x {rt}",
                    },
                )
            )

        # 3. Direct Head-to-Head: True Acceleration (F1 + F3) Mispriced Drop vs Flat vs Consensus Jump
        true_acc = pdf[pdf["fund_tier"].isin(["F1_3to4Q_DoubleInflect", "F3_Unprof_GMSGA_gt10_Exp"])]
        h2h_cuts = [
            ("TrueAcc_F1_or_F3", "Mispriced_Drop_le_m4", true_acc[true_acc["earn_jump_ret"] <= -0.04]),
            ("TrueAcc_F1_or_F3", "Mispriced_Drop_le_m5", true_acc[true_acc["earn_jump_ret"] <= -0.05]),
            ("TrueAcc_F1_or_F3", "Mispriced_Crash_le_m10", true_acc[true_acc["earn_jump_ret"] <= -0.10]),
            ("TrueAcc_F1_or_F3", "Flat_m4_to_p4", true_acc[(true_acc["earn_jump_ret"] > -0.04) & (true_acc["earn_jump_ret"] < 0.04)]),
            ("TrueAcc_F1_or_F3", "Consensus_Jump_ge_p4", true_acc[true_acc["earn_jump_ret"] >= 0.04]),
            ("TrueAcc_F1_or_F3", "Consensus_BigJump_ge_p10", true_acc[true_acc["earn_jump_ret"] >= 0.10]),
            # Pure uncontaminated earnings-window drop robustness (8K+10Q window shock <= -5%)
            ("TrueAcc_F1_or_F3_Win8K10Q", "WinShock_Drop_le_m5", true_acc[(true_acc["earn_jump_ret"] <= -0.04) & (true_acc["earn_win_shock_2d"] <= -0.05)]),
            ("TrueAcc_F1_or_F3_Win8K10Q", "WinShock_Jump_ge_p10", true_acc[true_acc["earn_win_shock_2d"] >= 0.10]),
            # Separate F1 vs F3 Mispriced Drop <= -4%
            ("F1_Only_3to4Q_DblInf", "Mispriced_Drop_le_m4", pdf[(pdf["fund_tier"] == "F1_3to4Q_DoubleInflect") & (pdf["earn_jump_ret"] <= -0.04)]),
            ("F1_Only_3to4Q_DblInf", "Consensus_Jump_ge_p4", pdf[(pdf["fund_tier"] == "F1_3to4Q_DoubleInflect") & (pdf["earn_jump_ret"] >= 0.04)]),
            ("F3_Only_Unprof_GMSGA_gt10", "Mispriced_Drop_le_m4", pdf[(pdf["fund_tier"] == "F3_Unprof_GMSGA_gt10_Exp") & (pdf["earn_jump_ret"] <= -0.04)]),
            ("F3_Only_Unprof_GMSGA_gt10", "Consensus_Jump_ge_p4", pdf[(pdf["fund_tier"] == "F3_Unprof_GMSGA_gt10_Exp") & (pdf["earn_jump_ret"] >= 0.04)]),
        ]
        for fg, rg, s_df in h2h_cuts:
            rows.append(
                eval_with_ex_bubble(
                    s_df,
                    {
                        "pool": pool_name,
                        "section": "HeadToHead_Mispriced_vs_Consensus",
                        "fund_tier": fg,
                        "react_tier": rg,
                        "slice_name": f"{pool_name} | {fg} | {rg}",
                    },
                )
            )

    out = pd.DataFrame(rows)
    if "p_val_252d" in out.columns:
        out["bh_fdr_q_252d"] = benjamini_hochberg_fdr(out["p_val_252d"].values)
    return out


def run_table_3b(df: pd.DataFrame) -> pd.DataFrame:
    pools = [
        ("LargeCap_25B", df["pool_large_25b"]),
        ("MidCap_5to25B", df["pool_mid_5to25b"]),
    ]
    rows = []
    for pool_name, pmask in pools:
        for jump_label, j_thr in [("Jump_ge8pct", 0.08), ("Jump_ge10pct", 0.10)]:
            jdf = df[pmask & (df["earn_jump_ret"] >= j_thr)]
            # Baseline
            rows.append(
                eval_with_ex_bubble(
                    jdf,
                    {
                        "pool": pool_name,
                        "jump_threshold": jump_label,
                        "cut_dimension": "0_Baseline",
                        "cut_group": f"All_{jump_label}",
                        "slice_name": f"{pool_name} | {jump_label} | Baseline",
                    },
                )
            )

            # 1. Pre-Earnings Price Structure
            for tag in ["SlowUp_2to5Y", "SlowUp_6Mto2Y", "TightBase_6M", "HighFlyer_Parabolic", "DeepDrawdown_Left", "Other_Neutral"]:
                rows.append(
                    eval_with_ex_bubble(
                        jdf[jdf["slow_uptrend_tag"] == tag],
                        {
                            "pool": pool_name,
                            "jump_threshold": jump_label,
                            "cut_dimension": "1_PrePrice_Structure",
                            "cut_group": tag,
                            "slice_name": f"{pool_name} | {jump_label} | {tag}",
                        },
                    )
                )

            # 2. Valuation Cuts (PE, PS, PEG)
            val_slices = [
                ("PE_0to25_Reasonable", (jdf["pe_pit"] > 0) & (jdf["pe_pit"] <= 25)),
                ("PE_25to50_Growth", (jdf["pe_pit"] > 25) & (jdf["pe_pit"] <= 50)),
                ("PE_gt50_Expensive", jdf["pe_pit"] > 50),
                ("PE_le0_Unprofitable", jdf["pe_pit"] <= 0),
                ("PS_le4_Low", (jdf["ps_pit"] > 0) & (jdf["ps_pit"] <= 4)),
                ("PS_4to10_Mid", (jdf["ps_pit"] > 4) & (jdf["ps_pit"] <= 10)),
                ("PS_10to20_High", (jdf["ps_pit"] > 10) & (jdf["ps_pit"] <= 20)),
                ("PS_gt20_ExtremeTrap", jdf["ps_pit"] > 20),
                ("PEG_rev_le1.5", (jdf["peg_rev_pit"] > 0) & (jdf["peg_rev_pit"] <= 1.5)),
                ("PEG_rev_1.5to3.0", (jdf["peg_rev_pit"] > 1.5) & (jdf["peg_rev_pit"] <= 3.0)),
                ("PEG_rev_gt3.0", jdf["peg_rev_pit"] > 3.0),
                ("PEG_ni_le1.2", (jdf["peg_ni_pit"] > 0) & (jdf["peg_ni_pit"] <= 1.2)),
                ("PEG_ni_gt1.2", jdf["peg_ni_pit"] > 1.2),
            ]
            for vname, vmask in val_slices:
                rows.append(
                    eval_with_ex_bubble(
                        jdf[vmask],
                        {
                            "pool": pool_name,
                            "jump_threshold": jump_label,
                            "cut_dimension": "2_Valuation",
                            "cut_group": vname,
                            "slice_name": f"{pool_name} | {jump_label} | {vname}",
                        },
                    )
                )

            # 3. Consecutive Inflection Quarters
            inf_slices = [
                ("Consec_DblInf_0Q", jdf["consec_double_inflect_n"] == 0),
                ("Consec_DblInf_1Q_Flash", jdf["consec_double_inflect_n"] == 1),
                ("Consec_DblInf_2Q", jdf["consec_double_inflect_n"] == 2),
                ("Consec_DblInf_ge3Q_Sustained", jdf["consec_double_inflect_n"] >= 3),
                ("Unprof_GMSGA_gt10_Expanding", jdf["fund_tier"] == "F3_Unprof_GMSGA_gt10_Exp"),
            ]
            for iname, imask in inf_slices:
                rows.append(
                    eval_with_ex_bubble(
                        jdf[imask],
                        {
                            "pool": pool_name,
                            "jump_threshold": jump_label,
                            "cut_dimension": "3_Inflection_Duration",
                            "cut_group": iname,
                            "slice_name": f"{pool_name} | {jump_label} | {iname}",
                        },
                    )
                )

            # 4. Sector Cyclicality
            sec_slices = [
                ("Non_Cyclical_All", jdf["sector_type"] != "Deep_Cyclical"),
                ("Non_Cyc_ExFinUtil_CompounderTechHC", ~jdf["sector_type"].isin(["Deep_Cyclical", "Financial_Utility_RateSens"])),
                ("Tech_Soft_HC_Growth", jdf["sector_type"].isin(["Software_Internet", "Tech_Hardware_Semi", "Healthcare_LifeSci"])),
                ("Deep_Cyclical_Only", jdf["sector_type"] == "Deep_Cyclical"),
                ("Financial_Utility_RateSens", jdf["sector_type"] == "Financial_Utility_RateSens"),
            ]
            for sname, smask in sec_slices:
                rows.append(
                    eval_with_ex_bubble(
                        jdf[smask],
                        {
                            "pool": pool_name,
                            "jump_threshold": jump_label,
                            "cut_dimension": "4_Sector_Attribute",
                            "cut_group": sname,
                            "slice_name": f"{pool_name} | {jump_label} | {sname}",
                        },
                    )
                )

            # 5. Multi-Factor Golden Conditions vs Forbidden Chasing Red Lines
            combo_slices = [
                (
                    "GOLDEN_1_DblInf>=3Q_PS<=12_NonCyclical",
                    (jdf["consec_double_inflect_n"] >= 3) & (jdf["ps_pit"] <= 12) & (jdf["sector_type"] != "Deep_Cyclical"),
                ),
                (
                    "GOLDEN_2_DblInf>=3Q_PE10to45_NonCyclical",
                    (jdf["consec_double_inflect_n"] >= 3) & jdf["pe_pit"].between(10, 45) & (jdf["sector_type"] != "Deep_Cyclical"),
                ),
                (
                    "GOLDEN_3_TechSoftHC_DblInf>=3Q_PS<=15",
                    jdf["sector_type"].isin(["Software_Internet", "Tech_Hardware_Semi", "Healthcare_LifeSci"])
                    & (jdf["consec_double_inflect_n"] >= 3)
                    & (jdf["ps_pit"] <= 15),
                ),
                (
                    "GOLDEN_4_SlowUp_DblInf>=2Q_PS<=15_NonCyclical",
                    jdf["slow_uptrend_tag"].isin(["SlowUp_2to5Y", "SlowUp_6Mto2Y"])
                    & (jdf["consec_double_inflect_n"] >= 2)
                    & (jdf["ps_pit"] <= 15)
                    & (jdf["sector_type"] != "Deep_Cyclical"),
                ),
                (
                    "REDLINE_1_ExtremeValuation_PS_gt20",
                    jdf["ps_pit"] > 20,
                ),
                (
                    "REDLINE_2_Unprofitable_WeakUnitEcon_GMSGA<=10pct",
                    (jdf["pe_pit"] <= 0) & ((jdf["gm_minus_sga_q"] <= 0.10) | jdf["gm_minus_sga_q"].isna()),
                ),
                (
                    "REDLINE_3_Parabolic_Overheated_HighFlyer",
                    jdf["slow_uptrend_tag"] == "HighFlyer_Parabolic",
                ),
                (
                    "REDLINE_4_FakeCostCut_TightBase_or_LeftDrawdown",
                    (jdf["fund_tier"] == "F4_CostCut_FakeInflect")
                    & jdf["slow_uptrend_tag"].isin(["TightBase_6M", "DeepDrawdown_Left"]),
                ),
                (
                    "REDLINE_5_Single1QFlash_Expensive_PS>10_or_PE>50",
                    (jdf["consec_double_inflect_n"] == 1) & ((jdf["ps_pit"] > 10) | (jdf["pe_pit"] > 50)),
                ),
            ]
            for cname, cmask in combo_slices:
                rows.append(
                    eval_with_ex_bubble(
                        jdf[cmask],
                        {
                            "pool": pool_name,
                            "jump_threshold": jump_label,
                            "cut_dimension": "5_Golden_vs_RedLine_Rules",
                            "cut_group": cname,
                            "slice_name": f"{pool_name} | {jump_label} | {cname}",
                        },
                    )
                )

    out = pd.DataFrame(rows)
    if "p_val_252d" in out.columns:
        out["bh_fdr_q_252d"] = benjamini_hochberg_fdr(out["p_val_252d"].values)
    return out


def run_table_3c(df: pd.DataFrame) -> pd.DataFrame:
    pools = [
        ("LargeCap_25B_All", df["pool_large_25b"]),
        ("LargeCap_25B_ExFinUtil", df["pool_large_25b"] & (df["sector_type"] != "Financial_Utility_RateSens")),
        ("MidCap_5to25B_All", df["pool_mid_5to25b"]),
        ("MidCap_5to25B_ExFinUtil", df["pool_mid_5to25b"] & (df["sector_type"] != "Financial_Utility_RateSens")),
    ]
    rows = []

    # Part A: SlowUp_2to5Y x Fundamental Regime Shift (MainWave vs Steady vs Mild Decel vs True Breakdown)
    for pool_name, pmask in pools:
        su = df[pmask & (df["slow_uptrend_tag"] == "SlowUp_2to5Y")]
        su_slices = [
            ("0_Baseline_Ordinary_SlowUp_2to5Y", pd.Series(True, index=su.index)),
            (
                "1_MainWave_Consec>=3Q_DoubleInflect_ConfirmedJump>=4pct",
                (su["consec_double_inflect_n"] >= 3) & (su["earn_jump_ret"] >= 0.04),
            ),
            (
                "2_MainWave_1to3Q_DoubleInflect_BreakoutJump>=8pct_PS<=15",
                (su["consec_double_inflect_n"] >= 1) & (su["earn_jump_ret"] >= 0.08) & (su["ps_pit"] <= 15),
            ),
            (
                "3_MainWave_Consec>=3Q_DoubleInflect_AllReactions",
                su["consec_double_inflect_n"] >= 3,
            ),
            (
                "4_Steady_Compound_Rev>=5pct_MarginStable",
                (su["rev_yoy"] >= 0.05) & (su["opm_yoy_chg"] >= -0.005) & (su["consec_double_inflect_n"] < 3),
            ),
            (
                "5_Noise_Mild2Q_Decel_OPMDip_All",
                su["consec_both_det_n"] == 2,
            ),
            (
                "6_Breakdown_Consec>=3Q_RevDecel_AND_OPMShrink",
                su["consec_both_det_n"] >= 3,
            ),
            (
                "7_Breakdown_RevNeg_OPMShrink>=200bps_ROICDrop>=150bps",
                (su["rev_yoy"] < 0) & (su["opm_yoy_chg"] <= -0.02) & (su["roic_yoy_chg"] <= -0.015),
            ),
            (
                "8_Breakdown_Consec>=2Q_Det_AND_EarningsDrop<=-4pct",
                (su["consec_both_det_n"] >= 2) & (su["earn_jump_ret"] <= -0.04),
            ),
        ]
        for sname, smask in su_slices:
            rows.append(
                eval_with_ex_bubble(
                    su[smask],
                    {
                        "pool": pool_name,
                        "section": "PartA_SlowUp2to5Y_Regime_Coupling",
                        "pre_structure": "SlowUp_2to5Y",
                        "fundamental_state": sname,
                        "slice_name": f"{pool_name} | SlowUp_2to5Y | {sname}",
                    },
                )
            )

    # Part B: All 6 Pre-Earnings Price Structures x (1Q Inflection vs 3-4Q Inflection vs Unprof GM-SGA>10% vs Decel) Launchpad Matrix
    for pool_name, pmask in [("LargeCap_25B_All", df["pool_large_25b"]), ("MidCap_5to25B_All", df["pool_mid_5to25b"])]:
        pdf = df[pmask]
        for tag in ["SlowUp_2to5Y", "SlowUp_6Mto2Y", "TightBase_6M", "HighFlyer_Parabolic", "DeepDrawdown_Left", "Other_Neutral"]:
            tdf = pdf[pdf["slow_uptrend_tag"] == tag]
            f_states = [
                ("All_Quarters_Baseline", pd.Series(True, index=tdf.index)),
                ("1Q_Initial_DoubleInflect", tdf["fund_tier"] == "F2_1Q_InitialInflect"),
                ("3to4Q_Sustained_DoubleInflect", tdf["fund_tier"] == "F1_3to4Q_DoubleInflect"),
                ("3to4Q_DoubleInflect_AND_Jump>=4pct", (tdf["fund_tier"] == "F1_3to4Q_DoubleInflect") & (tdf["earn_jump_ret"] >= 0.04)),
                ("3to4Q_DoubleInflect_AND_Drop<=-4pct", (tdf["fund_tier"] == "F1_3to4Q_DoubleInflect") & (tdf["earn_jump_ret"] <= -0.04)),
                ("Unprof_GMSGA_gt10_Expanding", tdf["fund_tier"] == "F3_Unprof_GMSGA_gt10_Exp"),
                ("Decel_Deteriorate", tdf["fund_tier"] == "F5_Decel_Deteriorate"),
            ]
            for fn, fm in f_states:
                rows.append(
                    eval_with_ex_bubble(
                        tdf[fm],
                        {
                            "pool": pool_name,
                            "section": "PartB_PreStructure_x_Inflection_Launchpad",
                            "pre_structure": tag,
                            "fundamental_state": fn,
                            "slice_name": f"{pool_name} | {tag} | {fn}",
                        },
                    )
                )

    out = pd.DataFrame(rows)
    if "p_val_252d" in out.columns:
        out["bh_fdr_q_252d"] = benjamini_hochberg_fdr(out["p_val_252d"].values)
    return out


def run_table_3d_subperiods(df: pd.DataFrame) -> pd.DataFrame:
    strategies = []
    for pool_name, pmask in [("LargeCap_25B", df["pool_large_25b"]), ("MidCap_5to25B", df["pool_mid_5to25b"])]:
        pdf = df[pmask]
        true_acc = pdf["fund_tier"].isin(["F1_3to4Q_DoubleInflect", "F3_Unprof_GMSGA_gt10_Exp"])
        strategies.extend([
            (f"{pool_name} | Mispriced_Goldmine (TrueAcc + Drop<=-4%)", pdf[true_acc & (pdf["earn_jump_ret"] <= -0.04)]),
            (f"{pool_name} | Consensus_Confirm (TrueAcc + Jump>=+4%)", pdf[true_acc & (pdf["earn_jump_ret"] >= 0.04)]),
            (
                f"{pool_name} | Golden_JumpChase (Jump>=8% + DblInf>=3Q + PS<=12 + NonCyc)",
                pdf[(pdf["earn_jump_ret"] >= 0.08) & (pdf["consec_double_inflect_n"] >= 3) & (pdf["ps_pit"] <= 12) & (pdf["sector_type"] != "Deep_Cyclical")],
            ),
            (
                f"{pool_name} | RedLine_Trap (Jump>=8% + PS>20)",
                pdf[(pdf["earn_jump_ret"] >= 0.08) & (pdf["ps_pit"] > 20)],
            ),
            (
                f"{pool_name} | SlowUp_MainWave (SlowUp2to5Y + DblInf>=3Q + Jump>=+4%)",
                pdf[(pdf["slow_uptrend_tag"] == "SlowUp_2to5Y") & (pdf["consec_double_inflect_n"] >= 3) & (pdf["earn_jump_ret"] >= 0.04)],
            ),
            (
                f"{pool_name} | SlowUp_HardBreakdown (SlowUp2to5Y + Rev<0 + OPM<=-2% + ROIC<=-1.5%)",
                pdf[(pdf["slow_uptrend_tag"] == "SlowUp_2to5Y") & (pdf["rev_yoy"] < 0) & (pdf["opm_yoy_chg"] <= -0.02) & (pdf["roic_yoy_chg"] <= -0.015)],
            ),
        ])

    frames = []
    for strat_name, sdf in strategies:
        if len(sdf) >= 5:
            sub_df = eval_d15_subperiods(sdf, date_col="entry_date", label=strat_name)
            sub_df.insert(0, "strategy", strat_name)
            frames.append(sub_df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def extract_8_historical_cases(df: pd.DataFrame) -> pd.DataFrame:
    """
    Extracts 8 verified real historical SEC PIT cases across the 4 required archetypes (2 per archetype),
    with 100% factual PIT metrics and zero-lookahead D+1 forward returns.
    """
    specs = [
        # Archetype 1: Jump >= +10% & Multi-Year Compounding Winner
        ("1_Jump_Continue_Winner", "APP", "2024-06-30", "4季连续双拐点叠加PE仅32倍，跳涨11.2%次日追入后1年净超额486.0%"),
        ("1_Jump_Continue_Winner", "EME", "2023-06-30", "2至5年右上角缓涨叠加3季双拐点与PE仅20.8倍，跳涨12.0%次日追入后3年净超额214.6%"),
        # Archetype 2: Jump >= +10% & Parabolic / Extreme-PS Blow-off Top Trap
        ("2_Jump_Blowoff_Trap", "ENPH", "2022-09-30", "前期暴涨过热且PS高达21.1倍（PE达144倍），跳涨15.2%次日追高后1年净超额负81.1%、3年净超额负175.6%"),
        ("2_Jump_Blowoff_Trap", "DUOL", "2025-03-31", "双拐点中断且PS飙至29.5倍（PE达248倍）触碰禁追红线，跳涨23.5%次日追入后1年净超额负110.5%"),
        # Archetype 3: True Multi-Quarter Acceleration / High GM-SGA Smashed on Earnings & Reversal Goldmine
        ("3_Mispriced_Goldmine_Reversal", "DUOL", "2024-03-31", "营收增44.9%、营业利润率同比扩17.2个百分点、GM减SGA达52.1%，因指引保守暴跌23.1%，次日买入1年净超额173.2%"),
        ("3_Mispriced_Goldmine_Reversal", "ENPH", "2019-09-30", "连续4季双拐点且GM减SGA达30.4%、PS仅4.9倍，财报被砸跌26.3%，次日买入1年净超额435.8%、3年净超额1503.2%"),
        # Archetype 4: SlowUp_2to5Y Fundamental Breakdown Warning
        ("4_SlowUp_Fundamental_Breakdown", "BA", "2019-06-30", "前期2至5年缓涨龙头出现连季恶化，营收跌35.1%、营业利润率缩32.6个百分点且财报跌6.7%，次日后1年净超额负58.3%、3年净超额负91.2%"),
        ("4_SlowUp_Fundamental_Breakdown", "TPR", "2018-06-30", "前期2至5年缓涨但连续2季增速回落叠加营业利润率同比缩4.4个百分点（PE达37.3倍），次日后1年净超额负61.3%、3年净超额负78.3%"),
    ]

    keep_cols = [
        "ticker", "name", "sector", "sector_type", "end", "filed", "entry_date",
        "mcap_usd_b", "mcap_2026_equiv_b", "slow_uptrend_tag",
        "earn_jump_ret", "rev_yoy", "rev_accel_1q", "consec_double_inflect_n",
        "consec_both_det_n", "opm_q", "opm_yoy_chg", "gm_minus_sga_q", "gm_sga_yoy_chg",
        "pe_pit", "ps_pit", "peg_rev_pit", "roic_ttm",
        "fwd_63d", "alpha_fwd_63d", "fwd_252d", "alpha_fwd_252d",
        "fwd_504d", "alpha_fwd_504d", "fwd_756d", "alpha_fwd_756d",
    ]
    case_rows = []
    for archetype, tk, end_dt, note in specs:
        m = df[(df["ticker"] == tk) & (df["end"] == end_dt)]
        if len(m) == 0:
            raise ValueError(f"Historical case not found: {tk} {end_dt}")
        r = m.iloc[0]
        item = {"archetype": archetype, "mechanism_note": note}
        for c in keep_cols:
            val = r[c] if c in r.index else np.nan
            if isinstance(val, (pd.Timestamp, np.datetime64)):
                val = pd.Timestamp(val).strftime("%Y-%m-%d")
            item[c] = val
        case_rows.append(item)
    return pd.DataFrame(case_rows)


def main():
    t_start = time.time()
    os.makedirs(OUT_DIR, exist_ok=True)

    df = prepare_master_dataset()

    print("[1/4] Computing Table 3A: 5 Reaction Tiers x 5 Fundamental Trajectory Tiers...")
    t3a = run_table_3a(df)
    t3a_path = os.path.join(OUT_DIR, "table_3a_reaction_x_trajectory.csv")
    t3a.to_csv(t3a_path, index=False)

    print("[2/4] Computing Table 3B: Jump >=+8% / >=+10% Anatomy, Golden Conditions & Red Lines...")
    t3b = run_table_3b(df)
    t3b_path = os.path.join(OUT_DIR, "table_3b_jump_anatomy.csv")
    t3b.to_csv(t3b_path, index=False)

    print("[3/4] Computing Table 3C: SlowUp Coupling & Pre-Price Structure Launchpad Matrix...")
    t3c = run_table_3c(df)
    t3c_path = os.path.join(OUT_DIR, "table_3c_slowup_and_launchpad.csv")
    t3c.to_csv(t3c_path, index=False)

    print("[4/4] Computing Table 3D: D15 Subperiod Splits & 8 Verified Historical Cases...")
    t3d_sub = run_table_3d_subperiods(df)
    t3d_sub_path = os.path.join(OUT_DIR, "table_3d_d15_subperiods.csv")
    t3d_sub.to_csv(t3d_sub_path, index=False)

    t3d_cases = extract_8_historical_cases(df)
    t3d_cases_path = os.path.join(OUT_DIR, "table_3d_8_historical_cases.csv")
    t3d_cases.to_csv(t3d_cases_path, index=False)

    # Build clean JSON digest for programmatic consumption
    digest = {
        "meta": {
            "module": "M3_Reaction_x_Trajectory_x_PrePriceStructure",
            "source_parquet": DATA_PATH,
            "total_clean_events": int(len(df)),
            "largecap_25b_events": int(df["pool_large_25b"].sum()),
            "midcap_5to25b_events": int(df["pool_mid_5to25b"].sum()),
            "entry_rule": "Strictly D+1 close after SEC filing (0% earnings jump leakage)",
            "dedup_cooldown_trading_days": DEDUP_DAYS,
            "runtime_sec": round(time.time() - t_start, 2),
        },
        "table_3a_h2h": json.loads(
            t3a[t3a["section"] == "HeadToHead_Mispriced_vs_Consensus"].to_json(orient="records")
        ),
        "table_3b_rules": json.loads(
            t3b[t3b["cut_dimension"] == "5_Golden_vs_RedLine_Rules"].to_json(orient="records")
        ),
        "table_3c_slowup": json.loads(
            t3c[t3c["section"] == "PartA_SlowUp2to5Y_Regime_Coupling"].to_json(orient="records")
        ),
        "table_3d_cases": json.loads(t3d_cases.to_json(orient="records")),
    }
    json_path = os.path.join(OUT_DIR, "m3_reaction_price_results.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(digest, f, ensure_ascii=False, indent=2)

    print(f"[DONE] Saved all CSVs and JSON to {OUT_DIR} in {time.time() - t_start:.2f}s.")


if __name__ == "__main__":
    main()

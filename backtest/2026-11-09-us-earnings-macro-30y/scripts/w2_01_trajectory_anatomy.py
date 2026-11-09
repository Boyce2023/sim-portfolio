#!/usr/bin/env python3
"""
w2_01_trajectory_anatomy.py
Module M1 (W2_01): Single-Quarter vs 3-4 Consecutive-Quarter Earnings Trajectory Decoupling
& False-Inflection Anatomy Engine (2009-2026 SEC XBRL Strictly Point-in-Time Universe).

Strictly read-only on xbrl_master_pit_2009_2026.parquet.
Outputs all CSVs, JSON summary, and Markdown report to results/m1_trajectory/.
"""

import os
import sys
import json
import time
import numpy as np
import pandas as pd

PROJ = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-09-us-earnings-macro-30y"
DATA_PATH = f"{PROJ}/data/xbrl_master_pit_2009_2026.parquet"
OUT_DIR = f"{PROJ}/results/m1_trajectory"

sys.path.insert(0, f"{PROJ}/scripts")
from backtest_stats_lib import (
    eval_slice,
    eval_d15_subperiods,
    deduplicate_cooldown,
    benjamini_hochberg_fdr,
)
from price_feature_lib import PriceEngine


def build_uniform_pit_trajectories(df_raw: pd.DataFrame) -> pd.DataFrame:
    """
    Constructs 100% uniform, zero-lookahead sequential quarterly streak indicators across all shards.
    Ensures every prior quarter used in a streak was strictly filed BEFORE the current filing date
    and spaced by 65..125 calendar days between fiscal period end dates.
    """
    df = df_raw.sort_values(["ticker", "end", "filed"]).reset_index(drop=True).copy()
    # Guard against rare SEC XBRL annual-GP tag leak where gm_q > 1.0 (216 of 66,680 rows)
    bad_gm = df["gm_q"] > 1.0
    if bad_gm.any():
        df.loc[bad_gm, ["gm_q", "gm_minus_sga_q", "gm_yoy_chg", "gm_sga_yoy_chg"]] = np.nan
    n = len(df)

    tks = df["ticker"].values
    end_days = pd.to_datetime(df["end"]).values.astype("datetime64[D]").astype(np.int64)
    filed_days = pd.to_datetime(df["filed"]).values.astype("datetime64[D]").astype(np.int64)

    valid_prev = np.zeros(n, dtype=bool)
    valid_next = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if tks[i] == tks[i - 1]:
            ediff = end_days[i] - end_days[i - 1]
            if 65 <= ediff <= 125 and filed_days[i - 1] < filed_days[i]:
                valid_prev[i] = True
                valid_next[i - 1] = True

    df["valid_prev_q"] = valid_prev
    df["valid_next_q"] = valid_next

    rev_yoy = df["rev_yoy"].values
    rev_acc = df["rev_accel_1q"].values
    opm_chg = df["opm_yoy_chg"].values
    gmsga_chg = df["gm_sga_yoy_chg"].values
    gm_sga_q = df["gm_minus_sga_q"].values
    fcf_m = df["fcf_margin_ttm"].values

    # Compute YoY change in fcf_margin_ttm strictly PIT (~365d prior quarter filed < current filed)
    fcf_m_yoy_chg = np.full(n, np.nan, dtype=np.float64)
    for i in range(4, n):
        if np.isnan(fcf_m[i]):
            continue
        for k in range(i - 1, max(-1, i - 7), -1):
            if tks[k] != tks[i]:
                break
            ediff = end_days[i] - end_days[k]
            if 335 <= ediff <= 395 and filed_days[k] < filed_days[i] and not np.isnan(fcf_m[k]):
                fcf_m_yoy_chg[i] = fcf_m[i] - fcf_m[k]
                break
    df["fcf_margin_yoy_chg_pit"] = fcf_m_yoy_chg

    # Uniform sequential streak counters
    s_rev_acc = np.zeros(n, dtype=np.int32)
    s_opm_exp = np.zeros(n, dtype=np.int32)
    s_gmsga_exp = np.zeros(n, dtype=np.int32)
    s_mgn_exp = np.zeros(n, dtype=np.int32)       # opm_yoy_chg > 0 OR gm_sga_yoy_chg > 0
    s_dbl_inf = np.zeros(n, dtype=np.int32)       # (rev_yoy >= 0.12 OR rev_accel_1q > 0) & (opm_chg > 0 OR gmsga_chg > 0)
    s_dbl_strict = np.zeros(n, dtype=np.int32)    # (rev_yoy >= 0.12 AND rev_accel_1q > 0) & (opm_chg > 0 OR gmsga_chg > 0)
    s_rev15 = np.zeros(n, dtype=np.int32)         # consecutive rev_yoy >= 0.15
    s_rev20 = np.zeros(n, dtype=np.int32)         # consecutive rev_yoy >= 0.20
    s_rev25 = np.zeros(n, dtype=np.int32)         # consecutive rev_yoy >= 0.25
    s_comm_inf = np.zeros(n, dtype=np.int32)      # consecutive (rev_yoy >= 0.20 & gm_minus_sga_q >= 0.10 & gm_sga_yoy_chg > 0)

    # Also store lag1..lag3 of gm_minus_sga_q for historical case trajectory display
    gmsga_lag1 = np.full(n, np.nan, dtype=np.float64)
    gmsga_lag2 = np.full(n, np.nan, dtype=np.float64)
    gmsga_lag3 = np.full(n, np.nan, dtype=np.float64)

    for i in range(n):
        vp = valid_prev[i]
        if vp:
            gmsga_lag1[i] = gm_sga_q[i - 1]
            if valid_prev[i - 1]:
                gmsga_lag2[i] = gm_sga_q[i - 2]
                if valid_prev[i - 2]:
                    gmsga_lag3[i] = gm_sga_q[i - 3]

        if not np.isnan(rev_acc[i]) and rev_acc[i] > 0:
            s_rev_acc[i] = (s_rev_acc[i - 1] + 1) if vp else 1
        if not np.isnan(opm_chg[i]) and opm_chg[i] > 0:
            s_opm_exp[i] = (s_opm_exp[i - 1] + 1) if vp else 1
        if not np.isnan(gmsga_chg[i]) and gmsga_chg[i] > 0:
            s_gmsga_exp[i] = (s_gmsga_exp[i - 1] + 1) if vp else 1

        mgn_ok = (not np.isnan(opm_chg[i]) and opm_chg[i] > 0) or (
            not np.isnan(gmsga_chg[i]) and gmsga_chg[i] > 0
        )
        if mgn_ok:
            s_mgn_exp[i] = (s_mgn_exp[i - 1] + 1) if vp else 1

        rev_ok = (not np.isnan(rev_yoy[i]) and rev_yoy[i] >= 0.12) or (
            not np.isnan(rev_acc[i]) and rev_acc[i] > 0
        )
        if rev_ok and mgn_ok:
            s_dbl_inf[i] = (s_dbl_inf[i - 1] + 1) if vp else 1

        rev_strict_ok = (
            not np.isnan(rev_yoy[i])
            and rev_yoy[i] >= 0.12
            and not np.isnan(rev_acc[i])
            and rev_acc[i] > 0
        )
        if rev_strict_ok and mgn_ok:
            s_dbl_strict[i] = (s_dbl_strict[i - 1] + 1) if vp else 1

        if not np.isnan(rev_yoy[i]) and rev_yoy[i] >= 0.15:
            s_rev15[i] = (s_rev15[i - 1] + 1) if vp else 1
        if not np.isnan(rev_yoy[i]) and rev_yoy[i] >= 0.20:
            s_rev20[i] = (s_rev20[i - 1] + 1) if vp else 1
        if not np.isnan(rev_yoy[i]) and rev_yoy[i] >= 0.25:
            s_rev25[i] = (s_rev25[i - 1] + 1) if vp else 1

        comm_ok = (
            not np.isnan(rev_yoy[i])
            and rev_yoy[i] >= 0.20
            and not np.isnan(gm_sga_q[i])
            and gm_sga_q[i] >= 0.10
            and not np.isnan(gmsga_chg[i])
            and gmsga_chg[i] > 0
        )
        if comm_ok:
            s_comm_inf[i] = (s_comm_inf[i - 1] + 1) if vp else 1

    df["pit_rev_accel_n"] = s_rev_acc
    df["pit_opm_expand_n"] = s_opm_exp
    df["pit_gmsga_expand_n"] = s_gmsga_exp
    df["pit_mgn_expand_n"] = s_mgn_exp
    df["pit_dbl_inflect_n"] = s_dbl_inf
    df["pit_dbl_strict_n"] = s_dbl_strict
    df["pit_rev15_n"] = s_rev15
    df["pit_rev20_n"] = s_rev20
    df["pit_rev25_n"] = s_rev25
    df["pit_comm_inflect_n"] = s_comm_inf
    df["gm_sga_q_lag1"] = gmsga_lag1
    df["gm_sga_q_lag2"] = gmsga_lag2
    df["gm_sga_q_lag3"] = gmsga_lag3

    return df


def run_table_1a(df: pd.DataFrame) -> pd.DataFrame:
    """
    Table 1A: Single-Quarter vs Consecutive 2/3/4+ Quarter Trajectory Return Gradient.
    Evaluated on both mcap_2026_equiv_b >= 10 and >= 25.
    """
    rows = []
    horizons = (63, 126, 252, 504, 756, 1260)

    for univ_name, mcap_min in [("MidLarge_ge10B", 10.0), ("CoreLarge_ge25B", 25.0)]:
        u = df[
            (df["mcap_2026_equiv_b"] >= mcap_min)
            & df["entry_date"].notna()
            & (~df["has_anomaly_break"].fillna(False))
        ].copy()

        mgn_drop = (u["opm_yoy_chg"] < 0) & (u["gm_sga_yoy_chg"].fillna(-1.0) < 0)
        quad_ok = (u["fcf_margin_ttm"] > 0) & (u["dilution_yoy_clean"] <= 0.03)
        quad_fcf_exp = (
            (u["fcf_margin_ttm"] > 0)
            & (u["fcf_margin_yoy_chg_pit"] > 0)
            & (u["dilution_yoy_clean"] <= 0.03)
        )
        non_cyc_non_peak = (u["sector_type"] != "Deep_Cyclical") & (u["opm_5y_pct_pit"] < 0.85)

        slices = [
            # Panel A1: Pure Revenue Acceleration
            ("A1_PureRev", "0_NoAccel_Baseline", u["pit_rev_accel_n"] == 0),
            (
                "A1_PureRev",
                "1_1Q_SuddenSpike_ge8pp_PriorMediocre",
                (u["pit_rev_accel_n"] == 1)
                & (u["rev_accel_1q"] >= 0.08)
                & (u["rev_yoy_lag1"] < 0.10)
                & (u["rev_yoy_lag2"] < 0.10),
            ),
            ("A1_PureRev", "1b_1Q_RevAccel_All", u["pit_rev_accel_n"] == 1),
            ("A1_PureRev", "2_Consec_2Q_RevAccel", u["pit_rev_accel_n"] == 2),
            ("A1_PureRev", "3_Consec_3Q_RevAccel", u["pit_rev_accel_n"] == 3),
            ("A1_PureRev", "4_Consec_4Qplus_RevAccel", u["pit_rev_accel_n"] >= 4),
            # Panel A2: Operating Leverage Overlay (Margin Drop vs Double Inflection)
            (
                "A2_OpLeverage",
                "0a_1Q_RevAccel_MarginDrop",
                (u["pit_rev_accel_n"] == 1) & mgn_drop,
            ),
            (
                "A2_OpLeverage",
                "0b_2Qplus_RevAccel_MarginDrop_NoLeverage",
                (u["pit_rev_accel_n"] >= 2) & mgn_drop,
            ),
            ("A2_OpLeverage", "1_DoubleInflect_1Q", u["pit_dbl_inflect_n"] == 1),
            ("A2_OpLeverage", "2_DoubleInflect_2Q", u["pit_dbl_inflect_n"] == 2),
            ("A2_OpLeverage", "3_DoubleInflect_3Q", u["pit_dbl_inflect_n"] == 3),
            ("A2_OpLeverage", "4_DoubleInflect_4Qplus", u["pit_dbl_inflect_n"] >= 4),
            ("A2_OpLeverage", "3plus_DoubleInflect_3Qplus", u["pit_dbl_inflect_n"] >= 3),
            ("A2_OpLeverage", "3plus_StrictDoubleAccel_3Qplus", u["pit_dbl_strict_n"] >= 3),
            # Panel A3: 4th Puzzle Piece (FCF > 0 + Low Dilution <= 3% + Non-Peak Cycle)
            ("A3_QuadInflect", "1_QuadInflect_1Q_FCFpos_LowDil", (u["pit_dbl_inflect_n"] == 1) & quad_ok),
            ("A3_QuadInflect", "2_QuadInflect_2Q_FCFpos_LowDil", (u["pit_dbl_inflect_n"] == 2) & quad_ok),
            ("A3_QuadInflect", "3_QuadInflect_3Q_FCFpos_LowDil", (u["pit_dbl_inflect_n"] == 3) & quad_ok),
            ("A3_QuadInflect", "4_QuadInflect_4Qplus_FCFpos_LowDil", (u["pit_dbl_inflect_n"] >= 4) & quad_ok),
            ("A3_QuadInflect", "3plus_QuadInflect_3Qplus_FCFpos_LowDil", (u["pit_dbl_inflect_n"] >= 3) & quad_ok),
            (
                "A3_QuadInflect",
                "3plus_QuadInflect_3Qplus_FCFExpand_LowDil",
                (u["pit_dbl_inflect_n"] >= 3) & quad_fcf_exp,
            ),
            (
                "A3_QuadInflect",
                "3plus_QuadInflect_3Qplus_NonCyc_NonPeakOPM",
                (u["pit_dbl_inflect_n"] >= 3) & quad_ok & non_cyc_non_peak,
            ),
            (
                "A3_QuadInflect",
                "Bad_DoubleInflect_2Qplus_NegFCF_or_HighDil",
                (u["pit_dbl_inflect_n"] >= 2)
                & ((u["fcf_margin_ttm"] <= 0) | (u["dilution_yoy_clean"] > 0.03)),
            ),
        ]

        for panel, sname, mask in slices:
            r = eval_slice(u[mask], horizons=horizons, label=f"{univ_name}|{panel}|{sname}")
            r["universe"] = univ_name
            r["panel"] = panel
            r["slice_name"] = sname
            rows.append(r)

    out = pd.DataFrame(rows)
    for h in (252, 756):
        col_p = f"p_val_{h}d"
        if col_p in out.columns:
            out[f"bh_q_val_{h}d"] = benjamini_hochberg_fdr(out[col_p].values)
    return out


def run_table_1b(df: pd.DataFrame) -> pd.DataFrame:
    """
    Table 1B: Head-to-Head Showdown of 4 Classic False-Inflection Traps vs True Inflections.
    Evaluated across MidLarge >=10B, CoreLarge >=25B, plus MidSmall >=2B reference for unprofitable growth.
    """
    rows = []
    horizons = (63, 126, 252, 504, 756, 1260)

    for univ_name, mcap_min in [
        ("MidLarge_ge10B", 10.0),
        ("CoreLarge_ge25B", 25.0),
        ("AllInvestable_ge2B", 2.0),
    ]:
        u = df[
            (df["mcap_2026_equiv_b"] >= mcap_min)
            & df["entry_date"].notna()
            & (~df["has_anomaly_break"].fillna(False))
        ].copy()

        slices = [
            # Baseline naive 1Q EPS/NI surge
            (
                "Baseline",
                "Baseline_1Q_GAAP_NI_Surge_ge25pct",
                (u["ni_yoy"] >= 0.25) & (u["pe_pit"] > 0),
            ),
            # Trap 1: Cost-Cut False Inflection
            (
                "Trap_1",
                "Trap_1_CostCut_OPM2Q_or_NI25_RevLt3pct",
                ((u["pit_opm_expand_n"] >= 2) | (u["ni_yoy"] >= 0.25)) & (u["rev_yoy"] < 0.03),
            ),
            (
                "Trap_1",
                "Trap_1b_CostCut_Strict_OPM2Q_NegRev",
                (u["pit_opm_expand_n"] >= 2) & (u["rev_yoy"] < 0.0),
            ),
            # Trap 2: Cash-Furnace Unprofitable High Growth (Prompt broad OR + Unit-Economics Deteriorating isolation)
            (
                "Trap_2",
                "Trap_2_CashFurnace_PromptBroad_OR",
                (u["pit_rev25_n"] >= 2)
                & (u["pe_pit"] < 0)
                & ((u["gm_minus_sga_q"] < 0) | (u["dilution_yoy_clean"] > 0.05)),
            ),
            (
                "Trap_2",
                "Trap_2b_CashFurnace_NegUE_and_NotImproving",
                (u["pit_rev25_n"] >= 2)
                & (u["pe_pit"] < 0)
                & (u["gm_minus_sga_q"] < 0)
                & (u["gm_sga_yoy_chg"] <= 0),
            ),
            (
                "Trap_2",
                "Trap_2c_CashFurnace_1Q25_DeterioratingUE_HighDil",
                (u["rev_yoy"] >= 0.25)
                & (u["pe_pit"] < 0)
                & ((u["gm_minus_sga_q"] < 0) | (u["dilution_yoy_clean"] > 0.05))
                & (u["gm_sga_yoy_chg"] <= 0),
            ),
            # True 1: NTRA/VRTX Commercialization Inflection (GAAP loss due to R&D, GM-SGA >= +10% & 2Q+ expanding)
            (
                "True_1",
                "True_1_CommercialInflect_GMSGAge10_2QExp",
                (u["pe_pit"] < 0)
                & (u["rev_yoy"] >= 0.20)
                & (u["gm_minus_sga_q"] >= 0.10)
                & (u["pit_gmsga_expand_n"] >= 2),
            ),
            (
                "True_1",
                "True_1b_CommercialInflect_ControlledDil_le5pct",
                (u["pe_pit"] < 0)
                & (u["rev_yoy"] >= 0.20)
                & (u["gm_minus_sga_q"] >= 0.10)
                & (u["pit_gmsga_expand_n"] >= 2)
                & (u["dilution_yoy_clean"] <= 0.05),
            ),
            # Trap 3: Peak-Cycle / Peak-Margin 1Q Profit Surge
            (
                "Trap_3",
                "Trap_3_PeakCycle_1Q_DeepCyc_or_OPMpct85",
                ((u["sector_type"] == "Deep_Cyclical") | (u["opm_5y_pct_pit"] >= 0.85))
                & ((u["opinc_yoy"] >= 0.30) | (u["ni_yoy"] >= 0.30))
                & (u["pit_rev_accel_n"] <= 1),
            ),
            (
                "Trap_3",
                "Trap_3b_PeakOPMpct85_1QSurge_DecelRev",
                (u["opm_5y_pct_pit"] >= 0.85)
                & ((u["opinc_yoy"] >= 0.30) | (u["ni_yoy"] >= 0.30))
                & (u["pit_rev_accel_n"] == 0),
            ),
            # True 2: Non-Cyclical 3Q+ Compounder Inflection (Low Dilution < 3% + Non-Peak Margin < 85%)
            (
                "True_2",
                "True_2_Compounder_3Q_NonCyc_LowDil_NonPeakOPM",
                (u["sector_type"] != "Deep_Cyclical")
                & (u["pit_dbl_inflect_n"] >= 3)
                & (u["dilution_yoy_clean"] < 0.03)
                & (u["opm_5y_pct_pit"] < 0.85),
            ),
            (
                "True_2",
                "True_2b_Compounder_3Q_PosFCF_ExFinCyc_NonPeakOPM",
                (~u["sector_type"].isin(["Deep_Cyclical", "Financial_Utility_RateSens"]))
                & (u["pit_dbl_inflect_n"] >= 3)
                & (u["fcf_margin_ttm"] > 0)
                & (u["dilution_yoy_clean"] < 0.03)
                & (u["opm_5y_pct_pit"] < 0.85),
            ),
            (
                "True_2",
                "True_2c_SecularCompounder_3Q_PosFCF_ExCyc_NoOPMCap",
                (u["sector_type"] != "Deep_Cyclical")
                & (u["pit_dbl_inflect_n"] >= 3)
                & (u["fcf_margin_ttm"] > 0)
                & (u["dilution_yoy_clean"] < 0.03),
            ),
        ]

        for cat, sname, mask in slices:
            r = eval_slice(u[mask], horizons=horizons, label=f"{univ_name}|{sname}")
            r["universe"] = univ_name
            r["category"] = cat
            r["slice_name"] = sname
            rows.append(r)

    out = pd.DataFrame(rows)
    for h in (252, 756):
        col_p = f"p_val_{h}d"
        if col_p in out.columns:
            out[f"bh_q_val_{h}d"] = benjamini_hochberg_fdr(out[col_p].values)
    return out


def run_table_1c(df: pd.DataFrame) -> pd.DataFrame:
    """
    Table 1C: Anatomy of GAAP Turnaround to Profit (turnaround_to_profit_1q == 1).
    """
    rows = []
    horizons = (63, 126, 252, 504, 756, 1260)

    for univ_name, mcap_min in [("MidLarge_ge10B", 10.0), ("CoreLarge_ge25B", 25.0)]:
        u = df[
            (df["mcap_2026_equiv_b"] >= mcap_min)
            & df["entry_date"].notna()
            & (~df["has_anomaly_break"].fillna(False))
        ].copy()
        t = u["turnaround_to_profit_1q"] == 1

        slices = [
            ("C1_RawTurnaround_All", t),
            (
                "C2_TrueTurnaround_3QRev15_PosOCFq",
                t & (u["pit_rev15_n"] >= 3) & (u["ocf"] > 0),
            ),
            (
                "C2b_TrueTurnaround_3QRev15_PosOCFttm_LowDil",
                t & (u["pit_rev15_n"] >= 3) & (u["ocf_ttm"] > 0) & (u["dilution_yoy_clean"] <= 0.03),
            ),
            (
                "C2c_TrueTurnaround_2QRev15_PosOCF_MgnExp",
                t & (u["pit_rev15_n"] >= 2) & (u["ocf_ttm"] > 0) & (u["pit_mgn_expand_n"] >= 2),
            ),
            (
                "C3_FakeTurnaround_RevLt5pct_OR_NegOCFq",
                t & ((u["rev_yoy"] < 0.05) | (u["ocf"] < 0)),
            ),
            (
                "C3b_PureAccountingTurnaround_RevLt5pct_AND_NegOCFq",
                t & (u["rev_yoy"] < 0.05) & (u["ocf"] < 0),
            ),
            (
                "C3c_CyclicalOrPeakTurnaround",
                t & ((u["sector_type"] == "Deep_Cyclical") | (u["opm_5y_pct_pit"] >= 0.85)),
            ),
        ]

        for sname, mask in slices:
            r = eval_slice(u[mask], horizons=horizons, label=f"{univ_name}|{sname}")
            r["universe"] = univ_name
            r["slice_name"] = sname
            rows.append(r)

    return pd.DataFrame(rows)


def run_table_1d_episodes(df: pd.DataFrame, pe: PriceEngine) -> tuple[pd.DataFrame, dict]:
    """
    Table 1D: Episode Tracking — Front-Running at Q1 vs Waiting for Q2 / Q3 / Q4 Confirmation.
    Tracks every complete episode entering Double Inflection (Q1: pit_dbl_inflect_n == 1 from Q0 == 0).
    Computes:
    - Exact fizzle / false-inflection probabilities at Q2, Q3, Q4.
    - Exact missed return & missed net excess vs SPY during the wait window (Q1->Q2, Q1->Q3, Q1->Q4).
    - Post-entry forward 1Y/2Y/3Y returns of Unconditional Q1 vs Confirmed Q2 vs Confirmed Q3 vs Conditional Q1 Rules.
    """
    n = len(df)
    s_dbl = df["pit_dbl_inflect_n"].values
    vp = df["valid_prev_q"].values
    vn = df["valid_next_q"].values
    horizons = (63, 126, 252, 504, 756, 1260)

    rows = []
    funnel_summary = {}

    def calc_wait_cost(idx_start_arr: np.ndarray, step_ahead: int) -> dict:
        if len(idx_start_arr) == 0:
            return {}
        idx_end_arr = idx_start_arr + step_ahead
        ent1 = pd.to_datetime(df.loc[idx_start_arr, "entry_date"]).dt.normalize().values
        ent2 = pd.to_datetime(df.loc[idx_end_arr, "entry_date"]).dt.normalize().values
        px1 = df.loc[idx_start_arr, "entry_adj_close"].values.astype(np.float64)
        px2 = df.loc[idx_end_arr, "entry_adj_close"].values.astype(np.float64)

        stk_r = np.full(len(idx_start_arr), np.nan)
        spy_r = np.full(len(idx_start_arr), np.nan)
        for j in range(len(idx_start_arr)):
            d1 = pd.Timestamp(ent1[j])
            d2 = pd.Timestamp(ent2[j])
            i1 = pe.date_to_idx.get(d1, -1)
            i2 = pe.date_to_idx.get(d2, -1)
            if i1 >= 0 and i2 > i1 and px1[j] > 0 and px2[j] > 0:
                stk_r[j] = px2[j] / px1[j] - 1.0
                spy_r[j] = float(pe.spy_tr[i2] / pe.spy_tr[i1] - 1.0)
        net_a = stk_r - spy_r
        v = ~np.isnan(net_a)
        if v.sum() == 0:
            return {}
        return {
            "n_valid_pairs": int(v.sum()),
            "wait_raw_ret_mean": float(np.mean(stk_r[v])),
            "wait_raw_ret_med": float(np.median(stk_r[v])),
            "wait_spy_ret_mean": float(np.mean(spy_r[v])),
            "wait_missed_alpha_mean": float(np.mean(net_a[v])),
            "wait_missed_alpha_med": float(np.median(net_a[v])),
            "wait_missed_alpha_p25": float(np.percentile(net_a[v], 25)),
            "wait_missed_alpha_p75": float(np.percentile(net_a[v], 75)),
            "pct_wait_beats_or_ties_spy": float(np.mean(net_a[v] <= 0.0)),
            "pct_wait_missed_gt20pct_alpha": float(np.mean(net_a[v] > 0.20)),
        }

    for univ_name, mcap_min in [("MidLarge_ge10B", 10.0), ("CoreLarge_ge25B", 25.0)]:
        # Find all Q1 episode starts with valid sequential Q2 and Q3 observations
        ep_q1 = []
        ep_q1_strict2q_mediocre = []
        for i in range(1, n - 3):
            if s_dbl[i] == 1 and vp[i] and s_dbl[i - 1] == 0:
                if (
                    df.at[i, "mcap_2026_equiv_b"] >= mcap_min
                    and pd.notna(df.at[i, "entry_date"])
                    and not bool(df.at[i, "has_anomaly_break"])
                ):
                    if vn[i] and vn[i + 1]:
                        ep_q1.append(i)
                        if i >= 2 and vp[i - 1] and s_dbl[i - 2] == 0:
                            ep_q1_strict2q_mediocre.append(i)

        ep_q1 = np.array(ep_q1, dtype=np.int64)
        ep_q1_strict = np.array(ep_q1_strict2q_mediocre, dtype=np.int64)

        surv_q2 = s_dbl[ep_q1 + 1] >= 2
        surv_q3 = surv_q2 & (s_dbl[ep_q1 + 2] >= 3)
        surv_q4 = surv_q3 & vn[ep_q1 + 2] & (s_dbl[ep_q1 + 3] >= 4)

        cost_q1_to_q2 = calc_wait_cost(ep_q1[surv_q2], 1)
        cost_q1_to_q3 = calc_wait_cost(ep_q1[surv_q3], 2)
        cost_q1_to_q4 = calc_wait_cost(ep_q1[surv_q4], 3)

        # Also check strict prior-2Q-mediocre episodes
        surv_q2_s = s_dbl[ep_q1_strict + 1] >= 2
        surv_q3_s = surv_q2_s & (s_dbl[ep_q1_strict + 2] >= 3)
        cost_q1_to_q3_strict = calc_wait_cost(ep_q1_strict[surv_q3_s], 2)

        funnel_summary[univ_name] = {
            "n_episodes_q1": int(len(ep_q1)),
            "fizzle_at_q2_rate": float((~surv_q2).mean()),
            "survive_to_q2_rate": float(surv_q2.mean()),
            "fizzle_by_q3_false_inflect_rate": float((~surv_q3).mean()),
            "survive_to_q3_rate": float(surv_q3.mean()),
            "fizzle_by_q4_rate": float((~surv_q4).mean()),
            "survive_to_q4_rate": float(surv_q4.mean()),
            "wait_q1_to_q2_cost": cost_q1_to_q2,
            "wait_q1_to_q3_cost": cost_q1_to_q3,
            "wait_q1_to_q4_cost": cost_q1_to_q4,
            "strict_2q_mediocre_n_episodes": int(len(ep_q1_strict)),
            "strict_2q_mediocre_fizzle_by_q3_rate": float((~surv_q3_s).mean()) if len(ep_q1_strict) else np.nan,
            "strict_2q_mediocre_wait_q1_to_q3_cost": cost_q1_to_q3_strict,
        }

        # Build Q1 DataFrame with forward survival tags
        q1_df = df.loc[ep_q1].copy()
        q1_df["surv_q2"] = surv_q2
        q1_df["surv_q3"] = surv_q3

        q2_confirmed_df = df.loc[ep_q1[surv_q2] + 1].copy()
        q3_confirmed_df = df.loc[ep_q1[surv_q3] + 2].copy()
        q4_confirmed_df = df.loc[ep_q1[surv_q4] + 3].copy()

        # Filtered Q3 Compounder Confirmation (Zero lookahead at Q3 entry!)
        q3_comp_mask = (
            (q3_confirmed_df["sector_type"] != "Deep_Cyclical")
            & (q3_confirmed_df["fcf_margin_ttm"] > 0)
            & (q3_confirmed_df["dilution_yoy_clean"] <= 0.03)
            & (q3_confirmed_df["opm_5y_pct_pit"] < 0.85)
        )
        q3_comp_df = q3_confirmed_df[q3_comp_mask].copy()
        # Wait cost specifically for Q3 compounders
        q3_comp_ep_idx = ep_q1[surv_q3][q3_comp_mask.values]
        cost_q1_to_q3_comp = calc_wait_cost(q3_comp_ep_idx, 2)
        funnel_summary[univ_name]["wait_q1_to_q3_compounder_cost"] = cost_q1_to_q3_comp

        # Sequential Entry Strategies + Q1 Conditional Decision Matrix
        episode_slices = [
            # Part 1: Sequential Entry Timing Comparison (Zero-Lookahead Entry Rules)
            ("Timing_Curve", "T1_Buy_All_Q1_Unconditional", q1_df, float(surv_q3.mean()), 0.0, 0.0),
            (
                "Timing_Curve",
                "T2_Wait_Buy_Confirmed_Q2",
                q2_confirmed_df,
                float((s_dbl[ep_q1[surv_q2] + 2] >= 3).mean()),
                cost_q1_to_q2.get("wait_missed_alpha_mean", np.nan),
                cost_q1_to_q2.get("wait_missed_alpha_med", np.nan),
            ),
            (
                "Timing_Curve",
                "T3_Wait_Buy_Confirmed_Q3_All",
                q3_confirmed_df,
                1.0,
                cost_q1_to_q3.get("wait_missed_alpha_mean", np.nan),
                cost_q1_to_q3.get("wait_missed_alpha_med", np.nan),
            ),
            (
                "Timing_Curve",
                "T3b_Wait_Buy_Confirmed_Q3_QualityCompounder",
                q3_comp_df,
                1.0,
                cost_q1_to_q3_comp.get("wait_missed_alpha_mean", np.nan),
                cost_q1_to_q3_comp.get("wait_missed_alpha_med", np.nan),
            ),
            (
                "Timing_Curve",
                "T4_Wait_Buy_Confirmed_Q4_All",
                q4_confirmed_df,
                1.0,
                cost_q1_to_q4.get("wait_missed_alpha_mean", np.nan),
                cost_q1_to_q4.get("wait_missed_alpha_med", np.nan),
            ),
            # Ex-Post Diagnostic Decomposition of Q1 (explains why unconditional Q1 fails)
            (
                "ExPost_Diagnostic",
                "Diag_Q1_Fizzled_in_Q2_or_Q3_ExPost",
                q1_df[~q1_df["surv_q3"]],
                0.0,
                0.0,
                0.0,
            ),
            (
                "ExPost_Diagnostic",
                "Diag_Q1_Actually_Reached_Q3_ExPost",
                q1_df[q1_df["surv_q3"]],
                1.0,
                0.0,
                0.0,
            ),
        ]

        # Part 2: Zero-Lookahead Q1 Front-Run vs Must-Wait Conditional Filters
        q1_conds = [
            (
                "Q1_FrontRun_Rule",
                "Q1_Gold_Jump5_ROIC12_PEle25_LowDil_NonCyc",
                (q1_df["earn_jump_ret"] >= 0.05)
                & (q1_df["roic_5y_med_pit"] >= 0.12)
                & q1_df["pe_pit"].between(0.1, 25.0)
                & (q1_df["dilution_yoy_clean"] <= 0.03)
                & (q1_df["sector_type"] != "Deep_Cyclical"),
            ),
            (
                "Q1_FrontRun_Rule",
                "Q1_Jump_ge8pct_MarketConfirmed",
                q1_df["earn_jump_ret"] >= 0.08,
            ),
            (
                "Q1_FrontRun_Rule",
                "Q1_Jump_ge5pct_ROIC12_FCFpos_NonCyc",
                (q1_df["earn_jump_ret"] >= 0.05)
                & (q1_df["roic_5y_med_pit"] >= 0.12)
                & (q1_df["fcf_margin_ttm"] > 0)
                & (q1_df["sector_type"] != "Deep_Cyclical"),
            ),
            (
                "Q1_SingleFactor",
                "Q1_CheapOnly_PEle22_NoJump_ValueTrapCheck",
                q1_df["pe_pit"].between(0.1, 22.0)
                & (q1_df["earn_jump_ret"] < 0.05)
                & (q1_df["sector_type"] != "Deep_Cyclical"),
            ),
            (
                "Q1_MustWait_Danger",
                "Q1_Danger_SellTheNews_Drop_le_minus5pct",
                q1_df["earn_jump_ret"] <= -0.05,
            ),
            (
                "Q1_MustWait_Danger",
                "Q1_Danger_Unprofitable_PE_lt_0",
                q1_df["pe_pit"] < 0,
            ),
            (
                "Q1_MustWait_Danger",
                "Q1_Danger_HighPEgt40_or_Dilutiongt3pct",
                (q1_df["pe_pit"] > 40.0) | (q1_df["dilution_yoy_clean"] > 0.03),
            ),
            (
                "Q1_MustWait_Danger",
                "Q1_Danger_PeakOPMge85_or_DeepCyclical",
                (q1_df["opm_5y_pct_pit"] >= 0.85) | (q1_df["sector_type"] == "Deep_Cyclical"),
            ),
        ]

        for grp, sname, sub_df, p_q3, w_mean, w_med in episode_slices:
            r = eval_slice(sub_df, horizons=horizons, label=f"{univ_name}|{sname}")
            r["universe"] = univ_name
            r["group"] = grp
            r["slice_name"] = sname
            r["prob_reach_q3"] = p_q3
            r["false_inflect_rate_before_q3"] = 1.0 - p_q3 if pd.notna(p_q3) else np.nan
            r["missed_alpha_before_entry_mean"] = w_mean
            r["missed_alpha_before_entry_med"] = w_med
            rows.append(r)

        for grp, sname, mask in q1_conds:
            sub_df = q1_df[mask]
            p_q3 = float(sub_df["surv_q3"].mean()) if len(sub_df) > 0 else np.nan
            r = eval_slice(sub_df, horizons=horizons, label=f"{univ_name}|{sname}")
            r["universe"] = univ_name
            r["group"] = grp
            r["slice_name"] = sname
            r["prob_reach_q3"] = p_q3
            r["false_inflect_rate_before_q3"] = 1.0 - p_q3 if pd.notna(p_q3) else np.nan
            r["missed_alpha_before_entry_mean"] = 0.0
            r["missed_alpha_before_entry_med"] = 0.0
            rows.append(r)

    return pd.DataFrame(rows), funnel_summary


def run_table_1e_d15(df: pd.DataFrame) -> pd.DataFrame:
    """
    Table 1E: Mandatory D15 Multi-Subperiod Stability Verification across Key Trajectory Slices & Traps.
    """
    all_sub = []
    for univ_name, mcap_min in [("MidLarge_ge10B", 10.0), ("CoreLarge_ge25B", 25.0)]:
        u = df[
            (df["mcap_2026_equiv_b"] >= mcap_min)
            & df["entry_date"].notna()
            & (~df["has_anomaly_break"].fillna(False))
        ].copy()

        key_strategies = [
            ("PureRev_3Qplus_Accel", u["pit_rev_accel_n"] >= 3),
            (
                "RevAccel2Qplus_MarginDrop",
                (u["pit_rev_accel_n"] >= 2)
                & (u["opm_yoy_chg"] < 0)
                & (u["gm_sga_yoy_chg"].fillna(-1.0) < 0),
            ),
            ("DoubleInflect_1Q", u["pit_dbl_inflect_n"] == 1),
            ("DoubleInflect_3Qplus", u["pit_dbl_inflect_n"] >= 3),
            (
                "QuadInflect_3Qplus_FCFpos_LowDil",
                (u["pit_dbl_inflect_n"] >= 3)
                & (u["fcf_margin_ttm"] > 0)
                & (u["dilution_yoy_clean"] <= 0.03),
            ),
            (
                "Trap_1_CostCut",
                ((u["pit_opm_expand_n"] >= 2) | (u["ni_yoy"] >= 0.25)) & (u["rev_yoy"] < 0.03),
            ),
            (
                "Trap_2_CashFurnace_PromptOR",
                (u["pit_rev25_n"] >= 2)
                & (u["pe_pit"] < 0)
                & ((u["gm_minus_sga_q"] < 0) | (u["dilution_yoy_clean"] > 0.05)),
            ),
            (
                "Trap_2b_CashFurnace_NegDeterUE",
                (u["pit_rev25_n"] >= 2)
                & (u["pe_pit"] < 0)
                & (u["gm_minus_sga_q"] < 0)
                & (u["gm_sga_yoy_chg"] <= 0),
            ),
            (
                "True_1b_CommercialInflect_LowDil",
                (u["pe_pit"] < 0)
                & (u["rev_yoy"] >= 0.20)
                & (u["gm_minus_sga_q"] >= 0.10)
                & (u["pit_gmsga_expand_n"] >= 2)
                & (u["dilution_yoy_clean"] <= 0.05),
            ),
            (
                "Trap_3_PeakCycle_1Q",
                ((u["sector_type"] == "Deep_Cyclical") | (u["opm_5y_pct_pit"] >= 0.85))
                & ((u["opinc_yoy"] >= 0.30) | (u["ni_yoy"] >= 0.30))
                & (u["pit_rev_accel_n"] <= 1),
            ),
            (
                "True_2_Compounder_3Q_NonCyc_NonPeak",
                (u["sector_type"] != "Deep_Cyclical")
                & (u["pit_dbl_inflect_n"] >= 3)
                & (u["dilution_yoy_clean"] < 0.03)
                & (u["opm_5y_pct_pit"] < 0.85),
            ),
            (
                "Turnaround_True_3QRev15_PosOCF",
                (u["turnaround_to_profit_1q"] == 1) & (u["pit_rev15_n"] >= 3) & (u["ocf_ttm"] > 0),
            ),
            (
                "Turnaround_Fake_RevLt5_AND_NegOCF",
                (u["turnaround_to_profit_1q"] == 1) & (u["rev_yoy"] < 0.05) & (u["ocf"] < 0),
            ),
            (
                "Q1_FrontRun_Gold",
                (u["pit_dbl_inflect_n"] == 1)
                & (u["earn_jump_ret"] >= 0.05)
                & (u["roic_5y_med_pit"] >= 0.12)
                & u["pe_pit"].between(0.1, 25.0)
                & (u["dilution_yoy_clean"] <= 0.03)
                & (u["sector_type"] != "Deep_Cyclical"),
            ),
        ]

        for sname, mask in key_strategies:
            sub = u[mask]
            if len(sub) >= 5:
                d_res = eval_d15_subperiods(sub, label=f"{univ_name}|{sname}")
                d_res["universe"] = univ_name
                d_res["strategy"] = sname
                all_sub.append(d_res)

    return pd.concat(all_sub, ignore_index=True)


def select_pit_historical_cases(df: pd.DataFrame) -> pd.DataFrame:
    """
    Selects 10 concrete, strictly Point-in-Time historical positive & negative examples
    with complete prior 3-4Q revenue growth & margin trajectories and realized 1Y-3Y forward returns.
    """
    u = df[
        df["entry_date"].notna()
        & (~df["has_anomaly_break"].fillna(False))
        & df["fwd_252d"].notna()
    ].copy()

    def fmt_seq(r, col_base, lag_cols):
        vals = [r.get(c, np.nan) for c in lag_cols] + [r.get(col_base, np.nan)]
        return " -> ".join(["NA" if pd.isna(v) else f"{v*100:+.1f}%" for v in vals])

    def fmt_mgn_seq(r, col_base, lag_cols):
        vals = [r.get(c, np.nan) for c in lag_cols] + [r.get(col_base, np.nan)]
        return " -> ".join(["NA" if pd.isna(v) else f"{v*100:.1f}%" for v in vals])

    # Explicit PIT historical cases verified in xbrl_master_pit_2009_2026.parquet
    pinned_specs = [
        ("Positive_1_Compounder_3Q_DoubleInflect", "ANET", "2021-09-30"),
        ("Positive_2a_True1_CommercialInflect_Biotech", "VRTX", "2016-09-30"),
        ("Positive_2b_True1_CommercialInflect_Diagnostics", "NTRA", "2024-06-30"),
        ("Positive_3_TrueTurnaround_3QRev15_PosOCF", "AMZN", "2014-03-31"),
        ("Positive_4_Q1_FrontRun_Gold_Jump_ROIC_LowPE", "AAPL", "2018-06-30"),
        ("Positive_5_WaitUntilQ3_ConfirmedCompounder", "AVGO", "2021-01-31"),
        ("Negative_1_Trap1_CostCut_MarginUp_RevShrink", "IBM", "2012-09-30"),
        ("Negative_2_Trap2_CashFurnace_NegUE_HighDil", "NTRA", "2021-06-30"),
        ("Negative_3_Trap3_PeakCycle_1QProfitSurge", "MOS", "2022-09-30"),
        ("Negative_4_FakeTurnaround_WeakRev_NegOCF", "UA", "2019-03-31"),
        ("Negative_5_Q1_SingleQuarterSpike_HighPE_Fizzle", "PYPL", "2020-06-30"),
    ]

    candidates = []
    for case_type, tk, f_end in pinned_specs:
        m = u[(u["ticker"] == tk) & (u["end"] == f_end)]
        if len(m) == 0:
            continue
        picked = m.iloc[0]
        candidates.append(
            {
                "case_type": case_type,
                "ticker": picked["ticker"],
                "company_name": picked["name"],
                "sector_type": picked["sector_type"],
                "fiscal_end": picked["end"],
                "filed_date": picked["filed"],
                "entry_date": str(pd.Timestamp(picked["entry_date"]).strftime("%Y-%m-%d")),
                "mcap_pit_usd_b": round(float(picked["mcap_usd_b"]), 2),
                "mcap_2026_equiv_b": round(float(picked["mcap_2026_equiv_b"]), 2),
                "pe_pit": round(float(picked["pe_pit"]), 2) if pd.notna(picked["pe_pit"]) else np.nan,
                "ps_pit": round(float(picked["ps_pit"]), 2) if pd.notna(picked["ps_pit"]) else np.nan,
                "rev_yoy_seq_4q": fmt_seq(
                    picked, "rev_yoy", ["rev_yoy_lag3", "rev_yoy_lag2", "rev_yoy_lag1"]
                ),
                "opm_q_seq_4q": fmt_mgn_seq(
                    picked, "opm_q", ["opm_q_lag3", "opm_q_lag2", "opm_q_lag1"]
                ),
                "gm_minus_sga_seq_4q": fmt_mgn_seq(
                    picked, "gm_minus_sga_q", ["gm_sga_q_lag3", "gm_sga_q_lag2", "gm_sga_q_lag1"]
                ),
                "fcf_margin_ttm": round(float(picked["fcf_margin_ttm"]), 4)
                if pd.notna(picked["fcf_margin_ttm"])
                else np.nan,
                "ocf_q_usd_m": round(float(picked["ocf"]) / 1e6, 1)
                if pd.notna(picked["ocf"])
                else np.nan,
                "dilution_yoy_clean": round(float(picked["dilution_yoy_clean"]), 4)
                if pd.notna(picked["dilution_yoy_clean"])
                else np.nan,
                "opm_5y_pct_pit": round(float(picked["opm_5y_pct_pit"]), 3)
                if pd.notna(picked["opm_5y_pct_pit"])
                else np.nan,
                "earn_jump_ret": round(float(picked["earn_jump_ret"]), 4)
                if pd.notna(picked["earn_jump_ret"])
                else np.nan,
                "fwd_1y_ret": round(float(picked["fwd_252d"]), 4)
                if pd.notna(picked["fwd_252d"])
                else np.nan,
                "fwd_1y_alpha_vs_spy": round(float(picked["alpha_fwd_252d"]), 4)
                if pd.notna(picked["alpha_fwd_252d"])
                else np.nan,
                "fwd_2y_ret": round(float(picked["fwd_504d"]), 4)
                if pd.notna(picked["fwd_504d"])
                else np.nan,
                "fwd_3y_ret": round(float(picked["fwd_756d"]), 4)
                if pd.notna(picked["fwd_756d"])
                else np.nan,
                "fwd_3y_alpha_vs_spy": round(float(picked["alpha_fwd_756d"]), 4)
                if pd.notna(picked["alpha_fwd_756d"])
                else np.nan,
            }
        )

    return pd.DataFrame(candidates)


def main():
    t0 = time.time()
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"[W2_01] Loading strictly PIT master parquet: {DATA_PATH}")
    df_raw = pd.read_parquet(DATA_PATH)
    print(f"Loaded {len(df_raw):,} rows across {df_raw['ticker'].nunique():,} tickers.")

    print("[W2_01] Building uniform zero-lookahead PIT sequential trajectory counters...")
    df = build_uniform_pit_trajectories(df_raw)

    print("[W2_01] Initializing PriceEngine for Episode Q1->Q3 exact SPY-matched wait cost...")
    pe = PriceEngine.get_instance()

    print("[W2_01] Computing Table 1A (1Q vs 2/3/4+Q Trajectory Return Gradient)...")
    t1a = run_table_1a(df)
    t1a.to_csv(f"{OUT_DIR}/table_1a_accel_trajectory_gradient.csv", index=False)

    print("[W2_01] Computing Table 1B (4 False-Inflection Traps vs True Inflections)...")
    t1b = run_table_1b(df)
    t1b.to_csv(f"{OUT_DIR}/table_1b_false_vs_true_inflections.csv", index=False)

    print("[W2_01] Computing Table 1C (GAAP Turnaround Anatomy)...")
    t1c = run_table_1c(df)
    t1c.to_csv(f"{OUT_DIR}/table_1c_gaap_turnaround_anatomy.csv", index=False)

    print("[W2_01] Computing Table 1D (Episode Q1 Front-Run vs Q3 Confirmation Tradeoff)...")
    t1d, funnel_summary = run_table_1d_episodes(df, pe)
    t1d.to_csv(f"{OUT_DIR}/table_1d_episode_q1_vs_q3_tradeoff.csv", index=False)

    print("[W2_01] Computing Table 1E (D15 Multi-Subperiod Stability Matrix)...")
    t1e = run_table_1e_d15(df)
    t1e.to_csv(f"{OUT_DIR}/table_1e_d15_subperiod_stability.csv", index=False)

    print("[W2_01] Extracting 10 Point-in-Time Historical Cases...")
    t1f = select_pit_historical_cases(df)
    t1f.to_csv(f"{OUT_DIR}/table_1f_pit_historical_cases.csv", index=False)

    summary_payload = {
        "module": "W2_01_Trajectory_Anatomy_Engine",
        "input_rows": int(len(df_raw)),
        "input_tickers": int(df_raw["ticker"].nunique()),
        "investable_ge10B_rows": int(
            (
                (df["mcap_2026_equiv_b"] >= 10.0)
                & df["entry_date"].notna()
                & (~df["has_anomaly_break"].fillna(False))
            ).sum()
        ),
        "core_ge25B_rows": int(
            (
                (df["mcap_2026_equiv_b"] >= 25.0)
                & df["entry_date"].notna()
                & (~df["has_anomaly_break"].fillna(False))
            ).sum()
        ),
        "episode_funnel_summary": funnel_summary,
        "table_1a_ge10B": t1a[t1a["universe"] == "MidLarge_ge10B"].to_dict(orient="records"),
        "table_1a_ge25B": t1a[t1a["universe"] == "CoreLarge_ge25B"].to_dict(orient="records"),
        "table_1b_ge10B": t1b[t1b["universe"] == "MidLarge_ge10B"].to_dict(orient="records"),
        "table_1b_ge25B": t1b[t1b["universe"] == "CoreLarge_ge25B"].to_dict(orient="records"),
        "table_1c_ge10B": t1c[t1c["universe"] == "MidLarge_ge10B"].to_dict(orient="records"),
        "table_1c_ge25B": t1c[t1c["universe"] == "CoreLarge_ge25B"].to_dict(orient="records"),
        "table_1d_ge10B": t1d[t1d["universe"] == "MidLarge_ge10B"].to_dict(orient="records"),
        "table_1d_ge25B": t1d[t1d["universe"] == "CoreLarge_ge25B"].to_dict(orient="records"),
        "historical_cases": t1f.to_dict(orient="records"),
        "elapsed_sec": round(time.time() - t0, 2),
    }
    with open(f"{OUT_DIR}/m1_trajectory_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary_payload, f, indent=2, ensure_ascii=False)

    print(f"[W2_01] Completed all 6 tables + JSON in {time.time() - t0:.2f}s -> {OUT_DIR}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
w2_05_macro_conditioning.py
Module 5 (W2_05): Macro Cycle State x Earnings Inflection Trajectory Coupling & Regime-Switching Engine
Covers BOTH:
  1. 2009-2026 Exact PIT XBRL Fundamental Inflection Archetypes (A/B/C/D/E) x 6 PIT Macro Dimensions
     (with explicit Ex-2020-2021 COVID ZIRP quarantine & SP500_PIT zero-survivorship calibration).
  2. 1996-2026 Full 30-Year Price Trajectory / Volume Breakout / Exact SEC Earnings Filings x 8 Historical Eras
     & 6 PIT Macro Dimensions (spanning 1996-2000 DotCom, 2001-2002 TechBust, 2003-2007 Hike Cycle Bull,
     2008-2009 GFC, 2010-2019 LowRate Bull, 2020-2021 COVID ZIRP, 2022-2023 Rate Hike Reset, 2024-2026 HighRate AI).
  3. Actionable Buy-Side Macro Traffic-Light Veto Gates & Overweight Rules (Table 5C).

Strict Compliance:
  - Zero modification to input parquets; zero writes to /tmp.
  - Reuses backtest_stats_lib.py (D15 calendar-quarter equal-weight alpha vs SPY, 250d/180d cooldown dedup,
    BH-FDR q-values, Bailey-Lopez de Prado Sharpe Haircut).
"""

import os
import sys
import glob
import json
import time
import warnings

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

PROJ_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-09-us-earnings-macro-30y"
DATA_DIR = os.path.join(PROJ_DIR, "data")
SCRIPTS_DIR = os.path.join(PROJ_DIR, "scripts")
OUT_DIR = os.path.join(PROJ_DIR, "results", "m5_macro_overlay")

os.makedirs(OUT_DIR, exist_ok=True)
sys.path.insert(0, SCRIPTS_DIR)

from backtest_stats_lib import (
    eval_slice,
    eval_d15_subperiods,
    deduplicate_cooldown,
    benjamini_hochberg_fdr,
    sharpe_haircut_bailey_lopez,
)
from price_feature_lib import PriceEngine


# ---------------------------------------------------------------------------
# Helper: Attach 6 Standardized PIT Macro Dimensions to any DataFrame
# ---------------------------------------------------------------------------
def attach_six_macro_dims(df: pd.DataFrame, date_col_for_covid: str = "entry_date") -> pd.DataFrame:
    out = df.copy()

    # Dim 1: 10Y Treasury Yield Level (<4% vs >=4%) x 6M Yield Direction (dgs10_chg_126d < 0 vs >= 0)
    out["dim1_rate_level_x_dir"] = np.select(
        [
            (out["dgs10"] < 4.0) & (out["dgs10_chg_126d"] < 0.0),
            (out["dgs10"] < 4.0) & (out["dgs10_chg_126d"] >= 0.0),
            (out["dgs10"] >= 4.0) & (out["dgs10_chg_126d"] >= 0.0),
            (out["dgs10"] >= 4.0) & (out["dgs10_chg_126d"] < 0.0),
        ],
        [
            "1_LowRate_lt4%_Falling",
            "2_LowRate_lt4%_Rising",
            "3_HighRate_ge4%_Rising",
            "4_HighRate_ge4%_Falling",
        ],
        default="Unknown",
    )

    # Also keep strict +35bp hike shock slice for diagnostic precision
    out["dim1b_strict_rate_shock"] = np.select(
        [
            (out["dgs10"] >= 4.0) & (out["rate_dir_6m"] == "Rising_35bp+"),
            (out["dgs10"] >= 4.0) & (out["rate_dir_6m"] != "Rising_35bp+"),
            (out["dgs10"] < 4.0) & (out["rate_dir_6m"] == "Rising_35bp+"),
            (out["dgs10"] < 4.0) & (out["rate_dir_6m"] == "Falling_35bp+"),
        ],
        [
            "HighRate_ge4%_Rising35bp+",
            "HighRate_ge4%_StableOrFalling",
            "LowRate_lt4%_Rising35bp+",
            "LowRate_lt4%_Falling35bp+",
        ],
        default="LowRate_lt4%_Stable",
    )

    # Dim 2: 10Y Real Rate PIT (TIPS / CPI-adjusted): <0% vs 0%-1.5% vs >=1.5%
    out["dim2_real_rate_pit"] = np.select(
        [
            out["real_rate_10y_pit"] < 0.0,
            (out["real_rate_10y_pit"] >= 0.0) & (out["real_rate_10y_pit"] < 1.5),
            out["real_rate_10y_pit"] >= 1.5,
        ],
        [
            "1_NegRealRate_lt0%_ZIRP_QE",
            "2_ModRealRate_0_to_1.5%",
            "3_HighRealRate_ge1.5%_Discipline",
        ],
        default="Unknown",
    )

    # Dim 3: Yield Curve Cycle (10Y-2Y PIT)
    out["dim3_yc_regime"] = out["yc_regime"].astype(str)

    # Dim 4: Credit Spread Regime (BAA10Y PIT)
    out["dim4_credit_regime"] = np.select(
        [
            out["baa10y"] < 1.8,
            (out["baa10y"] >= 1.8) & (out["baa10y"] < 2.5),
            out["baa10y"] >= 2.5,
        ],
        [
            "1_Benign_lt1.8%",
            "2_Normal_1.8_to_2.5%",
            "3_Stress_Crisis_ge2.5%",
        ],
        default="Unknown",
    )

    # Dim 5: Four Macro Quadrants (Growth x Inflation/Rate/Credit PIT)
    out["dim5_macro_quadrant"] = out["macro_quadrant"].astype(str)

    # Dim 6: Explicit Quarantine of 2020-2021 COVID Zero-Rate Liquidity Flood
    dt_cov = pd.to_datetime(out[date_col_for_covid])
    out["dim6_covid_quarantine"] = np.where(
        (dt_cov >= "2020-03-01") & (dt_cov <= "2021-12-31"),
        "COVID_ZIRP_Flood_2020_2021",
        "Ex_2020_2021_Normal_&_HighRate",
    )
    return out


def build_sp500_pit_Lookup(pe: PriceEngine):
    sp_csv = "/tmp/us_xuangu_20261109/w1_a1/sp500_ticker_start_end.csv"
    sp_hist = pd.read_csv(sp_csv)
    sp_hist["start_date"] = pd.to_datetime(sp_hist["start_date"])
    sp_hist["end_date"] = pd.to_datetime(sp_hist["end_date"]).fillna(pd.Timestamp("2099-12-31"))

    sp_intervals = {}
    for tk, grp in sp_hist.groupby("ticker"):
        sp_intervals[tk] = list(zip(grp["start_date"], grp["end_date"]))

    sp_mat = np.zeros((pe.n_days, pe.n_stocks), dtype=bool)
    for _, row in sp_hist.iterrows():
        c = pe.tk_to_col.get(row["ticker"], -1)
        if c >= 0:
            s_idx = np.searchsorted(pe.dates, np.datetime64(row["start_date"].strftime("%Y-%m-%d")))
            e_idx = np.searchsorted(pe.dates, np.datetime64(row["end_date"].strftime("%Y-%m-%d")), side="right")
            sp_mat[s_idx:e_idx, c] = True

    return sp_intervals, sp_mat


def tag_sp500_pit_series(tickers, dates_series, sp_intervals) -> np.ndarray:
    dts = pd.to_datetime(dates_series)
    res = np.zeros(len(tickers), dtype=bool)
    for i, (tk, dt) in enumerate(zip(tickers, dts)):
        if pd.isna(dt):
            continue
        ivs = sp_intervals.get(tk)
        if ivs:
            for s, e in ivs:
                if s <= dt <= e:
                    res[i] = True
                    break
    return res


def define_five_archetypes(d: pd.DataFrame) -> dict:
    """
    Defines the 5 clean, executable fundamental earnings inflection archetypes (zero lookahead):
      - A: Low-Valuation Value Reversal (0 < PE < 15x + single/multi-quarter rev or margin+NI acceleration)
      - B: GARP Core Compounder Inflection (PE 15-35x + 2-4Q consecutive rev & margin double expansion + ROIC >= 12%)
      - C: High-Growth Quality Leader Acceleration ((PE > 35x or PS 8-20x) + 2-3Q rev YoY >= 25% + GM-SGA >= 15% healthy unit economics)
      - D: Cash-Burn / Extreme-PS Story Acceleration ((PE < 0 & GM-SGA < 5%) or (PS > 20x & weak profitability/unit economics) + 1Q rev accel)
      - D_UnprofPS20_Sub: Explicit sub-audit for Unprofitable PS > 20x single-quarter acceleration (pure bubble gauge)
      - E: Right-Side True Slow Uptrend + Earnings Re-acceleration (SlowUp_2to5Y/6Mto2Y + rev accel > 0 + margin YoY expansion)
    """
    gm_sga_eff = d["gm_minus_sga_q"].fillna(d["opm_q"])
    margin_improving = (d["opm_yoy_chg"] > 0.0) | (d["gm_sga_yoy_chg"] > 0.0)

    mask_A = (
        (d["pe_pit"] > 0.0)
        & (d["pe_pit"] < 15.0)
        & (d["rev_yoy"] > 0.0)
        & ((d["consec_rev_accel_n"] >= 1) | ((d["opm_yoy_chg"] > 0.01) & (d["ni_yoy"] > 0.10)))
    )

    mask_B = (
        (d["pe_pit"] >= 15.0)
        & (d["pe_pit"] <= 35.0)
        & (d["roic_ttm"] >= 0.12)
        & (
            (d["consec_double_inflect_n"] >= 2)
            | ((d["consec_rev_accel_n"] >= 2) & (d["consec_opm_expand_n"] >= 1) & (d["rev_yoy"] > 0.05))
            | ((d["consec_opm_expand_n"] >= 2) & (d["consec_rev_accel_n"] >= 1) & (d["rev_yoy"] > 0.08))
        )
    )

    mask_C = (
        ((d["pe_pit"] > 35.0) | ((d["ps_pit"] >= 8.0) & (d["ps_pit"] <= 20.0)))
        & (d["rev_yoy"] >= 0.25)
        & (d["rev_yoy_lag1"] >= 0.25)
        & ((d["consec_rev_accel_n"] >= 1) | margin_improving)
        & (gm_sga_eff >= 0.15)
        & ((d["pe_pit"] > 0.0) | (d["fcf_margin_ttm"] > 0.05))
    )

    mask_D = (
        (
            (((d["pe_pit"] < 0.0) | (d["ni_ttm"] < 0.0)) & (gm_sga_eff < 0.05))
            | ((d["ps_pit"] > 20.0) & ((d["pe_pit"] < 0.0) | (d["ni_ttm"] < 0.0) | (gm_sga_eff < 0.15)))
        )
        & (d["rev_yoy"] > 0.05)
        & ((d["consec_rev_accel_n"] >= 1) | (d["rev_accel_1q"] > 0.0))
    )

    mask_D_unprof_ps20 = (
        ((d["pe_pit"] < 0.0) | (d["ni_ttm"] < 0.0) | (gm_sga_eff < 0.05))
        & (d["ps_pit"] > 20.0)
        & (d["rev_yoy"] > 0.05)
        & ((d["consec_rev_accel_n"] >= 1) | (d["rev_accel_1q"] > 0.0))
    )

    mask_E = (
        d["slow_uptrend_tag"].isin(["SlowUp_2to5Y", "SlowUp_6Mto2Y"])
        & (d["rev_yoy"] > 0.05)
        & (d["rev_accel_1q"] > 0.0)
        & margin_improving
    )

    return {
        "A_LowPE_Value_Inflect": mask_A,
        "B_GARP_Compounder_2Q": mask_B,
        "C_HighGrowth_Quality_Leader": mask_C,
        "D_CashBurn_or_PS20_Story": mask_D,
        "D_Sub_Unprof_PSgt20_Bubble": mask_D_unprof_ps20,
        "E_SlowUp_Right_Reaccel": mask_E,
    }


def add_fdr_columns(df_res: pd.DataFrame, horizons=(63, 252, 504, 756)) -> pd.DataFrame:
    out = df_res.copy()
    for h in horizons:
        pcol = f"p_val_{h}d"
        qcol = f"fdr_q_val_{h}d"
        if pcol in out.columns:
            out[qcol] = benjamini_hochberg_fdr(out[pcol].values)
    return out


# ---------------------------------------------------------------------------
# PART 1: Table 5A (2009-2026 XBRL Fundamental Archetypes x 6 PIT Macro Dims)
# ---------------------------------------------------------------------------
def run_table_5a(pe: PriceEngine, sp_intervals: dict):
    print("\n[Part 1/3] Running Table 5A: 2009-2026 5 Earnings Archetypes x 6 PIT Macro Dimensions...")
    xbrl_path = os.path.join(DATA_DIR, "xbrl_master_pit_2009_2026.parquet")
    df_raw = pd.read_parquet(xbrl_path)

    df_raw["is_sp500_pit"] = tag_sp500_pit_series(df_raw["ticker"].values, df_raw["entry_date"], sp_intervals)

    # Clean commercial investable filter (100% PIT known at entry_date, removes unit-scaling split bugs & pre-revenue shells)
    investable_mask = (
        df_raw["entry_date"].notna()
        & (~df_raw["has_anomaly_break"].fillna(False))
        & (df_raw["mcap_2026_equiv_b"] >= 0.5)
        & (df_raw["mcap_usd_b"] <= 5500.0)
        & (df_raw["unadj_entry_px"] >= 2.0)
        & (df_raw["rev_ttm"] >= 1e8)
    )
    d = attach_six_macro_dims(df_raw[investable_mask].copy(), date_col_for_covid="entry_date")
    print(f"  Clean commercial XBRL observations: {len(d):,} across {d['ticker'].nunique():,} tickers (SP500_PIT={d['is_sp500_pit'].sum():,})")

    archetypes = define_five_archetypes(d)
    horizons = (63, 252, 504, 756)

    macro_dims = [
        ("0_Baseline", "Full_2009_2026", pd.Series("Full_2009_2026", index=d.index)),
        ("1_RateLevel_x_6MDir", "dim1_rate_level_x_dir", d["dim1_rate_level_x_dir"]),
        ("1B_Strict_RateShock_35bp", "dim1b_strict_rate_shock", d["dim1b_strict_rate_shock"]),
        ("2_RealRate_10Y_PIT", "dim2_real_rate_pit", d["dim2_real_rate_pit"]),
        ("3_YieldCurve_Cycle", "dim3_yc_regime", d["dim3_yc_regime"]),
        ("4_CreditSpread_BAA10Y", "dim4_credit_regime", d["dim4_credit_regime"]),
        ("5_Macro_Quadrant", "dim5_macro_quadrant", d["dim5_macro_quadrant"]),
        ("6_COVID_ZIRP_Quarantine", "dim6_covid_quarantine", d["dim6_covid_quarantine"]),
        ("7_Era_Subperiod_2009_2026", "era_regime", d["era_regime"].astype(str)),
    ]

    rows_all = []
    for dim_label, _, dim_series in macro_dims:
        regimes = sorted([r for r in dim_series.dropna().unique() if r not in ("Unknown", "None", "nan")])
        for reg in regimes:
            reg_mask = dim_series == reg
            for arch_name, arch_mask in archetypes.items():
                sub = d[arch_mask & reg_mask]
                if len(sub) < 5:
                    continue
                st = eval_slice(
                    sub,
                    horizons=horizons,
                    dedup_days=250,
                    date_col="entry_date",
                    label=f"{arch_name} | {dim_label}:{reg}",
                )
                st["universe"] = "Commercial_All_1069"
                st["archetype"] = arch_name
                st["macro_dimension"] = dim_label
                st["macro_regime"] = reg
                rows_all.append(st)

    df_5a = add_fdr_columns(pd.DataFrame(rows_all), horizons=horizons)

    # Also build Zero-Survivorship Calibration Table on SP500_PIT & PIT_LargeMidCap (is_sp500_pit OR mcap_2026_equiv_b >= 8B)
    rows_cal = []
    for univ_name, u_mask in [
        ("SP500_PIT_Strict_ZeroSurvivorship", d["is_sp500_pit"]),
        ("PIT_LargeMidCap_or_SP500_ge8B", d["is_sp500_pit"] | (d["mcap_2026_equiv_b"] >= 8.0)),
    ]:
        du = d[u_mask]
        for dim_label, _, dim_series in [
            ("0_Baseline", "Full", pd.Series("Full_2009_2026", index=d.index)),
            ("2_RealRate_10Y_PIT", "dim2", d["dim2_real_rate_pit"]),
            ("4_CreditSpread_BAA10Y", "dim4", d["dim4_credit_regime"]),
            ("5_Macro_Quadrant", "dim5", d["dim5_macro_quadrant"]),
            ("6_COVID_ZIRP_Quarantine", "dim6", d["dim6_covid_quarantine"]),
        ]:
            ds_u = dim_series.loc[du.index]
            for reg in sorted([r for r in ds_u.dropna().unique() if r not in ("Unknown", "None", "nan")]):
                for arch_name, arch_mask in archetypes.items():
                    if arch_name == "D_Sub_Unprof_PSgt20_Bubble":
                        continue
                    sub = du[arch_mask.loc[du.index] & (ds_u == reg)]
                    if len(sub) < 5:
                        continue
                    st = eval_slice(
                        sub,
                        horizons=horizons,
                        dedup_days=250,
                        date_col="entry_date",
                        label=f"{univ_name} | {arch_name} | {reg}",
                    )
                    st["universe"] = univ_name
                    st["archetype"] = arch_name
                    st["macro_dimension"] = dim_label
                    st["macro_regime"] = reg
                    rows_cal.append(st)

    df_5a_cal = add_fdr_columns(pd.DataFrame(rows_cal), horizons=horizons)

    p_5a = os.path.join(OUT_DIR, "table_5a_archetypes_x_macro_2009_2026.csv")
    p_5a_cal = os.path.join(OUT_DIR, "table_5a_sp500_pit_calibration.csv")
    df_5a.to_csv(p_5a, index=False)
    df_5a_cal.to_csv(p_5a_cal, index=False)
    print(f"  Saved {p_5a} ({len(df_5a)} rows) and {p_5a_cal} ({len(df_5a_cal)} rows).")
    return d, archetypes, df_5a, df_5a_cal


# ---------------------------------------------------------------------------
# PART 2: Table 5B (1996-2026 Full 30-Year 8 Eras & 6 Macro Dims)
# ---------------------------------------------------------------------------
def build_eom_30y_panel(pe: PriceEngine, sp_mat: np.ndarray, macro: pd.DataFrame) -> pd.DataFrame:
    dates_pd = pd.to_datetime(pe.dates)
    cal_df = pd.DataFrame({"date": dates_pd, "idx": np.arange(pe.n_days)})
    cal_df = cal_df[(cal_df["date"] >= "1996-01-01") & (cal_df["date"] <= "2026-10-31")].copy()
    cal_df["ym"] = cal_df["date"].dt.to_period("M")
    eom_idxs = cal_df.groupby("ym")["idx"].last().values

    P = pe.P_adj
    spy = pe.spy_tr
    chunks = []

    for d_idx in eom_idxs:
        if d_idx + 1 >= pe.n_days:
            continue
        d_ent = d_idx + 1  # Strictly enter next trading day close (zero lookahead)
        valid_c = np.where(
            (~np.isnan(P[d_idx]))
            & (P[d_idx] > 0)
            & (~np.isnan(P[d_ent]))
            & (P[d_ent] > 0)
            & (pe.P_cls[d_idx] >= 3.0)
            & (pe.seg_breaks[d_idx] == 0)
        )[0]
        if len(valid_c) == 0:
            continue

        df_d = pd.DataFrame(
            {
                "ticker": pe.tickers[valid_c],
                "signal_date": dates_pd[d_idx],
                "entry_date": dates_pd[d_ent],
                "is_sp500_pit": sp_mat[d_idx, valid_c],
                "slow_code": pe.slow_tag[d_idx, valid_c],
                "ma50_gt_200": pe.ma50_above_ma200[d_idx, valid_c].astype(bool),
                "pre_ret_21d": pe.pre_ret_21d[d_idx, valid_c],
                "pre_ret_63d": pe.pre_ret_63d[d_idx, valid_c],
                "pre_ret_252d": pe.pre_ret_252d[d_idx, valid_c],
                "dist_52w_high": pe.dist_52w_high[d_idx, valid_c],
                "max_dd_252d": pe.max_dd_252d[d_idx, valid_c],
            }
        )
        p0 = P[d_ent, valid_c]
        l_idx = pe.last_valid_idx[valid_c]
        for h in (63, 252, 504, 756):
            d_t = d_ent + h
            if d_t < pe.n_days:
                pt = P[d_t, valid_c]
                sr = float(spy[d_t] / spy[d_ent] - 1.0)
                r_stk = np.where((~np.isnan(pt)) & (pt > 0), pt / p0 - 1.0, np.nan)
                del_m = (l_idx < d_t) & (l_idx < pe.n_days - 15) & (l_idx >= d_ent)
                if np.any(del_m):
                    vc_del = valid_c[del_m]
                    pl = P[l_idx[del_m], vc_del]
                    t_ret = pe.terminal_rets[vc_del]
                    r_del = np.where((~np.isnan(pl)) & (pl > 0), (pl / p0[del_m]) * (1.0 + t_ret) - 1.0, -1.0)
                    r_stk[del_m] = r_del
                df_d[f"fwd_{h}d"] = r_stk
                df_d[f"alpha_fwd_{h}d"] = r_stk - sr
            else:
                df_d[f"fwd_{h}d"] = np.nan
                df_d[f"alpha_fwd_{h}d"] = np.nan
        chunks.append(df_d)

    panel = pd.concat(chunks, ignore_index=True)
    panel["macro_join_date"] = pd.to_datetime(panel["signal_date"]).dt.normalize()
    macro_cols = [
        "macro_join_date", "dgs10", "dgs10_chg_126d", "rate_dir_6m", "real_rate_10y_pit",
        "yc_regime", "baa10y", "credit_regime", "macro_quadrant", "era_regime", "vix", "sp500_dd_252d"
    ]
    panel = panel.merge(macro[macro_cols], on="macro_join_date", how="left")
    panel = attach_six_macro_dims(panel, date_col_for_covid="entry_date")
    return panel


def build_30y_jump_and_sec_events(pe: PriceEngine, sp_mat: np.ndarray, sp_intervals: dict, macro: pd.DataFrame):
    # 1. Volume-Confirmed Catalyst/Earnings Jumps >= +8% across 1996-2026 (2x 20d avg volume)
    P = pe.P_adj
    VOL = pe.VOL
    ret_1d = P[1:] / P[:-1] - 1.0
    vol_ma20 = pd.DataFrame(VOL).rolling(20, min_periods=10).mean().values[:-1]
    vol_ratio = VOL[1:] / np.where(vol_ma20 > 0, vol_ma20, np.nan)
    start_1996 = np.searchsorted(pe.dates, np.datetime64("1996-01-02"))

    j_idx_m1, j_col = np.where(
        (np.arange(1, pe.n_days)[:, None] >= start_1996)
        & (ret_1d >= 0.08)
        & (ret_1d <= 0.80)
        & (vol_ratio >= 2.0)
        & (pe.P_cls[1:] >= 5.0)
        & (pe.seg_breaks[1:] == 0)
    )
    j_day = j_idx_m1 + 1
    ev_vol = pd.DataFrame(
        {
            "ticker": pe.tickers[j_col],
            "event_date": pd.to_datetime(pe.dates[j_day]),
            "is_sp500_pit": sp_mat[j_day, j_col],
            "jump_1d_raw": ret_1d[j_idx_m1, j_col],
            "vol_ratio": vol_ratio[j_idx_m1, j_col],
        }
    )
    ev_vol = pe.attach_price_features(ev_vol, ticker_col="ticker", date_col="event_date")
    ev_vol["macro_join_date"] = pd.to_datetime(ev_vol["pre_date"]).dt.normalize()
    macro_cols = [
        "macro_join_date", "dgs10", "dgs10_chg_126d", "rate_dir_6m", "real_rate_10y_pit",
        "yc_regime", "baa10y", "credit_regime", "macro_quadrant", "era_regime", "vix", "sp500_dd_252d"
    ]
    ev_vol = ev_vol.merge(macro[macro_cols], on="macro_join_date", how="left")
    ev_vol = attach_six_macro_dims(ev_vol, date_col_for_covid="entry_date")

    # 2. Exact SEC 1996-2026 Quarterly/Annual Earnings Filings (8-K Item 2.02 / 10-Q / 10-K)
    sec_files = sorted(glob.glob("/tmp/us_earn_macro_bt_20261109/pre2009_shards/sec_filings_1995_2026_part*.parquet"))
    sec_q = pd.DataFrame()
    if sec_files:
        sec_all = pd.concat([pd.read_parquet(f) for f in sec_files], ignore_index=True)
        sec_all["filingDate"] = pd.to_datetime(sec_all["filingDate"])
        sec_all = sec_all[(sec_all["filingDate"] >= "1996-01-01") & (sec_all["filingDate"] <= "2026-11-06")].copy()
        sec_all = sec_all.sort_values(["ticker", "filingDate"]).reset_index(drop=True)
        keep_s = np.ones(len(sec_all), dtype=bool)
        tks_s = sec_all["ticker"].values
        dts_s = sec_all["filingDate"].values.astype("datetime64[D]").astype(np.int64)
        for i in range(1, len(sec_all)):
            if tks_s[i] == tks_s[i - 1] and (dts_s[i] - dts_s[i - 1]) < 25:
                keep_s[i] = False
        sec_q = sec_all[keep_s].copy()
        sec_q["is_bmo"] = sec_q["session_timing"].astype(str).str.upper().eq("BMO")
        sec_q = pe.attach_price_features(sec_q, ticker_col="ticker", date_col="filingDate", bmo_flag_col="is_bmo")
        sec_q = sec_q[sec_q["entry_date"].notna() & (~sec_q["has_anomaly_break"].fillna(False))].copy()
        sec_q["is_sp500_pit"] = tag_sp500_pit_series(sec_q["ticker"].values, sec_q["entry_date"], sp_intervals)
        sec_q["macro_join_date"] = pd.to_datetime(sec_q["pre_date"]).dt.normalize()
        sec_q = sec_q.merge(macro[macro_cols], on="macro_join_date", how="left")
        sec_q = attach_six_macro_dims(sec_q, date_col_for_covid="entry_date")

    return ev_vol, sec_q


def run_table_5b(pe: PriceEngine, sp_mat: np.ndarray, sp_intervals: dict, macro: pd.DataFrame):
    print("\n[Part 2/3] Running Table 5B: 1996-2026 Full 30-Year 8-Era & 6-Macro-Dim Switching Engine...")
    panel = build_eom_30y_panel(pe, sp_mat, macro)
    ev_vol, sec_q = build_30y_jump_and_sec_events(pe, sp_mat, sp_intervals, macro)

    # Focus primary Table 5B on SP500_PIT (strict zero-survivorship across 1996-2026!), plus Full Universe comparison
    panel_sp = panel[panel["is_sp500_pit"]].copy()
    ev_sp = ev_vol[ev_vol["is_sp500_pit"]].copy()
    sec_sp = sec_q[sec_q["is_sp500_pit"]].copy() if len(sec_q) > 0 else pd.DataFrame()

    eras_8 = [
        "1996_2000_DotCom",
        "2001_2002_TechBust",
        "2003_2007_CycleBull",
        "2008_2009_GFC",
        "2010_2019_LowRateBull",
        "2020_2021_ZeroRateCovid",
        "2022_2023_RateHikeReset",
        "2024_2026_HighRateAI",
    ]

    # Define 30Y trajectory & jump strategies on SP500_PIT
    def get_panel_strategies(p_df):
        return {
            "P0_SP500_EqualWeight_Baseline": pd.Series(True, index=p_df.index),
            "P1_SlowUp_Right_Accel": p_df["slow_code"].isin([1, 2]) & p_df["ma50_gt_200"] & (p_df["pre_ret_63d"] > 0.05),
            "P2_TightBase_NearHigh_Breakout": (p_df["slow_code"] == 3) & (p_df["dist_52w_high"] >= -0.08) & (p_df["pre_ret_21d"] > 0.02),
            "P3_DeepDrawdown_Left_BottomFish": (p_df["slow_code"] == 5) & (p_df["pre_ret_21d"] > 0.03),
            "P4_HighFlyer_Parabolic_Momentum": (p_df["slow_code"] == 4),
        }

    def get_jump_strategies(j_df):
        return {
            "J1_VolJump8_Right_Breakout": j_df["ma50_above_ma200"] & (j_df["dist_52w_high"] >= -0.15),
            "J2_VolJump8_SlowUp_Reaccel": j_df["slow_uptrend_tag"].isin(["SlowUp_2to5Y", "SlowUp_6Mto2Y"]),
            "J3_VolJump8_Left_DeepDD_Bounce": (j_df["slow_uptrend_tag"] == "DeepDrawdown_Left") | (j_df["dist_52w_high"] <= -0.35),
        }

    def get_sec_strategies(s_df):
        return {
            "S1_SECEarn_RightJump_ge6%": (s_df["earn_jump_ret"] >= 0.06) & s_df["ma50_above_ma200"] & (s_df["dist_52w_high"] >= -0.15),
            "S2_SECEarn_SlowUp_Jump_ge4%": (s_df["earn_jump_ret"] >= 0.04) & s_df["slow_uptrend_tag"].isin(["SlowUp_2to5Y", "SlowUp_6Mto2Y"]),
            "S3_SECEarn_LeftDeepDD_DropDipBuy": (s_df["earn_jump_ret"] <= -0.06) & (s_df["slow_uptrend_tag"] == "DeepDrawdown_Left"),
        }

    horizons = (63, 252, 504, 756)
    rows_era = []

    # Define 8 individual eras + 4 pooled super-regimes!
    era_cuts = [(e, [e]) for e in eras_8] + [
        ("POOL_3_HighRate_CapexBooms_96_00_03_07_24_26", ["1996_2000_DotCom", "2003_2007_CycleBull", "2024_2026_HighRateAI"]),
        ("POOL_2_Great_Bear_Crashes_01_02_08_09", ["2001_2002_TechBust", "2008_2009_GFC"]),
        ("POOL_Full_30Y_1996_2026", eras_8),
        ("POOL_Ex_2020_2021_30Y", [e for e in eras_8 if e != "2020_2021_ZeroRateCovid"]),
    ]

    p_strats = get_panel_strategies(panel_sp)
    j_strats = get_jump_strategies(ev_sp)
    s_strats = get_sec_strategies(sec_sp) if len(sec_sp) > 0 else {}

    for era_label, era_list in era_cuts:
        # Panel trajectories (SP500_PIT)
        pm = panel_sp["era_regime"].isin(era_list)
        for sname, smask in p_strats.items():
            sub = panel_sp[smask & pm]
            if len(sub) < 5:
                continue
            ded_days = 30 if sname == "P0_SP500_EqualWeight_Baseline" else 180
            st = eval_slice(sub, horizons=horizons, dedup_days=ded_days, date_col="entry_date", label=f"{sname} | {era_label}")
            st["universe"] = "SP500_PIT_30Y"
            st["strategy_family"] = "Monthly_Trajectory"
            st["strategy"] = sname
            st["era_slice"] = era_label
            rows_era.append(st)

        # Volume Jump >=8% Events (SP500_PIT)
        jm = ev_sp["era_regime"].isin(era_list)
        for sname, smask in j_strats.items():
            sub = ev_sp[smask & jm]
            if len(sub) < 5:
                continue
            st = eval_slice(sub, horizons=horizons, dedup_days=180, date_col="entry_date", label=f"{sname} | {era_label}")
            st["universe"] = "SP500_PIT_30Y"
            st["strategy_family"] = "Catalyst_VolJump_ge8%"
            st["strategy"] = sname
            st["era_slice"] = era_label
            rows_era.append(st)

        # Exact SEC Earnings Events (SP500_PIT)
        if len(sec_sp) > 0:
            sm = sec_sp["era_regime"].isin(era_list)
            for sname, smask in s_strats.items():
                sub = sec_sp[smask & sm]
                if len(sub) < 5:
                    continue
                st = eval_slice(sub, horizons=horizons, dedup_days=180, date_col="entry_date", label=f"{sname} | {era_label}")
                st["universe"] = "SP500_PIT_30Y"
                st["strategy_family"] = "SEC_Exact_Earnings_1996_2026"
                st["strategy"] = sname
                st["era_slice"] = era_label
                rows_era.append(st)

    df_5b_eras = add_fdr_columns(pd.DataFrame(rows_era), horizons=horizons)

    # Also evaluate 1996-2026 Full 30-Year Strategies across all 6 PIT Macro Dimensions!
    rows_30y_macro = []
    macro_dim_cols = [
        ("1_RateLevel_x_6MDir", "dim1_rate_level_x_dir"),
        ("2_RealRate_10Y_PIT", "dim2_real_rate_pit"),
        ("3_YieldCurve_Cycle", "dim3_yc_regime"),
        ("4_CreditSpread_BAA10Y", "dim4_credit_regime"),
        ("5_Macro_Quadrant", "dim5_macro_quadrant"),
        ("6_COVID_ZIRP_Quarantine", "dim6_covid_quarantine"),
    ]

    for dim_label, col_name in macro_dim_cols:
        for reg in sorted([r for r in panel_sp[col_name].dropna().unique() if r not in ("Unknown", "None", "nan")]):
            for sname, smask in p_strats.items():
                if sname == "P0_SP500_EqualWeight_Baseline":
                    continue
                sub = panel_sp[smask & (panel_sp[col_name] == reg)]
                if len(sub) >= 5:
                    st = eval_slice(sub, horizons=horizons, dedup_days=180, date_col="entry_date", label=f"{sname}|{reg}")
                    st["universe"] = "SP500_PIT_30Y"
                    st["strategy"] = sname
                    st["macro_dimension"] = dim_label
                    st["macro_regime"] = reg
                    rows_30y_macro.append(st)

        for reg in sorted([r for r in ev_sp[col_name].dropna().unique() if r not in ("Unknown", "None", "nan")]):
            for sname, smask in j_strats.items():
                sub = ev_sp[smask & (ev_sp[col_name] == reg)]
                if len(sub) >= 5:
                    st = eval_slice(sub, horizons=horizons, dedup_days=180, date_col="entry_date", label=f"{sname}|{reg}")
                    st["universe"] = "SP500_PIT_30Y"
                    st["strategy"] = sname
                    st["macro_dimension"] = dim_label
                    st["macro_regime"] = reg
                    rows_30y_macro.append(st)

        if len(sec_sp) > 0:
            for reg in sorted([r for r in sec_sp[col_name].dropna().unique() if r not in ("Unknown", "None", "nan")]):
                for sname, smask in s_strats.items():
                    sub = sec_sp[smask & (sec_sp[col_name] == reg)]
                    if len(sub) >= 5:
                        st = eval_slice(sub, horizons=horizons, dedup_days=180, date_col="entry_date", label=f"{sname}|{reg}")
                        st["universe"] = "SP500_PIT_30Y"
                        st["strategy"] = sname
                        st["macro_dimension"] = dim_label
                        st["macro_regime"] = reg
                        rows_30y_macro.append(st)

    df_5b_macro = add_fdr_columns(pd.DataFrame(rows_30y_macro), horizons=horizons)

    # Also compute Selection Alpha over Contemporary Equal-Weight SP500 Baseline in each Era!
    ew_base = df_5b_eras[df_5b_eras["strategy"] == "P0_SP500_EqualWeight_Baseline"].set_index("era_slice")
    for h in horizons:
        col_a = f"qtr_ew_alpha_{h}d"
        if col_a in df_5b_eras.columns:
            base_map = ew_base[col_a].to_dict()
            df_5b_eras[f"alpha_vs_ew_sp500_{h}d"] = df_5b_eras[col_a] - df_5b_eras["era_slice"].map(base_map)

    p_5b_eras = os.path.join(OUT_DIR, "table_5b_30y_eras_1996_2026_trajectories_and_jumps.csv")
    p_5b_macro = os.path.join(OUT_DIR, "table_5b_30y_macro_6dims_1996_2026.csv")
    df_5b_eras.to_csv(p_5b_eras, index=False)
    df_5b_macro.to_csv(p_5b_macro, index=False)
    print(f"  Saved {p_5b_eras} ({len(df_5b_eras)} rows) and {p_5b_macro} ({len(df_5b_macro)} rows).")
    return panel_sp, ev_sp, sec_sp, df_5b_eras, df_5b_macro


# ---------------------------------------------------------------------------
# PART 3: Table 5C (Buy-Side Actionable Macro Traffic-Light Veto & Overweight Rules)
# ---------------------------------------------------------------------------
def run_table_5c(d_xbrl: pd.DataFrame, archetypes: dict, panel_sp: pd.DataFrame, ev_sp: pd.DataFrame):
    print("\n[Part 3/3] Computing Table 5C: Buy-Side Macro Traffic-Light Veto Gates & Overweight Rules...")
    gm_sga_eff = d_xbrl["gm_minus_sga_q"].fillna(d_xbrl["opm_q"])
    horizons = (63, 252, 504, 756)
    rule_rows = []

    def add_rule_pair(rule_id, rule_title, current_2026_signal, green_lbl, green_df, red_lbl, red_df, date_col="entry_date", dedup=250):
        sg = eval_slice(green_df, horizons=horizons, dedup_days=dedup, date_col=date_col, label=green_lbl)
        sr = eval_slice(red_df, horizons=horizons, dedup_days=dedup, date_col=date_col, label=red_lbl)
        for side, st in [("GREEN_OVERWEIGHT", sg), ("RED_VETO_AVOID", sr)]:
            st["rule_id"] = rule_id
            st["rule_title"] = rule_title
            st["traffic_light"] = side
            st["status_on_2026_11_06"] = current_2026_signal
            rule_rows.append(st)

    # Rule 1: Low-PE (<15x) Value Inflection — Credit Washout Early-Cycle Green vs Curve-Uninverting / HighRealRate Trap Red
    mask_A = archetypes["A_LowPE_Value_Inflect"]
    r1_green = d_xbrl[mask_A & ((d_xbrl["baa10y"] >= 2.5) | ((d_xbrl["dgs10"] < 4.0) & (d_xbrl["real_rate_10y_pit"] < 0.0)))]
    r1_red = d_xbrl[
        mask_A
        & (
            (d_xbrl["yc_regime"] == "Bear_or_Bull_Uninverting")
            | (d_xbrl["is_sp500_pit"] & (d_xbrl["real_rate_10y_pit"] >= 1.5) & (d_xbrl["baa10y"] < 2.0))
        )
    ]
    add_rule_pair(
        "Rule_1_LowPE_Cycle_Gate",
        "低PE(<15x)反转周期门：仅在信用利差出清(BAA10Y>=2.5%)或负实际利率救市期做多；在曲线刚解除倒挂窗口或高实际利率+良性利差顶峰期否决大盘低PE陷阱",
        "YELLOW/RED_UNDERWEIGHT (2026-11: RealRate=2.60%>=1.5% & BAA10Y=1.57%<2.0%, 大盘表观低PE跑输SPY)",
        "Green: LowPE<15x in CreditStress(>=2.5%) or NegRealRate",
        r1_green,
        "Red: LowPE<15x in Uninverting Window or SP500 HighRealRate+BenignCredit",
        r1_red,
    )

    # Rule 2: Unprofitable High-PS / Cash-Burn Story — ZIRP QE Launch Only vs High-Rate / Rising-Rate Veto Gate
    m_burn_strict = (
        (((d_xbrl["pe_pit"] < 0.0) | (d_xbrl["ni_ttm"] < 0.0)) & (gm_sga_eff < 0.05) & (d_xbrl["gm_sga_yoy_chg"].fillna(-0.01) <= 0.0))
        | ((d_xbrl["ps_pit"] > 20.0) & ((d_xbrl["pe_pit"] < 0.0) | (gm_sga_eff < 0.10)))
    ) & (d_xbrl["rev_yoy"] > 0.05)
    dt_x = pd.to_datetime(d_xbrl["entry_date"])
    r2_green = d_xbrl[m_burn_strict & (dt_x.dt.year == 2020)]
    r2_red = d_xbrl[
        m_burn_strict
        & (
            (d_xbrl["dgs10_chg_126d"] >= 0.35)
            | (dt_x.dt.year == 2021)
            | (d_xbrl["is_sp500_pit"] & (d_xbrl["real_rate_10y_pit"] >= 1.5))
        )
    ]
    add_rule_pair(
        "Rule_2_CashBurn_PS20_Veto",
        "纯烧钱/未盈利PS>20x一票否决门：仅在零利率QE启动元年(2020)爆发；在6M利率上行>=35bp、零利率泡沫末期(2021)及标普高实际利率期一票否决",
        "HARD_RED_VETO (2026-11: 10Y=4.84%, Rising_35bp+, RealRate=2.60%; 严禁未跨越GM-SGA>=15%奇点的纯烧钱与PS>20x亏损股)",
        "Green: Unprof PS>20x / CashBurn in 2020 QE Launch Impulse",
        r2_green,
        "Red: Unprof PS>20x / CashBurn in 6M Rate Rising>=35bp, 2021 Peak, or SP500 RealRate>=1.5%",
        r2_red,
    )

    # Rule 3: High-Rate Capex Boom (RealRate>=1.5% & Benign Credit <2.0% / Q2 Reflation) — Quality Growth (C) + GARP Inflection (B) Overweight Gate
    cur_capex_macro = (d_xbrl["real_rate_10y_pit"] >= 1.5) & (d_xbrl["baa10y"] < 2.0)
    mask_B = archetypes["B_GARP_Compounder_2Q"]
    mask_C = archetypes["C_HighGrowth_Quality_Leader"]
    r3_green = d_xbrl[(mask_C | (mask_B & (d_xbrl["earn_jump_ret"] >= 0.02))) & cur_capex_macro]
    # Contrast against unconfirmed / non-accelerating slow stocks or low-ROIC high-multiple stocks in same regime
    m_mediocre_highrate = (
        cur_capex_macro
        & (d_xbrl["rev_yoy"] < 0.08)
        & (d_xbrl["rev_accel_1q"] <= 0.0)
        & (d_xbrl["pe_pit"] > 20.0)
    )
    r3_red = d_xbrl[m_mediocre_highrate]
    add_rule_pair(
        "Rule_3_CapexBoom_QualityGrowth_Overweight",
        "高实际利率(>=1.5%)+良性信用(<2.0%)资本开支繁荣门：重仓高成长商业化健康龙头(原型C: 连季营收>=25% & GM-SGA>=15%)与GARP双扩张跳涨确认(原型B)，规避无增速高估值平庸白马",
        "STRONG_GREEN_OVERWEIGHT (2026-11核心主线：精准匹配当下Q2_Reflation_CapexBoom + RealRate 2.60% + BAA10Y 1.57%)",
        "Green: Archetype C or Jump-Confirmed Archetype B in RealRate>=1.5% & BenignCredit<2.0%",
        r3_green,
        "Red: Decelerating Low-Growth (<8%) PE>20x Stocks in RealRate>=1.5% & BenignCredit<2.0%",
        r3_red,
    )

    # Rule 4 (30-Year 1996-2026 Verification): Right-Side Catalyst Jump Continuation vs Left-Side Bottom-Fishing across Capex Bulls vs Bear Crashes
    capex_3_eras = ["1996_2000_DotCom", "2003_2007_CycleBull", "2024_2026_HighRateAI"]
    tight_hike_eras = ["2010_2019_LowRateBull", "2022_2023_RateHikeReset"]
    r4_green = ev_sp[
        ev_sp["era_regime"].isin(capex_3_eras)
        & ev_sp["ma50_above_ma200"]
        & (ev_sp["dist_52w_high"] >= -0.15)
    ]
    r4_red = panel_sp[
        panel_sp["era_regime"].isin(tight_hike_eras)
        & (panel_sp["slow_code"] == 5)
        & (panel_sp["pre_ret_21d"] > 0.03)
    ]
    add_rule_pair(
        "Rule_4_30Y_RightJump_vs_LeftBottomFish",
        "30年(1996-2026)左右侧宏观切换门：在三次高利率资本开支牛市(96-00/03-07/24-26)坚持右侧近新高放量跳涨续涨；在非崩盘常规期与加息重置期严禁左侧深跌抄底",
        "GREEN_RIGHT_BREAKOUT / RED_LEFT_DIPBUY (2026-11处于高利率AI资本开支扩张期且非系统性崩盘，坚持右侧突破跳涨，禁左侧接飞刀)",
        "Green (30Y SP500_PIT): Right-Side Volume Jump>=8% in 3 High-Rate Capex Eras (96-00, 03-07, 24-26)",
        r4_green,
        "Red (30Y SP500_PIT): Left-Side DeepDD Bottom-Fishing in Non-Crash / Rate-Hike Reset Eras",
        r4_red,
        dedup=180,
    )

    df_5c = add_fdr_columns(pd.DataFrame(rule_rows), horizons=horizons)
    p_5c = os.path.join(OUT_DIR, "table_5c_macro_traffic_light_rules.csv")
    df_5c.to_csv(p_5c, index=False)
    print(f"  Saved {p_5c} ({len(df_5c)} rows).")
    return df_5c


def main():
    t0 = time.time()
    print("=" * 85)
    print("W2_05: Macro Cycle State x Earnings Inflection Trajectory Coupling Engine (1996-2026)")
    print("=" * 85)

    macro = pd.read_parquet(os.path.join(DATA_DIR, "macro_pit_daily_1990_2026.parquet"))
    macro["macro_join_date"] = pd.to_datetime(macro["date"]).dt.normalize()
    snap_row = macro[macro["date_str"] == "2026-11-06"].iloc[0]

    pe = PriceEngine.get_instance()
    sp_intervals, sp_mat = build_sp500_pit_Lookup(pe)

    d_xbrl, archetypes, df_5a, df_5a_cal = run_table_5a(pe, sp_intervals)
    panel_sp, ev_sp, sec_sp, df_5b_eras, df_5b_macro = run_table_5b(pe, sp_mat, sp_intervals, macro)
    df_5c = run_table_5c(d_xbrl, archetypes, panel_sp, ev_sp)

    # Multiple-testing Sharpe haircut across all 1Y (252d) archetype x macro slices in Table 5A
    valid_5a_252 = df_5a.dropna(subset=["t_stat_252d", "n_qtrs_252d"]).copy()
    valid_5a_252["ann_sharpe_proxy"] = valid_5a_252["t_stat_252d"] / np.sqrt(np.maximum(valid_5a_252["n_qtrs_252d"] / 4.0, 1.0))
    best_idx = valid_5a_252["ann_sharpe_proxy"].idxmax()
    haircut_audit = sharpe_haircut_bailey_lopez(
        float(valid_5a_252.loc[best_idx, "ann_sharpe_proxy"]),
        valid_5a_252["ann_sharpe_proxy"].values,
    )
    haircut_audit["best_slice_label"] = str(valid_5a_252.loc[best_idx, "label"])

    # Live 2026Q3/Q4 recent triggers in current macro regime (2026-07-01 to 2026-11-06) for Archetypes C & B
    recent_cut = pd.to_datetime(d_xbrl["entry_date"]) >= "2026-07-01"
    live_c = d_xbrl[recent_cut & archetypes["C_HighGrowth_Quality_Leader"]].sort_values("mcap_usd_b", ascending=False)
    live_b = d_xbrl[recent_cut & archetypes["B_GARP_Compounder_2Q"]].sort_values("mcap_usd_b", ascending=False)

    summary_json = {
        "module": "M5_Macro_Cycle_x_Earnings_Inflection_Overlay",
        "generated_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        "runtime_seconds": round(time.time() - t0, 2),
        "current_macro_snapshot_2026_11_06": {
            "date": str(snap_row["date_str"]),
            "dgs10_pct": round(float(snap_row["dgs10"]), 3),
            "rate_level_bin": str(snap_row["rate_level_bin"]),
            "dgs10_chg_126d_pct": round(float(snap_row["dgs10_chg_126d"]), 3),
            "rate_dir_6m": str(snap_row["rate_dir_6m"]),
            "real_rate_10y_pit_pct": round(float(snap_row["real_rate_10y_pit"]), 3),
            "yc_regime": str(snap_row["yc_regime"]),
            "baa10y_pct": round(float(snap_row["baa10y"]), 3),
            "credit_regime": str(snap_row["credit_regime"]),
            "vix": round(float(snap_row["vix"]), 2),
            "vix_regime": str(snap_row["vix_regime"]),
            "indpro_yoy_pit_pct": round(float(snap_row["indpro_yoy_pit"]), 3),
            "indpro_accel_pit_pct": round(float(snap_row["indpro_accel_pit"]), 3),
            "macro_quadrant": str(snap_row["macro_quadrant"]),
            "era_regime": str(snap_row["era_regime"]),
        },
        "dataset_coverage": {
            "xbrl_commercial_pit_2009_2026_rows": int(len(d_xbrl)),
            "xbrl_commercial_tickers": int(d_xbrl["ticker"].nunique()),
            "xbrl_sp500_pit_rows": int(d_xbrl["is_sp500_pit"].sum()),
            "sp500_pit_30y_eom_1996_2026_rows": int(len(panel_sp)),
            "sp500_pit_30y_vol_jump_events": int(len(ev_sp)),
            "sp500_pit_30y_sec_earnings_events": int(len(sec_sp)),
        },
        "multiple_testing_audit": haircut_audit,
        "live_2026_second_half_exemplars": {
            "Archetype_C_HighGrowth_Quality_Leader": live_c[["ticker", "filed", "mcap_usd_b", "pe_pit", "ps_pit", "rev_yoy", "gm_minus_sga_q", "earn_jump_ret"]].head(15).to_dict(orient="records"),
            "Archetype_B_GARP_Compounder_2Q": live_b[["ticker", "filed", "mcap_usd_b", "pe_pit", "roic_ttm", "rev_yoy", "consec_double_inflect_n", "earn_jump_ret"]].head(15).to_dict(orient="records"),
        },
        "output_files": [
            os.path.join(OUT_DIR, "table_5a_archetypes_x_macro_2009_2026.csv"),
            os.path.join(OUT_DIR, "table_5a_sp500_pit_calibration.csv"),
            os.path.join(OUT_DIR, "table_5b_30y_eras_1996_2026_trajectories_and_jumps.csv"),
            os.path.join(OUT_DIR, "table_5b_30y_macro_6dims_1996_2026.csv"),
            os.path.join(OUT_DIR, "table_5c_macro_traffic_light_rules.csv"),
            os.path.join(OUT_DIR, "m5_summary.md"),
        ],
    }

    json_path = os.path.join(OUT_DIR, "m5_macro_overlay_results.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary_json, f, indent=2, ensure_ascii=False)

    print(f"\n[DONE] Saved JSON audit to {json_path} in {time.time() - t0:.2f}s!")


if __name__ == "__main__":
    main()

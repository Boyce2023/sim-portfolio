#!/usr/bin/env python3
"""
g04_exit_rules_backtest.py
G04 Module: Zero-Lookahead Daily & Quarterly Exit Rules, Valuation Take-Profit Caps,
and Mechanical Stop-Loss Whipsaw Anatomy (2009-2026 SEC XBRL PIT + Daily Total Return).

Strict Guarantees:
1. 100% Zero Lookahead:
   - Entry strictly at `entry_date = filed + 1` trading day close.
   - Quarterly fundamental exits evaluate strictly on `filed[k]` (where `filed[k] > filed[k_0]`
     and `end[k] > end[k_0]`) and execute strictly at NEXT trading day close (`idx_filed[k] + 1`).
   - Daily price, MA200, and dynamic valuation (`PS_dyn`, `PE_dyn`) signals evaluate at day `d` close
     (using only filings already effective with `idx_entry[k] <= d`) and execute strictly at NEXT
     trading day close (`d + 1`).
2. Survivorship-Bias Free:
   - Uses `unified_prices_and_bench.parquet` + `PriceEngine` delisting terminal returns (`terminal_rets`)
     spliced at `last_valid_idx`.
3. D15 Backtest Anti-Fraud Compliance:
   - Calendar-quarter equal-weight net excess vs contemporaneous SPY (`qtr_ew_net_alpha`).
   - 10-slot capped daily portfolio rotation CAGR net excess vs SPY (`port_10slot_cagr_alpha`, max 10% per position,
     idle slots parked in SPY, avoiding `Mean(Alpha)/Mean(HoldDays)` Simpson's paradox).
   - Matched 3-Year (756d) SPY-reinvested net excess & annualized excess (`reinv_3y_net_alpha`, `reinv_3y_ann_alpha`)
     to eliminate horizon-length confounding against Fixed 3Y!
   - Mandatory 3-subperiod win rates & payoff ratios: Full (2009-2026), Last 10Y (2016-2026), Recent 3Y (2023-2026)
     plus High-Rate Era (2022-2026).
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
XBRL_PATH = os.path.join(PROJ_DIR, "data/xbrl_master_pit_2009_2026.parquet")
UNIFIED_PX_PATH = "/tmp/us_earn_macro_bt_20261109/unified_prices_and_bench.parquet"
OUT_DIR = os.path.join(PROJ_DIR, "results/granularity_v2/g04_exit_rules")
SCRIPTS_DIR = os.path.join(PROJ_DIR, "scripts")

sys.path.insert(0, SCRIPTS_DIR)
from backtest_stats_lib import deduplicate_cooldown
from price_feature_lib import PriceEngine
from w2_01_trajectory_anatomy import build_uniform_pit_trajectories


def verify_unified_prices_alignment(pe: PriceEngine) -> dict:
    """
    Explicitly reads unified_prices_and_bench.parquet (2009-2026 daily adj_close + spy_adj_close)
    and verifies bit-level alignment with PriceEngine matrices.
    """
    t0 = time.time()
    upx = pd.read_parquet(
        UNIFIED_PX_PATH,
        columns=["ticker", "date", "adj_close", "spy_adj_close"],
    )
    n_rows = len(upx)
    n_tks = upx["ticker"].nunique()
    dt_min = str(upx["date"].min())[:10]
    dt_max = str(upx["date"].max())[:10]

    # Spot-check 500 random rows for exact equality with PriceEngine P_adj & spy_tr
    sample = upx.iloc[::16000].copy()
    diffs_px = []
    diffs_spy = []
    for tk, dt, ac, sc in zip(
        sample["ticker"].values,
        pd.to_datetime(sample["date"]).dt.normalize(),
        sample["adj_close"].values,
        sample["spy_adj_close"].values,
    ):
        col = pe.tk_to_col.get(tk, -1)
        d_i = pe.date_to_idx.get(dt, -1)
        if col >= 0 and d_i >= 0 and pd.notna(ac) and ac > 0:
            pe_ac = float(pe.P_adj[d_i, col])
            pe_sp = float(pe.spy_tr[d_i])
            if pe_ac > 0:
                diffs_px.append(abs(pe_ac / float(ac) - 1.0))
            if pe_sp > 0 and pd.notna(sc) and sc > 0:
                diffs_spy.append(abs(pe_sp / float(sc) - 1.0))

    max_px_rel_err = float(max(diffs_px)) if diffs_px else 0.0
    max_spy_rel_err = float(max(diffs_spy)) if diffs_spy else 0.0
    del upx
    info = {
        "unified_px_rows": int(n_rows),
        "unified_px_tickers": int(n_tks),
        "date_min": dt_min,
        "date_max": dt_max,
        "max_px_rel_err": max_px_rel_err,
        "max_spy_rel_err": max_spy_rel_err,
        "verify_sec": round(time.time() - t0, 2),
    }
    print(f"[Verify Unified Prices] {info}")
    assert max_px_rel_err < 1e-4 and max_spy_rel_err < 1e-4, f"Price mismatch: {info}"
    return info


def build_master_pit_with_streaks(pe: PriceEngine) -> pd.DataFrame:
    """
    Loads xbrl_master_pit_2009_2026.parquet, builds uniform PIT acceleration streaks AND
    strictly PIT post-entry deterioration streaks (`consec_rev_decel_n`, `consec_opm_shrink_n`,
    `consec_neg_gmsga_n`, `consec_rev_drop5_n`).
    """
    t0 = time.time()
    df_raw = pd.read_parquet(XBRL_PATH)
    df = build_uniform_pit_trajectories(df_raw)

    # Sort strictly by ticker, fiscal period end, filing date
    df = df.sort_values(["ticker", "end", "filed"]).reset_index(drop=True)
    n = len(df)

    tks = df["ticker"].values
    end_days = pd.to_datetime(df["end"]).values.astype("datetime64[D]").astype(np.int64)
    filed_days = pd.to_datetime(df["filed"]).values.astype("datetime64[D]").astype(np.int64)

    rev_yoy = df["rev_yoy"].values
    rev_acc = df["rev_accel_1q"].values
    opm_q = df["opm_q"].values
    opm_chg = df["opm_yoy_chg"].values
    gm_chg = df["gm_yoy_chg"].values
    gmsga_q = df["gm_minus_sga_q"].values
    gmsga_chg = df["gm_sga_yoy_chg"].values
    fcf_ttm = df["fcf_ttm"].values

    c_rev_decel = np.zeros(n, dtype=np.int32)
    c_opm_shrink = np.zeros(n, dtype=np.int32)
    c_rev_neg5 = np.zeros(n, dtype=np.int32)
    c_bad_ue = np.zeros(n, dtype=np.int32)
    fcf_turned_neg = np.zeros(n, dtype=bool)

    for i in range(n):
        vp = False
        if i > 0 and tks[i] == tks[i - 1]:
            ediff = end_days[i] - end_days[i - 1]
            if 60 <= ediff <= 135 and filed_days[i - 1] < filed_days[i]:
                vp = True

        is_dec = (not np.isnan(rev_acc[i])) and (rev_acc[i] < 0.0)
        is_opm_dn = (not np.isnan(opm_chg[i])) and (opm_chg[i] < 0.0)
        is_rneg5 = (not np.isnan(rev_yoy[i])) and (rev_yoy[i] < -0.05)
        is_bue = (
            (not np.isnan(gmsga_q[i]))
            and (gmsga_q[i] < 0.0)
            and (not np.isnan(gmsga_chg[i]))
            and (gmsga_chg[i] < 0.0)
        )

        c_rev_decel[i] = (c_rev_decel[i - 1] + 1) if (vp and is_dec) else (1 if is_dec else 0)
        c_opm_shrink[i] = (c_opm_shrink[i - 1] + 1) if (vp and is_opm_dn) else (1 if is_opm_dn else 0)
        c_rev_neg5[i] = (c_rev_neg5[i - 1] + 1) if (vp and is_rneg5) else (1 if is_rneg5 else 0)
        c_bad_ue[i] = (c_bad_ue[i - 1] + 1) if (vp and is_bue) else (1 if is_bue else 0)

        if vp and (not np.isnan(fcf_ttm[i])) and (fcf_ttm[i] < 0.0):
            if (not np.isnan(fcf_ttm[i - 1])) and (fcf_ttm[i - 1] > 0.0):
                fcf_turned_neg[i] = True

    df["consec_rev_decel_n"] = c_rev_decel
    df["consec_opm_shrink_n"] = c_opm_shrink
    df["consec_rev_neg5_n"] = c_rev_neg5
    df["consec_bad_ue_n"] = c_bad_ue
    df["fcf_qoq_turned_neg"] = fcf_turned_neg

    # Canonical M3 fund_tier for Strategy 2 (exact match to w2_03_reaction_price_matrix.py)
    cond_f3 = (
        ((df["ni_ttm"] <= 0) | (df["opinc_ttm"] <= 0))
        & (df["gm_minus_sga_q"] > 0.10)
        & (df["gm_sga_yoy_chg"] > 0)
        & (df["rev_yoy"] >= 0.05)
    )
    cond_f1 = (~cond_f3) & (df["consec_double_inflect_n"] >= 3) & (df["rev_yoy"] >= 0.05)
    df["is_m3_true_accel"] = cond_f1 | cond_f3

    # Attach trading calendar indices (`idx_filed`, `idx_entry`) and stock column index
    stock_cols = np.array([pe.tk_to_col.get(tk, -1) for tk in tks], dtype=np.int32)
    filed_dt_vals = pd.to_datetime(df["filed"]).dt.normalize().values.astype("datetime64[D]")
    idx_filed = np.clip(np.searchsorted(pe.dates, filed_dt_vals), 0, pe.n_days - 1)

    entry_dt_s = pd.to_datetime(df["entry_date"]).dt.normalize()
    idx_entry = np.array(
        [pe.date_to_idx.get(dt, -1) if pd.notna(dt) else -1 for dt in entry_dt_s],
        dtype=np.int32,
    )

    df["stock_col"] = stock_cols
    df["idx_filed"] = idx_filed
    df["idx_entry"] = idx_entry

    print(f"[Master PIT] Prepared {len(df):,} rows across {df['ticker'].nunique():,} tickers in {time.time()-t0:.2f}s.")
    return df


def define_four_strategies(df: pd.DataFrame, pe: PriceEngine) -> dict:
    """
    Constructs the 4 canonical entry strategies with 250d cooldown deduplication.
    Requires at least 252 trading days before the end of the dataset (`idx_entry <= n_days - 253`)
    so every entry has at least a full 1-year live path.
    """
    clean = (
        df["entry_date"].notna()
        & (df["idx_entry"] >= 200)
        & (df["idx_entry"] <= pe.n_days - 253)
        & (df["stock_col"] >= 0)
        & (df["entry_adj_close"] > 0)
        & (~df["has_anomaly_break"].fillna(False))
        & (df["unadj_entry_px"].fillna(0.0) >= 2.0)
    )
    u = df[clean].copy()

    # Strategy 1: 连3季双加速大票 (Large-Cap >= $25B 2026-equiv, 3Q+ Double Inflection, Non-Cyclical, Non-Peak OPM, Low Dilution)
    m_s1 = (
        (u["mcap_2026_equiv_b"] >= 25.0)
        & (u["pit_dbl_inflect_n"] >= 3)
        & (u["sector_type"] != "Deep_Cyclical")
        & (u["opm_5y_pct_pit"].fillna(0.50) < 0.85)
        & (u["dilution_yoy_clean"].fillna(0.0) <= 0.03)
    )

    # Strategy 2: 真加速财报跌>=4%错杀买点 (M3 Mispriced Goldmine: >= $5B 2026-equiv, F1/F3 True Accel, Jump <= -4%)
    m_s2 = (
        (u["mcap_2026_equiv_b"] >= 5.0)
        & u["is_m3_true_accel"]
        & (u["earn_jump_ret"] <= -0.04)
    )

    # Strategy 3: PE<15低估值真拐点 (>= $2B 2026-equiv, 0 < PE < 15, Double Inflection >= 1Q, ROIC >= 12%, Non-Cyclical Non-Peak, Non-Neg Reaction)
    m_s3 = (
        (u["mcap_2026_equiv_b"] >= 2.0)
        & (u["pe_pit"] > 0.0)
        & (u["pe_pit"] < 15.0)
        & (u["pit_dbl_inflect_n"] >= 1)
        & (u["roic_ttm"] >= 0.12)
        & (u["opm_5y_pct_pit"].fillna(0.50) <= 0.75)
        & (u["sector_type"] != "Deep_Cyclical")
        & (u["earn_jump_ret"] >= 0.0)
    )

    # Strategy 4: 毛销差>=10%未盈利突破 (M1 True_1b: >= $2B 2026-equiv, PE < 0, Rev YoY >= 20%, GM-SGA >= 10%, 2Q+ Expanding, Dilution <= 5%)
    m_s4 = (
        (u["mcap_2026_equiv_b"] >= 2.0)
        & (u["pe_pit"] < 0.0)
        & (u["rev_yoy"] >= 0.20)
        & (u["gm_minus_sga_q"] >= 0.10)
        & (u["pit_gmsga_expand_n"] >= 2)
        & (u["dilution_yoy_clean"].fillna(0.0) <= 0.05)
    )

    strats = {
        "S1_LargeCap_3Q_DoubleAccel": (
            "① 连3季双加速大票",
            deduplicate_cooldown(u[m_s1], date_col="entry_date", cooldown_days=250),
        ),
        "S2_TrueAccel_Drop_ge4pct": (
            "② 真加速财报跌>=4%错杀",
            deduplicate_cooldown(u[m_s2], date_col="entry_date", cooldown_days=250),
        ),
        "S3_PElt15_TrueInflect": (
            "③ PE<15低估值真拐点",
            deduplicate_cooldown(u[m_s3], date_col="entry_date", cooldown_days=250),
        ),
        "S4_Unprof_GMSGA_ge10_Breakout": (
            "④ 毛销差>=10%未盈利突破",
            deduplicate_cooldown(u[m_s4], date_col="entry_date", cooldown_days=250),
        ),
    }
    for k, (cn, sub) in strats.items():
        print(f"  Strategy {k} ({cn}): N_dedup = {len(sub)} across {sub['ticker'].nunique()} unique tickers.")
    return strats


def precompute_ma200(P_adj: np.ndarray) -> np.ndarray:
    """
    Computes strictly causal 200-trading-day simple moving average of adjusted close `P_adj` (n_days, n_stocks).
    Handles leading NaNs per column cleanly via cumulative sums.
    """
    t0 = time.time()
    p64 = np.where(np.isnan(P_adj), 0.0, P_adj.astype(np.float64))
    valid = (~np.isnan(P_adj) & (P_adj > 0)).astype(np.int32)

    cs_p = np.vstack([np.zeros((1, p64.shape[1]), dtype=np.float64), np.cumsum(p64, axis=0)])
    cs_v = np.vstack([np.zeros((1, valid.shape[1]), dtype=np.int32), np.cumsum(valid, axis=0)])

    ma200 = np.full(P_adj.shape, np.nan, dtype=np.float32)
    win_sum = cs_p[200:] - cs_p[:-200]
    win_cnt = cs_v[200:] - cs_v[:-200]
    ok = win_cnt == 200
    out_slice = np.full(win_sum.shape, np.nan, dtype=np.float32)
    out_slice[ok] = (win_sum[ok] / 200.0).astype(np.float32)
    ma200[199:] = out_slice
    print(f"[MA200] Precomputed causal 200-day moving average in {time.time()-t0:.2f}s.")
    return ma200


EXIT_RULES = [
    ("R01_Fixed_1Y_252d", "1a. 固定持有1年(252d)"),
    ("R02_Fixed_2Y_504d", "1b. 固定持有2年(504d)"),
    ("R03_Fixed_3Y_756d", "1c. 固定持有3年(756d)"),
    ("R03b_Fixed_5Y_1260d", "1d. 固定持有5年(1260d对照)"),
    ("R04_Fund_1Q_RevDecel", "2. 单季营收减速即卖(次日)"),
    ("R05_Fund_2Q_RevDecel", "3. 连续2季营收减速即卖(次日)"),
    ("R06_Fund_3Q_Decel_OPMBreak", "4. 连3季减速+利润率转负/连降2季"),
    ("R07_Fund_GM200bps_or_FCFNeg", "5. 毛利恶化>=200bps或FCF转负"),
    ("R08_Val_Bubble_PS22_PE48", "6. 估值泡沫止盈(成长PS>22/稳态PE>48)"),
    ("R09a_Val_Repair_PE22", "7a. 估值修复止盈(PE>=22x)"),
    ("R09b_Val_Repair_PE28", "7b. 估值修复止盈(PE>=28x)"),
    ("R09c_Val_Repair_PE35", "7c. 估值修复止盈(PE>=35x)"),
    ("R10_Stop_Hard_m15pct", "8. 机械止损(-15%次日卖)"),
    ("R11_Stop_Trail_m25pct", "9. 最高点回撤止损(-25%次日卖)"),
    ("R12_Trend_MA200_5d_m5pct", "10. 跌破200MA满5日且<-5%"),
    ("R13_Composite_Optimal", "11. 复合慢账守则(证伪硬止损+泡沫止盈)"),
]


def build_ticker_filing_lookup(df: pd.DataFrame) -> dict:
    """
    Pre-packs per-ticker chronologically sorted SEC filings into fast NumPy arrays
    for zero-lookahead quarterly & daily dynamic valuation simulation.
    """
    lookup = {}
    for tk, grp in df.groupby("ticker", sort=False):
        g = grp.sort_values(["filed", "end"]).reset_index(drop=True)
        lookup[tk] = {
            "end_int": pd.to_datetime(g["end"]).values.astype("datetime64[D]").astype(np.int64),
            "filed_int": pd.to_datetime(g["filed"]).values.astype("datetime64[D]").astype(np.int64),
            "idx_filed": g["idx_filed"].values.astype(np.int32),
            "idx_entry": g["idx_entry"].values.astype(np.int32),
            "entry_adj_close": g["entry_adj_close"].values.astype(np.float64),
            "mcap_pit": g["mcap_pit"].values.astype(np.float64),
            "rev_ttm": g["rev_ttm"].values.astype(np.float64),
            "ni_ttm": g["ni_ttm"].values.astype(np.float64),
            "opinc_ttm": g["opinc_ttm"].values.astype(np.float64),
            "fcf_ttm": g["fcf_ttm"].values.astype(np.float64),
            "rev_yoy": g["rev_yoy"].values.astype(np.float64),
            "rev_accel_1q": g["rev_accel_1q"].values.astype(np.float64),
            "opm_q": g["opm_q"].values.astype(np.float64),
            "opm_yoy_chg": g["opm_yoy_chg"].values.astype(np.float64),
            "gm_yoy_chg": g["gm_yoy_chg"].values.astype(np.float64),
            "gm_minus_sga_q": g["gm_minus_sga_q"].values.astype(np.float64),
            "gm_sga_yoy_chg": g["gm_sga_yoy_chg"].values.astype(np.float64),
            "consec_rev_decel_n": g["consec_rev_decel_n"].values.astype(np.int32),
            "consec_opm_shrink_n": g["consec_opm_shrink_n"].values.astype(np.int32),
            "consec_rev_neg5_n": g["consec_rev_neg5_n"].values.astype(np.int32),
            "consec_bad_ue_n": g["consec_bad_ue_n"].values.astype(np.int32),
            "fcf_qoq_turned_neg": g["fcf_qoq_turned_neg"].values.astype(bool),
            "pe_pit": g["pe_pit"].values.astype(np.float64),
            "ps_pit": g["ps_pit"].values.astype(np.float64),
        }
    return lookup


def compute_exact_return_with_delist(
    pe: PriceEngine, col: int, d_start: int, d_end: int
) -> tuple:
    """
    Computes exact stock total return, SPY total return, net excess return, holding days,
    and holding-period max drawdown between `d_start` and `d_end`, properly splicing
    delisting terminal returns if `d_end > last_valid_idx[col]`.
    """
    last_v = int(pe.last_valid_idx[col])
    p0 = float(pe.P_adj[d_start, col])
    spy0 = float(pe.spy_tr[d_start])

    if d_end <= last_v:
        actual_exit = d_end
        p1 = float(pe.P_adj[actual_exit, col])
        if np.isnan(p1) or p1 <= 0:
            # Fallback backward to last valid close before actual_exit
            sub_p = pe.P_adj[d_start : actual_exit + 1, col]
            valid_pos = np.where((~np.isnan(sub_p)) & (sub_p > 0))[0]
            actual_exit = d_start + int(valid_pos[-1])
            p1 = float(pe.P_adj[actual_exit, col])
        r_stk = p1 / p0 - 1.0
        is_delist = False
    else:
        actual_exit = min(last_v, pe.n_days - 1)
        p_last = float(pe.P_adj[actual_exit, col])
        term_r = float(pe.terminal_rets[col])
        if np.isnan(term_r):
            term_r = 0.0
        r_stk = (p_last / p0) * (1.0 + term_r) - 1.0
        is_delist = True

    spy1 = float(pe.spy_tr[actual_exit])
    r_spy = spy1 / spy0 - 1.0
    alpha = r_stk - r_spy
    hold_days = max(1, actual_exit - d_start)

    # Holding-period max drawdown along daily path d_start .. actual_exit
    path_px = pe.P_adj[d_start : actual_exit + 1, col].astype(np.float64)
    valid_px = path_px[(~np.isnan(path_px)) & (path_px > 0)]
    if len(valid_px) >= 2:
        run_max = np.maximum.accumulate(valid_px)
        dds = valid_px / run_max - 1.0
        mdd = float(np.min(dds))
        if is_delist and (1.0 + r_stk) < valid_px[-1] / p0:
            term_eq = p0 * (1.0 + r_stk)
            mdd = min(mdd, float(term_eq / np.max(valid_px) - 1.0))
    else:
        mdd = min(0.0, float(r_stk))

    return actual_exit, hold_days, r_stk, r_spy, alpha, mdd, is_delist


def simulate_single_trade_all_rules(
    row: pd.Series,
    tk_filings: dict,
    pe: PriceEngine,
    ma200: np.ndarray,
    max_dyn_days: int = 756,
) -> dict:
    """
    Simulates all 15 exit rules for a single entry event strictly zero-lookahead.
    Primary dynamic window uses `max_dyn_days = 756` (3Y, 100% horizon-matched to Fixed 3Y
    so comparisons have ZERO horizon-extension bias), while ALSO computing `max_dyn_days = 1260` (5Y)
    let-winners-run excess for Composite & Valuation rules.
    Every triggered exit executes strictly on `d_sig + 1` close!
    """
    tk = row["ticker"]
    col = int(row["stock_col"])
    d0 = int(row["idx_entry"])
    p0 = float(pe.P_adj[d0, col])
    end0_int = int(np.datetime64(str(row["end"])[:10], "D").astype(np.int64))
    filed0_int = int(np.datetime64(str(row["filed"])[:10], "D").astype(np.int64))
    ent_pe = float(row["pe_pit"]) if pd.notna(row["pe_pit"]) else np.nan
    ent_ps = float(row["ps_pit"]) if pd.notna(row["ps_pit"]) else np.nan
    ent_fcf = float(row["fcf_ttm"]) if pd.notna(row["fcf_ttm"]) else np.nan

    last_avail = min(int(pe.last_valid_idx[col]), pe.n_days - 1)
    max_d_3y = min(d0 + max_dyn_days, pe.n_days - 1)
    max_d_5y = min(d0 + 1260, pe.n_days - 1)

    tf = tk_filings[tk]
    n_f = len(tf["filed_int"])

    # Locate current entry filing index k0 (latest filing with filed_int <= filed0_int and end_int <= end0_int)
    cand_k0 = np.where((tf["filed_int"] <= filed0_int) & (tf["end_int"] <= end0_int))[0]
    k0 = int(cand_k0[-1]) if len(cand_k0) > 0 else 0

    # Subsequent strictly PIT filings after entry (`filed_int > filed0_int` AND `end_int > end0_int` AND `idx_filed >= d0`)
    sub_ks = [
        k for k in range(k0 + 1, n_f)
        if tf["filed_int"][k] > filed0_int
        and tf["end_int"][k] > end0_int
        and tf["idx_filed"][k] >= d0
        and tf["idx_filed"][k] + 1 < pe.n_days
    ]

    # -------------------------------------------------------------------------
    # 1. Quarterly Fundamental Exit Signals -> Execute on `idx_filed[k] + 1`
    # -------------------------------------------------------------------------
    sig_r04 = None  # 1Q rev decel
    sig_r05 = None  # 2Q consec rev decel
    sig_r06 = None  # 3Q consec rev decel + (opm_yoy_chg < 0 or 2Q opm shrink or opm_q < 0)
    sig_r07 = None  # GM yoy <= -200bps OR FCF_TTM positive -> negative
    sig_comp_fund = None  # Structural thesis falsification for R13 Composite

    fcf_was_pos = (not np.isnan(ent_fcf)) and (ent_fcf > 0.0)

    for k in sub_ks:
        d_exec_f = int(tf["idx_filed"][k]) + 1  # Strictly next trading day after SEC filing!
        r_acc = tf["rev_accel_1q"][k]
        r_yoy = tf["rev_yoy"][k]
        c_dec = tf["consec_rev_decel_n"][k]
        c_opm = tf["consec_opm_shrink_n"][k]
        opm_q = tf["opm_q"][k]
        opm_c = tf["opm_yoy_chg"][k]
        gm_c = tf["gm_yoy_chg"][k]
        fcf_k = tf["fcf_ttm"][k]
        c_rn5 = tf["consec_rev_neg5_n"][k]
        c_bue = tf["consec_bad_ue_n"][k]

        if sig_r04 is None and (not np.isnan(r_acc)) and (r_acc < 0.0):
            sig_r04 = d_exec_f

        if sig_r05 is None and c_dec >= 2:
            sig_r05 = d_exec_f

        opm_broken = (
            ((not np.isnan(opm_c)) and (opm_c < 0.0))
            or (c_opm >= 2)
            or ((not np.isnan(opm_q)) and (opm_q < 0.0))
        )
        if sig_r06 is None and (c_dec >= 3) and opm_broken:
            sig_r06 = d_exec_f

        gm_bad = (not np.isnan(gm_c)) and (gm_c <= -0.02)
        fcf_bad = (not np.isnan(fcf_k)) and (fcf_k < 0.0) and (fcf_was_pos or bool(tf["fcf_qoq_turned_neg"][k]))
        if sig_r07 is None and (gm_bad or fcf_bad):
            sig_r07 = d_exec_f
        if (not np.isnan(fcf_k)) and (fcf_k > 0.0):
            fcf_was_pos = True

        # Structural Fundamental Falsification (avoids healthy high-base deceleration shakeouts; cuts real decay)
        cond_struct_1 = (
            (c_dec >= 3)
            and (not np.isnan(r_yoy))
            and (r_yoy < 0.02)
            and ((c_opm >= 2) or ((not np.isnan(opm_q)) and (opm_q < 0.0)))
        )
        cond_struct_2 = (
            (c_rn5 >= 2)
            and (not np.isnan(opm_c))
            and (opm_c <= -0.02)
            and (not np.isnan(fcf_k))
            and (fcf_k < 0.0)
        )
        cond_struct_3 = (not np.isnan(ent_pe)) and (ent_pe < 0.0) and (c_bue >= 2)
        if sig_comp_fund is None and (cond_struct_1 or cond_struct_2 or cond_struct_3):
            sig_comp_fund = d_exec_f

    # -------------------------------------------------------------------------
    # 2. Daily Path Simulation (d = d0 + 1 .. min(last_avail, max_d_5y - 1)) -> Execute on `d + 1`
    # -------------------------------------------------------------------------
    sig_r08 = None
    sig_r09a = None
    sig_r09b = None
    sig_r09c = None
    sig_r10 = None
    sig_r11 = None
    sig_r12 = None
    sig_comp_val = None

    peak_px = p0
    ma0 = float(ma200[d0, col])
    reclaimed_ma200 = (not np.isnan(ma0)) and (ma0 > 0) and (p0 >= ma0)
    below_ma200_streak = 0

    # Pointer to latest already-effective filing (`idx_entry[k] <= d`)
    active_k = k0
    sub_ptr = 0
    n_sub = len(sub_ks)

    scan_end = min(last_avail, max_d_5y - 1)
    P_col = pe.P_adj[:, col]
    MA_col = ma200[:, col]

    is_low_pe_entry = (not np.isnan(ent_pe)) and (0.0 < ent_pe < 15.0)
    is_unprof_entry = (not np.isnan(ent_pe)) and (ent_pe < 0.0)

    for d in range(d0 + 1, scan_end + 1):
        px = float(P_col[d])
        if np.isnan(px) or px <= 0.0:
            continue

        # Advance active SEC filing strictly when `idx_entry <= d` (`filed + 1` effective)
        while sub_ptr < n_sub and tf["idx_entry"][sub_ks[sub_ptr]] <= d:
            if tf["mcap_pit"][sub_ks[sub_ptr]] > 0 and tf["entry_adj_close"][sub_ks[sub_ptr]] > 0:
                active_k = sub_ks[sub_ptr]
            sub_ptr += 1

        if px > peak_px:
            peak_px = px
        gain_from_entry = px / p0 - 1.0
        dd_from_peak = px / peak_px - 1.0

        # Rule 8: -15% hard stop from entry price -> sell next day `d + 1`
        if sig_r10 is None and gain_from_entry <= -0.15:
            sig_r10 = d + 1

        # Rule 9: -25% trailing stop from peak -> sell next day `d + 1`
        if sig_r11 is None and dd_from_peak <= -0.25:
            sig_r11 = d + 1

        # Rule 10: Close < MA200 for >= 5 consecutive days AND distance <= -5% -> sell `d + 1`
        ma_d = float(MA_col[d])
        if (not np.isnan(ma_d)) and (ma_d > 0.0):
            if px >= ma_d:
                reclaimed_ma200 = True
                below_ma200_streak = 0
            elif reclaimed_ma200:
                below_ma200_streak += 1
                if sig_r12 is None and below_ma200_streak >= 5 and (px / ma_d - 1.0 <= -0.05):
                    sig_r12 = d + 1

        # Dynamic Split-Proof Valuation Multiples at day `d`
        mc_anchor = tf["mcap_pit"][active_k]
        px_anchor = tf["entry_adj_close"][active_k]
        if mc_anchor > 0.0 and px_anchor > 0.0 and gain_from_entry >= 0.10:
            mcap_d = mc_anchor * (px / px_anchor)
            rev_t = tf["rev_ttm"][active_k]
            ni_t = tf["ni_ttm"][active_k]
            op_t = tf["opinc_ttm"][active_k]
            ry_curr = tf["rev_yoy"][active_k]

            ps_d = (mcap_d / rev_t) if (rev_t > 0.0) else np.nan
            pe_d = (mcap_d / ni_t) if (ni_t > 0.0) else np.nan
            nm_t = (ni_t / rev_t) if (rev_t > 0.0 and not np.isnan(ni_t)) else np.nan
            p_ebit_d = (mcap_d / op_t) if (op_t > 0.0) else np.nan

            # Rule 6 (`R08`): Growth PS > 22x OR Steady PE > 48x
            is_growth_now = is_unprof_entry or ((not np.isnan(ry_curr)) and (ry_curr >= 0.20))
            if sig_r08 is None and gain_from_entry >= 0.15:
                if is_growth_now:
                    ps_cross = np.isnan(ent_ps) or (ent_ps <= 22.0) or (ps_d >= ent_ps * 1.25)
                    if (not np.isnan(ps_d)) and (ps_d > 22.0) and ps_cross:
                        sig_r08 = d + 1
                else:
                    pe_cross = np.isnan(ent_pe) or (ent_pe <= 48.0) or (pe_d >= ent_pe * 1.25)
                    clean_pe48 = (
                        (not np.isnan(pe_d))
                        and (pe_d > 48.0)
                        and (not np.isnan(nm_t))
                        and (nm_t >= 0.06)
                        and (not np.isnan(p_ebit_d))
                        and (p_ebit_d > 32.0)
                        and pe_cross
                    )
                    if clean_pe48:
                        sig_r08 = d + 1

            # Rule 7 (`R09a/b/c`): PE Valuation Repair 22x vs 28x vs 35x
            if (not np.isnan(pe_d)) and (not np.isnan(nm_t)) and (nm_t >= 0.04) and (not np.isnan(p_ebit_d)):
                if (
                    sig_r09a is None
                    and pe_d >= 22.0
                    and p_ebit_d >= 15.0
                    and (np.isnan(ent_pe) or ent_pe < 22.0)
                ):
                    sig_r09a = d + 1
                if (
                    sig_r09b is None
                    and gain_from_entry >= 0.15
                    and pe_d >= 28.0
                    and p_ebit_d >= 19.0
                    and (np.isnan(ent_pe) or ent_pe < 28.0)
                ):
                    sig_r09b = d + 1
                if (
                    sig_r09c is None
                    and gain_from_entry >= 0.20
                    and pe_d >= 35.0
                    and p_ebit_d >= 24.0
                    and (np.isnan(ent_pe) or ent_pe < 35.0)
                ):
                    sig_r09c = d + 1

            # Composite Valuation Bubble Cap (`sig_comp_val`):
            # Physical logic: do not cut an actively accelerating rocket at PS=22.1x while rev_accel_1q > 0 unless
            # multiple hits extreme blow-off (PS > 30x / PE > 60x); once rev_accel_1q <= 0, harvest at PS > 22x / PE > 48x (or PE >= 35x for low-PE entry).
            r_acc_curr = tf["rev_accel_1q"][active_k]
            still_accelerating = (not np.isnan(r_acc_curr)) and (r_acc_curr > 0.0)
            if sig_comp_val is None and gain_from_entry >= 0.25:
                upgraded_growth = (not np.isnan(ry_curr)) and (ry_curr >= 0.25)
                if is_low_pe_entry and (not upgraded_growth):
                    pe_thresh_low = 42.0 if still_accelerating else 35.0
                    if (
                        (not np.isnan(pe_d))
                        and (pe_d >= pe_thresh_low)
                        and (not np.isnan(nm_t))
                        and (nm_t >= 0.04)
                        and (not np.isnan(p_ebit_d))
                        and (p_ebit_d >= 24.0)
                    ):
                        sig_comp_val = d + 1
                elif is_growth_now:
                    ps_thresh = 30.0 if still_accelerating else 22.0
                    ps_cross = np.isnan(ent_ps) or (ent_ps <= ps_thresh) or (ps_d >= ent_ps * 1.30)
                    if (not np.isnan(ps_d)) and (ps_d > ps_thresh) and ps_cross:
                        sig_comp_val = d + 1
                else:
                    pe_thresh = 60.0 if still_accelerating else 48.0
                    pe_cross = np.isnan(ent_pe) or (ent_pe <= pe_thresh) or (pe_d >= ent_pe * 1.30)
                    if (
                        (not np.isnan(pe_d))
                        and (pe_d > pe_thresh)
                        and (not np.isnan(nm_t))
                        and (nm_t >= 0.06)
                        and (not np.isnan(p_ebit_d))
                        and (p_ebit_d > 32.0)
                        and pe_cross
                    ):
                        sig_comp_val = d + 1

    # Composite earliest trigger
    comp_candidates = [x for x in (sig_comp_fund, sig_comp_val) if x is not None]
    sig_r13 = min(comp_candidates) if comp_candidates else None

    raw_signals = {
        "R01_Fixed_1Y_252d": (min(d0 + 252, pe.n_days - 1), False),
        "R02_Fixed_2Y_504d": (min(d0 + 504, pe.n_days - 1), False),
        "R03_Fixed_3Y_756d": (min(d0 + 756, pe.n_days - 1), False),
        "R03b_Fixed_5Y_1260d": (min(d0 + 1260, pe.n_days - 1), False),
        "R04_Fund_1Q_RevDecel": (sig_r04, True),
        "R05_Fund_2Q_RevDecel": (sig_r05, True),
        "R06_Fund_3Q_Decel_OPMBreak": (sig_r06, True),
        "R07_Fund_GM200bps_or_FCFNeg": (sig_r07, True),
        "R08_Val_Bubble_PS22_PE48": (sig_r08, True),
        "R09a_Val_Repair_PE22": (sig_r09a, True),
        "R09b_Val_Repair_PE28": (sig_r09b, True),
        "R09c_Val_Repair_PE35": (sig_r09c, True),
        "R10_Stop_Hard_m15pct": (sig_r10, True),
        "R11_Stop_Trail_m25pct": (sig_r11, True),
        "R12_Trend_MA200_5d_m5pct": (sig_r12, True),
        "R13_Composite_Optimal": (sig_r13, True),
    }

    # Reference 3Y return for exact counterfactual whipsaw comparison
    d_3y_target = min(d0 + 756, pe.n_days - 1)
    act_3y, hd_3y, rstk_3y, rspy_3y, alpha_3y, mdd_3y, _ = compute_exact_return_with_delist(
        pe, col, d0, d_3y_target
    )
    has_full_3y = (d0 + 756) < pe.n_days

    trade_out = {}
    for r_code, (sig_d, is_dyn) in raw_signals.items():
        if not is_dyn:
            d_target = sig_d
            triggered = True
        else:
            if sig_d is not None and sig_d <= max_d_3y:
                d_target = sig_d
                triggered = True
            else:
                d_target = max_d_3y
                triggered = False

        act_exit, hd, r_stk, r_spy, alpha, mdd, is_delist = compute_exact_return_with_delist(
            pe, col, d0, d_target
        )

        # Matched 3Y SPY-parked wealth: hold stock `d0 -> act_exit`, then park proceeds in SPY `act_exit -> act_3y`!
        if act_exit < act_3y:
            spy_rem = float(pe.spy_tr[act_3y] / pe.spy_tr[act_exit])
            wealth_3y_reinv = (1.0 + r_stk) * spy_rem - 1.0
        else:
            wealth_3y_reinv = r_stk
        reinv_3y_alpha = wealth_3y_reinv - rspy_3y

        # Also evaluate 5Y-let-winners-run cap (`max_d_5y`) for dynamic rules
        if is_dyn:
            d_target_5y = sig_d if (sig_d is not None and sig_d <= max_d_5y) else max_d_5y
            act_5y, hd_5y, rstk_5y, rspy_5y, alpha_5y, _, _ = compute_exact_return_with_delist(
                pe, col, d0, d_target_5y
            )
            trig_5y = (sig_d is not None) and (sig_d <= max_d_5y)
        else:
            act_5y, hd_5y, rstk_5y, rspy_5y, alpha_5y, trig_5y = (
                act_exit, hd, r_stk, r_spy, alpha, True
            )

        # Post-exit 1-year (252 trading days AFTER `act_exit`) flyaway calculation!
        # Definition from prompt: 卖出后1年继续跑赢SPY超20%的比例 (`post_alpha_1y > +0.20`)
        if (not is_delist) and (act_exit + 252 < pe.n_days):
            _, _, post_r_stk, post_r_spy, post_alpha_1y, _, _ = compute_exact_return_with_delist(
                pe, col, act_exit, act_exit + 252
            )
            fly_20 = float(post_alpha_1y > 0.20)
            fly_50 = float(post_alpha_1y > 0.50)
        elif is_delist:
            # Stock delisted at or before exit -> cannot rally after exit
            post_alpha_1y = 0.0
            fly_20 = 0.0
            fly_50 = 0.0
        else:
            post_alpha_1y = np.nan
            fly_20 = np.nan
            fly_50 = np.nan

        # Trigger-only flyaway (specifically when a dynamic rule actively sold the position early!)
        trig_fly_20 = fly_20 if (is_dyn and triggered) else np.nan
        trig_fly_50 = fly_50 if (is_dyn and triggered) else np.nan
        trig_post_alpha_1y = post_alpha_1y if (is_dyn and triggered) else np.nan

        trade_out[r_code] = {
            "ticker": tk,
            "stock_col": col,
            "entry_date": str(pe.dates[d0])[:10],
            "exit_date": str(pe.dates[act_exit])[:10],
            "d0": d0,
            "d_exit": act_exit,
            "triggered": bool(triggered),
            "trig_5y": bool(trig_5y),
            "hold_days": int(hd),
            "hold_days_5y": int(hd_5y),
            "r_stk": float(r_stk),
            "r_spy": float(r_spy),
            "net_alpha": float(alpha),
            "net_alpha_5y_cap": float(alpha_5y),
            "reinv_3y_ret": float(wealth_3y_reinv),
            "reinv_3y_spy": float(rspy_3y),
            "reinv_3y_alpha": float(reinv_3y_alpha),
            "hold_3y_counterfactual_alpha": float(alpha_3y),
            "has_full_3y": bool(has_full_3y),
            "trade_mdd": float(mdd),
            "post_exit_1y_alpha": float(post_alpha_1y) if not np.isnan(post_alpha_1y) else np.nan,
            "flyaway_1y_gt20": fly_20,
            "flyaway_1y_gt50": fly_50,
            "trig_flyaway_1y_gt20": trig_fly_20,
            "trig_flyaway_1y_gt50": trig_fly_50,
            "trig_post_1y_alpha": trig_post_alpha_1y,
            "comp_trig_type": (
                "Fund_Falsified"
                if (r_code == "R13_Composite_Optimal" and triggered and sig_comp_fund is not None and sig_d == sig_comp_fund)
                else ("Val_Bubble_Cap" if (r_code == "R13_Composite_Optimal" and triggered) else "Hold_Cap")
            ),
        }
    return trade_out


def simulate_10slot_daily_portfolio(trades_df: pd.DataFrame, pe: PriceEngine, max_slots: int = 10) -> dict:
    """
    Simulates a realistic, zero-lookahead 10-slot capped daily portfolio from first entry to 2026-11-06:
    - Each active trade holds at most `1 / max_slots` (10%) weight; if >10 concurrent signals exist,
      equal-weights active positions (`1 / N_active`).
    - Any unfilled slots `(max_slots - N_active) / max_slots` earn daily SPY total return (zero idle-cash bias,
      zero 100%-single-stock concentration blowup).
    Returns annualized portfolio CAGR, SPY CAGR, net annualized excess (`port_10slot_cagr_alpha`), and portfolio MDD.
    """
    if len(trades_df) == 0:
        return {"port_cagr": np.nan, "spy_cagr": np.nan, "port_cagr_alpha": np.nan, "port_mdd": np.nan}

    d_min = int(trades_df["d0"].min())
    d_max = int(trades_df["d_exit"].max())
    if d_max <= d_min + 20:
        return {"port_cagr": np.nan, "spy_cagr": np.nan, "port_cagr_alpha": np.nan, "port_mdd": np.nan}

    n_span = d_max - d_min
    sum_stk_ret = np.zeros(n_span, dtype=np.float64)
    cnt_act = np.zeros(n_span, dtype=np.int32)

    spy_tr = pe.spy_tr.astype(np.float64)
    spy_daily = spy_tr[d_min + 1 : d_max + 1] / spy_tr[d_min:d_max] - 1.0

    for col, d0, de, rstk in zip(
        trades_df["stock_col"].values,
        trades_df["d0"].values,
        trades_df["d_exit"].values,
        trades_df["r_stk"].values,
    ):
        if de <= d0:
            continue
        px_slice = pe.P_adj[d0 : de + 1, int(col)].astype(np.float64)
        # Forward-fill any single missing print safely
        if np.isnan(px_slice).any():
            s = pd.Series(px_slice).ffill().bfill().values
        else:
            s = px_slice
        d_rets = s[1:] / s[:-1] - 1.0
        # Splice exact terminal delisting return on final day if delisted
        cum_path = float(np.prod(1.0 + d_rets) - 1.0)
        if abs(cum_path - rstk) > 1e-3 and (1.0 + cum_path) > 1e-6:
            d_rets[-1] = (1.0 + d_rets[-1]) * ((1.0 + rstk) / (1.0 + cum_path)) - 1.0

        s_idx = int(d0) - d_min
        e_idx = int(de) - d_min
        sum_stk_ret[s_idx:e_idx] += d_rets
        cnt_act[s_idx:e_idx] += 1

    # Position weight = 1/max_slots when cnt <= max_slots, else 1/cnt_act; remainder in SPY
    w_each = np.where(cnt_act > max_slots, 1.0 / np.maximum(cnt_act, 1), 1.0 / float(max_slots))
    spy_weight = np.maximum(0.0, 1.0 - cnt_act * w_each)
    port_daily = sum_stk_ret * w_each + spy_weight * spy_daily

    nav_port = np.cumprod(1.0 + port_daily)
    nav_spy = np.cumprod(1.0 + spy_daily)

    yrs = n_span / 252.0
    port_cagr = float(nav_port[-1] ** (1.0 / yrs) - 1.0)
    spy_cagr = float(nav_spy[-1] ** (1.0 / yrs) - 1.0)
    run_pk = np.maximum.accumulate(np.insert(nav_port, 0, 1.0))
    port_mdd = float(np.min(np.insert(nav_port, 0, 1.0) / run_pk - 1.0))

    # Active-day-only deployed slot excess annualized (when cnt_act > 0, average active stock daily alpha * 252)
    act_mask = cnt_act > 0
    if np.any(act_mask):
        avg_stk_daily = sum_stk_ret[act_mask] / cnt_act[act_mask]
        nav_act_stk = float(np.prod(1.0 + avg_stk_daily))
        nav_act_spy = float(np.prod(1.0 + spy_daily[act_mask]))
        act_yrs = float(np.sum(act_mask)) / 252.0
        active_eq_cagr_alpha = float(nav_act_stk ** (1.0 / act_yrs) - nav_act_spy ** (1.0 / act_yrs))
    else:
        active_eq_cagr_alpha = np.nan

    return {
        "port_10slot_cagr": port_cagr,
        "spy_same_span_cagr": spy_cagr,
        "port_10slot_cagr_alpha": port_cagr - spy_cagr,
        "active_eq_cagr_alpha": active_eq_cagr_alpha,
        "port_10slot_mdd": port_mdd,
    }


def subperiod_win_payoff(df_t: pd.DataFrame, mask: np.ndarray) -> tuple:
    sub = df_t[mask]
    if len(sub) < 3:
        return np.nan, np.nan, int(len(sub))
    a = sub["net_alpha"].values
    wr = float(np.mean(a > 0))
    pos = a[a > 0]
    neg = a[a <= 0]
    po = float(pos.mean() / abs(neg.mean())) if (len(pos) > 0 and len(neg) > 0 and neg.mean() != 0) else np.nan
    return wr, po, int(len(sub))


def aggregate_rule_metrics(
    strat_code: str,
    strat_cn: str,
    rule_code: str,
    rule_cn: str,
    df_t: pd.DataFrame,
    pe: PriceEngine,
) -> dict:
    df_t = df_t.copy()
    df_t["cal_qtr"] = pd.to_datetime(df_t["entry_date"]).dt.to_period("Q")
    dt_ent = pd.to_datetime(df_t["entry_date"])

    # Calendar-quarter equal-weight net excess vs SPY (D15 requirement #1)
    qtr_ew_alpha = float(df_t.groupby("cal_qtr")["net_alpha"].mean().mean())
    qtr_ew_alpha_5y_cap = float(df_t.groupby("cal_qtr")["net_alpha_5y_cap"].mean().mean())

    a = df_t["net_alpha"].values
    r = df_t["r_stk"].values
    wr_full, po_full, n_full = subperiod_win_payoff(df_t, np.ones(len(df_t), dtype=bool))
    wr_10y, po_10y, n_10y = subperiod_win_payoff(df_t, (dt_ent >= "2016-01-01").values)
    wr_3y, po_3y, n_3y = subperiod_win_payoff(df_t, (dt_ent >= "2023-01-01").values)
    wr_hr, po_hr, n_hr = subperiod_win_payoff(df_t, (dt_ent >= "2022-01-01").values)

    # Matched 3Y SPY-parked annualized excess (strictly on trades with full 3Y calendar window)
    f3 = df_t[df_t["has_full_3y"]]
    if len(f3) >= 5:
        q_w = float(f3.groupby("cal_qtr")["reinv_3y_ret"].mean().mean())
        q_s = float(f3.groupby("cal_qtr")["reinv_3y_spy"].mean().mean())
        reinv_3y_qew_alpha = q_w - q_s
        reinv_3y_ann_alpha = float((1.0 + q_w) ** (1.0 / 3.0) - (1.0 + q_s) ** (1.0 / 3.0))
    else:
        reinv_3y_qew_alpha = np.nan
        reinv_3y_ann_alpha = np.nan

    # Realistic 10-slot daily portfolio CAGR excess
    port_stats = simulate_10slot_daily_portfolio(df_t, pe, max_slots=10)

    # Flyaway rates (all exits vs triggered early exits)
    fly20_all = df_t["flyaway_1y_gt20"].dropna()
    fly50_all = df_t["flyaway_1y_gt50"].dropna()
    post1y_all = df_t["post_exit_1y_alpha"].dropna()

    trig_fly20 = df_t["trig_flyaway_1y_gt20"].dropna()
    trig_post1y = df_t["trig_post_1y_alpha"].dropna()

    return {
        "strategy_code": strat_code,
        "strategy_name": strat_cn,
        "rule_code": rule_code,
        "rule_name": rule_cn,
        "n_trades": int(n_full),
        "trigger_rate": float(df_t["triggered"].mean()),
        "avg_hold_days": float(df_t["hold_days"].mean()),
        "med_hold_days": float(df_t["hold_days"].median()),
        "avg_hold_days_5y_cap": float(df_t["hold_days_5y"].mean()),
        "qtr_ew_net_alpha": qtr_ew_alpha,
        "qtr_ew_net_alpha_5y_cap": qtr_ew_alpha_5y_cap,
        "mean_net_alpha": float(np.mean(a)),
        "med_net_alpha": float(np.median(a)),
        "port_10slot_cagr_alpha": port_stats["port_10slot_cagr_alpha"],
        "active_eq_cagr_alpha": port_stats["active_eq_cagr_alpha"],
        "reinv_3y_qew_alpha": reinv_3y_qew_alpha,
        "reinv_3y_ann_alpha": reinv_3y_ann_alpha,
        "win_rate_full": wr_full,
        "payoff_full": po_full,
        "win_rate_last10y": wr_10y,
        "payoff_last10y": po_10y,
        "win_rate_recent3y": wr_3y,
        "payoff_recent3y": po_3y,
        "win_rate_highrate_22_26": wr_hr,
        "payoff_highrate_22_26": po_hr,
        "med_trade_mdd": float(df_t["trade_mdd"].median()),
        "mean_trade_mdd": float(df_t["trade_mdd"].mean()),
        "port_10slot_mdd": port_stats["port_10slot_mdd"],
        "halve_prob_le_m50": float(np.mean(r <= -0.50)),
        "bagger2x_prob_ge_100": float(np.mean(r >= 1.00)),
        "flyaway_1y_gt20pct": float(fly20_all.mean()) if len(fly20_all) else np.nan,
        "flyaway_1y_gt50pct": float(fly50_all.mean()) if len(fly50_all) else np.nan,
        "post_exit_1y_mean_alpha": float(post1y_all.mean()) if len(post1y_all) else np.nan,
        "triggered_only_flyaway_1y_gt20pct": float(trig_fly20.mean()) if len(trig_fly20) else np.nan,
        "triggered_only_post_1y_mean_alpha": float(trig_post1y.mean()) if len(trig_post1y) else np.nan,
    }


def build_whipsaw_audit_table(all_trade_records: dict) -> tuple:
    """
    Builds `table_g04_stop_loss_whipsaw_audit.csv` dissecting the exact whipsaw & early-shakeout damage
    of `-15%` mechanical stop loss (`R10`), `-25%` trailing stop (`R11`), `MA200` breakdown (`R12`),
    `1Q Rev Decel` (`R04`), and `2Q Rev Decel` (`R05`), vs `3Q Decel+OPM` (`R06`), `Bubble Cap` (`R08`),
    and `Composite Slow-Ledger` (`R13`), strictly on trades with full 3Y counterfactual window (`has_full_3y`).
    Also extracts top real historical whipsaw cases with exact dates & numbers.
    """
    audit_rules = [
        ("R10_Stop_Hard_m15pct", "8. 机械止损(-15%次日卖)"),
        ("R11_Stop_Trail_m25pct", "9. 移动回撤止损(-25%次日卖)"),
        ("R12_Trend_MA200_5d_m5pct", "10. 跌破200MA满5日且<-5%"),
        ("R04_Fund_1Q_RevDecel", "2. 单季营收减速即卖"),
        ("R05_Fund_2Q_RevDecel", "3. 连续2季营收减速即卖"),
        ("R07_Fund_GM200bps_or_FCFNeg", "5. 毛利恶化>=200bps或FCF转负"),
        ("R06_Fund_3Q_Decel_OPMBreak", "4. 连3季减速+利润率破位"),
        ("R08_Val_Bubble_PS22_PE48", "6. 估值泡沫止盈(PS>22/PE>48)"),
        ("R13_Composite_Optimal", "11. 复合慢账守则(证伪+泡沫)"),
    ]

    rows = []
    notable_cases = []

    for (strat_code, strat_cn), rule_map in all_trade_records.items():
        for r_code, r_cn in audit_rules:
            df_r = rule_map[r_code]
            f3 = df_r[df_r["has_full_3y"]].copy()
            trig = f3[f3["triggered"]].copy()
            untrig = f3[~f3["triggered"]].copy()

            n_f3 = len(f3)
            n_tr = len(trig)
            if n_f3 == 0:
                continue

            # Counterfactual comparison on the EXACT shaken-out (`triggered`) subset:
            # What did the rule realize at exit vs what did holding those exact shaken-out stocks to 3Y achieve?
            if n_tr > 0:
                realized_alpha_trig = float(trig["net_alpha"].mean())
                reinv_3y_alpha_trig = float(trig["reinv_3y_alpha"].mean())
                hold_3y_alpha_trig = float(trig["hold_3y_counterfactual_alpha"].mean())
                whipsaw_gap_vs_hold3y = hold_3y_alpha_trig - reinv_3y_alpha_trig
                recovered_beat_spy_3y = float((trig["hold_3y_counterfactual_alpha"] > 0.0).mean())
                recovered_beat_exit_by_20pct = float(
                    ((trig["hold_3y_counterfactual_alpha"] - trig["reinv_3y_alpha"]) > 0.20).mean()
                )
                fly1y_20 = float(trig["flyaway_1y_gt20"].dropna().mean()) if len(trig["flyaway_1y_gt20"].dropna()) else np.nan
                fly1y_50 = float(trig["flyaway_1y_gt50"].dropna().mean()) if len(trig["flyaway_1y_gt50"].dropna()) else np.nan
                post1y_mean = float(trig["post_exit_1y_alpha"].dropna().mean()) if len(trig["post_exit_1y_alpha"].dropna()) else np.nan
                avg_exit_days = float(trig["hold_days"].mean())

                # Collect top whipsaw examples for R10 (-15% stop) and R04 (1Q decel)
                if r_code in ("R10_Stop_Hard_m15pct", "R04_Fund_1Q_RevDecel", "R08_Val_Bubble_PS22_PE48"):
                    trig_sorted = trig.assign(
                        missed_3y_gain=trig["hold_3y_counterfactual_alpha"] - trig["reinv_3y_alpha"]
                    ).sort_values("missed_3y_gain", ascending=(r_code == "R08_Val_Bubble_PS22_PE48"))
                    for _, cr in trig_sorted.head(5).iterrows():
                        notable_cases.append(
                            {
                                "strategy_code": strat_code,
                                "strategy_name": strat_cn,
                                "rule_code": r_code,
                                "ticker": cr["ticker"],
                                "entry_date": cr["entry_date"],
                                "exit_date": cr["exit_date"],
                                "hold_days": int(cr["hold_days"]),
                                "realized_net_alpha": round(float(cr["net_alpha"]), 4),
                                "reinv_3y_alpha": round(float(cr["reinv_3y_alpha"]), 4),
                                "hold_3y_alpha": round(float(cr["hold_3y_counterfactual_alpha"]), 4),
                                "missed_3y_alpha_gap": round(float(cr["missed_3y_alpha_gap"]) if "missed_3y_alpha_gap" in cr else float(cr["missed_3y_gain"]), 4),
                                "post_exit_1y_alpha": round(float(cr["post_exit_1y_alpha"]), 4) if pd.notna(cr["post_exit_1y_alpha"]) else np.nan,
                            }
                        )
            else:
                realized_alpha_trig = np.nan
                reinv_3y_alpha_trig = np.nan
                hold_3y_alpha_trig = np.nan
                whipsaw_gap_vs_hold3y = np.nan
                recovered_beat_spy_3y = np.nan
                recovered_beat_exit_by_20pct = np.nan
                fly1y_20 = np.nan
                fly1y_50 = np.nan
                post1y_mean = np.nan
                avg_exit_days = np.nan

            rows.append(
                {
                    "strategy_code": strat_code,
                    "strategy_name": strat_cn,
                    "rule_code": r_code,
                    "rule_name": r_cn,
                    "n_3y_cohort": int(n_f3),
                    "n_triggered": int(n_tr),
                    "trigger_shakeout_pct": float(n_tr / n_f3),
                    "avg_days_to_trigger": avg_exit_days,
                    "triggered_realized_alpha_at_exit": realized_alpha_trig,
                    "triggered_reinv_spy_to_3y_alpha": reinv_3y_alpha_trig,
                    "triggered_counterfactual_hold_3y_alpha": hold_3y_alpha_trig,
                    "whipsaw_cost_missed_3y_alpha_on_triggered": whipsaw_gap_vs_hold3y,
                    "pct_triggered_eventual_3y_positive_alpha": recovered_beat_spy_3y,
                    "pct_triggered_rebounded_gt20pct_to_3y": recovered_beat_exit_by_20pct,
                    "triggered_flyaway_1y_gt20pct": fly1y_20,
                    "triggered_flyaway_1y_gt50pct": fly1y_50,
                    "triggered_post_exit_1y_mean_alpha": post1y_mean,
                    "full_cohort_reinv_3y_mean_alpha": float(f3["reinv_3y_alpha"].mean()),
                    "full_cohort_hold_3y_mean_alpha": float(f3["hold_3y_counterfactual_alpha"].mean()),
                }
            )

    return pd.DataFrame(rows), pd.DataFrame(notable_cases)


def main():
    t0 = time.time()
    os.makedirs(OUT_DIR, exist_ok=True)

    pe = PriceEngine.get_instance()
    px_verify = verify_unified_prices_alignment(pe)
    df = build_master_pit_with_streaks(pe)
    strats = define_four_strategies(df, pe)
    ma200 = precompute_ma200(pe.P_adj)
    tk_lookup = build_ticker_filing_lookup(df)

    main_rows = []
    all_trade_records = {}

    for strat_code, (strat_cn, df_s) in strats.items():
        t_s = time.time()
        per_rule_lists = {rc: [] for rc, _ in EXIT_RULES}
        for _, row in df_s.iterrows():
            res_map = simulate_single_trade_all_rules(
                row, tk_lookup, pe, ma200, max_dyn_days=756
            )
            for rc, _ in EXIT_RULES:
                per_rule_lists[rc].append(res_map[rc])

        rule_dfs = {rc: pd.DataFrame(per_rule_lists[rc]) for rc, _ in EXIT_RULES}
        all_trade_records[(strat_code, strat_cn)] = rule_dfs

        for rc, rcn in EXIT_RULES:
            agg = aggregate_rule_metrics(strat_code, strat_cn, rc, rcn, rule_dfs[rc], pe)
            main_rows.append(agg)
        print(f"[Simulated] {strat_code} ({len(df_s)} trades x 15 rules) in {time.time()-t_s:.2f}s.")

    df_main = pd.DataFrame(main_rows)
    csv_main = os.path.join(OUT_DIR, "table_g04_exit_rules_by_strategy.csv")
    df_main.to_csv(csv_main, index=False)

    df_whip, df_cases = build_whipsaw_audit_table(all_trade_records)
    csv_whip = os.path.join(OUT_DIR, "table_g04_stop_loss_whipsaw_audit.csv")
    df_whip.to_csv(csv_whip, index=False)

    cases_json_path = os.path.join(OUT_DIR, "g04_notable_cases_and_meta.json")
    with open(cases_json_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "price_verification": px_verify,
                "notable_cases": df_cases.to_dict(orient="records"),
                "elapsed_sec": round(time.time() - t0, 2),
            },
            f,
            indent=2,
            ensure_ascii=False,
        )

    # Print crisp verification tables to stdout
    pd.set_option("display.max_columns", 30)
    pd.set_option("display.width", 220)
    cols_show = [
        "strategy_code",
        "rule_code",
        "n_trades",
        "trigger_rate",
        "avg_hold_days",
        "qtr_ew_net_alpha",
        "qtr_ew_net_alpha_5y_cap",
        "port_10slot_cagr_alpha",
        "reinv_3y_ann_alpha",
        "win_rate_full",
        "payoff_full",
        "win_rate_last10y",
        "win_rate_recent3y",
        "med_trade_mdd",
        "flyaway_1y_gt20pct",
        "triggered_only_flyaway_1y_gt20pct",
    ]
    print("\n================ TABLE 1: EXIT RULES BY STRATEGY (3Y-MATCHED & 5Y-CAP) ================")
    print(df_main[cols_show].to_string(index=False))

    print("\n================ TABLE 2: WHIPSAW & SHAKEOUT AUDIT ================")
    w_cols = [
        "strategy_code",
        "rule_code",
        "n_3y_cohort",
        "trigger_shakeout_pct",
        "avg_days_to_trigger",
        "triggered_realized_alpha_at_exit",
        "triggered_reinv_spy_to_3y_alpha",
        "triggered_counterfactual_hold_3y_alpha",
        "whipsaw_cost_missed_3y_alpha_on_triggered",
        "triggered_flyaway_1y_gt20pct",
        "triggered_flyaway_1y_gt50pct",
    ]
    print(df_whip[w_cols].to_string(index=False))

    print("\n================ NOTABLE HISTORICAL WHIPSAW & BUBBLE-EXIT CASES ================")
    print(df_cases.to_string(index=False))
    print(f"\n[DONE] Saved {csv_main} and {csv_whip} in {time.time()-t0:.2f}s.")


if __name__ == "__main__":
    main()

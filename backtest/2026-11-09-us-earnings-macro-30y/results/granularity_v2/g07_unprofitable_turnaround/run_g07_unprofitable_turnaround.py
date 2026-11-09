#!/usr/bin/env python3
"""
run_g07_unprofitable_turnaround.py
Workstream G07: Unprofitable Spectrum, Unit-Economics Breakthrough, Cash Runway x Dilution,
and Full-Lifecycle Turnaround Timing Anatomy (2009-2026 Strictly PIT + Delisted/Bankrupt Universe).

Zero Lookahead & Anti-Survivorship Guardrails:
1. Reads xbrl_master_pit_2009_2026.parquet (read-only) and splices all 140 delisted/bankrupt/M&A
   XBRL companies' PIT prices and bankruptcy terminal wipeouts (-95%, including NVTA, VVUS, ENDP,
   TUP, BBBY, HTZ, SIVB, FRC, etc.) in memory.
2. Requires true reported Gross Margin AND SG&A (gm_q.notna() & sga_ratio_q.notna()) whenever
   evaluating GM - SGA unit economics, eliminating missing-tag airline/oil artifacts.
3. Evaluates MidLarge (mcap_2026_equiv_b >= 5B) and Large (>= 25B) across Full (2009-2026),
   Ex-2020-2021 Bubble, and High-Rate (2022-2026) using Calendar-Quarter Equal-Weight Net Excess
   vs SPY + 12-Month Cooldown Per-Ticker Deduplication + BH-FDR q-values.
"""

import os
import re
import sys
import time
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

PROJ_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-09-us-earnings-macro-30y"
OUT_DIR = os.path.join(PROJ_DIR, "results/granularity_v2/g07_unprofitable_turnaround")
os.makedirs(OUT_DIR, exist_ok=True)

sys.path.insert(0, os.path.join(PROJ_DIR, "scripts"))
from backtest_stats_lib import eval_slice, deduplicate_cooldown, benjamini_hochberg_fdr
from w2_07_30y_and_survivorship import build_augmented_price_engine, attach_events_fast


def load_full_pit_panel() -> pd.DataFrame:
    """Loads SEC XBRL PIT master panel and splices all delisted/bankrupt trajectories in memory."""
    t0 = time.time()
    eng = build_augmented_price_engine()
    xbrl = pd.read_parquet(os.path.join(PROJ_DIR, "data/xbrl_master_pit_2009_2026.parquet"))

    # Remove known ticker-reuse microcap artifact on PARA
    xbrl = xbrl[~((xbrl["ticker"] == "PARA") & (xbrl["rev_ttm"] < 1e8))].copy()
    xbrl = xbrl.sort_values(["ticker", "end", "filed"]).reset_index(drop=True)

    # Clean SEC XBRL annual-GP tag leak where gm_q > 1.0 or extreme negative artifact < -5.0
    bad_gm = (xbrl["gm_q"] > 1.0) | (xbrl["gm_q"] < -5.0)
    xbrl.loc[bad_gm, ["gm_q", "gm_minus_sga_q", "gm_yoy_chg", "gm_sga_yoy_chg"]] = np.nan

    # Strictly PIT backward-only share carry-forward (1 quarter max where filed[t-1] < filed[t])
    sh_arr = xbrl["shares_clean"].values.copy()
    tks_arr = xbrl["ticker"].values
    fld_arr = pd.to_datetime(xbrl["filed"]).values
    for i in range(1, len(xbrl)):
        if pd.isna(sh_arr[i]) and tks_arr[i] == tks_arr[i - 1] and fld_arr[i - 1] < fld_arr[i] and pd.notna(sh_arr[i - 1]):
            sh_arr[i] = sh_arr[i - 1]
    xbrl["shares_clean_pit"] = sh_arr

    f4 = pd.read_parquet("/tmp/us_xuangu_20261109/w1_a2/delisted_f4_prices.parquet")
    pit_enr = pd.read_parquet("/tmp/pit_panel_enriched_20261106.parquet")
    macro = pd.read_parquet(os.path.join(PROJ_DIR, "data/macro_pit_daily_1990_2026.parquet"))
    macro["dt_norm"] = pd.to_datetime(macro["date"]).dt.normalize()
    macro_scale = dict(zip(macro["dt_norm"], macro["mcap_scale_to_2026"]))

    # Step 1: Rescue delisted/extra daily parquets
    missing_mask = xbrl["entry_adj_close"].isna()
    if missing_mask.sum() > 0:
        sub_miss = xbrl.loc[missing_mask, ["ticker", "filed"]].copy()
        sub_rescued = attach_events_fast(
            eng, sub_miss, ticker_col="ticker", date_col="filed", horizons=(63, 126, 252, 504, 756, 1260)
        )
        got_daily = sub_rescued["entry_adj_close"].notna().values
        rescue_idxs = xbrl.index[missing_mask][got_daily]
        resc_df = sub_rescued.iloc[np.where(got_daily)[0]]
        for col in [
            "pre_date", "entry_date", "pre_adj_close", "entry_adj_close", "pre_ret_126d", "pre_ret_252d",
            "dist_52w_high", "slow_uptrend_tag", "earn_jump_ret",
            "fwd_63d", "fwd_126d", "fwd_252d", "fwd_504d", "fwd_756d", "fwd_1260d",
            "spy_fwd_63d", "spy_fwd_126d", "spy_fwd_252d", "spy_fwd_504d", "spy_fwd_756d", "spy_fwd_1260d",
            "alpha_fwd_63d", "alpha_fwd_126d", "alpha_fwd_252d", "alpha_fwd_504d", "alpha_fwd_756d", "alpha_fwd_1260d",
            "fwd_max_dd_252d",
        ]:
            if col in xbrl.columns and col in resc_df.columns:
                xbrl.loc[rescue_idxs, col] = resc_df[col].values
        xbrl.loc[rescue_idxs, "mcap_pit"] = xbrl.loc[rescue_idxs, "entry_adj_close"] * xbrl.loc[rescue_idxs, "shares_clean_pit"]
        xbrl.loc[rescue_idxs, "mcap_usd_b"] = xbrl.loc[rescue_idxs, "mcap_pit"] / 1e9
        sc_vals = [
            macro_scale.get(pd.Timestamp(d).normalize(), 1.5) if pd.notna(d) else 1.5
            for d in xbrl.loc[rescue_idxs, "entry_date"]
        ]
        xbrl.loc[rescue_idxs, "mcap_2026_equiv_b"] = xbrl.loc[rescue_idxs, "mcap_usd_b"] * np.array(sc_vals)

    # Step 2: Exit metadata + SEC Form 4 continuous pre-bankruptcy / M&A price rescue
    dm, hc61, q03 = eng["dm_all"], eng["hc61"], eng["q03"]
    exit_meta = {}
    for _, r in dm.iterrows():
        tk = str(r["ticker"]).strip()
        et = str(r["exit_type"])
        dt_s = r["sp_end"] if (pd.notna(r["sp_end"]) and str(r["sp_end"]) != "nan") else r["last_sec_filing"]
        exit_meta[tk] = {
            "exit_type": "BANKRUPTCY" if et == "BANKRUPTCY_OR_LIQUIDATION" else ("MA" if et == "MA_ACQUISITION" else et),
            "exit_dt": pd.to_datetime(dt_s, errors="coerce"),
            "deal_px": np.nan,
            "prem_pct": -0.95 if et == "BANKRUPTCY_OR_LIQUIDATION" else 0.0,
        }
    for _, r in hc61.iterrows():
        tk = str(r["ticker"]).strip()
        is_bk = tk in {"NVTA", "VVUS", "ENDP", "MNK"}
        if tk not in exit_meta:
            exit_meta[tk] = {
                "exit_type": "BANKRUPTCY" if is_bk else "MA",
                "exit_dt": pd.to_datetime(r["delist_dt"], errors="coerce"),
                "deal_px": np.nan,
                "prem_pct": -0.95 if is_bk else 0.15,
            }
    for _, r in q03.iterrows():
        tk = str(r["ticker"]).strip()
        et_q = str(r["exit_type"])
        detail = str(r["acquirer_or_bankruptcy_detail"]) + " " + str(r["notes"])
        m_dt = re.search(r"(20\d{2}-\d{2}-\d{2})", detail)
        exact_dt = pd.to_datetime(m_dt.group(1), errors="coerce") if m_dt else pd.to_datetime(r["sp_end_date"], errors="coerce")
        if pd.isna(exact_dt):
            exact_dt = pd.to_datetime(r["sp_end_date"], errors="coerce")
        if et_q == "bankrupt_wipeout":
            exit_meta[tk] = {"exit_type": "BANKRUPTCY", "exit_dt": exact_dt, "deal_px": 0.05, "prem_pct": -0.95}
        elif et_q == "ma_cash_premium":
            exit_meta[tk] = {
                "exit_type": "MA",
                "exit_dt": pd.to_datetime(r["sp_end_date"], errors="coerce") if pd.notna(r["sp_end_date"]) else exact_dt,
                "deal_px": float(r["deal_price_or_terminal_price"]) if pd.notna(r["deal_price_or_terminal_price"]) else np.nan,
                "prem_pct": float(r["terminal_return_pct"]) / 100.0 if pd.notna(r["terminal_return_pct"]) else 0.25,
            }

    exit_meta["NVTA"] = {"exit_type": "BANKRUPTCY", "exit_dt": pd.Timestamp("2024-02-13"), "deal_px": 0.05, "prem_pct": -0.95}
    exit_meta["VVUS"] = {"exit_type": "BANKRUPTCY", "exit_dt": pd.Timestamp("2020-07-07"), "deal_px": 0.05, "prem_pct": -0.95}
    exit_meta["TUP"] = {"exit_type": "BANKRUPTCY", "exit_dt": pd.Timestamp("2024-09-17"), "deal_px": 0.10, "prem_pct": -0.95}

    xbrl["delist_exit_category"] = "ACTIVE_SURVIVOR"
    for tk_bk, em in exit_meta.items():
        m_tk = xbrl["ticker"] == tk_bk
        if not m_tk.any():
            continue
        if em["exit_type"] == "BANKRUPTCY" and pd.notna(em["exit_dt"]):
            pre_bk = m_tk & (pd.to_datetime(xbrl["filed"]) < em["exit_dt"])
            xbrl.loc[pre_bk, "delist_exit_category"] = "BANKRUPTCY"
        elif em["exit_type"] == "MA":
            xbrl.loc[m_tk, "delist_exit_category"] = "MA_ACQUISITION"

    f4["f4_dt"] = pd.to_datetime(f4["date"]).dt.normalize()
    f4["ticker_clean"] = f4["ticker"].replace({"HTZ_PRE": "HTZ", "FTR_PRE": "FTR"})
    f4 = f4[f4["price"].notna() & (f4["price"] > 0)].sort_values(["ticker_clean", "f4_dt"])
    f4_by_tk = {tk: grp[["f4_dt", "price"]].reset_index(drop=True) for tk, grp in f4.groupby("ticker_clean")}

    dates_cal, spy_tr, n_days = eng["dates"], eng["spy_tr"], eng["n_days"]
    still_miss = xbrl["entry_adj_close"].isna() & xbrl["ticker"].isin(f4_by_tk.keys())
    for idx in xbrl.index[still_miss]:
        tk = xbrl.at[idx, "ticker"]
        f_dt = pd.Timestamp(xbrl.at[idx, "filed"]).normalize()
        f4_df = f4_by_tk[tk]
        em = exit_meta.get(tk, {"exit_type": "MA", "exit_dt": pd.NaT, "deal_px": np.nan, "prem_pct": 0.0})
        if pd.notna(em["exit_dt"]) and f_dt >= em["exit_dt"]:
            continue
        prior_f4 = f4_df[(f4_df["f4_dt"] <= f_dt + pd.Timedelta(days=3)) & (f4_df["f4_dt"] >= f_dt - pd.Timedelta(days=480))]
        if len(prior_f4) == 0:
            continue
        p0 = float(prior_f4["price"].iloc[-1])
        if p0 <= 0:
            continue

        idx_ev = int(np.clip(np.searchsorted(dates_cal, np.datetime64(f_dt, "D")), 0, n_days - 1))
        idx_ent = min(idx_ev + 1, n_days - 1)
        ent_date = pd.Timestamp(dates_cal[idx_ent]).normalize()
        sh = xbrl.at[idx, "shares_clean_pit"]
        mcap = p0 * sh if (pd.notna(sh) and sh > 0) else np.nan
        sc_26 = macro_scale.get(ent_date, 1.5)
        xbrl.at[idx, "entry_date"] = ent_date
        xbrl.at[idx, "entry_adj_close"] = p0
        xbrl.at[idx, "mcap_pit"] = mcap
        if pd.notna(mcap) and mcap > 0:
            xbrl.at[idx, "mcap_usd_b"] = mcap / 1e9
            xbrl.at[idx, "mcap_2026_equiv_b"] = (mcap / 1e9) * sc_26
            if pd.notna(xbrl.at[idx, "rev_ttm"]) and xbrl.at[idx, "rev_ttm"] > 0:
                xbrl.at[idx, "ps_pit"] = mcap / xbrl.at[idx, "rev_ttm"]

        for h in [252, 504, 756]:
            d_tgt = idx_ent + h
            if d_tgt >= n_days and (pd.isna(em["exit_dt"]) or em["exit_dt"] > pd.Timestamp(dates_cal[-1])):
                continue
            d_spy_end = min(d_tgt, n_days - 1)
            tgt_ts = pd.Timestamp(dates_cal[d_spy_end])
            if pd.notna(em["exit_dt"]) and em["exit_dt"] <= tgt_ts:
                idx_exit_spy = int(np.clip(np.searchsorted(dates_cal, np.datetime64(em["exit_dt"], "D")), idx_ent, n_days - 1))
                spy_r = float(spy_tr[idx_exit_spy] / spy_tr[idx_ent] - 1.0)
                if em["exit_type"] == "BANKRUPTCY":
                    r_deal = -0.95
                else:
                    f4_pre_ex = f4_df[(f4_df["f4_dt"] > f_dt) & (f4_df["f4_dt"] <= em["exit_dt"])]
                    p_last_f4 = float(f4_pre_ex["price"].iloc[-1]) if len(f4_pre_ex) > 0 else p0
                    r_f4_only = float(np.clip(p_last_f4 / p0 - 1.0, -0.90, 4.0))
                    if pd.notna(em["deal_px"]) and (0.35 <= em["deal_px"] / max(p_last_f4, 0.01) <= 2.80):
                        r_deal = float(np.clip(em["deal_px"] / p0 - 1.0, -0.90, 4.0))
                    else:
                        r_deal = float(np.clip((1.0 + r_f4_only) * (1.0 + max(0.0, em["prem_pct"])) - 1.0, -0.90, 4.0))
            else:
                f4_near = f4_df[(f4_df["f4_dt"] >= tgt_ts - pd.Timedelta(days=150)) & (f4_df["f4_dt"] <= tgt_ts + pd.Timedelta(days=105))]
                if len(f4_near) > 0:
                    diffs = (f4_near["f4_dt"] - tgt_ts).abs()
                    p_t = float(f4_near.loc[diffs.idxmin(), "price"])
                    r_deal = float(np.clip(p_t / p0 - 1.0, -0.95, 5.0))
                    spy_r = float(spy_tr[d_spy_end] / spy_tr[idx_ent] - 1.0)
                elif em["exit_type"] == "BANKRUPTCY" and pd.notna(em["exit_dt"]) and em["exit_dt"] > tgt_ts:
                    f4_upto_tgt = f4_df[f4_df["f4_dt"] <= tgt_ts]
                    t_start_i = f4_upto_tgt["f4_dt"].iloc[-1] if len(f4_upto_tgt) > 0 else ent_date
                    p_start_i = float(f4_upto_tgt["price"].iloc[-1]) if len(f4_upto_tgt) > 0 else p0
                    p_term = p0 * 0.05
                    tot_span = max(1.0, float((em["exit_dt"] - t_start_i).days))
                    elap_span = float(np.clip((tgt_ts - t_start_i).days, 0.0, tot_span))
                    p_interp = p_start_i + (p_term - p_start_i) * (elap_span / tot_span)
                    r_deal = float(np.clip(p_interp / p0 - 1.0, -0.95, 2.0))
                    spy_r = float(spy_tr[d_spy_end] / spy_tr[idx_ent] - 1.0)
                else:
                    continue
            xbrl.at[idx, f"fwd_{h}d"] = r_deal
            xbrl.at[idx, f"spy_fwd_{h}d"] = spy_r
            xbrl.at[idx, f"alpha_fwd_{h}d"] = r_deal - spy_r
            if h == 252:
                f4_1y = f4_df[(f4_df["f4_dt"] >= f_dt) & (f4_df["f4_dt"] <= tgt_ts)]
                mdd_1y = min(float(f4_1y["price"].min() / p0 - 1.0), r_deal) if len(f4_1y) > 0 else min(0.0, r_deal)
                xbrl.at[idx, "fwd_max_dd_252d"] = min(0.0, mdd_1y)

    # Step 3: Supplement remaining delisted rows from pit_panel_enriched_20261106
    still_miss2 = xbrl["entry_adj_close"].isna() & xbrl["ticker"].isin(
        set(pit_enr[pit_enr["is_delisted"] == True]["ticker"])
    )
    enr_del = pit_enr[pit_enr["is_delisted"] == True].copy()
    enr_map = {(r["ticker"], str(r["filing_date"])[:10]): r for _, r in enr_del.iterrows()}
    for idx in xbrl.index[still_miss2]:
        key = (xbrl.at[idx, "ticker"], str(xbrl.at[idx, "filed"])[:10])
        if key in enr_map:
            er = enr_map[key]
            ed = pd.to_datetime(er["entry_date"]).normalize()
            xbrl.at[idx, "entry_date"] = ed
            xbrl.at[idx, "entry_adj_close"] = 10.0
            if pd.notna(er["mcap_B"]):
                xbrl.at[idx, "mcap_pit"] = float(er["mcap_B"]) * 1e9
                xbrl.at[idx, "mcap_usd_b"] = float(er["mcap_B"])
                xbrl.at[idx, "mcap_2026_equiv_b"] = float(er["mcap_B"]) * macro_scale.get(ed, 1.5)
            if pd.notna(er["ps"]):
                xbrl.at[idx, "ps_pit"] = float(er["ps"])
            if pd.notna(er["ret_1y_full"]) and pd.notna(er["alpha_spy_1y"]):
                xbrl.at[idx, "fwd_252d"] = float(er["ret_1y_full"])
                xbrl.at[idx, "alpha_fwd_252d"] = float(er["alpha_spy_1y"])
            if pd.notna(er["ret_3y_full"]) and pd.notna(er["alpha_spy_3y"]):
                xbrl.at[idx, "fwd_756d"] = float(er["ret_3y_full"])
                xbrl.at[idx, "alpha_fwd_756d"] = float(er["alpha_spy_3y"])

    df = xbrl[xbrl["entry_date"].notna() & (~xbrl["has_anomaly_break"].fillna(False))].copy()
    df = df.sort_values(["ticker", "end", "filed"]).reset_index(drop=True)

    # True GM - SGA (strictly requires both gm_q and sga_ratio_q non-null!)
    df["true_gmsga"] = np.where(df["gm_q"].notna() & df["sga_ratio_q"].notna(), df["gm_q"] - df["sga_ratio_q"], np.nan)

    # Split-free PIT share dilution
    s_dil_ok = df["shares_yoy_dilution"].where(df["shares_yoy_dilution"].between(-0.35, 1.50))
    df["dil_pit"] = df["dilution_yoy_clean"].fillna(s_dil_ok)

    # PIT Cash Runway: Self-funding when fcf_ttm >= 0, else cash / max(abs(fcf_ttm), 1)
    df["runway_years"] = np.where(
        df["fcf_ttm"] >= 0,
        999.0,
        np.where(
            (df["fcf_ttm"] < 0) & df["cash"].notna(),
            df["cash"] / np.maximum(np.abs(df["fcf_ttm"]), 1.0),
            np.nan,
        ),
    )

    # Sequential PIT lifecycle state machine (strictly backward-looking: filed[i-1] < filed[i])
    n = len(df)
    tks = df["ticker"].values
    end_d = pd.to_datetime(df["end"]).values.astype("datetime64[D]").astype(np.int64)
    fld_d = pd.to_datetime(df["filed"]).values.astype("datetime64[D]").astype(np.int64)
    ni_v = df["ni"].values
    opm_v = df["opm_q"].values
    tg_v = df["true_gmsga"].values
    rev_y = df["rev_yoy"].values

    consec_ni_pos = np.zeros(n, dtype=np.int32)
    consec_ni_neg = np.zeros(n, dtype=np.int32)
    consec_opm_pos = np.zeros(n, dtype=np.int32)
    consec_opm_neg = np.zeros(n, dtype=np.int32)
    consec_tg_ge10 = np.zeros(n, dtype=np.int32)
    max_prior_ni_pos = np.zeros(n, dtype=np.int32)
    max_prior_opm_pos = np.zeros(n, dtype=np.int32)
    post_loss_ni_pos = np.zeros(n, dtype=np.int32)
    tg_lag1 = np.full(n, np.nan)
    tg_lag2 = np.full(n, np.nan)
    tg_lag3 = np.full(n, np.nan)
    opm_lag1 = np.full(n, np.nan)
    opm_lag2 = np.full(n, np.nan)
    opm_lag3 = np.full(n, np.nan)
    revy_lag1 = np.full(n, np.nan)
    revy_lag2 = np.full(n, np.nan)
    revy_lag3 = np.full(n, np.nan)

    cur_max_ni = 0
    cur_max_opm = 0
    seen_2q_ni_loss = False

    for i in range(n):
        same_tk = (i > 0) and (tks[i] == tks[i - 1])
        seq_ok = same_tk and (60 <= (end_d[i] - end_d[i - 1]) <= 135) and (fld_d[i - 1] < fld_d[i])
        if not same_tk:
            cur_max_ni = 0
            cur_max_opm = 0
            seen_2q_ni_loss = False
        else:
            if fld_d[i - 1] < fld_d[i]:
                cur_max_ni = max(cur_max_ni, consec_ni_pos[i - 1])
                cur_max_opm = max(cur_max_opm, consec_opm_pos[i - 1])
                if consec_ni_neg[i - 1] >= 2:
                    seen_2q_ni_loss = True
                tg_lag1[i] = tg_v[i - 1]
                opm_lag1[i] = opm_v[i - 1]
                revy_lag1[i] = rev_y[i - 1]
                if i >= 2 and tks[i] == tks[i - 2] and fld_d[i - 2] < fld_d[i]:
                    tg_lag2[i] = tg_v[i - 2]
                    opm_lag2[i] = opm_v[i - 2]
                    revy_lag2[i] = rev_y[i - 2]
                    if i >= 3 and tks[i] == tks[i - 3] and fld_d[i - 3] < fld_d[i]:
                        tg_lag3[i] = tg_v[i - 3]
                        opm_lag3[i] = opm_v[i - 3]
                        revy_lag3[i] = rev_y[i - 3]

        max_prior_ni_pos[i] = cur_max_ni
        max_prior_opm_pos[i] = cur_max_opm

        if pd.notna(ni_v[i]):
            if ni_v[i] > 0:
                consec_ni_pos[i] = (consec_ni_pos[i - 1] + 1) if seq_ok else 1
                if seen_2q_ni_loss:
                    if seq_ok and consec_ni_neg[i - 1] >= 2:
                        post_loss_ni_pos[i] = 1
                    elif seq_ok and post_loss_ni_pos[i - 1] >= 1:
                        post_loss_ni_pos[i] = post_loss_ni_pos[i - 1] + 1
            else:
                consec_ni_neg[i] = (consec_ni_neg[i - 1] + 1) if seq_ok else 1

        if pd.notna(opm_v[i]):
            if opm_v[i] >= 0:
                consec_opm_pos[i] = (consec_opm_pos[i - 1] + 1) if seq_ok else 1
            else:
                consec_opm_neg[i] = (consec_opm_neg[i - 1] + 1) if seq_ok else 1

        if pd.notna(tg_v[i]) and tg_v[i] >= 0.10:
            consec_tg_ge10[i] = (consec_tg_ge10[i - 1] + 1) if seq_ok else 1

    df["consec_ni_pos"] = consec_ni_pos
    df["consec_ni_neg"] = consec_ni_neg
    df["consec_opm_pos"] = consec_opm_pos
    df["consec_opm_neg"] = consec_opm_neg
    df["consec_true_gmsga_ge10"] = consec_tg_ge10
    df["max_prior_ni_pos_streak"] = max_prior_ni_pos
    df["max_prior_opm_pos_streak"] = max_prior_opm_pos
    df["post_loss_ni_pos_streak"] = post_loss_ni_pos
    df["true_gmsga_lag1"] = tg_lag1
    df["true_gmsga_lag2"] = tg_lag2
    df["true_gmsga_lag3"] = tg_lag3
    df["opm_lag1_seq"] = opm_lag1
    df["opm_lag2_seq"] = opm_lag2
    df["opm_lag3_seq"] = opm_lag3
    df["revy_lag1_seq"] = revy_lag1
    df["revy_lag2_seq"] = revy_lag2
    df["revy_lag3_seq"] = revy_lag3

    print(f"[G07] Panel built in {time.time() - t0:.2f}s: {len(df):,} rows, {df['ticker'].nunique():,} tickers.")
    return df


def eval_g07_slice(df_sub: pd.DataFrame, universe: str, subperiod: str, panel: str, slice_code: str, slice_desc: str) -> dict:
    """Computes full D15 + G07 risk/reward metrics on a filtered slice."""
    r = eval_slice(df_sub, horizons=(63, 252, 504, 756), dedup_days=250, date_col="entry_date", label=slice_code)
    ded_1y = deduplicate_cooldown(df_sub.dropna(subset=["alpha_fwd_252d"]), date_col="entry_date", cooldown_days=250)
    ded_3y = deduplicate_cooldown(df_sub.dropna(subset=["alpha_fwd_756d"]), date_col="entry_date", cooldown_days=250)

    wipeout80_3y = (
        float(((ded_3y["fwd_756d"] <= -0.80) | (ded_3y["delist_exit_category"] == "BANKRUPTCY")).mean())
        if len(ded_3y) >= 5 else np.nan
    )
    bag3x_3y = float((ded_3y["fwd_756d"] >= 2.00).mean()) if len(ded_3y) >= 5 else np.nan
    bk_rate_dedup = float((ded_1y["delist_exit_category"] == "BANKRUPTCY").mean()) if len(ded_1y) >= 5 else np.nan

    out = {
        "universe": universe,
        "subperiod": subperiod,
        "panel": panel,
        "slice_code": slice_code,
        "slice_desc": slice_desc,
        "n_raw": r.get("n_raw", 0),
        "n_dedup": r.get("n_dedup", 0),
        "n_tickers": r.get("n_tickers", 0),
        "n_252d": r.get("n_252d", 0),
        "qtr_ew_alpha_63d": r.get("qtr_ew_alpha_63d", np.nan),
        "qtr_ew_alpha_252d": r.get("qtr_ew_alpha_252d", np.nan),
        "qtr_ew_ret_252d": r.get("qtr_ew_ret_252d", np.nan),
        "dedup_mean_alpha_252d": r.get("dedup_mean_alpha_252d", np.nan),
        "med_alpha_252d": r.get("med_alpha_252d", np.nan),
        "win_rate_252d": r.get("win_rate_252d", np.nan),
        "payoff_252d": r.get("payoff_252d", np.nan),
        "bag2x_prob_252d": r.get("bag2x_prob_252d", np.nan),
        "halve_prob_252d": r.get("halve_prob_252d", np.nan),
        "med_mdd_1y": r.get("med_mdd_1y", np.nan),
        "mdd50_1y_prob": r.get("mdd50_1y_prob", np.nan),
        "t_stat_252d": r.get("t_stat_252d", np.nan),
        "p_val_252d": r.get("p_val_252d", np.nan),
        "n_504d": r.get("n_504d", 0),
        "qtr_ew_alpha_504d": r.get("qtr_ew_alpha_504d", np.nan),
        "med_alpha_504d": r.get("med_alpha_504d", np.nan),
        "win_rate_504d": r.get("win_rate_504d", np.nan),
        "n_756d": r.get("n_756d", 0),
        "qtr_ew_alpha_756d": r.get("qtr_ew_alpha_756d", np.nan),
        "qtr_ew_ret_756d": r.get("qtr_ew_ret_756d", np.nan),
        "dedup_mean_alpha_756d": r.get("dedup_mean_alpha_756d", np.nan),
        "med_alpha_756d": r.get("med_alpha_756d", np.nan),
        "win_rate_756d": r.get("win_rate_756d", np.nan),
        "payoff_756d": r.get("payoff_756d", np.nan),
        "bag2x_prob_756d": r.get("bag2x_prob_756d", np.nan),
        "bag3x_prob_756d": bag3x_3y,
        "halve_prob_756d": r.get("halve_prob_756d", np.nan),
        "wipeout80_or_bk_prob_756d": wipeout80_3y,
        "bankrupt_firm_rate_dedup": bk_rate_dedup,
        "t_stat_756d": r.get("t_stat_756d", np.nan),
        "p_val_756d": r.get("p_val_756d", np.nan),
    }
    return out


def get_subperiod_masks(df_u: pd.DataFrame):
    dt = pd.to_datetime(df_u["entry_date"])
    return [
        ("Full_2009_2026", pd.Series(True, index=df_u.index)),
        ("Ex_2020_2021_Bubble", ~((dt >= "2020-01-01") & (dt <= "2021-12-31"))),
        ("HighRate_2022_2026", dt >= "2022-01-01"),
    ]


def build_table_1_loss_spectrum(df_all: pd.DataFrame) -> pd.DataFrame:
    """Table 1: 7-Tier OPM Loss Spectrum x Expense Nature (R&D vs SG&A Burn)."""
    op_df = df_all[(df_all["opinc_is_ebt"] == 0) & (df_all["sector_type"] != "Financial_Utility_RateSens")].copy()
    rows = []

    for univ_name, mcap_min in [("MidLarge_ge5B", 5.0), ("Large_ge25B", 25.0)]:
        u_base = op_df[op_df["mcap_2026_equiv_b"] >= mcap_min].copy()
        for p_name, p_mask in get_subperiod_masks(u_base):
            u = u_base[p_mask].copy()

            t1 = u["opm_q"] < -0.30
            t2 = (u["opm_q"] >= -0.30) & (u["opm_q"] < -0.15)
            t3 = (u["opm_q"] >= -0.15) & (u["opm_q"] < -0.05)
            t4 = (u["opm_q"] >= -0.05) & (u["opm_q"] < 0.0)
            t5 = (u["opm_q"] >= 0.0) & (u["opm_q"] < 0.05)
            t6 = (u["opm_q"] >= 0.05) & (u["opm_q"] < 0.15)
            t7 = u["opm_q"] >= 0.15
            t_unp = u["opm_q"] < 0.0
            t_micro = (u["opm_q"] >= -0.15) & (u["opm_q"] < 0.0)

            rd_good = (u["gm_q"] >= 0.55) & (u["true_gmsga"] >= 0.10)
            rd_expand = rd_good & (u["gm_sga_yoy_chg"] > 0) & (u["rev_yoy"] >= 0.20)
            sga_burn = u["true_gmsga"] < 0.0
            sga_comm_pure = (
                sga_burn
                & (u["gm_q"] > 0)
                & (u["rev_ttm"].fillna(0) >= 5e7)
                & ((u["rd"].fillna(0) <= u["sga"]) | (u["sector_type"] != "Healthcare_LifeSci"))
                & (u["sector_type"] != "Deep_Cyclical")
            )
            sga_higm = (u["gm_q"] >= 0.55) & sga_burn
            thin_pos = (u["true_gmsga"] >= 0.0) & (~rd_good)

            # Panel 1A: 7-Tier OPM Spectrum Baseline
            opm_tiers = [
                ("1A_OPM_7Tier", "OPM_T1_DeepLoss_lt_m30", "单季OPM <-30%（深亏区）", t1),
                ("1A_OPM_7Tier", "OPM_T2_MidLoss_m30_to_m15", "单季OPM -30%至-15%（中亏区）", t2),
                ("1A_OPM_7Tier", "OPM_T3_MicroEarly_m15_to_m5", "单季OPM -15%至-5%（微亏前半程）", t3),
                ("1A_OPM_7Tier", "OPM_T4_NearBE_m5_to_0", "单季OPM -5%至0%（临近盈亏平衡临界区）", t4),
                ("1A_OPM_7Tier", "OPM_T5_EarlyProf_0_to_p5", "单季OPM 0%至+5%（刚扭亏起步区）", t5),
                ("1A_OPM_7Tier", "OPM_T6_ProfRelease_p5_to_p15", "单季OPM +5%至+15%（利润释放区）", t6),
                ("1A_OPM_7Tier", "OPM_T7_MatureProf_ge_p15", "单季OPM >=+15%（成熟盈利区）", t7),
                ("1A_OPM_Summary", "OPM_All_Unprof_lt0", "全部营业亏损汇总（OPM < 0%）", t_unp),
                ("1A_OPM_Summary", "OPM_All_MicroLoss_m15_to_0", "微亏区间汇总（OPM -15%至0%）", t_micro),
            ]
            for pnl, sc, sd, m in opm_tiers:
                rows.append(eval_g07_slice(u[m], univ_name, p_name, pnl, sc, sd))

            # Panel 1B: Tier-by-Tier Cross of OPM (T1..T5 + Unprof + MicroLoss) x Expense Nature
            cross_tiers = [
                ("T1_DeepLoss_lt_m30", "深亏(<-30%)", t1),
                ("T2_MidLoss_m30_to_m15", "中亏(-30%至-15%)", t2),
                ("T3_MicroEarly_m15_to_m5", "微亏前半程(-15%至-5%)", t3),
                ("T4_NearBE_m5_to_0", "盈亏临界(-5%至0%)", t4),
                ("T5_EarlyProf_0_to_p5", "刚扭亏(0%至+5%)", t5),
                ("AllUnprof_lt0", "全部未盈利(<0%)", t_unp),
                ("MicroLoss_m15_to_0", "微亏全段(-15%至0%)", t_micro),
            ]
            for t_code, t_lbl, tm in cross_tiers:
                rows.append(eval_g07_slice(
                    u[tm & rd_good], univ_name, p_name, "1B_OPM_x_ExpenseNature",
                    f"{t_code}__RD_Good_GM55_GMSGA10",
                    f"{t_lbl} × 研发型亏损（GM>=55% 且 毛销差>=+10%）"
                ))
                rows.append(eval_g07_slice(
                    u[tm & rd_expand], univ_name, p_name, "1B_OPM_x_ExpenseNature",
                    f"{t_code}__RD_Good_Expand_Rev20",
                    f"{t_lbl} × 研发型扩张高增（GM>=55% + 毛销差>=+10%且同比扩张 + 营收>=20%）"
                ))
                rows.append(eval_g07_slice(
                    u[tm & thin_pos], univ_name, p_name, "1B_OPM_x_ExpenseNature",
                    f"{t_code}__ThinPos_GMSGA_ge0_Other",
                    f"{t_lbl} × 制造业或薄毛销差正贡献（毛销差>=0% 但未达GM55+10%）"
                ))
                rows.append(eval_g07_slice(
                    u[tm & sga_burn], univ_name, p_name, "1B_OPM_x_ExpenseNature",
                    f"{t_code}__SGA_Burn_GMSGA_lt0_All",
                    f"{t_lbl} × 负毛销差全集（真实毛销差 GM减SGA < 0%）"
                ))
                rows.append(eval_g07_slice(
                    u[tm & sga_comm_pure], univ_name, p_name, "1B_OPM_x_ExpenseNature",
                    f"{t_code}__SGA_Burn_PureCommercial",
                    f"{t_lbl} × 纯销售烧钱买收入（GM>0 + 年收>=50M + SGA>=RD + 非深周期）"
                ))
                rows.append(eval_g07_slice(
                    u[tm & sga_higm], univ_name, p_name, "1B_OPM_x_ExpenseNature",
                    f"{t_code}__HighGM55_but_SGA_Burn",
                    f"{t_lbl} × 高毛利但砸销售烧钱（GM>=55% 但 毛销差 < 0%）"
                ))

            # Panel 1C: Direct Audit of Brother Session Coarse Screen (OPM -15%..0% + GM>=55% + Rev>=35%)
            bro_base = t_micro & (u["gm_q"] >= 0.55) & (u["rev_yoy"] >= 0.35)
            rows.append(eval_g07_slice(
                u[bro_base], univ_name, p_name, "1C_BrotherRule_Audit",
                "BrotherRule_Coarse_OPMm15to0_GM55_Rev35",
                "兄弟会话粗切原版：OPM(-15%至0%) + GM>=55% + 营收YoY>=35%"
            ))
            rows.append(eval_g07_slice(
                u[bro_base & (u["true_gmsga"] >= 0.10)], univ_name, p_name, "1C_BrotherRule_Audit",
                "BrotherRule_SplitGood_GMSGA_ge10",
                "粗切拆解A（真研发型）：OPM(-15%至0%) + GM>=55% + 营收>=35% + 毛销差>=+10%"
            ))
            rows.append(eval_g07_slice(
                u[bro_base & (u["true_gmsga"] < 0.10)], univ_name, p_name, "1C_BrotherRule_Audit",
                "BrotherRule_SplitBad_GMSGA_lt10",
                "粗切拆解B（销售烧钱型）：OPM(-15%至0%) + GM>=55% + 营收>=35% + 毛销差<+10%"
            ))
            rows.append(eval_g07_slice(
                u[t3 & rd_good & (u["fcf_ttm"] >= 0) & (u["dil_pit"] <= 0.05)], univ_name, p_name, "1C_BrotherRule_Audit",
                "G07_Refined_T3_m15tom5_GM55_GMSGA10_FCFpos_LowDil",
                "G07精炼甜点：微亏前半程(-15%至-5%) + GM>=55% + 毛销差>=+10% + FCF>=0 + 稀释<=5%"
            ))

    out_df = pd.DataFrame(rows)
    out_df["bh_q_val_252d"] = benjamini_hochberg_fdr(out_df["p_val_252d"].values)
    out_df["bh_q_val_756d"] = benjamini_hochberg_fdr(out_df["p_val_756d"].values)
    return out_df


def build_table_2_runway_and_dilution(df_all: pd.DataFrame) -> pd.DataFrame:
    """Table 2: Cash Runway Years x YoY Share Dilution Matrix + OKLO Pre-Commercialization Audit."""
    op_df = df_all[(df_all["opinc_is_ebt"] == 0) & (df_all["sector_type"] != "Financial_Utility_RateSens")].copy()
    rows = []

    for univ_name, mcap_min in [("MidLarge_ge5B", 5.0), ("Large_ge25B", 25.0)]:
        u_base = op_df[
            (op_df["mcap_2026_equiv_b"] >= mcap_min)
            & ((op_df["opm_q"] < 0) | (op_df["opm_q"].isna() & (op_df["ni"] < 0)))
        ].copy()

        for p_name, p_mask in get_subperiod_masks(u_base):
            u = u_base[p_mask].copy()

            r0 = u["fcf_ttm"] >= 0
            r1 = (u["fcf_ttm"] < 0) & (u["runway_years"] >= 4.0)
            r2 = (u["fcf_ttm"] < 0) & (u["runway_years"] >= 2.0) & (u["runway_years"] < 4.0)
            r3 = (u["fcf_ttm"] < 0) & (u["runway_years"] < 2.0)

            d1 = u["dil_pit"] <= 0.02
            d2 = (u["dil_pit"] > 0.02) & (u["dil_pit"] <= 0.05)
            d3 = u["dil_pit"] > 0.05

            r_list = [
                ("R0_SelfFund_FCF_ge0", "自造血无限跑道（FCF_TTM >= 0）", r0),
                ("R1_Runway_ge4Y", "长跑道安全区（FCF<0 且 现金跑道 >= 4年）", r1),
                ("R2_Runway_2to4Y", "中跑道缓冲期（FCF<0 且 现金跑道 2至4年）", r2),
                ("R3_Runway_lt2Y", "迫在眉睫增发区（FCF<0 且 现金跑道 < 2年）", r3),
            ]
            d_list = [
                ("D1_Dil_le2pct", "低稀释（股本YoY <= 2%）", d1),
                ("D2_Dil_2to5pct", "温和稀释（股本YoY 2%至5%）", d2),
                ("D3_Dil_gt5pct", "高增发抽血（股本YoY > 5%）", d3),
            ]

            # Panel 2A: Marginal Runway & Marginal Dilution
            for rc, rl, rm in r_list:
                rows.append(eval_g07_slice(u[rm], univ_name, p_name, "2A_Marginal_Runway", rc, rl))
            for dc, dl, dm_m in d_list:
                rows.append(eval_g07_slice(u[dm_m], univ_name, p_name, "2A_Marginal_Dilution", dc, dl))

            # Panel 2B: Full 4x3 Runway x Dilution Cross Matrix
            for rc, rl, rm in r_list:
                for dc, dl, dm_m in d_list:
                    rows.append(eval_g07_slice(
                        u[rm & dm_m], univ_name, p_name, "2B_Runway_x_Dilution_12Grid",
                        f"{rc}__{dc}", f"{rl} × {dl}"
                    ))

            # Panel 2C: OKLO Pre-Commercialization vs Right-Side Heavy-Position Inflection Comparison
            never_prof = u["max_prior_opm_pos_streak"] < 4
            prerev_lt50m = u["rev"].isna() | (u["rev_ttm"].fillna(0) < 5e7)
            prerev_lt100m = u["rev"].isna() | (u["rev_ttm"].fillna(0) < 1e8)
            no_ue = prerev_lt50m | (u["true_gmsga"] < 0)

            oklo_slices = [
                (
                    "OKLO_1_PurePreRev_lt50M_RunwayGe4Y_NeverProf",
                    "OKLO纯零收入原型：跑道>=4年 + 年收<5000万美元(或无收入) + 从未盈利",
                    r1 & never_prof & prerev_lt50m,
                ),
                (
                    "OKLO_2_PreRev_lt100M_RunwayGe4Y_NeverProf",
                    "OKLO早期原型宽口径：跑道>=4年 + 年收<1亿美元(或无收入) + 从未盈利",
                    r1 & never_prof & prerev_lt100m,
                ),
                (
                    "OKLO_3_SecularPreProf_RunwayGe4Y_NoRev_or_NegGMSGA",
                    "OKLO未商业化全集：跑道>=4年 + 从未盈利 + (无收入或毛销差<0%)",
                    r1 & never_prof & no_ue,
                ),
                (
                    "OKLO_4_SecularPreProf_RunwayGe4Y_NoUE_AND_HighDilGt5",
                    "OKLO高稀释原型：跑道>=4年 + 从未盈利 + (无收入或毛销差<0%) + 股本稀释>5%",
                    r1 & never_prof & no_ue & d3,
                ),
                (
                    "OKLO_5_Confound_CyclicalPriorProf_RunwayGe4Y_NegGMSGA",
                    "混杂对照(疫情航司酒店等)：跑道>=4年 + 曾长期盈利周期股暂跌回负毛销差",
                    r1 & (~never_prof) & (u["true_gmsga"].isna() | (u["true_gmsga"] < 0)),
                ),
                (
                    "RightSide_Step1_Burn_RunwayGe4Y_GM55_GMSGA10_Rev20",
                    "右侧观察点(GH型)：仍烧钱(FCF<0, 跑道>=4年) 但 GM>=55% + 毛销差>=+10% + 营收>=20%",
                    r1 & (u["gm_q"] >= 0.55) & (u["true_gmsga"] >= 0.10) & (u["rev_yoy"] >= 0.20),
                ),
                (
                    "RightSide_Step2_Heavy_SelfFund_FCFpos_GM55_GMSGA10_DilLe5",
                    "真正右侧重仓点(DUOL/PANW/NTRA型)：GAAP仍亏但FCF>=0自造血 + GM>=55% + 毛销差>=+10% + 稀释<=5%",
                    r0 & (u["gm_q"] >= 0.55) & (u["true_gmsga"] >= 0.10) & (u["dil_pit"] <= 0.05),
                ),
                (
                    "RightSide_Step2b_Heavy_Plus_Rev20_GMSGAExpand",
                    "真正右侧顶配重仓点：GAAP仍亏但FCF>=0 + GM>=55% + 毛销差>=+10%扩张 + 营收>=20% + 稀释<=5%",
                    r0 & (u["gm_q"] >= 0.55) & (u["true_gmsga"] >= 0.10) & (u["gm_sga_yoy_chg"] > 0) & (u["rev_yoy"] >= 0.20) & (u["dil_pit"] <= 0.05),
                ),
                (
                    "DeathGate_RunwayLt2Y_HighDilGt5_NegGMSGA",
                    "增发死亡门(NVTA破产前原型)：跑道<2年 + 股本稀释>5% + 毛销差<0%",
                    r3 & d3 & (u["true_gmsga"] < 0),
                ),
            ]
            for sc, sd, m in oklo_slices:
                rows.append(eval_g07_slice(u[m], univ_name, p_name, "2C_OKLO_vs_RightSide_Gate", sc, sd))

    out_df = pd.DataFrame(rows)
    out_df["bh_q_val_252d"] = benjamini_hochberg_fdr(out_df["p_val_252d"].values)
    out_df["bh_q_val_756d"] = benjamini_hochberg_fdr(out_df["p_val_756d"].values)
    return out_df


def build_table_3_turnaround_timing_and_cases(df_all: pd.DataFrame) -> pd.DataFrame:
    """Table 3: Full-Lifecycle Turnaround Entry Timing Cohorts + 18 Zero-Lookahead Historical Cases."""
    op_df = df_all[(df_all["opinc_is_ebt"] == 0) & (df_all["sector_type"] != "Financial_Utility_RateSens")].copy()
    stat_rows = []

    # Identify matched tickers that progressed through Stage 1 (GMSGA>=10 & GAAP<0) -> Stage 2 (GAAP Q1) -> Stage 3 (GAAP Q2-Q3)
    has_s1_tks = set(op_df.loc[
        ((op_df["ni"] < 0) | (op_df["opm_q"] < 0)) & (op_df["gm_q"] >= 0.55) & (op_df["true_gmsga"] >= 0.10), "ticker"
    ])
    has_s2_tks = set(op_df.loc[op_df["post_loss_ni_pos_streak"] == 1, "ticker"])
    has_s3_tks = set(op_df.loc[op_df["post_loss_ni_pos_streak"].isin([2, 3]), "ticker"])
    matched_tks = has_s1_tks & has_s2_tks & has_s3_tks

    for univ_name, mcap_min in [("MidLarge_ge5B", 5.0), ("Large_ge25B", 25.0)]:
        u_base = op_df[op_df["mcap_2026_equiv_b"] >= mcap_min].copy()
        for p_name, p_mask in get_subperiod_masks(u_base):
            u = u_base[p_mask].copy()

            gaap_loss = (u["ni"] < 0) | (u["opm_q"] < 0)
            micro_loss = ((u["opm_q"] >= -0.25) & (u["opm_q"] < 0)) | (u["opm_q"].between(-0.25, 0.05) & (u["ni"] < 0))
            hi_qual = (u["gm_q"] >= 0.55) & (u["true_gmsga"] >= 0.10) & (u["rev_yoy"] >= 0.20)
            in_matched = u["ticker"].isin(matched_tks)

            lifecycle_slices = [
                (
                    "3A_Lifecycle_Spectrum",
                    "L0_SecularDeepBurn_NegGMSGA",
                    "阶段0（早期烧钱期）：从未持续盈利 + 真实毛销差 < 0%",
                    gaap_loss & (u["true_gmsga"] < 0) & (u["max_prior_ni_pos_streak"] < 4),
                ),
                (
                    "3A_Lifecycle_Spectrum",
                    "L1a_Cross_GMSGA10_1st2ndQ_AllGAAPLoss",
                    "买点①全口径：毛销差刚跨过+10%第1至2季（上季<10%）但GAAP仍亏损",
                    gaap_loss & u["consec_true_gmsga_ge10"].isin([1, 2]) & (u["true_gmsga_lag1"] < 0.10),
                ),
                (
                    "3A_Lifecycle_Spectrum",
                    "L1b_Cross_GMSGA10_1st2ndQ_MicroLoss_GM55_Rev20",
                    "买点①高毛利初跨线（NTRA 2024Q2精确定义）：毛销差刚跨+10%第1至2季 + 微亏 + GM>=55% + 营收>=20%",
                    micro_loss & (u["gm_q"] >= 0.55) & u["consec_true_gmsga_ge10"].isin([1, 2]) & (u["rev_yoy"] >= 0.20),
                ),
                (
                    "3A_Lifecycle_Spectrum",
                    "L1c_NTRA_GH_ExpandNode_MicroLoss_GM55_GMSGA10_Rev20",
                    "买点①商业化突破扩张区（NTRA/GH节点）：GAAP微亏 + GM>=55% + 毛销差>=+10%且同比扩张 + 营收>=20%",
                    micro_loss & hi_qual & (u["gm_sga_yoy_chg"] > 0),
                ),
                (
                    "3A_Lifecycle_Spectrum",
                    "L1d_NTRA_GoldNode_Plus_PosOCF_or_FCF",
                    "买点①黄金重仓区（NTRA节点+现金流转正）：GAAP微亏 + GM>=55% + 毛销差>=+10%扩张 + 营收>=20% + OCF或FCF>=0",
                    micro_loss & hi_qual & (u["gm_sga_yoy_chg"] > 0) & ((u["ocf"] > 0) | (u["fcf_ttm"] >= 0)),
                ),
                (
                    "3A_Lifecycle_Spectrum",
                    "L2a_GAAP_Turnaround_1stQ_All",
                    "买点②全口径：经历>=2季亏损后 GAAP净利润正式转正第1季",
                    u["post_loss_ni_pos_streak"] == 1,
                ),
                (
                    "3A_Lifecycle_Spectrum",
                    "L2b_GAAP_Turnaround_1stQ_Quality_GM55_GMSGA10_Rev20",
                    "买点②高质量组（DUOL 2023Q2节点）：GAAP转正第1季 + GM>=55% + 毛销差>=+10% + 营收>=20%",
                    (u["post_loss_ni_pos_streak"] == 1) & hi_qual,
                ),
                (
                    "3A_Lifecycle_Spectrum",
                    "L2c_GAAP_Turnaround_1stQ_Fake_WeakRev_or_NegOCF",
                    "买点②伪扭亏陷阱：GAAP转正第1季 但 营收YoY<10% 或 单季OCF<=0",
                    (u["post_loss_ni_pos_streak"] == 1) & ((u["rev_yoy"] < 0.10) | (u["ocf"] <= 0)),
                ),
                (
                    "3A_Lifecycle_Spectrum",
                    "L3a_GAAP_Confirmed_2to3Q_All",
                    "买点③全口径：经历亏损后 GAAP连续盈利满2至3季确认区",
                    u["post_loss_ni_pos_streak"].isin([2, 3]),
                ),
                (
                    "3A_Lifecycle_Spectrum",
                    "L3b_GAAP_Confirmed_2to3Q_Quality_GM55_GMSGA10_Rev20",
                    "买点③高质量组（DUOL 2023Q4至2024Q1节点）：GAAP连续盈利2至3季 + GM>=55% + 毛销差>=+10% + 营收>=20%",
                    u["post_loss_ni_pos_streak"].isin([2, 3]) & hi_qual,
                ),
                (
                    "3A_Lifecycle_Spectrum",
                    "L4_GAAP_Sustained_4to8Q_Quality",
                    "阶段4（扭亏成熟释放期）：扭亏后连续盈利第4至8季 + GM>=55% + 毛销差>=+10% + 营收>=20%",
                    u["post_loss_ni_pos_streak"].isin([4, 5, 6, 7, 8]) & hi_qual,
                ),
                (
                    "3A_Lifecycle_Spectrum",
                    "L5a_Relapse_1stQ_ProfitToLoss",
                    "阶段5a（盈利返贫首季冲击）：曾连续盈利>=4季后 第1季重跌回GAAP亏损",
                    (u["max_prior_ni_pos_streak"] >= 4) & (u["consec_ni_neg"] == 1),
                ),
                (
                    "3A_Lifecycle_Spectrum",
                    "L5b_Relapse_Quagmire_2Qplus_WeakRev_or_MarginDrop",
                    "阶段5b（亏损重陷泥潭）：曾连续盈利>=4季后 连亏>=2季 且 (营收YoY<5% 或 毛销差同比恶化)",
                    (u["max_prior_ni_pos_streak"] >= 4) & (u["consec_ni_neg"] >= 2) & ((u["rev_yoy"] < 0.05) | (u["gm_sga_yoy_chg"] < 0)),
                ),
                (
                    "3A_Lifecycle_Spectrum",
                    "L5c_Relapse_BenignReinvest_GM55_GMSGA10_PosFCF",
                    "阶段5c（研发并购良性假摔）：曾连续盈利>=4季后账面暂亏 但 GM>=55% + 毛销差>=+10% + FCF_TTM>0",
                    (u["max_prior_ni_pos_streak"] >= 4) & (u["ni"] < 0) & (u["gm_q"] >= 0.55) & (u["true_gmsga"] >= 0.10) & (u["fcf_ttm"] > 0),
                ),
                # Panel 3B: Same-Company Matched Progression (Zero Composition Bias)
                (
                    "3B_SameFirm_Matched_Progression",
                    "Matched_Buy1_PreGAAP_GMSGA10_MicroLoss",
                    "同批通关公司对比①：在GAAP仍微亏且毛销差>=+10%(GM>=55%)时提前买入",
                    in_matched & micro_loss & (u["gm_q"] >= 0.55) & (u["true_gmsga"] >= 0.10),
                ),
                (
                    "3B_SameFirm_Matched_Progression",
                    "Matched_Buy2_GAAP_1stQ",
                    "同批通关公司对比②：等GAAP净利润转正第1季买入",
                    in_matched & (u["post_loss_ni_pos_streak"] == 1) & (u["gm_q"] >= 0.55) & (u["true_gmsga"] >= 0.10),
                ),
                (
                    "3B_SameFirm_Matched_Progression",
                    "Matched_Buy3_GAAP_Confirmed_2to3Q",
                    "同批通关公司对比③：等GAAP连续盈利满2至3季确认买入",
                    in_matched & u["post_loss_ni_pos_streak"].isin([2, 3]) & (u["gm_q"] >= 0.55) & (u["true_gmsga"] >= 0.10),
                ),
            ]
            for pnl, sc, sd, m in lifecycle_slices:
                r = eval_g07_slice(u[m], univ_name, p_name, pnl, sc, sd)
                r["record_type"] = "COHORT_STAT"
                stat_rows.append(r)

    stat_df = pd.DataFrame(stat_rows)
    stat_df["bh_q_val_252d"] = benjamini_hochberg_fdr(stat_df["p_val_252d"].values)
    stat_df["bh_q_val_756d"] = benjamini_hochberg_fdr(stat_df["p_val_756d"].values)

    # Panel 3C: Extract 18 Exact Zero-Lookahead PIT Historical Cases
    case_specs = [
        # (case_id, case_category, ticker, target_end, note)
        ("C01_Success_Biotech_Breakthrough", "成功大牛：研发型商业化突破(FCF已正+GAAP微亏)", "VRTX", "2012-06-30", "Kalydeco获批放量首季毛销差跃升至+46.9%且FCF转正"),
        ("C02_Success_Biotech_SustainedTurn", "成功大牛：Orkambi放量扭亏确认", "VRTX", "2016-12-31", "毛利率87%+毛销差63%+FCF正循环开启长牛且回撤仅17%"),
        ("C03_Success_Biotech_RDBurnTo10x", "成功大牛：超高毛利研发型亏损前夜", "REGN", "2011-12-31", "Eylea放量前夕GM 97.6%+毛销差+68.0%但研发致OPM负36.9%"),
        ("C04_Success_EV_MfgTurnaround", "成功大牛：制造业毛销差刚跨+10%扭亏临界", "TSLA", "2013-06-30", "Model S爬坡使毛利率升至24.8%且毛销差首跨+10.0%"),
        ("C05_Success_SaaS_MicroLossGMSGA", "成功大牛：SaaS微亏前半程+毛销差+48%", "NOW", "2013-09-30", "GAAP微亏OPM负13.2%但GM 62.6%+毛销差+48.1%+营收增73%"),
        ("C06_Success_Cyber_SelfFundMicroLoss", "成功大牛：网安微亏前半程+自造血无限跑道", "PANW", "2013-10-31", "OPM负5.5%微亏临界+GM 73.6%+毛销差+62.6%+FCF正9620万"),
        ("C07_Success_Cloud_SelfFundMicroLoss", "成功大牛：云安全微亏前半程+自造血无限跑道", "ZS", "2019-07-31", "OPM负9.2%微亏前半程+GM 79.9%+毛销差+68.1%+FCF正3250万"),
        ("C08_Success_Diag_GMSGA10Cross", "成功标杆①：毛销差首跨+10%突破前哨买点", "NTRA", "2024-06-30", "Signatera放量使毛销差首跨+10%(+10.94%)且OPM收窄至负10.6%"),
        ("C09_Success_Diag_FCFSelfFund", "成功标杆②：微亏期FCF转正自造血重仓买点", "NTRA", "2024-12-31", "毛利率升至62.9%+毛销差+13.6%+TTM自由现金流转正随后市值翻倍"),
        ("C10_Success_AdTech_MarginExplode", "成功大牛：高利率期毛销差扩张扭亏30倍股", "APP", "2022-09-30", "AXON升级前夕毛销差+24.0%+FCF正3.34亿+股本负稀释"),
        ("C11_Success_ConsumerSaaS_PreGAAP", "成功标杆①：商业化突破高毛销差亏损收窄买点", "DUOL", "2022-09-30", "GM 72.6%+毛销差+41.2%+营收增51%开启扭亏前翻倍主升浪"),
        ("C12_Success_ConsumerSaaS_GAAP3Q", "成功标杆②：GAAP连续扭亏满3季确认主升浪", "DUOL", "2024-03-31", "GAAP连续盈利第3季OPM跃升至+9.8%+毛销差+52.1%+FCF破2亿"),
        ("C13_Success_AISaaS_GAAP1stQ", "成功大牛：GAAP净利首季转正+自造血无限跑道", "PLTR", "2022-12-31", "OPM负3.5%临界+GAAP净利首季转正+毛销差+50.0%+FCF正1.84亿"),
        ("C14_Success_Diag_GMSGAJump", "历史兑现节点：毛销差跃升跨过+40%拐点", "GH", "2025-06-30", "GM跃升至65.0%+毛销差+43.4%驱动1年超额+266%"),
        ("C15_LiveNode_Diag_2026Q3_Step1", "当前实盘节点(2026Q3)：毛销差+40.2%但FCF仍负观察区", "GH", "2026-09-30", "GM 65.4%+毛销差+40.2%+现金10.3亿(跑道4.4年)待OCF转正重仓门"),
        ("C16_LiveWatch_PreRev_LongRunway", "当前跟踪原型：长跑道无商业化单位经济期权", "OKLO", "2026-06-30", "现金16.4亿美元(跑道5.96年)但毛销差深度为负仍处纯期权左侧"),
        ("C17_Fail_LongCash_NegUE_Halved", "失败反例：百亿现金跑道但负毛销差照样腰斩", "RIVN", "2022-09-30", "账上132.7亿美元现金但毛销差负246.6%致1年跌51%/3年跑输131%"),
        ("C18_Fail_Bankrupt_DeathGate", "破产反例：负毛销差+短跑道+高稀释破产归零", "NVTA", "2022-06-30", "毛销差负19.5%+现金跑道仅0.44年最终2024年2月Chapter11归零"),
    ]

    def fmt_pct_4q(r_row, c3, c2, c1, c0):
        vals = [r_row.get(c3, np.nan), r_row.get(c2, np.nan), r_row.get(c1, np.nan), r_row.get(c0, np.nan)]
        parts = [f"{v * 100:+.1f}%" if pd.notna(v) else "NA" for v in vals]
        return " -> ".join(parts)

    case_rows = []
    for cid, ccat, tk, tgt_end, cnote in case_specs:
        tk_df = df_all[df_all["ticker"] == tk].copy()
        if len(tk_df) == 0:
            continue
        exact = tk_df[tk_df["end"] == tgt_end]
        if len(exact) == 0:
            # Pick nearest end date within 60 days
            diffs = (pd.to_datetime(tk_df["end"]) - pd.Timestamp(tgt_end)).abs()
            if diffs.min().days <= 75:
                row_s = tk_df.loc[diffs.idxmin()]
            else:
                continue
        else:
            row_s = exact.iloc[0]

        rw_str = (
            "SelfFunding_FCF>=0"
            if (pd.notna(row_s["fcf_ttm"]) and row_s["fcf_ttm"] >= 0)
            else (f"{row_s['runway_years']:.2f}Y" if pd.notna(row_s["runway_years"]) else "NA")
        )
        case_rows.append({
            "record_type": "HISTORICAL_CASE",
            "universe": "MidLarge_ge5B" if (pd.notna(row_s["mcap_2026_equiv_b"]) and row_s["mcap_2026_equiv_b"] >= 5.0) else "Sub5B_Ref",
            "subperiod": str(row_s.get("era_regime", "")),
            "panel": "3C_PIT_Historical_Cases",
            "slice_code": cid,
            "slice_desc": f"{ccat} | {cnote}",
            "case_ticker": tk,
            "case_company": str(row_s.get("name", tk)),
            "case_fiscal_end": str(row_s["end"]),
            "case_filed_date": str(row_s["filed"]),
            "case_entry_date": str(pd.Timestamp(row_s["entry_date"]).strftime("%Y-%m-%d")),
            "case_mcap_2026_equiv_b": round(float(row_s["mcap_2026_equiv_b"]), 2) if pd.notna(row_s["mcap_2026_equiv_b"]) else np.nan,
            "case_gm_q": round(float(row_s["gm_q"]), 4) if pd.notna(row_s["gm_q"]) else np.nan,
            "case_sga_ratio_q": round(float(row_s["sga_ratio_q"]), 4) if pd.notna(row_s["sga_ratio_q"]) else np.nan,
            "case_rd_ratio_q": round(float(row_s["rd_ratio_q"]), 4) if pd.notna(row_s["rd_ratio_q"]) else np.nan,
            "case_true_gmsga_q": round(float(row_s["true_gmsga"]), 4) if pd.notna(row_s["true_gmsga"]) else np.nan,
            "case_opm_q": round(float(row_s["opm_q"]), 4) if pd.notna(row_s["opm_q"]) else np.nan,
            "case_rev_yoy": round(float(row_s["rev_yoy"]), 4) if pd.notna(row_s["rev_yoy"]) else np.nan,
            "case_fcf_ttm_m": round(float(row_s["fcf_ttm"]) / 1e6, 1) if pd.notna(row_s["fcf_ttm"]) else np.nan,
            "case_cash_m": round(float(row_s["cash"]) / 1e6, 1) if pd.notna(row_s["cash"]) else np.nan,
            "case_runway_status": rw_str,
            "case_dilution_yoy": round(float(row_s["dil_pit"]), 4) if pd.notna(row_s["dil_pit"]) else np.nan,
            "case_gmsga_4q_traj": fmt_pct_4q(row_s, "true_gmsga_lag3", "true_gmsga_lag2", "true_gmsga_lag1", "true_gmsga"),
            "case_opm_4q_traj": fmt_pct_4q(row_s, "opm_lag3_seq", "opm_lag2_seq", "opm_lag1_seq", "opm_q"),
            "qtr_ew_ret_252d": row_s.get("fwd_252d", np.nan),
            "qtr_ew_alpha_252d": row_s.get("alpha_fwd_252d", np.nan),
            "qtr_ew_alpha_504d": row_s.get("alpha_fwd_504d", np.nan),
            "qtr_ew_ret_756d": row_s.get("fwd_756d", np.nan),
            "qtr_ew_alpha_756d": row_s.get("alpha_fwd_756d", np.nan),
            "med_mdd_1y": row_s.get("fwd_max_dd_252d", np.nan),
        })

    cases_df = pd.DataFrame(case_rows)
    out_df = pd.concat([stat_df, cases_df], ignore_index=True)
    return out_df


def main():
    t_all = time.time()
    df = load_full_pit_panel()

    t1_df = build_table_1_loss_spectrum(df)
    p1 = os.path.join(OUT_DIR, "table_g07_loss_spectrum_rd_vs_sga.csv")
    t1_df.to_csv(p1, index=False)
    print(f"[1/3] Saved {p1} ({len(t1_df)} rows)")

    t2_df = build_table_2_runway_and_dilution(df)
    p2 = os.path.join(OUT_DIR, "table_g07_runway_and_dilution.csv")
    t2_df.to_csv(p2, index=False)
    print(f"[2/3] Saved {p2} ({len(t2_df)} rows)")

    t3_df = build_table_3_turnaround_timing_and_cases(df)
    p3 = os.path.join(OUT_DIR, "table_g07_turnaround_timing_and_cases.csv")
    t3_df.to_csv(p3, index=False)
    print(f"[3/3] Saved {p3} ({len(t3_df)} rows, including {(t3_df['record_type']=='HISTORICAL_CASE').sum()} PIT cases)")
    print(f"[G07 DONE] Total time: {time.time() - t_all:.2f}s")


if __name__ == "__main__":
    main()

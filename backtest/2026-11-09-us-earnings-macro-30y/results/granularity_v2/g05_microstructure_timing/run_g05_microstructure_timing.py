#!/usr/bin/env python3
"""
run_g05_microstructure_timing.py
G05: Earnings-Day Volume/Candle Microstructure & Post-Earnings D+1..D+20 Entry Timing Actuarial Engine
30-Year US Stock Selection Joint Backtest (SEC XBRL PIT 2009-2026 + Unified OHLCV + Delisted Splicing)

Strict Zero-Lookahead & Anti-Bias Guarantees:
1. 100% Zero-Lookahead Entry:
   - All SEC XBRL fundamental features (filed = idx_filed) and reaction-window OHLCV (idx_filed, idx_filed+1,
     or prior 8-K reaction day within [max(end+5, idx_filed-8), idx_filed+1]) are strictly realized <= idx_d1
     (entry_date = idx_filed + 1 close).
   - Every entry (unconditional D+1..D+20 or conditional candle/pullback trigger) executes strictly at the
     closing price of day D+k (k >= 1), NEVER using intraday low, intraday limit-fill assumption, or future highs.
2. Zero Survivorship Bias:
   - Integrates delisted daily OHLCV (delisted_prices_0/1.parquet) and terminal bankruptcy/M&A residual returns
     (terminal_rets from PriceEngine & delisted_meta) across all forward horizons (5d to 756d).
3. D15 Compliance:
   - Reports Calendar-Quarter Equal-Weight Net Excess vs SPY (qtr_ew_alpha), 250-day per-ticker cooldown
     deduplicated Mean/Median Net Excess vs SPY, Win Rate vs SPY, Real Payoff Ratio, Ex-2020-2021 Bubble,
     Last 10Y (2016-2026), and High-Rate Era (2022-2026) subperiod splits.
   - For conditional triggers, simultaneously reports Fill Rate, Miss Rate, Missed-Trades D+1 Alpha,
     Triggered-Only Net Excess, and All-Intentions (0% alpha on missed trades) Net Excess.
"""

import os
import sys
import json
import time
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from scipy import stats

PROJ_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-09-us-earnings-macro-30y"
DATA_XBRL = os.path.join(PROJ_DIR, "data/xbrl_master_pit_2009_2026.parquet")
DATA_PX = "/tmp/us_earn_macro_bt_20261109/unified_prices_and_bench.parquet"
CACHE_NPZ = "/tmp/us_earn_macro_bt_20261109/price_engine_cache.npz"
DELIST_DIR = "/tmp/us_earn_macro_bt_20261109/delisted_prices"
OUT_DIR = os.path.join(PROJ_DIR, "results/granularity_v2/g05_microstructure_timing")

sys.path.insert(0, os.path.join(PROJ_DIR, "scripts"))
from backtest_stats_lib import deduplicate_cooldown, benjamini_hochberg_fdr

DEDUP_DAYS = 250


def build_ohlcv_and_delisted_engine():
    """
    Loads PriceEngine base grid and overlays full daily Open/High/Low/Close/Volume from
    unified_prices_and_bench.parquet plus delisted_prices_0/1.parquet for 100% OHLCV & survivorship coverage.
    """
    t0 = time.time()
    print("[1/5] Building unified zero-survivorship OHLCV matrix...")
    pe_npz = np.load(CACHE_NPZ, allow_pickle=True)
    dates = pe_npz["dates"]
    dates_ts = pd.to_datetime(dates)
    n_days = len(dates)
    dt_to_row = {pd.Timestamp(d).normalize(): i for i, d in enumerate(dates)}

    base_tickers = list(pe_npz["tickers"])
    base_set = set(base_tickers)

    # Load delisted metadata & daily OHLCV
    supp_dfs = []
    for fn in ("delisted_prices_0.parquet", "delisted_prices_1.parquet"):
        p = os.path.join(DELIST_DIR, fn)
        if os.path.exists(p):
            dp = pd.read_parquet(p)
            dp["date"] = pd.to_datetime(dp["date"]).dt.tz_localize(None).dt.normalize()
            keep_c = [c for c in ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume"] if c in dp.columns]
            supp_dfs.append(dp[keep_c])

    df_supp = pd.concat(supp_dfs, ignore_index=True) if supp_dfs else pd.DataFrame()
    if len(df_supp) > 0:
        df_supp = df_supp[~df_supp["ticker"].isin(base_set) & df_supp["date"].isin(dt_to_row)].copy()
        df_supp = df_supp.sort_values(["ticker", "date"]).drop_duplicates(["ticker", "date"], keep="last")
        new_tickers = sorted(df_supp["ticker"].unique().tolist())
    else:
        new_tickers = []

    all_tickers = base_tickers + new_tickers
    n_base = len(base_tickers)
    n_new = len(new_tickers)
    n_stocks = len(all_tickers)
    tk_to_col = {tk: i for i, tk in enumerate(all_tickers)}

    # Allocate matrices
    P_adj = np.full((n_days, n_stocks), np.nan, dtype=np.float32)
    O_raw = np.full((n_days, n_stocks), np.nan, dtype=np.float32)
    H_raw = np.full((n_days, n_stocks), np.nan, dtype=np.float32)
    L_raw = np.full((n_days, n_stocks), np.nan, dtype=np.float32)
    C_raw = np.full((n_days, n_stocks), np.nan, dtype=np.float32)
    VOL   = np.full((n_days, n_stocks), np.nan, dtype=np.float32)

    P_adj[:, :n_base] = pe_npz["P_adj"]
    VOL[:, :n_base]   = pe_npz["VOL"]

    last_valid_idx = np.full(n_stocks, -1, dtype=np.int32)
    last_valid_idx[:n_base] = pe_npz["last_valid_idx"]

    terminal_rets = np.zeros(n_stocks, dtype=np.float32)
    terminal_rets[:n_base] = pe_npz["terminal_rets"]

    # Overlay base OHLC from unified_prices_and_bench.parquet
    px = pd.read_parquet(DATA_PX, columns=["date", "ticker", "open", "high", "low", "close", "adj_close", "volume"])
    px_sub = px[px["ticker"].isin(base_set)].copy()
    r_idx = px_sub["date"].map(dt_to_row).values
    c_idx = px_sub["ticker"].map(tk_to_col).values
    ok = pd.notna(r_idx) & pd.notna(c_idx)
    px_sub = px_sub[ok]
    r_i = r_idx[ok].astype(np.int32)
    c_i = c_idx[ok].astype(np.int32)

    O_raw[r_i, c_i] = px_sub["open"].values.astype(np.float32)
    H_raw[r_i, c_i] = px_sub["high"].values.astype(np.float32)
    L_raw[r_i, c_i] = px_sub["low"].values.astype(np.float32)
    C_raw[r_i, c_i] = px_sub["close"].values.astype(np.float32)

    # Overlay delisted supplement OHLCV & terminal returns
    if n_new > 0:
        dm_list = []
        for fn in ("delisted_meta_0.parquet", "delisted_meta_1.parquet"):
            p = os.path.join(DELIST_DIR, fn)
            if os.path.exists(p):
                dm_list.append(pd.read_parquet(p))
        dm_all = pd.concat(dm_list, ignore_index=True) if dm_list else pd.DataFrame()
        t_map = {}
        for _, r in dm_all.iterrows():
            tk = str(r["ticker"]).strip()
            et = str(r.get("exit_type", ""))
            tr_v = float(r["terminal_delist_ret"]) if pd.notna(r.get("terminal_delist_ret", np.nan)) else (
                -0.95 if et == "BANKRUPTCY_OR_LIQUIDATION" else 0.0
            )
            t_map[tk] = tr_v

        r_s = df_supp["date"].map(dt_to_row).values.astype(np.int32)
        c_s = df_supp["ticker"].map(tk_to_col).values.astype(np.int32)
        P_adj[r_s, c_s] = df_supp["adj_close"].values.astype(np.float32)
        C_raw[r_s, c_s] = df_supp["close"].values.astype(np.float32)
        if "open" in df_supp.columns:
            O_raw[r_s, c_s] = df_supp["open"].values.astype(np.float32)
            H_raw[r_s, c_s] = df_supp["high"].values.astype(np.float32)
            L_raw[r_s, c_s] = df_supp["low"].values.astype(np.float32)
        if "volume" in df_supp.columns:
            VOL[r_s, c_s] = df_supp["volume"].values.astype(np.float32)

        for tk in new_tickers:
            col = tk_to_col[tk]
            vm = ~np.isnan(P_adj[:, col]) & (P_adj[:, col] > 0)
            if np.any(vm):
                last_valid_idx[col] = int(np.where(vm)[0][-1])
            terminal_rets[col] = float(t_map.get(tk, 0.0))

    # Split- and dividend-consistent adjusted OHLC (exact intraday geometry preserved)
    adj_mult = np.where((C_raw > 0) & (P_adj > 0), P_adj / C_raw, np.nan)
    O_adj = (O_raw * adj_mult).astype(np.float32)
    H_adj = (H_raw * adj_mult).astype(np.float32)
    L_adj = (L_raw * adj_mult).astype(np.float32)

    spy_tr = pe_npz["spy_tr"].astype(np.float64)

    print(
        f"  OHLCV Engine ready in {time.time() - t0:.2f}s: {n_stocks:,} stocks ({n_base:,} base + {n_new:,} delisted) x {n_days:,} trading days."
    )
    return {
        "dates": dates,
        "dates_ts": dates_ts,
        "n_days": n_days,
        "dt_to_row": dt_to_row,
        "tickers": all_tickers,
        "tk_to_col": tk_to_col,
        "O_raw": O_raw,
        "H_raw": H_raw,
        "L_raw": L_raw,
        "C_raw": C_raw,
        "O_adj": O_adj,
        "H_adj": H_adj,
        "L_adj": L_adj,
        "P_adj": P_adj,
        "VOL": VOL,
        "spy_tr": spy_tr,
        "last_valid_idx": last_valid_idx,
        "terminal_rets": terminal_rets,
    }


def prepare_events_with_microstructure(eng: dict) -> pd.DataFrame:
    """
    Loads SEC XBRL PIT panel, rescues any unpriced delisted events, and extracts zero-lookahead
    earnings-day candle & volume microstructure features strictly realized on or before entry_date (D+1 close).
    """
    t0 = time.time()
    print("[2/5] Preparing PIT XBRL events & earnings-day candle/volume microstructure...")
    df = pd.read_parquet(DATA_XBRL)

    dates = eng["dates"]
    dates_ts = eng["dates_ts"]
    n_days = eng["n_days"]
    tk_to_col = eng["tk_to_col"]
    O_raw, H_raw, L_raw, C_raw = eng["O_raw"], eng["H_raw"], eng["L_raw"], eng["C_raw"]
    O_adj, H_adj, L_adj, P_adj = eng["O_adj"], eng["H_adj"], eng["L_adj"], eng["P_adj"]
    VOL = eng["VOL"]

    s_col = np.array([tk_to_col.get(str(t), -1) for t in df["ticker"].values], dtype=np.int32)
    f_idx = np.searchsorted(dates, pd.to_datetime(df["filed"]).dt.normalize().values.astype("datetime64[D]"))
    f_idx = np.clip(f_idx, 0, n_days - 1)
    e_idx = f_idx + 1
    end_idx = np.searchsorted(dates, pd.to_datetime(df["end"]).dt.normalize().values.astype("datetime64[D]"))

    # Rescue delisted rows where entry_date / earn_jump_ret was missing in base table
    rescue_mask = df["entry_date"].isna() & (s_col >= 0) & (f_idx >= 1) & (e_idx < n_days)
    if rescue_mask.any():
        r_ix = np.where(rescue_mask)[0]
        p_pre = P_adj[f_idx[r_ix] - 1, s_col[r_ix]]
        p_ent = P_adj[e_idx[r_ix], s_col[r_ix]]
        ok_r = (~np.isnan(p_pre)) & (p_pre > 0) & (~np.isnan(p_ent)) & (p_ent > 0)
        r_ok = r_ix[ok_r]
        if len(r_ok) > 0:
            df.loc[r_ok, "pre_date"] = dates_ts.values[f_idx[r_ok] - 1]
            df.loc[r_ok, "entry_date"] = dates_ts.values[e_idx[r_ok]]
            df.loc[r_ok, "pre_adj_close"] = p_pre[ok_r]
            df.loc[r_ok, "entry_adj_close"] = p_ent[ok_r]
            df.loc[r_ok, "earn_jump_ret"] = p_ent[ok_r] / p_pre[ok_r] - 1.0
            # Backfill mcap_2026_equiv_b if missing using shares_clean * close * mcap_scale_to_2026
            c_ent_raw = C_raw[e_idx[r_ok], s_col[r_ok]]
            mcap_est = (c_ent_raw * df.loc[r_ok, "shares_clean"].values) / 1e9
            df.loc[r_ok, "mcap_usd_b"] = np.where(df.loc[r_ok, "mcap_usd_b"].notna(), df.loc[r_ok, "mcap_usd_b"], mcap_est)
            df.loc[r_ok, "mcap_2026_equiv_b"] = np.where(
                df.loc[r_ok, "mcap_2026_equiv_b"].notna(),
                df.loc[r_ok, "mcap_2026_equiv_b"],
                df.loc[r_ok, "mcap_usd_b"] * df.loc[r_ok, "mcap_scale_to_2026"].fillna(1.5),
            )
            df.loc[r_ok, "ps_pit"] = np.where(
                df.loc[r_ok, "ps_pit"].notna(),
                df.loc[r_ok, "ps_pit"],
                np.where(df.loc[r_ok, "rev_ttm"] > 0, (df.loc[r_ok, "mcap_usd_b"] * 1e9) / df.loc[r_ok, "rev_ttm"], np.nan),
            )
            print(f"  Rescued {len(r_ok):,} delisted filing events into zero-survivorship sample.")

    # Filter valid events with clean price & sufficient prior 20-day volume history
    valid = (
        (~df["has_anomaly_break"].fillna(False))
        & df["earn_jump_ret"].notna()
        & df["entry_date"].notna()
        & (s_col >= 0)
        & (f_idx >= 32)
        & (e_idx < n_days - 5)
    )
    d = df[valid].copy().reset_index(drop=True)
    f_idx = f_idx[valid]
    e_idx = e_idx[valid]
    end_idx = end_idx[valid]
    s_col = s_col[valid]

    d["f_idx"] = f_idx
    d["e_idx"] = e_idx
    d["s_col"] = s_col

    # -------------------------------------------------------------------------
    # A. Filing-Window Reaction Day D0 in {f_idx, f_idx+1} (100% <= e_idx!)
    #    Handles BMO / prior-night AMC filings (reacting on f_idx) vs filing-day AMC (reacting on f_idx+1)
    # -------------------------------------------------------------------------
    vol_hist_20 = np.stack([VOL[f_idx - k, s_col] for k in range(1, 21)], axis=0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        v_ma20_f = np.nanmean(vol_hist_20, axis=0)

    prev0 = P_adj[f_idx - 1, s_col]
    prev1 = P_adj[f_idx, s_col]
    tr0 = (np.maximum(H_adj[f_idx, s_col], prev0) - np.minimum(L_adj[f_idx, s_col], prev0)) / np.where(prev0 > 0, prev0, np.nan)
    tr1 = (np.maximum(H_adj[f_idx + 1, s_col], prev1) - np.minimum(L_adj[f_idx + 1, s_col], prev1)) / np.where(prev1 > 0, prev1, np.nan)
    vm0 = VOL[f_idx, s_col] / np.where(v_ma20_f > 0, v_ma20_f, np.nan)
    vm1 = VOL[f_idx + 1, s_col] / np.where(v_ma20_f > 0, v_ma20_f, np.nan)

    imp0 = np.nan_to_num(tr0, 0.0) * np.sqrt(np.clip(np.nan_to_num(vm0, 1.0), 0.25, 25.0))
    imp1 = np.nan_to_num(tr1, 0.0) * np.sqrt(np.clip(np.nan_to_num(vm1, 1.0), 0.25, 25.0))
    is_amc = imp1 > imp0
    d0_idx = np.where(is_amc, f_idx + 1, f_idx)

    # -------------------------------------------------------------------------
    # B. Full 8-K + 10-Q Earnings Window Reaction Day in [max(end+5, f_idx-8) .. f_idx+1]
    #    Captures companies releasing 8-K earnings 1-8 trading days prior to 10-Q filing,
    #    while STILL entering strictly at e_idx = f_idx + 1 close (zero lookahead!).
    # -------------------------------------------------------------------------
    offsets = list(range(-8, 2))
    vol_mat = np.stack([VOL[f_idx + k, s_col] for k in offsets], axis=1)
    prev_mat = np.stack([P_adj[f_idx + k - 1, s_col] for k in offsets], axis=1)
    hi_mat = np.stack([H_adj[f_idx + k, s_col] for k in offsets], axis=1)
    lo_mat = np.stack([L_adj[f_idx + k, s_col] for k in offsets], axis=1)
    tr_mat = (np.maximum(hi_mat, prev_mat) - np.minimum(lo_mat, prev_mat)) / np.where(prev_mat > 0, prev_mat, np.nan)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        v_base8k = np.nanmean(np.stack([VOL[f_idx - 8 - k, s_col] for k in range(1, 21)], axis=0), axis=0)

    vm_mat = vol_mat / np.where(v_base8k[:, None] > 0, v_base8k[:, None], np.nan)
    day_mat = f_idx[:, None] + np.array(offsets)[None, :]
    score_8k = np.where(
        day_mat > (end_idx[:, None] + 4),
        np.nan_to_num(tr_mat, 0.0) * np.sqrt(np.clip(np.nan_to_num(vm_mat, 1.0), 0.25, 25.0)),
        -1.0,
    )
    best_j = np.argmax(score_8k, axis=1)
    d8k_idx = f_idx + np.array(offsets)[best_j]

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        v_ma20_8k = np.nanmean(np.stack([VOL[d8k_idx - k, s_col] for k in range(1, 21)], axis=0), axis=0)

    for prefix, r_day, v20 in [("d0", d0_idx, v_ma20_f), ("d8k", d8k_idx, v_ma20_8k)]:
        pc = P_adj[r_day - 1, s_col]
        op = O_adj[r_day, s_col]
        hi = H_adj[r_day, s_col]
        lo = L_adj[r_day, s_col]
        cl = P_adj[r_day, s_col]
        sp_raw = H_raw[r_day, s_col] - L_raw[r_day, s_col]

        d[f"{prefix}_idx"] = r_day
        d[f"{prefix}_vol_ma20"] = v20
        d[f"{prefix}_vol_mult"] = VOL[r_day, s_col] / np.where(v20 > 0, v20, np.nan)
        d[f"{prefix}_clv"] = np.where(sp_raw > 1e-8, (C_raw[r_day, s_col] - L_raw[r_day, s_col]) / sp_raw, 0.5)
        d[f"{prefix}_open_gap"] = op / np.where(pc > 0, pc, np.nan) - 1.0
        d[f"{prefix}_high_ret"] = hi / np.where(pc > 0, pc, np.nan) - 1.0
        d[f"{prefix}_low_ret"] = lo / np.where(pc > 0, pc, np.nan) - 1.0
        d[f"{prefix}_close_ret"] = cl / np.where(pc > 0, pc, np.nan) - 1.0
        d[f"{prefix}_body_ret"] = cl / np.where(op > 0, op, np.nan) - 1.0
        d[f"{prefix}_fade_from_high"] = cl / np.where(hi > 0, hi, np.nan) - 1.0
        d[f"{prefix}_prev_close_adj"] = pc
        d[f"{prefix}_low_adj"] = lo

    # Volume bins & CLV bins on d0
    vm = d["d0_vol_mult"]
    d["vol_bin"] = np.select(
        [vm < 1.5, (vm >= 1.5) & (vm < 2.5), (vm >= 2.5) & (vm < 4.0), vm >= 4.0],
        ["V1_lt1.5x", "V2_1.5to2.5x", "V3_2.5to4.0x", "V4_ge4.0x_Climax"],
        default="Missing",
    )
    clv = d["d0_clv"]
    d["clv_bin"] = np.select(
        [clv < 0.25, (clv >= 0.25) & (clv < 0.75), clv >= 0.75],
        ["C1_lt0.25_LowClose_GravestoneOrShavedRed", "C2_0.25to0.75_MidClose", "C3_ge0.75_HighClose_MarubozuOrHammer"],
        default="Missing",
    )

    # Canonical True Acceleration Flag (aligned with M3 F1 | F3)
    # F1: >=3 consecutive quarters of revenue acceleration + OPM expansion (rev_yoy >= 5%)
    # F3: Early/unprofitable commercial inflectors with GM - SGA >= 10% expanding YoY (rev_yoy >= 5%)
    cond_f1 = (d["consec_double_inflect_n"] >= 3) & (d["rev_yoy"] >= 0.05)
    cond_f3 = (
        ((d["ni_ttm"] <= 0) | (d["opinc_ttm"] <= 0))
        & (d["gm_minus_sga_q"] >= 0.10)
        & (d["gm_sga_yoy_chg"] > 0)
        & (d["rev_yoy"] >= 0.05)
    )
    d["is_true_acc"] = cond_f1 | cond_f3

    # Subperiod boolean masks for D15 verification
    dt_ent = pd.to_datetime(d["entry_date"])
    d["is_ex_bubble"] = ~((dt_ent >= "2020-03-01") & (dt_ent <= "2021-12-31"))
    d["is_last_10y"] = dt_ent >= "2016-01-01"
    d["is_high_rate_22_26"] = dt_ent >= "2022-01-01"

    print(
        f"  Prepared {len(d):,} clean events (TrueAcc={d['is_true_acc'].sum():,}, Mcap>=15B={(d['mcap_2026_equiv_b']>=15).sum():,}, Mcap>=25B={(d['mcap_2026_equiv_b']>=25).sum():,}) in {time.time() - t0:.2f}s."
    )
    return d


def compute_forward_returns_from_entries(eng: dict, ent_idx_arr: np.ndarray, s_col_arr: np.ndarray, horizons=(5, 10, 21, 63, 126, 252, 756)):
    """
    Computes exact zero-lookahead forward stock returns and net excess returns vs SPY
    starting strictly from each event's realized entry close index ent_idx_arr[i],
    with full delisting terminal return splicing.
    """
    P_adj = eng["P_adj"]
    spy_tr = eng["spy_tr"]
    last_valid_idx = eng["last_valid_idx"]
    terminal_rets = eng["terminal_rets"]
    n_days = eng["n_days"]
    n = len(ent_idx_arr)

    out_ret = {h: np.full(n, np.nan, dtype=np.float64) for h in horizons}
    out_alp = {h: np.full(n, np.nan, dtype=np.float64) for h in horizons}

    for i in range(n):
        de = int(ent_idx_arr[i])
        if de < 0 or de >= n_days:
            continue
        c = int(s_col_arr[i])
        p0 = float(P_adj[de, c])
        if np.isnan(p0) or p0 <= 0:
            continue
        spy0 = float(spy_tr[de])
        if np.isnan(spy0) or spy0 <= 0:
            continue
        l_idx = int(last_valid_idx[c])
        t_ret = float(terminal_rets[c])

        for h in horizons:
            dtgt = de + h
            if l_idx < dtgt and l_idx < n_days - 15 and l_idx >= de:
                p_last = float(P_adj[l_idx, c])
                r_last = (p_last / p0 - 1.0) if (not np.isnan(p_last) and p_last > 0) else -1.0
                rtot = (1.0 + r_last) * (1.0 + t_ret) - 1.0
                d_spy = min(dtgt, n_days - 1)
                sr = float(spy_tr[d_spy]) / spy0 - 1.0
                out_ret[h][i] = rtot
                out_alp[h][i] = rtot - sr
            elif dtgt < n_days:
                pt = float(P_adj[dtgt, c])
                if not np.isnan(pt) and pt > 0:
                    rs = pt / p0 - 1.0
                    sr = float(spy_tr[dtgt]) / spy0 - 1.0
                    out_ret[h][i] = rs
                    out_alp[h][i] = rs - sr

    return out_ret, out_alp


def summarize_entry_metrics(
    sub_raw: pd.DataFrame,
    ent_raw: np.ndarray,
    eng: dict,
    horizons=(63, 126, 252, 756),
    d1_alp_252_raw: np.ndarray = None,
) -> dict:
    """
    Computes full D15-compliant metrics for an entry rule (unconditional or conditional):
    - Applies 250-day per-ticker cooldown deduplication on the signal cohort
    - Computes Fill Rate, Miss Rate, Entry Price Diff vs D+1 Close
    - Computes Calendar-Quarter Equal-Weight Alpha, Deduplicated Mean/Median Alpha, Win Rate, Payoff Ratio
    - Computes Ex-2020-2021 Bubble, Last 10Y (2016-2026), and High-Rate (2022-2026) 1Y Win Rate & Median Alpha
    - Computes All-Intentions Alpha (assigning 0.0 net excess to missed conditional signals) & Missed-Signal D+1 Alpha
    """
    P_adj = eng["P_adj"]
    n_days = eng["n_days"]
    res = {"n_signals_raw": int(len(sub_raw))}
    if len(sub_raw) == 0:
        return res

    work = sub_raw[
        ["ticker", "entry_date", "e_idx", "s_col", "is_ex_bubble", "is_last_10y", "is_high_rate_22_26"]
    ].copy()
    work["trig_idx"] = ent_raw
    work["filled"] = (ent_raw >= 0) & (ent_raw < n_days)
    work["cal_qtr"] = pd.to_datetime(work["entry_date"]).dt.to_period("Q")

    ret_d, alp_d = compute_forward_returns_from_entries(eng, ent_raw, work["s_col"].values, horizons=horizons)
    for h in horizons:
        work[f"ret_{h}d"] = ret_d[h]
        work[f"alp_{h}d"] = alp_d[h]

    if d1_alp_252_raw is not None:
        work["d1_alp_252d"] = d1_alp_252_raw

    # Entry price improvement / slippage vs D+1 close (negative = cheaper entry than D+1, positive = higher entry than D+1)
    e_base = work["e_idx"].values
    c_arr = work["s_col"].values
    p_d1 = P_adj[e_base, c_arr]
    p_ent = np.where(work["filled"].values, P_adj[np.clip(ent_raw, 0, n_days - 1), c_arr], np.nan)
    work["entry_px_vs_d1"] = p_ent / np.where(p_d1 > 0, p_d1, np.nan) - 1.0
    work["entry_day_k"] = np.where(work["filled"].values, ent_raw - e_base + 1, np.nan)

    ded = deduplicate_cooldown(work, date_col="entry_date", cooldown_days=DEDUP_DAYS)
    n_ded = len(ded)
    res["n_signals_dedup"] = int(n_ded)
    if n_ded == 0:
        return res

    fill_mask_ded = ded["filled"].values
    res["n_filled_dedup"] = int(fill_mask_ded.sum())
    res["fill_rate"] = float(fill_mask_ded.mean())
    res["miss_rate"] = float(1.0 - fill_mask_ded.mean())
    res["med_entry_day_k"] = float(np.nanmedian(ded["entry_day_k"].values)) if fill_mask_ded.any() else np.nan
    res["med_entry_px_vs_d1"] = float(np.nanmedian(ded["entry_px_vs_d1"].values)) if fill_mask_ded.any() else np.nan
    res["mean_entry_px_vs_d1"] = float(np.nanmean(ded["entry_px_vs_d1"].values)) if fill_mask_ded.any() else np.nan

    if d1_alp_252_raw is not None:
        missed_d1 = ded.loc[~ded["filled"], "d1_alp_252d"].dropna().values
        res["missed_trades_d1_mean_alpha_252d"] = float(np.mean(missed_d1)) if len(missed_d1) > 0 else np.nan
        res["missed_trades_d1_med_alpha_252d"] = float(np.median(missed_d1)) if len(missed_d1) > 0 else np.nan

    for h in horizons:
        ac = f"alp_{h}d"
        rc = f"ret_{h}d"

        # 1. Triggered trades metrics
        valid_raw = work[work["filled"]].dropna(subset=[ac])
        valid_ded = ded[ded["filled"]].dropna(subset=[ac])
        res[f"n_trig_{h}d"] = int(len(valid_ded))

        if len(valid_ded) >= 3:
            q_means = valid_raw.groupby("cal_qtr")[ac].mean()
            q_ew = float(q_means.mean())
            q_se = float(q_means.std(ddof=1) / np.sqrt(len(q_means))) if len(q_means) > 2 else np.nan
            t_st = q_ew / q_se if (q_se and q_se > 0) else np.nan
            p_vl = float(2 * (1 - stats.t.cdf(abs(t_st), df=max(len(q_means) - 1, 1)))) if pd.notna(t_st) else np.nan

            av = valid_ded[ac].values
            rv = valid_ded[rc].values
            pos_a = av[av > 0]
            neg_a = av[av <= 0]
            payoff = float(pos_a.mean() / abs(neg_a.mean())) if (len(pos_a) > 0 and len(neg_a) > 0 and neg_a.mean() != 0) else np.nan

            res[f"trig_qtr_ew_alpha_{h}d"] = q_ew
            res[f"trig_mean_alpha_{h}d"] = float(np.mean(av))
            res[f"trig_med_alpha_{h}d"] = float(np.median(av))
            res[f"trig_med_ret_{h}d"] = float(np.median(rv))
            res[f"trig_win_rate_{h}d"] = float(np.mean(av > 0))
            res[f"trig_payoff_{h}d"] = payoff
            res[f"trig_t_stat_{h}d"] = t_st
            res[f"trig_p_val_{h}d"] = p_vl
        else:
            for k in ("trig_qtr_ew_alpha", "trig_mean_alpha", "trig_med_alpha", "trig_med_ret", "trig_win_rate", "trig_payoff", "trig_t_stat", "trig_p_val"):
                res[f"{k}_{h}d"] = np.nan

        # 2. All-Intentions portfolio metrics (missed trades earn 0% excess return vs SPY)
        # Note: exclude only rows whose horizon extends past end of dataset (2026-11-06)
        max_needed_idx = work["e_idx"] + 20 + h
        elig_raw = work[max_needed_idx < n_days].copy()
        elig_ded = ded[(ded["e_idx"] + 20 + h) < n_days].copy()
        if len(elig_ded) >= 3:
            elig_raw["intent_alp"] = np.where(elig_raw["filled"] & elig_raw[ac].notna(), elig_raw[ac], 0.0)
            elig_ded["intent_alp"] = np.where(elig_ded["filled"] & elig_ded[ac].notna(), elig_ded[ac], 0.0)
            res[f"all_intent_qtr_ew_alpha_{h}d"] = float(elig_raw.groupby("cal_qtr")["intent_alp"].mean().mean())
            res[f"all_intent_mean_alpha_{h}d"] = float(elig_ded["intent_alp"].mean())
            res[f"all_intent_med_alpha_{h}d"] = float(elig_ded["intent_alp"].median())
        else:
            res[f"all_intent_qtr_ew_alpha_{h}d"] = np.nan
            res[f"all_intent_mean_alpha_{h}d"] = np.nan
            res[f"all_intent_med_alpha_{h}d"] = np.nan

    # D15 Mandatory Subperiods on 252d (1Y): Ex-Bubble, Last 10Y (2016-2026), High-Rate Recent (2022-2026)
    v252 = ded[ded["filled"]].dropna(subset=["alp_252d"])
    for sp_lbl, sp_col in [
        ("ex_bub", "is_ex_bubble"),
        ("last10y", "is_last_10y"),
        ("highrate_22_26", "is_high_rate_22_26"),
    ]:
        s_sp = v252[v252[sp_col]]
        res[f"{sp_lbl}_n_252d"] = int(len(s_sp))
        res[f"{sp_lbl}_med_alpha_252d"] = float(s_sp["alp_252d"].median()) if len(s_sp) >= 3 else np.nan
        res[f"{sp_lbl}_win_rate_252d"] = float((s_sp["alp_252d"] > 0).mean()) if len(s_sp) >= 3 else np.nan

    return res


def find_conditional_triggers(sub_raw: pd.DataFrame, eng: dict, rule_name: str) -> np.ndarray:
    """
    Computes zero-lookahead conditional entry day index in [e_idx .. e_idx + 19] (D+1 to D+20 close).
    Every condition uses ONLY daily OHLCV up to day t close, and enters strictly at day t close!
    """
    O_raw, C_raw = eng["O_raw"], eng["C_raw"]
    L_adj, P_adj, VOL = eng["L_adj"], eng["P_adj"], eng["VOL"]
    n_days = eng["n_days"]

    e_arr = sub_raw["e_idx"].values
    f_arr = sub_raw["f_idx"].values
    d0_arr = sub_raw["d0_idx"].values
    c_arr = sub_raw["s_col"].values
    d0_low_arr = sub_raw["d0_low_adj"].values

    n = len(sub_raw)
    out = np.full(n, -1, dtype=np.int32)

    for i in range(n):
        e0 = int(e_arr[i])
        f0 = int(f_arr[i])
        d0 = int(d0_arr[i])
        c = int(c_arr[i])

        if rule_name == "Cond_Drop_FirstGreenUp_D1toD20":
            # First trading day in [D+1..D+20] with green body (C > O) AND higher close (C[t] > C[t-1])
            for off in range(0, 20):
                t = e0 + off
                if t >= n_days:
                    break
                if C_raw[t, c] > O_raw[t, c] and P_adj[t, c] > P_adj[t - 1, c]:
                    out[i] = t
                    break

        elif rule_name == "Cond_Drop_FirstGreenUp_D2toD20":
            # Skip Day 1 catching-falling-knife; wait for first green up-close day in [D+2..D+20]
            for off in range(1, 20):
                t = e0 + off
                if t >= n_days:
                    break
                if C_raw[t, c] > O_raw[t, c] and P_adj[t, c] > P_adj[t - 1, c]:
                    out[i] = t
                    break

        elif rule_name == "Cond_Drop_VolDryUp_Stabilize_D2toD20":
            # Volume dries up below 65% of earnings-day volume AND close > prior close in [D+2..D+20]
            v_d0 = float(VOL[d0, c])
            for off in range(1, 20):
                t = e0 + off
                if t >= n_days:
                    break
                if v_d0 > 0 and VOL[t, c] <= 0.65 * v_d0 and P_adj[t, c] > P_adj[t - 1, c]:
                    out[i] = t
                    break

        elif rule_name == "Cond_Jump_Pullback_HoldGapLower_Green":
            # Wait in [D+2..D+20] for at least 1 pullback day (C[t] < C[t-1] or C[t] < C[D+1]),
            # never breaking pre-earnings close (gap lower bound = P_adj[f0 - 1]), then buy on first green up-close!
            gap_floor = float(P_adj[f0 - 1, c])
            had_pullback = False
            for off in range(1, 20):
                t = e0 + off
                if t >= n_days:
                    break
                if P_adj[t, c] < gap_floor or L_adj[t, c] < gap_floor * 0.995:
                    break  # Gap broken -> abort!
                if P_adj[t, c] < P_adj[t - 1, c]:
                    had_pullback = True
                elif had_pullback and C_raw[t, c] > O_raw[t, c] and P_adj[t, c] > P_adj[t - 1, c]:
                    out[i] = t
                    break

        elif rule_name == "Cond_Jump_Pullback_HoldD0Low_Green":
            # Wait in [D+2..D+20] for pullback while holding strictly above reaction-day intraday low (gap upper support D0_Low),
            # then buy on first green up-close!
            d0_low = float(d0_low_arr[i])
            had_pullback = False
            for off in range(1, 20):
                t = e0 + off
                if t >= n_days:
                    break
                if P_adj[t, c] < d0_low or L_adj[t, c] < d0_low * 0.995:
                    break  # D0 low violated -> abort!
                if P_adj[t, c] < P_adj[t - 1, c]:
                    had_pullback = True
                elif had_pullback and C_raw[t, c] > O_raw[t, c] and P_adj[t, c] > P_adj[t - 1, c]:
                    out[i] = t
                    break

        elif rule_name == "Cond_Jump_Dip2pct_HoldGapLower_Close":
            # Buy at close on the first day in [D+2..D+20] where close pulls back >= 2% below D+1 close
            # while still holding above pre-earnings close (gap lower bound).
            p_d1 = float(P_adj[e0, c])
            gap_floor = float(P_adj[f0 - 1, c])
            for off in range(1, 20):
                t = e0 + off
                if t >= n_days:
                    break
                if P_adj[t, c] < gap_floor or L_adj[t, c] < gap_floor * 0.995:
                    break
                if P_adj[t, c] <= p_d1 * 0.98:
                    out[i] = t
                    break

    return out


# ==============================================================================
# TABLE 1: Entry Timing Rhythm Table (D+1 to D+20 Unconditional vs Conditional)
# ==============================================================================
def build_table_1_entry_timing(d: pd.DataFrame, eng: dict) -> pd.DataFrame:
    print("[3/5] Computing Table 1: table_g05_entry_timing_d1_to_d20.csv...")
    rows = []

    pools = [
        ("Mcap_ge15B", d["mcap_2026_equiv_b"] >= 15.0),
        ("Mcap_ge25B", d["mcap_2026_equiv_b"] >= 25.0),
    ]

    uncond_rules = [
        ("Uncond_D+1_Close", 0),
        ("Uncond_D+2_Close", 1),
        ("Uncond_D+3_Close", 2),
        ("Uncond_D+5_Close", 4),
        ("Uncond_D+10_Close", 9),
        ("Uncond_D+20_Close", 19),
    ]

    for pool_name, p_mask in pools:
        u = d[p_mask & d["is_true_acc"]].copy()

        cohorts = [
            # 1. Mispriced Drop Tiers (True Acceleration)
            ("1_TrueAcc_Mispriced_Drop", "Drop_4to8pct", (u["earn_jump_ret"] <= -0.04) & (u["earn_jump_ret"] > -0.08), True),
            ("1_TrueAcc_Mispriced_Drop", "Drop_8to15pct", (u["earn_jump_ret"] <= -0.08) & (u["earn_jump_ret"] > -0.15), True),
            ("1_TrueAcc_Mispriced_Drop", "Drop_gt15pct", u["earn_jump_ret"] <= -0.15, True),
            ("1_TrueAcc_Mispriced_Drop", "Drop_All_ge4pct", u["earn_jump_ret"] <= -0.04, True),
            # Microstructure-conditioned Mispriced Drops (Moderate-Vol vs Heavy-Vol Shaved-Bottom Red)
            (
                "1B_TrueAcc_Drop_By_VolCandle",
                "Drop_ge4pct_ModVol_lt2.5x_ShavedRed",
                (u["earn_jump_ret"] <= -0.04) & (u["d0_body_ret"] < 0) & (u["d0_clv"] < 0.25) & (u["d0_vol_mult"] < 2.5),
                True,
            ),
            (
                "1B_TrueAcc_Drop_By_VolCandle",
                "Drop_ge4pct_HeavyVol_ge2.5x_ShavedRed",
                (u["earn_jump_ret"] <= -0.04) & (u["d0_body_ret"] < 0) & (u["d0_clv"] < 0.25) & (u["d0_vol_mult"] >= 2.5),
                True,
            ),
            # 2. Breakout Jump Tiers (True Acceleration & PS <= 15)
            (
                "2_TrueAcc_PSle15_Breakout_Jump",
                "Jump_5to10pct",
                (u["ps_pit"] > 0) & (u["ps_pit"] <= 15.0) & (u["earn_jump_ret"] >= 0.05) & (u["earn_jump_ret"] < 0.10),
                False,
            ),
            (
                "2_TrueAcc_PSle15_Breakout_Jump",
                "Jump_10to18pct",
                (u["ps_pit"] > 0) & (u["ps_pit"] <= 15.0) & (u["earn_jump_ret"] >= 0.10) & (u["earn_jump_ret"] < 0.18),
                False,
            ),
            (
                "2_TrueAcc_PSle15_Breakout_Jump",
                "Jump_gt18pct",
                (u["ps_pit"] > 0) & (u["ps_pit"] <= 15.0) & (u["earn_jump_ret"] >= 0.18),
                False,
            ),
            (
                "2_TrueAcc_PSle15_Breakout_Jump",
                "Jump_All_ge5pct",
                (u["ps_pit"] > 0) & (u["ps_pit"] <= 15.0) & (u["earn_jump_ret"] >= 0.05),
                False,
            ),
        ]

        for fam, tier_name, c_mask, is_drop in cohorts:
            sub = u[c_mask].copy().reset_index(drop=True)
            if len(sub) == 0:
                continue

            # Baseline D+1 252d alpha for missed-trade attribution
            _, d1_alps = compute_forward_returns_from_entries(eng, sub["e_idx"].values, sub["s_col"].values, horizons=(252,))
            d1_a252 = d1_alps[252]

            # Unconditional D+1 .. D+20
            for r_lbl, off in uncond_rules:
                ent_k = sub["e_idx"].values + off
                m = summarize_entry_metrics(sub, ent_k, eng, horizons=(63, 126, 252, 756), d1_alp_252_raw=d1_a252)
                row = {
                    "mcap_pool": pool_name,
                    "strategy_family": fam,
                    "reaction_tier": tier_name,
                    "entry_type": "Unconditional",
                    "entry_rule": r_lbl,
                }
                row.update(m)
                rows.append(row)

            # Conditional triggers
            cond_list = (
                [
                    "Cond_Drop_FirstGreenUp_D1toD20",
                    "Cond_Drop_FirstGreenUp_D2toD20",
                    "Cond_Drop_VolDryUp_Stabilize_D2toD20",
                ]
                if is_drop
                else [
                    "Cond_Jump_Pullback_HoldGapLower_Green",
                    "Cond_Jump_Pullback_HoldD0Low_Green",
                    "Cond_Jump_Dip2pct_HoldGapLower_Close",
                ]
            )
            for c_rule in cond_list:
                trig_ent = find_conditional_triggers(sub, eng, c_rule)
                m = summarize_entry_metrics(sub, trig_ent, eng, horizons=(63, 126, 252, 756), d1_alp_252_raw=d1_a252)
                row = {
                    "mcap_pool": pool_name,
                    "strategy_family": fam,
                    "reaction_tier": tier_name,
                    "entry_type": "Conditional",
                    "entry_rule": c_rule,
                }
                row.update(m)
                rows.append(row)

    out_df = pd.DataFrame(rows)
    if "trig_p_val_252d" in out_df.columns:
        out_df["bh_fdr_q_252d"] = benjamini_hochberg_fdr(out_df["trig_p_val_252d"].values)
    return out_df


# ==============================================================================
# TABLE 2: Volume Multiple x Candle CLV Microstructure & CLS Fade / Drop Hammer Anatomy
# ==============================================================================
def build_table_2_microstructure(d: pd.DataFrame, eng: dict) -> pd.DataFrame:
    print("[4/5] Computing Table 2: table_g05_volume_and_candle_microstructure.csv...")
    rows = []

    vol_bins = ["V1_lt1.5x", "V2_1.5to2.5x", "V3_2.5to4.0x", "V4_ge4.0x_Climax"]
    clv_bins = [
        "C1_lt0.25_LowClose_GravestoneOrShavedRed",
        "C2_0.25to0.75_MidClose",
        "C3_ge0.75_HighClose_MarubozuOrHammer",
    ]

    pools = [
        ("Mcap_ge15B", d["mcap_2026_equiv_b"] >= 15.0),
        ("Mcap_ge25B", d["mcap_2026_equiv_b"] >= 25.0),
    ]

    for pool_name, p_mask in pools:
        p_df = d[p_mask].copy()

        # ---------------------------------------------------------------------
        # Sections A, B, C: 4x3 Vol_Mult x CLV Matrices + Marginals
        # ---------------------------------------------------------------------
        matrix_universes = [
            (
                "SecA_TrueAcc_PSle15_Jump_ge5pct_4x3",
                p_df[p_df["is_true_acc"] & (p_df["ps_pit"] > 0) & (p_df["ps_pit"] <= 15.0) & (p_df["earn_jump_ret"] >= 0.05)],
            ),
            (
                "SecB_AllStocks_PSle15_Jump_ge5pct_4x3",
                p_df[(p_df["ps_pit"] > 0) & (p_df["ps_pit"] <= 15.0) & (p_df["earn_jump_ret"] >= 0.05)],
            ),
            (
                "SecC_TrueAcc_Mispriced_Drop_le_m4pct_4x3",
                p_df[p_df["is_true_acc"] & (p_df["earn_jump_ret"] <= -0.04)],
            ),
        ]

        for sec_name, u_sub in matrix_universes:
            # Full baseline row
            m_all = summarize_entry_metrics(u_sub, u_sub["e_idx"].values, eng, horizons=(63, 126, 252, 756))
            rows.append(
                {
                    "mcap_pool": pool_name,
                    "section": sec_name,
                    "vol_tier": "ALL_VOL",
                    "clv_tier": "ALL_CLV",
                    "pattern_label": f"{sec_name} | ALL_BASELINE",
                    "entry_rule": "Uncond_D+1_Close",
                    **m_all,
                }
            )
            # 4x3 cells + row marginals
            for vb in vol_bins:
                for cb in clv_bins:
                    cell = u_sub[(u_sub["vol_bin"] == vb) & (u_sub["clv_bin"] == cb)]
                    mc = summarize_entry_metrics(cell, cell["e_idx"].values, eng, horizons=(63, 126, 252, 756))
                    rows.append(
                        {
                            "mcap_pool": pool_name,
                            "section": sec_name,
                            "vol_tier": vb,
                            "clv_tier": cb,
                            "pattern_label": f"{vb} x {cb}",
                            "entry_rule": "Uncond_D+1_Close",
                            **mc,
                        }
                    )
                v_marg = u_sub[u_sub["vol_bin"] == vb]
                mv = summarize_entry_metrics(v_marg, v_marg["e_idx"].values, eng, horizons=(63, 126, 252, 756))
                rows.append(
                    {
                        "mcap_pool": pool_name,
                        "section": sec_name,
                        "vol_tier": vb,
                        "clv_tier": "ALL_CLV",
                        "pattern_label": f"{vb} | Marginal",
                        "entry_rule": "Uncond_D+1_Close",
                        **mv,
                    }
                )
            # Column marginals
            for cb in clv_bins:
                c_marg = u_sub[u_sub["clv_bin"] == cb]
                mcc = summarize_entry_metrics(c_marg, c_marg["e_idx"].values, eng, horizons=(63, 126, 252, 756))
                rows.append(
                    {
                        "mcap_pool": pool_name,
                        "section": sec_name,
                        "vol_tier": "ALL_VOL",
                        "clv_tier": cb,
                        "pattern_label": f"ALL_VOL x {cb} | Marginal",
                        "entry_rule": "Uncond_D+1_Close",
                        **mcc,
                    }
                )

        # ---------------------------------------------------------------------
        # Section D: CLS-Style Climax Intraday Surge & Gravestone Fade Anatomy
        #            Evaluated on BOTH Filing-Day D0 and Full 8K+10Q Reaction Day (both entered at D+1 close!)
        # ---------------------------------------------------------------------
        cls_slices = [
            # 1. Filing-window D0 Intraday Surge >= +10%
            ("D0_IntradaySurge_ge10pct | PowerMarubozu (CLV>=0.75 & Vol>=2.5x)", (p_df["d0_high_ret"] >= 0.10) & (p_df["d0_clv"] >= 0.75) & (p_df["d0_vol_mult"] >= 2.5), "V3_V4_ge2.5x", "C3_ge0.75"),
            ("D0_IntradaySurge_ge10pct | TrueAcc_PSle15_PowerMarubozu (CLV>=0.75 & Vol>=2.5x)", (p_df["d0_high_ret"] >= 0.10) & p_df["is_true_acc"] & (p_df["ps_pit"] > 0) & (p_df["ps_pit"] <= 15) & (p_df["d0_clv"] >= 0.75) & (p_df["d0_vol_mult"] >= 2.5), "V3_V4_ge2.5x", "C3_ge0.75"),
            ("D0_IntradaySurge_ge10pct | GravestoneFade (CLV<0.25 & Vol>=2.5x)", (p_df["d0_high_ret"] >= 0.10) & (p_df["d0_clv"] < 0.25) & (p_df["d0_vol_mult"] >= 2.5), "V3_V4_ge2.5x", "C1_lt0.25"),
            ("D0_IntradaySurge_ge10pct | ClimaxGravestoneFade (CLV<0.25 & Vol>=4.0x)", (p_df["d0_high_ret"] >= 0.10) & (p_df["d0_clv"] < 0.25) & (p_df["d0_vol_mult"] >= 4.0), "V4_ge4.0x_Climax", "C1_lt0.25"),
            # 2. Filing-window D0 Intraday Surge >= +15% (CLS scale!)
            ("D0_IntradaySurge_ge15pct | ClimaxGravestoneFade (CLV<0.25 & Vol>=4.0x)", (p_df["d0_high_ret"] >= 0.15) & (p_df["d0_clv"] < 0.25) & (p_df["d0_vol_mult"] >= 4.0), "V4_ge4.0x_Climax", "C1_lt0.25"),
            # 3. Full 8K+10Q Earnings Reaction Window Intraday Surge >= +10% & >= +15%
            ("8KWin_IntradaySurge_ge10pct | TrueAcc_PSle15_PowerMarubozu (CLV>=0.75 & Vol>=2.5x)", (p_df["d8k_high_ret"] >= 0.10) & p_df["is_true_acc"] & (p_df["ps_pit"] > 0) & (p_df["ps_pit"] <= 15) & (p_df["d8k_clv"] >= 0.75) & (p_df["d8k_vol_mult"] >= 2.5), "V3_V4_ge2.5x", "C3_ge0.75"),
            ("8KWin_IntradaySurge_ge10pct | ClimaxGravestone_BearBody (CLV<0.25 & C<O & Vol>=4.0x)", (p_df["d8k_high_ret"] >= 0.10) & (p_df["d8k_clv"] < 0.25) & (p_df["d8k_body_ret"] < 0) & (p_df["d8k_vol_mult"] >= 4.0), "V4_ge4.0x_Climax", "C1_lt0.25"),
            ("8KWin_IntradaySurge_ge15pct | TrueAcc_PSle15_PowerMarubozu (CLV>=0.75 & Vol>=2.5x)", (p_df["d8k_high_ret"] >= 0.15) & p_df["is_true_acc"] & (p_df["ps_pit"] > 0) & (p_df["ps_pit"] <= 15) & (p_df["d8k_clv"] >= 0.75) & (p_df["d8k_vol_mult"] >= 2.5), "V3_V4_ge2.5x", "C3_ge0.75"),
            ("8KWin_IntradaySurge_ge15pct | HeavyVol_Gravestone_BearBody (CLV<0.25 & C<O & Vol>=2.5x)", (p_df["d8k_high_ret"] >= 0.15) & (p_df["d8k_clv"] < 0.25) & (p_df["d8k_body_ret"] < 0) & (p_df["d8k_vol_mult"] >= 2.5), "V3_V4_ge2.5x", "C1_lt0.25"),
            ("8KWin_IntradaySurge_ge15pct | ClimaxVol_Gravestone_BearBody (CLV<0.25 & C<O & Vol>=4.0x, CLS!)", (p_df["d8k_high_ret"] >= 0.15) & (p_df["d8k_clv"] < 0.25) & (p_df["d8k_body_ret"] < 0) & (p_df["d8k_vol_mult"] >= 4.0), "V4_ge4.0x_Climax", "C1_lt0.25"),
        ]
        for pat_lbl, mask_s, vt, ct in cls_slices:
            sub_s = p_df[mask_s]
            ms = summarize_entry_metrics(sub_s, sub_s["e_idx"].values, eng, horizons=(63, 126, 252, 756))
            rows.append(
                {
                    "mcap_pool": pool_name,
                    "section": "SecD_CLS_ClimaxSurge_vs_PowerBreakout_Anatomy",
                    "vol_tier": vt,
                    "clv_tier": ct,
                    "pattern_label": pat_lbl,
                    "entry_rule": "Uncond_D+1_Close",
                    **ms,
                }
            )

        # ---------------------------------------------------------------------
        # Section E: Mispriced Drop Candle Anatomy & Optimal Entry Handling
        #            ("Gap-Down Green Hammer Support" vs "Mod-Vol Shaved Red" vs "Heavy-Vol Shaved Red Dump")
        # ---------------------------------------------------------------------
        ta = p_df[p_df["is_true_acc"]].copy()
        drop_patterns = [
            ("TrueAcc_GapDown_le_m3pct_GreenHammer (C>O & CLV>=0.65)", (ta["d0_open_gap"] <= -0.03) & (ta["d0_body_ret"] > 0) & (ta["d0_clv"] >= 0.65), "ALL_VOL", "C3_ge0.65_GreenHammer"),
            ("TrueAcc_Drop_le_m4pct_IntradayGreenBody (C>O, FakeGreen)", (ta["earn_jump_ret"] <= -0.04) & (ta["d0_body_ret"] > 0), "ALL_VOL", "GreenBody_CgtO"),
            ("TrueAcc_Drop_le_m4pct_HighCLV_Support (CLV>=0.60)", (ta["earn_jump_ret"] <= -0.04) & (ta["d0_clv"] >= 0.60), "ALL_VOL", "CLV_ge0.60"),
            ("TrueAcc_Drop_le_m4pct_ModVol_ShavedRed (C<O & CLV<0.25 & Vol<2.5x)", (ta["earn_jump_ret"] <= -0.04) & (ta["d0_body_ret"] < 0) & (ta["d0_clv"] < 0.25) & (ta["d0_vol_mult"] < 2.5), "V1_V2_lt2.5x", "C1_lt0.25_ShavedRed"),
            ("TrueAcc_Drop_le_m4pct_HeavyVol_ShavedRed (C<O & CLV<0.25 & Vol>=2.5x)", (ta["earn_jump_ret"] <= -0.04) & (ta["d0_body_ret"] < 0) & (ta["d0_clv"] < 0.25) & (ta["d0_vol_mult"] >= 2.5), "V3_V4_ge2.5x", "C1_lt0.25_ShavedRed"),
            ("TrueAcc_Drop_le_m4pct_ClimaxVol_ShavedRed (C<O & CLV<0.25 & Vol>=4.0x)", (ta["earn_jump_ret"] <= -0.04) & (ta["d0_body_ret"] < 0) & (ta["d0_clv"] < 0.25) & (ta["d0_vol_mult"] >= 4.0), "V4_ge4.0x_Climax", "C1_lt0.25_ShavedRed"),
        ]
        for pat_lbl, mask_d, vt, ct in drop_patterns:
            sub_d = ta[mask_d].copy().reset_index(drop=True)
            if len(sub_d) == 0:
                continue
            for r_lbl, ent_vec in [
                ("Uncond_D+1_Close", sub_d["e_idx"].values),
                ("Uncond_D+5_Close", sub_d["e_idx"].values + 4),
                ("Cond_Drop_FirstGreenUp_D2toD20", find_conditional_triggers(sub_d, eng, "Cond_Drop_FirstGreenUp_D2toD20")),
            ]:
                md_res = summarize_entry_metrics(sub_d, ent_vec, eng, horizons=(63, 126, 252, 756))
                rows.append(
                    {
                        "mcap_pool": pool_name,
                        "section": "SecE_MispricedDrop_Hammer_vs_ShavedRed_Handling",
                        "vol_tier": vt,
                        "clv_tier": ct,
                        "pattern_label": pat_lbl,
                        "entry_rule": r_lbl,
                        **md_res,
                    }
                )

    out_df = pd.DataFrame(rows)
    if "trig_p_val_252d" in out_df.columns:
        out_df["bh_fdr_q_252d"] = benjamini_hochberg_fdr(out_df["trig_p_val_252d"].values)
    return out_df


# ==============================================================================
# TABLE 3: Cumulative Post-Earnings Drift (PEAD) Path: D+5 to D+756 (3Y)
# ==============================================================================
def build_table_3_pead_drift_path(d: pd.DataFrame, eng: dict) -> pd.DataFrame:
    print("[5/5] Computing Table 3: table_g05_pead_drift_path.csv...")
    drift_horizons = [5, 10, 21, 63, 126, 252, 756]
    horizon_labels = {
        5: "D+5 (1W)",
        10: "D+10 (2W)",
        21: "D+21 (1M)",
        63: "D+63 (3M)",
        126: "D+126 (6M)",
        252: "D+252 (1Y)",
        756: "D+756 (3Y)",
    }

    rows = []
    pools = [
        ("Mcap_ge15B", d["mcap_2026_equiv_b"] >= 15.0),
        ("Mcap_ge25B", d["mcap_2026_equiv_b"] >= 25.0),
    ]

    for pool_name, p_mask in pools:
        p_df = d[p_mask].copy()
        ta = p_df[p_df["is_true_acc"]].copy()

        core_groups = [
            # 1. Mispriced Drop Tiers
            ("1_Mispriced_Drop_4to8pct", ta[(ta["earn_jump_ret"] <= -0.04) & (ta["earn_jump_ret"] > -0.08)]),
            ("2_Mispriced_Drop_8to15pct", ta[(ta["earn_jump_ret"] <= -0.08) & (ta["earn_jump_ret"] > -0.15)]),
            ("3_Mispriced_Drop_gt15pct", ta[ta["earn_jump_ret"] <= -0.15]),
            ("4_Mispriced_Drop_All_ge4pct", ta[ta["earn_jump_ret"] <= -0.04]),
            # 2. Mispriced Drop Microstructure Subgroups
            (
                "5_Mispriced_ModVol_lt2.5x_ShavedRed_Goldmine",
                ta[(ta["earn_jump_ret"] <= -0.04) & (ta["d0_body_ret"] < 0) & (ta["d0_clv"] < 0.25) & (ta["d0_vol_mult"] < 2.5)],
            ),
            (
                "6_Mispriced_HeavyVol_ge2.5x_ShavedRed_Dump",
                ta[(ta["earn_jump_ret"] <= -0.04) & (ta["d0_body_ret"] < 0) & (ta["d0_clv"] < 0.25) & (ta["d0_vol_mult"] >= 2.5)],
            ),
            (
                "7_TrueAcc_GapDown_GreenHammer_FakeSupport",
                ta[(ta["d0_open_gap"] <= -0.03) & (ta["d0_body_ret"] > 0) & (ta["d0_clv"] >= 0.65)],
            ),
            # 3. Breakout Jump Tiers (TrueAcc & PS <= 15)
            (
                "8_Breakout_PSle15_Jump_5to10pct",
                ta[(ta["ps_pit"] > 0) & (ta["ps_pit"] <= 15.0) & (ta["earn_jump_ret"] >= 0.05) & (ta["earn_jump_ret"] < 0.10)],
            ),
            (
                "9_Breakout_PSle15_Jump_10to18pct",
                ta[(ta["ps_pit"] > 0) & (ta["ps_pit"] <= 15.0) & (ta["earn_jump_ret"] >= 0.10) & (ta["earn_jump_ret"] < 0.18)],
            ),
            (
                "10_Breakout_PSle15_Jump_gt18pct",
                ta[(ta["ps_pit"] > 0) & (ta["ps_pit"] <= 15.0) & (ta["earn_jump_ret"] >= 0.18)],
            ),
            (
                "11_Breakout_PSle15_Jump_All_ge5pct",
                ta[(ta["ps_pit"] > 0) & (ta["ps_pit"] <= 15.0) & (ta["earn_jump_ret"] >= 0.05)],
            ),
            # 4. Breakout Microstructure Sweet Spot vs CLS Climax Gravestone Trap
            (
                "12_Breakout_Golden_Vol_ge2.5x_Marubozu_CLV_ge0.75",
                ta[(ta["ps_pit"] > 0) & (ta["ps_pit"] <= 15.0) & (ta["earn_jump_ret"] >= 0.05) & (ta["d0_vol_mult"] >= 2.5) & (ta["d0_clv"] >= 0.75)],
            ),
            (
                "13_Trap_PSle15_Jump_ClimaxVol_ge4.0x_Fade_CLV_lt0.25",
                p_df[(p_df["ps_pit"] > 0) & (p_df["ps_pit"] <= 15.0) & (p_df["earn_jump_ret"] >= 0.05) & (p_df["d0_vol_mult"] >= 4.0) & (p_df["d0_clv"] < 0.25)],
            ),
            (
                "14_Trap_CLS_8KWin_Surge_ge15pct_ClimaxFade_Vol_ge4.0x_CLV_lt0.25",
                p_df[(p_df["d8k_high_ret"] >= 0.15) & (p_df["d8k_clv"] < 0.25) & (p_df["d8k_body_ret"] < 0) & (p_df["d8k_vol_mult"] >= 4.0)],
            ),
        ]

        for grp_name, g_sub in core_groups:
            if len(g_sub) == 0:
                continue
            work = g_sub[["ticker", "entry_date", "e_idx", "s_col", "is_ex_bubble", "is_last_10y", "is_high_rate_22_26"]].copy().reset_index(drop=True)
            work["cal_qtr"] = pd.to_datetime(work["entry_date"]).dt.to_period("Q")
            ret_d, alp_d = compute_forward_returns_from_entries(eng, work["e_idx"].values, work["s_col"].values, horizons=drift_horizons)
            for h in drift_horizons:
                work[f"ret_{h}d"] = ret_d[h]
                work[f"alp_{h}d"] = alp_d[h]

            ded = deduplicate_cooldown(work, date_col="entry_date", cooldown_days=DEDUP_DAYS)

            # Build both long-format per-horizon rows AND wide-summary clarity: long format (group x horizon) is cleanest for plotting curves!
            for h in drift_horizons:
                ac = f"alp_{h}d"
                rc = f"ret_{h}d"
                v_raw = work.dropna(subset=[ac])
                v_ded = ded.dropna(subset=[ac])
                n_h = len(v_ded)
                if n_h < 3:
                    continue

                q_means = v_raw.groupby("cal_qtr")[ac].mean()
                q_ew = float(q_means.mean())
                q_se = float(q_means.std(ddof=1) / np.sqrt(len(q_means))) if len(q_means) > 2 else np.nan
                t_st = q_ew / q_se if (q_se and q_se > 0) else np.nan
                p_vl = float(2 * (1 - stats.t.cdf(abs(t_st), df=max(len(q_means) - 1, 1)))) if pd.notna(t_st) else np.nan

                av = v_ded[ac].values
                rv = v_ded[rc].values
                pos_a = av[av > 0]
                neg_a = av[av <= 0]
                payoff = float(pos_a.mean() / abs(neg_a.mean())) if (len(pos_a) > 0 and len(neg_a) > 0 and neg_a.mean() != 0) else np.nan

                ex_b = v_ded[v_ded["is_ex_bubble"]]
                hr_22 = v_ded[v_ded["is_high_rate_22_26"]]
                l10 = v_ded[v_ded["is_last_10y"]]

                rows.append(
                    {
                        "mcap_pool": pool_name,
                        "core_group": grp_name,
                        "horizon_days": h,
                        "horizon_label": horizon_labels[h],
                        "n_raw": int(len(v_raw)),
                        "n_dedup": int(n_h),
                        "qtr_ew_alpha": q_ew,
                        "dedup_mean_alpha": float(np.mean(av)),
                        "med_alpha": float(np.median(av)),
                        "med_raw_ret": float(np.median(rv)),
                        "win_rate_vs_spy": float(np.mean(av > 0)),
                        "payoff_ratio": payoff,
                        "t_stat": t_st,
                        "p_val": p_vl,
                        "ex_bubble_med_alpha": float(ex_b[ac].median()) if len(ex_b) >= 3 else np.nan,
                        "ex_bubble_win_rate": float((ex_b[ac] > 0).mean()) if len(ex_b) >= 3 else np.nan,
                        "last10y_win_rate": float((l10[ac] > 0).mean()) if len(l10) >= 3 else np.nan,
                        "highrate_22_26_win_rate": float((hr_22[ac] > 0).mean()) if len(hr_22) >= 3 else np.nan,
                    }
                )

    return pd.DataFrame(rows)


def main():
    t_start = time.time()
    os.makedirs(OUT_DIR, exist_ok=True)

    eng = build_ohlcv_and_delisted_engine()
    d = prepare_events_with_microstructure(eng)

    t1 = build_table_1_entry_timing(d, eng)
    p1 = os.path.join(OUT_DIR, "table_g05_entry_timing_d1_to_d20.csv")
    t1.to_csv(p1, index=False)
    print(f"  -> Saved {p1} ({len(t1):,} rows x {len(t1.columns)} cols)")

    t2 = build_table_2_microstructure(d, eng)
    p2 = os.path.join(OUT_DIR, "table_g05_volume_and_candle_microstructure.csv")
    t2.to_csv(p2, index=False)
    print(f"  -> Saved {p2} ({len(t2):,} rows x {len(t2.columns)} cols)")

    t3 = build_table_3_pead_drift_path(d, eng)
    p3 = os.path.join(OUT_DIR, "table_g05_pead_drift_path.csv")
    t3.to_csv(p3, index=False)
    print(f"  -> Saved {p3} ({len(t3):,} rows x {len(t3.columns)} cols)")

    print(f"[DONE] All G05 tables generated cleanly in {time.time() - t_start:.2f}s.")


if __name__ == "__main__":
    main()

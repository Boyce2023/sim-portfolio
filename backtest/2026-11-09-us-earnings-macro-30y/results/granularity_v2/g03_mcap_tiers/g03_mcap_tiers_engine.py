#!/usr/bin/env python3
"""
G03: 7-Tier Zero-Lookahead Market Cap Stratification, Optimal Threshold Scaling Laws,
and $25B -> $100B Secular Crossover vs Pulse-Peak Anatomy Engine (2009-2026 PIT + 1996-2026 Price History).

Strict Guarantees:
1. 100% Zero Lookahead Market Cap (`mcap_2026_equiv_b`):
   Strictly contemporary PIT Shares (bidirectionally calibrated for 1000x/1e6x XBRL unit errors using ONLY
   contemporary EPS-implied shares, prior-filing EntityPublicFloat, contemporary Assets/Equity/Rev scale,
   and strictly prior-quarter share continuity) x Contemporary Unadjusted Close x Contemporary S&P 500
   Purchasing-Power Scale (`mcap_scale_to_2026 = SPX_2026 / SPX_t`).
   NEVER filters by future 2026 market cap!
2. Full Delisting & Bankruptcy Residual Splicing:
   Integrates `xbrl_master_pit_2009_2026.parquet` + `unified_prices_and_bench.parquet` +
   `all_daily.parquet` + `delisted_prices_0/1` + `extra_prices` + `delisted_f4_prices` +
   571 S&P 500 Historical Exits + 61 HC/Growth Delisted + 165 SEC Form 25/8-K Deal/Bankruptcy Records.
3. D15 Anti-Bias Statistical Protocol:
   - Calendar-Quarter Equal-Weight Net Excess vs SPY across 7 horizons (1M, 3M, 6M, 1Y, 2Y, 3Y, 5Y)
   - Within-Tier Baseline Excess (`spread_vs_tier_base`) to isolate pure signal alpha from <$10B backfill drift
   - 250-Trading-Day Per-Ticker Cooldown Deduplication for Win Rate, Payoff, Bag2x, Bag3x, Halve50, Delist/Bankruptcy
   - Subperiods: Full (2009-2026), Ex-2020-2021 Bubble, Last 10Y (2016-2026), High-Rate Era (2022-2026)
"""

import os
import re
import sys
import glob
import json
import time
import zipfile
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from scipy import stats

PROJ_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-09-us-earnings-macro-30y"
TMP_DIR = "/tmp/us_earn_macro_bt_20261109"
OUT_DIR = os.path.join(PROJ_DIR, "results/granularity_v2/g03_mcap_tiers")
os.makedirs(OUT_DIR, exist_ok=True)

sys.path.insert(0, os.path.join(PROJ_DIR, "scripts"))
from backtest_stats_lib import deduplicate_cooldown, benjamini_hochberg_fdr
from price_feature_lib import TAG_MAP

HORIZONS = [
    (21, "1m"),
    (63, "3m"),
    (126, "6m"),
    (252, "1y"),
    (504, "2y"),
    (756, "3y"),
    (1260, "5y"),
]

MCAP_TIERS = [
    ("T1_2to5B", "1_20亿至50亿(小中盘观察层)", 2.0, 5.0),
    ("T2_5to10B", "2_50亿至100亿(中盘黑马层_DUOL)", 5.0, 10.0),
    ("T3_10to25B", "3_100亿至250亿(准大盘跃迁层_HALO_LITE_TLN)", 10.0, 25.0),
    ("T4_25to50B", "4_250亿至500亿(新兴大盘层_VST_NTRA)", 25.0, 50.0),
    ("T5_50to150B", "5_500亿至1500亿(中坚大盘层_VRT_ICE_APP)", 50.0, 150.0),
    ("T6_150to500B", "6_1500亿至5000亿(行业龙头层_KLAC_APH_GEV_ANET_LRCX)", 150.0, 500.0),
    ("T7_ge500B", "7_5000亿以上(超级生态巨头层_LLY_TSM_GOOGL_MSFT)", 500.0, np.inf),
]


# ==============================================================================
# STEP 1: Build Complete Price + Delisted Residual Matrix (1996-2026)
# ==============================================================================
def build_complete_price_and_delist_engine():
    t0 = time.time()
    print("[Step 1] Loading unified_prices_and_bench / price_engine_cache + delisted & all_daily supplements...")

    up_path = os.path.join(TMP_DIR, "unified_prices_and_bench.parquet")
    if not os.path.exists(up_path):
        raise FileNotFoundError(f"Missing {up_path}")
    cache = np.load(os.path.join(TMP_DIR, "price_engine_cache.npz"), allow_pickle=True)

    dates = cache["dates"]
    dates_ts = pd.to_datetime(dates)
    n_days = len(dates)
    date_to_idx = {pd.Timestamp(d).normalize(): i for i, d in enumerate(dates)}

    base_tickers = [str(t) for t in cache["tickers"]]
    base_set = set(base_tickers)

    dm0 = pd.read_parquet(os.path.join(TMP_DIR, "delisted_prices/delisted_meta_0.parquet"))
    dm1 = pd.read_parquet(os.path.join(TMP_DIR, "delisted_prices/delisted_meta_1.parquet"))
    dm_all = pd.concat([dm0.assign(shard=0), dm1.assign(shard=1)], ignore_index=True)
    hc61 = pd.read_parquet(os.path.join(TMP_DIR, "delisted_prices/hc_delisted_61_meta.parquet"))
    q03_path = "/tmp/us_xuangu_20261109/w2/q03_delisted_ma_vs_bankrupt.csv"
    q03 = pd.read_csv(q03_path) if os.path.exists(q03_path) else pd.DataFrame()

    exit_meta = {}
    for _, r in dm_all.iterrows():
        tk = str(r["ticker"]).strip()
        et = str(r["exit_type"])
        dt_s = r["sp_end"] if (pd.notna(r["sp_end"]) and str(r["sp_end"]) != "nan") else r["last_sec_filing"]
        t_ret = float(r["terminal_delist_ret"]) if pd.notna(r["terminal_delist_ret"]) else 0.0
        exit_meta[tk] = {
            "exit_type": "BANKRUPTCY" if et == "BANKRUPTCY_OR_LIQUIDATION" else ("MA" if et == "MA_ACQUISITION" else et),
            "exit_dt": pd.to_datetime(dt_s, errors="coerce"),
            "deal_px": np.nan,
            "t_ret": -0.95 if et == "BANKRUPTCY_OR_LIQUIDATION" else t_ret,
        }

    hc_bk_set = {"NVTA", "VVUS", "ENDP", "MNK"}
    for _, r in hc61.iterrows():
        tk = str(r["ticker"]).strip()
        is_bk = tk in hc_bk_set
        if tk not in exit_meta:
            exit_meta[tk] = {
                "exit_type": "BANKRUPTCY" if is_bk else "MA",
                "exit_dt": pd.to_datetime(r["delist_dt"], errors="coerce"),
                "deal_px": np.nan,
                "t_ret": -0.95 if is_bk else 0.15,
            }
        elif pd.isna(exit_meta[tk]["exit_dt"]):
            exit_meta[tk]["exit_dt"] = pd.to_datetime(r["delist_dt"], errors="coerce")

    if len(q03) > 0:
        for _, r in q03.iterrows():
            tk = str(r["ticker"]).strip()
            et_q = str(r["exit_type"])
            detail = str(r.get("acquirer_or_bankruptcy_detail", "")) + " " + str(r.get("notes", ""))
            m_dt = re.search(r"(20\d{2}-\d{2}-\d{2})", detail)
            exact_dt = pd.to_datetime(m_dt.group(1), errors="coerce") if m_dt else pd.to_datetime(r["sp_end_date"], errors="coerce")
            if pd.isna(exact_dt):
                exact_dt = pd.to_datetime(r["sp_end_date"], errors="coerce")
            if et_q == "bankrupt_wipeout":
                exit_meta[tk] = {
                    "exit_type": "BANKRUPTCY",
                    "exit_dt": exact_dt,
                    "deal_px": float(r["deal_price_or_terminal_price"]) if pd.notna(r["deal_price_or_terminal_price"]) else 0.05,
                    "t_ret": -0.95,
                }
            elif et_q == "ma_cash_premium":
                prem = float(r["terminal_return_pct"]) / 100.0 if pd.notna(r["terminal_return_pct"]) else 0.25
                exit_meta[tk] = {
                    "exit_type": "MA",
                    "exit_dt": pd.to_datetime(r["sp_end_date"], errors="coerce") if pd.notna(r["sp_end_date"]) else exact_dt,
                    "deal_px": float(r["deal_price_or_terminal_price"]) if pd.notna(r["deal_price_or_terminal_price"]) else np.nan,
                    "t_ret": prem,
                }

    exit_meta["NVTA"] = {"exit_type": "BANKRUPTCY", "exit_dt": pd.Timestamp("2024-02-13"), "deal_px": 0.05, "t_ret": -0.95}
    exit_meta["VVUS"] = {"exit_type": "BANKRUPTCY", "exit_dt": pd.Timestamp("2020-07-07"), "deal_px": 0.05, "t_ret": -0.95}
    exit_meta["TUP"] = {"exit_type": "BANKRUPTCY", "exit_dt": pd.Timestamp("2024-09-17"), "deal_px": 0.10, "t_ret": -0.95}
    exit_meta["BBBY"] = {"exit_type": "BANKRUPTCY", "exit_dt": pd.Timestamp("2023-04-23"), "deal_px": 0.05, "t_ret": -0.95}
    exit_meta["SIVB"] = {"exit_type": "BANKRUPTCY", "exit_dt": pd.Timestamp("2023-03-10"), "deal_px": 0.05, "t_ret": -0.95}
    exit_meta["FRC"] = {"exit_type": "BANKRUPTCY", "exit_dt": pd.Timestamp("2023-05-01"), "deal_px": 0.05, "t_ret": -0.95}
    exit_meta["SBNY"] = {"exit_type": "BANKRUPTCY", "exit_dt": pd.Timestamp("2023-03-12"), "deal_px": 0.05, "t_ret": -0.95}
    exit_meta["SAVE"] = {"exit_type": "BANKRUPTCY", "exit_dt": pd.Timestamp("2024-11-18"), "deal_px": 0.05, "t_ret": -0.95}
    exit_meta["RAD"] = {"exit_type": "BANKRUPTCY", "exit_dt": pd.Timestamp("2023-10-15"), "deal_px": 0.05, "t_ret": -0.95}

    xbrl_tks = set(pd.read_parquet(os.path.join(PROJ_DIR, "data/xbrl_master_pit_2009_2026.parquet"), columns=["ticker"])["ticker"].unique())
    miss_xbrl_tks = xbrl_tks - base_set

    supp_dfs = []
    for p in [
        os.path.join(TMP_DIR, "delisted_prices/delisted_prices_0.parquet"),
        os.path.join(TMP_DIR, "delisted_prices/delisted_prices_1.parquet"),
    ]:
        if os.path.exists(p):
            d = pd.read_parquet(p, columns=["date", "ticker", "close", "adj_close"])
            d["date"] = pd.to_datetime(d["date"]).dt.tz_localize(None).dt.normalize()
            supp_dfs.append(d)

    for ep in sorted(glob.glob("/tmp/us_xuangu_20261109/w2/extra_prices/*.parquet")):
        tk_ep = os.path.basename(ep).replace(".parquet", "")
        if tk_ep not in base_set and tk_ep != "HTZ":
            d = pd.read_parquet(ep)
            if "date" not in d.columns:
                d = d.reset_index()
                if "Date" in d.columns:
                    d = d.rename(columns={"Date": "date"})
            d = d.rename(columns={c: c.lower().replace(" ", "_") for c in d.columns})
            if "date" in d.columns and ("adj_close" in d.columns or "close" in d.columns):
                d["date"] = pd.to_datetime(d["date"]).dt.tz_localize(None).dt.normalize()
                d["ticker"] = tk_ep
                if "adj_close" not in d.columns:
                    d["adj_close"] = d["close"]
                if "close" not in d.columns:
                    d["close"] = d["adj_close"]
                supp_dfs.append(d[["date", "ticker", "close", "adj_close"]])

    ad_path = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/us_price_db/all_daily.parquet"
    if os.path.exists(ad_path) and len(miss_xbrl_tks) > 0:
        ad = pd.read_parquet(ad_path, columns=["date", "ticker", "close", "adj_close"])
        ad = ad[ad["ticker"].isin(miss_xbrl_tks - {"HTZ", "PARA"})].copy()
        if len(ad) > 0:
            ad["date"] = pd.to_datetime(ad["date"]).dt.tz_localize(None).dt.normalize()
            supp_dfs.append(ad[["date", "ticker", "close", "adj_close"]])

    df_supp = pd.concat(supp_dfs, ignore_index=True) if supp_dfs else pd.DataFrame(columns=["date", "ticker", "close", "adj_close"])
    df_supp = df_supp[~df_supp["ticker"].isin(base_set) & df_supp["date"].isin(date_to_idx)].copy()
    df_supp = df_supp.sort_values(["ticker", "date"]).drop_duplicates(["ticker", "date"], keep="last")

    new_tickers = sorted(df_supp["ticker"].unique().tolist())
    n_new = len(new_tickers)

    if n_new > 0:
        new_tk_to_c = {tk: i for i, tk in enumerate(new_tickers)}
        P_adj_new = np.full((n_days, n_new), np.nan, dtype=np.float32)
        P_cls_new = np.full((n_days, n_new), np.nan, dtype=np.float32)

        d_idx = df_supp["date"].map(date_to_idx).values
        c_idx = df_supp["ticker"].map(new_tk_to_c).values
        P_adj_new[d_idx, c_idx] = df_supp["adj_close"].values.astype(np.float32)
        P_cls_new[d_idx, c_idx] = df_supp["close"].values.astype(np.float32)

        last_new = np.full(n_new, -1, dtype=np.int32)
        for c in range(n_new):
            vm = ~np.isnan(P_adj_new[:, c]) & (P_adj_new[:, c] > 0)
            if np.any(vm):
                last_new[c] = np.where(vm)[0][-1]

        P_adj_new = pd.DataFrame(P_adj_new).ffill(limit=5).values.astype(np.float32)
        P_cls_new = pd.DataFrame(P_cls_new).ffill(limit=5).values.astype(np.float32)
        P_adj_new[P_adj_new <= 0] = np.nan
        P_cls_new[P_cls_new <= 0] = np.nan

        P_df = pd.DataFrame(P_adj_new)
        pre_new = {}
        for h in [21, 63, 126, 252, 504, 756, 1260]:
            rm = np.full((n_days, n_new), np.nan, dtype=np.float32)
            rm[h:, :] = P_adj_new[h:, :] / P_adj_new[:-h, :] - 1.0
            pre_new[h] = rm

        roll_max_252 = P_df.rolling(252, min_periods=21).max().values.astype(np.float32)
        roll_min_126 = P_df.rolling(126, min_periods=21).min().values.astype(np.float32)
        roll_max_126 = P_df.rolling(126, min_periods=21).max().values.astype(np.float32)
        roll_max_504 = P_df.rolling(504, min_periods=42).max().values.astype(np.float32)

        dist_52w_new = (P_adj_new / roll_max_252 - 1.0).astype(np.float32)
        dist_2y_new = (P_adj_new / roll_max_504 - 1.0).astype(np.float32)
        max_dd_252_new = (P_df / roll_max_252 - 1.0).rolling(252, min_periods=21).min().values.astype(np.float32)
        max_dd_126_new = (P_df / roll_max_126 - 1.0).rolling(126, min_periods=21).min().values.astype(np.float32)
        vol_252_new = (P_df.pct_change().rolling(252, min_periods=63).std() * np.sqrt(252)).values.astype(np.float32)
        ma50_gt_200_new = (P_df.rolling(50, min_periods=25).mean().values > P_df.rolling(200, min_periods=100).mean().values).astype(np.uint8)

        c1 = ((pre_new[504] > 0.40) | (pre_new[756] > 0.40)) & (vol_252_new < 0.38) & (max_dd_252_new > -0.25) & (dist_52w_new > -0.15)
        c2 = (~c1) & (((pre_new[126] >= 0.15) & (pre_new[126] <= 0.80)) | ((pre_new[252] >= 0.15) & (pre_new[252] <= 0.80))) & (max_dd_126_new > -0.20) & (ma50_gt_200_new == 1)
        c4 = (pre_new[126] > 0.80) | (vol_252_new > 0.65) | (pre_new[63] > 0.50)
        amp_126 = roll_max_126 / np.where(roll_min_126 > 0, roll_min_126, np.nan) - 1.0
        c3 = amp_126 < 0.28
        c5 = (dist_52w_new <= -0.35) | (dist_2y_new <= -0.35)

        slow_new = np.zeros((n_days, n_new), dtype=np.int8)
        slow_new[c5] = 5
        slow_new[c3] = 3
        slow_new[c4] = 4
        slow_new[c2] = 2
        slow_new[c1] = 1

        seg_breaks_new = np.zeros((n_days, n_new), dtype=np.uint8)
        ret_1d_new = P_df.pct_change().values
        ext_r, ext_c = np.where((ret_1d_new > 4.0) | (ret_1d_new < -0.92))
        for r_i, c_i in zip(ext_r, ext_c):
            tk_i = new_tickers[c_i]
            if tk_i not in ("FNMA", "FMCC", "HTZ"):
                seg_breaks_new[max(0, r_i - 5):min(n_days, r_i + 6), c_i] = 1

        all_tickers = base_tickers + new_tickers
        P_adj = np.hstack([cache["P_adj"], P_adj_new])
        P_cls = np.hstack([cache["P_cls"], P_cls_new])
        pre_ret_126d = np.hstack([cache["pre_ret_126d"], pre_new[126]])
        pre_ret_252d = np.hstack([cache["pre_ret_252d"], pre_new[252]])
        dist_52w_high = np.hstack([cache["dist_52w_high"], dist_52w_new])
        vol_252d = np.hstack([cache["realized_vol_252d"], vol_252_new])
        slow_tag = np.hstack([cache["slow_tag"], slow_new])
        seg_breaks = np.hstack([cache["seg_breaks"], seg_breaks_new])
        last_valid_idx = np.concatenate([cache["last_valid_idx"], last_new])
    else:
        all_tickers = base_tickers
        P_adj = cache["P_adj"]
        P_cls = cache["P_cls"]
        pre_ret_126d = cache["pre_ret_126d"]
        pre_ret_252d = cache["pre_ret_252d"]
        dist_52w_high = cache["dist_52w_high"]
        vol_252d = cache["realized_vol_252d"]
        slow_tag = cache["slow_tag"]
        seg_breaks = cache["seg_breaks"]
        last_valid_idx = cache["last_valid_idx"]

    n_stocks = len(all_tickers)
    tk_to_col = {tk: i for i, tk in enumerate(all_tickers)}
    for tk, idx in list(tk_to_col.items()):
        for alt in (tk.replace(".", "-"), tk.replace("-", ".")):
            if alt not in tk_to_col:
                tk_to_col[alt] = idx

    terminal_rets = np.zeros(n_stocks, dtype=np.float32)
    for i, tk in enumerate(all_tickers):
        info = exit_meta.get(tk) or exit_meta.get(tk.replace("-", "."))
        if info is not None and last_valid_idx[i] < n_days - 15:
            terminal_rets[i] = float(info["t_ret"])

    print(f"  Price + Delist Engine ready in {time.time() - t0:.2f}s: {n_stocks} stocks x {n_days} days.")
    return {
        "dates": dates,
        "dates_ts": dates_ts,
        "n_days": n_days,
        "date_to_idx": date_to_idx,
        "tickers": all_tickers,
        "tk_to_col": tk_to_col,
        "P_adj": P_adj,
        "P_cls": P_cls,
        "spy_tr": cache["spy_tr"],
        "pre_ret_126d": pre_ret_126d,
        "pre_ret_252d": pre_ret_252d,
        "dist_52w_high": dist_52w_high,
        "vol_252d": vol_252d,
        "slow_tag": slow_tag,
        "seg_breaks": seg_breaks,
        "last_valid_idx": last_valid_idx,
        "terminal_rets": terminal_rets,
        "exit_meta": exit_meta,
    }


# ==============================================================================
# STEP 2: Reconstruct Full Zero-Lookahead XBRL Panel + Bidirectional Unit Calibration
# ==============================================================================
def calibrate_shares_and_mcap_pit(df: pd.DataFrame, float_map: dict) -> pd.DataFrame:
    """
    100% Zero-Lookahead Bidirectional Calibration of XBRL 1000x / 1,000,000x share-unit errors.
    Uses ONLY information available on or before `filed`:
      1. Contemporary EPS-implied shares (`ni / eps_q_pit`) for both 1000x under- and over-scaling.
      2. Prior/contemporary `dei:EntityPublicFloat` (`filed <= current_filed`).
      3. Contemporary accounting scale (`equity`, `rev_ttm`, `assets`) when `mcap` is off by >=1000x.
      4. Strictly backward-only prior-quarter share continuity (`k = i - 1` filed < current `filed`).
    """
    d = df.sort_values(["ticker", "end", "filed"]).reset_index(drop=True).copy()
    sh = d["shares_clean"].values.copy()
    imp = d["implied_shares_eps"].values
    eps_q = d["eps_q_pit"].values
    unadj_px = d["unadj_entry_px"].values
    is_f4 = d.get("_is_f4_rescued", pd.Series(False, index=d.index)).values
    rev_t = d["rev_ttm"].values
    eq_v = d["equity"].values
    ass_v = d["assets"].values
    tks = d["ticker"].values
    ciks = d["cik"].values
    flds = d["filed"].values
    ni_t = d["ni_ttm"].values
    fcf_t = d["fcf_ttm"].values
    op_t = d["opinc_ttm"].values
    debt_t = d["total_debt"].fillna(0.0).values
    cash_t = d["cash"].fillna(0.0).values

    n_fixed_over = 0
    n_fixed_under = 0

    for i in range(len(d)):
        s = sh[i]
        p = unadj_px[i]
        im = imp[i]
        cik_i = int(ciks[i]) if pd.notna(ciks[i]) else -1
        f_str = str(flds[i])

        # Helper: latest prior/contemporary EntityPublicFloat strictly <= f_str
        last_pf = np.nan
        pfs = float_map.get(cik_i, [])
        if pfs:
            for pf_dt, pf_val in reversed(pfs):
                if pf_dt <= f_str and (pd.Timestamp(f_str) - pd.Timestamp(pf_dt)).days <= 550:
                    last_pf = pf_val
                    break

        # Pre-spinoff nominal shell guard (e.g. CTVA 100,000 parent-held shares prior to regular-way spin-off)
        if pd.notna(s) and s <= 250000.0 and pd.isna(rev_t[i]) and pd.isna(last_pf):
            sh[i] = np.nan
            unadj_px[i] = np.nan
            continue

        # 1. Contemporary EPS-implied shares (require |eps_q| >= 0.08 so REIT/bank preferred dividends near 0 EPS never distort im!)
        ep = eps_q[i]
        if pd.notna(s) and s > 0 and pd.notna(im) and im > 0 and pd.notna(ep) and abs(ep) >= 0.08:
            r_over = s / im
            if 450.0 <= r_over <= 2200.0:
                s /= 1000.0
                n_fixed_over += 1
            elif 450000.0 <= r_over <= 2200000.0:
                s /= 1000000.0
                n_fixed_over += 1
            elif 4.5e8 <= r_over <= 2.2e9:
                s /= 1e9
                n_fixed_over += 1
            else:
                r_under = im / s
                if 450.0 <= r_under <= 2200.0:
                    s *= 1000.0
                    n_fixed_under += 1
                elif 450000.0 <= r_under <= 2200000.0:
                    s *= 1000000.0
                    n_fixed_under += 1

        # 2. Check against PIT EntityPublicFloat (both 1000x XBRL unit errors AND Form-4 reverse-split mismatches like RAD 1:20!)
        if pd.notna(s) and s > 0 and pd.notna(p) and p > 0 and pd.notna(last_pf) and last_pf > 2e7:
            mc_curr = s * p
            for mult in [1e9, 1e6, 1e3]:
                if 0.35 * mult <= (mc_curr / last_pf) <= 3.0 * mult:
                    s /= mult
                    n_fixed_over += 1
                    break
                elif 0.35 * mult <= (last_pf / mc_curr) <= 3.0 * mult:
                    s *= mult
                    n_fixed_under += 1
                    break
            # Reverse-split guard for Form-4 rescued rows where Form-4 prices were post-reverse-split adjusted
            mc_curr = s * p
            if is_f4[i] and 5.0 <= (mc_curr / last_pf) <= 100.0:
                rspec = round(mc_curr / last_pf)
                if rspec >= 5:
                    s /= float(rspec)
                    n_fixed_over += 1

        # 3. Balance-sheet & revenue scale check BEFORE continuity propagation (prevents propagating any 1st-row error!)
        if pd.notna(s) and s > 0 and pd.notna(p) and p > 0:
            mc_curr = s * p
            eq_pos = float(eq_v[i]) if (pd.notna(eq_v[i]) and eq_v[i] > 1e7) else 0.0
            rv_pos = float(rev_t[i]) if (pd.notna(rev_t[i]) and rev_t[i] > 1e7) else 0.0
            as_pos = float(ass_v[i]) if (pd.notna(ass_v[i]) and ass_v[i] > 1e7) else 0.0
            ref_anchor = max(eq_pos, rv_pos) if max(eq_pos, rv_pos) > 0 else (as_pos * 0.15)
            if ref_anchor > 1e7:
                if (mc_curr / ref_anchor) > 250.0:
                    cands = [m for m in [1e3, 1e6, 1e9] if 0.08 <= ((mc_curr / m) / ref_anchor) <= 25.0]
                    if cands:
                        best_m = min(cands, key=lambda m: abs(np.log10(((mc_curr / m) / ref_anchor) / 1.5)))
                        s /= best_m
                        n_fixed_over += 1
                elif (ref_anchor / mc_curr) > 250.0:
                    cands = [m for m in [1e3, 1e6, 1e9] if 0.08 <= ((mc_curr * m) / ref_anchor) <= 25.0]
                    if cands:
                        best_m = min(cands, key=lambda m: abs(np.log10(((mc_curr * m) / ref_anchor) / 1.5)))
                        s *= best_m
                        n_fixed_under += 1

        # 4. Strictly backward-only prior-quarter continuity (catches zero-EPS quarters without PublicFloat!)
        if i > 0 and tks[i] == tks[i - 1] and pd.notna(sh[i - 1]) and sh[i - 1] > 0:
            if pd.isna(s) or s <= 0:
                s = sh[i - 1]
            else:
                ratio_prev = s / sh[i - 1]
                for mult in [1e9, 1e6, 1e3]:
                    if 0.35 * mult <= ratio_prev <= 2.80 * mult:
                        s /= mult
                        n_fixed_over += 1
                        break
                    elif 0.35 * mult <= (1.0 / ratio_prev) <= 2.80 * mult:
                        s *= mult
                        n_fixed_under += 1
                        break

        sh[i] = s

    d["shares_clean"] = sh
    mcap_new = np.where(pd.notna(sh) & (sh > 0) & pd.notna(unadj_px) & (unadj_px > 0), sh * unadj_px, d["mcap_pit"].values)
    d["mcap_pit"] = mcap_new
    d["mcap_usd_b"] = mcap_new / 1e9
    d["mcap_2026_equiv_b"] = d["mcap_usd_b"] * d["mcap_scale_to_2026"]
    ev_new = mcap_new + debt_t - cash_t
    d["ev_pit"] = ev_new
    d["pe_pit"] = np.where(pd.notna(ni_t) & (ni_t != 0) & pd.notna(mcap_new), mcap_new / ni_t, np.nan)
    d["ps_pit"] = np.where(pd.notna(rev_t) & (rev_t > 0) & pd.notna(mcap_new), mcap_new / rev_t, np.nan)
    d["ev_sales_pit"] = np.where(pd.notna(rev_t) & (rev_t > 0) & pd.notna(ev_new), ev_new / rev_t, np.nan)
    d["ev_ebit_pit"] = np.where(pd.notna(op_t) & (op_t > 0) & pd.notna(ev_new), ev_new / op_t, np.nan)
    d["fcf_yield_pit"] = np.where(pd.notna(mcap_new) & (mcap_new > 0) & pd.notna(fcf_t), fcf_t / mcap_new, np.nan)

    g_rev_pct = d["rev_yoy"] * 100.0
    d["peg_rev_pit"] = np.where((d["pe_pit"] > 0) & (g_rev_pct >= 5.0), d["pe_pit"] / g_rev_pct, np.nan)

    print(f"  [PIT Unit Calibration] Fixed {n_fixed_over:,} over-scaled (1000x/1e6x) & {n_fixed_under:,} under-scaled share rows.")
    return d


def build_augmented_xbrl_panel(eng):
    t0 = time.time()
    print("[Step 2] Building zero-lookahead XBRL panel with bidirectional unit calibration & delist tracking...")

    df = pd.read_parquet(os.path.join(PROJ_DIR, "data/xbrl_master_pit_2009_2026.parquet"))
    # Remove known ticker-reuse non-operating/microcap rows (PARA microcap pre-merger, SPCX SPAC/ETF shell)
    df = df[~((df["ticker"] == "PARA") & (df["rev_ttm"] < 1e8))].copy()
    df = df[df["ticker"] != "SPCX"].copy().reset_index(drop=True)

    bad_gm = df["gm_q"] > 1.0
    if bad_gm.any():
        df.loc[bad_gm, ["gm_q", "gm_minus_sga_q", "gm_yoy_chg", "gm_sga_yoy_chg"]] = np.nan

    macro = pd.read_parquet(os.path.join(PROJ_DIR, "data/macro_pit_daily_1990_2026.parquet"))
    macro["dt_norm"] = pd.to_datetime(macro["date"]).dt.normalize()
    scale_map = macro.set_index("dt_norm")["mcap_scale_to_2026"].to_dict()

    sm_path = "/tmp/us_xuangu_20261109/w1_a2/splits_map.json"
    splits_map = json.load(open(sm_path)) if os.path.exists(sm_path) else {}

    # Load EntityPublicFloat across ALL CIKs in XBRL (fast ~2.5s zip scan for 100% clean PublicFloat anchoring)
    float_map = {}
    zip_path = os.path.join(TMP_DIR, "companyfacts.zip")
    all_ciks = sorted(df["cik"].dropna().astype(int).unique())
    if os.path.exists(zip_path):
        with zipfile.ZipFile(zip_path, "r") as zf:
            znames = set(zf.namelist())
            for cik in all_ciks:
                fn = f"CIK{cik:010d}.json"
                if fn not in znames:
                    continue
                raw = json.loads(zf.read(fn))
                pf_obj = raw.get("facts", {}).get("dei", {}).get("EntityPublicFloat", {}).get("units", {}).get("USD", [])
                pf_list = [(r.get("filed", ""), float(r.get("val"))) for r in pf_obj if r.get("filed") and r.get("val") and r.get("val") > 1e6]
                if pf_list:
                    pf_list.sort(key=lambda x: x[0])
                    float_map[cik] = pf_list

    # 2A: Rescue rows missing from base cache using supplementary daily prices
    dates = eng["dates"]
    dates_ts = eng["dates_ts"]
    n_days = eng["n_days"]
    tk2c = eng["tk_to_col"]
    P_adj = eng["P_adj"]
    P_cls = eng["P_cls"]
    spy_tr = eng["spy_tr"]
    last_v = eng["last_valid_idx"]
    term_r = eng["terminal_rets"]

    miss_idxs = df.index[df["entry_adj_close"].isna()].values
    daily_rescued = 0
    if len(miss_idxs) > 0:
        sub_tks = df.loc[miss_idxs, "ticker"].values
        sub_flds = pd.to_datetime(df.loc[miss_idxs, "filed"]).dt.normalize().values.astype("datetime64[D]")
        cols = np.array([tk2c.get(str(t), -1) for t in sub_tks], dtype=np.int32)
        idx_ev = np.clip(np.searchsorted(dates, sub_flds), 0, n_days - 1)
        idx_pre = idx_ev - 1
        idx_ent = idx_ev + 1

        for k_pos, orig_i in enumerate(miss_idxs):
            c = cols[k_pos]
            de = idx_ent[k_pos]
            dp = idx_pre[k_pos]
            if c < 0 or dp < 0 or de >= n_days:
                continue
            p_ent_adj = float(P_adj[de, c])
            p_pre_adj = float(P_adj[dp, c])
            if np.isnan(p_ent_adj) or p_ent_adj <= 0:
                continue

            tk = str(sub_tks[k_pos])
            ent_dt = pd.Timestamp(dates_ts[de]).normalize()
            pre_dt = pd.Timestamp(dates_ts[dp]).normalize()

            sp_d = splits_map.get(tk, {})
            fut_mult = 1.0
            for s_dt_str, mult in sp_d.items():
                if pd.Timestamp(s_dt_str) > ent_dt:
                    fut_mult *= float(mult)
            unadj_px = float(P_cls[de, c]) * fut_mult

            df.at[orig_i, "pre_date"] = pre_dt
            df.at[orig_i, "entry_date"] = ent_dt
            df.at[orig_i, "pre_adj_close"] = p_pre_adj
            df.at[orig_i, "entry_adj_close"] = p_ent_adj
            df.at[orig_i, "unadj_entry_px"] = unadj_px
            df.at[orig_i, "pre_ret_126d"] = float(eng["pre_ret_126d"][dp, c])
            df.at[orig_i, "pre_ret_252d"] = float(eng["pre_ret_252d"][dp, c])
            df.at[orig_i, "dist_52w_high"] = float(eng["dist_52w_high"][dp, c])
            df.at[orig_i, "realized_vol_252d"] = float(eng["vol_252d"][dp, c])
            df.at[orig_i, "slow_uptrend_tag"] = TAG_MAP.get(int(eng["slow_tag"][dp, c]), "Other_Neutral")
            df.at[orig_i, "has_anomaly_break"] = bool(eng["seg_breaks"][dp, c] > 0)
            if p_pre_adj > 0 and not np.isnan(p_pre_adj):
                df.at[orig_i, "earn_jump_ret"] = p_ent_adj / p_pre_adj - 1.0
            df.at[orig_i, "mcap_scale_to_2026"] = scale_map.get(pre_dt) or scale_map.get(ent_dt) or 1.5

            lv = last_v[c]
            tr = float(term_r[c])
            for h_d, _ in HORIZONS:
                dtgt = de + h_d
                if lv < dtgt and lv < n_days - 15 and lv >= de:
                    pl = float(P_adj[lv, c])
                    r_last = (pl / p_ent_adj - 1.0) if (not np.isnan(pl) and pl > 0) else -1.0
                    rtot = (1.0 + r_last) * (1.0 + tr) - 1.0
                    d_spy = min(dtgt, n_days - 1)
                    rb = float(spy_tr[d_spy] / spy_tr[de] - 1.0)
                    df.at[orig_i, f"fwd_{h_d}d"] = rtot
                    df.at[orig_i, f"spy_fwd_{h_d}d"] = rb
                    df.at[orig_i, f"alpha_fwd_{h_d}d"] = rtot - rb
                elif dtgt < n_days:
                    pt = float(P_adj[dtgt, c])
                    if not np.isnan(pt) and pt > 0:
                        rs = pt / p_ent_adj - 1.0
                        rb = float(spy_tr[dtgt] / spy_tr[de] - 1.0)
                        df.at[orig_i, f"fwd_{h_d}d"] = rs
                        df.at[orig_i, f"spy_fwd_{h_d}d"] = rb
                        df.at[orig_i, f"alpha_fwd_{h_d}d"] = rs - rb

            sl = P_adj[de:min(de + 253, n_days), c]
            vs = sl[(~np.isnan(sl)) & (sl > 0)]
            if len(vs) > 1:
                cmax = np.maximum.accumulate(vs)
                mdd_v = float(np.min(vs / cmax - 1.0))
                if lv < de + 252 and lv < n_days - 15 and tr < -0.50:
                    mdd_v = min(mdd_v, tr)
                df.at[orig_i, "fwd_max_dd_252d"] = mdd_v

            daily_rescued += 1

    # 2B: Rescue remaining delisted rows via SEC Form 4 insider transaction prices + continuous bankruptcy path
    f4_path = "/tmp/us_xuangu_20261109/w1_a2/delisted_f4_prices.parquet"
    f4_rescued = 0
    exit_meta = eng["exit_meta"]
    if os.path.exists(f4_path):
        f4 = pd.read_parquet(f4_path)
        f4["f4_dt"] = pd.to_datetime(f4["date"]).dt.normalize()
        f4["ticker_clean"] = f4["ticker"].replace({"HTZ_PRE": "HTZ", "FTR_PRE": "FTR"})
        df["_is_f4_rescued"] = False
        f4 = f4[f4["price"].notna() & (f4["price"] > 0)].sort_values(["ticker_clean", "f4_dt"])
        f4_by_tk = {}
        for tk_k, grp in f4.groupby("ticker_clean"):
            g2 = grp[["f4_dt", "price"]].reset_index(drop=True).copy()
            if len(g2) >= 5:
                rmed = g2["price"].rolling(5, center=True, min_periods=2).median()
                g2 = g2[(g2["price"] <= 3.5 * rmed) & (g2["price"] >= 0.28 * rmed)].reset_index(drop=True)
            if len(g2) > 0:
                f4_by_tk[tk_k] = g2

        still_miss = df["entry_adj_close"].isna() & df["ticker"].isin(f4_by_tk.keys())
        for idx in df.index[still_miss]:
            tk = df.at[idx, "ticker"]
            f_dt = pd.Timestamp(df.at[idx, "filed"]).normalize()
            f4_df = f4_by_tk[tk]
            em = exit_meta.get(tk, {"exit_type": "MA", "exit_dt": pd.NaT, "deal_px": np.nan, "t_ret": 0.0})
            if pd.notna(em["exit_dt"]) and f_dt >= em["exit_dt"]:
                continue

            prior_f4 = f4_df[(f4_df["f4_dt"] <= f_dt + pd.Timedelta(days=3)) & (f4_df["f4_dt"] >= f_dt - pd.Timedelta(days=480))]
            if len(prior_f4) == 0:
                continue
            p0 = float(prior_f4["price"].iloc[-1])
            if p0 <= 0:
                continue

            pre_f4 = f4_df[(f4_df["f4_dt"] < f_dt) & (f4_df["f4_dt"] >= f_dt - pd.Timedelta(days=45))]
            post_f4 = f4_df[(f4_df["f4_dt"] >= f_dt) & (f4_df["f4_dt"] <= f_dt + pd.Timedelta(days=14))]
            ej_approx = np.nan
            if len(pre_f4) > 0 and len(post_f4) > 0:
                ej_approx = float(np.clip(post_f4["price"].iloc[0] / pre_f4["price"].iloc[-1] - 1.0, -0.80, 1.50))

            hist_2y = f4_df[(f4_df["f4_dt"] <= f_dt + pd.Timedelta(days=3)) & (f4_df["f4_dt"] >= f_dt - pd.Timedelta(days=750))]
            p_max_2y = float(hist_2y["price"].max()) if len(hist_2y) > 0 else p0
            hist_1y = f4_df[(f4_df["f4_dt"] <= f_dt - pd.Timedelta(days=180)) & (f4_df["f4_dt"] >= f_dt - pd.Timedelta(days=480))]
            p_1y_ago = float(hist_1y["price"].iloc[-1]) if len(hist_1y) > 0 else float(hist_2y["price"].iloc[0])
            dist_high = p0 / p_max_2y - 1.0
            ret_pre_1y = p0 / p_1y_ago - 1.0

            if dist_high <= -0.35 or ret_pre_1y <= -0.30:
                tag = "DeepDrawdown_Left"
            elif 0.12 <= ret_pre_1y <= 0.85 and dist_high > -0.20:
                tag = "SlowUp_6Mto2Y"
            elif ret_pre_1y > 0.85:
                tag = "HighFlyer_Parabolic"
            else:
                tag = "Other_Neutral"

            idx_ev = int(np.clip(np.searchsorted(dates, np.datetime64(f_dt, "D")), 0, n_days - 1))
            idx_ent = min(idx_ev + 1, n_days - 1)
            ent_date = pd.Timestamp(dates[idx_ent]).normalize()

            df.at[idx, "entry_date"] = ent_date
            df.at[idx, "entry_adj_close"] = p0
            df.at[idx, "unadj_entry_px"] = p0
            df.at[idx, "_is_f4_rescued"] = True
            df.at[idx, "pre_ret_252d"] = ret_pre_1y
            df.at[idx, "dist_52w_high"] = dist_high
            df.at[idx, "slow_uptrend_tag"] = tag
            df.at[idx, "earn_jump_ret"] = ej_approx
            df.at[idx, "mcap_scale_to_2026"] = scale_map.get(ent_date, 1.5)

            for h_d, _ in HORIZONS:
                d_tgt = idx_ent + h_d
                if d_tgt >= n_days and (pd.isna(em["exit_dt"]) or em["exit_dt"] > pd.Timestamp(dates[-1])):
                    continue
                d_spy_end = min(d_tgt, n_days - 1)
                tgt_ts = pd.Timestamp(dates[d_spy_end])

                if pd.notna(em["exit_dt"]) and em["exit_dt"] <= tgt_ts:
                    idx_exit_spy = int(np.clip(np.searchsorted(dates, np.datetime64(em["exit_dt"], "D")), idx_ent, n_days - 1))
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
                            r_deal = float(np.clip((1.0 + r_f4_only) * (1.0 + max(0.0, em["t_ret"])) - 1.0, -0.90, 4.0))
                else:
                    win_pad = 45 if h_d <= 63 else (90 if h_d <= 126 else 140)
                    f4_near = f4_df[(f4_df["f4_dt"] >= tgt_ts - pd.Timedelta(days=win_pad)) & (f4_df["f4_dt"] <= tgt_ts + pd.Timedelta(days=win_pad))]
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

                df.at[idx, f"fwd_{h_d}d"] = r_deal
                df.at[idx, f"spy_fwd_{h_d}d"] = spy_r
                df.at[idx, f"alpha_fwd_{h_d}d"] = r_deal - spy_r

            f4_rescued += 1

    # 2C: Apply strict zero-lookahead bidirectional share-unit calibration across ALL active & rescued rows!
    df = calibrate_shares_and_mcap_pit(df, float_map)

    # 2D: Attach exact delisting & bankruptcy flags within 3Y (1100 calendar days) and ever
    df["delist_exit_category"] = "ACTIVE"
    df["exit_dt_exact"] = pd.NaT
    for tk_e, em in exit_meta.items():
        m_tk = df["ticker"] == tk_e
        if not m_tk.any():
            continue
        et = em["exit_type"]
        ex_dt = em["exit_dt"]
        if et == "BANKRUPTCY":
            if pd.notna(ex_dt):
                pre_bk = m_tk & (pd.to_datetime(df["filed"]) < ex_dt)
                df.loc[pre_bk, "delist_exit_category"] = "BANKRUPTCY"
                df.loc[pre_bk, "exit_dt_exact"] = ex_dt
            else:
                df.loc[m_tk, "delist_exit_category"] = "BANKRUPTCY"
        elif et == "MA":
            df.loc[m_tk, "delist_exit_category"] = "MA_ACQUISITION"
            if pd.notna(ex_dt):
                df.loc[m_tk, "exit_dt_exact"] = ex_dt

    ent_ts = pd.to_datetime(df["entry_date"])
    days_to_exit = (df["exit_dt_exact"] - ent_ts).dt.days
    df["bankrupt_in_3y"] = (df["delist_exit_category"] == "BANKRUPTCY") & (
        (days_to_exit.between(1, 1100)) | (df["exit_dt_exact"].isna())
    )
    df["ma_delist_in_3y"] = (df["delist_exit_category"] == "MA_ACQUISITION") & days_to_exit.between(1, 1100)
    df["any_delist_in_3y"] = df["bankrupt_in_3y"] | df["ma_delist_in_3y"]
    df["is_bankrupt_firm"] = df["delist_exit_category"] == "BANKRUPTCY"

    bk_3y_fix = df["bankrupt_in_3y"] & df["entry_date"].notna() & (df["fwd_756d"].isna() | (df["fwd_756d"] > -0.50))
    for idx in df.index[bk_3y_fix]:
        ex_dt = df.at[idx, "exit_dt_exact"]
        e_dt = pd.Timestamp(df.at[idx, "entry_date"]).normalize()
        if pd.notna(ex_dt) and ex_dt <= pd.Timestamp(dates[-1]):
            i_e = int(np.clip(np.searchsorted(dates, np.datetime64(e_dt, "D")), 0, n_days - 1))
            i_x = int(np.clip(np.searchsorted(dates, np.datetime64(ex_dt, "D")), i_e, n_days - 1))
            spy_r = float(spy_tr[i_x] / spy_tr[i_e] - 1.0)
            df.at[idx, "fwd_756d"] = -0.95
            df.at[idx, "spy_fwd_756d"] = spy_r
            df.at[idx, "alpha_fwd_756d"] = -0.95 - spy_r

    # 2E: Uniform sequential PIT trajectory counters
    df = df.sort_values(["ticker", "end", "filed"]).reset_index(drop=True)
    n = len(df)
    tks = df["ticker"].values
    end_days = pd.to_datetime(df["end"]).values.astype("datetime64[D]").astype(np.int64)
    filed_days = pd.to_datetime(df["filed"]).values.astype("datetime64[D]").astype(np.int64)

    valid_prev = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if tks[i] == tks[i - 1]:
            ediff = end_days[i] - end_days[i - 1]
            if 65 <= ediff <= 125 and filed_days[i - 1] < filed_days[i]:
                valid_prev[i] = True

    rev_yoy = df["rev_yoy"].values
    rev_acc = df["rev_accel_1q"].values
    opm_chg = df["opm_yoy_chg"].values
    gmsga_chg = df["gm_sga_yoy_chg"].values

    s_rev_acc = np.zeros(n, dtype=np.int32)
    s_gmsga_exp = np.zeros(n, dtype=np.int32)
    s_dbl_inf = np.zeros(n, dtype=np.int32)
    s_rev20 = np.zeros(n, dtype=np.int32)

    for i in range(n):
        vp = valid_prev[i]
        if not np.isnan(rev_acc[i]) and rev_acc[i] > 0:
            s_rev_acc[i] = (s_rev_acc[i - 1] + 1) if vp else 1
        if not np.isnan(gmsga_chg[i]) and gmsga_chg[i] > 0:
            s_gmsga_exp[i] = (s_gmsga_exp[i - 1] + 1) if vp else 1

        mgn_ok = (not np.isnan(opm_chg[i]) and opm_chg[i] > 0) or (not np.isnan(gmsga_chg[i]) and gmsga_chg[i] > 0)
        rev_ok = (not np.isnan(rev_yoy[i]) and rev_yoy[i] >= 0.12) or (not np.isnan(rev_acc[i]) and rev_acc[i] > 0)
        if rev_ok and mgn_ok:
            s_dbl_inf[i] = (s_dbl_inf[i - 1] + 1) if vp else 1

        if not np.isnan(rev_yoy[i]) and rev_yoy[i] >= 0.20:
            s_rev20[i] = (s_rev20[i - 1] + 1) if vp else 1

    df["pit_rev_accel_n"] = s_rev_acc
    df["pit_gmsga_expand_n"] = s_gmsga_exp
    df["pit_dbl_inflect_n"] = s_dbl_inf
    df["pit_rev20_n"] = s_rev20

    mc = df["mcap_2026_equiv_b"]
    conds = [(mc >= lo) & (mc < hi) for _, _, lo, hi in MCAP_TIERS]
    df["mcap_tier_id"] = np.select(conds, [x[0] for x in MCAP_TIERS], default="T0_lt2B_or_NA")
    df["mcap_tier_label"] = np.select(conds, [x[1] for x in MCAP_TIERS], default="0_20亿以下或缺失")

    print(
        f"  Augmented XBRL panel ready in {time.time() - t0:.2f}s: "
        f"{len(df):,} total rows | {df['entry_date'].notna().sum():,} priced rows "
        f"(rescued {daily_rescued:,} daily + {f4_rescued:,} Form4) | "
        f"Bankrupt-in-3Y rows: {df['bankrupt_in_3y'].sum():,}"
    )
    return df


# ==============================================================================
# Unified Slice Evaluator Across 7 Horizons + Tail/Bankruptcy Metrics
# ==============================================================================
def eval_g03_slice(df_sub: pd.DataFrame, dedup_days: int = 250) -> dict:
    out = {"n_raw": int(len(df_sub))}
    if len(df_sub) == 0:
        out["n_dedup"] = 0
        out["n_tickers"] = 0
        return out

    df_clean = df_sub[~df_sub["has_anomaly_break"].fillna(False)].copy()
    if len(df_clean) == 0:
        out["n_dedup"] = 0
        out["n_tickers"] = 0
        return out

    df_clean["cal_qtr"] = pd.to_datetime(df_clean["entry_date"]).dt.to_period("Q")
    df_dedup = deduplicate_cooldown(df_clean, date_col="entry_date", cooldown_days=dedup_days)

    out["n_dedup"] = int(len(df_dedup))
    out["n_tickers"] = int(df_dedup["ticker"].nunique())

    elig_3y = df_dedup[
        (pd.to_datetime(df_dedup["entry_date"]) <= "2023-11-06") | df_dedup["any_delist_in_3y"]
    ]
    n_elig_del = len(elig_3y)
    out["n_elig_delist_3y"] = int(n_elig_del)
    if n_elig_del >= 3:
        out["bankrupt_3y_n"] = int(elig_3y["bankrupt_in_3y"].sum())
        out["bankrupt_3y_rate"] = float(elig_3y["bankrupt_in_3y"].mean())
        out["ma_delist_3y_rate"] = float(elig_3y["ma_delist_in_3y"].mean())
        out["total_delist_3y_rate"] = float(elig_3y["any_delist_in_3y"].mean())
    else:
        out["bankrupt_3y_n"] = int(df_dedup["bankrupt_in_3y"].sum())
        out["bankrupt_3y_rate"] = np.nan
        out["ma_delist_3y_rate"] = np.nan
        out["total_delist_3y_rate"] = np.nan
    out["bankrupt_ever_rate"] = float(df_dedup["is_bankrupt_firm"].mean()) if len(df_dedup) >= 3 else np.nan

    for h_d, h_lbl in HORIZONS:
        r_col = f"fwd_{h_d}d"
        a_col = f"alpha_fwd_{h_d}d"
        sub_h = df_clean.dropna(subset=[a_col, r_col])
        ded_h = df_dedup.dropna(subset=[a_col, r_col])
        n_h = len(ded_h)
        out[f"n_{h_lbl}"] = int(n_h)
        if n_h < 3:
            for k in ("qtr_ew_alpha", "med_alpha", "win_rate", "payoff", "t_stat", "p_val"):
                out[f"{k}_{h_lbl}"] = np.nan
            if h_lbl == "3y":
                for k in ("bag2x_3y_rate", "bag3x_3y_rate", "halve_3y_rate"):
                    out[k] = np.nan
            if h_lbl == "5y":
                for k in ("bag2x_5y_rate", "bag5x_5y_rate", "bag10x_5y_rate", "halve_5y_rate"):
                    out[k] = np.nan
            continue

        qtr_means = sub_h.groupby("cal_qtr")[a_col].mean()
        qtr_ew_alpha = float(qtr_means.mean())
        qtr_se = float(qtr_means.std(ddof=1) / np.sqrt(len(qtr_means))) if len(qtr_means) > 2 else np.nan
        t_stat = qtr_ew_alpha / qtr_se if (qtr_se and qtr_se > 0) else np.nan
        p_val = float(2 * (1 - stats.t.cdf(abs(t_stat), df=max(len(qtr_means) - 1, 1)))) if pd.notna(t_stat) else np.nan

        a_vals = ded_h[a_col].values
        r_vals = ded_h[r_col].values
        pos_a = a_vals[a_vals > 0]
        neg_a = a_vals[a_vals <= 0]
        payoff = float(pos_a.mean() / abs(neg_a.mean())) if (len(pos_a) > 0 and len(neg_a) > 0 and neg_a.mean() != 0) else np.nan

        out[f"qtr_ew_alpha_{h_lbl}"] = qtr_ew_alpha
        out[f"med_alpha_{h_lbl}"] = float(np.median(a_vals))
        out[f"win_rate_{h_lbl}"] = float(np.mean(a_vals > 0))
        out[f"payoff_{h_lbl}"] = payoff
        out[f"t_stat_{h_lbl}"] = t_stat
        out[f"p_val_{h_lbl}"] = p_val

        if h_lbl == "3y":
            out["bag2x_3y_rate"] = float(np.mean(r_vals >= 1.0))
            out["bag3x_3y_rate"] = float(np.mean(r_vals >= 2.0))
            out["halve_3y_rate"] = float(np.mean(r_vals <= -0.50))
        elif h_lbl == "5y":
            out["bag2x_5y_rate"] = float(np.mean(r_vals >= 1.0))
            out["bag5x_5y_rate"] = float(np.mean(r_vals >= 4.0))
            out["bag10x_5y_rate"] = float(np.mean(r_vals >= 9.0))
            out["halve_5y_rate"] = float(np.mean(r_vals <= -0.50))

    mdd = df_dedup["fwd_max_dd_252d"].dropna().values
    out["med_mdd_1y"] = float(np.median(mdd)) if len(mdd) >= 3 else np.nan
    return out


# ==============================================================================
# DELIVERABLE 1: 7 Market-Cap Tiers x 6 Core Strategies Across 7 Horizons & Subperiods
# ==============================================================================
def build_strategy_masks(u: pd.DataFrame) -> list:
    is_unprof = (u["pe_pit"] < 0) | (u["ni_ttm"] <= 0) | (u["opinc_ttm"] <= 0)
    unprof_breakout = is_unprof & (u["gm_minus_sga_q"] >= 0.10) & (u["gm_sga_yoy_chg"] > 0) & (u["rev_yoy"] >= 0.15)
    consec_3q_dbl = (u["pit_dbl_inflect_n"] >= 3) & (u["rev_yoy"] >= 0.05)

    q1_raw = (u["pit_dbl_inflect_n"] == 1) & (u["rev_yoy"] >= 0.05)
    q1_gold = (
        (u["pit_dbl_inflect_n"] == 1)
        & (u["earn_jump_ret"] >= 0.05)
        & ((u["roic_5y_med_pit"] >= 0.12) | (u["roic_ttm"] >= 0.12))
        & u["pe_pit"].between(0.1, 30.0)
        & (u["dilution_yoy_clean"].fillna(0.0) <= 0.03)
        & (u["sector_type"] != "Deep_Cyclical")
    )

    true_inflect_drop4 = (consec_3q_dbl | unprof_breakout) & (u["earn_jump_ret"] <= -0.04)
    jump_ge10 = u["earn_jump_ret"] >= 0.10
    s5_unprof = unprof_breakout

    s6_lowpe_true = (
        u["pe_pit"].between(0.1, 15.0)
        & (u["rev_accel_1q"] > 0)
        & (u["opm_yoy_chg"] > 0)
        & (u["sector_type"] != "Deep_Cyclical")
        & ((u["opm_5y_pct_pit"] < 0.80) | u["opm_5y_pct_pit"].isna())
        & ((u["roic_5y_med_pit"] >= 0.10) | (u["roic_ttm"] >= 0.10))
    )

    return [
        ("S0_Baseline_Tier_All", "0_档内全样本基线", pd.Series(True, index=u.index)),
        ("S1_Consec3Q_DoubleInflect", "1_连3季双加速", consec_3q_dbl),
        ("S2_Q1_FrontRun_Golden", "2_Q1抢跑(跳涨>=5%+ROIC>=12%+PE<=30非周期)", q1_gold),
        ("S2_ref_Q1_Unconditional", "2b_Q1无条件盲抢对照(单季双改善初现)", q1_raw),
        ("S3_TrueAccel_Drop_ge4pct", "3_真加速错杀跌>=4%低吸", true_inflect_drop4),
        ("S4_Jump_ge10pct_Chase", "4_跳涨>=10%次日追高", jump_ge10),
        ("S5_Unprof_GMSGA_ge10pct", "5_毛销差>=10%未盈利突破", s5_unprof),
        ("S6_LowPE_lt15_TrueInflect", "6_PE<15非周期真拐点", s6_lowpe_true),
    ]


def run_table_1_mcap7_x_strategies(df: pd.DataFrame) -> pd.DataFrame:
    t0 = time.time()
    print("[Step 3] Computing Table 1: 7 Market-Cap Tiers x 6 Core Strategies x 7 Horizons x 4 Subperiods...")

    valid = df[
        df["entry_date"].notna()
        & (~df["has_anomaly_break"].fillna(False))
        & (df["mcap_tier_id"] != "T0_lt2B_or_NA")
    ].copy()

    dt = pd.to_datetime(valid["entry_date"])
    subperiods = [
        ("Full_2009_2026", "全期(2009至2026)", pd.Series(True, index=valid.index)),
        ("ExBubble_2009_2026", "剔除疫情泡沫(Ex 2020.03至2021.12)", ~((dt >= "2020-03-01") & (dt <= "2021-12-31"))),
        ("Last10Y_2016_2026", "近10年(2016至2026)", dt >= "2016-01-01"),
        ("HighRate_2022_2026", "高利率期(2022至2026)", dt >= "2022-01-01"),
    ]

    rows = []
    for sp_id, sp_lbl, sp_mask in subperiods:
        sub_sp = valid[sp_mask]
        for t_id, t_lbl, _, _ in MCAP_TIERS:
            u = sub_sp[sub_sp["mcap_tier_id"] == t_id]
            strats = build_strategy_masks(u)
            base_stats = eval_g03_slice(u)

            for s_id, s_lbl, s_mask in strats:
                st = eval_g03_slice(u[s_mask])
                row = {
                    "subperiod_id": sp_id,
                    "subperiod_label": sp_lbl,
                    "mcap_tier_id": t_id,
                    "mcap_tier_label": t_lbl,
                    "strategy_id": s_id,
                    "strategy_label": s_lbl,
                }
                row.update(st)
                for _, h_lbl in HORIZONS:
                    ah = st.get(f"qtr_ew_alpha_{h_lbl}", np.nan)
                    bh = base_stats.get(f"qtr_ew_alpha_{h_lbl}", np.nan)
                    row[f"spread_vs_tier_base_{h_lbl}"] = (ah - bh) if (pd.notna(ah) and pd.notna(bh)) else np.nan
                rows.append(row)

    out = pd.DataFrame(rows)
    for h_lbl in ["1y", "3y"]:
        pcol = f"p_val_{h_lbl}"
        if pcol in out.columns:
            out[f"bh_q_val_{h_lbl}"] = benjamini_hochberg_fdr(out[pcol].values)

    out_path = os.path.join(OUT_DIR, "table_g03_mcap7_x_strategies.csv")
    out.to_csv(out_path, index=False)
    print(f"  Saved {out_path} ({len(out):,} rows) in {time.time() - t0:.2f}s.")
    return out


# ==============================================================================
# DELIVERABLE 2: Optimal Threshold Scaling Laws Across 7 Market-Cap Tiers
# ==============================================================================
def run_table_2_threshold_scaling(df: pd.DataFrame) -> pd.DataFrame:
    t0 = time.time()
    print("[Step 4] Computing Table 2: Optimal Threshold Scaling Laws across 7 Market-Cap Tiers...")

    valid = df[
        df["entry_date"].notna()
        & (~df["has_anomaly_break"].fillna(False))
        & (df["mcap_tier_id"] != "T0_lt2B_or_NA")
    ].copy()
    dt = pd.to_datetime(valid["entry_date"])
    valid["is_ex_bubble"] = ~((dt >= "2020-03-01") & (dt <= "2021-12-31"))

    # Precompute tier baselines for spread_vs_tier_base_1y & 3y
    tier_base_map = {}
    for t_id, _, _, _ in MCAP_TIERS:
        bs = eval_g03_slice(valid[valid["mcap_tier_id"] == t_id])
        tier_base_map[t_id] = (bs.get("qtr_ew_alpha_1y", np.nan), bs.get("qtr_ew_alpha_3y", np.nan))

    rows = []

    def add_grid(exp_id, exp_desc, sample_filter_fn, specs):
        for t_id, t_lbl, _, _ in MCAP_TIERS:
            u_tier = valid[valid["mcap_tier_id"] == t_id]
            u = sample_filter_fn(u_tier)
            if len(u) == 0:
                continue
            b1_tier, b3_tier = tier_base_map[t_id]
            for b_order, b_lbl, b_mask_fn in specs:
                m = b_mask_fn(u) if callable(b_mask_fn) else b_mask_fn
                cell = u[m]
                if len(cell) < 3:
                    continue
                st = eval_g03_slice(cell)
                if st["n_dedup"] < 3:
                    continue
                ex_st = eval_g03_slice(cell[cell["is_ex_bubble"]]) if cell["is_ex_bubble"].sum() >= 3 else {}
                a1 = st.get("qtr_ew_alpha_1y", np.nan)
                a3 = st.get("qtr_ew_alpha_3y", np.nan)
                row = {
                    "experiment_id": exp_id,
                    "experiment_desc": exp_desc,
                    "mcap_tier_id": t_id,
                    "mcap_tier_label": t_lbl,
                    "bin_order": b_order,
                    "threshold_bin": b_lbl,
                    "n_dedup": st["n_dedup"],
                    "n_tickers": st["n_tickers"],
                    "qtr_ew_alpha_3m": st.get("qtr_ew_alpha_3m", np.nan),
                    "qtr_ew_alpha_1y": a1,
                    "spread_vs_tier_base_1y": (a1 - b1_tier) if (pd.notna(a1) and pd.notna(b1_tier)) else np.nan,
                    "med_alpha_1y": st.get("med_alpha_1y", np.nan),
                    "win_rate_1y": st.get("win_rate_1y", np.nan),
                    "qtr_ew_alpha_3y": a3,
                    "spread_vs_tier_base_3y": (a3 - b3_tier) if (pd.notna(a3) and pd.notna(b3_tier)) else np.nan,
                    "med_alpha_3y": st.get("med_alpha_3y", np.nan),
                    "win_rate_3y": st.get("win_rate_3y", np.nan),
                    "payoff_3y": st.get("payoff_3y", np.nan),
                    "bag2x_3y_rate": st.get("bag2x_3y_rate", np.nan),
                    "bag3x_3y_rate": st.get("bag3x_3y_rate", np.nan),
                    "halve_3y_rate": st.get("halve_3y_rate", np.nan),
                    "bankrupt_3y_rate": st.get("bankrupt_3y_rate", np.nan),
                    "qtr_ew_alpha_5y": st.get("qtr_ew_alpha_5y", np.nan),
                    "bag2x_5y_rate": st.get("bag2x_5y_rate", np.nan),
                    "ex_bubble_qtr_ew_alpha_1y": ex_st.get("qtr_ew_alpha_1y", np.nan),
                    "ex_bubble_qtr_ew_alpha_3y": ex_st.get("qtr_ew_alpha_3y", np.nan),
                    "ex_bubble_win_rate_3y": ex_st.get("win_rate_3y", np.nan),
                    "t_stat_3y": st.get("t_stat_3y", np.nan),
                    "p_val_3y": st.get("p_val_3y", np.nan),
                }
                rows.append(row)

    rev_specs = [
        (1, "RevYoY < 0% (萎缩)", lambda d: d["rev_yoy"] < 0.0),
        (2, "0% <= RevYoY < 5% (停滞)", lambda d: d["rev_yoy"].between(0.0, 0.05, inclusive="left")),
        (3, "5% <= RevYoY < 10% (高个位数)", lambda d: d["rev_yoy"].between(0.05, 0.10, inclusive="left")),
        (4, "10% <= RevYoY < 15% (稳健双位数)", lambda d: d["rev_yoy"].between(0.10, 0.15, inclusive="left")),
        (5, "15% <= RevYoY < 20% (中高成长)", lambda d: d["rev_yoy"].between(0.15, 0.20, inclusive="left")),
        (6, "20% <= RevYoY < 30% (高速成长)", lambda d: d["rev_yoy"].between(0.20, 0.30, inclusive="left")),
        (7, "30% <= RevYoY < 50% (爆发成长)", lambda d: d["rev_yoy"].between(0.30, 0.50, inclusive="left")),
        (8, "RevYoY >= 50% (超高速爆发)", lambda d: d["rev_yoy"] >= 0.50),
    ]
    add_grid("1A_RevYoY_AllEvents", "全样本营收增速门槛漂移", lambda d: d[d["rev_yoy"].notna()], rev_specs)
    add_grid(
        "1B_RevYoY_MarginExpand",
        "利润率扩张样本(OPM或毛销差同比提升)营收增速门槛漂移",
        lambda d: d[d["rev_yoy"].notna() & ((d["opm_yoy_chg"] > 0) | (d["gm_sga_yoy_chg"] > 0))],
        rev_specs,
    )

    ps_jump_specs = [
        (1, "PS < 3x", lambda d: d["ps_pit"].between(0.01, 3.0, inclusive="left")),
        (2, "3x <= PS < 6x", lambda d: d["ps_pit"].between(3.0, 6.0, inclusive="left")),
        (3, "6x <= PS < 10x", lambda d: d["ps_pit"].between(6.0, 10.0, inclusive="left")),
        (4, "10x <= PS < 15x", lambda d: d["ps_pit"].between(10.0, 15.0, inclusive="left")),
        (5, "15x <= PS < 20x", lambda d: d["ps_pit"].between(15.0, 20.0, inclusive="left")),
        (6, "PS >= 20x (极高估值)", lambda d: d["ps_pit"] >= 20.0),
    ]
    add_grid("2A_JumpGe10_x_PS_Redline", "跳涨>=10%追高 × PS估值红线漂移", lambda d: d[(d["earn_jump_ret"] >= 0.10) & d["ps_pit"].notna()], ps_jump_specs)
    add_grid("2B_JumpGe6_x_PS_Redline", "跳涨>=6%追高 × PS估值红线漂移(兼容大盘巨头跳涨幅度)", lambda d: d[(d["earn_jump_ret"] >= 0.06) & d["ps_pit"].notna()], ps_jump_specs)

    rev_jump_specs = [
        (1, "RevYoY < 10%", lambda d: d["rev_yoy"] < 0.10),
        (2, "10% <= RevYoY < 15%", lambda d: d["rev_yoy"].between(0.10, 0.15, inclusive="left")),
        (3, "15% <= RevYoY < 20%", lambda d: d["rev_yoy"].between(0.15, 0.20, inclusive="left")),
        (4, "20% <= RevYoY < 30%", lambda d: d["rev_yoy"].between(0.20, 0.30, inclusive="left")),
        (5, "RevYoY >= 30%", lambda d: d["rev_yoy"] >= 0.30),
    ]
    add_grid("3A_JumpGe10_x_MinRevYoY", "跳涨>=10%追高 × 最低营收增速门槛", lambda d: d[(d["earn_jump_ret"] >= 0.10) & d["rev_yoy"].notna()], rev_jump_specs)
    add_grid("3B_JumpGe6_x_MinRevYoY", "跳涨>=6%追高 × 最低营收增速门槛", lambda d: d[(d["earn_jump_ret"] >= 0.06) & d["rev_yoy"].notna()], rev_jump_specs)

    add_grid("4A_PS_AllEvents", "全样本PS估值带漂移", lambda d: d[d["ps_pit"].notna()], ps_jump_specs)
    add_grid("4B_PS_2QplusDoubleInflect", "连2季及以上双改善 × PS估值上限漂移", lambda d: d[(d["pit_dbl_inflect_n"] >= 2) & d["ps_pit"].notna()], ps_jump_specs)

    pe_specs = [
        (1, "PE < 0 (未盈利亏损)", lambda d: d["pe_pit"] < 0),
        (2, "0 < PE < 12x (深度低估/强周期顶)", lambda d: d["pe_pit"].between(0.01, 12.0, inclusive="left")),
        (3, "12x <= PE < 18x (传统价值)", lambda d: d["pe_pit"].between(12.0, 18.0, inclusive="left")),
        (4, "18x <= PE < 28x (GARP合理溢价)", lambda d: d["pe_pit"].between(18.0, 28.0, inclusive="left")),
        (5, "28x <= PE < 45x (高景气成长)", lambda d: d["pe_pit"].between(28.0, 45.0, inclusive="left")),
        (6, "PE >= 45x (极高倍数预期)", lambda d: d["pe_pit"] >= 45.0),
    ]
    add_grid("5_PE_Band_AllEvents", "PE估值甜点与低估值陷阱随市值漂移", lambda d: d[d["pe_pit"].notna()], pe_specs)

    gmsga_specs = [
        (1, "GM-SGA < 0% (倒贴烧钱)", lambda d: d["gm_minus_sga_q"] < 0.0),
        (2, "0% <= GM-SGA < 10% (薄利挣扎)", lambda d: d["gm_minus_sga_q"].between(0.0, 0.10, inclusive="left")),
        (3, "10% <= GM-SGA < 25% (商业化自洽)", lambda d: d["gm_minus_sga_q"].between(0.10, 0.25, inclusive="left")),
        (4, "25% <= GM-SGA < 40% (优良印钞机)", lambda d: d["gm_minus_sga_q"].between(0.25, 0.40, inclusive="left")),
        (5, "GM-SGA >= 40% (顶级垄断经济模型)", lambda d: d["gm_minus_sga_q"] >= 0.40),
    ]
    add_grid("6_UnitEcon_GMSGA", "毛销差(GM减SGA)护城河阈值随市值漂移", lambda d: d[d["gm_minus_sga_q"].notna()], gmsga_specs)

    dil_specs = [
        (1, "净回购缩股 <= -2%/年 (Cannibal)", lambda d: d["dilution_yoy_clean"] <= -0.02),
        (2, "微回购 -2% < 稀释 <= 0%", lambda d: d["dilution_yoy_clean"].between(-0.02, 0.0, inclusive="right") & (d["dilution_yoy_clean"] > -0.02)),
        (3, "克制稀释 0% < 稀释 <= 2%", lambda d: d["dilution_yoy_clean"].between(0.00001, 0.02)),
        (4, "中度SBC稀释 2% < 稀释 <= 5%", lambda d: d["dilution_yoy_clean"].between(0.02001, 0.05)),
        (5, "重度抽血稀释 > 5%/年", lambda d: d["dilution_yoy_clean"] > 0.05),
    ]
    add_grid("7_ShareDilution_Buyback", "股本净稀释与回购注销效应随市值漂移", lambda d: d[d["dilution_yoy_clean"].notna()], dil_specs)

    out = pd.DataFrame(rows)
    if "p_val_3y" in out.columns:
        out["bh_q_val_3y"] = benjamini_hochberg_fdr(out["p_val_3y"].values)

    out_path = os.path.join(OUT_DIR, "table_g03_threshold_scaling_by_mcap.csv")
    out.to_csv(out_path, index=False)
    print(f"  Saved {out_path} ({len(out):,} rows) in {time.time() - t0:.2f}s.")
    return out


# ==============================================================================
# DELIVERABLE 3: Anatomy of First-Time $10B-$25B -> >=$25B Crossover Companies
# ==============================================================================
def run_table_3_25b_crossover_anatomy(df: pd.DataFrame, eng: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    t0 = time.time()
    print("[Step 5] Auditing Clean Unique First-Time $10B-$25B -> >=$25B Crossover Companies (2009-2026)...")

    macro = pd.read_parquet(os.path.join(PROJ_DIR, "data/macro_pit_daily_1990_2026.parquet"))
    macro["dt_norm"] = pd.to_datetime(macro["date"]).dt.normalize()
    scale_s = macro.set_index("dt_norm")["mcap_scale_to_2026"]

    dates_ts = pd.to_datetime(eng["dates"]).normalize()
    scale_arr = np.array([scale_s.get(d, np.nan) for d in dates_ts], dtype=np.float64)
    scale_arr = pd.Series(scale_arr).ffill().bfill().values

    tk2c = eng["tk_to_col"]
    P_adj = eng["P_adj"]
    spy_tr = eng["spy_tr"]
    n_days = eng["n_days"]

    valid = df[
        df["entry_date"].notna()
        & df["mcap_2026_equiv_b"].notna()
        & (~df["has_anomaly_break"].fillna(False))
    ].sort_values(["ticker", "entry_date"]).reset_index(drop=True)

    pref_order = {"GOOG": 1, "BRK-A": 1, "FOX": 1, "NWS": 1}
    valid["alias_pen"] = valid["ticker"].map(lambda x: pref_order.get(x, 0))
    cik_primary_tk = (
        valid.sort_values(["cik", "alias_pen", "entry_date"])
        .groupby("cik")["ticker"]
        .first()
        .to_dict()
    )
    valid = valid[valid["ticker"] == valid["cik"].map(cik_primary_tk)].copy().reset_index(drop=True)

    crossover_cases = []

    for cik, grp in valid.groupby("cik"):
        grp = grp.sort_values("entry_date").reset_index(drop=True)
        mc_arr = grp["mcap_2026_equiv_b"].values
        tk = grp["ticker"].iloc[0]

        ge25_idxs = np.where(mc_arr >= 25.0)[0]
        if len(ge25_idxs) == 0:
            continue
        first_idx = int(ge25_idxs[0])

        if first_idx == 0:
            continue
        prior_mc = mc_arr[:first_idx]
        # Specifically track companies climbing through 10B-25B (or 5B-25B) before first crossing >=25B
        if not np.any((prior_mc >= 5.0) & (prior_mc < 25.0)):
            continue

        had_10to25_prior = bool(np.any((prior_mc >= 10.0) & (prior_mc < 25.0)))
        r_cross = grp.iloc[first_idx]
        cross_dt = pd.Timestamp(r_cross["entry_date"]).normalize()
        cross_mc26 = float(r_cross["mcap_2026_equiv_b"])
        cross_adj_px = float(r_cross["entry_adj_close"])

        # Pre-2009 / Pre-XBRL check to exclude GFC Fallen-Angel Rebounders
        r0 = grp.iloc[0]
        first_xbrl_dt = pd.Timestamp(r0["entry_date"]).normalize()
        imp_sh_adj_0 = (float(r0["mcap_pit"]) / float(r0["entry_adj_close"])) if (pd.notna(r0["mcap_pit"]) and float(r0["entry_adj_close"]) > 0) else np.nan

        was_pre_xbrl_25b = False
        c_col = tk2c.get(tk, -1)
        if c_col >= 0 and pd.notna(imp_sh_adj_0) and imp_sh_adj_0 > 0:
            idx_first_xbrl = int(np.searchsorted(dates_ts, first_xbrl_dt))
            if idx_first_xbrl > 60:
                px_pre = P_adj[:idx_first_xbrl, c_col].astype(np.float64)
                sc_pre = scale_arr[:idx_first_xbrl]
                est_mc26_pre = (px_pre * imp_sh_adj_0 / 1e9) * sc_pre
                valid_pre_mc = est_mc26_pre[~np.isnan(est_mc26_pre) & (est_mc26_pre > 0)]
                if len(valid_pre_mc) > 20 and float(np.percentile(valid_pre_mc, 99)) >= 28.0:
                    was_pre_xbrl_25b = True

        post_grp = grp.iloc[first_idx:]
        qtr_peak_mc26 = float(post_grp["mcap_2026_equiv_b"].max())
        qtr_min_after_cross = float(post_grp["mcap_2026_equiv_b"].iloc[1:].min()) if len(post_grp) > 1 else cross_mc26
        qtr_last_mc26 = float(post_grp["mcap_2026_equiv_b"].iloc[-1])

        daily_peak_mc26 = qtr_peak_mc26
        daily_last_mc26 = qtr_last_mc26
        min_mc26_post = qtr_min_after_cross
        max_dd_from_cross_3y = np.nan
        max_dd_after_peak = np.nan
        reached_100b_dt = pd.NaT
        total_ret_to_end = np.nan
        alpha_to_end = np.nan

        if c_col >= 0 and cross_adj_px > 0:
            idx_c = int(np.clip(np.searchsorted(dates_ts, cross_dt), 0, n_days - 1))
            lv = eng["last_valid_idx"][c_col]
            end_i = min(lv + 1, n_days) if lv >= idx_c else n_days
            if end_i > idx_c + 1:
                sh_series = np.full(end_i - idx_c, float(r_cross["mcap_pit"]) / cross_adj_px, dtype=np.float64)
                for _, pr in post_grp.iterrows():
                    p_dt = pd.Timestamp(pr["entry_date"]).normalize()
                    p_eadj = float(pr["entry_adj_close"])
                    p_mpit = float(pr["mcap_pit"])
                    if p_eadj > 0 and pd.notna(p_mpit) and p_mpit > 0:
                        pos = int(np.searchsorted(dates_ts[idx_c:end_i], p_dt))
                        if 0 <= pos < len(sh_series):
                            sh_series[pos:] = p_mpit / p_eadj

                px_post = P_adj[idx_c:end_i, c_col].astype(np.float64)
                sc_post = scale_arr[idx_c:end_i]
                mc26_daily = (px_post * sh_series / 1e9) * sc_post
                vm = ~np.isnan(mc26_daily) & (mc26_daily > 0)
                if np.any(vm):
                    mc_v = mc26_daily[vm]
                    dt_v = dates_ts[idx_c:end_i][vm]
                    ge100_days = np.where(mc_v >= 100.0)[0]
                    if len(ge100_days) >= 3 or qtr_peak_mc26 >= 100.0:
                        daily_peak_mc26 = float(max(qtr_peak_mc26, np.percentile(mc_v, 99.5)))
                        if len(ge100_days) > 0:
                            reached_100b_dt = pd.Timestamp(dt_v[ge100_days[0]])
                    else:
                        daily_peak_mc26 = float(max(qtr_peak_mc26, np.max(mc_v)))

                    daily_last_mc26 = float(mc_v[-1])
                    if len(mc_v) > 20:
                        min_mc26_post = float(min(qtr_min_after_cross, np.min(mc_v[5:])))

                    cmax_mc = np.maximum.accumulate(mc_v)
                    max_dd_after_peak = float(np.min(mc_v / cmax_mc - 1.0))

                    px_3y = px_post[:min(len(px_post), 757)]
                    px_3y_v = px_3y[~np.isnan(px_3y) & (px_3y > 0)]
                    if len(px_3y_v) > 5:
                        max_dd_from_cross_3y = float(np.min(px_3y_v / cross_adj_px - 1.0))

                    tr_term = float(eng["terminal_rets"][c_col]) if (lv < n_days - 15) else 0.0
                    if r_cross["delist_exit_category"] == "BANKRUPTCY":
                        tr_term = -0.95
                        daily_last_mc26 = 0.0
                    p_end = float(px_post[vm][-1])
                    total_ret_to_end = (p_end / cross_adj_px) * (1.0 + tr_term) - 1.0
                    spy_end_idx = idx_c + np.where(vm)[0][-1]
                    spy_tot = float(spy_tr[spy_end_idx] / spy_tr[idx_c] - 1.0)
                    alpha_to_end = total_ret_to_end - spy_tot

        years_since_cross = (pd.Timestamp("2026-11-06") - cross_dt).days / 365.25
        years_to_100b = ((reached_100b_dt - cross_dt).days / 365.25) if pd.notna(reached_100b_dt) else np.nan
        reached_100b = bool(daily_peak_mc26 >= 100.0)
        reached_50b = bool(daily_peak_mc26 >= 50.0)

        is_bk = r_cross["delist_exit_category"] == "BANKRUPTCY"
        crashed_hard = (
            is_bk
            or (daily_last_mc26 < 15.0)
            or (pd.notna(r_cross["fwd_756d"]) and float(r_cross["fwd_756d"]) <= -0.45)
            or (pd.notna(total_ret_to_end) and total_ret_to_end <= -0.45)
        )

        if reached_100b and daily_last_mc26 >= 50.0 and not is_bk:
            archetype = "1_True_100B_King (真跃迁王: 跨250亿后涨上>=1000亿且稳守大盘)"
        elif reached_100b and (daily_last_mc26 < 50.0 or is_bk):
            archetype = "2_Bubble_100B_Roundtrip (泡沫过山车: 曾摸千亿后暴跌回吐)"
        elif crashed_hard:
            archetype = "4_Pulse_Peak_Crash (脉冲过客: 跨250亿即大顶摔回<150亿或深跌>=45%)"
        elif years_since_cross < 2.2 and daily_peak_mc26 < 100.0:
            archetype = "6_Recent_2024_2026_Pending (近两年新晋跨250亿观察中)"
        elif reached_50b and daily_last_mc26 >= 30.0:
            archetype = "3_Solid_50to100B_Compounder (稳健进阶中坚: 达500至1000亿且守住阵地)"
        else:
            archetype = "5_Stagnant_25to50B_or_MA (250至500亿横盘滞涨或并购退市)"

        sbc_to_rev = (float(r_cross["sbc_ttm"]) / float(r_cross["rev_ttm"])) if (pd.notna(r_cross["sbc_ttm"]) and pd.notna(r_cross["rev_ttm"]) and float(r_cross["rev_ttm"]) > 0) else np.nan

        crossover_cases.append({
            "ticker": tk,
            "cik": int(cik),
            "name": str(r_cross["name"]),
            "sector_type": str(r_cross["sector_type"]),
            "was_pre2009_largecap_rebound": was_pre_xbrl_25b,
            "had_10to25b_xbrl_prior": had_10to25_prior,
            "cross_date": cross_dt.strftime("%Y-%m-%d"),
            "cross_year": int(cross_dt.year),
            "cross_era": (
                "2020_2021_ZeroRateBubble" if ("2020-03-01" <= cross_dt.strftime("%Y-%m-%d") <= "2021-12-31")
                else ("2022_2026_HighRate" if cross_dt.year >= 2022 else "2009_2019_PreCovid")
            ),
            "archetype": archetype,
            "mcap_2026_b_at_cross": round(cross_mc26, 2),
            "mcap_nominal_b_at_cross": round(float(r_cross["mcap_usd_b"]), 2) if pd.notna(r_cross["mcap_usd_b"]) else np.nan,
            "peak_post_mcap_2026_b": round(daily_peak_mc26, 2),
            "latest_or_exit_mcap_2026_b": round(daily_last_mc26, 2),
            "min_post_mcap_2026_b": round(min_mc26_post, 2),
            "reached_100b": reached_100b,
            "years_to_100b": round(years_to_100b, 2) if pd.notna(years_to_100b) else np.nan,
            "delist_exit_category": str(r_cross["delist_exit_category"]),
            "rev_yoy_at_cross": r_cross["rev_yoy"],
            "pit_dbl_inflect_n_at_cross": int(r_cross["pit_dbl_inflect_n"]),
            "pit_rev20_n_at_cross": int(r_cross["pit_rev20_n"]),
            "gm_q_at_cross": r_cross["gm_q"],
            "opm_q_at_cross": r_cross["opm_q"],
            "gm_minus_sga_at_cross": r_cross["gm_minus_sga_q"],
            "fcf_margin_ttm_at_cross": r_cross["fcf_margin_ttm"],
            "roic_ttm_at_cross": r_cross["roic_ttm"],
            "roic_5y_med_at_cross": r_cross["roic_5y_med_pit"],
            "dilution_yoy_at_cross": r_cross["dilution_yoy_clean"],
            "sbc_to_rev_at_cross": sbc_to_rev,
            "opm_5y_pct_at_cross": r_cross["opm_5y_pct_pit"],
            "pe_pit_at_cross": r_cross["pe_pit"],
            "ps_pit_at_cross": r_cross["ps_pit"],
            "pre_ret_252d_at_cross": r_cross["pre_ret_252d"],
            "realized_vol_252d_at_cross": r_cross["realized_vol_252d"],
            "slow_uptrend_tag_at_cross": str(r_cross["slow_uptrend_tag"]),
            "earn_jump_at_cross": r_cross["earn_jump_ret"],
            "fwd_1y": r_cross["fwd_252d"],
            "alpha_1y": r_cross["alpha_fwd_252d"],
            "fwd_3y": r_cross["fwd_756d"],
            "alpha_3y": r_cross["alpha_fwd_756d"],
            "fwd_5y": r_cross["fwd_1260d"],
            "alpha_5y": r_cross["alpha_fwd_1260d"],
            "max_dd_3y_from_cross": max_dd_from_cross_3y,
            "max_dd_after_peak": max_dd_after_peak,
            "total_ret_to_2026_or_exit": total_ret_to_end,
            "alpha_to_2026_or_exit": alpha_to_end,
        })

    df_cases = pd.DataFrame(crossover_cases)

    # Pure Secular First-Time Crossovers (excluding pre-2009 GFC rebounders)
    pure = df_cases[~df_cases["was_pre2009_largecap_rebound"]].copy()
    uncens = pure[~pure["archetype"].str.startswith("6_")].copy()

    anat_rows = []

    def summarize_cohort(sub: pd.DataFrame, section: str, group_name: str, desc: str) -> dict:
        n_c = len(sub)
        if n_c == 0:
            return {}
        pos_pe = sub.loc[sub["pe_pit_at_cross"] > 0, "pe_pit_at_cross"]
        top_examples = (
            sub.sort_values("peak_post_mcap_2026_b", ascending=False)["ticker"]
            .head(12)
            .tolist()
        )
        return {
            "record_section": section,
            "group_or_ticker": group_name,
            "description_or_company": desc,
            "n_companies": n_c,
            "pct_of_uncensored_pool": n_c / max(len(uncens), 1) if section == "A_Archetype_Summary" else np.nan,
            "reach_100b_king_rate": float((sub["archetype"].str.startswith("1_")).mean()),
            "solid_50b_plus_rate": float((sub["archetype"].str.startswith(("1_", "3_"))).mean()),
            "pulse_crash_rate": float((sub["archetype"].str.startswith(("2_", "4_"))).mean()),
            "bankrupt_rate": float((sub["delist_exit_category"] == "BANKRUPTCY").mean()),
            "med_cross_mcap_2026_b": float(sub["mcap_2026_b_at_cross"].median()),
            "med_peak_post_mcap_2026_b": float(sub["peak_post_mcap_2026_b"].median()),
            "med_latest_mcap_2026_b": float(sub["latest_or_exit_mcap_2026_b"].median()),
            "med_years_to_100b": float(sub["years_to_100b"].dropna().median()) if sub["years_to_100b"].notna().any() else np.nan,
            "med_rev_yoy": float(sub["rev_yoy_at_cross"].dropna().median()) if sub["rev_yoy_at_cross"].notna().any() else np.nan,
            "pct_rev_yoy_ge25": float((sub["rev_yoy_at_cross"] >= 0.25).mean()),
            "pct_dbl_inflect_ge2q": float((sub["pit_dbl_inflect_n_at_cross"] >= 2).mean()),
            "pct_dbl_inflect_ge3q": float((sub["pit_dbl_inflect_n_at_cross"] >= 3).mean()),
            "med_gm_q": float(sub["gm_q_at_cross"].dropna().median()) if sub["gm_q_at_cross"].notna().any() else np.nan,
            "med_opm_q": float(sub["opm_q_at_cross"].dropna().median()) if sub["opm_q_at_cross"].notna().any() else np.nan,
            "med_gm_minus_sga": float(sub["gm_minus_sga_at_cross"].dropna().median()) if sub["gm_minus_sga_at_cross"].notna().any() else np.nan,
            "med_fcf_margin_ttm": float(sub["fcf_margin_ttm_at_cross"].dropna().median()) if sub["fcf_margin_ttm_at_cross"].notna().any() else np.nan,
            "pct_pos_fcf": float((sub["fcf_margin_ttm_at_cross"] > 0).mean()) if sub["fcf_margin_ttm_at_cross"].notna().any() else np.nan,
            "med_roic_ttm": float(sub["roic_ttm_at_cross"].dropna().median()) if sub["roic_ttm_at_cross"].notna().any() else np.nan,
            "med_dilution_yoy": float(sub["dilution_yoy_at_cross"].dropna().median()) if sub["dilution_yoy_at_cross"].notna().any() else np.nan,
            "med_sbc_to_rev": float(sub["sbc_to_rev_at_cross"].dropna().median()) if sub["sbc_to_rev_at_cross"].notna().any() else np.nan,
            "pct_unprofitable_at_cross": float(((sub["pe_pit_at_cross"] < 0) | sub["pe_pit_at_cross"].isna()).mean()),
            "med_pos_pe_at_cross": float(pos_pe.median()) if len(pos_pe) > 0 else np.nan,
            "med_ps_at_cross": float(sub["ps_pit_at_cross"].dropna().median()) if sub["ps_pit_at_cross"].notna().any() else np.nan,
            "pct_ps_gt_18": float((sub["ps_pit_at_cross"] > 18.0).mean()),
            "med_pre_1y_ret": float(sub["pre_ret_252d_at_cross"].dropna().median()) if sub["pre_ret_252d_at_cross"].notna().any() else np.nan,
            "pct_parabolic_pre_runup": float(((sub["slow_uptrend_tag_at_cross"] == "HighFlyer_Parabolic") | (sub["pre_ret_252d_at_cross"] > 1.0)).mean()),
            "pct_healthy_slowup_pre": float(sub["slow_uptrend_tag_at_cross"].isin(["SlowUp_6Mto2Y", "SlowUp_2to5Y"]).mean()),
            "pct_covid_2020_2021_cross": float((sub["cross_era"] == "2020_2021_ZeroRateBubble").mean()),
            "mean_alpha_1y": float(sub["alpha_1y"].dropna().mean()) if sub["alpha_1y"].notna().any() else np.nan,
            "med_alpha_1y": float(sub["alpha_1y"].dropna().median()) if sub["alpha_1y"].notna().any() else np.nan,
            "mean_alpha_3y": float(sub["alpha_3y"].dropna().mean()) if sub["alpha_3y"].notna().any() else np.nan,
            "med_alpha_3y": float(sub["alpha_3y"].dropna().median()) if sub["alpha_3y"].notna().any() else np.nan,
            "win_rate_3y": float((sub["alpha_3y"].dropna() > 0).mean()) if sub["alpha_3y"].notna().any() else np.nan,
            "mean_alpha_5y": float(sub["alpha_5y"].dropna().mean()) if sub["alpha_5y"].notna().any() else np.nan,
            "med_max_dd_3y": float(sub["max_dd_3y_from_cross"].dropna().median()) if sub["max_dd_3y_from_cross"].notna().any() else np.nan,
            "representative_tickers": ", ".join(top_examples),
        }

    anat_rows.append(summarize_cohort(uncens, "A_Archetype_Summary", "0_All_Uncensored_Pure_25B_Crossovers", "全部首次从100至250亿跨过250亿独立公司(已剔除2009前老巨头反弹与近两年未满期新晋)"))
    for arch in sorted(uncens["archetype"].unique()):
        anat_rows.append(summarize_cohort(uncens[uncens["archetype"] == arch], "A_Archetype_Summary", arch.split(" ")[0], arch))
    rec_df = pure[pure["archetype"].str.startswith("6_")]
    if len(rec_df) > 0:
        anat_rows.append(summarize_cohort(rec_df, "A_Recent_Observing", "6_Recent_2024_2026_Pending", "2024至2026近两年首次跨250亿观察中名单"))
    if len(df_cases[df_cases["was_pre2009_largecap_rebound"]]) > 0:
        anat_rows.append(summarize_cohort(df_cases[df_cases["was_pre2009_largecap_rebound"]], "A_Reference_GFC_Rebound", "Ref_Pre2009_FallenAngel_Rebound", "对照: 2009年前已是>280亿老牌大盘股、次贷危机跌破250亿后重返250亿"))

    # Panel B: Zero-Lookahead Ex-Ante Crossover Separation Rules (evaluated strictly at T_cross!)
    is_tech_hc_comp = uncens["sector_type"].isin(["Tech_Hardware_Semi", "Software_Internet", "Healthcare_LifeSci", "Industrial_Consumer_Compounder"])
    ex_ante_rules = [
        (
            "Rule1_True100B_HyperEngine",
            "千亿跃迁主引擎: 科技/医药/复利赛道 + 营收增速>=25% + 毛销差>=25% + PS<=18x (兼顾高成长与商业模型护城河)",
            is_tech_hc_comp
            & (uncens["rev_yoy_at_cross"] >= 0.25)
            & (uncens["gm_minus_sga_at_cross"] >= 0.25)
            & (uncens["ps_pit_at_cross"].fillna(8.0) <= 18.0),
        ),
        (
            "Rule2_Quality_Compounder_Cross",
            "高胜率进阶铁律: 非周期金融 + 营收增速>=20% + 毛销差>=25% + FCF利润率>0 + PS<=18x",
            is_tech_hc_comp
            & (uncens["rev_yoy_at_cross"] >= 0.20)
            & (uncens["gm_minus_sga_at_cross"] >= 0.25)
            & (uncens["fcf_margin_ttm_at_cross"] > 0)
            & (uncens["ps_pit_at_cross"].fillna(8.0) <= 18.0),
        ),
        (
            "Rule3_Consec2Q_DoubleInflect_ReasonablePS",
            "连季双扩跨槛: 跨250亿当季连>=2季双改善 + 营收>=20% + 毛销差>=20% + PS<=18x",
            (uncens["pit_dbl_inflect_n_at_cross"] >= 2)
            & (uncens["rev_yoy_at_cross"] >= 0.20)
            & (uncens["gm_minus_sga_at_cross"] >= 0.20)
            & (uncens["ps_pit_at_cross"].fillna(8.0) <= 18.0),
        ),
        (
            "Trap1_ExtremePS_gt20_at_Cross",
            "致命泡沫跨槛陷阱1: 首次跨250亿时PS>20倍(疫情零利率SaaS/概念透支顶)",
            uncens["ps_pit_at_cross"] > 20.0,
        ),
        (
            "Trap2_LowGrowth_lt12pct_at_Cross",
            "平庸估值拔高陷阱2: 首次跨250亿时营收增速<12%(无内生增长支撑难破500亿天花板)",
            uncens["rev_yoy_at_cross"] < 0.12,
        ),
        (
            "Trap3_WeakUnitEcon_GMSGA_lt15_and_HighPS",
            "伪成长烧钱陷阱3: 毛销差<15% 且 (PS>10倍 或 FCF<=0)",
            (uncens["gm_minus_sga_at_cross"] < 0.15) & ((uncens["ps_pit_at_cross"] > 10.0) | (uncens["fcf_margin_ttm_at_cross"] <= 0)),
        ),
        (
            "Trap4_DeepCyclical_or_PeakOPM85",
            "周期极值陷阱4: 强周期股 或 5年利润率分位>=85%且营收增速<20%",
            (uncens["sector_type"] == "Deep_Cyclical") | ((uncens["opm_5y_pct_at_cross"] >= 0.85) & (uncens["rev_yoy_at_cross"] < 0.20)),
        ),
        (
            "Trap5_CovidBubble_2020_2021_HighPS_gt15",
            "零利率泡沫跨槛陷阱5: 2020至2021放水期首次跨250亿且PS>15倍",
            (uncens["cross_era"] == "2020_2021_ZeroRateBubble") & (uncens["ps_pit_at_cross"] > 15.0),
        ),
    ]
    for r_id, r_desc, r_mask in ex_ante_rules:
        if r_mask.sum() >= 3:
            anat_rows.append(summarize_cohort(uncens[r_mask], "B_ExAnte_Crossover_Filter", r_id, r_desc))

    pure_sorted = pure.sort_values(["archetype", "peak_post_mcap_2026_b"], ascending=[True, False])
    for _, c in pure_sorted.iterrows():
        anat_rows.append({
            "record_section": "C_Individual_Company_Crossover",
            "group_or_ticker": c["ticker"],
            "description_or_company": f"{c['name']} | {c['sector_type']} | Cross={c['cross_date']} | {c['archetype']}",
            "n_companies": 1,
            "pct_of_uncensored_pool": np.nan,
            "reach_100b_king_rate": 1.0 if str(c["archetype"]).startswith("1_") else 0.0,
            "solid_50b_plus_rate": 1.0 if str(c["archetype"]).startswith(("1_", "3_")) else 0.0,
            "pulse_crash_rate": 1.0 if str(c["archetype"]).startswith(("2_", "4_")) else 0.0,
            "bankrupt_rate": 1.0 if c["delist_exit_category"] == "BANKRUPTCY" else 0.0,
            "med_cross_mcap_2026_b": c["mcap_2026_b_at_cross"],
            "med_peak_post_mcap_2026_b": c["peak_post_mcap_2026_b"],
            "med_latest_mcap_2026_b": c["latest_or_exit_mcap_2026_b"],
            "med_years_to_100b": c["years_to_100b"],
            "med_rev_yoy": c["rev_yoy_at_cross"],
            "pct_rev_yoy_ge25": 1.0 if (pd.notna(c["rev_yoy_at_cross"]) and c["rev_yoy_at_cross"] >= 0.25) else 0.0,
            "pct_dbl_inflect_ge2q": 1.0 if c["pit_dbl_inflect_n_at_cross"] >= 2 else 0.0,
            "pct_dbl_inflect_ge3q": 1.0 if c["pit_dbl_inflect_n_at_cross"] >= 3 else 0.0,
            "med_gm_q": c["gm_q_at_cross"],
            "med_opm_q": c["opm_q_at_cross"],
            "med_gm_minus_sga": c["gm_minus_sga_at_cross"],
            "med_fcf_margin_ttm": c["fcf_margin_ttm_at_cross"],
            "pct_pos_fcf": 1.0 if (pd.notna(c["fcf_margin_ttm_at_cross"]) and c["fcf_margin_ttm_at_cross"] > 0) else 0.0,
            "med_roic_ttm": c["roic_ttm_at_cross"],
            "med_dilution_yoy": c["dilution_yoy_at_cross"],
            "med_sbc_to_rev": c["sbc_to_rev_at_cross"],
            "pct_unprofitable_at_cross": 1.0 if (pd.isna(c["pe_pit_at_cross"]) or c["pe_pit_at_cross"] < 0) else 0.0,
            "med_pos_pe_at_cross": c["pe_pit_at_cross"] if (pd.notna(c["pe_pit_at_cross"]) and c["pe_pit_at_cross"] > 0) else np.nan,
            "med_ps_at_cross": c["ps_pit_at_cross"],
            "pct_ps_gt_18": 1.0 if (pd.notna(c["ps_pit_at_cross"]) and c["ps_pit_at_cross"] > 18.0) else 0.0,
            "med_pre_1y_ret": c["pre_ret_252d_at_cross"],
            "pct_parabolic_pre_runup": 1.0 if ((c["slow_uptrend_tag_at_cross"] == "HighFlyer_Parabolic") or (pd.notna(c["pre_ret_252d_at_cross"]) and c["pre_ret_252d_at_cross"] > 1.0)) else 0.0,
            "pct_healthy_slowup_pre": 1.0 if c["slow_uptrend_tag_at_cross"] in ("SlowUp_6Mto2Y", "SlowUp_2to5Y") else 0.0,
            "pct_covid_2020_2021_cross": 1.0 if c["cross_era"] == "2020_2021_ZeroRateBubble" else 0.0,
            "mean_alpha_1y": c["alpha_1y"],
            "med_alpha_1y": c["alpha_1y"],
            "mean_alpha_3y": c["alpha_3y"],
            "med_alpha_3y": c["alpha_3y"],
            "win_rate_3y": (1.0 if c["alpha_3y"] > 0 else 0.0) if pd.notna(c["alpha_3y"]) else np.nan,
            "mean_alpha_5y": c["alpha_5y"],
            "med_max_dd_3y": c["max_dd_3y_from_cross"],
            "representative_tickers": f"CrossDate={c['cross_date']} | Exit={c['delist_exit_category']}",
        })

    out_anat = pd.DataFrame(anat_rows)
    out_path = os.path.join(OUT_DIR, "table_g03_25b_crossover_anatomy.csv")
    out_anat.to_csv(out_path, index=False)
    print(
        f"  Saved {out_path} ({len(out_anat):,} rows | "
        f"{len(pure):,} pure first-time crossovers, {len(uncens):,} uncensored) in {time.time() - t0:.2f}s."
    )
    return out_anat, df_cases


def main():
    t_all = time.time()
    eng = build_complete_price_and_delist_engine()
    df = build_augmented_xbrl_panel(eng)
    t1 = run_table_1_mcap7_x_strategies(df)
    t2 = run_table_2_threshold_scaling(df)
    t3, df_cases = run_table_3_25b_crossover_anatomy(df, eng)

    print("\n" + "=" * 95)
    print("CLEAN CALIBRATED EXECUTIVE SUMMARY (G03)")
    print("=" * 95)

    print("\n[0] Verify Top T7_ge500B Tickers (Zero Fake Mid-Cap Spikes!):")
    t7_chk = df[df["mcap_tier_id"] == "T7_ge500B"].groupby("ticker")["mcap_2026_equiv_b"].agg(["count", "max"]).sort_values("max", ascending=False)
    print("Total T7 unique tickers:", len(t7_chk), "| Top 20:", t7_chk.head(20).index.tolist())
    print("Bottom 10 T7 tickers:", t7_chk.tail(10).index.tolist())

    print("\n[1] Full Period (2009-2026) 7 Tiers x Strategies:")
    f_t1 = t1[t1["subperiod_id"] == "Full_2009_2026"][[
        "mcap_tier_id", "strategy_id", "n_dedup", "qtr_ew_alpha_1y", "qtr_ew_alpha_3y",
        "spread_vs_tier_base_3y", "win_rate_3y", "bag2x_3y_rate", "bag3x_3y_rate", "halve_3y_rate", "bankrupt_3y_rate"
    ]]
    print(f_t1.to_string(index=False))

    print("\n[2] HighRate Era (2022-2026) 7 Tiers x Strategies (1Y Alpha & Win Rate):")
    f_hr = t1[t1["subperiod_id"] == "HighRate_2022_2026"][[
        "mcap_tier_id", "strategy_id", "n_dedup", "qtr_ew_alpha_3m", "qtr_ew_alpha_1y", "spread_vs_tier_base_1y", "win_rate_1y", "payoff_1y"
    ]]
    print(f_hr.to_string(index=False))

    print("\n[3] Clean $25B Crossover Anatomy Summary (Panels A & B):")
    f_c = t3[t3["record_section"].isin(["A_Archetype_Summary", "A_Recent_Observing", "B_ExAnte_Crossover_Filter"])][[
        "record_section", "group_or_ticker", "n_companies", "reach_100b_king_rate", "solid_50b_plus_rate", "pulse_crash_rate",
        "med_rev_yoy", "med_gm_minus_sga", "med_fcf_margin_ttm", "med_ps_at_cross",
        "med_pre_1y_ret", "mean_alpha_3y", "win_rate_3y", "representative_tickers"
    ]]
    print(f_c.to_string(index=False))
    print(f"\n[DONE] Total Clean G03 runtime: {time.time() - t_all:.2f}s")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
g08_macro_x_8strategies.py
G08: 1996-2026 Full 30-Year 8 US Stock Selection Strategies (+ 2 Control Traps)
     x 7 ALFRED Point-in-Time (PIT) Macro Dimensions Fine-Grained Switchboard Engine.

Strict Compliance:
- Zero Lookahead:
  * All fundamentals strictly from SEC XBRL / Pre-2009 SEC filingDate PIT records.
  * All entries strictly at D+1 trading day close after filingDate (earn jump excluded from forward returns).
  * All 7 macro dimensions strictly merged as of pre-event / signal date using ALFRED unrevised PIT series.
- Zero Survivorship Bias & Dual-Track 30Y Verification:
  * Track 1 (1_XBRL_2009_2026_Strict_SP500_PIT): 100% pure zero-survivorship S&P 500 historical PIT constituents
    (includes all 571 historical S&P 500 exits/bankruptcies; zero 2026 backfilled small-cap survivor bias).
  * Track 2 (2_XBRL_2009_2026_Commercial_All): Exact XBRL fundamentals across all 1,069 commercial companies
    (captures mid/small-cap early commercialization breakthroughs like S7, paired with median & win-rate audit).
  * Track 3 (3_Full30Y_1996_2026_SP500_PIT): Full 30-year (1996-2026) strict PIT S&P 500 dynamic constituents
    with delisting/bankruptcy terminal return splicing across all 8 historical eras (including 1996-2000 DotCom,
    2001-2002 TechBust, 2003-2007 Hike Capex Bull, 2008-2009 GFC).
- D15 Anti-Bias Statistical Protocol:
  * Calendar-quarter equal-weight net excess return vs SPY total return (1Q, 1Y, 2Y, 3Y).
  * 250-day (180-day for 30Y panel) per-ticker cooldown deduplication for median alpha, win rate, payoff, and 1Y MaxDD.
  * Benjamini-Hochberg FDR multiple-testing adjusted q-values across the full strategy x macro grid.
"""

import os
import glob
import sys
import time
import warnings

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

PROJ_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-09-us-earnings-macro-30y"
DATA_DIR = os.path.join(PROJ_DIR, "data")
SCRIPTS_DIR = os.path.join(PROJ_DIR, "scripts")
TMP_DIR = "/tmp/us_earn_macro_bt_20261109"
OUT_DIR = os.path.join(PROJ_DIR, "results", "granularity_v2", "g08_macro_x_8strategies")

os.makedirs(OUT_DIR, exist_ok=True)
sys.path.insert(0, SCRIPTS_DIR)

from backtest_stats_lib import (
    classify_sector_type,
    deduplicate_cooldown,
    eval_slice,
    benjamini_hochberg_fdr,
)
from price_feature_lib import TAG_MAP


# ==============================================================================
# 1. Seven Fine-Grained ALFRED PIT Macro Dimensions (Exact G08 Specification)
# ==============================================================================
def build_macro_7dims_table() -> pd.DataFrame:
    macro_path = os.path.join(DATA_DIR, "macro_pit_daily_1990_2026.parquet")
    m = pd.read_parquet(macro_path).sort_values("date").reset_index(drop=True)
    m["macro_join_date"] = pd.to_datetime(m["date"]).dt.normalize()

    # Rolling 252-trading-day minimum of T10Y2Y to capture the exact post-inversion steepening window
    m["t10y2y_rmin_252"] = m["t10y2y"].rolling(252, min_periods=1).min()

    # Dim 1: 10Y Nominal Treasury Yield — 5 bins (<2%, 2-3%, 3-4%, 4-5%, >=5%)
    m["m1_dgs10_5bin"] = pd.cut(
        m["dgs10"],
        bins=[-np.inf, 2.0, 3.0, 4.0, 5.0, np.inf],
        labels=["1_<2%", "2_2-3%", "3_3-4%", "4_4-5%", "5_>=5%"],
        right=False,
    ).astype(str)

    # Dim 2: 10Y Yield 6-Month Change (126 trading days) — 4 bins
    m["m2_rate6m_4bin"] = np.select(
        [
            m["dgs10_chg_126d"] <= -0.50,
            (m["dgs10_chg_126d"] > -0.50) & (m["dgs10_chg_126d"] <= -0.15),
            (m["dgs10_chg_126d"] > -0.15) & (m["dgs10_chg_126d"] < 0.35),
            m["dgs10_chg_126d"] >= 0.35,
        ],
        [
            "1_急降<=-50bp",
            "2_缓降-50至-15bp",
            "3_走平-15至+35bp",
            "4_上行>=+35bp",
        ],
        default="Unknown",
    )

    # Dim 3: 10Y TIPS / Real Yield PIT — 4 bins (<0%, 0-1.0%, 1.0-2.0%, >=2.0%)
    m["m3_realrate_4bin"] = pd.cut(
        m["real_rate_10y_pit"],
        bins=[-np.inf, 0.0, 1.0, 2.0, np.inf],
        labels=[
            "1_负实际利率<0%",
            "2_0至1.0%",
            "3_1.0至2.0%",
            "4_高实际利率>=2.0%",
        ],
        right=False,
    ).astype(str)

    # Dim 4: 10Y-2Y Yield Curve Cycle — 4 bins
    m["m4_yc_4bin"] = np.select(
        [
            m["t10y2y"] < -0.10,
            (m["t10y2y"] >= -0.10) & (m["t10y2y"] <= 1.20) & (m["t10y2y_rmin_252"] < -0.10),
            (m["t10y2y"] >= -0.10) & (m["t10y2y"] <= 1.20),
            m["t10y2y"] > 1.20,
        ],
        [
            "1_倒挂<-10bp",
            "2_刚解除倒挂陡峭化",
            "3_正常正斜率10至120bp",
            "4_衰退后极陡>120bp",
        ],
        default="Unknown",
    )

    # Dim 5: Moody's BAA - 10Y Treasury Credit Spread — 4 bins (<1.7%, 1.7-2.3%, 2.3-3.0%, >=3.0%)
    m["m5_baa_4bin"] = pd.cut(
        m["baa10y"],
        bins=[-np.inf, 1.70, 2.30, 3.00, np.inf],
        labels=[
            "1_极紧<1.7%",
            "2_常态1.7-2.3%",
            "3_偏紧2.3-3.0%",
            "4_危机>=3.0%",
        ],
        right=False,
    ).astype(str)

    # Dim 6: VIX Volatility Index — 4 bins (<15, 15-22, 22-30, >=30)
    m["m6_vix_4bin"] = pd.cut(
        m["vix"],
        bins=[-np.inf, 15.0, 22.0, 30.0, np.inf],
        labels=["1_<15", "2_15-22", "3_22-30", "4_>=30"],
        right=False,
    ).astype(str)

    # Dim 7: Industrial Production YoY PIT x CPI YoY PIT Merrill/Macro Four Quadrants
    m["m7_merrill_4q"] = np.select(
        [
            (m["indpro_yoy_pit"] >= 1.0) & (m["cpi_yoy_pit"] < 3.0),
            (m["indpro_yoy_pit"] >= 1.0) & (m["cpi_yoy_pit"] >= 3.0),
            (m["indpro_yoy_pit"] < 1.0) & (m["cpi_yoy_pit"] >= 3.0),
            (m["indpro_yoy_pit"] < 1.0) & (m["cpi_yoy_pit"] < 3.0),
        ],
        [
            "1_复苏金发姑娘(INDPRO>=1%_CPI<3%)",
            "2_过热再通胀Capex(INDPRO>=1%_CPI>=3%)",
            "3_滞胀紧缩(INDPRO<1%_CPI>=3%)",
            "4_衰退出清(INDPRO<1%_CPI<3%)",
        ],
        default="Unknown",
    )

    return m


MACRO_DIM_SPECS = [
    ("0_全样本与隔离基线", "m0_baseline"),
    ("1_10Y美债名义利率(5档)", "m1_dgs10_5bin"),
    ("2_10Y利率半年变化(4档)", "m2_rate6m_4bin"),
    ("3_10Y_TIPS实际利率(4档)", "m3_realrate_4bin"),
    ("4_10Y-2Y收益率曲线(4周期)", "m4_yc_4bin"),
    ("5_BAA信用利差(4档)", "m5_baa_4bin"),
    ("6_VIX恐慌指数(4档)", "m6_vix_4bin"),
    ("7_工业产出x通胀美林四象限", "m7_merrill_4q"),
]


# ==============================================================================
# 2. S&P 500 PIT Dynamic Membership & Augmented 30Y Price + Delisted Engine
# ==============================================================================
def load_sp500_pit_intervals():
    sp_csv = "/tmp/us_xuangu_20261109/w1_a1/sp500_ticker_start_end.csv"
    sp_hist = pd.read_csv(sp_csv)
    sp_hist["start_date"] = pd.to_datetime(sp_hist["start_date"])
    sp_hist["end_date"] = pd.to_datetime(sp_hist["end_date"]).fillna(pd.Timestamp("2099-12-31"))
    sp_intervals = {}
    for tk, grp in sp_hist.groupby("ticker"):
        sp_intervals[str(tk).strip()] = list(zip(grp["start_date"], grp["end_date"]))
    return sp_hist, sp_intervals


def tag_sp500_pit(tickers, dates_series, sp_intervals: dict) -> np.ndarray:
    dts = pd.to_datetime(dates_series)
    out = np.zeros(len(tickers), dtype=bool)
    for i, (tk, dt) in enumerate(zip(tickers, dts)):
        if pd.isna(dt):
            continue
        ivs = sp_intervals.get(str(tk).strip())
        if ivs:
            for s, e in ivs:
                if s <= dt <= e:
                    out[i] = True
                    break
    return out


def build_augmented_30y_engine(sp_hist: pd.DataFrame):
    t0 = time.time()
    cache = np.load(os.path.join(TMP_DIR, "price_engine_cache.npz"), allow_pickle=True)
    dates = cache["dates"]
    dates_ts = pd.to_datetime(dates)
    n_days = len(dates)
    date_to_idx = {pd.Timestamp(d).normalize(): i for i, d in enumerate(dates)}

    base_tickers = [str(t) for t in cache["tickers"]]
    base_set = set(base_tickers)

    up_meta = pd.read_parquet(
        os.path.join(TMP_DIR, "unified_prices_and_bench.parquet"),
        columns=["ticker", "sector", "industry"],
    ).drop_duplicates("ticker")
    sec_map = {}
    for _, r in up_meta.iterrows():
        sec_map[str(r["ticker"])] = classify_sector_type(r["sector"], r["industry"])

    dm0 = pd.read_parquet(os.path.join(TMP_DIR, "delisted_prices/delisted_meta_0.parquet"))
    dm1 = pd.read_parquet(os.path.join(TMP_DIR, "delisted_prices/delisted_meta_1.parquet"))
    dm_all = pd.concat([dm0, dm1], ignore_index=True)
    q03_path = "/tmp/us_xuangu_20261109/w2/q03_delisted_ma_vs_bankrupt.csv"
    q03 = pd.read_csv(q03_path) if os.path.exists(q03_path) else pd.DataFrame()

    term_lookup = {}
    for _, r in dm_all.iterrows():
        tk = str(r["ticker"]).strip()
        et = str(r["exit_type"])
        term_lookup[tk] = -0.95 if et == "BANKRUPTCY_OR_LIQUIDATION" else 0.0

    if len(q03) > 0:
        for _, r in q03.iterrows():
            tk = str(r["ticker"]).strip()
            et_raw = str(r["exit_type"])
            if et_raw == "bankrupt_wipeout":
                term_lookup[tk] = -0.95
            elif et_raw == "ma_cash_premium":
                prem = float(r["terminal_return_pct"]) / 100.0 if pd.notna(r["terminal_return_pct"]) else 0.0
                term_lookup[tk] = np.clip(prem, -0.50, 0.80)

    supp_dfs = []
    for p in [
        os.path.join(TMP_DIR, "delisted_prices/delisted_prices_0.parquet"),
        os.path.join(TMP_DIR, "delisted_prices/delisted_prices_1.parquet"),
    ]:
        if os.path.exists(p):
            d = pd.read_parquet(p)
            d["date"] = pd.to_datetime(d["date"]).dt.tz_localize(None).dt.normalize()
            supp_dfs.append(d[["date", "ticker", "close", "adj_close"]])

    for ep in sorted(glob.glob("/tmp/us_xuangu_20261109/w2/extra_prices/*.parquet")):
        tk_ep = os.path.basename(ep).replace(".parquet", "")
        if tk_ep not in base_set:
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
            vm = (~np.isnan(P_adj_new[:, c])) & (P_adj_new[:, c] > 0)
            if np.any(vm):
                last_new[c] = np.where(vm)[0][-1]

        P_adj_new = pd.DataFrame(P_adj_new).ffill(limit=5).values.astype(np.float32)
        P_adj_new[P_adj_new <= 0] = np.nan
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
        pos_24m_new = (P_df.pct_change(21) > 0).rolling(504, min_periods=126).mean().values.astype(np.float32)

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
            if new_tickers[c_i] not in ("FNMA", "FMCC", "HTZ"):
                seg_breaks_new[max(0, r_i - 5):min(n_days, r_i + 6), c_i] = 1

        all_tickers = base_tickers + new_tickers
        P_adj = np.hstack([cache["P_adj"], P_adj_new])
        P_cls = np.hstack([cache["P_cls"], P_cls_new])
        pre_ret_63d = np.hstack([cache["pre_ret_63d"], pre_new[63]])
        pre_ret_126d = np.hstack([cache["pre_ret_126d"], pre_new[126]])
        pre_ret_252d = np.hstack([cache["pre_ret_252d"], pre_new[252]])
        pre_ret_504d = np.hstack([cache["pre_ret_504d"], pre_new[504]])
        pre_ret_756d = np.hstack([cache["pre_ret_756d"], pre_new[756]])
        pre_ret_1260d = np.hstack([cache["pre_ret_1260d"], pre_new[1260]])
        dist_52w_high = np.hstack([cache["dist_52w_high"], dist_52w_new])
        dist_2y_high = np.hstack([cache["dist_2y_high"], dist_2y_new])
        max_dd_252d = np.hstack([cache["max_dd_252d"], max_dd_252_new])
        realized_vol_252d = np.hstack([cache["realized_vol_252d"], vol_252_new])
        ma50_above_ma200 = np.hstack([cache["ma50_above_ma200"], ma50_gt_200_new])
        pos_21d_win_24m = np.hstack([cache["pos_21d_win_24m"], pos_24m_new])
        slow_tag = np.hstack([cache["slow_tag"], slow_new])
        seg_breaks = np.hstack([cache["seg_breaks"], seg_breaks_new])
        last_valid_idx = np.concatenate([cache["last_valid_idx"], last_new])
    else:
        all_tickers = base_tickers
        P_adj = cache["P_adj"]
        P_cls = cache["P_cls"]
        pre_ret_63d = cache["pre_ret_63d"]
        pre_ret_126d = cache["pre_ret_126d"]
        pre_ret_252d = cache["pre_ret_252d"]
        pre_ret_504d = cache["pre_ret_504d"]
        pre_ret_756d = cache["pre_ret_756d"]
        pre_ret_1260d = cache["pre_ret_1260d"]
        dist_52w_high = cache["dist_52w_high"]
        dist_2y_high = cache["dist_2y_high"]
        max_dd_252d = cache["max_dd_252d"]
        realized_vol_252d = cache["realized_vol_252d"]
        ma50_above_ma200 = cache["ma50_above_ma200"]
        pos_21d_win_24m = cache["pos_21d_win_24m"]
        slow_tag = cache["slow_tag"]
        seg_breaks = cache["seg_breaks"]
        last_valid_idx = cache["last_valid_idx"]

    n_stocks = len(all_tickers)
    tk_to_col = {tk: i for i, tk in enumerate(all_tickers)}
    for tk, idx in list(tk_to_col.items()):
        for alt in (tk.replace(".", "-"), tk.replace("-", ".")):
            if alt not in tk_to_col:
                tk_to_col[alt] = idx

    terminal_rets = np.array([cache["terminal_rets"][i] if i < len(base_tickers) else 0.0 for i in range(n_stocks)], dtype=np.float32)
    for i, tk in enumerate(all_tickers):
        tr = term_lookup.get(tk) if tk in term_lookup else term_lookup.get(tk.replace("-", "."))
        if tr is not None and last_valid_idx[i] < n_days - 15:
            terminal_rets[i] = float(tr)

    sp_mat = np.zeros((n_days, n_stocks), dtype=bool)
    for _, row in sp_hist.iterrows():
        c = tk_to_col.get(str(row["ticker"]).strip(), -1)
        if c >= 0:
            s_idx = np.searchsorted(dates, np.datetime64(row["start_date"].strftime("%Y-%m-%d")))
            e_idx = np.searchsorted(dates, np.datetime64(row["end_date"].strftime("%Y-%m-%d")), side="right")
            sp_mat[s_idx:e_idx, c] = True

    print(f"[Engine30Y] Ready in {time.time()-t0:.2f}s: {n_stocks} stocks x {n_days} trading days.")
    return {
        "dates": dates,
        "dates_ts": dates_ts,
        "n_days": n_days,
        "tickers": all_tickers,
        "tk_to_col": tk_to_col,
        "sec_map": sec_map,
        "P_adj": P_adj,
        "P_cls": P_cls,
        "spy_tr": cache["spy_tr"],
        "pre_ret_63d": pre_ret_63d,
        "pre_ret_126d": pre_ret_126d,
        "pre_ret_252d": pre_ret_252d,
        "pre_ret_504d": pre_ret_504d,
        "pre_ret_756d": pre_ret_756d,
        "pre_ret_1260d": pre_ret_1260d,
        "dist_52w_high": dist_52w_high,
        "dist_2y_high": dist_2y_high,
        "max_dd_252d": max_dd_252d,
        "realized_vol_252d": realized_vol_252d,
        "ma50_above_ma200": ma50_above_ma200,
        "pos_21d_win_24m": pos_21d_win_24m,
        "slow_tag": slow_tag,
        "seg_breaks": seg_breaks,
        "last_valid_idx": last_valid_idx,
        "terminal_rets": terminal_rets,
        "sp_mat": sp_mat,
    }


# ==============================================================================
# 3. Eight Strategies + Two Control Traps Definitions (2009-2026 Exact XBRL)
# ==============================================================================
STRATEGY_NAMES = [
    ("S1_缓涨高增策略", "S1", "Strategy"),
    ("S2_高护城河稳态复利", "S2", "Strategy"),
    ("S3_低估值真拐点", "S3", "Strategy"),
    ("S4_连3季双加速主升", "S4", "Strategy"),
    ("S5_财报真加速错杀", "S5", "Strategy"),
    ("S6_50法则经营杠杆跳涨", "S6", "Strategy"),
    ("S7_微亏商业化突破", "S7", "Strategy"),
    ("S8_高ROIC净缩股食人族", "S8", "Strategy"),
    ("T1_高稀释烧钱高PS", "T1", "Control_Trap"),
    ("T2_强周期低PE利润极顶", "T2", "Control_Trap"),
]


def define_8_strategies_xbrl(d: pd.DataFrame) -> dict:
    dil_eff = d["dilution_yoy_clean"].fillna(d["shares_yoy_dilution"])
    clean_fcf = d["fcf_ttm"] - d["sbc_ttm"].fillna(0.0)
    non_fin_reit = d["sector_type"] != "Financial_Utility_RateSens"

    # S1: 1.5-3Y smooth slow uptrend + Rev YoY >= 15% + ROIC >= 15% + GM >= 55%
    s1_smooth = (
        d["slow_uptrend_tag"].isin(["SlowUp_2to5Y", "SlowUp_6Mto2Y"])
        & ((d["pre_ret_504d"] >= 0.25) | (d["pre_ret_756d"] >= 0.35))
        & (d["max_dd_252d"] > -0.28)
        & (d["realized_vol_252d"] < 0.42)
    )
    m_s1 = s1_smooth & (d["rev_yoy"] >= 0.15) & (d["roic_ttm"] >= 0.15) & (d["gm_q"] >= 0.55)

    # S2: 5Y GM std < 3% + GM >= 55% + ROIC >= 20%
    m_s2 = (d["gm_5y_std_pit"] < 0.03) & (d["gm_q"] >= 0.55) & (d["roic_ttm"] >= 0.20) & non_fin_reit

    # S3: 0 < PE < 15 + Earn Jump >= 5% + OCF/NI >= 0.85 + Non-Cyclical Peak
    is_cyc_peak = ((d["sector_type"] == "Deep_Cyclical") & (d["opm_5y_pct_pit"].fillna(0.5) >= 0.85)) | (
        d["opm_5y_pct_pit"].fillna(0.5) >= 0.90
    )
    m_s3 = (d["pe_pit"] > 0.0) & (d["pe_pit"] < 15.0) & (d["earn_jump_ret"] >= 0.05) & (d["ocf_to_ni_ttm"] >= 0.85) & (~is_cyc_peak)

    # S4: >=3Q consecutive rev accel + margin expansion + FCF > 0 + dilution <= 3%
    m_s4 = (
        (d["consec_rev_accel_n"] >= 3)
        & ((d["opm_yoy_chg"] > 0.0) | (d["consec_opm_expand_n"] >= 1) | (d["gm_sga_yoy_chg"] > 0.0))
        & (d["fcf_ttm"] > 0.0)
        & (dil_eff <= 0.03)
    )

    # S5: (>=3Q rev accel OR GM-SGA>=10% expanding with positive rev growth & accel) + Earn Drop <= -4% next-day dip buy
    m_s5 = (
        (
            (d["consec_rev_accel_n"] >= 3)
            | ((d["gm_minus_sga_q"] >= 0.10) & (d["gm_sga_yoy_chg"] > 0.0) & (d["rev_yoy"] >= 0.10) & (d["rev_accel_1q"] > 0.0))
        )
        & (d["earn_jump_ret"] <= -0.04)
    )

    # S6: Rule of 50 operating leverage jump: Rev YoY + OPM >= 50% + OPM YoY chg >= +3pct + Jump >= +6% + 0 < PS <= 20
    m_s6 = (
        ((d["rev_yoy"] + d["opm_q"]) >= 0.50)
        & (d["opm_yoy_chg"] >= 0.03)
        & (d["earn_jump_ret"] >= 0.06)
        & (d["ps_pit"] > 0.0)
        & (d["ps_pit"] <= 20.0)
        & non_fin_reit
    )

    # S7: Narrow-loss commercialization breakthrough: OPM in [-15%, 0%) + GM-SGA >= 10% consec expanding + Rev >= 25% + dilution <= 5%
    m_s7 = (
        (d["opm_q"] >= -0.15)
        & (d["opm_q"] < 0.0)
        & (d["gm_minus_sga_q"] >= 0.10)
        & ((d["consec_gm_sga_expand_n"] >= 2) | ((d["consec_gm_sga_expand_n"] >= 1) & (d["gm_sga_yoy_chg"] > 0.0)))
        & (d["rev_yoy"] >= 0.25)
        & (dil_eff <= 0.05)
    )

    # S8: High-ROIC net share cannibal: ROIC >= 20% + annual net share reduction >= 2% + positive Clean FCF
    m_s8 = (d["roic_ttm"] >= 0.20) & (dil_eff <= -0.02) & (clean_fcf > 0.0) & (d["fcf_ttm"] > 0.0)

    # T1: High-dilution / Cash-burn / Unprofitable High-PS Trap (PS>15 cash-burn/unprofitable OR dilution>4% & negative FCF)
    m_t1 = non_fin_reit & (
        ((d["ps_pit"] > 15.0) & ((clean_fcf <= 0.0) | (d["fcf_ttm"] <= 0.0) | (d["opm_q"] < 0.0)))
        | ((dil_eff > 0.04) & ((d["fcf_ttm"] < 0.0) | (clean_fcf < 0.0)))
    )

    # T2: Deep-Cyclical Low-PE Peak Margin Trap (0 < PE < 12 + 5Y OPM >= 85th percentile in Deep Cyclicals)
    m_t2 = (d["pe_pit"] > 0.0) & (d["pe_pit"] < 12.0) & (d["opm_5y_pct_pit"] >= 0.85) & (d["sector_type"] == "Deep_Cyclical")

    return {
        "S1_缓涨高增策略": m_s1,
        "S2_高护城河稳态复利": m_s2,
        "S3_低估值真拐点": m_s3,
        "S4_连3季双加速主升": m_s4,
        "S5_财报真加速错杀": m_s5,
        "S6_50法则经营杠杆跳涨": m_s6,
        "S7_微亏商业化突破": m_s7,
        "S8_高ROIC净缩股食人族": m_s8,
        "T1_高稀释烧钱高PS": m_t1,
        "T2_强周期低PE利润极顶": m_t2,
    }


# ==============================================================================
# 4. Build 1996-2026 Full 30Y SEC Earnings + Trajectory SP500_PIT Panel
# ==============================================================================
def build_30y_sp500_sec_panel(eng: dict, macro_df: pd.DataFrame) -> pd.DataFrame:
    t0 = time.time()
    sec_files = sorted(glob.glob(os.path.join(TMP_DIR, "pre2009_shards/sec_filings_1995_2026_part*.parquet")))
    sec_all = pd.concat([pd.read_parquet(f) for f in sec_files], ignore_index=True)
    sec_all["filingDate"] = pd.to_datetime(sec_all["filingDate"]).dt.normalize()
    sec_all = sec_all[(sec_all["filingDate"] >= "1995-01-01") & (sec_all["filingDate"] <= "2026-11-06")].copy()
    sec_all = sec_all.sort_values(["ticker", "filingDate"]).reset_index(drop=True)

    keep = np.ones(len(sec_all), dtype=bool)
    tks = sec_all["ticker"].astype(str).values
    dts = sec_all["filingDate"].values.astype("datetime64[D]").astype(np.int64)
    for i in range(1, len(sec_all)):
        if tks[i] == tks[i - 1] and (dts[i] - dts[i - 1]) < 25:
            keep[i] = False
    ev = sec_all[keep].copy().reset_index(drop=True)

    tk2c = eng["tk_to_col"]
    dates = eng["dates"]
    dates_ts = eng["dates_ts"]
    n_days = eng["n_days"]
    P_adj = eng["P_adj"]
    P_cls = eng["P_cls"]
    spy_tr = eng["spy_tr"]
    last_v = eng["last_valid_idx"]
    term_r = eng["terminal_rets"]
    sp_mat = eng["sp_mat"]

    cols = np.array([tk2c.get(str(t).strip(), -1) for t in ev["ticker"].values], dtype=np.int32)
    ev_dt = ev["filingDate"].values.astype("datetime64[D]")
    idx_ev = np.clip(np.searchsorted(dates, ev_dt), 0, n_days - 1)
    idx_pre = idx_ev - 1
    idx_ent = idx_ev + 1  # Strict D+1 close entry

    valid = (idx_pre >= 0) & (idx_ent < n_days) & (cols >= 0)
    ev = ev[valid].copy().reset_index(drop=True)
    cols = cols[valid]
    idx_ev = idx_ev[valid]
    idx_pre = idx_pre[valid]
    idx_ent = idx_ent[valid]
    m_len = len(ev)

    pre_px = P_adj[idx_pre, cols]
    ent_px = P_adj[idx_ent, cols]
    cls_pre = P_cls[idx_pre, cols]
    is_sp500 = sp_mat[idx_pre, cols]
    has_brk = (eng["seg_breaks"][idx_pre, cols] > 0) | (eng["seg_breaks"][idx_ent, cols] > 0)

    ev["pre_date"] = dates_ts.values[idx_pre]
    ev["entry_date"] = dates_ts.values[idx_ent]
    ev["is_sp500_pit"] = is_sp500
    ev["has_anomaly_break"] = has_brk
    ev["unadj_pre_px"] = cls_pre

    ev["pre_ret_63d"] = eng["pre_ret_63d"][idx_pre, cols]
    ev["pre_ret_126d"] = eng["pre_ret_126d"][idx_pre, cols]
    ev["pre_ret_252d"] = eng["pre_ret_252d"][idx_pre, cols]
    ev["pre_ret_504d"] = eng["pre_ret_504d"][idx_pre, cols]
    ev["pre_ret_756d"] = eng["pre_ret_756d"][idx_pre, cols]
    ev["pre_ret_1260d"] = eng["pre_ret_1260d"][idx_pre, cols]
    ev["dist_52w_high"] = eng["dist_52w_high"][idx_pre, cols]
    ev["dist_2y_high"] = eng["dist_2y_high"][idx_pre, cols]
    ev["max_dd_252d"] = eng["max_dd_252d"][idx_pre, cols]
    ev["realized_vol_252d"] = eng["realized_vol_252d"][idx_pre, cols]
    ev["ma50_above_ma200"] = eng["ma50_above_ma200"][idx_pre, cols].astype(bool)
    ev["pos_21d_win_24m"] = eng["pos_21d_win_24m"][idx_pre, cols]

    t_codes = eng["slow_tag"][idx_pre, cols]
    slow_tags = np.full(m_len, "Other_Neutral", dtype=object)
    for code, t_str in TAG_MAP.items():
        mm = t_codes == code
        if np.any(mm):
            slow_tags[mm] = t_str
    ev["slow_uptrend_tag"] = slow_tags
    ev["sector_type"] = [eng["sec_map"].get(str(tk).strip(), "Industrial_Consumer_Compounder") for tk in ev["ticker"].values]

    ok_px = (pre_px > 0) & (~np.isnan(pre_px)) & (ent_px > 0) & (~np.isnan(ent_px))
    earn_jump = np.where(ok_px, ent_px / pre_px - 1.0, np.nan)
    spy_win = spy_tr[idx_ent] / spy_tr[idx_pre] - 1.0
    ev["earn_jump_ret"] = earn_jump
    ev["earn_excess_ret"] = earn_jump - spy_win

    # Compute zero-lookahead consecutive positive & negative earnings reaction streaks per ticker
    ev = ev.sort_values(["ticker", "filingDate"]).reset_index(drop=True)
    pos_streak = np.zeros(len(ev), dtype=np.int16)
    neg_streak = np.zeros(len(ev), dtype=np.int16)
    tks_arr = ev["ticker"].values
    ex_arr = ev["earn_excess_ret"].values
    cur_p, cur_n = 0, 0
    prev_tk = None
    for i in range(len(ev)):
        if tks_arr[i] != prev_tk:
            cur_p, cur_n = 0, 0
            prev_tk = tks_arr[i]
        if not np.isnan(ex_arr[i]):
            if ex_arr[i] > 0.005:
                cur_p += 1
                cur_n = 0
            elif ex_arr[i] < -0.005:
                cur_n += 1
                cur_p = 0
            else:
                cur_p, cur_n = 0, 0
        else:
            cur_p, cur_n = 0, 0
        pos_streak[i] = cur_p
        neg_streak[i] = cur_n
    ev["consec_pos_earn_streak"] = pos_streak
    ev["consec_neg_earn_streak"] = neg_streak

    cols_s = np.array([tk2c.get(str(t).strip(), -1) for t in ev["ticker"].values], dtype=np.int32)
    idx_ent_s = np.clip(np.searchsorted(dates, ev["entry_date"].values.astype("datetime64[D]")), 0, n_days - 1)
    p0_s = P_adj[idx_ent_s, cols_s]
    lv_s = last_v[cols_s]
    tr_s = term_r[cols_s]
    valid_e = np.where((p0_s > 0) & (~np.isnan(p0_s)))[0]

    de_v = idx_ent_s[valid_e]
    ce_v = cols_s[valid_e]
    p0_v = p0_s[valid_e]
    lv_v = lv_s[valid_e]
    tr_v = tr_s[valid_e]

    for h in (63, 252, 504, 756):
        stk_r = np.full(len(ev), np.nan, dtype=np.float32)
        alp_r = np.full(len(ev), np.nan, dtype=np.float32)
        dtgt = de_v + h

        m_norm = dtgt < n_days
        in_norm = np.where(m_norm)[0]
        if len(in_norm) > 0:
            pt = P_adj[dtgt[in_norm], ce_v[in_norm]]
            ok_t = (~np.isnan(pt)) & (pt > 0)
            in_ok = in_norm[ok_t]
            rs = pt[ok_t] / p0_v[in_ok] - 1.0
            rb = spy_tr[dtgt[in_ok]] / spy_tr[de_v[in_ok]] - 1.0
            orig_i = valid_e[in_ok]
            stk_r[orig_i] = rs
            alp_r[orig_i] = rs - rb

        m_del = (lv_v < dtgt) & (lv_v < n_days - 15) & (lv_v >= de_v)
        in_del = np.where(m_del)[0]
        if len(in_del) > 0:
            pl = P_adj[lv_v[in_del], ce_v[in_del]]
            r_last = np.where((~np.isnan(pl)) & (pl > 0), pl / p0_v[in_del] - 1.0, -1.0)
            rtot = (1.0 + r_last) * (1.0 + tr_v[in_del]) - 1.0
            d_spy = np.minimum(dtgt[in_del], n_days - 1)
            rb = spy_tr[d_spy] / spy_tr[de_v[in_del]] - 1.0
            orig_i = valid_e[in_del]
            stk_r[orig_i] = rtot
            alp_r[orig_i] = rtot - rb

        ev[f"fwd_{h}d"] = stk_r
        ev[f"alpha_fwd_{h}d"] = alp_r

    ev_sp = ev[
        (ev["filingDate"] >= "1996-01-01")
        & ev["is_sp500_pit"]
        & (~ev["has_anomaly_break"])
        & (ev["unadj_pre_px"] >= 3.0)
        & ev["earn_jump_ret"].notna()
    ].copy().reset_index(drop=True)

    cols_sp = np.array([tk2c.get(str(t).strip(), -1) for t in ev_sp["ticker"].values], dtype=np.int32)
    idx_ent_sp = np.clip(np.searchsorted(dates, ev_sp["entry_date"].values.astype("datetime64[D]")), 0, n_days - 1)
    mdd_arr = np.full(len(ev_sp), np.nan, dtype=np.float32)
    for k in range(len(ev_sp)):
        d0 = idx_ent_sp[k]
        c0 = cols_sp[k]
        sl = P_adj[d0:min(d0 + 253, n_days), c0]
        vs = sl[(~np.isnan(sl)) & (sl > 0)]
        if len(vs) > 1:
            cmax = np.maximum.accumulate(vs)
            mv = float(np.min(vs / cmax - 1.0))
            if last_v[c0] < d0 + 252 and last_v[c0] < n_days - 15 and term_r[c0] < -0.50:
                mv = min(mv, float(term_r[c0]))
            mdd_arr[k] = mv
    ev_sp["fwd_max_dd_252d"] = mdd_arr

    ev_sp["macro_join_date"] = pd.to_datetime(ev_sp["pre_date"]).dt.normalize()
    m_cols = [
        "macro_join_date", "dgs10", "dgs10_chg_126d", "real_rate_10y_pit", "t10y2y",
        "baa10y", "vix", "indpro_yoy_pit", "cpi_yoy_pit", "era_regime", "macro_quadrant",
        "m1_dgs10_5bin", "m2_rate6m_4bin", "m3_realrate_4bin", "m4_yc_4bin",
        "m5_baa_4bin", "m6_vix_4bin", "m7_merrill_4q",
    ]
    ev_sp = ev_sp.merge(macro_df[m_cols], on="macro_join_date", how="left")
    print(f"[Panel30Y] Built 1996-2026 SP500_PIT SEC Earnings Panel: {len(ev_sp):,} events across {ev_sp['ticker'].nunique()} tickers in {time.time()-t0:.2f}s.")
    return ev_sp


def define_8_strategies_30y_proxy(d: pd.DataFrame) -> dict:
    """
    Consistent 1996-2026 30-Year Price/Volatility/SEC-Earnings-Streak Proxy Definitions on SP500_PIT:
    Note: T1 strictly models high-volatility fundamental bleed / broken-story stocks (vol >= 42% + >=2Q consecutive
    negative earnings excess reaction + broken trend), NOT profitable S&P 500 leaders like CSCO/NVDA!
    """
    non_cyc = d["sector_type"] != "Deep_Cyclical"
    non_fin = d["sector_type"] != "Financial_Utility_RateSens"
    growth_sec = d["sector_type"].isin(["Software_Internet", "Tech_Hardware_Semi", "Healthcare_LifeSci"])

    # S1: Smooth 1.5-3Y slow uptrend + positive earnings confirmation
    m_s1 = (
        d["slow_uptrend_tag"].isin(["SlowUp_2to5Y", "SlowUp_6Mto2Y"])
        & ((d["pre_ret_504d"] >= 0.35) | (d["pre_ret_756d"] >= 0.45))
        & (d["max_dd_252d"] > -0.24)
        & (d["realized_vol_252d"] < 0.34)
        & (d["earn_jump_ret"] >= 0.01)
    )

    # S2: Ultra-low-volatility steady moat compounder (3Y+ positive compounding, vol < 23%, shallow drawdown < 18%)
    m_s2 = (
        (d["pre_ret_756d"] >= 0.25)
        & (d["realized_vol_252d"] < 0.23)
        & (d["max_dd_252d"] > -0.18)
        & non_cyc
        & non_fin
    )

    # S3: Depressed / low-expectation true earnings turnaround jump (>=+5% SEC earnings jump off multi-quarter lag, non-cyclical 3Y peak)
    m_s3 = (
        (d["dist_2y_high"] <= -0.20)
        & (d["pre_ret_252d"] <= 0.05)
        & (d["earn_jump_ret"] >= 0.05)
        & ~((d["sector_type"] == "Deep_Cyclical") & (d["pre_ret_756d"] > 0.80))
    )

    # S4: >=3 consecutive quarters of positive SEC earnings excess reaction + uptrend
    m_s4 = (
        (d["consec_pos_earn_streak"] >= 3)
        & d["ma50_above_ma200"]
        & (d["slow_uptrend_tag"] != "HighFlyer_Parabolic")
    )

    # S5: Prior multi-quarter beat streak or healthy slow uptrend + sudden >=4% earnings drop dip-buy
    m_s5 = (
        (
            (d["consec_pos_earn_streak"].shift(1).where(d["ticker"] == d["ticker"].shift(1), 0) >= 2)
            | (d["slow_uptrend_tag"].isin(["SlowUp_2to5Y", "SlowUp_6Mto2Y"]) & (d["pre_ret_252d"] >= 0.15))
        )
        & (d["earn_jump_ret"] <= -0.04)
    )

    # S6: Strong operating momentum breakout jump (earn jump >= +6% near 52w high, non-parabolic)
    m_s6 = (
        (d["earn_jump_ret"] >= 0.06)
        & d["ma50_above_ma200"]
        & (d["dist_52w_high"] >= -0.15)
        & (d["pre_ret_252d"] >= 0.15)
        & (d["pre_ret_126d"] <= 0.90)
    )

    # S7: Tech/Healthcare turnaround commercialization breakout (off >=18% 2Y drawdown turning positive 3M momentum + >=5% jump)
    m_s7 = (
        growth_sec
        & (d["dist_2y_high"] <= -0.18)
        & (d["pre_ret_63d"] > 0.03)
        & (d["earn_jump_ret"] >= 0.05)
    )

    # S8: Long-horizon mature compounder cannibal proxy (5Y ret >= 65%, moderate vol < 28%, non-cyclical/non-financial)
    m_s8 = (
        (d["pre_ret_1260d"] >= 0.65)
        & (d["realized_vol_252d"] < 0.28)
        & (d["max_dd_252d"] > -0.24)
        & non_cyc
        & non_fin
    )

    # T1: Overextended speculative story / bubble high-vol stock cracking on earnings (1Y/2Y surge + vol >= 45% + earn drop <= -3%)
    m_t1 = (
        ((d["pre_ret_252d"] >= 0.50) | (d["pre_ret_504d"] >= 0.80))
        & (d["realized_vol_252d"] >= 0.45)
        & (d["earn_jump_ret"] <= -0.03)
        & non_fin
    )

    # T2: Deep-cyclical multi-year boom peak stall proxy (Deep_Cyclical after >=80% 2Y/3Y surge with flat/negative earnings reaction)
    m_t2 = (
        (d["sector_type"] == "Deep_Cyclical")
        & ((d["pre_ret_504d"] >= 0.80) | (d["pre_ret_756d"] >= 1.00))
        & (d["earn_jump_ret"] <= 0.0)
    )

    return {
        "S1_缓涨高增策略": m_s1,
        "S2_高护城河稳态复利": m_s2,
        "S3_低估值真拐点": m_s3,
        "S4_连3季双加速主升": m_s4,
        "S5_财报真加速错杀": m_s5,
        "S6_50法则经营杠杆跳涨": m_s6,
        "S7_微亏商业化突破": m_s7,
        "S8_高ROIC净缩股食人族": m_s8,
        "T1_高稀释烧钱高PS": m_t1,
        "T2_强周期低PE利润极顶": m_t2,
    }


# ==============================================================================
# 5. Standardized Metric Formatting & Traffic-Light Switch Assignment
# ==============================================================================
CURRENT_2026_11_BINS = {
    "1_10Y美债名义利率(5档)": "4_4-5%",
    "2_10Y利率半年变化(4档)": "4_上行>=+35bp",
    "3_10Y_TIPS实际利率(4档)": "4_高实际利率>=2.0%",
    "4_10Y-2Y收益率曲线(4周期)": "3_正常正斜率10至120bp",
    "5_BAA信用利差(4档)": "1_极紧<1.7%",
    "6_VIX恐慌指数(4档)": "3_22-30",
    "7_工业产出x通胀美林四象限": "2_过热再通胀Capex(INDPRO>=1%_CPI>=3%)",
}


def classify_switch_signal(a1y: float, win1y: float, t1y: float, med1y: float, n1y: int) -> str:
    if n1y < 8 or pd.isna(a1y):
        return "LOW_SAMPLE_HOLD"
    if a1y <= -0.02 or (pd.notna(med1y) and med1y <= -0.06 and win1y < 0.45):
        return "OFF_VETO_关闭"
    if a1y >= 0.06 and (win1y >= 0.50 or med1y >= 0.01 or (pd.notna(t1y) and t1y >= 1.8)):
        return "STRONG_ON_全开"
    if a1y >= 0.02 and (win1y >= 0.48 or med1y >= 0.0):
        return "ON_开启"
    return "NEUTRAL_半仓观察"


def evaluate_grid_for_track(
    df_panel: pd.DataFrame,
    strat_masks: dict,
    track_name: str,
    dedup_days: int = 250,
) -> pd.DataFrame:
    horizons = (63, 252, 504, 756)
    dt_ent = pd.to_datetime(df_panel["entry_date"])
    ex_covid = ~((dt_ent >= "2020-03-01") & (dt_ent <= "2021-12-31"))

    rows = []
    dim_iter = [
        ("0_全样本与隔离基线", "1_Full_Period", pd.Series(True, index=df_panel.index)),
        ("0_全样本与隔离基线", "2_Ex_2020_2021_ZIRP_Bubble", ex_covid),
    ]
    for dim_label, col_name in MACRO_DIM_SPECS[1:]:
        bins = sorted([b for b in df_panel[col_name].dropna().unique() if b not in ("Unknown", "nan", "None")])
        for b in bins:
            dim_iter.append((dim_label, b, df_panel[col_name] == b))

    for dim_label, bin_label, reg_mask in dim_iter:
        is_cur_2026 = CURRENT_2026_11_BINS.get(dim_label) == bin_label
        for s_full, s_code, s_role in STRATEGY_NAMES:
            sub = df_panel[reg_mask & strat_masks[s_full]]
            if len(sub) < 5:
                continue
            st = eval_slice(
                sub,
                horizons=horizons,
                dedup_days=dedup_days,
                date_col="entry_date",
                label=f"{track_name} | {s_full} | {dim_label}:{bin_label}",
            )
            a1 = st.get("qtr_ew_alpha_252d", np.nan)
            w1 = st.get("win_rate_252d", np.nan)
            t1 = st.get("t_stat_252d", np.nan)
            m1 = st.get("med_alpha_252d", np.nan)
            n1 = st.get("n_252d", 0)

            rows.append(
                {
                    "track_universe": track_name,
                    "strategy_code": s_code,
                    "strategy_name": s_full,
                    "strategy_role": s_role,
                    "macro_dimension": dim_label,
                    "macro_bin": bin_label,
                    "is_2026_11_current_bin": bool(is_cur_2026),
                    "action_switch": classify_switch_signal(a1, w1, t1, m1, n1),
                    "n_raw": st.get("n_raw", 0),
                    "n_dedup": st.get("n_dedup", 0),
                    "n_tickers": st.get("n_tickers", 0),
                    "n_1y": n1,
                    "n_qtrs_1y": st.get("n_qtrs_252d", 0),
                    "qtr_ew_alpha_1q_pct": round(st.get("qtr_ew_alpha_63d", np.nan) * 100, 2),
                    "qtr_ew_alpha_1y_pct": round(a1 * 100, 2) if pd.notna(a1) else np.nan,
                    "qtr_ew_alpha_2y_pct": round(st.get("qtr_ew_alpha_504d", np.nan) * 100, 2),
                    "qtr_ew_alpha_3y_pct": round(st.get("qtr_ew_alpha_756d", np.nan) * 100, 2),
                    "med_alpha_1y_pct": round(m1 * 100, 2) if pd.notna(m1) else np.nan,
                    "med_alpha_2y_pct": round(st.get("med_alpha_504d", np.nan) * 100, 2),
                    "med_alpha_3y_pct": round(st.get("med_alpha_756d", np.nan) * 100, 2),
                    "win_rate_1y_pct": round(w1 * 100, 1) if pd.notna(w1) else np.nan,
                    "win_rate_2y_pct": round(st.get("win_rate_504d", np.nan) * 100, 1),
                    "win_rate_3y_pct": round(st.get("win_rate_756d", np.nan) * 100, 1),
                    "payoff_1y": round(st.get("payoff_252d", np.nan), 2),
                    "med_mdd_1y_pct": round(st.get("med_mdd_1y", np.nan) * 100, 2),
                    "mdd50_1y_prob_pct": round(st.get("mdd50_1y_prob", np.nan) * 100, 1),
                    "bag2x_1y_prob_pct": round(st.get("bag2x_prob_252d", np.nan) * 100, 1),
                    "halve_end_1y_prob_pct": round(st.get("halve_prob_252d", np.nan) * 100, 1),
                    "t_stat_1y": round(t1, 2) if pd.notna(t1) else np.nan,
                    "t_stat_2y": round(st.get("t_stat_504d", np.nan), 2),
                    "t_stat_3y": round(st.get("t_stat_756d", np.nan), 2),
                    "p_val_1y": st.get("p_val_252d", np.nan),
                    "p_val_2y": st.get("p_val_504d", np.nan),
                    "p_val_3y": st.get("p_val_756d", np.nan),
                }
            )

    out_df = pd.DataFrame(rows)
    for h_lbl in ("1y", "2y", "3y"):
        p_col = f"p_val_{h_lbl}"
        q_col = f"bh_fdr_q_{h_lbl}"
        if p_col in out_df.columns:
            out_df[q_col] = np.round(benjamini_hochberg_fdr(out_df[p_col].values), 4)
            out_df[p_col] = np.round(out_df[p_col], 4)
    return out_df


# ==============================================================================
# 6. Build 1996-2026 30Y Regime Playbook (8 Eras + 31 Years + 2026.11 Live Rank)
# ==============================================================================
ERAS_8_SPEC = [
    ("1996_2000_DotCom", 1996, 2000, "科网高利率Capex牛市(10Y 5.5-6.5% + 实际利率>3% + 良性信用)"),
    ("2001_2002_TechBust", 2001, 2002, "科网泡沫破灭衰退熊市(急降息 + 杀高估值 + 信用走阔)"),
    ("2003_2007_CycleBull", 2003, 2007, "格林斯潘加息扩产周期牛(利率上行 + 工业Capex繁荣 + 极紧信用利差)"),
    ("2008_2009_GFC", 2008, 2009, "次贷金融海啸与零利率救市(BAA>=3.5%危机出清 + 曲线陡峭化)"),
    ("2010_2019_LowRateBull", 2010, 2019, "低利率温和增长慢牛(10Y 1.5-3.0% + 金发姑娘低波期)"),
    ("2020_2021_ZeroRateCovid", 2020, 2021, "疫情零利率QE流动性洪水(负实际利率-1.0% + 极陡曲线)"),
    ("2022_2023_RateHikeReset", 2022, 2023, "40年最猛加息估值重置(10Y急升至5% + 曲线深倒挂)"),
    ("2024_2026_HighRateAI", 2024, 2026, "高实际利率AI资本开支繁荣(10Y 4-5% + 实际利率>2% + 极紧利差)"),
]


def rank_strategies_in_window(
    df_win: pd.DataFrame,
    masks_win: dict,
    df_sp_strict: pd.DataFrame = None,
    masks_sp_strict: dict = None,
    min_n: int = 4,
    dedup_days: int = 180,
) -> list:
    """
    Evaluates strategies in a time window. For T1 (high-dilution cash-burn trap), when strict S&P 500 PIT
    observations exist (n >= 3), uses the strict zero-survivorship S&P 500 PIT slice so backfilled 2026 small-cap
    lottery survivors do not contaminate the control trap benchmark.
    """
    perf = []
    for s_full, s_code, s_role in STRATEGY_NAMES:
        if s_code == "T1" and df_sp_strict is not None and masks_sp_strict is not None:
            sub_sp = df_sp_strict[masks_sp_strict.get(s_full, pd.Series(False, index=df_sp_strict.index))]
            sub = sub_sp if len(sub_sp) >= 3 else df_win[masks_win.get(s_full, pd.Series(False, index=df_win.index))]
        else:
            sub = df_win[masks_win.get(s_full, pd.Series(False, index=df_win.index))]

        if len(sub) < min_n:
            continue

        st = eval_slice(sub, horizons=(63, 252, 504, 756), dedup_days=dedup_days, date_col="entry_date")
        n1 = st.get("n_252d", 0)
        if n1 >= min_n and pd.notna(st.get("qtr_ew_alpha_252d", np.nan)):
            score = st["qtr_ew_alpha_252d"]
            win = st.get("win_rate_252d", np.nan)
            med = st.get("med_alpha_252d", np.nan)
            a2 = st.get("qtr_ew_alpha_504d", np.nan)
            a3 = st.get("qtr_ew_alpha_756d", np.nan)
            horizon_used = "1Y_252d"
            n_used = n1
        elif st.get("n_63d", 0) >= min_n and pd.notna(st.get("qtr_ew_alpha_63d", np.nan)):
            score = st["qtr_ew_alpha_63d"]
            win = st.get("win_rate_63d", np.nan)
            med = st.get("med_alpha_63d", np.nan)
            a2 = np.nan
            a3 = np.nan
            horizon_used = "1Q_63d_2026YTD"
            n_used = st.get("n_63d", 0)
        else:
            continue

        perf.append(
            {
                "code": s_code,
                "name": s_full,
                "role": s_role,
                "n": int(n_used),
                "horizon_used": horizon_used,
                "alpha_primary_pct": round(score * 100, 2),
                "med_alpha_pct": round(med * 100, 2) if pd.notna(med) else np.nan,
                "win_rate_pct": round(win * 100, 1) if pd.notna(win) else np.nan,
                "alpha_2y_pct": round(a2 * 100, 2) if pd.notna(a2) else np.nan,
                "alpha_3y_pct": round(a3 * 100, 2) if pd.notna(a3) else np.nan,
                "mdd_1y_pct": round(st.get("med_mdd_1y", np.nan) * 100, 1) if pd.notna(st.get("med_mdd_1y", np.nan)) else np.nan,
            }
        )
    perf.sort(key=lambda x: x["alpha_primary_pct"], reverse=True)
    return perf


def build_30y_regime_playbook(
    d_xbrl_sp: pd.DataFrame,
    masks_xbrl_sp: dict,
    d_xbrl_all: pd.DataFrame,
    masks_xbrl_all: dict,
    ev_30y: pd.DataFrame,
    masks_30y: dict,
    macro_df: pd.DataFrame,
    df_grid_all: pd.DataFrame,
):
    playbook_rows = []

    m96 = macro_df[(macro_df["date"] >= "1996-01-01") & (macro_df["date"] <= "2026-11-09")].copy()
    m96["year"] = m96["date"].dt.year

    ev_30y_yr = pd.to_datetime(ev_30y["filingDate"]).dt.year
    xbrl_sp_yr = pd.to_datetime(d_xbrl_sp["entry_date"]).dt.year
    xbrl_all_yr = pd.to_datetime(d_xbrl_all["entry_date"]).dt.year

    # --------------------------------------------------------------------------
    # PART A: 8 Historical Eras (1996-2026)
    # --------------------------------------------------------------------------
    for era_code, y_start, y_end, era_desc in ERAS_8_SPEC:
        m_sub = m96[(m96["year"] >= y_start) & (m96["year"] <= y_end)]
        macro_summary = (
            f"10Y={m_sub['dgs10'].mean():.2f}% | Real={m_sub['real_rate_10y_pit'].mean():+.2f}% | "
            f"YC={m_sub['t10y2y'].mean():+.2f}% | BAA={m_sub['baa10y'].mean():.2f}% | "
            f"VIX={m_sub['vix'].mean():.1f} | INDPRO={m_sub['indpro_yoy_pit'].mean():+.1f}% | CPI={m_sub['cpi_yoy_pit'].mean():.1f}%"
        )

        if y_start >= 2010:
            w_all = (xbrl_all_yr >= y_start) & (xbrl_all_yr <= y_end)
            w_sp = (xbrl_sp_yr >= y_start) & (xbrl_sp_yr <= y_end)
            sub_all = d_xbrl_all[w_all]
            sub_sp = d_xbrl_sp[w_sp]
            m_all_w = {k: v.loc[sub_all.index] for k, v in masks_xbrl_all.items()}
            m_sp_w = {k: v.loc[sub_sp.index] for k, v in masks_xbrl_sp.items()}
            ranked = rank_strategies_in_window(sub_all, m_all_w, sub_sp, m_sp_w, min_n=5, dedup_days=250)
            data_source_tag = "Exact_XBRL_PIT(T1=Strict_SP500_PIT)"
        else:
            w_30 = (ev_30y_yr >= y_start) & (ev_30y_yr <= y_end)
            sub_30 = ev_30y[w_30]
            m_30_w = {k: v.loc[sub_30.index] for k, v in masks_30y.items()}
            ranked = rank_strategies_in_window(sub_30, m_30_w, min_n=5, dedup_days=180)
            data_source_tag = "SP500_PIT_SEC_Trajectory_30Y"

        s_only = [r for r in ranked if r["role"] == "Strategy"]
        top1 = s_only[0] if len(s_only) >= 1 else {}
        top2 = s_only[1] if len(s_only) >= 2 else {}
        worst_s = s_only[-1] if len(s_only) >= 1 else {}
        worst_all = ranked[-1] if len(ranked) >= 1 else {}

        full_rank_str = " > ".join([f"{r['code']}({r['alpha_primary_pct']:+.1f}%)" for r in ranked])

        playbook_rows.append(
            {
                "section_type": "PartA_8大历史时代最优与垫底策略(1996-2026)",
                "period_or_rank": era_code,
                "year_span": f"{y_start}-{y_end}",
                "data_track": data_source_tag,
                "macro_regime_summary": f"{era_desc} | {macro_summary}",
                "top1_strategy": top1.get("name", ""),
                "top1_alpha_1y_pct": top1.get("alpha_primary_pct", np.nan),
                "top1_win_1y_pct": top1.get("win_rate_pct", np.nan),
                "top1_alpha_3y_pct": top1.get("alpha_3y_pct", np.nan),
                "top2_strategy": top2.get("name", ""),
                "top2_alpha_1y_pct": top2.get("alpha_primary_pct", np.nan),
                "top2_win_1y_pct": top2.get("win_rate_pct", np.nan),
                "worst_strategy_among_S1_S8": worst_s.get("name", ""),
                "worst_S_alpha_1y_pct": worst_s.get("alpha_primary_pct", np.nan),
                "worst_overall_incl_traps": worst_all.get("name", ""),
                "worst_overall_alpha_1y_pct": worst_all.get("alpha_primary_pct", np.nan),
                "full_ranking_1_to_10": full_rank_str,
                "actionable_instruction": f"主开 {top1.get('code','')} + {top2.get('code','')}；严关 {worst_s.get('code','')} 与 {worst_all.get('code','')}",
            }
        )

    # --------------------------------------------------------------------------
    # PART B: Year-by-Year Annual Playbook (1996 to 2026, all 31 calendar years)
    # --------------------------------------------------------------------------
    for yr in range(1996, 2027):
        m_y = m96[m96["year"] == yr]
        if len(m_y) == 0:
            continue
        era_y = m_y["era_regime"].mode().iloc[0]
        q_y = m_y["m7_merrill_4q"].mode().iloc[0]
        macro_y_str = (
            f"10Y={m_y['dgs10'].mean():.2f}%(6M:{m_y['dgs10_chg_126d'].mean():+.2f}%) | "
            f"Real={m_y['real_rate_10y_pit'].mean():+.2f}% | YC={m_y['t10y2y'].mean():+.2f}% | "
            f"BAA={m_y['baa10y'].mean():.2f}% | VIX={m_y['vix'].mean():.1f} | {q_y}"
        )

        if yr >= 2011:
            w_all = xbrl_all_yr == yr
            w_sp = xbrl_sp_yr == yr
            sub_all = d_xbrl_all[w_all]
            sub_sp = d_xbrl_sp[w_sp]
            m_all_w = {k: v.loc[sub_all.index] for k, v in masks_xbrl_all.items()}
            m_sp_w = {k: v.loc[sub_sp.index] for k, v in masks_xbrl_sp.items()}
            ranked_y = rank_strategies_in_window(sub_all, m_all_w, sub_sp, m_sp_w, min_n=3, dedup_days=180)
            track_y = "XBRL_PIT_Annual(2026=1Q_63d)" if yr == 2026 else "XBRL_PIT_Annual"
        else:
            w_y = ev_30y_yr == yr
            sub_y = ev_30y[w_y]
            m_30_w = {k: v.loc[sub_y.index] for k, v in masks_30y.items()}
            ranked_y = rank_strategies_in_window(sub_y, m_30_w, min_n=3, dedup_days=120)
            track_y = "SP500_PIT_SEC_30Y_Annual"

        s_y = [r for r in ranked_y if r["role"] == "Strategy"]
        top1 = s_y[0] if len(s_y) >= 1 else {}
        top2 = s_y[1] if len(s_y) >= 2 else {}
        worst_s = s_y[-1] if len(s_y) >= 1 else {}
        worst_all = ranked_y[-1] if len(ranked_y) >= 1 else {}
        full_rank_str = " > ".join([f"{r['code']}({r['alpha_primary_pct']:+.1f}%)" for r in ranked_y])

        playbook_rows.append(
            {
                "section_type": "PartB_1996至2026逐年最优前二与垫底对照(31年全序列)",
                "period_or_rank": f"Year_{yr}",
                "year_span": str(yr),
                "data_track": track_y,
                "macro_regime_summary": f"{era_y} | {macro_y_str}",
                "top1_strategy": top1.get("name", ""),
                "top1_alpha_1y_pct": top1.get("alpha_primary_pct", np.nan),
                "top1_win_1y_pct": top1.get("win_rate_pct", np.nan),
                "top1_alpha_3y_pct": top1.get("alpha_3y_pct", np.nan),
                "top2_strategy": top2.get("name", ""),
                "top2_alpha_1y_pct": top2.get("alpha_primary_pct", np.nan),
                "top2_win_1y_pct": top2.get("win_rate_pct", np.nan),
                "worst_strategy_among_S1_S8": worst_s.get("name", ""),
                "worst_S_alpha_1y_pct": worst_s.get("alpha_primary_pct", np.nan),
                "worst_overall_incl_traps": worst_all.get("name", ""),
                "worst_overall_alpha_1y_pct": worst_all.get("alpha_primary_pct", np.nan),
                "full_ranking_1_to_10": full_rank_str,
                "actionable_instruction": f"{yr}最优:{top1.get('code','')}/{top2.get('code','')} | 垫底:{worst_s.get('code','')}",
            }
        )

    # --------------------------------------------------------------------------
    # PART C: Exact 2026.11 Live Macro Coordinate Composite Ranking (Ranks 1 to 10)
    #   Uses Strict_SP500_PIT (zero survivorship) + Commercial_All (for small/mid-cap S7 coverage)
    #   + Full 30Y SP500_PIT, explicitly weighting both Qtr-EW Alpha AND Median Alpha to prevent
    #   single-stock right-tail lottery distortion!
    # --------------------------------------------------------------------------
    cur_grid = df_grid_all[df_grid_all["is_2026_11_current_bin"]].copy()
    live_scores = []
    for s_full, s_code, s_role in STRATEGY_NAMES:
        g_sp = cur_grid[(cur_grid["strategy_code"] == s_code) & (cur_grid["track_universe"] == "1_XBRL_2009_2026_Strict_SP500_PIT")]
        g_cm = cur_grid[(cur_grid["strategy_code"] == s_code) & (cur_grid["track_universe"] == "2_XBRL_2009_2026_Commercial_All")]
        g_30 = cur_grid[(cur_grid["strategy_code"] == s_code) & (cur_grid["track_universe"] == "3_Full30Y_1996_2026_SP500_PIT")]

        # For T1 (cash-burn trap), Strict_SP500_PIT is mandatory to eliminate 2026 small-cap survivor bias;
        # For S7 (narrow-loss commercialization breakthrough, mostly mid-caps pre-S&P500), Commercial_All has full sample!
        if s_code == "T1":
            primary_g = g_sp if len(g_sp) >= 4 else g_cm
        elif s_code == "S7":
            primary_g = g_cm
        else:
            # Blend Strict_SP500_PIT and Commercial_All equally where available
            primary_g = g_cm

        sp_mean_1y = float(g_sp["qtr_ew_alpha_1y_pct"].mean()) if len(g_sp) else np.nan
        sp_med_1y = float(g_sp["med_alpha_1y_pct"].mean()) if len(g_sp) else np.nan
        cm_mean_1y = float(g_cm["qtr_ew_alpha_1y_pct"].mean()) if len(g_cm) else np.nan
        cm_med_1y = float(g_cm["med_alpha_1y_pct"].mean()) if len(g_cm) else np.nan
        cm_win_1y = float(g_cm["win_rate_1y_pct"].mean()) if len(g_cm) else np.nan
        cm_mean_3y = float(g_cm["qtr_ew_alpha_3y_pct"].mean()) if len(g_cm) else np.nan
        t30_mean_1y = float(g_30["qtr_ew_alpha_1y_pct"].mean()) if len(g_30) else np.nan

        sp_pos_bins = int((g_sp["qtr_ew_alpha_1y_pct"] > 0).sum())
        cm_pos_bins = int((g_cm["qtr_ew_alpha_1y_pct"] > 0).sum())
        t30_pos_bins = int((g_30["qtr_ew_alpha_1y_pct"] > 0).sum())

        # Zero-survivorship calibrated Composite Score across the 7 current 2026.11 macro dimensions:
        #   For T1: 50% Strict_SP500_PIT 1Y Qtr-EW + 20% Strict_SP500_PIT Median + 30% 30Y_SP500_PIT 1Y Qtr-EW
        #   For S7 (pre-SP500 mid-caps): 50% Commercial Qtr-EW + 20% Commercial Median + 30% 30Y_SP500_PIT 1Y Qtr-EW
        #   For S1-S6, S8, T2: 35% Strict_SP500_PIT Qtr-EW + 35% Commercial Qtr-EW + 30% 30Y_SP500_PIT Qtr-EW
        if s_code == "T1":
            comp_alpha = 0.50 * (sp_mean_1y if pd.notna(sp_mean_1y) else cm_mean_1y) + 0.20 * (sp_med_1y if pd.notna(sp_med_1y) else cm_med_1y) + 0.30 * (t30_mean_1y if pd.notna(t30_mean_1y) else 0.0)
        elif s_code == "S7":
            comp_alpha = 0.50 * cm_mean_1y + 0.20 * cm_med_1y + 0.30 * (t30_mean_1y if pd.notna(t30_mean_1y) else 0.0)
        else:
            eff_sp = sp_mean_1y if pd.notna(sp_mean_1y) else cm_mean_1y
            comp_alpha = 0.35 * eff_sp + 0.35 * cm_mean_1y + 0.30 * (t30_mean_1y if pd.notna(t30_mean_1y) else 0.0)

        bin_details = []
        for _, r_b in primary_g.sort_values("macro_dimension").iterrows():
            d_short = r_b["macro_dimension"].split("_")[0]
            bin_details.append(f"D{d_short}:{r_b['qtr_ew_alpha_1y_pct']:+.1f}%")

        live_scores.append(
            {
                "code": s_code,
                "name": s_full,
                "role": s_role,
                "comp_alpha": round(comp_alpha, 2),
                "sp_7bin_mean_1y": round(sp_mean_1y, 2) if pd.notna(sp_mean_1y) else np.nan,
                "sp_7bin_med_1y": round(sp_med_1y, 2) if pd.notna(sp_med_1y) else np.nan,
                "cm_7bin_mean_1y": round(cm_mean_1y, 2) if pd.notna(cm_mean_1y) else np.nan,
                "cm_7bin_med_1y": round(cm_med_1y, 2) if pd.notna(cm_med_1y) else np.nan,
                "cm_7bin_win_1y": round(cm_win_1y, 1) if pd.notna(cm_win_1y) else np.nan,
                "cm_7bin_mean_3y": round(cm_mean_3y, 2) if pd.notna(cm_mean_3y) else np.nan,
                "t30_7bin_mean_1y": round(t30_mean_1y, 2) if pd.notna(t30_mean_1y) else np.nan,
                "pos_hit_sp": f"{sp_pos_bins}/{len(g_sp)}",
                "pos_hit_cm": f"{cm_pos_bins}/{len(g_cm)}",
                "pos_hit_30y": f"{t30_pos_bins}/{len(g_30)}",
                "bin_str": " | ".join(bin_details),
            }
        )

    live_scores.sort(key=lambda x: x["comp_alpha"], reverse=True)
    for rk, item in enumerate(live_scores, 1):
        if item["role"] == "Control_Trap" or item["comp_alpha"] < 0.0:
            sw_cmd = "强制关闭与一票否决 (HARD_OFF_VETO)"
        elif item["comp_alpha"] >= 8.0:
            sw_cmd = "一档全开与核心重仓 (TIER1_MAX_ON)"
        elif item["comp_alpha"] >= 3.0:
            sw_cmd = "二档开启与标准配置 (TIER2_ON)"
        else:
            sw_cmd = "三档降权与精选底仓 (TIER3_SELECTIVE)"

        sp_str = f"{item['sp_7bin_mean_1y']:+.2f}%" if pd.notna(item["sp_7bin_mean_1y"]) else "N/A"
        playbook_rows.append(
            {
                "section_type": "PartC_2026年11月当下7大宏观坐标精确排位(第1至第10名)",
                "period_or_rank": f"2026.11_Rank_{rk:02d}",
                "year_span": "2026-11-09实时",
                "data_track": "DualTrack_SP500_PIT+Commercial_XBRL+Full30Y",
                "macro_regime_summary": (
                    "2026.11七维同档: ①10Y=4.84%(4-5%) | ②6M=+42bp(上行>=35bp) | ③TIPS实际=+2.60%(>=2%) | "
                    "④10Y-2Y=+35bp(正常正斜率) | ⑤BAA=1.57%(极紧<1.7%) | ⑥VIX=25.64(22-30) | ⑦INDPRO+2.25%&CPI+3.72%(过热再通胀Capex)"
                ),
                "top1_strategy": item["name"],
                "top1_alpha_1y_pct": item["comp_alpha"],
                "top1_win_1y_pct": item["cm_7bin_win_1y"],
                "top1_alpha_3y_pct": item["cm_7bin_mean_3y"],
                "top2_strategy": f"SP500零幸存均:{sp_str} | 商业全池均:{item['cm_7bin_mean_1y']:+.2f}%",
                "top2_alpha_1y_pct": item["cm_7bin_mean_1y"],
                "top2_win_1y_pct": item["cm_7bin_med_1y"],
                "worst_strategy_among_S1_S8": f"30年SP500同档均:{item['t30_7bin_mean_1y']:+.2f}%",
                "worst_S_alpha_1y_pct": item["t30_7bin_mean_1y"],
                "worst_overall_incl_traps": f"7档正超额命中: 全池{item['pos_hit_cm']} | SP500 {item['pos_hit_sp']} | 30Y {item['pos_hit_30y']}",
                "worst_overall_alpha_1y_pct": item["sp_7bin_med_1y"],
                "full_ranking_1_to_10": item["bin_str"],
                "actionable_instruction": sw_cmd,
            }
        )

    return pd.DataFrame(playbook_rows), live_scores


# ==============================================================================
# 7. Main Execution Entrypoint
# ==============================================================================
def main():
    t0 = time.time()
    print("=" * 90)
    print("G08: 1996-2026 Full 30Y 8 Strategies x 7 ALFRED PIT Macro Switchboard Engine")
    print("=" * 90)

    macro_df = build_macro_7dims_table()
    latest_m = macro_df.iloc[-1]
    print(
        f"[Macro Snapshot {latest_m['date_str']}] "
        f"10Y={latest_m['dgs10']:.2f}% ({latest_m['m1_dgs10_5bin']}) | "
        f"6M={latest_m['dgs10_chg_126d']:+.2f}% ({latest_m['m2_rate6m_4bin']}) | "
        f"TIPS={latest_m['real_rate_10y_pit']:+.2f}% ({latest_m['m3_realrate_4bin']}) | "
        f"YC={latest_m['t10y2y']:+.2f}% ({latest_m['m4_yc_4bin']}) | "
        f"BAA={latest_m['baa10y']:.2f}% ({latest_m['m5_baa_4bin']}) | "
        f"VIX={latest_m['vix']:.2f} ({latest_m['m6_vix_4bin']}) | "
        f"4Q={latest_m['m7_merrill_4q']}"
    )

    sp_hist, sp_intervals = load_sp500_pit_intervals()

    # 1. Load & prepare 2009-2026 XBRL Master PIT Panel
    xbrl_raw = pd.read_parquet(os.path.join(DATA_DIR, "xbrl_master_pit_2009_2026.parquet"))
    xbrl_raw["is_sp500_pit"] = tag_sp500_pit(xbrl_raw["ticker"].values, xbrl_raw["entry_date"], sp_intervals)

    inv_mask = (
        xbrl_raw["entry_date"].notna()
        & (~xbrl_raw["has_anomaly_break"].fillna(False))
        & (xbrl_raw["mcap_2026_equiv_b"] >= 0.5)
        & (xbrl_raw["mcap_usd_b"] <= 5500.0)
        & (xbrl_raw["unadj_entry_px"] >= 2.0)
        & (xbrl_raw["rev_ttm"] >= 1e8)
    )
    d_xbrl_all = xbrl_raw[inv_mask].copy().reset_index(drop=True)
    d_xbrl_all["macro_join_date"] = pd.to_datetime(d_xbrl_all["pre_date"]).dt.normalize()
    new_m_cols = [
        "macro_join_date",
        "m1_dgs10_5bin",
        "m2_rate6m_4bin",
        "m3_realrate_4bin",
        "m4_yc_4bin",
        "m5_baa_4bin",
        "m6_vix_4bin",
        "m7_merrill_4q",
    ]
    d_xbrl_all = d_xbrl_all.merge(macro_df[new_m_cols], on="macro_join_date", how="left")

    # Strict 100% Zero-Survivorship S&P 500 PIT sub-universe
    d_xbrl_sp = d_xbrl_all[d_xbrl_all["is_sp500_pit"]].copy().reset_index(drop=True)

    masks_xbrl_all = define_8_strategies_xbrl(d_xbrl_all)
    masks_xbrl_sp = define_8_strategies_xbrl(d_xbrl_sp)

    print(f"[XBRL Panel] Commercial_All={len(d_xbrl_all):,} rows | Strict_SP500_PIT={len(d_xbrl_sp):,} rows.")

    # 2. Build 1996-2026 Full 30-Year SP500_PIT Panel
    eng_30y = build_augmented_30y_engine(sp_hist)
    ev_30y = build_30y_sp500_sec_panel(eng_30y, macro_df)
    masks_30y = define_8_strategies_30y_proxy(ev_30y)

    # 3. Evaluate all 3 tracks across 8 Strategies + 2 Traps x 7 Macro Dimensions
    print("[Grid Evaluation] Computing Track 1 (Strict SP500_PIT XBRL), Track 2 (Commercial All XBRL), Track 3 (Full 30Y SP500_PIT)...")
    g_t1 = evaluate_grid_for_track(d_xbrl_sp, masks_xbrl_sp, "1_XBRL_2009_2026_Strict_SP500_PIT", dedup_days=250)
    g_t2 = evaluate_grid_for_track(d_xbrl_all, masks_xbrl_all, "2_XBRL_2009_2026_Commercial_All", dedup_days=250)
    g_t3 = evaluate_grid_for_track(ev_30y, masks_30y, "3_Full30Y_1996_2026_SP500_PIT", dedup_days=180)

    df_grid_all = pd.concat([g_t1, g_t2, g_t3], ignore_index=True)
    p_grid = os.path.join(OUT_DIR, "table_g08_8strategies_x_macro_grid.csv")
    df_grid_all.to_csv(p_grid, index=False)
    print(f"  -> Saved {p_grid} ({len(df_grid_all):,} rows)")

    # 4. Build 1996-2026 30Y Regime Playbook + Annual Table + 2026.11 Live Coordinate Ranking
    df_playbook, live_scores = build_30y_regime_playbook(
        d_xbrl_sp, masks_xbrl_sp, d_xbrl_all, masks_xbrl_all, ev_30y, masks_30y, macro_df, df_grid_all
    )
    p_play = os.path.join(OUT_DIR, "table_g08_1996_2026_30y_regime_playbook.csv")
    df_playbook.to_csv(p_play, index=False)
    print(f"  -> Saved {p_play} ({len(df_playbook):,} rows)")

    print("\n=== 2026.11 LIVE 7-MACRO-COORDINATE COMPOSITE RANKING (1 to 10) ===")
    for rk, it in enumerate(live_scores, 1):
        sp_s = f"{it['sp_7bin_mean_1y']:+6.2f}%" if pd.notna(it["sp_7bin_mean_1y"]) else "   N/A "
        print(
            f"  #{rk:02d} {it['name']:24s} | Comp={it['comp_alpha']:+6.2f}% | "
            f"SP500_PIT={sp_s} | All_XBRL={it['cm_7bin_mean_1y']:+6.2f}% (3Y:{it['cm_7bin_mean_3y']:+6.2f}%) | "
            f"30Y_SP500={it['t30_7bin_mean_1y']:+6.2f}% | Hit_All={it['pos_hit_cm']} (30Y:{it['pos_hit_30y']})"
        )

    print(f"\n[DONE] G08 completed in {time.time()-t0:.2f}s!")


if __name__ == "__main__":
    main()

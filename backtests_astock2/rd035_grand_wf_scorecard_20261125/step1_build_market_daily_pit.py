#!/opt/homebrew/bin/python3.13
"""RD035 Wave 1-A Step 1: Build strictly PIT (T-1 / pre-09:25) Market Daily Feature Library.

Outputs (under wave1_base/):
  - market_daily_all_new_factors_pit.parquet
  - _audit_step1_market.json
"""
import gc
import json
import os
import sys
import time
import warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

ROOT = "/Users/huaichuaibeimeng/claude-projects"
OUT_DIR = os.path.join(
    ROOT, "sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
)
os.makedirs(OUT_DIR, exist_ok=True)

sys.path.insert(0, os.path.join(ROOT, "sim-portfolio/backtests_astock2/china_policy_macro_rd027"))
from rd029_engine import score_v3_causal


def _load_st_set():
    p = os.path.join(ROOT, "sim-portfolio/data/st_universe.json")
    with open(p) as f:
        d = json.load(f)
    codes = d.get("codes", d) if isinstance(d, dict) else d
    return set(str(x)[-6:] for x in codes)


def _norm_dt_col(s) -> pd.Series:
    return pd.Series(pd.to_datetime(s)).dt.strftime("%Y-%m-%d")


def _compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    diff = series.diff()
    gain = diff.clip(lower=0.0)
    loss = (-diff).clip(lower=0.0)
    avg_g = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_l = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_g / avg_l.replace(0.0, np.nan)
    return 100.0 - 100.0 / (1.0 + rs)


def _compute_causal_pct(arr: np.ndarray, win: int = 250, min_p: int = 60) -> np.ndarray:
    n = len(arr)
    out = np.full(n, np.nan, dtype=np.float64)
    for i in range(n):
        if not np.isfinite(arr[i]):
            continue
        start = max(0, i - win + 1)
        w = arr[start : i + 1]
        w = w[np.isfinite(w)]
        if len(w) >= min_p:
            out[i] = float(np.mean(w <= arr[i]))
    return out


def build_market_daily(end_cutoff: str = "2026-11-25", start_out: str = "2021-01-04"):
    t0 = time.time()
    print(f"[Step1] Building market_daily PIT up to {end_cutoff} ...")

    # 1. RD034 Layer-1 (33 strictly T-1 / calendar cols)
    rd34_path = os.path.join(
        ROOT, "sim-portfolio/backtests_astock2/rd034_ashare_3layer_cycles_6strat_20261125/rd034_market_daily_pit.parquet"
    )
    l1 = pd.read_parquet(rd34_path)
    l1["trade_date"] = l1["dt"].astype(str).str[:10]
    l1 = l1[l1["trade_date"] <= end_cutoff].sort_values("trade_date").reset_index(drop=True)
    l1_cols = [c for c in l1.columns if c.startswith("L1_")]
    l1 = l1[["trade_date"] + l1_cols].copy()

    # Master trading calendar (from 2019-10-01..end_cutoff for warmup, output >= start_out)
    dmp_path = os.path.join(
        ROOT, "output/china_policy_macro_rd027_20261125/rd029_daybyday_etf/cache/daily_market_panel_2000_20261125.parquet"
    )
    dmp = pd.read_parquet(dmp_path)
    dmp["trade_date"] = _norm_dt_col(dmp["date"])
    dmp = dmp[dmp["trade_date"] <= end_cutoff].sort_values("trade_date").reset_index(drop=True)

    full_cal = dmp["trade_date"].values  # 2000-01-04 .. end_cutoff
    out_dates = l1.loc[l1["trade_date"] >= start_out, "trade_date"].values
    base = pd.DataFrame({"trade_date": out_dates})
    base = base.merge(l1, on="trade_date", how="left")

    # 2. A-share stock bars: T-1 micro breadth, 09:25 live auction breadth, & 15Y causal style pulses
    st_set = _norm_st = _load_st_set()
    cols_bar = ["date", "ticker", "open", "high", "low", "close", "adj_close", "amount", "oshare"]
    df_a = pd.read_parquet(os.path.join(ROOT, "sim-portfolio/data/cn_hk_price_db/a_daily.parquet"), columns=cols_bar)
    df_d = pd.read_parquet(os.path.join(ROOT, "sim-portfolio/data/cn_hk_price_db/a_delisted_daily.parquet"), columns=cols_bar)
    bars = pd.concat([df_a, df_d], ignore_index=True)
    del df_a, df_d
    gc.collect()

    bars["dt"] = _norm_dt_col(bars["date"])
    bars = bars[(bars["dt"] >= "2020-01-01") & (bars["dt"] <= end_cutoff)].copy()
    bars["c6"] = bars["ticker"].astype(str).str[:6]
    suf = bars["ticker"].astype(str).str[-3:]
    valid_pref = bars["c6"].str.startswith(("00", "60", "30", "688", "689"))
    bars = bars[valid_pref & suf.isin([".SH", ".SZ"]) & (bars["close"] > 0) & (bars["adj_close"] > 0)].copy()
    bars = bars.sort_values(["ticker", "dt"]).drop_duplicates(subset=["ticker", "dt"], keep="first").reset_index(drop=True)

    # Causal prev bar within ticker
    g = bars.groupby("ticker", sort=False)
    prev_adj = g["adj_close"].shift(1)
    prev_close_raw = prev_adj * (bars["close"] / bars["adj_close"])
    prev_amt = g["amount"].shift(1)
    prev_oshare = g["oshare"].shift(1)
    bars["ret_1d"] = bars["adj_close"] / prev_adj - 1.0
    bars["open_pct"] = bars["open"] / prev_close_raw - 1.0
    bars["oc_ret"] = bars["close"] / bars["open"] - 1.0
    bars["ret_20d"] = bars["adj_close"] / g["adj_close"].shift(20) - 1.0
    bars["ret_60d"] = bars["adj_close"] / g["adj_close"].shift(60) - 1.0
    bars["prev_ret_20d"] = g["ret_20d"].shift(1)
    bars["prev_ret_60d"] = g["ret_60d"].shift(1)
    bars["prev_mcap"] = prev_close_raw * prev_oshare
    bars["prev_amt"] = prev_amt

    # Limit up / down classification (using exact board & ST limit rule pre/post 2026-07-06)
    is_20cm = bars["c6"].str.startswith(("30", "688", "689"))
    is_st = bars["c6"].isin(st_set)
    lim = np.where(is_20cm, 0.20, np.where(is_st & (bars["dt"] < "2026-07-06"), 0.05, 0.10))
    zt_px = np.round(prev_close_raw * (1.0 + lim), 2)
    dt_px = np.round(prev_close_raw * (1.0 - lim), 2)

    valid_prev = prev_close_raw.notna() & (prev_close_raw > 0)
    non_st = ~is_st
    bars["is_zt"] = valid_prev & non_st & (bars["close"] >= zt_px - 1e-4) & (bars["close"] >= bars["high"] - 1e-4)
    bars["hit_zt"] = valid_prev & non_st & (bars["high"] >= zt_px - 1e-4)
    bars["is_broken_zt"] = bars["hit_zt"] & (~bars["is_zt"])
    bars["is_yizi_zt"] = bars["is_zt"] & (bars["open"] >= zt_px - 1e-4) & (bars["low"] >= zt_px - 1e-4)
    bars["is_dt"] = valid_prev & non_st & (bars["close"] <= dt_px + 1e-4) & (bars["close"] <= bars["low"] + 1e-4)
    bars["open_zt"] = valid_prev & non_st & (bars["open"] >= zt_px - 1e-4)
    bars["open_dt"] = valid_prev & non_st & (bars["open"] <= dt_px + 1e-4)
    bars["is_20cm"] = is_20cm & non_st

    # Streak & yesterday first-board clean
    # Causal consecutive ZT count via numpy over sorted ticker-dt
    tkr_vals = bars["ticker"].values
    zt_vals = bars["is_zt"].values
    streak = np.zeros(len(bars), dtype=np.int16)
    cur_s = 0
    prev_t = ""
    for idx in range(len(bars)):
        tk = tkr_vals[idx]
        if tk != prev_t:
            cur_s = 0
            prev_t = tk
        if zt_vals[idx]:
            cur_s += 1
        else:
            cur_s = 0
        streak[idx] = cur_s
    bars["streak"] = streak
    g2 = bars.groupby("ticker", sort=False)
    bars["prev_zt"] = g2["is_zt"].shift(1).fillna(False).astype(bool)
    bars["prev_streak"] = g2["streak"].shift(1).fillna(0).astype(np.int16)

    # Daily T-bar aggregations (shifted by 1 for EOD metrics, unshifted for 09:25 live metrics)
    eod_rows = []
    style_rows = []
    for dt_val, grp in bars.groupby("dt", sort=True):
        if dt_val < "2020-11-01":
            continue
        v_nonst = grp[grp["prev_amt"].notna() & (~grp["c6"].isin(st_set))]
        n_act = len(v_nonst)
        zt20 = int((v_nonst["is_20cm"] & v_nonst["is_zt"]).sum())
        dt20 = int((v_nonst["is_20cm"] & v_nonst["is_dt"]).sum())
        b3p = int((v_nonst["streak"] >= 3).sum())
        yizi_cnt = int(v_nonst["is_yizi_zt"].sum())
        amt_tril = float(grp["amount"].sum() / 1e12)

        brk = v_nonst[v_nonst["is_broken_zt"]]
        brk_avg_ret = float(brk["ret_1d"].mean() * 100.0) if len(brk) > 0 else 0.0

        pzt = v_nonst[v_nonst["prev_zt"] & v_nonst["oc_ret"].notna()]
        zt_next_oc = float(pzt["oc_ret"].mean() * 100.0) if len(pzt) > 0 else 0.0

        # 09:25 auction features (strictly T 09:25)
        o_zt = int(v_nonst["open_zt"].sum())
        o_dt = int(v_nonst["open_dt"].sum())
        o20_zt = int((v_nonst["is_20cm"] & v_nonst["open_zt"]).sum())
        o_gap = float(v_nonst["open_pct"].clip(-0.25, 0.25).mean() * 100.0) if n_act > 0 else 0.0
        fb20_deep = int(
            (v_nonst["is_20cm"] & (v_nonst["prev_streak"] == 1) & (v_nonst["open_pct"] <= -0.03)).sum()
        )

        eod_rows.append(
            {
                "dt": dt_val,
                "mkt20_zt_cnt": zt20,
                "mkt20_dt_cnt": dt20,
                "mkt_b3plus_cnt": b3p,
                "mkt_yizi_zt_cnt": yizi_cnt,
                "mkt_amt_tril": amt_tril,
                "mkt_broken_avg_ret": brk_avg_ret,
                "mkt_zt_next_oc": zt_next_oc,
                "mkt_0925_zt_cnt": o_zt,
                "mkt_0925_dt_cnt": o_dt,
                "mkt20_0925_zt_cnt": o20_zt,
                "mkt_0925_avg_gap_pct": o_gap,
                "mkt_0925_fb20_deepopen_cnt": fb20_deep,
            }
        )

        # 15Y style daily factor pulses (purely causal t-1 cross-sectional sort -> day t return)
        sv = grp[
            grp["ret_1d"].notna()
            & grp["prev_mcap"].gt(0)
            & grp["prev_amt"].gt(0)
            & grp["prev_ret_20d"].notna()
            & grp["prev_ret_60d"].notna()
        ]
        if len(sv) >= 500:
            q20_m, q80_m = np.nanpercentile(sv["prev_mcap"].values, [20, 80])
            sh_ret = float(sv.loc[sv["prev_mcap"] <= q20_m, "ret_1d"].mean() - sv.loc[sv["prev_mcap"] >= q80_m, "ret_1d"].mean())
            q20_r20, q80_r20 = np.nanpercentile(sv["prev_ret_20d"].values, [20, 80])
            rev_ret = float(sv.loc[sv["prev_ret_20d"] <= q20_r20, "ret_1d"].mean() - sv.loc[sv["prev_ret_20d"] >= q80_r20, "ret_1d"].mean())
            q20_r60, q80_r60 = np.nanpercentile(sv["prev_ret_60d"].values, [20, 80])
            mom_ret = float(sv.loc[sv["prev_ret_60d"] >= q80_r60, "ret_1d"].mean() - sv.loc[sv["prev_ret_60d"] <= q20_r60, "ret_1d"].mean())
        else:
            sh_ret = rev_ret = mom_ret = 0.0
        style_rows.append({"dt": dt_val, "sh_1d": sh_ret, "rev_1d": rev_ret, "mom_1d": mom_ret})

    del bars
    gc.collect()

    df_eod = pd.DataFrame(eod_rows).sort_values("dt").reset_index(drop=True)
    # Shift T-bar EOD features by 1 so row T contains T-1 close metrics
    t1_shift_cols = [
        "mkt20_zt_cnt",
        "mkt20_dt_cnt",
        "mkt_b3plus_cnt",
        "mkt_yizi_zt_cnt",
        "mkt_amt_tril",
        "mkt_broken_avg_ret",
        "mkt_zt_next_oc",
    ]
    for c in t1_shift_cols:
        df_eod[f"{c}_t1"] = df_eod[c].shift(1)
    keep_eod = ["dt"] + [f"{c}_t1" for c in t1_shift_cols] + [
        "mkt_0925_zt_cnt",
        "mkt_0925_dt_cnt",
        "mkt20_0925_zt_cnt",
        "mkt_0925_avg_gap_pct",
        "mkt_0925_fb20_deepopen_cnt",
    ]
    base = base.merge(df_eod[keep_eod], left_on="trade_date", right_on="dt", how="left").drop(columns=["dt"])

    # Style 20d cumulative factor spreads shifted by 1
    df_sty = pd.DataFrame(style_rows).sort_values("dt").reset_index(drop=True)
    df_sty["th_style_shell_spread_20d_t1"] = df_sty["sh_1d"].rolling(20, min_periods=10).sum().shift(1) * 100.0
    df_sty["th_style_rev_20d_spread_t1"] = df_sty["rev_1d"].rolling(20, min_periods=10).sum().shift(1) * 100.0
    df_sty["th_style_mom_60d_spread_t1"] = df_sty["mom_1d"].rolling(20, min_periods=10).sum().shift(1) * 100.0
    base = base.merge(
        df_sty[["dt", "th_style_shell_spread_20d_t1", "th_style_rev_20d_spread_t1", "th_style_mom_60d_spread_t1"]],
        left_on="trade_date",
        right_on="dt",
        how="left",
    ).drop(columns=["dt"])

    # 3. Daily Market Panel (Bank vs Tech, Index returns, Notices, Tech indicators: CSI300 MA20/60, RSI14, MACD, 40m Cycle)
    dmp["mkt_bank_vs_tech_ret_t1"] = (dmp["bank_idx_cc_ret"] - dmp["tmt_info_cc_ret"]).shift(1) * 100.0
    dmp["mkt_csi300_ret1d_t1"] = dmp["csi300_cc_ret"].shift(1) * 100.0
    dmp["mkt_csi1000_ret1d_t1"] = dmp["csi1000_cc_ret"].shift(1) * 100.0
    # Regulatory/severe abnormal notice 5d count strictly T-1 from pit_reg_tox_notices + cninfo (avoid sparse NaN in dmp)
    tox = pd.read_parquet(os.path.join(ROOT, "sim-portfolio/data/pit_reg_tox_notices_5y_complete.parquet"), columns=["pub_datetime_cst", "title"])
    tox["pub_dt"] = tox["pub_datetime_cst"].astype(str).str[:10]
    tox = tox[tox["pub_dt"] <= end_cutoff].copy()
    tox["is_sev"] = tox["title"].astype(str).str.contains("严重异常波动|风险提示|立案|监管", regex=True).astype(np.float32)
    tox_day = tox.groupby("pub_dt", as_index=False)["is_sev"].sum().rename(columns={"pub_dt": "trade_date", "is_sev": "tox_sev_cnt"})
    dmp = dmp.merge(tox_day, on="trade_date", how="left")
    dmp["tox_sev_cnt"] = dmp["tox_sev_cnt"].fillna(0.0)
    dmp["mkt_notices_sev_abn_5d_t1"] = dmp["tox_sev_cnt"].rolling(5, min_periods=1).sum().shift(1)

    c300 = dmp["csi300_close"].astype(float)
    ma20 = c300.rolling(20, min_periods=20).mean()
    ma60 = c300.rolling(60, min_periods=60).mean()
    dmp["th_tech_csi300_ma20_dist_t1"] = ((c300 / ma20 - 1.0) * 100.0).shift(1)
    dmp["th_tech_csi300_ma20_60_spread_t1"] = ((ma20 / ma60 - 1.0) * 100.0).shift(1)
    dmp["th_tech_csi300_rsi14_t1"] = _compute_rsi(c300, 14).shift(1)
    ema12 = c300.ewm(span=12, adjust=False).mean()
    ema26 = c300.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    dmp["th_tech_chan_macd_hist_t1"] = ((dif - dea) * 2.0 / c300 * 100.0).shift(1)

    # 40-month (~820 trading days) cycle anchored at 2008-11-04, shifted by 1
    anchor_pos = int(np.searchsorted(full_cal, "2008-11-04"))
    idx_arr = np.arange(len(dmp), dtype=np.float64) - 1.0  # t-1 trading index
    dmp["th_macro_40m_cycle_sin_t1"] = np.sin(2.0 * np.pi * (idx_arr - anchor_pos) / 820.0)
    dmp["th_macro_40m_cycle_cos_t1"] = np.cos(2.0 * np.pi * (idx_arr - anchor_pos) / 820.0)

    dmp_keep = [
        "trade_date",
        "mkt_bank_vs_tech_ret_t1",
        "mkt_csi300_ret1d_t1",
        "mkt_csi1000_ret1d_t1",
        "mkt_notices_sev_abn_5d_t1",
        "th_tech_csi300_ma20_dist_t1",
        "th_tech_csi300_ma20_60_spread_t1",
        "th_tech_csi300_rsi14_t1",
        "th_tech_chan_macd_hist_t1",
        "th_macro_40m_cycle_sin_t1",
        "th_macro_40m_cycle_cos_t1",
    ]
    base = base.merge(dmp[dmp_keep], on="trade_date", how="left")

    # Calendar theory regime (deterministic pre-known from trade_date month)
    m_num = pd.to_datetime(base["trade_date"]).dt.month
    base["th_tech_calendar_regime"] = np.where(m_num.isin([2, 3, 4]), 1.0, np.where(m_num.isin([5, 6]), -1.0, 0.0))

    # 4. Breadth, Valuation, Margin & Flow (from breadth_daily_2005_20261125, strictly shift(1))
    bp = pd.read_parquet(
        os.path.join(ROOT, "output/china_policy_macro_rd027_20261125/rd029_daybyday_etf/cache/breadth_daily_2005_20261125.parquet")
    )
    bp["trade_date"] = _norm_dt_col(bp["date"])
    bp = bp[bp["trade_date"] <= end_cutoff].sort_values("trade_date").reset_index(drop=True)
    bp_map = {
        "pct_above_ma20": "mkt_pct_above_ma20_t1",
        "pct_above_ma60": "mkt_pct_above_ma60_t1",
        "pct_above_ma200": "mkt_pct_above_ma200_t1",
        "pct_new_high_250d": "mkt_pct_newhigh_250d_t1",
        "pct_new_low_250d": "mkt_pct_newlow_250d_t1",
        "turn_median": "mkt_turn_median_t1",
        "turn_pct_3y": "mkt_turn_pct_3y_t1",
        "amount_pct_3y": "mkt_amt_pct_3y_t1",
        "all_a_median_pe_ttm": "mkt_all_a_median_pe_t1",
        "erp_csi300_pct": "mkt_erp_csi300_pct_t1",
        "erp_csi300_pct_5y": "mkt_erp_csi300_pct_5y_t1",
        "margin_to_float_mcap_pct": "mkt_margin_to_float_pct_t1",
    }
    for src_c, dst_c in bp_map.items():
        bp[dst_c] = bp[src_c].shift(1)
    # Causal ERP regime (750d rolling percentile of erp_csi300_pct, shifted 1)
    bp["th_macro_erp_pct750_t1"] = pd.Series(
        _compute_causal_pct(bp["erp_csi300_pct"].values, win=750, min_p=250)
    ).shift(1)
    base = base.merge(bp[["trade_date"] + list(bp_map.values()) + ["th_macro_erp_pct750_t1"]], on="trade_date", how="left")

    # Ice point composite (from L1 + breadth strictly T-1)
    base["th_style_ice_point_sig_t1"] = (
        (base["L1_zt_pct60_t1"] <= 0.20) & (base["L1_ew_bias20_t1"] <= -0.03)
    ).astype(np.float32)

    # 5. National Team V3.0 + NT Mantra (from score_v3_causal + v3_raw_panel, strictly shift(1))
    v3_raw = pd.read_parquet(
        os.path.join(ROOT, "output/china_policy_macro_rd027_20261125/rd029_daybyday_etf/cache/v3_raw_panel_2016_20261125.parquet")
    )
    nt_raw = json.load(open(os.path.join(ROOT, "output/csrc_policy_100factors_20261114/national_team/nt_official_events.json")))
    nt_ev = pd.DataFrame(nt_raw["events"] if isinstance(nt_raw, dict) and "events" in nt_raw else nt_raw)
    v3_sc = score_v3_causal(v3_raw, nt_ev, cutoff_date=end_cutoff)
    v3_sc["trade_date"] = v3_sc["date"].astype(str).str[:10]

    v3_raw_c = v3_raw.drop(columns=[c for c in ["etf22_wflow_yi"] if c in v3_raw.columns]).copy()
    v3_raw_c["trade_date"] = _norm_dt_col(v3_raw_c["date"])
    v3_raw_c = v3_raw_c[v3_raw_c["trade_date"] <= end_cutoff].sort_values("trade_date").reset_index(drop=True)
    v3_raw_c = v3_raw_c.merge(
        v3_sc[["trade_date", "v3_score_live", "v3_score_eod", "etf22_amt_spike", "core10_amt_spike", "etf22_wflow_yi"]],
        on="trade_date",
        how="left",
    )
    v3_raw_c["nt_v3_score_live_t1"] = v3_raw_c["v3_score_live"].shift(1)
    v3_raw_c["nt_v3_score_eod_t1"] = v3_raw_c["v3_score_eod"].shift(1)
    v3_raw_c["nt_etf22_amt_spike_t1"] = v3_raw_c["etf22_amt_spike"].shift(1)
    v3_raw_c["nt_core10_amt_spike_t1"] = v3_raw_c["core10_amt_spike"].shift(1)
    v3_raw_c["nt_etf22_wflow_yi_t1"] = v3_raw_c["etf22_wflow_yi"].shift(1)
    v3_raw_c["nt_if0_basis_pct_t1"] = ((v3_raw_c["IF0_close"] / v3_raw_c["c300_close"] - 1.0) * 100.0).shift(1)
    if0_med20 = v3_raw_c["IF0_vol"].rolling(20, min_periods=10).median().shift(1)
    v3_raw_c["nt_if0_vol_spike20_t1"] = (v3_raw_c["IF0_vol"] / if0_med20.replace(0, np.nan)).shift(1)
    v3_raw_c["nt_hw16_sync_cnt_t1"] = v3_raw_c["hw16_sync_cnt"].shift(1)
    v3_raw_c["nt_big4_oil_ret_t1"] = (v3_raw_c["big4_oil_ret"] * 100.0).shift(1)
    v3_raw_c["nt_fund8_dump_cnt_t1"] = v3_raw_c["fund8_dump_cnt"].shift(1)

    nt_cols = [
        "nt_v3_score_live_t1",
        "nt_v3_score_eod_t1",
        "nt_etf22_amt_spike_t1",
        "nt_core10_amt_spike_t1",
        "nt_etf22_wflow_yi_t1",
        "nt_if0_basis_pct_t1",
        "nt_if0_vol_spike20_t1",
        "nt_hw16_sync_cnt_t1",
        "nt_big4_oil_ret_t1",
        "nt_fund8_dump_cnt_t1",
    ]
    base = base.merge(v3_raw_c[["trade_date"] + nt_cols], on="trade_date", how="left")

    # 6. US Overnight Benchmarks (strictly us_date < trade_date, i.e., < end_cutoff)
    us_dir = os.path.join(ROOT, "sim-portfolio/data/us_price_db/benchmarks")
    us_dict = {}
    for sym in ["IXIC", "GSPC", "RUT", "VIX", "TNX", "DX-Y_NYB"]:
        df_u = pd.read_parquet(os.path.join(us_dir, f"{sym}.parquet"))
        u_dt = _norm_dt_col(df_u["date"] if "date" in df_u.columns else df_u.index)
        u_s = pd.DataFrame({"us_dt": u_dt.values, "close": df_u["close"].values})
        u_s = u_s[u_s["us_dt"] < end_cutoff].drop_duplicates("us_dt").sort_values("us_dt").reset_index(drop=True)
        us_dict[sym] = u_s

    ix = us_dict["IXIC"].copy()
    ix["us_ixic_ret1d_on"] = ix["close"].pct_change(1) * 100.0
    ix["us_ixic_ret5d_on"] = ix["close"].pct_change(5) * 100.0

    gs = us_dict["GSPC"].copy()
    gs["us_gspc_ret1d_on"] = gs["close"].pct_change(1) * 100.0
    gs["gspc_ret5"] = gs["close"].pct_change(5) * 100.0

    ru = us_dict["RUT"].copy()
    ru["us_rut_ret1d_on"] = ru["close"].pct_change(1) * 100.0
    ru["rut_ret5"] = ru["close"].pct_change(5) * 100.0

    vx = us_dict["VIX"].copy()
    vx["us_vix_level_on"] = vx["close"]
    vx["us_vix_chg1d_on"] = vx["close"].diff(1)
    vx["us_vix_pct250_on"] = _compute_causal_pct(vx["close"].values, win=250, min_p=60)

    tnx = us_dict["TNX"].copy()
    tnx["us_tnx_chg5d_on"] = tnx["close"].diff(5) * 100.0  # yield in % -> change in bps

    dxy = us_dict["DX-Y_NYB"].copy()
    dxy["us_dxy_ret5d_on"] = dxy["close"].pct_change(5) * 100.0

    us_merged = (
        ix[["us_dt", "us_ixic_ret1d_on", "us_ixic_ret5d_on"]]
        .merge(gs[["us_dt", "us_gspc_ret1d_on", "gspc_ret5"]], on="us_dt", how="outer")
        .merge(ru[["us_dt", "us_rut_ret1d_on", "rut_ret5"]], on="us_dt", how="outer")
        .merge(vx[["us_dt", "us_vix_level_on", "us_vix_chg1d_on", "us_vix_pct250_on"]], on="us_dt", how="outer")
        .merge(tnx[["us_dt", "us_tnx_chg5d_on"]], on="us_dt", how="outer")
        .merge(dxy[["us_dt", "us_dxy_ret5d_on"]], on="us_dt", how="outer")
        .sort_values("us_dt")
        .ffill()
        .reset_index(drop=True)
    )
    us_merged["us_rut_vs_gspc_5d_on"] = us_merged["rut_ret5"] - us_merged["gspc_ret5"]
    us_merged["us_dt_ts"] = pd.to_datetime(us_merged["us_dt"])
    base["trade_ts"] = pd.to_datetime(base["trade_date"])

    us_cols = [
        "us_ixic_ret1d_on",
        "us_ixic_ret5d_on",
        "us_gspc_ret1d_on",
        "us_rut_ret1d_on",
        "us_rut_vs_gspc_5d_on",
        "us_vix_level_on",
        "us_vix_chg1d_on",
        "us_vix_pct250_on",
        "us_tnx_chg5d_on",
        "us_dxy_ret5d_on",
    ]
    base = pd.merge_asof(
        base.sort_values("trade_ts"),
        us_merged[["us_dt_ts"] + us_cols].sort_values("us_dt_ts"),
        left_on="trade_ts",
        right_on="us_dt_ts",
        direction="backward",
        allow_exact_matches=False,
    ).drop(columns=["us_dt_ts"])

    # 7. Cross-Market Commodities & Extreme Counts (strictly comm_dt < trade_date, < end_cutoff)
    comm_dir = os.path.join(ROOT, "sim-portfolio/output/extreme_commodities_3ring_backtest_20261125/data_cache")
    cf = pd.read_parquet(os.path.join(comm_dir, "cn_futures_close.parquet"))
    gf = pd.read_parquet(os.path.join(comm_dir, "global_futures_close.parquet"))
    bdi = pd.read_parquet(os.path.join(comm_dir, "bdi.parquet"))
    for df_c in (cf, gf, bdi):
        df_c.index = pd.to_datetime(df_c.index).strftime("%Y-%m-%d")

    cf = cf[cf.index < end_cutoff].sort_index()
    gf = gf[gf.index < end_cutoff].sort_index()
    bdi = bdi[bdi.index < end_cutoff].sort_index()

    # Specific benchmark commodity returns (strictly < trade_date)
    comm_feat = pd.DataFrame(index=sorted(set(cf.index) | set(gf.index) | set(bdi.index)))
    comm_feat.index.name = "comm_dt"
    gf_ff = gf.reindex(comm_feat.index).ffill()
    cf_ff = cf.reindex(comm_feat.index).ffill()
    bdi_ff = bdi.reindex(comm_feat.index).ffill()

    comm_feat["comm_au_ret5d_t1"] = gf_ff["GC_F"].pct_change(5) * 100.0
    comm_feat["comm_cu_ret5d_t1"] = gf_ff["HG_F"].pct_change(5) * 100.0
    comm_feat["comm_wti_ret5d_t1"] = gf_ff["CL_F"].pct_change(5) * 100.0
    comm_feat["comm_rb_ret5d_t1"] = cf_ff["RB0"].pct_change(5) * 100.0
    comm_feat["comm_al_ret5d_t1"] = cf_ff["AL0"].pct_change(5) * 100.0
    cu_au = gf_ff["HG_F"] / gf_ff["GC_F"].replace(0, np.nan)
    comm_feat["comm_cu_au_ratio_ret20_t1"] = cu_au.pct_change(20) * 100.0
    comm_feat["comm_bdi_ret20_t1"] = bdi_ff["BDI"].pct_change(20) * 100.0
    comm_feat["comm_cn_ew_ret5d_t1"] = cf_ff.pct_change(5).mean(axis=1) * 100.0

    # Causal 5Y (1260d) extreme high (>=95%) / low (<=5%) counts across 83 CN+Global commodities
    all_comm = pd.concat([cf, gf], axis=1).sort_index()
    all_comm_recent = all_comm[all_comm.index >= "2014-01-01"].copy()
    hi_cnt = np.zeros(len(all_comm_recent), dtype=np.float32)
    lo_cnt = np.zeros(len(all_comm_recent), dtype=np.float32)
    vals = all_comm_recent.values
    # Causal rolling percentile against past 1260 non-NaN obs using searchsorted/broadcasting over last 1260 rows
    idx_comm = all_comm_recent.index.values
    mask_2021_plus = idx_comm >= "2020-11-01"
    for r in np.where(mask_2021_plus)[0]:
        s = max(0, r - 1259)
        win_v = vals[s : r + 1]
        cur_v = vals[r]
        valid_col = np.isfinite(cur_v)
        # Count finite obs per column
        fin_mask = np.isfinite(win_v)
        n_obs = fin_mask.sum(axis=0)
        ok_col = valid_col & (n_obs >= 252)
        if ok_col.any():
            # pct = mean(win_v <= cur_v) among finite obs
            le_cnt = ((win_v[:, ok_col] <= cur_v[ok_col]) & fin_mask[:, ok_col]).sum(axis=0)
            pct = le_cnt / n_obs[ok_col]
            hi_cnt[r] = float((pct >= 0.95).sum())
            lo_cnt[r] = float((pct <= 0.05).sum())

    ext_df = pd.DataFrame(
        {"comm_extreme_high_cnt_t1": hi_cnt, "comm_extreme_low_cnt_t1": lo_cnt},
        index=all_comm_recent.index,
    )
    comm_feat = comm_feat.join(ext_df, how="left").reset_index()
    comm_feat["comm_ts"] = pd.to_datetime(comm_feat["comm_dt"])
    comm_cols = [
        "comm_au_ret5d_t1",
        "comm_cu_ret5d_t1",
        "comm_wti_ret5d_t1",
        "comm_rb_ret5d_t1",
        "comm_al_ret5d_t1",
        "comm_cu_au_ratio_ret20_t1",
        "comm_bdi_ret20_t1",
        "comm_cn_ew_ret5d_t1",
        "comm_extreme_high_cnt_t1",
        "comm_extreme_low_cnt_t1",
    ]
    base = pd.merge_asof(
        base.sort_values("trade_ts"),
        comm_feat[["comm_ts"] + comm_cols].sort_values("comm_ts"),
        left_on="trade_ts",
        right_on="comm_ts",
        direction="backward",
        allow_exact_matches=False,
    ).drop(columns=["comm_ts"])

    # 8. Macro Pain Daily + Monthly Waterpool + Policy Events (strictly PIT)
    mp = pd.read_parquet(
        os.path.join(ROOT, "output/china_policy_macro_rd027_20261125/rd029_daybyday_etf/cache/macro_pain_daily_2005_20261125.parquet")
    )
    mp["trade_date"] = _norm_dt_col(mp["date"])
    mp = mp[mp["trade_date"] <= end_cutoff].sort_values("trade_date").reset_index(drop=True)
    mp_cols_src = [
        "cn_m1_m2_diff",
        "cn_pmi_mfg",
        "cn_ppi_minus_cpi",
        "cn_bond_10y",
        "cn_us_10y_spread_bp",
        "us_net_liquidity_bn_pct_3y",
        "usdcny_chg_20d",
    ]
    mp[mp_cols_src] = mp[mp_cols_src].ffill()
    mp["macro_cn_m1_m2_diff_t1"] = mp["cn_m1_m2_diff"].shift(1)
    mp["macro_cn_pmi_mfg_t1"] = mp["cn_pmi_mfg"].shift(1)
    mp["macro_cn_ppi_minus_cpi_t1"] = mp["cn_ppi_minus_cpi"].shift(1)
    mp["macro_cn_bond_10y_t1"] = mp["cn_bond_10y"].shift(1)
    mp["macro_cn_us_10y_spread_bp_t1"] = mp["cn_us_10y_spread_bp"].shift(1)
    mp["macro_us_net_liq_pct3y_t1"] = mp["us_net_liquidity_bn_pct_3y"].shift(1)
    mp["macro_usdcny_chg20_t1"] = mp["usdcny_chg_20d"].shift(1)

    # Merrill Lynch Clock (1=Reflation, 2=Recovery, 3=Overheat, 4=Stagflation) & Inventory Quadrant (Tao)
    pmi_up = mp["cn_pmi_mfg"] > mp["cn_pmi_mfg"].shift(120)
    ppi_up = mp["cn_ppi_yoy"].ffill() > mp["cn_ppi_yoy"].ffill().shift(120)
    merrill = np.where(pmi_up & (~ppi_up), 2.0, np.where(pmi_up & ppi_up, 3.0, np.where((~pmi_up) & ppi_up, 4.0, 1.0)))
    mp["th_macro_merrill_clock_t1"] = pd.Series(merrill).shift(1)
    ppi_chg60 = mp["cn_ppi_yoy"].ffill() - mp["cn_ppi_yoy"].ffill().shift(60)
    ppi_hi = mp["cn_ppi_yoy"].ffill() > mp["cn_ppi_yoy"].ffill().rolling(750, min_periods=250).median()
    inv_quad = np.where((~ppi_hi) & (ppi_chg60 > 0), 1.0, np.where(ppi_hi & (ppi_chg60 > 0), 2.0, np.where(ppi_hi & (ppi_chg60 <= 0), 3.0, 4.0)))
    mp["th_macro_inventory_quad_t1"] = pd.Series(inv_quad).shift(1)

    mp_keep = [
        "trade_date",
        "macro_cn_m1_m2_diff_t1",
        "macro_cn_pmi_mfg_t1",
        "macro_cn_ppi_minus_cpi_t1",
        "macro_cn_bond_10y_t1",
        "macro_cn_us_10y_spread_bp_t1",
        "macro_us_net_liq_pct3y_t1",
        "macro_usdcny_chg20_t1",
        "th_macro_merrill_clock_t1",
        "th_macro_inventory_quad_t1",
    ]
    base = base.merge(mp[mp_keep], on="trade_date", how="left")

    # Waterpool Monthly (strict M+1 17th lag so partial ongoing month never leaks!)
    wp = pd.read_parquet(os.path.join(ROOT, "output/china_policy_macro_rd027_20261125/data_pillars/pillar1_waterpool_monthly.parquet"))
    wp = wp[wp["month"].astype(str) < end_cutoff[:7]].copy()
    m1_17 = (pd.PeriodIndex(wp["month"].astype(str), freq="M") + 1).to_timestamp() + pd.Timedelta(days=16)
    avail_dt = pd.to_datetime(wp["available_date"])
    wp["wp_pit_ts"] = np.maximum(m1_17.values, avail_dt.values)
    wp = wp[wp["wp_pit_ts"] < pd.Timestamp(end_cutoff)].sort_values("wp_pit_ts").reset_index(drop=True)
    wp["wp_net_trading_pct_mcap_pit"] = wp["net_waterpool_trading_pct_mcap"]
    wp["wp_drain_total_pct_mcap_pit"] = wp["drain_total_pct_mcap"]
    wp["wp_net_trading_pct_5y_pit"] = wp["net_waterpool_trading_pct_mcap_pct_5y"]
    base = pd.merge_asof(
        base.sort_values("trade_ts"),
        wp[["wp_pit_ts", "wp_net_trading_pct_mcap_pit", "wp_drain_total_pct_mcap_pit", "wp_net_trading_pct_5y_pit"]].sort_values("wp_pit_ts"),
        left_on="trade_ts",
        right_on="wp_pit_ts",
        direction="backward",
        allow_exact_matches=True,
    ).drop(columns=["wp_pit_ts"])

    # Policy Events: master_events_v2 & pillar3_sector_traffic_lights strictly tradable_date <= end_cutoff
    me = pd.read_parquet(
        os.path.join(ROOT, "output/csrc_policy_100factors_20261114/policy_polymarket_v1/master_events_v2_20261125.parquet"),
        columns=["tradable_date", "market_rescue_signal", "speculation_fraud_crackdown", "share_reduction_crackdown"],
    )
    me["td"] = _norm_dt_col(me["tradable_date"])
    me = me[me["td"] <= end_cutoff].copy()
    me["is_any"] = 1.0
    me["is_rescue"] = (me["market_rescue_signal"].fillna(0) > 0).astype(float)
    me["is_crack"] = ((me["speculation_fraud_crackdown"].fillna(0) > 0) | (me["share_reduction_crackdown"].fillna(0) > 0)).astype(float)

    # Map each event's tradable_date to first trading day >= td on full_cal
    pos_me = np.searchsorted(full_cal, me["td"].values, side="left")
    valid_me = pos_me < len(full_cal)
    me = me[valid_me].copy()
    me["mapped_dt"] = full_cal[pos_me[valid_me]]
    me_day = me.groupby("mapped_dt", as_index=False)[["is_any", "is_rescue", "is_crack"]].sum()

    p3 = pd.read_parquet(
        os.path.join(ROOT, "output/china_policy_macro_rd027_20261125/data_pillars/pillar3_sector_traffic_lights.parquet"),
        columns=["tradable_date", "signal_polarity", "intensity"],
    )
    p3["td"] = _norm_dt_col(p3["tradable_date"])
    p3 = p3[p3["td"] <= end_cutoff].copy()
    p3["pol_score"] = p3["signal_polarity"].fillna(0).astype(float) * p3["intensity"].fillna(1).astype(float)
    pos_p3 = np.searchsorted(full_cal, p3["td"].values, side="left")
    valid_p3 = pos_p3 < len(full_cal)
    p3 = p3[valid_p3].copy()
    p3["mapped_dt"] = full_cal[pos_p3[valid_p3]]
    p3_day = p3.groupby("mapped_dt", as_index=False)[["pol_score"]].sum()

    pol_cal = pd.DataFrame({"trade_date": full_cal})
    pol_cal = pol_cal.merge(me_day, left_on="trade_date", right_on="mapped_dt", how="left").drop(columns=["mapped_dt"])
    pol_cal = pol_cal.merge(p3_day, left_on="trade_date", right_on="mapped_dt", how="left").drop(columns=["mapped_dt"])
    for c in ["is_any", "is_rescue", "is_crack", "pol_score"]:
        pol_cal[c] = pol_cal[c].fillna(0.0)
    pol_cal["pol_any_event_cnt_10d"] = pol_cal["is_any"].rolling(10, min_periods=1).sum()
    pol_cal["pol_rescue_signal_10d"] = pol_cal["is_rescue"].rolling(10, min_periods=1).sum()
    pol_cal["pol_crackdown_signal_10d"] = pol_cal["is_crack"].rolling(10, min_periods=1).sum()
    pol_cal["pol_p3_net_polarity_20d"] = pol_cal["pol_score"].rolling(20, min_periods=1).sum()

    base = base.merge(
        pol_cal[
            [
                "trade_date",
                "pol_any_event_cnt_10d",
                "pol_rescue_signal_10d",
                "pol_crackdown_signal_10d",
                "pol_p3_net_polarity_20d",
            ]
        ],
        on="trade_date",
        how="left",
    )

    base = base.drop(columns=["trade_ts"]).sort_values("trade_date").reset_index(drop=True)
    # Cast all numeric feature columns to float32
    feat_cols = [c for c in base.columns if c != "trade_date"]
    for c in feat_cols:
        base[c] = pd.to_numeric(base[c], errors="coerce").astype(np.float32)

    elapsed = time.time() - t0
    print(f"[Step1] Done {base.shape} in {elapsed:.1f}s (dates {base['trade_date'].min()}..{base['trade_date'].max()})")
    return base


def main():
    df_full = build_market_daily("2026-11-25")
    df_trunc = build_market_daily("2024-12-31")

    m = df_trunc.merge(df_full[df_full["trade_date"] <= "2024-12-31"], on="trade_date", suffixes=("_t", "_f"))
    assert len(m) == len(df_trunc), f"Row mismatch: {len(m)} vs {len(df_trunc)}"
    feat_cols = [c for c in df_full.columns if c != "trade_date"]

    max_diff = 0.0
    worst_col = None
    col_diffs = {}
    for c in feat_cols:
        a = m[f"{c}_t"].values.astype(np.float64)
        b = m[f"{c}_f"].values.astype(np.float64)
        nan_eq = np.array_equal(np.isnan(a), np.isnan(b))
        fin = np.isfinite(a) & np.isfinite(b)
        d = float(np.max(np.abs(a[fin] - b[fin]))) if fin.any() else 0.0
        if not nan_eq:
            d = 999.0
        col_diffs[c] = d
        if d > max_diff:
            max_diff = d
            worst_col = c

    print(f"[Step1] 2024-12-31 physical truncation check: max_abs_diff={max_diff} (worst={worst_col})")
    assert max_diff == 0.0, f"PIT truncation leaked on {worst_col}: {max_diff}"

    # Check missingness across 2021-01-04..2026-11-25 and tail rows
    miss_rates = {c: round(float(df_full[c].isna().mean()), 6) for c in feat_cols}
    nonzero_miss = {k: v for k, v in miss_rates.items() if v > 0}
    tail_nulls = {c: int(df_full.tail(5)[c].isna().sum()) for c in feat_cols if df_full.tail(5)[c].isna().any()}
    print(f"[Step1] Total features={len(feat_cols)}, nonzero_miss_cols={len(nonzero_miss)}: {nonzero_miss}")
    print(f"[Step1] Last 5 days nulls: {tail_nulls}")

    out_pq = os.path.join(OUT_DIR, "market_daily_all_new_factors_pit.parquet")
    df_full.to_parquet(out_pq, index=False, compression="snappy")

    audit = {
        "file": out_pq,
        "rows": int(len(df_full)),
        "date_min": str(df_full["trade_date"].min()),
        "date_max": str(df_full["trade_date"].max()),
        "n_features": len(feat_cols),
        "features": feat_cols,
        "truncation_2024_12_31_rows": int(len(m)),
        "truncation_2024_12_31_max_abs_diff": max_diff,
        "nonzero_missing_rates": nonzero_miss,
        "tail5_nulls": tail_nulls,
        "size_mb": round(os.path.getsize(out_pq) / 1024 / 1024, 3),
    }
    audit_path = os.path.join(OUT_DIR, "_audit_step1_market.json")
    with open(audit_path, "w") as f:
        json.dump(audit, f, indent=2, ensure_ascii=False)
    print(f"[Step1] Saved {out_pq} ({audit['size_mb']} MB) & {audit_path}")


if __name__ == "__main__":
    main()

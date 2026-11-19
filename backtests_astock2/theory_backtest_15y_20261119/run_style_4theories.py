#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A-Share 15-Year Local Style, Fundamental & Sentiment Cycle Empirical Backtest (2011-01-01 to 2026-11-18).
Covers 5 theories:
  1. 小市值轮动_壳价值理论 (Smallest 5% float mcap, monthly rebalance)
  2. 核心资产大蓝筹低波_茅指数本土化 (Top 15% float mcap -> lowest 30 by 60d volatility)
  3. 超跌反转效应_跌多了就买 (Bottom 10% by trailing 20d return)
  4. 动量追强效应_强者恒强 (Top 10% by trailing 60d ex-5d return; + pure 60d check)
  5. 情绪冰点与量能拥挤择时_游资周期论 (Causal 250d amt_pct + breadth/limit-up-down timing)
Strict PIT, zero yfinance (D12), D15 turnover cost (0.15% one-way / 0.30% round-trip),
limit-up & suspension execution guard, IPO >= 180d, ST proxy (low price < 2.0 or 5% daily cap).
"""
import json
import os
import time
import numpy as np
import pandas as pd

import tei_metrics

BASE_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/theory_backtest_15y_20261119"
DATA_CACHE = os.path.join(BASE_DIR, "data_cache")
A_DAILY_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_daily.parquet"
A_DELIST_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_delisted_daily.parquet"
INDUSTRY_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/industry.csv"

START_DATE = "2011-01-01"
END_DATE = "2026-11-18"
ONE_WAY_FEE = 0.0015  # 0.15% one-way = 0.30% round-trip

# Exact 10-industry CSRC prefix partition verified to 1e-18 against sector_ret_ew_15y.parquet
SEC_MAP = {
    "传媒文娱": ["I63", "L72", "R86", "R87", "R88"],
    "公用基建交运": ["D44", "D45", "D46", "E47", "E48", "E49", "E50", "G54", "G55", "G58", "G59", "G60", "N76", "N77"],
    "其他综合": ["A02", "A03", "A04", "A05", "B10", "B11", "C19", "C20", "C23", "C29", "C41", "C42", "F51", "L71", "M73", "M74", "M75", "N78", "P83", "R89", "S91"],
    "医药生物": ["C27", "Q84"],
    "周期资源": ["B06", "B07", "B08", "B09", "C22", "C25", "C26", "C28", "C30", "C31", "C32"],
    "消费食饮": ["A01", "C13", "C14", "C15", "C17", "C18", "C21", "C24", "F52", "H61", "H62"],
    "电力新能源": ["C38", "C40"],
    "科技电子软件": ["C39", "I64", "I65", "O81"],
    "金融地产": ["J66", "J67", "J68", "J69", "K70"],
    "高端制造军工": ["C33", "C34", "C35", "C36", "C37", "C43", "G53", "G56"],
}
PREF_TO_SEC = {p: s for s, ps in SEC_MAP.items() for p in ps}
SECTORS = list(SEC_MAP.keys())


def load_industry_map() -> dict:
    ind = pd.read_csv(INDUSTRY_PATH)
    ind["ticker"] = ind["code"].apply(lambda c: f"{c.split('.')[1]}.{c.split('.')[0].upper()}")
    ind["sec"] = ind["industry"].fillna("").str[:3].map(PREF_TO_SEC)
    return ind.dropna(subset=["sec"]).set_index("ticker")["sec"].to_dict()


def build_panel_matrices(include_delisted: bool = False):
    """Load daily data (>=2010-06-01), compute exact first listing dates, and build dense [T, N] matrices."""
    t0 = time.time()
    all_dt = pd.read_parquet(A_DAILY_PATH, columns=["date", "ticker"])
    first_dt_map = all_dt.groupby("ticker")["date"].min()
    del all_dt

    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "oshare"]
    df = pd.read_parquet(A_DAILY_PATH, columns=cols, filters=[("date", ">=", pd.Timestamp("2010-06-01"))])

    if include_delisted:
        dl = pd.read_parquet(A_DELIST_PATH, columns=cols)
        dl = dl[dl["date"] >= pd.Timestamp("2010-06-01")].copy()
        dl = dl.sort_values(["ticker", "date"])
        dl["oshare"] = dl.groupby("ticker")["oshare"].ffill()
        dl_first = dl.groupby("ticker")["date"].min()
        first_dt_map = pd.concat([first_dt_map, dl_first])
        df = pd.concat([df, dl], ignore_index=True)

    df = df[(df["close"] > 0) & (df["adj_close"] > 0) & (df["oshare"] > 0) & (df["volume"] > 0)].copy()
    df = df.sort_values(["ticker", "date"]).drop_duplicates(["ticker", "date"], keep="last")

    # Daily return clipped strictly by board & regime date to prevent resumption/dirty spikes
    prev_adj = df.groupby("ticker")["adj_close"].shift(1)
    raw_ret = df["adj_close"] / prev_adj - 1.0
    is_20pct_board = df["ticker"].str.startswith(("300", "301", "688"))
    is_post_reg = df["date"] >= pd.Timestamp("2020-08-24")
    lim = np.where(is_20pct_board & is_post_reg, 0.22, 0.11)
    df["ret"] = raw_ret.clip(-lim, lim)

    # Exact one-word limit up: open==high==low==close and ret >= 9.5%
    df["is_yz_zt"] = (
        (df["open"] == df["high"])
        & (df["high"] == df["low"])
        & (df["low"] == df["close"])
        & (df["ret"] >= 0.095)
    )

    # PIT ST proxy: penny close < 2.0 OR 40d max |ret| <= 5.5% with >=1 5%-locked day
    prev_c = df.groupby("ticker")["close"].shift(1)
    ret_raw_c = df["close"] / prev_c - 1.0
    is_5_lock = (
        (ret_raw_c.abs().between(0.046, 0.055))
        & ((df["close"] >= df["high"] - 1e-4) | (df["close"] <= df["low"] + 1e-4))
    ).astype(np.float32)
    max_abs_40 = ret_raw_c.abs().groupby(df["ticker"]).transform(lambda s: s.rolling(40, min_periods=15).max())
    lock5_40 = is_5_lock.groupby(df["ticker"]).transform(lambda s: s.rolling(40, min_periods=15).sum())
    df["is_st"] = (df["close"] < 2.0) | ((max_abs_40 <= 0.055) & (lock5_40 >= 1))

    # Listing age >= 180 calendar days
    df["first_date"] = df["ticker"].map(first_dt_map)
    df["age_ok"] = (df["date"] - df["first_date"]).dt.days >= 180
    df["mcap"] = df["close"] * df["oshare"]

    dates = pd.DatetimeIndex(sorted(df["date"].unique()))
    tickers = np.array(sorted(df["ticker"].unique()))
    d_idx = dates.get_indexer(df["date"])
    t_idx = pd.Index(tickers).get_indexer(df["ticker"])
    T, N = len(dates), len(tickers)

    ret_mat = np.zeros((T, N), dtype=np.float64)
    traded_mat = np.zeros((T, N), dtype=bool)
    yz_zt_mat = np.zeros((T, N), dtype=bool)
    st_mat = np.zeros((T, N), dtype=bool)
    age_mat = np.zeros((T, N), dtype=bool)
    mcap_mat = np.full((T, N), np.nan, dtype=np.float64)

    ret_valid = df["ret"].fillna(0.0).to_numpy(dtype=np.float64)
    ret_mat[d_idx, t_idx] = ret_valid
    traded_mat[d_idx, t_idx] = True
    yz_zt_mat[d_idx, t_idx] = df["is_yz_zt"].to_numpy(dtype=bool)
    st_mat[d_idx, t_idx] = df["is_st"].to_numpy(dtype=bool)
    age_mat[d_idx, t_idx] = df["age_ok"].to_numpy(dtype=bool)
    mcap_mat[d_idx, t_idx] = df["mcap"].to_numpy(dtype=np.float64)

    # Track last traded date index per ticker so delisted stocks can exit cleanly in sensitivity test
    last_trade_idx = np.zeros(N, dtype=np.int32)
    np.maximum.at(last_trade_idx, t_idx, d_idx)

    # Vectorized rolling factor signals over trading calendar
    # Compounded returns via log(1+r) only on traded days; counts verify min_periods
    log_r = np.where(traded_mat, np.log1p(np.clip(ret_mat, -0.95, 2.0)), 0.0)
    tr_int = traded_mat.astype(np.int32)
    cs_log = np.vstack([np.zeros((1, N)), np.cumsum(log_r, axis=0)])
    cs_cnt = np.vstack([np.zeros((1, N), dtype=np.int32), np.cumsum(tr_int, axis=0)])

    def win_ret(end_offset: int, start_offset: int, min_obs: int):
        """Return compounded return over [t - start_offset + 1, t - end_offset] inclusive."""
        out = np.full((T, N), np.nan, dtype=np.float64)
        hi = np.arange(T) + 1 - end_offset
        lo = np.arange(T) + 1 - start_offset
        valid_rows = lo >= 0
        hi_v = hi[valid_rows]
        lo_v = lo[valid_rows]
        cnt = cs_cnt[hi_v] - cs_cnt[lo_v]
        s_log = cs_log[hi_v] - cs_log[lo_v]
        val = np.where(cnt >= min_obs, np.expm1(s_log), np.nan)
        out[valid_rows] = val
        return out

    ret_20d = win_ret(0, 20, 15)
    mom_60_ex5 = win_ret(5, 60, 35)
    mom_60_pure = win_ret(0, 60, 40)

    # 60d rolling daily volatility (on traded days only)
    r_tr = np.where(traded_mat, ret_mat, 0.0)
    r2_tr = np.where(traded_mat, ret_mat * ret_mat, 0.0)
    cs_r = np.vstack([np.zeros((1, N)), np.cumsum(r_tr, axis=0)])
    cs_r2 = np.vstack([np.zeros((1, N)), np.cumsum(r2_tr, axis=0)])
    vol_60d = np.full((T, N), np.nan, dtype=np.float64)
    idx_hi = np.arange(60, T + 1)
    idx_lo = idx_hi - 60
    cnt60 = cs_cnt[idx_hi] - cs_cnt[idx_lo]
    mean60 = (cs_r[idx_hi] - cs_r[idx_lo]) / np.maximum(cnt60, 1)
    var60 = np.maximum(0.0, (cs_r2[idx_hi] - cs_r2[idx_lo]) / np.maximum(cnt60, 1) - mean60 ** 2)
    vol_60d[idx_hi - 1] = np.where(cnt60 >= 40, np.sqrt(var60), np.nan)

    print(f"Panel built (delisted={include_delisted}): T={T}, N={N} in {time.time() - t0:.2f}s")
    return {
        "dates": dates,
        "tickers": tickers,
        "ret_mat": ret_mat,
        "traded_mat": traded_mat,
        "yz_zt_mat": yz_zt_mat,
        "st_mat": st_mat,
        "age_mat": age_mat,
        "mcap_mat": mcap_mat,
        "ret_20d": ret_20d,
        "mom_60_ex5": mom_60_ex5,
        "mom_60_pure": mom_60_pure,
        "vol_60d": vol_60d,
        "last_trade_idx": last_trade_idx,
    }


def get_monthly_schedule(dates: pd.DatetimeIndex):
    """Return list of (signal_idx_month_end, exec_idx_next_month_first) starting from 2010-11 -> 2010-12."""
    s = pd.Series(np.arange(len(dates)), index=dates)
    ym = dates.to_period("M")
    m_ends = s.groupby(ym).last().values
    m_starts = s.groupby(ym).first().values
    # Pair month k's last day with month k+1's first day
    pairs = []
    for k in range(len(m_ends) - 1):
        sig_i = int(m_ends[k])
        exe_i = int(m_starts[k + 1])
        if dates[sig_i] >= pd.Timestamp("2010-11-01"):
            pairs.append((sig_i, exe_i))
    return pairs


def simulate_monthly_portfolio(panel, schedule, selector_fn, universe_mask=None, freeze_suspended=True):
    """
    Execute monthly strategy: select targets on sig_i close -> execute on exe_i close
    (excluding one-word limit-ups & untraded on exe_i), deduct 0.15% one-way turnover fee.
    Returns daily return Series (2011-01-01..2026-11-18), monthly audit records, turnover_ann, avg_holdings.
    """
    dates = panel["dates"]
    ret_mat = panel["ret_mat"]
    traded_mat = panel["traded_mat"]
    yz_zt_mat = panel["yz_zt_mat"]
    st_mat = panel["st_mat"]
    age_mat = panel["age_mat"]
    last_trade_idx = panel["last_trade_idx"]
    T, N = ret_mat.shape

    if universe_mask is None:
        universe_mask = np.ones(N, dtype=bool)

    daily_ret = np.zeros(T, dtype=np.float64)
    w = np.zeros(N, dtype=np.float64)
    total_oneway_to = 0.0
    holding_counts = []
    monthly_logs = []
    delist_mask = last_trade_idx < (T - 25)

    for m_idx, (sig_i, exe_i) in enumerate(schedule):
        next_exe_i = schedule[m_idx + 1][1] if m_idx + 1 < len(schedule) else T - 1

        # 1. Propagate old weights through (prev_exe_i + 1 .. exe_i)
        # On first step (m_idx == 0), start holding from exe_i close onward
        if m_idx > 0:
            prev_exe = schedule[m_idx - 1][1]
            gross_nav = 1.0
            for d in range(prev_exe + 1, exe_i + 1):
                if w.sum() <= 0:
                    daily_ret[d] = 0.0
                    continue
                r_d = np.where(traded_mat[d], ret_mat[d], 0.0)
                rp_d = float(np.dot(w, r_d))
                # Liquidate delisted stocks at close of their final trading day (into cash)
                delist_today = delist_mask & (last_trade_idx == d) & (w > 1e-10)
                if np.any(delist_today):
                    liq_w = float(w[delist_today].sum())
                    rp_d = (1.0 + rp_d) * (1.0 - ONE_WAY_FEE * liq_w) - 1.0
                    if dates[d] >= pd.Timestamp(START_DATE):
                        total_oneway_to += 0.5 * liq_w
                daily_ret[d] = rp_d
                gross_nav *= (1.0 + rp_d)
                denom = 1.0 + rp_d
                if denom > 1e-6:
                    w = w * (1.0 + r_d) / denom
                if np.any(delist_today):
                    w[delist_today] = 0.0
            if monthly_logs:
                monthly_logs[-1]["gross_ret"] = round((gross_nav - 1.0) * 100.0, 3)
                monthly_logs[-1]["net_ret"] = round(((1.0 - monthly_logs[-1]["cost_pct"] / 100.0) * gross_nav - 1.0) * 100.0, 3)

        # 2. Select targets using strict t <= sig_i information
        elig_sig = universe_mask & traded_mat[sig_i] & age_mat[sig_i] & (~st_mat[sig_i])
        picks = selector_fn(panel, sig_i, elig_sig)

        # 3. Filter at execution day exe_i: must trade & NOT one-word limit-up
        buyable = picks[traded_mat[exe_i, picks] & (~yz_zt_mat[exe_i, picks])] if len(picks) > 0 else np.array([], dtype=int)

        # Frozen positions: currently held stocks temporarily suspended on exe_i (still trading later) cannot be sold
        if freeze_suspended and m_idx > 0:
            held_mask = w > 1e-10
            frozen_mask = held_mask & (~traded_mat[exe_i]) & (exe_i < last_trade_idx)
            frozen_w = float(w[frozen_mask].sum())
        else:
            frozen_mask = np.zeros(N, dtype=bool)
            frozen_w = 0.0

        w_new = np.zeros(N, dtype=np.float64)
        if frozen_w > 0:
            w_new[frozen_mask] = w[frozen_mask]
        avail_w = max(0.0, 1.0 - frozen_w)

        if len(buyable) > 0 and avail_w > 1e-6:
            # Exclude already-frozen tickers from new equal-weight allocation
            buyable_nf = buyable[~frozen_mask[buyable]]
            if len(buyable_nf) > 0:
                w_new[buyable_nf] = avail_w / len(buyable_nf)

        # 4. Exact turnover & fee deduction on exe_i close
        if m_idx > 0:
            abs_diff = float(np.sum(np.abs(w_new - w)))
            cost = ONE_WAY_FEE * abs_diff
            if dates[exe_i] >= pd.Timestamp(START_DATE):
                total_oneway_to += 0.5 * abs_diff
            daily_ret[exe_i] = (1.0 + daily_ret[exe_i]) * (1.0 - cost) - 1.0
        else:
            cost = 0.0

        w = w_new
        n_hold = int((w > 1e-10).sum())
        if dates[exe_i] >= pd.Timestamp(START_DATE):
            holding_counts.append(n_hold)
            monthly_logs.append({
                "rebal_date": str(dates[exe_i])[:10],
                "end_date": str(dates[next_exe_i])[:10],
                "n_selected": int(len(picks)),
                "n_buyable": int(len(buyable)),
                "n_hold": n_hold,
                "cost_pct": round(cost * 100.0, 3),
                "gross_ret": None,
                "net_ret": None,
            })

    # Final tail from last exe_i + 1 to T - 1
    last_exe = schedule[-1][1]
    tail_gross = 1.0
    for d in range(last_exe + 1, T):
        if w.sum() <= 0:
            continue
        r_d = np.where(traded_mat[d], ret_mat[d], 0.0)
        rp_d = float(np.dot(w, r_d))
        daily_ret[d] = rp_d
        tail_gross *= (1.0 + rp_d)
        denom = 1.0 + rp_d
        if denom > 1e-6:
            w = w * (1.0 + r_d) / denom
    if monthly_logs:
        monthly_logs[-1]["gross_ret"] = round((tail_gross - 1.0) * 100.0, 3)
        monthly_logs[-1]["net_ret"] = round(((1.0 - monthly_logs[-1]["cost_pct"] / 100.0) * tail_gross - 1.0) * 100.0, 3)

    s_ret = pd.Series(daily_ret, index=dates).loc[START_DATE:END_DATE]
    years = len(s_ret) / 242.0
    return {
        "ret": s_ret,
        "turnover_ann_oneway": round(total_oneway_to / max(years, 0.1), 2),
        "avg_holdings": round(float(np.mean(holding_counts)) if holding_counts else 0.0, 1),
        "monthly_logs": monthly_logs,
    }


# --- Selector functions (all strictly t <= sig_i) ---
def sel_small_cap(panel, sig_i, elig, frac=0.05, min_k=10):
    mcap = panel["mcap_mat"][sig_i]
    valid = elig & np.isfinite(mcap) & (mcap > 0)
    idx = np.flatnonzero(valid)
    if len(idx) == 0:
        return idx
    k = min(len(idx), max(min_k, int(round(frac * len(idx)))))
    order = np.argsort(mcap[idx])[:k]
    return idx[order]


def sel_core_lowvol(panel, sig_i, elig, top_mcap_frac=0.15, k_lowvol=30, min_pool=12):
    mcap = panel["mcap_mat"][sig_i]
    vol = panel["vol_60d"][sig_i]
    valid = elig & np.isfinite(mcap) & (mcap > 0) & np.isfinite(vol) & (vol > 0)
    idx = np.flatnonzero(valid)
    if len(idx) == 0:
        return idx
    pool_n = min(len(idx), max(min_pool, int(round(top_mcap_frac * len(idx)))))
    big_idx = idx[np.argsort(-mcap[idx])[:pool_n]]
    k = min(len(big_idx), k_lowvol)
    return big_idx[np.argsort(vol[big_idx])[:k]]


def sel_rev_20d(panel, sig_i, elig, frac=0.10, min_k=5):
    r20 = panel["ret_20d"][sig_i]
    valid = elig & np.isfinite(r20)
    idx = np.flatnonzero(valid)
    if len(idx) == 0:
        return idx
    k = min(len(idx), max(min_k, int(round(frac * len(idx)))))
    return idx[np.argsort(r20[idx])[:k]]


def sel_mom_60_ex5(panel, sig_i, elig, frac=0.10, min_k=5):
    mom = panel["mom_60_ex5"][sig_i]
    valid = elig & np.isfinite(mom)
    idx = np.flatnonzero(valid)
    if len(idx) == 0:
        return idx
    k = min(len(idx), max(min_k, int(round(frac * len(idx)))))
    return idx[np.argsort(-mom[idx])[:k]]


def sel_mom_60_pure(panel, sig_i, elig, frac=0.10, min_k=5):
    mom = panel["mom_60_pure"][sig_i]
    valid = elig & np.isfinite(mom)
    idx = np.flatnonzero(valid)
    if len(idx) == 0:
        return idx
    k = min(len(idx), max(min_k, int(round(frac * len(idx)))))
    return idx[np.argsort(-mom[idx])[:k]]


def build_sentiment_positions(mb: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """
    Strictly causal (t-1 signal -> t position) sentiment cycle timing from market_breadth_15y.parquet.
    Returns:
      pos_cycle: 3-state prompt-faithful timing (1.0 post-ice-point/low-vol stabilization, 0.5 neutral, 0.0 crowded peak rollover)
      pos_ice_only: pure post-ice-point 10-day event long (1.0 vs 0.0)
    """
    df = mb.sort_index().copy()
    df["dt_ratio"] = df["n_dt"] / df["n_stocks"].clip(lower=1)
    df["net_zt_dt"] = (df["n_zt"] - df["n_dt"]) / df["n_stocks"].clip(lower=1)
    df["net_5d"] = df["net_zt_dt"].rolling(5).mean()
    df["amt_pct"] = df["tot_amt_yi"].rolling(250, min_periods=120).rank(pct=True)
    df["net5d_pct"] = df["net_5d"].rolling(250, min_periods=120).rank(pct=True)

    # Ice-point / low-volume condition in past 5 days -> enter 1.0 on stabilization
    ice_raw = (df["amt_pct"] < 0.20) | (df["adv_ratio"] < 0.20) | (df["dt_ratio"] > 0.015)
    stabilized = (df["adv_ratio"] >= 0.45) & (df["n_zt"] >= df["n_dt"])
    ice_stab = ice_raw.rolling(5, min_periods=1).max().astype(bool) & stabilized

    # Overheat crowding peak rollover: 5d max amt_pct > 92% AND 5d赚钱效应见顶回落
    crowd_roll = (
        (df["amt_pct"].rolling(5, min_periods=1).max() > 0.92)
        & (df["net_5d"] < df["net_5d"].rolling(10, min_periods=3).max())
        & (df["net5d_pct"] < 0.65)
    )
    cool_back = (df["amt_pct"] < 0.70) & (df["adv_ratio"] >= 0.45)

    # Pure deep panic/ice-point event trigger (for auxiliary short-term bounce check)
    deep_ice_raw = (df["amt_pct"] < 0.12) | (df["adv_ratio"] < 0.20) | (df["dt_ratio"] > 0.015)
    deep_ice_stab = deep_ice_raw.rolling(5, min_periods=1).max().astype(bool) & stabilized

    # Hysteresis state machine with 5d cooldown (computed at close t, shifted +1 for trading day t+1)
    pos_arr = np.full(len(df), 0.5, dtype=np.float64)
    ice_arr = np.zeros(len(df), dtype=np.float64)
    state = 0.5
    cd = 0
    ice_hold = 0
    for i in range(len(df)):
        if cd > 0:
            cd -= 1
        if crowd_roll.iloc[i] and cd == 0:
            state = 0.0
            cd = 5
            ice_hold = 0
        elif ice_stab.iloc[i] and cd == 0:
            state = 1.0
            cd = 5
        elif state == 0.0 and cool_back.iloc[i] and cd == 0:
            state = 0.5
            cd = 5
        pos_arr[i] = state

        if ice_hold == 0 and deep_ice_stab.iloc[i]:
            ice_hold = 10
        if ice_hold > 0:
            ice_arr[i] = 1.0
            ice_hold -= 1

    pos_cycle = pd.Series(pos_arr, index=df.index).shift(1).fillna(0.5)
    pos_ice_only = pd.Series(ice_arr, index=df.index).shift(1).fillna(0.0)
    return pos_cycle, pos_ice_only


def apply_timing_overlay(pos: pd.Series, asset_ret: pd.Series) -> tuple[pd.Series, float]:
    """Apply daily causal position weight pos[t] to asset_ret[t] with 0.15% one-way turnover fee."""
    df = pd.DataFrame({"pos": pos, "ret": asset_ret}).dropna()
    df = df.loc[START_DATE:END_DATE]
    d_pos = df["pos"].diff().abs().fillna(0.0)
    strat = df["pos"] * df["ret"] - ONE_WAY_FEE * d_pos
    to_ann = float(d_pos.sum() * 0.5 / max(len(df) / 242.0, 0.1))
    return strat, round(to_ann, 2)


def extract_extreme_months(ret_s: pd.Series, bench_s: pd.Series, logs: list = None) -> dict:
    """Audit top 5 best and worst monthly returns for sanity check."""
    m_s = (1.0 + ret_s).resample("ME").prod() - 1.0
    m_b = (1.0 + bench_s.reindex(ret_s.index).fillna(0.0)).resample("ME").prod() - 1.0
    df_m = pd.DataFrame({"strat_pct": (m_s * 100.0).round(2), "bench_pct": (m_b * 100.0).round(2)})
    df_m["excess_pct"] = (df_m["strat_pct"] - df_m["bench_pct"]).round(2)
    df_m.index = df_m.index.strftime("%Y-%m")
    best5 = [{"month": k, **v} for k, v in df_m.nlargest(5, "strat_pct").to_dict("index").items()]
    worst5 = [{"month": k, **v} for k, v in df_m.nsmallest(5, "strat_pct").to_dict("index").items()]
    out = {"best_5_months": best5, "worst_5_months": worst5}
    if logs:
        valid_logs = [x for x in logs if x["net_ret"] is not None]
        out["rebal_top3_net"] = sorted(valid_logs, key=lambda x: x["net_ret"], reverse=True)[:3]
        out["rebal_bot3_net"] = sorted(valid_logs, key=lambda x: x["net_ret"])[:3]
    return out


def main():
    t_start = time.time()
    ind_map = load_industry_map()
    panel = build_panel_matrices(include_delisted=False)
    schedule = get_monthly_schedule(panel["dates"])

    # Load benchmarks & regime table
    broad = pd.read_parquet(os.path.join(DATA_CACHE, "broad_indices_15y.parquet"))
    sh300 = broad[broad["symbol"] == "sh000300"].sort_values("date").set_index("date")["close"].pct_change()
    sh300 = sh300.loc[START_DATE:END_DATE].dropna()
    sector_cw = pd.read_parquet(os.path.join(DATA_CACHE, "sector_ret_cw_15y.parquet")).loc[START_DATE:END_DATE]
    regime_df = pd.read_parquet(os.path.join(DATA_CACHE, "regime_daily_15y.parquet"))
    mb = pd.read_parquet(os.path.join(DATA_CACHE, "market_breadth_15y.parquet"))

    ticker_secs = np.array([ind_map.get(t, "OTHER") for t in panel["tickers"]])
    sec_masks = {sec: (ticker_secs == sec) for sec in SECTORS}

    # Theory specs: (name, selector_full, selector_ind)
    stock_theories = [
        ("小市值轮动_壳价值理论", lambda p, i, e: sel_small_cap(p, i, e, 0.05, 10), lambda p, i, e: sel_small_cap(p, i, e, 0.05, 5)),
        ("核心资产大蓝筹低波_茅指数本土化", lambda p, i, e: sel_core_lowvol(p, i, e, 0.15, 30, 15), lambda p, i, e: sel_core_lowvol(p, i, e, 0.25, 10, 12)),
        ("超跌反转效应_跌多了就买", lambda p, i, e: sel_rev_20d(p, i, e, 0.10, 10), lambda p, i, e: sel_rev_20d(p, i, e, 0.10, 5)),
        ("动量追强效应_强者恒强", lambda p, i, e: sel_mom_60_ex5(p, i, e, 0.10, 10), lambda p, i, e: sel_mom_60_ex5(p, i, e, 0.10, 5)),
    ]

    results = {
        "meta": {
            "window": f"{START_DATE} to {END_DATE}",
            "n_days": int(len(sh300)),
            "n_rebalance_months": len(schedule) - 1,
            "cost_rule": "0.15% one-way (0.30% round-trip) on actual drifted turnover",
            "pit_rules": "Month-end signal -> next month first trading day close execution; excludes one-word limit-up, suspended, age<180d, ST proxy (close<2.0 or 5% limit); daily return clipped [-0.11,0.11] main/pre-2020.08, [-0.22,0.22] 300/301/688 post-2020.08",
            "benchmark_main": "sh000300",
            "benchmark_industry": "sector_ret_cw_15y",
        },
        "theories": {},
        "auxiliary_checks": {},
    }
    daily_rets = {}

    for name, fn_full, fn_ind in stock_theories:
        res_full = simulate_monthly_portfolio(panel, schedule, fn_full, universe_mask=None)
        ret_full = res_full["ret"].reindex(sh300.index).fillna(0.0)
        daily_rets[name] = ret_full
        prof = tei_metrics.evaluate_full_profile(name, ret_full, sh300, regime_df)
        prof["turnover_ann_oneway"] = res_full["turnover_ann_oneway"]
        prof["avg_holdings"] = res_full["avg_holdings"]
        prof["extreme_months_audit"] = extract_extreme_months(ret_full, sh300, res_full["monthly_logs"])

        ind_tei = {}
        for sec in SECTORS:
            res_s = simulate_monthly_portfolio(panel, schedule, fn_ind, universe_mask=sec_masks[sec])
            ret_s = res_s["ret"].reindex(sh300.index).fillna(0.0)
            b_s = sector_cw[sec].reindex(sh300.index).fillna(0.0)
            p_s = tei_metrics.evaluate_full_profile(f"{name}_{sec}", ret_s, b_s, regime_df)
            ind_tei[sec] = {
                "overall_15y": p_s["overall_15y"],
                "last_10y": p_s["last_10y"],
                "last_3y": p_s["last_3y"],
                "tei_decay_per_decade": p_s["tei_decay_per_decade"],
                "turnover_ann_oneway": res_s["turnover_ann_oneway"],
                "avg_holdings": res_s["avg_holdings"],
            }
        prof["industry_tei"] = ind_tei
        results["theories"][name] = prof
        print(f"Done {name}: 15Y TEI={prof['overall_15y']['tei']}, ex={prof['overall_15y']['excess_ann']}%, 3Y TEI={prof['last_3y']['tei']}")

    # Theory 5: Sentiment & Crowding Timing
    pos_cycle, pos_ice_only = build_sentiment_positions(mb)
    t5_name = "情绪冰点与量能拥挤择时_游资周期论"
    ret_t5, to_t5 = apply_timing_overlay(pos_cycle, sh300)
    act_t5 = (pos_cycle.reindex(ret_t5.index).fillna(0.0) > 0.01).astype(float)
    daily_rets[t5_name] = ret_t5
    prof_t5 = tei_metrics.evaluate_full_profile(t5_name, ret_t5, sh300, regime_df, active_mask=act_t5)
    prof_t5["turnover_ann_oneway"] = to_t5
    prof_t5["avg_exposure_pct"] = round(float(pos_cycle.reindex(ret_t5.index).mean() * 100.0), 1)
    prof_t5["extreme_months_audit"] = extract_extreme_months(ret_t5, sh300)

    ind_tei_t5 = {}
    for sec in SECTORS:
        b_s = sector_cw[sec].reindex(sh300.index).fillna(0.0)
        r_s, to_s = apply_timing_overlay(pos_cycle, b_s)
        p_s = tei_metrics.evaluate_full_profile(f"{t5_name}_{sec}", r_s, b_s, regime_df, active_mask=act_t5)
        ind_tei_t5[sec] = {
            "overall_15y": p_s["overall_15y"],
            "last_10y": p_s["last_10y"],
            "last_3y": p_s["last_3y"],
            "tei_decay_per_decade": p_s["tei_decay_per_decade"],
            "turnover_ann_oneway": to_s,
        }
    prof_t5["industry_tei"] = ind_tei_t5
    results["theories"][t5_name] = prof_t5
    print(f"Done {t5_name}: 15Y TEI={prof_t5['overall_15y']['tei']}, ex={prof_t5['overall_15y']['excess_ann']}%, 3Y TEI={prof_t5['last_3y']['tei']}")

    # Auxiliary checks: (1) Pure 60d momentum vs skip-5d; (2) Pure ice-point event long; (3) Survivorship check with a_delisted_daily (2015-2026)
    res_m60p = simulate_monthly_portfolio(panel, schedule, lambda p, i, e: sel_mom_60_pure(p, i, e, 0.10, 10))
    ret_m60p = res_m60p["ret"].reindex(sh300.index).fillna(0.0)
    daily_rets["动量追强_纯60d"] = ret_m60p
    results["auxiliary_checks"]["动量追强_纯60d"] = tei_metrics.evaluate_full_profile("动量追强_纯60d", ret_m60p, sh300, regime_df)

    ret_ice, to_ice = apply_timing_overlay(pos_ice_only, sh300)
    act_ice = (pos_ice_only.reindex(ret_ice.index).fillna(0.0) > 0.01).astype(float)
    daily_rets["情绪纯冰点短线做多"] = ret_ice
    prof_ice = tei_metrics.evaluate_full_profile("情绪纯冰点短线做多", ret_ice, sh300, regime_df, active_mask=act_ice)
    prof_ice["turnover_ann_oneway"] = to_ice
    results["auxiliary_checks"]["情绪纯冰点短线做多"] = prof_ice

    # Survivorship sensitivity check (2015-07-01 .. 2026-11-18) including a_delisted_daily.parquet
    del panel
    panel_dl = build_panel_matrices(include_delisted=True)
    sched_dl = get_monthly_schedule(panel_dl["dates"])
    res_sc_dl = simulate_monthly_portfolio(panel_dl, sched_dl, lambda p, i, e: sel_small_cap(p, i, e, 0.05, 10))
    ret_sc_dl = res_sc_dl["ret"].reindex(sh300.index).fillna(0.0)
    daily_rets["小市值轮动_含退市检验"] = ret_sc_dl
    w_start = "2015-07-01"
    m_nodl = tei_metrics.compute_period_metrics(daily_rets["小市值轮动_壳价值理论"].loc[w_start:], sh300.loc[w_start:])
    m_withdl = tei_metrics.compute_period_metrics(ret_sc_dl.loc[w_start:], sh300.loc[w_start:])
    results["auxiliary_checks"]["survivorship_smallcap_2015_2026"] = {
        "note": "a_daily.parquet contains 5216 surviving tickers; a_delisted_daily.parquet adds 255 delisted tickers from 2015-01-05 onward. Compared over 2015-07-01 to 2026-11-18.",
        "a_daily_only": m_nodl,
        "with_a_delisted": m_withdl,
        "ann_ret_gap_pct": round(m_withdl["ann_ret"] - m_nodl["ann_ret"], 2),
    }

    # Save parquet & JSON
    df_out = pd.DataFrame(daily_rets, index=sh300.index)
    df_out.index.name = "date"
    pq_path = os.path.join(BASE_DIR, "daily_ret_style.parquet")
    df_out.to_parquet(pq_path)

    # Compact summary for quick inspection
    comp = {}
    for k, v in results["theories"].items():
        comp[k] = {
            "15y_tei": v["overall_15y"]["tei"],
            "15y_ann": v["overall_15y"]["ann_ret"],
            "15y_ex": v["overall_15y"]["excess_ann"],
            "15y_ir": v["overall_15y"]["ir"],
            "15y_mdd": v["overall_15y"]["mdd"],
            "10y_tei": v["last_10y"]["tei"],
            "10y_ex": v["last_10y"]["excess_ann"],
            "3y_tei": v["last_3y"]["tei"],
            "3y_ex": v["last_3y"]["excess_ann"],
            "decay_per_decade": v["tei_decay_per_decade"],
            "era_tei": {ek: ev["tei"] for ek, ev in v["regimes"].get("era", {}).items()},
            "era_ex": {ek: ev["excess_ann"] for ek, ev in v["regimes"].get("era", {}).items()},
        }
    results["comparison_summary"] = comp

    json_path = os.path.join(BASE_DIR, "res_style_4theories.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"ALL DONE in {time.time() - t_start:.2f}s -> {json_path}, {pq_path}")


if __name__ == "__main__":
    main()

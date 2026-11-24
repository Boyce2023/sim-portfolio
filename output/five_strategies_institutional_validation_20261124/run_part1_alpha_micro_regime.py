#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD024 Institutional Quantitative Validation - Pillars 1, 2 & 3
Pillar 1: 5-Factor Alpha Attribution (Newey-West HAC lag=5) & Matched Control
Pillar 2: Almgren-Chriss Capacity, Fill Stress, Adverse Selection & +5m/+15m Delay
Pillar 3: 4D Regime Matrix, Extreme Scenarios & Moving Block Bootstrap (10,000x)

Strict Rules:
- 100% read-only on production scripts, clean ledgers, parquets, and PIT SQLite (mode=ro).
- Zero yfinance imports (D12). Zero external network calls. Zero data fabrication.
"""
import os
import sys
import json
import math
import sqlite3
import pickle
import warnings
import numpy as np
import pandas as pd
import scipy.stats as stats
import statsmodels.api as sm

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
warnings.filterwarnings("ignore", category=FutureWarning)

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
LEDGER_DIR = f"{SIM}/backtests_astock/redteam_full_audit_20261123/partC_clean_ledgers_v191"
OUT_DIR = f"{SIM}/output/five_strategies_institutional_validation_20261124"
os.makedirs(OUT_DIR, exist_ok=True)

START_DATE = "2021-11-16"
END_DATE = "2026-11-16"
SEED = 20261124

LEDGERS = {
    "3to4_V41": "ledger_3to4_v41_clean.csv",
    "high_V51": "ledger_high_v51_clean.csv",
    "pry_V21_ss165": "ledger_pry_v21_ss165_clean.csv",
    "pry_V21_top1": "ledger_pry_v21_top1_clean.csv",
    "2to3_V21": "ledger_2to3_v21_opt_std90_clean.csv",
    "1to2_V19": "ledger_1to2_v19_clean.csv",
    "combined_V191": "ledger_combined_5strat_v191_slot1_clean.csv",
}

STRAT_POOL_MAP = {
    "三进四V4.1": "3to4_V41",
    "高标首阴V5.1": "high_V51",
    "超跌撬板V2.1": "pry_V21",
    "二进三V2.1": "2to3_V21",
    "一进二V19": "1to2_V19",
}


def load_calendar_and_csi300():
    idx_cache = json.load(
        open(f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json", encoding="utf-8")
    )
    sh300 = idx_cache["sh000300"]
    all_dts = sorted(sh300.keys())
    cal_dates = [d for d in all_dts if START_DATE <= d <= END_DATE]
    prev_dt = [d for d in all_dts if d < START_DATE][-1]
    px_series = [sh300[prev_dt]] + [sh300[d] for d in cal_dates]
    csi_rets = np.diff(px_series) / np.array(px_series[:-1], dtype=float)
    csi_s = pd.Series(csi_rets, index=cal_dates, name="CSI300")
    return cal_dates, sh300, csi_s


def load_daily_universe(cal_dates):
    print("[1/6] Loading active + delisted daily bars & building 10cm universe...")
    cols = [
        "date", "ticker", "open", "high", "low", "close",
        "adj_close", "volume", "amount", "oshare", "turn", "qfq_factor",
    ]
    dt_cut = pd.Timestamp("2021-09-01")
    dt_end = pd.Timestamp(END_DATE)
    da = pd.read_parquet(
        f"{SIM}/data/cn_hk_price_db/a_daily.parquet",
        columns=cols,
        filters=[("date", ">=", dt_cut), ("date", "<=", dt_end)],
    )
    dd = pd.read_parquet(
        f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet",
        columns=cols,
        filters=[("date", ">=", dt_cut), ("date", "<=", dt_end)],
    )
    df_all = pd.concat([da, dd], ignore_index=True)
    df_all["c6"] = df_all["ticker"].str[:6]
    df_all = df_all[~df_all["ticker"].str.endswith(".BJ")].copy()
    df_all["dt"] = df_all["date"].dt.strftime("%Y-%m-%d")
    df_all.sort_values(["c6", "dt"], inplace=True)
    df_all.drop_duplicates(["c6", "dt"], keep="first", inplace=True)

    # Total market daily turnover across all A-shares (Yuan) for regime amt_q60
    tot_amt = df_all.groupby("dt")["amount"].sum().sort_index()

    # Main board 10cm subset (00/60)
    df = df_all[df_all["c6"].str.startswith(("00", "60"))].copy()
    del df_all, da, dd

    df["adjf"] = np.where(df["close"] > 0, df["adj_close"] / df["close"], 1.0)
    g = df.groupby("c6", sort=False)
    df["prev_c_adj"] = g["close"].shift(1) * g["adjf"].shift(1) / df["adjf"]
    df["ret"] = df["adj_close"] / g["adj_close"].shift(1) - 1.0
    df["vol_m1"] = g["volume"].shift(1)

    # Circulating shares = oshare, fallback volume / turn
    shares = np.where(
        df["oshare"].notna() & (df["oshare"] > 0),
        df["oshare"],
        np.where(df["turn"] > 0, df["volume"] / df["turn"], np.nan),
    )
    df["mcap"] = df["close"] * shares
    df["mcap_m1"] = g["mcap"].shift(1)
    df["turn_m1"] = g["turn"].shift(1)
    df["vol20"] = g["ret"].transform(lambda s: s.rolling(20, min_periods=15).std())
    df["vol20_m1"] = g["vol20"].shift(1)
    df["turn20"] = g["turn"].transform(lambda s: s.rolling(20, min_periods=10).mean())
    df["turn20_m1"] = g["turn20"].shift(1)
    df["ma10"] = g["adj_close"].transform(lambda s: s.rolling(10, min_periods=10).mean())
    df["bias10"] = df["adj_close"] / df["ma10"] - 1.0
    df["bias10_m1"] = g["bias10"].shift(1)
    df["ret_m1"] = g["ret"].shift(1)
    df["open_m1"] = g["open"].shift(1)
    df["close_m1"] = g["close"].shift(1)

    df["zt_px"] = np.floor(df["prev_c_adj"] * 1.10 * 100.0 + 0.5) / 100.0
    df["dt_px"] = np.floor(df["prev_c_adj"] * 0.90 * 100.0 + 0.5) / 100.0
    df["is_zt"] = (df["close"] >= df["zt_px"] - 0.011) & (df["ret"] >= 0.095)
    df["hit_zt"] = (df["high"] >= df["zt_px"] - 0.011) & (df["prev_c_adj"] > 0)
    df["is_dt"] = (df["close"] <= df["dt_px"] + 0.011) & (df["ret"] <= -0.095)
    df["is_yizi_zt"] = df["is_zt"] & (df["open"] >= df["zt_px"] - 0.015) & (df["low"] >= df["zt_px"] - 0.015)
    df["is_yizi_dt"] = df["is_dt"] & (df["open"] <= df["dt_px"] + 0.015) & (df["high"] <= df["dt_px"] + 0.015)
    df["vwap"] = np.where(df["volume"] > 0, df["amount"] / df["volume"], df["close"])

    # Consecutive ZT streak
    zt_arr = df["is_zt"].to_numpy(dtype=np.int32)
    c6_arr = df["c6"].to_numpy()
    streak = np.zeros(len(df), dtype=np.int32)
    cur, prev_c = 0, ""
    for i in range(len(df)):
        if c6_arr[i] != prev_c:
            cur = 0
            prev_c = c6_arr[i]
        cur = cur + 1 if zt_arr[i] == 1 else 0
        streak[i] = cur
    df["board_cnt"] = streak
    df["board_cnt_m1"] = g["board_cnt"].shift(1)
    df["board_cnt_m2"] = g["board_cnt"].shift(2)
    df["is_dt_m1"] = g["is_dt"].shift(1)
    df["is_dt_m2"] = g["is_dt"].shift(2)
    df["is_dt_m3"] = g["is_dt"].shift(3)

    # ST flags (union st_universe snapshot + PIT zt_micro_tape ST/退 names)
    st_snap = set(json.load(open(f"{SIM}/data/st_universe.json", encoding="utf-8"))["codes"])
    conn = sqlite3.connect(f"file:{SIM}/data/zt_micro_tape_5y_pit.db?mode=ro", uri=True)
    zt_tape = pd.read_sql_query(
        "SELECT trade_date, sec_code, sec_name, first_seal_time, first_seal_ts, "
        "seal_amount, board_count, open_board_count "
        "FROM zt_micro_tape WHERE trade_date >= '2021-10-01' AND trade_date <= '2026-11-18'",
        conn,
    )
    conn.close()
    pit_st_codes = set(zt_tape[zt_tape["sec_name"].str.contains("ST|退", na=False)]["sec_code"].unique())
    st_all = st_snap | pit_st_codes
    df["is_st_flag"] = df["c6"].isin(st_all)

    return df, tot_amt, zt_tape


def build_5_factors(df, cal_dates, all_dts, zt_tape, csi_s):
    print("[2/6] Building 5 daily factors (2021-11-16..2026-11-16)...")
    dt_set = set(cal_dates)
    sub = df[df["dt"].isin(dt_set)].copy()

    # Cross-sectional valid mask on day t: non-ST, traded t & t-1, valid mcap_m1, no IPO/delisting no-limit artifact
    valid = (
        (~sub["is_st_flag"])
        & (sub["volume"] > 0)
        & (sub["vol_m1"] > 0)
        & sub["mcap_m1"].notna()
        & (sub["mcap_m1"] > 0)
        & sub["ret"].notna()
        & (sub["ret"].abs() <= 0.22)
    )
    sv = sub[valid].copy()

    # MKT (value-weighted & equal-weight)
    sv["w_ret"] = sv["mcap_m1"] * sv["ret"]
    g_dt = sv.groupby("dt")
    mkt_vw = (g_dt["w_ret"].sum() / g_dt["mcap_m1"].sum()).reindex(cal_dates)
    mkt_ew = g_dt["ret"].mean().reindex(cal_dates)

    # SMB: bottom 30% mcap_m1 EW minus top 30% mcap_m1 EW
    sv["mcap_pct"] = g_dt["mcap_m1"].rank(pct=True)
    smb = (
        sv[sv["mcap_pct"] <= 0.30].groupby("dt")["ret"].mean()
        - sv[sv["mcap_pct"] >= 0.70].groupby("dt")["ret"].mean()
    ).reindex(cal_dates)

    # VOL: top 30% vol20_m1 EW minus bottom 30% vol20_m1 EW
    sv_vol = sv[sv["vol20_m1"].notna() & (sv["vol20_m1"] > 0)].copy()
    sv_vol["vol_pct"] = sv_vol.groupby("dt")["vol20_m1"].rank(pct=True)
    vol_f = (
        sv_vol[sv_vol["vol_pct"] >= 0.70].groupby("dt")["ret"].mean()
        - sv_vol[sv_vol["vol_pct"] <= 0.30].groupby("dt")["ret"].mean()
    ).reindex(cal_dates)

    # LIQ: top 30% turn20_m1 EW minus bottom 30% turn20_m1 EW
    sv_liq = sv[sv["turn20_m1"].notna() & (sv["turn20_m1"] > 0)].copy()
    sv_liq["liq_pct"] = sv_liq.groupby("dt")["turn20_m1"].rank(pct=True)
    liq_f = (
        sv_liq[sv_liq["liq_pct"] >= 0.70].groupby("dt")["ret"].mean()
        - sv_liq[sv_liq["liq_pct"] <= 0.30].groupby("dt")["ret"].mean()
    ).reindex(cal_dates)

    # LIANBAN_BETA: t-1 non-ST 10cm >=2-board ZT next-day EW return (excess over MKT)
    # Build (prev_dt -> dt) lookup
    prev_map = {}
    for d in cal_dates:
        p = all_dts.index(d)
        prev_map[d] = all_dts[p - 1]

    zt_lb = zt_tape[
        zt_tape["sec_code"].str.startswith(("00", "60"))
        & (~zt_tape["sec_name"].str.contains("ST|退", na=False))
        & (zt_tape["board_count"] >= 2)
    ][["trade_date", "sec_code"]].drop_duplicates()

    # Map t-1 ZT trade_date -> target return date t
    rev_prev = {v: k for k, v in prev_map.items()}
    zt_lb["dt"] = zt_lb["trade_date"].map(rev_prev)
    zt_lb = zt_lb.dropna(subset=["dt"])
    ret_sub = sub[["c6", "dt", "ret", "volume"]].rename(columns={"c6": "sec_code"})
    lb_m = zt_lb.merge(ret_sub, on=["sec_code", "dt"], how="inner")
    lb_m = lb_m[lb_m["ret"].notna() & (lb_m["ret"].abs() <= 0.22)]
    lb_raw = lb_m.groupby("dt")["ret"].mean().reindex(cal_dates)
    # Fallback to board_cnt_m1 >= 2 if any day empty (though zt_micro_tape covered 1212/1212)
    if lb_raw.isna().any():
        fb = sub[(~sub["is_st_flag"]) & (sub["board_cnt_m1"] >= 2) & sub["ret"].notna()].groupby("dt")["ret"].mean()
        lb_raw = lb_raw.fillna(fb)
    lb_excess = lb_raw - mkt_vw

    # Tradable non-yizi intraday O2C LIANBAN factor & decomposition
    ret_o2c_df = sub[["c6", "dt", "ret", "open", "close", "is_yizi_zt", "volume"]].rename(columns={"c6": "sec_code"})
    lb_m2 = zt_lb.merge(ret_o2c_df, on=["sec_code", "dt"], how="inner")
    lb_m2 = lb_m2[lb_m2["ret"].notna() & (lb_m2["ret"].abs() <= 0.22) & (lb_m2["volume"] > 0) & (lb_m2["open"] > 0)]
    lb_m2["o2c"] = lb_m2["close"] / lb_m2["open"] - 1.0
    lb_non_yizi = lb_m2[~lb_m2["is_yizi_zt"]]
    lb_o2c_raw = lb_non_yizi.groupby("dt")["o2c"].mean().reindex(cal_dates).fillna(0.0)
    lb_o2c_excess = lb_o2c_raw - mkt_vw

    factors = pd.DataFrame({
        "MKT": mkt_vw,
        "SMB": smb,
        "VOL": vol_f,
        "LIQ": liq_f,
        "LIANBAN_BETA": lb_excess,
    }, index=cal_dates)
    assert not factors.isna().any().any(), f"NaN in factors: {factors.isna().sum().to_dict()}"

    extra = pd.DataFrame({
        "MKT_EW": mkt_ew,
        "CSI300": csi_s.reindex(cal_dates),
        "LIANBAN_RAW": lb_raw,
        "LIANBAN_O2C_RAW": lb_o2c_raw,
        "LIANBAN_O2C_EXCESS": lb_o2c_excess,
    }, index=cal_dates)

    # Summary stats
    fac_stats = {}
    for col in list(factors.columns) + list(extra.columns):
        s = factors[col] if col in factors.columns else extra[col]
        nav = float(np.prod(1.0 + s.to_numpy()))
        ann_ret = float(s.mean() * 252.0 * 100.0)
        ann_comp = float((nav ** (252.0 / len(s)) - 1.0) * 100.0)
        ann_vol = float(s.std(ddof=1) * math.sqrt(252.0) * 100.0)
        sr = float(s.mean() / s.std(ddof=1) * math.sqrt(252.0)) if s.std(ddof=1) > 0 else 0.0
        fac_stats[col] = {
            "nav_5y": round(nav, 4),
            "ann_ret_arith_pct": round(ann_ret, 2),
            "ann_ret_comp_pct": round(ann_comp, 2),
            "ann_vol_pct": round(ann_vol, 2),
            "sharpe": round(sr, 3),
        }
    corr_mat = {k: {k2: round(float(v2), 4) for k2, v2 in row.items()} for k, row in factors.corr().to_dict().items()}
    lb_decomp = {
        "n_stock_days": int(len(lb_m2)),
        "yizi_zt_pct": round(float(lb_m2["is_yizi_zt"].mean() * 100.0), 2),
        "all_c2c_mean_bps_day": round(float(lb_m2["ret"].mean() * 10000.0), 2),
        "non_yizi_o2c_mean_bps_day": round(float(lb_non_yizi["o2c"].mean() * 10000.0), 2),
        "note": "Raw C2C LIANBAN includes unbuyable overnight gaps & ~13% yizi_zt locked opens; non-yizi intraday O2C averages negative bps/day",
    }
    return factors, extra, {"stats": fac_stats, "corr": corr_mat, "lianban_decomp": lb_decomp}


def build_by_c_lookup(df):
    by_c = {}
    for c6, grp in df.groupby("c6", sort=False):
        g = grp.reset_index(drop=True)
        dt_list = g["dt"].tolist()
        by_c[c6] = {
            "dt": dt_list,
            "dt_to_pos": {d: i for i, d in enumerate(dt_list)},
            "open": g["open"].to_numpy(dtype=float),
            "high": g["high"].to_numpy(dtype=float),
            "low": g["low"].to_numpy(dtype=float),
            "close": g["close"].to_numpy(dtype=float),
            "adj_close": g["adj_close"].to_numpy(dtype=float),
            "adjf": g["adjf"].to_numpy(dtype=float),
            "qfq": g["qfq_factor"].to_numpy(dtype=float),
            "amount": g["amount"].to_numpy(dtype=float),
            "vol20_m1": g["vol20_m1"].to_numpy(dtype=float),
            "zt_px": g["zt_px"].to_numpy(dtype=float),
            "is_yizi_dt": g["is_yizi_dt"].to_numpy(dtype=bool),
            "volume": g["volume"].to_numpy(dtype=float),
            "vwap": g["vwap"].to_numpy(dtype=float),
        }
    return by_c


def compute_daily_mtm(led_df, by_c, cal_dates, allow_overlap=False):
    """Convert ledger trades to exact 1,212-day daily MTM returns (flat cash days = 0)."""
    dt_to_idx = {d: i for i, d in enumerate(cal_dates)}
    n_days = len(cal_dates)
    # Track per-day gross multiplier list for active slots
    day_trades = [[] for _ in range(n_days)]
    active_flag = np.zeros(n_days, dtype=bool)
    trade_spans = []

    for r in led_df.itertuples(index=False):
        c6 = r.c6
        b_dt, e_dt = r.buy_date, r.exit_date
        b_px, e_px = float(r.buy_price), float(r.exit_price)
        net_ret = float(r.net_ret)
        bar = by_c[c6]
        p0 = bar["dt_to_pos"][b_dt]
        pe = bar["dt_to_pos"][e_dt]
        assert pe > p0, f"T+0 violation: {c6} {b_dt} -> {e_dt}"

        b_adj = b_px * bar["adjf"][p0]
        e_adj = e_px * bar["adjf"][pe]
        # Build gross daily multipliers across [p0 .. pe]
        factors_g = []
        idx_days = []
        for k in range(p0, pe + 1):
            dk = bar["dt"][k]
            idx_d = dt_to_idx[dk]
            idx_days.append(idx_d)
            if k == p0:
                gf = bar["adj_close"][k] / b_adj
            elif k < pe:
                gf = bar["adj_close"][k] / bar["adj_close"][k - 1]
            else:
                gf = e_adj / bar["adj_close"][k - 1]
            factors_g.append(gf)

        prod_gross = float(np.prod(factors_g))
        target_mult = 1.0 + net_ret
        # Split cost/rounding residual equally on entry and exit days so product == 1 + net_ret exactly
        scale = math.sqrt(target_mult / prod_gross) if prod_gross > 0 else 1.0
        factors_g[0] *= scale
        factors_g[-1] *= scale

        for d_idx, mult in zip(idx_days, factors_g):
            active_flag[d_idx] = True
            day_trades[d_idx].append(mult)
        trade_spans.append((idx_days[0], idx_days[-1]))

    daily_ret = np.zeros(n_days, dtype=float)
    for t in range(n_days):
        if not day_trades[t]:
            daily_ret[t] = 0.0
        elif len(day_trades[t]) == 1:
            daily_ret[t] = day_trades[t][0] - 1.0
        else:
            if allow_overlap:
                # Multi-slot overlap (e.g. pry_V21_top1): equal weight across active positions
                daily_ret[t] = float(np.mean(day_trades[t])) - 1.0
            else:
                # Single-slot same-day exit then re-entry: sequential compounding on day t
                m = 1.0
                for x in day_trades[t]:
                    m *= x
                daily_ret[t] = m - 1.0

    nav_mtm = float(np.prod(1.0 + daily_ret))
    nav_led = float(np.prod(1.0 + led_df["net_ret"].to_numpy(dtype=float)))
    if not allow_overlap:
        rel_err = abs(nav_mtm / nav_led - 1.0)
        assert rel_err < 1e-4, f"MTM mismatch: mtm={nav_mtm}, led={nav_led}, err={rel_err}"

    return pd.Series(daily_ret, index=cal_dates), active_flag, nav_mtm, nav_led


def fit_hac_ols(y, X, maxlags=5):
    X_c = sm.add_constant(X, has_constant="add")
    res = sm.OLS(y, X_c).fit(cov_type="HAC", cov_kwds={"maxlags": maxlags})
    alpha_d = float(res.params["const"])
    se_d = float(res.bse["const"])
    t_a = float(res.tvalues["const"])
    p_a = float(res.pvalues["const"])
    betas = {}
    for col in X.columns:
        betas[col] = {
            "beta": round(float(res.params[col]), 4),
            "nw_t": round(float(res.tvalues[col]), 3),
            "nw_p": round(float(res.pvalues[col]), 4),
        }
    return {
        "n_obs": int(len(y)),
        "alpha_daily_bps": round(alpha_d * 10000.0, 2),
        "alpha_ann_pct": round(alpha_d * 252.0 * 100.0, 2),
        "alpha_ann_comp_pct": round((((1.0 + alpha_d) ** 252.0) - 1.0) * 100.0 if (1.0 + alpha_d) > 0 else -100.0, 2),
        "nw_se_bps": round(se_d * 10000.0, 2),
        "nw_t": round(t_a, 3),
        "nw_p": round(p_a, 6),
        "r2": round(float(res.rsquared), 4),
        "adj_r2": round(float(res.rsquared_adj), 4),
        "factors": betas,
    }


def run_pillar1_regressions(strat_key, led_df, daily_s, active_flag, factors, extra, cal_dates):
    y = daily_s.to_numpy(dtype=float)
    full_hac = fit_hac_ols(y, factors, maxlags=5)

    # CSI300 sensitivity
    f_csi = factors.copy()
    f_csi["MKT"] = extra["CSI300"]
    csi_sens = fit_hac_ols(y, f_csi, maxlags=5)

    # 4-factor tradable sensitivity (excluding non-tradable C2C LIANBAN_BETA)
    f_4fac = factors[["MKT", "SMB", "VOL", "LIQ"]]
    hac_4fac = fit_hac_ols(y, f_4fac, maxlags=5)

    # 5-factor with tradable non-yizi O2C LIANBAN_BETA
    f_o2c = factors.copy()
    f_o2c["LIANBAN_BETA"] = extra["LIANBAN_O2C_EXCESS"]
    hac_o2c = fit_hac_ols(y, f_o2c, maxlags=5)

    # Active days only daily HAC
    y_act = y[active_flag]
    f_act = factors.iloc[active_flag]
    active_hac = fit_hac_ols(y_act, f_act, maxlags=min(5, max(1, len(y_act) // 10)))

    # Trade-level holding-period 5-factor regression
    dt_to_idx = {d: i for i, d in enumerate(cal_dates)}
    f_arr = factors.to_numpy(dtype=float)
    tr_f_rows = []
    for r in led_df.itertuples(index=False):
        i0 = dt_to_idx[r.buy_date]
        i1 = dt_to_idx[r.exit_date]
        seg = f_arr[i0 : i1 + 1]
        comp = np.prod(1.0 + seg, axis=0) - 1.0
        tr_f_rows.append(comp)
    X_tr = pd.DataFrame(tr_f_rows, columns=factors.columns)
    y_tr = led_df["net_ret"].to_numpy(dtype=float)
    X_tr_c = sm.add_constant(X_tr, has_constant="add")
    res_tr = sm.OLS(y_tr, X_tr_c).fit(cov_type="HC3")
    tr_betas = {
        col: {
            "beta": round(float(res_tr.params[col]), 4),
            "hc3_t": round(float(res_tr.tvalues[col]), 3),
            "hc3_p": round(float(res_tr.pvalues[col]), 4),
        }
        for col in X_tr.columns
    }
    trade_level = {
        "n_trades": int(len(y_tr)),
        "alpha_per_trade_pct": round(float(res_tr.params["const"]) * 100.0, 3),
        "hc3_t": round(float(res_tr.tvalues["const"]), 3),
        "hc3_p": round(float(res_tr.pvalues["const"]), 6),
        "r2": round(float(res_tr.rsquared), 4),
        "factors": tr_betas,
    }

    return {
        "full_5y_daily_hac": full_hac,
        "full_5y_csi300_sensitivity": {
            "alpha_ann_pct": csi_sens["alpha_ann_pct"],
            "alpha_daily_bps": csi_sens["alpha_daily_bps"],
            "nw_t": csi_sens["nw_t"],
            "nw_p": csi_sens["nw_p"],
            "r2": csi_sens["r2"],
        },
        "full_5y_4factor_tradable_hac": hac_4fac,
        "full_5y_o2c_lianban_hac": {
            "alpha_ann_pct": hac_o2c["alpha_ann_pct"],
            "alpha_daily_bps": hac_o2c["alpha_daily_bps"],
            "nw_t": hac_o2c["nw_t"],
            "nw_p": hac_o2c["nw_p"],
            "r2": hac_o2c["r2"],
            "beta_lb_o2c": hac_o2c["factors"]["LIANBAN_BETA"],
        },
        "active_days_daily_hac": active_hac,
        "trade_level_hc3": trade_level,
    }


def prepare_matched_pools(df, cal_dates):
    print("[3/6] Precomputing ecological matched-control pools...")
    dt_set = set(cal_dates)
    sub = df[
        df["dt"].isin(dt_set)
        & (~df["is_st_flag"])
        & (df["volume"] > 0)
        & (df["vol_m1"] > 0)
        & df["mcap_m1"].notna()
        & (df["mcap_m1"] > 0)
        & df["turn_m1"].notna()
        & (df["turn_m1"] > 0)
    ].copy()

    # Cross-sectional quartiles on t-1 mcap & t-1 turnover
    sub["mcap_q"] = sub.groupby("dt")["mcap_m1"].transform(
        lambda s: pd.qcut(s.rank(method="first"), 4, labels=[1, 2, 3, 4]).astype(int)
    )
    sub["turn_q"] = sub.groupby("dt")["turn_m1"].transform(
        lambda s: pd.qcut(s.rank(method="first"), 4, labels=[1, 2, 3, 4]).astype(int)
    )

    buyable = ~sub["is_yizi_zt"]
    sub_b = sub[buyable].copy()

    # Ecological masks on buy_date t (using t-1/t-2 info only)
    masks = {
        "1to2_V19": sub_b["board_cnt_m1"] == 1,
        "2to3_V21": sub_b["board_cnt_m1"] == 2,
        "3to4_V41": sub_b["board_cnt_m1"] == 3,
        "high_V51": (sub_b["board_cnt_m2"] >= 4) & (sub_b["board_cnt_m1"] == 0) & (sub_b["close_m1"] >= sub_b["open_m1"]),
        "high_V51_fb": (sub_b["board_cnt_m2"] >= 3) & (sub_b["board_cnt_m1"] == 0) & (sub_b["close_m1"] >= sub_b["open_m1"]),
        "high_V51_fb2": (sub_b["board_cnt_m2"] >= 2) & (sub_b["board_cnt_m1"] == 0),
        "pry_V21": (sub_b["bias10_m1"] <= -0.15) & (
            sub_b["is_dt_m1"].fillna(False)
            | sub_b["is_dt_m2"].fillna(False)
            | sub_b["is_dt_m3"].fillna(False)
            | (sub_b["ret_m1"] <= -0.05)
        ),
        "pry_V21_fb": (sub_b["bias10_m1"] <= -0.10) & (sub_b["ret_m1"] <= -0.03),
    }

    pool_by_dt = {}
    for pk, m in masks.items():
        d_map = {}
        for dt, grp in sub_b[m].groupby("dt", sort=False):
            d_map[dt] = list(zip(grp["c6"].tolist(), grp["mcap_q"].tolist(), grp["turn_q"].tolist()))
        pool_by_dt[pk] = d_map

    # Target stock quartiles lookup
    q_lookup = {}
    for r in sub[["c6", "dt", "mcap_q", "turn_q"]].itertuples(index=False):
        q_lookup[(r.c6, r.dt)] = (int(r.mcap_q), int(r.turn_q))

    return pool_by_dt, q_lookup


def peer_hold_return(c6, b_dt, e_dt, b_hhmm, e_hhmm, by_c, entry_mode="matched_timing"):
    bar = by_c.get(c6)
    if bar is None:
        return None
    p0 = bar["dt_to_pos"].get(b_dt)
    pe = bar["dt_to_pos"].get(e_dt)
    if p0 is None:
        return None
    if pe is None:
        # Find first trading date >= e_dt
        pe_cand = next((i for i, d in enumerate(bar["dt"]) if d >= e_dt), None)
        if pe_cand is None or pe_cand <= p0:
            return None
        pe = pe_cand

    if entry_mode == "open":
        b_px = bar["open"][p0]
    else:
        b_px = bar["open"][p0] if int(b_hhmm) == 925 else bar["vwap"][p0]
    if b_px <= 0 or np.isnan(b_px):
        return None

    # Physical exit deferral if suspended or locked limit-down at 15:00
    if int(e_hhmm) == 925 and not bar["is_yizi_dt"][pe] and bar["volume"][pe] > 0:
        e_px = bar["open"][pe]
    elif int(e_hhmm) > 925 and not bar["is_yizi_dt"][pe] and bar["volume"][pe] > 0 and bar["close"][pe] > 0:
        # Check exact 15:00 limit-down (is_yizi_dt or close == dt_px)
        e_px = bar["close"][pe]
    else:
        k = pe + 1
        while k < len(bar["dt"]) - 1 and (bar["is_yizi_dt"][k] or bar["volume"][k] <= 0):
            k += 1
        if k >= len(bar["dt"]):
            k = pe
        e_px = bar["open"][k] if bar["volume"][k] > 0 else bar["close"][k]

    if e_px <= 0 or np.isnan(e_px):
        return None
    return (e_px / b_px) * (bar["qfq"][p0] / bar["qfq"][pe]) * 0.9980 - 1.0


def run_matched_control(strat_key, led_df, pool_by_dt, q_lookup, by_c):
    rng = np.random.default_rng(SEED)
    tier_counts = {1: 0, 2: 0, 3: 0, 4: 0, "unmatched": 0}
    strat_rets, peer_means, peer_open_means = [], [], []
    peer_lists_for_mc = []

    base_pk = "pry_V21" if strat_key.startswith("pry_V21") else strat_key

    for r in led_df.itertuples(index=False):
        c6, b_dt, e_dt = r.c6, r.buy_date, r.exit_date
        b_hhmm, e_hhmm = int(r.buy_hhmm), int(r.exit_hhmm)
        pk = STRAT_POOL_MAP[r.strategy] if strat_key == "combined_V191" else base_pk

        mq, tq = q_lookup.get((c6, b_dt), (None, None))
        cands_all = [x for x in pool_by_dt[pk].get(b_dt, []) if x[0] != c6]

        tier = None
        selected = []
        if mq is not None:
            t1 = [x[0] for x in cands_all if x[1] == mq and x[2] == tq]
            t2 = [x[0] for x in cands_all if x[1] == mq]
            if t1:
                selected, tier = t1, 1
            elif t2:
                selected, tier = t2, 2
        if not selected and cands_all:
            selected, tier = [x[0] for x in cands_all], 3
        if not selected:
            # Tier 4 fallback
            fb_keys = []
            if pk == "high_V51":
                fb_keys = ["high_V51_fb", "high_V51_fb2", "3to4_V41"]
            elif pk == "pry_V21":
                fb_keys = ["pry_V21_fb"]
            elif pk == "3to4_V41":
                fb_keys = ["2to3_V21", "1to2_V19"]
            elif pk == "2to3_V21":
                fb_keys = ["1to2_V19", "3to4_V41"]
            elif pk == "1to2_V19":
                fb_keys = ["2to3_V21"]
            for fk in fb_keys:
                fc = [x[0] for x in pool_by_dt[fk].get(b_dt, []) if x[0] != c6]
                if fc:
                    selected, tier = fc, 4
                    break

        if not selected:
            tier_counts["unmatched"] += 1
            continue

        prets, prets_open = [], []
        for pc in selected:
            pr = peer_hold_return(pc, b_dt, e_dt, b_hhmm, e_hhmm, by_c, entry_mode="matched_timing")
            pr_o = peer_hold_return(pc, b_dt, e_dt, b_hhmm, e_hhmm, by_c, entry_mode="open")
            if pr is not None:
                prets.append(pr)
            if pr_o is not None:
                prets_open.append(pr_o)

        if not prets:
            tier_counts["unmatched"] += 1
            continue

        tier_counts[tier] += 1
        strat_rets.append(float(r.net_ret))
        peer_means.append(float(np.mean(prets)))
        peer_open_means.append(float(np.mean(prets_open)) if prets_open else float(np.mean(prets)))
        peer_lists_for_mc.append(np.array(prets, dtype=float))

    sr = np.array(strat_rets, dtype=float)
    pm = np.array(peer_means, dtype=float)
    pm_o = np.array(peer_open_means, dtype=float)
    diff = sr - pm
    t_stat, p_val = stats.ttest_rel(sr, pm) if len(sr) > 1 else (0.0, 1.0)
    try:
        _, w_p = stats.wilcoxon(diff) if len(sr) >= 5 else (0.0, 1.0)
    except Exception:
        w_p = 1.0

    # 1,000-seed single-peer random draw Monte Carlo
    mc_ex, mc_sig = [], []
    if len(peer_lists_for_mc) > 1:
        for _ in range(1000):
            draw = np.array([arr[rng.integers(0, len(arr))] for arr in peer_lists_for_mc])
            d_mc = sr - draw
            mc_ex.append(float(np.mean(d_mc) * 100.0))
            _, pmc = stats.ttest_rel(sr, draw)
            mc_sig.append(pmc < 0.05)

    return {
        "n_total": int(len(led_df)),
        "n_matched": int(len(sr)),
        "tier_counts": {str(k): int(v) for k, v in tier_counts.items()},
        "strat_avg_ret_pct": round(float(sr.mean() * 100.0), 3),
        "matched_avg_ret_pct": round(float(pm.mean() * 100.0), 3),
        "matched_open_avg_ret_pct": round(float(pm_o.mean() * 100.0), 3),
        "excess_over_matched_pct": round(float(diff.mean() * 100.0), 3),
        "excess_median_pct": round(float(np.median(diff) * 100.0), 3),
        "strat_wr_pct": round(float((sr > 0).mean() * 100.0), 2),
        "matched_wr_pct": round(float((pm > 0).mean() * 100.0), 2),
        "wr_diff_pp": round(float(((sr > 0).mean() - (pm > 0).mean()) * 100.0), 2),
        "paired_t": round(float(t_stat), 3),
        "paired_p": round(float(p_val), 6),
        "wilcoxon_p": round(float(w_p), 6),
        "mc_1draw_1000_excess_med_pct": round(float(np.median(mc_ex)), 3) if mc_ex else None,
        "mc_1draw_1000_sig05_rate_pct": round(float(np.mean(mc_sig) * 100.0), 1) if mc_sig else None,
    }


def load_targeted_5m_bars(target_pairs):
    print("[4/6] Loading targeted local 5m bars (verifying 1m=MISSING_LOCAL_DATA)...")
    bars_5m = {}
    need = set(target_pairs)

    def _add_df(df_sub):
        if df_sub.empty:
            return
        df_sub = df_sub.copy()
        df_sub["c6"] = df_sub["c6"].astype(str).str.zfill(6)
        df_sub["date"] = df_sub["date"].astype(str).str.slice(0, 10)
        df_sub["pair"] = list(zip(df_sub["c6"], df_sub["date"]))
        df_sub = df_sub[df_sub["pair"].isin(need)]
        if df_sub.empty:
            return
        df_sub.sort_values(["c6", "date", "hhmm_int"], inplace=True)
        for pair, grp in df_sub.groupby("pair", sort=False):
            if pair not in bars_5m and len(grp) > 0:
                bars_5m[pair] = grp[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float)

    for pq_p in [
        f"{SIM}/data/all_strategies_5m_complete_pit.parquet",
        f"{SIM}/backtests_astock2/data_5y/cand_3to4_5m_bars.parquet",
        f"{SIM}/data/cand_5m_bars_v15_complete.parquet",
        f"{SIM}/backtests_astock/ablation_1to2_price60_20261119/gt60_5m_patch.parquet",
    ]:
        if len(bars_5m) == len(need):
            break
        if os.path.exists(pq_p):
            d = pd.read_parquet(pq_p, columns=["c6", "date", "hhmm_int", "open", "high", "low", "close", "volume", "amount"])
            _add_df(d)

    # Check pkl caches if any still missing
    rem = need - set(bars_5m.keys())
    if rem:
        for pkp, mode in [
            (f"{SIM}/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113/sub2_5m_bars_cache.pkl", "sub2"),
            (f"{SIM}/backtests_astock/_archive/20261118_wave1_static_exit_opt/s2_2to3_exit/_cache_2to3_pit_20261116.pkl", "b5m"),
            (f"{SIM}/backtests_astock/_archive/20261118_wave1_static_exit_opt/s2_2to3_exit/_cache_5m_supplement_bs.pkl", "supp"),
        ]:
            if not os.path.exists(pkp) or not rem:
                continue
            obj = pickle.load(open(pkp, "rb"))
            src = obj if mode == "sub2" else obj["b5m_need"] if mode == "b5m" else obj["supp_5m"]
            for k, v in src.items():
                if not isinstance(v, pd.DataFrame) or v.empty:
                    continue
                pair = (str(k[0]).zfill(6), str(k[2] if mode == "sub2" else k[1])[:10])
                if pair in rem and pair not in bars_5m:
                    sub = v[v["date"].astype(str).str.slice(0, 10) == pair[1]].copy() if "date" in v.columns else v.copy()
                    if not sub.empty:
                        if "hhmm_int" not in sub.columns:
                            sub["hhmm_int"] = sub["hhmm"].astype(str).str.replace(":", "").astype(int)
                        sub.sort_values("hhmm_int", inplace=True)
                        bars_5m[pair] = sub[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float)
            rem = need - set(bars_5m.keys())

    if rem:
        dbp = f"{SIM}/backtests_astock2/data_5y/firstboard_5m_5y_pit.db"
        if os.path.exists(dbp):
            conn = sqlite3.connect(f"file:{dbp}?mode=ro", uri=True)
            codes_sql = ",".join(f"'{c}'" for c in sorted(set(p[0] for p in rem)))
            q_df = pd.read_sql_query(
                f"SELECT sec_code as c6, substr(bar_time,1,10) as date, "
                f"CAST(substr(bar_time,12,2)||substr(bar_time,15,2) AS INTEGER) as hhmm_int, "
                f"open, high, low, close, volume, amount FROM firstboard_5m_kline "
                f"WHERE sec_code IN ({codes_sql})",
                conn,
            )
            conn.close()
            _add_df(q_df)

    return bars_5m


def eval_ac_metrics(trade_items, daily_base_mults, n_days, allow_overlap, Q, Y):
    """Evaluate exact daily MTM NAV, CAGR, Sharpe with Almgren-Chriss impact at ticket size Q."""
    day_mults = [list(x) for x in daily_base_mults]
    imp_rts = []
    adj_trade_rets = []
    for it in trade_items:
        imp_b = min(0.95, Y * it["sig_b"] * math.sqrt(Q / it["v_b"])) if it["v_b"] > 0 else 0.95
        imp_e = min(0.95, Y * it["sig_e"] * math.sqrt(Q / it["v_e"])) if it["v_e"] > 0 else 0.95
        day_mults[it["d0"]][it["pos0"]] *= (1.0 - imp_b)
        day_mults[it["dk"]][it["posk"]] *= (1.0 - imp_e)
        imp_rts.append((1.0 - (1.0 - imp_b) * (1.0 - imp_e)) * 10000.0)
        adj_trade_rets.append((1.0 + it["net_ret"]) * (1.0 - imp_b) * (1.0 - imp_e) - 1.0)

    dr = np.zeros(n_days, dtype=float)
    for t in range(n_days):
        lst = day_mults[t]
        if not lst:
            dr[t] = 0.0
        elif len(lst) == 1:
            dr[t] = lst[0] - 1.0
        elif allow_overlap:
            dr[t] = float(np.mean(lst)) - 1.0
        else:
            m = 1.0
            for x in lst:
                m *= x
            dr[t] = m - 1.0

    nav = float(np.prod(1.0 + dr))
    cagr = ((nav ** (252.0 / n_days)) - 1.0) * 100.0 if nav > 0 else -100.0
    sd = float(dr.std(ddof=1))
    sr = float(dr.mean() / sd * math.sqrt(252.0)) if sd > 0 else 0.0
    return {
        "nav_5y": nav,
        "cagr_pct": cagr,
        "sharpe": sr,
        "avg_trade_ret_pct": float(np.mean(adj_trade_rets) * 100.0),
        "avg_rt_impact_bps": float(np.mean(imp_rts)),
    }


def bisect_capacity(fn_val, target, lo=1e4, hi=1e12, tol_rel=1e-4):
    v_lo = fn_val(lo)
    if v_lo <= target:
        return round(lo / 1e4, 2)
    while fn_val(hi) > target and hi < 1e14:
        hi *= 10.0
    if fn_val(hi) > target:
        return None
    for _ in range(60):
        mid = math.sqrt(lo * hi)
        if fn_val(mid) > target:
            lo = mid
        else:
            hi = mid
        if (hi - lo) / max(lo, 1.0) < tol_rel:
            break
    return round(math.sqrt(lo * hi) / 1e4, 2)


def run_pillar2(strat_key, led_df, by_c, cal_dates, bars_5m, zt_tape, allow_overlap=False):
    dt_to_idx = {d: i for i, d in enumerate(cal_dates)}
    n_days = len(cal_dates)

    # Precompute daily_base_mults & trade impact metadata
    day_base = [[] for _ in range(n_days)]
    trade_items = []
    for r in led_df.itertuples(index=False):
        bar = by_c[r.c6]
        p0, pe = bar["dt_to_pos"][r.buy_date], bar["dt_to_pos"][r.exit_date]
        b_adj = float(r.buy_price) * bar["adjf"][p0]
        e_adj = float(r.exit_price) * bar["adjf"][pe]
        gfs, idxs = [], []
        for k in range(p0, pe + 1):
            idxs.append(dt_to_idx[bar["dt"][k]])
            if k == p0:
                gfs.append(bar["adj_close"][k] / b_adj)
            elif k < pe:
                gfs.append(bar["adj_close"][k] / bar["adj_close"][k - 1])
            else:
                gfs.append(e_adj / bar["adj_close"][k - 1])
        pg = float(np.prod(gfs))
        sc = math.sqrt((1.0 + float(r.net_ret)) / pg) if pg > 0 else 1.0
        gfs[0] *= sc
        gfs[-1] *= sc
        pos_list = []
        for d_idx, mult in zip(idxs, gfs):
            pos_list.append((d_idx, len(day_base[d_idx])))
            day_base[d_idx].append(mult)

        sig_b = bar["vol20_m1"][p0]
        sig_e = bar["vol20_m1"][pe]
        sig_b = 0.04 if (np.isnan(sig_b) or sig_b <= 0) else float(sig_b)
        sig_e = 0.04 if (np.isnan(sig_e) or sig_e <= 0) else float(sig_e)
        v_b = float(bar["amount"][p0])
        v_e = float(bar["amount"][pe])
        trade_items.append({
            "d0": pos_list[0][0], "pos0": pos_list[0][1],
            "dk": pos_list[-1][0], "posk": pos_list[-1][1],
            "sig_b": sig_b, "sig_e": sig_e, "v_b": v_b, "v_e": v_e,
            "net_ret": float(r.net_ret),
        })

    # 1. Almgren-Chriss grid & bisection for Y=0.50 and Y=0.70
    q_grid = [1e6, 3e6, 5e6, 1e7, 2e7, 5e7, 1e8]
    ac_results = {}
    base_0 = eval_ac_metrics(trade_items, day_base, n_days, allow_overlap, Q=0.0, Y=0.50)
    for Y in (0.50, 0.70):
        grid_out = {}
        for Q in q_grid:
            m = eval_ac_metrics(trade_items, day_base, n_days, allow_overlap, Q=Q, Y=Y)
            q_lbl = f"{int(Q // 1e4)}w"
            grid_out[q_lbl] = {
                "nav_5y": round(m["nav_5y"], 4),
                "cagr_pct": round(m["cagr_pct"], 2),
                "sharpe": round(m["sharpe"], 3),
                "avg_trade_ret_pct": round(m["avg_trade_ret_pct"], 3),
                "avg_rt_impact_bps": round(m["avg_rt_impact_bps"], 1),
            }
        be_cap = bisect_capacity(
            lambda q: eval_ac_metrics(trade_items, day_base, n_days, allow_overlap, q, Y)["nav_5y"],
            1.0,
        )
        half_cagr_cap = bisect_capacity(
            lambda q: eval_ac_metrics(trade_items, day_base, n_days, allow_overlap, q, Y)["cagr_pct"],
            0.5 * base_0["cagr_pct"],
        )
        half_prof_cap = bisect_capacity(
            lambda q: eval_ac_metrics(trade_items, day_base, n_days, allow_overlap, q, Y)["nav_5y"] - 1.0,
            0.5 * (base_0["nav_5y"] - 1.0),
        )
        ac_results[f"Y_{Y:.2f}"] = {
            "grid": grid_out,
            "breakeven_cap_wan": be_cap,
            "half_cagr_cap_wan": half_cagr_cap,
            "half_simple_profit_cap_wan": half_prof_cap,
        }

    # Dynamic compounding sensitivity (Q_t = Q_0 * NAV_{t-1}, Y=0.50, uncapped vs 10M cap)
    dyn_comp = {}
    for q0 in (1e6, 5e6):
        for cap_val in (None, 1e7):
            nav_cur = 1.0
            for it in trade_items:
                q_t = q0 * nav_cur if cap_val is None else min(cap_val, q0 * nav_cur)
                ib = min(0.95, 0.50 * it["sig_b"] * math.sqrt(q_t / it["v_b"])) if it["v_b"] > 0 else 0.95
                ie = min(0.95, 0.50 * it["sig_e"] * math.sqrt(q_t / it["v_e"])) if it["v_e"] > 0 else 0.95
                r_adj = (1.0 + it["net_ret"]) * (1.0 - ib) * (1.0 - ie) - 1.0
                nav_cur *= (1.0 + r_adj)
            lbl = f"q0_{int(q0//1e4)}w_{'uncapped' if cap_val is None else 'cap1000w'}"
            dyn_comp[lbl] = round(nav_cur, 4)

    # 2. Random Fill Stress (50% / 70%, 2000 trials)
    rng = np.random.default_rng(SEED)
    rets_arr = led_df["net_ret"].to_numpy(dtype=float)
    n_tr = len(rets_arr)
    fill_stress = {}
    for p_fill in (0.50, 0.70):
        masks = rng.random((2000, n_tr)) < p_fill
        mults = np.where(masks, 1.0 + rets_arr[None, :], 1.0)
        paths = np.concatenate([np.ones((2000, 1)), np.cumprod(mults, axis=1)], axis=1)
        term_navs = paths[:, -1]
        cagrs = ((term_navs ** (252.0 / n_days)) - 1.0) * 100.0
        dds = 1.0 - paths / np.maximum.accumulate(paths, axis=1)
        mdds = dds.max(axis=1) * 100.0
        fill_stress[f"fill_{int(p_fill*100)}pct"] = {
            "nav_5y_median": round(float(np.median(term_navs)), 4),
            "nav_5y_p05": round(float(np.quantile(term_navs, 0.05)), 4),
            "nav_5y_p95": round(float(np.quantile(term_navs, 0.95)), 4),
            "cagr_median_pct": round(float(np.median(cagrs)), 2),
            "cagr_p05_pct": round(float(np.quantile(cagrs, 0.05)), 2),
            "mdd_median_pct": round(float(np.median(mdds)), 2),
            "mdd_p95_pct": round(float(np.quantile(mdds, 0.95)), 2),
        }

    # 3. Adverse Selection (Trim Top 10% & Top 20% by net_ret + by ZT seal strength)
    seal_map = {}
    for zr in zt_tape.itertuples(index=False):
        seal_map[(zr.sec_code, zr.trade_date)] = (int(zr.first_seal_ts or 9999999999), -float(zr.seal_amount or 0.0))

    def _trim_stats(keep_mask):
        sub_r = rets_arr[keep_mask]
        nav = float(np.prod(1.0 + sub_r)) if len(sub_r) > 0 else 1.0
        return {
            "n_rem": int(len(sub_r)),
            "n_dropped": int(n_tr - len(sub_r)),
            "wr_pct": round(float((sub_r > 0).mean() * 100.0), 2) if len(sub_r) else 0.0,
            "avg_ret_pct": round(float(sub_r.mean() * 100.0), 3) if len(sub_r) else 0.0,
            "nav_5y": round(nav, 4),
        }

    # Sort indices for return trim and seal strength trim
    idx_ret_desc = np.argsort(-rets_arr, kind="mergesort")
    seal_keys = []
    seal_cov = 0
    for r in led_df.itertuples(index=False):
        # Check buy_date ZT first (strongest seal on entry day), else t-1 ZT
        bar = by_c[r.c6]
        p0 = bar["dt_to_pos"][r.buy_date]
        dt_m1 = bar["dt"][p0 - 1] if p0 > 0 else r.buy_date
        sk = seal_map.get((r.c6, r.buy_date)) or seal_map.get((r.c6, dt_m1))
        if sk is not None:
            seal_cov += 1
            # Normalize time-of-day within trade_date: smaller (ts - day_start) or higher seal_amount = stronger
            seal_keys.append((0, sk[1]))  # highest seal_amount = hardest queue
        else:
            seal_keys.append((1, -float(r.net_ret)))
    idx_seal_desc = sorted(range(n_tr), key=lambda i: seal_keys[i])

    adverse = {"by_net_ret": {}, "by_seal_amount_queue_proxy": {"seal_tape_cov": f"{seal_cov}/{n_tr}"}}
    for pct in (10, 20):
        k_drop = max(1, int(round(n_tr * pct / 100.0)))
        m_ret = np.ones(n_tr, dtype=bool)
        m_ret[idx_ret_desc[:k_drop]] = False
        adverse["by_net_ret"][f"drop_top_{pct}pct"] = _trim_stats(m_ret)

        m_seal = np.ones(n_tr, dtype=bool)
        m_seal[idx_seal_desc[:k_drop]] = False
        adverse["by_seal_amount_queue_proxy"][f"drop_top_{pct}pct"] = _trim_stats(m_seal)

    # 4. Entry Delay (+5m / +15m via 5m bars; 1m = MISSING_LOCAL_DATA)
    delay_out = {
        "delay_1m": "MISSING_LOCAL_DATA (本地无任何A股1分钟K线数据，仅存5分钟K线)",
        "five_m_buy_coverage_count": 0,
        "five_m_total_trades": n_tr,
        "five_m_buy_coverage_pct": 0.0,
    }
    cov_flags = []
    for r in led_df.itertuples(index=False):
        cov_flags.append((r.c6, r.buy_date) in bars_5m)
    n_cov = int(sum(cov_flags))
    delay_out["five_m_buy_coverage_count"] = n_cov
    delay_out["five_m_buy_coverage_pct"] = round(n_cov / n_tr * 100.0, 1) if n_tr else 0.0
    delay_out["five_m_data_status"] = (
        "COMPLETE_100PCT" if n_cov == n_tr else f"PARTIAL_LOCAL_5M_DATA ({n_cov}/{n_tr})"
    )

    for step_lbl, shift_bars in (("plus_5m", 1), ("plus_15m", 3)):
        # For buy_hhmm == 925: +5m = bar idx 0 (09:35), +15m = bar idx 2 (09:45)
        rets_cov_zero, rets_cov_skip = [], []
        rets_full_zero, rets_full_skip = [], []
        rets_base_cov = []
        n_missed_close_zt, n_missed_strict_low_zt = 0, 0
        for r in led_df.itertuples(index=False):
            arr = bars_5m.get((r.c6, r.buy_date))
            if arr is None or len(arr) == 0:
                # Uncovered: cannot simulate 5m delay
                rets_full_zero.append(float(r.net_ret))
                rets_full_skip.append(float(r.net_ret))
                continue
            rets_base_cov.append(float(r.net_ret))
            bar_d = by_c[r.c6]
            p0 = bar_d["dt_to_pos"][r.buy_date]
            pe = bar_d["dt_to_pos"][r.exit_date]
            zt_px = float(bar_d["zt_px"][p0])
            b_hhmm = int(r.buy_hhmm)

            hh_arr = arr[:, 0].astype(int)
            if b_hhmm <= 925:
                tgt_idx = shift_bars - 1  # 0 for +5m (935), 2 for +15m (945)
            else:
                pos_arr = np.where(hh_arr >= b_hhmm)[0]
                base_idx = int(pos_arr[0]) if len(pos_arr) > 0 else 0
                tgt_idx = min(len(arr) - 1, base_idx + shift_bars)

            d_bar = arr[tgt_idx]
            # d_bar: [hhmm_int, open, high, low, close, volume, amount]
            is_zt_close = (not np.isnan(zt_px)) and (d_bar[4] >= zt_px - 0.011)
            is_zt_low = (not np.isnan(zt_px)) and (d_bar[3] >= zt_px - 0.011)
            if is_zt_low:
                n_missed_strict_low_zt += 1
            if is_zt_close:
                n_missed_close_zt += 1
                rets_cov_zero.append(0.0)
                rets_full_zero.append(0.0)
            else:
                new_bpx = float(d_bar[4])  # delayed bar close
                qfq_ratio = bar_d["qfq"][p0] / bar_d["qfq"][pe]
                new_ret = (float(r.exit_price) / new_bpx) * qfq_ratio * 0.9980 - 1.0
                rets_cov_zero.append(new_ret)
                rets_cov_skip.append(new_ret)
                rets_full_zero.append(new_ret)
                rets_full_skip.append(new_ret)

        def _sum_delay(lst):
            a = np.array(lst, dtype=float)
            if len(a) == 0:
                return {"n": 0, "wr_pct": None, "avg_ret_pct": None, "nav_5y": None}
            return {
                "n": int(len(a)),
                "wr_pct": round(float((a > 0).mean() * 100.0), 2),
                "avg_ret_pct": round(float(a.mean() * 100.0), 3),
                "nav_5y": round(float(np.prod(1.0 + a)), 4),
            }

        base_cov_arr = np.array(rets_base_cov, dtype=float)
        delay_out[step_lbl] = {
            "covered_base_stats": _sum_delay(base_cov_arr),
            "missed_zt_close_count": int(n_missed_close_zt),
            "missed_zt_strict_low_count": int(n_missed_strict_low_zt),
            "covered_missed_as_zero": _sum_delay(rets_cov_zero),
            "covered_missed_skipped": _sum_delay(rets_cov_skip),
            "full_with_uncovered_unshifted_missed_as_zero": _sum_delay(rets_full_zero) if n_cov < n_tr else None,
            "full_with_uncovered_unshifted_missed_skipped": _sum_delay(rets_full_skip) if n_cov < n_tr else None,
        }

    vb_arr = np.array([it["v_b"] for it in trade_items], dtype=float) / 1e4  # wan
    ve_arr = np.array([it["v_e"] for it in trade_items], dtype=float) / 1e4  # wan
    v5_list = []
    for r in led_df.itertuples(index=False):
        arr5 = bars_5m.get((r.c6, r.buy_date))
        if arr5 is not None and len(arr5) > 0:
            hh = 935 if int(r.buy_hhmm) <= 925 else int(r.buy_hhmm)
            idx5 = np.where(arr5[:, 0] >= hh)[0]
            v5_list.append(float(arr5[idx5[0] if len(idx5) else 0, 6]) / 1e4)
    v_guard = {
        "v_buy_wan_min": round(float(np.min(vb_arr)), 1),
        "v_buy_wan_p10": round(float(np.quantile(vb_arr, 0.10)), 1),
        "v_buy_wan_median": round(float(np.median(vb_arr)), 1),
        "v_exit_wan_min": round(float(np.min(ve_arr)), 1),
        "v_exit_wan_p10": round(float(np.quantile(ve_arr, 0.10)), 1),
        "v_exit_wan_median": round(float(np.median(ve_arr)), 1),
        "cap_10pct_adv_p10_wan": round(float(min(np.quantile(vb_arr, 0.10), np.quantile(ve_arr, 0.10)) * 0.10), 1),
        "cap_5pct_adv_p10_wan": round(float(min(np.quantile(vb_arr, 0.10), np.quantile(ve_arr, 0.10)) * 0.05), 1),
        "v_entry_5m_cov": f"{len(v5_list)}/{n_tr}",
        "v_entry_5m_wan_p10": round(float(np.quantile(v5_list, 0.10)), 1) if v5_list else None,
        "v_entry_5m_wan_median": round(float(np.median(v5_list)), 1) if v5_list else None,
        "cap_20pct_5m_p10_wan": round(float(np.quantile(v5_list, 0.10) * 0.20), 1) if v5_list else None,
    }

    return {
        "baseline_unconstrained": {
            "nav_5y": round(base_0["nav_5y"], 4),
            "cagr_pct": round(base_0["cagr_pct"], 2),
            "sharpe": round(base_0["sharpe"], 3),
        },
        "liquidity_participation_guardrails": v_guard,
        "almgren_chriss": ac_results,
        "dynamic_compounding_sensitivity_Y050": dyn_comp,
        "random_fill_2000mc": fill_stress,
        "adverse_selection": adverse,
        "entry_delay": delay_out,
    }


def build_regime_table(cal_dates, all_dts, tot_amt, zt_tape, df):
    print("[5/6] Building 4D daily regime matrix (2021-11-16..2026-11-16)...")
    r15 = pd.read_parquet(
        f"{SIM}/backtests_astock2/theory_backtest_15y_20261119/data_cache/regime_daily_15y.parquet"
    )
    r15.index = pd.to_datetime(r15.index).strftime("%Y-%m-%d")

    # Rolling 60-day median turnover (lagged [t-60..t-1] PIT)
    tot_amt_roll60_med = tot_amt.shift(1).rolling(60, min_periods=20).median()
    amt_q60_flag = np.where(
        tot_amt.reindex(cal_dates) >= tot_amt_roll60_med.reindex(cal_dates),
        "放量(>=60日分位)",
        "缩量(<60日分位)",
    )

    # Lianban ecology from daily_env_5y + seamless extension from zt_tape & df for 2026-11-12..16
    de5 = pd.read_parquet(
        f"{SIM}/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/daily_env_5y.parquet"
    ).set_index("dt_str")

    # Compute exact non-ST 10cm >=2-board promotion rate from zt_tape across all dates
    zt_10 = zt_tape[
        zt_tape["sec_code"].str.startswith(("00", "60"))
        & (~zt_tape["sec_name"].str.contains("ST|退", na=False))
    ]
    zt_all_nonst = zt_tape[~zt_tape["sec_name"].str.contains("ST|退", na=False)]
    zt_by_dt = {d: set(g["sec_code"]) for d, g in zt_10.groupby("trade_date")}
    lb2_by_dt = {d: set(g["sec_code"]) for d, g in zt_10[zt_10["board_count"] >= 2].groupby("trade_date")}
    n_zt_all_map = zt_all_nonst.groupby("trade_date").size().to_dict()

    # Daily hit_zt & is_zt on non-ST for seal_rate fallback (2026-11-12..16)
    nonst_df = df[(~df["is_st_flag"]) & (df["dt"] >= "2026-11-01")]
    seal_ext = nonst_df.groupby("dt").agg(n_zt=("is_zt", "sum"), n_hit=("hit_zt", "sum"))
    seal_ext["sr"] = seal_ext["n_zt"] / seal_ext["n_hit"].replace(0, np.nan)

    rows = []
    for d in cal_dates:
        p = all_dts.index(d)
        prev_d = all_dts[p - 1]
        prev_lb = lb2_by_dt.get(prev_d, set())
        cur_zt = zt_by_dt.get(d, set())
        promo_lb = len(prev_lb & cur_zt) / len(prev_lb) if prev_lb else np.nan

        if d in de5.index:
            n_zt = float(de5.loc[d, "n_zt"])
            sr = float(de5.loc[d, "seal_rate"])
            ho_r = de5.loc[d, "ho_zt_r"]
            promo_eff = float(ho_r) if pd.notna(ho_r) else promo_lb
        else:
            n_zt = float(n_zt_all_map.get(d, seal_ext.loc[d, "n_zt"] if d in seal_ext.index else np.nan))
            sr = float(seal_ext.loc[d, "sr"]) if d in seal_ext.index else np.nan
            promo_eff = promo_lb

        zhaban_rate = 1.0 - sr if pd.notna(sr) else np.nan
        is_ebb = bool((pd.notna(promo_eff) and promo_eff < 0.20) or (pd.notna(zhaban_rate) and zhaban_rate > 0.35))

        if n_zt < 40:
            nzt_b = "冰点(涨停<40)"
        elif n_zt <= 85:
            nzt_b = "常规(40~85)"
        else:
            nzt_b = "高潮(涨停>85)"

        lb_quad = "退潮(晋级<20%或炸板>35%)" if is_ebb else nzt_b

        rows.append({
            "dt": d,
            "trend_regime": str(r15.loc[d, "trend_regime"]) if d in r15.index else "未知",
            "vol_regime": str(r15.loc[d, "vol_regime"]) if d in r15.index else "未知",
            "amt_regime_15y": str(r15.loc[d, "amt_regime"]) if d in r15.index else "未知",
            "amt_regime_q60": str(amt_q60_flag[cal_dates.index(d)]),
            "n_zt": n_zt,
            "zhaban_rate": zhaban_rate,
            "promo_lb": promo_eff,
            "lb_quadrant": lb_quad,
            "lb_nzt_bucket": nzt_b,
            "lb_ebb_flag": "退潮日" if is_ebb else "非退潮日",
        })

    reg_df = pd.DataFrame(rows).set_index("dt")
    # Also attach shifted t-1 PIT columns
    for col in ["trend_regime", "vol_regime", "amt_regime_q60", "lb_quadrant", "lb_nzt_bucket", "lb_ebb_flag"]:
        reg_df[f"{col}_m1"] = reg_df[col].shift(1).bfill()
    return reg_df


def _slice_trade_metrics(sub_df):
    n = int(len(sub_df))
    if n == 0:
        return {"n": 0, "wr_pct": None, "avg_ret_pct": None, "cum_ret_pct": 0.0, "max_dd_pct": 0.0}
    r = sub_df["net_ret"].to_numpy(dtype=float)
    nav = np.concatenate([[1.0], np.cumprod(1.0 + r)])
    dd = (1.0 - nav / np.maximum.accumulate(nav)).max() * 100.0
    return {
        "n": n,
        "wr_pct": round(float((r > 0).mean() * 100.0), 2),
        "avg_ret_pct": round(float(r.mean() * 100.0), 3),
        "cum_ret_pct": round(float((nav[-1] - 1.0) * 100.0), 2),
        "max_dd_pct": round(float(dd), 2),
    }


def _slice_mtm_metrics(r_arr):
    if len(r_arr) == 0:
        return {"mtm_days": 0, "mtm_cum_ret_pct": 0.0, "mtm_max_dd_pct": 0.0}
    nav = np.concatenate([[1.0], np.cumprod(1.0 + r_arr)])
    dd = (1.0 - nav / np.maximum.accumulate(nav)).max() * 100.0
    return {
        "mtm_days": int(len(r_arr)),
        "mtm_cum_ret_pct": round(float((nav[-1] - 1.0) * 100.0), 2),
        "mtm_max_dd_pct": round(float(dd), 2),
    }


def run_pillar3(strat_key, led_df, daily_s, reg_df, csi_s, cal_dates):
    # 1. Regime Slicing Matrix (both t concurrent buy_date and t-1 PIT)
    dims = [
        ("trend_regime", "大盘趋势"),
        ("amt_regime_q60", "市场量能_60日分位"),
        ("amt_regime_15y", "市场量能_15Y对照"),
        ("vol_regime", "市场波动"),
        ("lb_quadrant", "连板生态四象限"),
        ("lb_nzt_bucket", "涨停家数三档"),
        ("lb_ebb_flag", "退潮标记"),
    ]
    d_work = led_df.copy()
    for col, _ in dims:
        d_work[col] = d_work["buy_date"].map(reg_df[col])
        if f"{col}_m1" in reg_df.columns:
            d_work[f"{col}_m1"] = d_work["buy_date"].map(reg_df[f"{col}_m1"])

    regime_matrix = {"by_buy_date": {}, "by_pit_m1": {}}
    enemy_cands = []
    for col, label in dims:
        grp_out = {}
        for val, sub in d_work.groupby(col, sort=False):
            m = _slice_trade_metrics(sub)
            # Also add daily MTM cum_ret inside this regime
            mask_d = (reg_df[col] == val).to_numpy()
            mtm_m = _slice_mtm_metrics(daily_s.to_numpy()[mask_d])
            m["mtm_days"] = mtm_m["mtm_days"]
            m["mtm_cum_ret_pct"] = mtm_m["mtm_cum_ret_pct"]
            grp_out[str(val)] = m
            if col in ("trend_regime", "amt_regime_q60", "vol_regime", "lb_quadrant"):
                enemy_cands.append((f"{label}:{val}", m["n"], m["avg_ret_pct"], m["cum_ret_pct"], m["wr_pct"]))
        regime_matrix["by_buy_date"][col] = grp_out

        if f"{col}_m1" in d_work.columns:
            grp_m1 = {}
            for val, sub in d_work.groupby(f"{col}_m1", sort=False):
                grp_m1[str(val)] = _slice_trade_metrics(sub)
            regime_matrix["by_pit_m1"][col] = grp_m1

    # Identify worst enemy regime (among cells with n >= 3 if any, plus absolute worst)
    cands_n3 = [x for x in enemy_cands if x[1] >= 3 and x[2] is not None]
    worst_n3 = min(cands_n3, key=lambda x: (x[3], x[2])) if cands_n3 else None
    cands_any = [x for x in enemy_cands if x[1] >= 1 and x[2] is not None]
    worst_any = min(cands_any, key=lambda x: (x[3], x[2])) if cands_any else None
    regime_matrix["worst_enemy_regime_n_ge_3"] = (
        {"regime": worst_n3[0], "n": worst_n3[1], "avg_ret_pct": worst_n3[2], "cum_ret_pct": worst_n3[3], "wr_pct": worst_n3[4]}
        if worst_n3 else None
    )
    regime_matrix["worst_enemy_regime_any_n"] = (
        {"regime": worst_any[0], "n": worst_any[1], "avg_ret_pct": worst_any[2], "cum_ret_pct": worst_any[3], "wr_pct": worst_any[4]}
        if worst_any else None
    )

    # 2. Extreme Historical Scenarios
    scenarios_spec = [
        ("W1_2022_04_lockdown", "2022-03-01", "2022-04-30", False),
        ("W2_2024_01_microcap_crash", "2024-01-01", "2024-02-08", False),
        ("W3_2024_0924_rally", "2024-09-24", "2024-10-15", False),
        ("W4_2025_2026_ebb_tide", "2025-01-01", "2026-11-16", True),
        ("W4_2025_2026_full_period", "2025-01-01", "2026-11-16", False),
    ]
    scenarios = {}
    cal_arr = np.array(cal_dates)
    ebb_arr = (reg_df["lb_ebb_flag"] == "退潮日").to_numpy()
    daily_arr = daily_s.to_numpy(dtype=float)
    csi_arr = csi_s.to_numpy(dtype=float)

    for w_name, d0, d1, ebb_only in scenarios_spec:
        tr_mask = (d_work["buy_date"] >= d0) & (d_work["buy_date"] <= d1)
        day_mask = (cal_arr >= d0) & (cal_arr <= d1)
        if ebb_only:
            tr_mask = tr_mask & (d_work["lb_ebb_flag"] == "退潮日")
            day_mask = day_mask & ebb_arr
        tm = _slice_trade_metrics(d_work[tr_mask])
        mm = _slice_mtm_metrics(daily_arr[day_mask])
        cm = _slice_mtm_metrics(csi_arr[day_mask])
        scenarios[w_name] = {
            **tm,
            **mm,
            "csi300_cum_ret_pct": cm["mtm_cum_ret_pct"],
        }

    # Monthly 2025-2026 breakdown (identifying monthly ebb count + strategy performance)
    d_work["ym"] = d_work["buy_date"].str.slice(0, 7)
    monthly_2526 = {}
    for ym in sorted(set(d[:7] for d in cal_dates if d >= "2025-01-01")):
        tr_sub = d_work[d_work["ym"] == ym]
        day_m = np.array([d.startswith(ym) for d in cal_dates], dtype=bool)
        ebb_cnt = int((day_m & ebb_arr).sum())
        tm = _slice_trade_metrics(tr_sub)
        mm = _slice_mtm_metrics(daily_arr[day_m])
        monthly_2526[ym] = {
            "ebb_days": ebb_cnt,
            "total_days": int(day_m.sum()),
            "n_trades": tm["n"],
            "wr_pct": tm["wr_pct"],
            "trade_cum_ret_pct": tm["cum_ret_pct"],
            "mtm_cum_ret_pct": mm["mtm_cum_ret_pct"],
            "mtm_max_dd_pct": mm["mtm_max_dd_pct"],
        }
    scenarios["W4_2025_2026_monthly"] = monthly_2526

    # 3. Moving Block Bootstrap (10,000x, block_len=5 trading days)
    rng = np.random.default_rng(SEED)
    n_days = len(daily_arr)
    b_len = 5
    n_blocks = int(math.ceil(n_days / b_len))
    n_boot = 10000

    # Prebuild block matrix of shape (n_days - b_len + 1, b_len)
    n_starts = n_days - b_len + 1
    blocks = np.lib.stride_tricks.sliding_window_view(daily_arr, b_len)  # (n_starts, 5)
    starts = rng.integers(0, n_starts, size=(n_boot, n_blocks))
    sim_rets = blocks[starts].reshape(n_boot, n_blocks * b_len)[:, :n_days]

    sim_nav_paths = np.concatenate([np.ones((n_boot, 1)), np.cumprod(1.0 + sim_rets, axis=1)], axis=1)
    term_navs = sim_nav_paths[:, -1]
    peaks = np.maximum.accumulate(sim_nav_paths, axis=1)
    dds = (1.0 - sim_nav_paths / peaks) * 100.0
    mdds = dds.max(axis=1)

    # Exact longest underwater duration (trading days) across 10,000 paths
    is_uw = sim_nav_paths[:, 1:] < peaks[:, 1:] * (1.0 - 1e-12)
    cur_uw = np.zeros(n_boot, dtype=np.int32)
    max_uw = np.zeros(n_boot, dtype=np.int32)
    for t in range(n_days):
        uw_t = is_uw[:, t]
        cur_uw = np.where(uw_t, cur_uw + 1, 0)
        max_uw = np.maximum(max_uw, cur_uw)

    csi_5y_nav = float(np.prod(1.0 + csi_arr))
    bootstrap = {
        "n_boot": n_boot,
        "block_len": b_len,
        "actual_5y_nav": round(float(np.prod(1.0 + daily_arr)), 4),
        "csi300_5y_nav": round(csi_5y_nav, 4),
        "nav_5y_mean": round(float(np.mean(term_navs)), 4),
        "nav_5y_median": round(float(np.median(term_navs)), 4),
        "nav_5y_p01": round(float(np.quantile(term_navs, 0.01)), 4),
        "nav_5y_p05": round(float(np.quantile(term_navs, 0.05)), 4),
        "nav_5y_p25": round(float(np.quantile(term_navs, 0.25)), 4),
        "nav_5y_p75": round(float(np.quantile(term_navs, 0.75)), 4),
        "nav_5y_p95": round(float(np.quantile(term_navs, 0.95)), 4),
        "prob_loss_pct": round(float((term_navs < 1.0).mean() * 100.0), 2),
        "prob_beat_csi300_pct": round(float((term_navs > csi_5y_nav).mean() * 100.0), 2),
        "max_dd_mean_pct": round(float(np.mean(mdds)), 2),
        "max_dd_median_pct": round(float(np.median(mdds)), 2),
        "max_dd_p95_pct": round(float(np.quantile(mdds, 0.95)), 2),
        "max_dd_p99_pct": round(float(np.quantile(mdds, 0.99)), 2),
        "underwater_days_mean": round(float(np.mean(max_uw)), 1),
        "underwater_days_median": round(float(np.median(max_uw)), 1),
        "underwater_days_p95": round(float(np.quantile(max_uw, 0.95)), 1),
        "underwater_days_p99": round(float(np.quantile(max_uw, 0.99)), 1),
    }

    return {
        "regime_matrix": regime_matrix,
        "extreme_scenarios": scenarios,
        "block_bootstrap_10k": bootstrap,
    }


def main():
    cal_dates, sh300, csi_s = load_calendar_and_csi300()
    df, tot_amt, zt_tape = load_daily_universe(cal_dates)
    factors, extra, fac_summary = build_5_factors(df, cal_dates, sorted(sh300.keys()), zt_tape, csi_s)
    by_c = build_by_c_lookup(df)
    pool_by_dt, q_lookup = prepare_matched_pools(df, cal_dates)
    reg_df = build_regime_table(cal_dates, sorted(sh300.keys()), tot_amt, zt_tape, df)

    # Load all ledgers & collect target (c6, buy_date) pairs for targeted 5m load
    loaded_ledgers = {}
    target_pairs = set()
    for sk, fn in LEDGERS.items():
        ld = pd.read_csv(f"{LEDGER_DIR}/{fn}")
        ld["c6"] = ld["code"].astype(str).str.strip().str.zfill(6)
        ld["buy_date"] = ld["buy_date"].astype(str).str.slice(0, 10)
        ld["exit_date"] = ld["exit_date"].astype(str).str.slice(0, 10)
        ld["buy_hhmm"] = pd.to_numeric(ld["buy_hhmm"], errors="coerce").fillna(925).astype(int)
        ld["exit_hhmm"] = pd.to_numeric(ld["exit_hhmm"], errors="coerce").fillna(1500).astype(int)
        ld["net_ret"] = pd.to_numeric(ld["net_ret"], errors="coerce").astype(float)
        ld.sort_values(["buy_date", "buy_hhmm", "c6"], inplace=True)
        ld.reset_index(drop=True, inplace=True)
        loaded_ledgers[sk] = ld
        for r in ld.itertuples(index=False):
            target_pairs.add((r.c6, r.buy_date))

    bars_5m = load_targeted_5m_bars(target_pairs)

    print("[6/6] Running Pillars 1, 2 & 3 across all 7 ledgers...")
    results = {
        "metadata": {
            "window": f"{START_DATE} to {END_DATE}",
            "n_trading_days": len(cal_dates),
            "seed": SEED,
            "one_minute_bars_status": "MISSING_LOCAL_DATA (本地无任何A股1分钟K线数据，仅存5分钟K线)",
            "factor_summary": fac_summary,
            "regime_day_counts": {
                "trend_regime": reg_df["trend_regime"].value_counts().to_dict(),
                "vol_regime": reg_df["vol_regime"].value_counts().to_dict(),
                "amt_regime_q60": reg_df["amt_regime_q60"].value_counts().to_dict(),
                "lb_quadrant": reg_df["lb_quadrant"].value_counts().to_dict(),
                "lb_ebb_flag": reg_df["lb_ebb_flag"].value_counts().to_dict(),
            },
        },
        "strategies": {},
    }

    for sk, ld in loaded_ledgers.items():
        allow_ov = sk == "pry_V21_top1"
        daily_s, active_flag, nav_mtm, nav_led = compute_daily_mtm(ld, by_c, cal_dates, allow_overlap=allow_ov)
        p1_reg = run_pillar1_regressions(sk, ld, daily_s, active_flag, factors, extra, cal_dates)
        p1_mc = run_matched_control(sk, ld, pool_by_dt, q_lookup, by_c)
        p2 = run_pillar2(sk, ld, by_c, cal_dates, bars_5m, zt_tape, allow_overlap=allow_ov)
        p3 = run_pillar3(sk, ld, daily_s, reg_df, csi_s, cal_dates)

        results["strategies"][sk] = {
            "n_trades": int(len(ld)),
            "n_active_days": int(active_flag.sum()),
            "nav_ledger": round(nav_led, 4),
            "nav_daily_mtm": round(nav_mtm, 4),
            "pillar1_alpha_attribution": {
                "regressions": p1_reg,
                "matched_control": p1_mc,
            },
            "pillar2_micro_capacity": p2,
            "pillar3_regime_stress_bootstrap": p3,
        }
        print(
            f"  Done {sk:14s}: alpha={p1_reg['full_5y_daily_hac']['alpha_ann_pct']:+.2f}% "
            f"(NW_t={p1_reg['full_5y_daily_hac']['nw_t']:.2f}), "
            f"MC_ex={p1_mc['excess_over_matched_pct']:+.2f}% (p={p1_mc['paired_p']:.4f}), "
            f"AC_BE(Y0.5)={p2['almgren_chriss']['Y_0.50']['breakeven_cap_wan']}w, "
            f"Boot_p05={p3['block_bootstrap_10k']['nav_5y_p05']:.2f}x"
        )

    out_json = f"{OUT_DIR}/part1_alpha_micro_regime.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, allow_nan=False)
    print(f"SAVED: {out_json} ({os.path.getsize(out_json)} bytes)")


if __name__ == "__main__":
    main()

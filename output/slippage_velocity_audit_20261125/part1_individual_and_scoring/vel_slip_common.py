#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Shared loaders, 3-tier velocity slippage engine, daily MTM & D15 metrics (ZERO yfinance, ZERO cap10m).
"""
import json
import math
import os
import pickle
import sys
import numpy as np
import pandas as pd
import pyarrow.dataset as ds
import scipy.stats as stats

assert "yfinance" not in sys.modules, "D12 VIOLATION: yfinance forbidden"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
OUT_DIR = f"{SIM}/output/slippage_velocity_audit_20261125/part1_individual_and_scoring"

PATH_5M = f"{SIM}/data/all_strategies_5m_complete_pit.parquet"
PATH_A_DAILY = f"{SIM}/data/cn_hk_price_db/a_daily.parquet"
PATH_A_DELIST = f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet"
PATH_IDX_JSON = f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json"
PATH_SUB2_5M = f"{SIM}/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113/sub2_5m_bars_cache.pkl"

LEDGER_PATHS = {
    "1to2": f"{SIM}/output/six_strategies_v20_upgrade_20261124/partA_10cm_upgrades/ledger_1to2_v20_cand.csv",
    "3to4": f"{SIM}/backtests_astock/redteam_full_audit_20261123/partC_clean_ledgers_v191/ledger_3to4_v41_clean.csv",
    "high": f"{SIM}/backtests_astock/redteam_full_audit_20261123/partC_clean_ledgers_v191/ledger_high_v51_clean.csv",
    "2to3": f"{SIM}/backtests_astock/redteam_full_audit_20261123/partC_clean_ledgers_v191/ledger_2to3_v21_opt_std90_clean.csv",
    "pry": f"{SIM}/backtests_astock/redteam_full_audit_20261123/partC_clean_ledgers_v191/ledger_pry_v21_ss165_clean.csv",
    "20cm": f"{SIM}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v11_unified_redteam_attack/final_v11_ledger_S82.csv",
}

POOL_PATHS = {
    "1to2": f"{SIM}/backtests_astock/mkt_water_scoring_audit_20261123/part3_1to2/pool_1to2_full_clean.csv",
    "3to4": f"{SIM}/backtests_astock/mkt_water_scoring_audit_20261123/part1_3to4_high/pool_3to4_full_clean.csv",
    "high": f"{SIM}/backtests_astock/mkt_water_scoring_audit_20261123/part1_3to4_high/pool_high_full_clean.csv",
    "2to3": f"{SIM}/backtests_astock/mkt_water_scoring_audit_20261123/part2_2to3_pry/pool_2to3_full_clean.csv",
    "pry": f"{SIM}/backtests_astock/mkt_water_scoring_audit_20261123/part2_2to3_pry/pool_pry_full_clean.csv",
    "20cm": f"{SIM}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v11_unified_redteam_attack/final_v11_all_scored_signals.csv",
}

CANON_WINDOWS = [
    ("FULL", "2021-11-16", "2026-11-16"),
    ("Near3Y", "2023-11-16", "2026-11-16"),
    ("Y2026", "2026-01-01", "2026-11-16"),
    ("IS", "2021-11-16", "2024-06-30"),
    ("OOS", "2024-07-04", "2026-11-16"),
]

WINDOWS_20CM_FULL = [
    ("FULL_2021_2026", "2021-01-04", "2026-11-16"),
    ("IS_2021_20240630", "2021-01-04", "2024-06-30"),
] + CANON_WINDOWS

TRD_DAYS_YEAR = 242.0


def sf(x, digits=6):
    if x is None:
        return None
    v = float(x)
    if math.isnan(v) or math.isinf(v):
        return None
    return round(v, digits)


def sanitize_json(obj):
    if isinstance(obj, dict):
        return {str(k): sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_json(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return None if (math.isnan(v) or math.isinf(v)) else v
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    return obj


def load_market_data(codes_needed: set[str]):
    with open(PATH_IDX_JSON, "r", encoding="utf-8") as f:
        sh300 = {k: float(v) for k, v in json.load(f)["sh000300"].items()}
    all_sh_dts = sorted(sh300.keys())

    df5 = pd.read_parquet(PATH_5M, columns=["c6", "date", "hhmm_int", "open", "high", "low", "close", "volume", "amount"])
    df5["c6"] = df5["c6"].astype(str).str.zfill(6)
    df5["dt"] = df5["date"].astype(str).str[:10]
    df5["hh"] = df5["hhmm_int"].astype(int)
    m5_bar = {
        (r.c6, r.dt, r.hh): (float(r.open), float(r.high), float(r.low), float(r.close), float(r.volume), float(r.amount))
        for r in df5.itertuples(index=False)
    }

    sub2_raw = pickle.load(open(PATH_SUB2_5M, "rb"))
    sub2_bar = {}
    for k, v in sub2_raw.items():
        if isinstance(v, pd.DataFrame) and not v.empty:
            c6, dt = str(k[0]).zfill(6), str(k[2])[:10]
            sub = v[v["date"].astype(str).str[:10] == dt]
            for r in sub.itertuples(index=False):
                hh = int(str(r.hhmm).replace(":", ""))
                sub2_bar[(c6, dt, hh)] = (float(r.open), float(r.high), float(r.low), float(r.close), float(r.volume), float(r.amount))

    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "qfq_factor"]
    flt = ds.field("date") >= pd.Timestamp("2020-12-01")
    da = ds.dataset(PATH_A_DAILY, format="parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    dd = ds.dataset(PATH_A_DELIST, format="parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    da["dl"], dd["dl"] = 0, 1
    df_d = pd.concat([da, dd], ignore_index=True)
    df_d["c6"] = df_d["ticker"].astype(str).str[:6]
    df_d = df_d[df_d["c6"].isin(codes_needed) & (~df_d["ticker"].astype(str).str.endswith(".BJ"))].copy()
    df_d["dt"] = df_d["date"].dt.strftime("%Y-%m-%d")
    df_d.sort_values(["c6", "dt", "dl"], inplace=True)
    df_d.drop_duplicates(["c6", "dt"], keep="first", inplace=True)
    df_d.reset_index(drop=True, inplace=True)
    df_d["adjf"] = np.where((df_d["close"] > 0) & (df_d["adj_close"] > 0), df_d["adj_close"] / df_d["close"], 1.0)
    g = df_d.groupby("c6", sort=False)
    df_d["pre_c"] = g["close"].shift(1) * g["adjf"].shift(1) / df_d["adjf"]
    lim = np.where(df_d["c6"].str.startswith(("300", "301", "688", "689")), 0.20, 0.10)
    df_d["zt_px"] = np.floor(df_d["pre_c"] * (1.0 + lim) * 100.0 + 0.5) / 100.0

    dmap = {
        (r.c6, r.dt): {
            "open": float(r.open), "high": float(r.high), "low": float(r.low), "close": float(r.close),
            "adj_close": float(r.adj_close), "qfq": float(r.qfq_factor), "adjf": float(r.adjf),
            "pre_c": float(r.pre_c) if pd.notna(r.pre_c) else np.nan,
            "zt_px": float(r.zt_px) if pd.notna(r.zt_px) else np.nan,
        }
        for r in df_d.itertuples(index=False)
    }
    return sh300, all_sh_dts, m5_bar, sub2_bar, dmap


def apply_vel_slip_df(
    df_in: pd.DataFrame,
    dmap: dict,
    m5_bar: dict,
    sub2_bar: dict | None = None,
    mode: str = "base",
    is_20cm: bool = False,
    allow_sub2_fallback: bool = False,
    missing_5m_policy: str = "error",
) -> pd.DataFrame:
    """
    Apply 3-tier velocity slippage model.
    missing_5m_policy: 'error' | 'zero' | 'daily_proxy'
    """
    d = df_in.copy()
    c6_col = "c6" if ("c6" in d.columns and "code" not in d.columns) else "code"
    d["c6"] = d[c6_col].astype(str).str.strip().str.zfill(6)
    d["buy_date"] = d["buy_date"].astype(str).str[:10]
    d["exit_date"] = d["exit_date"].astype(str).str[:10]
    if "buy_hhmm" not in d.columns:
        d["buy_hhmm"] = 925
    d["buy_hhmm"] = pd.to_numeric(d["buy_hhmm"], errors="coerce").fillna(925).astype(int)
    ret_col = "net_ret_eval" if ("net_ret_eval" in d.columns and is_20cm) else "net_ret"

    tiers, slips, real_slips, eff_pxs, new_rets = [], [], [], [], []
    zt_pxs, surges, jumps, hit_zts, seal_zts, srcs = [], [], [], [], [], []

    for r in d.itertuples(index=False):
        c6, bd, hh = r.c6, r.buy_date, int(r.buy_hhmm)
        db = dmap[(c6, bd)]
        old_ret = float(getattr(r, ret_col))
        if is_20cm:
            bp_adj = float(getattr(r, "buy_px"))
            trig_p = round(bp_adj / db["adjf"], 4)
        else:
            trig_p = float(getattr(r, "buy_price"))
        zt_px = float(db["zt_px"])
        pre_c = float(db["pre_c"])

        if hh <= 925:
            tiers.append("auction_0925")
            slips.append(0.0)
            real_slips.append(0.0)
            eff_pxs.append(trig_p)
            new_rets.append(old_ret)
            zt_pxs.append(zt_px)
            surges.append(0.0)
            jumps.append(0.0)
            hit_zts.append(False)
            seal_zts.append(False)
            srcs.append("auction_0925")
            continue

        b5 = m5_bar.get((c6, bd, hh))
        src = "parquet_5m"
        if b5 is None and allow_sub2_fallback and sub2_bar is not None:
            b5 = sub2_bar.get((c6, bd, hh))
            if b5 is not None:
                src = "sub2_5m_cache"

        if b5 is None:
            if missing_5m_policy == "error":
                raise KeyError(f"Missing 5m bar for {c6} {bd} {hh}")
            elif missing_5m_policy == "zero":
                tiers.append("missing_5m_zero")
                slips.append(0.0)
                real_slips.append(0.0)
                eff_pxs.append(trig_p)
                new_rets.append(old_ret)
                zt_pxs.append(zt_px)
                surges.append(np.nan)
                jumps.append(np.nan)
                hit_zts.append(False)
                seal_zts.append(False)
                srcs.append("missing_5m")
                continue
            elif missing_5m_policy == "daily_proxy":
                h_d = float(db["high"])
                hit_zt_d = h_d >= zt_px - 0.01
                sl = 0.010 if hit_zt_d else 0.005
                eff_p = min(trig_p * (1.0 + sl), zt_px)
                tiers.append("missing_5m_fast_proxy" if hit_zt_d else "missing_5m_med_proxy")
                slips.append(sl)
                real_slips.append(eff_p / trig_p - 1.0)
                eff_pxs.append(eff_p)
                new_rets.append((1.0 + old_ret) * (trig_p / eff_p) - 1.0)
                zt_pxs.append(zt_px)
                surges.append((h_d - trig_p) / trig_p)
                jumps.append(np.nan)
                hit_zts.append(bool(hit_zt_d))
                seal_zts.append(bool(float(db["close"]) >= zt_px - 0.01))
                srcs.append("missing_5m_daily_proxy")
                continue
            else:
                raise ValueError(missing_5m_policy)

        o5, h5, _, c5, _, _ = b5
        surge = (h5 - trig_p) / trig_p
        jump = (h5 - o5) / pre_c
        hit_zt = h5 >= zt_px - 0.01
        seal_zt = hit_zt and (c5 >= zt_px - 0.01)

        if mode == "base":
            if hit_zt or surge >= 0.025 or jump >= 0.040:
                tier, sl = "fast", 0.010
            elif surge >= 0.010 or jump >= 0.020:
                tier, sl = "medium", 0.005
            else:
                tier, sl = "slow", 0.000
        elif mode == "strict_surge":
            if hit_zt or surge >= 0.015 or jump >= 0.040:
                tier, sl = "fast", 0.010
            elif surge >= 0.005 or jump >= 0.020:
                tier, sl = "medium", 0.005
            else:
                tier, sl = "slow", 0.000
        elif mode == "strict_both":
            if hit_zt or surge >= 0.015 or jump >= 0.025:
                tier, sl = "fast", 0.010
            elif surge >= 0.005 or jump >= 0.010:
                tier, sl = "medium", 0.005
            else:
                tier, sl = "slow", 0.000
        else:
            raise ValueError(mode)

        eff_p = min(trig_p * (1.0 + sl), zt_px)
        nr = (1.0 + old_ret) * (trig_p / eff_p) - 1.0
        tiers.append(tier)
        slips.append(sl)
        real_slips.append(eff_p / trig_p - 1.0)
        eff_pxs.append(eff_p)
        new_rets.append(nr)
        zt_pxs.append(zt_px)
        surges.append(surge)
        jumps.append(jump)
        hit_zts.append(bool(hit_zt))
        seal_zts.append(bool(seal_zt))
        srcs.append(src)

    d["vel_tier"] = tiers
    d["extra_slip"] = np.round(slips, 6)
    d["realized_extra_slip"] = np.round(real_slips, 6)
    d["eff_buy_price"] = np.round(eff_pxs, 6)
    d["net_ret_vel"] = np.round(new_rets, 8)
    d["zt_px"] = np.round(zt_pxs, 4)
    d["surge_over_trig"] = np.round(surges, 6)
    d["bar_jump"] = np.round(jumps, 6)
    d["is_zt_hit_bar"] = hit_zts
    d["is_zt_sealed_bar"] = seal_zts
    d["src_5m"] = srcs
    return d


def build_daily_mtm_series(
    df_tr: pd.DataFrame,
    cal_dts: list[str],
    dt_to_idx: dict,
    dmap: dict,
    ret_col: str = "net_ret",
    buy_px_col: str = "buy_price",
    is_20cm: bool = False,
) -> tuple[np.ndarray, float]:
    T = len(cal_dts)
    day_mult = np.ones(T, dtype=float)
    if df_tr.empty:
        return np.zeros(T, dtype=float), 0.0
    for r in df_tr.itertuples(index=False):
        bi = dt_to_idx.get(str(r.buy_date)[:10])
        ei = dt_to_idx.get(str(r.exit_date)[:10])
        if bi is None:
            continue
        c6 = str(r.c6).zfill(6)
        bb = dmap.get((c6, str(r.buy_date)[:10]))
        if is_20cm and "buy_px" in df_tr.columns and buy_px_col == "buy_px":
            b_adj = float(getattr(r, "buy_px"))
        else:
            bp = float(getattr(r, buy_px_col))
            b_adj = bp * bb["adjf"] if bb else bp
        if b_adj <= 0:
            b_adj = 1.0
        prev_v, last_c = b_adj, b_adj
        end_loop = ei if (ei is not None and ei > bi) else T
        for t in range(bi, end_loop):
            bt = dmap.get((c6, cal_dts[t]))
            cur_c = bt["adj_close"] if bt else last_c
            if cur_c <= 0:
                cur_c = last_c
            day_mult[t] *= (cur_c / prev_v)
            prev_v, last_c = cur_c, cur_c
        ret_v = float(getattr(r, ret_col))
        if ei is not None and ei > bi:
            day_mult[ei] *= (b_adj * (1.0 + ret_v)) / prev_v
    daily_r = day_mult - 1.0
    mtm_nav = float(np.prod(day_mult))
    tr_nav = float(np.prod(1.0 + df_tr[ret_col].to_numpy(float)))
    return daily_r, abs(mtm_nav - tr_nav)


def get_csi_ret(sh300: dict, all_sh_dts: list[str], sdt: str, edt: str) -> float:
    dts = [d for d in all_sh_dts if sdt <= d <= edt]
    if not dts:
        return 0.0
    prevs = [d for d in all_sh_dts if d < dts[0]]
    p0 = sh300[prevs[-1]] if prevs else sh300[dts[0]]
    return float((sh300[dts[-1]] / p0 - 1.0) * 100.0)


def calc_d15_window(
    df_tr: pd.DataFrame,
    daily_mtm_r: np.ndarray,
    cal_dts: list[str],
    dt_to_idx: dict,
    sh300: dict,
    all_sh_dts: list[str],
    sdt: str,
    edt: str,
    ret_col: str = "net_ret",
    pool_df: pd.DataFrame | None = None,
    pool_ret_col: str = "net_ret",
) -> dict:
    csi_pct = get_csi_ret(sh300, all_sh_dts, sdt, edt)
    sub = df_tr[(df_tr["buy_date"] >= sdt) & (df_tr["buy_date"] <= edt)] if not df_tr.empty else pd.DataFrame()
    win_idx = [dt_to_idx[d] for d in cal_dts if sdt <= d <= edt]
    dr = daily_mtm_r[win_idx] if win_idx else np.zeros(1)
    T = len(dr)

    mtm_nav = float(np.prod(1.0 + dr))
    cum_d = np.cumprod(1.0 + dr)
    pk_d = np.maximum.accumulate(np.insert(cum_d, 0, 1.0))[1:]
    daily_mdd = float(np.max((pk_d - cum_d) / pk_d) * 100.0) if T > 0 else 0.0
    sd = float(np.std(dr, ddof=1)) if T > 1 else 0.0
    sharpe = float(np.mean(dr) / sd * math.sqrt(TRD_DAYS_YEAR)) if sd > 1e-12 else 0.0
    cagr = (mtm_nav ** (TRD_DAYS_YEAR / T) - 1.0) * 100.0 if (T > 0 and mtm_nav > 0) else -100.0
    calmar = (cagr / daily_mdd) if daily_mdd > 1e-6 else 0.0

    eq_nav, eq_days = 1.0, 0
    if pool_df is not None and not pool_df.empty:
        sp = pool_df[(pool_df["buy_date"] >= sdt) & (pool_df["buy_date"] <= edt)]
        if not sp.empty:
            daily_eq_s = sp.groupby("buy_date", sort=True)[pool_ret_col].mean().to_numpy(float)
            eq_days = int(len(daily_eq_s))
            eq_nav = float(np.prod(1.0 + daily_eq_s))

    if sub.empty:
        return {
            "trades": 0, "win_rate_pct": 0.0, "plr": 0.0, "mean_ret_pct": 0.0,
            "nav_1s": 1.0, "ex_top3_nav": 1.0, "ex_top5_nav": 1.0,
            "trade_mdd_pct": 0.0, "daily_mtm_mdd_pct": sf(daily_mdd, 2),
            "daily_sharpe": sf(sharpe, 3), "daily_calmar": sf(calmar, 2),
            "eq_days_pool": eq_days, "eq_nav_pool": sf(eq_nav, 4),
            "csi300_pct": sf(csi_pct, 2),
            "excess_1s_pp": sf(-csi_pct, 2),
            "excess_eq_pp": sf((eq_nav - 1.0) * 100.0 - csi_pct, 2),
        }

    rets = sub[ret_col].to_numpy(float)
    w, l = rets[rets > 0], rets[rets < 0]
    wr = float((rets > 0).mean() * 100.0)
    plr = float(w.mean() / abs(l.mean())) if (len(w) and len(l)) else (99.0 if len(w) else 0.0)
    nav = float(np.prod(1.0 + rets))
    s_rets = np.sort(rets)
    ex3 = float(np.prod(1.0 + s_rets[:-3])) if len(rets) > 3 else 1.0
    ex5 = float(np.prod(1.0 + s_rets[:-5])) if len(rets) > 5 else 1.0
    cum_t = np.cumprod(1.0 + rets)
    pk_t = np.maximum.accumulate(np.insert(cum_t, 0, 1.0))[1:]
    trade_mdd = float(np.max((pk_t - cum_t) / pk_t) * 100.0)

    return {
        "trades": int(len(rets)),
        "win_rate_pct": sf(wr, 2),
        "plr": sf(plr, 2),
        "mean_ret_pct": sf(rets.mean() * 100.0, 2),
        "nav_1s": sf(nav, 4),
        "ex_top3_nav": sf(ex3, 4),
        "ex_top5_nav": sf(ex5, 4),
        "trade_mdd_pct": sf(trade_mdd, 2),
        "daily_mtm_mdd_pct": sf(daily_mdd, 2),
        "daily_sharpe": sf(sharpe, 3),
        "daily_calmar": sf(calmar, 2),
        "eq_days_pool": eq_days,
        "eq_nav_pool": sf(eq_nav, 4),
        "csi300_pct": sf(csi_pct, 2),
        "excess_1s_pp": sf((nav - 1.0) * 100.0 - csi_pct, 2),
        "excess_eq_pp": sf((eq_nav - 1.0) * 100.0 - csi_pct, 2),
    }


def calc_hlz_dsr(df_tr: pd.DataFrame, sh300: dict, all_sh_dts: list[str], ret_col: str = "net_ret", m_trials: int = 150) -> tuple[float, float]:
    n = len(df_tr)
    if n < 5:
        return 0.0, 0.0
    def _b(bd, ed):
        prevs = [d for d in all_sh_dts if d < bd]
        posts = [d for d in all_sh_dts if d <= ed]
        p0 = sh300[prevs[-1]] if prevs else sh300[all_sh_dts[0]]
        return float(sh300[posts[-1]] / p0 - 1.0)
    ex = np.array([float(getattr(r, ret_col)) - _b(str(r.buy_date)[:10], str(r.exit_date)[:10]) for r in df_tr.itertuples(index=False)], float)
    sd = float(ex.std(ddof=1))
    if sd <= 1e-12:
        return 0.0, 0.0
    sr = float(ex.mean() / sd)
    t_val = sr * math.sqrt(n)
    sk = float(stats.skew(ex, bias=False)) if n > 2 else 0.0
    ku = max(1.0, float(stats.kurtosis(ex, fisher=False, bias=False))) if n > 3 else 3.0
    gm = 0.5772156649
    sr0 = (1.0 / math.sqrt(n - 1)) * ((1.0 - gm) * stats.norm.ppf(1.0 - 1.0 / m_trials) + gm * stats.norm.ppf(1.0 - 1.0 / (m_trials * math.e)))
    den = math.sqrt(max(1e-12, 1.0 - sk * sr + ((ku - 1.0) / 4.0) * (sr ** 2)))
    return sf(t_val, 2), sf(float(stats.norm.cdf((sr - sr0) * math.sqrt(n - 1) / den)), 4)

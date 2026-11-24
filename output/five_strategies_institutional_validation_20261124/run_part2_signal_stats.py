#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD024 Part 2: Institutional Quantitative Signal Quality (Pillar 4) & Statistical Confidence (Pillar 5)
Targets:
  - 3to4_v41 (ledger_3to4_v41_clean.csv, N=95)
  - high_v51 (ledger_high_v51_clean.csv, N=42)
  - pry_v21_ss165 (ledger_pry_v21_ss165_clean.csv, N=16)
  - 2to3_v21 (ledger_2to3_v21_opt_std90_clean.csv, N=95)
  - 1to2_v19 (ledger_1to2_v19_clean.csv, N=97)
  - combined_5strat_v191_slot1 (ledger_combined_5strat_v191_slot1_clean.csv, N=228)
  + Auxiliary reference: pry_v21_top1 (ledger_pry_v21_top1_clean.csv, N=25, multi-slot overlapping)

Hard Rules:
  - 100% read-only on all production scripts, ledgers, pools, and PIT price databases.
  - Zero yfinance imports (D12). Zero network calls.
  - Zero fabrication: explicitly discloses candidate pool scope and missingness.
  - Outputs strictly inside sim-portfolio/output/five_strategies_institutional_validation_20261124/.
"""
import json
import math
import os
import sys
import time
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import scipy.optimize as opt
import scipy.stats as stats
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import StratifiedKFold

warnings.filterwarnings("ignore", category=FutureWarning)
assert "yfinance" not in sys.modules, "D12 VIOLATION: yfinance must never be imported"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
PARTC_DIR = f"{SIM}/backtests_astock/redteam_full_audit_20261123/partC_clean_ledgers_v191"
MW_DIR = f"{SIM}/backtests_astock/mkt_water_scoring_audit_20261123"
IDX_JSON = f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json"
A_DAILY = f"{SIM}/data/cn_hk_price_db/a_daily.parquet"
A_DELISTED = f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet"
OUT_DIR = f"{SIM}/output/five_strategies_institutional_validation_20261124"

CANON_START = "2021-11-16"
CANON_END = "2026-11-16"
ORIG_FEE_RT = 0.0020  # Verified empirically across all 6 clean ledgers = 0.9980 multiplier
ORIG_FEE_OW_BPS = 10.0
ANN_DAYS = 252
YEARS_5Y = 5.0
BOOT_B = 5000
MC_RUNS_B = 10000
RNG = np.random.default_rng(20261124)

TARGETS_META = [
    {
        "key": "3to4_v41",
        "label": "三进四 V4.1",
        "ledger_path": f"{PARTC_DIR}/ledger_3to4_v41_clean.csv",
        "pool_path": f"{MW_DIR}/part1_3to4_high/pool_3to4_full_clean.csv",
        "threshold": 90.0,
        "pool_type": "full_candidate_pool",
        "pool_note": "全量可买骨架候选池 base_score>=65 (N=318: >=90分115笔, <90分未入选近线203笔)",
    },
    {
        "key": "high_v51",
        "label": "高标首阴 V5.1",
        "ledger_path": f"{PARTC_DIR}/ledger_high_v51_clean.csv",
        "pool_path": f"{MW_DIR}/part1_3to4_high/pool_high_full_clean.csv",
        "threshold": 88.0,
        "pool_type": "full_candidate_pool",
        "pool_note": "全量非一票否决早盘可成交候选池 base_score>=60 (N=62: >=88分46笔, <88分未入选近线16笔)",
    },
    {
        "key": "pry_v21_ss165",
        "label": "超跌撬板 V2.1 (单槽)",
        "ledger_path": f"{PARTC_DIR}/ledger_pry_v21_ss165_clean.csv",
        "pool_path": f"{MW_DIR}/part2_2to3_pry/pool_pry_full_clean.csv",
        "threshold": 165.0,
        "pool_type": "full_candidate_pool",
        "pool_note": "全量撬板候选池 base_score>=120 (N=759 across 79日: >=165分435笔/25日, <165分未入选324笔)",
    },
    {
        "key": "2to3_v21",
        "label": "二进三 V2.1",
        "ledger_path": f"{PARTC_DIR}/ledger_2to3_v21_opt_std90_clean.csv",
        "pool_path": f"{MW_DIR}/part2_2to3_pry/pool_2to3_full_clean.csv",
        "threshold": 90.0,
        "pool_type": "full_candidate_pool",
        "pool_note": "全量二进三候选池 base_score>=65 (N=1532: >=90分138笔, <90分未入选近线1394笔)",
    },
    {
        "key": "1to2_v19",
        "label": "一进二 V19",
        "ledger_path": f"{PARTC_DIR}/ledger_1to2_v19_clean.csv",
        "pool_path": f"{MW_DIR}/part3_1to2/pool_1to2_full_clean.csv",
        "threshold": 304.8,
        "pool_type": "full_candidate_pool",
        "pool_note": "全量可成交一进二候选池 base_score>=250 (N=447: >=304.8分158笔, <304.8分未入选近线289笔; 另有256笔未触及触发价无成交价)",
    },
    {
        "key": "combined_5strat_v191_slot1",
        "label": "五策略合体 V19.1 (单槽)",
        "ledger_path": f"{PARTC_DIR}/ledger_combined_5strat_v191_slot1_clean.csv",
        "pool_path": None,
        "threshold": None,
        "pool_type": "no_unified_unselected_pool",
        "pool_note": "缺未入选全底池同标尺统一打分（5子策略打分标尺异构: 65-141/120-220/250-430且跨策略按priority 1~5轮动）；主表仅报真账内分策略标准化打分(within-strategy z-score & pct-rank)及原始分对照，另附5池合并(N=3118, 策略内z-score)对照",
    },
]


def sf(x, digits=6):
    """Safe finite float conversion for strict JSON."""
    if x is None:
        return None
    v = float(x)
    if math.isnan(v) or math.isinf(v):
        return None
    return round(v, digits)


def load_market_and_prices(codes_needed: set[str]):
    raw_idx = json.load(open(IDX_JSON, encoding="utf-8"))
    sh300 = {k: float(v) for k, v in raw_idx["sh000300"].items()}
    all_sh_dts = sorted(sh300.keys())
    t_days = [d for d in all_sh_dts if CANON_START <= d <= CANON_END]
    day_idx = {d: i for i, d in enumerate(t_days)}

    # Daily CSI 300 returns aligned with t_days (first day uses 2021-11-15 close)
    csi_daily = np.zeros(len(t_days), dtype=float)
    for i, d in enumerate(t_days):
        pos_all = all_sh_dts.index(d)
        prev_d = all_sh_dts[pos_all - 1]
        csi_daily[i] = sh300[d] / sh300[prev_d] - 1.0

    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "qfq_factor"]
    da = pd.read_parquet(A_DAILY, columns=cols, filters=[("date", ">=", pd.Timestamp("2021-11-01"))])
    dd = pd.read_parquet(A_DELISTED, columns=cols, filters=[("date", ">=", pd.Timestamp("2021-11-01"))])
    px = pd.concat([da, dd], ignore_index=True)
    px["c6"] = px["ticker"].astype(str).str[:6]
    px = px[px["c6"].isin(codes_needed) & (~px["ticker"].astype(str).str.endswith(".BJ"))].copy()
    px["dt"] = px["date"].dt.strftime("%Y-%m-%d")
    px.sort_values(["c6", "dt"], inplace=True)
    px.drop_duplicates(["c6", "dt"], keep="first", inplace=True)
    px.reset_index(drop=True, inplace=True)

    px["adjf"] = np.where((px["close"] > 0) & px["adj_close"].notna() & (px["adj_close"] > 0), px["adj_close"] / px["close"], 1.0)
    g = px.groupby("c6")
    px["prev_c_adj"] = g["close"].shift(1) * g["adjf"].shift(1) / px["adjf"]
    # 20cm detection if any, though all 00/60 are 10cm
    lim_pct = np.where(px["c6"].str.startswith(("300", "301", "688", "689")), 0.20, 0.10)
    px["dt_px"] = np.floor(px["prev_c_adj"] * (1.0 - lim_pct) * 100.0 + 0.5) / 100.0
    px["is_dt_exact"] = (px["prev_c_adj"] > 0) & (px["close"] <= px["dt_px"] + 0.005)
    px["is_yizi_dt"] = px["is_dt_exact"] & (px["open"] <= px["dt_px"] + 0.005) & (px["high"] <= px["dt_px"] + 0.005)

    by_c = {}
    for c6, grp in px.groupby("c6", sort=False):
        gr = grp.reset_index(drop=True)
        dt_to_pos = {d: idx for idx, d in enumerate(gr["dt"])}
        by_c[c6] = {"df": gr, "dt_to_pos": dt_to_pos}
    return sh300, all_sh_dts, t_days, day_idx, csi_daily, by_c


def get_csi_period_ret(sh300: dict, all_sh_dts: list[str], buy_date: str, end_date: str) -> float:
    prevs = [d for d in all_sh_dts if d < buy_date]
    p0 = sh300[prevs[-1]] if prevs else sh300[all_sh_dts[0]]
    p1s = [d for d in all_sh_dts if d <= end_date]
    p1 = sh300[p1s[-1]]
    return float(p1 / p0 - 1.0)


def norm_ledger(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["code"] = d["code"].astype(str).str.strip().str.zfill(6)
    d["buy_date"] = d["buy_date"].astype(str).str[:10]
    d["exit_date"] = d["exit_date"].astype(str).str[:10]
    if "buy_hhmm" not in d.columns:
        d["buy_hhmm"] = 925
    if "exit_hhmm" not in d.columns:
        d["exit_hhmm"] = 1500
    d["buy_hhmm"] = pd.to_numeric(d["buy_hhmm"], errors="coerce").fillna(925).astype(int)
    d["exit_hhmm"] = pd.to_numeric(d["exit_hhmm"], errors="coerce").fillna(1500).astype(int)
    d["net_ret"] = pd.to_numeric(d["net_ret"], errors="coerce").astype(float)
    d.sort_values(["buy_date", "buy_hhmm", "code"], inplace=True)
    d.reset_index(drop=True, inplace=True)
    return d


def compute_trade_mtm_segment(c6: str, buy_date: str, exit_date: str, buy_price: float, exit_price: float, net_ret: float,
                              t_days: list[str], day_idx: dict, by_c: dict) -> tuple[np.ndarray, np.ndarray]:
    """Compute exact daily MTM returns over [buy_date, exit_date] so product == 1 + net_ret."""
    info = by_c[c6]
    df_c = info["df"]
    pos_map = info["dt_to_pos"]
    pb = pos_map[buy_date]
    pe = pos_map[exit_date]
    sub = df_c.iloc[pb:pe + 1]
    sub_dts = sub["dt"].tolist()
    sub_closes = sub["close"].to_numpy(dtype=float)
    sub_adjf = sub["adjf"].to_numpy(dtype=float)

    # Map to market trading days between buy_date and exit_date
    ib = day_idx[buy_date]
    ie = day_idx[exit_date]
    seg_idx = np.arange(ib, ie + 1, dtype=int)
    m_len = len(seg_idx)
    gross_factors = np.ones(m_len, dtype=float)

    # First day: buy_price -> close(buy_date)
    prev_adj_val = float(buy_price) * float(sub_adjf[0])
    dt_bar_map = {dt: (sub_closes[k], sub_adjf[k]) for k, dt in enumerate(sub_dts)}
    for k, d_idx in enumerate(seg_idx):
        dt = t_days[d_idx]
        if k == m_len - 1:
            # Exit day: prev close -> exit_price
            cur_adj_val = float(exit_price) * float(sub_adjf[-1])
            gross_factors[k] = cur_adj_val / prev_adj_val
            prev_adj_val = cur_adj_val
        else:
            if dt in dt_bar_map:
                cl, af = dt_bar_map[dt]
                cur_adj_val = float(cl) * float(af)
                gross_factors[k] = cur_adj_val / prev_adj_val
                prev_adj_val = cur_adj_val
            else:
                # Suspended day: factor remains 1.0
                gross_factors[k] = 1.0

    gross_total = float(np.prod(gross_factors))
    lam = (1.0 + float(net_ret)) / gross_total if gross_total > 0 else (1.0 - ORIG_FEE_RT)
    lam_buy = math.sqrt(max(lam, 1e-6))
    lam_sell = lam / lam_buy
    gross_factors[0] *= lam_buy
    gross_factors[-1] *= lam_sell
    daily_rets = gross_factors - 1.0
    return seg_idx, daily_rets


def trades_to_daily_mtm(df_trades: pd.DataFrame, t_days: list[str], day_idx: dict, by_c: dict,
                        mtm_cache: dict, allow_overlap: bool = False) -> tuple[np.ndarray, float]:
    """Convert a trade sequence to T=1212 daily MTM return series. Enforces exact NAV invariant for single-slot."""
    T = len(t_days)
    if df_trades.empty:
        return np.zeros(T, dtype=float), 0.0

    if not allow_overlap:
        factors = np.ones(T, dtype=float)
        for r in df_trades.itertuples(index=False):
            bd_s, ed_s = str(r.buy_date)[:10], str(r.exit_date)[:10]
            if bd_s not in day_idx or ed_s not in day_idx:
                continue
            key = (str(r.code).zfill(6), bd_s, ed_s,
                   round(float(r.buy_price), 4), round(float(r.exit_price), 4), round(float(r.net_ret), 8))
            seg = mtm_cache.get(key)
            if seg is None:
                seg = compute_trade_mtm_segment(*key, t_days, day_idx, by_c)
                mtm_cache[key] = seg
            s_idx, s_rets = seg
            factors[s_idx] *= (1.0 + s_rets)
        daily = factors - 1.0
        nav_mtm = float(np.prod(factors))
        nav_tr = float(np.prod(1.0 + df_trades["net_ret"].to_numpy(dtype=float)))
        return daily, abs(nav_mtm - nav_tr)
    else:
        # Equal-weight across concurrent active positions (for pry_v21_top1 auxiliary)
        day_lists = [[] for _ in range(T)]
        for r in df_trades.itertuples(index=False):
            key = (str(r.code).zfill(6), str(r.buy_date)[:10], str(r.exit_date)[:10],
                   round(float(r.buy_price), 4), round(float(r.exit_price), 4), round(float(r.net_ret), 8))
            seg = mtm_cache.get(key)
            if seg is None:
                seg = compute_trade_mtm_segment(*key, t_days, day_idx, by_c)
                mtm_cache[key] = seg
            s_idx, s_rets = seg
            for j, d_i in enumerate(s_idx):
                day_lists[d_i].append(float(s_rets[j]))
        daily = np.array([float(np.mean(lst)) if lst else 0.0 for lst in day_lists], dtype=float)
        return daily, 0.0


# ==============================================================================
# PILLAR 4 HELPERS
# ==============================================================================

def newey_west_slope_t(x: np.ndarray, y: np.ndarray, max_lag: int = 6) -> tuple[float, float, float, float, float]:
    """OLS slope of y on x with both OLS t/p and Newey-West HAC t/p."""
    n = len(x)
    if n < 3 or np.std(x) < 1e-12:
        return 0.0, 0.0, 1.0, 0.0, 1.0
    X = np.column_stack([np.ones(n), x])
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    resid = y - X @ beta
    slope = float(beta[1])
    xtx_inv = np.linalg.inv(X.T @ X)

    # OLS standard error
    s2 = float(np.sum(resid ** 2) / max(1, n - 2))
    se_ols = math.sqrt(max(1e-18, s2 * xtx_inv[1, 1]))
    t_ols = slope / se_ols
    p_ols = float(2.0 * stats.t.sf(abs(t_ols), df=max(1, n - 2)))

    # Newey-West HAC covariance
    L = min(max_lag, max(1, n - 2))
    S_hac = (X * resid[:, None]).T @ (X * resid[:, None])
    for lag in range(1, L + 1):
        w = 1.0 - lag / (L + 1.0)
        G_lag = (X[lag:] * resid[lag:, None]).T @ (X[:-lag] * resid[:-lag, None])
        S_hac += w * (G_lag + G_lag.T)
    cov_hac = xtx_inv @ S_hac @ xtx_inv
    se_hac = math.sqrt(max(1e-18, float(cov_hac[1, 1])))
    t_hac = slope / se_hac
    p_hac = float(2.0 * stats.t.sf(abs(t_hac), df=max(1, n - 2)))
    return slope, t_ols, p_ols, t_hac, p_hac


def calc_ic_block(df: pd.DataFrame, score_col: str, ret_col: str = "net_ret", min_period_n: int = 4, min_roll_n: int = 10) -> dict:
    d = df.dropna(subset=[score_col, ret_col]).copy()
    d["bd"] = d["buy_date"].astype(str).str[:10]
    n = len(d)
    if n < 3 or d[score_col].nunique() < 2:
        return {"n": int(n), "insufficient": True}

    rho_all, p_all = stats.spearmanr(d[score_col], d[ret_col])

    # Daily cross-sectional IC (days with >=2 and >=3 candidates)
    cs_stats = {}
    for min_d in (2, 3):
        ics = []
        for _, grp in d.groupby("bd"):
            if len(grp) >= min_d and grp[score_col].nunique() >= 2 and grp[ret_col].nunique() >= 2:
                r, _ = stats.spearmanr(grp[score_col], grp[ret_col])
                if not np.isnan(r):
                    ics.append(float(r))
        if ics:
            arr = np.array(ics)
            sd = float(arr.std(ddof=1)) if len(arr) > 1 else 0.0
            cs_stats[f"min_cand_{min_d}"] = {
                "n_days": len(arr),
                "mean_ic": sf(arr.mean(), 4),
                "std_ic": sf(sd, 4),
                "icir": sf(arr.mean() / sd, 4) if sd > 1e-12 else None,
                "pos_rate_pct": sf((arr > 0).mean() * 100.0, 2),
            }
        else:
            cs_stats[f"min_cand_{min_d}"] = {"n_days": 0}

    # Grouped IC helper (quarter and month)
    def grouped_ic(period_series: pd.Series, min_obs: int) -> dict:
        d_tmp = d.copy()
        d_tmp["_p"] = period_series.values
        vals = []
        for per, grp in d_tmp.groupby("_p", sort=True):
            if len(grp) >= min_obs and grp[score_col].nunique() >= 2 and grp[ret_col].nunique() >= 2:
                r, p = stats.spearmanr(grp[score_col], grp[ret_col])
                if not np.isnan(r):
                    vals.append({"period": str(per), "n": int(len(grp)), "ic": float(r), "p": float(p)})
        if not vals:
            return {"n_valid_periods": 0}
        arr = np.array([v["ic"] for v in vals])
        sd = float(arr.std(ddof=1)) if len(arr) > 1 else 0.0
        return {
            "n_valid_periods": len(arr),
            "mean_ic": sf(arr.mean(), 4),
            "std_ic": sf(sd, 4),
            "icir": sf(arr.mean() / sd, 4) if sd > 1e-12 else None,
            "pos_rate_pct": sf((arr > 0).mean() * 100.0, 2),
            "periods_sample": [{**v, "ic": sf(v["ic"], 4), "p": sf(v["p"], 4)} for v in vals],
        }

    dt_idx = pd.to_datetime(d["bd"])
    q_res = grouped_ic(dt_idx.dt.to_period("Q"), min_period_n)
    m_res = grouped_ic(dt_idx.dt.to_period("M"), min_period_n)

    # Rolling 12-month IC decay slope (monthly steps from 2022-11 to 2026-11)
    end_months = pd.period_range("2022-11", "2026-11", freq="M")
    roll_pts = []
    for em in end_months:
        w_end = em.to_timestamp(how="end").strftime("%Y-%m-%d")
        w_start = (em - 11).to_timestamp(how="start").strftime("%Y-%m-%d")
        sub = d[(d["bd"] >= w_start) & (d["bd"] <= w_end)]
        if len(sub) >= min_roll_n and sub[score_col].nunique() >= 2 and sub[ret_col].nunique() >= 2:
            r, _ = stats.spearmanr(sub[score_col], sub[ret_col])
            if not np.isnan(r):
                roll_pts.append({"end_month": str(em), "n": int(len(sub)), "ic": float(r)})

    if len(roll_pts) >= 6:
        t_yrs = np.array([(pd.Period(p["end_month"], "M") - end_months[0]).n / 12.0 for p in roll_pts], dtype=float)
        ics_r = np.array([p["ic"] for p in roll_pts], dtype=float)
        slope, t_ols, p_ols, t_hac, p_hac = newey_west_slope_t(t_yrs, ics_r, max_lag=6)
        roll_res = {
            "n_windows": len(roll_pts),
            "min_window_n": min_roll_n,
            "mean_ic": sf(ics_r.mean(), 4),
            "first_window": {"month": roll_pts[0]["end_month"], "n": roll_pts[0]["n"], "ic": sf(roll_pts[0]["ic"], 4)},
            "last_window": {"month": roll_pts[-1]["end_month"], "n": roll_pts[-1]["n"], "ic": sf(roll_pts[-1]["ic"], 4)},
            "ols_slope_per_year": sf(slope, 4),
            "ols_t_stat": sf(t_ols, 3),
            "ols_p_value": sf(p_ols, 4),
            "nw_hac_lag6_t_stat": sf(t_hac, 3),
            "nw_hac_lag6_p_value": sf(p_hac, 4),
            "sig_decay_at_5pct_hac": bool(slope < 0 and p_hac < 0.05),
            "sig_decay_at_5pct_ols": bool(slope < 0 and p_ols < 0.05),
        }
    else:
        roll_res = {"n_windows": len(roll_pts), "insufficient": True}

    # IS vs OOS & Yearly IC
    is_sub = d[d["bd"] <= "2023-12-31"]
    oos_sub = d[d["bd"] >= "2024-01-01"]
    def _sp(sub_df):
        if len(sub_df) < 3 or sub_df[score_col].nunique() < 2:
            return {"n": int(len(sub_df)), "ic": None, "p": None}
        r, p = stats.spearmanr(sub_df[score_col], sub_df[ret_col])
        return {"n": int(len(sub_df)), "ic": sf(r, 4), "p": sf(p, 4)}

    yearly = {yr: _sp(d[d["bd"].str.startswith(yr)]) for yr in ("2022", "2023", "2024", "2025", "2026")}
    return {
        "n": int(n),
        "pooled_spearman_ic": sf(rho_all, 4),
        "pooled_p_value": sf(p_all, 6),
        "daily_cross_sectional_ic": cs_stats,
        "quarterly_ic": q_res,
        "monthly_ic": m_res,
        "rolling_12m_ic_decay": roll_res,
        "is_ic": _sp(is_sub),
        "oos_ic": _sp(oos_sub),
        "yearly_ic": yearly,
    }


def calc_quantile_bins(scores: np.ndarray, rets: np.ndarray, n_bins: int, mode: str = "value_qcut") -> dict:
    s = pd.Series(scores, dtype=float)
    r = np.asarray(rets, dtype=float)
    if len(s) < n_bins:
        return {"insufficient": True, "n": len(s)}
    if mode == "value_qcut":
        try:
            cats = pd.qcut(s, q=n_bins, labels=False, duplicates="drop")
        except Exception:
            return {"insufficient": True, "n": len(s)}
    else:
        cats = pd.qcut(s.rank(method="first"), q=n_bins, labels=False)

    actual_bins = int(cats.nunique())
    if actual_bins < 2:
        return {"insufficient": True, "actual_bins": actual_bins}

    rows = []
    for b in sorted(cats.unique()):
        m = (cats == b).to_numpy()
        rb = r[m]
        sb = scores[m]
        w = rb[rb > 0]
        l = rb[rb <= 0]
        plr = float(w.mean() / abs(l.mean())) if (len(w) and len(l) and l.mean() < 0) else (99.0 if len(w) else 0.0)
        rows.append({
            "bin": int(b) + 1,
            "n": int(m.sum()),
            "score_min": sf(sb.min(), 2),
            "score_max": sf(sb.max(), 2),
            "win_rate_pct": sf((rb > 0).mean() * 100.0, 2),
            "mean_ret_pct": sf(rb.mean() * 100.0, 3),
            "median_ret_pct": sf(np.median(rb) * 100.0, 3),
            "plr": sf(plr, 2),
        })
    bin_idx = np.array([x["bin"] for x in rows], dtype=float)
    bin_means = np.array([x["mean_ret_pct"] for x in rows], dtype=float)
    bin_wrs = np.array([x["win_rate_pct"] for x in rows], dtype=float)
    rho_ret, p_ret = stats.spearmanr(bin_idx, bin_means)
    rho_wr, p_wr = stats.spearmanr(bin_idx, bin_wrs)

    r_bot = r[(cats == min(cats.unique())).to_numpy()]
    r_top = r[(cats == max(cats.unique())).to_numpy()]
    spread_pp = (r_top.mean() - r_bot.mean()) * 100.0
    t_sp, p_sp = stats.ttest_ind(r_top, r_bot, equal_var=False) if (len(r_top) > 1 and len(r_bot) > 1) else (0.0, 1.0)
    return {
        "requested_bins": n_bins,
        "actual_bins": actual_bins,
        "mode": mode,
        "bins": rows,
        "spearman_rho_mean_ret": sf(rho_ret, 4),
        "spearman_p_mean_ret": sf(p_ret, 4),
        "spearman_rho_win_rate": sf(rho_wr, 4),
        "spearman_p_win_rate": sf(p_wr, 4),
        "top_minus_bot_mean_pp": sf(spread_pp, 3),
        "top_minus_bot_welch_t": sf(t_sp, 3),
        "top_minus_bot_welch_p": sf(p_sp, 4),
    }


def calc_breakeven_cost(net_rets: np.ndarray, csi_5y_ret: float) -> dict:
    """Restore gross return from 20bps RT (0.9980) and solve arithmetic & 5Y geometric breakeven one-way bps."""
    n = len(net_rets)
    gross_mult = (1.0 + net_rets) / (1.0 - ORIG_FEE_RT)
    gross_rets = gross_mult - 1.0
    arith_gross_mean = float(np.mean(gross_rets))
    log_gross_mean = float(np.mean(np.log(np.maximum(1e-9, gross_mult))))
    geom_gross_mult = math.exp(log_gross_mean)

    # Model A (repo exact): (1 + r_gross) * (1 - 2*c)
    c_arith_ow = 0.5 * (1.0 - 1.0 / (1.0 + arith_gross_mean))
    c_geom_ow = 0.5 * (1.0 - 1.0 / geom_gross_mult)

    # Beat CSI 300 5Y NAV: prod((1+r_gross)*(1-2c)) = 1 + csi_5y_ret => G_geom^n * (1-2c)^n = 1 + csi_5y_ret
    target_mult_per_trade = (1.0 + csi_5y_ret) ** (1.0 / n) if n > 0 else 1.0
    c_csi_ow = 0.5 * (1.0 - target_mult_per_trade / geom_gross_mult)

    # Model B (symmetric buy/sell slippage factor (1-c)/(1+c))
    # G * (1-c)/(1+c) = 1 => c = (G - 1)/(G + 1)
    c_arith_slip_ow = arith_gross_mean / (2.0 + arith_gross_mean)
    c_geom_slip_ow = (geom_gross_mult - 1.0) / (geom_gross_mult + 1.0)

    sens_grid = []
    for ow_bps in (10, 25, 50, 100, 150, 200, 300):
        rt = 2.0 * ow_bps / 10000.0
        r_c = gross_mult * (1.0 - rt) - 1.0
        nav = float(np.prod(1.0 + r_c))
        # 10M cap nav (1M init, 10M cap -> 100 -> 1000 unit scale)
        cap = 100.0
        for rc in r_c:
            cap += min(cap, 1000.0) * float(rc)
        sens_grid.append({
            "one_way_bps": ow_bps,
            "round_trip_bps": 2 * ow_bps,
            "arith_mean_pct": sf(r_c.mean() * 100.0, 3),
            "nav_5y": sf(nav, 4),
            "cap10m_nav_5y": sf(cap / 100.0, 2),
        })

    return {
        "original_deducted_rt_bps": ORIG_FEE_RT * 10000.0,
        "original_deducted_ow_bps": ORIG_FEE_OW_BPS,
        "gross_arith_mean_pct": sf(arith_gross_mean * 100.0, 3),
        "gross_geom_mean_pct": sf((geom_gross_mult - 1.0) * 100.0, 3),
        "breakeven_ow_arith_bps": sf(c_arith_ow * 10000.0, 1),
        "breakeven_ow_geom_5y_bps": sf(c_geom_ow * 10000.0, 1),
        "breakeven_ow_beat_csi300_bps": sf(c_csi_ow * 10000.0, 1),
        "breakeven_ow_slip_ratio_arith_bps": sf(c_arith_slip_ow * 10000.0, 1),
        "breakeven_ow_slip_ratio_geom_bps": sf(c_geom_slip_ow * 10000.0, 1),
        "safety_margin_vs_10bps_ow_geom": sf((c_geom_ow * 10000.0) / ORIG_FEE_OW_BPS, 2),
        "cost_sensitivity_grid": sens_grid,
    }


def calc_cal_metrics(y: np.ndarray, probs: np.ndarray, n_bins: int = 5) -> dict:
    bs = float(np.mean((probs - y) ** 2))
    p_bar = float(np.mean(y))
    bs_ref = p_bar * (1.0 - p_bar)
    bss = 1.0 - bs / bs_ref if bs_ref > 1e-12 else 0.0
    roc = float(roc_auc_score(y, probs)) if len(np.unique(y)) == 2 else None
    pr = float(average_precision_score(y, probs)) if len(np.unique(y)) == 2 else None

    # 5-bin quantile calibration curve
    s_p = pd.Series(probs)
    bins = pd.qcut(s_p.rank(method="first"), q=min(n_bins, len(y)), labels=False)
    cal_rows = []
    ece = 0.0
    for b in sorted(bins.unique()):
        m = (bins == b).to_numpy()
        p_m = float(probs[m].mean())
        y_m = float(y[m].mean())
        err = abs(p_m - y_m)
        ece += (m.sum() / len(y)) * err
        cal_rows.append({
            "bin": int(b) + 1,
            "n": int(m.sum()),
            "pred_win_prob_pct": sf(p_m * 100.0, 2),
            "actual_win_rate_pct": sf(y_m * 100.0, 2),
            "abs_err_pp": sf(err * 100.0, 2),
        })
    return {
        "n": int(len(y)),
        "base_win_rate_pct": sf(p_bar * 100.0, 2),
        "brier_score": sf(bs, 5),
        "brier_baseline_p1mp": sf(bs_ref, 5),
        "brier_skill_score": sf(bss, 4),
        "roc_auc": sf(roc, 4),
        "pr_auc": sf(pr, 4),
        "ece_pp": sf(ece * 100.0, 2),
        "calibration_5bins": cal_rows,
    }


def calc_classification_calibration(df: pd.DataFrame, score_col: str) -> dict:
    d = df.dropna(subset=[score_col, "net_ret"]).sort_values(["buy_date", "code"]).reset_index(drop=True)
    x = d[score_col].to_numpy(dtype=float)
    y = (d["net_ret"].to_numpy(dtype=float) > 0).astype(int)
    n = len(y)
    if n < 10 or len(np.unique(y)) < 2 or np.std(x) < 1e-12:
        return {"n": int(n), "insufficient": True}

    raw_roc = float(roc_auc_score(y, x))
    raw_pr = float(average_precision_score(y, x))

    # 5-fold stratified OOF logistic regression
    k_folds = min(5, int(min(np.sum(y == 1), np.sum(y == 0))))
    if k_folds >= 2:
        skf = StratifiedKFold(n_splits=k_folds, shuffle=True, random_state=20261124)
        oof_probs = np.zeros(n, dtype=float)
        for tr_i, te_i in skf.split(x, y):
            mu, sd = x[tr_i].mean(), max(1e-9, x[tr_i].std())
            clf = LogisticRegression(C=100.0, solver="lbfgs")
            clf.fit(((x[tr_i] - mu) / sd).reshape(-1, 1), y[tr_i])
            oof_probs[te_i] = clf.predict_proba(((x[te_i] - mu) / sd).reshape(-1, 1))[:, 1]
        oof_res = calc_cal_metrics(y, oof_probs, n_bins=5)
    else:
        oof_res = {"insufficient": True}

    # Causal expanding walk-forward logistic regression (train strictly on buy_date < cur_bd)
    bd_arr = d["buy_date"].astype(str).str[:10].to_numpy()
    warmup = max(12, int(0.25 * n))
    wf_probs, wf_y = [], []
    for i in range(warmup, n):
        tr_m = bd_arr < bd_arr[i]
        if tr_m.sum() < 10 or len(np.unique(y[tr_m])) < 2 or np.std(x[tr_m]) < 1e-12:
            continue
        mu, sd = x[tr_m].mean(), max(1e-9, x[tr_m].std())
        clf = LogisticRegression(C=100.0, solver="lbfgs")
        clf.fit(((x[tr_m] - mu) / sd).reshape(-1, 1), y[tr_m])
        p_i = float(clf.predict_proba(np.array([[(x[i] - mu) / sd]]))[0, 1])
        wf_probs.append(p_i)
        wf_y.append(int(y[i]))
    if len(wf_y) >= 10 and len(np.unique(wf_y)) == 2:
        wf_res = calc_cal_metrics(np.array(wf_y), np.array(wf_probs), n_bins=5)
    else:
        wf_res = {"n": len(wf_y), "insufficient": True}

    return {
        "n": int(n),
        "positive_rate_pct": sf(y.mean() * 100.0, 2),
        "raw_score_roc_auc": sf(raw_roc, 4),
        "raw_score_pr_auc": sf(raw_pr, 4),
        "oof_5fold_logistic": oof_res,
        "causal_expanding_logistic": wf_res,
    }


def calc_holding_decay(df_ledger: pd.DataFrame, by_c: dict, sh300: dict, all_sh_dts: list[str]) -> dict:
    """Compute T+0, T+1, T+2, T+3, T+5 holding curves from real buy_price with physical limit-down deferral."""
    d = norm_ledger(df_ledger)
    horizons = (0, 1, 2, 3, 5)
    raw_rets = {h: [] for h in horizons}
    phys_rets = {h: [] for h in horizons}
    csi_rets = {h: [] for h in horizons}
    deferred_logs = {h: [] for h in (1, 2, 3, 5)}

    for r in d.itertuples(index=False):
        c6 = r.code
        info = by_c[c6]
        gc = info["df"]
        p0 = info["dt_to_pos"][r.buy_date]
        bpx_adj = float(r.buy_price) * float(gc.loc[p0, "adjf"])

        for h in horizons:
            ph = min(p0 + h, len(gc) - 1)
            dt_h = str(gc.loc[ph, "dt"])
            raw_px_adj = float(gc.loc[ph, "close"]) * float(gc.loc[ph, "adjf"])
            r_raw = raw_px_adj / bpx_adj - 1.0
            raw_rets[h].append(r_raw)

            if h > 0 and bool(gc.loc[ph, "is_dt_exact"]):
                # Physically locked limit-down at 15:00 close -> defer to next non-yizi_dt open
                k = ph + 1
                while k < len(gc) - 1 and bool(gc.loc[k, "is_yizi_dt"]):
                    k += 1
                dt_exec = str(gc.loc[k, "dt"])
                exec_px_adj = float(gc.loc[k, "open"]) * float(gc.loc[k, "adjf"])
                r_phys = exec_px_adj / bpx_adj - 1.0
                deferred_logs[h].append({
                    "code": c6, "name": str(r.name), "buy_date": r.buy_date,
                    "target_t_plus_h_dt": dt_h, "deferred_exec_dt": dt_exec,
                    "raw_ret_pct": sf(r_raw * 100.0, 2), "deferred_ret_pct": sf(r_phys * 100.0, 2),
                })
            else:
                dt_exec = dt_h
                r_phys = r_raw

            phys_rets[h].append(r_phys)
            csi_rets[h].append(get_csi_period_ret(sh300, all_sh_dts, r.buy_date, dt_exec))

    summary_h = {}
    prev_gross = None
    prev_ex = None
    for h in horizons:
        pr = np.array(phys_rets[h], dtype=float)
        rr = np.array(raw_rets[h], dtype=float)
        cr = np.array(csi_rets[h], dtype=float)
        ex = pr - cr
        net20 = (1.0 + pr) * (1.0 - ORIG_FEE_RT) - 1.0
        g_mean = float(pr.mean())
        ex_mean = float(ex.mean())
        inc_g = (g_mean - prev_gross) if prev_gross is not None else g_mean
        inc_ex = (ex_mean - prev_ex) if prev_ex is not None else ex_mean
        prev_gross, prev_ex = g_mean, ex_mean

        summary_h[f"T+{h}"] = {
            "n": len(pr),
            "phys_gross_mean_pct": sf(g_mean * 100.0, 3),
            "phys_gross_median_pct": sf(np.median(pr) * 100.0, 3),
            "phys_net20bps_mean_pct": sf(net20.mean() * 100.0, 3),
            "phys_win_rate_pct": sf((pr > 0).mean() * 100.0, 2),
            "csi300_mean_pct": sf(cr.mean() * 100.0, 3),
            "phys_excess_mean_pct": sf(ex_mean * 100.0, 3),
            "marginal_gross_inc_pp": sf(inc_g * 100.0, 3),
            "marginal_excess_inc_pp": sf(inc_ex * 100.0, 3),
            "raw_undeferred_gross_mean_pct": sf(rr.mean() * 100.0, 3),
            "raw_undeferred_excess_mean_pct": sf((rr - np.array([get_csi_period_ret(sh300, all_sh_dts, r.buy_date, str(by_c[r.code]['df'].loc[min(by_c[r.code]['dt_to_pos'][r.buy_date]+h, len(by_c[r.code]['df'])-1), 'dt'])) for r in d.itertuples(index=False)])).mean() * 100.0, 3) if h > 0 else sf(ex_mean * 100.0, 3),
            "dt_sealed_deferred_count": len(deferred_logs.get(h, [])),
            "dt_sealed_deferred_examples": deferred_logs.get(h, [])[:5],
        }

    # Estimate Alpha Decay Half-Life carefully based on curve shape
    hs = np.array([1.0, 2.0, 3.0, 5.0])
    ex_curve = np.array([summary_h[f"T+{int(h)}"]["phys_excess_mean_pct"] for h in hs], dtype=float)
    g_curve = np.array([summary_h[f"T+{int(h)}"]["phys_gross_mean_pct"] for h in hs], dtype=float)
    t0_ex = summary_h["T+0"]["phys_excess_mean_pct"]
    # Daily marginal excess returns on (0->1), (1->2), (2->3), (3->5 per day)
    m_daily_ex = np.array([
        ex_curve[0] - t0_ex,
        ex_curve[1] - ex_curve[0],
        ex_curve[2] - ex_curve[1],
        (ex_curve[3] - ex_curve[2]) / 2.0,
    ])
    peak_idx = int(np.argmax(ex_curve))
    peak_h = int(hs[peak_idx])
    peak_ex = float(ex_curve[peak_idx])

    # Method 1: Positive marginal decay fit or exponential saturation A_inf * (1 - exp(-lam * h))
    half_life_sat = None
    half_life_marginal = None
    half_life_post_peak = None
    regime_note = ""

    # Fit cumulative saturation alpha(h) = A_inf * (1 - exp(-lam * h)) for h in [1,2,3,5] if rising overall
    if ex_curve[-1] > 0 and ex_curve[0] > 0:
        try:
            def loss_sat(params):
                A_inf, lam = params
                pred = A_inf * (1.0 - np.exp(-lam * hs))
                return float(np.sum((pred - ex_curve) ** 2))
            res_sat = opt.minimize(loss_sat, x0=[max(ex_curve) * 1.1, 0.5],
                                   bounds=[(0.01, max(ex_curve) * 5.0), (0.02, 5.0)])
            if res_sat.success and res_sat.x[1] > 1e-4:
                half_life_sat = math.log(2.0) / float(res_sat.x[1])
        except Exception:
            pass

    # Method 2: First-crossing interpolation where marginal daily alpha drops to <= 50% of T+1 marginal alpha (or buy->T+1 vs T+0->T+1)
    # Check marginal increments from T+0->T+1 (d1) vs T+1->T+2 (d2) vs T+2->T+3 (d3) vs T+3->T+5/2 (d4)
    # Also check from buy (T_buy -> T+1 = ex_curve[0]) vs subsequent daily increments!
    inc_from_buy = np.array([ex_curve[0], m_daily_ex[1], m_daily_ex[2], m_daily_ex[3]])
    inc_h_mid = np.array([0.5, 1.5, 2.5, 4.0])
    pos_mask = inc_from_buy > 0
    if pos_mask.sum() >= 2 and inc_from_buy[0] > 0:
        # Log-linear regression on positive marginal increments from buy
        log_inc = np.log(inc_from_buy[pos_mask])
        t_pos = inc_h_mid[pos_mask]
        sl, _, _, _, _ = stats.linregress(t_pos, log_inc)
        if sl < -1e-4:
            half_life_marginal = math.log(2.0) / (-sl)

    # Method 3: Post-peak alpha retention (if curve peaked before T+5 and decayed afterwards)
    if peak_h < 5 and peak_ex > 0 and ex_curve[-1] < peak_ex:
        decay_frac = (peak_ex - ex_curve[-1]) / peak_ex
        dt_span = 5.0 - peak_h
        if ex_curve[-1] > 0:
            lam_pp = -math.log(ex_curve[-1] / peak_ex) / dt_span
            if lam_pp > 1e-6:
                half_life_post_peak = math.log(2.0) / lam_pp
        regime_note = f"Cum excess peaked at T+{peak_h} ({peak_ex:.2f}%), decayed {decay_frac*100:.1f}% by T+5 ({ex_curve[-1]:.2f}%)"
    elif peak_h == 5:
        regime_note = f"Cum excess still rising through T+5 ({ex_curve[0]:.2f}% at T+1 -> {ex_curve[-1]:.2f}% at T+5)"
    else:
        regime_note = f"Cum excess negative or flat (peak T+{peak_h}={peak_ex:.2f}%, T+5={ex_curve[-1]:.2f}%)"

    # Primary recommended half-life: marginal alpha half-life if positive-decaying, else saturation half-life
    primary_hl = half_life_marginal if half_life_marginal is not None else half_life_sat
    pct_captured_t1 = (ex_curve[0] / peak_ex * 100.0) if peak_ex > 0 else None

    return {
        "horizons": summary_h,
        "alpha_decay_analysis": {
            "peak_horizon_excess": f"T+{peak_h}",
            "peak_excess_pct": sf(peak_ex, 3),
            "pct_of_peak_excess_at_T1": sf(pct_captured_t1, 1),
            "daily_marginal_excess_pp_from_buy": {
                "buy_to_T1": sf(inc_from_buy[0], 3),
                "T1_to_T2": sf(inc_from_buy[1], 3),
                "T2_to_T3": sf(inc_from_buy[2], 3),
                "T3_to_T5_per_day": sf(inc_from_buy[3], 3),
            },
            "half_life_marginal_days": sf(half_life_marginal, 2),
            "half_life_saturation_days": sf(half_life_sat, 2),
            "half_life_post_peak_days": sf(half_life_post_peak, 2),
            "primary_alpha_half_life_days": sf(primary_hl, 2),
            "curve_diagnosis": regime_note,
        },
    }


# ==============================================================================
# PILLAR 5 HELPERS
# ==============================================================================

def calc_psr_mintrl(rets: np.ndarray, annualize_factor: float, bench_sr_ann_1: float = 1.0) -> dict:
    """Bailey & Lopez de Prado (2012) PSR and MinTRL with exact skewness & Pearson kurtosis."""
    n = len(rets)
    if n < 4:
        return {"n": int(n), "insufficient": True}
    mu = float(np.mean(rets))
    sd = float(np.std(rets, ddof=1))
    if sd <= 1e-12:
        return {"n": int(n), "std_zero": True}
    sr = mu / sd
    sr_ann = sr * math.sqrt(annualize_factor)
    sk = float(stats.skew(rets, bias=False))
    kurt_pearson = float(stats.kurtosis(rets, fisher=False, bias=False))
    kurt_excess = kurt_pearson - 3.0
    # Variance inflation factor inside sqrt: 1 - gamma3*SR + ((gamma4 - 1)/4)*SR^2
    var_factor = max(1e-12, 1.0 - sk * sr + ((kurt_pearson - 1.0) / 4.0) * (sr ** 2))
    denom = math.sqrt(var_factor)

    sr_star_0 = 0.0
    sr_star_1 = bench_sr_ann_1 / math.sqrt(annualize_factor)

    psr_0 = float(stats.norm.cdf((sr - sr_star_0) * math.sqrt(n - 1) / denom))
    psr_1 = float(stats.norm.cdf((sr - sr_star_1) * math.sqrt(n - 1) / denom))

    z95 = float(stats.norm.ppf(0.95))
    mintrl_0 = (1.0 + var_factor * (z95 / (sr - sr_star_0)) ** 2) if sr > sr_star_0 else None
    mintrl_1 = (1.0 + var_factor * (z95 / (sr - sr_star_1)) ** 2) if sr > sr_star_1 else None

    return {
        "n_obs": int(n),
        "mean_pct": sf(mu * 100.0, 4),
        "std_pct": sf(sd * 100.0, 4),
        "skewness_gamma3": sf(sk, 4),
        "excess_kurtosis": sf(kurt_excess, 4),
        "pearson_kurtosis_gamma4": sf(kurt_pearson, 4),
        "sr_per_period": sf(sr, 5),
        "sr_annualized": sf(sr_ann, 3),
        "psr_sr_gt_0": sf(psr_0, 6),
        "psr_sr_gt_1_ann": sf(psr_1, 6),
        "mintrl_95_sr0": sf(mintrl_0, 1),
        "mintrl_95_sr0_unattainable": bool(mintrl_0 is None),
        "mintrl_95_sr1_ann": sf(mintrl_1, 1),
        "mintrl_95_sr1_unattainable": bool(mintrl_1 is None),
        "passes_mintrl_95_sr0": bool(mintrl_0 is not None and n >= mintrl_0),
        "passes_mintrl_95_sr1_ann": bool(mintrl_1 is not None and n >= mintrl_1),
    }


def politis_white_opt_block_len(x: np.ndarray) -> float:
    """Automatic stationary bootstrap block length estimator (Politis & White 2004 / Patton et al. 2009)."""
    n = len(x)
    if n < 20 or np.std(x) < 1e-12:
        return 5.0
    xc = x - np.mean(x)
    gamma0 = float(np.dot(xc, xc) / n)
    if gamma0 <= 1e-18:
        return 5.0
    max_k = min(int(math.ceil(math.sqrt(n))) + 10, n // 3)
    K_N = max(5, int(math.ceil(math.sqrt(math.log10(n)))))
    crit = 1.96 * math.sqrt(math.log10(n) / n)
    # Find smallest m where K_N consecutive autocorrelations are insignificant
    m_hat = 1
    rhos = np.array([float(np.dot(xc[:n - k], xc[k:]) / (n * gamma0)) for k in range(max_k + 1)])
    for m in range(1, max_k - K_N):
        if np.all(np.abs(rhos[m + 1:m + 1 + K_N]) < crit):
            m_hat = m
            break
    M = min(max_k, 2 * m_hat)
    g_hat = 0.0
    d_sb = 2.0 * (gamma0 ** 2)
    for k in range(1, M + 1):
        lam = 1.0 if k <= M / 2.0 else 2.0 * (1.0 - k / float(M))
        gk = rhos[k] * gamma0
        g_hat += 2.0 * lam * k * gk
        d_sb += 2.0 * (lam * gk) ** 2 + 2.0 * 0.0  # leading spectral term at freq 0
    # Full spectral density f(0) = gamma0 + 2*sum(lam*gk)
    f0 = gamma0 + 2.0 * sum((1.0 if k <= M / 2.0 else 2.0 * (1.0 - k / float(M))) * rhos[k] * gamma0 for k in range(1, M + 1))
    d_sb = 2.0 * (f0 ** 2)
    if d_sb <= 1e-18 or abs(g_hat) <= 1e-18:
        return 5.0
    b_opt = ((2.0 * (g_hat ** 2) / d_sb) * n) ** (1.0 / 3.0)
    return float(max(2.0, min(b_opt, n / 4.0)))


def stationary_bootstrap_weights(T: int, B: int, L: float, rng: np.random.Generator) -> np.ndarray:
    """Generate (B, T) row-stochastic frequency weights under Politis-Romano Stationary Bootstrap."""
    q = 1.0 / float(L)
    W = np.zeros((B, T), dtype=np.float64)
    # Vectorized across B replicates step-by-step over t=0..T-1
    idx = rng.integers(0, T, size=B)
    for b_col in range(T):
        # Increment counts
        np.add.at(W, (np.arange(B), idx), 1.0)
        jump = rng.random(B) < q
        new_idx = rng.integers(0, T, size=B)
        idx = np.where(jump, new_idx, (idx + 1) % T)
    W /= float(T)
    return W


def hansen_omega_hat(D: np.ndarray, L: float) -> np.ndarray:
    """Hansen (2005) consistent long-run std dev omega_k under Stationary Bootstrap (Eq. 5)."""
    T, M = D.shape
    q = 1.0 / float(L)
    Dc = D - D.mean(axis=0, keepdims=True)
    # gamma_0
    omega2 = np.sum(Dc * Dc, axis=0) / float(T)
    # Truncate summation at i where (1-q)^i < 1e-6 or T-1
    max_i = min(T - 1, int(math.ceil(math.log(1e-6) / math.log(max(1e-9, 1.0 - q)))) if q < 1.0 else 1)
    for i in range(1, max_i + 1):
        kappa = ((T - i) / float(T)) * ((1.0 - q) ** i) + (i / float(T)) * ((1.0 - q) ** (T - i))
        gamma_i = np.sum(Dc[:-i] * Dc[i:], axis=0) / float(T)
        omega2 += 2.0 * kappa * gamma_i
    return np.sqrt(np.maximum(1e-14, omega2))


def run_wrc_and_spa(D: np.ndarray, W_dict: dict[int, np.ndarray], L_main: int = 10) -> dict:
    """Compute White's Reality Check & Hansen's SPA (lower/consistent/upper) across Stationary Bootstrap replicates."""
    T, M = D.shape
    d_bar = D.mean(axis=0)  # (M,)
    sqrtT = math.sqrt(T)
    V_wrc = float(np.max(sqrtT * d_bar))

    out_by_L = {}
    for L, W in W_dict.items():
        omega = hansen_omega_hat(D, float(L))
        t_obs_vec = sqrtT * d_bar / omega
        T_spa = float(max(0.0, np.max(t_obs_vec)))

        mean_star = W @ D  # (B, M)
        # WRC
        V_star = np.max(sqrtT * (mean_star - d_bar[None, :]), axis=1)
        p_wrc = float(np.mean(V_star > V_wrc))

        # Hansen SPA three null configurations
        thresh_c = -math.sqrt(2.0 * math.log(math.log(T)))
        mu_l = np.minimum(d_bar, 0.0)
        mu_c = np.where(t_obs_vec <= thresh_c, d_bar, 0.0)
        # mu_u = 0.0

        Z_l = (mean_star - d_bar[None, :] + mu_l[None, :]) * sqrtT / omega[None, :]
        Z_c = (mean_star - d_bar[None, :] + mu_c[None, :]) * sqrtT / omega[None, :]
        Z_u = (mean_star - d_bar[None, :]) * sqrtT / omega[None, :]

        T_l = np.maximum(0.0, np.max(Z_l, axis=1))
        T_c = np.maximum(0.0, np.max(Z_c, axis=1))
        T_u = np.maximum(0.0, np.max(Z_u, axis=1))

        p_l = float(np.mean(T_l > T_spa))
        p_c = float(np.mean(T_c > T_spa))
        p_u = float(np.mean(T_u > T_spa))

        # Active rule is column 0
        rank_active = int(1 + np.sum(t_obs_vec > t_obs_vec[0]))
        out_by_L[L] = {
            "block_len_L": int(L),
            "active_rule_t_stat": sf(t_obs_vec[0], 3),
            "active_rule_rank_in_M": rank_active,
            "max_rule_t_stat": sf(T_spa, 3),
            "wrc_p_value": sf(p_wrc, 4),
            "spa_p_lower": sf(p_l, 4),
            "spa_p_consistent": sf(p_c, 4),
            "spa_p_upper": sf(p_u, 4),
        }

    main_res = out_by_L[L_main]
    return {
        **main_res,
        "sensitivity_L5": out_by_L.get(5),
        "sensitivity_L20": out_by_L.get(20),
    }


def bca_bootstrap_ci(x: np.ndarray, B: int = 5000, alpha: float = 0.05, rng: np.random.Generator = RNG) -> dict:
    """Efron (1987) BCa 95% CI with mid-p tie handling for discrete win rate & exact jackknife acceleration."""
    n = len(x)
    theta_hat = float(np.mean(x))
    if n < 3 or np.std(x) < 1e-12:
        return {"point_est": sf(theta_hat, 6), "ci_low": sf(theta_hat, 6), "ci_high": sf(theta_hat, 6)}

    # Bootstrap means
    idx = rng.integers(0, n, size=(B, n))
    boot_vals = np.mean(x[idx], axis=1)

    # Bias-correction z0 with mid-p tie adjustment
    p0 = float(np.mean(boot_vals < theta_hat) + 0.5 * np.mean(boot_vals == theta_hat))
    p0 = max(0.5 / B, min(1.0 - 0.5 / B, p0))
    z0 = float(stats.norm.ppf(p0))

    # Jackknife acceleration a_hat
    tot = float(np.sum(x))
    jack = (tot - x) / float(n - 1)
    jack_diff = float(np.mean(jack)) - jack
    num = float(np.sum(jack_diff ** 3))
    den = 6.0 * (float(np.sum(jack_diff ** 2)) ** 1.5)
    a_hat = num / den if den > 1e-18 else 0.0

    z_lo = float(stats.norm.ppf(alpha / 2.0))
    z_hi = float(stats.norm.ppf(1.0 - alpha / 2.0))

    def _adj_q(z_a):
        den_q = 1.0 - a_hat * (z0 + z_a)
        if abs(den_q) < 1e-12:
            return 0.5
        return float(stats.norm.cdf(z0 + (z0 + z_a) / den_q))

    q_lo = max(0.0, min(1.0, _adj_q(z_lo)))
    q_hi = max(0.0, min(1.0, _adj_q(z_hi)))
    ci_low = float(np.quantile(boot_vals, q_lo))
    ci_high = float(np.quantile(boot_vals, q_hi))

    return {
        "point_est": sf(theta_hat, 6),
        "ci_95_low": sf(ci_low, 6),
        "ci_95_high": sf(ci_high, 6),
        "z0": sf(z0, 4),
        "acc_hat": sf(a_hat, 4),
        "q_adj_low": sf(q_lo, 4),
        "q_adj_high": sf(q_hi, 4),
    }


def wilson_ci_95(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    z = 1.959963984540054
    p = k / n
    den = 1.0 + z * z / n
    ctr = (p + z * z / (2.0 * n)) / den
    hlf = (z * math.sqrt((p * (1.0 - p) + z * z / (4.0 * n)) / n)) / den
    return max(0.0, ctr - hlf), min(1.0, ctr + hlf)


def calc_runs_autocorr_kelly(rets: np.ndarray, rng: np.random.Generator = RNG) -> dict:
    n = len(rets)
    wins = (rets > 0).astype(int)
    n1 = int(wins.sum())
    n0 = int(n - n1)

    # Observed runs
    runs = 1 + int(np.sum(wins[1:] != wins[:-1])) if n > 0 else 0
    if n1 > 0 and n0 > 0 and n > 1:
        mu_r = 1.0 + (2.0 * n1 * n0) / n
        var_r = (2.0 * n1 * n0 * (2.0 * n1 * n0 - n)) / ((n ** 2) * (n - 1.0))
        sd_r = math.sqrt(max(1e-12, var_r))
        z_runs = (runs - mu_r) / sd_r
        p_runs_norm = float(2.0 * stats.norm.sf(abs(z_runs)))
    else:
        mu_r, sd_r, z_runs, p_runs_norm = float(runs), 0.0, 0.0, 1.0

    # Observed max consecutive loss streak
    def max_zero_streak(arr):
        mx, cur = 0, 0
        for v in arr:
            if v == 0:
                cur += 1
                if cur > mx:
                    mx = cur
            else:
                cur = 0
        return mx

    actual_streak = max_zero_streak(wins)
    cur_prod, min_prod = 1.0, 1.0
    for r in rets:
        if r <= 0:
            cur_prod *= (1.0 + r)
            if cur_prod < min_prod:
                min_prod = cur_prod
        else:
            cur_prod = 1.0

    # 10,000 random permutations for exact runs p-value & simulated max loss streak distribution
    mc_runs = np.empty(MC_RUNS_B, dtype=int)
    mc_streaks = np.empty(MC_RUNS_B, dtype=int)
    base_arr = wins.copy()
    for b in range(MC_RUNS_B):
        perm = rng.permutation(base_arr)
        mc_runs[b] = 1 + int(np.sum(perm[1:] != perm[:-1]))
        mc_streaks[b] = max_zero_streak(perm)
    p_runs_mc = float(np.mean(np.abs(mc_runs - mu_r) >= abs(runs - mu_r)))

    # Lag-1 & Lag-2 autocorrelation + P(Loss_t | Loss_{t-1})
    def lag_acf(arr, lag):
        if len(arr) <= lag + 2 or np.std(arr[:-lag]) < 1e-12 or np.std(arr[lag:]) < 1e-12:
            return None, None
        c, p = stats.pearsonr(arr[:-lag], arr[lag:])
        return float(c), float(p)

    acf1, p_acf1 = lag_acf(rets, 1)
    acf2, p_acf2 = lag_acf(rets, 2)
    loss_bin = (rets <= 0).astype(float)
    acf1_loss, p_acf1_loss = lag_acf(loss_bin, 1)

    prev_l = loss_bin[:-1] == 1
    curr_l = loss_bin[1:] == 1
    n_ll = int(np.sum(prev_l & curr_l))
    n_lw = int(np.sum(prev_l & (~curr_l)))
    n_wl = int(np.sum((~prev_l) & curr_l))
    n_ww = int(np.sum((~prev_l) & (~curr_l)))
    p_l_given_l = float(n_ll / max(1, n_ll + n_lw)) if (n_ll + n_lw) > 0 else None
    p_l_given_w = float(n_wl / max(1, n_wl + n_ww)) if (n_wl + n_ww) > 0 else None
    _, fisher_p = stats.fisher_exact([[n_ll, n_lw], [n_wl, n_ww]]) if n > 2 else (1.0, 1.0)

    # Exact Numerical Kelly vs Mean-Variance Kelly
    r_min = float(np.min(rets))
    ruin_f = (-1.0 / r_min) if r_min < -1e-9 else 10.0
    upper_f = max(0.0, min(10.0, ruin_f * 0.999))
    mu_r_val = float(np.mean(rets))
    var_r_val = float(np.var(rets, ddof=1)) if n > 1 else 1e-6

    if mu_r_val <= 0 or upper_f <= 0:
        f_exact = 0.0
        g_full = 0.0
    else:
        def neg_exp_log(f):
            arg = 1.0 + f * rets
            if np.any(arg <= 1e-12):
                return 1e9
            return -float(np.mean(np.log(arg)))
        res_k = opt.minimize_scalar(neg_exp_log, bounds=(0.0, upper_f), method="bounded")
        f_exact = float(res_k.x)
        g_full = -float(res_k.fun)

    g_at_100 = float(np.mean(np.log(np.maximum(1e-12, 1.0 + rets))))
    f_mv = (mu_r_val / var_r_val) if var_r_val > 1e-12 else 0.0

    return {
        "wald_wolfowitz_runs": {
            "n_trades": int(n),
            "n_wins": n1,
            "n_losses": n0,
            "observed_runs": int(runs),
            "expected_runs": sf(mu_r, 2),
            "std_runs": sf(sd_r, 2),
            "z_stat": sf(z_runs, 3),
            "p_value_norm": sf(p_runs_norm, 4),
            "p_value_mc_10k": sf(p_runs_mc, 4),
            "randomness_rejected_5pct": bool(p_runs_mc < 0.05),
        },
        "consecutive_loss_tail": {
            "actual_max_consec_losses": int(actual_streak),
            "actual_max_consec_loss_ret_pct": sf((min_prod - 1.0) * 100.0, 2),
            "mc_10k_mean_max_streak": sf(mc_streaks.mean(), 2),
            "mc_10k_p95_max_streak": int(np.quantile(mc_streaks, 0.95)),
            "mc_10k_p99_max_streak": int(np.quantile(mc_streaks, 0.99)),
            "mc_prob_ge_actual_pct": sf((mc_streaks >= actual_streak).mean() * 100.0, 2),
        },
        "serial_dependence": {
            "lag1_ret_acf": sf(acf1, 4),
            "lag1_ret_p": sf(p_acf1, 4),
            "lag2_ret_acf": sf(acf2, 4),
            "lag2_ret_p": sf(p_acf2, 4),
            "lag1_loss_binary_acf": sf(acf1_loss, 4),
            "lag1_loss_binary_p": sf(p_acf1_loss, 4),
            "p_loss_uncond_pct": sf((n0 / n) * 100.0, 2),
            "p_loss_given_prev_loss_pct": sf(p_l_given_l * 100.0, 2) if p_l_given_l is not None else None,
            "p_loss_given_prev_win_pct": sf(p_l_given_w * 100.0, 2) if p_l_given_w is not None else None,
            "transition_counts_LL_LW_WL_WW": [n_ll, n_lw, n_wl, n_ww],
            "fisher_exact_p_loss_clustering": sf(fisher_p, 4),
        },
        "kelly_position_sizing": {
            "worst_trade_ret_pct": sf(r_min * 100.0, 2),
            "ruin_leverage_limit_pct": sf(ruin_f * 100.0, 1) if r_min < 0 else None,
            "full_kelly_exact_pct": sf(f_exact * 100.0, 1),
            "half_kelly_exact_pct": sf(0.5 * f_exact * 100.0, 1),
            "full_kelly_unlevered_cap100_pct": sf(min(1.0, f_exact) * 100.0, 1),
            "half_kelly_unlevered_cap100_pct": sf(min(1.0, 0.5 * f_exact) * 100.0, 1),
            "expected_log_growth_at_full_kelly_pct": sf(g_full * 100.0, 3),
            "expected_log_growth_at_100pct_pct": sf(g_at_100 * 100.0, 3),
            "full_kelly_mv_approx_pct": sf(f_mv * 100.0, 1),
            "half_kelly_mv_approx_pct": sf(0.5 * f_mv * 100.0, 1),
            "mv_vs_exact_ratio": sf(f_mv / f_exact, 3) if f_exact > 1e-6 else None,
        },
    }


# ==============================================================================
# WRC / SPA CANDIDATE RULE FAMILY BUILDERS (FROM AUTHENTIC LOCAL CLEAN POOLS)
# ==============================================================================

def _water_delta(df: pd.DataFrame, fid: str, mode: str, shape: str, step: float) -> np.ndarray:
    if fid == "F1":
        v = df["zb_rate_t1"].to_numpy(dtype=float)
        sw = (v >= 25.0) & (v <= 40.0)
        dg = ~sw
        sc = df["s_zb_t1"].to_numpy(dtype=float)
    elif fid == "F2":
        v = df["max_b_drop5_t1"].to_numpy(dtype=float)
        sw, dg = v >= 2.0, v <= 0.0
        sc = df["s_mb_t1"].to_numpy(dtype=float)
    elif fid == "F3":
        v = df["dt_3d_t1"].to_numpy(dtype=float)
        sw, dg = v >= 40.0, v <= 12.0
        sc = df["s_dt_t1"].to_numpy(dtype=float)
    elif fid == "F4":
        v = df["prem_3d_t1"].to_numpy(dtype=float)
        sw, dg = v <= 1.0, v > 3.0
        sc = df["s_p3_t1"].to_numpy(dtype=float)
    else:
        v = df["v2_idx_t1"].to_numpy(dtype=float)
        sw, dg = v >= 65.0, v < 45.0
        sc = v
    if shape == "discrete":
        if mode == "plus":
            return np.where(sw, step, 0.0)
        if mode == "minus":
            return np.where(dg, -step, 0.0)
        return np.where(sw, step, np.where(dg, -step, 0.0))
    else:
        u = (sc - 50.0) / 50.0
        if mode == "plus":
            return step * np.maximum(0.0, u)
        if mode == "minus":
            return -step * np.maximum(0.0, -u)
        return step * u


def sim_3to4_rule(pool: pd.DataFrame, scores: np.ndarray, thr: float, op_cap: float = 9.9) -> pd.DataFrame:
    m = (scores >= thr) & (pool["open_pct"].to_numpy(dtype=float) <= op_cap)
    sub = pool[m].copy()
    if sub.empty:
        return sub
    sub["_sc"] = scores[m]
    sub["_prio"] = sub["_sc"] * 10.0 + sub["prio_tie"] * 0.1
    srt = sub.sort_values(["buy_date", "buy_hhmm", "_prio", "code"], ascending=[True, True, False, True])
    taken, fd, fh = [], "", 0
    for r in srt.itertuples(index=False):
        if (not fd) or (r.buy_date > fd) or (r.buy_date == fd and int(r.buy_hhmm) > fh):
            taken.append(r._asdict())
            fd, fh = str(r.exit_date), int(r.exit_hhmm)
    return pd.DataFrame(taken)


def sim_high_rule(pool: pd.DataFrame, scores: np.ndarray, thr: float, use_cb: bool = False,
                  op_cap: float = 9.9, only_b_open_h: bool | None = None) -> pd.DataFrame:
    m = (scores >= thr) & (pool["open_pct"].to_numpy(dtype=float) <= op_cap)
    if only_b_open_h is not None:
        m = m & (pool["b_open_h"].to_numpy(dtype=bool) == only_b_open_h)
    sub = pool[m].copy()
    if sub.empty:
        return sub
    sub["_sc"] = scores[m]
    srt = sub.sort_values(["buy_date", "_sc", "code"], ascending=[True, False, True])
    taken, fd, peo, cl, sk = [], "", False, 0, False
    for r in srt.itertuples(index=False):
        if fd == "" or r.buy_date > fd or (r.buy_date == fd and peo and (not bool(r.b_open_h))):
            if use_cb and sk:
                fd, peo = str(r.exit_date), bool(r.eo)
                if float(r.net_ret) > 0.0:
                    sk, cl = False, 0
                continue
            taken.append(r._asdict())
            fd, peo = str(r.exit_date), bool(r.eo)
            if float(r.net_ret) < -0.02:
                cl += 1
                if cl >= 2:
                    sk = True
            elif float(r.net_ret) > 0.0:
                cl = 0
    return pd.DataFrame(taken)


def sim_2to3_rule(pool: pd.DataFrame, scores: np.ndarray, thr: float, op_cap: float = 9.9) -> pd.DataFrame:
    m = (scores >= thr) & (pool["open_pct"].to_numpy(dtype=float) <= op_cap)
    sub = pool[m].copy()
    if sub.empty:
        return sub
    sub["_sc"] = scores[m]
    srt = sub.sort_values(["buy_date", "_sc", "open_pct", "plate_sz", "code"], ascending=[True, False, True, True, True])
    taken, fd, fh = [], "", 0
    for r in srt.itertuples(index=False):
        if (not fd) or (r.buy_date > fd) or (r.buy_date == fd and int(r.buy_hhmm) > fh):
            taken.append(r._asdict())
            fd, fh = str(r.exit_date), int(r.exit_hhmm)
    return pd.DataFrame(taken)


def sim_pry_rule(pool: pd.DataFrame, scores: np.ndarray, thr: float, bias_max: float = 0.0) -> pd.DataFrame:
    m = (scores >= thr) & (pool["bias10"].to_numpy(dtype=float) <= bias_max)
    sub = pool[m].copy()
    if sub.empty:
        return sub
    sub["_sc"] = scores[m]
    srt = sub.sort_values(["buy_date", "_sc", "bias10", "code"], ascending=[True, False, True, True])
    taken, fd = [], ""
    for r in srt.itertuples(index=False):
        if (not fd) or (r.buy_date > fd):
            taken.append(r._asdict())
            fd = str(r.exit_date)
    return pd.DataFrame(taken)


def sim_1to2_pretrig_rule(pretrig: pd.DataFrame, delta: np.ndarray, force_base: bool = False) -> pd.DataFrame:
    if force_base:
        sub = pretrig[pretrig["base_pass_v19"]].copy()
        sub["_sv"] = sub["sv_base"]
    else:
        sc_adj = pretrig["base_score"].to_numpy() + delta
        m_t1 = pretrig["elig_t1"].to_numpy() & (sc_adj >= pretrig["thr_vec"].to_numpy())
        m_t2 = pretrig["elig_t2"].to_numpy()
        m_mon = pretrig["elig_mon"].to_numpy() & (sc_adj >= pretrig["thr_vec"].to_numpy())
        m_dom = pretrig["elig_dom295"].to_numpy() & ((sc_adj - pretrig["sc_t3_pen"].to_numpy()) >= 295.0)
        tot_v18 = m_t1 | m_t2 | m_mon
        tot_v19 = tot_v18 | m_dom
        if not tot_v19.any():
            return pd.DataFrame()
        sv = np.where(m_t1 | m_t2, sc_adj + 1000.0, np.where(m_mon, sc_adj, sc_adj + 500.0))
        sub = pretrig[tot_v19].copy()
        sub["_sv"] = sv[tot_v19]
        sub["_is_v18"] = tot_v18[tot_v19]
        bad_dts, dom_no_dragon = set(), set()
        for d, grp in sub.groupby("buy_date", sort=False):
            if (grp["rk_theme"] == 1).any():
                top_rk = grp.sort_values("_sv", ascending=False).iloc[0]["rk_theme"]
                if top_rk >= 4:
                    bad_dts.add(d)
            t1_p = grp["t1_dom_plate"].iloc[0]
            if t1_p:
                v18_g = grp[grp["_is_v18"]]
                if not (len(v18_g) > 0 and (v18_g["plate"] == t1_p).any()):
                    dom_no_dragon.add(d)
        keep = (~sub["buy_date"].isin(bad_dts)) & (~(sub["buy_date"].isin(dom_no_dragon) & (sub["rk_theme"] == 3)))
        sub = sub[keep].copy()
    if sub.empty:
        return pd.DataFrame()
    sub.sort_values(["buy_date", "_sv", "code"], ascending=[True, False, True], inplace=True)
    picked, free_dt, free_open = [], "", False
    for d2, grp in sub.groupby("buy_date", sort=True):
        if free_dt == "" or d2 > free_dt or (d2 == free_dt and free_open):
            top = grp.iloc[0]
            if bool(top["sim_ok"]):
                picked.append(top.to_dict())
                free_dt = str(top["exit_date"])
                free_open = bool(top["exit_at_open"])
    return pd.DataFrame(picked)


def sim_combined_slot(pool_5: pd.DataFrame, prio_map: dict[str, int]) -> pd.DataFrame:
    d = pool_5.copy()
    d["_p"] = d["strat_key"].map(prio_map)
    d = d[d["_p"].notna()].sort_values(["buy_date", "_p", "score", "buy_hhmm", "code"],
                                       ascending=[True, True, False, True, True])
    taken, fd, fh = [], "", 0
    for r in d.itertuples(index=False):
        if (not fd) or (r.buy_date > fd) or (r.buy_date == fd and int(r.buy_hhmm) > fh):
            taken.append(r._asdict())
            fd, fh = str(r.exit_date), int(r.exit_hhmm)
    return pd.DataFrame(taken)


def build_rule_family_matrix(key: str, active_ledger: pd.DataFrame, active_daily: np.ndarray,
                             pools: dict, pretrig_1to2: pd.DataFrame, ledgers_dict: dict,
                             t_days: list[str], day_idx: dict, by_c: dict, mtm_cache: dict) -> tuple[np.ndarray, dict]:
    """Construct M=50..181 authentic rule variants -> (T, M) daily MTM matrix with column 0 == active rule."""
    cols_list = [active_daily]
    rule_names = [f"{key}_ACTIVE"]
    base_map = {"3to4_v41": "pool_3to4", "high_v51": "pool_high", "2to3_v21": "pool_2to3",
                "pry_v21_ss165": "pool_pry", "1to2_v19": "pool_1to2"}

    if key in ("3to4_v41", "high_v51", "2to3_v21", "pry_v21_ss165"):
        pool = pools[base_map[key]].copy()
        pool["code"] = pool["code"].astype(str).str.zfill(6)
        pool["buy_date"] = pool["buy_date"].astype(str).str[:10]
        pool["exit_date"] = pool["exit_date"].astype(str).str[:10]
        b_sc = pool["base_score"].to_numpy(dtype=float)

        if key == "3to4_v41":
            for thr in [65, 70, 75, 80, 82, 85, 86, 88, 89, 91, 92, 94, 96, 98, 100, 102, 105]:
                tr = sim_3to4_rule(pool, b_sc, thr)
                d_vec, _ = trades_to_daily_mtm(tr, t_days, day_idx, by_c, mtm_cache)
                cols_list.append(d_vec); rule_names.append(f"thr_{thr}")
            for op in [0.00, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08]:
                tr = sim_3to4_rule(pool, b_sc, 90.0, op_cap=op)
                d_vec, _ = trades_to_daily_mtm(tr, t_days, day_idx, by_c, mtm_cache)
                cols_list.append(d_vec); rule_names.append(f"thr90_op_{op}")
            for fid in ("F1", "F2", "F3", "F4", "F_comp"):
                for mode in ("plus", "minus", "bidir"):
                    for shape in ("discrete", "linear"):
                        for step in (2, 4, 6, 8, 10, 12):
                            sc = b_sc + _water_delta(pool, fid, mode, shape, float(step))
                            tr = sim_3to4_rule(pool, sc, 90.0)
                            d_vec, _ = trades_to_daily_mtm(tr, t_days, day_idx, by_c, mtm_cache)
                            cols_list.append(d_vec); rule_names.append(f"{fid}_{mode}_{shape}_{step}")
            fam_desc = "3to4 clean pool (N=318): 17 score thresholds [65..105] + 8 open_pct caps + 180 T-1 market water variants"

        elif key == "high_v51":
            for thr in [60, 65, 70, 75, 80, 84, 88, 90, 92, 96, 100, 105, 110]:
                for cb in (False, True):
                    tr = sim_high_rule(pool, b_sc, thr, use_cb=cb)
                    d_vec, _ = trades_to_daily_mtm(tr, t_days, day_idx, by_c, mtm_cache)
                    cols_list.append(d_vec); rule_names.append(f"thr_{thr}_cb{int(cb)}")
            for op in [-0.03, 0.0, 0.02, 0.04]:
                tr = sim_high_rule(pool, b_sc, 88.0, use_cb=False, op_cap=op)
                d_vec, _ = trades_to_daily_mtm(tr, t_days, day_idx, by_c, mtm_cache)
                cols_list.append(d_vec); rule_names.append(f"op_{op}")
            for obh in (True, False):
                tr = sim_high_rule(pool, b_sc, 88.0, use_cb=False, only_b_open_h=obh)
                d_vec, _ = trades_to_daily_mtm(tr, t_days, day_idx, by_c, mtm_cache)
                cols_list.append(d_vec); rule_names.append(f"b_open_h_{obh}")
            for fid in ("F1", "F2", "F3", "F4", "F_comp"):
                for mode in ("plus", "minus", "bidir"):
                    for shape in ("discrete", "linear"):
                        for step in (2, 4, 6, 8, 10, 12):
                            sc = b_sc + _water_delta(pool, fid, mode, shape, float(step))
                            tr = sim_high_rule(pool, sc, 88.0, use_cb=True)
                            d_vec, _ = trades_to_daily_mtm(tr, t_days, day_idx, by_c, mtm_cache)
                            cols_list.append(d_vec); rule_names.append(f"{fid}_{mode}_{shape}_{step}")
            fam_desc = "High V5.1 clean pool (N=62): 26 threshold/CB rules + 6 entry filters + 180 T-1 market water variants (deduplicated to unique return series for transparency)"

        elif key == "2to3_v21":
            for thr in [65, 70, 75, 80, 82, 85, 86, 88, 89, 91, 92, 94, 96, 98, 100]:
                tr = sim_2to3_rule(pool, b_sc, thr)
                d_vec, _ = trades_to_daily_mtm(tr, t_days, day_idx, by_c, mtm_cache)
                cols_list.append(d_vec); rule_names.append(f"thr_{thr}")
            for op in [0.00, 0.02, 0.04, 0.05, 0.06, 0.07]:
                tr = sim_2to3_rule(pool, b_sc, 90.0, op_cap=op)
                d_vec, _ = trades_to_daily_mtm(tr, t_days, day_idx, by_c, mtm_cache)
                cols_list.append(d_vec); rule_names.append(f"op_{op}")
            for fid in ("F1", "F2", "F3", "F4", "F_comp"):
                for mode in ("plus", "minus", "bidir"):
                    for shape in ("discrete", "linear"):
                        for step in (2, 4, 6, 8, 10):
                            sc = b_sc + _water_delta(pool, fid, mode, shape, float(step))
                            tr = sim_2to3_rule(pool, sc, 90.0)
                            d_vec, _ = trades_to_daily_mtm(tr, t_days, day_idx, by_c, mtm_cache)
                            cols_list.append(d_vec); rule_names.append(f"{fid}_{mode}_{shape}_{step}")
            fam_desc = "2to3 clean pool (N=1532): 15 score thresholds [65..100] + 6 open_pct caps + 150 T-1 market water variants"

        else:  # pry_v21_ss165
            for thr in [120, 130, 140, 145, 150, 155, 160, 170, 175, 180, 185, 190, 195, 200]:
                tr = sim_pry_rule(pool, b_sc, thr)
                d_vec, _ = trades_to_daily_mtm(tr, t_days, day_idx, by_c, mtm_cache)
                cols_list.append(d_vec); rule_names.append(f"thr_{thr}")
            for bmax in [-0.14, -0.16, -0.18, -0.20, -0.22]:
                tr = sim_pry_rule(pool, b_sc, 165.0, bias_max=bmax)
                d_vec, _ = trades_to_daily_mtm(tr, t_days, day_idx, by_c, mtm_cache)
                cols_list.append(d_vec); rule_names.append(f"bias_{bmax}")
            for fid in ("F1", "F2", "F3", "F4", "F_comp"):
                for mode in ("plus", "minus", "bidir"):
                    for shape in ("discrete", "linear"):
                        for step in (5, 10, 15, 20, 25):
                            sc = b_sc + _water_delta(pool, fid, mode, shape, float(step))
                            tr = sim_pry_rule(pool, sc, 165.0)
                            d_vec, _ = trades_to_daily_mtm(tr, t_days, day_idx, by_c, mtm_cache)
                            cols_list.append(d_vec); rule_names.append(f"{fid}_{mode}_{shape}_{step}")
            fam_desc = "Pry clean pool (N=759): 14 score thresholds [120..200] + 5 bias10 caps + 150 T-1 market water variants"

    elif key == "1to2_v19":
        pt = pretrig_1to2.copy()
        pt["code"] = pt["code"].astype(str).str.zfill(6)
        pt["buy_date"] = pt["buy_date"].astype(str).str[:10]
        pt["exit_date"] = pt["exit_date"].astype(str).str[:10]
        pt = pt[pt["buy_date"] >= CANON_START].copy().reset_index(drop=True)
        for fid in ("F1", "F2", "F3", "F4", "F_comp"):
            for mode in ("plus", "minus", "bidir"):
                for shape in ("discrete", "linear"):
                    for step in (5, 10, 15, 20, 25, 30):
                        delta = _water_delta(pt, fid, mode, shape, float(step))
                        tr = sim_1to2_pretrig_rule(pt, delta, force_base=False)
                        d_vec, _ = trades_to_daily_mtm(tr, t_days, day_idx, by_c, mtm_cache)
                        cols_list.append(d_vec); rule_names.append(f"{fid}_{mode}_{shape}_{step}")
        fam_desc = "1to2 pretrig clean pool (N=703, sim_ok=447): exact V19 active + 180 T-1 market water variants (5 factors x 3 modes x 2 shapes x 6 steps)"

    else:  # combined_5strat_v191_slot1
        import itertools
        # Build union of 5 clean constituent streams: 3to4, high, pry_top1, 2to3, 1to2
        s_names = ["3to4", "high", "pry", "2to3", "1to2"]
        cols_keep = ["buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name", "score", "buy_price", "exit_price", "net_ret"]
        base_streams = {
            "3to4": norm_ledger(ledgers_dict["3to4_v41"])[cols_keep].assign(strat_key="3to4"),
            "high": norm_ledger(ledgers_dict["high_v51"])[cols_keep].assign(strat_key="high"),
            "pry": norm_ledger(ledgers_dict["pry_v21_top1"])[cols_keep].assign(strat_key="pry"),
            "2to3": norm_ledger(ledgers_dict["2to3_v21"])[cols_keep].assign(strat_key="2to3"),
            "1to2": norm_ledger(ledgers_dict["1to2_v19"])[cols_keep].assign(strat_key="1to2"),
        }
        pool_5 = pd.concat(list(base_streams.values()), ignore_index=True)

        # All 5! = 120 priority permutations across the 5 strategies
        for perm in itertools.permutations(s_names):
            if perm == ("3to4", "high", "pry", "2to3", "1to2"):
                continue  # Already column 0
            pmap = {s: idx + 1 for idx, s in enumerate(perm)}
            tr = sim_combined_slot(pool_5, pmap)
            d_vec, _ = trades_to_daily_mtm(tr, t_days, day_idx, by_c, mtm_cache)
            cols_list.append(d_vec); rule_names.append("perm_" + "_".join(perm))

        # Plus 31 subset / leave-one-out / threshold-tightening rules across the 5 clean pools
        base_prio = {"3to4": 1, "high": 2, "pry": 3, "2to3": 4, "1to2": 5}
        for drop_s in s_names:
            pmap = {s: p for s, p in base_prio.items() if s != drop_s}
            tr = sim_combined_slot(pool_5, pmap)
            d_vec, _ = trades_to_daily_mtm(tr, t_days, day_idx, by_c, mtm_cache)
            cols_list.append(d_vec); rule_names.append(f"drop_{drop_s}")
        for pair in itertools.combinations(s_names, 2):
            pmap = {s: p for s, p in base_prio.items() if s not in pair}
            tr = sim_combined_slot(pool_5, pmap)
            d_vec, _ = trades_to_daily_mtm(tr, t_days, day_idx, by_c, mtm_cache)
            cols_list.append(d_vec); rule_names.append(f"drop_{pair[0]}_{pair[1]}")

        # Threshold tightening variants on the 5 pools
        p34 = pools["pool_3to4"].rename(columns={"base_score": "score"}).assign(strat_key="3to4")
        p23 = pools["pool_2to3"].rename(columns={"base_score": "score"}).assign(strat_key="2to3")
        p12 = pools["pool_1to2"].rename(columns={"base_score": "score"}).assign(strat_key="1to2")
        ph = pools["pool_high"].rename(columns={"base_score": "score"}).assign(strat_key="high")
        pp = pools["pool_pry"].rename(columns={"base_score": "score"}).assign(strat_key="pry")
        for c_df in (p34, p23, p12, ph, pp):
            c_df["code"] = c_df["code"].astype(str).str.zfill(6)
            c_df["buy_date"] = c_df["buy_date"].astype(str).str[:10]
            c_df["exit_date"] = c_df["exit_date"].astype(str).str[:10]
        for q_off in (-4, -2, 2, 4, 6, 8, 10):
            p_var = pd.concat([
                p34[p34["score"] >= 90 + q_off][cols_keep + ["strat_key"]],
                ph[ph["score"] >= 88 + q_off][cols_keep + ["strat_key"]],
                pp[pp["score"] >= 165 + q_off * 2][cols_keep + ["strat_key"]],
                p23[p23["score"] >= 90 + q_off][cols_keep + ["strat_key"]],
                p12[p12["score"] >= 304.8 + q_off * 3][cols_keep + ["strat_key"]],
            ], ignore_index=True)
            tr = sim_combined_slot(p_var, base_prio)
            d_vec, _ = trades_to_daily_mtm(tr, t_days, day_idx, by_c, mtm_cache)
            cols_list.append(d_vec); rule_names.append(f"thresh_shift_{q_off:+d}")

        fam_desc = "Combined 5-strat single-slot rules: active baseline + 119 priority permutations (all 5!=120) + 15 leave-1/2-out subsets + 7 joint score-threshold shifts"

    mat_full = np.column_stack(cols_list)  # (T, M_total)
    # Deduplicate identical columns while preserving column 0
    seen = {}
    uniq_idx = []
    for j in range(mat_full.shape[1]):
        h = hash(mat_full[:, j].round(10).tobytes())
        if h not in seen:
            seen[h] = j
            uniq_idx.append(j)
    mat_uniq = mat_full[:, uniq_idx]
    meta = {
        "family_description": fam_desc,
        "M_total_rules": int(mat_full.shape[1]),
        "M_unique_series": int(mat_uniq.shape[1]),
    }
    return mat_uniq, meta


def main():
    t0 = time.time()
    os.makedirs(OUT_DIR, exist_ok=True)
    print("[1/4] Loading ledgers, candidate pools, and collecting unique codes...")

    ledgers = {}
    for m in TARGETS_META:
        ledgers[m["key"]] = norm_ledger(pd.read_csv(m["ledger_path"]))
    ledgers["pry_v21_top1"] = norm_ledger(pd.read_csv(f"{PARTC_DIR}/ledger_pry_v21_top1_clean.csv"))

    pools = {
        "pool_3to4": pd.read_csv(f"{MW_DIR}/part1_3to4_high/pool_3to4_full_clean.csv"),
        "pool_high": pd.read_csv(f"{MW_DIR}/part1_3to4_high/pool_high_full_clean.csv"),
        "pool_2to3": pd.read_csv(f"{MW_DIR}/part2_2to3_pry/pool_2to3_full_clean.csv"),
        "pool_pry": pd.read_csv(f"{MW_DIR}/part2_2to3_pry/pool_pry_full_clean.csv"),
        "pool_1to2": pd.read_csv(f"{MW_DIR}/part3_1to2/pool_1to2_full_clean.csv"),
    }
    pretrig_1to2 = pd.read_parquet(f"{MW_DIR}/part3_1to2/_cache_pretrig_pool.parquet")

    codes_needed = set()
    for df in ledgers.values():
        codes_needed.update(df["code"].astype(str).str.zfill(6))
    for df in pools.values():
        codes_needed.update(df["code"].astype(str).str.zfill(6))
    codes_needed.update(pretrig_1to2["code"].astype(str).str.zfill(6))

    print(f"[2/4] Loading PIT daily bars for {len(codes_needed)} unique stocks & CSI 300...")
    sh300, all_sh_dts, t_days, day_idx, csi_daily, by_c = load_market_and_prices(codes_needed)
    csi_5y_ret = float(np.prod(1.0 + csi_daily) - 1.0)
    T = len(t_days)
    print(f"      Calendar T={T} trading days ({t_days[0]}..{t_days[-1]}), CSI300 5Y={csi_5y_ret*100:.2f}%")

    # Pre-generate stationary bootstrap weight matrices for B=5000 at L=10, 5, 20 (shared CRN across strategies!)
    print(f"[3/4] Generating Stationary Bootstrap weight matrices (B={BOOT_B}, L=10/5/20)...")
    W_dict = {L: stationary_bootstrap_weights(T, BOOT_B, float(L), RNG) for L in (10, 5, 20)}

    # Build standardized 5-pool merged reference for combined
    merged_5pool_frames = []
    for pname, skey, thr in [
        ("pool_3to4", "3to4", 90.0), ("pool_high", "high", 88.0),
        ("pool_pry", "pry", 165.0), ("pool_2to3", "2to3", 90.0), ("pool_1to2", "1to2", 304.8),
    ]:
        p_sub = pools[pname].copy()
        p_sub["code"] = p_sub["code"].astype(str).str.zfill(6)
        p_sub["buy_date"] = p_sub["buy_date"].astype(str).str[:10]
        mu_s, sd_s = p_sub["base_score"].mean(), p_sub["base_score"].std(ddof=1)
        p_sub["score_z_within_pool"] = (p_sub["base_score"] - mu_s) / sd_s
        p_sub["strat_key"] = skey
        merged_5pool_frames.append(p_sub[["buy_date", "code", "strat_key", "base_score", "score_z_within_pool", "net_ret"]])
    merged_5pool = pd.concat(merged_5pool_frames, ignore_index=True)

    mtm_cache = {}
    results = {
        "metadata": {
            "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "canonical_window": {"start": CANON_START, "end": CANON_END, "prior_ref": "2021-11-15", "trading_days": T},
            "csi300_5y_ret_pct": sf(csi_5y_ret * 100.0, 2),
            "yfinance_imported": False,
            "fee_verification": {
                "empirical_implied_multiplier": 0.9980,
                "original_roundtrip_bps": 20.0,
                "original_one_way_bps": 10.0,
                "note": "Verified empirically across all 6 clean ledgers in partC_clean_ledgers_v191 via price DB adj_close/buy_price/exit_price.",
            },
            "bootstrap_params": {"B_stationary": BOOT_B, "L_main": 10, "L_sensitivity": [5, 20], "B_bca": BOOT_B, "MC_runs": MC_RUNS_B},
        },
        "targets": {},
        "auxiliary_targets": {},
    }

    all_runs = TARGETS_META + [{
        "key": "pry_v21_top1",
        "label": "超跌撬板 V2.1 (每日Top1含重叠对照)",
        "ledger_path": f"{PARTC_DIR}/ledger_pry_v21_top1_clean.csv",
        "pool_path": f"{MW_DIR}/part2_2to3_pry/pool_pry_full_clean.csv",
        "threshold": 165.0,
        "pool_type": "full_candidate_pool",
        "pool_note": "同 pry_v21_ss165 全池 (N=759)，真账允许跨日重叠持仓 (8处重叠)",
    }]

    print("[4/4] Computing Pillar 4 & Pillar 5 for 6 main targets + 1 auxiliary...")
    for m in all_runs:
        key = m["key"]
        df_ld = ledgers[key].copy()
        is_aux = (key == "pry_v21_top1")
        rets_tr = df_ld["net_ret"].to_numpy(dtype=float)
        n_tr = len(rets_tr)

        # Daily MTM series
        daily_mtm, nav_diff = trades_to_daily_mtm(df_ld, t_days, day_idx, by_c, mtm_cache, allow_overlap=is_aux)
        nav_5y_tr = float(np.prod(1.0 + rets_tr))
        nav_5y_mtm = float(np.prod(1.0 + daily_mtm))
        cum_tr = np.cumprod(1.0 + rets_tr)
        pk_tr = np.maximum.accumulate(np.insert(cum_tr, 0, 1.0))[1:]
        mdd_tr = float(np.max((pk_tr - cum_tr) / pk_tr) * 100.0)
        cum_d = np.cumprod(1.0 + daily_mtm)
        pk_d = np.maximum.accumulate(np.insert(cum_d, 0, 1.0))[1:]
        mdd_d = float(np.max((pk_d - cum_d) / pk_d) * 100.0)

        basic = {
            "label": m["label"],
            "n_trades": int(n_tr),
            "date_range": [str(df_ld["buy_date"].min()), str(df_ld["exit_date"].max())],
            "win_rate_pct": sf((rets_tr > 0).mean() * 100.0, 2),
            "mean_net_ret_pct": sf(rets_tr.mean() * 100.0, 3),
            "median_net_ret_pct": sf(np.median(rets_tr) * 100.0, 3),
            "std_net_ret_pct": sf(rets_tr.std(ddof=1) * 100.0, 3),
            "skewness_trade": sf(stats.skew(rets_tr, bias=False), 3) if n_tr > 2 else None,
            "excess_kurtosis_trade": sf(stats.kurtosis(rets_tr, fisher=True, bias=False), 3) if n_tr > 3 else None,
            "nav_5y_trade": sf(nav_5y_tr, 4),
            "nav_5y_mtm_daily": sf(nav_5y_mtm, 4),
            "mtm_nav_reconcile_diff": sf(nav_diff, 10),
            "mdd_trade_pct": sf(mdd_tr, 2),
            "mdd_mtm_daily_pct": sf(mdd_d, 2),
        }

        # -------------------- PILLAR 4 --------------------
        if m["pool_path"] is not None:
            pool_key = {"3to4_v41": "pool_3to4", "high_v51": "pool_high", "pry_v21_ss165": "pool_pry",
                        "pry_v21_top1": "pool_pry", "2to3_v21": "pool_2to3", "1to2_v19": "pool_1to2"}[key]
            df_pool = pools[pool_key].copy()
            min_roll_n = 5 if key == "high_v51" else 10
            ic_full = calc_ic_block(df_pool, "base_score", "net_ret", min_period_n=4, min_roll_n=min_roll_n)
            mono_full_q5 = calc_quantile_bins(df_pool["base_score"].to_numpy(dtype=float), df_pool["net_ret"].to_numpy(dtype=float), 5, "value_qcut")
            mono_full_q5_bal = calc_quantile_bins(df_pool["base_score"].to_numpy(dtype=float), df_pool["net_ret"].to_numpy(dtype=float), 5, "rank_balanced")
            mono_full_d10 = calc_quantile_bins(df_pool["base_score"].to_numpy(dtype=float), df_pool["net_ret"].to_numpy(dtype=float), 10, "value_qcut")
            mono_full_d10_bal = calc_quantile_bins(df_pool["base_score"].to_numpy(dtype=float), df_pool["net_ret"].to_numpy(dtype=float), 10, "rank_balanced")
            cal_full = calc_classification_calibration(df_pool, "base_score")

            thr = m["threshold"]
            p_pass = df_pool[df_pool["base_score"] >= thr]["net_ret"].to_numpy(dtype=float)
            p_fail = df_pool[df_pool["base_score"] < thr]["net_ret"].to_numpy(dtype=float)
            t_pf, p_pf = stats.ttest_ind(p_pass, p_fail, equal_var=False) if (len(p_pass) > 1 and len(p_fail) > 1) else (0.0, 1.0)
            pass_vs_fail = {
                "threshold": thr,
                "n_pass": int(len(p_pass)), "wr_pass_pct": sf((p_pass > 0).mean() * 100.0, 2), "mean_pass_pct": sf(p_pass.mean() * 100.0, 3),
                "n_fail": int(len(p_fail)), "wr_fail_pct": sf((p_fail > 0).mean() * 100.0, 2), "mean_fail_pct": sf(p_fail.mean() * 100.0, 3),
                "pass_minus_fail_pp": sf((p_pass.mean() - p_fail.mean()) * 100.0, 3),
                "welch_t": sf(t_pf, 3), "welch_p": sf(p_pf, 6),
            }
            pool_block = {
                "pool_status": m["pool_type"],
                "pool_note": m["pool_note"],
                "ic_and_decay": ic_full,
                "monotonicity_q5_value": mono_full_q5,
                "monotonicity_q5_balanced": mono_full_q5_bal,
                "monotonicity_d10_value": mono_full_d10,
                "monotonicity_d10_balanced": mono_full_d10_bal,
                "pass_vs_fail_threshold": pass_vs_fail,
                "classification_calibration": cal_full,
            }
        else:
            # combined_5strat_v191_slot1: explicit disclosure + 5-pool within-strategy z-score reference
            ic_5p_z = calc_ic_block(merged_5pool, "score_z_within_pool", "net_ret", min_period_n=4, min_roll_n=10)
            mono_5p_q5 = calc_quantile_bins(merged_5pool["score_z_within_pool"].to_numpy(dtype=float), merged_5pool["net_ret"].to_numpy(dtype=float), 5, "value_qcut")
            mono_5p_d10 = calc_quantile_bins(merged_5pool["score_z_within_pool"].to_numpy(dtype=float), merged_5pool["net_ret"].to_numpy(dtype=float), 10, "value_qcut")
            cal_5p_z = calc_classification_calibration(merged_5pool, "score_z_within_pool")
            pool_block = {
                "pool_status": m["pool_type"],
                "pool_note": m["pool_note"],
                "combined_5pool_within_strat_zscore_ref": {
                    "ic_and_decay": ic_5p_z,
                    "monotonicity_q5": mono_5p_q5,
                    "monotonicity_d10": mono_5p_d10,
                    "classification_calibration": cal_5p_z,
                },
            }

        # Within-ledger controls
        if key == "combined_5strat_v191_slot1":
            # Compute within-strategy z-score and within-strategy pct-rank inside combined ledger
            df_ld["score_z_within_strat"] = df_ld.groupby("strategy")["score"].transform(lambda s: (s - s.mean()) / max(1e-9, s.std(ddof=1)))
            df_ld["score_pct_within_strat"] = df_ld.groupby("strategy")["score"].rank(pct=True)
            within_ledger_block = {
                "note": "合体真账原始 score 混杂5种不同标尺 (90~430)，主看策略内标准化 z-score 与分位 rank，另附原始混合分对照",
                "within_strat_zscore": {
                    "ic_and_decay": calc_ic_block(df_ld, "score_z_within_strat", "net_ret", min_period_n=4, min_roll_n=10),
                    "monotonicity_q5": calc_quantile_bins(df_ld["score_z_within_strat"].to_numpy(dtype=float), rets_tr, 5, "value_qcut"),
                    "monotonicity_d10": calc_quantile_bins(df_ld["score_z_within_strat"].to_numpy(dtype=float), rets_tr, 10, "value_qcut"),
                    "classification_calibration": calc_classification_calibration(df_ld, "score_z_within_strat"),
                },
                "within_strat_pct_rank": {
                    "ic_and_decay": calc_ic_block(df_ld, "score_pct_within_strat", "net_ret", min_period_n=4, min_roll_n=10),
                    "monotonicity_q5": calc_quantile_bins(df_ld["score_pct_within_strat"].to_numpy(dtype=float), rets_tr, 5, "value_qcut"),
                    "classification_calibration": calc_classification_calibration(df_ld, "score_pct_within_strat"),
                },
                "raw_mixed_score_confounded_ctrl": {
                    "ic_and_decay": calc_ic_block(df_ld, "score", "net_ret", min_period_n=4, min_roll_n=10),
                    "monotonicity_q5": calc_quantile_bins(df_ld["score"].to_numpy(dtype=float), rets_tr, 5, "value_qcut"),
                },
            }
        else:
            within_ledger_block = {
                "ic_and_decay": calc_ic_block(df_ld, "score", "net_ret", min_period_n=4, min_roll_n=5 if n_tr < 50 else 10),
                "monotonicity_q5_value": calc_quantile_bins(df_ld["score"].to_numpy(dtype=float), rets_tr, 5, "value_qcut"),
                "monotonicity_q5_balanced": calc_quantile_bins(df_ld["score"].to_numpy(dtype=float), rets_tr, 5, "rank_balanced"),
                "classification_calibration": calc_classification_calibration(df_ld, "score"),
            }

        be_cost = calc_breakeven_cost(rets_tr, csi_5y_ret)
        holding_decay = calc_holding_decay(df_ld, by_c, sh300, all_sh_dts)

        pillar4 = {
            "candidate_pool_analysis": pool_block,
            "within_ledger_analysis": within_ledger_block,
            "breakeven_transaction_cost": be_cost,
            "holding_period_decay": holding_decay,
        }

        # -------------------- PILLAR 5 --------------------
        # PSR & MinTRL: Daily MTM basis + Trade-level basis
        trades_per_year = float(n_tr) / YEARS_5Y
        daily_excess_csi = daily_mtm - csi_daily
        trade_csi_hold = np.array([get_csi_period_ret(sh300, all_sh_dts, r.buy_date, r.exit_date) for r in df_ld.itertuples(index=False)], dtype=float)
        trade_excess_csi = rets_tr - trade_csi_hold

        psr_block = {
            "daily_mtm_basis": {
                "annualize_days": ANN_DAYS,
                "vs_zero": calc_psr_mintrl(daily_mtm, float(ANN_DAYS), 1.0),
                "vs_csi300": calc_psr_mintrl(daily_excess_csi, float(ANN_DAYS), 1.0),
            },
            "trade_level_basis": {
                "trades_per_year_5y": sf(trades_per_year, 2),
                "vs_zero": calc_psr_mintrl(rets_tr, trades_per_year, 1.0),
                "vs_csi300_holding": calc_psr_mintrl(trade_excess_csi, trades_per_year, 1.0),
            },
        }

        # WRC & Hansen SPA
        if not is_aux:
            mat_M, fam_meta = build_rule_family_matrix(key, df_ld, daily_mtm, pools, pretrig_1to2, ledgers, t_days, day_idx, by_c, mtm_cache)
            b_opt_pw = politis_white_opt_block_len(daily_mtm)
            wrc_spa = {
                "family_meta": {**fam_meta, "politis_white_opt_L_days": sf(b_opt_pw, 2)},
                "vs_cash0": run_wrc_and_spa(mat_M, W_dict, L_main=10),
                "vs_csi300": run_wrc_and_spa(mat_M - csi_daily[:, None], W_dict, L_main=10),
            }
        else:
            wrc_spa = {"note": "Auxiliary overlapping multi-slot reference; WRC/SPA evaluated on single-slot pry_v21_ss165."}

        # 95% BCa Bootstrap CI
        bca_mean = bca_bootstrap_ci(rets_tr * 100.0, B=BOOT_B, alpha=0.05, rng=RNG)
        bca_wr = bca_bootstrap_ci((rets_tr > 0).astype(float) * 100.0, B=BOOT_B, alpha=0.05, rng=RNG)
        w_lo, w_hi = wilson_ci_95(int((rets_tr > 0).sum()), n_tr)
        bca_wr["wilson_95_ci_pct"] = [sf(w_lo * 100.0, 2), sf(w_hi * 100.0, 2)]
        bca_block = {
            "mean_net_ret_pct": {**bca_mean, "excludes_zero": bool(bca_mean["ci_95_low"] > 0)},
            "win_rate_pct": bca_wr,
        }

        # Runs test, streak tail, autocorrelation, Kelly
        seq_kelly = calc_runs_autocorr_kelly(rets_tr, rng=RNG)

        pillar5 = {
            "psr_and_mintrl": psr_block,
            "multiple_testing_wrc_spa": wrc_spa,
            "bca_bootstrap_95ci": bca_block,
            **seq_kelly,
        }

        entry = {"basic_summary": basic, "pillar4_signal_and_turnover": pillar4, "pillar5_statistical_confidence_and_sequence": pillar5}
        if is_aux:
            results["auxiliary_targets"][key] = entry
        else:
            results["targets"][key] = entry

        print(f"  [{key}] n={n_tr} | NAV={nav_5y_tr:.2f}x (mtm_diff={nav_diff:.1e}) | BE_OW_geom={be_cost['breakeven_ow_geom_5y_bps']}bps | "
              f"PSR_d={psr_block['daily_mtm_basis']['vs_zero']['psr_sr_gt_0']} | "
              f"FullKelly={seq_kelly['kelly_position_sizing']['full_kelly_exact_pct']}%")

    out_json = f"{OUT_DIR}/part2_signal_stats.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, allow_nan=False)

    print(f"DONE in {time.time() - t0:.2f}s -> {out_json}")


if __name__ == "__main__":
    main()

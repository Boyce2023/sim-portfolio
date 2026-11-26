#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD043 Step 2: Comprehensive Blind Matrix (5Y & WF) + Multi-Factor Expanding Walk-Forward Scorecard.

Evaluates:
  - Part A: 5-year (2021-01-04..2026-11-24) & WF-window (2023-01-03..2026-11-24) Blind Matrix across:
      * Proto A (10cm/20cm, >=1/3/5 yi, clv>=0.75/0.85, break20, strong mainline)
      * Proto B (ice-point old dragon, >=2/3 boards, strict zt<40, ret>=3%)
      * Proto C (prior ZT/lianban divergence + heavy turnover green close, broken ZT red)
      * All 5 exits (E1_T1O, E2_T1C_HoldZT, E2b_PureT1C, E3a_Open0_Hold, E3b_Open15_Hold)
      * All 4 cost tiers (30, 50, 80, 120 bps round-trip)
      * Single-slot Top-1 vs Same-day Equal-Weight, ex3/ex5/ex10, yearly 2021..2026 + 26H2
  - Part B: Multi-Factor Expanding Walk-Forward Scorecard (exit_date < t) across 15 tracks:
      * 3 causal scoring families: RD035 Scorecard 0-100, Causal Equal-Weight Direction, Causal IC-Weighted
      * Thresholds: all_cands, top30, top20, top10, top5, abs_70, abs_75, abs_80
      * 4 cost tiers (30/50/80/120 bps), ex5/ex10, DSR, permutation p, CSI300 excess, MTM reconciliation

Zero yfinance (D12). Peak RSS < 1.6 GB.
"""
import os
for _k in (
    "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS",
):
    os.environ[_k] = "1"

import gc
import json
import math
import resource
import sys
import time
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
BASE_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd043_tail_rush_arbitrage_20261126"
PQ_PATH = f"{OUT_DIR}/rd043_tail_events_pit.parquet"

if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import wf_scorecard_engine as wf
import _wf_sim_and_metrics as wfm

TRD_DAYS_YEAR = 242.0

CAUSAL_FEATURES = [
    "dist_hi10", "dist_hi20", "dist_hi60",
    "clv", "upper_shad", "lower_shad", "ret_1d", "intraday_gain", "open_pct", "dist_zt_pct",
    "turn_pct", "vol_ratio5_t", "turn_5_20_t1", "log_amt_t", "log_mcap_t1",
    "zt_cnt_20d_t1", "max_stk_40d_t1", "cool_days_since_last_zt",
    "csrc_ind_zt_share5_t1", "csrc_ind_ex5_t1", "ind_t_zt_cnt", "kpl_in_t1",
    "L1_zt_cnt_t1", "L1_zb_rate_t1", "mkt_t_up_pct", "rel_str_vs_mkt",
    "mkt_down_streak_t1", "dd_20d_t1", "bias10_t1",
]


def peak_rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 2)


def sanitize_json(obj):
    if isinstance(obj, dict):
        return {str(k): sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_json(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return None if (math.isnan(v) or math.isinf(v)) else round(v, 6)
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    return obj


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_ppf(p: float) -> float:
    lo, hi = -8.0, 8.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if _norm_cdf(mid) < p:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def compute_dsr(dr: np.ndarray, n_trials: int) -> dict:
    T = len(dr)
    if T < 30 or np.std(dr, ddof=1) < 1e-12:
        return {"n_trials": n_trials, "sr_ann": 0.0, "sr0_ann": 0.0, "dsr": 0.0}
    sr_d = float(np.mean(dr) / np.std(dr, ddof=1))
    sr_ann = sr_d * math.sqrt(TRD_DAYS_YEAR)
    z = (dr - np.mean(dr)) / np.std(dr, ddof=1)
    skew = float(np.mean(z ** 3))
    kurt = float(np.mean(z ** 4))
    var_sr_d = (0.35 ** 2) / TRD_DAYS_YEAR
    gamma = 0.5772156649
    sr0_d = math.sqrt(var_sr_d) * (
        (1.0 - gamma) * _norm_ppf(1.0 - 1.0 / max(2, n_trials))
        + gamma * _norm_ppf(1.0 - 1.0 / (max(2, n_trials) * math.e))
    )
    denom_sq = max(1e-12, (1.0 - skew * sr_d + ((kurt - 1.0) / 4.0) * (sr_d ** 2)) / (T - 1))
    dsr_val = _norm_cdf((sr_d - sr0_d) / math.sqrt(denom_sq))
    return {
        "n_trials": n_trials,
        "sr_ann": round(sr_ann, 3),
        "sr0_ann": round(sr0_d * math.sqrt(TRD_DAYS_YEAR), 3),
        "dsr": round(dsr_val, 4),
    }


def attach_net_mtm_tuples(df: pd.DataFrame, mtm_json_col: str, fee_rt: float, dt_to_idx: dict[str, int]) -> list:
    f_buy = fee_rt * 0.5
    f_sell_mult = (1.0 - fee_rt) / (1.0 - f_buy)
    out = []
    for s in df[mtm_json_col]:
        arr = json.loads(s) if isinstance(s, str) and s else []
        if not arr:
            out.append(())
            continue
        loc = []
        last_i = len(arr) - 1
        for k, (d_str, mult) in enumerate(arr):
            ti = dt_to_idx.get(d_str)
            m_val = float(mult)
            if k == 0:
                m_val *= (1.0 - f_buy)
            if k == last_i:
                m_val *= f_sell_mult
            if ti is not None:
                loc.append((ti, m_val))
        out.append(tuple(loc))
    return out


def eval_slice_stats(
    df_sub: pd.DataFrame,
    ex_pref: str,
    tie_col: str,
    bench_df: pd.DataFrame,
    start_dt: str,
    end_dt: str,
    fee_rt: float = 0.0030,
) -> dict:
    """Fast vectorized single-slot & equal-weight evaluation for blind matrix."""
    sub = df_sub[(df_sub["buy_date"] >= start_dt) & (df_sub["buy_date"] <= end_dt)].copy()
    sub["exit_date"] = sub[f"{ex_pref}_exit_date"].astype(str).str[:10]
    sub["exit_hhmm"] = sub[f"{ex_pref}_exit_hhmm"].astype(int)
    sub["gross_ret"] = pd.to_numeric(sub[f"{ex_pref}_gross_ret"], errors="coerce")
    sub = sub[sub["gross_ret"].notna() & (sub["exit_date"] > sub["buy_date"]) & (sub["exit_date"] <= "2026-11-25")].copy()
    if sub.empty:
        return {"n_cands": 0, "n_slot": 0, "nav": 1.0, "eq_nav": 1.0}

    sub["net_ret"] = (1.0 + sub["gross_ret"].to_numpy(float)) * (1.0 - fee_rt) - 1.0
    sub["can_buy_hygiene"] = True
    sub["dummy_score"] = sub[tie_col].fillna(0.0).to_numpy(float)

    pass_df, slot_df = wfm.select_single_slot_trades(
        sub, score_col="dummy_score", threshold=None, tie_col="amount_yi", wf_only=False
    )
    b_win = bench_df[bench_df["trade_date"].between(start_dt, "2026-11-25")].sort_values("trade_date").reset_index(drop=True)
    cal_dts = b_win["trade_date"].astype(str).tolist()
    dt_idx = {d: i for i, d in enumerate(cal_dts)}
    csi_arr = b_win["csi300_daily_ret"].to_numpy(float)

    slot_df = slot_df.copy()
    slot_df["mtm_t"] = attach_net_mtm_tuples(slot_df, f"{ex_pref}_mtm_json", fee_rt, dt_idx)
    dr, mtm_diff = wfm.build_daily_mtm_returns(slot_df, cal_dts, mtm_col="mtm_t")
    assert mtm_diff < 1e-4, f"MTM mismatch: {mtm_diff}"

    rets = slot_df["net_ret"].to_numpy(float)
    nav = float(np.prod(1.0 + rets)) if len(rets) else 1.0
    sr = np.sort(rets)
    ex3 = float(np.prod(1.0 + sr[:-3])) if len(rets) > 3 else 1.0
    ex5 = float(np.prod(1.0 + sr[:-5])) if len(rets) > 5 else 1.0
    ex10 = float(np.prod(1.0 + sr[:-10])) if len(rets) > 10 else 1.0
    wr = float((rets > 0).mean() * 100.0) if len(rets) else 0.0
    mean_pct = float(rets.mean() * 100.0) if len(rets) else 0.0

    w = rets[rets > 0]
    l = rets[rets <= 0]
    plr = float(w.mean() / abs(l.mean())) if (len(w) and len(l) and l.mean() < 0) else 0.0

    # Equal-weight daily portfolio
    eq_d = pass_df.groupby("buy_date")["net_ret"].mean().to_numpy(float)
    eq_nav = float(np.prod(1.0 + eq_d)) if len(eq_d) else 1.0
    eq_mean = float(eq_d.mean() * 100.0) if len(eq_d) else 0.0

    T = len(cal_dts)
    sd = float(np.std(dr, ddof=1)) if T > 1 else 0.0
    sharpe = float(np.mean(dr) / sd * math.sqrt(TRD_DAYS_YEAR)) if sd > 1e-12 else 0.0
    curve = np.concatenate([[1.0], np.cumprod(1.0 + dr)])
    pk = np.maximum.accumulate(curve)
    mdd = float(np.max((pk - curve) / pk) * 100.0)
    csi_pct = (float(np.prod(1.0 + csi_arr)) - 1.0) * 100.0

    # Multi-cost NAV quick calc on selected slot trades
    gr_s = slot_df["gross_ret"].to_numpy(float)
    nav_50 = float(np.prod(1.0 + ((1.0 + gr_s) * (1.0 - 0.0050) - 1.0))) if len(gr_s) else 1.0
    nav_80 = float(np.prod(1.0 + ((1.0 + gr_s) * (1.0 - 0.0080) - 1.0))) if len(gr_s) else 1.0
    nav_120 = float(np.prod(1.0 + ((1.0 + gr_s) * (1.0 - 0.0120) - 1.0))) if len(gr_s) else 1.0

    # Yearly breakdown
    yr_navs = {}
    for y_lbl, y_lo, y_hi in [
        ("2021", "2021-01-01", "2021-12-31"),
        ("2022", "2022-01-01", "2022-12-31"),
        ("2023", "2023-01-01", "2023-12-31"),
        ("2024", "2024-01-01", "2024-12-31"),
        ("2025", "2025-01-01", "2025-12-31"),
        ("2026", "2026-01-01", "2026-12-31"),
        ("26H2", "2026-07-01", "2026-12-31"),
    ]:
        ym = slot_df["buy_date"].between(y_lo, y_hi).to_numpy()
        yr_navs[y_lbl] = round(float(np.prod(1.0 + rets[ym])), 3) if ym.any() else 1.0

    return {
        "n_cands": int(len(pass_df)),
        "n_slot": int(len(slot_df)),
        "wr_pct": round(wr, 2),
        "plr": round(plr, 2),
        "mean_pct": round(mean_pct, 3),
        "nav_30": round(nav, 4),
        "nav_50": round(nav_50, 4),
        "nav_80": round(nav_80, 4),
        "nav_120": round(nav_120, 4),
        "ex3_30": round(ex3, 4),
        "ex5_30": round(ex5, 4),
        "ex10_30": round(ex10, 4),
        "eq_nav_30": round(eq_nav, 4),
        "eq_mean_pct": round(eq_mean, 3),
        "sharpe": round(sharpe, 3),
        "mdd_pct": round(mdd, 2),
        "excess_csi_pp": round((nav - 1.0) * 100.0 - csi_pct, 2),
        "mtm_diff": round(mtm_diff, 8),
        "yr_navs": yr_navs,
    }


def run_causal_linear_wf(
    cand_df: pd.DataFrame,
    feature_cols: list[str],
    model_type: str = "EQ_DIR",  # "EQ_DIR" or "IC_WT"
    wf_start_date: str = "2023-01-03",
    min_warmup_trades: int = 80,
    recalc_freq: str = "monthly",
    top_k: int = 12,
    min_t_stat: float = 1.0,
    fee_rt: float = 0.0030,
) -> pd.DataFrame:
    """
    Causal expanding Walk-Forward alternative linear models (strictly exit_date < t):
      - EQ_DIR: select top_k factors with |cluster_t| >= min_t_stat, assign equal weight * sign(t) to z-scored features.
      - IC_WT: select top_k factors with |cluster_t| >= min_t_stat, weight by clipped t-stat / shrunk correlation.
    Maps score to expanding historical percentile [0, 100] so top30/top20/top10/top5 thresholds are 100% causal!
    """
    from _wf_core import _cluster_t_stat

    df = wfm.prepare_hygiene_and_net_ret(cand_df, fee_rt=fee_rt, gross_ret_col="gross_ret")
    n = len(df)
    buy_dts = df["buy_date"].astype(str).str[:10].to_numpy()
    exit_dts = df["exit_date"].astype(str).str[:10].to_numpy()
    codes = df["code"].astype(str).str.zfill(6).to_numpy()
    y_ret = df["net_ret"].to_numpy(float)
    can_buy = df["can_buy_hygiene"].to_numpy(bool) & np.isfinite(y_ret)

    X_all = df[feature_cols].apply(pd.to_numeric, errors="coerce").to_numpy(float)
    uniq_dts = sorted(set(buy_dts.tolist()))
    dt_to_id = {d: i for i, d in enumerate(uniq_dts)}
    day_ids = np.array([dt_to_id[d] for d in buy_dts], dtype=np.int32)

    buyable_idx = np.flatnonzero(can_buy)
    exit_order = sorted(buyable_idx.tolist(), key=lambda i: (exit_dts[i], buy_dts[i], codes[i]))
    e_arr = np.asarray(exit_order, dtype=np.int64)
    e_dts = exit_dts[e_arr]
    X_ex = X_all[e_arr]
    r_ex = y_ret[e_arr]
    d_ex = day_ids[e_arr]

    by_dt = {}
    for i in buyable_idx:
        by_dt.setdefault(buy_dts[i], []).append(i)

    wf_in = np.zeros(n, dtype=bool)
    wf_score = np.full(n, np.nan, dtype=float)
    t30 = np.full(n, np.nan, dtype=float)
    t20 = np.full(n, np.nan, dtype=float)
    t10 = np.full(n, np.nan, dtype=float)
    t5 = np.full(n, np.nan, dtype=float)

    ptr = 0
    n_ex = len(e_arr)
    last_m = ""
    last_ptr = -1
    model = None
    started = False

    for t in sorted(by_dt.keys()):
        while ptr < n_ex and e_dts[ptr] < t:
            ptr += 1
        if t < wf_start_date:
            continue
        if not started:
            if ptr >= min_warmup_trades:
                started = True
            else:
                continue
        if model is None or (recalc_freq == "monthly" and t[:7] != last_m) or (recalc_freq == "daily" and ptr > last_ptr):
            X_tr = X_ex[:ptr]
            r_tr = r_ex[:ptr]
            d_tr = d_ex[:ptr]
            mu_x = np.nanmean(X_tr, axis=0)
            sd_x = np.nanstd(X_tr, axis=0)
            sd_x = np.where((sd_x > 1e-9) & np.isfinite(sd_x), sd_x, 1.0)
            mu_x = np.where(np.isfinite(mu_x), mu_x, 0.0)
            Z_tr = np.nan_to_num((X_tr - mu_x) / sd_x, nan=0.0)
            Z_tr = np.clip(Z_tr, -3.5, 3.5)

            f_stats = []
            for j in range(Z_tr.shape[1]):
                valid_j = np.isfinite(X_tr[:, j])
                if valid_j.sum() < max(40, int(0.45 * ptr)):
                    continue
                tj = _cluster_t_stat(r_tr[valid_j], Z_tr[valid_j, j], d_tr[valid_j])
                f_stats.append((abs(tj), tj, j))
            f_stats.sort(key=lambda x: (-x[0], x[2]))
            sel = [x for x in f_stats if x[0] >= min_t_stat][:top_k]
            if len(sel) < 5:
                sel = f_stats[:min(5, len(f_stats))]
            w = np.zeros(Z_tr.shape[1], dtype=float)
            for abs_t, tj, j in sel:
                if model_type == "EQ_DIR":
                    w[j] = 1.0 if tj >= 0 else -1.0
                else:
                    w[j] = np.clip(tj, -4.0, 4.0)
            raw_tr = Z_tr @ w
            q70, q80, q90, q95 = np.percentile(raw_tr, [70, 80, 90, 95])
            model = (mu_x, sd_x, w, q70, q80, q90, q95, raw_tr)
            last_m = t[:7]
            last_ptr = ptr

        mu_x, sd_x, w, q70, q80, q90, q95, raw_tr = model
        rows_t = np.asarray(by_dt[t], dtype=np.int64)
        Zt = np.clip(np.nan_to_num((X_all[rows_t] - mu_x) / sd_x, nan=0.0), -3.5, 3.5)
        raw_t = Zt @ w
        # Map to 0..100 percentile relative to training distribution
        pct_t = np.searchsorted(np.sort(raw_tr), raw_t) / max(1, len(raw_tr)) * 100.0
        wf_in[rows_t] = True
        wf_score[rows_t] = pct_t
        t30[rows_t] = 70.0
        t20[rows_t] = 80.0
        t10[rows_t] = 90.0
        t5[rows_t] = 95.0

    df["wf_in_window"] = wf_in
    df["wf_score"] = wf_score
    df["wf_thr_top30"] = t30
    df["wf_thr_top20"] = t20
    df["wf_thr_top10"] = t10
    df["wf_thr_top5"] = t5
    return df


def main():
    t0 = time.time()
    print("[Step2] Loading rd043_tail_events_pit.parquet and V20 context...")
    df = pd.read_parquet(PQ_PATH)
    v20_ctx = wf.load_v20_reference_context(BASE_DIR)
    bench_df = v20_ctx["bench"]
    print(f"[Step2] Loaded {len(df):,} rows | RSS={peak_rss_mb()} MB")

    # =========================================================================
    # PART A: COMPREHENSIVE BLIND MATRIX (5Y 2021..2026 & WF 2023..2026)
    # =========================================================================
    print("\n[Step2-PartA] Running Blind Matrix across Prototypes A/B/C x Exits x Liquidity x Horizons...")
    strong_ml = (df["kpl_in_t1"] == 1) | (df["csrc_ind_zt_share5_t1"] >= 0.06) | (df["ind_t_zt_cnt"] >= 3)
    blind_slices = [
        ("A_10cm_1yi", (df["proto_A"] == 1) & (df["is_20cm"] == 0)),
        ("A_10cm_3yi", (df["proto_A"] == 1) & (df["is_20cm"] == 0) & (df["amount_yi"] >= 3.0)),
        ("A_10cm_5yi", (df["proto_A"] == 1) & (df["is_20cm"] == 0) & (df["amount_yi"] >= 5.0)),
        ("A_10cm_clv85", (df["proto_A"] == 1) & (df["is_20cm"] == 0) & (df["clv"] >= 0.85)),
        ("A_10cm_brk20", (df["proto_A"] == 1) & (df["is_20cm"] == 0) & (df["is_break_hi20"] == 1)),
        ("A_10cm_strongML_3yi", (df["proto_A"] == 1) & (df["is_20cm"] == 0) & (df["amount_yi"] >= 3.0) & strong_ml & (df["clv"] >= 0.85)),
        ("A_20cm_1yi", (df["proto_A"] == 1) & (df["is_20cm"] == 1)),
        ("A_20cm_3yi", (df["proto_A"] == 1) & (df["is_20cm"] == 1) & (df["amount_yi"] >= 3.0)),
        ("A_20cm_clv85", (df["proto_A"] == 1) & (df["is_20cm"] == 1) & (df["clv"] >= 0.85)),
        ("A_20cm_brk20", (df["proto_A"] == 1) & (df["is_20cm"] == 1) & (df["is_break_hi20"] == 1)),
        ("B_all_1yi", (df["proto_B"] == 1)),
        ("B_3yi", (df["proto_B"] == 1) & (df["amount_yi"] >= 3.0)),
        ("B_streak3plus", (df["proto_B"] == 1) & (df["max_stk_40d_t1"] >= 3)),
        ("B_ztlt40_ice", (df["proto_B"] == 1) & (df["L1_zt_cnt_t1"] < 40)),
        ("B_ret3_clv75", (df["proto_B"] == 1) & (df["ret_1d"] >= 3.0) & (df["clv"] >= 0.75)),
        ("B_ice_phase1", (df["proto_B"] == 1) & (df["L1_sent_phase_t1"] == 1)),
        ("C_all_1yi", (df["proto_C"] == 1)),
        ("C_lianban2plus", (df["proto_C"] == 1) & (df["prev_streak"] >= 2)),
        ("C_firstboard1", (df["proto_C"] == 1) & (df["prev_streak"] == 1)),
        ("C_clv80_ret3", (df["proto_C"] == 1) & (df["clv"] >= 0.80) & (df["ret_1d"] >= 3.0)),
        ("C_brokenzt_red", (df["proto_C"] == 1) & (df["is_broken_zt"] == 1)),
        ("ABC_union", (df["proto_A"] == 1) | (df["proto_B"] == 1) | (df["proto_C"] == 1)),
    ]

    blind_rows = []
    for s_name, mask in blind_slices:
        df_s = df[mask]
        tie_c = "clv" if s_name.startswith("A_") else ("max_stk_40d_t1" if s_name.startswith("B_") else "amount_yi")
        for ex_pref in ("E1_T1O", "E2_T1C_HoldZT", "E2b_PureT1C", "E3a_Open0_Hold", "E3b_Open15_Hold"):
            st_5y = eval_slice_stats(df_s, ex_pref, tie_c, bench_df, "2021-01-04", "2026-11-24", fee_rt=0.0030)
            st_wf = eval_slice_stats(df_s, ex_pref, tie_c, bench_df, "2023-01-03", "2026-11-24", fee_rt=0.0030)
            row = {
                "slice": s_name,
                "exit": ex_pref,
                "n_5y_cands": st_5y["n_cands"],
                "n_5y_slot": st_5y["n_slot"],
                "wr_5y": st_5y["wr_pct"],
                "mean_5y": st_5y["mean_pct"],
                "nav5y_30": st_5y["nav_30"],
                "nav5y_50": st_5y["nav_50"],
                "nav5y_80": st_5y["nav_80"],
                "nav5y_120": st_5y["nav_120"],
                "ex5_5y": st_5y["ex5_30"],
                "ex10_5y": st_5y["ex10_30"],
                "eq5y_30": st_5y["eq_nav_30"],
                "sh_5y": st_5y["sharpe"],
                "mdd_5y": st_5y["mdd_pct"],
                "n_wf_slot": st_wf["n_slot"],
                "wr_wf": st_wf["wr_pct"],
                "mean_wf": st_wf["mean_pct"],
                "nav_wf_30": st_wf["nav_30"],
                "nav_wf_80": st_wf["nav_80"],
                "ex5_wf": st_wf["ex5_30"],
                "eq_wf_30": st_wf["eq_nav_30"],
                "sh_wf": st_wf["sharpe"],
                "y2021": st_5y["yr_navs"]["2021"],
                "y2022": st_5y["yr_navs"]["2022"],
                "y2023": st_wf["yr_navs"]["2023"],
                "y2024": st_wf["yr_navs"]["2024"],
                "y2025": st_wf["yr_navs"]["2025"],
                "y2026": st_wf["yr_navs"]["2026"],
                "y26H2": st_wf["yr_navs"]["26H2"],
            }
            blind_rows.append(row)

    blind_df = pd.DataFrame(blind_rows)
    blind_df.to_csv(f"{OUT_DIR}/rd043_blind_matrix.csv", index=False)
    print(f"[Step2-PartA DONE] {len(blind_df)} blind configs saved | elapsed={time.time()-t0:.1f}s")
    print("\n--- Top 12 Blind Configs (by nav_wf_30 with n_wf_slot >= 30) ---")
    b_top = blind_df[blind_df["n_wf_slot"] >= 30].sort_values("nav_wf_30", ascending=False).head(12)
    print(b_top[["slice", "exit", "n_5y_slot", "nav5y_30", "ex5_5y", "eq5y_30", "n_wf_slot", "nav_wf_30", "nav_wf_80", "ex5_wf", "eq_wf_30", "sh_wf", "y2023", "y2024", "y2025", "y2026"]].to_string(index=False))

    # =========================================================================
    # PART B: MULTI-FACTOR EXPANDING WALK-FORWARD SCORECARD (exit_date < t)
    # =========================================================================
    print("\n[Step2-PartB] Running Expanding WF Scorecard across 15 Tracks x 3 Model Families...")
    wf_tracks = [
        ("T01_A_10cm_E1", (df["proto_A"] == 1) & (df["is_20cm"] == 0), "E1_T1O"),
        ("T02_A_10cm_E2", (df["proto_A"] == 1) & (df["is_20cm"] == 0), "E2_T1C_HoldZT"),
        ("T03_A_10cm_3yi_E1", (df["proto_A"] == 1) & (df["is_20cm"] == 0) & (df["amount_yi"] >= 3.0), "E1_T1O"),
        ("T04_A_10cm_E3a", (df["proto_A"] == 1) & (df["is_20cm"] == 0), "E3a_Open0_Hold"),
        ("T05_A_20cm_E1", (df["proto_A"] == 1) & (df["is_20cm"] == 1), "E1_T1O"),
        ("T06_A_20cm_E2", (df["proto_A"] == 1) & (df["is_20cm"] == 1), "E2_T1C_HoldZT"),
        ("T07_A_20cm_3yi_E1", (df["proto_A"] == 1) & (df["is_20cm"] == 1) & (df["amount_yi"] >= 3.0), "E1_T1O"),
        ("T08_A_All_E1", (df["proto_A"] == 1), "E1_T1O"),
        ("T09_B_All_E1", (df["proto_B"] == 1), "E1_T1O"),
        ("T10_B_All_E2", (df["proto_B"] == 1), "E2_T1C_HoldZT"),
        ("T11_B_All_E3a", (df["proto_B"] == 1), "E3a_Open0_Hold"),
        ("T12_B_Streak3_E1", (df["proto_B"] == 1) & (df["max_stk_40d_t1"] >= 3), "E1_T1O"),
        ("T13_C_All_E1", (df["proto_C"] == 1), "E1_T1O"),
        ("T14_C_Lianban_E1", (df["proto_C"] == 1) & (df["prev_streak"] >= 2), "E1_T1O"),
        ("T15_ABC_Union_E1", (df["proto_A"] == 1) | (df["proto_B"] == 1) | (df["proto_C"] == 1), "E1_T1O"),
    ]

    grid_rows = []
    # Also store latest factor scorecards for audit
    track_meta = {}

    b_wf = bench_df[bench_df["trade_date"].between("2023-01-03", "2026-11-25")].sort_values("trade_date").reset_index(drop=True)
    cal_wf = b_wf["trade_date"].astype(str).tolist()
    dt_idx_wf = {d: i for i, d in enumerate(cal_wf)}
    csi_wf = b_wf["csi300_daily_ret"].to_numpy(float)

    for tid, mask, ex_pref in wf_tracks:
        sub = df[mask].copy()
        sub["exit_date"] = sub[f"{ex_pref}_exit_date"].astype(str).str[:10]
        sub["exit_hhmm"] = sub[f"{ex_pref}_exit_hhmm"].astype(int)
        sub["gross_ret"] = pd.to_numeric(sub[f"{ex_pref}_gross_ret"], errors="coerce")
        sub = sub[sub["gross_ret"].notna() & (sub["exit_date"] > sub["buy_date"]) & (sub["exit_date"] <= "2026-11-25")].copy().reset_index(drop=True)

        # 1. RD035 Scorecard 0-100 (monthly rebuild for sweep speed)
        res = wf.run_wf_scorecard_new_strategy(
            sub, feature_cols=CAUSAL_FEATURES, v20_ctx=v20_ctx,
            wf_start_date="2023-01-03", end_date="2026-11-24",
            min_warmup_trades=80, min_warmup_trades_rare=50, min_warmup_months=18,
            recalc_freq="monthly", top_k=12, min_k=5, max_corr=0.65, min_t_stat=1.0,
            shrink_tau=20.0, fee_rt=0.0030, gross_ret_col="gross_ret",
            tie_col="amount_yi",
            thresholds=("all_cands", "top30", "top20", "top10", "top5", 70, 75, 80),
            eval_v20_patch=False, perm_n=200, seed=20261126,
        )
        track_meta[tid] = {
            "n_total_cands": int(len(sub)),
            "wf_actual_start": res["meta"]["wf_actual_start"],
            "n_rebuilds": res["meta"]["n_rebuilds"],
            "latest_factors": [
                {"name": f["name"], "t": f["t_cluster"], "shape": f["shape"], "pts": f["budget_pts"]}
                for f in res["meta"]["latest_scorecard"].get("factors", [])
            ],
        }

        for th_raw in ("all_cands", "top30", "top20", "top10", "top5", 70, 75, 80):
            th = f"abs_{th_raw}" if isinstance(th_raw, int) else th_raw
            obj = res["threshold_results"][th]
            slot = obj["slot_df"].copy()
            p_df = obj["pass_df"]
            ev = obj["metrics"]
            fw = ev["windows"].get("FULL_WF", {})
            y23 = ev["windows"].get("Y2023", {})
            y24 = ev["windows"].get("Y2024", {})
            y25 = ev["windows"].get("Y2025", {})
            y26 = ev["windows"].get("Y2026", {})

            if not slot.empty:
                slot["mtm_30"] = attach_net_mtm_tuples(slot, f"{ex_pref}_mtm_json", 0.0030, dt_idx_wf)
                dr30, mtm_diff = wfm.build_daily_mtm_returns(slot, cal_wf, mtm_col="mtm_30")
                assert mtm_diff < 1e-4, f"MTM diff {mtm_diff}"
                rets30 = slot["net_ret"].to_numpy(float)
                gr_s = slot["gross_ret"].to_numpy(float)
                sr_s = np.sort(rets30)
                ex5 = float(np.prod(1.0 + sr_s[:-5])) if len(rets30) > 5 else 1.0
                ex10 = float(np.prod(1.0 + sr_s[:-10])) if len(rets30) > 10 else 1.0
                nav50 = float(np.prod(1.0 + ((1.0 + gr_s) * (1.0 - 0.0050) - 1.0)))
                nav80 = float(np.prod(1.0 + ((1.0 + gr_s) * (1.0 - 0.0080) - 1.0)))
                nav120 = float(np.prod(1.0 + ((1.0 + gr_s) * (1.0 - 0.0120) - 1.0)))
                sd30 = float(np.std(dr30, ddof=1))
                sh30 = float(np.mean(dr30) / sd30 * math.sqrt(TRD_DAYS_YEAR)) if sd30 > 1e-12 else 0.0
                curve30 = np.concatenate([[1.0], np.cumprod(1.0 + dr30)])
                pk30 = np.maximum.accumulate(curve30)
                mdd30 = float(np.max((pk30 - curve30) / pk30) * 100.0)
                y26h2_m = slot["buy_date"].between("2026-07-01", "2026-12-31").to_numpy()
                nav_26h2 = float(np.prod(1.0 + rets30[y26h2_m])) if y26h2_m.any() else 1.0
                dsr_d = compute_dsr(dr30, n_trials=120)
            else:
                ex5 = ex10 = nav50 = nav80 = nav120 = nav_26h2 = 1.0
                sh30 = mdd30 = mtm_diff = 0.0
                dsr_d = {"dsr": 0.0, "sr0_ann": 0.0}

            grid_rows.append({
                "track_id": tid,
                "model": "RD035_SC",
                "exit": ex_pref,
                "threshold": th,
                "n_pass": int(len(p_df)),
                "n_trades": int(fw.get("n", 0)),
                "wr_pct": fw.get("wr_pct", 0.0),
                "plr": fw.get("plr", 0.0),
                "mean_pct": fw.get("mean_pct", 0.0),
                "nav_30": fw.get("nav", 1.0),
                "nav_50": round(nav50, 4),
                "nav_80": round(nav80, 4),
                "nav_120": round(nav120, 4),
                "ex3_30": fw.get("ex_top3_nav", 1.0),
                "ex5_30": round(ex5, 4),
                "ex10_30": round(ex10, 4),
                "eq_nav_30": fw.get("eq_nav", 1.0),
                "sharpe": round(sh30, 3),
                "mdd_pct": round(mdd30, 2),
                "excess_csi_pp": fw.get("excess_csi300_pp", 0.0),
                "y2023": y23.get("nav", 1.0),
                "y2024": y24.get("nav", 1.0),
                "y2025": y25.get("nav", 1.0),
                "y2026": y26.get("nav", 1.0),
                "y26H2": round(nav_26h2, 4),
                "perm_sd_p": ev["permutation_1000"]["same_day_p_nav"],
                "perm_any_p": ev["permutation_1000"]["any_cand_day_p_nav"],
                "dsr": dsr_d["dsr"],
                "mtm_diff": round(mtm_diff, 8),
            })

        # 2. Alternative scoring families (EQ_DIR & IC_WT) on the main prototype tracks
        if tid in ("T01_A_10cm_E1", "T02_A_10cm_E2", "T05_A_20cm_E1", "T09_B_All_E1", "T13_C_All_E1", "T15_ABC_Union_E1"):
            for mtype in ("EQ_DIR", "IC_WT"):
                scored_alt = run_causal_linear_wf(sub, CAUSAL_FEATURES, model_type=mtype, recalc_freq="monthly", fee_rt=0.0030)
                for th_nm, t_col in (("top30", "wf_thr_top30"), ("top20", "wf_thr_top20"), ("top10", "wf_thr_top10"), ("top5", "wf_thr_top5")):
                    p_df, slot = wfm.select_single_slot_trades(scored_alt, score_col="wf_score", threshold=t_col, tie_col="amount_yi", wf_only=True)
                    if slot.empty:
                        continue
                    slot = slot.copy()
                    slot["mtm_30"] = attach_net_mtm_tuples(slot, f"{ex_pref}_mtm_json", 0.0030, dt_idx_wf)
                    dr30, mtm_diff = wfm.build_daily_mtm_returns(slot, cal_wf, mtm_col="mtm_30")
                    rets30 = slot["net_ret"].to_numpy(float)
                    gr_s = slot["gross_ret"].to_numpy(float)
                    sr_s = np.sort(rets30)
                    nav30 = float(np.prod(1.0 + rets30))
                    ex5 = float(np.prod(1.0 + sr_s[:-5])) if len(rets30) > 5 else 1.0
                    ex10 = float(np.prod(1.0 + sr_s[:-10])) if len(rets30) > 10 else 1.0
                    nav50 = float(np.prod(1.0 + ((1.0 + gr_s) * (1.0 - 0.0050) - 1.0)))
                    nav80 = float(np.prod(1.0 + ((1.0 + gr_s) * (1.0 - 0.0080) - 1.0)))
                    nav120 = float(np.prod(1.0 + ((1.0 + gr_s) * (1.0 - 0.0120) - 1.0)))
                    eq_d = p_df.groupby("buy_date")["net_ret"].mean().to_numpy(float)
                    eq_nav = float(np.prod(1.0 + eq_d)) if len(eq_d) else 1.0
                    sd30 = float(np.std(dr30, ddof=1))
                    sh30 = float(np.mean(dr30) / sd30 * math.sqrt(TRD_DAYS_YEAR)) if sd30 > 1e-12 else 0.0
                    curve30 = np.concatenate([[1.0], np.cumprod(1.0 + dr30)])
                    pk30 = np.maximum.accumulate(curve30)
                    mdd30 = float(np.max((pk30 - curve30) / pk30) * 100.0)
                    csi_pct = (float(np.prod(1.0 + csi_wf)) - 1.0) * 100.0
                    yr_n = {
                        y: round(float(np.prod(1.0 + rets30[slot["buy_date"].str.startswith(y).to_numpy()])), 3)
                        if slot["buy_date"].str.startswith(y).any() else 1.0
                        for y in ("2023", "2024", "2025", "2026")
                    }
                    y26h2_m = slot["buy_date"].between("2026-07-01", "2026-12-31").to_numpy()
                    nav_26h2 = float(np.prod(1.0 + rets30[y26h2_m])) if y26h2_m.any() else 1.0
                    dsr_d = compute_dsr(dr30, n_trials=120)
                    w_pos = rets30[rets30 > 0]
                    l_neg = rets30[rets30 <= 0]
                    plr = float(w_pos.mean() / abs(l_neg.mean())) if (len(w_pos) and len(l_neg) and l_neg.mean() < 0) else 0.0
                    grid_rows.append({
                        "track_id": tid,
                        "model": mtype,
                        "exit": ex_pref,
                        "threshold": th_nm,
                        "n_pass": int(len(p_df)),
                        "n_trades": int(len(slot)),
                        "wr_pct": round(float((rets30 > 0).mean() * 100.0), 2),
                        "plr": round(plr, 2),
                        "mean_pct": round(float(rets30.mean() * 100.0), 3),
                        "nav_30": round(nav30, 4),
                        "nav_50": round(nav50, 4),
                        "nav_80": round(nav80, 4),
                        "nav_120": round(nav120, 4),
                        "ex3_30": round(float(np.prod(1.0 + sr_s[:-3])) if len(rets30) > 3 else 1.0, 4),
                        "ex5_30": round(ex5, 4),
                        "ex10_30": round(ex10, 4),
                        "eq_nav_30": round(eq_nav, 4),
                        "sharpe": round(sh30, 3),
                        "mdd_pct": round(mdd30, 2),
                        "excess_csi_pp": round((nav30 - 1.0) * 100.0 - csi_pct, 2),
                        "y2023": yr_n["2023"],
                        "y2024": yr_n["2024"],
                        "y2025": yr_n["2025"],
                        "y2026": yr_n["2026"],
                        "y26H2": round(nav_26h2, 4),
                        "perm_sd_p": np.nan,
                        "perm_any_p": np.nan,
                        "dsr": dsr_d["dsr"],
                        "mtm_diff": round(mtm_diff, 8),
                    })

        del res, sub
        gc.collect()
        print(f"  Done {tid} | RSS={peak_rss_mb()} MB")

    grid_df = pd.DataFrame(grid_rows)
    grid_df.to_csv(f"{OUT_DIR}/rd043_grid.csv", index=False)
    with open(f"{OUT_DIR}/_step2_track_meta.json", "w", encoding="utf-8") as f:
        json.dump(sanitize_json(track_meta), f, ensure_ascii=False, indent=2)

    print(f"\n[Step2-PartB DONE] {len(grid_df)} WF rows saved to rd043_grid.csv | elapsed={time.time()-t0:.1f}s | RSS={peak_rss_mb()} MB")
    print("\n--- Top 18 WF Scorecard Results (n_trades >= 30, sorted by nav_30) ---")
    top_wf = grid_df[(grid_df["n_trades"] >= 30) & (grid_df["threshold"] != "all_cands")].sort_values("nav_30", ascending=False).head(18)
    print(top_wf[["track_id", "model", "threshold", "n_trades", "wr_pct", "mean_pct", "nav_30", "nav_50", "nav_80", "nav_120", "ex5_30", "eq_nav_30", "sharpe", "y2023", "y2024", "y2025", "y2026", "perm_sd_p", "dsr"]].to_string(index=False))

    print("\n--- Best WF Result per Track ---")
    best_per_tr = grid_df[(grid_df["n_trades"] >= 20) & (grid_df["threshold"] != "all_cands")].sort_values("nav_30", ascending=False).groupby("track_id", as_index=False).first()
    print(best_per_tr[["track_id", "model", "threshold", "n_trades", "wr_pct", "nav_30", "nav_80", "ex5_30", "eq_nav_30", "sharpe", "y2023", "y2024", "y2025", "y2026", "perm_sd_p", "dsr"]].to_string(index=False))


if __name__ == "__main__":
    main()

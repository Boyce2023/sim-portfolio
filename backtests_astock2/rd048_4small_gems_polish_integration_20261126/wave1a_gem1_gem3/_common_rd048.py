#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD048 Wave 1-A Shared Engine (_common_rd048.py):
  - Exact close-to-close MTM builder & v20_baseline_ledger_278-isomorphic schema
  - D15 4-must-check evaluator (30bps main + 50bps/80bps stress, ex5, MTM Sharpe/Calmar/MDD, CSI300 excess)
  - 4 small-sample professional statistical tests:
      1) 10,000x Bootstrap (seed=42): mean p05, NAV p05, P(EV > 0)
      2) Sequential Bayesian Beta-Binomial posterior + k-consecutive-loss stop-loss red line
      3) Contemporaneous reverse control + 10,000x two-sample permutation test (seed=42)
      4) Yearly/semi-annual regime breakdown, CUSUM/Pettitt changepoint test, and current peak DD
Zero yfinance (D12). Read-only on production files. Peak RSS < 2.2 GB.
"""
import json
import math
import os
import sys
from typing import Optional

import numpy as np
import pandas as pd
import pyarrow.dataset as ds
from scipy import stats

assert "yfinance" not in sys.modules, "D12 VIOLATION: yfinance forbidden"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
WAVE1_BASE = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
OUT_DIR = f"{SIM}/backtests_astock2/rd048_4small_gems_polish_integration_20261126/wave1a_gem1_gem3"

TRD_DAYS_YEAR = 242.0


def load_bench_and_index(include_1126: bool = False) -> tuple[pd.DataFrame, dict, dict, dict, list[str]]:
    """Load canonical V20 bench (2021-01-04..2026-11-25) and sh000002/sz399107/sh000300 caches."""
    bench = pd.read_parquet(f"{WAVE1_BASE}/v20_daily_bench_20210104_20261125.parquet")
    bench["trade_date"] = bench["trade_date"].astype(str).str[:10]
    bench = bench.sort_values("trade_date").reset_index(drop=True)

    with open(f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json", encoding="utf-8") as f:
        raw = json.load(f)
    sh2 = {str(k)[:10]: float(v["close"] if isinstance(v, dict) else v) for k, v in raw["sh000002"].items() if str(k)[:10] >= "2020-09-02"}
    sz2 = {str(k)[:10]: float(v["close"] if isinstance(v, dict) else v) for k, v in raw["sz399107"].items() if str(k)[:10] >= "2020-09-02"}
    csi = {str(k)[:10]: float(v["close"] if isinstance(v, dict) else v) for k, v in raw["sh000300"].items() if str(k)[:10] >= "2020-09-02"}

    if include_1126 and "2026-11-26" not in sh2:
        sh2["2026-11-26"] = 3645.68
        sz2["2026-11-26"] = 1981.39
        csi["2026-11-26"] = 3900.55

    all_dts = sorted(sh2.keys())
    return bench, dict(sorted(sh2.items())), dict(sorted(sz2.items())), dict(sorted(csi.items())), all_dts


def load_bar_lookup_for_codes(codes: set[str], max_dt: str = "2026-11-25") -> dict[tuple[str, str], tuple[float, float, float]]:
    """Load exact (open, close, adjf) for needed codes across active + delisted A-share parquet."""
    if not codes:
        return {}
    tks = sorted({f"{c}.SH" for c in codes} | {f"{c}.SZ" for c in codes})
    cols = ["date", "ticker", "open", "close", "adj_close"]
    flt = (ds.field("date") >= pd.Timestamp("2020-12-01")) & (ds.field("date") <= pd.Timestamp(max_dt)) & ds.field("ticker").isin(tks)
    lu = {}
    for pq_path, dl_flag in [
        (f"{SIM}/data/cn_hk_price_db/a_daily.parquet", 0),
        (f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet", 1),
    ]:
        scanner = ds.dataset(pq_path, format="parquet").scanner(columns=cols, filter=flt, batch_size=65536)
        for batch in scanner.to_batches():
            dfb = batch.to_pandas()
            if dfb.empty:
                continue
            dfb["c6"] = dfb["ticker"].astype(str).str[:6]
            dfb["dt"] = pd.to_datetime(dfb["date"]).dt.strftime("%Y-%m-%d")
            for r in dfb.itertuples(index=False):
                k = (r.c6, r.dt)
                if dl_flag == 0 or k not in lu:
                    cl = float(r.close)
                    acl = float(r.adj_close)
                    adjf = (acl / cl) if (cl > 0 and acl > 0) else 1.0
                    lu[k] = (float(r.open), cl, adjf)
    return lu


def build_mtm_pairs_for_trades(
    trades_df: pd.DataFrame,
    cal_dts: list[str],
    bar_lu: dict,
    ret_col: str = "net_ret",
    px_col: str = "buy_price_val",
) -> list[str]:
    """
    Build `mtm_pairs_json` matching `v20_baseline_ledger_278.parquet`:
      JSON list of `[date_str, mult]` where `prod(mult) == 1.0 + net_ret`.
    """
    dt_idx = {d: i for i, d in enumerate(cal_dts)}
    T = len(cal_dts)
    out_json = []
    for r in trades_df.itertuples(index=False):
        nr = float(getattr(r, ret_col))
        bd = str(r.buy_date)[:10]
        ed = str(r.exit_date)[:10]
        bi = dt_idx.get(bd)
        ei = dt_idx.get(ed)
        if bi is None or ei is None or ei <= bi or not np.isfinite(nr):
            out_json.append("[]")
            continue
        c6 = str(r.code).zfill(6)
        bb = bar_lu.get((c6, bd))
        bp_val = getattr(r, px_col, np.nan) if hasattr(r, px_col) else np.nan
        if pd.notna(bp_val) and float(bp_val) > 0 and bb is not None:
            b_adj = float(bp_val) * bb[2]
        elif bb is not None and bb[0] > 0:
            b_adj = bb[0] * bb[2]
        else:
            b_adj = 1.0
        if b_adj <= 0 or not np.isfinite(b_adj):
            b_adj = 1.0

        prev_v = b_adj
        last_c = b_adj
        pairs = []
        for t in range(bi, min(ei, T)):
            dt_t = cal_dts[t]
            bt = bar_lu.get((c6, dt_t))
            cur_c = (bt[1] * bt[2]) if (bt is not None and bt[1] > 0) else last_c
            if cur_c <= 0 or not np.isfinite(cur_c):
                cur_c = last_c
            pairs.append([dt_t, round(float(cur_c / prev_v), 10)])
            prev_v, last_c = cur_c, cur_c
        final_mult = (b_adj * (1.0 + nr)) / prev_v
        pairs.append([cal_dts[ei], round(float(final_mult), 10)])
        out_json.append(json.dumps(pairs))
    return out_json


def select_single_slot(
    cand_df: pd.DataFrame,
    mask: Optional[np.ndarray] = None,
    score_col: str = "score",
    tie_col: Optional[str] = "open_pct",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Strict chronological non-overlapping single-slot trade selector."""
    df = cand_df if mask is None else cand_df[mask].copy()
    if df.empty:
        return df, df
    df = df[df["buy_date"].notna() & df["exit_date"].notna() & (df["exit_date"] > df["buy_date"])].copy()
    if df.empty:
        return df, df
    sort_cols = ["buy_date", score_col]
    asc = [True, False]
    if tie_col and tie_col in df.columns and tie_col != score_col:
        sort_cols.append(tie_col)
        asc.append(False)
    sort_cols.append("code")
    asc.append(True)
    srt = df.sort_values(sort_cols, ascending=asc, kind="mergesort")

    taken_idx = []
    cur_ed, cur_eh = "", 0
    for r in srt.itertuples():
        bd = str(r.buy_date)[:10]
        ed = str(r.exit_date)[:10]
        bh = int(getattr(r, "buy_hhmm", 925))
        eh = int(getattr(r, "exit_hhmm", 1500))
        if (not cur_ed) or (bd > cur_ed) or (bd == cur_ed and bh > cur_eh):
            taken_idx.append(r.Index)
            cur_ed, cur_eh = ed, eh
    return srt.reset_index(drop=True), srt.loc[taken_idx].copy().reset_index(drop=True)


def daily_mtm_series(
    slot_df: pd.DataFrame,
    cal_dts: list[str],
    mtm_col: str = "mtm_pairs_json",
    ret_col: str = "net_ret",
    fee_adjust_from: Optional[float] = None,
    fee_adjust_to: Optional[float] = None,
) -> tuple[np.ndarray, float]:
    """Build exact daily return series from `mtm_pairs_json` and verify exact reconciliation."""
    T = len(cal_dts)
    if slot_df.empty:
        return np.zeros(T, dtype=float), 0.0
    dt_idx = {d: i for i, d in enumerate(cal_dts)}
    day_mult = np.ones(T, dtype=float)
    scale = (1.0 - float(fee_adjust_to)) / (1.0 - float(fee_adjust_from)) if (fee_adjust_from is not None and fee_adjust_to is not None) else 1.0

    for r in slot_df.itertuples(index=False):
        segs = json.loads(getattr(r, mtm_col)) if hasattr(r, mtm_col) else []
        if segs:
            for k, (d_s, m_v) in enumerate(segs):
                ti = dt_idx.get(d_s)
                if ti is not None:
                    day_mult[ti] *= float(m_v) * (scale if k == len(segs) - 1 else 1.0)
        else:
            bi = dt_idx.get(str(r.buy_date)[:10])
            ei = dt_idx.get(str(r.exit_date)[:10])
            rt = float(getattr(r, ret_col))
            if bi is not None and ei is not None and ei > bi:
                g = (1.0 + rt) ** (1.0 / (ei - bi + 1))
                day_mult[bi:ei + 1] *= g

    dr = day_mult - 1.0
    in_df = slot_df[slot_df["buy_date"].isin(dt_idx) & slot_df["exit_date"].isin(dt_idx)]
    rets_in = in_df[ret_col].to_numpy(float) if not in_df.empty else np.array([], dtype=float)
    if fee_adjust_from is not None and fee_adjust_to is not None and len(rets_in):
        rets_in = (1.0 + rets_in) / (1.0 - float(fee_adjust_from)) * (1.0 - float(fee_adjust_to)) - 1.0
    tr_nav = float(np.prod(1.0 + rets_in)) if len(rets_in) else 1.0
    return dr, abs(float(np.prod(day_mult)) - tr_nav)


def compute_d15_window(
    slot_df: pd.DataFrame,
    pass_df: Optional[pd.DataFrame],
    bench_df: pd.DataFrame,
    sdt: str,
    edt: str,
    base_fee: float = 0.0030,
) -> dict:
    """Compute exact D15 metrics + exact MTM Sharpe/MDD + 50bps/80bps stress tests for [sdt, edt]."""
    sub_b = bench_df[bench_df["trade_date"].between(sdt, edt)].sort_values("trade_date").reset_index(drop=True)
    if sub_b.empty:
        return {"n": 0, "nav": 1.0}
    cal_dts = sub_b["trade_date"].tolist()
    T = len(cal_dts)
    csi_r = sub_b["csi300_daily_ret"].to_numpy(float)
    ew_r = sub_b["alla_ew_daily_ret"].to_numpy(float)
    csi_pct = (float(np.prod(1.0 + csi_r)) - 1.0) * 100.0
    ew_pct = (float(np.prod(1.0 + ew_r)) - 1.0) * 100.0

    sub = slot_df[slot_df["buy_date"].between(sdt, edt)].copy().reset_index(drop=True) if not slot_df.empty else pd.DataFrame()
    if pass_df is not None and not pass_df.empty:
        psub = pass_df[pass_df["buy_date"].between(sdt, edt)]
        raw_n = int(len(psub))
        eq_d = psub.groupby("buy_date")["net_ret"].mean().to_numpy(float) if not psub.empty else np.array([])
        eq_nav = float(np.prod(1.0 + eq_d)) if len(eq_d) else 1.0
    else:
        raw_n = int(len(sub))
        eq_nav = 1.0

    # Restrict MTM calendar to window (also drop trades exiting outside window if any? No, buy_date in window; expand cal_end to max exit)
    max_ex = str(sub["exit_date"].max()) if (not sub.empty) else edt
    cal_ext_b = bench_df[bench_df["trade_date"].between(sdt, max(edt, max_ex))].sort_values("trade_date").reset_index(drop=True)
    cal_ext_dts = cal_ext_b["trade_date"].tolist()
    dr_full, mtm_diff = daily_mtm_series(sub, cal_ext_dts, ret_col="net_ret")
    dr = dr_full[:T] if len(dr_full) >= T else dr_full

    mtm_nav = float(np.prod(1.0 + dr_full))
    curve = np.concatenate([[1.0], np.cumprod(1.0 + dr_full)])
    pk = np.maximum.accumulate(curve)
    daily_mdd = float(np.max((pk - curve) / pk) * 100.0)
    sd = float(np.std(dr, ddof=1)) if len(dr) > 1 else 0.0
    sharpe = float(np.mean(dr) / sd * math.sqrt(TRD_DAYS_YEAR)) if sd > 1e-12 else 0.0
    cagr = (mtm_nav ** (TRD_DAYS_YEAR / max(1, len(dr_full))) - 1.0) * 100.0 if mtm_nav > 0 else -100.0
    calmar = (cagr / daily_mdd) if daily_mdd > 1e-6 else 0.0

    if sub.empty:
        return {
            "raw_n": raw_n, "ss_n": 0, "wr_pct": 0.0, "plr": 0.0, "mean_pct": 0.0,
            "nav": 1.0, "mtm_nav": 1.0, "eq_nav": round(eq_nav, 4),
            "ex3_nav": 1.0, "ex5_nav": 1.0, "daily_mdd_pct": 0.0, "trade_mdd_pct": 0.0,
            "daily_sharpe": 0.0, "daily_calmar": 0.0, "mtm_diff": 0.0,
            "csi300_pct": round(csi_pct, 2), "excess_csi300_pp": round(-csi_pct, 2),
            "alla_ew_pct": round(ew_pct, 2), "excess_alla_ew_pp": round(-ew_pct, 2),
            "nav_50bps": 1.0, "nav_80bps": 1.0, "mean_50bps_pct": 0.0, "mean_80bps_pct": 0.0,
        }

    rets = sub["net_ret"].to_numpy(float)
    w, l = rets[rets > 0], rets[rets <= 0]
    wr = float((rets > 0).mean() * 100.0)
    plr = float(w.mean() / abs(l.mean())) if (len(w) and len(l) and l.mean() < 0) else (99.0 if len(w) else 0.0)
    tr_nav = float(np.prod(1.0 + rets))
    sr = np.sort(rets)
    ex3 = float(np.prod(1.0 + sr[:-3])) if len(rets) > 3 else 1.0
    ex5 = float(np.prod(1.0 + sr[:-5])) if len(rets) > 5 else 1.0
    tc = np.concatenate([[1.0], np.cumprod(1.0 + rets)])
    tp = np.maximum.accumulate(tc)
    tr_mdd = float(np.max((tp - tc) / tp) * 100.0)

    r50 = (1.0 + rets) / (1.0 - base_fee) * (1.0 - 0.0050) - 1.0
    r80 = (1.0 + rets) / (1.0 - base_fee) * (1.0 - 0.0080) - 1.0
    dr50, _ = daily_mtm_series(sub, cal_ext_dts, ret_col="net_ret", fee_adjust_from=base_fee, fee_adjust_to=0.0050)
    dr80, _ = daily_mtm_series(sub, cal_ext_dts, ret_col="net_ret", fee_adjust_from=base_fee, fee_adjust_to=0.0080)
    sh50 = float(np.mean(dr50[:T]) / np.std(dr50[:T], ddof=1) * math.sqrt(TRD_DAYS_YEAR)) if np.std(dr50[:T], ddof=1) > 1e-12 else 0.0
    sh80 = float(np.mean(dr80[:T]) / np.std(dr80[:T], ddof=1) * math.sqrt(TRD_DAYS_YEAR)) if np.std(dr80[:T], ddof=1) > 1e-12 else 0.0

    return {
        "raw_n": raw_n,
        "ss_n": int(len(rets)),
        "wr_pct": round(wr, 2),
        "plr": round(plr, 2),
        "mean_pct": round(float(rets.mean() * 100.0), 2),
        "nav": round(tr_nav, 4),
        "mtm_nav": round(mtm_nav, 4),
        "eq_nav": round(eq_nav, 4),
        "ex3_nav": round(ex3, 4),
        "ex5_nav": round(ex5, 4),
        "daily_mdd_pct": round(daily_mdd, 2),
        "trade_mdd_pct": round(tr_mdd, 2),
        "daily_sharpe": round(sharpe, 3),
        "daily_calmar": round(calmar, 2),
        "mtm_diff": round(float(mtm_diff), 10),
        "csi300_pct": round(csi_pct, 2),
        "excess_csi300_pp": round((tr_nav - 1.0) * 100.0 - csi_pct, 2),
        "alla_ew_pct": round(ew_pct, 2),
        "excess_alla_ew_pp": round((tr_nav - 1.0) * 100.0 - ew_pct, 2),
        "nav_50bps": round(float(np.prod(1.0 + r50)), 4),
        "nav_80bps": round(float(np.prod(1.0 + r80)), 4),
        "mean_50bps_pct": round(float(r50.mean() * 100.0), 2),
        "mean_80bps_pct": round(float(r80.mean() * 100.0), 2),
        "sharpe_50bps": round(sh50, 3),
        "sharpe_80bps": round(sh80, 3),
    }


def evaluate_d15_windows(
    slot_df: pd.DataFrame,
    pass_df: Optional[pd.DataFrame],
    bench_df: pd.DataFrame,
    windows: list[tuple[str, str, str]],
    base_fee: float = 0.0030,
) -> dict:
    return {wn: compute_d15_window(slot_df, pass_df, bench_df, s, e, base_fee=base_fee) for wn, s, e in windows}


def tool1_bootstrap(rets: np.ndarray, n_boot: int = 10000, seed: int = 42) -> dict:
    """10,000x nonparametric bootstrap (seed=42) on single-slot trade returns."""
    n = len(rets)
    if n < 2:
        return {"n": int(n), "mean_p05_pct": 0.0, "nav_p05": 1.0, "prob_mean_gt_0": 0.0, "prob_nav_gt_1": 0.0}
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_boot, n))
    mat = rets[idx]
    means = mat.mean(axis=1)
    navs = np.prod(1.0 + mat, axis=1)
    return {
        "n": int(n),
        "n_boot": int(n_boot),
        "seed": int(seed),
        "mean_p05_pct": round(float(np.percentile(means, 5) * 100.0), 2),
        "mean_p50_pct": round(float(np.percentile(means, 50) * 100.0), 2),
        "mean_p95_pct": round(float(np.percentile(means, 95) * 100.0), 2),
        "nav_p05": round(float(np.percentile(navs, 5)), 4),
        "nav_p50": round(float(np.percentile(navs, 50)), 4),
        "nav_p95": round(float(np.percentile(navs, 95)), 4),
        "prob_mean_gt_0": round(float(np.mean(means > 0.0)), 4),
        "prob_nav_gt_1": round(float(np.mean(navs > 1.0)), 4),
    }


def tool2_bayesian_posterior(rets: np.ndarray) -> dict:
    """
    Sequential Beta-Binomial posterior update under Beta(2,2) neutral prior
    and Beta(1.5, 2.5) conservative negative-skewed prior, plus k-consecutive-loss stop red line.
    """
    n = len(rets)
    w = int((rets > 0).sum())
    l_cnt = n - w
    wins = rets[rets > 0]
    losses = rets[rets <= 0]
    avg_w = float(wins.mean()) if len(wins) else 0.05
    avg_l = abs(float(losses.mean())) if (len(losses) and losses.mean() < 0) else 0.05
    plr = avg_w / max(1e-6, avg_l)
    wr_breakeven = 1.0 / (1.0 + plr)
    # Conservative capped PLR (max 2.5) for break-even check against outlier inflation
    plr_cons = min(plr, 2.5)
    wr_be_cons = 1.0 / (1.0 + plr_cons)

    out = {
        "n": int(n),
        "wins": int(w),
        "losses": int(l_cnt),
        "observed_wr_pct": round(w / max(1, n) * 100.0, 2),
        "observed_plr": round(plr, 3),
        "breakeven_wr_pct": round(wr_breakeven * 100.0, 2),
        "breakeven_wr_capped25_pct": round(wr_be_cons * 100.0, 2),
        "priors": {},
    }
    for pname, (a0, b0) in [("Beta(2,2)_neutral", (2.0, 2.0)), ("Beta(1.5,2.5)_neg_skew", (1.5, 2.5))]:
        ap = a0 + w
        bp = b0 + l_cnt
        post_mean = ap / (ap + bp)
        ci05, ci95 = float(stats.beta.ppf(0.05, ap, bp)), float(stats.beta.ppf(0.95, ap, bp))
        prob_ev_pos = float(1.0 - stats.beta.cdf(wr_breakeven, ap, bp))
        prob_ev_pos_cons = float(1.0 - stats.beta.cdf(wr_be_cons, ap, bp))

        # Sequential consecutive losses k starting from current posterior (ap, bp):
        k_stop_mean_be = None
        k_stop_p50_cons = None
        k_stop_p30_cons = None
        for k in range(1, 31):
            p_k = ap / (ap + bp + k)
            prob_k_cons = float(1.0 - stats.beta.cdf(wr_be_cons, ap, bp + k))
            if k_stop_mean_be is None and p_k <= wr_breakeven:
                k_stop_mean_be = k
            if k_stop_p50_cons is None and prob_k_cons < 0.50:
                k_stop_p50_cons = k
            if k_stop_p30_cons is None and prob_k_cons < 0.30:
                k_stop_p30_cons = k

        out["priors"][pname] = {
            "alpha_post": round(ap, 2),
            "beta_post": round(bp, 2),
            "post_wr_mean_pct": round(post_mean * 100.0, 2),
            "post_wr_ci90_pct": [round(ci05 * 100.0, 2), round(ci95 * 100.0, 2)],
            "prob_ev_pos": round(prob_ev_pos, 4),
            "prob_ev_pos_capped25": round(prob_ev_pos_cons, 4),
            "k_consec_loss_mean_below_be": k_stop_mean_be if k_stop_mean_be is not None else ">30",
            "k_consec_loss_prob50_capped25": k_stop_p50_cons if k_stop_p50_cons is not None else ">30",
            "k_consec_loss_prob30_capped25": k_stop_p30_cons if k_stop_p30_cons is not None else ">30",
        }
    return out


def tool3_reverse_control_perm(
    kept_rets: np.ndarray,
    rev_df: pd.DataFrame,
    n_perm: int = 10000,
    seed: int = 42,
    rev_label: str = "reverse_control",
) -> dict:
    """Contemporaneous reverse control metrics + 10,000x two-sample permutation test (seed=42)."""
    if rev_df.empty or len(kept_rets) == 0:
        return {"label": rev_label, "rev_ss_n": 0, "p_mean_one_sided": 1.0, "p_mean_two_sided": 1.0, "p_wr_one_sided": 1.0}
    _, rev_slot = select_single_slot(rev_df, score_col="score" if "score" in rev_df.columns else "open_pct")
    rev_rets = rev_slot["net_ret"].to_numpy(float)
    rev_raw_rets = rev_df["net_ret"].to_numpy(float)

    def _stats_arr(arr):
        if len(arr) == 0:
            return {"n": 0, "wr_pct": 0.0, "mean_pct": 0.0, "nav": 1.0}
        return {
            "n": int(len(arr)),
            "wr_pct": round(float((arr > 0).mean() * 100.0), 2),
            "mean_pct": round(float(arr.mean() * 100.0), 2),
            "nav": round(float(np.prod(1.0 + arr)), 4),
        }

    # Two-sample permutation test comparing kept_rets vs rev_rets (single-slot) and vs rev_raw_rets
    def _perm_2sample(a: np.ndarray, b: np.ndarray) -> dict:
        na, nb = len(a), len(b)
        if na < 2 or nb < 2:
            return {"p_mean_1s": 1.0, "p_mean_2s": 1.0, "p_wr_1s": 1.0}
        obs_diff_m = float(a.mean() - b.mean())
        obs_diff_w = float((a > 0).mean() - (b > 0).mean())
        pool_m = np.concatenate([a, b])
        pool_w = (pool_m > 0).astype(float)
        tot_m = float(pool_m.sum())
        tot_w = float(pool_w.sum())
        rng = np.random.default_rng(seed)
        cnt_m1, cnt_m2, cnt_w1 = 0, 0, 0
        # Vectorized chunked permutation
        n_tot = na + nb
        for s in range(0, n_perm, 500):
            bs = min(500, n_perm - s)
            # Random keys -> argpartition first na elements
            keys = rng.random((bs, n_tot))
            idx_a = np.argpartition(keys, na, axis=1)[:, :na]
            sum_am = pool_m[idx_a].sum(axis=1)
            diff_m = sum_am / na - (tot_m - sum_am) / nb
            sum_aw = pool_w[idx_a].sum(axis=1)
            diff_w = sum_aw / na - (tot_w - sum_aw) / nb
            cnt_m1 += int(np.sum(diff_m >= obs_diff_m - 1e-12))
            cnt_m2 += int(np.sum(np.abs(diff_m) >= abs(obs_diff_m) - 1e-12))
            cnt_w1 += int(np.sum(diff_w >= obs_diff_w - 1e-12))
        return {
            "obs_diff_mean_pp": round(obs_diff_m * 100.0, 2),
            "obs_diff_wr_pp": round(obs_diff_w * 100.0, 2),
            "p_mean_1s": round((cnt_m1 + 1) / (n_perm + 1), 4),
            "p_mean_2s": round((cnt_m2 + 1) / (n_perm + 1), 4),
            "p_wr_1s": round((cnt_w1 + 1) / (n_perm + 1), 4),
        }

    return {
        "label": rev_label,
        "rev_slot": _stats_arr(rev_rets),
        "rev_raw": _stats_arr(rev_raw_rets),
        "perm_vs_rev_slot": _perm_2sample(kept_rets, rev_rets),
        "perm_vs_rev_raw": _perm_2sample(kept_rets, rev_raw_rets),
    }


def tool4_regime_changepoint_and_dd(slot_df: pd.DataFrame, n_perm: int = 2000, seed: int = 42) -> dict:
    """Yearly/semi-annual breakdown, CUSUM & Pettitt changepoint detection, rolling window, and current peak DD."""
    if slot_df.empty:
        return {"yearly": {}, "half_yearly": {}, "current_dd_pct": 0.0}
    df = slot_df.sort_values("buy_date").reset_index(drop=True)
    df["yr"] = df["buy_date"].str[:4]
    df["hy"] = df["buy_date"].apply(lambda d: f"{d[:4]}H1" if int(d[5:7]) <= 6 else f"{d[:4]}H2")

    def _agg(sub):
        r = sub["net_ret"].to_numpy(float)
        if len(r) == 0:
            return {"n": 0, "wr_pct": 0.0, "mean_pct": 0.0, "nav": 1.0}
        w, l = r[r > 0], r[r <= 0]
        po = float(w.mean() / abs(l.mean())) if (len(w) and len(l) and l.mean() < 0) else (99.0 if len(w) else 0.0)
        return {
            "n": int(len(r)),
            "wr_pct": round(float((r > 0).mean() * 100.0), 2),
            "plr": round(po, 2),
            "mean_pct": round(float(r.mean() * 100.0), 2),
            "nav": round(float(np.prod(1.0 + r)), 4),
        }

    yearly = {yr: _agg(g) for yr, g in df.groupby("yr", sort=True)}
    half_yearly = {hy: _agg(g) for hy, g in df.groupby("hy", sort=True)}
    slump_23_25 = _agg(df[df["buy_date"].between("2023-01-01", "2025-12-31")])

    rets = df["net_ret"].to_numpy(float)
    n = len(rets)
    curve = np.cumprod(1.0 + rets)
    pk_arr = np.maximum.accumulate(np.concatenate([[1.0], curve]))[1:]
    pk_idx = int(np.argmax(curve))
    curr_dd = float((pk_arr[-1] - curve[-1]) / pk_arr[-1] * 100.0) if n > 0 else 0.0

    # CUSUM & Pettitt changepoint test
    cp_info = {"n": int(n), "cusum_p": 1.0, "pettitt_p": 1.0, "changepoint_date": None}
    if n >= 8:
        centered = rets - rets.mean()
        cusum = np.cumsum(centered)
        obs_cusum = float(np.max(np.abs(cusum)))
        cp_pos = int(np.argmax(np.abs(cusum)))

        # Pettitt rank-based U_t
        ranks = stats.rankdata(rets)
        t_arr = np.arange(1, n + 1, dtype=float)
        U_t = 2.0 * np.cumsum(ranks) - t_arr * (n + 1.0)
        obs_pet = float(np.max(np.abs(U_t[:-1])))
        pet_pos = int(np.argmax(np.abs(U_t[:-1])))
        pet_p_approx = float(min(1.0, 2.0 * math.exp(-6.0 * (obs_pet ** 2) / (n ** 3 + n ** 2))))

        rng = np.random.default_rng(seed)
        cnt_cu = 0
        for _ in range(n_perm):
            perm_r = rng.permutation(centered)
            if float(np.max(np.abs(np.cumsum(perm_r)))) >= obs_cusum - 1e-12:
                cnt_cu += 1

        b_cut = max(1, cp_pos + 1)
        cp_info = {
            "n": int(n),
            "cusum_cp_idx": int(cp_pos),
            "changepoint_date": str(df["buy_date"].iloc[cp_pos]),
            "cusum_max_abs": round(obs_cusum, 4),
            "cusum_p_perm": round((cnt_cu + 1) / (n_perm + 1), 4),
            "before_cp_n": int(b_cut),
            "before_cp_mean_pct": round(float(rets[:b_cut].mean() * 100.0), 2),
            "before_cp_wr_pct": round(float((rets[:b_cut] > 0).mean() * 100.0), 2),
            "after_cp_n": int(n - b_cut),
            "after_cp_mean_pct": round(float(rets[b_cut:].mean() * 100.0), 2) if n > b_cut else None,
            "after_cp_wr_pct": round(float((rets[b_cut:] > 0).mean() * 100.0), 2) if n > b_cut else None,
            "pettitt_cp_date": str(df["buy_date"].iloc[pet_pos]),
            "pettitt_p_approx": round(pet_p_approx, 4),
        }

    # Rolling 10-trade window stats
    roll10 = {}
    if n >= 10:
        r10_means = [float(rets[i - 10:i].mean() * 100.0) for i in range(10, n + 1)]
        r10_wrs = [float((rets[i - 10:i] > 0).mean() * 100.0) for i in range(10, n + 1)]
        roll10 = {
            "min_mean_pct": round(min(r10_means), 2),
            "max_mean_pct": round(max(r10_means), 2),
            "latest_mean_pct": round(r10_means[-1], 2),
            "min_wr_pct": round(min(r10_wrs), 1),
            "max_wr_pct": round(max(r10_wrs), 1),
            "latest_wr_pct": round(r10_wrs[-1], 1),
        }

    return {
        "yearly": yearly,
        "half_yearly": half_yearly,
        "period_2023_2025": slump_23_25,
        "changepoint": cp_info,
        "rolling_10_trades": roll10,
        "terminal_nav": round(float(curve[-1]), 4),
        "peak_nav": round(float(pk_arr[-1]), 4),
        "peak_date": str(df["buy_date"].iloc[pk_idx]),
        "current_dd_from_peak_pct": round(curr_dd, 2),
    }


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
    if isinstance(obj, np.ndarray):
        return sanitize_json(obj.tolist())
    return obj

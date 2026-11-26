#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Single-Slot Simulator, Exact Daily MTM Builder & Mandatory Anti-Overfit Evaluator.
Zero yfinance (D12).
"""
import math
from typing import Optional

import numpy as np
import pandas as pd

TRD_DAYS_YEAR = 242.0


def prepare_hygiene_and_net_ret(
    df: pd.DataFrame,
    fee_rt: float = 0.0030,
    gross_ret_col: Optional[str] = None,
) -> pd.DataFrame:
    """Enforce一字不可买 exclusion and 0.30% round-trip friction when gross returns are passed."""
    out = df.copy()
    out["buy_date"] = out["buy_date"].astype(str).str[:10]
    out["exit_date"] = out["exit_date"].astype(str).str[:10]
    out["code"] = out["code"].astype(str).str.zfill(6)
    if "buy_hhmm" not in out.columns:
        out["buy_hhmm"] = 925
    if "exit_hhmm" not in out.columns:
        out["exit_hhmm"] = 1500
    out["buy_hhmm"] = pd.to_numeric(out["buy_hhmm"], errors="coerce").fillna(925).astype(int)
    out["exit_hhmm"] = pd.to_numeric(out["exit_hhmm"], errors="coerce").fillna(1500).astype(int)

    if gross_ret_col is not None and gross_ret_col in out.columns:
        gr = pd.to_numeric(out[gross_ret_col], errors="coerce").astype(float)
        out["net_ret"] = (1.0 + gr) * (1.0 - float(fee_rt)) - 1.0
    elif "net_ret" not in out.columns and "gross_ret" in out.columns:
        gr = pd.to_numeric(out["gross_ret"], errors="coerce").astype(float)
        out["net_ret"] = (1.0 + gr) * (1.0 - float(fee_rt)) - 1.0
    else:
        out["net_ret"] = pd.to_numeric(out["net_ret"], errors="coerce").astype(float)

    can_buy = np.ones(len(out), dtype=bool)
    if "is_yizi" in out.columns:
        can_buy &= (~out["is_yizi"].fillna(False).to_numpy(bool))
    if "can_buy" in out.columns:
        can_buy &= out["can_buy"].fillna(True).to_numpy(bool)
    if "sim_ok" in out.columns:
        can_buy &= out["sim_ok"].fillna(True).to_numpy(bool)
    out["can_buy_hygiene"] = can_buy & out["net_ret"].notna()
    return out


def select_single_slot_trades(
    scored_df: pd.DataFrame,
    score_col: str = "wf_score",
    threshold: float | str | None = None,
    tie_col: Optional[str] = None,
    wf_only: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Pick highest-scoring buyable candidate per day >= threshold under strict single-slot non-overlap.
    `threshold` may be None (all buyable), float (e.g. 75.0), or column name (e.g. 'wf_thr_top10').
    Returns (passing_candidates_df, single_slot_trades_df).
    """
    m = scored_df["can_buy_hygiene"].fillna(True).to_numpy(bool)
    if wf_only and "wf_in_window" in scored_df.columns:
        m &= scored_df["wf_in_window"].fillna(False).to_numpy(bool)
    m &= scored_df[score_col].notna().to_numpy(bool)

    if threshold is not None:
        if isinstance(threshold, str):
            thr_vals = pd.to_numeric(scored_df[threshold], errors="coerce").to_numpy(float)
            m &= np.isfinite(thr_vals) & (scored_df[score_col].to_numpy(float) >= thr_vals)
        else:
            m &= scored_df[score_col].to_numpy(float) >= float(threshold)

    passing = scored_df[m].copy()
    if passing.empty:
        return passing, passing

    sort_cols = ["buy_date", score_col]
    asc = [True, False]
    if tie_col and tie_col in passing.columns:
        sort_cols.append(tie_col)
        asc.append(False)
    sort_cols.append("code")
    asc.append(True)
    srt = passing.sort_values(sort_cols, ascending=asc, kind="mergesort")

    taken_idx = []
    cur_ed, cur_eh = "", 0
    for r in srt.itertuples():
        bd = str(r.buy_date)
        ed = str(r.exit_date)
        bh = int(getattr(r, "buy_hhmm", 925))
        eh = int(getattr(r, "exit_hhmm", 1500))
        if ed <= bd:
            continue
        if (not cur_ed) or (bd > cur_ed) or (bd == cur_ed and bh > cur_eh):
            taken_idx.append(r.Index)
            cur_ed, cur_eh = ed, eh

    slot_df = srt.loc[taken_idx].copy().reset_index(drop=True)
    return passing.reset_index(drop=True), slot_df


def build_daily_mtm_returns(
    trades_df: pd.DataFrame,
    cal_dts: list[str],
    mtm_col: Optional[str] = None,
) -> tuple[np.ndarray, float]:
    """
    Compute exact daily MTM returns over `cal_dts`.
    Uses precomputed segment multipliers `mtm_col` if present; otherwise allocates trade
    return uniformly (geometric daily root) across [buy_date, exit_date] holding window
    when intraday bar lookup isn't supplied.
    """
    T = len(cal_dts)
    if trades_df.empty:
        return np.zeros(T, dtype=float), 0.0
    dt_idx = {d: i for i, d in enumerate(cal_dts)}
    day_mult = np.ones(T, dtype=float)

    if mtm_col and mtm_col in trades_df.columns:
        for segs in trades_df[mtm_col]:
            for t_i, mult in segs:
                if 0 <= t_i < T:
                    day_mult[t_i] *= float(mult)
    else:
        for r in trades_df.itertuples(index=False):
            bi = dt_idx.get(str(r.buy_date))
            ei = dt_idx.get(str(r.exit_date))
            if bi is None:
                continue
            if ei is None or ei <= bi:
                day_mult[bi] *= (1.0 + float(r.net_ret))
            else:
                span = ei - bi + 1
                g = (1.0 + float(r.net_ret)) ** (1.0 / span)
                day_mult[bi:ei + 1] *= g

    dr = day_mult - 1.0
    tr_sub = trades_df[trades_df["buy_date"].isin(dt_idx)]
    tr_nav = float(np.prod(1.0 + tr_sub["net_ret"].to_numpy(float))) if not tr_sub.empty else 1.0
    return dr, abs(float(np.prod(day_mult)) - tr_nav)


def _calc_one_window(
    slot_df: pd.DataFrame,
    pass_df: Optional[pd.DataFrame],
    dr_full: np.ndarray,
    cal_dts: list[str],
    dt_idx: dict[str, int],
    csi_arr: np.ndarray,
    ew_arr: np.ndarray,
    sdt: str,
    edt: str,
) -> dict:
    win_pos = [dt_idx[d] for d in cal_dts if sdt <= d <= edt]
    T = len(win_pos)
    if T == 0:
        return {"n": 0, "nav": 1.0}

    dr = dr_full[win_pos]
    csi_r = csi_arr[win_pos]
    ew_r = ew_arr[win_pos]
    csi_pct = (float(np.prod(1.0 + csi_r)) - 1.0) * 100.0
    alla_pct = (float(np.prod(1.0 + ew_r)) - 1.0) * 100.0

    mtm_nav = float(np.prod(1.0 + dr))
    curve = np.concatenate([[1.0], np.cumprod(1.0 + dr)])
    pk = np.maximum.accumulate(curve)
    daily_mdd = float(np.max((pk - curve) / pk) * 100.0)
    sd = float(np.std(dr, ddof=1)) if T > 1 else 0.0
    sharpe = float(np.mean(dr) / sd * math.sqrt(TRD_DAYS_YEAR)) if sd > 1e-12 else 0.0
    cagr = (mtm_nav ** (TRD_DAYS_YEAR / T) - 1.0) * 100.0 if mtm_nav > 0 else -100.0
    calmar = (cagr / daily_mdd) if daily_mdd > 1e-6 else 0.0

    sub = slot_df[slot_df["buy_date"].between(sdt, edt)] if not slot_df.empty else pd.DataFrame()
    if pass_df is not None and not pass_df.empty:
        psub = pass_df[pass_df["buy_date"].between(sdt, edt)]
        eq_d = psub.groupby("buy_date")["net_ret"].mean().to_numpy(float) if not psub.empty else np.array([])
        eq_nav = float(np.prod(1.0 + eq_d)) if len(eq_d) else 1.0
    else:
        eq_nav = 1.0

    act_days = 0
    for r in sub.itertuples(index=False):
        bi, ei = dt_idx.get(str(r.buy_date)), dt_idx.get(str(r.exit_date))
        if bi is not None and ei is not None:
            act_days += max(0, min(ei, win_pos[-1]) - max(bi, win_pos[0]) + 1)
    act_days = min(act_days, T)
    exp_pct = act_days / T * 100.0
    tpy = len(sub) / (T / TRD_DAYS_YEAR)

    if sub.empty:
        return {
            "n": 0, "wr_pct": 0.0, "plr": 0.0, "mean_pct": 0.0,
            "nav": 1.0, "mtm_nav": round(mtm_nav, 4), "eq_nav": round(eq_nav, 4),
            "ex_top3_nav": 1.0, "ex_top5_nav": 1.0,
            "daily_mdd_pct": round(daily_mdd, 2), "trade_mdd_pct": 0.0,
            "daily_sharpe": round(sharpe, 3), "daily_calmar": round(calmar, 2),
            "cagr_pct": round(cagr, 2),
            "csi300_pct": round(csi_pct, 2), "excess_csi300_pp": round(-csi_pct, 2),
            "alla_ew_pct": round(alla_pct, 2), "excess_alla_ew_pp": round(-alla_pct, 2),
            "active_days": int(act_days), "exposure_pct": round(exp_pct, 2),
            "trades_per_year": 0.0,
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

    return {
        "n": int(len(rets)), "wr_pct": round(wr, 2), "plr": round(plr, 2),
        "mean_pct": round(float(rets.mean() * 100.0), 2),
        "nav": round(tr_nav, 4), "mtm_nav": round(mtm_nav, 4), "eq_nav": round(eq_nav, 4),
        "ex_top3_nav": round(ex3, 4), "ex_top5_nav": round(ex5, 4),
        "daily_mdd_pct": round(daily_mdd, 2), "trade_mdd_pct": round(tr_mdd, 2),
        "daily_sharpe": round(sharpe, 3), "daily_calmar": round(calmar, 2),
        "cagr_pct": round(cagr, 2),
        "csi300_pct": round(csi_pct, 2), "excess_csi300_pp": round((tr_nav - 1.0) * 100.0 - csi_pct, 2),
        "alla_ew_pct": round(alla_pct, 2), "excess_alla_ew_pp": round((tr_nav - 1.0) * 100.0 - alla_pct, 2),
        "active_days": int(act_days), "exposure_pct": round(exp_pct, 2),
        "trades_per_year": round(tpy, 1),
    }


def perm_test_trading_days(
    slot_df: pd.DataFrame,
    cand_pool_df: pd.DataFrame,
    start_dt: str,
    end_dt: str,
    n_perm: int = 1000,
    seed: int = 20261125,
) -> dict:
    """1,000x trading-day permutation test (both same-day stock-pick & any-cand-day timing+pick)."""
    sub_s = slot_df[slot_df["buy_date"].between(start_dt, end_dt)] if not slot_df.empty else pd.DataFrame()
    sub_p = cand_pool_df[cand_pool_df["buy_date"].between(start_dt, end_dt) & cand_pool_df["can_buy_hygiene"]]
    n_tr = len(sub_s)
    if n_tr < 3 or sub_p.empty:
        return {"n_perm": n_perm, "same_day_p_mean": 1.0, "same_day_p_nav": 1.0, "any_cand_day_p_mean": 1.0, "any_cand_day_p_nav": 1.0}

    rng = np.random.default_rng(seed)
    obs_rets = sub_s["net_ret"].to_numpy(float)
    obs_mean = float(obs_rets.mean())
    obs_nav = float(np.prod(1.0 + obs_rets))

    by_dt = {d: g["net_ret"].to_numpy(float) for d, g in sub_p.groupby("buy_date")}
    all_day_keys = list(by_dt.keys())
    day_arrs = [by_dt[d] for d in all_day_keys]

    # 1. Same-day random draw conditional on active trade dates
    same_cols = []
    for d in sub_s["buy_date"]:
        arr = by_dt.get(d, obs_rets)
        same_cols.append(arr[rng.integers(0, len(arr), size=n_perm)])
    sd_mat = np.column_stack(same_cols)
    p_sd_mean = float((np.sum(sd_mat.mean(axis=1) >= obs_mean - 1e-12) + 1) / (n_perm + 1))
    p_sd_nav = float((np.sum(np.prod(1.0 + sd_mat, axis=1) >= obs_nav - 1e-12) + 1) / (n_perm + 1))

    # 2. Random candidate-day sampling (draws n_tr days with replacement across all candidate days, 1 stock/day)
    n_days = len(day_arrs)
    pick_d = rng.integers(0, n_days, size=(n_perm, n_tr))
    any_mat = np.empty((n_perm, n_tr), dtype=float)
    for j in range(n_tr):
        d_idx_col = pick_d[:, j]
        for k_p in range(n_perm):
            arr = day_arrs[d_idx_col[k_p]]
            any_mat[k_p, j] = arr[rng.integers(0, len(arr))]
    p_any_mean = float((np.sum(any_mat.mean(axis=1) >= obs_mean - 1e-12) + 1) / (n_perm + 1))
    p_any_nav = float((np.sum(np.prod(1.0 + any_mat, axis=1) >= obs_nav - 1e-12) + 1) / (n_perm + 1))

    return {
        "n_perm": int(n_perm),
        "n_trades": int(n_tr),
        "n_cand_days": int(n_days),
        "same_day_p_mean": round(p_sd_mean, 4),
        "same_day_p_nav": round(p_sd_nav, 4),
        "any_cand_day_p_mean": round(p_any_mean, 4),
        "any_cand_day_p_nav": round(p_any_nav, 4),
    }


def evaluate_wf_ledger(
    slot_df: pd.DataFrame,
    pass_df: Optional[pd.DataFrame],
    cand_pool_df: pd.DataFrame,
    bench_df: pd.DataFrame,
    wf_start_dt: str = "2023-01-03",
    end_dt: str = "2026-11-25",
    mtm_col: Optional[str] = None,
    perm_n: int = 1000,
    seed: int = 20261125,
) -> dict:
    """Compute mandatory metrics across FULL_WF, Y2023, Y2024, Y2025, Y2026, Y2025_2026 + 1000x perm."""
    b = bench_df[bench_df["trade_date"].between(wf_start_dt, end_dt)].sort_values("trade_date").reset_index(drop=True)
    cal_dts = b["trade_date"].tolist()
    dt_idx = {d: i for i, d in enumerate(cal_dts)}
    csi_arr = b["csi300_daily_ret"].to_numpy(float)
    ew_arr = b["alla_ew_daily_ret"].to_numpy(float)

    dr_full, mtm_diff = build_daily_mtm_returns(slot_df, cal_dts, mtm_col=mtm_col)
    windows = [
        ("FULL_WF", wf_start_dt, end_dt),
        ("Y2023", max(wf_start_dt, "2023-01-01"), "2023-12-31"),
        ("Y2024", "2024-01-01", "2024-12-31"),
        ("Y2025", "2025-01-01", "2025-12-31"),
        ("Y2026", "2026-01-01", end_dt),
        ("Y2025_2026", "2025-01-01", end_dt),
    ]
    win_res = {
        wn: _calc_one_window(slot_df, pass_df, dr_full, cal_dts, dt_idx, csi_arr, ew_arr, s, e)
        for wn, s, e in windows if s <= e
    }
    perm = perm_test_trading_days(slot_df, cand_pool_df, wf_start_dt, end_dt, n_perm=perm_n, seed=seed)
    return {
        "wf_window": f"{wf_start_dt} ~ {end_dt}",
        "mtm_reconciliation_diff": round(float(mtm_diff), 8),
        "windows": win_res,
        "permutation_1000": perm,
    }

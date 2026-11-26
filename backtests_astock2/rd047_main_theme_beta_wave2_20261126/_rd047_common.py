#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD047 Shared Evaluation, Exact MTM Accounting, Benchmark & V20 Correlation / Dual-Ledger Utilities.
Zero yfinance (D12). Peak RAM guard.
"""
import json
import math
import os
import resource
import sys
from typing import Optional

import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation!"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
BASE_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
DATA_DIR = f"{ROOT}/sim-portfolio/data"
RD044_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd044_quant_4families_review_20261126"
RD047_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd047_main_theme_beta_wave2_20261126"
CACHE_DIR = f"{RD047_DIR}/_cache"

TRD_DAYS_YEAR = 242.0
FULL_START = "2021-01-04"
WF_START = "2023-01-03"
EVAL_END = "2026-11-24"

WINDOWS_ALL = [
    ("FULL_5Y", FULL_START, EVAL_END),
    ("WF_OOS", WF_START, EVAL_END),
    ("Y2021", "2021-01-04", "2021-12-31"),
    ("Y2022", "2022-01-01", "2022-12-31"),
    ("Y2023", "2023-01-03", "2023-12-31"),
    ("Y2024", "2024-01-01", "2024-12-31"),
    ("Y2025", "2025-01-01", "2025-12-31"),
    ("Y2026", "2026-01-01", EVAL_END),
    ("Y26H2", "2026-07-01", EVAL_END),
]


def rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 1)


def load_stock_names() -> dict[str, str]:
    names: dict[str, str] = {}
    for p in (f"{DATA_DIR}/csrc_industry_l2.csv", f"{DATA_DIR}/csrc_industry_pit_clean.csv"):
        if not os.path.exists(p):
            continue
        df = pd.read_csv(p)
        col_c = "sec_code" if "sec_code" in df.columns else "code"
        for r in df.itertuples(index=False):
            c6 = str(getattr(r, col_c)).split(".")[-1].zfill(6)
            nm = str(r.code_name).strip() if pd.notna(r.code_name) else ""
            if nm and nm != "nan":
                names[c6] = nm
    kpl_p = f"{DATA_DIR}/kpl_plates_2018_2026_merged.jsonl"
    if os.path.exists(kpl_p):
        with open(kpl_p, encoding="utf-8") as f:
            for ln in f:
                if not ln.strip():
                    continue
                o = json.loads(ln)
                for pl in o.get("plates", []):
                    for st in pl.get("stocks", []):
                        if isinstance(st, list) and len(st) >= 2:
                            c6 = str(st[0]).zfill(6)
                            nm = str(st[1]).strip()
                            if nm and c6 not in names:
                                names[c6] = nm
    return names


def load_bench_and_v20(end_dt: str = EVAL_END) -> dict:
    bench = pd.read_parquet(f"{BASE_DIR}/v20_daily_bench_20210104_20261125.parquet")
    bench = bench[bench["trade_date"].between(FULL_START, end_dt)].sort_values("trade_date").reset_index(drop=True)
    cal_ext = pd.read_parquet(f"{BASE_DIR}/v20_daily_slot_calendar_to_20261125.parquet")
    cal_ext = cal_ext[cal_ext["trade_date"].between(FULL_START, end_dt)].sort_values("trade_date").reset_index(drop=True)
    etf_df = pd.read_parquet(f"{RD044_DIR}/etf_daily_qfq_cache.parquet")
    b511 = etf_df[(etf_df["code"] == "511010") & (etf_df["dt"] <= end_dt)].sort_values("dt").copy()
    b511["ret_1d"] = b511["close"].pct_change().fillna(0.0)
    b511_map = dict(zip(b511["dt"].astype(str), b511["ret_1d"].astype(float)))
    cal_dts = bench["trade_date"].tolist()
    bond_dr = np.array([float(b511_map.get(d, 0.0)) for d in cal_dts], dtype=np.float64)
    return {
        "bench": bench,
        "cal_dts": cal_dts,
        "dt_idx": {d: i for i, d in enumerate(cal_dts)},
        "csi300_dr": bench["csi300_daily_ret"].to_numpy(float),
        "alla_ew_dr": bench["alla_ew_daily_ret"].to_numpy(float),
        "v20_cal": cal_ext,
        "bond_511010_dr": bond_dr,
    }


def apply_bond_parking(
    dr: np.ndarray,
    act_mask: np.ndarray,
    bond_dr: np.ndarray,
    etf_fee_rt: float = 0.0005,
    start_idx: int = 0,
) -> np.ndarray:
    """Park flat cash (where ~act_mask) into 511010 Bond ETF with 5bps round-trip switching friction."""
    out = dr.copy()
    flat = (~act_mask).copy()
    if start_idx > 0:
        flat[:start_idx] = False
    prev_flat = np.concatenate(([False], flat[:-1]))
    sw_cost = np.where(flat != prev_flat, etf_fee_rt * 0.5, 0.0)
    out[flat] = bond_dr[flat] - sw_cost[flat]
    out[~flat] = out[~flat] - sw_cost[~flat]
    return out


def calc_window_metrics(
    dr: np.ndarray,
    csi_dr: np.ndarray,
    ew_dr: np.ndarray,
    cal_dts: list[str],
    sdt: str,
    edt: str,
    active_mask: Optional[np.ndarray] = None,
    turnover_daily: Optional[np.ndarray] = None,
) -> dict:
    mask = np.array([sdt <= d <= edt for d in cal_dts], dtype=bool)
    T = int(mask.sum())
    if T == 0:
        return {"T": 0, "nav": 1.0}
    r = dr[mask]
    c = csi_dr[mask]
    e = ew_dr[mask]

    nav = float(np.prod(1.0 + r))
    csi_nav = float(np.prod(1.0 + c))
    ew_nav = float(np.prod(1.0 + e))

    curve = np.concatenate([[1.0], np.cumprod(1.0 + r)])
    pk = np.maximum.accumulate(curve)
    mdd = float(np.max((pk - curve) / pk) * 100.0)
    sd = float(np.std(r, ddof=1)) if T > 1 else 0.0
    sharpe = float(np.mean(r) / sd * math.sqrt(TRD_DAYS_YEAR)) if sd > 1e-12 else 0.0
    cagr = (nav ** (TRD_DAYS_YEAR / T) - 1.0) * 100.0 if nav > 0 else -100.0
    calmar = (cagr / mdd) if mdd > 1e-6 else 0.0

    tot_ret_pct = (nav - 1.0) * 100.0
    csi_pct = (csi_nav - 1.0) * 100.0
    ew_pct = (ew_nav - 1.0) * 100.0
    csi_cagr = (csi_nav ** (TRD_DAYS_YEAR / T) - 1.0) * 100.0 if csi_nav > 0 else -100.0
    ex_d = r - c
    sd_ex = float(np.std(ex_d, ddof=1)) if T > 1 else 0.0
    ir_csi = float(np.mean(ex_d) / sd_ex * math.sqrt(TRD_DAYS_YEAR)) if sd_ex > 1e-12 else 0.0

    sr = np.sort(r)
    nav_ex5d = float(np.prod(1.0 + sr[:-5])) if T > 10 else nav
    exp_pct = float(np.mean(active_mask[mask]) * 100.0) if active_mask is not None else float(np.mean(np.abs(r) > 1e-12) * 100.0)
    ann_to = float(np.mean(turnover_daily[mask]) * TRD_DAYS_YEAR * 100.0) if turnover_daily is not None else 0.0

    return {
        "T": T,
        "nav": round(nav, 4),
        "tot_ret_pct": round(tot_ret_pct, 2),
        "cagr_pct": round(cagr, 2),
        "sharpe": round(sharpe, 3),
        "mdd_pct": round(mdd, 2),
        "calmar": round(calmar, 2),
        "csi300_pct": round(csi_pct, 2),
        "excess_csi300_pp": round(tot_ret_pct - csi_pct, 2),
        "excess_cagr_pp": round(cagr - csi_cagr, 2),
        "ir_csi300": round(ir_csi, 3),
        "alla_ew_pct": round(ew_pct, 2),
        "excess_alla_ew_pp": round(tot_ret_pct - ew_pct, 2),
        "nav_ex_top5d": round(nav_ex5d, 4),
        "exposure_pct": round(exp_pct, 2),
        "ann_turnover_pct": round(ann_to, 1),
    }


def evaluate_daily_series(
    dr: np.ndarray,
    bench_ctx: dict,
    active_mask: Optional[np.ndarray] = None,
    turnover_daily: Optional[np.ndarray] = None,
    windows: list[tuple[str, str, str]] = WINDOWS_ALL,
) -> dict:
    cal_dts = bench_ctx["cal_dts"]
    csi_dr = bench_ctx["csi300_dr"]
    ew_dr = bench_ctx["alla_ew_dr"]
    res = {}
    for wn, s, e in windows:
        if s > cal_dts[-1] or e < cal_dts[0]:
            continue
        res[wn] = calc_window_metrics(dr, csi_dr, ew_dr, cal_dts, s, e, active_mask=active_mask, turnover_daily=turnover_daily)
    return res


def compute_trade_stats(trades_df: pd.DataFrame, sdt: str, edt: str) -> dict:
    if trades_df.empty:
        return {"n": 0, "wr_pct": 0.0, "plr": 0.0, "mean_pct": 0.0, "avg_hold_days": 0.0, "top5_profit_share_pct": 0.0, "ex_top5_trade_nav": 1.0}
    sub = trades_df[trades_df["buy_date"].between(sdt, edt)]
    if sub.empty:
        return {"n": 0, "wr_pct": 0.0, "plr": 0.0, "mean_pct": 0.0, "avg_hold_days": 0.0, "top5_profit_share_pct": 0.0, "ex_top5_trade_nav": 1.0}
    rets = sub["net_ret"].to_numpy(float)
    w, l = rets[rets > 0], rets[rets <= 0]
    wr = float((rets > 0).mean() * 100.0)
    plr = float(w.mean() / abs(l.mean())) if (len(w) and len(l) and l.mean() < 0) else (99.0 if len(w) else 0.0)
    avg_hold = float(sub["hold_days"].mean()) if "hold_days" in sub.columns else 0.0
    tot_pos = float(np.sum(np.maximum(rets, 0.0)))
    top5_sum = float(np.sum(np.sort(np.maximum(rets, 0.0))[-5:]))
    top5_share = (top5_sum / tot_pos * 100.0) if tot_pos > 1e-9 else 0.0
    # Ex-top5 trade compound check (slot-scaled by average concurrent slots if present)
    n_slots = float(sub["slots_cap"].iloc[0]) if "slots_cap" in sub.columns else 1.0
    sr = np.sort(rets)
    ex5_nav = float(np.prod(1.0 + sr[:-5] / max(1.0, n_slots))) if len(rets) > 5 else 1.0
    return {
        "n": int(len(rets)),
        "wr_pct": round(wr, 2),
        "plr": round(plr, 2),
        "mean_pct": round(float(rets.mean() * 100.0), 2),
        "avg_hold_days": round(avg_hold, 1),
        "top5_profit_share_pct": round(top5_share, 1),
        "ex_top5_trade_nav": round(ex5_nav, 4),
    }


def compute_v20_corr_and_blend(
    q_dr: np.ndarray,
    bench_ctx: dict,
    start_dt: str = WF_START,
    end_dt: str = EVAL_END,
) -> dict:
    cal_dts = bench_ctx["cal_dts"]
    v20_cal = bench_ctx["v20_cal"]
    v20_map = dict(zip(v20_cal["trade_date"], v20_cal["v20_daily_ret"].fillna(0.0)))
    idx_win = [i for i, d in enumerate(cal_dts) if start_dt <= d <= end_dt]
    dts_w = [cal_dts[i] for i in idx_win]
    v_dr = np.array([float(v20_map.get(d, 0.0)) for d in dts_w], dtype=float)
    q_w = q_dr[idx_win]
    csi_w = bench_ctx["csi300_dr"][idx_win]

    corr_all = float(np.corrcoef(q_w, v_dr)[0, 1]) if (np.std(q_w) > 1e-12 and np.std(v_dr) > 1e-12) else 0.0
    q_act = np.abs(q_w) > 1e-10
    v_act = np.abs(v_dr) > 1e-10
    corr_q_act = float(np.corrcoef(q_w[q_act], v_dr[q_act])[0, 1]) if (q_act.sum() >= 10 and np.std(q_w[q_act]) > 1e-12 and np.std(v_dr[q_act]) > 1e-12) else None
    corr_v_act = float(np.corrcoef(q_w[v_act], v_dr[v_act])[0, 1]) if (v_act.sum() >= 10 and np.std(q_w[v_act]) > 1e-12) else None
    corr_csi = float(np.corrcoef(q_w, csi_w)[0, 1]) if (np.std(q_w) > 1e-12 and np.std(csi_w) > 1e-12) else 0.0

    def _stats(arr):
        nv = float(np.prod(1.0 + arr))
        cv = np.concatenate([[1.0], np.cumprod(1.0 + arr)])
        pk = np.maximum.accumulate(cv)
        mdd = float(np.max((pk - cv) / pk) * 100.0)
        sd = float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0
        sh = float(np.mean(arr) / sd * math.sqrt(TRD_DAYS_YEAR)) if sd > 1e-12 else 0.0
        cagr = (nv ** (TRD_DAYS_YEAR / len(arr)) - 1.0) * 100.0 if nv > 0 else -100.0
        cal = cagr / mdd if mdd > 1e-6 else 0.0
        return {"nav": round(nv, 2), "cagr_pct": round(cagr, 2), "sharpe": round(sh, 3), "mdd_pct": round(mdd, 2), "calmar": round(cal, 2)}

    return {
        "window": f"{start_dt} ~ {end_dt}",
        "T": len(dts_w),
        "corr_all_days": round(corr_all, 4),
        "corr_strat_active": round(corr_q_act, 4) if corr_q_act is not None else None,
        "corr_v20_active": round(corr_v_act, 4) if corr_v_act is not None else None,
        "corr_csi300": round(corr_csi, 4),
        "blends": {
            "v20_100pct": _stats(v_dr),
            "strat_100pct": _stats(q_w),
            "daily_70v20_30s": _stats(0.70 * v_dr + 0.30 * q_w),
            "daily_50v20_50s": _stats(0.50 * v_dr + 0.50 * q_w),
            "daily_80v20_20s": _stats(0.80 * v_dr + 0.20 * q_w),
        },
    }


def deflated_sharpe_ratio(dr: np.ndarray, n_trials: int, trial_sharpes: Optional[list[float]] = None) -> dict:
    from scipy.stats import norm
    T = len(dr)
    if T < 30 or np.std(dr, ddof=1) <= 1e-12:
        return {"sr_ann": 0.0, "dsr": 0.0, "n_trials": int(n_trials)}
    sr_daily = float(np.mean(dr) / np.std(dr, ddof=1))
    sr_ann = sr_daily * math.sqrt(TRD_DAYS_YEAR)
    z = (dr - np.mean(dr)) / np.std(dr, ddof=1)
    skew = float(np.mean(z ** 3))
    kurt = float(np.mean(z ** 4))
    var_sr_ann = float(np.var(trial_sharpes, ddof=1)) if (trial_sharpes is not None and len(trial_sharpes) > 1) else 0.25
    var_sr_daily = var_sr_ann / TRD_DAYS_YEAR
    n_eff = max(2, int(n_trials))
    gamma = 0.5772156649
    sr0_daily = math.sqrt(max(var_sr_daily, 1e-9)) * (
        (1.0 - gamma) * norm.ppf(1.0 - 1.0 / n_eff) + gamma * norm.ppf(1.0 - 1.0 / (n_eff * math.e))
    )
    denom_sq = max(1e-9, 1.0 - skew * sr_daily + ((kurt - 1.0) / 4.0) * (sr_daily ** 2))
    z_stat = (sr_daily - sr0_daily) * math.sqrt(T - 1) / math.sqrt(denom_sq)
    return {
        "T": T,
        "n_trials": int(n_trials),
        "sr_ann": round(sr_ann, 3),
        "sr0_ann_hurdle": round(sr0_daily * math.sqrt(TRD_DAYS_YEAR), 3),
        "dsr": round(float(norm.cdf(z_stat)), 4),
    }

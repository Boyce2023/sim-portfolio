#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
V22.0 Pillar 1B Shared Strict-PIT Evaluator, Data Loaders & Statistical Audit Engine (`_p1b_common.py`).
Supports:
  - D15 metrics across IS(2021-2023), OOS(2024-2026), 2025-2026, 2026, 2026H2, FULL_5Y
    (both canonical V20/V21 `..2026-11-16` and RD048 extended `..2026-11-24` windows)
  - 30bps primary + 50bps stress + 20bps parity reference
  - Exact close-to-close daily MTM series (`mtm_diff == 0.0`), daily equal-weight NAV (`eq_nav`),
    ex_top2 / ex_top3 / ex_top5 NAV, CSI 300 net excess return
  - 10,000x bootstrap (mean_p05, nav_p05, P(mean>0)), Bayesian posterior, paired daily t-test, reverse perm test
  - Strictly causal PIT regulatory / notice maps truncated at `max_dt`
Zero yfinance (D12). SQLite always opened `?mode=ro`.
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import bisect
import glob
import json
import math
import pickle
import re
import resource
import sqlite3
import sys
import warnings
from collections import defaultdict
from typing import Optional

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
from scipy import stats

pa.set_cpu_count(1)
pa.set_io_thread_count(1)
warnings.filterwarnings("ignore")
assert "yfinance" not in sys.modules, "D12 VIOLATION: yfinance forbidden"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
OUT_DIR = f"{SIM}/backtests_astock/v22_grand_convergence_20261126/p1b_high_4to5_mutual"
WAVE1_BASE = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
RD038_DIR = f"{SIM}/backtests_astock2/rd038_grand_bundle_assembly_20261126"
RD048_DIR = f"{SIM}/backtests_astock2/rd048_4small_gems_polish_integration_20261126"
RD048_W1A = f"{RD048_DIR}/wave1a_gem1_gem3"
RD039_F23 = f"{SIM}/backtests_astock2/rd039_single_strat_sharpe_lift_20261126/front2_3_3to4_high_pry"
HIGH_SBX = f"{SIM}/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113"
PARTC_V191 = f"{SIM}/backtests_astock/redteam_full_audit_20261123/partC_clean_ledgers_v191"
F1_3TO4 = f"{SIM}/backtests_astock/exit_factors_v2_20261118/f1_3to4"
P3_DEEP = f"{SIM}/backtests_astock2/p3_deep_100"

TRD_DAYS_YEAR = 242.0

WINDOWS_1116 = [
    ("FULL_5Y", "2021-11-16", "2026-11-16"),
    ("IS_2123", "2021-11-16", "2023-12-31"),
    ("OOS_2426", "2024-01-01", "2026-11-16"),
    ("WF_2326", "2023-01-03", "2026-11-16"),
    ("Y2025_2026", "2025-01-01", "2026-11-16"),
    ("Y2026", "2026-01-01", "2026-11-16"),
    ("Y2026_H2", "2026-07-01", "2026-11-16"),
]

WINDOWS_1124 = [
    ("FULL_5Y_EXT", "2021-11-16", "2026-11-24"),
    ("IS_2123", "2021-11-16", "2023-12-31"),
    ("OOS_2426_EXT", "2024-01-01", "2026-11-24"),
    ("Y2025_2026_EXT", "2025-01-01", "2026-11-24"),
    ("Y2026_EXT", "2026-01-01", "2026-11-24"),
    ("Y2026_H2_EXT", "2026-07-01", "2026-11-24"),
]

TOX_NARROW_RE = re.compile(r"(?:减持计划|股东减持|立案调查|收到立案|退市风险)")
TOX_BROAD_RE = re.compile(r"(?:减持计划|股东减持|立案调查|收到立案|退市风险|违法违规)")
TOX_STRICT_RE = re.compile(r"(?:减持.*(?:计划|预披露|公告)|(?:计划|预披露).*减持|立案调查|收到立案|退市风险|违法违规|股票交易风险提示)")
JIANCHI_ONLY_RE = re.compile(r"(?:减持.*(?:计划|预披露|公告)|(?:计划|预披露).*减持|立案调查|收到立案|退市风险|违法违规)")

REG_INC_WORDS = ("监管工作函", "监管函", "关注函", "重点监控", "停牌核查")
REG_EXC_WORDS = ("ST", "回复", "回函", "延期", "核查意见", "复牌", "募集资金", "监事", "独立董事", "保荐")
REG_EXC_LITE = ("回复", "取消", "撤销", "解除", "不予")

DAY_SURF_RE = re.compile(r"(?:拉萨|东方财富证券|华宝证券.*(?:上海|东大名路)|华泰证券.*总部|中国银河.*北京中关村)")
INST_RE = re.compile(r"机构专用")
QUANT_RE = re.compile(r"(?:量化|华鑫|中金上海|瑞银|高盛|摩根|招商上海|华泰总部|量化基金|中国国际金融上海)")


def rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 1)


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


def convert_fee(ret_arr, from_fee: float, to_fee: float):
    return (1.0 + ret_arr) / (1.0 - float(from_fee)) * (1.0 - float(to_fee)) - 1.0


def load_bench_and_index(max_dt: Optional[str] = None) -> tuple[pd.DataFrame, dict, dict, dict, list[str]]:
    bench = pd.read_parquet(f"{WAVE1_BASE}/v20_daily_bench_20210104_20261125.parquet")
    bench["trade_date"] = bench["trade_date"].astype(str).str[:10]
    if max_dt:
        bench = bench[bench["trade_date"] <= max_dt].copy()
    bench = bench.sort_values("trade_date").reset_index(drop=True)

    with open(f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json", encoding="utf-8") as f:
        raw = json.load(f)
    sh2 = {str(k)[:10]: float(v["close"] if isinstance(v, dict) else v) for k, v in raw["sh000002"].items() if str(k)[:10] >= "2020-09-02" and (not max_dt or str(k)[:10] <= max_dt)}
    sz2 = {str(k)[:10]: float(v["close"] if isinstance(v, dict) else v) for k, v in raw["sz399107"].items() if str(k)[:10] >= "2020-09-02" and (not max_dt or str(k)[:10] <= max_dt)}
    csi = {str(k)[:10]: float(v["close"] if isinstance(v, dict) else v) for k, v in raw["sh000300"].items() if str(k)[:10] >= "2020-09-02" and (not max_dt or str(k)[:10] <= max_dt)}
    all_dts = sorted(sh2.keys())
    return bench, dict(sorted(sh2.items())), dict(sorted(sz2.items())), dict(sorted(csi.items())), all_dts


def load_bar_lookup(codes: set[str], max_dt: str = "2026-11-25") -> dict[tuple[str, str], tuple[float, float, float]]:
    """Load exact (open, close, adjf) for needed codes from a_daily + a_delisted_daily."""
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
        scanner = ds.dataset(pq_path, format="parquet").scanner(columns=cols, filter=flt, batch_size=65536, use_threads=False)
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
    pa.default_memory_pool().release_unused()
    return lu


def build_mtm_pairs_for_trades(
    trades_df: pd.DataFrame,
    cal_dts: list[str],
    bar_lu: dict,
    ret_col: str = "net_ret",
    px_col: str = "buy_price_val",
) -> list[str]:
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


def daily_mtm_series(
    slot_df: pd.DataFrame,
    cal_dts: list[str],
    mtm_col: str = "mtm_pairs_json",
    ret_col: str = "net_ret",
    fee_adjust_from: Optional[float] = None,
    fee_adjust_to: Optional[float] = None,
) -> tuple[np.ndarray, float]:
    T = len(cal_dts)
    if slot_df is None or slot_df.empty:
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
                day_mult[bi : ei + 1] *= g

    dr = day_mult - 1.0
    in_df = slot_df[slot_df["buy_date"].isin(dt_idx) & slot_df["exit_date"].isin(dt_idx)]
    rets_in = in_df[ret_col].to_numpy(float) if not in_df.empty else np.array([], dtype=float)
    if fee_adjust_from is not None and fee_adjust_to is not None and len(rets_in):
        rets_in = convert_fee(rets_in, fee_adjust_from, fee_adjust_to)
    tr_nav = float(np.prod(1.0 + rets_in)) if len(rets_in) else 1.0
    return dr, abs(float(np.prod(day_mult)) - tr_nav)


def compute_d15_window(
    slot_df: pd.DataFrame,
    pass_df: Optional[pd.DataFrame],
    bench_df: pd.DataFrame,
    sdt: str,
    edt: str,
    base_fee: float = 0.0030,
    ret_col: str = "net_ret",
) -> dict:
    sub_b = bench_df[bench_df["trade_date"].between(sdt, edt)].sort_values("trade_date").reset_index(drop=True)
    if sub_b.empty:
        return {"raw_n": 0, "ss_n": 0, "nav": 1.0}
    cal_dts = sub_b["trade_date"].tolist()
    T = len(cal_dts)
    csi_r = sub_b["csi300_daily_ret"].to_numpy(float)
    ew_r = sub_b["alla_ew_daily_ret"].to_numpy(float)
    csi_pct = (float(np.prod(1.0 + csi_r)) - 1.0) * 100.0
    ew_pct = (float(np.prod(1.0 + ew_r)) - 1.0) * 100.0

    sub = slot_df[slot_df["buy_date"].between(sdt, edt)].copy().reset_index(drop=True) if (slot_df is not None and not slot_df.empty) else pd.DataFrame()
    if pass_df is not None and not pass_df.empty:
        psub = pass_df[pass_df["buy_date"].between(sdt, edt)]
        raw_n = int(len(psub))
        eq_d = psub.groupby("buy_date")[ret_col].mean().to_numpy(float) if not psub.empty else np.array([])
        eq_nav = float(np.prod(1.0 + eq_d)) if len(eq_d) else 1.0
        eq_d_50 = convert_fee(eq_d, base_fee, 0.0050) if len(eq_d) else np.array([])
        eq_nav_50 = float(np.prod(1.0 + eq_d_50)) if len(eq_d_50) else 1.0
    else:
        raw_n = int(len(sub))
        eq_nav = 1.0
        eq_nav_50 = 1.0

    max_ex = str(sub["exit_date"].max()) if (not sub.empty) else edt
    cal_ext_b = bench_df[bench_df["trade_date"].between(sdt, max(edt, max_ex))].sort_values("trade_date").reset_index(drop=True)
    cal_ext_dts = cal_ext_b["trade_date"].tolist()
    dr_full, mtm_diff = daily_mtm_series(sub, cal_ext_dts, ret_col=ret_col)
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
            "ex2_nav": 1.0, "ex3_nav": 1.0, "ex5_nav": 1.0,
            "daily_mdd_pct": 0.0, "trade_mdd_pct": 0.0, "daily_sharpe": 0.0, "daily_calmar": 0.0,
            "mtm_diff": 0.0, "csi300_pct": round(csi_pct, 2), "excess_csi300_pp": round(-csi_pct, 2),
            "alla_ew_pct": round(ew_pct, 2), "excess_alla_ew_pp": round(-ew_pct, 2),
            "nav_50bps": 1.0, "eq_nav_50bps": round(eq_nav_50, 4), "ex2_50bps_nav": 1.0,
            "mean_50bps_pct": 0.0, "sharpe_50bps": 0.0, "daily_mdd_50bps_pct": 0.0,
        }

    rets = sub[ret_col].to_numpy(float)
    w, l = rets[rets > 0], rets[rets <= 0]
    wr = float((rets > 0).mean() * 100.0)
    plr = float(w.mean() / abs(l.mean())) if (len(w) and len(l) and l.mean() < 0) else (99.0 if len(w) else 0.0)
    tr_nav = float(np.prod(1.0 + rets))
    sr = np.sort(rets)
    ex2 = float(np.prod(1.0 + sr[:-2])) if len(rets) > 2 else 1.0
    ex3 = float(np.prod(1.0 + sr[:-3])) if len(rets) > 3 else 1.0
    ex5 = float(np.prod(1.0 + sr[:-5])) if len(rets) > 5 else 1.0
    tc = np.concatenate([[1.0], np.cumprod(1.0 + rets)])
    tp = np.maximum.accumulate(tc)
    tr_mdd = float(np.max((tp - tc) / tp) * 100.0)

    r50 = convert_fee(rets, base_fee, 0.0050)
    sr50 = np.sort(r50)
    ex2_50 = float(np.prod(1.0 + sr50[:-2])) if len(r50) > 2 else 1.0
    dr50, _ = daily_mtm_series(sub, cal_ext_dts, ret_col=ret_col, fee_adjust_from=base_fee, fee_adjust_to=0.0050)
    sd50 = float(np.std(dr50[:T], ddof=1)) if len(dr50[:T]) > 1 else 0.0
    sh50 = float(np.mean(dr50[:T]) / sd50 * math.sqrt(TRD_DAYS_YEAR)) if sd50 > 1e-12 else 0.0
    c50 = np.concatenate([[1.0], np.cumprod(1.0 + dr50)])
    pk50 = np.maximum.accumulate(c50)
    mdd50 = float(np.max((pk50 - c50) / pk50) * 100.0)

    return {
        "raw_n": raw_n,
        "ss_n": int(len(rets)),
        "wr_pct": round(wr, 2),
        "plr": round(plr, 2),
        "mean_pct": round(float(rets.mean() * 100.0), 2),
        "nav": round(tr_nav, 4),
        "mtm_nav": round(mtm_nav, 4),
        "eq_nav": round(eq_nav, 4),
        "ex2_nav": round(ex2, 4),
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
        "eq_nav_50bps": round(eq_nav_50, 4),
        "ex2_50bps_nav": round(ex2_50, 4),
        "mean_50bps_pct": round(float(r50.mean() * 100.0), 2),
        "sharpe_50bps": round(sh50, 3),
        "daily_mdd_50bps_pct": round(mdd50, 2),
    }


def evaluate_d15_windows(
    slot_df: pd.DataFrame,
    pass_df: Optional[pd.DataFrame],
    bench_df: pd.DataFrame,
    windows: list[tuple[str, str, str]],
    base_fee: float = 0.0030,
    ret_col: str = "net_ret",
) -> dict:
    return {wn: compute_d15_window(slot_df, pass_df, bench_df, s, e, base_fee=base_fee, ret_col=ret_col) for wn, s, e in windows}


def bootstrap_10k(rets: np.ndarray, n_boot: int = 10000, seed: int = 42) -> dict:
    n = len(rets)
    if n < 2:
        return {"n": int(n), "mean_p05_pct": 0.0, "mean_p50_pct": 0.0, "nav_p05": 1.0, "nav_p50": 1.0, "prob_mean_gt_0": 0.0, "prob_nav_gt_1": 0.0}
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


def perm_test_two_sample(rets_keep: np.ndarray, rets_drop: np.ndarray, n_perm: int = 10000, seed: int = 42) -> dict:
    n_k, n_d = len(rets_keep), len(rets_drop)
    if n_k < 2 or n_d < 1:
        return {"n_keep": int(n_k), "n_drop": int(n_d), "obs_diff_pp": 0.0, "p_mean_1s": 1.0}
    obs = float(rets_keep.mean() - rets_drop.mean())
    pooled = np.concatenate([rets_keep, rets_drop])
    rng = np.random.default_rng(seed)
    ge = 0
    for _ in range(n_perm):
        perm = rng.permutation(pooled)
        if perm[:n_k].mean() - perm[n_k:].mean() >= obs - 1e-12:
            ge += 1
    return {
        "n_keep": int(n_k),
        "n_drop": int(n_d),
        "keep_mean_pct": round(float(rets_keep.mean() * 100.0), 2),
        "drop_mean_pct": round(float(rets_drop.mean() * 100.0), 2),
        "obs_diff_pp": round(obs * 100.0, 2),
        "p_mean_1s": round(float((ge + 1) / (n_perm + 1)), 4),
    }


def paired_daily_ttest(dr_cand: np.ndarray, dr_base: np.ndarray) -> dict:
    if len(dr_cand) != len(dr_base) or len(dr_cand) < 10:
        return {"t_stat": 0.0, "p_2sided": 1.0}
    diff = dr_cand - dr_base
    if np.all(np.abs(diff) < 1e-14):
        return {"t_stat": 0.0, "p_2sided": 1.0}
    t_val, p_val = stats.ttest_1samp(diff, 0.0)
    return {"t_stat": round(float(t_val), 3), "p_2sided": round(float(p_val), 4)}


def load_pit_notice_maps(max_dt: str = "2026-11-25") -> dict:
    """
    Load strictly PIT regulatory / toxic notice events truncated at `max_dt`:
      - `pit_reg_tox_notices_5y_complete.parquet`
      - `cninfo_notices_5y_pit.db` (read-only)
      - `kpl/zdjk/*.json`
      - `part1_cache.pkl` native stock_reg & ex_reg (benchmark parity reference)
    """
    max_ts = f"{max_dt} 23:59:59"
    df_tox = pd.read_parquet(f"{SIM}/data/pit_reg_tox_notices_5y_complete.parquet")
    df_tox["c6"] = df_tox["sec_code"].astype(str).str[:6].str.zfill(6)
    df_tox["pdt"] = df_tox["pub_datetime_cst"].astype(str).str[:19]
    df_tox["dt"] = df_tox["pdt"].str[:10]
    df_tox = df_tox[df_tox["dt"] <= max_dt].copy()

    tox_strict_pq = defaultdict(list)
    tox_jianchi_pq = defaultdict(list)
    tox_broad_pq = defaultdict(list)
    reg_pq = defaultdict(list)
    ex_events_pq = {"SH": [], "SZ": []}

    for r in df_tox.itertuples(index=False):
        ti = str(r.title or "")
        c6 = r.c6
        pdt = r.pdt
        dt = r.dt
        if TOX_BROAD_RE.search(ti):
            tox_broad_pq[c6].append((pdt, ti))
        if TOX_STRICT_RE.search(ti):
            tox_strict_pq[c6].append((pdt, ti))
        if JIANCHI_ONLY_RE.search(ti):
            tox_jianchi_pq[c6].append((pdt, ti))
        if any(w in ti for w in REG_INC_WORDS) and not any(w in ti for w in REG_EXC_WORDS):
            reg_pq[c6].append((pdt, ti))
            if c6.startswith(("00", "60")):
                ex = "SH" if c6.startswith("60") else "SZ"
                ex_events_pq[ex].append((dt, c6, pdt))

    # Also read cninfo_notices_5y_pit.db (covers full notices including some missing from pq)
    tox_strict_cn = defaultdict(list)
    tox_jianchi_cn = defaultdict(list)
    reg_cn = defaultdict(list)
    ex_events_cn = {"SH": [], "SZ": []}

    con_cn = sqlite3.connect(f"file:{SIM}/data/cninfo_notices_5y_pit.db?mode=ro", uri=True)
    q = """SELECT sec_code, pub_datetime_cst, title FROM notices
           WHERE pub_datetime_cst <= ?
             AND (title LIKE '%监管%' OR title LIKE '%关注%' OR title LIKE '%监控%'
                  OR title LIKE '%核查%' OR title LIKE '%风险提示%' OR title LIKE '%减持%'
                  OR title LIKE '%立案%' OR title LIKE '%退市%' OR title LIKE '%违法%')"""
    for sc, pdt, ti in con_cn.execute(q, (max_ts,)):
        c6 = str(sc).zfill(6)
        pdt_s = str(pdt)[:19]
        dt = pdt_s[:10]
        if dt > max_dt:
            continue
        ti_s = str(ti or "")
        if TOX_STRICT_RE.search(ti_s):
            tox_strict_cn[c6].append((pdt_s, ti_s))
        if JIANCHI_ONLY_RE.search(ti_s):
            tox_jianchi_cn[c6].append((pdt_s, ti_s))
        if any(w in ti_s for w in REG_INC_WORDS) and not any(w in ti_s for w in REG_EXC_WORDS):
            reg_cn[c6].append((pdt_s, ti_s))
            if c6.startswith(("00", "60")):
                ex = "SH" if c6.startswith("60") else "SZ"
                ex_events_cn[ex].append((dt, c6, pdt_s))
    con_cn.close()

    zdjk_map = defaultdict(list)
    ex_events_zd = {"SH": [], "SZ": []}
    for zf in glob.glob(f"{SIM}/data/kpl/zdjk/*.json"):
        zd = json.load(open(zf, encoding="utf-8"))
        for it in zd.get("List", []):
            c6 = str(it[0]).zfill(6)
            dt = str(it[2])[:10]
            if dt <= max_dt:
                zdjk_map[c6].append((dt + " 08:00:00", "KPL_ZDJK:" + str(it[1])))
                if c6.startswith(("00", "60")):
                    ex = "SH" if c6.startswith("60") else "SZ"
                    ex_events_zd[ex].append((dt, c6, dt + " 08:00:00"))

    with open(f"{HIGH_SBX}/part1_cache.pkl", "rb") as f:
        p1 = pickle.load(f)
    p1_sreg_raw, p1_ereg_raw, p1_tox_raw = p1[10], p1[11], p1[12]
    p1_sreg = {str(k).zfill(6): sorted([str(d)[:10] for d in v if str(d)[:10] <= max_dt]) for k, v in p1_sreg_raw.items()}
    p1_ereg = {ex: sorted([str(d)[:10] for d in v if str(d)[:10] <= max_dt]) for ex, v in p1_ereg_raw.items()}
    del p1

    # Deduplicate full exchange events within 7 calendar days per stock (matching build_pit_cache / fast_high_dragon_today.py)
    ex_full_dedup = {}
    for ex in ("SH", "SZ"):
        raw_ev = sorted(set((dt, c6) for dt, c6, _ in (ex_events_pq[ex] + ex_events_cn[ex] + ex_events_zd[ex])))
        ded, seen = [], {}
        for dt, c6 in raw_ev:
            ts = pd.Timestamp(dt)
            if c6 not in seen or (ts - seen[c6]).days > 7:
                seen[c6] = ts
                ded.append((dt, c6))
        ex_full_dedup[ex] = ded

    # Unified union maps per stock
    tox_strict_union = defaultdict(list)
    tox_jianchi_union = defaultdict(list)
    sreg_union = defaultdict(list)
    for src in (tox_strict_pq, tox_strict_cn):
        for c6, lst in src.items():
            tox_strict_union[c6].extend(lst)
    for src in (tox_jianchi_pq, tox_jianchi_cn):
        for c6, lst in src.items():
            tox_jianchi_union[c6].extend(lst)
    for src in (reg_pq, reg_cn, zdjk_map):
        for c6, lst in src.items():
            sreg_union[c6].extend(lst)

    return {
        "tox_strict_pq": dict(tox_strict_pq),
        "tox_jianchi_pq": dict(tox_jianchi_pq),
        "tox_broad_pq": dict(tox_broad_pq),
        "tox_strict_union": dict(tox_strict_union),
        "tox_jianchi_union": dict(tox_jianchi_union),
        "sreg_union": dict(sreg_union),
        "zdjk_map": dict(zdjk_map),
        "p1_sreg": p1_sreg,
        "p1_ereg": p1_ereg,
        "ex_full_dedup": ex_full_dedup,
    }


def query_notice_flags(c6: str, bd: str, cal_dts: list[str], cal_idx: dict[str, int], nmap: dict) -> dict:
    """Strictly causal (< bd 09:25:00) notice / regulatory flags for stock `c6` on `bd`."""
    cut = f"{bd} 09:25:00"
    d90 = (pd.Timestamp(bd) - pd.Timedelta(days=90)).strftime("%Y-%m-%d 00:00:00")
    d10 = (pd.Timestamp(bd) - pd.Timedelta(days=10)).strftime("%Y-%m-%d 00:00:00")

    def _hits(m: dict, lo: str, hi: str) -> list[str]:
        return [ti for pdt, ti in m.get(c6, []) if lo <= pdt < hi]

    h_tox_pq = _hits(nmap["tox_strict_pq"], d90, cut)
    h_tox_un = _hits(nmap["tox_strict_union"], d90, cut)
    h_jc_pq = _hits(nmap["tox_jianchi_pq"], d90, cut)
    h_jc_un = _hits(nmap["tox_jianchi_union"], d90, cut)
    h_sreg_un = _hits(nmap["sreg_union"], d10, cut)
    h_zdjk = _hits(nmap["zdjk_map"], d10, cut)

    p1_sr = any(d10[:10] <= d < bd for d in nmap["p1_sreg"].get(c6, []))

    ex = "SH" if c6.startswith("60") else "SZ"
    bi = cal_idx.get(bd)
    if bi is None:
        bi = bisect.bisect_left(cal_dts, bd)
    w5 = cal_dts[max(0, bi - 5)] if bi > 0 else bd
    p1_ex_cnt5 = sum(1 for d in nmap["p1_ereg"].get(ex, []) if w5 <= d < bd)
    full_ex_cnt5 = len({sc for d, sc in nmap["ex_full_dedup"].get(ex, []) if w5 <= d < bd})

    return {
        "tox_strict_pq": len(h_tox_pq) > 0,
        "tox_strict_union": len(h_tox_un) > 0,
        "jianchi_only_pq": len(h_jc_pq) > 0,
        "jianchi_only_union": len(h_jc_un) > 0,
        "sreg_10d_union": len(h_sreg_un) > 0,
        "zdjk_10d": len(h_zdjk) > 0,
        "p1_sreg_10d": bool(p1_sr),
        "p1_ex_reg5": int(p1_ex_cnt5),
        "full_ex_reg5": int(full_ex_cnt5),
        "tox_titles": h_tox_un[:2],
        "sreg_titles": h_sreg_un[:2],
    }

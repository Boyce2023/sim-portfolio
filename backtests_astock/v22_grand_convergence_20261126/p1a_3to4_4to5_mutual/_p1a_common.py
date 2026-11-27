#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
_p1a_common.py — V22.0 Pillar 1A 共享底座（零 yfinance / SQLite 只读 / 精确 MTM 与 D15 五窗口审计）。
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import json
import math
import pickle
import sys
from typing import Optional

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds

pa.set_cpu_count(1)
pa.set_io_thread_count(1)
sys.dont_write_bytecode = True
assert "yfinance" not in sys.modules, "D12 VIOLATION: yfinance forbidden"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
OUT_DIR = f"{SIM}/backtests_astock/v22_grand_convergence_20261126/p1a_3to4_4to5_mutual"
os.makedirs(OUT_DIR, exist_ok=True)

A_DAILY_PQ = f"{SIM}/data/cn_hk_price_db/a_daily.parquet"
A_DELIST_PQ = f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet"
BENCH_PQ = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base/v20_daily_bench_20210104_20261125.parquet"
IDX_JSON = f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json"

TRD_DAYS_YEAR = 242.0
FEE_MAIN = 0.0030
FEE_STRESS = 0.0050

WINDOWS_5 = [
    ("IS_21_23", "2021-11-15", "2023-12-31"),
    ("OOS_24_26", "2024-01-01", "2026-11-16"),
    ("Y2025_2026", "2025-01-01", "2026-11-16"),
    ("Y2026", "2026-01-01", "2026-11-16"),
    ("Y2026_H2", "2026-07-01", "2026-11-16"),
    ("FULL_5Y", "2021-11-15", "2026-11-16"),
]


def convert_fee(arr: np.ndarray | float, from_fee: float, to_fee: float):
    """Convert net return from `from_fee` round-trip friction to `to_fee`."""
    return (1.0 + arr) / (1.0 - from_fee) * (1.0 - to_fee) - 1.0


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


def load_bench_and_indices(max_dt: str = "2026-11-16") -> tuple[pd.DataFrame, dict, dict, dict, list[str]]:
    """Load canonical daily benchmark and sh000002/sz399107/sh000300 strictly truncated <= max_dt."""
    bench = pd.read_parquet(BENCH_PQ)
    bench["trade_date"] = bench["trade_date"].astype(str).str[:10]
    bench = bench[bench["trade_date"] <= max_dt].sort_values("trade_date").reset_index(drop=True)

    with open(IDX_JSON, encoding="utf-8") as f:
        raw = json.load(f)
    sh2 = {str(k)[:10]: float(v["close"] if isinstance(v, dict) else v) for k, v in raw["sh000002"].items() if "2020-09-02" <= str(k)[:10] <= max_dt}
    sz2 = {str(k)[:10]: float(v["close"] if isinstance(v, dict) else v) for k, v in raw["sz399107"].items() if "2020-09-02" <= str(k)[:10] <= max_dt}
    csi = {str(k)[:10]: float(v["close"] if isinstance(v, dict) else v) for k, v in raw["sh000300"].items() if "2020-09-02" <= str(k)[:10] <= max_dt}
    all_dts = sorted(sh2.keys())
    return bench, dict(sorted(sh2.items())), dict(sorted(sz2.items())), dict(sorted(csi.items())), all_dts


def load_bar_lookup(codes: set[str], max_dt: str = "2026-11-16") -> dict[tuple[str, str], tuple[float, float, float]]:
    """Load exact (open, close, adjf) from active + delisted A-share parquet strictly <= max_dt."""
    if not codes:
        return {}
    tks = sorted({f"{c}.SH" for c in codes} | {f"{c}.SZ" for c in codes})
    cols = ["date", "ticker", "open", "close", "adj_close"]
    flt = (ds.field("date") >= pd.Timestamp("2020-12-01")) & (ds.field("date") <= pd.Timestamp(max_dt)) & ds.field("ticker").isin(tks)
    lu = {}
    for pq_path, dl_flag in [(A_DAILY_PQ, 0), (A_DELIST_PQ, 1)]:
        sc = ds.dataset(pq_path, format="parquet").scanner(columns=cols, filter=flt, batch_size=65536, use_threads=False)
        for batch in sc.to_batches():
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


def load_merged_5m_bars(codes: set[str], max_dt: str = "2026-11-16") -> dict[tuple[str, str], np.ndarray]:
    """Load merged local 5m bars for `codes` strictly filtered date <= max_dt."""
    b5m = {}
    tks_list = sorted(codes)
    pq_sources = [
        f"{SIM}/backtests_astock2/_archive/20261116/old_phase1_phase2_supersede/p2_4to5/cand_4to5_5m_bars.parquet",
        f"{SIM}/backtests_astock2/data_5y/cand_3to4_5m_bars.parquet",
        f"{SIM}/data/cand_5m_bars_v15_complete.parquet",
        f"{SIM}/data/all_strategies_5m_complete_pit.parquet",
        f"{SIM}/output/slippage_velocity_audit_20261125/part2_trigger_price_opt/_patch_5m_bars.parquet",
    ]
    for pq in pq_sources:
        if not os.path.exists(pq):
            continue
        sc = ds.dataset(pq, format="parquet").scanner(
            columns=["c6", "date", "hhmm_int", "open", "high", "low", "close", "volume", "amount"],
            filter=(ds.field("date") <= max_dt),
            batch_size=65536,
            use_threads=False,
        )
        parts = []
        for batch in sc.to_batches():
            d = batch.to_pandas()
            if d.empty:
                continue
            d["c6"] = d["c6"].astype(str).str[:6].str.zfill(6)
            d = d[d["c6"].isin(codes)]
            if not d.empty:
                parts.append(d)
        if not parts:
            continue
        df_s = pd.concat(parts, ignore_index=True).sort_values(["c6", "date", "hhmm_int"])
        for (c6, dt), grp in df_s.groupby(["c6", "date"], sort=False):
            k = (c6, str(dt)[:10])
            if k not in b5m:
                b5m[k] = grp[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float)

    sub2_p = f"{SIM}/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113/sub2_5m_bars_cache.pkl"
    if os.path.exists(sub2_p):
        with open(sub2_p, "rb") as f:
            pk = pickle.load(f)
        for k_raw, df_k in pk.items():
            c6 = str(k_raw[0]).zfill(6)
            if c6 in codes and isinstance(df_k, pd.DataFrame) and "date" in df_k.columns and not df_k.empty:
                for dt, grp in df_k.groupby("date", sort=False):
                    dt_s = str(dt)[:10]
                    if dt_s <= max_dt and (c6, dt_s) not in b5m:
                        h_arr = (
                            grp["hhmm_int"].to_numpy(dtype=float).reshape(-1, 1)
                            if "hhmm_int" in grp.columns
                            else grp["hhmm"].astype(str).str.replace(":", "").astype(float).to_numpy().reshape(-1, 1)
                        )
                        b5m[(c6, dt_s)] = np.hstack([h_arr, grp[["open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float)])
    pa.default_memory_pool().release_unused()
    return b5m


def build_mtm_pairs(
    trades_df: pd.DataFrame,
    cal_dts: list[str],
    bar_lu: dict,
    ret_col: str = "net_ret",
    px_col: str = "buy_price",
) -> list[str]:
    """Build exact daily close-to-close MTM multiplier JSON pairs where prod(mult) == 1 + net_ret."""
    dt_idx = {d: i for i, d in enumerate(cal_dts)}
    T = len(cal_dts)
    out = []
    for r in trades_df.itertuples(index=False):
        nr = float(getattr(r, ret_col))
        bd = str(r.buy_date)[:10]
        ed = str(r.exit_date)[:10]
        bi, ei = dt_idx.get(bd), dt_idx.get(ed)
        if bi is None or ei is None or ei <= bi or not np.isfinite(nr):
            out.append("[]")
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
        out.append(json.dumps(pairs))
    return out


def daily_mtm_series(
    slot_df: pd.DataFrame,
    cal_dts: list[str],
    mtm_col: str = "mtm_pairs_json",
    ret_col: str = "net_ret",
    fee_from: Optional[float] = None,
    fee_to: Optional[float] = None,
) -> tuple[np.ndarray, float]:
    """Reconstruct exact daily MTM return series and verify reconciliation error."""
    T = len(cal_dts)
    if slot_df.empty:
        return np.zeros(T, dtype=float), 0.0
    dt_idx = {d: i for i, d in enumerate(cal_dts)}
    day_mult = np.ones(T, dtype=float)
    scale = (1.0 - float(fee_to)) / (1.0 - float(fee_from)) if (fee_from is not None and fee_to is not None) else 1.0

    for r in slot_df.itertuples(index=False):
        segs = json.loads(getattr(r, mtm_col)) if (hasattr(r, mtm_col) and getattr(r, mtm_col)) else []
        if segs:
            for k, (d_s, m_v) in enumerate(segs):
                ti = dt_idx.get(d_s)
                if ti is not None:
                    day_mult[ti] *= float(m_v) * (scale if k == len(segs) - 1 else 1.0)
        else:
            bi, ei = dt_idx.get(str(r.buy_date)[:10]), dt_idx.get(str(r.exit_date)[:10])
            rt = float(getattr(r, ret_col))
            if fee_from is not None and fee_to is not None:
                rt = convert_fee(rt, fee_from, fee_to)
            if bi is not None and ei is not None and ei > bi:
                day_mult[bi : ei + 1] *= (1.0 + rt) ** (1.0 / (ei - bi + 1))

    dr = day_mult - 1.0
    in_df = slot_df[slot_df["buy_date"].isin(dt_idx) & slot_df["exit_date"].isin(dt_idx)]
    rets_in = in_df[ret_col].to_numpy(float) if not in_df.empty else np.array([], dtype=float)
    if fee_from is not None and fee_to is not None and len(rets_in):
        rets_in = convert_fee(rets_in, fee_from, fee_to)
    tr_nav = float(np.prod(1.0 + rets_in)) if len(rets_in) else 1.0
    return dr, abs(float(np.prod(day_mult)) - tr_nav)


def compute_window_metrics(
    slot_df: pd.DataFrame,
    raw_df: Optional[pd.DataFrame],
    bench_df: pd.DataFrame,
    sdt: str,
    edt: str,
    base_fee: float = FEE_MAIN,
    ret_col: str = "net_ret",
) -> dict:
    """Compute complete D15 + ex-top2 + 50bps stress metrics for window [sdt, edt]."""
    sub_b = bench_df[bench_df["trade_date"].between(sdt, edt)].sort_values("trade_date").reset_index(drop=True)
    if sub_b.empty:
        return {"ss_n": 0, "nav": 1.0}
    cal_dts = sub_b["trade_date"].tolist()
    T = len(cal_dts)
    csi_r = sub_b["csi300_daily_ret"].to_numpy(float)
    csi_pct = (float(np.prod(1.0 + csi_r)) - 1.0) * 100.0

    sub = slot_df[slot_df["buy_date"].between(sdt, edt)].copy().reset_index(drop=True) if not slot_df.empty else pd.DataFrame()
    if raw_df is not None and not raw_df.empty:
        psub = raw_df[raw_df["buy_date"].between(sdt, edt)]
        raw_n = int(len(psub))
        eq_d = psub.groupby("buy_date")[ret_col].mean().to_numpy(float) if not psub.empty else np.array([])
        eq_nav = float(np.prod(1.0 + eq_d)) if len(eq_d) else 1.0
    else:
        raw_n = int(len(sub))
        eq_nav = 1.0

    if sub.empty:
        return {
            "raw_n": raw_n, "ss_n": 0, "wr_pct": 0.0, "plr": 0.0, "mean_pct": 0.0,
            "nav": 1.0, "eq_nav": round(eq_nav, 4), "ex2_nav": 1.0, "ex3_nav": 1.0, "ex_hefu_nav": 1.0,
            "daily_sharpe": 0.0, "daily_mdd_pct": 0.0, "trade_mdd_pct": 0.0, "mtm_diff": 0.0,
            "csi300_pct": round(csi_pct, 2), "excess_csi300_pp": round(-csi_pct, 2),
            "nav_50bps": 1.0, "mean_50bps_pct": 0.0, "sharpe_50bps": 0.0, "mdd_50bps_pct": 0.0,
            "ex2_50bps_nav": 1.0, "excess_csi300_50bps_pp": round(-csi_pct, 2),
        }

    max_ex = str(sub["exit_date"].max())
    cal_ext = bench_df[bench_df["trade_date"].between(sdt, max(edt, max_ex))].sort_values("trade_date").reset_index(drop=True)["trade_date"].tolist()
    dr_full, mtm_diff = daily_mtm_series(sub, cal_ext, ret_col=ret_col)
    dr = dr_full[:T] if len(dr_full) >= T else dr_full
    curve = np.concatenate([[1.0], np.cumprod(1.0 + dr_full)])
    pk = np.maximum.accumulate(curve)
    daily_mdd = float(np.max((pk - curve) / pk) * 100.0)
    sd = float(np.std(dr, ddof=1)) if len(dr) > 1 else 0.0
    sharpe = float(np.mean(dr) / sd * math.sqrt(TRD_DAYS_YEAR)) if sd > 1e-12 else 0.0

    rets = sub[ret_col].to_numpy(float)
    w, l = rets[rets > 0], rets[rets <= 0]
    wr = float((rets > 0).mean() * 100.0)
    plr = float(w.mean() / abs(l.mean())) if (len(w) and len(l) and l.mean() < 0) else (99.0 if len(w) else 0.0)
    nav = float(np.prod(1.0 + rets))
    sr = np.sort(rets)
    ex2 = float(np.prod(1.0 + sr[:-2])) if len(rets) > 2 else 1.0
    ex3 = float(np.prod(1.0 + sr[:-3])) if len(rets) > 3 else 1.0
    ex_hefu = float(np.prod(1.0 + sub.loc[sub["code"].astype(str).str.zfill(6) != "603122", ret_col].to_numpy(float)))
    tc = np.concatenate([[1.0], np.cumprod(1.0 + rets)])
    tp = np.maximum.accumulate(tc)
    tr_mdd = float(np.max((tp - tc) / tp) * 100.0)

    # 50bps stress
    r50 = convert_fee(rets, base_fee, FEE_STRESS)
    sr50 = np.sort(r50)
    ex2_50 = float(np.prod(1.0 + sr50[:-2])) if len(r50) > 2 else 1.0
    nav50 = float(np.prod(1.0 + r50))
    dr50_full, _ = daily_mtm_series(sub, cal_ext, ret_col=ret_col, fee_from=base_fee, fee_to=FEE_STRESS)
    dr50 = dr50_full[:T] if len(dr50_full) >= T else dr50_full
    c50 = np.concatenate([[1.0], np.cumprod(1.0 + dr50_full)])
    pk50 = np.maximum.accumulate(c50)
    mdd50 = float(np.max((pk50 - c50) / pk50) * 100.0)
    sd50 = float(np.std(dr50, ddof=1)) if len(dr50) > 1 else 0.0
    sh50 = float(np.mean(dr50) / sd50 * math.sqrt(TRD_DAYS_YEAR)) if sd50 > 1e-12 else 0.0

    return {
        "raw_n": raw_n,
        "ss_n": int(len(rets)),
        "wr_pct": round(wr, 2),
        "plr": round(plr, 2),
        "mean_pct": round(float(rets.mean() * 100.0), 2),
        "nav": round(nav, 4),
        "eq_nav": round(eq_nav, 4),
        "ex2_nav": round(ex2, 4),
        "ex3_nav": round(ex3, 4),
        "ex_hefu_nav": round(ex_hefu, 4),
        "daily_sharpe": round(sharpe, 3),
        "daily_mdd_pct": round(daily_mdd, 2),
        "trade_mdd_pct": round(tr_mdd, 2),
        "mtm_diff": round(float(mtm_diff), 10),
        "csi300_pct": round(csi_pct, 2),
        "excess_csi300_pp": round((nav - 1.0) * 100.0 - csi_pct, 2),
        "nav_50bps": round(nav50, 4),
        "mean_50bps_pct": round(float(r50.mean() * 100.0), 2),
        "sharpe_50bps": round(sh50, 3),
        "mdd_50bps_pct": round(mdd50, 2),
        "ex2_50bps_nav": round(ex2_50, 4),
        "excess_csi300_50bps_pp": round((nav50 - 1.0) * 100.0 - csi_pct, 2),
    }


def eval_all_windows(
    slot_df: pd.DataFrame,
    raw_df: Optional[pd.DataFrame],
    bench_df: pd.DataFrame,
    max_dt: str = "2026-11-16",
    base_fee: float = FEE_MAIN,
    ret_col: str = "net_ret",
) -> dict:
    wins = [(wn, sdt, min(edt, max_dt)) for wn, sdt, edt in WINDOWS_5 if sdt <= max_dt]
    return {wn: compute_window_metrics(slot_df, raw_df, bench_df, s, e, base_fee=base_fee, ret_col=ret_col) for wn, s, e in wins}


def bootstrap_10k(rets: np.ndarray, n_boot: int = 10000, seed: int = 42) -> dict:
    """10,000x nonparametric bootstrap lower bound on trade returns."""
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
        "mean_p05_pct": round(float(np.percentile(means, 5) * 100.0), 2),
        "mean_p50_pct": round(float(np.percentile(means, 50) * 100.0), 2),
        "nav_p05": round(float(np.percentile(navs, 5)), 4),
        "nav_p50": round(float(np.percentile(navs, 50)), 4),
        "prob_mean_gt_0": round(float(np.mean(means > 0.0)), 4),
        "prob_nav_gt_1": round(float(np.mean(navs > 1.0)), 4),
    }


def perm_2sample_10k(a: np.ndarray, b: np.ndarray, n_perm: int = 10000, seed: int = 42) -> dict:
    """10,000x two-sample permutation test comparing `a` vs `b`."""
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return {"obs_diff_mean_pp": 0.0, "p_mean_1s": 1.0, "p_mean_2s": 1.0}
    obs_m = float(a.mean() - b.mean())
    pool = np.concatenate([a, b])
    tot = float(pool.sum())
    rng = np.random.default_rng(seed)
    cnt1, cnt2 = 0, 0
    n_tot = na + nb
    for s in range(0, n_perm, 500):
        bs = min(500, n_perm - s)
        keys = rng.random((bs, n_tot))
        idx_a = np.argpartition(keys, na, axis=1)[:, :na]
        sum_a = pool[idx_a].sum(axis=1)
        dm = sum_a / na - (tot - sum_a) / nb
        cnt1 += int(np.sum(dm >= obs_m - 1e-12))
        cnt2 += int(np.sum(np.abs(dm) >= abs(obs_m) - 1e-12))
    return {
        "obs_diff_mean_pp": round(obs_m * 100.0, 2),
        "p_mean_1s": round((cnt1 + 1) / (n_perm + 1), 4),
        "p_mean_2s": round((cnt2 + 1) / (n_perm + 1), 4),
    }


def select_single_slot_3to4(df_recs: pd.DataFrame) -> pd.DataFrame:
    """Exact 3to4 single-slot chronology (buy_date, buy_hhmm asc, priority_score desc, code asc)."""
    if df_recs.empty:
        return pd.DataFrame()
    srt = df_recs.sort_values(["buy_date", "buy_hhmm", "priority_score", "code"], ascending=[True, True, False, True], kind="mergesort")
    taken = []
    free_dt, free_hh = "", 0
    for r in srt.itertuples(index=False):
        bd = str(r.buy_date)[:10]
        bh = int(r.buy_hhmm)
        if (not free_dt) or (bd > free_dt) or (bd == free_dt and bh > free_hh):
            taken.append(r._asdict())
            free_dt = str(r.exit_date)[:10]
            free_hh = int(r.exit_hhmm)
    out = pd.DataFrame(taken)
    if not out.empty:
        assert (out["exit_date"] > out["buy_date"]).all(), "T+0 violation"
        for i in range(1, len(out)):
            p, c = out.iloc[i - 1], out.iloc[i]
            assert (c["buy_date"] > p["exit_date"]) or (c["buy_date"] == p["exit_date"] and int(c["buy_hhmm"]) > int(p["exit_hhmm"])), "Overlap violation"
    return out


def select_single_slot_4to5(df_recs: pd.DataFrame, score_col: str = "score", tie_col: Optional[str] = "open_pct") -> tuple[pd.DataFrame, pd.DataFrame]:
    """Exact 4to5 single-slot chronology (buy_date asc, score desc, optional tie_col desc, code asc)."""
    if df_recs.empty:
        return df_recs, df_recs
    df = df_recs[df_recs["buy_date"].notna() & df_recs["exit_date"].notna() & (df_recs["exit_date"] > df_recs["buy_date"])].copy()
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
    taken = []
    cur_ed, cur_eh = "", 0
    for r in srt.itertuples():
        bd = str(r.buy_date)[:10]
        ed = str(r.exit_date)[:10]
        bh = int(getattr(r, "buy_hhmm", 925))
        eh = int(getattr(r, "exit_hhmm", 1500))
        if (not cur_ed) or (bd > cur_ed) or (bd == cur_ed and bh > cur_eh):
            taken.append(r.Index)
            cur_ed, cur_eh = ed, eh
    return srt.reset_index(drop=True), srt.loc[taken].copy().reset_index(drop=True)

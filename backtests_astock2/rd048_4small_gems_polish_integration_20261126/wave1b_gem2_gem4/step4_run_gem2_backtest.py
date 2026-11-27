#!/usr/bin/env python3
"""Step 4 for Gem 2 (Memory-Lean < 1.5 GB Peak RSS):
Backtest & Polish US->CN Mapping (Control 0 Leaky vs Strict PIT Track 1A/1B/Track 2).
Uses EXACT percentage-point units for open_pct (e.g., 1.0 = +1%, 5.0 = +5%, 6.0 = +6%).
Runs 2024-12-31 physical truncation verification in an isolated subprocess so Peak RSS < 2.2 GB.
Strictly ZERO yfinance imports.
"""
import os
for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[k] = "1"

import argparse
import gc
import json
import resource
import subprocess
import sys
import time
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

pa.set_cpu_count(1)
pa.set_io_thread_count(1)

BASE = Path("/Users/huaichuaibeimeng/claude-projects")
OUT_DIR = BASE / "sim-portfolio/backtests_astock2/rd048_4small_gems_polish_integration_20261126/wave1b_gem2_gem4"
W1_BASE = BASE / "sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"

sys.path.insert(0, str(OUT_DIR))
import gem_stats_lib as gsl
import step3_build_gem2_pit_map as s3


EXIT_MAP = {
    "T1O": ("exit_dt_t1o", "gret_t1o", 925),
    "T1C": ("exit_dt_t1c", "gret_t1c", 1500),
    "T2C": ("exit_dt_t2c", "gret_t2c", 1500),
    "MA5": ("exit_dt_ma5", "gret_ma5", 1500),
}


def load_price_lookup_for_codes(c6_set: set[str], cutoff_date: str = "2026-11-25"):
    pq_path = W1_BASE / "stock_day_core_features_pit.parquet"
    px_chunks = []
    for batch in pq.ParquetFile(pq_path).iter_batches(batch_size=300_000, columns=["dt", "c6", "open", "close", "adj_factor"]):
        b = batch.to_pandas()
        dt_ok = {x for x in b["dt"].cat.categories if str(x) <= cutoff_date} if hasattr(b["dt"], "cat") else None
        c6_ok = {x for x in b["c6"].cat.categories if str(x).zfill(6) in c6_set} if hasattr(b["c6"], "cat") else None
        m = (b["dt"].isin(dt_ok) if dt_ok is not None else (b["dt"].astype(str) <= cutoff_date)) & (b["c6"].isin(c6_ok) if c6_ok is not None else b["c6"].astype(str).str.zfill(6).isin(c6_set))
        if m.any():
            sub = b[m].copy()
            sub["dt"] = sub["dt"].astype(str)
            sub["c6"] = sub["c6"].astype(str).str.zfill(6)
            px_chunks.append(sub)
        del b, m
    pa.default_memory_pool().release_unused()
    px_df = pd.concat(px_chunks, ignore_index=True).sort_values(["c6", "dt"]).reset_index(drop=True)
    px_df["adj_o"] = px_df["open"].astype(np.float64) * px_df["adj_factor"].astype(np.float64)
    px_df["adj_c"] = px_df["close"].astype(np.float64) * px_df["adj_factor"].astype(np.float64)
    lookup, pos_cache = {}, {}
    for c6_v, grp in px_df.groupby("c6", sort=False):
        dts_a = grp["dt"].to_numpy()
        lookup[c6_v] = (dts_a, grp["adj_o"].to_numpy(), grp["adj_c"].to_numpy())
        pos_cache[c6_v] = {d: i for i, d in enumerate(dts_a)}
    del px_df, px_chunks
    gc.collect()
    return lookup, pos_cache


def compute_trade_mtm_pairs(c6_v: str, bd: str, ed: str, ex_hhmm: int, fee_rt: float, lookup: dict, pos_cache: dict) -> tuple[list, float]:
    dts_a, ao_a, ac_a = lookup[c6_v][:3]
    pc = pos_cache[c6_v]
    p0 = pc[bd]
    p1 = pc[ed]
    entry_px = ao_a[p0]
    exit_px = ao_a[p1] if (ex_hhmm == 925 and p1 == p0 + 1 and ao_a[p1] > 0) else ac_a[p1]
    gr = float(exit_px / entry_px - 1.0)
    nr = (1.0 + gr) * (1.0 - fee_rt) - 1.0

    raw_pairs = [[dts_a[p0], ac_a[p0] / entry_px - 1.0]]
    if p1 > p0:
        if ex_hhmm == 925 and p1 == p0 + 1 and ao_a[p1] > 0:
            raw_pairs.append([dts_a[p1], ao_a[p1] / ac_a[p0] - 1.0])
        else:
            for k in range(p0 + 1, p1 + 1):
                raw_pairs.append([dts_a[k], ac_a[k] / ac_a[k - 1] - 1.0])

    f_half_geom = np.sqrt(1.0 - fee_rt)
    adj_pairs = []
    for k_i, (d_str, d_ret) in enumerate(raw_pairs):
        factor = 1.0 + float(d_ret)
        if k_i == 0:
            factor *= f_half_geom
        if k_i == len(raw_pairs) - 1:
            factor *= f_half_geom
        adj_pairs.append([str(d_str), round(float(factor - 1.0), 10)])

    prod_chk = float(np.prod([1.0 + x[1] for x in adj_pairs]))
    assert abs(prod_chk - (1.0 + nr)) < 1e-6, f"MTM err on {c6_v} {bd}->{ed}: {prod_chk} vs {1+nr}"
    return adj_pairs, nr


def compute_rank_score(df: pd.DataFrame, rank_mode: str = "corr_amt") -> pd.Series:
    if rank_mode == "us_ret_amt":
        return df["us_max_ret"].fillna(0) * 100.0 + np.log1p(df["amount_yi_t1"].clip(lower=0.0)) * 0.5
    if rank_mode == "corr_amt":
        c = df["us_corr_250d_t1"].fillna(0.15) if "us_corr_250d_t1" in df.columns else 0.15
        return c * 20.0 + np.log1p(df["amount_yi_t1"].clip(lower=0.0)) * 1.0 + df["us_max_ret"].fillna(0) * 10.0
    if rank_mode == "causal_wf_score":
        return df["causal_wf_score"].fillna(0.0)
    return df["amount_yi_t1"].fillna(0.0)


def attach_causal_expanding_score(
    cand_df: pd.DataFrame,
    gret_col: str = "gret_t1c",
    exit_col: str = "exit_dt_t1c",
    min_warmup: int = 40,
    shrink_tau: float = 20.0,
) -> pd.Series:
    feats = ["open_pct", "vol_ratio5_t1", "real_turn_pct_t1", "pos_20d_t1", "ret_5d_t1", "amount_yi_t1", "us_max_ret", "prev_streak"]
    if "us_corr_250d_t1" in cand_df.columns and cand_df["us_corr_250d_t1"].notna().sum() > 50:
        feats.append("us_corr_250d_t1")

    df = cand_df.sort_values(["dt", "c6"])
    orig_index = df.index
    df = df.reset_index(drop=True)
    dts = df["dt"].astype(str).to_numpy()
    ex_dts = df[exit_col].astype(str).to_numpy()
    y = df[gret_col].to_numpy(dtype=np.float64)
    months = np.array([d[:7] for d in dts])
    uniq_months = sorted(np.unique(months))

    scores = np.zeros(len(df), dtype=np.float64)
    for m in uniq_months:
        m_start = f"{m}-01"
        m_mask = (months == m)
        train_mask = (ex_dts != "") & (ex_dts < m_start) & np.isfinite(y)
        n_tr = int(train_mask.sum())
        if n_tr < min_warmup:
            continue
        y_tr = y[train_mask]
        y_z = (y_tr - y_tr.mean()) / max(y_tr.std(ddof=1), 1e-6)
        s_vec = np.zeros(int(m_mask.sum()), dtype=np.float64)
        for fc in feats:
            x_tr = df.loc[train_mask, fc].to_numpy(dtype=np.float64)
            ok = np.isfinite(x_tr)
            if ok.sum() < 20:
                continue
            mu = x_tr[ok].mean()
            sd = max(x_tr[ok].std(ddof=1), 1e-6)
            xz = (x_tr[ok] - mu) / sd
            corr = float(np.mean(xz * y_z[ok]))
            n_ok = float(ok.sum())
            t_stat = corr * np.sqrt(max(n_ok - 2.0, 1.0) / max(1.0 - corr * corr, 1e-6))
            if abs(t_stat) < 1.0:
                continue
            w = corr * (n_ok / (n_ok + shrink_tau))
            x_te = df.loc[m_mask, fc].to_numpy(dtype=np.float64)
            x_tez = np.where(np.isfinite(x_te), np.clip((x_te - mu) / sd, -3.0, 3.0), 0.0)
            s_vec += w * x_tez
        scores[m_mask] = s_vec
    return pd.Series(scores, index=orig_index).reindex(cand_df.index)


def run_gem2_slot_sim(
    cands_df: pd.DataFrame,
    cal_dates: np.ndarray,
    lookup: dict,
    pos_cache: dict,
    variant_name: str,
    pool_label: str,
    exit_type: str = "T1C",
    fee_rt: float = 0.0030,
    rank_mode: str = "corr_amt",
    start_date: str = "2021-01-04",
    end_date: str = "2026-11-25",
    allow_same_0925_chain: bool = False,
    top_k_basket: int = 1,
) -> tuple[pd.DataFrame, np.ndarray]:
    """Chronological selector. top_k_basket=1 = standard single-slot; top_k_basket>1 = equal-weight top-K basket on signal day."""
    ex_col, gret_col, ex_hhmm = EXIT_MAP[exit_type]
    df = cands_df[
        (cands_df["dt"] >= start_date)
        & (cands_df["dt"] <= end_date)
        & (cands_df[ex_col] != "")
        & (cands_df[ex_col] <= end_date)
        & cands_df[gret_col].notna()
    ].copy()
    dt_to_idx = {str(d): i for i, d in enumerate(cal_dates)}
    n_cal = len(cal_dates)
    daily_mtm_rets = np.zeros(n_cal, dtype=np.float64)

    if len(df) == 0:
        return pd.DataFrame(columns=["variant", "buy_date", "exit_date", "buy_hhmm", "exit_hhmm", "code", "name", "net_ret", "mtm_pairs_json"]), daily_mtm_rets

    df["_rank_score"] = compute_rank_score(df, rank_mode)
    df = df.sort_values(["dt", "_rank_score", "c6"], ascending=[True, False, True])

    trades = []
    busy_until_dt = ""
    last_exit_hhmm = 1500

    for bd, grp in df.groupby("dt", sort=True):
        bd = str(bd)
        if bd < busy_until_dt:
            continue
        if bd == busy_until_dt:
            if not (allow_same_0925_chain and last_exit_hhmm == 925):
                continue

        picked = grp.head(top_k_basket)
        if len(picked) == 1:
            r = picked.iloc[0]
            ed = str(r[ex_col])
            c6_v = str(r["c6"])
            adj_pairs, nr = compute_trade_mtm_pairs(c6_v, bd, ed, ex_hhmm, fee_rt, lookup, pos_cache)
            for d_str, adj_ret in adj_pairs:
                idx_d = dt_to_idx.get(d_str)
                if idx_d is not None:
                    daily_mtm_rets[idx_d] = (1.0 + daily_mtm_rets[idx_d]) * (1.0 + adj_ret) - 1.0
            trades.append({
                "variant": variant_name,
                "pool_type": pool_label,
                "buy_date": bd,
                "exit_date": ed,
                "buy_hhmm": 925,
                "exit_hhmm": int(ex_hhmm),
                "code": c6_v,
                "name": str(r.get("name", "")),
                "us_group": str(r.get("us_group", "")),
                "us_max_ret": round(float(r.get("us_max_ret", 0.0)), 4),
                "open_pct": round(float(r.get("open_pct", 0.0)), 4),
                "prev_streak": int(r.get("prev_streak", 0)),
                "fee_bps": round(fee_rt * 10000.0, 1),
                "gross_ret": float(r[gret_col]),
                "net_ret": float(nr),
                "mtm_pairs_json": json.dumps(adj_pairs),
            })
            busy_until_dt = ed
            last_exit_hhmm = ex_hhmm
        else:
            # Equal-weight multi-stock basket: sync exit to max(exit_date) and aggregate daily basket MTM
            # Note: fixed horizon exits (T1O, T1C, T2C) share exact exit_date across all stocks (unless yizi_dt);
            # handle exact equity weighted curve across constituent trades!
            sub_pairs_list, sub_nrs, max_ed = [], [], bd
            for _, r in picked.iterrows():
                ed_i = str(r[ex_col])
                max_ed = max(max_ed, ed_i)
                ap, nr_i = compute_trade_mtm_pairs(str(r["c6"]), bd, ed_i, ex_hhmm, fee_rt, lookup, pos_cache)
                sub_pairs_list.append(ap)
                sub_nrs.append(nr_i)
            # Reconstruct exact EW daily basket NAV from day 0..exit
            w_list = [1.0 / len(sub_pairs_list)] * len(sub_pairs_list)
            all_ds = sorted({p[0] for ap in sub_pairs_list for p in ap})
            day_map_list = [{p[0]: p[1] for p in ap} for ap in sub_pairs_list]
            prev_tot = 1.0
            agg_pairs = []
            # Track each leg cumulative equity
            leg_eq = [1.0] * len(sub_pairs_list)
            for ds in all_ds:
                tot = 0.0
                for j in range(len(sub_pairs_list)):
                    dr_j = day_map_list[j].get(ds, 0.0)
                    leg_eq[j] *= (1.0 + dr_j)
                    tot += w_list[j] * leg_eq[j]
                d_ret = tot / prev_tot - 1.0
                agg_pairs.append([ds, round(float(d_ret), 10)])
                idx_d = dt_to_idx.get(ds)
                if idx_d is not None:
                    daily_mtm_rets[idx_d] = (1.0 + daily_mtm_rets[idx_d]) * (1.0 + d_ret) - 1.0
                prev_tot = tot
            nr_basket = float(np.mean(sub_nrs))
            r0 = picked.iloc[0]
            trades.append({
                "variant": variant_name,
                "pool_type": pool_label,
                "buy_date": bd,
                "exit_date": max_ed,
                "buy_hhmm": 925,
                "exit_hhmm": int(ex_hhmm),
                "code": ",".join(picked["c6"].astype(str).tolist()),
                "name": f"EW{len(picked)}_" + str(r0.get("name", "")),
                "us_group": str(r0.get("us_group", "")),
                "us_max_ret": round(float(r0.get("us_max_ret", 0.0)), 4),
                "open_pct": round(float(picked["open_pct"].mean()), 4),
                "prev_streak": int(picked["prev_streak"].max()),
                "fee_bps": round(fee_rt * 10000.0, 1),
                "gross_ret": float(picked[gret_col].mean()),
                "net_ret": nr_basket,
                "mtm_pairs_json": json.dumps(agg_pairs),
            })
            busy_until_dt = max_ed
            last_exit_hhmm = ex_hhmm

    return pd.DataFrame(trades), daily_mtm_rets


def eval_variant(tdf: pd.DataFrame, mtm: np.ndarray, bench_df: pd.DataFrame, neg_ctrl: dict) -> dict:
    cal_dates = bench_df["date"].to_numpy(dtype=str)
    bench_rets = bench_df["csi300_ret"].to_numpy(dtype=np.float64)
    end_dt = str(cal_dates[-1])
    d15 = {}
    for wk, ws in [("W_5Y_2021_2026", "2021-01-04"), ("W_3Y_2023_2026", "2023-01-03"), ("W_2026", "2026-01-05"), ("W_26H2", "2026-07-01")]:
        d15[wk] = gsl.compute_window_d15_metrics(tdf, mtm, cal_dates, bench_rets, ws, end_dt)
    tests4 = gsl.run_four_small_sample_tests(
        tdf, mtm, cal_dates, bench_rets, ret_col="net_ret", neg_ctrl_summary=neg_ctrl, seed=20261126,
    )
    return {"d15": d15, "four_small_sample_tests": tests4}


def get_pool_slice(cands: pd.DataFrame, pool_name: str, extra=None) -> pd.DataFrame:
    if pool_name == "Control0_Leaky_All":
        sub = cands[cands["pool_type"] == "Control0_Leaky_All"]
    elif pool_name == "Control0_Leaky_Mingmen":
        sub = cands[(cands["pool_type"] == "Control0_Leaky_All") & (cands["c0_mingmen"] == True)]
    elif pool_name == "Control0_Leaky_PrePatch_Mingmen":
        sub = cands[(cands["pool_type"] == "Control0_Leaky_All") & (cands["c0_prepatch_mingmen"] == True)]
    elif pool_name == "Control0_Leaky_Mingmen_NoZT":
        sub = cands[(cands["pool_type"] == "Control0_Leaky_All") & (cands["c0_mingmen"] == True) & (cands["prev_streak"] == 0)]
    else:
        sub = cands[cands["pool_type"] == pool_name]
    if extra is not None:
        sub = sub[extra(sub)]
    return sub.copy()


def build_variant_specs(cands: pd.DataFrame, only_names: set[str] = None) -> list[tuple]:
    """Note: open_pct is in PERCENTAGE POINTS (e.g. -3.0 = -3%, +5.0 = +5%, +6.0 = +6%)!"""
    specs = []

    def add(vn, pool_lbl, sub_fn, ex_type, fee, rmode, top_k=1):
        if only_names is not None and vn not in only_names:
            return
        specs.append((vn, pool_lbl, sub_fn(), ex_type, fee, rmode, top_k))

    # Stage A: Control 0 (Leaky) vs Strict PIT Pools (T1C, 30bps)
    for pool in [
        "Control0_Leaky_All",
        "Control0_Leaky_Mingmen",
        "Control0_Leaky_PrePatch_Mingmen",
        "Control0_Leaky_Mingmen_NoZT",
        "PIT_Track1A_CausalCorr",
        "PIT_Track1B_IR_Plus_Corr",
        "PIT_Track2_Pre2020_Whitelist",
    ]:
        add(f"A_{pool}_AllowZT_T1C_30bps", pool, lambda p=pool: get_pool_slice(cands, p), "T1C", 0.0030, "corr_amt")
        add(f"A_{pool}_NoZT_T1C_30bps", pool, lambda p=pool: get_pool_slice(cands, p, lambda d: d["prev_streak"] == 0), "T1C", 0.0030, "corr_amt")

    # Control 0 Causal WF Reproduction (reproducing w2b6 ModE expanding WF selection)
    for vn_c0, flt_fn in [
        ("A_C0_Leaky_Mingmen_WF_T1C", lambda d: (d["amount_yi_t1"] >= 1.0)),
        ("A_C0_Leaky_Mingmen_NoZT_WF_T1C", lambda d: (d["prev_streak"] == 0) & (d["amount_yi_t1"] >= 1.0)),
    ]:
        if only_names is None or vn_c0 in only_names:
            df_c0 = get_pool_slice(cands, "Control0_Leaky_Mingmen", flt_fn)
            df_c0["causal_wf_score"] = attach_causal_expanding_score(df_c0, gret_col="gret_t1c", exit_col="exit_dt_t1c", min_warmup=80)
            specs.append((vn_c0, "Control0_Leaky_Mingmen", df_c0[df_c0["causal_wf_score"] > 0.05].copy(), "T1C", 0.0030, "causal_wf_score", 1))

    # Stage B: True Percentage-Point Polish Dimensions on Strict PIT Pools
    for pool, short in [
        ("PIT_Track1A_CausalCorr", "PIT1A"),
        ("PIT_Track1B_IR_Plus_Corr", "PIT1B"),
        ("PIT_Track2_Pre2020_Whitelist", "PIT2"),
    ]:
        # Open gap spectrum in percentage points!
        gap_rules = [
            ("GapLow_m4_p1", lambda d: (d["open_pct"] >= -4.0) & (d["open_pct"] <= 1.0)),
            ("GapSweet_m1_p4", lambda d: (d["open_pct"] >= -1.0) & (d["open_pct"] <= 4.0)),
            ("GapMod_p1_p5", lambda d: (d["open_pct"] >= 1.0) & (d["open_pct"] <= 5.0)),
            ("GapHigh_p3_p6", lambda d: (d["open_pct"] > 3.0) & (d["open_pct"] <= 6.0)),
            ("GapOverheat_gt6", lambda d: d["open_pct"] > 6.0),
            ("GapLe5", lambda d: d["open_pct"] <= 5.0),
        ]
        for gname, gfn in gap_rules:
            add(f"B_{short}_AllZT_{gname}_T1C", pool, lambda p=pool, fn=gfn: get_pool_slice(cands, p, fn), "T1C", 0.0030, "corr_amt")
            add(f"B_{short}_NoZT_{gname}_T1C", pool, lambda p=pool, fn=gfn: get_pool_slice(cands, p, lambda d: (d["prev_streak"] == 0) & fn(d)), "T1C", 0.0030, "corr_amt")

        polish_filters = [
            ("US5pct_GapLe5", lambda d: (d["us_max_ret"] >= 0.05) & (d["open_pct"] <= 5.0)),
            ("USBroad3pct_GapLe5", lambda d: (d["us_bench_ret"] >= 0.03) & (d["open_pct"] <= 5.0)),
            ("USBroad3pct_NoZT_GapLe4", lambda d: (d["us_bench_ret"] >= 0.03) & (d["prev_streak"] == 0) & (d["open_pct"] <= 4.0)),
            ("NoZT_GapLe4_Pos20Le70", lambda d: (d["prev_streak"] == 0) & (d["open_pct"] <= 4.0) & (d["pos_20d_t1"] <= 0.70)),
            ("NoZT_GapMod15_VR12", lambda d: (d["prev_streak"] == 0) & (d["open_pct"] >= 1.0) & (d["open_pct"] <= 5.0) & (d["vol_ratio5_t1"] >= 1.2)),
            ("NoZT_GapLow_m3_p1_VR12", lambda d: (d["prev_streak"] == 0) & (d["open_pct"] >= -3.0) & (d["open_pct"] <= 1.0) & (d["vol_ratio5_t1"] >= 1.2)),
            ("AllowZT_GapMod15_Pos20Le80_VR12", lambda d: (d["open_pct"] >= 1.0) & (d["open_pct"] <= 5.0) & (d["pos_20d_t1"] <= 0.80) & (d["vol_ratio5_t1"] >= 1.2)),
            ("NoZT_US5pct_GapSweet_Pos20Le75", lambda d: (d["prev_streak"] == 0) & (d["us_max_ret"] >= 0.05) & (d["open_pct"] >= -1.0) & (d["open_pct"] <= 4.0) & (d["pos_20d_t1"] <= 0.75)),
            ("AllZT_US5pct_GapMod15", lambda d: (d["us_max_ret"] >= 0.05) & (d["open_pct"] >= 1.0) & (d["open_pct"] <= 5.0)),
        ]
        for fname, ffn in polish_filters:
            for ex in ("T1O", "T1C", "T2C", "MA5"):
                add(f"P_{short}_{fname}_{ex}_30bps", pool, lambda p=pool, fn=ffn: get_pool_slice(cands, p, fn), ex, 0.0030, "corr_amt")

        # Equal-weight Top-3 basket check on Broad US >= 3% & US >= 5% Gap<=5%
        for ex in ("T1C", "T2C"):
            add(f"EW3_{short}_USBroad3pct_GapLe5_{ex}_30bps", pool, lambda p=pool: get_pool_slice(cands, p, lambda d: (d["us_bench_ret"] >= 0.03) & (d["open_pct"] <= 5.0)), ex, 0.0030, "corr_amt", top_k=3)
            add(f"EW3_{short}_NoZT_USBroad3pct_GapLe5_{ex}_30bps", pool, lambda p=pool: get_pool_slice(cands, p, lambda d: (d["prev_streak"] == 0) & (d["us_bench_ret"] >= 0.03) & (d["open_pct"] <= 5.0)), ex, 0.0030, "corr_amt", top_k=3)

        # Causal WF Expanding Scorecard
        for ex in ("T1C", "T2C"):
            for zt_lbl, zt_fn in [("AllZT", lambda d: d["open_pct"] <= 5.0), ("NoZT", lambda d: (d["prev_streak"] == 0) & (d["open_pct"] <= 5.0))]:
                vn_wf = f"WF_{short}_{zt_lbl}_CausalScore_{ex}_30bps"
                if only_names is None or vn_wf in only_names:
                    ex_col, gret_col, _ = EXIT_MAP[ex]
                    df_wf = get_pool_slice(cands, pool, zt_fn)
                    df_wf["causal_wf_score"] = attach_causal_expanding_score(df_wf, gret_col=gret_col, exit_col=ex_col)
                    specs.append((vn_wf, pool, df_wf[df_wf["causal_wf_score"] > 0.05].copy(), ex, 0.0030, "causal_wf_score", 1))

    return specs


def run_trunc_worker(variants_json_path: str, out_trunc_path: str):
    """Isolated clean process to rebuild 2024-12-31 PIT map and verify max_abs_diff == 0.0."""
    with open(variants_json_path) as f:
        key_meta = json.load(f)
    only_names = set(key_meta.keys())
    built = s3.build_all_pools("2024-12-31", save_outputs=False)
    cands_tr = built["cands"]
    lookup_tr = built["price_lookup"]
    pos_tr = built["dt_pos_cache"]

    bench = pd.read_parquet(W1_BASE / "v20_daily_bench_20210104_20261125.parquet")
    bench["date"] = bench["trade_date"].astype(str)
    bench_tr = bench[bench["date"] <= "2024-12-31"].sort_values("date").reset_index(drop=True)
    cal_tr = bench_tr["date"].to_numpy(dtype=str)

    specs_tr = {s[0]: s for s in build_variant_specs(cands_tr, only_names=only_names)}
    trunc_out = {}
    for vn, info in key_meta.items():
        _, pool_lbl, sub_tr, ex_type, fee, rmode, top_k = specs_tr[vn]
        t_tr, m_tr = run_gem2_slot_sim(sub_tr, cal_tr, lookup_tr, pos_tr, vn, pool_lbl, ex_type, fee, rmode, end_date="2024-12-31", top_k_basket=top_k)
        tr_sub = t_tr[t_tr["exit_date"] <= "2024-12-31"].reset_index(drop=True)
        trunc_out[vn] = {
            "n_resolved": int(len(tr_sub)),
            "codes": tr_sub["code"].tolist() if len(tr_sub) else [],
            "net_rets": tr_sub["net_ret"].tolist() if len(tr_sub) else [],
            "mtm_tr": m_tr.tolist(),
        }
    Path(out_trunc_path).write_text(json.dumps(trunc_out))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trunc-worker", nargs=2, metavar=("IN_JSON", "OUT_JSON"))
    args = parser.parse_args()
    if args.trunc_worker:
        run_trunc_worker(args.trunc_worker[0], args.trunc_worker[1])
        return

    t0 = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    cands = pd.read_parquet(OUT_DIR / "_gem2_pit_candidates_cache.parquet")
    cand_codes = set(cands["c6"].unique().tolist())
    lookup, pos_cache = load_price_lookup_for_codes(cand_codes, "2026-11-25")

    bench = pd.read_parquet(W1_BASE / "v20_daily_bench_20210104_20261125.parquet")
    bench["date"] = bench["trade_date"].astype(str)
    bench["csi300_ret"] = bench["csi300_daily_ret"].astype(np.float64)
    bench = bench.sort_values("date").reset_index(drop=True)
    cal_dates = bench["date"].to_numpy(dtype=str)

    with open(OUT_DIR / "_gem2_hindsight_audit.json") as f:
        haud = json.load(f)

    # Negative Controls
    neg_ctrls = {}
    for nc_pool in ("NegCtrl_Track2_US_Flat", "NegCtrl_SameInd_LowCorrLag"):
        nc_df, nc_mtm = run_gem2_slot_sim(get_pool_slice(cands, nc_pool), cal_dates, lookup, pos_cache, nc_pool, nc_pool, "T1C", 0.0030, "corr_amt")
        r = nc_df["net_ret"].to_numpy(dtype=np.float64) if len(nc_df) else np.array([])
        sd_v = float(np.std(nc_mtm, ddof=1)) if len(nc_mtm) > 1 else 0.0
        sh = float(np.mean(nc_mtm) / sd_v * np.sqrt(252.0)) if sd_v > 1e-12 else 0.0
        neg_ctrls[nc_pool] = {
            "n_trades_5y": int(len(nc_df)),
            "wr_5y_pct": round(float((r > 0).mean() * 100.0), 2) if len(r) else 0.0,
            "mean_ret_pct": round(float(r.mean() * 100.0), 3) if len(r) else 0.0,
            "nav_5y": round(float(np.prod(1.0 + r)), 4) if len(r) else 1.0,
            "sharpe_5y": round(sh, 3),
        }

    specs = build_variant_specs(cands)
    summary_rows, full_evals, trade_tables = [], {}, []

    for vname, pool_lbl, sub_df, ex_type, fee, rmode, top_k in specs:
        tdf, mtm = run_gem2_slot_sim(sub_df, cal_dates, lookup, pos_cache, vname, pool_lbl, ex_type, fee, rmode, top_k_basket=top_k)
        ev = eval_variant(tdf, mtm, bench, neg_ctrl=neg_ctrls)
        full_evals[vname] = {"exit_type": ex_type, "fee_bps": round(fee * 10000, 1), "top_k_basket": top_k, **ev}
        w5 = ev["d15"]["W_5Y_2021_2026"]
        w3 = ev["d15"]["W_3Y_2023_2026"]
        w26 = ev["d15"]["W_2026"]
        w26h2 = ev["d15"]["W_26H2"]
        b1 = ev["four_small_sample_tests"].get("test1_bootstrap_10k", {})
        summary_rows.append({
            "variant": vname,
            "exit": ex_type,
            "top_k": top_k,
            "fee_bps": round(fee * 10000, 1),
            "n_5y": w5["n_trades"],
            "wr_5y": w5["wr_pct"],
            "nav_5y": w5["mtm_nav"],
            "ex5_5y": w5["ex5_nav"],
            "mdd_5y": w5["mdd_pct"],
            "sharpe_5y": w5["sharpe"],
            "excess_5y_pp": w5["excess_csi300_pp"],
            "n_3y": w3["n_trades"],
            "wr_3y": w3["wr_pct"],
            "nav_3y": w3["mtm_nav"],
            "ex5_3y": w3["ex5_nav"],
            "sharpe_3y": w3["sharpe"],
            "nav_2026": w26["mtm_nav"],
            "nav_26H2": w26h2["mtm_nav"],
            "boot_p_pos": b1.get("prob_positive_expectancy_pct", 0.0),
            "boot_mean_p05": b1.get("mean_ret_pct_p05", 0.0),
        })
        if len(tdf) > 0:
            trade_tables.append(tdf)

    sum_df = pd.DataFrame(summary_rows)
    pit_only = sum_df[sum_df["variant"].str.contains("PIT1A|PIT1B|PIT2|PIT_Track") & (sum_df["n_5y"] >= 20)].copy()
    top_pit_all = pit_only.sort_values(["sharpe_5y", "nav_5y"], ascending=False).head(6).to_dict(orient="records")
    top_pit_nozt = pit_only[pit_only["variant"].str.contains("NoZT")].sort_values(["sharpe_5y", "nav_5y"], ascending=False).head(6).to_dict(orient="records")

    spec_map = {s[0]: s for s in specs}
    key_variants = [
        "A_Control0_Leaky_Mingmen_AllowZT_T1C_30bps",
        "A_Control0_Leaky_PrePatch_Mingmen_AllowZT_T1C_30bps",
        "A_Control0_Leaky_Mingmen_NoZT_T1C_30bps",
        "A_C0_Leaky_Mingmen_WF_T1C",
        "A_C0_Leaky_Mingmen_NoZT_WF_T1C",
        "A_PIT_Track1A_CausalCorr_AllowZT_T1C_30bps",
        "A_PIT_Track1A_CausalCorr_NoZT_T1C_30bps",
        "A_PIT_Track1B_IR_Plus_Corr_AllowZT_T1C_30bps",
        "A_PIT_Track1B_IR_Plus_Corr_NoZT_T1C_30bps",
        "A_PIT_Track2_Pre2020_Whitelist_AllowZT_T1C_30bps",
        "A_PIT_Track2_Pre2020_Whitelist_NoZT_T1C_30bps",
    ]
    for r in top_pit_all[:3] + top_pit_nozt[:3]:
        if r["variant"] not in key_variants:
            key_variants.append(r["variant"])

    stress_results = {}
    key_full_runs = {}
    for vn in key_variants:
        _, pool_lbl, sub_df, ex_type, fee, rmode, top_k = spec_map[vn]
        t_kf, m_kf = run_gem2_slot_sim(sub_df, cal_dates, lookup, pos_cache, vn, pool_lbl, ex_type, fee, rmode, top_k_basket=top_k)
        key_full_runs[vn] = (t_kf, m_kf)
        stress_results[vn] = {}
        for fee_bps in (30, 50, 80):
            t_s, m_s = run_gem2_slot_sim(sub_df, cal_dates, lookup, pos_cache, f"{vn}_f{fee_bps}", pool_lbl, ex_type, fee_bps / 10000.0, rmode, top_k_basket=top_k)
            if fee_bps in (50, 80) and len(t_s) > 0:
                trade_tables.append(t_s)
            ev_s = eval_variant(t_s, m_s, bench, neg_ctrl=neg_ctrls)
            stress_results[vn][f"fee_{fee_bps}bps"] = {
                "5y": ev_s["d15"]["W_5Y_2021_2026"],
                "3y": ev_s["d15"]["W_3Y_2023_2026"],
                "2026": ev_s["d15"]["W_2026"],
            }
        t_o_strict, _ = run_gem2_slot_sim(sub_df, cal_dates, lookup, pos_cache, f"{vn}_T1O_strict", pool_lbl, "T1O", 0.0030, rmode, allow_same_0925_chain=False, top_k_basket=top_k)
        t_o_naive, _ = run_gem2_slot_sim(sub_df, cal_dates, lookup, pos_cache, f"{vn}_T1O_naive", pool_lbl, "T1O", 0.0030, rmode, allow_same_0925_chain=True, top_k_basket=top_k)
        stress_results[vn]["T1O_0925_cash_collision_audit"] = {
            "strict_n": int(len(t_o_strict)),
            "strict_nav_5y": round(float((1.0 + t_o_strict["net_ret"]).prod()), 4) if len(t_o_strict) else 1.0,
            "naive_chain_n": int(len(t_o_naive)),
            "naive_chain_nav_5y": round(float((1.0 + t_o_naive["net_ret"]).prod()), 4) if len(t_o_naive) else 1.0,
        }

    all_trades = pd.concat(trade_tables, ignore_index=True)
    req_cols = ["variant", "buy_date", "exit_date", "buy_hhmm", "exit_hhmm", "code", "name", "net_ret", "mtm_pairs_json"]
    extra_cols = [c for c in all_trades.columns if c not in req_cols]
    all_trades = all_trades[req_cols + extra_cols]
    trades_pq = OUT_DIR / "rd048_gem2_trades.parquet"
    all_trades.to_parquet(trades_pq, index=False)
    total_trade_rows_saved = int(len(all_trades))
    del all_trades, trade_tables, cands, specs, spec_map, lookup, pos_cache
    gc.collect()

    # Run isolated child subprocess for 2024-12-31 physical truncation check
    in_tmp = Path("/tmp/rd048_gem2_trunc_keys.json")
    out_tmp = Path("/tmp/rd048_gem2_trunc_res.json")
    in_tmp.write_text(json.dumps({vn: True for vn in key_variants}))
    subprocess.run([sys.executable, __file__, "--trunc-worker", str(in_tmp), str(out_tmp)], check=True)
    trunc_raw = json.loads(out_tmp.read_text())

    cal_tr = cal_dates[cal_dates <= "2024-12-31"]
    trunc_audit = {}
    max_trunc_diff = 0.0
    for vn in key_variants:
        t_full, m_full = key_full_runs[vn]
        tr_d = trunc_raw[vn]
        f_sub = t_full[t_full["exit_date"] <= "2024-12-31"].reset_index(drop=True)
        n_diff = abs(len(f_sub) - tr_d["n_resolved"])
        if n_diff == 0 and len(f_sub) > 0:
            code_diff = sum(1 for a, b in zip(f_sub["code"].tolist(), tr_d["codes"]) if a != b)
            ret_diff = float(np.max(np.abs(f_sub["net_ret"].to_numpy() - np.array(tr_d["net_rets"], dtype=np.float64))))
        elif n_diff == 0:
            code_diff, ret_diff = 0, 0.0
        else:
            code_diff, ret_diff = n_diff, 999.0

        last_res_idx = len(cal_tr)
        if len(f_sub) > 0:
            open_across = t_full[(t_full["buy_date"] <= "2024-12-31") & (t_full["exit_date"] > "2024-12-31")]
            if len(open_across) > 0:
                last_res_idx = int(np.searchsorted(cal_tr, str(open_across.iloc[0]["buy_date"])))
        m_tr = np.array(tr_d["mtm_tr"], dtype=np.float64)
        m_diff = float(np.max(np.abs(m_full[:last_res_idx] - m_tr[:last_res_idx]))) if (code_diff == 0 and last_res_idx > 0) else (0.0 if code_diff == 0 else 999.0)
        v_max = max(ret_diff, m_diff)
        max_trunc_diff = max(max_trunc_diff, v_max)
        trunc_audit[vn] = {
            "n_resolved_le_20241231": int(len(f_sub)),
            "count_diff": int(n_diff),
            "code_mismatch": int(code_diff),
            "trade_ret_max_abs_diff": float(ret_diff),
            "mtm_daily_max_abs_diff": float(m_diff),
            "pass": bool(v_max == 0.0),
        }

    peak_rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)
    out = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t0, 2),
        "peak_rss_mb": round(peak_rss_mb, 2),
        "d12_yfinance_imported": False,
        "hindsight_audit_product_tree": haud["hindsight_audit_product_tree"],
        "negative_controls": neg_ctrls,
        "stage_a_leaky_vs_pit_table": summary_rows[:16],
        "top_pit_all_zt_and_polished": top_pit_all,
        "top_pit_nozt_strict": top_pit_nozt,
        "key_variants_full_eval": {k: full_evals[k] for k in key_variants},
        "stress_50_80bps_and_0925_collision": stress_results,
        "truncation_20241231_audit": {
            "max_abs_diff_all_key_variants": float(max_trunc_diff),
            "all_pass": bool(max_trunc_diff == 0.0),
            "details": trunc_audit,
        },
        "all_variants_summary": summary_rows,
        "outputs": {
            "trades_parquet": str(trades_pq),
            "total_trade_rows_saved": total_trade_rows_saved,
        },
    }
    out_json = OUT_DIR / "rd048_gem2_usmap.json"
    out_json.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"DONE step4_run_gem2_backtest in {out['elapsed_sec']}s | peak RSS={out['peak_rss_mb']}MB | trunc max_abs_diff={max_trunc_diff}")
    cols_s = ["variant", "n_5y", "wr_5y", "nav_5y", "ex5_5y", "mdd_5y", "sharpe_5y", "excess_5y_pp", "n_3y", "wr_3y", "nav_3y", "nav_2026", "boot_p_pos"]
    print("\n=== Stage A: Control 0 (Leaky) vs Strict PIT Track 1A/1B/2 (T1C, 30bps) ===")
    print(sum_df.iloc[:16][cols_s].to_string(index=False))
    print("\n=== Top PIT (All/Polished) ===")
    print(pd.DataFrame(top_pit_all)[cols_s].to_string(index=False))
    print("\n=== Top PIT (Strict NoZT) ===")
    print(pd.DataFrame(top_pit_nozt)[cols_s].to_string(index=False))


if __name__ == "__main__":
    main()

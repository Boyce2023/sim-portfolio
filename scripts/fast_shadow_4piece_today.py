#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
fast_shadow_4piece_today.py — 稳健四件套 (RD038 GREEDY_ROBUST) 每日只读影子对照引擎
================================================================================
严格只读：绝不修改任何现役 V20.0 生产脚本、盘前缓存或持仓状态；零 yfinance (D12)。
精确对齐 RD038 GREEDY_ROBUST 规格：
  1. 一进二 (1to2)      : V20.0 原版不变
  2. 超跌撬板 (pry)     : V20.0 原版不变
  3. 20cm (stack_c50_avg): 昨10cm涨停 < 50 关 F06 + (d_cb15 + d_mn15 + d_3w12)/3 四舍五入，门槛 S>=80
  4. 三进四 (m4_4way_bl15): 因果四因子排雷黑名单 (top 15%) 拦截
  5. 二进三 (m2_pair_cold45_d15): 昨10cm涨停 < 45 冷清日因果配对调分 [+-15]
  6. 高标首阴 (m1_causal_cold_drop40_t0): 昨10cm涨停 < 40 剔除负向加分项
  7. 买卖点、执行价与 S2C 三梯队顺位 100% 保持现役 V20.0 不变。
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

import argparse
import bisect
import datetime
import json
import math
import pickle
import re
import sqlite3
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM_DIR = f"{ROOT}/sim-portfolio"
DATA_DIR = f"{SIM_DIR}/data"
SCRIPTS_DIR = f"{SIM_DIR}/scripts"

RD034_DIR = f"{SIM_DIR}/backtests_astock2/rd034_ashare_3layer_cycles_6strat_20261125"
RD035_BASE = f"{SIM_DIR}/backtests_astock2/rd035_grand_wf_scorecard_20261125"
RD036_DIR = f"{SIM_DIR}/backtests_astock2/rd036_highorder_3way_4way_20261126"
RD038_DIR = f"{SIM_DIR}/backtests_astock2/rd038_grand_bundle_assembly_20261126"

CAUSAL_CACHE_PKL = f"{DATA_DIR}/shadow_4piece_causal_cache.pkl"
T1_CACHE_JSON = f"{DATA_DIR}/shadow_4piece_t1_cache.json"
LEDGER_JSONL = f"{DATA_DIR}/shadow_4piece_2w_ledger.jsonl"

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"


# ---------------------------------------------------------------------------
# Pure-Numpy Exact RD038 / RD036 / RD035 Scorers (Zero Heavy Runtime Imports)
# ---------------------------------------------------------------------------

def score_card_by_name(feat_rows: list[dict[str, float]], card: dict) -> np.ndarray:
    """Evaluate a causal scorecard using feature names directly (exact _wf_core parity)."""
    n = len(feat_rows)
    factors = card.get("factors", [])
    if not factors:
        return np.full(n, 50 if card.get("mode") == "scorecard_0_100" else 0, dtype=np.int32)
    tot = np.zeros(n, dtype=np.int32)
    for f in factors:
        fname = f["name"]
        col = np.array([float(r.get(fname, np.nan)) if r.get(fname) is not None else np.nan for r in feat_rows], dtype=np.float64)
        edges = f["edges"]
        pts = np.asarray(f["bin_pts"], dtype=np.int32)
        nan_pt = int(f["nan_pt"])
        valid = np.isfinite(col)
        sc = np.full(n, nan_pt, dtype=np.int32)
        if valid.any():
            xv = col[valid]
            if f.get("is_discrete"):
                ed = np.asarray(edges, dtype=np.float64)
                idx = np.argmin(np.abs(xv[:, None] - ed[None, :]), axis=1)
                sc[valid] = pts[idx]
            elif len(edges) == 1:
                idx = (xv > float(edges[0])).astype(np.int32)
                sc[valid] = pts[idx]
            else:
                e0, e1 = float(edges[0]), float(edges[1])
                idx = np.where(xv <= e0, 0, np.where(xv <= e1, 1, 2))
                sc[valid] = pts[idx]
        tot += sc
    if card.get("mode") == "scorecard_0_100":
        tot = np.clip(tot, 0, 100)
    return tot


def eval_3way_rules_by_name(feat_rows: list[dict[str, float]], rules: list[dict]) -> list[dict[str, float]]:
    """Evaluate frozen 20cm 3-way rules into named binary feature dicts."""
    n = len(feat_rows)
    out = [{} for _ in range(n)]
    if not rules or n == 0:
        return out
    for r in rules:
        rname = r["name"]
        for i, row in enumerate(feat_rows):
            hit = True
            for t in r["terms"]:
                tname = t["name"]
                v = row.get(tname, np.nan)
                xv = float(v) if (v is not None and np.isfinite(float(v))) else float(t["med"])
                cond = (xv > float(t["thr"])) if int(t["state"]) == 1 else (xv <= float(t["thr"]))
                if not cond:
                    hit = False
                    break
            out[i][rname] = 1.0 if hit else 0.0
    return out


def score_4way_mine_by_name(feat_rows: list[dict[str, float]], m_mn: dict) -> tuple[np.ndarray, np.ndarray, list[list[str]]]:
    """Evaluate RD036 3to4 M4 4-way minefield blacklist (`m4_4way_bl15`)."""
    n = len(feat_rows)
    rules = m_mn.get("rules", [])
    base_meta = m_mn.get("base_meta", [])
    q85 = float(m_mn.get("q_cuts", {}).get("q85", 999.0))
    thr = max(1.0, q85)
    if not rules or not base_meta or n == 0:
        return np.zeros(n, dtype=np.float64), np.zeros(n, dtype=bool), [[] for _ in range(n)]

    k = len(base_meta)
    l_mat = np.zeros((n, 2 * k), dtype=bool)
    for m in base_meta:
        bi = int(m["base_idx"])
        cname = m["name"]
        med = float(m["med"])
        bthr = float(m["thr"])
        col = np.array([float(r.get(cname, np.nan)) if r.get(cname) is not None else np.nan for r in feat_rows], dtype=np.float64)
        xv = np.where(np.isfinite(col), col, med)
        hi = xv > bthr
        l_mat[:, 2 * bi] = hi
        l_mat[:, 2 * bi + 1] = ~hi

    tot = np.zeros(n, dtype=np.float64)
    matched = [[] for _ in range(n)]
    for r in rules:
        m_hit = np.ones(n, dtype=bool)
        for l_idx, s in r["lits"]:
            m_hit &= l_mat[:, 2 * int(l_idx) + int(s)]
        pts = float(r["pts"])
        tot[m_hit] += pts
        for i in np.where(m_hit)[0]:
            matched[i].append(str(r.get("label", "")))

    blocked = tot >= thr
    return tot, blocked, matched


def attach_dyn_pairs_by_name(feat_rows: list[dict[str, float]], card: dict) -> list[dict[str, float]]:
    """Compute any `dyn_*` pairwise features referenced in `card['dyn_pairs_meta']` by column name."""
    dyn_meta = card.get("dyn_pairs_meta", [])
    needed_dyn = {f["name"] for f in card.get("factors", []) if str(f.get("name", "")).startswith("dyn_")}
    if not dyn_meta or not needed_dyn:
        return feat_rows
    out = [dict(r) for r in feat_rows]
    for d in dyn_meta:
        pname = d["name"]
        if pname not in needed_dyn:
            continue
        col_a = d["col_a"]
        col_b = d["col_b"]
        tag = d["tag"]
        for i, row in enumerate(feat_rows):
            va = row.get(col_a, np.nan)
            vb = row.get(col_b, np.nan)
            xa = float(va) if (va is not None and np.isfinite(float(va))) else float(d["med_a"])
            xb = float(vb) if (vb is not None and np.isfinite(float(vb))) else float(d["med_b"])
            ha = xa > float(d["thr_a"])
            hb = xb > float(d["thr_b"])
            if tag == "HiHi":
                val = 1.0 if (ha and hb) else 0.0
            elif tag == "HiLo":
                val = 1.0 if (ha and (not hb)) else 0.0
            elif tag == "LoHi":
                val = 1.0 if ((not ha) and hb) else 0.0
            elif tag == "LoLo":
                val = 1.0 if ((not ha) and (not hb)) else 0.0
            else:
                za = max(-3.0, min(3.0, (xa - float(d["med_a"])) / float(d["iqr_a"]))) * float(d["sgn_a"])
                zb = max(-3.0, min(3.0, (xb - float(d["med_b"])) / float(d["iqr_b"]))) * float(d["sgn_b"])
                val = za * zb
            out[i][pname] = val
    return out


# ---------------------------------------------------------------------------
# Lazy Research Importers (Used ONLY by --refresh-cache and --verify-rd038)
# ---------------------------------------------------------------------------

def _lazy_import_rd038():
    paths = [
        f"{RD035_BASE}/wave1_base",
        f"{RD035_BASE}/wave2a/w2a3_old_20cm",
        f"{RD035_BASE}/wave2a/w2a4_pairwise_interactions",
        f"{RD036_DIR}/part1_20cm",
        f"{RD036_DIR}/part2_other5",
        RD038_DIR,
    ]
    for p in paths:
        if p not in sys.path:
            sys.path.insert(0, p)
    import rd036_lib as lib20
    import _wf_core as wfc
    import _common_rd036 as cm
    import run_m1_m2_cold_and_pairwise as m12
    import run_m3_m4_3way_4way_trees as m34
    assert "yfinance" not in sys.modules, "D12 violation after lazy import"
    return lib20, wfc, cm, m12, m34


def fit_20cm_stack_c50_as_of(cutoff_dt: str, p20: pd.DataFrame, meta20: dict, lib20, wfc) -> dict:
    """Fit exact causal 20cm stack_c50_avg cards using strictly exit_date < cutoff_dt."""
    can_buy = p20["can_buy_hygiene"].to_numpy(bool) & (p20["exit_date"].astype(str).to_numpy() < cutoff_dt)
    ex_idx = sorted(
        np.where(can_buy)[0].tolist(),
        key=lambda i: (str(p20["exit_date"].iloc[i]), str(p20["buy_date"].iloc[i]), str(p20["code"].iloc[i])),
    )
    tr = p20.iloc[ex_idx]
    y_ret = tr["net_ret"].to_numpy(float)
    y_win = (y_ret > 0.0).astype(float)
    uniq_d = sorted(set(tr["buy_date"].astype(str)))
    d_map = {d: i for i, d in enumerate(uniq_d)}
    d_ids = np.array([d_map[d] for d in tr["buy_date"].astype(str)], dtype=np.int32)
    orig_tr = tr["v20_cold50"].to_numpy(float)

    # 1. CLEAN_B delta_15
    fcb = meta20["feat_clean_b"]
    X_cb_raw = tr[fcb].apply(pd.to_numeric, errors="coerce").to_numpy(float)
    min_v = max(35, int(0.45 * len(tr)))
    keep_cb = []
    for j in range(X_cb_raw.shape[1]):
        xv = X_cb_raw[:, j]
        xv = xv[np.isfinite(xv)]
        if len(xv) < min_v:
            continue
        uniq, cnts = np.unique(xv, return_counts=True)
        if len(uniq) <= 3 and (len(cnts) < 2 or int(np.sort(cnts)[-2]) < 15):
            continue
        keep_cb.append(j)
    cb_names = [fcb[j] for j in keep_cb]
    card_cb = wfc.fit_causal_scorecard(
        X_cb_raw[:, keep_cb], y_ret, y_win, d_ids, cb_names,
        mode="delta_patch", top_k=10, min_k=5, max_corr=0.65,
        max_corr_orig=0.70, min_t_stat=1.0, shrink_tau=20.0,
        max_delta=15, orig_score_train=orig_tr,
    )

    # 2. Mech130 delta_15
    fix = meta20["ix_cols"]
    X_mn = tr[fix].apply(pd.to_numeric, errors="coerce").to_numpy(float)
    card_mn = wfc.fit_causal_scorecard(
        X_mn, y_ret, y_win, d_ids, fix,
        mode="delta_patch", top_k=10, min_k=5, max_corr=0.65,
        max_corr_orig=0.70, min_t_stat=1.0, shrink_tau=20.0,
        max_delta=15, orig_score_train=orig_tr,
    )

    # 3. Rule3Way delta_12 (exact parameters from rd036_lib.py lines 1091-1109)
    fat = meta20["atomic_cols"]
    X_at = tr[fat].apply(pd.to_numeric, errors="coerce").to_numpy(float)
    res_ho = lib20.fit_causal_3way_and_4way_rules(
        X_at, y_ret, y_win, d_ids, fat,
        top_base_k=25, max_base_corr=0.70,
        min_leaf_3way=25, min_pct_3way=0.05, min_t_3way=2.5,
        min_syn_t_3way=1.5, min_cond_t_3way=1.1,
        min_leaf_4way=20, min_t_4way=2.8, min_syn_t_4way=1.5,
        max_rules_keep=24, enable_4way=False,
    )
    rules_3w = res_ho["rules_3way"]
    if res_ho["X_3way"].shape[1] > 0:
        card_3w = wfc.fit_causal_scorecard(
            res_ho["X_3way"], y_ret, y_win, d_ids,
            [r["name"] for r in rules_3w],
            mode="delta_patch", top_k=8, min_k=1, max_corr=0.65,
            min_t_stat=1.5, shrink_tau=20.0, max_delta=12,
        )
    else:
        card_3w = {"mode": "delta_patch", "factors": []}
    used_3w_names = {f["name"] for f in card_3w.get("factors", [])}
    active_rules_3w = [r for r in rules_3w if r["name"] in used_3w_names]

    return {
        "card_cb": card_cb,
        "card_mn": card_mn,
        "card_3w": card_3w,
        "rules_3w": active_rules_3w,
    }


def fit_3to4_m4_as_of(cutoff_dt: str, df34: pd.DataFrame, bp34: list[str], m34) -> dict:
    """Fit exact causal 3to4 m4_4way_bl15 minefield blacklist strictly exit_date < cutoff_dt."""
    can_buy = df34["can_buy_hygiene"].to_numpy(bool) & (df34["exit_date"].astype(str).to_numpy() < cutoff_dt)
    ex_idx = sorted(
        np.where(can_buy)[0].tolist(),
        key=lambda i: (str(df34["exit_date"].iloc[i]), str(df34["buy_date"].iloc[i]), str(df34["code"].iloc[i])),
    )
    if len(ex_idx) < 20:
        return {"base_meta": [], "rules": [], "q_cuts": {}}
    tr = df34.iloc[ex_idx]
    Xb = tr[bp34].apply(pd.to_numeric, errors="coerce").to_numpy(float)
    ym = (tr["net_ret_030"].to_numpy(float) <= -0.07).astype(float)
    uniq_d = sorted(set(tr["buy_date"].astype(str)))
    dm = {d: i for i, d in enumerate(uniq_d)}
    d_ids = np.array([dm[d] for d in tr["buy_date"].astype(str)], dtype=np.int32)
    return m34.fit_4way_synergy_card(Xb, ym, ym, d_ids, bp34, min_leaf=20, min_days=8, max_deltas=(100,), orig_tr=None, mode="mine_0_100")


def fit_2to3_m2_as_of(cutoff_dt: str, df23: pd.DataFrame, ix_cols: list[str], bp23: list[str], cm, m12) -> dict:
    """Fit exact causal 2to3 m2_pair_cold45_d15 card strictly exit_date < cutoff_dt & mkt10 < 45."""
    can_buy = (
        df23["can_buy_hygiene"].to_numpy(bool)
        & (df23["exit_date"].astype(str).to_numpy() < cutoff_dt)
        & (df23["mkt10_zt_est_t1"].to_numpy(float) < 45.0)
    )
    ex_idx = sorted(
        np.where(can_buy)[0].tolist(),
        key=lambda i: (str(df23["exit_date"].iloc[i]), str(df23["buy_date"].iloc[i]), str(df23["code"].iloc[i])),
    )
    tr = df23.iloc[ex_idx]
    Xm = tr[ix_cols].apply(pd.to_numeric, errors="coerce").to_numpy(float)
    Xb = tr[bp23].apply(pd.to_numeric, errors="coerce").to_numpy(float)
    y_ret = tr["net_ret_030"].to_numpy(float)
    y_win = (y_ret > 0.0).astype(float)
    uniq_d = sorted(set(tr["buy_date"].astype(str)))
    dm = {d: i for i, d in enumerate(uniq_d)}
    d_ids = np.array([dm[d] for d in tr["buy_date"].astype(str)], dtype=np.int32)
    orig_tr = tr["orig_score"].to_numpy(float)
    cards = m12._fit_pairwise_multi_delta(
        Xm, Xb, y_ret, y_win, d_ids, ix_cols, bp23,
        max_deltas=(15,), orig_tr=orig_tr, min_cell=cm.MIN_LEAF_MAP["2to3"],
    )
    card = cards[15]
    for pm in card.get("dyn_pairs_meta", []):
        pm["col_a"] = bp23[int(pm["j_a"])]
        pm["col_b"] = bp23[int(pm["j_b"])]
    return card


def fit_high_m1_as_of(cutoff_dt: str, dfhi: pd.DataFrame, cols_hi: list[str], cmat_hi: np.ndarray, m12) -> list[str]:
    """Fit exact causal high m1_causal_cold_drop40_t0 drop atom list strictly exit_date < cutoff_dt."""
    can_buy = dfhi["can_buy_hygiene"].to_numpy(bool) & (dfhi["exit_date"].astype(str).to_numpy() < cutoff_dt)
    ex_idx = sorted(
        np.where(can_buy)[0].tolist(),
        key=lambda i: (str(dfhi["exit_date"].iloc[i]), str(dfhi["buy_date"].iloc[i]), str(dfhi["code"].iloc[i])),
    )
    if len(ex_idx) < 10:
        return []
    ex_arr = np.asarray(ex_idx, dtype=np.int64)
    is_cold = dfhi["mkt10_zt_est_t1"].to_numpy(float)[ex_arr] < 40.0
    sub_idx = ex_arr[is_cold] if int(is_cold.sum()) >= 10 else ex_arr
    rv = dfhi["net_ret_030"].to_numpy(float)[sub_idx]
    wv = (rv > 0.0).astype(float)
    uniq_d = sorted(set(dfhi["buy_date"].astype(str)))
    dm = {d: i for i, d in enumerate(uniq_d)}
    dv = np.array([dm[str(dfhi["buy_date"].iloc[i])] for i in sub_idx], dtype=np.int32)
    mu0, wr0 = float(rv.mean()), float(wv.mean())
    sdr = max(1e-5, float(rv.std(ddof=1)))
    u = 0.6 * (rv - mu0) / sdr + 0.4 * (wv - wr0) / 0.25
    drop_cols = []
    for j, col in enumerate(cols_hi):
        if float(np.max(cmat_hi[:, j])) <= 0.0:
            continue
        xj = cmat_hi[sub_idx, j]
        if float(np.std(xj)) < 1e-12:
            continue
        if m12._cluster_t_weighted(u, xj, dv, None) < 0.0:
            drop_cols.append(col)
    return drop_cols


def _build_compressed_pit_st_tl(cutoff_dt: str) -> dict[str, tuple[list[str], list[int]]]:
    if RD034_DIR not in sys.path:
        sys.path.insert(0, RD034_DIR)
    import step1_build_3layer_cycles_pit as r34
    raw_tl = r34.build_pit_st_timeline(cutoff_dt)
    comp: dict[str, tuple[list[str], list[int]]] = {}
    for c6, (ts_l, val_l) in raw_tl.items():
        nt, nv = [], []
        for t, v in zip(ts_l, val_l):
            if not nv or v != nv[-1]:
                if nt and nt[-1] == t:
                    nv[-1] = v
                else:
                    nt.append(t)
                    nv.append(v)
        if any(x == 1 for x in nv):
            comp[c6] = (nt, nv)
    return comp


def _is_pit_st(pit_st_tl: Optional[dict], c6: str, dt: str, fallback_st: set[str]) -> bool:
    if pit_st_tl:
        tl = pit_st_tl.get(c6)
        if not tl:
            return False
        idx = bisect.bisect_left(tl[0], f"{dt} 15:00:00")
        return bool(tl[1][idx - 1] == 1) if idx > 0 else False
    return c6 in fallback_st


def _extract_compact_ref_tails(cutoff_dt: str) -> dict:
    """Store lightweight historical reference slices (<2MB) so daily T-1 extensions run <0.5s."""
    rd35_mkt_p = f"{RD035_BASE}/wave1_base/market_daily_all_new_factors_pit.parquet"
    rd35_mkt = pd.read_parquet(rd35_mkt_p)
    bp_p = f"{ROOT}/output/china_policy_macro_rd027_20261125/rd029_daybyday_etf/cache/breadth_daily_2005_20261125.parquet"
    bp = pd.read_parquet(bp_p, columns=["date", "total_amount_yi", "turn_mkt_weighted", "margin_balance_yi"])
    bp["dt"] = pd.to_datetime(bp["date"]).dt.strftime("%Y-%m-%d")
    bp = bp.sort_values("dt").tail(800).reset_index(drop=True)

    dmp_p = f"{ROOT}/output/china_policy_macro_rd027_20261125/rd029_daybyday_etf/cache/daily_market_panel_2000_20261125.parquet"
    dmp = pd.read_parquet(dmp_p, columns=["date", "bank_idx_close", "tmt_info_close", "csi300_close"])
    dmp["dt"] = pd.to_datetime(dmp["date"]).dt.strftime("%Y-%m-%d")
    full_cal_to_25 = sorted(dmp["dt"].unique().tolist())
    dmp_tail = dmp.sort_values("dt").tail(80).reset_index(drop=True)

    comm_dir = f"{SIM_DIR}/output/extreme_commodities_3ring_backtest_20261125/data_cache"
    cf = pd.read_parquet(f"{comm_dir}/cn_futures_close.parquet")[["RB0", "AL0"]].tail(40).copy()
    cf.index = pd.to_datetime(cf.index).strftime("%Y-%m-%d")
    gf = pd.read_parquet(f"{comm_dir}/global_futures_close.parquet")[["GC_F", "HG_F", "CL_F"]].tail(40).copy()
    gf.index = pd.to_datetime(gf.index).strftime("%Y-%m-%d")

    vx = pd.read_parquet(f"{DATA_DIR}/us_price_db/benchmarks/VIX.parquet")[["close"]].tail(40).copy()
    vx.index = pd.to_datetime(vx.index).strftime("%Y-%m-%d")

    v3_p = f"{ROOT}/output/china_policy_macro_rd027_20261125/rd029_daybyday_etf/cache/v3_raw_panel_2016_20261125.parquet"
    v3_tail = pd.read_parquet(v3_p).tail(20).copy()

    me_p = f"{ROOT}/output/csrc_policy_100factors_20261114/policy_polymarket_v1/master_events_v2_20261125.parquet"
    me = pd.read_parquet(me_p, columns=["tradable_date", "speculation_fraud_crackdown", "share_reduction_crackdown"])
    me["td"] = pd.to_datetime(me["tradable_date"]).dt.strftime("%Y-%m-%d")
    me = me[me["td"] >= "2026-10-01"].copy()
    me["is_crack"] = ((me["speculation_fraud_crackdown"].fillna(0) > 0) | (me["share_reduction_crackdown"].fillna(0) > 0)).astype(float)
    crack_by_dt = me.groupby("td")["is_crack"].sum().to_dict()

    with open(f"{SIM_DIR}/output/extreme_commodities_3ring_backtest_20261125/three_ring_mapping.json") as f:
        tm = json.load(f)
    stock_ring = {}
    for _, item in tm["commodities"].items():
        for tier, key in [(1, "ring1"), (2, "ring2"), (3, "ring3")]:
            for tk in item.get(key, []):
                c6 = str(tk)[:6]
                if c6 not in stock_ring or tier < stock_ring[c6]:
                    stock_ring[c6] = tier

    csrc = pd.read_csv(f"{DATA_DIR}/csrc_industry_pit_clean.csv")
    csrc["c6"] = csrc["sec_code"].astype(str).str.zfill(6)
    csrc = csrc[csrc["industry"].notna()].sort_values(["c6", "start_date"])
    csrc_latest = csrc.groupby("c6", as_index=False).last()[["c6", "industry"]].set_index("c6")["industry"].to_dict()

    return {
        "rd35_mkt_tail": rd35_mkt.tail(40).reset_index(drop=True),
        "rd35_mkt_max_dt": str(rd35_mkt["trade_date"].max()),
        "bp_tail": bp,
        "full_cal_to_25": full_cal_to_25,
        "anchor_2008_11_04_pos": int(np.searchsorted(full_cal_to_25, "2008-11-04")),
        "dmp_tail": dmp_tail,
        "cf_tail": cf.to_dict(),
        "gf_tail": gf.to_dict(),
        "vx_tail": vx["close"].to_dict(),
        "v3_tail": v3_tail,
        "crack_by_dt": crack_by_dt,
        "stock_ring": stock_ring,
        "csrc_latest": csrc_latest,
        "pit_st_tl": _build_compressed_pit_st_tl(cutoff_dt),
    }


def build_or_load_causal_cache(force_refresh: bool = False, cutoff_dt: Optional[str] = None) -> dict:
    """Load or causally rebuild GREEDY_ROBUST models strictly exit_date < cutoff_dt."""
    if cutoff_dt is None:
        cutoff_dt = datetime.date.today().isoformat()
    if (not force_refresh) and os.path.exists(CAUSAL_CACHE_PKL):
        try:
            with open(CAUSAL_CACHE_PKL, "rb") as f:
                obj = pickle.load(f)
            if obj.get("schema_v") == 3 and obj.get("cutoff_dt") == cutoff_dt:
                return obj
        except Exception:
            pass

    lib20, wfc, cm, m12, m34 = _lazy_import_rd038()
    with open(f"{RD038_DIR}/_cache/rd038_master_cache.pkl", "rb") as f:
        rd38 = pickle.load(f)
    with open(f"{RD036_DIR}/part2_other5/_cache/rd036_other5_bundle.pkl", "rb") as f:
        bundle = pickle.load(f)

    p20, meta20 = lib20.load_20cm_enriched_data()
    m20 = fit_20cm_stack_c50_as_of(cutoff_dt, p20, meta20, lib20, wfc)

    df34 = rd38["pools_ext"]["3to4"]
    bp34 = list(dict.fromkeys(bundle["base_dyn_cols"] + bundle["atom_info"]["3to4"]["cols"]))
    m34_card = fit_3to4_m4_as_of(cutoff_dt, df34, bp34, m34)

    df23 = rd38["pools_ext"]["2to3"]
    bp23 = list(dict.fromkeys(bundle["base_dyn_cols"] + bundle["atom_info"]["2to3"]["cols"]))
    c23_card = fit_2to3_m2_as_of(cutoff_dt, df23, bundle["ix_cols"], bp23, cm, m12)

    dfhi = rd38["pools_ext"]["high"]
    hi_drops = fit_high_m1_as_of(
        cutoff_dt, dfhi, bundle["atom_info"]["high"]["cols"], bundle["atom_info"]["high"]["contrib_mat"], m12
    )

    obj = {
        "schema_v": 3,
        "built_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "cutoff_dt": cutoff_dt,
        "models": {
            "20cm": m20,
            "3to4": m34_card,
            "2to3": c23_card,
            "high_drop_cols": hi_drops,
        },
        "refs": _extract_compact_ref_tails(cutoff_dt),
    }
    tmp = CAUSAL_CACHE_PKL + ".tmp"
    with open(tmp, "wb") as f:
        pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp, CAUSAL_CACHE_PKL)
    return obj


# ---------------------------------------------------------------------------
# Fast Read-Only Daily Market & Candidate Stock Feature Builder
# ---------------------------------------------------------------------------

def _http_get_text(url: str, headers: Optional[dict] = None, timeout: float = 1.8) -> str:
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    hdr = {"User-Agent": "Mozilla/5.0"}
    if headers:
        hdr.update(headers)
    with op.open(urllib.request.Request(url, headers=hdr), timeout=timeout) as resp:
        raw = resp.read()
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", errors="ignore")


def _load_st_set() -> set[str]:
    p = f"{DATA_DIR}/st_universe.json"
    if not os.path.exists(p):
        return set()
    d = json.load(open(p, encoding="utf-8"))
    codes = d.get("codes", d) if isinstance(d, dict) else d
    return {str(x)[-6:].zfill(6) for x in codes}


def _fetch_sina_idx_klines(sym: str, datalen: int = 35) -> dict[str, float]:
    url = (
        f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var/CN_MarketDataService.getKLineData"
        f"?symbol={sym}&scale=240&ma=no&datalen={datalen}"
    )
    try:
        txt = _http_get_text(url, timeout=1.5)
        i, j = txt.find("["), txt.rfind("]")
        if i >= 0 and j > i:
            return {str(r["day"])[:10]: float(r["close"]) for r in json.loads(txt[i : j + 1])}
    except Exception:
        pass
    return {}


def _fetch_sina_vix_and_fut() -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        raw = _http_get_text(
            "http://hq.sinajs.cn/list=znb_VIX,hf_GC,hf_HG,hf_CL,nf_RB0,nf_AL0",
            headers={"Referer": "https://finance.sina.com.cn"},
            timeout=1.5,
        )
        for ln in raw.strip().splitlines():
            if '="' not in ln:
                continue
            k, v = ln.split('="', 1)
            val = v.rstrip('";')
            parts = val.split(",")
            if k.endswith("znb_VIX") and len(parts) >= 8:
                out["vix"] = (str(parts[6])[:10], float(parts[1] or 0.0))
            elif k.endswith("hf_GC") and len(parts) >= 13:
                out["GC_F"] = (str(parts[12])[:10], float(parts[0] or 0.0), float(parts[7] or 0.0))
            elif k.endswith("hf_HG") and len(parts) >= 13:
                out["HG_F"] = (str(parts[12])[:10], float(parts[0] or 0.0), float(parts[7] or 0.0))
            elif k.endswith("nf_RB0") and len(parts) >= 18:
                out["RB0"] = (str(parts[17])[:10], float(parts[8] or 0.0))
            elif k.endswith("nf_AL0") and len(parts) >= 18:
                out["AL0"] = (str(parts[17])[:10], float(parts[8] or 0.0))
    except Exception:
        pass
    return out


def _fetch_fut_daily_sina(sym: str) -> dict[str, float]:
    url = f"https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var/InnerFuturesNewService.getDailyKLine?symbol={sym}"
    try:
        txt = _http_get_text(url, headers={"Referer": "https://finance.sina.com.cn"}, timeout=1.5)
        i, j = txt.find("["), txt.rfind("]")
        if i >= 0 and j > i:
            rows = json.loads(txt[i : j + 1])[-25:]
            return {str(r.get("d", r.get("date", "")))[:10]: float(r.get("c", r.get("close", 0.0))) for r in rows}
    except Exception:
        pass
    return {}


def _fetch_margin_latest_yi() -> Optional[tuple[str, float]]:
    url = (
        "https://datacenter-web.eastmoney.com/api/data/v1/get"
        "?reportName=RPTA_WEB_RZRQ_LSHJ&columns=DIM_DATE,FIN_BALANCE"
        "&pageNumber=1&pageSize=3&sortColumns=DIM_DATE&sortTypes=-1&source=WEB&client=WEB"
    )
    try:
        js = json.loads(_http_get_text(url, timeout=1.5))
        rows = (js.get("result") or {}).get("data") or []
        if rows:
            dt_s = str(rows[0]["DIM_DATE"])[:10]
            bal = float(rows[0]["FIN_BALANCE"]) / 1e8
            return dt_s, bal
    except Exception:
        pass
    return None


def _rolling_pct_last(arr: np.ndarray, win: int = 726, min_p: int = 120) -> float:
    w = arr[-win:]
    w = w[np.isfinite(w)]
    if len(w) < min_p or not np.isfinite(arr[-1]):
        return float("nan")
    return float(np.mean(w <= arr[-1]))


def _compute_daily_adaily_slice(sig_date: str, st_set: set[str], pit_st_tl: Optional[dict] = None) -> pd.DataFrame:
    """Load recent ~140 calendar days of a_daily.parquet with exact rd034/rd035 PIT ST & ZT/DT rules."""
    start_d = datetime.date.fromisoformat(sig_date) - datetime.timedelta(days=140)
    end_d = datetime.date.fromisoformat(sig_date)
    tbl = ds.dataset(f"{DATA_DIR}/cn_hk_price_db/a_daily.parquet", format="parquet").scanner(
        columns=["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "amount", "oshare", "turn"],
        filter=(ds.field("date") >= ds.scalar(start_d)) & (ds.field("date") <= ds.scalar(end_d)),
    ).to_table().to_pandas()
    tbl["dt"] = tbl["date"].dt.strftime("%Y-%m-%d")
    tbl["c6"] = tbl["ticker"].astype(str).str[:6]
    suf = tbl["ticker"].astype(str).str[-3:]
    valid = tbl["c6"].str.startswith(("00", "60", "30", "688", "689")) & suf.isin([".SH", ".SZ"])
    tbl = tbl[valid & (tbl["close"] > 0) & (tbl["adj_close"] > 0)].copy()
    tbl = tbl.sort_values(["ticker", "dt"]).drop_duplicates(["ticker", "dt"]).reset_index(drop=True)

    g = tbl.groupby("ticker", sort=False)
    prev_adj = g["adj_close"].shift(1)
    prev_close_raw = prev_adj * (tbl["close"] / tbl["adj_close"])
    tbl["prev_close_raw"] = prev_close_raw
    tbl["ret"] = tbl["adj_close"] / prev_adj - 1.0
    tbl["oc_ret"] = tbl["close"] / tbl["open"] - 1.0
    tbl["mcap_yi"] = np.where(tbl["oshare"] > 0, tbl["close"] * tbl["oshare"] / 1e8, np.nan)
    tbl["prev_mcap"] = prev_close_raw * g["oshare"].shift(1)
    tbl["amt_med20_s1"] = g["amount"].transform(lambda s: s.rolling(20, min_periods=10).median().shift(1))

    is_20 = tbl["c6"].str.startswith(("30", "688", "689"))
    if pit_st_tl:
        c6_v = tbl["c6"].to_numpy()
        dt_v = tbl["dt"].to_numpy()
        st_v = np.zeros(len(tbl), dtype=bool)
        for i_row in range(len(tbl)):
            tl = pit_st_tl.get(c6_v[i_row])
            if tl:
                pos_st = bisect.bisect_left(tl[0], f"{dt_v[i_row]} 15:00:00")
                if pos_st > 0 and tl[1][pos_st - 1] == 1:
                    st_v[i_row] = True
        is_st = pd.Series(st_v, index=tbl.index)
    else:
        is_st = tbl["c6"].isin(st_set)
    lim = np.where(is_20, 0.20, np.where(is_st & (tbl["dt"] < "2026-07-06"), 0.05, 0.10))
    r_th = np.where(is_20, 0.195, 0.095)
    abn = tbl["ret"].abs() > np.where(is_20, 0.22, 0.12)
    zt_px = np.floor(prev_close_raw * (1.0 + lim) * 100.0 + 0.5) / 100.0
    dt_px = np.floor(prev_close_raw * (1.0 - lim) * 100.0 + 0.5) / 100.0
    vp = prev_close_raw.notna() & (prev_close_raw > 0) & (tbl["volume"].fillna(0.0) > 0)
    raw_zt = vp & (~is_st) & (tbl["close"] >= zt_px - 0.011) & (tbl["ret"] >= r_th) & (~abn)
    raw_dt = vp & (~is_st) & (tbl["close"] <= dt_px + 0.011) & (tbl["ret"] <= -r_th) & (~abn)

    # Exact list_age > 20 guard only for stocks with <= 20 bars in the slice that hit ZT/DT
    bar_rank = g.cumcount() + 1
    short_mask = (raw_zt | raw_dt) & (bar_rank <= 20)
    if short_mask.any():
        short_tkrs = sorted(tbl.loc[short_mask, "ticker"].unique().tolist())
        hist_cnt = ds.dataset(f"{DATA_DIR}/cn_hk_price_db/a_daily.parquet", format="parquet").scanner(
            columns=["date", "ticker"],
            filter=(ds.field("ticker").isin(short_tkrs)) & (ds.field("date") < ds.scalar(start_d)),
        ).to_table().to_pandas()
        pre_cnt = hist_cnt.groupby("ticker").size().to_dict() if not hist_cnt.empty else {}
        true_age = bar_rank + tbl["ticker"].map(pre_cnt).fillna(0).astype(int)
        age_ok = true_age > 20
        raw_zt &= age_ok
        raw_dt &= age_ok

    tbl["is_zt"] = raw_zt
    tbl["is_yizi"] = tbl["is_zt"] & (tbl["open"] >= zt_px - 0.011) & (tbl["low"] >= zt_px - 0.011)
    tbl["is_dt"] = raw_dt
    tbl["is_st"] = is_st
    tbl["is_20"] = is_20 & (~is_st)

    tkr_v = tbl["ticker"].to_numpy()
    zt_v = tbl["is_zt"].to_numpy()
    stk = np.zeros(len(tbl), dtype=np.int16)
    cur_s = 0
    prev_t = ""
    for i in range(len(tbl)):
        tk = tkr_v[i]
        if tk != prev_t:
            cur_s = 0
            prev_t = tk
        cur_s = (cur_s + 1) if zt_v[i] else 0
        stk[i] = cur_s
    tbl["streak"] = stk
    return tbl


def compute_market_t1_features(sig_date: str, buy_date: str, refs: dict, mkt_slice: pd.DataFrame) -> dict[str, float]:
    """Compute exact T-1 market & macro features strictly <= sig_date (or lookup rd35_mkt_tail)."""
    tail_df = refs["rd35_mkt_tail"]
    hit = tail_df[tail_df["trade_date"].astype(str) == buy_date]
    if not hit.empty:
        row = hit.iloc[0].to_dict()
        mf = {k: float(v) if (v is not None and pd.notna(v)) else float("nan") for k, v in row.items() if k != "trade_date"}
        mf["mkt10_zt_est_t1"] = mf["L1_zt_cnt_t1"] - mf["mkt20_zt_cnt_t1"]
        mf["buy_date_weekday"] = float(pd.Timestamp(buy_date).weekday())
        return mf

    # Incremental computation for buy_date > rd35_mkt_max_dt (2026-11-26 .. 2026-12-10)
    dts_sub = sorted(mkt_slice["dt"].unique().tolist())
    dts_le = [d for d in dts_sub if d <= sig_date]
    t1_dt = dts_le[-1] if dts_le else sig_date

    val = mkt_slice[(~mkt_slice["is_st"]) & (mkt_slice["amount"] > 0)].copy()
    d_t1 = val[val["dt"] == t1_dt]
    zt_cnt = float(d_t1["is_zt"].sum())
    nat_zt_cnt = float((d_t1["is_zt"] & (~d_t1["is_yizi"])).sum())
    dt_cnt = float(d_t1["is_dt"].sum())
    zt20_cnt = float((d_t1["is_zt"] & d_t1["is_20"]).sum())
    max_board = float(d_t1["streak"].max()) if len(d_t1) else 0.0
    lb_cnt = float((d_t1["streak"] >= 2).sum())

    # Amt ratio5v60 & 3Y percentiles spliced onto bp_tail
    bp_tail = refs["bp_tail"].copy()
    new_dts = [d for d in dts_le if d > str(bp_tail["dt"].max())]
    amt_by_d = mkt_slice[mkt_slice["amount"] > 0].groupby("dt").agg(
        amt_yi=("amount", lambda s: float(s.sum() / 1e8)),
        tot_fmcap=("mcap_yi", "sum"),
    )
    all_amts = list(bp_tail["total_amount_yi"].to_numpy(float))
    all_turns = list(bp_tail["turn_mkt_weighted"].to_numpy(float))
    for nd in new_dts:
        if nd in amt_by_d.index:
            ay = float(amt_by_d.loc[nd, "amt_yi"])
            fm = float(amt_by_d.loc[nd, "tot_fmcap"])
            all_amts.append(ay)
            all_turns.append((ay / fm) if fm > 0 else np.nan)
    amt_arr = np.asarray(all_amts, dtype=np.float64)
    turn_arr = np.asarray(all_turns, dtype=np.float64)
    amt_r5v60 = float(np.mean(amt_arr[-5:]) / np.mean(amt_arr[-60:])) if len(amt_arr) >= 60 else 1.0
    amt_pct_3y = _rolling_pct_last(amt_arr, 726, 120)
    turn_pct_3y = _rolling_pct_last(turn_arr, 726, 120)

    # SMB 20d
    vr = val[(val["prev_mcap"] > 0) & val["ret"].notna() & (val["ret"].abs() <= 0.22)].copy()
    vr["mc_pct"] = vr.groupby("dt")["prev_mcap"].rank(pct=True)
    sm_r = vr[vr["mc_pct"] <= 0.20].groupby("dt")["ret"].mean().reindex(dts_le).fillna(0.0)
    bg_r = vr[vr["mc_pct"] >= 0.90].groupby("dt")["ret"].mean().reindex(dts_le).fillna(0.0)
    sm_idx = (1.0 + sm_r).cumprod()
    bg_idx = (1.0 + bg_r).cumprod()
    smb_20d = float(((sm_idx.iloc[-1] / sm_idx.iloc[-21] - 1.0) - (bg_idx.iloc[-1] / bg_idx.iloc[-21] - 1.0)) * 100.0) if len(sm_idx) >= 21 else 0.0

    # NT Big4+Oil & Fund8 dump
    b4o_set = {"601398.SH", "601288.SH", "601988.SH", "601939.SH", "601857.SH", "600028.SH"}
    f8_set = {"300750.SZ", "300308.SZ", "300274.SZ", "688256.SZ", "300059.SZ", "002475.SZ", "603259.SZ", "000858.SZ"}
    b4o_df = mkt_slice[(mkt_slice["dt"] == t1_dt) & (mkt_slice["ticker"].isin(b4o_set))]
    nt_b4o = float(b4o_df["ret"].mean() * 100.0) if len(b4o_df) else 0.0
    f8_df = mkt_slice[(mkt_slice["dt"] == t1_dt) & (mkt_slice["ticker"].isin(f8_set))].copy()
    f8_spk = f8_df["amount"] / f8_df["amt_med20_s1"].replace(0, np.nan)
    nt_f8_dump = float(((f8_df["oc_ret"] <= -0.020) & (f8_spk >= 1.2)).sum()) if len(f8_df) else 0.0

    # Parallel lightweight HTTP fetches (VIX, Futures, Indexes, Margin)
    with ThreadPoolExecutor(max_workers=6) as ex:
        f_vix_fut = ex.submit(_fetch_sina_vix_and_fut)
        f_c300 = ex.submit(_fetch_sina_idx_klines, "sh000300", 35)
        f_bank = ex.submit(_fetch_sina_idx_klines, "sz399986", 10)
        f_tmt = ex.submit(_fetch_sina_idx_klines, "sh000993", 10)
        f_rb = ex.submit(_fetch_fut_daily_sina, "RB0")
        f_al = ex.submit(_fetch_fut_daily_sina, "AL0")
        f_mrg = ex.submit(_fetch_margin_latest_yi)
        vf = f_vix_fut.result()
        k_c300 = f_c300.result()
        k_bank = f_bank.result()
        k_tmt = f_tmt.result()
        k_rb = f_rb.result()
        k_al = f_al.result()
        mrg_res = f_mrg.result()

    # 40m cycle cos/sin
    cal25 = refs["full_cal_to_25"]
    extra_td = len([d for d in dts_le if d > cal25[-1]])
    idx_t1 = len(cal25) + extra_td - 1
    anc = int(refs["anchor_2008_11_04_pos"])
    cyc_sin = float(math.sin(2.0 * math.pi * (idx_t1 - anc) / 820.0))
    cyc_cos = float(math.cos(2.0 * math.pi * (idx_t1 - anc) / 820.0))

    # Index MA20 & Bank vs TMT
    dmp_t = refs["dmp_tail"]
    c3_map = {str(r["dt"]): float(r["csi300_close"]) for _, r in dmp_t.iterrows() if pd.notna(r["csi300_close"])}
    c3_map.update({k: v for k, v in k_c300.items() if k <= t1_dt})
    c3_vals = [c3_map[k] for k in sorted(c3_map.keys()) if k <= t1_dt]
    csi_ma20_dist = float((c3_vals[-1] / np.mean(c3_vals[-20:]) - 1.0) * 100.0) if len(c3_vals) >= 20 else 0.0

    bk_map = {str(r["dt"]): float(r["bank_idx_close"]) for _, r in dmp_t.iterrows() if pd.notna(r["bank_idx_close"])}
    bk_map.update({k: v for k, v in k_bank.items() if k <= t1_dt})
    tm_map = {str(r["dt"]): float(r["tmt_info_close"]) for _, r in dmp_t.iterrows() if pd.notna(r["tmt_info_close"])}
    tm_map.update({k: v for k, v in k_tmt.items() if k <= t1_dt})
    bk_s = [bk_map[k] for k in sorted(bk_map.keys()) if k <= t1_dt]
    tm_s = [tm_map[k] for k in sorted(tm_map.keys()) if k <= t1_dt]
    bk_r = (bk_s[-1] / bk_s[-2] - 1.0) if len(bk_s) >= 2 else 0.0
    tm_r = (tm_s[-1] / tm_s[-2] - 1.0) if len(tm_s) >= 2 else 0.0
    bank_vs_tech = float((bk_r - tm_r) * 100.0)

    # US VIX (< buy_date CST)
    vx_map = {str(k)[:10]: float(v) for k, v in refs["vx_tail"].items() if str(k)[:10] < buy_date}
    if "vix" in vf and vf["vix"][0] <= buy_date and vf["vix"][1] > 0:
        vx_map[vf["vix"][0]] = vf["vix"][1]
    vix_lvl = float(vx_map[max(vx_map.keys())]) if vx_map else 20.0

    # Futures 5d returns (< buy_date)
    def _fut_5d(base_dict: dict, live_key: str, sina_daily: Optional[dict] = None) -> float:
        m = {str(k)[:10]: float(v) for k, v in base_dict.items() if str(k)[:10] < buy_date and pd.notna(v)}
        if sina_daily:
            for d, v in sina_daily.items():
                if d < buy_date and v > 0:
                    m[d] = v
        if live_key in vf:
            d_lv, p_lv = vf[live_key][0], vf[live_key][1]
            if d_lv < buy_date and p_lv > 0:
                m[d_lv] = p_lv
        ks = sorted(m.keys())
        if len(ks) >= 6 and m[ks[-6]] > 0:
            return float((m[ks[-1]] / m[ks[-6]] - 1.0) * 100.0)
        return 0.0

    cf_t, gf_t = refs["cf_tail"], refs["gf_tail"]
    rb_r5 = _fut_5d(cf_t.get("RB0", {}), "RB0", k_rb)
    al_r5 = _fut_5d(cf_t.get("AL0", {}), "AL0", k_al)
    au_r5 = _fut_5d(gf_t.get("GC_F", {}), "GC_F", None)
    cu_r5 = _fut_5d(gf_t.get("HG_F", {}), "HG_F", None)

    # NT V3 live T-1 score from latest_monitor_snapshot.json (or rd035 last value)
    nt_v3_live = float(tail_df["nt_v3_score_live_t1"].iloc[-1])
    nt_snap_p = f"{ROOT}/output/csrc_policy_100factors_20261114/national_team/latest_monitor_snapshot.json"
    if os.path.exists(nt_snap_p):
        try:
            nt_js = json.load(open(nt_snap_p, encoding="utf-8"))
            v3_rs = nt_js.get("v3_rescue_score") or {}
            # In EOD settled snapshot, base + D5 + D1_5d + D2 + D3 + D4_f8_lag match live_score logic
            if str(v3_rs.get("settled_date", "")) == t1_dt:
                # Recompute exact v3_score_live (excluding EOD net flow items)
                eod_items = (v3_rs.get("settled_eod_score") or {}).get("items") or []
                if eod_items:
                    # Wait: D1_宽基ETF池 contains both spike (+pts) and EOD net flow (+12/+7/+6/-5/-12)
                    # Simply subtract net-flow-only EOD tags to keep strict v3_score_live scale!
                    eod_only_labels = {"大额净申购", "中额净申购", "一二队同步", "只托50/300", "大额净赎回", "5日净赎回", "救市退出", "尾盘", "证券+龙虎"}
                    sc_adj = sum(
                        int(it.get("pts", 0)) for it in eod_items
                        if not any(lbl in str(it.get("label", "")) for lbl in eod_only_labels)
                    )
                    nt_v3_live = float(max(0, min(100, sc_adj)))
        except Exception:
            pass

    # Margin / Total float mcap
    tot_fmcap = float(amt_by_d.loc[t1_dt, "tot_fmcap"]) if t1_dt in amt_by_d.index else 800000.0
    mrg_bal = float(bp_tail["margin_balance_yi"].dropna().iloc[-1])
    if mrg_res and mrg_res[0] <= t1_dt:
        mrg_bal = mrg_res[1]
    mkt_margin = float(mrg_bal / tot_fmcap * 100.0) if tot_fmcap > 0 else 2.5

    # Policy crackdown 10d
    crack_map = refs["crack_by_dt"]
    last10_dts = (cal25 + new_dts)[-10:]
    pol_crack = float(sum(crack_map.get(d, 0.0) for d in last10_dts))

    return {
        "t1_dt": t1_dt,
        "L1_zt_cnt_t1": zt_cnt,
        "L1_nat_zt_cnt_t1": nat_zt_cnt,
        "L1_dt_cnt_t1": dt_cnt,
        "mkt20_zt_cnt_t1": zt20_cnt,
        "mkt10_zt_est_t1": zt_cnt - zt20_cnt,
        "L1_max_board_t1": max_board,
        "L1_lianban_cnt_t1": lb_cnt,
        "L1_amt_ratio5v60_t1": amt_r5v60,
        "L1_smb_20d_t1": smb_20d,
        "mkt_amt_pct_3y_t1": amt_pct_3y,
        "mkt_turn_pct_3y_t1": turn_pct_3y,
        "mkt_margin_to_float_pct_t1": mkt_margin,
        "mkt_bank_vs_tech_ret_t1": bank_vs_tech,
        "th_tech_csi300_ma20_dist_t1": csi_ma20_dist,
        "th_macro_40m_cycle_sin_t1": cyc_sin,
        "th_macro_40m_cycle_cos_t1": cyc_cos,
        "us_vix_level_on": vix_lvl,
        "comm_rb_ret5d_t1": rb_r5,
        "comm_al_ret5d_t1": al_r5,
        "comm_au_ret5d_t1": au_r5,
        "comm_cu_ret5d_t1": cu_r5,
        "nt_v3_score_live_t1": nt_v3_live,
        "nt_big4_oil_ret_t1": nt_b4o,
        "nt_fund8_dump_cnt_t1": nt_f8_dump,
        "pol_crackdown_signal_10d": pol_crack,
        "buy_date_weekday": float(pd.Timestamp(buy_date).weekday()),
    }


def _fetch_yahoo_chart_daily(symbol_enc: str) -> dict[str, float]:
    """Pure urllib Yahoo v8 daily close map (zero yfinance import, used once/day in T-1 cache)."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol_enc}?range=1mo&interval=1d"
    try:
        js = json.loads(_http_get_text(url, timeout=2.0))
        res = js["chart"]["result"][0]
        ts = res["timestamp"]
        cl = res["indicators"]["quote"][0]["close"]
        out = {}
        for t_u, c_v in zip(ts, cl):
            if c_v is not None and np.isfinite(float(c_v)):
                dt_s = datetime.datetime.fromtimestamp(int(t_u), tz=datetime.timezone.utc).strftime("%Y-%m-%d")
                out[dt_s] = float(c_v)
        return out
    except Exception:
        return {}


def _load_cand_full_bars(cand_codes: list[str], sig_date: str) -> dict[str, pd.DataFrame]:
    """Load full history for <=30 candidate codes from a_daily + a_delisted (<=0.05s)."""
    if not cand_codes:
        return {}
    tkrs = [(f"{c}.SH" if c.startswith("6") else f"{c}.SZ") for c in sorted(set(cand_codes))]
    end_d = datetime.date.fromisoformat(sig_date)
    parts = []
    for p in (f"{DATA_DIR}/cn_hk_price_db/a_daily.parquet", f"{DATA_DIR}/cn_hk_price_db/a_delisted_daily.parquet"):
        if not os.path.exists(p):
            continue
        t = ds.dataset(p, format="parquet").scanner(
            columns=["date", "ticker", "open", "high", "low", "close", "adj_close", "amount", "oshare", "turn"],
            filter=(ds.field("ticker").isin(tkrs)) & (ds.field("date") <= ds.scalar(end_d)),
        ).to_table().to_pandas()
        if not t.empty:
            parts.append(t)
    if not parts:
        return {}
    df = pd.concat(parts, ignore_index=True)
    df["dt"] = df["date"].dt.strftime("%Y-%m-%d")
    df["c6"] = df["ticker"].astype(str).str[:6]
    df = df[df["close"] > 0].sort_values(["c6", "dt"]).drop_duplicates(["c6", "dt"]).reset_index(drop=True)
    return {ck: g.reset_index(drop=True) for ck, g in df.groupby("c6", sort=False)}


def compute_stocks_t1_features(
    cand_codes: list[str],
    sig_date: str,
    buy_date: str,
    refs: dict,
    mkt_slice: pd.DataFrame,
    st_set: set[str],
    pre_lock_map: dict[str, float],
) -> dict[str, dict[str, Any]]:
    """Compute exact L3_*, oh_*, sd_*, L2_*, w24_* T-1/pre-0925 features strictly <= sig_date."""
    cands = sorted(set(str(c).zfill(6) for c in cand_codes if c))
    if not cands:
        return {}

    bars_map = _load_cand_full_bars(cands, sig_date)
    cal_sub = sorted([d for d in mkt_slice["dt"].unique() if d <= sig_date])
    cal_full = sorted(set(refs["full_cal_to_25"]) | set(cal_sub))
    cal_idx = {d: i for i, d in enumerate(cal_full)}
    m_t = cal_idx.get(buy_date, len(cal_full))

    # Cross-sectional T-1 mcap & real free mcap percentiles on sig_date
    d_t1 = mkt_slice[(mkt_slice["dt"] == sig_date) & (~mkt_slice["is_st"]) & (mkt_slice["amount"] > 0)].copy()
    mcap_pct_map = {}
    if not d_t1.empty:
        d_t1["mc_pct"] = d_t1["mcap_yi"].rank(pct=True)
        mcap_pct_map = dict(zip(d_t1["c6"], d_t1["mc_pct"]))
    # Estimate cross-sectional rfm pct using mcap*(1 - 0.35 fallback) when exact lock unavailable market-wide
    # Note: rd25_rfm_pct_all_t1 exact fallback vs stock_day_core_features_pit when <= 2026-11-25
    rfm_pct_map = {}
    sd_core_p = f"{RD035_BASE}/wave1_base/stock_day_core_features_pit.parquet"
    if os.path.exists(sd_core_p):
        try:
            sd_sub = ds.dataset(sd_core_p, format="parquet").scanner(
                columns=["c6", "dt", "free_mcap_yi_t1"],
                filter=(ds.field("dt") == buy_date),
            ).to_table().to_pandas()
            if not sd_sub.empty:
                sd_sub["rfm_pct"] = sd_sub["free_mcap_yi_t1"].rank(pct=True)
                rfm_pct_map = dict(zip(sd_sub["c6"].astype(str), sd_sub["rfm_pct"]))
        except Exception:
            pass
    if not rfm_pct_map and not d_t1.empty:
        # Approximate rfm cross-section cleanly from mcap_yi (or pre_lock for cands)
        rfm_s = d_t1["mcap_yi"] * (1.0 - 0.35)
        for c6_k, lp_v in pre_lock_map.items():
            rfm_s = rfm_s.where(d_t1["c6"] != c6_k, d_t1["mcap_yi"] * (1.0 - float(lp_v) / 100.0))
        d_t1["rfm_pct"] = rfm_s.rank(pct=True)
        rfm_pct_map = dict(zip(d_t1["c6"], d_t1["rfm_pct"]))

    # Industry 5d ZT share
    csrc_map = refs["csrc_latest"]
    d5_dts = cal_sub[-5:]
    d5_df = mkt_slice[(mkt_slice["dt"].isin(d5_dts)) & (~mkt_slice["is_st"]) & (mkt_slice["amount"] > 0)].copy()
    d5_df["ind"] = d5_df["c6"].map(csrc_map)
    ind_zt5 = d5_df[d5_df["ind"].notna()].groupby("ind")["is_zt"].sum().to_dict()
    tot_zt5 = max(1.0, float(d5_df["is_zt"].sum()))

    # KPL plates tail (last ~70 trading days up to sig_date) -> streak & candidate core plate + peers
    kpl_p = f"{DATA_DIR}/kpl_plates_2018_2026_merged.jsonl"
    kpl_cut_dt = cal_sub[-min(len(cal_sub), 75)] if cal_sub else "2026-01-01"
    plate_cnt_by_dt: dict[str, dict[str, int]] = {}
    plate_stocks_on_sig: dict[str, list[str]] = {}
    stock_last_plate: dict[str, tuple[str, int, str]] = {}
    if os.path.exists(kpl_p):
        with open(kpl_p, encoding="utf-8") as f:
            for ln in f:
                if not ln.strip():
                    continue
                obj = json.loads(ln)
                dt_s = str(obj.get("date", ""))[:10]
                if dt_s < kpl_cut_dt or dt_s > sig_date:
                    continue
                for pl in obj.get("plates", []):
                    pname = str(pl.get("plate", "")).strip()
                    if pname in ("其他", "无", "", "ST板块"):
                        continue
                    sts = pl.get("stocks", [])
                    psz = len(sts)
                    if psz == 0:
                        continue
                    plate_cnt_by_dt.setdefault(pname, {})[dt_s] = plate_cnt_by_dt.get(pname, {}).get(dt_s, 0) + psz
                    if dt_s == sig_date:
                        plate_stocks_on_sig[pname] = [str(st[0]).strip().zfill(6) for st in sts]
                    for st in sts:
                        c6_s = str(st[0]).strip().zfill(6)
                        if c6_s in cands:
                            prev = stock_last_plate.get(c6_s)
                            if (prev is None) or (dt_s > prev[0]) or (dt_s == prev[0] and psz > prev[1]):
                                stock_last_plate[c6_s] = (dt_s, psz, pname)

    kpl_streak_by_plate = {}
    for pname, dt_map in plate_cnt_by_dt.items():
        cur_s = 0
        for d in cal_sub:
            if dt_map.get(d, 0) >= 3:
                cur_s += 1
            else:
                cur_s = 0
        kpl_streak_by_plate[pname] = float(cur_s)

    # ZT micro tape seal amount on sig_date
    seal_yi_map: dict[str, float] = {}
    zt_db = f"{DATA_DIR}/zt_micro_tape_5y_pit.db"
    if os.path.exists(zt_db):
        try:
            c_sql = ",".join(f"'{c}'" for c in cands)
            con = sqlite3.connect(f"file:{zt_db}?mode=ro", uri=True)
            rows = con.execute(
                f"SELECT sec_code, seal_amount FROM zt_micro_tape WHERE trade_date=? AND sec_code IN ({c_sql})",
                (sig_date,),
            ).fetchall()
            con.close()
            for sc, sa in rows:
                seal_yi_map[str(sc).zfill(6)] = float(sa or 0.0) / 1e8
        except Exception:
            pass

    # LHB T-1 on sig_date (exact rd016 canonical TRADE_ID + side deduplication)
    lhb_on_map, lhb_inst_map = {}, {}
    lb_p = f"{SIM_DIR}/backtest/2026-10-20-lhasa/lhb_buy.parquet"
    ls_p = f"{SIM_DIR}/backtest/2026-10-20-lhasa/lhb_sell.parquet"
    if os.path.exists(lb_p) and os.path.exists(ls_p):
        try:
            lb = pd.read_parquet(lb_p)
            ls = pd.read_parquet(ls_p)
            lb_s = lb[(lb["TRADE_DATE"].astype(str).str[:10] == sig_date) & (lb["SECURITY_CODE"].astype(str).str.zfill(6).isin(cands))].copy()
            ls_s = ls[(ls["TRADE_DATE"].astype(str).str[:10] == sig_date) & (ls["SECURITY_CODE"].astype(str).str.zfill(6).isin(cands))].copy()
            lb_s["side"] = "B"
            ls_s["side"] = "S"
            raw_lhb = pd.concat([lb_s, ls_s], ignore_index=True)
            if not raw_lhb.empty:
                raw_lhb["c6"] = raw_lhb["SECURITY_CODE"].astype(str).str.zfill(6)
                raw_lhb["is_three"] = raw_lhb["EXPLANATION"].astype(str).str.contains("三个交易日|3个交易日").astype(int)
                canon = raw_lhb.groupby(["c6", "is_three"], as_index=False)["TRADE_ID"].min()
                raw_lhb = raw_lhb.merge(canon, on=["c6", "is_three", "TRADE_ID"], how="inner")
                raw_lhb["dept_code"] = raw_lhb["OPERATEDEPT_CODE"].astype(str).str.strip()
                raw_lhb["dept_name"] = raw_lhb["OPERATEDEPT_NAME"].astype(str).str.strip()
                non_org = raw_lhb[raw_lhb["dept_code"] != "0"].drop_duplicates(["c6", "is_three", "dept_code", "BUY", "SELL"])
                non_org = non_org.drop_duplicates(["c6", "is_three", "dept_code"])
                org = raw_lhb[raw_lhb["dept_code"] == "0"].drop_duplicates(["c6", "is_three", "side", "BUY", "SELL"])
                clean_lhb = pd.concat([non_org, org], ignore_index=True)
                clean_lhb["is_inst"] = clean_lhb["dept_name"].str.contains("机构", na=False) | clean_lhb["dept_code"].isin(["0", "99999"])
                seat_lhb = clean_lhb.groupby(["c6", "dept_code"], as_index=False).agg(NET=("NET", "mean"), is_inst=("is_inst", "max"))
                for ck, grp in seat_lhb.groupby("c6"):
                    lhb_on_map[ck] = 1.0
                    inst_v = grp.loc[grp["is_inst"], "NET"].sum() / 1e8
                    lhb_inst_map[ck] = float(inst_v)
        except Exception:
            pass

    # Community (XQ 1d/3d/1y & comm_active_month_ratio_1y) strictly < buy_date 09:25:00
    xq_3d_map = {c: 0.0 for c in cands}
    xq_1y_map = {c: 0.0 for c in cands}
    actm_1y_map = {c: 0.0 for c in cands}
    c_sql = ",".join(f"'{c}'" for c in cands)
    cal_t6_ym = cal_full[max(0, m_t - 6)][:7] if cal_full else buy_date[:7]
    ym_y, ym_m = int(cal_t6_ym[:4]), int(cal_t6_ym[5:7])
    ym_list = []
    for k in range(12):
        mm0 = (ym_m - 1) - (k + 1)
        yy = ym_y + (mm0 // 12)
        mm_mod = (mm0 % 12) + 1
        ym_list.append(f"{yy:04d}-{mm_mod:02d}")
    ym_set = set(ym_list)

    def _eff_idx(dt_s: str, hm_s: str) -> int:
        pos = bisect.bisect_left(cal_full, dt_s)
        if pos < len(cal_full) and cal_full[pos] == dt_s and hm_s >= "09:25:00":
            return pos + 1
        return pos

    xq_events: dict[str, list[int]] = {c: [] for c in cands}
    comm_ym_cnt: dict[str, dict[str, int]] = {c: {} for c in cands}
    seen_pids: dict[str, set[str]] = {c: set() for c in cands}
    db1 = f"{DATA_DIR}/xueqiu_guba_5y_pit.db"
    db2 = f"{DATA_DIR}/astock_community_5y_pit.db"
    cut_1y_dt = cal_full[max(0, m_t - 260)] if cal_full else "2025-01-01"
    cut_14m = min(ym_list) + "-01"
    if os.path.exists(db1):
        try:
            con = sqlite3.connect(f"file:{db1}?mode=ro", uri=True)
            for pid, c6_r, ts_r in con.execute(
                f"SELECT CAST(post_id AS TEXT), symbol, created_time_str FROM xueqiu_posts "
                f"WHERE symbol IN ({c_sql}) AND created_time_str >= ? AND substr(created_time_str,1,10) <= ?",
                (cut_14m, buy_date),
            ).fetchall():
                c6_k = str(c6_r).zfill(6)
                if pid in seen_pids[c6_k]:
                    continue
                seen_pids[c6_k].add(pid)
                dt_s, hm_s = str(ts_r)[:10], str(ts_r)[11:19]
                eff = _eff_idx(dt_s, hm_s)
                if eff <= m_t:
                    xq_events[c6_k].append(eff)
                    if dt_s[:7] in ym_set:
                        comm_ym_cnt[c6_k][dt_s[:7]] = comm_ym_cnt[c6_k].get(dt_s[:7], 0) + 1
            for c6_r, dt_s, cnt in con.execute(
                f"SELECT sec_code, substr(pub_time,1,10), COUNT(*) FROM guba_posts "
                f"WHERE sec_code IN ({c_sql}) AND pub_time >= ? AND substr(pub_time,1,10) < ? "
                f"GROUP BY sec_code, substr(pub_time,1,10)",
                (cut_14m, cal_t6_ym + "-01"),
            ).fetchall():
                c6_k = str(c6_r).zfill(6)
                if dt_s[:7] in ym_set:
                    comm_ym_cnt[c6_k][dt_s[:7]] = comm_ym_cnt[c6_k].get(dt_s[:7], 0) + int(cnt)
            con.close()
        except Exception:
            pass
    if os.path.exists(db2):
        try:
            con = sqlite3.connect(f"file:{db2}?mode=ro", uri=True)
            for pid, src, c6_r, ts_r in con.execute(
                f"SELECT CAST(post_id AS TEXT), source, symbol, pub_datetime_cst FROM community_posts "
                f"WHERE symbol IN ({c_sql}) AND pub_datetime_cst >= ? AND substr(pub_datetime_cst,1,10) <= ?",
                (cut_14m, buy_date),
            ).fetchall():
                c6_k = str(c6_r).zfill(6)
                dt_s, hm_s = str(ts_r)[:10], str(ts_r)[11:19]
                eff = _eff_idx(dt_s, hm_s)
                if src == "xueqiu":
                    if pid not in seen_pids[c6_k] and eff <= m_t:
                        seen_pids[c6_k].add(pid)
                        xq_events[c6_k].append(eff)
                if dt_s[:7] in ym_set:
                    comm_ym_cnt[c6_k][dt_s[:7]] = comm_ym_cnt[c6_k].get(dt_s[:7], 0) + 1
            con.close()
        except Exception:
            pass
    for c6_k in cands:
        ev = sorted(xq_events[c6_k])
        if ev:
            arr_e = np.asarray(ev, dtype=np.int32)
            r = int(np.searchsorted(arr_e, m_t, side="right"))
            l3 = int(np.searchsorted(arr_e, m_t - 2, side="left"))
            l1y = int(np.searchsorted(arr_e, m_t - 242, side="left"))
            r1y = int(np.searchsorted(arr_e, m_t - 5, side="left"))
            xq_3d_map[c6_k] = float(r - l3)
            xq_1y_map[c6_k] = float(max(0, r1y - l1y))
        actm_1y_map[c6_k] = float(
            sum(1 for ym_i in ym_list if comm_ym_cnt[c6_k].get(ym_i, 0) > (1 if ym_i >= "2026-06" else 0)) / 12.0
        )

    out: dict[str, dict[str, Any]] = {}
    for c6_k in cands:
        g = bars_map.get(c6_k)
        if g is None or g.empty:
            out[c6_k] = {}
            continue
        ac = g["adj_close"].to_numpy(float)
        cl = g["close"].to_numpy(float)
        sc = ac / cl
        ah = g["high"].to_numpy(float) * sc
        al = g["low"].to_numpy(float) * sc
        trn = pd.to_numeric(g["turn"], errors="coerce").fillna(0.0).to_numpy(float)
        amt = g["amount"].to_numpy(float)
        osh = g["oshare"].to_numpy(float)
        dts_g = g["dt"].tolist()
        mkt_g = [cal_idx.get(d, bisect.bisect_left(cal_full, d)) for d in dts_g]

        n_b = len(g)
        c_t1 = ac[-1]
        p1_lo = bisect.bisect_left(mkt_g, m_t - 250)
        win_al = al[p1_lo:] if p1_lo < n_b else al
        win_ah = ah[p1_lo:] if p1_lo < n_b else ah
        min250 = float(np.nanmin(win_al))
        max250 = float(np.nanmax(win_ah))
        off_low_250 = float((c_t1 / min250 - 1.0) * 100.0) if min250 > 0 else np.nan
        pos_250 = float(np.clip((c_t1 - min250) / (max250 - min250), 0.0, 1.0)) if max250 > min250 else np.nan
        dd_1y = float(c_t1 / max250 - 1.0) if max250 > 0 else np.nan
        ma60 = float(np.mean(ac[-60:])) if n_b >= 40 else np.nan
        bias60 = float((c_t1 / ma60 - 1.0) * 100.0) if (np.isfinite(ma60) and ma60 > 0) else np.nan
        cum_t20 = float(np.sum(trn[-20:]) * 100.0) if n_b >= 20 else np.nan
        t5 = float(np.mean(trn[-5:])) if n_b >= 5 else np.nan
        t20 = float(np.mean(trn[-20:])) if n_b >= 20 else np.nan
        t520 = float(t5 / t20) if (np.isfinite(t5) and np.isfinite(t20) and t20 > 0) else np.nan

        # ZT bars & active-wave cutoff (exact rd028 lines 508-521)
        is_20_s = c6_k.startswith(("30", "688", "689"))
        pit_tl_ref = refs.get("pit_st_tl")
        lim_s = 0.20 if is_20_s else 0.10
        zt_b = []
        for idx_i in range(1, n_b):
            if _is_pit_st(pit_tl_ref, c6_k, dts_g[idx_i], st_set):
                continue
            prev_raw = ac[idx_i - 1] * (cl[idx_i] / ac[idx_i])
            zp = round(prev_raw * (1.0 + lim_s), 2)
            if cl[idx_i] >= zp - 1e-4 and g["high"].iloc[idx_i] >= cl[idx_i] - 1e-4:
                zt_b.append(idx_i)
        if zt_b and (n_b - zt_b[-1]) <= 5:
            ws = len(zt_b) - 1
            while ws > 0 and (zt_b[ws] - zt_b[ws - 1]) <= 5:
                ws -= 1
            cutoff_bar = zt_b[ws] - 1
            z_end_ex = ws
        else:
            cutoff_bar = n_b - 1
            z_end_ex = len(zt_b)

        turn_pref = np.concatenate(([0.0], np.cumsum(trn)))
        oh_turn1y = float("nan")
        if cutoff_bar >= 0:
            b1_lo = bisect.bisect_left(mkt_g, m_t - 250, 0, cutoff_bar + 1)
            if cutoff_bar + 1 > b1_lo:
                oh_turn1y = float(turn_pref[cutoff_bar + 1] - turn_pref[b1_lo])
        cool_zt = float(m_t - mkt_g[zt_b[z_end_ex - 1]]) if z_end_ex > 0 else -1.0

        prev_c_raw = float(cl[-1])
        mcap_yi = float(cl[-1] * osh[-1] / 1e8) if osh[-1] > 0 else np.nan
        amt_yi_t1 = float(amt[-1] / 1e8)
        lp_v = pre_lock_map.get(c6_k, 35.0)
        fmcap_yi = float(mcap_yi * (1.0 - lp_v / 100.0)) if np.isfinite(mcap_yi) else np.nan
        seal_ratio = float(seal_yi_map.get(c6_k, 0.0) / amt_yi_t1) if amt_yi_t1 > 0 else 0.0

        ind_nm = csrc_map.get(c6_k)
        ind_zt_sh5 = float(ind_zt5.get(ind_nm, 0.0) / tot_zt5 * 100.0) if ind_nm else 0.0

        lp_info = stock_last_plate.get(c6_k)
        core_plate = lp_info[2] if lp_info else None
        kpl_stk = float(kpl_streak_by_plate.get(core_plate, 0.0)) if core_plate else 0.0
        peers_10 = [pc for pc in plate_stocks_on_sig.get(core_plate, []) if not pc.startswith(("30", "688", "689"))] if core_plate else []
        if not peers_10 and ind_nm:
            peers_10 = [pc for pc in d_t1.loc[d_t1["c6"].map(csrc_map) == ind_nm, "c6"].tolist() if not pc.startswith(("30", "688", "689")) and d_t1.loc[d_t1["c6"] == pc, "is_zt"].any()]

        out[c6_k] = {
            "L3_off_low_250d_t1": off_low_250,
            "L3_pos_250d_t1": pos_250,
            "L3_bias60_t1": bias60,
            "L3_cum_turn20_t1": cum_t20,
            "L3_mcap_pct_t1": float(mcap_pct_map.get(c6_k, np.nan)),
            "rd25_rfm_pct_all_t1": float(rfm_pct_map.get(c6_k, np.nan)),
            "oh_dd_from_1y_high": dd_1y,
            "oh_cum_turnover_1y": oh_turn1y,
            "oh_list_age": float(n_b),
            "oh_cool_days_since_last_zt": cool_zt,
            "oh_comm_active_month_ratio_1y": actm_1y_map[c6_k],
            "sd_prev_close_raw": prev_c_raw,
            "sd_mcap_yi_t1": mcap_yi,
            "sd_free_mcap_yi_t1": fmcap_yi,
            "xtr_fmcap_le25": 1.0 if (np.isfinite(fmcap_yi) and fmcap_yi <= 25.0) else 0.0,
            "sd_turn_5_20_t1": t520,
            "sd_d1_seal_ratio_t1": seal_ratio,
            "sd_lhb_on_t1": float(lhb_on_map.get(c6_k, 0.0)),
            "sd_lhb_inst_net_yi_t1": float(lhb_inst_map.get(c6_k, 0.0)),
            "sd_comm_ring_tier": float(refs["stock_ring"].get(c6_k, 0.0)),
            "L2_ind_zt_share5_t1": ind_zt_sh5,
            "L2_kpl_streak_t1": kpl_stk,
            "w24_xq_3d_pre": xq_3d_map[c6_k],
            "w24_xq_1y_pre": xq_1y_map[c6_k],
            "_peers_10_on_sig": peers_10[:60],
        }
    return out


def enrich_live_and_ix_features(
    mkt_f: dict[str, float],
    stk_f: dict[str, Any],
    open_pct: Optional[float],
    auc_thm10_yizi: Optional[float],
) -> dict[str, float]:
    """Combine market T-1, stock T-1, and optional 09:25 open into full active feature dict."""
    r = {**mkt_f, **{k: v for k, v in stk_f.items() if not str(k).startswith("_")}}
    zt_cnt = float(r.get("L1_zt_cnt_t1", 50.0))
    r["xtr_mkt_zt_warm_35_85"] = 1.0 if (35.0 <= zt_cnt <= 85.0) else 0.0

    # Static mechanism interactions
    mkt_margin = float(r.get("mkt_margin_to_float_pct_t1", 2.0))
    amt_r5v60 = float(r.get("L1_amt_ratio5v60_t1", 1.0))
    mkt_turn_pct = float(r.get("mkt_turn_pct_3y_t1", 0.5))
    rfm_pct = float(r.get("rd25_rfm_pct_all_t1", np.nan))
    ind_zt_sh5 = float(r.get("L2_ind_zt_share5_t1", 0.0))
    fund8_dump = float(r.get("nt_fund8_dump_cnt_t1", 0.0))
    pos250 = float(r.get("L3_pos_250d_t1", np.nan))
    turn20 = float(r.get("L3_cum_turn20_t1", np.nan))
    dd1y = float(r.get("oh_dd_from_1y_high", np.nan))
    comm_ring = float(r.get("sd_comm_ring_tier", 0.0))
    comm_cyc = float(r.get("comm_cu_ret5d_t1", 0.0)) + float(r.get("comm_au_ret5d_t1", 0.0)) + float(r.get("comm_al_ret5d_t1", 0.0))
    xq_3d = float(r.get("w24_xq_3d_pre", 0.0))
    xq_1y = float(r.get("w24_xq_1y_pre", 0.0))
    xq_1y_daily = xq_1y / 237.0

    r["ix_margin_x_climax"] = mkt_margin * (1.0 if zt_cnt >= 80.0 else 0.0)
    r["ix_amt_r5v60_x_turnpct"] = amt_r5v60 * mkt_turn_pct
    r["ix_small_fmcap_x_ind_zt"] = (1.0 - rfm_pct) * ind_zt_sh5 if np.isfinite(rfm_pct) else np.nan
    r["ix_fund8_dump_x_pos250"] = fund8_dump * pos250 if np.isfinite(pos250) else np.nan
    r["ix_turn20_x_dd1y"] = (math.log1p(max(turn20, 0.0)) * max(0.0, -dd1y)) if (np.isfinite(turn20) and np.isfinite(dd1y)) else np.nan
    r["ix_comm_ring_x_cyc"] = comm_ring * float(np.sign(comm_cyc))
    r["ix_xq_burst_3d_vs_1y"] = (xq_3d + 0.1) / (xq_1y_daily * 3.0 + 0.5)
    r["ix_monday_fix"] = 1.0 if r.get("buy_date_weekday", 1.0) == 0.0 else 0.0

    if open_pct is not None and np.isfinite(open_pct):
        op_pct_100 = float(open_pct) * 100.0
        csi_ma20_dist = float(r.get("th_tech_csi300_ma20_dist_t1", 0.0))
        smb20 = float(r.get("L1_smb_20d_t1", 0.0))
        r["open_pct"] = float(open_pct)
        r["ix_open_per_zt_heat"] = op_pct_100 / (zt_cnt / 60.0 + 0.5)
        r["ix_csima_x_smb20_x_open"] = float(np.sign(csi_ma20_dist)) * smb20 * op_pct_100
    else:
        r["ix_open_per_zt_heat"] = np.nan
        r["ix_csima_x_smb20_x_open"] = np.nan

    r["auc_thm10_has_yizi_open"] = float(auc_thm10_yizi) if (auc_thm10_yizi is not None and np.isfinite(auc_thm10_yizi)) else np.nan
    return r


def build_or_load_t1_cache(
    sig_date: str,
    buy_date: str,
    cand_codes: list[str],
    refs: dict,
    st_set: set[str],
    pre_lock_map: dict[str, float],
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Load or build daily T-1 feature snapshot cache (<=0.01s warm, <=0.8s once/day)."""
    cands_set = {str(c).zfill(6) for c in cand_codes if c}
    if (not force_refresh) and os.path.exists(T1_CACHE_JSON):
        try:
            old = json.load(open(T1_CACHE_JSON, encoding="utf-8"))
            if (
                old.get("schema_v") == 3
                and old.get("sig_date") == sig_date
                and old.get("buy_date") == buy_date
                and cands_set.issubset(set(old.get("stocks", {}).keys()))
            ):
                return old
        except Exception:
            pass

    mkt_slice = _compute_daily_adaily_slice(sig_date, st_set, refs.get("pit_st_tl"))
    mkt_f = compute_market_t1_features(sig_date, buy_date, refs, mkt_slice)
    # Also fetch Yahoo v8 1mo daily closes for GC=F, HG=F, ^VIX if buy_date > rd35_mkt_max_dt
    if buy_date > refs["rd35_mkt_max_dt"]:
        with ThreadPoolExecutor(max_workers=3) as ex:
            fv = ex.submit(_fetch_yahoo_chart_daily, "%5EVIX")
            fg = ex.submit(_fetch_yahoo_chart_daily, "GC%3DF")
            fh = ex.submit(_fetch_yahoo_chart_daily, "HG%3DF")
            v_map, g_map, h_map = fv.result(), fg.result(), fh.result()
        v_valid = {d: v for d, v in v_map.items() if d < buy_date}
        if v_valid:
            mkt_f["us_vix_level_on"] = float(v_valid[max(v_valid.keys())])
        for col_f, raw_m, tail_k in [("comm_au_ret5d_t1", g_map, "GC_F"), ("comm_cu_ret5d_t1", h_map, "HG_F")]:
            merged = {str(k)[:10]: float(v) for k, v in refs["gf_tail"].get(tail_k, {}).items() if str(k)[:10] < buy_date and pd.notna(v)}
            merged.update({d: v for d, v in raw_m.items() if d < buy_date})
            ks = sorted(merged.keys())
            if len(ks) >= 6 and merged[ks[-6]] > 0:
                mkt_f[col_f] = float((merged[ks[-1]] / merged[ks[-6]] - 1.0) * 100.0)

    stocks_f = compute_stocks_t1_features(sorted(cands_set), sig_date, buy_date, refs, mkt_slice, st_set, pre_lock_map)
    obj = {
        "schema_v": 3,
        "built_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sig_date": sig_date,
        "buy_date": buy_date,
        "mkt": mkt_f,
        "stocks": stocks_f,
    }
    tmp = T1_CACHE_JSON + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, T1_CACHE_JSON)
    return obj


# ---------------------------------------------------------------------------
# --verify-rd038 Historical Zero-Drift Replay & Live Feature Parity Gate
# ---------------------------------------------------------------------------

def run_verify_rd038() -> int:
    """Verify 100% causal score/mask parity against rd038_master_cache.pkl & pools_6strat_master."""
    t0 = time.time()
    lib20, wfc, cm, m12, m34 = _lazy_import_rd038()
    with open(f"{RD038_DIR}/_cache/rd038_master_cache.pkl", "rb") as f:
        rd38 = pickle.load(f)
    with open(f"{RD036_DIR}/part2_other5/_cache/rd036_other5_bundle.pkl", "rb") as f:
        bundle = pickle.load(f)
    p20, meta20 = lib20.load_20cm_enriched_data()
    p20["stack_c50_avg"] = rd38["sc20_aligned"]["stack_c50_avg"]

    df34 = rd38["pools_ext"]["3to4"].copy()
    df34["m4_mask"] = rd38["other5_variants"]["3to4"]["m4_4way_bl15"]["mask"]
    bp34 = list(dict.fromkeys(bundle["base_dyn_cols"] + bundle["atom_info"]["3to4"]["cols"]))

    df23 = rd38["pools_ext"]["2to3"].copy()
    df23["m2_score"] = rd38["other5_variants"]["2to3"]["m2_pair_cold45_d15"]["score"]
    bp23 = list(dict.fromkeys(bundle["base_dyn_cols"] + bundle["atom_info"]["2to3"]["cols"]))

    dfhi = rd38["pools_ext"]["high"].copy()
    dfhi["m1_score"] = rd38["other5_variants"]["high"]["m1_causal_cold_drop40_t0"]["score"]
    cols_hi = bundle["atom_info"]["high"]["cols"]
    cmat_hi = bundle["atom_info"]["high"]["contrib_mat"]

    checks_20 = [("2023-03-28", "300688"), ("2023-08-22", "301288"), ("2025-05-14", "300840"), ("2025-05-14", "301317"), ("2026-08-28", "688790"), ("2026-10-13", "688517")]
    checks_34 = [("2023-11-01", "002889"), ("2024-06-17", "002199"), ("2024-11-29", "000753"), ("2026-03-27", "603538")]
    checks_23 = [("2023-02-22", "002713"), ("2023-06-29", "002168"), ("2023-07-18", "603496"), ("2024-08-20", "001298"), ("2025-09-04", "002021"), ("2026-07-14", "605090")]
    checks_hi = [("2023-09-13", "600895"), ("2026-10-27", "002724")]

    max_err = 0.0
    all_ok = True
    rows_out = []

    for dt, code in checks_20:
        row = p20[(p20["buy_date"] == dt) & (p20["code"] == code)].iloc[0]
        m20 = fit_20cm_stack_c50_as_of(dt, p20, meta20, lib20, wfc)
        rdict = {k: float(row[k]) if (pd.notna(row[k]) if k in row else False) else np.nan for k in set(p20.columns) if isinstance(row.get(k), (int, float, np.number))}
        d_cb = int(score_card_by_name([rdict], m20["card_cb"])[0])
        d_mn = int(score_card_by_name([rdict], m20["card_mn"])[0])
        r3w = eval_3way_rules_by_name([rdict], m20["rules_3w"])
        d_3w = int(score_card_by_name(r3w, m20["card_3w"])[0])
        pred = float(row["v20_cold50"]) + float(np.round((d_cb + d_mn + d_3w) / 3.0))
        ref = float(row["stack_c50_avg"])
        err = abs(pred - ref)
        max_err = max(max_err, err)
        ok = err <= 1e-6
        all_ok &= ok
        rows_out.append(f"[{'PASS' if ok else 'FAIL'}] 20cm {dt} {code}: RD038={ref:.1f} vs shadow={pred:.1f} (v20={row['v20_score']:.1f}, cold50={row['v20_cold50']:.1f}, d=({d_cb},{d_mn},{d_3w}))")

    for dt, code in checks_34:
        row = df34[(df34["buy_date"] == dt) & (df34["code"] == code)].iloc[0]
        m34_c = fit_3to4_m4_as_of(dt, df34, bp34, m34)
        rdict = {c: float(row[c]) if pd.notna(row[c]) else np.nan for c in bp34}
        sc_mn, blk, _ = score_4way_mine_by_name([rdict], m34_c)
        pred_mask = not bool(blk[0])
        ref_mask = bool(row["m4_mask"])
        ok = (pred_mask == ref_mask)
        all_ok &= ok
        rows_out.append(f"[{'PASS' if ok else 'FAIL'}] 3to4 {dt} {code}: RD038_mask={ref_mask} vs shadow_mask={pred_mask} (orig={row['v20_score']:.1f}, mine_sc={sc_mn[0]:.1f})")

    for dt, code in checks_23:
        row = df23[(df23["buy_date"] == dt) & (df23["code"] == code)].iloc[0]
        c23 = fit_2to3_m2_as_of(dt, df23, bundle["ix_cols"], bp23, cm, m12)
        need_cols = set(bundle["ix_cols"]) | set(bp23)
        rdict = {c: float(row[c]) if pd.notna(row[c]) else np.nan for c in need_cols if c in row}
        r_aug = attach_dyn_pairs_by_name([rdict], c23)
        delta = int(score_card_by_name(r_aug, c23)[0]) if float(row["mkt10_zt_est_t1"]) < 45.0 else 0
        pred = float(row["orig_score"]) + delta
        ref = float(row["m2_score"])
        err = abs(pred - ref)
        max_err = max(max_err, err)
        ok = err <= 1e-6
        all_ok &= ok
        rows_out.append(f"[{'PASS' if ok else 'FAIL'}] 2to3 {dt} {code}: RD038={ref:.1f} vs shadow={pred:.1f} (orig={row['orig_score']:.1f}, delta={delta:+d})")

    for dt, code in checks_hi:
        idx = dfhi[(dfhi["buy_date"] == dt) & (dfhi["code"] == code)].index[0]
        row = dfhi.loc[idx]
        drops = fit_high_m1_as_of(dt, dfhi, cols_hi, cmat_hi, m12)
        drop_pts = sum(float(cmat_hi[idx, cols_hi.index(dc)]) for dc in drops) if float(row["mkt10_zt_est_t1"]) < 40.0 else 0.0
        pred = float(row["orig_score"]) - drop_pts
        ref = float(row["m1_score"])
        err = abs(pred - ref)
        max_err = max(max_err, err)
        ok = err <= 1e-6
        all_ok &= ok
        rows_out.append(f"[{'PASS' if ok else 'FAIL'}] high {dt} {code}: RD038={ref:.1f} vs shadow={pred:.1f} (orig={row['orig_score']:.1f}, dropped={drops})")

    # Check live feature extractor parity on 2026-11-12 (latest overlap day in master parquet)
    cache_now = build_or_load_causal_cache(force_refresh=False)
    refs = cache_now["refs"]
    st_set = _load_st_set()
    pools = pd.read_parquet(f"{RD035_BASE}/wave1_base/pools_6strat_master_newfactors_pit.parquet")
    p12 = pools[pools["buy_date"] == "2026-11-12"].copy()
    mkt_s = _compute_daily_adaily_slice("2026-11-24", st_set, refs.get("pit_st_tl"))
    d24_val = mkt_s[(mkt_s["dt"] == "2026-11-24") & (~mkt_s["is_st"]) & (mkt_s["volume"] > 0)]
    zt24_tot = float(d24_val["is_zt"].sum())
    zt24_20 = float((d24_val["is_zt"] & d24_val["is_20"]).sum())
    zt24_10 = zt24_tot - zt24_20
    ref25 = refs["rd35_mkt_tail"][refs["rd35_mkt_tail"]["trade_date"].astype(str) == "2026-11-25"].iloc[0]
    ok_mkt = (abs(zt24_tot - float(ref25["L1_zt_cnt_t1"])) < 1e-6) and (abs(zt24_20 - float(ref25["mkt20_zt_cnt_t1"])) < 1e-6)
    all_ok &= ok_mkt
    rows_out.append(f"[{'PASS' if ok_mkt else 'FAIL'}] MarketT1Parity 2026-11-24->25: RD035=({int(ref25['L1_zt_cnt_t1'])},{int(ref25['mkt20_zt_cnt_t1'])},{int(ref25['L1_zt_cnt_t1']-ref25['mkt20_zt_cnt_t1'])}) vs shadow=({int(zt24_tot)},{int(zt24_20)},{int(zt24_10)})")
    mkt_f = compute_market_t1_features("2026-11-11", "2026-11-12", refs, mkt_s)
    lock_m = {str(r["code"]).zfill(6): float(r.get("sd_lock_top10_pct_pre", 35.0) or 35.0) for _, r in p12.iterrows()}
    stk_f = compute_stocks_t1_features(p12["code"].tolist(), "2026-11-11", "2026-11-12", refs, mkt_s, st_set, lock_m)
    feat_max_diff = 0.0
    check_cols = [
        "L3_off_low_250d_t1", "L3_bias60_t1", "L3_cum_turn20_t1", "L3_pos_250d_t1",
        "oh_dd_from_1y_high", "oh_cum_turnover_1y", "oh_cool_days_since_last_zt", "oh_comm_active_month_ratio_1y",
        "sd_turn_5_20_t1", "sd_mcap_yi_t1", "sd_lhb_on_t1", "sd_lhb_inst_net_yi_t1", "sd_d1_seal_ratio_t1", "L2_kpl_streak_t1",
    ]
    for _, rp in p12.iterrows():
        ck = str(rp["code"]).zfill(6)
        for col in check_cols:
            dv = abs(float(stk_f[ck][col]) - float(rp[col]))
            feat_max_diff = max(feat_max_diff, dv)
    ok_feat = feat_max_diff <= 1e-3
    all_ok &= ok_feat
    rows_out.append(f"[{'PASS' if ok_feat else 'FAIL'}] LiveFeatureParity 2026-11-12 (301052/600715, 14 cols): max_abs_diff={feat_max_diff:.6f}")

    print(f"=== verify-rd038 ({time.time()-t0:.2f}s) | max_score_err={max_err:.6g} | ALL_PASS={all_ok} ===")
    for ln in rows_out:
        print(" ", ln)
    return 0 if all_ok else 1


# ---------------------------------------------------------------------------
# Fast Live 09:25 Quote Fetcher + V20.0 / GREEDY_ROBUST Arbiter & Card
# ---------------------------------------------------------------------------

HIGH_ATOM_KEY_MAP = {
    "shigh_af_brk_r10": "brk_r10",
    "shigh_af_n_zt_low": "n_zt",
    "shigh_af_csi5": "csi5",
    "shigh_af_d1_op_neg": "d1_op",
    "shigh_af_d0_tight": "d0_tight",
    "shigh_af_pelo_cool": "pelo",
    "shigh_af_lh1_zero": "lh1",
    "shigh_af_inst_pen": "in1",
    "shigh_af_px_le20": "price_tier",
    "shigh_af_turn_b4": "turn_boards",
    "shigh_af_d1_dip6": "d1_deep_dip",
    "shigh_af_lock_fmcap": "lock",
    "shigh_af_qu_in": "qu1",
    "shigh_af_kpl_ge5": "kpl_hist",
    "shigh_af_old_stk_th": "kpl_theme",
    "shigh_af_d0_top_lock": "top_locked",
    "shigh_af_d1_lh_hvy": "lh_heavy",
    "shigh_af_d1_net_pos": "net_pos",
    "shigh_af_d0_surf": "day_surf",
    "shigh_af_d0_early": "early_seal",
    "shigh_af_tech_pen": "reason_tech",
}


def fetch_qq(codes: list[str], max_workers: int = 24) -> dict[str, dict]:
    """Read-only batch Tencent live quote fetcher (zero yfinance)."""
    uniq = sorted({c for c in codes if c})
    if not uniq:
        return {}
    chunks = [uniq[i : i + 80] for i in range(0, len(uniq), 80)]
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _chunk(ch: list[str]) -> dict[str, dict]:
        res = {}
        url = "http://qt.gtimg.cn/q=" + ",".join(ch)
        for _ in range(2):
            try:
                raw = op.open(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=2.5).read().decode("gbk", errors="ignore")
                for ln in raw.split(";"):
                    if "~" not in ln:
                        continue
                    f = ln.split("~")
                    if len(f) > 38:
                        c6 = f[2].strip()
                        nm = f[1].strip()
                        cur, pre, opn = float(f[3] or 0), float(f[4] or 0), float(f[5] or 0)
                        hi, lo, amt = float(f[33] or 0), float(f[34] or 0), float(f[37] or 0) / 10000.0
                        b1, s1 = float(f[10] or 0), float(f[20] or 0)
                        dt8 = str(f[30]).strip()[:8] if len(f) > 30 else ""
                        q_dt = f"{dt8[:4]}-{dt8[4:6]}-{dt8[6:8]}" if len(dt8) == 8 and dt8.isdigit() else ""
                        op_px = opn if opn > 0 else cur
                        opct = (op_px / pre - 1.0) if pre > 0 and op_px > 0 else 0.0
                        cpct = (cur / pre - 1.0) if pre > 0 and cur > 0 else 0.0
                        is20 = c6.startswith(("30", "688", "689"))
                        lim = 1.20 if is20 else 1.10
                        zt_thr = 0.195 if is20 else 0.098
                        zt = float(np.floor(pre * lim * 100.0 + 0.5) / 100.0) if pre > 0 else 999.0
                        is_yz = bool(op_px >= zt - (0.011 if is20 else 0.005) or (b1 > 0 and s1 == 0 and opct >= zt_thr))
                        res[c6] = {
                            "name": nm, "pre": pre, "open": op_px, "raw_open": opn, "cur": cur, "hi": hi, "lo": lo,
                            "b1": b1, "s1": s1, "opct": opct, "cpct": cpct, "amt_yi": amt, "zt": zt,
                            "is_yizi": is_yz, "q_dt": q_dt,
                        }
                if res:
                    return res
            except Exception:
                pass
        return res

    if len(chunks) == 1:
        return _chunk(chunks[0])
    out = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for res in ex.map(_chunk, chunks):
            out.update(res)
    return out


def _fmt_pct_zh(val: float) -> str:
    p = float(val) * 100.0
    if p > 0.0005:
        return f"涨{p:.2f}%"
    if p < -0.0005:
        return f"跌{abs(p):.2f}%"
    return "平0.00%"


def _fmt_open_zh(val: float) -> str:
    p = float(val) * 100.0
    if p > 0.0005:
        return f"高开{p:.2f}%"
    if p < -0.0005:
        return f"低开{abs(p):.2f}%"
    return "平开0.00%"


def _fmt_delta_zh(d: int) -> str:
    if d > 0:
        return f"加{d}分"
    if d < 0:
        return f"减{abs(d)}分"
    return "0分"


def _no_hyphen(s: str) -> str:
    return str(s).replace("-", "至")


def _arbitrate_s2c(
    p_34: list[dict],
    p_hd: list[dict],
    p_pry: list[dict],
    p_23: list[dict],
    p_12: list[dict],
    p_20: list[dict],
    s20_thr: int,
) -> tuple[str, Optional[dict]]:
    """Exact V20.0 S2C 3-tier strict priority arbitrator."""
    top_all = []
    p34_S = [x for x in p_34 if x["sc_base"] >= 102]
    p34_Ad = [x for x in p_34 if 90 <= x["sc_base"] < 102 and x["open_pct"] >= 0.065]
    p34_Ac = [x for x in p_34 if 90 <= x["sc_base"] < 102 and x["open_pct"] < 0.065]
    phd_S = [x for x in p_hd if x["sc_base"] >= 96]
    phd_Ad = [x for x in p_hd if 88 <= x["sc_base"] < 96 and x["is_direct_open"]]
    phd_Ac = [x for x in p_hd if 88 <= x["sc_base"] < 96 and not x["is_direct_open"]]
    p12_d = [x for x in p_12 if x.get("is_direct_open")]
    p12_c = [x for x in p_12 if not x.get("is_direct_open")]

    if p34_S:
        x = p34_S[0]
        top_all.append({"tier_group": 1, "prio": 1, "strategy": "3to4", "code": x["code"], "name": x["name"], "score": x["sc_base"], "rk_prio": float(x["rk_prio"]), "label": f"[一梯队S档]三进四 {x['code']} {x['name']}({x['sc_base']}分)", "order": "开盘直买" if x["open_pct"] >= 0.065 else "条件单(10:30撤)"})
    if phd_S:
        x = phd_S[0]
        top_all.append({"tier_group": 1, "prio": 2, "strategy": "high", "code": x["code"], "name": x["name"], "score": x["sc_base"], "rk_prio": float(x["rk_prio"]), "label": f"[一梯队S档]高标首阴 {x['code']} {x['name']}({x['sc_base']}分)", "order": "开盘直买" if x["is_direct_open"] else "条件单(11:30撤)"})
    if p34_Ad:
        x = p34_Ad[0]
        top_all.append({"tier_group": 2, "prio": 3, "strategy": "3to4", "code": x["code"], "name": x["name"], "score": x["sc_base"], "rk_prio": float(x["rk_prio"]), "label": f"[二梯队09:25直买]三进四A {x['code']} {x['name']}({x['sc_base']}分)", "order": "开盘直买"})
    if phd_Ad:
        x = phd_Ad[0]
        top_all.append({"tier_group": 2, "prio": 4, "strategy": "high", "code": x["code"], "name": x["name"], "score": x["sc_base"], "rk_prio": float(x["rk_prio"]), "label": f"[二梯队09:25直买]高标A {x['code']} {x['name']}({x['sc_base']}分)", "order": "开盘直买"})
    if p_pry:
        x = p_pry[0]
        top_all.append({"tier_group": 2, "prio": 5, "strategy": "pry", "code": x["code"], "name": x["name"], "score": x["score"], "rk_prio": float(x["rk_prio"]), "label": f"[二梯队09:25直买]超跌撬板 {x['code']} {x['name']}({x['score']}分)", "order": "开盘直买"})
    if p_23:
        x = p_23[0]
        top_all.append({"tier_group": 2, "prio": 6, "strategy": "2to3", "code": x["code"], "name": x["name"], "score": x["score"], "rk_prio": float(x["rk_prio"]), "label": f"[二梯队09:25直买]二进三 {x['code']} {x['name']}({x['score']}分 {_fmt_open_zh(x['open_pct'])})", "order": "开盘直买"})
    if p12_d:
        x = p12_d[0]
        top_all.append({"tier_group": 2, "prio": 7, "strategy": "1to2", "code": x["c6"], "name": x["name"], "score": round(float(x["tot_v18"]), 1), "rk_prio": float(x["rk_prio"]), "label": f"[二梯队09:25直买]一进二周一 {x['c6']} {x['name']}({x['tot_v18']:.1f}分)", "order": "开盘直买"})
    if p_20:
        x = p_20[0]
        top_all.append({"tier_group": 2, "prio": 8, "strategy": "20cm", "code": x["code"], "name": x["name"], "score": x["score"], "rk_prio": float(x["rk_prio"]), "label": f"[二梯队09:25直买]20cm(S>={s20_thr}) {x['code']} {x['name']}({x['score']}分 {_fmt_open_zh(x['open_pct'])})", "order": "09:25直买"})
    if p34_Ac:
        x = p34_Ac[0]
        top_all.append({"tier_group": 3, "prio": 9, "strategy": "3to4", "code": x["code"], "name": x["name"], "score": x["sc_base"], "rk_prio": float(x["rk_prio"]), "label": f"[三梯队盘中单]三进四A {x['code']} {x['name']}({x['sc_base']}分)", "order": "条件单(10:30撤)"})
    if phd_Ac:
        x = phd_Ac[0]
        top_all.append({"tier_group": 3, "prio": 10, "strategy": "high", "code": x["code"], "name": x["name"], "score": x["sc_base"], "rk_prio": float(x["rk_prio"]), "label": f"[三梯队盘中单]高标A绿开 {x['code']} {x['name']}({x['sc_base']}分)", "order": "条件单(11:30撤)"})
    if p12_c:
        x = p12_c[0]
        top_all.append({"tier_group": 3, "prio": 11, "strategy": "1to2", "code": x["c6"], "name": x["name"], "score": round(float(x["tot_v18"]), 1), "rk_prio": float(x["rk_prio"]), "label": f"[三梯队盘中单]一进二盘中 {x['c6']} {x['name']}({x['tot_v18']:.1f}分)", "order": "条件单(11:30撤)"})

    if not top_all:
        return "全线空仓观望", None
    best = sorted(top_all, key=lambda x: (x["tier_group"], x["prio"]))[0]
    return f"{best['order']} {best['label']}", best


def run_shadow_compare(args) -> dict[str, Any]:
    t0 = time.time()
    if SCRIPTS_DIR not in sys.path:
        sys.path.insert(0, SCRIPTS_DIR)
    from live_3to4_v40_engine import score_single_3to4_v40_row
    from fast_2to3_today import evaluate_2to3_candidate
    from fast_1to2_today import evaluate_1to2_v19_df
    from fast_20cm_deepopen_today import evaluate_20cm_candidates
    assert "yfinance" not in sys.modules, "D12 violation"

    c1 = json.load(open(f"{DATA_DIR}/1to2_premarket_cache.json", encoding="utf-8"))
    c3 = json.load(open(f"{DATA_DIR}/3to4_premarket_cache.json", encoding="utf-8"))
    ch = json.load(open(f"{DATA_DIR}/high_dragon_premarket_cache.json", encoding="utf-8"))
    cpry = json.load(open(f"{DATA_DIR}/pry_premarket_cache.json", encoding="utf-8"))
    c23 = json.load(open(f"{DATA_DIR}/2to3_premarket_cache.json", encoding="utf-8"))
    c20 = json.load(open(f"{DATA_DIR}/20cm_deepopen_premarket_cache.json", encoding="utf-8"))

    d1_str = c1.get("d1_date", "")
    d3_str = c3.get("d3_date", "")
    dhd_str = ch.get("as_of_d1", "")
    dpr_str = cpry.get("sig_date", "")
    d23_str = c23.get("data_as_of_date") or c23.get("sig_date", "")
    d20_str = c20.get("sig_date", "")
    sig_date = max(d for d in (d20_str, d3_str, d23_str, dhd_str, d1_str, dpr_str) if d)
    buy_date = c20.get("buy_date") or c3.get("buy_date") or c23.get("buy_date") or datetime.date.today().isoformat()

    # Load / refresh causal models + T-1 feature snapshot
    causal = build_or_load_causal_cache(force_refresh=args.refresh_cache)
    st_set = _load_st_set()

    shadow_cands = []
    pre_lock_map: dict[str, float] = {}
    for x in c20.get("candidates", []):
        shadow_cands.append(x["code"])
        if x.get("lock_pct") is not None:
            pre_lock_map[str(x["code"]).zfill(6)] = float(x["lock_pct"])
    for x in c3.get("candidates", []):
        shadow_cands.append(x["code"])
        if x.get("lock_top10") is not None:
            pre_lock_map[str(x["code"]).zfill(6)] = float(x["lock_top10"])
    for x in c23.get("candidates", []):
        shadow_cands.append(x["code"])
        if x.get("lock_top10") is not None:
            pre_lock_map[str(x["code"]).zfill(6)] = float(x["lock_top10"])
    for x in ch.get("candidates", []):
        shadow_cands.append(x["code"])

    t1_snap = build_or_load_t1_cache(
        sig_date, buy_date, shadow_cands, causal["refs"], st_set, pre_lock_map, force_refresh=args.refresh_cache
    )
    mkt_f = t1_snap["mkt"]
    stocks_f = t1_snap["stocks"]
    yest_10cm_zt = int(round(float(mkt_f.get("mkt10_zt_est_t1", c20.get("mkt10_zt_cnt", 50)))))

    # Mock-open map (only for offline simulation tests)
    cache_pre_map = {}
    for lst, key_c, key_p in [
        (ch.get("candidates", []), "code", "close_d1"),
        (c3.get("candidates", []), "code", "px_d3"),
        (cpry.get("candidates", []), "code", "close"),
        (c23.get("candidates", []), "code", "prev_close"),
        (c1.get("candidates", []), "c6", "pre_c"),
        (c20.get("candidates", []), "code", "prev_close"),
    ]:
        for x in lst:
            if x.get(key_p):
                cache_pre_map[str(x[key_c]).zfill(6)] = float(x[key_p])

    mock_map = {}
    if args.mock_open:
        for pair in args.mock_open.split(","):
            if "=" in pair:
                km, vm = pair.split("=", 1)
                mock_map[km.strip().zfill(6)] = float(vm.strip())

    # Collect quotes cleanly
    q = {}
    all20_q_map = None
    if (not args.premarket) or bool(mock_map):
        fetch_list = []
        for x in c1.get("candidates", []):
            fetch_list.append(("sh" if x["c6"].startswith("6") else "sz") + x["c6"])
        for x in c3.get("candidates", []):
            fetch_list.append(("sh" if x["code"].startswith("6") else "sz") + x["code"])
            for fc in x.get("plate_fb_codes", []) + x.get("plate_zt_codes", []):
                fetch_list.append(("sh" if fc.startswith("6") else "sz") + fc)
        for x in ch.get("candidates", []):
            fetch_list.append(("sh" if x["code"].startswith("6") else "sz") + x["code"])
        for x in cpry.get("candidates", []):
            fetch_list.append(("sh" if x["code"].startswith("6") else "sz") + x["code"])
        for x in c23.get("candidates", []):
            fetch_list.append(("sh" if x["code"].startswith("6") else "sz") + x["code"])
        for x in c20.get("candidates", []):
            fetch_list.append(("sh" if x["code"].startswith("6") else "sz") + x["code"])
            for pc in stocks_f.get(x["code"], {}).get("_peers_10_on_sig", []):
                fetch_list.append(("sh" if pc.startswith("6") else "sz") + pc)
        if not c1.get("fb20_cln_blocked_by_16", False):
            for x in c1.get("fb20_cln_pool", []):
                fetch_list.append(("sh" if x["c6"].startswith("6") else "sz") + x["c6"])

        if not args.premarket:
            q = fetch_qq(fetch_list)
            if (not c20.get("halt_ge16", False)) and c20.get("candidates"):
                all20_c = [str(it[0]).zfill(6) for it in c20.get("all_20cm_codes", [])]
                if all20_c:
                    all20_q_map = fetch_qq([("sh" if mc.startswith("6") else "sz") + mc for mc in all20_c])

        for c6m, opv in mock_map.items():
            pre_m = float(q.get(c6m, {}).get("pre") or cache_pre_map.get(c6m) or 10.0)
            op_m = round(pre_m * (1.0 + opv), 2)
            lim_m = 1.20 if c6m.startswith(("30", "688", "689")) else 1.10
            zt_m = float(np.floor(pre_m * lim_m * 100.0 + 0.5) / 100.0)
            q[c6m] = {
                **q.get(c6m, {}),
                "name": q.get(c6m, {}).get("name", c6m),
                "pre": pre_m, "open": op_m, "cur": op_m, "hi": op_m, "lo": op_m,
                "b1": 0.0, "s1": 0.0, "opct": opv, "cpct": opv,
                "zt": zt_m, "is_yizi": bool(op_m >= zt_m - 0.005), "q_dt": "9999-12-31",
            }

    # Seasonal SR map for rk_prio
    sr_p = f"{DATA_DIR}/seasonal_rolling_sr_state.json"
    sr_st = json.load(open(sr_p, encoding="utf-8")) if os.path.exists(sr_p) else {"train_stds_2021_2025": {}, "blended_seasonal_sr": {}}
    stds_m = sr_st.get("train_stds_2021_2025", {})
    bsr_m = sr_st.get("blended_seasonal_sr", {})
    std_34, bsr_34 = float(stds_m.get("三进四_V41", 7.2638)), float(bsr_m.get("三进四_V41", 0.6412))
    std_12, bsr_12 = float(stds_m.get("一进二_V19", 25.8750)), float(bsr_m.get("一进二_V19", 0.6254))
    std_hd, bsr_hd = float(stds_m.get("高标首阴_V51", 14.9334)), float(bsr_m.get("高标首阴_V51", 0.9884))
    std_pry, bsr_pry = float(stds_m.get("超跌撬板_V21", 15.4066)), float(bsr_m.get("超跌撬板_V21", 0.5182))
    std_23, bsr_23 = float(stds_m.get("二进三_V21", 4.5105)), float(bsr_m.get("二进三_V21", 0.4246))
    std_20, bsr_20 = float(stds_m.get("20cm_V11", 4.2)), float(bsr_m.get("20cm_V11", 0.50))

    strategy_diffs = []

    # 1. 高标首阴 (V20 vs m1_causal_cold_drop40_t0)
    hd_v20, hd_sh = [], []
    drop_cols_hi = causal["models"]["high_drop_cols"]
    for r in ch.get("candidates", []):
        c6 = r["code"]
        rq = q.get(c6, {})
        is_lv = (not args.premarket or c6 in mock_map) and ((not dhd_str) or rq.get("q_dt", "") > dhd_str)
        op = rq.get("opct", 0.0) if is_lv else -0.99
        op2_pts = (8 if op < 0 else (6 if op <= 0.025 else 0)) if is_lv else 0
        v51_raw = int(r["static_score"]) + op2_pts
        vetos = list(r.get("veto_reasons", []))
        if not is_lv:
            vetos.append("盘前待09:25")
        else:
            if op > 0.045: vetos.append("超涨")
            if op < -0.065: vetos.append("核按钮")
            if rq.get("is_yizi") or (rq.get("open", 0) > 0 and rq.get("open", 0) >= rq.get("zt", 999) - 0.005):
                vetos.append("一字")
        is_veto = bool(r.get("is_vetoed", False)) or bool(vetos)
        sc_v = v51_raw if not is_veto else -999
        pass_v = (sc_v >= 88) and (not is_veto)
        item_v = {"code": c6, "name": r.get("name", c6), "sc_base": sc_v, "rk_prio": round((sc_v - 88.0) / std_hd + bsr_hd, 3) if pass_v else -999.0, "open_pct": op if is_lv else 0.0, "is_direct_open": (0.0 <= op <= 0.045) if is_lv else False, "passed_base": pass_v}
        hd_v20.append(item_v)

        drop_pts = 0
        dropped_names = []
        if yest_10cm_zt < 40 and drop_cols_hi:
            bd = r.get("breakdown", {})
            for dc in drop_cols_hi:
                if dc == "shigh_af_op2_neg":
                    if op2_pts > 0:
                        drop_pts += op2_pts
                        dropped_names.append("开盘调分")
                elif dc in HIGH_ATOM_KEY_MAP:
                    k_b = HIGH_ATOM_KEY_MAP[dc]
                    pts_k = int((bd.get(k_b) or {}).get("pts", 0))
                    if pts_k != 0:
                        drop_pts += pts_k
                        dropped_names.append(str((bd.get(k_b) or {}).get("name", k_b)))
        sc_s = (v51_raw - drop_pts) if not is_veto else -999
        pass_s = (sc_s >= 88) and (not is_veto)
        hd_sh.append({**item_v, "sc_base": sc_s, "rk_prio": round((sc_s - 88.0) / std_hd + bsr_hd, 3) if pass_s else -999.0, "passed_base": pass_s})
        if drop_pts != 0:
            hd_type = "盘前预检降分" if args.premarket else ("拦截" if (pass_v and not pass_s) else "降分")
            strategy_diffs.append({"strategy": "high", "code": c6, "name": r.get("name", c6), "type": hd_type, "v20_score": v51_raw, "shadow_score": v51_raw - drop_pts, "reason": f"高标首阴冷清日(昨10cm={yest_10cm_zt}<40)剔除负向加分({','.join(dropped_names)})"})
    hd_v20.sort(key=lambda x: (-x["rk_prio"], -x["sc_base"]))
    hd_sh.sort(key=lambda x: (-x["rk_prio"], -x["sc_base"]))

    # 2. 三进四 (V20 vs m4_4way_bl15)
    env3 = c3.get("env", {})
    cands3 = c3.get("candidates", [])
    t34_v20, t34_sh = [], []

    def _is3b(ri, rqi):
        ilv = (not args.premarket or ri["code"] in mock_map) and ((not d3_str) or rqi.get("q_dt", "") > d3_str)
        opx = float(rqi.get("open", 0.0) or 0.0)
        zpx = float(rqi.get("zt") or (np.floor(ri["px_d3"] * 1.10 * 100.0 + 0.5) / 100.0))
        return bool(ilv and opx > 0 and float(rqi.get("opct", -1.0)) < 0.098 and opx < zpx - 0.005 and (not rqi.get("is_yizi", False)))

    buy3 = [r["code"] for r in cands3 if _is3b(r, q.get(r["code"], {}))]
    top1_3 = max(buy3, key=lambda ck: q.get(ck, {}).get("opct", -1.0)) if buy3 else ""

    m34_card = causal["models"]["3to4"]
    feat_rows_34 = [enrich_live_and_ix_features(mkt_f, stocks_f.get(r["code"], {}), None, None) for r in cands3]
    sc_mn34, bl_34, match_34 = score_4way_mine_by_name(feat_rows_34, m34_card)

    for idx, r in enumerate(cands3):
        c6 = r["code"]
        rq = q.get(c6, {})
        ilv = (not args.premarket or c6 in mock_map) and ((not d3_str) or rq.get("q_dt", "") > d3_str)
        fb_ops = [q.get(fc, {}) for fc in r.get("plate_fb_codes", []) if fc in q and ((not d3_str) or q.get(fc, {}).get("q_dt", "") > d3_str)]
        zt_ops = [q.get(zc, {}).get("opct", 0.0) for zc in r.get("plate_zt_codes", []) if zc in q and ((not d3_str) or q.get(zc, {}).get("q_dt", "") > d3_str)]
        row = dict(r, **env3)
        row["open_pct"] = rq.get("opct", 0.0) if ilv else 0.0
        row["buyable_open"] = _is3b(r, rq)
        row["is_top1_3b_open"] = (c6 == top1_3) if ilv else False
        row["plate_fb_ho_cnt"] = sum(1 for x in fb_ops if x.get("opct", 0) >= 0.03 and not x.get("is_yizi"))
        row["plate_fb_yz_cnt"] = sum(1 for x in fb_ops if x.get("is_yizi"))
        row["plate_peers_open_avg"] = float(np.mean(zt_ops)) if zt_ops else 0.0
        res = score_single_3to4_v40_row(row)
        sc_v = res["score"] if (ilv and res["passed_skeleton"]) else -999
        pass_v = (sc_v >= 90) and res["passed_skeleton"] and ilv
        item_v = {"code": c6, "name": r.get("name", c6), "sc_base": sc_v, "rk_prio": round((sc_v - 90.0) / std_34 + bsr_34, 3) if pass_v else -999.0, "open_pct": row["open_pct"], "passed_base": pass_v}
        t34_v20.append(item_v)

        is_bl = bool(bl_34[idx])
        pass_s = pass_v and (not is_bl)
        item_s = {**item_v, "passed_base": pass_s, "rk_prio": item_v["rk_prio"] if pass_s else -999.0}
        t34_sh.append(item_s)
        if is_bl:
            strategy_diffs.append({"strategy": "3to4", "code": c6, "name": r.get("name", c6), "type": "盘前排雷拦截" if args.premarket else ("拦截" if pass_v else "预检触发排雷"), "v20_score": res["score"] if ilv else "待09:25", "shadow_score": "黑名单拦截", "reason": f"三进四触发四因子排雷黑名单({len(match_34[idx])}条命中)"})
    t34_v20.sort(key=lambda x: (-x["rk_prio"], -x["sc_base"]))
    t34_sh.sort(key=lambda x: (-x["rk_prio"], -x["sc_base"]))

    # 3. 一进二 (V20原版)
    df1, meta1 = evaluate_1to2_v19_df(c1, q, mock_map=mock_map)
    tot_thr12 = float(meta1.get("tot_thr", 304.8))
    if not df1.empty:
        df1["rk_prio"] = np.where(
            df1["passed_v18"],
            np.round((df1["tot_v18"] - tot_thr12) / std_12 + bsr_12, 3),
            np.where(df1["fb_dom295"], np.round((df1["tot_no_t3"] - 295.0) / std_12 - 5.0, 3), -999.0),
        )
    p_12 = df1[df1["passed_base"]].sort_values("rk_prio", ascending=False).to_dict("records") if not df1.empty else []

    # 4. 超跌撬板 (V20原版)
    pry_cands = cpry.get("candidates", [])
    need_pry_mkt = []
    for c in pry_cands:
        c6_p = c["code"]
        qp = q.get(c6_p, {})
        ilv = (not args.premarket or c6_p in mock_map) and ((not dpr_str) or qp.get("q_dt", "") > dpr_str)
        op_px = float(qp.get("open", 0.0)) if ilv else 0.0
        op_p = float(qp.get("opct", 0.0)) if (ilv and op_px > 0) else 0.0
        is_st_p = (c6_p in st_set) or ("ST" in str(qp.get("name", c.get("name", ""))).upper()) or ("退" in str(qp.get("name", c.get("name", ""))))
        is_yz = bool(ilv and (qp.get("is_yizi", False) or (op_px > 0 and op_px >= float(qp.get("zt", 999.0)) - 0.005)))
        if ilv and (not is_st_p) and (not is_yz) and op_px > 0 and (0.0 <= op_p <= 0.05) and int(c.get("static_score", 100)) + 15 >= 165:
            need_pry_mkt.append(c)
    zt_open_cnt = 0
    if need_pry_mkt and (not args.premarket):
        all_m = [str(mc).zfill(6) for mc in cpry.get("main_codes_sample", []) if str(mc).zfill(6) not in st_set]
        if all_m:
            qm = fetch_qq([("sh" if mc.startswith("6") else "sz") + mc for mc in all_m])
            zt_open_cnt = sum(
                1 for ck, v in qm.items()
                if ck not in st_set and "ST" not in str(v.get("name", "")).upper() and "退" not in str(v.get("name", ""))
                and ((not dpr_str) or v.get("q_dt", "") > dpr_str)
                and v.get("open", 0.0) > 0 and v.get("open", 0.0) >= v.get("zt", 999.0) - 0.005
            )
    p_pry = []
    for c in pry_cands:
        c6_p = c["code"]
        qp = q.get(c6_p, {})
        ilv = (not args.premarket or c6_p in mock_map) and ((not dpr_str) or qp.get("q_dt", "") > dpr_str)
        op_px = float(qp.get("open", 0.0)) if ilv else 0.0
        op_p = float(qp.get("opct", 0.0)) if (ilv and op_px > 0) else 0.0
        is_st_p = (c6_p in st_set) or ("ST" in str(qp.get("name", c.get("name", ""))).upper()) or ("退" in str(qp.get("name", c.get("name", ""))))
        is_yz = bool(ilv and (qp.get("is_yizi", False) or (op_px > 0 and op_px >= float(qp.get("zt", 999.0)) - 0.005)))
        if ilv and (not is_st_p) and (not is_yz) and op_px > 0 and (0.0 <= op_p <= 0.05):
            tot_p = int(c["static_score"]) + (15 if zt_open_cnt >= 12 else 0)
            if tot_p >= 165:
                p_pry.append({**c, "name": qp.get("name", c.get("name", c6_p)), "score": tot_p, "rk_prio": round((tot_p - 165.0) / std_pry + bsr_pry, 3)})
    p_pry.sort(key=lambda x: (-x["rk_prio"], -x["score"], x.get("bias10", 0.0), x["code"]))

    # 5. 二进三 (V20 vs m2_pair_cold45_d15)
    c23_list = c23.get("candidates", [])
    c23_card = causal["models"]["2to3"]
    feat_rows_23 = attach_dyn_pairs_by_name(
        [enrich_live_and_ix_features(mkt_f, stocks_f.get(r["code"], {}), None, None) for r in c23_list],
        c23_card,
    )
    deltas_23 = score_card_by_name(feat_rows_23, c23_card) if (yest_10cm_zt < 45 and c23_list) else np.zeros(len(c23_list), dtype=np.int32)
    e23_v20, e23_sh = [], []
    for idx, r in enumerate(c23_list):
        c6 = r["code"]
        rq = q.get(c6, {})
        ilv = (not args.premarket or c6 in mock_map) and ((not d23_str) or rq.get("q_dt", "") > d23_str)
        pre_c = float(r.get("prev_close", 0.0)) or rq.get("pre", 0.0)
        opn = rq.get("open", 0.0) if ilv else 0.0
        op = rq.get("opct", 0.0) if (ilv and opn > 0) else 0.0
        zt_23 = float(np.floor(pre_c * 1.10 * 100.0 + 0.5) / 100.0) if pre_c > 0 else 999.0
        is_yz = bool(ilv and (rq.get("is_yizi", False) or opn >= zt_23 - 0.005 or (rq.get("b1", 0.0) > 0 and rq.get("s1", 0.0) == 0 and op >= 0.098)))
        buyable = bool(ilv and opn > 0 and not is_yz)
        ev = evaluate_2to3_candidate(r, op, buyable)
        pass_v = bool(ev["passed_std90"] and ilv)
        item_v = {**r, **ev, "name": r.get("name") or rq.get("name", c6), "open_pct": op, "passed_std90": pass_v, "rk_prio": round((ev["score"] - 90.0) / std_23 + bsr_23, 3) if pass_v else -999.0}
        e23_v20.append(item_v)

        d_i = int(deltas_23[idx])
        sc_s = int(ev["score"]) + d_i
        no_veto_23 = bool(buyable and (len(ev["veto_reasons"]) == 0 or (not ev["veto_reasons"])))
        # Note evaluate_2to3_candidate adds "总分X<90" inside veto_reasons when score < 90!
        other_vetos = [vt for vt in ev.get("veto_reasons", []) if "总分" not in str(vt) and "未过" not in str(vt)]
        pass_s = bool(ilv and buyable and (not other_vetos) and sc_s >= 90)
        e23_sh.append({**item_v, "score": sc_s, "passed_std90": pass_s, "rk_prio": round((sc_s - 90.0) / std_23 + bsr_23, 3) if pass_s else -999.0})
        if d_i != 0:
            tag_t = "拦截" if (pass_v and not pass_s) else ("新放行" if ((not pass_v) and pass_s) else ("降分" if d_i < 0 else "升分"))
            strategy_diffs.append({"strategy": "2to3", "code": c6, "name": item_v["name"], "type": tag_t, "v20_score": int(ev["score"]) if ilv else "待09:25", "shadow_score": sc_s if ilv else f"T1配对{_fmt_delta_zh(d_i)}", "reason": f"二进三冷清日(昨10cm={yest_10cm_zt}<45)配对重排{_fmt_delta_zh(d_i)}"})
    p23_v20 = sorted([x for x in e23_v20 if x["passed_std90"]], key=lambda x: (-x["score"], x["open_pct"], x["plate_sz"], x["code"]))
    p23_sh = sorted([x for x in e23_sh if x["passed_std90"]], key=lambda x: (-x["score"], x["open_pct"], x["plate_sz"], x["code"]))

    # 6. 20cm (V20 >= 82 vs stack_c50_avg >= 80)
    c20_eval, _ = evaluate_20cm_candidates(c20, q, all20_q_map=all20_q_map, mock_map=mock_map, scan_f08_on_q=(not args.premarket or bool(mock_map)))
    m20_cards = causal["models"]["20cm"]
    p20_v20, p20_sh = [], []
    for r20 in c20_eval:
        c6 = r20["code"]
        pass_v = bool(r20["passed_S"])
        iv = {**r20, "rk_prio": round((r20["score"] - 82.0) / std_20 + bsr_20, 3) if pass_v else -999.0}
        if pass_v:
            p20_v20.append(iv)

        is_lv20 = bool(r20["is_live"])
        op_v = float(r20["open_pct"]) if is_lv20 else None
        auc_yz = None
        if is_lv20:
            peers10 = stocks_f.get(c6, {}).get("_peers_10_on_sig", [])
            auc_yz = 1.0 if any(((not d20_str) or q.get(pc, {}).get("q_dt", "") > d20_str) and float(q.get(pc, {}).get("opct", 0.0)) >= 0.095 for pc in peers10) else 0.0
        fdict = enrich_live_and_ix_features(mkt_f, stocks_f.get(c6, {}), op_v, auc_yz)
        d_cb = int(score_card_by_name([fdict], m20_cards["card_cb"])[0])
        d_mn = int(score_card_by_name([fdict], m20_cards["card_mn"])[0])
        r3w_d = eval_3way_rules_by_name([fdict], m20_cards["rules_3w"])
        d_3w = int(score_card_by_name(r3w_d, m20_cards["card_3w"])[0])
        delta20 = int(np.round((d_cb + d_mn + d_3w) / 3.0))
        f06_pts = int((r20.get("static_factors") or {}).get("F06_inst", 0))
        cold_sub = f06_pts if (yest_10cm_zt < 50 and f06_pts > 0) else 0
        sc_s = int(r20["score"]) - cold_sub + delta20
        pass_s = bool(r20["gates_ok"] and sc_s >= 80)
        if pass_s:
            p20_sh.append({**r20, "score": sc_s, "rk_prio": round((sc_s - 80.0) / std_20 + bsr_20, 3)})

        if cold_sub != 0 or delta20 != 0 or (pass_v != pass_s):
            cold_msg = f"冷清日(昨10cm={yest_10cm_zt}<50)关机构分减{cold_sub}并" if cold_sub > 0 else ""
            if is_lv20:
                tag_t = "拦截" if (pass_v and not pass_s) else ("新放行" if ((not pass_v) and pass_s) else ("降分" if sc_s < r20["score"] else "升分"))
                strategy_diffs.append({"strategy": "20cm", "code": c6, "name": r20["name"], "type": tag_t, "v20_score": r20["score"], "shadow_score": sc_s, "reason": f"20cm {cold_msg}三路重算{_fmt_delta_zh(delta20)}(门槛80)"})
            else:
                strategy_diffs.append({"strategy": "20cm", "code": c6, "name": r20["name"], "type": "盘前预检", "v20_score": f"静{r20['static_score']}", "shadow_score": f"静{int(r20['static_score'])-cold_sub}{_fmt_delta_zh(delta20)}", "reason": f"20cm {cold_msg}三路重算{_fmt_delta_zh(delta20)}，待09:25竞价定最终分"})

    p20_v20.sort(key=lambda x: (-x["score"], x["code"]))
    p20_sh.sort(key=lambda x: (-x["score"], x["code"]))

    p34_v_ok = [x for x in t34_v20 if x["passed_base"]]
    p34_s_ok = [x for x in t34_sh if x["passed_base"]]
    phd_v_ok = [x for x in hd_v20 if x["passed_base"]]
    phd_s_ok = [x for x in hd_sh if x["passed_base"]]

    v20_pick_str, v20_pick_obj = _arbitrate_s2c(p34_v_ok, phd_v_ok, p_pry, p23_v20, p_12, p20_v20, 82)
    sh_pick_str, sh_pick_obj = _arbitrate_s2c(p34_s_ok, phd_s_ok, p_pry, p23_sh, p_12, p20_sh, 80)

    is_same = (
        (v20_pick_obj is None and sh_pick_obj is None)
        or (v20_pick_obj is not None and sh_pick_obj is not None and v20_pick_obj["strategy"] == sh_pick_obj["strategy"] and v20_pick_obj["code"] == sh_pick_obj["code"])
    )

    elapsed = round(time.time() - t0, 3)
    return {
        "date": buy_date,
        "sig_date": sig_date,
        "mode": "premarket" if args.premarket else "0925_live",
        "mode_label": "盘前备战" if args.premarket else "09:25 实盘对照",
        "run_ts": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": elapsed,
        "yest_10cm_zt": yest_10cm_zt,
        "cold_flags": {"c50": yest_10cm_zt < 50, "c45": yest_10cm_zt < 45, "c40": yest_10cm_zt < 40},
        "v20_pick": v20_pick_str,
        "shadow_pick": sh_pick_str,
        "v20_pick_obj": v20_pick_obj,
        "shadow_pick_obj": sh_pick_obj,
        "is_same": is_same,
        "strategy_diffs": strategy_diffs,
        "details": {
            "cand_counts": {"1to2": len(df1), "3to4": len(cands3), "high": len(ch.get("candidates", [])), "pry": len(pry_cands), "2to3": len(c23_list), "20cm": len(c20_eval)},
            "mkt_t1": {k: (round(float(v), 4) if isinstance(v, (int, float)) and np.isfinite(v) else v) for k, v in mkt_f.items()},
        },
    }


def format_compact_card(res: dict[str, Any]) -> str:
    """Format strictly <=15 lines, pure plain Chinese, ZERO '-' hyphens."""
    dt_slash = str(res["date"]).replace("-", "/")
    sig_slash = str(res["sig_date"]).replace("-", "/")
    y10 = res["yest_10cm_zt"]
    cf = res["cold_flags"]
    cold_tags = []
    if cf["c50"]: cold_tags.append("20cm冷清(<50)")
    if cf["c45"]: cold_tags.append("二进三冷清(<45)")
    if cf["c40"]: cold_tags.append("高标冷清(<40)")
    cold_desc = "，".join(cold_tags) if cold_tags else "常态日(未触发冷清条件)"

    lines = [
        f"【V21.0 影子对照】{dt_slash} ({res['mode_label']} | 基准日 {sig_slash} | 耗时 {res['elapsed_sec']:.2f}s)",
        f"昨日10cm涨停: {y10}家 ({cold_desc})",
        f"现役 V20.0 唯一买点: {_no_hyphen(res['v20_pick'])}",
        f"影子 V21.0 唯一买点: {_no_hyphen(res['shadow_pick'])}",
    ]
    if res["is_same"] and not res["strategy_diffs"]:
        lines.append("双轨裁决结果: 双轨完全一致（今日四件套未改分、未拦截，S2C买点完全相同）")
    elif res["is_same"]:
        lines.append("双轨裁决结果: 唯一买点双轨完全一致（局部候选有调分但未改最终唯一买点）")
    else:
        lines.append("双轨裁决结果: 双轨出现分歧（详见下方变更清单）")

    if res["mode"] == "premarket":
        lines.append("盘前提示: 20cm与需09:25开盘价条目待 09:25 竞价定最终分，当前基于昨日/盘前条件预检")

    diffs = res["strategy_diffs"]
    if diffs:
        max_show = 15 - len(lines) - (1 if len(diffs) > (15 - len(lines)) else 0)
        for d in diffs[:max(1, max_show)]:
            lines.append(_no_hyphen(f"  [{d['type']}] {d['code']} {d['name']} | 原={d['v20_score']} 新={d['shadow_score']} | {d['reason']}"))
        if len(diffs) > max_show:
            lines.append(f"  其余 {len(diffs) - max_show} 条差异详见影子账本或 JSON 输出")

    card = "\n".join(lines[:15])
    assert "-" not in card, f"Hyphen violation in compact card:\n{card}"
    assert len(card.splitlines()) <= 15, f"Card >15 lines: {len(card.splitlines())}"
    return card


def write_idempotent_ledger(res: dict[str, Any]) -> None:
    """Idempotently upsert snapshot keyed by (date, mode) in shadow_4piece_2w_ledger.jsonl."""
    key = (res["date"], res["mode"])
    rec = {k: res[k] for k in ("date", "sig_date", "mode", "run_ts", "yest_10cm_zt", "v20_pick", "shadow_pick", "is_same", "strategy_diffs", "details")}
    existing = []
    if os.path.exists(LEDGER_JSONL):
        with open(LEDGER_JSONL, encoding="utf-8") as f:
            for ln in f:
                if ln.strip():
                    obj = json.loads(ln)
                    if (obj.get("date"), obj.get("mode")) != key:
                        existing.append(obj)
    existing.append(rec)
    existing.sort(key=lambda x: (str(x.get("date", "")), str(x.get("mode", ""))))
    tmp = LEDGER_JSONL + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for obj in existing:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    os.replace(tmp, LEDGER_JSONL)


def main() -> int:
    ap = argparse.ArgumentParser(description="稳健四件套 (GREEDY_ROBUST) 每日只读影子报盘工具")
    ap.add_argument("--premarket", action="store_true", help="盘前/盘后备战影子对照模式")
    ap.add_argument("--dry-run", action="store_true", help="仅打印对比卡与校验信息，不写账本")
    ap.add_argument("--json-only", action="store_true", help="仅输出机器可读 JSON")
    ap.add_argument("--refresh-cache", action="store_true", help="强制刷新截至昨日因果参数与当日T1缓存")
    ap.add_argument("--verify-rd038", action="store_true", help="历史分歧日零漂移一致性自检")
    ap.add_argument("--mock-open", type=str, default="", help="测试用模拟竞价涨跌幅，如 '300086=-0.05'")
    args = ap.parse_args()

    if args.verify_rd038:
        return run_verify_rd038()

    res = run_shadow_compare(args)
    if not args.dry_run:
        write_idempotent_ledger(res)

    if args.json_only:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(format_compact_card(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())

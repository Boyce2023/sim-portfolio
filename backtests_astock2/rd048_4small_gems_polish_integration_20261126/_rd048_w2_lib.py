#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD048 Wave 2 Shared Library: Cache Loader, Exact MTM Segs, Unified Simulator & Forensics."""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import json, math, pickle, re, resource, sys
from typing import Optional
import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 VIOLATION"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
BASE_AST2 = f"{SIM}/backtests_astock2"
RD038_DIR = f"{BASE_AST2}/rd038_grand_bundle_assembly_20261126"
RD048_DIR = f"{BASE_AST2}/rd048_4small_gems_polish_integration_20261126"
W1_BASE = f"{BASE_AST2}/rd035_grand_wf_scorecard_20261125/wave1_base"

if RD038_DIR not in sys.path:
    sys.path.insert(0, RD038_DIR)
import _rd038_engine as eng
import _common_rd036 as cm

CFG_V20 = {"s20": "base_76", "s34": "base", "s23": "base", "shi": "base", "spr": "base", "s12": "base", "w2a5": "none", "w2a6": "s_tier_reserve_only"}
CFG_V21 = {"s20": "stack_c50_avg", "s34": "m4_4way_bl15", "s23": "m2_pair_cold45_d15", "shi": "m1_causal_cold_drop40_t0", "spr": "base", "s12": "base", "w2a5": "none", "w2a6": "s_tier_reserve_only"}

def rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 1)

def load_rd038_cache() -> dict:
    with open(f"{RD038_DIR}/_cache/rd038_master_cache.pkl", "rb") as f:
        return pickle.load(f)

def convert_ret_fee(r: float, fee_from: float, fee_to: float) -> float:
    return (1.0 + float(r)) / (1.0 - fee_from) * (1.0 - fee_to) - 1.0

def mtm_json_to_segs(mtm_json_str: str, idx_map: dict, val_is_mult: bool, ret_from: float, ret_to: float) -> tuple:
    """Convert mtm_pairs_json (mult or daily_ret) to ((ti, mult), ...) with exact terminal fee scaling."""
    raw = json.loads(mtm_json_str) if mtm_json_str else []
    segs = []
    for dt_s, v in raw:
        ti = idx_map.get(str(dt_s)[:10])
        if ti is not None:
            m = float(v) if val_is_mult else (1.0 + float(v))
            segs.append((int(ti), m))
    if segs and abs(ret_to - ret_from) > 1e-12:
        segs = list(cm.scale_mtm_segs(tuple(segs), ret_from, ret_to))
    if segs:
        p = 1.0
        for _, m in segs:
            p *= float(m)
        target = 1.0 + float(ret_to)
        if p > 0 and abs(p - target) < 1e-5 * max(1.0, abs(target)):
            segs[-1] = (segs[-1][0], segs[-1][1] * (target / p))
    return tuple(segs)

def prepare_gem_pool_for_rd038(
    df_raw: pd.DataFrame, strategy_name: str, tier_name: str, prio_val: float, phase_val: Optional[int],
    idx_5y: dict, val_is_mult: bool, fee_mode: str = "030", cal_end: str = "2026-11-16",
) -> pd.DataFrame:
    """Standardize Gem trades/candidates to match RD038 pool6 schema with exact MTM tuples."""
    sub = df_raw[(df_raw["buy_date"] >= "2021-11-16") & (df_raw["exit_date"] <= cal_end)].copy().reset_index(drop=True)
    if sub.empty:
        return pd.DataFrame()
    tag = {"030": "030", "050": "050", "080": "080"}[fee_mode]
    f_to = float(fee_mode) / 10000.0
    col_r = f"net_ret_{tag}"
    rets = sub[col_r].to_numpy(float) if col_r in sub.columns else np.array([convert_ret_fee(x, 0.0030, f_to) for x in sub["net_ret"].to_numpy(float)])
    base_rets = sub["net_ret"].to_numpy(float)
    mtm_list = [mtm_json_to_segs(s, idx_5y, val_is_mult, float(rb), float(rn)) for s, rb, rn in zip(sub["mtm_pairs_json"], base_rets, rets)]
    bh_arr = pd.to_numeric(sub["buy_hhmm"], errors="coerce").fillna(925).astype(int) if "buy_hhmm" in sub.columns else np.full(len(sub), 925, dtype=int)
    eh_arr = pd.to_numeric(sub["exit_hhmm"], errors="coerce").fillna(1500).astype(int) if "exit_hhmm" in sub.columns else np.full(len(sub), 1500, dtype=int)
    sc_arr = pd.to_numeric(sub["score"], errors="coerce").fillna(114.0).astype(float) if "score" in sub.columns else np.full(len(sub), 100.0, dtype=float)
    out = pd.DataFrame({
        "buy_date": sub["buy_date"].astype(str).str[:10], "buy_hhmm": bh_arr,
        "exit_date": sub["exit_date"].astype(str).str[:10], "exit_hhmm": eh_arr,
        "code": sub["code"].astype(str).str.zfill(6), "name": sub["name"].astype(str),
        "strategy": strategy_name, "tier": tier_name, "score": sc_arr,
        "net_ret": rets, "mtm_use": mtm_list, "buy_price_val": np.nan, "is_adj_px": False, "is_untrig": False,
        "prio": float(prio_val), "phase": int(phase_val) if phase_val is not None else np.where(bh_arr == 925, 0, 1),
    })
    return out

def compute_dr_and_eval(name: str, group: str, tr_df: pd.DataFrame, cache: dict, ref_dr_wf: Optional[np.ndarray] = None, waits_n: int = 0) -> dict:
    """Compute exact MTM daily returns, 5-window D15 metrics, and vs-base stats matching RD038."""
    cal_5y = cache["cal_5y"]
    idx_5y = {d: i for i, d in enumerate(cal_5y)}
    T = len(cal_5y)
    day_mult = np.ones(T, dtype=float)
    if not tr_df.empty:
        for r in tr_df.itertuples(index=False):
            segs = getattr(r, "mtm_use", None)
            if segs:
                for ti, mult in segs:
                    if 0 <= int(ti) < T:
                        day_mult[int(ti)] *= float(mult)
            else:
                bi, ei = idx_5y.get(r.buy_date), idx_5y.get(r.exit_date)
                if bi is not None and ei is not None and ei > bi:
                    span = ei - bi + 1
                    day_mult[bi : ei + 1] *= (1.0 + float(r.net_ret)) ** (1.0 / span)
    dr_5y = day_mult - 1.0
    nav_5y_tr = float(np.prod(1.0 + tr_df["net_ret"].to_numpy(float))) if not tr_df.empty else 1.0
    mtm_diff_5y = abs(float(np.prod(day_mult)) - nav_5y_tr)
    wf_off = idx_5y[eng.WF_START]
    dr_wf = dr_5y[wf_off:]
    wf_seg_prod = 1.0
    if not tr_df.empty:
        for r in tr_df.itertuples(index=False):
            segs = getattr(r, "mtm_use", None)
            if segs:
                for ti, mult in segs:
                    if int(ti) >= wf_off and int(ti) < T:
                        wf_seg_prod *= float(mult)
            elif r.buy_date >= eng.WF_START:
                wf_seg_prod *= (1.0 + float(r.net_ret))
    mtm_diff_wf = abs(float(np.prod(1.0 + dr_wf)) - wf_seg_prod)
    sim_res = {"trades_df": tr_df, "dr_5y": dr_5y, "dr_wf": dr_wf, "mtm_diff_5y": mtm_diff_5y, "mtm_diff_wf": mtm_diff_wf, "waits": [0] * waits_n, "swaps": []}
    ev = eng.evaluate_bundle(name, group, sim_res, cache, ref_dr_wf=ref_dr_wf, perm_n=0)
    ev["dr_5y"] = dr_5y
    ev["dr_wf"] = dr_wf
    ev["trades_df"] = tr_df
    return ev

def run_tier_or_empty_sim(
    cache: dict, base_cfg: dict, extra_df: Optional[pd.DataFrame], mode: str = "tier", fee_mode: str = "030",
    stock_to_fut_lag: int = 0, fut_to_stock_lag: int = 0,
) -> tuple[pd.DataFrame, list]:
    """Unified simulator: mode='tier' integrates extra_df into priority queue; mode='empty_fill' only enters when base is idle."""
    cal_5y = cache["cal_5y"]
    idx_5y = {d: i for i, d in enumerate(cal_5y)}
    pool6, ut_df = eng.build_bundle_pools(cache, base_cfg, fee_mode=fee_mode)
    base_df = pd.concat([pool6, ut_df], ignore_index=True) if not ut_df.empty else pool6.copy()
    base_df["prio"] = base_df["tier"].map(eng.m1.S2C_MAP).fillna(999).astype(float)
    base_df = base_df[base_df["prio"] < 999].copy()
    is_s_cond = base_df["tier"].isin(["3to4_S(>=102)", "high_S(>=96)"])
    base_df["phase"] = np.where((base_df["buy_hhmm"] == 925) | is_s_cond, 0, 1)

    if mode == "tier" and extra_df is not None and not extra_df.empty:
        df = pd.concat([base_df, extra_df], ignore_index=True)
        srt = df.sort_values(["buy_date", "phase", "prio", "score", "buy_hhmm", "code"], ascending=[True, True, True, False, True, True], kind="mergesort").reset_index(drop=True)
        by_dt = {dt: grp for dt, grp in srt.groupby("buy_date", sort=False)}
        taken, waits = [], []
        cur_ed, cur_eh = "", 0
        for dt in cal_5y:
            grp = by_dt.get(dt)
            if grp is None:
                continue
            for r in grp.itertuples(index=False):
                if (not cur_ed) or (r.buy_date > cur_ed) or (r.buy_date == cur_ed and int(r.buy_hhmm) > cur_eh):
                    if r.is_untrig:
                        waits.append(r.buy_date)
                    else:
                        taken.append(r._asdict())
                    cur_ed, cur_eh = str(r.exit_date), int(r.exit_hhmm)
                    break
        return pd.DataFrame(taken), waits

    # Empty-day fill mode (base strictly wins on any day it is eligible; extra enters only when slot free & base silent)
    srt_b = base_df.sort_values(["buy_date", "phase", "prio", "score", "buy_hhmm", "code"], ascending=[True, True, True, False, True, True], kind="mergesort")
    by_dt_b = {dt: grp for dt, grp in srt_b.groupby("buy_date", sort=False)}
    by_dt_e = {}
    if extra_df is not None and not extra_df.empty:
        srt_e = extra_df.sort_values(["buy_date", "prio", "score", "buy_hhmm", "code"], ascending=[True, True, False, True, True], kind="mergesort")
        by_dt_e = {dt: grp for dt, grp in srt_e.groupby("buy_date", sort=False)}

    taken, waits = [], []
    cur_ed, cur_eh = "", 0
    last_stk_exit_ti = -999
    last_fut_exit_ti = -999
    for ti, dt in enumerate(cal_5y):
        picked_base = False
        grp_b = by_dt_b.get(dt)
        if grp_b is not None:
            for r in grp_b.itertuples(index=False):
                # Enforce futures->stock transfer lag if fut_to_stock_lag > 0
                if fut_to_stock_lag > 0 and ti < last_fut_exit_ti + fut_to_stock_lag:
                    continue
                if (not cur_ed) or (r.buy_date > cur_ed) or (r.buy_date == cur_ed and int(r.buy_hhmm) > cur_eh):
                    if r.is_untrig:
                        waits.append(r.buy_date)
                    else:
                        taken.append(r._asdict())
                    cur_ed, cur_eh = str(r.exit_date), int(r.exit_hhmm)
                    last_stk_exit_ti = idx_5y.get(cur_ed, ti)
                    picked_base = True
                    break
        if picked_base:
            continue
        grp_e = by_dt_e.get(dt)
        if grp_e is not None:
            if stock_to_fut_lag > 0 and ti < last_stk_exit_ti + stock_to_fut_lag:
                continue
            for r in grp_e.itertuples(index=False):
                if (not cur_ed) or (r.buy_date > cur_ed) or (r.buy_date == cur_ed and int(r.buy_hhmm) > cur_eh):
                    taken.append(r._asdict())
                    cur_ed, cur_eh = str(r.exit_date), int(r.exit_hhmm)
                    if fut_to_stock_lag > 0:
                        last_fut_exit_ti = idx_5y.get(cur_ed, ti)
                    else:
                        last_stk_exit_ti = idx_5y.get(cur_ed, ti)
                    break
    return pd.DataFrame(taken), waits

#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
_v22_engine.py — V22.0 Grand Assembly Engine:
  - Clean integration of P2_R_OPT, P1A_DirA_Tight80, and P1A_4to5 (Pos1/Pos2/Pos5) onto V21/V20
  - Full 7-window D15 evaluation (incl. second_mdd_pct, ex_top3/5, excess_csi300, 1000x perm & paired perm)
  - LOO & Dual-Scissors counterfactual audit (handling added, removed, and modified-return trades)
  - 4-Tier 1.5x Margin Simulator (L1..L4 incl. Buwen Selective) with intraday-low MMR
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import json
import math
import resource
import sys
from typing import Optional

import numpy as np
import pandas as pd
import scipy.stats as stats

assert "yfinance" not in sys.modules, "D12 VIOLATION"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
RD038 = f"{SIM}/backtests_astock2/rd038_grand_bundle_assembly_20261126"
RD048 = f"{SIM}/backtests_astock2/rd048_4small_gems_polish_integration_20261126"
RD049 = f"{SIM}/backtests_astock2/rd049_traffic_light_granular_20261126"
P1A = f"{SIM}/backtests_astock/v22_grand_convergence_20261126/p1a_3to4_4to5_mutual"
P2 = f"{SIM}/backtests_astock/v22_grand_convergence_20261126/p2_rd049_falsekill_audit"

for p in (RD038, RD048, RD049, P1A, P2):
    if p not in sys.path:
        sys.path.insert(0, p)

import _rd038_engine as eng
import _wf_sim_and_metrics as wfm
import _rd048_w2_lib as w2
import _rd049_common as cm49
import step2_targeted_rescue_and_truncation as p2s

CFG_V20 = dict(cm49.CFG_V20)
CFG_V21 = dict(cm49.CFG_V21)

D15_WINDOWS = [
    ("FULL_5Y", "2021-11-16", "2026-11-16"),
    ("IS_2123", "2021-11-16", "2023-12-31"),
    ("OOS_2426", "2024-01-01", "2026-11-16"),
    ("WF_2326", "2023-01-03", "2026-11-16"),
    ("Y2025_2026", "2025-01-01", "2026-11-16"),
    ("Y2026", "2026-01-01", "2026-11-16"),
    ("Y2026_H2", "2026-07-01", "2026-11-16"),
]


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


def apply_v22_modifications(
    cache: dict,
    reg_idx: pd.DataFrame,
    use_p2: bool = False,
    use_dirA: bool = False,
    dirA_raw_df: Optional[pd.DataFrame] = None,
) -> dict:
    """Return a clean shallow copy of `cache` with optional P2_R_OPT and DirA_Risk7D2_Tight80 applied."""
    if use_p2:
        c2 = p2s.apply_rescue_filter(cache, reg_idx, pos_cut=0.50, pry_mkt_cut=50.0, pry_dt_climax=100.0)
    else:
        c2 = {**cache, "pools_ext": {k: v.copy() for k, v in cache["pools_ext"].items()}}

    if use_dirA and dirA_raw_df is not None and not dirA_raw_df.empty:
        idx_5y = {d: i for i, d in enumerate(c2["cal_5y"])}
        d34 = c2["pools_ext"]["3to4"].copy()
        da_map = {}
        for r in dirA_raw_df.itertuples(index=False):
            da_map[(str(r.buy_date)[:10], str(r.code).zfill(6))] = r

        for i in d34.index:
            bd = str(d34.at[i, "buy_date"])[:10]
            c6 = str(d34.at[i, "code"]).zfill(6)
            dr = da_map.get((bd, c6))
            if dr is None:
                continue
            r30_old = float(d34.at[i, "net_ret_030"])
            r30_new = float(dr.net_ret_030)
            if abs(r30_new - r30_old) <= 1e-6 and str(dr.exit_date)[:10] == str(d34.at[i, "exit_date"])[:10]:
                continue
            r20_new = float(dr.net_ret_020)
            d34.at[i, "exit_date"] = str(dr.exit_date)[:10]
            d34.at[i, "exit_hhmm"] = int(dr.exit_hhmm)
            d34.at[i, "net_ret"] = r20_new
            d34.at[i, "net_ret_020"] = r20_new
            d34.at[i, "net_ret_030"] = r30_new
            d34.at[i, "net_ret_050"] = float(dr.net_ret_050)
            d34.at[i, "net_ret_080"] = float(dr.net_ret_080)
            if "net_ret_native" in d34.columns:
                d34.at[i, "net_ret_native"] = r20_new
            mtm_str = getattr(dr, "mtm_pairs_json", "")
            for tag, fv in [("020", 0.0020), ("030", 0.0030), ("050", 0.0050), ("080", 0.0080)]:
                r_f = float(w2.convert_ret_fee(r20_new, 0.0020, fv))
                segs = w2.mtm_json_to_segs(mtm_str, idx_5y, True, r30_new, r_f)
                d34.at[i, f"mtm_5y_{tag}"] = segs
                if tag == "020" and "mtm_5y_native" in d34.columns:
                    d34.at[i, "mtm_5y_native"] = segs
        c2["pools_ext"]["3to4"] = d34
    return c2


def prepare_4to5_pool(raw_4to5_df: pd.DataFrame, pos_mode: str, fee_mode: str, cal_5y: list[str], tier_lbl: str) -> pd.DataFrame:
    """Convert 4to5 raw parquet/dataframe to RD038 pool schema preserving buy_price_val and exact MTM."""
    if raw_4to5_df is None or raw_4to5_df.empty or pos_mode == "none":
        return pd.DataFrame()
    idx_5y = {d: i for i, d in enumerate(cal_5y)}
    prio_map = {"Pos1": 0.0, "Pos2": 2.5, "Pos5": 99.0}
    ep = w2.prepare_gem_pool_for_rd038(
        raw_4to5_df, "4to5", tier_lbl, prio_map[pos_mode], 0, idx_5y, True, fee_mode, cal_end=cal_5y[-1]
    )
    if not ep.empty and "buy_price_val" in raw_4to5_df.columns:
        bp_map = {
            (str(r.buy_date)[:10], str(r.code).zfill(6)): float(r.buy_price_val)
            for r in raw_4to5_df.itertuples(index=False)
            if pd.notna(r.buy_price_val)
        }
        ep["buy_price_val"] = [bp_map.get((r.buy_date, r.code), np.nan) for r in ep.itertuples(index=False)]
    return ep


def run_v22_sim(
    cache: dict,
    base_cfg: dict,
    raw_4to5_df: Optional[pd.DataFrame] = None,
    pos_mode: str = "none",
    fee_mode: str = "030",
    tier_lbl: str = "4to5",
) -> dict:
    """Run exact single-slot causal simulation with optional 4to5 integration (Pos1/Pos2/Pos5)."""
    cal_5y = cache["cal_5y"]
    idx_5y = {d: i for i, d in enumerate(cal_5y)}
    if pos_mode == "none" or raw_4to5_df is None:
        return eng.run_bundle_sim(cache, base_cfg, fee_mode=fee_mode)

    ep = prepare_4to5_pool(raw_4to5_df, pos_mode, fee_mode, cal_5y, tier_lbl)
    sim_mode = "empty_fill" if pos_mode == "Pos5" else "tier"
    tr_df, waits = w2.run_tier_or_empty_sim(cache, base_cfg, ep, mode=sim_mode, fee_mode=fee_mode)
    if not tr_df.empty:
        assert (tr_df["exit_date"] > tr_df["buy_date"]).all(), "T+0 violation"
        for i in range(1, len(tr_df)):
            p, c = tr_df.iloc[i - 1], tr_df.iloc[i]
            assert (c["buy_date"], int(c["buy_hhmm"])) > (p["exit_date"], int(p["exit_hhmm"])), f"Overlap at {i}"

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
    tr_wf = tr_df[tr_df["buy_date"] >= eng.WF_START] if not tr_df.empty else tr_df
    dr_wf = dr_5y[wf_off:]
    nav_wf_tr = float(np.prod(1.0 + tr_wf["net_ret"].to_numpy(float))) if not tr_wf.empty else 1.0
    mtm_diff_wf = abs(float(np.prod(1.0 + dr_wf)) - nav_wf_tr)

    return {
        "trades_df": tr_df,
        "waits": waits,
        "swaps": [],
        "dr_5y": dr_5y,
        "dr_wf": dr_wf,
        "mtm_diff_5y": float(mtm_diff_5y),
        "mtm_diff_wf": float(mtm_diff_wf),
    }


def calc_top2_dd(dr: np.ndarray) -> tuple[float, float]:
    """Compute largest and second-largest daily MTM drawdown episodes (%)."""
    if len(dr) == 0:
        return 0.0, 0.0
    cv = np.cumprod(1.0 + dr)
    pk = np.maximum.accumulate(np.concatenate([[1.0], cv]))[1:]
    dd = (pk - cv) / pk
    eps = []
    i = 0
    while i < len(dd):
        if dd[i] > 1e-12:
            j = i
            while j < len(dd) and dd[j] > 1e-12:
                j += 1
            eps.append(float(np.max(dd[i:j]) * 100.0))
            i = j
        else:
            i += 1
    eps.sort(reverse=True)
    d1 = eps[0] if len(eps) >= 1 else 0.0
    d2 = eps[1] if len(eps) >= 2 else 0.0
    return round(d1, 2), round(d2, 2)


def paired_perm_test(dr_new: np.ndarray, dr_base: np.ndarray, n_perm: int = 1000, seed: int = 20261126) -> dict:
    """1,000x paired sign-flip permutation test on daily return differences (and paired t-test)."""
    dd = np.asarray(dr_new, dtype=float) - np.asarray(dr_base, dtype=float)
    T = len(dd)
    nz = np.abs(dd) > 1e-12
    n_diff = int(nz.sum())
    if n_diff < 2:
        return {"paired_t": 0.0, "paired_p_2sided": 1.0, "paired_perm_p_1sided": 0.5, "paired_perm_p_2sided": 1.0, "n_diff_days": n_diff}
    sd = float(np.std(dd, ddof=1))
    t_stat = float(np.mean(dd) / (sd / math.sqrt(T))) if sd > 1e-12 else 0.0
    p2_t = float(2.0 * stats.t.sf(abs(t_stat), df=T - 1)) if sd > 1e-12 else 1.0

    # Paired sign-flip permutation over non-zero diff days (mathematically equivalent to flipping all T days)
    nz_dd = dd[nz]
    obs_sum = float(np.sum(nz_dd))
    rng = np.random.default_rng(seed)
    signs = rng.choice([-1.0, 1.0], size=(n_perm, n_diff))
    perm_sums = signs @ nz_dd
    p1_perm = float((np.sum(perm_sums >= obs_sum - 1e-12) + 1) / (n_perm + 1))
    p2_perm = float((np.sum(np.abs(perm_sums) >= abs(obs_sum) - 1e-12) + 1) / (n_perm + 1))
    return {
        "paired_t": round(t_stat, 3),
        "paired_p_2sided": round(p2_t, 4),
        "paired_perm_p_1sided": round(p1_perm, 4),
        "paired_perm_p_2sided": round(p2_perm, 4),
        "n_diff_days": n_diff,
    }


def evaluate_d15_full(
    name: str,
    group: str,
    sim_res: dict,
    cache: dict,
    ref_dr_wf: Optional[np.ndarray] = None,
    ref_dr_5y: Optional[np.ndarray] = None,
    perm_n: int = 1000,
) -> dict:
    """Compute all 7 D15 windows (incl. second_mdd_pct), MTM verification, and 1000x permutation tests."""
    cal_5y = cache["cal_5y"]
    idx_5y = {d: i for i, d in enumerate(cal_5y)}
    bench = cache["bench_5y"]
    csi_5y = bench["csi300_daily_ret"].to_numpy(float)
    ew_5y = bench["alla_ew_daily_ret"].to_numpy(float)
    tr_df = sim_res["trades_df"]
    dr_5y = sim_res["dr_5y"]
    dr_wf = sim_res["dr_wf"]

    windows = {}
    for wn, sdt, edt in D15_WINDOWS:
        w = wfm._calc_one_window(tr_df, None, dr_5y, cal_5y, idx_5y, csi_5y, ew_5y, sdt, edt)
        pos = [idx_5y[d] for d in cal_5y if sdt <= d <= edt]
        _, dd2 = calc_top2_dd(dr_5y[pos])
        w["second_mdd_pct"] = dd2
        windows[wn] = w

    perm_wf = {"same_day_p_nav": np.nan, "any_cand_day_p_nav": np.nan}
    if perm_n > 0 and not tr_df.empty:
        tr_wf = tr_df[tr_df["buy_date"] >= eng.WF_START]
        perm_wf = wfm.perm_test_trading_days(tr_wf, cache["master_cand_perm"], eng.WF_START, eng.WF_END, n_perm=perm_n, seed=20261126)

    paired_wf = paired_perm_test(dr_wf, ref_dr_wf, n_perm=max(1000, perm_n)) if ref_dr_wf is not None else {}
    paired_5y = paired_perm_test(dr_5y, ref_dr_5y, n_perm=max(1000, perm_n)) if ref_dr_5y is not None else {}

    nav_5y = max(1.0, float(np.prod(1.0 + dr_5y)))
    nav_wf = max(1.0, float(np.prod(1.0 + dr_wf)))
    return {
        "name": name,
        "group": group,
        "mtm_diff_5y": float(sim_res["mtm_diff_5y"]),
        "mtm_rel_5y": float(sim_res["mtm_diff_5y"] / nav_5y),
        "mtm_diff_wf": float(sim_res["mtm_diff_wf"]),
        "mtm_rel_wf": float(sim_res["mtm_diff_wf"] / nav_wf),
        "n_waits": len(sim_res["waits"]),
        "windows": windows,
        "perm_wf": perm_wf,
        "paired_vs_ref_wf": paired_wf,
        "paired_vs_ref_5y": paired_5y,
    }


def run_dual_scissors_and_diff(
    tag: str,
    tr_new: pd.DataFrame,
    tr_base: pd.DataFrame,
    ev_new: dict,
    ev_base: dict,
) -> dict:
    """Audit added, removed, and modified-return trades + dual-scissors counterfactual (FULL_5Y & WF_2326)."""
    kb = {(str(r.buy_date)[:10], str(r.code).zfill(6), str(r.strategy)): r for r in tr_base.itertuples(index=False)}
    kn = {(str(r.buy_date)[:10], str(r.code).zfill(6), str(r.strategy)): r for r in tr_new.itertuples(index=False)}
    removed = [kb[k] for k in sorted(kb) if k not in kn]
    added = [kn[k] for k in sorted(kn) if k not in kb]
    modified = []
    for k in sorted(set(kb) & set(kn)):
        if abs(float(kn[k].net_ret) - float(kb[k].net_ret)) > 1e-6:
            modified.append((kb[k], kn[k]))

    def _calc_win(win_name: str, sdt: str) -> dict:
        rem_w = [r for r in removed if str(r.buy_date) >= sdt]
        add_w = [r for r in added if str(r.buy_date) >= sdt]
        mod_w = [(b, n) for b, n in modified if str(n.buy_date) >= sdt]
        n_new = ev_new["windows"][win_name]["nav"]
        n_base = ev_base["windows"][win_name]["nav"]
        sh_new = ev_new["windows"][win_name]["daily_sharpe"]
        sh_base = ev_base["windows"][win_name]["daily_sharpe"]
        mdd_new = ev_new["windows"][win_name]["daily_mdd_pct"]
        mdd_base = ev_base["windows"][win_name]["daily_mdd_pct"]
        raw_mult = n_new / max(1e-12, n_base)

        worst_rem = min(rem_w, key=lambda r: float(r.net_ret)) if rem_w else None
        best_add = max(add_w, key=lambda r: float(r.net_ret)) if add_w else None
        best_mod = max(mod_w, key=lambda p: (1.0 + float(p[1].net_ret)) / (1.0 + float(p[0].net_ret))) if mod_w else None

        cf_ex_worst_crowd = raw_mult * (1.0 + float(worst_rem.net_ret)) if (worst_rem and float(worst_rem.net_ret) < 0) else raw_mult
        cf_ex_best_add = raw_mult / (1.0 + float(best_add.net_ret)) if (best_add and float(best_add.net_ret) > 0) else raw_mult
        cf_ex_both = cf_ex_worst_crowd / (1.0 + float(best_add.net_ret)) if (best_add and float(best_add.net_ret) > 0) else cf_ex_worst_crowd
        mod_ratio = ((1.0 + float(best_mod[1].net_ret)) / (1.0 + float(best_mod[0].net_ret))) if best_mod else 1.0
        cf_ex_both_and_mod = cf_ex_both / max(1.0, mod_ratio)

        return {
            "nav_base": n_base, "nav_new": n_new, "raw_mult": round(raw_mult, 4),
            "d_sharpe": round(sh_new - sh_base, 3), "d_mdd_pp": round(mdd_new - mdd_base, 2),
            "n_added": len(add_w), "n_removed": len(rem_w), "n_modified": len(mod_w),
            "worst_crowded_loss": {"buy_date": worst_rem.buy_date, "code": worst_rem.code, "name": worst_rem.name, "strat": worst_rem.strategy, "ret_pct": round(float(worst_rem.net_ret) * 100.0, 2)} if worst_rem else None,
            "best_added_win": {"buy_date": best_add.buy_date, "code": best_add.code, "name": best_add.name, "strat": best_add.strategy, "ret_pct": round(float(best_add.net_ret) * 100.0, 2)} if best_add else None,
            "best_modified_win": {"buy_date": best_mod[1].buy_date, "code": best_mod[1].code, "name": best_mod[1].name, "strat": best_mod[1].strategy, "base_ret_pct": round(float(best_mod[0].net_ret) * 100.0, 2), "new_ret_pct": round(float(best_mod[1].net_ret) * 100.0, 2)} if best_mod else None,
            "mult_ex_worst_crowd": round(cf_ex_worst_crowd, 4),
            "mult_ex_best_add": round(cf_ex_best_add, 4),
            "mult_ex_both": round(cf_ex_both, 4),
            "mult_ex_both_and_mod": round(cf_ex_both_and_mod, 4),
        }

    diff_rows = []
    for r in removed:
        diff_rows.append({"tag": tag, "diff_type": "REMOVED", "buy_date": r.buy_date, "exit_date": r.exit_date, "strategy": r.strategy, "code": r.code, "name": r.name, "base_ret_pct": round(float(r.net_ret) * 100.0, 2), "new_ret_pct": np.nan, "delta_pp": round(-float(r.net_ret) * 100.0, 2)})
    for r in added:
        diff_rows.append({"tag": tag, "diff_type": "ADDED", "buy_date": r.buy_date, "exit_date": r.exit_date, "strategy": r.strategy, "code": r.code, "name": r.name, "base_ret_pct": np.nan, "new_ret_pct": round(float(r.net_ret) * 100.0, 2), "delta_pp": round(float(r.net_ret) * 100.0, 2)})
    for rb, rn in modified:
        diff_rows.append({"tag": tag, "diff_type": "MODIFIED", "buy_date": rn.buy_date, "exit_date": rn.exit_date, "strategy": rn.strategy, "code": rn.code, "name": rn.name, "base_ret_pct": round(float(rb.net_ret) * 100.0, 2), "new_ret_pct": round(float(rn.net_ret) * 100.0, 2), "delta_pp": round((float(rn.net_ret) - float(rb.net_ret)) * 100.0, 2)})

    return {"cf_5y": _calc_win("FULL_5Y", "2021-11-16"), "cf_wf": _calc_win("WF_2326", eng.WF_START), "diff_rows": diff_rows}


def simulate_margin_tier(
    sim_res: dict,
    cal_5y: list[str],
    bar_low_lu: dict,
    f5_low_lu: dict,
    elig_map: dict,
    mode: str,
    annual_rate: float = 0.055,
) -> dict:
    """
    4-tier margin accounting with 5.5% interest & intraday-LOW MMR:
      - L1_10x_Cash: 1.0x all trades
      - L2_15x_TheoFull: 1.5x all trades
      - L3_15x_EligOnly: 1.5x if T-1 official margin-eligible else 1.0x
      - L4_15x_BuwenSelective: 1.5x if (strategy in {1to2,2to3,high,4to5} and T-1 official eligible) else 1.0x
    """
    tr_df = sim_res["trades_df"]
    idx_5y = {d: i for i, d in enumerate(cal_5y)}
    T = len(cal_5y)
    day_mult_lev = np.ones(T, dtype=float)
    low_tail_strats = {"1to2", "2to3", "high", "4to5"}

    mmr_records = []
    n_elig = 0
    n_lev = 0
    lev_sum = 0.0

    for r in tr_df.itertuples(index=False):
        c6 = str(r.code).zfill(6)
        bd = str(r.buy_date)[:10]
        ed = str(r.exit_date)[:10]
        bi = idx_5y.get(bd)
        ei = idx_5y.get(ed)
        is_elig = bool(elig_map.get(f"{c6}|{bd}", False))
        if is_elig:
            n_elig += 1
        if mode == "L1_10x_Cash":
            L = 1.0
        elif mode == "L2_15x_TheoFull":
            L = 1.5
        elif mode == "L3_15x_EligOnly":
            L = 1.5 if is_elig else 1.0
        elif mode == "L4_15x_BuwenSelective":
            L = 1.5 if (is_elig and str(r.strategy) in low_tail_strats) else 1.0
        else:
            raise ValueError(f"Unknown margin mode: {mode}")

        if L > 1.0:
            n_lev += 1
        lev_sum += L

        cal_days = max(1, (pd.Timestamp(ed) - pd.Timestamp(bd)).days)
        interest_tot = (L - 1.0) * annual_rate * (cal_days / 365.0)
        net_ret_1x = float(r.net_ret)
        net_ret_L = L * net_ret_1x - interest_tot

        segs = getattr(r, "mtm_use", None)
        if bi is not None and ei is not None and ei > bi:
            if segs:
                v_curr, e_prev = 1.0, 1.0
                for ti, mult1x in segs:
                    if not (0 <= int(ti) < T):
                        continue
                    v_curr *= float(mult1x)
                    dt_t = cal_5y[int(ti)]
                    cd_t = max(0, (pd.Timestamp(dt_t) - pd.Timestamp(bd)).days)
                    int_t = (L - 1.0) * annual_rate * (cd_t / 365.0)
                    e_curr = max(1e-6, 1.0 + net_ret_L) if int(ti) == ei else max(1e-6, 1.0 + L * (v_curr - 1.0) - int_t)
                    day_mult_lev[int(ti)] *= (e_curr / e_prev)
                    e_prev = e_curr
            else:
                span = ei - bi + 1
                day_mult_lev[bi : ei + 1] *= (1.0 + max(-0.99, net_ret_L)) ** (1.0 / span)

        if L > 1.0 and bi is not None and ei is not None:
            bb = bar_low_lu.get((c6, bd))
            if pd.notna(getattr(r, "buy_price_val", np.nan)) and bb is not None:
                b_adj = float(r.buy_price_val) * bb[3]
            elif bb is not None:
                b_adj = bb[0]
            else:
                b_adj = np.nan

            if np.isfinite(b_adj) and b_adj > 0:
                min_mmr_trade, min_mmr_dt = 999.0, bd
                bh = int(getattr(r, "buy_hhmm", 925))
                eh = int(getattr(r, "exit_hhmm", 1500))
                for t in range(bi, min(ei + 1, T)):
                    dt_t = cal_5y[t]
                    bt = bar_low_lu.get((c6, dt_t))
                    if bt is None:
                        continue
                    if t == bi and bh > 925:
                        low_5m = f5_low_lu.get((c6, dt_t, "after", bh))
                        low_adj = (low_5m * bt[3]) if low_5m is not None else bt[1]
                    elif t == ei and eh <= 930:
                        low_adj = bt[0]
                    elif t == ei and eh < 1500:
                        low_5m = f5_low_lu.get((c6, dt_t, "before", eh))
                        low_adj = (low_5m * bt[3]) if low_5m is not None else bt[1]
                    else:
                        low_adj = bt[1]
                    asset_low = L * (low_adj / b_adj)
                    cd_t = max(1, (pd.Timestamp(dt_t) - pd.Timestamp(bd)).days)
                    debt_t = (L - 1.0) * (1.0 + annual_rate * (cd_t / 365.0))
                    mmr_t = (asset_low / debt_t) * 100.0 if debt_t > 0 else 999.0
                    if mmr_t < min_mmr_trade:
                        min_mmr_trade, min_mmr_dt = mmr_t, dt_t
                mmr_records.append({
                    "buy_date": bd, "exit_date": ed, "code": c6, "name": r.name,
                    "strategy": r.strategy, "net_ret_1x_pct": round(net_ret_1x * 100, 2),
                    "net_ret_lev_pct": round(net_ret_L * 100, 2),
                    "min_mmr_pct": round(min_mmr_trade, 2), "min_mmr_dt": min_mmr_dt,
                })

    dr_lev = day_mult_lev - 1.0
    mmr_df = pd.DataFrame(mmr_records)
    min_mmr_overall = float(mmr_df["min_mmr_pct"].min()) if not mmr_df.empty else 999.0
    n_warn_150 = int((mmr_df["min_mmr_pct"] < 150.0).sum()) if not mmr_df.empty else 0
    n_liq_130 = int((mmr_df["min_mmr_pct"] < 130.0).sum()) if not mmr_df.empty else 0
    worst_mmr_row = mmr_df.sort_values("min_mmr_pct").iloc[0].to_dict() if not mmr_df.empty else {}

    win_out = {}
    for wn, sdt, edt in D15_WINDOWS:
        pos = [i for i, d in enumerate(cal_5y) if sdt <= d <= edt]
        ds_w = dr_lev[pos]
        T_w = len(ds_w)
        nav = float(np.prod(1.0 + ds_w))
        mdd, dd2 = calc_top2_dd(ds_w)
        sd = float(np.std(ds_w, ddof=1)) if T_w > 1 else 0.0
        sh = float(np.mean(ds_w) / sd * math.sqrt(eng.TRD_DAYS_YEAR)) if sd > 1e-12 else 0.0
        cagr = (nav ** (eng.TRD_DAYS_YEAR / T_w) - 1.0) * 100.0 if nav > 0 else -100.0
        calmar = (cagr / mdd) if mdd > 1e-6 else 0.0
        win_out[wn] = {
            "nav": round(nav, 4), "mdd_pct": mdd, "second_mdd_pct": dd2,
            "sharpe": round(sh, 3), "calmar": round(calmar, 2), "cagr_pct": round(cagr, 2),
        }

    return {
        "mode": mode,
        "n_trades": int(len(tr_df)),
        "n_eligible": int(n_elig),
        "n_leveraged": int(n_lev),
        "elig_pct": round(n_elig / max(1, len(tr_df)) * 100.0, 2),
        "lev_pct": round(n_lev / max(1, len(tr_df)) * 100.0, 2),
        "avg_eff_leverage": round(lev_sum / max(1, len(tr_df)), 3),
        "min_mmr_pct": round(min_mmr_overall, 2),
        "n_warn_below_150": n_warn_150,
        "n_liq_below_130": n_liq_130,
        "worst_mmr_trade": worst_mmr_row,
        "windows": win_out,
        "dr_lev": dr_lev,
    }

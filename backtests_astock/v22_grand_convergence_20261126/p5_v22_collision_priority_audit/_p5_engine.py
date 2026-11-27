#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
_p5_engine.py — V22.0 Pillar 5 Shared Core:
  - Builds exact Pure_V21_P2_SJ114_E4 (7-strategy: 3to4, high, pry, 2to3, 1to2, 20cm S>=80, 4to5 SJ114_E4_DtDefer)
    in both Primary (pool6 + ut_df + 4to5_raw, matching V22 engine SSOT) and CrossCheck (pass_top1 + ut_df + 4to5_raw).
  - Assigns fine-grained physical sub-buckets for exhaustive permutation & three-tier testing.
  - Ultra-fast exact causal single-slot simulator + exact MTM + 7-window D15 + Dual-Scissors + 1000x paired perm.
Zero yfinance (D12). Read-only on V20/V21/RD038/RD049/P2/P3.
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import math
import pickle
import sys
from typing import Callable, Optional

import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 VIOLATION"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
RD038 = f"{SIM}/backtests_astock2/rd038_grand_bundle_assembly_20261126"
RD049 = f"{SIM}/backtests_astock2/rd049_traffic_light_granular_20261126"
P2 = f"{SIM}/backtests_astock/v22_grand_convergence_20261126/p2_rd049_falsekill_audit"
P3 = f"{SIM}/backtests_astock/v22_grand_convergence_20261126/p3_v22_grand_assembly"
P5 = f"{SIM}/backtests_astock/v22_grand_convergence_20261126/p5_v22_collision_priority_audit"

for p in (RD038, RD049, P2, P3):
    if p not in sys.path:
        sys.path.insert(0, p)

import _v22_engine as v22

ALL7 = ["3to4", "high", "pry", "2to3", "1to2", "20cm", "4to5"]


def load_p5_raw_assets() -> dict:
    """Load RD038 cache, RD049 regime, and DirB SJ114_E4_DtDefer full ledgers."""
    with open(f"{RD038}/_cache/rd038_master_cache.pkl", "rb") as f:
        cache_base = pickle.load(f)
    reg = pd.read_parquet(f"{RD049}/_cache/rd049_daily_regime_pit.parquet")
    reg_idx = v22.cm49.build_2d_states(reg, y_cut=42.0, x_sh=20.0, x_dp=42.0).set_index("trade_date")
    with open(f"{P3}/_cache/v22_dirb_ledgers_full.pkl", "rb") as f:
        dirb = pickle.load(f)["ledgers"]
    c_p2 = v22.apply_v22_modifications(cache_base, reg_idx, use_p2=True, use_dirA=False)
    return {
        "cache_base": cache_base,
        "c_p2": c_p2,
        "reg_idx": reg_idx,
        "raw_4to5": dirb["SJ114_E4_DtDefer"]["raw"].copy(),
        "slot_4to5": dirb["SJ114_E4_DtDefer"]["slot"].copy(),
    }


def _assign_fine_bucket(row) -> str:
    st = str(row.strategy)
    sc = float(row.score)
    hh = int(row.buy_hhmm)
    if st == "3to4":
        if sc >= 106.0:
            return "3to4_S106_925" if hh == 925 else "3to4_S106_cond"
        if sc >= 102.0:
            return "3to4_S102_105_925" if hh == 925 else "3to4_S102_105_cond"
        return "3to4_A_925" if hh == 925 else "3to4_A_cond"
    if st == "high":
        if sc >= 96.0:
            return "high_S_925" if hh == 925 else "high_S_cond"
        return "high_A_925" if hh == 925 else "high_A_cond"
    if st == "pry":
        return "pry_S" if sc >= 175.0 else "pry_A"
    if st == "2to3":
        return "2to3_S" if sc >= 96.0 else "2to3_A"
    if st == "1to2":
        if hh == 925:
            return "1to2_925_S" if sc >= 340.0 else "1to2_925_A"
        if sc >= 340.0:
            return "1to2_cond_S"
        if sc >= 304.8:
            return "1to2_cond_A"
        return "1to2_cond_FB"
    if st == "20cm":
        return "20cm_S86" if sc >= 86.0 else "20cm_80_85"
    if st == "4to5":
        return "4to5_S120" if sc >= 120.0 else "4to5_114_119"
    raise ValueError(f"Unknown strategy: {st}")


def _build_pass_top1_pool6(c_p2: dict, fee_mode: str = "030") -> tuple[pd.DataFrame, pd.DataFrame]:
    """Cross-check pool: daily top-1 passing candidates per strategy WITHOUT standalone single-slot pre-occlusion."""
    pools_ext = c_p2["pools_ext"]
    ut_raw = c_p2["ut_full_raw"]
    o5 = c_p2["other5_variants"]
    sc20 = c_p2["sc20_aligned"]
    cfg = v22.CFG_V21
    cm = v22.eng.cm
    tpe = v22.eng.tpe
    parts = []
    trig_dts = {}

    for st in cm.ALL6:
        df = pools_ext[st].copy()
        rc, mc, _ = v22.eng._fee_cols(fee_mode, st)
        df["net_ret"] = df[rc]
        df["mtm_use"] = df[mc]
        if st == "20cm":
            sv = np.where(
                df["buy_date"] < v22.eng.WF_START,
                np.where(df["orig_score"].to_numpy(float) >= 82.0, df["orig_score"].to_numpy(float), -999.0),
                sc20[cfg["s20"]],
            )
            m = df["can_buy_hygiene"].fillna(True).to_numpy(bool) & np.isfinite(sv) & (sv >= float(cfg.get("s20_thr", 80.0)))
            p_df = df[m].copy()
            p_df["score"] = sv[m].astype(float)
            p_df = p_df.sort_values(["buy_date", "score", "code"], ascending=[True, False, True], kind="mergesort").groupby("buy_date", as_index=False).first()
            p_df["tier"] = "20cm_S(>=82)"
        else:
            vkey = {"3to4": cfg["s34"], "2to3": cfg["s23"], "high": cfg["shi"], "pry": cfg["spr"], "1to2": cfg["s12"]}[st]
            if vkey == "base":
                p_df, _ = cm.sim_strategy(st, df, df["orig_score"].to_numpy(float), wf_only=False)
                sc_arr = p_df["orig_score"].to_numpy(float)
            else:
                vcfg = o5[st][vkey]
                p_df, _ = cm.sim_strategy(st, df, vcfg["score"], mask=vcfg["mask"], wf_only=False)
                sc_arr = p_df["_sc_adj"].to_numpy(float) if "_sc_adj" in p_df.columns else p_df["orig_score"].to_numpy(float)
            p_df["score"] = [round(float(x), 1) for x in sc_arr] if st == "1to2" else sc_arr.astype(float)
            if st == "3to4":
                pt = pd.to_numeric(p_df["prio_tie"], errors="coerce").fillna(0.0).to_numpy(float)
                p_df["_prio"] = p_df["score"] * 10.0 + pt * 0.1
                p_df = p_df.sort_values(["buy_date", "buy_hhmm", "_prio", "code"], ascending=[True, True, False, True], kind="mergesort").groupby("buy_date", as_index=False).first()
            elif st == "pry":
                b10 = pd.to_numeric(p_df["bias10"], errors="coerce").fillna(0.0).to_numpy(float) if "bias10" in p_df.columns else np.zeros(len(p_df))
                p_df["_b10"] = b10
                p_df = p_df.sort_values(["buy_date", "score", "_b10", "code"], ascending=[True, False, True, True], kind="mergesort").groupby("buy_date", as_index=False).first()
            elif st == "2to3":
                p_df = p_df.sort_values(["buy_date", "score", "open_pct", "plate_sz", "code"], ascending=[True, False, True, True, True], kind="mergesort").groupby("buy_date", as_index=False).first()
            elif st == "high":
                p_df = p_df.sort_values(["buy_date", "score", "code"], ascending=[True, False, True], kind="mergesort").groupby("buy_date", as_index=False).first()
            elif st == "1to2":
                p_df = p_df.sort_values(["buy_date", "_sv", "code"], ascending=[True, False, True], kind="mergesort").groupby("buy_date", as_index=False).first()
            p_df["tier"] = [tpe.assign_physical_tier(st, sc) for sc in p_df["score"]]

        p_df = p_df[p_df["buy_date"].between("2021-11-16", v22.eng.WF_END)].copy()
        p_df["strategy"] = st
        p_df["is_untrig"] = False
        if "buy_price_val" not in p_df.columns:
            p_df["buy_price_val"] = pd.to_numeric(p_df.get("buy_price", np.nan), errors="coerce")
        if "is_adj_px" not in p_df.columns:
            p_df["is_adj_px"] = False
        trig_dts[st] = set(p_df["buy_date"])
        keep_cols = [
            "buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name",
            "strategy", "tier", "score", "net_ret", "mtm_use", "buy_price_val", "is_adj_px", "is_untrig",
        ]
        parts.append(p_df[keep_cols])

    pool6 = pd.concat(parts, ignore_index=True)
    ut_parts = []
    for st_u in ("3to4", "high", "1to2"):
        sub_u = ut_raw[(ut_raw["strategy"] == st_u) & (~ut_raw["buy_date"].isin(trig_dts.get(st_u, set())))].copy()
        thr_u = {"3to4": 90.0, "high": 88.0, "1to2": 0.0}[st_u]
        sub_u = sub_u[sub_u["score"] >= thr_u].sort_values(["buy_date", "score", "code"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()
        if not sub_u.empty:
            sub_u["tier"] = [tpe.assign_physical_tier(st_u, sc) for sc in sub_u["score"]]
            ut_parts.append(sub_u)
    ut_df = pd.concat(ut_parts, ignore_index=True) if ut_parts else pd.DataFrame()
    if not ut_df.empty:
        ut_df["is_untrig"] = True
        ut_df["net_ret"] = 0.0
        ut_df["mtm_use"] = [() for _ in range(len(ut_df))]
        ut_df["buy_price_val"] = np.nan
        ut_df["is_adj_px"] = False
        ut_df = ut_df[["buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name", "strategy", "tier", "score", "net_ret", "mtm_use", "buy_price_val", "is_adj_px", "is_untrig"]]
    return pool6, ut_df


def build_p5_master_pool(c_p2: dict, raw_4to5: pd.DataFrame, fee_mode: str = "030", use_pass_top1: bool = False) -> pd.DataFrame:
    """
    Build unified 7-strategy + untriggered conditional pool for Pure_V21_P2_SJ114_E4.
    `use_pass_top1=False` (Primary SSOT) uses `eng.build_bundle_pools` + `raw_4to5`.
    """
    cal_5y = c_p2["cal_5y"]
    idx_5y = {d: i for i, d in enumerate(cal_5y)}
    if use_pass_top1:
        pool6, ut_df = _build_pass_top1_pool6(c_p2, fee_mode=fee_mode)
    else:
        pool6, ut_df = v22.eng.build_bundle_pools(c_p2, v22.CFG_V21, fee_mode=fee_mode)

    ep45 = v22.prepare_4to5_pool(raw_4to5, "Pos5", fee_mode, cal_5y, "4to5_SJ114_E4_DtDefer")
    keep_cols = [
        "buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name",
        "strategy", "tier", "score", "net_ret", "mtm_use", "buy_price_val", "is_adj_px", "is_untrig",
    ]
    parts = [pool6[keep_cols]]
    if not ut_df.empty:
        parts.append(ut_df[keep_cols])
    if not ep45.empty:
        parts.append(ep45[keep_cols])
    df = pd.concat(parts, ignore_index=True)
    df["buy_date"] = df["buy_date"].astype(str).str[:10]
    df["exit_date"] = df["exit_date"].astype(str).str[:10]
    df["buy_hhmm"] = pd.to_numeric(df["buy_hhmm"], errors="coerce").fillna(925).astype(int)
    df["exit_hhmm"] = pd.to_numeric(df["exit_hhmm"], errors="coerce").fillna(1500).astype(int)
    df["code"] = df["code"].astype(str).str.zfill(6)
    df["score"] = pd.to_numeric(df["score"], errors="coerce").astype(float)
    df["net_ret"] = pd.to_numeric(df["net_ret"], errors="coerce").astype(float)
    df["is_untrig"] = df["is_untrig"].astype(bool)
    df["bucket"] = [_assign_fine_bucket(r) for r in df.itertuples(index=False)]
    df["s2c_prio"] = df["tier"].map(v22.eng.m1.S2C_MAP).fillna(999).astype(int)
    return df.reset_index(drop=True)


def run_priority_sim(
    master_df: pd.DataFrame,
    bucket_rank_fn: Callable[[pd.DataFrame], np.ndarray],
    cal_5y: list[str],
    allow_untrig: bool = True,
) -> dict:
    """
    Fast, exact causal single-slot simulation given an integer priority rank vector per row.
    Rows with rank >= 9000 are excluded. Within same (buy_date, rank), tie-break by score desc, buy_hhmm asc, code asc.
    """
    df = master_df if allow_untrig else master_df[~master_df["is_untrig"]]
    ranks = np.asarray(bucket_rank_fn(df), dtype=int)
    keep = ranks < 9000
    sub = df[keep].copy()
    sub["_rk"] = ranks[keep]
    sub = sub.sort_values(
        ["buy_date", "_rk", "score", "buy_hhmm", "code"],
        ascending=[True, True, False, True, True],
        kind="mergesort",
    ).reset_index(drop=True)

    # Convert to pure python tuple list grouped by date for microsecond loop speed
    by_dt = {}
    cols = ["buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name", "strategy", "tier", "bucket", "score", "net_ret", "mtm_use", "is_untrig", "_rk"]
    recs = list(sub[cols].itertuples(index=False, name="Row"))
    for r in recs:
        by_dt.setdefault(r.buy_date, []).append(r)

    taken = []
    waits = []
    cur_ed, cur_eh = "", 0
    for dt in cal_5y:
        grp = by_dt.get(dt)
        if not grp:
            continue
        for r in grp:
            if (not cur_ed) or (r.buy_date > cur_ed) or (r.buy_date == cur_ed and r.buy_hhmm > cur_eh):
                if r.is_untrig:
                    waits.append({
                        "buy_date": r.buy_date, "strategy": r.strategy, "tier": r.tier,
                        "bucket": r.bucket, "code": r.code, "name": r.name,
                        "score": float(r.score), "cancel_hhmm": int(r.exit_hhmm),
                    })
                else:
                    taken.append(r)
                cur_ed, cur_eh = r.exit_date, int(r.exit_hhmm)
                break

    T = len(cal_5y)
    idx_5y = {d: i for i, d in enumerate(cal_5y)}
    day_mult = np.ones(T, dtype=float)
    for r in taken:
        segs = r.mtm_use
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
    tr_df = pd.DataFrame([{
        "buy_date": r.buy_date, "buy_hhmm": r.buy_hhmm, "exit_date": r.exit_date, "exit_hhmm": r.exit_hhmm,
        "code": r.code, "name": r.name, "strategy": r.strategy, "tier": r.tier, "bucket": r.bucket,
        "score": r.score, "net_ret": r.net_ret, "mtm_use": r.mtm_use,
    } for r in taken])

    nav_5y_tr = float(np.prod(1.0 + tr_df["net_ret"].to_numpy(float))) if not tr_df.empty else 1.0
    mtm_diff_5y = abs(float(np.prod(day_mult)) - nav_5y_tr)
    wf_off = idx_5y[v22.eng.WF_START]
    dr_wf = dr_5y[wf_off:]
    tr_wf = tr_df[tr_df["buy_date"] >= v22.eng.WF_START] if not tr_df.empty else tr_df
    nav_wf_tr = float(np.prod(1.0 + tr_wf["net_ret"].to_numpy(float))) if not tr_wf.empty else 1.0
    mtm_diff_wf = abs(float(np.prod(1.0 + dr_wf)) - nav_wf_tr)

    if not tr_df.empty:
        assert (tr_df["exit_date"] > tr_df["buy_date"]).all(), "T+0 violation"
        for i in range(1, len(tr_df)):
            p, c = tr_df.iloc[i - 1], tr_df.iloc[i]
            assert (c["buy_date"], int(c["buy_hhmm"])) > (p["exit_date"], int(p["exit_hhmm"])), f"Overlap at {i}"

    return {
        "trades_df": tr_df,
        "waits": waits,
        "dr_5y": dr_5y,
        "dr_wf": dr_wf,
        "mtm_diff_5y": mtm_diff_5y,
        "mtm_diff_wf": mtm_diff_wf,
    }


def make_bucket_rank_fn(bucket_map: dict[str, int]) -> Callable[[pd.DataFrame], np.ndarray]:
    def _fn(df: pd.DataFrame) -> np.ndarray:
        return df["bucket"].map(bucket_map).fillna(9999).to_numpy(dtype=int)
    return _fn


def make_engine_s2c_rank_fn(map_4to5: dict[str, int]) -> Callable[[pd.DataFrame], np.ndarray]:
    """
    Exact replication of _v22_engine.py (`S2C_MAP` + `phase` + `empty_fill`), where:
      - phase 0 (`09:25` OR `3to4_S>=102` OR `high_S>=96`): rank = s2c_prio (1..6)
      - phase 1 (other `>925` conditional orders): rank = 100 + s2c_prio
      - 4to5 buckets mapped via `map_4to5` (e.g. {'4to5_S120': 900, '4to5_114_119': 900} for Pos5).
    """
    def _fn(df: pd.DataFrame) -> np.ndarray:
        is_45 = (df["strategy"] == "4to5").to_numpy(bool)
        is_s_cond = df["tier"].isin(["3to4_S(>=102)", "high_S(>=96)"]).to_numpy(bool)
        is_p0 = (df["buy_hhmm"].to_numpy(int) == 925) | is_s_cond
        s2c_p = df["s2c_prio"].to_numpy(int)
        base_rk = np.where(is_p0, s2c_p, 100 + s2c_p)
        rk45 = df["bucket"].map(map_4to5).fillna(9999).to_numpy(int)
        return np.where(is_45, rk45, base_rk)
    return _fn


def eval_fast_windows(sim_res: dict, cache: dict) -> dict:
    """Fast 7-window metrics without running slow 1000x day permutation (for screening)."""
    cal_5y = cache["cal_5y"]
    idx_5y = {d: i for i, d in enumerate(cal_5y)}
    bench = cache["bench_5y"]
    csi_5y = bench["csi300_daily_ret"].to_numpy(float)
    ew_5y = bench["alla_ew_daily_ret"].to_numpy(float)
    tr_df = sim_res["trades_df"]
    dr_5y = sim_res["dr_5y"]
    out = {}
    for wn, sdt, edt in v22.D15_WINDOWS:
        w = v22.wfm._calc_one_window(tr_df, None, dr_5y, cal_5y, idx_5y, csi_5y, ew_5y, sdt, edt)
        pos = [idx_5y[d] for d in cal_5y if sdt <= d <= edt]
        _, dd2 = v22.calc_top2_dd(dr_5y[pos])
        w["second_mdd_pct"] = dd2
        out[wn] = w
    return out


def calc_window_dual_scissors(tr_new: pd.DataFrame, tr_base: pd.DataFrame, w_new: dict, w_base: dict, win_name: str, sdt: str, edt: str) -> dict:
    """Exact dual-scissors counterfactual on ANY window [sdt..edt]."""
    tb = tr_base[tr_base["buy_date"].between(sdt, edt)] if not tr_base.empty else tr_base
    tn = tr_new[tr_new["buy_date"].between(sdt, edt)] if not tr_new.empty else tr_new
    kb = {(str(r.buy_date)[:10], str(r.code).zfill(6), str(r.strategy)): r for r in tb.itertuples(index=False)}
    kn = {(str(r.buy_date)[:10], str(r.code).zfill(6), str(r.strategy)): r for r in tn.itertuples(index=False)}
    rem = [kb[k] for k in sorted(kb) if k not in kn]
    add = [kn[k] for k in sorted(kn) if k not in kb]

    n_new = float(w_new[win_name]["nav"])
    n_base = float(w_base[win_name]["nav"])
    raw_mult = n_new / max(1e-12, n_base)
    worst_rem = min(rem, key=lambda r: float(r.net_ret)) if rem else None
    best_add = max(add, key=lambda r: float(r.net_ret)) if add else None

    cf_ex_worst_crowd = raw_mult * (1.0 + float(worst_rem.net_ret)) if (worst_rem and float(worst_rem.net_ret) < 0) else raw_mult
    cf_ex_best_add = raw_mult / (1.0 + float(best_add.net_ret)) if (best_add and float(best_add.net_ret) > 0) else raw_mult
    cf_ex_both = cf_ex_worst_crowd / (1.0 + float(best_add.net_ret)) if (best_add and float(best_add.net_ret) > 0) else cf_ex_worst_crowd

    return {
        "raw_mult": round(raw_mult, 4),
        "n_added": len(add),
        "n_removed": len(rem),
        "worst_crowded": {"buy_date": worst_rem.buy_date, "code": worst_rem.code, "name": worst_rem.name, "strat": worst_rem.strategy, "ret_pct": round(float(worst_rem.net_ret) * 100.0, 2)} if worst_rem else None,
        "best_added": {"buy_date": best_add.buy_date, "code": best_add.code, "name": best_add.name, "strat": best_add.strategy, "ret_pct": round(float(best_add.net_ret) * 100.0, 2)} if best_add else None,
        "mult_ex_worst_crowd": round(cf_ex_worst_crowd, 4),
        "mult_ex_best_add": round(cf_ex_best_add, 4),
        "mult_ex_both": round(cf_ex_both, 4),
    }

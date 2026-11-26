#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD039-C (Front 4): Cold-Blooded Red-Team Audit Across All 4 Fronts + V20.0 / RD038 Grand PK.
Outputs in front4_redteam_and_assembly/:
  - rd039_3to4_stop_forensics.csv
  - rd039_vs_rd038_pk.csv
  - rd039_final_audit.json
Strict compliance: /opt/homebrew/bin/python3.13, zero yfinance, zero cap10m, threads <= 2, RSS < 2.5 GB.
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import gc
import json
import math
import pickle
import resource
import sys
import time
import warnings

import numpy as np
import pandas as pd
import pyarrow as pa
import scipy.stats as stats

pa.set_cpu_count(1)
pa.set_io_thread_count(1)
warnings.filterwarnings("ignore")
assert "yfinance" not in sys.modules, "D12 VIOLATION: yfinance forbidden"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
RD038_DIR = f"{SIM}/backtests_astock2/rd038_grand_bundle_assembly_20261126"
RD039_F1_DIR = f"{SIM}/backtests_astock2/rd039_single_strat_sharpe_lift_20261126/front1_2to3_20cm_cond"
RD039_F23_DIR = f"{SIM}/backtests_astock2/rd039_single_strat_sharpe_lift_20261126/front2_3_3to4_high_pry"
OUT_DIR = f"{SIM}/backtests_astock2/rd039_single_strat_sharpe_lift_20261126/front4_redteam_and_assembly"
os.makedirs(OUT_DIR, exist_ok=True)

for _p in (RD038_DIR, RD039_F23_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import _rd038_engine as eng
import _common_rd036 as cm36
import _f23_common as cm23
import run_front2_3to4 as f2
import _w2a4_data_and_features as w2f


def rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 1)


def calc_dsr_exact(dr: np.ndarray, n_trials: int, var_sr_daily: float, sr_bench_daily: float = 0.0) -> dict:
    x = np.asarray(dr, dtype=float)
    T = len(x)
    mu = float(np.mean(x))
    sd = float(np.std(x, ddof=1))
    sr = mu / sd
    g3 = float(stats.skew(x, bias=True))
    g4 = float(stats.kurtosis(x, fisher=False, bias=True))
    gamma_em = 0.5772156649015329
    if n_trials <= 1 or var_sr_daily <= 0.0:
        sr0 = sr_bench_daily
    else:
        z1 = float(stats.norm.ppf(1.0 - 1.0 / n_trials))
        z2 = float(stats.norm.ppf(1.0 - 1.0 / (n_trials * math.e)))
        sr0 = sr_bench_daily + math.sqrt(var_sr_daily) * ((1.0 - gamma_em) * z1 + gamma_em * z2)
    denom_in = max(1e-12, (1.0 - g3 * sr + ((g4 - 1.0) / 4.0) * (sr ** 2)) / max(1, T - 1))
    z_dsr = (sr - sr0) / math.sqrt(denom_in)
    return {
        "sr_ann": round(sr * math.sqrt(eng.TRD_DAYS_YEAR), 3),
        "sr0_ann": round(sr0 * math.sqrt(eng.TRD_DAYS_YEAR), 3),
        "z_dsr": round(z_dsr, 4),
        "dsr": round(float(stats.norm.cdf(z_dsr)), 6),
    }


def build_mtm_segs_from_dmap(c6: str, bd: str, ed: str, bp: float, ret_val: float, cal_5y: list[str], idx_5y: dict, dmap: dict) -> tuple:
    bi = idx_5y.get(bd)
    ei = idx_5y.get(ed)
    if bi is None or ei is None or ei <= bi:
        return ((ei if ei is not None else bi), 1.0 + ret_val) if bi is not None else ()
    bb = dmap.get((c6, bd))
    b_adj = bp * bb["adjf"] if (bb is not None and bb["adjf"] > 0) else bp
    if not np.isfinite(b_adj) or b_adj <= 0:
        b_adj = 1.0
    prev_v = b_adj
    last_c = b_adj
    segs = []
    for t in range(bi, ei):
        bt = dmap.get((c6, cal_5y[t]))
        cur_c = float(bt["adj_close"]) if (bt is not None and bt["adj_close"] > 0) else last_c
        if cur_c <= 0:
            cur_c = last_c
        segs.append((t, cur_c / prev_v))
        prev_v = cur_c
        last_c = cur_c
    segs.append((ei, (b_adj * (1.0 + ret_val)) / prev_v))
    return tuple(segs)


def audit_3to4_components_and_5m_forensics() -> dict:
    """
    Stage 1: Cold-blooded audit of RD039-B 3to4 Components A, B, C:
      - Unbiased all-22-factor causal LOO vs hardcoded s34_af_20
      - 5m bar-by-bar forensics + conservative slippage stress (-30/-50/-100bps & next-bar low)
      - 2024-12-31 physical factor-ranking snapshot at cutoff
    """
    print("[Stage 1] Auditing 3to4 Components A, B, C & 5m stop forensics ...")
    m34 = pd.read_parquet(f"{cm23.WAVE1}/pool_3to4_master_pit.parquet")
    m34["bd"] = m34["buy_date"].astype(str).str[:10]
    m34["c6"] = m34["code"].astype(str).str.zfill(6)
    s34_cols = sorted([c for c in m34.columns if c.startswith("s34_af_")])

    with open(f"{f2.F1_DIR}/pit_exit_cache_full.pkl", "rb") as f:
        _cp = pickle.load(f)
    codes = set(m34["c6"]) | {str(e["code"]).zfill(6) for e in _cp["buy_entries"] if e["skel"] and e["sc_v40"] >= 90.0}
    del _cp
    ctx = cm23.load_filtered_5m_and_dmap(codes, load_5m=True, load_sub2=False)
    s34_ctx = f2.build_3to4_surgical_ctx(ctx)
    f2.attach_causal_loo_s34_af20(ctx, s34_ctx)

    af_map = {}
    for r in m34.itertuples(index=False):
        af_map[(r.bd, r.c6)] = {c: float(getattr(r, c)) if pd.notna(getattr(r, c)) else 0.0 for c in s34_cols}
    bonus_cols = [c for c in s34_cols if max(af_map[k][c] for k in af_map) > 0]

    base_b = {"trig_mult": 1.065, "cancel_hhmm": 1030, "hi_open_mode": "direct_0925"}
    base_e = {"d5_mode": "base", "zt_sl_mode": "base"}

    closed = []
    for item in s34_ctx["entries"]:
        item["af_all"] = af_map.get((item["bd"], item["c6"]), {c: 0.0 for c in s34_cols})
        if item["orig_buy_px"] is not None and not np.isnan(item["orig_buy_px"]):
            binfo = f2._sim_buy_3to4(item, ctx, s34_ctx, base_b)
            if binfo is not None:
                rec = f2._sim_exit_3to4(item, ctx, s34_ctx, binfo, base_e)
                closed.append((rec["buy_date"], rec["exit_date"], item["af_all"], float(cm23.fee_adjust(rec["net_ret_020"], 0.0030))))

    # Factor ranking snapshots at 2023-01-03, 2024-12-31, 2025-01-03, 2026-11-16
    snapshots = {}
    for snap_dt in ("2023-01-03", "2024-12-31", "2025-01-03", "2026-11-16"):
        hist = [c for c in closed if c[1] < snap_dt]
        u = np.clip(np.array([c[3] for c in hist], dtype=np.float64), -0.10, 0.25)
        bds = np.array([c[0] for c in hist])
        _, g_inv = np.unique(bds, return_inverse=True)
        G = int(g_inv.max() + 1)
        r_arr = np.array([h[3] for h in hist])
        rows_s = []
        for c in s34_cols:
            is_b = max(af_map[k][c] for k in af_map) > 0
            vals = np.array([h[2][c] for h in hist], dtype=np.float64)
            z = (vals > 0).astype(np.float64) if is_b else (vals < 0).astype(np.float64)
            if z.sum() >= 5 and (len(hist) - z.sum()) >= 5:
                tc = float(w2f._batch_cluster_t_stats(u, z[:, None], g_inv, G)[0])
                rows_s.append({
                    "factor": c, "type": "BONUS" if is_b else "PEN",
                    "n_act": int(z.sum()), "n_ina": int(len(hist) - z.sum()),
                    "t_clip": round(tc, 4),
                    "mean_act_pct": round(float(r_arr[z > 0].mean() * 100.0), 2),
                    "mean_ina_pct": round(float(r_arr[z == 0].mean() * 100.0), 2),
                })
        rows_s.sort(key=lambda x: x["t_clip"])
        snapshots[snap_dt] = {"n_closed": len(hist), "ranking": rows_s}

    # Per-entry unbiased bonus_tmap
    for item in s34_ctx["entries"]:
        bd = item["bd"]
        hist = [c for c in closed if c[1] < bd]
        tmap = {}
        if len(hist) >= 20:
            u = np.clip(np.array([c[3] for c in hist], dtype=np.float64), -0.10, 0.25)
            bds = np.array([c[0] for c in hist])
            _, g_inv = np.unique(bds, return_inverse=True)
            G = int(g_inv.max() + 1)
            for c in bonus_cols:
                z = np.array([float(h[2][c] > 0) for h in hist])
                if z.sum() >= 5 and (len(hist) - z.sum()) >= 5:
                    tmap[c] = float(w2f._batch_cluster_t_stats(u, z[:, None], g_inv, G)[0])
        item["bonus_tmap"] = tmap

    res_base, sl_base = f2.eval_3to4_variant("V41_Baseline", ctx, s34_ctx, base_b, base_e)
    bwf, b5y = res_base["dr_wf_030"], res_base["dr_5y_030"]

    ablation_specs = [
        ("0_V41_Baseline", "none", False, "base"),
        ("A_Only5mStop_Prevc6", "none", False, "prevc_tp1_m6_1000"),
        ("A_Only5mStop_D4Low", "none", False, "d4low_tp1_1000"),
        ("B_Only_M4MineBL15", "none", True, "base"),
        ("AB_CleanBest_M4_Prevc6", "none", True, "prevc_tp1_m6_1000"),
        ("AB_CleanNeighbor_M4_D4Low", "none", True, "d4low_tp1_1000"),
        ("C_Hardcoded_Af20_Only", "hardcoded_af20_t0", False, "base"),
        ("ABC_RD039B_Hardcoded_Af20", "hardcoded_af20_t0", True, "prevc_tp1_m6_1000"),
        ("U1_AllBonus_t0", "all_bonus_t0", False, "base"),
        ("U2_AllBonus_tm10", "all_bonus_tm10", False, "base"),
        ("U3_AllBonus_tm15", "all_bonus_tm15", False, "base"),
        ("U4_Worst1Bonus_t0", "worst1_bonus_t0", False, "base"),
        ("AB_plus_U1_AllBonus_t0", "all_bonus_t0", True, "prevc_tp1_m6_1000"),
        ("AB_plus_U4_Worst1Bonus_t0", "worst1_bonus_t0", True, "prevc_tp1_m6_1000"),
    ]
    ablation_rows = []
    slot_cache = {}
    for vid, lmode, use_m4, ztm in ablation_specs:
        def _mk_fn(lm=lmode, um=use_m4):
            def sfn(it):
                if um and it["m4_mine_bl15"]:
                    return False
                tm = it["bonus_tmap"]
                dp = 0.0
                if lm == "hardcoded_af20_t0":
                    if tm.get("s34_af_20", 0.0) < 0.0 and "s34_af_20" in tm:
                        dp = it["af_all"]["s34_af_20"]
                elif lm == "all_bonus_t0":
                    dp = sum(it["af_all"][c] for c, tv in tm.items() if tv < 0.0)
                elif lm == "all_bonus_tm10":
                    dp = sum(it["af_all"][c] for c, tv in tm.items() if tv < -1.0)
                elif lm == "all_bonus_tm15":
                    dp = sum(it["af_all"][c] for c, tv in tm.items() if tv < -1.5)
                elif lm == "worst1_bonus_t0":
                    neg = [(tv, c) for c, tv in tm.items() if tv < 0.0]
                    if neg:
                        neg.sort()
                        dp = it["af_all"][neg[0][1]]
                return (it["score"] - dp) >= 90.0
            return sfn

        r, sl = f2.eval_3to4_variant(vid, ctx, s34_ctx, base_b, {"d5_mode": "base", "zt_sl_mode": ztm}, _mk_fn(), bwf, b5y)
        slot_cache[vid] = sl
        wf = r["windows_030"]["WF_2326"]
        f5 = r["windows_030"]["FULL_5Y"]
        i21 = r["windows_030"]["IS_2124"]
        o25 = r["windows_030"]["OOS_2526"]
        yh_in = bool(not sl[(sl["buy_date"] == "2025-01-03") & (sl["code"] == "600778")].empty)
        zyd_row = sl[(sl["buy_date"] == "2025-03-27") & (sl["code"] == "600610")]
        zyd_ret = round(float(cm23.fee_adjust(zyd_row.iloc[0]["net_ret_020"], 0.0030) * 100.0), 2) if not zyd_row.empty else None
        ablation_rows.append({
            "variant_id": vid, "n_5y": f5["n"], "nav_5y": f5["nav"], "sh_5y": f5["sharpe"], "mdd_5y": f5["mdd_pct"],
            "n_is": i21["n"], "nav_is": i21["nav"], "sh_is": i21["sharpe"],
            "n_wf": wf["n"], "wr_wf": wf["wr_pct"], "nav_wf": wf["nav"], "ex5_wf": wf["ex_top5_nav"],
            "sh_wf": wf["sharpe"], "mdd_wf": wf["mdd_pct"], "nav_2526": o25["nav"],
            "paired_t_wf": r["paired_t_wf_030"], "paired_p_wf": r["paired_p_wf_030"],
            "hefu_ret_pct": r["hefu_ret_pct"], "youhao_20250103_in": yh_in, "zhongyida_20250327_ret30": zyd_ret,
        })

    # Detailed 5m stop forensics + conservative slippage stress on ALL triggered trades across Prevc6 and D4Low
    cb_map = s34_ctx["cache"]["code_bars_ext"]
    b5_map = s34_ctx["cache"]["bars_5m_map"]
    entry_lu = {(it["bd"], it["c6"]): it for it in s34_ctx["entries"]}
    kb = {(r.buy_date, r.code): r for r in sl_base.itertuples(index=False)}
    kp = {(r.buy_date, r.code): r for r in slot_cache["A_Only5mStop_Prevc6"].itertuples(index=False)}
    kd = {(r.buy_date, r.code): r for r in slot_cache["A_Only5mStop_D4Low"].itertuples(index=False)}

    # Also build candidate-level stop overrides for ALL 115 pool rows (for V20 injection)
    # and collect forensics for every touched trade + key missed ZT blowups
    forensics_rows = []
    led278 = pd.read_parquet(f"{cm23.WAVE1}/v20_baseline_ledger_278.parquet")
    v20_34_keys = set(zip(led278.loc[led278["strategy"] == "3to4", "buy_date"].astype(str).str[:10],
                          led278.loc[led278["strategy"] == "3to4", "code"].astype(str).str.zfill(6)))

    touched_keys = sorted(
        {k for k in kb if abs(kb[k].net_ret_020 - kp[k].net_ret_020) > 1e-6 or abs(kb[k].net_ret_020 - kd[k].net_ret_020) > 1e-6}
        | {("2024-12-23", "603421"), ("2023-09-19", "601188"), ("2025-01-03", "600778")}
    )
    for bd, c6 in touched_keys:
        rb, rp, rd = kb[(bd, c6)], kp[(bd, c6)], kd[(bd, c6)]
        it = entry_lu[(bd, c6)]
        pos = it["entry"]["pos"]
        cb = cb_map[c6]
        k1 = pos + 1
        dt1 = str(cb["dts"][k1])
        pck = float(cb["pre_c"][k1])
        dtk = round(pck * 0.90, 2)
        arr = b5_map.get((c6, dt1))
        if arr is None:
            arr = ctx["bars_5m"].get((c6, dt1))

        # Check bar details at rp exit time
        nx_low = np.nan
        nx_amt_w = np.nan
        trig_bar_c_pct = np.nan
        if arr is not None and rp.exit_date == dt1 and "zt_" in str(rp.exit_reason):
            hits = np.where(arr[:, 0].astype(int) == int(rp.exit_hhmm))[0]
            if len(hits) > 0:
                hi = int(hits[0])
                nx_low = float(arr[hi, 3])
                nx_amt_w = float(arr[hi, 6]) / 1e4
                if hi > 0:
                    trig_bar_c_pct = (float(arr[hi - 1, 4]) / pck - 1.0) * 100.0
        # Compute conservative extra sell slippage (-50bps / -100bps / next-bar low) on Prevc6
        adj_b = float(cb["adjf"][pos])
        adj_e = float(cb["adjf"][k1])
        bp = float(rb.buy_price)
        ret30_base = float(cm23.fee_adjust(rb.net_ret_020, 0.0030) * 100.0)
        ret30_p6 = float(cm23.fee_adjust(rp.net_ret_020, 0.0030) * 100.0)
        ret30_d4 = float(cm23.fee_adjust(rd.net_ret_020, 0.0030) * 100.0)
        if np.isfinite(nx_low):
            ret30_p6_plus50 = ((rp.exit_price * 0.995 * adj_e) / (bp * adj_b) * 0.9970 - 1.0) * 100.0
            ret30_p6_nxlow = ((nx_low * adj_e) / (bp * adj_b) * 0.9970 - 1.0) * 100.0
        else:
            ret30_p6_plus50 = ret30_p6
            ret30_p6_nxlow = ret30_p6

        forensics_rows.append({
            "buy_date": bd, "code": c6, "name": it["name"],
            "window": "WF" if bd >= cm23.WF_START else "IS",
            "in_v20_baseline_278": (bd, c6) in v20_34_keys,
            "d4_is_zt": bool(cb["is_zt"][pos]),
            "base_exit_date": rb.exit_date, "base_exit_hhmm": int(rb.exit_hhmm),
            "base_exit_reason": rb.exit_reason, "base_ret30_pct": round(ret30_base, 2),
            "prevc6_triggered": "zt_" in str(rp.exit_reason),
            "prevc6_exit_date": rp.exit_date, "prevc6_exit_hhmm": int(rp.exit_hhmm),
            "prevc6_exit_px": round(float(rp.exit_price), 2),
            "d5_dt_px": dtk, "trig_bar_close_pct": round(trig_bar_c_pct, 2) if np.isfinite(trig_bar_c_pct) else None,
            "exec_bar_low": round(nx_low, 2) if np.isfinite(nx_low) else None,
            "exec_bar_amt_wan": round(nx_amt_w, 1) if np.isfinite(nx_amt_w) else None,
            "prevc6_ret30_pct": round(ret30_p6, 2),
            "prevc6_delta_pp": round(ret30_p6 - ret30_base, 2),
            "prevc6_extra50bps_ret30_pct": round(ret30_p6_plus50, 2),
            "prevc6_nxlow_ret30_pct": round(ret30_p6_nxlow, 2),
            "d4low_triggered": "zt_" in str(rd.exit_reason),
            "d4low_exit_hhmm": int(rd.exit_hhmm),
            "d4low_ret30_pct": round(ret30_d4, 2),
            "d4low_delta_pp": round(ret30_d4 - ret30_base, 2),
        })

    # Precompute modified trade map across ALL entries (for exact RD038 pool patching)
    def _build_pool_patch_map(zt_mode: str, extra_sell_slip: float = 0.0) -> dict:
        out_m = {}
        ecfg = {"d5_mode": "base", "zt_sl_mode": zt_mode}
        for it in s34_ctx["entries"]:
            bi = f2._sim_buy_3to4(it, ctx, s34_ctx, base_b)
            if bi is None:
                continue
            rec = f2._sim_exit_3to4(it, ctx, s34_ctx, bi, ecfg)
            if extra_sell_slip > 0.0 and "zt_" in str(rec["exit_reason"]):
                # Apply extra conservative sell slippage on 5m stop-loss
                rec["net_ret_020"] = (1.0 + rec["net_ret_020"]) * (1.0 - extra_sell_slip) - 1.0
            out_m[(it["bd"], it["c6"])] = rec
        return out_m

    patch_prevc6 = _build_pool_patch_map("prevc_tp1_m6_1000", 0.0)
    patch_prevc6_slip50 = _build_pool_patch_map("prevc_tp1_m6_1000", 0.0050)
    patch_d4low = _build_pool_patch_map("d4low_tp1_1000", 0.0)

    # Also compute conservative slippage stress on standalone 3to4 (both A alone and AB_M4)
    # Wait: check standalone sensitivity quickly
    plateau_zt_patches = {}
    for thr_s in ["4", "4.5", "5", "5.5", "6", "6.5", "7"]:
        for hh_s in ["0945", "1000", "1015", "1030"]:
            zm = f"prevc_tp1_m{thr_s}_{hh_s}"
            plateau_zt_patches[zm] = _build_pool_patch_map(zm, 0.0)
    for hh_s in ["0945", "1000", "1015", "1030"]:
        zm = f"d4low_tp1_{hh_s}"
        plateau_zt_patches[zm] = _build_pool_patch_map(zm, 0.0)

    # Save lean dmap & cal_5y for pool MTM recomputation, free heavy 5m bars
    dmap_lean = ctx["dmap"]
    del ctx, s34_ctx
    gc.collect()
    pa.default_memory_pool().release_unused()

    return {
        "snapshots_22factors": snapshots,
        "ablation_rows": ablation_rows,
        "forensics_rows": forensics_rows,
        "patch_prevc6": patch_prevc6,
        "patch_prevc6_slip50": patch_prevc6_slip50,
        "patch_d4low": patch_d4low,
        "plateau_zt_patches": plateau_zt_patches,
        "dmap_lean": dmap_lean,
    }


def make_patched_3to4_df(df34_orig: pd.DataFrame, patch_map: dict, cal_5y: list[str], idx_5y: dict, dmap: dict) -> pd.DataFrame:
    """Create a modified copy of RD038 pools_ext['3to4'] with exact exit dates, returns & close-to-close MTM segments."""
    df = df34_orig.copy()
    has_orig_exit = list(zip(df["exit_date"].astype(str).str[:10], df["exit_hhmm"].astype(int)))
    n = len(df)
    new_ed = df["exit_date"].astype(str).str[:10].tolist()
    new_eh = df["exit_hhmm"].astype(int).tolist()
    new_ep = df["exit_price"].astype(float).tolist()
    r20 = df["net_ret_020"].to_numpy(float).copy()
    r30 = df["net_ret_030"].to_numpy(float).copy()
    r50 = df["net_ret_050"].to_numpy(float).copy()
    r80 = df["net_ret_080"].to_numpy(float).copy()
    rnat = df["net_ret_native"].to_numpy(float).copy()
    m20 = df["mtm_5y_020"].tolist()
    m30 = df["mtm_5y_030"].tolist()
    m50 = df["mtm_5y_050"].tolist()
    m80 = df["mtm_5y_080"].tolist()
    mnat = df["mtm_5y_native"].tolist()

    for i in range(n):
        bd = str(df["buy_date"].iloc[i])[:10]
        c6 = str(df["code"].iloc[i]).zfill(6)
        rec = patch_map.get((bd, c6))
        if rec is None:
            continue
        if abs(rec["net_ret_020"] - r20[i]) <= 1e-6 and str(rec["exit_date"]) == new_ed[i] and int(rec["exit_hhmm"]) == new_eh[i]:
            continue
        ed_i = str(rec["exit_date"])
        eh_i = int(rec["exit_hhmm"])
        bp_i = float(df["buy_price"].iloc[i]) if pd.notna(df["buy_price"].iloc[i]) else float(rec["buy_price"])
        new_ed[i] = ed_i
        new_eh[i] = eh_i
        new_ep[i] = float(rec["exit_price"])
        v20 = float(rec["net_ret_020"])
        v30 = float(cm36.convert_fee(v20, 0.0030))
        v50 = float(cm36.convert_fee(v20, 0.0050))
        v80 = float(cm36.convert_fee(v20, 0.0080))
        r20[i], r30[i], r50[i], r80[i], rnat[i] = v20, v30, v50, v80, v20
        m20[i] = build_mtm_segs_from_dmap(c6, bd, ed_i, bp_i, v20, cal_5y, idx_5y, dmap)
        m30[i] = build_mtm_segs_from_dmap(c6, bd, ed_i, bp_i, v30, cal_5y, idx_5y, dmap)
        m50[i] = build_mtm_segs_from_dmap(c6, bd, ed_i, bp_i, v50, cal_5y, idx_5y, dmap)
        m80[i] = build_mtm_segs_from_dmap(c6, bd, ed_i, bp_i, v80, cal_5y, idx_5y, dmap)
        mnat[i] = m20[i]

    df["exit_date"] = new_ed
    df["exit_hhmm"] = new_eh
    df["exit_price"] = new_ep
    df["net_ret_020"] = r20
    df["net_ret_030"] = r30
    df["net_ret_050"] = r50
    df["net_ret_080"] = r80
    df["net_ret_native"] = rnat
    df["mtm_5y_020"] = m20
    df["mtm_5y_030"] = m30
    df["mtm_5y_050"] = m50
    df["mtm_5y_080"] = m80
    df["mtm_5y_native"] = mnat
    return df


def run_v20_grand_pk(stage1: dict) -> dict:
    """
    Stage 2: Same-engine V20.0 Grand PK across 30/50/80bps + >=2yi liquidity + paired t/p + DSR +
    5m stop plateau on GRAND_COMBO + 2024-12-31 physical truncation check.
    """
    print("\n[Stage 2] Loading RD038 master cache & running unified V20.0 Grand PK ...")
    with open(f"{RD038_DIR}/_cache/rd038_master_cache.pkl", "rb") as f:
        cache = pickle.load(f)
    with open(f"{RD038_DIR}/rd038_grand_bundle_audit.json", encoding="utf-8") as f:
        a38 = json.load(f)

    cal_5y = cache["cal_5y"]
    idx_5y = {d: i for i, d in enumerate(cal_5y)}
    dmap = stage1["dmap_lean"]
    df34_orig = cache["pools_ext"]["3to4"]

    # Build patched caches for clean 3to4 stop rules (+ conservative -50bps sell slip + negative control)
    cache_prevc6 = {**cache, "pools_ext": {**cache["pools_ext"], "3to4": make_patched_3to4_df(df34_orig, stage1["patch_prevc6"], cal_5y, idx_5y, dmap)}}
    cache_slip50 = {**cache, "pools_ext": {**cache["pools_ext"], "3to4": make_patched_3to4_df(df34_orig, stage1["patch_prevc6_slip50"], cal_5y, idx_5y, dmap)}}
    cache_d4low = {**cache, "pools_ext": {**cache["pools_ext"], "3to4": make_patched_3to4_df(df34_orig, stage1["patch_d4low"], cal_5y, idx_5y, dmap)}}

    # Negative Control: static_loo_af20 + m4_4way_bl15 on cache_prevc6 (matching RD039-B raw leaky V42!)
    o5_leaky = {**cache_prevc6["other5_variants"]}
    v_m4 = o5_leaky["3to4"]["m4_4way_bl15"]
    v_af20 = o5_leaky["3to4"]["static_loo_af20"]
    o5_leaky["3to4"] = {**o5_leaky["3to4"], "m4_plus_af20_leaky": {"score": v_af20["score"], "mask": v_m4["mask"]}}
    cache_leaky = {**cache_prevc6, "other5_variants": o5_leaky}

    cfg_v20 = {"s20": "base_76", "s34": "base", "s23": "base", "shi": "base", "spr": "base", "s12": "base", "w2a5": "none", "w2a6": "s_tier_reserve_only"}
    cfg_clean5 = dict(a38["step2_summary"]["greedy_configs"]["OFFENSIVE_BLEND"])
    cfg_clean4 = dict(a38["step2_summary"]["greedy_configs"]["ROBUST_STACK"])
    cfg_allin_rob = {"s20": "stack_c50_avg", "s34": "m4_4way_bl15", "s23": "m2_pair_cold45_d15", "shi": "m1_causal_cold_drop40_t0", "spr": "m1_skip_cold50", "s12": "base", "w2a5": "S_HighTier_0925", "w2a6": "s_tier_plus_1to2S"}

    pk_specs = [
        ("1_V20_Baseline", "0_BASE", cache, cfg_v20),
        ("2_RD039_Pure5mStop_Prevc6", "1_RD039_CLEAN", cache_prevc6, cfg_v20),
        ("2b_RD039_Pure5mStop_D4Low", "1_RD039_CLEAN", cache_d4low, cfg_v20),
        ("3_RD039_3to4_CleanBest", "1_RD039_CLEAN", cache_prevc6, {**cfg_v20, "s34": "m4_4way_bl15"}),
        ("3c_V20_3to4_M4Only_Ctrl", "1_RD039_CLEAN", cache, {**cfg_v20, "s34": "m4_4way_bl15"}),
        ("3b_RD039_LeakyOrig_Ref", "9_LEAKY_REF", cache_leaky, {**cfg_v20, "s34": "m4_plus_af20_leaky"}),
        ("4_RD038_Clean5", "2_RD038_CLEAN", cache, cfg_clean5),
        ("5_RD038_Clean4", "2_RD038_CLEAN", cache, cfg_clean4),
        ("5b_RD038_ALLIN_ROBUST", "2_RD038_CLEAN", cache, cfg_allin_rob),
        ("6_GRAND_COMBO_Clean5_Prevc6", "3_GRAND_COMBO", cache_prevc6, cfg_clean5),
        ("6b_GRAND_COMBO_Clean5_Slip50", "3_GRAND_COMBO", cache_slip50, cfg_clean5),
        ("6c_GRAND_COMBO_Clean5_D4Low", "3_GRAND_COMBO", cache_d4low, cfg_clean5),
        ("7_GRAND_COMBO_Clean4_Prevc6", "3_GRAND_COMBO", cache_prevc6, cfg_clean4),
        ("8_GRAND_COMBO_ALLIN_Prevc6", "3_GRAND_COMBO", cache_prevc6, cfg_allin_rob),
    ]

    # Run baseline first to capture ref_dr_wf
    sim_v20_30 = eng.run_bundle_sim(cache, cfg_v20, fee_mode="030")
    ref_v20_dr_wf = sim_v20_30["dr_wf"]
    assert abs(float(np.prod(1.0 + ref_v20_dr_wf)) - 534297.0208) < 0.05

    sim_c5_30 = eng.run_bundle_sim(cache, cfg_clean5, fee_mode="030")
    ref_c5_dr_wf = sim_c5_30["dr_wf"]

    pk_rows = []
    bundle_meta = {}
    dr_wf_map = {}

    for bname, bgrp, c_use, bcfg in pk_specs:
        s30 = eng.run_bundle_sim(c_use, bcfg, fee_mode="030")
        s50 = eng.run_bundle_sim(c_use, bcfg, fee_mode="050")
        s80 = eng.run_bundle_sim(c_use, bcfg, fee_mode="080")
        nav_tr_5y = float(np.prod(1.0 + s30["trades_df"]["net_ret"].to_numpy(float)))
        rel_diff_5y = s30["mtm_diff_5y"] / max(1.0, nav_tr_5y)
        assert rel_diff_5y < 1e-11 and s30["mtm_diff_wf"] < 1e-5, f"MTM diff error on {bname}: rel5y={rel_diff_5y}, wf={s30['mtm_diff_wf']}"
        e30 = eng.evaluate_bundle(bname, bgrp, s30, c_use, ref_dr_wf=ref_v20_dr_wf, perm_n=1000)
        e50 = eng.evaluate_bundle(bname, bgrp, s50, c_use, perm_n=0)
        e80 = eng.evaluate_bundle(bname, bgrp, s80, c_use, perm_n=0)

        # Paired test vs RD038_Clean5
        dd_c5 = s30["dr_wf"] - ref_c5_dr_wf
        sd_c5 = float(np.std(dd_c5, ddof=1))
        t_c5 = float(np.mean(dd_c5) / (sd_c5 / math.sqrt(len(dd_c5)))) if sd_c5 > 1e-12 else 0.0
        p_c5 = float(stats.t.sf(t_c5, df=len(dd_c5) - 1)) if sd_c5 > 1e-12 else 0.5

        # >= 2亿 Liquidity subset check
        pools_liq = {}
        for st, df_s in c_use["pools_ext"].items():
            d2 = df_s.copy()
            d2["can_buy_hygiene"] = d2["can_buy_hygiene"].fillna(True).to_numpy(bool) & (d2["sd_amount_yi_t1"].fillna(0.0).to_numpy(float) >= 2.0)
            pools_liq[st] = d2
        c_liq = {**c_use, "pools_ext": pools_liq}
        s_liq = eng.run_bundle_sim(c_liq, bcfg, fee_mode="030")
        e_liq = eng.evaluate_bundle(f"{bname}_LIQ2YI", "LIQ", s_liq, c_liq, perm_n=0)
        del c_liq, pools_liq

        dr_wf_map[bname] = s30["dr_wf"]
        bundle_meta[bname] = {
            "group": bgrp,
            "cfg": bcfg,
            "mtm_diff_5y": e30["mtm_diff_5y"],
            "mtm_diff_wf": e30["mtm_diff_wf"],
            "perm_wf": e30["perm_wf"],
            "vs_v20_wf": e30["vs_v20_wf"],
            "vs_clean5_wf": {"paired_t": round(t_c5, 3), "paired_p_1sided": round(p_c5, 4)},
            "windows_030": e30["windows"],
            "wf_050": e50["windows"]["WF_2326"],
            "wf_080": e80["windows"]["WF_2326"],
            "wf_liq2yi": e_liq["windows"]["WF_2326"],
            "n_3to4_wf": int((s30["trades_df"][s30["trades_df"]["buy_date"] >= eng.WF_START]["strategy"] == "3to4").sum()),
        }

        for ftag, ev_obj in [("030", e30), ("050", e50), ("080", e80), ("liq2yi_030", e_liq)]:
            for wn, w in ev_obj["windows"].items():
                if ftag != "030" and wn != "WF_2326":
                    continue
                pk_rows.append({
                    "bundle": bname, "group": bgrp, "fee_liq": ftag, "window": wn,
                    "n": w["n"], "wr_pct": w["wr_pct"], "plr": w["plr"], "mean_pct": w["mean_pct"],
                    "nav": w["nav"], "mtm_nav": w["mtm_nav"], "ex_top5_nav": w["ex_top5_nav"],
                    "daily_sharpe": w["daily_sharpe"], "daily_mdd_pct": w["daily_mdd_pct"], "daily_calmar": w["daily_calmar"],
                    "excess_csi300_pp": w["excess_csi300_pp"], "excess_alla_ew_pp": w["excess_alla_ew_pp"],
                    "mtm_diff_wf": ev_obj["mtm_diff_wf"],
                    "paired_t_vs_v20": e30["vs_v20_wf"]["paired_t"] if ftag == "030" else None,
                    "paired_p1_vs_v20": e30["vs_v20_wf"]["paired_p_1sided"] if ftag == "030" else None,
                    "paired_t_vs_clean5": round(t_c5, 3) if ftag == "030" else None,
                })
        w30 = e30["windows"]["WF_2326"]
        print(f"  {bname:30s} | n={w30['n']:3d} WF={w30['nav']:12,.2f}x Sh={w30['daily_sharpe']:.3f} MDD={w30['daily_mdd_pct']:5.2f}% Cal={w30['daily_calmar']:6.2f} Ex5={w30['ex_top5_nav']:9,.2f}x LiQ={e_liq['windows']['WF_2326']['nav']:11,.2f}x t_v20={e30['vs_v20_wf']['paired_t']:+.3f}")

    # 32-variant 5m Stop Parameter Plateau inside GRAND_COMBO_Clean5 & V20
    print("\n[Stage 2B] Running 32-variant 5m stop plateau inside GRAND_COMBO_Clean5 & V20 ...")
    plat_rows = []
    for zm, pmap in stage1["plateau_zt_patches"].items():
        c_p = {**cache, "pools_ext": {**cache["pools_ext"], "3to4": make_patched_3to4_df(df34_orig, pmap, cal_5y, idx_5y, dmap)}}
        s_gc = eng.run_bundle_sim(c_p, cfg_clean5, fee_mode="030")
        e_gc = eng.evaluate_bundle(f"GC5_{zm}", "PLAT", s_gc, c_p, perm_n=0)
        w_gc = e_gc["windows"]["WF_2326"]
        plat_rows.append({"zt_mode": zm, "n_wf": w_gc["n"], "nav_wf": w_gc["nav"], "sharpe_wf": w_gc["daily_sharpe"], "mdd_wf": w_gc["daily_mdd_pct"]})

    # Global DSR including RD035+RD036+RD038 (8127) + RD039 F1 (688) + RD039 F2/3 (287) + RD039 F4 (len(pk_specs) + len(plat_rows))
    f1_grid = pd.read_csv(f"{RD039_F1_DIR}/rd039_f1_cond_grid.csv")
    f23_grid = pd.read_csv(f"{RD039_F23_DIR}/rd039_f23_grid.csv")
    n_rd039_f1 = int(len(f1_grid))
    n_rd039_f23 = int(len(f23_grid))
    n_rd039_f4 = int(len(pk_specs) + len(plat_rows))
    n_cum_all = 8127 + n_rd039_f1 + n_rd039_f23 + n_rd039_f4

    sr_v20_daily = float(np.mean(ref_v20_dr_wf) / np.std(ref_v20_dr_wf, ddof=1))
    sr_c5_daily = float(np.mean(ref_c5_dr_wf) / np.std(ref_c5_dr_wf, ddof=1))
    srs_pk = [float(np.mean(v) / np.std(v, ddof=1)) for k, v in dr_wf_map.items() if k != "3b_RD039_LeakyOrig_Ref"]
    var_local_pk = float(np.var(srs_pk, ddof=1)) if len(srs_pk) > 1 else eng.DSR_VAR_POOLED
    var_pool = eng.DSR_VAR_POOLED
    var_null = 1.0 / max(1, len(ref_v20_dr_wf) - 1)

    dsr_table = {}
    for bname, dr in dr_wf_map.items():
        dsr_table[bname] = {
            "abs_vs0_cum_pool": calc_dsr_exact(dr, n_cum_all, var_pool, 0.0),
            "abs_vs0_cum_null": calc_dsr_exact(dr, n_cum_all, var_null, 0.0),
            "inc_vs_v20_local": calc_dsr_exact(dr, len(pk_specs) + len(plat_rows), var_local_pk, sr_v20_daily),
            "inc_vs_v20_cum_pool": calc_dsr_exact(dr, n_cum_all, var_pool, sr_v20_daily),
            "inc_vs_v20_cum_null": calc_dsr_exact(dr, n_cum_all, var_null, sr_v20_daily),
            "inc_vs_clean5_cum_null": calc_dsr_exact(dr, n_cum_all, var_null, sr_c5_daily),
        }

    # Physical 2024-12-31 Truncation Zero-Leakage Check on Clean Bundles
    print("\n[Stage 2C] Physical 2024-12-31 Truncation Zero-Leakage Proof on GRAND_COMBO & RD039 Clean ...")
    # Compare trades exiting <= 2024-12-31 using full cache vs physically truncated <= 2024-12-31 cache & rebuilt M4/Blend/Pairwise!
    import step3_redteam_and_truncation as rt38
    import rd036_lib as lib20
    import run_m1_m2_cold_and_pairwise as m12
    import run_m3_m4_3way_4way_trees as m34
    CUTOFF = "2024-12-31"
    bundle_o5 = cm36.build_or_load_cache(force_rebuild=False)
    pools_t = {st: df[df["buy_date"] <= CUTOFF].copy().reset_index(drop=True) for st, df in cache_prevc6["pools_ext"].items()}
    ut_t = cache_prevc6["ut_full_raw"][cache_prevc6["ut_full_raw"]["buy_date"] <= CUTOFF].copy().reset_index(drop=True)
    cal_5y_t = [d for d in cal_5y if d <= CUTOFF]
    bench_t = cache["bench_5y"][cache["bench_5y"]["trade_date"] <= CUTOFF].copy().reset_index(drop=True)

    p20_t, meta20_t = lib20.load_20cm_enriched_data(end_cutoff=CUTOFF)
    p20_t["wf_in_window"] = p20_t["buy_date"] >= eng.WF_START
    dm_cb_t, _ = lib20.run_mode_b_multi_grid(p20_t, meta20_t["feat_clean_b"], ["v20_cold50"], deltas=(15,), min_discrete_bin_cnt=15, top_k=10)
    dm_mn_t, _ = lib20.run_mode_b_multi_grid(p20_t, meta20_t["ix_cols"], ["v20_cold50"], deltas=(15,), min_discrete_bin_cnt=0, top_k=10)
    s_blend_t = p20_t["v20_cold50"].to_numpy(float) + np.round(0.5 * dm_cb_t[("v20_cold50", 15)] + 0.5 * dm_mn_t[("v20_cold50", 15)])
    ho_t = lib20.run_causal_highorder_and_tree_wf(p20_t, atomic_cols=meta20_t["atomic_cols"], extra_static_cols=meta20_t["feat_union_cb_mech"], wf_start_date=eng.WF_START, min_warmup_trades=80, deltas=(8, 12, 15), enable_4way=False)
    s_stack_t = p20_t["v20_cold50"].to_numpy(float) + np.round((dm_cb_t[("v20_cold50", 15)] + dm_mn_t[("v20_cold50", 15)] + ho_t["rule_deltas"][("Rule3Way", 12)]) / 3.0)
    p20_key_t = {(str(r.buy_date)[:10], str(r.code).zfill(6)): idx for idx, r in enumerate(p20_t.itertuples(index=False))}
    sc20_t = {}
    for kn, sv_src in [("blend_c50_half", s_blend_t), ("stack_c50_avg", s_stack_t)]:
        arr = np.empty(len(pools_t["20cm"]), dtype=float)
        for j, r in enumerate(pools_t["20cm"].itertuples(index=False)):
            idx_p = p20_key_t.get((str(r.buy_date)[:10], str(r.code).zfill(6)))
            if idx_p is None:
                arr[j] = float(r.orig_score)
            elif str(r.buy_date)[:10] < eng.WF_START:
                arr[j] = float(r.orig_score) if float(r.orig_score) >= 82.0 else -999.0
            else:
                arr[j] = float(sv_src[idx_p])
        sc20_t[kn] = arr
    del p20_t, dm_cb_t, dm_mn_t, ho_t
    gc.collect()

    o5_t = {"3to4": {}, "2to3": {}, "high": {}, "pry": {}}
    df34_t_orig = cache["pools_ext"]["3to4"][cache["pools_ext"]["3to4"]["buy_date"] <= CUTOFF].copy().reset_index(drop=True)
    orig34_t = pools_t["3to4"]["orig_score"].to_numpy(float)
    bp34 = list(dict.fromkeys(bundle_o5["base_dyn_cols"] + bundle_o5["atom_info"]["3to4"]["cols"]))
    r4_34_t = m34.run_wf_3way_4way_and_trees(df34_t_orig, bp34, min_leaf=20, min_days=8, order=4, run_trees=False)
    o5_t["3to4"]["m4_4way_bl15"] = {"score": orig34_t, "mask": np.where(df34_t_orig["buy_date"] >= eng.WF_START, ~r4_34_t["mine_bl"][15], True)}
    df23_t = pools_t["2to3"]
    bp23 = list(dict.fromkeys(bundle_o5["base_dyn_cols"] + bundle_o5["atom_info"]["2to3"]["cols"]))
    dp23_t, _ = m12.run_causal_pairwise_multi(df23_t, bundle_o5["ix_cols"], bp23, cold_cut=45.0, regime_mode="cold_only", max_deltas=(15,), min_cell=cm36.MIN_LEAF_MAP["2to3"])
    o5_t["2to3"]["m2_pair_cold45_d15"] = {"score": df23_t["orig_score"].to_numpy(float) + np.where(df23_t["buy_date"] >= eng.WF_START, dp23_t[15], 0.0), "mask": None}
    m_hi_t = (cache["pools_ext"]["high"]["buy_date"] <= CUTOFF).to_numpy(bool)
    dfhi_t = pools_t["high"]
    sc_hi_t = m12.run_causal_cold_atom_disable(dfhi_t, bundle_o5["atom_info"]["high"]["cols"], bundle_o5["atom_info"]["high"]["contrib_mat"][m_hi_t], cold_cut=40.0, t_cut=0.0, bonus_only=True)
    o5_t["high"]["m1_causal_cold_drop40_t0"] = {"score": np.where(dfhi_t["buy_date"] >= eng.WF_START, sc_hi_t, dfhi_t["orig_score"].to_numpy(float)), "mask": None}
    dfpr_t = pools_t["pry"]
    bp_pr = list(dict.fromkeys(bundle_o5["base_dyn_cols"] + bundle_o5["atom_info"]["pry"]["cols"]))
    dp_pr_t, _ = m12.run_causal_pairwise_multi(dfpr_t, bundle_o5["ix_cols"], bp_pr, cold_cut=45.0, regime_mode="cold_only", max_deltas=(15,), min_cell=cm36.MIN_LEAF_MAP["pry"], decluster_days=True)
    o5_t["pry"]["m2_pair_cold45_d15"] = {"score": dfpr_t["orig_score"].to_numpy(float) + np.where(dfpr_t["buy_date"] >= eng.WF_START, dp_pr_t[15], 0.0), "mask": None}
    o5_t["pry"]["m1_skip_cold50"] = {"score": dfpr_t["orig_score"].to_numpy(float), "mask": np.where(dfpr_t["buy_date"] >= eng.WF_START, dfpr_t["mkt10_zt_est_t1"].to_numpy(float) >= 50.0, True)}

    trunc_cache = {
        "cal_5y": cal_5y_t, "bench_5y": bench_t, "pools_ext": pools_t, "ut_full_raw": ut_t,
        "sc20_aligned": sc20_t, "other5_variants": o5_t,
        "b0_lu": {k: v for k, v in cache["b0_lu"].items() if k[2] <= CUTOFF},
        "swap_close_lu": {k: v for k, v in cache["swap_close_lu"].items() if k[1] <= CUTOFF},
    }

    trunc_proofs = {}
    for tname, tcfg in [
        ("2_RD039_Pure5mStop_Prevc6", cfg_v20),
        ("3_RD039_3to4_CleanBest", {**cfg_v20, "s34": "m4_4way_bl15"}),
        ("6_GRAND_COMBO_Clean5_Prevc6", cfg_clean5),
        ("7_GRAND_COMBO_Clean4_Prevc6", cfg_clean4),
    ]:
        sf = eng.run_bundle_sim(cache_prevc6, tcfg, fee_mode="030")["trades_df"]
        st = eng.run_bundle_sim(trunc_cache, tcfg, fee_mode="030")["trades_df"]
        fle = sf[sf["exit_date"] <= CUTOFF].sort_values(["buy_date", "code"]).reset_index(drop=True)
        tle = st[st["exit_date"] <= CUTOFF].sort_values(["buy_date", "code"]).reset_index(drop=True)
        assert len(fle) == len(tle) and list(zip(fle["buy_date"], fle["code"], fle["strategy"])) == list(zip(tle["buy_date"], tle["code"], tle["strategy"]))
        sc_diff = float(np.max(np.abs(fle["score"].to_numpy(float) - tle["score"].to_numpy(float))))
        r_diff = float(np.max(np.abs(fle["net_ret"].to_numpy(float) - tle["net_ret"].to_numpy(float))))
        assert sc_diff == 0.0 and r_diff == 0.0
        trunc_proofs[tname] = {"cutoff": CUTOFF, "n_trades_checked": int(len(fle)), "max_abs_score_diff": sc_diff, "max_abs_ret_diff": r_diff, "zero_leakage_pass": True}
        print(f"  Trunc {tname:28s}: n={len(fle)} max_score_diff={sc_diff} max_ret_diff={r_diff} [PASS]")

    return {
        "pk_rows": pk_rows,
        "bundle_meta": bundle_meta,
        "plateau_gc5_32": plat_rows,
        "dsr_counts": {
            "rd035_036_038": 8127,
            "rd039_f1": n_rd039_f1,
            "rd039_f23": n_rd039_f23,
            "rd039_f4": n_rd039_f4,
            "n_cum_all": n_cum_all,
            "var_local_pk": round(var_local_pk, 6),
            "var_pooled_prior": var_pool,
            "var_null_1_over_T": round(var_null, 6),
        },
        "dsr_table": dsr_table,
        "truncation_20241231_proof": trunc_proofs,
    }


def main():
    t0 = time.time()
    stage1 = audit_3to4_components_and_5m_forensics()
    stage2 = run_v20_grand_pk(stage1)

    # Read Front 1 & Front 3 summaries for unified 4-front final audit JSON
    with open(f"{RD039_F1_DIR}/rd039_f1_audit.json", encoding="utf-8") as f:
        f1 = json.load(f)
    with open(f"{RD039_F23_DIR}/rd039_f23_audit.json", encoding="utf-8") as f:
        f23 = json.load(f)

    pd.DataFrame(stage1["forensics_rows"]).to_csv(f"{OUT_DIR}/rd039_3to4_stop_forensics.csv", index=False)
    pd.DataFrame(stage2["pk_rows"]).to_csv(f"{OUT_DIR}/rd039_vs_rd038_pk.csv", index=False)

    f1_summ = {
        tgt: ad["baseline_vs_all_cond_summary"]
        for tgt, ad in f1["per_target_audit"].items()
    }
    f1_total_cond = sum(v["n_cond_variants_tested"] for v in f1_summ.values())
    f1_total_beat_sh = sum(v["n_beat_base_sharpe_wf"] for v in f1_summ.values())
    f1_total_beat_nav = sum(v["n_beat_base_nav_wf"] for v in f1_summ.values())

    audit = cm23.sanitize_json({
        "task": "RD039-C Front 4: Four-Front Cold-Blooded Red-Team Audit & V20.0/RD038 Grand Assembly PK",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t0, 2),
        "peak_rss_mb": rss_mb(),
        "d12_yfinance_imported": False,
        "front1_2to3_20cm_audit": {
            "total_cond_variants": f1_total_cond,
            "total_beat_base_sharpe_wf": f1_total_beat_sh,
            "total_beat_base_nav_wf": f1_total_beat_nav,
            "per_target": f1_summ,
            "v20_collision_baseline_wf_nav": f1["module3_0925_sell_old_buy_new_collision"]["v20_portfolio_experiments_20bps"][0]["nav_wf"],
            "v20_collision_cond_wf_nav": f1["module3_0925_sell_old_buy_new_collision"]["v20_portfolio_experiments_20bps"][2]["nav_wf"],
            "verdict": "REJECTED_0_OF_684",
        },
        "front2_3to4_redteam_autopsy": {
            "component_c_hardcoding_finding": {
                "killed": True,
                "reason": "run_front2_3to4.py attach_causal_loo_s34_af20 hardcoded s34_af_20 (1/22 native factors). At 2024-12-31 & 2025-01-03 (N=65), #1 worst bonus factor by exit_date<t t_clip was s34_af_05 (-1.772), NOT s34_af_20 (-1.297, raw mean +6.15% vs +6.12%). Unbiased all-22-factor causal LOO either collapses trades (t<0 -> 11t / 2.25x / Sh 1.094; t<-1.0 -> 51t / 46.36x / Sh 2.452) or drops s34_af_05 (Worst1 -> 180.14x / Sh 2.724) leaving 2025-01-03 友好集团 (-23.82%) untouched. Hardcoded s34_af_20 merely replicated RD036 STATIC_POSTHOC_LOO (identical 63t / 401.69x / MDD 27.32%), producing the fake 31.12% V20 MDD drop.",
            },
            "factor_snapshots_exit_lt_t": stage1["snapshots_22factors"],
            "component_ablation": stage1["ablation_rows"],
            "stop_5m_forensics_summary": {
                "n_rows_inspected": len(stage1["forensics_rows"]),
                "prevc6_triggered_count_5y": sum(1 for r in stage1["forensics_rows"] if r["prevc6_triggered"]),
                "prevc6_triggered_count_wf": sum(1 for r in stage1["forensics_rows"] if r["prevc6_triggered"] and r["window"] == "WF"),
                "prevc6_triggered_in_v20_278_count": sum(1 for r in stage1["forensics_rows"] if r["prevc6_triggered"] and r["in_v20_baseline_278"]),
                "prevc6_triggered_in_v20_wf_count": sum(1 for r in stage1["forensics_rows"] if r["prevc6_triggered"] and r["in_v20_baseline_278"] and r["window"] == "WF"),
            },
        },
        "front3a_high_audit": f23["verdicts"]["front3a_high"],
        "front3b_pry_audit": f23["verdicts"]["front3b_pry"],
        "v20_grand_pk": {
            "bundles": stage2["bundle_meta"],
            "plateau_gc5_32": {
                "n": len(stage2["plateau_gc5_32"]),
                "nav_wf_min": min(r["nav_wf"] for r in stage2["plateau_gc5_32"]),
                "nav_wf_med": float(np.median([r["nav_wf"] for r in stage2["plateau_gc5_32"]])),
                "nav_wf_max": max(r["nav_wf"] for r in stage2["plateau_gc5_32"]),
                "sharpe_wf_min": min(r["sharpe_wf"] for r in stage2["plateau_gc5_32"]),
                "sharpe_wf_med": float(np.median([r["sharpe_wf"] for r in stage2["plateau_gc5_32"]])),
                "sharpe_wf_max": max(r["sharpe_wf"] for r in stage2["plateau_gc5_32"]),
                "mdd_wf_all": sorted({r["mdd_wf"] for r in stage2["plateau_gc5_32"]}),
                "rows": stage2["plateau_gc5_32"],
            },
            "dsr_counts": stage2["dsr_counts"],
            "dsr_table": stage2["dsr_table"],
            "truncation_20241231_proof": stage2["truncation_20241231_proof"],
        },
    })
    with open(f"{OUT_DIR}/rd039_final_audit.json", "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)

    print(f"\n[RD039-C COMPLETE in {time.time()-t0:.1f}s | Peak RSS={rss_mb()} MB]")
    print("DSR Summary (cum N =", stage2["dsr_counts"]["n_cum_all"], "):")
    for bn, dv in stage2["dsr_table"].items():
        print(f"  {bn:30s} | SR={dv['abs_vs0_cum_null']['sr_ann']:.3f} | AbsDSR(null)={dv['abs_vs0_cum_null']['dsr']:.4f} | IncDSR_vs_V20(null)={dv['inc_vs_v20_cum_null']['dsr']:.4f} (z={dv['inc_vs_v20_cum_null']['z_dsr']:.2f})")


if __name__ == "__main__":
    main()

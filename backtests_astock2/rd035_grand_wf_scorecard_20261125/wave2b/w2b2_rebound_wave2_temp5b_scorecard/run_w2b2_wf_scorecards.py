#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 2B-2 Step 2: Run Full Day-by-Day Expanding Walk-Forward Scorecards (0..100, exit_date < t)
+ V20 Empty-Slot Patch (Strict Combined No-Peek & Standalone) + Physical Truncation Proof
across Tracks A, B, C, D (incl. Minefield Separation) and Track E (Unified 4-Track Pool).

Hard rules:
  - Peak RSS < 2.0 GB, threads <= 1, zero yfinance (D12), zero cap10m.
  - 0.30% RT friction, non-yizi buyable, 1000x permutation test, V20 correlation, 2024-12-31 truncation proof.
"""
import gc
import json
import math
import os
import resource
import sys
import time
from typing import Optional

import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
WAVE1_BASE = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
OUT_DIR = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave2b/w2b2_rebound_wave2_temp5b_scorecard"

if WAVE1_BASE not in sys.path:
    sys.path.insert(0, WAVE1_BASE)

import wf_scorecard_engine as wf
import _wf_sim_and_metrics as wfm

CORE_FEATURES = [
    "open_pct", "prev_close_raw", "mcap_yi_t1", "amount_yi_t1", "ret_1d_t1", "d1_open_pct",
    "prev_clv", "prev_streak", "prev_is_broken_zt", "prev_is_yizi_zt", "overhang_pct_t1",
    "hr10d_space_t1", "hr30d_space_t1", "down_streak_t1", "pos_20d_t1", "pos_60d_t1", "pos_250d_t1",
    "dd_20d_t1", "amp_20d_t1", "bias10_t1", "bias20_t1", "ret_5d_t1", "ret_20d_t1",
    "vol_ratio5_t1", "turn_5_20_t1", "amp_comp_20v60_t1",
    "lhb_on_t1", "lhb_bayes_t2_t1", "lhb_inst_net_yi_t1", "lhb_lhasa_share_t1",
    "lhb_has_good_yz_t1", "lhb_has_surf_yz_t1", "lhb_has_quant_t1", "lhb_cnt_5d_t1",
    "lock_top10_pct_pre", "free_mcap_yi_t1", "real_turn_pct_t1", "d1_first_seal_hhmm_t1",
    "d1_open_board_cnt_t1", "d1_seal_ratio_t1", "list_age", "waves_3y_g15_t1", "zt_cnt_1y_t1",
    "max_streak_3y", "cum_turnover_1y", "trap_waves_3y", "dd_from_3y_high",
    "cool_days_since_last_zt", "cool_days_since_last_2b", "comm_posts_1y_pct", "xq_posts_1y_pct",
    "kpl_unique_plates_3y", "kpl_top_plate_share", "kpl_zt3_t1", "kpl_days_30d_t1",
    "kpl_in_t1", "kpl_rank_t1", "kpl_zt1_t1", "kpl_streak_t1",
    "csrc_ind_ex5_t1", "csrc_ind_ex20_t1", "csrc_ind_rank20_t1", "csrc_ind_zt_share5_t1",
    "csrc_ind_amt_pct250_t1", "tox_reg_30d_pre", "abn_notice_30d_pre", "ir_cnt_30d_pre",
    "comm_ring_tier", "drv_open_minus_ret_t1", "drv_hr_min_space_t1", "drv_lock_ge50",
    "drv_real_turn_ge15", "drv_lhb_inst_minus_lhasa", "drv_ind_rel5_t1", "drv_ind_rel20_t1",
    "drv_has_reg_or_tox",
]


def _get_feature_list(df: pd.DataFrame, extra_cols: list[str], exclude_cols: tuple[str, ...] = ()) -> list[str]:
    mkt_cols = [c for c in df.columns if c.startswith(("L1_", "mkt", "th_", "nt_", "us_", "comm_", "macro_", "wp_", "pol_")) and c not in ("comm_posts_1y_pct", "comm_ring_tier", "comm_driver_ret20_t1", "comm_driver_pct5y_t1")]
    cand = list(dict.fromkeys(CORE_FEATURES + mkt_cols + extra_cols))
    excl = set(exclude_cols)
    # Causal pre-WF (<= 2022-12-31) non-degeneracy gate: drops constant or 1-outlier sparse features
    # that otherwise bypass _wf_core's len(uniq) <= 3 branch and inflate |t|. Zero post-2022 lookahead!
    w = df[df["buy_date"] <= "2022-12-31"]
    clean = []
    for c in cand:
        if c not in df.columns or c in excl or not pd.api.types.is_numeric_dtype(df[c]):
            continue
        s = w[c].dropna()
        if len(s) < 35:
            continue
        vc = s.value_counts()
        if len(vc) <= 1:
            continue
        if len(vc) <= 3 and int(vc.min()) < 15:
            continue
        clean.append(c)
    return clean


def _sanitize(obj):
    if isinstance(obj, dict):
        return {str(k): _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return None if (np.isnan(v) or np.isinf(v)) else round(v, 6)
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    return obj


def _compute_v20_correlation(slot_df: pd.DataFrame, v20_ctx: dict, wf_start_dt: str, end_dt: str) -> dict:
    """Compute Pearson correlation of track daily MTM returns vs V20 baseline over WF calendar."""
    cal_df = v20_ctx["calendar_5y"]
    cal_win = cal_df[cal_df["trade_date"].between(wf_start_dt, end_dt)].sort_values("trade_date").reset_index(drop=True)
    cal_dts = cal_win["trade_date"].tolist()
    v20_dr = cal_win["v20_daily_ret"].fillna(0.0).to_numpy(float)
    tr_dr, _ = wfm.build_daily_mtm_returns(slot_df, cal_dts)
    corr_all = float(np.corrcoef(tr_dr, v20_dr)[0, 1]) if (np.std(tr_dr) > 1e-12 and np.std(v20_dr) > 1e-12) else 0.0
    both_act = (np.abs(tr_dr) > 1e-10) & (np.abs(v20_dr) > 1e-10)
    corr_both = float(np.corrcoef(tr_dr[both_act], v20_dr[both_act])[0, 1]) if (both_act.sum() >= 5 and np.std(tr_dr[both_act]) > 1e-12 and np.std(v20_dr[both_act]) > 1e-12) else None
    track_act = np.abs(tr_dr) > 1e-10
    corr_track_act = float(np.corrcoef(tr_dr[track_act], v20_dr[track_act])[0, 1]) if (track_act.sum() >= 5 and np.std(tr_dr[track_act]) > 1e-12 and np.std(v20_dr[track_act]) > 1e-12) else None
    return {
        "n_wf_days": int(len(cal_dts)),
        "n_track_active_days": int(track_act.sum()),
        "n_both_active_days": int(both_act.sum()),
        "corr_v20_all_days": round(corr_all, 4),
        "corr_v20_track_active_days": round(corr_track_act, 4) if corr_track_act is not None else None,
        "corr_v20_both_active_days": round(corr_both, 4) if corr_both is not None else None,
    }


def _eval_full_5y_baseline(df: pd.DataFrame, bench_df: pd.DataFrame, start_dt: str = "2021-11-16", end_dt: str = "2026-11-16") -> dict:
    """Evaluate full 5Y (and sub-windows) unfiltered single-slot & daily-EW baseline with 0.30% RT friction."""
    sub = wfm.prepare_hygiene_and_net_ret(df, fee_rt=0.0030, gross_ret_col="gross_ret")
    sub = sub[sub["can_buy_hygiene"] & sub["buy_date"].between(start_dt, end_dt)].copy()
    if sub.empty:
        return {"n_raw": 0}
    _, slot = wfm.select_single_slot_trades(sub.assign(wf_score=100.0), score_col="wf_score", threshold=None, wf_only=False)
    ev = wfm.evaluate_wf_ledger(slot, sub, sub, bench_df, wf_start_dt=start_dt, end_dt=end_dt, perm_n=100, seed=20261125)
    # Also compute explicit 2021-11-16~2026-11-16 full window
    b = bench_df[bench_df["trade_date"].between(start_dt, end_dt)].sort_values("trade_date").reset_index(drop=True)
    cal_dts = b["trade_date"].tolist()
    dt_idx = {d: i for i, d in enumerate(cal_dts)}
    dr_full, _ = wfm.build_daily_mtm_returns(slot, cal_dts)
    full_5y = wfm._calc_one_window(slot, sub, dr_full, cal_dts, dt_idx, b["csi300_daily_ret"].to_numpy(float), b["alla_ew_daily_ret"].to_numpy(float), start_dt, end_dt)
    eq_mean_pct = float(sub.groupby("buy_date")["net_ret"].mean().mean() * 100.0)
    raw_wr = float((sub["net_ret"] > 0).mean() * 100.0)
    raw_mean = float(sub["net_ret"].mean() * 100.0)
    return {
        "window": f"{start_dt} ~ {end_dt}",
        "n_cands": int(len(sub)),
        "raw_wr_pct": round(raw_wr, 2),
        "raw_mean_pct": round(raw_mean, 2),
        "daily_ew_mean_pct": round(eq_mean_pct, 2),
        "single_slot_5y": full_5y,
        "sub_windows": ev["windows"],
    }


def _evaluate_track(
    track_id: str,
    label: str,
    df: pd.DataFrame,
    feature_cols: list[str],
    v20_ctx: dict,
    thresholds: tuple = ("all_cands", "top30", "top20", "top10", "top5", 65, 70, 75, 80, 85),
    run_trunc_proof: bool = False,
) -> tuple[dict, list[dict], dict]:
    """Run WF scorecard + V20 patch + V20 corr + truncation proof for one track/variant."""
    t0 = time.time()
    res = wf.run_wf_scorecard_new_strategy(
        df,
        feature_cols=feature_cols,
        v20_ctx=v20_ctx,
        wf_start_date="2023-01-03",
        end_date="2026-11-16",
        min_warmup_trades=80,
        min_warmup_trades_rare=60,
        min_warmup_months=18,
        recalc_freq="daily",
        top_k=12,
        min_k=5,
        max_corr=0.65,
        min_t_stat=1.0,
        shrink_tau=20.0,
        fee_rt=0.0030,
        gross_ret_col="gross_ret",
        thresholds=thresholds,
        eval_v20_patch=True,
        perm_n=1000,
        seed=20261125,
    )

    actual_wf_start = res["meta"]["wf_actual_start"] or "2023-01-03"
    # Also compute V20 empty-slot patch for all_cands baseline
    all_tr = res["threshold_results"]["all_cands"]
    if all_tr["v20_empty_patch"] is None and not all_tr["pass_df"].empty:
        all_tr["v20_empty_patch"] = wf.simulate_v20_empty_slot_patch(
            all_tr["pass_df"], v20_ctx=v20_ctx, wf_start_dt=actual_wf_start, end_dt="2026-11-16", score_col="wf_score"
        )

    trunc_res = None
    if run_trunc_proof:
        trunc_res = wf.verify_truncation_zero_leakage(
            df, feature_cols, mode="A", cutoff="2024-12-31", score_threshold="top10",
            v20_ctx=v20_ctx, wf_start_date="2023-01-03", end_date="2026-11-16",
            min_warmup_trades=80, min_warmup_trades_rare=60, min_warmup_months=18,
            recalc_freq="daily", top_k=12, min_k=5, max_corr=0.65, min_t_stat=1.0,
            shrink_tau=20.0, fee_rt=0.0030, gross_ret_col="gross_ret",
        )

    csv_rows = []
    thr_details = {}
    for th in thresholds:
        tname = str(th) if not isinstance(th, (int, float)) else f"abs_{int(th)}"
        tr = res["threshold_results"][tname]
        ev = tr["metrics"]
        slot_df = tr["slot_df"]
        fw = ev["windows"].get("FULL_WF", {})
        y2526 = ev["windows"].get("Y2025_2026", {})
        y26 = ev["windows"].get("Y2026", {})
        perm = ev["permutation_1000"]
        corr_v20 = _compute_v20_correlation(slot_df, v20_ctx, actual_wf_start, "2026-11-16")

        vp = tr["v20_empty_patch"]
        m1 = vp["mode1_strict_combined_no_peek"] if vp else None
        m2 = vp["mode2_empty_slot_standalone"] if vp else None
        m1_base = m1["v20_baseline"]["FULL_WF"] if m1 else {}
        m1_comb = m1["combined_with_patch"]["FULL_WF"] if m1 else {}
        m2_fw = m2["windows"]["FULL_WF"] if m2 else {}
        m2_2526 = m2["windows"].get("Y2025_2026", {}) if m2 else {}
        m2_y26 = m2["windows"].get("Y2026", {}) if m2 else {}

        csv_rows.append({
            "track": track_id,
            "label": label,
            "threshold": tname,
            "wf_start": actual_wf_start,
            "wf_end": "2026-11-16",
            "n_pass": tr["n_passing_cands"],
            "n_trades": fw.get("n", 0),
            "wr_pct": fw.get("wr_pct", 0.0),
            "plr": fw.get("plr", 0.0),
            "mean_pct": fw.get("mean_pct", 0.0),
            "nav_wf": fw.get("nav", 1.0),
            "ex3_wf": fw.get("ex_top3_nav", 1.0),
            "ex5_wf": fw.get("ex_top5_nav", 1.0),
            "daily_mdd_pct": fw.get("daily_mdd_pct", 0.0),
            "trade_mdd_pct": fw.get("trade_mdd_pct", 0.0),
            "sharpe": fw.get("daily_sharpe", 0.0),
            "excess_csi300_pp": fw.get("excess_csi300_pp", 0.0),
            "excess_alla_ew_pp": fw.get("excess_alla_ew_pp", 0.0),
            "n_2526": y2526.get("n", 0),
            "wr_2526_pct": y2526.get("wr_pct", 0.0),
            "nav_2526": y2526.get("nav", 1.0),
            "ex5_2526": y2526.get("ex_top5_nav", 1.0),
            "excess_csi_2526_pp": y2526.get("excess_csi300_pp", 0.0),
            "n_y26": y26.get("n", 0),
            "wr_y26_pct": y26.get("wr_pct", 0.0),
            "nav_y26": y26.get("nav", 1.0),
            "excess_csi_y26_pp": y26.get("excess_csi300_pp", 0.0),
            "perm_sd_p": perm.get("same_day_p_nav", 1.0),
            "perm_any_p": perm.get("any_cand_day_p_nav", 1.0),
            "corr_v20_all_days": corr_v20["corr_v20_all_days"],
            "corr_v20_track_act": corr_v20["corr_v20_track_active_days"],
            "v20_base_nav": m1_base.get("nav"),
            "v20_base_sharpe": m1_base.get("daily_sharpe"),
            "v20_base_mdd": m1_base.get("daily_mdd_pct"),
            "v20_comb_nav": m1_comb.get("nav"),
            "v20_comb_sharpe": m1_comb.get("daily_sharpe"),
            "v20_comb_mdd": m1_comb.get("daily_mdd_pct"),
            "v20_comb_delta_ratio": m1.get("delta_nav_ratio_full_wf") if m1 else None,
            "v20_comb_delta_sharpe": m1.get("delta_sharpe_full_wf") if m1 else None,
            "v20_comb_delta_mdd_pp": m1.get("delta_mdd_pp_full_wf") if m1 else None,
            "v20_patch_added_n": m1.get("n_patch_added") if m1 else None,
            "v20_skipped_cnt": m1.get("n_v20_skipped_by_collision") if m1 else None,
            "v20_skipped_prod": m1.get("skipped_v20_net_ret_prod") if m1 else None,
            "emp_n": m2_fw.get("n"),
            "emp_wr_pct": m2_fw.get("wr_pct"),
            "emp_plr": m2_fw.get("plr"),
            "emp_nav": m2_fw.get("nav"),
            "emp_ex5_nav": m2_fw.get("ex_top5_nav"),
            "emp_mdd_pct": m2_fw.get("daily_mdd_pct"),
            "emp_2526_nav": m2_2526.get("nav"),
            "emp_y26_nav": m2_y26.get("nav"),
            "emp_collision_pct": m2.get("collision_rate_pct") if m2 else None,
            "trunc_20241231_pass": trunc_res["zero_leakage_pass"] if trunc_res else None,
        })

        thr_details[tname] = {
            "n_passing_cands": tr["n_passing_cands"],
            "windows": ev["windows"],
            "permutation_1000": perm,
            "v20_correlation": corr_v20,
            "v20_empty_patch": {
                "mode1_strict_combined_no_peek": {k: v for k, v in m1.items() if k != "skipped_v20_trades"} if m1 else None,
                "mode2_empty_slot_standalone": m2,
            },
        }

    latest_card = res["meta"]["latest_scorecard"]
    audit_obj = {
        "track": track_id,
        "label": label,
        "elapsed_sec": round(time.time() - t0, 2),
        "n_input_rows": int(len(df)),
        "n_features": int(len(feature_cols)),
        "wf_actual_start": actual_wf_start,
        "n_daily_rebuilds": res["meta"]["n_rebuilds"],
        "baseline_5y_unfiltered": _eval_full_5y_baseline(df, v20_ctx["bench"]),
        "truncation_20241231": trunc_res,
        "latest_scorecard_factors": [
            {
                "name": f["name"], "t": f["t_cluster"], "shape": f["shape"],
                "budget_pts": f["budget_pts"], "bin_pts": f["bin_pts"],
                "bin_cnts": f["bin_cnts"], "bin_wr_pct": f["bin_wr_pct"], "bin_mean_pct": f["bin_mean_pct"],
            }
            for f in (latest_card["factors"] if latest_card else [])
        ],
        "thresholds": thr_details,
    }
    print(f"[{track_id}] done in {audit_obj['elapsed_sec']}s (n={len(df)}, F={len(feature_cols)}, wf_start={actual_wf_start})")
    return audit_obj, csv_rows, res


def main():
    t_all = time.time()
    v20_ctx = wf.load_v20_reference_context(WAVE1_BASE)

    pA = pd.read_parquet(f"{OUT_DIR}/pool_A_temp5b_pit.parquet")
    pB = pd.read_parquet(f"{OUT_DIR}/pool_B_b4_wave2_pit.parquet")
    pC = pd.read_parquet(f"{OUT_DIR}/pool_C_ndmb_2b3b_pit.parquet")
    pD = pd.read_parquet(f"{OUT_DIR}/pool_D_surge_crash_pit.parquet")
    pDr = pd.read_parquet(f"{OUT_DIR}/pool_D_reb1b_pit.parquet")

    all_csv_rows = []
    audits = {}
    best_candidates = []  # store (track_id, tname, row_summary, slot_df)

    # --- TRACK A: Temp 5B ---
    fA = _get_feature_list(pA, ["t5_selected_height", "t5_five_to_buy_days", "t5_streak_yizi_cnt", "t5_streak_turn_avg", "t5_last_turn_pct"])
    auA, rowsA, resA = _evaluate_track("A_temp5b", "赛道A_临时五板_5年全量打分制", pA, fA, v20_ctx, run_trunc_proof=True)
    # Add Temp5B 2026-07-01+ & lock>=50 special diagnostics
    pA_eval = wfm.prepare_hygiene_and_net_ret(pA, fee_rt=0.0030, gross_ret_col="gross_ret")
    pA_2607 = pA_eval[pA_eval["five_date"] >= "2026-07-01"]
    pA_scored = resA["scored_df"]
    pA_wf_2607 = pA_scored[pA_scored["wf_in_window"] & (pA_scored["five_date"] >= "2026-07-01")]
    auA["temp5b_special_diagnostics"] = {
        "full_5y_lock_ge50": _eval_full_5y_baseline(pA[pA["lock_top10_pct_pre"] >= 50.0], v20_ctx["bench"]),
        "full_5y_lock_lt50": _eval_full_5y_baseline(pA[pA["lock_top10_pct_pre"] < 50.0], v20_ctx["bench"]),
        "since_20260701_all": {"n": int(len(pA_2607)), "wr_pct": round(float((pA_2607["net_ret"] > 0).mean() * 100), 2), "mean_pct": round(float(pA_2607["net_ret"].mean() * 100), 2)},
        "since_20260701_lock_ge50": {"n": int((pA_2607["lock_top10_pct_pre"] >= 50).sum()), "wr_pct": round(float((pA_2607[pA_2607["lock_top10_pct_pre"] >= 50]["net_ret"] > 0).mean() * 100), 2), "mean_pct": round(float(pA_2607[pA_2607["lock_top10_pct_pre"] >= 50]["net_ret"].mean() * 100), 2)},
        "since_20260701_wf_top20": {"n": int((pA_wf_2607["wf_score"] >= pA_wf_2607["wf_thr_top20"]).sum()), "wr_pct": round(float((pA_wf_2607[pA_wf_2607["wf_score"] >= pA_wf_2607["wf_thr_top20"]]["net_ret"] > 0).mean() * 100), 2) if (pA_wf_2607["wf_score"] >= pA_wf_2607["wf_thr_top20"]).any() else 0.0, "mean_pct": round(float(pA_wf_2607[pA_wf_2607["wf_score"] >= pA_wf_2607["wf_thr_top20"]]["net_ret"].mean() * 100), 2) if (pA_wf_2607["wf_score"] >= pA_wf_2607["wf_thr_top20"]).any() else 0.0},
    }
    audits["A_temp5b"] = auA
    all_csv_rows.extend(rowsA)
    best_candidates.append(("A_temp5b", rowsA, resA))

    # --- TRACK B: B4 Break Wave 2 (unified + 3 subtypes) ---
    fB = _get_feature_list(pB, ["b4_subtype", "b4_peak_streak", "b4_adj_days", "b4_brk_ret", "b4_brk_is_yang", "b4_brk_clv", "b4_dd_from_peak_t1", "b4_vol_shrink_ratio"])
    auB, rowsB, resB = _evaluate_track("B_b4_wave2", "赛道B_四板断板调整1至5日二波", pB, fB, v20_ctx, run_trunc_proof=True)
    audits["B_b4_wave2"] = auB
    all_csv_rows.extend(rowsB)
    best_candidates.append(("B_b4_wave2", rowsB, resB))

    for sub_id, sub_lbl in [(1, "B1_turn_red_0_55"), (2, "B2_deep_dip"), (3, "B3_reb1b_nextopen")]:
        pB_sub = pB[pB["b4_subtype"] == sub_id].copy().reset_index(drop=True)
        if len(pB_sub) >= 120:
            fBs = _get_feature_list(pB_sub, ["b4_peak_streak", "b4_adj_days", "b4_brk_ret", "b4_brk_is_yang", "b4_brk_clv", "b4_dd_from_peak_t1", "b4_vol_shrink_ratio"])
            auBs, rowsBs, _ = _evaluate_track(sub_lbl, f"赛道B子项_{sub_lbl}", pB_sub, fBs, v20_ctx, thresholds=("all_cands", "top30", "top20", "top10", 70, 75), run_trunc_proof=False)
            audits[sub_lbl] = auBs
            all_csv_rows.extend(rowsBs)

    # --- TRACK C: 2B/3B Break Rebound ---
    fC = _get_feature_list(pC, ["c_prior_streak", "c_d1_is_yang", "c_d1_is_true_yin", "c_d1_is_fake_yin", "c_d1_lower_shad", "c_d1_ret", "c_d1_clv", "c_d1_turn_ratio", "c_open_sweet_red", "c_open_green"])
    auC, rowsC, resC = _evaluate_track("C_ndmb_2b3b", "赛道C_2板3板断板次日弱转强", pC, fC, v20_ctx, run_trunc_proof=True)
    audits["C_ndmb_2b3b"] = auC
    all_csv_rows.extend(rowsC)
    best_candidates.append(("C_ndmb_2b3b", rowsC, resC))

    for c_tag, c_mask in [
        ("C1_red_0_55", pC["c_open_sweet_red"] == 1.0),
        ("C2_trueyin_brk", pC["c_d1_is_true_yin"] == 1.0),
        ("C3_yang_brk", pC["c_d1_is_yang"] == 1.0),
        ("C4_3b_only", pC["c_prior_streak"] == 3),
    ]:
        pCs = pC[c_mask].copy().reset_index(drop=True)
        fCs = _get_feature_list(pCs, ["c_prior_streak", "c_d1_is_yang", "c_d1_is_true_yin", "c_d1_lower_shad", "c_d1_ret", "c_d1_clv", "c_d1_turn_ratio", "c_open_sweet_red"])
        auCs, rowsCs, _ = _evaluate_track(c_tag, f"赛道C切片_{c_tag}", pCs, fCs, v20_ctx, thresholds=("all_cands", "top30", "top20", "top10", 70, 75), run_trunc_proof=False)
        audits[c_tag] = auCs
        all_csv_rows.extend(rowsCs)

    # --- TRACK D: Surge Crash Rebound + 排雷分家 ---
    mine_cols = ("mine_tox_reg", "mine_abn_notice", "mine_prev_dt", "mine_lhasa_heavy", "mine_nuclear_open", "mine_unstopped_knife", "mine_any_cnt", "is_mine_cleared")
    fD_raw = _get_feature_list(pD, ["d_surge_pct", "d_surge_lu_cnt", "d_surge_max_streak", "d_crash_days", "d_crash_ld_cnt", "d_dd_from_peak_t1", "d_vol_shrink_ratio", "d_t1_is_yang", "mine_any_cnt", "is_mine_cleared"])
    auD_raw, rowsD_raw, resD_raw = _evaluate_track("D_raw", "赛道D_暴涨暴跌2至4日反抽_全量未排雷", pD, fD_raw, v20_ctx, run_trunc_proof=True)
    audits["D_raw"] = auD_raw
    all_csv_rows.extend(rowsD_raw)

    # 排雷分家: Minefield-cleared pool, excluding mine_* from Alpha scorecard
    pD_clr = pD[pD["is_mine_cleared"] == 1].copy().reset_index(drop=True)
    fD_clr = _get_feature_list(pD_clr, ["d_surge_pct", "d_surge_lu_cnt", "d_surge_max_streak", "d_crash_days", "d_crash_ld_cnt", "d_dd_from_peak_t1", "d_vol_shrink_ratio", "d_t1_is_yang"], exclude_cols=mine_cols + ("tox_reg_30d_pre", "abn_notice_30d_pre", "drv_has_reg_or_tox"))
    auD_clr, rowsD_clr, resD_clr = _evaluate_track("D_cleared", "赛道D_暴涨暴跌_排雷分家净池", pD_clr, fD_clr, v20_ctx, run_trunc_proof=True)
    pD_rej = pD[pD["is_mine_cleared"] == 0].copy().reset_index(drop=True)
    auD_clr["minefield_separation_audit"] = {
        "n_raw": int(len(pD)),
        "n_cleared": int(len(pD_clr)),
        "n_rejected_by_minefield": int(len(pD_rej)),
        "rejected_5y_baseline": _eval_full_5y_baseline(pD_rej, v20_ctx["bench"]),
        "cleared_5y_baseline": _eval_full_5y_baseline(pD_clr, v20_ctx["bench"]),
    }
    audits["D_cleared"] = auD_clr
    all_csv_rows.extend(rowsD_clr)
    best_candidates.append(("D_cleared", rowsD_clr, resD_clr))

    # Track D T+3 hold sensitivity + D_reb1b
    pD_t3 = pD_clr[pD_clr["gross_ret_t3"].notna() & (pD_clr["exit_date_t3"] != "")].copy().reset_index(drop=True)
    pD_t3["gross_ret"] = pD_t3["gross_ret_t3"]
    pD_t3["exit_date"] = pD_t3["exit_date_t3"]
    auD_t3, rowsD_t3, _ = _evaluate_track("D_cleared_T3", "赛道D_排雷净池_T3收盘卖对照", pD_t3, fD_clr, v20_ctx, thresholds=("all_cands", "top20", "top10", 70, 75), run_trunc_proof=False)
    audits["D_cleared_T3"] = auD_t3
    all_csv_rows.extend(rowsD_t3)

    fDr = _get_feature_list(pDr, ["d_surge_pct", "d_surge_max_streak", "d_crash_days", "d_dd_from_peak_t1"])
    auDr, rowsDr, _ = _evaluate_track("D_reb1b", "赛道D_暴涨暴跌反抽首板次日", pDr, fDr, v20_ctx, thresholds=("all_cands", "top20", "top10", 70, 75), run_trunc_proof=False)
    audits["D_reb1b"] = auDr
    all_csv_rows.extend(rowsDr)

    # --- TRACK E: Unified 4-Track Pool (All vs Cleared-D) ---
    def _build_unified(df_d_use: pd.DataFrame, tag: str) -> pd.DataFrame:
        parts = []
        for idx_t, (nm, d_part) in enumerate([("A", pA), ("B", pB), ("C", pC), ("D", df_d_use)], start=1):
            dp = d_part.copy()
            dp["track_id_num"] = float(idx_t)
            dp["is_track_A"] = 1.0 if nm == "A" else 0.0
            dp["is_track_B"] = 1.0 if nm == "B" else 0.0
            dp["is_track_C"] = 1.0 if nm == "C" else 0.0
            dp["is_track_D"] = 1.0 if nm == "D" else 0.0
            parts.append(dp)
        # Align columns cleanly
        common_cols = sorted(set.intersection(*[set(p.columns) for p in parts]))
        u = pd.concat([p[common_cols] for p in parts], ignore_index=True)
        # Priority on exact (buy_date, code) overlap: A (1) > B (2) > C (3) > D (4)
        u = u.sort_values(["buy_date", "code", "track_id_num"], ascending=[True, True, True]).drop_duplicates(["buy_date", "code"], keep="first").reset_index(drop=True)
        return u

    pE_all = _build_unified(pD, "all")
    fE_all = _get_feature_list(pE_all, ["track_id_num", "is_track_A", "is_track_B", "is_track_C", "is_track_D", "mine_any_cnt", "is_mine_cleared"])
    auE_all, rowsE_all, resE_all = _evaluate_track("E_unified_all", "赛道E_四子赛道全量联合池", pE_all, fE_all, v20_ctx, run_trunc_proof=False)
    audits["E_unified_all"] = auE_all
    all_csv_rows.extend(rowsE_all)

    pE_clr = _build_unified(pD_clr, "cleared")
    fE_clr = _get_feature_list(pE_clr, ["track_id_num", "is_track_A", "is_track_B", "is_track_C", "is_track_D"])
    auE_clr, rowsE_clr, resE_clr = _evaluate_track("E_unified_cleared", "赛道E_四子赛道联合池_含D排雷", pE_clr, fE_clr, v20_ctx, run_trunc_proof=True)
    audits["E_unified_cleared"] = auE_clr
    all_csv_rows.extend(rowsE_clr)
    best_candidates.append(("E_unified_cleared", rowsE_clr, resE_clr))

    # Save tracks compare CSV
    cmp_df = pd.DataFrame(all_csv_rows)
    cmp_csv_path = f"{OUT_DIR}/w2b2_tracks_compare.csv"
    cmp_df.to_csv(cmp_csv_path, index=False, encoding="utf-8-sig")

    # Check if any genuine WF winner exists
    # Genuine winner criteria: n_trades >= 20, nav_wf > 1.0, ex5_wf > 1.0, excess_csi300_pp > 0, perm_any_p < 0.05
    # AND/OR V20 combined patch delta_nav_ratio > 1.05 & delta_sharpe > 0 & emp_nav > 1.0
    scored_rows = cmp_df[cmp_df["threshold"] != "all_cands"].copy()
    genuine = scored_rows[
        (scored_rows["n_trades"] >= 20)
        & (scored_rows["nav_wf"] > 1.0)
        & (scored_rows["ex5_wf"] > 1.0)
        & (scored_rows["excess_csi300_pp"] > 0.0)
        & (scored_rows["perm_any_p"] < 0.05)
    ].sort_values(["sharpe", "nav_wf"], ascending=False)

    patch_winners = scored_rows[
        (scored_rows["v20_comb_delta_ratio"].fillna(0.0) > 1.05)
        & (scored_rows["v20_comb_delta_sharpe"].fillna(-99.0) > 0.0)
        & (scored_rows["emp_nav"].fillna(0.0) > 1.0)
        & (scored_rows["emp_ex5_nav"].fillna(0.0) > 1.0)
    ].sort_values(["v20_comb_delta_sharpe", "v20_comb_delta_ratio"], ascending=False)

    best_saved_path = None
    best_winner_info = None
    if not genuine.empty:
        top_w = genuine.iloc[0]
        tid, th_nm = str(top_w["track"]), str(top_w["threshold"])
        best_winner_info = top_w.to_dict()
        for c_tid, _, c_res in best_candidates:
            if c_tid == tid and th_nm in c_res["threshold_results"]:
                best_df = c_res["threshold_results"][th_nm]["slot_df"].copy()
                best_saved_path = f"{OUT_DIR}/w2b2_best_trades.parquet"
                best_df.to_parquet(best_saved_path, index=False)
                break
    elif not patch_winners.empty:
        top_w = patch_winners.iloc[0]
        tid, th_nm = str(top_w["track"]), str(top_w["threshold"])
        best_winner_info = top_w.to_dict()
        for c_tid, _, c_res in best_candidates:
            if c_tid == tid and th_nm in c_res["threshold_results"]:
                best_df = c_res["threshold_results"][th_nm]["slot_df"].copy()
                best_saved_path = f"{OUT_DIR}/w2b2_best_trades.parquet"
                best_df.to_parquet(best_saved_path, index=False)
                break

    rss_mb = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 2)
    final_audit = _sanitize({
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t_all, 2),
        "peak_rss_mb": rss_mb,
        "d12_yfinance_imported": "yfinance" in sys.modules,
        "friction_rt": 0.0030,
        "wf_window": "2023-01-03 ~ 2026-11-16",
        "v20_baseline_wf": {
            "n_trades": int(len(v20_ctx["v20_ledger"][v20_ctx["v20_ledger"]["buy_date"].between("2023-01-03", "2026-11-16")])),
            "full_wf": resA["threshold_results"]["top10"]["v20_empty_patch"]["mode1_strict_combined_no_peek"]["v20_baseline"]["FULL_WF"],
            "y2025_2026": resA["threshold_results"]["top10"]["v20_empty_patch"]["mode1_strict_combined_no_peek"]["v20_baseline"]["Y2025_2026"],
            "y2026": resA["threshold_results"]["top10"]["v20_empty_patch"]["mode1_strict_combined_no_peek"]["v20_baseline"]["Y2026"],
        },
        "genuine_standalone_winners_cnt": int(len(genuine)),
        "genuine_patch_winners_cnt": int(len(patch_winners)),
        "best_winner_summary": best_winner_info,
        "best_trades_parquet": best_saved_path,
        "tracks_compare_csv": cmp_csv_path,
        "tracks": audits,
    })
    audit_path = f"{OUT_DIR}/w2b2_audit.json"
    with open(audit_path, "w", encoding="utf-8") as f:
        json.dump(final_audit, f, ensure_ascii=False, indent=2, allow_nan=False)

    print(f"\n[Step2 DONE in {final_audit['elapsed_sec']}s | Peak RSS={rss_mb}MB]")
    print(f"  Genuine standalone winners: {len(genuine)} | V20 patch winners: {len(patch_winners)} | best_trades: {best_saved_path}")
    assert rss_mb < 2000.0, f"Peak RSS exceeded 2.0GB: {rss_mb}MB"


if __name__ == "__main__":
    main()

#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Public Day-by-Day Expanding Walk-Forward Scorecard Engine (`wf_scorecard_engine.py`).

Provides unified, vectorized, strictly zero-leakage (exit_date < t) Walk-Forward evaluation
for all Wave 2 research agents (6 V20.0 strategy upgrades + 5 new/empty-slot tracks):
  - Mode A (`run_wf_scorecard_new_strategy`): 0..100 integer scorecard + causal threshold tests.
  - Mode B (`run_wf_scorecard_patch_v20`): orig_score + bounded wf_delta_score (+-15 / +-25).
  - Empty-slot patch (`simulate_v20_empty_slot_patch`): strict no-peek combined + standalone.
  - Physical truncation proof (`verify_truncation_zero_leakage`): asserts max_abs_diff == 0.0.

Zero yfinance (D12). Zero cap10m. Read-only on production scripts and strategy_astock.md.
"""
import os
import sys
import time
from typing import Callable, Optional

import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)

import _wf_core as wfc
import _wf_sim_and_metrics as wfm
import _wf_v20_patch as wfp

load_v20_reference_context = wfp.load_v20_reference_context
simulate_v20_empty_slot_patch = wfp.simulate_v20_empty_slot_patch
evaluate_wf_ledger = wfm.evaluate_wf_ledger
select_single_slot_trades = wfm.select_single_slot_trades
prepare_hygiene_and_net_ret = wfm.prepare_hygiene_and_net_ret
build_daily_mtm_returns = wfm.build_daily_mtm_returns


def run_wf_scorecard_new_strategy(
    cand_df: pd.DataFrame,
    feature_cols: list[str],
    v20_ctx: Optional[dict] = None,
    wf_start_date: str = "2023-01-03",
    end_date: Optional[str] = None,
    min_warmup_trades: int = 80,
    min_warmup_trades_rare: int = 60,
    min_warmup_months: int = 18,
    recalc_freq: str = "daily",
    top_k: int = 12,
    min_k: int = 5,
    max_corr: float = 0.65,
    min_t_stat: float = 1.0,
    shrink_tau: float = 20.0,
    fee_rt: float = 0.0030,
    gross_ret_col: Optional[str] = None,
    tie_col: Optional[str] = None,
    mtm_col: Optional[str] = None,
    thresholds: tuple = ("all_cands", "top30", "top20", "top10", "top5", 70, 75, 80, 85),
    eval_v20_patch: bool = True,
    perm_n: int = 1000,
    seed: int = 20261125,
) -> dict:
    """
    Mode A: Day-by-day expanding 0..100 integer scorecard for new strategies or empty-slot tracks.
    """
    t0 = time.time()
    if v20_ctx is None:
        v20_ctx = load_v20_reference_context()

    df_h = prepare_hygiene_and_net_ret(cand_df, fee_rt=fee_rt, gross_ret_col=gross_ret_col)
    if end_date is not None:
        df_h = df_h[df_h["buy_date"] <= end_date].copy()
    else:
        end_date = str(df_h["buy_date"].max()) if not df_h.empty else "2026-11-25"
    # Align evaluation horizon to bench calendar max if needed
    bench_df = v20_ctx["bench"]
    max_bench_dt = str(bench_df["trade_date"].max())
    eval_end_dt = min(max_bench_dt, max(end_date, "2026-11-16")) if end_date <= max_bench_dt else max_bench_dt

    scored_df, core_meta = wfc.run_expanding_scorecard_loop(
        df_h,
        feature_cols=feature_cols,
        mode="scorecard_0_100",
        wf_start_date=wf_start_date,
        min_warmup_trades=min_warmup_trades,
        min_warmup_trades_rare=min_warmup_trades_rare,
        min_warmup_months=min_warmup_months,
        recalc_freq=recalc_freq,
        top_k=top_k,
        min_k=min_k,
        max_corr=max_corr,
        min_t_stat=min_t_stat,
        shrink_tau=shrink_tau,
        save_snapshot_freq="monthly",
    )

    actual_wf_start = core_meta["wf_actual_start"] or wf_start_date
    wf_cands = scored_df[scored_df["wf_in_window"]].copy()

    thr_map = {
        "all_cands": None,
        "top30": "wf_thr_top30",
        "top20": "wf_thr_top20",
        "top10": "wf_thr_top10",
        "top5": "wf_thr_top5",
    }
    results = {}
    summary_rows = []

    for th in thresholds:
        tname = str(th) if not isinstance(th, (int, float)) else f"abs_{int(th)}"
        t_arg = thr_map[th] if th in thr_map else float(th)
        pass_df, slot_df = select_single_slot_trades(
            scored_df, score_col="wf_score", threshold=t_arg, tie_col=tie_col, wf_only=True
        )
        ev = evaluate_wf_ledger(
            slot_df, pass_df, wf_cands, bench_df,
            wf_start_dt=actual_wf_start, end_dt=eval_end_dt,
            mtm_col=mtm_col, perm_n=perm_n, seed=seed,
        )
        patch_res = None
        if eval_v20_patch and not pass_df.empty and th != "all_cands":
            patch_end = min(eval_end_dt, "2026-11-16")
            patch_res = simulate_v20_empty_slot_patch(
                pass_df, v20_ctx=v20_ctx, wf_start_dt=actual_wf_start, end_dt=patch_end,
                score_col="wf_score", patch_mtm_col=mtm_col,
            )

        results[tname] = {
            "threshold_name": tname,
            "n_passing_cands": int(len(pass_df)),
            "metrics": ev,
            "v20_empty_patch": patch_res,
            "slot_df": slot_df,
            "pass_df": pass_df,
        }
        fw = ev["windows"].get("FULL_WF", {})
        y2526 = ev["windows"].get("Y2025_2026", {})
        y26 = ev["windows"].get("Y2026", {})
        p_sd = ev["permutation_1000"]["same_day_p_nav"]
        p_any = ev["permutation_1000"]["any_cand_day_p_nav"]
        summary_rows.append({
            "threshold": tname,
            "n_pass": int(len(pass_df)),
            "n_trades": fw.get("n", 0),
            "wr_pct": fw.get("wr_pct", 0.0),
            "plr": fw.get("plr", 0.0),
            "mean_pct": fw.get("mean_pct", 0.0),
            "nav_wf": fw.get("nav", 1.0),
            "ex3_wf": fw.get("ex_top3_nav", 1.0),
            "ex5_wf": fw.get("ex_top5_nav", 1.0),
            "mdd_pct": fw.get("daily_mdd_pct", 0.0),
            "sharpe": fw.get("daily_sharpe", 0.0),
            "excess_csi_pp": fw.get("excess_csi300_pp", 0.0),
            "excess_ew_pp": fw.get("excess_alla_ew_pp", 0.0),
            "nav_2526": y2526.get("nav", 1.0),
            "ex3_2526": y2526.get("ex_top3_nav", 1.0),
            "nav_y26": y26.get("nav", 1.0),
            "perm_sd_p": p_sd,
            "perm_any_p": p_any,
        })

    return {
        "mode": "A_NEW_SCORECARD_0_100",
        "elapsed_sec": round(time.time() - t0, 3),
        "meta": core_meta,
        "scored_df": scored_df,
        "threshold_results": results,
        "summary_table": pd.DataFrame(summary_rows),
    }


def run_wf_scorecard_patch_v20(
    cand_df: pd.DataFrame,
    feature_cols: list[str],
    orig_score_col: str = "v20_score",
    strat_name: Optional[str] = None,
    sim_fn: Optional[Callable[[pd.DataFrame, np.ndarray], tuple[pd.DataFrame, pd.DataFrame]]] = None,
    orig_threshold: Optional[float] = None,
    v20_ctx: Optional[dict] = None,
    wf_start_date: str = "2023-01-03",
    end_date: Optional[str] = None,
    min_warmup_trades: int = 80,
    min_warmup_trades_rare: int = 60,
    min_warmup_months: int = 18,
    recalc_freq: str = "daily",
    top_k: int = 10,
    min_k: int = 5,
    max_corr: float = 0.65,
    max_corr_orig: Optional[float] = 0.70,
    min_t_stat: float = 1.0,
    shrink_tau: float = 20.0,
    max_delta: int = 15,
    mtm_col: Optional[str] = None,
    perm_n: int = 1000,
    seed: int = 20261125,
) -> dict:
    """
    Mode B: Keep `orig_score` as base, fit bounded causal `wf_delta_score` in [-max_delta, +max_delta]
    from 5..12 orthogonal factors (exit_date < t), then compare new_score vs V20.0 baseline.
    """
    t0 = time.time()
    if v20_ctx is None:
        v20_ctx = load_v20_reference_context()

    df_h = prepare_hygiene_and_net_ret(cand_df, fee_rt=0.0020)
    if end_date is not None:
        df_h = df_h[df_h["buy_date"] <= end_date].copy()
    else:
        end_date = str(df_h["buy_date"].max()) if not df_h.empty else "2026-11-16"
    bench_df = v20_ctx["bench"]
    max_bench_dt = str(bench_df["trade_date"].max())
    eval_end_dt = min(max_bench_dt, max(end_date, "2026-11-16")) if end_date <= max_bench_dt else max_bench_dt

    scored_df, core_meta = wfc.run_expanding_scorecard_loop(
        df_h,
        feature_cols=feature_cols,
        mode="delta_patch",
        wf_start_date=wf_start_date,
        min_warmup_trades=min_warmup_trades,
        min_warmup_trades_rare=min_warmup_trades_rare,
        min_warmup_months=min_warmup_months,
        recalc_freq=recalc_freq,
        top_k=top_k,
        min_k=min_k,
        max_corr=max_corr,
        min_t_stat=min_t_stat,
        shrink_tau=shrink_tau,
        max_delta=max_delta,
        orig_score_col=orig_score_col,
        max_corr_orig=max_corr_orig,
        save_snapshot_freq="monthly",
    )

    delta_vec = scored_df["wf_delta_score"].to_numpy(float)
    zeros_vec = np.zeros(len(scored_df), dtype=float)

    if sim_fn is not None:
        base_pass, base_slot = sim_fn(scored_df, zeros_vec)
        patch_pass, patch_slot = sim_fn(scored_df, delta_vec)
    elif strat_name in ("1to2", "2to3", "3to4", "high", "pry", "20cm"):
        rd028_dir = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd028_old_hot_stock_6strat_5y_20261125"
        if rd028_dir not in sys.path:
            sys.path.insert(0, rd028_dir)
        import step4_mod_rules_and_sim as m1
        base_pass, base_slot = m1.sim_standalone(strat_name, scored_df, zeros_vec, high_cb_mode="v51_exact", cm20_thr=82.0)
        patch_pass, patch_slot = m1.sim_standalone(strat_name, scored_df, delta_vec, high_cb_mode="v51_exact", cm20_thr=82.0)
    else:
        base_pass, base_slot = select_single_slot_trades(scored_df, score_col=orig_score_col, threshold=orig_threshold, wf_only=False)
        patch_pass, patch_slot = select_single_slot_trades(scored_df, score_col="wf_new_score", threshold=orig_threshold, wf_only=False)

    actual_wf_start = core_meta["wf_actual_start"] or wf_start_date
    wf_cands = scored_df[scored_df["wf_in_window"]].copy()

    # Evaluate only WF period (>= actual_wf_start) for honest comparison
    base_wf_slot = base_slot[base_slot["buy_date"] >= actual_wf_start].reset_index(drop=True)
    patch_wf_slot = patch_slot[patch_slot["buy_date"] >= actual_wf_start].reset_index(drop=True)
    base_wf_pass = base_pass[base_pass["buy_date"] >= actual_wf_start].reset_index(drop=True)
    patch_wf_pass = patch_pass[patch_pass["buy_date"] >= actual_wf_start].reset_index(drop=True)

    ev_base = evaluate_wf_ledger(base_wf_slot, base_wf_pass, wf_cands, bench_df, wf_start_dt=actual_wf_start, end_dt=eval_end_dt, mtm_col=mtm_col, perm_n=perm_n, seed=seed)
    ev_patch = evaluate_wf_ledger(patch_wf_slot, patch_wf_pass, wf_cands, bench_df, wf_start_dt=actual_wf_start, end_dt=eval_end_dt, mtm_col=mtm_col, perm_n=perm_n, seed=seed)

    b_keys = set(zip(base_wf_slot["buy_date"], base_wf_slot["code"]))
    p_keys = set(zip(patch_wf_slot["buy_date"], patch_wf_slot["code"]))
    return {
        "mode": "B_V20_DELTA_PATCH",
        "elapsed_sec": round(time.time() - t0, 3),
        "max_delta": int(max_delta),
        "meta": core_meta,
        "scored_df": scored_df,
        "baseline_metrics": ev_base,
        "patch_metrics": ev_patch,
        "base_slot_df": base_slot,
        "patch_slot_df": patch_slot,
        "wf_trade_diff_summary": {
            "kicked_count": int(len(b_keys - p_keys)),
            "added_count": int(len(p_keys - b_keys)),
            "kicked_keys": sorted(list(b_keys - p_keys)),
            "added_keys": sorted(list(p_keys - b_keys)),
        },
    }


def verify_truncation_zero_leakage(
    cand_df: pd.DataFrame,
    feature_cols: list[str],
    mode: str = "A",
    cutoff: str = "2024-12-31",
    score_threshold: str | float = "top10",
    **engine_kwargs,
) -> dict:
    """
    Physical truncation test at `cutoff` (default 2024-12-31):
    Drops all rows with buy_date > cutoff, reruns engine from scratch, and asserts
    max_abs_score_diff == 0.0 AND max_abs_ret_diff == 0.0 on all trades exiting <= cutoff.
    """
    df_full = cand_df.copy()
    df_full["buy_date"] = df_full["buy_date"].astype(str).str[:10]
    df_full["exit_date"] = df_full["exit_date"].astype(str).str[:10]
    df_full["code"] = df_full["code"].astype(str).str.zfill(6)
    df_trunc = df_full[df_full["buy_date"] <= cutoff].copy().reset_index(drop=True)

    if mode == "A":
        res_f = run_wf_scorecard_new_strategy(df_full, feature_cols, thresholds=(score_threshold,), eval_v20_patch=False, perm_n=50, **engine_kwargs)
        res_t = run_wf_scorecard_new_strategy(df_trunc, feature_cols, thresholds=(score_threshold,), eval_v20_patch=False, perm_n=50, **engine_kwargs)
        sc_col = "wf_score"
        tname = str(score_threshold) if not isinstance(score_threshold, (int, float)) else f"abs_{int(score_threshold)}"
        slot_f = res_f["threshold_results"][tname]["slot_df"]
        slot_t = res_t["threshold_results"][tname]["slot_df"]
    else:
        res_f = run_wf_scorecard_patch_v20(df_full, feature_cols, perm_n=50, **engine_kwargs)
        res_t = run_wf_scorecard_patch_v20(df_trunc, feature_cols, perm_n=50, **engine_kwargs)
        sc_col = "wf_delta_score"
        slot_f = res_f["patch_slot_df"]
        slot_t = res_t["patch_slot_df"]

    sf_le = res_f["scored_df"]
    sf_le = sf_le[sf_le["buy_date"] <= cutoff].sort_values(["buy_date", "code"]).reset_index(drop=True)
    st_le = res_t["scored_df"].sort_values(["buy_date", "code"]).reset_index(drop=True)
    assert len(sf_le) == len(st_le), f"Row count mismatch <= {cutoff}: {len(sf_le)} vs {len(st_le)}"

    vf = sf_le[sc_col].fillna(-999999.0).to_numpy(float)
    vt = st_le[sc_col].fillna(-999999.0).to_numpy(float)
    max_score_diff = float(np.max(np.abs(vf - vt))) if len(vf) else 0.0
    assert max_score_diff == 0.0, f"Truncation score diff != 0: {max_score_diff}"

    tr_f = slot_f[slot_f["exit_date"] <= cutoff].sort_values(["buy_date", "code"]).reset_index(drop=True)
    tr_t = slot_t[slot_t["exit_date"] <= cutoff].sort_values(["buy_date", "code"]).reset_index(drop=True)
    assert len(tr_f) == len(tr_t), f"Trade count mismatch <= {cutoff}: {len(tr_f)} vs {len(tr_t)}"
    assert list(zip(tr_f["buy_date"], tr_f["code"])) == list(zip(tr_t["buy_date"], tr_t["code"])), "Trunc trade sequence mismatch"
    max_ret_diff = float(np.max(np.abs(tr_f["net_ret"].to_numpy(float) - tr_t["net_ret"].to_numpy(float)))) if len(tr_f) else 0.0
    assert max_ret_diff == 0.0, f"Truncation ret diff != 0: {max_ret_diff}"

    return {
        "mode": mode,
        "cutoff": cutoff,
        "n_rows_checked": int(len(sf_le)),
        "n_trades_exiting_le_cutoff": int(len(tr_f)),
        "max_abs_score_diff": max_score_diff,
        "max_abs_ret_diff": max_ret_diff,
        "zero_leakage_pass": True,
    }

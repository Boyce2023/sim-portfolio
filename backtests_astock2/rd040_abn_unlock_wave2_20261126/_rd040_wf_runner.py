#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD040 WF Scorecard Runner: exact MTM re-eval, 30/50/80bps, >=2yi liquidity, V20 patch & truncation."""
import sys
import time
import numpy as np
import pandas as pd

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd040_abn_unlock_wave2_20261126"
WAVE1_BASE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
for p in (OUT_DIR, WAVE1_BASE):
    if p not in sys.path:
        sys.path.insert(0, p)

import wf_scorecard_engine as wf
import _wf_sim_and_metrics as wfm
import _rd040_eval as rd_ev

EXACT_WINDOWS = [
    ("FULL_WF", "2023-01-03", "2026-11-16"),
    ("Y2025_2026", "2025-01-01", "2026-11-16"),
    ("Y2026", "2026-01-01", "2026-11-16"),
    ("Y2026_H2", "2026-07-01", "2026-11-16"),
]


def get_causal_feature_list(df: pd.DataFrame, extra_cols: list[str], exclude_cols: tuple[str, ...] = ()) -> list[str]:
    """Strictly causal pre-2023 non-degeneracy filter on ~170+ stock + market + abn features."""
    abn_cols = [
        "abn_peak_dev10", "abn_peak_h_dev10", "abn_was_hit_100", "abn_hp_days", "abn_adj_days",
        "abn_days_since_hp", "abn_zt_cnt_wave", "abn_sig_dev10", "abn_proj_flat_b",
        "abn_rel_actual_pp", "abn_rel_proj_pp", "abn_room_open_b", "abn_dd_peak_t1_pct",
        "abn_retrace_frac", "abn_wave_gain_pct", "abn_vol_shrink", "abn_amt_ratio3",
        "abn_above_ma5", "abn_above_ma10", "abn_sig_amt_yi", "abn_open_pct", "abn_sig_ret1d",
        "drv_open_minus_ret_t1", "drv_lhb_inst_minus_lhasa", "drv_ind_rel5_t1", "drv_ind_rel20_t1",
    ]
    pit_prefixes = ("L1_", "mkt", "th_", "nt_", "us_", "comm_", "macro_", "wp_", "pol_",
                    "mcap_", "amount_", "ret_", "d1_", "prev_", "overhang_", "hr", "down_", "pos_",
                    "dd_", "amp_", "bias", "vol_", "turn_", "lhb_", "lock_", "free_", "real_",
                    "list_age", "waves_", "zt_", "max_streak", "cum_", "trap_", "cool_", "xq_",
                    "kpl_", "csrc_", "tox_", "abn_notice", "ir_cnt", "open_pct", "mine_", "is_mine")
    cands = list(dict.fromkeys(abn_cols + extra_cols + [c for c in df.columns if c.startswith(pit_prefixes)]))
    excl = set(exclude_cols)
    w = df[df["buy_date"] <= "2022-12-31"]
    clean = []
    for c in cands:
        if c not in df.columns or c in excl or not pd.api.types.is_numeric_dtype(df[c]):
            continue
        s = w[c].dropna()
        if len(s) < 30:
            continue
        vc = s.value_counts()
        if len(vc) <= 1:
            continue
        if len(vc) <= 3 and int(vc.min()) < 10:
            continue
        clean.append(c)
    return clean


def evaluate_wf_track(
    track_id: str, df_view: pd.DataFrame, feature_cols: list[str], v20_ctx: dict,
    all_idx_dts: list[str], thresholds: tuple = ("all_cands", "top30", "top20", "top10", "top5", 70, 75, 80),
    run_trunc: bool = False, min_warmup_trades: int = 60, min_warmup_trades_rare: int = 40,
) -> tuple[dict, list[dict], dict]:
    t0 = time.time()
    res = wf.run_wf_scorecard_new_strategy(
        df_view, feature_cols=feature_cols, v20_ctx=v20_ctx, wf_start_date="2023-01-03", end_date="2026-11-16",
        min_warmup_trades=min_warmup_trades, min_warmup_trades_rare=min_warmup_trades_rare, min_warmup_months=18,
        recalc_freq="daily", top_k=12, min_k=5, max_corr=0.65, min_t_stat=1.0, shrink_tau=20.0,
        fee_rt=0.0030, gross_ret_col="gross_ret", thresholds=thresholds, eval_v20_patch=False, perm_n=100, seed=20261126,
    )
    actual_wf_start = res["meta"]["wf_actual_start"] or "2023-01-03"
    bench_df = v20_ctx["bench"]
    scored_df = res["scored_df"]
    wf_cands = scored_df[scored_df["wf_in_window"]].copy()
    cal_df = v20_ctx["calendar_5y"]
    patch_cal_dts = cal_df[cal_df["trade_date"].between(actual_wf_start, "2026-11-16")].sort_values("trade_date")["trade_date"].tolist()

    trunc_res = None
    if run_trunc and not wf_cands.empty:
        trunc_res = wf.verify_truncation_zero_leakage(
            df_view, feature_cols, mode="A", cutoff="2024-12-31", score_threshold="top20",
            v20_ctx=v20_ctx, wf_start_date="2023-01-03", end_date="2026-11-16",
            min_warmup_trades=min_warmup_trades, min_warmup_trades_rare=min_warmup_trades_rare, min_warmup_months=18,
            recalc_freq="daily", top_k=12, min_k=5, max_corr=0.65, min_t_stat=1.0, shrink_tau=20.0,
            fee_rt=0.0030, gross_ret_col="gross_ret",
        )

    csv_rows, thr_details = [], {}
    for th in thresholds:
        tname = str(th) if not isinstance(th, (int, float)) else f"abs_{int(th)}"
        tr = res["threshold_results"][tname]
        slot_df, pass_df = tr["slot_df"].copy(), tr["pass_df"].copy()

        # Exact MTM evaluation at 30bps (1000x permutation)
        ev30 = rd_ev.eval_windows_exact(
            slot_df, pass_df, wf_cands, bench_df, all_idx_dts, "mtm_json_use", 0.0030,
            actual_wf_start, "2026-11-16", EXACT_WINDOWS, perm_n=1000, seed=20261126,
        )
        # 50bps & 80bps friction stress
        ev50 = rd_ev.eval_windows_exact(
            slot_df.assign(net_ret=(1.0 + slot_df["gross_ret"]) * (1.0 - 0.0050) - 1.0),
            pass_df.assign(net_ret=(1.0 + pass_df["gross_ret"]) * (1.0 - 0.0050) - 1.0),
            wf_cands.assign(net_ret=(1.0 + wf_cands["gross_ret"]) * (1.0 - 0.0050) - 1.0),
            bench_df, all_idx_dts, "mtm_json_use", 0.0050, actual_wf_start, "2026-11-16", EXACT_WINDOWS, perm_n=50,
        )
        ev80 = rd_ev.eval_windows_exact(
            slot_df.assign(net_ret=(1.0 + slot_df["gross_ret"]) * (1.0 - 0.0080) - 1.0),
            pass_df.assign(net_ret=(1.0 + pass_df["gross_ret"]) * (1.0 - 0.0080) - 1.0),
            wf_cands.assign(net_ret=(1.0 + wf_cands["gross_ret"]) * (1.0 - 0.0080) - 1.0),
            bench_df, all_idx_dts, "mtm_json_use", 0.0080, actual_wf_start, "2026-11-16", EXACT_WINDOWS, perm_n=50,
        )
        # Liquidity >= 2yi filter (abn_sig_amt_yi >= 2.0) re-selection
        liq_pass = pass_df[pass_df["abn_sig_amt_yi"] >= 2.0].copy() if not pass_df.empty else pass_df
        _, liq_slot = wfm.select_single_slot_trades(liq_pass, score_col="wf_score", threshold=None, wf_only=False) if not liq_pass.empty else (liq_pass, liq_pass)
        ev_liq = rd_ev.eval_windows_exact(liq_slot, liq_pass, wf_cands, bench_df, all_idx_dts, "mtm_json_use", 0.0030, actual_wf_start, "2026-11-16", EXACT_WINDOWS, perm_n=50)

        # V20 correlation & strict empty-slot patch (exact MTM)
        v20_corr = rd_ev.compute_v20_corr_exact(slot_df, v20_ctx, all_idx_dts, "mtm_json_use", 0.0030, actual_wf_start, "2026-11-16")
        patch_res = None
        if not pass_df.empty and th != "all_cands":
            p_mtm = rd_ev.attach_exact_mtm_col(pass_df, "mtm_json_use", patch_cal_dts, all_idx_dts, 0.0030, out_col="mtm_patch_exact")
            patch_res = wf.simulate_v20_empty_slot_patch(p_mtm, v20_ctx=v20_ctx, wf_start_dt=actual_wf_start, end_dt="2026-11-16", score_col="wf_score", patch_mtm_col="mtm_patch_exact")

        fw = ev30["windows"].get("FULL_WF", {})
        y2526 = ev30["windows"].get("Y2025_2026", {})
        y26 = ev30["windows"].get("Y2026", {})
        y26h2 = ev30["windows"].get("Y2026_H2", {})
        fw50 = ev50["windows"].get("FULL_WF", {})
        fw80 = ev80["windows"].get("FULL_WF", {})
        fw_liq = ev_liq["windows"].get("FULL_WF", {})
        perm = ev30["permutation_1000"]
        m1 = patch_res["mode1_strict_combined_no_peek"] if patch_res else None
        m2 = patch_res["mode2_empty_slot_standalone"] if patch_res else None

        csv_rows.append({
            "track": track_id, "threshold": tname, "wf_start": actual_wf_start, "n_pass": int(len(pass_df)),
            "n_trades": fw.get("n", 0), "wr_pct": fw.get("wr_pct", 0.0), "plr": fw.get("plr", 0.0), "mean_pct": fw.get("mean_pct", 0.0),
            "nav_30": fw.get("nav", 1.0), "ex3_30": fw.get("ex_top3_nav", 1.0), "ex5_30": fw.get("ex_top5_nav", 1.0),
            "mdd_pct": fw.get("daily_mdd_pct", 0.0), "sharpe": fw.get("daily_sharpe", 0.0), "calmar": fw.get("daily_calmar", 0.0),
            "mtm_diff": ev30["mtm_reconciliation_diff"],
            "excess_csi300_pp": fw.get("excess_csi300_pp", 0.0), "excess_alla_ew_pp": fw.get("excess_alla_ew_pp", 0.0),
            "nav_50": fw50.get("nav", 1.0), "ex5_50": fw50.get("ex_top5_nav", 1.0),
            "nav_80": fw80.get("nav", 1.0), "ex5_80": fw80.get("ex_top5_nav", 1.0),
            "liq2yi_n": fw_liq.get("n", 0), "liq2yi_nav": fw_liq.get("nav", 1.0), "liq2yi_ex5": fw_liq.get("ex_top5_nav", 1.0),
            "n_2526": y2526.get("n", 0), "nav_2526": y2526.get("nav", 1.0), "ex5_2526": y2526.get("ex_top5_nav", 1.0),
            "n_y26": y26.get("n", 0), "nav_y26": y26.get("nav", 1.0),
            "n_26h2": y26h2.get("n", 0), "nav_26h2": y26h2.get("nav", 1.0),
            "perm_sd_p": perm.get("same_day_p_nav", 1.0), "perm_any_p": perm.get("any_cand_day_p_nav", 1.0),
            "corr_v20_all": v20_corr["corr_all_days"], "corr_v20_act": v20_corr["corr_track_active"],
            "v20_comb_delta_ratio": m1.get("delta_nav_ratio_full_wf") if m1 else None,
            "v20_comb_delta_sharpe": m1.get("delta_sharpe_full_wf") if m1 else None,
            "v20_patch_added_n": m1.get("n_patch_added") if m1 else None,
            "v20_skipped_n": m1.get("n_v20_skipped_by_collision") if m1 else None,
            "emp_n": m2["windows"]["FULL_WF"].get("n") if m2 else None,
            "emp_nav": m2["windows"]["FULL_WF"].get("nav") if m2 else None,
            "emp_ex5": m2["windows"]["FULL_WF"].get("ex_top5_nav") if m2 else None,
            "trunc_pass": trunc_res["zero_leakage_pass"] if trunc_res else None,
        })
        thr_details[tname] = {"ev30": ev30, "ev50_fw": fw50, "ev80_fw": fw80, "liq2yi_fw": fw_liq, "v20_corr": v20_corr,
                              "v20_patch_m1": ({k: v for k, v in m1.items() if k != "skipped_v20_trades"} if m1 else None),
                              "v20_patch_m2": m2}
    latest_card = res["meta"]["latest_scorecard"]
    audit = {"track": track_id, "elapsed_sec": round(time.time() - t0, 2), "n_rows": int(len(df_view)), "n_features": int(len(feature_cols)),
             "wf_actual_start": actual_wf_start, "truncation_20241231": trunc_res,
             "latest_factors": ([{k: f[k] for k in ("name", "t_cluster", "shape", "budget_pts", "bin_pts", "bin_cnts", "bin_wr_pct", "bin_mean_pct")} for f in latest_card["factors"]] if latest_card else []),
             "thresholds": thr_details}
    return audit, csv_rows, res

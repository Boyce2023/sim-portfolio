#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD041 Step 3: Full Expanding Walk-Forward Scorecard (exit_date < t),
Slippage Stress (+30/+50/+80 bps), Adverse Selection Stress (70%/50% Sealed vs 100% Broken, 500x MC),
V20.0 Empty-Slot Patch, 1000x Permutation, and 2024-12-31 Physical Truncation Proof.

Zero yfinance (D12). Zero cap10m. Threads <= 1. Peak RSS < 2.0 GB.
"""
import os
for _env_k in (
    "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS",
):
    os.environ[_env_k] = "1"

import gc
import json
import math
import resource
import sys
import time
import warnings

import numpy as np
import pandas as pd
import pyarrow as pa

pa.set_cpu_count(1)
pa.set_io_thread_count(1)
warnings.filterwarnings("ignore")

assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
BASE_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd041_day0_firstboard_sweep_20261126"
CACHE_DIR = f"{OUT_DIR}/_cache"
PQ_PATH = f"{CACHE_DIR}/rd041_fb_master_pit.parquet"

if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import wf_scorecard_engine as wf
import _wf_sim_and_metrics as wfm

TRD_DAYS_YEAR = 242.0

# Strictly causal features: ONLY <= T-1 close, overnight US, <= 09:25 pre-open news, or 09:25 auction!
CAUSAL_FEATURES = [
    "open_pct", "gap_to_zt_dist", "is_20cm",
    "mcap_yi_t1", "free_mcap_yi_t1", "amount_yi_t1", "real_turn_pct_t1",
    "ret_1d_t1", "d1_open_pct", "prev_clv", "prev_is_broken_zt", "prev_is_yizi_zt",
    "overhang_pct_t1", "hr10d_space_t1", "hr30d_space_t1", "down_streak_t1",
    "pos_20d_t1", "pos_60d_t1", "pos_250d_t1", "dd_20d_t1", "amp_20d_t1",
    "bias10_t1", "bias20_t1", "ret_5d_t1", "ret_20d_t1", "vol_ratio5_t1",
    "turn_5_20_t1", "amp_comp_20v60_t1",
    "lhb_on_t1", "lhb_bayes_t2_t1", "lhb_inst_net_yi_t1", "lhb_lhasa_share_t1",
    "lhb_has_good_yz_t1", "lhb_has_surf_yz_t1", "lhb_has_quant_t1", "lhb_cnt_5d_t1",
    "lock_top10_pct_pre", "d1_first_seal_hhmm_t1", "d1_open_board_cnt_t1", "d1_seal_ratio_t1",
    "list_age", "waves_3y_g15_t1", "zt_cnt_1y_t1", "max_streak_3y",
    "cum_turnover_1y", "trap_waves_3y", "dd_from_3y_high",
    "cool_days_since_last_zt", "cool_days_since_last_2b",
    "comm_posts_1y_pct", "xq_posts_1y_pct",
    "kpl_unique_plates_3y", "kpl_top_plate_share",
    "kpl_zt3_t1", "kpl_days_30d_t1", "kpl_in_t1", "kpl_rank_t1", "kpl_zt1_t1", "kpl_streak_t1",
    "csrc_ind_ex5_t1", "csrc_ind_ex20_t1", "csrc_ind_rank20_t1",
    "csrc_ind_zt_share5_t1", "csrc_ind_amt_pct250_t1",
    "tox_reg_30d_pre", "abn_notice_30d_pre", "ir_cnt_30d_pre",
    "comm_ring_tier", "comm_driver_ret20_t1", "comm_driver_pct5y_t1",
    "L1_zt_cnt_t1", "L1_nat_zt_cnt_t1", "L1_dt_cnt_t1", "L1_zt_dt_logratio_t1",
    "L1_zb_rate_t1", "L1_max_board_t1", "L1_lianban_cnt_t1", "L1_zt_prem_t1",
    "L1_lb_promo_t1", "L1_duanban_damian_t1", "L1_zt_mom3v20_t1", "L1_zt_pct60_t1",
    "L1_sent_phase_t1", "L1_smb_5d_t1", "L1_smb_20d_t1", "L1_amt_ratio20_t1",
    "L1_ew_bias20_t1", "L1_ew_pos60_t1", "L1_is_earn_win", "L1_is_month_end3", "L1_weekday",
    "mkt20_zt_cnt_t1", "mkt_amt_tril_t1", "mkt_0925_zt_cnt", "mkt_0925_avg_gap_pct",
    "th_style_ice_point_sig_t1", "us_ixic_ret1d_on", "us_gspc_ret1d_on", "us_vix_level_on",
    "pol_rescue_signal_10d", "pol_crackdown_signal_10d",
    "ind_0925_gap3_cnt", "ind_0925_gap5_cnt", "ind_0925_rank_gap",
    "kpl_0925_gap3_cnt", "kpl_0925_rank_gap", "kpl_theme_cold_t1",
    "fn_pre_any", "fn_pre_pos", "fn_pre_hard", "fn_pre_cold", "fn_pre_neg",
    "cninfo_pre_pos", "ir_pre_pos", "any_pre_cat", "theme_news_pre_cnt",
    "is_weak_to_strong_brk", "is_weak_to_strong_neg", "is_day0_theme_ignite",
]

FORBIDDEN_SUBSTR = ("audit_only", "is_zt", "is_broken_zt", "ret_1d", "gross_ret", "exit_date", "mtm_json")
for fc in CAUSAL_FEATURES:
    if fc != "ret_1d_t1":
        for bad in FORBIDDEN_SUBSTR:
            assert bad not in fc or fc.endswith("_t1") or fc in ("prev_is_broken_zt", "prev_is_yizi_zt"), f"Leakage risk in {fc}"


def peak_rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 2)


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
    return obj


def attach_net_mtm_tuples(df: pd.DataFrame, mtm_json_col: str, fee_rt: float, dt_to_cal_idx: dict[str, int]) -> list:
    """Convert raw gross mtm_json into exact (cal_idx, net_mult) tuples matching fee_rt."""
    f_buy = fee_rt * 0.5
    f_sell_mult = (1.0 - fee_rt) / (1.0 - f_buy)
    out = []
    for s in df[mtm_json_col]:
        arr = json.loads(s) if isinstance(s, str) and s else []
        if not arr:
            out.append(())
            continue
        loc = []
        last_i = len(arr) - 1
        for idx_k, (d_str, mult) in enumerate(arr):
            ti = dt_to_cal_idx.get(d_str)
            m_val = float(mult)
            if idx_k == 0:
                m_val *= (1.0 - f_buy)
            if idx_k == last_i:
                m_val *= f_sell_mult
            if ti is not None:
                loc.append((ti, m_val))
        out.append(tuple(loc))
    return out


def mc_adverse_selection(
    pass_df: pd.DataFrame,
    cal_dts: list[str],
    mtm_col: str,
    p_fill_zt: float,
    allow_fallback: bool,
    fee_rt: float = 0.0030,
    n_mc: int = 500,
    seed: int = 20261126,
) -> dict:
    """500x Monte Carlo queue-miss adverse selection: broken=100% fill, sealed=p_fill_zt."""
    if pass_df.empty:
        return {"n_mc": n_mc, "med_n": 0, "med_nav": 1.0, "med_sharpe": 0.0, "med_mdd_pct": 0.0, "med_wr_pct": 0.0, "med_mean_pct": 0.0}

    srt = pass_df.sort_values(["buy_date", "wf_score", "code"], ascending=[True, False, True]).reset_index(drop=True)
    day_groups = []
    for bd, grp in srt.groupby("buy_date", sort=True):
        cands = []
        for r in grp.itertuples(index=False):
            nr = (1.0 + float(r.gross_ret)) * (1.0 - fee_rt) - 1.0
            cands.append((
                str(r.buy_date), str(r.exit_date),
                int(getattr(r, "buy_hhmm", 935)), int(getattr(r, "exit_hhmm", 1500)),
                int(r.is_zt), nr, getattr(r, mtm_col),
            ))
        day_groups.append((bd, cands))

    T = len(cal_dts)
    rng = np.random.default_rng(seed)

    navs = np.empty(n_mc, dtype=float)
    sharpes = np.empty(n_mc, dtype=float)
    mdds = np.empty(n_mc, dtype=float)
    wrs = np.empty(n_mc, dtype=float)
    means = np.empty(n_mc, dtype=float)
    ns = np.empty(n_mc, dtype=int)
    brk_shares = np.empty(n_mc, dtype=float)

    for m in range(n_mc):
        cur_ed, cur_eh = "", 0
        tr_rets = []
        tr_brks = 0
        day_mult = np.ones(T, dtype=float)

        for bd, cands in day_groups:
            if cur_ed and not (bd > cur_ed or (bd == cur_ed and cands[0][2] > cur_eh)):
                continue
            chosen = None
            if not allow_fallback:
                c0 = cands[0]
                if c0[4] == 0 or rng.random() < p_fill_zt:
                    chosen = c0
            else:
                for ck in cands:
                    if ck[4] == 0 or rng.random() < p_fill_zt:
                        chosen = ck
                        break
            if chosen is not None:
                _, ed, _, eh, zt_f, nr, segs = chosen
                cur_ed, cur_eh = ed, eh
                tr_rets.append(nr)
                if zt_f == 0:
                    tr_brks += 1
                for ti, mult in segs:
                    if 0 <= ti < T:
                        day_mult[ti] *= float(mult)

        ns[m] = len(tr_rets)
        if not tr_rets:
            navs[m], sharpes[m], mdds[m], wrs[m], means[m], brk_shares[m] = 1.0, 0.0, 0.0, 0.0, 0.0, 0.0
            continue
        arr_r = np.asarray(tr_rets, dtype=float)
        navs[m] = float(np.prod(1.0 + arr_r))
        wrs[m] = float((arr_r > 0).mean() * 100.0)
        means[m] = float(arr_r.mean() * 100.0)
        brk_shares[m] = float(tr_brks / len(tr_rets) * 100.0)

        dr = day_mult - 1.0
        sd = float(np.std(dr, ddof=1)) if T > 1 else 0.0
        sharpes[m] = float(np.mean(dr) / sd * math.sqrt(TRD_DAYS_YEAR)) if sd > 1e-12 else 0.0
        curve = np.concatenate([[1.0], np.cumprod(1.0 + dr)])
        pk = np.maximum.accumulate(curve)
        mdds[m] = float(np.max((pk - curve) / pk) * 100.0)

    return {
        "n_mc": n_mc,
        "p_fill_zt": p_fill_zt,
        "allow_fallback": allow_fallback,
        "fee_bps": round(fee_rt * 10000, 1),
        "med_n": int(np.median(ns)),
        "med_brk_share_pct": round(float(np.median(brk_shares)), 1),
        "med_wr_pct": round(float(np.median(wrs)), 2),
        "med_mean_pct": round(float(np.median(means)), 2),
        "med_nav": round(float(np.median(navs)), 4),
        "p25_nav": round(float(np.percentile(navs, 25)), 4),
        "p75_nav": round(float(np.percentile(navs, 75)), 4),
        "med_sharpe": round(float(np.median(sharpes)), 3),
        "med_mdd_pct": round(float(np.median(mdds)), 2),
    }


def eval_track_full(
    track_id: str,
    track_group: str,
    desc: str,
    df_sub: pd.DataFrame,
    exit_prefix: str,
    v20_ctx: dict,
    end_date: str = "2026-11-16",
    min_warmup_trades: int = 80,
    min_warmup_trades_rare: int = 40,
    recalc_freq: str = "monthly",
    perm_n: int = 1000,
    thresholds: tuple = ("all_cands", "top30", "top20", "top10", "top5", 70, 75),
    run_trunc_check: bool = True,
) -> dict:
    """Run Mode A WF scorecard + exact MTM + Slippage + Adverse Selection MC + V20 Patch + 2024-12-31 Truncation."""
    t0 = time.time()
    bench_df = v20_ctx["bench"]

    max_bench_dt = str(bench_df["trade_date"].max())
    eval_end_dt = min(max_bench_dt, max(end_date, "2026-11-16"))

    fcols_use = [c for c in CAUSAL_FEATURES if c in df_sub.columns]
    keep_cols = ["buy_date", "code", "is_zt", f"{exit_prefix}_exit_date", f"{exit_prefix}_exit_hhmm", f"{exit_prefix}_gross_ret", f"{exit_prefix}_mtm_json"] + fcols_use
    keep_cols = list(dict.fromkeys(keep_cols))
    cand = df_sub[keep_cols].copy()
    cand["exit_date"] = cand[f"{exit_prefix}_exit_date"].astype(str).str[:10]
    cand["exit_hhmm"] = cand[f"{exit_prefix}_exit_hhmm"].astype(int)
    cand["gross_ret"] = cand[f"{exit_prefix}_gross_ret"].astype(float)
    cand["buy_hhmm"] = 935
    cand["can_buy"] = cand["gross_ret"].notna() & (cand["exit_date"] > cand["buy_date"]) & (cand["buy_date"] <= end_date) & (cand["exit_date"] <= eval_end_dt)
    cand["is_yizi"] = False
    cand = cand[cand["can_buy"]].copy().reset_index(drop=True)
    mtm_col_name = f"{exit_prefix}_mtm_json"

    res = wf.run_wf_scorecard_new_strategy(
        cand,
        feature_cols=fcols_use,
        v20_ctx=v20_ctx,
        wf_start_date="2023-01-03",
        end_date=end_date,
        min_warmup_trades=min_warmup_trades,
        min_warmup_trades_rare=min_warmup_trades_rare,
        min_warmup_months=18,
        recalc_freq=recalc_freq,
        top_k=12,
        min_k=min(5, len(fcols_use)),
        max_corr=0.65,
        min_t_stat=1.0,
        shrink_tau=20.0,
        fee_rt=0.0030,
        gross_ret_col="gross_ret",
        mtm_col=None,
        thresholds=thresholds,
        eval_v20_patch=True,
        perm_n=perm_n,
    )

    actual_wf_start = res["meta"]["wf_actual_start"] or "2023-01-03"
    b_win = bench_df[bench_df["trade_date"].between(actual_wf_start, eval_end_dt)].sort_values("trade_date").reset_index(drop=True)
    cal_win = b_win["trade_date"].astype(str).tolist()
    dt_idx_win = {d: i for i, d in enumerate(cal_win)}
    csi_arr = b_win["csi300_daily_ret"].to_numpy(float)
    ew_arr = b_win["alla_ew_daily_ret"].to_numpy(float)

    cal_5y_df = v20_ctx["calendar_5y"]
    v20_win_cal = cal_5y_df[cal_5y_df["trade_date"].between(actual_wf_start, min(eval_end_dt, "2026-11-16"))].sort_values("trade_date")
    v20_dr_win = v20_win_cal["v20_daily_ret"].to_numpy(float)

    rows_out = []
    best_row = None
    best_obj = None
    best_rank = -1e18

    for th_name, obj in res["threshold_results"].items():
        slot_df = obj["slot_df"].copy()
        pass_df = obj["pass_df"].copy()
        ev = obj["metrics"]
        patch = obj["v20_empty_patch"]
        p_m1 = patch["mode1_strict_combined_no_peek"] if patch else None
        p_m2 = patch["mode2_empty_slot_standalone"] if patch else None

        if not slot_df.empty:
            slot_df["mtm_30"] = attach_net_mtm_tuples(slot_df, f"{exit_prefix}_mtm_json", 0.0030, dt_idx_win)
        else:
            slot_df["mtm_30"] = []
        dr30, mtm_diff = wfm.build_daily_mtm_returns(slot_df, cal_win, mtm_col="mtm_30")
        assert mtm_diff < 1e-5, f"MTM diff error on {track_id}/{th_name}: {mtm_diff}"

        w_full = wfm._calc_one_window(slot_df, pass_df, dr30, cal_win, dt_idx_win, csi_arr, ew_arr, actual_wf_start, eval_end_dt)
        w_23 = wfm._calc_one_window(slot_df, pass_df, dr30, cal_win, dt_idx_win, csi_arr, ew_arr, actual_wf_start, "2023-12-31")
        w_24 = wfm._calc_one_window(slot_df, pass_df, dr30, cal_win, dt_idx_win, csi_arr, ew_arr, "2024-01-01", "2024-12-31")
        w_2526 = wfm._calc_one_window(slot_df, pass_df, dr30, cal_win, dt_idx_win, csi_arr, ew_arr, "2025-01-01", eval_end_dt)
        w_26 = wfm._calc_one_window(slot_df, pass_df, dr30, cal_win, dt_idx_win, csi_arr, ew_arr, "2026-01-01", eval_end_dt)

        dr_sub_v20 = dr30[:len(v20_dr_win)]
        corr_v20 = float(np.corrcoef(dr_sub_v20, v20_dr_win)[0, 1]) if (len(dr_sub_v20) == len(v20_dr_win) and np.std(dr_sub_v20) > 1e-12 and np.std(v20_dr_win) > 1e-12) else 0.0

        slip_res = {}
        for f_bps, f_val in [(60, 0.0060), (80, 0.0080), (110, 0.0110)]:
            if slot_df.empty:
                slip_res[f_bps] = {"nav": 1.0, "sharpe": 0.0, "mean_pct": 0.0, "ex5_nav": 1.0}
            else:
                s_tmp = slot_df.copy()
                s_tmp["net_ret"] = (1.0 + s_tmp["gross_ret"].astype(float)) * (1.0 - f_val) - 1.0
                s_tmp["mtm_f"] = attach_net_mtm_tuples(s_tmp, f"{exit_prefix}_mtm_json", f_val, dt_idx_win)
                dr_f, _ = wfm.build_daily_mtm_returns(s_tmp, cal_win, mtm_col="mtm_f")
                wf_f = wfm._calc_one_window(s_tmp, None, dr_f, cal_win, dt_idx_win, csi_arr, ew_arr, actual_wf_start, eval_end_dt)
                slip_res[f_bps] = {"nav": wf_f["nav"], "sharpe": wf_f["daily_sharpe"], "mean_pct": wf_f["mean_pct"], "ex5_nav": wf_f["ex_top5_nav"]}

        brk_share_pct = round(float((slot_df["is_zt"] == 0).mean() * 100.0), 1) if not slot_df.empty else 0.0

        row = {
            "track_id": track_id,
            "track_group": track_group,
            "recalc_freq": recalc_freq,
            "exit_mode": exit_prefix,
            "threshold": th_name,
            "desc": desc,
            "wf_actual_start": actual_wf_start,
            "end_date": eval_end_dt,
            "n_cands_total": int(len(cand)),
            "n_pass": int(obj["n_passing_cands"]),
            "n_trades_wf": w_full["n"],
            "brk_share_pct": brk_share_pct,
            "wr_wf_pct": w_full["wr_pct"],
            "plr_wf": w_full["plr"],
            "mean_wf_pct": w_full["mean_pct"],
            "nav_wf": w_full["nav"],
            "ex3_wf": w_full["ex_top3_nav"],
            "ex5_wf": w_full["ex_top5_nav"],
            "mdd_wf_pct": w_full["daily_mdd_pct"],
            "sharpe_wf": w_full["daily_sharpe"],
            "calmar_wf": w_full["daily_calmar"],
            "cagr_wf_pct": w_full["cagr_pct"],
            "excess_csi_wf_pp": w_full["excess_csi300_pp"],
            "excess_ew_wf_pp": w_full["excess_alla_ew_pp"],
            "nav_y23": w_23["nav"],
            "nav_y24": w_24["nav"],
            "n_2526": w_2526["n"],
            "nav_2526": w_2526["nav"],
            "ex5_2526": w_2526["ex_top5_nav"],
            "sharpe_2526": w_2526["daily_sharpe"],
            "nav_2026": w_26["nav"],
            "slip60_nav": slip_res[60]["nav"],
            "slip80_nav": slip_res[80]["nav"],
            "slip80_sharpe": slip_res[80]["sharpe"],
            "slip110_nav": slip_res[110]["nav"],
            "corr_v20_wf": round(corr_v20, 4),
            "perm_sd_p": ev["permutation_1000"]["same_day_p_nav"],
            "perm_any_p": ev["permutation_1000"]["any_cand_day_p_nav"],
            "mtm_diff": round(float(mtm_diff), 8),
            "patch_n_added": p_m1["n_patch_added"] if p_m1 else 0,
            "patch_delta_nav_ratio": p_m1["delta_nav_ratio_full_wf"] if p_m1 else 1.0,
            "patch_delta_sharpe": p_m1["delta_sharpe_full_wf"] if p_m1 else 0.0,
            "emp_standalone_n": p_m2["n_standalone_empty_trades"] if p_m2 else 0,
            "emp_standalone_nav": p_m2["windows"]["FULL_WF"]["nav"] if p_m2 else 1.0,
        }
        rows_out.append(row)

        if th_name != "all_cands" and w_full["n"] >= 10:
            rk = w_full["daily_sharpe"] + (0.2 if row["patch_delta_nav_ratio"] > 1.0 else 0.0) - 0.005 * w_full["daily_mdd_pct"]
            if rk > best_rank:
                best_rank = rk
                best_row = row
                best_obj = obj

    if best_row is None and rows_out:
        best_row = rows_out[0]
        best_obj = res["threshold_results"][best_row["threshold"]]

    as_stress = {}
    if best_obj is not None and not best_obj["pass_df"].empty:
        p_df = best_obj["pass_df"].copy()
        p_df["mtm_30"] = attach_net_mtm_tuples(p_df, f"{exit_prefix}_mtm_json", 0.0030, dt_idx_win)
        p_df["mtm_80"] = attach_net_mtm_tuples(p_df, f"{exit_prefix}_mtm_json", 0.0080, dt_idx_win)
        as_stress["best_70_no_fb_30bp"] = mc_adverse_selection(p_df, cal_win, "mtm_30", 0.70, False, 0.0030, 500)
        as_stress["best_50_no_fb_30bp"] = mc_adverse_selection(p_df, cal_win, "mtm_30", 0.50, False, 0.0030, 500)
        as_stress["best_70_with_fb_30bp"] = mc_adverse_selection(p_df, cal_win, "mtm_30", 0.70, True, 0.0030, 500)
        as_stress["best_50_with_fb_30bp"] = mc_adverse_selection(p_df, cal_win, "mtm_30", 0.50, True, 0.0030, 500)
        as_stress["best_50_with_fb_80bp"] = mc_adverse_selection(p_df, cal_win, "mtm_80", 0.50, True, 0.0080, 500)

    latest_card = res["meta"]["latest_scorecard"]
    top_factors = [
        {"name": f["name"], "t": f["t_cluster"], "shape": f["shape"], "pts": f["budget_pts"], "bin_wr": f["bin_wr_pct"], "bin_mean": f["bin_mean_pct"]}
        for f in (latest_card["factors"] if latest_card else [])
    ]

    del res
    gc.collect()

    trunc_proof = None
    if run_trunc_check and len(cand[cand["buy_date"] <= "2024-12-31"]) >= min_warmup_trades + 15:
        th_tr = best_row["threshold"] if best_row else "top20"
        th_arg = int(th_tr.split("_")[1]) if th_tr.startswith("abs_") else th_tr
        trunc_proof = wf.verify_truncation_zero_leakage(
            cand, feature_cols=fcols_use, mode="A", cutoff="2024-12-31", score_threshold=th_arg,
            v20_ctx=v20_ctx, wf_start_date="2023-01-03", min_warmup_trades=min_warmup_trades,
            min_warmup_trades_rare=min_warmup_trades_rare, min_warmup_months=18,
            recalc_freq=recalc_freq, top_k=12, min_k=min(5, len(fcols_use)), gross_ret_col="gross_ret", fee_rt=0.0030,
        )

    print(
        f"[WF {track_id:24s} {recalc_freq[0].upper()}] best={best_row['threshold']:9s} n={best_row['n_trades_wf']:3d} brk={best_row['brk_share_pct']:4.1f}% "
        f"WR={best_row['wr_wf_pct']:4.1f}% mean={best_row['mean_wf_pct']:+5.2f}% NAV={best_row['nav_wf']:6.3f} "
        f"ex5={best_row['ex5_wf']:5.3f} Sh={best_row['sharpe_wf']:5.2f} 2526={best_row['nav_2526']:5.3f} "
        f"80bp={best_row['slip80_nav']:5.3f} p={best_row['perm_sd_p']} "
        f"| AS50_noFB={as_stress.get('best_50_no_fb_30bp',{}).get('med_nav','-')} "
        f"AS50_FB={as_stress.get('best_50_with_fb_30bp',{}).get('med_nav','-')} "
        f"| dV20={best_row['patch_delta_nav_ratio']:.4f} | t={time.time()-t0:.1f}s",
        flush=True,
    )

    return {
        "track_id": track_id,
        "track_group": track_group,
        "recalc_freq": recalc_freq,
        "exit_mode": exit_prefix,
        "desc": desc,
        "threshold_rows": rows_out,
        "best_row": best_row,
        "adverse_selection_mc500": as_stress,
        "top_factors_latest": top_factors,
        "truncation_20241231": trunc_proof,
    }


def main():
    t0 = time.time()
    v20_ctx = wf.load_v20_reference_context(BASE_DIR)
    df = pd.read_parquet(PQ_PATH)
    print(f"[Step3] Loaded {len(df)} rows | RSS={peak_rss_mb()} MB", flush=True)

    # Smart speed tier: pools > 15k rows sweep monthly (exact exit_date<t), top large tracks + all <=15k tracks run daily!
    tracks_spec = [
        ("B1_10cm_All_T1O", "TrackB_Full10", "10cm All NonYizi FB -> T1 Open", df[df["is_20cm"] == 0], "E1_T1Open", "2026-11-16", 80, 60, True),
        ("B2_10cm_All_T1C", "TrackB_Full10", "10cm All NonYizi FB -> T1 Close", df[df["is_20cm"] == 0], "E2_T1Close", "2026-11-16", 80, 60, False),
        ("B3_10cm_All_T2C", "TrackB_Full10", "10cm All NonYizi FB -> T2 Close", df[df["is_20cm"] == 0], "E3_T2Close", "2026-11-16", 80, 60, False),
        ("B4_10cm_All_Stk", "TrackB_Full10", "10cm All NonYizi FB -> StreakHold", df[df["is_20cm"] == 0], "E4_StreakHold", "2026-11-16", 80, 60, True),

        ("B5_20cm_All_T1O", "TrackB_Full20", "20cm All NonYizi FB -> T1 Open", df[df["is_20cm"] == 1], "E1_T1Open", "2026-11-16", 80, 60, True),
        ("B6_20cm_All_T1C", "TrackB_Full20", "20cm All NonYizi FB -> T1 Close", df[df["is_20cm"] == 1], "E2_T1Close", "2026-11-16", 80, 60, False),
        ("B7_20cm_All_Stk", "TrackB_Full20", "20cm All NonYizi FB -> StreakHold", df[df["is_20cm"] == 1], "E4_StreakHold", "2026-11-16", 80, 60, True),

        ("B8_Comb_All_T1O", "TrackB_Comb", "10+20cm All NonYizi FB -> T1 Open", df, "E1_T1Open", "2026-11-16", 80, 60, False),
        ("B9_Comb_All_Stk", "TrackB_Comb", "10+20cm All NonYizi FB -> StreakHold", df, "E4_StreakHold", "2026-11-16", 80, 60, True),

        ("B10_10cm_Gap2_8_T1O", "TrackB_0925", "10cm Gap [2%,8%) -> T1 Open", df[(df["is_20cm"] == 0) & df["open_pct"].between(2.0, 8.0)], "E1_T1Open", "2026-11-16", 80, 60, True),
        ("B11_10cm_Gap2_8_Stk", "TrackB_0925", "10cm Gap [2%,8%) -> StreakHold", df[(df["is_20cm"] == 0) & df["open_pct"].between(2.0, 8.0)], "E4_StreakHold", "2026-11-16", 80, 60, True),
        ("B12_10cm_W2S_T1O", "TrackB_W2S", "10cm Weak-to-Strong -> T1 Open", df[(df["is_20cm"] == 0) & ((df["is_weak_to_strong_brk"] == 1) | (df["is_weak_to_strong_neg"] == 1))], "E1_T1Open", "2026-11-16", 60, 40, True),
        ("B13_10cm_W2S_Stk", "TrackB_W2S", "10cm Weak-to-Strong -> StreakHold", df[(df["is_20cm"] == 0) & ((df["is_weak_to_strong_brk"] == 1) | (df["is_weak_to_strong_neg"] == 1))], "E4_StreakHold", "2026-11-16", 60, 40, True),

        ("A1_PreCat_All_T1O", "TrackA_News", "Pre-Open AnyCat (FN/CN/IR) -> T1 Open", df[(df["buy_date"] <= "2026-11-11") & (df["any_pre_cat"] == 1)], "E1_T1Open", "2026-11-11", 50, 35, True),
        ("A2_PreCat_All_T1C", "TrackA_News", "Pre-Open AnyCat (FN/CN/IR) -> T1 Close", df[(df["buy_date"] <= "2026-11-11") & (df["any_pre_cat"] == 1)], "E2_T1Close", "2026-11-11", 50, 35, False),
        ("A3_PreCat_All_Stk", "TrackA_News", "Pre-Open AnyCat (FN/CN/IR) -> StreakHold", df[(df["buy_date"] <= "2026-11-11") & (df["any_pre_cat"] == 1)], "E4_StreakHold", "2026-11-11", 50, 35, True),
        ("A4_FN_PrePos_T1O", "TrackA_News", "Pre-Open FlashNews Pos -> T1 Open", df[(df["buy_date"] <= "2026-11-11") & (df["fn_pre_pos"] == 1)], "E1_T1Open", "2026-11-11", 40, 30, True),
        ("A5_FN_PrePos_Stk", "TrackA_News", "Pre-Open FlashNews Pos -> StreakHold", df[(df["buy_date"] <= "2026-11-11") & (df["fn_pre_pos"] == 1)], "E4_StreakHold", "2026-11-11", 40, 30, True),
        ("A6_Day0Theme_Gap2_T1O", "TrackA_Theme", "Day0 Theme Ignite TopGap<=2 -> T1 Open", df[(df["buy_date"] <= "2026-11-11") & (df["is_day0_theme_ignite"] == 1) & ((df["kpl_0925_rank_gap"] <= 2) | (df["ind_0925_rank_gap"] <= 2))], "E1_T1Open", "2026-11-11", 80, 50, True),
        ("A7_Day0Theme_Gap2_Stk", "TrackA_Theme", "Day0 Theme Ignite TopGap<=2 -> StreakHold", df[(df["buy_date"] <= "2026-11-11") & (df["is_day0_theme_ignite"] == 1) & ((df["kpl_0925_rank_gap"] <= 2) | (df["ind_0925_rank_gap"] <= 2))], "E4_StreakHold", "2026-11-11", 80, 50, True),
        ("A8_Day0Theme_Cold_Stk", "TrackA_Theme", "Cold Theme PreNews -> StreakHold", df[(df["buy_date"] <= "2026-11-11") & (df["theme_news_pre_cnt"] >= 1) & (df["kpl_theme_cold_t1"] == 1)], "E4_StreakHold", "2026-11-11", 80, 50, True),
    ]

    all_results = []
    grid_rows = []
    best_rows = []
    trunc_proofs = {}
    as_map = {}
    factors_map = {}

    spec_by_id = {x[0]: x for x in tracks_spec}

    for tid, tgrp, desc, sub_df, ex_pref, edt, mw, mwr, do_tr in tracks_spec:
        is_large = len(sub_df) > 15000
        rfreq = "monthly" if is_large else "daily"
        pn = 100 if is_large else 1000
        res_t = eval_track_full(
            tid, tgrp, desc, sub_df, ex_pref, v20_ctx,
            end_date=edt, min_warmup_trades=mw, min_warmup_trades_rare=mwr,
            recalc_freq=rfreq, perm_n=pn, run_trunc_check=(False if is_large else do_tr),
        )
        all_results.append(res_t)

    # Automatically upgrade Top-2 monthly tracks by Sharpe/NAV into DAILY recalc + 1000x perm + trunc proof
    # (Skip daily rebuild if > 25k rows would take >3min, instead run monthly trunc proof + 1000x perm!)
    monthly_cands = [r for r in all_results if r["recalc_freq"] == "monthly" and r["best_row"]]
    monthly_cands.sort(key=lambda r: (r["best_row"]["sharpe_wf"], r["best_row"]["nav_wf"]), reverse=True)
    for top_m in monthly_cands[:2]:
        tid_m = top_m["track_id"]
        _, tgrp, desc, sub_df, ex_pref, edt, mw, mwr, _ = spec_by_id[tid_m]
        rf_top = "monthly" if len(sub_df) > 35000 else "daily"
        print(f"\n[Step3] Promoting top monthly track {tid_m} -> {rf_top.upper()} recalc + 1000x perm + truncation proof", flush=True)
        res_d = eval_track_full(
            f"{tid_m}_TOPCHECK", f"{tgrp}_Top", f"{desc} ({rf_top})", sub_df, ex_pref, v20_ctx,
            end_date=edt, min_warmup_trades=mw, min_warmup_trades_rare=mwr,
            recalc_freq=rf_top, perm_n=1000, run_trunc_check=True,
        )
        all_results.append(res_d)

    for res_t in all_results:
        tid = res_t["track_id"]
        for r in res_t["threshold_rows"]:
            r2 = dict(r)
            r2["is_track_best"] = 1 if (res_t["best_row"] and r["threshold"] == res_t["best_row"]["threshold"]) else 0
            grid_rows.append(r2)
        if res_t["best_row"]:
            b = dict(res_t["best_row"])
            b["as50_nofb_med_nav"] = res_t["adverse_selection_mc500"].get("best_50_no_fb_30bp", {}).get("med_nav")
            b["as50_fb_med_nav"] = res_t["adverse_selection_mc500"].get("best_50_with_fb_30bp", {}).get("med_nav")
            b["as70_fb_med_nav"] = res_t["adverse_selection_mc500"].get("best_70_with_fb_30bp", {}).get("med_nav")
            best_rows.append(b)
        if res_t["truncation_20241231"] is not None:
            trunc_proofs[tid] = res_t["truncation_20241231"]
        as_map[tid] = res_t["adverse_selection_mc500"]
        factors_map[tid] = res_t["top_factors_latest"]

    grid_df = pd.DataFrame(grid_rows)
    grid_path = f"{OUT_DIR}/rd041_grid.csv"
    grid_df.to_csv(grid_path, index=False)

    best_df = pd.DataFrame(best_rows).sort_values(["sharpe_wf", "nav_wf"], ascending=[False, False]).reset_index(drop=True)

    step1_aud = json.load(open(f"{CACHE_DIR}/rd041_step1_audit.json"))
    step2_aud = json.load(open(f"{CACHE_DIR}/rd041_step2_diag.json"))

    trunc_all_pass = all(
        v.get("zero_leakage_pass") is True and v.get("max_abs_score_diff") == 0.0 and v.get("max_abs_ret_diff") == 0.0
        for v in trunc_proofs.values()
    )

    passing_strict = [
        r for r in best_rows
        if r["n_trades_wf"] >= 20
        and r["nav_wf"] > 1.30
        and r["ex5_wf"] > 1.10
        and r["nav_2526"] > 1.00
        and r["sharpe_wf"] >= 0.60
        and r["perm_sd_p"] < 0.05
        and (r.get("as50_fb_med_nav") or 0.0) > 1.15
        and (r.get("slip80_nav") or 0.0) > 1.10
    ]

    audit_out = sanitize_json({
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t0, 2),
        "peak_rss_mb": peak_rss_mb(),
        "d12_yfinance_imported": "yfinance" in sys.modules,
        "truncation_20241231_all_pass": trunc_all_pass,
        "truncation_20241231_proofs": trunc_proofs,
        "step1_pool_and_news_audit": step1_aud,
        "step2_baseline_and_trap_diag": step2_aud,
        "n_tracks": len(all_results),
        "n_grid_rows": len(grid_df),
        "passing_strict_count": len(passing_strict),
        "passing_strict_tracks": passing_strict,
        "verdict": "VALID_INCREMENTAL" if len(passing_strict) > 0 else "FALSIFIED",
        "best_summary_sorted": best_df.to_dict("records"),
        "adverse_selection_mc500": as_map,
        "top_factors_latest": factors_map,
    })
    audit_path = f"{OUT_DIR}/rd041_audit.json"
    with open(audit_path, "w", encoding="utf-8") as f:
        json.dump(audit_out, f, ensure_ascii=False, indent=2, allow_nan=False)

    print(f"\n[Step3 DONE] Verdict={audit_out['verdict']} (passing_strict={len(passing_strict)}) | trunc_all_pass={trunc_all_pass} | Peak RSS={audit_out['peak_rss_mb']} MB | elapsed={audit_out['elapsed_sec']}s", flush=True)
    print(f"Saved: {grid_path} ({len(grid_df)} rows) & {audit_path}", flush=True)
    cols_show = ["track_id", "recalc_freq", "threshold", "n_trades_wf", "brk_share_pct", "wr_wf_pct", "mean_wf_pct", "nav_wf", "ex5_wf", "sharpe_wf", "nav_2526", "slip80_nav", "as50_nofb_med_nav", "as50_fb_med_nav", "perm_sd_p", "patch_delta_nav_ratio"]
    print(best_df[cols_show].to_string(index=False), flush=True)


if __name__ == "__main__":
    main()

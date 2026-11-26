#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 2B-1 Shared Causal Library:
- 96-feature curated core PIT catalog (strict T-1 / 09:25) + full 232-feature superset.
- 4 Sub-pools (P0_Full, P1_Strong, P2_TypeB, P3_TypeA) x 4 Entries (E1_all, E4_deep, E3_weak, E2_mild) x 3 Exits.
- Strictly causal Two-Step Mine-Removal (bottom 20% risk blacklist on exit_date < t) + Dragon-Hunting Scorecard.
- Full V20.0 Empty-Slot Audit (combined NAV, standalone empty-slot NAV, ex-top5, same-exposure CSI300/EW excess,
  V20 daily return correlation, and 1,000x permutation p-values).
Zero yfinance (D12). Zero cap10m. Internal threads <= 1.
"""
import os
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

import json
import math
import sys
from typing import Optional

import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
WAVE1 = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
OUT_DIR = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave2b/w2b1_20cm_surge10_19_scorecard"

if WAVE1 not in sys.path:
    sys.path.insert(0, WAVE1)

import _wf_core as wfc
import _wf_sim_and_metrics as wfm
import _wf_v20_patch as wfp
import wf_scorecard_engine as wf

# 96 curated orthogonal-oriented T-1 / 09:25 PIT features spanning all requested mechanisms
CORE_96_FEATURES = [
    # 1. T0 candle & microstructure (11)
    "t0_open_pct", "t0_ret_1d", "t0_turn_pct", "t0_turn_pct250",
    "t0_upper_shad_hl", "t0_upper_shad_pc", "t0_lower_shad_hl",
    "t0_body_ratio_hl", "t0_amp_pct", "der_is_type_a", "der_is_type_b",
    # 2. T1 09:25 price/open/volume/position/space (24)
    "t1_open_pct", "der_open_abs", "der_open_vs_t0_ret",
    "mcap_yi_t1", "free_mcap_yi_t1", "amount_yi_t1", "real_turn_pct_t1",
    "vol_ratio5_t1", "turn_5_20_t1", "pos_20d_t1", "pos_60d_t1", "pos_250d_t1",
    "der_t0_break60", "der_t0_break20", "dd_20d_t1", "amp_20d_t1", "amp_comp_20v60_t1",
    "bias10_t1", "bias20_t1", "ret_5d_t1", "ret_20d_t1",
    "overhang_pct_t1", "hr10d_space_t1", "hr30d_space_t1",
    # 3. Cooling, old-hot, notices, LHB (21)
    "down_streak_t1", "der_prev_ret5_pre", "der_big10_20d_pre", "der_first_wave_flag",
    "der_dist_5d_vs_csi3d", "list_age", "waves_3y_g15_t1", "zt_cnt_1y_t1",
    "max_streak_3y", "cum_turnover_1y", "trap_waves_3y", "dd_from_3y_high",
    "cool_days_since_last_zt", "cool_days_since_last_2b",
    "comm_posts_1y_pct", "xq_posts_1y_pct",
    "tox_reg_30d_pre", "abn_notice_30d_pre", "ir_cnt_30d_pre",
    "lhb_on_t1", "lhb_bayes_t2_t1", "lhb_inst_net_yi_t1", "lhb_lhasa_share_t1",
    "lhb_has_good_yz_t1", "lhb_has_quant_t1", "lhb_cnt_5d_t1",
    # 4. KPL mainline theme, rank, industry & 09:25 same-theme 10cm auction (22)
    "kpl_has_hist_t0", "der_kpl_rank_eff", "kpl_zt_cnt_t0", "kpl_10yz_t0",
    "kpl_10e1030_t0", "kpl_zt_365_t0", "kpl_unique_plates_3y", "kpl_top_plate_share",
    "der_rk20_ret_in_theme", "der_rk20_amt_in_theme",
    "csrc_ind_ex5_t1", "csrc_ind_ex20_t1", "csrc_ind_rank20_t1",
    "csrc_ind_zt_share5_t1", "csrc_ind_amt_pct250_t1",
    "auc_thm10_n_peers", "auc_thm10_max_streak", "auc_thm10_ldr_open_pct",
    "auc_thm10_peer_mean_open", "auc_thm10_nuke_ratio", "auc_thm10_strong_ratio",
    "auc_thm10_has_yizi_open", "auc_thm20_has_yizi_open", "auc_mkt10_ldr_open_pct",
    "auc_mkt10_lb_nuke_ratio", "auc_rel_gap_vs_thm10", "auc_rel_gap_vs_mkt",
    # 5. Market sentiment, 09:25 microstructure, US & flow (18)
    "L1_zt_cnt_t1", "L1_dt_cnt_t1", "L1_zt_dt_logratio_t1", "L1_zb_rate_t1",
    "L1_max_board_t1", "L1_zt_prem_t1", "L1_duanban_damian_t1", "L1_sent_phase_t1",
    "L1_smb_20d_t1", "L1_breadth_5d_t1", "L1_amt_ratio5v60_t1", "L1_weekday",
    "mkt20_zt_cnt_t1", "mkt20_dt_cnt_t1", "mkt_0925_zt_cnt", "mkt_0925_dt_cnt",
    "mkt20_0925_zt_cnt", "mkt_0925_avg_gap_pct", "mkt_0925_fb20_deepopen_cnt",
    "nt_v3_score_live_t1", "us_ixic_ret1d_on", "us_vix_chg1d_on",
    "wp_net_trading_pct_mcap_pit", "der_t0_amt_vs_mkt", "der_mkt20_share_zt",
    "der_kpl_zt_x_open", "der_ice_deep_open",
]

POOL_SPECS = [
    ("P0_Full", lambda d: np.ones(len(d), dtype=bool)),
    ("P1_Strong", lambda d: d["der_is_strong_mainline"].to_numpy() == 1),
    ("P2_TypeB", lambda d: d["der_is_type_b"].to_numpy() == 1),
    ("P3_TypeA", lambda d: d["der_is_type_a"].to_numpy() == 1),
]

ENTRY_SPECS = [
    ("E1_all", lambda d: np.ones(len(d), dtype=bool)),
    ("E4_deep", lambda d: d["t1_open_pct"].between(-8.0, -1.0).to_numpy()),
    ("E3_weak", lambda d: d["t1_open_pct"].between(-3.0, 2.0).to_numpy()),
    ("E2_mild", lambda d: d["t1_open_pct"].between(1.0, 5.0).to_numpy()),
]

EXIT_SPECS = ["X1_T1_Close", "X2_T2_Close", "X3_20cm_4Branch"]


def sanitize(obj):
    if isinstance(obj, dict):
        return {str(k): sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return None if (math.isnan(v) or math.isinf(v)) else round(v, 6)
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    return obj


def slice_pool_entry_exit(df: pd.DataFrame, pool_name: str, entry_name: str, exit_name: str) -> pd.DataFrame:
    pm = dict(POOL_SPECS)[pool_name](df)
    em = dict(ENTRY_SPECS)[entry_name](df)
    sub = df[pm & em].copy().reset_index(drop=True)
    sub["buy_hhmm"] = 925
    sub["exit_date"] = sub[f"{exit_name}__exit_date"].astype(str)
    sub["exit_hhmm"] = sub[f"{exit_name}__exit_hhmm"].astype(int)
    sub["gross_ret"] = sub[f"{exit_name}__gross_ret"].astype(float)
    sub["net_ret"] = sub[f"{exit_name}__net_ret"].astype(float)
    sub["exit_reason"] = sub[f"{exit_name}__reason"].astype(str)
    sub["hold_bars"] = sub[f"{exit_name}__hold_bars"].astype(int)
    sub = sub[sub["net_ret"].notna() & (sub["exit_date"] > sub["buy_date"])].copy().reset_index(drop=True)
    return sub


def run_causal_mine_removal(
    sub_df: pd.DataFrame,
    feature_cols: list[str],
    mine_mode: str = "self_7pct",
    recalc_freq: str = "monthly",
    mine_start_date: str = "2021-09-01",
    min_warmup_trades: int = 80,
    min_warmup_months: int = 6,
    top_k_mine: int = 10,
    blacklist_pct: float = 20.0,
) -> tuple[pd.DataFrame, dict]:
    """
    Strictly causal Mine-Removal Scorecard (`exit_date < t`):
    - Trains a 0..100 Safety Score predicting `non-mine` (`net_ret > -7%`).
    - Blacklists bottom `blacklist_pct`% lowest safety scores (highest tail-crash risk)
      using ONLY `X_exit[:ptr]` percentiles!
    - Zero leakage, 100% truncation-invariant.
    """
    df = wfm.prepare_hygiene_and_net_ret(sub_df, fee_rt=0.0)
    n = len(df)
    if n == 0:
        out = df.copy()
        out["wf_mine_safety_score"] = np.nan
        out["wf_mine_q20_thr"] = np.nan
        out["is_safe_causal"] = False
        return out, {"n_in": 0}

    buy_dts = df["buy_date"].astype(str).str[:10].to_numpy()
    codes = df["code"].astype(str).str.zfill(6).to_numpy()
    orig_ret = df["net_ret"].to_numpy(dtype=np.float64)

    if mine_mode == "t1t2_7pct":
        r1 = df["X1_T1_Close__net_ret"].to_numpy(dtype=np.float64)
        r2 = df["X2_T2_Close__net_ret"].to_numpy(dtype=np.float64)
        r1 = np.where(np.isfinite(r1), r1, orig_ret)
        r2 = np.where(np.isfinite(r2), r2, orig_ret)
        min_r = np.minimum(r1, r2)
        is_mine = min_r <= -0.07
        y_ret_mine = np.where(is_mine, np.minimum(min_r, -0.07), 0.0001)
        e1 = df["X1_T1_Close__exit_date"].astype(str).str[:10].to_numpy()
        e2 = df["X2_T2_Close__exit_date"].astype(str).str[:10].to_numpy()
        exit_dts = np.where(e2 > e1, e2, e1)
    else:
        is_mine = orig_ret <= -0.07
        y_ret_mine = np.where(is_mine, np.minimum(orig_ret, -0.07), 0.0001)
        exit_dts = df["exit_date"].astype(str).str[:10].to_numpy()

    y_safe = (~is_mine).astype(np.float64)
    can_buy = df["can_buy_hygiene"].to_numpy(bool) & np.isfinite(y_ret_mine)

    X_all = df[feature_cols].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=np.float64)
    uniq_dts = sorted(set(buy_dts.tolist()))
    dt_to_id = {d: i for i, d in enumerate(uniq_dts)}
    day_ids_all = np.array([dt_to_id[d] for d in buy_dts], dtype=np.int32)

    buyable_idx = np.where(can_buy)[0]
    exit_order = sorted(buyable_idx.tolist(), key=lambda i: (exit_dts[i], buy_dts[i], codes[i]))
    exit_order_arr = np.asarray(exit_order, dtype=np.int64)
    exit_dts_sorted = exit_dts[exit_order_arr]
    X_exit = X_all[exit_order_arr]
    r_exit = y_ret_mine[exit_order_arr]
    w_exit = y_safe[exit_order_arr]
    d_exit = day_ids_all[exit_order_arr]

    first_buy_dt = buy_dts[buyable_idx].min() if len(buyable_idx) else "2021-01-04"
    rare_fallback_dt = wfc._add_months(str(first_buy_dt), min_warmup_months)

    by_dt_rows = {}
    for i in buyable_idx:
        by_dt_rows.setdefault(buy_dts[i], []).append(i)
    sorted_trade_dts = sorted(by_dt_rows.keys())

    safety_sc = np.full(n, np.nan, dtype=np.float64)
    q20_thr = np.full(n, np.nan, dtype=np.float64)
    is_safe_out = np.zeros(n, dtype=bool)

    ptr = 0
    n_exit_tot = len(exit_order_arr)
    started = False
    mine_actual_start = None
    cur_card = None
    cur_q20 = 50.0
    last_ptr = -1
    last_month = ""
    n_rebuilds = 0

    for t in sorted_trade_dts:
        while ptr < n_exit_tot and exit_dts_sorted[ptr] < t:
            ptr += 1
        if t < mine_start_date:
            continue
        if not started:
            if (ptr >= min_warmup_trades) or (t >= rare_fallback_dt and ptr >= 50):
                started = True
                mine_actual_start = t
            else:
                continue

        need_rebuild = (
            cur_card is None
            or (recalc_freq == "daily" and ptr > last_ptr)
            or (recalc_freq == "monthly" and t[:7] != last_month)
        )
        if need_rebuild:
            cur_card = wfc.fit_causal_scorecard(
                X_exit[:ptr], r_exit[:ptr], w_exit[:ptr], d_exit[:ptr],
                feature_names=feature_cols, mode="scorecard_0_100",
                top_k=top_k_mine, min_k=5, max_corr=0.65, min_t_stat=1.0, shrink_tau=20.0,
            )
            tr_sc = wfc.score_candidates_with_card(X_exit[:ptr], cur_card)
            q_val = float(np.percentile(tr_sc, blacklist_pct))
            # Pick strict > or >= closest to blacklist_pct
            r_gt = float(np.mean(tr_sc <= q_val)) * 100.0
            r_ge = float(np.mean(tr_sc < q_val)) * 100.0
            cur_q20 = q_val + 0.5 if abs(r_gt - blacklist_pct) <= abs(r_ge - blacklist_pct) else q_val - 0.5
            last_ptr = ptr
            last_month = t[:7]
            n_rebuilds += 1

        rows_t = np.asarray(by_dt_rows[t], dtype=np.int64)
        sc_t = wfc.score_candidates_with_card(X_all[rows_t], cur_card).astype(np.float64)
        safety_sc[rows_t] = sc_t
        q20_thr[rows_t] = cur_q20
        is_safe_out[rows_t] = sc_t > cur_q20

    out = df.copy()
    out["wf_mine_safety_score"] = safety_sc
    out["wf_mine_q20_thr"] = q20_thr
    out["is_mine_label"] = is_mine
    out["is_safe_causal"] = is_safe_out

    # Diagnostics on WF period (>= 2023-01-03)
    wf_m = (out["buy_date"] >= "2023-01-03") & out["wf_mine_safety_score"].notna() & out["can_buy_hygiene"]
    wf_sub = out[wf_m]
    blk = wf_sub[~wf_sub["is_safe_causal"]]
    saf = wf_sub[wf_sub["is_safe_causal"]]
    meta = {
        "mine_mode": mine_mode,
        "recalc_freq": recalc_freq,
        "mine_actual_start": mine_actual_start,
        "n_rebuilds": n_rebuilds,
        "wf_n_scored": int(len(wf_sub)),
        "wf_blacklist_n": int(len(blk)),
        "wf_blacklist_pct": round(float(len(blk) / max(1, len(wf_sub)) * 100.0), 2),
        "wf_safe_n": int(len(saf)),
        "mine_rate_all_pct": round(float(wf_sub["is_mine_label"].mean() * 100.0), 2) if len(wf_sub) else 0.0,
        "mine_rate_blacklisted_pct": round(float(blk["is_mine_label"].mean() * 100.0), 2) if len(blk) else 0.0,
        "mine_rate_safe_pct": round(float(saf["is_mine_label"].mean() * 100.0), 2) if len(saf) else 0.0,
        "mean_ret_blacklisted_pct": round(float(blk["net_ret"].mean() * 100.0), 2) if len(blk) else 0.0,
        "mean_ret_safe_pct": round(float(saf["net_ret"].mean() * 100.0), 2) if len(saf) else 0.0,
        "latest_mine_factors": [
            {"name": f["name"], "t": f["t_cluster"], "shape": f["shape"], "budget_pts": f["budget_pts"]}
            for f in (cur_card.get("factors", []) if cur_card else [])
        ],
    }
    return out, meta


def compute_full_v20_patch_audit(
    pass_df: pd.DataFrame,
    slot_df: pd.DataFrame,
    cand_pool_df: pd.DataFrame,
    v20_ctx: dict,
    wf_start_dt: str,
    end_dt_patch: str = "2026-11-16",
    perm_n: int = 1000,
    seed: int = 20261125,
) -> dict:
    """
    Full Module 4 audit:
      - Mode 1: strict non-overlapping combined V20.0 + patch NAV/Sharpe/MDD across windows
      - Mode 2: pure V20.0 empty-slot standalone NAV, WR, PLR, ex-top5, Y25-26, Y26
      - Same-exposure CSI300 & All-A EW excess return (active-day matched & avg-exp matched)
      - Daily return Pearson correlation with V20.0 (all days & active days)
      - 1,000x permutation test on empty-slot standalone trades
    """
    patch_res = wf.simulate_v20_empty_slot_patch(
        pass_df, v20_ctx=v20_ctx, wf_start_dt=wf_start_dt, end_dt=end_dt_patch,
        respect_stier_waits=True, score_col="wf_score",
    )

    cal_df = v20_ctx["calendar_5y"]
    cal_win = cal_df[cal_df["trade_date"].between(wf_start_dt, end_dt_patch)].sort_values("trade_date").reset_index(drop=True)
    cal_dts = cal_win["trade_date"].tolist()
    dt_idx = {d: i for i, d in enumerate(cal_dts)}
    csi_r = cal_win["csi300_daily_ret"].to_numpy(float)
    ew_r = cal_win["alla_ew_daily_ret"].to_numpy(float)

    empty_set = set(cal_win.loc[cal_win["v20_empty_slot"], "trade_date"]) - set(cal_win.loc[cal_win["v20_has_stier_wait"], "trade_date"])
    p = pass_df.copy()
    p["buy_date"] = p["buy_date"].astype(str).str[:10]
    p["exit_date"] = p["exit_date"].astype(str).str[:10]
    p["code"] = p["code"].astype(str).str.zfill(6)
    p = p[p["buy_date"].between(wf_start_dt, end_dt_patch) & (p["exit_date"] > p["buy_date"])].copy()
    if "wf_score" not in p.columns:
        p["wf_score"] = 100.0
    p_top1 = p.sort_values(["buy_date", "wf_score", "code"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()
    p_emp = p_top1[p_top1["buy_date"].isin(empty_set)].sort_values("buy_date").reset_index(drop=True)
    _, patch_emp_slot = wfm.select_single_slot_trades(
        p_emp.assign(can_buy_hygiene=True), score_col="wf_score", threshold=None, wf_only=False
    )

    dr_emp, _ = wfm.build_daily_mtm_returns(patch_emp_slot, cal_dts, mtm_col=None)
    v20_led = v20_ctx["v20_ledger"]
    v20_win = v20_led[v20_led["buy_date"].between(wf_start_dt, end_dt_patch)].copy().reset_index(drop=True)
    v20_win["source"] = "v20"
    dr_v20, _ = wfp._build_combined_mtm(v20_win, cal_dts)

    # Exact active day boolean mask for empty-slot patch
    act_emp = np.zeros(len(cal_dts), dtype=bool)
    for r in patch_emp_slot.itertuples(index=False):
        bi, ei = dt_idx.get(str(r.buy_date)), dt_idx.get(str(r.exit_date))
        if bi is not None and ei is not None:
            act_emp[max(0, bi) : min(len(cal_dts), ei + 1)] = True

    def _same_exp_win(sdt: str, edt: str) -> dict:
        pos = [dt_idx[d] for d in cal_dts if sdt <= d <= edt]
        if not pos:
            return {}
        d_e = dr_emp[pos]
        d_v = dr_v20[pos]
        c_r = csi_r[pos]
        a_r = ew_r[pos]
        m_a = act_emp[pos]
        exp_ratio = float(np.mean(m_a))
        emp_nav = float(np.prod(1.0 + d_e))
        csi_act_nav = float(np.prod(1.0 + np.where(m_a, c_r, 0.0)))
        ew_act_nav = float(np.prod(1.0 + np.where(m_a, a_r, 0.0)))
        csi_avg_nav = float(np.prod(1.0 + exp_ratio * c_r))
        ew_avg_nav = float(np.prod(1.0 + exp_ratio * a_r))
        corr_all = float(np.corrcoef(d_e, d_v)[0, 1]) if (np.std(d_e) > 1e-12 and np.std(d_v) > 1e-12) else 0.0
        either_act = (np.abs(d_e) > 1e-12) | (np.abs(d_v) > 1e-12)
        corr_act = float(np.corrcoef(d_e[either_act], d_v[either_act])[0, 1]) if (either_act.sum() >= 5 and np.std(d_e[either_act]) > 1e-12 and np.std(d_v[either_act]) > 1e-12) else 0.0
        return {
            "exposure_pct": round(exp_ratio * 100.0, 2),
            "emp_nav": round(emp_nav, 4),
            "csi300_same_act_pct": round((csi_act_nav - 1.0) * 100.0, 2),
            "excess_csi300_same_act_pp": round((emp_nav - csi_act_nav) * 100.0, 2),
            "alla_ew_same_act_pct": round((ew_act_nav - 1.0) * 100.0, 2),
            "excess_alla_ew_same_act_pp": round((emp_nav - ew_act_nav) * 100.0, 2),
            "excess_csi300_same_avg_pp": round((emp_nav - csi_avg_nav) * 100.0, 2),
            "excess_alla_ew_same_avg_pp": round((emp_nav - ew_avg_nav) * 100.0, 2),
            "corr_v20_all_days": round(corr_all, 4),
            "corr_v20_active_days": round(corr_act, 4),
        }

    same_exp = {
        wn: _same_exp_win(s, e)
        for wn, s, e in [
            ("FULL_WF", wf_start_dt, end_dt_patch),
            ("Y2025_2026", "2025-01-01", end_dt_patch),
            ("Y2026", "2026-01-01", end_dt_patch),
        ]
    }
    perm_emp = wfm.perm_test_trading_days(
        patch_emp_slot, cand_pool_df[cand_pool_df["buy_date"].isin(empty_set)],
        wf_start_dt, end_dt_patch, n_perm=perm_n, seed=seed,
    )
    patch_res["same_exposure_and_v20_corr"] = same_exp
    patch_res["empty_slot_permutation_1000"] = perm_emp
    patch_res["patch_emp_slot_df"] = patch_emp_slot
    return patch_res

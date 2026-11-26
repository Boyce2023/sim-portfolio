#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 2A-5 Runner Part 3:
  - Module 4: Day-by-Day Expanding Walk-Forward Dynamic Hold-vs-Cut Scorecard (strictly exit_date < t)
  - 2024-12-31 Physical Truncation Zero-Leakage Proof (max_abs_score_diff == 0.0, max_abs_ret_diff == 0.0)
  - Final Assembly -> w2a5_exit_matrix.csv + w2a5_audit.json
"""
import gc
import json
import os
import pickle
import resource
import sys
import time
import warnings

import numpy as np
import pandas as pd

os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
warnings.filterwarnings("ignore", category=FutureWarning)

WAVE1 = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave2a/w2a5_exit_tree_swaps"
for p in (WAVE1, OUT_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import _wf_core as wfc
import w2a5_data_loader as dl
import w2a5_exit_trees as et
import w2a5_metrics as wm
import step4_mod_rules_and_sim as m1

WF_FEATS = [
    "f_b0_is_zt", "f_b0_ret_1d", "f_b0_body_pct", "f_b0_clv", "f_b0_open_pct",
    "f_b0_ret_vs_buypx", "f_b0_upper_shad", "f_b0_amp_pct", "f_b0_is_20cm",
    "f_tp1_open_pct", "f_tp1_open_vs_buypx", "f_tp1_abs_open_pct", "f_tp1_is_weak_red",
    "f_mkt_b0_zt_cnt", "f_mkt_b0_dt_cnt", "f_mkt_b0_zb_rate", "f_mkt_b0_sent_phase",
    "f_mkt_b0_max_board", "f_mkt_b0_lb_promo", "f_mkt_tp1_0925_zt", "f_mkt_tp1_0925_gap",
    "f_us_ixic_on",
]


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


def build_wf_exit_dataset(ctx: dict, max_dt_cutoff: str = "2026-11-16") -> tuple[pd.DataFrame, dict]:
    """
    Build unified passing-pool dataset indexed by decision day t = tp1_dt (09:25).
    Computes exact causal outcomes at 09:25 cut (`r_0925`), T+1 close/ZT (`r_t1c`), T+2 close/ZT (`r_t2c`),
    and native V20.0 exit (`r_native`).
    """
    mkt_map = ctx["mkt_daily"].set_index("trade_date").to_dict("index")
    records = []
    pools_030 = {}
    for st in m1.STRAT_ORDER:
        p = et.apply_tree_to_pool(ctx["pools"][st], st, "E0_Native", ctx, fee=0.0030, rebuild_mtm=True)
        pools_030[st] = p
        sub = p[p["is_pass_official"] == 1].copy()
        for row_idx, r in sub.iterrows():
            c6, bd = str(r["code"]).zfill(6), str(r["buy_date"])[:10]
            ss = ctx["stock_series"].get(c6)
            if ss is None or bd not in ss["d2i"]:
                continue
            b0 = ss["d2i"][bd]
            if b0 + 1 >= len(ss["dts"]):
                continue
            k1 = b0 + 1
            tp1_dt = str(ss["dts"][k1])
            if tp1_dt > max_dt_cutoff:
                continue

            adjf0 = float(ss["adjf"][b0])
            bp_val = float(r["buy_price_val"]) if pd.notna(r["buy_price_val"]) else float(ss["open"][b0])
            buy_adj = bp_val if bool(r["is_adj_px"]) else bp_val * adjf0
            if buy_adj <= 0:
                continue

            o0, h0, l0, c0 = float(ss["open"][b0]), float(ss["high"][b0]), float(ss["low"][b0]), float(ss["close"][b0])
            pc0 = float(ss["prev_c"][b0]) if np.isfinite(ss["prev_c"][b0]) else o0
            hl0 = max(1e-6, h0 - l0)
            o1, pc1 = float(ss["open"][k1]), float(ss["prev_c"][k1])
            op1_pct = (o1 / pc1 - 1.0) * 100.0 if pc1 > 0 else 0.0
            can_decide_0925 = (not bool(ss["is_yizi_dt"][k1])) and (not bool(ss["open_is_zt"][k1])) and (o1 > float(ss["dt_px"][k1]) + 0.005)

            # Payoff 0: 09:25 cut (defer if yizi_dt)
            kd = et._defer_yizi_dt(ss, k1)
            ed_925, eh_925, ep_925, r_925, _, dd_925 = et._finish_px(ss, kd, float(ss["open"][kd]), 925, buy_adj, 0.0030, "wf_cut_925", kd > k1)

            # Payoff 1: Hold to T+1 close (or ride ZT if sealed on b0 or tp1)
            if bool(ss["is_zt"][b0]):
                ed_t1, eh_t1, ep_t1, r_t1, _, dd_t1 = et._ride_zt_chain(c6, ss, b0, b0, buy_adj, 0.0030, ctx, imm_mode="none", max_k_off=10)
            elif bool(ss["is_zt"][kd]):
                ed_t1, eh_t1, ep_t1, r_t1, _, dd_t1 = et._ride_zt_chain(c6, ss, kd, b0, buy_adj, 0.0030, ctx, imm_mode="none", max_k_off=10)
            elif kd > k1:
                ed_t1, eh_t1, ep_t1, r_t1, dd_t1 = ed_925, eh_925, ep_925, r_925, True
            else:
                ed_t1, eh_t1, ep_t1, r_t1, _, dd_t1 = et._finish_close(ss, k1, b0, buy_adj, 0.0030, "wf_hold_t1c")

            # Payoff 2: Hold to T+2 close (or ZT)
            k2 = et._defer_yizi_dt(ss, min(k1 + 1, len(ss["dts"]) - 1))
            if bool(ss["is_zt"][b0]):
                ed_t2, eh_t2, ep_t2, r_t2, dd_t2 = ed_t1, eh_t1, ep_t1, r_t1, dd_t1
            else:
                ed_t2, eh_t2, ep_t2, r_t2, _, dd_t2 = et._finish_close(ss, k2, b0, buy_adj, 0.0030, "wf_hold_t2c")

            mk = mkt_map.get(tp1_dt, {})
            records.append({
                "pool_idx": int(row_idx),
                "strategy": st,
                "code": c6,
                "b0_dt": bd,
                "buy_date": tp1_dt,  # WF decision timestamp t = tp1_dt 09:25
                "exit_date": str(ed_t1),  # max causal completion date for training gate exit_date < t
                "can_decide_0925": can_decide_0925,
                "r_925": float(r_925), "ed_925": ed_925, "eh_925": eh_925, "ep_925": ep_925, "dd_925": dd_925,
                "r_t1c": float(r_t1), "ed_t1": ed_t1, "eh_t1": eh_t1, "ep_t1": ep_t1, "dd_t1": dd_t1,
                "r_t2c": float(r_t2), "ed_t2": ed_t2, "eh_t2": eh_t2, "ep_t2": ep_t2, "dd_t2": dd_t2,
                "r_native": float(r["net_ret"]),
                "net_ret": float(r_t1 - r_925),  # Incremental Hold-vs-Cut edge used for training scorecard!
                "is_yizi": False,
                "can_buy": bool(can_decide_0925),
                "f_b0_is_zt": float(bool(ss["is_zt"][b0])),
                "f_b0_ret_1d": (c0 / pc0 - 1.0) * 100.0 if pc0 > 0 else 0.0,
                "f_b0_body_pct": (c0 / o0 - 1.0) * 100.0 if o0 > 0 else 0.0,
                "f_b0_clv": (c0 - l0) / hl0,
                "f_b0_open_pct": (o0 / pc0 - 1.0) * 100.0 if pc0 > 0 else 0.0,
                "f_b0_ret_vs_buypx": (c0 * adjf0 / buy_adj - 1.0) * 100.0,
                "f_b0_upper_shad": (h0 - max(o0, c0)) / hl0,
                "f_b0_amp_pct": (h0 - l0) / pc0 * 100.0 if pc0 > 0 else 0.0,
                "f_b0_is_20cm": float(ss["lim"][b0] >= 0.15),
                "f_tp1_open_pct": op1_pct,
                "f_tp1_open_vs_buypx": (o1 * float(ss["adjf"][k1]) / buy_adj - 1.0) * 100.0,
                "f_tp1_abs_open_pct": abs(op1_pct),
                "f_tp1_is_weak_red": float(0.5 <= op1_pct <= 3.0),
                "f_mkt_b0_zt_cnt": float(mk.get("L1_zt_cnt_t1", np.nan)),
                "f_mkt_b0_dt_cnt": float(mk.get("L1_dt_cnt_t1", np.nan)),
                "f_mkt_b0_zb_rate": float(mk.get("L1_zb_rate_t1", np.nan)),
                "f_mkt_b0_sent_phase": float(mk.get("L1_sent_phase_t1", np.nan)),
                "f_mkt_b0_max_board": float(mk.get("L1_max_board_t1", np.nan)),
                "f_mkt_b0_lb_promo": float(mk.get("L1_lb_promo_t1", np.nan)),
                "f_mkt_tp1_0925_zt": float(mk.get("mkt_0925_zt_cnt", np.nan)),
                "f_mkt_tp1_0925_gap": float(mk.get("mkt_0925_avg_gap_pct", np.nan)),
                "f_us_ixic_on": float(mk.get("us_ixic_ret1d_on", np.nan)),
            })

    wf_df = pd.DataFrame(records)
    return wf_df, pools_030


def apply_wf_decisions_to_pools(
    wf_scored: pd.DataFrame, pools_base: dict, ctx: dict, mode_cfg: dict,
) -> dict:
    """Apply WF Hold-vs-Cut scores (for wf_in_window rows) on top of base pools and rebuild MTM."""
    out_pools = {st: pools_base[st].copy() for st in m1.STRAT_ORDER}
    idx_full = {d: i for i, d in enumerate(ctx["cal_full"])}
    idx_5y = {d: i for i, d in enumerate(ctx["cal_5y"])}

    by_st = {st: grp for st, grp in wf_scored.groupby("strategy")}
    for st in m1.STRAT_ORDER:
        df = out_pools[st]
        sub = by_st.get(st)
        if sub is None or sub.empty:
            continue
        ed_arr = df["exit_date"].astype(str).to_numpy(dtype=object)
        eh_arr = df["exit_hhmm"].to_numpy(dtype=int)
        ep_arr = df["exit_price"].to_numpy(dtype=float)
        nr_arr = df["net_ret"].to_numpy(dtype=float)
        dt_def_arr = df["dt_deferred"].to_numpy(bool) if "dt_deferred" in df.columns else np.zeros(len(df), dtype=bool)

        for r in sub.itertuples(index=False):
            if not bool(r.wf_in_window) or not bool(r.can_decide_0925):
                continue
            if mode_cfg.get("unsealed_only", False) and r.f_b0_is_zt > 0.5:
                continue
            sc = float(r.wf_score)
            idx = int(r.pool_idx)
            hold_thr = float(mode_cfg["hold_thr"])
            t2_thr = mode_cfg.get("t2_thr", None)

            if sc < hold_thr:
                # Cut at 09:25
                if mode_cfg.get("override_native", True) or (str(ed_arr[idx]) > str(r.buy_date) or int(eh_arr[idx]) > 925):
                    ed_arr[idx], eh_arr[idx], ep_arr[idx], nr_arr[idx], dt_def_arr[idx] = r.ed_925, int(r.eh_925), float(r.ep_925), float(r.r_925), bool(r.dd_925)
            elif t2_thr is not None and sc >= float(t2_thr):
                # Hold T+2 close / ZT
                ed_arr[idx], eh_arr[idx], ep_arr[idx], nr_arr[idx], dt_def_arr[idx] = r.ed_t2, int(r.eh_t2), float(r.ep_t2), float(r.r_t2c), bool(r.dd_t2)
            elif mode_cfg.get("override_native", True):
                # Hold T+1 close / ZT
                ed_arr[idx], eh_arr[idx], ep_arr[idx], nr_arr[idx], dt_def_arr[idx] = r.ed_t1, int(r.eh_t1), float(r.ep_t1), float(r.r_t1c), bool(r.dd_t1)

        df["exit_date"] = ed_arr
        df["exit_hhmm"] = eh_arr
        df["exit_price"] = ep_arr
        df["net_ret"] = nr_arr
        if "exit_at_open" in df.columns:
            df["exit_at_open"] = (eh_arr == 925)
        if "eo" in df.columns:
            df["eo"] = (eh_arr == 925)
        if st == "high":
            df["v51_cb_loss"] = (nr_arr < -0.02) & (~dt_def_arr)
        df["mtm_full"] = m1.precompute_mtm_segments(df, ctx["cal_full"], idx_full, ctx["bar_lu"], is_20cm_adj=(st == "20cm"))
        df["mtm_5y"] = m1.precompute_mtm_segments(df, ctx["cal_5y"], idx_5y, ctx["bar_lu"], is_20cm_adj=(st == "20cm"))

    return out_pools


def run_wf_and_truncation_proof(ctx: dict):
    """Run Module 4 expanding WF scorecard & strict 2024-12-31 physical truncation verification."""
    wf_df_full, pools_base_full = build_wf_exit_dataset(ctx, max_dt_cutoff="2026-11-16")
    # Ensure exact causal training outcome: y_win = (r_t1c > r_925)
    scored_full, meta_full = wfc.run_expanding_scorecard_loop(
        wf_df_full,
        feature_cols=WF_FEATS,
        mode="scorecard_0_100",
        wf_start_date="2023-01-03",
        min_warmup_trades=120,
        min_warmup_trades_rare=80,
        min_warmup_months=14,
        recalc_freq="daily",
        top_k=10,
        min_k=5,
        max_corr=0.65,
        min_t_stat=1.0,
        shrink_tau=25.0,
        can_buy_mask=wf_df_full["can_decide_0925"].to_numpy(bool),
    )

    # Physical truncation at 2024-12-31 (load fresh truncated context after freeing unused refs!)
    ctx_trunc = dl.load_w2a5_context("2024-12-31", load_5m=False)
    wf_df_trunc, pools_base_trunc = build_wf_exit_dataset(ctx_trunc, max_dt_cutoff="2024-12-31")
    scored_trunc, _ = wfc.run_expanding_scorecard_loop(
        wf_df_trunc,
        feature_cols=WF_FEATS,
        mode="scorecard_0_100",
        wf_start_date="2023-01-03",
        min_warmup_trades=120,
        min_warmup_trades_rare=80,
        min_warmup_months=14,
        recalc_freq="daily",
        top_k=10,
        min_k=5,
        max_corr=0.65,
        min_t_stat=1.0,
        shrink_tau=25.0,
        can_buy_mask=wf_df_trunc["can_decide_0925"].to_numpy(bool),
    )

    sf_le = scored_full[scored_full["buy_date"] <= "2024-12-31"].sort_values(["strategy", "b0_dt", "code"]).reset_index(drop=True)
    st_le = scored_trunc.sort_values(["strategy", "b0_dt", "code"]).reset_index(drop=True)
    assert len(sf_le) == len(st_le), f"WF trunc row mismatch: {len(sf_le)} vs {len(st_le)}"
    vf = sf_le["wf_score"].fillna(-999.0).to_numpy(float)
    vt = st_le["wf_score"].fillna(-999.0).to_numpy(float)
    max_sc_diff = float(np.max(np.abs(vf - vt)))
    assert max_sc_diff == 0.0, f"WF score trunc leak: {max_sc_diff}"

    # Verify combined V20.0 trade returns <= 2024-12-31 are 0.0 diff under truncation
    cfg_check = {"name": "WF_HoldCut_Thr50", "hold_thr": 50.0, "override_native": True, "unsealed_only": False}
    p_wf_full = apply_wf_decisions_to_pools(scored_full, pools_base_full, ctx, cfg_check)
    p_wf_trunc = apply_wf_decisions_to_pools(scored_trunc, pools_base_trunc, ctx_trunc, cfg_check)
    tr_f, _ = m1.run_combined_v20(p_wf_full, ctx["untrig_base"], {}, end_dt="2026-11-16")
    tr_t, _ = m1.run_combined_v20(p_wf_trunc, ctx_trunc["untrig_base"], {}, end_dt="2024-12-31")
    tr_f_le = tr_f[tr_f["exit_date"] <= "2024-12-30"].sort_values(["buy_date", "code"]).reset_index(drop=True)
    tr_t_le = tr_t[tr_t["exit_date"] <= "2024-12-30"].sort_values(["buy_date", "code"]).reset_index(drop=True)
    assert len(tr_f_le) == len(tr_t_le), f"WF combined trunc count mismatch: {len(tr_f_le)} vs {len(tr_t_le)}"
    assert list(zip(tr_f_le["buy_date"], tr_f_le["code"])) == list(zip(tr_t_le["buy_date"], tr_t_le["code"]))
    max_ret_diff = float(np.max(np.abs(tr_f_le["net_ret"].to_numpy(float) - tr_t_le["net_ret"].to_numpy(float))))
    assert max_ret_diff == 0.0, f"WF combined ret trunc leak: {max_ret_diff}"
    del ctx_trunc, wf_df_trunc, pools_base_trunc, scored_trunc, p_wf_trunc, tr_t, tr_t_le
    gc.collect()

    trunc_proof = {
        "cutoff": "2024-12-31",
        "n_wf_rows_checked": int(len(sf_le)),
        "n_combined_trades_exiting_le_cutoff": int(len(tr_f_le)),
        "max_abs_score_diff": max_sc_diff,
        "max_abs_ret_diff": max_ret_diff,
        "zero_leakage_pass": True,
    }

    # Evaluate grid of WF dynamic exit configs
    cand_all = pd.concat(
        [pools_base_full[st][pools_base_full[st]["is_pass_official"] == 1][["buy_date", "code", "net_ret"]] for st in m1.STRAT_ORDER],
        ignore_index=True,
    )
    wf_configs = [
        {"name": "WF_HoldCut_All_Thr45", "hold_thr": 45.0, "override_native": True, "unsealed_only": False},
        {"name": "WF_HoldCut_All_Thr50", "hold_thr": 50.0, "override_native": True, "unsealed_only": False},
        {"name": "WF_HoldCut_All_Thr55", "hold_thr": 55.0, "override_native": True, "unsealed_only": False},
        {"name": "WF_HoldCut_All_Thr60", "hold_thr": 60.0, "override_native": True, "unsealed_only": False},
        {"name": "WF_3Act_T2Thr65_Cut50", "hold_thr": 50.0, "t2_thr": 65.0, "override_native": True, "unsealed_only": False},
        {"name": "WF_UnsealedOnly_Thr50", "hold_thr": 50.0, "override_native": True, "unsealed_only": True},
        {"name": "WF_KeepNative_BoostCut_Thr45", "hold_thr": 45.0, "override_native": False, "unsealed_only": True},
        {"name": "WF_KeepNative_BoostCut_Thr50", "hold_thr": 50.0, "override_native": False, "unsealed_only": True},
    ]

    wf_rows = []
    wf_summaries = []
    for cfg in wf_configs:
        p_mod = apply_wf_decisions_to_pools(scored_full, pools_base_full, ctx, cfg)
        tr_c, _ = m1.run_combined_v20(p_mod, ctx["untrig_base"], {})
        ev_c = wm.evaluate_ledger_windows(tr_c, None, cand_all, ctx, perm_n=1000)
        wf_rows.append(wm.flatten_row(f"M4_COMB_{cfg['name']}", "combined", cfg["name"], "m4_wf_combined", ev_c))
        for st in ("1to2", "2to3", "3to4", "20cm"):
            pass_df, slot_df = m1.sim_standalone(st, p_mod[st], np.zeros(len(p_mod[st])))
            ev_s = wm.evaluate_ledger_windows(slot_df, pass_df, pass_df, ctx, perm_n=500)
            wf_rows.append(wm.flatten_row(f"M4_SOLO_{st}_{cfg['name']}", st, cfg["name"], "m4_wf_standalone", ev_s))
        wf_summaries.append({
            "config": cfg["name"],
            "wf_2326_nav": ev_c["windows"]["WF_23_26"]["nav"],
            "wf_2326_mdd": ev_c["windows"]["WF_23_26"]["daily_mdd_pct"],
            "wf_2326_wr": ev_c["windows"]["WF_23_26"]["wr_pct"],
            "oos_2526_nav": ev_c["windows"]["OOS_25_26"]["nav"],
            "y2026_nav": ev_c["windows"]["Y2026"]["nav"],
            "y5_nav": ev_c["windows"]["Y5"]["nav"],
            "perm_wf_sd_p": ev_c["perm_wf"]["same_day_p_nav"],
        })

    return pd.DataFrame(wf_rows), {
        "truncation_proof_20241231": trunc_proof,
        "wf_meta": {
            "wf_actual_start": meta_full["wf_actual_start"],
            "n_rebuilds": meta_full["n_rebuilds"],
            "n_wf_decisions": meta_full["n_wf_candidates"],
            "latest_top_factors": [
                {"name": f["name"], "t": f["t_cluster"], "shape": f["shape"], "pts": f["bin_pts"], "wr_pct": f["bin_wr_pct"], "mean_pct": f["bin_mean_pct"]}
                for f in (meta_full["latest_scorecard"].get("factors", []) if meta_full["latest_scorecard"] else [])
            ],
        },
        "wf_combined_summary": wf_summaries,
    }


def main():
    t0 = time.time()
    ctx = dl.load_w2a5_context("2026-11-16", load_5m=False)
    print(f"[M4+Audit] Context loaded in {time.time()-t0:.2f}s")

    m4_df, m4_meta = run_wf_and_truncation_proof(ctx)
    print(f"[M4] Truncation proof PASS: {m4_meta['truncation_proof_20241231']}")

    m13_df = pd.read_csv(f"{OUT_DIR}/_partial_m1_m3_matrix.csv")
    m2_df = pd.read_csv(f"{OUT_DIR}/_partial_m2_swaps.csv")
    m3_details = pickle.load(open(f"{OUT_DIR}/_partial_m3_details.pkl", "rb"))

    full_matrix = pd.concat([m13_df, m2_df, m4_df], ignore_index=True)
    full_matrix.to_csv(f"{OUT_DIR}/w2a5_exit_matrix.csv", index=False, encoding="utf-8-sig")

    # Build rich w2a5_audit.json
    base_030 = m13_df[m13_df["label"] == "BASE_V20_UNIFIED_030"].iloc[0].to_dict()
    base_nat = m13_df[m13_df["label"] == "BASE_V20_NATIVE_FEE"].iloc[0].to_dict()

    m1_solo = m13_df[m13_df["scope"] == "standalone"].copy()
    m1_comb = m13_df[m13_df["scope"] == "combined_v20_single_swap"].copy()
    m1_all6 = m13_df[m13_df["scope"] == "combined_v20_all6"].copy()

    best_solo_by_strat = {}
    for st in m1.STRAT_ORDER:
        sub = m1_solo[m1_solo["strategy"] == st].sort_values("Y5_nav", ascending=False)
        nat_r = sub[sub["exit_tree"] == "E0_Native"].iloc[0]
        top_r = sub.iloc[0]
        best_solo_by_strat[st] = {
            "native_030": {"tree": "E0_Native", "y5_nav": nat_r["Y5_nav"], "wf_nav": nat_r["WF_23_26_nav"], "oos_2526_nav": nat_r["OOS_25_26_nav"], "y26_nav": nat_r["Y2026_nav"], "mdd": nat_r["Y5_mdd"], "wr": nat_r["Y5_wr"]},
            "best_y5": {"tree": top_r["exit_tree"], "y5_nav": top_r["Y5_nav"], "wf_nav": top_r["WF_23_26_nav"], "oos_2526_nav": top_r["OOS_25_26_nav"], "y26_nav": top_r["Y2026_nav"], "mdd": top_r["Y5_mdd"], "wr": top_r["Y5_wr"]},
        }

    m2_v20 = m2_df[(m2_df["scope"] == "m2_swap") & (m2_df["label"].str.startswith("M2_v20_slot|"))].sort_values("Y5_nav", ascending=False)
    rss_mb = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 2)

    audit = _sanitize({
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t0, 2),
        "peak_rss_mb": rss_mb,
        "d12_yfinance_imported": "yfinance" in sys.modules,
        "baseline_parity": {
            "v20_native_278": base_nat,
            "v20_unified_030_278": base_030,
        },
        "module1_cross_transplant": {
            "total_matrix_rows": int(len(m1_solo) + len(m1_comb) + len(m1_all6)),
            "best_standalone_vs_native": best_solo_by_strat,
            "top10_combined_single_swaps_by_y5": m1_comb.sort_values("Y5_nav", ascending=False).head(10)[
                ["strategy", "exit_tree", "Y5_n", "Y5_wr", "Y5_nav", "Y5_ex5", "Y5_mdd", "WF_23_26_nav", "OOS_25_26_nav", "Y2026_nav", "perm5y_sd_p"]
            ].to_dict("records"),
            "all6_unified_trees": m1_all6.sort_values("Y5_nav", ascending=False)[
                ["exit_tree", "Y5_n", "Y5_wr", "Y5_nav", "Y5_ex5", "Y5_mdd", "WF_23_26_nav", "OOS_25_26_nav", "Y2026_nav"]
            ].to_dict("records"),
        },
        "module2_weak_red_0925_swap": {
            "total_configs": int(len(m2_df)),
            "top15_v20_slot_configs_by_y5": m2_v20.head(15)[
                ["label", "n_swaps", "Y5_n", "Y5_wr", "Y5_nav", "Y5_ex5", "Y5_mdd", "WF_23_26_nav", "OOS_25_26_nav", "Y2026_nav"]
            ].to_dict("records"),
            "top10_v20_slot_configs_by_2526": m2_v20.sort_values("OOS_25_26_nav", ascending=False).head(10)[
                ["label", "n_swaps", "Y5_n", "Y5_wr", "Y5_nav", "OOS_25_26_nav", "Y2026_nav", "Y5_mdd"]
            ].to_dict("records"),
        },
        "module3_5m_blowoff_clv_guard": m3_details,
        "module4_wf_dynamic_exit": m4_meta,
    })

    with open(f"{OUT_DIR}/w2a5_audit.json", "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2, allow_nan=False)

    print(f"[ALL DONE in {time.time()-t0:.2f}s | RSS={rss_mb}MB] Matrix rows={len(full_matrix)} -> {OUT_DIR}")


if __name__ == "__main__":
    main()

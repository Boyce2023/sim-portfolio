#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 2A-6 Part 2: Module 4 (PM Pain Point #4B)
  1. Upstream Rank-1 unbuyable (yizi / over-open-cap) & conditional-order untrig fallback to Rank-2.
  2. V20.0 41 wait days & missed 09:25 Rank-2 candidates audit.
  3. Same-strategy Rank-1 vs Rank-2 comparison across all multi-candidate days.
  4. Near-Miss Pool (3-5pt relaxed edge candidates + 20cm_A76 + full near_line) evaluated via
     strictly causal day-by-day WF multi-factor scorecard (`wf_scorecard_engine.py` Mode A),
     both standalone on V20 empty days and strict no-peek combined with V20.0.
  5. 2024-12-31 physical truncation proof (max_abs_diff == 0.0).
Zero yfinance (D12). Zero lookahead.
"""
import json
import os
import pickle
import resource
import sys
import time

import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)

import _w2a6_common as w2c
import wf_scorecard_engine as wfe

OUT_DIR = w2c.OUT_DIR


def _grp_stats(rets: np.ndarray) -> dict:
    if len(rets) == 0:
        return {"n": 0, "wr_pct": 0.0, "plr": 0.0, "mean_pct": 0.0, "median_pct": 0.0, "solo_nav": 1.0}
    w, l = rets[rets > 0], rets[rets <= 0]
    plr = float(w.mean() / abs(l.mean())) if (len(w) and len(l) and l.mean() < 0) else (99.0 if len(w) else 0.0)
    return {
        "n": int(len(rets)),
        "wr_pct": round(float((rets > 0).mean() * 100.0), 2),
        "plr": round(plr, 2),
        "mean_pct": round(float(rets.mean() * 100.0), 2),
        "median_pct": round(float(np.median(rets) * 100.0), 2),
        "solo_nav": round(float(np.prod(1.0 + rets)), 4),
    }


def audit_rank1_skips_and_rank2(ctx: dict) -> dict:
    print("[Module 4A] Auditing upstream yizi/over-cap Rank-1 skips, 1to2 untrig->Rank2, same-strat Rank1 vs Rank2, and V20 41 waits...")
    master_5y = ctx["master_5y"]
    pass_pool = ctx["pass_pool_64"].copy()
    cal_5y = ctx["cal_5y"]
    idx_5y = ctx["idx_5y"]
    slot_pool = ctx["slot_pool_64"]
    ut_5y = ctx["untrig_base"]
    tr_base = ctx["tr_base"]
    waits_41 = ctx["v20_ctx"]["v20_waits"]

    # 1. Upstream yizi / over-cap audit
    # 1a. 1to2: front-lock yizi/overcap in same plate & 1to2 untrig days with buyable Rank 2
    p12_pass = master_5y[(master_5y["strategy"] == "1to2") & (master_5y["is_pass_official"] == 1) & (master_5y["sim_ok"] == 1)].copy()
    p12_pass["net_ret"] = p12_pass["net_ret_f64"]
    p12_untrig_dts = set(master_5y[(master_5y["strategy"] == "1to2") & (master_5y["pool_layer"] == "untrig")]["buy_date"])
    has_fl = (p12_pass["s12_plate_d2_yizi_cnt"].fillna(0) > 0) | (p12_pass["s12_atom_front_lock_crowd"].fillna(0) > 0) | (p12_pass["s12_atom_front_lock1"].fillna(0) > 0)
    p12_on_ut = p12_pass[p12_pass["buy_date"].isin(p12_untrig_dts)]
    p12_clean_no_ut = p12_pass[~p12_pass["buy_date"].isin(p12_untrig_dts)]

    # 1b. 2to3: load raw_all from _cache_2to3_pit_20261116.pkl to identify days with yizi or open > +2.5% 2-board peers
    c23_path = f"{w2c.SIM}/backtests_astock/_archive/20261118_wave1_static_exit_opt/s2_2to3_exit/_cache_2to3_pit_20261116.pkl"
    c23 = pickle.load(open(c23_path, "rb"))
    raw23 = c23["raw_all"]
    raw23 = raw23[raw23["buy_date"].between("2021-11-16", "2026-11-16")].copy()
    yizi_dts_23 = set(raw23[~raw23["buyable_open"]]["buy_date"].astype(str).str[:10])
    overcap_dts_23 = set(raw23[raw23["buyable_open"] & (~raw23["prev_is_yizi"]) & (raw23["open_pct"] > 0.025)]["buy_date"].astype(str).str[:10])
    p23_pass = pass_pool[pass_pool["strategy"] == "2to3"].sort_values(["buy_date", "score", "code"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()

    # 1c. 3to4: load cand_df from pit_exit_cache_full.pkl to identify days with ~buyable_open or open_pct > 0.092 or untriggered buy_px is None
    c34_path = f"{w2c.SIM}/backtests_astock/exit_factors_v2_20261118/f1_3to4/pit_exit_cache_full.pkl"
    c34 = pickle.load(open(c34_path, "rb"))
    d34 = c34["cand_df"].copy()
    d34["sc_v40"] = c34["sc_v40"]
    d34 = d34[d34["buy_date"].astype(str).between("2021-11-16", "2026-11-16")].copy()
    yizi_dts_34 = set(d34[~d34["buyable_open"]]["buy_date"].astype(str).str[:10])
    overcap_dts_34 = set(d34[d34["buyable_open"] & (d34["open_pct"] > 0.092)]["buy_date"].astype(str).str[:10])
    p34_pass = pass_pool[pass_pool["strategy"] == "3to4"].sort_values(["buy_date", "score", "code"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()
    p34_m = master_5y[(master_5y["strategy"] == "3to4") & (master_5y["is_pass_official"] == 1)].copy()
    p34_m["net_ret"] = p34_m["net_ret_f64"]

    upstream_skip_audit = {
        "1to2_front_lock_or_yizi_in_plate": _grp_stats(p12_pass.loc[has_fl, "net_ret"].to_numpy(float)),
        "1to2_clean_no_front_lock": _grp_stats(p12_pass.loc[~has_fl, "net_ret"].to_numpy(float)),
        "1to2_rank2_when_rank1_untrig": _grp_stats(p12_on_ut["net_ret"].to_numpy(float)),
        "1to2_normal_no_untrig_day": _grp_stats(p12_clean_no_ut["net_ret"].to_numpy(float)),
        "2to3_days_with_yizi_peer": _grp_stats(p23_pass.loc[p23_pass["buy_date"].isin(yizi_dts_23), "net_ret"].to_numpy(float)),
        "2to3_days_no_yizi_peer": _grp_stats(p23_pass.loc[~p23_pass["buy_date"].isin(yizi_dts_23), "net_ret"].to_numpy(float)),
        "2to3_days_with_overcap25_peer": _grp_stats(p23_pass.loc[p23_pass["buy_date"].isin(overcap_dts_23), "net_ret"].to_numpy(float)),
        "2to3_days_no_overcap25_peer": _grp_stats(p23_pass.loc[~p23_pass["buy_date"].isin(overcap_dts_23), "net_ret"].to_numpy(float)),
        "3to4_days_with_yizi_3b_peer": _grp_stats(p34_pass.loc[p34_pass["buy_date"].isin(yizi_dts_34), "net_ret"].to_numpy(float)),
        "3to4_days_no_yizi_3b_peer": _grp_stats(p34_pass.loc[~p34_pass["buy_date"].isin(yizi_dts_34), "net_ret"].to_numpy(float)),
        "3to4_days_with_overcap92_3b_peer": _grp_stats(p34_pass.loc[p34_pass["buy_date"].isin(overcap_dts_34), "net_ret"].to_numpy(float)),
        "3to4_non_top1_3b_open_flag": _grp_stats(p34_m.loc[p34_m["s34_af_02"].fillna(0) < 0, "net_ret"].to_numpy(float)),
        "3to4_top1_3b_open_flag": _grp_stats(p34_m.loc[p34_m["s34_af_02"].fillna(0) >= 0, "net_ret"].to_numpy(float)),
    }

    # 2. Same-strategy Rank 1 vs Rank 2 (and Rank 3) on all multi-candidate passing days
    same_strat_rk = {}
    for st in ("1to2", "2to3", "3to4", "20cm", "pry"):
        sub = pass_pool[(pass_pool["strategy"] == st) & (pass_pool["tier"] != "20cm_A(76-81)")].copy()
        r1_list, r2_list = [], []
        for dt, grp in sub.groupby("buy_date"):
            if len(grp) < 2:
                continue
            gs = grp.sort_values(["score", "code"], ascending=[False, True])
            r1_list.append(float(gs.iloc[0]["net_ret"]))
            r2_list.append(float(gs.iloc[1]["net_ret"]))
        same_strat_rk[st] = {
            "n_multi_days": len(r1_list),
            "rank1": _grp_stats(np.asarray(r1_list, float)),
            "rank2": _grp_stats(np.asarray(r2_list, float)),
        }

    # Cross-strategy Rank 1 vs Rank 2 when >= 2 strategies pass on same day
    pass_s2c = pass_pool[pass_pool["tier"] != "20cm_A(76-81)"].copy()
    pass_s2c["prio"] = pass_s2c["tier"].map(w2c.CANON_S2C_TIER_MAP).fillna(999).astype(int)
    cs_r1, cs_r2 = [], []
    for dt, grp in pass_s2c.groupby("buy_date"):
        if grp["strategy"].nunique() < 2:
            continue
        gs = grp.sort_values(["prio", "score", "code"], ascending=[True, False, True]).drop_duplicates("strategy", keep="first")
        if len(gs) >= 2:
            cs_r1.append(float(gs.iloc[0]["net_ret"]))
            cs_r2.append(float(gs.iloc[1]["net_ret"]))
    cross_strat_rk = {
        "n_multi_strat_days": len(cs_r1),
        "rank1_s2c": _grp_stats(np.asarray(cs_r1, float)),
        "rank2_s2c": _grp_stats(np.asarray(cs_r2, float)),
    }

    # 3. Audit V20.0 41 S-tier waits & missed 09:25 Rank-2 candidates + check afternoon fallback after 10:30/11:30 cancel
    # Wait: in waits_41, missed_0925_candidates was empty in v20_waits_41.json ONLY IF slot_pool didn't record them,
    # Wait! Let's check pass_pool AND slot_pool on all 41 wait dates directly!
    wait_dts_41 = [w["buy_date"] for w in waits_41]
    wait_missed_pass = []
    wait_missed_slot = []
    after_cancel_cands = []
    for w in waits_41:
        bd = w["buy_date"]
        c_hh = int(w["cancel_hhmm"])
        # Look up all buyable 09:25 passing candidates on bd
        p_bd = pass_s2c[(pass_s2c["buy_date"] == bd) & (pass_s2c["buy_hhmm"] == 925)].sort_values(["prio", "score"], ascending=[True, False])
        if not p_bd.empty:
            top = p_bd.iloc[0]
            wait_missed_pass.append({
                "buy_date": bd, "wait_strat": w["wait_strategy"], "wait_tier": w["wait_tier"],
                "missed_strat": top["strategy"], "missed_code": top["code"], "missed_name": top["name"],
                "missed_score": float(top["score"]), "missed_ret": float(top["net_ret"]),
            })
        s_bd = slot_pool[(slot_pool["buy_date"] == bd) & (slot_pool["tier"] != "20cm_A(76-81)") & (slot_pool["buy_hhmm"] == 925)].sort_values(["score"], ascending=False)
        if not s_bd.empty:
            top_s = s_bd.iloc[0]
            wait_missed_slot.append(float(top_s["net_ret"]))
        p_late = pass_s2c[(pass_s2c["buy_date"] == bd) & (pass_s2c["buy_hhmm"] > c_hh)]
        if not p_late.empty:
            after_cancel_cands.append(float(p_late.iloc[0]["net_ret"]))

    # Also test adding 1to2 Rank-2 (when Rank 1 is untrig) as fallback in V20.0 empty-slot patch!
    p12_rank2_df = p12_on_ut.sort_values(["buy_date", "v20_score", "code"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()
    p12_rank2_df["mtm_5y_col"] = p12_rank2_df["mtm_5y"]
    patch_1to2_r2 = w2c.wfp.simulate_v20_empty_slot_patch(
        p12_rank2_df.assign(wf_score=p12_rank2_df["v20_score"]),
        v20_ctx=ctx["v20_ctx"], wf_start_dt="2021-11-16", end_dt="2026-11-16",
        score_col="wf_score", patch_mtm_col="mtm_5y_col",
    )

    return {
        "upstream_yizi_overcap_skip_audit": upstream_skip_audit,
        "same_strategy_rank1_vs_rank2": same_strat_rk,
        "cross_strategy_rank1_vs_rank2": cross_strat_rk,
        "v20_41_waits_missed_0925_rank2": {
            "n_waits": len(waits_41),
            "n_had_0925_pass_cand": len(wait_missed_pass),
            "missed_0925_pass_stats": _grp_stats(np.asarray([x["missed_ret"] for x in wait_missed_pass], float)),
            "missed_0925_slot_stats": _grp_stats(np.asarray(wait_missed_slot, float)),
            "n_had_post_cancel_cand": len(after_cancel_cands),
            "missed_details_sample": wait_missed_pass[:15],
        },
        "1to2_rank2_on_untrig_v20_patch": {
            "mode1_combined": {k: v for k, v in patch_1to2_r2["mode1_strict_combined_no_peek"].items() if k != "skipped_v20_trades"},
            "mode2_standalone_empty": patch_1to2_r2["mode2_empty_slot_standalone"],
        },
    }


def _select_pure_pit_features(df: pd.DataFrame, catalog: dict) -> list[str]:
    """Select strictly pre-entry PIT numeric features from master catalog (ZERO bar_* exit cols!)."""
    mfc = catalog["master_factor_catalog"]
    allowed_roles = {"entry_feature", "cross_transplant_factor"}
    # Keep dense market/stock/L1/L2/L3/oh/evo/sd/yz/abn/rd25/nt/us/comm/macro/wp/pol/xtr features
    # Exclude sparse strategy-specific atomic cols (s12_*, s23_*, s34_*, shigh_*, spry_*, s20cm_*)
    cols = []
    for c in df.columns:
        info = mfc.get(c, {})
        role = info.get("role", "") if isinstance(info, dict) else ""
        if role not in allowed_roles:
            continue
        if c.startswith(("bar_", "s12_", "s23_", "s34_", "shigh_", "spry_", "s20cm_")):
            continue
        if pd.api.types.is_numeric_dtype(df[c]):
            cols.append(c)
    for extra in ("open_pct", "rel_score_gap"):
        if extra in df.columns and extra not in cols:
            cols.append(extra)
    return cols


def run_nearmiss_wf_audit(ctx: dict) -> dict:
    print("[Module 4B] Running Causal WF Scorecard Mode A on Near-Miss Pools (3-5pt relaxed & full near_line)...")
    m5y = ctx["master_5y"].copy()
    m5y["net_ret"] = m5y["net_ret_f64"]
    m5y["can_buy"] = (m5y["sim_ok"] == 1) & m5y["net_ret"].notna()
    m5y["is_yizi"] = False

    thr_map = {"1to2": 304.8, "2to3": 90.0, "3to4": 90.0, "high": 88.0, "pry": 165.0, "20cm": 82.0}
    m5y["rel_score_gap"] = m5y["v20_score"].astype(float) - m5y["strategy"].map(thr_map).astype(float)

    feat_cols = _select_pure_pit_features(m5y, ctx["catalog"])
    assert not any(c.startswith("bar_") for c in feat_cols), "Leakage guard: bar_* found in feature_cols!"
    print(f"  Selected {len(feat_cols)} pure entry-time PIT features for Near-Miss WF Scorecard.")

    # Define Near-Miss sub-pools (only non-passing buyable candidates!)
    edge_base = m5y[(m5y["is_pass_official"] == 0) & (m5y["sim_ok"] == 1) & m5y["net_ret"].notna()].copy()

    mask_tight_3_5 = (
        ((edge_base["strategy"] == "1to2") & (edge_base["v20_score"] >= 295.0))
        | ((edge_base["strategy"] == "2to3") & (edge_base["v20_score"] >= 85.0))
        | ((edge_base["strategy"] == "3to4") & (edge_base["v20_score"] >= 85.0))
        | ((edge_base["strategy"] == "high") & (edge_base["v20_score"] >= 83.0))
        | ((edge_base["strategy"] == "pry") & (edge_base["v20_score"] >= 160.0))
        | ((edge_base["strategy"] == "20cm") & (edge_base["v20_score"] >= 76.0))
    )
    nm_pools = {
        "NM_Tight_3to5pt": edge_base[mask_tight_3_5].copy(),
        "NM_NearLine_All": edge_base[edge_base["is_near_line"] == 1].copy(),
        "NM_Excl_Pry_Tight": edge_base[mask_tight_3_5 & (edge_base["strategy"] != "pry")].copy(),
        "NM_20cm_A76_81": edge_base[(edge_base["strategy"] == "20cm") & (edge_base["v20_score"] >= 76.0)].copy(),
        "NM_Pry_150_164": edge_base[(edge_base["strategy"] == "pry") & (edge_base["v20_score"] >= 150.0)].copy(),
        "NM_All_Edge_2769": edge_base.copy(),
    }

    # Raw baseline breakdown on V20 empty days (strict no S-tier wait)
    cal_5y_df = ctx["cal_df_5y"]
    empty_strict_dts = set(cal_5y_df.loc[cal_5y_df["v20_empty_strict_no_stier_wait"], "trade_date"])

    raw_breakdown = {}
    for pname, pdf in nm_pools.items():
        by_st = {}
        for st, grp in pdf.groupby("strategy"):
            grp_e = grp[grp["buy_date"].isin(empty_strict_dts)]
            by_st[st] = {
                "all_edge": _grp_stats(grp["net_ret"].to_numpy(float)),
                "on_v20_empty_days": _grp_stats(grp_e["net_ret"].to_numpy(float)),
            }
        raw_breakdown[pname] = {
            "total_rows": int(len(pdf)),
            "on_v20_empty_days_rows": int(pdf["buy_date"].isin(empty_strict_dts).sum()),
            "overall": _grp_stats(pdf["net_ret"].to_numpy(float)),
            "overall_empty_days": _grp_stats(pdf.loc[pdf["buy_date"].isin(empty_strict_dts), "net_ret"].to_numpy(float)),
            "by_strategy": by_st,
        }

    # Run Mode A WF Scorecard (strictly causal exit_date < t) on main Near-Miss pools
    wf_results = {}
    csv_rows_m4 = []
    ut_5y = ctx["untrig_base"]
    cal_5y = ctx["cal_5y"]
    idx_5y = ctx["idx_5y"]
    slot_pool = ctx["slot_pool_64"]

    for pname in ("NM_Tight_3to5pt", "NM_NearLine_All", "NM_Excl_Pry_Tight", "NM_20cm_A76_81"):
        pdf = nm_pools[pname].copy()
        res = wfe.run_wf_scorecard_new_strategy(
            pdf, feat_cols, v20_ctx=ctx["v20_ctx"],
            wf_start_date="2023-01-03", end_date="2026-11-16",
            min_warmup_trades=60, min_warmup_trades_rare=40, min_warmup_months=14,
            recalc_freq="daily", top_k=10, min_k=4, max_corr=0.65,
            min_t_stat=1.0, shrink_tau=20.0, fee_rt=0.0020,
            mtm_col=None, thresholds=("all_cands", "top30", "top20", "top10", 70, 75, 80),
            eval_v20_patch=True, perm_n=1000, seed=20261125,
        )
        # Extract strategy composition of top20 & abs_70 on V20 empty days
        th_details = {}
        for tname, tres in res["threshold_results"].items():
            vp = tres.get("v20_empty_patch")
            pass_sub = tres["pass_df"]
            pass_empty = pass_sub[pass_sub["buy_date"].isin(empty_strict_dts)]

            # Exact bar-MTM combined V20 + Near-Miss simulation (strictly no-peek, S-tier wait respected)
            exact_comb_ev = None
            if tname in ("top20", "top10", "abs_70", "abs_75") and not pass_sub.empty:
                p_patch = pass_sub[["buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name", "strategy", "wf_score", "net_ret", "mtm_5y", "open_pct"]].copy()
                p_patch["tier"] = "nm_patch"
                p_patch["score"] = p_patch["wf_score"].astype(float)
                p_patch["is_untrig"] = False
                # Combine with slot_pool where V20 signals always have prio <= 6 and patch has prio = 50
                comb_pool = pd.concat([slot_pool, p_patch[slot_pool.columns.intersection(p_patch.columns)]], ignore_index=True)
                def _nm_rank_fn(d):
                    out = d.copy()
                    p = out["tier"].map(w2c.CANON_S2C_TIER_MAP).fillna(999).astype(int)
                    p = np.where(out["tier"] == "nm_patch", 50, p)
                    out["prio"] = p
                    return out
                sim_c = w2c.simulate_multi_slot_mtm(
                    comb_pool, _nm_rank_fn, cal_5y, idx_5y, n_slots=1,
                    untrig_df=ut_5y, timing_mode="s_tier_reserve_only", max_per_strat_per_day=1,
                )
                exact_comb_ev = w2c.evaluate_portfolio_windows(sim_c["trades_df"], sim_c["dr_5y"], ctx, perm_n=200)
                w = exact_comb_ev["windows"]
                csv_rows_m4.append({
                    "module": "Module4_NearMiss",
                    "scheme_id": f"M4_{pname}_{tname}_V20Patch",
                    "desc": f"V20空仓日补位(严格不偷看未来): {pname} [{tname}]",
                    "n_5y": w["Y5"]["n"], "wr_5y_pct": w["Y5"]["wr_pct"], "plr_5y": w["Y5"]["plr"], "mean_5y_pct": w["Y5"]["mean_pct"],
                    "nav_5y": w["Y5"]["nav"], "mtm_nav_5y": w["Y5"]["mtm_nav"], "ex5_5y": w["Y5"]["ex_top5_nav"],
                    "mdd_5y_pct": w["Y5"]["daily_mdd_pct"], "sharpe_5y": w["Y5"]["daily_sharpe"], "calmar_5y": w["Y5"]["daily_calmar"],
                    "excess_csi_5y_pp": w["Y5"]["excess_csi300_pp"], "perm_sd_p_5y": exact_comb_ev["perm_5y"].get("same_day_p_nav"), "perm_any_p_5y": exact_comb_ev["perm_5y"].get("any_cand_day_p_nav"),
                    "n_wf": w["WF_2023_2026"]["n"], "nav_wf": w["WF_2023_2026"]["nav"], "ex5_wf": w["WF_2023_2026"]["ex_top5_nav"],
                    "mdd_wf_pct": w["WF_2023_2026"]["daily_mdd_pct"], "sharpe_wf": w["WF_2023_2026"]["daily_sharpe"], "calmar_wf": w["WF_2023_2026"]["daily_calmar"],
                    "excess_csi_wf_pp": w["WF_2023_2026"]["excess_csi300_pp"], "perm_sd_p_wf": exact_comb_ev["perm_wf"].get("same_day_p_nav"),
                    "n_is": w["IS_2021_2024"]["n"], "nav_is": w["IS_2021_2024"]["nav"], "sharpe_is": w["IS_2021_2024"]["daily_sharpe"],
                    "n_2526": w["Y2025_2026"]["n"], "nav_2526": w["Y2025_2026"]["nav"], "ex5_2526": w["Y2025_2026"]["ex_top5_nav"],
                    "mdd_2526_pct": w["Y2025_2026"]["daily_mdd_pct"], "sharpe_2526": w["Y2025_2026"]["daily_sharpe"], "calmar_2526": w["Y2025_2026"]["daily_calmar"],
                    "excess_csi_2526_pp": w["Y2025_2026"]["excess_csi300_pp"],
                    "n_2026": w["Y2026"]["n"], "nav_2026": w["Y2026"]["nav"], "ex5_2026": w["Y2026"]["ex_top5_nav"],
                    "mdd_2026_pct": w["Y2026"]["daily_mdd_pct"], "sharpe_2026": w["Y2026"]["daily_sharpe"], "calmar_2026": w["Y2026"]["daily_calmar"],
                    "excess_csi_2026_pp": w["Y2026"]["excess_csi300_pp"],
                })

            th_details[tname] = {
                "metrics_windows": tres["metrics"]["windows"],
                "permutation_1000": tres["metrics"]["permutation_1000"],
                "empty_days_pass_strat_dist": pass_empty["strategy"].value_counts().to_dict(),
                "empty_days_pass_by_strat": {
                    st: _grp_stats(g["net_ret"].to_numpy(float)) for st, g in pass_empty.groupby("strategy")
                },
                "v20_empty_patch_combined": {k: v for k, v in vp["mode1_strict_combined_no_peek"].items() if k != "skipped_v20_trades"} if vp else None,
                "v20_empty_patch_standalone": vp["mode2_empty_slot_standalone"] if vp else None,
                "exact_bar_mtm_v20_combined_eval": exact_comb_ev,
            }

        wf_results[pname] = {
            "wf_actual_start": res["meta"]["wf_actual_start"],
            "n_daily_rebuilds": res["meta"]["n_rebuilds"],
            "summary_table": res["summary_table"].to_dict("records"),
            "threshold_details": th_details,
            "latest_scorecard_top_factors": [
                {"name": f["name"], "t": f["t_cluster"], "shape": f["shape"], "budget_pts": f["budget_pts"], "bin_pts": f["bin_pts"], "bin_wr_pct": f["bin_wr_pct"], "bin_mean_pct": f["bin_mean_pct"]}
                for f in (res["meta"]["latest_scorecard"]["factors"] if res["meta"]["latest_scorecard"] else [])
            ],
        }

    # Physical truncation 2024-12-31 test on NM_NearLine_All
    trunc_nm = wfe.verify_truncation_zero_leakage(
        nm_pools["NM_NearLine_All"], feat_cols, mode="A", cutoff="2024-12-31", score_threshold="top20",
        v20_ctx=ctx["v20_ctx"], wf_start_date="2023-01-03",
        min_warmup_trades=60, min_warmup_trades_rare=40, min_warmup_months=14,
        recalc_freq="daily", top_k=10, min_k=4, max_corr=0.65, fee_rt=0.0020, mtm_col=None,
    )

    return {
        "n_pure_pit_features": len(feat_cols),
        "raw_nearmiss_breakdown": raw_breakdown,
        "wf_scorecard_nearmiss": wf_results,
        "truncation_20241231_proof": trunc_nm,
        "csv_rows_m4": csv_rows_m4,
    }


def main():
    t0 = time.time()
    ctx = w2c.load_w2a6_context()
    part4a = audit_rank1_skips_and_rank2(ctx)
    part4b = run_nearmiss_wf_audit(ctx)

    rss_mb = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 2)
    out = w2c.sanitize_json({
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t0, 2),
        "peak_rss_mb": rss_mb,
        "d12_yfinance_imported": "yfinance" in sys.modules,
        "baseline_parity": ctx["parity_info"],
        "part4a_rank1_skips_and_rank2": part4a,
        "part4b_nearmiss_pool_wf_audit": part4b,
    })
    out_path = f"{OUT_DIR}/w2a6_nearmiss_pool_audit.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, allow_nan=False)

    print(f"[PART 2 DONE in {time.time()-t0:.2f}s | RSS={rss_mb}MB] -> {out_path}")
    print("  Trunc 2024-12-31:", part4b["truncation_20241231_proof"])
    for pname in ("NM_Tight_3to5pt", "NM_NearLine_All", "NM_Excl_Pry_Tight", "NM_20cm_A76_81"):
        print(f"\n--- {pname} WF Scorecard Summary ---")
        print(pd.DataFrame(part4b["wf_scorecard_nearmiss"][pname]["summary_table"])[["threshold", "n_pass", "n_trades", "wr_pct", "plr", "mean_pct", "nav_wf", "mdd_pct", "sharpe", "nav_2526", "nav_y26", "perm_sd_p"]].to_string(index=False))


if __name__ == "__main__":
    main()

#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Part D2 Pillars 6 & 7: Hygiene, 5-Fold Purged CV, 6x6 Correlations, Dual-Basis LOO & CUSUM/SPRT Redlines."""
import json, math, os, sys
import numpy as np, pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
VAL5_DIR = f"{SIM}/output/five_strategies_institutional_validation_20261124"
PARTB_DIR = f"{SIM}/output/six_strategies_v20_upgrade_20261124/partB_20cm_full_jianyan"
PARTC_V20 = f"{SIM}/output/six_strategies_v20_upgrade_20261124/partC_fine_tier_priority"
PARTC_DIR = f"{SIM}/backtests_astock/redteam_full_audit_20261123/partC_clean_ledgers_v191"
PARTA_DIR = f"{SIM}/output/six_strategies_v20_upgrade_20261124/partA_10cm_upgrades"
V11_DIR = f"{SIM}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v11_unified_redteam_attack"
for p in (VAL5_DIR, PARTB_DIR, PARTC_V20):
    if p not in sys.path: sys.path.insert(0, p)

import run_part3_hygiene_portfolio_cusum as p3
import run_partB_20cm_7pillars as pb
import tier_priority_engine as tpe

S2C_MAP = {"3to4_S(>=102)": 1, "3to4_A(90-101)": 1, "high_S(>=96)": 2, "high_A(88-95)": 2,
           "pry_S(>=175)": 3, "pry_A(165-174)": 3, "2to3_S(>=96)": 4, "2to3_A(90-95)": 4,
           "1to2_S(>=340)": 5, "1to2_A(304.8-339.9)": 5, "1to2_FB(295-304.7)": 5, "20cm_S(>=82)": 6, "20cm_A(76-81)": 999}

def run_pillar6_v20(comb_df: pd.DataFrame, daily_comb: np.ndarray, cal_dates: list[str], bar_lu: dict) -> dict:
    ex_list, max_err, bad = [], 0.0, 0
    for r in comb_df.itertuples(index=False):
        bb, eb = bar_lu[(r.code, r.buy_date)], bar_lu[(r.code, r.exit_date)]
        qr = bb[3] / eb[3] if eb[3] > 0 else 1.0
        exp_r = (float(r.exit_price) / float(r.buy_price)) * qr * (1.0 - float(r.fee_rt)) - 1.0
        err = abs(exp_r - float(r.net_ret)); max_err = max(max_err, err)
        if err > 0.005: bad += 1
        if abs(qr - 1.0) > 1e-4:
            ex_list.append({"code": r.code, "name": r.name, "strategy": r.strategy, "buy_date": r.buy_date,
                            "exit_date": r.exit_date, "qfq_ratio": round(qr, 5), "net_ret_pct": round(float(r.net_ret) * 100.0, 2)})
    dt_idx = {d: i for i, d in enumerate(cal_dates)}
    cv_ledger = p3.audit_pillar6_3_purged_cv({"3to4": comb_df, "high": comb_df, "pry_ss165": comb_df, "2to3": comb_df, "1to2": comb_df, "comb_v191": comb_df},
                                            {"3to4": daily_comb, "high": daily_comb, "pry_ss165": daily_comb, "2to3": daily_comb, "1to2": daily_comb, "comb_v191": daily_comb},
                                            cal_dates, dt_idx)["comb_v191"]
    pc_json = json.load(open(f"{PARTC_V20}/partC_v20_final_tier_priority.json", encoding="utf-8"))
    refit_cv = pc_json["primary_exact_6csv"]["overfitting_audits"]["purged_5fold_refit_cv"]["P3_S2C_STierReserve"]
    return {
        "raw_vs_qfq_combined_278": {"n_trades": int(len(comb_df)), "ex_div_trades_count": len(ex_list),
                                    "ex_div_mismatch_gt50bps": bad, "max_ret_diff_bps": round(max_err * 10000.0, 2), "ex_div_trades": ex_list},
        "reporting_lag_audit": p3.audit_pillar6_2_reporting_lag(),
        "purged_embargoed_5fold_cv_ledger": cv_ledger,
        "purged_embargoed_5fold_cv_refit_from_partC": refit_cv,
    }

def run_pillar7_v20(comb_df: pd.DataFrame, daily_comb: np.ndarray, pool6: pd.DataFrame, untrig_df: pd.DataFrame,
                    by_c_all: dict, cal_dates: list[str], bar_lu: dict, sh300: dict, csi_5y_pct: float) -> dict:
    dt_idx = {d: i for i, d in enumerate(cal_dates)}
    # Load 6 standalone clean ledgers for 6x6 correlation, 6-arm EW LOO & CUSUM
    l34 = p3.norm_ledger(pd.read_csv(f"{PARTC_DIR}/ledger_3to4_v41_clean.csv", dtype={"code": str}))
    lhd = p3.norm_ledger(pd.read_csv(f"{PARTC_DIR}/ledger_high_v51_clean.csv", dtype={"code": str}))
    lpr = p3.norm_ledger(pd.read_csv(f"{PARTC_DIR}/ledger_pry_v21_ss165_clean.csv", dtype={"code": str}))
    l23 = p3.norm_ledger(pd.read_csv(f"{PARTC_DIR}/ledger_2to3_v21_opt_std90_clean.csv", dtype={"code": str}))
    l12 = p3.norm_ledger(pd.read_csv(f"{PARTA_DIR}/ledger_1to2_v20_cand.csv", dtype={"code": str}))
    l20_full = pd.read_csv(f"{V11_DIR}/final_v11_ledger_S82.csv", dtype={"c6": str})
    l20_full["c6"] = l20_full["c6"].str.zfill(6)
    l20_5y = l20_full[l20_full["buy_date"].between("2021-11-16", "2026-11-16") & (l20_full["exit_date"] <= "2026-11-16")].copy()

    daily6 = {}
    for k, ld in [("3to4_V41", l34), ("high_V51", lhd), ("pry_V21", lpr), ("2to3_V21", l23), ("1to2_V20", l12)]:
        dr, chk = p3.build_daily_mtm_series(ld, cal_dates, dt_idx, bar_lu); assert chk["nav_abs_diff"] < 1e-4
        daily6[k] = dr
    dr20, _, _, _ = pb.compute_daily_mtm(l20_5y, by_c_all, cal_dates, prices_are_adj=True)
    daily6["20cm_V11_S82"] = dr20

    # 6x6 Correlation & CSI300 Worst 10% Downside Tail
    keys = ["3to4_V41", "high_V51", "pry_V21", "2to3_V21", "1to2_V20", "20cm_V11_S82"]
    df_r = pd.DataFrame({k: daily6[k] for k in keys}, index=cal_dates)
    all_sh = sorted(sh300.keys()); i0 = all_sh.index(cal_dates[0])
    csi_vals = np.array([float(sh300[d]) for d in cal_dates], float)
    csi_ret = csi_vals / np.concatenate([[float(sh300[all_sh[i0 - 1]])], csi_vals[:-1]]) - 1.0
    q10 = float(np.quantile(csi_ret, 0.10)); w10_m = csi_ret <= q10; act_m = (df_r.abs() > 1e-12).any(axis=1); los_m = (df_r < 0).any(axis=1)
    def _cpack(sub):
        pm, sm = sub.corr("pearson").fillna(0.0).round(4), sub.corr("spearman").fillna(0.0).round(4)
        v = pm.to_numpy(); off = [v[i, j] for i in range(6) for j in range(i + 1, 6)]
        return {"n_days": int(len(sub)), "pearson": {k: {k2: float(pm.loc[k, k2]) for k2 in keys} for k in keys},
                "spearman": {k: {k2: float(sm.loc[k, k2]) for k2 in keys} for k in keys},
                "mean_pairwise_pearson": round(float(np.mean(off)), 4), "max_pairwise_pearson": round(float(np.max(off)), 4)}
    w10_exp = {k: {"active_days": int((df_r.loc[w10_m, k].abs() > 1e-12).sum()),
                   "all_worst10_mean_bps": round(float(df_r.loc[w10_m, k].mean() * 10000.0), 2),
                   "active_mean_pct": round(float(df_r.loc[w10_m, k][df_r.loc[w10_m, k].abs() > 1e-12].mean() * 100.0), 2) if (df_r.loc[w10_m, k].abs() > 1e-12).any() else 0.0} for k in keys}
    loss_cnt = (df_r < -1e-6).sum(axis=1)
    corr_block = {"full_5y_calendar": _cpack(df_r), "any_active_days_only": _cpack(df_r[act_m]),
                  "downside_csi300_worst10pct": {"csi_q10_threshold_pct": round(q10 * 100.0, 2), **_cpack(df_r[w10_m]), "strategy_exposure_in_crash": w10_exp},
                  "downside_any_strategy_loss_days": _cpack(df_r[los_m]),
                  "simultaneous_blowup_check": {"days_ge2_simultaneous_loss": int((loss_cnt >= 2).sum()), "days_ge3_simultaneous_loss": int((loss_cnt >= 3).sum()), "max_simultaneous_losing": int(loss_cnt.max())}}

    # Dual-Basis LOO: Basis A (Single-slot P3_S2C_STierReserveOnly) + Basis B (6-arm Equal Weight Daily MTM)
    base_1s = p3.metrics_from_daily_and_trades(daily_comb, comb_df["net_ret"].to_numpy(float), csi_5y_pct)
    base_1s["by_strategy"] = comb_df["strategy"].value_counts().to_dict()
    loo_1s = {}
    for drop_k in ("3to4", "high", "pry", "2to3", "1to2", "20cm"):
        p_sub = pool6[pool6["strategy"] != drop_k].copy(); u_sub = untrig_df[untrig_df["strategy"] != drop_k].copy()
        tr_l, _ = tpe.run_single_slot(p_sub, lambda d: d["tier"].map(S2C_MAP).fillna(999).to_numpy(), untrig_df=u_sub, timing_mode="s_tier_reserve_only")
        dr_l, nd = tpe.build_daily_mtm_series(tr_l, cal_dates, dt_idx, bar_lu); assert nd < 1e-3
        m = p3.metrics_from_daily_and_trades(dr_l, tr_l["net_ret"].to_numpy(float), csi_5y_pct)
        m["by_strategy"] = tr_l["strategy"].value_counts().to_dict()
        m["marginal_delta_sharpe"] = round(base_1s["daily_sharpe"] - m["daily_sharpe"], 4)
        m["marginal_delta_calmar"] = round(base_1s["calmar"] - m["calmar"], 4)
        m["marginal_delta_mdd_pp"] = round(base_1s["daily_mdd_pct"] - m["daily_mdd_pct"], 2)
        m["nav_multiplier_contrib"] = round(base_1s["total_nav"] / max(m["total_nav"], 1e-9), 4)
        loo_1s[f"drop_{drop_k}"] = m

    r_mat = np.column_stack([daily6[k] for k in keys]); ew_base = p3.metrics_from_daily_and_trades(r_mat.mean(axis=1), np.array([]), csi_5y_pct)
    for c in ("trades","wr_pct","plr","trade_mean_pct","trade_sharpe","trade_mdd_pct"): ew_base.pop(c, None)
    loo_ew = {}
    for idx_d, dk in enumerate(keys):
        rem = [i for i in range(6) if i != idx_d]
        m = p3.metrics_from_daily_and_trades(r_mat[:, rem].mean(axis=1), np.array([]), csi_5y_pct)
        for c in ("trades","wr_pct","plr","trade_mean_pct","trade_sharpe","trade_mdd_pct"): m.pop(c, None)
        m["marginal_delta_sharpe"] = round(ew_base["daily_sharpe"] - m["daily_sharpe"], 4)
        m["marginal_delta_calmar"] = round(ew_base["calmar"] - m["calmar"], 4)
        m["marginal_delta_mdd_pp"] = round(ew_base["daily_mdd_pct"] - m["daily_mdd_pct"], 2)
        m["nav_multiplier_contrib"] = round(ew_base["total_nav"] / max(m["total_nav"], 1e-9), 4)
        loo_ew[f"drop_{dk}"] = m

    # CUSUM/SPRT Redlines (5,000x MC) for combined_v20, 1to2_V20, 20cm_S82 + reuse 4 unchanged 10cm from part3
    rng = np.random.default_rng(20261124)
    p3_json = json.load(open(f"{VAL5_DIR}/part3_hygiene_portfolio_cusum.json", encoding="utf-8"))
    cusum = {
        "combined_6strat_v20": pb.calc_cusum_sprt_one(comb_df["net_ret"].to_numpy(float), rng),
        "1to2_V20": pb.calc_cusum_sprt_one(l12["net_ret"].to_numpy(float), rng),
        "20cm_V11_S82_full199": pb.calc_cusum_sprt_one(l20_full["net_ret_eval"].to_numpy(float), rng),
        "20cm_V11_S82_5y160": pb.calc_cusum_sprt_one(l20_5y["net_ret_eval"].to_numpy(float), rng),
        "3to4_V41_from_RD024": p3_json["pillar7_portfolio_cusum"]["cusum_sprt_redlines"]["3to4"],
        "high_V51_from_RD024": p3_json["pillar7_portfolio_cusum"]["cusum_sprt_redlines"]["high"],
        "pry_V21_from_RD024": p3_json["pillar7_portfolio_cusum"]["cusum_sprt_redlines"]["pry_ss165"],
        "2to3_V21_from_RD024": p3_json["pillar7_portfolio_cusum"]["cusum_sprt_redlines"]["2to3"],
    }
    return {"daily_mtm_correlation_and_tail": corr_block,
            "loo_marginal_contribution": {"single_slot_v20_p3_s2c_stier_reserve": {"baseline": base_1s, "leave_one_out": loo_1s},
                                          "equal_weight_6sleeves_daily": {"baseline": ew_base, "leave_one_out": loo_ew}},
            "cusum_sprt_redlines": cusum}

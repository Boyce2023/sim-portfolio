#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Part D2 Pillars 4 & 5: Z-Score IC, Breakeven BPS (pure compounding only), Holding Decay, PSR/MinTRL, WRC/SPA, BCa, Runs & Kelly."""
import itertools, math, sys
import numpy as np, pandas as pd, scipy.stats as stats

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
VAL5_DIR = f"{SIM}/output/five_strategies_institutional_validation_20261124"
PARTC_V20 = f"{SIM}/output/six_strategies_v20_upgrade_20261124/partC_fine_tier_priority"
PARTA_DIR = f"{SIM}/output/six_strategies_v20_upgrade_20261124/partA_10cm_upgrades"
PARTC_DIR = f"{SIM}/backtests_astock/redteam_full_audit_20261123/partC_clean_ledgers_v191"
MW_DIR = f"{SIM}/backtests_astock/mkt_water_scoring_audit_20261123"
V11_DIR = f"{SIM}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v11_unified_redteam_attack"
for p in (VAL5_DIR, PARTC_V20):
    if p not in sys.path: sys.path.insert(0, p)

import run_part2_signal_stats as p2
import tier_priority_engine as tpe

SEED = 20261124

def sf(x, digits=6):
    if x is None: return None
    v = float(x)
    return None if (math.isnan(v) or math.isinf(v)) else round(v, digits)

def calc_breakeven_v20(net_rets: np.ndarray, fee_rt_vec: np.ndarray, csi_5y_ret: float) -> dict:
    """Restore per-trade exact gross return (20bps 10cm, 30bps 20cm) and solve breakeven OW bps (pure compounding only)."""
    n = len(net_rets)
    gross_mult = (1.0 + net_rets) / (1.0 - fee_rt_vec)
    gross_rets = gross_mult - 1.0
    arith_g = float(np.mean(gross_rets))
    geom_g = math.exp(float(np.mean(np.log(np.maximum(1e-9, gross_mult)))))
    c_arith = 0.5 * (1.0 - 1.0 / (1.0 + arith_g))
    c_geom = 0.5 * (1.0 - 1.0 / geom_g)
    tgt = (1.0 + csi_5y_ret) ** (1.0 / n) if n > 0 else 1.0
    c_csi = 0.5 * (1.0 - tgt / geom_g)
    avg_rt_bps = float(np.mean(fee_rt_vec) * 10000.0)
    avg_ow_bps = avg_rt_bps / 2.0
    grid = []
    for ow in (10, 15, 25, 50, 100, 150, 200, 300):
        rt = 2.0 * ow / 10000.0
        rc = gross_mult * (1.0 - rt) - 1.0
        grid.append({"one_way_bps": ow, "round_trip_bps": 2 * ow, "arith_mean_pct": sf(rc.mean() * 100.0, 3), "nav_5y": sf(np.prod(1.0 + rc), 4)})
    return {
        "weighted_orig_deducted_rt_bps": sf(avg_rt_bps, 2),
        "weighted_orig_deducted_ow_bps": sf(avg_ow_bps, 2),
        "gross_arith_mean_pct": sf(arith_g * 100.0, 3),
        "gross_geom_mean_pct": sf((geom_g - 1.0) * 100.0, 3),
        "breakeven_ow_arith_bps": sf(c_arith * 10000.0, 1),
        "breakeven_ow_geom_5y_bps": sf(c_geom * 10000.0, 1),
        "breakeven_ow_beat_csi300_bps": sf(c_csi * 10000.0, 1),
        "safety_margin_vs_weighted_orig_ow": sf((c_geom * 10000.0) / avg_ow_bps, 2),
        "cost_sensitivity_grid": grid,
    }

def calc_holding_decay_v20(comb_df: pd.DataFrame, by_c_all: dict, sh300: dict, all_sh_dts: list[str]) -> dict:
    horizons = (0, 1, 2, 3, 5)
    phys_rets, csi_rets, def_cnt = {h: [] for h in horizons}, {h: [] for h in horizons}, {h: 0 for h in horizons}
    for r in comb_df.itertuples(index=False):
        bar = by_c_all[r.code]; p0 = bar["dt_to_pos"][r.buy_date]; bpx_adj = float(r.buy_px_adj)
        for h in horizons:
            ph = min(p0 + h, len(bar["dt"]) - 1); dt_h = bar["dt"][ph]
            if h > 0 and (bar["is_dt"][ph] or bar["is_yizi_dt"][ph]):
                def_cnt[h] += 1; k = ph + 1
                while k < len(bar["dt"]) - 1 and (bar["is_yizi_dt"][k] or bar["volume"][k] <= 0): k += 1
                dt_exec = bar["dt"][k]
                px_adj = float(bar["open"][k]) * float(bar["adjf"][k]) if bar["volume"][k] > 0 else float(bar["adj_close"][k])
            else:
                dt_exec = dt_h; px_adj = float(bar["adj_close"][ph])
            phys_rets[h].append(px_adj / bpx_adj - 1.0)
            csi_rets[h].append(p2.get_csi_period_ret(sh300, all_sh_dts, r.buy_date, dt_exec))
    summary_h, pg, pex = {}, None, None
    fee_vec = comb_df["fee_rt"].to_numpy(float)
    for h in horizons:
        pr, cr = np.array(phys_rets[h]), np.array(csi_rets[h]); ex = pr - cr
        net_v = (1.0 + pr) * (1.0 - fee_vec) - 1.0; gm, exm = float(pr.mean()), float(ex.mean())
        summary_h[f"T+{h}"] = {
            "n": len(pr), "phys_gross_mean_pct": sf(gm * 100.0, 3), "phys_gross_median_pct": sf(np.median(pr) * 100.0, 3),
            "phys_net_mean_pct": sf(net_v.mean() * 100.0, 3), "phys_win_rate_pct": sf((pr > 0).mean() * 100.0, 2),
            "csi300_mean_pct": sf(cr.mean() * 100.0, 3), "phys_excess_mean_pct": sf(exm * 100.0, 3),
            "marginal_gross_inc_pp": sf((gm - pg if pg is not None else gm) * 100.0, 3),
            "marginal_excess_inc_pp": sf((exm - pex if pex is not None else exm) * 100.0, 3),
            "dt_sealed_deferred_count": def_cnt[h],
        }
        pg, pex = gm, exm
    hs = np.array([1.0, 2.0, 3.0, 5.0])
    ex_c = np.array([summary_h[f"T+{int(h)}"]["phys_excess_mean_pct"] for h in hs], float)
    inc = np.array([ex_c[0], ex_c[1] - ex_c[0], ex_c[2] - ex_c[1], (ex_c[3] - ex_c[2]) / 2.0])
    pm = inc > 0; hl_m = None
    if pm.sum() >= 2 and inc[0] > 0:
        sl = stats.linregress(np.array([0.5, 1.5, 2.5, 4.0])[pm], np.log(inc[pm])).slope
        if sl < -1e-4: hl_m = math.log(2.0) / (-sl)
    pk_i = int(np.argmax(ex_c)); pk_h, pk_ex = int(hs[pk_i]), float(ex_c[pk_i])
    return {"horizons": summary_h, "alpha_decay_analysis": {"peak_horizon_excess": f"T+{pk_h}", "peak_excess_pct": sf(pk_ex, 3),
            "pct_of_peak_excess_at_T1": sf(ex_c[0] / pk_ex * 100.0, 1) if pk_ex > 0 else None,
            "daily_marginal_excess_pp_from_buy": {"buy_to_T1": sf(inc[0], 3), "T1_to_T2": sf(inc[1], 3), "T2_to_T3": sf(inc[2], 3), "T3_to_T5_per_day": sf(inc[3], 3)},
            "half_life_marginal_days": sf(hl_m, 2)}}

def run_pillar4_v20(comb_df: pd.DataFrame, by_c_all: dict, sh300: dict, all_sh_dts: list[str], csi_5y_ret: float) -> dict:
    d = comb_df.copy()
    d["score_z_within_strat"] = d.groupby("strategy")["score"].transform(lambda s: (s - s.mean()) / max(1e-9, s.std(ddof=1)))
    d["score_pct_within_strat"] = d.groupby("strategy")["score"].rank(pct=True)
    rets = d["net_ret"].to_numpy(float)

    # 6-pool merged reference
    p6_frames = []
    for pth, sk, sc_c in [
        (f"{MW_DIR}/part1_3to4_high/pool_3to4_full_clean.csv", "3to4", "base_score"),
        (f"{MW_DIR}/part1_3to4_high/pool_high_full_clean.csv", "high", "base_score"),
        (f"{MW_DIR}/part2_2to3_pry/pool_pry_full_clean.csv", "pry", "base_score"),
        (f"{MW_DIR}/part2_2to3_pry/pool_2to3_full_clean.csv", "2to3", "base_score"),
        (f"{MW_DIR}/part3_1to2/pool_1to2_full_clean.csv", "1to2", "base_score"),
        (f"{V11_DIR}/final_v11_all_scored_signals.csv", "20cm", "score"),
    ]:
        ps = pd.read_csv(pth); ps["buy_date"] = ps["buy_date"].astype(str).str[:10]
        ps = ps[ps["buy_date"].between("2021-11-16", "2026-11-16")].copy()
        mu, sd = ps[sc_c].mean(), ps[sc_c].std(ddof=1)
        ps["score_z_within_pool"] = (ps[sc_c] - mu) / sd
        p6_frames.append(ps[["buy_date", "net_ret", "score_z_within_pool"]])
    m6 = pd.concat(p6_frames, ignore_index=True)
    m6["code"] = "000001"

    return {
        "within_ledger_analysis": {
            "within_strat_zscore": {"ic_and_decay": p2.calc_ic_block(d, "score_z_within_strat", "net_ret", 4, 10),
                                    "monotonicity_q5": p2.calc_quantile_bins(d["score_z_within_strat"].to_numpy(float), rets, 5, "value_qcut"),
                                    "classification_calibration": p2.calc_classification_calibration(d, "score_z_within_strat")},
            "within_strat_pct_rank": {"ic_and_decay": p2.calc_ic_block(d, "score_pct_within_strat", "net_ret", 4, 10),
                                      "monotonicity_q5": p2.calc_quantile_bins(d["score_pct_within_strat"].to_numpy(float), rets, 5, "value_qcut")},
            "raw_mixed_score_confounded_ctrl": {"ic_and_decay": p2.calc_ic_block(d, "score", "net_ret", 4, 10)},
        },
        "merged_6pool_within_strat_zscore_ref": {"pool_n": int(len(m6)), "ic_and_decay": p2.calc_ic_block(m6, "score_z_within_pool", "net_ret", 4, 10),
                                                 "monotonicity_q5": p2.calc_quantile_bins(m6["score_z_within_pool"].to_numpy(float), m6["net_ret"].to_numpy(float), 5, "value_qcut")},
        "breakeven_transaction_cost": calc_breakeven_v20(rets, d["fee_rt"].to_numpy(float), csi_5y_ret),
        "holding_period_decay": calc_holding_decay_v20(d, by_c_all, sh300, all_sh_dts),
    }

def run_pillar5_v20(comb_df: pd.DataFrame, daily_s: np.ndarray, csi_daily: np.ndarray, sh300: dict, all_sh_dts: list[str],
                    pool6: pd.DataFrame, untrig_df: pd.DataFrame, cal_dates: list[str], bar_lu: dict) -> dict:
    rng = np.random.default_rng(SEED)
    rets = comb_df["net_ret"].to_numpy(float); n_tr = len(rets); tr_per_yr = n_tr / 5.0
    d_ex = daily_s - csi_daily; dt_idx = {d: i for i, d in enumerate(cal_dates)}
    tr_csi = np.array([p2.get_csi_period_ret(sh300, all_sh_dts, r.buy_date, r.exit_date) for r in comb_df.itertuples(index=False)], float)
    psr = {
        "daily_mtm_basis": {"vs_zero": p2.calc_psr_mintrl(daily_s, 252.0, 1.0), "vs_csi300": p2.calc_psr_mintrl(d_ex, 252.0, 1.0)},
        "trade_level_basis": {"trades_per_year_5y": sf(tr_per_yr, 2), "vs_zero": p2.calc_psr_mintrl(rets, tr_per_yr, 1.0), "vs_csi300_holding": p2.calc_psr_mintrl(rets - tr_csi, tr_per_yr, 1.0)},
    }

    # Build authentic M>=120 candidate rule family around P3_S2C_STierReserveOnly (col 0)
    cols_list = [daily_s]
    s_names = ["3to4", "high", "pry", "2to3", "1to2"]
    for perm in itertools.permutations(s_names):
        pmap = {s: i + 1 for i, s in enumerate(perm)}; pmap["20cm"] = 6
        tmap = {t: pmap[t.split("_")[0]] for t in pool6["tier"].unique()}; tmap["20cm_A(76-81)"] = 999
        tr_p, _ = tpe.run_single_slot(pool6, lambda d, _tm=tmap: d["tier"].map(_tm).fillna(999).to_numpy(), untrig_df=untrig_df, timing_mode="s_tier_reserve_only")
        dr_p, _ = tpe.build_daily_mtm_series(tr_p, cal_dates, dt_idx, bar_lu)
        cols_list.append(dr_p)
    for drop_s in ["3to4", "high", "pry", "2to3", "1to2", "20cm"]:
        pm = {k: v for k, v in {"3to4":1,"high":2,"pry":3,"2to3":4,"1to2":5,"20cm":6}.items() if k != drop_s}
        tmap = {t: pm.get(t.split("_")[0], 999) for t in pool6["tier"].unique()}; tmap["20cm_A(76-81)"] = 999
        tr_p, _ = tpe.run_single_slot(pool6, lambda d, _tm=tmap: d["tier"].map(_tm).fillna(999).to_numpy(), untrig_df=untrig_df, timing_mode="s_tier_reserve_only")
        dr_p, _ = tpe.build_daily_mtm_series(tr_p, cal_dates, dt_idx, bar_lu); cols_list.append(dr_p)
    for tmode in ("naive", "reserve_all", "confirmed_0925_first"):
        s2c = {"3to4_S(>=102)":1,"3to4_A(90-101)":1,"high_S(>=96)":2,"high_A(88-95)":2,"pry_S(>=175)":3,"pry_A(165-174)":3,"2to3_S(>=96)":4,"2to3_A(90-95)":4,"1to2_S(>=340)":5,"1to2_A(304.8-339.9)":5,"1to2_FB(295-304.7)":5,"20cm_S(>=82)":6,"20cm_A(76-81)":999}
        tr_p, _ = tpe.run_single_slot(pool6, lambda d, _tm=s2c: d["tier"].map(_tm).fillna(999).to_numpy(), untrig_df=untrig_df, timing_mode=tmode)
        dr_p, _ = tpe.build_daily_mtm_series(tr_p, cal_dates, dt_idx, bar_lu); cols_list.append(dr_p)

    mat_full = np.column_stack(cols_list); seen, uniq = {}, []
    for j in range(mat_full.shape[1]):
        h = hash(mat_full[:, j].round(10).tobytes())
        if h not in seen: seen[h] = j; uniq.append(j)
    mat_uniq = mat_full[:, uniq]
    W_dict = {L: p2.stationary_bootstrap_weights(len(cal_dates), 5000, float(L), rng) for L in (10, 5, 20)}
    wrc_spa = {"family_meta": {"M_total": int(mat_full.shape[1]), "M_unique": int(mat_uniq.shape[1]), "politis_white_opt_L": sf(p2.politis_white_opt_block_len(daily_s), 2)},
               "vs_cash0": p2.run_wrc_and_spa(mat_uniq, W_dict, 10), "vs_csi300": p2.run_wrc_and_spa(mat_uniq - csi_daily[:, None], W_dict, 10)}

    bca_m = p2.bca_bootstrap_ci(rets * 100.0, B=5000, alpha=0.05, rng=rng)
    bca_w = p2.bca_bootstrap_ci((rets > 0).astype(float) * 100.0, B=5000, alpha=0.05, rng=rng)
    wl, wh = p2.wilson_ci_95(int((rets > 0).sum()), n_tr); bca_w["wilson_95_ci_pct"] = [sf(wl * 100.0, 2), sf(wh * 100.0, 2)]
    return {"psr_and_mintrl": psr, "multiple_testing_wrc_spa": wrc_spa,
            "bca_bootstrap_95ci": {"mean_net_ret_pct": {**bca_m, "excludes_zero": bool(bca_m["ci_95_low"] > 0)}, "win_rate_pct": bca_w},
            **p2.calc_runs_autocorr_kelly(rets, rng=rng)}

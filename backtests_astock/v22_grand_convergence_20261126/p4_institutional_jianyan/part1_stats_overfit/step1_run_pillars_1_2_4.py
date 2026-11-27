#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
step1_run_pillars_1_2_4.py — V22.0 Institutional Audit Part 1 (Pillars 1, 2, and 4):
  - Pillar 1: Deflated Sharpe Ratio (DSR) & MinTRL under N = 100 / 300 / 600 (Absolute & Incremental vs V21)
  - Pillar 2: CSCV PBO (S=10 exact 252 splits & S=16 2,000 non-dup + 12,870 full splits) across 25 real variants
  - Pillar 4: Leave-One-Year-Out (2021..2026) + 10,000x Moving Block Bootstrap (block=5 & block=10)
Compares B0_V20, B1_V21, V21_M5_B_NoXQ_Pos5 (Champion), and Pure_V21_P2_SJ114_E4_Pos5 (Pure).
Zero yfinance (D12). Read-only on V20/V21/RD038/RD048/RD049/P1A/P2/P3.
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import itertools
import json
import math
import pickle
import sys
import time
import warnings

import numpy as np
import pandas as pd
import scipy.stats as stats

warnings.filterwarnings("ignore")
assert "yfinance" not in sys.modules, "D12 VIOLATION"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
RD038 = f"{SIM}/backtests_astock2/rd038_grand_bundle_assembly_20261126"
RD049 = f"{SIM}/backtests_astock2/rd049_traffic_light_granular_20261126"
P2 = f"{SIM}/backtests_astock/v22_grand_convergence_20261126/p2_rd049_falsekill_audit"
P3 = f"{SIM}/backtests_astock/v22_grand_convergence_20261126/p3_v22_grand_assembly"
OUT_DIR = f"{SIM}/backtests_astock/v22_grand_convergence_20261126/p4_institutional_jianyan/part1_stats_overfit"
CACHE_DIR = f"{OUT_DIR}/_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

for p in (RD038, RD049, P2, P3):
    if p not in sys.path:
        sys.path.insert(0, p)

import _v22_engine as v22
import step2_targeted_rescue_and_truncation as p2s

TRD_DAYS_YEAR = 242.0
EULER_GAMMA = 0.5772156649015329
CHAMP_ID = "V21_M5_B_NoXQ_Pos5"
PURE_ID = "Pure_V21_P2_SJ114_E4_Pos5"


def calc_moments(dr: np.ndarray) -> dict:
    x = np.asarray(dr, dtype=float)
    T = len(x)
    mu = float(np.mean(x))
    sd = float(np.std(x, ddof=1))
    sr_d = mu / sd if sd > 1e-12 else 0.0
    sr_ann = sr_d * math.sqrt(TRD_DAYS_YEAR)
    skew = float(stats.skew(x, bias=True))
    kurt_tot = float(stats.kurtosis(x, fisher=False, bias=True))
    ex_kurt = kurt_tot - 3.0
    nav = float(np.prod(1.0 + x))
    mdd, dd2 = v22.calc_top2_dd(x)
    cagr = (nav ** (TRD_DAYS_YEAR / T) - 1.0) * 100.0 if nav > 0 else -100.0
    calmar = (cagr / mdd) if mdd > 1e-6 else 0.0
    return {
        "T": int(T),
        "mean_daily_bps": round(mu * 10000.0, 3),
        "std_daily_pct": round(sd * 100.0, 4),
        "sr_daily": round(sr_d, 6),
        "sr_ann": round(sr_ann, 4),
        "skew": round(skew, 4),
        "kurtosis_total": round(kurt_tot, 4),
        "excess_kurtosis": round(ex_kurt, 4),
        "nav": round(nav, 4),
        "cagr_pct": round(cagr, 2),
        "mdd_pct": mdd,
        "dd2_pct": dd2,
        "calmar": round(calmar, 2),
    }


def calc_dsr_and_mintrl(dr: np.ndarray, n_trials: int, var_sr_daily: float, sr_bench_daily: float = 0.0, alpha: float = 0.05) -> dict:
    """Exact Bailey & Lopez de Prado (2014) DSR & MinTRL."""
    x = np.asarray(dr, dtype=float)
    T = len(x)
    mu = float(np.mean(x))
    sd = float(np.std(x, ddof=1))
    sr = mu / sd if sd > 1e-12 else 0.0
    g3 = float(stats.skew(x, bias=True))
    g4 = float(stats.kurtosis(x, fisher=False, bias=True))  # total kurtosis

    if n_trials <= 1 or var_sr_daily <= 0.0:
        sr0 = float(sr_bench_daily)
    else:
        z1 = float(stats.norm.ppf(1.0 - 1.0 / n_trials))
        z2 = float(stats.norm.ppf(1.0 - 1.0 / (n_trials * math.e)))
        sr0 = float(sr_bench_daily) + math.sqrt(var_sr_daily) * ((1.0 - EULER_GAMMA) * z1 + EULER_GAMMA * z2)

    nonnorm_factor = max(1e-12, 1.0 - g3 * sr + ((g4 - 1.0) / 4.0) * (sr ** 2))
    denom = math.sqrt(nonnorm_factor / max(1, T - 1))
    z_dsr = (sr - sr0) / denom
    dsr = float(stats.norm.cdf(z_dsr))

    z_req = float(stats.norm.ppf(1.0 - alpha))
    if sr > sr0 + 1e-12:
        mintrl = 1.0 + nonnorm_factor * ((z_req / (sr - sr0)) ** 2)
    else:
        mintrl = float("inf")

    return {
        "n_trials": int(n_trials),
        "var_sr_daily": round(float(var_sr_daily), 8),
        "sr_daily": round(sr, 6),
        "sr_ann": round(sr * math.sqrt(TRD_DAYS_YEAR), 4),
        "sr0_daily": round(sr0, 6),
        "sr0_ann": round(sr0 * math.sqrt(TRD_DAYS_YEAR), 4),
        "z_dsr": round(z_dsr, 4),
        "dsr": round(dsr, 6),
        "mintrl_days": round(mintrl, 2) if math.isfinite(mintrl) else None,
        "actual_T": int(T),
        "pass_dsr_095": bool(dsr >= 0.95),
        "pass_mintrl_lt_T": bool(math.isfinite(mintrl) and mintrl < T),
    }


def run_pillar1_dsr(models: dict, all_v22_sims: dict) -> dict:
    print("[Pillar 1] Computing DSR & MinTRL (N=100, 300, 600)...", flush=True)
    out = {"moments": {}, "absolute_vs_0": {}, "incremental_spread_vs_v21": {}, "champion_vs_pure_spread": {}}

    # Trial SR variances
    v21_vars = [v for k, v in all_v22_sims.items() if k.startswith("V21_") or k == "B1_V21"]
    srs_5y = [float(np.mean(v["dr_5y"]) / np.std(v["dr_5y"], ddof=1)) for v in all_v22_sims.values()]
    srs_wf = [float(np.mean(v["dr_wf"]) / np.std(v["dr_wf"], ddof=1)) for v in all_v22_sims.values()]
    var_emp_5y = float(np.var(srs_5y, ddof=1))
    var_emp_wf = float(np.var(srs_wf, ddof=1))
    var_pooled = float(v22.eng.DSR_VAR_POOLED)  # 0.001459

    v21_5y = models["B1_V21"]["dr_5y"]
    v21_wf = models["B1_V21"]["dr_wf"]
    ex_srs_5y = [
        float(np.mean(v["dr_5y"] - v21_5y) / np.std(v["dr_5y"] - v21_5y, ddof=1))
        if np.std(v["dr_5y"] - v21_5y, ddof=1) > 1e-12 else 0.0
        for v in v21_vars
    ]
    ex_srs_wf = [
        float(np.mean(v["dr_wf"] - v21_wf) / np.std(v["dr_wf"] - v21_wf, ddof=1))
        if np.std(v["dr_wf"] - v21_wf, ddof=1) > 1e-12 else 0.0
        for v in v21_vars
    ]
    var_ex_5y = float(np.var(ex_srs_5y, ddof=1))
    var_ex_wf = float(np.var(ex_srs_wf, ddof=1))

    out["variance_inputs"] = {
        "n_v22_pool_total": len(all_v22_sims),
        "var_sr_daily_v22_5y": round(var_emp_5y, 8),
        "var_sr_daily_v22_wf": round(var_emp_wf, 8),
        "var_sr_daily_pooled_rd035_036": var_pooled,
        "var_sr_daily_null_5y": round(1.0 / (len(v21_5y) - 1), 8),
        "var_sr_daily_null_wf": round(1.0 / (len(v21_wf) - 1), 8),
        "var_sr_daily_spread_v21_5y": round(var_ex_5y, 8),
        "var_sr_daily_spread_v21_wf": round(var_ex_wf, 8),
    }

    for nm, sim in models.items():
        out["moments"][nm] = {
            "FULL_5Y": calc_moments(sim["dr_5y"]),
            "WF_2326": calc_moments(sim["dr_wf"]),
        }
        out["absolute_vs_0"][nm] = {}
        for win_lbl, dr, v_emp in [
            ("FULL_5Y", sim["dr_5y"], var_emp_5y),
            ("WF_2326", sim["dr_wf"], var_emp_wf),
        ]:
            v_null = 1.0 / (len(dr) - 1)
            out["absolute_vs_0"][nm][win_lbl] = {}
            for N in (100, 300, 600):
                out["absolute_vs_0"][nm][win_lbl][f"N_{N}"] = {
                    "pooled_var": calc_dsr_and_mintrl(dr, N, var_pooled, 0.0),
                    "null_var": calc_dsr_and_mintrl(dr, N, v_null, 0.0),
                    "emp_var": calc_dsr_and_mintrl(dr, N, v_emp, 0.0),
                }

    # Incremental spread DSR vs V21 (and direct benchmark shift)
    sr_v21_5y = float(np.mean(v21_5y) / np.std(v21_5y, ddof=1))
    sr_v21_wf = float(np.mean(v21_wf) / np.std(v21_wf, ddof=1))
    for nm in (CHAMP_ID, PURE_ID):
        sim = models[nm]
        out["incremental_spread_vs_v21"][nm] = {}
        for win_lbl, dr, ref, v_ex, sr_ref, v_emp in [
            ("FULL_5Y", sim["dr_5y"], v21_5y, var_ex_5y, sr_v21_5y, var_emp_5y),
            ("WF_2326", sim["dr_wf"], v21_wf, var_ex_wf, sr_v21_wf, var_emp_wf),
        ]:
            d_ser = dr - ref
            v_null = 1.0 / (len(d_ser) - 1)
            out["incremental_spread_vs_v21"][nm][win_lbl] = {
                "spread_moments": calc_moments(d_ser),
                "by_N": {},
            }
            for N in (100, 300, 600):
                out["incremental_spread_vs_v21"][nm][win_lbl]["by_N"][f"N_{N}"] = {
                    "spread_emp_var": calc_dsr_and_mintrl(d_ser, N, v_ex, 0.0),
                    "spread_null_var": calc_dsr_and_mintrl(d_ser, N, v_null, 0.0),
                    "direct_sr_shift_emp": calc_dsr_and_mintrl(dr, N, v_emp, sr_ref),
                }

    # Champion vs Pure marginal spread
    for win_lbl, dr_ch, dr_pu in [
        ("FULL_5Y", models[CHAMP_ID]["dr_5y"], models[PURE_ID]["dr_5y"]),
        ("WF_2326", models[CHAMP_ID]["dr_wf"], models[PURE_ID]["dr_wf"]),
    ]:
        d_cp = dr_ch - dr_pu
        out["champion_vs_pure_spread"][win_lbl] = {
            "moments": calc_moments(d_cp),
            "N_1_ttest": calc_dsr_and_mintrl(d_cp, 1, 0.0, 0.0),
            "N_100_null": calc_dsr_and_mintrl(d_cp, 100, 1.0 / (len(d_cp) - 1), 0.0),
        }

    return out


def cscv_evaluate(mat_dict: dict[str, np.ndarray], S: int, max_splits: int | None = None, seed: int = 20261126) -> dict:
    """Exact CSCV PBO evaluation with optional deterministic non-duplicate combo sampling."""
    names = list(mat_dict.keys())
    M = np.column_stack([np.asarray(mat_dict[k], dtype=float) for k in names])
    T_tot, K = M.shape
    L = T_tot // S
    T_use = L * S
    M = M[T_tot - T_use :, :]
    blocks = M.reshape(S, L, K)
    blk_sum = blocks.sum(axis=1)
    blk_sum2 = (blocks ** 2).sum(axis=1)
    tot_sum = blk_sum.sum(axis=0)
    tot_sum2 = blk_sum2.sum(axis=0)

    all_combos = list(itertools.combinations(range(S), S // 2))
    total_possible = len(all_combos)
    if max_splits is not None and total_possible > max_splits:
        rng = np.random.default_rng(seed)
        pick = rng.choice(total_possible, size=max_splits, replace=False)
        combos = [all_combos[i] for i in sorted(pick)]
    else:
        combos = all_combos

    n_splits = len(combos)
    ind = np.zeros((n_splits, S), dtype=float)
    for r_i, cmb in enumerate(combos):
        ind[r_i, list(cmb)] = 1.0

    n_is = (S // 2) * L
    n_oos = T_use - n_is
    is_sum = ind @ blk_sum
    is_sum2 = ind @ blk_sum2
    is_mu = is_sum / n_is
    is_sd = np.sqrt(np.maximum(0.0, (is_sum2 - n_is * (is_mu ** 2)) / max(1, n_is - 1)))
    is_sr = np.where(is_sd > 1e-12, is_mu / np.maximum(is_sd, 1e-12) * math.sqrt(TRD_DAYS_YEAR), -999.0)

    oos_sum = tot_sum[None, :] - is_sum
    oos_sum2 = tot_sum2[None, :] - is_sum2
    oos_mu = oos_sum / n_oos
    oos_sd = np.sqrt(np.maximum(0.0, (oos_sum2 - n_oos * (oos_mu ** 2)) / max(1, n_oos - 1)))
    oos_sr = np.where(oos_sd > 1e-12, oos_mu / np.maximum(oos_sd, 1e-12) * math.sqrt(TRD_DAYS_YEAR), 0.0)

    win_idx = np.argmax(is_sr, axis=1)
    win_oos_sr = oos_sr[np.arange(n_splits), win_idx]

    ranks = np.empty(n_splits, dtype=float)
    for r_i in range(n_splits):
        row = oos_sr[r_i]
        wv = win_oos_sr[r_i]
        n_lt = float(np.sum(row < wv))
        n_eq = float(np.sum(row == wv))
        ranks[r_i] = (n_lt + 0.5 * (n_eq + 1.0)) / (K + 1.0)

    ranks_c = np.clip(ranks, 1e-4, 1.0 - 1e-4)
    logits = np.log(ranks_c / (1.0 - ranks_c))
    pbo = float(np.mean(logits <= 0.0))

    name_to_j = {nm: j for j, nm in enumerate(names)}
    j_ch = name_to_j[CHAMP_ID]
    j_pu = name_to_j[PURE_ID]
    j_v21 = name_to_j["B1_V21"]
    j_v20 = name_to_j["B0_V20"]

    per_cand = {}
    for j, nm in enumerate(names):
        mw = (win_idx == j)
        col_oos = oos_sr[:, j]
        # Compute OOS rank of candidate j across all splits
        all_ranks_j = np.mean(oos_sr < col_oos[:, None], axis=1)
        per_cand[nm] = {
            "is_win_pct": round(float(mw.mean() * 100.0), 2),
            "mean_oos_sr": round(float(np.mean(col_oos)), 3),
            "median_oos_pct_rank": round(float(np.median(all_ranks_j)), 4),
            "win_pbo": round(float(np.mean(logits[mw] <= 0.0)), 4) if mw.any() else None,
        }

    return {
        "K": K,
        "S": S,
        "L": L,
        "T_use": T_use,
        "n_splits": n_splits,
        "total_possible_splits": total_possible,
        "pbo": round(pbo, 4),
        "pbo_pct": round(pbo * 100.0, 2),
        "oos_rank_median": round(float(np.median(ranks)), 4),
        "oos_rank_p25": round(float(np.quantile(ranks, 0.25)), 4),
        "oos_rank_p75": round(float(np.quantile(ranks, 0.75)), 4),
        "logit_median": round(float(np.median(logits)), 4),
        "champ_vs_v21_oos_win_pct": round(float(np.mean(oos_sr[:, j_ch] > oos_sr[:, j_v21]) * 100.0), 2),
        "champ_vs_v20_oos_win_pct": round(float(np.mean(oos_sr[:, j_ch] > oos_sr[:, j_v20]) * 100.0), 2),
        "pure_vs_v21_oos_win_pct": round(float(np.mean(oos_sr[:, j_pu] > oos_sr[:, j_v21]) * 100.0), 2),
        "champ_vs_pure_oos_win_pct": round(float(np.mean(oos_sr[:, j_ch] > oos_sr[:, j_pu]) * 100.0), 2),
        "per_candidate": per_cand,
    }


def run_pillar2_cscv(cands_all: dict) -> dict:
    print("[Pillar 2] Running CSCV PBO (S=10 & S=16)...", flush=True)
    # Deduplicate mathematically identical curves (e.g. M5_A_Pos1 == M5_A_Pos2 == M5_A_Pos5)
    uniq = {}
    seen = []
    dups_dropped = []
    for nm, sim in cands_all.items():
        arr = sim["dr_5y"]
        matched = None
        for snm, sarr in seen:
            if np.allclose(arr, sarr, atol=1e-12):
                matched = snm
                break
        if matched is not None:
            dups_dropped.append(f"{nm} == {matched}")
        else:
            uniq[nm] = sim
            seen.append((nm, arr))

    print(f"  Candidate pool: {len(cands_all)} total -> {len(uniq)} unique (dropped exact dups: {dups_dropped})", flush=True)

    res = {
        "candidate_names_unique": list(uniq.keys()),
        "duplicates_dropped": dups_dropped,
        "full_pool": {},
        "no_rejected_xq_pool": {},
    }

    uniq_noxq = {k: v for k, v in uniq.items() if "XQLt6" not in k and "M5_B_Pos" not in k}
    for pool_lbl, pool_dict in [("full_pool", uniq), ("no_rejected_xq_pool", uniq_noxq)]:
        for win_lbl, wkey in [("FULL_5Y", "dr_5y"), ("WF_2326", "dr_wf")]:
            mat = {k: v[wkey] for k, v in pool_dict.items()}
            res[pool_lbl][win_lbl] = {
                "S10_exact_252": cscv_evaluate(mat, S=10, max_splits=None),
                "S16_2000_nondup": cscv_evaluate(mat, S=16, max_splits=2000, seed=20261126),
                "S16_exact_12870": cscv_evaluate(mat, S=16, max_splits=None),
            }
    return res


def run_pillar4_loyo_and_boot(models: dict, cal_5y: list[str]) -> tuple[dict, pd.DataFrame]:
    print("[Pillar 4] Running Leave-One-Year-Out (2021..2026) & 10,000x Moving Block Bootstrap...", flush=True)
    years_all = sorted({d[:4] for d in cal_5y})
    yr_arr = np.array([d[:4] for d in cal_5y])

    loyo_rows = []
    # 1. Leave-One-Year-Out (daily MTM mask) + Standalone Year
    for mode in ("LOYO_EXCL_YEAR", "SOLO_YEAR"):
        for yr in years_all:
            mask = (yr_arr != yr) if mode == "LOYO_EXCL_YEAR" else (yr_arr == yr)
            T_sub = int(mask.sum())
            row_pack = {}
            for nm, sim in models.items():
                dr_sub = sim["dr_5y"][mask]
                m = calc_moments(dr_sub)
                row_pack[nm] = m
                loyo_rows.append({
                    "eval_mode": mode,
                    "year_tag": yr,
                    "n_days": T_sub,
                    "model": nm,
                    "nav": m["nav"],
                    "cagr_pct": m["cagr_pct"],
                    "sr_ann": m["sr_ann"],
                    "mdd_pct": m["mdd_pct"],
                    "dd2_pct": m["dd2_pct"],
                    "calmar": m["calmar"],
                })

    # 2. Also verify Trade-Level LOYO (excluding trades with buy_date[:4] == yr)
    idx_5y = {d: i for i, d in enumerate(cal_5y)}
    T_5y = len(cal_5y)
    for yr in years_all:
        for nm, sim in models.items():
            tr_df = sim["trades_df"]
            tr_sub = tr_df[tr_df["buy_date"].str[:4] != yr]
            day_mult = np.ones(T_5y, dtype=float)
            for r in tr_sub.itertuples(index=False):
                segs = getattr(r, "mtm_use", None)
                if segs:
                    for ti, mult in segs:
                        if 0 <= int(ti) < T_5y:
                            day_mult[int(ti)] *= float(mult)
                else:
                    bi, ei = idx_5y.get(r.buy_date), idx_5y.get(r.exit_date)
                    if bi is not None and ei is not None and ei > bi:
                        span = ei - bi + 1
                        day_mult[bi : ei + 1] *= (1.0 + float(r.net_ret)) ** (1.0 / span)
            dr_tr = day_mult - 1.0
            m = calc_moments(dr_tr)
            loyo_rows.append({
                "eval_mode": "LOYO_EXCL_TRADES_IN_YEAR",
                "year_tag": yr,
                "n_days": T_5y,
                "model": nm,
                "nav": m["nav"],
                "cagr_pct": m["cagr_pct"],
                "sr_ann": m["sr_ann"],
                "mdd_pct": m["mdd_pct"],
                "dd2_pct": m["dd2_pct"],
                "calmar": m["calmar"],
            })

    df_loyo = pd.DataFrame(loyo_rows)
    df_loyo.to_csv(f"{OUT_DIR}/p4_loyo_table.csv", index=False, encoding="utf-8-sig")

    # Summary checks on LOYO_EXCL_YEAR
    loyo_summary = {"years": years_all, "champ_beats_v21_all_6_nav": True, "champ_beats_v21_all_6_sr": True, "champ_mdd_le_v21_all_6": True, "pure_beats_v21_all_6_nav": True, "pure_beats_v21_all_6_sr": True, "by_year_excl": {}}
    sub_ex = df_loyo[df_loyo["eval_mode"] == "LOYO_EXCL_YEAR"]
    for yr in years_all:
        g = sub_ex[sub_ex["year_tag"] == yr].set_index("model")
        ch, pu, v21, v20 = g.loc[CHAMP_ID], g.loc[PURE_ID], g.loc["B1_V21"], g.loc["B0_V20"]
        loyo_summary["champ_beats_v21_all_6_nav"] &= bool(ch["nav"] > v21["nav"])
        loyo_summary["champ_beats_v21_all_6_sr"] &= bool(ch["sr_ann"] > v21["sr_ann"])
        loyo_summary["champ_mdd_le_v21_all_6"] &= bool(ch["mdd_pct"] <= v21["mdd_pct"] + 1e-6)
        loyo_summary["pure_beats_v21_all_6_nav"] &= bool(pu["nav"] > v21["nav"])
        loyo_summary["pure_beats_v21_all_6_sr"] &= bool(pu["sr_ann"] > v21["sr_ann"])
        loyo_summary["by_year_excl"][yr] = {
            "V20": {"nav": float(v20["nav"]), "sr": float(v20["sr_ann"]), "mdd": float(v20["mdd_pct"])},
            "V21": {"nav": float(v21["nav"]), "sr": float(v21["sr_ann"]), "mdd": float(v21["mdd_pct"])},
            "Champ": {"nav": float(ch["nav"]), "sr": float(ch["sr_ann"]), "mdd": float(ch["mdd_pct"])},
            "Pure": {"nav": float(pu["nav"]), "sr": float(pu["sr_ann"]), "mdd": float(pu["mdd_pct"])},
        }

    # 3. 10,000x Moving Block Bootstrap (block_size = 5 & 10)
    def moving_block_boot(dr_a: np.ndarray, dr_b: np.ndarray, blk_sz: int, n_boot: int = 10000, seed: int = 20261126) -> dict:
        T = len(dr_a)
        n_blocks = math.ceil(T / blk_sz)
        max_start = T - blk_sz
        # Pre-extract overlapping blocks of log1p(r) and diff for ultra-fast vectorized computation
        l1a = np.log1p(np.clip(dr_a, -0.99, None))
        l1b = np.log1p(np.clip(dr_b, -0.99, None))
        diff = dr_a - dr_b

        starts = np.arange(max_start + 1)
        blk_idx = starts[:, None] + np.arange(blk_sz)[None, :]  # (max_start+1, blk_sz)
        blk_a = dr_a[blk_idx]
        blk_b = dr_b[blk_idx]
        blk_la = l1a[blk_idx]
        blk_lb = l1b[blk_idx]
        blk_d = diff[blk_idx]

        rng = np.random.default_rng(seed)
        # Process in chunks of 2000 to keep peak RAM tiny (< 50 MB)
        mean_d_all = np.empty(n_boot, dtype=float)
        nav_mult_all = np.empty(n_boot, dtype=float)
        dsr_all = np.empty(n_boot, dtype=float)

        chunk = 2000
        for s0 in range(0, n_boot, chunk):
            bs = min(chunk, n_boot - s0)
            picks = rng.integers(0, max_start + 1, size=(bs, n_blocks))
            sa = blk_a[picks].reshape(bs, n_blocks * blk_sz)[:, :T]
            sb = blk_b[picks].reshape(bs, n_blocks * blk_sz)[:, :T]
            sla = blk_la[picks].reshape(bs, n_blocks * blk_sz)[:, :T]
            slb = blk_lb[picks].reshape(bs, n_blocks * blk_sz)[:, :T]
            sd_arr = blk_d[picks].reshape(bs, n_blocks * blk_sz)[:, :T]

            mean_d_all[s0 : s0 + bs] = np.mean(sd_arr, axis=1)
            nav_mult_all[s0 : s0 + bs] = np.exp(np.sum(sla - slb, axis=1))
            sr_a = np.mean(sa, axis=1) / np.std(sa, axis=1, ddof=1) * math.sqrt(TRD_DAYS_YEAR)
            sr_b = np.mean(sb, axis=1) / np.std(sb, axis=1, ddof=1) * math.sqrt(TRD_DAYS_YEAR)
            dsr_all[s0 : s0 + bs] = sr_a - sr_b

        return {
            "n_boot": n_boot,
            "block_size": blk_sz,
            "T": T,
            "prob_mean_excess_gt0_pct": round(float(np.mean(mean_d_all > 0.0) * 100.0), 2),
            "mean_excess_ann_pp_p05": round(float(np.quantile(mean_d_all, 0.05) * TRD_DAYS_YEAR * 100.0), 2),
            "mean_excess_ann_pp_med": round(float(np.median(mean_d_all) * TRD_DAYS_YEAR * 100.0), 2),
            "mean_excess_ann_pp_p95": round(float(np.quantile(mean_d_all, 0.95) * TRD_DAYS_YEAR * 100.0), 2),
            "prob_nav_mult_gt1_pct": round(float(np.mean(nav_mult_all > 1.0) * 100.0), 2),
            "nav_mult_p05": round(float(np.quantile(nav_mult_all, 0.05)), 4),
            "nav_mult_med": round(float(np.median(nav_mult_all)), 4),
            "nav_mult_p95": round(float(np.quantile(nav_mult_all, 0.95)), 4),
            "prob_sharpe_beat_pct": round(float(np.mean(dsr_all > 0.0) * 100.0), 2),
            "d_sharpe_p05": round(float(np.quantile(dsr_all, 0.05)), 4),
            "d_sharpe_med": round(float(np.median(dsr_all)), 4),
            "d_sharpe_p95": round(float(np.quantile(dsr_all, 0.95)), 4),
        }

    boot_res = {}
    pairs = [
        ("Champ_vs_V21", CHAMP_ID, "B1_V21"),
        ("Pure_vs_V21", PURE_ID, "B1_V21"),
        ("Champ_vs_V20", CHAMP_ID, "B0_V20"),
        ("Champ_vs_Pure", CHAMP_ID, PURE_ID),
    ]
    for pname, nm_a, nm_b in pairs:
        boot_res[pname] = {}
        for wlbl, wkey in [("FULL_5Y", "dr_5y"), ("WF_2326", "dr_wf")]:
            boot_res[pname][wlbl] = {
                "block_5": moving_block_boot(models[nm_a][wkey], models[nm_b][wkey], blk_sz=5, n_boot=10000),
                "block_10": moving_block_boot(models[nm_a][wkey], models[nm_b][wkey], blk_sz=10, n_boot=10000),
            }

    return {"loyo_summary": loyo_summary, "moving_block_bootstrap_10k": boot_res}, df_loyo


def main():
    t0 = time.time()
    print("[Step 1] Loading caches & constructing full 25+ candidate pool...", flush=True)
    with open(f"{P3}/_cache/step1_ablation_results.pkl", "rb") as f:
        s1 = pickle.load(f)
    with open(f"{RD038}/_cache/rd038_master_cache.pkl", "rb") as f:
        cache_base = pickle.load(f)
    reg = pd.read_parquet(f"{RD049}/_cache/rd049_daily_regime_pit.parquet")
    reg_idx = v22.cm49.build_2d_states(reg, y_cut=42.0, x_sh=20.0, x_dp=42.0).set_index("trade_date")
    with open(f"{P3}/_cache/v22_dirb_ledgers_full.pkl", "rb") as f:
        dirb = pickle.load(f)["ledgers"]

    cal_5y = cache_base["cal_5y"]

    # Build Pure_V21_P2_SJ114_E4_Pos1/Pos2/Pos5 + RD049 S1..S5 + P2_R_AGGR
    c_p2_only = v22.apply_v22_modifications(cache_base, reg_idx, use_p2=True, use_dirA=False)
    pure_sims = {}
    for pm in ("Pos1", "Pos2", "Pos5"):
        pure_sims[f"Pure_V21_P2_SJ114_E4_{pm}"] = v22.run_v22_sim(
            c_p2_only, v22.CFG_V21, raw_4to5_df=dirb["SJ114_E4_DtDefer"]["raw"],
            pos_mode=pm, fee_mode="030", tier_lbl="4to5_SJ114_E4_DtDefer",
        )

    rd049_sims = {}
    for nm, kw in [
        ("V21_S1_SkipYellow", dict(mode="skip_yellow", pry_cold=True)),
        ("V21_S2_DynThr", dict(mode="tier", d_l4=12, d_l3=9, d_l2=9, af03_weak=False, pry_cold=True)),
        ("V21_S3_TierFull", dict(mode="tier", d_l4=12, d_l3=9, d_l2=9, af03_weak=True, pry_cold=True)),
        ("V21_S4_R2DFull", dict(mode="runion", r0=38, rk=12, raf=45, af03_weak=True, pry_cold=True)),
        ("V21_S5_TierNoPry", dict(mode="tier", d_l4=12, d_l3=9, d_l2=9, af03_weak=True, pry_cold=False)),
    ]:
        cf = v22.cm49.apply_rd049_filter(cache_base, reg_idx, **kw)
        rd049_sims[nm] = v22.eng.run_bundle_sim(cf, v22.CFG_V21, fee_mode="030")

    cf_aggr = p2s.apply_rescue_filter(cache_base, reg_idx, pos_cut=0.50, pry_mkt_cut=30.0, pry_dt_climax=100.0)
    rd049_sims["V21_P2_R_AGGR"] = v22.eng.run_bundle_sim(cf_aggr, v22.CFG_V21, fee_mode="030")

    models_4 = {
        "B0_V20": s1["sim_030"]["B0_V20"],
        "B1_V21": s1["sim_030"]["B1_V21"],
        CHAMP_ID: s1["sim_030"][CHAMP_ID],
        PURE_ID: pure_sims[PURE_ID],
    }

    # Assemble candidate pool for CSCV
    cscv_pool = {
        "B0_V20": s1["sim_030"]["B0_V20"],
        "B1_V21": s1["sim_030"]["B1_V21"],
        **rd049_sims,
        "V21_M1_P2_OPT": s1["sim_030"]["V21_M1_P2"],
        "V21_M2_DirA": s1["sim_030"]["V21_M2_DirA"],
        "V21_M4_P2_DirA": s1["sim_030"]["V21_M4_P2_DirA"],
        "V21_M3_Fix120_7f_DtDefer_Pos5": s1["sim_030"]["V21_M3_Fix120_7f_DtDefer_Pos5"],
        "V21_M3_SJ114_E4_DtDefer_Pos5": s1["sim_030"]["V21_M3_SJ114_E4_DtDefer_Pos5"],
        "V21_M3_SJ114_7f_DtDefer_Pos5": s1["sim_030"]["V21_M3_SJ114_7f_DtDefer_Pos5"],
        "V21_M3_SJ114_XQLt6_7f_DtDefer_Pos5": s1["sim_030"]["V21_M3_SJ114_XQLt6_7f_DtDefer_Pos5"],
        **pure_sims,
        "V21_M5_A_Pos5": s1["sim_030"]["V21_M5_A_Pos5"],
        "V21_M5_A_Pos1": s1["sim_030"]["V21_M5_A_Pos1"],
        "V21_M5_A_Pos2": s1["sim_030"]["V21_M5_A_Pos2"],
        "V21_M5_B_NoXQ_Pos1": s1["sim_030"]["V21_M5_B_NoXQ_Pos1"],
        "V21_M5_B_NoXQ_Pos2": s1["sim_030"]["V21_M5_B_NoXQ_Pos2"],
        CHAMP_ID: s1["sim_030"][CHAMP_ID],
        "V21_M5_B_Pos1": s1["sim_030"]["V21_M5_B_Pos1"],
        "V21_M5_B_Pos2": s1["sim_030"]["V21_M5_B_Pos2"],
        "V21_M5_B_Pos5": s1["sim_030"]["V21_M5_B_Pos5"],
    }

    all_v22_sims = {**s1["sim_030"], **pure_sims, **rd049_sims}

    p1 = run_pillar1_dsr(models_4, all_v22_sims)
    p2 = run_pillar2_cscv(cscv_pool)
    p4, _ = run_pillar4_loyo_and_boot(models_4, cal_5y)

    out_pkg = v22.sanitize_json({
        "elapsed_sec": round(time.time() - t0, 2),
        "pillar1_dsr_mintrl": p1,
        "pillar2_cscv_pbo": p2,
        "pillar4_loyo_and_boot": p4,
    })
    with open(f"{CACHE_DIR}/p4_pillars_1_2_4.json", "w", encoding="utf-8") as f:
        json.dump(out_pkg, f, ensure_ascii=False, indent=2)

    print(f"\n[Pillars 1, 2, 4 DONE in {time.time()-t0:.1f}s | RSS={v22.rss_mb()} MB]", flush=True)
    print("=== P1 Summary (N=300) ===")
    for nm in ("B0_V20", "B1_V21", CHAMP_ID, PURE_ID):
        d5 = p1["absolute_vs_0"][nm]["FULL_5Y"]["N_300"]["pooled_var"]
        dw = p1["absolute_vs_0"][nm]["WF_2326"]["N_300"]["pooled_var"]
        print(f"  Abs {nm:28s}: 5Y SR={d5['sr_ann']:.3f} DSR={d5['dsr']:.4f} MinTRL={d5['mintrl_days']}d | WF SR={dw['sr_ann']:.3f} DSR={dw['dsr']:.4f} MinTRL={dw['mintrl_days']}d")
    for nm in (CHAMP_ID, PURE_ID):
        s5 = p1["incremental_spread_vs_v21"][nm]["FULL_5Y"]["by_N"]["N_300"]
        sw = p1["incremental_spread_vs_v21"][nm]["WF_2326"]["by_N"]["N_300"]
        print(f"  Spread vs V21 {nm:18s}: 5Y empDSR={s5['spread_emp_var']['dsr']:.4f} (MinTRL={s5['spread_emp_var']['mintrl_days']}d) nullDSR={s5['spread_null_var']['dsr']:.4f} | WF empDSR={sw['spread_emp_var']['dsr']:.4f} (MinTRL={sw['spread_emp_var']['mintrl_days']}d) nullDSR={sw['spread_null_var']['dsr']:.4f}")

    print("=== P2 Summary (full_pool K={}) ===".format(p2["full_pool"]["FULL_5Y"]["S10_exact_252"]["K"]))
    for w in ("FULL_5Y", "WF_2326"):
        for s in ("S10_exact_252", "S16_2000_nondup", "S16_exact_12870"):
            x = p2["full_pool"][w][s]
            print(f"  {w:7s} {s:16s}: PBO={x['pbo_pct']:5.2f}%, med_rank={x['oos_rank_median']:.3f}, Ch>V21={x['champ_vs_v21_oos_win_pct']:.2f}%, Pu>V21={x['pure_vs_v21_oos_win_pct']:.2f}%")

    print("=== P4 Summary ===")
    print("  LOYO:", {k: v for k, v in p4["loyo_summary"].items() if k != "by_year_excl"})
    for pn in ("Champ_vs_V21", "Pure_vs_V21", "Champ_vs_Pure"):
        b5 = p4["moving_block_bootstrap_10k"][pn]["FULL_5Y"]["block_5"]
        b10 = p4["moving_block_bootstrap_10k"][pn]["FULL_5Y"]["block_10"]
        print(f"  Boot5Y {pn:14s}: B5 P(mean>0)={b5['prob_mean_excess_gt0_pct']}%, P(NAV>1)={b5['prob_nav_mult_gt1_pct']}%, mult_p05={b5['nav_mult_p05']} | B10 P(mean>0)={b10['prob_mean_excess_gt0_pct']}%, mult_p05={b10['nav_mult_p05']}")


if __name__ == "__main__":
    main()

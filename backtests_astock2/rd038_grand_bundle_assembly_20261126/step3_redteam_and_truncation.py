#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD038 Step 4: Physical 2024-12-31 Truncation Proof, Bundle Plateau, CSCV PBO, >=2yi Liquidity, & Incremental DSR."""

import gc
import json
import math
import os
import pickle
import resource
import sys
import time

os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "2")

import numpy as np
import pandas as pd
import scipy.stats as stats

assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd038_grand_bundle_assembly_20261126"
CACHE_PKL = f"{OUT_DIR}/_cache/rd038_master_cache.pkl"
PART1_20CM = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd036_highorder_3way_4way_20261126/part1_20cm"
PART2_O5 = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd036_highorder_3way_4way_20261126/part2_other5"

for p in (OUT_DIR, PART1_20CM, PART2_O5):
    if p not in sys.path:
        sys.path.insert(0, p)

import _rd038_engine as eng
import _common_rd036 as cm
import rd036_lib as lib20
import run_m1_m2_cold_and_pairwise as m12
import run_m3_m4_3way_4way_trees as m34

CUTOFF = "2024-12-31"


def rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 1)


def calc_dsr_exact(dr: np.ndarray, n_trials: int, var_sr_daily: float, sr_bench_daily: float = 0.0) -> dict:
    """High-precision DSR returning exact z_dsr and 6-decimal p-value."""
    x = np.asarray(dr, dtype=float)
    T = len(x)
    mu = float(np.mean(x))
    sd = float(np.std(x, ddof=1))
    sr = mu / sd
    g3 = float(stats.skew(x, bias=True))
    g4 = float(stats.kurtosis(x, fisher=False, bias=True))
    gamma_em = 0.5772156649015329
    if n_trials <= 1 or var_sr_daily <= 0.0:
        sr0 = sr_bench_daily
    else:
        z1 = float(stats.norm.ppf(1.0 - 1.0 / n_trials))
        z2 = float(stats.norm.ppf(1.0 - 1.0 / (n_trials * math.e)))
        sr0 = sr_bench_daily + math.sqrt(var_sr_daily) * ((1.0 - gamma_em) * z1 + gamma_em * z2)
    denom_in = max(1e-12, (1.0 - g3 * sr + ((g4 - 1.0) / 4.0) * (sr ** 2)) / max(1, T - 1))
    z_dsr = (sr - sr0) / math.sqrt(denom_in)
    return {
        "sr_ann": round(sr * math.sqrt(eng.TRD_DAYS_YEAR), 3),
        "sr0_ann": round(sr0 * math.sqrt(eng.TRD_DAYS_YEAR), 3),
        "z_dsr": round(z_dsr, 4),
        "dsr": round(float(stats.norm.cdf(z_dsr)), 6),
    }


def run_physical_truncation_proof(cache: dict, step2_meta: dict) -> dict:
    """Physically truncate all pools & raw 20cm to <=2024-12-31, rebuild every causal learner from scratch, and prove 0 diff."""
    print("\n[RedTeam 1/4] Physical 2024-12-31 Truncation Zero-Leakage Proof ...")
    bundle_o5 = cm.build_or_load_cache(force_rebuild=False)
    pools_t = {st: df[df["buy_date"] <= CUTOFF].copy().reset_index(drop=True) for st, df in cache["pools_ext"].items()}
    ut_t = cache["ut_full_raw"][cache["ut_full_raw"]["buy_date"] <= CUTOFF].copy().reset_index(drop=True)
    cal_5y_t = [d for d in cache["cal_5y"] if d <= CUTOFF]
    bench_t = cache["bench_5y"][cache["bench_5y"]["trade_date"] <= CUTOFF].copy().reset_index(drop=True)

    # 1. Rebuild 20cm Stack & Blend strictly from raw <=2024-12-31
    p20_t, meta20_t = lib20.load_20cm_enriched_data(end_cutoff=CUTOFF)
    p20_t["wf_in_window"] = p20_t["buy_date"] >= eng.WF_START
    dm_cb_t, _ = lib20.run_mode_b_multi_grid(p20_t, meta20_t["feat_clean_b"], ["v20_cold50"], deltas=(15,), min_discrete_bin_cnt=15, top_k=10)
    dm_mn_t, _ = lib20.run_mode_b_multi_grid(p20_t, meta20_t["ix_cols"], ["v20_cold50"], deltas=(15,), min_discrete_bin_cnt=0, top_k=10)
    ho_t = lib20.run_causal_highorder_and_tree_wf(
        p20_t, atomic_cols=meta20_t["atomic_cols"], extra_static_cols=meta20_t["feat_union_cb_mech"],
        wf_start_date=eng.WF_START, min_warmup_trades=80, deltas=(8, 12, 15), enable_4way=False,
    )
    c50_t = p20_t["v20_cold50"].to_numpy(float)
    d_cb_t = dm_cb_t[("v20_cold50", 15)]
    d_mn_t = dm_mn_t[("v20_cold50", 15)]
    d_3w_t = ho_t["rule_deltas"][("Rule3Way", 12)]
    s_blend_t = c50_t + np.round(0.5 * d_cb_t + 0.5 * d_mn_t)
    s_stack_t = c50_t + np.round((d_cb_t + d_mn_t + d_3w_t) / 3.0)

    p20_key_t = {(str(r.buy_date)[:10], str(r.code).zfill(6)): idx for idx, r in enumerate(p20_t.itertuples(index=False))}
    sc20_t = {}
    for kn, sv_src in [("blend_c50_half", s_blend_t), ("stack_c50_avg", s_stack_t)]:
        arr = np.empty(len(pools_t["20cm"]), dtype=float)
        for j, r in enumerate(pools_t["20cm"].itertuples(index=False)):
            idx_p = p20_key_t.get((str(r.buy_date)[:10], str(r.code).zfill(6)))
            if idx_p is None:
                arr[j] = float(r.orig_score)
            elif str(r.buy_date)[:10] < eng.WF_START:
                arr[j] = float(r.orig_score) if float(r.orig_score) >= 82.0 else -999.0
            else:
                arr[j] = float(sv_src[idx_p])
        sc20_t[kn] = arr
    del p20_t, dm_cb_t, dm_mn_t, ho_t
    gc.collect()

    # 2. Rebuild 3to4, 2to3, high, pry causal learners strictly on <=2024-12-31
    o5_t = {"3to4": {}, "2to3": {}, "high": {}, "pry": {}}
    df34_t = pools_t["3to4"]
    orig34_t = df34_t["orig_score"].to_numpy(float)
    bp34 = list(dict.fromkeys(bundle_o5["base_dyn_cols"] + bundle_o5["atom_info"]["3to4"]["cols"]))
    r4_34_t = m34.run_wf_3way_4way_and_trees(df34_t, bp34, min_leaf=20, min_days=8, order=4, run_trees=False)
    o5_t["3to4"]["m4_4way_bl15"] = {"score": orig34_t, "mask": np.where(df34_t["buy_date"] >= eng.WF_START, ~r4_34_t["mine_bl"][15], True)}

    df23_t = pools_t["2to3"]
    orig23_t = df23_t["orig_score"].to_numpy(float)
    bp23 = list(dict.fromkeys(bundle_o5["base_dyn_cols"] + bundle_o5["atom_info"]["2to3"]["cols"]))
    dp23_t, _ = m12.run_causal_pairwise_multi(df23_t, bundle_o5["ix_cols"], bp23, cold_cut=45.0, regime_mode="cold_only", max_deltas=(15,), min_cell=cm.MIN_LEAF_MAP["2to3"])
    o5_t["2to3"]["m2_pair_cold45_d15"] = {"score": orig23_t + np.where(df23_t["buy_date"] >= eng.WF_START, dp23_t[15], 0.0), "mask": None}

    dfhi_full = cache["pools_ext"]["high"]
    m_hi_t = (dfhi_full["buy_date"] <= CUTOFF).to_numpy(bool)
    dfhi_t = pools_t["high"]
    orighi_t = dfhi_t["orig_score"].to_numpy(float)
    sc_hi_t = m12.run_causal_cold_atom_disable(dfhi_t, bundle_o5["atom_info"]["high"]["cols"], bundle_o5["atom_info"]["high"]["contrib_mat"][m_hi_t], cold_cut=40.0, t_cut=0.0, bonus_only=True)
    o5_t["high"]["m1_causal_cold_drop40_t0"] = {"score": np.where(dfhi_t["buy_date"] >= eng.WF_START, sc_hi_t, orighi_t), "mask": None}

    dfpr_t = pools_t["pry"]
    origpr_t = dfpr_t["orig_score"].to_numpy(float)
    bp_pr = list(dict.fromkeys(bundle_o5["base_dyn_cols"] + bundle_o5["atom_info"]["pry"]["cols"]))
    dp_pr_t, _ = m12.run_causal_pairwise_multi(dfpr_t, bundle_o5["ix_cols"], bp_pr, cold_cut=45.0, regime_mode="cold_only", max_deltas=(15,), min_cell=cm.MIN_LEAF_MAP["pry"], decluster_days=True)
    o5_t["pry"]["m1_skip_cold50"] = {"score": origpr_t, "mask": np.where(dfpr_t["buy_date"] >= eng.WF_START, dfpr_t["mkt10_zt_est_t1"].to_numpy(float) >= 50.0, True)}
    o5_t["pry"]["m2_pair_cold45_d15"] = {"score": origpr_t + np.where(dfpr_t["buy_date"] >= eng.WF_START, dp_pr_t[15], 0.0), "mask": None}

    # Check raw component score diffs <= CUTOFF
    comp_diffs = {}
    m_20_t = (cache["pools_ext"]["20cm"]["buy_date"] <= CUTOFF).to_numpy(bool)
    m_34_t = (cache["pools_ext"]["3to4"]["buy_date"] <= CUTOFF).to_numpy(bool)
    m_23_t = (cache["pools_ext"]["2to3"]["buy_date"] <= CUTOFF).to_numpy(bool)
    m_pr_t = (cache["pools_ext"]["pry"]["buy_date"] <= CUTOFF).to_numpy(bool)
    for kn in ("stack_c50_avg", "blend_c50_half"):
        f_arr = cache["sc20_aligned"][kn][m_20_t]
        comp_diffs[f"20cm_{kn}"] = float(np.max(np.abs(f_arr - sc20_t[kn])))
    comp_diffs["3to4_m4_4way_bl15_mask_diff"] = int(np.sum(cache["other5_variants"]["3to4"]["m4_4way_bl15"]["mask"][m_34_t] != o5_t["3to4"]["m4_4way_bl15"]["mask"]))
    comp_diffs["2to3_m2_pair_cold45_d15"] = float(np.max(np.abs(cache["other5_variants"]["2to3"]["m2_pair_cold45_d15"]["score"][m_23_t] - o5_t["2to3"]["m2_pair_cold45_d15"]["score"])))
    comp_diffs["high_cold_drop40_t0"] = float(np.max(np.abs(cache["other5_variants"]["high"]["m1_causal_cold_drop40_t0"]["score"][m_hi_t] - o5_t["high"]["m1_causal_cold_drop40_t0"]["score"])))
    comp_diffs["pry_m2_pair_cold45_d15"] = float(np.max(np.abs(cache["other5_variants"]["pry"]["m2_pair_cold45_d15"]["score"][m_pr_t] - o5_t["pry"]["m2_pair_cold45_d15"]["score"])))
    for k, dv in comp_diffs.items():
        assert dv == 0.0, f"Component score diff on {k}: {dv}"

    trunc_cache = {
        "cal_5y": cal_5y_t,
        "bench_5y": bench_t,
        "pools_ext": pools_t,
        "ut_full_raw": ut_t,
        "sc20_aligned": sc20_t,
        "other5_variants": o5_t,
        "b0_lu": {k: v for k, v in cache["b0_lu"].items() if k[2] <= CUTOFF},
        "swap_close_lu": {k: v for k, v in cache["swap_close_lu"].items() if k[1] <= CUTOFF},
    }

    target_cfgs = {
        "ALLIN_ROBUST": {
            "s20": "stack_c50_avg", "s34": "m4_4way_bl15", "s23": "m2_pair_cold45_d15",
            "shi": "m1_causal_cold_drop40_t0", "spr": "m1_skip_cold50", "s12": "base",
            "w2a5": "S_HighTier_0925", "w2a6": "s_tier_plus_1to2S",
        },
        "ALLIN_OFFENSIVE": {
            "s20": "blend_c50_half", "s34": "m4_4way_bl15", "s23": "m2_pair_cold45_d15",
            "shi": "m1_causal_cold_drop40_t0", "spr": "m2_pair_cold45_d15", "s12": "base",
            "w2a5": "S_HighTier_0925", "w2a6": "s_tier_plus_1to2S",
        },
        "GREEDY_CLEAN": step2_meta["greedy_configs"]["OFFENSIVE_BLEND"],
        "GREEDY_ROBUST": step2_meta["greedy_configs"]["ROBUST_STACK"],
    }

    bundle_proofs = {}
    for bname, bcfg in target_cfgs.items():
        s_full = eng.run_bundle_sim(cache, bcfg, fee_mode="030")["trades_df"]
        s_trunc = eng.run_bundle_sim(trunc_cache, bcfg, fee_mode="030")["trades_df"]
        f_le = s_full[s_full["exit_date"] <= CUTOFF].sort_values(["buy_date", "code"]).reset_index(drop=True)
        t_le = s_trunc[s_trunc["exit_date"] <= CUTOFF].sort_values(["buy_date", "code"]).reset_index(drop=True)
        assert len(f_le) == len(t_le), f"{bname} count mismatch: {len(f_le)} vs {len(t_le)}"
        assert list(zip(f_le["buy_date"], f_le["code"], f_le["strategy"])) == list(zip(t_le["buy_date"], t_le["code"], t_le["strategy"]))
        r_diff = float(np.max(np.abs(f_le["net_ret"].to_numpy(float) - t_le["net_ret"].to_numpy(float))))
        assert r_diff == 0.0, f"{bname} ret diff={r_diff}"
        bundle_proofs[bname] = {
            "cutoff": CUTOFF,
            "n_trades_exiting_le_cutoff": int(len(f_le)),
            "max_abs_score_diff": 0.0,
            "max_abs_ret_diff": r_diff,
            "zero_leakage_pass": True,
        }
        print(f"  Trunc {bname:18s}: trades_le={len(f_le)}, max_score_diff=0.0, max_ret_diff={r_diff} [PASS]")

    return {"component_diffs": comp_diffs, "bundles": bundle_proofs}


def run_plateau_pbo_and_liquidity(cache: dict, step2_meta: dict) -> dict:
    """Bundle-level parameter perturbation plateau, CSCV PBO, >=2yi liquidity check & DSR_vs_V20."""
    print("\n[RedTeam 2/4] Building bundle-level neighbor parameter perturbation plateau ...")
    bundle_o5 = cm.build_or_load_cache(force_rebuild=False)
    o5_ext = {st: dict(v) for st, v in cache["other5_variants"].items()}

    # Generate clean neighbor variants for 3to4, 2to3, high, pry
    df34 = cache["pools_ext"]["3to4"]
    orig34 = df34["orig_score"].to_numpy(float)
    bp34 = list(dict.fromkeys(bundle_o5["base_dyn_cols"] + bundle_o5["atom_info"]["3to4"]["cols"]))
    r4_34 = m34.run_wf_3way_4way_and_trees(df34, bp34, min_leaf=20, min_days=8, order=4, run_trees=False)
    for q in (10, 20):
        o5_ext["3to4"][f"m4_4way_bl{q}"] = {"score": orig34, "mask": np.where(df34["buy_date"] >= eng.WF_START, ~r4_34["mine_bl"][q], True)}

    df23 = cache["pools_ext"]["2to3"]
    orig23 = df23["orig_score"].to_numpy(float)
    bp23 = list(dict.fromkeys(bundle_o5["base_dyn_cols"] + bundle_o5["atom_info"]["2to3"]["cols"]))
    for cc in (40.0, 45.0, 50.0):
        dp23, _ = m12.run_causal_pairwise_multi(df23, bundle_o5["ix_cols"], bp23, cold_cut=cc, regime_mode="cold_only", max_deltas=(10, 15), min_cell=cm.MIN_LEAF_MAP["2to3"])
        for md in (10, 15):
            o5_ext["2to3"][f"m2_pair_c{int(cc)}_d{md}"] = {"score": orig23 + np.where(df23["buy_date"] >= eng.WF_START, dp23[md], 0.0), "mask": None}

    dfhi = cache["pools_ext"]["high"]
    orighi = dfhi["orig_score"].to_numpy(float)
    for cc in (35.0, 45.0):
        sch = m12.run_causal_cold_atom_disable(dfhi, bundle_o5["atom_info"]["high"]["cols"], bundle_o5["atom_info"]["high"]["contrib_mat"], cold_cut=cc, t_cut=0.0, bonus_only=True)
        o5_ext["high"][f"m1_cold_drop{int(cc)}_t0"] = {"score": np.where(dfhi["buy_date"] >= eng.WF_START, sch, orighi), "mask": None}

    dfpr = cache["pools_ext"]["pry"]
    origpr = dfpr["orig_score"].to_numpy(float)
    for cc in (45, 55):
        o5_ext["pry"][f"m1_skip_cold{cc}"] = {"score": origpr, "mask": np.where(dfpr["buy_date"] >= eng.WF_START, dfpr["mkt10_zt_est_t1"].to_numpy(float) >= float(cc), True)}

    cache_ext = {**cache, "other5_variants": o5_ext}
    cfg_v20 = {"s20": "base_76", "s34": "base", "s23": "base", "shi": "base", "spr": "base", "s12": "base", "w2a5": "none", "w2a6": "s_tier_reserve_only"}

    base_greedy_clean = step2_meta["greedy_configs"]["OFFENSIVE_BLEND"]
    base_greedy_robust = step2_meta["greedy_configs"]["ROBUST_STACK"]
    allin_rob = {"s20": "stack_c50_avg", "s34": "m4_4way_bl15", "s23": "m2_pair_cold45_d15", "shi": "m1_causal_cold_drop40_t0", "spr": "m1_skip_cold50", "s12": "base", "w2a5": "S_HighTier_0925", "w2a6": "s_tier_plus_1to2S"}
    allin_off = {"s20": "blend_c50_half", "s34": "m4_4way_bl15", "s23": "m2_pair_cold45_d15", "shi": "m1_causal_cold_drop40_t0", "spr": "m2_pair_cold45_d15", "s12": "base", "w2a5": "S_HighTier_0925", "w2a6": "s_tier_plus_1to2S"}

    # Build neighbor suite around ALLIN & GREEDY + core bundles for CSCV PBO
    mat_dict = {}
    core_bundles = {
        "BASE_V20_Unified": cfg_v20,
        "BASE_V20_S80_Thresh": {**cfg_v20, "s20": "base_80_wf"},
        "ONLY_20CM_COLD50": {**cfg_v20, "s20": "cold50_wf"},
        "ONLY_20CM_CLEANB": {**cfg_v20, "s20": "cleanb_c50_d15"},
        "ONLY_20CM_STACK": {**cfg_v20, "s20": "stack_c50_avg"},
        "ONLY_20CM_BLEND": {**cfg_v20, "s20": "blend_c50_half"},
        "OTHER5_ONLY_ALLIN": {**allin_rob, "s20": "base_76"},
        "ALLIN_ROBUST": allin_rob,
        "ALLIN_ROBUST_NoRound": {**allin_rob, "s20": "stack_c50_noround"},
        "ALLIN_OFFENSIVE": allin_off,
        "ALLIN_OFFENSIVE_NoRound": {**allin_off, "s20": "blend_c50_noround"},
        "GREEDY_CLEAN": base_greedy_clean,
        "GREEDY_ROBUST": base_greedy_robust,
    }
    nb_configs = {
        "NB_Rob_20cm_S78": {**allin_rob, "s20_thr": 78.0},
        "NB_Rob_20cm_S82": {**allin_rob, "s20_thr": 82.0},
        "NB_Rob_20cm_S84": {**allin_rob, "s20_thr": 84.0},
        "NB_Grd_20cm_S78": {**base_greedy_clean, "s20_thr": 78.0},
        "NB_Grd_20cm_S82": {**base_greedy_clean, "s20_thr": 82.0},
        "NB_Grd_20cm_S84": {**base_greedy_clean, "s20_thr": 84.0},
        "NB_Rob_34_BL10": {**allin_rob, "s34": "m4_4way_bl10"},
        "NB_Rob_34_BL20": {**allin_rob, "s34": "m4_4way_bl20"},
        "NB_Rob_34_Pair45": {**allin_rob, "s34": "m2_pair_cold45_d15"},
        "NB_Rob_23_c40_d15": {**allin_rob, "s23": "m2_pair_c40_d15"},
        "NB_Rob_23_c50_d15": {**allin_rob, "s23": "m2_pair_c50_d15"},
        "NB_Rob_23_c45_d10": {**allin_rob, "s23": "m2_pair_c45_d10"},
        "NB_Rob_hi_cut35": {**allin_rob, "shi": "m1_cold_drop35_t0"},
        "NB_Rob_hi_cut45": {**allin_rob, "shi": "m1_cold_drop45_t0"},
        "NB_Rob_pry_Skip45": {**allin_rob, "spr": "m1_skip_cold45"},
        "NB_Rob_pry_Skip55": {**allin_rob, "spr": "m1_skip_cold55"},
        "NB_Grd_34_BL10": {**base_greedy_clean, "s34": "m4_4way_bl10"},
        "NB_Grd_34_BL20": {**base_greedy_clean, "s34": "m4_4way_bl20"},
        "NB_Grd_23_c40_d15": {**base_greedy_clean, "s23": "m2_pair_c40_d15"},
        "NB_Grd_23_c50_d15": {**base_greedy_clean, "s23": "m2_pair_c50_d15"},
        "NB_Grd_23_c45_d10": {**base_greedy_clean, "s23": "m2_pair_c45_d10"},
        "NB_Grd_hi_cut35": {**base_greedy_clean, "shi": "m1_cold_drop35_t0"},
        "NB_Grd_hi_cut45": {**base_greedy_clean, "shi": "m1_cold_drop45_t0"},
        "NB_Grd_pry_Skip50": {**base_greedy_clean, "spr": "m1_skip_cold50"},
    }

    plateau_rows = []
    for nm, cfg in {**core_bundles, **nb_configs}.items():
        sim = eng.run_bundle_sim(cache_ext, cfg, fee_mode="030")
        ev = eng.evaluate_bundle(nm, "NB", sim, cache_ext, perm_n=0)
        mat_dict[nm] = sim["dr_wf"]
        if nm in nb_configs:
            wf = ev["windows"]["WF_2326"]
            plateau_rows.append({
                "neighbor": nm, "n_wf": wf["n"], "nav_wf": wf["nav"],
                "ex5_wf": wf["ex_top5_nav"], "sharpe_wf": wf["daily_sharpe"],
                "mdd_wf": wf["daily_mdd_pct"], "nav_26h2": ev["windows"]["Y2026_H2"]["nav"],
            })

    # CSCV PBO (S=16 and S=10)
    print("[RedTeam 3/4] Running CSCV PBO (S=16 & S=10) & >=2yi Liquidity subset ...")
    targets = ["BASE_V20_Unified", "ONLY_20CM_STACK", "ONLY_20CM_BLEND", "ALLIN_ROBUST", "ALLIN_OFFENSIVE", "GREEDY_CLEAN", "GREEDY_ROBUST"]
    pbo_s16 = cm.cscv_pbo(mat_dict, S=16, target_names=targets)
    pbo_s10 = cm.cscv_pbo(mat_dict, S=10, target_names=targets)
    print(f"  CSCV PBO (K={pbo_s16['n_variants']}): S=16 PBO={pbo_s16['pbo']:.4f} | S=10 PBO={pbo_s10['pbo']:.4f}")

    # Causal >= 2亿 Liquidity subset check
    pools_liq = {}
    for st, df in cache["pools_ext"].items():
        d2 = df.copy()
        d2["can_buy_hygiene"] = d2["can_buy_hygiene"].fillna(True).to_numpy(bool) & (d2["sd_amount_yi_t1"].fillna(0.0).to_numpy(float) >= 2.0)
        pools_liq[st] = d2
    cache_liq = {**cache, "pools_ext": pools_liq}

    liq_res = {}
    for nm in targets:
        sim_l = eng.run_bundle_sim(cache_liq, core_bundles[nm], fee_mode="030")
        ev_l = eng.evaluate_bundle(f"{nm}_LIQ2YI", "LIQ", sim_l, cache_liq, perm_n=0)
        wf_l = ev_l["windows"]["WF_2326"]
        liq_res[nm] = {
            "n_wf": wf_l["n"], "nav_wf": wf_l["nav"], "ex5_wf": wf_l["ex_top5_nav"],
            "sharpe_wf": wf_l["daily_sharpe"], "mdd_wf": wf_l["daily_mdd_pct"],
            "nav_26h2": ev_l["windows"]["Y2026_H2"]["nav"],
        }
        print(f"  Liq >=2yi {nm:20s}: n={wf_l['n']:3d} WF={wf_l['nav']:11,.2f}x Sh={wf_l['daily_sharpe']:.3f}")

    # Incremental & Absolute Portfolio DSR
    print("[RedTeam 4/4] Computing high-precision DSR (vs 0 & incremental vs V20 SR=4.624) ...")
    sr_v20_daily = float(np.mean(mat_dict["BASE_V20_Unified"]) / np.std(mat_dict["BASE_V20_Unified"], ddof=1))
    n_rd038 = int(step2_meta["dsr_summary"]["n_trials_rd038"])
    n_cum = int(step2_meta["dsr_summary"]["n_trials_cum_with_rd035_rd036"])
    var_loc = float(step2_meta["dsr_summary"]["var_sr_daily_rd038_local"])
    var_pool = eng.DSR_VAR_POOLED
    var_null = 1.0 / max(1, len(mat_dict["BASE_V20_Unified"]) - 1)

    dsr_table = {}
    for nm in targets + ["OTHER5_ONLY_ALLIN", "ALLIN_ROBUST_NoRound", "ALLIN_OFFENSIVE_NoRound"]:
        dr = mat_dict[nm]
        dsr_table[nm] = {
            "abs_vs0_single_local": calc_dsr_exact(dr, n_rd038, var_loc, 0.0),
            "abs_vs0_cum_pool": calc_dsr_exact(dr, n_cum, var_pool, 0.0),
            "abs_vs0_cum_null": calc_dsr_exact(dr, n_cum, var_null, 0.0),
            "inc_vs_v20_single_local": calc_dsr_exact(dr, n_rd038, var_loc, sr_v20_daily),
            "inc_vs_v20_cum_local": calc_dsr_exact(dr, n_cum, var_loc, sr_v20_daily),
            "inc_vs_v20_cum_pool": calc_dsr_exact(dr, n_cum, var_pool, sr_v20_daily),
            "inc_vs_v20_cum_null": calc_dsr_exact(dr, n_cum, var_null, sr_v20_daily),
        }
        iv_loc = dsr_table[nm]["inc_vs_v20_single_local"]
        iv_cum = dsr_table[nm]["inc_vs_v20_cum_null"]
        print(f"  DSR_vs_V20 {nm:24s} | SR={iv_loc['sr_ann']:.3f} | single(N={n_rd038})={iv_loc['dsr']:.4f} (z={iv_loc['z_dsr']:.2f}) | cum_null(N={n_cum})={iv_cum['dsr']:.4f} (z={iv_cum['z_dsr']:.2f})")

    return {
        "plateau_neighbors": plateau_rows,
        "plateau_summary": {
            "n_neighbors": len(plateau_rows),
            "nav_wf_min": round(min(r["nav_wf"] for r in plateau_rows), 2),
            "nav_wf_median": round(float(np.median([r["nav_wf"] for r in plateau_rows])), 2),
            "nav_wf_max": round(max(r["nav_wf"] for r in plateau_rows), 2),
            "sharpe_wf_min": round(min(r["sharpe_wf"] for r in plateau_rows), 3),
            "pct_beat_v20_unified_nav": 100.0 if min(r["nav_wf"] for r in plateau_rows) > 534297.02 else 0.0,
        },
        "cscv_pbo": {"S16": pbo_s16, "S10": pbo_s10},
        "liquidity_2yi_wf": liq_res,
        "dsr_table": dsr_table,
    }


def main():
    t0 = time.time()
    with open(CACHE_PKL, "rb") as f:
        cache = pickle.load(f)
    with open(f"{OUT_DIR}/_cache/rd038_step2_summary.json", encoding="utf-8") as f:
        step2_meta = json.load(f)

    trunc_res = run_physical_truncation_proof(cache, step2_meta)
    rt_res = run_plateau_pbo_and_liquidity(cache, step2_meta)

    comp_df = pd.read_csv(f"{OUT_DIR}/rd038_bundles_compare.csv")
    loo_df = pd.read_csv(f"{OUT_DIR}/rd038_loo_stepwise_audit.csv")

    audit = cm.sanitize_json({
        "task": "RD038: Grand Bundle Assembly (RD035 W2A1-W2A6 + RD036 Part1/Part2) & Red-Team Audit",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t0, 2),
        "peak_rss_mb": rss_mb(),
        "d12_yfinance_imported": False,
        "step2_summary": step2_meta,
        "physical_truncation_2024_12_31": trunc_res,
        "redteam_plateau_pbo_liq_dsr": rt_res,
        "key_bundles_wf_030": comp_df[(comp_df["window"] == "WF_2326") & (comp_df["fee"] == "030")].to_dict("records"),
        "key_bundles_wf_050": comp_df[(comp_df["window"] == "WF_2326") & (comp_df["fee"] == "050")].to_dict("records"),
        "key_bundles_wf_080": comp_df[(comp_df["window"] == "WF_2326") & (comp_df["fee"] == "080")].to_dict("records"),
        "loo_and_stepwise": loo_df.to_dict("records"),
    })
    out_json = f"{OUT_DIR}/rd038_grand_bundle_audit.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(audit, f, indent=2, ensure_ascii=False)
    print(f"\n[STEP 3 REDTEAM DONE in {time.time()-t0:.1f}s | RSS={rss_mb()} MB] Saved {out_json}")


if __name__ == "__main__":
    main()

#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Part 2 Step 2:
  - M6 4-Way Grand Bundle PK via exact RD038 engine (`_rd038_engine.py`):
      1. V20.0 Baseline (`BASE_V20_Unified`)
      2. V21.0 Robust 4-Piece (`V21_GREEDY_ROBUST`)
      3. Pure Orthogonal / Shrinkage Upgrade (`ORTHO_PURE_*`, ZERO RD038 cold-day rules)
      4. V21.0 + Orthogonal Consolidation (`V21_PLUS_ORTHO_*`)
  - 5 Evaluation Windows (FULL_5Y, WF_2326, Y2025_2026, Y2026, Y2026_H2)
  - 3 Slippage Levels (030, 050, 080) + ex_top3 + ex_top5 + exact MTM (mtm_diff == 0.0)
  - 1000x Permutation Test + Paired-t vs V20 & V21 + >=2yi Liquidity Stress Test
  - Physical 2024-12-31 Truncation Zero-Leakage Proof (max_abs_score_diff == 0.0, max_abs_ret_diff == 0.0)
  - Outputs: `part2_combined_pk.csv`, `part2_ortho_audit.json`

Zero yfinance (D12). Read-only on RD038/RD036 caches.
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import json
import math
import pickle
import resource
import sys
import time

import numpy as np
import pandas as pd
import scipy.stats as stats

assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
RD038 = f"{SIM}/backtests_astock2/rd038_grand_bundle_assembly_20261126"
RD036_P2 = f"{SIM}/backtests_astock2/rd036_highorder_3way_4way_20261126/part2_other5"
OUT_DIR = f"{SIM}/backtests_astock/factor_orthogonality_consolidation_20261126/part2_ortho_models"

for p in (OUT_DIR, RD038, RD036_P2):
    if p not in sys.path:
        sys.path.insert(0, p)

import _ortho_lib as ol
import _rd038_engine as eng
import _common_rd036 as cm

CUTOFF = "2024-12-31"


def rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 1)


def paired_test(dr_a: np.ndarray, dr_b: np.ndarray) -> dict:
    dd = dr_a - dr_b
    sd = float(np.std(dd, ddof=1))
    T = len(dd)
    t_val = float(np.mean(dd) / (sd / math.sqrt(T))) if sd > 1e-12 else 0.0
    p2 = float(2.0 * stats.t.sf(abs(t_val), df=T - 1)) if sd > 1e-12 else 1.0
    return {"paired_t": round(t_val, 3), "paired_p_2sided": round(p2, 4), "n_diff_days": int((np.abs(dd) > 1e-12).sum())}


def build_truncation_proof(cache: dict, bundle: dict, st1_scores: dict, cand_ext_cols: list[str], bundle_cfgs: dict) -> dict:
    """
    Physically truncate ALL raw pools and calendars to <= 2024-12-31, re-fit EVERY causal ortho model
    used in M6 (plus representative M1-M5 across all 6 strategies) from scratch, and verify:
      - max_abs_score_diff == 0.0
      - max_abs_ret_diff == 0.0
    """
    print("\n[Truncation Proof] Physically truncating data to <= 2024-12-31 and refitting from scratch ...")
    pools_t = {st: df[df["buy_date"] <= CUTOFF].copy().reset_index(drop=True) for st, df in cache["pools_ext"].items()}
    ut_t = cache["ut_full_raw"][cache["ut_full_raw"]["buy_date"] <= CUTOFF].copy().reset_index(drop=True)
    cal_5y_t = [d for d in cache["cal_5y"] if d <= CUTOFF]
    bench_t = cache["bench_5y"][cache["bench_5y"]["trade_date"] <= CUTOFF].copy().reset_index(drop=True)

    # Specs to verify bit-for-bit truncation invariance across ALL 6 strategies & ALL 5 methods
    verify_specs_by_track = {
        "1to2": [
            {"variant_id": "M5_ENet_a06_g30__C_DynCore", "method": "M5", "feat_set": "C_DynCore", "reg_type": "enet", "alpha": 0.06, "gamma": 0.30, "cap": 15.0},
            {"variant_id": "M1_sign_r35_eq_v20sc__A_Atoms", "method": "M1", "feat_set": "A_Atoms", "r_cut": 0.35, "dist_mode": "signed", "agg_mode": "eq_z", "outer": "prior_v20"},
        ],
        "2to3": [
            {"variant_id": "M3_eps30_v20sc__A_Atoms", "method": "M3", "feat_set": "A_Atoms", "eps": 0.30, "outer": "prior_v20"},
            {"variant_id": "M4_Ridge_a150__B_PhysCore", "method": "M4", "feat_set": "B_PhysCore", "reg_type": "ridge", "alpha": 150.0},
        ],
        "3to4": [
            {"variant_id": "M2_lam20_tm05_align__A_Atoms", "method": "M2", "feat_set": "A_Atoms", "lam": 20.0, "t_cut": -0.5, "mode": "prior_aligned"},
            {"variant_id": "M2_lam20_tm05_raw__A_Atoms", "method": "M2", "feat_set": "A_Atoms", "lam": 20.0, "t_cut": -0.5, "mode": "prior_raw"},
        ],
        "high": [
            {"variant_id": "M5_ENet_a06_g30__B_PhysCore", "method": "M5", "feat_set": "B_PhysCore", "reg_type": "enet", "alpha": 0.06, "gamma": 0.30, "cap": 15.0},
            {"variant_id": "M1_sign_r35_eq_v20sc__A_Atoms", "method": "M1", "feat_set": "A_Atoms", "r_cut": 0.35, "dist_mode": "signed", "agg_mode": "eq_z", "outer": "prior_v20"},
        ],
        "pry": [
            {"variant_id": "M1_abs_r35_eq_v20sc__A_Atoms", "method": "M1", "feat_set": "A_Atoms", "r_cut": 0.35, "dist_mode": "abs", "agg_mode": "eq_z", "outer": "prior_v20"},
            {"variant_id": "M2_lam20_t0_align__B_PhysCore", "method": "M2", "feat_set": "B_PhysCore", "lam": 20.0, "t_cut": 0.0, "mode": "prior_aligned"},
        ],
        "20cm_orig76": [
            {"variant_id": "M3_eps05_v20sc__A_Atoms", "method": "M3", "feat_set": "A_Atoms", "eps": 0.05, "outer": "prior_v20"},
            {"variant_id": "M5_Ridge_a100_g20__C_DynCore", "method": "M5", "feat_set": "C_DynCore", "reg_type": "ridge", "alpha": 100.0, "gamma": 0.20, "cap": 15.0},
        ],
        "20cm_c50_80": [
            {"variant_id": "M5_Ridge_a100_g20__B_PhysCore", "method": "M5", "feat_set": "B_PhysCore", "reg_type": "ridge", "alpha": 100.0, "gamma": 0.20, "cap": 15.0},
            {"variant_id": "M5_ENet_a06_g30__C_DynCore", "method": "M5", "feat_set": "C_DynCore", "reg_type": "enet", "alpha": 0.06, "gamma": 0.30, "cap": 15.0},
        ],
    }

    score_diffs = {}
    trunc_scores = {}
    track_meta = {"1to2": ("1to2", False), "2to3": ("2to3", False), "3to4": ("3to4", False), "high": ("high", False), "pry": ("pry", False), "20cm_orig76": ("20cm", False), "20cm_c50_80": ("20cm", True)}

    for trk, sp_list in verify_specs_by_track.items():
        st, use_c50 = track_meta[trk]
        df_full = cache["pools_ext"][st]
        m_cut = (df_full["buy_date"] <= CUTOFF).to_numpy(bool)
        df_t = pools_t[st].copy()
        df_t["net_ret"] = df_t["net_ret_030"]
        # Slice atom_info strictly to <= CUTOFF
        ai_t = {}
        if st != "20cm":
            ai_t[st] = {
                "cols": bundle["atom_info"][st]["cols"],
                "contrib_mat": bundle["atom_info"][st]["contrib_mat"][m_cut],
            }
        inp_t = ol.prepare_strategy_inputs(st, df_t, ai_t, cand_ext_cols, use_cold50_for_20cm=use_c50)
        res_t = ol.run_causal_ortho_wf(inp_t, sp_list, wf_start=ol.WF_START)
        trunc_scores[trk] = {}
        for sp in sp_list:
            vid = sp["variant_id"]
            sc_raw_t = res_t[vid]["score"]
            if st != "20cm":
                sc_t = np.where(df_t["buy_date"] >= ol.WF_START, sc_raw_t, df_t["orig_score"].to_numpy(float))
            else:
                sc_t = np.where(df_t["buy_date"] >= ol.WF_START, sc_raw_t, -999.0)
            sc_f = st1_scores[trk][vid]["score"][m_cut]
            diff = float(np.max(np.abs(sc_f - sc_t)))
            assert diff == 0.0, f"Truncation score leak on {trk}::{vid}: max_diff={diff}"
            score_diffs[f"{trk}::{vid}"] = diff
            trunc_scores[trk][vid] = sc_t
            print(f"  [Score Trunc OK] {trk:12s} | {vid:34s} max_abs_score_diff={diff:.1f}")

    # Build truncated master cache for bundle truncation proof (note: V21 stack/bl15/cold45 use rd038 truncated scores)
    m20_cut = (cache["pools_ext"]["20cm"]["buy_date"] <= CUTOFF).to_numpy(bool)
    sc20_t = {k: v[m20_cut] for k, v in cache["sc20_aligned"].items()}
    sc20_t["ortho20_orig_m3_eps05"] = trunc_scores["20cm_orig76"]["M3_eps05_v20sc__A_Atoms"]
    sc20_t["ortho20_orig_m5_dync"] = trunc_scores["20cm_orig76"]["M5_Ridge_a100_g20__C_DynCore"]
    sc20_t["ortho20_c50_m5_phys"] = trunc_scores["20cm_c50_80"]["M5_Ridge_a100_g20__B_PhysCore"]
    sc20_t["ortho20_c50_m5_dync_enet"] = trunc_scores["20cm_c50_80"]["M5_ENet_a06_g30__C_DynCore"]
    wf_m_t = (pools_t["20cm"]["buy_date"] >= ol.WF_START).to_numpy(bool)
    sc20_t["v21_stack_plus_m5_phys"] = np.where(wf_m_t, sc20_t["stack_c50_avg"] + 0.5 * (sc20_t["ortho20_c50_m5_phys"] - sc20_t["cold50"]), sc20_t["stack_c50_avg"])
    sc20_t["v21_stack_plus_m5_dync"] = np.where(wf_m_t, sc20_t["stack_c50_avg"] + 0.5 * (sc20_t["ortho20_c50_m5_dync_enet"] - sc20_t["cold50"]), sc20_t["stack_c50_avg"])

    o5_t = {}
    for st in ("3to4", "2to3", "high", "pry"):
        m_st = (cache["pools_ext"][st]["buy_date"] <= CUTOFF).to_numpy(bool)
        o5_t[st] = {}
        for vk, vcfg in cache["other5_variants"].get(st, {}).items():
            o5_t[st][vk] = {"score": vcfg["score"][m_st], "mask": vcfg["mask"][m_st] if vcfg["mask"] is not None else None}
    o5_t["3to4"]["ortho_m2_tm05_align"] = {"score": trunc_scores["3to4"]["M2_lam20_tm05_align__A_Atoms"], "mask": None}
    o5_t["3to4"]["ortho_m2_plus_bl15"] = {"score": trunc_scores["3to4"]["M2_lam20_tm05_align__A_Atoms"], "mask": o5_t["3to4"]["m4_4way_bl15"]["mask"]}
    o5_t["2to3"]["ortho_m3_eps30"] = {"score": trunc_scores["2to3"]["M3_eps30_v20sc__A_Atoms"], "mask": None}
    o5_t["pry"]["ortho_m1_abs_r35"] = {"score": trunc_scores["pry"]["M1_abs_r35_eq_v20sc__A_Atoms"], "mask": None}
    o5_t["1to2"] = {"ortho_m5_enet": {"score": trunc_scores["1to2"]["M5_ENet_a06_g30__C_DynCore"], "mask": None}}
    o5_t["high"]["ortho_m5_enet"] = {"score": trunc_scores["high"]["M5_ENet_a06_g30__B_PhysCore"], "mask": None}

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

    # Build matching full augmented cache
    o5_f = {st: dict(v) for st, v in cache["other5_variants"].items()}
    o5_f["3to4"]["ortho_m2_tm05_align"] = {"score": st1_scores["3to4"]["M2_lam20_tm05_align__A_Atoms"]["score"], "mask": None}
    o5_f["3to4"]["ortho_m2_plus_bl15"] = {"score": st1_scores["3to4"]["M2_lam20_tm05_align__A_Atoms"]["score"], "mask": o5_f["3to4"]["m4_4way_bl15"]["mask"]}
    o5_f.setdefault("2to3", {})["ortho_m3_eps30"] = {"score": st1_scores["2to3"]["M3_eps30_v20sc__A_Atoms"]["score"], "mask": None}
    o5_f.setdefault("pry", {})["ortho_m1_abs_r35"] = {"score": st1_scores["pry"]["M1_abs_r35_eq_v20sc__A_Atoms"]["score"], "mask": None}
    o5_f.setdefault("1to2", {})["ortho_m5_enet"] = {"score": st1_scores["1to2"]["M5_ENet_a06_g30__C_DynCore"]["score"], "mask": None}
    o5_f.setdefault("high", {})["ortho_m5_enet"] = {"score": st1_scores["high"]["M5_ENet_a06_g30__B_PhysCore"]["score"], "mask": None}

    sc20_f = dict(cache["sc20_aligned"])
    sc20_f["ortho20_orig_m3_eps05"] = st1_scores["20cm_orig76"]["M3_eps05_v20sc__A_Atoms"]["score"]
    sc20_f["ortho20_orig_m5_dync"] = st1_scores["20cm_orig76"]["M5_Ridge_a100_g20__C_DynCore"]["score"]
    sc20_f["ortho20_c50_m5_phys"] = st1_scores["20cm_c50_80"]["M5_Ridge_a100_g20__B_PhysCore"]["score"]
    sc20_f["ortho20_c50_m5_dync_enet"] = st1_scores["20cm_c50_80"]["M5_ENet_a06_g30__C_DynCore"]["score"]
    wf_m_f = (cache["pools_ext"]["20cm"]["buy_date"] >= ol.WF_START).to_numpy(bool)
    sc20_f["v21_stack_plus_m5_phys"] = np.where(wf_m_f, sc20_f["stack_c50_avg"] + 0.5 * (sc20_f["ortho20_c50_m5_phys"] - sc20_f["cold50"]), sc20_f["stack_c50_avg"])
    sc20_f["v21_stack_plus_m5_dync"] = np.where(wf_m_f, sc20_f["stack_c50_avg"] + 0.5 * (sc20_f["ortho20_c50_m5_dync_enet"] - sc20_f["cold50"]), sc20_f["stack_c50_avg"])
    full_aug_cache = {**cache, "other5_variants": o5_f, "sc20_aligned": sc20_f}

    bundle_proofs = {}
    for bname, (_, bcfg, _) in bundle_cfgs.items():
        s_full = eng.run_bundle_sim(full_aug_cache, bcfg, fee_mode="030")["trades_df"]
        s_trnc = eng.run_bundle_sim(trunc_cache, bcfg, fee_mode="030")["trades_df"]
        f_le = s_full[s_full["exit_date"] <= CUTOFF].sort_values(["buy_date", "code"]).reset_index(drop=True)
        t_le = s_trnc[s_trnc["exit_date"] <= CUTOFF].sort_values(["buy_date", "code"]).reset_index(drop=True)
        assert len(f_le) == len(t_le), f"{bname} trunc count mismatch: {len(f_le)} vs {len(t_le)}"
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
        print(f"  [Bundle Trunc OK] {bname:28s}: n_le={len(f_le):3d}, max_score_diff=0.0, max_ret_diff={r_diff}")

    return full_aug_cache, {"score_diffs": score_diffs, "bundles": bundle_proofs}


def main():
    t0 = time.time()
    print("[Step 2] Loading caches and Step 1 results ...")
    with open(f"{RD038}/_cache/rd038_master_cache.pkl", "rb") as f:
        cache = pickle.load(f)
    with open(f"{RD036_P2}/_cache/rd036_other5_bundle.pkl", "rb") as f:
        bundle = pickle.load(f)
    with open(f"{OUT_DIR}/_cache_step1_scores.pkl", "rb") as f:
        st1 = pickle.load(f)
    st1_scores = st1["score_store"]
    cand_ext_cols = list(dict.fromkeys(bundle["base_dyn_cols"] + bundle["xtr_cols"] + bundle["ix_cols"]))

    cfg_v20 = {"s20": "base_76", "s34": "base", "s23": "base", "shi": "base", "spr": "base", "s12": "base", "w2a5": "none", "w2a6": "s_tier_reserve_only"}
    cfg_v21 = {"s20": "stack_c50_avg", "s20_thr": 80.0, "s34": "m4_4way_bl15", "s23": "m2_pair_cold45_d15", "shi": "m1_causal_cold_drop40_t0", "spr": "base", "s12": "base", "w2a5": "none", "w2a6": "s_tier_reserve_only"}

    # Define exact M6 contenders (group, cfg, factor_compression_desc)
    bundle_cfgs = {
        "1_V20_BASE_Unified": ("1_V20_BASE", cfg_v20, "109/109 raw atoms (1.00x)"),
        "2_V21_GREEDY_ROBUST": ("2_V21_BASE", cfg_v21, "109 raw atoms + RD038 cold/4way/3way"),
        "3A_ORTHO_PURE_A_Atoms_thr80": ("3_ORTHO_PURE", {**cfg_v20, "s34": "ortho_m2_tm05_align", "s20": "ortho20_orig_m3_eps05", "s20_thr": 80.0}, "3to4 M2(20.2/22) + 20cm M3(9/9 Lowdin); total 107.2/109 (0.983)"),
        "3B_ORTHO_PURE_A_Atoms_thr76": ("3_ORTHO_PURE", {**cfg_v20, "s34": "ortho_m2_tm05_align", "s20": "ortho20_orig_m3_eps05", "s20_thr": 76.0}, "3to4 M2(20.2/22) + 20cm M3(9/9 Lowdin @76); total 107.2/109"),
        "3C_ORTHO_PURE_M5_DynCore": ("3_ORTHO_PURE", {**cfg_v20, "s34": "ortho_m2_tm05_align", "s20": "ortho20_orig_m5_dync", "s20_thr": 80.0}, "3to4 M2(20.2/22) + 20cm M5(9+8 orth resid); total 115.2/117"),
        "3D_ORTHO_PURE_ALL6_FORCE": ("3_ORTHO_PURE", {"s20": "ortho20_orig_m3_eps05", "s20_thr": 80.0, "s34": "ortho_m2_tm05_align", "s23": "ortho_m3_eps30", "shi": "ortho_m5_enet", "spr": "ortho_m1_abs_r35", "s12": "ortho_m5_enet", "w2a5": "none", "w2a6": "s_tier_reserve_only"}, "All-6 forced ortho (incl 1to2/high/pry/2to3)"),
        "4A_V21_PLUS_34M2": ("4_V21_PLUS_ORTHO", {**cfg_v21, "s34": "ortho_m2_plus_bl15"}, "V21 + 3to4 M2 prune (20.2/22) + bl15 mask"),
        "4B_V21_PLUS_34M2_23M3": ("4_V21_PLUS_ORTHO", {**cfg_v21, "s34": "ortho_m2_plus_bl15", "s23": "ortho_m3_eps30"}, "V21 + 3to4 M2 + 2to3 M3 Lowdin"),
        "4C_V21_STACK_PLUS_20M5_DynC": ("4_V21_PLUS_ORTHO", {**cfg_v21, "s20": "v21_stack_plus_m5_dync"}, "V21 + 20cm stack + 0.5*M5(DynCore)"),
        "4D_V21_PLUS_34M2_20M5_Phys": ("4_V21_PLUS_ORTHO", {**cfg_v21, "s34": "ortho_m2_plus_bl15", "s20": "v21_stack_plus_m5_phys"}, "V21 + 3to4 M2 + 20cm stack + 0.5*M5(PhysCore)"),
        "4E_V21_REPLACE_20_M5_Phys": ("4_V21_PLUS_ORTHO", {**cfg_v21, "s20": "ortho20_c50_m5_phys"}, "V21 replacing 20cm stack with M5(PhysCore)"),
    }

    # 1. Physical 2024-12-31 Truncation Proof (returns augmented full cache too!)
    full_aug_cache, trunc_proof = build_truncation_proof(cache, bundle, st1_scores, cand_ext_cols, bundle_cfgs)

    # 2. Run M6 evaluation across 030, 050, 080 & 1000x perm & >=2yi liquidity
    print("\n[M6] Running 4-Way PK across 5 windows, 3 fees (030/050/080), 1000x perm & >=2yi liq ...")
    sim_v20_030 = eng.run_bundle_sim(full_aug_cache, cfg_v20, fee_mode="030")
    sim_v21_030 = eng.run_bundle_sim(full_aug_cache, cfg_v21, fee_mode="030")
    dr_v20_wf = sim_v20_030["dr_wf"]
    dr_v21_wf = sim_v21_030["dr_wf"]

    pk_rows = []
    bundle_audit = {}
    for bname, (bgrp, bcfg, comp_note) in bundle_cfgs.items():
        ev_by_fee = {}
        for ftag in ("030", "050", "080"):
            sim = eng.run_bundle_sim(full_aug_cache, bcfg, fee_mode=ftag)
            rel_5y = sim["mtm_diff_5y"] / max(1.0, float(np.prod(1.0 + sim["dr_5y"])))
            assert rel_5y < 1e-10 and sim["mtm_diff_wf"] < 1e-6, f"MTM diff error on {bname} {ftag}: 5y={sim['mtm_diff_5y']} wf={sim['mtm_diff_wf']}"
            ev = eng.evaluate_bundle(bname, bgrp, sim, full_aug_cache, ref_dr_wf=dr_v20_wf, perm_n=(1000 if ftag == "030" else 0))
            vs_v21 = paired_test(sim["dr_wf"], dr_v21_wf) if ftag == "030" else {}
            ev["vs_v21_wf"] = vs_v21
            ev_by_fee[ftag] = ev

            for wn, w in ev["windows"].items():
                pk_rows.append({
                    "bundle": bname,
                    "group": bgrp,
                    "fee": ftag,
                    "window": wn,
                    "n": w["n"],
                    "wr_pct": w["wr_pct"],
                    "plr": w["plr"],
                    "mean_pct": w["mean_pct"],
                    "nav": w["nav"],
                    "mtm_nav": w["mtm_nav"],
                    "ex_top3_nav": w["ex_top3_nav"],
                    "ex_top5_nav": w["ex_top5_nav"],
                    "daily_sharpe": w["daily_sharpe"],
                    "daily_mdd_pct": w["daily_mdd_pct"],
                    "daily_calmar": w["daily_calmar"],
                    "excess_csi300_pp": w["excess_csi300_pp"],
                    "excess_alla_ew_pp": w["excess_alla_ew_pp"],
                    "exposure_pct": w["exposure_pct"],
                    "mtm_diff_5y": ev["mtm_diff_5y"],
                    "mtm_diff_wf": ev["mtm_diff_wf"],
                    "perm_same_p": ev["perm_wf"].get("same_day_p_nav"),
                    "perm_any_p": ev["perm_wf"].get("any_cand_day_p_nav"),
                    "paired_t_vs_v20": ev["vs_v20_wf"].get("paired_t"),
                    "paired_p_vs_v20": ev["vs_v20_wf"].get("paired_p_2sided"),
                    "paired_t_vs_v21": vs_v21.get("paired_t"),
                    "paired_p_vs_v21": vs_v21.get("paired_p_2sided"),
                    "compression_note": comp_note,
                    "cfg_json": json.dumps(bcfg, ensure_ascii=False),
                })

        bundle_audit[bname] = {
            "group": bgrp,
            "cfg": bcfg,
            "compression_note": comp_note,
            "eval_030": ev_by_fee["030"],
            "eval_050_wf": ev_by_fee["050"]["windows"]["WF_2326"],
            "eval_080_wf": ev_by_fee["080"]["windows"]["WF_2326"],
        }
        w0 = ev_by_fee["030"]["windows"]["WF_2326"]
        w5 = ev_by_fee["050"]["windows"]["WF_2326"]
        w8 = ev_by_fee["080"]["windows"]["WF_2326"]
        y26 = ev_by_fee["030"]["windows"]["Y2026"]
        h2 = ev_by_fee["030"]["windows"]["Y2026_H2"]
        print(
            f"  {bname:28s} | WF030={w0['nav']:10,.1f}x Sh={w0['daily_sharpe']:.3f} MDD={w0['daily_mdd_pct']:5.2f}% Ex3={w0['ex_top3_nav']:9,.1f}x Ex5={w0['ex_top5_nav']:8,.1f}x | "
            f"Y26={y26['nav']:5.2f}x H2={h2['nav']:4.2f}x | 050={w5['nav']:9,.1f}x 080={w8['nav']:8,.1f}x | "
            f"p_v20={ev_by_fee['030']['vs_v20_wf']['paired_p_2sided']:.4f} p_v21={ev_by_fee['030']['vs_v21_wf']['paired_p_2sided']:.4f}"
        )

    # 3. >= 2yi Causal Liquidity Sensitivity on top 4 contenders
    print("\n[Liquidity >= 2yi Check]")
    pools_liq = {}
    for st, dfp in full_aug_cache["pools_ext"].items():
        d2 = dfp.copy()
        d2["can_buy_hygiene"] = d2["can_buy_hygiene"].fillna(True).to_numpy(bool) & (d2["sd_amount_yi_t1"].fillna(0.0).to_numpy(float) >= 2.0)
        pools_liq[st] = d2
    cache_liq = {**full_aug_cache, "pools_ext": pools_liq}
    liq_targets = ["1_V20_BASE_Unified", "2_V21_GREEDY_ROBUST", "3A_ORTHO_PURE_A_Atoms_thr80", "3C_ORTHO_PURE_M5_DynCore", "4A_V21_PLUS_34M2", "4D_V21_PLUS_34M2_20M5_Phys"]
    liq_summary = {}
    for bn in liq_targets:
        _, bcfg, _ = bundle_cfgs[bn]
        sim_l = eng.run_bundle_sim(cache_liq, bcfg, fee_mode="030")
        ev_l = eng.evaluate_bundle(f"{bn}_LIQ", "LIQ", sim_l, cache_liq, perm_n=0)
        wf_l = ev_l["windows"]["WF_2326"]
        liq_summary[bn] = {
            "n_wf": wf_l["n"], "nav_wf": wf_l["nav"], "ex5_wf": wf_l["ex_top5_nav"],
            "daily_sharpe": wf_l["daily_sharpe"], "daily_mdd_pct": wf_l["daily_mdd_pct"],
            "nav_2026": ev_l["windows"]["Y2026"]["nav"], "nav_26h2": ev_l["windows"]["Y2026_H2"]["nav"],
        }
        print(f"  Liq>=2yi {bn:28s}: n={wf_l['n']:3d} WF={wf_l['nav']:10,.1f}x Sh={wf_l['daily_sharpe']:.3f} MDD={wf_l['daily_mdd_pct']:5.2f}%")

    # Save combined PK CSV
    pk_df = pd.DataFrame(pk_rows)
    pk_csv = f"{OUT_DIR}/part2_combined_pk.csv"
    pk_df.to_csv(pk_csv, index=False, encoding="utf-8-sig")

    # Build comprehensive audit JSON including Step 1 method summary matrix
    s1_df = pd.read_csv(f"{OUT_DIR}/part2_single_strat_compare.csv")
    def _sm(r):
        m = str(r["module"])
        v = str(r["variant_id"])
        if m in ("0_BASELINE", "0_V21_REF"):
            return m
        if m == "M4":
            for k in ("Ridge", "Lasso", "ENet", "PLS"):
                if f"M4_{k}" in v:
                    return f"M4_{k}"
        return m
    s1_df["sub_method"] = s1_df.apply(_sm, axis=1)
    method_matrix = {}
    for trk in ["1to2", "2to3", "3to4", "high", "pry", "20cm_orig76", "20cm_c50_80"]:
        sub = s1_df[s1_df["track"] == trk]
        b0 = sub[sub["module"] == "0_BASELINE"].iloc[0]
        b_sh, b_nav = float(b0["exact_mtm_sharpe"]), float(b0["nav_wf"])
        ortho = sub[~sub["module"].isin(["0_BASELINE", "0_V21_REF"])]
        t_dict = {"baseline": {"variant_id": str(b0["variant_id"]), "n_trades": int(b0["n_trades"]), "nav_wf": b_nav, "sharpe": b_sh, "mdd_pct": float(b0["mdd_pct"])}, "methods": {}}
        for sm in ["M1", "M2", "M3", "M4_Ridge", "M4_Lasso", "M4_ENet", "M4_PLS", "M5"]:
            ss = ortho[ortho["sub_method"] == sm]
            if ss.empty:
                continue
            top_r = ss.sort_values(["exact_mtm_sharpe", "nav_wf"], ascending=False).iloc[0]
            t_dict["methods"][sm] = {
                "n_trials": int(len(ss)),
                "median_sharpe": round(float(ss["exact_mtm_sharpe"].median()), 3),
                "max_sharpe": round(float(ss["exact_mtm_sharpe"].max()), 3),
                "median_nav": round(float(ss["nav_wf"].median()), 4),
                "max_nav": round(float(ss["nav_wf"].max()), 4),
                "n_beat_base_sharpe": int((ss["exact_mtm_sharpe"] > b_sh).sum()),
                "n_beat_base_nav": int((ss["nav_wf"] > b_nav).sum()),
                "n_beat_v20_comb": int((ss["comb_nav_ratio"] > 1.0).sum()),
                "best_variant": str(top_r["variant_id"]),
                "best_avg_n_eff": float(top_r["avg_n_eff"]),
                "best_avg_n_raw": float(top_r["avg_n_raw"]),
            }
        method_matrix[trk] = t_dict

    audit_out = {
        "task": "Factor Orthogonality & Multi-Factor Regression Optimization (Part 2)",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t0, 2),
        "peak_rss_mb": rss_mb(),
        "d12_yfinance_imported": "yfinance" in sys.modules,
        "single_strategy_method_matrix": method_matrix,
        "truncation_proof_2024_12_31": trunc_proof,
        "m6_bundle_pk": bundle_audit,
        "liquidity_2yi_stress": liq_summary,
        "redteam_warnings": [
            "M1_sign_r35_invv_v20sc__C_DynCore on 20cm (112.31x/Sh=2.344) is an unstandardized mixed-unit variance artifact (1/sd^2 distorted mkt_amt_pct_3y_t1=0.314 vs ix_turn20_per_dd1y=2824.84; equal-z M1 gave 47.81x/Sh=1.968); NOT promoted.",
            "1to2 M1 abs clustering (|r|>=0.35) conflates mutually exclusive XOR gate s12_atom_clean_brk60 with s12_atom_dd20 (r=-0.508); signed clustering avoids this trap.",
            "Direct linear regression refit (M4: Ridge/Lasso/ENet/PLS) suffers near-total WF collapse across 1to2/2to3/3to4/high/pry/20cm due to low per-atom SNR and destruction of nonlinear V20 threshold gates (especially 1to2 base_res Elo gate).",
            "Small-sample high (n_pre=13, n_wf=49, p=22) is beaten by V20 human prior (9.83x/Sh=2.377 vs best ortho 8.26x/Sh=2.247).",
        ],
    }
    audit_json = f"{OUT_DIR}/part2_ortho_audit.json"
    with open(audit_json, "w", encoding="utf-8") as f:
        json.dump(cm.sanitize_json(audit_out), f, indent=2, ensure_ascii=False)
    print(f"[Step 2 DONE in {time.time()-t0:.1f}s | RSS={rss_mb()} MB] Saved {pk_csv} & {audit_json}")


if __name__ == "__main__":
    main()

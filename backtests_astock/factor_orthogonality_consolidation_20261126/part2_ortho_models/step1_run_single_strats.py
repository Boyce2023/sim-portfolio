#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Part 2 Step 1: Run 5 Multi-Factor Orthogonality & Regression Families (M1..M5)
across all 6 strategies (1to2, 2to3, 3to4, high, pry, 20cm + 20cm_c50) on 3 input sets:
  - A_Atoms: pure native atomic scoring factors
  - B_PhysCore: native atoms + 14 curated orthogonal physical core features
  - C_DynCore: native atoms + top-8 strictly causal (<t) low-correlation dynamic features

Strictly causal (exit_date < t). Exact close-to-close daily MTM. Zero yfinance (D12).
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import pickle
import resource
import sys
import time

import numpy as np
import pandas as pd

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


def rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 1)


def _eval_v20_comb_exact(
    cache: dict,
    strat: str,
    sc_vec: np.ndarray,
    s20_thr: float,
    base_v20_wf: dict,
) -> dict:
    """Plug single-strategy WF score vector into exact RD038 V20.0 unified 0.30% engine."""
    cfg_v20 = {"s20": "base_76", "s34": "base", "s23": "base", "shi": "base", "spr": "base", "s12": "base", "w2a5": "none", "w2a6": "s_tier_reserve_only"}
    o5_mod = {k: dict(v) for k, v in cache["other5_variants"].items()}
    sc20_mod = dict(cache["sc20_aligned"])
    if strat == "20cm":
        sc20_mod["__ortho_tmp__"] = sc_vec
        cfg_v20["s20"] = "__ortho_tmp__"
        cfg_v20["s20_thr"] = float(s20_thr)
    else:
        o5_mod.setdefault(strat, {})
        o5_mod[strat]["__ortho_tmp__"] = {"score": sc_vec, "mask": None}
        skey = {"3to4": "s34", "2to3": "s23", "high": "shi", "pry": "spr", "1to2": "s12"}[strat]
        cfg_v20[skey] = "__ortho_tmp__"
    c_tmp = {**cache, "other5_variants": o5_mod, "sc20_aligned": sc20_mod}
    sim = eng.run_bundle_sim(c_tmp, cfg_v20, fee_mode="030")
    ev = eng.evaluate_bundle("__tmp__", "TMP", sim, c_tmp, perm_n=0)
    wf = ev["windows"]["WF_2326"]
    y25 = ev["windows"]["Y2025_2026"]
    y26 = ev["windows"]["Y2026"]
    h2 = ev["windows"]["Y2026_H2"]
    return {
        "comb_nav_wf": wf["nav"],
        "comb_nav_ratio": round(wf["nav"] / max(1e-9, base_v20_wf["nav"]), 4),
        "comb_sharpe": wf["daily_sharpe"],
        "comb_sharpe_delta": round(wf["daily_sharpe"] - base_v20_wf["daily_sharpe"], 4),
        "comb_mdd_delta": round(wf["daily_mdd_pct"] - base_v20_wf["daily_mdd_pct"], 2),
        "comb_ex5_ratio": round(wf["ex_top5_nav"] / max(1e-9, base_v20_wf["ex_top5_nav"]), 4),
        "comb_2526_nav": y25["nav"],
        "comb_2026_nav": y26["nav"],
        "comb_26h2_nav": h2["nav"],
        "comb_mtm_diff": ev["mtm_diff_wf"],
    }


def main():
    t0 = time.time()
    print("[Step 1] Loading rd038_master_cache.pkl & rd036_other5_bundle.pkl ...")
    with open(f"{RD038}/_cache/rd038_master_cache.pkl", "rb") as f:
        cache = pickle.load(f)
    with open(f"{RD036_P2}/_cache/rd036_other5_bundle.pkl", "rb") as f:
        bundle = pickle.load(f)

    # Exact V20.0 combined baseline via RD038 engine
    cfg_v20 = {"s20": "base_76", "s34": "base", "s23": "base", "shi": "base", "spr": "base", "s12": "base", "w2a5": "none", "w2a6": "s_tier_reserve_only"}
    sim_v20 = eng.run_bundle_sim(cache, cfg_v20, fee_mode="030")
    ev_v20 = eng.evaluate_bundle("BASE_V20_Unified", "0_BASE", sim_v20, cache, perm_n=0)
    base_v20_wf = ev_v20["windows"]["WF_2326"]
    print(f"  [RD038 V20 Base OK] WF_nav={base_v20_wf['nav']:,.2f}x Sh={base_v20_wf['daily_sharpe']} MDD={base_v20_wf['daily_mdd_pct']}%")

    cand_ext_cols = list(dict.fromkeys(bundle["base_dyn_cols"] + bundle["xtr_cols"] + bundle["ix_cols"]))
    std_specs = ol.build_standard_spec_grid()

    all_rows = []
    score_store = {}  # track -> {vid: {"score": arr, "thr": float, "meta": ...}}

    tracks = [
        ("1to2", "1to2", False, None),
        ("2to3", "2to3", False, 90.0),
        ("3to4", "3to4", False, 90.0),
        ("high", "high", False, 88.0),
        ("pry", "pry", False, 165.0),
        ("20cm_orig76", "20cm", False, 76.0),
        ("20cm_c50_80", "20cm", True, 80.0),
    ]

    for track_name, st, use_c50, thr_val in tracks:
        t_st = time.time()
        df_pool = cache["pools_ext"][st].copy()
        df_pool["net_ret"] = df_pool["net_ret_030"]
        assert len(df_pool) == len(bundle["pools"][st])

        inp = ol.prepare_strategy_inputs(st, df_pool, bundle["atom_info"], cand_ext_cols, use_cold50_for_20cm=use_c50)
        specs_run = list(std_specs)
        if st == "1to2":
            specs_run.extend([
                {"variant_id": "M3_eps15_ridge50_noanchor__A_Atoms", "method": "M3", "feat_set": "A_Atoms", "eps": 0.15, "outer": "ridge", "alpha": 50.0, "anchor_1to2": False},
                {"variant_id": "M4_Ridge_a150_noanchor__A_Atoms", "method": "M4", "feat_set": "A_Atoms", "reg_type": "ridge", "alpha": 150.0, "anchor_1to2": False},
                {"variant_id": "M4_PLS_k3_noanchor__A_Atoms", "method": "M4", "feat_set": "A_Atoms", "reg_type": "pls", "n_comp": 3, "anchor_1to2": False},
            ])

        # First evaluate baselines for this track
        score_store[track_name] = {}
        base_variants = []
        if track_name == "20cm_orig76":
            base_variants.append(("BASE_V20_76", "0_BASELINE", df_pool["orig_score"].to_numpy(float), None, 76.0))
            base_variants.append(("BASE_V20_82", "0_BASELINE", df_pool["orig_score"].to_numpy(float), None, 82.0))
        elif track_name == "20cm_c50_80":
            base_variants.append(("BASE_COLD50_80", "0_BASELINE", cache["sc20_aligned"]["cold50"], None, 80.0))
            base_variants.append(("V21_STACK_C50_80", "0_V21_REF", cache["sc20_aligned"]["stack_c50_avg"], None, 80.0))
            base_variants.append(("RD036_BLEND_C50_80", "0_V21_REF", cache["sc20_aligned"]["blend_c50_half"], None, 80.0))
        else:
            base_variants.append(("BASE_V20", "0_BASELINE", df_pool["orig_score"].to_numpy(float), None, thr_val))
            for vk, vcfg in cache["other5_variants"].get(st, {}).items():
                base_variants.append((f"V21_REF_{vk}", "0_V21_REF", vcfg["score"], vcfg["mask"], thr_val))

        ref_dr_base = None
        for bname, bmod, bsc, bmsk, bthr in base_variants:
            _, sl_b = cm.sim_strategy(st, df_pool, bsc, thr=bthr, mask=bmsk, wf_only=True)
            row_b, dr_b = cm.evaluate_variant_complete(bundle, st, bmod, bname, sl_b, sl_b, perm_n=0, eval_comb=False, eval_liq=False)
            if ref_dr_base is None:
                ref_dr_base = dr_b
            comb_b = _eval_v20_comb_exact(cache, st, bsc, bthr if st == "20cm" else 80.0, base_v20_wf)
            row_b.update({
                "track": track_name, "feat_set": "RAW", "avg_n_raw": len(inp["acols"]), "avg_n_eff": len(inp["acols"]),
                "compression_ratio": 1.0, **comb_b,
            })
            all_rows.append(row_b)

        # Run all M1..M5 causal expanding models
        res_map = ol.run_causal_ortho_wf(inp, specs_run, wf_start=ol.WF_START)
        n_beat_base_nav = 0
        best_vid, best_sh, best_nav = "", -1.0, 0.0

        for sp in specs_run:
            vid = sp["variant_id"]
            rinfo = res_map[vid]
            sc_vec = rinfo["score"]
            # Ensure pre-WF (< 2023-01-03) strictly matches baseline orig_score for clean 5Y bundle compatibility
            if st != "20cm":
                sc_sim = np.where(df_pool["buy_date"] >= ol.WF_START, sc_vec, df_pool["orig_score"].to_numpy(float))
            else:
                sc_sim = np.where(df_pool["buy_date"] >= ol.WF_START, sc_vec, -999.0)

            _, sl_m = cm.sim_strategy(st, df_pool, sc_sim, thr=thr_val, wf_only=True)
            row_m, dr_m = cm.evaluate_variant_complete(bundle, st, sp["method"], vid, sl_m, sl_m, perm_n=0, eval_comb=False, eval_liq=False)
            # Recompute paired_t vs exact track baseline (especially critical for 20cm_orig76 & 20cm_c50_80)
            diff = dr_m - ref_dr_base
            sd_d = float(np.std(diff, ddof=1))
            pt = float(np.mean(diff) / (sd_d / np.sqrt(len(diff)))) if sd_d > 1e-12 else 0.0
            row_m["paired_t"] = round(pt, 3)

            comb_m = _eval_v20_comb_exact(cache, st, sc_sim, thr_val if st == "20cm" else 80.0, base_v20_wf)
            row_m.update({
                "track": track_name,
                "feat_set": sp["feat_set"],
                "avg_n_raw": rinfo["avg_n_raw"],
                "avg_n_eff": rinfo["avg_n_eff"],
                "compression_ratio": rinfo["compression_ratio"],
                **comb_m,
            })
            all_rows.append(row_m)
            score_store[track_name][vid] = {
                "score": sc_sim,
                "thr": thr_val,
                "avg_n_raw": rinfo["avg_n_raw"],
                "avg_n_eff": rinfo["avg_n_eff"],
                "compression_ratio": rinfo["compression_ratio"],
                "nav_wf": row_m["nav_wf"],
                "sharpe_wf": row_m["exact_mtm_sharpe"],
                "comb_nav_ratio": row_m["comb_nav_ratio"],
            }
            if row_m["exact_mtm_sharpe"] > best_sh:
                best_sh = row_m["exact_mtm_sharpe"]
                best_nav = row_m["nav_wf"]
                best_vid = vid

        base_row = [r for r in all_rows if r["track"] == track_name and r["module"] == "0_BASELINE"][0]
        print(
            f"  [{track_name:12s}] done in {time.time()-t_st:5.1f}s | Base: n={base_row['n_trades']} NAV={base_row['nav_wf']:7.2f}x Sh={base_row['exact_mtm_sharpe']:.3f} | "
            f"Best: {best_vid:42s} NAV={best_nav:7.2f}x Sh={best_sh:.3f}"
        )

    df_out = pd.DataFrame(all_rows)
    csv_path = f"{OUT_DIR}/part2_single_strat_compare.csv"
    df_out.to_csv(csv_path, index=False, encoding="utf-8-sig")
    with open(f"{OUT_DIR}/_cache_step1_scores.pkl", "wb") as f:
        pickle.dump({"score_store": score_store, "tracks": tracks}, f)
    print(f"[Step 1 DONE in {time.time()-t0:.1f}s | RSS={rss_mb()} MB] Saved {len(df_out)} rows -> {csv_path}")


if __name__ == "__main__":
    main()

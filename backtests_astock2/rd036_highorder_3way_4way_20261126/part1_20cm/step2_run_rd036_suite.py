#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD036-A Step 2: Execute Modules 1, 2, 3, and 4 on 20cm Deep-Open Strategy.
  - Module 1: Cold<40/45/50/55> x CLEAN_B(d8/10/15/20) x Mech130(d5/10/15/20) x Thr(78/80/82/84) + 3-way blends
  - Module 2: Causal 3-Way AND Gates (A&B&C, min_leaf=25, cluster synergy) + Depth=3 Shallow Trees (DT/GBDT)
  - Module 3: Causal 4-Way Expansion (min_leaf=20) + Depth=4 Shallow Trees (DT/GBDT) vs 3-Way
  - Module 4: Full Grid Exact MTM Sharpe, 50/80bps, >=2yi, Paired-t, Global/Family CSCV PBO, DSR(N_trials), 1000x Perm & V20.0 Combined

Zero yfinance (D12), Peak RSS < 2.0 GB, internal threads <= 2.
"""
import gc
import json
import os
import pickle
import resource
import sys
import time
import warnings

os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "2")

import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True
warnings.filterwarnings("ignore")

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd036_highorder_3way_4way_20261126/part1_20cm"
if OUT_DIR not in sys.path:
    sys.path.insert(0, OUT_DIR)

import rd036_lib as lib
import _wf_core as wfc
import _wf_sim_and_metrics as wfm

THRS = (78, 80, 82, 84)


def rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 1)


def run_mode_b_scorecard(df_h: pd.DataFrame, feat_cols: list[str], orig_col: str, max_delta: int, min_discrete_bin_cnt: int = 15, top_k: int = 10) -> tuple[np.ndarray, dict]:
    """Run causal Mode B delta_patch and return delta vector + metadata."""
    sc_df, meta_out = lib.w23.run_causal_scorecard_ext(
        df_h,
        feat_cols,
        mode="delta_patch",
        wf_start_date=lib.WF_START_DT,
        min_warmup_trades=80,
        top_k=top_k,
        min_k=5,
        max_corr=0.65,
        min_t_stat=1.0,
        shrink_tau=20.0,
        max_delta=max_delta,
        orig_score_col=orig_col,
        max_corr_orig=0.70,
        min_discrete_bin_cnt=min_discrete_bin_cnt,
    )
    return sc_df["wf_delta_score"].to_numpy(float), meta_out


def main():
    t_all = time.time()
    print("[RD036-A Step 2] Loading prebuilt PIT cache ...")
    p20 = pd.read_parquet(f"{OUT_DIR}/_cache_p20.parquet")
    with open(f"{OUT_DIR}/_cache_p20_segs.pkl", "rb") as f:
        seg_obj = pickle.load(f)
    with open(f"{OUT_DIR}/_cache_v20_comb_ctx.pkl", "rb") as f:
        v20_ctx = pickle.load(f)

    p20["segs_30"] = seg_obj["segs_30"]
    p20["segs_50"] = seg_obj["segs_50"]
    p20["segs_80"] = seg_obj["segs_80"]
    meta = seg_obj["meta"]
    del seg_obj
    gc.collect()

    wf_ctx = v20_ctx["wf_ctx"]
    bench_df = wf_ctx["bench"]
    base_comb = lib.w23.get_official_v20_comb_metrics(v20_ctx)

    df_h = p20.copy()
    df_h["wf_in_window"] = df_h["buy_date"] >= lib.WF_START_DT
    wf_cands = df_h[df_h["wf_in_window"]].copy()

    feat_cb = meta["feat_clean_b"]
    feat_ix = meta["ix_cols"]
    feat_union = meta["feat_union_cb_mech"]
    atomic_cols = meta["atomic_cols"]
    print(f"  Loaded p20={p20.shape}, CB={len(feat_cb)}, Mech={len(feat_ix)}, Union={len(feat_union)}, Atomic={len(atomic_cols)} | RSS={rss_mb()}MB")

    # Store all variant evaluations & daily MTM vectors for CSCV/DSR/paired-t
    all_evals = {}
    grid_rows = []
    dr_dict = {}
    score_cache = {}  # variant_name -> score vector (length len(df_h))

    def _eval_and_reg(name: str, family: str, score_vec: np.ndarray, thr: float, veto_mask=None):
        df_tmp = df_h[["buy_date", "exit_date", "code", "name", "buy_hhmm", "exit_hhmm",
                       "can_buy_hygiene", "wf_in_window", "net_ret", "net_ret_30", "net_ret_50", "net_ret_80",
                       "segs_30", "segs_50", "segs_80", "sd_amount_yi_t1", "v20_score"]].copy()
        df_tmp["_sc"] = score_vec
        ev = lib.evaluate_variant_fast(name, family, df_tmp, "_sc", float(thr), bench_df, wf_cands, veto_mask=veto_mask, perm_n=0, v20_comb_ctx=None)
        all_evals[name] = ev
        grid_rows.append(ev["row"])
        dr_dict[name] = ev["dr30"]
        score_cache[name] = (score_vec, float(thr), veto_mask)

    # =========================================================================
    # MODULE 1: Cold<40/45/50/55> x CLEAN_B x Mech130 x Thr + 3-Way Combos
    # =========================================================================
    t_m1 = time.time()
    print("\n=== [Module 1] Cold-Day x CLEAN_B x Mech130 Full Neighborhood & Superposition ===")
    # 1.1 Baselines & Pure Cold
    for thr in THRS:
        _eval_and_reg(f"BASE_V11_S{thr}", "0_BASELINE", df_h["v20_score"].to_numpy(float), thr)
    for cut in (40, 45, 50, 55):
        for thr in THRS:
            _eval_and_reg(f"COLD{cut}_S{thr}", "1A_PURE_COLD", df_h[f"v20_cold{cut}"].to_numpy(float), thr)

    # 1.2 CLEAN_B across v20 & cold40/45/50/55 x d{8,10,15,20} (batched single-pass!)
    orig_map = {"v20": "v20_score", "cold40": "v20_cold40", "cold45": "v20_cold45", "cold50": "v20_cold50", "cold55": "v20_cold55"}
    dm_cb, cb_cards = lib.run_mode_b_multi_grid(
        df_h, feat_cb, list(orig_map.values()), deltas=(8, 10, 15, 20), min_discrete_bin_cnt=15, top_k=10
    )
    cb_deltas = {}
    for btag, orig_c in orig_map.items():
        for md in (8, 10, 15, 20):
            dv = dm_cb[(orig_c, md)]
            cb_deltas[(btag, md)] = dv
            sc_v = df_h[orig_c].to_numpy(float) + dv
            fam = "1B_CLEANB_V20" if btag == "v20" else f"1B_CLEANB_{btag.upper()}"
            for thr in THRS:
                _eval_and_reg(f"CLEANB_{btag}_d{md}_S{thr}", fam, sc_v, thr)
    print(f"  1.2 CLEAN_B 80 variants done ({time.time()-t_m1:.1f}s)")

    # 1.3 Mech130 (Native min_bin=0 & Clean min_bin=15) across v20 & cold40/45/50/55 x d{5,10,15,20}
    t_m13 = time.time()
    dm_mn, mech_nat_cards = lib.run_mode_b_multi_grid(
        df_h, feat_ix, list(orig_map.values()), deltas=(5, 10, 15, 20), min_discrete_bin_cnt=0, top_k=10
    )
    dm_mc, mech_cln_cards = lib.run_mode_b_multi_grid(
        df_h, feat_ix, ["v20_score", "v20_cold45", "v20_cold50"], deltas=(5, 10, 15, 20), min_discrete_bin_cnt=15, top_k=10
    )
    mech_nat_deltas, mech_cln_deltas = {}, {}
    for btag, orig_c in orig_map.items():
        for md in (5, 10, 15, 20):
            dv_n = dm_mn[(orig_c, md)]
            mech_nat_deltas[(btag, md)] = dv_n
            sc_vn = df_h[orig_c].to_numpy(float) + dv_n
            fam_n = "1C_MECHNAT_V20" if btag == "v20" else f"1C_MECHNAT_{btag.upper()}"
            for thr in THRS:
                _eval_and_reg(f"MechNat_{btag}_d{md}_S{thr}", fam_n, sc_vn, thr)
            if btag in ("v20", "cold45", "cold50"):
                dv_c = dm_mc[(orig_c, md)]
                mech_cln_deltas[(btag, md)] = dv_c
                sc_vc = df_h[orig_c].to_numpy(float) + dv_c
                fam_c = "1C_MECHCLN_V20" if btag == "v20" else f"1C_MECHCLN_{btag.upper()}"
                for thr in THRS:
                    _eval_and_reg(f"MechClean_{btag}_d{md}_S{thr}", fam_c, sc_vc, thr)
    print(f"  1.3 Mech130 128 variants done ({time.time()-t_m13:.1f}s)")

    # 1.4 Three-way Superposition: Cold + CLEAN_B + Mech130 (Unified Pool, Additive Blends, Sequential Residual)
    t_m14 = time.time()
    dm_u10, u10_cards = lib.run_mode_b_multi_grid(
        df_h, feat_union, ["v20_score", "v20_cold45", "v20_cold50"], deltas=(8, 10, 15, 20), min_discrete_bin_cnt=15, top_k=10
    )
    dm_u12, u12_cards = lib.run_mode_b_multi_grid(
        df_h, feat_union, ["v20_cold50"], deltas=(8, 10, 15, 20), min_discrete_bin_cnt=15, top_k=12
    )
    union_deltas = {}
    for btag, orig_c in [("v20", "v20_score"), ("cold45", "v20_cold45"), ("cold50", "v20_cold50")]:
        for md in (8, 10, 15, 20):
            dv_u = dm_u10[(orig_c, md)]
            union_deltas[(btag, md, 10)] = dv_u
            sc_u = df_h[orig_c].to_numpy(float) + dv_u
            for thr in THRS:
                _eval_and_reg(f"Union10_CB_Mech_{btag}_d{md}_S{thr}", "1D_UNION_CB_MECH", sc_u, thr)
            if btag == "cold50":
                dv_u12 = dm_u12[(orig_c, md)]
                union_deltas[(btag, md, 12)] = dv_u12
                for thr in THRS:
                    _eval_and_reg(f"Union12_CB_Mech_{btag}_d{md}_S{thr}", "1D_UNION_CB_MECH", df_h[orig_c].to_numpy(float) + dv_u12, thr)

    # Additive & Ratio Blends on Cold50
    c50_base = df_h["v20_cold50"].to_numpy(float)
    blend_specs = [
        ("Blend_c50_CB15_MN10_uncap", cb_deltas[("cold50", 15)] + mech_nat_deltas[("cold50", 10)]),
        ("Blend_c50_CB15_MN15_uncap", cb_deltas[("cold50", 15)] + mech_nat_deltas[("cold50", 15)]),
        ("Blend_c50_CB10_MN10_uncap", cb_deltas[("cold50", 10)] + mech_nat_deltas[("cold50", 10)]),
        ("Blend_c50_CB15_MN10_cap20", np.clip(cb_deltas[("cold50", 15)] + mech_nat_deltas[("cold50", 10)], -20.0, 20.0)),
        ("Blend_c50_CB15_MN15_cap20", np.clip(cb_deltas[("cold50", 15)] + mech_nat_deltas[("cold50", 15)], -20.0, 20.0)),
        ("Blend_c50_CB15_MC10_cap20", np.clip(cb_deltas[("cold50", 15)] + mech_cln_deltas[("cold50", 10)], -20.0, 20.0)),
        ("Blend_c50_Half_CB15_MN15", np.round(0.5 * cb_deltas[("cold50", 15)] + 0.5 * mech_nat_deltas[("cold50", 15)])),
        ("Blend_c50_Half_CB15_MC15", np.round(0.5 * cb_deltas[("cold50", 15)] + 0.5 * mech_cln_deltas[("cold50", 15)])),
        ("Blend_c50_Half_CB10_MN10", np.round(0.5 * cb_deltas[("cold50", 10)] + 0.5 * mech_nat_deltas[("cold50", 10)])),
    ]
    # Sequential residual: first CB15 on cold50, then Mech130 on (cold50 + CB15)
    df_seq = df_h.copy()
    df_seq["v20_c50_cb15"] = c50_base + cb_deltas[("cold50", 15)]
    dv_seq_m10, _ = run_mode_b_scorecard(df_seq, feat_ix, "v20_c50_cb15", 10, min_discrete_bin_cnt=15, top_k=8)
    dv_seq_m10_nat, _ = run_mode_b_scorecard(df_seq, feat_ix, "v20_c50_cb15", 10, min_discrete_bin_cnt=0, top_k=8)
    blend_specs.append(("SeqRes_c50_CB15_then_MC10", cb_deltas[("cold50", 15)] + dv_seq_m10))
    blend_specs.append(("SeqRes_c50_CB15_then_MN10", cb_deltas[("cold50", 15)] + dv_seq_m10_nat))
    del df_seq

    for bname, dvec in blend_specs:
        for thr in THRS:
            _eval_and_reg(f"{bname}_S{thr}", "1E_BLEND_CB_MECH", c50_base + dvec, thr)
    print(f"  1.4 Superposition blends done ({time.time()-t_m14:.1f}s) | Total variants so far: {len(grid_rows)} | RSS={rss_mb()}MB")

    # =========================================================================
    # MODULE 2 & 3: 3-Way AND + Shallow Trees D3 + 4-Way AND + Trees D4
    # =========================================================================
    t_m2 = time.time()
    print("\n=== [Modules 2 & 3] Causal 3-Way AND + Depth=3 Trees + 4-Way Expansion + Depth=4 Trees ===")
    ho_res = lib.run_causal_highorder_and_tree_wf(
        df_h,
        atomic_cols=atomic_cols,
        extra_static_cols=feat_union,
        wf_start_date=lib.WF_START_DT,
        min_warmup_trades=80,
        deltas=(8, 12, 15),
        enable_4way=True,
    )
    print(f"  High-order + Trees WF loop finished in {time.time()-t_m2:.1f}s (rebuilds={ho_res['n_rebuilds']}) | RSS={rss_mb()}MB")

    v20_arr = df_h["v20_score"].to_numpy(float)
    for base_tag, b_arr in [("v20", v20_arr), ("cold50", c50_base)]:
        # 3-Way & 4-Way & Static+3Way rule scorecards
        for mname, fam in [("Rule3Way", "2A_3WAY_AND"), ("Rule4Way", "3A_4WAY_AND"), ("Rule3Way_Static", "2C_STACK_UNION_3W")]:
            for d_cap in (8, 12, 15):
                dv = ho_res["rule_deltas"][(mname, d_cap)]
                for thr in THRS:
                    _eval_and_reg(f"{mname}_{base_tag}_d{d_cap}_S{thr}", fam, b_arr + dv, thr)

        # Shallow Trees (DT_D3, GBDT_D3, DT_D4, GBDT_D4)
        for tname, fam in [("DT_D3", "2B_TREE_D3"), ("GBDT_D3", "2B_TREE_D3"), ("DT_D4", "3B_TREE_D4"), ("GBDT_D4", "3B_TREE_D4")]:
            z_arr = np.nan_to_num(ho_res["raw_z"][tname], nan=0.0)
            for d_cap in (8, 12, 15):
                dv_tree = np.round(z_arr * float(d_cap))
                for thr in THRS:
                    _eval_and_reg(f"{tname}_{base_tag}_d{d_cap}_S{thr}", fam, b_arr + dv_tree, thr)

    # Grand Composite Stacks on Cold50 (Module 4 required combos: Cold50+NewFactor+Mech+3Way etc.)
    d_3w_8 = ho_res["rule_deltas"][("Rule3Way", 8)]
    d_3w_12 = ho_res["rule_deltas"][("Rule3Way", 12)]
    d_4w_8 = ho_res["rule_deltas"][("Rule4Way", 8)]
    d_gb3_8 = np.round(np.nan_to_num(ho_res["raw_z"]["GBDT_D3"], nan=0.0) * 8.0)
    d_gb3_12 = np.round(np.nan_to_num(ho_res["raw_z"]["GBDT_D3"], nan=0.0) * 12.0)

    stack_specs = [
        ("Stack_c50_CB15_Rule3W8_uncap", cb_deltas[("cold50", 15)] + d_3w_8),
        ("Stack_c50_CB15_Rule3W8_cap20", np.clip(cb_deltas[("cold50", 15)] + d_3w_8, -20.0, 20.0)),
        ("Stack_c50_MN10_Rule3W8_cap20", np.clip(mech_nat_deltas[("cold50", 10)] + d_3w_8, -20.0, 20.0)),
        ("Stack_c50_CB15_MN10_Rule3W8_uncap", cb_deltas[("cold50", 15)] + mech_nat_deltas[("cold50", 10)] + d_3w_8),
        ("Stack_c50_CB15_MN10_Rule3W8_cap20", np.clip(cb_deltas[("cold50", 15)] + mech_nat_deltas[("cold50", 10)] + d_3w_8, -20.0, 20.0)),
        ("Stack_c50_Avg_CB15_MN15_R3W12", np.round((cb_deltas[("cold50", 15)] + mech_nat_deltas[("cold50", 15)] + d_3w_12) / 3.0)),
        ("Stack_c50_Blend_Union15_R3W12", np.round(0.6 * union_deltas[("cold50", 15, 10)] + 0.4 * d_3w_12)),
        ("Stack_c50_CB15_GBDT3_8_uncap", cb_deltas[("cold50", 15)] + d_gb3_8),
        ("Stack_c50_CB15_GBDT3_8_cap20", np.clip(cb_deltas[("cold50", 15)] + d_gb3_8, -20.0, 20.0)),
        ("Stack_c50_CB15_MN10_GBDT3_8_cap20", np.clip(cb_deltas[("cold50", 15)] + mech_nat_deltas[("cold50", 10)] + d_gb3_8, -20.0, 20.0)),
        ("Stack_c50_CB15_Rule4W8_cap20", np.clip(cb_deltas[("cold50", 15)] + d_4w_8, -20.0, 20.0)),
    ]
    for sname, dvec in stack_specs:
        for thr in THRS:
            _eval_and_reg(f"{sname}_S{thr}", "4_GRAND_STACK", c50_base + dvec, thr)

    print(f"  All grid variants evaluated: N_trials_grid = {len(grid_rows)} | RSS={rss_mb()}MB")

    # =========================================================================
    # MODULE 4: Statistical Tests (Paired-t, DSR, CSCV PBO, 1000x Perm, V20 Comb)
    # =========================================================================
    t_m4 = time.time()
    print("\n=== [Module 4] Computing Paired-t, DSR, Global/Family CSCV PBO, 1000x Perm & V20 Comb ===")
    n_trials_grid = len(grid_rows)
    grid_names = [r["variant"] for r in grid_rows]
    dr_mat = np.column_stack([dr_dict[nm] for nm in grid_names])  # (936, N_grid)
    grid_daily_srs = [
        float(np.mean(dr_mat[:, j]) / np.std(dr_mat[:, j], ddof=1)) if np.std(dr_mat[:, j], ddof=1) > 1e-12 else 0.0
        for j in range(n_trials_grid)
    ]

    # Global CSCV PBO (S=10 -> 252 splits, S=8 -> 70 splits)
    cscv_global_s10 = lib.compute_cscv_pbo(dr_mat, grid_names, n_blocks=10)
    cscv_global_s8 = lib.compute_cscv_pbo(dr_mat, grid_names, n_blocks=8)
    print(f"  Global CSCV PBO (N={n_trials_grid}): S=10 -> {cscv_global_s10['pbo_pct']}% (med OOS rank={cscv_global_s10['median_oos_pct_rank']}%), S=8 -> {cscv_global_s8['pbo_pct']}%")

    # Family-level CSCV PBO
    cscv_by_family = {}
    df_grid = pd.DataFrame(grid_rows)
    for fam, grp in df_grid.groupby("family"):
        f_names = grp["variant"].tolist()
        if len(f_names) >= 3:
            f_mat = np.column_stack([dr_dict[nm] for nm in f_names])
            cscv_by_family[fam] = lib.compute_cscv_pbo(f_mat, f_names, n_blocks=10)

    # Compute Paired-t vs BASE_V11_S82 & BASE_V11_S80 + DSR for ALL rows
    dr_b82 = dr_dict["BASE_V11_S82"]
    dr_b80 = dr_dict["BASE_V11_S80"]
    slot_b82 = all_evals["BASE_V11_S82"]["slot_df"]
    slot_b80 = all_evals["BASE_V11_S80"]["slot_df"]

    stat_cols = []
    for r in grid_rows:
        nm = r["variant"]
        st82 = lib.compute_paired_t_and_dsr(dr_dict[nm], dr_b82, all_evals[nm]["slot_df"], slot_b82, n_trials_grid, grid_daily_srs)
        st80 = lib.compute_paired_t_and_dsr(dr_dict[nm], dr_b80, all_evals[nm]["slot_df"], slot_b80, n_trials_grid, grid_daily_srs)
        r["t_vs_s82"] = st82["t_daily_mtm_vs_base"]
        r["p_vs_s82_2s"] = st82["p_daily_mtm_2s"]
        r["t_vs_s80"] = st80["t_daily_mtm_vs_base"]
        r["p_vs_s80_2s"] = st80["p_daily_mtm_2s"]
        r["dsr_grid_N"] = st82["dsr_exact_grid_N"]
        r["dsr_null_N"] = st82["dsr_null_grid_N"]
        r["dsr_null_500"] = st82["dsr_null_N500"]
        r["dsr_null_2000"] = st82["dsr_null_N2000"]
        r["fam_pbo_pct"] = cscv_by_family.get(r["family"], {}).get("pbo_pct", np.nan)
        stat_cols.append((nm, st82, st80))

    df_grid = pd.DataFrame(grid_rows)

    # Select key benchmarks + top candidates from EVERY family for expensive 1000x perm & V20.0 Combined check
    must_check = [
        "BASE_V11_S82", "BASE_V11_S80", "BASE_V11_S78", "BASE_V11_S84",
        "COLD50_S80", "COLD50_S82", "COLD50_S78", "COLD50_S84", "COLD45_S80",
        "CLEANB_v20_d15_S80", "CLEANB_cold50_d15_S80", "CLEANB_cold50_d15_S84", "CLEANB_cold50_d15_S78",
        "MechNat_v20_d10_S82", "MechNat_v20_d15_S82", "MechNat_cold50_d10_S80", "MechNat_cold50_d15_S80", "MechNat_cold50_d20_S80",
        "MechClean_cold50_d15_S80", "MechClean_cold50_d20_S80",
    ]
    # Add top 3 by sharpe_wf and top 3 by nav_wf (with n_wf >= 80) from each major family
    for fam in ["1D_UNION_CB_MECH", "1E_BLEND_CB_MECH", "2A_3WAY_AND", "2B_TREE_D3", "2C_STACK_UNION_3W", "3A_4WAY_AND", "3B_TREE_D4", "4_GRAND_STACK"]:
        sub = df_grid[(df_grid["family"] == fam) & (df_grid["n_wf"] >= 75)]
        if not sub.empty:
            must_check.extend(sub.sort_values("sharpe_wf", ascending=False)["variant"].head(3).tolist())
            must_check.extend(sub.sort_values("nav_wf", ascending=False)["variant"].head(3).tolist())
    # Also add global top 10 by Sharpe & top 10 by NAV (with n_wf >= 80)
    sub_all = df_grid[df_grid["n_wf"] >= 80]
    must_check.extend(sub_all.sort_values("sharpe_wf", ascending=False)["variant"].head(8).tolist())
    must_check.extend(sub_all.sort_values("nav_wf", ascending=False)["variant"].head(8).tolist())
    must_check = list(dict.fromkeys([m for m in must_check if m in all_evals]))

    print(f"  Running 1000x Perm + V20.0 Combined replacement on {len(must_check)} finalists ...")
    finalist_details = {}
    perm_map = {}
    comb_map = {}
    for idx_m, nm in enumerate(must_check):
        slot_df = all_evals[nm]["slot_df"]
        pm = wfm.perm_test_trading_days(slot_df, wf_cands, lib.WF_START_DT, lib.WF_END_DT, n_perm=1000, seed=20261126)
        cm = lib.w23.eval_v20_combined_replacement(v20_ctx, slot_df, wf_start_dt=lib.WF_START_DT, end_dt=lib.WF_END_DT)
        perm_map[nm] = pm
        comb_map[nm] = cm

        row_base = df_grid[df_grid["variant"] == nm].iloc[0].to_dict()
        cw, c2526, ch2 = cm["FULL_WF"], cm["Y2025_2026"], cm["Y2026H2"]
        finalist_details[nm] = {
            **row_base,
            "perm_1000": pm,
            "v20_comb": {
                "full_wf": cw,
                "y2025_2026": c2526,
                "y2026": cm["Y2026"],
                "y2026h2": ch2,
                "comb_wf_nav_ratio": round(cw["nav"] / max(1e-9, base_comb["FULL_WF"]["nav"]), 4),
                "comb_2526_nav_ratio": round(c2526["nav"] / max(1e-9, base_comb["Y2025_2026"]["nav"]), 4),
                "comb_26h2_nav_ratio": round(ch2["nav"] / max(1e-9, base_comb["Y2026H2"]["nav"]), 4),
            },
        }
        if (idx_m + 1) % 15 == 0:
            print(f"    ... {idx_m+1}/{len(must_check)} finalists evaluated ({time.time()-t_m4:.1f}s)")

    # Attach perm_1000 and comb columns back to df_grid where evaluated
    df_grid["perm_sd_p"] = df_grid["variant"].map(lambda x: perm_map[x]["same_day_p_nav"] if x in perm_map else np.nan)
    df_grid["perm_any_p"] = df_grid["variant"].map(lambda x: perm_map[x]["any_cand_day_p_nav"] if x in perm_map else np.nan)
    df_grid["comb_wf_nav"] = df_grid["variant"].map(lambda x: comb_map[x]["FULL_WF"]["nav"] if x in comb_map else np.nan)
    df_grid["comb_wf_nav_ratio"] = df_grid["variant"].map(lambda x: round(comb_map[x]["FULL_WF"]["nav"] / base_comb["FULL_WF"]["nav"], 4) if x in comb_map else np.nan)
    df_grid["comb_wf_mdd"] = df_grid["variant"].map(lambda x: comb_map[x]["FULL_WF"]["daily_mdd_pct"] if x in comb_map else np.nan)
    df_grid["comb_wf_sharpe"] = df_grid["variant"].map(lambda x: comb_map[x]["FULL_WF"]["daily_sharpe"] if x in comb_map else np.nan)
    df_grid["comb_wf_n20"] = df_grid["variant"].map(lambda x: comb_map[x]["FULL_WF"]["n_20cm"] if x in comb_map else np.nan)
    df_grid["comb_2526_nav"] = df_grid["variant"].map(lambda x: comb_map[x]["Y2025_2026"]["nav"] if x in comb_map else np.nan)
    df_grid["comb_26h2_nav"] = df_grid["variant"].map(lambda x: comb_map[x]["Y2026H2"]["nav"] if x in comb_map else np.nan)

    df_grid.to_csv(f"{OUT_DIR}/rd036_20cm_grid.csv", index=False)

    # Save top rules CSV (3-way & 4-way rules across monthly snapshots + latest rules + DT_D3 leaves)
    top_rules_rows = []
    latest_st = ho_res["latest_state"]
    latest_3w_lu = {r["name"]: r for r in latest_st["res_ho"]["rules_3way"]}
    latest_4w_lu = {r["name"]: r for r in latest_st["res_ho"]["rules_4way"]}
    n_sn_m = max(1, len(ho_res["tree_rule_snaps"]))
    for rname, cnt in sorted(ho_res["rule_freq_3w"].items(), key=lambda kv: (-kv[1], kv[0])):
        lr = latest_3w_lu.get(rname, {})
        top_rules_rows.append({
            "order": 3, "rule_name": rname, "appear_months": cnt, "appear_pct": round(cnt / n_sn_m * 100.0, 1),
            "latest_cnt": lr.get("cnt", np.nan), "latest_wr_pct": lr.get("win_rate_pct", np.nan),
            "latest_mean_pct": lr.get("mean_ret_pct", np.nan), "latest_crash_m7_pct": lr.get("crash_m7_pct", np.nan),
            "latest_t": lr.get("t_cluster", np.nan), "latest_t_synergy": lr.get("t_anova_synergy", np.nan),
            "latest_min_cond_t": lr.get("min_cond_t", np.nan),
        })
    for rname, cnt in sorted(ho_res["rule_freq_4w"].items(), key=lambda kv: (-kv[1], kv[0])):
        lr = latest_4w_lu.get(rname, {})
        top_rules_rows.append({
            "order": 4, "rule_name": rname, "appear_months": cnt, "appear_pct": round(cnt / n_sn_m * 100.0, 1),
            "latest_cnt": lr.get("cnt", np.nan), "latest_wr_pct": lr.get("win_rate_pct", np.nan),
            "latest_mean_pct": lr.get("mean_ret_pct", np.nan), "latest_crash_m7_pct": lr.get("crash_m7_pct", np.nan),
            "latest_t": lr.get("t_cluster", np.nan), "latest_t_synergy": lr.get("t_4vs3_synergy", np.nan),
            "latest_min_cond_t": np.nan,
        })
    pd.DataFrame(top_rules_rows).to_csv(f"{OUT_DIR}/rd036_20cm_top_rules.csv", index=False, encoding="utf-8-sig")

    # Identify Top 3 winners (among n_wf >= 80, non-baseline, balanced Sharpe + Ex5 + 2526 + V20 Comb)
    # Rank by composite score of Sharpe, Ex5, 2526 NAV, and Comb NAV Ratio, excluding exact baseline duplicates
    cand_f = df_grid[(df_grid["n_wf"] >= 80) & (df_grid["variant"].isin(must_check)) & (~df_grid["family"].isin(["0_BASELINE", "1A_PURE_COLD"]))].copy()
    cand_f["comb_score"] = (
        cand_f["sharpe_wf"].rank(pct=True) * 0.30
        + cand_f["ex5_wf"].rank(pct=True) * 0.25
        + cand_f["nav_2526"].rank(pct=True) * 0.20
        + cand_f["comb_wf_nav_ratio"].fillna(1.0).rank(pct=True) * 0.25
    )
    cand_f = cand_f.sort_values("comb_score", ascending=False)
    top_winners = cand_f["variant"].head(8).tolist()
    best_nm = top_winners[0]

    # Save best trades parquet
    best_slot_df = all_evals[best_nm]["slot_df"].copy()
    keep_tr_cols = [c for c in ["buy_date", "exit_date", "code", "name", "v20_score", "score", "net_ret_30", "net_ret_50", "net_ret_80", "sd_amount_yi_t1"] if c in best_slot_df.columns]
    best_slot_df[keep_tr_cols].to_parquet(f"{OUT_DIR}/rd036_20cm_best_trades.parquet", index=False)

    # Save intermediate suite summary for Step 3 (physical truncation verification + final audit assembly)
    suite_out = lib.sanitize_json({
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t_all, 2),
        "peak_rss_mb": rss_mb(),
        "n_trials_grid": n_trials_grid,
        "v20_official_comb_baseline": base_comb,
        "cscv_global_s10": cscv_global_s10,
        "cscv_global_s8": cscv_global_s8,
        "cscv_by_family_s10": cscv_by_family,
        "must_check_finalists": finalist_details,
        "top_ranked_winners": top_winners,
        "best_winner": best_nm,
        "latest_3way_rules": [{k: v for k, v in r.items() if k != "abc_idx"} for r in latest_st["res_ho"]["rules_3way"]],
        "latest_4way_rules": latest_st["res_ho"]["rules_4way"],
        "latest_dt_d3_rules": ho_res["tree_rule_snaps"][-1] if ho_res["tree_rule_snaps"] else {},
        "latest_scorecards": {
            "CLEANB_cold50_d15": cb_cards["v20_cold50_d15"],
            "MechNat_cold50_d10": mech_nat_cards["v20_cold50_d10"],
            "MechNat_cold50_d20": mech_nat_cards["v20_cold50_d20"],
            "MechClean_cold50_d15": mech_cln_cards["v20_cold50_d15"],
            "Union10_cold50_d15": u10_cards["v20_cold50_d15"],
            "Union12_cold50_d15": u12_cards["v20_cold50_d15"],
            "Rule3Way_d12": latest_st["cards_ho"][("Rule3Way", 12)],
            "Rule3Way_Static_d15": latest_st["cards_ho"][("Rule3Way_Static", 15)],
            "Rule4Way_d12": latest_st["cards_ho"][("Rule4Way", 12)],
        },
    })
    with open(f"{OUT_DIR}/_suite_interim.json", "w", encoding="utf-8") as f:
        json.dump(suite_out, f, ensure_ascii=False, indent=2, allow_nan=False)

    print(f"\n[Step 2 DONE in {time.time()-t_all:.1f}s | Peak RSS={rss_mb()}MB]")
    print("=== TOP 15 BY SHARPE_WF (n_wf >= 80) ===")
    cols_p = ["variant", "family", "n_wf", "wr_wf", "nav_wf", "ex5_wf", "mdd_wf", "sharpe_wf", "nav_2526", "nav_80bps", "dsr_grid_N", "t_vs_s82", "comb_wf_nav_ratio"]
    print(df_grid[df_grid["n_wf"] >= 80].sort_values("sharpe_wf", ascending=False)[cols_p].head(15).to_string(index=False))
    print("\n=== TOP 15 FINALISTS BY COMPOSITE SCORE ===")
    print(cand_f[cols_p].head(15).to_string(index=False))


if __name__ == "__main__":
    main()

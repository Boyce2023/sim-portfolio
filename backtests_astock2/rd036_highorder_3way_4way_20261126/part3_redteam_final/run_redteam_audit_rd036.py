#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD036-C Cold-Blooded Red-Team Final Audit (`run_redteam_audit_rd036.py`):
  Gate 1: Trade-by-trade forensics on Blend / Stack / GBDT_D3 (top5/bot5, ST/delisted/yizi, ex5/ex10 at 30/80bps)
  Gate 2: Global 7,493-trial & 548-trial DSR across 3 variance regimes + full Blend weight/delta/thr plateau + CSCV
  Gate 3: Year-by-year (2023/2024/2025/2026/26H2) vs S82 & S80 + 80bps + >=2yi + V20 combined slot displacement check
  Gate 4 & 5: Honest cold-blooded Tiering & save `rd036_redteam_audit.json`.

Strictly read-only on part1_20cm & part2_other5. Zero yfinance. RSS < 2.0 GB.
"""
import gc
import json
import math
import os
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

HERE = os.path.dirname(os.path.abspath(__file__))
PART1 = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd036_highorder_3way_4way_20261126/part1_20cm"
PART2 = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd036_highorder_3way_4way_20261126/part2_other5"
RD035_W3B = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave3_final/w3_3_redteam_audit_b"
for p in (HERE, PART1):
    if p not in sys.path:
        sys.path.insert(0, p)

import rd036_lib as lib
import _rt_audit_helpers as ah


def rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 1)


def main():
    t0 = time.time()
    print("[RD036-C] Loading 20cm enriched PIT data & lean V20 context ...")
    p20, meta = lib.load_20cm_enriched_data()
    v20_ctx = lib.load_lean_v20_comb_context()
    bench_df = v20_ctx["wf_ctx"]["bench"]
    p20["wf_in_window"] = p20["buy_date"] >= lib.WF_START_DT
    wf_cands = p20[p20["wf_in_window"]].copy()

    feat_cb = meta["feat_clean_b"]
    feat_ix = meta["ix_cols"]
    feat_union = meta["feat_union_cb_mech"]
    atomic_cols = meta["atomic_cols"]

    # 1. Reconstruct exact CB & MN deltas across cold cuts & deltas (single fast pass)
    orig_map = {"v20": "v20_score", "cold40": "v20_cold40", "cold45": "v20_cold45", "cold50": "v20_cold50", "cold55": "v20_cold55"}
    dm_cb, _ = lib.run_mode_b_multi_grid(p20, feat_cb, list(orig_map.values()), deltas=(10, 15), min_discrete_bin_cnt=15, top_k=10)
    dm_mn, _ = lib.run_mode_b_multi_grid(p20, feat_ix, list(orig_map.values()), deltas=(10, 15), min_discrete_bin_cnt=0, top_k=10)

    # 2. Reconstruct 3-way & GBDT_D3
    ho_res = lib.run_causal_highorder_and_tree_wf(
        p20, atomic_cols=atomic_cols, extra_static_cols=feat_union,
        wf_start_date=lib.WF_START_DT, min_warmup_trades=80, deltas=(8, 12, 15), enable_4way=True,
    )
    c50 = p20["v20_cold50"].to_numpy(float)
    d_cb15 = dm_cb[("v20_cold50", 15)]
    d_mn15 = dm_mn[("v20_cold50", 15)]
    d_3w12 = ho_res["rule_deltas"][("Rule3Way", 12)]
    d_gb3_8 = np.round(np.nan_to_num(ho_res["raw_z"]["GBDT_D3"], nan=0.0) * 8.0)
    d_gb3_12 = np.round(np.nan_to_num(ho_res["raw_z"]["GBDT_D3"], nan=0.0) * 12.0)

    key_specs = {
        "BASE_V11_S82": (p20["v20_score"].to_numpy(float), 82.0),
        "BASE_V11_S80": (p20["v20_score"].to_numpy(float), 80.0),
        "COLD50_S80": (c50, 80.0),
        "CLEANB_cold50_d15_S80": (c50 + d_cb15, 80.0),
        "CLEANB_cold50_d15_S84": (c50 + d_cb15, 84.0),
        "MechNat_cold50_d15_S80": (c50 + d_mn15, 80.0),
        "Blend_c50_Half_CB15_MN15_S80": (c50 + np.round(0.5 * d_cb15 + 0.5 * d_mn15), 80.0),
        "Blend_c50_Half_CB15_MN15_NoRound_S80": (c50 + 0.5 * d_cb15 + 0.5 * d_mn15, 80.0),
        "Blend_c50_Half_CB15_MN15_HalfUp_S80": (c50 + np.floor(0.5 * d_cb15 + 0.5 * d_mn15 + 0.5), 80.0),
        "Stack_c50_Avg_CB15_MN15_R3W12_S80": (c50 + np.round((d_cb15 + d_mn15 + d_3w12) / 3.0), 80.0),
        "Stack_c50_Avg_CB15_MN15_R3W12_NoRound_S80": (c50 + (d_cb15 + d_mn15 + d_3w12) / 3.0, 80.0),
        "GBDT_D3_cold50_d8_S80": (c50 + d_gb3_8, 80.0),
    }

    eval_cols = ["buy_date", "exit_date", "code", "name", "buy_hhmm", "exit_hhmm", "can_buy_hygiene", "wf_in_window",
                 "net_ret", "net_ret_30", "net_ret_50", "net_ret_80", "segs_30", "segs_50", "segs_80", "sd_amount_yi_t1", "v20_score"]
    df_ev_base = p20[eval_cols].copy()

    key_evals = {}
    for nm, (sc_v, thr) in key_specs.items():
        dtmp = df_ev_base.copy()
        dtmp["_sc"] = sc_v
        key_evals[nm] = lib.evaluate_variant_fast(nm, "KEY", dtmp, "_sc", thr, bench_df, wf_cands, perm_n=0, v20_comb_ctx=v20_ctx)

    # Verify exact match with rd036_20cm_best_trades.parquet
    best_pq = pd.read_parquet(f"{PART1}/rd036_20cm_best_trades.parquet")
    blend_sl = key_evals["Blend_c50_Half_CB15_MN15_S80"]["slot_df"]
    assert len(best_pq) == len(blend_sl) and list(zip(best_pq["buy_date"], best_pq["code"])) == list(zip(blend_sl["buy_date"], blend_sl["code"]))
    print(f"  [Parity OK] Blend exact match with best_trades.parquet ({len(best_pq)} trades, NAV={key_evals['Blend_c50_Half_CB15_MN15_S80']['row']['nav_wf']})")

    # 3. Gate 1: Trade-by-trade Forensics
    codes_all = set()
    for nm in ("BASE_V11_S82", "BASE_V11_S80", "Blend_c50_Half_CB15_MN15_S80", "Stack_c50_Avg_CB15_MN15_R3W12_S80", "GBDT_D3_cold50_d8_S80"):
        codes_all.update(key_evals[nm]["slot_df"]["code"].astype(str).str.zfill(6).unique())
    ref_lu = ah.build_forensic_lookup(codes_all)
    gate1_forensics = {
        nm: ah.forensic_audit_trades(nm, key_evals[nm]["slot_df"], ref_lu)
        for nm in ("BASE_V11_S82", "BASE_V11_S80", "Blend_c50_Half_CB15_MN15_S80", "Stack_c50_Avg_CB15_MN15_R3W12_S80", "GBDT_D3_cold50_d8_S80")
    }

    # 4. Gate 2A: Full Blend Plateau Grid (w_cb/w_mn in 0.0/1.0, 0.3/0.7, 0.5/0.5, 0.7/0.3, 1.0/0.0 x d10/d15 x cut x thr)
    plateau_rows = []
    plateau_drs = {}
    weights = [(0.0, 1.0, "w00_10"), (0.3, 0.7, "w30_70"), (0.5, 0.5, "w50_50"), (0.7, 0.3, "w70_30"), (1.0, 0.0, "w10_00")]
    for btag, orig_c in [("v20", "v20_score"), ("cold45", "v20_cold45"), ("cold50", "v20_cold50"), ("cold55", "v20_cold55")]:
        b_arr = p20[orig_c].to_numpy(float)
        for d_cb, d_mn in [(10, 10), (10, 15), (15, 10), (15, 15)]:
            dcb = dm_cb[(orig_c, d_cb)]
            dmn = dm_mn[(orig_c, d_mn)]
            for wc, wm, wtag in weights:
                if (wtag in ("w00_10", "w10_00")) and d_cb != d_mn:
                    continue
                sc_b = b_arr + np.round(wc * dcb + wm * dmn)
                for thr in (78, 80, 82, 84):
                    vname = f"PB_{btag}_{wtag}_cb{d_cb}_mn{d_mn}_S{thr}"
                    dtmp = df_ev_base.copy()
                    dtmp["_sc"] = sc_b
                    ev = lib.evaluate_variant_fast(vname, "BLEND_PLATEAU", dtmp, "_sc", float(thr), bench_df, wf_cands, perm_n=0, v20_comb_ctx=None)
                    r_p = ev["row"]
                    r_p.update({"btag": btag, "wtag": wtag, "w_cb": wc, "w_mn": wm, "d_cb": d_cb, "d_mn": d_mn, "thr": thr})
                    plateau_rows.append(r_p)
                    plateau_drs[vname] = ev["dr30"]

    df_plat = pd.DataFrame(plateau_rows)
    plat_names = df_plat["variant"].tolist()
    plat_mat = np.column_stack([plateau_drs[nm] for nm in plat_names])
    cscv_plat_s10 = lib.compute_cscv_pbo(plat_mat, plat_names, n_blocks=10)
    # Also CSCV specifically for Cold50 Blend neighborhood (exclude pure endpoints, focus on 0.3/0.7, 0.5/0.5, 0.7/0.3)
    c50_mix_names = df_plat[(df_plat["btag"] == "cold50") & (df_plat["wtag"].isin(["w30_70", "w50_50", "w70_30"]))]["variant"].tolist()
    cscv_c50_mix_s10 = lib.compute_cscv_pbo(np.column_stack([plateau_drs[nm] for nm in c50_mix_names]), c50_mix_names, n_blocks=10)
    c50_s80_names = df_plat[(df_plat["btag"] == "cold50") & (df_plat["thr"] == 80)]["variant"].tolist()
    cscv_c50_s80_s10 = lib.compute_cscv_pbo(np.column_stack([plateau_drs[nm] for nm in c50_s80_names]), c50_s80_names, n_blocks=10)

    # Also Stack & GBDT_D3 neighbors
    extra_neighbors = {}
    for nm, (sc_v, thr) in {
        "Stack_c50_Avg_CB15_MN15_R3W8_S80": (c50 + np.round((d_cb15 + d_mn15 + ho_res["rule_deltas"][("Rule3Way", 8)]) / 3.0), 80.0),
        "Stack_c50_Avg_CB15_MN15_R3W15_S80": (c50 + np.round((d_cb15 + d_mn15 + ho_res["rule_deltas"][("Rule3Way", 15)]) / 3.0), 80.0),
        "Stack_c50_Avg_CB10_MN10_R3W12_S80": (c50 + np.round((dm_cb[("v20_cold50", 10)] + dm_mn[("v20_cold50", 10)] + d_3w12) / 3.0), 80.0),
        "Stack_c50_Avg_CB15_MN15_R3W12_S78": (c50 + np.round((d_cb15 + d_mn15 + d_3w12) / 3.0), 78.0),
        "Stack_c50_Avg_CB15_MN15_R3W12_S82": (c50 + np.round((d_cb15 + d_mn15 + d_3w12) / 3.0), 82.0),
        "Stack_c50_Avg_CB15_MN15_R3W12_S84": (c50 + np.round((d_cb15 + d_mn15 + d_3w12) / 3.0), 84.0),
        "GBDT_D3_cold50_d5_S80": (c50 + np.round(np.nan_to_num(ho_res["raw_z"]["GBDT_D3"], nan=0.0) * 5.0), 80.0),
        "GBDT_D3_cold50_d10_S80": (c50 + np.round(np.nan_to_num(ho_res["raw_z"]["GBDT_D3"], nan=0.0) * 10.0), 80.0),
        "GBDT_D3_cold50_d12_S80": (c50 + d_gb3_12, 80.0),
        "GBDT_D3_cold50_d15_S80": (c50 + np.round(np.nan_to_num(ho_res["raw_z"]["GBDT_D3"], nan=0.0) * 15.0), 80.0),
    }.items():
        dtmp = df_ev_base.copy()
        dtmp["_sc"] = sc_v
        extra_neighbors[nm] = lib.evaluate_variant_fast(nm, "NEIGHBOR", dtmp, "_sc", thr, bench_df, wf_cands, perm_n=0, v20_comb_ctx=None)["row"]

    # 5. Gate 2B: Multi-Trial DSR under N=548, N=7,493 (6,945 + 548), N=8,018 (6,945 + 548 + 525)
    g20 = pd.read_csv(f"{PART1}/rd036_20cm_grid.csv")
    sr_daily_548 = g20["sharpe_wf"].to_numpy(float) / math.sqrt(242.0)
    var_rd036a_548 = float(np.var(sr_daily_548, ddof=1))
    var_null = 1.0 / 935.0  # 1 / (T - 1)
    rd035_cal = json.load(open(f"{RD035_W3B}/w3_3_redteam_b_audit.json"))["exact_mtm_pool_calibration"]
    var_rd035_exact = float(rd035_cal["var_sr_daily_exact_all"])  # 0.002371
    var_rd036b_525 = float(json.load(open(f"{PART2}/rd036_other5_audit.json"))["multi_trial_accounting"]["var_sr_daily_rd036"])  # 0.003039
    # Weighted pooled variance of RD035 (778 exact tracks) + RD036-A (548 tracks)
    var_pooled_7493 = (777 * var_rd035_exact + 547 * var_rd036a_548) / (777 + 547)

    dsr_audit = {}
    for nm in ("BASE_V11_S82", "BASE_V11_S80", "CLEANB_cold50_d15_S80", "CLEANB_cold50_d15_S84",
               "Blend_c50_Half_CB15_MN15_S80", "Stack_c50_Avg_CB15_MN15_R3W12_S80", "GBDT_D3_cold50_d8_S80"):
        dr = key_evals[nm]["dr30"]
        dsr_audit[nm] = {
            "N548_var_rd036a": ah.calc_dsr_explicit(dr, 548, var_rd036a_548),
            "N548_var_null": ah.calc_dsr_explicit(dr, 548, var_null),
            "N7493_var_rd036a": ah.calc_dsr_explicit(dr, 7493, var_rd036a_548),
            "N7493_var_null": ah.calc_dsr_explicit(dr, 7493, var_null),
            "N7493_var_pooled_grand": ah.calc_dsr_explicit(dr, 7493, var_pooled_7493),
            "N7493_var_rd035_exact": ah.calc_dsr_explicit(dr, 7493, var_rd035_exact),
            "N8018_var_rd035_exact": ah.calc_dsr_explicit(dr, 8018, var_rd035_exact),
        }

    # 6. Gate 3: Year-by-year comparison + V20 Combined Single-Slot Displacement Audit
    yearly_comp = {}
    for nm in ("BASE_V11_S82", "BASE_V11_S80", "COLD50_S80", "CLEANB_cold50_d15_S80", "CLEANB_cold50_d15_S84",
               "Blend_c50_Half_CB15_MN15_S80", "Blend_c50_Half_CB15_MN15_NoRound_S80", "Blend_c50_Half_CB15_MN15_HalfUp_S80",
               "Stack_c50_Avg_CB15_MN15_R3W12_S80", "Stack_c50_Avg_CB15_MN15_R3W12_NoRound_S80", "GBDT_D3_cold50_d8_S80"):
        ev = key_evals[nm]
        w30 = ev["windows_30bps"]
        yearly_comp[nm] = {
            "row": ev["row"],
            "Y2023": w30["Y2023"], "Y2024": w30["Y2024"], "Y2025": w30["Y2025"],
            "Y2026": w30["Y2026"], "Y2025_2026": w30["Y2025_2026"], "Y2026H2": w30["Y2026H2"],
            "FULL_WF_80bps": ev["windows_80bps"]["FULL_WF"],
            "FULL_WF_liq2y": ev["windows_liq2y"]["FULL_WF"],
            "v20_comb": ev["comb"],
        }

    tr_s82 = ah.extract_v20_comb_ledger(v20_ctx, key_evals["BASE_V11_S82"]["slot_df"])
    tr_s80 = ah.extract_v20_comb_ledger(v20_ctx, key_evals["BASE_V11_S80"]["slot_df"])
    tr_blend = ah.extract_v20_comb_ledger(v20_ctx, key_evals["Blend_c50_Half_CB15_MN15_S80"]["slot_df"])
    tr_stack = ah.extract_v20_comb_ledger(v20_ctx, key_evals["Stack_c50_Avg_CB15_MN15_R3W12_S80"]["slot_df"])
    tr_gbdt = ah.extract_v20_comb_ledger(v20_ctx, key_evals["GBDT_D3_cold50_d8_S80"]["slot_df"])
    v20_off_wf = v20_ctx["wf_ctx"]["v20_ledger"]
    v20_off_wf = v20_off_wf[v20_off_wf["buy_date"].between(lib.WF_START_DT, lib.WF_END_DT)].copy()

    comb_displacement = {
        "S82_vs_Official_V20_207": ah.analyze_comb_displacement("S82_Engine", tr_s82, "Official_V20_207", v20_off_wf),
        "S80_vs_S82": ah.analyze_comb_displacement("BASE_S80", tr_s80, "BASE_S82", tr_s82),
        "Blend_vs_S82": ah.analyze_comb_displacement("Blend_S80", tr_blend, "BASE_S82", tr_s82),
        "Blend_vs_S80": ah.analyze_comb_displacement("Blend_S80", tr_blend, "BASE_S80", tr_s80),
        "Stack_vs_S82": ah.analyze_comb_displacement("Stack_S80", tr_stack, "BASE_S82", tr_s82),
        "Stack_vs_S80": ah.analyze_comb_displacement("Stack_S80", tr_stack, "BASE_S80", tr_s80),
        "GBDT_D3_vs_S82": ah.analyze_comb_displacement("GBDT_D3_S80", tr_gbdt, "BASE_S82", tr_s82),
        "GBDT_D3_vs_S80": ah.analyze_comb_displacement("GBDT_D3_S80", tr_gbdt, "BASE_S80", tr_s80),
    }

    # Summarize Blend plateau stats
    s80_base_nav = key_evals["BASE_V11_S80"]["row"]["nav_wf"]
    s82_base_nav = key_evals["BASE_V11_S82"]["row"]["nav_wf"]
    c50_mix_df = df_plat[(df_plat["btag"] == "cold50") & (df_plat["wtag"].isin(["w30_70", "w50_50", "w70_30"]))]
    c50_mix_s80 = c50_mix_df[c50_mix_df["thr"] == 80]

    audit_out = lib.sanitize_json({
        "task": "RD036-C Cold-Blooded Red-Team Final Audit",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t0, 2),
        "peak_rss_mb": rss_mb(),
        "d12_yfinance_imported": "yfinance" in sys.modules,
        "gate1_trade_forensics": gate1_forensics,
        "gate2_dsr_multi_trial": {
            "variance_inputs": {
                "var_null_1_over_935": round(var_null, 6),
                "var_rd036a_548_daily": round(var_rd036a_548, 6),
                "var_rd035_exact_778_daily": round(var_rd035_exact, 6),
                "var_rd036b_525_daily": round(var_rd036b_525, 6),
                "var_pooled_grand_daily": round(var_pooled_7493, 6),
            },
            "candidates": dsr_audit,
        },
        "gate2_blend_plateau": {
            "summary_cold50_mix_48": {
                "n_variants": int(len(c50_mix_df)),
                "pct_beat_s82_nav": round(float((c50_mix_df["nav_wf"] > s82_base_nav).mean() * 100.0), 1),
                "pct_beat_s80_nav": round(float((c50_mix_df["nav_wf"] > s80_base_nav).mean() * 100.0), 1),
                "nav_min": round(float(c50_mix_df["nav_wf"].min()), 2),
                "nav_median": round(float(c50_mix_df["nav_wf"].median()), 2),
                "nav_max": round(float(c50_mix_df["nav_wf"].max()), 2),
                "sharpe_median": round(float(c50_mix_df["sharpe_wf"].median()), 3),
                "cscv_pbo_s10_pct": cscv_c50_mix_s10["pbo_pct"],
            },
            "summary_cold50_s80_slice": {
                "n_variants": int(len(c50_s80_names)),
                "pct_beat_s80_nav": round(float((c50_mix_s80["nav_wf"] > s80_base_nav).mean() * 100.0), 1),
                "nav_min": round(float(c50_mix_s80["nav_wf"].min()), 2),
                "nav_median": round(float(c50_mix_s80["nav_wf"].median()), 2),
                "nav_max": round(float(c50_mix_s80["nav_wf"].max()), 2),
                "cscv_pbo_s10_pct": cscv_c50_s80_s10["pbo_pct"],
            },
            "cscv_full_plateau_s10": cscv_plat_s10,
            "cold50_mix_s80_table": c50_mix_s80[["variant", "w_cb", "w_mn", "d_cb", "d_mn", "n_wf", "wr_wf", "nav_wf", "ex5_wf", "mdd_wf", "sharpe_wf", "nav_2526", "nav_26h2", "nav_80bps", "nav_liq2y"]].to_dict("records"),
            "full_plateau_rows": plateau_rows,
            "stack_and_gbdt_neighbors": extra_neighbors,
        },
        "gate3_yearly_and_displacement": {
            "yearly_comparison": yearly_comp,
            "v20_combined_displacement": comb_displacement,
        },
    })
    out_path = f"{HERE}/rd036_redteam_audit.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(audit_out, f, ensure_ascii=False, indent=2, allow_nan=False)
    print(f"[RD036-C DONE in {time.time()-t0:.1f}s | RSS={rss_mb()}MB] Saved {out_path}")


if __name__ == "__main__":
    main()

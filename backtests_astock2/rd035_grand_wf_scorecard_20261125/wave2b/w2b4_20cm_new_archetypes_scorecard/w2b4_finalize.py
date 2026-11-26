#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 2B-4 Finalizer:
  1. Verifies 2024-12-31 physical truncation (max_abs_diff == 0.0) both end-to-end (pool rebuild)
     and across all 5 tracks' daily WF scorecards via wf.verify_truncation_zero_leakage.
  2. Audits S82 complementarity (Track D & winners vs S82 active/absent days) and B1 discrete sensitivity.
  3. Saves w2b4_best_trades.parquet & w2b4_audit.json, verifies Peak RSS < 1.8 GB, cleans _cache_*.
"""
import os

for _env in (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
):
    os.environ[_env] = "1"

import gc
import json
import pickle
import sys
import time

import numpy as np
import pandas as pd
import pyarrow as pa

pa.set_cpu_count(1)
pa.set_io_thread_count(1)
assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave2b/w2b4_20cm_new_archetypes_scorecard"
if OUT_DIR not in sys.path:
    sys.path.insert(0, OUT_DIR)

import w2b4_lib as lib
import w2b4_run_all as run_all


def check_end_to_end_pool_truncation(master_full: pd.DataFrame, all_fcols: list[str], cutoff: str = "2024-12-31") -> dict:
    """Physically rebuild 2024-12-31 truncated candidate pool and assert 0.0 diff on all features & completed exits <= cutoff."""
    trunc_df, _, trunc_meta = lib.build_w2b4_candidate_pool(end_cutoff=cutoff)
    full_cut = master_full[master_full["buy_date"] <= cutoff].copy()

    mode_counts = {}
    max_feat_diff = 0.0
    worst_col = None
    for mname in ("v11", "h1", "h2"):
        ex_col = f"{mname}_exit_date"
        f_mask = (full_cut[ex_col].astype(str) != "") & (full_cut[ex_col].astype(str) <= cutoff) & (full_cut[ex_col].astype(str) > full_cut["buy_date"].astype(str))
        t_mask = (trunc_df[ex_col].astype(str) != "") & (trunc_df[ex_col].astype(str) <= cutoff) & (trunc_df[ex_col].astype(str) > trunc_df["buy_date"].astype(str))
        full_ex = full_cut[f_mask].sort_values(["buy_date", "code"]).reset_index(drop=True)
        trunc_ex = trunc_df[t_mask].sort_values(["buy_date", "code"]).reset_index(drop=True)
        assert len(full_ex) == len(trunc_ex), f"Pool {mname} trunc row count mismatch: {len(full_ex)} vs {len(trunc_ex)}"
        assert (full_ex["buy_date"].values == trunc_ex["buy_date"].values).all(), f"Pool {mname} buy_date mismatch"
        assert (full_ex["code"].values == trunc_ex["code"].values).all(), f"Pool {mname} code mismatch"
        assert (full_ex[ex_col].astype(str).values == trunc_ex[ex_col].astype(str).values).all(), f"Pool {mname} exit_date mismatch"
        mode_counts[mname] = int(len(full_ex))

        check_cols = (all_fcols if mname == "v11" else []) + [f"{mname}_gross_ret", f"{mname}_net_ret", f"{mname}_hold_bars"]
        for c in check_cols:
            if c not in full_ex.columns or c not in trunc_ex.columns:
                continue
            a = pd.to_numeric(full_ex[c], errors="coerce").to_numpy(np.float64)
            b = pd.to_numeric(trunc_ex[c], errors="coerce").to_numpy(np.float64)
            if not np.array_equal(np.isnan(a), np.isnan(b)):
                d = 999.0
            else:
                fin = np.isfinite(a) & np.isfinite(b)
                d = float(np.max(np.abs(a[fin] - b[fin]))) if fin.any() else 0.0
            if d > max_feat_diff:
                max_feat_diff = d
                worst_col = f"{mname}:{c}"
        assert max_feat_diff == 0.0, f"Pool feature/ret trunc diff != 0 on {worst_col}: {max_feat_diff}"

    del trunc_df, full_cut, full_ex, trunc_ex
    gc.collect()
    pa.default_memory_pool().release_unused()
    return {
        "cutoff": cutoff,
        "rebuild_rss_mb": trunc_meta["peak_rss_mb"],
        "mode_completed_rows_le_cutoff": mode_counts,
        "max_abs_feature_and_ret_diff": max_feat_diff,
        "worst_col": worst_col,
        "zero_leakage_pass": True,
    }


def compute_s82_complementarity(master_df: pd.DataFrame, specs_map: dict, v20_ctx: dict, pure_stock: list[str], stock_micro: list[str]) -> dict:
    """Measure exact overlap/complementarity with official S82 20cm (from V20 ledger & pool_20cm_master_pit)."""
    p20 = pd.read_parquet(f"{lib.WAVE1_BASE}/pool_20cm_master_pit.parquet", columns=["buy_date", "code", "v20_score", "is_pass_official", "net_ret"])
    p20_wf = p20[p20["buy_date"].between("2023-01-03", "2026-11-16") & (p20["is_pass_official"] == 1)].copy()
    s82_pass_days = set(p20_wf["buy_date"].astype(str).str[:10])
    v20_led = v20_ctx["v20_ledger"]
    s82_v20_days = set(v20_led[(v20_led["strategy"] == "20cm") & v20_led["buy_date"].between("2023-01-03", "2026-11-16")]["buy_date"].astype(str).str[:10])
    cal5 = v20_ctx["calendar_5y"]
    empty_days = set(cal5[cal5["trade_date"].between("2023-01-03", "2026-11-16") & cal5["v20_empty_strict_no_stier_wait"]]["trade_date"])

    out = {"n_s82_pass_wf_days": len(s82_pass_days), "n_s82_v20_wf_days": len(s82_v20_days), "n_v20_empty_wf_days": len(empty_days), "tracks": {}}
    check_list = [
        ("A5_12_23_v11_PURE", "abs_80"),
        ("A1_12_23_h1_PURE", "abs_75"),
        ("B1_all_h1_MICRO", "top10"),
        ("B3_streak2_v11_MICRO", "top20"),
        ("D1_s82zone_v11_PURE", "abs_75"),
        ("D3_wide_h1_PURE", "abs_80"),
        ("E1_mild_v11_PURE", "abs_80"),
    ]
    for tid, thr_lbl in check_list:
        _, _, mask, ex_mode, fset, _ = specs_map[tid]
        sub_df, vf_cols = lib.prepare_track_df(master_df, mask, exit_mode=ex_mode, end_dt="2026-11-16", all_feat_cols=fset)
        df_h = lib.wfm.prepare_hygiene_and_net_ret(sub_df, fee_rt=0.0030, gross_ret_col="gross_ret")
        scored_df, _ = lib.wfc.run_expanding_scorecard_loop(
            df_h, feature_cols=vf_cols, mode="scorecard_0_100", wf_start_date="2023-01-03",
            min_warmup_trades=80, min_warmup_trades_rare=60, min_warmup_months=18,
            recalc_freq="daily", top_k=12, min_k=5, max_corr=0.65, min_t_stat=1.0, shrink_tau=20.0,
        )
        t_arg = f"wf_thr_{thr_lbl}" if thr_lbl.startswith("top") else float(thr_lbl.split("_")[1])
        pass_df, slot_df = lib.wfm.select_single_slot_trades(scored_df, score_col="wf_score", threshold=t_arg, wf_only=True)
        # Verify zero trade-level (buy_date, code) overlap with S82 pool
        s82_pairs = set(zip(p20_wf["buy_date"].astype(str), p20_wf["code"].astype(str).str.zfill(6)))
        tr_pairs = set(zip(pass_df["buy_date"].astype(str), pass_df["code"].astype(str).str.zfill(6)))
        assert len(s82_pairs & tr_pairs) == 0, f"{tid} overlapped with S82!"

        pass_days = set(pass_df["buy_date"].astype(str))
        on_s82_absent_days = sorted(pass_days - s82_pass_days)
        on_empty_s82_absent = sorted(pass_days & empty_days - s82_pass_days)
        sub_absent = slot_df[slot_df["buy_date"].isin(on_s82_absent_days)]
        out["tracks"][f"{tid}@{thr_lbl}"] = {
            "n_pass_days": len(pass_days),
            "n_slot_trades": int(len(slot_df)),
            "n_days_s82_absent": len(on_s82_absent_days),
            "pct_days_s82_absent": round(len(on_s82_absent_days) / max(1, len(pass_days)) * 100.0, 2),
            "n_days_v20_empty_and_s82_absent": len(on_empty_s82_absent),
            "slot_trades_on_s82_absent_n": int(len(sub_absent)),
            "slot_trades_on_s82_absent_wr_pct": round(float((sub_absent["net_ret"] > 0).mean() * 100.0), 2) if not sub_absent.empty else 0.0,
            "slot_trades_on_s82_absent_nav": round(float(np.prod(1.0 + sub_absent["net_ret"].to_numpy(float))), 4) if not sub_absent.empty else 1.0,
            "zero_s82_stock_day_overlap": True,
        }
    return out


def main():
    t0 = time.time()
    master_df = pd.read_parquet(f"{OUT_DIR}/_cache_w2b4_master.parquet")
    with open(f"{OUT_DIR}/_cache_w2b4_meta.json", encoding="utf-8") as f:
        mc = json.load(f)
    all_fcols, build_meta = mc["all_fcols"], mc["build_meta"]
    with open(f"{OUT_DIR}/_cache_w2b4_daily_details.pkl", "rb") as f:
        all_details = pickle.load(f)
    comp_df = pd.read_csv(f"{OUT_DIR}/w2b4_tracks_compare.csv")

    pure_stock, stock_micro = run_all.get_feature_scopes(all_fcols)
    specs = run_all.define_final_specs(master_df, pure_stock, stock_micro)
    specs_map = {s[0]: s for s in specs}
    v20_ctx = lib.wf.load_v20_reference_context(lib.WAVE1_BASE)

    # 1. Save best trades parquet:
    # Primary dual-winning champion: A5_12_23_v11_PURE @ abs_80 (7.09x WF, ex5=1.22x, perm_p=0.015, V20 patch 1.79x, empty=4.23x)
    # Also save A1_12_23_h1_PURE @ abs_75 (9.37x WF, ex5=2.18x, 2526=4.50x, 2026=2.65x) as secondary reference
    best_ledgers = {}
    for label, tid, thr_val, out_pq in [
        ("primary_winner_A5_v11_abs80", "A5_12_23_v11_PURE", 80.0, f"{OUT_DIR}/w2b4_best_trades.parquet"),
        ("secondary_standalone_A1_h1_abs75", "A1_12_23_h1_PURE", 75.0, f"{OUT_DIR}/w2b4_best_a1_abs75_trades.parquet"),
    ]:
        _, _, mask, ex_mode, fset, _ = specs_map[tid]
        sub_df, vf_cols = lib.prepare_track_df(master_df, mask, exit_mode=ex_mode, end_dt="2026-11-16", all_feat_cols=fset)
        df_h = lib.wfm.prepare_hygiene_and_net_ret(sub_df, fee_rt=0.0030, gross_ret_col="gross_ret")
        scored_df, _ = lib.wfc.run_expanding_scorecard_loop(
            df_h, feature_cols=vf_cols, mode="scorecard_0_100", wf_start_date="2023-01-03",
            min_warmup_trades=80, min_warmup_trades_rare=60, min_warmup_months=18,
            recalc_freq="daily", top_k=12, min_k=5, max_corr=0.65, min_t_stat=1.0, shrink_tau=20.0,
        )
        _, slot_df = lib.wfm.select_single_slot_trades(scored_df, score_col="wf_score", threshold=thr_val, wf_only=True)
        keep_cols = [
            "buy_date", "exit_date", "code", "buy_hhmm", "exit_hhmm", "open_pct",
            "gross_ret", "net_ret", "hold_bars", "exit_reason", "wf_score",
            "eng_is_2to3", "mcap_yi_t1", "list_age", "kpl_rank_t1", "kpl_zt1_t1",
        ]
        save_cols = [c for c in keep_cols if c in slot_df.columns]
        slot_df[save_cols].to_parquet(out_pq, index=False)
        best_ledgers[label] = {"n_trades": int(len(slot_df)), "nav": round(float(np.prod(1.0 + slot_df["net_ret"].to_numpy(float))), 4), "file": out_pq}
    print("[1/5] Saved best_trades parquets", flush=True)

    # 2. Check B1 sensitivity without rare discrete lhb_has_surf_yz_t1
    _, _, b1_mask, b1_ex, b1_fset, _ = specs_map["B1_all_h1_MICRO"]
    b1_sub, b1_vf = lib.prepare_track_df(master_df, b1_mask, exit_mode=b1_ex, end_dt="2026-11-16", all_feat_cols=b1_fset)
    b1_surf_cnt = int((b1_sub["lhb_has_surf_yz_t1"] == 1).sum())
    b1_vf_nosurf = [c for c in b1_vf if c != "lhb_has_surf_yz_t1"]
    b1_nosurf_rows, _, _ = lib.evaluate_track_full(
        "B1_nosurf_check", "Track_B_HighYin", b1_sub, b1_vf_nosurf, v20_ctx,
        thresholds=("top20", "top10", 75), perm_n=250, recalc_freq="daily",
    )
    del b1_sub
    print("[2/5] Completed B1_nosurf sensitivity check", flush=True)

    # 3. S82 Complementarity check
    s82_comp = compute_s82_complementarity(master_df, specs_map, v20_ctx, pure_stock, stock_micro)
    print("[3/5] Completed S82 complementarity check", flush=True)

    # 4. Physical 2024-12-31 Truncation Zero-Leakage Proofs across all 5 tracks!
    trunc_track_proofs = {}
    trunc_targets = [
        ("A1_12_23_h1_PURE", 75.0),
        ("A5_12_23_v11_PURE", 80.0),
        ("B1_all_h1_MICRO", "top10"),
        ("C1_mild_v11_MICRO", 70.0),
        ("D1_s82zone_v11_PURE", 75.0),
        ("D3_wide_h1_PURE", 80.0),
        ("E1_mild_v11_PURE", 80.0),
    ]
    for tid, thr in trunc_targets:
        _, _, mask, ex_mode, fset, _ = specs_map[tid]
        sub_df, vf_cols = lib.prepare_track_df(master_df, mask, exit_mode=ex_mode, end_dt="2026-11-16", all_feat_cols=fset)
        tp = lib.wf.verify_truncation_zero_leakage(
            sub_df, vf_cols, mode="A", cutoff="2024-12-31", score_threshold=thr,
            v20_ctx=v20_ctx, wf_start_date="2023-01-03", min_warmup_trades=80,
            min_warmup_trades_rare=60, min_warmup_months=18, recalc_freq="daily",
            top_k=12, min_k=5, max_corr=0.65, min_t_stat=1.0, shrink_tau=20.0,
            gross_ret_col="gross_ret", fee_rt=0.0030,
        )
        trunc_track_proofs[tid] = tp
        del sub_df
    print("[4/5] Completed all 7 track 2024-12-31 truncation zero-leakage proofs", flush=True)

    # Free master_df before end-to-end 2024-12-31 pool rebuild so RSS stays < 1.8 GB
    master_cut_ref = master_df[master_df["buy_date"] <= "2024-12-31"].copy()
    del master_df, v20_ctx
    gc.collect()
    pa.default_memory_pool().release_unused()

    pool_trunc_proof = check_end_to_end_pool_truncation(master_cut_ref, all_fcols, cutoff="2024-12-31")
    del master_cut_ref
    gc.collect()

    # Build concise per-track headline summaries
    track_headlines = {}
    for grp in ("Track_A_Relay", "Track_B_HighYin", "Track_C_Pullback", "Track_D_ZhabanDeep", "Track_E_ThemeMild"):
        sub_c = comp_df[(comp_df["track_group"] == grp) & (comp_df["threshold"] != "all_cands")].copy()
        best_nav = sub_c.sort_values("nav_wf", ascending=False).iloc[0].to_dict()
        best_ex5 = sub_c.sort_values("ex5_wf", ascending=False).iloc[0].to_dict()
        best_patch = sub_c.sort_values("patch_delta_nav_ratio", ascending=False).iloc[0].to_dict()
        track_headlines[grp] = {
            "best_standalone_nav": best_nav,
            "best_ex5": best_ex5,
            "best_v20_patch": best_patch,
        }

    latest_scorecards = {
        tid: {
            "wf_actual_start": all_details[tid]["meta"]["wf_actual_start"],
            "n_rebuilds": all_details[tid]["meta"]["n_rebuilds"],
            "n_features_used": all_details[tid]["meta"]["n_features_used"],
            "factors": all_details[tid]["meta"]["latest_scorecard"].get("factors", []),
        }
        for tid in [
            "A1_12_23_h1_PURE", "A3_12_23_h2_PURE", "A5_12_23_v11_PURE", "A6_1to2_hiopen_h1_PURE",
            "A7_2to3_only_h1_PURE", "B1_all_h1_MICRO", "B3_streak2_v11_MICRO",
            "C1_mild_v11_MICRO", "D1_s82zone_v11_PURE", "D3_wide_h1_PURE",
            "E1_mild_v11_PURE", "E2_strong_thm_v11_PURE", "E3_mild_h1_PURE",
        ]
    }

    max_mtm_diff = float(comp_df["mtm_diff"].max())
    assert max_mtm_diff < 1e-6, f"MTM reconciliation diff exceeded 1e-6: {max_mtm_diff}"
    rss_mb = lib.get_rss_mb()
    assert rss_mb < 1800.0, f"Peak RSS exceeded 1.8 GB: {rss_mb} MB"

    audit = lib.sanitize_json({
        "task": "RD035 Wave 2B-4: 20cm New Archetypes Full Spectrum (Tracks A-E, 0-100 Scorecard, Daily Expanding WF)",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t0, 2),
        "hygiene_and_constraints": {
            "python": sys.version.split()[0],
            "d12_yfinance_imported": "yfinance" in sys.modules,
            "omp_threads": os.environ.get("OMP_NUM_THREADS"),
            "peak_rss_mb_build": build_meta["peak_rss_mb"],
            "peak_rss_mb_finalize": rss_mb,
            "peak_rss_under_1800mb": rss_mb < 1800.0 and build_meta["peak_rss_mb"] < 1800.0,
            "fee_round_trip": 0.0030,
            "yizi_excluded": True,
            "s82_overlap_count": 0,
            "max_mtm_reconciliation_diff": max_mtm_diff,
            "recalc_freq": "daily",
            "perm_n": 1000,
        },
        "deliverables": {
            "tracks_compare_csv": f"{OUT_DIR}/w2b4_tracks_compare.csv",
            "audit_json": f"{OUT_DIR}/w2b4_audit.json",
            "best_trades_parquet": f"{OUT_DIR}/w2b4_best_trades.parquet",
            "secondary_best_a1_parquet": f"{OUT_DIR}/w2b4_best_a1_abs75_trades.parquet",
        },
        "universe_counts": build_meta["track_counts"],
        "best_ledgers_summary": best_ledgers,
        "truncation_2024_12_31_proof": {
            "all_zero_diff_passed": True,
            "end_to_end_pool_rebuild": pool_trunc_proof,
            "all_5_tracks_wf_scorecard": trunc_track_proofs,
        },
        "s82_complementarity": s82_comp,
        "b1_surf_yz_sensitivity": {
            "n_surf_yz_obs_in_b1": b1_surf_cnt,
            "without_surf_yz_rows": b1_nosurf_rows,
        },
        "track_headlines": track_headlines,
        "latest_causal_scorecards": latest_scorecards,
    })

    with open(f"{OUT_DIR}/w2b4_audit.json", "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2, allow_nan=False)

    # Clean up temporary cache & intermediate screen files
    for tmp in (
        "_cache_w2b4_master.parquet",
        "_cache_w2b4_meta.json",
        "_cache_w2b4_daily_details.pkl",
        "_screen_tracks_compare.csv",
        "_screen_meta.json",
    ):
        tp = f"{OUT_DIR}/{tmp}"
        if os.path.exists(tp):
            os.remove(tp)

    print(f"[FINALIZE PASS in {audit['elapsed_sec']}s | Finalize RSS={rss_mb} MB | Build RSS={build_meta['peak_rss_mb']} MB | MTM max diff={max_mtm_diff}]")
    print("=== 2024-12-31 Truncation Proofs ===")
    print("  Pool rebuild:", pool_trunc_proof)
    for k, v in trunc_track_proofs.items():
        print(f"  {k:22s}: score_diff={v['max_abs_score_diff']}, ret_diff={v['max_abs_ret_diff']}, trades_le={v['n_trades_exiting_le_cutoff']}")


if __name__ == "__main__":
    main()

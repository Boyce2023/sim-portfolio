#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 2A-4 Road 2:
  Cross-Strategy Unified Grand Melee (4,183 candidates across all 6 strategies):
  Combines 37 cross-strategy atomic factors (xtr_*) + 130 mechanism interactions (ix_*)
  + 6 strategy dummies (strat_*) + causal exit_date<t Top-20x19/2 pairwise quadrants/products
  into a SINGLE day-by-day expanding 0..100 scorecard selecting the single highest-scoring
  stock each day (and top-quantile / absolute thresholds), head-to-head vs V20.0 6-strategy combined!

Zero yfinance (D12). Read-only on wave1_base and production files.
"""
import gc
import json
import os
import pickle
import resource
import sys
import time
import warnings

import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True
warnings.filterwarnings("ignore")

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
WAVE1_DIR = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
OUT_DIR = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave2a/w2a4_pairwise_interactions"

for p in (WAVE1_DIR, OUT_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import wf_scorecard_engine as wf
import _wf_sim_and_metrics as wfm
import _w2a4_data_and_features as w2f

STRATS = ["1to2", "2to3", "3to4", "high", "pry", "20cm"]
THRESHOLDS = ("all_cands", "top30", "top20", "top10", "top5", 70, 75, 80, 85)


def _sanitize(obj):
    if isinstance(obj, dict):
        return {str(k): _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return None if (np.isnan(v) or np.isinf(v)) else round(v, 6)
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    return obj


def _extract_km(ev: dict) -> dict:
    ws = ev.get("windows", {})
    fw = ws.get("FULL_WF", {})
    y2526 = ws.get("Y2025_2026", {})
    y26 = ws.get("Y2026", {})
    return {
        "wf_window": ev.get("wf_window", ""),
        "mtm_diff": ev.get("mtm_reconciliation_diff", 0.0),
        "full_wf": {
            "n": fw.get("n", 0), "wr_pct": fw.get("wr_pct", 0.0), "plr": fw.get("plr", 0.0),
            "mean_pct": fw.get("mean_pct", 0.0), "nav": fw.get("nav", 1.0),
            "ex_top3_nav": fw.get("ex_top3_nav", 1.0), "ex_top5_nav": fw.get("ex_top5_nav", 1.0),
            "daily_mdd_pct": fw.get("daily_mdd_pct", 0.0), "daily_sharpe": fw.get("daily_sharpe", 0.0),
            "excess_csi300_pp": fw.get("excess_csi300_pp", 0.0),
        },
        "y2025_2026": {
            "n": y2526.get("n", 0), "wr_pct": y2526.get("wr_pct", 0.0), "nav": y2526.get("nav", 1.0),
            "ex_top5_nav": y2526.get("ex_top5_nav", 1.0), "daily_mdd_pct": y2526.get("daily_mdd_pct", 0.0),
            "daily_sharpe": y2526.get("daily_sharpe", 0.0), "excess_csi300_pp": y2526.get("excess_csi300_pp", 0.0),
        },
        "y2026": {
            "n": y26.get("n", 0), "wr_pct": y26.get("wr_pct", 0.0), "nav": y26.get("nav", 1.0),
            "ex_top5_nav": y26.get("ex_top5_nav", 1.0), "daily_mdd_pct": y26.get("daily_mdd_pct", 0.0),
            "daily_sharpe": y26.get("daily_sharpe", 0.0), "excess_csi300_pp": y26.get("excess_csi300_pp", 0.0),
        },
        "perm_1000": ev.get("permutation_1000", {}),
    }


def _fmt_patch_res(pr: dict | None) -> dict | None:
    if pr is None:
        return None
    m1 = pr["mode1_strict_combined_no_peek"]
    m2 = pr["mode2_empty_slot_standalone"]
    return {
        "combined_with_patch_full_wf": m1["combined_with_patch"].get("FULL_WF"),
        "v20_baseline_full_wf": m1["v20_baseline"].get("FULL_WF"),
        "n_patch_added": m1["n_patch_added"],
        "n_v20_skipped": m1["n_v20_skipped_by_collision"],
        "delta_nav_ratio": m1["delta_nav_ratio_full_wf"],
        "delta_sharpe": m1["delta_sharpe_full_wf"],
        "delta_mdd_pp": m1["delta_mdd_pp_full_wf"],
        "empty_standalone_full_wf": m2["windows"].get("FULL_WF"),
    }


def _eval_thresholds(scored_df: pd.DataFrame, core_meta: dict, v20_ctx: dict, mtm_col: str | None = "mtm_full", perm_n: int = 1000) -> tuple[dict, dict]:
    bench_df = v20_ctx["bench"]
    actual_wf_start = core_meta["wf_actual_start"] or "2023-01-03"
    max_bench_dt = str(bench_df["trade_date"].max())
    end_date = str(scored_df["buy_date"].max())
    eval_end_dt = min(max_bench_dt, max(end_date, "2026-11-16")) if end_date <= max_bench_dt else max_bench_dt
    wf_cands = scored_df[scored_df["wf_in_window"]].copy()

    thr_map = {
        "all_cands": None,
        "top30": "wf_thr_top30",
        "top20": "wf_thr_top20",
        "top10": "wf_thr_top10",
        "top5": "wf_thr_top5",
    }
    res_out = {}
    slot_dfs = {}
    for th in THRESHOLDS:
        tname = str(th) if not isinstance(th, (int, float)) else f"abs_{int(th)}"
        t_arg = thr_map[th] if th in thr_map else float(th)
        pass_df, slot_df = wfm.select_single_slot_trades(scored_df, score_col="wf_score", threshold=t_arg, wf_only=True)
        ev = wf.evaluate_wf_ledger(slot_df, pass_df, wf_cands, bench_df, wf_start_dt=actual_wf_start, end_dt=eval_end_dt, mtm_col=mtm_col, perm_n=perm_n, seed=20261125)
        patch_res = None
        if not pass_df.empty and th in ("top20", "top10", 70, 75):
            patch_end = min(eval_end_dt, "2026-11-16")
            pr = wf.simulate_v20_empty_slot_patch(
                pass_df, v20_ctx=v20_ctx, wf_start_dt=actual_wf_start, end_dt=patch_end,
                score_col="wf_score", patch_mtm_col=mtm_col,
            )
            patch_res = _fmt_patch_res(pr)
        strat_mix = slot_df["strategy"].value_counts().to_dict() if not slot_df.empty else {}
        res_out[tname] = {
            "threshold": tname,
            "n_pass_cands": int(len(pass_df)),
            "strat_mix": {str(k): int(v) for k, v in strat_mix.items()},
            "metrics": _extract_km(ev),
            "v20_empty_patch": patch_res,
        }
        slot_dfs[tname] = slot_df
    return res_out, slot_dfs


def _add_strategy_dummies_and_v20_margin(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    out = df.copy()
    dummy_cols = []
    for st in STRATS:
        dc = f"strat_{st}"
        out[dc] = (out["strategy"] == st).astype(np.float32)
        dummy_cols.append(dc)
    # Causal static V20 margin relative to strategy entry bar (zero lookahead!)
    thr_map = {"1to2": 295.0, "2to3": 90.0, "3to4": 90.0, "high": 88.0, "pry": 165.0, "20cm": 76.0}
    sc = pd.to_numeric(out["v20_score"], errors="coerce").to_numpy(float)
    th = out["strategy"].map(thr_map).fillna(90.0).to_numpy(float)
    out["w24_v20_margin"] = np.where(out["strategy"] == "1to2", (sc - th) / 20.0, (sc - th) / 10.0).astype(np.float32)
    return out, dummy_cols


def main():
    t_all = time.time()
    print("[W2A4 Road 2] Starting Cross-Strategy Unified Grand Melee (4,183 candidates) ...")

    v20_ctx = wf.load_v20_reference_context(WAVE1_DIR)
    cal_dts = v20_ctx["bench"]["trade_date"].tolist()

    m_full = pd.read_parquet(f"{OUT_DIR}/_cache_master_w2a4_pit.parquet")
    with open(f"{OUT_DIR}/_cache_mtm_map.pkl", "rb") as f:
        cache_obj = pickle.load(f)
    mtm_map = cache_obj["mtm_map"]
    ix_cols = cache_obj["ix_cols"]
    base_cols = cache_obj["base_cols"]

    m_full["mtm_full"] = [mtm_map[(r.strategy, r.buy_date, r.code)] for r in m_full[["strategy", "buy_date", "code"]].itertuples(index=False)]
    m_full, dummy_cols = _add_strategy_dummies_and_v20_margin(m_full)
    xtr_37 = [c for c in m_full.columns if c.startswith("xtr_")]
    assert len(xtr_37) == 37, f"Expected 37 xtr cols, got {len(xtr_37)}"

    feat_base37 = xtr_37 + dummy_cols
    feat_mech130 = xtr_37 + ix_cols + dummy_cols
    feat_mech_v20m = feat_mech130 + ["w24_v20_margin", "orig_pass"]

    road2_models = {}
    factor_freq_rows = []
    best_model_name = None
    best_all_cands_nav = 0.0
    best_all_cands_df = None

    def _collect_freq(snaps: list[dict], scope_nm: str):
        n_sn = max(1, len(snaps))
        f_cnt, f_t = {}, {}
        for sn in snaps:
            for f in sn.get("factors", []):
                fn = f["name"]
                f_cnt[fn] = f_cnt.get(fn, 0) + 1
                f_t[fn] = f_t.get(fn, 0.0) + abs(float(f["t_cluster"]))
        for fn, cnt in f_cnt.items():
            factor_freq_rows.append({
                "road": "Road2",
                "scope": scope_nm,
                "variant": scope_nm,
                "factor": fn,
                "is_dynamic_20x19": fn.startswith("dyn_"),
                "appear_pct": round(cnt / n_sn * 100.0, 2),
                "mean_abs_t": round(f_t[fn] / cnt, 3),
                "n_snapshots": n_sn,
            })

    # 1. Ablation A: R2_Base37_Dummy (37 xtr + 6 strategy dummies, NO interactions)
    t0 = time.time()
    res_b37 = wf.run_wf_scorecard_new_strategy(
        m_full, feat_base37, v20_ctx=v20_ctx, wf_start_date="2023-01-03",
        min_warmup_trades=80, recalc_freq="daily", top_k=12, min_k=5, max_corr=0.65,
        thresholds=THRESHOLDS, eval_v20_patch=True, mtm_col="mtm_full", perm_n=1000,
    )
    road2_models["R2_Base37_Dummy"] = {
        "elapsed_sec": round(time.time() - t0, 2),
        "n_features": len(feat_base37),
        "wf_actual_start": res_b37["meta"]["wf_actual_start"],
        "n_rebuilds": res_b37["meta"]["n_rebuilds"],
        "latest_factors": res_b37["meta"]["latest_scorecard"]["factors"],
        "thresholds": {
            k: {
                "threshold": k,
                "n_pass_cands": v["n_passing_cands"],
                "strat_mix": v["slot_df"]["strategy"].value_counts().to_dict() if not v["slot_df"].empty else {},
                "metrics": _extract_km(v["metrics"]),
                "v20_empty_patch": _fmt_patch_res(v.get("v20_empty_patch")) if k in ("top20", "top10", "abs_70", "abs_75") else None,
            }
            for k, v in res_b37["threshold_results"].items()
        },
    }
    _collect_freq(res_b37["meta"].get("snapshots", []), "R2_Base37_Dummy")
    fw_b37 = road2_models["R2_Base37_Dummy"]["thresholds"]["all_cands"]["metrics"]["full_wf"]
    print(f"  [R2_Base37_Dummy] {time.time()-t0:.1f}s | all_cands n={fw_b37['n']}, NAV={fw_b37['nav']:.2f}, MDD={fw_b37['daily_mdd_pct']}%, Sharpe={fw_b37['daily_sharpe']}")
    del res_b37
    gc.collect()

    # 2. Ablation B: R2_Mech130_Native (37 xtr + 130 ix + 6 strategy dummies via native engine)
    t1 = time.time()
    res_m130 = wf.run_wf_scorecard_new_strategy(
        m_full, feat_mech130, v20_ctx=v20_ctx, wf_start_date="2023-01-03",
        min_warmup_trades=80, recalc_freq="daily", top_k=12, min_k=5, max_corr=0.65,
        thresholds=THRESHOLDS, eval_v20_patch=True, mtm_col="mtm_full", perm_n=1000,
    )
    road2_models["R2_Mech130_Native"] = {
        "elapsed_sec": round(time.time() - t1, 2),
        "n_features": len(feat_mech130),
        "wf_actual_start": res_m130["meta"]["wf_actual_start"],
        "n_rebuilds": res_m130["meta"]["n_rebuilds"],
        "latest_factors": res_m130["meta"]["latest_scorecard"]["factors"],
        "thresholds": {
            k: {
                "threshold": k,
                "n_pass_cands": v["n_passing_cands"],
                "strat_mix": v["slot_df"]["strategy"].value_counts().to_dict() if not v["slot_df"].empty else {},
                "metrics": _extract_km(v["metrics"]),
                "v20_empty_patch": _fmt_patch_res(v.get("v20_empty_patch")) if k in ("top20", "top10", "abs_70", "abs_75") else None,
            }
            for k, v in res_m130["threshold_results"].items()
        },
    }
    _collect_freq(res_m130["meta"].get("snapshots", []), "R2_Mech130_Native")
    fw_m130 = road2_models["R2_Mech130_Native"]["thresholds"]["all_cands"]["metrics"]["full_wf"]
    print(f"  [R2_Mech130_Native] {time.time()-t1:.1f}s | all_cands n={fw_m130['n']}, NAV={fw_m130['nav']:.2f}, MDD={fw_m130['daily_mdd_pct']}%, Sharpe={fw_m130['daily_sharpe']}")
    if fw_m130["nav"] > best_all_cands_nav:
        best_all_cands_nav = fw_m130["nav"]
        best_model_name = "R2_Mech130_Native"
        best_all_cands_df = res_m130["threshold_results"]["all_cands"]["slot_df"].copy()
    del res_m130
    gc.collect()

    sf_d_cached = None
    slot_f_d_cached = None

    # 3. Ablation C & D: Guarded Mech130 (no Dyn) & Guarded Mech130 + Causal exit_date<t Top-20x19/2
    for mname, sub_df, m_feats, b_feats in [
        ("R2_Mech130_Guarded", m_full, feat_mech130, []),
        ("R2_Mech_Plus_Dyn20x19", m_full, feat_mech130, base_cols),
        ("R2_MechDyn_With_V20Margin", m_full, feat_mech_v20m, base_cols),
        ("R2_OrigPassOnly_MechDyn", m_full[m_full["orig_pass"] == 1].copy().reset_index(drop=True), feat_mech130, base_cols),
    ]:
        t_m = time.time()
        df_h = wfm.prepare_hygiene_and_net_ret(sub_df, fee_rt=0.0030)
        sc_df, cmeta = w2f.run_expanding_interaction_loop(
            df_h, mech_cols=m_feats, base_cols=b_feats,
            mode="scorecard_0_100", wf_start_date="2023-01-03",
            min_warmup_trades=80, min_warmup_trades_rare=60, min_warmup_months=18,
            recalc_freq="daily", top_k=12, min_k=5, max_corr=0.65,
            min_t_stat=1.0, min_t_stat_dyn=2.6, min_synergy_t=1.6,
            shrink_tau=20.0, top_base_k=20, max_dyn_keep=25,
        )
        th_res, slot_dfs = _eval_thresholds(sc_df, cmeta, v20_ctx, mtm_col="mtm_full", perm_n=1000)
        if mname == "R2_Mech_Plus_Dyn20x19":
            sf_d_cached = sc_df
            slot_f_d_cached = slot_dfs["all_cands"]
        road2_models[mname] = {
            "elapsed_sec": round(time.time() - t_m, 2),
            "n_input_rows": int(len(sub_df)),
            "n_mech_features": len(m_feats),
            "n_base_dyn_pool": len(b_feats),
            "wf_actual_start": cmeta["wf_actual_start"],
            "n_rebuilds": cmeta["n_rebuilds"],
            "latest_factors": cmeta["latest_scorecard"]["factors"],
            "thresholds": th_res,
        }
        fw_m = th_res["all_cands"]["metrics"]["full_wf"]
        print(f"  [{mname:26s}] {time.time()-t_m:.1f}s | all_cands n={fw_m['n']}, NAV={fw_m['nav']:.2f}, ex5={fw_m['ex_top5_nav']:.2f}, MDD={fw_m['daily_mdd_pct']}%, Sharpe={fw_m['daily_sharpe']}")

        if mname in ("R2_Mech130_Guarded", "R2_Mech_Plus_Dyn20x19") and fw_m["nav"] > best_all_cands_nav:
            best_all_cands_nav = fw_m["nav"]
            best_model_name = mname
            best_all_cands_df = slot_dfs["all_cands"]

        _collect_freq(cmeta.get("snapshots", []), mname)

    # 4. Physical 2024-12-31 Truncation Zero-Leakage Proof on Road 2 (Native + Dyn20x19)
    print("  [Trunc 2024-12-31] Running Road 2 physical truncation verification ...")
    t_tr = time.time()
    m_trunc = w2f.load_master_with_sim_cols("2024-12-31")
    m_trunc = w2f.attach_pit_community_1d_burst(m_trunc, cal_dts, end_cutoff="2024-12-31")
    m_trunc, _, _ = w2f.build_mechanism_interactions(m_trunc)
    m_trunc, _ = _add_strategy_dummies_and_v20_margin(m_trunc)

    tnat_r2 = wf.verify_truncation_zero_leakage(
        m_full, feat_mech130, mode="A", cutoff="2024-12-31", score_threshold="all_cands",
        v20_ctx=v20_ctx, wf_start_date="2023-01-03", min_warmup_trades=80, recalc_freq="daily", top_k=12,
    )
    # Also Dyn20x19 truncation check (reuse cached full-run scored df + slot df, recompute truncated <= 2024-12-31 from scratch)
    df_t_h = wfm.prepare_hygiene_and_net_ret(m_trunc, fee_rt=0.0030)
    sf_d = sf_d_cached
    st_d, _ = w2f.run_expanding_interaction_loop(
        df_t_h, mech_cols=feat_mech130, base_cols=base_cols, mode="scorecard_0_100",
        wf_start_date="2023-01-03", min_warmup_trades=80, recalc_freq="daily", top_k=12, min_k=5,
        max_corr=0.65, min_t_stat=1.0, min_t_stat_dyn=2.6, min_synergy_t=1.6, shrink_tau=20.0,
    )
    slot_f_d = slot_f_d_cached
    _, slot_t_d = wfm.select_single_slot_trades(st_d, score_col="wf_score", threshold=None, wf_only=True)
    sf_le = sf_d[sf_d["buy_date"] <= "2024-12-31"].sort_values(["buy_date", "code"]).reset_index(drop=True)
    st_le = st_d.sort_values(["buy_date", "code"]).reset_index(drop=True)
    dyn_sc_diff = float(np.max(np.abs(sf_le["wf_score"].fillna(-999.0).to_numpy(float) - st_le["wf_score"].fillna(-999.0).to_numpy(float))))
    tf_le = slot_f_d[slot_f_d["exit_date"] <= "2024-12-31"].sort_values(["buy_date", "code"]).reset_index(drop=True)
    tt_le = slot_t_d[slot_t_d["exit_date"] <= "2024-12-31"].sort_values(["buy_date", "code"]).reset_index(drop=True)
    dyn_ret_diff = float(np.max(np.abs(tf_le["net_ret"].to_numpy(float) - tt_le["net_ret"].to_numpy(float)))) if len(tf_le) else 0.0
    assert tnat_r2["max_abs_score_diff"] == 0.0 and tnat_r2["max_abs_ret_diff"] == 0.0
    assert dyn_sc_diff == 0.0 and dyn_ret_diff == 0.0
    print(f"    Road 2 Trunc 2024-12-31 ({time.time()-t_tr:.1f}s): native=0.0/0.0 | dyn20x19={dyn_sc_diff}/{dyn_ret_diff}")

    rss_mb = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024), 2)
    out_summary = _sanitize({
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t_all, 2),
        "peak_rss_mb": rss_mb,
        "best_pure_road2_model": best_model_name,
        "road2_models": road2_models,
        "truncation_2024_12_31_proof": {
            "native_mech130": tnat_r2,
            "dyn20x19": {
                "n_rows_checked": int(len(sf_le)),
                "n_trades_exiting_le_cutoff": int(len(tf_le)),
                "max_abs_score_diff": dyn_sc_diff,
                "max_abs_ret_diff": dyn_ret_diff,
                "zero_leakage_pass": True,
            },
        },
        "factor_frequency_rows": factor_freq_rows,
    })
    with open(f"{OUT_DIR}/w2a4_road2_summary.json", "w", encoding="utf-8") as f:
        json.dump(out_summary, f, ensure_ascii=False, indent=2, allow_nan=False)
    if best_all_cands_df is not None:
        best_all_cands_df.drop(columns=[c for c in best_all_cands_df.columns if c.startswith("mtm")], errors="ignore").to_parquet(
            f"{OUT_DIR}/_cache_best_road2_trades.parquet", index=False
        )
    print(f"[W2A4 Road 2 DONE in {out_summary['elapsed_sec']}s | Peak RSS={rss_mb}MB] -> {OUT_DIR}/w2a4_road2_summary.json")


if __name__ == "__main__":
    main()

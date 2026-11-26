#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 2B-1 Step 2: Module 2 Full Grid Sweep (4 Pools x 4 Entries x 3 Exits x top_k=8/12/15)
plus Exact Daily Walk-Forward Verification (`recalc_freq='daily'`, `perm_n=1000`, V20 empty-slot audit).
Zero yfinance (D12). Zero cap10m. Internal threads <= 1. Peak RSS < 0.8 GB.
"""
import os
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

import json
import resource
import sys
import time
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave2b/w2b1_20cm_surge10_19_scorecard"
if OUT_DIR not in sys.path:
    sys.path.insert(0, OUT_DIR)

import w2b1_core_lib as lib
import wf_scorecard_engine as wf

THRESHOLDS = ("all_cands", "top20", "top10", "top5", 75, 80, 85)


def _extract_grid_rows(track: str, pool: str, entry: str, exit_r: str, top_k: int, feat_set: str, recalc: str, res: dict) -> list[dict]:
    rows = []
    th_map = res["threshold_results"]
    for row in res["summary_table"].to_dict("records"):
        th = row["threshold"]
        ev = th_map[th]["metrics"]
        fw = ev["windows"].get("FULL_WF", {})
        y23 = ev["windows"].get("Y2023", {})
        y24 = ev["windows"].get("Y2024", {})
        y25 = ev["windows"].get("Y2025", {})
        y26 = ev["windows"].get("Y2026", {})
        y2526 = ev["windows"].get("Y2025_2026", {})
        rows.append({
            "track": track,
            "pool": pool,
            "entry": entry,
            "exit_rule": exit_r,
            "top_k": int(top_k),
            "feature_set": feat_set,
            "recalc_freq": recalc,
            "threshold": th,
            "wf_actual_start": res["meta"]["wf_actual_start"],
            "n_wf_cands": res["meta"]["n_wf_candidates"],
            "n_pass": row["n_pass"],
            "n_trades": row["n_trades"],
            "wr_pct": row["wr_pct"],
            "plr": row["plr"],
            "mean_pct": row["mean_pct"],
            "nav_wf": row["nav_wf"],
            "eq_nav_wf": fw.get("eq_nav", 1.0),
            "ex3_wf": row["ex3_wf"],
            "ex5_wf": row["ex5_wf"],
            "mdd_pct": row["mdd_pct"],
            "sharpe": row["sharpe"],
            "calmar": fw.get("daily_calmar", 0.0),
            "exposure_pct": fw.get("exposure_pct", 0.0),
            "excess_csi_pp": row["excess_csi_pp"],
            "excess_ew_pp": row["excess_ew_pp"],
            "nav_2023": y23.get("nav", 1.0),
            "nav_2024": y24.get("nav", 1.0),
            "nav_2025": y25.get("nav", 1.0),
            "nav_2026": y26.get("nav", 1.0),
            "n_2026": y26.get("n", 0),
            "nav_2526": row["nav_2526"],
            "ex3_2526": row["ex3_2526"],
            "ex5_2526": y2526.get("ex_top5_nav", 1.0),
            "perm_sd_p": row["perm_sd_p"],
            "perm_any_p": row["perm_any_p"],
        })
    return rows


def main():
    t_all = time.time()
    df = pd.read_parquet(f"{OUT_DIR}/w2b1_cand_pool_pit.parquet")
    cat = json.load(open(f"{OUT_DIR}/w2b1_feature_catalog.json", encoding="utf-8"))
    all_fcols = cat["feature_cols"]
    core_fcols = [c for c in lib.CORE_96_FEATURES if c in df.columns]
    assert len(core_fcols) == len(lib.CORE_96_FEATURES), f"Missing core cols: {set(lib.CORE_96_FEATURES) - set(core_fcols)}"
    v20_ctx = wf.load_v20_reference_context(lib.WAVE1)

    print(f"[Pass 1: Mode A Full 144-Run Grid] Pools=4 x Entries=4 x Exits=3 x top_k=(8,12,15) | core_feats={len(core_fcols)}, all_feats={len(all_fcols)}")

    pass1_rows = []
    t_p1 = time.time()
    run_idx = 0
    for pn, _ in lib.POOL_SPECS:
        for en, _ in lib.ENTRY_SPECS:
            for ex in lib.EXIT_SPECS:
                sub = lib.slice_pool_entry_exit(df, pn, en, ex)
                if len(sub) < 120:
                    continue
                for tk in (8, 12, 15):
                    run_idx += 1
                    res = wf.run_wf_scorecard_new_strategy(
                        sub, core_fcols, v20_ctx=v20_ctx,
                        wf_start_date="2023-01-03", min_warmup_trades=80, min_warmup_trades_rare=50,
                        min_warmup_months=18, recalc_freq="monthly", top_k=tk, min_k=5,
                        max_corr=0.65, min_t_stat=1.0, shrink_tau=20.0, fee_rt=0.0,
                        thresholds=THRESHOLDS, eval_v20_patch=False, perm_n=150,
                    )
                    pass1_rows.extend(_extract_grid_rows("ModeA_Direct", pn, en, ex, tk, f"core_{len(core_fcols)}", "monthly", res))
                    if run_idx % 18 == 0:
                        best_so_far = max(pass1_rows, key=lambda r: r["nav_wf"] if r["n_trades"] >= 30 else 0.0)
                        print(f"  Progress {run_idx}/144 in {time.time()-t_p1:.1f}s | best(n>=30): {best_so_far['pool']}/{best_so_far['entry']}/{best_so_far['exit_rule']} k={best_so_far['top_k']} thr={best_so_far['threshold']} -> nav={best_so_far['nav_wf']:.3f}x ex5={best_so_far['ex5_wf']:.3f}x 2526={best_so_far['nav_2526']:.3f}x")

    p1_df = pd.DataFrame(pass1_rows)
    p1_df.to_csv(f"{OUT_DIR}/_mode_a_pass1_monthly_grid.csv", index=False)
    print(f"[Pass 1 Done] {len(p1_df)} rows in {time.time()-t_p1:.1f}s")

    # Identify top diverse finalists + best per (pool, entry) for exact DAILY WF verification (perm_n=1000 + V20 patch)
    sub_sel = p1_df[(p1_df["threshold"] != "all_cands") & (p1_df["n_trades"] >= 20)].copy()
    sub_sel["rank_score"] = sub_sel["sharpe"] + 0.5 * np.log(np.maximum(0.05, sub_sel["ex5_wf"])) + 0.3 * np.log(np.maximum(0.05, sub_sel["nav_2526"]))
    # Top 12 distinct (pool, entry, exit, top_k) combos overall + best per pool
    top_combos = []
    seen = set()
    for limit, grp_df in [
        (8, sub_sel.sort_values("rank_score", ascending=False)),
        (14, sub_sel.sort_values(["pool", "rank_score"], ascending=[True, False]).groupby("pool").head(2)),
        (18, sub_sel.sort_values(["entry", "rank_score"], ascending=[True, False]).groupby("entry").head(2)),
    ]:
        for r in grp_df.itertuples(index=False):
            key = (r.pool, r.entry, r.exit_rule, int(r.top_k))
            if key not in seen:
                seen.add(key)
                top_combos.append(key)
            if len(top_combos) >= limit:
                break

    # Ensure at least top StrongMainline & TypeA & TypeB & FullPool cells are checked in daily mode
    must_check = [
        ("P1_Strong", "E4_deep", "X3_20cm_4Branch", 12),
        ("P1_Strong", "E3_weak", "X2_T2_Close", 12),
        ("P3_TypeA", "E4_deep", "X2_T2_Close", 12),
        ("P3_TypeA", "E3_weak", "X2_T2_Close", 12),
        ("P2_TypeB", "E4_deep", "X1_T1_Close", 12),
    ]
    for mk in must_check:
        if mk not in seen:
            seen.add(mk)
            top_combos.append(mk)

    print(f"\n[Pass 2: Daily Walk-Forward Verification (`recalc_freq='daily'`, `perm_n=1000`)] {len(top_combos)} finalist combos...")
    daily_rows = []
    daily_details = {}
    t_p2 = time.time()

    for idx_c, (pn, en, ex, tk) in enumerate(top_combos, start=1):
        sub = lib.slice_pool_entry_exit(df, pn, en, ex)
        # Run core_96 daily, plus all_232 daily on top 4
        feat_sets = [(f"core_{len(core_fcols)}", core_fcols)]
        if idx_c <= 4:
            feat_sets.append((f"all_{len(all_fcols)}", all_fcols))

        for fs_lbl, fcols in feat_sets:
            t_run = time.time()
            res_d = wf.run_wf_scorecard_new_strategy(
                sub, fcols, v20_ctx=v20_ctx,
                wf_start_date="2023-01-03", min_warmup_trades=80, min_warmup_trades_rare=50,
                min_warmup_months=18, recalc_freq="daily", top_k=tk, min_k=5,
                max_corr=0.65, min_t_stat=1.0, shrink_tau=20.0, fee_rt=0.0,
                thresholds=THRESHOLDS, eval_v20_patch=False, perm_n=1000,
            )
            daily_rows.extend(_extract_grid_rows("ModeA_Daily", pn, en, ex, tk, fs_lbl, "daily", res_d))

            # Full V20 empty-slot audit on top20, top10, top5, abs_75, abs_80
            wf_cands = res_d["scored_df"][res_d["scored_df"]["wf_in_window"]].copy()
            patch_audits = {}
            for tname in ("top20", "top10", "top5", "abs_75", "abs_80"):
                tr_obj = res_d["threshold_results"][tname]
                if not tr_obj["pass_df"].empty:
                    pa_res = lib.compute_full_v20_patch_audit(
                        tr_obj["pass_df"], tr_obj["slot_df"], wf_cands, v20_ctx,
                        wf_start_dt=res_d["meta"]["wf_actual_start"], end_dt_patch="2026-11-16", perm_n=1000,
                    )
                    patch_audits[tname] = {
                        "mode1_combined": {k: v for k, v in pa_res["mode1_strict_combined_no_peek"].items() if k != "skipped_v20_trades"},
                        "mode2_standalone": pa_res["mode2_empty_slot_standalone"],
                        "same_exposure_and_v20_corr": pa_res["same_exposure_and_v20_corr"],
                        "empty_slot_permutation_1000": pa_res["empty_slot_permutation_1000"],
                    }

            key_str = f"{pn}__{en}__{ex}__k{tk}__{fs_lbl}"
            daily_details[key_str] = {
                "meta": {k: v for k, v in res_d["meta"].items() if k != "snapshots"},
                "summary": res_d["summary_table"].to_dict("records"),
                "v20_empty_patch_by_threshold": patch_audits,
            }
            best_t = res_d["summary_table"]
            best_t = best_t[best_t["threshold"] != "all_cands"].sort_values("nav_wf", ascending=False).head(1)
            bt_str = ""
            if not best_t.empty:
                r0 = best_t.iloc[0]
                bt_str = f"best={r0['threshold']}(n={r0['n_trades']},wr={r0['wr_pct']}%,nav={r0['nav_wf']:.3f}x,ex5={r0['ex5_wf']:.3f}x,2526={r0['nav_2526']:.3f}x,p={r0['perm_sd_p']:.3f})"
            print(f"  [{idx_c}/{len(top_combos)}] {key_str} ({time.time()-t_run:.1f}s) | {bt_str}")

    d_df = pd.DataFrame(daily_rows)
    d_df.to_csv(f"{OUT_DIR}/_mode_a_pass2_daily_finalists.csv", index=False)
    with open(f"{OUT_DIR}/_mode_a_daily_details.json", "w", encoding="utf-8") as f:
        json.dump(lib.sanitize(daily_details), f, ensure_ascii=False, indent=2)

    rss_mb = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1048576.0, 1)
    print(f"\n[Mode A Complete in {time.time()-t_all:.1f}s | Peak RSS={rss_mb}MB]")


if __name__ == "__main__":
    main()

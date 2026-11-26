#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 2B-1 Step 3: Module 3 Two-Step Mine-Removal + Dragon-Hunting Scorecard +
Module 4 V20.0 Empty-Slot Audit + 2024-12-31 Physical Truncation Proof (`max_abs_diff == 0.0`).
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


def run_two_step_pipeline(
    sub_df: pd.DataFrame,
    fcols: list[str],
    v20_ctx: dict,
    mine_mode: str = "t1t2_7pct",
    recalc_freq: str = "monthly",
    top_k_mine: int = 10,
    top_k_dragon: int = 12,
    blacklist_pct: float = 20.0,
    perm_n: int = 150,
    eval_v20: bool = False,
) -> dict:
    """Strictly causal 2-step pipeline: Mine-Removal (exit_date < t) -> Safe Pool -> Dragon Scorecard."""
    mined_df, mine_meta = lib.run_causal_mine_removal(
        sub_df, fcols, mine_mode=mine_mode, recalc_freq=recalc_freq,
        mine_start_date="2021-09-01", min_warmup_trades=80, min_warmup_months=6,
        top_k_mine=top_k_mine, blacklist_pct=blacklist_pct,
    )
    safe_df = mined_df[mined_df["is_safe_causal"]].copy().reset_index(drop=True)
    if len(safe_df) < 100:
        return {"empty": True, "mine_meta": mine_meta}

    dragon_res = wf.run_wf_scorecard_new_strategy(
        safe_df, fcols, v20_ctx=v20_ctx,
        wf_start_date="2023-01-03", min_warmup_trades=80, min_warmup_trades_rare=45,
        min_warmup_months=18, recalc_freq=recalc_freq, top_k=top_k_dragon, min_k=5,
        max_corr=0.65, min_t_stat=1.0, shrink_tau=20.0, fee_rt=0.0,
        thresholds=THRESHOLDS, eval_v20_patch=False, perm_n=perm_n,
    )

    patch_audits = {}
    if eval_v20:
        wf_cands = dragon_res["scored_df"][dragon_res["scored_df"]["wf_in_window"]].copy()
        for tname in ("top20", "top10", "top5", "abs_75", "abs_80"):
            tr_obj = dragon_res["threshold_results"][tname]
            if not tr_obj["pass_df"].empty:
                pa_res = lib.compute_full_v20_patch_audit(
                    tr_obj["pass_df"], tr_obj["slot_df"], wf_cands, v20_ctx,
                    wf_start_dt=dragon_res["meta"]["wf_actual_start"], end_dt_patch="2026-11-16", perm_n=perm_n,
                )
                patch_audits[tname] = {
                    "mode1_combined": {k: v for k, v in pa_res["mode1_strict_combined_no_peek"].items() if k != "skipped_v20_trades"},
                    "mode2_standalone": pa_res["mode2_empty_slot_standalone"],
                    "same_exposure_and_v20_corr": pa_res["same_exposure_and_v20_corr"],
                    "empty_slot_permutation_1000": pa_res["empty_slot_permutation_1000"],
                }

    return {
        "empty": False,
        "mine_meta": mine_meta,
        "mined_df": mined_df,
        "dragon_res": dragon_res,
        "v20_patch_audits": patch_audits,
    }


def _rows_from_two_step(track: str, pn: str, en: str, ex: str, mine_mode: str, tk: int, fs_lbl: str, recalc: str, out: dict) -> list[dict]:
    if out.get("empty"):
        return []
    res = out["dragon_res"]
    mm = out["mine_meta"]
    th_map = res["threshold_results"]
    rows = []
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
            "pool": pn,
            "entry": en,
            "exit_rule": ex,
            "mine_mode": mine_mode,
            "top_k": int(tk),
            "feature_set": fs_lbl,
            "recalc_freq": recalc,
            "threshold": th,
            "wf_actual_start": res["meta"]["wf_actual_start"],
            "mine_blacklist_pct": mm["wf_blacklist_pct"],
            "mine_rate_blk_pct": mm["mine_rate_blacklisted_pct"],
            "mine_rate_safe_pct": mm["mine_rate_safe_pct"],
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
    v20_ctx = wf.load_v20_reference_context(lib.WAVE1)

    print(f"[Module 3 Pass 1: Two-Step Mine-Removal + Dragon-Hunting] 4 Pools x 4 Entries x 3 Exits x 2 Mine Modes (monthly screen)...")
    m1_rows = []
    mine_diagnostics = {}
    t1 = time.time()
    idx_r = 0

    for pn, _ in lib.POOL_SPECS:
        for en, _ in lib.ENTRY_SPECS:
            for ex in lib.EXIT_SPECS:
                sub = lib.slice_pool_entry_exit(df, pn, en, ex)
                if len(sub) < 220:
                    continue
                for mm_mode in ("t1t2_7pct", "self_7pct"):
                    idx_r += 1
                    out = run_two_step_pipeline(
                        sub, core_fcols, v20_ctx, mine_mode=mm_mode, recalc_freq="monthly",
                        top_k_mine=10, top_k_dragon=12, blacklist_pct=20.0, perm_n=150, eval_v20=False,
                    )
                    m1_rows.extend(_rows_from_two_step("ModeM_MineDragon", pn, en, ex, mm_mode, 12, f"core_{len(core_fcols)}", "monthly", out))
                    if not out.get("empty"):
                        mine_diagnostics[f"{pn}__{en}__{ex}__{mm_mode}"] = out["mine_meta"]
                    if idx_r % 16 == 0:
                        print(f"  Progress {idx_r} runs in {time.time()-t1:.1f}s")

    m1_df = pd.DataFrame(m1_rows)
    m1_df.to_csv(f"{OUT_DIR}/_mode3_mine_monthly_grid.csv", index=False)
    print(f"[Module 3 Pass 1 Done] {len(m1_df)} rows in {time.time()-t1:.1f}s")

    # Select top diverse Module 3 finalists + test top_k=8,12,15 in DAILY mode (perm_n=1000, V20 audit)
    sub_sel = m1_df[(m1_df["threshold"] != "all_cands") & (m1_df["n_trades"] >= 20)].copy()
    sub_sel["rank_score"] = sub_sel["sharpe"] + 0.5 * np.log(np.maximum(0.05, sub_sel["ex5_wf"])) + 0.3 * np.log(np.maximum(0.05, sub_sel["nav_2526"]))
    top_m3 = []
    seen = set()
    for limit, gdf in [
        (6, sub_sel.sort_values("rank_score", ascending=False)),
        (10, sub_sel.sort_values(["pool", "rank_score"], ascending=[True, False]).groupby("pool").head(2)),
        (12, sub_sel.sort_values(["entry", "rank_score"], ascending=[True, False]).groupby("entry").head(2)),
    ]:
        for r in gdf.itertuples(index=False):
            k = (r.pool, r.entry, r.exit_rule, r.mine_mode)
            if k not in seen:
                seen.add(k)
                top_m3.append(k)
            if len(top_m3) >= limit:
                break

    for mk in [
        ("P0_Full", "E4_deep", "X1_T1_Close", "t1t2_7pct"),
        ("P1_Strong", "E4_deep", "X3_20cm_4Branch", "t1t2_7pct"),
        ("P3_TypeA", "E4_deep", "X2_T2_Close", "t1t2_7pct"),
    ]:
        if mk not in seen:
            seen.add(mk)
            top_m3.append(mk)

    print(f"\n[Module 3 Pass 2: Daily Two-Step Walk-Forward (`recalc_freq='daily'`, `perm_n=1000`)] {len(top_m3)} finalists...")
    m2_rows = []
    m2_details = {}
    for idx_c, (pn, en, ex, mm_mode) in enumerate(top_m3, start=1):
        sub = lib.slice_pool_entry_exit(df, pn, en, ex)
        k_list = (8, 12, 15) if idx_c <= 3 else (12,)
        for tk in k_list:
            t_r = time.time()
            out_d = run_two_step_pipeline(
                sub, core_fcols, v20_ctx, mine_mode=mm_mode, recalc_freq="daily",
                top_k_mine=10, top_k_dragon=tk, blacklist_pct=20.0, perm_n=1000, eval_v20=True,
            )
            m2_rows.extend(_rows_from_two_step("ModeM_Daily", pn, en, ex, mm_mode, tk, f"core_{len(core_fcols)}", "daily", out_d))
            if not out_d.get("empty"):
                dr = out_d["dragon_res"]
                kstr = f"{pn}__{en}__{ex}__{mm_mode}__k{tk}"
                m2_details[kstr] = {
                    "mine_meta": out_d["mine_meta"],
                    "dragon_meta": {k: v for k, v in dr["meta"].items() if k != "snapshots"},
                    "summary": dr["summary_table"].to_dict("records"),
                    "v20_empty_patch_by_threshold": out_d["v20_patch_audits"],
                }
                bt = dr["summary_table"]
                bt = bt[bt["threshold"] != "all_cands"].sort_values("nav_wf", ascending=False).head(1)
                bs = f"best={bt.iloc[0]['threshold']}(n={bt.iloc[0]['n_trades']},nav={bt.iloc[0]['nav_wf']:.3f}x,ex5={bt.iloc[0]['ex5_wf']:.3f}x,p={bt.iloc[0]['perm_sd_p']:.3f})" if not bt.empty else ""
                print(f"  [{idx_c}/{len(top_m3)}] {kstr} ({time.time()-t_r:.1f}s) | mine:blk={out_d['mine_meta']['mine_rate_blacklisted_pct']}% vs safe={out_d['mine_meta']['mine_rate_safe_pct']}% | {bs}")

    m2_df = pd.DataFrame(m2_rows)
    m2_df.to_csv(f"{OUT_DIR}/_mode3_mine_daily_finalists.csv", index=False)
    with open(f"{OUT_DIR}/_mode3_mine_daily_details.json", "w", encoding="utf-8") as f:
        json.dump(lib.sanitize(m2_details), f, ensure_ascii=False, indent=2)
    with open(f"{OUT_DIR}/_mode3_mine_diagnostics.json", "w", encoding="utf-8") as f:
        json.dump(lib.sanitize(mine_diagnostics), f, ensure_ascii=False, indent=2)

    # 2024-12-31 Physical Truncation Proof on BOTH Mode A Daily AND Two-Step Mine-Removal Daily
    print("\n[Truncation Proof 2024-12-31 on Daily Mode A & Daily Two-Step Mine-Dragon]...")
    sub_tp = lib.slice_pool_entry_exit(df, "P3_TypeA", "E4_deep", "X3_20cm_4Branch")
    trunc_mode_a = wf.verify_truncation_zero_leakage(
        sub_tp, core_fcols, mode="A", cutoff="2024-12-31", score_threshold="top20",
        v20_ctx=v20_ctx, wf_start_date="2023-01-03", min_warmup_trades=80,
        min_warmup_trades_rare=50, recalc_freq="daily", top_k=12, fee_rt=0.0,
    )

    # Physical truncation proof for chained Two-Step Mine-Removal + Dragon-Hunting (daily)
    sub_tp_tr = sub_tp[sub_tp["buy_date"] <= "2024-12-31"].copy().reset_index(drop=True)
    out_f = run_two_step_pipeline(sub_tp, core_fcols, v20_ctx, mine_mode="t1t2_7pct", recalc_freq="daily", perm_n=50, eval_v20=False)
    out_t = run_two_step_pipeline(sub_tp_tr, core_fcols, v20_ctx, mine_mode="t1t2_7pct", recalc_freq="daily", perm_n=50, eval_v20=False)

    mf = out_f["mined_df"]
    mf_le = mf[mf["buy_date"] <= "2024-12-31"].sort_values(["buy_date", "code"]).reset_index(drop=True)
    mt_le = out_t["mined_df"].sort_values(["buy_date", "code"]).reset_index(drop=True)
    assert len(mf_le) == len(mt_le)
    mine_sc_diff = float(np.max(np.abs(mf_le["wf_mine_safety_score"].fillna(-999).to_numpy(float) - mt_le["wf_mine_safety_score"].fillna(-999).to_numpy(float))))

    df_f = out_f["dragon_res"]["scored_df"]
    df_f_le = df_f[df_f["buy_date"] <= "2024-12-31"].sort_values(["buy_date", "code"]).reset_index(drop=True)
    df_t_le = out_t["dragon_res"]["scored_df"].sort_values(["buy_date", "code"]).reset_index(drop=True)
    assert len(df_f_le) == len(df_t_le)
    drag_sc_diff = float(np.max(np.abs(df_f_le["wf_score"].fillna(-999).to_numpy(float) - df_t_le["wf_score"].fillna(-999).to_numpy(float))))

    tr_f = out_f["dragon_res"]["threshold_results"]["top20"]["slot_df"]
    tr_f = tr_f[tr_f["exit_date"] <= "2024-12-31"].sort_values(["buy_date", "code"]).reset_index(drop=True)
    tr_t = out_t["dragon_res"]["threshold_results"]["top20"]["slot_df"]
    tr_t = tr_t[tr_t["exit_date"] <= "2024-12-31"].sort_values(["buy_date", "code"]).reset_index(drop=True)
    assert len(tr_f) == len(tr_t)
    drag_ret_diff = float(np.max(np.abs(tr_f["net_ret"].to_numpy(float) - tr_t["net_ret"].to_numpy(float)))) if len(tr_f) else 0.0
    assert mine_sc_diff == 0.0 and drag_sc_diff == 0.0 and drag_ret_diff == 0.0

    trunc_proof = {
        "mode_a_daily_20241231": trunc_mode_a,
        "two_step_mine_dragon_daily_20241231": {
            "cutoff": "2024-12-31",
            "n_mine_rows_checked": int(len(mf_le)),
            "n_dragon_safe_rows_checked": int(len(df_f_le)),
            "n_trades_exiting_le_cutoff": int(len(tr_f)),
            "max_abs_mine_score_diff": mine_sc_diff,
            "max_abs_dragon_score_diff": drag_sc_diff,
            "max_abs_ret_diff": drag_ret_diff,
            "zero_leakage_pass": True,
        },
    }
    with open(f"{OUT_DIR}/_truncation_proof_daily.json", "w", encoding="utf-8") as f:
        json.dump(lib.sanitize(trunc_proof), f, ensure_ascii=False, indent=2)

    rss_mb = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1048576.0, 1)
    print(f"[TRUNC PASS] ModeA diff={trunc_mode_a['max_abs_score_diff']}/{trunc_mode_a['max_abs_ret_diff']} | TwoStep diff={mine_sc_diff}/{drag_sc_diff}/{drag_ret_diff} | Peak RSS={rss_mb}MB in {time.time()-t_all:.1f}s")


if __name__ == "__main__":
    main()

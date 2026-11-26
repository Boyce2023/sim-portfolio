#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 2B-3: Low-RAM (<1.5GB) Expanding Walk-Forward Scorecard Runner & Auditor.
Evaluates all 4 tracks across multiple sub-definitions, horizons, and causal thresholds:
  - Track A: Sector Climax Day-1 (A1_KPL & A2_CSRC; T+1, T+2, T+3) [all daily recalc]
  - Track B: Strong Mainline Trend Shrinking Pullback (B1_MAINLINE & B2_ALLTREND; T+2, T+3, T+5)
             + daily recalc verification on B1_MAINLINE_T2 & B2_ALLTREND_T3
  - Track C: 2-5d Laggard Second-Tier Catch-Up (C0_ALL, C1_ACCEL, C2_BROKEN; T+2, T+3, T+5) [all daily recalc]
  - Track D: Cold Low-Crowding + Vol Compression Seesaw (D1_COLD_STRICT, D2_SEESAW_BROAD, D3_NO_CROWD_DIV; T+3, T+4, T+5) [all daily recalc]

Produces under OUT_DIR:
  - w2b3_tracks_compare.csv
  - w2b3_audit.json
  - w2b3_best_trades.parquet

Zero yfinance (D12). Zero cap10m. Threads <= 1. Peak RSS < 2.0 GB. Fee = 0.30% bilateral.
"""
import gc
import json
import math
import os
import resource
import sys
import time
import warnings

import numpy as np
import pandas as pd
import pyarrow as pa

warnings.filterwarnings("ignore")

os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
pa.set_cpu_count(1)
pa.set_io_thread_count(1)

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True

BASE_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave2b/w2b3_theme_pullback_laggard_scorecard"
CACHE_DIR = f"{OUT_DIR}/_cache_pools"

if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
if OUT_DIR not in sys.path:
    sys.path.insert(0, OUT_DIR)

import wf_scorecard_engine as wf
import _wf_v20_patch as wfp
import w2b3_build_pools as bp


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


def _compute_corr_and_mtm_diag(slot_df: pd.DataFrame, v20_ctx: dict, wf_start: str, stk_map: dict) -> dict:
    """Compute exact daily MTM returns, MDD, Sharpe, and V20/CSI300 correlations over canonical V20 window."""
    if slot_df.empty:
        return {
            "exact_mtm_nav": 1.0, "exact_mtm_mdd_pct": 0.0, "exact_mtm_sharpe": 0.0,
            "corr_v20_daily_all": 0.0, "corr_v20_daily_active": 0.0,
            "corr_v20_monthly": 0.0, "corr_csi300_daily": 0.0,
            "empty_slot_trade_pct": 0.0, "bull_trade_pct": 0.0, "bull_wr_pct": 0.0, "bull_mean_pct": 0.0,
        }
    end_v20 = "2026-11-16"
    cal_df = v20_ctx["calendar_5y"]
    cal_win = cal_df[cal_df["trade_date"].between(wf_start, end_v20)].sort_values("trade_date").reset_index(drop=True)
    cal_dts = cal_win["trade_date"].tolist()
    emp_set = set(cal_win.loc[cal_win["v20_empty_slot"], "trade_date"])
    reg_map = dict(zip(cal_win["trade_date"], cal_win["regime_3bucket_t1"]))

    v20_led = v20_ctx["v20_ledger"]
    v20_win = v20_led[v20_led["buy_date"].between(wf_start, end_v20)].copy()
    v20_win["source"] = "v20"
    dr_v20, _ = wfp._build_combined_mtm(v20_win, cal_dts)

    slot_v20 = slot_df[slot_df["buy_date"].between(wf_start, end_v20)].copy()
    dr_tr, _ = bp.compute_exact_daily_mtm_series(slot_v20, cal_dts, fee_rt=0.0030, stk_map=stk_map)
    csi_r = cal_win["csi300_daily_ret"].to_numpy(float)

    curve = np.concatenate([[1.0], np.cumprod(1.0 + dr_tr)])
    pk = np.maximum.accumulate(curve)
    mtm_mdd = float(np.max((pk - curve) / pk) * 100.0)
    sd = float(np.std(dr_tr, ddof=1)) if len(dr_tr) > 1 else 0.0
    mtm_shp = float(np.mean(dr_tr) / sd * math.sqrt(242.0)) if sd > 1e-12 else 0.0
    mtm_nav = float(curve[-1])

    def _safe_corr(a, b):
        if len(a) < 5 or np.std(a) < 1e-12 or np.std(b) < 1e-12:
            return 0.0
        return float(np.corrcoef(a, b)[0, 1])

    c_all = _safe_corr(dr_tr, dr_v20)
    act_m = (np.abs(dr_tr) > 1e-9) | (np.abs(dr_v20) > 1e-9)
    c_act = _safe_corr(dr_tr[act_m], dr_v20[act_m])
    c_csi = _safe_corr(dr_tr, csi_r)

    mdf = pd.DataFrame({"ym": [d[:7] for d in cal_dts], "tr": dr_tr, "v20": dr_v20})
    mg = mdf.groupby("ym", as_index=False).agg(
        tr=("tr", lambda s: float(np.prod(1.0 + s) - 1.0)),
        v20=("v20", lambda s: float(np.prod(1.0 + s) - 1.0)),
    )
    c_mon = _safe_corr(mg["tr"].to_numpy(float), mg["v20"].to_numpy(float))

    emp_pct = float(slot_df["buy_date"].isin(emp_set).mean() * 100.0)
    reg_s = pd.Series([reg_map.get(d, "OTHER") for d in slot_df["buy_date"]])
    bull_m = reg_s == "主升"
    bull_pct = float(bull_m.mean() * 100.0)
    bull_rets = slot_df.loc[bull_m.values, "net_ret"].to_numpy(float)
    bull_wr = float((bull_rets > 0).mean() * 100.0) if len(bull_rets) else 0.0
    bull_mean = float(bull_rets.mean() * 100.0) if len(bull_rets) else 0.0

    return {
        "exact_mtm_nav": round(mtm_nav, 4),
        "exact_mtm_mdd_pct": round(mtm_mdd, 2),
        "exact_mtm_sharpe": round(mtm_shp, 3),
        "corr_v20_daily_all": round(c_all, 4),
        "corr_v20_daily_active": round(c_act, 4),
        "corr_v20_monthly": round(c_mon, 4),
        "corr_csi300_daily": round(c_csi, 4),
        "empty_slot_trade_pct": round(emp_pct, 2),
        "bull_trade_pct": round(bull_pct, 2),
        "bull_wr_pct": round(bull_wr, 2),
        "bull_mean_pct": round(bull_mean, 2),
    }


def _regime_breakdown(slot_df: pd.DataFrame, v20_ctx: dict) -> dict:
    if slot_df.empty:
        return {}
    cal = v20_ctx["calendar_ext"]
    rmap = dict(zip(cal["trade_date"], cal["regime_3bucket_t1"]))
    emap = dict(zip(cal["trade_date"], cal["v20_empty_slot"]))
    s = slot_df.copy()
    s["regime"] = [rmap.get(d, "OTHER") for d in s["buy_date"]]
    s["is_empty"] = [bool(emap.get(d, False)) for d in s["buy_date"]]
    out = {}
    for key, sub in [
        ("bull_主升", s[s["regime"] == "主升"]),
        ("osc_震荡", s[s["regime"] == "震荡"]),
        ("ice_冰点", s[s["regime"] == "冰点"]),
        ("empty_all", s[s["is_empty"]]),
        ("empty_bull", s[s["is_empty"] & (s["regime"] == "主升")]),
    ]:
        if sub.empty:
            out[key] = {"n": 0, "wr_pct": 0.0, "mean_pct": 0.0, "nav": 1.0}
        else:
            r = sub["net_ret"].to_numpy(float)
            out[key] = {
                "n": int(len(r)),
                "wr_pct": round(float((r > 0).mean() * 100.0), 2),
                "mean_pct": round(float(r.mean() * 100.0), 2),
                "nav": round(float(np.prod(1.0 + r)), 4),
            }
    return out


def _load_one_pool(pname: str, h: int) -> tuple[pd.DataFrame, list[str]]:
    df_raw = pd.read_parquet(f"{CACHE_DIR}/{pname}.parquet")
    df_raw["exit_date"] = df_raw[f"exit_date_T{h}"]
    df_raw["gross_ret"] = df_raw[f"gross_ret_T{h}"]
    df_raw = df_raw[df_raw["exit_date"].notna() & df_raw["gross_ret"].notna()].reset_index(drop=True)
    fcols = bp.get_track_features(df_raw, pname)
    return df_raw, fcols


def main():
    t_start = time.time()
    v20_ctx = wf.load_v20_reference_context(BASE_DIR)

    # Full experiment matrix (daily recalc on A1/A2/C/D; monthly + daily spot-verify on B)
    specs = [
        ("Track_A_ClimaxDay1", "A1_KPL", 1, "daily"),
        ("Track_A_ClimaxDay1", "A1_KPL", 2, "daily"),
        ("Track_A_ClimaxDay1", "A1_KPL", 3, "daily"),
        ("Track_A_ClimaxDay1", "A2_CSRC", 1, "daily"),
        ("Track_A_ClimaxDay1", "A2_CSRC", 2, "daily"),
        ("Track_A_ClimaxDay1", "A2_CSRC", 3, "daily"),
        ("Track_A_ClimaxDay1", "A2_CSRC", 3, "monthly"),

        ("Track_B_TrendPullback", "B1_MAINLINE", 2, "monthly"),
        ("Track_B_TrendPullback", "B1_MAINLINE", 3, "monthly"),
        ("Track_B_TrendPullback", "B1_MAINLINE", 5, "monthly"),
        ("Track_B_TrendPullback", "B2_ALLTREND", 2, "monthly"),
        ("Track_B_TrendPullback", "B2_ALLTREND", 3, "monthly"),
        ("Track_B_TrendPullback", "B2_ALLTREND", 5, "monthly"),
        ("Track_B_TrendPullback", "B2_ALLTREND", 3, "daily"),

        ("Track_C_LaggardCatchup", "C0_ALL", 2, "daily"),
        ("Track_C_LaggardCatchup", "C0_ALL", 3, "daily"),
        ("Track_C_LaggardCatchup", "C0_ALL", 5, "daily"),
        ("Track_C_LaggardCatchup", "C1_ACCEL", 2, "daily"),
        ("Track_C_LaggardCatchup", "C1_ACCEL", 3, "daily"),
        ("Track_C_LaggardCatchup", "C1_ACCEL", 5, "daily"),
        ("Track_C_LaggardCatchup", "C2_BROKEN", 2, "daily"),
        ("Track_C_LaggardCatchup", "C2_BROKEN", 3, "daily"),
        ("Track_C_LaggardCatchup", "C2_BROKEN", 5, "daily"),

        ("Track_D_ColdSeesaw", "D1_COLD_STRICT", 3, "daily"),
        ("Track_D_ColdSeesaw", "D1_COLD_STRICT", 4, "daily"),
        ("Track_D_ColdSeesaw", "D1_COLD_STRICT", 5, "daily"),
        ("Track_D_ColdSeesaw", "D2_SEESAW_BROAD", 3, "daily"),
        ("Track_D_ColdSeesaw", "D2_SEESAW_BROAD", 5, "daily"),
        ("Track_D_ColdSeesaw", "D3_NO_CROWD_DIV", 3, "daily"),
        ("Track_D_ColdSeesaw", "D3_NO_CROWD_DIV", 5, "daily"),
    ]

    # Preload price series ONLY once for candidate codes (RAM < 0.25 GB)
    all_codes = set()
    for pname in sorted({s[1] for s in specs}):
        c_ser = pd.read_parquet(f"{CACHE_DIR}/{pname}.parquet", columns=["code"])["code"]
        all_codes.update(c_ser.astype(str).str.zfill(6).unique())
    stk_map = bp.build_stk_px_map(all_codes)
    print(f"[Init] Preloaded price map for {len(stk_map)} codes | RSS={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1e9:.3f}GB")

    thresholds = ("all_cands", "top30", "top20", "top10", "top5", 70, 75, 80, 85)
    compare_rows = []
    track_details = {}
    best_candidates = {}  # key -> (rank_val, row, spec, regime_breakdown)

    for tg, pname, h, freq in specs:
        df_raw, fcols = _load_one_pool(pname, h)
        vkey = f"{pname}_T{h}_{freq}" if (pname == "A2_CSRC" and h == 3) or (pname == "B2_ALLTREND" and h == 3) else f"{pname}_T{h}"
        t0 = time.time()
        res = wf.run_wf_scorecard_new_strategy(
            df_raw,
            fcols,
            v20_ctx=v20_ctx,
            wf_start_date="2023-01-03",
            end_date="2026-11-25",
            min_warmup_trades=80,
            min_warmup_trades_rare=60,
            recalc_freq=freq,
            top_k=10,
            min_k=5,
            max_corr=0.65,
            min_t_stat=1.2,
            shrink_tau=20.0,
            fee_rt=0.0030,
            gross_ret_col="gross_ret",
            mtm_col=None,
            thresholds=thresholds,
            eval_v20_patch=True,
            perm_n=1000,
            seed=20261125,
        )
        el = round(time.time() - t0, 2)
        wf_act_start = res["meta"]["wf_actual_start"] or "2023-01-03"
        latest_card = res["meta"]["latest_scorecard"]

        wf_pool = res["scored_df"][res["scored_df"]["wf_in_window"] & res["scored_df"]["can_buy_hygiene"]]
        uncond_wf_mean = round(float(wf_pool["net_ret"].mean() * 100.0), 3) if not wf_pool.empty else 0.0
        uncond_wf_wr = round(float((wf_pool["net_ret"] > 0).mean() * 100.0), 2) if not wf_pool.empty else 0.0

        th_summaries = {}
        for th_name, tr in res["threshold_results"].items():
            ev = tr["metrics"]
            fw = ev["windows"].get("FULL_WF", {})
            y23 = ev["windows"].get("Y2023", {})
            y24 = ev["windows"].get("Y2024", {})
            y25 = ev["windows"].get("Y2025", {})
            y2526 = ev["windows"].get("Y2025_2026", {})
            y26 = ev["windows"].get("Y2026", {})
            perm = ev["permutation_1000"]
            slot_df = tr["slot_df"]

            if len(slot_df) >= 10:
                mtm_diag = _compute_corr_and_mtm_diag(slot_df, v20_ctx, wf_act_start, stk_map)
            else:
                mtm_diag = {
                    "exact_mtm_nav": fw.get("nav", 1.0), "exact_mtm_mdd_pct": fw.get("daily_mdd_pct", 0.0),
                    "exact_mtm_sharpe": fw.get("daily_sharpe", 0.0), "corr_v20_daily_all": 0.0,
                    "corr_v20_daily_active": 0.0, "corr_v20_monthly": 0.0, "corr_csi300_daily": 0.0,
                    "empty_slot_trade_pct": 0.0, "bull_trade_pct": 0.0, "bull_wr_pct": 0.0, "bull_mean_pct": 0.0,
                }

            patch = tr.get("v20_empty_patch")
            if patch:
                m1 = patch["mode1_strict_combined_no_peek"]
                m2_fw = patch["mode2_empty_slot_standalone"]["windows"].get("FULL_WF", {})
                m2_25 = patch["mode2_empty_slot_standalone"]["windows"].get("Y2025_2026", {})
                m2_26 = patch["mode2_empty_slot_standalone"]["windows"].get("Y2026", {})
                patch_row = {
                    "comb_nav_wf": m1["combined_with_patch"]["FULL_WF"].get("nav", 1.0),
                    "comb_nav_ratio": m1["delta_nav_ratio_full_wf"],
                    "comb_d_sharpe": m1["delta_sharpe_full_wf"],
                    "comb_d_mdd_pp": m1["delta_mdd_pp_full_wf"],
                    "comb_n_added": m1["n_patch_added"],
                    "comb_n_v20_skip": m1["n_v20_skipped_by_collision"],
                    "emp_n": m2_fw.get("n", 0),
                    "emp_wr_pct": m2_fw.get("wr_pct", 0.0),
                    "emp_mean_pct": m2_fw.get("mean_pct", 0.0),
                    "emp_nav_wf": m2_fw.get("nav", 1.0),
                    "emp_ex5_wf": m2_fw.get("ex_top5_nav", 1.0),
                    "emp_mdd_pct": m2_fw.get("daily_mdd_pct", 0.0),
                    "emp_nav_2526": m2_25.get("nav", 1.0),
                    "emp_nav_y26": m2_26.get("nav", 1.0),
                }
            else:
                patch_row = {
                    "comb_nav_wf": None, "comb_nav_ratio": None, "comb_d_sharpe": None,
                    "comb_d_mdd_pp": None, "comb_n_added": 0, "comb_n_v20_skip": 0,
                    "emp_n": 0, "emp_wr_pct": 0.0, "emp_mean_pct": 0.0, "emp_nav_wf": 1.0,
                    "emp_ex5_wf": 1.0, "emp_mdd_pct": 0.0, "emp_nav_2526": 1.0, "emp_nav_y26": 1.0,
                }

            row = {
                "track_group": tg, "pool": pname, "horizon_T": h, "variant": vkey,
                "recalc_freq": freq, "threshold": th_name,
                "n_cands_wf": len(wf_pool), "uncond_wf_mean_pct": uncond_wf_mean,
                "uncond_wf_wr_pct": uncond_wf_wr, "n_pass": tr["n_passing_cands"],
                "n_trades": fw.get("n", 0), "wr_pct": fw.get("wr_pct", 0.0),
                "plr": fw.get("plr", 0.0), "mean_pct": fw.get("mean_pct", 0.0),
                "nav_wf": fw.get("nav", 1.0), "eq_nav_wf": fw.get("eq_nav", 1.0),
                "ex3_wf": fw.get("ex_top3_nav", 1.0), "ex5_wf": fw.get("ex_top5_nav", 1.0),
                "mdd_pct": fw.get("daily_mdd_pct", 0.0), "trade_mdd_pct": fw.get("trade_mdd_pct", 0.0),
                "sharpe": fw.get("daily_sharpe", 0.0), "cagr_pct": fw.get("cagr_pct", 0.0),
                "excess_csi_pp": fw.get("excess_csi300_pp", 0.0), "excess_ew_pp": fw.get("excess_alla_ew_pp", 0.0),
                "nav_23": y23.get("nav", 1.0), "nav_24": y24.get("nav", 1.0), "nav_25": y25.get("nav", 1.0),
                "n_2526": y2526.get("n", 0), "wr_2526": y2526.get("wr_pct", 0.0),
                "nav_2526": y2526.get("nav", 1.0), "ex5_2526": y2526.get("ex_top5_nav", 1.0),
                "mdd_2526": y2526.get("daily_mdd_pct", 0.0), "excess_csi_2526_pp": y2526.get("excess_csi300_pp", 0.0),
                "n_y26": y26.get("n", 0), "wr_y26": y26.get("wr_pct", 0.0),
                "nav_y26": y26.get("nav", 1.0), "mdd_y26": y26.get("daily_mdd_pct", 0.0),
                "excess_csi_y26_pp": y26.get("excess_csi300_pp", 0.0),
                "perm_sd_p_nav": perm.get("same_day_p_nav", 1.0), "perm_sd_p_mean": perm.get("same_day_p_mean", 1.0),
                "perm_any_p_nav": perm.get("any_cand_day_p_nav", 1.0), "perm_any_p_mean": perm.get("any_cand_day_p_mean", 1.0),
                **mtm_diag, **patch_row,
            }
            compare_rows.append(row)
            th_summaries[th_name] = row

            # Candidate ranking (prefer daily recalc for winner selection!)
            if th_name != "all_cands" and fw.get("n", 0) >= 20:
                freq_bonus = 1.0 if freq == "daily" else 0.85
                rank_val = (
                    freq_bonus
                    * fw.get("nav", 1.0)
                    * (0.5 + 0.5 * min(1.5, fw.get("ex_top5_nav", 1.0)))
                    * (0.5 + 0.5 * min(1.5, y2526.get("nav", 1.0)))
                )
                best_candidates[f"{vkey}::{th_name}"] = (
                    rank_val, row, (tg, pname, h, freq, th_name), _regime_breakdown(slot_df, v20_ctx),
                )

        track_details[vkey] = {
            "track_group": tg, "pool": pname, "horizon_T": h, "recalc_freq": freq,
            "elapsed_sec": el, "n_input_rows": int(len(df_raw)), "n_features": int(len(fcols)),
            "wf_actual_start": wf_act_start, "n_rebuilds": res["meta"]["n_rebuilds"],
            "uncond_wf_mean_pct": uncond_wf_mean, "uncond_wf_wr_pct": uncond_wf_wr,
            "latest_scorecard_factors": [
                {
                    "name": f["name"], "t": f["t_cluster"], "shape": f["shape"],
                    "budget_pts": f["budget_pts"], "bin_pts": f["bin_pts"],
                    "bin_wr_pct": f["bin_wr_pct"], "bin_mean_pct": f["bin_mean_pct"],
                }
                for f in (latest_card["factors"] if latest_card else [])
            ],
            "thresholds": th_summaries,
        }
        top10_r = th_summaries.get("top10", {})
        abs75_r = th_summaries.get("abs_75", {})
        print(
            f"[{vkey:24s} | {el:5.1f}s] "
            f"top10(n={top10_r.get('n_trades',0):3d} nav={top10_r.get('nav_wf',1):.3f} ex5={top10_r.get('ex5_wf',1):.3f} 2526={top10_r.get('nav_2526',1):.3f}) | "
            f"abs75(n={abs75_r.get('n_trades',0):3d} nav={abs75_r.get('nav_wf',1):.3f} ex5={abs75_r.get('ex5_wf',1):.3f} 2526={abs75_r.get('nav_2526',1):.3f})"
        )
        del df_raw, res
        gc.collect()

    cmp_df = pd.DataFrame(compare_rows)
    cmp_path = f"{OUT_DIR}/w2b3_tracks_compare.csv"
    cmp_df.to_csv(cmp_path, index=False)

    # Pick overall best & per-track-group best
    best_by_group = {}
    for full_k, tup in best_candidates.items():
        tg = tup[2][0]
        if tg not in best_by_group or tup[0] > best_by_group[tg][0]:
            best_by_group[tg] = (tup[0], full_k, tup)

    overall_best_k = max(best_candidates.keys(), key=lambda k: best_candidates[k][0])
    _, best_row, best_spec, best_reg = best_candidates[overall_best_k]

    # Re-run ONLY the 4 track winners to save `w2b3_best_trades.parquet` & verify 2024-12-31 truncation!
    trunc_checks = {}
    for tg, (_, fk, tup) in sorted(best_by_group.items()):
        _, _, (tg_s, pn, hh, fr, thn), _ = tup
        d_raw, f_cols = _load_one_pool(pn, hh)
        th_arg = int(thn.split("_")[1]) if thn.startswith("abs_") else thn
        if fk == overall_best_k:
            res_best = wf.run_wf_scorecard_new_strategy(
                d_raw, f_cols, v20_ctx=v20_ctx, wf_start_date="2023-01-03", end_date="2026-11-25",
                min_warmup_trades=80, min_warmup_trades_rare=60, recalc_freq=fr, top_k=10, min_k=5,
                max_corr=0.65, min_t_stat=1.2, shrink_tau=20.0, fee_rt=0.0030, gross_ret_col="gross_ret",
                thresholds=(th_arg,), eval_v20_patch=False, perm_n=10,
            )
            best_slot_df = res_best["threshold_results"][thn]["slot_df"]
            best_slot_df.to_parquet(f"{OUT_DIR}/w2b3_best_trades.parquet", index=False)
            del res_best

        tr_chk = wf.verify_truncation_zero_leakage(
            d_raw, f_cols, mode="A", cutoff="2024-12-31", score_threshold=th_arg,
            v20_ctx=v20_ctx, wf_start_date="2023-01-03", min_warmup_trades=80,
            min_warmup_trades_rare=60, recalc_freq=fr, top_k=10, min_k=5,
            max_corr=0.65, min_t_stat=1.2, shrink_tau=20.0, fee_rt=0.0030, gross_ret_col="gross_ret",
        )
        trunc_checks[fk] = tr_chk
        assert tr_chk["zero_leakage_pass"] and tr_chk["max_abs_score_diff"] == 0.0 and tr_chk["max_abs_ret_diff"] == 0.0
        del d_raw
        gc.collect()

    rss_gb = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e9, 3)

    audit = _sanitize({
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_elapsed_sec": round(time.time() - t_start, 2),
        "peak_rss_gb": rss_gb,
        "d12_yfinance_imported": "yfinance" in sys.modules,
        "fee_rt_bilateral": 0.0030,
        "overall_best_key": overall_best_k,
        "overall_best_metrics": best_row,
        "overall_best_regime_breakdown": best_reg,
        "best_by_track_group": {
            tg: {"best_key": fk, "metrics": tup[1], "regime_breakdown": tup[3]}
            for tg, (_, fk, tup) in sorted(best_by_group.items())
        },
        "track_c_leader_state_comparison": {
            "C1_ACCEL_T3": track_details.get("C1_ACCEL_T3", {}).get("thresholds", {}).get("top10"),
            "C1_ACCEL_T5": track_details.get("C1_ACCEL_T5", {}).get("thresholds", {}).get("top10"),
            "C2_BROKEN_T3": track_details.get("C2_BROKEN_T3", {}).get("thresholds", {}).get("top10"),
            "C2_BROKEN_T5": track_details.get("C2_BROKEN_T5", {}).get("thresholds", {}).get("top10"),
            "uncond_wf_mean_pct": {
                k: track_details[k]["uncond_wf_mean_pct"]
                for k in ("C1_ACCEL_T2", "C1_ACCEL_T3", "C1_ACCEL_T5", "C2_BROKEN_T2", "C2_BROKEN_T3", "C2_BROKEN_T5")
                if k in track_details
            },
        },
        "truncation_20241231_proof": trunc_checks,
        "track_details": track_details,
    })

    audit_path = f"{OUT_DIR}/w2b3_audit.json"
    with open(audit_path, "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2, allow_nan=False)

    print(f"\n[W2B3 DONE in {audit['total_elapsed_sec']}s | Peak RSS={rss_gb}GB]")
    print(f"  Overall Best: {overall_best_k} -> nav={best_row['nav_wf']} ex5={best_row['ex5_wf']} 2526={best_row['nav_2526']} y26={best_row['nav_y26']} corr_v20={best_row['corr_v20_daily_all']}")


if __name__ == "__main__":
    main()

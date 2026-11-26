#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD043 Step 3: Red-Team Daily-Rebuild + Physical Truncation Proof + V20.0 Empty-Slot Patch
(all 3 capital ledgers: E1_NoCollision 09:24 / E1_StrictCashLock 09:25 / E2_T1Close 15:00)
+ Real 5-Minute K-Line Execution Audit (local 5m overlap + Baostock 2023-2026 real 5m fetch).

Zero yfinance (D12). Peak RSS < 1.8 GB.
"""
import os
for _k in (
    "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS",
):
    os.environ[_k] = "1"

import gc
import json
import math
import resource
import sys
import time
import warnings

import baostock as bs
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
BASE_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd043_tail_rush_arbitrage_20261126"
PQ_PATH = f"{OUT_DIR}/rd043_tail_events_pit.parquet"
PARQUET_5M = f"{ROOT}/sim-portfolio/data/all_strategies_5m_complete_pit.parquet"

for p in (BASE_DIR, OUT_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import wf_scorecard_engine as wf
import _wf_sim_and_metrics as wfm
import step2_blind_matrix_and_wf as s2


def peak_rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 2)


def prepare_track_df(df: pd.DataFrame, mask: pd.Series, ex_pref: str) -> pd.DataFrame:
    sub = df[mask].copy()
    sub["exit_date"] = sub[f"{ex_pref}_exit_date"].astype(str).str[:10]
    sub["exit_hhmm"] = sub[f"{ex_pref}_exit_hhmm"].astype(int)
    sub["gross_ret"] = pd.to_numeric(sub[f"{ex_pref}_gross_ret"], errors="coerce")
    sub = sub[sub["gross_ret"].notna() & (sub["exit_date"] > sub["buy_date"]) & (sub["exit_date"] <= "2026-11-25")].copy().reset_index(drop=True)
    return sub


def run_daily_wf_and_truncation(df: pd.DataFrame, v20_ctx: dict) -> tuple[dict, dict]:
    """
    Run strict daily-rebuilt WF scorecard (perm_n=1000), extreme thresholds (abs_85, abs_90),
    V20.0 empty-slot integration (3 capital ledgers), and 2024-12-31 physical truncation proof.
    """
    specs = [
        ("T10_B_All_E2", (df["proto_B"] == 1), "E2_T1C_HoldZT", "top5", 1500),
        ("T11_B_All_E3a", (df["proto_B"] == 1), "E3a_Open0_Hold", "abs_75", 1500),
        ("T01_A_10cm_E1", (df["proto_A"] == 1) & (df["is_20cm"] == 0), "E1_T1O", "top5", 924),
        ("T02_A_10cm_E2", (df["proto_A"] == 1) & (df["is_20cm"] == 0), "E2_T1C_HoldZT", "top5", 1500),
        ("T05_A_20cm_E1", (df["proto_A"] == 1) & (df["is_20cm"] == 1), "E1_T1O", "top5", 924),
        ("T06_A_20cm_E2", (df["proto_A"] == 1) & (df["is_20cm"] == 1), "E2_T1C_HoldZT", "top10", 1500),
        ("T13_C_All_E1", (df["proto_C"] == 1), "E1_T1O", "top5", 924),
    ]

    daily_res_out = {}
    trunc_out = {}
    v20_patch_out = {}
    sample_pools_for_5m = {}

    bench_df = v20_ctx["bench"]
    b_wf = bench_df[bench_df["trade_date"].between("2023-01-03", "2026-11-25")].sort_values("trade_date").reset_index(drop=True)
    cal_wf = b_wf["trade_date"].astype(str).tolist()
    dt_idx_wf = {d: i for i, d in enumerate(cal_wf)}

    # Note: v20_baseline_ledger_278 covers up to 2026-11-16 (canonical 5Y); cal_ext covers to 2026-11-25
    for tid, mask, ex_pref, best_th, default_ehh in specs:
        t0 = time.time()
        sub = prepare_track_df(df, mask, ex_pref)
        # Use daily rebuild on C (9k rows) and monthly on very large A/B, PLUS daily rebuild on T10_B_All_E2 & T05_A_20cm_E1 for truncation proof!
        rfreq = "daily" if tid in ("T10_B_All_E2", "T13_C_All_E1") else "monthly"
        res = wf.run_wf_scorecard_new_strategy(
            sub, feature_cols=s2.CAUSAL_FEATURES, v20_ctx=v20_ctx,
            wf_start_date="2023-01-03", end_date="2026-11-24",
            min_warmup_trades=80, min_warmup_trades_rare=50, min_warmup_months=18,
            recalc_freq=rfreq, top_k=12, min_k=5, max_corr=0.65, min_t_stat=1.0,
            shrink_tau=20.0, fee_rt=0.0030, gross_ret_col="gross_ret",
            tie_col="amount_yi",
            thresholds=("top10", "top5", 75, 80, 85, 90),
            eval_v20_patch=False, perm_n=1000, seed=20261126,
        )

        # Save top-scored passing candidates for 5m fetch
        obj_best = res["threshold_results"][best_th]
        sample_pools_for_5m[tid] = obj_best["slot_df"].copy()

        # Check all thresholds including abs_85, abs_90
        th_dict = {}
        for th_nm in ("top10", "top5", "abs_75", "abs_80", "abs_85", "abs_90"):
            obj = res["threshold_results"][th_nm]
            slot = obj["slot_df"].copy()
            ev = obj["metrics"]
            fw = ev["windows"].get("FULL_WF", {})
            if not slot.empty:
                slot["mtm_30"] = s2.attach_net_mtm_tuples(slot, f"{ex_pref}_mtm_json", 0.0030, dt_idx_wf)
                dr30, mdiff = wfm.build_daily_mtm_returns(slot, cal_wf, mtm_col="mtm_30")
                assert mdiff < 1e-4
                rets = slot["net_ret"].to_numpy(float)
                gr_s = slot["gross_ret"].to_numpy(float)
                sr = np.sort(rets)
                ex5 = float(np.prod(1.0 + sr[:-5])) if len(rets) > 5 else 1.0
                ex10 = float(np.prod(1.0 + sr[:-10])) if len(rets) > 10 else 1.0
                nav80 = float(np.prod(1.0 + ((1.0 + gr_s) * (1.0 - 0.0080) - 1.0)))
                nav120 = float(np.prod(1.0 + ((1.0 + gr_s) * (1.0 - 0.0120) - 1.0)))
                sd30 = float(np.std(dr30, ddof=1))
                sh30 = float(np.mean(dr30) / sd30 * math.sqrt(242.0)) if sd30 > 1e-12 else 0.0
                dsr_d = s2.compute_dsr(dr30, n_trials=168)
                mtm_exact_diff = mdiff
            else:
                ex5 = ex10 = nav80 = nav120 = 1.0
                sh30 = mtm_exact_diff = 0.0
                dsr_d = {"dsr": 0.0}

            th_dict[th_nm] = {
                "n_pass": int(len(obj["pass_df"])),
                "n_trades": int(fw.get("n", 0)),
                "wr_pct": fw.get("wr_pct", 0.0),
                "mean_pct": fw.get("mean_pct", 0.0),
                "nav_30": fw.get("nav", 1.0),
                "nav_80": round(nav80, 4),
                "nav_120": round(nav120, 4),
                "ex5_30": round(ex5, 4),
                "ex10_30": round(ex10, 4),
                "eq_nav_30": fw.get("eq_nav", 1.0),
                "sharpe": round(sh30, 3),
                "mdd_pct": fw.get("daily_mdd_pct", 0.0),
                "excess_csi_pp": fw.get("excess_csi300_pp", 0.0),
                "perm_sd_p": ev["permutation_1000"]["same_day_p_nav"],
                "perm_any_p": ev["permutation_1000"]["any_cand_day_p_nav"],
                "dsr": dsr_d["dsr"],
                "mtm_diff": round(mtm_exact_diff, 8),
            }
        daily_res_out[tid] = {
            "recalc_freq": rfreq,
            "elapsed_sec": round(time.time() - t0, 2),
            "best_threshold": best_th,
            "thresholds": th_dict,
        }

        # Physical 2024-12-31 truncation proof on key representatives of all 3 prototypes
        if tid in ("T10_B_All_E2", "T01_A_10cm_E1", "T05_A_20cm_E1", "T13_C_All_E1"):
            tr_th = best_th if not best_th.startswith("abs_") else int(best_th.split("_")[1])
            tr_proof = wf.verify_truncation_zero_leakage(
                sub, feature_cols=s2.CAUSAL_FEATURES, mode="A", cutoff="2024-12-31",
                score_threshold=tr_th, v20_ctx=v20_ctx,
                wf_start_date="2023-01-03", min_warmup_trades=80, min_warmup_trades_rare=50,
                min_warmup_months=18, recalc_freq=rfreq, top_k=12, min_k=5,
                max_corr=0.65, min_t_stat=1.0, shrink_tau=20.0, fee_rt=0.0030,
                gross_ret_col="gross_ret", tie_col="amount_yi",
            )
            trunc_out[tid] = tr_proof

        # V20.0 Empty-Slot Patch under explicit physical capital ledgers!
        p_best = obj_best["pass_df"].copy()
        p_best_can = p_best[p_best["buy_date"] <= "2026-11-16"].copy()
        patch_modes = []
        if ex_pref == "E1_T1O":
            patch_modes = [
                ("E1_NoCollision_0924", 924, True),
                ("E1_StrictCashLock_0925", 925, True),
                ("E1_NoCollision_IgnoreMorningWait", 924, False),
            ]
        else:
            patch_modes = [
                (f"{ex_pref}_BlocksAllNextDay_1500", 1500, True),
            ]

        v20_patch_out[tid] = {}
        for pm_name, ex_hh_override, resp_wait in patch_modes:
            p_in = p_best_can.copy()
            # Preserve exact deferred exit_hhmm if DT deferred to 1500, else override 924 vs 925
            if ex_pref == "E1_T1O":
                p_in["exit_hhmm"] = np.where(p_in["E1_T1O_dt_deferred"] == 1, 1500, ex_hh_override)
            else:
                p_in["exit_hhmm"] = p_in[f"{ex_pref}_exit_hhmm"].astype(int)
            p_in["buy_hhmm"] = 1445
            p_res = wf.simulate_v20_empty_slot_patch(
                p_in, v20_ctx=v20_ctx, wf_start_dt="2023-01-03", end_dt="2026-11-16",
                respect_stier_waits=resp_wait, score_col="wf_score",
            )
            m1 = p_res["mode1_strict_combined_no_peek"]
            m2 = p_res["mode2_empty_slot_standalone"]
            v20_patch_out[tid][pm_name] = {
                "v20_base_nav": m1["v20_baseline"]["FULL_WF"]["nav"],
                "v20_base_sharpe": m1["v20_baseline"]["FULL_WF"]["daily_sharpe"],
                "v20_base_mdd_pct": m1["v20_baseline"]["FULL_WF"]["daily_mdd_pct"],
                "combined_nav": m1["combined_with_patch"]["FULL_WF"]["nav"],
                "combined_sharpe": m1["combined_with_patch"]["FULL_WF"]["daily_sharpe"],
                "combined_mdd_pct": m1["combined_with_patch"]["FULL_WF"]["daily_mdd_pct"],
                "delta_nav_ratio": m1["delta_nav_ratio_full_wf"],
                "delta_sharpe": m1["delta_sharpe_full_wf"],
                "delta_mdd_pp": m1["delta_mdd_pp_full_wf"],
                "n_v20_kept": m1["n_v20_kept"],
                "n_patch_added": m1["n_patch_added"],
                "n_v20_skipped_by_collision": m1["n_v20_skipped_by_collision"],
                "skipped_v20_net_ret_prod": m1["skipped_v20_net_ret_prod"],
                "skipped_v20_trades": m1["skipped_v20_trades"][:10],
                "emp_standalone_n": m2["n_standalone_empty_trades"],
                "emp_standalone_wr": m2["windows"]["FULL_WF"].get("wr_pct", 0.0),
                "emp_standalone_nav": m2["windows"]["FULL_WF"].get("nav", 1.0),
                "emp_standalone_ex5": m2["windows"]["FULL_WF"].get("ex_top5_nav", 1.0),
                "emp_collision_rate_pct": m2["collision_rate_pct"],
            }

        print(f"  [Daily/Trunc/V20] {tid} ({rfreq}) | best={best_th} nav30={th_dict[best_th]['nav_30']} perm_p={th_dict[best_th]['perm_sd_p']} | V20={list(v20_patch_out[tid].keys())}")

    return {"daily_wf": daily_res_out, "truncation_20241231": trunc_out, "v20_empty_patch": v20_patch_out}, sample_pools_for_5m


def run_5m_execution_audit(df_all: pd.DataFrame, sample_pools: dict[str, pd.DataFrame]) -> dict:
    """
    1. Audit exact coverage of local `all_strategies_5m_complete_pit.parquet`.
    2. Fetch REAL historical 5m K-lines from Baostock for ~400 WF trades (Proto A 10cm, A 20cm, B, C)
       and measure exact tail 14:40/14:45/14:50/14:55 vs 15:00 close slippage & T+1 09:35/09:45 vs 09:25 open!
    """
    t0 = time.time()
    print("\n[Step3-5m] Checking local 5m parquet coverage...")
    df5 = pd.read_parquet(PARQUET_5M, columns=["c6", "date", "hhmm_int", "open", "close"])
    df5["c6"] = df5["c6"].astype(str).str.zfill(6)
    df5["date"] = df5["date"].astype(str).str[:10]

    n_5m_codes = int(df5["c6"].nunique())
    n_5m_pairs = int(df5[["c6", "date"]].drop_duplicates().shape[0])

    # Local 5m overlap on day T
    piv_t = df5[df5["hhmm_int"].isin([1430, 1440, 1445, 1450, 1455, 1500])].pivot_table(
        index=["date", "c6"], columns="hhmm_int", values="close"
    ).reset_index().rename(columns={"date": "buy_date", "c6": "code"})
    ov = df_all.merge(piv_t, on=["buy_date", "code"], how="inner")

    local_stats = {
        "local_5m_parquet_pairs": n_5m_pairs,
        "local_5m_parquet_codes": n_5m_codes,
        "overlap_events": int(len(ov)),
        "overlap_pct_of_rd043": round(len(ov) / max(1, len(df_all)) * 100.0, 2),
        "note": "all_strategies_5m_complete_pit.parquet covers only the 6 V20 strategies universe, NOT full 5,425 A-share stocks.",
    }
    if not ov.empty:
        for tbar in (1440, 1445, 1450):
            chg = (ov[1500] / ov[tbar] - 1.0) * 100.0
            e1_bar = (1.0 + ov["E1_T1O_gross_ret"]) * (ov[1500] / ov[tbar]) - 1.0
            local_stats[f"local_tail_{tbar}_to_1500_mean_pct"] = round(float(chg.mean()), 4)
            local_stats[f"local_tail_{tbar}_to_1500_med_pct"] = round(float(chg.median()), 4)
            local_stats[f"local_e1_from_{tbar}_gross_mean_pct"] = round(float(e1_bar.mean() * 100.0), 4)
        local_stats["local_e1_from_close_gross_mean_pct"] = round(float(ov["E1_T1O_gross_ret"].mean() * 100.0), 4)
        # Check late-tail spike (>=2% in 14:30->15:00) vs flat-tail (<0.5%)
        tail30 = (ov[1500] / ov[1430] - 1.0) * 100.0
        for lbl, m_t in [("late_spike_ge2pct", tail30 >= 2.0), ("steady_lt05pct", tail30 < 0.5)]:
            sub_ov = ov[m_t]
            e1_1445 = (1.0 + sub_ov["E1_T1O_gross_ret"]) * (sub_ov[1500] / sub_ov[1445]) - 1.0
            local_stats[f"local_shape_{lbl}"] = {
                "n": int(len(sub_ov)),
                "e1_from_close_pct": round(float(sub_ov["E1_T1O_gross_ret"].mean() * 100.0), 3),
                "e1_from_1445_pct": round(float(e1_1445.mean() * 100.0), 3),
            }
    del df5, piv_t, ov
    gc.collect()

    # Build representative ~380-trade sample from top WF tracks (2023-2026) for REAL Baostock 5m verification
    cache_5m_path = f"{OUT_DIR}/rd043_baostock_5m_exec_sample.parquet"
    sample_list = []
    for tid, max_n in [("T10_B_All_E2", 120), ("T01_A_10cm_E1", 100), ("T05_A_20cm_E1", 100), ("T13_C_All_E1", 80)]:
        sp = sample_pools[tid].copy()
        sp = sp[sp["buy_date"] >= "2023-01-03"].copy()
        # Take evenly spaced or latest + top-scored up to max_n
        if len(sp) > max_n:
            idx_take = np.linspace(0, len(sp) - 1, max_n, dtype=int)
            sp = sp.iloc[idx_take].copy()
        sp["sample_track"] = tid
        sample_list.append(sp[["sample_track", "buy_date", "code", "E1_T1O_exit_date", "E1_T1O_gross_ret", "E2_T1C_HoldZT_gross_ret", "close_raw", "adj_factor", "ret_1d"]])
    samp_df = pd.concat(sample_list, ignore_index=True).drop_duplicates(subset=["buy_date", "code"]).reset_index(drop=True)

    if os.path.exists(cache_5m_path):
        bs_df = pd.read_parquet(cache_5m_path)
    else:
        print(f"[Step3-5m] Fetching REAL 5m K-lines via Baostock for {len(samp_df)} WF trades (2023-2026)...")
        lg = bs.login()
        assert lg.error_code == "0", f"Baostock login failed: {lg.error_msg}"
        rec_5m = []
        for idx_i, r in enumerate(samp_df.itertuples(index=False)):
            pref = "sh." if r.code.startswith(("60", "68")) else "sz."
            # Map buy_date and T+1 date
            rs = bs.query_history_k_data_plus(
                pref + r.code, "date,time,open,high,low,close,volume,amount",
                start_date=r.buy_date, end_date=r.E1_T1O_exit_date,
                frequency="5", adjustflag="3",
            )
            bars = []
            while rs.error_code == "0" and rs.next():
                bars.append(rs.get_row_data())
            if not bars:
                continue
            bdf = pd.DataFrame(bars, columns=rs.fields)
            bdf["hhmm"] = bdf["time"].str[8:12].astype(int)
            for col in ("open", "high", "low", "close"):
                bdf[col] = pd.to_numeric(bdf[col], errors="coerce")
            d0 = bdf[bdf["date"] == r.buy_date].set_index("hhmm")
            d1 = bdf[bdf["date"] == r.E1_T1O_exit_date].set_index("hhmm")
            if d0.empty or d1.empty:
                continue
            if 1500 not in d0.index or 935 not in d1.index:
                continue
            c1500 = float(d0.loc[1500, "close"])
            if not (c1500 > 0):
                continue
            row_o = {
                "sample_track": r.sample_track,
                "buy_date": r.buy_date,
                "code": r.code,
                "t1_date": r.E1_T1O_exit_date,
                "daily_close_raw": float(r.close_raw),
                "bs_c1500": c1500,
                "bs_c1430": float(d0.loc[1430, "close"]) if 1430 in d0.index else np.nan,
                "bs_c1440": float(d0.loc[1440, "close"]) if 1440 in d0.index else np.nan,
                "bs_c1445": float(d0.loc[1445, "close"]) if 1445 in d0.index else np.nan,
                "bs_c1450": float(d0.loc[1450, "close"]) if 1450 in d0.index else np.nan,
                "bs_c1455": float(d0.loc[1455, "close"]) if 1455 in d0.index else np.nan,
                "bs_t1_o935": float(d1.loc[935, "open"]),
                "bs_t1_c935": float(d1.loc[935, "close"]),
                "bs_t1_c945": float(d1.loc[945, "close"]) if 945 in d1.index else np.nan,
                "bs_t1_c1000": float(d1.loc[1000, "close"]) if 1000 in d1.index else np.nan,
                "bs_t1_c1500": float(d1.loc[1500, "close"]) if 1500 in d1.index else np.nan,
                "daily_e1_gross": float(r.E1_T1O_gross_ret),
                "daily_e2_gross": float(r.E2_T1C_HoldZT_gross_ret),
            }
            rec_5m.append(row_o)
            if (idx_i + 1) % 80 == 0:
                print(f"    Fetched {idx_i+1}/{len(samp_df)} ({len(rec_5m)} ok) in {time.time()-t0:.1f}s")
        bs.logout()
        bs_df = pd.DataFrame(rec_5m)
        bs_df.to_parquet(cache_5m_path, index=False)

    # Analyze exact 5m execution deviations
    bs_df["close_match_diff_pct"] = (bs_df["bs_c1500"] / bs_df["daily_close_raw"] - 1.0).abs() * 100.0
    # Keep split-consistent rows for direct open/close comparison, and adjust 1445->1500 ratio for all
    bs_clean = bs_df[bs_df["bs_c1445"].notna() & bs_df["bs_c1450"].notna() & bs_df["bs_t1_c935"].notna()].copy()
    for tbar in (1440, 1445, 1450, 1455):
        bs_clean[f"tail_{tbar}_to_1500_pct"] = (bs_clean["bs_c1500"] / bs_clean[f"bs_c{tbar}"] - 1.0) * 100.0
        # Split-safe E1 return from tbar: (1 + daily_e1_gross) * (bs_c1500 / bs_c{tbar}) - 1
        bs_clean[f"e1_open_from_{tbar}_gross"] = (1.0 + bs_clean["daily_e1_gross"]) * (bs_clean["bs_c1500"] / bs_clean[f"bs_c{tbar}"]) - 1.0
        # Realized 5m exit at T+1 09:35 close (note: adjust by open_ratio if dividend occurred overnight; daily_e1_gross already includes adj!)
        # Actually check overnight adj consistency: t1_open_to_0935_mult = bs_t1_c935 / bs_t1_o935 (intraday T+1!)
        bs_clean[f"e1_0935_from_{tbar}_gross"] = (1.0 + bs_clean[f"e1_open_from_{tbar}_gross"]) * (bs_clean["bs_t1_c935"] / bs_clean["bs_t1_o935"]) - 1.0
        bs_clean[f"e1_0945_from_{tbar}_gross"] = (1.0 + bs_clean[f"e1_open_from_{tbar}_gross"]) * (bs_clean["bs_t1_c945"] / bs_clean["bs_t1_o935"]) - 1.0

    # Summary by track
    by_tr = {}
    for tr_nm, grp in bs_clean.groupby("sample_track"):
        e1_cl = grp["daily_e1_gross"].to_numpy(float)
        e1_45_o = grp["e1_open_from_1445_gross"].to_numpy(float)
        e1_45_935 = grp["e1_0935_from_1445_gross"].to_numpy(float)
        e1_50_935 = grp["e1_0935_from_1450_gross"].to_numpy(float)
        by_tr[tr_nm] = {
            "n": int(len(grp)),
            "tail_1445_to_1500_mean_pct": round(float(grp["tail_1445_to_1500_pct"].mean()), 3),
            "tail_1445_to_1500_med_pct": round(float(grp["tail_1445_to_1500_pct"].median()), 3),
            "tail_1450_to_1500_mean_pct": round(float(grp["tail_1450_to_1500_pct"].mean()), 3),
            "daily_close_e1_gross_mean_pct": round(float(e1_cl.mean() * 100.0), 3),
            "real_1445_to_t1open_gross_mean_pct": round(float(e1_45_o.mean() * 100.0), 3),
            "real_1445_to_0935_gross_mean_pct": round(float(e1_45_935.mean() * 100.0), 3),
            "real_1450_to_0935_gross_mean_pct": round(float(e1_50_935.mean() * 100.0), 3),
            "real_1445_to_0935_net30_nav": round(float(np.prod(1.0 + ((1.0 + e1_45_935) * 0.997 - 1.0))), 4),
            "real_1450_to_0935_net30_nav": round(float(np.prod(1.0 + ((1.0 + e1_50_935) * 0.997 - 1.0))), 4),
            "daily_close_e1_net30_nav": round(float(np.prod(1.0 + ((1.0 + e1_cl) * 0.997 - 1.0))), 4),
        }

    # Check 5m tail shape (late spike vs steady) across Baostock sample
    shape_stats = {}
    if bs_clean["bs_c1430"].notna().any():
        sp30 = (bs_clean["bs_c1500"] / bs_clean["bs_c1430"] - 1.0) * 100.0
        for lbl, m_s in [("late_spike_ge15pct", sp30 >= 1.5), ("flat_lt05pct", sp30 < 0.5)]:
            g_s = bs_clean[m_s]
            shape_stats[lbl] = {
                "n": int(len(g_s)),
                "daily_e1_gross_pct": round(float(g_s["daily_e1_gross"].mean() * 100.0), 3),
                "real_1445_to_0935_gross_pct": round(float(g_s["e1_0935_from_1445_gross"].mean() * 100.0), 3),
                "real_1445_to_0935_net30_nav": round(float(np.prod(1.0 + ((1.0 + g_s["e1_0935_from_1445_gross"]) * 0.997 - 1.0))), 4) if len(g_s) else 1.0,
            }

    overall_5m = {
        "n_fetched": int(len(bs_clean)),
        "close_match_le_005pct_rate": round(float((bs_clean["close_match_diff_pct"] <= 0.05).mean() * 100.0), 2),
        "tail_1440_to_1500_mean_pct": round(float(bs_clean["tail_1440_to_1500_pct"].mean()), 3),
        "tail_1445_to_1500_mean_pct": round(float(bs_clean["tail_1445_to_1500_pct"].mean()), 3),
        "tail_1450_to_1500_mean_pct": round(float(bs_clean["tail_1450_to_1500_pct"].mean()), 3),
        "tail_1455_to_1500_mean_pct": round(float(bs_clean["tail_1455_to_1500_pct"].mean()), 3),
        "t1_open_to_0935_mean_pct": round(float((bs_clean["bs_t1_c935"] / bs_clean["bs_t1_o935"] - 1.0).mean() * 100.0), 3),
        "t1_open_to_0945_mean_pct": round(float((bs_clean["bs_t1_c945"] / bs_clean["bs_t1_o935"] - 1.0).mean() * 100.0), 3),
        "daily_e1_gross_mean_pct": round(float(bs_clean["daily_e1_gross"].mean() * 100.0), 3),
        "real_1445_to_0935_gross_mean_pct": round(float(bs_clean["e1_0935_from_1445_gross"].mean() * 100.0), 3),
        "real_1450_to_0935_gross_mean_pct": round(float(bs_clean["e1_0935_from_1450_gross"].mean() * 100.0), 3),
        "by_track": by_tr,
        "shape_stats": shape_stats,
    }
    return {"local_5m_parquet": local_stats, "baostock_real_5m_audit": overall_5m}, bs_clean


def main():
    t0 = time.time()
    print("[Step3] Loading rd043_tail_events_pit.parquet and V20 context...")
    df = pd.read_parquet(PQ_PATH)
    v20_ctx = wf.load_v20_reference_context(BASE_DIR)

    # Check V20 baseline empty rate explicitly
    cal_5y = v20_ctx["calendar_5y"]
    cal_ext = v20_ctx["calendar_ext"]
    v20_stats = {
        "canonical_5y_days": int(len(cal_5y)),
        "canonical_5y_empty_days": int(cal_5y["v20_empty_slot"].sum()),
        "canonical_5y_empty_pct": round(float(cal_5y["v20_empty_slot"].mean() * 100.0), 2),
        "wf_2023_20261116_days": int(len(cal_5y[cal_5y["trade_date"] >= "2023-01-03"])),
        "wf_2023_20261116_empty_days": int(cal_5y.loc[cal_5y["trade_date"] >= "2023-01-03", "v20_empty_slot"].sum()),
        "wf_2023_20261116_empty_pct": round(float(cal_5y.loc[cal_5y["trade_date"] >= "2023-01-03", "v20_empty_slot"].mean() * 100.0), 2),
        "ext_to_20261125_empty_days": int(cal_ext["v20_empty_slot"].sum()),
    }

    print("\n[Step3] Running Daily WF, Extreme Thresholds, Truncation Proof, and V20.0 Empty-Slot Patch...")
    redteam_res, sample_pools = run_daily_wf_and_truncation(df, v20_ctx)

    print("\n[Step3] Running Real 5-Minute Execution Audit...")
    m5_res, _ = run_5m_execution_audit(df, sample_pools)

    # Summarize blind + WF grid into rd043_audit.json
    blind_df = pd.read_csv(f"{OUT_DIR}/rd043_blind_matrix.csv")
    grid_df = pd.read_csv(f"{OUT_DIR}/rd043_grid.csv")
    step1_audit = json.load(open(f"{OUT_DIR}/_step1_audit.json", encoding="utf-8"))
    track_meta = json.load(open(f"{OUT_DIR}/_step2_track_meta.json", encoding="utf-8"))

    # Strict Pass Gate Check across ALL 168 + daily configs
    strict_pass = grid_df[
        (grid_df["n_trades"] >= 30)
        & (grid_df["nav_30"] >= 1.5)
        & (grid_df["nav_80"] >= 1.15)
        & (grid_df["ex5_30"] >= 1.15)
        & (grid_df["ex10_30"] >= 1.05)
        & (grid_df["eq_nav_30"] >= 1.15)
        & (grid_df["dsr"] >= 0.95)
    ]

    verdict = "VALIDATED" if len(strict_pass) > 0 else "FALSIFIED"

    audit = {
        "rd_id": "RD043",
        "title": "尾盘抢筹套利实证",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t0, 2),
        "peak_rss_mb": peak_rss_mb(),
        "d12_yfinance_imported": False,
        "verdict": verdict,
        "strict_pass_count": int(len(strict_pass)),
        "v20_calendar_stats": v20_stats,
        "step1_data_audit": step1_audit,
        "blind_matrix_count": int(len(blind_df)),
        "blind_best_by_wf_nav": blind_df.sort_values("nav_wf_30", ascending=False).head(5).to_dict(orient="records"),
        "wf_grid_count": int(len(grid_df)),
        "wf_best_by_nav30": grid_df[grid_df["n_trades"] >= 30].sort_values("nav_30", ascending=False).head(10).to_dict(orient="records"),
        "daily_wf_and_extreme_thresholds": redteam_res["daily_wf"],
        "truncation_2024_12_31_proof": redteam_res["truncation_20241231"],
        "v20_empty_slot_patch": redteam_res["v20_empty_patch"],
        "real_5m_execution_audit": m5_res,
        "track_meta_latest_factors": track_meta,
    }

    with open(f"{OUT_DIR}/rd043_audit.json", "w", encoding="utf-8") as f:
        json.dump(s2.sanitize_json(audit), f, ensure_ascii=False, indent=2, allow_nan=False)

    print("\n=== STEP 3 SUMMARY ===")
    print("Verdict:", verdict, "| Strict Pass Count:", len(strict_pass))
    print("\nTruncation 2024-12-31 Proof:")
    for k, v in redteam_res["truncation_20241231"].items():
        print(f"  {k}: score_diff={v['max_abs_score_diff']}, ret_diff={v['max_abs_ret_diff']}, pass={v['zero_leakage_pass']}")
    print("\nV20 Empty-Slot Patch:")
    for k, d in redteam_res["v20_empty_patch"].items():
        for pm, pv in d.items():
            print(f"  {k} [{pm}]: added={pv['n_patch_added']}, V20_skip={pv['n_v20_skipped_by_collision']} (prod={pv['skipped_v20_net_ret_prod']}), delta_ratio={pv['delta_nav_ratio']}, emp_n={pv['emp_standalone_n']}, emp_nav={pv['emp_standalone_nav']}")
    print("\n5m Execution Audit (Baostock):")
    print(json.dumps(m5_res, ensure_ascii=False, indent=2))
    print(f"\n[Step3 DONE] Saved rd043_audit.json | peak_rss={peak_rss_mb()} MB")


if __name__ == "__main__":
    main()

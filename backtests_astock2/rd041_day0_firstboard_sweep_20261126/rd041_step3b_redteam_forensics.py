#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD041 Step 3b: Cold-Blooded Institutional Red-Team Forensics on Top Track A/B Candidates
(Threshold Plateaus, Double-Whammy AS50 x 80bp/110bp, Trade-by-Trade News & Liquidity Audit,
 V20 Collision Autopsy, 3 Ablations, and Deflated Sharpe Ratio under Total Trials).

Zero yfinance (D12). Threads <= 1. Peak RSS < 1.5 GB.
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import json
import math
import sqlite3
import sys
import time
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
BASE_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
DATA_DIR = f"{ROOT}/sim-portfolio/data"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd041_day0_firstboard_sweep_20261126"
CACHE_DIR = f"{OUT_DIR}/_cache"

if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
if OUT_DIR not in sys.path:
    sys.path.insert(0, OUT_DIR)

import wf_scorecard_engine as wf
import _wf_sim_and_metrics as wfm
import rd041_step3_wf_scorecard_and_stress as s3

TRD_DAYS_YEAR = 242.0


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_ppf(p: float) -> float:
    # Acklam / binary search accurate to 1e-8
    lo, hi = -8.0, 8.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if _norm_cdf(mid) < p:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def compute_dsr(dr: np.ndarray, n_trials: int) -> dict:
    """Bailey & Lopez de Prado (2014) Deflated Sharpe Ratio on daily MTM returns."""
    T = len(dr)
    if T < 30 or np.std(dr, ddof=1) < 1e-12:
        return {"sr_ann": 0.0, "sr0_ann": 0.0, "dsr": 0.0}
    sr_d = float(np.mean(dr) / np.std(dr, ddof=1))
    sr_ann = sr_d * math.sqrt(TRD_DAYS_YEAR)
    z = (dr - np.mean(dr)) / np.std(dr, ddof=1)
    skew = float(np.mean(z ** 3))
    kurt = float(np.mean(z ** 4))
    # Assume cross-trial daily SR variance ~ (0.35 / sqrt(242))^2 (conservative vs pooled prior)
    var_sr_d = (0.35 ** 2) / TRD_DAYS_YEAR
    gamma = 0.5772156649
    sr0_d = math.sqrt(var_sr_d) * ((1.0 - gamma) * _norm_ppf(1.0 - 1.0 / max(2, n_trials)) + gamma * _norm_ppf(1.0 - 1.0 / (max(2, n_trials) * math.e)))
    denom_sq = max(1e-12, (1.0 - skew * sr_d + ((kurt - 1.0) / 4.0) * (sr_d ** 2)) / (T - 1))
    dsr_val = _norm_cdf((sr_d - sr0_d) / math.sqrt(denom_sq))
    return {
        "n_trials": n_trials,
        "sr_ann": round(sr_ann, 3),
        "sr0_ann": round(sr0_d * math.sqrt(TRD_DAYS_YEAR), 3),
        "skew": round(skew, 3),
        "kurt": round(kurt, 3),
        "dsr": round(dsr_val, 4),
    }


def main():
    t0 = time.time()
    grid = pd.read_csv(f"{OUT_DIR}/rd041_grid.csv")
    audit = json.load(open(f"{OUT_DIR}/rd041_audit.json"))

    print("=== 1. THRESHOLD PLATEAU CHECK ON KEY TRACKS ===")
    for tid in ["A4_FN_PrePos_T1O", "A1_PreCat_All_T1O", "A6_Day0Theme_Gap2_T1O", "B4_10cm_All_Stk", "B1_10cm_All_T1O", "B6_20cm_All_T1C", "B7_20cm_All_Stk"]:
        sub = grid[grid["track_id"] == tid]
        print(f"\n--- {tid} ---")
        cols = ["threshold", "n_pass", "n_trades_wf", "brk_share_pct", "wr_wf_pct", "mean_wf_pct", "nav_wf", "ex5_wf", "sharpe_wf", "nav_2526", "slip80_nav", "perm_sd_p", "patch_n_added", "patch_delta_nav_ratio", "emp_standalone_n", "emp_standalone_nav"]
        print(sub[cols].to_string(index=False))

    # 2. Deep Replay on A1, A4, A6 (daily WF) for full forensics, ablations, liquidity filter & DSR
    v20_ctx = wf.load_v20_reference_context(BASE_DIR)
    df = pd.read_parquet(f"{CACHE_DIR}/rd041_fb_master_pit.parquet")
    bench_df = v20_ctx["bench"]

    # Stock name map for forensic trade printing
    con_zt = sqlite3.connect(f"file:{DATA_DIR}/zt_micro_tape_5y_pit.db?mode=ro", uri=True)
    nm_rows = con_zt.execute("SELECT DISTINCT sec_code, sec_name FROM zt_micro_tape").fetchall()
    con_zt.close()
    code_to_name = {str(c).zfill(6): n for c, n in nm_rows}
    csrc = pd.read_csv(f"{DATA_DIR}/csrc_industry_pit_clean.csv", usecols=["code", "code_name"]).drop_duplicates()
    for c, n in zip(csrc["code"], csrc["code_name"]):
        code_to_name.setdefault(str(c)[-6:], str(n))

    forensic_out = {}
    focus_specs = [
        ("A1_PreCat_All_T1O", df[(df["buy_date"] <= "2026-11-11") & (df["any_pre_cat"] == 1)], "E1_T1Open", "2026-11-11", 50, 35),
        ("A4_FN_PrePos_T1O", df[(df["buy_date"] <= "2026-11-11") & (df["fn_pre_pos"] == 1)], "E1_T1Open", "2026-11-11", 40, 30),
        ("A6_Day0Theme_Gap2_T1O", df[(df["buy_date"] <= "2026-11-11") & (df["is_day0_theme_ignite"] == 1) & ((df["kpl_0925_rank_gap"] <= 2) | (df["ind_0925_rank_gap"] <= 2))], "E1_T1Open", "2026-11-11", 80, 50),
    ]

    for tid, sub_df, ex_pref, edt, mw, mwr in focus_specs:
        fcols_use = [c for c in s3.CAUSAL_FEATURES if c in sub_df.columns]
        keep_cols = ["buy_date", "code", "is_zt", "is_20cm", "open_pct", "ret_1d", "mcap_yi_t1", "audit_only_amount_yi",
                     "fn_pre_pos", "fn_pre_hard", "cninfo_pre_pos", "ir_pre_pos",
                     f"{ex_pref}_exit_date", f"{ex_pref}_exit_hhmm", f"{ex_pref}_gross_ret", f"{ex_pref}_mtm_json"] + fcols_use
        keep_cols = list(dict.fromkeys(keep_cols))
        cand = sub_df[keep_cols].copy()
        cand["exit_date"] = cand[f"{ex_pref}_exit_date"].astype(str).str[:10]
        cand["exit_hhmm"] = cand[f"{ex_pref}_exit_hhmm"].astype(int)
        cand["gross_ret"] = cand[f"{ex_pref}_gross_ret"].astype(float)
        cand["buy_hhmm"] = 935
        cand["can_buy"] = cand["gross_ret"].notna() & (cand["exit_date"] > cand["buy_date"]) & (cand["buy_date"] <= edt) & (cand["exit_date"] <= "2026-11-16")
        cand["is_yizi"] = False
        cand = cand[cand["can_buy"]].copy().reset_index(drop=True)

        res = wf.run_wf_scorecard_new_strategy(
            cand, feature_cols=fcols_use, v20_ctx=v20_ctx, wf_start_date="2023-01-03", end_date=edt,
            min_warmup_trades=mw, min_warmup_trades_rare=mwr, min_warmup_months=18,
            recalc_freq="daily", top_k=12, min_k=min(5, len(fcols_use)),
            max_corr=0.65, min_t_stat=1.0, shrink_tau=20.0, fee_rt=0.0030, gross_ret_col="gross_ret",
            thresholds=("all_cands", "top20", "top10", "top5", 70, 75), eval_v20_patch=True, perm_n=200,
        )

        wf_start = res["meta"]["wf_actual_start"] or "2023-01-03"
        b_win = bench_df[bench_df["trade_date"].between(wf_start, "2026-11-16")].sort_values("trade_date").reset_index(drop=True)
        cal_win = b_win["trade_date"].astype(str).tolist()
        dt_idx_win = {d: i for i, d in enumerate(cal_win)}
        csi_arr = b_win["csi300_daily_ret"].to_numpy(float)

        print(f"\n=== 2. DEEP FORENSICS: {tid} (wf_start={wf_start}) ===")
        th_details = {}
        for th_nm in ("top20", "top10", "top5", "abs_70", "abs_75"):
            obj = res["threshold_results"][th_nm]
            slot = obj["slot_df"].copy()
            p_df = obj["pass_df"].copy()
            if slot.empty:
                continue
            slot["mtm_30"] = s3.attach_net_mtm_tuples(slot, f"{ex_pref}_mtm_json", 0.0030, dt_idx_win)
            dr30, _ = wfm.build_daily_mtm_returns(slot, cal_win, mtm_col="mtm_30")
            dsr_res = compute_dsr(dr30, n_trials=len(grid))

            # Year-by-year breakdown
            yr_stats = {}
            for y in ("2023", "2024", "2025", "2026"):
                ys = slot[slot["buy_date"].str.startswith(y)]
                yr_stats[y] = {
                    "n": int(len(ys)),
                    "wr": round(float((ys["net_ret"] > 0).mean() * 100.0), 1) if len(ys) else 0.0,
                    "nav": round(float(np.prod(1.0 + ys["net_ret"].to_numpy(float))), 3) if len(ys) else 1.0,
                }

            # Liquidity filter check (T-1 amt >= 1.0 yi & mcap >= 20 yi)
            slot_liq = slot[(slot["amount_yi_t1"] >= 1.0) & (slot["mcap_yi_t1"] >= 20.0)]
            liq_nav = round(float(np.prod(1.0 + slot_liq["net_ret"].to_numpy(float))), 3) if len(slot_liq) else 1.0

            # Active days only Sharpe (ex-cash!) & CSI300 matched exposure ablation
            act_mask = dr30 != 0.0
            sh_excash = float(np.mean(dr30[act_mask]) / np.std(dr30[act_mask], ddof=1) * math.sqrt(TRD_DAYS_YEAR)) if act_mask.sum() > 5 else 0.0
            csi_exp_nav = float(np.prod(1.0 + csi_arr[act_mask])) if act_mask.sum() else 1.0

            # Adverse selection matrix (70% / 50% x 30bp / 80bp / 110bp)
            p_df["mtm_30"] = s3.attach_net_mtm_tuples(p_df, f"{ex_pref}_mtm_json", 0.0030, dt_idx_win)
            p_df["mtm_80"] = s3.attach_net_mtm_tuples(p_df, f"{ex_pref}_mtm_json", 0.0080, dt_idx_win)
            p_df["mtm_110"] = s3.attach_net_mtm_tuples(p_df, f"{ex_pref}_mtm_json", 0.0110, dt_idx_win)
            as70_30 = s3.mc_adverse_selection(p_df, cal_win, "mtm_30", 0.70, True, 0.0030, 500)
            as50_30 = s3.mc_adverse_selection(p_df, cal_win, "mtm_30", 0.50, True, 0.0030, 500)
            as70_80 = s3.mc_adverse_selection(p_df, cal_win, "mtm_80", 0.70, True, 0.0080, 500)
            as50_80 = s3.mc_adverse_selection(p_df, cal_win, "mtm_80", 0.50, True, 0.0080, 500)
            as50_110 = s3.mc_adverse_selection(p_df, cal_win, "mtm_110", 0.50, True, 0.0110, 500)

            patch = obj["v20_empty_patch"]
            p_m1 = patch["mode1_strict_combined_no_peek"] if patch else {}
            p_m2 = patch["mode2_empty_slot_standalone"] if patch else {}

            print(
                f"  [{th_nm:6s}] n={len(slot):2d} (10cm={(slot['is_20cm']==0).sum()}, brk={(slot['is_zt']==0).sum()}) "
                f"yr={yr_stats} | exCashSh={sh_excash:.2f} csiSameDays={csi_exp_nav:.3f} | DSR(147)={dsr_res['dsr']} (SR0={dsr_res['sr0_ann']})"
                f" | liq(n={len(slot_liq)})={liq_nav} | AS70_30={as70_30['med_nav']} AS50_30={as50_30['med_nav']} AS70_80={as70_80['med_nav']} AS50_80={as50_80['med_nav']} AS50_110={as50_110['med_nav']}"
                f" | V20skip={p_m1.get('n_v20_skipped_by_collision',0)} (prod={p_m1.get('skipped_v20_net_ret_prod',1.0)}) empN={p_m2.get('n_standalone_empty_trades',0)} empNAV={p_m2.get('windows',{}).get('FULL_WF',{}).get('nav',1.0)}"
            )
            th_details[th_nm] = {
                "yr_stats": yr_stats, "dsr": dsr_res, "sh_excash": round(sh_excash, 3),
                "csi_same_days_nav": round(csi_exp_nav, 3),
                "liq_n": int(len(slot_liq)), "liq_nav": liq_nav,
                "as70_30": as70_30, "as50_30": as50_30, "as70_80": as70_80, "as50_80": as50_80, "as50_110": as50_110,
                "skipped_v20_trades": p_m1.get("skipped_v20_trades", []),
            }

            # Print top 5 wins & worst 5 losses + news match for best threshold
            if (tid == "A4_FN_PrePos_T1O" and th_nm == "abs_70") or (tid == "A1_PreCat_All_T1O" and th_nm == "top5"):
                print(f"\n  --- Trade-by-Trade Audit ({tid} / {th_nm}, N={len(slot)}) ---")
                slot["name"] = slot["code"].map(lambda c: code_to_name.get(c, ""))
                show_c = ["buy_date", "code", "name", "is_20cm", "is_zt", "open_pct", "wf_score", "net_ret", "mcap_yi_t1", "audit_only_amount_yi", "fn_pre_pos", "fn_pre_hard", "cninfo_pre_pos", "ir_pre_pos"]
                print("  Top 8 Winners:")
                print(slot.sort_values("net_ret", ascending=False)[show_c].head(8).to_string(index=False))
                print("  Worst 8 Losers:")
                print(slot.sort_values("net_ret", ascending=True)[show_c].head(8).to_string(index=False))

        forensic_out[tid] = th_details

    with open(f"{CACHE_DIR}/rd041_redteam_forensics.json", "w", encoding="utf-8") as f:
        json.dump(s3.sanitize_json(forensic_out), f, ensure_ascii=False, indent=2)
    print(f"\n[Step3b DONE] Elapsed={time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()

#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 3-3 Red Team B - Part 2B2:
Build exact close-to-close daily MTM series (`dr_exact`, `dr_emp`, `dr_comb`) & slim ledgers
for W2B4 (20cm New Archetypes: all Track A1..A8 + Track B/C/D/E reference tracks).
Read-only on Wave 1/2 files. Single-thread, zero yfinance, RSS < 1.8 GB.
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
import pickle
import sys
import time

import numpy as np
import pandas as pd
import pyarrow as pa

pa.set_cpu_count(1)
pa.set_io_thread_count(1)
assert "yfinance" not in sys.modules
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
RD035_DIR = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125"
WAVE1_DIR = f"{RD035_DIR}/wave1_base"
W2B4_DIR = f"{RD035_DIR}/wave2b/w2b4_20cm_new_archetypes_scorecard"
OUT_DIR = f"{RD035_DIR}/wave3_final/w3_3_redteam_audit_b"
os.makedirs(OUT_DIR, exist_ok=True)

for p in (WAVE1_DIR, W2B4_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import _wf_sim_and_metrics as wfm
import _wf_v20_patch as wfp
import w2b4_lib as lib
import w2b4_run_all as r4


def build_comb_emp_mtm_w2b4(
    pass_df: pd.DataFrame,
    v20_ctx: dict,
    cal_dts: list[str],
    wf_start_dt: str = "2023-01-03",
    end_dt: str = "2026-11-16",
) -> dict:
    cal_df = v20_ctx["calendar_5y"]
    cal_win = cal_df[cal_df["trade_date"].between(wf_start_dt, end_dt)].sort_values("trade_date").reset_index(drop=True)
    empty_set = set(cal_win.loc[cal_win["v20_empty_slot"] & (~cal_win["v20_has_stier_wait"]), "trade_date"])

    p = pass_df.copy()
    p["buy_date"] = p["buy_date"].astype(str).str[:10]
    p["exit_date"] = p["exit_date"].astype(str).str[:10]
    p["code"] = p["code"].astype(str).str.zfill(6)
    p = p[p["buy_date"].between(wf_start_dt, end_dt) & (p["exit_date"] > p["buy_date"])].copy()
    if "buy_hhmm" not in p.columns:
        p["buy_hhmm"] = 925
    if "exit_hhmm" not in p.columns:
        p["exit_hhmm"] = 1500
    p["buy_hhmm"] = pd.to_numeric(p["buy_hhmm"], errors="coerce").fillna(925).astype(int)
    p["exit_hhmm"] = pd.to_numeric(p["exit_hhmm"], errors="coerce").fillna(1500).astype(int)
    p_top1 = p.sort_values(["buy_date", "wf_score", "code"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()

    p_emp = p_top1[p_top1["buy_date"].isin(empty_set)].sort_values("buy_date").reset_index(drop=True)
    _, emp_slot_df = wfm.select_single_slot_trades(p_emp.assign(can_buy_hygiene=True), score_col="wf_score", threshold=None, wf_only=False)
    dr_emp, _ = wfm.build_daily_mtm_returns(emp_slot_df, cal_dts, mtm_col="mtm_segs")

    v20_led = v20_ctx["v20_ledger"]
    v20_win = v20_led[v20_led["buy_date"].between(wf_start_dt, end_dt)].copy().reset_index(drop=True)
    events = []
    for r in v20_win.itertuples(index=False):
        events.append({
            "buy_date": r.buy_date, "buy_hhmm": int(r.buy_hhmm), "exit_date": r.exit_date, "exit_hhmm": int(r.exit_hhmm),
            "code": r.code, "strategy": r.strategy, "net_ret": float(r.net_ret),
            "prio_src": 0, "is_wait": False, "source": "v20", "mtm_pairs": r.mtm_pairs,
        })
    for w in v20_ctx["v20_waits"]:
        if wf_start_dt <= w["buy_date"] <= end_dt and w["wait_tier"] in ("3to4_S(>=102)", "high_S(>=96)"):
            events.append({
                "buy_date": w["buy_date"], "buy_hhmm": 935, "exit_date": w["buy_date"], "exit_hhmm": int(w["cancel_hhmm"]),
                "code": w["wait_code"], "strategy": w["wait_strategy"], "net_ret": 0.0,
                "prio_src": 0, "is_wait": True, "source": "v20_wait", "mtm_pairs": [],
            })
    for r in p_top1.itertuples(index=False):
        rec = {
            "buy_date": r.buy_date, "buy_hhmm": int(r.buy_hhmm), "exit_date": r.exit_date, "exit_hhmm": int(r.exit_hhmm),
            "code": r.code, "strategy": "patch", "net_ret": float(r.net_ret),
            "prio_src": 1, "is_wait": False, "source": "patch", "mtm_pairs": [],
            "mtm_segs": getattr(r, "mtm_segs"),
        }
        events.append(rec)

    ev_df = pd.DataFrame(events).sort_values(["buy_date", "prio_src", "buy_hhmm", "code"], ascending=[True, True, True, True]).reset_index(drop=True)
    taken_comb, skipped_v20 = [], []
    cur_ed, cur_eh = "", 0
    for r in ev_df.itertuples(index=False):
        if r.source == "patch" and r.buy_date not in empty_set:
            continue
        can_enter = (not cur_ed) or (r.buy_date > cur_ed) or (r.buy_date == cur_ed and int(r.buy_hhmm) > cur_eh)
        if can_enter:
            if not r.is_wait:
                taken_comb.append(r._asdict())
            cur_ed, cur_eh = r.exit_date, int(r.exit_hhmm)
        elif r.source == "v20":
            skipped_v20.append(float(r.net_ret))

    comb_df = pd.DataFrame(taken_comb) if taken_comb else pd.DataFrame(columns=["buy_date", "exit_date", "code", "strategy", "net_ret", "source", "mtm_pairs"])
    dr_comb, _ = wfp._build_combined_mtm(comb_df, cal_dts, patch_mtm_col="mtm_segs")
    n_patch_added = int((comb_df["source"] == "patch").sum()) if not comb_df.empty else 0
    return {
        "dr_emp": dr_emp,
        "dr_comb": dr_comb,
        "emp_slot_df": emp_slot_df,
        "n_patch_added": n_patch_added,
        "n_v20_skipped": int(len(skipped_v20)),
        "skipped_v20_prod": float(np.prod(1.0 + np.asarray(skipped_v20))) if skipped_v20 else 1.0,
    }


def slim_df(df: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in ["buy_date", "exit_date", "code", "net_ret", "wf_score"] if c in df.columns]
    return df[cols].copy() if not df.empty else pd.DataFrame(columns=["buy_date", "exit_date", "code", "net_ret"])


def main():
    t0 = time.time()
    master_df, all_fcols, _ = lib.build_w2b4_candidate_pool("2026-11-16")
    pure_stock, stock_micro = r4.get_feature_scopes(all_fcols)
    v20_ctx = lib.wf.load_v20_reference_context(lib.WAVE1_BASE)
    cal_df = v20_ctx["calendar_5y"]
    cal_wf = cal_df[cal_df["trade_date"].between("2023-01-03", "2026-11-16")].sort_values("trade_date").reset_index(drop=True)
    cal_dts_wf = cal_wf["trade_date"].tolist()

    specs = r4.define_final_specs(master_df, pure_stock, stock_micro)
    keep_ids = {
        "A1_12_23_h1_PURE", "A2_12_23_h1_MICRO", "A3_12_23_h2_PURE", "A4_12_23_v11_MICRO",
        "A5_12_23_v11_PURE", "A6_1to2_hiopen_h1_PURE", "A7_2to3_only_h1_PURE", "A8_2to3_only_v11_MICRO",
        "B1_all_h1_MICRO", "B2_all_v11_MICRO", "C1_mild_v11_MICRO", "D1_s82zone_v11_PURE",
        "E1_mild_v11_PURE", "E2_strong_thm_v11_PURE",
    }
    thresholds = ("all_cands", "top30", "top20", "top10", "top5", 70, 75, 80, 85)
    thr_map = {"all_cands": None, "top30": "wf_thr_top30", "top20": "wf_thr_top20", "top10": "wf_thr_top10", "top5": "wf_thr_top5"}

    t_b4 = {}
    for tid, tgrp, mask, ex_mode, fset, scope_lbl in specs:
        if tid not in keep_ids:
            continue
        sub_df, vf_cols = lib.prepare_track_df(master_df, mask, exit_mode=ex_mode, end_dt="2026-11-16", all_feat_cols=fset)
        df_h = wfm.prepare_hygiene_and_net_ret(sub_df, fee_rt=0.0030, gross_ret_col="gross_ret")
        scored_df, core_meta = lib.wfc.run_expanding_scorecard_loop(
            df_h, feature_cols=vf_cols, mode="scorecard_0_100", wf_start_date="2023-01-03",
            min_warmup_trades=80, min_warmup_trades_rare=60, min_warmup_months=18,
            recalc_freq="daily", top_k=12, min_k=5, max_corr=0.65, min_t_stat=1.0, shrink_tau=20.0,
        )
        actual_wf_start = core_meta["wf_actual_start"] or "2023-01-03"
        scored_aligned = lib.attach_aligned_mtm(scored_df, cal_dts_wf, mtm_col="mtm_segs")

        for th in thresholds:
            tname = str(th) if not isinstance(th, (int, float)) else f"abs_{int(th)}"
            t_arg = thr_map[th] if th in thr_map else float(th)
            pass_df, slot_df = wfm.select_single_slot_trades(scored_aligned, score_col="wf_score", threshold=t_arg, wf_only=True)
            dr_exact, diff = wfm.build_daily_mtm_returns(slot_df, cal_dts_wf, mtm_col="mtm_segs")
            if th != "all_cands" and not pass_df.empty:
                p_res = build_comb_emp_mtm_w2b4(pass_df, v20_ctx, cal_dts_wf, wf_start_dt="2023-01-03", end_dt="2026-11-16")
            else:
                p_res = {
                    "dr_emp": np.zeros(len(cal_dts_wf)),
                    "dr_comb": None,
                    "emp_slot_df": pd.DataFrame(columns=["buy_date", "exit_date", "code", "net_ret"]),
                    "n_patch_added": 0,
                    "n_v20_skipped": 0,
                    "skipped_v20_prod": 1.0,
                }
            t_b4[f"{tid}::{tname}"] = {
                "wf_actual_start": actual_wf_start,
                "n_cands_total": int(len(sub_df)),
                "n_pass": int(len(pass_df)),
                "slot_df": slim_df(slot_df),
                "emp_slot_df": slim_df(p_res["emp_slot_df"]),
                "dr_exact": dr_exact,
                "dr_emp": p_res["dr_emp"],
                "dr_comb": p_res["dr_comb"],
                "n_patch_added": p_res["n_patch_added"],
                "n_v20_skipped": p_res["n_v20_skipped"],
                "skipped_v20_prod": p_res["skipped_v20_prod"],
                "diff": float(diff),
            }
        print(f"  [W2B4 {tid:22s}] RSS={lib.get_rss_mb()} MB", flush=True)
        del sub_df, df_h, scored_df, scored_aligned
        gc.collect()

    out_pkl = f"{OUT_DIR}/_cache_tracks_b4.pkl"
    with open(out_pkl, "wb") as f:
        pickle.dump({"W2B4_20cm_New": t_b4}, f)
    print(f"[Part 2B2 DONE in {time.time()-t0:.1f}s] {len(t_b4)} variants -> {out_pkl} | Peak RSS={lib.get_rss_mb()} MB", flush=True)


if __name__ == "__main__":
    main()

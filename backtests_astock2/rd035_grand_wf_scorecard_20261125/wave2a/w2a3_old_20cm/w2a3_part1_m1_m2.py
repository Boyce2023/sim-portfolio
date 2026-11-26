#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD035 Wave 2A-3 Part 1: Baseline Parity + Module 1 (F01..F09 & F06 surgery) + Module 2 (xtr_* 37 transplant)."""
import json
import os
import sys
import time

os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")

import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave2a/w2a3_old_20cm"
if OUT_DIR not in sys.path:
    sys.path.insert(0, OUT_DIR)

import w2a3_lib as lib
import _wf_core as wfc
import _wf_sim_and_metrics as wfm

F9_COLS = lib.F9_COLS


def _run_score_variant(name, group, df_h, score_arr, thr, v20_ctx, wf_ctx, base_comb, wf_cands, perm_n=200):
    d = df_h.copy()
    d["_sc"] = score_arr
    pass_df, slot_df = wfm.select_single_slot_trades(d, score_col="_sc", threshold=thr, wf_only=True)
    slot_df["score"] = slot_df["_sc"]
    row, det = lib.summarize_variant(
        name, group, slot_df, pass_df, wf_cands, wf_ctx,
        v20_comb_ctx=v20_ctx, v20_base_comb=base_comb, perm_n=perm_n,
    )
    return row, det


def main():
    t0 = time.time()
    p20, meta = lib.load_w2a3_data()
    v20_ctx = lib.load_v20_comb_context()
    wf_ctx = v20_ctx["wf_ctx"]

    df_h = wfm.prepare_hygiene_and_net_ret(p20, fee_rt=0.0030)
    df_h["wf_in_window"] = df_h["buy_date"] >= "2023-01-03"
    wf_cands = df_h[df_h["wf_in_window"]].copy()

    # 0. Exact S82 All-Period & WF Baseline Parity
    _, s_all_base = wfm.select_single_slot_trades(df_h, score_col="v20_score", threshold=82.0, wf_only=False)
    all_nav = float(np.prod(1.0 + s_all_base["net_ret"].to_numpy(float)))
    assert len(s_all_base) == 199 and abs(all_nav - 468.2898) < 0.05, f"Parity mismatch: {len(s_all_base)}, {all_nav}"

    p_wf_b, s_wf_b = wfm.select_single_slot_trades(df_h, score_col="v20_score", threshold=82.0, wf_only=True)
    s_wf_b["score"] = s_wf_b["v20_score"]
    base_comb = lib.get_official_v20_comb_metrics(v20_ctx)
    assert base_comb["FULL_5Y"]["n"] == 278 and abs(base_comb["FULL_5Y"]["nav"] - 69134091.51) < 10.0, f"V20 parity fail: {base_comb['FULL_5Y']}"
    print("Official V20.0 Combined WF:", base_comb["FULL_WF"])

    rows = []
    details = {}

    def add_res(row, det):
        rows.append(row)
        details[row["variant"]] = {"eval": det["eval"], "comb": det["comb"]}

    # Baseline + threshold sweep
    r_base, d_base = _run_score_variant("BASE_V11_S82", "0_BASELINE", df_h, df_h["v20_score"].to_numpy(float), 82.0, v20_ctx, wf_ctx, base_comb, wf_cands, perm_n=1000)
    add_res(r_base, d_base)
    for thr in (76, 78, 80, 84):
        r, d = _run_score_variant(f"BASE_V11_S{thr}", "0_BASELINE", df_h, df_h["v20_score"].to_numpy(float), float(thr), v20_ctx, wf_ctx, base_comb, wf_cands)
        add_res(r, d)

    # ================= MODULE 1: F01..F09 LOO ABLATION & F06 SURGERY =================
    v20_sc = df_h["v20_score"].to_numpy(float)
    for col in F9_COLS:
        f_vals = df_h[col].to_numpy(float)
        sc_no = v20_sc - f_vals
        short = col.replace("s20cm_", "")
        r, d = _run_score_variant(f"M1_LOO_drop_{short}_thr82", "M1_LOO", df_h, sc_no, 82.0, v20_ctx, wf_ctx, base_comb, wf_cands)
        add_res(r, d)
        max_pos = float(np.max(f_vals))
        if max_pos > 0:
            adj_thr = max(70.0, 82.0 - max_pos)
            r2, d2 = _run_score_variant(f"M1_LOO_drop_{short}_thr{int(adj_thr)}", "M1_LOO", df_h, sc_no, adj_thr, v20_ctx, wf_ctx, base_comb, wf_cands)
            add_res(r2, d2)

    # PM Pain Point 1: Delete F06 at thr=80, 78, 77
    f6_vals = df_h["s20cm_F06_inst_net_pos"].to_numpy(float)
    sc_no6 = v20_sc - f6_vals
    for thr in (80, 78, 77):
        r, d = _run_score_variant(f"M1_F06_DEL_thr{thr}", "M1_F06_SURGERY", df_h, sc_no6, float(thr), v20_ctx, wf_ctx, base_comb, wf_cands)
        add_res(r, d)

    # PM Pain Point 2: Cold-day disable F06 when mkt10_zt_est_t1 < 40/45/50 (and L1_zt_cnt_t1 < 45)
    mkt10 = df_h["mkt10_zt_est_t1"].to_numpy(float)
    l1zt = df_h["L1_zt_cnt_t1"].to_numpy(float)
    for cut in (40, 45, 50):
        sc_c = np.where(mkt10 < cut, sc_no6, v20_sc)
        for thr in (82, 80):
            r, d = _run_score_variant(f"M1_F06_COLD{cut}_thr{thr}", "M1_F06_SURGERY", df_h, sc_c, float(thr), v20_ctx, wf_ctx, base_comb, wf_cands)
            add_res(r, d)
    sc_l1c = np.where(l1zt < 45, sc_no6, v20_sc)
    r, d = _run_score_variant("M1_F06_L1COLD45_thr82", "M1_F06_SURGERY", df_h, sc_l1c, 82.0, v20_ctx, wf_ctx, base_comb, wf_cands)
    add_res(r, d)

    # PM Pain Point 3: Replace F06 (+5) with causal single factor (exit_date < t)
    df_no6 = df_h.copy()
    df_no6["v20_no6"] = sc_no6
    rep_groups = {
        "turn20": ["L3_cum_turn20_t1", "L3_turn20_pct250_t1", "evo_turn_5_20"],
        "kpl20": ["L2_kpl_zt20_t1", "L2_ind_ex20_t1", "L2_kpl_peak_ratio_t1"],
        "us_on": ["us_ixic_ret1d_on", "us_ixic_ret5d_on", "us_vix_chg1d_on"],
        "oldhot": ["oh_cool_days_since_last_zt", "oh_waves_3y_g15", "oh_trap_waves_3y", "oh_dd_from_1y_high"],
    }
    all_rep_cands = [c for cs in rep_groups.values() for c in cs if c in df_no6.columns]
    for rname, rcols in [("best1", all_rep_cands)] + list(rep_groups.items()):
        rcols = [c for c in rcols if c in df_no6.columns]
        patched, pmeta = lib.run_causal_scorecard_ext(
            df_no6, rcols, mode="delta_patch", wf_start_date="2023-01-03",
            min_warmup_trades=80, top_k=1, min_k=1, max_corr=0.95, min_t_stat=0.0,
            shrink_tau=20.0, max_delta=5, orig_score_col="v20_no6", max_corr_orig=0.95,
        )
        # Shift delta from [-5,+5] -> [0,+5] and [-5,+5] variants
        for thr in (82, 80, 78):
            pass_df, slot_df = wfm.select_single_slot_trades(patched, score_col="wf_score", threshold=float(thr), wf_only=True)
            slot_df["score"] = slot_df["wf_score"]
            r, d = lib.summarize_variant(f"M1_F06_REP_{rname}_d5_thr{thr}", "M1_F06_REPLACE", slot_df, pass_df, wf_cands, wf_ctx, v20_ctx, base_comb)
            add_res(r, d)

    # PM Pain Point 4: Causal WF Reweighting of native 9 factors (F01..F09)
    for cfg_tag, mint in [("all9_t0", 0.0), ("sig9_t1", 1.0)]:
        sc_f9, m_f9 = lib.run_causal_scorecard_ext(
            df_h, F9_COLS, mode="scorecard_0_100", wf_start_date="2023-01-03",
            min_warmup_trades=80, top_k=9, min_k=4, max_corr=0.90, min_t_stat=mint, shrink_tau=20.0,
        )
        for th in ("top20", "top15", "top10", 76, 78, 80, 82, 84):
            tname = th if isinstance(th, str) else f"S{th}"
            targ = f"wf_thr_{th}" if isinstance(th, str) else float(th)
            pass_df, slot_df = wfm.select_single_slot_trades(sc_f9, score_col="wf_score", threshold=targ, wf_only=True)
            slot_df["score"] = slot_df["wf_score"]
            r, d = lib.summarize_variant(f"M1_F9_REWEIGHT_{cfg_tag}_{tname}", "M1_F9_REWEIGHT", slot_df, pass_df, wf_cands, wf_ctx, v20_ctx, base_comb)
            add_res(r, d)
        details[f"M1_F9_REWEIGHT_{cfg_tag}_latest_card"] = m_f9["latest_card"]

    # ================= MODULE 2: 37 CROSS-STRATEGY ATOMIC TRANSPLANT =================
    for xtag, xcols in [("xtr37", meta["xtr_active"]), ("xtr37fix", meta["xtr_fixed"])]:
        # Mode A: F9 + xtr -> 0..100
        sc_m2a, m_m2a = lib.run_causal_scorecard_ext(
            df_h, F9_COLS + xcols, mode="scorecard_0_100", wf_start_date="2023-01-03",
            min_warmup_trades=80, top_k=12, min_k=5, max_corr=0.65, min_t_stat=1.0, shrink_tau=20.0,
        )
        for th in ("top20", "top15", "top10", 76, 78, 80, 82, 84):
            tname = th if isinstance(th, str) else f"S{th}"
            targ = f"wf_thr_{th}" if isinstance(th, str) else float(th)
            pass_df, slot_df = wfm.select_single_slot_trades(sc_m2a, score_col="wf_score", threshold=targ, wf_only=True)
            slot_df["score"] = slot_df["wf_score"]
            r, d = _run_score_variant_df(f"M2_A_F9_{xtag}_{tname}", "M2_XTR_MODE_A", sc_m2a, targ, v20_ctx, wf_ctx, base_comb, wf_cands)
            add_res(r, d)
        details[f"M2_A_{xtag}_latest_card"] = m_m2a["latest_card"]

        # Mode B: V20 + delta(xtr) max_delta in {8, 15, 25}
        for md in (8, 15, 25):
            sc_m2b, m_m2b = lib.run_causal_scorecard_ext(
                df_h, xcols, mode="delta_patch", wf_start_date="2023-01-03",
                min_warmup_trades=80, top_k=10, min_k=4, max_corr=0.65, min_t_stat=1.0,
                shrink_tau=20.0, max_delta=md, orig_score_col="v20_score", max_corr_orig=0.70,
            )
            for th in ("top20", "top15", "top10", 76, 78, 80, 82, 84):
                tname = th if isinstance(th, str) else f"S{th}"
                targ = f"wf_thr_{th}" if isinstance(th, str) else float(th)
                r, d = _run_score_variant_df(f"M2_B_{xtag}_d{md}_{tname}", "M2_XTR_MODE_B", sc_m2b, targ, v20_ctx, wf_ctx, base_comb, wf_cands)
                add_res(r, d)
            if md == 15:
                details[f"M2_B_{xtag}_d15_latest_card"] = m_m2b["latest_card"]

    df_res = pd.DataFrame(rows)
    df_res.to_csv(f"{OUT_DIR}/_part1_m1_m2_table.csv", index=False)
    with open(f"{OUT_DIR}/_part1_m1_m2_details.json", "w", encoding="utf-8") as f:
        json.dump(details, f, ensure_ascii=False, indent=2, default=str)
    print(f"[Part1 DONE in {time.time()-t0:.1f}s] {len(df_res)} variants saved.")
    print(df_res.sort_values("nav_wf", ascending=False)[
        ["variant", "n_wf", "wr_wf", "nav_wf", "ex5_wf", "mdd_wf", "nav_2526", "n_26h2", "wr_26h2", "nav_26h2", "comb_wf_nav_ratio"]
    ].head(20).to_string(index=False))


def _run_score_variant_df(name, group, scored_df, targ, v20_ctx, wf_ctx, base_comb, wf_cands):
    pass_df, slot_df = wfm.select_single_slot_trades(scored_df, score_col="wf_score", threshold=targ, wf_only=True)
    slot_df["score"] = slot_df["wf_score"]
    return lib.summarize_variant(name, group, slot_df, pass_df, wf_cands, wf_ctx, v20_ctx, base_comb)


if __name__ == "__main__":
    main()

#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD035 Wave 2A-3 Finalizer: 1000x perm on finalists, 2024-12-31 truncation proof (<2GB RSS), & deliverables."""
import gc
import json
import os
import resource
import sys
import time

os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")

import numpy as np
import pandas as pd
import pyarrow as pa

sys.dont_write_bytecode = True
OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave2a/w2a3_old_20cm"
if OUT_DIR not in sys.path:
    sys.path.insert(0, OUT_DIR)

import w2a3_lib as lib
import _wf_sim_and_metrics as wfm


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


def _run_model_df(p20, meta, kind):
    df_h = wfm.prepare_hygiene_and_net_ret(p20, fee_rt=0.0030)
    f6 = df_h["s20cm_F06_inst_net_pos"].to_numpy(float)
    mkt10 = df_h["mkt10_zt_est_t1"].to_numpy(float)
    df_h["v20_cold50"] = np.where(mkt10 < 50.0, df_h["v20_score"].to_numpy(float) - f6, df_h["v20_score"].to_numpy(float))

    feat_pre = list(dict.fromkeys(lib.F9_COLS + meta["xtr_fixed"] + meta["entry_num"]))
    feat_auc = list(dict.fromkeys(feat_pre + meta["auc_cols"]))
    feat_delta_auc = list(dict.fromkeys(meta["entry_num"] + meta["xtr_fixed"] + meta["auc_cols"]))

    if kind == "CLEAN_B_cold50_d15":
        sc, _ = lib.run_causal_scorecard_ext(
            df_h, feat_delta_auc, mode="delta_patch", wf_start_date="2023-01-03",
            min_warmup_trades=80, top_k=10, min_k=5, max_corr=0.65, min_t_stat=1.0,
            shrink_tau=20.0, max_delta=15, orig_score_col="v20_cold50", max_corr_orig=0.70,
            min_discrete_bin_cnt=15,
        )
        return sc, 84.0
    if kind == "M2_B_xtr37fix_d8":
        sc, _ = lib.run_causal_scorecard_ext(
            df_h, meta["xtr_fixed"], mode="delta_patch", wf_start_date="2023-01-03",
            min_warmup_trades=80, top_k=10, min_k=4, max_corr=0.65, min_t_stat=1.0,
            shrink_tau=20.0, max_delta=8, orig_score_col="v20_score", max_corr_orig=0.70,
        )
        return sc, 80.0
    if kind == "CLEAN_A_pre_k12":
        sc, _ = lib.run_causal_scorecard_ext(
            df_h, feat_pre, mode="scorecard_0_100", wf_start_date="2023-01-03",
            min_warmup_trades=80, top_k=12, min_k=5, max_corr=0.65, min_t_stat=1.0,
            shrink_tau=20.0, min_discrete_bin_cnt=15,
        )
        return sc, "wf_thr_top20"
    if kind == "CLEAN_mine_auc_c":
        sc, _ = lib.run_causal_scorecard_ext(
            df_h, feat_auc, mode="scorecard_0_100", wf_start_date="2023-01-03",
            min_warmup_trades=80, top_k=10, min_k=5, max_corr=0.65, min_t_stat=1.0,
            shrink_tau=20.0, target_mode="mine_m7", min_discrete_bin_cnt=15,
        )
        return sc, "wf_thr_top15"
    raise ValueError(kind)


def check_truncation(p20_full, meta_full, p20_trunc, meta_trunc, kind, cutoff="2024-12-31"):
    sc_f, thr = _run_model_df(p20_full, meta_full, kind)
    sc_t, _ = _run_model_df(p20_trunc, meta_trunc, kind)
    f_le = sc_f[sc_f["buy_date"] <= cutoff].sort_values(["buy_date", "code"]).reset_index(drop=True)
    t_le = sc_t.sort_values(["buy_date", "code"]).reset_index(drop=True)
    assert len(f_le) == len(t_le)
    sf = f_le["wf_score"].fillna(-999999.0).to_numpy(float)
    st = t_le["wf_score"].fillna(-999999.0).to_numpy(float)
    max_sc_diff = float(np.max(np.abs(sf - st)))
    assert max_sc_diff == 0.0, f"{kind} trunc score diff={max_sc_diff}"

    _, sl_f = wfm.select_single_slot_trades(sc_f, score_col="wf_score", threshold=thr, wf_only=True)
    _, sl_t = wfm.select_single_slot_trades(sc_t, score_col="wf_score", threshold=thr, wf_only=True)
    tr_f = sl_f[sl_f["exit_date"] <= cutoff].sort_values(["buy_date", "code"]).reset_index(drop=True)
    tr_t = sl_t[sl_t["exit_date"] <= cutoff].sort_values(["buy_date", "code"]).reset_index(drop=True)
    assert list(zip(tr_f["buy_date"], tr_f["code"])) == list(zip(tr_t["buy_date"], tr_t["code"]))
    max_r_diff = float(np.max(np.abs(tr_f["net_ret"].to_numpy(float) - tr_t["net_ret"].to_numpy(float)))) if len(tr_f) else 0.0
    assert max_r_diff == 0.0, f"{kind} trunc ret diff={max_r_diff}"
    return {
        "kind": kind,
        "cutoff": cutoff,
        "n_rows_checked": int(len(f_le)),
        "n_trades_le_cutoff": int(len(tr_f)),
        "max_abs_score_diff": max_sc_diff,
        "max_abs_ret_diff": max_r_diff,
        "zero_leakage_pass": True,
    }


def main():
    t0 = time.time()
    t1 = pd.read_csv(f"{OUT_DIR}/_part1_m1_m2_table.csv")
    t2 = pd.read_csv(f"{OUT_DIR}/_part2_m3_m4_table.csv")
    t3 = pd.read_csv(f"{OUT_DIR}/_part3_clean_table.csv")
    all_df = pd.concat([t1, t2, t3], ignore_index=True).drop_duplicates(subset=["variant"], keep="last").reset_index(drop=True)

    p20, meta = lib.load_w2a3_data()
    v20_ctx = lib.load_v20_comb_context()
    wf_ctx = v20_ctx["wf_ctx"]
    df_h = wfm.prepare_hygiene_and_net_ret(p20, fee_rt=0.0030)
    df_h["wf_in_window"] = df_h["buy_date"] >= "2023-01-03"
    wf_cands = df_h[df_h["wf_in_window"]].copy()
    base_comb = lib.get_official_v20_comb_metrics(v20_ctx)

    f6 = df_h["s20cm_F06_inst_net_pos"].to_numpy(float)
    mkt10 = df_h["mkt10_zt_est_t1"].to_numpy(float)
    df_h["v20_cold50"] = np.where(mkt10 < 50.0, df_h["v20_score"].to_numpy(float) - f6, df_h["v20_score"].to_numpy(float))
    df_h["v20_no6"] = df_h["v20_score"].to_numpy(float) - f6
    feat_pre = list(dict.fromkeys(lib.F9_COLS + meta["xtr_fixed"] + meta["entry_num"]))
    feat_auc = list(dict.fromkeys(feat_pre + meta["auc_cols"]))
    feat_delta_auc = list(dict.fromkeys(meta["entry_num"] + meta["xtr_fixed"] + meta["auc_cols"]))

    sc_cold50_d15, m_c50 = lib.run_causal_scorecard_ext(
        df_h, feat_delta_auc, mode="delta_patch", wf_start_date="2023-01-03",
        min_warmup_trades=80, top_k=10, min_k=5, max_corr=0.65, min_t_stat=1.0,
        shrink_tau=20.0, max_delta=15, orig_score_col="v20_cold50", max_corr_orig=0.70,
        min_discrete_bin_cnt=15,
    )
    sc_xtr37fix_d8, m_xtr = lib.run_causal_scorecard_ext(
        df_h, meta["xtr_fixed"], mode="delta_patch", wf_start_date="2023-01-03",
        min_warmup_trades=80, top_k=10, min_k=4, max_corr=0.65, min_t_stat=1.0,
        shrink_tau=20.0, max_delta=8, orig_score_col="v20_score", max_corr_orig=0.70,
    )
    sc_rep_oldhot, m_oh = lib.run_causal_scorecard_ext(
        df_h.assign(v20_no6=df_h["v20_no6"]),
        ["oh_cool_days_since_last_zt", "oh_waves_3y_g15", "oh_trap_waves_3y", "oh_dd_from_1y_high"],
        mode="delta_patch", wf_start_date="2023-01-03", min_warmup_trades=80,
        top_k=1, min_k=1, max_corr=0.95, min_t_stat=0.0, shrink_tau=20.0,
        max_delta=5, orig_score_col="v20_no6", max_corr_orig=0.95,
    )
    sc_clean_a, m_ca = lib.run_causal_scorecard_ext(
        df_h, feat_pre, mode="scorecard_0_100", wf_start_date="2023-01-03",
        min_warmup_trades=80, top_k=12, min_k=5, max_corr=0.65, min_t_stat=1.0,
        shrink_tau=20.0, min_discrete_bin_cnt=15,
    )
    sc_mine_c, m_mc = lib.run_causal_scorecard_ext(
        df_h, feat_auc, mode="scorecard_0_100", wf_start_date="2023-01-03",
        min_warmup_trades=80, top_k=10, min_k=5, max_corr=0.65, min_t_stat=1.0,
        shrink_tau=20.0, target_mode="mine_m7", min_discrete_bin_cnt=15,
    )
    sc_v20_d15, _ = lib.run_causal_scorecard_ext(
        df_h, feat_delta_auc, mode="delta_patch", wf_start_date="2023-01-03",
        min_warmup_trades=80, top_k=10, min_k=5, max_corr=0.65, min_t_stat=1.0,
        shrink_tau=20.0, max_delta=15, orig_score_col="v20_score", max_corr_orig=0.70,
        min_discrete_bin_cnt=15,
    )
    veto_m15 = (sc_mine_c["wf_score"] >= sc_mine_c["wf_thr_top15"]).fillna(False).to_numpy(bool)

    finalist_specs = [
        ("BASE_V11_S82", df_h, "v20_score", 82.0, None),
        ("BASE_V11_S80", df_h, "v20_score", 80.0, None),
        ("M1_F06_COLD50_thr80", df_h, "v20_cold50", 80.0, None),
        ("M1_F06_REP_oldhot_d5_thr80", sc_rep_oldhot, "wf_score", 80.0, None),
        ("M2_B_xtr37fix_d8_S80", sc_xtr37fix_d8, "wf_score", 80.0, None),
        ("CLEAN_A_pre_k12_top20", sc_clean_a, "wf_score", "wf_thr_top20", None),
        ("CLEAN_mine_auc_c_top15_MB_v20_d15_S80", sc_v20_d15, "wf_score", 80.0, veto_m15),
        ("CLEAN_B_cold50_d15_S78", sc_cold50_d15, "wf_score", 78.0, None),
        ("CLEAN_B_cold50_d15_S80", sc_cold50_d15, "wf_score", 80.0, None),
        ("CLEAN_B_cold50_d15_S84", sc_cold50_d15, "wf_score", 84.0, None),
        ("CLEAN_B_cold50_d15_S80_mine15", sc_cold50_d15, "wf_score", 80.0, veto_m15),
    ]

    finalist_rows, finalist_details = [], {}
    best_slot_df = None
    for fname, df_s, scol, thr, vmask in finalist_specs:
        d = df_s.copy()
        if vmask is not None:
            d["can_buy_hygiene"] = d["can_buy_hygiene"].to_numpy(bool) & (~vmask)
        p_df, s_df = wfm.select_single_slot_trades(d, score_col=scol, threshold=thr, wf_only=True)
        if not s_df.empty:
            s_df["score"] = s_df[scol]
        r, det = lib.summarize_variant(fname, "FINALIST_1000X", s_df, p_df, wf_cands, wf_ctx, v20_ctx, base_comb, perm_n=1000)
        finalist_rows.append(r)
        finalist_details[fname] = det
        if fname == "CLEAN_B_cold50_d15_S84":
            best_slot_df = s_df.copy()

    best_slot_df.to_parquet(f"{OUT_DIR}/w2a3_best_trades.parquet", index=False)

    # Free heavy V20 bars context before running 2024-12-31 truncation load
    del v20_ctx, wf_ctx, df_h, wf_cands, sc_cold50_d15, sc_xtr37fix_d8, sc_rep_oldhot, sc_clean_a, sc_mine_c, sc_v20_d15
    gc.collect()
    pa.default_memory_pool().release_unused()

    p20_trunc, meta_trunc = lib.load_w2a3_data(end_cutoff="2024-12-31")
    trunc_proofs = {
        k: check_truncation(p20, meta, p20_trunc, meta_trunc, k, cutoff="2024-12-31")
        for k in ("CLEAN_B_cold50_d15", "M2_B_xtr37fix_d8", "CLEAN_A_pre_k12", "CLEAN_mine_auc_c")
    }

    all_df = pd.concat([all_df, pd.DataFrame([r for r in finalist_rows if r["variant"] == "CLEAN_B_cold50_d15_S80_mine15"])], ignore_index=True)
    all_df = all_df.drop_duplicates(subset=["variant"], keep="last").reset_index(drop=True)
    all_df.to_csv(f"{OUT_DIR}/w2a3_variants_table.csv", index=False)

    with open(f"{OUT_DIR}/_part3_clean_details.json") as f:
        d3 = json.load(f)

    rss_mb = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 2)
    audit = _sanitize({
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t0, 2),
        "peak_rss_mb": rss_mb,
        "d12_yfinance_imported": "yfinance" in sys.modules,
        "total_variants_tested": int(len(all_df)),
        "baseline_all_5y_parity": {
            "n_trades": 199,
            "nav": 468.2898,
            "v20_combined_5y_n": base_comb["FULL_5Y"]["n"],
            "v20_combined_5y_nav": base_comb["FULL_5Y"]["nav"],
            "v20_combined_wf_n": base_comb["FULL_WF"]["n"],
            "v20_combined_wf_nav": base_comb["FULL_WF"]["nav"],
        },
        "truncation_2024_12_31_proof": trunc_proofs,
        "recommended_primary_winner": "CLEAN_B_cold50_d15_S84",
        "recommended_high_freq_v20_winner": "CLEAN_B_cold50_d15_S80",
        "finalists_1000x_perm": finalist_rows,
        "finalists_full_windows_and_v20_comb": finalist_details,
        "latest_causal_scorecards": {
            "CLEAN_B_cold50_d15": m_c50["latest_card"],
            "M2_B_xtr37fix_d8": m_xtr["latest_card"],
            "M1_F06_REP_oldhot_d5": m_oh["latest_card"],
            "CLEAN_A_pre_k12": m_ca["latest_card"],
            "CLEAN_mine_auc_c": m_mc["latest_card"],
        },
        "minefield_diagnostics": d3["CLEAN_mine_diagnostics"],
        "module1_loo_summary": t1[t1["group"].isin(["0_BASELINE", "M1_LOO", "M1_F06_SURGERY", "M1_F06_REPLACE"])].to_dict("records"),
    })
    with open(f"{OUT_DIR}/w2a3_audit.json", "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2, allow_nan=False)

    print(f"[FINALIZE PASS in {audit['elapsed_sec']}s | RSS={rss_mb}MB | total_variants={len(all_df)}]")
    print("=== Truncation 2024-12-31 Proofs ===")
    for k, v in trunc_proofs.items():
        print(f"  {k}: score_diff={v['max_abs_score_diff']}, ret_diff={v['max_abs_ret_diff']}, trades_le={v['n_trades_le_cutoff']}")


if __name__ == "__main__":
    main()

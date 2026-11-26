#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD035 Wave 2A-3 Part 3: Clean-Bin (min_discrete_bin_cnt=15) Mode A/B/Mine-Split + Synergy Tests."""
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
import _wf_sim_and_metrics as wfm

F9_COLS = lib.F9_COLS
ALL_THRS = ("top20", "top15", "top10", 76, 78, 80, 82, 84)


def _eval_and_add(rows, details, name, group, df_scored, score_col, targ, v20_ctx, wf_ctx, base_comb, wf_cands, veto_mask=None):
    d = df_scored.copy()
    if veto_mask is not None:
        d["can_buy_hygiene"] = d["can_buy_hygiene"].to_numpy(bool) & (~np.asarray(veto_mask, dtype=bool))
    pass_df, slot_df = wfm.select_single_slot_trades(d, score_col=score_col, threshold=targ, wf_only=True)
    if not slot_df.empty:
        slot_df["score"] = slot_df[score_col]
    row, det = lib.summarize_variant(name, group, slot_df, pass_df, wf_cands, wf_ctx, v20_ctx, base_comb, perm_n=200)
    rows.append(row)
    details[name] = {"eval": det["eval"], "comb": det["comb"]}


def main():
    t0 = time.time()
    p20, meta = lib.load_w2a3_data()
    v20_ctx = lib.load_v20_comb_context()
    wf_ctx = v20_ctx["wf_ctx"]

    df_h = wfm.prepare_hygiene_and_net_ret(p20, fee_rt=0.0030)
    df_h["wf_in_window"] = df_h["buy_date"] >= "2023-01-03"
    wf_cands = df_h[df_h["wf_in_window"]].copy()
    base_comb = lib.get_official_v20_comb_metrics(v20_ctx)

    f6 = df_h["s20cm_F06_inst_net_pos"].to_numpy(float)
    mkt10 = df_h["mkt10_zt_est_t1"].to_numpy(float)
    yizi10 = df_h["auc_thm10_has_yizi_open"].fillna(0.0).to_numpy(float)
    df_h["v20_cold45"] = np.where(mkt10 < 45.0, df_h["v20_score"].to_numpy(float) - f6, df_h["v20_score"].to_numpy(float))
    df_h["v20_cold50"] = np.where(mkt10 < 50.0, df_h["v20_score"].to_numpy(float) - f6, df_h["v20_score"].to_numpy(float))
    df_h["v20_no6"] = df_h["v20_score"].to_numpy(float) - f6

    feat_pre = list(dict.fromkeys(F9_COLS + meta["xtr_fixed"] + meta["entry_num"]))
    feat_auc = list(dict.fromkeys(feat_pre + meta["auc_cols"]))
    feat_delta_auc = list(dict.fromkeys(meta["entry_num"] + meta["xtr_fixed"] + meta["auc_cols"]))

    rows, details = [], {}

    # 1. Clean-Bin Mode B (min_discrete_bin_cnt=15) across V20, cold45, cold50
    mb_cache = {}
    for btag, orig_c in [("v20", "v20_score"), ("cold45", "v20_cold45"), ("cold50", "v20_cold50")]:
        for md in (8, 15, 25):
            sc_b, m_b = lib.run_causal_scorecard_ext(
                df_h, feat_delta_auc, mode="delta_patch", wf_start_date="2023-01-03",
                min_warmup_trades=80, top_k=10, min_k=5, max_corr=0.65, min_t_stat=1.0,
                shrink_tau=20.0, max_delta=md, orig_score_col=orig_c, max_corr_orig=0.70,
                min_discrete_bin_cnt=15,
            )
            mb_cache[(btag, md)] = sc_b
            details[f"CLEAN_B_{btag}_d{md}_latest_card"] = m_b["latest_card"]
            for th in ALL_THRS:
                tname = th if isinstance(th, str) else f"S{th}"
                targ = f"wf_thr_{th}" if isinstance(th, str) else float(th)
                _eval_and_add(rows, details, f"CLEAN_B_{btag}_d{md}_{tname}", "CLEAN_MODE_B", sc_b, "wf_score", targ, v20_ctx, wf_ctx, base_comb, wf_cands)

    # 2. Clean-Bin Mode A (0..100 from scratch, min_discrete_bin_cnt=15)
    ma_cache = {}
    for atag, fcols, tk in [("pre_k12", feat_pre, 12), ("auc_k12", feat_auc, 12), ("auc_k15", feat_auc, 15)]:
        sc_a, m_a = lib.run_causal_scorecard_ext(
            df_h, fcols, mode="scorecard_0_100", wf_start_date="2023-01-03",
            min_warmup_trades=80, top_k=tk, min_k=5, max_corr=0.65, min_t_stat=1.0,
            shrink_tau=20.0, min_discrete_bin_cnt=15,
        )
        ma_cache[atag] = sc_a
        details[f"CLEAN_A_{atag}_latest_card"] = m_a["latest_card"]
        for th in ALL_THRS:
            tname = th if isinstance(th, str) else f"S{th}"
            targ = f"wf_thr_{th}" if isinstance(th, str) else float(th)
            _eval_and_add(rows, details, f"CLEAN_A_{atag}_{tname}", "CLEAN_MODE_A", sc_a, "wf_score", targ, v20_ctx, wf_ctx, base_comb, wf_cands)

    # 3. Clean-Bin Minefield Scorecard (target: net_ret <= -0.07, min_discrete_bin_cnt=15)
    mine_clean = {}
    mine_diag = {}
    for mtag, fcols in [("mine_pre_c", feat_pre), ("mine_auc_c", feat_auc)]:
        sc_m, m_m = lib.run_causal_scorecard_ext(
            df_h, fcols, mode="scorecard_0_100", wf_start_date="2023-01-03",
            min_warmup_trades=80, top_k=10, min_k=5, max_corr=0.65, min_t_stat=1.0,
            shrink_tau=20.0, target_mode="mine_m7", min_discrete_bin_cnt=15,
        )
        mine_clean[mtag] = sc_m
        details[f"CLEAN_{mtag}_latest_card"] = m_m["latest_card"]
        wf_sub = sc_m[sc_m["wf_in_window"]]
        diag_d = {}
        for qname, qcol in [("top15", "wf_thr_top15"), ("top20", "wf_thr_top20"), ("top25", "wf_thr_top25")]:
            veto = sc_m["wf_score"] >= sc_m[qcol]
            v_wf = veto[sc_m["wf_in_window"]]
            diag_d[qname] = {
                "n_veto": int(v_wf.sum()),
                "veto_crash_m7_pct": round(float((wf_sub.loc[v_wf, "net_ret"] <= -0.07).mean() * 100.0), 2),
                "clean_crash_m7_pct": round(float((wf_sub.loc[~v_wf, "net_ret"] <= -0.07).mean() * 100.0), 2),
                "veto_mean_pct": round(float(wf_sub.loc[v_wf, "net_ret"].mean() * 100.0), 2),
                "clean_mean_pct": round(float(wf_sub.loc[~v_wf, "net_ret"].mean() * 100.0), 2),
            }
        mine_diag[mtag] = diag_d
    details["CLEAN_mine_diagnostics"] = mine_diag

    # 4. Physical Split (Clean Mine Veto x V1.1 / cold45 / cold50 / Clean Mode B / Clean Mode A Dragon)
    sc_dragon_c, m_dc = lib.run_causal_scorecard_ext(
        df_h, feat_auc, mode="scorecard_0_100", wf_start_date="2023-01-03",
        min_warmup_trades=80, top_k=12, min_k=5, max_corr=0.65, min_t_stat=1.0,
        shrink_tau=20.0, train_filter_mask=(df_h["net_ret"].to_numpy(float) > -0.07),
        min_discrete_bin_cnt=15,
    )
    details["CLEAN_dragon_latest_card"] = m_dc["latest_card"]

    for mtag, sc_m in mine_clean.items():
        for qname, qcol in [("top15", "wf_thr_top15"), ("top20", "wf_thr_top20"), ("top25", "wf_thr_top25")]:
            veto = (sc_m["wf_score"] >= sc_m[qcol]).fillna(False).to_numpy(bool)
            for thr in (78, 80, 82):
                _eval_and_add(rows, details, f"CLEAN_{mtag}_{qname}_V11_S{thr}", "CLEAN_MINE_SPLIT", df_h, "v20_score", float(thr), v20_ctx, wf_ctx, base_comb, wf_cands, veto_mask=veto)
                _eval_and_add(rows, details, f"CLEAN_{mtag}_{qname}_cold50_S{thr}", "CLEAN_MINE_SPLIT", df_h, "v20_cold50", float(thr), v20_ctx, wf_ctx, base_comb, wf_cands, veto_mask=veto)
            for btag in ("v20", "cold45", "cold50"):
                for md in (8, 15, 25):
                    sc_b = mb_cache[(btag, md)]
                    for th in (78, 80, 82, "top20", "top15"):
                        tname = th if isinstance(th, str) else f"S{th}"
                        targ = f"wf_thr_{th}" if isinstance(th, str) else float(th)
                        _eval_and_add(rows, details, f"CLEAN_{mtag}_{qname}_MB_{btag}_d{md}_{tname}", "CLEAN_MINE_SPLIT", sc_b, "wf_score", targ, v20_ctx, wf_ctx, base_comb, wf_cands, veto_mask=veto)
            for dtag, sc_d in [("A_auc", ma_cache["auc_k12"]), ("A_cleanDragon", sc_dragon_c)]:
                for th in ("top20", "top15", "top10"):
                    _eval_and_add(rows, details, f"CLEAN_{mtag}_{qname}_{dtag}_{th}", "CLEAN_MINE_SPLIT", sc_d, "wf_score", f"wf_thr_{th}", v20_ctx, wf_ctx, base_comb, wf_cands, veto_mask=veto)

    df_res = pd.DataFrame(rows)
    df_res.to_csv(f"{OUT_DIR}/_part3_clean_table.csv", index=False)
    with open(f"{OUT_DIR}/_part3_clean_details.json", "w", encoding="utf-8") as f:
        json.dump(details, f, ensure_ascii=False, indent=2, default=str)
    print(f"[Part3 DONE in {time.time()-t0:.1f}s] {len(df_res)} variants saved.")
    print(df_res.sort_values("nav_wf", ascending=False)[
        ["variant", "n_wf", "wr_wf", "nav_wf", "ex5_wf", "mdd_wf", "big_loss_m7_pct", "nav_2526", "wr_26h2", "nav_26h2", "comb_wf_nav_ratio"]
    ].head(20).to_string(index=False))


if __name__ == "__main__":
    main()

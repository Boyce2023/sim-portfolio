#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD035 Wave 2A-3 Part 2: Module 3 (334 new factors Mode A & B) + Module 4 (Mine/Dragon split & 09:25 auction)."""
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

    # Cold-day F06 disabled base
    f6 = df_h["s20cm_F06_inst_net_pos"].to_numpy(float)
    mkt10 = df_h["mkt10_zt_est_t1"].to_numpy(float)
    df_h["v20_cold45"] = np.where(mkt10 < 45.0, df_h["v20_score"].to_numpy(float) - f6, df_h["v20_score"].to_numpy(float))

    rows, details = [], {}

    # ================= MODULE 3: 334 NEW FACTORS (MODE B & MODE A) =================
    feat_334_xtr = list(dict.fromkeys(meta["entry_num"] + meta["xtr_active"]))
    feat_334_xtr_auc = list(dict.fromkeys(meta["entry_num"] + meta["xtr_fixed"] + meta["auc_cols"]))
    feat_all_a = list(dict.fromkeys(F9_COLS + meta["xtr_active"] + meta["entry_num"]))
    feat_all_a_auc = list(dict.fromkeys(F9_COLS + meta["xtr_fixed"] + meta["entry_num"] + meta["auc_cols"]))

    # Mode B: V20 + delta (max_delta = 8, 15, 25)
    mode_b_cache = {}
    for btag, orig_col, fcols in [
        ("new334_xtr", "v20_score", feat_334_xtr),
        ("new334_auc", "v20_score", feat_334_xtr_auc),
        ("cold45_new334", "v20_cold45", feat_334_xtr_auc),
    ]:
        for md in (8, 15, 25):
            sc_b, m_b = lib.run_causal_scorecard_ext(
                df_h, fcols, mode="delta_patch", wf_start_date="2023-01-03",
                min_warmup_trades=80, top_k=10, min_k=5, max_corr=0.65, min_t_stat=1.0,
                shrink_tau=20.0, max_delta=md, orig_score_col=orig_col, max_corr_orig=0.70,
            )
            mode_b_cache[(btag, md)] = sc_b
            details[f"M3_B_{btag}_d{md}_latest_card"] = m_b["latest_card"]
            for th in ALL_THRS:
                tname = th if isinstance(th, str) else f"S{th}"
                targ = f"wf_thr_{th}" if isinstance(th, str) else float(th)
                _eval_and_add(rows, details, f"M3_B_{btag}_d{md}_{tname}", "M3_MODE_B", sc_b, "wf_score", targ, v20_ctx, wf_ctx, base_comb, wf_cands)

    # Mode A: 0..100 from scratch
    mode_a_cache = {}
    for atag, fcols, tk, mt in [
        ("all_k12_t10", feat_all_a, 12, 1.0),
        ("all_k15_t10", feat_all_a, 15, 1.0),
        ("all_k12_t15", feat_all_a, 12, 1.5),
        ("all_auc_k12_t10", feat_all_a_auc, 12, 1.0),
        ("all_auc_k15_t10", feat_all_a_auc, 15, 1.0),
    ]:
        sc_a, m_a = lib.run_causal_scorecard_ext(
            df_h, fcols, mode="scorecard_0_100", wf_start_date="2023-01-03",
            min_warmup_trades=80, top_k=tk, min_k=5, max_corr=0.65, min_t_stat=mt, shrink_tau=20.0,
        )
        mode_a_cache[atag] = sc_a
        details[f"M3_A_{atag}_latest_card"] = m_a["latest_card"]
        for th in ALL_THRS:
            tname = th if isinstance(th, str) else f"S{th}"
            targ = f"wf_thr_{th}" if isinstance(th, str) else float(th)
            _eval_and_add(rows, details, f"M3_A_{atag}_{tname}", "M3_MODE_A", sc_a, "wf_score", targ, v20_ctx, wf_ctx, base_comb, wf_cands)

    # ================= MODULE 4: MINE/DRAGON SPLIT & 09:25 AUCTION SCISSOR =================
    # 4A. Causal Minefield Scorecard (target: net_ret <= -0.07)
    mine_models = {}
    mine_diag = {}
    for mtag, fcols in [("mine_pre", feat_all_a), ("mine_auc", feat_all_a_auc)]:
        sc_m, m_m = lib.run_causal_scorecard_ext(
            df_h, fcols, mode="scorecard_0_100", wf_start_date="2023-01-03",
            min_warmup_trades=80, top_k=10, min_k=5, max_corr=0.65, min_t_stat=1.0,
            shrink_tau=20.0, target_mode="mine_m7",
        )
        mine_models[mtag] = sc_m
        details[f"M4_{mtag}_latest_card"] = m_m["latest_card"]
        wf_sub = sc_m[sc_m["wf_in_window"]]
        diag_d = {}
        for qname, qcol in [("top15", "wf_thr_top15"), ("top20", "wf_thr_top20"), ("top25", "wf_thr_top25")]:
            veto = sc_m["wf_score"] >= sc_m[qcol]
            v_wf = veto[sc_m["wf_in_window"]]
            bad_hit = float((wf_sub.loc[v_wf, "net_ret"] <= -0.07).mean() * 100.0) if v_wf.any() else 0.0
            clean_hit = float((wf_sub.loc[~v_wf, "net_ret"] <= -0.07).mean() * 100.0)
            bad_mean = float(wf_sub.loc[v_wf, "net_ret"].mean() * 100.0) if v_wf.any() else 0.0
            clean_mean = float(wf_sub.loc[~v_wf, "net_ret"].mean() * 100.0)
            diag_d[qname] = {
                "n_veto": int(v_wf.sum()), "veto_rate_pct": round(float(v_wf.mean() * 100.0), 2),
                "veto_crash_m7_pct": round(bad_hit, 2), "clean_crash_m7_pct": round(clean_hit, 2),
                "veto_mean_pct": round(bad_mean, 2), "clean_mean_pct": round(clean_mean, 2),
            }
        mine_diag[mtag] = diag_d
    details["M4_mine_diagnostics"] = mine_diag

    # Apply causal Mine Veto (top15 / top20 / top25) to: V1.1, cold45, Mode B, Mode A (all vs clean-trained)
    sc_dragon_clean, m_dc = lib.run_causal_scorecard_ext(
        df_h, feat_all_a_auc, mode="scorecard_0_100", wf_start_date="2023-01-03",
        min_warmup_trades=80, top_k=12, min_k=5, max_corr=0.65, min_t_stat=1.0,
        shrink_tau=20.0, train_filter_mask=(df_h["net_ret"].to_numpy(float) > -0.07),
    )
    details["M4_dragon_clean_latest_card"] = m_dc["latest_card"]

    for mtag, sc_m in mine_models.items():
        for qname, qcol in [("top15", "wf_thr_top15"), ("top20", "wf_thr_top20"), ("top25", "wf_thr_top25")]:
            veto = (sc_m["wf_score"] >= sc_m[qcol]).fillna(False).to_numpy(bool)
            # 1) V1.1 & cold45 + Mine Veto
            for thr in (78, 80, 82):
                _eval_and_add(rows, details, f"M4_{mtag}_{qname}_V11_S{thr}", "M4_MINE_SPLIT", df_h, "v20_score", float(thr), v20_ctx, wf_ctx, base_comb, wf_cands, veto_mask=veto)
                _eval_and_add(rows, details, f"M4_{mtag}_{qname}_cold45_S{thr}", "M4_MINE_SPLIT", df_h, "v20_cold45", float(thr), v20_ctx, wf_ctx, base_comb, wf_cands, veto_mask=veto)
            # 2) Mode B (d15, d8, d25) + Mine Veto
            for md in (8, 15, 25):
                sc_b = mode_b_cache[("new334_auc", md)]
                for th in (78, 80, 82, "top20", "top15"):
                    tname = th if isinstance(th, str) else f"S{th}"
                    targ = f"wf_thr_{th}" if isinstance(th, str) else float(th)
                    _eval_and_add(rows, details, f"M4_{mtag}_{qname}_MB_d{md}_{tname}", "M4_MINE_SPLIT", sc_b, "wf_score", targ, v20_ctx, wf_ctx, base_comb, wf_cands, veto_mask=veto)
            # 3) Mode A (all_auc_k12_t10 & clean-trained dragon) + Mine Veto
            for dtag, sc_d in [("A_auc", mode_a_cache["all_auc_k12_t10"]), ("A_cleanDragon", sc_dragon_clean)]:
                for th in ("top20", "top15", "top10", 76, 78, 80):
                    tname = th if isinstance(th, str) else f"S{th}"
                    targ = f"wf_thr_{th}" if isinstance(th, str) else float(th)
                    _eval_and_add(rows, details, f"M4_{mtag}_{qname}_{dtag}_{tname}", "M4_MINE_SPLIT", sc_d, "wf_score", targ, v20_ctx, wf_ctx, base_comb, wf_cands, veto_mask=veto)

    # 4B. Direct 09:25 Scissor-Spread Rules (Same-theme 10cm leader strong/yizi vs nuke)
    v20_sc = df_h["v20_score"].to_numpy(float)
    cold45_sc = df_h["v20_cold45"].to_numpy(float)
    yizi10 = df_h["auc_thm10_has_yizi_open"].fillna(0.0).to_numpy(float)
    ldr10 = df_h["auc_thm10_ldr_open_pct"].fillna(0.0).to_numpy(float)
    nuke10 = df_h["auc_thm10_nuke_ratio"].fillna(0.0).to_numpy(float)
    # Test clean scissor penalties/bonuses on V1.1 & cold45
    scissor_specs = [
        ("V11_pen_yizi10_5", v20_sc - 5.0 * (yizi10 >= 1)),
        ("V11_pen_nuke10_5", v20_sc - 5.0 * ((ldr10 <= -5.0) | (nuke10 >= 0.5))),
        ("V11_pen_both_5", v20_sc - 5.0 * ((yizi10 >= 1) | (ldr10 <= -5.0) | (nuke10 >= 0.5))),
        ("cold45_pen_both_5", cold45_sc - 5.0 * ((yizi10 >= 1) | (ldr10 <= -5.0) | (nuke10 >= 0.5))),
        ("V11_scissor_sweet", v20_sc + np.where((yizi10 == 0) & (ldr10 >= -2.0) & (ldr10 < 5.0), 3.0, np.where((ldr10 <= -5.0) | (yizi10 >= 1), -5.0, 0.0))),
    ]
    for sname, sarr in scissor_specs:
        d_s = df_h.copy()
        d_s["_sc"] = sarr
        for thr in (80, 82):
            _eval_and_add(rows, details, f"M4_AUC_{sname}_S{thr}", "M4_0925_SCISSOR", d_s, "_sc", float(thr), v20_ctx, wf_ctx, base_comb, wf_cands)

    df_res = pd.DataFrame(rows)
    df_res.to_csv(f"{OUT_DIR}/_part2_m3_m4_table.csv", index=False)
    with open(f"{OUT_DIR}/_part2_m3_m4_details.json", "w", encoding="utf-8") as f:
        json.dump(details, f, ensure_ascii=False, indent=2, default=str)
    print(f"[Part2 DONE in {time.time()-t0:.1f}s] {len(df_res)} variants saved.")
    print(df_res.sort_values("nav_wf", ascending=False)[
        ["variant", "n_wf", "wr_wf", "nav_wf", "ex5_wf", "mdd_wf", "nav_2526", "n_26h2", "wr_26h2", "nav_26h2", "comb_wf_nav_ratio"]
    ].head(25).to_string(index=False))


if __name__ == "__main__":
    main()

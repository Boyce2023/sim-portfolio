#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 2A-1 Runner Part 2: Module 3 (334 New Factors Mode B & Mode A)
+ Module 4 (Physical Risk/Dragon Split) + Module 5 (Solo/Resonance & Rank #2 Fallback).
"""
import json
import os
import sys
import time

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import numpy as np
import pandas as pd

DIR = os.path.dirname(os.path.abspath(__file__))
if DIR not in sys.path:
    sys.path.insert(0, DIR)

import w2a1_data_and_eval as de
import w2a1_causal_models as cm
import wf_scorecard_engine as wf
import _wf_sim_and_metrics as wfm


def run_mode_a_grid(bundle: dict, strat: str, module: str, tag: str, feat_cols: list[str], recalc_freq: str = "daily", top_k: int = 12, min_t_stat: float = 1.0, thresholds=("all_cands", "top30", "top20", "top10", "top5", 70, 75, 80, 85)) -> tuple[list[dict], dict]:
    df = bundle["p12"] if strat == "1to2" else bundle["p23"]
    res = wf.run_wf_scorecard_new_strategy(
        df, feat_cols, v20_ctx=bundle["v20_ctx"], wf_start_date=de.WF_START, end_date=de.WF_END,
        min_warmup_trades=80, recalc_freq=recalc_freq, top_k=top_k, max_corr=0.65,
        min_t_stat=min_t_stat, thresholds=thresholds, eval_v20_patch=False, perm_n=100,
    )
    rows = []
    for th in thresholds:
        tname = str(th) if not isinstance(th, (int, float)) else f"abs_{int(th)}"
        tr = res["threshold_results"][tname]
        rows.append(de.eval_variant_full(bundle, strat, module, f"{tag}__{tname}", tr["pass_df"], tr["slot_df"], perm_n=1000))
    return rows, res


def main():
    t0 = time.time()
    bundle = de.load_all_bundle()
    p12, p23 = bundle["p12"], bundle["p23"]
    orig_12 = p12["v20_score"].to_numpy(float)
    orig_23 = p23["v20_score"].to_numpy(float)
    s12_cols, s23_cols = bundle["s12_atom_28"], bundle["s23_af_18"]
    xtr_37, new_330 = bundle["xtr_37"], bundle["new_330"]
    rows = []

    # --- 3. Module 3: 334 New Factors (330 numeric) Mode B & Mode A ---
    print("[M3] Running 330 new factors Mode B...")
    for ftag, feats_12, feats_23 in [
        ("New330", new_330, new_330),
        ("New330_XTR37", new_330 + xtr_37, new_330 + xtr_37),
    ]:
        for md in (10, 15, 25):
            for freq in ("daily", "monthly"):
                if freq == "monthly" and md == 10:
                    continue
                d12, _ = cm.score_mode_b_all_rows(p12, feats_12, wf_start_date=de.WF_START, recalc_freq=freq, top_k=10, max_delta=md)
                ps12, sl12 = de.sim_1to2_custom(p12, orig_12 + d12)
                rows.append(de.eval_variant_full(bundle, "1to2", "M3_New_ModeB", f"{ftag}_ModeB_d{md}_{freq}", ps12, sl12, perm_n=1000))
                if md == 15 and freq == "daily":
                    ps12_h, sl12_h = de.sim_1to2_custom(p12, orig_12 + d12, thr_vec=p12["thr_vec"].to_numpy(float) + 10.0)
                    rows.append(de.eval_variant_full(bundle, "1to2", "M3_New_ModeB", f"{ftag}_ModeB_d15_thrP10", ps12_h, sl12_h, perm_n=1000))

                d23, _ = cm.score_mode_b_all_rows(p23, feats_23, wf_start_date=de.WF_START, recalc_freq=freq, top_k=10, max_delta=md)
                ps23, sl23 = de.sim_2to3_custom(p23, orig_23 + d23, thr=90.0)
                rows.append(de.eval_variant_full(bundle, "2to3", "M3_New_ModeB", f"{ftag}_ModeB_d{md}_{freq}", ps23, sl23, perm_n=1000))
                if md in (15, 25) and freq == "daily":
                    for hthr in (93.0, 96.0):
                        ps23_h, sl23_h = de.sim_2to3_custom(p23, orig_23 + d23, thr=hthr)
                        rows.append(de.eval_variant_full(bundle, "2to3", "M3_New_ModeB", f"{ftag}_ModeB_d{md}_thr{int(hthr)}", ps23_h, sl23_h, perm_n=1000))

    # Strict t-stat 1.5 variant on Mode B
    for st_tag, df, orig_sc, feats in [("1to2", p12, orig_12, new_330 + xtr_37), ("2to3", p23, orig_23, new_330 + xtr_37)]:
        d_s, _ = cm.score_mode_b_all_rows(df, feats, wf_start_date=de.WF_START, recalc_freq="daily", top_k=8, min_t_stat=1.5, max_delta=15)
        if st_tag == "1to2":
            ps, sl = de.sim_1to2_custom(df, orig_sc + d_s)
        else:
            ps, sl = de.sim_2to3_custom(df, orig_sc + d_s, thr=90.0)
        rows.append(de.eval_variant_full(bundle, st_tag, "M3_New_ModeB", "New330_XTR37_ModeB_d15_t15_k8", ps, sl, perm_n=1000))

    print("[M3] Running Mode A 0..100 full rebuild...")
    for mtag, f12, f23, freq, tk, mt in [
        ("ModeA_New330_d", new_330, new_330, "daily", 12, 1.0),
        ("ModeA_Atom_New330_d", s12_cols + new_330, s23_cols + new_330, "daily", 12, 1.0),
        ("ModeA_All_d", s12_cols + xtr_37 + new_330, s23_cols + xtr_37 + new_330, "daily", 12, 1.0),
        ("ModeA_All_m", s12_cols + xtr_37 + new_330, s23_cols + xtr_37 + new_330, "monthly", 12, 1.0),
        ("ModeA_All_t15_k10", s12_cols + xtr_37 + new_330, s23_cols + xtr_37 + new_330, "daily", 10, 1.5),
    ]:
        r12, _ = run_mode_a_grid(bundle, "1to2", "M3_New_ModeA", mtag, f12, recalc_freq=freq, top_k=tk, min_t_stat=mt)
        r23, _ = run_mode_a_grid(bundle, "2to3", "M3_New_ModeA", mtag, f23, recalc_freq=freq, top_k=tk, min_t_stat=mt)
        rows.extend(r12)
        rows.extend(r23)

    # --- 4. Module 4: Risk Blacklist vs Dragon-Hunt Separation ---
    print("[M4] Running Risk/Dragon physical separation...")
    all_f12 = s12_cols + xtr_37 + new_330
    all_f23 = s23_cols + xtr_37 + new_330

    d12_b15, _ = cm.score_mode_b_all_rows(p12, new_330 + xtr_37, wf_start_date=de.WF_START, recalc_freq="daily", top_k=10, max_delta=15)
    d23_b15, _ = cm.score_mode_b_all_rows(p23, new_330 + xtr_37, wf_start_date=de.WF_START, recalc_freq="daily", top_k=10, max_delta=15)

    for bcut, blbl in [(-0.07, "m7"), (-0.05, "m5")]:
        for dtgt in ("util", "big_win"):
            if bcut == -0.05 and dtgt == "big_win":
                continue
            rd12 = cm.run_causal_risk_and_dragon(p12, all_f12, wf_start_date=de.WF_START, blowup_cut=bcut, dragon_target=dtgt)
            rd23 = cm.run_causal_risk_and_dragon(p23, all_f23, wf_start_date=de.WF_START, blowup_cut=bcut, dragon_target=dtgt)

            for qcol, qlbl in [("risk_q85", "top15"), ("risk_q80", "top20"), ("risk_q75", "top25")]:
                safe12 = np.where(np.isnan(rd12["wf_risk_score"]), True, rd12["wf_risk_score"] < rd12[qcol])
                safe23 = np.where(np.isnan(rd23["wf_risk_score"]), True, rd23["wf_risk_score"] < rd23[qcol])

                if dtgt == "util":
                    # 4A: V20 orig score on safe pool (safe-pool fallback vs strict kill)
                    ps12, sl12 = de.sim_1to2_custom(p12, orig_12, mask=safe12)
                    rows.append(de.eval_variant_full(bundle, "1to2", "M4_RiskV20", f"Risk_{blbl}_drop_{qlbl}__V20_safePool", ps12, sl12, perm_n=1000))
                    ps23, sl23 = de.sim_2to3_custom(p23, orig_23, thr=90.0, mask=safe23)
                    rows.append(de.eval_variant_full(bundle, "2to3", "M4_RiskV20", f"Risk_{blbl}_drop_{qlbl}__V20_safePool", ps23, sl23, perm_n=1000))

                    # Strict kill day if original #1 is blacklisted (no #2 fallback)
                    _, sl12_b = de.sim_1to2_custom(p12, orig_12)
                    _, sl23_b = de.sim_2to3_custom(p23, orig_23, thr=90.0)
                    s12_map = dict(zip(zip(p12["buy_date"], p12["code"]), safe12))
                    s23_map = dict(zip(zip(p23["buy_date"], p23["code"]), safe23))
                    sl12_sk = sl12_b[[s12_map[(r.buy_date, r.code)] for r in sl12_b.itertuples()]]
                    sl23_sk = sl23_b[[s23_map[(r.buy_date, r.code)] for r in sl23_b.itertuples()]]
                    rows.append(de.eval_variant_full(bundle, "1to2", "M4_RiskV20", f"Risk_{blbl}_drop_{qlbl}__V20_strictKill", ps12, sl12_sk, perm_n=1000))
                    rows.append(de.eval_variant_full(bundle, "2to3", "M4_RiskV20", f"Risk_{blbl}_drop_{qlbl}__V20_strictKill", ps23, sl23_sk, perm_n=1000))

                    # 4C: Mode B d15 + Risk blacklist
                    ps12_b, sl12_b2 = de.sim_1to2_custom(p12, orig_12 + d12_b15, mask=safe12)
                    rows.append(de.eval_variant_full(bundle, "1to2", "M4_RiskModeB", f"Risk_{blbl}_drop_{qlbl}__ModeB_d15", ps12_b, sl12_b2, perm_n=1000))
                    ps23_b, sl23_b2 = de.sim_2to3_custom(p23, orig_23 + d23_b15, thr=90.0, mask=safe23)
                    rows.append(de.eval_variant_full(bundle, "2to3", "M4_RiskModeB", f"Risk_{blbl}_drop_{qlbl}__ModeB_d15", ps23_b, sl23_b2, perm_n=1000))

                # 4B: Independent Dragon-Hunting Scorecard on safe pool (both targets)
                for d_thr_col, d_lbl in [("drag_q80", "dragTop20"), ("drag_q90", "dragTop10"), (75.0, "dragAbs75")]:
                    for st_nm, df_s, rd_s, sf_s in [("1to2", p12, rd12, safe12), ("2to3", p23, rd23, safe23)]:
                        df_tmp = df_s.copy()
                        df_tmp["wf_dragon_score"] = rd_s["wf_dragon_score"].values
                        df_tmp["can_buy_hygiene"] = (~df_tmp["is_yizi"].to_numpy(bool)) & df_tmp["net_ret"].notna().to_numpy(bool) & sf_s
                        if "sim_ok" in df_tmp.columns:
                            df_tmp["can_buy_hygiene"] &= df_tmp["sim_ok"].fillna(True).to_numpy(bool)
                        df_tmp["wf_in_window"] = df_tmp["buy_date"] >= de.WF_START
                        if isinstance(d_thr_col, str):
                            df_tmp["_dthr"] = rd_s[d_thr_col].values
                            t_arg = "_dthr"
                        else:
                            t_arg = d_thr_col
                        ps_d, sl_d = wfm.select_single_slot_trades(df_tmp, score_col="wf_dragon_score", threshold=t_arg, wf_only=True)
                        rows.append(de.eval_variant_full(bundle, st_nm, "M4_RiskDragon", f"Risk_{blbl}_{qlbl}__Drag_{dtgt}_{d_lbl}", ps_d, sl_d, perm_n=1000))

    # --- 5. Module 5: Solo vs Resonance Days & Rank #2 Fallback ---
    print("[M5] Running Solo vs Resonance & Rank #2 Fallback...")
    # 5.1 Rank #2 fallback on 1to2 when #1 fails trigger (sim_ok==False)
    ps12_fb, sl12_fb = de.sim_1to2_custom(p12, orig_12, allow_next_rank=True)
    rows.append(de.eval_variant_full(bundle, "1to2", "M5_Rank2Fallback", "V20_1to2_Rank2Fallback", ps12_fb, sl12_fb, perm_n=1000))
    ps12_fb_m, sl12_fb_m = de.sim_1to2_custom(p12, orig_12 + d12_b15, allow_next_rank=True)
    rows.append(de.eval_variant_full(bundle, "1to2", "M5_Rank2Fallback", "ModeB_d15_1to2_Rank2Fallback", ps12_fb_m, sl12_fb_m, perm_n=1000))

    # 5.2 Diagnostics + Dynamic Pass-Count Thresholds
    ps12_base, _ = de.sim_1to2_custom(p12, orig_12)
    ps23_base, _ = de.sim_2to3_custom(p23, orig_23, thr=90.0)
    cnt12_pass = ps12_base.groupby("buy_date").size().to_dict()
    cnt23_pass = ps23_base.groupby("buy_date").size().to_dict()
    cnt12_cand = p12.groupby("buy_date").size().to_dict()
    cnt23_cand = p23.groupby("buy_date").size().to_dict()

    # Solo vs Resonance diagnostics on WF passing days
    diag_m5 = {}
    for st_nm, ps_b, sl_b_orig, c_pass, c_cand in [
        ("1to2", ps12_base, de.sim_1to2_custom(p12, orig_12)[1], cnt12_pass, cnt12_cand),
        ("2to3", ps23_base, de.sim_2to3_custom(p23, orig_23, thr=90.0)[1], cnt23_pass, cnt23_cand),
    ]:
        sl_w = sl_b_orig[sl_b_orig["buy_date"].between(de.WF_START, de.WF_END)].copy()
        sl_w["n_pass_day"] = sl_w["buy_date"].map(c_pass).fillna(1).astype(int)
        sl_w["n_cand_day"] = sl_w["buy_date"].map(c_cand).fillna(1).astype(int)
        solo = sl_w[sl_w["n_pass_day"] == 1]["net_ret"].to_numpy(float)
        res_d = sl_w[sl_w["n_pass_day"] >= 2]["net_ret"].to_numpy(float)
        ps_w = ps_b[ps_b["buy_date"].between(de.WF_START, de.WF_END)].copy()
        ps_w["rk_day"] = ps_w.groupby("buy_date")["v20_score"].rank(ascending=False, method="first")
        r1 = ps_w[ps_w["buy_date"].isin(ps_w[ps_w["rk_day"] >= 2]["buy_date"]) & (ps_w["rk_day"] == 1)]["net_ret"].to_numpy(float)
        r2 = ps_w[ps_w["rk_day"] == 2]["net_ret"].to_numpy(float)
        diag_m5[st_nm] = {
            "solo_pass_n": int(len(solo)), "solo_wr_pct": round(float((solo > 0).mean() * 100), 2) if len(solo) else 0.0,
            "solo_mean_pct": round(float(solo.mean() * 100), 2) if len(solo) else 0.0,
            "solo_nav": round(float(np.prod(1 + solo)), 4) if len(solo) else 1.0,
            "res_pass_n": int(len(res_d)), "res_wr_pct": round(float((res_d > 0).mean() * 100), 2) if len(res_d) else 0.0,
            "res_mean_pct": round(float(res_d.mean() * 100), 2) if len(res_d) else 0.0,
            "res_nav": round(float(np.prod(1 + res_d)), 4) if len(res_d) else 1.0,
            "multi_pass_days_rank1_n": int(len(r1)), "rank1_mean_pct": round(float(r1.mean() * 100), 2) if len(r1) else 0.0,
            "multi_pass_days_rank2_n": int(len(r2)), "rank2_mean_pct": round(float(r2.mean() * 100), 2) if len(r2) else 0.0,
            "rank2_wr_pct": round(float((r2 > 0).mean() * 100), 2) if len(r2) else 0.0,
        }

    # Dynamic pass-count / cand-count threshold variants
    # 1to2
    n_c12 = p12["buy_date"].map(cnt12_cand).to_numpy(int)
    n_p12 = p12["buy_date"].map(cnt12_pass).fillna(0).to_numpy(int)
    tv12 = p12["thr_vec"].to_numpy(float)
    for vtag, tv_new, m_extra in [
        ("SoloCand_TightP15", np.where(n_c12 == 1, tv12 + 15.0, tv12), None),
        ("SoloPass_TightP15", np.where(n_p12 == 1, tv12 + 15.0, tv12), None),
        ("ResCand3_RelaxM10", np.where(n_c12 >= 3, tv12 - 10.0, tv12), None),
        ("ResPassOnly_ge2", tv12, (n_p12 >= 2)),
        ("SoloPassOnly_eq1", tv12, (n_p12 == 1)),
    ]:
        ps, sl = de.sim_1to2_custom(p12, orig_12, thr_vec=tv_new, mask=m_extra)
        rows.append(de.eval_variant_full(bundle, "1to2", "M5_SoloResonance", vtag, ps, sl, perm_n=1000))

    # 2to3
    n_c23 = p23["buy_date"].map(cnt23_cand).to_numpy(int)
    n_p23 = p23["buy_date"].map(cnt23_pass).fillna(0).to_numpy(int)
    for vtag, thr_new, m_extra in [
        ("SoloCand_Tight95", np.where(n_c23 == 1, 95.0, 90.0), None),
        ("SoloPass_Tight95", np.where(n_p23 == 1, 95.0, 90.0), None),
        ("ResCand3_Relax86", np.where(n_c23 >= 3, 86.0, 90.0), None),
        ("ResCand3_Relax86_Solo95", np.where(n_c23 == 1, 95.0, np.where(n_c23 >= 3, 86.0, 90.0)), None),
        ("ResPassOnly_ge2", 90.0, (n_p23 >= 2)),
        ("SoloPassOnly_eq1", 90.0, (n_p23 == 1)),
    ]:
        ps, sl = de.sim_2to3_custom(p23, orig_23, thr=thr_new, mask=m_extra)
        rows.append(de.eval_variant_full(bundle, "2to3", "M5_SoloResonance", vtag, ps, sl, perm_n=1000))

    # Also test Gap filter on 2to3 & 1to2 multi-candidate days
    s2_gap12 = p12.groupby("buy_date")["v20_score"].transform(lambda s: s.max() - s.nlargest(2).iloc[-1] if len(s) >= 2 else 999.0).to_numpy(float)
    ps12_g, sl12_g = de.sim_1to2_custom(p12, orig_12, mask=(n_p12 == 1) | (s2_gap12 >= 10.0))
    rows.append(de.eval_variant_full(bundle, "1to2", "M5_SoloResonance", "ResGap_ge10_filter", ps12_g, sl12_g, perm_n=1000))
    s2_gap23 = p23.groupby("buy_date")["v20_score"].transform(lambda s: s.max() - s.nlargest(2).iloc[-1] if len(s) >= 2 else 999.0).to_numpy(float)
    ps23_g, sl23_g = de.sim_2to3_custom(p23, orig_23, thr=90.0, mask=(n_p23 == 1) | (s2_gap23 >= 4.0))
    rows.append(de.eval_variant_full(bundle, "2to3", "M5_SoloResonance", "ResGap_ge4_filter", ps23_g, sl23_g, perm_n=1000))

    df_res = pd.DataFrame(rows)
    df_res.to_csv(f"{de.OUT_DIR}/_part2_m3_m4_m5.csv", index=False)
    with open(f"{de.OUT_DIR}/_diag_m5.json", "w", encoding="utf-8") as f:
        json.dump(diag_m5, f, ensure_ascii=False, indent=2)
    print(f"[M3+M4+M5 DONE in {time.time()-t0:.1f}s] {len(df_res)} variants saved.")


if __name__ == "__main__":
    main()

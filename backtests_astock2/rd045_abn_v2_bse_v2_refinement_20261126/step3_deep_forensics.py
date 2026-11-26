#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD045 Step 3: Deep Red-Team Forensics on Track 1 Theme Continuation & Track 2 BSE Sensitivity."""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"
import json, sys, time
import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
BASE_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
RD045_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd045_abn_v2_bse_v2_refinement_20261126"
for p in (BASE_DIR, RD045_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import wf_scorecard_engine as wf
import _wf_sim_and_metrics as wfm
import _rd045_common as cm
import _rd045_bse_helpers as bh

END_DT = "2026-11-25"


def run_track1_forensics(v20_ctx: dict) -> dict:
    df = pd.read_parquet(f"{RD045_DIR}/track1_abn_v2_events_pit.parquet")
    bench_df = v20_ctx["bench"]
    is_a = (df["entry_type"] == "V2_A").to_numpy()
    is_c = (df["entry_type"] == "V2_C").to_numpy()
    v2a_ex = is_a & (df["abn_mg100_prev"] <= 5.0).to_numpy() & (df["abn_mg100_b"] >= 10.0).to_numpy()
    stk3 = (df["abn_max_streak_wave"] >= 3).to_numpy()
    amt3 = (df["abn_sig_amt_yi"] >= 3.0).to_numpy()
    ma5 = (df["abn_above_ma5"] == 1).to_numpy()
    op53 = df["abn_open_pct"].between(-5.0, 3.0).to_numpy()
    no100 = (df["abn_was_hit_100"] == 0).to_numpy()
    shrk = (df["abn_vol_shrink"] <= 0.85).to_numpy()

    wins_yr = [
        ("FULL_5Y", "2021-01-04", END_DT), ("WF_2326", "2023-01-03", END_DT),
        ("Y2021", "2021-01-04", "2021-12-31"), ("Y2022", "2022-01-01", "2022-12-31"),
        ("Y2023", "2023-01-01", "2023-12-31"), ("Y2024", "2024-01-01", "2024-12-31"),
        ("Y2025", "2025-01-01", "2025-12-31"), ("Y2026", "2026-01-01", END_DT),
    ]

    # 1. Detailed year-by-year + Top/Bot trades on V2_C_ThmUp_Qual_Amt3 & OpenQual_G1_ThmUp
    det_out = {}
    for nm, msk, ex in [
        ("OpenQual_G1_ThmUp_S7", (v2a_ex | is_c) & stk3 & amt3 & ma5 & op53 & (df["thm_delta"] > 0).to_numpy(), "S7_lianban"),
        ("OpenQual_G1_ThmUp_S1", (v2a_ex | is_c) & stk3 & amt3 & ma5 & op53 & (df["thm_delta"] > 0).to_numpy(), "S1_hold1c"),
        ("V2C_ThmUp_Qual_S7", is_c & no100 & df["abn_open_pct"].between(-4.5, 2.5).to_numpy() & stk3 & amt3 & ma5 & (df["thm_delta"] > 0).to_numpy(), "S7_lianban"),
        ("V2A_ThmUp_S2", v2a_ex & stk3 & amt3 & ma5 & op53 & (df["thm_delta"] > 0).to_numpy(), "S2_hold2c"),
    ]:
        vw = cm.make_clean_view(df, ex, msk, 0.0030)
        cp = cm.make_clean_view(df, ex, (is_a | is_c), 0.0030)
        ps, sl = wfm.select_single_slot_trades(vw, score_col="abn_sig_amt_yi", threshold=None, tie_col="abn_sig_amt_yi", wf_only=False)
        ev30 = cm.eval_slice_exact(sl, ps, cp, bench_df, "mtm_json_use", 0.0030, "2021-01-04", END_DT, wins_yr, perm_n=500)
        ev80 = cm.eval_slice_exact(sl.assign(net_ret=(1.0 + sl["gross_ret"]) * (1.0 - 0.0080) - 1.0), ps, cp, bench_df, "mtm_json_use", 0.0080, "2021-01-04", END_DT, wins_yr[:2], perm_n=20)
        v20c = cm.compute_v20_corr_and_patch(ps, sl, v20_ctx, "mtm_json_use", 0.0030, "2023-01-03", "2026-11-16", score_col="abn_sig_amt_yi")
        top5 = sl.sort_values("net_ret", ascending=False).head(6)[["buy_date", "exit_date", "code", "abn_open_pct", "thm_score_t0", "thm_score_sig", "net_ret"]].to_dict("records")
        bot5 = sl.sort_values("net_ret", ascending=True).head(5)[["buy_date", "exit_date", "code", "abn_open_pct", "thm_score_t0", "thm_score_sig", "net_ret"]].to_dict("records")
        det_out[nm] = {"windows_30bps": ev30["windows"], "wf_80bps": ev80["windows"]["WF_2326"], "full_80bps": ev80["windows"]["FULL_5Y"],
                       "perm": ev30["permutation"], "v20_corr": v20c["corr_all_days"],
                       "v20_delta_ratio": v20c["patch_m1"]["delta_nav_ratio_full_wf"] if v20c.get("patch_m1") else None,
                       "v20_emp": v20c["patch_m2"]["windows"]["FULL_WF"] if v20c.get("patch_m2") else None,
                       "top6": top5, "bot5": bot5}

    # 2. Plateau on thm_ratio / thm_delta & amt_yi on OpenQual (to test overfitting vs true plateau!)
    plat = []
    base_oq = (v2a_ex | is_c) & stk3 & ma5 & op53
    for a_thr in (2.0, 3.0, 5.0):
        for r_thr in (0.75, 0.85, 0.95, 1.00, 1.10, 1.20):
            msk = base_oq & (df["abn_sig_amt_yi"] >= a_thr).to_numpy() & (df["thm_ratio"] >= r_thr).to_numpy()
            for ex in ("S1_hold1c", "S7_lianban"):
                vw = cm.make_clean_view(df, ex, msk, 0.0030)
                if len(vw) < 10:
                    continue
                ps, sl = wfm.select_single_slot_trades(vw, score_col="abn_sig_amt_yi", threshold=None, wf_only=False)
                ev = cm.eval_slice_exact(sl, ps, vw, bench_df, "mtm_json_use", 0.0030, "2021-01-04", END_DT, wins_yr[:5], perm_n=100)
                f5, wfw, y23 = ev["windows"]["FULL_5Y"], ev["windows"]["WF_2326"], ev["windows"]["Y2023"]
                plat.append({"amt_min": a_thr, "thm_ratio_min": r_thr, "exit": ex, "n5y": f5["n"], "nav5y": f5["nav"],
                             "ex5_5y": f5["ex_top5_nav"], "n_wf": wfw["n"], "nav_wf": wfw["nav"], "ex5_wf": wfw["ex_top5_nav"],
                             "nav_23": y23["nav"], "wr5y": f5["wr_pct"], "p_any": ev["permutation"]["any_cand_day_p_nav"]})

    # 3. Also test Low-DOF WF directly INSIDE OpenQual (ma5 & op53 & stk3 & amt3)
    oq_wf_rows = []
    f_oq = ["thm_delta", "thm_ratio", "thm_rel_delta", "thm_score_sig", "thm_kp_cnt_sig", "thm_ind_zt3d_sig", "abn_sig_amt_yi", "abn_open_pct", "abn_vol_shrink"]
    for ex in ("S1_hold1c", "S7_lianban"):
        vw = cm.make_clean_view(df, ex, base_oq & amt3, 0.0030)
        if len(vw) >= 50:
            wfr = wf.run_wf_scorecard_new_strategy(
                vw, feature_cols=f_oq, v20_ctx=v20_ctx, wf_start_date="2023-01-03", end_date=END_DT,
                min_warmup_trades=25, min_warmup_trades_rare=20, min_warmup_months=15, recalc_freq="daily",
                top_k=5, min_k=3, max_corr=0.65, min_t_stat=0.8, shrink_tau=20.0, fee_rt=0.0030,
                gross_ret_col="gross_ret", thresholds=("top30", "top20", 65), eval_v20_patch=False, perm_n=30,
            )
            scd = wfr["scored_df"]
            for th in ("top30", "top20", "abs_65"):
                tc = {"top30": "wf_thr_top30", "top20": "wf_thr_top20"}.get(th, 65.0)
                ps, sl = wfm.select_single_slot_trades(scd, score_col="wf_score", threshold=tc, wf_only=True)
                ev = cm.eval_slice_exact(sl, ps, scd[scd["wf_in_window"]], bench_df, "mtm_json_use", 0.0030, "2023-01-03", END_DT, wins_yr[1:2] + wins_yr[4:], perm_n=200)
                wfw = ev["windows"]["WF_2326"]
                oq_wf_rows.append({"exit": ex, "thr": th, "n": wfw["n"], "wr": wfw["wr_pct"], "nav_wf": wfw["nav"], "ex5_wf": wfw["ex_top5_nav"], "nav_23": ev["windows"].get("Y2023", {}).get("nav", 1.0), "p_any": ev["permutation"]["any_cand_day_p_nav"]})

    return {"details": det_out, "plateau": plat, "openqual_wf": oq_wf_rows}


def _staggered_port_nav(sub_df: pd.DataFrame, cal_dts: list[str], H: int, start_dt: str, end_dt: str) -> dict:
    """True daily staggered 1/H equal-weight cohort portfolio (zero calendar-phase bias)."""
    s = sub_df[sub_df["buy_date"].between(start_dt, end_dt)]
    if s.empty:
        return {"n_days": 0, "nav": 1.0, "ex5_day_nav": 1.0}
    day_r = s.groupby("buy_date")["net_ret"].mean().to_dict()
    dts_w = [d for d in cal_dts if start_dt <= d <= end_dt]
    # Approximate daily staggered return: mean over active cohorts (each day deploys 1/H capital, earns ~ net_ret / H on entry or exact cohort average)
    # Better: exact discrete daily MTM across H staggered slots!
    slots = [[] for _ in range(H)]
    for i, d in enumerate(dts_w):
        if d in day_r:
            slots[i % H].append((d, day_r[d]))
    # Even cleaner: run all H phase offsets separately and report median/mean NAV & ex5!
    navs, ex5s = [], []
    for ph in range(H):
        sel_r = []
        cur_ed = ""
        for d in dts_w[ph:]:
            if cur_ed and d <= cur_ed:
                continue
            g = s[s["buy_date"] == d]
            if not g.empty:
                sel_r.append(float(g["net_ret"].mean()))
                cur_ed = str(g["exit_date"].max())
        if sel_r:
            arr = np.asarray(sel_r)
            navs.append(float(np.prod(1.0 + arr)))
            sr = np.sort(arr)
            ex5s.append(float(np.prod(1.0 + sr[:-5])) if len(arr) > 5 else 1.0)
    return {"H": H, "n_cohorts": len(day_r), "phase_mean_nav": round(float(np.mean(navs)), 4) if navs else 1.0,
            "phase_min_nav": round(float(np.min(navs)), 4) if navs else 1.0,
            "phase_max_nav": round(float(np.max(navs)), 4) if navs else 1.0,
            "phase_mean_ex5": round(float(np.mean(ex5s)), 4) if ex5s else 1.0}


def run_track2_forensics(v20_ctx: dict) -> dict:
    ev_df = pd.read_parquet(f"{RD045_DIR}/track2_bse_events_pit.parquet")
    rot_df = pd.read_parquet(f"{RD045_DIR}/track2_bse_rot_panel_pit.parquet")
    bench_df = v20_ctx["bench"]
    cal_dts = bench_df[bench_df["trade_date"].between("2024-09-24", END_DT)].sort_values("trade_date")["trade_date"].tolist()

    # 1. All-phase staggered test + baseline BSE liquid benchmark in EX_OCT24 (2024-11-01 ~ 2026-11-25)
    rot_ex = cm.make_clean_view(rot_df, "S3_hold3c", (rot_df["bj_amt_yi_t1"] >= 0.50).to_numpy(), 0.0030)
    rot_ex_1y = cm.make_clean_view(rot_df, "S3_hold3c", (rot_df["bj_amt_yi_t1"] >= 1.00).to_numpy(), 0.0030)
    # Test Contrarian / Pullback / Volume-Surge low-DOF ranking in B2_C (opposite of chasing!)
    rot_df["z_contrarian"] = (
        (1.0 - rot_df.groupby("buy_date")["bj_ret_5d_t1"].rank(pct=True).fillna(0.5))
        + rot_df.groupby("buy_date")["bj_amt_trend_5v20"].rank(pct=True).fillna(0.5)
        + rot_df["bj_above_ma10_t1"].to_numpy(float) * 0.5
        + rot_df.groupby("buy_date")["bj_clv_t1"].rank(pct=True).fillna(0.5)
    )
    b2c_tests = []
    for l_nm, l_thr in (("5kw", 0.50), ("1yi", 1.00)):
        for ex, H in (("S3_hold3c", 3), ("S4_hold5c", 5), ("S_ma5_trail10", 5)):
            vw = cm.make_clean_view(rot_df, ex, (rot_df["bj_amt_yi_t1"] >= l_thr).to_numpy(), 0.0030)
            st_all = _staggered_port_nav(vw, cal_dts, H, "2024-11-01", END_DT)
            top3 = vw.sort_values(["buy_date", "z_contrarian", "bj_amt_yi_t1"], ascending=[True, False, False]).groupby("buy_date").head(3)
            st_con3 = _staggered_port_nav(top3, cal_dts, H, "2024-11-01", END_DT)
            _, sl1 = wfm.select_single_slot_trades(vw, score_col="z_contrarian", threshold=None, wf_only=False)
            ev_con1 = cm.eval_slice_exact(sl1, vw, vw, bench_df, "mtm_json_use", 0.0030, "2024-11-01", END_DT, [("EX_OCT24", "2024-11-01", END_DT), ("Y2526", "2025-01-01", END_DT)], perm_n=50)
            b2c_tests.append({
                "liq": l_nm, "exit": ex, "all_liq_ew_phase_mean": st_all["phase_mean_nav"],
                "contrarian_top3_phase_mean": st_con3["phase_mean_nav"], "contrarian_top3_ex5": st_con3["phase_mean_ex5"],
                "contrarian_top1_nav": ev_con1["windows"]["EX_OCT24"]["nav"], "contrarian_top1_ex5": ev_con1["windows"]["EX_OCT24"]["ex_top5_nav"],
            })

    # 2. B2_A Seesaw Plateau & Trade Anatomy
    mb_supp = ((ev_df["L1_max_board_t1"] <= 4) | (ev_df["L1_duanban_damian_t1"] >= 20) | (ev_df["L1_zb_rate_t1"] >= 35) | (ev_df["mkt_notices_sev_abn_5d_t1"] >= 3) | ((ev_df["L1_max_board_t2"] >= 5) & (ev_df["L1_max_board_t1"] < ev_df["L1_max_board_t2"])))
    b2a_plat = []
    for sh_thr in (1.10, 1.20, 1.35):
        for r_lo, r_hi in ((10.0, 25.0), (12.0, 25.0), (15.0, 28.0)):
            for amt_thr in (0.50, 1.00):
                msk = mb_supp & (ev_df["bj_amt_share_ratio20_t1"] >= sh_thr) & (ev_df["bj_mkt_surge15_cnt_t1"] >= 4) & ev_df["bj_ret_1d_t1"].between(r_lo, r_hi) & (ev_df["bj_clv_t1"] >= 0.60) & (ev_df["bj_amt_yi_t1"] >= amt_thr)
                for ex in ("S3_hold3c", "S4_hold5c", "S_ma5_trail10"):
                    vw = cm.make_clean_view(ev_df, ex, msk.to_numpy(), 0.0030)
                    if len(vw) < 8:
                        continue
                    ps, sl = wfm.select_single_slot_trades(vw, score_col="bj_amt_yi_t1", threshold=None, wf_only=False)
                    ev = cm.eval_slice_exact(sl, ps, vw, bench_df, "mtm_json_use", 0.0030, "2024-09-24", END_DT, [("POST924", "2024-09-24", END_DT), ("EX_OCT24", "2024-11-01", END_DT)], perm_n=50)
                    b2a_plat.append({"sh_thr": sh_thr, "ret_rng": f"{r_lo}-{r_hi}", "amt": amt_thr, "exit": ex,
                                     "n_p924": ev["windows"]["POST924"]["n"], "nav_p924": ev["windows"]["POST924"]["nav"], "ex5_p924": ev["windows"]["POST924"]["ex_top5_nav"],
                                     "n_exoct": ev["windows"]["EX_OCT24"]["n"], "nav_exoct": ev["windows"]["EX_OCT24"]["nav"], "ex5_exoct": ev["windows"]["EX_OCT24"]["ex_top5_nav"]})

    return {"b2c_contrarian_and_stagger": b2c_tests, "b2a_plateau": b2a_plat}


def main():
    t0 = time.time()
    v20_ctx = wf.load_v20_reference_context(BASE_DIR)
    t1_f = run_track1_forensics(v20_ctx)
    t2_f = run_track2_forensics(v20_ctx)
    with open(f"{RD045_DIR}/rd045_forensics.json", "w", encoding="utf-8") as f:
        json.dump({"t1": t1_f, "t2": t2_f}, f, ensure_ascii=False, indent=2)

    print("=== T1 OpenQual_G1_ThmUp_S7 Years ===")
    for k, v in t1_f["details"]["OpenQual_G1_ThmUp_S7"]["windows_30bps"].items():
        print(f"  {k:9s}: n={v.get('n',0):2d} wr={v.get('wr_pct',0):5.1f}% nav={v.get('nav',1):6.3f} ex5={v.get('ex_top5_nav',1):6.3f} csi={v.get('csi300_pct',0):+6.1f}%")
    print("  80bps WF:", t1_f["details"]["OpenQual_G1_ThmUp_S7"]["wf_80bps"]["nav"], "ex5:", t1_f["details"]["OpenQual_G1_ThmUp_S7"]["wf_80bps"]["ex_top5_nav"])
    print("  TOP6:", t1_f["details"]["OpenQual_G1_ThmUp_S7"]["top6"])

    print("\n=== T1 V2C_ThmUp_Qual_S7 Years ===")
    for k, v in t1_f["details"]["V2C_ThmUp_Qual_S7"]["windows_30bps"].items():
        print(f"  {k:9s}: n={v.get('n',0):2d} wr={v.get('wr_pct',0):5.1f}% nav={v.get('nav',1):6.3f} ex5={v.get('ex_top5_nav',1):6.3f} csi={v.get('csi300_pct',0):+6.1f}%")
    print("  80bps WF:", t1_f["details"]["V2C_ThmUp_Qual_S7"]["wf_80bps"]["nav"], "ex5:", t1_f["details"]["V2C_ThmUp_Qual_S7"]["wf_80bps"]["ex_top5_nav"])
    print("  TOP6:", t1_f["details"]["V2C_ThmUp_Qual_S7"]["top6"])
    print("  BOT5:", t1_f["details"]["V2C_ThmUp_Qual_S7"]["bot5"])

    print("\n=== T1 Plateau (S7_lianban & S1_hold1c) ===")
    print(pd.DataFrame(t1_f["plateau"]).sort_values("ex5_wf", ascending=False).head(12).to_string(index=False))

    print("\n=== T1 OpenQual Inside WF ===")
    print(pd.DataFrame(t1_f["openqual_wf"]).to_string(index=False))

    print("\n=== T2 B2_C Contrarian & All-Phase Staggered (EX_OCT24) ===")
    print(pd.DataFrame(t2_f["b2c_contrarian_and_stagger"]).to_string(index=False))

    print("\n=== T2 B2_A Plateau ===")
    print(pd.DataFrame(t2_f["b2a_plateau"]).sort_values("ex5_exoct", ascending=False).head(10).to_string(index=False))
    print(f"[Step3 DONE in {time.time()-t0:.1f}s]")


if __name__ == "__main__":
    main()

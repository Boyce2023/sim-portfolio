#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD045 Step 2B: Evaluate Track 2 BSE 30cm V2 (B2_A Seesaw, B2_B Trend, B2_C Low-DOF Rotation + WF)."""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"
import json, resource, sys, time
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
BSE_WINS = [
    ("POST924", "2024-09-24", END_DT),
    ("EX_OCT24", "2024-11-01", END_DT),
    ("Y2025_2026", "2025-01-01", END_DT),
    ("Y2026", "2026-01-01", END_DT),
    ("Y2026_H2", "2026-07-01", END_DT),
]


from typing import Optional

def _pack_row(sec: str, name: str, ex: str, ev30: dict, ev50: dict, ev80: dict, bask3: Optional[dict] = None, v20c: Optional[dict] = None, extra: Optional[dict] = None) -> dict:
    p9 = ev30["windows"].get("POST924", {})
    eo = ev30["windows"].get("EX_OCT24", {})
    y25 = ev30["windows"].get("Y2025_2026", {})
    y26 = ev30["windows"].get("Y2026", {})
    row = {
        "section": sec, "track": name, "exit_rule": ex,
        "n_p924": p9.get("n", 0), "wr_p924": p9.get("wr_pct", 0.0), "plr_p924": p9.get("plr", 0.0),
        "nav_p924": p9.get("nav", 1.0), "ex5_p924": p9.get("ex_top5_nav", 1.0),
        "eq_p924": p9.get("eq_nav", 1.0), "mdd_p924": p9.get("daily_mdd_pct", 0.0),
        "sharpe_p924": p9.get("daily_sharpe", 0.0), "excess_csi_p924": p9.get("excess_csi300_pp", 0.0),
        "mtm_diff": ev30.get("mtm_reconciliation_diff", 0.0),
        "nav_50": ev50["windows"].get("POST924", {}).get("nav", 1.0),
        "nav_80": ev80["windows"].get("POST924", {}).get("nav", 1.0),
        "n_exoct": eo.get("n", 0), "nav_exoct": eo.get("nav", 1.0), "ex5_exoct": eo.get("ex_top5_nav", 1.0),
        "sharpe_exoct": eo.get("daily_sharpe", 0.0), "excess_csi_exoct": eo.get("excess_csi300_pp", 0.0),
        "nav_exoct_80": ev80["windows"].get("EX_OCT24", {}).get("nav", 1.0),
        "n_2526": y25.get("n", 0), "nav_2526": y25.get("nav", 1.0), "ex5_2526": y25.get("ex_top5_nav", 1.0),
        "nav_y26": y26.get("nav", 1.0), "perm_any_p": ev30.get("permutation", {}).get("any_cand_day_p_nav", 1.0),
    }
    if bask3:
        bp = bask3["windows"].get("POST924", {})
        be = bask3["windows"].get("EX_OCT24", {})
        row.update({"top3_nav_p924": bp.get("nav", 1.0), "top3_ex5_p924": bp.get("ex_top5_nav", 1.0),
                    "top3_nav_exoct": be.get("nav", 1.0), "top3_ex5_exoct": be.get("ex_top5_nav", 1.0),
                    "top3_mtm_diff": bask3.get("mtm_reconciliation_diff", 0.0)})
    if v20c and v20c.get("patch_m1"):
        m1, m2 = v20c["patch_m1"], v20c["patch_m2"]
        row.update({"corr_v20": v20c["corr_all_days"], "v20_delta_ratio": m1.get("delta_nav_ratio_full_wf"),
                    "v20_delta_sharpe": m1.get("delta_sharpe_full_wf"),
                    "emp_nav": m2["windows"]["FULL_WF"].get("nav"), "emp_ex5": m2["windows"]["FULL_WF"].get("ex_top5_nav")})
    if extra:
        row.update(extra)
    return row


def _eval_view(sec: str, name: str, ex: str, view: pd.DataFrame, cand_pool: pd.DataFrame, v20_ctx: dict,
               score_col: str = "bj_amt_yi_t1", thresh=None, wf_only: bool = False, do_top3: bool = True, perm_n: int = 200) -> dict:
    bench_df = v20_ctx["bench"]
    pass_df, slot_df = wfm.select_single_slot_trades(view, score_col=score_col, threshold=thresh, tie_col="bj_amt_yi_t1", wf_only=wf_only)
    if slot_df.empty:
        return {}
    ev30 = cm.eval_slice_exact(slot_df, pass_df, cand_pool, bench_df, "mtm_json_use", 0.0030, "2024-09-24", END_DT, BSE_WINS, perm_n=perm_n)
    ev50 = cm.eval_slice_exact(slot_df.assign(net_ret=(1.0 + slot_df["gross_ret"]) * (1.0 - 0.0050) - 1.0), pass_df, cand_pool, bench_df, "mtm_json_use", 0.0050, "2024-09-24", END_DT, BSE_WINS[:3], perm_n=20)
    ev80 = cm.eval_slice_exact(slot_df.assign(net_ret=(1.0 + slot_df["gross_ret"]) * (1.0 - 0.0080) - 1.0), pass_df, cand_pool, bench_df, "mtm_json_use", 0.0080, "2024-09-24", END_DT, BSE_WINS[:3], perm_n=20)
    bask3 = None
    if do_top3:
        b3 = bh.select_topk_basket_trades(view, score_col=score_col, k=3, threshold=thresh, wf_only=wf_only)
        bask3 = bh.eval_baskets_exact(b3, bench_df, 0.0030, "2024-09-24", END_DT, BSE_WINS[:3])
    v20c = cm.compute_v20_corr_and_patch(pass_df, slot_df, v20_ctx, "mtm_json_use", 0.0030, "2024-09-24", "2026-11-16", score_col=score_col)
    return _pack_row(sec, name, ex, ev30, ev50, ev80, bask3, v20c)


def main():
    t0 = time.time()
    ev_df = pd.read_parquet(f"{RD045_DIR}/track2_bse_events_pit.parquet")
    rot_df = pd.read_parquet(f"{RD045_DIR}/track2_bse_rot_panel_pit.parquet")
    v20_ctx = wf.load_v20_reference_context(BASE_DIR)
    bench_df = v20_ctx["bench"]
    rows = []

    # --- 1. B2_A & B2_B Rule Grid ---
    amt5kw = ev_df["bj_amt_yi_t1"] >= 0.50
    amt1yi = ev_df["bj_amt_yi_t1"] >= 1.00
    mb_supp = (
        (ev_df["L1_max_board_t1"] <= 4) | (ev_df["L1_duanban_damian_t1"] >= 20)
        | (ev_df["L1_zb_rate_t1"] >= 35) | (ev_df["mkt_notices_sev_abn_5d_t1"] >= 3)
        | ((ev_df["L1_max_board_t2"] >= 5) & (ev_df["L1_max_board_t1"] < ev_df["L1_max_board_t2"]))
    )
    bj_inflow = (ev_df["bj_amt_share_ratio20_t1"] >= 1.20) & ((ev_df["bj_mkt_zt30_cnt_t1"] >= 2) | (ev_df["bj_mkt_surge15_cnt_t1"] >= 4))
    seesaw = mb_supp & bj_inflow
    zt30 = ev_df["bj_is_zt30_t1"] == 1
    yang12 = ev_df["bj_ret_1d_t1"].between(12.0, 25.0) & (ev_df["bj_vr5_t1"] >= 1.5) & (ev_df["bj_clv_t1"] >= 0.65)
    div63 = ev_df["open_pct"].between(-6.0, 3.0)
    div84 = ev_df["open_pct"].between(-8.0, 4.0)
    pb_ma5 = ev_df["bj_days_since_s15"].between(1, 5) & (ev_df["bj_above_ma5_t1"] == 1) & ev_df["bj_dist_ma5_pct_t1"].between(-0.5, 6.0) & ev_df["open_pct"].between(-5.0, 3.0)

    specs = [
        ("B2_A_Seesaw", "B2_A1_ZT30_div_5kw", seesaw & zt30 & div84 & amt5kw),
        ("B2_A_Seesaw", "B2_A1_ZT30_div_1yi", seesaw & zt30 & div84 & amt1yi),
        ("B2_A_Seesaw", "B2_A2_Yang12_brk_5kw", seesaw & yang12 & amt5kw),
        ("B2_A_Seesaw", "B2_A2_Yang12_brk_1yi", seesaw & yang12 & amt1yi),
        ("B2_A_Seesaw", "B2_A3_Active12_5kw", seesaw & (ev_df["bj_ret_1d_t1"] >= 12.0) & amt5kw),
        ("B2_B_Trend", "B2_B1_ZT30_div63_5kw", zt30 & div63 & amt5kw),
        ("B2_B_Trend", "B2_B1_ZT30_div63_1yi", zt30 & div63 & amt1yi),
        ("B2_B_Trend", "B2_B2_Surge15_div63_5kw", (ev_df["bj_ret_1d_t1"] >= 15.0) & div63 & amt5kw),
        ("B2_B_Trend", "B2_B2_Surge15_div63_1yi", (ev_df["bj_ret_1d_t1"] >= 15.0) & div63 & amt1yi),
        ("B2_B_Trend", "B2_B3_MA5_pullback_5kw", pb_ma5 & amt5kw),
        ("B2_B_Trend", "B2_B3_MA5_pullback_1yi", pb_ma5 & amt1yi),
    ]
    for sec, nm, msk in specs:
        for ex in ("S1_hold1c", "S3_hold3c", "S4_hold5c", "S_ma5_trail10", "S_ma10_trail15", "S_stop8_ma5"):
            v = cm.make_clean_view(ev_df, ex, msk.to_numpy(bool), 0.0030)
            cp = cm.make_clean_view(ev_df, ex, amt5kw.to_numpy(bool), 0.0030)
            r = _eval_view(sec, nm, ex, v, cp, v20_ctx, perm_n=200)
            if r:
                rows.append(r)

    # --- 2. B2_C Low-DOF 5-Factor Rotation (Zero-Fit Equal-Rank + Expanding WF + 2025-12-31 Trunc) ---
    f5 = ["bj_amt_trend_5v20", "bj_ret_5d_t1", "bj_ret_10d_t1", "bj_dist_hi_60_t1", "bj_clv_t1"]
    rot_df["z_comp"] = 0.0
    for c in f5:
        rot_df["z_comp"] += rot_df.groupby("buy_date")[c].rank(pct=True).fillna(0.5)
    for l_nm, l_thr in (("5kw", 0.50), ("1yi", 1.00)):
        msk_r = (rot_df["bj_amt_yi_t1"] >= l_thr).to_numpy(bool)
        for ex in ("S3_hold3c", "S4_hold5c", "S_ma5_trail10", "S_ma10_trail15"):
            vr = cm.make_clean_view(rot_df, ex, msk_r, 0.0030)
            r = _eval_view("B2_C_ZeroFit", f"B2_C_ZeroFit_{l_nm}", ex, vr, vr, v20_ctx, score_col="z_comp", perm_n=200)
            if r:
                rows.append(r)
            # Expanding WF strictly on the 5 low-DOF factors (warmup >= 25 trades, start 2025-01-02)
            wf_res = wf.run_wf_scorecard_new_strategy(
                vr, feature_cols=f5, v20_ctx=v20_ctx, wf_start_date="2025-01-02", end_date=END_DT,
                min_warmup_trades=25, min_warmup_trades_rare=20, min_warmup_months=3, recalc_freq="daily",
                top_k=5, min_k=3, max_corr=0.75, min_t_stat=0.5, shrink_tau=20.0, fee_rt=0.0030,
                gross_ret_col="gross_ret", thresholds=("top20", "top10", 70), eval_v20_patch=False, perm_n=30,
            )
            sc_df = wf_res["scored_df"]
            tr_chk = None
            if ex in ("S3_hold3c", "S_ma5_trail10"):
                tr_chk = wf.verify_truncation_zero_leakage(
                    vr, f5, mode="A", cutoff="2025-12-31", score_threshold="top20", v20_ctx=v20_ctx,
                    wf_start_date="2025-01-02", end_date=END_DT, min_warmup_trades=25, min_warmup_trades_rare=20,
                    min_warmup_months=3, recalc_freq="daily", top_k=5, min_k=3, max_corr=0.75, min_t_stat=0.5,
                    shrink_tau=20.0, fee_rt=0.0030, gross_ret_col="gross_ret",
                )
            for th in ("top20", "top10", "abs_70"):
                tcol = {"top20": "wf_thr_top20", "top10": "wf_thr_top10"}.get(th, 70.0)
                r_wf = _eval_view("B2_C_WF", f"B2_C_WF_{l_nm}_{th}", ex, sc_df, sc_df[sc_df["wf_in_window"]], v20_ctx,
                                  score_col="wf_score", thresh=tcol, wf_only=True, perm_n=200)
                if r_wf:
                    r_wf["trunc_20251231_pass"] = tr_chk["zero_leakage_pass"] if tr_chk else None
                    rows.append(r_wf)

    res_df = pd.DataFrame(rows)
    res_df.to_csv(f"{RD045_DIR}/rd045_track2_bse_grid.csv", index=False, encoding="utf-8-sig")
    print(f"[Step2B DONE {time.time()-t0:.1f}s | RSS={round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1048576,1)}MB] rows={len(res_df)}")
    if not res_df.empty:
        cols = ["section", "track", "exit_rule", "n_p924", "nav_p924", "ex5_p924", "n_exoct", "nav_exoct", "ex5_exoct", "nav_2526", "nav_80", "top3_nav_exoct", "v20_delta_ratio"]
        print(res_df.sort_values("ex5_exoct", ascending=False)[[c for c in cols if c in res_df.columns]].head(18).to_string(index=False))


if __name__ == "__main__":
    main()

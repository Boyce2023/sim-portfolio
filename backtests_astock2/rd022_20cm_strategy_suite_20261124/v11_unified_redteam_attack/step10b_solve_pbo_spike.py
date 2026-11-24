#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Step 10b: Identify which factor(s) cause the >=83 IS spike / OOS drop & check CSCV across clean orthogonal variants."""
import itertools, os, pickle, sys
import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
BASE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
V1_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v1_deepopen_scorecard_exit"
PART2_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/part2_native_strategies"
OUT_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v11_unified_redteam_attack"
sys.path.insert(0, V1_DIR); sys.path.insert(0, PART2_DIR); sys.path.insert(0, OUT_DIR)

from backtest_utils import _sim_k_slots
from step3_oos_and_tables import FINAL_EXIT_CFG
from step2_audit_exits_and_beta import sim_deepopen_strict_exec
from step7_is_refine_card_and_pbo import build_refined_cards
from step3_diagnose_pbo_and_prune import cscv_detail, build_daily_mat


def full_cscv_suite(tr_c: pd.DataFrame, thr_A: float, all_dts: list) -> dict:
    t_days = [d for d in sorted(all_dts) if "2021-01-04" <= d <= "2026-11-23"]
    day_idx = {d: i for i, d in enumerate(t_days)}
    R_w = build_daily_mat(tr_c, [70, 72, 74, 76, 78, 80, 82], all_dts)
    loc = [int(thr_A + d) for d in (-4, -2, 0, 2, 4)]
    R_l = build_daily_mat(tr_c, loc, all_dts)
    sc_sub = tr_c[tr_c["score"] >= thr_A]["score"]
    cols = []
    q_lbls = ["base"] + [f"q{v}" for v in range(1, 14)]
    for v in range(14):
        qv = thr_A if v == 0 else float(np.quantile(sc_sub, 0.05 + (v / 14.0) * 0.40))
        s1, _, _ = _sim_k_slots(tr_c[tr_c["score"] >= qv], 1)
        arr = np.zeros(len(t_days))
        for r in s1.itertuples(index=False):
            i = day_idx.get(str(r.exit_date))
            if i is not None: arr[i] += float(r.net_ret_eval)
        cols.append(arr)
    Rq = np.column_stack(cols)
    return {
        "wide_S8": cscv_detail(R_w, [70,72,74,76,78,80,82], 8)["pbo_pct"],
        "wide_S10": cscv_detail(R_w, [70,72,74,76,78,80,82], 10)["pbo_pct"],
        "loc_S8": cscv_detail(R_l, loc, 8)["pbo_pct"],
        "loc_S10": cscv_detail(R_l, loc, 10)["pbo_pct"],
        "q14_S8": cscv_detail(Rq, q_lbls, 8)["pbo_pct"],
        "q14_S10": cscv_detail(Rq, q_lbls, 10)["pbo_pct"],
        "loc_win": cscv_detail(R_l, loc, 10)["winners"],
    }


def main():
    aux = pickle.load(open(f"{PART2_DIR}/cache_20cm_aux.pkl", "rb"))
    all_dts = aux["all_dts"]
    df = pd.read_parquet(f"{V1_DIR}/p1_clean_candidates.parquet")
    pool = df[df["f1_o_pct"].between(-0.10, -0.030) & (df["mkt20_zt_cnt"] < 16)].copy().reset_index(drop=True)
    deep_cfg = {**FINAL_EXIT_CFG, "zt_imm": False}
    tr_base = sim_deepopen_strict_exec(pool, deep_cfg, fee=0.0030, tp_buf=0.0030)

    # Check variations of 9-10 clean factors (with/without rfm<=20, with/without zt_late, cap positive sum or use negative-heavy risk filter + core positives!)
    # Insight: Why did >=82 beat >=80 in IS only? Let's test dropping ONE positive factor from V11_10_late_rfm and check CSCV!
    _, fm_base = build_refined_cards(pool)["V11_10_late_rfm"]

    tests = [
        ("Full_10_late_rfm (th76)", fm_base, 76),
        ("Full_10_late_rfm (th78)", fm_base, 78),
        ("Drop_rfm_le20 (9item, th76)", fm_base.drop(columns=["F10_rfm_le20_pos"]), 76),
        ("Drop_rfm_le20 (9item, th78)", fm_base.drop(columns=["F10_rfm_le20_pos"]), 78),
        ("Drop_zt_late (9item, th76)", fm_base.drop(columns=["F11_zt_late_ge1400"]), 76),
        ("Drop_zt_late (9item, th78)", fm_base.drop(columns=["F11_zt_late_ge1400"]), 78),
        ("Drop_zt60d (9item, th76)", fm_base.drop(columns=["F04_zt60d_ge2"]), 76),
        ("Drop_dist3d30 (9item, th76)", fm_base.drop(columns=["F03_dist3d30_ge10"]), 76),
        ("Drop_inst (9item, th76)", fm_base.drop(columns=["F06_inst_net_pos"]), 76),
    ]
    # Also test: what if we cap bonus stacking or shift weights so good scores plateau around 78..84 instead of spiking at 84?
    # Test: Core 10 factors where 6 penalties/risk filters (-10/-8/-5) + 4 broad positives (zt60d+4, mkt10+6/+3, inst+4, rfm20+3, zt_late+3, dist+3, open+4) -> NO single narrow spike!
    # Wait: test a risk-filter-centric card: Base=80! Penalties do the heavy lifting, core alpha adds +3/+4/+5!
    f_risk = pd.DataFrame(index=pool.index)
    f_risk["F01_open_gap"] = np.where(pool["f1_o_pct"] < -0.080, -12, np.where(pool["f1_o_pct"].between(-0.070, -0.030), 3, 0))
    f_risk["F02_dist3d30_ge10"] = np.where(pool["dist_3d30"].fillna(0.0) >= 0.10, 3, 0)
    f_risk["F03_zt60d_ge2"] = np.where(pool["zt_cnt_60d"].fillna(0) >= 2, 4, 0)
    f_risk["F04_zt_late_ge1400"] = np.where((pool["zt_hhmm"] >= 1400) & (pool["zt_hhmm"] < 9999), 3, 0)
    f_risk["F05_seal_ratio_ge10_pen"] = np.where(pool["zt_seal_ratio"].fillna(0.0) >= 0.10, -6, 0)
    f_risk["F06_inst_net_pos"] = np.where(pool["lhb_inst_net"].fillna(0.0) > 0.0, 4, 0)
    f_risk["F07_mkt10_zt_gt55"] = np.where(pool["mkt10_zt_cnt"].fillna(0) > 70, 6, np.where(pool["mkt10_zt_cnt"].fillna(0) > 55, 3, 0))
    f_risk["F08_yizi20_siphon_pen"] = np.where(pool["f1_mkt20_0925_zt"].fillna(0) >= 1, -6, 0)
    f_risk["F09_monday_pen"] = np.where(pool["f1_weekday"] == 0, -9, 0)
    f_risk["F10_rfm_le20_pos"] = np.where(pool["real_free_mcap"].fillna(999.0) <= 20.0, 3, 0)
    tests.append(("RiskBal_10 (th76)", f_risk, 76))
    tests.append(("RiskBal_10 (th77)", f_risk, 77))

    # Also test: what if we keep ONLY 8-10 factors that work in BOTH IS & OOS with gentler weights AND add `lhb_lh_net_pos` (+4)?
    f_lh = f_risk.copy()
    f_lh["F11_lhasa_panic_pos"] = np.where(pool["lhb_lh_net_pos"].fillna(0) == 1, 4, 0)
    tests.append(("RiskBal_11_lh (th76)", f_lh, 76))
    tests.append(("RiskBal_11_lh (th77)", f_lh, 77))

    for nm, fm, thr in tests:
        sc = 70.0 + fm.sum(axis=1).to_numpy()
        sc_map = dict(zip(zip(pool["dt"], pool["c6"]), sc))
        tc = tr_base.copy()
        tc["score"] = [sc_map[(r.sig_date, r.c6)] for r in tc.itertuples(index=False)]
        sf, nf, mf = _sim_k_slots(tc[tc["score"] >= thr], 1)
        _, ni, _ = _sim_k_slots(tc[(tc["score"] >= thr) & (tc["buy_date"] <= "2024-08-31")], 1)
        _, no, mo = _sim_k_slots(tc[(tc["score"] >= thr) & (tc["buy_date"] >= "2024-09-01")], 1)
        _, n25, _ = _sim_k_slots(tc[(tc["score"] >= thr) & (tc["buy_date"].str[:4] == "2025")], 1)
        _, n26, _ = _sim_k_slots(tc[(tc["score"] >= thr) & (tc["buy_date"].str[:4] == "2026")], 1)
        pb = full_cscv_suite(tc, thr, all_dts)
        print(f"{nm:28s} | N={len(sf):3d} FULL={nf:6.1f}x MDD={mf*100:4.1f}% IS={ni:5.1f}x OOS={no:5.2f}x(m={mo*100:4.1f}%) 25={n25:4.2f}x 26={n26:4.2f}x | "
              f"PBO w8/10={pb['wide_S8']:4.1f}/{pb['wide_S10']:4.1f}% loc={pb['loc_S8']:4.1f}/{pb['loc_S10']:4.1f}% q14={pb['q14_S8']:4.1f}/{pb['q14_S10']:4.1f}%")


if __name__ == "__main__":
    main()

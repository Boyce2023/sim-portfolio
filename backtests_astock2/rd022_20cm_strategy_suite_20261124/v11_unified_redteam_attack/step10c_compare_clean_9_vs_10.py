#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Step 10c: Compare 4 drift-free orthogonal V1.1 scorecard candidates (Zero-Mcap vs Bias20 vs Causal-Rolling-Median-Mcap vs Fixed-20B-NoLate)."""
import os, pickle, sys
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
from step10b_solve_pbo_spike import full_cscv_suite
from step3_diagnose_pbo_and_prune import cscv_detail, build_daily_mat


def main():
    aux = pickle.load(open(f"{PART2_DIR}/cache_20cm_aux.pkl", "rb"))
    all_dts = aux["all_dts"]
    is_dts = [d for d in sorted(all_dts) if "2021-01-04" <= d <= "2024-08-31"]
    df = pd.read_parquet(f"{V1_DIR}/p1_clean_candidates.parquet")

    # Compute strictly causal rolling-252-trading-day median of real_free_mcap on clean 20cm first-board pool (strictly < dt!)
    df_sorted = df.sort_values("dt").reset_index(drop=True)
    dt_med = df_sorted.groupby("dt")["real_free_mcap"].median().sort_index()
    # Rolling past 120 active signal days shifted by 1 so strictly < T0!
    roll_med = dt_med.rolling(80, min_periods=10).median().shift(1).fillna(16.0).to_dict()

    pool = df[df["f1_o_pct"].between(-0.10, -0.030) & (df["mkt20_zt_cnt"] < 16)].copy().reset_index(drop=True)
    pool["rfm_roll_med"] = pool["dt"].map(roll_med).fillna(16.0)
    deep_cfg = {**FINAL_EXIT_CFG, "zt_imm": False}
    tr_base = sim_deepopen_strict_exec(pool, deep_cfg, fee=0.0030, tp_buf=0.0030)

    def make_9base():
        f = pd.DataFrame(index=pool.index)
        f["F01_open_gap"] = np.where(pool["f1_o_pct"] < -0.080, -10, np.where(pool["f1_o_pct"].between(-0.070, -0.030), 4, 0))
        f["F02_dist3d30_ge10"] = np.where(pool["dist_3d30"].fillna(0.0) >= 0.10, 4, 0)
        f["F03_zt60d_ge2"] = np.where(pool["zt_cnt_60d"].fillna(0) >= 2, 5, 0)
        f["F04_zt_late_ge1400"] = np.where((pool["zt_hhmm"] >= 1400) & (pool["zt_hhmm"] < 9999), 4, 0)
        f["F05_seal_ratio_ge10_pen"] = np.where(pool["zt_seal_ratio"].fillna(0.0) >= 0.10, -5, 0)
        f["F06_inst_net_pos"] = np.where(pool["lhb_inst_net"].fillna(0.0) > 0.0, 5, 0)
        f["F07_mkt10_zt_gt55"] = np.where(pool["mkt10_zt_cnt"].fillna(0) > 70, 7, np.where(pool["mkt10_zt_cnt"].fillna(0) > 55, 4, 0))
        f["F08_yizi20_siphon_pen"] = np.where(pool["f1_mkt20_0925_zt"].fillna(0) >= 1, -5, 0)
        f["F09_monday_pen"] = np.where(pool["f1_weekday"] == 0, -8, 0)
        return f

    f1 = make_9base()
    f2 = make_9base(); f2["F10_bias20_le20"] = np.where(pool["bias20"].fillna(1.0) <= 0.20, 4, 0)
    f3 = make_9base(); f3["F10_rfm_le_rollmed"] = np.where(pool["real_free_mcap"].fillna(999.0) <= pool["rfm_roll_med"], 4, 0)
    f4 = make_9base().drop(columns=["F04_zt_late_ge1400"]); f4["F10_rfm_le20"] = np.where(pool["real_free_mcap"].fillna(999.0) <= 20.0, 4, 0)
    # Cand5: Cand1 + rfm <= 1.2 * roll_med
    f5 = make_9base(); f5["F10_rfm_le_12roll"] = np.where(pool["real_free_mcap"].fillna(999.0) <= pool["rfm_roll_med"] * 1.2, 4, 0)

    cands = [
        ("Cand1_Pure9_NoMcap", f1, [74, 76, 78, 80, 82]),
        ("Cand2_10_Bias20", f2, [74, 76, 78, 80, 82, 84]),
        ("Cand3_10_RollMed", f3, [74, 76, 78, 80, 82, 84]),
        ("Cand4_9_Rfm20_NoLate", f4, [74, 76, 78, 80, 82, 84]),
        ("Cand5_10_Roll12Med", f5, [74, 76, 78, 80, 82, 84]),
    ]

    for cnm, fm, ths in cands:
        sc = 70.0 + fm.sum(axis=1).to_numpy()
        sc_map = dict(zip(zip(pool["dt"], pool["c6"]), sc))
        tc = tr_base.copy()
        tc["score"] = [sc_map[(r.sig_date, r.c6)] for r in tc.itertuples(index=False)]
        tr_is = tc[tc["buy_date"] <= "2024-08-31"]
        is_p = cscv_detail(build_daily_mat(tr_is, [70, 72, 74, 76, 78, 80], is_dts), [70,72,74,76,78,80], 8)["pbo_pct"]
        print(f"\n=== {cnm} ({fm.shape[1]} items) | IS_PBO(70..80)={is_p}% ===")
        for th in ths:
            sf, nf, mf = _sim_k_slots(tc[tc["score"] >= th], 1)
            _, ni, mi = _sim_k_slots(tc[(tc["score"] >= th) & (tc["buy_date"] <= "2024-08-31")], 1)
            _, no, mo = _sim_k_slots(tc[(tc["score"] >= th) & (tc["buy_date"] >= "2024-09-01")], 1)
            s25, n25, _ = _sim_k_slots(tc[(tc["score"] >= th) & (tc["buy_date"].str[:4] == "2025")], 1)
            s26, n26, _ = _sim_k_slots(tc[(tc["score"] >= th) & (tc["buy_date"].str[:4] == "2026")], 1)
            pb = full_cscv_suite(tc, th, all_dts)
            print(f"  th>={th:2d} | N={len(sf):3d}(25={len(s25):2d},26={len(s26):2d}) FULL={nf:5.1f}x MDD={mf*100:4.1f}% | IS={ni:5.1f}x(m={mi*100:4.1f}%) OOS={no:5.2f}x(m={mo*100:4.1f}%) 25={n25:4.2f}x 26={n26:4.2f}x | "
                  f"PBO w={pb['wide_S8']:4.1f}/{pb['wide_S10']:4.1f}% l={pb['loc_S8']:4.1f}/{pb['loc_S10']:4.1f}% q={pb['q14_S8']:4.1f}/{pb['q14_S10']:4.1f}%")


if __name__ == "__main__":
    main()

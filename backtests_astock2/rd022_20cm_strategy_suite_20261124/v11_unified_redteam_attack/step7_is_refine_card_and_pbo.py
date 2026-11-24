#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Step 7: Refine 10-item orthogonal DeepOpen V1.1 on IS & check PBO (wide/local/q14), OOS, 2025, 2026 under +0.30% TP buffer."""
import os, pickle, sys
import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
BASE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
V1_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v1_deepopen_scorecard_exit"
PART2_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/part2_native_strategies"
OUT_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v11_unified_redteam_attack"
sys.path.insert(0, V1_DIR)
sys.path.insert(0, PART2_DIR)
sys.path.insert(0, OUT_DIR)

from backtest_utils import _sim_k_slots
from step3_oos_and_tables import FINAL_EXIT_CFG
from step2_audit_exits_and_beta import sim_deepopen_strict_exec
from step3_diagnose_pbo_and_prune import cscv_detail, build_daily_mat


def build_refined_cards(d: pd.DataFrame) -> dict:
    cards = {}
    # Base 9-item core (cleanest weights)
    def base_df():
        f = pd.DataFrame(index=d.index)
        f["F01_open_gap"] = np.where(d["f1_o_pct"] < -0.080, -10, np.where(d["f1_o_pct"].between(-0.070, -0.030), 4, 0))
        f["F02_bias20_le20"] = np.where(d["bias20"].fillna(1.0) <= 0.20, 4, 0)
        f["F03_dist3d30_ge10"] = np.where(d["dist_3d30"].fillna(0.0) >= 0.10, 4, 0)
        f["F04_zt60d_ge2"] = np.where(d["zt_cnt_60d"].fillna(0) >= 2, 5, 0)
        f["F05_seal_ratio_ge10_pen"] = np.where(d["zt_seal_ratio"].fillna(0.0) >= 0.10, -5, 0)
        f["F06_inst_net_pos"] = np.where(d["lhb_inst_net"].fillna(0.0) > 0.0, 5, 0)
        f["F07_mkt10_zt_gt55"] = np.where(d["mkt10_zt_cnt"].fillna(0) > 70, 7, np.where(d["mkt10_zt_cnt"].fillna(0) > 55, 4, 0))
        f["F08_yizi20_siphon_pen"] = np.where(d["f1_mkt20_0925_zt"].fillna(0) >= 1, -5, 0)
        f["F09_monday_pen"] = np.where(d["f1_weekday"] == 0, -8, 0)
        return f

    # V11_10_rfm: Base 9 + rfm <= 20B (+4)
    f1 = base_df()
    f1["F10_rfm_le20_pos"] = np.where(d["real_free_mcap"].fillna(999.0) <= 20.0, 4, 0)
    cards["V11_10_rfm"] = (70.0 + f1.sum(axis=1).to_numpy(), f1)

    # V11_10_rfm_ztlate: Replace bias20<=20 with zt_hhmm>=1400? Or keep all 11? Test both!
    f2 = f1.copy()
    f2["F11_zt_late_ge1400"] = np.where((d["zt_hhmm"] >= 1400) & (d["zt_hhmm"] < 9999), 4, 0)
    cards["V11_11_rfm_late"] = (70.0 + f2.sum(axis=1).to_numpy(), f2)

    # V11_10_nolock_late: Base 9 (drop bias20) + rfm<=20 + zt_late>=1400 (10 items)
    f3 = f2.drop(columns=["F02_bias20_le20"]).copy()
    cards["V11_10_late_rfm"] = (70.0 + f3.sum(axis=1).to_numpy(), f3)

    # V11_11_quant: V11_10_rfm + quant_noinst (-4)
    f4 = f1.copy()
    f4["F11_quant_noinst_pen"] = np.where((d["lhb_quant"].fillna(0) >= 1) & (d["lhb_inst_net"].fillna(0.0) <= 0.0), -4, 0)
    cards["V11_11_rfm_quant"] = (70.0 + f4.sum(axis=1).to_numpy(), f4)

    # V11_10_CapPeak: Keep CardB weights, test if slightly gentler mkt10 (+6/+3) & open (+3/-10) makes plateau flatter!
    f5 = pd.DataFrame(index=d.index)
    f5["F01_open_gap"] = np.where(d["f1_o_pct"] < -0.080, -10, np.where(d["f1_o_pct"].between(-0.070, -0.030), 3, 0))
    f5["F02_rfm_le20_pos"] = np.where(d["real_free_mcap"].fillna(999.0) <= 20.0, 4, 0)
    f5["F03_bias20_le20"] = np.where(d["bias20"].fillna(1.0) <= 0.20, 4, 0)
    f5["F04_dist3d30_ge10"] = np.where(d["dist_3d30"].fillna(0.0) >= 0.10, 4, 0)
    f5["F05_zt60d_ge2"] = np.where(d["zt_cnt_60d"].fillna(0) >= 2, 5, 0)
    f5["F06_seal_ratio_ge10_pen"] = np.where(d["zt_seal_ratio"].fillna(0.0) >= 0.10, -5, 0)
    f5["F07_inst_net_pos"] = np.where(d["lhb_inst_net"].fillna(0.0) > 0.0, 5, 0)
    f5["F08_mkt10_zt_gt55"] = np.where(d["mkt10_zt_cnt"].fillna(0) > 70, 6, np.where(d["mkt10_zt_cnt"].fillna(0) > 55, 3, 0))
    f5["F09_yizi20_siphon_pen"] = np.where(d["f1_mkt20_0925_zt"].fillna(0) >= 1, -5, 0)
    f5["F10_monday_pen"] = np.where(d["f1_weekday"] == 0, -8, 0)
    cards["V11_10_Flat"] = (70.0 + f5.sum(axis=1).to_numpy(), f5)

    return cards


def main():
    aux = pickle.load(open(f"{PART2_DIR}/cache_20cm_aux.pkl", "rb"))
    all_dts = aux["all_dts"]
    is_dts = [d for d in sorted(all_dts) if "2021-01-04" <= d <= "2024-08-31"]
    df = pd.read_parquet(f"{V1_DIR}/p1_clean_candidates.parquet")
    pool = df[df["f1_o_pct"].between(-0.10, -0.030) & (df["mkt20_zt_cnt"] < 16)].copy().reset_index(drop=True)
    tr_base = sim_deepopen_strict_exec(pool, FINAL_EXIT_CFG, fee=0.0030, tp_buf=0.0030)

    cards = build_refined_cards(pool)
    for cname, (sc, fm) in cards.items():
        sc_map = dict(zip(zip(pool["dt"], pool["c6"]), sc))
        tr_c = tr_base.copy()
        tr_c["score"] = [sc_map[(r.sig_date, r.c6)] for r in tr_c.itertuples(index=False)]

        # IS-only CSCV (68..82)
        tr_is = tr_c[tr_c["buy_date"] <= "2024-08-31"]
        is_pbo = cscv_detail(build_daily_mat(tr_is, [68, 70, 72, 74, 76, 78, 80, 82], is_dts), [68, 70, 72, 74, 76, 78, 80, 82], 8)
        # Full CSCV on A-tier neighborhood (72..82) and wide (68..82) and wide (70..84)
        f_pbo_72_82_s8 = cscv_detail(build_daily_mat(tr_c, [72, 74, 76, 78, 80, 82], all_dts), [72, 74, 76, 78, 80, 82], 8)
        f_pbo_72_82_s10 = cscv_detail(build_daily_mat(tr_c, [72, 74, 76, 78, 80, 82], all_dts), [72, 74, 76, 78, 80, 82], 10)
        f_pbo_wide_s8 = cscv_detail(build_daily_mat(tr_c, [68, 70, 72, 74, 76, 78, 80, 82], all_dts), [68, 70, 72, 74, 76, 78, 80, 82], 8)
        f_pbo_wide_s10 = cscv_detail(build_daily_mat(tr_c, [68, 70, 72, 74, 76, 78, 80, 82], all_dts), [68, 70, 72, 74, 76, 78, 80, 82], 10)
        # Local around 78 (74..82)
        f_pbo_loc_s8 = cscv_detail(build_daily_mat(tr_c, [74, 75, 76, 77, 78, 79, 80, 81, 82], all_dts), [74, 75, 76, 77, 78, 79, 80, 81, 82], 8)

        print(f"\n=== {cname} ({fm.shape[1]} items) ===")
        print(f"  IS_PBO(68..82)={is_pbo['pbo_pct']}% | FULL_72_82(S8/S10)={f_pbo_72_82_s8['pbo_pct']}%/{f_pbo_72_82_s10['pbo_pct']}% | FULL_68_82(S8/S10)={f_pbo_wide_s8['pbo_pct']}%/{f_pbo_wide_s10['pbo_pct']}% | LOC_74_82(S8)={f_pbo_loc_s8['pbo_pct']}%")
        for th in [74, 76, 78, 80, 82, 84]:
            sf, nvf, mddf = _sim_k_slots(tr_c[tr_c["score"] >= th], 1)
            si, nvi, _ = _sim_k_slots(tr_c[(tr_c["score"] >= th) & (tr_c["buy_date"] <= "2024-08-31")], 1)
            so, nvo, mddo = _sim_k_slots(tr_c[(tr_c["score"] >= th) & (tr_c["buy_date"] >= "2024-09-01")], 1)
            s25, nv25, _ = _sim_k_slots(tr_c[(tr_c["score"] >= th) & (tr_c["buy_date"].str[:4] == "2025")], 1)
            s26, nv26, _ = _sim_k_slots(tr_c[(tr_c["score"] >= th) & (tr_c["buy_date"].str[:4] == "2026")], 1)
            print(f"  th>={th:2d} | N={len(sf):3d}(IS={len(si):3d},OOS={len(so):2d},25={len(s25):2d},26={len(s26):2d}) | FULL={nvf:6.2f}x MDD={mddf*100:4.1f}% | IS={nvi:6.2f}x | OOS={nvo:5.2f}x(mdd={mddo*100:4.1f}%) | 25={nv25:4.2f}x 26={nv26:4.2f}x")


if __name__ == "__main__":
    main()

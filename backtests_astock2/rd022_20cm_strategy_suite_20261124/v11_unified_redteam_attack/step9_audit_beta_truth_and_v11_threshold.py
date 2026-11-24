#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Step 9: Dissect Beta displacement vs alpha (IS/924/OOS_ex924) & compare DeepOpen V1.1 A=78 vs A=80 across all CSCV/robustness checks."""
import os, pickle, sys
import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
BASE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
V1_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v1_deepopen_scorecard_exit"
B1_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v1_beta_scorecard_exit"
PART2_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/part2_native_strategies"
OUT_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v11_unified_redteam_attack"
sys.path.insert(0, V1_DIR); sys.path.insert(0, B1_DIR); sys.path.insert(0, PART2_DIR); sys.path.insert(0, OUT_DIR)

from step3_oos_and_tables import FINAL_EXIT_CFG
from step2_audit_exits_and_beta import sim_deepopen_strict_exec
from step7_is_refine_card_and_pbo import build_refined_cards
from step8a_deepopen_v11_exit_and_loo import sim_beta_strict_buf
from step8b_4arch_pk import sim_portfolio_k_slots, build_beta_df
from step3_diagnose_pbo_and_prune import cscv_detail, build_daily_mat


def main():
    aux = pickle.load(open(f"{PART2_DIR}/cache_20cm_aux.pkl", "rb"))
    all_dts = aux["all_dts"]
    df = pd.read_parquet(f"{V1_DIR}/p1_clean_candidates.parquet")
    pool = df[df["f1_o_pct"].between(-0.10, -0.030) & (df["mkt20_zt_cnt"] < 16)].copy().reset_index(drop=True)
    cards = build_refined_cards(pool)
    sc, fm = cards["V11_10_late_rfm"]
    sc_map = dict(zip(zip(pool["dt"], pool["c6"]), sc))
    deep_cfg = {**FINAL_EXIT_CFG, "zt_imm": False}
    tr_deep = sim_deepopen_strict_exec(pool, deep_cfg, fee=0.0030, tp_buf=0.0030)
    tr_deep["score"] = [sc_map[(r.sig_date, r.c6)] for r in tr_deep.itertuples(index=False)]
    tr_deep["track"] = "DEEP"

    # 1. Check Beta V1.0 & Pruned Beta V1.1 pure standalone net contribution in Arch3a / Arch3c / Arch4c (OOS_ex924 & 2026!)
    b_sig = pd.read_csv(f"{B1_DIR}/all_scored_signals_beta_v1.csv")
    b_sig["c6"] = b_sig["c6"].astype(str).str.zfill(6)
    # Also compute honest 5-factor pruned Beta V1.1 score (no 15-item IS noise)
    og1 = b_sig["t1_open_gap"].fillna(0.0).to_numpy()
    p20 = b_sig["pos20_pre"].fillna(0.5).to_numpy()
    dm60 = b_sig["dist_ma60_pre"].fillna(0.0).to_numpy()
    rfm = b_sig["real_free_mcap"].fillna(b_sig["circ_mcap"] * 0.6).to_numpy()
    cm = b_sig["circ_mcap"].fillna(50.0).to_numpy()
    rto = b_sig["real_to"].fillna(15.0).to_numpy()
    b_sig["score_honest"] = (
        50
        + np.where(og1 < -0.025, -14, np.where(og1 > 0.040, -6, np.where((og1 >= -0.012) & (og1 <= 0.018), 5, 0)))
        + np.where(p20 <= 0.25, 10, np.where(p20 <= 0.42, 5, np.where(p20 > 0.65, -8, 0)))
        + np.where(dm60 <= -0.15, 12, np.where(dm60 <= 0.0, 6, np.where(dm60 > 0.10, -8, 0)))
        + np.where((cm >= 150.0) | (rfm >= 80.0), -10, np.where(rfm <= 25.0, 10, np.where(rfm <= 45.0, 4, 0)))
        + np.where(rto > 28.0, -8, np.where((rto >= 6.0) & (rto <= 22.0), 5, 0))
    )
    b_honest = b_sig[b_sig["score_honest"] >= 80].sort_values(["dt", "score_honest", "circ_mcap", "c6"], ascending=[True, False, True, True]).groupby("dt", sort=False).head(3)

    pk = pickle.load(open(f"{B1_DIR}/v1_stock_paths.pkl", "rb"))
    paths, dt_to_gidx = pk["paths"], pk["dt_to_gidx"]
    cols_u = ["sig_date", "buy_date", "exit_date", "c6", "score", "net_ret", "track"]
    d80 = tr_deep[tr_deep["score"] >= 80.0][cols_u].copy()

    print("=== BETA DISPLACEMENT & HONEST-BETA CHECK (DeepOpen >= 80, 1-SLOT & 3-SLOT) ===")
    for nm, b_sub, ex_r, emp in [
        ("BetaV1_TP10T3", b_sig[b_sig["pass_A"]], "GRID_TP10_SL07_T3", False),
        ("BetaV1_FixT2", b_sig[b_sig["pass_A"]], "FIX_T2", False),
        ("BetaV1_EmptyS", b_sig[b_sig["pass_S"]], "DYN_YANG_TP15_T5", True),
        ("BetaHonest5_T5", b_honest, "DYN_YANG_TP15_T5", False),
        ("BetaHonest5_TP10T3", b_honest, "GRID_TP10_SL07_T3", False),
        ("BetaHonest5_FixT2", b_honest, "FIX_T2", False),
        ("BetaHonest5_EmptyT2", b_honest, "FIX_T2", True),
    ]:
        bdf = build_beta_df(b_sub, paths, dt_to_gidx, ex_r)
        cmb = pd.concat([d80, bdf[cols_u]], ignore_index=True)
        for ks in [1, 3]:
            r_pure = sim_portfolio_k_slots(d80, ks, True, False)
            r_cmb = sim_portfolio_k_slots(cmb, ks, True, emp)
            r_is = sim_portfolio_k_slots(cmb[cmb["buy_date"] <= "2024-08-31"], ks, True, emp)
            r_ox = sim_portfolio_k_slots(cmb[(cmb["buy_date"] >= "2024-09-01") & (~cmb["sig_date"].between("2024-09-24", "2024-10-08"))], ks, True, emp)
            r_26 = sim_portfolio_k_slots(cmb[cmb["buy_date"].str[:4] == "2026"], ks, True, emp)
            pure_ox = sim_portfolio_k_slots(d80[d80["buy_date"] >= "2024-09-01"], ks, True, False)["nav"]
            pure_26 = sim_portfolio_k_slots(d80[d80["buy_date"].str[:4] == "2026"], ks, True, False)["nav"]
            # Check Beta-only standalone returns inside executed cmb!
            bt = r_cmb["tdf"][r_cmb["tdf"]["track"] == "BETA"]
            bt_ox = bt[(bt["buy_date"] >= "2024-09-01") & (~bt["sig_date"].between("2024-09-24", "2024-10-08"))]
            bt_26 = bt[bt["buy_date"].str[:4] == "2026"]
            print(f"  {ks}s {nm:20s} | IS={r_is['nav']:5.2f}x | OOSx={r_ox['nav']:5.2f}x(vsPure {pure_ox:5.2f}x) | Y26={r_26['nav']:4.2f}x(vsPure {pure_26:4.2f}x) | "
                  f"ExecB={len(bt):3d}(OOSx n={len(bt_ox):2d},mn={bt_ox['net_ret'].mean()*100 if len(bt_ox) else 0:+4.2f}%,Y26 n={len(bt_26):2d},mn={bt_26['net_ret'].mean()*100 if len(bt_26) else 0:+4.2f}%)")

    # 2. Check V11_10_late_rfm threshold A=78 vs A=80 CSCV (local, wide, q14) & S-tier 2025 counts
    print("\n=== DEEPOPEN V1.1 (V11_10_late_rfm) CSCV & S-TIER CHECK ===")
    for th_a in [76, 78, 80]:
        loc = [th_a - 4, th_a - 2, th_a, th_a + 2, th_a + 4]
        loc1 = list(range(th_a - 4, th_a + 5))
        R_loc2 = build_daily_mat(tr_deep, loc, all_dts)
        R_loc1 = build_daily_mat(tr_deep, loc1, all_dts)
        R_w6 = build_daily_mat(tr_deep, [72, 74, 76, 78, 80, 82], all_dts)
        p_l2_8 = cscv_detail(R_loc2, loc, 8); p_l2_10 = cscv_detail(R_loc2, loc, 10)
        p_l1_8 = cscv_detail(R_loc1, loc1, 8); p_l1_10 = cscv_detail(R_loc1, loc1, 10)
        print(f"  A>={th_a}: loc_step2(S8/S10)={p_l2_8['pbo_pct']}%/{p_l2_10['pbo_pct']}% win={p_l2_10['winners']} | "
              f"loc_step1(S8/S10)={p_l1_8['pbo_pct']}%/{p_l1_10['pbo_pct']}%")
    for th_s in [82, 83, 84, 85, 86]:
        sub_s = tr_deep[tr_deep["score"] >= th_s]
        s_f = sim_portfolio_k_slots(sub_s[cols_u], 1)
        s_i = sim_portfolio_k_slots(sub_s[sub_s["buy_date"] <= "2024-08-31"][cols_u], 1)
        s_o = sim_portfolio_k_slots(sub_s[sub_s["buy_date"] >= "2024-09-01"][cols_u], 1)
        s_25 = sim_portfolio_k_slots(sub_s[sub_s["buy_date"].str[:4] == "2025"][cols_u], 1)
        s_26 = sim_portfolio_k_slots(sub_s[sub_s["buy_date"].str[:4] == "2026"][cols_u], 1)
        print(f"  S>={th_s}: N={s_f['n']:3d} WR={s_f['wr']}% FULL={s_f['nav']:6.2f}x MDD={s_f['mdd']:4.1f}% | IS={s_i['nav']:5.2f}x | OOS={s_o['nav']:4.2f}x | 25(n={s_25['n']:2d})={s_25['nav']:4.2f}x | 26(n={s_26['n']:2d})={s_26['nav']:4.2f}x")


if __name__ == "__main__":
    main()

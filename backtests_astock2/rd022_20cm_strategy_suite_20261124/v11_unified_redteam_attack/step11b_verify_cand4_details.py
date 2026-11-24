#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Quick verification of Cand4_9_Rfm20_76: S-tier (82 vs 83 vs 84), Arch1-4 PK at A=76, risk_mode triggers, and ex-div/deferral trades."""
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

from backtest_utils import _sim_k_slots
from step3_oos_and_tables import FINAL_EXIT_CFG
from step2_audit_exits_and_beta import sim_deepopen_strict_exec
from step8b_4arch_pk import window_summary, build_beta_df


def score_cand4(d: pd.DataFrame) -> tuple[np.ndarray, pd.DataFrame]:
    f = pd.DataFrame(index=d.index)
    f["F01_open_gap"] = np.where(d["f1_o_pct"] < -0.080, -10, np.where(d["f1_o_pct"].between(-0.070, -0.030), 4, 0))
    f["F02_rfm_le20"] = np.where(d["real_free_mcap"].fillna(999.0) <= 20.0, 4, 0)
    f["F03_dist3d30_ge10"] = np.where(d["dist_3d30"].fillna(0.0) >= 0.10, 4, 0)
    f["F04_zt60d_ge2"] = np.where(d["zt_cnt_60d"].fillna(0) >= 2, 5, 0)
    f["F05_seal_ratio_ge10_pen"] = np.where(d["zt_seal_ratio"].fillna(0.0) >= 0.10, -5, 0)
    f["F06_inst_net_pos"] = np.where(d["lhb_inst_net"].fillna(0.0) > 0.0, 5, 0)
    f["F07_mkt10_zt_gt55"] = np.where(d["mkt10_zt_cnt"].fillna(0) > 70, 7, np.where(d["mkt10_zt_cnt"].fillna(0) > 55, 4, 0))
    f["F08_yizi20_siphon_pen"] = np.where(d["f1_mkt20_0925_zt"].fillna(0) >= 1, -5, 0)
    f["F09_monday_pen"] = np.where(d["f1_weekday"] == 0, -8, 0)
    return 70.0 + f.sum(axis=1).to_numpy(), f


def main():
    df = pd.read_parquet(f"{V1_DIR}/p1_clean_candidates.parquet")
    pool = df[df["f1_o_pct"].between(-0.10, -0.030) & (df["mkt20_zt_cnt"] < 16)].copy().reset_index(drop=True)
    sc, _ = score_cand4(pool)
    sc_map = dict(zip(zip(pool["dt"], pool["c6"]), sc))
    deep_cfg = {**FINAL_EXIT_CFG, "zt_imm": False}
    tr = sim_deepopen_strict_exec(pool, deep_cfg, fee=0.0030, tp_buf=0.0030)
    tr["score"] = [sc_map[(r.sig_date, r.c6)] for r in tr.itertuples(index=False)]
    tr["track"] = "DEEP"

    # 1. Exit tree ablation at A>=76
    print("=== EXIT TREE ABLATION ON CAND4 (A>=76, +0.30% TP BUFFER) ===")
    for nm, cfg in [
        ("V11_Tree_NoZTImm", deep_cfg),
        ("NoB2D3_OnlyD2TP12", {**deep_cfg, "b2_mode": "d2_tp"}),
        ("NoRisk_Switch", {**deep_cfg, "risk_mode": "none"}),
        ("PureT2_Close", {"b3_tp_mode": "none", "b2_mode": "d2_close", "zt_imm": False, "risk_mode": "none"}),
    ]:
        tx = sim_deepopen_strict_exec(pool, cfg, fee=0.0030, tp_buf=0.0030)
        tx["score"] = [sc_map[(r.sig_date, r.c6)] for r in tx.itertuples(index=False)]
        sub = tx[tx["score"] >= 76.0]
        s1, nf, mf = _sim_k_slots(sub, 1)
        _, ni, _ = _sim_k_slots(sub[sub["buy_date"] <= "2024-08-31"], 1)
        _, no, _ = _sim_k_slots(sub[sub["buy_date"] >= "2024-09-01"], 1)
        _, n26, _ = _sim_k_slots(sub[sub["buy_date"].str[:4] == "2026"], 1)
        print(f"  {nm:20s} | N={len(s1):3d} FULL={nf:5.1f}x MDD={mf*100:4.1f}% | IS={ni:5.1f}x | OOS={no:5.2f}x | 2026={n26:4.2f}x")

    # 2. S-tier check
    print("\n=== CAND4 S-TIER CANDIDATES (80..85) ===")
    for ths in [80, 82, 83, 84, 85]:
        sub = tr[tr["score"] >= ths]
        s1, nf, mf = _sim_k_slots(sub, 1)
        _, ni, _ = _sim_k_slots(sub[sub["buy_date"] <= "2024-08-31"], 1)
        _, no, _ = _sim_k_slots(sub[sub["buy_date"] >= "2024-09-01"], 1)
        s25, n25, _ = _sim_k_slots(sub[sub["buy_date"].str[:4] == "2025"], 1)
        s26, n26, _ = _sim_k_slots(sub[sub["buy_date"].str[:4] == "2026"], 1)
        print(f"  S>={ths}: N={len(s1):3d} WR={(s1['net_ret_eval']>0).mean()*100:4.1f}% FULL={nf:5.1f}x MDD={mf*100:4.1f}% | IS={ni:5.1f}x | OOS={no:4.2f}x | 25(n={len(s25):2d})={n25:4.2f}x | 26(n={len(s26):2d})={n26:4.2f}x")

    # 3. Arch 1-4 PK specifically for Cand4 A>=76!
    b_sig = pd.read_csv(f"{B1_DIR}/all_scored_signals_beta_v1.csv")
    b_sig["c6"] = b_sig["c6"].astype(str).str.zfill(6)
    pk = pickle.load(open(f"{B1_DIR}/v1_stock_paths.pkl", "rb"))
    paths, dt_to_gidx = pk["paths"], pk["dt_to_gidx"]
    b_A_T5 = build_beta_df(b_sig[b_sig["pass_A"]], paths, dt_to_gidx, "DYN_YANG_TP15_T5")
    b_A_T3 = build_beta_df(b_sig[b_sig["pass_A"]], paths, dt_to_gidx, "GRID_TP10_SL07_T3")
    b_A_F2 = build_beta_df(b_sig[b_sig["pass_A"]], paths, dt_to_gidx, "FIX_T2")
    b_S_T5 = build_beta_df(b_sig[b_sig["pass_S"]], paths, dt_to_gidx, "DYN_YANG_TP15_T5")
    b_m_T5 = build_beta_df(b_sig[b_sig["pass_A"] & (b_sig["mkt_prev5d_ew"] >= -0.02)], paths, dt_to_gidx, "DYN_YANG_TP15_T5")
    cols_u = ["sig_date", "buy_date", "exit_date", "c6", "score", "net_ret", "track"]
    d76 = tr[tr["score"] >= 76.0][cols_u].copy()

    archs = [
        ("Arch1_PureDeep_76", d76, True, False),
        ("Arch2_UniFull_T5", pd.concat([d76, b_A_T5[cols_u]], ignore_index=True), True, False),
        ("Arch3a_FastBeta_TP10T3", pd.concat([d76, b_A_T3[cols_u]], ignore_index=True), True, False),
        ("Arch3b_FastBeta_FixT2", pd.concat([d76, b_A_F2[cols_u]], ignore_index=True), True, False),
        ("Arch4a_PriEmpty_BetaA", pd.concat([d76, b_A_T5[cols_u]], ignore_index=True), True, True),
        ("Arch4b_PriEmpty_BetaS", pd.concat([d76, b_S_T5[cols_u]], ignore_index=True), True, True),
        ("Arch4c_PriEmpty_MktPos", pd.concat([d76, b_m_T5[cols_u]], ignore_index=True), True, True),
    ]
    print("\n=== 4-ARCHITECTURE PK AT CAND4 A>=76 (+0.30% TP BUFFER) ===")
    pk_rows = []
    for ks in [1, 2, 3]:
        print(f"  [{ks}-SLOT]")
        for aname, adf, pri, emp in archs:
            w = window_summary(adf, ks, pri, emp)
            f, i, o, ox, y5, y6 = w["FULL"], w["IS"], w["OOS"], w["OOSx"], w["Y25"], w["Y26"]
            bt = f["tdf"][f["tdf"]["track"] == "BETA"]
            bt_ox = bt[(bt["buy_date"] >= "2024-09-01") & (~bt["sig_date"].between("2024-09-24", "2024-10-08"))]
            print(f"    {aname:23s} | N={f['n']:3d}(D={f['n_deep']:3d},B={f['n_beta']:2d}) | FULL={f['nav']:5.1f}x MDD={f['mdd']:4.1f}% Cal={f['calmar']:4.2f} cap10m={f['cap10m']:5.1f}x | "
                  f"IS={i['nav']:5.1f}x | OOS={o['nav']:5.2f}x OOSx={ox['nav']:5.2f}x | 25={y5['nav']:4.2f}x 26={y6['nav']:4.2f}x | B_OOSx_mn={bt_ox['net_ret'].mean()*100 if len(bt_ox) else 0:+4.2f}%")
            pk_rows.append({
                "deep_th": 76, "k_slots": ks, "arch": aname, "N": f["n"], "N_deep": f["n_deep"], "N_beta": f["n_beta"],
                "WR": f["wr"], "FULL_nav": f["nav"], "FULL_mdd": f["mdd"], "Calmar": f["calmar"], "cap10m": f["cap10m"],
                "IS_nav": i["nav"], "OOS_nav": o["nav"], "OOSx924_nav": ox["nav"], "Y25_nav": y5["nav"], "Y26_nav": y6["nav"],
                "Beta_OOSx924_mean_pct": round(bt_ox["net_ret"].mean() * 100, 2) if len(bt_ox) else 0.0,
            })
    pd.DataFrame(pk_rows).to_csv(f"{OUT_DIR}/arch_pk_v11_cand4_76.csv", index=False)


if __name__ == "__main__":
    main()

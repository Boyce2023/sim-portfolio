#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Step 4: Dissect 2025 rank inversion in V11_9item, scan drift-free orthogonal factors on IS, and build Beta V1.1."""
import os, pickle, sys
import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
BASE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
V1_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v1_deepopen_scorecard_exit"
B1_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v1_beta_scorecard_exit"
PART2_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/part2_native_strategies"
OUT_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v11_unified_redteam_attack"
sys.path.insert(0, V1_DIR)
sys.path.insert(0, B1_DIR)
sys.path.insert(0, PART2_DIR)
sys.path.insert(0, OUT_DIR)

from backtest_utils import _sim_k_slots
from step3_oos_and_tables import FINAL_EXIT_CFG
from step2_audit_exits_and_beta import sim_deepopen_strict_exec
from step3_diagnose_pbo_and_prune import compute_deepopen_v11
from v1_exit_engine import simulate_exit_v1, _sim_k_slots_v1


def main():
    df = pd.read_parquet(f"{V1_DIR}/p1_clean_candidates.parquet")
    pool = df[df["f1_o_pct"].between(-0.10, -0.030) & (df["mkt20_zt_cnt"] < 16)].copy().reset_index(drop=True)

    # Run strict +0.30% exec on full pool
    sc, fm = compute_deepopen_v11(pool, include_rfm_small=False, include_bias20=True)
    pool["score"] = sc
    tr = sim_deepopen_strict_exec(pool, FINAL_EXIT_CFG, fee=0.0030, tp_buf=0.0030)
    m = pool.merge(tr[["sig_date", "c6", "net_ret", "exit_reason"]], left_on=["dt", "c6"], right_on=["sig_date", "c6"], how="inner")
    m = pd.concat([m, fm.loc[m.index]], axis=1)

    # 1. Dissect 2025: why score 72..77 beat score >= 78!
    y25 = m[m["f1_dt"].str[:4] == "2025"].copy()
    print("=== 2025 SCORE BUCKETS (V11_9item + 0.30% buf) ===")
    for lbl, lo, hi in [("<70", -999, 69.9), ("70..77", 70, 77.9), (">=78", 78, 999)]:
        sub = y25[y25["score"].between(lo, hi)]
        s1, nv, _ = _sim_k_slots(tr[(tr["buy_date"].str[:4] == "2025") & (tr["score"].between(lo, hi))], 1)
        print(f"  {lbl:7s}: rawN={len(sub):2d} 1sN={len(s1):2d} raw_mn={sub['net_ret'].mean()*100:+5.2f}% 1s_nav={nv:.3f}x WR={(sub['net_ret']>0).mean()*100:5.1f}%")
    print("\n  [2025 Big Winners in score 70..77]:")
    w25 = y25[y25["score"].between(70, 77.9) & (y25["net_ret"] > 0.05)][["f1_dt", "c6", "name", "score", "net_ret", "F01_open_gap_zone", "F03_dist3d30_ge10", "F04_zt60d_ge2", "F05_seal_ratio_ge10_pen", "F06_inst_net_pos", "F07_mkt10_zt_gt70", "F08_yizi20_siphon_pen", "F09_monday_pen", "real_free_mcap"]]
    print(w25.to_string(index=False))

    # 2. Check ALL drift-free candidate features on IS vs OOS (NO scraper/Elo!)
    print("\n=== DRIFT-FREE CANDIDATE FEATURE CHECK (IS <=2024-08 vs OOS >=2024-09, raw pool strict+buf) ===")
    is_m = m["f1_dt"] <= "2024-08-31"
    oos_m = m["f1_dt"] >= "2024-09-01"
    is_b = m.loc[is_m, "net_ret"].mean() * 100
    oos_b = m.loc[oos_m, "net_ret"].mean() * 100
    feats = [
        ("open<-8.0%", m["f1_o_pct"] < -0.080),
        ("open[-6.5,-3.0]", m["f1_o_pct"].between(-0.065, -0.030)),
        ("open[-7.0,-3.0]", m["f1_o_pct"].between(-0.070, -0.030)),
        ("bias20<=12%", m["bias20"] <= 0.12),
        ("bias20<=20%", m["bias20"] <= 0.20),
        ("dist_3d30>=10%", m["dist_3d30"] >= 0.10),
        ("zt60d>=2", m["zt_cnt_60d"] >= 2),
        ("seal_ratio>=10%", m["zt_seal_ratio"] >= 0.10),
        ("zt_hhmm<=945", m["zt_hhmm"] <= 945),
        ("zt_hhmm>=1400", (m["zt_hhmm"] >= 1400) & (m["zt_hhmm"] < 9999)),
        ("inst_net>0", m["lhb_inst_net"] > 0),
        ("quant_noinst", (m["lhb_quant"] >= 1) & (m["lhb_inst_net"] <= 0)),
        ("lh_net_pos", m["lhb_lh_net_pos"] == 1),
        ("mkt10_zt>70", m["mkt10_zt_cnt"] > 70),
        ("mkt10_zt>55", m["mkt10_zt_cnt"] > 55),
        ("yizi20_0925>=1", m["f1_mkt20_0925_zt"] >= 1),
        ("monday", m["f1_weekday"] == 0),
        ("rfm<=20B", m["real_free_mcap"] <= 20.0),
        ("rfm<=25B", m["real_free_mcap"] <= 25.0),
        ("rfm>50B", m["real_free_mcap"] > 50.0),
        ("amt>=3e8", m["amount"] >= 3e8),
        ("turn>=15%", m["to"] >= 15.0),
        ("turn>=25%", m["to"] >= 25.0),
        ("prev_ret10<0", m["ac"] / m["ma20"] - 1 < 0),
        ("chinext300", m["is_chinext"] == 1),
        ("star688", m["is_chinext"] == 0),
    ]
    for nm, mk in feats:
        ri, ro = m.loc[is_m & mk, "net_ret"], m.loc[oos_m & mk, "net_ret"]
        print(f"  {nm:16s} | IS: N={len(ri):3d} WR={(ri>0).mean()*100:4.1f}% d={ri.mean()*100-is_b:+5.2f}% | "
              f"OOS: N={len(ro):3d} WR={(ro>0).mean()*100:4.1f}% d={ro.mean()*100-oos_b:+5.2f}%")

    # 3. Beta V1.1 Pruned check (only 5 drift-free core factors: Pos20, DistMA60, RealFreeMcap, RealTO, T1Open)
    # Tested with DYN_YANG_TP15_T5 vs GRID_TP10_SL07_T3 vs FIX_T3 vs +0.30% TP buffer!
    b_base = pd.read_parquet(f"{B1_DIR}/v1_beta_base_pool.parquet")
    b_hist = b_base[(b_base["dt"] <= "2026-11-20") & (b_base["buyable_B"])].copy().reset_index(drop=True)
    pk = pickle.load(open(f"{B1_DIR}/v1_stock_paths.pkl", "rb"))
    mkt = pd.read_parquet(f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/part1_beta_waves/market_daily.parquet")
    mkt_ew = dict(zip(mkt["dt"], mkt["ew_ret_all"]))
    paths, dt_to_gidx = pk["paths"], pk["dt_to_gidx"]

    # Pruned 6-item orthogonal Beta V1.1 (Base=50): Pos20, DistMA60, RealFreeMcap, RealTO, AntiOldDragon, T1Open
    og1 = b_hist["t1_open_gap"].fillna(0.0).to_numpy()
    p20 = b_hist["pos20_pre"].fillna(0.5).to_numpy()
    dm60 = b_hist["dist_ma60_pre"].fillna(0.0).to_numpy()
    rfm = b_hist["real_free_mcap"].fillna(b_hist["circ_mcap"] * 0.6).to_numpy()
    cm = b_hist["circ_mcap"].fillna(50.0).to_numpy()
    rto = b_hist["real_to"].fillna(b_hist["turn_pct"] / 0.6).to_numpy()
    b_sc = (
        50
        + np.where(og1 < -0.025, -14, np.where(og1 > 0.040, -6, np.where((og1 >= -0.012) & (og1 <= 0.018), 5, 0)))
        + np.where(p20 <= 0.25, 10, np.where(p20 <= 0.42, 5, np.where(p20 > 0.65, -8, 0)))
        + np.where(dm60 <= -0.15, 12, np.where(dm60 <= 0.0, 6, np.where(dm60 > 0.10, -8, 0)))
        + np.where((cm >= 150.0) | (rfm >= 80.0), -10, np.where(rfm <= 25.0, 10, np.where(rfm <= 45.0, 4, 0)))
        + np.where(rto > 28.0, -8, np.where((rto >= 6.0) & (rto <= 22.0), 5, 0))
    )
    b_hist["score_b11"] = b_sc
    print("\n=== PRUNED BETA V1.1 (5 ORTHOGONAL FACTORS) FAST vs T5 CHECK ===")
    for th in [75, 78, 80, 82, 85]:
        sel = b_hist[b_hist["score_b11"] >= th].sort_values(["dt", "score_b11", "circ_mcap", "c6"], ascending=[True, False, True, True]).groupby("dt", sort=False).head(3)
        for ex_r in ["FIX_T2", "FIX_T3", "GRID_TP10_SL07_T3", "DYN_YANG_TP15_T5"]:
            trows = []
            for r in sel.itertuples(index=False):
                res = simulate_exit_v1(paths, mkt_ew, r.c6, dt_to_gidx[r.dt], ex_r, float(r.mkt_prev5d_ew))
                if res:
                    trows.append({"signal_dt": r.dt, "buy_dt": res[0], "sell_dt": res[2], "c6": r.c6, "circ_mcap": r.circ_mcap, "score": r.score_b11, "net_ret": res[4]})
            tdf = pd.DataFrame(trows)
            _, n1_is, _, _ = _sim_k_slots_v1(tdf[tdf["buy_dt"] <= "2024-08-31"], 1)
            _, n1_oo, _, _ = _sim_k_slots_v1(tdf[tdf["buy_dt"] >= "2024-09-01"], 1)
            _, n1_ox, _, _ = _sim_k_slots_v1(tdf[(tdf["buy_dt"] >= "2024-09-01") & (~tdf["signal_dt"].between("2024-09-24", "2024-10-08"))], 1)
            _, n1_26, _, _ = _sim_k_slots_v1(tdf[tdf["buy_dt"] >= "2026-01-01"], 1)
            _, n3_ox, _, _ = _sim_k_slots_v1(tdf[(tdf["buy_dt"] >= "2024-09-01") & (~tdf["signal_dt"].between("2024-09-24", "2024-10-08"))], 3)
            _, n3_26, _, _ = _sim_k_slots_v1(tdf[tdf["buy_dt"] >= "2026-01-01"], 3)
            if ex_r in ("FIX_T3", "GRID_TP10_SL07_T3", "DYN_YANG_TP15_T5"):
                print(f"  th>={th} {ex_r:17s} | 1s: IS={n1_is:.2f}x OOS={n1_oo:.2f}x OOSx={n1_ox:.2f}x Y26={n1_26:.2f}x | 3s: OOSx={n3_ox:.2f}x Y26={n3_26:.2f}x")


if __name__ == "__main__":
    main()

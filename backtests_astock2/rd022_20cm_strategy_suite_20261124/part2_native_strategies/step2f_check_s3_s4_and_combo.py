#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Step 2f: Audit P1_S1 full D15 stats, test lean structural P2_S3 (prev_streak==1, open[-6%,0%], tiebreak -to), and test P1+P2 portfolio."""
import json, pickle
import numpy as np
import pandas as pd
from backtest_utils import calc_d15_suite, _sim_k_slots
from step2d_scorers import score_p1_s1, sim_exit_v2
from step2e_validate_final import monkey_pvalue, yearly_table

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd022_20cm_strategy_suite_20261124/part2_native_strategies"


def score_p2_s3_lean(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Lean P2_S3: strictly first-board broken true-yang, to<=30%, T+1 dip open [-6%, 0%], tiebreak -to."""
    skel = (
        df["tradable"] & (df["is_st_pit"] == 0) & (df["close"] >= 2.0)
        & (df["tox_90d"] == 0) & (df["reg_10d"] == 0)
        & (df["prev_streak"] == 1) & (~df["is_zt"]) & df["is_true_yang"] & (df["to"] <= 30.0)
        & df["f1_buyable"] & df["f1_o_pct"].between(-0.06, 0.0)
    )
    sc = np.full(len(df), 70.0)
    sc += np.where(df["pos60"] <= 0.50, 10.0, 0.0)
    sc += np.where(df["prev_pos20"] <= 0.45, 8.0, 0.0)
    sc += np.where(df["bias20"] <= 0.10, 6.0, 0.0)
    sc += np.where(df["lock_top10"].fillna(0) >= 45.0, 6.0, 0.0)
    sc += np.where(df["dist_3d30"] >= 0.10, 5.0, 0.0)
    sc += np.where(df["prev_zt_obc"] == 0, 4.0, 0.0)
    sc += np.where(df["real_to"] <= 25.0, 4.0, 0.0)
    mon = df["f1_dt"].astype(str).str.slice(5, 7)
    sc += np.where(mon.isin(["01", "04"]), -8.0, 0.0)
    sc += np.where(df["lhb_surf"] == 1, -6.0, 0.0)
    # Deterministic low-turnover tiebreak (smaller turnover = calmer washout)
    sc -= df["to"].fillna(20.0) * 0.05
    return skel, pd.Series(sc, index=df.index)


def print_full_d15(title: str, tr: pd.DataFrame, sh300: dict, ew20: dict, bg_rets: np.ndarray):
    m = calc_d15_suite(tr, sh300, ew20)
    t1, nav1, _ = _sim_k_slots(tr, 1)
    pv = monkey_pvalue(tr, bg_rets, len(t1), nav1)
    yt = yearly_table(tr)
    print(f"\n=== {title} (Monkey p={pv:.4f}) ===")
    for w in ("FULL", "IS", "OOS", "2026"):
        mw = m[w]
        print(f"  {w:4s} | raw={mw['raw_n']:3d} 1sN={mw['n_1s']:3d} WR={mw['wr_1s']:5.1f}% PO={mw['po_1s']:4.2f} "
              f"1s={mw['nav_1s']:6.2f}x MDD={mw['mdd_1s']:5.1f}% ex5={mw['ex5_1s']:5.2f}x f50={mw['fee50_1s']:5.2f}x | "
              f"3s={mw['nav_3s']:5.2f}x MDD3={mw['mdd_3s']:5.1f}% f50_3s={mw['fee50_3s']:5.2f}x | ew={mw['ew_nav']:6.2f}x | "
              f"exHS300={mw['ex_hs300_1s']:+7.1f}pp ex20EW={mw['ex_ew20_1s']:+7.1f}pp HLZ_t={mw['hlz_t']:5.2f}")
    print("  Yearly:", " | ".join(f"{y}:{v['nav_1s']}x(N={v['n_1s']},WR={v.get('wr_1s',0)}%,3s={v.get('nav_3s',1)}x)" for y, v in yt.items()))
    return m, yt, pv


def main():
    df = pd.read_parquet(f"{OUT_DIR}/cache_20cm_panel.parquet")
    g = df.groupby("c6", sort=False)
    df["prev_zt_obc"] = g["zt_obc"].shift(1).fillna(-1).astype(int)
    aux = pickle.load(open(f"{OUT_DIR}/cache_20cm_aux.pkl", "rb"))
    sh300, ew20 = aux["sh300"], aux["ew20_daily"]

    # 1. Print full D15 for P1_S1_DeepOpen (th75_T2_close and th75_T2_zt_tp10)
    sk1, sc1 = score_p1_s1(df)
    p1_pool = df[sk1].copy(); p1_pool["score"] = sc1[sk1].values
    bg1 = sim_exit_v2(p1_pool, "T2_zt_tp10")["net_ret"].to_numpy()
    tr1_c = sim_exit_v2(p1_pool[p1_pool["score"] >= 75.0], "T2_close")
    tr1_tp = sim_exit_v2(p1_pool[p1_pool["score"] >= 75.0], "T2_zt_tp10")
    m1_c, y1_c, pv1_c = print_full_d15("P1_S1_DeepOpen [th75_T2_close]", tr1_c, sh300, ew20, bg1)
    m1_tp, y1_tp, pv1_tp = print_full_d15("P1_S1_DeepOpen [th75_T2_zt_tp10]", tr1_tp, sh300, ew20, bg1)

    # 2. Test lean P2_S3
    sk2, sc2 = score_p2_s3_lean(df)
    p2_pool = df[sk2].copy(); p2_pool["score"] = sc2[sk2].values
    bg2 = sim_exit_v2(p2_pool, "T2_zt_ride")["net_ret"].to_numpy()
    for th in [68.0, 74.0, 78.0]:
        for ex in ["T2_zt_ride", "T2_close"]:
            tr2 = sim_exit_v2(p2_pool[p2_pool["score"] >= th], ex)
            print_full_d15(f"P2_S3_Lean [th{int(th)}_{ex}]", tr2, sh300, ew20, bg2)

    # 3. Also test combined P1 (prio +100) + P2_S3_Lean (th74) 1-slot & 3-slot
    tr2_sel = sim_exit_v2(p2_pool[p2_pool["score"] >= 74.0], "T2_zt_ride")
    tr1_prio = tr1_tp.copy(); tr1_prio["score"] = tr1_prio["score"] + 100.0
    combo = pd.concat([tr1_prio, tr2_sel], ignore_index=True)
    print_full_d15("COMBO P1(th75_tp10) + P2_Lean(th74_zt_ride)", combo, sh300, ew20, bg1)


if __name__ == "__main__":
    main()

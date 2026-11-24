#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Step 2g: Test IS-derived Low-Position P2_S3 & P3_S4 skeletons + P1_S1 capacity/liquidity & 2026 trade audit."""
import json, pickle
import numpy as np
import pandas as pd
from backtest_utils import calc_d15_suite, _sim_k_slots
from step2d_scorers import score_p1_s1, sim_exit_v2
from step2e_validate_final import monkey_pvalue, yearly_table

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd022_20cm_strategy_suite_20261124/part2_native_strategies"


def eval_and_print(title: str, tr: pd.DataFrame, sh300: dict, ew20: dict, bg_rets: np.ndarray):
    m = calc_d15_suite(tr, sh300, ew20)
    t1, nav1, _ = _sim_k_slots(tr, 1)
    pv = monkey_pvalue(tr, bg_rets, len(t1), nav1)
    yt = yearly_table(tr)
    print(f"\n=== {title} (Monkey p={pv:.4f}) ===")
    for w in ("FULL", "IS", "OOS", "2026"):
        mw = m[w]
        print(f"  {w:4s} | raw={mw['raw_n']:3d} 1sN={mw['n_1s']:3d} WR={mw['wr_1s']:5.1f}% PO={mw['po_1s']:4.2f} "
              f"1s={mw['nav_1s']:6.2f}x MDD={mw['mdd_1s']:5.1f}% ex5={mw['ex5_1s']:5.2f}x f50={mw['fee50_1s']:5.2f}x | "
              f"3s={mw['nav_3s']:5.2f}x MDD3={mw['mdd_3s']:5.1f}% | ew={mw['ew_nav']:6.2f}x | "
              f"exHS300={mw['ex_hs300_1s']:+7.1f}pp ex20EW={mw['ex_ew20_1s']:+7.1f}pp HLZ_t={mw['hlz_t']:5.2f}")
    print("  Yearly:", " | ".join(f"{y}:{v['nav_1s']}x(N={v['n_1s']},WR={v.get('wr_1s',0)}%,3s={v.get('nav_3s',1)}x)" for y, v in yt.items()))
    return m, yt, pv


def main():
    df = pd.read_parquet(f"{OUT_DIR}/cache_20cm_panel.parquet")
    g = df.groupby("c6", sort=False)
    df["prev_zt_obc"] = g["zt_obc"].shift(1).fillna(-1).astype(int)
    aux = pickle.load(open(f"{OUT_DIR}/cache_20cm_aux.pkl", "rb"))
    sh300, ew20 = aux["sh300"], aux["ew20_daily"]

    # 1. P1_S1 capacity & liquidity audit (amount >= 1e8 / 2e8) + inspect 2026 trades
    sk1, sc1 = score_p1_s1(df)
    p1 = df[sk1].copy(); p1["score"] = sc1[sk1].values
    p1_th = p1[p1["score"] >= 75.0]
    bg1 = sim_exit_v2(p1, "T2_close")["net_ret"].to_numpy()
    print(f"P1_S1 median T0 amount: {p1_th['amount'].median()/1e8:.2f}亿, min: {p1_th['amount'].min()/1e8:.2f}亿, <1亿 pct: {(p1_th['amount']<1e8).mean()*100:.1f}%")
    tr1_liq = sim_exit_v2(p1_th[p1_th["amount"] >= 1e8], "T2_zt_tp10")
    eval_and_print("P1_S1 [th75 + T0_amt>=1亿 + T2_zt_tp10]", tr1_liq, sh300, ew20, bg1)
    tr1_c = sim_exit_v2(p1_th, "T2_close")
    t1_c, _, _ = _sim_k_slots(tr1_c, 1)
    print("\nP1_S1 2026 1-slot sample tail 10 trades:")
    print(t1_c[t1_c["buy_date"] >= "2026-01-01"].tail(10)[["buy_date", "exit_date", "c6", "score", "open_pct", "buy_px", "exit_px", "net_ret_eval"]].to_string(index=False))

    # 2. P2_S3 LowPos (IS-calibrated: pos60 <= 0.55 or prev_pos20 <= 0.50)
    skel2 = (
        df["tradable"] & (df["is_st_pit"] == 0) & (df["close"] >= 2.0)
        & (df["tox_90d"] == 0) & (df["reg_10d"] == 0)
        & (df["prev_streak"] == 1) & (~df["is_zt"]) & df["is_true_yang"] & (df["to"] <= 35.0)
        & ((df["pos60"] <= 0.55) | (df["prev_pos20"] <= 0.50))
        & df["f1_buyable"] & df["f1_o_pct"].between(-0.07, 0.01)
    )
    sc2 = np.full(len(df), 70.0)
    sc2 += np.where(df["pos60"] <= 0.45, 8.0, 0.0)
    sc2 += np.where(df["prev_pos20"] <= 0.40, 8.0, 0.0)
    sc2 += np.where(df["bias20"] <= 0.10, 6.0, 0.0)
    sc2 += np.where(df["close"] <= 25.0, 5.0, 0.0)
    sc2 += np.where(df["lock_top10"].fillna(0) >= 45.0, 5.0, 0.0)
    sc2 += np.where(df["dist_3d30"] >= 0.10, 4.0, 0.0)
    sc2 += np.where(df["prev_zt_obc"] == 0, 4.0, 0.0)
    mon = df["f1_dt"].astype(str).str.slice(5, 7)
    sc2 += np.where(mon.isin(["01", "04"]), -8.0, 0.0)
    sc2 -= df["to"].fillna(20.0) * 0.05
    p2 = df[skel2].copy(); p2["score"] = sc2[skel2]
    bg2 = sim_exit_v2(p2, "T2_zt_ride")["net_ret"].to_numpy()
    for th in [70.0, 76.0, 82.0]:
        tr2 = sim_exit_v2(p2[p2["score"] >= th], "T2_zt_ride")
        eval_and_print(f"P2_S3_LowPos [th{int(th)}_T2_zt_ride]", tr2, sh300, ew20, bg2)

    # 3. P3_S4 LowPos (IS-calibrated: touch ZT broke, ret<12%, to<=30%, pos60<=0.55 or bias20<=0.10, open[-10%,-2.5%])
    skel3 = (
        df["tradable"] & (df["is_st_pit"] == 0) & (df["close"] >= 2.0)
        & (df["tox_90d"] == 0) & (df["reg_10d"] == 0)
        & df["is_touch_zt"] & (~df["is_zt"]) & (df["ret"] < 0.12) & (df["to"] <= 30.0)
        & ((df["pos60"] <= 0.55) | (df["bias20"] <= 0.10))
        & df["f1_buyable"] & df["f1_o_pct"].between(-0.10, -0.025)
    )
    sc3 = np.full(len(df), 70.0)
    sc3 += np.where(df["real_to"] < 20.0, 8.0, 0.0)
    sc3 += np.where(df["pos60"] <= 0.45, 6.0, 0.0)
    sc3 += np.where(df["close"] <= 25.0, 6.0, 0.0)
    sc3 += np.where(df["is_true_yang"], 4.0, 0.0)
    sc3 += np.where(df["lock_top10"].fillna(0) >= 45.0, 4.0, 0.0)
    sc3 += np.where(mon.isin(["01", "04"]), -6.0, 0.0)
    sc3 += np.where(df["lhb_has"] == 1, -8.0, 0.0)
    p3 = df[skel3].copy(); p3["score"] = sc3[skel3]
    bg3 = sim_exit_v2(p3, "T2_gap_cut_only")["net_ret"].to_numpy()
    for th in [70.0, 76.0]:
        tr3 = sim_exit_v2(p3[p3["score"] >= th], "T2_gap_cut_only")
        eval_and_print(f"P3_S4_LowPos [th{int(th)}_T2_gap_cut]", tr3, sh300, ew20, bg3)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Step 2h: Inspect P1_S1 IS drawdowns + test 20cm Big-Yang Deep-Open & Trend Pullback native prototypes."""
import pickle
import numpy as np
import pandas as pd
from backtest_utils import calc_d15_suite, _sim_k_slots
from step2d_scorers import score_p1_s1, sim_exit_v2
from step2e_validate_final import monkey_pvalue, yearly_table

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd022_20cm_strategy_suite_20261124/part2_native_strategies"


def show(title: str, tr: pd.DataFrame, sh300: dict, ew20: dict):
    m = calc_d15_suite(tr, sh300, ew20)
    yt = yearly_table(tr)
    IS, OOS, Y26, FULL = m["IS"], m["OOS"], m["2026"], m["FULL"]
    print(f"{title:44s} | IS:{IS.get('n_1s',0):3d} WR={IS.get('wr_1s',0):4.1f}% 1s={IS.get('nav_1s',1):5.2f}x MDD={IS.get('mdd_1s',0):4.1f}% ew={IS.get('ew_nav',1):5.2f}x | "
          f"OOS:{OOS.get('n_1s',0):3d} WR={OOS.get('wr_1s',0):4.1f}% 1s={OOS.get('nav_1s',1):5.2f}x MDD={OOS.get('mdd_1s',0):4.1f}% ew={OOS.get('ew_nav',1):4.2f}x | "
          f"26:{Y26.get('nav_1s',1):4.2f}x | ex5={FULL.get('ex5_1s',1):5.2f}x f50={FULL.get('fee50_1s',1):5.2f}x")
    print("  Years:", " | ".join(f"{y}:{v['nav_1s']}x({v['n_1s']})" for y, v in yt.items()))


def main():
    df = pd.read_parquet(f"{OUT_DIR}/cache_20cm_panel.parquet")
    aux = pickle.load(open(f"{OUT_DIR}/cache_20cm_aux.pkl", "rb"))
    sh300, ew20 = aux["sh300"], aux["ew20_daily"]

    # 1. P1_S1 refinement checks (IS-motivated!)
    sk1, sc1 = score_p1_s1(df)
    p1 = df[sk1].copy(); p1["score"] = sc1[sk1].values
    p1 = p1[p1["amount"] >= 1e8].copy()

    # Check worst IS trades & drawdown dates of P1_S1
    tr_base = sim_exit_v2(p1[p1["score"] >= 75.0], "T2_zt_tp10")
    t1_is, _, _ = _sim_k_slots(tr_base[tr_base["buy_date"] <= "2024-08-31"], 1)
    print("P1_S1 worst 8 IS trades:")
    print(t1_is.sort_values("net_ret_eval").head(8)[["buy_date", "c6", "score", "open_pct", "net_ret_eval"]].to_string(index=False))

    # Test regime guards on P1_S1
    for nm, extra in [
        ("P1_base(th75+amt1e8)", lambda d: d["score"] >= 75.0),
        ("P1+hard_no_mkt20_ge16", lambda d: (d["score"] >= 75.0) & (d["mkt20_zt_cnt"] < 16)),
        ("P1+hard_no_Mon", lambda d: (d["score"] >= 75.0) & (pd.to_datetime(d["f1_dt"]).dt.dayofweek != 0)),
        ("P1+hard_no_mkt16_no_Mon", lambda d: (d["score"] >= 75.0) & (d["mkt20_zt_cnt"] < 16) & (pd.to_datetime(d["f1_dt"]).dt.dayofweek != 0)),
        ("P1+open[-8.5,-3.5]", lambda d: (d["score"] >= 75.0) & d["f1_o_pct"].between(-0.085, -0.035)),
        ("P1+csi5d>-0.03", lambda d: (d["score"] >= 75.0) & (d["csi_5d"] > -0.03)),
    ]:
        show(nm, sim_exit_v2(p1[extra(p1)], "T2_zt_tp10"), sh300, ew20)

    # 2. Check 20cm Big-Yang (+12%~+19.5%, non-ZT) Deep-Open (-10%~-3.5%)
    base = df[df["tradable"] & (df["is_st_pit"] == 0) & (df["close"] >= 2.0) & (df["tox_90d"] == 0) & (df["reg_10d"] == 0)].copy()
    by_pool = base[(~base["is_zt"]) & (base["ret"].between(0.12, 0.194)) & (base["is_true_yang"]) & (base["f1_buyable"]) & (base["f1_o_pct"].between(-0.10, -0.035))].copy()
    by_pool["score"] = 70.0 + np.where(by_pool["real_free_mcap"] <= 35, 6.0, 0.0) + np.where(by_pool["to"] <= 30, 6.0, 0.0)
    show("Sibling_大阳12~19%次日深低开_T2", sim_exit_v2(by_pool, "T2_close"), sh300, ew20)
    show("Sibling_大阳12~19%+to<=30%_T2", sim_exit_v2(by_pool[by_pool["to"] <= 30], "T2_close"), sh300, ew20)

    # 3. Check 20cm Trend First-Pullback (ma20>ma60, prev_ret>=10%, today缩量回踩 -8%~-1% above ma20)
    g = df.groupby("c6", sort=False)
    ma60 = df["ma60"]
    df_t = base[(base["ac"] > base["ma20"]) & (base["ma20"] > base["ma60"]) & (base["prev_ret"] >= 0.10) & (base["ret"].between(-0.08, -0.01)) & (base["vol_ratio5"] < 1.3) & (base["f1_buyable"])].copy()
    df_t["score"] = 70.0 - df_t["pos60"] * 10.0
    show("Trend_大阳后缩量回踩_T1开_T2", sim_exit_v2(df_t[df_t["f1_o_pct"].between(-0.04, 0.03)], "T2_close"), sh300, ew20)
    show("Trend_低位pos60<=0.6_回踩_T1开_T2", sim_exit_v2(df_t[(df_t["pos60"] <= 0.60) & df_t["f1_o_pct"].between(-0.04, 0.03)], "T2_close"), sh300, ew20)


if __name__ == "__main__":
    main()

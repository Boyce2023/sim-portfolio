#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
step3b_is_analysis.py
严格仅看 IS (2021-11-15 ~ 2023-12-31) 进行四阶段诊断、邻域平滑检查与 IS 最优锁定。
严禁在本步骤读取 OOS 列！
"""

import os
import sys
import pickle
import pandas as pd
import numpy as np

sys.dont_write_bytecode = True

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/exit_opt_20261118/s1_3to4_exit"
sys.path.insert(0, OUT_DIR)
import step3_exit_sweep_all_phases as s3

IS_COLS = [
    "label", "dt_ex", "IS_raw_n", "IS_raw_wr", "IS_raw_mean", "IS_eq_nav",
    "IS_1s_n", "IS_1s_wr", "IS_1s_plr", "IS_1s_nav", "IS_mdd", "IS_calmar",
    "IS22_1s_nav", "IS23_1s_nav", "IS22_eq_nav", "IS23_eq_nav"
]

def main():
    df = pd.read_csv(f"{OUT_DIR}/sweep_all_phases_raw.csv")
    df_is = df[["phase"] + IS_COLS].copy()

    for ph in ["A", "B1", "B2", "C_peer", "D"]:
        print(f"\n==================== PHASE {ph} (ALL ROWS, IS ONLY) ====================")
        sub = df_is[df_is["phase"] == ph].sort_values(["IS_1s_nav", "IS_eq_nav"], ascending=False)
        print(sub[IS_COLS].to_string(index=False))

    print("\n==================== PHASE C (START_HHMM x PEAK x DROP IS HEATMAP) ====================")
    sub_c = df_is[df_is["phase"] == "C"].copy()
    print("--- Top 25 Phase C on IS_1s_nav ---")
    print(sub_c.sort_values(["IS_1s_nav", "IS_eq_nav"], ascending=False)[IS_COLS].head(25).to_string(index=False))

    print("\n--- Top 20 Phase C on IS_eq_nav ---")
    print(sub_c.sort_values(["IS_eq_nav", "IS_1s_nav"], ascending=False)[IS_COLS].head(20).to_string(index=False))

    # Check Baseline row in C (C_1345_p85_d50) and its neighborhood in IS
    print("\n--- Phase C: Baseline C_1345_p85_d50 & ±20% Neighbors (IS ONLY) ---")
    nbr_labels = []
    for st in [1300, 1330, 1345, 1400, 1415]:
        for pk in ["p75", "p80", "p85", "p90"]:
            for dr in ["d40", "d50", "d60", "dd35", "dd45", "dvwap"]:
                nbr_labels.append(f"C_{st}_{pk}_{dr}")
    nbr = sub_c[sub_c["label"].isin(nbr_labels)].copy()
    # Pivot IS_1s_nav by (start, peak) x drop
    nbr[["c", "st", "pk", "dr"]] = nbr["label"].str.split("_", expand=True)
    piv_1s = nbr.pivot(index=["st", "pk"], columns="dr", values="IS_1s_nav")
    piv_eq = nbr.pivot(index=["st", "pk"], columns="dr", values="IS_eq_nav")
    print("Pivot IS_1s_nav:")
    print(piv_1s.to_string())
    print("\nPivot IS_eq_nav:")
    print(piv_eq.to_string())

    # Also inspect ALL start times for d60, d50, d40, dvwap, dd35, dd45
    print("\n--- Phase C: Peak=p85 across all start_hhmm x drop (IS_1s_nav) ---")
    sub_p85 = sub_c[sub_c["label"].str.contains("_p85_")].copy()
    sub_p85[["c", "st", "pk", "dr"]] = sub_p85["label"].str.split("_", expand=True)
    print(sub_p85.pivot(index="st", columns="dr", values="IS_1s_nav").to_string())

    print("\n--- Phase C: Peak=p75 across all start_hhmm x drop (IS_1s_nav) ---")
    sub_p75 = sub_c[sub_c["label"].str.contains("_p75_")].copy()
    sub_p75[["c", "st", "pk", "dr"]] = sub_p75["label"].str.split("_", expand=True)
    print(sub_p75.pivot(index="st", columns="dr", values="IS_1s_nav").to_string())

    print("\n--- Phase C: Peak=pzt across all start_hhmm x drop (IS_1s_nav) ---")
    sub_pzt = sub_c[sub_c["label"].str.contains("_pzt_")].copy()
    sub_pzt[["c", "st", "pk", "dr"]] = sub_pzt["label"].str.split("_", expand=True)
    print(sub_pzt.pivot(index="st", columns="dr", values="IS_1s_nav").to_string())

    # Inspect IS dt_exact exits in baseline
    with open(f"{OUT_DIR}/cache_3to4_exit.pkl", "rb") as f:
        cache = pickle.load(f)
    base = s3.evaluate_variant(cache, {"a_mode": "baseline"}, "BASE", 90.0)
    base_is_dt = base["slot_df"][(base["slot_df"]["buy_date"] <= "2023-12-31") & (base["slot_df"]["is_dt_exact_exit"])]
    print("\n--- Baseline IS trades that exited on is_dt_exact (15:00 limit down) ---")
    print(base_is_dt[["code", "name", "buy_date", "exit_date", "exit_hhmm", "exit_price", "net_ret", "reason"]].to_string(index=False))


if __name__ == "__main__":
    main()

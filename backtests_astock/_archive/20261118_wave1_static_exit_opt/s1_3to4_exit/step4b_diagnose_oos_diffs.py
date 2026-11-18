#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
step4b_diagnose_oos_diffs.py
逐笔核对 IS 锁定候选在 OOS (2024-2026) 上与 BASE_V40 的交易差异，
判断 OOS 退化或增益的物理来源（个别大妖震出 vs 系统性机制改善）。
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


def show_all_diffs(base_res, cand_res, label, scope="ALL"):
    b = base_res["raw_df"].set_index(["buy_date", "code"])
    c = cand_res["raw_df"].set_index(["buy_date", "code"])
    diffs = []
    for k in b.index:
        if scope == "IS" and k[0] > "2023-12-31":
            continue
        if scope == "OOS" and k[0] <= "2023-12-31":
            continue
        rb, rc = b.loc[k], c.loc[k]
        if abs(rb["net_ret"] - rc["net_ret"]) > 1e-6 or rb["exit_date"] != rc["exit_date"] or rb["exit_hhmm"] != rc["exit_hhmm"]:
            diffs.append({
                "buy_date": k[0], "code": k[1], "name": rb["name"], "score": rb["score"],
                "base_ex": f"{rb['exit_date']}@{rb['exit_hhmm']}", "base_ret": round(rb["net_ret"]*100, 2),
                "new_ex": f"{rc['exit_date']}@{rc['exit_hhmm']}", "new_ret": round(rc["net_ret"]*100, 2),
                "new_rsn": rc["reason"], "delta_pp": round((rc["net_ret"] - rb["net_ret"])*100, 2),
            })
    ddf = pd.DataFrame(diffs)
    pos_cnt = int((ddf["delta_pp"] > 0).sum()) if not ddf.empty else 0
    neg_cnt = int((ddf["delta_pp"] < 0).sum()) if not ddf.empty else 0
    print(f"\n=== {label} [{scope}] Diffs={len(ddf)} (Win={pos_cnt}, Loss={neg_cnt}) | OOS_1s={cand_res['OOS']['nav_1s']}x (base {base_res['OOS']['nav_1s']}x), OOS_eq={cand_res['OOS']['eq_nav']}x (base {base_res['OOS']['eq_nav']}x) ===")
    if not ddf.empty:
        print(ddf.to_string(index=False))


def main():
    with open(f"{OUT_DIR}/cache_3to4_exit.pkl", "rb") as f:
        cache = pickle.load(f)
    base = s3.evaluate_variant(cache, {"a_mode": "baseline"}, "BASE", 90.0)

    check_list = [
        ("B2_dev93_ge7b_8bday", {"b_dev_ratio": 0.93, "b_dev_min_boards": 7}),
        ("C_1345_p85_d60", {"c_mode": "grid", "c_start": 1345, "c_peak_type": "pct", "c_peak_val": 0.085, "c_drop_type": "pct", "c_drop_val": 0.060}),
        ("C_1345_p75_d60", {"c_mode": "grid", "c_start": 1345, "c_peak_type": "pct", "c_peak_val": 0.075, "c_drop_type": "pct", "c_drop_val": 0.060}),
        ("C_1330_p85_dd35", {"c_mode": "grid", "c_start": 1330, "c_peak_type": "pct", "c_peak_val": 0.085, "c_drop_type": "dd", "c_drop_val": 0.035}),
        ("D1_zero_immunity", {"d_mode": "zero"}),
        ("D2b_yang_and_pct_ge_2", {"d_mode": "true_yang_pct_ge_2"}),
        ("D3_true_yang_only", {"d_mode": "true_yang_only"}),
        ("D4_yang_pct0_to35", {"d_mode": "true_yang_to_cap", "d_to_cap": 35.0}),
        ("D5_imm_next_opencut_n3", {"d_imm_next_cut": -0.03}),
    ]
    for lbl, cfg in check_list:
        r = s3.evaluate_variant(cache, cfg, lbl, 90.0)
        show_all_diffs(base, r, lbl, "ALL")

    # 也检查阶段 C 的全量 IS vs OOS 对比：到底有没有哪组 c_start/peak/drop 或相邻参数在 OOS 表现如何（仅供事后物理归因分析！）
    df_sweep = pd.read_csv(f"{OUT_DIR}/sweep_all_phases_raw.csv")
    sub_c = df_sweep[df_sweep["phase"].isin(["C", "C_peer"])].copy()
    sub_c["both_win"] = (sub_c["IS_1s_nav"] > 4.7483) & (sub_c["IS_eq_nav"] > 4.5351) & (sub_c["OOS_1s_nav"] > 379.0811) & (sub_c["OOS_eq_nav"] > 983.2141)
    print("\n=== Stage C: Any variant beating baseline on ALL FOUR (IS_1s, IS_eq, OOS_1s, OOS_eq)? ===")
    wins = sub_c[sub_c["both_win"]]
    if wins.empty:
        print("NONE! Zero variants in all 284 Stage C variants beat baseline simultaneously on (IS_1s, IS_eq, OOS_1s, OOS_eq)!")
    else:
        print(wins[["label", "IS_1s_nav", "IS_eq_nav", "IS_mdd", "OOS_1s_nav", "OOS_eq_nav", "OOS_mdd", "5Y_1s_nav", "5Y_eq_nav"]].to_string(index=False))

    # Print Stage C top by OOS_eq_nav for diagnostic understanding (NOT for selection!)
    print("\n=== Stage C Diagnostic: Top 15 by 5Y_eq_nav (to see why baseline d50 vs others behaved differently in OOS) ===")
    print(sub_c.sort_values("5Y_eq_nav", ascending=False)[["label", "IS_1s_nav", "IS_eq_nav", "IS_mdd", "OOS_1s_nav", "OOS_eq_nav", "OOS_mdd", "5Y_1s_nav", "5Y_eq_nav"]].head(15).to_string(index=False))


if __name__ == "__main__":
    main()

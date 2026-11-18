#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
step4_oos_blind_validation.py
一次性在全盲 OOS (2024-01-01 ~ 2026-11-16) 检验所有 IS 锁定候选、组合方案及待证伪项。
覆盖 std90 与 strict102 双档。
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


def main():
    with open(f"{OUT_DIR}/cache_3to4_exit.pkl", "rb") as f:
        cache = pickle.load(f)

    # 1. 先检查 IS 组合候选（与 IS 锁定单项一起列出）
    candidates = [
        ("BASE_V40", {"a_mode": "baseline"}),

        # Stage A 对照（验证 IS 失败的策略在 OOS 是否也被证伪或真能反转）
        ("A1_2to3_no_0925_cut", {"a_mode": "no_cut"}),
        ("A2_2to3_big_yin_neg3", {"a_mode": "big_yin", "a_yin_thr": -0.03}),
        ("A5a_1to2_d5_1030_vwap_all", {"a_mode": "1030_vwap_all"}),
        ("A6b_dark_exempt_d5_0925", {"a_mode": "dark_exempt_cutweak", "a_dark_src": "d5"}),

        # Stage B 对照（验证孤立尖峰是否 OOS 证伪）
        ("B1_gap88_ge5b", {"b_gap_thr": 0.088, "b_gap_scope": "ge5b"}),
        ("B1_gap92_first_next", {"b_gap_thr": 0.092, "b_gap_scope": "first"}),
        ("B2_dev93_all_boards", {"b_dev_ratio": 0.93, "b_dev_min_boards": 4}),
        ("B2_dev93_ge5b_6bday", {"b_dev_ratio": 0.93, "b_dev_min_boards": 5}),
        ("B2_dev93_ge6b_7bday", {"b_dev_ratio": 0.93, "b_dev_min_boards": 6}),
        ("B2_dev93_ge7b_8bday", {"b_dev_ratio": 0.93, "b_dev_min_boards": 7}),
        ("B2_dev96_ge6b_7bday", {"b_dev_ratio": 0.96, "b_dev_min_boards": 6}),
        ("B2_dev96_ge7b_8bday", {"b_dev_ratio": 0.96, "b_dev_min_boards": 7}),
        ("B2_dev98_ge6b_7bday", {"b_dev_ratio": 0.98, "b_dev_min_boards": 6}),
        ("B2_dev98_ge7b_8bday", {"b_dev_ratio": 0.98, "b_dev_min_boards": 7}),

        # Stage C IS锁定主候选及其邻域高原 + 1to2 对照
        ("C_1to2_1030vwap_1430rush", {"c_mode": "1to2_vwap"}),
        ("C_base1345_plus_1430rush", {"c_mode": "grid", "c_start": 1345, "c_peak_type": "pct", "c_peak_val": 0.085, "c_drop_type": "pct", "c_drop_val": 0.050, "c_1430_rush": True}),
        ("C_1345_p85_d60 [IS_MAIN]", {"c_mode": "grid", "c_start": 1345, "c_peak_type": "pct", "c_peak_val": 0.085, "c_drop_type": "pct", "c_drop_val": 0.060}),
        ("C_1345_p75_d60 [IS_ALT1]", {"c_mode": "grid", "c_start": 1345, "c_peak_type": "pct", "c_peak_val": 0.075, "c_drop_type": "pct", "c_drop_val": 0.060}),
        ("C_1345_p80_d60", {"c_mode": "grid", "c_start": 1345, "c_peak_type": "pct", "c_peak_val": 0.080, "c_drop_type": "pct", "c_drop_val": 0.060}),
        ("C_1345_p85_d65", {"c_mode": "grid", "c_start": 1345, "c_peak_type": "pct", "c_peak_val": 0.085, "c_drop_type": "pct", "c_drop_val": 0.065}),
        ("C_1345_p85_d70", {"c_mode": "grid", "c_start": 1345, "c_peak_type": "pct", "c_peak_val": 0.085, "c_drop_type": "pct", "c_drop_val": 0.070}),
        ("C_1330_p85_d60", {"c_mode": "grid", "c_start": 1330, "c_peak_type": "pct", "c_peak_val": 0.085, "c_drop_type": "pct", "c_drop_val": 0.060}),
        ("C_1330_p85_dd35 [IS_ALT2]", {"c_mode": "grid", "c_start": 1330, "c_peak_type": "pct", "c_peak_val": 0.085, "c_drop_type": "dd", "c_drop_val": 0.035}),
        ("C_1345_p85_dd35", {"c_mode": "grid", "c_start": 1345, "c_peak_type": "pct", "c_peak_val": 0.085, "c_drop_type": "dd", "c_drop_val": 0.035}),

        # Stage D IS待决候选
        ("D1_zero_immunity", {"d_mode": "zero"}),
        ("D2a_1to2_pct_ge_2", {"d_mode": "pct_ge_2"}),
        ("D2b_yang_and_pct_ge_2", {"d_mode": "true_yang_pct_ge_2"}),
        ("D3_true_yang_only", {"d_mode": "true_yang_only"}),
        ("D4_yang_pct0_to35", {"d_mode": "true_yang_to_cap", "d_to_cap": 35.0}),
        ("D5_imm_next_opencut_n3", {"d_imm_next_cut": -0.03}),

        # 组合合成候选 (IS 锁定组合)
        ("Combo_C8560_D1", {"c_mode": "grid", "c_start": 1345, "c_peak_type": "pct", "c_peak_val": 0.085, "c_drop_type": "pct", "c_drop_val": 0.060, "d_mode": "zero"}),
        ("Combo_C7560_D1", {"c_mode": "grid", "c_start": 1345, "c_peak_type": "pct", "c_peak_val": 0.075, "c_drop_type": "pct", "c_drop_val": 0.060, "d_mode": "zero"}),
        ("Combo_C8560_D5n3", {"c_mode": "grid", "c_start": 1345, "c_peak_type": "pct", "c_peak_val": 0.085, "c_drop_type": "pct", "c_drop_val": 0.060, "d_imm_next_cut": -0.03}),
        ("Combo_C8560_D2b", {"c_mode": "grid", "c_start": 1345, "c_peak_type": "pct", "c_peak_val": 0.085, "c_drop_type": "pct", "c_drop_val": 0.060, "d_mode": "true_yang_pct_ge_2"}),
        ("Combo_C8560_B2dev93ge7b", {"c_mode": "grid", "c_start": 1345, "c_peak_type": "pct", "c_peak_val": 0.085, "c_drop_type": "pct", "c_drop_val": 0.060, "b_dev_ratio": 0.93, "b_dev_min_boards": 7}),
        ("Combo_C8560_D1_B2dev93ge7b", {"c_mode": "grid", "c_start": 1345, "c_peak_type": "pct", "c_peak_val": 0.085, "c_drop_type": "pct", "c_drop_val": 0.060, "d_mode": "zero", "b_dev_ratio": 0.93, "b_dev_min_boards": 7}),
    ]

    rows90, rows102 = [], []
    res_store = {}
    for lbl, cfg in candidates:
        r90 = s3.evaluate_variant(cache, cfg, lbl, 90.0)
        r102 = s3.evaluate_variant(cache, cfg, lbl, 102.0)
        res_store[lbl] = (r90, r102)
        rows90.append({
            "label": lbl,
            "IS_1s": r90["IS"]["nav_1s"], "IS_eq": r90["IS"]["eq_nav"], "IS_mdd": r90["IS"]["mdd"],
            "OOS_n": r90["OOS"]["n_1s"], "OOS_wr": r90["OOS"]["wr_1s"], "OOS_plr": r90["OOS"]["plr_1s"],
            "OOS_1s": r90["OOS"]["nav_1s"], "OOS_eq": r90["OOS"]["eq_nav"], "OOS_mdd": r90["OOS"]["mdd"],
            "5Y_n": r90["ALL_5Y"]["n_1s"], "5Y_wr": r90["ALL_5Y"]["wr_1s"], "5Y_1s": r90["ALL_5Y"]["nav_1s"],
            "5Y_eq": r90["ALL_5Y"]["eq_nav"], "5Y_mdd": r90["ALL_5Y"]["mdd"], "5Y_t3": r90["ALL_5Y"]["t3"], "5Y_t5": r90["ALL_5Y"]["t5"],
            "Y26_1s": r90["Y26"]["nav_1s"],
        })
        rows102.append({
            "label": lbl,
            "IS_1s": r102["IS"]["nav_1s"], "IS_mdd": r102["IS"]["mdd"],
            "OOS_n": r102["OOS"]["n_1s"], "OOS_wr": r102["OOS"]["wr_1s"], "OOS_1s": r102["OOS"]["nav_1s"], "OOS_mdd": r102["OOS"]["mdd"],
            "5Y_n": r102["ALL_5Y"]["n_1s"], "5Y_wr": r102["ALL_5Y"]["wr_1s"], "5Y_1s": r102["ALL_5Y"]["nav_1s"], "5Y_mdd": r102["ALL_5Y"]["mdd"],
            "5Y_t3": r102["ALL_5Y"]["t3"], "Y26_1s": r102["Y26"]["nav_1s"],
        })

    df90 = pd.DataFrame(rows90)
    df102 = pd.DataFrame(rows102)
    df90.to_csv(f"{OUT_DIR}/oos_blind_check_std90.csv", index=False, encoding="utf-8-sig")
    df102.to_csv(f"{OUT_DIR}/oos_blind_check_strict102.csv", index=False, encoding="utf-8-sig")

    print("\n==================== BLIND OOS VALIDATION: STD90 (>=90分) ====================")
    print(df90.to_string(index=False))

    print("\n==================== BLIND OOS VALIDATION: STRICT102 (>=102分) ====================")
    print(df102.to_string(index=False))


if __name__ == "__main__":
    main()

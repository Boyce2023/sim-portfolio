#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
step3c_is_deep_check.py
严格仅在 IS (2021-11-15 ~ 2023-12-31) 深度解剖：
1. Stage B2 (dev93/96/98) 在 IS 逐笔触发明细与反常尖峰诊断
2. Stage D (免死金牌各规则) 在 IS 逐笔触发明细
3. Stage C 在 d55/d60/d65/d70 & dd30/dd35/dd40 精细高原扫描 + 逐笔差异
4. strict102 (102分S档) 在 IS 的同步对比
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


def diff_is_trades(base_res, cand_res, label):
    b = base_res["raw_df"]
    c = cand_res["raw_df"]
    b_is = b[b["buy_date"] <= "2023-12-31"].set_index(["buy_date", "code"])
    c_is = c[c["buy_date"] <= "2023-12-31"].set_index(["buy_date", "code"])
    print(f"\n--- IS RAW Trade Diff: {label} (IS_1s={cand_res['IS']['nav_1s']}x, IS_eq={cand_res['IS']['eq_nav']}x) ---")
    cnt = 0
    for k in b_is.index:
        rb, rc = b_is.loc[k], c_is.loc[k]
        if abs(rb["net_ret"] - rc["net_ret"]) > 1e-6 or rb["exit_date"] != rc["exit_date"] or rb["exit_hhmm"] != rc["exit_hhmm"]:
            cnt += 1
            print(f"  {k[0]} {k[1]} {rb['name']}: BASE {rb['exit_date']}@{rb['exit_hhmm']} ({rb['net_ret']*100:+.2f}%, {rb['reason']}) -> NEW {rc['exit_date']}@{rc['exit_hhmm']} ({rc['net_ret']*100:+.2f}%, {rc['reason']}) [delta={(rc['net_ret']-rb['net_ret'])*100:+.2f}pp]")
    if cnt == 0:
        print("  (Zero IS trades changed)")


def main():
    with open(f"{OUT_DIR}/cache_3to4_exit.pkl", "rb") as f:
        cache = pickle.load(f)

    base = s3.evaluate_variant(cache, {"a_mode": "baseline"}, "BASE", 90.0)

    # 1. Stage B1 & B2 IS trade diffs
    for lbl, cfg in [
        ("B1_gap88_ge5b", {"b_gap_thr": 0.088, "b_gap_scope": "ge5b"}),
        ("B2_dev93_ge5b", {"b_dev_ratio": 0.93, "b_dev_min_boards": 5}),
        ("B2_dev96_ge5b", {"b_dev_ratio": 0.96, "b_dev_min_boards": 5}),
        ("B2_dev98_ge5b", {"b_dev_ratio": 0.98, "b_dev_min_boards": 5}),
        ("B2_dev93_ge6b", {"b_dev_ratio": 0.93, "b_dev_min_boards": 6}),
        ("B2_dev96_ge6b", {"b_dev_ratio": 0.96, "b_dev_min_boards": 6}),
        ("B2_dev93_ge7b", {"b_dev_ratio": 0.93, "b_dev_min_boards": 7}),
        ("B2_dev96_ge7b", {"b_dev_ratio": 0.96, "b_dev_min_boards": 7}),
    ]:
        r = s3.evaluate_variant(cache, cfg, lbl, 90.0)
        diff_is_trades(base, r, lbl)

    # 2. Stage D IS trade diffs
    for lbl, cfg in [
        ("D1_zero_immunity", {"d_mode": "zero"}),
        ("D2a_1to2_pct_ge_2", {"d_mode": "pct_ge_2"}),
        ("D2b_yang_and_pct_ge_2", {"d_mode": "true_yang_pct_ge_2"}),
        ("D3_true_yang_only", {"d_mode": "true_yang_only"}),
        ("D4_yang_pct0_to35", {"d_mode": "true_yang_to_cap", "d_to_cap": 35.0}),
        ("D5_imm_next_opencut_n3", {"d_imm_next_cut": -0.03}),
    ]:
        r = s3.evaluate_variant(cache, cfg, lbl, 90.0)
        diff_is_trades(base, r, lbl)

    # 3. Stage C fine plateau check (IS ONLY) around d50..d70 and dd25..dd45
    print("\n=== Stage C Fine Plateau (IS ONLY, std90 & strict102) ===")
    c_cands = [("C_only_1455_none", {"c_mode": "none"})]
    for st in [1115, 1300, 1330, 1345, 1400]:
        for pk_lbl, pk_v in [("p75", 0.075), ("p80", 0.080), ("p85", 0.085), ("p90", 0.090)]:
            for dr_lbl, dt_t, dv in [
                ("d50", "pct", 0.050), ("d55", "pct", 0.055), ("d60", "pct", 0.060), ("d65", "pct", 0.065), ("d70", "pct", 0.070),
                ("dd30", "dd", 0.030), ("dd35", "dd", 0.035), ("dd40", "dd", 0.040),
            ]:
                c_cands.append((
                    f"C_{st}_{pk_lbl}_{dr_lbl}",
                    {"c_mode": "grid", "c_start": st, "c_peak_type": "pct", "c_peak_val": pk_v, "c_drop_type": dt_t, "c_drop_val": dv}
                ))

    rows = []
    for lbl, cfg in c_cands:
        r90 = s3.evaluate_variant(cache, cfg, lbl, 90.0)
        r102 = s3.evaluate_variant(cache, cfg, lbl, 102.0)
        rows.append({
            "label": lbl,
            "IS90_eq": r90["IS"]["eq_nav"], "IS90_1s": r90["IS"]["nav_1s"],
            "IS90_mdd": r90["IS"]["mdd"], "IS90_calmar": r90["IS"]["calmar"],
            "IS22_eq": r90["IS_2022"]["eq_nav"], "IS23_eq": r90["IS_2023"]["eq_nav"],
            "IS22_1s": r90["IS_2022"]["nav_1s"], "IS23_1s": r90["IS_2023"]["nav_1s"],
            "IS102_1s": r102["IS"]["nav_1s"], "IS102_mdd": r102["IS"]["mdd"],
        })
    cdf = pd.DataFrame(rows).sort_values(["IS90_1s", "IS90_eq"], ascending=False)
    print(cdf.head(35).to_string(index=False))
    print("\nBaseline C_1345_p85_d50 & C_only_1455_none:")
    print(cdf[cdf["label"].isin(["C_1345_p85_d50", "C_only_1455_none"])].to_string(index=False))

    # Inspect IS trade diffs for C_1345_p85_d60, C_1345_p75_d60, C_1330_p85_dd35
    for lbl, cfg in [
        ("C_1345_p85_d60", {"c_mode": "grid", "c_start": 1345, "c_peak_type": "pct", "c_peak_val": 0.085, "c_drop_type": "pct", "c_drop_val": 0.060}),
        ("C_1345_p75_d60", {"c_mode": "grid", "c_start": 1345, "c_peak_type": "pct", "c_peak_val": 0.075, "c_drop_type": "pct", "c_drop_val": 0.060}),
        ("C_1330_p85_dd35", {"c_mode": "grid", "c_start": 1330, "c_peak_type": "pct", "c_peak_val": 0.085, "c_drop_type": "dd", "c_drop_val": 0.035}),
    ]:
        r = s3.evaluate_variant(cache, cfg, lbl, 90.0)
        diff_is_trades(base, r, lbl)


if __name__ == "__main__":
    main()

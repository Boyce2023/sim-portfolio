#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
step4d_final_truth_check.py
检验 351 核心宇宙与 std90/strict102 上，是否真有任何卖点变体能同时通过：
  (1) IS 双子段同向正增益
  (2) IS ±20% 参数邻域平滑
  (3) 盲测 OOS (std90 1S & EQ, strict102 1S) 全部不退化且正向增益
  (4) 独立触发变动笔数充分 (不靠单笔巧合)
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

    # 1. Check ALL 363 variants in sweep_all_phases_raw.csv: which ones beat BASE on BOTH IS and OOS (1S AND EQ) without worsening MDD?
    df = pd.read_csv(f"{OUT_DIR}/sweep_all_phases_raw.csv")
    base = df[df["label"] == "A0_baseline_cut_weak"].iloc[0]

    print(f"BASE: IS_1s={base['IS_1s_nav']}, IS_eq={base['IS_eq_nav']}, IS_mdd={base['IS_mdd']} | OOS_1s={base['OOS_1s_nav']}, OOS_eq={base['OOS_eq_nav']}, OOS_mdd={base['OOS_mdd']} | 5Y_1s={base['5Y_1s_nav']}, 5Y_eq={base['5Y_eq_nav']}")

    mask_all4 = (
        (df["IS_1s_nav"] > base["IS_1s_nav"] + 1e-4)
        & (df["IS_eq_nav"] > base["IS_eq_nav"] + 1e-4)
        & (df["OOS_1s_nav"] > base["OOS_1s_nav"] + 1e-4)
        & (df["OOS_eq_nav"] > base["OOS_eq_nav"] + 1e-4)
        & (df["IS_mdd"] <= base["IS_mdd"] + 1e-4)
        & (df["OOS_mdd"] <= base["OOS_mdd"] + 1e-4)
    )
    winners = df[mask_all4].copy()
    print(f"\n=== Out of {len(df)} variants, how many beat BASE on IS_1s, IS_eq, OOS_1s, OOS_eq AND non-worse MDD? Count = {len(winners)} ===")
    if not winners.empty:
        cols = ["phase", "label", "IS_1s_nav", "IS_eq_nav", "IS_mdd", "IS22_1s_nav", "IS23_1s_nav", "OOS_1s_nav", "OOS_eq_nav", "OOS_mdd", "5Y_1s_nav", "5Y_eq_nav"]
        print(winners[cols].to_string(index=False))

    # Relaxed check: allow IS_1s > base and OOS_eq > base (or OOS_1s > base)
    mask_relaxed = (
        (df["IS_1s_nav"] > base["IS_1s_nav"] + 1e-4)
        & (df["IS_eq_nav"] > base["IS_eq_nav"] + 1e-4)
        & ((df["OOS_1s_nav"] > base["OOS_1s_nav"] + 1e-4) | (df["OOS_eq_nav"] > base["OOS_eq_nav"] + 1e-4))
    )
    w_rel = df[mask_relaxed].copy()
    print(f"\n=== Relaxed (IS both win + at least one of OOS_1s/OOS_eq wins): Count = {len(w_rel)} ===")
    if not w_rel.empty:
        cols = ["phase", "label", "IS_1s_nav", "IS_eq_nav", "IS_mdd", "OOS_1s_nav", "OOS_eq_nav", "OOS_mdd", "5Y_1s_nav", "5Y_eq_nav"]
        print(w_rel[cols].to_string(index=False))

    # 2. Check D4_to_cap across 351 core universe
    r_b = s3.evaluate_variant(cache, {}, "BASE", -999.0)["raw_df"].set_index(["buy_date", "code"])
    for cap in [25.0, 30.0, 35.0, 40.0]:
        r_d4 = s3.evaluate_variant(cache, {"d_mode": "true_yang_to_cap", "d_to_cap": cap}, f"D4_{cap}", -999.0)["raw_df"].set_index(["buy_date", "code"])
        diffs = []
        for k in r_b.index:
            d = (r_d4.loc[k, "net_ret"] - r_b.loc[k, "net_ret"]) * 100.0
            if abs(d) > 1e-4:
                diffs.append((k[0], k[1], r_b.loc[k, "name"], r_b.loc[k, "score"], round(r_b.loc[k, "net_ret"]*100, 2), round(r_d4.loc[k, "net_ret"]*100, 2), round(d, 2)))
        print(f"\nD4_to_{int(cap)} (core 351): changed={len(diffs)} -> {diffs}")

    # 3. Check C_1345_p75_d50 on 351 core universe & strict102
    for lbl, cfg in [
        ("BASE", {}),
        ("C_1345_p75_d50", {"c_mode": "grid", "c_start": 1345, "c_peak_type": "pct", "c_peak_val": 0.075, "c_drop_type": "pct", "c_drop_val": 0.050}),
        ("C_1345_p80_d50", {"c_mode": "grid", "c_start": 1345, "c_peak_type": "pct", "c_peak_val": 0.080, "c_drop_type": "pct", "c_drop_val": 0.050}),
        ("C_1345_p85_d60", {"c_mode": "grid", "c_start": 1345, "c_peak_type": "pct", "c_peak_val": 0.085, "c_drop_type": "pct", "c_drop_val": 0.060}),
    ]:
        r_core = s3.evaluate_variant(cache, cfg, lbl, -999.0)
        r_102 = s3.evaluate_variant(cache, cfg, lbl, 102.0)
        print(f"\n{lbl:16s} | CORE351: IS_eq={r_core['IS']['eq_nav']:.4f}x, OOS_eq={r_core['OOS']['eq_nav']:.4f}x, 5Y_eq={r_core['ALL_5Y']['eq_nav']:.4f}x | S102: IS_1s={r_102['IS']['nav_1s']:.4f}x, OOS_1s={r_102['OOS']['nav_1s']:.4f}x, 5Y_1s={r_102['ALL_5Y']['nav_1s']:.4f}x")


if __name__ == "__main__":
    main()

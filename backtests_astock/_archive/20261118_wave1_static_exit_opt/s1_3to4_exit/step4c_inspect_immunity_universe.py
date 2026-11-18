#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
step4c_inspect_immunity_universe.py
全面审计所有 115 笔 std90 与 全 389 笔 core_skel 在断板免死金牌处的真实表现，
检验 D3_true_yang_only, D2b_yang_and_pct_ge_2, D5_imm_next_opencut_n3 是否具备大样本统计显著性。
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

    # 1. Inspect all trades in std90 that triggered baseline immunity OR D3 OR D2b
    base90 = s3.evaluate_variant(cache, {"a_mode": "baseline"}, "BASE", 90.0)
    d1_90 = s3.evaluate_variant(cache, {"d_mode": "zero"}, "D1", 90.0)
    d3_90 = s3.evaluate_variant(cache, {"d_mode": "true_yang_only"}, "D3", 90.0)

    b_df = base90["raw_df"].set_index(["buy_date", "code"])
    d1_df = d1_90["raw_df"].set_index(["buy_date", "code"])
    d3_df = d3_90["raw_df"].set_index(["buy_date", "code"])

    print("=== ALL std90 trades where BASE immunity OR D3 immunity triggered ===")
    cb_map = cache["code_bars_ext"]
    for k in b_df.index:
        rb, r1, r3 = b_df.loc[k], d1_df.loc[k], d3_df.loc[k]
        if abs(rb["net_ret"] - r1["net_ret"]) > 1e-6 or abs(rb["net_ret"] - r3["net_ret"]) > 1e-6:
            cb = cb_map[k[1]]
            # find break day (exit day of D1)
            ex1 = r1["exit_date"]
            p = cb["date_to_pos"][ex1]
            pc, op, cl, to = cb["pre_c"][p], cb["open"][p], cb["close"][p], cb["to"][p]
            nxt_op = cb["open"][p+1] / cl - 1.0 if p+1 < len(cb["dts"]) else 0.0
            print(f"  [{ 'IS' if k[0]<='2023-12-31' else 'OOS'}] {k[0]} {k[1]} {rb['name']} (sc={rb['score']}): break={ex1} open={op/pc-1:+.2%} close={cl/pc-1:+.2%} body={(cl-op)/pc:+.2%} to={to:.1f}% next_op={nxt_op:+.2%} | D1={r1['net_ret']*100:+.2f}% BASE={rb['net_ret']*100:+.2f}% D3={r3['net_ret']*100:+.2f}%")

    # 2. Test on ENTIRE skel universe (score >= -999, N=389 core candidates) to check if D3/D2b/D5 hold on broad universe!
    print("\n=== FULL CORE UNIVERSE (all skel, ~389 cands) CHECK: IS vs OOS RAW MEAN & EQ_NAV ===")
    for lbl, cfg in [
        ("BASE", {}),
        ("D1_zero_imm", {"d_mode": "zero"}),
        ("D2b_yang_pct2", {"d_mode": "true_yang_pct_ge_2"}),
        ("D3_true_yang_only", {"d_mode": "true_yang_only"}),
        ("D4_to_35", {"d_mode": "true_yang_to_cap", "d_to_cap": 35.0}),
        ("D5_opencut_n3", {"d_imm_next_cut": -0.03}),
        ("D3_plus_D5n3", {"d_mode": "true_yang_only", "d_imm_next_cut": -0.03}),
        ("C_1345_p85_d60", {"c_mode": "grid", "c_start": 1345, "c_peak_type": "pct", "c_peak_val": 0.085, "c_drop_type": "pct", "c_drop_val": 0.060}),
    ]:
        r_all = s3.evaluate_variant(cache, cfg, lbl, -999.0)
        print(f"  {lbl:20s} | ALL(N={r_all['ALL_5Y']['raw_n']}): raw_mean={r_all['ALL_5Y']['raw_mean']:+.2f}%, eq={r_all['ALL_5Y']['eq_nav']:.2f}x | IS(N={r_all['IS']['raw_n']}): mean={r_all['IS']['raw_mean']:+.2f}%, eq={r_all['IS']['eq_nav']:.2f}x | OOS(N={r_all['OOS']['raw_n']}): mean={r_all['OOS']['raw_mean']:+.2f}%, eq={r_all['OOS']['eq_nav']:.2f}x")

    # 3. On full core universe, print ALL trades changed by D3_true_yang_only and D5_opencut_n3
    r_b = s3.evaluate_variant(cache, {}, "BASE", -999.0)["raw_df"].set_index(["buy_date", "code"])
    r_d3 = s3.evaluate_variant(cache, {"d_mode": "true_yang_only"}, "D3", -999.0)["raw_df"].set_index(["buy_date", "code"])
    r_d5 = s3.evaluate_variant(cache, {"d_imm_next_cut": -0.03}, "D5", -999.0)["raw_df"].set_index(["buy_date", "code"])
    r_d2b = s3.evaluate_variant(cache, {"d_mode": "true_yang_pct_ge_2"}, "D2b", -999.0)["raw_df"].set_index(["buy_date", "code"])

    for name_t, r_t in [("D3_true_yang_only (core skel)", r_d3), ("D5_opencut_n3 (core skel)", r_d5), ("D2b_yang_pct2 (core skel)", r_d2b)]:
        diffs = []
        for k in r_b.index:
            d = (r_t.loc[k, "net_ret"] - r_b.loc[k, "net_ret"]) * 100.0
            if abs(d) > 1e-4:
                diffs.append((k[0], k[1], r_b.loc[k, "name"], r_b.loc[k, "score"], round(r_b.loc[k, "net_ret"]*100, 2), round(r_t.loc[k, "net_ret"]*100, 2), round(d, 2)))
        w = sum(1 for x in diffs if x[6] > 0)
        l = sum(1 for x in diffs if x[6] < 0)
        print(f"\n--- {name_t}: Total changed={len(diffs)} (Win={w}, Loss={l}, AvgDelta={np.mean([x[6] for x in diffs]) if diffs else 0:+.2f}pp) ---")
        for x in diffs:
            print(f"  {x[0]} {x[1]} {x[2]} (sc={x[3]}): {x[4]:+.2f}% -> {x[5]:+.2f}% ({x[6]:+.2f}pp)")


if __name__ == "__main__":
    main()

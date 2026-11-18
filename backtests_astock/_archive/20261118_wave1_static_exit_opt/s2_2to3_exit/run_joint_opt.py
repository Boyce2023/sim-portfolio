#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Joint synthesis & parameter plateau verification across Track 1 (Canon 5m) and Track 2 (Full 5m).
Also checks exact trade-level diffs and ±20% plateau stability on IS before OOS confirmation.
"""
import os, sys, json, pickle
import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/exit_opt_20261118/s2_2to3_exit"
IDX_JSON = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/sandbox_lab/index_klines_5y_cache.json"
CSI_CANON_JSON = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/clean_rebacktest_20261116/csi300_canonical_20261116.json"
CACHE_IN = f"{OUT_DIR}/_cache_2to3_pit_20261116.pkl"
SUPP_IN = f"{OUT_DIR}/_cache_5m_supplement_bs.pkl"

sys.path.insert(0, OUT_DIR)
import exit_engine as ee


def fmt_row(res: dict, th: str) -> str:
    w_is = res[th]["IS_21_23"]
    w_ie = res[th]["IS_early"]
    w_il = res[th]["IS_late"]
    w_oo = res[th]["OOS_24_26"]
    w_5y = res[th]["5Y_211116"]
    return (
        f"{res['name']:34s} | IS:{w_is['trades']:2d}b {w_is['win_rate_pct']:5.1f}% PLR={w_is['plr']:4.2f} "
        f"NAV={w_is['nav']:5.2f}x MDD={w_is['max_dd_pct']:4.1f}%(E={w_ie['nav']:5.2f},L={w_il['nav']:4.2f}) | "
        f"OOS:{w_oo['trades']:2d}b {w_oo['win_rate_pct']:5.1f}% NAV={w_oo['nav']:5.2f}x MDD={w_oo['max_dd_pct']:4.1f}% | "
        f"5Y:{w_5y['nav']:6.2f}x EQ={w_5y['eq_nav']:6.2f}x T3={w_5y['trim3_nav']:5.2f}x MDD={w_5y['max_dd_pct']:4.1f}%"
    )


def main():
    d = pickle.load(open(CACHE_IN, "rb"))
    supp = pickle.load(open(SUPP_IN, "rb"))
    g = d["gated_all"]
    sub90 = g[g["score_v2"] >= 90].copy().reset_index(drop=True)
    codes90 = set(sub90["code"].astype(str).str.zfill(6))
    da = d["da_need"][d["da_need"]["c6"].isin(codes90)].copy()
    b5m1 = d["b5m_need"]
    b5m2 = {**b5m1, **supp["supp_5m"]}
    all_dts = d["all_dts"]
    dt_idx = {x: i for i, x in enumerate(all_dts)}
    idx_cache = json.load(open(IDX_JSON))
    csi_map = json.load(open(CSI_CANON_JSON))
    plook, stk_hist = ee.build_lookups(da)

    combos = [
        ee.ExitConfig("Base_V20"),
        ee.ExitConfig("C_1345_p85_d60", c_start_hhmm=1345, c_peak_th=0.085, c_drop_th=0.060),
        ee.ExitConfig("C_1345_p85_d65", c_start_hhmm=1345, c_peak_th=0.085, c_drop_th=0.065),
        ee.ExitConfig("C_1345_p80_d65", c_start_hhmm=1345, c_peak_th=0.080, c_drop_th=0.065),
        ee.ExitConfig("C_1345_p85_d70", c_start_hhmm=1345, c_peak_th=0.085, c_drop_th=0.070),
        ee.ExitConfig("C_1345_p85_d65+B1_85", hi_open_th=0.085, c_start_hhmm=1345, c_peak_th=0.085, c_drop_th=0.065),
        ee.ExitConfig("C_1345_p85_d65+B1_80", hi_open_th=0.080, c_start_hhmm=1345, c_peak_th=0.085, c_drop_th=0.065),
        ee.ExitConfig("C_1345_p85_d65+B2_b5_98", dbl_dev_buf=0.98, dbl_dev_min_board=5, c_start_hhmm=1345, c_peak_th=0.085, c_drop_th=0.065),
        ee.ExitConfig("C_1345_p85_d65+B2_b6_98", dbl_dev_buf=0.98, dbl_dev_min_board=6, c_start_hhmm=1345, c_peak_th=0.085, c_drop_th=0.065),
        ee.ExitConfig("C_1345_p85_d65+D_turn35", c_start_hhmm=1345, c_peak_th=0.085, c_drop_th=0.065, d_mode="yang_ge0_turn35"),
        ee.ExitConfig("C_1345_p85_d65+D_pct2", c_start_hhmm=1345, c_peak_th=0.085, c_drop_th=0.065, d_mode="yang_pct_ge2"),
        ee.ExitConfig("C_1345_p85_d65+D_no_imm", c_start_hhmm=1345, c_peak_th=0.085, c_drop_th=0.065, d_mode="no_imm"),
        ee.ExitConfig("C_d65+B1_85+D_turn35", hi_open_th=0.085, c_start_hhmm=1345, c_peak_th=0.085, c_drop_th=0.065, d_mode="yang_ge0_turn35"),
        ee.ExitConfig("C_d65+B2_b5_98+D_turn35", dbl_dev_buf=0.98, dbl_dev_min_board=5, c_start_hhmm=1345, c_peak_th=0.085, c_drop_th=0.065, d_mode="yang_ge0_turn35"),
    ]

    for tname, bmap in [("TRACK1_CANON_5M", b5m1), ("TRACK2_FULL_5M_BS", b5m2)]:
        print(f"\n==================== {tname} JOINT SYNTHESIS ====================")
        res_list = [ee.eval_variant(sub90, plook, stk_hist, bmap, all_dts, dt_idx, idx_cache["sh000002"], idx_cache["sz399107"], cfg, csi_map, th_list=(90, 96)) for cfg in combos]
        print("--- Std90 ---")
        for r in res_list:
            print(" ", fmt_row(r, "th_90"))
        print("--- Strict96 ---")
        for r in res_list:
            print(" ", fmt_row(r, "th_96"))

    # Inspect ALL Track 2 diffs for C_1345_p85_d65 vs Base_V20
    rb, edb, ehb, _ = ee.sim_exit_all(sub90, plook, stk_hist, b5m2, all_dts, dt_idx, idx_cache["sh000002"], idx_cache["sz399107"], combos[0])
    rc, edc, ehc, _ = ee.sim_exit_all(sub90, plook, stk_hist, b5m2, all_dts, dt_idx, idx_cache["sh000002"], idx_cache["sz399107"], combos[2])
    print("\n=== ALL Track 2 trade diffs: C_1345_p85_d65 vs Base_V20 ===")
    for i in range(len(sub90)):
        if abs(rc[i] - rb[i]) > 1e-6 or edc[i] != edb[i] or ehc[i] != ehb[i]:
            row = sub90.iloc[i]
            print(f"  {row.buy_date} {str(row.code).zfill(6)} {row.name} (sc={int(row.score_v2)},s3={row.sealed_3b}): "
                  f"Base {edb[i]}({ehb[i]}) {rb[i]*100:+.2f}% -> New {edc[i]}({ehc[i]}) {rc[i]*100:+.2f}% (diff={(rc[i]-rb[i])*100:+.2f}pp)")


if __name__ == "__main__":
    main()

#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Four-stage orthogonal exit scan for 二进三 V2.0 (s_2to3).
Runs ALL Stage A/B/C/D variants strictly calibrated on IS (2021-01-04 ~ 2023-12-31,
early/late IS check + parameter plateau), and compares Track 1 (Canonical 5m only)
vs Track 2 (100% 5m Complete with Baostock supplement).
"""
import os, sys, json, time, pickle
import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules

ROOT = "/Users/huaichuaibeimeng/claude-projects"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock/exit_opt_20261118/s2_2to3_exit"
IDX_JSON = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/index_klines_5y_cache.json"
CSI_CANON_JSON = f"{ROOT}/sim-portfolio/backtests_astock/clean_rebacktest_20261116/csi300_canonical_20261116.json"
CACHE_IN = f"{OUT_DIR}/_cache_2to3_pit_20261116.pkl"
SUPP_IN = f"{OUT_DIR}/_cache_5m_supplement_bs.pkl"

sys.path.insert(0, OUT_DIR)
import exit_engine as ee


def build_stage_configs() -> list[tuple[str, ee.ExitConfig]]:
    cfgs = [("BASE", ee.ExitConfig(name="Base_V20"))]

    # --- Stage A: Day3 Unsealed (~sealed_3b) ---
    cfgs += [
        ("A", ee.ExitConfig(name="A0_v10_cut05", unsealed_mode="v10_cut05")),
        ("A", ee.ExitConfig(name="A1a_vwap1030", unsealed_mode="vwap_1030")),
        ("A", ee.ExitConfig(name="A1b_vwap1000", unsealed_mode="vwap_1000")),
        ("A", ee.ExitConfig(name="A1c_vwap1100", unsealed_mode="vwap_1100")),
        ("A", ee.ExitConfig(name="A2a_vwap1030_ex1_xq_or_yin", unsealed_mode="vwap_1030_exempt_v1")),
        ("A", ee.ExitConfig(name="A2b_vwap1030_ex2_hot_or_rot", unsealed_mode="vwap_1030_exempt_v2")),
        ("A", ee.ExitConfig(name="A2c_vwap1030_ex3_d3yin", unsealed_mode="vwap_1030_exempt_v3")),
        ("A", ee.ExitConfig(name="A3a_d3_m3_0925", unsealed_mode="d3_stop_0925", d3_stop_pct=-0.03)),
        ("A", ee.ExitConfig(name="A3b_d3_m5_0925", unsealed_mode="d3_stop_0925", d3_stop_pct=-0.05)),
        ("A", ee.ExitConfig(name="A3c_d3_m7_0925", unsealed_mode="d3_stop_0925", d3_stop_pct=-0.07)),
        ("A", ee.ExitConfig(name="A3d_d3_dt_0925", unsealed_mode="d3_stop_0925", d3_stop_dt_only=True)),
        ("A", ee.ExitConfig(name="A3e_d3_m5_1030vw", unsealed_mode="d3_stop_1030_vwap", d3_stop_pct=-0.05)),
        ("A", ee.ExitConfig(name="A4a_tp4_c3o3", unsealed_mode="tp_limit", tp_pct=0.04, tp_cond="c3_gt_o3")),
        ("A", ee.ExitConfig(name="A4b_tp6_c3o3", unsealed_mode="tp_limit", tp_pct=0.06, tp_cond="c3_gt_o3")),
        ("A", ee.ExitConfig(name="A4c_tp8_c3o3", unsealed_mode="tp_limit", tp_pct=0.08, tp_cond="c3_gt_o3")),
        ("A", ee.ExitConfig(name="A4d_tp6_c3o3c2", unsealed_mode="tp_limit", tp_pct=0.06, tp_cond="c3_gt_o3_and_c2")),
        ("A", ee.ExitConfig(name="A4e_tp8_c3o3c2", unsealed_mode="tp_limit", tp_pct=0.08, tp_cond="c3_gt_o3_and_c2")),
    ]

    # --- Stage B: High Open + Double Severe Abnormal Volatility Buffer ---
    cfgs.append(("B1", ee.ExitConfig(name="B1_hi_off", hi_open_th=None)))
    for scope in ["d4_only", "all_boards"]:
        for th in [0.080, 0.085, 0.088, 0.090, 0.092, 0.095]:
            if scope == "d4_only" and th == 0.092:
                continue
            cfgs.append(("B1", ee.ExitConfig(name=f"B1_{scope}_{int(th*1000)}", hi_open_th=th, hi_open_scope=scope)))

    for mb in [3, 4, 5, 6]:
        for buf in [0.93, 0.96, 0.98]:
            cfgs.append(("B2", ee.ExitConfig(name=f"B2_b{mb}_buf{int(buf*100)}", dbl_dev_buf=buf, dbl_dev_min_board=mb)))

    # --- Stage C: Sealed Hold Intraday 5m Reconstruction ---
    cfgs += [
        ("C_special", ee.ExitConfig(name="C_1to2_vwap1030_rush1430", c_mode="1to2_vwap1030_rush1430", c_use_1030_vwap_in_1to2=True)),
        ("C_special", ee.ExitConfig(name="C_1to2_rush1430_no1030", c_mode="1to2_vwap1030_rush1430", c_use_1030_vwap_in_1to2=False)),
        ("C_special", ee.ExitConfig(name="C_rush1430_after_zt", c_mode="rush1430_after_zt")),
        ("C_special", ee.ExitConfig(name="C_eod_1500_only", c_mode="grid", c_start_hhmm=9999)),
    ]
    for sh in [1030, 1115, 1315, 1345, 1400, 1415, 1430]:
        for pk in [0.075, 0.080, 0.085, 0.090, "zt"]:
            for dr in [0.020, 0.035, 0.050, 0.065, "vwap", "draw4"]:
                if sh == 1345 and pk == 0.085 and dr == 0.050:
                    continue
                pk_s = "zt" if pk == "zt" else f"p{int(pk*1000)}"
                dr_s = str(dr) if isinstance(dr, str) else f"d{int(dr*1000)}"
                cfgs.append(("C_grid", ee.ExitConfig(name=f"Cg_{sh}_{pk_s}_{dr_s}", c_mode="grid", c_start_hhmm=sh, c_peak_th=pk, c_drop_th=dr)))

    # --- Stage D: Immunity Conditions ---
    for dm in ["true_yang_any", "pct_ge2", "yang_pct_ge2", "yang_ge_m3", "yang_ge0_turn35", "yang_turn35", "yang_real_turn35", "no_imm"]:
        cfgs.append(("D", ee.ExitConfig(name=f"D_{dm}", d_mode=dm)))

    return cfgs


def summarize_is_line(res: dict, th: str = "th_90") -> str:
    w_is = res[th]["IS_21_23"]
    w_ie = res[th]["IS_early"]
    w_il = res[th]["IS_late"]
    w_oos = res[th]["OOS_24_26"]
    w_5y = res[th]["5Y_211116"]
    return (
        f"{res['name']:28s} | IS:{w_is['trades']:2d}b {w_is['win_rate_pct']:5.1f}% PLR={w_is['plr']:4.2f} "
        f"NAV={w_is['nav']:6.2f}x MDD={w_is['max_dd_pct']:5.1f}% (E={w_ie['nav']:4.2f}x L={w_il['nav']:4.2f}x) | "
        f"[OOS:{w_oos['trades']:2d}b {w_oos['win_rate_pct']:5.1f}% NAV={w_oos['nav']:5.2f}x MDD={w_oos['max_dd_pct']:5.1f}% | "
        f"5Y:{w_5y['nav']:6.2f}x EQ={w_5y['eq_nav']:6.2f}x MDD={w_5y['max_dd_pct']:5.1f}%]"
    )


def run_track(track_name: str, sub86: pd.DataFrame, plook: dict, stk_hist: dict, b5m: dict, all_dts: list, dt_idx: dict, idx_sh: dict, idx_sz: dict, csi_map: dict, cfgs: list):
    t0 = time.time()
    results = []
    for stage, cfg in cfgs:
        r = ee.eval_variant(sub86, plook, stk_hist, b5m, all_dts, dt_idx, idx_sh, idx_sz, cfg, csi_map, th_list=(90, 96))
        r["stage"] = stage
        results.append(r)
    print(f"\n==================== {track_name} ({len(results)} variants in {time.time()-t0:.1f}s) ====================")
    base_res = results[0]
    print("BASELINE:", summarize_is_line(base_res, "th_90"))
    print("BASE_96 :", summarize_is_line(base_res, "th_96"))

    # Print Stage A, B1, B2, C_special, top C_grid on IS (sorted by IS Sharpe/Calmar proxy = nav / max(1, mdd)), D
    for stg in ["A", "B1", "B2", "C_special", "D"]:
        print(f"\n--- {track_name} Stage {stg} (Std90) ---")
        rows = [x for x in results if x["stage"] == stg]
        for x in rows:
            print(" ", summarize_is_line(x, "th_90"))

    # Top 15 of Stage C_grid sorted by IS nav and IS Calmar (nav / mdd)
    c_grid = [x for x in results if x["stage"] == "C_grid"]
    c_by_nav = sorted(c_grid, key=lambda x: (x["th_90"]["IS_21_23"]["nav"], -x["th_90"]["IS_21_23"]["max_dd_pct"]), reverse=True)
    print(f"\n--- {track_name} Stage C_grid Top 15 by IS NAV (Std90) ---")
    for x in c_by_nav[:15]:
        print(" ", summarize_is_line(x, "th_90"))
    c_by_mdd = sorted(c_grid, key=lambda x: (x["th_90"]["IS_21_23"]["nav"] / max(5.0, x["th_90"]["IS_21_23"]["max_dd_pct"])), reverse=True)
    print(f"\n--- {track_name} Stage C_grid Top 15 by IS NAV/MDD (Std90) ---")
    for x in c_by_mdd[:15]:
        print(" ", summarize_is_line(x, "th_90"))

    return results


def main():
    d = pickle.load(open(CACHE_IN, "rb"))
    g = d["gated_all"]
    da = d["da_need"]
    b5m_canon = d["b5m_need"]
    all_dts = d["all_dts"]
    dt_idx = {x: i for i, x in enumerate(all_dts)}

    idx_cache = json.load(open(IDX_JSON, encoding="utf-8"))
    idx_sh = idx_cache["sh000002"]
    idx_sz = idx_cache["sz399107"]
    csi_map = json.load(open(CSI_CANON_JSON, encoding="utf-8"))

    plook, stk_hist = ee.build_lookups(da)
    sub90 = g[g["score_v2"] >= 90].copy().reset_index(drop=True)
    cfgs = build_stage_configs()
    print(f"Total exit configs to scan: {len(cfgs)} | sub90 signals={len(sub90)}")

    # Verify Track 1 baseline 0.0 match against upgrade_2to3_pit.py
    rets_b, eds_b, ehs_b, st_b = ee.sim_exit_all(sub90, plook, stk_hist, b5m_canon, all_dts, dt_idx, idx_sh, idx_sz, cfgs[0][1])
    max_d = float(np.max(np.abs(np.array(rets_b) - sub90["ret_v2"].to_numpy())))
    assert max_d < 1e-13 and list(eds_b) == list(sub90["ed_v2"]) and list(ehs_b) == list(sub90["eh_v2"]), f"Baseline diff: {max_d}"
    print(f"[VERIFIED] exit_engine Base_V20 matches upgrade_2to3_pit.py on all {len(sub90)} >=90 signals (max_diff={max_d:.2e})")

    res_t1 = run_track("TRACK1_CANON_5M", sub90, plook, stk_hist, b5m_canon, all_dts, dt_idx, idx_sh, idx_sz, csi_map, cfgs)

    res_t2 = None
    if os.path.exists(SUPP_IN):
        supp_pkg = pickle.load(open(SUPP_IN, "rb"))
        b5m_full = {**b5m_canon, **supp_pkg["supp_5m"]}
        res_t2 = run_track("TRACK2_FULL_5M_BS", sub90, plook, stk_hist, b5m_full, all_dts, dt_idx, idx_sh, idx_sz, csi_map, cfgs)

    with open(f"{OUT_DIR}/stage_scan_results.pkl", "wb") as f:
        pickle.dump({"track1": res_t1, "track2": res_t2}, f)
    print(f"\nSaved full stage scan results to {OUT_DIR}/stage_scan_results.pkl")


if __name__ == "__main__":
    main()

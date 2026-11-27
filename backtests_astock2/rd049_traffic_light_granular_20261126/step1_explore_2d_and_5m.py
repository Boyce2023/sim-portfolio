#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD049 Step 1: Comprehensive Exploration of 5-Tier Traffic Lights, 2D R_risk, Dynamic Thresholds, and 3to4 5m Tightening."""
import os
import pickle
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
assert "yfinance" not in sys.modules
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
RD038 = f"{SIM}/backtests_astock2/rd038_grand_bundle_assembly_20261126"
RD049 = f"{SIM}/backtests_astock2/rd049_traffic_light_granular_20261126"
sys.path.insert(0, RD038)
import _rd038_engine as eng


def build_2d_states(reg: pd.DataFrame) -> pd.DataFrame:
    df = reg.copy()
    # Continuous Dimension X: Breakdown Slope Stress in [0, 100] (excluding Red Floor bounce zone via separate flag)
    x_ma20 = np.clip((-1.0 - df["gz_vs_ma20_t1"].fillna(0.0)) / 6.0, 0.0, 1.0)
    x_dd20 = np.clip((-3.0 - df["gz_dd20_t1"].fillna(0.0)) / 9.0, 0.0, 1.0)
    x_r5 = np.clip((-1.5 - df["gz_r5_t1"].fillna(0.0)) / 6.0, 0.0, 1.0)
    x_r10 = np.clip((-2.0 - df["gz_r10_t1"].fillna(0.0)) / 8.0, 0.0, 1.0)
    x_med5 = np.clip((-1.5 - df["alla_med_r5_t1"].fillna(0.0)) / 5.5, 0.0, 1.0)
    df["X_score"] = (0.25 * x_ma20 + 0.25 * x_dd20 + 0.20 * x_r5 + 0.15 * x_r10 + 0.15 * x_med5) * 100.0

    # Continuous Dimension Y: High-Board Micro Infighting Temperature in [0, 100]
    y_prm = np.clip((0.40 - df["hb2_promo_t1"].fillna(0.40)) / 0.25, 0.0, 1.0)
    y_dam = np.clip((df["hb2_dam5_rate_t1"].fillna(0.15) - 0.15) / 0.30, 0.0, 1.0)
    y_pbop = np.clip((-2.0 - df["pb_hb2_fail_open_t1"].fillna(-2.0)) / 4.5, 0.0, 1.0)
    y_zb = np.clip((df["zb_rate_t1"].fillna(30.0) - 30.0) / 18.0, 0.0, 1.0)
    y_dt = np.clip((df["dt_cnt_t1"].fillna(5.0) - 5.0) / 20.0, 0.0, 1.0)
    df["Y_score"] = (0.25 * y_prm + 0.20 * y_dam + 0.25 * y_pbop + 0.15 * y_zb + 0.15 * y_dt) * 100.0

    # Red Floor physical detector (capitulation oversold zone: MUST NOT BLOCK)
    df["is_red_floor"] = (
        (df["gz_dd20_t1"] <= -13.5) | (df["gz_r10_t1"] <= -11.5) | (df["gz_r5_t1"] <= -8.5)
    ).fillna(False)

    # 2D Continuous Risk Score R_risk in [0, 100] (dampened when is_red_floor unless extreme)
    df["R_risk"] = 0.55 * df["X_score"] + 0.45 * df["Y_score"]

    # 5-Tier Traffic Light
    def classify_5tier(r):
        if r["is_red_floor"]:
            return "L5_红灯地板"
        if r["gz_vs_ma20_t1"] < -3.5 or r["gz_dd20_t1"] <= -7.0 or r["gz_r5_t1"] <= -5.0 or r["gz_r10_t1"] <= -7.0:
            return "L4_深黄主跌"
        if r["gz_vs_ma20_t1"] < -1.5 or r["gz_dd20_t1"] <= -4.5 or r["alla_med_r5_t1"] <= -3.0:
            return "L3_浅黄预警"
        if r["Y_score"] >= 45.0:
            return "L2_绿灯内杀"
        return "L1_纯绿畅通"

    df["light_5"] = df.apply(classify_5tier, axis=1)
    return df


def eval_fast(cache: dict, cfg: dict, reg_map: dict, light_map: dict, rrisk_map: dict, x_map: dict, y_map: dict,
              rule_fn=None, size_fn=None, label: str = "") -> dict:
    """Fast simulation with optional pre-market score adjustment / mask / sizing."""
    # Deep copy only pools_ext
    c2 = {**cache, "pools_ext": {k: v.copy() for k, v in cache["pools_ext"].items()}}
    if rule_fn is not None:
        rule_fn(c2, reg_map, light_map, rrisk_map, x_map, y_map)
    sim = eng.run_bundle_sim(c2, cfg, fee_mode="030")
    cal = c2["cal_5y"]
    dr = sim["dr_5y"]
    if size_fn is not None:
        # Scale daily return on active days (assuming cash earns 0)
        mult = np.array([size_fn(d) for d in cal], dtype=float)
        dr = dr * mult

    tr = sim["trades_df"]

    def wstats(sdt, edt):
        pos = [i for i, d in enumerate(cal) if sdt <= d <= edt]
        dsub = dr[pos]
        nav = float(np.prod(1.0 + dsub))
        curve = np.concatenate([[1.0], np.cumprod(1.0 + dsub)])
        pk = np.maximum.accumulate(curve)
        mdd = float(np.max((pk - curve) / pk) * 100.0)
        sd = float(np.std(dsub, ddof=1))
        sh = float(np.mean(dsub) / sd * np.sqrt(242.0)) if sd > 1e-12 else 0.0
        tsub = tr[tr["buy_date"].between(sdt, edt)] if not tr.empty else tr
        wr = float((tsub["net_ret"] > 0).mean() * 100.0) if not tsub.empty else 0.0
        return {"n": len(tsub), "wr": round(wr, 1), "nav": nav, "mdd": round(mdd, 2), "sh": round(sh, 3)}

    return {
        "label": label,
        "FULL_5Y": wstats("2021-11-16", "2026-11-16"),
        "IS_2123": wstats("2021-11-16", "2023-12-31"),
        "OOS_2426": wstats("2024-01-01", "2026-11-16"),
        "WF_2326": wstats("2023-01-03", "2026-11-16"),
        "Y2026": wstats("2026-01-01", "2026-11-16"),
        "Y26H2": wstats("2026-07-01", "2026-11-16"),
        "trades_df": tr,
    }


def main():
    with open(f"{RD038}/_cache/rd038_master_cache.pkl", "rb") as f:
        cache = pickle.load(f)
    reg = pd.read_parquet(f"{RD049}/_cache/rd049_daily_regime_pit.parquet")
    reg_2d = build_2d_states(reg)
    reg_5y = reg_2d[reg_2d["trade_date"].between("2021-11-16", "2026-11-16")].copy()
    print("=== 5-Tier Traffic Light Day Distribution (1212 trading days) ===")
    print(reg_5y["light_5"].value_counts().to_dict())

    reg_idx = reg_2d.set_index("trade_date")
    light_map = reg_idx["light_5"].to_dict()
    rrisk_map = reg_idx["R_risk"].to_dict()
    x_map = reg_idx["X_score"].to_dict()
    y_map = reg_idx["Y_score"].to_dict()
    reg_map = reg_idx.to_dict("index")

    cfg_v21 = {"s20": "stack_c50_avg", "s34": "m4_4way_bl15", "s23": "m2_pair_cold45_d15", "shi": "m1_causal_cold_drop40_t0", "spr": "base", "s12": "base", "w2a5": "none", "w2a6": "s_tier_reserve_only"}
    cfg_v20 = {"s20": "base_76", "s34": "base", "s23": "base", "shi": "base", "spr": "base", "s12": "base", "w2a5": "none", "w2a6": "s_tier_reserve_only"}

    # 1. Print 6 Strategies x 5-Tier Traffic Lights (Standalone V21 Pool)
    pool6, _ = eng.build_bundle_pools(cache, cfg_v21, fee_mode="030")
    pool6["light_5"] = pool6["buy_date"].map(light_map)
    print("\n=== 6 Strategies x 5-Tier Traffic Lights (Standalone V21 Candidates, IS vs OOS) ===")
    for st in ["3to4", "high", "pry", "2to3", "1to2", "20cm"]:
        print(f"Strategy [{st}]:")
        sub = pool6[pool6["strategy"] == st]
        for l5 in ["L1_纯绿畅通", "L2_绿灯内杀", "L3_浅黄预警", "L4_深黄主跌", "L5_红灯地板"]:
            g = sub[sub["light_5"] == l5]
            gis = g[g["buy_date"] < "2024-01-01"]
            goos = g[g["buy_date"] >= "2024-01-01"]
            def sfmt(d):
                if d.empty: return "n= 0"
                r = d["net_ret"]
                return f"n={len(d):2d} wr={(r>0).mean()*100:4.0f}% mn={r.mean()*100:+5.1f}% min={r.min()*100:+5.1f}%"
            print(f"  {l5}: ALL[{sfmt(g)}] | IS[{sfmt(gis)}] | OOS[{sfmt(goos)}]")

    # 2. Test Candidate Dynamic Threshold & Regime Rules on V21 (BOTH FULL & DE-SINGLETON!)
    def make_3to4_rule(mode: str, param: float = 0.0):
        def _fn(c2, rmap, lmap, rrk, xm, ym):
            df34 = c2["pools_ext"]["3to4"]
            dts = df34["buy_date"].astype(str).str[:10].tolist()
            l5s = [lmap.get(d, "L1_纯绿畅通") for d in dts]
            rrs = np.array([rrk.get(d, 0.0) for d in dts])
            ys = np.array([ym.get(d, 0.0) for d in dts])
            xs = np.array([xm.get(d, 0.0) for d in dts])
            reds = np.array([rmap.get(d, {}).get("is_red_floor", False) for d in dts])
            sc = df34["orig_score"].to_numpy(float).copy()
            keep = df34["can_buy_hygiene"].to_numpy(bool).copy()

            if mode == "skip_L4":
                keep &= np.array([x != "L4_深黄主跌" for x in l5s])
            elif mode == "skip_L3_L4":
                keep &= np.array([x not in ("L3_浅黄预警", "L4_深黄主跌") for x in l5s])
            elif mode == "skip_L2_L4":
                keep &= np.array([x not in ("L2_绿灯内杀", "L4_深黄主跌") for x in l5s])
            elif mode == "skip_L2_L3_L4":
                keep &= np.array([x not in ("L2_绿灯内杀", "L3_浅黄预警", "L4_深黄主跌") for x in l5s])
            elif mode == "raise_L4_L3_L2":
                # Raise orig_score threshold dynamically by deducting penalty from orig_score (equivalent to raising threshold!)
                # Wait: raising thr from 90 to 90+delta == deducting delta from score, BUT wait: S tier threshold is 102!
                # Better: block if orig_score < 90 + delta, keeping tier intact if it passes!
                deltas = np.where(np.array(l5s) == "L4_深黄主跌", param,
                         np.where(np.array(l5s) == "L3_浅黄预警", param * 0.75,
                         np.where(np.array(l5s) == "L2_绿灯内杀", param * 0.75, 0.0)))
                keep &= (sc >= 90.0 + deltas)
            elif mode == "raise_L4_L2":
                deltas = np.where(np.array(l5s) == "L4_深黄主跌", param,
                         np.where(np.array(l5s) == "L2_绿灯内杀", param * 0.75, 0.0))
                keep &= (sc >= 90.0 + deltas)
            elif mode == "rrisk_linear":
                # Dynamic threshold: if not red_floor and R_risk > 35: thr = 90 + param * (R_risk - 35) / 30
                thr = np.where((~reds) & (rrs > 35.0), 90.0 + param * (rrs - 35.0) / 30.0, 90.0)
                keep &= (sc >= thr)
            elif mode == "rrisk_hard":
                # Hard skip if not red_floor and R_risk >= param
                keep &= ~((~reds) & (rrs >= param))
            elif mode == "rrisk_plus_pry_cold":
                thr = np.where((~reds) & (rrs > 35.0), 90.0 + param * (rrs - 35.0) / 30.0, 90.0)
                keep &= (sc >= thr)
                dfpr = c2["pools_ext"]["pry"]
                dfpr["can_buy_hygiene"] = dfpr["can_buy_hygiene"].to_numpy(bool) & (dfpr["mkt10_zt_est_t1"].to_numpy(float) >= 50.0)
            df34["can_buy_hygiene"] = keep
        return _fn

    def make_multi_rule(s34_mode: str, s34_param: float, skip_12_L4: bool = False, skip_pry_cold: bool = False, boost_20cm_L4: bool = False):
        f34 = make_3to4_rule(s34_mode, s34_param)
        def _fn(c2, rmap, lmap, rrk, xm, ym):
            f34(c2, rmap, lmap, rrk, xm, ym)
            if skip_12_L4:
                d12 = c2["pools_ext"]["1to2"]
                m12 = np.array([lmap.get(str(d)[:10], "L1") != "L4_深黄主跌" for d in d12["buy_date"]])
                d12["can_buy_hygiene"] = d12["can_buy_hygiene"].to_numpy(bool) & m12
            if skip_pry_cold:
                dfpr = c2["pools_ext"]["pry"]
                dfpr["can_buy_hygiene"] = dfpr["can_buy_hygiene"].to_numpy(bool) & (dfpr["mkt10_zt_est_t1"].to_numpy(float) >= 50.0)
        return _fn

    tests = [
        ("BASE_V21", None, None),
        ("3to4_skip_L4", make_3to4_rule("skip_L4"), None),
        ("3to4_skip_L3_L4", make_3to4_rule("skip_L3_L4"), None),
        ("3to4_skip_L2_L4", make_3to4_rule("skip_L2_L4"), None),
        ("3to4_skip_L2_L3_L4", make_3to4_rule("skip_L2_L3_L4"), None),
        ("3to4_raise_d8_L4L3L2", make_3to4_rule("raise_L4_L3_L2", 8.0), None),
        ("3to4_raise_d10_L4L3L2", make_3to4_rule("raise_L4_L3_L2", 10.0), None),
        ("3to4_raise_d12_L4L3L2", make_3to4_rule("raise_L4_L3_L2", 12.0), None),
        ("3to4_raise_d10_L4L2", make_3to4_rule("raise_L4_L2", 10.0), None),
        ("3to4_rrisk_lin_8", make_3to4_rule("rrisk_linear", 8.0), None),
        ("3to4_rrisk_lin_10", make_3to4_rule("rrisk_linear", 10.0), None),
        ("3to4_rrisk_lin_12", make_3to4_rule("rrisk_linear", 12.0), None),
        ("3to4_rrisk_hard_45", make_3to4_rule("rrisk_hard", 45.0), None),
        ("3to4_rrisk_hard_50", make_3to4_rule("rrisk_hard", 50.0), None),
        ("3to4_rrisk_hard_55", make_3to4_rule("rrisk_hard", 55.0), None),
        ("3to4_skipL2L4_pryCold", make_multi_rule("skip_L2_L4", 0, False, True), None),
        ("3to4_rrisk50_pryCold", make_multi_rule("rrisk_hard", 50.0, False, True), None),
        ("3to4_rriskLin10_12L4_pryCold", make_multi_rule("rrisk_linear", 10.0, True, True), None),
        ("3to4_skipL4_12L4_pryCold", make_multi_rule("skip_L4", 0, True, True), None),
        ("CTRL_Const65_Size", None, lambda d: 0.65),
    ]

    # Build De-Singleton cache (removing 2025-01-03 600778 & 2024-12-23 603421)
    cache_ds = {**cache, "pools_ext": {k: v.copy() for k, v in cache["pools_ext"].items()}}
    p34_ds = cache_ds["pools_ext"]["3to4"]
    m_ds = ((p34_ds["buy_date"] == "2025-01-03") & (p34_ds["code"] == "600778")) | ((p34_ds["buy_date"] == "2024-12-23") & (p34_ds["code"] == "603421"))
    p34_ds.loc[m_ds, "can_buy_hygiene"] = False

    print("\n=== V21 Portfolio Simulation Comparison (FULL vs DE-SINGLETON) ===")
    hdr = f"{'Rule':28s} | {'5Y_MDD':6s} {'5Y_Sh':5s} {'5Y_NAV':11s} | {'IS_MDD':6s} {'IS_Sh':5s} | {'OOS_MDD':7s} {'OOS_Sh':6s} | {'26_NAV':7s} | {'DS_5Y_MDD':9s} {'DS_OOS_MDD':10s} {'DS_5Y_Sh':8s}"
    print(hdr)
    for lbl, rfn, sfn in tests:
        res_f = eval_fast(cache, cfg_v21, reg_map, light_map, rrisk_map, x_map, y_map, rfn, sfn, lbl)
        res_d = eval_fast(cache_ds, cfg_v21, reg_map, light_map, rrisk_map, x_map, y_map, rfn, sfn, lbl)
        f5, fis, foos, f26 = res_f["FULL_5Y"], res_f["IS_2123"], res_f["OOS_2426"], res_f["Y2026"]
        d5, doos = res_d["FULL_5Y"], res_d["OOS_2426"]
        print(f"{lbl:28s} | {f5['mdd']:5.2f}% {f5['sh']:5.3f} {f5['nav']:11,.1f} | {fis['mdd']:5.2f}% {fis['sh']:5.3f} | {foos['mdd']:6.2f}% {foos['sh']:6.3f} | {f26['nav']:6.2f}x | {d5['mdd']:8.2f}% {doos['mdd']:9.2f}% {d5['sh']:8.3f}")


if __name__ == "__main__":
    main()

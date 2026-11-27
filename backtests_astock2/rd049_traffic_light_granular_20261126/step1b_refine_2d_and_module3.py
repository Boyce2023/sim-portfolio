#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD049 Step 1B: Honest Grid Exploration of 2D State Machine, Dynamic Thresholds, and Module 3 5m Tightening."""
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
sys.path.insert(0, RD049)
import _rd038_engine as eng


def build_2d_v2(reg: pd.DataFrame, y_cut: float = 42.0, x_sh: float = 20.0, x_dp: float = 42.0) -> pd.DataFrame:
    df = reg.copy()
    # X: Macro breakdown slope stress in [0, 100] (5 zero-free-degree physical components)
    x_ma20 = np.clip((-1.0 - df["gz_vs_ma20_t1"].fillna(0.0)) / 5.5, 0.0, 1.0)
    x_dd20 = np.clip((-3.0 - df["gz_dd20_t1"].fillna(0.0)) / 8.5, 0.0, 1.0)
    x_r5 = np.clip((-1.5 - df["gz_r5_t1"].fillna(0.0)) / 5.5, 0.0, 1.0)
    x_r10 = np.clip((-2.0 - df["gz_r10_t1"].fillna(0.0)) / 7.5, 0.0, 1.0)
    x_med5 = np.clip((-1.5 - df["alla_med_r5_t1"].fillna(0.0)) / 5.0, 0.0, 1.0)
    df["X_score"] = (0.25 * x_ma20 + 0.25 * x_dd20 + 0.20 * x_r5 + 0.15 * x_r10 + 0.15 * x_med5) * 100.0

    # Y: Short-term High-Board Infighting Micro Temperature in [0, 100]
    # Uses 5 equal-weight physical stress gauges:
    # 1. hb2_promo_t1 low (0.40 -> 0.18)
    # 2. L1_duanban_damian_t1 high (15% -> 40%)
    # 3. pb_hb2_fail_open_t1 deep low open (-2% -> -6%)
    # 4. zb_rate_t1 high (30% -> 46%)
    # 5. dt_cnt_t1 high (5 -> 20)
    y_prm = np.clip((0.40 - df["hb2_promo_t1"].fillna(0.40)) / 0.22, 0.0, 1.0)
    y_dbm = np.clip((df["L1_duanban_damian_t1"].fillna(15.0) - 15.0) / 25.0, 0.0, 1.0)
    y_pb = np.clip((-2.0 - df["pb_hb2_fail_open_t1"].fillna(-2.0)) / 4.0, 0.0, 1.0)
    y_zb = np.clip((df["zb_rate_t1"].fillna(30.0) - 30.0) / 16.0, 0.0, 1.0)
    y_dt = np.clip((df["dt_cnt_t1"].fillna(5.0) - 5.0) / 15.0, 0.0, 1.0)
    df["Y_score"] = (0.20 * y_prm + 0.20 * y_dbm + 0.20 * y_pb + 0.20 * y_zb + 0.20 * y_dt) * 100.0

    df["is_red_floor"] = (
        (df["gz_dd20_t1"] <= -13.5) | (df["gz_r10_t1"] <= -11.5) | (df["gz_r5_t1"] <= -8.5)
    ).fillna(False)

    df["R_risk"] = 0.55 * df["X_score"] + 0.45 * df["Y_score"]

    def cls5(r):
        if r["is_red_floor"]:
            return "L5_红灯地板"
        if r["X_score"] >= x_dp:
            return "L4_深黄主跌"
        if r["X_score"] >= x_sh:
            return "L3_浅黄预警"
        if r["Y_score"] >= y_cut:
            return "L2_绿灯内杀"
        return "L1_纯绿畅通"

    df["light_5"] = df.apply(cls5, axis=1)
    return df


def main():
    with open(f"{RD038}/_cache/rd038_master_cache.pkl", "rb") as f:
        cache = pickle.load(f)
    reg = pd.read_parquet(f"{RD049}/_cache/rd049_daily_regime_pit.parquet")
    f5 = pd.read_parquet(f"{SIM}/data/all_strategies_5m_complete_pit.parquet")
    f5["dt"] = f5["date"].astype(str).str[:10]

    # Precompute honest 5m execution map for 3to4 (explicitly blocking if sealed at 09:40!)
    df34_raw = cache["pools_ext"]["3to4"]
    b5_info = {}
    for r in df34_raw[df34_raw["orig_score"] >= 90].itertuples():
        bars = f5[(f5["c6"] == str(r.code).zfill(6)) & (f5["dt"] == r.buy_date)].sort_values("hhmm_int")
        if bars.empty:
            continue
        b935 = bars[bars["hhmm_int"] == 935].iloc[0]
        b940 = bars[bars["hhmm_int"] == 940].iloc[0] if not bars[bars["hhmm_int"] == 940].empty else b935
        o935, c935 = float(b935["open"]), float(b935["close"])
        o940, l940 = float(b940["open"]), float(b940["low"])
        pc = o935 / (1.0 + float(r.open_pct))
        zt_approx = round(pc * 1.10, 2)
        sealed_940 = (o940 >= zt_approx - 0.015) and (l940 >= zt_approx - 0.015)
        b5_info[(r.buy_date, str(r.code).zfill(6))] = {
            "red935": c935 < o935,
            "sealed_940": sealed_940,
            "o940": o940,
        }

    reg2 = build_2d_v2(reg, y_cut=42.0, x_sh=20.0, x_dp=42.0)
    r5y = reg2[reg2["trade_date"].between("2021-11-16", "2026-11-16")]
    print("V2 5-tier day counts:", r5y["light_5"].value_counts().to_dict())
    r_idx = reg2.set_index("trade_date")
    for dt, nm in [("2025-01-03", "友好"), ("2024-12-23", "鼎信"), ("2022-07-22", "法尔胜"), ("2022-07-26", "大港"), ("2022-03-10", "时代"), ("2024-01-05", "长白山"), ("2024-02-05", "登云")]:
        row = r_idx.loc[dt]
        print(f"  {dt} {nm:5s}: {row['light_5']} X={row['X_score']:4.1f} Y={row['Y_score']:4.1f} R={row['R_risk']:4.1f}")

    lmap = r_idx["light_5"].to_dict()
    rmap = r_idx.to_dict("index")
    cfg_v21 = {"s20": "stack_c50_avg", "s34": "m4_4way_bl15", "s23": "m2_pair_cold45_d15", "shi": "m1_causal_cold_drop40_t0", "spr": "base", "s12": "base", "w2a5": "none", "w2a6": "s_tier_reserve_only"}
    cfg_v20 = {"s20": "base_76", "s34": "base", "s23": "base", "shi": "base", "spr": "base", "s12": "base", "w2a5": "none", "w2a6": "s_tier_reserve_only"}

    cache_ds = {**cache, "pools_ext": {k: v.copy() for k, v in cache["pools_ext"].items()}}
    p34_ds = cache_ds["pools_ext"]["3to4"]
    p34_ds.loc[((p34_ds["buy_date"] == "2025-01-03") & (p34_ds["code"] == "600778")) | ((p34_ds["buy_date"] == "2024-12-23") & (p34_ds["code"] == "603421")), "can_buy_hygiene"] = False

    def run_cfg(c_src, cfg, d_l4, d_l3, d_l2, r_cut=None, pry_cold=True, s34_925_in_weak=False, s34_af03_in_weak=False, honest_delay935=False, s12_skip_l4=False):
        c2 = {**c_src, "pools_ext": {k: v.copy() for k, v in c_src["pools_ext"].items()}}
        d34 = c2["pools_ext"]["3to4"]
        keep = d34["can_buy_hygiene"].to_numpy(bool).copy()
        sc = d34["orig_score"].to_numpy(float)
        dts = d34["buy_date"].astype(str).str[:10].tolist()
        l5s = np.array([lmap.get(d, "L1_纯绿畅通") for d in dts])
        rrs = np.array([rmap.get(d, {}).get("R_risk", 0.0) for d in dts])
        reds = np.array([rmap.get(d, {}).get("is_red_floor", False) for d in dts])

        if r_cut is not None:
            # Continuous R_risk threshold raise or block
            deltas = np.where((~reds) & (rrs >= r_cut), d_l4, 0.0)
        else:
            deltas = np.where(l5s == "L4_深黄主跌", d_l4, np.where(l5s == "L3_浅黄预警", d_l3, np.where(l5s == "L2_绿灯内杀", d_l2, 0.0)))
        keep &= (sc >= 90.0 + deltas)

        weak_mask = np.isin(l5s, ["L2_绿灯内杀", "L3_浅黄预警", "L4_深黄主跌"])
        if s34_925_in_weak:
            keep &= (~weak_mask) | (d34["buy_hhmm"].to_numpy(int) == 925)
        if s34_af03_in_weak:
            keep &= (~weak_mask) | (d34["s34_af_03"].to_numpy(float) == 4.0)
        if honest_delay935:
            # Honest 5m delay: if intraday buy (hh==935), must NOT be red935 AND NOT sealed_at_940 (or else unfillable!)
            bhs = d34["buy_hhmm"].to_numpy(int)
            codes = d34["code"].astype(str).str.zfill(6).tolist()
            n_rets = d34["net_ret_030"].to_numpy(float).copy()
            mtms = list(d34["mtm_5y_030"])
            for i in range(len(d34)):
                if not keep[i] or bhs[i] != 935:
                    continue
                info = b5_info.get((dts[i], codes[i]))
                if info is None:
                    continue
                if info["red935"] or info["sealed_940"]:
                    keep[i] = False
                else:
                    old_px = float(d34.iloc[i]["buy_price"]) if pd.notna(d34.iloc[i]["buy_price"]) else info["o940"]
                    new_px = info["o940"]
                    if old_px > 0 and new_px > 0:
                        n_rets[i] = (1.0 + n_rets[i]) * (old_px / new_px) - 1.0
                        segs = list(mtms[i])
                        if segs:
                            segs[0] = (segs[0][0], segs[0][1] * (old_px / new_px))
                            mtms[i] = tuple(segs)
            d34["net_ret_030"] = n_rets
            d34["mtm_5y_030"] = mtms

        d34["can_buy_hygiene"] = keep
        if pry_cold:
            dp = c2["pools_ext"]["pry"]
            dp["can_buy_hygiene"] = dp["can_buy_hygiene"].to_numpy(bool) & (dp["mkt10_zt_est_t1"].to_numpy(float) >= 50.0)
        if s12_skip_l4:
            d12 = c2["pools_ext"]["1to2"]
            m12 = np.array([lmap.get(str(d)[:10], "L1") != "L4_深黄主跌" for d in d12["buy_date"]])
            d12["can_buy_hygiene"] = d12["can_buy_hygiene"].to_numpy(bool) & m12

        sim = eng.run_bundle_sim(c2, cfg, fee_mode="030")
        cal = c2["cal_5y"]
        dr = sim["dr_5y"]
        tr = sim["trades_df"]
        def ws(s, e):
            pos = [i for i, d in enumerate(cal) if s <= d <= e]
            dsub = dr[pos]
            nav = float(np.prod(1.0 + dsub))
            cv = np.concatenate([[1.0], np.cumprod(1.0 + dsub)])
            pk = np.maximum.accumulate(cv)
            mdd = float(np.max((pk - cv) / pk) * 100.0)
            sd = float(np.std(dsub, ddof=1))
            sh = float(np.mean(dsub) / sd * np.sqrt(242.0)) if sd > 1e-12 else 0.0
            ts = tr[tr["buy_date"].between(s, e)]
            return {"n": len(ts), "nav": nav, "mdd": round(mdd, 2), "sh": round(sh, 3)}
        return {"5Y": ws("2021-11-16", "2026-11-16"), "IS": ws("2021-11-16", "2023-12-31"), "OOS": ws("2024-01-01", "2026-11-16"), "Y26": ws("2026-01-01", "2026-11-16")}

    specs = [
        ("BASE", dict(d_l4=0, d_l3=0, d_l2=0, pry_cold=False)),
        ("T1_d10_L4_8L3_8L2", dict(d_l4=10, d_l3=8, d_l2=8, pry_cold=True)),
        ("T2_d12_L4_9L3_9L2", dict(d_l4=12, d_l3=9, d_l2=9, pry_cold=True)),
        ("T3_d14_L4_10L3_10L2", dict(d_l4=14, d_l3=10, d_l2=10, pry_cold=True)),
        ("T4_skipL4_d10L3_d10L2", dict(d_l4=99, d_l3=10, d_l2=10, pry_cold=True)),
        ("T5_skipL2L4_d10L3", dict(d_l4=99, d_l3=10, d_l2=99, pry_cold=True)),
        ("T6_skipL2L3L4", dict(d_l4=99, d_l3=99, d_l2=99, pry_cold=True)),
        ("T7_R40_skip34", dict(d_l4=99, d_l3=0, d_l2=0, r_cut=40.0, pry_cold=True)),
        ("T8_R40_d12", dict(d_l4=12, d_l3=0, d_l2=0, r_cut=40.0, pry_cold=True)),
        ("T9_R35_d12", dict(d_l4=12, d_l3=0, d_l2=0, r_cut=35.0, pry_cold=True)),
        ("M3_d12_925inWeak", dict(d_l4=12, d_l3=9, d_l2=9, pry_cold=True, s34_925_in_weak=True)),
        ("M3_skipL4_925inWeak", dict(d_l4=99, d_l3=0, d_l2=0, pry_cold=True, s34_925_in_weak=True)),
        ("M3_d12_af03inWeak", dict(d_l4=12, d_l3=9, d_l2=9, pry_cold=True, s34_af03_in_weak=True)),
        ("M3_d12_honestDelay935", dict(d_l4=12, d_l3=9, d_l2=9, pry_cold=True, honest_delay935=True)),
    ]

    for cname, cfg in [("V21", cfg_v21), ("V20", cfg_v20)]:
        print(f"\n=== {cname} V2 5-Tier & Module 3 Tests (FULL vs DE-SINGLETON) ===")
        for lbl, kw in specs:
            rf = run_cfg(cache, cfg, **kw)
            rd = run_cfg(cache_ds, cfg, **kw)
            print(f"  {lbl:24s} | 5Y: MDD={rf['5Y']['mdd']:5.2f}% Sh={rf['5Y']['sh']:5.3f} NAV={rf['5Y']['nav']:12,.0f} | IS: MDD={rf['IS']['mdd']:5.2f}% Sh={rf['IS']['sh']:5.3f} | OOS: MDD={rf['OOS']['mdd']:5.2f}% Sh={rf['OOS']['sh']:5.3f} | 26={rf['Y26']['nav']:5.2f}x | DS: 5Y_MDD={rd['5Y']['mdd']:5.2f}% OOS={rd['OOS']['mdd']:5.2f}% Sh={rd['5Y']['sh']:5.3f}")


if __name__ == "__main__":
    main()

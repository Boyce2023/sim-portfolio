#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Step 3 Prep: Read-only load 4 strategies candidate pools, cache them in sandbox, verify baseline & LHB coverage."""

import importlib.util
import os
import pickle
import sys
import time

import numpy as np
import pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
SANDBOX = f"{SIM}/backtests_astock2/rd016_famous_youzi_seats_20261117"
UPG_DIR = f"{SIM}/backtests_astock/clean_3strategies_mutual_upgrade_20261117"
HIGH_DIR = f"{SIM}/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113"

LHB_PQ = f"{SANDBOX}/clean_lhb_5y.parquet"
THS_PQ = f"{SANDBOX}/ths_pit_youzi_5y.parquet"


def load_mod(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    t0 = time.time()
    lhb = pd.read_parquet(LHB_PQ)
    d1_keys = set(zip(lhb[lhb["is_three"] == 0]["date"], lhb[lhb["is_three"] == 0]["stock_code"]))
    d3_keys = set(zip(lhb[lhb["is_three"] == 1]["date"], lhb[lhb["is_three"] == 1]["stock_code"]))
    any_keys = d1_keys | d3_keys

    # 1. 一进二 V19
    t1 = time.time()
    m1 = load_mod("u12", f"{UPG_DIR}/upgrade_1to2_pit.py")
    ctx12 = m1.build_signals_and_data_pit("2026-11-16")
    fb = ctx12["hist_fb"].copy()
    fb["c6"] = fb["c6"].astype(str).str.zfill(6)
    fb["mask_v18"] = ctx12["mask_v18"]
    fb["mask_v19"] = ctx12["mask_v19"]
    # Simulate all V19_pass and near-threshold (score_active >= 270) rows for fast sandbox scoring
    sim_v19 = m1.make_trade_sim(ctx12, use_m1_d3_exempt=True)
    fb_5y = fb[fb["d2_dt"] >= "2021-11-15"].copy()
    # Pre-simulate all rows in common_ok & open_in_win & p_tight or score >= 260
    cand12_mask = fb["mask_v19"] | ((fb["d2_dt"] >= "2021-11-15") & (fb["score_active"] >= 265.0) & fb["is_buyable_open"] & (~fb["nuclear_halt"]) & (~fb["promo_freeze"]))
    sim_res12 = []
    for idx_i in np.where(cand12_mask)[0]:
        row_d = fb.iloc[idx_i].to_dict()
        tr = sim_v19(row_d)
        sim_res12.append(tr)
    fb_cand = fb[cand12_mask].copy().reset_index(drop=True)
    fb_cand["sim_tr"] = sim_res12
    fb_cand["has_d1_single"] = [(d, c) in d1_keys for d, c in zip(fb_cand["dt_str"], fb_cand["c6"])]
    fb_cand["has_d1_any"] = [(d, c) in any_keys for d, c in zip(fb_cand["dt_str"], fb_cand["c6"])]

    fb_all5y = fb[fb["d2_dt"] >= "2021-11-15"]
    fb_m19 = fb_cand[fb_cand["mask_v19"]]
    # Check baseline 20bps replay count vs 97
    tr19_base, eq19_base, _ = m1.run_slot_and_eq(ctx12, ctx12["mask_v19"], "_sv_v19", sim_v19, "2021-11-15", "2026-11-16")
    print(f"[1to2 V19] ({time.time()-t1:.1f}s) | all_fb_5y={len(fb_all5y)} d1_s={fb_all5y['dt_str'].combine(fb_all5y['c6'], lambda d,c:(d,c) in d1_keys).mean()*100:.1f}%")
    print(f"  V19 triggered={len(fb_m19)} d1_single_cov={fb_m19['has_d1_single'].mean()*100:.1f}% d1_any_cov={fb_m19['has_d1_any'].mean()*100:.1f}% | slot_trades={len(tr19_base)}")

    # 2. 二进三 V2.0
    t2 = time.time()
    m2 = load_mod("u23", f"{UPG_DIR}/upgrade_2to3_pit.py")
    _, df23_all, gated23, _ = m2.build_pit_dataset(cutoff_date="2026-11-16")
    gated23["score_v2"] = 60.0 + m2.compute_v20_components(gated23).sum(axis=1)
    g23_5y = gated23[gated23["buy_date"] >= "2021-11-16"].copy().reset_index(drop=True)
    g23_5y["c6"] = g23_5y["code"].astype(str).str.zfill(6)
    g23_5y["has_d2_s"] = [(d, c) in d1_keys for d, c in zip(g23_5y["sig_date"], g23_5y["c6"])]
    g23_5y["has_d2_any"] = [(d, c) in any_keys for d, c in zip(g23_5y["sig_date"], g23_5y["c6"])]
    g23_5y["has_d1_or_d2_any"] = [((d, c) in any_keys) or ((d1, c) in any_keys) for d, d1, c in zip(g23_5y["sig_date"], g23_5y["d1_date"], g23_5y["c6"])]
    g23_90 = g23_5y[g23_5y["score_v2"] >= 90]
    led23 = m2.sim_single_slot(g23_90, "score_v2", "ret_v2", "ed_v2", "eh_v2")
    print(f"[2to3 V2.0] ({time.time()-t2:.1f}s) | gated_5y={len(g23_5y)} d2_s={g23_5y['has_d2_s'].mean()*100:.1f}% d2_any={g23_5y['has_d2_any'].mean()*100:.1f}% d1_or_d2={g23_5y['has_d1_or_d2_any'].mean()*100:.1f}%")
    print(f"  V2.0>=90 pool={len(g23_90)} d2_s={g23_90['has_d2_s'].mean()*100:.1f}% d2_any={g23_90['has_d2_any'].mean()*100:.1f}% d1_or_d2={g23_90['has_d1_or_d2_any'].mean()*100:.1f}% | slot_trades={len(led23)}")

    # 3. 三进四 V4.0
    t3 = time.time()
    m3 = load_mod("u34", f"{UPG_DIR}/upgrade_3to4_pit.py")
    res34 = m3.run_causal_pipeline("2026-11-16", verbose=False)
    c34 = res34["cand_df"].copy()
    c34["comp_v40_sum"] = res34["comp_v40"].sum(axis=1)
    c34["sc_v40"] = res34["sc_v40"]
    c34["skel"] = res34["skel"]
    c34["p_1030"] = res34["p_1030"]
    c34_sk = c34[c34["skel"]].copy().reset_index(drop=True)
    c34_sk["c6"] = c34_sk["code"].astype(str).str.zfill(6)
    c34_sk["has_d3_s"] = [(d, c) in d1_keys for d, c in zip(c34_sk["sig_date"], c34_sk["c6"])]
    c34_sk["has_d3_any"] = [(d, c) in any_keys for d, c in zip(c34_sk["sig_date"], c34_sk["c6"])]
    # Also check D2/D1 availability using code_bars
    cb34 = res34["code_bars"]
    has_any_123 = []
    d2_list, d1_list = [], []
    for r in c34_sk.itertuples(index=False):
        cb = cb34.get(r.c6)
        pos = cb["date_to_pos"].get(r.buy_date, -1) if cb else -1
        d2_dt = str(cb["dts"][pos - 2]) if (cb and pos >= 2) else ""
        d1_dt = str(cb["dts"][pos - 3]) if (cb and pos >= 3) else ""
        d2_list.append(d2_dt)
        d1_list.append(d1_dt)
        has_any_123.append(((r.sig_date, r.c6) in any_keys) or ((d2_dt, r.c6) in any_keys) or ((d1_dt, r.c6) in any_keys))
    c34_sk["d2_date"] = d2_list
    c34_sk["d1_date"] = d1_list
    c34_sk["has_d123_any"] = has_any_123
    c34_90 = c34_sk[c34_sk["sc_v40"] >= 90]
    _, led34 = m3.extract_raw_and_slot(res34, res34["sc_v40"], 90.0, "p_1030")
    print(f"[3to4 V4.0] ({time.time()-t3:.1f}s) | skel={len(c34_sk)} d3_s={c34_sk['has_d3_s'].mean()*100:.1f}% d3_any={c34_sk['has_d3_any'].mean()*100:.1f}% d123_any={c34_sk['has_d123_any'].mean()*100:.1f}%")
    print(f"  V4.0>=90 pool={len(c34_90)} d3_s={c34_90['has_d3_s'].mean()*100:.1f}% d3_any={c34_90['has_d3_any'].mean()*100:.1f}% d123_any={c34_90['has_d123_any'].mean()*100:.1f}% | slot_trades={len(led34)}")

    # 4. 高标首阴 V5.1
    v5 = pd.read_pickle(f"{HIGH_DIR}/v5_enriched_119.pkl")
    v5["c6"] = v5["code"].astype(str).str.zfill(6)
    v5["has_d1_s"] = [(d, c) in d1_keys for d, c in zip(v5["d1"], v5["c6"])]
    v5["has_d1_any"] = [(d, c) in any_keys for d, c in zip(v5["d1"], v5["c6"])]
    v5["has_d0_any"] = [(d, c) in any_keys for d, c in zip(v5["d0"], v5["c6"])]
    v5["has_d0_or_d1"] = v5["has_d1_any"] | v5["has_d0_any"]
    v5_88 = v5[v5["sc4"] >= 88]
    print(f"[High V5.1] all_119={len(v5)} d1_s={v5['has_d1_s'].mean()*100:.1f}% d1_any={v5['has_d1_any'].mean()*100:.1f}% d0_any={v5['has_d0_any'].mean()*100:.1f}% d0_or_d1={v5['has_d0_or_d1'].mean()*100:.1f}%")
    print(f"  V5.1>=88 pool={len(v5_88)} d1_s={v5_88['has_d1_s'].mean()*100:.1f}% d0_or_d1={v5_88['has_d0_or_d1'].mean()*100:.1f}%")

    cache = {
        "fb_cand": fb_cand,
        "fb_all5y_cov": {
            "N": int(len(fb_all5y)),
            "d1_single_cov_pct": round(float(fb_all5y["dt_str"].combine(fb_all5y["c6"], lambda d, c: (d, c) in d1_keys).mean() * 100.0), 2),
            "d1_any_cov_pct": round(float(fb_all5y["dt_str"].combine(fb_all5y["c6"], lambda d, c: (d, c) in any_keys).mean() * 100.0), 2),
        },
        "g23_5y": g23_5y,
        "g23_all": gated23,
        "c34_sk": c34_sk,
        "v5_119": v5,
    }
    with open(f"{SANDBOX}/strat_pools_cache.pkl", "wb") as f:
        pickle.dump(cache, f)
    print(f"Saved strat_pools_cache.pkl in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()

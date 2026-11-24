#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Step 2i: IS-only calibration + full 120+ factor scan on S1B_BigYang_DeepOpen (ret 12~19.4%, to<=30%, open -10~-3.5%)."""
import pickle, time
import numpy as np
import pandas as pd
from step2_factor_scan import eval_slice, factor_specs
from step2b_is_calibration_probe import attach_t2_ret, scan_is
from step2c_is_exit_probe import sim_dynamic_exit

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd022_20cm_strategy_suite_20261124/part2_native_strategies"


def main():
    df = pd.read_parquet(f"{OUT_DIR}/cache_20cm_panel.parquet")
    g = df.groupby("c6", sort=False)
    df["prev_zt_hhmm"] = g["zt_hhmm"].shift(1).fillna(9999).astype(int)
    df["prev_zt_obc"] = g["zt_obc"].shift(1).fillna(-1).astype(int)
    df["prev_lhb_lh_cnt"] = g["lhb_lh_cnt"].shift(1).fillna(0).astype(int)
    aux = pickle.load(open(f"{OUT_DIR}/cache_20cm_aux.pkl", "rb"))
    mkt10 = aux["mkt10"]
    df["mkt10_dt_cnt"] = df["dt"].map({k: v["mkt10_dt_cnt"] for k, v in mkt10.items()}).fillna(0).astype(int)

    base = df[df["tradable"] & (df["is_st_pit"] == 0) & (df["close"] >= 2.0) & (df["tox_90d"] == 0) & (df["reg_10d"] == 0)].copy()
    pool = base[(~base["is_zt"]) & base["ret"].between(0.12, 0.194) & base["is_true_yang"] & (base["to"] <= 30.0) & base["f1_buyable"] & base["f1_o_pct"].between(-0.10, -0.035)].copy()

    # Append 120+ factor scan rows for P1B_BigYang to factor_scan_part2.csv
    tr_list, valid_idx = [], []
    for idx, r in enumerate(pool.itertuples(index=False)):
        k = 2
        while k < 11 and not getattr(r, f"f{k}_sellable", False): k += 1
        while k >= 2 and np.isnan(getattr(r, f"f{k}_ac", np.nan)): k -= 1
        if k < 2: continue
        s_px = float(getattr(r, f"f{k}_ac"))
        s_dt = getattr(r, f"f{k}_dt")
        if not s_dt or np.isnan(s_px) or s_px <= 0: continue
        valid_idx.append(idx)
        tr_list.append({"sig_date": r.dt, "buy_date": r.f1_dt, "exit_date": s_dt, "c6": r.c6, "net_ret": (s_px / float(r.f1_ao)) * 0.9970 - 1.0})
    sub_df = pool.iloc[valid_idx].reset_index(drop=True)
    tr_df = pd.DataFrame(tr_list)

    extra_rows = []
    for grp, fname, fn in factor_specs("P1B_BigYang"):
        m = np.asarray(fn(sub_df), dtype=bool)
        r = eval_slice(tr_df, m)
        extra_rows.append({
            "proto": "P1B_BigYang", "layer": grp, "factor": fname,
            "IS_N": r["IS"][0], "IS_WR": r["IS"][1], "IS_mean": r["IS"][2], "IS_t": r["IS"][3], "IS_ew": r["IS"][4],
            "OOS_N": r["OOS"][0], "OOS_WR": r["OOS"][1], "OOS_mean": r["OOS"][2], "OOS_t": r["OOS"][3], "OOS_ew": r["OOS"][4],
            "Y26_N": r["2026"][0], "Y26_WR": r["2026"][1], "Y26_mean": r["2026"][2], "Y26_ew": r["2026"][4],
        })
    old = pd.read_csv(f"{OUT_DIR}/factor_scan_part2.csv")
    old = old[old["proto"] != "P1B_BigYang"]
    pd.concat([old, pd.DataFrame(extra_rows)], ignore_index=True).to_csv(f"{OUT_DIR}/factor_scan_part2.csv", index=False)

    # IS-ONLY calibration printout (strictly <= 2024-08-31!)
    p_is = attach_t2_ret(pool[pool["f1_dt"] <= "2024-08-31"])
    scan_is("P1B_BigYang (IS ONLY)", p_is, [
        ("mkt20_zt<16", lambda d: d["mkt20_zt_cnt"] < 16),
        ("pos60<=0.55", lambda d: d["pos60"] <= 0.55),
        ("prev_pos20<=0.50", lambda d: d["prev_pos20"] <= 0.50),
        ("bias20<=0.12", lambda d: d["bias20"] <= 0.12),
        ("mcap<=50亿", lambda d: d["mcap"] <= 50.0),
        ("rf_mcap<=30亿", lambda d: d["real_free_mcap"] <= 30.0),
        ("lock_top10>=45%", lambda d: d["lock_top10"] >= 45.0),
        ("real_to<20%", lambda d: d["real_to"] < 20.0),
        ("real_to>=30%", lambda d: d["real_to"] >= 30.0),
        ("close<=25", lambda d: d["close"] <= 25.0),
        ("close>40", lambda d: d["close"] > 40.0),
        ("dist_3d30>=0.10", lambda d: d["dist_3d30"] >= 0.10),
        ("kpl_hist_10zt>=4", lambda d: d["kpl_hist_10zt_max"] >= 4),
        ("lhb_has==0", lambda d: d["lhb_has"] == 0),
        ("lhb_inst_net>0", lambda d: d["lhb_inst_net"] > 0),
        ("lhb_surf==1", lambda d: d["lhb_surf"] == 1),
        ("is_tech==1", lambda d: d["is_tech"] == 1),
        ("weekday==Mon", lambda d: pd.to_datetime(d["f1_dt"]).dt.dayofweek == 0),
        ("month in (1,4)", lambda d: d["f1_dt"].str.slice(5, 7).isin(["01", "04"])),
        ("ret[14%,19.4%]", lambda d: d["ret"] >= 0.14),
        ("close_pos>=0.70", lambda d: d["close_pos"] >= 0.70),
        ("open<-5%", lambda d: d["f1_o_pct"] < -0.05),
    ])

    # IS-ONLY exit probe
    pool_is = pool[pool["f1_dt"] <= "2024-08-31"].copy(); pool_is["score"] = 0.0
    print("\n=== P1B_BigYang IS EXIT PROBE ===")
    for rl in ["T2_close", "T3_close", "T2_zt_ride", "T2_gap_cut_only", "T2_tp08_ty", "T2_tp10_weakcut"]:
        tr = sim_dynamic_exit(pool_is, rl)
        r = tr["net_ret"].to_numpy()
        w, l = r[r > 0], r[r <= 0]
        po = w.mean() / abs(l.mean()) if len(w) and len(l) else 0
        ew = np.prod(1.0 + tr.groupby("buy_date")["net_ret"].mean().to_numpy())
        print(f"  {rl:18s} | N={len(r):4d} WR={len(w)/len(r)*100:5.1f}% PO={po:4.2f} mn={r.mean()*100:+5.2f}% ew={ew:6.2f}x")


if __name__ == "__main__":
    main()

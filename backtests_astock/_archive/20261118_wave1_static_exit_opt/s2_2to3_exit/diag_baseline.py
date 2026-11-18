#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Baseline reproduction + 5m coverage + trade anatomy diagnostics for 二进三 V2.0 (s_2to3).
Uses cutoff_date='2026-11-16' to match data_as_of_date=2026-11-16 of clean_2to3_5y & summary_upg_2to3.json.
"""
import os, sys, json, pickle
import numpy as np
import pandas as pd
import pyarrow.dataset as ds

assert "yfinance" not in sys.modules

ROOT = "/Users/huaichuaibeimeng/claude-projects"
UPG_DIR = f"{ROOT}/sim-portfolio/backtests_astock/clean_3strategies_mutual_upgrade_20261117"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock/exit_opt_20261118/s2_2to3_exit"
os.makedirs(OUT_DIR, exist_ok=True)

sys.path.insert(0, UPG_DIR)
import upgrade_2to3_pit as u23

def main():
    CUTOFF = "2026-11-16"
    raw_all, df_all, gated_all, _ = u23.build_pit_dataset(cutoff_date=CUTOFF)
    assert len(raw_all) == 10848 and len(df_all) == 6070
    comp_v2 = u23.compute_v20_components(gated_all)
    gated_all["score_v2"] = 60.0 + comp_v2.sum(axis=1)
    gated_all["score"] = gated_all["score_v2"]

    da, b5m = u23.load_daily_and_5m(CUTOFF)
    all_dts = sorted(da["dt"].unique())
    dt_idx = {d: i for i, d in enumerate(all_dts)}

    gated_5y = gated_all[gated_all["buy_date"] >= u23.CANON_5Y_START].copy().reset_index(drop=True)
    led_std_5y = u23.sim_single_slot(gated_5y[gated_5y["score_v2"] >= 90], "score_v2", "ret_v2", "ed_v2", "eh_v2")
    led_str_5y = u23.sim_single_slot(gated_5y[gated_5y["score_v2"] >= 96], "score_v2", "ret_v2", "ed_v2", "eh_v2")

    ref_std = pd.read_csv(f"{UPG_DIR}/ledger_upg_2to3_std.csv")
    ref_str = pd.read_csv(f"{UPG_DIR}/ledger_upg_2to3_strict.csv")
    ref_std["code"] = ref_std["code"].astype(str).str.zfill(6)
    ref_str["code"] = ref_str["code"].astype(str).str.zfill(6)

    for tag, my_df, ref_df in [("std90", led_std_5y, ref_std), ("strict96", led_str_5y, ref_str)]:
        assert len(my_df) == len(ref_df), f"{tag} len mismatch: {len(my_df)} vs {len(ref_df)}"
        assert (my_df["code"] == ref_df["code"]).all()
        assert (my_df["buy_date"] == ref_df["buy_date"]).all()
        assert (my_df["exit_date"] == ref_df["exit_date"]).all()
        assert (my_df["exit_hhmm"] == ref_df["exit_hhmm"]).all()
        max_ret_diff = float(np.max(np.abs(my_df["net_ret"].to_numpy() - ref_df["net_ret"].to_numpy())))
        assert max_ret_diff < 1e-12, f"{tag} ret diff {max_ret_diff}"
        m0 = u23.calc_nav_cap10m(my_df["net_ret"].to_numpy(dtype=float))
        sa = gated_5y[gated_5y["score_v2"] >= (90 if tag == "std90" else 96)]
        ew = float(np.prod(1.0 + sa.groupby("buy_date")["ret_v2"].mean().sort_index().to_numpy()))
        print(f"[EXACT MATCH 0.0] {tag}: N={m0['trades']}, WR={m0['win_rate_pct']}%, PLR={m0['plr']}, "
              f"1S={m0['nav']}x, EQ={ew:.2f}x, MDD={m0['max_dd_pct']}%, max_ret_diff={max_ret_diff:.2e}")

    # Check 603706 score
    r_603706 = gated_all[(gated_all["code"].astype(str).str.zfill(6) == "603706") & (gated_all["buy_date"] == "2026-11-11")]
    if not r_603706.empty:
        print("603706 2026-11-11:", r_603706[["score_v2", "ed_v2", "eh_v2", "ret_v2"]].to_dict(orient="records"))

    # Signal counts
    sub90 = gated_all[gated_all["score_v2"] >= 90].copy()
    sub96 = gated_all[gated_all["score_v2"] >= 96].copy()
    print(f"Signals >=90: total={len(sub90)}, IS(<=2023)={(sub90['buy_date']<='2023-12-31').sum()}, "
          f"5Y(>={u23.CANON_5Y_START})={(sub90['buy_date']>=u23.CANON_5Y_START).sum()}, "
          f"OOS(>=2024)={(sub90['buy_date']>='2024-01-01').sum()}")
    print(f"Signals >=96: total={len(sub96)}, IS(<=2023)={(sub96['buy_date']<='2023-12-31').sum()}, "
          f"5Y(>={u23.CANON_5Y_START})={(sub96['buy_date']>=u23.CANON_5Y_START).sum()}, "
          f"OOS(>=2024)={(sub96['buy_date']>='2024-01-01').sum()}")

    # 5m bar coverage for >=90 hold days
    miss_hold = []
    tot_hold_days = 0
    for r in sub90.itertuples(index=False):
        c6 = str(r.code).zfill(6)
        p0 = dt_idx.get(str(r.buy_date), -1)
        p_end = dt_idx.get(str(r.ed_v2), p0 + 1)
        for k in range(p0 + 1, min(p_end + 1, len(all_dts))):
            dk = all_dts[k]
            tot_hold_days += 1
            arr = b5m.get((c6, dk))
            if arr is None or len(arr) < 12:
                miss_hold.append((str(r.buy_date), c6, str(r.name), dk, 0 if arr is None else len(arr), bool(r.sealed_3b)))
    print(f"5m hold-day coverage (>=90 all, up to baseline exit): {tot_hold_days - len(miss_hold)}/{tot_hold_days}, missing={len(miss_hold)}")
    for m in miss_hold[:15]:
        print("  MISS 5m:", m)

    # Also check extended coverage (k+1..k+11) on >=90
    miss_ext = []
    tot_ext = 0
    for r in sub90.itertuples(index=False):
        c6 = str(r.code).zfill(6)
        p0 = dt_idx.get(str(r.buy_date), -1)
        for k in range(p0 + 1, min(p0 + 12, len(all_dts))):
            dk = all_dts[k]
            tot_ext += 1
            arr = b5m.get((c6, dk))
            if arr is None or len(arr) < 12:
                miss_ext.append((str(r.buy_date), c6, dk, 0 if arr is None else len(arr)))
    print(f"5m extended coverage (p0+1..p0+11 on >=90): {tot_ext - len(miss_ext)}/{tot_ext}, missing={len(miss_ext)}")

    # Breakdown of std90 5Y ledger by sealed_3b & exit_hhmm
    for s3 in [False, True]:
        ss = led_std_5y[led_std_5y["sealed_3b"] == s3]
        print(f"5Y Std90 sealed_3b={s3}: N={len(ss)}, WR={(ss['net_ret']>0).mean()*100:.1f}%, "
              f"mean={ss['net_ret'].mean()*100:.2f}%, prod={np.prod(1+ss['net_ret']):.2f}x, "
              f"exit_hh={ss['exit_hhmm'].value_counts().to_dict()}")

    led_std_full = u23.sim_single_slot(gated_all[gated_all["score_v2"] >= 90], "score_v2", "ret_v2", "ed_v2", "eh_v2")
    for wname, cond in [("IS(<=2023)", led_std_full["buy_date"] <= "2023-12-31"), ("OOS(>=2024)", led_std_full["buy_date"] >= "2024-01-01")]:
        wdf = led_std_full[cond]
        for s3 in [False, True]:
            ss = wdf[wdf["sealed_3b"] == s3]
            print(f"  {wname} sealed_3b={s3}: N={len(ss)}, WR={(ss['net_ret']>0).mean()*100:.1f}%, mean={ss['net_ret'].mean()*100:.2f}%, prod={np.prod(1+ss['net_ret']):.2f}x")

    print("Worst 10 trades in 5Y Std90:")
    for r in led_std_5y.sort_values("net_ret").head(10).itertuples(index=False):
        print(f"  {r.buy_date}->{r.exit_date}({r.exit_hhmm}) {r.code} {r.name} s3={r.sealed_3b} sc={r.score} ret={r.net_ret*100:.2f}%")

    print("Top 10 winners in 5Y Std90:")
    for r in led_std_5y.sort_values("net_ret", ascending=False).head(10).itertuples(index=False):
        print(f"  {r.buy_date}->{r.exit_date}({r.exit_hhmm}) {r.code} {r.name} s3={r.sealed_3b} sc={r.score} ret={r.net_ret*100:.2f}%")

    # Load turn & oshare for needed codes so Phase D turnover checks are 100% accurate
    codes_needed = set(gated_all["code"].astype(str).str.zfill(6).unique())
    flt = (ds.field("date") >= pd.Timestamp("2020-11-01")) & (ds.field("date") <= pd.Timestamp(CUTOFF))
    tcols = ["date", "ticker", "turn", "oshare", "qfq_factor"]
    t_act = ds.dataset(u23.A_DAILY_PQ, format="parquet").scanner(columns=tcols, filter=flt).to_table().to_pandas()
    t_del = ds.dataset(u23.A_DELISTED_PQ, format="parquet").scanner(columns=tcols, filter=flt).to_table().to_pandas()
    ta = pd.concat([t_act, t_del], ignore_index=True)
    ta["c6"] = ta["ticker"].astype(str).str[:6]
    ta = ta[ta["c6"].isin(codes_needed) & (~ta["ticker"].astype(str).str.endswith(".BJ"))].copy()
    ta["dt"] = ta["date"].dt.strftime("%Y-%m-%d")
    ta.drop_duplicates(["c6", "dt"], keep="first", inplace=True)

    da_need = da[da["c6"].isin(codes_needed) & (da["dt"] >= "2020-11-01")].copy()
    da_need = da_need.merge(ta[["c6", "dt", "turn", "oshare", "qfq_factor"]], on=["c6", "dt"], how="left")
    b5m_need = {k: v for k, v in b5m.items() if k[0] in codes_needed}

    cache_path = f"{OUT_DIR}/_cache_2to3_pit_20261116.pkl"
    with open(cache_path, "wb") as f:
        pickle.dump({
            "gated_all": gated_all, "comp_v2": comp_v2, "da_need": da_need,
            "b5m_need": b5m_need, "all_dts": all_dts, "raw_all": raw_all, "df_all": df_all
        }, f)
    print(f"Saved fast cache to {cache_path} (codes={len(codes_needed)}, da_need={len(da_need)}, b5m_need={len(b5m_need)})")

if __name__ == "__main__":
    main()

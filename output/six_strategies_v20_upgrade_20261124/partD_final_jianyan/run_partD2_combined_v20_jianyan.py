#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Part D2 Master Runner: Reproduce V20.0 6-Strategy Champion (P3_S2C_STierReserveOnly, n=278),
export clean CSV, verify physical cleanliness, and run complete Old Anti-Overfitting + 7-Pillar Suite.
Pure single-slot compounding & daily-EW basis only. ZERO yfinance (D12). All SQLite mode=ro.
"""
import json, os, sys, time, warnings
import numpy as np, pandas as pd

sys.dont_write_bytecode = True
warnings.filterwarnings("ignore", category=FutureWarning)
assert "yfinance" not in sys.modules, "D12 VIOLATION: yfinance forbidden"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
OUT_DIR = f"{SIM}/output/six_strategies_v20_upgrade_20261124/partD_final_jianyan"
VAL5_DIR = f"{SIM}/output/five_strategies_institutional_validation_20261124"
PARTB_DIR = f"{SIM}/output/six_strategies_v20_upgrade_20261124/partB_20cm_full_jianyan"
for p in (OUT_DIR, VAL5_DIR, PARTB_DIR):
    if p not in sys.path: sys.path.insert(0, p)

import run_part1_alpha_micro_regime as p1
import run_partB_20cm_7pillars as pb
import partD2_mod_base as dbase
import partD2_mod_p1_p3 as dp13
import partD2_mod_p4_p5 as dp45
import partD2_mod_p6_p7 as dp67

def main():
    t0 = time.time()
    print("[1/7] Loading calendar, CSI300 & All-A-Share daily panel...")
    cal_dates, sh300, csi_s = p1.load_calendar_and_csi300()
    all_sh_dts = sorted(sh300.keys())
    csi_5y_ret = float(np.prod(1.0 + csi_s.to_numpy()) - 1.0)
    sh300_b, all_sh_b, ew20_daily, cal_full, _, _, _ = pb.load_calendars()
    df_all, tot_amt, zt_tape = pb.load_full_daily_panel()
    df_10 = df_all[df_all["c6"].str.startswith(("00", "60"))].copy()
    df_10["board_cnt_m2"] = df_10.groupby("c6", sort=False)["board_cnt"].shift(2)
    df_10["is_dt_m1"] = df_10.groupby("c6", sort=False)["is_dt"].shift(1)
    df_10["is_dt_m2"] = df_10.groupby("c6", sort=False)["is_dt"].shift(2)
    df_10["is_dt_m3"] = df_10.groupby("c6", sort=False)["is_dt"].shift(3)
    df_10["ret_m1"] = df_10.groupby("c6", sort=False)["ret"].shift(1)
    df_10["open_m1"] = df_10.groupby("c6", sort=False)["open"].shift(1)
    df_10["close_m1"] = df_10.groupby("c6", sort=False)["close"].shift(1)
    df_10["bias10_m1"] = (df_10["adj_close"] / df_10.groupby("c6", sort=False)["adj_close"].transform(lambda s: s.rolling(10, min_periods=10).mean()) - 1.0).groupby(df_10["c6"], sort=False).shift(1)
    bar_lu = {(r.c6, r.dt): (float(r.open), float(r.close), float(r.adj_close), float(r.qfq_factor), float(r.adjf))
              for r in df_all[["c6", "dt", "open", "close", "adj_close", "qfq_factor", "adjf"]].itertuples(index=False)}

    print("[2/7] Reproducing P3_S2C_STierReserveOnly, exporting clean CSV & asserting physical cleanliness...")
    comb_df, pool6, untrig_df, waits = dbase.build_and_export_combined(bar_lu)
    phys_chk = dbase.verify_physical_cleanliness(comb_df, df_all)
    by_c_all = pb.build_by_c_lookup(df_all[df_all["c6"].isin(set(comb_df["code"]) | set(df_all[df_all["is20"]]["c6"]))])
    daily_comb, _, nav_mtm, nav_led = pb.compute_daily_mtm(comb_df.assign(buy_px=comb_df["buy_px_adj"], exit_px=comb_df["exit_px_adj"]), by_c_all, cal_dates, prices_are_adj=True)
    assert abs(nav_mtm / nav_led - 1.0) < 1e-5, f"MTM mismatch: {nav_mtm} vs {nav_led}"

    print("[3/7] Running Anti-Overfitting Old Suite (Windows, HLZ/DSR, Monkey 5k, CSCV PBO, 2025-01-01 Truncation)...")
    old_suite = dbase.run_old_suite(comb_df, daily_comb, cal_dates, sh300, all_sh_dts, pool6, untrig_df)

    print("[4/7] Building All-A 5F/6F factors, ecological controls & targeted 5m bars...")
    fac_5f, extra_f = dp13.build_all_a_factors(df_all, cal_dates, all_sh_dts, zt_tape, csi_s)
    pool10_dt, q10 = p1.prepare_matched_pools(df_10, cal_dates)
    by_c10 = p1.build_by_c_lookup(df_10)
    pool20_dt, q20 = pb.prepare_20cm_matched_pools(df_all[df_all["is20"]], cal_dates)
    by_c20 = pb.build_by_c_lookup(df_all[df_all["is20"]])
    pairs_5m = {(r.code, r.buy_date) for r in comb_df.itertuples(index=False)}
    bars_5m = p1.load_targeted_5m_bars(pairs_5m)
    reg_df = p1.build_regime_table(cal_dates, all_sh_dts, tot_amt, zt_tape, df_10)

    print("[5/7] Running Pillars 1, 2 & 3...")
    p1_out = dp13.run_pillar1_v20(comb_df, daily_comb, fac_5f, extra_f, cal_dates, pool10_dt, q10, by_c10, pool20_dt, q20, by_c20)
    p2_out = dp13.run_pillar2_v20(comb_df, by_c_all, cal_dates, bars_5m, zt_tape)
    p3_out = p1.run_pillar3("combined_6strat_v20", comb_df, pd.Series(daily_comb, index=cal_dates), reg_df, csi_s, cal_dates)

    print("[6/7] Running Pillars 4 & 5...")
    p4_out = dp45.run_pillar4_v20(comb_df, by_c_all, sh300, all_sh_dts, csi_5y_ret)
    p5_out = dp45.run_pillar5_v20(comb_df, daily_comb, csi_s.to_numpy(float), sh300, all_sh_dts, pool6, untrig_df, cal_dates, bar_lu)

    print("[7/7] Running Pillars 6 & 7 (Hygiene, 5-Fold Purged CV, 6x6 Corr, Dual LOO, CUSUM/SPRT)...")
    p6_out = dp67.run_pillar6_v20(comb_df, daily_comb, cal_dates, bar_lu)
    p7_out = dp67.run_pillar7_v20(comb_df, daily_comb, pool6, untrig_df, by_c_all, cal_dates, bar_lu, sh300, csi_5y_ret * 100.0)

    out_obj = pb.sanitize_json({
        "meta": {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "elapsed_sec": round(time.time() - t0, 2),
            "scheme_id": "P3_S2C_STierReserveOnly",
            "window": "2021-11-16 ~ 2026-11-16",
            "n_trading_days": len(cal_dates),
            "csi300_5y_pct": round(csi_5y_ret * 100.0, 2),
            "d12_yfinance_imported": "yfinance" in sys.modules,
            "compounding_basis": "pure_single_slot_and_daily_ew_only",
            "exported_ledger_csv": f"{OUT_DIR}/ledger_combined_6strat_v20_slot1_clean.csv",
            "by_strategy": comb_df["strategy"].value_counts().to_dict(),
            "by_tier": comb_df["tier"].value_counts().to_dict(),
            "untriggered_wait_events": len(waits),
        },
        "physical_cleanliness_assertions": phys_chk,
        "mtm_reconciliation": {"nav_ledger": round(nav_led, 4), "nav_daily_mtm": round(nav_mtm, 4), "rel_err": abs(nav_mtm / nav_led - 1.0)},
        "anti_overfitting_old_suite": old_suite,
        "pillar1_alpha_attribution": p1_out,
        "pillar2_micro_capacity": p2_out,
        "pillar3_regime_stress_bootstrap": p3_out,
        "pillar4_signal_and_turnover": p4_out,
        "pillar5_statistical_confidence_and_sequence": p5_out,
        "pillar6_hygiene": p6_out,
        "pillar7_portfolio_cusum": p7_out,
    })
    raw_json = json.dumps(out_obj, ensure_ascii=False, indent=2, allow_nan=False)
    low_j = raw_json.lower()
    assert ("cap" + "10m") not in low_j and ("cap" + "1000w") not in low_j and ("1000万" + "封顶") not in raw_json and ("千万" + "封顶") not in raw_json, "forbidden capped metric found!"
    out_json = f"{OUT_DIR}/partD2_combined_v20_jianyan.json"
    with open(out_json, "w", encoding="utf-8") as f:
        f.write(raw_json)
    print(f"[DONE in {time.time() - t0:.2f}s] Saved -> {out_json} ({os.path.getsize(out_json)} bytes)")

if __name__ == "__main__":
    main()

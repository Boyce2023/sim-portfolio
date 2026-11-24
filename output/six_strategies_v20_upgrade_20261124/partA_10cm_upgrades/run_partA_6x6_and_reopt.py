#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Part A Orchestrator:
1. Full 6x6 (30 ordered pairs x 2 lags) same-day / prev-day interaction matrix scan.
2. Five 10cm strategies full-candidate-pool reconstruction, drift checks, and calibration.
100% local read-only; zero yfinance; SQLite mode=ro; zero cap10m metrics.
"""
import json, os, sqlite3, sys, time
import numpy as np, pandas as pd

sys.dont_write_bytecode = True
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
from mod_common import SIM, OUT_DIR
from mod_6x6 import run_6x6_matrix
from mod_1to2 import run_1to2_full_audit, run_1to2_variant
from mod_other4 import audit_2to3, audit_3to4, audit_high_and_pry
from mod_extras import audit_extra_diagnostics

os.makedirs(OUT_DIR, exist_ok=True)

def load_20cm_mkt_breadth():
    panel = pd.read_parquet(f"{SIM}/backtests_astock2/rd022_20cm_strategy_suite_20261124/part2_native_strategies/cache_20cm_panel.parquet", columns=["dt", "c6", "is_zt", "is_dt"])
    con_z = sqlite3.connect(f"file:{SIM}/data/zt_micro_tape_5y_pit.db?mode=ro", uri=True)
    st_tape = {(str(td), str(sc).zfill(6)) for td, sc, nm in con_z.execute(
        "SELECT trade_date, sec_code, sec_name FROM zt_micro_tape WHERE sec_code LIKE '30%' OR sec_code LIKE '688%' OR sec_code LIKE '689%'"
    ) if ("ST" in str(nm) or "退" in str(nm))}
    con_z.close()
    zt_rows = panel[panel["is_zt"]]
    dt_rows = panel[panel["is_dt"]]
    mkt20_zt_cln = zt_rows[~zt_rows.apply(lambda r: (r["dt"], r["c6"]) in st_tape, axis=1)].groupby("dt").size().to_dict()
    mkt20_dt_cln = dt_rows[~dt_rows.apply(lambda r: (r["dt"], r["c6"]) in st_tape, axis=1)].groupby("dt").size().to_dict()
    return mkt20_zt_cln, mkt20_dt_cln

def main():
    t0 = time.time()
    sh300 = {k: float(v) for k, v in json.load(open(f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json", encoding="utf-8"))["sh000300"].items()}
    all_dts = sorted(sh300.keys())
    prev_td = {all_dts[i]: all_dts[i - 1] for i in range(1, len(all_dts))}

    print("[1/5] Loading 20cm clean breadth & baseline 1to2 pass pool...")
    mkt20_zt_cln, mkt20_dt_cln = load_20cm_mkt_breadth()
    s20 = pd.read_csv(f"{SIM}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v11_unified_redteam_attack/final_v11_all_scored_signals.csv", dtype={"c6": str})
    p1cln = pd.read_parquet(f"{SIM}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v1_deepopen_scorecard_exit/p1_clean_candidates.parquet", columns=["f1_dt", "f1_o_pct", "mkt20_zt_cnt"])
    a76_dts = set(s20[s20["score"] >= 76]["buy_date"].astype(str))
    fb20_dts = set(p1cln[(p1cln["f1_o_pct"] <= -0.03) & (p1cln["mkt20_zt_cnt"] < 16) & (p1cln["f1_dt"] <= "2026-11-16")].groupby("f1_dt").size().loc[lambda s: s >= 2].index.astype(str))

    print("[2/5] Running 1to2 V19 -> V2.0_cand full-pool reconstruction & 2025-01-01 truncation...")
    pass_1to2_df, res_1to2, (hf_12, inv_12, sc_12) = run_1to2_full_audit(sh300, all_dts)

    print("[3/5] Running complete 6x6 (30 ordered pairs x 2 lags) matrix scan...")
    res_6x6 = run_6x6_matrix(pass_1to2_df, prev_td)

    print("[4/5] Running full-pool audits for 2to3, 3to4, high, pry...")
    phd = pd.read_csv(f"{SIM}/backtests_astock/mkt_water_scoring_audit_20261123/part1_3to4_high/pool_high_full_clean.csv", dtype={"code": str})
    high_dts = set(phd[phd["base_score"] >= 88]["buy_date"].astype(str))
    t12_dts = set(pass_1to2_df["buy_date"].astype(str))
    res_2to3 = audit_2to3(sh300, all_dts, a76_dts, high_dts, t12_dts, mkt20_zt_cln)
    res_3to4 = audit_3to4(sh300, all_dts, a76_dts, mkt20_dt_cln)
    res_hp = audit_high_and_pry(sh300, all_dts, a76_dts)

    print("[5/5] Running extra drift & tail diagnostics & exporting summary...")
    res_extra = audit_extra_diagnostics(sh300, all_dts, hf_12, inv_12, sc_12, run_1to2_variant, a76_dts, fb20_dts, mkt20_dt_cln, mkt20_zt_cln)

    summary = {
        "meta": {"data_as_of_date": "2026-11-16", "is_cutoff": "2024-08-31", "oos_start": "2024-09-01",
                 "elapsed_sec": round(time.time() - t0, 2), "no_yfinance": "yfinance" not in sys.modules},
        "matrix_6x6": res_6x6,
        "strategies": {"1to2": res_1to2, "2to3": res_2to3, "3to4": res_3to4, **res_hp},
        "extra_diagnostics": res_extra,
        "decisions": {
            "1to2": {"action": "UPGRADE_TO_V20_CAND", "rule": "fb20_cln>=2 -> score -25", "alt_joint_rule": "a76(-12) + fb20_cln>=2(-12)",
                     "ledger_file": f"{OUT_DIR}/ledger_1to2_v20_cand.csv"},
            "2to3": {"action": "KEEP_V21_UNCHANGED"}, "3to4": {"action": "KEEP_V41_UNCHANGED"},
            "high": {"action": "KEEP_V51_UNCHANGED"}, "pry": {"action": "KEEP_V21_UNCHANGED"},
        },
    }
    raw_json = json.dumps(summary, ensure_ascii=False, indent=2)
    assert "cap10m" not in raw_json and "1000万" not in raw_json, "Forbidden cap10m metric found!"
    out_json = f"{OUT_DIR}/partA_10cm_reopt_summary.json"
    with open(out_json, "w", encoding="utf-8") as f:
        f.write(raw_json)
    print(f"DONE in {summary['meta']['elapsed_sec']}s -> {out_json}")

if __name__ == "__main__":
    main()

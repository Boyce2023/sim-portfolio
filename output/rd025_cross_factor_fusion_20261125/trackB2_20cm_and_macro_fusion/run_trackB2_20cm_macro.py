#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD025-Track B2 Master Runner:
  Core 1: >=60 strictly PIT atomic factors from 11 astock2 modules + oversold pry DNA into 20cm DeepOpen V1.1 (S82 & A76-81).
  Core 2: Macro/market/cross-strategy switches into V20.0 6-strategy portfolio (Mode A static + Mode B causal pool6 + Mode C 0.5x).
Hard rules: ZERO yfinance (D12), all SQLite ?mode=ro, pure compounding only, 100% PIT, IS<=2024-06-30 / Blind OOS>=2024-07-04 / Y26>=2026-01-01.
"""
import json, os, sys, time, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning)
sys.dont_write_bytecode = True
assert "yfinance" not in sys.modules, "D12 VIOLATION: yfinance forbidden"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
OUT_DIR = f"{SIM}/output/rd025_cross_factor_fusion_20261125/trackB2_20cm_and_macro_fusion"
P2_DIR = f"{SIM}/backtests_astock2/rd022_20cm_strategy_suite_20261124/part2_native_strategies"
PARTC_V20 = f"{SIM}/output/six_strategies_v20_upgrade_20261124/partC_fine_tier_priority"
PARTD_V20 = f"{SIM}/output/six_strategies_v20_upgrade_20261124/partD_final_jianyan"
V11_DIR = f"{SIM}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v11_unified_redteam_attack"
for p in (OUT_DIR, P2_DIR, PARTC_V20, PARTD_V20, V11_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from backtest_utils import _sim_k_slots
import tier_priority_engine as tpe
import partD2_mod_base as dbase
from b2_mod_eval import sanitize_json
from b2_mod_market import load_market_daily_and_bars
from b2_mod_macro_pit import build_mkt_buy_pit
from b2_mod_stock_pit import build_20cm_enriched_panel
from b2_mod_core1_scan import run_atomic_ic_scan
from b2_mod_core1_audit import run_core1_suite
from b2_mod_core2 import run_core2_v20_suite


def main():
    t0 = time.time()
    print("[1/5] Collecting all 20cm & V20.0 ticker universe + loading A-share market panel & bars...")
    v11_all = pd.read_csv(f"{V11_DIR}/final_v11_all_scored_signals.csv")
    pool6 = pd.concat([tpe.load_strategy_csv(st, p, "2021-11-16", "2026-11-16") for st, p in dbase.CSV_MAP.items()], ignore_index=True)
    target_codes = set(v11_all["c6"].astype(str).str.zfill(6)) | set(pool6["code"].astype(str).str.zfill(6))
    mkt_daily, bar_lu, sub_df, sh300, sz399107, all_sh_dts, all_dts = load_market_daily_and_bars(target_codes)

    print("[2/5] Building strictly PIT buy-day (d 09:25) macro table (NT V3, CSRC 22, US, 15Y Style, RD012/013, Gap)...")
    mkt_buy_pit = build_mkt_buy_pit(mkt_daily)
    cal_20cm = [d for d in all_dts if "2021-01-04" <= d <= "2026-11-23"]
    dt_idx_20 = {d: i for i, d in enumerate(cal_20cm)}

    print("[3/5] Assembling >=60 strictly PIT atomic factors on all 809 20cm signals & running Core 1 IC/S82/A76-81...")
    df20, v11_fcols = build_20cm_enriched_panel(mkt_buy_pit, sub_df)
    ic_matrix = run_atomic_ic_scan(df20, v11_fcols)
    core1_res = run_core1_suite(df20, v11_fcols, _sim_k_slots, tpe, bar_lu, cal_20cm, dt_idx_20, sh300, all_sh_dts)

    print("[4/5] Running Core 2: V20.0 6-Strategy Portfolio Macro/Market Switch Audit (Mode A/B/C + CSCV PBO)...")
    core2_res = run_core2_v20_suite(mkt_buy_pit, bar_lu, all_dts, sh300, all_sh_dts, df20=df20)

    print("[5/5] Exporting & auditing trackB2_summary.json...")
    assert "yfinance" not in sys.modules, "D12 violation"
    spot7 = {
        "us_ixic_drop_panic_open": [r for r in core1_res["s82_enhancement_tests"] if "ixic" in r["rule_id"]],
        "nt_v3": [r for r in core1_res["s82_enhancement_tests"] if r["module"] == "M2_国家队V3"],
        "youzi_bayes_lasa_sell": [r for r in core1_res["s82_enhancement_tests"] if r["module"] == "M5_游资贝叶斯"],
        "abnormality_headroom": [r for r in core1_res["s82_enhancement_tests"] if "abn_" in r["rule_id"]],
        "brk_r10": [r for r in core1_res["s82_enhancement_tests"] if "brk_r10" in r["rule_id"]],
        "streak_gap": [r for r in core1_res["s82_enhancement_tests"] if r["module"] == "M9_连板断层"],
        "oversold_mkt_dt": [r for r in core1_res["s82_enhancement_tests"] if "R_M11_dt" in r["rule_id"] or "M11_dt" in r["rule_id"]],
    }
    summary = sanitize_json({
        "meta": {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "elapsed_sec": round(time.time() - t0, 2),
            "yfinance_imported": "yfinance" in sys.modules,
            "n_atomic_factors": len(ic_matrix),
            "n_core1_s82_rules": len(core1_res["s82_enhancement_tests"]),
            "n_core1_a7681_tests": core1_res["a76_81_rescue_audit"]["n_tested"],
            "n_core2_macro_switches": len(core2_res["mode_A_static_278"]),
            "splits": {"IS": "<=2024-06-30", "OOS_BLIND": ">=2024-07-04", "OOS_RT": ">=2024-09-01", "Y26": ">=2026-01-01"},
        },
        "core1_atomic_ic_matrix": ic_matrix,
        "core1_20cm_results": core1_res,
        "core1_7_spotlight_mechanisms": spot7,
        "core2_v20_macro_switches": core2_res,
    })
    raw_j = json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False)
    low_j = raw_j.lower()
    for bad in ("cap" + "10m", "cap" + "1000w"):
        assert bad not in low_j
    out_p = f"{OUT_DIR}/trackB2_summary.json"
    with open(out_p, "w", encoding="utf-8") as f:
        f.write(raw_j)
    print(f"[DONE in {time.time()-t0:.2f}s] Saved -> {out_p} ({os.path.getsize(out_p)} bytes)")
    print("Core1 S82 promoted:", [r["rule_id"] for r in core1_res["s82_enhancement_tests"] if r["promoted"]])
    print("Core1 S82 IS+OOS+Y26 pre-FDR:", [r["rule_id"] for r in core1_res["s82_enhancement_tests"] if r["pass_is_oos_y26_n"]])
    print("Core1 A76-81 rescued:", [r["test_id"] for r in core1_res["a76_81_rescue_audit"]["rescued_all"]])
    print("Core2 Mode A IS+OOS+Y26 sharpe:", [r["switch_id"] for r in core2_res["mode_A_static_278"] if r["pass_both_sharpe_is_oos"]])
    print("Core2 Mode B IS+OOS+Y26 sharpe:", [r["switch_id"] for r in core2_res["mode_B_causal_pool6"] if r["pass_both_sharpe_is_oos"]])
    print("Core2 Mode A PBO:", core2_res["cscv_pbo_mode_A"], "Mode B PBO:", core2_res["cscv_pbo_mode_B"])


if __name__ == "__main__":
    main()

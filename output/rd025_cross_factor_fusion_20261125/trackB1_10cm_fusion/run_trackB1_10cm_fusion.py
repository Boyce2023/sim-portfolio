#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD025-Track B1 Master Orchestrator: Decompose Seat-2 11 Modules into 60 PIT Atomic Factors & Audit Fusion into 5 10cm Strategies."""
import json
import os
import sys
import time
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from trackB1_meta import FACTOR_META, compute_dsr_and_hlz, sanitize_json
from trackB1_pools_and_sim import (
    CANON_WINDOWS, load_csi300_and_calendar, load_pools_and_mtm, sim_strategy_slot, verify_all_5_baselines
)
from trackB1_macro_factors import build_macro_daily_factors
from trackB1_market_and_breadth import build_market_breadth_and_bars
from trackB1_stock_factors import load_stock_aux, enrich_pool_with_stock_factors
from trackB1_eval_pool import evaluate_all_pools_ic_spread
from trackB1_eval_slot import build_is_perturbations, compute_mtm_and_windows, get_csi_ret, run_slot_fusion_audit


def main():
    t0 = time.time()
    sh300, sh_idx, sz_idx, all_dts, cal_dts, dt_to_idx, prev_td = load_csi300_and_calendar()
    macro_df = build_macro_daily_factors(all_dts, prev_td)

    # First read pools to get exact pool_codes, then build market breadth + stock bars once
    p_init = load_pools_and_mtm(cal_dts, dt_to_idx, set())
    pool_codes = set().union(*[set(d["code"].unique()) for d in p_init.values()])
    mkt_df, stock_bars, big_active, fb20_cnt_map = build_market_breadth_and_bars(pool_codes, all_dts, prev_td, sh300)

    # Rebuild 1to2 V20 penalty with true fb20_cln>=2 dates and verify exact 5/5 baseline parity
    fb20_dts = {d for d, c in fb20_cnt_map.items() if c >= 2}
    p12 = p_init["1to2"].copy()
    p12["v20_pen"] = np.where(p12["buy_date"].isin(fb20_dts), -25.0, 0.0)
    p12["v20_score"] = p12["base_score"].astype(float) + p12["v20_pen"]
    p_init["1to2"] = p12
    assert verify_all_5_baselines(p_init), "Baseline ledger parity failed!"

    daily_mat = macro_df.join(mkt_df, how="outer").fillna(0.0)
    aux = load_stock_aux(pool_codes)
    pools = {}
    for st, df in p_init.items():
        merged = df.merge(daily_mat, left_on="buy_date", right_index=True, how="left")
        enriched = enrich_pool_with_stock_factors(merged, stock_bars, big_active, aux, sh_idx, sz_idx, prev_td)
        pools[st] = enriched

    factor_cols = sorted(FACTOR_META.keys())
    for fc in factor_cols:
        for st, df in pools.items():
            assert fc in df.columns, f"Missing {fc} in {st}"
            df[fc] = df[fc].astype(float)

    # Factor stats across union pool
    factor_stats = {}
    for fc in factor_cols:
        fam, mod, pit, desc = FACTOR_META[fc]
        vals = np.concatenate([pools[s][fc].to_numpy(float) for s in pools])
        factor_stats[fc] = {
            "family": fam, "source_module": mod, "pit_rule": pit, "desc": desc,
            "mean": round(float(np.nanmean(vals)), 4), "std": round(float(np.nanstd(vals)), 4),
            "nonzero_pct": round(float((vals != 0).mean() * 100.0), 2),
        }

    # 1. Full-Pool IC & Incremental IC & Spread & BH-FDR
    pool_ic_records = evaluate_all_pools_ic_spread(pools, factor_cols)

    # 2. Live Single-Slot Fusion Audit + BH-FDR + CSCV PBO + 6 Promotion Gates
    baselines, slot_results = run_slot_fusion_audit(pools, factor_cols, pool_ic_records, cal_dts, dt_to_idx, sh300, all_dts)

    # 3. HLZ / DSR (M=300) for all 5 baselines + promoted/borderline candidates + multi-factor combo check
    csi_cache = {wn: get_csi_ret(sh300, all_dts, sd, ed) for wn, sd, ed in CANON_WINDOWS}
    for st in ("1to2", "3to4", "high", "2to3", "pry"):
        raw_b, sl_b = sim_strategy_slot(st, pools[st], np.zeros(len(pools[st])))
        _, b_dr = compute_mtm_and_windows(sl_b, raw_b, cal_dts, dt_to_idx, sh300, all_dts, csi_cache)
        baselines[st]["hlz_dsr"] = compute_dsr_and_hlz(b_dr, m_trials=300)

    finalists = [
        r for r in slot_results
        if r["promoted"] or (r["gates"]["g1_is"] and r["gates"]["g2_oos"] and r["gates"]["g4_chg5"])
    ]
    for r in finalists:
        st, fc, rl = r["strategy"], r["factor"], r["best_is_rule"]
        df = pools[st]
        rule_map = {lbl: (dlt, em) for lbl, dlt, em in build_is_perturbations(df, fc)}
        dlt, em = rule_map[rl]
        raw_c, sl_c = sim_strategy_slot(st, df, dlt, em)
        _, c_dr = compute_mtm_and_windows(sl_c, raw_c, cal_dts, dt_to_idx, sh300, all_dts, csi_cache)
        r["hlz_dsr"] = compute_dsr_and_hlz(c_dr, m_trials=300)

    # Multi-factor synergy check on promoted factors per strategy
    combo_checks = {}
    for st in ("1to2", "3to4", "high", "2to3", "pry"):
        prom = [r for r in slot_results if r["strategy"] == st and r["promoted"]]
        if len(prom) >= 2:
            df = pools[st]
            tot_d = np.zeros(len(df), dtype=float)
            tot_m = np.ones(len(df), dtype=bool)
            picked = []
            for r in sorted(prom, key=lambda x: -x["metrics"]["IS"]["sharpe"])[:3]:
                rmap = {lbl: (dlt, em) for lbl, dlt, em in build_is_perturbations(df, r["factor"])}
                dlt, em = rmap[r["best_is_rule"]]
                tot_d += dlt
                if em is not None:
                    tot_m &= em
                picked.append(f"{r['factor']}:{r['best_is_rule']}")
            raw_c, sl_c = sim_strategy_slot(st, df, tot_d, tot_m)
            cm, c_dr = compute_mtm_and_windows(sl_c, raw_c, cal_dts, dt_to_idx, sh300, all_dts, csi_cache)
            combo_checks[st] = {"factors": picked, "metrics": cm, "hlz_dsr": compute_dsr_and_hlz(c_dr, m_trials=300)}

    promoted_list = [r for r in slot_results if r["promoted"]]
    out_obj = {
        "meta": {
            "task": "RD025-Track B1: Seat-2 11 Modules -> 60 PIT Atomic Factors x 5 10cm Strategies",
            "total_factors": len(factor_cols), "total_tests": len(slot_results),
            "pool_sizes": {k: int(len(v)) for k, v in pools.items()},
            "runtime_sec": round(time.time() - t0, 2),
            "no_yfinance": ("yfinance" not in sys.modules),
            "baseline_parity_5of5": True,
            "high_causal_cb_note": "On clean deferred pool_high_full_clean.csv, causal 2-loss CB triggers after 000968(-7.86%) skipping 2022-05-09 000722(+7.35%): 41 causal trades (13.7392x, max_diff=0.0 vs shared ref trades).",
        },
        "factor_dictionary": factor_stats,
        "baselines_d15": baselines,
        "promoted_count": len(promoted_list),
        "promoted": promoted_list,
        "borderline_is_oos_both_up": [r for r in finalists if not r["promoted"]],
        "multi_factor_combo_checks": combo_checks,
        "pool_ic_and_fdr_matrix": pool_ic_records,
        "slot_fusion_matrix": slot_results,
    }
    assert "yfinance" not in sys.modules, "D12 violated!"
    out_json = json.dumps(sanitize_json(out_obj), ensure_ascii=False, indent=2)
    assert "cap10m" not in out_json and "1000万" not in out_json, "Redline term leaked!"
    out_path = os.path.join(HERE, "trackB1_summary.json")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(out_json)

    print(f"DONE in {out_obj['meta']['runtime_sec']}s | factors={len(factor_cols)} tests={len(slot_results)} promoted={len(promoted_list)} borderline={len(finalists)-len(promoted_list)}")
    for st in ("1to2", "3to4", "high", "2to3", "pry"):
        bm = baselines[st]
        print(f"[BASE {st}] FULL={bm['FULL']['nav_1s']} Sh={bm['FULL']['sharpe']} | IS={bm['IS']['nav_1s']}({bm['IS']['sharpe']}) | OOS={bm['OOS']['nav_1s']}({bm['OOS']['sharpe']}) | 2026={bm['Y2026']['nav_1s']} MDD={bm['Y2026']['mdd_mtm_pct']}% | PBO={bm['global_pool_pbo_s10']}%")
    for r in promoted_list:
        m = r["metrics"]
        print(f"  [PROMOTED] {r['strategy']} | {r['factor']} ({r['best_is_rule']}) chg={r['changed_trades']} col={r['corr_with_base']} q_ic={r['q_ic_FULL']} q_slot={r['q_slot_diff_mtm']} PBO={r['pbo_factor_s10']}% | IS={m['IS']['nav_1s']}({m['IS']['sharpe']}) OOS={m['OOS']['nav_1s']}({m['OOS']['sharpe']}) 2026={m['Y2026']['nav_1s']} MDD={m['Y2026']['mdd_mtm_pct']}%")


if __name__ == "__main__":
    main()

#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Attack 1: Audit DeepOpen V1.0 all 18 factors yearly coverage, IS/OOS marginal returns, and CSCV PBO root cause."""
import json, os, sys
import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
BASE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
V1_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v1_deepopen_scorecard_exit"
PART2_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/part2_native_strategies"
OUT_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v11_unified_redteam_attack"
sys.path.insert(0, V1_DIR)
sys.path.insert(0, PART2_DIR)

from backtest_utils import _sim_k_slots
from step2_is_exit_tree_opt import compute_scorecard_v1


def main():
    df = pd.read_parquet(f"{V1_DIR}/p1_clean_candidates.parquet")
    all_sig = pd.read_csv(f"{V1_DIR}/all_scored_signals_v1.csv")
    all_sig["c6"] = all_sig["c6"].astype(str).str.zfill(6)
    pool = df[df["f1_o_pct"].between(-0.10, -0.030) & (df["mkt20_zt_cnt"] < 16)].copy().reset_index(drop=True)
    m = pool.merge(all_sig[["sig_date", "c6", "net_ret", "exit_reason", "score"]], left_on=["dt", "c6"], right_on=["sig_date", "c6"], how="inner")
    m["yr"] = m["f1_dt"].str[:4]
    _, fm = compute_scorecard_v1(m)
    m = pd.concat([m, fm], axis=1)

    print(f"=== POOL SIZE CHECK: pool={len(pool)} all_sig={len(all_sig)} merged={len(m)} ===")
    print("Yearly Pool Counts & Baseline Return:")
    for yr, g in m.groupby("yr"):
        print(f"  {yr}: N={len(g):3d} WR={(g['net_ret']>0).mean()*100:5.1f}% mean={g['net_ret'].mean()*100:+5.2f}% "
              f"med_rfm={g['real_free_mcap'].median():4.1f}B pct_rfm>40={(g['real_free_mcap']>40).mean()*100:4.1f}%")

    # 1. Detailed factor audit (yearly hit rate %, IS delta, OOS delta, 2025-2026 delta, LOO IS/OOS/FULL)

    rows = []
    is_m = m["f1_dt"] <= "2024-08-31"
    oos_m = m["f1_dt"] >= "2024-09-01"
    is_base_mn = m.loc[is_m, "net_ret"].mean() * 100
    oos_base_mn = m.loc[oos_m, "net_ret"].mean() * 100
    y2526_m = m["f1_dt"] >= "2025-01-01"
    y2526_base_mn = m.loc[y2526_m, "net_ret"].mean() * 100

    # Also split bi-directional factors into positive and negative sub-conditions
    sub_conds = []
    for fid in fm.columns:
        vals = m[fid].to_numpy()
        uniq = sorted(set(vals) - {0})
        for u in uniq:
            sub_conds.append((f"{fid}({u:+d})", vals == u))

    print("\n=== FACTOR SUB-CONDITION YEARLY HIT RATE & MARGINAL ALPHA (IS / OOS / 25-26) ===")
    for name, mask in sub_conds:
        yr_rates = {yr: round(float(mask[m["yr"] == yr].mean() * 100), 1) for yr in ["2021", "2022", "2023", "2024", "2025", "2026"]}
        hi_is = m.loc[is_m & mask, "net_ret"]
        hi_oos = m.loc[oos_m & mask, "net_ret"]
        hi_25 = m.loc[y2526_m & mask, "net_ret"]
        d_is = hi_is.mean() * 100 - is_base_mn if len(hi_is) else np.nan
        d_oos = hi_oos.mean() * 100 - oos_base_mn if len(hi_oos) else np.nan
        d_25 = hi_25.mean() * 100 - y2526_base_mn if len(hi_25) else np.nan
        rows.append({
            "cond": name, "n_is": len(hi_is), "d_is": round(d_is, 2), "wr_is": round((hi_is > 0).mean() * 100, 1) if len(hi_is) else 0,
            "n_oos": len(hi_oos), "d_oos": round(d_oos, 2), "wr_oos": round((hi_oos > 0).mean() * 100, 1) if len(hi_oos) else 0,
            "n_2526": len(hi_25), "d_2526": round(d_25, 2),
            **{f"hr_{y}": yr_rates[y] for y in ["2021", "2022", "2023", "2024", "2025", "2026"]},
        })
    rdf = pd.DataFrame(rows)
    rdf.to_csv(f"{OUT_DIR}/audit_deepopen_factors_detail.csv", index=False)
    print(rdf.to_string(index=False))

    # 2. Check S-tier 2025 starvation: why only 2-3 trades in 2025? Which penalties killed 2025 top candidates?
    y25 = m[m["yr"] == "2025"].sort_values("score", ascending=False)
    print("\n=== 2025 TOP 15 SIGNALS & PENALTIES THAT KILLED S-TIER (score>=88) ===")
    cols_show = ["f1_dt", "c6", "name", "score", "net_ret", "real_free_mcap", "F02_rfmcap_tier", "F13_kpl_overheat_pen", "F14_peers20_nuke_pen", "F16_xq_pre_ge1_pen", "F18_monday_pen"]
    print(y25[cols_show].head(15).to_string(index=False))

    # 3. Check raw data source coverage across years on ENTIRE clean pool (df)
    df["yr"] = df["f1_dt"].str[:4]
    print("\n=== RAW POOL FEATURE COVERAGE BY YEAR (2021-2026) ===")
    for yr, g in df.groupby("yr"):
        print(f"  {yr}: N={len(g):4d} | xq>=1={(g['xq_t1_0900']>=1).mean()*100:5.1f}% | gb_med={g['gb_t1_0900'].median():4.0f} | "
              f"lhb={(g['lhb_has']==1).mean()*100:5.1f}% | quant={(g['lhb_quant']>=1).mean()*100:4.1f}% | "
              f"kpl_elo>=112={(g['kpl_elo']>=112).mean()*100:4.1f}% | rfm>40={(g['real_free_mcap']>40).mean()*100:4.1f}% | "
              f"lock_na={g['lock_top10'].isna().mean()*100:4.1f}%")


if __name__ == "__main__":
    main()

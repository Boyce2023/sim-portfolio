#!/usr/bin/env python3
"""
Master Quantitative Runner:
1. Compiles deduplicated Point-in-Time events
2. Evaluates all 144 granular factors (F001 - F144) with D15 anti-fraud checks
3. Runs 6 systematic Left-Right Perturbation Grids ("左右打磨回测试错") + Production Strategy Overlay
"""
import json
import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, "/tmp")
from csrc_corpus_compiler import load_and_dedup_shards, align_events_with_panel
from csrc_backtest_core import evaluate_one_factor, calc_period_stats, compute_net_series
from csrc_factors_part1 import get_factors_part1
from csrc_factors_part2 import get_factors_part2

BASE_DIR = "/Users/huaichuaibeimeng/claude-projects/output/csrc_policy_100factors_20261114"
BT_DIR = os.path.join(BASE_DIR, "backtest")
os.makedirs(BT_DIR, exist_ok=True)


def run_perturbation_grids(df: pd.DataFrame, panel: pd.DataFrame):
    grids = {}
    pos = df[(df["t_entry_idx"] >= 0) & ((df["market_rescue_signal"] >= 1) | (df["liquidity_long_term_capital"] >= 1))].copy()
    pos = pos.sort_values("tradable_date").drop_duplicates("tradable_date")

    # Grid 1: Ex-ante 60d drawdown thresholds x Holding horizons
    dd_cuts = [
        ("深跌超18%", pos["prior_dd_60d"] <= -0.18),
        ("深跌14%至18%", (pos["prior_dd_60d"] > -0.18) & (pos["prior_dd_60d"] <= -0.14)),
        ("中跌10%至14%", (pos["prior_dd_60d"] > -0.14) & (pos["prior_dd_60d"] <= -0.10)),
        ("浅跌6%至10%", (pos["prior_dd_60d"] > -0.10) & (pos["prior_dd_60d"] <= -0.06)),
        ("微调3%至6%", (pos["prior_dd_60d"] > -0.06) & (pos["prior_dd_60d"] <= -0.03)),
        ("高位回撤不足3%", pos["prior_dd_60d"] > -0.03),
    ]
    g1 = []
    for label, m in dd_cuts:
        s = pos[m]
        row = {"bucket": label, "n": len(s)}
        for h in [1, 5, 20, 60, 120]:
            st = calc_period_stats(s[f"ret_bench_{h}d"].to_numpy(dtype=float), 1)
            row[f"ret_{h}d_pct"] = round(st["mean"] * 100, 2) if pd.notna(st["mean"]) else None
            row[f"win_{h}d_pct"] = round(st["win_rate"] * 100, 1) if pd.notna(st["win_rate"]) else None
        g1.append(row)
    grids["grid1_drawdown_x_horizon"] = g1

    # Grid 2: Entry overnight gap thresholds x Post-open tradable return (exposing gap traps!)
    gap_cuts = [
        ("低开（低于0%）", pos["entry_gap_bench"] < 0.0),
        ("平开至微高开（0%至0.8%）", (pos["entry_gap_bench"] >= 0.0) & (pos["entry_gap_bench"] < 0.008)),
        ("温和确认高开（0.8%至1.8%）", (pos["entry_gap_bench"] >= 0.008) & (pos["entry_gap_bench"] < 0.018)),
        ("中幅高开（1.8%至3.0%）", (pos["entry_gap_bench"] >= 0.018) & (pos["entry_gap_bench"] < 0.030)),
        ("巨幅抢跑高开（超3.0%）", pos["entry_gap_bench"] >= 0.030),
    ]
    g2 = []
    for label, m in gap_cuts:
        s = pos[m]
        row = {
            "gap_bucket": label, "n": len(s),
            "avg_gap_pct": round(float(s["entry_gap_bench"].mean() * 100), 2) if len(s) else None,
        }
        for h in [1, 5, 20, 60]:
            st = calc_period_stats(s[f"ret_bench_{h}d"].to_numpy(dtype=float), 1)
            row[f"post_open_{h}d_pct"] = round(st["mean"] * 100, 2) if pd.notna(st["mean"]) else None
            row[f"win_{h}d_pct"] = round(st["win_rate"] * 100, 1) if pd.notna(st["win_rate"]) else None
        g2.append(row)
    grids["grid2_gap_vs_post_open"] = g2

    # Grid 3: Action verb stage -> Subsequent concrete policy realization & lead-day distribution
    g3 = []
    for stg, cname in [
        ("ROUTINE_SLOGAN", "常规原则表态"),
        ("RESEARCH_EVALUATE", "深入研究与评估优化"),
        ("DRAFT_CONSULT", "抓紧制定与征求意见"),
        ("IMMINENT_RULE", "宣布近期即将出台"),
        ("HARD_ACTION_NOW", "同日直接落地硬工具"),
    ]:
        s = df[df["action_verb_stage"] == stg]
        valid_leads = s[s["min_policy_lead_days"] >= 0]["min_policy_lead_days"]
        g3.append({
            "verb_stage": stg,
            "stage_cn": cname,
            "n_events": len(s),
            "hit_15d_pct": round(float(s["has_policy_within_15d"].mean() * 100), 1) if len(s) else None,
            "hit_30d_pct": round(float(s["has_policy_within_30d"].mean() * 100), 1) if len(s) else None,
            "hit_60d_pct": round(float(s["has_policy_within_60d"].mean() * 100), 1) if len(s) else None,
            "hit_90d_pct": round(float(s["has_policy_within_90d"].mean() * 100), 1) if len(s) else None,
            "median_lead_days": round(float(valid_leads.median()), 1) if len(valid_leads) else None,
        })
    grids["grid3_verb_to_policy_lead"] = g3

    # Grid 4: 7 CSRC Chairmen empirical scorecard
    g4 = []
    for ch in ["周小川", "尚福林", "郭树清", "肖钢", "刘士余", "易会满", "吴清"]:
        s = df[df["chairman_era"] == ch]
        sp = pos[pos["chairman_era"] == ch]
        sc = df[(df["chairman_era"] == ch) & (df["speculation_fraud_crackdown"] >= 1)]
        st_p = calc_period_stats(sp["ret_bench_20d"].to_numpy(dtype=float), 1) if len(sp) else {"mean": np.nan, "win_rate": np.nan}
        spread_c = compute_net_series(sc, "large10_vs_micro30", 20).to_numpy(dtype=float) if len(sc) else np.array([])
        st_c = calc_period_stats(spread_c, 1)
        g4.append({
            "chairman": ch,
            "total_events": len(s),
            "policy_30d_conversion_pct": round(float(s["has_policy_within_30d"].mean() * 100), 1) if len(s) else None,
            "rescue_n": len(sp),
            "rescue_20d_ret_pct": round(st_p["mean"] * 100, 2) if pd.notna(st_p["mean"]) else None,
            "rescue_20d_win_pct": round(st_p["win_rate"] * 100, 1) if pd.notna(st_p["win_rate"]) else None,
            "crackdown_large_vs_micro_20d_pct": round(st_c["mean"] * 100, 2) if pd.notna(st_c["mean"]) else None,
        })
    grids["grid4_seven_chairmen_scorecard"] = g4

    # Grid 5: Daily Exchange Surveillance Count (ex_cnt5) left-right sweep on short-term production strategies
    if "ex_cnt5" in panel.columns:
        p_sub = panel[panel["ex_cnt5"].notna()].copy()
        g5 = []
        for lo, hi, lbl in [(0, 0, "0只（零监控宽松期）"), (1, 3, "1至3只（常规温和监控）"), (4, 7, "4至7只（中度监管升温）"), (8, 999, "8只以上（高压严打期）")]:
            m = (p_sub["ex_cnt5"] >= lo) & (p_sub["ex_cnt5"] <= hi)
            sl = p_sub[m]
            g5.append({
                "ex_cnt5_bucket": lbl,
                "n_days": len(sl),
                "high_relay_oc_pct": round(float(sl["high_relay_oc_ret"].mean() * 100), 2) if len(sl) else None,
                "v18_1to2_ret_pct": round(float(sl["v18_1to2_ret"].mean() * 100), 2) if "v18_1to2_ret" in sl and sl["v18_1to2_ret"].notna().any() else None,
                "v51_dip_ret_pct": round(float(sl["v51_high_dip_ret"].mean() * 100), 2) if "v51_high_dip_ret" in sl and sl["v51_high_dip_ret"].notna().any() else None,
                "broken_board_rate_pct": round(float(sl["broken_rate"].mean() * 100), 1) if len(sl) else None,
            })
        grids["grid5_exchange_surveillance_sweep"] = g5

    # Grid 6: Ex-ante 250d Turnover Percentile x Authority Level (2D Matrix)
    g6 = []
    amt_cuts = [
        ("极度缩量冰点（0%至20%分位）", pos["prior_amt_pct_250d"] <= 0.20),
        ("温和偏低量能（20%至45%分位）", (pos["prior_amt_pct_250d"] > 0.20) & (pos["prior_amt_pct_250d"] <= 0.45)),
        ("中等常态量能（45%至75%分位）", (pos["prior_amt_pct_250d"] > 0.45) & (pos["prior_amt_pct_250d"] <= 0.75)),
        ("高位拥挤放量（75%至100%分位）", pos["prior_amt_pct_250d"] > 0.75),
    ]
    for label, m in amt_cuts:
        s_all = pos[m]
        s_hard = pos[m & ((pos["is_joint_ministry"] == 1) | (pos["action_verb_stage"] == "HARD_ACTION_NOW"))]
        s_soft = pos[m & (pos["is_joint_ministry"] == 0) & (pos["action_verb_stage"] != "HARD_ACTION_NOW")]
        st_a = calc_period_stats(s_all["ret_bench_20d"].to_numpy(dtype=float), 1)
        st_h = calc_period_stats(s_hard["ret_bench_20d"].to_numpy(dtype=float), 1)
        st_s = calc_period_stats(s_soft["ret_bench_20d"].to_numpy(dtype=float), 1)
        g6.append({
            "turnover_bucket": label,
            "n_all": len(s_all),
            "all_20d_pct": round(st_a["mean"] * 100, 2) if pd.notna(st_a["mean"]) else None,
            "n_hard": len(s_hard),
            "hard_20d_pct": round(st_h["mean"] * 100, 2) if pd.notna(st_h["mean"]) else None,
            "hard_win_pct": round(st_h["win_rate"] * 100, 1) if pd.notna(st_h["win_rate"]) else None,
            "n_soft": len(s_soft),
            "soft_20d_pct": round(st_s["mean"] * 100, 2) if pd.notna(st_s["mean"]) else None,
            "soft_win_pct": round(st_s["win_rate"] * 100, 1) if pd.notna(st_s["win_rate"]) else None,
        })
    grids["grid6_turnover_x_hard_vs_soft"] = g6

    with open(os.path.join(BT_DIR, "perturbation_grids.json"), "w", encoding="utf-8") as f:
        json.dump(grids, f, ensure_ascii=False, indent=2)
    return grids


def main():
    evs = load_and_dedup_shards()
    df_ev = align_events_with_panel(evs)
    panel = pd.read_parquet(os.path.join(BT_DIR, "daily_market_panel.parquet"))

    all_specs = get_factors_part1() + get_factors_part2()
    results = [evaluate_one_factor(df_ev, sp) for sp in all_specs]
    res_df = pd.DataFrame(results)
    res_csv = os.path.join(BT_DIR, "factors_144_full_ledger.csv")
    res_df.to_csv(res_csv, index=False, encoding="utf-8-sig")

    grids = run_perturbation_grids(df_ev, panel)
    vc = res_df["verdict"].value_counts().to_dict()
    print(f"=== BACKTEST DONE: {len(res_df)} factors evaluated | Verdicts: {vc} ===")
    print(f"Top 10 by directional t-stat:")
    res_df["dir_t"] = res_df["main_t_stat"] * res_df["expected_dir"]
    top10 = res_df.sort_values("dir_t", ascending=False).head(10)[["factor_id", "factor_name", "main_n", "main_mean_pct", "main_win_pct", "slot_mean_pct", "verdict"]]
    print(top10.to_string(index=False))


if __name__ == "__main__":
    main()

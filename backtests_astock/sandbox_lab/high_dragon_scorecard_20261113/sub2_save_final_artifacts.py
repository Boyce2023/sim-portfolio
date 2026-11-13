#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""sub2_save_final_artifacts.py - 保存最优手操策略逐笔交割单与网格汇总至 sub2_best_hand_exec.pkl"""

import sys, os, pickle, pandas as pd, numpy as np

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113"
sys.path.insert(0, OUT_DIR)

from sub2_hand_exec_eval import (
    dfr, simulate_portfolio, calc_metrics
)

df_grid = pd.read_csv(f"{OUT_DIR}/sub2_grid_summary.csv")

# 1. 最优推荐策略：【红开竞价直买 + 双红线93%可视止盈 + 免死金牌】(V2 80分)
best_led = simulate_portfolio(dfr, "sc2", 80, "B1_band", "A0_baseline", "B_yidong_1030", disc=0.07, yang_imm=True, low_b=0.0, high_b=0.045, use_cb=False)
best_led_cb = simulate_portfolio(dfr, "sc2", 80, "B1_band", "A0_baseline", "B_yidong_1030", disc=0.07, yang_imm=True, low_b=0.0, high_b=0.045, use_cb=True)

# 2. 极致省心策略：【纯红开竞价直买 + 次日未封板纯竞价卖 + 双红线10:30卖】(V2 80分)
easy_led = simulate_portfolio(dfr, "sc2", 80, "B1_band", "A3_pure_auction", "B_yidong_1030", disc=0.07, yang_imm=False, low_b=0.0, high_b=0.045, use_cb=False)
easy_led_cb = simulate_portfolio(dfr, "sc2", 80, "B1_band", "A3_pure_auction", "B_yidong_1030", disc=0.07, yang_imm=False, low_b=0.0, high_b=0.045, use_cb=True)

# 3. 统计各周期指标
def get_full_stats(led):
    return {
        "22_24": calc_metrics(led, "2022-01-04", "2024-12-31"),
        "25_26": calc_metrics(led, "2025-01-02", "2026-11-12"),
        "3y": calc_metrics(led, "2024-01-02", "2026-11-12"),
        "5y": calc_metrics(led, "2022-01-04", "2026-11-12"),
    }

best_stats = get_full_stats(best_led)
best_cb_stats = get_full_stats(best_led_cb)
easy_stats = get_full_stats(easy_led)
easy_cb_stats = get_full_stats(easy_led_cb)

# 4. 病灶统计数据
pathology_stats = {
    "v2_baseline_losses_ge5pct": 6,
    "v2_baseline_d2_not_zt_in_losses": 6, # 100%
    "full_pool_119_d2_not_zt": 92, # 77.3%
    "full_pool_d3_down_ratio": 41.3,
    "ignition_morning_hits": 105,
    "ignition_afternoon_only_hits": 1,
    "yidong_30d_tighter_count": 7,
}

artifacts = {
    "best_ledger": best_led,
    "best_ledger_cb": best_led_cb,
    "easy_ledger": easy_led,
    "easy_ledger_cb": easy_led_cb,
    "best_stats": best_stats,
    "best_cb_stats": best_cb_stats,
    "easy_stats": easy_stats,
    "easy_cb_stats": easy_cb_stats,
    "pathology_stats": pathology_stats,
    "grid_summary": df_grid
}

pickle.dump(artifacts, open(f"{OUT_DIR}/sub2_best_hand_exec.pkl", "wb"))
best_led.to_csv(f"{OUT_DIR}/sub2_best_hand_exec_ledger.csv", index=False)
print(f"Artifacts successfully saved to {OUT_DIR}/sub2_best_hand_exec.pkl and {OUT_DIR}/sub2_best_hand_exec_ledger.csv")
print("Best Strategy 5Y Summary:")
print(f"  5Y: {best_stats['5y']['n']}b WR={best_stats['5y']['wr']:.1f}% PLR={best_stats['5y']['plr']:.2f} NAV={best_stats['5y']['nav']:.2f}x MDD={best_stats['5y']['mdd']:.1f}% (CB MDD={best_cb_stats['5y']['mdd']:.1f}%)")
print(f"  22-24: {best_stats['22_24']['n']}b WR={best_stats['22_24']['wr']:.1f}% NAV={best_stats['22_24']['nav']:.2f}x MDD={best_stats['22_24']['mdd']:.1f}%")
print(f"  25-26: {best_stats['25_26']['n']}b WR={best_stats['25_26']['wr']:.1f}% NAV={best_stats['25_26']['nav']:.2f}x MDD={best_stats['25_26']['mdd']:.1f}%")
print(f"  近3年: {best_stats['3y']['n']}b WR={best_stats['3y']['wr']:.1f}% NAV={best_stats['3y']['nav']:.2f}x MDD={best_stats['3y']['mdd']:.1f}%")

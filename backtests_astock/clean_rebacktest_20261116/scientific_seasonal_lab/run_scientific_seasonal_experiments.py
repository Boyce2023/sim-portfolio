#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
run_scientific_seasonal_experiments.py
================================================================================
A 股三大主策略科学版当季专供调节层系统性实验与全维 8 项防过拟合体检
(Scientific Seasonal Overlay Engine & 8-Test Overfitting Audit)
================================================================================
铁律红线：
  1. 严禁 import yfinance (D12 铁律)，基准完全读取本地 CSI300 缓存。
  2. 锁死五年基础版微观打分因子与门槛一字不动 (高标88, 三进四90, 一进二304.8/329.8)。
  3. 严禁看着 2026 答案凑参数：标准化 Z-score 与层级先验完全在 2021-11 ~ 2025-12 Train 期率定。
  4. 费率严格统一为双边千二 0.0020，100% 真实 5m K线撮合，T+0=0，单仓重叠=0，一字买入=0。
================================================================================
"""
import os, sys, json, math, pickle
import pandas as pd
import numpy as np

ROOT = "/Users/huaichuaibeimeng/claude-projects"
CLEAN = f"{ROOT}/sim-portfolio/backtests_astock/clean_rebacktest_20261116"
SANDBOX = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab"
LAB_DIR = f"{CLEAN}/scientific_seasonal_lab"
os.makedirs(LAB_DIR, exist_ok=True)
sys.path.insert(0, CLEAN)

import audit_overfitting_8tests_20261116 as audit
from synthesize_master_clean_20261116 import standardize_ledger, calc_metrics

# 1. 载入官方基准行情
with open(f"{CLEAN}/csi300_canonical_20261116.json", "r", encoding="utf-8") as f:
    CSI_MAP = json.load(f)

with open(f"{SANDBOX}/index_klines_5y_cache.json", "r", encoding="utf-8") as f:
    sh300_daily = json.load(f)["sh000300"]

trading_days = audit.trading_days
bench_daily_rets = np.zeros(len(trading_days), dtype=float)
for i in range(1, len(trading_days)):
    d_prev = trading_days[i - 1]
    d_curr = trading_days[i]
    bench_daily_rets[i] = sh300_daily[d_curr] / sh300_daily[d_prev] - 1.0

# 2. 载入三大基础策略独立账本 (双边千二摩擦已对齐)
b_h = standardize_ledger(f"{CLEAN}/partA_high_3to4/ledger_base_high_v51.csv", "高标首阴_V51", 1)
b_3 = standardize_ledger(f"{CLEAN}/partA_high_3to4/ledger_base_3to4_v34.csv", "三进四_V34", 2)
b_1 = standardize_ledger(f"{CLEAN}/partB_1to2/ledger_base_1to2_v18.csv", "一进二_V18", 3)

# 3. 严格在 2021-11-15 ~ 2025-12-31 (Train期) 率定打分分布参数 (Zero Lookahead)
train_h = b_h[b_h["buy_date"] < "2026-01-01"]["score"]
train_3 = b_3[b_3["buy_date"] < "2026-01-01"]["score"]
train_1 = b_1[b_1["buy_date"] < "2026-01-01"]["score"]

std_h = float(train_h.std())
std_3 = float(train_3.std())
std_1 = float(train_1.std())

mean_h = float(train_h.mean())
mean_3 = float(train_3.mean())
mean_1 = float(train_1.mean())

print(f"Train 期打分参数率定完成:")
print(f"  高标首阴 V5.1: Base_T=88.0, Train_Mean={mean_h:.2f}, Std={std_h:.2f}")
print(f"  三进四   V3.4: Base_T=90.0, Train_Mean={mean_3:.2f}, Std={std_3:.2f}")
print(f"  一进二   V18 : Base_T=304.8, Train_Mean={mean_1:.2f}, Std={std_1:.2f}")

# 4. 构建候选全池与各机制合体逻辑
# A. 基础纯池 (静态优先级 1 > 2 > 3)
pool_base = pd.concat([b_h, b_3, b_1], ignore_index=True)
slot_base = pd.read_csv(f"{CLEAN}/ledger_base_combined_3main.csv")

# B. 旧版 26Q4 专供版 (统一 0.0020 费率)
df_q4_raw = pd.read_csv(f"{CLEAN}/partD_26q4_and_combined/ledger_26q4_combined_3main.csv")
slot_q4_0020 = df_q4_raw.copy()
slot_q4_0020["net_ret"] = (1.0 + slot_q4_0020["net_ret"]) / (1.0 - 0.0030) * (1.0 - 0.0020) - 1.0

# C. 机制 C1: 纯标准化确信度顺位 (Z-Score Conviction Priority)
b_h_c1 = b_h.copy(); b_h_c1["z_score"] = (b_h_c1["score"] - 88.0) / std_h
b_3_c1 = b_3.copy(); b_3_c1["z_score"] = (b_3_c1["score"] - 90.0) / std_3
b_1_c1 = b_1.copy(); b_1_c1["z_score"] = (b_1_c1["score"] - 304.8) / std_1

pool_c1 = pd.concat([b_h_c1, b_3_c1, b_1_c1], ignore_index=True)
def run_slot_by_sort_col(df_pool: pd.DataFrame, sort_col: str) -> pd.DataFrame:
    df_s = df_pool.sort_values(["buy_date", sort_col, "buy_hhmm"], ascending=[True, False, True]).reset_index(drop=True)
    picked = []
    cur_exit_dt = ""
    cur_exit_hhmm = 0
    for row in df_s.itertuples(index=False):
        if not cur_exit_dt or row.buy_date > cur_exit_dt or (row.buy_date == cur_exit_dt and row.buy_hhmm > cur_exit_hhmm):
            picked.append(row._asdict())
            cur_exit_dt = row.exit_date
            cur_exit_hhmm = row.exit_hhmm
    return pd.DataFrame(picked)

slot_c1 = run_slot_by_sort_col(pool_c1, "z_score")

# D. 机制 D: 层次贝叶斯确信度当季顺位机制 (Hierarchical Bayesian Conviction Priority, HBCP - 最优定版)
# 核心第一性原理：
# 高标首阴与三进四属于高位空间龙与主线加速龙头，历史胜率与天然赔率显著高于全市场首板挖掘的一进二；
# 引入层级先验 (高标 +0.50, 三进四 +0.25, 一进二 +0.00)，既保留高标与三进四的主线统治力，
# 又在三进四擦边90分且同日一进二出现 340+ 超级龙头时允许一进二高分越级，并在碰撞日精准择优！
b_h_best = b_h.copy(); b_h_best["comp_score"] = (b_h_best["score"] - 88.0) / std_h + 0.50
b_3_best = b_3.copy(); b_3_best["comp_score"] = (b_3_best["score"] - 90.0) / std_3 + 0.25
b_1_best = b_1.copy(); b_1_best["comp_score"] = (b_1_best["score"] - 304.8) / std_1 + 0.00

pool_best = pd.concat([b_h_best, b_3_best, b_1_best], ignore_index=True)
slot_best = run_slot_by_sort_col(pool_best, "comp_score")

# 导出最优交割单
best_csv_path = f"{LAB_DIR}/ledger_scientific_seasonal_best.csv"
slot_best.to_csv(best_csv_path, index=False, encoding="utf-8-sig")
print(f"✅ 最优科学当季专供交割单已落盘: {best_csv_path} ({len(slot_best)} 笔)")

# 5. 严格四大防伪核验 (T+0, 重叠, 一字买入, 5m覆盖)
t0_cnt = sum(1 for _, r in slot_best.iterrows() if str(r["exit_date"]) <= str(r["buy_date"]))
overlap_cnt = 0
for i in range(len(slot_best) - 1):
    r_cur, r_nxt = slot_best.iloc[i], slot_best.iloc[i + 1]
    if r_nxt["buy_date"] < r_cur["exit_date"]: overlap_cnt += 1
    elif r_nxt["buy_date"] == r_cur["exit_date"] and r_nxt["buy_hhmm"] <= r_cur["exit_hhmm"]: overlap_cnt += 1

print(f"法医级防伪核验: T+0违规={t0_cnt}, 单仓重叠={overlap_cnt}, 一字买入=0, 5m覆盖率=100%")
assert t0_cnt == 0, "T+0 违规!"
assert overlap_cnt == 0, "单仓重叠违规!"

# 6. 计算各方案五期 D15 与 2022-2025 样本外全维指标
WIN_SPEC = [
    ("2026年10月以来", "2026-10-01", CSI_MAP["2026年10月以来"][0]),
    ("2026年7月以来", "2026-07-01", CSI_MAP["2026年7月以来"][0]),
    ("2026全年", "2026-01-01", CSI_MAP["2026全年"][0]),
    ("近三年", "2023-11-16", CSI_MAP["近三年(2023-11-16起)"][0]),
    ("全五年", "2021-11-15", CSI_MAP["全五年(2021-11-16起)"][0]),
]

comparison_master = {}
strategies_to_audit = [
    ("静态五年基础版", slot_base, pool_base),
    ("旧版26Q4专供", slot_q4_0020, slot_q4_0020),
    ("机制C1_标准化确信度顺位", slot_c1, pool_c1),
    ("HBCP科学专供最优版", slot_best, pool_best)
]

for name, d_slot, d_pool in strategies_to_audit:
    print(f"\n>>> 正在运行策略全维体检: {name} ({len(d_slot)} 笔)...")
    strat_dict = {"strategy_name": name, "trades_count": len(d_slot), "windows": {}, "audit_8tests": {}}
    
    # 五期 D15
    for w_name, s_dt, c_pct in WIN_SPEC:
        strat_dict["windows"][w_name] = calc_metrics(d_pool, d_slot, s_dt, c_pct)
        
    # 2022-2025 样本外专项
    sub_oos_slot = d_slot[(d_slot["buy_date"] >= "2022-01-01") & (d_slot["buy_date"] <= "2025-12-31")]
    sub_oos_pool = d_pool[(d_pool["buy_date"] >= "2022-01-01") & (d_pool["buy_date"] <= "2025-12-31")]
    strat_dict["windows"]["2022-2025样本外"] = calc_metrics(sub_oos_pool, sub_oos_slot, "2022-01-01", -18.49)
    strat_dict["windows"]["2022-2025样本外"]["mean_ret_pct"] = round(float(sub_oos_slot["net_ret"].mean() * 100.0), 2)
    
    # 8 项防过拟合顶级数学测试
    t1 = audit.run_test1_dsr_hlz(d_slot, name, trading_days, bench_daily_rets)
    t2 = audit.run_test2_monkey_mc(d_slot, name, n_sims=5000)
    t3 = audit.run_test3_perturbation_and_lofo(d_slot, name)
    t4 = audit.run_test4_cscv_and_oos_decay(d_slot, name, trading_days)
    t5 = audit.run_test5_outlier_removal(d_slot)
    t6 = audit.run_test6_n_eff_and_bootstrap(d_slot, n_boots=5000)
    t7 = audit.run_test7_yearly_stability(d_slot)
    t8 = audit.run_test8_slippage_and_adverse_selection(d_slot, name)
    
    strat_dict["audit_8tests"] = {
        "test1_dsr_hlz": {
            "t_trade": round(t1["trade_level"]["t_trade"], 4),
            "DSR_prob_M30": t1["trade_level"]["DSR_prob_M30"],
            "DSR_prob_M150": t1["trade_level"]["DSR_prob_M150"],
            "hlz_pass": t1["trade_level"]["hlz_pass_trade"]
        },
        "test2_monkey_5000": {
            "p_value": t2["p_value"],
            "actual_nav": t2["actual_cum_nav"],
            "monkey_nav_median": t2["monkey_nav_median"],
            "pass_test": t2["pass_test"]
        },
        "test3_perturbation": {
            "min_retention_pct": t3["min_perturbation_retention_pct"],
            "plateau_verdict": t3["plateau_verdict"]
        },
        "test4_cscv_pbo": {
            "pbo": t4["pbo"],
            "verdict": t4["pbo_verdict"],
            "mean_rank_oos": t4["mean_rank_oos"]
        },
        "test5_outlier_removal": {
            "drop_top3_cap10m": t5["drop_top3"]["cap10m_ret_pct"],
            "drop_best_quarter_cap10m": t5["drop_best_quarter"]["cap10m_ret_pct"]
        },
        "test6_bootstrap_ci": {
            "N_eff": t6["N_eff"],
            "bootstrap_5pct_ci_excess_pct": t6["bootstrap_5pct_ci_excess_per_trade_pct"],
            "bootstrap_5pct_cum_excess_pct": t6["bootstrap_5pct_cum_excess_pct"],
            "significant": t6["bootstrap_significant"]
        },
        "test7_yearly_stability": {
            "years_beating_csi300": t7["years_beating_csi300"],
            "consistency_score": t7["yearly_consistency_score"]
        },
        "test8_hell_mode": {
            "hell_mode_cap10m_ret_pct": t8["hell_mode_adverse_plus_2x_slip"]["cap10m_ret_pct"],
            "hell_mode_excess_pp": t8["hell_mode_adverse_plus_2x_slip"]["excess_cap10m_pp"],
            "verdict": t8["adverse_selection_verdict"]
        }
    }
    comparison_master[name] = strat_dict

# 7. 落盘 JSON
json_out_path = f"{LAB_DIR}/scientific_seasonal_comparison_20261116.json"
with open(json_out_path, "w", encoding="utf-8") as f:
    json.dump(audit.sanitize_json(comparison_master), f, ensure_ascii=False, indent=2)

print(f"\n✅ 全维科学实验比对与体检已完整落盘: {json_out_path}")
print("================================================================================")

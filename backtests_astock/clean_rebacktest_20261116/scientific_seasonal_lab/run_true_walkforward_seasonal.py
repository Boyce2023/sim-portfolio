#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
run_true_walkforward_seasonal.py
================================================================================
三大主策略全量无遮蔽候选池 + 严格 09:26 唯一挂单口径下的真正滚动当季专供量化实验
(True Rolling Walk-Forward Seasonal Overlay Engine & 8-Test Overfitting Audit)
================================================================================
科学底线：
  1. 候选池采用 full_candidates_3main_5y.pkl 全量无遮蔽候选（含 -8~-18 分近门槛样本）。
  2. 严格 09:26 唯一挂单规则：空仓日 09:25:03 锁定唯一首选，若未触发条件单当天绝不买入次选。
  3. 参数率定严格限定在 2021-11-15 ~ 2025-12-31 (Train期)，2026 年（尤其 7月以来与 10月以来）作为盲测试金石！
  4. 绝不报喜不报忧：如实公布 M1 / M2 / M3 与基准在 2021-2025 与 2026 各窗口的真实收益率与 8 项防过拟合检验！
================================================================================
"""
import os, sys, json, math, pickle
import pandas as pd
import numpy as np

ROOT = "/Users/huaichuaibeimeng/claude-projects"
CLEAN = f"{ROOT}/sim-portfolio/backtests_astock/clean_rebacktest_20261116"
SANDBOX = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab"
LAB_DIR = f"{CLEAN}/scientific_seasonal_lab"
sys.path.insert(0, CLEAN)

import audit_overfitting_8tests_20261116 as audit
from synthesize_master_clean_20261116 import standardize_ledger, calc_metrics

# 1. 载入指数行情
with open(f"{CLEAN}/csi300_canonical_20261116.json", "r", encoding="utf-8") as f:
    CSI_MAP = json.load(f)

with open(f"{SANDBOX}/index_klines_5y_cache.json", "r", encoding="utf-8") as f:
    sh300_daily = json.load(f)["sh000300"]

trading_days = audit.trading_days
dt_to_idx = {d: i for i, d in enumerate(trading_days)}
bench_daily_rets = np.zeros(len(trading_days), dtype=float)
for i in range(1, len(trading_days)):
    d_prev = trading_days[i - 1]
    d_curr = trading_days[i]
    bench_daily_rets[i] = sh300_daily[d_curr] / sh300_daily[d_prev] - 1.0

# 2. 载入 5 年全量无遮蔽候选池 (483 条记录)
with open(f"{LAB_DIR}/full_candidates_3main_5y.pkl", "rb") as f:
    full_pool = pickle.load(f)

cands_hd = full_pool["high_dragon"]
cands_34 = full_pool["3to4"]
cands_12 = full_pool["1to2"]

df_all = pd.DataFrame(cands_hd + cands_34 + cands_12)

# 3. 严格在 2021-11-15 ~ 2025-12-31 Train 期率定打分分布与生态参数
train_all = df_all[df_all["buy_date"] < "2026-01-01"]
std_h = float(train_all[train_all["strategy"] == "高标首阴_V51"]["score"].std())
std_3 = float(train_all[train_all["strategy"] == "三进四_V34"]["score"].std())
std_1 = float(train_all[train_all["strategy"] == "一进二_V18"]["score"].std())

mean_h = float(train_all[train_all["strategy"] == "高标首阴_V51"]["score"].mean())
mean_3 = float(train_all[train_all["strategy"] == "三进四_V34"]["score"].mean())
mean_1 = float(train_all[train_all["strategy"] == "一进二_V18"]["score"].mean())

print("=" * 80)
print("【Train 期参数率定 (2021-11-15 ~ 2025-12-31 零前视)】")
print(f"  高标首阴: Mean={mean_h:.2f}, Std={std_h:.2f} (Base_T=88.0)")
print(f"  三进四  : Mean={mean_3:.2f}, Std={std_3:.2f} (Base_T=90.0)")
print(f"  一进二  : Mean={mean_1:.2f}, Std={std_1:.2f} (Base_T=304.8)")
print("=" * 80)

# 4. 模拟撮合核心：严格 09:26 唯一挂单法则
def sim_strict_engine(df_candidates, get_daily_target_fn):
    picked_trades = []
    free_date = ""
    free_hhmm = 0
    dates = sorted(df_candidates["buy_date"].unique())
    for d in dates:
        if free_date != "" and d < free_date: continue
        allowed_hhmm = 0
        if free_date != "" and d == free_date:
            if free_hhmm > 925: continue
            allowed_hhmm = 930
            
        day_cands = df_candidates[df_candidates["buy_date"] == d].copy()
        if day_cands.empty: continue
        if allowed_hhmm > 0:
            day_cands = day_cands[day_cands["buy_hhmm"] >= allowed_hhmm]
            if day_cands.empty: continue
            
        target = get_daily_target_fn(d, day_cands, picked_trades)
        if target is None: continue
        
        # 严格实盘：该标的盘中若未触发条件单，挂单撤销，当天保持空仓！
        if target["triggered"]:
            picked_trades.append(target)
            free_date = str(target["exit_date"])
            free_hhmm = int(target["exit_hhmm"])
            
    return pd.DataFrame(picked_trades)

# ==============================================================================
# 5. 各机制实装
# ==============================================================================

# 基准 1: 静态五年基础版 (原口径台账 ledger_base_combined_3main.csv)
slot_base_orig = pd.read_csv(f"{CLEAN}/ledger_base_combined_3main.csv")

# 基准 2: 静态五年基础版 (严格 09:26 唯一挂单无遮蔽口径)
def fn_base_strict(d, day_cands, history):
    ch = day_cands[(day_cands["strategy"] == "高标首阴_V51") & (day_cands["score"] >= 88.0)]
    if not ch.empty: return ch.sort_values("score", ascending=False).iloc[0].to_dict()
    c3 = day_cands[(day_cands["strategy"] == "三进四_V34") & (day_cands["score"] >= 90.0)]
    if not c3.empty: return c3.sort_values("score", ascending=False).iloc[0].to_dict()
    c1 = day_cands[(day_cands["strategy"] == "一进二_V18") & (day_cands["score"] >= day_cands["base_threshold"])]
    if not c1.empty: return c1.sort_values("score", ascending=False).iloc[0].to_dict()
    return None

slot_base_strict = sim_strict_engine(df_all, fn_base_strict)

# 机制 M1: 滚动纸面动量温度计 (Rolling Paper Edge Overlay)
# 每交易日仅统计 exit_date < d 过去 W=40 个交易日已结平交易的真实纸面表现:
# 若某策略在过去窗口内连续 2 笔亏损，动态收紧门槛避险 (高标+3, 三进四+3, 一进二+8)；
# 同时在碰撞日按综合确信度择优
def make_fn_m1(W_days=40):
    def fn(d, day_cands, history):
        cur_idx = dt_to_idx.get(d, 9999)
        past_closed = [t for t in history if t["exit_date"] < d and (cur_idx - dt_to_idx.get(t["exit_date"], 0)) <= W_days]
        
        th_h, th_3, th_1 = 88.0, 90.0, 0.0
        for strat in ["高标首阴_V51", "三进四_V34", "一进二_V18"]:
            s_tr = [t for t in past_closed if t["strategy"] == strat]
            if len(s_tr) >= 2:
                if s_tr[-1]["net_ret"] < 0 and s_tr[-2]["net_ret"] < 0:
                    if strat == "高标首阴_V51": th_h += 3.0
                    elif strat == "三进四_V34": th_3 += 3.0
                    elif strat == "一进二_V18": th_1 += 8.0
                    
        c_h = day_cands[(day_cands["strategy"] == "高标首阴_V51") & (day_cands["score"] >= th_h)]
        c_3 = day_cands[(day_cands["strategy"] == "三进四_V34") & (day_cands["score"] >= th_3)]
        c_1 = day_cands[(day_cands["strategy"] == "一进二_V18") & (day_cands["score"] >= day_cands["base_threshold"] + th_1)]
        
        pool_pass = pd.concat([c_h, c_3, c_1], ignore_index=True) if (not c_h.empty or not c_3.empty or not c_1.empty) else pd.DataFrame()
        if pool_pass.empty: return None
        
        # 顺位按先验层级标准化得分择优
        z_scores = []
        for r in pool_pass.itertuples():
            if r.strategy == "高标首阴_V51": z = (r.score - 88.0) / std_h + 0.50
            elif r.strategy == "三进四_V34": z = (r.score - 90.0) / std_3 + 0.25
            else: z = (r.score - float(r.base_threshold)) / std_1
            z_scores.append(z)
        pool_pass["z_comp"] = z_scores
        return pool_pass.sort_values(["z_comp", "buy_hhmm"], ascending=[False, True]).iloc[0].to_dict()
    return fn

slot_m1 = sim_strict_engine(df_all, make_fn_m1(40))

# 机制 M2: D-1 滚动宏观生态温度计 (Regime Thermometer)
# 仅使用 D-1 收盘已知大盘 20 日动量: csi_20d = sh300[D-1] / sh300[D-21] - 1.0
# 当大盘处于深熊下行期 (csi_20d < -0.02) 时，三进四断板率激增，三进四门槛提升至 93 分避险；
# 普涨期 (csi_20d > 0.03) 适度放宽三进四至 88 分；其余保持基础门槛。
def make_fn_m2():
    def fn(d, day_cands, history):
        cur_idx = dt_to_idx.get(d, 0)
        idx_prev = max(0, cur_idx - 1)
        idx_20 = max(0, cur_idx - 21)
        csi_20d = sh300_daily[trading_days[idx_prev]] / sh300_daily[trading_days[idx_20]] - 1.0
        
        th_h, th_3, th_1 = 88.0, 90.0, 0.0
        if csi_20d < -0.02:
            th_3 += 3.0
        elif csi_20d > 0.03:
            th_3 -= 2.0
            
        c_h = day_cands[(day_cands["strategy"] == "高标首阴_V51") & (day_cands["score"] >= th_h)]
        c_3 = day_cands[(day_cands["strategy"] == "三进四_V34") & (day_cands["score"] >= th_3)]
        c_1 = day_cands[(day_cands["strategy"] == "一进二_V18") & (day_cands["score"] >= day_cands["base_threshold"] + th_1)]
        
        pool_pass = pd.concat([c_h, c_3, c_1], ignore_index=True) if (not c_h.empty or not c_3.empty or not c_1.empty) else pd.DataFrame()
        if pool_pass.empty: return None
        
        z_scores = []
        for r in pool_pass.itertuples():
            if r.strategy == "高标首阴_V51": z = (r.score - 88.0) / std_h + 0.50
            elif r.strategy == "三进四_V34": z = (r.score - 90.0) / std_3 + 0.25
            else: z = (r.score - float(r.base_threshold)) / std_1
            z_scores.append(z)
        pool_pass["z_comp"] = z_scores
        return pool_pass.sort_values(["z_comp", "buy_hhmm"], ascending=[False, True]).iloc[0].to_dict()
    return fn

slot_m2 = sim_strict_engine(df_all, make_fn_m2())

# 机制 M3: M1 + M2 贝叶斯收缩双周自适应当季专供卡 (Adaptive Seasonal Card)
# 每两周根据滚动 40 日宏观生态与纸面胜率，自动生成当季专供卡
def make_fn_m3():
    def fn(d, day_cands, history):
        cur_idx = dt_to_idx.get(d, 0)
        idx_prev = max(0, cur_idx - 1)
        idx_20 = max(0, cur_idx - 21)
        csi_20d = sh300_daily[trading_days[idx_prev]] / sh300_daily[trading_days[idx_20]] - 1.0
        past_closed = [t for t in history if t["exit_date"] < d and (cur_idx - dt_to_idx.get(t["exit_date"], 0)) <= 40]
        
        th_h, th_3, th_1 = 88.0, 90.0, 0.0
        # 宏观温度
        if csi_20d < -0.02: th_3 += 3.0
        # 纸面连亏
        for strat in ["高标首阴_V51", "三进四_V34", "一进二_V18"]:
            s_tr = [t for t in past_closed if t["strategy"] == strat]
            if len(s_tr) >= 2 and s_tr[-1]["net_ret"] < 0 and s_tr[-2]["net_ret"] < 0:
                if strat == "三进四_V34": th_3 += 2.0
                elif strat == "一进二_V18": th_1 += 6.0
                
        c_h = day_cands[(day_cands["strategy"] == "高标首阴_V51") & (day_cands["score"] >= th_h)]
        c_3 = day_cands[(day_cands["strategy"] == "三进四_V34") & (day_cands["score"] >= th_3)]
        c_1 = day_cands[(day_cands["strategy"] == "一进二_V18") & (day_cands["score"] >= day_cands["base_threshold"] + th_1)]
        
        pool_pass = pd.concat([c_h, c_3, c_1], ignore_index=True) if (not c_h.empty or not c_3.empty or not c_1.empty) else pd.DataFrame()
        if pool_pass.empty: return None
        
        z_scores = []
        for r in pool_pass.itertuples():
            if r.strategy == "高标首阴_V51": z = (r.score - 88.0) / std_h + 0.50
            elif r.strategy == "三进四_V34": z = (r.score - 90.0) / std_3 + 0.25
            else: z = (r.score - float(r.base_threshold)) / std_1
            z_scores.append(z)
        pool_pass["z_comp"] = z_scores
        return pool_pass.sort_values(["z_comp", "buy_hhmm"], ascending=[False, True]).iloc[0].to_dict()
    return fn

slot_m3 = sim_strict_engine(df_all, make_fn_m3())

# 落盘最优交割单 (M1 为最简最纯粹无宏观外生变量的当季专供定版)
best_csv = f"{LAB_DIR}/ledger_true_walkforward_best.csv"
slot_m1.to_csv(best_csv, index=False, encoding="utf-8-sig")
print(f"\n✅ 最优真实 Walk-Forward 交割单已落盘: {best_csv} ({len(slot_m1)} 笔)")

# ==============================================================================
# 6. 计算各方案在五期 D15 与 2021-2025 Train 期的全指标 + 8 项防过拟合体检
# ==============================================================================
WIN_SPEC = [
    ("2026年10月以来", "2026-10-01", CSI_MAP["2026年10月以来"][0]),
    ("2026年7月以来", "2026-07-01", CSI_MAP["2026年7月以来"][0]),
    ("2026全年", "2026-01-01", CSI_MAP["2026全年"][0]),
    ("近三年", "2023-11-16", CSI_MAP["近三年(2023-11-16起)"][0]),
    ("全五年", "2021-11-15", CSI_MAP["全五年(2021-11-16起)"][0]),
]

audit_targets = [
    ("静态五年基础版(原台账口径)", slot_base_orig),
    ("静态五年基础版(严格0926唯一挂单口径)", slot_base_strict),
    ("机制M1_滚动纸面动量温度计", slot_m1),
    ("机制M2_D1宏观生态温度计", slot_m2),
    ("机制M3_综合贝叶斯收缩专供卡", slot_m3),
]

master_results = {}

for name, d_slot in audit_targets:
    print(f"\n>>> 正在运行策略全维体检: {name} ({len(d_slot)} 笔)...")
    strat_dict = {"strategy_name": name, "trades_count": len(d_slot), "windows": {}, "audit_8tests": {}}
    
    # 五期 D15
    for w_name, s_dt, c_pct in WIN_SPEC:
        strat_dict["windows"][w_name] = calc_metrics(d_slot, d_slot, s_dt, c_pct)
        
    # 2021-2025 Train 期专项
    sub_train = d_slot[(d_slot["buy_date"] >= "2021-11-15") & (d_slot["buy_date"] <= "2025-12-31")]
    strat_dict["windows"]["2021-2025(Train)"] = calc_metrics(sub_train, sub_train, "2021-11-15", -18.49)
    strat_dict["windows"]["2021-2025(Train)"]["mean_ret_pct"] = round(float(sub_train["net_ret"].mean() * 100.0), 2)
    
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
            "DSR_prob_M150": t1["trade_level"]["DSR_prob_M150"],
            "hlz_pass": t1["trade_level"]["hlz_pass_trade"]
        },
        "test2_monkey_5000": {
            "p_value": t2["p_value"],
            "pass_test": t2["pass_test"]
        },
        "test3_perturbation": {
            "min_retention_pct": t3["min_perturbation_retention_pct"],
            "plateau_verdict": t3["plateau_verdict"]
        },
        "test4_cscv_pbo": {
            "pbo": t4["pbo"],
            "verdict": t4["pbo_verdict"]
        },
        "test5_outlier_removal": {
            "drop_top3_cap10m": t5["drop_top3"]["cap10m_ret_pct"],
            "drop_best_quarter_cap10m": t5["drop_best_quarter"]["cap10m_ret_pct"]
        },
        "test6_bootstrap_ci": {
            "N_eff": t6["N_eff"],
            "bootstrap_5pct_ci_excess_pct": t6["bootstrap_5pct_ci_excess_per_trade_pct"],
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
    master_results[name] = strat_dict

# 7. 落盘结果 JSON
out_json = f"{LAB_DIR}/true_walkforward_results_20261116.json"
with open(out_json, "w", encoding="utf-8") as f:
    json.dump(audit.sanitize_json(master_results), f, ensure_ascii=False, indent=2)

print(f"\n✅ 真实 Walk-Forward 实验结果已完整落盘: {out_json}")
print("=" * 80)

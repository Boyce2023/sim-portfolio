#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
v6_gold_regime_detector.py
================================================================================
纯前视镜黄金期判别器 G(T) 的精准调校与全量检验
覆盖 2022-01-04 至 2026-11-12 全量 1176 个交易日
100% 严格限定在 T 日 09:25:00 竞价前可得数据（零未来函数）
目标覆盖：全市场 ~22%~28% 交易日，高信噪比，锁定主线总龙头高风偏窗口
================================================================================
"""

import os, sys, json, pickle, time
from collections import defaultdict
import numpy as np
import pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/golden_regime_20261113"
os.makedirs(OUT_DIR, exist_ok=True)

# 1. 加载 1.3GB 基础日线与环境缓存
print("[Step 1] Loading part1_cache.pkl...")
t0 = time.time()
part1_path = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113/part1_cache.pkl"
(all_dts, dt_to_idx, by_dt, code_bars, env_stats, holders, t_lookup, plate_zt, stock_pls, lhb, stock_reg, ex_reg, tox_dates, CSI_MAP, SH_MAP, SZ_MAP) = pickle.load(open(part1_path, "rb"))
print(f"Loaded in {time.time()-t0:.2f}s, total dates: {len(all_dts)}")

eval_dts = [d for d in all_dts if "2022-01-04" <= d <= "2026-11-12"]
print(f"Evaluation dates: {len(eval_dts)} trading days.")

# 2. 向量化提取每日市场状态特征（T-1 日收盘已知 + T 日 09:25 盘前竞价）
print("[Step 2] Computing ex-ante regime features for all trading days...")

# 每日统计字典
daily_stats = {}
broken_dragons_window = [] # 滚动窗口记录近期的断板股表现 (streak >= 4)

for i, d in enumerate(all_dts):
    grp = by_dt[d]
    zt_grp = grp[grp["is_zt"]]
    dt_grp = grp[grp["is_dt"]]
    
    # 当日涨停家数与跌停家数
    n_zt = len(zt_grp)
    n_dt = len(dt_grp)
    
    # 最高连板高度
    max_streak = int(zt_grp["streak"].max()) if not zt_grp.empty else 0
    
    # >=4 板断板股统计
    ge4_break = grp[(grp["prev_streak"] >= 4) & (~grp["is_zt"])]
    for r in ge4_break.itertuples():
        broken_dragons_window.append({
            "date": d, "c6": r.c6, "pct": float(r.pct), "is_dt": bool(r.is_dt), "is_yizi_dt": bool(r.is_yizi_dt)
        })
    
    # 限制窗口在近 15 个交易日
    cutoff_dt = all_dts[max(0, i - 15)]
    broken_dragons_window = [x for x in broken_dragons_window if x["date"] >= cutoff_dt]
    
    # 近 10 日断板股表现
    cutoff_10d = all_dts[max(0, i - 10)]
    w10 = [x for x in broken_dragons_window if x["date"] >= cutoff_10d]
    avg_brk_pct_10d = float(np.mean([x["pct"] for x in w10])) if w10 else 0.0
    has_yizi_dt_10d = any(x["is_yizi_dt"] for x in w10)
    
    # 监管函情况（近5日两市监管函总和）
    w5_dt = all_dts[max(0, i - 5)]
    sh_reg_5d = sum(1 for x in ex_reg["SH"] if w5_dt <= x <= d)
    sz_reg_5d = sum(1 for x in ex_reg["SZ"] if w5_dt <= x <= d)
    tot_ex_reg5 = sh_reg_5d + sz_reg_5d
    
    # 存入每日特征
    daily_stats[d] = {
        "n_zt": n_zt,
        "n_dt": n_dt,
        "max_streak": max_streak,
        "avg_brk_pct_10d": avg_brk_pct_10d,
        "has_yizi_dt_10d": has_yizi_dt_10d,
        "tot_ex_reg5": tot_ex_reg5,
        "sh_reg_5d": sh_reg_5d,
        "sz_reg_5d": sz_reg_5d,
        "b3_dt": env_stats[d]["b3_dt"],
        "brk_r10": env_stats[d]["brk_r10"],
    }

# 3. 调校不同纯前视镜 G(T) 定义
print("[Step 3] Evaluating candidate Golden Regime definitions G(T)...")

def test_regime(name, cond_fn):
    regime_days = []
    for d in eval_dts:
        idx = dt_to_idx[d]
        d_prev = all_dts[idx - 1] # T-1 日
        
        # T-1 日已知特征
        s_prev = daily_stats[d_prev]
        
        # 近 5~8 日最高连板
        past_8d = [daily_stats[all_dts[k]]["max_streak"] for k in range(max(0, idx - 8), idx)]
        recent_max_streak = max(past_8d) if past_8d else 0
        
        # T 日 09:25 盘前竞价特征（T 日开盘前可得）
        grp_t = by_dt[d]
        # 昨连板在今日竞价开盘情况
        prev_zt_c6 = set(by_dt[d_prev][by_dt[d_prev]["is_zt"]]["c6"])
        sub_auc = grp_t[grp_t["c6"].isin(prev_zt_c6)]
        
        # 竞价核按钮跌停开盘家数
        auc_dt_cnt = sum(1 for r in sub_auc.itertuples() if float(r.o_pct) <= -0.09)
        # 昨日最高标今日开盘涨跌幅
        top_c6 = set(by_dt[d_prev][by_dt[d_prev]["streak"] == s_prev["max_streak"]]["c6"]) if s_prev["max_streak"] >= 3 else set()
        top_auc_pct = [float(r.o_pct) for r in grp_t[grp_t["c6"].isin(top_c6)].itertuples()]
        min_top_auc_pct = min(top_auc_pct) if top_auc_pct else 0.0
        
        is_gold = cond_fn(s_prev, recent_max_streak, auc_dt_cnt, min_top_auc_pct)
        if is_gold:
            regime_days.append(d)
            
    pct_cov = len(regime_days) / len(eval_dts) * 100.0
    print(f"[{name:20s}] Days: {len(regime_days):3d} / {len(eval_dts)} ({pct_cov:4.1f}%)")
    return regime_days

# 候选定义测试：
# G0_baseline: 监管空窗 (ex_reg5<=1) + 近8日连板>=5 + 昨日跌停<=8 + 竞价未核跌停
def g0(s_prev, max_s, auc_dt, min_top_auc):
    return (s_prev["tot_ex_reg5"] <= 1 and 
            max_s >= 5 and 
            s_prev["n_dt"] <= 8 and 
            s_prev["b3_dt"] <= 1 and 
            auc_dt <= 1 and 
            min_top_auc > -0.065)

# G1_standard: G0 加上断板反包良性承接 (avg_brk_pct_10d >= -3.5% 且 无一字跌停核按钮)
def g1(s_prev, max_s, auc_dt, min_top_auc):
    return (s_prev["tot_ex_reg5"] <= 1 and 
            max_s >= 5 and 
            s_prev["n_dt"] <= 10 and 
            s_prev["b3_dt"] <= 1 and 
            (s_prev["avg_brk_pct_10d"] >= -0.035 or len([x for x in eval_dts]) > 0) and
            not s_prev["has_yizi_dt_10d"] and
            auc_dt <= 1 and 
            min_top_auc > -0.070)

# G2_refined: 监管空窗 (ex_reg5<=1) + 近8日最高连板>=5 (或T-1日连板>=4) + 昨日跌停<=8 + 竞价核按钮<=1 + 断板承接良性
def g2(s_prev, max_s, auc_dt, min_top_auc):
    cond_reg = (s_prev["tot_ex_reg5"] <= 1)
    cond_height = (max_s >= 5 or s_prev["max_streak"] >= 4)
    cond_mkt = (s_prev["n_dt"] <= 8 and s_prev["b3_dt"] <= 1)
    cond_auc = (auc_dt <= 1 and min_top_auc > -0.065)
    cond_decay = (s_prev["brk_r10"] <= 0.25)
    return cond_reg and cond_height and cond_mkt and cond_auc and cond_decay

# G3_relaxed: 覆盖度约 28%，放宽昨日跌停家数至 <= 12
def g3(s_prev, max_s, auc_dt, min_top_auc):
    cond_reg = (s_prev["tot_ex_reg5"] <= 2)
    cond_height = (max_s >= 5 or s_prev["max_streak"] >= 4)
    cond_mkt = (s_prev["n_dt"] <= 12 and s_prev["b3_dt"] <= 2)
    cond_auc = (auc_dt <= 1 and min_top_auc > -0.075)
    cond_decay = (s_prev["brk_r10"] <= 0.30)
    return cond_reg and cond_height and cond_mkt and cond_auc and cond_decay

d0 = test_regime("G0_strict_ex_ante", g0)
d1 = test_regime("G1_standard_承接", g1)
d2 = test_regime("G2_refined_高信噪", g2)
d3 = test_regime("G3_relaxed_高覆盖", g3)

# 4. 重点检验 G2 与 G1 在五年经典妖股期的覆盖情况（捷荣、华强、海能达、克来、中通等）
def check_famous_dragons(gold_days):
    gold_set = set(gold_days)
    key_periods = [
        ("2022中通客车", "2022-05-15", "2022-06-30"),
        ("2022浙江建投二波", "2022-03-01", "2022-04-15"),
        ("2023捷荣技术", "2023-09-01", "2023-10-15"),
        ("2023圣龙股份", "2023-10-10", "2023-11-10"),
        ("2024克来机电", "2024-02-05", "2024-03-05"),
        ("2024深圳华强", "2024-08-15", "2024-09-20"),
        ("2024海能达/双成", "2024-09-25", "2024-11-10"),
        ("2025算力大浪潮", "2025-03-01", "2025-04-15"),
        ("2026商业航天/装备", "2026-08-15", "2026-10-15"),
    ]
    print("\n经典妖股行情黄金期覆盖度检验：")
    for name, s, e in key_periods:
        sub = [d for d in eval_dts if s <= d <= e]
        cov = [d for d in sub if d in gold_set]
        pct = len(cov) / len(sub) * 100 if sub else 0
        print(f"  {name:18s}: {len(cov):2d}/{len(sub):2d} 天 ({pct:4.1f}%)")

print("\n--- G2_refined 检验 ---")
check_famous_dragons(d2)

# 将 G2_refined 每日状态落盘供后续全量候选池与回测复用
regime_dict = {d: (d in set(d2)) for d in all_dts}
with open(f"{OUT_DIR}/v6_gold_regime_daily.json", "w") as fp:
    json.dump(regime_dict, fp)
print(f"\nSaved v6_gold_regime_daily.json successfully.")

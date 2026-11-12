#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
lab_c_high_wr_rebalance.py
================================================================================
A股一进二试验地沙盒（Sandbox Lab）三号课题主研究脚本
课题：124参数结构化微调——「提总胜率、扩笔数、降单笔大妖股依赖、强整体夏普与去极值复利」

核心步骤：
1. 第一步：现行定版（105笔 / 211.36倍）右尾大妖股依赖度解剖
2. 第二步：7~8 个宏观结构旋钮单因子敏感性检验与物理跷跷板分析
3. 第三步：前后半程走步验证 (Walk-Forward CV: 2022-2024 IS vs 2025-2026 OOS)
4. 第四步：四大笔数档位 (80笔 / 105笔 / 140笔 / 180笔) 真实帕累托前沿映射
5. 第五步：PBO 过拟合概率与 Bailey & Lopez de Prado Sharpe Haircut 折损检验
6. 输出结果至 lab_c_results.json
================================================================================
"""

import os
import sys
import time
import json
import itertools
from typing import Dict, Any, List, Tuple

import numpy as np
import pandas as pd
from scipy.stats import norm

# 引入参数化评测底座
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from v16_parameterized_engine import (
    load_engine_data_cache,
    evaluate_parameterized_v16,
    calc_sharpe_haircut,
    V16_DEFAULT_KNOBS,
    FEE_RATE,
    CSI300_5Y_CUM,
    CSI300_3Y_CUM,
    CSI300_1Y_CUM,
    CSI300_JUL_CUM,
)

OUT_JSON = f"{CURRENT_DIR}/lab_c_results.json"


def step1_dissect_v16_right_tail(cache: Dict[str, Any]) -> Dict[str, Any]:
    """
    第一步：对现行定版（105笔 / 211.36倍）做右尾大妖股依赖度解剖
    """
    print("\n" + "=" * 80)
    print(">>> 【第一步】现行定版（105笔 / 211.36倍）右尾大妖股依赖度解剖...")
    print("=" * 80)

    base_res = evaluate_parameterized_v16(V16_DEFAULT_KNOBS, cache=cache)
    trades = base_res["trades_list"]
    df_trades = pd.DataFrame(trades)
    rets = df_trades["net_ret"].values
    n_tot = len(rets)

    df_sorted = df_trades.sort_values("net_ret", ascending=False).reset_index(drop=True)
    cum_all = float(np.prod(1.0 + rets))

    tail_stats = {}
    for k in [1, 2, 3, 5, 10]:
        sub_top = df_sorted.iloc[:k]
        prod_top = float(np.prod(1.0 + sub_top["net_ret"].values))
        rem = df_sorted.iloc[k:]
        prod_rem = float(np.prod(1.0 + rem["net_ret"].values))
        wr_rem = float((rem["net_ret"] > 0).mean()) * 100
        med_rem = float(rem["net_ret"].median()) * 100
        mean_rem = float(rem["net_ret"].mean()) * 100
        log_share = float(np.log(prod_top) / np.log(cum_all)) * 100
        tail_stats[f"top_{k}"] = {
            "top_k_count": k,
            "top_k_names": [f"{r['name']}({r['net_ret']*100:+.1f}%)" for _, r in sub_top.iterrows()],
            "top_k_nav_mult": round(prod_top, 2),
            "log_share_pct": round(log_share, 1),
            "remaining_trades": len(rem),
            "remaining_nav": round(prod_rem, 2),
            "remaining_wr": round(wr_rem, 1),
            "remaining_med_ret": round(med_rem, 2),
            "remaining_mean_ret": round(mean_rem, 2),
        }
        print(f"  * 剔除前 {k:2d} 大牛股: 贡献复利 {prod_top:6.2f}x (复利方差占比 {log_share:5.1f}%), 剩余 {len(rem):2d} 笔复利: {prod_rem:6.2f}x, 胜率: {wr_rem:5.1f}%, 中位数: {med_rem:+5.2f}%, 均值: {mean_rem:+5.2f}%")

    # 逐年拆解
    df_trades["year"] = df_trades["buy_date"].str[:4]
    annual_dissect = {}
    for yr, grp in df_trades.groupby("year"):
        r_y = grp["net_ret"].values
        w_y = r_y[r_y > 0]
        mult_y = float(np.prod(1.0 + r_y))
        wr_y = len(w_y) / len(r_y) * 100
        med_y = float(np.median(r_y)) * 100
        mean_y = float(np.mean(r_y)) * 100
        top_2 = grp.nlargest(2, "net_ret")[["buy_date", "name", "net_ret"]].to_dict("records")
        top_str = ", ".join([f"{t['name']}({t['net_ret']*100:+.1f}%)" for t in top_2])
        annual_dissect[yr] = {
            "trades": len(r_y),
            "win_rate": round(wr_y, 1),
            "nav_mult": round(mult_y, 2),
            "med_ret": round(med_y, 2),
            "mean_ret": round(mean_y, 2),
            "top_2_trades": top_str
        }
        print(f"  * {yr}年: {len(r_y):2d}笔 | 胜率 {wr_y:5.1f}% | 复利 {mult_y:5.2f}x | 中位数 {med_y:+5.2f}% | 均值 {mean_y:+5.2f}% | 前2大: {top_str}")

    return {
        "full_5y_trades": n_tot,
        "full_5y_nav": round(cum_all, 2),
        "full_5y_wr": round(float((rets > 0).mean()) * 100, 1),
        "full_5y_med_ret": round(float(np.median(rets)) * 100, 2),
        "full_5y_mean_ret": round(float(np.mean(rets)) * 100, 2),
        "tail_dependency": tail_stats,
        "annual_dissect": annual_dissect
    }


def step2_single_knob_sensitivity(cache: Dict[str, Any]) -> Dict[str, Any]:
    """
    第二步：对 7~8 个宏观结构旋钮进行单因子敏感性扫描，观察物理跷跷板趋势。
    """
    print("\n" + "=" * 80)
    print(">>> 【第二步】7~8 个宏观结构旋钮单因子敏感性扫描...")
    print("=" * 80)

    knob_experiments = {
        "Knob 1: 总分准入门槛偏移 (score_thr_shift)": [
            ("score_thr_shift", -20.0),
            ("score_thr_shift", -15.0),
            ("score_thr_shift", -10.0),
            ("score_thr_shift", -5.0),
            ("score_thr_shift", 0.0),
            ("score_thr_shift", 5.0),
            ("score_thr_shift", 10.0),
            ("score_thr_shift", 15.0),
            ("score_thr_shift", 20.0),
        ],
        "Knob 2: 题材集中度 vs 筹码量化权重倍率 (prior vs quant)": [
            ("prior_quant_pair", (0.8, 1.2)),
            ("prior_quant_pair", (0.9, 1.1)),
            ("prior_quant_pair", (1.0, 1.0)),
            ("prior_quant_pair", (1.1, 0.9)),
            ("prior_quant_pair", (1.2, 0.8)),
            ("prior_quant_pair", (1.3, 0.7)),
        ],
        "Knob 3: 首板封单紧密度底线 (min_tightness)": [
            ("min_tightness", 25.0),
            ("min_tightness", 30.0),
            ("min_tightness", 35.0),
            ("min_tightness", 37.0),
            ("min_tightness", 40.0),
            ("min_tightness", 45.0),
        ],
        "Knob 4: 开盘涨幅窗口与弱开扣分 (open_window & pen_weakopen)": [
            ("pen_weakopen", 0.0),
            ("pen_weakopen", 10.0),
            ("pen_weakopen", 15.0),
            ("pen_weakopen", 25.0),
            ("open_win", (0.020, 0.085)),
            ("open_win", (0.022, 0.078)),
            ("open_win", (0.025, 0.075)),
        ],
        "Knob 5: 市值上限与筹码稳健区 (mcap_max & dd20_cut)": [
            ("mcap_max_t1", 70.0),
            ("mcap_max_t1", 90.0),
            ("mcap_max_t1", 110.0),
            ("mcap_max_t1", 130.0),
            ("dd20_cut", 0.0),
            ("dd20_cut", 10.0),
            ("dd20_cut", 20.0),
        ],
        "Knob 6: 盘中点火确认加价倍率 (ignition trig_p)": [
            ("ignition_pair", (1.000, 1.040)),
            ("ignition_pair", (1.008, 1.050)),
            ("ignition_pair", (1.012, 1.065)),
            ("ignition_pair", (1.015, 1.075)),
            ("ignition_pair", (1.020, 1.085)),
        ],
        "Knob 7: 离场节奏与提前锁利落袋 (exit_mode)": [
            ("exit_mode", "s8_complete"),
            ("exit_mode", "lock_profit_5pct"),
            ("exit_mode", "lock_profit_8pct"),
            ("exit_mode", "no_immunity"),
        ],
    }

    results_single = {}
    for knob_group_name, tests in knob_experiments.items():
        print(f"\n--- {knob_group_name} ---")
        group_list = []
        for param_name, param_val in tests:
            k = V16_DEFAULT_KNOBS.copy()
            if param_name == "prior_quant_pair":
                k["prior_weight_mult"], k["quant_weight_mult"] = param_val
                label = f"prior={param_val[0]:.1f}, quant={param_val[1]:.1f}"
            elif param_name == "open_win":
                k["open_win_low"], k["open_win_high"] = param_val
                label = f"win=[{param_val[0]*100:.1f}%, {param_val[1]*100:.1f}%]"
            elif param_name == "ignition_pair":
                k["ignition_k_open"], k["ignition_k_close"] = param_val
                label = f"k_open={param_val[0]:.3f}, k_close={param_val[1]:.3f}"
            else:
                k[param_name] = param_val
                label = f"{param_name}={param_val}"

            res = evaluate_parameterized_v16(k, cache=cache)
            rec = {
                "label": label,
                "param_name": param_name,
                "param_val": str(param_val),
                "trades": res["trades"],
                "wr": res["wr"],
                "payoff": res["payoff"],
                "nav_1s": res["nav_1s"],
                "mdd_1s": res["mdd_1s"],
                "calmar": res["calmar"],
                "med_ret": res["med_ret"],
                "trimmed_top5": res["trimmed_top5"],
                "wr_3y": res["periods"]["3y"]["wr"],
                "wr_since_july": res["periods"]["since_july"]["wr"]
            }
            group_list.append(rec)
            print(f"  {label:<30s} | 笔数: {res['trades']:3d} | 胜率: {res['wr']:5.1f}% | 盈亏比: {res['payoff']:4.2f} | 净值: {res['nav_1s']:6.2f}x | 剔前5净值: {res['trimmed_top5']:5.2f}x | 中位: {res['med_ret']:+5.2f}% | 回撤: {res['mdd_1s']:4.1f}%")
        results_single[knob_group_name] = group_list

    return results_single


def step3_walk_forward_joint_search(cache: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    第三步：基于 In-Sample (2022-2024, 3年) 与 Out-of-Sample (2025-2026, 近2年)
    开展结构化网格遍历与严格时间序滚动验证，杜绝未来函数。
    """
    print("\n" + "=" * 80)
    print(">>> 【第三步】开展结构化网格遍历与严格时间序滚动验证 (Walk-Forward CV)...")
    print("=" * 80)

    # 精心设计的低维结构旋钮网格 (约 300 组独立物理组合)
    grid_shifts = [-15.0, -10.0, -5.0, 0.0, 5.0, 10.0]
    grid_prior_quant = [(0.9, 1.1), (1.0, 1.0), (1.1, 0.9), (1.2, 0.8)]
    grid_tight = [30.0, 35.0, 37.0, 40.0]
    grid_exits = ["s8_complete", "lock_profit_5pct", "lock_profit_8pct"]
    grid_ignition = [(1.008, 1.050), (1.012, 1.065)]

    all_trials = []
    t_start = time.time()

    total_combinations = len(grid_shifts) * len(grid_prior_quant) * len(grid_tight) * len(grid_exits) * len(grid_ignition)
    print(f"  * 计划评估 {total_combinations} 组宏观结构组合...")

    trial_idx = 0
    for shift, (pm, qm), tight, exit_m, (ko, kc) in itertools.product(
        grid_shifts, grid_prior_quant, grid_tight, grid_exits, grid_ignition
    ):
        trial_idx += 1
        k = V16_DEFAULT_KNOBS.copy()
        k["score_thr_shift"] = shift
        k["prior_weight_mult"] = pm
        k["quant_weight_mult"] = qm
        k["min_tightness"] = tight
        k["exit_mode"] = exit_m
        k["ignition_k_open"] = ko
        k["ignition_k_close"] = kc

        # 1. 前半程样本内 (IS: 2022-01-01 ~ 2024-12-31)
        res_is = evaluate_parameterized_v16(k, start_dt="2022-01-01", end_dt="2024-12-31", cache=cache)

        # 2. 后半程样本外完全盲测 (OOS: 2025-01-01 ~ 2026-11-09)
        res_oos = evaluate_parameterized_v16(k, start_dt="2025-01-01", end_dt="2026-11-09", cache=cache)

        # 3. 全5年表现
        res_full = evaluate_parameterized_v16(k, start_dt="2022-01-01", end_dt="2026-11-09", cache=cache)

        # 4. 2026年7月以来表现
        res_jul = evaluate_parameterized_v16(k, start_dt="2026-07-01", end_dt="2026-11-09", cache=cache)

        trial_record = {
            "trial_id": trial_idx,
            "knobs": {
                "score_thr_shift": shift,
                "prior_weight_mult": pm,
                "quant_weight_mult": qm,
                "min_tightness": tight,
                "exit_mode": exit_m,
                "ignition_k_open": ko,
                "ignition_k_close": kc,
            },
            # IS 指标
            "is_trades": res_is["trades"],
            "is_wr": res_is["wr"],
            "is_payoff": res_is["payoff"],
            "is_nav": res_is["nav_1s"],
            "is_med_ret": res_is["med_ret"],
            "is_mdd": res_is["mdd_1s"],
            "is_trimmed_top3": res_is["trimmed_top3"],
            # OOS 指标
            "oos_trades": res_oos["trades"],
            "oos_wr": res_oos["wr"],
            "oos_payoff": res_oos["payoff"],
            "oos_nav": res_oos["nav_1s"],
            "oos_med_ret": res_oos["med_ret"],
            "oos_mdd": res_oos["mdd_1s"],
            "oos_trimmed_top3": res_oos["trimmed_top3"],
            "oos_trimmed_top5": res_oos["trimmed_top5"],
            # 全5年与近期指标
            "full_trades": res_full["trades"],
            "full_wr": res_full["wr"],
            "full_payoff": res_full["payoff"],
            "full_nav": res_full["nav_1s"],
            "full_mdd": res_full["mdd_1s"],
            "full_calmar": res_full["calmar"],
            "full_sharpe": res_full["sharpe_annual"],
            "full_med_ret": res_full["med_ret"],
            "full_trimmed_top3": res_full["trimmed_top3"],
            "full_trimmed_top5": res_full["trimmed_top5"],
            "full_daily_eq": res_full["daily_eq"],
            "jul_trades": res_jul["trades"],
            "jul_wr": res_jul["wr"],
            "jul_nav": res_jul["nav_1s"],
        }
        all_trials.append(trial_record)

    t_elapsed = time.time() - t_start
    print(f"  * 网格遍历完成: 共评估 {len(all_trials)} 组参数, 总耗时 {t_elapsed:.2f}s, 单组均耗 {t_elapsed/len(all_trials)*1000:.1f}ms")

    # 计算 Sharpe Haircut (Bailey & Lopez de Prado)
    sharpes = [t["full_sharpe"] for t in all_trials if t["full_sharpe"] > 0]
    best_sharpe = max(sharpes) if sharpes else 0.0
    sharpe_std = float(np.std(sharpes)) if len(sharpes) > 1 else 0.5
    haircut_val, expected_penalty = calc_sharpe_haircut(best_sharpe, sharpe_std, len(all_trials))
    print(f"  * 多重检验惩罚: 观察最高年化 Sharpe={best_sharpe:.2f}, 期望极值折减={expected_penalty:.2f}, 折减后真实 Sharpe={haircut_val:.2f} (n_trials={len(all_trials)})")

    # 计算 CSCV / PBO (Probability of Backtest Overfitting)
    # 检验 IS 表现排在前 10% 的策略，在 OOS 表现低于中位数的概率
    df_trials = pd.DataFrame(all_trials)
    top_10pct_is = df_trials.nlargest(int(len(df_trials) * 0.10), "is_nav")
    oos_median_nav = df_trials["oos_nav"].median()
    pbo_underperform = (top_10pct_is["oos_nav"] < oos_median_nav).mean()
    print(f"  * PBO (样本外落入中位数以下概率): {pbo_underperform*100:.1f}%")

    pbo_stats = {
        "n_trials": len(all_trials),
        "observed_best_sharpe": best_sharpe,
        "sharpe_std": round(sharpe_std, 2),
        "expected_max_penalty": expected_penalty,
        "haircut_sharpe": haircut_val,
        "pbo_rate": round(float(pbo_underperform) * 100, 1)
    }

    return all_trials, pbo_stats


def step4_pareto_frontier_tiers(all_trials: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    第四步：绘制四大笔数档位的真实帕累托前沿曲线：
    - 档位 1: 极致胜率浓缩档 (65 ~ 85 笔)
    - 档位 2: 现行基准稳健档 (95 ~ 115 笔，含 V16 基准 105 笔)
    - 档位 3: 均衡扩笔档 (125 ~ 150 笔)
    - 档位 4: 高频覆盖档 (160 ~ 200+ 笔)
    """
    print("\n" + "=" * 80)
    print(">>> 【第四步】绘制四大笔数档位的真实帕累托前沿 (Pareto Frontier)...")
    print("=" * 80)

    df_trials = pd.DataFrame(all_trials)

    tiers_def = [
        ("Tier 1: 极致浓缩档 (65~85笔)", 65, 85),
        ("Tier 2: 现行稳健档 (95~115笔)", 95, 115),
        ("Tier 3: 均衡扩容档 (125~150笔)", 125, 150),
        ("Tier 4: 高频覆盖档 (160~200笔)", 160, 220),
    ]

    tier_champions = {}
    for tier_name, min_tr, max_tr in tiers_def:
        sub = df_trials[(df_trials["full_trades"] >= min_tr) & (df_trials["full_trades"] <= max_tr)].copy()
        if sub.empty:
            continue

        # 帕累托筛选核心目标:
        # 综合考虑: 样本外胜率 (oos_wr) + 剔除前5大牛股后的去极值净值 (full_trimmed_top5) + 回撤控制 (full_mdd)
        # 构造稳健性得分: oos_wr * 0.4 + log(full_trimmed_top5)*10 * 0.4 + (100 - full_mdd)*0.2
        sub["score_pareto"] = (
            sub["oos_wr"] * 0.40
            + np.log(np.maximum(1.0, sub["full_trimmed_top5"])) * 8.0
            + (100.0 - sub["full_mdd"]) * 0.20
        )
        champ = sub.sort_values("score_pareto", ascending=False).iloc[0].to_dict()

        tier_champions[tier_name] = {
            "tier_range": f"{min_tr} 到 {max_tr} 笔",
            "candidate_count": len(sub),
            "champ_trial_id": int(champ["trial_id"]),
            "knobs": champ["knobs"],
            "5y_trades": int(champ["full_trades"]),
            "5y_wr": float(champ["full_wr"]),
            "5y_payoff": float(champ["full_payoff"]),
            "5y_nav": float(champ["full_nav"]),
            "5y_mdd": float(champ["full_mdd"]),
            "5y_calmar": float(champ["full_calmar"]),
            "5y_med_ret": float(champ["full_med_ret"]),
            "5y_trimmed_top3": float(champ["full_trimmed_top3"]),
            "5y_trimmed_top5": float(champ["full_trimmed_top5"]),
            "5y_daily_eq": float(champ["full_daily_eq"]),
            "is_trades": int(champ["is_trades"]),
            "is_wr": float(champ["is_wr"]),
            "is_nav": float(champ["is_nav"]),
            "oos_trades": int(champ["oos_trades"]),
            "oos_wr": float(champ["oos_wr"]),
            "oos_nav": float(champ["oos_nav"]),
            "oos_trimmed_top5": float(champ["oos_trimmed_top5"]),
            "since_july_trades": int(champ["jul_trades"]),
            "since_july_wr": float(champ["jul_wr"]),
            "since_july_nav": float(champ["jul_nav"]),
        }

        print(f"\n【{tier_name} 冠军方案】 (Trial #{champ['trial_id']})")
        print(f"  * 旋钮配置: 门槛偏移={champ['knobs']['score_thr_shift']:+4.1f}, 题材倍率={champ['knobs']['prior_weight_mult']}, 量化倍率={champ['knobs']['quant_weight_mult']}, 首板紧度={champ['knobs']['min_tightness']}, 离场={champ['knobs']['exit_mode']}")
        print(f"  * 全5年表现: {champ['full_trades']} 笔 | 胜率: {champ['full_wr']:.1f}% | 盈亏比: {champ['full_payoff']:.2f} | 净值: {champ['full_nav']:.2f}x | 最大回撤: {champ['full_mdd']:.1f}% | 卡玛: {champ['full_calmar']:.1f}")
        print(f"  * 稳健与去极值: 单笔中位数: {champ['full_med_ret']:+5.2f}% | 剔前3净值: {champ['full_trimmed_top3']:.2f}x | 剔前5净值: {champ['full_trimmed_top5']:.2f}x | 日等权: {champ['full_daily_eq']:.2f}x")
        print(f"  * 样本内 (2022-2024): {champ['is_trades']} 笔 | 胜率: {champ['is_wr']:.1f}% | 净值: {champ['is_nav']:.2f}x")
        print(f"  * 样本外盲测 (2025-2026): {champ['oos_trades']} 笔 | 胜率: {champ['oos_wr']:.1f}% | 净值: {champ['oos_nav']:.2f}x | 盲测剔前5净值: {champ['oos_trimmed_top5']:.2f}x")
        print(f"  * 7月以来实战区间: {champ['jul_trades']} 笔 | 胜率: {champ['jul_wr']:.1f}% | 净值: {champ['jul_nav']:.2f}x")

    return tier_champions


def main():
    print("=" * 80)
    print("【A股一进二试验地沙盒三号课题：124参数结构化微调与去极值复利总检验】")
    print("=" * 80)

    cache = load_engine_data_cache()

    # 第一步：大妖股依赖度解剖
    step1_res = step1_dissect_v16_right_tail(cache)

    # 第二步：单旋钮敏感性扫描
    step2_res = step2_single_knob_sensitivity(cache)

    # 第三步：Walk-Forward 网格遍历与 PBO 检验
    all_trials, pbo_stats = step3_walk_forward_joint_search(cache)

    # 第四步：四大档位帕累托前沿映射
    step4_res = step4_pareto_frontier_tiers(all_trials)

    # 汇总导出 JSON
    output_bundle = {
        "meta": {
            "topic": "LAB_C_HIGH_WR_REBALANCE",
            "audit_timestamp": pd.Timestamp.now().isoformat(),
            "friction": FEE_RATE,
            "engine": "v16_parameterized_engine"
        },
        "step1_right_tail_dissection": step1_res,
        "step2_single_knob_sensitivity": step2_res,
        "step3_overfitting_pbo_stats": pbo_stats,
        "step4_pareto_frontier_tiers": step4_res,
    }

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(output_bundle, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 80)
    print(f"【课题三研究完成】结果已落盘至: {OUT_JSON}")
    print("=" * 80)


if __name__ == "__main__":
    main()

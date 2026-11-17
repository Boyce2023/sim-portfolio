# -*- coding: utf-8 -*-
"""
v18_case_selector.py: V18 题库抽样与题型分布控制模块
严格限制单文件 150 行以内。
"""
import random
from collections import defaultdict

def select_pack1_50(buy_cases, empty_cases, seed=42):
    rng = random.Random(seed)
    # 按年份分组
    buy_by_yr = defaultdict(list)
    for c in buy_cases.values():
        buy_by_yr[c["date"][:4]].append(c)
    emp_by_yr = defaultdict(list)
    for c in empty_cases.values():
        emp_by_yr[c["date"][:4]].append(c)

    # 目标：34 买入题 (23 赢 11 亏，胜率 67.6% 贴近 V18 账本 68.4%) + 16 空仓题
    # 年份分布：2022(9+3), 2023(5+4), 2024(5+4), 2025(8+2), 2026(7+3)
    quota_buy = {"2022": 9, "2023": 5, "2024": 5, "2025": 8, "2026": 7}
    quota_emp = {"2022": 3, "2023": 4, "2024": 4, "2025": 2, "2026": 3}

    picked_buys = []
    for yr in ["2022", "2023", "2024", "2025", "2026"]:
        pool = list(buy_by_yr[yr])
        wins = [c for c in pool if c["market_best_ret"] > 0]
        losses = [c for c in pool if c["market_best_ret"] <= 0]
        q = quota_buy[yr]
        loss_q = {"2022": 3, "2023": 2, "2024": 2, "2025": 2, "2026": 2}[yr]
        rng.shuffle(wins)
        rng.shuffle(losses)
        p_l = losses[:min(len(losses), loss_q)]
        win_q = q - len(p_l)
        p_w = wins[:win_q]
        picked_buys.extend(p_w + p_l)

    picked_emps = []
    for yr in ["2022", "2023", "2024", "2025", "2026"]:
        pool = list(emp_by_yr[yr])
        rng.shuffle(pool)
        picked_emps.extend(pool[:quota_emp[yr]])

    all_50 = sorted(picked_buys + picked_emps, key=lambda c: c["date"])
    res = []
    for i, c in enumerate(all_50):
        cp = dict(c)
        cp["id"] = i + 1
        res.append(cp)
    return res

def select_chal_5(buy_cases, empty_cases, seed=88):
    rng = random.Random(seed)
    years = ["2022", "2023", "2024", "2025", "2026"]
    
    # 尝试寻找覆盖 A, B, C, D, E 且 5 年各 1 关的组合
    for _ in range(5000):
        emp_yr = rng.choice(years)
        buy_yrs = [y for y in years if y != emp_yr]
        
        emp_pool = [c for c in empty_cases.values() if c["date"][:4] == emp_yr]
        if not emp_pool:
            continue
        c_e = dict(rng.choice(emp_pool))
        
        picked_buys = []
        possible = True
        for yr in buy_yrs:
            pool = [c for c in buy_cases.values() if c["date"][:4] == yr]
            if not pool:
                possible = False
                break
            picked_buys.append(rng.choice(pool))
        if not possible:
            continue
        
        combo = picked_buys + [c_e]
        ans_set = set(c["market_ans"] for c in combo)
        if ans_set == {"A", "B", "C", "D", "E"}:
            combo.sort(key=lambda c: c["date"])
            res = []
            for i, c in enumerate(combo):
                cp = dict(c)
                cp["id"] = i + 1
                res.append(cp)
            return res

    # 兜底：若随机未命中，按固定组合返回
    combo = []
    for yr in years[:-1]:
        pool = [c for c in buy_cases.values() if c["date"][:4] == yr]
        combo.append(pool[0])
    combo.append([c for c in empty_cases.values() if c["date"][:4] == years[-1]][0])
    combo.sort(key=lambda c: c["date"])
    for i, c in enumerate(combo):
        c["id"] = i + 1
    return combo

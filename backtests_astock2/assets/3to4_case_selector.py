# -*- coding: utf-8 -*-
"""三进四刷题机题库样本选择器（按年份与题型严格对齐实操分布）"""
import os, sys
import pandas as pd
CUR_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if CUR_DIR not in sys.path:
    sys.path.insert(0, CUR_DIR)
from score_3to4_v31_card import score_single_3to4_row
from bt_3to4_v32_final_build import sim_pool, df, code_bars

p_v32 = sim_pool("touch65_1130", "cut_weak", "pm1345", True, False)

def select_case_indices():
    """返回标准卷50题与挑战赛5题的原始索引列表"""
    years = ["2022", "2023", "2024", "2025", "2026"]
    by_cat = {y: {"pass_win": [], "pass_loss": [], "pass_not_trig": [], "sub90": [], "veto": []} for y in years}
    for idx, r in enumerate(df.itertuples(index=False)):
        res = score_single_3to4_row(r._asdict())
        y = str(r.buy_date)[:4]
        if y not in by_cat: continue
        c6 = str(r.code).zfill(6)
        cb = code_bars.get(c6)
        if cb is None or str(r.buy_date) not in cb["date_to_pos"]: continue
        if cb["date_to_pos"][str(r.buy_date)] < 1: continue
        pool_res = p_v32[idx]
        if not res["passed_skeleton"]: cat = "veto"
        elif res["score"] < 90: cat = "sub90"
        elif pool_res is None: cat = "pass_not_trig"
        elif pool_res["net_ret"] > 0: cat = "pass_win"
        else: cat = "pass_loss"
        by_cat[y][cat].append(idx)

    # 50题配比方案：每年前4赚、2亏、适量未过线与骨架否决，兼顾未触发撤单
    quotas = {
        "2022": [("pass_win", 4), ("pass_loss", 2), ("pass_not_trig", 1), ("sub90", 2), ("veto", 1)],
        "2023": [("pass_win", 4), ("pass_loss", 2), ("pass_not_trig", 1), ("sub90", 2), ("veto", 1)],
        "2024": [("pass_win", 4), ("pass_loss", 2), ("pass_not_trig", 0), ("sub90", 3), ("veto", 1)],
        "2025": [("pass_win", 4), ("pass_loss", 2), ("pass_not_trig", 0), ("sub90", 3), ("veto", 1)],
        "2026": [("pass_win", 4), ("pass_loss", 2), ("pass_not_trig", 0), ("sub90", 2), ("veto", 2)],
    }
    std_indices = []
    for y in years:
        for cat, cnt in quotas[y]:
            if cnt <= 0: continue
            cand_list = by_cat[y][cat]
            cand_list.sort(key=lambda i: df.iloc[i]["buy_date"])
            step = max(1, len(cand_list) // cnt)
            picks = [cand_list[k * step] for k in range(cnt)]
            std_indices.extend(picks)

    # 挑战赛5关：跨5年挑选最具代表性知名标的
    # 2022: 002761 浙江建投 (score>=102, 大牛股)
    # 2023: 002855 捷荣技术 (经典主线龙头)
    # 2024: 000002 万科A (2024-10-08 骨架否决典型: 四板一字不可买且换手低)
    # 2025: 000718 苏宁环球 (高分过线实战胜局)
    # 2026: 000678 襄阳轴承 (2026最新高确信标的)
    chal_picks = []
    # 2022
    for i in by_cat["2022"]["pass_win"]:
        if "浙江建投" in str(df.iloc[i]["name"]) or "大港股份" in str(df.iloc[i]["name"]):
            chal_picks.append(i); break
    if len(chal_picks) < 1: chal_picks.append(by_cat["2022"]["pass_win"][0])
    # 2023
    for i in by_cat["2023"]["pass_win"]:
        if "捷荣技术" in str(df.iloc[i]["name"]) or "通化金马" in str(df.iloc[i]["name"]):
            chal_picks.append(i); break
    if len(chal_picks) < 2: chal_picks.append(by_cat["2023"]["pass_win"][0])
    # 2024 (万科A 骨架否决或经典胜局)
    vanke = [i for i in by_cat["2024"]["veto"] if "万科" in str(df.iloc[i]["name"])]
    if vanke: chal_picks.append(vanke[0])
    else: chal_picks.append(by_cat["2024"]["pass_win"][0])
    # 2025
    for i in by_cat["2025"]["pass_win"]:
        if "苏宁环球" in str(df.iloc[i]["name"]) or "山子高科" in str(df.iloc[i]["name"]):
            chal_picks.append(i); break
    if len(chal_picks) < 4: chal_picks.append(by_cat["2025"]["pass_win"][0])
    # 2026
    for i in by_cat["2026"]["pass_win"]:
        if "襄阳轴承" in str(df.iloc[i]["name"]) or "闽东电力" in str(df.iloc[i]["name"]):
            chal_picks.append(i); break
    if len(chal_picks) < 5: chal_picks.append(by_cat["2026"]["pass_win"][0])

    return std_indices, chal_picks

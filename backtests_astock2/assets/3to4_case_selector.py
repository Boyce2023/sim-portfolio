# -*- coding: utf-8 -*-
"""三进四 V4.0 刷题机题库样本选择器（按年份与题型严格对齐 V4.0 台账分布）"""
import os
import sys
import importlib

CUR_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS_DIR = os.path.dirname(os.path.abspath(__file__))
for _p in (CUR_DIR, ASSETS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from score_3to4_v31_card import score_single_3to4_row
loader_m = importlib.import_module("3to4_v40_loader")


def select_case_indices():
    """返回标准卷50题与挑战赛5题在 cand_df 中的原始索引列表（胜负触发单100%对齐 V4.0 台账）"""
    bundle = loader_m.get_v40_bundle()
    df = bundle["cand_df"]
    code_bars = bundle["code_bars"]
    p_1030 = bundle["p_1030"]
    ledger_map = bundle["ledger_map"]

    years = ["2022", "2023", "2024", "2025", "2026"]
    by_cat = {y: {"pass_win": [], "pass_loss": [], "pass_not_trig": [], "sub90": [], "veto": []} for y in years}
    for idx, r in enumerate(df.itertuples(index=False)):
        bd = str(r.buy_date)
        y = bd[:4]
        if y not in by_cat or bd < "2022-01-04":
            continue
        c6 = str(r.code).zfill(6)
        cb = code_bars.get(c6)
        if cb is None or bd not in cb["date_to_pos"] or cb["date_to_pos"][bd] < 1:
            continue
        res = score_single_3to4_row(r._asdict())
        pool_res = p_1030[idx]
        if not res["passed_skeleton"]:
            by_cat[y]["veto"].append(idx)
        elif res["score"] < 90:
            by_cat[y]["sub90"].append(idx)
        elif pool_res is None:
            by_cat[y]["pass_not_trig"].append(idx)
        elif (bd, c6) in ledger_map:
            cat = "pass_win" if pool_res["net_ret"] > 0 else "pass_loss"
            by_cat[y][cat].append(idx)

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
            if cnt <= 0:
                continue
            cand_list = sorted(by_cat[y][cat], key=lambda i: df.iloc[i]["buy_date"])
            step = max(1, len(cand_list) // cnt)
            picks = [cand_list[k * step] for k in range(cnt)]
            std_indices.extend(picks)

    chal_picks = []
    targets = [
        ("2022", "pass_win", ("浙江建投", "大港股份")),
        ("2023", "pass_win", ("捷荣技术", "通化金马")),
        ("2024", "veto", ("万科",)),
        ("2025", "pass_win", ("苏宁环球", "山子高科")),
        ("2026", "pass_win", ("襄阳轴承", "闽东电力")),
    ]
    for yr, cat, kw_tup in targets:
        picked = None
        for i in by_cat[yr][cat]:
            nm = str(df.iloc[i]["name"])
            if any(k in nm for k in kw_tup):
                picked = i
                break
        if picked is None:
            fallback_pool = by_cat[yr][cat] or by_cat[yr]["pass_win"]
            picked = fallback_pool[0]
        chal_picks.append(picked)

    return std_indices, chal_picks

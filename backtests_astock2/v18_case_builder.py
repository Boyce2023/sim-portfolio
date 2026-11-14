# -*- coding: utf-8 -*-
"""
v18_case_builder.py: V18 单日案例数据组装器
严格对齐 V18 生产规则，单个文件控制在 150 行以内。
"""
import random
from collections import defaultdict
import numpy as np
import pandas as pd

from v16_data_loader import EVENT_BASKET_PLATES
from v16_cand_builder import build_cand_dict
from v16_case_builder import build_theme_dict, build_case_dict
from build_true_v16_trainer_data import EARN_PAT, EVENT_PAT, NON_THEME

def build_case_for_day_v18(
    d2, cands_today, engine_fn, stk_hist, all_dts, dt_to_idx,
    price_lookup, zt_cnt_map, dt_cnt_map, fb_cnt_map, seal_rate_map,
    promo_ma5_map, max_height_map, d1_fb_open_map, sh_date_to_idx,
    sh_rows, plate_daily_sz, kpl_dates, seed=42, forced_plates=None
):
    idx2 = dt_to_idx.get(d2, -1)
    if idx2 <= 0:
        return None
    d1 = all_dts[idx2 - 1]
    is_mon = (pd.to_datetime(d2) - pd.to_datetime(d1)).days >= 3

    full_plate_cands = defaultdict(list)
    for c in cands_today:
        if (c.dt_str == d1) and (not c.is_st):
            full_plate_cands[c.plate].append(c)

    valid_cands_today = [
        c for c in cands_today if (c.dt_str == d1) and (not c.is_st)
        and (c.d2_open < c.d2_zt_p - 0.005)
        and (c.plate not in EVENT_BASKET_PLATES) and (c.plate not in NON_THEME)
        and (not EARN_PAT.search(c.plate)) and (not EVENT_PAT.search(c.plate))
    ]
    plate_cands = defaultdict(list)
    for c in valid_cands_today:
        plate_cands[c.plate].append(c)

    chosen_plates = []
    if forced_plates:
        for fp in forced_plates:
            if fp in plate_cands and len(plate_cands[fp]) >= 2 and fp not in NON_THEME and not EARN_PAT.search(fp):
                chosen_plates.append(fp)

    # 优先保证 V18 出手股所在板块入选
    v18_trig = [c for c in valid_cands_today if getattr(c, "v18_tot", getattr(c, "v16_tot", False))]
    if v18_trig and len(chosen_plates) < 3:
        best_trig = min(v18_trig, key=lambda c: -getattr(c, "v18_sv", getattr(c, "v16_sv", 0.0)))
        if best_trig.plate in plate_cands and len(plate_cands[best_trig.plate]) >= 2 and best_trig.plate not in chosen_plates:
            chosen_plates.append(best_trig.plate)

    other_plates = sorted(
        [p for p, cl in plate_cands.items() if len(cl) >= 2 and p not in chosen_plates],
        key=lambda p: max(getattr(c, "t_score_c", 100.0) for c in plate_cands[p]),
        reverse=True
    )
    for p in other_plates:
        if len(chosen_plates) >= 3:
            break
        chosen_plates.append(p)
    chosen_plates = chosen_plates[:3]
    if len(chosen_plates) < 3:
        return None

    rng = random.Random(seed)
    rng.shuffle(chosen_plates)

    theme_cands_map = {}
    all_case_cands = []
    for p in chosen_plates:
        pool = sorted(plate_cands[p], key=lambda c: getattr(c, "sys_rank_score", 0.0), reverse=True)
        picked = (pool[:3] + [pool[-1]]) if len(pool) > 4 else pool
        theme_cands_map[p] = picked
        all_case_cands.extend(picked)

    all_case_cands.sort(key=lambda c: getattr(c, "sys_rank_score", 0.0), reverse=True)
    cand_to_sysrank = {c.c6: i + 1 for i, c in enumerate(all_case_cands)}

    themes_json = []
    all_built_cands = []
    k_idx = kpl_dates.index(d1) if d1 in kpl_dates else -1

    for p_idx, p in enumerate(chosen_plates):
        pool_shuffled = list(theme_cands_map[p])
        rng.shuffle(pool_shuffled)
        opt_letters = ["A", "B", "C", "D"]
        all_p_cands = plate_cands[p]
        p_cands_in_win = sorted(
            [c for c in all_p_cands if c.is_buyable_open and (not c.nuclear_halt) and (not c.promo_freeze)
             and ((is_mon and (0.020 <= c.d2_o_pct <= 0.088)) or ((not is_mon) and (0.022 <= c.d2_o_pct <= 0.078)))],
            key=lambda c: c.d2_o_pct, reverse=True
        )
        p_non_yizi = sorted(all_p_cands, key=lambda c: c.d2_o_pct, reverse=True)

        built_cands = []
        d3_dt = all_dts[dt_to_idx[d2] + 1] if dt_to_idx.get(d2, 0) + 1 < len(all_dts) else d2
        for opt_i, c in enumerate(pool_shuffled):
            opt = opt_letters[opt_i]
            sim_res = engine_fn(c)
            d2_bar = price_lookup.get((c.c6, d2))
            d2_k = [round(float(d2_bar[0]), 2), round(float(d2_bar[1]), 2), round(float(d2_bar[2]), 2), round(float(d2_bar[3]), 2), round(float(d2_bar[8]), 0)] if d2_bar else [round(c.d2_open, 2), round(c.d2_high, 2), round(c.d2_low, 2), round(c.d2_close, 2), 100000.0]
            d3_bar = price_lookup.get((c.c6, d3_dt))
            d3_k = [round(float(d3_bar[0]), 2), round(float(d3_bar[1]), 2), round(float(d3_bar[2]), 2), round(float(d3_bar[3]), 2), round(float(d3_bar[8]), 0)] if d3_bar else d2_k
            cd = build_cand_dict(
                c, opt, p_idx, sim_res, stk_hist.get(c.c6, []),
                d1, d2_k, d3_k, is_mon, p_cands_in_win, p_non_yizi, cand_to_sysrank, full_plate_cands[p]
            )
            built_cands.append(cd)
            all_built_cands.append(cd)

        if k_idx >= 0:
            heat_bars = [plate_daily_sz[kpl_dates[j]].get(p, 0) for j in range(max(0, k_idx - 9), k_idx + 1)]
            if len(heat_bars) < 10: heat_bars = [0] * (10 - len(heat_bars)) + heat_bars
        else: heat_bars = [1] * 10

        th_obj = build_theme_dict(p_idx, p, theme_cands_map[p], all_p_cands, pool_shuffled[0].p_sz, heat_bars, is_mon, built_cands, full_plate_cands[p])
        themes_json.append(th_obj)

    return build_case_dict(
        1, d2, d1, themes_json, all_built_cands, cands_today,
        zt_cnt_map, dt_cnt_map, fb_cnt_map, seal_rate_map, promo_ma5_map,
        max_height_map, d1_fb_open_map, sh_date_to_idx, sh_rows
    )

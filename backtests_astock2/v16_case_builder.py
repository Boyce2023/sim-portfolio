# -*- coding: utf-8 -*-
"""
v16_case_builder.py: 题库关卡与题材对象构建器 (100% 契约对齐)
"""
import re, datetime, numpy as np, pandas as pd
from collections import Counter

WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

def build_theme_dict(p_idx, pname, chosen_pool, all_p_cands, p_sz, heat_bars, is_mon, built_cands, full_p_cands=None):
    stat_cands = full_p_cands if full_p_cands is not None else all_p_cands
    flc = sum(bool(c.d2_is_yizi or (c.d2_o_pct > (0.088 if is_mon else 0.078))) for c in stat_cands)
    plate_yz_cnt = sum(bool(c.d2_is_yizi) for c in stat_cands)
    high_open_cnt = sum(bool(c.d2_o_pct >= 0.020) for c in stat_cands)
    avg_open_val = np.mean([c.d2_o_pct for c in all_p_cands]) * 100.0 if all_p_cands else 0.0

    sub_counts = Counter(str(getattr(c, "r_short", "")) for c in all_p_cands if getattr(c, "r_short", "") and getattr(c, "r_short", "") != "其他")
    sub_max = sub_counts.most_common(1)[0][1] if sub_counts else 1

    if flc == 1: escort = "有高标护航 · 前排锁筹1只(助攻)"
    elif flc >= 2: escort = f"有高标护航 · 前排锁筹{flc}只(抽血)"
    else: escort = "无高标 · 前排锁筹0只"

    sample_c = chosen_pool[0]
    is_dying = getattr(sample_c, "is_dying_pulse", False)
    is_broad = getattr(sample_c, "is_broad_ind", False)
    is_ht = getattr(sample_c, "is_hard_tech", False) or bool(re.search(r"(?:机器人|芯片|半导体|算力|AI|华为|低空|光通信|智能驾驶)", pname))
    has_nw = getattr(sample_c, "has_new_term", False) or getattr(sample_c, "is_pioneer_word", False)

    if is_dying: term_type = f"前3至8日曾满5板且昨无连板股 · 同分支{sub_max}只"
    elif is_broad: term_type = f"宽泛行业分类 · 同细分分支{sub_max}只"
    elif is_ht: term_type = f"科技制造属性 · 同细分分支{sub_max}只"
    elif has_nw: term_type = f"近15日首现细分词 · 同分支{sub_max}只"
    else: term_type = f"常规题材分类 · 同细分分支{sub_max}只"

    pass_l3 = (len(all_p_cands) <= 1) or ((getattr(sample_c, "plate_peers_open_avg", 0.0) >= -0.010) and ((getattr(sample_c, "plate_d2_open_avg", 0.0) >= -0.005) or (getattr(sample_c, "plate_high_open_cnt", 0) >= 2)))
    if is_dying: p_warn = "前3至8日曾满5板且昨无2板以上连板股"
    elif is_broad and sub_max < 2: p_warn = "宽泛行业分类且同细分词不足2只"
    elif p_sz > 35: p_warn = "昨涨停超35家（量化上限拦截）"
    elif not pass_l3: p_warn = "板块竞价均幅<-0.5%且高开≥2%不足2只"
    else: p_warn = ""

    rk_th = getattr(sample_c, "rk_theme", np.nan)
    elo_rk = int(rk_th) if (pd.notna(rk_th) and np.isfinite(rk_th)) else int(getattr(sample_c, "rk_c", 1))
    t_sc = getattr(sample_c, "p_theme_med", getattr(sample_c, "s_prior_dual", 100.0))
    elo_sc = round(float(t_sc), 1) if (pd.notna(t_sc) and np.isfinite(t_sc)) else 100.0

    return {
        "idx": p_idx, "name": pname, "elo_rank": elo_rk, "elo_score": elo_sc,
        "first_boards": int(p_sz), "p_sz": int(p_sz), "sub_cluster_cnt": int(sub_max),
        "front_lock_cnt": int(flc), "plate_yizi_cnt": int(plate_yz_cnt),
        "high_open_cnt": int(high_open_cnt), "term_type": term_type, "escort": escort,
        "avg_open": f"{avg_open_val:+.1f}% (高开>=2%共{high_open_cnt}只)",
        "purifier_warn": p_warn, "heat_bars": heat_bars, "cands": built_cands
    }

def build_case_dict(case_id, d2, d1, themes_json, all_built_cands, day_cands_all, zt_cnt_map, dt_cnt_map, fb_cnt_map, seal_rate_map, promo_ma5_map, max_height_map, d1_fb_open_map, sh_date_to_idx, sh_rows):
    d2_dt_obj = datetime.date.fromisoformat(d2)
    d1_dt_obj = datetime.date.fromisoformat(d1)
    weekday_str = WEEKDAYS[d2_dt_obj.weekday()]
    d1_weekday_str = WEEKDAYS[d1_dt_obj.weekday()]
    gap_days = (d2_dt_obj - d1_dt_obj).days
    is_mon = gap_days >= 3

    sensor_cold = any(getattr(c, "weak_open_sensor_cold", False) for c in day_cands_all)
    is_melee = any(getattr(c, "is_melee_day", False) for c in day_cands_all)
    is_dom_nodrg = any(getattr(c, "is_dom_no_dragon", False) for c in day_cands_all)
    if is_mon:
        win_rule_str = "周一/节后窗口 2.0%~8.8% (周末发酵加10分)"
    elif sensor_cold:
        win_rule_str = "常规工作日窗口 2.2%~7.8% (近20日高开封板偏冷:低于3.5%扣25分)"
    else:
        win_rule_str = "常规工作日窗口 2.2%~7.8% (低于3.1%弱开扣15分)"
    if is_melee:
        win_rule_str += " · 三题材混战卡全场前二"
    elif is_dom_nodrg:
        win_rule_str += " · 断层主线无头名禁选第三题材"
    seal_r = seal_rate_map.get(d1, 0.55)
    tot_thr = 329.8 if seal_r > 0.75 else 304.8
    thr_reason_str = "昨封板率超75%提门槛至329.8分" if seal_r > 0.75 else "标准出手门槛304.8分"

    promo_ma5_val = promo_ma5_map.get(d1, 0.20) * 100.0
    promo_ma5_str = f"{promo_ma5_val:.1f}%" + (" (低于13%冰点熔断)" if promo_ma5_val < 13.0 else "")

    nuclear_halt = any(getattr(c, "nuclear_halt", False) for c in day_cands_all)
    promo_freeze = any(getattr(c, "promo_freeze", False) for c in day_cands_all)

    mkt_yizi_cnt = int(sum(bool(getattr(c, "d2_is_yizi", False)) for c in day_cands_all))
    if 1 <= mkt_yizi_cnt <= 2: mkt_yizi_str = f"{mkt_yizi_cnt} 家 (1至2家黄金共振)"
    elif mkt_yizi_cnt == 0: mkt_yizi_str = "0 家 (无一字催化)"
    else: mkt_yizi_str = f"{mkt_yizi_cnt} 家"

    executed_cands = [cd for cd in all_built_cands if cd["executed"]]
    if not executed_cands:
        market_ans, market_best_theme_idx, market_best_ret = "E", -1, 0.0
        best_stock_code, best_stock_name, case_type = "", "全场空仓防守", "empty"
    else:
        best_cand = max(executed_cands, key=lambda cd: cd["net_ret"])
        if best_cand["net_ret"] <= 0.5:
            market_ans, market_best_theme_idx, market_best_ret = "E", -1, 0.0
            best_stock_code, best_stock_name, case_type = "", "全场空仓防守", "empty"
        else:
            market_ans = best_cand["opt"]
            market_best_theme_idx = best_cand["theme_idx"]
            market_best_ret = best_cand["net_ret"]
            best_stock_code = best_cand["code"]
            best_stock_name = best_cand["name"]
            case_type = "dragon" if (best_cand["is_sealed"] and best_cand["net_ret"] >= 5.0) else "normal"

    v16_trig_cands = [cd for cd in all_built_cands if cd["sys_pass"]]
    if v16_trig_cands:
        sys_best = min(v16_trig_cands, key=lambda cd: cd["sys_rank"])
        sys_cand_code = sys_best["code"]
        sys_cand_name = f"{sys_best['name']}（触发量化出手）" if sys_best["executed"] else f"{sys_best['name']}（触发挂单但未点火撤单）"
        sys_cand_opt = sys_best["opt"]
        sys_cand_theme_idx = sys_best["theme_idx"]
        sys_ret = sys_best["net_ret"] if sys_best["executed"] else 0.0
    else:
        top1 = min(all_built_cands, key=lambda cd: cd["sys_rank"])
        sys_cand_code, sys_cand_opt, sys_cand_theme_idx, sys_ret = "", "", -1, 0.0
        sys_cand_name = f"今日量化空仓（榜首{top1['name']}未达出手线）"

    sys_beat = bool(market_best_ret > sys_ret)

    sent_zt = int(zt_cnt_map.get(d1, 50))
    sent_dt = int(dt_cnt_map.get(d1, 5))
    sent_first = int(fb_cnt_map.get(d1, 30))
    sent_promo = f"{seal_rate_map.get(d1, 0.20)*100:.1f}%"
    sent_height = f"{int(max_height_map.get(d1, 1))} 连板"
    sent_open = f"{d1_fb_open_map.get(d1, 0.0)*100:+.1f}%"
    sent_arr = [sent_zt, sent_dt, sent_first, sent_promo, sent_height, sent_open]

    sh_idx = sh_date_to_idx.get(d1, len(sh_rows) - 2)
    idx_bars = sh_rows[max(0, sh_idx - 29): sh_idx + 1]
    d2_sh_idx = sh_date_to_idx.get(d2, sh_idx + 1)
    idx_d2 = sh_rows[d2_sh_idx] if d2_sh_idx < len(sh_rows) else idx_bars[-1]

    return {
        "id": case_id, "date": d2, "d1_date": d1, "title": f"{d2} {weekday_str} 早盘多主线博弈局",
        "type": case_type, "market_ans": market_ans, "market_best_theme_idx": market_best_theme_idx,
        "market_best_ret": market_best_ret, "best_stock_code": best_stock_code, "best_stock_name": best_stock_name,
        "sys_cand_code": sys_cand_code, "sys_cand_name": sys_cand_name, "sys_cand_opt": sys_cand_opt,
        "sys_cand_theme_idx": sys_cand_theme_idx, "sys_ret": sys_ret, "sys_beat": sys_beat,
        "sent": sent_arr, "idx_bars": idx_bars, "idx_d2": idx_d2, "themes": themes_json,
        "weekday_str": weekday_str, "d1_weekday_str": d1_weekday_str, "gap_days": gap_days,
        "is_mon_window": is_mon, "window_rule_str": win_rule_str, "tot_thr": tot_thr,
        "thr_reason_str": thr_reason_str, "promo_ma5_str": promo_ma5_str, "nuclear_halt": nuclear_halt,
        "promo_freeze": promo_freeze, "mkt_yizi_cnt": mkt_yizi_cnt, "mkt_yizi_str": mkt_yizi_str,
    }

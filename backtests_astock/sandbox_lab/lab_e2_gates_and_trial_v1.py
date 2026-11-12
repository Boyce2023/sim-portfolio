#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
lab_e2_gates_and_trial_v1.py
================================================================================
A股一进二试验地沙盒（Sandbox Lab）五号课题 B 组主研究脚本
课题：全部门禁过滤器、特殊通道、买卖点子规则逐一消融 + 试验盘一号候选组合联测

严格遵循：
1. 生产盘硬隔离（绝不修改主策略文件与飞书文档，不修改 v16_parameterized_engine.py）
2. 绝对零未来函数（09:25 PIT，双边千二摩擦 FEE_RATE = 0.0020）
3. 严格沙盒只读（mode=ro, uri=True，严禁 import yfinance）
4. D15 回测防伪四必核（全5年、近3年、近1年、7月以来四期胜率、真实盈亏比、等权与单仓净值、最大回撤、剔前5去极值净值与沪深300超额）
5. 样本内（2022~2024 IS）vs 样本外（2025~2026 OOS）盲测验证
================================================================================
"""

import os
import sys
import time
import json
import sqlite3
import datetime
from typing import Dict, Any, List, Optional, Tuple, Set

import numpy as np
import pandas as pd
from scipy.stats import norm

# 引入基础沙盒底座
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from v16_parameterized_engine import (
    load_engine_data_cache,
    V16_DEFAULT_KNOBS,
    FEE_RATE,
    CSI300_5Y_CUM,
    CSI300_3Y_CUM,
    CSI300_1Y_CUM,
    CSI300_JUL_CUM,
    CSI300_ANNUAL,
)

OUT_JSON = f"{CURRENT_DIR}/lab_e2_results.json"
OUT_REPORT = f"{CURRENT_DIR}/LAB_E2_GATES_AND_TRIAL_V1_REPORT.md"


# ==============================================================================
# 1. 前视生态传感器与题材结构特征提取（严格 t-1 PIT 零未来函数）
# ==============================================================================
def build_pit_sensors_and_theme_matrix(cache: Dict[str, Any]) -> Tuple[Dict[str, Dict[str, float]], Set[str], Set[str]]:
    """
    预先计算：
    1. 传感器 3（量化高开封板率 roll20_ho_zt）：t-1 滚动前20日高开 >= 5.5% 标的二板封板率
    2. 断层第一主线无龙一日（dom_no_dragon）：第一题材领先第二题材 >= 20分或首板数 >= 6且 >= 2倍第二题材，但第一题材无过线标的
    3. 三大题材势均力敌混战日（melee_days）：前三大题材极差 <= 15分且规模均在 2~5 之间
    """
    hist_fb = cache["hist_fb"]

    # 1. 传感器 3 计算
    daily_records = []
    for d, grp in hist_fb.groupby("d2_dt"):
        buyable = grp[grp["is_buyable_open"] & (~grp["nuclear_halt"]) & (~grp["promo_freeze"])]
        ho = buyable[buyable["d2_o_pct"] >= 0.055]
        n_ho = len(ho)
        rate_ho_zt = (ho["d2_is_zt"].sum() / n_ho) if n_ho > 0 else np.nan
        daily_records.append({
            "date": d,
            "rate_ho_zt": rate_ho_zt,
        })
    df_daily = pd.DataFrame(daily_records).sort_values("date").reset_index(drop=True)
    df_daily["roll20_ho_zt"] = df_daily["rate_ho_zt"].shift(1).rolling(20, min_periods=5).mean().fillna(0.45)
    sensors_map = df_daily.set_index("date").to_dict(orient="index")

    # 2. 题材结构矩阵计算 (完全对齐 lab_b_theme_structure_matrix.py)
    valid_plate = hist_fb[(hist_fb["plate"] != "其他") & (~hist_fb["is_event_basket"])].copy()
    pg = valid_plate.groupby(["d2_dt", "plate"], as_index=False).agg(
        p_sz_max=("p_sz", "max"),
        p_theme_med=("s_prior_dual", "median")
    )
    pg_m = pg[pg["p_sz_max"] >= 2].copy()
    pg_m["rk_theme"] = pg_m.groupby("d2_dt")["p_theme_med"].rank(ascending=False, method="min")

    daily_t1 = pg_m[pg_m["rk_theme"] == 1].sort_values(["d2_dt", "p_theme_med"], ascending=[True, False]).drop_duplicates("d2_dt").set_index("d2_dt")
    daily_t2 = pg_m[pg_m["rk_theme"] == 2].sort_values(["d2_dt", "p_theme_med"], ascending=[True, False]).drop_duplicates("d2_dt").set_index("d2_dt")
    daily_t3 = pg_m[pg_m["rk_theme"] == 3].sort_values(["d2_dt", "p_theme_med"], ascending=[True, False]).drop_duplicates("d2_dt").set_index("d2_dt")

    # 现役 V16 候选池基准判断（用于识别 Theme 1 是否有龙一过线）
    wk_mask = cache["wk_mask"]
    q_pen = - np.where((~wk_mask) & (hist_fb["d2_o_pct"] < 0.031), 15.0, 0.0)
    dd20 = cache["dd20"]
    clean_brk60 = cache["clean_brk60"]
    d_ov = np.where((~clean_brk60) & (dd20 <= 0.82), -10.0, 0.0)
    open_cnt = cache["open_cnt"]
    seal_time = cache["seal_time"]
    is_ht = (open_cnt == 1) & (seal_time <= "10:30:00") & (hist_fb["d1_seal_tightness"] >= 38.0)
    bon_tape = np.where(is_ht, 5.0, 0.0) + np.where(hist_fb["has_ir_pit"], 5.0, 0.0)
    sp_v16 = hist_fb["s_prior_wk"] + cache["name_sub20"] + cache["y_std"] * 0.5
    sq_v16 = hist_fb["s_quant_dual"] + q_pen + d_ov + bon_tape + cache["rk_fix_delta"] + cache["y_std"] * 0.5
    sc_v16 = sp_v16 + sq_v16
    thr_vec = np.where(hist_fb["mkt_seal_rate"] > 0.75, 304.8 + 25.0, 304.8)

    p_tight = (hist_fb["d1_seal_tightness"] >= 37.0).values
    pass_nd_true = (
        (~((hist_fb["p_sz"] >= 2) & (hist_fb["true_buy_rk"] >= 3)))
        & (~((hist_fb["plate_d2_yizi_cnt"] >= 1) & ((hist_fb["mcap"] > 90.0) | (hist_fb["d1_seal_tightness"] < 15.0))))
    ).values
    open_in_win = (
        (wk_mask & hist_fb["d2_o_pct"].between(0.020, 0.088))
        | ((~wk_mask) & hist_fb["d2_o_pct"].between(0.022, 0.078))
    ).values
    m_t1_v16 = cache["common_ok"] & open_in_win & (sp_v16 >= 45.0) & (sq_v16 >= 150.0) & (sc_v16 >= thr_vec)
    mm_v16 = ((m_t1_v16 & cache["pass_l1"] & cache["pass_l2"] & cache["pass_l3"] & pass_nd_true & cache["pass_ac"]) | (cache["m_t2_base"] & cache["pass_l2"])) & p_tight
    mmon_v16 = (
        cache["common_ok"] & wk_mask & hist_fb["d2_o_pct"].between(0.015, 0.090)
        & (sp_v16 >= 38.0) & (sq_v16 >= 145.0) & (sc_v16 >= thr_vec)
        & cache["pass_l1"] & cache["pass_l2"] & cache["pass_l3"] & pass_nd_true & cache["pass_ac"] & p_tight
    )
    tot_v16 = (mm_v16 | (mmon_v16 & (~mm_v16))).copy()

    dom_no_dragon = set()
    melee_days = set()

    for d in sorted(daily_t1.index):
        t1_row = daily_t1.loc[d]
        t2_row = daily_t2.loc[d] if d in daily_t2.index else None
        t3_row = daily_t3.loc[d] if d in daily_t3.index else None

        t1_med = float(t1_row["p_theme_med"])
        t2_med = float(t2_row["p_theme_med"]) if t2_row is not None else 0.0
        t1_sz = int(t1_row["p_sz_max"])
        t2_sz = int(t2_row["p_sz_max"]) if t2_row is not None else 1

        diff_1_2 = t1_med - t2_med
        ratio_sz = t1_sz / max(1, t2_sz)
        is_dominant = (diff_1_2 >= 20.0) or ((t1_sz >= 6) and (ratio_sz >= 2.0))

        if is_dominant:
            t1_plate = t1_row["plate"]
            sub_d = hist_fb[hist_fb["d2_dt"] == d]
            sub_d_passed = sub_d[tot_v16[sub_d.index]]
            t1_has_passed = (sub_d_passed["plate"] == t1_plate).any() if len(sub_d_passed) > 0 else False
            if not t1_has_passed:
                dom_no_dragon.add(d)

        if t1_row is not None and t2_row is not None and t3_row is not None:
            t3_med = float(t3_row["p_theme_med"])
            range_top3 = t1_med - t3_med
            sz_max = max(int(t1_row["p_sz_max"]), int(t2_row["p_sz_max"]), int(t3_row["p_sz_max"]))
            sz_min = min(int(t1_row["p_sz_max"]), int(t2_row["p_sz_max"]), int(t3_row["p_sz_max"]))
            if range_top3 <= 15.0 and sz_max <= 5 and sz_min >= 2:
                melee_days.add(d)

    return sensors_map, dom_no_dragon, melee_days


# ==============================================================================
# 2. 高灵活可消融交易执行器构建器
# ==============================================================================
def create_ablation_trade_engine(
    price_lookup: Dict,
    all_dts: List[str],
    dt_to_idx: Dict[str, int],
    bars_5m_map: Dict,
    fee: float = FEE_RATE,
    # 买入端配置
    allow_do_direct: bool = True,
    ignition_mode: str = "standard",   # "standard": max(o2*1.012, c1*1.065), "only_close": c1*1.065, "only_open": o2*1.012
    k_open: float = 1.012,
    k_close: float = 1.065,
    # 卖出端配置
    exit_d2_red_hold: bool = True,      # 买入日未封收红+次日高开>=0.5%留仓
    exit_1430_rush: bool = True,        # 14:30 后炸板抢跑
    exit_1030_cut: bool = True,         # 10:30 破分时均线止损
    exit_immunity: bool = True,         # 满三板断板收涨>=2%免死多拿1天
):
    """
    高度可消融的逐笔交易执行器，严格零未来函数。
    """
    def sim_trade(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        c6, d2 = row["c6"], row["d2_dt"]
        idx2 = dt_to_idx.get(d2, -1)
        if idx2 < 0 or idx2 >= len(all_dts) - 1:
            return None
        d2_bar = price_lookup.get((c6, d2))
        if not d2_bar:
            return None
        o2, h2, l2, c2, zt2, dt2, is_zt2, is_yz_dt2 = d2_bar
        if o2 >= zt2 - 0.005 or o2 <= 0:
            return None

        is_monday = row.get("gap_days", 1) >= 3
        cand_score = row.get("score_active", row.get("score_0", 0.0))
        cand_lead = row.get("buy_open_lead", 0.0)

        # 竞价直买子规则消融
        do_direct = allow_do_direct and is_monday and (cand_score >= 310.0) and (cand_lead >= 0.025)

        # 点火价腿消融
        c1 = float(row["close"])
        if ignition_mode == "only_close":
            trig_p_calc = min(zt2, round(c1 * k_close, 2))
        elif ignition_mode == "only_open":
            trig_p_calc = min(zt2, round(o2 * k_open, 2))
        else: # standard
            trig_p_calc = min(zt2, max(round(o2 * k_open, 2), round(c1 * k_close, 2)))

        buy_px = round(float(o2), 2) if do_direct else round(float(trig_p_calc), 2)
        if (not do_direct) and (h2 < float(trig_p_calc) or float(trig_p_calc) >= zt2 - 0.005):
            return None

        prev_c = round(float(c2), 2)
        idx3 = idx2 + 1
        d3 = all_dts[idx3]
        d3_bar = price_lookup.get((c6, d3))
        if not d3_bar:
            net = round((prev_c / buy_px) * (1.0 - fee) - 1.0, 4)
            return {
                "net_ret": net, "exit_date": d3, "exit_at_open": True, "sealed_2b": int(is_zt2),
                "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": prev_c
            }
        o3, h3, l3, c3, zt3, dt3, is_zt3, is_yz_dt3 = d3_bar

        # Case 1: D2 未封二板 (炸板或冲高回落)
        if not is_zt2:
            if exit_d2_red_hold:
                d2_closed_up = (c2 >= float(row["close"]))
                if d2_closed_up and (o3 >= round(c2 * 1.005, 2)) and not is_yz_dt3:
                    if is_zt3:
                        curr = idx3 + 1
                        boards_held = 3
                        used_immunity = False
                        prev_c = round(float(c3), 2)
                        while curr < len(all_dts) and (curr - idx2 <= 12):
                            dc = all_dts[curr]
                            b = price_lookup.get((c6, dc))
                            if not b: break
                            oc, hc, lc, cc, ztc, dtc, iztc, iyzc = b
                            if iyzc:
                                prev_c = round(float(cc), 2); curr += 1; continue

                            arr = bars_5m_map.get((c6, dc))
                            if arr is not None and len(arr) >= 12:
                                idx_1030 = -1
                                cum_v, cum_a = 0.0, 0.0
                                for bi in range(len(arr)):
                                    cum_v += arr[bi, 5]; cum_a += arr[bi, 6]
                                    if arr[bi, 0] == 1030:
                                        idx_1030 = bi; break
                                if idx_1030 >= 0:
                                    bc_1030 = arr[idx_1030, 4]
                                    vwap_1030 = cum_a / cum_v if cum_v > 0 else bc_1030
                                    if bc_1030 >= ztc - 0.01:
                                        if exit_1430_rush:
                                            for bi in range(idx_1030 + 1, len(arr) - 1):
                                                if arr[bi, 0] >= 1430 and arr[bi, 4] < ztc - 0.01:
                                                    px = round(float(arr[bi + 1, 1]), 2)
                                                    return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "5m_1430_rush"}
                                        if iztc:
                                            prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
                                        else:
                                            px = round(float(cc), 2)
                                            return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "eod_break"}
                                    elif exit_1030_cut and (bc_1030 < vwap_1030):
                                        px = round(float(arr[idx_1030 + 1, 1]), 2) if idx_1030 + 1 < len(arr) else round(float(bc_1030), 2)
                                        return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "5m_1030_weak_cut"}
                                    else:
                                        if iztc:
                                            prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
                                        if exit_immunity and (boards_held >= 3) and (not used_immunity) and (cc >= prev_c * 1.02) and (curr + 1 < len(all_dts)):
                                            used_immunity = True; prev_c = round(float(cc), 2); curr += 1; continue
                                        px = round(float(cc), 2)
                                        return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "eod_close"}

                            if iztc:
                                prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
                            if exit_immunity and (boards_held >= 3) and (not used_immunity) and (cc >= prev_c * 1.02) and (curr + 1 < len(all_dts)):
                                used_immunity = True; prev_c = round(float(cc), 2); curr += 1; continue
                            px = round(float(cc), 2)
                            return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "eod_close"}
                        return {"net_ret": round((prev_c / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": all_dts[min(curr, len(all_dts)-1)], "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": prev_c}
                    else:
                        px = round(float(c3), 2)
                        return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": d3, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "nshape_d3_close"}

            # 若关掉未封收红留仓，或者未满足留仓条件，次日开盘直接走
            curr = idx3
            while curr < len(all_dts):
                b = price_lookup.get((c6, all_dts[curr]))
                if not b or not b[7]:
                    px = round(float(b[0]), 2) if b else prev_c
                    return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": all_dts[curr], "exit_at_open": True, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "fail_open_cut"}
                curr += 1
            return None

        # Case 2: D2 封死二板 (连板骑乘状态机)
        curr = idx3
        boards_held = 2
        used_immunity = False

        while curr < len(all_dts) and (curr - idx2 <= 12):
            dc = all_dts[curr]
            b = price_lookup.get((c6, dc))
            if not b: break
            oc, hc, lc, cc, ztc, dtc, iztc, iyzc = b
            if iyzc:
                prev_c = round(float(cc), 2); curr += 1; continue

            arr = bars_5m_map.get((c6, dc))
            if arr is not None and len(arr) >= 12:
                idx_1030 = -1
                cum_v, cum_a = 0.0, 0.0
                for bi in range(len(arr)):
                    cum_v += arr[bi, 5]; cum_a += arr[bi, 6]
                    if arr[bi, 0] == 1030:
                        idx_1030 = bi; break
                if idx_1030 >= 0:
                    bc_1030 = arr[idx_1030, 4]
                    vwap_1030 = cum_a / cum_v if cum_v > 0 else bc_1030
                    if bc_1030 >= ztc - 0.01:
                        if exit_1430_rush:
                            for bi in range(idx_1030 + 1, len(arr) - 1):
                                if arr[bi, 0] >= 1430 and arr[bi, 4] < ztc - 0.01:
                                    px = round(float(arr[bi + 1, 1]), 2)
                                    return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "5m_1430_rush"}
                        if iztc:
                            prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
                        else:
                            px = round(float(cc), 2)
                            return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "eod_break"}
                    elif exit_1030_cut and (bc_1030 < vwap_1030):
                        px = round(float(arr[idx_1030 + 1, 1]), 2) if idx_1030 + 1 < len(arr) else round(float(bc_1030), 2)
                        return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "5m_1030_weak_cut"}
                    else:
                        if iztc:
                            prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
                        if exit_immunity and (boards_held >= 3) and (not used_immunity) and (cc >= prev_c * 1.02) and (curr + 1 < len(all_dts)):
                            used_immunity = True; prev_c = round(float(cc), 2); curr += 1; continue
                        px = round(float(cc), 2)
                        return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "eod_close"}

            if iztc:
                prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
            if exit_immunity and (boards_held >= 3) and (not used_immunity) and (cc >= prev_c * 1.02) and (curr + 1 < len(all_dts)):
                used_immunity = True; prev_c = round(float(cc), 2); curr += 1; continue
            px = round(float(cc), 2)
            return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "eod_close"}

        return {"net_ret": round((prev_c / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": all_dts[min(curr, len(all_dts)-1)], "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": prev_c, "tag": "max_hold"}

    return sim_trade


# ==============================================================================
# 3. 核心评估器：全维度指标、样本内外与逐年对比
# ==============================================================================
def evaluate_ablation_experiment(
    config_name: str,
    desc: str,
    cache: Dict[str, Any],
    sensors_map: Dict[str, Dict[str, float]],
    dom_no_dragon: Set[str],
    melee_days: Set[str],
    # 门禁开闭旋钮 (默认均为 V16 标准设定)
    allow_l1a: bool = False,         # True: 去掉 L1a (不过滤 is_event_basket)
    allow_l1b: bool = False,         # True: 去掉 L1b (不过滤 is_broad_ind & sub<2)
    allow_l2: bool = False,          # True: 去掉 L2 (不过滤 is_dying_pulse)
    allow_l3: bool = False,          # True: 去掉 L3 (不过滤 pass_l3)
    allow_psz35: bool = False,       # True: 去掉 p_sz <= 35 限制
    allow_nuclear: bool = False,     # True: 去掉 nuclear_halt 熔断门
    allow_promo_freeze: bool = False,# True: 去掉 promo_freeze 熔断门
    overheat_add: float = 25.0,      # 0.0: 去掉过热加分门槛
    block_rk4: bool = True,          # False: 去掉 rk_theme >= 4 篡位过滤
    min_tightness: float = 37.0,     # 0.0: 去掉封单紧密度 37 分底线
    ignore_yizi_mcap90: bool = False,# True: 去掉一字板题材 mcap <= 90亿限制
    ignore_tbrk3_filter: bool = False,# True: 去掉 p_sz >= 2 时 true_buy_rk <= 2 限制
    sp_min: float = 45.0,            # -999.0: 去掉 sp >= 45 底线
    sq_min: float = 150.0,           # -999.0: 去掉 sq >= 150 底线
    allow_m_t2: bool = True,         # False: 去掉独苗先锋第二通道 m_t2
    allow_mmon: bool = True,         # False: 去掉周一兜底子通道 mmon
    # 买卖点执行配置
    allow_do_direct: bool = True,
    ignition_mode: str = "standard",
    exit_d2_red_hold: bool = True,
    exit_1430_rush: bool = True,
    exit_1030_cut: bool = True,
    exit_immunity: bool = True,
    # 用户钦定 3 条新规则
    rule_alpha: bool = False,        # 断层主线无龙一时禁止买入第三题材
    rule_beta: bool = False,         # 三大题材混战日卡全场竞价前二或硬催化
    rule_gamma: bool = False,        # Sensor 3: roll20_ho_zt < 0.45 时弱开 < 3.5% 扣 25 分
) -> Dict[str, Any]:
    hist_fb = cache["hist_fb"]
    price_lookup = cache["price_lookup"]
    all_dts = cache["all_dts"]
    dt_to_idx = cache["dt_to_idx"]
    bars_5m_map = cache["bars_5m_map"]

    seal_time = cache["seal_time"]
    open_cnt = cache["open_board_count"] if "open_board_count" in cache else cache["open_cnt"]
    dd20 = cache["dd20"]
    clean_brk60 = cache["clean_brk60"]
    wk_mask = cache["wk_mask"]
    rk_fix_delta = cache["rk_fix_delta"]
    name_sub20 = cache["name_sub20"]
    y_std = cache["y_std"]
    m_t2_base = cache["m_t2_base"]

    # 1. 基础情绪与通用开盘准入
    nuc_mask = np.zeros(len(hist_fb), dtype=bool) if allow_nuclear else hist_fb["nuclear_halt"].values
    promo_mask = np.zeros(len(hist_fb), dtype=bool) if allow_promo_freeze else hist_fb["promo_freeze"].values
    common_ok = (hist_fb["is_buyable_open"].values & (~nuc_mask) & (~promo_mask))

    # 2. 净化门
    if allow_l1a and allow_l1b:
        pass_l1 = np.ones(len(hist_fb), dtype=bool)
    elif allow_l1a:
        pass_l1 = (~(hist_fb["is_broad_ind"] & (hist_fb["sub_cluster_cnt"] < 2))).values
    elif allow_l1b:
        pass_l1 = (~hist_fb["is_event_basket"]).values
    else:
        pass_l1 = ((~hist_fb["is_event_basket"]) & (~(hist_fb["is_broad_ind"] & (hist_fb["sub_cluster_cnt"] < 2)))).values

    pass_l2 = np.ones(len(hist_fb), dtype=bool) if allow_l2 else (~hist_fb["is_dying_pulse"]).values
    pass_l3 = np.ones(len(hist_fb), dtype=bool) if allow_l3 else (
        (hist_fb["plate_fb_cnt"] <= 1)
        | ((hist_fb["plate_peers_open_avg"] >= -0.010) & ((hist_fb["plate_d2_open_avg"] >= -0.005) | (hist_fb["plate_high_open_cnt"] >= 2)))
    ).values

    if allow_psz35:
        pass_ac = (~hist_fb["notice_bad"]).values
    else:
        pass_ac = ((~(hist_fb["p_sz"] > 35)) & (~hist_fb["notice_bad"])).values

    # 3. 动态打分与弱开传感器 (Rule Gamma)
    # 如果开启 Rule Gamma，需要按日检查 roll20_ho_zt
    if rule_gamma:
        # 逐日自适应弱开惩罚
        pen_thr_vec = np.zeros(len(hist_fb))
        pen_val_vec = np.zeros(len(hist_fb))
        for d, s in sensors_map.items():
            ho_rate = s.get("roll20_ho_zt", 0.45)
            if ho_rate < 0.45:
                p_val, p_thr = 25.0, 0.035
            else:
                p_val, p_thr = 15.0, 0.031
            idx_d = (hist_fb["d2_dt"] == d).values
            pen_thr_vec[idx_d] = p_thr
            pen_val_vec[idx_d] = p_val
        q_pen = - np.where((~wk_mask) & (hist_fb["d2_o_pct"] < pen_thr_vec), pen_val_vec, 0.0)
    else:
        q_pen = - np.where((~wk_mask) & (hist_fb["d2_o_pct"] < 0.031), 15.0, 0.0)

    d_ov = np.where((~clean_brk60) & (dd20 <= 0.82), -10.0, 0.0)
    is_ht = (open_cnt == 1) & (seal_time <= "10:30:00") & (hist_fb["d1_seal_tightness"] >= 38.0)
    bon_tape = np.where(is_ht, 5.0, 0.0) + np.where(hist_fb["has_ir_pit"], 5.0, 0.0)

    sp_v = hist_fb["s_prior_wk"].values + name_sub20 + y_std * 0.5
    sq_v = hist_fb["s_quant_dual"].values + q_pen + d_ov + bon_tape + rk_fix_delta + y_std * 0.5
    sc_v = sp_v + sq_v
    hist_fb["score_active"] = sc_v

    # 4. 门槛与过热保护
    base_thr = 304.8
    thr_vec = np.where(hist_fb["mkt_seal_rate"] > 0.75, base_thr + overheat_add, base_thr)

    # 5. 个股硬门槛
    p_tight = (hist_fb["d1_seal_tightness"] >= min_tightness).values

    # pass_nd 拆解
    cond_tbrk = np.zeros(len(hist_fb), dtype=bool) if ignore_tbrk3_filter else ((hist_fb["p_sz"] >= 2) & (hist_fb["true_buy_rk"] >= 3)).values
    if ignore_yizi_mcap90:
        cond_yizi_mcap = ((hist_fb["plate_d2_yizi_cnt"] >= 1) & (hist_fb["d1_seal_tightness"] < 15.0)).values
    else:
        cond_yizi_mcap = ((hist_fb["plate_d2_yizi_cnt"] >= 1) & ((hist_fb["mcap"] > 90.0) | (hist_fb["d1_seal_tightness"] < 15.0))).values
    pass_nd = (~cond_tbrk) & (~cond_yizi_mcap)

    # 开盘窗口
    open_in_win = (
        (wk_mask & hist_fb["d2_o_pct"].between(0.020, 0.088))
        | ((~wk_mask) & hist_fb["d2_o_pct"].between(0.022, 0.078))
    ).values

    # 主通道 M_T1
    m_t1 = common_ok & open_in_win & (sp_v >= sp_min) & (sq_v >= sq_min) & (sc_v >= thr_vec)
    m_t1_full = m_t1 & pass_l1 & pass_l2 & pass_l3 & pass_nd & pass_ac & p_tight

    # 旁路 1: M_T2 独苗先锋通道
    if allow_m_t2:
        m_t2_full = m_t2_base & pass_l2 & p_tight
    else:
        m_t2_full = np.zeros(len(hist_fb), dtype=bool)

    mm = (m_t1_full | m_t2_full)

    # 旁路 2: MMON 周一兜底通道
    if allow_mmon:
        mmon = (
            common_ok & wk_mask & hist_fb["d2_o_pct"].between(0.015, 0.090)
            & (sp_v >= (sp_min - 7.0)) & (sq_v >= (sq_min - 5.0)) & (sc_v >= thr_vec)
            & pass_l1 & pass_l2 & pass_l3 & pass_nd & pass_ac & p_tight
        )
    else:
        mmon = np.zeros(len(hist_fb), dtype=bool)

    tot = (mm | (mmon & (~mm))).copy()

    # 6. 冷门题材防篡位门 (rk_theme >= 4)
    if block_rk4:
        sv = np.where(mm, sc_v + 1000.0, sc_v)
        sub_tot = hist_fb[tot].copy()
        sub_tot["_sv_tmp"] = sv[tot]
        bad_dts = set()
        for d, grp in sub_tot.groupby("d2_dt"):
            if (grp["rk_theme"] == 1).any():
                top_rk = grp.sort_values("_sv_tmp", ascending=False).iloc[0]["rk_theme"]
                if pd.notna(top_rk) and top_rk >= 4:
                    bad_dts.add(d)
        tot = tot & (~hist_fb["d2_dt"].isin(bad_dts)).values

    # 7. 用户钦定新规则应用
    # Rule Alpha: 断层主线无龙一时，禁止买入第三题材 (rk_theme == 3)
    if rule_alpha:
        is_blocked_alpha = np.zeros(len(hist_fb), dtype=bool)
        for idx, (d, rk) in enumerate(zip(hist_fb["d2_dt"], hist_fb["rk_theme"])):
            if d in dom_no_dragon and rk == 3:
                is_blocked_alpha[idx] = True
        tot = tot & (~is_blocked_alpha)

    # Rule Beta: 三大题材混战日，候选股必须 buyable_mkt_open_rk <= 2 或 notice_hard | is_ma
    if rule_beta:
        is_blocked_beta = np.zeros(len(hist_fb), dtype=bool)
        for idx, (d, mrk, nh, hm) in enumerate(zip(
            hist_fb["d2_dt"],
            hist_fb["buyable_mkt_open_rk"],
            hist_fb["notice_hard"],
            hist_fb["is_ma"]
        )):
            if d in melee_days:
                is_breakout = (mrk <= 2) or bool(nh) or bool(hm)
                if not is_breakout:
                    is_blocked_beta[idx] = True
        tot = tot & (~is_blocked_beta)

    # 8. 执行模拟引擎
    engine_fn = create_ablation_trade_engine(
        price_lookup=price_lookup,
        all_dts=all_dts,
        dt_to_idx=dt_to_idx,
        bars_5m_map=bars_5m_map,
        fee=FEE_RATE,
        allow_do_direct=allow_do_direct,
        ignition_mode=ignition_mode,
        exit_d2_red_hold=exit_d2_red_hold,
        exit_1430_rush=exit_1430_rush,
        exit_1030_cut=exit_1030_cut,
        exit_immunity=exit_immunity,
    )

    sv = np.where(mm, sc_v + 1000.0, sc_v)
    hist_fb["_sv_eval"] = sv

    sub = hist_fb[tot & (hist_fb["d2_dt"] >= "2022-01-01") & (hist_fb["d2_dt"] <= "2026-11-09")].copy()
    sub.sort_values(["d2_dt", "_sv_eval"], ascending=[True, False], inplace=True)

    free_dt, free_open = "", False
    nav_1s, peak_1s, mdd_1s = 1.0, 1.0, 0.0
    trades_1s = []
    eq_daily_rets = []

    for d2, grp in sub.groupby("d2_dt", sort=True):
        rows = [r._asdict() if hasattr(r, "_asdict") else r.to_dict() for _, r in grp.iterrows()]
        if free_dt == "" or d2 > free_dt or (d2 == free_dt and free_open):
            tr1 = engine_fn(rows[0])
            if tr1 is not None:
                nav_1s *= (1.0 + tr1["net_ret"])
                peak_1s = max(peak_1s, nav_1s)
                mdd_1s = max(mdd_1s, (peak_1s - nav_1s) / peak_1s)
                free_dt, free_open = tr1["exit_date"], tr1["exit_at_open"]
                trades_1s.append(tr1)

        d_rets = []
        for r_cand in rows:
            tr = engine_fn(r_cand)
            if tr is not None:
                d_rets.append(tr["net_ret"])
        if d_rets:
            eq_daily_rets.append((d2, float(np.mean(d_rets))))

    nav_eq, pk_eq, mdd_eq = 1.0, 1.0, 0.0
    for _, dr in eq_daily_rets:
        nav_eq *= (1.0 + dr)
        pk_eq = max(pk_eq, nav_eq)
        mdd_eq = max(mdd_eq, (pk_eq - nav_eq) / pk_eq)

    tot_trades = len(trades_1s)
    if tot_trades == 0:
        return {
            "config_name": config_name, "desc": desc, "trades": 0, "wr": 0.0, "payoff": 0.0,
            "nav_1s": 1.0, "mdd_1s": 0.0, "daily_eq": 1.0, "trimmed_top5": 1.0,
            "trades_list": [], "annual": {}, "periods": {}
        }

    rets = [t["net_ret"] for t in trades_1s]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r < 0]
    wr = len(wins) / tot_trades
    avg_win = np.mean(wins) if wins else 0.0
    avg_loss = abs(np.mean(losses)) if losses else 1e-4
    payoff = avg_win / avg_loss if avg_loss > 0 else 0.0

    # 剔除前 5 大牛股去极值净值
    sorted_rets = sorted(rets, reverse=True)
    rem_top5 = sorted_rets[5:] if len(sorted_rets) > 5 else sorted_rets
    trimmed_top5 = float(np.prod([1.0 + r for r in rem_top5]))

    # 四期与样本内外
    # IS: 2022-2024
    t_is = [t for t in trades_1s if t["buy_date"] < "2025-01-01"]
    wr_is = len([t for t in t_is if t["net_ret"] > 0]) / len(t_is) if t_is else 0.0
    nav_is = float(np.prod([1.0 + t["net_ret"] for t in t_is])) if t_is else 1.0

    # OOS: 2025-2026
    t_oos = [t for t in trades_1s if t["buy_date"] >= "2025-01-01"]
    wr_oos = len([t for t in t_oos if t["net_ret"] > 0]) / len(t_oos) if t_oos else 0.0
    nav_oos = float(np.prod([1.0 + t["net_ret"] for t in t_oos])) if t_oos else 1.0

    # 3Y: 2024-01-01 起 (代码标准口径) 与 2023-11-10 (滚动3年)
    t_3y = [t for t in trades_1s if t["buy_date"] >= "2024-01-01"]
    wr_3y = len([t for t in t_3y if t["net_ret"] > 0]) / len(t_3y) if t_3y else 0.0
    nav_3y = float(np.prod([1.0 + t["net_ret"] for t in t_3y])) if t_3y else 1.0

    # 1Y: 2025-11-12 起
    t_1y = [t for t in trades_1s if t["buy_date"] >= "2025-11-12"]
    wr_1y = len([t for t in t_1y if t["net_ret"] > 0]) / len(t_1y) if t_1y else 0.0
    nav_1y = float(np.prod([1.0 + t["net_ret"] for t in t_1y])) if t_1y else 1.0

    # July+: 2026-07-01 起
    t_jul = [t for t in trades_1s if t["buy_date"] >= "2026-07-01"]
    wr_jul = len([t for t in t_jul if t["net_ret"] > 0]) / len(t_jul) if t_jul else 0.0
    nav_jul = float(np.prod([1.0 + t["net_ret"] for t in t_jul])) if t_jul else 1.0

    # 逐年拆解
    annual = {}
    for yr in [2022, 2023, 2024, 2025, 2026]:
        t_yr = [t for t in trades_1s if t["buy_date"][:4] == str(yr)]
        c_nav = float(np.prod([1.0 + t["net_ret"] for t in t_yr])) if t_yr else 1.0
        w_yr = [t["net_ret"] for t in t_yr if t["net_ret"] > 0]
        wr_y = len(w_yr) / len(t_yr) if t_yr else 0.0
        annual[str(yr)] = {
            "trades": len(t_yr),
            "wr": round(wr_y * 100, 1),
            "nav": round(c_nav, 2),
            "mean_ret": round(float(np.mean([t["net_ret"] for t in t_yr])) * 100, 2) if t_yr else 0.0,
        }

    excess_csi300 = round((nav_1s - 1.0) - CSI300_5Y_CUM, 2)
    calmar = round((nav_1s - 1.0) / mdd_1s, 2) if mdd_1s > 0 else 0.0

    return {
        "config_name": config_name,
        "desc": desc,
        "trades": tot_trades,
        "wr": round(wr * 100, 1),
        "payoff": round(payoff, 2),
        "nav_1s": round(nav_1s, 2),
        "mdd_1s": round(mdd_1s * 100, 1),
        "calmar": calmar,
        "daily_eq": round(nav_eq, 2),
        "mdd_daily_eq": round(mdd_eq * 100, 1),
        "trimmed_top5": round(trimmed_top5, 2),
        "excess_csi300": excess_csi300,
        "is_oos": {
            "is_22_24": {"trades": len(t_is), "wr": round(wr_is * 100, 1), "nav": round(nav_is, 2)},
            "oos_25_26": {"trades": len(t_oos), "wr": round(wr_oos * 100, 1), "nav": round(nav_oos, 2)},
        },
        "periods": {
            "5y": {"trades": tot_trades, "wr": round(wr * 100, 1), "nav": round(nav_1s, 2)},
            "3y": {"trades": len(t_3y), "wr": round(wr_3y * 100, 1), "nav": round(nav_3y, 2)},
            "1y": {"trades": len(t_1y), "wr": round(wr_1y * 100, 1), "nav": round(nav_1y, 2)},
            "since_july": {"trades": len(t_jul), "wr": round(wr_jul * 100, 1), "nav": round(nav_jul, 2)},
        },
        "annual": annual,
        "trades_list": trades_1s,
    }


# ==============================================================================
# 4. 主流程编排：全量消融与候选组合测试
# ==============================================================================
def run_all_ablations_and_trials():
    t0 = time.time()
    print("=" * 80)
    print("【A股一进二沙盒五号课题 B 组：门禁消融与试验盘一号候选组合大考】")
    print(f"启动时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    # 1. 加载内存缓存与前视生态
    print("\n>>> [1/4] 加载只读内存缓存与构建 t-1 前视传感器/题材结构...")
    cache = load_engine_data_cache()
    sensors_map, dom_no_dragon, melee_days = build_pit_sensors_and_theme_matrix(cache)
    print(f"    传感器与矩阵计算完成: 混战日 {len(melee_days)} 天, 断层无龙一日 {len(dom_no_dragon)} 天")

    # 2. 现役 V16 基准
    print("\n>>> [2/4] 验证现役定版 V16 Champion 基准...")
    res_baseline = evaluate_ablation_experiment(
        config_name="V16_baseline",
        desc="现役定版 V16 基准完全体",
        cache=cache,
        sensors_map=sensors_map,
        dom_no_dragon=dom_no_dragon,
        melee_days=melee_days,
    )
    print(f"    V16 基准: {res_baseline['trades']}笔 | 胜率 {res_baseline['wr']}% | 盈亏比 {res_baseline['payoff']} | 单仓净值 {res_baseline['nav_1s']}x | MDD {res_baseline['mdd_1s']}% | Trimmed-Top5 {res_baseline['trimmed_top5']}x")
    assert res_baseline["trades"] == 105 and res_baseline["wr"] == 63.8 and res_baseline["nav_1s"] == 211.36, f"V16 benchmark verification failed: {res_baseline}"

    baseline_trades_dict = {(t["buy_date"], t["c6"]): t for t in res_baseline["trades_list"]}

    # 3. 逐项消融实验（核心任务一：全部 ~20 项门禁与子规则逐一摘除）
    print("\n>>> [3/4] 执行核心任务一：逐项消融测试（其余保持 V16 不变）...")
    ablation_defs = [
        # 1. 净化门拆解
        ("A01_no_L1a", "去掉L1a: 事件大筐拦截 (is_event_basket)", {"allow_l1a": True}),
        ("A02_no_L1b", "去掉L1b: 宽泛旧行业拦截 (is_broad_ind & sub<2)", {"allow_l1b": True}),
        ("A03_no_L2", "去掉L2: 退潮脉冲拦截 (is_dying_pulse)", {"allow_l2": True}),
        ("A04_no_L3", "去掉L3: 板块09:25竞价承接过滤 (pass_l3)", {"allow_l3": True}),
        ("A05_no_psz35", "去掉p_sz<=35: 过热大锅饭题材人数上限", {"allow_psz35": True}),

        # 2. 情绪与篡位熔断门拆解
        ("A06_no_nuclear", "去掉nuclear_halt: 昨日首板竞价均值<0%熔断门", {"allow_nuclear": True}),
        ("A07_no_promo_freeze", "去掉promo_freeze: 近5日自然晋级率<13%冰点门", {"allow_promo_freeze": True}),
        ("A08_no_overheat_add", "去掉overheat_add+25: 封板率>75%门槛上浮+25分", {"overheat_add": 0.0}),
        ("A09_no_block_rk4", "去掉rk_theme>=4: 主线在场时冷门题材防篡位门", {"block_rk4": False}),

        # 3. 个股硬门槛与双门槛拆解
        ("A10_no_ptight", "去掉p_tight>=37: 首板封单紧密度硬底线", {"min_tightness": 0.0}),
        ("A11_no_yizi_mcap90", "去掉pass_nd中一字板题材mcap<=90亿限制", {"ignore_yizi_mcap90": True}),
        ("A12_no_tbrk3_filter", "去掉pass_nd中p_sz>=2时true_buy_rk<=2限制", {"ignore_tbrk3_filter": True}),
        ("A13_no_sp_min", "去掉sp_v>=45题材单项底线 (只看总分>=304.8)", {"sp_min": -999.0}),
        ("A14_no_sq_min", "去掉sq_v>=150量化单项底线 (只看总分>=304.8)", {"sq_min": -999.0}),

        # 4. 特殊旁路子通道拆解
        ("A15_no_m_t2", "去掉m_t2: 独苗先锋第二通道 (p_sz==1)", {"allow_m_t2": False}),
        ("A16_no_mmon", "去掉mmon: 周一放宽兜底子通道 (1.5%~9.0%,sp>=38,sq>=145)", {"allow_mmon": False}),

        # 5. 买入与卖出子规则拆解
        ("A17_no_do_direct", "去掉do_direct: 周一>=310分竞价直买 (改为摸点火价)", {"allow_do_direct": False}),
        ("A18_ign_only_c1065", "点火价去掉o2*1.012腿 (只看c1*1.065)", {"ignition_mode": "only_close"}),
        ("A19_ign_only_o1012", "点火价去掉c1*1.065腿 (只看o2*1.012)", {"ignition_mode": "only_open"}),
        ("A20_exit_no_d2_red_hold", "卖出端去掉未封收红留仓 (未封次日开盘一律走)", {"exit_d2_red_hold": False}),
        ("A21_exit_no_1430_rush", "卖出端去掉14:30炸板抢跑 (等15:00收盘)", {"exit_1430_rush": False}),
        ("A22_exit_no_1030_cut", "卖出端去掉10:30破分时均线止损 (全天拿至收盘)", {"exit_1030_cut": False}),
        ("A23_exit_no_immunity", "卖出端去掉满三板断板免死一次多拿1天", {"exit_immunity": False}),
    ]

    ablation_results = {}
    print(f"\n{'ID':<20s} | {'测试项说明':<32s} | {'5Y笔':<4s} | {'胜率':<5s} | {'盈亏比':<5s} | {'单仓净值':<7s} | {'MDD':<5s} | {'去极值Top5':<8s} | {'IS净值':<6s} | {'OOS净值':<6s}")
    print("-" * 115)
    print(f"{'V16_baseline':<20s} | {'现役定版 V16 基准完全体':<32s} | {res_baseline['trades']:4d} | {res_baseline['wr']:4.1f}% | {res_baseline['payoff']:5.2f} | {res_baseline['nav_1s']:6.2f}x | {res_baseline['mdd_1s']:4.1f}% | {res_baseline['trimmed_top5']:6.2f}x | {res_baseline['is_oos']['is_22_24']['nav']:5.2f}x | {res_baseline['is_oos']['oos_25_26']['nav']:5.2f}x")

    for tag, name_desc, kwargs in ablation_defs:
        res_abl = evaluate_ablation_experiment(
            config_name=tag,
            desc=name_desc,
            cache=cache,
            sensors_map=sensors_map,
            dom_no_dragon=dom_no_dragon,
            melee_days=melee_days,
            **kwargs
        )
        ablation_results[tag] = res_abl

        # 交易差集
        t_curr_set = {(t["buy_date"], t["c6"]) for t in res_abl["trades_list"]}
        base_set = set(baseline_trades_dict.keys())
        added_keys = t_curr_set - base_set
        removed_keys = base_set - t_curr_set

        res_abl["diff_vs_baseline"] = {
            "added_count": len(added_keys),
            "removed_count": len(removed_keys),
            "added_trades": [t for t in res_abl["trades_list"] if (t["buy_date"], t["c6"]) in added_keys],
            "removed_trades": [baseline_trades_dict[k] for k in removed_keys],
        }

        print(f"{tag:<20s} | {name_desc:<32s} | {res_abl['trades']:4d} | {res_abl['wr']:4.1f}% | {res_abl['payoff']:5.2f} | {res_abl['nav_1s']:6.2f}x | {res_abl['mdd_1s']:4.1f}% | {res_abl['trimmed_top5']:6.2f}x | {res_abl['is_oos']['is_22_24']['nav']:5.2f}x | {res_abl['is_oos']['oos_25_26']['nav']:5.2f}x")

    # 4. 核心任务二：试验盘一号候选组合联测
    print("\n" + "=" * 80)
    print(">>> [4/4] 执行核心任务二：试验盘一号候选组合联测与逐笔穿透...")
    print("=" * 80)

    # 组合一：现役 V16 基准
    c1 = res_baseline

    # 组合二：V16 仅做减法（砍掉14:30抢跑 + 砍掉纯冗余 L1b与sq_min限制）
    c2 = evaluate_ablation_experiment(
        config_name="C2_V16_sub",
        desc="② V16 仅做减法(砍14:30抢跑+砍冗余门)",
        cache=cache,
        sensors_map=sensors_map,
        dom_no_dragon=dom_no_dragon,
        melee_days=melee_days,
        allow_l1b=True,
        sq_min=-999.0,
        exit_1430_rush=False
    )

    # 组合三：V16 + 用户钦定 3 条新规则 (α + β + γ)
    c3 = evaluate_ablation_experiment(
        config_name="C3_V16_3new",
        desc="③ V16 + 3条新规则(α+β+γ)",
        cache=cache,
        sensors_map=sensors_map,
        dom_no_dragon=dom_no_dragon,
        melee_days=melee_days,
        rule_alpha=True,
        rule_beta=True,
        rule_gamma=True,
    )

    # 组合四：试验盘精简增强版（做减法 + 3条新规则）
    c4 = evaluate_ablation_experiment(
        config_name="C4_Trial_v1",
        desc="④ 试验盘精简增强版(做减法+3条新规则)",
        cache=cache,
        sensors_map=sensors_map,
        dom_no_dragon=dom_no_dragon,
        melee_days=melee_days,
        allow_l1b=True,
        sq_min=-999.0,
        exit_1430_rush=False,
        rule_alpha=True,
        rule_beta=True,
        rule_gamma=True,
    )

    # 组合五：试验盘增强版2（做减法 + 3条新规则 + 砍掉 true_buy_rk<=2 限制）
    c5 = evaluate_ablation_experiment(
        config_name="C5_Trial_v2",
        desc="⑤ 试验盘增强版2(做减法+3新规则+去tbrk3限制)",
        cache=cache,
        sensors_map=sensors_map,
        dom_no_dragon=dom_no_dragon,
        melee_days=melee_days,
        allow_l1b=True,
        sq_min=-999.0,
        ignore_tbrk3_filter=True,
        exit_1430_rush=False,
        rule_alpha=True,
        rule_beta=True,
        rule_gamma=True,
    )

    trial_combos = {
        "combo_1_baseline": c1,
        "combo_2_subtraction_only": c2,
        "combo_3_v16_plus_3new": c3,
        "combo_4_trial_v1_champion": c4,
        "combo_5_trial_v2_notbrk": c5,
    }

    # 计算差集
    for k_c, c_obj in trial_combos.items():
        if k_c == "combo_1_baseline":
            continue
        t_set = {(t["buy_date"], t["c6"]) for t in c_obj["trades_list"]}
        b_set = set(baseline_trades_dict.keys())
        added_keys = t_set - b_set
        removed_keys = b_set - t_set
        c_obj["diff_vs_baseline"] = {
            "added_count": len(added_keys),
            "removed_count": len(removed_keys),
            "added_trades": [t for t in c_obj["trades_list"] if (t["buy_date"], t["c6"]) in added_keys],
            "removed_trades": [baseline_trades_dict[k] for k in removed_keys],
        }

    # 打印横向对比表
    print(f"\n{'组合说明':<32s} | {'5Y笔':<4s} | {'胜率':<5s} | {'盈亏比':<5s} | {'单仓净值':<7s} | {'MDD':<5s} | {'去极值Top5':<8s} | {'IS净值':<6s} | {'OOS净值':<6s}")
    print("-" * 115)
    for c in [c1, c2, c3, c4, c5]:
        print(f"{c['desc']:<32s} | {c['trades']:4d} | {c['wr']:4.1f}% | {c['payoff']:5.2f} | {c['nav_1s']:6.2f}x | {c['mdd_1s']:4.1f}% | {c['trimmed_top5']:6.2f}x | {c['is_oos']['is_22_24']['nav']:5.2f}x | {c['is_oos']['oos_25_26']['nav']:5.2f}x")

    # 导出完整 JSON
    final_output = {
        "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "baseline": c1,
        "ablations": ablation_results,
        "trial_combos": trial_combos,
    }
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(final_output, f, ensure_ascii=False, indent=2)
    print(f"\n成功输出完整实验 JSON 至: {OUT_JSON}")

    return res_baseline, ablation_results, trial_combos, sensors_map, dom_no_dragon, melee_days


if __name__ == "__main__":
    t_start = time.time()
    cache = load_engine_data_cache()
    sensors_map, dom_no_dragon, melee_days = build_pit_sensors_and_theme_matrix(cache)
    res_baseline, ablation_results, trial_combos, sensors_map, dom_no_dragon, melee_days = run_all_ablations_and_trials()

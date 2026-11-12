#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
v16_parameterized_engine.py
================================================================================
A股一进二试验地沙盒（Sandbox Lab）可复用参数化评测底座 (Parameterized V16 Engine)

设计定位：
1. 本模块为 sandbox_lab 下专属的可复用参数化底座，供课题三、课题四等实验共用。
2. 严格沙盒隔离：只读加载底层数据，严禁触碰生产策略文件与主文档。
3. 绝对零未来函数，严格执行双边千二摩擦 (FEE_RATE = 0.0020)。
4. 一次性将特征表与 5 分钟分时轨迹载入内存，单次评估耗时 < 0.05 秒。
5. 7~8 个宏观结构旋钮 (Macro Structural Knobs) 参数化，拒绝 124 参数暴力网格过拟合。
6. 内置 Bailey & Lopez de Prado 多重检验 Sharpe Haircut 计算与去极值净值 (Trimmed NAV) 统计。
================================================================================
"""

import os
import sys
import time
import pickle
import sqlite3
import datetime
from typing import Dict, Any, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.stats import norm

# 摩擦成本与基准常数
FEE_RATE = 0.0020
CSI300_5Y_CUM = -0.1784   # 2022-01-01 至 2026-11-09
CSI300_3Y_CUM = 0.0912    # 2024-01-01 起
CSI300_1Y_CUM = -0.1280   # 近 1 年
CSI300_JUL_CUM = -0.1850  # 2026-07-01 起

CSI300_ANNUAL = {
    "2022": -0.2163,
    "2023": -0.1138,
    "2024": 0.1470,
    "2025": -0.0520,
    "2026": 0.0980
}

PROJECT_ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM_DIR = f"{PROJECT_ROOT}/sim-portfolio"
BACKTEST_ASTOCK_DIR = f"{SIM_DIR}/backtests_astock"

# 全局内存单例缓存
_ENGINE_DATA_CACHE = None


def load_engine_data_cache(force_reload: bool = False) -> Dict[str, Any]:
    """
    一次性载入所有特征、价格字典与 5 分钟分时轨迹，构建毫秒级只读内存缓存。
    """
    global _ENGINE_DATA_CACHE
    if _ENGINE_DATA_CACHE is not None and not force_reload:
        return _ENGINE_DATA_CACHE

    t0 = time.time()
    pkl_fb = "/tmp/astock_hist_fb_preprocessed.pkl"
    pkl_prices = "/tmp/astock_price_lookup.pkl"
    parquet_5m = f"{SIM_DIR}/data/cand_5m_bars_v15_complete.parquet"

    if not os.path.exists(pkl_fb) or not os.path.exists(pkl_prices):
        raise FileNotFoundError(f"未找到预处理特征缓存: {pkl_fb} 或 {pkl_prices}")

    with open(pkl_fb, "rb") as f:
        hist_fb = pickle.load(f)
    with open(pkl_prices, "rb") as f:
        p_data = pickle.load(f)

    price_lookup = p_data["price_lookup"]
    all_dts = p_data["all_dts"]
    dt_to_idx = {d: i for i, d in enumerate(all_dts)}

    # 1. 过滤日期范围与基础列
    hist_fb = hist_fb[hist_fb["d2_dt"].notna() & (hist_fb["d2_dt"] <= "2026-11-10")].copy().reset_index(drop=True)
    hist_fb["gap_days"] = (pd.to_datetime(hist_fb["d2_dt"]) - pd.to_datetime(hist_fb["dt_str"])).dt.days
    hist_fb["c6"] = hist_fb["ticker"].astype(str).str[:6]

    # 2. 挂载证监会二级行业
    csrc_file = f"{SIM_DIR}/data/csrc_industry_l2.csv"
    if not os.path.exists(csrc_file):
        csrc_file = f"{SIM_DIR}/backtest/2026-10-15-review2022/industry.csv"
    ind_df = pd.read_csv(csrc_file)
    ind_df["c6"] = ind_df["code"].astype(str).str[-6:]
    ind_map = dict(zip(ind_df["c6"], ind_df["industry"].fillna("")))
    hist_fb["csrc_ind"] = hist_fb["c6"].map(ind_map).fillna("")

    # 3. 只读挂载首板盘口
    conn_tape = sqlite3.connect(f"file:{SIM_DIR}/data/zt_micro_tape_5y_pit.db?mode=ro", uri=True)
    tape_df = pd.read_sql_query("SELECT trade_date, sec_code, first_seal_time, seal_amount, open_board_count FROM zt_micro_tape", conn_tape)
    conn_tape.close()
    hist_fb = hist_fb.merge(tape_df.drop_duplicates(["trade_date", "sec_code"]), left_on=["dt_str", "c6"], right_on=["trade_date", "sec_code"], how="left")

    # 4. 只读挂载 PIT 机构调研
    conn_ir = sqlite3.connect(f"file:{SIM_DIR}/backtests_astock2/data_5y/cninfo_ir_qa_5y_pit.db?mode=ro", uri=True)
    ir_df = pd.read_sql_query("SELECT sec_code, pub_datetime_cst FROM ir_qa WHERE pub_datetime_cst IS NOT NULL", conn_ir)
    conn_ir.close()
    ir_grp = ir_df.groupby("sec_code")["pub_datetime_cst"].apply(lambda s: np.sort(s.unique())).to_dict()

    ir_7d_pit = np.zeros(len(hist_fb), dtype=bool)
    for idx, (c6, d2) in enumerate(zip(hist_fb["c6"], hist_fb["d2_dt"])):
        arr = ir_grp.get(c6)
        if arr is not None:
            pos = np.searchsorted(arr, f"{d2} 09:25:00", side="left")
            if pos > 0:
                last_dt = arr[pos - 1][:10]
                if 0 <= (pd.Timestamp(d2) - pd.Timestamp(last_dt)).days <= 8:
                    ir_7d_pit[idx] = True
    hist_fb["has_ir_pit"] = ir_7d_pit

    # 5. 题材日排名 rk_theme
    valid_plate = hist_fb[(hist_fb["plate"] != "其他") & (~hist_fb["is_event_basket"])].copy()
    pg = valid_plate.groupby(["d2_dt", "plate"], as_index=False).agg(p_sz_max=("p_sz", "max"), p_theme_med=("s_prior_dual", "median"))
    pg_m = pg[pg["p_sz_max"] >= 2].copy()
    pg_m["rk_theme"] = pg_m.groupby("d2_dt")["p_theme_med"].rank(ascending=False, method="min")
    hist_fb = hist_fb.merge(pg_m[["d2_dt", "plate", "rk_theme"]], on=["d2_dt", "plate"], how="left")

    # 6. 加载 5 分钟 K 线字典
    df_5m = pd.read_parquet(parquet_5m)
    df_5m["hhmm_int"] = df_5m["hhmm"].astype(int)
    df_5m.sort_values(["c6", "date", "hhmm_int"], inplace=True)
    bars_5m_map = {}
    for (c6, dt), grp in df_5m.groupby(["c6", "date"], sort=False):
        bars_5m_map[(c6, dt)] = grp[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy()

    # 7. 预先向量化固定特征
    seal_time = hist_fb["first_seal_time"].fillna("99:99:99").values
    open_cnt = hist_fb["open_board_count"].fillna(0).values
    dd20 = hist_fb["f_dd20_d0"].fillna(0.90).values
    clean_brk60 = (hist_fb["clean_brk60"].values == 1)

    is_granularity = (hist_fb["is_pioneer_word"] | hist_fb["has_new_term"] | hist_fb["own_new_term"] | (hist_fb["sub_cluster_cnt"] >= 2)).values
    bonus_spear = np.where(is_granularity, 15.0, 0.0) + np.where(hist_fb["s_elo"] >= 105.0, 10.0, np.where(hist_fb["s_elo"] <= 95.0, -10.0, 0.0))

    common_ok = (hist_fb["is_buyable_open"] & (~hist_fb["nuclear_halt"]) & (~hist_fb["promo_freeze"])).values
    pass_l1 = ((~hist_fb["is_event_basket"]) & (~(hist_fb["is_broad_ind"] & (hist_fb["sub_cluster_cnt"] < 2)))).values
    pass_l2 = (~hist_fb["is_dying_pulse"]).values
    pass_l3 = ((hist_fb["plate_fb_cnt"] <= 1) | ((hist_fb["plate_peers_open_avg"] >= -0.010) & ((hist_fb["plate_d2_open_avg"] >= -0.005) | (hist_fb["plate_high_open_cnt"] >= 2)))).values
    pass_ac = ((~(hist_fb["p_sz"] > 35)) & (~hist_fb["notice_bad"])).values
    wk_mask = (hist_fb["gap_days"] >= 3).values
    f3_bonus = np.where(hist_fb["notice_hard"], 8.0, 0.0) + np.where(hist_fb["notice_bad"], -35.0, 0.0)
    hist_fb["score_wk"] = hist_fb["score_dual"] + bonus_spear + np.where(wk_mask, 10.0, 0.0) + f3_bonus
    hist_fb["s_prior_wk"] = hist_fb["s_prior_dual"] + bonus_spear + np.where(wk_mask, 10.0, 0.0) + f3_bonus

    # 预计算可买窗口与前排锁筹排位
    in_std_buy_win = common_ok & (
        (wk_mask & hist_fb["d2_o_pct"].between(0.020, 0.088))
        | ((~wk_mask) & hist_fb["d2_o_pct"].between(0.022, 0.078))
    )
    is_front_lock = hist_fb["d2_is_yizi"] | ((~wk_mask) & (hist_fb["d2_o_pct"] > 0.078)) | (wk_mask & (hist_fb["d2_o_pct"] > 0.088))
    hist_fb["_is_front_lock"] = is_front_lock.astype(int)
    hist_fb["front_lock_cnt"] = hist_fb.groupby(["d2_dt", "plate"])["_is_front_lock"].transform("sum")
    hist_fb["mkt_yizi_cnt"] = hist_fb.groupby("d2_dt")["d2_is_yizi"].transform("sum").fillna(0).astype(int)

    hist_fb["_true_buy_o"] = np.where(in_std_buy_win, hist_fb["d2_o_pct"], -9.99)
    hist_fb["true_buy_rk"] = hist_fb.groupby(["d2_dt", "plate"])["_true_buy_o"].rank(ascending=False, method="min")

    has_distinct_sub = (hist_fb["p_sz"] >= 8) & (hist_fb["r_short"] != hist_fb["plate"]) & (hist_fb["r_short"] != "其他") & (hist_fb["r_short"] != "")
    orig_rk_bonus = np.where(hist_fb["buyable_plate_rk"] == 1, 35.0, np.where(has_distinct_sub & (hist_fb["subbranch_rk"] == 1), 24.0, np.where(hist_fb["buyable_plate_rk"] == 2, 8.0, -25.0)))
    true_rk_bonus = np.where(hist_fb["true_buy_rk"] == 1, 35.0, np.where(has_distinct_sub & (hist_fb["subbranch_rk"] == 1), 24.0, np.where(hist_fb["true_buy_rk"] == 2, 8.0, -25.0)))
    rk_fix_delta = true_rk_bonus - orig_rk_bonus

    csrc_sec = [str(c)[:3] if str(c) else "UNK" for c in hist_fb["csrc_ind"]]
    CSRC_PURE_OUTSIDER = {
        "A01","A02","A03","A04","A05","D44","D45","D46","E47","E48","E49","E50",
        "F51","F52","G53","G54","G55","G56","G58","G59","H61","H62","K70","L72","N77","N78",
        "C13","C14","C15","C17","C18","C19","C20","C21","C22"
    }
    is_hard_tech = hist_fb["plate"].astype(str).str.contains(r"(?:机器人|减速器|工业母机|芯片|半导体|光通信|算力|人工智能|AI|软件|信创|华为|消费电子|PCB|通信|数据|数字|智能驾驶|无人驾驶)", regex=True).values
    has_ma_hard = (hist_fb["notice_hard"] | hist_fb["is_ma"]).values
    is_pure_outsider = np.array([ht and (cs in CSRC_PURE_OUTSIDER) and (not hm) for ht, cs, hm in zip(is_hard_tech, csrc_sec, has_ma_hard)], dtype=bool)
    name_sub20 = np.where(is_pure_outsider, -20.0, 0.0)

    flc = hist_fb["front_lock_cnt"].values
    tbrk = hist_fb["true_buy_rk"].values
    myz = hist_fb["mkt_yizi_cnt"].values
    is_super_wave = ((hist_fb["rk_theme"] == 1) & (hist_fb["p_sz"] >= 8) & (tbrk == 1)).values

    y_std = np.select(
        [
            (flc == 1) & (tbrk == 1) & np.isin(myz, [1, 2]),
            (flc == 1) & (tbrk == 1),
            (flc == 1) & (tbrk >= 2),
            (flc >= 2) & is_super_wave,
            (flc == 2) & (~is_super_wave),
            (flc >= 3) & (~is_super_wave),
            (flc == 0) & (myz == 0) & (~has_ma_hard),
        ],
        [8.0, 5.0, -10.0, 5.0, -15.0, -22.0, -5.0],
        default=0.0,
    )

    m_t2_base = (
        common_ok & (hist_fb["p_sz"] == 1)
        & (hist_fb["is_pioneer_word"] | hist_fb["notice_hard"] | hist_fb["is_ma"] | hist_fb["has_new_term"] | hist_fb["own_new_term"])
        & hist_fb["d2_o_pct"].between(0.035, 0.078)
        & (hist_fb["buyable_mkt_open_rk"] <= 3)
        & (hist_fb["d1_seal_tightness"] >= 15.0)
        & ((hist_fb["f_dd20_d0"] <= 0.88) | (hist_fb["clean_brk60"] == 1))
    ).values

    _ENGINE_DATA_CACHE = {
        "hist_fb": hist_fb,
        "price_lookup": price_lookup,
        "all_dts": all_dts,
        "dt_to_idx": dt_to_idx,
        "bars_5m_map": bars_5m_map,
        "seal_time": seal_time,
        "open_cnt": open_cnt,
        "dd20": dd20,
        "clean_brk60": clean_brk60,
        "bonus_spear": bonus_spear,
        "common_ok": common_ok,
        "pass_l1": pass_l1,
        "pass_l2": pass_l2,
        "pass_l3": pass_l3,
        "pass_ac": pass_ac,
        "wk_mask": wk_mask,
        "f3_bonus": f3_bonus,
        "rk_fix_delta": rk_fix_delta,
        "name_sub20": name_sub20,
        "y_std": y_std,
        "m_t2_base": m_t2_base,
    }
    return _ENGINE_DATA_CACHE


# ------------------------------------------------------------------------------
# 7 组宏观结构旋钮默认值定义 (Macro Structural Knobs Baseline)
# ------------------------------------------------------------------------------
V16_DEFAULT_KNOBS = {
    # Knob 1: 总分准入门槛与过热门槛上浮偏移 (基准 304.8，过热 +25.0)
    "score_thr_shift": 0.0,
    "mkt_overheat_thr": 0.75,
    "overheat_add": 25.0,

    # Knob 2: 题材先验集中度 vs 个股量化筹码权重倍率平衡
    "prior_weight_mult": 1.0,
    "quant_weight_mult": 1.0,
    "sp_min_t1": 45.0,
    "sq_min_t1": 150.0,

    # Knob 3: 市值与筹码稳健区 (mcap 上限 90.0, dd20 扣分)
    "mcap_max_t1": 90.0,
    "dd20_cut": 10.0,
    "dd20_thr": 0.82,

    # Knob 4: 开盘涨幅窗口与弱开扣分 (平时 2.2%~7.8%, 周一 2.0%~8.8%, <3.1% 扣分)
    "open_win_low": 0.022,
    "open_win_high": 0.078,
    "pen_weakopen": 15.0,
    "pen_weakopen_thr": 0.031,

    # Knob 5: 首板封单紧密度底线 (min_tight 基准 37.0)
    "min_tightness": 37.0,

    # Knob 6: 盘中点火确认加价倍率 (trig_p = max(o2*1.012, c1*1.065))
    "ignition_k_open": 1.012,
    "ignition_k_close": 1.065,

    # Knob 7: 离场模式与止盈落袋节奏
    # "s8_complete": 现行主策略连板骑乘 + 10:30 分时破线出场 + 三板免死一次
    # "lock_profit_5pct": D3 高开 >= +5% 时竞价挂单锁定 50% 利润
    # "lock_profit_8pct": D3 高开 >= +8% 时竞价挂单锁定 50% 利润
    # "no_immunity": 关掉三板免死一次
    # "all_close": 关掉 10:30 分时卖点，全部尾盘 15:00 收盘卖
    "exit_mode": "s8_complete",
}


def create_parameterized_trade_engine(
    price_lookup: Dict,
    all_dts: List[str],
    dt_to_idx: Dict[str, int],
    bars_5m_map: Dict,
    knobs: Dict[str, Any],
    fee: float = FEE_RATE
):
    """
    根据给定的 Knobs 构建绝对零未来函数的交易执行器。
    """
    exit_mode = knobs.get("exit_mode", "s8_complete")
    k_open = float(knobs.get("ignition_k_open", 1.012))
    k_close = float(knobs.get("ignition_k_close", 1.065))

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
        do_direct = is_monday and (cand_score >= 310.0) and (cand_lead >= 0.025)

        # 动态计算点火价 trig_p
        trig_p_calc = min(zt2, max(round(o2 * k_open, 2), round(float(row["close"]) * k_close, 2)))
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

                        if exit_mode in ("s8_complete", "no_immunity", "lock_profit_5pct", "lock_profit_8pct"):
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
                                        for bi in range(idx_1030 + 1, len(arr) - 1):
                                            if arr[bi, 0] >= 1430 and arr[bi, 4] < ztc - 0.01:
                                                px = round(float(arr[bi + 1, 1]), 2)
                                                return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "5m_1430_rush"}
                                        if iztc:
                                            prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
                                        else:
                                            px = round(float(cc), 2)
                                            return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "eod_break"}
                                    elif bc_1030 < vwap_1030:
                                        px = round(float(arr[idx_1030 + 1, 1]), 2) if idx_1030 + 1 < len(arr) else round(float(bc_1030), 2)
                                        return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "5m_1030_weak_cut"}
                                    else:
                                        if iztc:
                                            prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
                                        if (exit_mode != "no_immunity") and (boards_held >= 3) and (not used_immunity) and (cc >= prev_c * 1.02) and (curr + 1 < len(all_dts)):
                                            used_immunity = True; prev_c = round(float(cc), 2); curr += 1; continue
                                        px = round(float(cc), 2)
                                        return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "eod_close"}

                        if iztc:
                            prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
                        if (exit_mode != "no_immunity") and (boards_held >= 3) and (not used_immunity) and (cc >= prev_c * 1.02) and (curr + 1 < len(all_dts)):
                            used_immunity = True; prev_c = round(float(cc), 2); curr += 1; continue
                        px = round(float(cc), 2)
                        return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "eod_close"}
                    return {"net_ret": round((prev_c / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": all_dts[min(curr, len(all_dts)-1)], "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": prev_c}
                else:
                    px = round(float(c3), 2)
                    return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": d3, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "nshape_d3_close"}

            curr = idx3
            while curr < len(all_dts):
                b = price_lookup.get((c6, all_dts[curr]))
                if not b or not b[7]:
                    px = round(float(b[0]), 2) if b else prev_c
                    return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": all_dts[curr], "exit_at_open": True, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "fail_open_cut"}
                curr += 1
            return None

        # Case 2: D2 封死二板 (连板骑乘或锁利状态机)
        curr = idx3
        boards_held = 2
        used_immunity = False
        has_locked_half = False
        r_half1 = 0.0
        thr_lock = 0.05 if "5pct" in exit_mode else (0.08 if "8pct" in exit_mode else 999.0)

        def make_res(px_exit, exit_dt, tag):
            r_exit = (px_exit / buy_px) * (1.0 - fee) - 1.0
            if has_locked_half:
                net_ret = round(0.5 * r_half1 + 0.5 * r_exit, 4)
                tag_final = f"lock50_{tag}"
            else:
                net_ret = round(r_exit, 4)
                tag_final = tag
            return {
                "net_ret": net_ret, "exit_date": exit_dt, "exit_at_open": False, "sealed_2b": 1,
                "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px_exit, "tag": tag_final
            }

        while curr < len(all_dts) and (curr - idx2 <= 12):
            dc = all_dts[curr]
            b = price_lookup.get((c6, dc))
            if not b: break
            oc, hc, lc, cc, ztc, dtc, iztc, iyzc = b
            if iyzc:
                prev_c = round(float(cc), 2); curr += 1; continue

            # 100% 绝对零未来函数：在 D3 09:25 集合竞价决断
            # 若非一字大幅高开 >= thr_lock 且未涨停 (oc < ztc - 0.005)：
            # 前 50% 仓位在 09:25 无条件按开盘价 oc 卖出落袋，后 50% 仓位继续照常走后续连板状态机！
            if curr == idx3 and exit_mode.startswith("lock_profit_"):
                o_gain = oc / prev_c - 1.0
                if o_gain >= thr_lock and oc < ztc - 0.005:
                    has_locked_half = True
                    p_lock1 = round(float(oc), 2)
                    r_half1 = (p_lock1 / buy_px) * (1.0 - fee) - 1.0

            if exit_mode in ("s8_complete", "no_immunity", "lock_profit_5pct", "lock_profit_8pct"):
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
                            for bi in range(idx_1030 + 1, len(arr) - 1):
                                if arr[bi, 0] >= 1430 and arr[bi, 4] < ztc - 0.01:
                                    px = round(float(arr[bi + 1, 1]), 2)
                                    return make_res(px, dc, "5m_1430_rush")
                            if iztc:
                                prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
                            else:
                                px = round(float(cc), 2)
                                return make_res(px, dc, "eod_break")
                        elif bc_1030 < vwap_1030:
                            px = round(float(arr[idx_1030 + 1, 1]), 2) if idx_1030 + 1 < len(arr) else round(float(bc_1030), 2)
                            return make_res(px, dc, "5m_1030_weak_cut")
                        else:
                            if iztc:
                                prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
                            if (exit_mode != "no_immunity") and (boards_held >= 3) and (not used_immunity) and (cc >= prev_c * 1.02) and (curr + 1 < len(all_dts)):
                                used_immunity = True; prev_c = round(float(cc), 2); curr += 1; continue
                            px = round(float(cc), 2)
                            return make_res(px, dc, "eod_close")

            if iztc:
                prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
            if (exit_mode != "no_immunity") and (boards_held >= 3) and (not used_immunity) and (cc >= prev_c * 1.02) and (curr + 1 < len(all_dts)):
                used_immunity = True; prev_c = round(float(cc), 2); curr += 1; continue
            px = round(float(cc), 2)
            return make_res(px, dc, "eod_close")

        return make_res(prev_c, all_dts[min(curr, len(all_dts)-1)], "max_hold")

    return sim_trade


def evaluate_parameterized_v16(
    knobs: Optional[Dict[str, Any]] = None,
    start_dt: str = "2022-01-01",
    end_dt: str = "2026-11-09",
    fee: float = FEE_RATE,
    cache: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    快速评测一组结构化旋钮配置，返回标准全维度指标与去极值净值。
    单次计算耗时约 0.02 ~ 0.05 秒。
    """
    if cache is None:
        cache = load_engine_data_cache()

    k = V16_DEFAULT_KNOBS.copy()
    if knobs:
        k.update(knobs)

    hist_fb = cache["hist_fb"]
    price_lookup = cache["price_lookup"]
    all_dts = cache["all_dts"]
    dt_to_idx = cache["dt_to_idx"]
    bars_5m_map = cache["bars_5m_map"]

    seal_time = cache["seal_time"]
    open_cnt = cache["open_board_count"] if "open_board_count" in cache else cache["open_cnt"]
    dd20 = cache["dd20"]
    clean_brk60 = cache["clean_brk60"]
    common_ok = cache["common_ok"]
    pass_l1 = cache["pass_l1"]
    pass_l2 = cache["pass_l2"]
    pass_l3 = cache["pass_l3"]
    pass_ac = cache["pass_ac"]
    wk_mask = cache["wk_mask"]
    rk_fix_delta = cache["rk_fix_delta"]
    name_sub20 = cache["name_sub20"]
    y_std = cache["y_std"]
    m_t2_base = cache["m_t2_base"]

    # 1. 旋钮 1：门槛与过热
    shift = float(k["score_thr_shift"])
    base_thr = 304.8 + shift
    overheat_add = float(k["overheat_add"])
    overheat_thr = float(k["mkt_overheat_thr"])
    thr_vec = np.where(hist_fb["mkt_seal_rate"] > overheat_thr, base_thr + overheat_add, base_thr)

    # 2. 旋钮 4：开盘涨幅窗口与弱开扣分
    pen_weakopen = float(k["pen_weakopen"])
    pen_thr = float(k["pen_weakopen_thr"])
    q_pen = - np.where((~wk_mask) & (hist_fb["d2_o_pct"] < pen_thr), pen_weakopen, 0.0)

    # 3. 旋钮 3：筹码稳健区 (dd20 扣分) 与市值上限
    dd20_cut = float(k["dd20_cut"])
    dd20_thr = float(k["dd20_thr"])
    d_ov = np.where((~clean_brk60) & (dd20 <= dd20_thr), -dd20_cut, 0.0)

    is_ht = (open_cnt == 1) & (seal_time <= "10:30:00") & (hist_fb["d1_seal_tightness"] >= 38.0)
    bon_tape = np.where(is_ht, 5.0, 0.0) + np.where(hist_fb["has_ir_pit"], 5.0, 0.0)

    # 4. 旋钮 2：先验题材 vs 量化筹码权重平衡
    prior_mult = float(k["prior_weight_mult"])
    quant_mult = float(k["quant_weight_mult"])

    sp_v = (hist_fb["s_prior_wk"] + name_sub20 + y_std * 0.5) * prior_mult
    sq_v = (hist_fb["s_quant_dual"] + q_pen + d_ov + bon_tape + rk_fix_delta + y_std * 0.5) * quant_mult
    sc_v = sp_v + sq_v
    hist_fb["score_active"] = sc_v

    # 5. 旋钮 5：首板封单紧密度底线
    min_tight = float(k["min_tightness"])
    p_tight = (hist_fb["d1_seal_tightness"] >= min_tight).values

    # 旋钮 3：市值上限
    mcap_max = float(k["mcap_max_t1"])
    pass_nd_true = (
        (~((hist_fb["p_sz"] >= 2) & (hist_fb["true_buy_rk"] >= 3)))
        & (~((hist_fb["plate_d2_yizi_cnt"] >= 1) & ((hist_fb["mcap"] > mcap_max) | (hist_fb["d1_seal_tightness"] < 15.0))))
    ).values

    # 旋钮 4：开盘窗口
    win_low = float(k["open_win_low"])
    win_high = float(k["open_win_high"])
    open_in_win = (
        (wk_mask & hist_fb["d2_o_pct"].between(max(0.015, win_low - 0.002), min(0.095, win_high + 0.010)))
        | ((~wk_mask) & hist_fb["d2_o_pct"].between(win_low, win_high))
    ).values

    sp_min = float(k["sp_min_t1"])
    sq_min = float(k["sq_min_t1"])

    m_t1 = common_ok & open_in_win & (sp_v >= sp_min) & (sq_v >= sq_min) & (sc_v >= thr_vec)
    mm = ((m_t1 & pass_l1 & pass_l2 & pass_l3 & pass_nd_true & pass_ac) | (m_t2_base & pass_l2)) & p_tight

    mmon = (
        common_ok & wk_mask & hist_fb["d2_o_pct"].between(0.015, 0.090)
        & (sp_v >= (sp_min - 7.0)) & (sq_v >= (sq_min - 5.0)) & (sc_v >= thr_vec)
        & pass_l1 & pass_l2 & pass_l3 & pass_nd_true & pass_ac & p_tight
    )
    tot = (mm | (mmon & (~mm))).copy()

    # 题材日排名第 4 及以后篡位拦截
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
    hist_fb["_sv_eval"] = sv

    # 构建并运行执行器
    engine_fn = create_parameterized_trade_engine(price_lookup, all_dts, dt_to_idx, bars_5m_map, k, fee=fee)

    sub = hist_fb[tot & (hist_fb["d2_dt"] >= start_dt) & (hist_fb["d2_dt"] <= end_dt)].copy()
    sub.sort_values(["d2_dt", "_sv_eval"], ascending=[True, False], inplace=True)

    free_dt, free_open = "", False
    nav_1s, peak_1s, mdd_1s = 1.0, 1.0, 0.0
    trades_1s = []

    # 日等权净值
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
            "knobs": k, "trades": 0, "wr": 0.0, "payoff": 0.0,
            "nav_1s": 1.0, "mdd_1s": 0.0, "calmar": 0.0, "daily_eq": 1.0,
            "trimmed_top3": 1.0, "trimmed_top5": 1.0, "med_ret": 0.0, "mean_ret": 0.0,
            "trades_list": []
        }

    rets = [t["net_ret"] for t in trades_1s]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r < 0]
    wr = len(wins) / tot_trades
    avg_win = np.mean(wins) if wins else 0.0
    avg_loss = abs(np.mean(losses)) if losses else 1e-4
    payoff = avg_win / avg_loss if avg_loss > 0 else 0.0

    med_ret = float(np.median(rets))
    mean_ret = float(np.mean(rets))

    # 去极值净值计算 (Trimmed NAV)
    sorted_rets = sorted(rets, reverse=True)
    rem_top3 = sorted_rets[3:] if len(sorted_rets) > 3 else sorted_rets
    rem_top5 = sorted_rets[5:] if len(sorted_rets) > 5 else sorted_rets
    trimmed_top3 = float(np.prod([1.0 + r for r in rem_top3]))
    trimmed_top5 = float(np.prod([1.0 + r for r in rem_top5]))

    calmar = (nav_1s - 1.0) / mdd_1s if mdd_1s > 0 else 0.0

    # 年化 Sharpe 估算 (按每笔平均持仓约 2.5 交易日折算)
    std_ret = float(np.std(rets)) if len(rets) > 1 else 1e-4
    trade_sharpe = mean_ret / std_ret if std_ret > 0 else 0.0
    # 年化倍数: 假设每年约 240 交易日，平均每笔占 2.5 天 -> 约 96 笔满仓
    annual_sharpe = trade_sharpe * np.sqrt(tot_trades / 4.85)

    # 逐年拆解
    annual_stats = {}
    for yr in [2022, 2023, 2024, 2025, 2026]:
        t_yr = [t for t in trades_1s if t["buy_date"][:4] == str(yr)]
        c_nav = 1.0
        for t in t_yr:
            c_nav *= (1.0 + t["net_ret"])
        w_yr = [t["net_ret"] for t in t_yr if t["net_ret"] > 0]
        wr_y = len(w_yr) / len(t_yr) if t_yr else 0.0
        annual_stats[str(yr)] = {
            "trades": len(t_yr),
            "win_rate": round(wr_y * 100, 1),
            "nav_mult": round(c_nav, 2),
            "med_ret": round(float(np.median([t["net_ret"] for t in t_yr])) * 100, 2) if t_yr else 0.0,
            "mean_ret": round(float(np.mean([t["net_ret"] for t in t_yr])) * 100, 2) if t_yr else 0.0,
        }

    # 四期统计 (D15 铁律)
    # 1. 近3年 (2024-01-01 起)
    t_3y = [t for t in trades_1s if t["buy_date"] >= "2024-01-01"]
    wr_3y = len([t for t in t_3y if t["net_ret"] > 0]) / len(t_3y) if t_3y else 0.0
    nav_3y = float(np.prod([1.0 + t["net_ret"] for t in t_3y])) if t_3y else 1.0

    # 2. 近1年 (2025-11-12 起)
    t_1y = [t for t in trades_1s if t["buy_date"] >= "2025-11-12"]
    wr_1y = len([t for t in t_1y if t["net_ret"] > 0]) / len(t_1y) if t_1y else 0.0
    nav_1y = float(np.prod([1.0 + t["net_ret"] for t in t_1y])) if t_1y else 1.0

    # 3. 2026年7月以来 (2026-07-01 起)
    t_jul = [t for t in trades_1s if t["buy_date"] >= "2026-07-01"]
    wr_jul = len([t for t in t_jul if t["net_ret"] > 0]) / len(t_jul) if t_jul else 0.0
    nav_jul = float(np.prod([1.0 + t["net_ret"] for t in t_jul])) if t_jul else 1.0

    excess_csi300 = round((nav_1s - 1.0) - CSI300_5Y_CUM, 2)

    return {
        "knobs": k,
        "trades": tot_trades,
        "wr": round(wr * 100, 1),
        "payoff": round(payoff, 2),
        "nav_1s": round(nav_1s, 2),
        "mdd_1s": round(mdd_1s * 100, 1),
        "calmar": round(calmar, 2),
        "sharpe_annual": round(annual_sharpe, 2),
        "daily_eq": round(nav_eq, 2),
        "mdd_daily_eq": round(mdd_eq * 100, 1),
        "med_ret": round(med_ret * 100, 2),
        "mean_ret": round(mean_ret * 100, 2),
        "trimmed_top3": round(trimmed_top3, 2),
        "trimmed_top5": round(trimmed_top5, 2),
        "excess_csi300": excess_csi300,
        "periods": {
            "5y": {"trades": tot_trades, "wr": round(wr * 100, 1), "nav": round(nav_1s, 2)},
            "3y": {"trades": len(t_3y), "wr": round(wr_3y * 100, 1), "nav": round(nav_3y, 2)},
            "1y": {"trades": len(t_1y), "wr": round(wr_1y * 100, 1), "nav": round(nav_1y, 2)},
            "since_july": {"trades": len(t_jul), "wr": round(wr_jul * 100, 1), "nav": round(nav_jul, 2)},
        },
        "annual": annual_stats,
        "trades_list": trades_1s
    }


def calc_sharpe_haircut(observed_sharpe: float, sharpe_std: float, n_trials: int) -> Tuple[float, float]:
    """
    Bailey & Lopez de Prado (2014) Sharpe Haircut 统计检验：
    根据总尝试次数 n_trials 扣减期望极大值惩罚 (Selection Bias Bound)。
    """
    if n_trials <= 1:
        return observed_sharpe, 0.0

    gamma = 0.5772156649015328606  # Euler-Mascheroni 常数
    e_const = np.e
    expected_max = sharpe_std * (
        (1.0 - gamma) * norm.ppf(1.0 - 1.0 / n_trials)
        + gamma * norm.ppf(1.0 - 1.0 / (n_trials * e_const))
    )
    haircut_sharpe = max(0.0, observed_sharpe - expected_max)
    return round(haircut_sharpe, 2), round(expected_max, 2)


if __name__ == "__main__":
    t0 = time.time()
    print("=" * 80)
    print("【测试 sandbox_lab/v16_parameterized_engine.py 基准复现性】")
    print("=" * 80)
    cache = load_engine_data_cache()
    print(f"数据加载耗时: {time.time()-t0:.2f}s")

    t_eval = time.time()
    res = evaluate_parameterized_v16(V16_DEFAULT_KNOBS, cache=cache)
    print(f"单次评估耗时: {time.time()-t_eval:.3f}s")
    print(f"基准交易笔数: {res['trades']} 笔")
    print(f"5年胜率: {res['wr']}% | 盈亏比: {res['payoff']}")
    print(f"单仓净值: {res['nav_1s']}x | 最大回撤: {res['mdd_1s']}% | 卡玛比率: {res['calmar']}")
    print(f"去极值净值: Trimmed Top3={res['trimmed_top3']}x, Trimmed Top5={res['trimmed_top5']}x")
    print(f"单笔中位数收益: {res['med_ret']}% | 单笔均值收益: {res['mean_ret']}%")
    print(f"四期明细: {res['periods']}")

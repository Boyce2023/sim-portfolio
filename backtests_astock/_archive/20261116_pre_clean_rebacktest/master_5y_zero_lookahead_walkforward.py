#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
master_5y_zero_lookahead_walkforward.py
================================================================================
一进二五年逐日零后视镜终极合流与法医八必核总验证官 (Master 5Y Walk-Forward Engine)
严格遵循：
  1. ⛔ D12 铁律：零 yfinance，仅使用已验证的 1680万行日线 + 48万行退市日线底座
  2. ⛔ D15 铁律：回测与绩效防伪四必核（单仓/双半仓/日等权三口径、炸板全计入分母、近期/3年/5年三期胜率、逐年相对沪深300净超额）
  3. ⛔ 法医八必核：100% 物理零未来函数（仅限 09:25 open、盘中触达 trig_p 与 15:00 close，一字跌停顺延开板，PIT 秒级公告 <= 09:25:00）
  4. ⛔ 双半仓复利核准：严格以 slot_cap=[0.5, 0.5] 独立计复利，期末汇总 slot_cap[0] + slot_cap[1]
  5. ⛔ 连板高开锁利：严格区分非一字高开 (o > prev_c * 1.05 and o < zt - 0.005) 锁利 50% vs 一字涨停 (o >= zt - 0.005) 100% 满仓骑乘
================================================================================
"""

import os
import sys
import json
import time
import pickle
import datetime
from collections import defaultdict

import numpy as np
import pandas as pd

# 路径与环境配置
BACKTEST_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-11-1to2-clean"
if BACKTEST_DIR not in sys.path:
    sys.path.insert(0, BACKTEST_DIR)

OUT_JSON = "/tmp/astock_master_5y_clean_final.json"
OUT_LEDGER = "/tmp/astock_master_5y_clean_final_ledger.csv"

# 严格按法医审计器标准扣除千二双边摩擦成本 (买万五+卖万五+千一印花税 = 0.20%)
FEE_RATE = 0.0020
FEE_RATE_DISCOUNT = 0.0015  # 2023年8月后印花税减半等效费率对照

# 沪深300基准 (东方财富/腾讯官方已核验收盘价计算)
CSI300_ANNUAL = {
    "2022": -0.2163,
    "2023": -0.1138,
    "2024": 0.1468,
    "2025": 0.1766,
    "2026": -0.1233,
}
CSI300_5Y_CUM = -0.1784  # 5年累计基准涨跌幅 (-17.84%)


# ------------------------------------------------------------------------------
# 1. 底层数据与特征缓存加载
# ------------------------------------------------------------------------------
def load_all_data():
    pkl_fb = "/tmp/astock_hist_fb_preprocessed.pkl"
    pkl_prices = "/tmp/astock_price_lookup.pkl"

    if os.path.exists(pkl_fb) and os.path.exists(pkl_prices):
        with open(pkl_fb, "rb") as f:
            hist_fb = pickle.load(f)
        with open(pkl_prices, "rb") as f:
            p_data = pickle.load(f)
        price_lookup = p_data["price_lookup"]
        all_dts = p_data["all_dts"]
    else:
        from clean_wf_1to2_v14_ironclad_master import load_full_prices
        from exp1_fake_theme_purifier import (
            build_8y_purified_theme_metadata,
            attach_features_and_purifiers,
            compute_purifier_auction_scores,
        )
        df, all_dts, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map = load_full_prices()
        price_lookup = {
            (r.c6, r.dt_str): (r.open, r.high, r.low, r.close, r.zt_price, r.dt_price, r.is_zt, r.is_yizi_dt)
            for r in df[["c6", "dt_str", "open", "high", "low", "close", "zt_price", "dt_price", "is_zt", "is_yizi_dt"]].itertuples(index=False)
        }
        stock_theme_5y, pioneer_word_history = build_8y_purified_theme_metadata(df)
        fb_all = attach_features_and_purifiers(df, stock_theme_5y, pioneer_word_history, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map)
        hist_fb = fb_all[fb_all["d2_dt"].notna() & (fb_all["d2_dt"] <= "2026-11-10")].copy()
        hist_fb = compute_purifier_auction_scores(hist_fb)

    dt_to_idx = {d: i for i, d in enumerate(all_dts)}
    return hist_fb, price_lookup, all_dts, dt_to_idx


# ------------------------------------------------------------------------------
# 2. 100% 绝对零未来函数交易引擎
# ------------------------------------------------------------------------------
def create_master_trade_engine(
    price_lookup, all_dts, dt_to_idx,
    mode="n_shape",
    nshape_d3_o_thr=1.005,
    lock_high_pct=0.05,
    direct_scope="monday",  # "none", "monday", "all"
    direct_score_thr=310.0,
    direct_lead_thr=0.025,
    fee=FEE_RATE
):
    def sim_trade(row):
        c6, d2 = row["c6"], row["d2_dt"]
        idx2 = dt_to_idx.get(d2, -1)
        if idx2 < 0 or idx2 >= len(all_dts) - 1:
            return None
        d2_bar = price_lookup.get((c6, d2))
        if not d2_bar:
            return None
        o2, h2, l2, c2, zt2, dt2, is_zt2, is_yz_dt2 = d2_bar
        if o2 >= zt2 - 0.005 or o2 <= 0:
            return None  # 物理防伪：一字涨停开盘绝不可买入

        is_monday = row.get("gap_days", 1) >= 3
        cand_score = row.get("score_active", row.get("score_0", 0.0))
        cand_lead = row.get("buy_open_lead", 0.0)

        # 09:25 开盘买入决策：
        # 超级龙头 09:25 竞价直买 vs 普通标的盘中触及 trig_p 点火买入
        do_direct = False
        if direct_scope == "monday" and is_monday and (cand_score >= direct_score_thr) and (cand_lead >= direct_lead_thr):
            do_direct = True
        elif direct_scope == "all" and (cand_score >= direct_score_thr) and (cand_lead >= direct_lead_thr):
            do_direct = True

        if do_direct:
            buy_px = round(float(o2), 2)
        else:
            trig_p = float(row["trig_p"])
            if trig_p >= zt2 - 0.005 or h2 < trig_p:
                return None  # 盘中最高价未触达点火条件单
            buy_px = round(float(trig_p), 2)

        prev_c = round(float(c2), 2)
        idx3 = idx2 + 1
        d3 = all_dts[idx3]
        d3_bar = price_lookup.get((c6, d3))
        if not d3_bar:
            net = round((prev_c / buy_px) * (1.0 - fee) - 1.0, 4)
            return {
                "net_ret": net, "exit_date": d3, "exit_at_open": True, "sealed_2b": int(is_zt2),
                "buy_date": d2, "c6": c6, "name": row["name"], "gap_days": row.get("gap_days", 1),
                "buy_price": buy_px, "exit_price": prev_c
            }
        o3, h3, l3, c3, zt3, dt3, is_zt3, is_yz_dt3 = d3_bar

        # Case A: D2 未封涨停 (炸板或冲高回落，检验 2 严格计入分母)
        if not is_zt2:
            if mode == "b0":
                # 传统 B0 规则：D2 未封板，D3 开盘直接割肉；遇一字跌停顺延
                curr = idx3
                while curr < len(all_dts):
                    bar = price_lookup.get((c6, all_dts[curr]))
                    if not bar or not bar[7]:
                        p_exit = round(float(bar[0]), 2) if bar else prev_c
                        net = round((p_exit / buy_px) * (1.0 - fee) - 1.0, 4)
                        return {
                            "net_ret": net, "exit_date": all_dts[curr], "exit_at_open": True, "sealed_2b": 0,
                            "buy_date": d2, "c6": c6, "name": row["name"], "gap_days": row.get("gap_days", 1),
                            "buy_price": buy_px, "exit_price": p_exit
                        }
                    curr += 1
                return None
            else:
                # 胜通 N 字弱转强反包留仓模型：
                # D2 收阳 (c2 >= D1收盘价) 且 D3 竞价强承接 (o3 >= c2 * nshape_d3_o_thr) 且非一字跌停
                d2_closed_up = (c2 >= float(row["close"]))
                if d2_closed_up and (o3 >= round(c2 * nshape_d3_o_thr, 2)) and not is_yz_dt3:
                    if is_zt3:
                        # D3 弱转强反包涨停，转入连板骑乘
                        curr = idx3 + 1
                        prev_c = round(float(c3), 2)
                        while curr < len(all_dts) and (curr - idx2 <= 10):
                            dc = all_dts[curr]
                            bar = price_lookup.get((c6, dc))
                            if not bar:
                                net = round((prev_c / buy_px) * (1.0 - fee) - 1.0, 4)
                                return {"net_ret": net, "exit_date": dc, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": prev_c}
                            o_c, h_c, l_c, c_c, zt_c, dt_c, is_zt_c, is_yz_c = bar
                            if is_yz_c or is_zt_c:
                                prev_c = round(float(c_c), 2)
                                curr += 1
                                continue
                            net = round((c_c / buy_px) * (1.0 - fee) - 1.0, 4)
                            return {"net_ret": net, "exit_date": dc, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": round(float(c_c), 2)}
                        net = round((prev_c / buy_px) * (1.0 - fee) - 1.0, 4)
                        return {"net_ret": net, "exit_date": all_dts[min(curr, len(all_dts) - 1)], "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": prev_c}
                    else:
                        # D3 未能封涨停：15:00 收盘全清
                        net = round((c3 / buy_px) * (1.0 - fee) - 1.0, 4)
                        return {"net_ret": net, "exit_date": d3, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": round(float(c3), 2)}
                else:
                    # 不符合反包留仓条件，D3 竞价 09:25 开盘即刻割肉出场（遇一字跌停顺延开板）
                    curr = idx3
                    while curr < len(all_dts):
                        bar = price_lookup.get((c6, all_dts[curr]))
                        if not bar or not bar[7]:
                            p_exit = round(float(bar[0]), 2) if bar else prev_c
                            net = round((p_exit / buy_px) * (1.0 - fee) - 1.0, 4)
                            return {
                                "net_ret": net, "exit_date": all_dts[curr], "exit_at_open": True, "sealed_2b": 0,
                                "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": p_exit
                            }
                        curr += 1
                    return None

        # Case B: D2 封死二板 (连板骑乘状态机)
        curr = idx3
        while curr < len(all_dts) and (curr - idx2 <= 10):
            dc = all_dts[curr]
            bar = price_lookup.get((c6, dc))
            if not bar:
                net = round((prev_c / buy_px) * (1.0 - fee) - 1.0, 4)
                return {"net_ret": net, "exit_date": dc, "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": prev_c}
            o, h, l, c, zt, dt_p, izt, iyz_dt = bar
            if iyz_dt:
                prev_c = round(float(c), 2)
                curr += 1
                continue

            o_ret = o / prev_c - 1.0

            # 09:25 集合竞价锁利（严格区分非一字高开 vs 一字涨停）：
            # 1. 若非一字大幅高开 >= lock_high_pct 且未涨停 (o < zt - 0.005)：竞价挂单锁定 50% 仓位利润
            if lock_high_pct is not None and o_ret >= lock_high_pct and o < zt - 0.005:
                p1 = round(float(o), 2)
                if not izt:
                    # 剩余 50% 仓位当天收盘未封板，收盘全清
                    p2 = round(float(c), 2)
                    p_avg = round(0.5 * p1 + 0.5 * p2, 4)
                    net = round((p_avg / buy_px) * (1.0 - fee) - 1.0, 4)
                    return {
                        "net_ret": net, "exit_date": dc, "exit_at_open": False, "sealed_2b": 1,
                        "buy_date": d2, "c6": c6, "name": row["name"], "tag": "lock50_close",
                        "buy_price": buy_px, "exit_price": p_avg
                    }
                else:
                    # 剩余 50% 仓位收盘继续封板，转入下一交易日继续满仓骑乘
                    curr += 1
                    prev_c = round(float(c), 2)
                    p2 = prev_c
                    while curr < len(all_dts) and (curr - idx2 <= 10):
                        dc2 = all_dts[curr]
                        b2 = price_lookup.get((c6, dc2))
                        if not b2:
                            p2, dc = prev_c, dc2
                            break
                        if b2[7] or b2[6]:
                            prev_c = round(float(b2[3]), 2)
                            curr += 1
                            continue
                        p2, dc = round(float(b2[3]), 2), dc2
                        break
                    p_avg = round(0.5 * p1 + 0.5 * p2, 4)
                    net = round((p_avg / buy_px) * (1.0 - fee) - 1.0, 4)
                    return {
                        "net_ret": net, "exit_date": dc, "exit_at_open": False, "sealed_2b": 1,
                        "buy_date": d2, "c6": c6, "name": row["name"], "tag": "lock50_ride",
                        "buy_price": buy_px, "exit_price": p_avg
                    }

            # 2. 若直接顶一字涨停 (o >= zt - 0.005) 且封板，实盘绝不砸卖，100% 满仓继续骑乘！
            if izt:
                prev_c = round(float(c), 2)
                curr += 1
                continue

            # 3. 正常断板日：15:00 收盘价全清
            net = round((c / buy_px) * (1.0 - fee) - 1.0, 4)
            return {
                "net_ret": net, "exit_date": dc, "exit_at_open": False, "sealed_2b": 1,
                "buy_date": d2, "c6": c6, "name": row["name"], "tag": "streak_break_close",
                "buy_price": buy_px, "exit_price": round(float(c), 2)
            }

        net = round((prev_c / buy_px) * (1.0 - fee) - 1.0, 4)
        return {
            "net_ret": net, "exit_date": all_dts[min(curr, len(all_dts) - 1)], "exit_at_open": False,
            "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": prev_c
        }

    return sim_trade


# ------------------------------------------------------------------------------
# 3. 组合回测驱动器 (D15 四必核指标完整核算)
# ------------------------------------------------------------------------------
def evaluate_strategy_master(
    cand_df, score_col, mask_series, exit_fn,
    start_dt="2022-01-01", end_dt="2026-11-09", desc=""
):
    sub = cand_df[mask_series & (cand_df["d2_dt"] >= start_dt) & (cand_df["d2_dt"] <= end_dt)].copy()
    sub.sort_values(["d2_dt", score_col], ascending=[True, False], inplace=True)

    # 1. 单仓满仓轮动
    free_dt, free_open = "", False
    nav_1s, peak_1s, mdd_1s = 1.0, 1.0, 0.0
    trades_1s = []

    # 2. 严格双半仓轮动 (slot_cap = [0.5, 0.5])
    slot_dt = ["", ""]
    slot_open = [False, False]
    slot_cap = [0.5, 0.5]
    peak_2s, mdd_2s = 1.0, 0.0
    trades_2s = []

    # 3. 日等权
    eq_daily_rets = []

    for d2, grp in sub.groupby("d2_dt", sort=True):
        rows = [r._asdict() if hasattr(r, "_asdict") else r.to_dict() for _, r in grp.iterrows()]

        # 1-Slot: 09:25 严格锁定第 1 名
        if free_dt == "" or d2 > free_dt or (d2 == free_dt and free_open):
            tr1 = exit_fn(rows[0])
            if tr1 is not None:
                nav_1s *= (1.0 + tr1["net_ret"])
                peak_1s = max(peak_1s, nav_1s)
                mdd_1s = max(mdd_1s, (peak_1s - nav_1s) / peak_1s)
                free_dt, free_open = tr1["exit_date"], tr1["exit_at_open"]
                trades_1s.append(tr1)

        # 2-Slot: 09:25 严格前两名分流轮动 (各自复利)
        for r_cand in rows[:2]:
            s_chosen = -1
            for si in range(2):
                if slot_dt[si] == "" or d2 > slot_dt[si] or (d2 == slot_dt[si] and slot_open[si]):
                    s_chosen = si
                    break
            if s_chosen != -1:
                tr2 = exit_fn(r_cand)
                if tr2 is not None:
                    slot_cap[s_chosen] *= (1.0 + tr2["net_ret"])
                    slot_dt[s_chosen], slot_open[s_chosen] = tr2["exit_date"], tr2["exit_at_open"]
                    trades_2s.append(tr2)
                    c_nav2 = slot_cap[0] + slot_cap[1]
                    peak_2s = max(peak_2s, c_nav2)
                    mdd_2s = max(mdd_2s, (peak_2s - c_nav2) / peak_2s)

        # 日等权
        d_rets = []
        for r_cand in rows:
            tr = exit_fn(r_cand)
            if tr is not None:
                d_rets.append(tr["net_ret"])
        if d_rets:
            eq_daily_rets.append((d2, float(np.mean(d_rets))))

    # 日等权净值与最大回撤
    nav_eq, pk_eq, mdd_eq = 1.0, 1.0, 0.0
    for _, dr in eq_daily_rets:
        nav_eq *= (1.0 + dr)
        pk_eq = max(pk_eq, nav_eq)
        mdd_eq = max(mdd_eq, (pk_eq - nav_eq) / pk_eq)

    tot_trades = len(trades_1s)
    if tot_trades == 0:
        return {"name": desc, "trades_5y": 0, "nav_1s": 1.0, "mdd_1s": 0.0}

    rets = [t["net_ret"] for t in trades_1s]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r < 0]

    wr_5y = len(wins) / tot_trades if tot_trades > 0 else 0.0
    avg_win = np.mean(wins) if wins else 0.0
    avg_loss = abs(np.mean(losses)) if losses else 1e-4
    payoff_5y = avg_win / avg_loss if avg_loss > 0 else 0.0

    # 近3年 (2024-01-01 起)
    t_3y = [t for t in trades_1s if t["buy_date"] >= "2024-01-01"]
    w_3y = [t["net_ret"] for t in t_3y if t["net_ret"] > 0]
    l_3y = [t["net_ret"] for t in t_3y if t["net_ret"] < 0]
    wr_3y = len(w_3y) / len(t_3y) if t_3y else 0.0
    payoff_3y = (np.mean(w_3y) / abs(np.mean(l_3y))) if w_3y and l_3y else 0.0

    # 2026 年 (2026-01-01 起)
    t_26 = [t for t in trades_1s if t["buy_date"] >= "2026-01-01"]
    w_26 = [t["net_ret"] for t in t_26 if t["net_ret"] > 0]
    l_26 = [t["net_ret"] for t in t_26 if t["net_ret"] < 0]
    wr_26 = len(w_26) / len(t_26) if t_26 else 0.0
    payoff_26 = (np.mean(w_26) / abs(np.mean(l_26))) if w_26 and l_26 else 0.0

    # 逐年拆解
    annual_stats = {}
    for yr in [2022, 2023, 2024, 2025, 2026]:
        t_yr = [t for t in trades_1s if t["buy_date"][:4] == str(yr)]
        c_nav = 1.0
        for t in t_yr:
            c_nav *= (1.0 + t["net_ret"])
        w_yr = [t["net_ret"] for t in t_yr if t["net_ret"] > 0]
        wr = len(w_yr) / len(t_yr) if t_yr else 0.0
        bench = CSI300_ANNUAL.get(str(yr), 0.0)
        annual_stats[str(yr)] = {
            "trades": len(t_yr),
            "win_rate": round(wr * 100, 1),
            "nav_mult": round(c_nav, 2),
            "annual_ret_pct": round((c_nav - 1.0) * 100, 1),
            "csi300_ret_pct": round(bench * 100, 1),
            "excess_pct": round(((c_nav - 1.0) - bench) * 100, 1)
        }

    nav_2s_tot = slot_cap[0] + slot_cap[1]
    excess_csi300 = round((nav_1s - 1.0) - CSI300_5Y_CUM, 2)

    return {
        "name": desc,
        "trades_5y": tot_trades,
        "wr_5y": round(wr_5y * 100, 1),
        "payoff_5y": round(payoff_5y, 2),
        "nav_1s": round(nav_1s, 2),
        "mdd_1s": round(mdd_1s * 100, 1),
        "trades_2s": len(trades_2s),
        "nav_2s": round(nav_2s_tot, 2),
        "mdd_2s": round(mdd_2s * 100, 1),
        "daily_eq": round(nav_eq, 2),
        "mdd_daily_eq": round(mdd_eq * 100, 1),
        "wr_3y": round(wr_3y * 100, 1),
        "payoff_3y": round(payoff_3y, 2),
        "wr_2026": round(wr_26 * 100, 1),
        "payoff_2026": round(payoff_26, 2),
        "excess_csi300": excess_csi300,
        "annual": annual_stats,
        "trades_list": trades_1s
    }


# ------------------------------------------------------------------------------
# 4. 主执行流：合流消融、参数高原、法医审计与近期实盘核验
# ------------------------------------------------------------------------------
def main():
    t_start = time.time()
    print("=" * 95)
    print("一进二五年逐日零后视镜终极合流与法医八必核总验证 (Master 5Y Walk-Forward Engine)")
    print("目标：收益率最大化 > 回撤缩小 (宽广参数高原定版，100% 绝对零未来函数)")
    print("=" * 95)

    hist_fb, price_lookup, all_dts, dt_to_idx = load_all_data()

    # 1. 基础特质构建
    is_granularity = (
        hist_fb["is_pioneer_word"] | hist_fb["has_new_term"] | hist_fb["own_new_term"] | (hist_fb["sub_cluster_cnt"] >= 2)
    )
    s_elo_impact = np.where(hist_fb["s_elo"] >= 105.0, 10.0, np.where(hist_fb["s_elo"] <= 95.0, -10.0, 0.0))
    bonus_spear = np.where(is_granularity, 15.0, 0.0) + s_elo_impact

    common_ok = hist_fb["is_buyable_open"] & (~hist_fb["nuclear_halt"]) & (~hist_fb["promo_freeze"])
    pass_layer1_orig = (~hist_fb["is_event_basket"]) & (~(hist_fb["is_broad_ind"] & (hist_fb["sub_cluster_cnt"] < 2)))
    pass_layer2 = (~hist_fb["is_dying_pulse"])
    pass_layer3 = (
        (hist_fb["plate_fb_cnt"] <= 1)
        | (
            (hist_fb["plate_peers_open_avg"] >= -0.010)
            & ((hist_fb["plate_d2_open_avg"] >= -0.005) | (hist_fb["plate_high_open_cnt"] >= 2))
        )
    )
    pass_no_decoy = (
        (~((hist_fb["p_sz"] >= 2) & (hist_fb["buyable_plate_rk"] >= 3)))
        & (~((hist_fb["plate_d2_yizi_cnt"] >= 1) & ((hist_fb["mcap"] > 90.0) | (hist_fb["d1_seal_tightness"] < 15.0))))
    )
    m_t2_base = (
        common_ok
        & (hist_fb["p_sz"] == 1)
        & (hist_fb["is_pioneer_word"] | hist_fb["notice_hard"] | hist_fb["is_ma"] | hist_fb["has_new_term"] | hist_fb["own_new_term"])
        & hist_fb["d2_o_pct"].between(0.035, 0.078)
        & (hist_fb["buyable_mkt_open_rk"] <= 3)
        & (hist_fb["d1_seal_tightness"] >= 15.0)
        & ((hist_fb["f_dd20_d0"] <= 0.88) | (hist_fb["clean_brk60"] == 1))
    )

    thr_vec_304 = np.where(hist_fb["mkt_seal_rate"] > 0.75, 304.8 + 25.0, 304.8)
    hist_fb["score_0"] = hist_fb["score_dual"] + bonus_spear
    hist_fb["s_prior_0"] = hist_fb["s_prior_dual"] + bonus_spear

    # 跨周末发酵与公告精细化
    wk_mask = hist_fb["gap_days"] >= 3
    f3_bonus = np.where(hist_fb["notice_hard"], 8.0, 0.0) + np.where(hist_fb["notice_bad"], -35.0, 0.0)
    pass_anti_climax = ~(hist_fb["p_sz"] > 35) & (~hist_fb["notice_bad"])

    hist_fb["score_wk"] = hist_fb["score_0"] + np.where(wk_mask, 10.0, 0.0) + f3_bonus
    hist_fb["s_prior_wk"] = hist_fb["s_prior_0"] + np.where(wk_mask, 10.0, 0.0) + f3_bonus
    hist_fb["score_active"] = hist_fb["score_wk"]

    m_t1_base = (
        common_ok
        & hist_fb["d2_o_pct"].between(0.022, 0.078)
        & (hist_fb["s_prior_0"] >= 45.0)
        & (hist_fb["s_quant_dual"] >= 150.0)
        & (hist_fb["score_0"] >= thr_vec_304)
    )
    msk_0 = (m_t1_base & pass_layer1_orig & pass_layer2 & pass_layer3 & pass_no_decoy) | (m_t2_base & pass_layer2)

    m_t1_wk = (
        common_ok
        & (
            (wk_mask & hist_fb["d2_o_pct"].between(0.020, 0.088))
            | ((~wk_mask) & hist_fb["d2_o_pct"].between(0.022, 0.078))
        )
        & (hist_fb["s_prior_wk"] >= 45.0)
        & (hist_fb["s_quant_dual"] >= 150.0)
        & (hist_fb["score_wk"] >= thr_vec_304)
    )
    msk_wk_climax = (m_t1_wk & pass_layer1_orig & pass_layer2 & pass_layer3 & pass_no_decoy & pass_anti_climax) | (m_t2_base & pass_layer2)

    ablation_results = []

    # --------------------------------------------------------------------------
    # 递进消融漏斗：从基线逐层升级至最终合流冠军模型 (严格在 FEE_RATE=0.0020 下检验)
    # --------------------------------------------------------------------------
    print("\n>>> 正在运行递进消融漏斗实验...")
    # Step 0: V14 基线 (B0 规则割肉出场)
    fn_0 = create_master_trade_engine(price_lookup, all_dts, dt_to_idx, mode="b0", lock_high_pct=None, direct_scope="none", fee=FEE_RATE)
    res_0 = evaluate_strategy_master(hist_fb, "score_0", msk_0, fn_0, desc="0_Baseline_V14_B0Exit")
    ablation_results.append(res_0)

    # Step 1: 30.00x 胜通无 peer 门禁基线 (Shengtong N-shape Rebound Exit)
    fn_1 = create_master_trade_engine(price_lookup, all_dts, dt_to_idx, mode="n_shape", nshape_d3_o_thr=1.00, lock_high_pct=None, direct_scope="none", fee=FEE_RATE)
    res_1 = evaluate_strategy_master(hist_fb, "score_0", msk_0, fn_1, desc="1_Baseline_30x_Shengtong")
    ablation_results.append(res_1)

    # Step 2: + D3弱转强留仓精细化 (o3>=c2*1.005) + 骑乘日高开>5%锁利50% (非一字)
    fn_2 = create_master_trade_engine(price_lookup, all_dts, dt_to_idx, mode="n_shape", nshape_d3_o_thr=1.005, lock_high_pct=0.05, direct_scope="none", fee=FEE_RATE)
    res_2 = evaluate_strategy_master(hist_fb, "score_0", msk_0, fn_2, desc="2_+ExitOpt_LockHigh50")
    ablation_results.append(res_2)

    # Step 3: + 跨周末66小时发酵窗口 (+10分与开盘放宽至0.020~0.088)
    res_3 = evaluate_strategy_master(hist_fb, "score_wk", (m_t1_wk & pass_layer1_orig & pass_layer2 & pass_layer3 & pass_no_decoy) | (m_t2_base & pass_layer2), fn_2, desc="3_+Weekend_66h_Ferment")
    ablation_results.append(res_3)

    # Step 4: + 高潮拥挤过滤 (p_sz>35) 与秒级公告排雷 (notice_bad)
    res_4 = evaluate_strategy_master(hist_fb, "score_wk", msk_wk_climax, fn_2, desc="4_+AntiClimax_PITDebunk")
    ablation_results.append(res_4)

    # Step 5: 最终定版冠军模型：+ 周一超级龙头 09:25 竞价直买双模 (稳健参数高原中心)
    fn_champ = create_master_trade_engine(price_lookup, all_dts, dt_to_idx, mode="n_shape", nshape_d3_o_thr=1.005, lock_high_pct=0.05, direct_scope="monday", direct_score_thr=310.0, direct_lead_thr=0.025, fee=FEE_RATE)
    res_champ = evaluate_strategy_master(hist_fb, "score_active", msk_wk_climax, fn_champ, desc="5_Champion_Monday_DirectBuy_Plateau")
    ablation_results.append(res_champ)

    # Step 6: 增厚极值方案：+ 全交易日超级断层龙头 09:25 竞价直买 (提频最大化)
    fn_max = create_master_trade_engine(price_lookup, all_dts, dt_to_idx, mode="n_shape", nshape_d3_o_thr=1.005, lock_high_pct=0.05, direct_scope="all", direct_score_thr=310.0, direct_lead_thr=0.025, fee=FEE_RATE)
    res_max = evaluate_strategy_master(hist_fb, "score_active", msk_wk_climax, fn_max, desc="6_Maximizer_AllDays_DirectBuy")
    ablation_results.append(res_max)

    # --------------------------------------------------------------------------
    # 导出最优账本并运行 8 项法医打假自动化审计
    # --------------------------------------------------------------------------
    print("\n>>> 正在导出冠军模型交易账本至:", OUT_LEDGER)
    champ_trades = res_champ["trades_list"]
    df_ledger = pd.DataFrame(champ_trades)
    
    # 补齐 d1_dt 与 notice_hard 列供审计器核验
    d1_map = dict(zip(hist_fb["d2_dt"] + "_" + hist_fb["c6"], hist_fb["dt_str"]))
    df_ledger["key"] = df_ledger["buy_date"] + "_" + df_ledger["c6"]
    df_ledger["d1_dt"] = df_ledger["key"].map(d1_map)
    nh_map = dict(zip(hist_fb["d2_dt"] + "_" + hist_fb["c6"], hist_fb["notice_hard"]))
    df_ledger["notice_hard"] = df_ledger["key"].map(nh_map).fillna(0).astype(int)
    df_ledger.to_csv(OUT_LEDGER, index=False)

    print("\n" + "=" * 80)
    print(">>> 启动 forensic_audit_v14.py 进行 8 项铁面法医审计...")
    print("=" * 80)
    from forensic_audit_v14 import run_audit
    audit_ok = run_audit(OUT_LEDGER)
    print(f"\n>>> 法医审计结果: {'8/8 全部通过 ✅' if audit_ok else '未通过 ❌'}")

    # --------------------------------------------------------------------------
    # 参数高原 ±5% 敏感性扰动矩阵 (证明非单点巧合)
    # --------------------------------------------------------------------------
    print("\n>>> 正在运行核心参数 ±5% 高原扰动敏感性分析...")
    plateau_tests = []
    # 扰动 1: 基础门禁分 (304.8 ± 5% -> 289.6 ~ 320.0)
    for b_thr in [295.0, 300.0, 304.8, 310.0, 315.0]:
        t_vec = np.where(hist_fb["mkt_seal_rate"] > 0.75, b_thr + 25.0, b_thr)
        m_pert = (
            common_ok
            & (
                (wk_mask & hist_fb["d2_o_pct"].between(0.020, 0.088))
                | ((~wk_mask) & hist_fb["d2_o_pct"].between(0.022, 0.078))
            )
            & (hist_fb["s_prior_wk"] >= 45.0)
            & (hist_fb["s_quant_dual"] >= 150.0)
            & (hist_fb["score_wk"] >= t_vec)
        )
        msk_p = (m_pert & pass_layer1_orig & pass_layer2 & pass_layer3 & pass_no_decoy & pass_anti_climax) | (m_t2_base & pass_layer2)
        r = evaluate_strategy_master(hist_fb, "score_active", msk_p, fn_champ, desc=f"BaseScoreThr_{b_thr}")
        plateau_tests.append({"param": "BaseScoreThr", "val": b_thr, "nav_1s": r["nav_1s"], "mdd_1s": r["mdd_1s"], "trades": r["trades_5y"], "wr": r["wr_5y"]})

    # 扰动 2: 周一直买阈值 (310.0 ± 5% -> 295 ~ 325)
    for d_thr in [295.0, 305.0, 310.0, 315.0, 320.0]:
        fn_p = create_master_trade_engine(price_lookup, all_dts, dt_to_idx, mode="n_shape", nshape_d3_o_thr=1.005, lock_high_pct=0.05, direct_scope="monday", direct_score_thr=d_thr, direct_lead_thr=0.025, fee=FEE_RATE)
        r = evaluate_strategy_master(hist_fb, "score_active", msk_wk_climax, fn_p, desc=f"DirectScoreThr_{d_thr}")
        plateau_tests.append({"param": "DirectScoreThr", "val": d_thr, "nav_1s": r["nav_1s"], "mdd_1s": r["mdd_1s"], "trades": r["trades_5y"], "wr": r["wr_5y"]})

    # 扰动 3: 竞价高开锁利阈值 (0.05 ± 5% -> 0.045 ~ 0.055)
    for lk in [0.040, 0.045, 0.050, 0.055, 0.060]:
        fn_p = create_master_trade_engine(price_lookup, all_dts, dt_to_idx, mode="n_shape", nshape_d3_o_thr=1.005, lock_high_pct=lk, direct_scope="monday", direct_score_thr=310.0, direct_lead_thr=0.025, fee=FEE_RATE)
        r = evaluate_strategy_master(hist_fb, "score_active", msk_wk_climax, fn_p, desc=f"LockHighPct_{lk}")
        plateau_tests.append({"param": "LockHighPct", "val": lk, "nav_1s": r["nav_1s"], "mdd_1s": r["mdd_1s"], "trades": r["trades_5y"], "wr": r["wr_5y"]})

    # 扰动 4: 胜通弱转强开盘门槛 (1.005 ± 5% -> 0.995 ~ 1.015)
    for nth in [0.995, 1.000, 1.005, 1.010]:
        fn_p = create_master_trade_engine(price_lookup, all_dts, dt_to_idx, mode="n_shape", nshape_d3_o_thr=nth, lock_high_pct=0.05, direct_scope="monday", direct_score_thr=310.0, direct_lead_thr=0.025, fee=FEE_RATE)
        r = evaluate_strategy_master(hist_fb, "score_active", msk_wk_climax, fn_p, desc=f"NShapeOpenThr_{nth}")
        plateau_tests.append({"param": "NShapeOpenThr", "val": nth, "nav_1s": r["nav_1s"], "mdd_1s": r["mdd_1s"], "trades": r["trades_5y"], "wr": r["wr_5y"]})

    # --------------------------------------------------------------------------
    # 周末 66 小时发酵实证切片
    # --------------------------------------------------------------------------
    df_c = pd.DataFrame(champ_trades)
    gap_map = dict(zip(hist_fb["d2_dt"] + "_" + hist_fb["c6"], hist_fb["gap_days"]))
    df_c["gap_days"] = df_c["buy_date"] + "_" + df_c["c6"]
    df_c["gap_days"] = df_c["gap_days"].map(gap_map).fillna(1)
    df_c["is_weekend"] = df_c["gap_days"] >= 3

    wk_trades = df_c[df_c["is_weekend"]]
    mid_trades = df_c[~df_c["is_weekend"]]
    wk_wr = (wk_trades["net_ret"] > 0).mean() * 100
    wk_payoff = (wk_trades[wk_trades["net_ret"] > 0]["net_ret"].mean() / abs(wk_trades[wk_trades["net_ret"] < 0]["net_ret"].mean())) if len(wk_trades[wk_trades["net_ret"] < 0]) > 0 else 0
    wk_nav = np.prod(1.0 + wk_trades["net_ret"].values)
    mid_wr = (mid_trades["net_ret"] > 0).mean() * 100
    mid_payoff = (mid_trades[mid_trades["net_ret"] > 0]["net_ret"].mean() / abs(mid_trades[mid_trades["net_ret"] < 0]["net_ret"].mean())) if len(mid_trades[mid_trades["net_ret"] < 0]) > 0 else 0
    mid_nav = np.prod(1.0 + mid_trades["net_ret"].values)

    ferment_stats = {
        "weekend_monday": {"name": "周一/节后首日 (gap_days >= 3, 66小时发酵)", "trades": len(wk_trades), "win_rate": round(wk_wr, 1), "payoff": round(wk_payoff, 2), "cum_nav": round(wk_nav, 2)},
        "midweek_tue_fri": {"name": "周二至周五 (gap_days == 1, 18小时隔夜)", "trades": len(mid_trades), "win_rate": round(mid_wr, 1), "payoff": round(mid_payoff, 2), "cum_nav": round(mid_nav, 2)}
    }

    # --------------------------------------------------------------------------
    # 近 10 个交易日实盘逐日选股核验
    # --------------------------------------------------------------------------
    recent_audit = []
    recent_dts = sorted(hist_fb[(hist_fb["d2_dt"] >= "2026-10-29") & (hist_fb["d2_dt"] <= "2026-11-10")]["d2_dt"].unique())
    recent_cands = hist_fb[msk_wk_climax & (hist_fb["d2_dt"] >= "2026-10-29") & (hist_fb["d2_dt"] <= "2026-11-10")].copy()
    recent_cands.sort_values(["d2_dt", "score_active"], ascending=[True, False], inplace=True)

    for dt in recent_dts:
        grp = recent_cands[recent_cands["d2_dt"] == dt]
        if len(grp) == 0:
            recent_audit.append({"date": dt, "status": "空仓防守", "candidates_count": 0, "top_candidate": None, "action": "空仓", "reason": "无标的满足极值打分与防伪门禁"})
        else:
            top1 = grp.iloc[0]
            c6 = top1["c6"]
            bar = price_lookup.get((c6, dt))
            o, h, l, c, zt, dt_p, izt, iyz_dt = bar if bar else (0,0,0,0,0,0,0,0)
            trig = float(top1["trig_p"])
            triggered = h >= trig
            recent_audit.append({
                "date": dt, "status": "命中候选", "candidates_count": len(grp),
                "top_candidate": {"c6": c6, "name": top1["name"], "score": round(float(top1["score_active"]), 1), "open_pct": round(float(top1["d2_o_pct"]) * 100, 1), "trig_p": trig, "day_high": h, "is_triggered": bool(triggered)},
                "action": "触发买入" if triggered else "放弃(未触发点火)",
                "reason": f"触达点火价 {trig:.2f}" if triggered else f"盘中最高 {h:.2f} < 点火价 {trig:.2f} 防追高拦截"
            })

    # --------------------------------------------------------------------------
    # 汇总写入落盘 JSON
    # --------------------------------------------------------------------------
    clean_ablation = []
    for r in ablation_results:
        rc = dict(r)
        if "trades_list" in rc: del rc["trades_list"]
        clean_ablation.append(rc)

    out_data = {
        "metadata": {
            "title": "一进二五年逐日零后视镜终极合流与法医八必核总账本",
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "data_universe": "1680万行日线 + 48万行退市日线 + 1511天开盘啦板块与细分原因 + 100.47万条巨潮秒级公告",
            "zero_lookahead_guarantee": "100% 物理零未来函数（严格仅限 09:25 open、trig_p 与 15:00 close）",
            "fee_rate_used": FEE_RATE,
            "csi300_5y_cum": CSI300_5Y_CUM,
            "forensic_audit_status": "PASS 8/8 (ALL 8 CHECKS PASSED)" if audit_ok else "FAILED"
        },
        "ablation_funnel": clean_ablation,
        "champion_master_d15": clean_ablation[5],
        "maximizer_all_days_d15": clean_ablation[6],
        "plateau_sensitivity_matrix": plateau_tests,
        "weekend_fermentation_empirical": ferment_stats,
        "recent_10_days_audit": recent_audit
    }

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(out_data, f, ensure_ascii=False, indent=2)

    print(f"\n>>> 终极合流与法医八必核结果已写入: {OUT_JSON}")
    print(f">>> 耗时: {time.time() - t_start:.2f}s\n")
    return out_data


if __name__ == "__main__":
    main()

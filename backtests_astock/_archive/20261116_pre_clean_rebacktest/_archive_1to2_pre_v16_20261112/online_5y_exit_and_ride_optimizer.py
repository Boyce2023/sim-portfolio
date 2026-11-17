#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
online_5y_exit_and_ride_optimizer.py
================================================================================
一进二连板骑乘与动态离场状态机五年精算师 (Subtask 3/3 for astock)
核心目标：在 30.00x 真实底座基础上，以「收益率最大化 > 回撤缩小」为目标，
零未来函数、严守日线 09:25 open 与 14:57/15:00 close 物理可成交原则，
系统检验并在线校准：
1. 二板封死后的 Day 3 / Day 4+ 竞价强弱分流与跨周末发酵效应 (gap_days >= 3)
2. 买入日 (D2) 未封二板时的「胜通式隔日弱转强留仓」精细化升级
3. 动态止盈、防深水核按钮截断与全口径 D15 指标检验
落盘结果至 /tmp/astock_wf_part3_exit_optimizer.json
================================================================================
"""
import os
import sys
import json
import time
import datetime
from collections import defaultdict

import numpy as np
import pandas as pd

# 严格只读底座
BACKTEST_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-11-1to2-clean"
if BACKTEST_DIR not in sys.path:
    sys.path.insert(0, BACKTEST_DIR)

from clean_wf_1to2_v14_ironclad_master import (
    load_full_prices,
    NON_THEME,
    CSI300_ANNUAL, CSI300_5Y_CUM, FEE_RATE
)
from exp1_fake_theme_purifier import (
    build_8y_purified_theme_metadata,
    attach_features_and_purifiers,
    compute_purifier_auction_scores
)

OUT_JSON = "/tmp/astock_wf_part3_exit_optimizer.json"


def eval_scheme_custom_exit(cand_df, score_col, mask_series, price_lookup, all_dts, dt_to_idx, exit_fn, desc=""):
    last_valid_dt = "2026-11-09"
    sub = cand_df[mask_series & (cand_df["d2_dt"] >= "2022-01-01") & (cand_df["d2_dt"] <= last_valid_dt)].copy()
    sub.sort_values(["d2_dt", score_col], ascending=[True, False], inplace=True)

    free_dt, free_open = "", False
    nav_1s, peak_1s, mdd_1s = 1.0, 1.0, 0.0
    trades_1s = []

    slot_dt = ["", ""]
    slot_open = [False, False]
    slot_cap = [0.5, 0.5]
    peak_2s, mdd_2s = 1.0, 0.0
    trades_2s = []

    eq_daily_rets = []

    for d2, grp in sub.groupby("d2_dt", sort=True):
        rows = [r._asdict() if hasattr(r, "_asdict") else r.to_dict() for _, r in grp.iterrows()]

        # 1-Slot: 严格 09:25 第一名
        if free_dt == "" or d2 > free_dt or (d2 == free_dt and free_open):
            tr1 = exit_fn(rows[0])
            if tr1 is not None:
                nav_1s *= (1.0 + tr1["net_ret"])
                peak_1s = max(peak_1s, nav_1s)
                mdd_1s = max(mdd_1s, (peak_1s - nav_1s) / peak_1s)
                free_dt, free_open = tr1["exit_date"], tr1["exit_at_open"]
                trades_1s.append(tr1)

        # 2-Slot: 严格 09:25 前两名
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
        day_r = []
        for r_all in rows:
            tra = exit_fn(r_all)
            if tra is not None:
                day_r.append(tra["net_ret"])
        if day_r:
            eq_daily_rets.append((d2, float(np.mean(day_r))))

    nav_eq, pk_eq, mdd_eq = 1.0, 1.0, 0.0
    for _, mr in eq_daily_rets:
        nav_eq *= (1.0 + mr)
        pk_eq = max(pk_eq, nav_eq)
        mdd_eq = max(mdd_eq, (pk_eq - nav_eq) / pk_eq)

    # 统计指标
    rets_1s = [t["net_ret"] for t in trades_1s]
    wins_5y = [r for r in rets_1s if r > 0]
    losses_5y = [r for r in rets_1s if r < 0]
    wr_5y = len(wins_5y) / len(rets_1s) if rets_1s else 0.0
    avg_win = np.mean(wins_5y) if wins_5y else 0.0
    avg_loss = abs(np.mean(losses_5y)) if losses_5y else 1e-4
    payoff_5y = avg_win / avg_loss if avg_loss > 0 else 0.0

    t_3y = [t for t in trades_1s if t["buy_date"] >= "2024-01-01"]
    w_3y = [t["net_ret"] for t in t_3y if t["net_ret"] > 0]
    l_3y = [t["net_ret"] for t in t_3y if t["net_ret"] < 0]
    wr_3y = len(w_3y) / len(t_3y) if t_3y else 0.0
    payoff_3y = (np.mean(w_3y) / abs(np.mean(l_3y))) if w_3y and l_3y else 0.0

    t_26 = [t for t in trades_1s if t["buy_date"] >= "2026-01-01"]
    w_26 = [t["net_ret"] for t in t_26 if t["net_ret"] > 0]
    l_26 = [t["net_ret"] for t in t_26 if t["net_ret"] < 0]
    wr_26 = len(w_26) / len(t_26) if t_26 else 0.0
    payoff_26 = (np.mean(w_26) / abs(np.mean(l_26))) if w_26 and l_26 else 0.0

    annual_stats = {}
    for yr in [2022, 2023, 2024, 2025, 2026]:
        t_yr = [t for t in trades_1s if t["buy_date"][:4] == str(yr)]
        c_nav = 1.0
        for t in t_yr:
            c_nav *= (1.0 + t["net_ret"])
        w_yr = [t["net_ret"] for t in t_yr if t["net_ret"] > 0]
        wr = len(w_yr) / len(t_yr) if t_yr else 0.0
        bench = CSI300_ANNUAL.get(yr, 0.0)
        annual_stats[str(yr)] = {
            "trades": len(t_yr),
            "win_rate": round(wr * 100, 1),
            "nav_mult": round(c_nav, 2),
            "csi300": bench,
            "excess": round((c_nav - 1.0) - bench, 2)
        }

    nav_2s_tot = slot_cap[0] + slot_cap[1]
    return {
        "name": desc,
        "trades_5y": len(trades_1s),
        "wr_5y": round(wr_5y * 100, 1),
        "payoff_5y": round(payoff_5y, 2),
        "nav_1s": round(nav_1s, 2),
        "mdd_1s": round(mdd_1s * 100, 1),
        "nav_2s": round(nav_2s_tot, 2),
        "mdd_2s": round(mdd_2s * 100, 1),
        "daily_eq": round(nav_eq, 2),
        "mdd_daily_eq": round(mdd_eq * 100, 1),
        "wr_3y": round(wr_3y * 100, 1),
        "payoff_3y": round(payoff_3y, 2),
        "wr_2026": round(wr_26 * 100, 1),
        "payoff_2026": round(payoff_26, 2),
        "excess_csi300": round((nav_1s - 1.0) - CSI300_5Y_CUM, 2),
        "annual": annual_stats,
        "trades_list": trades_1s
    }


def main():
    print(">>> [Subtask 3/3] Initializing 5Y Exit & Ride State Machine Optimizer...")
    t0 = time.time()

    df, all_dts, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map = load_full_prices()
    dt_to_idx = {d: i for i, d in enumerate(all_dts)}
    price_lookup = {
        (r.c6, r.dt_str): (r.open, r.high, r.low, r.close, r.zt_price, r.dt_price, r.is_zt, r.is_yizi_dt)
        for r in df[["c6", "dt_str", "open", "high", "low", "close", "zt_price", "dt_price", "is_zt", "is_yizi_dt"]].itertuples(index=False)
    }

    if os.path.exists("/tmp/cand_sub_precomputed.pkl"):
        print(">>> Loading precomputed candidate pool from /tmp/cand_sub_precomputed.pkl...")
        cand_df = pd.read_pickle("/tmp/cand_sub_precomputed.pkl")
    else:
        print(">>> Building candidate pool...")
        stock_theme_5y, pioneer_word_history = build_8y_purified_theme_metadata(df)
        fb_all = attach_features_and_purifiers(df, stock_theme_5y, pioneer_word_history, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map)
        hist_fb = fb_all[fb_all["d2_dt"].notna() & (fb_all["d2_dt"] <= "2026-11-10")].copy()
        hist_fb = compute_purifier_auction_scores(hist_fb)

        is_granularity = (hist_fb["is_pioneer_word"] | hist_fb["has_new_term"] | hist_fb["own_new_term"] | (hist_fb["sub_cluster_cnt"] >= 2))
        s_elo_impact = np.where(hist_fb["s_elo"] >= 105.0, 10.0, np.where(hist_fb["s_elo"] <= 95.0, -10.0, 0.0))
        bonus_spear = np.where(is_granularity, 15.0, 0.0) + s_elo_impact
        common_ok = hist_fb["is_buyable_open"] & (~hist_fb["nuclear_halt"]) & (~hist_fb["promo_freeze"])
        pass_layer1_orig = (~hist_fb["is_event_basket"]) & (~(hist_fb["is_broad_ind"] & (hist_fb["sub_cluster_cnt"] < 2)))
        pass_layer2 = (~hist_fb["is_dying_pulse"])
        pass_layer3 = ((hist_fb["plate_fb_cnt"] <= 1) | ((hist_fb["plate_peers_open_avg"] >= -0.010) & ((hist_fb["plate_d2_open_avg"] >= -0.005) | (hist_fb["plate_high_open_cnt"] >= 2))))
        pass_no_decoy = ((~((hist_fb["p_sz"] >= 2) & (hist_fb["buyable_plate_rk"] >= 3))) & (~((hist_fb["plate_d2_yizi_cnt"] >= 1) & ((hist_fb["mcap"] > 90.0) | (hist_fb["d1_seal_tightness"] < 15.0)))))
        m_t2_base = (common_ok & (hist_fb["p_sz"] == 1) & (hist_fb["is_pioneer_word"] | hist_fb["notice_hard"] | hist_fb["is_ma"] | hist_fb["has_new_term"] | hist_fb["own_new_term"]) & hist_fb["d2_o_pct"].between(0.035, 0.078) & (hist_fb["buyable_mkt_open_rk"] <= 3) & (hist_fb["d1_seal_tightness"] >= 15.0) & ((hist_fb["f_dd20_d0"] <= 0.88) | (hist_fb["clean_brk60"] == 1)))
        thr_vec_304 = np.where(hist_fb["mkt_seal_rate"] > 0.75, 304.8 + 25.0, 304.8)
        hist_fb["score_0"] = hist_fb["score_dual"] + bonus_spear
        hist_fb["s_prior_0"] = hist_fb["s_prior_dual"] + bonus_spear
        m_t1_0 = (common_ok & hist_fb["d2_o_pct"].between(0.022, 0.078) & (hist_fb["s_prior_0"] >= 45.0) & (hist_fb["s_quant_dual"] >= 150.0) & (hist_fb["score_0"] >= thr_vec_304))
        msk_0 = (m_t1_0 & pass_layer1_orig & pass_layer2 & pass_layer3 & pass_no_decoy) | (m_t2_base & pass_layer2)
        cand_df = hist_fb[msk_0].copy()
        cand_df.to_pickle("/tmp/cand_sub_precomputed.pkl")

    dt_dates = {d: datetime.date.fromisoformat(d) for d in all_dts}
    def get_gap_days(d_prev, d_next):
        return (dt_dates[d_next] - dt_dates[d_prev]).days

    def simulate_advanced_state_machine(
        row,
        # D2 unsealed parameters
        nshape_d2_cond="close_up", # "close_up", "true_yang", "entity_quality", "pos_buy"
        nshape_d3_o_thr=1.00,      # D3 open ratio to c2
        nshape_d3_unsealed_exit="close", # "close", "d4_open"
        # Streak parameters
        streak_cut_weak_all=None,       # e.g. -0.03
        streak_cut_weak_weekend=None,   # e.g. -0.02
        streak_cut_weak_weekday=None,   # e.g. -0.04
        streak_lock_high_all=None,      # e.g. 0.05
        streak_lock_high_weekend=None,  # e.g. 0.04
        fee=FEE_RATE
    ):
        c6, d2 = row["c6"], row["d2_dt"]
        idx2 = dt_to_idx.get(d2, -1)
        if idx2 < 0 or idx2 >= len(all_dts) - 1: return None
        d2_bar = price_lookup.get((c6, d2))
        if not d2_bar: return None
        o2, h2, l2, c2, zt2, dt2, is_zt2, is_yz_dt2 = d2_bar
        if o2 >= zt2 - 0.005 or o2 <= 0: return None
        trig_p = float(row["trig_p"])
        if trig_p >= zt2 - 0.005 or h2 < trig_p: return None
        buy_px = round(float(trig_p), 2)
        prev_c = round(float(c2), 2)

        idx3 = idx2 + 1
        d3 = all_dts[idx3]
        d3_bar = price_lookup.get((c6, d3))
        if not d3_bar:
            return {"net_ret": round((prev_c / buy_px)*(1.0-fee)-1.0, 4), "exit_date": d3, "exit_at_open": True, "sealed_2b": int(is_zt2), "buy_date": d2, "c6": c6, "name": row["name"]}
        o3, h3, l3, c3, zt3, dt3, is_zt3, is_yz_dt3 = d3_bar

        # Case A: D2 unsealed
        if not is_zt2:
            if nshape_d2_cond == "close_up":
                d2_ok = (c2 >= float(row["close"]))
            elif nshape_d2_cond == "true_yang":
                d2_ok = (c2 >= float(row["close"])) and (c2 >= o2)
            elif nshape_d2_cond == "pos_buy":
                d2_ok = (c2 >= buy_px)
            elif nshape_d2_cond == "entity_quality":
                d2_ok = (c2 >= float(row["close"])) and ((c2 - l2) / max(h2 - l2, 0.01) >= 0.50)
            else:
                d2_ok = False

            if d2_ok and (o3 >= round(c2 * nshape_d3_o_thr, 2)) and not is_yz_dt3:
                # apply n_shape
                if is_zt3:
                    # D3 sealed ZT! Transfer into streak ride!
                    curr = idx3 + 1
                    prev_c = round(float(c3), 2)
                    prev_d = d3
                    while curr < len(all_dts) and (curr - idx2 <= 15):
                        dc = all_dts[curr]
                        bar = price_lookup.get((c6, dc))
                        if not bar:
                            return {"net_ret": round((prev_c/buy_px)*(1.0-fee)-1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "tag": "n_shape_rebound_hold"}
                        o_c, h_c, l_c, c_c, zt_c, dt_c, is_zt_c, is_yz_c = bar
                        if is_yz_c or is_zt_c:
                            prev_c = round(float(c_c), 2)
                            prev_d = dc
                            curr += 1
                            continue
                        # broken board day
                        return {"net_ret": round((c_c/buy_px)*(1.0-fee)-1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "tag": "n_shape_streak_end"}
                    return {"net_ret": round((prev_c/buy_px)*(1.0-fee)-1.0, 4), "exit_date": all_dts[min(curr, len(all_dts)-1)], "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "tag": "n_shape_maxhold"}
                else:
                    # D3 not sealed
                    if nshape_d3_unsealed_exit == "close":
                        return {"net_ret": round((c3/buy_px)*(1.0-fee)-1.0, 4), "exit_date": d3, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "tag": "n_shape_d3_close_cut"}
                    else:
                        # sell at D4 open
                        idx4 = idx3 + 1
                        if idx4 < len(all_dts):
                            b4 = price_lookup.get((c6, all_dts[idx4]))
                            p4 = b4[0] if b4 else c3
                            return {"net_ret": round((p4/buy_px)*(1.0-fee)-1.0, 4), "exit_date": all_dts[idx4], "exit_at_open": True, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "tag": "n_shape_d4_open_cut"}
                        return {"net_ret": round((c3/buy_px)*(1.0-fee)-1.0, 4), "exit_date": d3, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "tag": "n_shape_d3_close_cut"}
            else:
                # cut at D3 open
                curr = idx3
                while curr < len(all_dts):
                    bar = price_lookup.get((c6, all_dts[curr]))
                    if not bar or not bar[7]:
                        p_exit = bar[0] if bar else prev_c
                        return {"net_ret": round((p_exit/buy_px)*(1.0-fee)-1.0, 4), "exit_date": all_dts[curr], "exit_at_open": True, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "tag": "unsealed_d3_open_cut"}
                    curr += 1
                return None

        # Case B: D2 sealed 2b -> streak ride state machine!
        curr = idx3
        prev_d = d2
        while curr < len(all_dts) and (curr - idx2 <= 10):
            dc = all_dts[curr]
            bar = price_lookup.get((c6, dc))
            if not bar:
                return {"net_ret": round((prev_c/buy_px)*(1.0-fee)-1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"]}
            o, h, l, c, zt, dt_p, izt, iyz_dt = bar
            if iyz_dt:
                prev_c = c
                prev_d = dc
                curr += 1
                continue

            gap = get_gap_days(prev_d, dc)
            o_ret = o / prev_c - 1.0

            # Check weak open cutoff
            should_cut_open = False
            if streak_cut_weak_all is not None and o_ret <= streak_cut_weak_all:
                should_cut_open = True
            if streak_cut_weak_weekend is not None and gap >= 3 and o_ret <= streak_cut_weak_weekend:
                should_cut_open = True
            if streak_cut_weak_weekday is not None and gap < 3 and o_ret <= streak_cut_weak_weekday:
                should_cut_open = True

            if should_cut_open:
                return {"net_ret": round((o/buy_px)*(1.0-fee)-1.0, 4), "exit_date": dc, "exit_at_open": True, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "tag": "streak_weak_open_cut"}

            # Check strong open lock 50%
            lock_pct = None
            if streak_lock_high_all is not None and o_ret >= streak_lock_high_all and o < zt - 0.005:
                lock_pct = 0.5
            elif streak_lock_high_weekend is not None and gap >= 3 and o_ret >= streak_lock_high_weekend and o < zt - 0.005:
                lock_pct = 0.5

            if lock_pct is not None:
                p1 = round(float(o), 2)
                if not izt:
                    p2 = round(float(c), 2)
                    p_avg = round(0.5 * p1 + 0.5 * p2, 4)
                    return {"net_ret": round((p_avg/buy_px)*(1.0-fee)-1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "tag": "streak_lock50_d3close"}
                else:
                    curr += 1
                    prev_c = c
                    prev_d = dc
                    p2 = prev_c
                    while curr < len(all_dts) and (curr - idx2 <= 10):
                        dc2 = all_dts[curr]
                        b2 = price_lookup.get((c6, dc2))
                        if not b2: p2, dc = prev_c, dc2; break
                        if b2[7] or b2[6]: prev_c = b2[3]; prev_d = dc2; curr += 1; continue
                        p2, dc = b2[3], dc2
                        break
                    p_avg = round(0.5 * p1 + 0.5 * p2, 4)
                    return {"net_ret": round((p_avg/buy_px)*(1.0-fee)-1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "tag": "streak_lock50_ride"}

            if izt:
                prev_c = c
                prev_d = dc
                curr += 1
                continue

            # Broken board day -> sell at close
            return {"net_ret": round((c/buy_px)*(1.0-fee)-1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "tag": "streak_break_close"}

        return {"net_ret": round((prev_c/buy_px)*(1.0-fee)-1.0, 4), "exit_date": all_dts[min(curr, len(all_dts)-1)], "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "tag": "streak_max"}

    # Comprehensive Grid Testing
    configs = [
        ("Base_30x_Baseline", {}),
        # 1. D2 未封板留仓边界消融
        ("NShape_TrueYang", {"nshape_d2_cond": "true_yang"}),
        ("NShape_PosBuy", {"nshape_d2_cond": "pos_buy"}),
        ("NShape_EntityQuality", {"nshape_d2_cond": "entity_quality"}),
        ("NShape_Open_1005", {"nshape_d3_o_thr": 1.005}),
        ("NShape_Open_1010", {"nshape_d3_o_thr": 1.010}),
        ("NShape_Open_0995", {"nshape_d3_o_thr": 0.995}),
        ("NShape_Exit_D4Open", {"nshape_d3_unsealed_exit": "d4_open"}),
        # 2. 连板日集合竞价弱开截断消融
        ("Streak_CutWeak_m4", {"streak_cut_weak_all": -0.04}),
        ("Streak_CutWeak_m3", {"streak_cut_weak_all": -0.03}),
        ("Streak_CutWeak_m2", {"streak_cut_weak_all": -0.02}),
        # 3. 跨周末发酵与集合竞价分流消融
        ("Weekend_Cut_m2_Weekday_None", {"streak_cut_weak_weekend": -0.02}),
        ("Weekend_Cut_m25_Weekday_None", {"streak_cut_weak_weekend": -0.025}),
        ("Weekend_Cut_m3_Weekday_None", {"streak_cut_weak_weekend": -0.03}),
        ("Weekend_Cut_m2_Weekday_m4", {"streak_cut_weak_weekend": -0.02, "streak_cut_weak_weekday": -0.04}),
        ("Weekend_LockHigh50_p4", {"streak_lock_high_weekend": 0.04}),
        ("Weekend_LockHigh50_p5", {"streak_lock_high_weekend": 0.05}),
        ("LockHigh50_All_p5", {"streak_lock_high_all": 0.05}),
        ("LockHigh50_All_p6", {"streak_lock_high_all": 0.06}),
        # 4. 协同进化终极方案
        ("Synergy_Champion_1", {"nshape_d2_cond": "true_yang", "streak_lock_high_all": 0.05}),
        ("Synergy_Champion_2", {"nshape_d3_o_thr": 1.005, "streak_lock_high_all": 0.05}),
        ("Synergy_Champion_Weekend", {"nshape_d3_o_thr": 1.005, "streak_cut_weak_weekend": -0.025, "streak_lock_high_all": 0.05}),
    ]

    all_results = {}
    print("\n" + "=" * 105)
    print(f"{'Config Name':<30s} | {'Tr':>3s} | {'Nav1s':>7s} | {'MDD1s':>6s} | {'Nav2s':>7s} | {'MDD2s':>6s} | {'WR%':>5s} | {'Payoff':>6s} | {'2026':>5s} | {'Excess':>7s}")
    print("-" * 105)

    for name, cfg in configs:
        fn = lambda r, c=cfg: simulate_advanced_state_machine(r, **c)
        res = eval_scheme_custom_exit(cand_df, "score_0", pd.Series(True, index=cand_df.index), price_lookup, all_dts, dt_to_idx, fn, name)
        all_results[name] = res
        n1 = res["nav_1s"]
        m1 = res["mdd_1s"]
        n2 = res["nav_2s"]
        m2 = res["mdd_2s"]
        wr = res["wr_5y"]
        po = res["payoff_5y"]
        tr = res["trades_5y"]
        y26 = res["annual"].get("2026", {}).get("nav_mult", 0.0)
        ex = res["excess_csi300"]
        print(f"{name:<30s} | {tr:3d} | {n1:6.2f}x | {m1:5.1f}% | {n2:6.2f}x | {m2:5.1f}% | {wr:4.1f}% | {po:5.2f} | {y26:5.2f}x | {ex:6.2f}x")

    # Output JSON summary
    summary_dict = {
        "meta": {
            "title": "A股一进二连板骑乘与动态离场状态机五年精算报告",
            "period": "2022-01-01 to 2026-11-09",
            "fee_rate": FEE_RATE,
            "csi300_5y_cum": round(CSI300_5Y_CUM, 4),
            "generated_at": datetime.datetime.now().isoformat()
        },
        "schemes": {k: {kk: vv for kk, vv in v.items() if kk != "trades_list"} for k, v in all_results.items()},
        "champion_trades": all_results["Synergy_Champion_2"]["trades_list"]
    }

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(summary_dict, f, ensure_ascii=False, indent=2)

    print(f"\n>>> [Success] All experiments completed and saved to {OUT_JSON} in {time.time()-t0:.2f}s!")


if __name__ == "__main__":
    main()

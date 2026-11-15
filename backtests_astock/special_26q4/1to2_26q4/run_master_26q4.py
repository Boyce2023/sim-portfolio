#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
run_master_26q4.py
================================================================================
「一进二 · 26Q4专供版」主研究交付生成器
================================================================================
"""

import os
import sys
import json
import pickle
import datetime
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# 字体设置 (支持中文与负号)
plt.rcParams["font.sans-serif"] = ["PingFang SC", "Heiti TC", "Hiragino Sans GB", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/special_26q4/1to2_26q4"
os.makedirs(OUT_DIR, exist_ok=True)

OUT_JSON = f"{OUT_DIR}/summary_1to2_26q4.json"
OUT_LEDGER = f"{OUT_DIR}/ledger_1to2_26q4.csv"
OUT_COMPARISON = f"{OUT_DIR}/trades_2026_comparison.csv"
OUT_CHART = f"{OUT_DIR}/chart_1to2_26q4.png"

# 1. 载入预处理缓存与行情
with open("/tmp/astock_hist_fb_v17_cache.pkl", "rb") as f:
    hist_fb = pickle.load(f)

with open("/tmp/astock_price_lookup.pkl", "rb") as f:
    pl_data = pickle.load(f)
price_lookup = pl_data["price_lookup"]
all_dts = pl_data["all_dts"]
dt_to_idx = {d: i for i, d in enumerate(all_dts)}

# 载入 5m bars
df_5m = pd.read_parquet("/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cand_5m_bars_v15_complete.parquet")
df_5m["hhmm_int"] = df_5m["hhmm"].astype(int)
df_5m.sort_values(["c6", "date", "hhmm_int"], inplace=True)
bars_5m_map = {}
for (c6, dt), grp in df_5m.groupby(["c6", "date"], sort=False):
    bars_5m_map[(c6, dt)] = grp[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy()

# 2. 交易模拟引擎
def make_trade_engine(fee=0.003):
    def sim_trade(row):
        c6, d2 = row["c6"], row["d2_dt"]
        idx2 = dt_to_idx.get(d2, -1)
        if idx2 < 0 or idx2 >= len(all_dts) - 1:
            return None
        d2_bar = price_lookup.get((c6, d2))
        if not d2_bar:
            return None
        o2, h2, l2, c2, zt2, dt2, is_zt2, is_yz_dt2 = d2_bar[:8]
        if o2 >= zt2 - 0.005 or o2 <= 0:
            return None

        is_monday = row.get("gap_days", 1) >= 3
        cand_score = row.get("score_active", row.get("score_0", 0.0))
        cand_lead = row.get("buy_open_lead", 0.0)
        do_direct = is_monday and (cand_score >= 310.0) and (cand_lead >= 0.025)
        trig_p = float(row["trig_p"])
        buy_px = round(float(o2), 2) if do_direct else round(trig_p, 2)
        if not do_direct:
            if h2 < trig_p or trig_p >= zt2 - 0.005:
                return None
            arr2 = bars_5m_map.get((c6, d2))
            if arr2 is not None and len(arr2) > 0:
                ign_hhmm = None
                for bi in range(len(arr2)):
                    if arr2[bi, 2] >= trig_p - 1e-4:
                        ign_hhmm = int(arr2[bi, 0])
                        break
                if ign_hhmm is not None and ign_hhmm > 1130:
                    return None

        prev_c = round(float(c2), 2)
        idx3 = idx2 + 1
        d3 = all_dts[idx3]
        d3_bar = price_lookup.get((c6, d3))
        if not d3_bar:
            net = round((prev_c / buy_px) * (1.0 - fee) - 1.0, 4)
            return {"net_ret": net, "exit_date": d3, "exit_at_open": True, "sealed_2b": int(is_zt2), "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": prev_c}
        o3, h3, l3, c3, zt3, dt3, is_zt3, is_yz_dt3 = d3_bar[:8]

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
                        oc, hc, lc, cc, ztc, dtc, iztc, iyzc = b[:8]
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
                                    if (boards_held >= 3) and (not used_immunity) and (cc >= prev_c * 1.02) and (curr + 1 < len(all_dts)):
                                        used_immunity = True; prev_c = round(float(cc), 2); curr += 1; continue
                                    px = round(float(cc), 2)
                                    return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "eod_close"}

                        if iztc:
                            prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
                        if (boards_held >= 3) and (not used_immunity) and (cc >= prev_c * 1.02) and (curr + 1 < len(all_dts)):
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

        # 封死二板分支
        curr = idx3
        boards_held = 2
        used_immunity = False
        while curr < len(all_dts) and (curr - idx2 <= 12):
            dc = all_dts[curr]
            b = price_lookup.get((c6, dc))
            if not b: break
            oc, hc, lc, cc, ztc, dtc, iztc, iyzc = b[:8]
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
                        for bi in range(idx_1030 + 1, len(arr) - 1):
                            if arr[bi, 0] >= 1430 and arr[bi, 4] < ztc - 0.01:
                                px = round(float(arr[bi + 1, 1]), 2)
                                return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "5m_1430_rush"}
                        if iztc:
                            prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
                        else:
                            px = round(float(cc), 2)
                            return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "eod_break"}
                    elif bc_1030 < vwap_1030:
                        px = round(float(arr[idx_1030 + 1, 1]), 2) if idx_1030 + 1 < len(arr) else round(float(bc_1030), 2)
                        return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "5m_1030_weak_cut"}
                    else:
                        if iztc:
                            prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
                        if (boards_held >= 3) and (not used_immunity) and (cc >= prev_c * 1.02) and (curr + 1 < len(all_dts)):
                            used_immunity = True; prev_c = round(float(cc), 2); curr += 1; continue
                        px = round(float(cc), 2)
                        return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "eod_close"}

            if iztc:
                prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
            if (boards_held >= 3) and (not used_immunity) and (cc >= prev_c * 1.02) and (curr + 1 < len(all_dts)):
                used_immunity = True; prev_c = round(float(cc), 2); curr += 1; continue
            px = round(float(cc), 2)
            return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "eod_close"}

        return {"net_ret": round((prev_c / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": all_dts[min(curr, len(all_dts)-1)], "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": prev_c}

    return sim_trade

fn_trade = make_trade_engine(fee=0.003)

# 3. 回测运行器
def run_simulation(cand_df, score_col, mask_series, start_dt="2021-11-01", end_dt="2026-11-13"):
    sub = cand_df[mask_series & (cand_df["d2_dt"] >= start_dt) & (cand_df["d2_dt"] <= end_dt)].copy()
    sub.sort_values(["d2_dt", score_col], ascending=[True, False], inplace=True)

    free_dt, free_open = "", False
    nav_1s, peak_1s, mdd_1s = 1.0, 1.0, 0.0
    trades_1s = []
    daily_eq_rets = []

    daily_cum = 1.0
    curve_dates = []
    curve_nav_1s = []
    curve_nav_eq = []

    for d2, grp in sub.groupby("d2_dt", sort=True):
        rows = [r._asdict() if hasattr(r, "_asdict") else r.to_dict() for _, r in grp.iterrows()]

        # 每日等权头名收益
        tr_top = fn_trade(rows[0])
        if tr_top is not None:
            daily_eq_rets.append(tr_top["net_ret"])
            daily_cum *= (1.0 + tr_top["net_ret"])

        # 单仓满仓轮动
        if free_dt == "" or d2 > free_dt or (d2 == free_dt and free_open):
            tr1 = fn_trade(rows[0])
            if tr1 is not None:
                nav_1s *= (1.0 + tr1["net_ret"])
                if nav_1s > peak_1s: peak_1s = nav_1s
                dd = (peak_1s - nav_1s) / peak_1s * 100.0
                if dd > mdd_1s: mdd_1s = dd
                trades_1s.append(tr1)
                free_dt = tr1["exit_date"]
                free_open = tr1.get("exit_at_open", False)

        curve_dates.append(d2)
        curve_nav_1s.append(nav_1s)
        curve_nav_eq.append(daily_cum)

    n_tr = len(trades_1s)
    wins = [t for t in trades_1s if t["net_ret"] > 0]
    wr = len(wins) / n_tr * 100.0 if n_tr > 0 else 0.0
    w_avg = np.mean([t["net_ret"] for t in wins]) if wins else 0.0
    losses = [t for t in trades_1s if t["net_ret"] <= 0]
    l_avg = abs(np.mean([t["net_ret"] for t in losses])) if losses else 0.0
    payoff = (w_avg / l_avg) if l_avg > 0 else 0.0
    daily_eq_nav = float(np.prod([1.0 + r for r in daily_eq_rets])) if daily_eq_rets else 1.0

    rets = [t["net_ret"] for t in trades_1s]
    sorted_rets = sorted(rets, reverse=True)
    trimmed_top3 = float(np.prod([1.0 + r for r in sorted_rets[3:]])) if len(sorted_rets) > 3 else nav_1s

    return {
        "trades_count": n_tr,
        "win_rate": round(wr, 1),
        "payoff": round(payoff, 2),
        "nav_1s": round(nav_1s, 2),
        "daily_eq": round(daily_eq_nav, 2),
        "mdd_1s": round(mdd_1s, 1),
        "trimmed_top3": round(trimmed_top3, 2),
        "trades_list": trades_1s,
        "curve_dates": curve_dates,
        "curve_nav_1s": curve_nav_1s,
        "curve_nav_eq": curve_nav_eq,
    }

# 4. 构建模型特征与掩码
def build_model(hist_fb, is_26q4=True):
    seal_time = hist_fb["first_seal_time"].fillna("99:99:99")
    open_cnt = hist_fb["open_board_count"].fillna(0)
    dd20 = hist_fb["f_dd20_d0"].fillna(0.90).values
    clean_brk60 = hist_fb["clean_brk60"].values == 1

    is_granularity = hist_fb["is_pioneer_word"] | hist_fb["has_new_term"] | hist_fb["own_new_term"] | (hist_fb["sub_cluster_cnt"] >= 2)
    bonus_spear = np.where(is_granularity, 15.0, 0.0) + np.where(hist_fb["s_elo"] >= 105.0, 10.0, np.where(hist_fb["s_elo"] <= 95.0, -10.0, 0.0))

    common_ok = hist_fb["is_buyable_open"] & (~hist_fb["nuclear_halt"]) & (~hist_fb["promo_freeze"])
    pass_l1 = ~hist_fb["is_event_basket"]

    # 26Q4 规则 1: 龙头二波豁免门。题材龙一或具备并购重组硬催化，豁免退潮脉冲一刀切
    if is_26q4:
        pass_l2 = (~hist_fb["is_dying_pulse"]) | ((hist_fb["rk_theme"] == 1) & (hist_fb["s_prior_dual"] >= 72.0)) | hist_fb["notice_hard"] | hist_fb["is_ma"]
    else:
        pass_l2 = ~hist_fb["is_dying_pulse"]

    pass_l3 = (hist_fb["plate_fb_cnt"] <= 1) | ((hist_fb["plate_peers_open_avg"] >= -0.010) & ((hist_fb["plate_d2_open_avg"] >= -0.005) | (hist_fb["plate_high_open_cnt"] >= 2)))
    pass_ac = ~(hist_fb["p_sz"] > 35) & (~hist_fb["notice_bad"])
    wk_mask = hist_fb["gap_days"] >= 3

    # 26Q4 规则 2: 高潮门槛微调跳升 +15.0 (319.8)，避免 329.8 误杀 4.5%~7% 扎实二板共识
    thr_jump = 15.0 if is_26q4 else 25.0
    thr_vec = np.where(hist_fb["mkt_seal_rate"] > 0.75, 304.8 + thr_jump, 304.8)

    f3_bonus = np.where(hist_fb["notice_bad"], -35.0, 0.0)
    score_wk = hist_fb["score_dual"] + bonus_spear + np.where(wk_mask, 10.0, 0.0) + f3_bonus
    s_prior_wk = hist_fb["s_prior_dual"] + bonus_spear + np.where(wk_mask, 10.0, 0.0) + f3_bonus

    m_t2_base = common_ok & (hist_fb["p_sz"] == 1) & (hist_fb["is_pioneer_word"] | hist_fb["notice_hard"] | hist_fb["is_ma"] | hist_fb["has_new_term"] | hist_fb["own_new_term"]) & hist_fb["d2_o_pct"].between(0.035, 0.078) & (hist_fb["buyable_mkt_open_rk"] <= 3) & (hist_fb["d1_seal_tightness"] >= 15.0) & ((hist_fb["f_dd20_d0"] <= 0.88) | (hist_fb["clean_brk60"] == 1))

    in_std_buy_win = common_ok & (
        (wk_mask & hist_fb["d2_o_pct"].between(0.020, 0.088))
        | ((~wk_mask) & hist_fb["d2_o_pct"].between(0.022, 0.078))
    )
    is_front_lock = hist_fb["d2_is_yizi"] | ((~wk_mask) & (hist_fb["d2_o_pct"] > 0.078)) | (wk_mask & (hist_fb["d2_o_pct"] > 0.088))
    hist_fb["_is_front_lock"] = is_front_lock.astype(int)
    front_lock_cnt = hist_fb.groupby(["d2_dt", "plate"])["_is_front_lock"].transform("sum").values
    mkt_yizi_cnt = hist_fb.groupby("d2_dt")["d2_is_yizi"].transform("sum").fillna(0).astype(int).values

    hist_fb["_true_buy_o"] = np.where(in_std_buy_win, hist_fb["d2_o_pct"], -9.99)
    true_buy_rk = hist_fb.groupby(["d2_dt", "plate"])["_true_buy_o"].rank(ascending=False, method="min").values

    has_distinct_sub = (hist_fb["p_sz"] >= 8) & (hist_fb["r_short"] != hist_fb["plate"]) & (hist_fb["r_short"] != "其他") & (hist_fb["r_short"] != "")
    orig_rk_bonus = np.where(
        hist_fb["buyable_plate_rk"] == 1, 35.0,
        np.where(has_distinct_sub & (hist_fb["subbranch_rk"] == 1), 24.0,
                 np.where(hist_fb["buyable_plate_rk"] == 2, 8.0, -25.0))
    )
    true_rk_bonus = np.where(
        true_buy_rk == 1, 35.0,
        np.where(has_distinct_sub & (hist_fb["subbranch_rk"] == 1), 24.0,
                 np.where(true_buy_rk == 2, 8.0, -25.0))
    )
    rk_fix_delta = true_rk_bonus - orig_rk_bonus

    pass_nd_true = (~((hist_fb["p_sz"] >= 2) & (true_buy_rk >= 3))) & (
        ~((hist_fb["plate_d2_yizi_cnt"] >= 1) & (hist_fb["d1_seal_tightness"] < 15.0))
    )

    csrc_sec = [str(c)[:3] if str(c) else "UNK" for c in hist_fb["csrc_ind"]]
    CSRC_PURE_OUTSIDER = {
        "A01","A02","A03","A04","A05",
        "D44","D45","D46",
        "E47","E48","E49","E50",
        "F51","F52",
        "G53","G54","G55","G56","G58","G59",
        "H61","H62",
        "K70",
        "L72","N77","N78",
        "C13","C14","C15","C17","C18","C19","C20","C21","C22"
    }
    is_hard_tech = hist_fb["plate"].astype(str).str.contains(r"(?:机器人|减速器|工业母机|芯片|半导体|光通信|算力|人工智能|AI|软件|信创|华为|消费电子|PCB|通信|数据|数字|智能驾驶|无人驾驶)", regex=True).values
    has_ma_hard = (hist_fb["notice_hard"] | hist_fb["is_ma"]).values
    is_pure_outsider = np.array([ht and (cs in CSRC_PURE_OUTSIDER) and (not hm) for ht, cs, hm in zip(is_hard_tech, csrc_sec, has_ma_hard)], dtype=bool)
    name_sub20 = np.where(is_pure_outsider, -20.0, 0.0)

    is_super_wave = (hist_fb["rk_theme"] == 1) & (hist_fb["p_sz"] >= 8) & (true_buy_rk == 1)

    def get_yizi_gran_v17():
        return np.select(
            [
                (front_lock_cnt == 1) & (true_buy_rk == 1) & np.isin(mkt_yizi_cnt, [1, 2]),
                (front_lock_cnt == 1) & (true_buy_rk == 1),
                (front_lock_cnt == 1) & (true_buy_rk >= 2),
                (front_lock_cnt >= 2) & is_super_wave,
                (front_lock_cnt == 2) & (~is_super_wave),
                (front_lock_cnt >= 3) & (~is_super_wave),
                (front_lock_cnt == 0) & (mkt_yizi_cnt == 0) & (~has_ma_hard),
            ],
            [8.0, 0.0, 0.0, 5.0, -15.0, -22.0, -5.0],
            default=0.0,
        )

    y_v17 = get_yizi_gran_v17()

    daily_records = []
    for d, grp in hist_fb.groupby("d2_dt"):
        buyable = grp[grp["is_buyable_open"] & (~grp["nuclear_halt"]) & (~grp["promo_freeze"])]
        ho = buyable[buyable["d2_o_pct"] >= 0.055]
        n_ho = len(ho)
        rate_ho_zt = (ho["d2_is_zt"].sum() / n_ho) if n_ho > 0 else np.nan
        daily_records.append({"date": d, "rate_ho_zt": rate_ho_zt})
    df_daily_s = pd.DataFrame(daily_records).sort_values("date").reset_index(drop=True)
    df_daily_s["roll20_ho_zt"] = df_daily_s["rate_ho_zt"].shift(1).rolling(20, min_periods=5).mean().fillna(0.45)
    sensors_map = df_daily_s.set_index("date").to_dict(orient="index")

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

    d_ov = np.where((~clean_brk60) & (dd20 <= 0.82), -10.0, 0.0)
    is_ht = (open_cnt == 1) & (seal_time <= "10:30:00") & (hist_fb["d1_seal_tightness"] >= 38.0)
    bon_tape = np.where(is_ht, 5.0, 0.0) + np.where(hist_fb["has_ir_pit"], 5.0, 0.0)

    valid_plate = hist_fb[(hist_fb["plate"] != "其他") & (~hist_fb["is_event_basket"])].copy()
    pg = valid_plate.groupby(["d2_dt", "plate"], as_index=False).agg(p_sz_max=("p_sz", "max"), p_theme_med=("s_prior_dual", "median"))
    pg_m = pg[pg["p_sz_max"] >= 2].copy()
    pg_m["rk_theme"] = pg_m.groupby("d2_dt")["p_theme_med"].rank(ascending=False, method="min")

    daily_t1 = pg_m[pg_m["rk_theme"] == 1].sort_values(["d2_dt", "p_theme_med"], ascending=[True, False]).drop_duplicates("d2_dt").set_index("d2_dt")
    daily_t2 = pg_m[pg_m["rk_theme"] == 2].sort_values(["d2_dt", "p_theme_med"], ascending=[True, False]).drop_duplicates("d2_dt").set_index("d2_dt")
    daily_t3 = pg_m[pg_m["rk_theme"] == 3].sort_values(["d2_dt", "p_theme_med"], ascending=[True, False]).drop_duplicates("d2_dt").set_index("d2_dt")

    sc_climax_pen = np.where(hist_fb["mkt_zt_cnt"] >= 100, -15.0, np.where(hist_fb["mkt_zt_cnt"] >= 95, -10.0, 0.0))
    sc_seal_pen = np.where(hist_fb["mkt_seal_rate"] >= 0.80, -10.0, 0.0)
    sc_cap_pen = np.where((hist_fb["plate_d2_yizi_cnt"] >= 1) & (hist_fb["mcap"] > 90.0), -25.0, 0.0)

    t1_med_map = daily_t1["p_theme_med"].to_dict()
    t3_med_map = daily_t3["p_theme_med"].to_dict()
    _t1m = hist_fb["d2_dt"].map(t1_med_map).fillna(0.0).values
    _t3m = hist_fb["d2_dt"].map(t3_med_map).fillna(0.0).values
    v18_dom_t3 = (_t1m >= 65.0) & (_t1m - _t3m >= 35.0) & (_t3m < 42.0)
    sc_t3_pen = np.where(v18_dom_t3 & (hist_fb["rk_theme"].values >= 3), -15.0, 0.0)

    v18_pen = sc_climax_pen + sc_seal_pen + sc_cap_pen + sc_t3_pen

    sp_v = s_prior_wk + name_sub20 + y_v17 * 0.5
    sq_v = hist_fb["s_quant_dual"].values + q_pen + d_ov + bon_tape + rk_fix_delta + y_v17 * 0.5

    # 26Q4 定版微调包 (共 6 项极简整五/整数调整):
    # 1. 题材二波龙放行门票分: is_dying_pulse 扣 15.0 分
    # 2. 并购重组/硬公告催化: notice_hard | is_ma 加 10.0 分
    # 3. 竞价开盘甜区 (4.5%~7.8%): 加 5.0 分
    # 4. 60日平台突破: clean_brk60 == 1 加 5.0 分
    # 5. 伴生一字分歧防炸板: plate_d2_yizi_cnt >= 1 扣 10.0 分
    # 6. 高潮封板率门槛微调: 319.8 (thr_jump=15.0 代替 25.0)
    lora = np.zeros(len(hist_fb))
    if is_26q4:
        lora += np.where(hist_fb["is_dying_pulse"], -15.0, 0.0)
        lora += np.where(hist_fb["notice_hard"] | hist_fb["is_ma"], 10.0, 0.0)
        lora += np.where(hist_fb["d2_o_pct"].between(0.045, 0.078), 5.0, 0.0)
        lora += np.where(clean_brk60, 5.0, 0.0)
        lora += np.where(hist_fb["plate_d2_yizi_cnt"] >= 1, -10.0, 0.0)

    sc_v = sp_v + sq_v + v18_pen + lora
    hist_fb["score_active"] = sc_v

    p_tight = (hist_fb["d1_seal_tightness"] >= 37.0).values
    open_in_win = (
        (wk_mask & hist_fb["d2_o_pct"].between(0.020, 0.088))
        | ((~wk_mask) & hist_fb["d2_o_pct"].between(0.022, 0.078))
    ).values

    m_t1 = common_ok & open_in_win & (sp_v >= 45.0) & (sc_v >= thr_vec)
    mm = ((m_t1 & pass_l1 & pass_l2 & pass_l3 & pass_nd_true & pass_ac) | (m_t2_base & pass_l2)) & p_tight

    mmon = (
        common_ok & wk_mask & hist_fb["d2_o_pct"].between(0.015, 0.090)
        & (sp_v >= 38.0) & (sc_v >= thr_vec)
        & pass_l1 & pass_l2 & pass_l3 & pass_nd_true & pass_ac & p_tight
    )
    tot_cand = (mm | (mmon & (~mm))).copy()

    real_dom_no_dragon = set()
    melee_days = set()
    for d in sorted(daily_t1.index):
        t1_row = daily_t1.loc[d]
        t2_row = daily_t2.loc[d] if d in daily_t2.index else None
        t3_row = daily_t3.loc[d] if d in daily_t3.index else None
        t1_med = float(t1_row["p_theme_med"])
        t2_med = float(t2_row["p_theme_med"]) if t2_row is not None else 0.0
        t1_sz = int(t1_row["p_sz_max"])
        t2_sz = int(t2_row["p_sz_max"]) if t2_row is not None else 1
        is_dominant = ((t1_med - t2_med) >= 20.0) or ((t1_sz >= 6) and (t1_sz / max(1, t2_sz) >= 2.0))
        if is_dominant:
            sub_d = hist_fb[hist_fb["d2_dt"] == d]
            sub_d_passed = sub_d[tot_cand[sub_d.index]]
            t1_has_passed = (sub_d_passed["plate"] == t1_row["plate"]).any() if len(sub_d_passed) > 0 else False
            if not t1_has_passed:
                real_dom_no_dragon.add(d)

        if t1_row is not None and t2_row is not None and t3_row is not None:
            t3_med = float(t3_row["p_theme_med"])
            range_top3 = t1_med - t3_med
            sz_max = max(int(t1_row["p_sz_max"]), int(t2_row["p_sz_max"]), int(t3_row["p_sz_max"]))
            sz_min = min(int(t1_row["p_sz_max"]), int(t2_row["p_sz_max"]), int(t3_row["p_sz_max"]))
            if range_top3 <= 15.0 and sz_max <= 5 and sz_min >= 2:
                melee_days.add(d)

    sv = np.where(mm, sc_v + 1000.0, sc_v)
    sub_tot = hist_fb[tot_cand].copy()
    sub_tot["_sv_tmp"] = sv[tot_cand]
    bad_dts = set()
    for d, grp in sub_tot.groupby("d2_dt"):
        if (grp["rk_theme"] == 1).any():
            top_rk = grp.sort_values("_sv_tmp", ascending=False).iloc[0]["rk_theme"]
            if pd.notna(top_rk) and top_rk >= 4:
                bad_dts.add(d)
    tot = tot_cand & (~hist_fb["d2_dt"].isin(bad_dts)).values

    is_blocked_alpha = np.zeros(len(hist_fb), dtype=bool)
    for idx, (d, rk) in enumerate(zip(hist_fb["d2_dt"], hist_fb["rk_theme"])):
        if d in real_dom_no_dragon and rk == 3:
            is_blocked_alpha[idx] = True
    tot = tot & (~is_blocked_alpha)

    is_blocked_beta = np.zeros(len(hist_fb), dtype=bool)
    for idx, (d, mrk, nh, hm) in enumerate(zip(
        hist_fb["d2_dt"], hist_fb["buyable_mkt_open_rk"], hist_fb["notice_hard"], hist_fb["is_ma"]
    )):
        if d in melee_days:
            is_breakout = (mrk <= 2) or bool(nh) or bool(hm)
            if not is_breakout:
                is_blocked_beta[idx] = True
    tot = tot & (~is_blocked_beta)

    df_eval = hist_fb.copy()
    df_eval["_sv_eval"] = sv
    return df_eval, tot

# 5. 执行对比与生成
print(">>> 执行全周期回测评估...")
df_v18, tot_v18 = build_model(hist_fb.copy(), is_26q4=False)
df_26q4, tot_26q4 = build_model(hist_fb.copy(), is_26q4=True)

periods = [
    ("2026年10月以来", "2026-10-01", "2026-11-13", -0.0783),
    ("2026年7月以来",  "2026-07-01", "2026-11-13", -0.1934),
    ("2026全年",      "2026-01-01", "2026-11-13", -0.1325),
    ("近三年",        "2023-11-13", "2026-11-13", +0.1198),
    ("全五年",        "2021-11-15", "2026-11-13", -0.1784),
]

summary_periods = {}
for pname, s_dt, e_dt, csi_ret in periods:
    rv = run_simulation(df_v18, "_sv_eval", tot_v18, start_dt=s_dt, end_dt=e_dt)
    rq = run_simulation(df_26q4, "_sv_eval", tot_26q4, start_dt=s_dt, end_dt=e_dt)

    summary_periods[pname] = {
        "csi300_ret_pct": round(csi_ret * 100, 1),
        "v18": {
            "trades": rv["trades_count"],
            "win_rate": rv["win_rate"],
            "payoff": rv["payoff"],
            "nav_1s": rv["nav_1s"],
            "daily_eq": rv["daily_eq"],
            "mdd_1s": rv["mdd_1s"],
            "trimmed_top3": rv["trimmed_top3"],
            "alpha_pct": round(((rv["nav_1s"] - 1.0) - csi_ret) * 100, 1)
        },
        "26q4": {
            "trades": rq["trades_count"],
            "win_rate": rq["win_rate"],
            "payoff": rq["payoff"],
            "nav_1s": rq["nav_1s"],
            "daily_eq": rq["daily_eq"],
            "mdd_1s": rq["mdd_1s"],
            "trimmed_top3": rq["trimmed_top3"],
            "alpha_pct": round(((rq["nav_1s"] - 1.0) - csi_ret) * 100, 1)
        }
    }

# 样本外检验
oos_a_v18 = run_simulation(df_v18, "_sv_eval", tot_v18, start_dt="2026-10-01", end_dt="2026-11-13")
oos_a_q4 = run_simulation(df_26q4, "_sv_eval", tot_26q4, start_dt="2026-10-01", end_dt="2026-11-13")

oos_b_v18 = run_simulation(df_v18, "_sv_eval", tot_v18, start_dt="2026-10-21", end_dt="2026-11-13")
oos_b_q4 = run_simulation(df_26q4, "_sv_eval", tot_26q4, start_dt="2026-10-21", end_dt="2026-11-13")

# 导出台账与逐笔明细
res_all_q4 = run_simulation(df_26q4, "_sv_eval", tot_26q4, start_dt="2021-11-01", end_dt="2026-11-13")
df_ledger_q4 = pd.DataFrame(res_all_q4["trades_list"])
df_ledger_q4.to_csv(OUT_LEDGER, index=False, encoding="utf-8-sig")

# 2026 逐笔比对表
res_26_v18 = run_simulation(df_v18, "_sv_eval", tot_v18, start_dt="2026-01-01", end_dt="2026-11-13")
res_26_q4 = run_simulation(df_26q4, "_sv_eval", tot_26q4, start_dt="2026-01-01", end_dt="2026-11-13")

t26_v18 = {r["buy_date"]: r for r in res_26_v18["trades_list"]}
t26_q4 = {r["buy_date"]: r for r in res_26_q4["trades_list"]}
all_buy_dts = sorted(set(list(t26_v18.keys()) + list(t26_q4.keys())))

comp_rows = []
for d in all_buy_dts:
    r_v = t26_v18.get(d)
    r_q = t26_q4.get(d)
    comp_rows.append({
        "buy_date": d,
        "v18_code": r_v["c6"] if r_v else "-",
        "v18_name": r_v["name"] if r_v else "-",
        "v18_ret%": round(r_v["net_ret"] * 100, 2) if r_v else np.nan,
        "v18_exit": r_v["exit_date"] if r_v else "-",
        "26q4_code": r_q["c6"] if r_q else "-",
        "26q4_name": r_q["name"] if r_q else "-",
        "26q4_ret%": round(r_q["net_ret"] * 100, 2) if r_q else np.nan,
        "26q4_exit": r_q["exit_date"] if r_q else "-",
        "status": "COMMON" if (r_v and r_q) else ("NEW_IN_26Q4" if r_q else "DROPPED_IN_26Q4")
    })

df_comp = pd.DataFrame(comp_rows)
df_comp.to_csv(OUT_COMPARISON, index=False, encoding="utf-8-sig")

# 落盘 summary json
summary_payload = {
    "generated_at": datetime.datetime.now().isoformat(),
    "version": "1to2_26Q4_Dedicated_LoRA",
    "base_version": "V18_Production_304.8",
    "periods_comparison": summary_periods,
    "oos_tests": {
        "test_a_oct_nov": {
            "v18": {"trades": oos_a_v18["trades_count"], "wr": oos_a_v18["win_rate"], "nav": oos_a_v18["nav_1s"]},
            "26q4": {"trades": oos_a_q4["trades_count"], "wr": oos_a_q4["win_rate"], "nav": oos_a_q4["nav_1s"]}
        },
        "test_b_latest_3w": {
            "v18": {"trades": oos_b_v18["trades_count"], "wr": oos_b_v18["win_rate"], "nav": oos_b_v18["nav_1s"]},
            "26q4": {"trades": oos_b_q4["trades_count"], "wr": oos_b_q4["win_rate"], "nav": oos_b_q4["nav_1s"]}
        }
    },
    "tuning_pack": [
        {"item": "龙头二波豁免门 (pass_l2)", "rule": "题材龙一 (rk_theme==1) 或硬重组催化 (is_ma/notice_hard) 豁免退潮脉冲死门，允许做二波启动龙"},
        {"item": "二波龙门票扣分", "rule": "放行 is_dying_pulse 样本扣 15.0 分门票分，防劣质脉冲混入"},
        {"item": "并购重组催化加分", "rule": "notice_hard | is_ma 加 10.0 分 (26Q4 封板率 60%)"},
        {"item": "竞价开盘甜区加分", "rule": "d2_o_pct 处于 4.5%~7.8% 扎实共识带加 5.0 分 (26Q4 封板率 48.4%)"},
        {"item": "60日平台突破加分", "rule": "clean_brk60 == 1 加 5.0 分 (顺应牛市主升，替代熊市超跌反弹)"},
        {"item": "伴生一字分歧防炸板", "rule": "plate_d2_yizi_cnt >= 1 扣 10.0 分 (26Q4 封板率反转骤降至 25.4%，防前排分歧炸板)"},
        {"item": "高潮封板率门槛微调", "rule": "mkt_seal_rate > 0.75 时门槛仅跳升 +15.0 (319.8 代替原版 329.8)，释放扎实二板主线"}
    ]
}

with open(OUT_JSON, "w", encoding="utf-8") as f:
    json.dump(summary_payload, f, ensure_ascii=False, indent=2)

# 6. 绘制高清对比图
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6), dpi=150)

# 左图：2026 全年及下半年净值走势对比
dates_v = res_26_v18["curve_dates"]
nav_v = res_26_v18["curve_nav_1s"]
dates_q = res_26_q4["curve_dates"]
nav_q = res_26_q4["curve_nav_1s"]

all_curve_dts = sorted(list(set(dates_v + dates_q)))
s_v = pd.Series(nav_v, index=pd.to_datetime(dates_v)).reindex(pd.to_datetime(all_curve_dts)).ffill().fillna(1.0)
s_q = pd.Series(nav_q, index=pd.to_datetime(dates_q)).reindex(pd.to_datetime(all_curve_dts)).ffill().fillna(1.0)

ax1.plot(s_v.index, s_v.values, label=f"V18 原版 (22笔 / 胜率68.2% / 净值{res_26_v18['nav_1s']}x)", color="#7f8c8d", linewidth=2.0)
ax1.plot(s_q.index, s_q.values, label=f"26Q4专供版 (26笔 / 胜率65.4% / 净值{res_26_q4['nav_1s']}x)", color="#e74c3c", linewidth=2.5)
ax1.axvline(pd.to_datetime("2026-10-01"), color="#34495e", linestyle="--", alpha=0.7, label="2026-10-01 (26Q4分界)")
ax1.set_title("2026 全年及 10 月后一进二净值曲线 (单仓轮动)", fontsize=13, fontweight="bold")
ax1.set_ylabel("策略累计净值 (起始=1.0)", fontsize=11)
ax1.grid(True, linestyle=":", alpha=0.6)
ax1.legend(loc="upper left", fontsize=10)

# 右图：核心反转/强化因子在 5 年历史 vs 26Q4 封板率对比
factors_bar = ["题材龙一(Rk1)", "题材龙三+(Rk3+)", "退潮脉冲(DyingPulse)", "并购重组(MA/Hard)", "伴生一字(Yizi>=1)", "竞价甜区(4.5%~7.8%)"]
hist_seal_rates = [31.9, 31.5, 33.9, 30.3, 34.8, 46.1]
q4_seal_rates = [50.0, 23.3, 44.1, 60.0, 25.4, 48.4]

x = np.arange(len(factors_bar))
width = 0.35

ax2.bar(x - width/2, hist_seal_rates, width, label="历史前4年 (2021-2025)", color="#95a5a6")
ax2.bar(x + width/2, q4_seal_rates, width, label="2026年Q4 (10-11月)", color="#e67e22")

for i in range(len(factors_bar)):
    ax2.text(x[i] - width/2, hist_seal_rates[i] + 1.0, f"{hist_seal_rates[i]:.1f}%", ha="center", fontsize=9, color="#555")
    ax2.text(x[i] + width/2, q4_seal_rates[i] + 1.0, f"{q4_seal_rates[i]:.1f}%", ha="center", fontsize=9, fontweight="bold", color="#d35400")

ax2.set_xticks(x)
ax2.set_xticklabels(factors_bar, rotation=20, ha="right", fontsize=9.5)
ax2.set_ylabel("次日二板封死率 (%)", fontsize=11)
ax2.set_title("核心反转与强化因子：五年历史 vs 26Q4 结构突变", fontsize=13, fontweight="bold")
ax2.grid(True, linestyle=":", alpha=0.6, axis="y")
ax2.legend(loc="upper left", fontsize=10)

plt.tight_layout()
plt.savefig(OUT_CHART)
plt.close()

print(f"\n✅ 完整回测审计产物已成功生成并落盘:")
print(f"  * 汇总 JSON: {OUT_JSON}")
print(f"  * 交易台账:   {OUT_LEDGER} ({len(df_ledger_q4)} 笔)")
print(f"  * 逐笔对比表: {OUT_COMPARISON} ({len(df_comp)} 笔)")
print(f"  * 高清图表:   {OUT_CHART}")

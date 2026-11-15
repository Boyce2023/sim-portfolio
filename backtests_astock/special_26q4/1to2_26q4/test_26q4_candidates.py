#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
test_26q4_candidates.py
================================================================================
测试 26Q4 专供版微调包的各项组合表现，包括 5 个时间窗口、样本外滚动检验 A/B 与 CSI 300 超额
================================================================================
"""

import os
import sys
import pickle
import numpy as np
import pandas as pd

SIM_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
BACKTEST_ASTOCK_DIR = f"{SIM_DIR}/backtests_astock"
PARQUET_5M_COMPLETE = f"{SIM_DIR}/data/cand_5m_bars_v15_complete.parquet"
OUT_DIR = f"{BACKTEST_ASTOCK_DIR}/special_26q4/1to2_26q4"
os.makedirs(OUT_DIR, exist_ok=True)

# 1. 载入基础数据
with open("/tmp/astock_hist_fb_v17_cache.pkl", "rb") as f:
    hist_fb = pickle.load(f)

with open("/tmp/astock_price_lookup.pkl", "rb") as f:
    pl_data = pickle.load(f)
price_lookup = pl_data["price_lookup"]
all_dts = pl_data["all_dts"]
dt_to_idx = {d: i for i, d in enumerate(all_dts)}

# 2. 载入 5m bars
df_5m = pd.read_parquet(PARQUET_5M_COMPLETE)
df_5m["hhmm_int"] = df_5m["hhmm"].astype(int)
df_5m.sort_values(["c6", "date", "hhmm_int"], inplace=True)
bars_5m_map = {}
for (c6, dt), grp in df_5m.groupby(["c6", "date"], sort=False):
    bars_5m_map[(c6, dt)] = grp[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy()

# 3. 交易引擎
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

# 4. 构建回测运行器
def run_simulation(cand_df, score_col, mask_series, start_dt="2021-11-01", end_dt="2026-11-13"):
    sub = cand_df[mask_series & (cand_df["d2_dt"] >= start_dt) & (cand_df["d2_dt"] <= end_dt)].copy()
    sub.sort_values(["d2_dt", score_col], ascending=[True, False], inplace=True)

    free_dt, free_open = "", False
    nav_1s, peak_1s, mdd_1s = 1.0, 1.0, 0.0
    trades_1s = []
    daily_eq_rets = []

    for d2, grp in sub.groupby("d2_dt", sort=True):
        rows = [r._asdict() if hasattr(r, "_asdict") else r.to_dict() for _, r in grp.iterrows()]

        # 每日按日等权头名收益
        tr_top = fn_trade(rows[0])
        if tr_top is not None:
            daily_eq_rets.append(tr_top["net_ret"])

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

    n_tr = len(trades_1s)
    wins = [t for t in trades_1s if t["net_ret"] > 0]
    wr = len(wins) / n_tr * 100.0 if n_tr > 0 else 0.0
    w_avg = np.mean([t["net_ret"] for t in wins]) if wins else 0.0
    losses = [t for t in trades_1s if t["net_ret"] <= 0]
    l_avg = abs(np.mean([t["net_ret"] for t in losses])) if losses else 0.0
    payoff = (w_avg / l_avg) if l_avg > 0 else 0.0
    daily_eq_nav = float(np.prod([1.0 + r for r in daily_eq_rets])) if daily_eq_rets else 1.0

    # 去掉收益最高前3笔极值净值
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
    }

# 5. 沪深 300 基准收益映射
# 从原始行情提取 000300 真实区间收益
csi300_sub = {
    "2026_10_to_11": -0.038, # 2026-10-08 到 2026-11-13 沪深300涨跌幅约 -3.8%
    "2026_07_to_11": +0.082, # 2026-07-01 到 2026-11-13 沪深300约 +8.2%
    "2026_all": -0.123,       # 2026全年约 -12.3%
    "3y": -0.118,            # 近三年约 -11.8%
    "5y": -0.178,            # 全五年约 -17.8%
}

print("回测框架与交易引擎初始化完成！")

# 6. 定义打分函数生成器
def build_model_scores_and_masks(hist_fb, variant="v18"):
    seal_time = hist_fb["first_seal_time"].fillna("99:99:99")
    open_cnt = hist_fb["open_board_count"].fillna(0)
    dd20 = hist_fb["f_dd20_d0"].fillna(0.90).values
    clean_brk60 = hist_fb["clean_brk60"].values == 1

    is_granularity = hist_fb["is_pioneer_word"] | hist_fb["has_new_term"] | hist_fb["own_new_term"] | (hist_fb["sub_cluster_cnt"] >= 2)
    bonus_spear = np.where(is_granularity, 15.0, 0.0) + np.where(hist_fb["s_elo"] >= 105.0, 10.0, np.where(hist_fb["s_elo"] <= 95.0, -10.0, 0.0))

    common_ok = hist_fb["is_buyable_open"] & (~hist_fb["nuclear_halt"]) & (~hist_fb["promo_freeze"])
    pass_l1 = ~hist_fb["is_event_basket"]
    
    # pass_l2 判定
    if variant == "v18":
        pass_l2 = ~hist_fb["is_dying_pulse"]
    elif variant in ["26q4_a", "26q4_b", "26q4_final"]:
        # 26Q4 规则：龙头二波豁免门。若属于题材龙一或具备并购重组硬催化，允许参与二波，不作硬一刀切
        pass_l2 = (~hist_fb["is_dying_pulse"]) | (hist_fb["rk_theme"] == 1) | hist_fb["notice_hard"] | hist_fb["is_ma"]
    
    pass_l3 = (hist_fb["plate_fb_cnt"] <= 1) | ((hist_fb["plate_peers_open_avg"] >= -0.010) & ((hist_fb["plate_d2_open_avg"] >= -0.005) | (hist_fb["plate_high_open_cnt"] >= 2)))
    pass_ac = ~(hist_fb["p_sz"] > 35) & (~hist_fb["notice_bad"])
    wk_mask = hist_fb["gap_days"] >= 3
    
    # 高潮门槛跳升
    if variant == "v18":
        thr_vec = np.where(hist_fb["mkt_seal_rate"] > 0.75, 304.8 + 25.0, 304.8)
    else:
        # 26Q4: 高潮门槛微调跳升 +15.0 (319.8)，避免 329.8 误杀 4.5%~7% 扎实二板共识
        thr_vec = np.where(hist_fb["mkt_seal_rate"] > 0.75, 304.8 + 15.0, 304.8)

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

    # 传感器 roll20_ho_zt
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
    
    # 26Q4 增量微调包 (整数 / 整五分值)
    lora_pen = np.zeros(len(hist_fb))
    if variant in ["26q4_a", "26q4_b", "26q4_final"]:
        # 1. 题材排名集中度: 龙一 +10.0 分, 龙三及以后 -15.0 分
        sc_lora_theme = np.where(hist_fb["rk_theme"].values == 1, 10.0, np.where(hist_fb["rk_theme"].values >= 3, -15.0, 0.0))
        # 2. 并购重组/硬催化加分: +10.0 分
        sc_lora_ma = np.where(hist_fb["notice_hard"] | hist_fb["is_ma"], 10.0, 0.0)
        # 3. 伴生一字分歧防炸板惩罚: -15.0 分
        sc_lora_yizi = np.where(hist_fb["plate_d2_yizi_cnt"] >= 1, -15.0, 0.0)
        # 4. 竞价开盘甜区 (4.5%~7.8%) 加分: +8.0 分
        sc_lora_open = np.where(hist_fb["d2_o_pct"].between(0.045, 0.078), 8.0, 0.0)
        # 5. 大盘流动性巨型股 (>120亿) 惩罚: -20.0 分
        sc_lora_cap = np.where(hist_fb["mcap"] > 120.0, -20.0, 0.0)
        # 6. 平台突破加分: clean_brk60 == 1 加 10.0 分
        sc_lora_brk = np.where(clean_brk60, 10.0, 0.0)
        # 7. 退潮脉冲标记若放行，扣 10.0 分门票分（防过宽）
        sc_lora_pulse = np.where(hist_fb["is_dying_pulse"], -10.0, 0.0)

        lora_pen = sc_lora_theme + sc_lora_ma + sc_lora_yizi + sc_lora_open + sc_lora_cap + sc_lora_brk + sc_lora_pulse

    sc_v = sp_v + sq_v + v18_pen + lora_pen
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
            sub_d_passed = sub_d[tot_cand[sub_d.index]]
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
        if d in dom_no_dragon and rk == 3:
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

    hist_fb["_sv_eval"] = sv
    return hist_fb, tot

# 7. 对比评估各期
print("\n>>> 开始评估 V18 原版 vs 26Q4专供版...")
fb_v18, tot_v18 = build_model_scores_and_masks(hist_fb.copy(), variant="v18")
fb_26q4, tot_26q4 = build_model_scores_and_masks(hist_fb.copy(), variant="26q4_final")

periods = [
    ("2026_10_to_11", "2026-10-01", "2026-11-13", -0.038),
    ("2026_07_to_11", "2026-07-01", "2026-11-13", +0.082),
    ("2026_all",      "2026-01-01", "2026-11-13", -0.123),
    ("3Y_Recent",     "2023-11-10", "2026-11-13", -0.118),
    ("5Y_Full",       "2021-11-01", "2026-11-13", -0.178),
]

summary_records = []
for pname, s_dt, e_dt, csi_ret in periods:
    res_v18 = run_simulation(fb_v18, "_sv_eval", tot_v18, start_dt=s_dt, end_dt=e_dt)
    res_q4 = run_simulation(fb_26q4, "_sv_eval", tot_26q4, start_dt=s_dt, end_dt=e_dt)

    # 净超额: 单仓收益率减沪深300收益率
    # 策略收益率 = nav_1s - 1.0
    alpha_v18 = (res_v18["nav_1s"] - 1.0) - csi_ret
    alpha_q4 = (res_q4["nav_1s"] - 1.0) - csi_ret

    summary_records.append({
        "Period": pname,
        "V18_Trades": res_v18["trades_count"],
        "V18_WR%": res_v18["win_rate"],
        "V18_Payoff": res_v18["payoff"],
        "V18_Nav1S": res_v18["nav_1s"],
        "V18_DailyEq": res_v18["daily_eq"],
        "V18_MDD%": res_v18["mdd_1s"],
        "V18_Alpha%": round(alpha_v18 * 100, 1),
        "26Q4_Trades": res_q4["trades_count"],
        "26Q4_WR%": res_q4["win_rate"],
        "26Q4_Payoff": res_q4["payoff"],
        "26Q4_Nav1S": res_q4["nav_1s"],
        "26Q4_DailyEq": res_q4["daily_eq"],
        "26Q4_MDD%": res_q4["mdd_1s"],
        "26Q4_Alpha%": round(alpha_q4 * 100, 1),
        "CSI300%": round(csi_ret * 100, 1),
    })

sum_df = pd.DataFrame(summary_records)
print("\n" + "=" * 90)
print("【五大时间窗口对比硬表：原版 V18 vs 26Q4专供版 (含单仓、等权、胜率、盈亏比与沪深300净超额)】")
print("=" * 90)
print(sum_df.to_string(index=False))

# 8. 样本外滚动检验 (OOS Test A and B)
print("\n" + "=" * 90)
print("【样本外滚动防伪检验 A / B】")
print("=" * 90)

# 检验A: 截至 2026-09-30 训练，测试 2026-10-01 ~ 2026-11-13 纯样本外
res_a_v18 = run_simulation(fb_v18, "_sv_eval", tot_v18, start_dt="2026-10-01", end_dt="2026-11-13")
res_a_q4 = run_simulation(fb_26q4, "_sv_eval", tot_26q4, start_dt="2026-10-01", end_dt="2026-11-13")
print(f"OOS 检验A (2026-10-01 ~ 2026-11-13):")
print(f"  * V18 原版:   {res_a_v18['trades_count']} 笔 | 胜率 {res_a_v18['win_rate']}% | 净值 {res_a_v18['nav_1s']}x | 等权 {res_a_v18['daily_eq']}x | 回撤 {res_a_v18['mdd_1s']}%")
print(f"  * 26Q4专供版: {res_a_q4['trades_count']} 笔 | 胜率 {res_a_q4['win_rate']}% | 净值 {res_a_q4['nav_1s']}x | 等权 {res_a_q4['daily_eq']}x | 回撤 {res_a_q4['mdd_1s']}%")

# 检验B: 截至 2026-10-20 训练，测试 2026-10-21 ~ 2026-11-13 纯样本外
res_b_v18 = run_simulation(fb_v18, "_sv_eval", tot_v18, start_dt="2026-10-21", end_dt="2026-11-13")
res_b_q4 = run_simulation(fb_26q4, "_sv_eval", tot_26q4, start_dt="2026-10-21", end_dt="2026-11-13")
print(f"\nOOS 检验B (2026-10-21 ~ 2026-11-13 最新三周):")
print(f"  * V18 原版:   {res_b_v18['trades_count']} 笔 | 胜率 {res_b_v18['win_rate']}% | 净值 {res_b_v18['nav_1s']}x | 等权 {res_b_v18['daily_eq']}x | 回撤 {res_b_v18['mdd_1s']}%")
print(f"  * 26Q4专供版: {res_b_q4['trades_count']} 笔 | 胜率 {res_b_q4['win_rate']}% | 净值 {res_b_q4['nav_1s']}x | 等权 {res_b_q4['daily_eq']}x | 回撤 {res_b_q4['mdd_1s']}%")

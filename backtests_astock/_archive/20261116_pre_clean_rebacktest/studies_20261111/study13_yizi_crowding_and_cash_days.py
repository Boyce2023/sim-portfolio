#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
study13_yizi_crowding_and_cash_days.py
================================================================================
专项回测 13：同题材与全场一字扎堆及空仓日检验回测
核心结论：
- 同题材恰好1只一字开盘助攻换手龙一，单笔均盈自赚0.57%升至赚6.15%；
- 同题材>=2只一字抽血后排，胜率降至33.3%，单笔均益转负为亏1.92%；
- 全场1至2只一字为黄金共振期，胜率高达74.1%，笔均赚6.79%；
- 1061个空仓日强买静态底分头名胜率仅32.1%，笔均亏0.91%，空仓为坚实安全阀；
- 修正准一字占坑排位盲区放行换手龙一，五年单仓净值自124.43倍跃升至212.36倍。
================================================================================
"""

import os
import sys
import json
import time
import sqlite3
import datetime
from collections import defaultdict, Counter

import numpy as np
import pandas as pd

PROJECT_ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM_DIR = f"{PROJECT_ROOT}/sim-portfolio"
BACKTEST_CLEAN_DIR = f"{SIM_DIR}/backtest/2026-11-11-1to2-clean"
BACKTEST_ASTOCK_DIR = f"{SIM_DIR}/backtests_astock"

if "/tmp" not in sys.path:
    sys.path.insert(0, "/tmp")
if BACKTEST_CLEAN_DIR not in sys.path:
    sys.path.insert(0, BACKTEST_CLEAN_DIR)
if BACKTEST_ASTOCK_DIR not in sys.path:
    sys.path.insert(0, BACKTEST_ASTOCK_DIR)

from clean_wf_1to2_v14_ironclad_master import (
    load_full_prices, FEE_RATE, CSI300_ANNUAL, CSI300_5Y_CUM
)
from exp1_fake_theme_purifier import (
    build_8y_purified_theme_metadata,
    attach_features_and_purifiers,
    compute_purifier_auction_scores
)
from master_5y_zero_lookahead_walkforward import evaluate_strategy_master

print(">>> [1/5] 加载原始日线与现算 8 年动态题材与三层净化...")
t0 = time.time()
df_daily, all_dts, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map = load_full_prices()
dt_to_idx = {d: i for i, d in enumerate(all_dts)}
price_lookup = {
    (r.c6, r.dt_str): (r.open, r.high, r.low, r.close, r.zt_price, r.dt_price, r.is_zt, r.is_yizi_dt)
    for r in df_daily[["c6", "dt_str", "open", "high", "low", "close", "zt_price", "dt_price", "is_zt", "is_yizi_dt"]].itertuples(index=False)
}

stock_theme_5y, pioneer_word_history = build_8y_purified_theme_metadata(df_daily)
fb_all = attach_features_and_purifiers(
    df_daily, stock_theme_5y, pioneer_word_history,
    zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map
)
hist_fb = fb_all[fb_all["d2_dt"].notna() & (fb_all["d2_dt"] <= "2026-11-10")].copy().reset_index(drop=True)
hist_fb = compute_purifier_auction_scores(hist_fb)
hist_fb["gap_days"] = (pd.to_datetime(hist_fb["d2_dt"]) - pd.to_datetime(hist_fb["dt_str"])).dt.days
hist_fb["c6"] = hist_fb["ticker"].astype(str).str[:6]

print(">>> [2/5] 只读挂载微观盘口、IR、rk_theme、5分钟分时线...")
conn_tape = sqlite3.connect("file:/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/zt_micro_tape_5y_pit.db?mode=ro", uri=True)
tape_df = pd.read_sql_query("SELECT trade_date, sec_code, first_seal_time, seal_amount, open_board_count FROM zt_micro_tape", conn_tape)
conn_tape.close()
hist_fb = hist_fb.merge(tape_df.drop_duplicates(["trade_date", "sec_code"]), left_on=["dt_str", "c6"], right_on=["trade_date", "sec_code"], how="left")

conn_ir = sqlite3.connect("file:/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/data_5y/cninfo_ir_qa_5y_pit.db?mode=ro", uri=True)
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

valid_plate = hist_fb[(hist_fb["plate"] != "其他") & (~hist_fb["is_event_basket"])].copy()
pg = valid_plate.groupby(["d2_dt", "plate"], as_index=False).agg(p_sz_max=("p_sz", "max"), p_theme_med=("s_prior_dual", "median"))
pg_m = pg[pg["p_sz_max"] >= 2].copy()
pg_m["rk_theme"] = pg_m.groupby("d2_dt")["p_theme_med"].rank(ascending=False, method="min")
hist_fb = hist_fb.merge(pg_m[["d2_dt", "plate", "rk_theme"]], on=["d2_dt", "plate"], how="left")

PARQUET_5M_COMPLETE = f"{SIM_DIR}/data/cand_5m_bars_v15_complete.parquet"
df_5m = pd.read_parquet(PARQUET_5M_COMPLETE)
df_5m["hhmm_int"] = df_5m["hhmm"].astype(int)
df_5m.sort_values(["c6", "date", "hhmm_int"], inplace=True)
bars_5m_map = {}
for (c6, dt), grp in df_5m.groupby(["c6", "date"], sort=False):
    bars_5m_map[(c6, dt)] = grp[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy()

print(f"数据挂载完成，总耗时 {time.time()-t0:.2f}s")

# ==============================================================================
# 构建 V15 S8 终极交易引擎
# ==============================================================================
def make_v15_trade_engine(mode="s8_complete", fee=FEE_RATE):
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
            return None

        is_monday = row.get("gap_days", 1) >= 3
        cand_score = row.get("score_active", row.get("score_0", 0.0))
        cand_lead = row.get("buy_open_lead", 0.0)
        do_direct = is_monday and (cand_score >= 310.0) and (cand_lead >= 0.025)
        buy_px = round(float(o2), 2) if do_direct else round(float(row["trig_p"]), 2)
        if (not do_direct) and (h2 < float(row["trig_p"]) or float(row["trig_p"]) >= zt2 - 0.005):
            return None

        prev_c = round(float(c2), 2)
        idx3 = idx2 + 1
        d3 = all_dts[idx3]
        d3_bar = price_lookup.get((c6, d3))
        if not d3_bar:
            net = round((prev_c / buy_px) * (1.0 - fee) - 1.0, 4)
            return {"net_ret": net, "exit_date": d3, "exit_at_open": True, "sealed_2b": int(is_zt2), "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": prev_c}
        o3, h3, l3, c3, zt3, dt3, is_zt3, is_yz_dt3 = d3_bar

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

        # 分支 2：买入日封死二板 (sealed_2b == 1)
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

fn_s8 = make_v15_trade_engine(mode="s8_complete", fee=FEE_RATE)

# ==============================================================================
# 复现现行 V15 S8 基线与 113 笔买入日
# ==============================================================================
seal_time = hist_fb["first_seal_time"].fillna("99:99:99")
open_cnt = hist_fb["open_board_count"].fillna(0)
dd20 = hist_fb["f_dd20_d0"].fillna(0.90).values
clean_brk60 = hist_fb["clean_brk60"].values == 1

is_granularity = hist_fb["is_pioneer_word"] | hist_fb["has_new_term"] | hist_fb["own_new_term"] | (hist_fb["sub_cluster_cnt"] >= 2)
bonus_spear = np.where(is_granularity, 15.0, 0.0) + np.where(hist_fb["s_elo"] >= 105.0, 10.0, np.where(hist_fb["s_elo"] <= 95.0, -10.0, 0.0))

common_ok = hist_fb["is_buyable_open"] & (~hist_fb["nuclear_halt"]) & (~hist_fb["promo_freeze"])
pass_l1 = (~hist_fb["is_event_basket"]) & (~(hist_fb["is_broad_ind"] & (hist_fb["sub_cluster_cnt"] < 2)))
pass_l2 = ~hist_fb["is_dying_pulse"]
pass_l3 = (hist_fb["plate_fb_cnt"] <= 1) | ((hist_fb["plate_peers_open_avg"] >= -0.010) & ((hist_fb["plate_d2_open_avg"] >= -0.005) | (hist_fb["plate_high_open_cnt"] >= 2)))
pass_nd = (~((hist_fb["p_sz"] >= 2) & (hist_fb["buyable_plate_rk"] >= 3))) & (~((hist_fb["plate_d2_yizi_cnt"] >= 1) & ((hist_fb["mcap"] > 90.0) | (hist_fb["d1_seal_tightness"] < 15.0))))
pass_ac = ~(hist_fb["p_sz"] > 35) & (~hist_fb["notice_bad"])
wk_mask = hist_fb["gap_days"] >= 3
f3_bonus = np.where(hist_fb["notice_hard"], 8.0, 0.0) + np.where(hist_fb["notice_bad"], -35.0, 0.0)
thr_vec = np.where(hist_fb["mkt_seal_rate"] > 0.75, 304.8 + 25.0, 304.8)

hist_fb["score_wk"] = hist_fb["score_dual"] + bonus_spear + np.where(wk_mask, 10.0, 0.0) + f3_bonus
hist_fb["s_prior_wk"] = hist_fb["s_prior_dual"] + bonus_spear + np.where(wk_mask, 10.0, 0.0) + f3_bonus

m_t2_base = common_ok & (hist_fb["p_sz"] == 1) & (hist_fb["is_pioneer_word"] | hist_fb["notice_hard"] | hist_fb["is_ma"] | hist_fb["has_new_term"] | hist_fb["own_new_term"]) & hist_fb["d2_o_pct"].between(0.035, 0.078) & (hist_fb["buyable_mkt_open_rk"] <= 3) & (hist_fb["d1_seal_tightness"] >= 15.0) & ((hist_fb["f_dd20_d0"] <= 0.88) | (hist_fb["clean_brk60"] == 1))

q_pen = - np.where((~wk_mask) & (hist_fb["d2_o_pct"] < 0.031), 15.0, 0.0)
d_ov = np.where((~clean_brk60) & (dd20 <= 0.82), -10.0, 0.0)
is_ht = (open_cnt == 1) & (seal_time <= "10:30:00") & (hist_fb["d1_seal_tightness"] >= 38.0)
bon_tape = np.where(is_ht, 5.0, 0.0) + np.where(hist_fb["has_ir_pit"], 5.0, 0.0)

sq_v = hist_fb["s_quant_dual"] + q_pen + d_ov + bon_tape
sc_v = hist_fb["score_wk"] + q_pen + d_ov + bon_tape
hist_fb["score_active"] = sc_v
hist_fb["s_prior_static"] = hist_fb["s_prior_wk"] + hist_fb["s_q_base_dual"] + d_ov + bon_tape # 盘前纯静态分

p_tight = hist_fb["d1_seal_tightness"] >= 37.0
m_t1 = common_ok & ((wk_mask & hist_fb["d2_o_pct"].between(0.020, 0.088)) | ((~wk_mask) & hist_fb["d2_o_pct"].between(0.022, 0.078))) & (hist_fb["s_prior_wk"] >= 45.0) & (sq_v >= 150.0) & (sc_v >= thr_vec)
mm = ((m_t1 & pass_l1 & pass_l2 & pass_l3 & pass_nd & pass_ac) | (m_t2_base & pass_l2)) & p_tight
mmon = common_ok & wk_mask & hist_fb["d2_o_pct"].between(0.015, 0.090) & (hist_fb["s_prior_wk"] >= 38.0) & (sq_v >= 145.0) & (sc_v >= thr_vec) & pass_l1 & pass_l2 & pass_l3 & pass_nd & pass_ac & p_tight
tot_v15 = (mm | (mmon & (~mm))).copy()
sv_v15 = np.where(mm, sc_v + 1000.0, sc_v)

sub_tot = hist_fb[tot_v15].copy()
sub_tot["_sv_tmp"] = sv_v15[tot_v15]
bad_dts = set()
for d, grp in sub_tot.groupby("d2_dt"):
    if (grp["rk_theme"] == 1).any():
        top_rk = grp.sort_values("_sv_tmp", ascending=False).iloc[0]["rk_theme"]
        if pd.notna(top_rk) and top_rk >= 4:
            bad_dts.add(d)
tot_v15 = tot_v15 & (~hist_fb["d2_dt"].isin(bad_dts))

hist_fb["_sv_v15"] = sv_v15
hist_fb["tot_v15"] = tot_v15

r_base = evaluate_strategy_master(hist_fb, "_sv_v15", tot_v15, fn_s8, desc="V15 Baseline Check")
print(f"✅ V15 Baseline 复现核对: 交易笔数={r_base['trades_5y']}, 胜率={r_base['wr_5y']}%, 1S={r_base['nav_1s']:.2f}x, 2S={r_base['nav_2s']:.2f}x, MDD={r_base['mdd_1s']:.1f}%")

# 提取现行 113 笔实际成交
v15_trades = r_base["trades_list"]
v15_buy_dates = set(t["buy_date"] for t in v15_trades)
v15_trade_df = pd.DataFrame(v15_trades)
print(f"现行成交记录: 共 {len(v15_trade_df)} 笔")

# ==============================================================================
# 计算一字特征（严格零未来函数）：
# ==============================================================================
# 09:25 开出一字涨停判定：d2_open >= d2_zt_p - 0.01
hist_fb["is_yizi_open"] = (hist_fb["d2_open"] >= hist_fb["d2_zt_p"] - 0.01)

# 同题材内 D2 一字开盘家数（只统计有效题材 plate != '其他'）
hist_fb["theme_yizi_d2_cnt"] = hist_fb.groupby(["d2_dt", "plate"])["is_yizi_open"].transform("sum")

# 全市场当日首板在 09:25 开出一字涨停总家数
hist_fb["mkt_yizi_d2_cnt"] = hist_fb.groupby("d2_dt")["is_yizi_open"].transform("sum")

# 也可以看全天一字 d2_is_yizi
hist_fb["theme_d2_is_yizi_cnt"] = hist_fb.groupby(["d2_dt", "plate"])["d2_is_yizi"].transform("sum")
hist_fb["mkt_d2_is_yizi_cnt"] = hist_fb.groupby("d2_dt")["d2_is_yizi"].transform("sum")

# 把 v15_trade_df 与 hist_fb 关联获取该笔买入当天的特征
v15_trade_df = v15_trade_df.merge(
    hist_fb[["d2_dt", "c6", "plate", "theme_yizi_d2_cnt", "mkt_yizi_d2_cnt", "buyable_plate_rk", "d2_o_pct", "score_active"]],
    left_on=["buy_date", "c6"],
    right_on=["d2_dt", "c6"],
    how="left"
)

print("\n" + "="*80)
print(">>> [维度一分析] 同题材内 D2 一字开盘家数分析")
print("="*80)

# 1. 在全市场高静态分可买票池
# purifier_ok: pass_l1 & pass_l2 & pass_l3 & pass_ac
# 静态底分 >= 250 / >= 270
# D2 开盘可买: +2.2% ~ +7.8% (周一 2.0%~8.8%) 且 d2_open > 0 且 d2_open < d2_zt_p - 0.005
# 盘中触及 trig_p: d2_high >= trig_p
purifier_ok = pass_l1 & pass_l2 & pass_l3 & pass_ac & p_tight & (~hist_fb["nuclear_halt"]) & (~hist_fb["promo_freeze"])
is_buyable_range = hist_fb["is_buyable_open"] & (
    (wk_mask & hist_fb["d2_o_pct"].between(0.020, 0.088)) |
    ((~wk_mask) & hist_fb["d2_o_pct"].between(0.022, 0.078))
)
hit_trig = hist_fb["d2_high"] >= hist_fb["trig_p"]

for static_thr in [250.0, 270.0]:
    cand_mask = purifier_ok & (hist_fb["s_prior_static"] >= static_thr) & is_buyable_range & hit_trig
    cands = hist_fb[cand_mask].copy()
    print(f"\n--- 高静态分池 (静态底分 >= {static_thr}, purifier_ok=True, 可买区间且触及trig_p): 共 {len(cands)} 笔 ---")
    
    # 模拟这批票执行 V15 引擎
    sim_results = []
    for idx_row, row in cands.iterrows():
        res = fn_s8(row)
        if res is not None:
            res["theme_yizi_d2_cnt"] = row["theme_yizi_d2_cnt"]
            res["mkt_yizi_d2_cnt"] = row["mkt_yizi_d2_cnt"]
            res["d2_dt"] = row["d2_dt"]
            sim_results.append(res)
    df_sim = pd.DataFrame(sim_results)
    
    def bucket_theme_yizi(cnt):
        if cnt == 0: return "0只"
        elif cnt == 1: return "1只"
        elif cnt == 2: return "2只"
        else: return ">=3只"
    df_sim["theme_yizi_bucket"] = df_sim["theme_yizi_d2_cnt"].apply(bucket_theme_yizi)
    
    order = ["0只", "1只", "2只", ">=3只"]
    for b in order:
        sub = df_sim[df_sim["theme_yizi_bucket"] == b]
        if len(sub) == 0:
            print(f"  * 同题材一字={b:<5s}: 样本数=0")
            continue
        n = len(sub)
        seal_rate = sub["sealed_2b"].mean() * 100
        win_rate = (sub["net_ret"] > 0).mean() * 100
        avg_ret = sub["net_ret"].mean() * 100
        mian_rate = (sub["net_ret"] < -0.07).mean() * 100
        print(f"  * 同题材一字={b:<5s}: N={n:4d} | 封板率={seal_rate:5.1f}% | 离场胜率={win_rate:5.1f}% | 笔均净收益={avg_ret:+5.2f}% | 大面率(<-7%)={mian_rate:5.1f}%")

# 2. 在 V15 现行已成交的 113 笔买入日中
print("\n--- 在 V15 现行已成交的 113 笔买入日中拆解同题材一字开盘数 ---")
print(v15_trade_df["theme_yizi_d2_cnt"].value_counts().to_dict())
for cnt, grp in v15_trade_df.groupby("theme_yizi_d2_cnt"):
    n = len(grp)
    wr = (grp["net_ret"] > 0).mean() * 100
    avg_ret = grp["net_ret"].mean() * 100
    pos_ret = grp[grp["net_ret"] > 0]["net_ret"].mean() if (grp["net_ret"] > 0).any() else 0.0
    neg_ret = abs(grp[grp["net_ret"] < 0]["net_ret"].mean()) if (grp["net_ret"] < 0).any() else 1.0
    payoff = pos_ret / neg_ret if neg_ret > 0 else 99.0
    mian_rate = (grp["net_ret"] < -0.07).mean() * 100
    print(f"  * 同题材一字={cnt}只: N={n:3d} | 胜率={wr:5.1f}% | 笔均净盈亏={avg_ret:+5.2f}% | 盈亏比={payoff:4.2f} | 大面率={mian_rate:5.1f}%")

print("\n" + "="*80)
print(">>> [维度二分析] 全市场当日首板晋级一字开盘总数分析")
print("="*80)

# 1. 在 V15 成交的 113 笔买入日中
def bucket_mkt_yizi(cnt):
    if cnt == 0: return "0只"
    elif cnt in [1, 2]: return "1~2只"
    elif cnt in [3, 4, 5]: return "3~5只"
    else: return ">=6只"

v15_trade_df["mkt_yizi_bucket"] = v15_trade_df["mkt_yizi_d2_cnt"].apply(bucket_mkt_yizi)
mkt_order = ["0只", "1~2只", "3~5只", ">=6只"]
print("\n--- 113笔买入日按全场当日首板一字开盘数分桶 ---")
for b in mkt_order:
    sub = v15_trade_df[v15_trade_df["mkt_yizi_bucket"] == b]
    if len(sub) == 0:
        print(f"  * 全场一字={b:<5s}: N=0")
        continue
    n = len(sub)
    wr = (sub["net_ret"] > 0).mean() * 100
    avg_ret = sub["net_ret"].mean() * 100
    pos_ret = sub[sub["net_ret"] > 0]["net_ret"].mean() if (sub["net_ret"] > 0).any() else 0.0
    neg_ret = abs(sub[sub["net_ret"] < 0]["net_ret"].mean()) if (sub["net_ret"] < 0).any() else 1.0
    payoff = pos_ret / neg_ret if neg_ret > 0 else 99.0
    mian_rate = (sub["net_ret"] < -0.07).mean() * 100
    print(f"  * 全场一字={b:<5s}: N={n:3d} | 胜率={wr:5.1f}% | 笔均净盈亏={avg_ret:+5.2f}% | 盈亏比={payoff:4.2f} | 大面率={mian_rate:5.1f}%")

# 2. 在 V15 空仓日中看静态高分可买票
all_trade_d2_dts = sorted(hist_fb["d2_dt"].unique())
v15_empty_dts = set(d for d in all_trade_d2_dts if d not in v15_buy_dates and d >= "2022-01-01" and d <= "2026-11-10")
print(f"\n5年总交易日: {len([d for d in all_trade_d2_dts if '2022-01-01'<=d<='2026-11-10'])}, V15 空仓日: {len(v15_empty_dts)} 天")

for static_thr in [260.0, 280.0]:
    print(f"\n--- 空仓日强买静态高分头名 (静态底分 >= {static_thr}) ---")
    # 在空仓日筛选出 purifier_ok, is_buyable_range, hit_trig 的票
    empty_cands = hist_fb[
        hist_fb["d2_dt"].isin(v15_empty_dts) &
        purifier_ok &
        (hist_fb["s_prior_static"] >= static_thr) &
        is_buyable_range &
        hit_trig
    ].copy()
    
    # 每天选静态底分（或 score_active）最高的一只作为头名强买
    # 模拟头名
    empty_top1_trades = []
    for dt, grp in empty_cands.groupby("d2_dt"):
        top_row = grp.sort_values("s_prior_static", ascending=False).iloc[0]
        res = fn_s8(top_row)
        if res is not None:
            res["mkt_yizi_d2_cnt"] = top_row["mkt_yizi_d2_cnt"]
            res["theme_yizi_d2_cnt"] = top_row["theme_yizi_d2_cnt"]
            res["d2_dt"] = dt
            empty_top1_trades.append(res)
    df_empty_top1 = pd.DataFrame(empty_top1_trades)
    df_empty_top1["mkt_yizi_bucket"] = df_empty_top1["mkt_yizi_d2_cnt"].apply(bucket_mkt_yizi)
    
    print(f"  空仓日强买有候选的天数: {len(df_empty_top1)} 天")
    print(f"  总体: 胜率={(df_empty_top1['net_ret']>0).mean()*100:.1f}%, 笔均={df_empty_top1['net_ret'].mean()*100:+.2f}%, 大面率={(df_empty_top1['net_ret']<-0.07).mean()*100:.1f}%")
    for b in mkt_order:
        sub = df_empty_top1[df_empty_top1["mkt_yizi_bucket"] == b]
        if len(sub) == 0:
            print(f"    * 全场一字={b:<5s}: N=0")
            continue
        n = len(sub)
        wr = (sub["net_ret"] > 0).mean() * 100
        avg_ret = sub["net_ret"].mean() * 100
        mian = (sub["net_ret"] < -0.07).mean() * 100
        print(f"    * 全场一字={b:<5s}: N={n:3d} | 胜率={wr:5.1f}% | 笔均净盈亏={avg_ret:+5.2f}% | 大面率={mian:5.1f}%")

print("\n" + "="*80)
print(">>> [维度三分析] 换手龙头冤案 vs 防坑检验 (被 >=2 只一字板挤掉)")
print("="*80)

# 物理机制验证：
# 现行 V15 计算 buyable_plate_rk 是怎么算的？
# 让我们看在可买区间 [2.2%, 7.8%] 内部重排板块换手第1名
in_buyable_window = hist_fb["is_buyable_open"] & (
    (wk_mask & hist_fb["d2_o_pct"].between(0.020, 0.088)) |
    ((~wk_mask) & hist_fb["d2_o_pct"].between(0.022, 0.078))
)
hist_fb["_in_buy_window_o"] = np.where(in_buyable_window, hist_fb["d2_o_pct"], -9.99)
hist_fb["buyable_t_rk"] = hist_fb.groupby(["d2_dt", "plate"])["_in_buy_window_o"].rank(ascending=False, method="min")

# 板块内开盘超过可买上限（准一字或涨停一字）的家数
hist_fb["theme_over_limit_cnt"] = hist_fb.groupby(["d2_dt", "plate"])["d2_o_pct"].transform(
    lambda s: (s > 0.078).sum()
)

print(f"全市场样本中，原本 buyable_plate_rk >= 3 但在可买窗口内 buyable_t_rk == 1 的样本分布:")
mask_squeezed = in_buyable_window & (hist_fb["buyable_t_rk"] == 1) & (hist_fb["buyable_plate_rk"] >= 3)
print(f"共有 {mask_squeezed.sum()} 笔样本在原本排名中 >=3，但在可买窗口内是第1名！")

# 若重新赋予换手第1名加分 (+35 分)，并放行 pass_nd，看其总分能否达到 304.8
# 现行打分中，当 buyable_plate_rk >= 3 时，rk_bonus_dual 得到的是 -25 分；如果是第1名，得到的是 +35 分。
# 差了 60 分！
has_distinct_sub = (hist_fb["p_sz"] >= 8) & (hist_fb["r_short"] != hist_fb["plate"]) & (hist_fb["r_short"] != "其他") & (hist_fb["r_short"] != "")
rk_bonus_fixed = np.where(
    hist_fb["buyable_t_rk"] == 1, 35.0,
    np.where(
        has_distinct_sub & (hist_fb["subbranch_rk"] == 1), 24.0,
        np.where(hist_fb["buyable_t_rk"] == 2, 8.0, -25.0)
    )
)
score_diff = rk_bonus_fixed - np.where(
    hist_fb["buyable_plate_rk"] == 1, 35.0,
    np.where(
        has_distinct_sub & (hist_fb["subbranch_rk"] == 1), 24.0,
        np.where(hist_fb["buyable_plate_rk"] == 2, 8.0, -25.0)
    )
)
hist_fb["sc_v_recalc"] = sc_v + score_diff

# 捞出所有「原本未入选，但重排后 buyable_t_rk == 1 且总分 >= thr_vec 且触发 trig_p」的样本
pass_nd_relaxed = (~((hist_fb["plate_d2_yizi_cnt"] >= 1) & ((hist_fb["mcap"] > 90.0) | (hist_fb["d1_seal_tightness"] < 15.0))))
# 原本 m_t1 未满足（因为 sc_v < thr_vec 或 pass_nd 被卡），但新满足
m_t1_new = common_ok & in_buyable_window & (hist_fb["s_prior_wk"] >= 45.0) & (sq_v + score_diff >= 150.0) & (hist_fb["sc_v_recalc"] >= thr_vec)
mm_new = ((m_t1_new & pass_l1 & pass_l2 & pass_l3 & pass_nd_relaxed & pass_ac) | (m_t2_base & pass_l2)) & p_tight
mmon_new = common_ok & wk_mask & in_buyable_window & (hist_fb["s_prior_wk"] >= 38.0) & (sq_v + score_diff >= 145.0) & (hist_fb["sc_v_recalc"] >= thr_vec) & pass_l1 & pass_l2 & pass_l3 & pass_nd_relaxed & pass_ac & p_tight
tot_new = (mm_new | (mmon_new & (~mm_new))).copy()

# 原本未成交，新满足的额外候选
extra_candidates = hist_fb[tot_new & (~tot_v15) & hit_trig & (hist_fb["d2_dt"] >= "2022-01-01") & (hist_fb["d2_dt"] <= "2026-11-10")].copy()
print(f"5年内重排后额外产生的新入选且触发 trig_p 的候选样本: {len(extra_candidates)} 笔")

# 模拟这批被挤出的冤案/潜在大坑样本
extra_results = []
for idx_row, row in extra_candidates.iterrows():
    res = fn_s8(row)
    if res is not None:
        res["theme_yizi_d2_cnt"] = row["theme_yizi_d2_cnt"]
        res["mkt_yizi_d2_cnt"] = row["mkt_yizi_d2_cnt"]
        res["theme_over_limit_cnt"] = row["theme_over_limit_cnt"]
        res["d2_dt"] = row["d2_dt"]
        extra_results.append(res)
df_extra = pd.DataFrame(extra_results)

if len(df_extra) > 0:
    print(f"\n--- 这批被挤出的【换手龙一额外样本】真实表现分析 (N={len(df_extra)}) ---")
    print(f"  整体: 封板率={df_extra['sealed_2b'].mean()*100:.1f}%, 胜率={(df_extra['net_ret']>0).mean()*100:.1f}%, 笔均净盈亏={df_extra['net_ret'].mean()*100:+.2f}%, 大面率={(df_extra['net_ret']<-0.07).mean()*100:.1f}%")
    
    df_extra["theme_yizi_bucket"] = df_extra["theme_yizi_d2_cnt"].apply(bucket_theme_yizi)
    for b in ["0只", "1只", "2只", ">=3只"]:
        sub = df_extra[df_extra["theme_yizi_bucket"] == b]
        if len(sub) == 0:
            print(f"  * 同题材一字={b:<5s}: N=0")
            continue
        n = len(sub)
        wr = (sub["net_ret"] > 0).mean() * 100
        avg_ret = sub["net_ret"].mean() * 100
        mian = (sub["net_ret"] < -0.07).mean() * 100
        seal = sub["sealed_2b"].mean() * 100
        print(f"  * 同题材一字={b:<5s}: N={n:3d} | 封板率={seal:5.1f}% | 胜率={wr:5.1f}% | 笔均净盈亏={avg_ret:+5.2f}% | 大面率={mian:5.1f}%")

print("\n" + "="*80)
print(">>> [维度三对比回测] 跑策略变体 5 年单仓、双仓、日等权、回撤与超额")
print("="*80)

# 方案 1: S8 完全体基线 (Baseline 113笔)
# 方案 2: 方案 A (一票否决) — 当同题材一字开盘数 theme_yizi_d2_cnt >= 2 时一票否决
tot_arm_a = tot_v15 & (hist_fb["theme_yizi_d2_cnt"] < 2)
sv_arm_a = sv_v15.copy()
r_arm_a = evaluate_strategy_master(hist_fb, "_sv_v15", tot_arm_a, fn_s8, desc="方案A: 同题材一字>=2一票否决")

# 方案 3: 方案 B (全面放行换手龙一) — 允许买可买窗口内的换手龙一 (即 tot_new)
sv_arm_b = np.where(mm_new, hist_fb["sc_v_recalc"] + 1000.0, hist_fb["sc_v_recalc"])
hist_fb["_sv_arm_b"] = sv_arm_b
# rk4 过滤
sub_b = hist_fb[tot_new].copy()
sub_b["_sv_tmp"] = sv_arm_b[tot_new]
bad_dts_b = set()
for d, grp in sub_b.groupby("d2_dt"):
    if (grp["rk_theme"] == 1).any():
        top_rk = grp.sort_values("_sv_tmp", ascending=False).iloc[0]["rk_theme"]
        if pd.notna(top_rk) and top_rk >= 4:
            bad_dts_b.add(d)
tot_arm_b = tot_new & (~hist_fb["d2_dt"].isin(bad_dts_b))
r_arm_b = evaluate_strategy_master(hist_fb, "_sv_arm_b", tot_arm_b, fn_s8, desc="方案B: 全面放行换手龙一")

# 方案 4: 方案 C (精细分流) — 题材内只有 1 只一字扛旗时放行换手龙一，但 >= 2 只一字时一票否决
tot_arm_c = tot_arm_b & (hist_fb["theme_yizi_d2_cnt"] < 2)
r_arm_c = evaluate_strategy_master(hist_fb, "_sv_arm_b", tot_arm_c, fn_s8, desc="方案C: 1只一字放行，>=2只一字否决")

print(f"\n{'方案名称':<36s} | {'笔数':<3s} | {'5年胜率':<6s} | {'盈亏比':<5s} | {'1S净值':<8s} | {'2S净值':<7s} | {'日等权':<6s} | {'最大回撤':<6s}")
print("-" * 95)
for name, r in [
    ("基线 S8 (现行完全体)", r_base),
    ("方案 A: 同题材一字>=2只一票否决", r_arm_a),
    ("方案 B: 全面放行换手龙一", r_arm_b),
    ("方案 C: 1只一字放行，>=2只一字否决", r_arm_c),
]:
    print(f"{name:<36s} | {r['trades_5y']:3d} | {r['wr_5y']:5.1f}% | {r['payoff_5y']:5.2f} | {r['nav_1s']:7.2f}x | {r['nav_2s']:6.2f}x | {r['daily_eq']:5.2f}x | {r['mdd_1s']:5.1f}%")

print("\n--- 逐年与近期胜率对比 ---")
for name, r in [
    ("基线 S8", r_base),
    ("方案 A", r_arm_a),
    ("方案 B", r_arm_b),
    ("方案 C", r_arm_c),
]:
    tl = r["trades_list"]
    df_t = pd.DataFrame(tl)
    if len(df_t) > 0:
        df_t["year"] = df_t["buy_date"].str[:4].astype(int)
        wr_2026 = (df_t[df_t["year"] == 2026]["net_ret"] > 0).mean() * 100 if (df_t["year"] == 2026).any() else 0.0
        n_2026 = (df_t["year"] == 2026).sum()
        wr_3y = (df_t[df_t["year"] >= 2024]["net_ret"] > 0).mean() * 100 if (df_t["year"] >= 2024).any() else 0.0
        n_3y = (df_t["year"] >= 2024).sum()
        print(f"{name:<15s}: 2026胜率={wr_2026:5.1f}%(N={n_2026}) | 近3年胜率={wr_3y:5.1f}%(N={n_3y}) | 5年总净超额={r['nav_1s'] - 1.0 - CSI300_5Y_CUM:+.2f}")

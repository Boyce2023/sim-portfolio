#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
lab_b_theme_structure_matrix.py
================================================================================
A股一进二试验地沙盒二号课题：题材打分真实贡献拆解与题材竞争结构优化空间深挖
Master Sandbox Lab B: Theme Scoring Contribution & Competition Matrix Audit

严格遵循：
1. 生产盘硬隔离（绝不修改主策略文件与飞书文档）
2. 绝对零未来函数（09:25 PIT，双边千二摩擦）
3. 绝对只读数据库（mode=ro, uri=True）
4. D15 回测防伪四必核（全5年、近3年、近1年、7月以来四期胜率、盈亏比、等权与单仓净值、最大回撤、沪深300超额）
================================================================================
"""

import os
import sys
import time
import json
import sqlite3
import datetime
from collections import defaultdict

import numpy as np
import pandas as pd

PROJECT_ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM_DIR = f"{PROJECT_ROOT}/sim-portfolio"
BACKTEST_CLEAN_DIR = f"{SIM_DIR}/backtest/2026-11-11-1to2-clean"
BACKTEST_ASTOCK_DIR = f"{SIM_DIR}/backtests_astock"
LAB_DIR = f"{BACKTEST_ASTOCK_DIR}/sandbox_lab"

if BACKTEST_CLEAN_DIR not in sys.path:
    sys.path.insert(0, BACKTEST_CLEAN_DIR)
if BACKTEST_ASTOCK_DIR not in sys.path:
    sys.path.insert(0, BACKTEST_ASTOCK_DIR)

from clean_wf_1to2_v14_ironclad_master import (
    load_full_prices, FEE_RATE, CSI300_5Y_CUM, CSI300_ANNUAL
)
from master_5y_zero_lookahead_walkforward import evaluate_strategy_master

CSI300_3Y = 0.0912
CSI300_1Y = -0.1280
CSI300_JUL = -0.1850

OUT_JSON = f"{LAB_DIR}/lab_b_results.json"
OUT_REPORT = f"{LAB_DIR}/LAB_B_THEME_STRUCTURE_REPORT.md"

print("=" * 80)
print("【A股一进二沙盒二号课题：题材打分真实贡献拆解与题材竞争结构矩阵】")
print(f"启动时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 80)

# ------------------------------------------------------------------------------
# 1. 加载行情与特征底座
# ------------------------------------------------------------------------------
t0 = time.time()
print("\n>>> [1/6] 加载行情与5分钟K线底座...")
df_daily, all_dts, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map = load_full_prices()
dt_to_idx = {d: i for i, d in enumerate(all_dts)}
price_lookup = {
    (r.c6, r.dt_str): (r.open, r.high, r.low, r.close, r.zt_price, r.dt_price, r.is_zt, r.is_yizi_dt)
    for r in df_daily[["c6", "dt_str", "open", "high", "low", "close", "zt_price", "dt_price", "is_zt", "is_yizi_dt"]].itertuples(index=False)
}

PARQUET_5M_COMPLETE = f"{SIM_DIR}/data/cand_5m_bars_v15_complete.parquet"
df_5m = pd.read_parquet(PARQUET_5M_COMPLETE)
df_5m["hhmm_int"] = df_5m["hhmm"].astype(int)
df_5m.sort_values(["c6", "date", "hhmm_int"], inplace=True)
bars_5m_map = {}
for (c6, dt), grp in df_5m.groupby(["c6", "date"], sort=False):
    bars_5m_map[(c6, dt)] = grp[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy()

with open("/tmp/astock_hist_fb_preprocessed.pkl", "rb") as fp:
    hist_fb = pickle_fb = pd.read_pickle(fp)

hist_fb = hist_fb[hist_fb["d2_dt"].notna() & (hist_fb["d2_dt"] <= "2026-11-10")].copy().reset_index(drop=True)
hist_fb["gap_days"] = (pd.to_datetime(hist_fb["d2_dt"]) - pd.to_datetime(hist_fb["dt_str"])).dt.days
hist_fb["c6"] = hist_fb["ticker"].astype(str).str[:6]

# 证监会二级行业
CSRC_PATH_PREF = f"{SIM_DIR}/data/csrc_industry_l2.csv"
ind_df = pd.read_csv(CSRC_PATH_PREF)
ind_df["c6"] = ind_df["code"].astype(str).str[-6:]
ind_map = dict(zip(ind_df["c6"], ind_df["industry"].fillna("")))
hist_fb["csrc_ind"] = hist_fb["c6"].map(ind_map).fillna("")

# 微观盘口
conn_tape = sqlite3.connect(f"file:{SIM_DIR}/data/zt_micro_tape_5y_pit.db?mode=ro", uri=True)
tape_df = pd.read_sql_query("SELECT trade_date, sec_code, first_seal_time, seal_amount, open_board_count FROM zt_micro_tape", conn_tape)
conn_tape.close()
hist_fb = hist_fb.merge(tape_df.drop_duplicates(["trade_date", "sec_code"]), left_on=["dt_str", "c6"], right_on=["trade_date", "sec_code"], how="left")

# PIT 机构调研
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

# 题材日排名 (rk_theme)
valid_plate = hist_fb[(hist_fb["plate"] != "其他") & (~hist_fb["is_event_basket"])].copy()
pg = valid_plate.groupby(["d2_dt", "plate"], as_index=False).agg(
    p_sz_max=("p_sz", "max"),
    p_theme_med=("s_prior_dual", "median"),
    p_theme_mean=("s_prior_dual", "mean"),
    p_open_avg=("d2_o_pct", "mean"),
    p_high_open_cnt=("_is_high_open", "sum"),
    p_cand_cnt=("ticker", "count")
)
pg_m = pg[pg["p_sz_max"] >= 2].copy()
pg_m["rk_theme"] = pg_m.groupby("d2_dt")["p_theme_med"].rank(ascending=False, method="min")
hist_fb = hist_fb.merge(pg_m[["d2_dt", "plate", "rk_theme"]], on=["d2_dt", "plate"], how="left")

print(f"    基础数据加载与挂载完成，耗时 {time.time()-t0:.2f}s, 首板样本 {len(hist_fb):,} 行")

# ------------------------------------------------------------------------------
# 2. 构建特征与交易模拟引擎
# ------------------------------------------------------------------------------
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
pass_nd_orig = (~((hist_fb["p_sz"] >= 2) & (hist_fb["buyable_plate_rk"] >= 3))) & (~((hist_fb["plate_d2_yizi_cnt"] >= 1) & ((hist_fb["mcap"] > 90.0) | (hist_fb["d1_seal_tightness"] < 15.0))))
pass_ac = ~(hist_fb["p_sz"] > 35) & (~hist_fb["notice_bad"])
wk_mask = hist_fb["gap_days"] >= 3
f3_bonus = np.where(hist_fb["notice_hard"], 8.0, 0.0) + np.where(hist_fb["notice_bad"], -35.0, 0.0)
thr_vec = np.where(hist_fb["mkt_seal_rate"] > 0.75, 304.8 + 25.0, 304.8)

hist_fb["score_wk"] = hist_fb["score_dual"] + bonus_spear + np.where(wk_mask, 10.0, 0.0) + f3_bonus
hist_fb["s_prior_wk"] = hist_fb["s_prior_dual"] + bonus_spear + np.where(wk_mask, 10.0, 0.0) + f3_bonus

m_t2_base = common_ok & (hist_fb["p_sz"] == 1) & (hist_fb["is_pioneer_word"] | hist_fb["notice_hard"] | hist_fb["is_ma"] | hist_fb["has_new_term"] | hist_fb["own_new_term"]) & hist_fb["d2_o_pct"].between(0.035, 0.078) & (hist_fb["buyable_mkt_open_rk"] <= 3) & (hist_fb["d1_seal_tightness"] >= 15.0) & ((hist_fb["f_dd20_d0"] <= 0.88) | (hist_fb["clean_brk60"] == 1))

in_std_buy_win = common_ok & (
    (wk_mask & hist_fb["d2_o_pct"].between(0.020, 0.088))
    | ((~wk_mask) & hist_fb["d2_o_pct"].between(0.022, 0.078))
)
is_front_lock = hist_fb["d2_is_yizi"] | (
    (~wk_mask) & (hist_fb["d2_o_pct"] > 0.078)
) | (
    wk_mask & (hist_fb["d2_o_pct"] > 0.088)
)
hist_fb["_is_front_lock"] = is_front_lock.astype(int)
hist_fb["front_lock_cnt"] = hist_fb.groupby(["d2_dt", "plate"])["_is_front_lock"].transform("sum")
hist_fb["mkt_yizi_cnt"] = hist_fb.groupby("d2_dt")["d2_is_yizi"].transform("sum").fillna(0).astype(int)

hist_fb["_true_buy_o"] = np.where(in_std_buy_win, hist_fb["d2_o_pct"], -9.99)
hist_fb["true_buy_rk"] = hist_fb.groupby(["d2_dt", "plate"])["_true_buy_o"].rank(ascending=False, method="min")

has_distinct_sub = (
    (hist_fb["p_sz"] >= 8)
    & (hist_fb["r_short"] != hist_fb["plate"])
    & (hist_fb["r_short"] != "其他")
    & (hist_fb["r_short"] != "")
)
orig_rk_bonus = np.where(
    hist_fb["buyable_plate_rk"] == 1, 35.0,
    np.where(has_distinct_sub & (hist_fb["subbranch_rk"] == 1), 24.0,
             np.where(hist_fb["buyable_plate_rk"] == 2, 8.0, -25.0))
)
true_rk_bonus = np.where(
    hist_fb["true_buy_rk"] == 1, 35.0,
    np.where(has_distinct_sub & (hist_fb["subbranch_rk"] == 1), 24.0,
             np.where(hist_fb["true_buy_rk"] == 2, 8.0, -25.0))
)
rk_fix_delta = true_rk_bonus - orig_rk_bonus

pass_nd_true = (~((hist_fb["p_sz"] >= 2) & (hist_fb["true_buy_rk"] >= 3))) & (
    ~((hist_fb["plate_d2_yizi_cnt"] >= 1) & ((hist_fb["mcap"] > 90.0) | (hist_fb["d1_seal_tightness"] < 15.0)))
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

flc = hist_fb["front_lock_cnt"].values
tbrk = hist_fb["true_buy_rk"].values
myz = hist_fb["mkt_yizi_cnt"].values
is_super_wave = (hist_fb["rk_theme"] == 1) & (hist_fb["p_sz"] >= 8) & (tbrk == 1)

def get_yizi_gran(w_flc1_gold=8.0, w_flc1_norm=5.0, w_flc1_sub=-10.0, w_super=5.0, w_flc2=-15.0, w_flc3=-22.0, w_mkt0=-5.0):
    return np.select(
        [
            (flc == 1) & (tbrk == 1) & np.isin(myz, [1, 2]),
            (flc == 1) & (tbrk == 1),
            (flc == 1) & (tbrk >= 2),
            (flc >= 2) & is_super_wave,
            (flc == 2) & (~is_super_wave),
            (flc >= 3) & (~is_super_wave),
            (flc == 0) & (myz == 0) & (~has_ma_hard),
        ],
        [w_flc1_gold, w_flc1_norm, w_flc1_sub, w_super, w_flc2, w_flc3, w_mkt0],
        default=0.0,
    )

y_std = get_yizi_gran(8.0, 5.0, -10.0, 5.0, -15.0, -22.0, -5.0)

# Trade engine definition (S8 complete 10:30 VWAP)
def make_v16_trade_engine(mode="s8_complete", fee=FEE_RATE):
    def sim_trade(row):
        c6, d2 = row["c6"], row["d2_dt"]
        idx2 = dt_to_idx.get(d2, -1)
        if idx2 < 0 or idx2 >= len(all_dts) - 1: return None
        d2_bar = price_lookup.get((c6, d2))
        if not d2_bar: return None
        o2, h2, l2, c2, zt2, dt2, is_zt2, is_yz_dt2 = d2_bar
        if o2 >= zt2 - 0.005 or o2 <= 0: return None
        is_monday = row.get("gap_days", 1) >= 3
        cand_score = row.get("score_active", row.get("score_0", 0.0))
        cand_lead = row.get("buy_open_lead", 0.0)
        do_direct = is_monday and (cand_score >= 310.0) and (cand_lead >= 0.025)
        buy_px = round(float(o2), 2) if do_direct else round(float(row["trig_p"]), 2)
        if (not do_direct) and (h2 < float(row["trig_p"]) or float(row["trig_p"]) >= zt2 - 0.005): return None
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
                        if iyzc: prev_c = round(float(cc), 2); curr += 1; continue
                        arr = bars_5m_map.get((c6, dc))
                        if arr is not None and len(arr) >= 12:
                            idx_1030 = -1
                            cum_v, cum_a = 0.0, 0.0
                            for bi in range(len(arr)):
                                cum_v += arr[bi, 5]; cum_a += arr[bi, 6]
                                if arr[bi, 0] == 1030: idx_1030 = bi; break
                            if idx_1030 >= 0:
                                bc_1030 = arr[idx_1030, 4]
                                vwap_1030 = cum_a / cum_v if cum_v > 0 else bc_1030
                                if bc_1030 >= ztc - 0.01:
                                    for bi in range(idx_1030 + 1, len(arr) - 1):
                                        if arr[bi, 0] >= 1430 and arr[bi, 4] < ztc - 0.01:
                                            px = round(float(arr[bi + 1, 1]), 2)
                                            return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "5m_1430_rush"}
                                    if iztc: prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
                                    else:
                                        px = round(float(cc), 2)
                                        return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "eod_break"}
                                elif bc_1030 < vwap_1030:
                                    px = round(float(arr[idx_1030 + 1, 1]), 2) if idx_1030 + 1 < len(arr) else round(float(bc_1030), 2)
                                    return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "5m_1030_weak_cut"}
                                else:
                                    if iztc: prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
                                    if (boards_held >= 3) and (not used_immunity) and (cc >= prev_c * 1.02) and (curr + 1 < len(all_dts)):
                                        used_immunity = True; prev_c = round(float(cc), 2); curr += 1; continue
                                    px = round(float(cc), 2)
                                    return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "eod_close"}
                        if iztc: prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
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
        # Branch 2: sealed 2B
        curr = idx3
        boards_held = 2
        used_immunity = False
        while curr < len(all_dts) and (curr - idx2 <= 12):
            dc = all_dts[curr]
            b = price_lookup.get((c6, dc))
            if not b: break
            oc, hc, lc, cc, ztc, dtc, iztc, iyzc = b
            if iyzc: prev_c = round(float(cc), 2); curr += 1; continue
            arr = bars_5m_map.get((c6, dc))
            if arr is not None and len(arr) >= 12:
                idx_1030 = -1
                cum_v, cum_a = 0.0, 0.0
                for bi in range(len(arr)):
                    cum_v += arr[bi, 5]; cum_a += arr[bi, 6]
                    if arr[bi, 0] == 1030: idx_1030 = bi; break
                if idx_1030 >= 0:
                    bc_1030 = arr[idx_1030, 4]
                    vwap_1030 = cum_a / cum_v if cum_v > 0 else bc_1030
                    if bc_1030 >= ztc - 0.01:
                        for bi in range(idx_1030 + 1, len(arr) - 1):
                            if arr[bi, 0] >= 1430 and arr[bi, 4] < ztc - 0.01:
                                px = round(float(arr[bi + 1, 1]), 2)
                                return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "5m_1430_rush"}
                        if iztc: prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
                        else:
                            px = round(float(cc), 2)
                            return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "eod_break"}
                    elif bc_1030 < vwap_1030:
                        px = round(float(arr[idx_1030 + 1, 1]), 2) if idx_1030 + 1 < len(arr) else round(float(bc_1030), 2)
                        return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "5m_1030_weak_cut"}
                    else:
                        if iztc: prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
                        if (boards_held >= 3) and (not used_immunity) and (cc >= prev_c * 1.02) and (curr + 1 < len(all_dts)):
                            used_immunity = True; prev_c = round(float(cc), 2); curr += 1; continue
                        px = round(float(cc), 2)
                        return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "eod_close"}
            if iztc: prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
            if (boards_held >= 3) and (not used_immunity) and (cc >= prev_c * 1.02) and (curr + 1 < len(all_dts)):
                used_immunity = True; prev_c = round(float(cc), 2); curr += 1; continue
            px = round(float(cc), 2)
            return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "eod_close"}
        return {"net_ret": round((prev_c / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": all_dts[min(curr, len(all_dts)-1)], "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": prev_c}
    return sim_trade

fn_s8_20 = make_v16_trade_engine("s8_complete", FEE_RATE)

def compute_d15_metrics(trades_list):
    if not trades_list:
        return {
            "nav_1s": 1.0, "mdd_1s": 0.0, "daily_eq": 1.0, "excess_csi300": 0.0,
            "trades_5y": 0, "wr_5y": 0.0, "payoff_5y": 0.0, "mean_5y": 0.0, "big_win_5y": 0.0, "big_loss_5y": 0.0,
            "trades_3y": 0, "wr_3y": 0.0, "payoff_3y": 0.0, "mean_3y": 0.0, "big_win_3y": 0.0, "big_loss_3y": 0.0,
            "trades_1y": 0, "wr_1y": 0.0, "payoff_1y": 0.0, "mean_1y": 0.0, "big_win_1y": 0.0, "big_loss_1y": 0.0,
            "trades_jul": 0, "wr_jul": 0.0, "payoff_jul": 0.0, "mean_jul": 0.0, "big_win_jul": 0.0, "big_loss_jul": 0.0,
        }
    df_t = pd.DataFrame(trades_list).sort_values("buy_date")
    
    # Single-slot rotation
    free_dt, free_open = "", False
    nav_1s, peak, mdd = 1.0, 1.0, 0.0
    rot_trades = []
    for dt, grp in df_t.groupby("buy_date", sort=True):
        if free_dt == "" or dt > free_dt or (dt == free_dt and free_open):
            tr = grp.iloc[0]
            nav_1s *= (1.0 + tr["net_ret"])
            peak = max(peak, nav_1s)
            mdd = max(mdd, (peak - nav_1s) / peak)
            free_dt, free_open = tr["exit_date"], bool(tr["exit_at_open"])
            rot_trades.append(tr)
    rot_df = pd.DataFrame(rot_trades)
    
    # Daily eq
    daily_grp = df_t.groupby("buy_date")["net_ret"].mean()
    eq_nav = float(np.prod(1.0 + daily_grp.values))
    
    def sub_stat(sub):
        if len(sub) == 0:
            return 0, 0.0, 0.0, 0.0, 0.0, 0.0
        r = sub["net_ret"].values
        wr = float((r > 0).mean() * 100)
        w = float(r[r > 0].mean()) if (r > 0).any() else 0.0
        l = float(abs(r[r < 0].mean())) if (r < 0).any() else 1e-4
        po = float(w / l) if (r < 0).any() else 99.9
        mr = float(r.mean() * 100)
        bw = float((r >= 0.15).mean() * 100)
        bl = float((r <= -0.07).mean() * 100)
        return len(sub), round(wr, 1), round(po, 2), round(mr, 2), round(bw, 1), round(bl, 1)

    t5, wr5, po5, mr5, bw5, bl5 = sub_stat(rot_df)
    t3, wr3, po3, mr3, bw3, bl3 = sub_stat(rot_df[rot_df["buy_date"] >= "2023-11-10"])
    t1, wr1, po1, mr1, bw1, bl1 = sub_stat(rot_df[rot_df["buy_date"] >= "2025-11-12"])
    tj, wrj, poj, mrj, bwj, blj = sub_stat(rot_df[rot_df["buy_date"] >= "2026-07-01"])

    return {
        "nav_1s": round(nav_1s, 2),
        "mdd_1s": round(mdd * 100, 1),
        "daily_eq": round(eq_nav, 2),
        "excess_csi300": round((nav_1s - 1.0 - CSI300_5Y_CUM) * 100, 1),
        "trades_5y": t5, "wr_5y": wr5, "payoff_5y": po5, "mean_5y": mr5, "big_win_5y": bw5, "big_loss_5y": bl5,
        "trades_3y": t3, "wr_3y": wr3, "payoff_3y": po3, "mean_3y": mr3, "big_win_3y": bw3, "big_loss_3y": bl3,
        "trades_1y": t1, "wr_1y": wr1, "payoff_1y": po1, "mean_1y": mr1, "big_win_1y": bw1, "big_loss_1y": bl1,
        "trades_jul": tj, "wr_jul": wrj, "payoff_jul": poj, "mean_jul": mrj, "big_win_jul": bwj, "big_loss_jul": blj,
        "rot_trades": rot_trades,
    }

# ------------------------------------------------------------------------------
# 3. 运行通用回测管道
# ------------------------------------------------------------------------------
def evaluate_custom_pipeline(
    desc,
    score_col,
    pass_mask,
    engine_fn=fn_s8_20,
    block_rk4=True,
    custom_rank_filter=None
):
    df_eval = hist_fb.copy()
    tot = pass_mask.copy()
    
    if block_rk4:
        sub_tot = df_eval[tot].copy()
        sub_tot["_sv_tmp"] = score_col[tot]
        bad_dts = set()
        for d, grp in sub_tot.groupby("d2_dt"):
            if (grp["rk_theme"] == 1).any():
                top_rk = grp.sort_values("_sv_tmp", ascending=False).iloc[0]["rk_theme"]
                if pd.notna(top_rk) and top_rk >= 4:
                    bad_dts.add(d)
        tot = tot & (~df_eval["d2_dt"].isin(bad_dts))
        
    if custom_rank_filter is not None:
        tot = tot & custom_rank_filter(df_eval, score_col)
        
    df_eval["_score_eval"] = score_col
    # Use evaluate_strategy_master to get official execution
    res = evaluate_strategy_master(df_eval, "_score_eval", tot, engine_fn, desc=desc)
    d15 = compute_d15_metrics(res["trades_list"])
    d15["desc"] = desc
    return d15, res

# Base V16 score and condition
rk_d = rk_fix_delta
q_pen = - np.where((~wk_mask) & (hist_fb["d2_o_pct"] < 0.031), 15.0, 0.0)
d_ov = np.where((~clean_brk60) & (dd20 <= 0.82), -10.0, 0.0)
is_ht = (open_cnt == 1) & (seal_time <= "10:30:00") & (hist_fb["d1_seal_tightness"] >= 38.0)
bon_tape = np.where(is_ht, 5.0, 0.0) + np.where(hist_fb["has_ir_pit"], 5.0, 0.0)

sp_v16 = hist_fb["s_prior_wk"] + name_sub20 + y_std * 0.5
sq_v16 = hist_fb["s_quant_dual"] + q_pen + d_ov + bon_tape + rk_d + y_std * 0.5
sc_v16 = hist_fb["score_wk"] + q_pen + d_ov + bon_tape + rk_d + y_std + name_sub20
hist_fb["score_active"] = sc_v16

p_tight = hist_fb["d1_seal_tightness"] >= 37.0
pass_nd_v = pass_nd_true

m_t1_v16 = common_ok & ((wk_mask & hist_fb["d2_o_pct"].between(0.020, 0.088)) | ((~wk_mask) & hist_fb["d2_o_pct"].between(0.022, 0.078))) & (sp_v16 >= 45.0) & (sq_v16 >= 150.0) & (sc_v16 >= thr_vec)
mm_v16 = ((m_t1_v16 & pass_l1 & pass_l2 & pass_l3 & pass_nd_v & pass_ac) | (m_t2_base & pass_l2)) & p_tight
mmon_v16 = common_ok & wk_mask & hist_fb["d2_o_pct"].between(0.015, 0.090) & (sp_v16 >= 38.0) & (sq_v16 >= 145.0) & (sc_v16 >= thr_vec) & pass_l1 & pass_l2 & pass_l3 & pass_nd_v & pass_ac & p_tight
tot_v16 = (mm_v16 | (mmon_v16 & (~mm_v16))).copy()
sv_v16 = np.where(mm_v16, sc_v16 + 1000.0, sc_v16)

# Verify V16 Champion
print("\n>>> [2/6] 验证定版 V16 基准...")
d15_v16, res_v16 = evaluate_custom_pipeline("V16基准完全体", sv_v16, tot_v16, block_rk4=True)
print(f"    V16基准核对结果: {d15_v16['trades_5y']}笔 | 胜率 {d15_v16['wr_5y']}% | 盈亏比 {d15_v16['payoff_5y']} | 1S净值 {d15_v16['nav_1s']}x | MDD {d15_v16['mdd_1s']}%")
assert d15_v16["trades_5y"] == 105 and d15_v16["wr_5y"] == 63.8, f"V16 verification failed! {d15_v16}"

# ------------------------------------------------------------------------------
# 4. 课题一：题材打分总纲消融与本质贡献拆解
# ------------------------------------------------------------------------------
print("\n" + "=" * 80)
print(">>> [3/6] 执行课题一：题材打分总纲消融与本质贡献拆解...")
print("=" * 80)

# 消融 A: 完全拿掉题材先验打分与题材排名 (纯个股筹码分 + 全市场竞价)
# 去除: s_prior, true_buy_rk plate rank, buy_open_lead, plate_d2_yizi, pass_l1/l2/l3, pass_nd, block_rk4
sc_pure_stock = hist_fb["s_q_base_dual"] + (
    np.where(hist_fb["buyable_mkt_open_rk"] <= 3, 20.0, np.where(hist_fb["buyable_mkt_open_rk"] <= 6, 12.0, 0.0))
    + np.where(hist_fb["d2_o_pct"].between(0.040, 0.082), 20.0, np.where(hist_fb["d2_o_pct"].between(0.018, 0.040), 12.0, 0.0))
    + q_pen + d_ov + bon_tape
)
# Calibrate threshold to yield similar opportunity density
# If threshold set to select top market auction candidate with standard chip quality
pass_pure_stock = common_ok & in_std_buy_win & p_tight & (~clean_brk60 | (dd20 <= 0.82))
# Let's test standard percentiles and absolute score thresholds for Pure Stock
thr_pure = np.quantile(sc_pure_stock[pass_pure_stock], 0.90)
m_pure = pass_pure_stock & (sc_pure_stock >= 195.0)
d15_pure_stock, _ = evaluate_custom_pipeline("消融1:纯个股筹码与全市场竞价(无题材打分/无三层净化)", sc_pure_stock, m_pure, block_rk4=False)

# 消融 B: 保留三层假题材净化 + 外行减20分，但拉平题材先验打分 (所有题材视为平权中性 50分)
sp_flat = np.full(len(hist_fb), 50.0) + name_sub20 + y_std * 0.5
sq_flat = hist_fb["s_quant_dual"] + q_pen + d_ov + bon_tape + rk_d + y_std * 0.5
sc_flat = sp_flat + sq_flat
m_flat_t1 = common_ok & in_std_buy_win & (sp_flat >= 45.0) & (sq_flat >= 150.0) & (sc_flat >= thr_vec)
mm_flat = ((m_flat_t1 & pass_l1 & pass_l2 & pass_l3 & pass_nd_v & pass_ac) | (m_t2_base & pass_l2)) & p_tight
tot_flat = mm_flat.copy()
sv_flat = np.where(mm_flat, sc_flat + 1000.0, sc_flat)
d15_flat_theme, _ = evaluate_custom_pipeline("消融2:保留三层净化但拉平题材分(题材平权中性)", sv_flat, tot_flat, block_rk4=False)

# 消融 C: 仅去除三层假题材净化 (Layer 1/2/3 关掉)，保留题材先验打分与排位
mm_no_purifier = ((m_t1_v16 & pass_nd_v & pass_ac) | m_t2_base) & p_tight
tot_no_purifier = mm_no_purifier.copy()
sv_no_purifier = np.where(mm_no_purifier, sc_v16 + 1000.0, sc_v16)
d15_no_purifier, _ = evaluate_custom_pipeline("消融3:关掉三层假题材净化(允许事件型/伪题材入池)", sv_no_purifier, tot_no_purifier, block_rk4=True)

# 消融 D: 仅去除冷门题材拦截 (关掉 block_rk4)
d15_no_block4, _ = evaluate_custom_pipeline("消融4:允许第4名及以后冷门题材(关掉block_rk4)", sv_v16, tot_v16, block_rk4=False)

module1_results = {
    "V16基准完全体": d15_v16,
    "消融1_纯个股无题材": d15_pure_stock,
    "消融2_拉平题材分": d15_flat_theme,
    "消融3_去除三层净化": d15_no_purifier,
    "消融4_关掉冷门拦截": d15_no_block4,
}

print(f"{'消融配置':<35s} | {'5Y笔数':<5s} | {'5Y胜率':<6s} | {'盈亏比':<5s} | {'大肉率':<5s} | {'大面率':<5s} | {'1S净值':<7s} | {'日等权':<6s} | {'MDD':<5s}")
print("-" * 95)
for k, v in module1_results.items():
    print(f"{v['desc']:<35s} | {v['trades_5y']:5d} | {v['wr_5y']:5.1f}% | {v['payoff_5y']:5.2f} | {v['big_win_5y']:4.1f}% | {v['big_loss_5y']:4.1f}% | {v['nav_1s']:6.2f}x | {v['daily_eq']:5.2f}x | {v['mdd_1s']:4.1f}%")

# ------------------------------------------------------------------------------
# 5. 课题二：重点场景A — 断层第一主线无过线龙一的真实表现
# ------------------------------------------------------------------------------
print("\n" + "=" * 80)
print(">>> [4/6] 执行课题二：重点场景A — 断层第一大主线无过线龙一分析...")
print("=" * 80)

# 题材竞争矩阵特征提取
daily_t1 = pg_m[pg_m["rk_theme"] == 1].sort_values(["d2_dt", "p_theme_med"], ascending=[True, False]).drop_duplicates("d2_dt").set_index("d2_dt")
daily_t2 = pg_m[pg_m["rk_theme"] == 2].sort_values(["d2_dt", "p_theme_med"], ascending=[True, False]).drop_duplicates("d2_dt").set_index("d2_dt")
daily_t3 = pg_m[pg_m["rk_theme"] == 3].sort_values(["d2_dt", "p_theme_med"], ascending=[True, False]).drop_duplicates("d2_dt").set_index("d2_dt")

# Dominant Theme 1 criteria:
# 1. diff_1_2 >= 15.0 or diff_1_2 >= 20.0
# 2. t1_sz >= 6 and t1_sz >= 2 * t2_sz
dates_with_t1 = sorted(daily_t1.index)
dom_stats = []
for d in dates_with_t1:
    t1_row = daily_t1.loc[d]
    t2_row = daily_t2.loc[d] if d in daily_t2.index else None
    t3_row = daily_t3.loc[d] if d in daily_t3.index else None
    
    t1_med = float(t1_row["p_theme_med"])
    t2_med = float(t2_row["p_theme_med"]) if t2_row is not None else 0.0
    t3_med = float(t3_row["p_theme_med"]) if t3_row is not None else 0.0
    t1_sz = int(t1_row["p_sz_max"])
    t2_sz = int(t2_row["p_sz_max"]) if t2_row is not None else 1
    
    diff_1_2 = t1_med - t2_med
    ratio_sz = t1_sz / max(1, t2_sz)
    
    is_dom_score = diff_1_2 >= 20.0
    is_dom_sz = (t1_sz >= 6) and (ratio_sz >= 2.0)
    is_dominant = is_dom_score or is_dom_sz
    
    # Check Theme 1 passed candidates in V16
    t1_plate = t1_row["plate"]
    sub_d = hist_fb[hist_fb["d2_dt"] == d]
    sub_d_passed = sub_d[tot_v16[sub_d.index]]
    
    t1_has_passed = (sub_d_passed["plate"] == t1_plate).any() if len(sub_d_passed) > 0 else False
    
    # If Theme 1 did not have passed dragon, inspect why
    t1_cands = sub_d[sub_d["plate"] == t1_plate]
    t1_yizi_all = len(t1_cands) > 0 and (t1_cands["d2_is_yizi"] | (t1_cands["d2_o_pct"] > 0.088)).all()
    t1_has_yizi = len(t1_cands) > 0 and (t1_cands["d2_is_yizi"] | (t1_cands["d2_o_pct"] > 0.088)).any()
    
    # Best turnover candidate in Theme 1
    t1_buyable = t1_cands[in_std_buy_win[t1_cands.index]]
    t1_top_turnover = t1_buyable.sort_values("true_buy_rk").iloc[0] if len(t1_buyable) > 0 else None
    
    dom_stats.append({
        "d2_dt": d,
        "t1_plate": t1_plate,
        "t1_med": t1_med,
        "t2_med": t2_med,
        "diff_1_2": diff_1_2,
        "t1_sz": t1_sz,
        "t2_sz": t2_sz,
        "ratio_sz": ratio_sz,
        "is_dominant": is_dominant,
        "t1_has_passed": t1_has_passed,
        "t1_yizi_all": t1_yizi_all,
        "t1_has_yizi": t1_has_yizi,
        "t1_cands_cnt": len(t1_cands),
        "t1_buyable_cnt": len(t1_buyable),
        "t1_top_score": float(sc_v16[t1_top_turnover.name]) if t1_top_turnover is not None else 0.0,
        "t1_top_tbrk": int(t1_top_turnover["true_buy_rk"]) if t1_top_turnover is not None else 99,
        "t1_top_c6": str(t1_top_turnover["c6"]) if t1_top_turnover is not None else "",
        "t1_top_name": str(t1_top_turnover["name"]) if t1_top_turnover is not None else "",
    })

df_dom = pd.DataFrame(dom_stats).set_index("d2_dt")
dom_days = df_dom[df_dom["is_dominant"]]
dom_no_dragon = dom_days[~dom_days["t1_has_passed"]]

print(f"5年断层第一主线交易日总数: {len(dom_days)} 天")
print(f"  - Theme 1 龙一过线并成功买入/入池: {dom_days['t1_has_passed'].sum()} 天")
print(f"  - Theme 1 没有过线换手龙一: {len(dom_no_dragon)} 天")
print(f"    * 原因1: Theme 1 前排全是一字/准一字开盘打死: {dom_no_dragon['t1_yizi_all'].sum()} 天")
print(f"    * 原因2: 有换手备选但 true_buy_rk==1 分数落入 [280, 304.8): {(dom_no_dragon['t1_top_tbrk']==1) & (dom_no_dragon['t1_top_score']>=280)}.sum() 天")
print(f"    * 原因3: 龙一被锁死，只剩换手老二 (true_buy_rk==2): {(dom_no_dragon['t1_top_tbrk']==2)}.sum() 天")

# 子情形 A1: 测试在断层大主线里买「换手备选活口」的真实表现
# 策略 A1.1: 买 true_buy_rk == 1 但分数放宽至 [290, 304.8) 的 Theme 1 换手龙一
cands_a1_1 = []
for d, row in dom_no_dragon.iterrows():
    if row["t1_top_tbrk"] == 1 and 290.0 <= row["t1_top_score"] < 304.8:
        c_row = hist_fb.loc[hist_fb[(hist_fb["d2_dt"] == d) & (hist_fb["c6"] == row["t1_top_c6"])].index[0]]
        t = fn_s8_20(c_row)
        if t is not None:
            cands_a1_1.append(t)

# 策略 A1.2: 买 Theme 1 里的换手老二 (true_buy_rk == 2)
cands_a1_2 = []
for d, row in dom_no_dragon.iterrows():
    if row["t1_top_tbrk"] == 2 and row["t1_top_score"] >= 270.0:
        c_row = hist_fb.loc[hist_fb[(hist_fb["d2_dt"] == d) & (hist_fb["c6"] == row["t1_top_c6"])].index[0]]
        t = fn_s8_20(c_row)
        if t is not None:
            cands_a1_2.append(t)

d15_a1_1 = compute_d15_metrics(cands_a1_1)
d15_a1_2 = compute_d15_metrics(cands_a1_2)

print("\n--- 子情形 A1 表现 ---")
print(f"A1.1 (断层主线换手龙一微放宽至290分): {d15_a1_1['trades_5y']}笔 | 胜率 {d15_a1_1['wr_5y']}% | 盈亏比 {d15_a1_1['payoff_5y']} | 笔均 {d15_a1_1['mean_5y']:+.2f}% | 大面率 {d15_a1_1['big_loss_5y']}%")
print(f"A1.2 (断层主线换手老二/次优活口):       {d15_a1_2['trades_5y']}笔 | 胜率 {d15_a1_2['wr_5y']}% | 盈亏比 {d15_a1_2['payoff_5y']} | 笔均 {d15_a1_2['mean_5y']:+.2f}% | 大面率 {d15_a1_2['big_loss_5y']}%")

# 子情形 A2: 现行 105 笔中，在断层第一主线无龙一时，退而买了 Theme 2 或 Theme 3 的交易！
v16_trades = res_v16["trades_list"]
t_t2_on_dom_t1 = []
t_t3_on_dom_t1 = []
for t in v16_trades:
    d = t["buy_date"]
    if d in dom_no_dragon.index:
        # Check bought stock's theme rank
        c_row = hist_fb[(hist_fb["d2_dt"] == d) & (hist_fb["c6"] == t["c6"])].iloc[0]
        rk = c_row["rk_theme"]
        if rk == 2:
            t_t2_on_dom_t1.append(t)
        elif rk == 3:
            t_t3_on_dom_t1.append(t)

print(f"\n--- 子情形 A2 现行 105 笔穿透 ---")
print(f"当断层 Theme 1 无龙一时，现行策略退而买了 Theme 2: 共 {len(t_t2_on_dom_t1)} 笔")
for t in t_t2_on_dom_t1:
    print(f"  * {t['buy_date']} {t['name']} ({t['c6']}) -> 收益: {t['net_ret']*100:+.2f}% (tag: {t['tag']})")
print(f"当断层 Theme 1 无龙一时，现行策略退而买了 Theme 3: 共 {len(t_t3_on_dom_t1)} 笔")
for t in t_t3_on_dom_t1:
    print(f"  * {t['buy_date']} {t['name']} ({t['c6']}) -> 收益: {t['net_ret']*100:+.2f}% (tag: {t['tag']})")

d15_t2_on_dom = compute_d15_metrics(t_t2_on_dom_t1)
d15_t3_on_dom = compute_d15_metrics(t_t3_on_dom_t1)

# 优化实验 A-Opt: 当断层 Theme 1 存在且无过线龙一时，禁止买入 Theme 3 (或者 Theme 2/3)
def filter_block_t3_on_dom(df_eval, score_col):
    # If day has dominant theme 1, block theme 3
    is_blocked = np.zeros(len(df_eval), dtype=bool)
    for idx, (d, rk) in enumerate(zip(df_eval["d2_dt"], df_eval["rk_theme"])):
        if d in dom_no_dragon.index and rk == 3:
            is_blocked[idx] = True
    return ~is_blocked

d15_opt_block_t3, _ = evaluate_custom_pipeline(
    "优化A:断层主线存在但无龙一时拦截Theme#3",
    sv_v16,
    tot_v16,
    block_rk4=True,
    custom_rank_filter=filter_block_t3_on_dom
)

print(f"\n优化A (断层主线无龙一时拦截Theme#3) 边际净变化:")
print(f"  - 5年: {d15_opt_block_t3['trades_5y']}笔 | 胜率 {d15_opt_block_t3['wr_5y']}% (基准 {d15_v16['wr_5y']}%) | 净值 {d15_opt_block_t3['nav_1s']}x (基准 {d15_v16['nav_1s']}x)")
print(f"  - 3年: {d15_opt_block_t3['trades_3y']}笔 | 胜率 {d15_opt_block_t3['wr_3y']}% (基准 {d15_v16['wr_3y']}%)")
print(f"  - 1年: {d15_opt_block_t3['trades_1y']}笔 | 胜率 {d15_opt_block_t3['wr_1y']}% (基准 {d15_v16['wr_1y']}%)")
print(f"  - 7月: {d15_opt_block_t3['trades_jul']}笔 | 胜率 {d15_opt_block_t3['wr_jul']}% (基准 {d15_v16['wr_jul']}%)")

# ------------------------------------------------------------------------------
# 6. 课题三：重点场景B — 三足鼎立/群雄混战分流日优化空间
# ------------------------------------------------------------------------------
print("\n" + "=" * 80)
print(">>> [5/6] 执行课题三：重点场景B — 三足鼎立/群雄混战分流日优化分析...")
print("=" * 80)

# 定义三题材势均力敌混战日:
# 1. 当日存在 >= 3 个有效题材
# 2. 前三题材先验极差 <= 15 分 (range_top3 <= 15.0)
# 3. 各题材涨停梯队规模接近 (2 <= p_sz <= 5)
melee_days = set()
single_dom_days = set()

for d in dates_with_t1:
    t1_row = daily_t1.loc[d]
    t2_row = daily_t2.loc[d] if d in daily_t2.index else None
    t3_row = daily_t3.loc[d] if d in daily_t3.index else None
    
    if t1_row is not None and t2_row is not None and t3_row is not None:
        t1_med = float(t1_row["p_theme_med"])
        t3_med = float(t3_row["p_theme_med"])
        range_top3 = t1_med - t3_med
        sz_max = max(int(t1_row["p_sz_max"]), int(t2_row["p_sz_max"]), int(t3_row["p_sz_max"]))
        sz_min = min(int(t1_row["p_sz_max"]), int(t2_row["p_sz_max"]), int(t3_row["p_sz_max"]))
        
        if range_top3 <= 15.0 and sz_max <= 5 and sz_min >= 2:
            melee_days.add(d)
            
    if d in dom_days.index:
        single_dom_days.add(d)

print(f"5年三足鼎立群雄混战日总数: {len(melee_days)} 天")
print(f"5年清晰单主线日总数: {len(single_dom_days)} 天")

# 统计现行 105 笔在两类日期的分布
trades_in_melee = [t for t in v16_trades if t["buy_date"] in melee_days]
trades_in_dom = [t for t in v16_trades if t["buy_date"] in single_dom_days]
trades_in_other = [t for t in v16_trades if t["buy_date"] not in melee_days and t["buy_date"] not in single_dom_days]

d15_melee = compute_d15_metrics(trades_in_melee)
d15_dom = compute_d15_metrics(trades_in_dom)
d15_other = compute_d15_metrics(trades_in_other)

print(f"\n现行 105 笔按题材格局分类表现:")
print(f"  * 三题材混战日买入: {len(trades_in_melee):2d}笔 | 胜率 {d15_melee['wr_5y']:5.1f}% | 盈亏比 {d15_melee['payoff_5y']:4.2f} | 笔均 {d15_melee['mean_5y']:+5.2f}% | 大肉率 {d15_melee['big_win_5y']:4.1f}% | 大面率 {d15_melee['big_loss_5y']:4.1f}%")
print(f"  * 单主线清晰日买入: {len(trades_in_dom):2d}笔 | 胜率 {d15_dom['wr_5y']:5.1f}% | 盈亏比 {d15_dom['payoff_5y']:4.2f} | 笔均 {d15_dom['mean_5y']:+5.2f}% | 大肉率 {d15_dom['big_win_5y']:4.1f}% | 大面率 {d15_dom['big_loss_5y']:4.1f}%")
print(f"  * 其他过渡日买入:   {len(trades_in_other):2d}笔 | 胜率 {d15_other['wr_5y']:5.1f}% | 盈亏比 {d15_other['payoff_5y']:4.2f} | 笔均 {d15_other['mean_5y']:+5.2f}% | 大肉率 {d15_other['big_win_5y']:4.1f}% | 大面率 {d15_other['big_loss_5y']:4.1f}%")

# 混战日赢家与输家微观解剖
print("\n混战日交易逐笔穿透:")
for t in trades_in_melee:
    c_row = hist_fb[(hist_fb["d2_dt"] == t["buy_date"]) & (hist_fb["c6"] == t["c6"])].iloc[0]
    lead = c_row["buy_open_lead"]
    mkt_rk = c_row["buyable_mkt_open_rk"]
    has_hard = bool(c_row["notice_hard"] or c_row["is_ma"])
    print(f"  * {t['buy_date']} {t['name']} ({t['c6']}) 题材={c_row['plate']} 收益={t['net_ret']*100:+.2f}% | 竞价开={c_row['d2_o_pct']*100:+.2f}% 全市场排={mkt_rk} 题材领先={lead*100:+.2f}% 硬公告={has_hard}")

# 优化实验 B-Opt: 在三题材混战日，资金抽血严重，要求必须具备「混战破局真龙」特征：
# 竞价绝对排位 <= 2 (全市场前二高开) 或 具备硬催化 (notice_hard / is_ma)
def filter_melee_breakout(df_eval, score_col):
    is_ok = np.ones(len(df_eval), dtype=bool)
    for idx, (d, mrk, nh, hm, lead) in enumerate(zip(
        df_eval["d2_dt"],
        df_eval["buyable_mkt_open_rk"],
        df_eval["notice_hard"],
        df_eval["is_ma"],
        df_eval["buy_open_lead"]
    )):
        if d in melee_days:
            # Must be true breakout dragon
            is_breakout = (mrk <= 2) or nh or hm or (lead >= 0.020)
            if not is_breakout:
                is_ok[idx] = False
    return is_ok

d15_opt_melee, _ = evaluate_custom_pipeline(
    "优化B:三题材混战日破局真龙卡位过滤",
    sv_v16,
    tot_v16,
    block_rk4=True,
    custom_rank_filter=filter_melee_breakout
)

print(f"\n优化B (三题材混战日破局过滤) 边际净变化:")
print(f"  - 5年: {d15_opt_melee['trades_5y']}笔 | 胜率 {d15_opt_melee['wr_5y']}% (基准 {d15_v16['wr_5y']}%) | 净值 {d15_opt_melee['nav_1s']}x (基准 {d15_v16['nav_1s']}x)")
print(f"  - 3年: {d15_opt_melee['trades_3y']}笔 | 胜率 {d15_opt_melee['wr_3y']}% (基准 {d15_v16['wr_3y']}%)")
print(f"  - 1年: {d15_opt_melee['trades_1y']}笔 | 胜率 {d15_opt_melee['wr_1y']}% (基准 {d15_v16['wr_1y']}%)")
print(f"  - 7月: {d15_opt_melee['trades_jul']}笔 | 胜率 {d15_opt_melee['wr_jul']}% (基准 {d15_v16['wr_jul']}%)")

# ------------------------------------------------------------------------------
# 7. 课题四：全景扫描题材竞争结构的其他真实盲区
# ------------------------------------------------------------------------------
print("\n" + "=" * 80)
print(">>> [6/6] 执行课题四：全景扫描题材竞争结构的其他真实盲区...")
print("=" * 80)

# 盲区 1: 盘前题材高分 vs 09:25 板块集体竞价背离
# plate_d2_open_avg < 0.0 (板块平均绿开兑现)
t_diverge_weak = []
t_diverge_strong = []
for t in v16_trades:
    c_row = hist_fb[(hist_fb["d2_dt"] == t["buy_date"]) & (hist_fb["c6"] == t["c6"])].iloc[0]
    p_avg = c_row["plate_d2_open_avg"]
    if p_avg < 0.0:
        t_diverge_weak.append(t)
    elif p_avg >= 0.025:
        t_diverge_strong.append(t)

d15_div_weak = compute_d15_metrics(t_diverge_weak)
d15_div_strong = compute_d15_metrics(t_diverge_strong)

print(f"盲区1 板块竞价承接背离检验:")
print(f"  * 盘前过线但板块整体竞价绿开 (<0.0%): {len(t_diverge_weak)}笔 | 胜率 {d15_div_weak['wr_5y']}% | 笔均 {d15_div_weak['mean_5y']:+.2f}%")
print(f"  * 板块整体竞价爆表 (>=+2.5%):         {len(t_diverge_strong)}笔 | 胜率 {d15_div_strong['wr_5y']}% | 笔均 {d15_div_strong['mean_5y']:+.2f}%")

# 盲区 2: 主线连续霸榜天数疲劳度 (Theme Fatigue)
# 计算每个板块连续霸榜第1名的天数
theme_streaks = {}
curr_t1, curr_streak = "", 0
daily_t1_sorted = pg_m[pg_m["rk_theme"] == 1].sort_values("d2_dt").drop_duplicates("d2_dt")
for _, r in daily_t1_sorted.iterrows():
    d, pl = r["d2_dt"], r["plate"]
    if pl == curr_t1:
        curr_streak += 1
    else:
        curr_t1 = pl
        curr_streak = 1
    theme_streaks[(d, pl)] = curr_streak

t_fatigue_new = []
t_fatigue_old = []
for t in v16_trades:
    c_row = hist_fb[(hist_fb["d2_dt"] == t["buy_date"]) & (hist_fb["c6"] == t["c6"])].iloc[0]
    stk = theme_streaks.get((t["buy_date"], c_row["plate"]), 1)
    if stk <= 2:
        t_fatigue_new.append(t)
    else:
        t_fatigue_old.append(t)

d15_fat_new = compute_d15_metrics(t_fatigue_new)
d15_fat_old = compute_d15_metrics(t_fatigue_old)

print(f"\n盲区2 主线连续霸榜天数疲劳度检验:")
print(f"  * 新晋/爆发首日与次日主线 (霸榜<=2天): {len(t_fatigue_new)}笔 | 胜率 {d15_fat_new['wr_5y']}% | 盈亏比 {d15_fat_new['payoff_5y']} | 笔均 {d15_fat_new['mean_5y']:+.2f}%")
print(f"  * 连续霸榜高位接力 (霸榜>=3天):       {len(t_fatigue_old)}笔 | 胜率 {d15_fat_old['wr_5y']}% | 盈亏比 {d15_fat_old['payoff_5y']} | 笔均 {d15_fat_old['mean_5y']:+.2f}%")

# 盲区 3: 单孤立题材 vs 双题材良性轮动
daily_valid_plates_cnt = pg_m.groupby("d2_dt")["plate"].count().to_dict()
t_single_plate = []
t_multi_plate = []
for t in v16_trades:
    cnt = daily_valid_plates_cnt.get(t["buy_date"], 1)
    if cnt == 1:
        t_single_plate.append(t)
    else:
        t_multi_plate.append(t)

d15_single = compute_d15_metrics(t_single_plate)
d15_multi = compute_d15_metrics(t_multi_plate)

print(f"\n盲区3 市场题材宽度检验:")
print(f"  * 全场仅1个有效题材 (独苗主线): {len(t_single_plate)}笔 | 胜率 {d15_single['wr_5y']}% | 笔均 {d15_single['mean_5y']:+.2f}%")
print(f"  * 全场有>=2个有效题材 (良性竞争): {len(t_multi_plate)}笔 | 胜率 {d15_multi['wr_5y']}% | 笔均 {d15_multi['mean_5y']:+.2f}%")

# ------------------------------------------------------------------------------
# 8. 综合输出 JSON 与报告落盘
# ------------------------------------------------------------------------------
all_output_data = {
    "timestamp": datetime.datetime.now().isoformat(),
    "version": "LAB_B_THEME_STRUCTURE_V16_AUDIT",
    "v16_baseline": d15_v16,
    "module1_ablation": module1_results,
    "module2_scenario_a": {
        "dom_days_cnt": len(dom_days),
        "dom_no_dragon_cnt": len(dom_no_dragon),
        "a1_1_turnover_dragon_relax290": d15_a1_1,
        "a1_2_turnover_runner_up": d15_a1_2,
        "a2_trades_t2_on_dom": d15_t2_on_dom,
        "a2_trades_t3_on_dom": d15_t3_on_dom,
        "opt_a_block_t3_on_dom": d15_opt_block_t3,
    },
    "module3_scenario_b": {
        "melee_days_cnt": len(melee_days),
        "single_dom_days_cnt": len(single_dom_days),
        "trades_in_melee": d15_melee,
        "trades_in_dom": d15_dom,
        "trades_in_other": d15_other,
        "opt_b_melee_breakout": d15_opt_melee,
    },
    "module4_scenario_c": {
        "c1_diverge_weak": d15_div_weak,
        "c1_diverge_strong": d15_div_strong,
        "c2_fatigue_new": d15_fat_new,
        "c2_fatigue_old": d15_fat_old,
        "c3_single_plate": d15_single,
        "c3_multi_plate": d15_multi,
    }
}

# Remove unpicklable rot_trades before json dump
def clean_for_json(obj):
    if isinstance(obj, dict):
        return {k: clean_for_json(v) for k, v in obj.items() if k != "rot_trades"}
    elif isinstance(obj, list):
        return [clean_for_json(x) for x in obj]
    elif isinstance(obj, (np.int64, np.int32)):
        return int(obj)
    elif isinstance(obj, (np.float64, np.float32)):
        return float(obj)
    return obj

with open(OUT_JSON, "w", encoding="utf-8") as f:
    json.dump(clean_for_json(all_output_data), f, ensure_ascii=False, indent=2)

print(f"\n✅ 课题二回测矩阵数据已成功落盘至: {OUT_JSON}")

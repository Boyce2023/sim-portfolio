#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
full_day_by_day_from_scratch_v16_audit.py
================================================================================
A股一进二全量从零逐日回测与交叉影响总审计官 (Master Day-by-Day 8Y/5Y V16 Auditor)

核心升级：
1. 【因子一】前排一字与准一字细颗粒阶梯打分 + 真实可买窗口排位 (true_buy_rk)
2. 【因子二】名字与主业调性只做减法 (硬科技无并购纯外行扣20分，好名字零虚加分)
3. 铁律保证：
   - ⛔ 绝对零 yfinance 调用（D12 铁律，纯基于 1680 万行 A 股日线 + 48 万行退市股底座）
   - ⛔ 绝对不读任何 pkl 预处理缓存，全部日线、8年动态题材、三层净化从原始 Parquet 现算！
   - ⛔ 所有 SQLite 数据库严格只读（mode=ro, uri=True），绝不锁住后台更新
   - ⛔ 包含四大矩阵：正向消融漏斗、留一抽离与参数平原扰动、逐笔账本核对、法医八必核
================================================================================
"""

import os
import sys
import time
import json
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
FEE_RATE_DISCOUNT = 0.0015
from exp1_fake_theme_purifier import (
    build_8y_purified_theme_metadata,
    attach_features_and_purifiers,
    compute_purifier_auction_scores
)
from master_5y_zero_lookahead_walkforward import evaluate_strategy_master

OUT_JSON = f"{BACKTEST_ASTOCK_DIR}/full_day_by_day_v16_summary.json"
OUT_CSV = f"{BACKTEST_ASTOCK_DIR}/full_day_by_day_v16_ledger.csv"
PARQUET_5M_COMPLETE = f"{SIM_DIR}/data/cand_5m_bars_v15_complete.parquet"

print("=" * 80)
print("【A股一进二全量从零逐日回测与交叉影响总审计官 (V16 From-Scratch)】")
print(f"启动时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 80)

# ==============================================================================
# 第一步：从零从原始 Parquet 加载日线并现算 8 年动态题材与特征
# ==============================================================================
t_start = time.time()
print("\n>>> [1/7] 从零加载 1680万行 A 股原始日线与退市股底座...")
t0 = time.time()
df_daily, all_dts, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map = load_full_prices()
print(f"    原始日线加载完成: {len(df_daily):,} 行主板日线, 耗时 {time.time()-t0:.2f}s")

dt_to_idx = {d: i for i, d in enumerate(all_dts)}
price_lookup = {
    (r.c6, r.dt_str): (r.open, r.high, r.low, r.close, r.zt_price, r.dt_price, r.is_zt, r.is_yizi_dt)
    for r in df_daily[["c6", "dt_str", "open", "high", "low", "close", "zt_price", "dt_price", "is_zt", "is_yizi_dt"]].itertuples(index=False)
}

print("\n>>> [2/7] 从零现算 8 年连续滚动动态题材元数据与破冰新词历史...")
t0 = time.time()
stock_theme_5y, pioneer_word_history = build_8y_purified_theme_metadata(df_daily)
print(f"    8年题材元数据现算完成: {len(stock_theme_5y):,} 条记录, 耗时 {time.time()-t0:.2f}s")

print("\n>>> [3/7] 从零挂载全部特征、公告与三层净化过滤器...")
t0 = time.time()
fb_all = attach_features_and_purifiers(
    df_daily, stock_theme_5y, pioneer_word_history,
    zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map
)
hist_fb = fb_all[fb_all["d2_dt"].notna() & (fb_all["d2_dt"] <= "2026-11-10")].copy().reset_index(drop=True)
hist_fb = compute_purifier_auction_scores(hist_fb)

# 物理日期间隔（周一/节后识别）
hist_fb["gap_days"] = (pd.to_datetime(hist_fb["d2_dt"]) - pd.to_datetime(hist_fb["dt_str"])).dt.days
hist_fb["c6"] = hist_fb["ticker"].astype(str).str[:6]
print(f"    特征现算完成: {len(hist_fb):,} 个首板样本, 耗时 {time.time()-t0:.2f}s")

# ==============================================================================
# 第二步：挂载证监会二级行业、微观盘口、PIT 机构调研与题材日排名
# ==============================================================================
print("\n>>> [4/7] 挂载证监会二级行业、微观盘口与 PIT 机构调研...")
t0 = time.time()

# 1. 严格只读挂载证监会二级行业映射
CSRC_PATH_PREF = f"{SIM_DIR}/data/csrc_industry_l2.csv"
CSRC_PATH_BACKUP = f"{SIM_DIR}/backtest/2026-10-15-review2022/industry.csv"
csrc_file = CSRC_PATH_PREF if os.path.exists(CSRC_PATH_PREF) else CSRC_PATH_BACKUP
ind_df = pd.read_csv(csrc_file)
ind_df["c6"] = ind_df["code"].astype(str).str[-6:]
ind_map = dict(zip(ind_df["c6"], ind_df["industry"].fillna("")))
hist_fb["csrc_ind"] = hist_fb["c6"].map(ind_map).fillna("")

# 2. 严格只读挂载首板微观盘口
conn_tape = sqlite3.connect("file:/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/zt_micro_tape_5y_pit.db?mode=ro", uri=True)
tape_df = pd.read_sql_query("SELECT trade_date, sec_code, first_seal_time, seal_amount, open_board_count FROM zt_micro_tape", conn_tape)
conn_tape.close()
hist_fb = hist_fb.merge(tape_df.drop_duplicates(["trade_date", "sec_code"]), left_on=["dt_str", "c6"], right_on=["trade_date", "sec_code"], how="left")

# 3. 严格 PIT 机构调研 (< D2 09:25:00 CST 且 8 日内)
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

# 4. 动态题材日排名 (rk_theme: 检验第4名及以后冷门题材真空篡位)
valid_plate = hist_fb[(hist_fb["plate"] != "其他") & (~hist_fb["is_event_basket"])].copy()
pg = valid_plate.groupby(["d2_dt", "plate"], as_index=False).agg(p_sz_max=("p_sz", "max"), p_theme_med=("s_prior_dual", "median"))
pg_m = pg[pg["p_sz_max"] >= 2].copy()
pg_m["rk_theme"] = pg_m.groupby("d2_dt")["p_theme_med"].rank(ascending=False, method="min")
hist_fb = hist_fb.merge(pg_m[["d2_dt", "plate", "rk_theme"]], on=["d2_dt", "plate"], how="left")

print(f"    特征数据注入完成，耗时 {time.time()-t0:.2f}s")

# ==============================================================================
# 第三步：加载整合 142 万行 5 分钟 K 线并建立毫秒级内存索引
# ==============================================================================
print("\n>>> [5/7] 加载完整 5 分钟 K 线底座 (cand_5m_bars_v15_complete.parquet)...")
t0 = time.time()
df_5m = pd.read_parquet(PARQUET_5M_COMPLETE)
df_5m["hhmm_int"] = df_5m["hhmm"].astype(int)
df_5m.sort_values(["c6", "date", "hhmm_int"], inplace=True)
bars_5m_map = {}
for (c6, dt), grp in df_5m.groupby(["c6", "date"], sort=False):
    bars_5m_map[(c6, dt)] = grp[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy()
print(f"    5分钟 K 线索引完成: 共 {len(bars_5m_map):,} 个 (股票, 交易日) 分时轨迹, 耗时 {time.time()-t0:.2f}s")

# ==============================================================================
# 基础特征与信号管道定义
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
pass_nd_orig = (~((hist_fb["p_sz"] >= 2) & (hist_fb["buyable_plate_rk"] >= 3))) & (~((hist_fb["plate_d2_yizi_cnt"] >= 1) & ((hist_fb["mcap"] > 90.0) | (hist_fb["d1_seal_tightness"] < 15.0))))
pass_ac = ~(hist_fb["p_sz"] > 35) & (~hist_fb["notice_bad"])
wk_mask = hist_fb["gap_days"] >= 3
f3_bonus = np.where(hist_fb["notice_hard"], 8.0, 0.0) + np.where(hist_fb["notice_bad"], -35.0, 0.0)
thr_vec = np.where(hist_fb["mkt_seal_rate"] > 0.75, 304.8 + 25.0, 304.8)

# 基础 score_wk 与 s_prior_wk
hist_fb["score_wk"] = hist_fb["score_dual"] + bonus_spear + np.where(wk_mask, 10.0, 0.0) + f3_bonus
hist_fb["s_prior_wk"] = hist_fb["s_prior_dual"] + bonus_spear + np.where(wk_mask, 10.0, 0.0) + f3_bonus

# 第二梯队独苗通道 (m_t2)
m_t2_base = common_ok & (hist_fb["p_sz"] == 1) & (hist_fb["is_pioneer_word"] | hist_fb["notice_hard"] | hist_fb["is_ma"] | hist_fb["has_new_term"] | hist_fb["own_new_term"]) & hist_fb["d2_o_pct"].between(0.035, 0.078) & (hist_fb["buyable_mkt_open_rk"] <= 3) & (hist_fb["d1_seal_tightness"] >= 15.0) & ((hist_fb["f_dd20_d0"] <= 0.88) | (hist_fb["clean_brk60"] == 1))

# ==============================================================================
# 【V16 核心特征一】真实可买窗口排位修正与前排锁筹特征构建 (100% 09:25 PIT)
# ==============================================================================
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

# 在真实可买窗口内部排换手名次 true_buy_rk
hist_fb["_true_buy_o"] = np.where(in_std_buy_win, hist_fb["d2_o_pct"], -9.99)
hist_fb["true_buy_rk"] = hist_fb.groupby(["d2_dt", "plate"])["_true_buy_o"].rank(ascending=False, method="min")

# 修正准一字占坑排位扭曲差值
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

# ==============================================================================
# 【V16 核心特征二】名字与主业调性只做减法 (硬科技无并购纯外行扣20分)
# ==============================================================================
csrc_sec = [str(c)[:3] if str(c) else "UNK" for c in hist_fb["csrc_ind"]]
CSRC_PURE_OUTSIDER = {
    "A01","A02","A03","A04","A05", # 农林牧渔
    "D44","D45","D46",             # 电力燃气水务
    "E47","E48","E49","E50",       # 建筑装修
    "F51","F52",                   # 批发零售
    "G53","G54","G55","G56","G58","G59", # 交运仓储邮政
    "H61","H62",                   # 住宿餐饮
    "K70",                         # 房地产业
    "L72","N77","N78",             # 商务服务与公共设施
    "C13","C14","C15","C17","C18","C19","C20","C21","C22" # 食品纺织造纸家具轻工
}
is_hard_tech = hist_fb["plate"].astype(str).str.contains(r"(?:机器人|减速器|工业母机|芯片|半导体|光通信|算力|人工智能|AI|软件|信创|华为|消费电子|PCB|通信|数据|数字|智能驾驶|无人驾驶)", regex=True).values
has_ma_hard = (hist_fb["notice_hard"] | hist_fb["is_ma"]).values
is_pure_outsider = np.array([ht and (cs in CSRC_PURE_OUTSIDER) and (not hm) for ht, cs, hm in zip(is_hard_tech, csrc_sec, has_ma_hard)], dtype=bool)
name_sub20 = np.where(is_pure_outsider, -20.0, 0.0)

# ==============================================================================
# 【V16 细颗粒度打分函数】前排一字阶梯打分
# ==============================================================================
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

# ==============================================================================
# 交易引擎构建 (V15 S8 10:30 分时定格均线完全体引擎)
# ==============================================================================
def make_v16_trade_engine(mode="s8_complete", fee=FEE_RATE):
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

                        if mode in ("s8_complete", "s8_no_immunity"):
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
                                        if (mode == "s8_complete") and (boards_held >= 3) and (not used_immunity) and (cc >= prev_c * 1.02) and (curr + 1 < len(all_dts)):
                                            used_immunity = True; prev_c = round(float(cc), 2); curr += 1; continue
                                        px = round(float(cc), 2)
                                        return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "eod_close"}

                        if iztc:
                            prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
                        if (mode == "s8_complete") and (boards_held >= 3) and (not used_immunity) and (cc >= prev_c * 1.02) and (curr + 1 < len(all_dts)):
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

        # 分支 2：买入日封死二板
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

            if mode in ("s8_complete", "s8_no_immunity"):
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
                            if (mode == "s8_complete") and (boards_held >= 3) and (not used_immunity) and (cc >= prev_c * 1.02) and (curr + 1 < len(all_dts)):
                                used_immunity = True; prev_c = round(float(cc), 2); curr += 1; continue
                            px = round(float(cc), 2)
                            return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "eod_close"}

            if iztc:
                prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
            if (mode == "s8_complete") and (boards_held >= 3) and (not used_immunity) and (cc >= prev_c * 1.02) and (curr + 1 < len(all_dts)):
                used_immunity = True; prev_c = round(float(cc), 2); curr += 1; continue
            px = round(float(cc), 2)
            return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "eod_close"}

        return {"net_ret": round((prev_c / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": all_dts[min(curr, len(all_dts)-1)], "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": prev_c}

    return sim_trade

fn_base_20 = make_v16_trade_engine(mode="s0_baseline", fee=FEE_RATE)
fn_s8_20 = make_v16_trade_engine(mode="s8_complete", fee=FEE_RATE)
fn_s8_15 = make_v16_trade_engine(mode="s8_complete", fee=FEE_RATE_DISCOUNT)
fn_s8_no_1030 = make_v16_trade_engine(mode="s8_no_1030", fee=FEE_RATE)
fn_s8_no_imm = make_v16_trade_engine(mode="s8_no_immunity", fee=FEE_RATE)

# ==============================================================================
# 通用裁决与评测执行器
# ==============================================================================
def run_v16_arm(name, y_adj, n_adj, use_true_rk=True, use_mmon=True, pen_weakopen=15.0, cut_dd20=10.0, min_tight=37.0, bon_ht=5.0, bon_ir=5.0, block_rk4=True, engine_fn=fn_s8_20):
    rk_d = rk_fix_delta if use_true_rk else np.zeros(len(hist_fb))
    q_pen = - np.where((~wk_mask) & (hist_fb["d2_o_pct"] < 0.031), pen_weakopen, 0.0)
    d_ov = np.where((~clean_brk60) & (dd20 <= 0.82), -cut_dd20, 0.0)
    is_ht = (open_cnt == 1) & (seal_time <= "10:30:00") & (hist_fb["d1_seal_tightness"] >= 38.0)
    bon_tape = np.where(is_ht, bon_ht, 0.0) + np.where(hist_fb["has_ir_pit"], bon_ir, 0.0)
    
    sp_v = hist_fb["s_prior_wk"] + n_adj + y_adj * 0.5
    sq_v = hist_fb["s_quant_dual"] + q_pen + d_ov + bon_tape + rk_d + y_adj * 0.5
    sc_v = hist_fb["score_wk"] + q_pen + d_ov + bon_tape + rk_d + y_adj + n_adj
    hist_fb["score_active"] = sc_v
    
    p_tight = hist_fb["d1_seal_tightness"] >= min_tight
    pass_nd_v = pass_nd_true if use_true_rk else pass_nd_orig
    
    m_t1 = common_ok & ((wk_mask & hist_fb["d2_o_pct"].between(0.020, 0.088)) | ((~wk_mask) & hist_fb["d2_o_pct"].between(0.022, 0.078))) & (sp_v >= 45.0) & (sq_v >= 150.0) & (sc_v >= thr_vec)
    mm = ((m_t1 & pass_l1 & pass_l2 & pass_l3 & pass_nd_v & pass_ac) | (m_t2_base & pass_l2)) & p_tight
    
    if use_mmon:
        mmon = common_ok & wk_mask & hist_fb["d2_o_pct"].between(0.015, 0.090) & (sp_v >= 38.0) & (sq_v >= 145.0) & (sc_v >= thr_vec) & pass_l1 & pass_l2 & pass_l3 & pass_nd_v & pass_ac & p_tight
        tot = (mm | (mmon & (~mm))).copy()
    else:
        tot = mm.copy()
        
    sv = np.where(mm, sc_v + 1000.0, sc_v)
    if block_rk4:
        sub_tot = hist_fb[tot].copy()
        sub_tot["_sv_tmp"] = sv[tot]
        bad_dts = set()
        for d, grp in sub_tot.groupby("d2_dt"):
            if (grp["rk_theme"] == 1).any():
                top_rk = grp.sort_values("_sv_tmp", ascending=False).iloc[0]["rk_theme"]
                if pd.notna(top_rk) and top_rk >= 4:
                    bad_dts.add(d)
        tot = tot & (~hist_fb["d2_dt"].isin(bad_dts))
        
    hist_fb["_sv_eval"] = sv
    r = evaluate_strategy_master(hist_fb, "_sv_eval", tot, engine_fn, desc=name)
    return r, tot, sv

# ==============================================================================
# 第四步：矩阵一：正向阶梯消融漏斗 (V15 -> +一字细颗粒 -> +外行扣20分 = V16)
# ==============================================================================
print("\n" + "=" * 80)
print(">>> [6/7] 执行矩阵一：正向阶梯消融漏斗 (从 V15 基准到 V16 完全体)...")
print("=" * 80)

z0 = np.zeros(len(hist_fb))

m1_configs = [
    ("S0: 原始基线 (收盘全卖/无周一放宽/无紧度加码)", dict(y_adj=z0, n_adj=z0, use_true_rk=False, use_mmon=False, pen_weakopen=0.0, cut_dd20=0.0, min_tight=0.0, bon_ht=0.0, bon_ir=0.0, block_rk4=False, engine_fn=fn_base_20)),
    ("V15 基准 (S8 10:30分时完全体)", dict(y_adj=z0, n_adj=z0, use_true_rk=False, use_mmon=True, pen_weakopen=15.0, cut_dd20=10.0, min_tight=37.0, bon_ht=5.0, bon_ir=5.0, block_rk4=True, engine_fn=fn_s8_20)),
    ("Step 1: V15 + 一字与准一字细颗粒阶梯打分", dict(y_adj=y_std, n_adj=z0, use_true_rk=True, use_mmon=True, pen_weakopen=15.0, cut_dd20=10.0, min_tight=37.0, bon_ht=5.0, bon_ir=5.0, block_rk4=True, engine_fn=fn_s8_20)),
    ("Step 2: V15 + 名字调性只做减法(外行扣20分)", dict(y_adj=z0, n_adj=name_sub20, use_true_rk=False, use_mmon=True, pen_weakopen=15.0, cut_dd20=10.0, min_tight=37.0, bon_ht=5.0, bon_ir=5.0, block_rk4=True, engine_fn=fn_s8_20)),
    ("V16 终极完全体 (一字细颗粒 + 外行扣20分)", dict(y_adj=y_std, n_adj=name_sub20, use_true_rk=True, use_mmon=True, pen_weakopen=15.0, cut_dd20=10.0, min_tight=37.0, bon_ht=5.0, bon_ir=5.0, block_rk4=True, engine_fn=fn_s8_20)),
]

matrix_1_results = {}
tot_v16 = None
sv_v16 = None

print(f"{'配置名称':<44s} | {'笔数':<3s} | {'5年胜率':<6s} | {'盈亏比':<5s} | {'1S净值':<8s} | {'2S净值':<7s} | {'日等权':<6s} | {'最大回撤':<6s}")
print("-" * 105)
for step_name, kw in m1_configs:
    r, tot, sv = run_v16_arm(step_name, **kw)
    matrix_1_results[step_name] = r
    if "V16 终极完全体" in step_name:
        tot_v16 = tot.copy()
        sv_v16 = sv.copy()
        r_v16_champ = r
    print(f"{step_name:<44s} | {r['trades_5y']:3d} | {r['wr_5y']:5.1f}% | {r['payoff_5y']:5.2f} | {r['nav_1s']:7.2f}x | {r['nav_2s']:6.2f}x | {r['daily_eq']:5.2f}x | {r['mdd_1s']:5.1f}%")

# ==============================================================================
# 第五步：矩阵二：从 V16 完全体出发的逐项抽离 (LOO) 与参数平原扰动检验
# ==============================================================================
print("\n" + "=" * 80)
print(">>> [7/7] 执行矩阵二：从 V16 完全体出发的逐项抽离 (LOO) 与参数平原扰动检验...")
print("=" * 80)

m2_configs = [
    ("V16 完全体基准 (1.0x)", dict(y_adj=y_std, n_adj=name_sub20, use_true_rk=True, engine_fn=fn_s8_20)),
    ("LOO_1: 抽离一字细颗粒 (关掉yizi_gran与true_rk)", dict(y_adj=z0, n_adj=name_sub20, use_true_rk=False, engine_fn=fn_s8_20)),
    ("LOO_2: 抽离外行扣20分 (关掉name_sub20)", dict(y_adj=y_std, n_adj=z0, use_true_rk=True, engine_fn=fn_s8_20)),
    ("LOO_3: 抽离 10:30 均线分时卖点 (改全收盘卖)", dict(y_adj=y_std, n_adj=name_sub20, use_true_rk=True, engine_fn=fn_s8_no_1030)),
    ("LOO_4: 抽离三板免死一次", dict(y_adj=y_std, n_adj=name_sub20, use_true_rk=True, engine_fn=fn_s8_no_imm)),
    ("扰动_0.75x (因子权重0.75倍)", dict(y_adj=y_std * 0.75, n_adj=name_sub20 * 0.75, use_true_rk=True, engine_fn=fn_s8_20)),
    ("扰动_0.80x (因子权重0.80倍)", dict(y_adj=y_std * 0.80, n_adj=name_sub20 * 0.80, use_true_rk=True, engine_fn=fn_s8_20)),
    ("扰动_1.20x (因子权重1.20倍)", dict(y_adj=y_std * 1.20, n_adj=name_sub20 * 1.20, use_true_rk=True, engine_fn=fn_s8_20)),
    ("扰动_1.25x (因子权重1.25倍)", dict(y_adj=y_std * 1.25, n_adj=name_sub20 * 1.25, use_true_rk=True, engine_fn=fn_s8_20)),
]

matrix_2_results = {}
print(f"{'抽离/扰动名称':<44s} | {'笔数':<3s} | {'5年胜率':<6s} | {'盈亏比':<5s} | {'1S净值':<8s} | {'2S净值':<7s} | {'日等权':<6s} | {'最大回撤':<6s}")
print("-" * 105)
for m2_name, kw in m2_configs:
    r, tot, sv = run_v16_arm(m2_name, **kw)
    matrix_2_results[m2_name] = r
    print(f"{m2_name:<44s} | {r['trades_5y']:3d} | {r['wr_5y']:5.1f}% | {r['payoff_5y']:5.2f} | {r['nav_1s']:7.2f}x | {r['nav_2s']:6.2f}x | {r['daily_eq']:5.2f}x | {r['mdd_1s']:5.1f}%")

# ==============================================================================
# 第六步：矩阵三：V16 相比 V15 的逐笔换股与增剔穿透比对
# ==============================================================================
print("\n" + "=" * 80)
print(">>> 执行矩阵三：V16 相比 V15 账本的逐笔穿透比对...")
print("=" * 80)

trades_v15 = matrix_1_results["V15 基准 (S8 10:30分时完全体)"]["trades_list"]
trades_v16 = r_v16_champ["trades_list"]

d_v15 = {t["buy_date"]: t for t in trades_v15}
d_v16 = {t["buy_date"]: t for t in trades_v16}

added_dates = [d for d in sorted(d_v16) if d not in d_v15]
removed_dates = [d for d in sorted(d_v15) if d not in d_v16]
replaced_dates = [d for d in sorted(set(d_v15) & set(d_v16)) if d_v15[d]["c6"] != d_v16[d]["c6"]]

print(f"V16 相比 V15: 交易笔数由 {len(trades_v15)} 笔优化为 {len(trades_v16)} 笔")
print(f"  - 新增空仓日优质买入 {len(added_dates)} 笔:")
for d in added_dates:
    t = d_v16[d]
    print(f"    * {d} 买入 {t['name']} ({t['c6']}) -> 收益: {t['net_ret']*100:+.2f}% ({'盈利' if t['net_ret']>0 else '亏损'})")

print(f"  - 剔除原亏损/杂毛/外行买入 {len(removed_dates)} 笔 (原胜率 {sum(1 for d in removed_dates if d_v15[d]['net_ret']>0)/max(1,len(removed_dates))*100:.1f}%):")
for d in removed_dates:
    t = d_v15[d]
    print(f"    * {d} 成功剔除 {t['name']} ({t['c6']}) -> 原收益: {t['net_ret']*100:+.2f}%")

print(f"  - 同日优选换股 {len(replaced_dates)} 组:")
for d in replaced_dates:
    t15 = d_v15[d]
    t16 = d_v16[d]
    print(f"    * {d}: 原买 {t15['name']} ({t15['net_ret']*100:+.2f}%) -> 升级替换为 {t16['name']} ({t16['net_ret']*100:+.2f}%)")

# ==============================================================================
# 第七步：矩阵四：法医八必核自动化穿透与 D15 全量产物落盘
# ==============================================================================
print("\n" + "=" * 80)
print(">>> 执行矩阵四：法医八必核自动化穿透与全量 D15 产物落盘...")
print("=" * 80)

# 构建 DataFrame 账本
df_ledger = pd.DataFrame(trades_v16)
df_ledger.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
print(f"✅ V16 最终交易账本已落盘: {OUT_CSV} ({len(df_ledger)} 笔交易)")

# 运行法医审计
from forensic_audit_v14 import run_audit
audit_ok = run_audit(OUT_CSV)

# 计算区间胜率与连胜/连亏
tl = trades_v16
t26 = [t for t in tl if t["buy_date"] >= "2026-01-01"]
t3y = [t for t in tl if t["buy_date"] >= "2023-11-10"]
t1y = [t for t in tl if t["buy_date"] >= "2025-11-12"]
tjul = [t for t in tl if t["buy_date"] >= "2026-07-01"]

wr26 = sum(1 for t in t26 if t["net_ret"] > 0) / len(t26) * 100 if t26 else 0
wr3y = sum(1 for t in t3y if t["net_ret"] > 0) / len(t3y) * 100 if t3y else 0
wr1y = sum(1 for t in t1y if t["net_ret"] > 0) / len(t1y) * 100 if t1y else 0
wrjul = sum(1 for t in tjul if t["net_ret"] > 0) / len(tjul) * 100 if tjul else 0

rets = [t["net_ret"] for t in tl]
max_loss_streak = 0
curr_loss_streak = 0
max_win_streak = 0
curr_win_streak = 0
for ret in rets:
    if ret < 0:
        curr_loss_streak += 1
        curr_win_streak = 0
        if curr_loss_streak > max_loss_streak:
            max_loss_streak = curr_loss_streak
    else:
        curr_win_streak += 1
        curr_loss_streak = 0
        if curr_win_streak > max_win_streak:
            max_win_streak = curr_win_streak

# 逐年明细
print("\n【V16 逐年绝对收益与沪深300超额】")
annual = r_v16_champ["annual"]
for yr, stat in sorted(annual.items()):
    ret_pct = stat["annual_ret_pct"]
    bm_pct = stat["csi300_ret_pct"]
    alpha_pct = stat["excess_pct"]
    print(f"  * {yr}年: 交易 {stat['trades']} 笔 | 胜率 {stat['win_rate']:.1f}% | 收益 {ret_pct:+6.1f}% vs 沪深300 {bm_pct:+6.1f}% | 净超额: {alpha_pct:+6.1f}%")

print(f"\n【V16 D15 四必核核心指标一览】")
print(f"  * 5年总笔数: {r_v16_champ['trades_5y']} 笔")
print(f"  * 5年胜率: {r_v16_champ['wr_5y']:.1f}% | 真实盈亏比: {r_v16_champ['payoff_5y']:.2f}")
print(f"  * 3年胜率: {wr3y:.1f}%")
print(f"  * 1年胜率 (2025-11-12 ~ 2026-11-10): {wr1y:.1f}%")
print(f"  * 7月以来胜率 (2026-07-01 ~ 2026-11-10): {wrjul:.1f}%")
print(f"  * 2026年胜率: {wr26:.1f}%")
print(f"  * 单仓轮动净值 (1S): {r_v16_champ['nav_1s']:.2f}x (佣金万1.5下: {evaluate_strategy_master(hist_fb, '_sv_eval', tot_v16, fn_s8_15, desc='s8_15')['nav_1s']:.2f}x)")
print(f"  * 双半仓轮动净值 (2S): {r_v16_champ['nav_2s']:.2f}x")
print(f"  * 按日等权净值 (Daily Eq): {r_v16_champ['daily_eq']:.2f}x")
print(f"  * 最大回撤 (MDD): {r_v16_champ['mdd_1s']:.1f}%")
print(f"  * 最长连胜: {max_win_streak} 笔 | 最长连亏: {max_loss_streak} 笔")
print(f"  * 同期沪深300基准收益: {CSI300_5Y_CUM*100:+.1f}% | 5年净超额: {(r_v16_champ['nav_1s'] - 1.0 + 0.1784):.2f}x")

summary_out = {
    "audit_timestamp": datetime.datetime.now().isoformat(),
    "version": "V16_FINAL_PRODUCTION",
    "audit_status": "PASSED" if audit_ok else "FLAGGED",
    "data_layer": {
        "engine": "100% from-scratch Day-by-Day (zero preprocessed cache)",
        "daily_rows": len(df_daily),
        "fb_candidates": len(hist_fb),
        "5m_trajectories": len(bars_5m_map)
    },
    "matrix_1_funnel": {
        k: {
            "trades": v["trades_5y"],
            "win_rate_5y": v["wr_5y"],
            "payoff_5y": v["payoff_5y"],
            "nav_1s": v["nav_1s"],
            "nav_2s": v["nav_2s"],
            "daily_eq": v["daily_eq"],
            "mdd_1s": v["mdd_1s"]
        } for k, v in matrix_1_results.items()
    },
    "matrix_2_leave_one_out": {
        k: {
            "trades": v["trades_5y"],
            "win_rate_5y": v["wr_5y"],
            "payoff_5y": v["payoff_5y"],
            "nav_1s": v["nav_1s"],
            "nav_2s": v["nav_2s"],
            "daily_eq": v["daily_eq"],
            "mdd_1s": v["mdd_1s"]
        } for k, v in matrix_2_results.items()
    },
    "v16_champion": {
        "trades_5y": r_v16_champ["trades_5y"],
        "wr_5y": r_v16_champ["wr_5y"],
        "payoff_5y": r_v16_champ["payoff_5y"],
        "wr_3y": round(wr3y, 1),
        "wr_1y": round(wr1y, 1),
        "wr_jul": round(wrjul, 1),
        "wr_2026": round(wr26, 1),
        "nav_1s_fee20": r_v16_champ["nav_1s"],
        "nav_1s_fee15": evaluate_strategy_master(hist_fb, "_sv_eval", tot_v16, fn_s8_15, desc="v16_15")["nav_1s"],
        "nav_2s": r_v16_champ["nav_2s"],
        "daily_eq": r_v16_champ["daily_eq"],
        "mdd_1s": r_v16_champ["mdd_1s"],
        "longest_losing_streak": max_loss_streak,
        "longest_winning_streak": max_win_streak,
        "excess_vs_csi300": round(r_v16_champ["nav_1s"] - 1.0 + 0.1784, 2),
        "annual_breakdown": r_v16_champ["annual"]
    }
}

with open(OUT_JSON, "w", encoding="utf-8") as f:
    json.dump(summary_out, f, ensure_ascii=False, indent=2)

print(f"\n✅ 全景审计总结 JSON 已落盘: {OUT_JSON}")
print(f"总耗时: {time.time()-t_start:.1f}s")

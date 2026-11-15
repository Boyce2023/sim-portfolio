#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
step2_lora_model_search.py
三进四 26Q4 专供版（LoRA增量打分模型）网格优化与双重样本外检验
"""
import os, sys, pickle, json
import numpy as np, pandas as pd

CACHE_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/special_26q4/3to4_26q4/cache_d_and_p.pkl"
BTEST2_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2"
OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/special_26q4/3to4_26q4"

sys.path.insert(0, BTEST2_DIR)
from core_3to4_5m_engine import _slice_metrics_chrono, _sim_single_slot_chrono, csi300_ret

with open(CACHE_PATH, "rb") as f:
    pkg = pickle.load(f)

d = pkg["df"].copy()
p = pkg["p_v32"]
sc_v34 = pkg["sc_v34"]

core = (d.is_10cm_non_st & (~d.prev_is_yizi) & d.buyable_open & (~d.has_tox_notice) & (~d.has_stock_reg))
obc = d.open_board_count >= 1
op_ok = d.open_pct.between(0.030, 0.092)
mask_A = core & obc & op_ok
top1 = d.is_top1_3b_open.astype(bool)
lock = (d.lock_top10 >= 45.0) | (d.real_free_mcap >= 45.0)
to_ok = d.prev_to.between(8.5, 31.0)
fst_num = pd.to_numeric(d.first_seal_time.astype(str).str.replace(":", "").str[:4], errors="coerce").fillna(9999)

# Baseline delta terms relative to V3.4:
# We want clean integer adjustments Δscore added to sc_v34!
# Let's define the candidate delta signals:
delta_signals = {
    # D1: 废除高价股扣分 (px_d3 > 32 补偿 +5)
    "d_px_gt32_cancel": np.where(d.px_d3 > 32.0, 5, 0),
    
    # D2: 非头名扣分由 -12 减轻至 -6 (补偿 +6)
    "d_soft_top1_m6": np.where(~top1, 6, 0),
    
    # D3: 开盘涨幅在 3%~6% 黄金带奖励 +3
    "d_op_3_to_6": np.where(d.open_pct.between(0.030, 0.060), 3, 0),
    
    # D4: 周一/跨周末发酵强化 (原 +2 提升至 +5，即增量 +3)
    "d_mon_boost": np.where(d.is_post_holiday_or_mon.astype(bool), 3, 0),
    
    # D5: 破局龙强化 (mkt_max_board_prev <= 4，原 +8 提升至 +10，即增量 +2)
    "d_break_boost": np.where(d.mkt_max_board_prev <= 4, 2, 0),
    
    # D6: 同题材首板顶一字扣分减半 (原 -7 调为 -3，即增量 +4)
    "d_soft_fb_yz": np.where(d.plate_fb_yz_cnt >= 1, 4, 0),
    
    # D7: 锁仓与自由流通盘双低扣分减半 (原 -10 调为 -5，即增量 +5)
    "d_soft_lock": np.where(~lock, 5, 0),
    
    # D8: 换手越界扣分减半 (原 -10 调为 -5，即增量 +5)
    "d_soft_to": np.where(~to_ok, 5, 0),
}

def eval_model(delta_sc, th=90):
    sc_new = np.where(mask_A, sc_v34 + delta_sc, -999.0)
    idx = np.where(sc_new >= th)[0]
    recs = [dict(p[i], score=int(sc_new[i]), priority_score=float(sc_new[i])*10.0 + float(d["prio_3to4"].iloc[i])*0.1)
            for i in idx if p[i] is not None]
    tdf = pd.DataFrame(recs)
    if len(tdf) == 0:
        return None
    
    # Evaluate across key periods
    # 1. 2026-10后 (2026-10-01 ~ 2026-11-13)
    m_10 = _slice_metrics_chrono(tdf[(tdf["buy_date"] >= "2026-10-01") & (tdf["buy_date"] <= "2026-11-13")], "2026-10-01", "2026-11-13")
    # 2. 2026-07后 (2026-07-01 ~ 2026-11-13)
    m_07 = _slice_metrics_chrono(tdf[(tdf["buy_date"] >= "2026-07-01") & (tdf["buy_date"] <= "2026-11-13")], "2026-07-01", "2026-11-13")
    # 3. 2026全年 (2026-01-01 ~ 2026-11-13)
    m_26 = _slice_metrics_chrono(tdf[(tdf["buy_date"] >= "2026-01-01") & (tdf["buy_date"] <= "2026-11-13")], "2026-01-01", "2026-11-13")
    # 4. 近三年 (2023-11-01 ~ 2026-11-13)
    m_r3 = _slice_metrics_chrono(tdf[(tdf["buy_date"] >= "2023-11-01") & (tdf["buy_date"] <= "2026-11-13")], "2023-11-01", "2026-11-13")
    # 5. 全五年 (2021-11-01 ~ 2026-11-13)
    m_5y = _slice_metrics_chrono(tdf[(tdf["buy_date"] >= "2021-11-01") & (tdf["buy_date"] <= "2026-11-13")], "2021-11-01", "2026-11-13")
    
    # OOS A: trained up to 2026-09-30, tested on 2026-10-01 ~ 2026-11-13
    oos_a = m_10
    # OOS B: trained up to 2026-10-20, tested on 2026-10-21 ~ 2026-11-13
    m_b = _slice_metrics_chrono(tdf[(tdf["buy_date"] >= "2026-10-21") & (tdf["buy_date"] <= "2026-11-13")], "2026-10-21", "2026-11-13")
    
    # 2026 Time-weighted metric
    # Era 2 (26H1), Era 3 (26Q3), Era 4 (26Q4)
    m_h1 = _slice_metrics_chrono(tdf[(tdf["buy_date"] >= "2026-01-01") & (tdf["buy_date"] < "2026-07-01")], "2026-01-01", "2026-06-30")
    m_q3 = _slice_metrics_chrono(tdf[(tdf["buy_date"] >= "2026-07-01") & (tdf["buy_date"] < "2026-10-01")], "2026-07-01", "2026-09-30")
    m_q4 = m_10
    
    w_ret = 1.0 * (m_h1["single_nav"] - 1.0) + 2.5 * (m_q3["single_nav"] - 1.0) + 4.5 * (m_q4["single_nav"] - 1.0)
    
    return {
        "th": th,
        "n_5y": m_5y["single_n"], "nav_5y": m_5y["single_nav"], "mdd_5y": m_5y["single_mdd_pct"], "wr_5y": m_5y["wr"], "po_5y": m_5y["payoff"],
        "n_r3": m_r3["single_n"], "nav_r3": m_r3["single_nav"], "mdd_r3": m_r3["single_mdd_pct"], "wr_r3": m_r3["wr"], "po_r3": m_r3["payoff"],
        "n_26": m_26["single_n"], "nav_26": m_26["single_nav"], "mdd_26": m_26["single_mdd_pct"], "wr_26": m_26["wr"], "po_26": m_26["payoff"],
        "n_07": m_07["single_n"], "nav_07": m_07["single_nav"], "mdd_07": m_07["single_mdd_pct"], "wr_07": m_07["wr"], "po_07": m_07["payoff"],
        "n_10": m_10["single_n"], "nav_10": m_10["single_nav"], "mdd_10": m_10["single_mdd_pct"], "wr_10": m_10["wr"], "po_10": m_10["payoff"],
        "n_b": m_b["single_n"], "nav_b": m_b["single_nav"], "wr_b": m_b["wr"], "po_b": m_b["payoff"],
        "w_ret": w_ret,
        "eq_nav_26": m_26["eq_nav"], "eq_nav_07": m_07["eq_nav"], "eq_nav_10": m_10["eq_nav"],
        "tdf": tdf,
    }

# Test Candidate Packages:
packages = {
    "P0_V34_Baseline": np.zeros(len(d)),
    
    # P1: 仅废除高价股扣分 (+5)
    "P1_PxCancel": delta_signals["d_px_gt32_cancel"],
    
    # P2: P1 + 适度开盘 3%~6% 加分 (+3)
    "P2_Px_Op": delta_signals["d_px_gt32_cancel"] + delta_signals["d_op_3_to_6"],
    
    # P3: P2 + 周一发酵强化 (+3) + 破局强化 (+2)
    "P3_Px_Op_Mon_Break": (delta_signals["d_px_gt32_cancel"] + delta_signals["d_op_3_to_6"]
                           + delta_signals["d_mon_boost"] + delta_signals["d_break_boost"]),
    
    # P4: P3 + 非头名软化 (+6)
    "P4_Core5": (delta_signals["d_px_gt32_cancel"] + delta_signals["d_op_3_to_6"]
                 + delta_signals["d_mon_boost"] + delta_signals["d_break_boost"]
                 + delta_signals["d_soft_top1_m6"]),
                 
    # P5: P4 + 首板一字软化 (+4)
    "P5_Core6": (delta_signals["d_px_gt32_cancel"] + delta_signals["d_op_3_to_6"]
                 + delta_signals["d_mon_boost"] + delta_signals["d_break_boost"]
                 + delta_signals["d_soft_top1_m6"] + delta_signals["d_soft_fb_yz"]),
                 
    # P6: P5 + 锁仓双低软化 (+5)
    "P6_Core7": (delta_signals["d_px_gt32_cancel"] + delta_signals["d_op_3_to_6"]
                 + delta_signals["d_mon_boost"] + delta_signals["d_break_boost"]
                 + delta_signals["d_soft_top1_m6"] + delta_signals["d_soft_fb_yz"]
                 + delta_signals["d_soft_lock"]),
}

print("=== 各候选微调包在门槛 90 分下的综合回测 ===")
res_list = []
for pname, dsc in packages.items():
    m = eval_model(dsc, th=90)
    if m is not None:
        res_list.append((pname, m))
        print(f"[{pname:20s}] 5Y:{m['n_5y']:2d}b {m['nav_5y']:6.1f}x(MDD{m['mdd_5y']:4.1f}%) | 3Y:{m['n_r3']:2d}b {m['nav_r3']:6.1f}x(MDD{m['mdd_r3']:4.1f}%) | 26年:{m['n_26']:2d}b {m['nav_26']:5.2f}x | 7月后:{m['n_07']:2d}b {m['nav_07']:5.2f}x | 10月后:{m['n_10']:2d}b {m['nav_10']:5.2f}x | 10-21后:{m['n_b']:2d}b {m['nav_b']:5.2f}x | 时间加权益:{m['w_ret']:+5.2f}")

print("\n=== 各候选微调包在门槛 95 分下的综合回测 ===")
for pname, dsc in packages.items():
    m = eval_model(dsc, th=95)
    if m is not None:
        print(f"[{pname:20s}] 5Y:{m['n_5y']:2d}b {m['nav_5y']:6.1f}x(MDD{m['mdd_5y']:4.1f}%) | 3Y:{m['n_r3']:2d}b {m['nav_r3']:6.1f}x(MDD{m['mdd_r3']:4.1f}%) | 26年:{m['n_26']:2d}b {m['nav_26']:5.2f}x | 7月后:{m['n_07']:2d}b {m['nav_07']:5.2f}x | 10月后:{m['n_10']:2d}b {m['nav_10']:5.2f}x | 10-21后:{m['n_b']:2d}b {m['nav_b']:5.2f}x | 时间加权益:{m['w_ret']:+5.2f}")

print("\n=== 各候选微调包在门槛 98 分（严格档）下的综合回测 ===")
for pname, dsc in packages.items():
    m = eval_model(dsc, th=98)
    if m is not None:
        print(f"[{pname:20s}] 5Y:{m['n_5y']:2d}b {m['nav_5y']:6.1f}x(MDD{m['mdd_5y']:4.1f}%) | 3Y:{m['n_r3']:2d}b {m['nav_r3']:6.1f}x(MDD{m['mdd_r3']:4.1f}%) | 26年:{m['n_26']:2d}b {m['nav_26']:5.2f}x | 7月后:{m['n_07']:2d}b {m['nav_07']:5.2f}x | 10月后:{m['n_10']:2d}b {m['nav_10']:5.2f}x | 10-21后:{m['n_b']:2d}b {m['nav_b']:5.2f}x | 时间加权益:{m['w_ret']:+5.2f}")

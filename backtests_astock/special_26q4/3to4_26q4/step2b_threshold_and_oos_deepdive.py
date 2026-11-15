#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
step2b_threshold_and_oos_deepdive.py
深入扫描 26Q4 专供版门槛与样本外双重检验
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

# Let's formulate the 26Q4 LoRA micro-tuning package (clean, integer adjustments):
# Item 1: 废除高价股扣5分 (26H2高流动性科技龙脱敏) -> +5分
# Item 2: 竞价开盘涨幅 3.0%~6.0% 换手黄金带 -> +3分
# Item 3: 周一/长假后跨周末发酵强化 -> +3分 (原+2提至+5)
# Item 4: 最高连板<=4板空间破局强化 -> +2分 (原+8提至+10)
# Item 5: 非竞价头名次名软化 -> +6分 (原-12减至-6)
# Item 6: 同题材首板顶一字软化 -> +4分 (原-7减至-3)

delta_26q4 = (
    np.where(d.px_d3 > 32.0, 5, 0)
    + np.where(d.open_pct.between(0.030, 0.060), 3, 0)
    + np.where(d.is_post_holiday_or_mon.astype(bool), 3, 0)
    + np.where(d.mkt_max_board_prev <= 4, 2, 0)
    + np.where(~top1, 6, 0)
    + np.where(d.plate_fb_yz_cnt >= 1, 4, 0)
)

sc_26q4 = np.where(mask_A, sc_v34 + delta_26q4, -999.0)

# Threshold scan
print("=== 26Q4 专供版打分门槛扫描 ===")
for th in [90, 92, 94, 95, 96, 98, 100, 102]:
    idx = np.where(sc_26q4 >= th)[0]
    recs = [dict(p[i], score=int(sc_26q4[i]), priority_score=float(sc_26q4[i])*10.0 + float(d["prio_3to4"].iloc[i])*0.1)
            for i in idx if p[i] is not None]
    tdf = pd.DataFrame(recs)
    if len(tdf) == 0: continue
    
    m_5y = _slice_metrics_chrono(tdf, "2021-11-01", "2026-11-13")
    m_r3 = _slice_metrics_chrono(tdf[tdf["buy_date"] >= "2023-11-01"], "2023-11-01", "2026-11-13")
    m_26 = _slice_metrics_chrono(tdf[tdf["buy_date"] >= "2026-01-01"], "2026-01-01", "2026-11-13")
    m_07 = _slice_metrics_chrono(tdf[tdf["buy_date"] >= "2026-07-01"], "2026-07-01", "2026-11-13")
    m_10 = _slice_metrics_chrono(tdf[tdf["buy_date"] >= "2026-10-01"], "2026-10-01", "2026-11-13")
    
    print(f"门槛 >={th:3d} | 5Y:{m_5y['single_n']:3d}b WR={m_5y['wr']:4.1f}% PO={m_5y['payoff']:4.2f} NAV={m_5y['single_nav']:6.1f}x MDD={m_5y['single_mdd_pct']:4.1f}% | 3Y:{m_r3['single_n']:2d}b {m_r3['single_nav']:5.1f}x | 26年:{m_26['single_n']:2d}b {m_26['single_nav']:4.2f}x | 7月起:{m_07['single_n']:2d}b {m_07['single_nav']:4.2f}x | 10月起:{m_10['single_n']:2d}b {m_10['single_nav']:4.2f}x")

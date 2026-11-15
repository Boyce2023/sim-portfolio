#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
step1_factor_diagnosis_v34_universe.py
在 V3.4 基础骨架 (mask_A = core & obc & op_ok) 底池内，深度解剖各因子在 4 个时段的表现
"""
import os, sys, pickle
import numpy as np, pandas as pd

CACHE_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/special_26q4/3to4_26q4/cache_d_and_p.pkl"
OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/special_26q4/3to4_26q4"

with open(CACHE_PATH, "rb") as f:
    pkg = pickle.load(f)

d = pkg["df"].copy()
p = pkg["p_v32"]
d["has_trade"] = [x is not None for x in p]
d["net_ret"] = [x["net_ret"] if x is not None else np.nan for x in p]
d["win"] = d["net_ret"] > 0

fst_num = pd.to_numeric(d["first_seal_time"].astype(str).str.replace(":", "").str[:4], errors="coerce").fillna(9999)
d["fst_num"] = fst_num

core = (d.is_10cm_non_st & (~d.prev_is_yizi) & d.buyable_open & (~d.has_tox_notice) & (~d.has_stock_reg))
obc = d.open_board_count >= 1
op_ok = d.open_pct.between(0.030, 0.092)
mask_A = core & obc & op_ok
d_sub = d[mask_A & d["has_trade"]].copy()

# 4 Eras
d_sub["era"] = "other"
d_sub.loc[d_sub["buy_date"] < "2026-01-01", "era"] = "1_hist_4y"
d_sub.loc[(d_sub["buy_date"] >= "2026-01-01") & (d_sub["buy_date"] < "2026-07-01"), "era"] = "2_26h1"
d_sub.loc[(d_sub["buy_date"] >= "2026-07-01") & (d_sub["buy_date"] < "2026-10-01"), "era"] = "3_26q3"
d_sub.loc[(d_sub["buy_date"] >= "2026-10-01") & (d_sub["buy_date"] <= "2026-11-13"), "era"] = "4_26q4"

print(f"V3.4 骨架内触发交易总数: {len(d_sub)}")
print(d_sub["era"].value_counts().sort_index())

factors = {
    # 1. 股价
    "F01_px_le20": d_sub["px_d3"] <= 20.0,
    "F02_px_gt32": d_sub["px_d3"] > 32.0,
    "F03_px_20_32": d_sub["px_d3"].between(20.0, 32.0),

    # 2. 空间破局 vs 高标压制
    "F04_max_b_le4": d_sub["mkt_max_board_prev"] <= 4,
    "F05_max_b_gt4": d_sub["mkt_max_board_prev"] > 4,
    "F06_max_b_ge6": d_sub["mkt_max_board_prev"] >= 6,

    # 3. 市场情绪 / 涨停家数
    "F07_mkt_zt_ge95": d_sub["mkt_zt_prev"] >= 95,
    "F08_mkt_zt_35_85": d_sub["mkt_zt_prev"].between(35, 85),
    "F09_mkt_zt_lt35": d_sub["mkt_zt_prev"] < 35,

    # 4. 同题材梯队
    "F10_plate_fb_ho_ge2_noyz": (d_sub["plate_fb_ho_cnt"] >= 2) & (d_sub["plate_fb_yz_cnt"] == 0),
    "F11_plate_fb_yz_ge1": d_sub["plate_fb_yz_cnt"] >= 1,
    "F12_plate_peers_nuke": d_sub["plate_peers_open_avg"] < -0.015,

    # 5. 席位
    "F13_lhb_lh_0": d_sub["lhb_lh_cnt"] == 0,
    "F14_lhb_lh_ge3": d_sub["lhb_lh_cnt"] >= 3,
    "F15_lhb_quant_ge1": d_sub.get("lhb_quant_cnt", 0) >= 1,
    "F16_lhb_inst_ge1": d_sub.get("lhb_inst_cnt", 0) >= 1,
    "F17_surf_yz_buy": d_sub["surf_yz_buy"].astype(bool),

    # 6. 题材热度
    "F18_p_elo_ge115": d_sub["p_elo"] >= 115.0,
    "F19_p_elo_lt115": d_sub["p_elo"] < 115.0,

    # 7. 换手率
    "F20_to_gold_95_28": d_sub["prev_to"].between(9.5, 28.0),
    "F21_to_ultra_high_gt31": d_sub["prev_to"] > 31.0,
    "F22_to_low_lt85": d_sub["prev_to"] < 8.5,
    "F22b_to_ok_85_31": d_sub["prev_to"].between(8.5, 31.0),

    # 8. 首封时间
    "F23_fst_gold_936_1030": d_sub["fst_num"].between(936, 1030),
    "F24_fst_quick_le935": d_sub["fst_num"] <= 935,
    "F25_fst_pm_ge1300": d_sub["fst_num"] >= 1300,

    # 9. 监管与地雷
    "F26_has_ex_reg": d_sub["has_ex_reg"].astype(bool),
    "F27_prev_3b_dt_0": d_sub["prev_3b_dt_cnt"] == 0,
    "F28_prev_3b_dt_ge2": d_sub["prev_3b_dt_cnt"] >= 2,

    # 10. 竞价头名与开盘涨幅
    "F29_top1_open": d_sub["is_top1_3b_open"].astype(bool),
    "F30_not_top1": ~d_sub["is_top1_3b_open"].astype(bool),
    "F31_op_pct_3_to_6": d_sub["open_pct"].between(0.030, 0.060),
    "F32_op_pct_6_to_92": d_sub["open_pct"].between(0.060, 0.092),

    # 11. 锁仓与流值
    "F33_lock_or_free_ok": (d_sub["lock_top10"] >= 45.0) | (d_sub["real_free_mcap"] >= 45.0),
    "F34_lock_and_free_bad": (d_sub["lock_top10"] < 45.0) & (d_sub["real_free_mcap"] < 45.0),

    # 12. 大盘急跌
    "F35_csi_sharp_drop": (d_sub["csi_1d_prev"] <= -0.020) | (d_sub["csi_5d_prev"] <= -0.030),

    # 13. 日历与周期
    "F36_mon_or_post_holiday": d_sub["is_post_holiday_or_mon"].astype(bool),
    "F37_fri_or_pre_holiday": d_sub["is_pre_holiday_or_fri"].astype(bool),
    "F38_jan_or_may": d_sub["buy_month"].isin([1, 5]),
}

results = []
eras = ["1_hist_4y", "2_26h1", "3_26q3", "4_26q4"]
for name, fmask in factors.items():
    row = {"name": name}
    sub = d_sub[fmask]
    row["5y_n"] = len(sub)
    row["5y_wr"] = float(sub["win"].mean() * 100) if len(sub) > 0 else np.nan
    row["5y_ret"] = float(sub["net_ret"].mean() * 100) if len(sub) > 0 else np.nan
    
    era_rets = []
    for era in eras:
        sub_e = d_sub[(d_sub["era"] == era) & fmask]
        n_e = len(sub_e)
        row[f"{era}_n"] = n_e
        if n_e > 0:
            row[f"{era}_wr"] = float(sub_e["win"].mean() * 100)
            row[f"{era}_ret"] = float(sub_e["net_ret"].mean() * 100)
            era_rets.append(row[f"{era}_ret"])
        else:
            row[f"{era}_wr"] = np.nan
            row[f"{era}_ret"] = np.nan
            era_rets.append(np.nan)
            
    sub_26h2 = d_sub[d_sub["era"].isin(["3_26q3", "4_26q4"]) & fmask]
    row["26h2_n"] = len(sub_26h2)
    row["26h2_wr"] = float(sub_26h2["win"].mean() * 100) if len(sub_26h2) > 0 else np.nan
    row["26h2_ret"] = float(sub_26h2["net_ret"].mean() * 100) if len(sub_26h2) > 0 else np.nan

    valid_w, weighted_ret = 0.0, 0.0
    for w, r in zip([1.0, 2.5, 4.5], era_rets[1:]):
        if not np.isnan(r):
            valid_w += w
            weighted_ret += w * r
    row["2026_w_ret"] = float(weighted_ret / valid_w) if valid_w > 0 else np.nan
    
    h_ret = row["1_hist_4y_ret"]
    h2_ret = row["26h2_ret"]
    if not np.isnan(h_ret) and not np.isnan(h2_ret):
        row["delta_26h2_vs_hist"] = float(h2_ret - h_ret)
        row["is_reversal"] = bool(h_ret * h2_ret < 0)
    else:
        row["delta_26h2_vs_hist"] = np.nan
        row["is_reversal"] = False
    results.append(row)

df_diag = pd.DataFrame(results)
df_diag.to_csv(f"{OUT_DIR}/factor_diagnosis_v34_universe.csv", index=False)

print("\n=== V3.4 骨架内：核心方向反转因子 (26H2 与 历史4Y 反着来) ===")
rev = df_diag[df_diag["is_reversal"] & (df_diag["26h2_n"] >= 2)].sort_values("delta_26h2_vs_hist", ascending=False)
for _, r in rev.iterrows():
    print(f"[{r['name']:25s}] 历史4Y: n={r['1_hist_4y_n']:3.0f} 均={r['1_hist_4y_ret']:+6.2f}% | 26H1: n={r['2_26h1_n']:2.0f} 均={r['2_26h1_ret']:+6.2f}% | 26Q3: n={r['3_26q3_n']:2.0f} 均={r['3_26q3_ret']:+6.2f}% | 26Q4: n={r['4_26q4_n']:2.0f} 均={r['4_26q4_ret']:+6.2f}% | 26H2: n={r['26h2_n']:2.0f} 均={r['26h2_ret']:+6.2f}% | Δ={r['delta_26h2_vs_hist']:+6.2f}%")

print("\n=== V3.4 骨架内：强化因子 (26H2 胜率/均益大幅提高) ===")
boost = df_diag[(~df_diag["is_reversal"]) & (df_diag["26h2_n"] >= 2) & (df_diag["delta_26h2_vs_hist"] >= 3.0)].sort_values("delta_26h2_vs_hist", ascending=False)
for _, r in boost.iterrows():
    print(f"[{r['name']:25s}] 历史4Y: n={r['1_hist_4y_n']:3.0f} 均={r['1_hist_4y_ret']:+6.2f}% | 26H1: n={r['2_26h1_n']:2.0f} 均={r['2_26h1_ret']:+6.2f}% | 26Q3: n={r['3_26q3_n']:2.0f} 均={r['3_26q3_ret']:+6.2f}% | 26Q4: n={r['4_26q4_n']:2.0f} 均={r['4_26q4_ret']:+6.2f}% | 26H2: n={r['26h2_n']:2.0f} 均={r['26h2_ret']:+6.2f}% | Δ={r['delta_26h2_vs_hist']:+6.2f}%")

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
step1_factor_diagnosis.py
逐因子解剖 2026 年（尤其 7 月后与 10 月后）与前四年的结构差异及「方向反转因子」
"""
import os, sys, pickle, json
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

# 4 Eras
d["era"] = "other"
d.loc[d["buy_date"] < "2026-01-01", "era"] = "1_hist_4y"
d.loc[(d["buy_date"] >= "2026-01-01") & (d["buy_date"] < "2026-07-01"), "era"] = "2_26h1"
d.loc[(d["buy_date"] >= "2026-07-01") & (d["buy_date"] < "2026-10-01"), "era"] = "3_26q3"
d.loc[(d["buy_date"] >= "2026-10-01") & (d["buy_date"] <= "2026-11-13"), "era"] = "4_26q4"

# Define Candidate Factors
factors = {
    # 1. 股价
    "F01_px_le20": d["px_d3"] <= 20.0,
    "F02_px_gt32": d["px_d3"] > 32.0,
    "F03_px_20_32": d["px_d3"].between(20.0, 32.0),

    # 2. 空间破局 vs 高标压制
    "F04_max_b_le4": d["mkt_max_board_prev"] <= 4,
    "F05_max_b_gt4": d["mkt_max_board_prev"] > 4,
    "F06_max_b_ge6": d["mkt_max_board_prev"] >= 6,

    # 3. 市场情绪 / 涨停家数
    "F07_mkt_zt_ge95": d["mkt_zt_prev"] >= 95,
    "F08_mkt_zt_35_85": d["mkt_zt_prev"].between(35, 85),
    "F09_mkt_zt_lt35": d["mkt_zt_prev"] < 35,

    # 4. 同题材梯队
    "F10_plate_fb_ho_ge2_noyz": (d["plate_fb_ho_cnt"] >= 2) & (d["plate_fb_yz_cnt"] == 0),
    "F11_plate_fb_yz_ge1": d["plate_fb_yz_cnt"] >= 1,
    "F12_plate_peers_nuke": d["plate_peers_open_avg"] < -0.015,

    # 5. 席位
    "F13_lhb_lh_0": d["lhb_lh_cnt"] == 0,
    "F14_lhb_lh_ge3": d["lhb_lh_cnt"] >= 3,
    "F15_lhb_quant_ge1": d.get("lhb_quant_cnt", 0) >= 1,
    "F16_lhb_inst_ge1": d.get("lhb_inst_cnt", 0) >= 1,
    "F17_surf_yz_buy": d["surf_yz_buy"].astype(bool),

    # 6. 题材热度
    "F18_p_elo_ge115": d["p_elo"] >= 115.0,
    "F19_p_elo_lt115": d["p_elo"] < 115.0,

    # 7. 换手率
    "F20_to_gold_95_28": d["prev_to"].between(9.5, 28.0),
    "F21_to_ultra_high_gt31": d["prev_to"] > 31.0,
    "F22_to_low_lt85": d["prev_to"] < 8.5,

    # 8. 首封时间
    "F23_fst_gold_936_1030": fst_num.between(936, 1030),
    "F24_fst_quick_le935": fst_num <= 935,
    "F25_fst_pm_ge1300": fst_num >= 1300,

    # 9. 监管与地雷
    "F26_has_ex_reg": d["has_ex_reg"].astype(bool),
    "F27_prev_3b_dt_0": d["prev_3b_dt_cnt"] == 0,
    "F28_prev_3b_dt_ge2": d["prev_3b_dt_cnt"] >= 2,

    # 10. 竞价头名与开盘涨幅
    "F29_top1_open": d["is_top1_3b_open"].astype(bool),
    "F30_not_top1": ~d["is_top1_3b_open"].astype(bool),
    "F31_op_pct_3_to_6": d["open_pct"].between(0.030, 0.060),
    "F32_op_pct_6_to_92": d["open_pct"].between(0.060, 0.092),

    # 11. 锁仓与流值
    "F33_lock_or_free_ok": (d["lock_top10"] >= 45.0) | (d["real_free_mcap"] >= 45.0),
    "F34_lock_and_free_bad": (d["lock_top10"] < 45.0) & (d["real_free_mcap"] < 45.0),

    # 12. 大盘急跌
    "F35_csi_sharp_drop": (d["csi_1d_prev"] <= -0.020) | (d["csi_5d_prev"] <= -0.030),

    # 13. 日历与周期
    "F36_mon_or_post_holiday": d["is_post_holiday_or_mon"].astype(bool),
    "F37_fri_or_pre_holiday": d["is_pre_holiday_or_fri"].astype(bool),
    "F38_jan_or_may": d["buy_month"].isin([1, 5]),
}

# Evaluate each factor on triggered trades (where trade actually occurred)
def analyze_factor_on_trades(f_mask, name):
    res = {"name": name}
    eras = ["1_hist_4y", "2_26h1", "3_26q3", "4_26q4"]
    weights = [0.0, 1.0, 2.5, 4.5] # time weights for 2026

    # Overall 5Y
    sub_5y = d[d["has_trade"] & f_mask]
    n_5y = len(sub_5y)
    if n_5y > 0:
        res["5y_n"] = n_5y
        res["5y_wr"] = float(sub_5y["win"].mean() * 100)
        res["5y_ret"] = float(sub_5y["net_ret"].mean() * 100)
        wins = sub_5y[sub_5y["net_ret"] > 0]["net_ret"]
        losses = sub_5y[sub_5y["net_ret"] <= 0]["net_ret"]
        res["5y_po"] = float(wins.mean() / abs(losses.mean())) if len(losses) > 0 and losses.mean() != 0 else 9.99
    else:
        res["5y_n"] = 0; res["5y_wr"] = 0.0; res["5y_ret"] = 0.0; res["5y_po"] = 0.0

    # Per Era
    era_rets = []
    for era in eras:
        sub_era = d[d["has_trade"] & (d["era"] == era) & f_mask]
        n_era = len(sub_era)
        res[f"{era}_n"] = n_era
        if n_era > 0:
            wr = float(sub_era["win"].mean() * 100)
            ret = float(sub_era["net_ret"].mean() * 100)
            res[f"{era}_wr"] = wr
            res[f"{era}_ret"] = ret
            era_rets.append(ret)
        else:
            res[f"{era}_wr"] = np.nan
            res[f"{era}_ret"] = np.nan
            era_rets.append(np.nan)

    # 26H2 combined (26Q3 + 26Q4)
    sub_26h2 = d[d["has_trade"] & d["era"].isin(["3_26q3", "4_26q4"]) & f_mask]
    n_26h2 = len(sub_26h2)
    res["26h2_n"] = n_26h2
    if n_26h2 > 0:
        res["26h2_wr"] = float(sub_26h2["win"].mean() * 100)
        res["26h2_ret"] = float(sub_26h2["net_ret"].mean() * 100)
    else:
        res["26h2_wr"] = np.nan; res["26h2_ret"] = np.nan

    # Time-weighted 2026 score: 1.0 * 26H1 + 2.5 * 26Q3 + 4.5 * 26Q4
    valid_w, weighted_ret = 0.0, 0.0
    for w, r in zip([1.0, 2.5, 4.5], era_rets[1:]):
        if not np.isnan(r):
            valid_w += w
            weighted_ret += w * r
    res["2026_w_ret"] = float(weighted_ret / valid_w) if valid_w > 0 else np.nan

    # Check direction delta vs 4y history
    hist_ret = res["1_hist_4y_ret"]
    h2_ret = res["26h2_ret"]
    if not np.isnan(hist_ret) and not np.isnan(h2_ret):
        res["delta_26h2_vs_hist"] = float(h2_ret - hist_ret)
        # Is reversal? (Hist < 0 but 26H2 > 0, or Hist > 0 but 26H2 < 0)
        res["is_reversal"] = (hist_ret * h2_ret < 0)
    else:
        res["delta_26h2_vs_hist"] = np.nan
        res["is_reversal"] = False

    return res

results = []
for fname, fmask in factors.items():
    results.append(analyze_factor_on_trades(fmask, fname))

df_res = pd.DataFrame(results)
df_res.to_csv(f"{OUT_DIR}/factor_diagnosis_all.csv", index=False)

print("=== 因子解剖完成，保存至 factor_diagnosis_all.csv ===")
print("\n=== 核心方向反转因子 (26H2/26Q4 与 历史前四年 方向相反) ===")
rev = df_res[df_res["is_reversal"] & (df_res["26h2_n"] >= 3)].sort_values("delta_26h2_vs_hist", ascending=False)
for _, r in rev.iterrows():
    print(f"[{r['name']:25s}] 历史4Y: n={r['1_hist_4y_n']:3.0f} 均={r['1_hist_4y_ret']:+6.2f}% | 26H1: n={r['2_26h1_n']:2.0f} 均={r['2_26h1_ret']:+6.2f}% | 26Q3: n={r['3_26q3_n']:2.0f} 均={r['3_26q3_ret']:+6.2f}% | 26Q4: n={r['4_26q4_n']:2.0f} 均={r['4_26q4_ret']:+6.2f}% | 26H2: n={r['26h2_n']:2.0f} 均={r['26h2_ret']:+6.2f}% | Δ={r['delta_26h2_vs_hist']:+6.2f}%")

print("\n=== 核心极端强化因子 (26H2/26Q4 收益显著放大) ===")
boost = df_res[(~df_res["is_reversal"]) & (df_res["26h2_n"] >= 3) & (df_res["delta_26h2_vs_hist"].abs() >= 4.0)].sort_values("delta_26h2_vs_hist", ascending=False)
for _, r in boost.iterrows():
    print(f"[{r['name']:25s}] 历史4Y: n={r['1_hist_4y_n']:3.0f} 均={r['1_hist_4y_ret']:+6.2f}% | 26H1: n={r['2_26h1_n']:2.0f} 均={r['2_26h1_ret']:+6.2f}% | 26Q3: n={r['3_26q3_n']:2.0f} 均={r['3_26q3_ret']:+6.2f}% | 26Q4: n={r['4_26q4_n']:2.0f} 均={r['4_26q4_ret']:+6.2f}% | 26H2: n={r['26h2_n']:2.0f} 均={r['26h2_ret']:+6.2f}% | Δ={r['delta_26h2_vs_hist']:+6.2f}%")

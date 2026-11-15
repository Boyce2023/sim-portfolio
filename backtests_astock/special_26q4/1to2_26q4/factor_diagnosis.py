#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
factor_diagnosis.py
================================================================================
逐因子解剖 2026 年（尤其是 7 月后与 10 月后）与历史前四年的结构差异及「方向反转因子」
================================================================================
"""

import os
import sys
import pickle
import numpy as np
import pandas as pd

CACHE_PATH = "/tmp/astock_hist_fb_v17_cache.pkl"
PRICE_LOOKUP_PATH = "/tmp/astock_price_lookup.pkl"
OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/special_26q4/1to2_26q4"
os.makedirs(OUT_DIR, exist_ok=True)

with open(CACHE_PATH, "rb") as f:
    df = pickle.load(f)

with open(PRICE_LOOKUP_PATH, "rb") as f:
    pl_data = pickle.load(f)
price_lookup = pl_data["price_lookup"]
all_dts = pl_data["all_dts"]
dt_to_idx = {d: i for i, d in enumerate(all_dts)}

# 仅保留有效可买窗口与基础过滤的样本做单因子效应检验
# 基础定义
df["gap_days"] = (pd.to_datetime(df["d2_dt"]) - pd.to_datetime(df["dt_str"])).dt.days
wk_mask = df["gap_days"] >= 3

# 划分四个时期
cond_era1 = (df["d2_dt"] >= "2021-11-01") & (df["d2_dt"] <= "2025-12-31")
cond_era2 = (df["d2_dt"] >= "2026-01-01") & (df["d2_dt"] <= "2026-06-30")
cond_era3 = (df["d2_dt"] >= "2026-07-01") & (df["d2_dt"] <= "2026-09-30")
cond_era4 = (df["d2_dt"] >= "2026-10-01") & (df["d2_dt"] <= "2026-11-13")

eras = [
    ("4Y_Hist(21-25)", cond_era1, 1.0),
    ("26H1(01-06)", cond_era2, 1.0),
    ("26Q3(07-09)", cond_era3, 2.5),
    ("26Q4(10-11)", cond_era4, 4.5),
]

# 样本子集：满足买入窗口开盘，非核按钮，非ST
base_sample = df[df["is_buyable_open"] & (~df["nuclear_halt"]) & (~df["promo_freeze"])].copy()

# 计算 D2 点火价买入且 D2 封板率 & D2 次日收益 proxy
# proxy return: (c2 / trig_p) - 1.0 if h2 >= trig_p else NaN
trig_p = np.maximum(base_sample["open"] * 1.012, base_sample["pre_c"] * 1.065) # standard
# check price lookup for d2 bar
c6_arr = base_sample["c6"].values
d2_arr = base_sample["d2_dt"].values

# 预先提取 D2 价格表现
d2_touch = np.zeros(len(base_sample), dtype=bool)
d2_zt = np.zeros(len(base_sample), dtype=bool)
d2_ret = np.zeros(len(base_sample), dtype=float)

for i, (c6, d2) in enumerate(zip(c6_arr, d2_arr)):
    b = price_lookup.get((c6, d2))
    if b:
        o, h, l, c, zt, dt, izt, iyz = b[:8]
        tp = base_sample["trig_p"].values[i] if "trig_p" in base_sample.columns else max(o * 1.012, b[3] * 1.065)
        if h >= tp and tp < zt - 0.005:
            d2_touch[i] = True
            d2_zt[i] = bool(izt)
            d2_ret[i] = (c / tp) - 1.0
        else:
            d2_ret[i] = np.nan

base_sample["d2_touch"] = d2_touch
base_sample["d2_zt_seal"] = d2_zt
base_sample["d2_day_ret"] = d2_ret

print("=" * 80)
print(f"有效基础样本数: {len(base_sample)}")
for name, cond, w in eras:
    sub = base_sample[cond[base_sample.index]]
    print(f"时期: {name:15s} 样本数: {len(sub):5d} 触及点火数: {sub['d2_touch'].sum():4d} 封二板率: {sub['d2_zt_seal'].sum()/max(1, sub['d2_touch'].sum())*100:.1f}%")
print("=" * 80)

# 定义待解剖的核心因子
factors = {
    # 1. 题材排名: 龙一 vs 龙二 vs 龙三及以后
    "Theme_Rk1": base_sample["rk_theme"] == 1,
    "Theme_Rk2": base_sample["rk_theme"] == 2,
    "Theme_Rk3_plus": base_sample["rk_theme"] >= 3,
    
    # 2. 20日超跌 vs 60日平台突破
    "Deep_DD20(dd20<=0.82)": base_sample["f_dd20_d0"] <= 0.82,
    "Mild_DD20(0.82<dd20<=0.88)": (base_sample["f_dd20_d0"] > 0.82) & (base_sample["f_dd20_d0"] <= 0.88),
    "High_Pos20(dd20>0.88)": base_sample["f_dd20_d0"] > 0.88,
    "Clean_Break60": base_sample["clean_brk60"] == 1,
    "Not_Clean_Break60": base_sample["clean_brk60"] != 1,

    # 3. 首板微观封单与开板换手
    "Tight_Seal(>=38)": base_sample["d1_seal_tightness"] >= 38.0,
    "Loose_Seal(<38)": base_sample["d1_seal_tightness"] < 38.0,
    "Open_Board_Once(open_cnt==1)": base_sample["open_board_count"] == 1,
    "Early_Seal(<=10:30)": base_sample["first_seal_time"].fillna("99:99") <= "10:30:00",

    # 4. 流通市值带
    "Mcap_18_50Y": base_sample["mcap"].between(18.0, 50.0),
    "Mcap_50_120Y": base_sample["mcap"].between(50.0, 120.0),
    "Mcap_120_220Y": base_sample["mcap"].between(120.0, 220.0),

    # 5. 竞价开盘涨幅
    "Open_Low(2.2%~4.5%)": base_sample["d2_o_pct"].between(0.022, 0.045),
    "Open_High(4.5%~7.8%)": base_sample["d2_o_pct"].between(0.045, 0.078),
    "Open_SuperHigh(>7.8%)": base_sample["d2_o_pct"] > 0.078,

    # 6. 伴生一字
    "Plate_Yizi_Ge1": base_sample["plate_d2_yizi_cnt"] >= 1,
    "Plate_Yizi_Eq0": base_sample["plate_d2_yizi_cnt"] == 0,

    # 7. 市场高潮/封板率
    "Mkt_SealRate_Gt75": base_sample["mkt_seal_rate"] > 0.75,
    "Mkt_SealRate_Le75": base_sample["mkt_seal_rate"] <= 0.75,
    "Mkt_ZT_Ge95": base_sample["mkt_zt_cnt"] >= 95,
    "Mkt_ZT_Lt95": base_sample["mkt_zt_cnt"] < 95,

    # 8. 催化与外行
    "Has_IR_PIT": base_sample["has_ir_pit"] == True,
    "Has_MA_or_Hard": (base_sample["notice_hard"] | base_sample["is_ma"]) == True,
    "Is_Dying_Pulse": base_sample["is_dying_pulse"] == True,
    "Not_Dying_Pulse": base_sample["is_dying_pulse"] == False,
}

records = []
for fname, fmask in factors.items():
    row = {"factor": fname}
    for name, cond, w in eras:
        sub = base_sample[cond[base_sample.index] & fmask]
        n_touch = sub["d2_touch"].sum()
        seal_rate = sub["d2_zt_seal"].sum() / max(1, n_touch) * 100 if n_touch > 0 else np.nan
        avg_ret = sub[sub["d2_touch"]]["d2_day_ret"].mean() * 100 if n_touch > 0 else np.nan
        row[f"{name}_N"] = int(n_touch)
        row[f"{name}_SealRate"] = round(seal_rate, 1) if pd.notna(seal_rate) else np.nan
        row[f"{name}_DayRet"] = round(avg_ret, 2) if pd.notna(avg_ret) else np.nan
    records.append(row)

res_df = pd.DataFrame(records)
print("\n【核心单因子在 4 个时期的封板率与买入日收益率表现对比】")
print(res_df.to_string(index=False))
res_df.to_csv(f"{OUT_DIR}/factor_diagnosis_table.csv", index=False, encoding="utf-8-sig")
print(f"\n✅ 诊断表已落盘: {OUT_DIR}/factor_diagnosis_table.csv")

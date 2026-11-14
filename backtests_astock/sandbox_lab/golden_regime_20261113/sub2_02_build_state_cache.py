#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""sub2_02_build_state_cache.py - 提炼 1176 个交易日纯前视镜 (T日 09:25:00 前 100% 可得) 生态特征库

严格零未来函数截断：
所有指标仅依赖 T-1 日及更早的收盘数据与交易所通知！
"""

import os, pickle
import numpy as np
import pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SRC_DIR = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113"
TARGET_DIR = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/golden_regime_20261113"
os.makedirs(TARGET_DIR, exist_ok=True)

# 载入基础设施
(all_dts, dt_to_idx, by_dt, code_bars, env_stats, holders, t_lookup, _, _, _, stock_reg, ex_reg, tox_dates, CSI_MAP, SH_MAP, SZ_MAP) = pickle.load(open(f"{SRC_DIR}/part1_cache.pkl", "rb"))

dts_5y = [d for d in all_dts if "2022-01-01" <= d <= "2026-11-12"]

# 提取全历史断板事件流
break_events = []
for d in all_dts:
    grp = by_dt[d]
    ge4 = grp[(grp["prev_streak"] >= 4) & (~grp["is_zt"])]
    for r in ge4.itertuples():
        break_events.append({
            "date": d, "code": r.c6, "name": r.name,
            "prev_streak": int(r.prev_streak), "pct": float(r.pct),
            "is_dt": bool(r.is_dt), "is_yizi_dt": bool(r.is_yizi_dt),
            "is_true_yang": bool((r.close > r.open) and (r.close > r.pre_c)),
            "open_pct": float(r.o_pct), "amplitude": float(r.h_pct - r.l_pct)
        })
df_breaks = pd.DataFrame(break_events)

# 计算每日 09:25 前纯前视镜状态
records = []
for idx_t, d in enumerate(dts_5y):
    prev_d = all_dts[dt_to_idx[d] - 1]
    
    # 1. T日盘前可见的最近断板高标微观表现 (历史累计截止 prev_d)
    past_breaks = df_breaks[df_breaks["date"] <= prev_d]
    k3 = past_breaks.tail(3)
    k5 = past_breaks.tail(5)
    
    k3_avg_pct = float(k3["pct"].mean()) if len(k3) > 0 else 0.0
    k3_dt_cnt = int(k3["is_dt"].sum()) if len(k3) > 0 else 0
    k3_yizi_cnt = int(k3["is_yizi_dt"].sum()) if len(k3) > 0 else 0
    k3_ty_cnt = int(k3["is_true_yang"].sum()) if len(k3) > 0 else 0
    
    k5_avg_pct = float(k5["pct"].mean()) if len(k5) > 0 else 0.0
    k5_dt_cnt = int(k5["is_dt"].sum()) if len(k5) > 0 else 0
    k5_yizi_cnt = int(k5["is_yizi_dt"].sum()) if len(k5) > 0 else 0
    k5_ty_cnt = int(k5["is_true_yang"].sum()) if len(k5) > 0 else 0
    
    # 2. 破局高度 (近5日及昨日最高连板)
    roll5_dts = [all_dts[dt_to_idx[d] - k] for k in range(1, 6)]
    max_b_prev1 = int(by_dt[prev_d]["streak"].max()) if len(by_dt[prev_d]) > 0 else 0
    max_b_roll5 = int(max(by_dt[pd_]["streak"].max() for pd_ in roll5_dts))
    
    # 3. 市场水位与梯队 (T-1日全天事实)
    prev_grp = by_dt[prev_d]
    prev_n_dt = int(prev_grp["is_dt"].sum())
    prev_n_zt = int(prev_grp["is_zt"].sum())
    prev_b3p = int((prev_grp["streak"] >= 3).sum())
    prev_b4p = int((prev_grp["streak"] >= 4).sum())
    
    # 4. 监管维度：交易所重点监控与监管函 (T-1日及前4日，严格在T日盘前已知)
    ex_cnt5 = sum(1 for ed in ex_reg["SH"] + ex_reg["SZ"] if 1 <= dt_to_idx[d] - dt_to_idx.get(ed, 0) <= 5)
    
    # 5. 极端末端高潮断头铡 / 熔断器 (T-1日)
    # 昨日最高板遭遇跌停或天地板大面
    prev_max_streak = prev_grp["streak"].max()
    prev_top_nuked = False
    if prev_max_streak >= 4:
        top_stocks = prev_grp[prev_grp["prev_streak"] >= 4]
        if len(top_stocks) > 0:
            if top_stocks["is_dt"].any() or (top_stocks["pct"] <= -0.07).any():
                prev_top_nuked = True
                
    # 百股涨停过热 (T-1日 n_zt >= 95 且高标放巨量或次日分歧)
    prev_overheated = (prev_n_zt >= 95)
    
    records.append({
        "date": d,
        "year": d[:4],
        "prev_date": prev_d,
        "max_b_prev1": max_b_prev1,
        "max_b_roll5": max_b_roll5,
        "k3_avg_pct": k3_avg_pct,
        "k3_dt_cnt": k3_dt_cnt,
        "k3_yizi_cnt": k3_yizi_cnt,
        "k3_ty_cnt": k3_ty_cnt,
        "k5_avg_pct": k5_avg_pct,
        "k5_dt_cnt": k5_dt_cnt,
        "k5_yizi_cnt": k5_yizi_cnt,
        "k5_ty_cnt": k5_ty_cnt,
        "prev_n_dt": prev_n_dt,
        "prev_n_zt": prev_n_zt,
        "prev_b3p": prev_b3p,
        "prev_b4p": prev_b4p,
        "ex_cnt5": ex_cnt5,
        "prev_top_nuked": prev_top_nuked,
        "prev_overheated": prev_overheated,
    })

df_state = pd.DataFrame(records)
df_state.to_parquet(f"{TARGET_DIR}/sub2_ex_ante_state.parquet")
print(f"[SUCCESS] sub2_ex_ante_state.parquet 生成完成，包含 {len(df_state)} 个交易日！")

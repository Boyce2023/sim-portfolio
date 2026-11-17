#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
严格防过拟合回测检验：星期效应（周一/周五/节后）与日历财报窗口（财报末期雷区 vs 业绩真空期 vs 自然月份）
检验标准：
1. 早期样本(2022-2023) 与 近期样本外(2024-2026) 方向必须同号一致；
2. Leave-One-Year-Out (LOYO 逐年留一交叉验证)：剔除任一年份后该因子边际依然为正；
3. 纳入 V3.3 模型后，90分标准档与98分严格档在 5Y / 去2025四年 / 2024-2026近三年 / 逐年正收益 全面优于或严控回撤。
"""
import os, sys, json
import numpy as np
import pandas as pd

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
if CUR_DIR not in sys.path:
    sys.path.insert(0, CUR_DIR)

from bt_3to4_v32_final_build import df, sim_pool
from core_3to4_5m_engine import CSI300_MAP, _slice_metrics_chrono

p_v32 = sim_pool("touch65_1130", "cut_weak", "pm1345", True, False)
df["ret"] = [x["net_ret"] if x is not None else np.nan for x in p_v32]

# 精确计算买入日与上一交易日间隔自然天数（>=3天即为周一或长假后首日！）以及卖出/次日是否跨周末（周五或节前最后一日！）
all_tdts = sorted(CSI300_MAP.keys())
td_pos = {d: i for i, d in enumerate(all_tdts)}
gap_prev, gap_next = [], []
for d in df["buy_date"]:
    idx = td_pos.get(str(d), -1)
    if idx > 0:
        gap_prev.append((pd.Timestamp(d) - pd.Timestamp(all_tdts[idx - 1])).days)
    else:
        gap_prev.append(1)
    if 0 <= idx < len(all_tdts) - 1:
        gap_next.append((pd.Timestamp(all_tdts[idx + 1]) - pd.Timestamp(d)).days)
    else:
        gap_next.append(3 if pd.Timestamp(d).weekday() == 4 else 1)

df["is_post_holiday_or_mon"] = np.array(gap_prev) >= 3   # 周一或节后首日（三连板经历周末/长假发酵）
df["is_pre_holiday_or_fri"] = np.array(gap_next) >= 3    # 周五或节前末日（四板封死后享受周末/长假发酵）
dt_s = pd.to_datetime(df["buy_date"])
df["dow"] = dt_s.dt.dayofweek + 1
df["mon"] = dt_s.dt.month
df["md"] = df["buy_date"].str[5:10]
df["yr"] = dt_s.dt.year

# 制度性日历假说：
# H_earn_mine: A股法定财报最后密集暴雷窗口 (01-15~01-31年报预告雷, 04-18~04-30年报一季报末期, 08-22~08-31中报末期, 10-20~10-30三季报末期)
df["is_earn_landmine"] = (
    df["md"].between("01-15", "01-31")
    | df["md"].between("04-18", "04-30")
    | df["md"].between("08-22", "08-31")
    | df["md"].between("10-20", "10-30")
)
# H_vacuum_gold: 财报彻底出清后的纯业绩真空主线期 (11-01~12-20 跨年真空期 + 06-01~07-25 暑期主线期)
df["is_vacuum_gold"] = df["md"].between("11-01", "12-20") | df["md"].between("06-01", "07-25")
# H_may_jan_slump: 1月与5月传统退潮/预告暴雷月
df["is_jan_or_may"] = df["mon"].isin([1, 5])
# H_midweek_tue_wed: 周二周三分歧期
df["is_tue_wed"] = df["dow"].isin([2, 3])

skel_base = (
    df["is_10cm_non_st"] & (~df["prev_is_yizi"]) & df["buyable_open"]
    & (~df["has_tox_notice"]) & (~df["has_stock_reg"])
    & (df["open_board_count"] >= 1)
    & ((df["lock_top10"] >= 45.0) | (df["real_free_mcap"] >= 45.0))
    & df["prev_to"].between(8.5, 31.0) & df["open_pct"].between(0.030, 0.092)
)
skel_v32 = skel_base & df["is_top1_3b_open"].astype(bool)

sub = df[skel_base & df["ret"].notna()].copy()
sub_early = sub[sub["buy_date"] < "2024-01-01"]
sub_late = sub[sub["buy_date"] >= "2024-01-01"]

print("=== [Step 1] 候选日历/星期因子 双期同向性 + 逐年留一(LOYO)稳定性检验 (硬骨架底池 N=177) ===")
cands = [
    ("W1.周一或节后首日(跨周末发酵)", "is_post_holiday_or_mon"),
    ("W2.周五或节前末日(跨周末孵妖)", "is_pre_holiday_or_fri"),
    ("W3.周一或周五双端(对比周二至周四)", lambda x: x["is_post_holiday_or_mon"] | x["is_pre_holiday_or_fri"]),
    ("W4.周二或周三周中分歧日", "is_tue_wed"),
    ("M1.法定财报密集暴雷末期窗", "is_earn_landmine"),
    ("M2.业绩真空主线黄金窗(6-7月+11-12月)", "is_vacuum_gold"),
    ("M3.1月或5月弱势月", "is_jan_or_may"),
    ("M4.纯11月+6月+7月三月组合", lambda x: x["mon"].isin([6, 7, 11])),
]

for label, col in cands:
    m_all = col(sub) if callable(col) else sub[col]
    m_e = col(sub_early) if callable(col) else sub_early[col]
    m_l = col(sub_late) if callable(col) else sub_late[col]
    r1, r0 = sub.loc[m_all, "ret"], sub.loc[~m_all, "ret"]
    e1, e0 = sub_early.loc[m_e, "ret"], sub_early.loc[~m_e, "ret"]
    l1, l0 = sub_late.loc[m_l, "ret"], sub_late.loc[~m_l, "ret"]
    # LOYO: in how many of the 5 leave-one-year-out folds does r1.mean() - r0.mean() keep the same sign?
    d_full = r1.mean() - r0.mean()
    loyo_same = 0
    for y in [2022, 2023, 2024, 2025, 2026]:
        sy = sub[sub["yr"] != y]
        my = col(sy) if callable(col) else sy[col]
        dy = sy.loc[my, "ret"].mean() - sy.loc[~my, "ret"].mean()
        if np.sign(dy) == np.sign(d_full):
            loyo_same += 1
    print(f"{label:34s} | 5Y(n={len(r1):2d}): WR={(r1>0).mean()*100:4.1f}%(Δ{((r1>0).mean()-(r0>0).mean())*100:+5.1f}%) 均={r1.mean()*100:+5.2f}%(Δ{d_full*100:+5.2f}%) | 22-23 Δ均={(e1.mean()-e0.mean())*100 if len(e1) and len(e0) else 0:+5.2f}% | 24-26 Δ均={(l1.mean()-l0.mean())*100 if len(l1) and len(l0) else 0:+5.2f}% | LOYO同向={loyo_same}/5")

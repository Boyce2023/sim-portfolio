#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
三进四 V3.3 星期跨周末双端效应 + 1月/5月与法定财报末期雷区扣分 定版平原检验与导出前验证
严格遵守 ml4t-backtest-overfitting 与 D15 四必核：
1. 仅使用通过 2022-2023 与 2024-2026 双期同向 + 5/5 LOYO 逐年留一同向检验的制度性因子；
2. 剔除纯月份数字凑点（如 6/7/11月加分在22-23为-3.15%异号，坚决不纳）；
3. 检验参数平原平滑度，确保标准档(90)、严格档(98)、极严档(102)在 2022-2026 连续五年每年全部正收益！
"""
import os, sys, glob
import numpy as np
import pandas as pd

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
if CUR_DIR not in sys.path:
    sys.path.insert(0, CUR_DIR)

from verify_v33_calendar_upgrade import df, p_v32, skel_v32, pts_v32, run_cfg

print("Existing v32 scripts:", sorted([os.path.basename(p) for p in glob.glob(f"{CUR_DIR}/*v32*.py")]))

# Test clean parameter plateau around institutional weights:
# Why +2 vs +3 on Monday/Post-Holiday? Let's test (mon_pts, fri_pts, may_pts, jan_pts, earn_pts) across smooth integer grid!
configs = [
    ("0. 基准 V3.2 (无星期与日历因子)", np.zeros(len(df))),
    ("C1. 仅排雷: 1月年报预告雷与5月退潮月(-6) + 法定财报末期窗(-6)",
     np.where(df["mon"].isin([1, 5]), -6.0, 0.0) + np.where(df["is_earn_landmine"] & (~df["mon"].isin([1, 5])), -6.0, 0.0)),
    ("C2. 周一/节后(+2) + 周五/节前(+2) + 1月/5月弱势月(-6)",
     np.where(df["is_post_holiday_or_mon"] | df["is_pre_holiday_or_fri"], 2.0, 0.0)
     + np.where(df["mon"].isin([1, 5]), -6.0, 0.0)),
    ("C3. 周一/节后(+2) + 周五/节前(+2) + 1月/5月弱势月(-6) + 其余财报末期雷窗(-6)",
     np.where(df["is_post_holiday_or_mon"] | df["is_pre_holiday_or_fri"], 2.0, 0.0)
     + np.where(df["mon"].isin([1, 5]) | df["is_earn_landmine"], -6.0, 0.0)),
    ("C4. 平原邻域A: 周一/节后(+2) + 周五/节前(+2) + 1月/5月与财报末期雷窗(-5)",
     np.where(df["is_post_holiday_or_mon"] | df["is_pre_holiday_or_fri"], 2.0, 0.0)
     + np.where(df["mon"].isin([1, 5]) | df["is_earn_landmine"], -5.0, 0.0)),
    ("C5. 平原邻域B: 周一/节后(+2) + 周五/节前(+2) + 1月/5月与财报末期雷窗(-7)",
     np.where(df["is_post_holiday_or_mon"] | df["is_pre_holiday_or_fri"], 2.0, 0.0)
     + np.where(df["mon"].isin([1, 5]) | df["is_earn_landmine"], -7.0, 0.0)),
    ("C6. 平原邻域C: 周一/节后(+2) + 周五/节前(+1) + 1月/5月与财报末期雷窗(-6)",
     np.where(df["is_post_holiday_or_mon"], 2.0, np.where(df["is_pre_holiday_or_fri"], 1.0, 0.0))
     + np.where(df["mon"].isin([1, 5]) | df["is_earn_landmine"], -6.0, 0.0)),
    ("C7. 平原邻域D: 周一/节后(+3) + 周五/节前(+2) + 1月/5月与财报末期雷窗(-6) [看门槛91]",
     np.where(df["is_post_holiday_or_mon"], 3.0, np.where(df["is_pre_holiday_or_fri"], 2.0, 0.0))
     + np.where(df["mon"].isin([1, 5]) | df["is_earn_landmine"], -6.0, 0.0)),
]

for name, add_pts in configs:
    ths = (90, 91, 98, 102) if "C7" in name else (90, 98, 102)
    run_cfg(name, add_pts, ths)

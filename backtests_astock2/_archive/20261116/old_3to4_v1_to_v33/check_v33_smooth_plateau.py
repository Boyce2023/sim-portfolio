#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
import numpy as np
from verify_v33_calendar_upgrade import df, run_cfg

for pen in [-3.0, -4.0, -5.0, -6.0]:
    run_cfg(f"P_mon2_pen{int(pen)}: 周一/节后首日(+2) + 1月与5月弱势月({int(pen)})",
            np.where(df["is_post_holiday_or_mon"], 2.0, 0.0) + np.where(df["mon"].isin([1, 5]), pen, 0.0), (90, 98, 102))

for pen in [-4.0, -5.0]:
    run_cfg(f"P_mon2_friWarm2_pen{int(pen)}: 周一/节后(+2) + 周五涨停温热35-85(+2) + 1月与5月({int(pen)})",
            np.where(df["is_post_holiday_or_mon"], 2.0, np.where(df["is_pre_holiday_or_fri"] & df["mkt_zt_prev"].between(35, 85), 2.0, 0.0))
            + np.where(df["mon"].isin([1, 5]), pen, 0.0), (90, 98, 102))

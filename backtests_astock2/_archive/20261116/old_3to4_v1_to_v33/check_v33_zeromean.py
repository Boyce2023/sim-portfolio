#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
import numpy as np, pandas as pd
from verify_v33_calendar_upgrade import df, p_v32, skel_v32, pts_v32, run_cfg

# Zero-mean centered weekday factor (Mon/post-holiday +4, Fri/pre-holiday +3, Tue/Wed/Thu -2 -> weekly mean +0.2, zero threshold drift!)
w_zero = np.where(df["is_post_holiday_or_mon"], 4.0, np.where(df["is_pre_holiday_or_fri"], 3.0, -2.0))
w_zero_soft = np.where(df["is_post_holiday_or_mon"], 3.0, np.where(df["is_pre_holiday_or_fri"], 3.0, -2.0))
c_earn6 = np.where(df["is_earn_landmine"], -6.0, 0.0)
c_earn8 = np.where(df["is_earn_landmine"], -8.0, 0.0)
c_may6 = np.where(df["mon"] == 5, -6.0, 0.0)
c_jm = np.where(df["mon"] == 5, -6.0, np.where(df["mon"] == 1, -4.0, 0.0))

run_cfg("G1. 零均值星期(周一+4/周五+3/周中-2)", w_zero, (90, 92, 98, 102))
run_cfg("G2. 零均值星期(+4/+3/-2) + 财报末期(-8) + 5月(-6)", w_zero + c_earn8 + c_may6, (90, 92, 98, 102))
run_cfg("G3. 零均值星期(+4/+3/-2) + 财报末期(-6) + 5月(-6)/1月(-4)", w_zero + c_earn6 + c_jm, (90, 92, 98, 102))
run_cfg("G4. 零均值星期(+3/+3/-2) + 财报末期(-8) + 5月(-6)/1月(-4)", w_zero_soft + c_earn8 + c_jm, (90, 92, 98, 102))
run_cfg("G5. D方案直接看 92/94/98/102 分阶梯",
        np.where(df["is_post_holiday_or_mon"], 4.0, np.where(df["is_pre_holiday_or_fri"], 3.0, 0.0)) + c_earn8 + c_jm,
        (90, 92, 94, 98, 102))
